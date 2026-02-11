/**
 * Unit tests for speed_calc.cpp
 *
 * Tests speed calculation from sensor timestamps.
 * Runs natively on desktop (no hardware needed).
 *
 * Run with: pio test -e native
 */

#include <unity.h>
#include "Arduino.h"   // stub
#include "config.h"
#include "sensor_array.h"
#include "speed_calc.h"

// Pull in the implementation directly for native builds
// (PlatformIO native test runner doesn't compile src/ by default)
#include "../../src/speed_calc.cpp"

// --- Stubs needed by the compiled units ---
FakeSerial Serial;
static uint32_t fake_millis = 0;
static uint32_t fake_micros = 0;
uint32_t millis() { return fake_millis; }
uint32_t micros() { return fake_micros; }

// --- Helpers ---

// Expected conversion constant: HO scale 87.1, mm/s to mph
static const float EXPECTED_MMS_TO_MPH = HO_SCALE_FACTOR * 3600.0f / (1000000.0f * 1.609344f);

/**
 * Build a RunResult for a uniform-speed A→B pass.
 *
 * All 4 sensors triggered at constant velocity.
 *  speed_mm_s: model speed in mm/s
 */
static RunResult makeUniformRun_AtoB(float speed_mm_s) {
    RunResult r;
    memset(&r, 0, sizeof(r));
    r.direction = DIR_A_TO_B;
    r.sensorsTriggered = NUM_SENSORS;

    // Time between sensors at this speed
    float dt_us = (SENSOR_SPACING_MM / speed_mm_s) * 1000000.0f;

    uint32_t t0 = 1000000;  // Start at 1 second (arbitrary)
    for (int i = 0; i < NUM_SENSORS; i++) {
        r.triggered[i] = true;
        r.timestamps[i] = t0 + (uint32_t)(i * dt_us);
    }
    r.runDurationUs = r.timestamps[NUM_SENSORS - 1] - r.timestamps[0];
    return r;
}

/**
 * Build a RunResult for a uniform-speed B→A pass.
 */
static RunResult makeUniformRun_BtoA(float speed_mm_s) {
    RunResult r;
    memset(&r, 0, sizeof(r));
    r.direction = DIR_B_TO_A;
    r.sensorsTriggered = NUM_SENSORS;

    float dt_us = (SENSOR_SPACING_MM / speed_mm_s) * 1000000.0f;

    uint32_t t0 = 1000000;
    // B→A: sensor N-1 fires first, sensor 0 fires last
    for (int i = 0; i < NUM_SENSORS; i++) {
        r.triggered[i] = true;
        r.timestamps[i] = t0 + (uint32_t)((NUM_SENSORS - 1 - i) * dt_us);
    }
    r.runDurationUs = r.timestamps[0] - r.timestamps[NUM_SENSORS - 1];
    return r;
}


// ================================================================
// Tests
// ================================================================

void test_uniform_speed_A_to_B(void) {
    // 500 mm/s model speed, A→B direction
    float speed_mms = 500.0f;
    RunResult run = makeUniformRun_AtoB(speed_mms);

    SpeedResult result;
    TEST_ASSERT_TRUE(speed_calculate(run, result));

    // Should have NUM_SENSORS - 1 intervals
    TEST_ASSERT_EQUAL_INT(NUM_SENSORS - 1, result.intervalCount);

    // Each interval should be the same speed
    float expected_mph = speed_mms * EXPECTED_MMS_TO_MPH;
    for (int i = 0; i < result.intervalCount; i++) {
        TEST_ASSERT_FLOAT_WITHIN(0.5f, expected_mph, result.scaleSpeedsMph[i]);
    }

    // Average should match
    TEST_ASSERT_FLOAT_WITHIN(0.5f, expected_mph, result.avgScaleSpeedMph);
}


void test_uniform_speed_B_to_A(void) {
    // 500 mm/s model speed, B→A direction
    float speed_mms = 500.0f;
    RunResult run = makeUniformRun_BtoA(speed_mms);

    SpeedResult result;
    TEST_ASSERT_TRUE(speed_calculate(run, result));

    TEST_ASSERT_EQUAL_INT(NUM_SENSORS - 1, result.intervalCount);

    // Speed should be the same regardless of direction
    float expected_mph = speed_mms * EXPECTED_MMS_TO_MPH;
    TEST_ASSERT_FLOAT_WITHIN(0.5f, expected_mph, result.avgScaleSpeedMph);
}


void test_same_speed_both_directions(void) {
    // A→B and B→A at the same model speed should give the same result
    float speed_mms = 300.0f;

    RunResult run_ab = makeUniformRun_AtoB(speed_mms);
    RunResult run_ba = makeUniformRun_BtoA(speed_mms);

    SpeedResult res_ab, res_ba;
    speed_calculate(run_ab, res_ab);
    speed_calculate(run_ba, res_ba);

    TEST_ASSERT_FLOAT_WITHIN(0.1f, res_ab.avgScaleSpeedMph, res_ba.avgScaleSpeedMph);
    TEST_ASSERT_EQUAL_INT(res_ab.intervalCount, res_ba.intervalCount);
}


