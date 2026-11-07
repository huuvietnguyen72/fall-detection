// Sketch thử mạch trên Wokwi (không phải firmware thật): kiểm tra từng linh kiện nối đúng chân.
//   - Quét I2C: phải thấy 0x3C (OLED) và 0x68 (MPU6050)
//   - LED đỏ (GPIO26) / xanh (GPIO27) nháy luân phiên, còi (GPIO25) kêu mỗi 2 giây
//   - Bấm nút (GPIO33): Serial in btn=0
#include <Wire.h>

void setup() {
  Serial.begin(115200);
  pinMode(25, OUTPUT);
  pinMode(26, OUTPUT);
  pinMode(27, OUTPUT);
  pinMode(33, INPUT_PULLUP);
  Wire.begin(21, 22);
  for (uint8_t addr = 1; addr < 127; addr++) {
    Wire.beginTransmission(addr);
    if (Wire.endTransmission() == 0) Serial.printf("I2C 0x%02X\n", addr);
  }
  Serial.println("Quet I2C xong");
}

void loop() {
  static int n = 0;
  digitalWrite(26, n % 2);
  digitalWrite(27, !(n % 2));
  digitalWrite(25, n % 4 == 0);
  Serial.printf("tick %d btn=%d\n", n++, digitalRead(33));
  delay(500);
}
