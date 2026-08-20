# Bonus C9 — Embedding serving regime (B5)

Host `Windows-AMD64` · llama.cpp `b10488` · `llama-server --embedding` :8081 ·
Gemma 4 E2B UD-Q4_K_XL ở pooling mode · `threads=4` · `ngl=0` · dim 1536 · corpus 8 docs

## Throughput theo batch size (prefill-bound)

| Batch | Latency (ms) | Throughput (texts/s) | vs batch 1 |
| ----: | -----------: | -------------------: | ---------: |
|     1 |       2498.1 |                  0.4 |      1.00x |
|     2 |       2566.8 |                  0.8 |      2.00x |
|     4 |       2713.1 |                  1.5 |      3.75x |
|     8 |       3286.3 |                  2.4 |      6.00x |
|    16 |       4233.4 |                  3.8 |      9.50x |

## Finding

**Batch gấp 16 lần cho throughput gấp 9.5 lần, trong khi latency chỉ tăng 1.69 lần.**
Đây là chữ ký của một regime hoàn toàn khác với track 02.

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
serving, doc đúng đạt 0.847 nhưng doc về RadixAttention — chủ đề khác hẳn — đạt 0.788,
chỉ kém 0.059. Doc thứ ba (speculative decoding, cũng không liên quan) đạt 0.745. Toàn bộ
top 3 nằm trong dải rộng 0.102.

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
