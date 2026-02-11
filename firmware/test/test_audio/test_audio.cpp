/**
 * Unit tests for audio_capture.cpp
 *
 * Tests RMS-to-dB and peak-to-dB conversion math.
 * Runs natively on desktop (no hardware needed).
 *
 * Run with: pio test -e native
 */

#include <unity.h>
#include "Arduino.h"   // stub
#include "config.h"

// --- Stubs ---
FakeSerial Serial;
uint32_t millis() { return 0; }
uint32_t micros() { return 0; }

// Redefine the pure analysis functions here for native testing
// (audio_capture.cpp includes I2S driver that won't compile natively)

float test_calc_rms_db(const int16_t* samples, int count) {
    if (count < 1) return -100.0f;
    double sumSq = 0.0;
    for (int i = 0; i < count; i++) {
        double s = (double)samples[i];
        sumSq += s * s;
    }
    double rms = sqrt(sumSq / (double)count);
    if (rms < 1.0) return -100.0f;
    return 20.0f * log10f((float)(rms / 32767.0));
}

float test_calc_peak_db(const int16_t* samples, int count) {
    if (count < 1) return -100.0f;
    int32_t peak = 0;
    for (int i = 0; i < count; i++) {
        int32_t absVal = abs((int32_t)samples[i]);
        if (absVal > peak) peak = absVal;
    }
    if (peak < 1) return -100.0f;
    return 20.0f * log10f((float)peak / 32767.0f);
}

// ================================================================
// Tests
// ================================================================

void test_rms_db_full_scale(void) {
    // Full-scale sine peak at 32767: RMS ~= 32767/sqrt(2), dB ~= -3.01
    // Use a simpler case: constant at 32767 => RMS=32767 => 0 dB
    int16_t samples[] = {32767, 32767, 32767, 32767};
    float db = test_calc_rms_db(samples, 4);
    TEST_ASSERT_FLOAT_WITHIN(0.1f, 0.0f, db);
}

void test_rms_db_half_scale(void) {
    // Constant at 16384 (half of full scale)
    // dB = 20 * log10(16384/32767) = 20 * log10(0.5) = -6.02
    int16_t samples[] = {16384, 16384, 16384, 16384};
    float db = test_calc_rms_db(samples, 4);
    TEST_ASSERT_FLOAT_WITHIN(0.5f, -6.0f, db);
}

void test_rms_db_silence(void) {
    // All zeros: should return -100 (floor)
    int16_t samples[] = {0, 0, 0, 0};
    float db = test_calc_rms_db(samples, 4);
    TEST_ASSERT_FLOAT_WITHIN(0.1f, -100.0f, db);
}

void test_rms_db_empty(void) {
    float db = test_calc_rms_db(NULL, 0);
    TEST_ASSERT_FLOAT_WITHIN(0.1f, -100.0f, db);
}

void test_rms_db_negative_samples(void) {
    // Negative values should contribute equally (squared)
    int16_t samples[] = {-32767, -32767, -32767, -32767};
    float db = test_calc_rms_db(samples, 4);
    TEST_ASSERT_FLOAT_WITHIN(0.1f, 0.0f, db);
}

void test_peak_db_full_scale(void) {
    // Peak at 32767: 0 dBFS
    int16_t samples[] = {0, 100, 32767, -100};
    float db = test_calc_peak_db(samples, 4);
    TEST_ASSERT_FLOAT_WITHIN(0.1f, 0.0f, db);
}

void test_peak_db_negative_peak(void) {
    // Peak at -32767 (absolute value): 0 dBFS
    int16_t samples[] = {0, 100, -32767, -100};
    float db = test_calc_peak_db(samples, 4);
    TEST_ASSERT_FLOAT_WITHIN(0.1f, 0.0f, db);
}

void test_peak_db_half(void) {
    // Peak at 16384: -6 dBFS
    int16_t samples[] = {0, 16384, 100};
    float db = test_calc_peak_db(samples, 3);
    TEST_ASSERT_FLOAT_WITHIN(0.5f, -6.0f, db);
}

void test_peak_db_silence(void) {
    int16_t samples[] = {0, 0, 0};
    float db = test_calc_peak_db(samples, 3);
    TEST_ASSERT_FLOAT_WITHIN(0.1f, -100.0f, db);
}

void test_peak_db_empty(void) {
    float db = test_calc_peak_db(NULL, 0);
    TEST_ASSERT_FLOAT_WITHIN(0.1f, -100.0f, db);
}

void test_rms_db_low_level(void) {
    // Very quiet: amplitude ~100 => -50.3 dBFS
    int16_t samples[] = {100, -100, 100, -100};
    float db = test_calc_rms_db(samples, 4);
    TEST_ASSERT_FLOAT_WITHIN(1.0f, -50.3f, db);
}

// ================================================================
// Test runner
// ================================================================

int main(int argc, char **argv) {
    UNITY_BEGIN();

    RUN_TEST(test_rms_db_full_scale);
    RUN_TEST(test_rms_db_half_scale);
    RUN_TEST(test_rms_db_silence);
    RUN_TEST(test_rms_db_empty);
    RUN_TEST(test_rms_db_negative_samples);
    RUN_TEST(test_peak_db_full_scale);
    RUN_TEST(test_peak_db_negative_peak);
    RUN_TEST(test_peak_db_half);
    RUN_TEST(test_peak_db_silence);
    RUN_TEST(test_peak_db_empty);
    RUN_TEST(test_rms_db_low_level);

    return UNITY_END();
}
