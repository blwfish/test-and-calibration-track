#include "load_cell.h"
#include "config.h"

#include <ArduinoJson.h>

// --- HX711 state ---
static int32_t rawValue = 0;
static float smoothedRaw = 0.0f;
static int32_t tareOffset = 0;
static bool tared = false;
static bool ready = false;
static unsigned long lastReadMs = 0;

// --- HX711 bit-bang protocol ---

// Read 24-bit signed value from HX711.
// Returns true if data was available and read successfully.
static bool hx711_read_raw(int32_t& value) {
    // DOUT LOW means data is ready
    if (digitalRead(HX711_DOUT_PIN) == HIGH) {
        return false;  // Not ready
    }

    // Clock out 24 data bits (MSB first)
    int32_t raw = 0;
    for (int i = 0; i < 24; i++) {
        digitalWrite(HX711_SCK_PIN, HIGH);
        delayMicroseconds(1);
        raw = (raw << 1) | digitalRead(HX711_DOUT_PIN);
        digitalWrite(HX711_SCK_PIN, LOW);
        delayMicroseconds(1);
    }

    // 25th pulse: set gain to 128 for next reading (Channel A)
    digitalWrite(HX711_SCK_PIN, HIGH);
    delayMicroseconds(1);
    digitalWrite(HX711_SCK_PIN, LOW);
    delayMicroseconds(1);

    // Sign-extend 24-bit to 32-bit
    if (raw & 0x800000) {
        raw |= 0xFF000000;
    }

    value = raw;
    return true;
}

// Power down HX711 by holding SCK HIGH for >60us
// (not used currently, but available if needed)
// static void hx711_power_down() {
//     digitalWrite(HX711_SCK_PIN, HIGH);
//     delayMicroseconds(100);
// }

// --- Conversion ---

// Convert raw ADC value (after tare) to grams.
float load_cell_raw_to_grams(int32_t raw, int32_t tare, float calFactor) {
    return (float)(raw - tare) / calFactor;
}

// Apply EMA filter: new = alpha * sample + (1 - alpha) * previous
float load_cell_ema(float previous, float sample, float alpha) {
    return alpha * sample + (1.0f - alpha) * previous;
}

// --- Public API ---

void load_cell_init() {
    pinMode(HX711_DOUT_PIN, INPUT);
    pinMode(HX711_SCK_PIN, OUTPUT);
    digitalWrite(HX711_SCK_PIN, LOW);

    Serial.println("HX711 load cell initialized.");
    Serial.printf("  DOUT=GPIO%d, SCK=GPIO%d\n", HX711_DOUT_PIN, HX711_SCK_PIN);
}

void load_cell_process() {
    unsigned long now = millis();
    if (now - lastReadMs < LOAD_CELL_SAMPLE_MS) {
        return;
    }
    lastReadMs = now;

    int32_t raw;
    if (!hx711_read_raw(raw)) {
        return;  // HX711 not ready yet
    }

    rawValue = raw;

    if (!ready) {
        // First reading: initialize EMA
        smoothedRaw = (float)raw;
        ready = true;
    } else {
        smoothedRaw = load_cell_ema(smoothedRaw, (float)raw, LOAD_CELL_EMA_ALPHA);
    }
}

void load_cell_tare() {
    if (ready) {
        tareOffset = (int32_t)smoothedRaw;
        tared = true;
        Serial.printf("Load cell tared at raw=%d\n", tareOffset);
    } else {
        Serial.println("Load cell not ready — cannot tare yet");
    }
}

float load_cell_get_grams() {
    return load_cell_raw_to_grams((int32_t)smoothedRaw, tareOffset, LOAD_CELL_CAL_FACTOR);
}

int32_t load_cell_get_raw() {
    return rawValue;
}

bool load_cell_is_ready() {
    return ready;
}

bool load_cell_is_tared() {
    return tared;
}

String load_cell_build_json() {
    JsonDocument doc;
    doc["type"] = "load";
    doc["grams"] = serialized(String(load_cell_get_grams(), 1));
    doc["raw"] = rawValue;
    doc["tared"] = tared;

    String json;
    serializeJson(doc, json);
    return json;
}
