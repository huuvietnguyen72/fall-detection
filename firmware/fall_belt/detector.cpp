#include "detector.h"

#include <math.h>
#include <string.h>

namespace fall {

float angle_between_deg(const float a[3], const float b[3]) {
    const float dot = a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
    const float na = sqrtf(a[0] * a[0] + a[1] * a[1] + a[2] * a[2]);
    const float nb = sqrtf(b[0] * b[0] + b[1] * b[1] + b[2] * b[2]);
    if (na < 1e-6f || nb < 1e-6f) return 0.0f;
    float c = dot / (na * nb);
    c = c > 1.0f ? 1.0f : (c < -1.0f ? -1.0f : c);
    return acosf(c) * 57.29578f;
}

float trunk_tilt_deg(const float accel[3]) {
    static const float kUpright[3] = {0.0f, -1.0f, 0.0f};  // đứng thẳng: gia tốc kế chỉ lên = -Y
    return angle_between_deg(accel, kUpright);
}

FallDetector::FallDetector(const DetectorConfig &cfg, ClassifierFn classifier, void *ctx, MicrosFn micros)
    : cfg_(cfg), classifier_(classifier), ctx_(ctx), micros_(micros) {
    reset();
}

void FallDetector::reset() {
    memset(buf_, 0, sizeof(buf_));
    count_ = 0;
    last_mag_g_ = 0;
    armed_ = true;
    refining_ = false;
    pending_head_ = pending_count_ = 0;
}

void FallDetector::mean_accel(uint32_t from, uint32_t to_inclusive, float out[3]) const {
    out[0] = out[1] = out[2] = 0;
    for (uint32_t i = from; i <= to_inclusive; i++) {
        const float *s = at(i);
        for (int k = 0; k < 3; k++) out[k] += s[k];
    }
    const float n = (float)(to_inclusive - from + 1);
    for (int k = 0; k < 3; k++) out[k] /= n;
}

Detection FallDetector::evaluate(uint32_t peak, float peak_g) {
    Detection d;
    memset(&d, 0, sizeof(d));
    d.peak_g = peak_g;
    d.peak_index = peak;

    float before[3], after[3];
    mean_accel(peak - kTiltPre, peak - kHalf - 1, before);
    mean_accel(peak + kHalf, peak + kTiltPost, after);
    d.tilt_deg = angle_between_deg(before, after);
    d.pre_tilt_deg = trunk_tilt_deg(before);

    d.ai_score = 1.0f;
    const bool posture_ok = d.tilt_deg >= cfg_.min_tilt_deg && d.pre_tilt_deg <= cfg_.max_pre_tilt_deg;
    if (classifier_ && posture_ok) {  // chỉ tốn công chạy model khi tư thế đã khớp
        for (int i = 0; i < kWindow; i++)
            memcpy(&window_[i * kChannels], at(peak - kHalf + i), sizeof(float) * kChannels);
        const uint32_t t0 = micros_ ? micros_() : 0;
        const float p = classifier_(window_, ctx_);
        d.infer_us = micros_ ? micros_() - t0 : 0;
        d.ai_used = p >= 0.0f;
        if (d.ai_used) d.ai_score = p;  // model lỗi -> chỉ dựa vào tư thế
    } else if (classifier_) {
        d.ai_score = 0.0f;
    }
    d.fall = posture_ok && d.ai_score >= cfg_.ai_threshold;
    return d;
}

bool FallDetector::push(const float sample[kChannels], Detection *out) {
    const uint32_t idx = count_++;
    memcpy(buf_[idx % kBuffer], sample, sizeof(float) * kChannels);
    last_mag_g_ = sqrtf(sample[0] * sample[0] + sample[1] * sample[1] + sample[2] * sample[2]) / kGravity;

    // 1. Bắt va chạm và tìm đỉnh
    if (refining_) {
        if (last_mag_g_ > refine_g_) {
            refine_peak_ = idx;
            refine_g_ = last_mag_g_;
        }
    } else if (!armed_) {
        armed_ = last_mag_g_ < cfg_.trigger_g;
    } else if (idx >= (uint32_t)kTiltPre && last_mag_g_ > cfg_.trigger_g) {
        refining_ = true;
        armed_ = false;
        refine_peak_ = idx;
        refine_g_ = last_mag_g_;
        refine_end_ = idx + (cfg_.refine_samples > 1 ? cfg_.refine_samples - 1 : 0);
    }
    if (refining_ && idx >= refine_end_) {
        refining_ = false;
        if (pending_count_ < kMaxPending) {
            const int slot = (pending_head_ + pending_count_) % kMaxPending;
            pending_peak_[slot] = refine_peak_;
            pending_g_[slot] = refine_g_;
            pending_count_++;
        }
    }

    // 2. Xét đỉnh cũ nhất khi đã đủ dữ liệu sau đỉnh
    if (pending_count_ > 0 && idx >= pending_peak_[pending_head_] + kTiltPost) {
        const Detection d = evaluate(pending_peak_[pending_head_], pending_g_[pending_head_]);
        pending_head_ = (pending_head_ + 1) % kMaxPending;
        pending_count_--;
        if (out) *out = d;
        return true;
    }
    return false;
}

}  // namespace fall
