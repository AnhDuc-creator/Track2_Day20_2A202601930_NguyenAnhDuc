# Bonus - GPU offload sweep

Host `Windows-AMD64` · backend(s) `nvidia_cuda, vulkan` ·
llama.cpp `b10488` · `threads=4` · metric `tg128`

| -ngl | tg128 (tok/s) | vs -ngl 0 | vs best |
| :--- | ------------: | --------: | ------: |
| 0    |           9.4 |     1.00x |     80% |
| 8    |          11.8 |     1.25x |    100% |
| 16   |           9.2 |     0.98x |     78% |
| 24   |           9.1 |     0.96x |     77% |
| 32   |           9.6 |     1.02x |     81% |
| 99   |          10.3 |     1.09x |     87% |

Best: `-ngl 8` at 11.8 tok/s
-- 1.25x faster than CPU-only.

> ⚠️ **Bảng và hai dòng kết luận ngay trên là output tự sinh của `-r 2` và KHÔNG tái lập
> được.** Chạy lại với `-r 5` cho `-ngl 8` = 9.10 tok/s, tức **chậm hơn** CPU-only
> (10.18). Đọc phần "Your finding" bên dưới trước khi dùng bất kỳ số nào ở đây.

Where the curve flattens tells you the model ran out of layers to move. Where it
_peaks below_ full offload tells you something did not fit and the accelerator
started paying to fetch weights it could not hold.

## Your finding

> **Bảng phía trên là dữ liệu gốc chạy với `-r 2` và tôi giữ nguyên làm hiện vật.** Khi
> đi xác minh cơ chế đằng sau nó, cả hai kết luận tôi rút ra ban đầu đều **sai**. Phần
> dưới là số đo, và cuối cùng là những gì tôi vẫn **chưa** giải thích được. Dữ liệu thô:
> `benchmarks/bonus-gpu-offload-verify.json`.

### Rút lại kết luận cũ số 1: "VRAM hết trước" — sai

Tôi đã dựng lại `llama-server` với đúng cấu hình track 02 (`-t 4 --ctx-size 2048
--parallel 4`) ở từng mức `-ngl`, đọc dòng đặt buffer trong log khởi động và lấy
`nvidia-smi --query-gpu=memory.used` trong lúc server còn sống:

| `-ngl` | log: offloaded | CUDA0 model buffer | CPU_Mapped model buffer | nvidia-smi used / 2048 MiB |
| :----- | :------------- | -----------------: | ----------------------: | -------------------------: |
| 0      | `0/36`         |               — | 3021.89 MiB |  **151 MiB** |
| 8      | `8/36`         |  549.66 MiB | 2736.23 MiB |  **713 MiB** |
| 16     | `16/36`        |  871.62 MiB | 2414.27 MiB | **1047 MiB** |
| 99     | `36/36`        | 1481.89 MiB | 1804.00 MiB | **1677 MiB** |

**VRAM không bao giờ hết.** Ngay cả full offload (`36/36` layer) cũng chỉ dùng 1677 trên
2048 MiB — còn thừa 371 MiB. Không có mức `-ngl` nào tràn sang shared system memory, và
llama.cpp cũng không hề báo tràn. Câu "từ 16 layer trở lên là vượt ngưỡng" ở bản trước
là suy diễn, không phải quan sát: 16 layer chỉ chiếm 871.62 MiB, thừa sức nằm trong
1645 MiB trống. Con số "8 layer ≈ 0.68 GB vừa khít 1645 MiB" cũng sai về số học ngay từ
đầu — 0.68 GB là 696 MiB, chưa tới một nửa chỗ trống.

Hai chi tiết nữa từ cùng log, để loại trừ các cách giải thích khác:

- Bộ auto-fit của build này **không** ghi đè `-ngl` của tôi: log ghi
  `n_gpu_layers already set by user to N, abort` ở cả bốn lần chạy.
- Dòng `cannot meet free memory target of 1024 MiB` **không** phải OOM. Đó là ngưỡng dự
  trữ theo heuristic; server vẫn nạp và phục vụ bình thường ở mọi mức `-ngl`.

Một hệ quả phụ đáng chú ý: ở `-ngl 0` GPU vẫn giữ **151 MiB**, vì llama.cpp đăng ký CUDA
làm compute device và cấp `CUDA0 compute buffer size = 118.88 MiB` kể cả khi không
offload layer nào. Nghĩa là "chạy CPU-only" trên build này **không** đồng nghĩa với
0 MiB VRAM.

### Rút lại kết luận cũ số 2: "1.25x nhờ cộng băng thông hai kênh nhớ" — không tái lập được

