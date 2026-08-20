#!/usr/bin/env python3
"""Bonus C2 - KV cache quantization: f16 vs q8_0.

Three measurements, all on a real llama-server started by this script:

  --rss-sweep   RSS of the server process across a ctx ladder, both cache types.
                This is the "watch RSS as --ctx-size grows" part of the challenge.
  --measure     At one ctx: prefill tok/s, decode tok/s, and a 10-prompt
                auto-graded eval (arithmetic + JSON extraction).

Exactly one llama-server is alive at a time: the script refuses to start if it
finds a stray one, and kills its own child before returning.

    .venv\\Scripts\\python.exe bonus\\kv-cache-quant.py --rss-sweep
    .venv\\Scripts\\python.exe bonus\\kv-cache-quant.py --measure --ctx 65536
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import subprocess
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "lib"))
import labkit  # noqa: E402

import httpx      # noqa: E402
import psutil     # noqa: E402

PORT = 8080
LOG = labkit.repo_root() / "benchmarks" / ".kv-quant-server.log"
OUT = labkit.repo_root() / "benchmarks" / "bonus-c2-kv-cache-quant.json"

# ── shared context ────────────────────────────────────────────
# One document in front of every eval prompt so each request actually fills KV
# cache instead of measuring a 30-token prompt. The distractor numbers are there
# on purpose: the model has to attend back into the context, which is exactly the
# path a quantized KV cache degrades.
DOC = """INTERNAL OPS LOG - MERIDIAN LOGISTICS - WEEK 41

Fleet north operated 214 delivery runs. Fleet south operated 138 delivery runs.
Fleet east operated 97 delivery runs and was taken offline on day 5 for servicing.
Depot A holds 1240 pallets. Depot B holds 860 pallets. Depot C holds 415 pallets.
Fuel cost per run north was 37 dollars, south 42 dollars, east 51 dollars.
Driver headcount: north 46, south 29, east 18.
Incident reports filed: north 3, south 7, east 2.
On-time rate: north 0.94, south 0.88, east 0.79.

Contract notes. The Ashford account renews on 2026-03-14 and is billed monthly at
18500 dollars. The Bellweather account renews on 2026-07-01 and is billed
quarterly at 47200 dollars. The Corvid account lapsed on 2025-11-30 and is not
billed. The Ashford account contact is Priya Raman, title Operations Director,
based in Leeds. The Bellweather contact is Tomas Vogel, title Head of Supply,
based in Hamburg.

Maintenance ledger. Vehicle T-118 logged 4 service events costing 220, 185, 640
and 95 dollars. Vehicle T-204 logged 2 service events costing 1310 and 460
dollars. Vehicle T-333 logged 1 service event costing 75 dollars. Vehicles are
retired after 12 service events or 400000 kilometres, whichever comes first.

Warehouse policy. Pallets over 900 kilograms require a two-person lift. Pallets
tagged HAZ require a supervisor signature. Night shift runs 22:00 to 06:00 and
carries a 15 percent pay differential. Overtime is authorised only when the
on-time rate for a fleet drops below 0.85 in a given week.

Staffing addendum. The Leeds site added 12 seasonal staff. The Hamburg site added
7 seasonal staff. The Lyon site added 0 seasonal staff and is scheduled to close.
Seasonal staff are paid 14 dollars per hour and work 6 hour shifts.
"""

SYSTEM = ("You are a precise data extraction assistant. Answer using only the "
          "MERIDIAN LOGISTICS document. Follow the output format exactly. "
          "Do not explain.")

# Neutral padding placed in front of the document. It carries no numbers or names
# that collide with the questions, so it cannot change the correct answer -- its
# only job is to push each request deep enough into the KV cache that attention
# actually has to read quantized K/V rather than a handful of cells.
PAD = """APPENDIX - GENERAL TERMS (NON-BINDING BOILERPLATE)

