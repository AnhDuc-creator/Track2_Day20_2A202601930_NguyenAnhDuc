# Reflection — Day 20 Lab (Personal Report)

> **Đây là báo cáo cá nhân.** Số liệu của bạn **không** so sánh được với bạn cùng lớp
> — chỉ so **before vs after trên chính máy bạn**.

**Họ Tên:** Nguyễn Anh Đức (2A202601930)
**Cohort:** 4
**Ngày submit:** 2026-08-20

---

## 1. Hardware & runtime _(rubric 1, 2 — 10 điểm)_

- **OS:** Windows 10 (AMD64)
- **CPU:** Intel Core i5-1035G1 @ 1.00GHz (Ice Lake, 15W)
- **Cores:** 4 physical / 8 logical
- **CPU extensions:** AVX2 + AVX-512 (Ice Lake; `detect-hardware.py` không báo cáo trường này nên đây là từ spec chip)
- **RAM:** 23.8 GB
- **Accelerator:** NVIDIA GeForce MX230 (2048 MiB) + Vulkan — phát hiện được nhưng **không dùng**, toàn bộ lab chạy `ngl=0`
- **llama.cpp asset đã tải:** llama-b10488-bin-win-cuda-12.4-x64.zip + cudart-llama-bin-win-cuda-12.4-x64.zip
- **Model đã dùng:** Gemma 4 E2B (`LAB_MODEL=gemma4-e2b`)
- **Quantization:** UD-Q4_K_XL (primary) + UD-Q2_K_XL (compare)

**Chạy ở đâu:** laptop của tôi.

**Setup story:** Hai thay đổi. Thứ nhất, `lab.ps1` là UTF-8 không BOM nên Windows
PowerShell 5.1 giải mã sai dấu gạch dài ở dòng 48, làm hỏng parse cả khối `switch`;
tôi ghi lại file kèm BOM là chạy được. Thứ hai, MX230 chỉ có 2048 MiB VRAM còn model
Q4 nặng 2.97 GB nên không nhét vừa; tôi đặt `LAB_N_GPU_LAYERS=0` và chạy toàn bộ trên
CPU. `nvidia-smi` xác nhận 0 MiB VRAM được dùng trong suốt lab.

---

## 2. Đo lường _(rubric 3, 4, 5 — 20 điểm)_

| Quantization | Size (GB) | Load (ms) | TTFT P50/P95 (ms) | TPOT P50/P95 (ms) |  E2E P50/P95/P99 (ms) | Decode (tok/s) |
| ------------ | --------: | --------: | ----------------: | ----------------: | --------------------: | -------------: |
| UD-Q4_K_XL   |      2.97 |      8685 |       2074 / 2777 |     129.1 / 164.2 | 10085 / 12361 / 12361 |            7.7 |
| UD-Q2_K_XL   |      2.24 |      5995 |       2012 / 3855 |     125.4 / 220.5 |  9824 / 17747 / 17747 |            8.0 |

**Quan sát:** 2-bit chỉ nhanh hơn 1.04x nhưng tệ hơn rõ ở đuôi: TTFT P95 3855 so với
2777 ms, TPOT P95 220.5 so với 164.2 ms. Với 23.8 GB RAM, tiết kiệm 0.73 GB không giải
quyết gì. Giữ 4-bit. Tôi chưa chạy đối chiếu chất lượng câu trả lời giữa hai bản, nên
kết luận này dựa hoàn toàn trên latency.

---

## 3. Serving under load _(rubric 8, 9, 10 — 20 điểm)_

| Users |  RPS | P50 (ms) | P95 (ms) | P99 (ms) | Eff. concurrency | Failures |
| ----: | ---: | -------: | -------: | -------: | ---------------: | -------: |
|    10 | 0.10 |    36000 |    51000 |    51000 |              3.7 |     0.0% |
|    50 | 0.18 |    44000 |    44000 |    44000 |              6.2 |     0.0% |

