# 03 - Integrate: RAG pipeline run

Host `Windows-AMD64` · llama.cpp `b10488` ·
retrieval backend: **keyword overlap** · 3 queries

| Query                                           |      Contexts retrieved | embed (ms) | retrieve (ms) | llm (ms) | total (ms) |
| :---------------------------------------------- | ----------------------: | ---------: | ------------: | -------: | ---------: |
| Why is goodput more useful than raw throughp... |   goodput, paged, radix |        0.0 |           0.1 |   7551.7 |     7551.8 |
| What problem does PagedAttention actually so... |    paged, radix, disagg |        0.0 |           0.1 |   5984.7 |     5984.8 |
| When does splitting prefill and decode help?... | disagg, radix, batching |        0.0 |           0.1 |   6130.6 |     6130.8 |

Mean per stage (ms): embed **0.0** · retrieve **0.1** ·
llm **6555.7** · total **6555.8**
Dominant stage: **llm** (100% of total)

## Answers returned

**Why is goodput more useful than raw throughput?**

> Goodput@SLO counts only the requests per second that met the TTFT and TPOT targets. Throughput at saturation ignores SLOs.

**What problem does PagedAttention actually solve?**

> PagedAttention stores the KV cache in non-contiguous pages, removing the internal fragmentation that wasted most GPU memory.

**When does splitting prefill and decode help?**

> Splitting prefill and decode helps because prefill is compute-bound and decode is memory-bandwidth-bound.

## Your reading

**Cái nào real, cái nào stub** (N16–N19 chưa nối, chỉ N20 là thật):

| Day                   | Piece                                         | Trạng thái                                     |
| --------------------- | --------------------------------------------- | ---------------------------------------------- |
| N16 Cloud/IaC         | không có cluster/Compose                      | **Stub** — chạy localhost                      |
| N17 Data pipeline     | không có DAG                                  | **Stub** — `TOY_DOCS` in-memory                |
| N18 Lakehouse         | không có Delta/Iceberg                        | **Stub** — dict trong bộ nhớ                   |
| N19 Vector + features | không có vector index                         | **Stub** — keyword overlap, `embed` trả 0.0 ms |
| N20 Serving           | `llama-server` b10488, Gemma 4 E2B UD-Q4_K_XL | **Real**                                       |

**Latency breakdown** (mean của 3 query): embed 0.0 ms · retrieve 0.1 ms ·
llm 6555.7 ms · total 6555.8 ms. Stage chiếm nhiều nhất: **llm, 100.0%**.

Con số 100% này không gây ngạc nhiên nhưng cũng không nói lên nhiều, vì hai stage kia
đang là stub: `embed` báo 0.0 ms do không có embedding server nên retrieval rơi về
keyword overlap, và `retrieve` báo 0.1 ms do corpus chỉ có vài document trong bộ nhớ.
Nếu nối N19 thật với vector index và một embedding endpoint riêng, embed sẽ thành một
forward pass thật và retrieve sẽ phải quét index — cả hai đều khác 0, dù trên máy này
LLM gần như chắc chắn vẫn áp đảo.

Bóc tách sâu hơn trong phần llm cho thấy chỗ đáng tấn công. Lấy query đầu làm ví dụ:
prefill 150 token mất 2274 ms (khoảng 66 tok/s), decode 30 token mất 2714 ms (khoảng
11 tok/s). Nghĩa là **prefill chiếm khoảng một phần ba độ trễ dù chỉ xử lý prompt**,
và tỉ lệ đó sẽ xấu đi nhanh khi RAG đưa context dài vào, vì chi phí attention tăng
theo bình phương độ dài prompt còn decode thì tuyến tính theo số token sinh ra.

Muốn giảm latency pipeline này 2x thì tấn công vào đâu:

1. **Prompt caching** — giữ system prompt giống nhau từng byte giữa các lần gọi để
   server tái dùng prefix đã cache. Với 3 query dùng chung system prompt, đây là phần
   prefill gần như cho không.
2. **Cắt ngân sách context** — ít chunk retrieve hơn, chunk ngắn hơn. Prefill là chỗ
   RAG thổi phồng độ trễ, và `--ctx-size` mặc định 2048 chia cho 4 slot chỉ còn 512
   token mỗi slot, nên context dài sẽ bị truncate trước khi kịp giúp gì.
3. **Giảm số token sinh ra** — decode ở 11 tok/s là trần băng thông của CPU này, không
   tối ưu phần mềm nào vượt qua được. Cắt `max_tokens` là đòn bẩy trực tiếp nhất.

Đổi model sang Qwen3.5 0.8B sẽ cho mức giảm lớn nhất, nhưng đó là đánh đổi chất lượng
chứ không phải tối ưu hệ thống.
