# Hệ thống giám sát và phát hiện té ngã thời gian thực
*Đai lưng ESP32 (TinyML) + Camera (MediaPipe) + Decision Fusion + Telegram*

```
 Đai lưng ESP32 + MPU6050 ─────────────┐                ┌──────────── Camera (Python, MediaPipe Pose)
 50 Hz → bắt đỉnh va chạm → AI Edge     │                │  khung xương → Đứng / Ngồi / Cúi / Nằm
 Impulse + góc nghiêng → còi/LED/OLED   │                │  + ảnh xem trước + ảnh hiện trường
                                        ▼                ▼
                         ┌──────────── MQTT (Mosquitto) ────────────┐
                                        │
                     Server "bộ não": Decision Fusion → Dashboard web → Telegram SOS (kèm ảnh)
```

## Kết quả đã kiểm chứng (chưa có phần cứng)

| Hạng mục | Cách kiểm chứng | Kết quả |
|---|---|---|
| Model AI của nhóm (Edge Impulse, int8) | Chạy **đúng mã C++** của model trên PC, tập test 80 cửa sổ | Accuracy **100%** |
| Bộ phát hiện của firmware chạy liên tục | **Đúng mã C++ của firmware** + model, trên **4500 bản ghi SisFall gốc (22 giờ)** | Recall **95.7%** (người mới: **97.6%**) · báo nhầm **0.5%** bản ghi sinh hoạt |
| So với cách trượt cửa sổ của sketch bàn giao | Cùng dữ liệu | Recall 95.8% · báo nhầm **8.1%** → giảm **16 lần** |
| Firmware ESP32 | `arduino-cli compile` kèm model thật | Biên dịch sạch, 38% flash, 16% RAM |
| Lõi firmware (detector, máy trạng thái, hiệu chuẩn) | Unit test C++ `-Wall -Werror` | Đạt |
| Review code độc lập (firmware, server, dashboard) | Đối chiếu mã nguồn thư viện ESP32/WiFiManager/MPU6050 | 8 vấn đề tìm thấy, **đã sửa hết** |
| Server/dashboard chịu bản tin MQTT sai/độc hại | Gửi `null`, mảng, chuỗi `<script>`, số sai kiểu | Không sập, không XSS |
| Server + camera + Telegram + dashboard | 3 kịch bản demo qua MQTT thật | Đạt |

> Tổng cộng 26 kiểm thử tự động: `.venv/bin/python -m pytest`.
> Những gì **chưa** kiểm chứng được: chạy trên ESP32 thật, cảm biến MPU6050 thật, thời gian suy luận thật trên ESP32.

---

## 1. Cài đặt (một lần)

Cần Python **3.10–3.12** (MediaPipe chưa hỗ trợ 3.13+), Homebrew (macOS).

```bash
brew install mosquitto arduino-cli
```

```bash
python3.11 -m venv .venv
```

```bash
.venv/bin/pip install -r requirements.txt
```

```bash
cp .env.example .env
```

Điền Telegram vào `.env` nếu có (mục 6). Để trống thì hệ thống chạy **chế độ thử**: tin nhắn và ảnh lưu vào `logs/`.

## 2. Chạy hệ thống — một lệnh

```bash
.venv/bin/python run.py
```

Lệnh này bật MQTT broker (nếu chưa chạy), server, camera (webcam) rồi mở dashboard **http://localhost:8088**.
- Camera điện thoại (app *IP Webcam* / *DroidCam*): `run.py --camera http://IP_DIEN_THOAI:8080/video`
- Không có webcam: `run.py --camera-sim`
- Lần đầu macOS hỏi quyền Camera cho Terminal: *System Settings → Privacy & Security → Camera*.
- Đặt camera **cao, nhìn chéo xuống sàn**, thấy toàn thân.

**Chưa có đai lưng?** Mở terminal khác và chạy bộ giả lập. Nó gửi đúng các bản tin như firmware thật:
```bash
.venv/bin/python -m simulator.belt_sim
```
Gõ `f` = ngã · `d` = rơi thiết bị · `j` = nhảy/chạy (bị bỏ qua) · `c` = bấm nút hủy · `o` = đai mất kết nối.

**Tập dượt 3 kịch bản demo tự động** (khoảng 45 giây, khi `run.py` đang chạy):
```bash
.venv/bin/python -m simulator.run_scenarios
```

