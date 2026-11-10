# Độ trễ hệ thống (tự sinh bởi `report/latency_bench.py`)

## Truyền tin và xử lý (BENCH, 30 lần, cùng máy)

| Chặng | Trung vị (ms) | TB (ms) | p95 (ms) | Min–Max (ms) |
|---|---|---|---|---|
| Đai → server (MQTT QoS1 + xử lý) | 0.62 | 1.19 | 1.16 | 0.22–17.62 |
| Camera → server (MQTT QoS0 + xử lý) | 0.56 | 0.58 | 0.93 | 0.11–13.54 |
| Hết đếm ngược → quyết định SOS | 43.94 | 44.04 | 51.55 | 28.98–81.66 |
| Quyết định → lệnh SOS tới đai | 0.84 | 0.84 | 1.47 | 0.28–1.81 |
| Yêu cầu → nhận ảnh hiện trường (30 KB) | 2.16 | 1.94 | 3.08 | 0.62–3.42 |

Một bước `FusionEngine.tick()`: **0.5 µs** CPU.

## Telegram API

getMe: trung vị **216 ms**, p95 521 ms (10 lần).

## Ngân sách thời gian từ lúc ngã đến khi gửi cảnh báo

| Giai đoạn | Thời gian |
|---|---|
| Đai xét va chạm | 2.50 s |
| Đai → server | 0.6 ms |
| Đếm ngược cho phép hủy | 15.00 s |
| quyết định | 43.9 ms |
| ảnh | 2.2 ms |
| Telegram API | 215.8 ms |
| **Tổng** | **17.76 s** |

Đếm ngược 15 s là thời gian CỐ Ý chờ người dùng bấm hủy (giảm báo nhầm), không phải độ trễ xử lý.
