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

Where the curve flattens tells you the model ran out of layers to move. Where it
_peaks below_ full offload tells you something did not fit and the accelerator
started paying to fetch weights it could not hold.

## Your finding

**Full offload không phải tốt nhất.** Peak nằm ở `-ngl 8` với 11.8 tok/s, nhanh hơn
CPU-only 1.25x; `-ngl 99` chỉ đạt 10.3 tok/s, tức thua partial offload 13%.

Cái hết trước là **VRAM**, không phải băng thông host-device. MX230 có 2048 MiB tổng,
`make probe` báo 1645 MiB trống. Gemma 4 E2B có 35 layer, model Q4 nặng 2.97 GB, nên 8
layer chiếm khoảng 0.68 GB — vừa khít VRAM khả dụng. Từ 16 layer trở lên là vượt ngưỡng,
và trên Windows WDDM driver không báo lỗi mà lặng lẽ tràn sang shared system memory. Khi
đó GPU phải kéo trọng số qua PCIe 3.0 x4 (~4 GB/s) cho mỗi token, chậm hơn một bậc so với
LPDDR4X hai kênh của CPU (~60 GB/s). Đó là lý do đường cong sụt ngay sau `-ngl 8` thay vì
tiếp tục leo.

Vì sao 8 layer lại _nhanh hơn_ CPU-only, dù băng thông GDDR5 của MX230 (~40 GB/s) còn
thấp hơn RAM hệ thống? Vì hai hệ thống bộ nhớ cùng gánh dòng trọng số cho mỗi token: 8
layer đọc từ VRAM, 27 layer còn lại đọc từ RAM. Tổng byte/giây cao hơn từng bên riêng lẻ.
Decode bị chặn bởi băng thông chứ không bởi compute, nên cộng thêm một kênh nhớ độc lập
là đúng thứ workload này cần — kể cả khi kênh đó chậm hơn.

**Một cảnh báo về độ tin cậy.** Cùng cấu hình `-ngl 0` cho 9.4 tok/s ở sweep này nhưng
10.4 tok/s ở `make tune`, tức 10% chênh giữa hai lần chạy cùng thiết lập. Vậy sàn nhiễu ở
đây khoảng 10%, và toàn bộ dải `-ngl` 16 đến 99 (9.1 đến 10.3 tok/s) nằm trong sàn đó —
không thể phân biệt được với nhau hay với CPU-only. Kết luận duy nhất vượt nhiễu là
`-ngl 8` ở 1.25x. Đường cong không đơn điệu trong dải trên (24 thấp hơn 32, 32 thấp hơn 99) củng cố điều này: đó là nhiễu, không phải xu hướng, và tôi không diễn giải nó.
