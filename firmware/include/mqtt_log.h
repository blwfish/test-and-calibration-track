#pragma once

#include <Arduino.h>

// ============================================================================
// MQTT Debug Logging
// ============================================================================
//
// Publishes formatted log messages to MQTT topic
//   {prefix}/speed-cal/{name}/log
// and optionally to Serial (ERROR and above always).
//
// Usage:
//   logInfo("Sensor armed");
//   logErrorf("I2C write error %d (reg 0x%02X)", err, reg);
//   logDebugf("Speed: %.1f mph", speed);
//

// --- Log levels (matches esp32-config convention) ---
enum LogLevel : uint8_t {
    LOG_DEBUG    = 0,
    LOG_INFO     = 1,
    LOG_WARN     = 2,
    LOG_ERROR    = 3,
    LOG_CRITICAL = 4
};

// --- Initialization ---
// Call after mqtt_init(). Loads persisted log level from NVS.
void mqtt_log_init();

// --- Core logging functions (fixed-string, no formatting overhead) ---
void logDebug(const char* msg);
void logInfo(const char* msg);
void logWarn(const char* msg);
void logError(const char* msg);
void logCritical(const char* msg);

// --- printf-style variants (for easy Serial.printf conversion) ---
void logDebugf(const char* fmt, ...) __attribute__((format(printf, 1, 2)));
void logInfof(const char* fmt, ...) __attribute__((format(printf, 1, 2)));
void logWarnf(const char* fmt, ...) __attribute__((format(printf, 1, 2)));
void logErrorf(const char* fmt, ...) __attribute__((format(printf, 1, 2)));
void logCriticalf(const char* fmt, ...) __attribute__((format(printf, 1, 2)));

// --- Runtime configuration ---
void mqtt_log_set_level(LogLevel level);
LogLevel mqtt_log_get_level();

// --- MQTT command handler (called by mqtt_manager callback) ---
// Payload: "0"-"4" or level name "DEBUG","INFO","WARN","ERROR","CRITICAL"
void mqtt_log_handle_command(const char* payload, unsigned int length);
