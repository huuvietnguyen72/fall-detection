#include "belt_logic.h"

#include <string.h>

namespace fall {

BeltEvent BeltController::on_fall(uint32_t now) {
    if (state_ != BeltState::Idle) return BeltEvent::None;
    enter(BeltState::Alarm, now);
    return BeltEvent::SendImpact;
}

BeltEvent BeltController::on_button(uint32_t now) {
    if (state_ == BeltState::Idle) return BeltEvent::None;
    enter(BeltState::Idle, now);
    return BeltEvent::SendCancel;
}

void BeltController::on_command(const char *cmd, uint32_t now) {
    if (strcmp(cmd, "sos") == 0) {
        enter(BeltState::Sos, now);
    } else if (strcmp(cmd, "dismiss") == 0) {
        if (state_ == BeltState::Alarm || state_ == BeltState::WaitServer) enter(BeltState::Idle, now);
    } else if (strcmp(cmd, "reset") == 0) {
        enter(BeltState::Idle, now);
    }
}

void BeltController::tick(uint32_t now, bool online) {
    const uint32_t elapsed = now - since_;
    if (state_ == BeltState::Alarm && elapsed >= countdown_ms_) {
        enter(online ? BeltState::WaitServer : BeltState::Sos, now);
    } else if (state_ == BeltState::WaitServer && (!online || elapsed >= server_timeout_ms_)) {
        enter(BeltState::Sos, now);  // không ai xác nhận được -> an toàn là trên hết
    }
}

int BeltController::remaining_s(uint32_t now) const {
    if (state_ != BeltState::Alarm) return 0;
    const uint32_t elapsed = now - since_;
    if (elapsed >= countdown_ms_) return 0;
    return (int)((countdown_ms_ - elapsed + 999) / 1000);
}

BeltOutputs BeltController::outputs(uint32_t now, bool online) const {
    const uint32_t t = now - since_;
    switch (state_) {
        case BeltState::Idle:       return {false, false, online || (now / 500) % 2 == 0};
        case BeltState::Alarm:      return {t % 1000 < 100, (now / 250) % 2 == 0, false};
        case BeltState::WaitServer: return {t % 500 < 100, (now / 150) % 2 == 0, false};
        case BeltState::Sos:        return {(now / 150) % 2 == 0, true, false};
    }
    return {false, false, false};
}

const char *BeltController::state_name() const {
    switch (state_) {
        case BeltState::Idle:       return "IDLE";
        case BeltState::Alarm:      return "ALARM";
        case BeltState::WaitServer: return "WAIT_SERVER";
        case BeltState::Sos:        return "SOS";
    }
    return "?";
}

}  // namespace fall
