#pragma once

#include <Arduino.h>

// Initialize I2S0 for INMP441 microphone. Call once in setup().
void audio_init();

// Start a timed capture window. Samples collected in process().
void audio_start_capture();

// True if a capture is currently in progress.
bool audio_is_capturing();

// Non-blocking I2S DMA read. Call from loop().
void audio_process();

// True if results are available from a completed capture.
bool audio_has_result();

// Build JSON string with analysis results.
String audio_build_json();

// --- Analysis functions (exposed for unit testing) ---

// Compute RMS of 16-bit signed samples, return as dB relative to full-scale.
float audio_calc_rms_db(const int16_t* samples, int count);

// Find peak absolute value in 16-bit signed samples, return as dB.
float audio_calc_peak_db(const int16_t* samples, int count);