Sweep gốc chạy `-r 2`. Tôi chạy lại đúng `llama-bench` đó với `-r 5`:

| `-ngl` | Sweep gốc (`-r 2`) | Chạy lại (`-r 5`) | Từng rep (`-r 5`)                        |
| :----- | -----------------: | ----------------: | :--------------------------------------- |
| 0      |          9.4 tok/s | **10.18 ± 0.46**  | 10.64 · 10.40 · 10.17 · 10.26 · 9.41     |
| 8      |     **11.8** tok/s | **9.10 ± 1.77**   | 10.75 · 10.52 · 9.83 · **7.39 · 7.00**   |
| 16     |          9.2 tok/s | **4.82 ± 0.72**   | 6.09 · 4.68 · 4.48 · 4.58 · 4.29         |
| 99     |         10.3 tok/s | **7.52 ± 2.68**   | 10.51 · 10.15 · **6.86 · 4.95 · 5.13**   |

`-ngl 8` **chậm hơn** CPU-only chứ không nhanh hơn 1.25x. Con số 11.8 không tái lập.

Lập luận "hai hệ thống bộ nhớ cùng gánh nên tổng byte/giây cao hơn" ở bản trước còn sai
cả về nguyên lý, không chỉ về số: các layer chạy **tuần tự**, layer trên GPU phải xong
mới tới layer trên CPU, nên băng thông hai bên **không chồng lấn** trong cùng một token.
Thời gian cộng lại chứ không song song. Tôi đã viết một cơ chế nghe hợp lý để khớp với
một con số, và đó chính là lỗi cần tránh.

### Cái tôi quan sát được nhưng **chưa** giải thích được

Mọi cấu hình có GPU đều tụt mạnh **trong lòng một lần chạy**, còn CPU-only thì không:

- `-ngl 8`: 10.75 → 7.00 (giảm 35% từ rep 1 đến rep 5)
- `-ngl 99`: 10.51 → 5.13 (giảm 51%)
- `-ngl 0`: 10.64 → 9.41 (giảm 12%)

Độ lệch chuẩn nói cùng một điều: 0.46 tok/s ở `-ngl 0` so với 1.77–2.68 tok/s khi GPU
tham gia. Hai rep đầu của mọi cấu hình GPU đều quanh 10.1–10.75, tức **xấp xỉ CPU-only**;
mức sụt chỉ đến sau đó. Điều này giải thích được vì sao sweep gốc `-r 2` cho toàn số đẹp:
nó chỉ lấy mẫu đúng cửa sổ "còn nguội".

**Tôi không xác định được nguyên nhân của mức sụt đó.** Các giả thuyết còn lại, chưa cái
nào được kiểm chứng:

1. **Trần nhiệt / trần công suất dùng chung.** i5-1035G1 là chip 15 W và MX230 nằm cùng
   khung máy; GPU hoạt động có thể lấy mất phần công suất của CPU, mà CPU vẫn đang chạy
   phần lớn số layer. Chưa kiểm chứng: tôi chưa đo xung nhịp, nhiệt độ hay điện năng.
2. **Quản lý power-state của driver trên WDDM** (đổi P-state, hạ xung khi tải không đều).
3. **Chi phí đồng bộ host–device mỗi token** ở cấu hình chia đôi, tăng dần khi hàng đợi
   lệnh bị lấp đầy.
4. Mức `-ngl 16` không khớp với hình mẫu "hai rep đầu còn nhanh" (rep 1 đã chỉ 6.09),
   nên có thể còn một yếu tố thứ hai chồng lên. Chưa giải thích được.

Để kết luận dứt điểm thì cần đo `nvidia-smi --query-gpu=clocks.sm,temperature.gpu,power.draw`
lấy mẫu theo thời gian **trong lúc** bench chạy, và xen kẽ thứ tự các mức `-ngl` để tách
hiệu ứng tích nhiệt khỏi hiệu ứng của chính `-ngl`. Tôi chưa làm phần đó.

### Kết luận dùng được

Trên máy này, **GPU offload không cho lợi ích nào chứng minh được**, và lựa chọn `ngl=0`
cho toàn bộ base track là đúng — nhưng đúng vì lý do khác với lý do tôi viết ban đầu.
Không phải vì "model không vừa VRAM" (phần offload được thì vừa), mà vì MX230 không đem
lại throughput cao hơn và làm phép đo mất ổn định hẳn. Bài học phương pháp: `-r 2` là quá
ít để kết luận bất cứ điều gì trên một laptop mỏng, và một cơ chế nghe hợp lý không thay
thế được một phép đo.
