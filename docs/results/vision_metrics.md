# Đánh giá thị giác máy tính (tự sinh bởi `report/vision_eval.py`)

Dữ liệu URFD, nửa RGB 320×240 của camera cam0; lớp dương = **NẰM**; khung nhãn 0 (đang ngã) bị bỏ qua.
Chỉ số theo từng khung hình, sau bộ làm mượt (đúng đầu ra hệ thống gửi cho fusion).
Không làm mượt (ảnh gốc): Accuracy 85.5%, Precision 86.9%, Recall 46.7%.
Bộ làm mượt CŨ (đếm lại khi mất dấu 1 khung, ảnh gốc): Accuracy 81.4%, Precision 89.1%, Recall 25.7%.

| Điều kiện | Accuracy | Precision | Recall | F1 | Phát hiện người | Chuỗi ngã được xác nhận | ADL báo nhầm NẰM | ms/khung (TB · p95) |
|---|---|---|---|---|---|---|---|---|
| Gốc | 85.4% | 90.5% | 44.1% | 59.3% | 80.4% | 15/30 | 4/24 | 13.6 · 24.9 |
| Thiếu sáng | 81.1% | 85.2% | 25.8% | 39.6% | 51.3% | 11/30 | 3/24 | 13.5 · 24.3 |
| Nhiễu ảnh | 80.7% | 87.0% | 23.1% | 36.6% | 55.4% | 11/30 | 2/24 | 13.6 · 24.9 |
| Nhòe chuyển động | 82.4% | 79.6% | 36.0% | 49.6% | 39.6% | 18/30 | 3/24 | 12.9 · 23.9 |
| Xa / độ phân giải thấp | 76.3% | 51.1% | 36.7% | 42.7% | 75.9% | 16/30 | 12/24 | 14.0 · 26.3 |
| Che khuất nửa dưới | 71.7% | 20.7% | 6.2% | 9.6% | 41.7% | 1/30 | 10/24 | 14.1 · 25.5 |

*Chuỗi ngã được xác nhận*: camera báo NẰM ở ≥ 50% số khung người thật sự nằm trên sàn.
*ADL báo nhầm NẰM*: trong các video sinh hoạt không có lúc nằm, camera báo NẰM ít nhất một lần.
Thời gian/khung đo trên máy chạy script (MediaPipe Pose Full, CPU).
