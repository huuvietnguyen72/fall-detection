/*
 * ĐAI LƯNG PHÁT HIỆN TÉ NGÃ — ESP32 + MPU6050 + OLED SSD1306 + Buzzer + LED + Tact switch
 *
 *   Task lấy mẫu (50 Hz)  ->  hàng đợi  ->  loop(): quy đổi trục -> FallDetector (AI + tư thế)
 *                                                 -> BeltController (còi, LED, đếm ngược) <-> MQTT server
 *
 * Nút bấm:   bấm nhanh = HỦY báo động  |  giữ 3 s = hiệu chuẩn hướng lắp  |  giữ 8 s = cấu hình WiFi
 *            giữ nút lúc cắm điện = cấu hình WiFi
 * Serial (115200): gõ "help" để xem lệnh (info, data, calib, wifi, fall, factory, reboot)
 *
 * Thư viện: Adafruit MPU6050, Adafruit SSD1306, Adafruit GFX, PubSubClient, WiFiManager (tzapu)
 *           + model: firmware/ei_models/Fall-Detection-SisFall_inferencing.zip (Sketch > Include Library > Add .ZIP)
 * Board: ESP32 Dev Module.  Partition Scheme: mặc định là đủ.
 */
#include <Adafruit_MPU6050.h>
#include <Wire.h>

#include <atomic>

#include "belt_logic.h"
#include "config.h"
#include "detector.h"
#include "display.h"
#include "ei_glue.h"
#include "net.h"
#include "orientation.h"
#include "settings.h"

// ------------------------------------------------------------------ dữ liệu dùng chung
struct RawSample {
    float a[3];  // m/s², hệ trục cảm biến
    float g[3];  // rad/s
};

static Adafruit_MPU6050 mpu;
static QueueHandle_t sample_queue;
static SemaphoreHandle_t i2c_mutex;
static std::atomic<uint32_t> missed_samples{0}, sensor_errors{0};

static Settings settings;
static fall::FallDetector *detector;
static fall::BeltController belt(COUNTDOWN_S * 1000UL, SERVER_TIMEOUT_S * 1000UL);

static bool data_mode = false;      // in CSV ra Serial để thu dữ liệu fine-tune
static float lp_acc[3] = {0, -fall::kGravity, 0};  // gia tốc lọc thông thấp (hệ SisFall) -> góc thân
static float acc_max_g = 0;         // |a| lớn nhất trong 1 giây
static float last_infer_ms = 0;
static char last_event[24] = "";
static char ui_message[96] = "";
static const char *kPortalMessage = "CAU HINH WIFI\nWiFi: " SETUP_AP_NAME "\nMK: " SETUP_AP_PASSWORD "\nroi vao 192.168.4.1";
static uint32_t ui_message_until = 0;

// ------------------------------------------------------------------ tiện ích
static uint32_t micros32() { return (uint32_t)micros(); }

static void show_message(const char *msg, uint32_t ms) {
    strlcpy(ui_message, msg, sizeof(ui_message));
    ui_message_until = millis() + ms;
}

static void buzz(bool on) { digitalWrite(PIN_BUZZER, on == (bool)BUZZER_ACTIVE_HIGH ? HIGH : LOW); }

static void chirp(int times) {
    for (int i = 0; i < times; i++) {
        buzz(true);
        delay(60);
        buzz(false);
        delay(80);
    }
}

// ------------------------------------------------------------------ task lấy mẫu 50 Hz
// Đọc trực tiếp 14 byte thanh ghi (thay vì getEvent, vốn luôn trả true) để phát hiện lỏng dây I2C.
static bool read_mpu(RawSample &s) {
    static const float kAccel = fall::kGravity / 2048.0f;           // ±16 g: 2048 LSB/g
    static const float kGyro = (3.14159265f / 180.0f) / 16.4f;      // ±2000 °/s: 16.4 LSB/(°/s)
    uint8_t b[14];
    Wire.beginTransmission(MPU_ADDR);
    Wire.write(0x3B);  // ACCEL_XOUT_H
    if (Wire.endTransmission(false) != 0 || Wire.requestFrom((uint8_t)MPU_ADDR, (uint8_t)14) != 14) return false;
    bool all_ff = true;
    for (uint8_t &v : b) {
        v = Wire.read();
        all_ff &= v == 0xFF;
    }
    if (all_ff) return false;  // bus treo / mất cảm biến
    auto word = [&](int i) { return (int16_t)((b[i] << 8) | b[i + 1]); };
    for (int k = 0; k < 3; k++) {
        s.a[k] = word(k * 2) * kAccel;
        s.g[k] = word(8 + k * 2) * kGyro;  // bỏ qua 2 byte nhiệt độ
    }
    return true;
}

