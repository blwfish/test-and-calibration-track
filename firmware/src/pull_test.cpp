#include "pull_test.h"
#include "config.h"
#include "load_cell.h"
#include "vibration.h"
#include "audio_capture.h"
#include "mqtt_manager.h"
#include "track_switch.h"

#include <ArduinoJson.h>

// --- State machine ---

enum PullTestState {
    PT_IDLE,
    PT_TARING,
    PT_SETTLING,
    PT_VIB_CAPTURE,    // Vibration capture in progress
    PT_AUDIO_CAPTURE,  // Audio capture in progress
    PT_READING,
    PT_DONE
};

struct PullTestEntry {
    int speedStep;
    float throttlePct;
    float pullGrams;
    uint16_t vibPeakToPeak;
    float vibRms;
    float audioRmsDb;
    float audioPeakDb;
};

// Configuration
static int stepInc = 5;
static unsigned long settleMs = 3000;

// State
static PullTestState state = PT_IDLE;
static unsigned long stateEnteredMs = 0;
static int currentStep = 0;          // Current DCC speed step being tested
static int currentStepNum = 0;       // 1-based index into sequence
static int totalSteps = 0;
static bool testComplete = false;

// Results
static const int MAX_ENTRIES = 128;
static PullTestEntry entries[MAX_ENTRIES];
static int entryCount = 0;
static float peakGrams = 0.0f;
static int peakStep = 0;

// --- Helpers ---

static void setSpeed(int step) {
    float throttle = (float)step / 126.0f;
    char buf[16];
    snprintf(buf, sizeof(buf), "%.3f", throttle);
    mqtt_publish_throttle("speed", String(buf));
}

static void stopLoco() {
    mqtt_publish_throttle("stop", "");
}

// Compute the next speed step in the sequence.
// Returns -1 if the sequence is complete.
static int nextStep(int current) {
    if (current == 0) {
        // First real step
        return stepInc;
    }
    int next = current + stepInc;
    if (next > 126) {
        // Already did (or passed) 126
        if (current >= 126) return -1;
        return 126;  // Always end at 126
    }
    return next;
}

// Count total steps in the sequence
static int countSteps() {
    int count = 0;
    int s = 0;
    while (true) {
        s = (s == 0) ? stepInc : s + stepInc;
        if (s > 126) {
            // Check if we need one more for 126
            int prev = s - stepInc;
            if (prev < 126) count++;  // for step 126
            break;
        }
        count++;
        if (s == 126) break;
    }
    return count;
}

// --- Public API ---

void pull_test_start(int step_inc, unsigned long settle_ms) {
    if (state != PT_IDLE) return;
    if (!load_cell_is_ready()) {
        Serial.println("Pull test: load cell not ready");
        return;
    }
    if (!mqtt_get_throttle_acquired()) {
        Serial.println("Pull test: throttle not acquired");
        return;
    }
    if (!track_switch_allow_dcc_test()) {
        Serial.println("Pull test: blocked by track switch (not in DCC programming mode)");
        return;
    }

    stepInc = step_inc > 0 ? step_inc : 5;
    settleMs = settle_ms > 0 ? settle_ms : 3000;

    // Reset results
    entryCount = 0;
    peakGrams = 0.0f;
    peakStep = 0;
    currentStep = 0;
    currentStepNum = 0;
    testComplete = false;

    totalSteps = countSteps();

    // Ensure loco is stopped before taring
    stopLoco();

    state = PT_TARING;
    stateEnteredMs = millis();

    Serial.printf("Pull test started: inc=%d, settle=%lums, %d steps\n",
                  stepInc, settleMs, totalSteps);
}

void pull_test_abort() {
    if (state == PT_IDLE || state == PT_DONE) return;

    stopLoco();
    testComplete = false;
    state = PT_DONE;

    Serial.printf("Pull test aborted at step %d (%d entries collected)\n",
                  currentStep, entryCount);
}

