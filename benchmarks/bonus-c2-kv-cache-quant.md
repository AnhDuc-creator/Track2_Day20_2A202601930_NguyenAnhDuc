# Bonus C2 — KV cache quantization (f16 vs q8_0)

Host `Windows-AMD64` · llama.cpp `b10488` · Gemma 4 E2B UD-Q4_K_XL ·
`threads=4` · `--parallel 4` · `ngl=0` · `--cache-type-k/-v q8_0`

Dữ liệu thô: `benchmarks/bonus-c2-kv-cache-quant.json` (sweep chính) và
`benchmarks/bonus-c2-kv-cache-quant-calib.json` (lần calib ở `ctx=8192`, 1 rep).
Sinh bằng `bonus/kv-cache-quant.py --rss-sweep --measure`. Mọi số dưới đây đọc thẳng
từ hai file đó.

## 1. KV cache nhỏ đi bao nhiêu

`--parallel 4` nên `ctx_per_slot = ctx_total / 4`.

| ctx total | ctx/slot | KV f16 | KV q8_0 | tỉ lệ | RSS f16 | RSS q8_0 | Δ RSS |
| --------: | -------: | -----: | ------: | ----: | ------: | -------: | ----: |
|      2048 |      512 |   36.0 |   19.13 | 0.531 |  1915.2 |   1896.5 |  18.7 |
|     16384 |     4096 |  144.0 |   76.50 | 0.531 |  2031.9 |   1958.2 |  73.7 |
|     65536 |    16384 |  432.0 |  229.50 | 0.531 |  2355.9 |   2125.5 | 230.4 |
|    131072 |    32768 |  816.0 |  433.50 | 0.531 |  2809.3 |   2348.2 | 461.1 |

_KV tính bằng MiB (llama.cpp báo), RSS bằng MB sau warm-up (đo từ tiến trình server)._

Hai điều đáng chú ý. Thứ nhất, tỉ lệ là **0.531 ở cả bốn mức ctx**, không hề dao động.
Thứ hai, **Δ RSS bám sát Δ KV** (18.7 vs 16.87 · 73.7 vs 67.5 · 230.4 vs 202.5 · 461.1
vs 382.5 MiB), tức phần tiết kiệm là bộ nhớ thật của tiến trình chứ không phải con số
kế toán. Chênh lệch dư ra tăng dần theo ctx (từ ~2 lên ~79 MB) và tôi **không xác định
được** nó đến từ đâu — nghi là buffer tính toán và phân mảnh allocator, nhưng chưa đo.

## 2. Vì sao là 0.531 chứ không phải 0.5

Đây không phải "gần một nửa" theo nghĩa xấp xỉ — nó là một con số chính xác rút ra từ
định dạng block:

- `f16`: 2 byte cho mỗi phần tử KV.
- `q8_0`: mỗi block 32 phần tử lưu 32 byte int8 **cộng một scale fp16 2 byte** = 34 byte,
  tức 1.0625 byte/phần tử.

Tỉ lệ = 1.0625 / 2 = **0.53125**. Khớp tuyệt đối với cả bốn hàng đo được. Nghĩa là q8_0
tiết kiệm **46.875%**, không phải 50%; 3.125 điểm phần trăm hụt đi chính là cái scale
fp16 của mỗi block 32 phần tử. Đi từ 16 bit xuống 8 bit mà chỉ được 46.9% là vì metadata
lượng tử hóa cũng phải nằm trong cache.

## 3. Mức tiết kiệm tỉ lệ với cái gì — cần nói chính xác hơn "tuyến tính theo ctx"

Tiết kiệm luôn là 46.875% **của KV**, ở mọi ctx. Nhưng bản thân KV **không** tuyến tính
theo ctx trên model này. Bóc tách các cache mà llama.cpp cấp phát:

| ctx/slot | Nhóm A (3 layer) | Nhóm B (12 layer) | Tổng f16 |
| -------: | :--------------- | :---------------- | -------: |
|      512 | 512 cells → 12 MiB | 512 cells → 24 MiB |     36.0 |
|     4096 | 4096 cells → 96 MiB | **1024** cells → 48 MiB |    144.0 |
|    16384 | 16384 cells → 384 MiB | **1024** cells → 48 MiB |    432.0 |
|    32768 | 32768 cells → 768 MiB | **1024** cells → 48 MiB |    816.0 |

Nhóm A dùng 8 KiB mỗi cell mỗi layer và số cell **bằng đúng** `ctx_per_slot` — đây là các
layer full-attention. Nhóm B dùng 4 KiB mỗi cell mỗi layer nhưng số cell **dừng ở 1024**
từ `ctx_per_slot = 4096` trở đi — đây là các layer sliding-window, và 1024 chính là bề
rộng cửa sổ. Vì vậy nhóm B đóng băng ở 48 MiB dù ctx tăng bao nhiêu đi nữa.

Hệ quả: tăng ctx **64 lần** (2048 → 131072) chỉ làm KV tăng **22.7 lần** (36 → 816 MiB),
chứ không phải 64 lần. Chỉ khi ctx đủ lớn để nhóm A áp đảo thì KV mới tiệm cận tuyến
tính. Nói cách khác:

> Mức tiết kiệm là một **tỉ lệ hằng số của KV** (46.875%), và nó tuyến tính theo ctx
> **chỉ ở phần full-attention**; phần sliding-window bị chặn trần nên đóng góp một hằng
> số. Ở ctx nhỏ, KV quant tiết kiệm rất ít về giá trị tuyệt đối (16.9 MiB ở ctx 2048)
> đơn giản vì lúc đó chẳng có mấy KV để mà nén.