static void sampling_task(void *) {
    TickType_t last = xTaskGetTickCount();
    for (;;) {
        vTaskDelayUntil(&last, pdMS_TO_TICKS(20));
        RawSample s;
        bool ok = false;
        // OLED vẽ lại mất ~25 ms trên cùng bus I2C -> chờ đủ lâu; vTaskDelayUntil sẽ tự bắt kịp nhịp 50 Hz
        if (xSemaphoreTake(i2c_mutex, pdMS_TO_TICKS(50)) == pdTRUE) {
            ok = read_mpu(s);
            xSemaphoreGive(i2c_mutex);
        }
        if (!ok) {
            sensor_errors++;
            continue;
        }
        if (xQueueSend(sample_queue, &s, 0) != pdTRUE) missed_samples++;
    }
}

// ------------------------------------------------------------------ MQTT
static void publish_impact(float score, float peak_g, float tilt, bool simulated) {
    char json[160];
    snprintf(json, sizeof(json),
             "{\"type\":\"impact\",\"score\":%.3f,\"peak_g\":%.2f,\"tilt\":%.0f,\"countdown_s\":%d%s}", score, peak_g,
             tilt, COUNTDOWN_S, simulated ? ",\"simulated\":true" : "");
    net::publish("event", json);
}

static void publish_detection(const fall::Detection &d) {
    char json[200];
    snprintf(json, sizeof(json),
             "{\"type\":\"detection\",\"fall\":%s,\"ai\":%.3f,\"ai_used\":%s,\"tilt\":%.0f,\"pre_tilt\":%.0f,"
             "\"peak_g\":%.2f,\"infer_ms\":%.1f}",
             d.fall ? "true" : "false", d.ai_score, d.ai_used ? "true" : "false", d.tilt_deg, d.pre_tilt_deg,
             d.peak_g, d.infer_us / 1000.0f);
    net::publish("event", json);
}

static void publish_status() {
    char json[420];
    snprintf(json, sizeof(json),
             "{\"state\":\"%s\",\"rssi\":%d,\"ip\":\"%s\",\"uptime_s\":%lu,\"fw\":\"%s\",\"model\":\"%s\","
             "\"calibrated\":%s,\"acc_max_g\":%.2f,\"tilt\":%.0f,\"infer_ms\":%.1f,\"missed\":%lu,"
             "\"sensor_err\":%lu,\"heap_kb\":%lu,\"remaining_s\":%d}",
             belt.state_name(), net::rssi(), net::ip().c_str(), (unsigned long)(millis() / 1000), FW_VERSION,
             fall::ei_model_name()[0] ? fall::ei_model_name() : "rule-only", settings.calibrated ? "true" : "false",
             acc_max_g, fall::trunk_tilt_deg(lp_acc), last_infer_ms, (unsigned long)missed_samples.load(),
             (unsigned long)sensor_errors.load(), (unsigned long)(ESP.getFreeHeap() / 1024), belt.remaining_s(millis()));
    net::publish("status", json);
}

static void send_event(fall::BeltEvent ev, float score, float peak_g, float tilt, bool simulated = false) {
    if (ev == fall::BeltEvent::SendImpact) {
        publish_impact(score, peak_g, tilt, simulated);
        Serial.printf("[ALARM] Phat hien nga (P=%.2f, %.1fg, nghieng %.0f) — dem nguoc %ds\n", score, peak_g, tilt,
                      COUNTDOWN_S);
    } else if (ev == fall::BeltEvent::SendCancel) {
        net::publish("event", "{\"type\":\"cancel\"}");
        Serial.println("[ALARM] Nguoi dung huy");
    }
}

static void on_server_command(const char *cmd) {
    Serial.printf("[MQTT] lenh tu server: %s\n", cmd);
    belt.on_command(cmd, millis());
}

// ------------------------------------------------------------------ hiệu chuẩn hướng lắp
enum class Calib { Off, Stand, Bow };
static Calib calib = Calib::Off;
static uint32_t calib_t0 = 0, calib_n = 0, calib_still_since = 0;
static float calib_sum[3], calib_stand[3];

