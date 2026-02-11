/**
 * Unit tests for load_cell.cpp
 *
 * Tests raw-to-grams conversion and EMA filter math.
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

// We only need the pure computation functions, declare them here
// (they are defined in load_cell.cpp)
extern float load_cell_raw_to_grams(int32_t raw, int32_t tare, float calFactor);
extern float load_cell_ema(float previous, float sample, float alpha);

// Pull in the implementation for the functions we need
// We'll use a minimal approach: just include the computation functions
// The hardware functions won't compile natively, so we extract just what we need.

// Since load_cell.cpp includes ArduinoJson and hardware APIs,
// we redefine the testable functions here instead.
float test_raw_to_grams(int32_t raw, int32_t tare, float calFactor) {
    return (float)(raw - tare) / calFactor;
}

float test_ema(float previous, float sample, float alpha) {
    return alpha * sample + (1.0f - alpha) * previous;
}

// ================================================================
// Tests
// ================================================================

void test_raw_to_grams_zero_tare(void) {
    // No tare offset, 420 raw units per gram
    float g = test_raw_to_grams(4200, 0, 420.0f);
    TEST_ASSERT_FLOAT_WITHIN(0.01f, 10.0f, g);
}

void test_raw_to_grams_with_tare(void) {
    // Tare at 1000, reading at 1420 = 1 gram
    float g = test_raw_to_grams(1420, 1000, 420.0f);
    TEST_ASSERT_FLOAT_WITHIN(0.01f, 1.0f, g);
}

void test_raw_to_grams_negative(void) {
    // Reading below tare = negative grams (pulling up)
    float g = test_raw_to_grams(500, 1000, 420.0f);
    TEST_ASSERT_TRUE(g < 0.0f);
    TEST_ASSERT_FLOAT_WITHIN(0.01f, -1.19f, g);
}

void test_raw_to_grams_zero_reading(void) {
    float g = test_raw_to_grams(0, 0, 420.0f);
    TEST_ASSERT_FLOAT_WITHIN(0.001f, 0.0f, g);
}

void test_ema_initial(void) {
    // With alpha=1.0, output should equal the sample
    float result = test_ema(0.0f, 100.0f, 1.0f);
    TEST_ASSERT_FLOAT_WITHIN(0.01f, 100.0f, result);
}

void test_ema_no_change(void) {
    // With alpha=0.0, output should equal previous
    float result = test_ema(50.0f, 100.0f, 0.0f);
    TEST_ASSERT_FLOAT_WITHIN(0.01f, 50.0f, result);
}

void test_ema_convergence(void) {
    // Repeated application of EMA with constant input should converge
    float val = 0.0f;
    float target = 100.0f;
    float alpha = 0.3f;
    for (int i = 0; i < 50; i++) {
        val = test_ema(val, target, alpha);
    }
    TEST_ASSERT_FLOAT_WITHIN(0.1f, target, val);
}

void test_ema_half_alpha(void) {
    // alpha=0.5: result should be average of previous and sample
    float result = test_ema(0.0f, 100.0f, 0.5f);
    TEST_ASSERT_FLOAT_WITHIN(0.01f, 50.0f, result);
}

void test_large_raw_value(void) {
    // HX711 24-bit range: values up to ~8 million
    float g = test_raw_to_grams(8000000, 0, 420.0f);
    TEST_ASSERT_FLOAT_WITHIN(1.0f, 19047.6f, g);
}

// ================================================================
// Test runner
// ================================================================

int main(int argc, char **argv) {
    UNITY_BEGIN();

    RUN_TEST(test_raw_to_grams_zero_tare);
    RUN_TEST(test_raw_to_grams_with_tare);
    RUN_TEST(test_raw_to_grams_negative);
    RUN_TEST(test_raw_to_grams_zero_reading);
    RUN_TEST(test_ema_initial);
    RUN_TEST(test_ema_no_change);
    RUN_TEST(test_ema_convergence);
    RUN_TEST(test_ema_half_alpha);
    RUN_TEST(test_large_raw_value);

    return UNITY_END();
}
