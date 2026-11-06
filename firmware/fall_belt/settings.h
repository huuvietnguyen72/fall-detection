// Cấu hình lưu trong flash (NVS) — giữ nguyên sau khi tắt nguồn.
#pragma once
#include <stdint.h>

#include "orientation.h"

struct Settings {
    char mqtt_host[64];
    uint16_t mqtt_port;
    char belt_id[24];
    bool calibrated;     // đã hiệu chuẩn hướng lắp bằng nút bấm
    fall::AxisMap axis;  // cảm biến -> hệ trục SisFall
};

void settings_load(Settings &s);   // đọc từ flash (thiếu thì lấy mặc định trong config.h)
void settings_save(const Settings &s);
void settings_factory_reset();     // xóa cấu hình đã lưu (kể cả WiFi)
