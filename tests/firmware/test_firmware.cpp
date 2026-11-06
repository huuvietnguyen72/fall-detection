// Kiểm thử lõi firmware (detector, máy trạng thái, quy đổi trục) trên PC — không cần ESP32.
// Biên dịch & chạy tự động bởi tests/test_firmware.py
#include <cmath>
#include <cstdio>
#include <cstring>
#include <vector>

#include "belt_logic.h"
#include "detector.h"
#include "orientation.h"

using namespace fall;

static int failures = 0;
#define CHECK(cond)                                                         \
    do {                                                                    \
        if (!(cond)) {                                                      \
            printf("FAIL %s:%d  %s\n", __FILE__, __LINE__, #cond);          \
            failures++;                                                     \
        }                                                                   \
    } while (0)

// Tín hiệu giả: đứng thẳng (trọng lực -Y), va chạm `impact_g` tại mẫu `at`, sau đó tư thế `after`
static std::vector<float> make_signal(int n, int at, float impact_g, const float after[3]) {
    std::vector<float> s((size_t)n * kChannels, 0.0f);
    for (int i = 0; i < n; i++) {
        float *p = &s[(size_t)i * kChannels];
        if (i < at) {
            p[1] = -kGravity;
        } else {
            for (int k = 0; k < 3; k++) p[k] = after[k] * kGravity;
        }
        if (i == at) p[0] += impact_g * kGravity;
    }
    return s;
}

static int run(FallDetector &det, const std::vector<float> &s, std::vector<Detection> *out) {
    Detection d;
    int n = 0;
    for (size_t i = 0; i < s.size() / kChannels; i++)
        if (det.push(&s[i * kChannels], &d)) {
            out->push_back(d);
            n++;
        }
    return n;
}

static float classifier_const(const float *, void *ctx) { return *(float *)ctx; }

static void test_lying_after_impact_is_fall() {
    const float lying[3] = {0, 0, 1};  // nằm ngửa: trọng lực theo +Z
    float p = 0.9f;
    FallDetector det(DetectorConfig(), classifier_const, &p);
    std::vector<Detection> ev;
    run(det, make_signal(600, 300, 4.0f, lying), &ev);
    CHECK(ev.size() == 1);
    CHECK(ev[0].fall);
    CHECK(ev[0].peak_index == 300);
    CHECK(std::fabs(ev[0].tilt_deg - 90.0f) < 1.0f);
    CHECK(ev[0].pre_tilt_deg < 1.0f);
}

static void test_low_ai_score_rejects() {
    const float lying[3] = {0, 0, 1};
    float p = 0.1f;
    FallDetector det(DetectorConfig(), classifier_const, &p);
    std::vector<Detection> ev;
    run(det, make_signal(600, 300, 4.0f, lying), &ev);
    CHECK(ev.size() == 1 && !ev[0].fall);
}

static void test_upright_after_impact_rejects_without_running_ai() {
    const float upright[3] = {0, -1, 0};
    float p = 0.99f;
    FallDetector det(DetectorConfig(), classifier_const, &p);
    std::vector<Detection> ev;
    run(det, make_signal(600, 300, 5.0f, upright), &ev);
    CHECK(ev.size() == 1 && !ev[0].fall && !ev[0].ai_used);
}

static void test_already_lying_rejects() {
    // Đang nằm (trọng lực +Z) rồi va chạm, vẫn nằm nghiêng -> không phải té ngã (trở mình trên giường)
    std::vector<float> s((size_t)600 * kChannels, 0.0f);
    for (int i = 0; i < 600; i++) {
        float *q = &s[(size_t)i * kChannels];
        if (i < 300) q[2] = kGravity; else q[0] = kGravity;
        if (i == 300) q[1] += 4.0f * kGravity;
    }
    float p = 0.99f;
    FallDetector det(DetectorConfig(), classifier_const, &p);
    std::vector<Detection> ev;
    run(det, s, &ev);
    CHECK(ev.size() == 1 && !ev[0].fall);
    CHECK(ev[0].pre_tilt_deg > 80.0f);
}

static void test_no_trigger_below_threshold() {
    const float lying[3] = {0, 0, 1};
    FallDetector det;
    std::vector<Detection> ev;
    run(det, make_signal(600, 300, 0.5f, lying), &ev);  // |a| ~ 1.1 g
    CHECK(ev.empty());
}

static void test_detection_latency_is_2_5s() {
    const float lying[3] = {0, 0, 1};
    FallDetector det;
    auto s = make_signal(600, 300, 4.0f, lying);
    Detection d;
    int at = -1;
    for (int i = 0; i < 600 && at < 0; i++)
        if (det.push(&s[(size_t)i * kChannels], &d)) at = i;
    CHECK(at == 300 + kTiltPost);
}

static void test_multiple_peaks_all_evaluated() {
    // Bước chạy (đỉnh 3 g, vẫn đứng) rồi ngã ngay sau 0.6 s -> cả 2 đỉnh đều được xét, đỉnh 2 là té ngã
    std::vector<float> s((size_t)800 * kChannels, 0.0f);
    for (int i = 0; i < 800; i++) {
        float *q = &s[(size_t)i * kChannels];
        if (i < 330) q[1] = -kGravity; else q[2] = kGravity;
    }
    s[(size_t)300 * kChannels + 0] += 3.0f * kGravity;
    s[(size_t)330 * kChannels + 0] += 5.0f * kGravity;
    float p = 0.9f;
    DetectorConfig cfg;
    cfg.refine_samples = 10;
    FallDetector det(cfg, classifier_const, &p);
    std::vector<Detection> ev;
    run(det, s, &ev);
    CHECK(ev.size() == 2);
    CHECK(ev.size() == 2 && ev[1].fall && ev[1].peak_index == 330);
}

static void test_belt_controller_flow() {
    BeltController b(15000, 20000);
    CHECK(b.on_fall(0) == BeltEvent::SendImpact);
    CHECK(b.state() == BeltState::Alarm);
    CHECK(b.remaining_s(0) == 15);
    CHECK(b.remaining_s(5500) == 10);
    CHECK(b.on_fall(100) == BeltEvent::None);       // đang báo động: bỏ qua
    CHECK(b.on_button(5000) == BeltEvent::SendCancel);
    CHECK(b.state() == BeltState::Idle);

    b.on_fall(10000);
    b.tick(25000, true);
    CHECK(b.state() == BeltState::WaitServer);
    b.on_command("sos", 26000);
    CHECK(b.state() == BeltState::Sos);
    CHECK(b.outputs(26000, true).led_red);
    CHECK(b.on_button(30000) == BeltEvent::SendCancel);

    b.on_fall(40000);
    b.on_command("dismiss", 42000);                   // camera thấy đứng -> báo giả
    CHECK(b.state() == BeltState::Idle);

    b.on_fall(50000);
    b.tick(65000, false);                             // offline khi hết giờ -> SOS tại chỗ
    CHECK(b.state() == BeltState::Sos);
    b.on_command("reset", 66000);

    b.on_fall(70000);
    b.tick(85000, true);
    b.tick(105001, true);                             // server im lặng quá lâu -> SOS tại chỗ
    CHECK(b.state() == BeltState::Sos);
}

static void test_millis_wraparound() {
    BeltController b(15000, 20000);
    const uint32_t t0 = 0xFFFFF000u;  // millis() sắp tràn
    b.on_fall(t0);
    b.tick(t0 + 14000, true);
    CHECK(b.state() == BeltState::Alarm);
    b.tick(t0 + 15000, true);  // đã tràn qua 0
    CHECK(b.state() == BeltState::WaitServer);
}

static void test_axis_config_map() {
    const int order[3] = {0, 1, 2}, sign[3] = {-1, -1, 1};
    AxisMap m = axis_map_from_config(order, sign);
    const float in[3] = {1, 2, 3};
    float out[3];
    axis_map_apply(m, in, out);
    CHECK(out[0] == -1 && out[1] == -2 && out[2] == 3);
}

static void rotate(const float r[3][3], const float v[3], float out[3]) {
    for (int i = 0; i < 3; i++) out[i] = r[i][0] * v[0] + r[i][1] * v[1] + r[i][2] * v[2];
}

static void test_axis_calibration_recovers_mounting() {
    // Cảm biến lắp tùy ý: R biến vector hệ SisFall -> hệ cảm biến (một phép quay thuận)
    const float R[3][3] = {{0, 0, 1}, {1, 0, 0}, {0, 1, 0}};
    const float up_sisfall[3] = {0, -kGravity, 0};                 // đứng: gia tốc kế chỉ lên
    const float a = 40.0f * 3.14159265f / 180.0f;                  // cúi 40° về trước
    const float bow_sisfall[3] = {0, -kGravity * cosf(a), -kGravity * sinf(a)};
    float stand[3], bow[3];
    rotate(R, up_sisfall, stand);
    rotate(R, bow_sisfall, bow);
    AxisMap m;
    CHECK(axis_map_calibrate(stand, bow, &m));
    const float probe_sisfall[3] = {1, 2, 3};
    float probe_sensor[3], back[3];
    rotate(R, probe_sisfall, probe_sensor);
    axis_map_apply(m, probe_sensor, back);
    for (int k = 0; k < 3; k++) CHECK(std::fabs(back[k] - probe_sisfall[k]) < 1e-3f);
    CHECK(!axis_map_calibrate(stand, stand, &m));  // không cúi -> từ chối
}

int main() {
    test_lying_after_impact_is_fall();
    test_low_ai_score_rejects();
    test_upright_after_impact_rejects_without_running_ai();
    test_already_lying_rejects();
    test_no_trigger_below_threshold();
    test_detection_latency_is_2_5s();
    test_multiple_peaks_all_evaluated();
    test_belt_controller_flow();
    test_millis_wraparound();
    test_axis_config_map();
    test_axis_calibration_recovers_mounting();
    printf(failures ? "%d FAILED\n" : "ALL PASSED\n", failures);
    return failures ? 1 : 0;
}
