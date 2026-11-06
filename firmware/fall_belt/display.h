// Màn hình OLED SSD1306 128x64 (chữ không dấu vì font mặc định không có tiếng Việt).
#pragma once
#include <stdint.h>

#include "belt_logic.h"

struct UiInfo {
    const char *belt_id;
    bool wifi, mqtt, portal;
    int rssi;
    fall::BeltState state;
    int remaining_s;
    float mag_g;          // |a| hiện tại
    float trunk_tilt;     // thân lệch phương thẳng đứng (độ)
    bool calibrated;
    const char *last_event;  // tóm tắt lần xét va chạm gần nhất
    const char *message;     // thông báo tạm (hiệu chuẩn, cấu hình...) — null nếu không có
};

namespace ui {

bool begin();
bool ok();
void boot(const char *const *lines, int count);  // màn hình tự kiểm tra lúc khởi động
void draw(const UiInfo &info);

}  // namespace ui
