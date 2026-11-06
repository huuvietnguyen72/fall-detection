// Bộ phát hiện té ngã — C++ thuần, không phụ thuộc Arduino (được kiểm thử trên PC với 4505 bản ghi SisFall).
//
// Quy trình (khớp cách tạo dữ liệu train của model Edge Impulse "Fall-Detection-SisFall"):
//   1. |a| vượt TRIGGER (2.0 g) -> đỉnh = mẫu lớn nhất trong 0.5 s kế tiếp; xếp vào hàng đợi
//      (nhiều đỉnh liên tiếp, vd. bước chạy rồi ngã, đều được xét — không bỏ sót)
//   2. Đủ 2.5 s sau đỉnh thì xét:
//      a. AI: model trên cửa sổ 2 s có đỉnh ở chính giữa (mẫu 50/100)    -> P(Fall)
//      b. Thân nghiêng thêm: hướng trọng lực [-2 s,-1 s] so với [+1 s,+2.5 s]  -> tilt
//      c. Tư thế trước va chạm: thân lệch phương thẳng đứng bao nhiêu         -> pre_tilt
//   3. Té ngã <=> P(Fall) >= ai_threshold  VÀ  tilt >= min_tilt  VÀ  pre_tilt <= max_pre_tilt
//      (pre_tilt loại trường hợp đang nằm trên giường rồi trở mình)
//
// Mẫu đầu vào (50 Hz, hệ trục SisFall: X phải, Y xuống chân, Z ra trước):
//   ax, ay, az [m/s²], gx, gy, gz [rad/s]
#pragma once
#include <stdint.h>

namespace fall {

constexpr int kChannels = 6;
constexpr int kWindow = 100;        // 2 s @ 50 Hz — đầu vào model
constexpr int kHalf = kWindow / 2;  // đỉnh nằm ở mẫu 50
constexpr int kTiltPre = 100;       // trọng lực trước đỉnh: [peak-100, peak-50)
constexpr int kTiltPost = 125;      // sau đỉnh: [peak+50, peak+125] -> kết luận 2.5 s sau đỉnh
constexpr int kBuffer = 256;        // >= kTiltPre + kTiltPost + 1
constexpr int kMaxPending = 8;      // số đỉnh chờ xét cùng lúc
constexpr float kGravity = 9.80665f;

struct DetectorConfig {
    float trigger_g = 2.0f;        // ngưỡng |a| để bắt đầu xét
    int refine_samples = 25;       // tìm đỉnh cao nhất trong 0.5 s sau khi vượt ngưỡng
    float ai_threshold = 0.5f;     // P(Fall) tối thiểu
    float min_tilt_deg = 30.0f;    // thân phải nghiêng thêm ít nhất bấy nhiêu độ
    float max_pre_tilt_deg = 65.0f;// trước va chạm thân phải gần thẳng đứng (đứng/ngồi)
};

struct Detection {
    bool fall;           // kết luận cuối cùng
    bool ai_used;        // có chạy model AI không
    float ai_score;      // P(Fall) (1.0 nếu không dùng AI)
    float tilt_deg;      // thân nghiêng thêm sau va chạm
    float pre_tilt_deg;  // độ lệch thân so với phương thẳng đứng trước va chạm
    float peak_g;        // độ lớn gia tốc tại đỉnh [g]
    uint32_t peak_index;
    uint32_t infer_us;   // thời gian chạy model
};

// Nhận cửa sổ kWindow x kChannels (xếp theo từng mẫu), trả P(Fall) hoặc < 0 nếu lỗi.
typedef float (*ClassifierFn)(const float *window, void *ctx);
typedef uint32_t (*MicrosFn)();

float angle_between_deg(const float a[3], const float b[3]);
// Góc giữa thân người và phương thẳng đứng, từ gia tốc đo được (hệ SisFall) khi tương đối yên.
float trunk_tilt_deg(const float accel[3]);

class FallDetector {
public:
    FallDetector(const DetectorConfig &cfg = DetectorConfig(), ClassifierFn classifier = nullptr,
                 void *ctx = nullptr, MicrosFn micros = nullptr);

    // Đưa 1 mẫu vào. Trả true khi vừa xét xong một va chạm (kết quả ghi vào *out).
    bool push(const float sample[kChannels], Detection *out);
    void reset();

    bool busy() const { return pending_count_ > 0 || refining_; }
    float magnitude_g() const { return last_mag_g_; }
    uint32_t samples() const { return count_; }
    const DetectorConfig &config() const { return cfg_; }
    void set_config(const DetectorConfig &cfg) { cfg_ = cfg; }

private:
    const float *at(uint32_t index) const { return buf_[index % kBuffer]; }
    void mean_accel(uint32_t from, uint32_t to_inclusive, float out[3]) const;
    Detection evaluate(uint32_t peak, float peak_g);

    DetectorConfig cfg_;
    ClassifierFn classifier_;
    void *ctx_;
    MicrosFn micros_;
    float buf_[kBuffer][kChannels];
    float window_[kWindow * kChannels];
    uint32_t count_ = 0;
    float last_mag_g_ = 0;

    bool armed_ = true;      // phải xuống dưới ngưỡng rồi mới bắt va chạm mới (trễ)
    bool refining_ = false;
    uint32_t refine_peak_ = 0, refine_end_ = 0;
    float refine_g_ = 0;

    uint32_t pending_peak_[kMaxPending];
    float pending_g_[kMaxPending];
    int pending_head_ = 0, pending_count_ = 0;
};

}  // namespace fall