| # | Hành động khi demo | Kết quả |
|---|---|---|
| 1 | Thả rơi đai, người vẫn đứng | `Belt: Fall Warning \| Camera: Standing -> System Action: IGNORED (False Alarm Dismissed)` — đai tự tắt còi sau ~3 s |
| 2 | Ngã xuống sofa, bấm nút ở giây thứ 5 | `... -> CANCELLED (User pressed cancel)` |
| 3 | Ngã xuống thảm, nằm im 15 s | `Belt: Fall Warning \| Camera: Lying -> System Action: SOS SENT (Fall Confirmed)` + Telegram kèm ảnh |

### Dashboard
- **Banner trạng thái**: An toàn / Cảnh báo sơ cấp (vòng đếm ngược) / SOS, kèm các bước Decision Fusion (đai · chờ hủy · camera).
- **Đai lưng**: WiFi, thời gian chạy, thời gian AI, hướng lắp; biểu đồ gia tốc 2 phút với ngưỡng 2g; đồng hồ góc nghiêng thân; bảng các va chạm đã xét (đỉnh, xác suất AI, góc nghiêng, kết luận).
- **Camera**: hình trực tiếp kèm khung xương, tư thế, độ tin cậy, FPS.
- **Decision Fusion + nhật ký**, ảnh hiện trường đã gửi, và thông tin hệ thống: **địa chỉ server cho đai** (`fallserver.local · IP`), MQTT, Telegram.
- Nút **Bật âm thanh** để máy tính kêu khi có cảnh báo; **Đã xác nhận an toàn** để reset sau SOS.

---

## 3. Khi có phần cứng

### 3.1 Đấu dây (ESP32 DevKit V1)

| Linh kiện | Chân linh kiện | ESP32 |
|---|---|---|
| MPU6050 (GY-521) | VCC / GND / SDA / SCL | **3V3** / GND / GPIO21 / GPIO22 (AD0 để trống → địa chỉ 0x68) |
| OLED SSD1306 0.96" I2C | VCC / GND / SDA / SCL | 3V3 / GND / GPIO21 / GPIO22 (chung bus) |
| Buzzer chủ động | + / − | GPIO25 / GND |
| LED đỏ + điện trở 220 Ω | Anode | GPIO26 |
| LED xanh + điện trở 220 Ω | Anode | GPIO27 |
| Tact switch | 2 chân | GPIO33 và GND |

Đổi chân trong [`firmware/fall_belt/config.h`](firmware/fall_belt/config.h) nếu đấu khác.

**Hướng lắp MPU6050** (mặc định, khỏi cần hiệu chuẩn): gắn **đứng** phía trước bụng trên đai, **mặt chip hướng ra ngoài**, **mũi tên Y trên board chỉ lên đầu**. Lắp kiểu khác thì dùng hiệu chuẩn bằng nút (mục 3.3).

### 3.2 Nạp firmware — một lệnh
Cắm ESP32 qua USB rồi chạy:
```bash
.venv/bin/python firmware/flash.py --monitor
```
Script tự cài bộ công cụ ESP32 và thư viện, biên dịch kèm model AI, tìm cổng USB rồi nạp, sau đó mở Serial Monitor. Nếu kẹt ở `Connecting...`, giữ nút **BOOT** trên ESP32.

<details><summary>Dùng Arduino IDE thay vì script</summary>

1. Boards Manager: cài **esp32 by Espressif**. Library Manager: cài **Adafruit MPU6050**, **Adafruit SSD1306**, **Adafruit GFX Library**, **PubSubClient**, **WiFiManager** (tzapu).
2. *Sketch → Include Library → Add .ZIP Library…*, chọn `firmware/ei_models/Fall-Detection-SisFall_inferencing.zip`.
3. Mở `firmware/fall_belt/fall_belt.ino`. Board **ESP32 Dev Module**, *Tools → Partition Scheme →* **Huge APP (3MB No OTA)**. Upload.
</details>

### 3.3 Lần đầu bật đai
1. **Tự kiểm tra**: OLED hiện `MPU6050 OK`, `OLED OK`, tên model AI; còi kêu một tiếng, 2 LED sáng. Nếu MPU6050 lỗi, LED đỏ nháy nhanh: kiểm tra dây.
2. **Cấu hình WiFi bằng điện thoại**: đai phát WiFi **`FallBelt-Setup`** (mật khẩu **`fallbelt123`**, hiện trên OLED). Kết nối vào, trang cấu hình tự mở (hoặc vào `192.168.4.1`). Trang tự đóng sau 3 phút không dùng. Chọn WiFi nhà bạn (**2.4 GHz**, chung mạng với máy tính) và nhập mật khẩu. Ô *Địa chỉ server* để mặc định **`fallserver.local`**: server tự quảng bá tên này. Mạng chặn mDNS thì nhập IP hiển thị trên dashboard.
3. Dashboard hiện **Đai lưng: Online**.
4. **Hiệu chuẩn hướng lắp** (nên làm, 10 giây): đeo đai, **giữ nút 3 giây** → đứng thẳng yên (beep 1) → **cúi người về trước ~45°** và giữ yên (beep 2) → beep 3 lần là xong. Kết quả lưu vĩnh viễn.

