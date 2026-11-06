// Máy trạng thái cảnh báo của đai lưng — C++ thuần (kiểm thử được trên PC).
//
//   IDLE --té ngã--> ALARM (đếm ngược) --bấm nút--> IDLE (gửi cancel)
//                      | hết giờ
//                      v
//        online: WAIT_SERVER --server "sos"--> SOS      --server "dismiss"--> IDLE
//        offline / server im lặng quá lâu --> SOS (hú còi tại chỗ)
//   SOS --bấm nút--> IDLE (gửi cancel);  server "reset" -> IDLE
#pragma once
#include <stdint.h>

namespace fall {

enum class BeltState : uint8_t { Idle, Alarm, WaitServer, Sos };
enum class BeltEvent : uint8_t { None, SendImpact, SendCancel };

struct BeltOutputs {
    bool buzzer;
    bool led_red;
    bool led_green;
};

class BeltController {
public:
    BeltController(uint32_t countdown_ms, uint32_t server_timeout_ms)
        : countdown_ms_(countdown_ms), server_timeout_ms_(server_timeout_ms) {}

    BeltEvent on_fall(uint32_t now);
    BeltEvent on_button(uint32_t now);
    void on_command(const char *cmd, uint32_t now);
    void tick(uint32_t now, bool online);

    BeltOutputs outputs(uint32_t now, bool online) const;
    int remaining_s(uint32_t now) const;
    BeltState state() const { return state_; }
    const char *state_name() const;

private:
    void enter(BeltState s, uint32_t now) { state_ = s; since_ = now; }

    uint32_t countdown_ms_;
    uint32_t server_timeout_ms_;
    BeltState state_ = BeltState::Idle;
    uint32_t since_ = 0;
};

}  // namespace fall
