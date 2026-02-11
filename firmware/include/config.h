#pragma once

// =============================================================================
// Speed Calibration Track - Configuration
// Phase 1: 4-sensor prototype on breadboard
// =============================================================================

// --- Sensor array ---
#define NUM_SENSORS           4       // Phase 1: 4 sensors; change to 16 for full PCB
#if NUM_SENSORS > 16
  #error "NUM_SENSORS cannot exceed 16 (MCP23017 limit: GPA0-7 + GPB0-7)"
#endif
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

// --- MQTT ---
#define MQTT_PORT             1883
#define MQTT_BUFFER_SIZE      2048
#define MQTT_NVS_NAMESPACE    "mqtt"
#define MQTT_DEFAULT_PREFIX   "/cova"
#define MQTT_DEFAULT_NAME     "speed-cal"
#define MQTT_RECONNECT_MS     5000    // Retry interval on disconnect
// Sensor topics: {prefix}/speed-cal/{name}/arm, /stop, /status, /result, /error
// Throttle topics: {prefix}/speed-cal/throttle/acquire, /speed, /direction, etc.
#define THROTTLE_TOPIC_NAME   "throttle"

// --- Web server ---
#define WS_PATH           "/ws"
#define HTTP_PORT         80

// --- HX711 Load Cell ---
#define HX711_DOUT_PIN        16      // Data out from HX711
#define HX711_SCK_PIN         17      // Clock to HX711
#define LOAD_CELL_SAMPLE_MS   100     // Read interval (ms)
#define LOAD_CELL_EMA_ALPHA   0.3f    // Smoothing factor (0-1, higher = less smoothing)
#define LOAD_CELL_CAL_FACTOR  420.0f  // Raw units per gram (tune with known weight)

// --- Piezo Vibration ---
#define PIEZO_ADC_PIN         36      // ADC1_CH0 (VP), safe with WiFi
#define VIBRATION_CAPTURE_MS  500     // Default capture window (ms)
#define VIBRATION_SAMPLE_US   500     // Sample interval (~2kHz)
#define VIBRATION_MAX_SAMPLES 1200    // Buffer size (headroom over 500ms/500us = 1000 samples)

// --- INMP441 Audio ---
#define I2S_SCK_PIN           18      // I2S bit clock
#define I2S_WS_PIN            19      // I2S word select (L/R)
#define I2S_SD_PIN            23      // I2S serial data (input)
#define AUDIO_SAMPLE_RATE     16000   // 16kHz
#define AUDIO_CAPTURE_MS      1000    // Default capture window (ms)
#define AUDIO_DMA_BUF_COUNT   4       // Number of DMA buffers
#define AUDIO_DMA_BUF_LEN     1024    // Samples per DMA buffer

// --- Track Switches (optional 3PDT safety interlocks) ---
#define TRACK_SW1_PIN             25      // Layout/Prog track switch (HIGH = prog)
#define TRACK_SW2_PIN             26      // DCC/DC switch (HIGH = DC)
#define TRACK_SWITCH_DEBOUNCE_MS  50      // Debounce time (ms)
#define TRACK_SWITCH_NVS_NAMESPACE "trksw"

// --- Serial ---
#define SERIAL_BAUD   115200