### 3.4 Sử dụng
| Thao tác | Chức năng |
|---|---|
| Bấm nhanh nút | **Hủy** báo động (lúc đếm ngược hoặc SOS) |
| Giữ nút 3 s (khi bình thường) | Hiệu chuẩn hướng lắp |
| Giữ nút 8 s, hoặc giữ nút lúc cắm điện | Mở lại cấu hình WiFi |

| Trạng thái | Còi | LED | OLED |
|---|---|---|---|
| Bình thường | im | xanh sáng (nháy = mất mạng) | AN TOAN, \|a\|, góc thân, va chạm gần nhất |
| Phát hiện ngã | bíp mỗi giây | đỏ nháy | đếm ngược 15 s, "Bam nut de HUY" |
| Chờ camera xác nhận | bíp nhanh | đỏ nháy nhanh | DANG XAC NHAN |
| SOS | hú dồn dập | đỏ sáng | SOS! |

Đai **mất mạng** lúc hết đếm ngược, hoặc server không phản hồi trong 20 s, thì tự chuyển SOS và hú còi tại chỗ. Mất WiFi (vd. router khởi động lại sau mất điện) thì đai tự kết nối lại mỗi 15 s; việc phát hiện té ngã vẫn chạy trong lúc đó. OLED báo **LOI CAM BIEN** nếu dây MPU6050 lỏng.

**Lệnh Serial (115200)**: `help`, `info` (trạng thái), `fall` (giả lập ngã để thử cả chuỗi), `cancel`, `calib`, `wifi`, `data` (in dữ liệu cảm biến để thu dữ liệu), `factory`, `reboot`.

---

## 4. Thuật toán phát hiện trên đai

[`detector.cpp`](firmware/fall_belt/detector.cpp) là C++ thuần, dùng chung cho ESP32 và bản kiểm thử trên PC:

1. Lấy mẫu MPU6050 **50 Hz** (±16 g, ±2000 °/s, lọc 21 Hz) trong task riêng; quy đổi về hệ trục SisFall (X phải, Y xuống, Z trước).
2. |a| > **2 g** → lấy đỉnh cao nhất trong 0,5 s; nhiều đỉnh liên tiếp đều được xét (hàng đợi), nên ngã ngay sau bước chạy không bị bỏ sót.
3. Đủ 2,5 s sau đỉnh thì xét:
   - **AI**: model Edge Impulse trên cửa sổ 2 s có **đỉnh ở chính giữa**. Đây đúng là cách dữ liệu train được cắt: mọi cửa sổ Fall có đỉnh tại mẫu 50.
   - **Thân nghiêng thêm** ≥ 30°: hướng trọng lực 1–2 s trước so với 1–2,5 s sau. Không phụ thuộc cách gắn cảm biến.
   - **Trước va chạm thân gần thẳng đứng** (≤ 65°): loại trường hợp đang nằm trên giường rồi trở mình.
4. Té ngã ⇔ P(ngã) ≥ 0,5 **và** nghiêng ≥ 30° **và** trước va chạm ≤ 65°.

Ngưỡng được chọn bằng `tinyml/stream_eval.py --grid` trên 4500 bản ghi:

| Cấu hình | Recall | Báo nhầm (bản ghi ADL) |
|---|---|---|
| Sketch bàn giao: trượt 0,5 s, P ≥ 0,8 × 2 lần | 95.8% | 8.1% (17.9 lần/giờ) |
| Chỉ AI theo đỉnh (không xét tư thế) | 97.2% | 12.1% |
| Chỉ luật tư thế (không AI) | 97.1–97.6% | 1.0–2.3% |
| **Firmware: AI + nghiêng + tư thế trước** | **95.7%** | **0.5%** (1 lần/giờ) |

Phần lớn ca bỏ sót là ngã khi đang ngồi (F13/F14), vốn có va chạm nhẹ. Camera bù lại phần này: đai mất kết nối mà camera thấy nằm lâu thì vẫn SOS.

## 5. TinyML: dữ liệu, đánh giá, train lại

| Thư mục / file | Nội dung |
|---|---|
| `firmware/ei_models/*.zip` | 2 model Edge Impulse của nhóm. Firmware dùng **Fall-Detection-SisFall** (tốt hơn hẳn bản ESP32: 100% so với 82.5%) |
| `data/ei_sisfall/` | Dữ liệu JSON nhóm đã dùng train (copy từ thư mục Drive `SisFall/`) |
| `data/sisfall_raw/` | SisFall gốc: `git clone --depth 1 https://github.com/Fall-Prevention-Team/sisfallData data/sisfall_raw` |