static void calib_start() {
    calib = Calib::Stand;
    calib_t0 = millis();
    calib_n = 0;
    memset(calib_sum, 0, sizeof(calib_sum));
    chirp(1);
    Serial.println("[CALIB] Buoc 1: dung thang, yen 3 giay");
}

static void calib_feed(const float a[3]) {
    const uint32_t t = millis() - calib_t0;
    if (calib == Calib::Stand) {
        show_message("HIEU CHUAN 1/2\n\nDung THANG, yen\nkhong cu dong...", 1000);
        if (t > 1000) {  // bỏ 1 s đầu cho người dùng đứng yên
            for (int k = 0; k < 3; k++) calib_sum[k] += a[k];
            calib_n++;
        }
        if (t > 3000) {
            for (int k = 0; k < 3; k++) calib_stand[k] = calib_sum[k] / calib_n;
            calib = Calib::Bow;
            calib_t0 = millis();
            calib_still_since = 0;
            chirp(2);
            Serial.println("[CALIB] Buoc 2: cui nguoi ve phia truoc ~45 do va giu yen");
        }
    } else if (calib == Calib::Bow) {
        show_message("HIEU CHUAN 2/2\n\nCUI nguoi ve TRUOC\n~45 do va giu yen", 1000);
        const float ang = fall::angle_between_deg(a, calib_stand);
        if (ang > 25.0f) {
            if (!calib_still_since) {
                calib_still_since = millis();
                calib_n = 0;
                memset(calib_sum, 0, sizeof(calib_sum));
            }
            for (int k = 0; k < 3; k++) calib_sum[k] += a[k];
            calib_n++;
        } else {
            calib_still_since = 0;
        }
        if (calib_still_since && millis() - calib_still_since > 1500) {
            float bow[3] = {calib_sum[0] / calib_n, calib_sum[1] / calib_n, calib_sum[2] / calib_n};
            fall::AxisMap map;
            if (fall::axis_map_calibrate(calib_stand, bow, &map)) {
                settings.axis = map;
                settings.calibrated = true;
                settings_save(settings);
                show_message("HIEU CHUAN XONG!\n\nDa luu huong lap.", 3000);
                Serial.println("[CALIB] Thanh cong, da luu");
                chirp(3);
            } else {
                show_message("HIEU CHUAN LOI\n\nGiu nut 3s de\nthu lai.", 4000);
            }
            calib = Calib::Off;
        } else if (t > 20000) {
            show_message("HET GIO\n\nGiu nut 3s de\nthu lai.", 4000);
            calib = Calib::Off;
        }
    }
}

// ------------------------------------------------------------------ xử lý mẫu
static void process_sample(const RawSample &raw) {
    float s[fall::kChannels];
    fall::axis_map_apply(settings.axis, raw.a, s);
    fall::axis_map_apply(settings.axis, raw.g, s + 3);

    if (data_mode) {
        Serial.printf("%.4f,%.4f,%.4f,%.4f,%.4f,%.4f\n", s[0], s[1], s[2], s[3], s[4], s[5]);
    }
    if (calib != Calib::Off) calib_feed(raw.a);

    for (int k = 0; k < 3; k++) lp_acc[k] += 0.05f * (s[k] - lp_acc[k]);

    fall::Detection d;
    const bool evaluated = detector->push(s, &d);
    if (detector->magnitude_g() > acc_max_g) acc_max_g = detector->magnitude_g();
    if (!evaluated || calib != Calib::Off) return;

    if (d.ai_used) last_infer_ms = d.infer_us / 1000.0f;
    snprintf(last_event, sizeof(last_event), "%.1fg P%.2f %.0f%c %s", d.peak_g, d.ai_score, d.tilt_deg, 248,
             d.fall ? "NGA" : "bo qua");
    Serial.printf("[DETECT] dinh %.2fg | AI %.3f%s | nghieng +%.0f | truoc %.0f | %s\n", d.peak_g, d.ai_score,
                  d.ai_used ? "" : " (khong chay)", d.tilt_deg, d.pre_tilt_deg, d.fall ? "=> TE NGA" : "=> bo qua");
    publish_detection(d);
    if (d.fall) send_event(belt.on_fall(millis()), d.ai_score, d.peak_g, d.tilt_deg);
}

