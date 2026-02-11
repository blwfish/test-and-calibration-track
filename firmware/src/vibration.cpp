#include "vibration.h"
#include "config.h"

#include <ArduinoJson.h>

// --- Capture state ---
static uint16_t sampleBuf[VIBRATION_MAX_SAMPLES];
static int sampleCount = 0;
static bool capturing = false;
static bool hasResult = false;
static unsigned long captureStartUs = 0;
static unsigned long lastSampleUs = 0;
static unsigned long captureDurationMs = VIBRATION_CAPTURE_MS;

// --- Result cache ---
static uint16_t resultPeakToPeak = 0;
static float resultRms = 0.0f;
static int resultSamples = 0;
static unsigned long resultDurationMs = 0;

// --- Analysis functions ---

uint16_t vibration_calc_peak_to_peak(const uint16_t* samples, int count) {
    if (count < 1) return 0;
    uint16_t minVal = samples[0];
    uint16_t maxVal = samples[0];
    for (int i = 1; i < count; i++) {
        if (samples[i] < minVal) minVal = samples[i];
        if (samples[i] > maxVal) maxVal = samples[i];
    }
    return maxVal - minVal;
}

float vibration_calc_rms(const uint16_t* samples, int count) {
    if (count < 1) return 0.0f;

    // Compute mean (DC offset from piezo bias)
    float sum = 0.0f;
    for (int i = 0; i < count; i++) {
        sum += (float)samples[i];
    }
    float mean = sum / (float)count;

    // Compute RMS of AC component (subtract mean)
    float sumSq = 0.0f;
    for (int i = 0; i < count; i++) {
        float diff = (float)samples[i] - mean;
        sumSq += diff * diff;
    }
    return sqrtf(sumSq / (float)count);
}

// --- Public API ---

void vibration_init() {
    pinMode(PIEZO_ADC_PIN, INPUT);
    // ADC1 channel 0 (GPIO 36) - no attenuation needed for low-voltage piezo
    analogReadResolution(12);

    Serial.println("Piezo vibration sensor initialized.");
    Serial.printf("  ADC pin=GPIO%d, capture=%dms\n", PIEZO_ADC_PIN, VIBRATION_CAPTURE_MS);
}

void vibration_start_capture() {
    if (capturing) return;

    sampleCount = 0;
    capturing = true;
    hasResult = false;
    captureStartUs = micros();
    lastSampleUs = captureStartUs;

    Serial.println("Vibration capture started...");
}

bool vibration_is_capturing() {
    return capturing;
}

void vibration_process() {
    if (!capturing) return;

    unsigned long now = micros();

    // Check if capture window has elapsed
    if ((now - captureStartUs) >= (captureDurationMs * 1000UL)) {
        // Capture complete — compute results
        capturing = false;
        hasResult = true;
        resultSamples = sampleCount;
        resultDurationMs = (now - captureStartUs) / 1000UL;

        if (sampleCount > 0) {
            resultPeakToPeak = vibration_calc_peak_to_peak(sampleBuf, sampleCount);
            resultRms = vibration_calc_rms(sampleBuf, sampleCount);
        } else {
            resultPeakToPeak = 0;
            resultRms = 0.0f;
        }

        Serial.printf("Vibration capture done: %d samples, p2p=%u, rms=%.1f\n",
                       resultSamples, resultPeakToPeak, resultRms);
        return;
    }

    // Sample at target rate
    if ((now - lastSampleUs) >= VIBRATION_SAMPLE_US && sampleCount < VIBRATION_MAX_SAMPLES) {
        sampleBuf[sampleCount++] = (uint16_t)analogRead(PIEZO_ADC_PIN);
        lastSampleUs = now;
    }
}

bool vibration_has_result() {
    return hasResult;
}

uint16_t vibration_get_peak_to_peak() {
    return resultPeakToPeak;
}

float vibration_get_rms() {
    return resultRms;
}

String vibration_build_json() {
    JsonDocument doc;
    doc["type"] = "vibration";
    doc["peak_to_peak"] = resultPeakToPeak;
    doc["rms"] = serialized(String(resultRms, 1));
    doc["samples"] = resultSamples;
    doc["duration_ms"] = resultDurationMs;

    String json;
    serializeJson(doc, json);
    return json;
}
