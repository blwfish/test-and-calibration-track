#pragma once

#include <Arduino.h>

// Automated drawbar pull test.
// Ramps loco speed in steps, reads load cell at each step,
// builds a pull-vs-speed table. Requires throttle acquired
// and load cell ready before starting.

// Start a pull test.
// step_inc: speed step increment (e.g. 5 = steps 5,10,...125,126)
// settle_ms: time to wait at each speed before reading load cell
void pull_test_start(int step_inc, unsigned long settle_ms);

// Abort a running test. Stops the loco, keeps partial results.
void pull_test_abort();

// Non-blocking state machine. Call from loop().
void pull_test_process();

// True if a test is currently running.
bool pull_test_is_running();

// Current speed step being tested (0 if not running).
int pull_test_current_step();

// Total number of steps in the test.
int pull_test_total_steps();

// Current step number (1-based index into the sequence).
int pull_test_current_step_num();

// Build complete results JSON. Valid after test completes or aborts.
String pull_test_build_json();

// Build progress JSON for the current step.
String pull_test_build_progress_json();
