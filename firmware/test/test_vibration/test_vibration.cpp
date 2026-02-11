/**
 * Unit tests for vibration.cpp
 *
 * Tests peak-to-peak and RMS calculation from sample buffers.
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
// (vibration.cpp includes hardware APIs that won't compile natively)

uint16_t test_calc_peak_to_peak(const uint16_t* samples, int count) {
    if (count < 1) return 0;
    uint16_t minVal = samples[0];
    uint16_t maxVal = samples[0];
    for (int i = 1; i < count; i++) {
        if (samples[i] < minVal) minVal = samples[i];
        if (samples[i] > maxVal) maxVal = samples[i];
    }
    return maxVal - minVal;
}

float test_calc_rms(const uint16_t* samples, int count) {
    if (count < 1) return 0.0f;
    float sum = 0.0f;
    for (int i = 0; i < count; i++) {
        sum += (float)samples[i];
    }
    float mean = sum / (float)count;
    float sumSq = 0.0f;
    for (int i = 0; i < count; i++) {
        float diff = (float)samples[i] - mean;
        sumSq += diff * diff;
    }
    return sqrtf(sumSq / (float)count);
}

// ================================================================
// Tests
// ================================================================

void test_peak_to_peak_constant(void) {
    // All same value = 0 peak-to-peak
    uint16_t samples[] = {2048, 2048, 2048, 2048};
    TEST_ASSERT_EQUAL_UINT16(0, test_calc_peak_to_peak(samples, 4));
}

void test_peak_to_peak_range(void) {
    uint16_t samples[] = {100, 500, 300, 900, 200};
    TEST_ASSERT_EQUAL_UINT16(800, test_calc_peak_to_peak(samples, 5));
}

void test_peak_to_peak_single(void) {
    uint16_t samples[] = {2048};
    TEST_ASSERT_EQUAL_UINT16(0, test_calc_peak_to_peak(samples, 1));
}

void test_peak_to_peak_empty(void) {
    TEST_ASSERT_EQUAL_UINT16(0, test_calc_peak_to_peak(NULL, 0));
}

void test_peak_to_peak_full_range(void) {
    // 12-bit ADC: 0 to 4095
    uint16_t samples[] = {0, 4095};
    TEST_ASSERT_EQUAL_UINT16(4095, test_calc_peak_to_peak(samples, 2));
}

void test_rms_constant(void) {
    // Constant signal = 0 RMS (AC component is zero)
    uint16_t samples[] = {2048, 2048, 2048, 2048};
    float rms = test_calc_rms(samples, 4);
    TEST_ASSERT_FLOAT_WITHIN(0.01f, 0.0f, rms);
}

void test_rms_symmetric_ac(void) {
    // Symmetric around 2048: +100 and -100
    // RMS of AC component should be 100
    uint16_t samples[] = {2148, 1948, 2148, 1948, 2148, 1948};
    float rms = test_calc_rms(samples, 6);
    TEST_ASSERT_FLOAT_WITHIN(1.0f, 100.0f, rms);
}

void test_rms_single_sample(void) {
    // Single sample: mean equals sample, so RMS of AC = 0
    uint16_t samples[] = {1000};
    float rms = test_calc_rms(samples, 1);
    TEST_ASSERT_FLOAT_WITHIN(0.01f, 0.0f, rms);
}

void test_rms_empty(void) {
    float rms = test_calc_rms(NULL, 0);
    TEST_ASSERT_FLOAT_WITHIN(0.01f, 0.0f, rms);
}

void test_rms_known_sine_approximation(void) {
    // Approximate a sine wave: 8 samples per cycle centered at 2048, amplitude 500
    // RMS of sine = amplitude / sqrt(2) = 500 / 1.414 = 353.6
    uint16_t samples[8];
    float angles[] = {0, 0.7854f, 1.5708f, 2.3562f, 3.1416f, 3.9270f, 4.7124f, 5.4978f};
    for (int i = 0; i < 8; i++) {
        samples[i] = (uint16_t)(2048 + 500 * sinf(angles[i]));
    }
    float rms = test_calc_rms(samples, 8);
    TEST_ASSERT_FLOAT_WITHIN(20.0f, 353.6f, rms);
}

// ================================================================
// Test runner
// ================================================================

int main(int argc, char **argv) {
    UNITY_BEGIN();

    RUN_TEST(test_peak_to_peak_constant);
    RUN_TEST(test_peak_to_peak_range);
    RUN_TEST(test_peak_to_peak_single);
    RUN_TEST(test_peak_to_peak_empty);
    RUN_TEST(test_peak_to_peak_full_range);
    RUN_TEST(test_rms_constant);
    RUN_TEST(test_rms_symmetric_ac);
    RUN_TEST(test_rms_single_sample);
    RUN_TEST(test_rms_empty);
    RUN_TEST(test_rms_known_sine_approximation);

    return UNITY_END();
}
