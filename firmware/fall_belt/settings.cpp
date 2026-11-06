#include "settings.h"

#include <Preferences.h>
#include <WiFi.h>
#include <string.h>

#include "config.h"

static const char *kNamespace = "fallbelt";

void settings_load(Settings &s) {
    const int order[3] = AXIS_ORDER, sign[3] = AXIS_SIGN;
    Preferences p;
    p.begin(kNamespace, true);
    strlcpy(s.mqtt_host, p.getString("mqtt_host", MQTT_HOST).c_str(), sizeof(s.mqtt_host));
    s.mqtt_port = p.getUShort("mqtt_port", MQTT_PORT);
    strlcpy(s.belt_id, p.getString("belt_id", BELT_ID).c_str(), sizeof(s.belt_id));
    s.calibrated = p.getBool("calibrated", false);
    if (!s.calibrated || p.getBytes("axis", &s.axis, sizeof(s.axis)) != sizeof(s.axis)) {
        s.calibrated = false;
        s.axis = fall::axis_map_from_config(order, sign);
    }
    p.end();
}

void settings_save(const Settings &s) {
    Preferences p;
    p.begin(kNamespace, false);
    p.putString("mqtt_host", s.mqtt_host);
    p.putUShort("mqtt_port", s.mqtt_port);
    p.putString("belt_id", s.belt_id);
    p.putBool("calibrated", s.calibrated);
    p.putBytes("axis", &s.axis, sizeof(s.axis));
    p.end();
}

void settings_factory_reset() {
    Preferences p;
    p.begin(kNamespace, false);
    p.clear();
    p.end();
    WiFi.disconnect(true, true);  // xóa luôn WiFi đã lưu
}
