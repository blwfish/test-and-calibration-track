#include "mqtt_log.h"
#include "config.h"
#include "mqtt_manager.h"

#include <Preferences.h>
#include <stdarg.h>

// --- State ---
static LogLevel currentLevel = LOG_INFO;

// --- Rate limiting ---
static unsigned long ratePeriodStart = 0;
static uint16_t rateCount = 0;
static uint16_t rateSuppressed = 0;

// --- Level name table ---
static const char* levelNames[] = {"DEBUG", "INFO", "WARN", "ERROR", "CRIT"};

// --- Core publish function ---
static void logPublish(LogLevel level, const char* msg) {
    if (level < currentLevel) {
        return;
    }

    // Format: [LEVEL][uptime_s] message
    char fullMsg[LOG_FMT_BUF_SIZE];
    unsigned long uptime = millis() / 1000;
    snprintf(fullMsg, sizeof(fullMsg), "[%s][%lu] %s",
             levelNames[level], uptime, msg);

    // Serial output: always for ERROR+
    if (level >= LOG_ERROR) {
        Serial.println(fullMsg);
    }

    // MQTT output with rate limiting
    if (mqtt_is_connected()) {
        unsigned long now = millis();
        if (now - ratePeriodStart >= LOG_RATE_PERIOD_MS) {
            // New rate window — report suppressed count from previous window
            if (rateSuppressed > 0) {
                char suppMsg[80];
                snprintf(suppMsg, sizeof(suppMsg),
                         "[WARN][%lu] Log rate limited: %u messages suppressed",
                         uptime, rateSuppressed);
                mqtt_publish_log(suppMsg);
            }
            ratePeriodStart = now;
            rateCount = 0;
            rateSuppressed = 0;
        }

        if (rateCount < LOG_RATE_MAX_PER_SEC) {
            mqtt_publish_log(fullMsg);
            rateCount++;
        } else {
            rateSuppressed++;
        }
    }
}

// --- Public API: init ---

void mqtt_log_init() {
    Preferences prefs;
    prefs.begin(LOG_NVS_NAMESPACE, true);
    uint8_t saved = prefs.getUChar("level", LOG_INFO);
    prefs.end();

    if (saved <= LOG_CRITICAL) {
        currentLevel = (LogLevel)saved;
    }

    Serial.printf("MQTT log: level=%s\n", levelNames[currentLevel]);
}

// --- Public API: fixed-string convenience ---

void logDebug(const char* msg)    { logPublish(LOG_DEBUG, msg); }
void logInfo(const char* msg)     { logPublish(LOG_INFO, msg); }
void logWarn(const char* msg)     { logPublish(LOG_WARN, msg); }
void logError(const char* msg)    { logPublish(LOG_ERROR, msg); }
void logCritical(const char* msg) { logPublish(LOG_CRITICAL, msg); }

// --- Public API: printf-style convenience ---

static void logPublishf(LogLevel level, const char* fmt, va_list args) {
    if (level < currentLevel) {
        return;  // Early exit before formatting
    }
    char buf[LOG_FMT_BUF_SIZE];
    vsnprintf(buf, sizeof(buf), fmt, args);
    logPublish(level, buf);
}

void logDebugf(const char* fmt, ...) {
    va_list args; va_start(args, fmt); logPublishf(LOG_DEBUG, fmt, args); va_end(args);
}
void logInfof(const char* fmt, ...) {
    va_list args; va_start(args, fmt); logPublishf(LOG_INFO, fmt, args); va_end(args);
}
void logWarnf(const char* fmt, ...) {
    va_list args; va_start(args, fmt); logPublishf(LOG_WARN, fmt, args); va_end(args);
}
void logErrorf(const char* fmt, ...) {
    va_list args; va_start(args, fmt); logPublishf(LOG_ERROR, fmt, args); va_end(args);
}
void logCriticalf(const char* fmt, ...) {
    va_list args; va_start(args, fmt); logPublishf(LOG_CRITICAL, fmt, args); va_end(args);
}

// --- Runtime level control ---

void mqtt_log_set_level(LogLevel level) {
    if (level > LOG_CRITICAL) return;
    currentLevel = level;

    // Persist to NVS
    Preferences prefs;
    prefs.begin(LOG_NVS_NAMESPACE, false);
    prefs.putUChar("level", (uint8_t)level);
    prefs.end();

    // Announce (always published regardless of current level)
    char buf[64];
    snprintf(buf, sizeof(buf), "Log level set to %s", levelNames[level]);
    logInfo(buf);
}

LogLevel mqtt_log_get_level() {
    return currentLevel;
}

// --- MQTT command handler ---

void mqtt_log_handle_command(const char* payload, unsigned int length) {
    // Accept numeric "0"-"4"
    if (length == 1 && payload[0] >= '0' && payload[0] <= '4') {
        mqtt_log_set_level((LogLevel)(payload[0] - '0'));
        return;
    }

    // Try level name match
    char upper[12];
    unsigned int copyLen = length < sizeof(upper) - 1 ? length : sizeof(upper) - 1;
    for (unsigned int i = 0; i < copyLen; i++) {
        upper[i] = toupper(payload[i]);
    }
    upper[copyLen] = '\0';

    if (strncmp(upper, "DEBUG", 5) == 0) mqtt_log_set_level(LOG_DEBUG);
    else if (strncmp(upper, "INFO", 4) == 0) mqtt_log_set_level(LOG_INFO);
    else if (strncmp(upper, "WARN", 4) == 0) mqtt_log_set_level(LOG_WARN);
    else if (strncmp(upper, "ERROR", 5) == 0) mqtt_log_set_level(LOG_ERROR);
    else if (strncmp(upper, "CRIT", 4) == 0) mqtt_log_set_level(LOG_CRITICAL);
}
