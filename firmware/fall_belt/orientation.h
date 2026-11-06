// Quy đổi trục cảm biến -> hệ trục của dataset SisFall (X phải, Y xuống chân, Z ra trước bụng).
// Model AI được train trên hệ trục này nên MPU6050 phải được quy đổi đúng.
//
// Hai cách:
//   1. Cố định theo cách lắp (AXIS_ORDER / AXIS_SIGN trong config.h)
//   2. Hiệu chuẩn bằng nút bấm: đứng thẳng (đo trọng lực) rồi cúi người về trước (đo hướng trước)
#pragma once

namespace fall {

struct AxisMap {
    float m[3][3];  // v_sisfall = m * v_sensor (mỗi hàng là 1 trục SisFall biểu diễn trong hệ cảm biến)
};

AxisMap axis_map_from_config(const int order[3], const int sign[3]);
// stand: gia tốc đo khi đứng thẳng yên; bow: khi cúi người về trước (>= 20°). Trả false nếu không hợp lệ.
bool axis_map_calibrate(const float stand[3], const float bow[3], AxisMap *out);
void axis_map_apply(const AxisMap &map, const float in[3], float out[3]);

}  // namespace fall