void test_fewer_than_two_sensors_fails(void) {
    // Only 1 sensor triggered — can't compute speed
    RunResult run;
    memset(&run, 0, sizeof(run));
    run.sensorsTriggered = 1;
    run.triggered[0] = true;
    run.timestamps[0] = 1000000;
    run.direction = DIR_A_TO_B;

    SpeedResult result;
    TEST_ASSERT_FALSE(speed_calculate(run, result));
    TEST_ASSERT_EQUAL_INT(0, result.intervalCount);
}


void test_zero_sensors_fails(void) {
    RunResult run;
    memset(&run, 0, sizeof(run));
    run.sensorsTriggered = 0;
    run.direction = DIR_UNKNOWN;

    SpeedResult result;
    TEST_ASSERT_FALSE(speed_calculate(run, result));
}


void test_two_sensors_only(void) {
    // Only sensors 0 and 1 triggered (partial pass)
    RunResult run;
    memset(&run, 0, sizeof(run));
    run.direction = DIR_A_TO_B;
    run.sensorsTriggered = 2;
    run.triggered[0] = true;
    run.triggered[1] = true;
    run.timestamps[0] = 1000000;
    run.timestamps[1] = 1200000;  // 200ms = 200000us between sensors
    run.runDurationUs = 200000;

    SpeedResult result;
    TEST_ASSERT_TRUE(speed_calculate(run, result));
    TEST_ASSERT_EQUAL_INT(1, result.intervalCount);

    // 100mm / 0.2s = 500 mm/s
    TEST_ASSERT_FLOAT_WITHIN(1.0f, 500.0f, result.intervalSpeedsMmS[0]);
}


void test_gap_in_sensors(void) {
    // Sensors 0, 1, 3 triggered (sensor 2 missed)
    RunResult run;
    memset(&run, 0, sizeof(run));
    run.direction = DIR_A_TO_B;
    run.sensorsTriggered = 3;
    run.triggered[0] = true;
    run.triggered[1] = true;
    run.triggered[2] = false;  // missed!
    run.triggered[3] = true;
    run.timestamps[0] = 1000000;
    run.timestamps[1] = 1200000;
    run.timestamps[2] = 0;
    run.timestamps[3] = 1600000;
    run.runDurationUs = 600000;

    SpeedResult result;
    TEST_ASSERT_TRUE(speed_calculate(run, result));

    // Should have 1 interval (0→1), gap skipped, no 2→3
    // Actually: 0→1 valid, 1→2 skipped (2 not triggered), 2→3 skipped
    TEST_ASSERT_EQUAL_INT(1, result.intervalCount);
}


void test_slow_speed(void) {
    // Very slow: 50 mm/s model (about 10 scale mph HO)
    float speed_mms = 50.0f;
    RunResult run = makeUniformRun_AtoB(speed_mms);

    SpeedResult result;
    TEST_ASSERT_TRUE(speed_calculate(run, result));

    float expected_mph = speed_mms * EXPECTED_MMS_TO_MPH;
    TEST_ASSERT_FLOAT_WITHIN(0.5f, expected_mph, result.avgScaleSpeedMph);
    // Sanity: should be around 9.7 scale mph
    TEST_ASSERT_TRUE(result.avgScaleSpeedMph > 5.0f);
    TEST_ASSERT_TRUE(result.avgScaleSpeedMph < 15.0f);
}


void test_fast_speed(void) {
    // Fast: 2000 mm/s model (about 390 scale mph HO — unrealistic but tests math)
    float speed_mms = 2000.0f;
    RunResult run = makeUniformRun_AtoB(speed_mms);

    SpeedResult result;
    TEST_ASSERT_TRUE(speed_calculate(run, result));

    float expected_mph = speed_mms * EXPECTED_MMS_TO_MPH;
    TEST_ASSERT_FLOAT_WITHIN(2.0f, expected_mph, result.avgScaleSpeedMph);
}


void test_interval_times_correct(void) {
    // Check that interval times in microseconds are correct
    RunResult run;
    memset(&run, 0, sizeof(run));
    run.direction = DIR_A_TO_B;
    run.sensorsTriggered = 4;
    run.triggered[0] = true;  run.timestamps[0] = 1000000;
    run.triggered[1] = true;  run.timestamps[1] = 1100000;  // 100ms
    run.triggered[2] = true;  run.timestamps[2] = 1250000;  // 150ms
    run.triggered[3] = true;  run.timestamps[3] = 1350000;  // 100ms
    run.runDurationUs = 350000;

    SpeedResult result;
    TEST_ASSERT_TRUE(speed_calculate(run, result));
    TEST_ASSERT_EQUAL_INT(3, result.intervalCount);

    TEST_ASSERT_EQUAL_UINT32(100000, result.intervalsUs[0]);
    TEST_ASSERT_EQUAL_UINT32(150000, result.intervalsUs[1]);
    TEST_ASSERT_EQUAL_UINT32(100000, result.intervalsUs[2]);
}


