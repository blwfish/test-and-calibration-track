#pragma once

#include <Arduino.h>
#include "config.h"
#include "sensor_array.h"

// Computed speed data from a completed run
struct SpeedResult {
    int intervalCount;                      // Number of valid intervals
    float intervalSpeedsMmS[NUM_SENSORS];   // Model-scale mm/s per interval
    float scaleSpeedsMph[NUM_SENSORS];      // Prototype mph per interval
    float avgScaleSpeedMph;                 // Mean prototype speed
    uint32_t intervalsUs[NUM_SENSORS];      // Time between adjacent sensors
};

// Compute speeds from a completed run result.
// Timestamps are reordered by direction of travel.
// Returns true if at least one valid interval was computed.
bool speed_calculate(const RunResult& run, SpeedResult& out);

// Print a speed result to Serial in human-readable format.
void speed_print_result(const RunResult& run, const SpeedResult& speed);
