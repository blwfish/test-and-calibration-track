#pragma once

#include <Arduino.h>

// Initialize piezo ADC pin. Call once in setup().
void vibration_init();

// Start a timed capture window. Samples will be collected in process().
void vibration_start_capture();

// True if a capture is currently in progress.
bool vibration_is_capturing();

// Non-blocking sample collection. Call from loop().
void vibration_process();

// True if results are available from a completed capture.
bool vibration_has_result();

// Build JSON string with analysis results.
String vibration_build_json();

// Get cached result values (valid after capture completes).
uint16_t vibration_get_peak_to_peak();
float vibration_get_rms();

// --- Analysis functions (exposed for unit testing) ---

// Compute peak-to-peak from a sample buffer.
uint16_t vibration_calc_peak_to_peak(const uint16_t* samples, int count);

// Compute RMS from a sample buffer (centered around midpoint).
float vibration_calc_rms(const uint16_t* samples, int count);
