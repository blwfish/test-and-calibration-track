#pragma once

// =============================================================================
// Speed Calibration Track - Configuration
// Phase 1: 4-sensor prototype on breadboard
// =============================================================================

// --- Sensor array ---
#define NUM_SENSORS           4       // Phase 1: 4 sensors (GPA0-GPA3)
#define SENSOR_SPACING_MM     100.0f  // Distance between adjacent sensors
#define HO_SCALE_FACTOR       87.1f   // HO scale ratio

// --- MCP23017 ---
#define MCP23017_ADDR         0x27    // A0=A1=A2=HIGH on this board
#define MCP23017_INT_PIN      13      // ESP32 GPIO for MCP23017 INTA

// MCP23017 registers (IOCON.BANK=0, sequential addressing)
#define MCP_IODIRA    0x00
#define MCP_IODIRB    0x01
#define MCP_IPOLA     0x02
#define MCP_IPOLB     0x03
#define MCP_GPINTENA  0x04
#define MCP_GPINTENB  0x05
#define MCP_DEFVALA   0x06
#define MCP_DEFVALB   0x07
#define MCP_INTCONA   0x08
#define MCP_INTCONB   0x09
#define MCP_IOCON     0x0A
#define MCP_GPPUA     0x0C
#define MCP_GPPUB     0x0D
#define MCP_INTFA     0x0E
#define MCP_INTFB     0x0F
#define MCP_INTCAPA   0x10
#define MCP_INTCAPB   0x11
#define MCP_GPIOA     0x12
#define MCP_GPIOB     0x13

// --- I2C ---
#define I2C_SDA       21
#define I2C_SCL       22
#define I2C_FREQ      400000  // 400kHz

// --- Timing ---
#define DETECTION_TIMEOUT_MS  60000   // Max time to wait for a complete pass
#define MIN_RETRIGGER_US      1000    // Ignore re-triggers faster than 1ms
#define ARM_SETTLE_MS         50      // Settle time after arming before accepting triggers

// --- WiFi ---
#define WIFI_AP_SSID      "SpeedCal"
#define WIFI_STA_TIMEOUT  10000   // ms to wait for STA connection
#define WIFI_NVS_NAMESPACE "wifi"

// --- Web server ---
#define WS_PATH           "/ws"
#define HTTP_PORT         80

// --- Serial ---
#define SERIAL_BAUD   115200
