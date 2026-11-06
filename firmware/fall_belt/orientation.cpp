#include "orientation.h"

#include <math.h>
#include <string.h>

namespace fall {

static float norm3(const float v[3]) { return sqrtf(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]); }

static void cross3(const float a[3], const float b[3], float out[3]) {
    out[0] = a[1] * b[2] - a[2] * b[1];
    out[1] = a[2] * b[0] - a[0] * b[2];
    out[2] = a[0] * b[1] - a[1] * b[0];
}

AxisMap axis_map_from_config(const int order[3], const int sign[3]) {
    AxisMap map;
    memset(&map, 0, sizeof(map));
    for (int i = 0; i < 3; i++) map.m[i][order[i]] = (float)sign[i];
    return map;
}

bool axis_map_calibrate(const float stand[3], const float bow[3], AxisMap *out) {
    const float ns = norm3(stand), nb = norm3(bow);
    if (ns < 5.0f || nb < 5.0f) return false;  // không đứng yên (phải đo được ~1 g)

    // Gia tốc kế khi đứng yên chỉ hướng LÊN -> trục Y (xuống) ngược chiều
    float up[3] = {stand[0] / ns, stand[1] / ns, stand[2] / ns};
    // Cúi về trước: hướng "lên" đo được nghiêng về phía LƯNG -> trục trước = ngược thành phần ngang
    const float d = (bow[0] * up[0] + bow[1] * up[1] + bow[2] * up[2]) / nb;
    if (d > cosf(20.0f * 3.14159265f / 180.0f)) return false;  // cúi chưa đủ 20°
    float fwd[3] = {-(bow[0] / nb - d * up[0]), -(bow[1] / nb - d * up[1]), -(bow[2] / nb - d * up[2])};
    const float nf = norm3(fwd);
    for (float &v : fwd) v /= nf;

    float y[3] = {-up[0], -up[1], -up[2]};
    float x[3];
    cross3(y, fwd, x);  // X = Y x Z (hệ thuận tay phải)
    for (int i = 0; i < 3; i++) {
        out->m[0][i] = x[i];
        out->m[1][i] = y[i];
        out->m[2][i] = fwd[i];
    }
    return true;
}

void axis_map_apply(const AxisMap &map, const float in[3], float out[3]) {
    for (int r = 0; r < 3; r++) out[r] = map.m[r][0] * in[0] + map.m[r][1] * in[1] + map.m[r][2] * in[2];
}

}  // namespace fall
