#include <Arduino.h>
#include <Wire.h>
#include "config.h"
#include "mcp23017.h"
#include "sensor_array.h"
#include "speed_calc.h"
#include "wifi_manager.h"
#include "web_server.h"
#include "mqtt_manager.h"
#include "load_cell.h"
#include "vibration.h"
#include "audio_capture.h"
#include "pull_test.h"

// Serial command buffer
static char cmdBuf[32];
static int cmdLen = 0;

static void printHelp() {
    Serial.println();
    Serial.println("Speed Calibration Track v0.4");
    Serial.println("Commands:");
    Serial.println("  arm       - Arm sensors for next pass");
    Serial.println("  disarm    - Cancel active measurement");
    Serial.println("  status    - Show current state");
    Serial.println("  read      - Read raw sensor state");
    Serial.println("  load      - Read load cell (grams)");
    Serial.println("  tare      - Tare (zero) load cell");
    Serial.println("  vibration - Start vibration capture");
    Serial.println("  audio     - Start audio capture");
    Serial.println("  help      - Show this message");
    Serial.println();
}

static void printStatus() {
    Serial.printf("State: %s\n", sensor_state_name(sensor_get_state()));
    if (sensor_get_state() == STATE_MEASURING) {
        const RunResult& r = sensor_get_result();
        Serial.printf("Sensors triggered: %d / %d\n", r.sensorsTriggered, NUM_SENSORS);
    }
    Serial.printf("MQTT: %s\n", mqtt_is_connected() ? "connected" : "disconnected");
    Serial.printf("Load cell: %s", load_cell_is_ready() ? "ready" : "not ready");
    if (load_cell_is_ready()) {
        Serial.printf(", %.1fg%s", load_cell_get_grams(), load_cell_is_tared() ? " (tared)" : "");
    }
    Serial.println();
    Serial.printf("Vibration: %s\n", vibration_is_capturing() ? "capturing" : "idle");
    Serial.printf("Audio: %s\n", audio_is_capturing() ? "capturing" : "idle");
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
    } else if (strcmp(cmd, "load") == 0) {
        if (load_cell_is_ready()) {
            Serial.printf("Load: %.1f g (raw=%d%s)\n",
                          load_cell_get_grams(), (int)load_cell_get_raw(),
                          load_cell_is_tared() ? ", tared" : "");
            web_send_load();
        } else {
            Serial.println("Load cell not ready (no HX711 data yet).");
        }
    } else if (strcmp(cmd, "tare") == 0) {
        load_cell_tare();
        web_send_load();
    } else if (strcmp(cmd, "vibration") == 0) {
        vibration_start_capture();
    } else if (strcmp(cmd, "audio") == 0) {
        audio_start_capture();
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
    Serial.println("Speed Calibration Track v0.4");
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

    // Initialize sensor peripherals
    load_cell_init();
    vibration_init();
    audio_init();

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

    // Sensor peripherals
    load_cell_process();

    bool vibWasCapturing = vibration_is_capturing();
    vibration_process();
    if (vibWasCapturing && !vibration_is_capturing()) {
        web_send_vibration();
    }

    bool audioWasCapturing = audio_is_capturing();
    audio_process();
    if (audioWasCapturing && !audio_is_capturing()) {
        web_send_audio();
    }

    // Pull test state machine
    bool pullWasRunning = pull_test_is_running();
    pull_test_process();
    if (pullWasRunning && !pull_test_is_running()) {
        web_send_pull_test();
    }
    // Send progress updates during pull test (throttled by state machine timing)
    static int lastPullStep = -1;
    if (pull_test_is_running()) {
        int curStep = pull_test_current_step_num();
        if (curStep != lastPullStep) {
            lastPullStep = curStep;
            web_send_pull_progress();
        }
    } else {
        lastPullStep = -1;
    }

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
