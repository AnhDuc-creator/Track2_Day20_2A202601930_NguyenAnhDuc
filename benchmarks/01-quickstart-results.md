# 01 - Measure: latency baseline

Model `Gemma 4 E2B` · host `Windows-AMD64` · llama.cpp `b10488`
Settings: `threads=4` `ngl=0` `ctx=2048`
`max_tokens=64` · warm-up discarded
Completed requests: `UD-Q4_K_XL` 10/10 · `UD-Q2_K_XL` 10/10

| Quantization | Size (GB) | Load (ms) | TTFT P50/P95 (ms) | TPOT P50/P95 (ms) |  E2E P50/P95/P99 (ms) | Decode (tok/s) |
| :----------- | --------: | --------: | ----------------: | ----------------: | --------------------: | -------------: |
| UD-Q4_K_XL   |      2.97 |      8685 |       2074 / 2777 |     129.1 / 164.2 | 10085 / 12361 / 12361 |            7.7 |
| UD-Q2_K_XL   |      2.24 |      5995 |       2012 / 3855 |     125.4 / 220.5 |  9824 / 17747 / 17747 |            8.0 |

- **TTFT** = prefill. Short prompts keep it small; long-context RAG is where it explodes.
- **TPOT** = per-output-token decode cost, bounded by memory bandwidth. `decode tok/s = 1000 / TPOT_p50`.
- `UD-Q2_K_XL` decodes **1.04x faster** than `UD-Q4_K_XL` here, for 0.73 GB less on disk.

## Your observation

Trên máy này (i5-1035G1, 4 nhân vật lý, `ngl=0`, `threads=4`), bản 2-bit **không đáng dùng**.

Decode chỉ nhanh hơn 1.04x (8.0 so với 7.7 tok/s), tức khoảng 4%, đổi lấy 0.73 GB dung
lượng. Đây là mức chênh nhỏ hơn hẳn kỳ vọng thông thường cho việc giảm từ 4-bit xuống
2-bit, và lý do nằm ở chỗ decode trên CPU này bị chặn bởi băng thông bộ nhớ chứ không
phải dung lượng: cả hai model đều lớn hơn nhiều so với cache, nên mỗi token vẫn phải
kéo toàn bộ trọng số từ RAM. Giảm số byte đi 25% chỉ dịch chuyển được một phần nhỏ vì
k-quant 2-bit cần nhiều thao tác giải nén hơn cho mỗi byte đọc vào, ăn lại phần lợi.

Quan trọng hơn con số trung vị: bản 2-bit **tệ hơn ở đuôi phân phối**. TTFT P95 là
3855 ms so với 2777 ms, và TPOT P95 là 220.5 ms so với 164.2 ms. E2E P95 chênh rất
lớn, 17747 ms so với 12361 ms. Nếu SLO đặt theo P95 thì bản 2-bit thua ở đúng chỉ số
người dùng cảm nhận được, dù thắng sát nút ở P50.

Với 23.8 GB RAM, tiết kiệm 0.73 GB không giải quyết vấn đề gì. Kết luận: giữ
`UD-Q4_K_XL`, vì nó vừa ổn định hơn ở P95 vừa bảo toàn chất lượng suy luận. Bản 2-bit
chỉ đáng cân nhắc trên máy dưới 8 GB RAM, nơi 0.73 GB là khác biệt giữa chạy được và
không chạy được.
