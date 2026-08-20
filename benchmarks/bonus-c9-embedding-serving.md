# Bonus C9 — Embedding serving regime (B5)

Host `Windows-AMD64` · llama.cpp `b10488` · `llama-server --embedding` :8081 ·
Gemma 4 E2B UD-Q4_K_XL ở pooling mode · `threads=4` · `ngl=0` · dim 1536 · corpus 8 docs

> **Xuất xứ số liệu.** Bản đầu của file này được viết tay từ output terminal và không
> kèm dữ liệu thô, nên không kiểm chứng được. Tôi đã **chạy lại** với
> `LAB_N_GPU_LAYERS=0` và lưu toàn bộ output thô vào
> `benchmarks/bonus-c9-embedding-serving.txt`. `ngl=0` của server embedding lần này là
> **đã xác minh**: log khởi động ghi
> `common_fit_params: ... n_gpu_layers already set by user to 0, abort`. Lưu ý `ngl=0`
> vẫn **không** đồng nghĩa 0 MiB VRAM — `nvidia-smi` báo **847 MiB / 2048 MiB** trong
> lúc server này sống, và về 0 MiB ngay khi tắt (xem `bonus-gpu-offload-sweep.md`).

## Throughput theo batch size (prefill-bound)

Cột "chạy lại" là số có dữ liệu thô kèm theo và là số tôi dùng để kết luận. Cột "lần
đầu" giữ lại để thấy biên độ dao động giữa hai lần chạy cùng cấu hình.

| Batch | Latency chạy lại (ms) | Throughput (texts/s) | vs batch 1 | Latency lần đầu (ms) |
| ----: | --------------------: | -------------------: | ---------: | -------------------: |
|     1 |                3393.6 |                 0.29 |      1.00x |               2498.1 |
|     2 |                4320.9 |                 0.46 |      1.57x |               2566.8 |
|     4 |                3435.5 |                 1.16 |      3.95x |               2713.1 |
|     8 |                4561.6 |                 1.75 |      5.95x |               3286.3 |
|    16 |                6700.9 |                 2.39 |      8.10x |               4233.4 |

## Finding

**Batch gấp 16 lần cho throughput gấp 8.1 lần, trong khi latency chỉ tăng 1.97 lần.**
Đây là chữ ký của một regime hoàn toàn khác với track 02.

Cần nói ngay về độ tin cậy: mỗi batch size chỉ chạy **một lần**, không lặp. Lần đầu cho
9.5x/1.69x, lần chạy lại cho 8.1x/1.97x, và trong lần chạy lại batch 2 (4320.9 ms) còn
chậm hơn batch 4 (3435.5 ms) — đường cong không đơn điệu, tức nhiễu cỡ ±1x là có thật.
Vì vậy **không nên đọc con số 8.1x như một phép đo chính xác**. Điều sống sót qua cả hai
lần chạy là dấu hiệu định tính, và nó đủ mạnh: throughput tăng gần một bậc trong khi
latency chưa tới gấp đôi, ngược hẳn với chat serving ở track 02 (5x tải chào chỉ cho
1.82x throughput). Muốn con số chắc thì phải lặp mỗi batch size vài lần và lấy trung vị,
việc tôi chưa làm.

Riêng phần retrieval thì tái lập rất tốt giữa hai lần chạy: cosine 0.848 / 0.785 / 0.744
lần này so với 0.847 / 0.788 / 0.745 lần đầu.

Lý do nằm ở chỗ embedding serving chỉ có prefill: mỗi text là một forward pass, không có
KV cache, không có vòng decode. Trọng số model được nạp một lần cho cả batch, và chi phí
đó được chia đều cho mọi text trong batch — batch 1 trả toàn bộ chi phí cho một text,
batch 16 chia cho 16. Đó là lý do latency gần như phẳng từ batch 1 đến 4 (2498 lên 2713
ms, chỉ +9% cho 4 lần công việc): phần tăng thêm chỉ là compute attention thật, còn phần
đọc trọng số không đổi.

Đối chiếu với track 02 cho thấy hai regime cần chiến lược batching ngược nhau. Ở chat
serving, tải chào tăng 5x chỉ cho 1.82x throughput (xem `02-server-results.md`) vì decode
bị chặn bởi băng thông bộ nhớ: mỗi token của mỗi request đều phải đọc lại toàn bộ trọng
số, nên gom nhiều request vào một batch không giảm được lượng byte phải di chuyển. Ở
embedding serving, gom batch **thực sự** amortize được chi phí đọc trọng số, nên
throughput gần như tuyến tính.

Hệ quả vận hành: chat endpoint cần **continuous batching** — nhét request mới vào slot
trống ngay khi có, vì mỗi request đến và đi ở thời điểm khác nhau và không có gì để
amortize. Embedding endpoint cần **static batching** lớn, gom text lại và sắp theo độ dài
token trước khi chạy, chấp nhận thêm chút chờ đợi để đổi lấy batch to hơn. Đặt hai
endpoint sau cùng một autoscaler là sai: chat cần scale theo số request đồng thời để giữ
TTFT, còn embedding cần scale theo tổng khối lượng text và hưởng lợi khi _dồn_ tải chứ
không phải trải mỏng nó.

## Giới hạn cần khai báo

Lab không có embedding model chuyên dụng, nên `serve-embed` chạy chat GGUF ở pooling
mode. Đây là sentence encoder yếu, và số đo cho thấy rõ: với query hỏi về embedding
serving, doc đúng đạt 0.848 nhưng doc về RadixAttention — chủ đề khác hẳn — đạt 0.785,
chỉ kém 0.063. Doc thứ ba (speculative decoding, cũng không liên quan) đạt 0.744. Toàn bộ
top 3 nằm trong dải rộng 0.104.

Phổ similarity bị nén như vậy làm việc đặt threshold gần như bất khả thi, và chạy
`semantic-cache-offline` xác nhận điều đó theo hướng cực đoan hơn: sweep threshold từ
0.70 đến 0.95 cho **cùng một kết quả 3/8 hit ở mọi ngưỡng**. Similarity của bag-of-words
chỉ nhận đúng hai giá trị 0.00 hoặc 1.00, nên không tồn tại đường cong để mà chọn điểm
cắt. Trong 8 prompt, "What does time to first token mean?" bị miss dù corpus có doc về
TTFT — một false miss điển hình, và không ngưỡng nào sửa được vì similarity của nó bằng
0 tuyệt đối.

Nguyên nhân sâu xa: decoder được train để dự đoán token kế tiếp, nên trạng thái ẩn của nó
tối ưu cho việc "từ nào tiếp theo", không phải "câu này nghĩa là gì". Mean-pooling các
trạng thái đó ra một vector là thao tác không nằm trong mục tiêu huấn luyện. Model
embedding chuyên dụng như Qwen3-Embedding hay BGE-M3 dùng contrastive training trên cặp
câu, kéo paraphrase lại gần và đẩy câu không liên quan ra xa, tạo ra đúng phổ similarity
trải rộng mà threshold cần. Retrieval production phải dùng loại đó; con số ở đây chỉ dùng
để đo **regime**, không dùng để đánh giá chất lượng retrieval.