// ------------------------------------------------------------------ nút bấm
static void handle_button() {
    static bool pressed = false, long_fired = false, portal_fired = false, started_idle = false;
    static uint32_t down_at = 0, changed_at = 0;
    const bool now_pressed = digitalRead(PIN_BUTTON) == LOW;
    const uint32_t now = millis();
    if (now_pressed != pressed && now - changed_at > 30) {
        changed_at = now;
        pressed = now_pressed;
        if (pressed) {
            down_at = now;
            long_fired = portal_fired = false;
            // Giữ nút để HỦY báo động (người vừa ngã có thể giữ lâu) không được kích hoạt hiệu chuẩn / cấu hình
            started_idle = belt.state() == fall::BeltState::Idle;
            if (!started_idle) send_event(belt.on_button(now), 0, 0, 0);  // hủy ngay khi bấm
        }
    }
    if (pressed && started_idle && belt.state() == fall::BeltState::Idle) {
        if (!long_fired && now - down_at > 3000) {
            long_fired = true;
            calib_start();
        }
        if (!portal_fired && now - down_at > 8000) {
            portal_fired = true;
            calib = Calib::Off;
            net::open_portal();
        }
    }
}

// ------------------------------------------------------------------ lệnh Serial
static void print_info() {
    Serial.printf("FW %s | model: %s | belt: %s\n", FW_VERSION,
                  fall::ei_model_name()[0] ? fall::ei_model_name() : "(khong co - chi dung luat)", settings.belt_id);
    Serial.printf("WiFi: %s (%s, %d dBm) | MQTT %s:%u -> %s %s\n", net::wifi_connected() ? "OK" : "chua",
                  net::ip().c_str(), net::rssi(), settings.mqtt_host, settings.mqtt_port, net::server_address(),
                  net::online() ? "OK" : "chua");
    Serial.printf("Truc: %s | Than nghieng %.0f do | |a| %.2fg | mat mau %lu | loi cam bien %lu | AI %.1f ms\n",
                  settings.calibrated ? "da hieu chuan" : "mac dinh config.h", fall::trunk_tilt_deg(lp_acc),
                  detector->magnitude_g(), (unsigned long)missed_samples.load(), (unsigned long)sensor_errors.load(), last_infer_ms);
}

static void handle_serial() {
    static char line[32];
    static int len = 0;
    while (Serial.available()) {
        const char c = (char)Serial.read();
        if (c != '\n' && c != '\r') {
            if (len < (int)sizeof(line) - 1) line[len++] = c;
            continue;
        }
        if (!len) continue;
        line[len] = 0;
        len = 0;
        if (!strcmp(line, "help")) {
            Serial.println("Lenh: info | data (bat/tat in CSV ax,ay,az,gx,gy,gz) | calib | wifi | fall (gia lap nga)"
                           " | cancel | factory (xoa cau hinh) | reboot");
        } else if (!strcmp(line, "info")) {
            print_info();
        } else if (!strcmp(line, "data")) {
            data_mode = !data_mode;
        } else if (!strcmp(line, "calib")) {
            calib_start();
        } else if (!strcmp(line, "wifi")) {
            net::open_portal();
        } else if (!strcmp(line, "fall")) {
            send_event(belt.on_fall(millis()), 0.99f, 4.2f, 85, true);
        } else if (!strcmp(line, "cancel")) {
            send_event(belt.on_button(millis()), 0, 0, 0);
        } else if (!strcmp(line, "factory")) {
            settings_factory_reset();
            ESP.restart();
        } else if (!strcmp(line, "reboot")) {
            ESP.restart();
        } else {
            Serial.printf("Khong hieu lenh '%s' — go help\n", line);
        }
    }
}