```bash
.venv/bin/python tinyml/evaluate_ei.py
```
Đánh giá các model trên tập test, bằng đúng mã C++ biên dịch cho PC.

```bash
.venv/bin/python tinyml/stream_eval.py --grid
```
Chạy firmware detector trên toàn bộ SisFall và so sánh các ngưỡng.

**Fine-tune bằng dữ liệu của chính đai** (nên làm trước khi demo nghiên cứu):
1. Gõ `data` trong Serial Monitor. Đai sẽ in `ax,ay,az,gx,gy,gz` ở 50 Hz, đúng hệ trục và đơn vị của model.
2. Đóng Serial Monitor. Cài công cụ bằng `npm install -g edge-impulse-cli`, rồi chạy `edge-impulse-data-forwarder --frequency 50` và đặt tên trục `ax,ay,az,gx,gy,gz`.
3. Thu mẫu `Fall` (ngã lên đệm) và `Normal` (đi, ngồi phịch, cúi, nhảy) vào project Edge Impulse của nhóm.
4. Muốn train lại từ SisFall cho khớp chiến lược kích hoạt theo đỉnh, chạy lệnh dưới đây rồi upload thư mục kết quả. Lệnh này tạo thêm các cửa sổ sinh hoạt có va chạm mạnh, căn đỉnh vào giữa:
   ```bash
   .venv/bin/python tinyml/sisfall_to_ei.py --sisfall-dir data/sisfall_raw --hard-negatives
   ```
5. Deploy → Arduino library → thay file trong `firmware/ei_models/`, sửa `EI_HEADER` trong `config.h` nếu đổi tên project, rồi chạy lại `stream_eval.py` để so sánh.

## 6. Telegram
1. Nhắn **@BotFather** → `/newbot` → nhận **token**. Nhắn một tin bất kỳ cho bot vừa tạo.
2. Lấy **chat id** qua **@userinfobot**.
3. Điền `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` (nhiều người nhận thì ngăn cách bằng dấu phẩy) vào `.env`, khởi động lại, rồi bấm **Gửi Telegram thử** trên dashboard.

## 7. Cấu trúc
| Thư mục | Nội dung |
|---|---|
| `firmware/fall_belt/` | Firmware: `detector`, `belt_logic`, `orientation` (C++ thuần, có test) · `net` (WiFi/MQTT/mDNS) · `display` · `settings` · `config.h` |
| `firmware/flash.py` | Nạp firmware một lệnh |
| `server/` | `fusion.py` (luật hợp nhất), `main.py` (MQTT + dashboard), `discovery.py` (mDNS), `telegram.py`, `static/index.html` |
| `vision/` | Camera: `posture.py` (luật tư thế), `backends.py` (MediaPipe / YOLO tùy chọn) |
| `tinyml/` | Chuyển đổi, đánh giá model và bộ phát hiện trên SisFall |
| `tools/ei_host/` | Biên dịch model Edge Impulse + firmware detector để chạy trên PC |
| `simulator/` | Giả lập đai, camera, tự chạy 3 kịch bản |
| `tests/` | `pytest` (Python + C++) |

Giao thức MQTT: [`common/protocol.py`](common/protocol.py). Mọi ngưỡng fusion chỉnh trong `.env`.

## 8. Xử lý sự cố
| Hiện tượng | Cách xử lý |
|---|---|
| OLED đai ghi `NO SRV` | Đai chưa tìm thấy server. Kiểm tra `run.py` đang chạy và cùng mạng WiFi. Mạng chặn mDNS thì giữ nút 8 s và nhập IP máy tính (hiện ở mục *Hệ thống* trên dashboard). Tắt tường lửa macOS cho cổng 1883 |
| OLED ghi `NO WIFI` | WiFi phải 2.4 GHz. Giữ nút 8 s để cấu hình lại |
| Báo ngã nhầm khi đeo | Chạy hiệu chuẩn hướng lắp (giữ nút 3 s); xem cột AI/nghiêng trong bảng va chạm trên dashboard |
| Không báo khi ngã thử | Gõ `info` trong Serial để xem góc thân; thử `fall` để kiểm tra chuỗi cảnh báo |
| Camera nằm nhưng báo Standing | Đặt camera cao hơn, tránh để chân hướng thẳng vào ống kính; chỉnh `PostureParams` trong `vision/posture.py` |
| `pip install mediapipe` lỗi | Dùng Python 3.11 |
