#include "display.h"

#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <Wire.h>

#include "config.h"

namespace ui {

static Adafruit_SSD1306 oled(128, 64, &Wire, -1, 400000UL, 400000UL);  // giữ I2C 400 kHz cho cả MPU6050
static bool g_ok = false;

bool begin() {
    g_ok = oled.begin(SSD1306_SWITCHCAPVCC, OLED_ADDR);
    if (g_ok) {
        oled.setTextColor(SSD1306_WHITE);
        oled.cp437(true);
    }
    return g_ok;
}

bool ok() { return g_ok; }

void boot(const char *const *lines, int count) {
    if (!g_ok) return;
    oled.clearDisplay();
    oled.setTextSize(1);
    for (int i = 0; i < count && i < 8; i++) {
        oled.setCursor(0, i * 8);
        oled.print(lines[i]);
    }
    oled.display();
}

static void centered(const char *text, int y, int size) {
    oled.setTextSize(size);
    const int w = (int)strlen(text) * 6 * size;
    oled.setCursor(w < 128 ? (128 - w) / 2 : 0, y);
    oled.print(text);
}

static void status_bar(const UiInfo &u) {
    oled.setTextSize(1);
    oled.setCursor(0, 0);
    oled.print(u.belt_id);
    oled.setCursor(56, 0);
    oled.print(u.portal ? "SETUP" : (u.mqtt ? "ONLINE" : (u.wifi ? "NO SRV" : "NO WIFI")));
    if (u.wifi) {  // vạch sóng WiFi
        const int bars = u.rssi > -55 ? 4 : u.rssi > -65 ? 3 : u.rssi > -75 ? 2 : 1;
        for (int i = 0; i < 4; i++) {
            const int h = 2 + i * 2;
            if (i < bars) oled.fillRect(108 + i * 5, 7 - h, 3, h, SSD1306_WHITE);
            else oled.drawRect(108 + i * 5, 7 - h, 3, h, SSD1306_WHITE);
        }
    }
    oled.drawFastHLine(0, 10, 128, SSD1306_WHITE);
}

void draw(const UiInfo &u) {
    if (!g_ok) return;
    oled.clearDisplay();
    status_bar(u);
    char buf[32];
    if (u.message) {
        oled.setTextSize(1);
        oled.setCursor(0, 16);
        oled.print(u.message);  // nhiều dòng phân tách bằng \n
    } else {
        switch (u.state) {
            case fall::BeltState::Idle:
                centered("AN TOAN", 15, 2);
                oled.setTextSize(1);
                snprintf(buf, sizeof(buf), "|a| %.2fg  Than %2.0f%c", u.mag_g, u.trunk_tilt, 248);
                oled.setCursor(0, 36);
                oled.print(buf);
                oled.setCursor(0, 46);
                oled.print(u.calibrated ? "Truc: da hieu chuan" : "Truc: mac dinh");
                oled.setCursor(0, 56);
                oled.print(u.last_event[0] ? u.last_event : "Chua co va cham");
                break;
            case fall::BeltState::Alarm:
                centered("PHAT HIEN NGA!", 14, 1);
                snprintf(buf, sizeof(buf), "%d", u.remaining_s);
                centered(buf, 26, 3);
                centered("Bam nut de HUY", 55, 1);
                break;
            case fall::BeltState::WaitServer:
                centered("DANG XAC NHAN", 20, 1);
                centered("voi camera...", 34, 1);
                centered("Bam nut de HUY", 55, 1);
                break;
            case fall::BeltState::Sos:
                centered("SOS!", 16, 3);
                centered(u.mqtt ? "Da bao nguoi than" : "Mat mang - hu coi", 44, 1);
                centered("Bam nut de HUY", 55, 1);
                break;
        }
    }
    oled.display();
}

}  // namespace ui
