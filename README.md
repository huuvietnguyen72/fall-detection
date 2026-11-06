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

## Hướng dẫn từng bước (macOS và Windows)

> Các lệnh khác nhau giữa hai hệ điều hành được ghi riêng **macOS** / **Windows**. Trên Windows, gõ lệnh trong **PowerShell**.
> Từ bước 2 trở đi, mọi lệnh `python ...` chạy trong thư mục `fall-detection` **sau khi đã kích hoạt môi trường ảo** (bước 1.3).

### Bước 0. Cài phần mềm nền (một lần)

| Cần cài | macOS (cài [Homebrew](https://brew.sh) trước) | Windows |
|---|---|---|
| Git | `brew install git` | `winget install Git.Git` |
| Python **3.11** (MediaPipe chưa hỗ trợ 3.13+) | `brew install python@3.11` | `winget install Python.Python.3.11` |
| MQTT broker Mosquitto | `brew install mosquitto` | `winget install EclipseFoundation.Mosquitto` |
| arduino-cli (để nạp ESP32) | `brew install arduino-cli` | `winget install ArduinoSA.CLI`, hoặc tải bản Windows ở [trang cài đặt chính thức](https://arduino.github.io/arduino-cli/latest/installation/) |
| Trình biên dịch C++ (chỉ cần cho lệnh chấm ngưỡng ở bước 7) | `xcode-select --install` | Dùng [WSL](https://learn.microsoft.com/windows/wsl/install) (Ubuntu) hoặc chạy bước 7.2 trên máy Mac |
| Driver USB của ESP32 | Thường có sẵn | Cài **CP210x** ([Silicon Labs](https://www.silabs.com/developer-tools/usb-to-uart-bridge-vcp-drivers)) hoặc **CH340** ([WCH](https://www.wch-ic.com/downloads/CH341SER_EXE.html)), tùy chip in trên board |

Cài xong trên Windows thì **đóng PowerShell, mở lại** để nhận lệnh mới. Thêm 2 việc riêng cho Windows:

1. **Tắt dịch vụ Mosquitto mặc định.** Bộ cài Windows tự chạy Mosquitto chỉ nghe trên máy, nên đai không kết nối được. Mở PowerShell **Run as Administrator** rồi chạy:
   ```powershell
   Stop-Service mosquitto; Set-Service mosquitto -StartupType Manual
   ```
   Từ đó `run.py` tự bật Mosquitto với cấu hình của dự án.
2. **Tường lửa:** lần đầu chạy, Windows hỏi quyền cho `python.exe` và `mosquitto.exe`. Chọn **Allow** cho mạng **Private**, và đặt WiFi nhà ở chế độ *Private network*.

### Bước 1. Tải code và cài thư viện Python

**1.1. Tải code** (repo đang để riêng tư, người khác cần được mời vào repo trước):
```bash
git clone https://github.com/khuatminh/fall-detection.git
```
```bash
cd fall-detection
```

**1.2. Tạo môi trường ảo:**

macOS:
```bash
python3.11 -m venv .venv
```
Windows:
```powershell
py -3.11 -m venv .venv
```

**1.3. Kích hoạt môi trường ảo** (làm lại mỗi khi mở terminal mới):

macOS:
```bash
source .venv/bin/activate
```
Windows (nếu báo lỗi *running scripts is disabled*, chạy trước `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`):
```powershell
.venv\Scripts\Activate.ps1
```

**1.4. Cài thư viện** (MediaPipe, OpenCV, Flask, MQTT...):
```bash
python -m pip install -r requirements.txt
```

**1.5. Tạo file cấu hình:**

macOS:
```bash
cp .env.example .env
```
Windows:
```powershell
copy .env.example .env
```

Điền Telegram vào `.env` nếu muốn (mục 5). Để trống thì tin nhắn và ảnh SOS được lưu vào `logs/` thay vì gửi đi.

### Bước 2. Chạy thử khi chưa có phần cứng
```bash
python run.py --camera-sim
```
Dashboard tự mở ở **http://localhost:8088**. Mở terminal thứ hai, kích hoạt lại môi trường ảo (bước 1.3), rồi chạy:
```bash
python -m simulator.run_scenarios
```
Lệnh này tự diễn 3 kịch bản demo. Bỏ `--camera-sim` để dùng webcam thật (chi tiết ở mục 1).

### Bước 3. Đấu dây
Theo bảng ở **mục 2.1**. Kiểm tra kỹ: MPU6050 và OLED cắm vào **3V3**, không cắm vào 5V; SDA → GPIO21, SCL → GPIO22.

### Bước 4. Nạp firmware
Cắm ESP32 bằng cáp USB **có dây dữ liệu** (cáp chỉ sạc sẽ không nhận). Sau đó chạy:
```bash
python firmware/flash.py --monitor
```
Lần đầu, script mất khoảng 5 phút để tự cài bộ công cụ ESP32, 5 thư viện Arduino, và giải nén model AI từ `firmware/ei_models/Fall-Detection-SisFall_inferencing.zip`. Sau đó nó biên dịch, tự tìm cổng USB, nạp, rồi mở Serial Monitor (Ctrl+C để thoát).

- **Không tìm thấy cổng:** chỉ định cổng bằng tay. Trên Windows xem số COM trong *Device Manager → Ports (COM & LPT)*, rồi chạy `python firmware/flash.py --port COM5`. Trên macOS là dạng `--port /dev/cu.usbserial-0001`.
- **Kẹt ở `Connecting...`:** giữ nút **BOOT** trên ESP32 cho đến khi thấy phần trăm nạp chạy.
- Muốn dùng Arduino IDE thay vì script: xem mục 2.2.

### Bước 5. Cấu hình đai lần đầu
1. Chạy `python run.py` trên máy tính. Máy tính và đai phải chung một mạng WiFi **2.4 GHz**.
2. OLED hiện tên WiFi **`FallBelt-Setup`**. Dùng điện thoại kết nối vào WiFi đó (mật khẩu `fallbelt123`), chọn WiFi nhà và nhập mật khẩu, giữ ô server mặc định là `fallserver.local`, rồi bấm Save.
3. Dashboard hiện **Đai lưng: Online**. Nếu OLED báo `NO SRV`, giữ nút 8 giây để mở lại trang cấu hình và nhập IP máy tính. IP này hiện ở ô *Hệ thống* trên dashboard.
4. Gõ `fall` trong Serial Monitor để thử cả chuỗi còi, LED, đếm ngược và dashboard mà không cần ngã thật.

### Bước 6. Demo
Đeo đai và đặt camera theo mục 1, rồi diễn 3 kịch bản trong bảng ở mục 1.

### Bước 7. Fine-tune bằng phần cứng

Làm lần lượt từ 7.1. Đa số trường hợp chỉ cần 7.1 và 7.2.

**7.1. Hiệu chuẩn hướng lắp (10 giây, bắt buộc nếu lắp cảm biến khác mặc định).** Đeo đai, **giữ nút 3 giây** → đứng thẳng yên (bíp 1) → cúi người về trước khoảng 45° và giữ yên (bíp 2) → bíp 3 lần là xong. Đai lưu vĩnh viễn kết quả. Gõ `info` trong Serial Monitor để xem góc thân: đứng thẳng phải gần 0°, nằm phải gần 90°.

**7.2. Thu dữ liệu từ đai và chỉnh ngưỡng.** Bước này cho biết với chính đai, người đeo và cách lắp của bạn, firmware bắt được bao nhiêu cú ngã và báo nhầm bao nhiêu.

Đóng Serial Monitor, giữ đai cắm USB vào máy tính (dùng cáp dài, hoặc ngã gần máy tính), rồi chạy:
```bash
python tinyml/belt_collect.py record --label Fall
```
Mỗi lần nhấn Enter, máy đếm ngược 3 giây rồi ghi 8 giây. Trong lúc ghi: **đứng yên khoảng 2 giây → ngã xuống đệm → nằm yên đến khi hết giờ**. Nên thu ít nhất 15 lần, đủ các kiểu: ngã về trước, ngã ngửa, ngã sang hai bên, khuỵu gối. Gõ `q` để kết thúc.

```bash
python tinyml/belt_collect.py record --label Normal
```
Tương tự, thu ít nhất 20 lần sinh hoạt dễ gây nhầm: ngồi phịch xuống ghế, cúi nhặt đồ, nhảy, chạy bộ, nằm xuống giường, tháo đai đặt mạnh xuống bàn.

Sau đó chấm điểm (cần trình biên dịch C++, xem bước 0):
```bash
python tinyml/belt_collect.py eval --grid
```
Lệnh này chạy **đúng mã firmware và model** trên từng lần thử. Bảng kết quả có các cột: đỉnh va chạm (g), xác suất AI, góc nghiêng thân, kết luận, và đánh dấu `<- SAI` ở lần thử sai. Phía dưới là tỉ lệ bắt ngã và báo nhầm cho 27 bộ ngưỡng. Chọn bộ ngưỡng phù hợp, sửa `TRIGGER_G`, `AI_THRESHOLD`, `MIN_TILT_DEG` trong [`firmware/fall_belt/config.h`](firmware/fall_belt/config.h), rồi nạp lại bằng bước 4.

Mẹo đọc kết quả:
- Ngã bị bỏ sót vì đỉnh dưới 2 g (ngã lên đệm dày): giảm `TRIGGER_G` xuống 1.8.
- Bỏ sót vì AI thấp: giảm `AI_THRESHOLD`, hoặc làm bước 7.3.
- Báo nhầm khi đặt đai xuống bàn: đã có camera hỗ trợ, nên chỉ tăng ngưỡng nếu nhầm quá nhiều.

**7.3. Train lại model AI bằng dữ liệu của đai.** Chỉ làm khi bước 7.2 cho thấy AI hay chấm sai.

Lệnh `record` ở bước 7.2 đã tự cắt sẵn các cửa sổ 2 giây, đỉnh va chạm nằm giữa (đúng cách dữ liệu train được cắt), vào thư mục `data/belt/ei/`. Tên file dạng `Fall.xxx.csv` / `Normal.xxx.csv`, nên Edge Impulse tự hiểu nhãn.

1. Đăng nhập [Edge Impulse](https://studio.edgeimpulse.com) và mở project **Fall-Detection-SisFall** của nhóm.
2. Vào **Data acquisition → Upload data**: chọn toàn bộ file trong `data/belt/ei/`, chọn *Automatically split between training and testing*, chọn *Infer from filename*, rồi bấm Upload.
3. Vào **Retrain model → Train model**, sau đó **Model testing → Classify all** để xem accuracy mới.
4. Vào **Deployment**: chọn **Arduino library**, bản **Quantized (int8)**, bấm **Build**.
5. Ghi đè file zip vừa tải lên `firmware/ei_models/Fall-Detection-SisFall_inferencing.zip` (giữ nguyên tên file).
6. Chạy lại `python tinyml/belt_collect.py eval` để so sánh với model cũ. Nếu tốt hơn thì nạp lại bằng bước 4.

---

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

> Tổng cộng 30 kiểm thử tự động: `python -m pytest`.
> Những gì **chưa** kiểm chứng được: chạy trên ESP32 thật, cảm biến MPU6050 thật, thời gian suy luận thật trên ESP32.

---

## 1. Chạy hệ thống — một lệnh

```bash
python run.py
```

Lệnh này bật MQTT broker (nếu chưa chạy), server, camera (webcam) rồi mở dashboard **http://localhost:8088**.
- Camera điện thoại (app *IP Webcam* / *DroidCam*): `run.py --camera http://IP_DIEN_THOAI:8080/video`
- Không có webcam: `run.py --camera-sim`
- Lần đầu macOS hỏi quyền Camera cho Terminal: *System Settings → Privacy & Security → Camera*.
- Đặt camera **cao, nhìn chéo xuống sàn**, thấy toàn thân.

**Chưa có đai lưng?** Mở terminal khác và chạy bộ giả lập. Nó gửi đúng các bản tin như firmware thật:
```bash
python -m simulator.belt_sim
```
Gõ `f` = ngã · `d` = rơi thiết bị · `j` = nhảy/chạy (bị bỏ qua) · `c` = bấm nút hủy · `o` = đai mất kết nối.

**Tập dượt 3 kịch bản demo tự động** (khoảng 45 giây, khi `run.py` đang chạy):
```bash
python -m simulator.run_scenarios
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

## 2. Khi có phần cứng

### 2.1 Đấu dây (ESP32 DevKit V1)

| Linh kiện | Chân linh kiện | ESP32 |
|---|---|---|
| MPU6050 (GY-521) | VCC / GND / SDA / SCL | **3V3** / GND / GPIO21 / GPIO22 (AD0 để trống → địa chỉ 0x68) |
| OLED SSD1306 0.96" I2C | VCC / GND / SDA / SCL | 3V3 / GND / GPIO21 / GPIO22 (chung bus) |
| Buzzer chủ động | + / − | GPIO25 / GND |
| LED đỏ + điện trở 220 Ω | Anode | GPIO26 |
| LED xanh + điện trở 220 Ω | Anode | GPIO27 |
| Tact switch | 2 chân | GPIO33 và GND |

Đổi chân trong [`firmware/fall_belt/config.h`](firmware/fall_belt/config.h) nếu đấu khác.

**Hướng lắp MPU6050** (mặc định, khỏi cần hiệu chuẩn): gắn **đứng** phía trước bụng trên đai, **mặt chip hướng ra ngoài**, **mũi tên Y trên board chỉ lên đầu**. Lắp kiểu khác thì dùng hiệu chuẩn bằng nút (mục 2.3).

### 2.2 Nạp firmware — một lệnh
Cắm ESP32 qua USB rồi chạy:
```bash
python firmware/flash.py --monitor
```
Script tự cài bộ công cụ ESP32 và thư viện, biên dịch kèm model AI, tìm cổng USB rồi nạp, sau đó mở Serial Monitor. Nếu kẹt ở `Connecting...`, giữ nút **BOOT** trên ESP32.

<details><summary>Dùng Arduino IDE thay vì script</summary>

1. Boards Manager: cài **esp32 by Espressif**. Library Manager: cài **Adafruit MPU6050**, **Adafruit SSD1306**, **Adafruit GFX Library**, **PubSubClient**, **WiFiManager** (tzapu).
2. *Sketch → Include Library → Add .ZIP Library…*, chọn `firmware/ei_models/Fall-Detection-SisFall_inferencing.zip`.
3. Mở `firmware/fall_belt/fall_belt.ino`. Board **ESP32 Dev Module**, *Tools → Partition Scheme →* **Huge APP (3MB No OTA)**. Upload.
</details>

### 2.3 Lần đầu bật đai
1. **Tự kiểm tra**: OLED hiện `MPU6050 OK`, `OLED OK`, tên model AI; còi kêu một tiếng, 2 LED sáng. Nếu MPU6050 lỗi, LED đỏ nháy nhanh: kiểm tra dây.
2. **Cấu hình WiFi bằng điện thoại**: đai phát WiFi **`FallBelt-Setup`** (mật khẩu **`fallbelt123`**, hiện trên OLED). Kết nối vào, trang cấu hình tự mở (hoặc vào `192.168.4.1`). Trang tự đóng sau 3 phút không dùng. Chọn WiFi nhà bạn (**2.4 GHz**, chung mạng với máy tính) và nhập mật khẩu. Ô *Địa chỉ server* để mặc định **`fallserver.local`**: server tự quảng bá tên này. Mạng chặn mDNS thì nhập IP hiển thị trên dashboard.
3. Dashboard hiện **Đai lưng: Online**.
4. **Hiệu chuẩn hướng lắp** (nên làm, 10 giây): đeo đai, **giữ nút 3 giây** → đứng thẳng yên (beep 1) → **cúi người về trước ~45°** và giữ yên (beep 2) → beep 3 lần là xong. Kết quả lưu vĩnh viễn.

### 2.4 Sử dụng
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

## 3. Thuật toán phát hiện trên đai

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

## 4. TinyML: dữ liệu, đánh giá, train lại

| Thư mục / file | Nội dung |
|---|---|
| `firmware/ei_models/*.zip` | 2 model Edge Impulse của nhóm. Firmware dùng **Fall-Detection-SisFall** (tốt hơn hẳn bản ESP32: 100% so với 82.5%) |
| `data/ei_sisfall/` | Dữ liệu JSON nhóm đã dùng train (copy từ thư mục Drive `SisFall/`) |
| `data/sisfall_raw/` | SisFall gốc: `git clone --depth 1 https://github.com/Fall-Prevention-Team/sisfallData data/sisfall_raw` |

```bash
python tinyml/evaluate_ei.py
```
Đánh giá các model trên tập test, bằng đúng mã C++ biên dịch cho PC.

```bash
python tinyml/stream_eval.py --grid
```
Chạy firmware detector trên toàn bộ SisFall và so sánh các ngưỡng.

**Fine-tune bằng dữ liệu của chính đai:** xem **Bước 7** ở đầu README (`tinyml/belt_collect.py`).

Muốn train lại từ SisFall cho khớp chiến lược kích hoạt theo đỉnh, chạy lệnh dưới đây. Lệnh này thêm các cửa sổ sinh hoạt có va chạm mạnh, căn đỉnh vào giữa; sau đó upload `data/sisfall_ei_csv` như bước 7.3:
```bash
python tinyml/sisfall_to_ei.py --sisfall-dir data/sisfall_raw --hard-negatives
```

## 5. Telegram
1. Nhắn **@BotFather** → `/newbot` → nhận **token**. Nhắn một tin bất kỳ cho bot vừa tạo.
2. Lấy **chat id** qua **@userinfobot**.
3. Điền `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` (nhiều người nhận thì ngăn cách bằng dấu phẩy) vào `.env`, khởi động lại, rồi bấm **Gửi Telegram thử** trên dashboard.

## 6. Cấu trúc
| Thư mục | Nội dung |
|---|---|
| `firmware/fall_belt/` | Firmware: `detector`, `belt_logic`, `orientation` (C++ thuần, có test) · `net` (WiFi/MQTT/mDNS) · `display` · `settings` · `config.h` |
| `firmware/flash.py` | Nạp firmware một lệnh |
| `server/` | `fusion.py` (luật hợp nhất), `main.py` (MQTT + dashboard), `discovery.py` (mDNS), `telegram.py`, `static/index.html` |
| `vision/` | Camera: `posture.py` (luật tư thế), `backends.py` (MediaPipe / YOLO tùy chọn) |
| `tinyml/` | Chuyển đổi, đánh giá model và bộ phát hiện trên SisFall · `belt_collect.py`: thu dữ liệu từ đai để fine-tune |
| `tools/ei_host/` | Biên dịch model Edge Impulse + firmware detector để chạy trên PC |
| `simulator/` | Giả lập đai, camera, tự chạy 3 kịch bản |
| `tests/` | `pytest` (Python + C++) |

Giao thức MQTT: [`common/protocol.py`](common/protocol.py). Mọi ngưỡng fusion chỉnh trong `.env`.

## 7. Xử lý sự cố
| Hiện tượng | Cách xử lý |
|---|---|
| OLED đai ghi `NO SRV` | Đai chưa tìm thấy server. Kiểm tra `run.py` đang chạy và cùng mạng WiFi. Mạng chặn mDNS thì giữ nút 8 s và nhập IP máy tính (hiện ở mục *Hệ thống* trên dashboard). Tắt tường lửa macOS cho cổng 1883 |
| OLED ghi `NO WIFI` | WiFi phải 2.4 GHz. Giữ nút 8 s để cấu hình lại |
| Báo ngã nhầm khi đeo | Chạy hiệu chuẩn hướng lắp (giữ nút 3 s); xem cột AI/nghiêng trong bảng va chạm trên dashboard |
| Không báo khi ngã thử | Gõ `info` trong Serial để xem góc thân; thử `fall` để kiểm tra chuỗi cảnh báo |
| Camera nằm nhưng báo Standing | Đặt camera cao hơn, tránh để chân hướng thẳng vào ống kính; chỉnh `PostureParams` trong `vision/posture.py` |
| `pip install mediapipe` lỗi | Dùng Python 3.11 |
