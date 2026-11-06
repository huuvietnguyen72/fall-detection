// Cầu nối tới model Edge Impulse (dùng chung cho ESP32 và bản chạy trên PC).
#pragma once

namespace fall {

// Cửa sổ 100 mẫu x 6 trục (ax,ay,az [m/s²], gx,gy,gz [rad/s]) -> P(Fall), hoặc -1 nếu lỗi / không có model.
float ei_fall_probability(const float *window, void *ctx);
const char *ei_model_name();  // "" nếu biên dịch không kèm model

}  // namespace fall
