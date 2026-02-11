#include "audio_capture.h"
#include "config.h"

#include <driver/i2s.h>
#include <ArduinoJson.h>

// --- Capture state ---
static bool i2sInitialized = false;
static bool capturing = false;
static bool hasResult = false;
static unsigned long captureStartMs = 0;
static unsigned long captureDurationMs = AUDIO_CAPTURE_MS;

// Running accumulators (avoid storing all samples)
static int64_t sumOfSquares = 0;
static int32_t peakAbsValue = 0;
static int32_t totalSamples = 0;

// --- Result cache ---
static float resultRmsDb = -100.0f;
static float resultPeakDb = -100.0f;
static int32_t resultSamples = 0;
static unsigned long resultDurationMs = 0;

// Temporary DMA read buffer
static int16_t dmaBuf[AUDIO_DMA_BUF_LEN];

// --- Analysis functions ---

float audio_calc_rms_db(const int16_t* samples, int count) {
    if (count < 1) return -100.0f;

    double sumSq = 0.0;
    for (int i = 0; i < count; i++) {
        double s = (double)samples[i];
        sumSq += s * s;
    }
    double rms = sqrt(sumSq / (double)count);

    // dB relative to full-scale 16-bit (32767)
    if (rms < 1.0) return -100.0f;
    return 20.0f * log10f((float)(rms / 32767.0));
}

float audio_calc_peak_db(const int16_t* samples, int count) {
    if (count < 1) return -100.0f;

    int32_t peak = 0;
    for (int i = 0; i < count; i++) {
        int32_t absVal = abs((int32_t)samples[i]);
        if (absVal > peak) peak = absVal;
    }

    if (peak < 1) return -100.0f;
    return 20.0f * log10f((float)peak / 32767.0f);
}

// --- Public API ---

void audio_init() {
    i2s_config_t i2sConfig = {};
    i2sConfig.mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_RX);
    i2sConfig.sample_rate = AUDIO_SAMPLE_RATE;
    i2sConfig.bits_per_sample = I2S_BITS_PER_SAMPLE_16BIT;
    i2sConfig.channel_format = I2S_CHANNEL_FMT_ONLY_LEFT;
    i2sConfig.communication_format = I2S_COMM_FORMAT_STAND_I2S;
    i2sConfig.intr_alloc_flags = ESP_INTR_FLAG_LEVEL1;
    i2sConfig.dma_buf_count = AUDIO_DMA_BUF_COUNT;
    i2sConfig.dma_buf_len = AUDIO_DMA_BUF_LEN;
    i2sConfig.use_apll = false;

    i2s_pin_config_t pinConfig = {};
    pinConfig.bck_io_num = I2S_SCK_PIN;
    pinConfig.ws_io_num = I2S_WS_PIN;
    pinConfig.data_in_num = I2S_SD_PIN;
    pinConfig.data_out_num = I2S_PIN_NO_CHANGE;

    esp_err_t err = i2s_driver_install(I2S_NUM_0, &i2sConfig, 0, NULL);
    if (err != ESP_OK) {
        Serial.printf("ERROR: I2S driver install failed: %d\n", err);
        return;
    }

    err = i2s_set_pin(I2S_NUM_0, &pinConfig);
    if (err != ESP_OK) {
        Serial.printf("ERROR: I2S pin config failed: %d\n", err);
        return;
    }

    i2sInitialized = true;
    Serial.println("INMP441 audio capture initialized.");
    Serial.printf("  SCK=GPIO%d, WS=GPIO%d, SD=GPIO%d, %dHz\n",
                  I2S_SCK_PIN, I2S_WS_PIN, I2S_SD_PIN, AUDIO_SAMPLE_RATE);
}

void audio_start_capture() {
    if (!i2sInitialized || capturing) return;

    // Reset accumulators
    sumOfSquares = 0;
    peakAbsValue = 0;
    totalSamples = 0;

    capturing = true;
    hasResult = false;
    captureStartMs = millis();

    Serial.println("Audio capture started...");
}

bool audio_is_capturing() {
    return capturing;
}

void audio_process() {
    if (!capturing) return;

    unsigned long now = millis();

    // Check if capture window has elapsed
    if ((now - captureStartMs) >= captureDurationMs) {
        capturing = false;
        hasResult = true;
        resultSamples = totalSamples;
        resultDurationMs = now - captureStartMs;

        // Compute final results from accumulators
        if (totalSamples > 0) {
            double rms = sqrt((double)sumOfSquares / (double)totalSamples);
            resultRmsDb = (rms < 1.0) ? -100.0f : 20.0f * log10f((float)(rms / 32767.0));
            resultPeakDb = (peakAbsValue < 1) ? -100.0f : 20.0f * log10f((float)peakAbsValue / 32767.0f);
        } else {
            resultRmsDb = -100.0f;
            resultPeakDb = -100.0f;
        }

        Serial.printf("Audio capture done: %d samples, rms=%.1f dB, peak=%.1f dB\n",
                       resultSamples, resultRmsDb, resultPeakDb);
        return;
    }

    // Non-blocking DMA read
    size_t bytesRead = 0;
    esp_err_t err = i2s_read(I2S_NUM_0, dmaBuf, sizeof(dmaBuf), &bytesRead, 0);
    if (err != ESP_OK || bytesRead == 0) {
        return;
    }

    int samplesRead = bytesRead / sizeof(int16_t);

    // Accumulate into running stats
    for (int i = 0; i < samplesRead; i++) {
        int32_t s = (int32_t)dmaBuf[i];
        sumOfSquares += s * s;
        int32_t absVal = abs(s);
        if (absVal > peakAbsValue) peakAbsValue = absVal;
    }
    totalSamples += samplesRead;
}

bool audio_has_result() {
    return hasResult;
}

float audio_get_rms_db() {
    return resultRmsDb;
}

float audio_get_peak_db() {
    return resultPeakDb;
}

String audio_build_json() {
    JsonDocument doc;
    doc["type"] = "audio";
    doc["rms_db"] = serialized(String(resultRmsDb, 1));
    doc["peak_db"] = serialized(String(resultPeakDb, 1));
    doc["samples"] = resultSamples;
    doc["duration_ms"] = resultDurationMs;

    String json;
    serializeJson(doc, json);
    return json;
}
