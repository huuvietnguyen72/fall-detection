# Chỉ số đánh giá AI (tự sinh bởi `report/ai_metrics.py`)

Cấu hình: kích hoạt ≥ 1.8 g · P(Ngã) ≥ 0.5 · nghiêng thêm ≥ 30° · trước va chạm ≤ 65° · model `Fall-Detection-SisFall_inferencing.zip`

Lớp dương = **Ngã**. Recall = tỉ lệ ca ngã được phát hiện; Specificity = tỉ lệ sinh hoạt không bị báo nhầm.

| Đánh giá | N | Accuracy | Precision | Recall (Sensitivity) | Specificity | F1 | TP | FP | FN | TN |
|---|---|---|---|---|---|---|---|---|---|---|
| Hệ thống trên đai · SisFall (bản ghi) | 4500 | 98.0% | 99.0% | 96.0% | 99.3% | 97.5% | 1726 | 18 | 72 | 2684 |
