# Hệ thống giám sát và phát hiện té ngã thời gian thực

*Đai lưng ESP32 (TinyML) + Camera (MediaPipe) + Decision Fusion + cảnh báo Telegram*

![Kiến trúc hệ thống](docs/figures/diagram_architecture.png)

Hệ thống có ba phần chạy song song:
- **Đai lưng** đeo trước bụng (ESP32 + cảm biến MPU6050). Đai tự phát hiện cú ngã bằng AI chạy ngay trên chip, báo bằng còi, đèn và màn hình, và cho người dùng bấm nút hủy.
- **Camera** (webcam, hoặc iPhone qua Wi-Fi) nhìn xem người còn nằm trên sàn không.
- **Server** trên laptop/PC trong nhà hợp nhất hai nguồn. Khi chắc chắn có người ngã, server gửi tin nhắn kèm ảnh hiện trường qua Telegram cho người thân.

| Bạn muốn… | Đọc |
|---|---|
| Chạy thử ngay trên máy mới (không cần phần cứng) | [Mục 1](#1-cài-đặt-và-chạy-trên-máy-mới) |
| Hiểu hệ thống chạy thế nào | [Mục 2](#2-luồng-chạy) |
| Lắp đai, nạp firmware, cấu hình Wi-Fi | [Mục 3](#3-phần-cứng-đai-lưng) |
| Dùng camera iPhone / điện thoại | [Mục 4](#4-camera) |
| Sửa code, chạy test, chỉnh thuật toán | [Mục 6](#6-phát-triển-và-sửa-code) |
| Viết báo cáo, bài báo, poster (số liệu, hình, sơ đồ) | **[docs/BAO_CAO_KY_THUAT.md](docs/BAO_CAO_KY_THUAT.md)** |
| Gặp lỗi | [Mục 8](#8-xử-lý-sự-cố) |

---

## 1. Cài đặt và chạy trên máy mới

### 1.1. Cài phần mềm nền (một lần)

| Cần cài | macOS (cài [Homebrew](https://brew.sh) trước) | Windows (PowerShell) |
|---|---|---|
| Git | `brew install git` | `winget install Git.Git` |
| Python 3.10–3.14 (đã chạy thử 3.11, 3.12, 3.14) | `brew install python` | `winget install Python.Python.3.12` |
| Mosquitto (MQTT broker) | `brew install mosquitto` | `winget install EclipseFoundation.Mosquitto` |
| arduino-cli (chỉ cần khi nạp firmware) | `brew install arduino-cli` | `winget install ArduinoSA.CLI` |
| Trình biên dịch C++ (chỉ cần khi chấm điểm AI / chạy `report/ai_metrics.py`) | `xcode-select --install` | [MSYS2](https://www.msys2.org) rồi `pacman -S mingw-w64-ucrt-x86_64-gcc`; trước khi chấm chạy `$env:Path = "C:\msys64\ucrt64\bin;$env:Path"` |

**Riêng Windows**, cài xong thì đóng và mở lại PowerShell, rồi làm thêm hai việc:
1. **Tắt dịch vụ Mosquitto mặc định**, vì dịch vụ này chỉ nghe trên máy nên đai không vào được. Mở PowerShell *Run as Administrator*:
   ```powershell
   Stop-Service mosquitto; Set-Service mosquitto -StartupType Manual
   ```
   Từ đó `run.py` tự bật Mosquitto bằng cấu hình của dự án.
2. **Tường lửa:** lần đầu chạy, chọn **Allow** cho `python.exe` và `mosquitto.exe` trên mạng **Private**, và đặt Wi-Fi nhà là *Private network*.

### 1.2. Tải code và cài đặt (một lệnh)

```bash
git clone https://github.com/khuatminh/fall-detection.git
cd fall-detection
```

macOS / Linux:
```bash
bash scripts/setup.sh
```
Windows:
```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
```

Script sẽ tạo môi trường ảo `.venv`, cài thư viện, tạo file `.env` từ `.env.example`, tải model MediaPipe, kiểm tra Mosquitto và chạy bộ test. Lần đầu mất vài phút.

### 1.3. Chạy

macOS / Linux:
```bash
.venv/bin/python run.py --camera-sim      # chưa có webcam/đai: camera giả lập
.venv/bin/python run.py                   # dùng webcam (hoặc camera trong .env)
```
Windows:
```powershell
.venv\Scripts\python run.py --camera-sim
.venv\Scripts\python run.py
```

Dashboard tự mở ở **http://localhost:8088**. `Ctrl+C` để tắt mọi thứ.

> Muốn gõ ngắn là `python` thay vì `.venv/bin/python`, hãy kích hoạt môi trường ảo trước: macOS `source .venv/bin/activate`, Windows `.venv\Scripts\Activate.ps1`. Nếu Windows báo *running scripts is disabled*, chạy trước `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`. **Các lệnh `python ...` bên dưới đều giả định đã kích hoạt.**

### 1.4. Thử khi chưa có đai

Mở terminal thứ hai:
```bash
python -m simulator.belt_sim          # gõ f = ngã · d = rơi thiết bị · j = nhảy · c = bấm hủy · o = mất kết nối
python -m simulator.run_scenarios     # tự diễn 3 kịch bản demo (~45 s)
```

| # | Kịch bản | Kết quả mong đợi |
|---|---|---|
| 1 | Thả rơi đai, người vẫn đứng | `IGNORED (False Alarm Dismissed)`, đai tự tắt còi sau ~3 s |
| 2 | Ngã xuống sofa, bấm nút ở giây thứ 5 | `CANCELLED (User pressed cancel)` |
| 3 | Ngã xuống thảm, nằm im 15 s | `SOS SENT (Fall Confirmed)` + Telegram kèm ảnh |

### 1.5. File cấu hình `.env`

Mở `.env` bằng trình soạn thảo bất kỳ. Những dòng hay sửa:

| Biến | Ý nghĩa |
|---|---|
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | Bot gửi cảnh báo (mục 5). Để trống thì tin nhắn và ảnh được lưu vào `logs/` thay vì gửi |
| `CAMERA_SOURCE` | `0` = webcam; `1`, `2`… = camera khác; hoặc URL camera điện thoại (mục 4) |
| `PREVIEW_FPS`, `PREVIEW_WIDTH` | độ mượt và độ nét của video trên dashboard (mặc định 12 FPS, 640 px) |
| `COUNTDOWN_S`, `STANDING_CONFIRM_S`, `VISION_ONLY_LYING_S`, `NO_VISION_POLICY` | ngưỡng của Decision Fusion (mục 2.3) |

`.env` chứa mật khẩu nên **không được đưa lên GitHub** (đã có trong `.gitignore`). Chuyển sang máy khác thì tự tạo lại, hoặc chép file tay.

---

## 2. Luồng chạy

### 2.1. `run.py` bật những gì

```
run.py
 ├─ Mosquitto (MQTT broker, cổng 1883)       mosquitto/mosquitto.conf
 ├─ server.main                              Decision Fusion + dashboard :8088 + Telegram + quảng bá fallserver.local
 └─ vision.main  (hoặc simulator.vision_sim) camera → MediaPipe Pose → tư thế → MQTT
Đai lưng (ESP32) tự tìm fallserver.local qua mDNS rồi kết nối MQTT.
```

Tùy chọn: `--camera <nguồn>` (ghi đè `CAMERA_SOURCE`), `--camera-sim`, `--no-camera` (camera chạy ở máy khác), `--no-browser`.

### 2.2. Một cú ngã đi qua hệ thống thế nào

![Luồng xử lý song song](docs/figures/diagram_parallel_pipeline.png)

1. **Đai** lấy mẫu cảm biến 50 lần mỗi giây. Khi gia tốc vượt 1,8 g, đai chờ 2,5 s rồi chạy model AI trên cửa sổ 2 s quanh va chạm, đồng thời đo góc nghiêng thân trước và sau va chạm. Nếu là ngã, đai kêu bíp, đếm ngược 15 s trên OLED và gửi sự kiện `impact` lên server.
2. **Camera** liên tục nhận diện khung xương và gửi tư thế (ĐỨNG / NGỒI / CÚI / NẰM / không có người) lên server.
3. **Server** đếm ngược 15 s:
   - Người dùng bấm nút trên đai thì hủy.
   - Camera thấy đứng liên tục 3 s thì coi là báo nhầm.
   - Hết 15 s mà camera thấy **NẰM** thì báo **SOS**: đai hú còi, server chụp ảnh hiện trường và gửi Telegram.
   - Hết 15 s mà camera không thấy người thì gửi cảnh báo mức nhẹ.
4. **Dự phòng:** mất đai mà camera thấy nằm ≥ 20 s thì vẫn SOS. Đai mất server 20 s thì tự SOS tại chỗ.

Chi tiết thuật toán, sơ đồ trạng thái và luồng bản tin MQTT: [docs/BAO_CAO_KY_THUAT.md](docs/BAO_CAO_KY_THUAT.md), mục 2 và 4.

### 2.3. Dashboard

- **Banner trạng thái:** An toàn / Cảnh báo (vòng đếm ngược) / SOS, kèm các bước fusion.
- **Đai lưng:** Wi-Fi, thời gian chạy AI, biểu đồ gia tốc 2 phút, góc nghiêng thân, bảng các va chạm đã xét (đỉnh g, xác suất AI, góc, kết luận).
- **Camera:** video trực tiếp có khung xương (MJPEG ~12 FPS), tư thế, độ tin cậy, FPS.
- **Nhật ký fusion**, ảnh hiện trường đã gửi, thông tin hệ thống (địa chỉ server cho đai, MQTT, Telegram).
- Nút **Bật âm thanh**, **Gửi Telegram thử**, **Đã xác nhận an toàn** (reset sau SOS).

---

## 3. Phần cứng (đai lưng)

### 3.1. Linh kiện và đấu dây

ESP32 DevKit V1, MPU6050 (GY-521; nhận cả module dùng chip MPU6500/9250), OLED SSD1306 0,96" I²C, còi chủ động, LED đỏ + LED xanh (mỗi LED một điện trở 220 Ω), nút nhấn, sạc dự phòng.

![Sơ đồ đấu dây](docs/wiring.svg)

| Linh kiện | Chân linh kiện | ESP32 |
|---|---|---|
| MPU6050 | VCC / GND / SDA / SCL | **3V3** / GND / GPIO21 / GPIO22 (AD0 để trống → địa chỉ 0x68) |
| OLED SSD1306 | VCC / GND / SDA / SCL | 3V3 / GND / GPIO21 / GPIO22 (chung bus) |
| Còi chủ động | + / − | GPIO25 / GND |
| LED đỏ + 220 Ω | chân dài | GPIO27 |
| LED xanh + 220 Ω | chân dài | GPIO26 |
| Nút nhấn | 2 chân chéo nhau | GPIO4 và GND (pull-up nội, không cần điện trở) |

- **Không cấp 5 V/VIN** cho MPU6050 và OLED.
- Còi kêu liên tục khi bình thường thì đổi `BUZZER_ACTIVE_HIGH` thành `0` trong [`config.h`](firmware/fall_belt/config.h).
- Đấu khác chân thì sửa trong `config.h`.
- Thử mạch trên trình duyệt: dán [`wokwi/diagram.json`](wokwi/diagram.json) và [`wokwi/sketch.ino`](wokwi/sketch.ino) vào [wokwi.com/projects/new/esp32](https://wokwi.com/projects/new/esp32).

**Hướng lắp MPU6050 mặc định:** gắn đứng trước bụng, mặt chip hướng ra ngoài, mũi tên Y chỉ lên đầu. Lắp kiểu khác thì hiệu chuẩn bằng nút (mục 3.3).

### 3.2. Nạp firmware

Cắm ESP32 bằng cáp USB **có dây dữ liệu**. Cáp chỉ sạc thì board vẫn sáng đèn nhưng máy không nhận.
```bash
python firmware/flash.py --monitor            # tự cài toolchain + thư viện + model, biên dịch, tìm cổng, nạp, mở Serial
python firmware/flash.py --compile-only       # chỉ biên dịch (không cần cắm board)
python firmware/flash.py --port COM5          # chỉ định cổng (macOS: /dev/cu.usbserial-xxxx)
```
- Lần đầu mất khoảng 5 phút.
- **Kẹt ở `Connecting...`:** giữ nút **BOOT** trên board.
- **Máy không thấy cổng:** đổi cáp, cắm thẳng vào máy thay vì qua hub. Trên Mac chip Apple, bấm *Allow* khi macOS hỏi cho phép phụ kiện. Windows có thể cần driver [CP210x](https://www.silabs.com/developer-tools/usb-to-uart-bridge-vcp-drivers) hoặc [CH340](https://www.wch-ic.com/downloads/CH341SER_EXE.html).

<details><summary>Dùng Arduino IDE thay vì script</summary>

1. Boards Manager: cài **esp32 by Espressif**. Library Manager: cài **Adafruit MPU6050**, **Adafruit SSD1306**, **Adafruit GFX Library**, **PubSubClient**, **WiFiManager** (tzapu).
2. *Sketch → Include Library → Add .ZIP Library…*, chọn `firmware/ei_models/Fall-Detection-SisFall_inferencing.zip`.
3. Mở `firmware/fall_belt/fall_belt.ino`, board **ESP32 Dev Module**, *Partition Scheme* **Huge APP (3MB No OTA)**, rồi Upload.
</details>

### 3.3. Lần đầu bật đai

1. **Tự kiểm tra:** OLED hiện `MPU6050 OK`, `OLED OK` và tên model, còi kêu một tiếng. Nếu LED đỏ nháy nhanh thì MPU6050 lỗi, cần kiểm tra dây.
2. **Cấu hình Wi-Fi bằng điện thoại.** Bật `run.py` trên máy tính trước. Điện thoại kết nối Wi-Fi **`FallBelt-Setup`** (mật khẩu `fallbelt123`), trang cấu hình sẽ tự mở (nếu không thì vào `192.168.4.1`). Chọn Wi-Fi nhà (**2,4 GHz**, chung mạng với máy tính). Ô *Địa chỉ server* để mặc định `fallserver.local`, hoặc nhập IP máy tính hiện ở ô *Hệ thống* trên dashboard. Bấm Save.
3. Dashboard hiện **Đai lưng: Online**.
4. **Hiệu chuẩn hướng lắp (10 giây, nên làm):** đeo đai, **giữ nút 3 s**, đứng thẳng yên (bíp 1), cúi về trước khoảng 45° và giữ yên (bíp 2), nghe bíp 3 lần là xong. Kết quả được lưu vĩnh viễn.

Đổi Wi-Fi hoặc đổi máy chủ (ví dụ chuyển từ máy Windows sang Mac): **giữ nút 8 s** để mở lại trang cấu hình. Nếu hai máy cùng chạy `run.py` trong một mạng, cả hai đều xưng là `fallserver.local`. Khi đó nên tắt một máy, hoặc nhập thẳng IP.

### 3.4. Sử dụng

| Thao tác | Chức năng |
|---|---|
| Bấm nhanh nút | **Hủy** báo động (lúc đếm ngược hoặc SOS) |
| Giữ 3 s | Hiệu chuẩn hướng lắp |
| Giữ 8 s, hoặc giữ nút lúc cắm điện | Mở lại cấu hình Wi-Fi |

| Trạng thái | Còi | LED | OLED |
|---|---|---|---|
| Bình thường | im | xanh sáng (nháy = mất mạng) | AN TOAN, \|a\|, góc thân |
| Phát hiện ngã | bíp mỗi giây | đỏ nháy | đếm ngược 15 s, "Bam nut de HUY" |
| Chờ camera xác nhận | bíp nhanh | đỏ nháy nhanh | DANG XAC NHAN |
| SOS | hú dồn dập | đỏ sáng | SOS! |

**Lệnh Serial (115200 baud):** `help`, `info`, `fall` (giả lập ngã để thử cả chuỗi), `cancel`, `calib`, `wifi`, `data`, `factory`, `reboot`.

---

## 4. Camera

| Cách | Cấu hình `CAMERA_SOURCE` trong `.env` |
|---|---|
| Webcam laptop | `0` |
| iPhone đặt gần Mac (Continuity Camera, không cần app) | `1` (nếu vẫn ra webcam Mac thì thử `2`, `3`) |
| Điện thoại đặt bất kỳ đâu, chung Wi-Fi (khuyên dùng) | URL do app phát, ví dụ `http://admin:matkhau@iphone.local:8081/video` |

**Điện thoại qua Wi-Fi:** cài app *IP Camera Lite* (iPhone) hoặc *IP Webcam* (Android), bật server trong app, rồi điền URL (kèm tên/mật khẩu nếu app yêu cầu) vào `.env`. Dùng tên `<tên-máy>.local` thay cho IP thì router có đổi IP vẫn chạy. Để app mở trên màn hình và cắm sạc, vì phần lớn app ngừng phát khi khóa màn hình. Camera rớt mạng thì hệ thống tự kết nối lại.

**Vị trí:** đặt camera **cao, nhìn chéo xuống sàn, thấy toàn thân**, không bị bàn ghế che, có đèn ngủ ban đêm. Đánh giá cho thấy che khuất và thiếu sáng làm camera nhận kém hẳn (xem báo cáo, mục 5.2).

**Mac:** lần đầu dùng webcam, macOS hỏi quyền Camera cho Terminal (*System Settings → Privacy & Security → Camera*).

---

## 5. Telegram

1. Nhắn **@BotFather**, gõ `/newbot` để nhận **token**.
2. **Nhắn `/start` cho bot vừa tạo.** Bot chỉ gửi được tin cho người đã nhắn nó trước.
3. Lấy chat id của bạn qua **@userinfobot**. Lưu ý: không dùng phần số ở đầu token, vì đó là id của chính con bot.
4. Điền `TELEGRAM_BOT_TOKEN` và `TELEGRAM_CHAT_ID` vào `.env` (nhiều người nhận thì cách nhau bằng dấu phẩy), chạy lại `run.py`, rồi bấm **Gửi Telegram thử** trên dashboard.

---

## 6. Phát triển và sửa code

### 6.1. Cấu trúc thư mục

| Thư mục / file | Nội dung | Sửa khi muốn… |
|---|---|---|
| `firmware/fall_belt/config.h` | chân cắm, ngưỡng phát hiện, Wi-Fi/MQTT mặc định | đổi chân, ngưỡng `TRIGGER_G`, `AI_THRESHOLD`… |
| `firmware/fall_belt/detector.*` | bộ phát hiện (kích hoạt + AI + tư thế), C++ thuần có test | đổi thuật toán trên đai |
| `firmware/fall_belt/belt_logic.*` | máy trạng thái của đai (đếm ngược, SOS tại chỗ) | |
| `firmware/fall_belt/fall_belt.ino`, `net.*`, `display.*`, `orientation.*`, `settings.*` | lấy mẫu, Wi-Fi/MQTT/mDNS, OLED, hiệu chuẩn, lưu cấu hình | |
| `firmware/ei_models/*.zip` | model Edge Impulse (firmware dùng **Fall-Detection-SisFall**) | thay model mới |
| `server/fusion.py` | **luật hợp nhất** (không phụ thuộc mạng, có test) | đổi cách quyết định SOS |
| `server/main.py`, `server/static/index.html` | MQTT, dashboard, luồng video | giao diện |
| `server/telegram.py`, `server/discovery.py` | Telegram, quảng bá mDNS | |
| `vision/posture.py` | **luật tư thế** + bộ làm mượt | camera nhận sai tư thế |
| `vision/main.py`, `vision/backends.py` | đọc camera, MediaPipe / YOLO | |
| `common/protocol.py`, `common/settings.py` | chủ đề MQTT, đọc `.env` | |
| `simulator/` | giả lập đai, camera, kịch bản demo | |
| `tinyml/` | đánh giá trên SisFall, thu dữ liệu đai, chấm ngưỡng | |
| `tools/ei_host/` | biên dịch model + detector để chạy trên PC | |
| `report/` | **sinh số liệu, hình, sơ đồ cho báo cáo** | |
| `data/belt/` | dữ liệu thu bằng đai (`raw/` = mỗi lần thử, `ei/` = cửa sổ 2 s cho Edge Impulse) | |
| `tests/` | `pytest` (Python + C++) | |

### 6.2. Kiểm thử

```bash
python -m pytest -q
```
Gồm test fusion, test tư thế, test firmware C++ (cần trình biên dịch C++), và test trên SisFall (tự bỏ qua nếu chưa tải dữ liệu). Sau khi sửa `server/fusion.py`, `vision/posture.py` hay `detector.cpp`, luôn chạy lại lệnh này.

### 6.3. Chỉnh ngưỡng và train lại AI bằng dữ liệu của đai

**Thu dữ liệu qua Wi-Fi** (đai cấp nguồn bằng sạc dự phòng, chung mạng với máy tính; IP đai xem trên dashboard):
```bash
python tinyml/belt_collect.py record --label Fall   --port 192.168.1.20   # hoặc --port belt01.local
python tinyml/belt_collect.py record --label Normal --port 192.168.1.20
```
Mỗi lần nhấn Enter, máy đếm ngược 3 s rồi ghi 8 s: **đứng yên khoảng 2 s, rồi ngã xuống đệm, rồi nằm yên tới hết giờ**. Nên thu ít nhất 15 lần Fall đủ kiểu (trước, ngửa, nghiêng, khuỵu gối) và 20 lần Normal (ngồi phịch, cúi nhặt đồ, nhảy, nằm xuống giường, đặt mạnh đai xuống bàn). Gõ `q` để dừng. `--port` cũng nhận cổng USB (COMx, /dev/...).

**Chấm ngưỡng** (chạy đúng mã firmware và model trên dữ liệu vừa thu):
```bash
python tinyml/belt_collect.py eval --grid
```
Chọn bộ ngưỡng phù hợp, sửa `config.h`, rồi nạp lại (mục 3.2). Mẹo:
- Bỏ sót vì đỉnh dưới ngưỡng thì giảm `TRIGGER_G`.
- Gặp thông báo `Ngã sớm quá` thì làm lại lần đó, nhớ đứng yên 2 s trước khi ngã.
- AI chấm sai thì train lại model như bên dưới.

**Train lại model trên Edge Impulse:**
1. Mở project **Fall-Detection-SisFall** trên [studio.edgeimpulse.com](https://studio.edgeimpulse.com).
2. *Data acquisition → Upload data*: chọn mọi file trong `data/belt/ei/`, chọn *Automatically split* và *Infer from filename*.
3. *Retrain model → Train*.
4. *Deployment → Arduino library → Quantized (int8) → Build*.
5. Ghi đè file zip vào `firmware/ei_models/Fall-Detection-SisFall_inferencing.zip` (giữ nguyên tên).
6. Chạy `python tinyml/belt_collect.py eval` để so với model cũ. Model mới tốt hơn thì mới nạp.

**Đưa dữ liệu mới lên GitHub** để máy khác dùng được: `git add data/belt && git commit && git push`. Thư mục này được phép commit, còn các bộ dữ liệu lớn khác trong `data/` thì không.

### 6.4. Đánh giá trên dữ liệu công khai

```bash
git clone --depth 1 https://github.com/Fall-Prevention-Team/sisfallData data/sisfall_raw   # SisFall, ~940 MB
python tinyml/stream_eval.py --grid          # bộ phát hiện của firmware trên 4500 bản ghi, so các ngưỡng
python tinyml/sisfall_to_ei.py --sisfall-dir data/sisfall_raw --hard-negatives   # tạo dữ liệu train căn đỉnh
```

---

## 7. Số liệu cho báo cáo, bài báo, poster

Toàn bộ nằm trong **[docs/BAO_CAO_KY_THUAT.md](docs/BAO_CAO_KY_THUAT.md)**: kiến trúc, thuật toán, thông số phần cứng (năng lượng, kích thước, tần số lấy mẫu), confusion matrix và Accuracy/Precision/Recall, độ chính xác camera theo điều kiện, độ trễ. Hình nằm ở `docs/figures/` (PNG 300 dpi + SVG), sơ đồ gốc ở `docs/diagrams/`.

Sinh lại mọi số liệu và hình:
```bash
python report/ai_metrics.py               # confusion matrix + chỉ số AI (SisFall + dữ liệu đai)
python report/vision_eval.py              # camera trong 6 điều kiện (tự tải URFD ~100 MB)
python report/latency_bench.py --telegram # độ trễ từng chặng (không ảnh hưởng hệ thống đang chạy)
python report/latency_bench.py --live     # thêm số đo trên đai + camera thật (khi run.py đang chạy, đai bật)
python report/render_diagrams.py          # sơ đồ khối SVG -> PNG (cần Chrome hoặc Edge)
```

---

## 8. Xử lý sự cố

| Hiện tượng | Cách xử lý |
|---|---|
| Máy không thấy ESP32 qua USB (board vẫn sáng) | Cáp chỉ sạc, hoặc hub không truyền dữ liệu: đổi cáp, cắm thẳng vào máy. Mac: bấm *Allow* khi hỏi phụ kiện |
| OLED ghi `NO SRV` | `run.py` chưa chạy hoặc khác mạng. Mạng chặn mDNS thì giữ nút 8 s và nhập IP máy tính. Mở tường lửa cổng 1883 |
| Đai lúc vào lúc không, Serial báo `fallserver.local -> <IP lạ>` | Có máy khác cũng đang chạy `run.py`. Tắt máy đó, hoặc nhập thẳng IP |
| OLED ghi `NO WIFI` | Wi-Fi phải là 2,4 GHz. Giữ nút 8 s để cấu hình lại |
| Camera không lên hình, log báo `CERTIFICATE_VERIFY_FAILED` | Python cài từ python.org trên macOS thiếu chứng chỉ. Code đã dùng `certifi`, chỉ cần chạy lại `pip install -r requirements.txt` |
| Camera điện thoại báo 401 / không kết nối | Thêm `user:pass@` vào URL. Kiểm tra app còn mở và iPhone chưa khóa màn hình |
| Camera nằm mà báo Standing | Đặt camera cao hơn, tránh bị che, bật đèn. Ngưỡng nằm nằm trong `PostureParams` ở `vision/posture.py` |
| Báo ngã nhầm khi đeo | Hiệu chuẩn hướng lắp (giữ nút 3 s). Xem cột AI / góc nghiêng trong bảng va chạm trên dashboard |
| Telegram không nhận tin | Đã nhắn `/start` cho bot chưa? `TELEGRAM_CHAT_ID` phải là id của bạn, không phải id bot. Bấm "Gửi Telegram thử" |
| Port 1883 / 8088 đã bị chiếm | Còn một `run.py` cũ đang chạy, hãy tắt nó (macOS: `lsof -i :1883`, Windows: `netstat -ano \| findstr 1883`) |