Đó cũng là câu trả lời cho "khi nào đáng bật": chỉ khi ctx đủ lớn. Ở `ctx=2048` mặc định
của lab, bật q8_0 đổi lấy 16.9 MiB — vô nghĩa trên máy 23.8 GB RAM.

## 4. Latency đổi theo hướng nào

Đo ở `ctx_total=65536`, `ctx_per_slot=16384`, prompt **7876 token**, 3 rep:

| Cache | Prefill trung vị | Các rep prefill | Decode trung vị | Các rep decode |
| :---- | ---------------: | :-------------- | --------------: | :------------- |
| f16   |  **131.26** tok/s | 125.84 · 131.26 · 132.18 | **1.37** tok/s | 1.486 · 1.259 · 1.367 |
| q8_0  |   **98.51** tok/s | 98.51 · 100.41 · 80.84 | **1.43** tok/s | 1.582 · 1.428 · 0.872 |

**Prefill chậm đi 25%** (131.26 → 98.51 tok/s). Đây là khác biệt thật: dải rep của hai
bên **không giao nhau** (125.84–132.18 so với 80.84–100.41). Cách giải thích khớp với dữ
liệu là prefill phải **ghi** toàn bộ KV cho 7876 token, và ghi ở dạng q8_0 tốn thêm bước
lượng tử hóa cho mỗi block; prefill vốn bị chặn bởi compute nên phần việc thêm này hiện
thẳng ra thành thời gian. Tôi chưa profile để xác nhận trực tiếp, nên coi đây là suy
luận khớp dữ liệu, không phải cơ chế đã đo.

**Decode nhanh hơn 4.4%** (1.37 → 1.43 tok/s) — nhưng con số này **không vượt nhiễu**.
Dải rep chồng lên nhau gần như hoàn toàn (1.259–1.486 so với 0.872–1.582), và q8_0 có
một rep 0.872 thấp hơn mọi rep của f16. Về lý thuyết decode bị chặn bởi băng thông nên
đọc KV nhỏ hơn *nên* nhanh hơn, nhưng **3 rep không đủ để chứng minh điều đó**, và tôi
không tuyên bố là có cải thiện.

Một quan sát nằm ngoài trục f16/q8_0 nhưng quan trọng hơn cả hai: decode ở đây chỉ
**1.37–1.43 tok/s**, trong khi lần calib ở `ctx=8192` với prompt 590 token cho **7.9
tok/s**. Ngữ cảnh dài mới là thứ giết throughput, và KV quant **không** sửa được điều đó
— nó chỉ giảm chỗ chứa.

## 5. Chất lượng có giảm không

Eval 10 prompt trên cùng tài liệu dài (prompt trung vị 2931 token): 5 câu số học nhiều
bước, 5 câu trích xuất JSON.

| Cache | Passed | Câu trượt | Đáp án sai                          |
| :---- | -----: | :-------- | :---------------------------------- |
| f16   | **8/10** | a3, a4 | a3 → 1365 (đúng 1140) · a4 → 5716 (đúng 5796) |
| q8_0  | **8/10** | a3, a4 | a3 → 1265 (đúng 1140) · a4 → 5616 (đúng 5796) |

**Không đo được mức giảm chất lượng nào.** Cùng điểm 8/10, cùng hai câu trượt, và cả 5
câu JSON đều đúng ở cả hai cấu hình. Đáng chú ý là trên a3, q8_0 còn *gần* đáp án đúng
hơn f16 (1265 so với 1365) trong khi trên a4 thì xa hơn — không có hướng suy giảm hệ
thống nào.

Phải nói rõ giới hạn: **10 prompt thì độ phân giải là 10 điểm phần trăm**. Kết quả này
loại trừ được mức suy giảm lớn, chứ không loại trừ được mức suy giảm nhỏ. Và hai câu
trượt là số học nhiều bước — dạng bài mà model E2B 4-bit vốn đã yếu, nên chúng nói về
model nhiều hơn là về KV cache.

## 6. Kết luận

| Trục | q8_0 so với f16 | Độ tin cậy |
| :--- | :--- | :--- |
| Bộ nhớ KV | **−46.9%**, chính xác ở mọi ctx | Cao — khớp lý thuyết block tuyệt đối |
| RSS tiến trình | giảm 18.7 → 461.1 MB theo ctx | Cao — đo từ tiến trình |
| Prefill | **−25%** (chậm hơn) | Cao — dải rep không giao nhau |
| Decode | +4.4% (nhanh hơn) | **Thấp — không vượt nhiễu, 3 rep** |
| Chất lượng | 8/10 ↔ 8/10, không đổi | Trung bình — chỉ 10 prompt |

**Khi nào bật:** khi ngữ cảnh dài và bộ nhớ mới là ràng buộc — ở `ctx=131072`, q8_0 trả
lại 461 MB RSS, đủ để chạy thêm slot hoặc tránh swap. **Khi nào không bật:** khi prefill
nằm trên đường tới hạn của SLO, vì đánh đổi ở đây là **25% prefill để lấy 47% KV**. Với
workload RAG prompt dài, sinh ít token — đúng hình dạng của track 03 — thì đó là đánh
đổi **sai hướng**, vì prefill mới là chi phí chính.

Ở cấu hình mặc định của lab (`ctx=2048`) thì câu hỏi không đặt ra: tiết kiệm 16.9 MiB
không đáng để mất 25% prefill.

**Chưa làm:** chưa thử `q4_0` cho KV, chưa thử bất đối xứng (`--cache-type-k q8_0` với
V giữ f16, cấu hình thường được khuyến nghị vì K nhạy hơn V), và chưa lặp đủ rep để kết
luận về decode.
