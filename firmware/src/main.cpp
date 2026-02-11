#include <Arduino.h>
#include <Wire.h>
#include "config.h"
#include "mcp23017.h"
#include "sensor_array.h"
#include "speed_calc.h"
#include "wifi_manager.h"
#include "web_server.h"
#include "mqtt_manager.h"

// Serial command buffer
static char cmdBuf[32];
static int cmdLen = 0;

static void printHelp() {
    Serial.println();
    Serial.println("Speed Calibration Track - Phase 1 (4-sensor prototype)");
    Serial.println("Commands:");
    Serial.println("  arm     - Arm sensors for next pass");
    Serial.println("  disarm  - Cancel active measurement");
    Serial.println("  status  - Show current state");
    Serial.println("  read    - Read raw sensor state");
    Serial.println("  help    - Show this message");
    Serial.println();
}

static void printStatus() {
    Serial.printf("State: %s\n", sensor_state_name(sensor_get_state()));
    if (sensor_get_state() == STATE_MEASURING) {
        const RunResult& r = sensor_get_result();
        Serial.printf("Sensors triggered: %d / %d\n", r.sensorsTriggered, NUM_SENSORS);
    }
    Serial.printf("MQTT: %s\n", mqtt_is_connected() ? "connected" : "disconnected");
}

static void readSensors() {
    uint8_t raw = mcp23017_read_sensors();
    Serial.printf("Port A raw: 0x%02X  [", raw);
    for (int i = 0; i < NUM_SENSORS; i++) {
        bool detected = !(raw & (1 << i));  // LOW = detection
        Serial.printf(" S%d:%s", i, detected ? "DET" : "---");
    }
    Serial.println(" ]");
}

static void processCommand(const char* cmd) {
    if (strcmp(cmd, "arm") == 0) {
        sensor_arm();
        Serial.println("Armed. Waiting for locomotive pass...");
        web_send_status();
    } else if (strcmp(cmd, "disarm") == 0) {
        sensor_disarm();
        Serial.println("Disarmed.");
        web_send_status();
    } else if (strcmp(cmd, "status") == 0) {
        printStatus();
    } else if (strcmp(cmd, "read") == 0) {
        readSensors();
    } else if (strcmp(cmd, "help") == 0) {
        printHelp();
    } else if (strlen(cmd) > 0) {
        Serial.printf("Unknown command: '%s' (type 'help')\n", cmd);
    }
}

void setup() {
    Serial.begin(SERIAL_BAUD);
    delay(500);  // Let serial settle

    Serial.println();
    Serial.println("================================");
    Serial.println("Speed Calibration Track v0.3");
    Serial.printf("Sensors: %d @ %dmm spacing\n", NUM_SENSORS, (int)SENSOR_SPACING_MM);
    Serial.println("================================");

    // Initialize I2C
    Wire.begin(I2C_SDA, I2C_SCL);
    Wire.setClock(I2C_FREQ);
    Serial.println("I2C initialized.");

    // Scan I2C bus
    Serial.println("Scanning I2C bus...");
    int found = 0;
    for (uint8_t addr = 0x08; addr < 0x78; addr++) {
        Wire.beginTransmission(addr);
        if (Wire.endTransmission() == 0) {
            Serial.printf("  Found device at 0x%02X\n", addr);
            found++;
        }
    }
    if (found == 0) {
        Serial.println("  No I2C devices found! Check SDA/SCL wiring and power.");
    }
    Serial.println();

    // Initialize MCP23017
    if (!mcp23017_init()) {
        Serial.printf("ERROR: MCP23017 not found at 0x%02X!\n", MCP23017_ADDR);
        Serial.println("Check wiring: SDA=GPIO21, SCL=GPIO22, VCC, GND");
        Serial.println("Halting.");
        while (true) { delay(1000); }
    }
    Serial.println("MCP23017 initialized.");

    // Initialize sensor array logic
    sensor_init();

    // Attach interrupt on MCP23017 INT pin (active-low, falling edge)
    pinMode(MCP23017_INT_PIN, INPUT_PULLUP);
    attachInterrupt(digitalPinToInterrupt(MCP23017_INT_PIN), sensor_isr, FALLING);
    Serial.printf("Interrupt attached on GPIO %d.\n", MCP23017_INT_PIN);

    // Read sensors once to show initial state
    readSensors();

    // Start WiFi
    wifi_init();

    // Start MQTT
    mqtt_init();

    // Start web server
    web_init();

    printHelp();
    Serial.printf("Web UI: http://%s/\n", wifi_get_ip().c_str());
    Serial.print("> ");
}

void loop() {
    // WiFi housekeeping (DNS for captive portal)
    wifi_process();

    // MQTT housekeeping (reconnect, process incoming)
    mqtt_process();

    // Process serial commands
    while (Serial.available()) {
        char c = Serial.read();
        if (c == '\n' || c == '\r') {
            if (cmdLen > 0) {
                cmdBuf[cmdLen] = '\0';
                processCommand(cmdBuf);
                cmdLen = 0;
                Serial.print("> ");
            }
        } else if (cmdLen < (int)sizeof(cmdBuf) - 1) {
            cmdBuf[cmdLen++] = c;
        }
    }

    // Update sensor detection state machine
    bool justCompleted = sensor_update();

    if (justCompleted) {
        const RunResult& run = sensor_get_result();

        Serial.println();

        if (run.sensorsTriggered < 2) {
            Serial.println("Run ended with fewer than 2 sensors triggered.");
            Serial.printf("Sensors triggered: %d\n", run.sensorsTriggered);
        } else {
            SpeedResult speed;
            if (speed_calculate(run, speed)) {
                speed_print_result(run, speed);
            } else {
                Serial.println("Run complete but could not compute speeds.");
            }
        }

        // Send result to web clients and MQTT
        web_send_result();

        Serial.println("Type 'arm' to measure again.");
        Serial.print("> ");
    }
}
