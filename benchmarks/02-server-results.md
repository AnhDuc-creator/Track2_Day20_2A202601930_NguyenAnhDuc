# 02 - Serve: load test + saturation reading

Host `Windows-AMD64` · llama.cpp `b10488` ·
`--parallel 4` · `ctx=2048` · `threads=4` ·
`ngl=0`

| Users | Reqs | RPS | P50 (ms) | P95 (ms) | P99 (ms) | Eff. concurrency | Failures |
|:--|--:|--:|--:|--:|--:|--:|--:|
| 10 | 5 | 0.10 | 36000 | 51000 | 51000 | 3.7 | 0.0% |
| 50 | 8 | 0.18 | 44000 | 44000 | 44000 | 6.2 | 0.0% |

*Effective concurrency = RPS x average latency (Little's Law) -- how many requests were
really in flight, regardless of how many users locust simulated. It counts queued requests
too, so the occupancy/slot ratio can legitimately exceed 1.0; it is occupancy, not
utilisation. For true slot utilisation use the server's own gauges (`make metrics`).*

## What these two runs say

| Going from 10 to 50 users | |
|:--|--:|
| Offered load | 5x |
| Throughput actually delivered | **1.82x** (36% of linear) |
| P95 latency | **0.86x** |
| Effective concurrency at 50 users | 6.2 vs `--parallel 4` slots (occupancy/slot ratio 1.55) |

**Saturated.** Throughput delivered only 1.82x for 5x the offered load, and effective concurrency (6.2) is at or above all 4 decode slots. Saturation sets in somewhere at or below 50 users; the load you added beyond that point became queue time rather than throughput.

P95 grew no faster than throughput (0.86x vs 1.82x), so this server still has headroom at 50 users.

> **Small sample.** Only 5 requests completed in the
> shorter run, so these percentiles are indicative rather than solid. Note also that
> locust averages only *completed* requests: when the run ends with requests still
> queued, effective concurrency is an **under**-estimate. Trust the throughput-scaling
> row over the concurrency row here, and run longer (`-t 3m`) if you want firmer numbers.

## Your reading

Server bão hòa ở dưới 50 users, nhưng **bằng chứng thuyết phục không nằm trong bảng
locust ở trên**. Nó nằm ở gauge của chính server.

Con số quyết định là `requests_deferred = 21` cùng với
`n_busy_slots_per_decode = 3.51 / 4` (88%), lấy từ `make metrics` chạy chồng thời gian
với `make load-50` (xem `02-server-batching-u50.md`). Deferred khác 0 nghĩa là có 21
request đến khi cả 4 slot đều bận và bị đẩy vào hàng đợi, không phải bị từ chối. Đó là
định nghĩa trực tiếp của bão hòa: điểm mà request thêm vào chuyển thành thời gian chờ
chứ không thành throughput. Busy slots 3.51/4 xác nhận scheduler đã gom batch gần hết
công suất — nghĩa là 21 request kia xếp hàng vì hết slot thật, không phải vì scheduler
bỏ trống tài nguyên.

### Bảng percentile ở trên có hai vấn đề, cần nói rõ cả hai

**Vấn đề 1 — P50 = 44000 ms không phải trung vị thật.** `locust-50_stats.csv` chứa hai
con số đá nhau ở cùng một dòng Aggregated:

| Cột trong CSV            | Giá trị        |
| :----------------------- | -------------: |
| `Median Response Time`   | **24266.7 ms** |
| `50%` (percentile bucket)| **44000 ms**   |
| `Average Response Time`  | 34349.3 ms     |

Locust tính các cột percentile từ một histogram đã làm tròn theo bucket (với giá trị
trên 10 s thì làm tròn về bội số của 1000 ms), rồi duyệt bucket từ cao xuống. Với đúng
8 mẫu, phép duyệt đó nhảy thẳng lên bucket 44000 trong khi trung vị số học của 8 mẫu
chỉ là 24.3 giây. `load-report.py` đọc cột `50%` trước (`num("50%", "Median Response
Time")`), nên bảng phía trên hiển thị 44000. **Con số đáng tin ở đây là 24.3 giây**;
44 giây là hiện vật của thuật toán bucket trên mẫu quá nhỏ, không phải phép đo.

**Vấn đề 2 — cột P95 của hai lần chạy không so được với nhau vì khác loại request.**

| Run       | Thành phần hoàn thành          |
| :-------- | :----------------------------- |
| locust-10 | 2 × `long-rag` + 3 × `short`   |
| locust-50 | 8 × `short`, **0** × `long-rag`|

P95 = 51000 ms ở 10 users là do hai request `long-rag` kéo lên (max 50574 ms, và
`long-rag` có median riêng 27171 ms so với `short` 36000 ms nhưng đuôi dài tới 50574
ms). Ở 50 users **không có request `long-rag` nào về đích**, nên P95 = 44000 ms chỉ mô
tả request `short`. Vì vậy tỉ số "P95 0.86x" là **so lệch loại request**, không chỉ là
thiên lệch hàng đợi. Cả hai cơ chế cùng tác động một chiều: locust chỉ tính request đã
hoàn thành, nên những request chậm nhất — mà ở mức 50 users chính là toàn bộ nhóm
`long-rag` — bị loại khỏi thống kê. Câu tự sinh phía trên đọc 0.86x thành "still has
headroom": kết luận đó sai, và bây giờ có hai lý do độc lập để bác nó.

Cùng cơ chế đó khiến effective concurrency 6.2 là con số **dưới** thực tế — chỉ riêng
deferred đã là 21.

Bằng chứng dùng được từ bảng này là hàng throughput: tải chào tăng 5x nhưng throughput
giao được chỉ tăng 1.82x (36% của tuyến tính). Đó là plateau, và nó nhất quán với
deferred khác 0. Hàng throughput không phụ thuộc vào percentile bucket cũng không phụ
thuộc vào mix request, nên nó sống sót qua cả hai vấn đề trên.

### Knob sẽ đổi trước để nâng goodput@SLO: giảm `--parallel` từ 4 xuống 2

Lý do là bottleneck ở đây là băng thông bộ nhớ, không phải số slot. `make tune` cho
thấy decode đã chạm trần băng thông từ 4 thread; thêm slot đồng thời không tạo thêm
băng thông, chỉ chia nhỏ nó ra. Với 4 slot chạy song song trên cùng kênh nhớ bão hòa,
mỗi request nhận một phần tư tốc độ decode, nên request nào cũng chậm và request nào
cũng có nguy cơ vi phạm SLO — E2E trung vị 24.3 giây cho request `short` thì hầu như
không SLO tương tác nào đạt được, và nhóm `long-rag` thậm chí không về đích trong cửa
sổ 60 giây. Giảm xuống 2 slot làm hàng đợi dài hơn nhưng cho mỗi request đang chạy gần
gấp đôi băng thông, nên một phần request về đích trong ngưỡng thay vì toàn bộ cùng
trượt. Goodput@SLO đếm số request kịp hạn, không đếm tổng token, nên đánh đổi này có
lợi.

Tăng `--parallel` lên 8 sẽ đi sai hướng: nó nâng raw throughput thêm chút ít nhưng đẩy
mọi request ra xa ngưỡng SLO hơn nữa. Đó đúng là khoảng cách giữa throughput và
goodput mà deck §8 nói tới, và ở máy này khoảng cách đó rất rộng vì trần băng thông
thấp.

Nếu cần số chắc hơn thì phải chạy lại với `-t 3m` để có đủ mẫu cho percentile — với 5
và 8 request thì chỉ gauge của server mới đáng tin, và cần giữ nguyên tỉ lệ trộn
`long-rag`/`short` giữa hai mức tải thì cột P95 mới so sánh được.
