/**
 * Arduino.h stub for native (desktop) unit tests.
 *
 * Provides just enough of the Arduino API for speed_calc.cpp and
 * sensor_array types to compile on a desktop platform (no hardware).
 */
#pragma once

#include <cstdint>
#include <cstring>
#include <cstdio>
#include <cstdlib>
#include <cstdarg>
#include <cmath>

// --- Types ---
typedef uint8_t byte;

// --- Attribute stubs ---
#define IRAM_ATTR

// --- Serial stub ---
class FakeSerial {
public:
    void begin(unsigned long) {}
    void println() {}
    void println(const char* s) { printf("%s\n", s); }
    void println(int v) { printf("%d\n", v); }
    void print(const char* s) { printf("%s", s); }
    void print(int v) { printf("%d", v); }
    void printf(const char* fmt, ...) {
        va_list args;
        va_start(args, fmt);
        vprintf(fmt, args);
        va_end(args);
    }
};

extern FakeSerial Serial;

// --- Time stubs ---
// These can be overridden in tests
uint32_t millis();
uint32_t micros();
