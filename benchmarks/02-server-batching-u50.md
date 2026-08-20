# 02 - Continuous batching under load (u50)

Host `Windows-AMD64` · `--parallel 4` · 14 samples over
60s at 2.0s intervals · raw CSV: `02-server-metrics-u50.csv`

| Gauge                                  |                            Peak observed |
| :------------------------------------- | ---------------------------------------: |
| `n_busy_slots_per_decode` (avg/decode) |                    3.51 of 4 slots (88%) |
| `requests_processing`                  |                                        4 |
| `requests_deferred`                    |                                       21 |
| `kv_cache_usage_ratio`                 | n/a — not exported by llama.cpp `b10488` |
| `tokens_predicted_total` (final)       |                                     1064 |

Highest sampled value was **3.51 of 4** slots. Note this gauge is llama.cpp's _average_ busy slots per decode step, so the number below is the highest average we sampled, not an instantaneous maximum batch width. A peak near 1 means
requests were served one at a time -- either the load was too light to overlap, or
they arrived too far apart. A peak approaching `--parallel` means the scheduler was
genuinely packing concurrent requests into shared decode steps.
`requests_deferred` went above zero: more requests arrived than there were slots, so some waited. That wait is the queue time in your P95.

## Your observation

Peak batch width là **3.51 / 4 slots (88%)**, kèm `requests_deferred = 21` và
`requests_processing = 4`. Batching hoạt động thật: gauge tiệm cận `--parallel` chứ
không quanh 1, nghĩa là scheduler đang nhồi nhiều request vào chung một bước decode.

Hai con số này **có vẻ** mâu thuẫn với `02-server-results.md`, nơi effective
concurrency tính bằng Little's Law chỉ ra 6.2. Nếu 6.2 request thực sự nằm trong hệ
thống mà chỉ có 4 slot, thì phải có khoảng 2 request đang chờ — trong khi deferred đã
đếm tới 21.

Tôi tin gauge của server, không tin Little's Law ở đây. Lý do là đầu vào của Little's
Law đến từ locust, mà locust chỉ tính request đã hoàn thành: chỉ 8 request về đích
trong 60 giây, còn những request chậm nhất vẫn nằm trong hàng đợi khi run kết thúc và
bị loại khỏi thống kê. Điều đó kéo cả latency trung bình lẫn RPS xuống, nên tích của
chúng là ước lượng **dưới** thực tế. Gauge `/metrics` thì đo trực tiếp từ scheduler,
không phụ thuộc request có kịp hoàn thành trong cửa sổ đo hay không.

Một lưu ý khi đọc 3.51: đây là trung bình số slot bận trên mỗi bước decode, lấy giá
trị mẫu cao nhất trong 14 mẫu, không phải bề rộng batch tức thời lớn nhất. Bề rộng
tức thời chạm 4 (thấy ở `requests_processing = 4`); 3.51 thấp hơn vì trong cùng một
cửa sổ lấy mẫu có những bước decode chỉ còn 3 slot bận khi một request vừa kết thúc và
request kế tiếp chưa được nạp vào.