- **Offered load tăng 5x, throughput thực tăng:** 1.82x
- **P95 tăng:** 0.86x (tức giảm — xem giải thích bên dưới)
- **Effective concurrency ở 50 users:** 6.2 so với `--parallel` = 4 slots

**Peak `llamacpp:n_busy_slots_per_decode`:** 3.51 / 4 slots (88%), kèm
`requests_deferred = 21`

**Saturation reading:** Bão hòa dưới 50 users, nhưng bằng chứng nằm ở gauge của server
chứ không ở bảng locust. `requests_deferred = 21` nghĩa là 21 request đến khi cả 4 slot
đều bận và bị xếp hàng; `busy_slots = 3.51/4` xác nhận chúng chờ vì hết slot thật chứ
không phải vì scheduler bỏ trống tài nguyên. Bảng locust không dùng được: chỉ 5 và 8
request hoàn thành trong 60 giây, nên P50 = P95 = P99 ở lần 50 users, và P95 lại _thấp
hơn_ ở 50 users so với 10 users. Locust chỉ tính request đã xong, nên những request
chậm nhất còn nằm trong hàng đợi bị loại khỏi thống kê, kéo latency đo được xuống và
làm effective concurrency 6.2 thành con số dưới thực tế. Số dùng được từ bảng là hàng
throughput: 5x tải chào chỉ cho 1.82x throughput, tức plateau. Để nâng goodput@SLO tôi
sẽ **giảm `--parallel` từ 4 xuống 2** trước tiên, vì bottleneck là băng thông bộ nhớ
chứ không phải số slot — 4 slot chia nhau một kênh nhớ đã bão hòa thì mọi request đều
chậm và đều trượt SLO, còn 2 slot cho mỗi request gần gấp đôi tốc độ decode nên một
phần về đích kịp hạn.

---

## 4. Integration _(rubric 12, 13 — 15 điểm)_

| Day                   | Piece                    | Real hay stub?            |
| --------------------- | ------------------------ | ------------------------- |
| N16 Cloud/IaC         | không có cluster/Compose | Stub — localhost          |
| N17 Data pipeline     | không có DAG             | Stub — TOY_DOCS in-memory |
| N18 Lakehouse         | không có Delta/Iceberg   | Stub — dict trong bộ nhớ  |
| N19 Vector + features | không có vector index    | Stub — keyword overlap    |
| N20 Serving           | `llama-server`           | real                      |

**Latency split** (mean của 3 query):

- embed: 0.0 ms
- retrieve: 0.1 ms
- llm: 6555.7 ms
- **stage chiếm nhiều nhất:** llm (100.0% của total)

**Reflection:** Đúng kỳ vọng, nhưng 100% này phần lớn do embed và retrieve đều là stub.
Điểm đáng chú ý nằm bên trong stage llm: prefill 150 token mất 2274 ms còn decode 30
token mất 2714 ms, tức prefill đã chiếm khoảng một phần ba độ trễ dù prompt còn ngắn.
Muốn giảm 2x, tôi tấn công prefill trước bằng prompt caching và cắt ngân sách context,
vì decode 11 tok/s là trần băng thông CPU, không tối ưu phần mềm nào vượt được.

---

## 5. The single change that mattered most _(rubric 11 — 10 điểm)_

**Change:** thread count `-t`, từ 1 lên 4 (đo bằng `llama-bench`, metric tg128, `ngl=0`)

```
before:  5.3 tok/s  (-t 1)
after:   10.4 tok/s (-t 4)
speedup: 1.95x
```

**Tại sao nó work:**

