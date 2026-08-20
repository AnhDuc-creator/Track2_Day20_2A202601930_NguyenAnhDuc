# 01 - Tune: thread-count sweep

Model `gemma-4-E2B-it-UD-Q4_K_XL.gguf` · host `Windows-AMD64` · llama.cpp `b10488`
CPU: **4 physical · 8 logical** cores · `ngl=0` · metric `tg128`

| threads (-t) | tg128 (tok/s) | vs best |
| :----------- | ------------: | ------: |
| 1            |           5.3 |     51% |
| 2            |           8.0 |     77% |
| 4            |          10.4 |    100% |
| 8            |          10.0 |     97% |
| 16           |           7.6 |     73% |

**Best**: `-t 4` at 10.4 tok/s
**Slowest tested**: `-t 1` at 5.3 tok/s (1.95x spread)
**Against the physical-core default** (`-t 4`, 10.4 tok/s): 1.00x

Use this in your run:

```bash
LAB_N_THREADS=4 make bench
```

## Your explanation

Knee nằm ở `-t 4`, đúng bằng số nhân vật lý (10.4 tok/s). Curve leo dốc từ 1 đến 4
(5.3 → 8.0 → 10.4), gần như phẳng ở 8 (10.0, tức 97%), rồi tụt rõ ở 16 (7.6, tức 73%).

Từ 1 đến 4 thread, mỗi thread thêm vào mang theo một nhân vật lý với đơn vị vector và
đường dẫn cache riêng, nên throughput tăng thật. Nhưng mức tăng đã dưới tuyến tính:
gấp 4 lần thread chỉ cho 1.95 lần throughput. Đó là dấu hiệu decode chạm trần băng
thông bộ nhớ từ trước khi hết nhân — model 2.97 GB phải được đọc lại toàn bộ cho mỗi
token, và i5-1035G1 là chip 15W với LPDDR4X hai kênh, nên kênh nhớ bão hòa trước khi
compute bão hòa.

Từ 4 lên 8, throughput không tăng mà giảm nhẹ 3%. i5-1035G1 có 4 nhân vật lý và 8
luồng logic, nên 4 thread thêm vào chỉ là các luồng SMT dùng chung đơn vị AVX-512, L1
và L2 của cùng một nhân vật lý. Chúng không mang thêm băng thông, chỉ chia nhỏ tài
nguyên sẵn có, và mỗi bước ma trận vẫn phải chờ đồng bộ ở cuối. Kết quả hòa vốn là hợp
lý cho một workload đã bị chặn bởi bộ nhớ.

Từ 8 lên 16 mới là mức phạt thật, mất 27%. Ở đây có 16 thread tranh 8 luồng logic, nên
OS phải preempt liên tục. Mỗi lần context switch làm mất working set trong L2, và vì
mọi thread đều đang stream cùng một khối trọng số nên chúng đá lẫn nhau ra khỏi cache
thay vì chia sẻ. Chi phí đồng bộ ở cuối mỗi lớp cũng tăng theo số thread.

Điểm cần nói rõ: kết quả này **không** cho một speedup dùng được cho §5. Best `-t 4`
trùng đúng mặc định của lab (số nhân vật lý), nên tỉ số so với mặc định là 1.00x. Bài
học ở đây mang tính xác nhận chứ không phải tối ưu — mặc định đã đúng, và giá trị của
sweep là chứng minh rằng tăng thread không phải hướng đi, chứ không phải tìm ra cấu
hình tốt hơn. Con số đáng chú ý cho việc tuning thực tế là spread 1.95x giữa `-t 1` và
`-t 4`: chọn sai thread count theo hướng quá ít gây thiệt hại lớn hơn nhiều so với
chọn quá nhiều.
