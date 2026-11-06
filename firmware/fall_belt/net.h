// Mạng: WiFi (cấu hình qua điện thoại bằng WiFiManager), tìm server qua mDNS, MQTT.
// Mọi hàm đều không chặn lâu — việc phát hiện té ngã vẫn chạy khi mất mạng.
#pragma once
#include <Arduino.h>

#include "settings.h"

typedef void (*CommandHandler)(const char *cmd);

namespace net {

void begin(Settings *settings, CommandHandler on_command, bool open_portal);
void loop();
bool online();             // WiFi + MQTT đều kết nối
bool wifi_connected();
bool portal_active();
void open_portal();        // phát WiFi SETUP_AP_NAME để cấu hình lại
bool publish(const char *subtopic, const char *json, bool retain = false);  // fall/belt/<id>/<subtopic>
String ip();
int rssi();
const char *server_address();  // IP đã phân giải của server MQTT ("" nếu chưa)

}  // namespace net
