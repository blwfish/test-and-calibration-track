#pragma once

#include <Arduino.h>

/**
 * Track switch position sensing.
 *
 * Two optional 3PDT switches control track connectivity:
 *   SW1: Layout bus / Programming track
 *   SW2: DCC / DC power pack
 *
 * Third pole of each switch connects to an ESP32 GPIO so firmware
 * knows the current mode. Three derived modes:
 *   LAYOUT    — SW1 selects layout bus (dangerous for calibration)
 *   PROG_DCC  — SW1 selects prog track, SW2 selects DCC (normal calibration)
 *   PROG_DC   — SW1 selects prog track, SW2 selects DC (mechanical testing)
 *
 * When switches are not installed (config option), all interlocks
 * are bypassed and mode reports as UNKNOWN.
 */

// Derived track mode
enum TrackMode {
    TRACK_MODE_UNKNOWN,     // Switches not installed or not yet read
    TRACK_MODE_LAYOUT,      // Connected to layout bus (SW1 = layout)
    TRACK_MODE_PROG_DCC,    // Programming track + DCC (SW1 = prog, SW2 = DCC)
    TRACK_MODE_PROG_DC      // Programming track + DC (SW1 = prog, SW2 = DC)
};

// Initialize GPIO pins and load config from NVS. Call in setup().
void track_switch_init();

// Read switches with debouncing. Call from loop().
void track_switch_process();

// Get current track mode.
TrackMode track_switch_get_mode();

// Human-readable mode name.
const char* track_switch_mode_name(TrackMode mode);

// True if switches are installed and enabled.
bool track_switch_enabled();

// Enable or disable switch sensing (persisted to NVS).
void track_switch_set_enabled(bool enabled);

// Safety check: true if track mode allows automated testing.
// Returns true if switches not installed (bypass) or mode is PROG_DCC.
bool track_switch_allow_dcc_test();

// Safety check: true if mode allows any track-powered operation.
// Returns true if switches not installed (bypass) or mode is not LAYOUT.
bool track_switch_allow_operation();

// True if mode changed since last call to this function.
// Used by main loop to detect transitions and send updates.
bool track_switch_changed();

// Build JSON for WebSocket/MQTT publishing.
String track_switch_build_json();
