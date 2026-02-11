#pragma once

#include <Arduino.h>

// Initialize HX711 GPIO pins. Call once in setup().
void load_cell_init();

// Non-blocking periodic read. Call from loop().
void load_cell_process();

// Zero the current reading (set tare offset).
void load_cell_tare();

// Get latest smoothed reading in grams.
float load_cell_get_grams();

// Get latest raw (unsmoothed, untared) ADC value.
int32_t load_cell_get_raw();

// True if at least one valid reading has been taken.
bool load_cell_is_ready();

// True if tare offset has been set.
bool load_cell_is_tared();

// Build JSON string for MQTT/WebSocket publishing.
String load_cell_build_json();
