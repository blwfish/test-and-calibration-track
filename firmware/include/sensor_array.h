#pragma once

#include <Arduino.h>
#include "config.h"

// Run states
enum RunState {
    STATE_IDLE,       // Not armed, ignoring triggers
    STATE_ARMED,      // Waiting for first sensor trigger
    STATE_MEASURING,  // First sensor triggered, collecting timestamps
    STATE_COMPLETE    // All sensors triggered (or timeout) — results ready
};

// Direction of travel
enum Direction {
    DIR_UNKNOWN = 0,
    DIR_A_TO_B = 1,   // Sensor 0 fired first
    DIR_B_TO_A = 2    // Sensor N-1 fired first
};

// Result of a single pass
struct RunResult {
    int sensorsTriggered;
    uint32_t timestamps[NUM_SENSORS];  // micros() at each trigger
    bool triggered[NUM_SENSORS];       // Which sensors fired
    Direction direction;
    uint32_t runStartMillis;           // millis() when first sensor fired
    uint32_t runDurationUs;            // Total time from first to last trigger
};

// ISR-callable: record that an interrupt occurred and capture timestamp.
// Called from the GPIO ISR attached to MCP23017_INT_PIN.
void IRAM_ATTR sensor_isr();

// Initialize sensor array state. Call once in setup().
void sensor_init();

// Arm the sensor array to detect the next pass.
void sensor_arm();

// Disarm / cancel a run in progress.
void sensor_disarm();

// Get current state.
RunState sensor_get_state();

// Call from loop(). Handles:
// - Reading MCP23017 after ISR fires to identify which sensor triggered
// - Timeout detection
// - Transition to STATE_COMPLETE when all sensors have fired
// Returns true if state just transitioned to STATE_COMPLETE.
bool sensor_update();

// Get the result of the last completed run.
// Only valid when state == STATE_COMPLETE.
const RunResult& sensor_get_result();

// Get a human-readable state name.
const char* sensor_state_name(RunState state);
