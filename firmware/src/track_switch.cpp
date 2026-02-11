#include "track_switch.h"
#include "config.h"

#include <Preferences.h>
#include <ArduinoJson.h>

// --- State ---

static Preferences prefs;
static bool switchesEnabled = false;   // Persisted in NVS
static TrackMode currentMode = TRACK_MODE_UNKNOWN;
static TrackMode lastReportedMode = TRACK_MODE_UNKNOWN;
static bool modeChanged = false;

// Debounce state
static bool lastSw1Raw = false;
static bool lastSw2Raw = false;
static unsigned long sw1StableMs = 0;
static unsigned long sw2StableMs = 0;
static bool sw1Debounced = false;      // true = programming track
static bool sw2Debounced = false;      // true = DC mode

// --- Helpers ---

static TrackMode deriveMode(bool sw1Prog, bool sw2Dc) {
    if (!sw1Prog) {
        return TRACK_MODE_LAYOUT;       // SW1 = layout bus
    }
    if (sw2Dc) {
        return TRACK_MODE_PROG_DC;      // SW1 = prog, SW2 = DC
    }
    return TRACK_MODE_PROG_DCC;         // SW1 = prog, SW2 = DCC
}

// --- Public API ---

void track_switch_init() {
    prefs.begin(TRACK_SWITCH_NVS_NAMESPACE, true);
    switchesEnabled = prefs.getBool("enabled", false);
    prefs.end();

    if (switchesEnabled) {
        // SW pins: HIGH when switch selects programming track / DC
        // Using INPUT_PULLDOWN: switch connects pin to 3.3V when active
        pinMode(TRACK_SW1_PIN, INPUT_PULLDOWN);
        pinMode(TRACK_SW2_PIN, INPUT_PULLDOWN);

        // Read initial state
        bool sw1 = digitalRead(TRACK_SW1_PIN);
        bool sw2 = digitalRead(TRACK_SW2_PIN);
        sw1Debounced = sw1;
        sw2Debounced = sw2;
        lastSw1Raw = sw1;
        lastSw2Raw = sw2;
        sw1StableMs = millis();
        sw2StableMs = millis();

        currentMode = deriveMode(sw1, sw2);
        lastReportedMode = currentMode;

        Serial.printf("Track switch: enabled, SW1=%s SW2=%s → %s\n",
            sw1 ? "PROG" : "LAYOUT", sw2 ? "DC" : "DCC",
            track_switch_mode_name(currentMode));
    } else {
        currentMode = TRACK_MODE_UNKNOWN;
        Serial.println("Track switch: not enabled (bypassed)");
    }
}

void track_switch_process() {
    if (!switchesEnabled) return;

    unsigned long now = millis();

    // Read raw pins
    bool sw1Raw = digitalRead(TRACK_SW1_PIN);
    bool sw2Raw = digitalRead(TRACK_SW2_PIN);

    // Debounce SW1
    if (sw1Raw != lastSw1Raw) {
        lastSw1Raw = sw1Raw;
        sw1StableMs = now;
    } else if (sw1Raw != sw1Debounced && (now - sw1StableMs) >= TRACK_SWITCH_DEBOUNCE_MS) {
        sw1Debounced = sw1Raw;
    }

    // Debounce SW2
    if (sw2Raw != lastSw2Raw) {
        lastSw2Raw = sw2Raw;
        sw2StableMs = now;
    } else if (sw2Raw != sw2Debounced && (now - sw2StableMs) >= TRACK_SWITCH_DEBOUNCE_MS) {
        sw2Debounced = sw2Raw;
    }

    // Derive mode
    TrackMode newMode = deriveMode(sw1Debounced, sw2Debounced);
    if (newMode != currentMode) {
        currentMode = newMode;
        modeChanged = true;
        Serial.printf("Track switch: mode changed → %s\n",
            track_switch_mode_name(currentMode));
    }
}

TrackMode track_switch_get_mode() {
    return currentMode;
}

const char* track_switch_mode_name(TrackMode mode) {
    switch (mode) {
        case TRACK_MODE_LAYOUT:    return "layout";
        case TRACK_MODE_PROG_DCC:  return "prog_dcc";
        case TRACK_MODE_PROG_DC:   return "prog_dc";
        default:                   return "unknown";
    }
}

bool track_switch_enabled() {
    return switchesEnabled;
}

void track_switch_set_enabled(bool enabled) {
    switchesEnabled = enabled;
    prefs.begin(TRACK_SWITCH_NVS_NAMESPACE, false);
    prefs.putBool("enabled", enabled);
    prefs.end();

    if (enabled) {
        pinMode(TRACK_SW1_PIN, INPUT_PULLDOWN);
        pinMode(TRACK_SW2_PIN, INPUT_PULLDOWN);
        bool sw1 = digitalRead(TRACK_SW1_PIN);
        bool sw2 = digitalRead(TRACK_SW2_PIN);
        sw1Debounced = sw1;
        sw2Debounced = sw2;
        lastSw1Raw = sw1;
        lastSw2Raw = sw2;
        sw1StableMs = millis();
        sw2StableMs = millis();
        currentMode = deriveMode(sw1, sw2);
    } else {
        currentMode = TRACK_MODE_UNKNOWN;
    }
    modeChanged = true;

    Serial.printf("Track switch: %s → %s\n",
        enabled ? "enabled" : "disabled",
        track_switch_mode_name(currentMode));
}

bool track_switch_allow_dcc_test() {
    // If switches not installed, bypass interlock
    if (!switchesEnabled) return true;
    return currentMode == TRACK_MODE_PROG_DCC;
}

bool track_switch_allow_operation() {
    // If switches not installed, bypass interlock
    if (!switchesEnabled) return true;
    return currentMode != TRACK_MODE_LAYOUT;
}

bool track_switch_changed() {
    if (modeChanged) {
        modeChanged = false;
        return true;
    }
    return false;
}

String track_switch_build_json() {
    JsonDocument doc;
    doc["type"] = "track_mode";
    doc["enabled"] = switchesEnabled;
    doc["mode"] = track_switch_mode_name(currentMode);
    doc["allow_dcc_test"] = track_switch_allow_dcc_test();
    doc["allow_operation"] = track_switch_allow_operation();

    String json;
    serializeJson(doc, json);
    return json;
}