This appendix restates the standard operating language used across all regional
handbooks. It introduces no new obligations and supersedes nothing. Where the
appendix and an operational schedule disagree, the operational schedule governs.
Terms defined in the master agreement retain their defined meaning here. Headings
are for convenience and do not affect interpretation. References to a party
include that party's permitted successors. Words importing the singular include
the plural and the reverse. A reference to writing includes electronic form
unless the context requires otherwise. Nothing in this appendix creates a
partnership, joint venture or agency relationship between the parties. The
failure of either party to enforce a provision is not a waiver of that provision
or of any other provision. If a provision is held unenforceable, the remainder
continues in force and the parties will negotiate a replacement that reflects the
original intent as closely as the law allows. Notices take effect on receipt when
delivered by hand and on the next working day when sent electronically. Each
party bears its own costs in connection with the negotiation of this appendix.
This appendix may be executed in counterparts, each of which is an original and
all of which together constitute one instrument. The appendix is governed by the
law of the place of the receiving depot and the parties submit to the
non-exclusive jurisdiction of its courts. Continuity of service obligations
survive termination for the period stated in the master agreement. Records are
retained in accordance with the retention schedule published by the compliance
function and are made available on reasonable notice during working hours.
"""

# ── the 10-prompt eval ────────────────────────────────────────
# 5 arithmetic (grade = last integer in the reply), 5 JSON (grade = parsed dict).
EVAL = [
    {"id": "a1", "kind": "num",
     "q": "How many delivery runs did fleet north and fleet south perform in total? "
          "Reply with only the number.",
     "want": 352},
    {"id": "a2", "kind": "num",
     "q": "What is the total number of pallets across depot A, depot B and depot C? "
          "Reply with only the number.",
     "want": 2515},
    {"id": "a3", "kind": "num",
     "q": "What is the total cost of the 4 service events logged for vehicle T-118? "
          "Reply with only the number.",
     "want": 1140},
    {"id": "a4", "kind": "num",
     "q": "What was the total fuel cost for fleet south, that is runs multiplied by "
          "fuel cost per run? Reply with only the number.",
     "want": 5796},
    {"id": "a5", "kind": "num",
     "q": "How many seasonal staff were added across the Leeds, Hamburg and Lyon "
          "sites in total? Reply with only the number.",
     "want": 19},
    {"id": "j1", "kind": "json",
     "q": 'Extract the Ashford account. Reply with only JSON: '
          '{"renews": "<date>", "amount": <number>, "cadence": "<monthly or quarterly>"}',
     "want": {"renews": "2026-03-14", "amount": 18500, "cadence": "monthly"}},
    {"id": "j2", "kind": "json",
     "q": 'Extract the Bellweather contact. Reply with only JSON: '
          '{"name": "<name>", "title": "<title>", "city": "<city>"}',
     "want": {"name": "Tomas Vogel", "title": "Head of Supply", "city": "Hamburg"}},
    {"id": "j3", "kind": "json",
     "q": 'Extract fleet east. Reply with only JSON: '
          '{"runs": <number>, "drivers": <number>, "on_time": <number>}',
     "want": {"runs": 97, "drivers": 18, "on_time": 0.79}},
    {"id": "j4", "kind": "json",
     "q": 'Extract the night shift policy. Reply with only JSON: '
          '{"start": "<HH:MM>", "end": "<HH:MM>", "differential_percent": <number>}',
     "want": {"start": "22:00", "end": "06:00", "differential_percent": 15}},
    {"id": "j5", "kind": "json",
     "q": 'Extract the vehicle retirement rule. Reply with only JSON: '
          '{"max_service_events": <number>, "max_km": <number>}',
     "want": {"max_service_events": 12, "max_km": 400000}},
]


# ── grading ───────────────────────────────────────────────────

def grade_num(reply: str, want: int) -> tuple[bool, str]:
    nums = re.findall(r"-?\d[\d,]*", reply.replace(" ", ""))
    if not nums:
        return False, "no number in reply"
    got = nums[-1].replace(",", "")
    try:
        return int(got) == want, got
    except ValueError:
        return False, got


def grade_json(reply: str, want: dict) -> tuple[bool, str]:
    m = re.search(r"\{.*\}", reply, re.S)
    if not m:
        return False, "no json object in reply"
    try:
        got = json.loads(m.group(0))
    except ValueError:
        return False, "unparseable json"
    for k, v in want.items():
        if k not in got:
            return False, f"missing key {k}"
        g = got[k]
        if isinstance(v, str):
            if str(g).strip().lower() != v.lower():
                return False, f"{k}={g!r}"
        else:
            try:
                if abs(float(g) - float(v)) > 1e-6:
                    return False, f"{k}={g!r}"
            except (TypeError, ValueError):
                return False, f"{k}={g!r}"
    return True, "ok"


def grade(item: dict, reply: str) -> tuple[bool, str]:
    return (grade_num if item["kind"] == "num" else grade_json)(reply, item["want"])


# ── process control ───────────────────────────────────────────

def strays() -> list[psutil.Process]:
    out = []
    for p in psutil.process_iter(["name"]):
        try:
            if (p.info["name"] or "").lower() == "llama-server.exe":
                out.append(p)
        except psutil.Error:
            pass
    return out


def require_clean() -> None:
    s = strays()
    if s:
        labkit.die(f"{len(s)} llama-server process(es) already running: "
                   f"{[p.pid for p in s]}",
                   "Kill them before measuring -- one server at a time is the whole point.")


class Server:
    """One llama-server, started and killed by us, with RSS sampling."""

    def __init__(self, ctx: int, cache_type: str | None):
        self.ctx = ctx
        self.cache_type = cache_type or "f16"
        self.proc: subprocess.Popen | None = None
        self.ps: psutil.Process | None = None

    def __enter__(self) -> "Server":
        require_clean()
        os.environ["LAB_N_CTX"] = str(self.ctx)
        model = str(labkit.repo_root() / labkit.load_active()["primary_model"])
        extra = ["-lv", "6"]
        if self.cache_type != "f16":
            extra += ["--cache-type-k", self.cache_type,
                      "--cache-type-v", self.cache_type]
        self.cmd = labkit.server_cmd(model, port=PORT, extra=extra)
        self.log = open(LOG, "w", encoding="utf-8", errors="replace")
        t0 = time.time()
        self.proc = subprocess.Popen(self.cmd, stdout=self.log,
                                     stderr=subprocess.STDOUT)
        if not labkit.wait_healthy(PORT, timeout=600, proc=self.proc):
            self.__exit__(None, None, None)
            labkit.die(f"server failed to become healthy (ctx={self.ctx}, "
                       f"cache={self.cache_type}); see {LOG}")
        self.load_s = time.time() - t0
        self.ps = psutil.Process(self.proc.pid)
        alive = strays()
        if len(alive) != 1:
            self.__exit__(None, None, None)
            labkit.die(f"expected exactly 1 llama-server, found {len(alive)}")
        return self

    def __exit__(self, *exc) -> None:
        if self.proc is not None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=30)
        try:
            self.log.close()
        except Exception:
            pass
        for _ in range(20):
            if not strays():
                break
            time.sleep(0.5)

    # -- observations -------------------------------------------------
    def rss_mb(self) -> float:
        return self.ps.memory_info().rss / 2**20

    def peak_mb(self) -> float:
        mi = self.ps.memory_info()
        return getattr(mi, "peak_wset", mi.rss) / 2**20

    def props_ctx(self) -> int:
        r = httpx.get(f"http://127.0.0.1:{PORT}/props", timeout=30).json()
        return int(r["default_generation_settings"]["n_ctx"])

    def kv_alloc(self) -> dict:
        """KV cache sizes llama.cpp reports for the context it actually built."""
        text = LOG.read_text(encoding="utf-8", errors="replace")
        rows = re.findall(
            r"llama_kv_cache: size =\s*([0-9.]+) MiB \(\s*(\d+) cells,\s*(\d+) layers",
            text)
        buffers = [float(x) for x in re.findall(
            r"llama_kv_cache:\s+CPU KV buffer size =\s*([0-9.]+) MiB", text)]
        # The loader runs a dry sizing pass first (buffer size 0.00); the real
        # allocation is the pass whose CPU KV buffer is non-zero. Take the last
        # len(real) rows so we report what was actually committed.
        real = [b for b in buffers if b > 0]
        tail = rows[-len(real):] if real else rows
        return {
            "caches": [{"mib": float(m), "cells": int(c), "layers": int(l)}
                       for m, c, l in tail],
            "total_mib": round(sum(float(m) for m, _, _ in tail), 2),
        }

    def chat(self, messages: list[dict], max_tokens: int) -> dict:
        payload = {
            "model": "local", "messages": messages,
            "max_tokens": max_tokens,
            "temperature": 0.0, "top_k": 1, "top_p": 1.0, "seed": 20260820,
            "cache_prompt": False,      # no prefix reuse -> prefill is really measured
        }
        r = httpx.post(f"http://127.0.0.1:{PORT}/v1/chat/completions",
                       json=payload, timeout=1800.0)
        r.raise_for_status()
        return r.json()

    def warmup(self) -> None:
        """Decode a few tokens so every mmap'd weight page is resident.

        Without this, RSS is a measure of how much of the model the OS happened to
        page in, not of the KV cache -- and the two configs would not be comparable.
        """
        self.chat([{"role": "user", "content": "Say OK."}], max_tokens=24)


# ── measurements ──────────────────────────────────────────────

def rss_sweep(ctxs: list[int], types: list[str]) -> list[dict]:
    rows = []
    for ctx in ctxs:
        for ct in types:
            with Server(ctx, ct) as s:
                after_load = s.rss_mb()
                s.warmup()
                row = {
                    "ctx_total": ctx,
                    "ctx_per_slot": s.props_ctx(),
                    "cache_type": ct,
                    "rss_after_load_mb": round(after_load, 1),
                    "rss_after_warmup_mb": round(s.rss_mb(), 1),
                    "peak_wset_mb": round(s.peak_mb(), 1),
                    "load_s": round(s.load_s, 1),
                    "kv": s.kv_alloc(),
                }
            rows.append(row)
            print(f"  ctx={ctx:>6} ({row['ctx_per_slot']}/slot)  {ct:<5} "
                  f"KV={row['kv']['total_mib']:>7.2f} MiB  "
                  f"RSS load={row['rss_after_load_mb']:>7.1f} "
                  f"warm={row['rss_after_warmup_mb']:>7.1f} "
                  f"peak={row['peak_wset_mb']:>7.1f} MB", flush=True)
    return rows


def latency_and_quality(ctx: int, ct: str, reps: int,
                        lat_pad: int, eval_pad: int) -> dict:
    with Server(ctx, ct) as s:
        ctx_slot = s.props_ctx()
        s.warmup()
        rss = s.rss_mb()
        kv = s.kv_alloc()

        # -- latency: a deliberately long prompt, so prefill and the attention
        #    reads during decode both touch a KV cache worth measuring
        lat = []
        for i in range(reps):
            body = s.chat([{"role": "system", "content": SYSTEM},
                           {"role": "user", "content": PAD * lat_pad + DOC +
                                                       "\nSummarise the fleet "
                                                       "table in one sentence."}],
                          max_tokens=64)
            t = body["timings"]
            lat.append({"prompt_n": t["prompt_n"], "prefill_tps": t["prompt_per_second"],
                        "predicted_n": t["predicted_n"],
                        "decode_tps": t["predicted_per_second"],
                        "prompt_ms": t["prompt_ms"], "predicted_ms": t["predicted_ms"]})
            print(f"    rep {i+1}/{reps}: prefill {t['prompt_n']:.0f} tok @ "
                  f"{t['prompt_per_second']:.2f} tok/s | decode "
                  f"{t['predicted_n']:.0f} tok @ {t['predicted_per_second']:.2f} tok/s",
                  flush=True)

        # -- quality
        results = []
        for item in EVAL:
            body = s.chat([{"role": "system", "content": SYSTEM},
                           {"role": "user", "content": PAD * eval_pad + DOC +
                                                       "\n" + item["q"]}],
                          max_tokens=160)
            reply = body["choices"][0]["message"]["content"].strip()
            ok, detail = grade(item, reply)
            results.append({"id": item["id"], "kind": item["kind"], "ok": ok,
                            "detail": detail, "reply": reply[:400],
                            "prompt_n": body["timings"]["prompt_n"]})
            print(f"    {item['id']:<3} {'PASS' if ok else 'FAIL'}  {detail}", flush=True)

        rss_end = s.rss_mb()
        peak = s.peak_mb()

    def med(key):
        vals = sorted(x[key] for x in lat)
        return vals[len(vals) // 2]

    return {
        "ctx_total": ctx, "ctx_per_slot": ctx_slot, "cache_type": ct,
        "kv": kv,
        "rss_after_warmup_mb": round(rss, 1),
        "rss_after_eval_mb": round(rss_end, 1),
        "peak_wset_mb": round(peak, 1),
        "latency": {"reps": lat,
                    "prefill_tps_median": round(med("prefill_tps"), 2),
                    "decode_tps_median": round(med("decode_tps"), 2),
                    "prompt_n": lat[0]["prompt_n"]},
        "quality": {"passed": sum(1 for r in results if r["ok"]),
                    "total": len(results), "results": results,
                    "prompt_n_median": sorted(r["prompt_n"] for r in results)[
                        len(results) // 2]},
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rss-sweep", action="store_true")
    ap.add_argument("--measure", action="store_true")
    ap.add_argument("--ctx", type=int, default=65536)
    ap.add_argument("--ctxs", default="2048,16384,65536,131072")
    ap.add_argument("--types", default="f16,q8_0")
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--lat-pad", type=int, default=22,
                    help="copies of PAD in front of the latency prompt")
    ap.add_argument("--eval-pad", type=int, default=7,
                    help="copies of PAD in front of each eval prompt")
    ap.add_argument("--tag", default="")
    args = ap.parse_args()

    if "LAB_N_GPU_LAYERS" not in os.environ:
        labkit.die("Set LAB_N_GPU_LAYERS explicitly.",
                   "This box reports a CUDA device, so labkit would default to "
                   "-ngl 99. The rest of the lab is ngl=0; run with "
                   "LAB_N_GPU_LAYERS=0 so this comparison matches it.")

    types = args.types.split(",")
    payload: dict = {"host": labkit.host_tag(), "build": labkit.LLAMA_CPP_BUILD,
                     "ngl": labkit.n_gpu_layers(), "threads": labkit.threads(),
                     "parallel": labkit.parallel_slots()}

    if args.rss_sweep:
        labkit.banner("C2 - RSS across the ctx ladder")
        payload["rss_sweep"] = rss_sweep([int(x) for x in args.ctxs.split(",")], types)

    if args.measure:
        labkit.banner(f"C2 - latency + quality at ctx={args.ctx}")
        payload["measure"] = []
        for ct in types:
            print(f"\n  === cache-type {ct} ===", flush=True)
            payload["measure"].append(
                latency_and_quality(args.ctx, ct, args.reps,
                                    args.lat_pad, args.eval_pad))

    name = OUT if not args.tag else OUT.with_name(f"{OUT.stem}-{args.tag}.json")
    prev = json.loads(name.read_text()) if name.exists() else {}
    prev.update(payload)
    name.write_text(json.dumps(prev, indent=2))
    print(f"\nwrote {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
