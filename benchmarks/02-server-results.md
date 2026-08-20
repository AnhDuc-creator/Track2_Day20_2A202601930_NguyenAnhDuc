# 02 - Serve: load test + saturation reading

Host `Windows-AMD64` · llama.cpp `b10488` ·
`--parallel 4` · `ctx=2048` · `threads=4` ·
`ngl=0`

| Users | Reqs |  RPS | P50 (ms) | P95 (ms) | P99 (ms) | Eff. concurrency | Failures |
| :---- | ---: | ---: | -------: | -------: | -------: | ---------------: | -------: |
| 10    |    5 | 0.10 |    36000 |    51000 |    51000 |              3.7 |     0.0% |
| 50    |    8 | 0.18 |    44000 |    44000 |    44000 |              6.2 |     0.0% |

_Effective concurrency = RPS x average latency (Little's Law) -- how many requests were
really in flight, regardless of how many users locust simulated. It counts queued requests
too, so the occupancy/slot ratio can legitimately exceed 1.0; it is occupancy, not
utilisation. For true slot utilisation use the server's own gauges (`make metrics`)._

## What these two runs say

| Going from 10 to 50 users         |                                                         |
| :-------------------------------- | ------------------------------------------------------: |
| Offered load                      |                                                      5x |
| Throughput actually delivered     |                               **1.82x** (36% of linear) |
| P95 latency                       |                                               **0.86x** |
| Effective concurrency at 50 users | 6.2 vs `--parallel 4` slots (occupancy/slot ratio 1.55) |

**Saturated.** Throughput delivered only 1.82x for 5x the offered load, and effective concurrency (6.2) is at or above all 4 decode slots. Saturation sets in somewhere at or below 50 users; the load you added beyond that point became queue time rather than throughput.

P95 grew no faster than throughput (0.86x vs 1.82x), so this server still has headroom at 50 users.

> **Small sample.** Only 5 requests completed in the
> shorter run, so these percentiles are indicative rather than solid. Note also that
> locust averages only _completed_ requests: when the run ends with requests still
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

Bảng locust phía trên **không** dùng được để lập luận, và cần nói rõ vì sao. Chỉ có 5
và 8 request hoàn thành trong 60 giây, nên mọi percentile đều được nội suy từ một
nhúm mẫu: ở lần 50 users, P50, P95 và P99 đều bằng nhau (44000 ms) vì 8 mẫu không đủ
để phân tách đuôi. Tệ hơn, P95 ở 50 users (44000 ms) lại _thấp hơn_ ở 10 users
(51000 ms), tỉ số 0.86x, và phần tự sinh phía trên đọc con số đó thành "still has
headroom". Kết luận đó sai. Nguyên nhân là locust chỉ tính request đã hoàn thành: khi
run kết thúc, những request chậm nhất vẫn đang nằm trong hàng đợi và bị loại khỏi
thống kê, nên latency đo được bị thiên lệch xuống. Cùng cơ chế đó khiến effective
concurrency 6.2 là con số **dưới** thực tế — chỉ riêng deferred đã là 21.

Bằng chứng dùng được từ bảng này là hàng throughput: tải chào tăng 5x nhưng throughput
giao được chỉ tăng 1.82x (36% của tuyến tính). Đó là plateau, và nó nhất quán với
deferred khác 0.

**Knob sẽ đổi trước để nâng goodput@SLO: giảm `--parallel` từ 4 xuống 2.**

Lý do là bottleneck ở đây là băng thông bộ nhớ, không phải số slot. `make tune` cho
thấy decode đã chạm trần băng thông từ 4 thread; thêm slot đồng thời không tạo thêm
băng thông, chỉ chia nhỏ nó ra. Với 4 slot chạy song song trên cùng kênh nhớ bão hòa,
mỗi request nhận một phần tư tốc độ decode, nên request nào cũng chậm và request nào
cũng có nguy cơ vi phạm SLO — E2E trung vị 44 giây thì không SLO thực tế nào đạt được.
Giảm xuống 2 slot làm hàng đợi dài hơn nhưng cho mỗi request đang chạy gần gấp đôi
băng thông, nên một phần request về đích trong ngưỡng thay vì toàn bộ cùng trượt.
Goodput@SLO đếm số request kịp hạn, không đếm tổng token, nên đánh đổi này có lợi.

Tăng `--parallel` lên 8 sẽ đi sai hướng: nó nâng raw throughput thêm chút ít nhưng đẩy
mọi request ra xa ngưỡng SLO hơn nữa. Đó đúng là khoảng cách giữa throughput và
goodput mà deck §8 nói tới, và ở máy này khoảng cách đó rất rộng vì trần băng thông
thấp.

Nếu cần số chắc hơn thì phải chạy lại với `-t 3m` để có đủ mẫu cho percentile — với 5
và 8 request thì chỉ gauge của server mới đáng tin.