void pull_test_process() {
    if (state == PT_IDLE || state == PT_DONE) return;

    unsigned long now = millis();
    unsigned long elapsed = now - stateEnteredMs;

    switch (state) {
        case PT_TARING:
            // Wait 500ms at speed 0, then tare
            if (elapsed >= 500) {
                load_cell_tare();
                Serial.println("Pull test: tared at speed 0");

                // Advance to first step
                currentStep = nextStep(0);
                if (currentStep < 0) {
                    // Shouldn't happen, but handle it
                    state = PT_DONE;
                    testComplete = true;
                    return;
                }
                currentStepNum = 1;

                setSpeed(currentStep);
                state = PT_SETTLING;
                stateEnteredMs = now;
            }
            break;

        case PT_SETTLING:
            if (elapsed >= settleMs) {
                // Start vibration capture before reading
                vibration_start_capture();
                state = PT_VIB_CAPTURE;
                stateEnteredMs = now;
            }
            break;

        case PT_VIB_CAPTURE:
            // Wait for vibration capture to complete (driven by vibration_process() in main loop)
            if (!vibration_is_capturing()) {
                // Start audio capture next
                audio_start_capture();
                state = PT_AUDIO_CAPTURE;
                stateEnteredMs = now;
            }
            break;

        case PT_AUDIO_CAPTURE:
            // Wait for audio capture to complete (driven by audio_process() in main loop)
            if (!audio_is_capturing()) {
                state = PT_READING;
                stateEnteredMs = now;
            }
            break;

        case PT_READING: {
            // Read load cell, vibration, and audio results
            float grams = load_cell_get_grams();
            float pct = (float)currentStep / 126.0f * 100.0f;

            // Get vibration results from the just-completed capture
            uint16_t vibPP = vibration_get_peak_to_peak();
            float vibRms = vibration_get_rms();

            // Get audio results from the just-completed capture
            float audRmsDb = audio_get_rms_db();
            float audPeakDb = audio_get_peak_db();

            // Store entry
            if (entryCount < MAX_ENTRIES) {
                entries[entryCount].speedStep = currentStep;
                entries[entryCount].throttlePct = pct;
                entries[entryCount].pullGrams = grams;
                entries[entryCount].vibPeakToPeak = vibPP;
                entries[entryCount].vibRms = vibRms;
                entries[entryCount].audioRmsDb = audRmsDb;
                entries[entryCount].audioPeakDb = audPeakDb;
                entryCount++;
            }

            // Track peak
            if (grams > peakGrams) {
                peakGrams = grams;
                peakStep = currentStep;
            }

            Serial.printf("Pull test: step %d (%.1f%%) = %.1fg, vib p2p=%u rms=%.1f, audio rms=%.1fdB peak=%.1fdB\n",
                          currentStep, pct, grams, vibPP, vibRms, audRmsDb, audPeakDb);

            // Advance to next step
            int next = nextStep(currentStep);
            if (next < 0) {
                // Sequence complete
                stopLoco();
                testComplete = true;
                state = PT_DONE;
                Serial.printf("Pull test complete: %d entries, peak=%.1fg at step %d\n",
                              entryCount, peakGrams, peakStep);
            } else {
                currentStep = next;
                currentStepNum++;
                setSpeed(currentStep);
                state = PT_SETTLING;
                stateEnteredMs = millis();
            }
            break;
        }

        default:
            break;
    }
}

bool pull_test_is_running() {
    return state != PT_IDLE && state != PT_DONE;
}

int pull_test_current_step() {
    return currentStep;
}

int pull_test_total_steps() {
    return totalSteps;
}

int pull_test_current_step_num() {
    return currentStepNum;
}

String pull_test_build_json() {
    JsonDocument doc;
    doc["type"] = "pull_test";
    doc["complete"] = testComplete;
    doc["step_inc"] = stepInc;
    doc["settle_ms"] = settleMs;
    doc["peak_grams"] = serialized(String(peakGrams, 1));
    doc["peak_step"] = peakStep;

    JsonArray arr = doc["entries"].to<JsonArray>();
    for (int i = 0; i < entryCount; i++) {
        JsonObject e = arr.add<JsonObject>();
        e["step"] = entries[i].speedStep;
        e["pct"] = serialized(String(entries[i].throttlePct, 1));
        e["grams"] = serialized(String(entries[i].pullGrams, 1));
        e["vib_pp"] = entries[i].vibPeakToPeak;
        e["vib_rms"] = serialized(String(entries[i].vibRms, 1));
        e["aud_rms"] = serialized(String(entries[i].audioRmsDb, 1));
        e["aud_peak"] = serialized(String(entries[i].audioPeakDb, 1));
    }

    String json;
    serializeJson(doc, json);
    return json;
}

String pull_test_build_progress_json() {
    JsonDocument doc;
    doc["type"] = "pull_progress";
    doc["step"] = currentStep;
    doc["total_steps"] = totalSteps;
    doc["current_step_num"] = currentStepNum;
    doc["grams"] = serialized(String(load_cell_get_grams(), 1));
    doc["peak_grams"] = serialized(String(peakGrams, 1));

    // Include latest vibration reading if available
    if (vibration_has_result()) {
        doc["vib_rms"] = serialized(String(vibration_get_rms(), 1));
    }

    // Include latest audio reading if available
    if (audio_has_result()) {
        doc["aud_rms"] = serialized(String(audio_get_rms_db(), 1));
    }

    String json;
    serializeJson(doc, json);
    return json;
}