// ------------------------------------------------------------------ setup / loop
void setup() {
    Serial.begin(115200);
    pinMode(PIN_BUZZER, OUTPUT);
    pinMode(PIN_LED_RED, OUTPUT);
    pinMode(PIN_LED_GREEN, OUTPUT);
    pinMode(PIN_BUTTON, INPUT_PULLUP);
    buzz(false);
    const bool button_at_boot = digitalRead(PIN_BUTTON) == LOW;

    Wire.begin(PIN_SDA, PIN_SCL);
    Wire.setClock(400000);
    i2c_mutex = xSemaphoreCreateMutex();
    settings_load(settings);

    // --- Tự kiểm tra phần cứng ---
    const bool oled_ok = ui::begin();
    const bool mpu_ok = mpu.begin(MPU_ADDR, &Wire);
    if (mpu_ok) {
        mpu.setAccelerometerRange(MPU6050_RANGE_16_G);  // giống SisFall: ADXL345 ±16g
        mpu.setGyroRange(MPU6050_RANGE_2000_DEG);       // ITG3200 ±2000°/s
        mpu.setFilterBandwidth(MPU6050_BAND_21_HZ);     // chống răng cưa cho 50 Hz
    }
    const char *model = fall::ei_model_name();
    char l_model[24];
    snprintf(l_model, sizeof(l_model), "AI: %.16s", model[0] ? model : "chi dung luat");
    const char *lines[] = {"DAI LUNG TE NGA v" FW_VERSION, "", mpu_ok ? "MPU6050   OK" : "MPU6050   LOI!",
                           oled_ok ? "OLED      OK" : "OLED      LOI", l_model,
                           settings.calibrated ? "Truc: da hieu chuan" : "Truc: mac dinh"};
    ui::boot(lines, 6);
    Serial.printf("\n=== Dai lung te nga v%s ===\nMPU6050 %s | OLED %s | %s\n", FW_VERSION, mpu_ok ? "OK" : "LOI",
                  oled_ok ? "OK" : "LOI", l_model);
    digitalWrite(PIN_LED_RED, HIGH);
    digitalWrite(PIN_LED_GREEN, HIGH);
    chirp(1);
    delay(700);
    digitalWrite(PIN_LED_RED, LOW);
    digitalWrite(PIN_LED_GREEN, LOW);

    if (!mpu_ok) {  // không có cảm biến thì không thể bảo vệ người dùng: báo lỗi rõ ràng
        Serial.println("Khong tim thay MPU6050! Kiem tra day SDA=21, SCL=22, VCC=3V3, GND.");
        for (;;) {
            digitalWrite(PIN_LED_RED, (millis() / 150) % 2);
            delay(10);
        }
    }

    fall::DetectorConfig cfg;
    cfg.trigger_g = TRIGGER_G;
    cfg.ai_threshold = AI_THRESHOLD;
    cfg.min_tilt_deg = MIN_TILT_DEG;
    cfg.max_pre_tilt_deg = MAX_PRE_TILT_DEG;
    detector = new fall::FallDetector(cfg, USE_EDGE_IMPULSE ? fall::ei_fall_probability : nullptr, nullptr, micros32);

    net::begin(&settings, on_server_command, button_at_boot);  // có thể chờ WiFi tới 10 s

    sample_queue = xQueueCreate(128, sizeof(RawSample));  // 2.5 s đệm khi mạng/màn hình chậm
    xTaskCreatePinnedToCore(sampling_task, "sampling", 4096, nullptr, configMAX_PRIORITIES - 2, nullptr, 1);
    Serial.println("San sang. Go 'help' de xem lenh.");
}

void loop() {
    RawSample raw;
    while (xQueueReceive(sample_queue, &raw, 0) == pdTRUE) process_sample(raw);

    net::loop();
    handle_button();
    handle_serial();

    const uint32_t now = millis();
    belt.tick(now, net::online());
    const fall::BeltOutputs out = belt.outputs(now, net::online());
    buzz(out.buzzer);
    digitalWrite(PIN_LED_RED, out.led_red);
    digitalWrite(PIN_LED_GREEN, out.led_green);

    static uint32_t last_status = 0, last_draw = 0;
    if (now - last_status >= 1000) {
        last_status = now;
        publish_status();
        acc_max_g = 0;
        static uint32_t errors_before = 0;
        const uint32_t errors = sensor_errors.load();
        if (errors - errors_before > 10) {  // > 20% số mẫu lỗi trong 1 giây
            show_message("LOI CAM BIEN!\n\nMPU6050 khong doc\nduoc - kiem tra day\nSDA/SCL/VCC/GND", 1500);
            Serial.printf("[SENSOR] %lu loi doc MPU6050 trong 1 giay\n", (unsigned long)(errors - errors_before));
        }
        errors_before = errors;
    }
    if (now - last_draw >= 200) {
        last_draw = now;
        const bool timed = ui_message[0] && (int32_t)(ui_message_until - now) > 0;
        const char *msg = timed ? ui_message : (net::portal_active() ? kPortalMessage : nullptr);
        const UiInfo info = {settings.belt_id, net::wifi_connected(), net::online(), net::portal_active(), net::rssi(),
                             belt.state(), belt.remaining_s(now), detector->magnitude_g(),
                             fall::trunk_tilt_deg(lp_acc), settings.calibrated, last_event, msg};
        if (xSemaphoreTake(i2c_mutex, pdMS_TO_TICKS(50)) == pdTRUE) {
            ui::draw(info);
            xSemaphoreGive(i2c_mutex);
        }
    }
    delay(2);
}