void test_varying_speeds(void) {
    // Non-uniform speed: accelerating
    RunResult run;
    memset(&run, 0, sizeof(run));
    run.direction = DIR_A_TO_B;
    run.sensorsTriggered = 4;
    run.triggered[0] = true;  run.timestamps[0] = 1000000;
    run.triggered[1] = true;  run.timestamps[1] = 1200000;  // 200ms -> 500 mm/s
    run.triggered[2] = true;  run.timestamps[2] = 1300000;  // 100ms -> 1000 mm/s
    run.triggered[3] = true;  run.timestamps[3] = 1350000;  //  50ms -> 2000 mm/s
    run.runDurationUs = 350000;

    SpeedResult result;
    TEST_ASSERT_TRUE(speed_calculate(run, result));
    TEST_ASSERT_EQUAL_INT(3, result.intervalCount);

    // Each interval should show increasing speed
    TEST_ASSERT_TRUE(result.intervalSpeedsMmS[0] < result.intervalSpeedsMmS[1]);
    TEST_ASSERT_TRUE(result.intervalSpeedsMmS[1] < result.intervalSpeedsMmS[2]);

    // Check individual interval speeds
    TEST_ASSERT_FLOAT_WITHIN(1.0f, 500.0f, result.intervalSpeedsMmS[0]);
    TEST_ASSERT_FLOAT_WITHIN(1.0f, 1000.0f, result.intervalSpeedsMmS[1]);
    TEST_ASSERT_FLOAT_WITHIN(1.0f, 2000.0f, result.intervalSpeedsMmS[2]);

    // Average should be the mean of the three scale speeds
    float avg = (result.scaleSpeedsMph[0] + result.scaleSpeedsMph[1] +
                 result.scaleSpeedsMph[2]) / 3.0f;
    TEST_ASSERT_FLOAT_WITHIN(0.1f, avg, result.avgScaleSpeedMph);
}


void test_scale_factor_sanity(void) {
    // 1000 mm/s model speed should be about 194.7 scale mph in HO
    // 1000 * 87.1 * 3600 / (1e6 * 1.609344) = 194.73
    float speed_mms = 1000.0f;
    RunResult run = makeUniformRun_AtoB(speed_mms);

    SpeedResult result;
    speed_calculate(run, result);

    TEST_ASSERT_FLOAT_WITHIN(1.0f, 194.7f, result.avgScaleSpeedMph);
}


void test_b_to_a_timestamps_reordered(void) {
    // B→A: sensor 3 fires first, sensor 0 fires last
    // Verify timestamps are reordered correctly for interval calc
    RunResult run;
    memset(&run, 0, sizeof(run));
    run.direction = DIR_B_TO_A;
    run.sensorsTriggered = 4;
    // Physical order: S3 first (1000000), S2, S1, S0 last
    run.triggered[0] = true;  run.timestamps[0] = 1600000;
    run.triggered[1] = true;  run.timestamps[1] = 1400000;
    run.triggered[2] = true;  run.timestamps[2] = 1200000;
    run.triggered[3] = true;  run.timestamps[3] = 1000000;
    run.runDurationUs = 600000;

    SpeedResult result;
    TEST_ASSERT_TRUE(speed_calculate(run, result));
    TEST_ASSERT_EQUAL_INT(3, result.intervalCount);

    // All intervals should be 200000 us (200ms)
    for (int i = 0; i < result.intervalCount; i++) {
        TEST_ASSERT_EQUAL_UINT32(200000, result.intervalsUs[i]);
    }

    // 100mm / 0.2s = 500 mm/s
    for (int i = 0; i < result.intervalCount; i++) {
        TEST_ASSERT_FLOAT_WITHIN(1.0f, 500.0f, result.intervalSpeedsMmS[i]);
    }
}


// ================================================================
// Test runner
// ================================================================

int main(int argc, char **argv) {
    UNITY_BEGIN();

    RUN_TEST(test_uniform_speed_A_to_B);
    RUN_TEST(test_uniform_speed_B_to_A);
    RUN_TEST(test_same_speed_both_directions);
    RUN_TEST(test_fewer_than_two_sensors_fails);
    RUN_TEST(test_zero_sensors_fails);
    RUN_TEST(test_two_sensors_only);
    RUN_TEST(test_gap_in_sensors);
    RUN_TEST(test_slow_speed);
    RUN_TEST(test_fast_speed);
    RUN_TEST(test_interval_times_correct);
    RUN_TEST(test_varying_speeds);
    RUN_TEST(test_scale_factor_sanity);
    RUN_TEST(test_b_to_a_timestamps_reordered);

    return UNITY_END();
}
