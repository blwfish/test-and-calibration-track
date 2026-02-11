#include "speed_calc.h"

// Conversion: mm/s model scale → prototype mph
// prototype_mph = model_mm_s * scale_factor / 1_000_000 * 3600 / 1.609344
// Simplified: prototype_mph = model_mm_s * scale_factor * 0.0022369
static const float MMS_TO_MPH = HO_SCALE_FACTOR * 3600.0f / (1000000.0f * 1.609344f);

bool speed_calculate(const RunResult& run, SpeedResult& out) {
    memset(&out, 0, sizeof(out));

    if (run.sensorsTriggered < 2) {
        return false;
    }

    // Build ordered array of timestamps in direction of travel.
    // Sensors are physically ordered 0..N-1 from end A to end B.
    // For A→B travel, use sensor order as-is.
    // For B→A travel, reverse the order.
    uint32_t ordered[NUM_SENSORS];
    bool orderedValid[NUM_SENSORS];

    for (int i = 0; i < NUM_SENSORS; i++) {
        int src = (run.direction == DIR_B_TO_A) ? (NUM_SENSORS - 1 - i) : i;
        ordered[i] = run.timestamps[src];
        orderedValid[i] = run.triggered[src];
    }

    // Compute intervals between consecutive triggered sensors
    int intervals = 0;
    float totalSpeed = 0;

    for (int i = 0; i < NUM_SENSORS - 1; i++) {
        if (!orderedValid[i] || !orderedValid[i + 1]) {
            continue;  // Skip gaps
        }

        uint32_t dt = ordered[i + 1] - ordered[i];
        if (dt == 0) {
            continue;  // Avoid division by zero
        }

        out.intervalsUs[intervals] = dt;
        out.intervalSpeedsMmS[intervals] = SENSOR_SPACING_MM / (dt / 1000000.0f);
        out.scaleSpeedsMph[intervals] = out.intervalSpeedsMmS[intervals] * MMS_TO_MPH;
        totalSpeed += out.scaleSpeedsMph[intervals];
        intervals++;
    }

    out.intervalCount = intervals;
    out.avgScaleSpeedMph = (intervals > 0) ? (totalSpeed / intervals) : 0;

    return intervals > 0;
}

void speed_print_result(const RunResult& run, const SpeedResult& speed) {
    Serial.println("=== Run Complete ===");
    Serial.printf("Direction: %s\n",
        (run.direction == DIR_A_TO_B) ? "A→B" :
        (run.direction == DIR_B_TO_A) ? "B→A" : "unknown");
    Serial.printf("Sensors triggered: %d / %d\n", run.sensorsTriggered, NUM_SENSORS);
    Serial.printf("Total time: %.1f ms\n", run.runDurationUs / 1000.0f);
    Serial.println();

    // Raw timestamps
    Serial.println("Sensor timestamps (us from first trigger):");
    uint32_t firstTs = UINT32_MAX;
    for (int i = 0; i < NUM_SENSORS; i++) {
        if (run.triggered[i] && run.timestamps[i] < firstTs) {
            firstTs = run.timestamps[i];
        }
    }
    for (int i = 0; i < NUM_SENSORS; i++) {
        if (run.triggered[i]) {
            Serial.printf("  S%d: %lu us\n", i, run.timestamps[i] - firstTs);
        } else {
            Serial.printf("  S%d: --\n", i);
        }
    }
    Serial.println();

    // Speed per interval
    if (speed.intervalCount > 0) {
        Serial.println("Interval speeds:");
        for (int i = 0; i < speed.intervalCount; i++) {
            Serial.printf("  [%d] %lu us  →  %.1f mm/s  →  %.1f scale mph\n",
                i, speed.intervalsUs[i],
                speed.intervalSpeedsMmS[i], speed.scaleSpeedsMph[i]);
        }
        Serial.println();
        Serial.printf("Average: %.1f scale mph\n", speed.avgScaleSpeedMph);
    } else {
        Serial.println("No valid intervals computed.");
    }
    Serial.println("====================");
}
