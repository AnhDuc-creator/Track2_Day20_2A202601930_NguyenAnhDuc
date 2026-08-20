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
- **Accelerator:** NVIDIA GeForce MX230 (2048 MiB) + Vulkan — **toàn bộ base track (01/02/03) chạy `ngl=0`**; chỉ bonus B2 `sweep-gpu` mới bật offload (`-ngl 8/16/24/32/99`, xem §6)
- **llama.cpp asset đã tải:** llama-b10488-bin-win-cuda-12.4-x64.zip + cudart-llama-bin-win-cuda-12.4-x64.zip
- **Model đã dùng:** Gemma 4 E2B (`LAB_MODEL=gemma4-e2b`)
- **Quantization:** UD-Q4_K_XL (primary) + UD-Q2_K_XL (compare)

**Chạy ở đâu:** laptop của tôi.

**Setup story:** Hai thay đổi. Thứ nhất, `lab.ps1` là UTF-8 không BOM nên Windows
PowerShell 5.1 giải mã sai dấu gạch dài ở dòng 48, làm hỏng parse cả khối `switch`;
tôi ghi lại file kèm BOM là chạy được. Thứ hai, MX230 chỉ có 2048 MiB VRAM còn model
Q4 nặng 2.97 GB nên tôi cho rằng không nhét vừa, và đặt `LAB_N_GPU_LAYERS=0` cho toàn
bộ base track. Lý do đó **hóa ra không đúng** — §6 cho thấy llama.cpp chỉ offload phần
layer lặp lại và phần đó vừa VRAM thoải mái — nhưng quyết định `ngl=0` thì vẫn đúng, vì
đo lại cho thấy offload không nhanh hơn. Chi tiết ở §6.

Cách tôi xác minh `ngl=0` là thật, chứ không phải giả định: server của track 02 được
khởi động bằng `$env:LAB_N_GPU_LAYERS="0"; .\lab.ps1 serve`, và
`labkit.n_gpu_layers()` đọc biến này trước mọi thứ khác nên `server_cmd()` phát ra
`-ngl 0`. Đây không phải giá trị mặc định rơi vào: khi biến đó **không** được set,
`llama-server --list-devices` vẫn liệt kê `CUDA0` nên cùng hàm đó trả về **99**. Trong
log khởi động của một server `-ngl 0` dựng lại y hệt cấu hình, `load_tensors:
CPU_Mapped model buffer size = 3021.89 MiB` và `offloaded 0/36 layers to GPU` — toàn bộ
trọng số nằm trên CPU.

**Đính chính một câu tôi đã viết sai ở bản trước:** `nvidia-smi` **không** báo 0 MiB khi
server chạy `ngl=0`. Đo lại hôm nay bằng `nvidia-smi --query-gpu=memory.used`
trong lúc server còn sống: **151 MiB** được cấp phát ngay ở `-ngl 0`, vì llama.cpp vẫn
đăng ký CUDA làm compute device và giữ `CUDA0 compute buffer size = 118.88 MiB` kể cả
khi không có layer nào được offload. Con số "0 MiB" ở bản trước đến từ
`nvidia-smi --query-compute-apps=...`, lệnh này trả về rỗng trên Windows WDDM bất kể
GPU có đang được dùng hay không — nó không phải bằng chứng. Kết luận `ngl=0` vẫn đúng,
nhưng bằng chứng đúng là log `offloaded 0/36`, không phải `nvidia-smi`.

Thứ ba, `scripts/verify.py` fail trên Windows với mọi file nằm trong thư mục con:
`is_committed()` dựng đường dẫn tương đối bằng `pathlib` (ra `benchmarks\file.md`) rồi
so với `git ls-files` (trả `benchmarks/file.md`), nên chuỗi không bao giờ khớp. File ở
gốc repo như `hardware.json` thì pass vì không có separator. Tôi vá một dòng trong
`is_committed()` để chuẩn hóa separator về `/` trước khi so sánh. Đây là sửa lỗi tương
thích, không thay đổi điều kiện kiểm tra nào.

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