Từ 1 lên 4 thread, mỗi thread mang theo một nhân vật lý với đơn vị vector và đường dẫn
cache riêng, nên throughput tăng thật. Nhưng mức tăng đã dưới tuyến tính rõ rệt: gấp 4
lần thread chỉ cho 1.95 lần throughput. Đó là dấu hiệu decode chạm trần băng thông bộ
nhớ trước khi hết nhân — model 2.97 GB phải được đọc lại toàn bộ cho mỗi token sinh ra,
và i5-1035G1 là chip 15W với LPDDR4X hai kênh, nên kênh nhớ bão hòa sớm hơn compute.
Điều này khớp với kết quả ở §2: giảm model từ 4-bit xuống 2-bit, tức bớt 25% số byte
phải đọc, chỉ đem lại 4% decode nhanh hơn, vì k-quant 2-bit cần thêm thao tác giải nén
cho mỗi byte đọc vào và ăn lại gần hết phần lợi. Cùng một trần băng thông giải thích cả
hai quan sát.

Phần ngược kỳ vọng đáng nói hơn. Curve **không** tiếp tục leo qua số nhân vật lý: `-t 8`
cho 10.0 tok/s (thấp hơn `-t 4` 3%) và `-t 16` cho 7.6 tok/s (thấp hơn 27%). i5-1035G1
có 4 nhân vật lý và 8 luồng logic, nên 4 thread thêm vào ở mốc 8 chỉ là các luồng SMT
dùng chung đơn vị AVX-512, L1 và L2 của cùng một nhân — chúng không mang thêm băng
thông, chỉ chia nhỏ tài nguyên sẵn có, nên hòa vốn là kết quả hợp lý cho workload đã bị
chặn bởi bộ nhớ. Ở mốc 16, 16 thread tranh 8 luồng logic buộc OS preempt liên tục; mỗi
context switch làm mất working set trong L2, và vì mọi thread đều đang stream cùng một
khối trọng số nên chúng đá lẫn nhau ra khỏi cache thay vì chia sẻ.

Cần nói thẳng một điều: mặc định của lab (`-t` = số nhân vật lý = 4) **đã** trùng đúng
điểm tối ưu, nên tỉ số so với mặc định là 1.00x. Giá trị của sweep này vì vậy mang tính
xác nhận chứ không phải cải thiện — nó chứng minh rằng tăng thread không phải hướng đi
trên máy này, và chỉ ra rằng knob thật sự còn lại là `--parallel` ở §3. Con số có ý
nghĩa vận hành nhất là spread 1.37x giữa `-t 16` và `-t 4`: đặt sai thread count theo
hướng quá nhiều vẫn mất một phần tư throughput, và đó là lỗi dễ mắc vì `-t 16` trông
như "dùng hết máy".

---

## 6. Bonus _(optional — tối đa 20 điểm)_

> Bỏ trống nếu không làm. Xem `bonus/README.md`. Đừng làm hết — **một** finding sâu
> ăn điểm hơn năm bảng nông.

**Đã làm:** _<B1 build-compare / B2 sweep nào / B4 challenge nào / B5 lựa chọn nào>_

**Numbers:**

```
before:  <số>
after:   <số>
speedup: <X.Y>×
```

**Điều này nói lên gì mà deck chưa nói:**

_(để trống nếu bạn không làm phần này)_

---

## 7. Điều làm bạn ngạc nhiên nhất _(optional)_

_(1–2 câu. Không bắt buộc, nhưng grader đọc hết.)_

_(để trống nếu bạn không làm phần này)_

---

## 8. Self-check trước khi push

- [x] `hardware.json` committed
- [x] `models/active.json` committed
- [x] `benchmarks/01-quickstart-results.md` committed
- [x] `benchmarks/01-tuning-tg128.md` committed
- [x] `benchmarks/02-server-results.md` committed
- [x] `benchmarks/02-server-batching-u50.md` committed
- [x] `benchmarks/locust-10_stats.csv` + `locust-50_stats.csv` committed
- [x] `benchmarks/03-integration-results.md` committed
- [x] Mọi section "required — replace this line" đã được thay
- [x] 5 screenshots trong `submission/screenshots/`
- [x] `make verify` → exit 0
- [x] Repo GitHub ở chế độ **public**
- [x] Đã paste public URL vào VinUni LMS
- [x] **Không** commit `models/*.gguf` hay `runtime/`
