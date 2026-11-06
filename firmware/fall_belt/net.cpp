#include "net.h"

#include <ESPmDNS.h>
#include <PubSubClient.h>
#include <WiFi.h>
#include <WiFiManager.h>

#include "config.h"

namespace net {

// Các thao tác mạng chạy trong loop() phải ngắn: hàng đợi cảm biến chỉ đệm được 2.5 s.
static const uint32_t kTcpTimeoutMs = 600;
static const uint32_t kMdnsTimeoutMs = 400;
static const uint32_t kMqttRetryMs = 5000;
static const uint32_t kWifiRetryMs = 15000;
static const uint32_t kPortalTimeoutMs = 180000;  // tự đóng trang cấu hình sau 3 phút

static Settings *g_settings = nullptr;
static CommandHandler g_on_command = nullptr;
static WiFiManager wm;
static WiFiClient wifi_client;
static PubSubClient mqtt(wifi_client);
static WiFiManagerParameter *p_host, *p_port, *p_belt;
static char server_ip[16] = "";
static char cmd_topic[64];
static uint32_t last_mqtt_try = 0, last_wifi_try = 0, portal_opened_at = 0;
static bool mdns_started = false;

static void on_message(char *, byte *payload, unsigned int len) {
    // payload dạng {"cmd":"sos"} — tách thủ công để khỏi phụ thuộc thư viện JSON ở đây
    char buf[96];
    len = len < sizeof(buf) - 1 ? len : sizeof(buf) - 1;
    memcpy(buf, payload, len);
    buf[len] = 0;
    char *p = strstr(buf, "\"cmd\"");
    if (!p || !(p = strchr(p + 5, '"'))) return;
    char *end = strchr(++p, '"');
    if (!end) return;
    *end = 0;
    if (g_on_command) g_on_command(p);
}

static void on_portal_saved() {
    strlcpy(g_settings->mqtt_host, p_host->getValue(), sizeof(g_settings->mqtt_host));
    const long port = atol(p_port->getValue());
    g_settings->mqtt_port = (port > 0 && port <= 65535) ? (uint16_t)port : MQTT_PORT;
    if (strlen(p_belt->getValue())) strlcpy(g_settings->belt_id, p_belt->getValue(), sizeof(g_settings->belt_id));
    settings_save(*g_settings);
    snprintf(cmd_topic, sizeof(cmd_topic), "fall/belt/%s/cmd", g_settings->belt_id);
    server_ip[0] = 0;
    mqtt.disconnect();
    Serial.printf("[NET] Da luu cau hinh: MQTT %s:%u, belt %s\n", g_settings->mqtt_host, g_settings->mqtt_port,
                  g_settings->belt_id);
}

// Phân giải địa chỉ server: IP sẵn, hoặc tên .local qua mDNS
static bool resolve_server() {
    IPAddress ip;
    const char *host = g_settings->mqtt_host;
    if (ip.fromString(host)) {
        strlcpy(server_ip, host, sizeof(server_ip));
        return true;
    }
    const char *dot = strstr(host, ".local");
    if (dot) {
        if (!mdns_started) mdns_started = MDNS.begin(g_settings->belt_id);
        String name(host);
        ip = MDNS.queryHost(name.substring(0, dot - host), kMdnsTimeoutMs);
    } else {
        WiFi.hostByName(host, ip);
    }
    if (ip == IPAddress(0, 0, 0, 0)) return false;
    strlcpy(server_ip, ip.toString().c_str(), sizeof(server_ip));
    Serial.printf("[NET] Server %s -> %s\n", host, server_ip);
    return true;
}

void begin(Settings *settings, CommandHandler on_command, bool force_portal) {
    g_settings = settings;
    g_on_command = on_command;
    snprintf(cmd_topic, sizeof(cmd_topic), "fall/belt/%s/cmd", settings->belt_id);

    static char port_str[8];
    snprintf(port_str, sizeof(port_str), "%u", settings->mqtt_port);
    p_host = new WiFiManagerParameter("mqtt_host", "Dia chi server (fallserver.local hoac IP may tinh)",
                                      settings->mqtt_host, 63);
    p_port = new WiFiManagerParameter("mqtt_port", "Cong MQTT", port_str, 6);
    p_belt = new WiFiManagerParameter("belt_id", "Ma dai lung", settings->belt_id, 23);
    wm.addParameter(p_host);
    wm.addParameter(p_port);
    wm.addParameter(p_belt);
    wm.setSaveParamsCallback(on_portal_saved);
    wm.setSaveConfigCallback(on_portal_saved);
    wm.setConfigPortalBlocking(false);  // vẫn phát hiện té ngã trong lúc chờ cấu hình
    wm.setConnectTimeout(10);
    wm.setTitle("Dai lung phat hien te nga");

    WiFi.mode(WIFI_STA);
    WiFi.setSleep(false);
    wifi_client.setConnectionTimeout(kTcpTimeoutMs);
    mqtt.setCallback(on_message);
    mqtt.setSocketTimeout(1);
    mqtt.setKeepAlive(15);
    mqtt.setBufferSize(768);

    const bool has_credentials = wm.getWiFiIsSaved() || strlen(WIFI_SSID);
    if (force_portal || !has_credentials) {
        open_portal();  // lần đầu (chưa có WiFi) hoặc người dùng yêu cầu
    } else if (!wm.getWiFiIsSaved()) {
        WiFi.begin(WIFI_SSID, WIFI_PASSWORD);  // WiFi điền sẵn trong config.h
    } else {
        // Đã có WiFi lưu: chỉ thử kết nối, KHÔNG tự mở portal khi router chưa lên (mất điện...) — loop() thử lại
        wm.setEnableConfigPortal(false);
        wm.autoConnect(SETUP_AP_NAME, SETUP_AP_PASSWORD);
        wm.setEnableConfigPortal(true);
    }
    last_wifi_try = millis();
}

void open_portal() {
    Serial.printf("[NET] Mo cau hinh: ket noi WiFi '%s' (mat khau %s) roi vao http://192.168.4.1\n", SETUP_AP_NAME,
                  SETUP_AP_PASSWORD);
    wm.startConfigPortal(SETUP_AP_NAME, SETUP_AP_PASSWORD);
    portal_opened_at = millis();
}

static void maintain_wifi(uint32_t now) {
    if (portal_active()) {
        // Chế độ non-blocking: WiFiManager không tự đóng portal -> tự đóng sau 3 phút rồi quay về WiFi đã lưu
        if (now - portal_opened_at > kPortalTimeoutMs && WiFi.softAPgetStationNum() == 0) {
            Serial.println("[NET] Dong trang cau hinh (het gio)");
            wm.stopConfigPortal();
            WiFi.mode(WIFI_STA);
            last_wifi_try = 0;
        }
        return;
    }
    if (WiFi.status() == WL_CONNECTED || now - last_wifi_try < kWifiRetryMs) return;
    last_wifi_try = now;
    Serial.println("[NET] Mat WiFi -> thu ket noi lai");
    WiFi.mode(WIFI_STA);
    if (wm.getWiFiIsSaved()) WiFi.begin();  // dùng WiFi đã lưu trong flash
    else if (strlen(WIFI_SSID)) WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
}

void loop() {
    const uint32_t now = millis();
    wm.process();
    maintain_wifi(now);
    if (WiFi.status() != WL_CONNECTED) return;
    if (mqtt.connected()) {
        mqtt.loop();
        return;
    }
    if (now - last_mqtt_try < kMqttRetryMs) return;
    last_mqtt_try = now;
    if (!server_ip[0] && !resolve_server()) {
        Serial.printf("[NET] Chua tim thay server '%s'\n", g_settings->mqtt_host);
        return;
    }
    mqtt.setServer(server_ip, g_settings->mqtt_port);
    char client_id[48];
    snprintf(client_id, sizeof(client_id), "belt-%s-%06lx", g_settings->belt_id,
             (unsigned long)(ESP.getEfuseMac() & 0xFFFFFF));
    const bool ok = strlen(MQTT_USER) ? mqtt.connect(client_id, MQTT_USER, MQTT_PASSWORD) : mqtt.connect(client_id);
    if (ok) {
        mqtt.subscribe(cmd_topic, 1);
        Serial.printf("[NET] MQTT da ket noi %s:%u\n", server_ip, g_settings->mqtt_port);
    } else {
        Serial.printf("[NET] MQTT loi (state %d) — se thu lai\n", mqtt.state());
        server_ip[0] = 0;  // có thể server đổi IP: phân giải lại lần sau
    }
}

bool wifi_connected() { return WiFi.status() == WL_CONNECTED; }
bool online() { return wifi_connected() && mqtt.connected(); }
bool portal_active() { return wm.getConfigPortalActive() || wm.getWebPortalActive(); }

bool publish(const char *subtopic, const char *json, bool retain) {
    if (!online()) return false;
    char topic[80];
    snprintf(topic, sizeof(topic), "fall/belt/%s/%s", g_settings->belt_id, subtopic);
    return mqtt.publish(topic, json, retain);
}

String ip() { return WiFi.localIP().toString(); }
int rssi() { return wifi_connected() ? WiFi.RSSI() : 0; }
const char *server_address() { return server_ip; }

}  // namespace net