> Hai cột P50/P95 ở trên lấy nguyên từ `load-report.py` để khớp
> `benchmarks/02-server-results.md`, nhưng **cả hai đều không đọc được như trung vị và
> P95 thông thường** — xem hai đoạn "Cảnh báo" ngay dưới bảng.

- **Offered load tăng 5x, throughput thực tăng:** 1.82x
- **P95 "tăng":** 0.86x (tức giảm — nhưng đây là hiện vật đo, không phải cải thiện)
- **Effective concurrency ở 50 users:** 6.2 so với `--parallel` = 4 slots

**Peak `llamacpp:n_busy_slots_per_decode`:** 3.51 / 4 slots (88%), kèm
`requests_deferred = 21`

**Cảnh báo 1 — P50 = 44000 ms không phải trung vị thật.** `locust-50_stats.csv` có hai
con số đá nhau trên cùng dòng Aggregated: `Median Response Time` = **24266.7 ms** còn
cột percentile `50%` = **44000 ms** (`Average Response Time` = 34349.3 ms). Locust tính
cột percentile từ histogram đã làm tròn theo bucket 1000 ms rồi duyệt từ bucket cao
xuống; với đúng 8 mẫu phép duyệt đó nhảy lên 44000 trong khi trung vị số học chỉ là
24.3 giây. `load-report.py` đọc cột `50%` trước nên bảng hiển thị 44000. **Con số đáng
tin là 24.3 giây.**

**Cảnh báo 2 — cột P95 hai lần chạy khác loại request nên không so được.** Lần 10 users
có 2 request `long-rag` + 3 `short`; lần 50 users chỉ có 8 `short` và **không request
`long-rag` nào về đích**. P95 = 51000 ms ở 10 users là do `long-rag` kéo lên (max 50574
ms); P95 = 44000 ms ở 50 users chỉ mô tả `short`. Vì vậy tỉ số 0.86x là **so lệch loại
request**, không đơn thuần là thiên lệch hàng đợi như tôi viết ở bản trước.

**Saturation reading:** Bão hòa dưới 50 users, nhưng bằng chứng nằm ở gauge của server
chứ không ở bảng locust. `requests_deferred = 21` nghĩa là 21 request đến khi cả 4 slot
đều bận và bị xếp hàng; `busy_slots = 3.51/4` xác nhận chúng chờ vì hết slot thật chứ
không phải vì scheduler bỏ trống tài nguyên. Bảng locust không dùng được cho lập luận
latency vì ba lý do chồng lên nhau: chỉ 5 và 8 request hoàn thành trong 60 giây; cột
percentile là bucket làm tròn chứ không phải trung vị; và mix request giữa hai lần chạy
khác nhau. Locust lại chỉ tính request đã xong, nên những request chậm nhất — ở mức 50
users chính là toàn bộ nhóm `long-rag` — bị loại khỏi thống kê, kéo latency đo được
xuống và làm effective concurrency 6.2 thành con số dưới thực tế.

Số dùng được từ bảng là hàng throughput: 5x tải chào chỉ cho 1.82x throughput, tức
plateau. Hàng này không phụ thuộc vào bucket percentile cũng không phụ thuộc vào mix
request, nên nó sống sót qua cả ba vấn đề trên. Để nâng goodput@SLO tôi sẽ **giảm
`--parallel` từ 4 xuống 2** trước tiên, vì bottleneck là băng thông bộ nhớ chứ không
phải số slot — 4 slot chia nhau một kênh nhớ đã bão hòa thì mọi request đều chậm và đều
trượt SLO (trung vị 24.3 giây cho `short`, còn `long-rag` không kịp về đích trong 60
giây), còn 2 slot cho mỗi request gần gấp đôi tốc độ decode nên một phần về đích kịp
hạn.

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
trên máy này, và chỉ ra rằng knob thật sự còn lại là `--parallel` ở §3.

Về bài học tuning thực tế thì phải nêu **cả hai** spread, vì chúng trả lời hai câu hỏi
khác nhau (giống hệt kết luận trong `benchmarks/01-tuning-tg128.md`):

| Hướng đặt sai       | Spread so với `-t 4` | Throughput mất |
| :------------------ | -------------------: | -------------: |
| Quá ít (`-t 1`)     |            **1.95x** |            49% |
| Quá nhiều (`-t 16`) |            **1.37x** |            27% |

