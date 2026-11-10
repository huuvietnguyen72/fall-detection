// ============================================================================
//  CẤU HÌNH ĐAI LƯNG
//  Mặc định đã chạy được ngay: WiFi + địa chỉ server cấu hình qua điện thoại (WiFi "FallBelt-Setup").
//  Chỉ sửa file này nếu đấu dây khác hoặc muốn điền sẵn WiFi.
// ============================================================================
#pragma once

#define FW_VERSION "2.0.0"

// ---------- Mạng (tùy chọn — để trống thì cấu hình qua điện thoại) ----------
#define WIFI_SSID       ""                // điền sẵn để bỏ qua bước cấu hình qua điện thoại
#define WIFI_PASSWORD   ""
#define MQTT_HOST       "fallserver.local" // server tự quảng bá tên này qua mDNS; hoặc điền IP máy tính
#define MQTT_PORT       1883
#define MQTT_USER       ""
#define MQTT_PASSWORD   ""
#define BELT_ID         "belt01"          // phải trùng BELT_ID trong .env của server
#define SETUP_AP_NAME   "FallBelt-Setup"  // tên WiFi phát ra khi cần cấu hình
#define SETUP_AP_PASSWORD "fallbelt123"   // mật khẩu WiFi cấu hình (>= 8 ký tự)
#define DATA_TCP_PORT   2323              // thu dữ liệu fine-tune qua WiFi: belt_collect.py --port <IP đai>; 0 = tắt

// ---------- Model AI ----------
// 1 = dùng model Edge Impulse (cài firmware/ei_models/Fall-Detection-SisFall_inferencing.zip vào Arduino IDE)
// 0 = chỉ dùng luật tư thế (không cần thư viện model)
#define USE_EDGE_IMPULSE  1
#define EI_HEADER         <Fall-Detection-SisFall_inferencing.h>

// ---------- Chân kết nối (ESP32 DevKit V1) ----------
#define PIN_SDA        21    // MPU6050 + OLED dùng chung I2C
#define PIN_SCL        22
#define PIN_BUZZER     25    // còi chủ động (active buzzer), HIGH = kêu
#define PIN_LED_RED    27
#define PIN_LED_GREEN  26
#define PIN_BUTTON     4     // Tact switch nối GND (dùng pull-up nội)
#define MPU_ADDR       0x68  // 0x69 nếu chân AD0 nối VCC
#define OLED_ADDR      0x3C
#define BUZZER_ACTIVE_HIGH 1 // 0 nếu module còi kêu khi mức LOW

// ---------- Phát hiện (đã tối ưu trên 4500 bản ghi SisFall — xem README) ----------
#define TRIGGER_G          1.8f   // |a| vượt ngưỡng này mới xét (2.0 -> 1.8: dữ liệu đai thật 11/2026, bắt 96% vs 88%, báo nhầm không đổi)
#define AI_THRESHOLD       0.5f   // P(Fall) tối thiểu
#define MIN_TILT_DEG       30.0f  // thân nghiêng thêm tối thiểu sau va chạm
#define MAX_PRE_TILT_DEG   65.0f  // trước va chạm thân phải gần thẳng đứng

#define COUNTDOWN_S        15     // thời gian cho phép hủy — khớp COUNTDOWN_S của server
#define SERVER_TIMEOUT_S   20     // hết đếm ngược mà server không phản hồi -> tự SOS tại chỗ

// ---------- Hướng lắp cảm biến (khi CHƯA hiệu chuẩn bằng nút) ----------
// Model dùng hệ trục SisFall: X = sang phải, Y = xuống chân, Z = ra trước bụng.
// Mặc định cho GY-521 gắn ĐỨNG phía trước bụng: mặt chip hướng ra ngoài, mũi tên Y trên board chỉ LÊN.
//   => X_sisfall = -X_mpu, Y_sisfall = -Y_mpu, Z_sisfall = +Z_mpu
// Lắp khác thì giữ nút 3 giây để hiệu chuẩn tự động (xem README), không cần sửa ở đây.
#define AXIS_ORDER  {0, 1, 2}
#define AXIS_SIGN   {-1, -1, 1}