Về **độ lớn**, đặt thiếu thread thiệt hại nặng hơn hẳn: mất 49% throughput so với 27%.
Nhưng về **xác suất mắc phải**, đặt thừa mới là lỗi phổ biến hơn — không ai cố tình gõ
`-t 1`, còn `-t 16` thì trông như "dùng hết máy" và là con số nhiều người sẽ chọn theo
phản xạ trên một chip 8 luồng. Kết luận vận hành: sai số lớn nhất nằm ở phía thiếu,
nhưng rủi ro thực tế nằm ở phía thừa.

---

## 6. Bonus _(optional — tối đa 20 điểm)_

**Đã làm:** B2 `sweep-gpu` · B3 (số liệu bên dưới) · **B4 (C2) KV cache quantization** ·
B5 chọn C9 embedding serving (`serve-embed` + `embed-demo`), kèm `semantic-cache-offline`
làm đối chứng

### B2/B3 — GPU offload: kết quả ban đầu **không tái lập được**

**Numbers (đã sửa sau khi xác minh):**

```
sweep gốc (-r 2):   -ngl 0 → 9.4 tok/s ·  -ngl 8 → 11.8 tok/s   ("speedup 1.25x")
chạy lại (-r 5):    -ngl 0 → 10.18 ± 0.46 ·  -ngl 8 → 9.10 ± 1.77
kết luận:           không có speedup. -ngl 8 CHẬM hơn CPU-only.
```

Bản trước tôi kết luận partial offload nhanh hơn 1.25x và giải thích bằng "VRAM hết
trước ở 16 layer" cộng "hai kênh nhớ cộng băng thông". Tôi đi đo lại để kiểm chứng cơ
chế, và **cả hai đều sai**. Số đo đầy đủ ở `benchmarks/bonus-gpu-offload-verify.json`.

**Sai lầm 1 — VRAM không hề hết.** Dựng lại `llama-server` ở từng mức `-ngl` và đọc
`nvidia-smi` lúc server sống:

| `-ngl` | log: offloaded | CUDA0 model buffer | nvidia-smi used / 2048 MiB |
| :----- | :------------- | -----------------: | -------------------------: |
| 0      | `0/36`         |                  — |                **151 MiB** |
| 8      | `8/36`         |         549.66 MiB |                **713 MiB** |
| 16     | `16/36`        |         871.62 MiB |               **1047 MiB** |
| 99     | `36/36`        |        1481.89 MiB |               **1677 MiB** |

Full offload dùng 1677/2048 MiB — **vừa, còn thừa 371 MiB**. Không mức nào tràn sang
shared memory. Con số "8 layer ≈ 0.68 GB vừa khít 1645 MiB" còn sai số học ngay từ đầu:
0.68 GB là 696 MiB, chưa tới một nửa chỗ trống.

**Sai lầm 2 — lập luận "cộng băng thông" sai cả nguyên lý.** Các layer chạy **tuần tự**,
nên băng thông VRAM và RAM **không chồng lấn** trong cùng một token; thời gian cộng lại
chứ không song song. Tôi đã dựng một cơ chế nghe hợp lý để khớp một con số — đúng cái lỗi
mà môn này dạy phải tránh.

**Cái tôi quan sát được nhưng chưa giải thích được.** Mọi cấu hình có GPU đều tụt mạnh
trong lòng một lần chạy, còn CPU-only thì không: `-ngl 8` đi từ 10.75 xuống 7.00 tok/s
qua 5 rep, `-ngl 99` từ 10.51 xuống 5.13, trong khi `-ngl 0` chỉ 10.64 → 9.41. Độ lệch
chuẩn 1.77–2.68 khi có GPU so với 0.46 khi không. Hai rep đầu của mọi cấu hình GPU đều
quanh 10.1–10.75 — tức **xấp xỉ CPU-only** — nên sweep gốc chạy `-r 2` chỉ lấy mẫu đúng
cửa sổ "còn nguội", và đó là cách con số 11.8 ra đời.

**Nguyên nhân của mức sụt thì tôi chưa xác định được.** Giả thuyết còn lại: trần
nhiệt/công suất dùng chung của chip 15 W với dGPU cùng khung máy; quản lý power-state của
driver trên WDDM; chi phí đồng bộ host–device tích lũy. Chưa cái nào được kiểm chứng —
muốn kết luận thì phải lấy mẫu `clocks.sm`, `temperature.gpu`, `power.draw` trong lúc
bench chạy và xáo thứ tự các mức `-ngl`, việc tôi chưa làm. Mức `-ngl 16` còn không khớp
hình mẫu đó (rep 1 đã chỉ 6.09), nên có thể còn yếu tố thứ hai.

**Điều này vẫn nói lên một điều deck chưa nói**, chỉ là không phải điều tôi tưởng: trên
laptop mỏng, `-r 2` không đủ để kết luận bất cứ điều gì về `-ngl`, vì cửa sổ đo đầu tiên
nằm trọn trong giai đoạn máy còn nguội. Lựa chọn `ngl=0` cho base track vẫn đúng — nhưng
vì MX230 không đem lại throughput cao hơn và làm phép đo mất ổn định, **không** phải vì
model không vừa VRAM.

### C9 — embedding serving

Chạy lại với `LAB_N_GPU_LAYERS=0` và lưu output thô
(`benchmarks/bonus-c9-embedding-serving.txt`): batch 16 cho throughput **8.1x** với
latency tăng **1.97x**, trong khi chat serving ở track 02 tăng tải 5x chỉ được 1.82x
throughput. Lần chạy đầu cho 9.5x/1.69x — mỗi batch size chỉ chạy một lần nên nhiễu cỡ
±1x là có thật, và tôi không đọc 8.1x như một phép đo chính xác. Điều sống sót qua cả hai
lần chạy là dấu hiệu định tính: cùng một model, cùng một máy, hai đường cong batching
ngược nhau. Chi tiết trong `benchmarks/bonus-c9-embedding-serving.md`.

### B4 (C2) — KV cache quantization f16 → q8_0

| Trục                        | q8_0 so với f16                              | Độ tin cậy                    |
| :-------------------------- | :------------------------------------------- | :---------------------------- |
| Bộ nhớ KV                   | **−46.9%** ở mọi ctx                         | Cao                           |
| RSS tiến trình              | −18.7 MB (ctx 2048) → −461.1 MB (ctx 131072) | Cao                           |
| Prefill                     | **−25%** (chậm hơn)                          | Cao — dải rep không giao nhau |
| Decode                      | +4.4% (nhanh hơn)                            | **Thấp — không vượt nhiễu**   |
| Chất lượng (eval 10 prompt) | 8/10 ↔ 8/10                                  | Trung bình — mẫu nhỏ          |

Con số đáng nói nhất là **0.531**: tỉ lệ KV q8_0/f16 giống hệt nhau ở cả bốn mức ctx, và
nó không phải "gần một nửa" mà là 34/64 chính xác — mỗi block 32 phần tử lưu 32 byte
int8 **cộng một scale fp16 2 byte**. Nên q8_0 tiết kiệm 46.875%, và 3.125 điểm phần trăm
hụt đi chính là metadata lượng tử hóa.

Chỗ tôi phải sửa lại cách hiểu của chính mình: mức tiết kiệm **không** tuyến tính theo
ctx. Nó là tỉ lệ hằng số của KV, còn KV thì chỉ tuyến tính ở phần full-attention. Gemma 4
E2B cấp 3 cache full-attention (số cell bằng `ctx_per_slot`) và 12 cache sliding-window
**dừng ở 1024 cell**. Vì thế tăng ctx 64 lần chỉ làm KV tăng 22.7 lần (36 → 816 MiB).

Đánh đổi thật là **25% prefill để lấy 47% KV**. Với workload RAG prompt dài sinh ít token
— đúng hình dạng track 03 — đó là đánh đổi **sai hướng**, vì prefill mới là chi phí
chính. Chỉ bật khi ngữ cảnh dài và bộ nhớ là ràng buộc. Chi tiết:
`benchmarks/bonus-c2-kv-cache-quant.md`.

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
