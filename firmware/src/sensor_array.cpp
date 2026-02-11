#include "sensor_array.h"
#include "mcp23017.h"

// --- ISR state (volatile, accessed from ISR and main loop) ---
static volatile bool isrFired = false;
static volatile uint32_t isrTimestamp = 0;

// --- Run state ---
static RunState state = STATE_IDLE;
static RunResult result;
static uint32_t armTime = 0;

void IRAM_ATTR sensor_isr() {
    isrTimestamp = micros();
    isrFired = true;
}

void sensor_init() {
    state = STATE_IDLE;
    memset(&result, 0, sizeof(result));
}

void sensor_arm() {
    // Clear any pending interrupt state on MCP23017
    mcp23017_read_interrupt();
    mcp23017_read_sensors();

    // Reset result
    memset(&result, 0, sizeof(result));
    result.direction = DIR_UNKNOWN;

    // Clear ISR flag
    isrFired = false;

    armTime = millis();
    state = STATE_ARMED;
}

void sensor_disarm() {
    state = STATE_IDLE;
    isrFired = false;
}

RunState sensor_get_state() {
    return state;
}

const RunResult& sensor_get_result() {
    return result;
}

const char* sensor_state_name(RunState s) {
    switch (s) {
        case STATE_IDLE:      return "idle";
        case STATE_ARMED:     return "armed";
        case STATE_MEASURING: return "measuring";
        case STATE_COMPLETE:  return "complete";
        default:              return "unknown";
    }
}

bool sensor_update() {
    if (state == STATE_IDLE || state == STATE_COMPLETE) {
        return false;
    }

    // Check timeout
    if (state == STATE_MEASURING) {
        if (millis() - result.runStartMillis > DETECTION_TIMEOUT_MS) {
            state = STATE_COMPLETE;
            return true;
        }
    }

    // Process ISR event
    if (!isrFired) {
        return false;
    }

    // Capture ISR data and clear flag
    uint32_t ts = isrTimestamp;
    isrFired = false;

    // Settle guard: ignore triggers right after arming
    if (state == STATE_ARMED && (millis() - armTime < ARM_SETTLE_MS)) {
        // Read interrupt to clear it, but discard
        mcp23017_read_interrupt();
        return false;
    }

    // Read which sensor(s) triggered — INTCAP has the port state at interrupt time
    uint8_t captured = mcp23017_read_interrupt();
    uint8_t sensorMask = (1 << NUM_SENSORS) - 1;

    // The captured value shows pin states. Sensors read LOW when triggered
    // (locomotive overhead blocks reflection, pullup goes low).
    // Invert and mask to get "which sensors are currently detecting".
    uint8_t active = (~captured) & sensorMask;

    // Find newly triggered sensors
    for (int i = 0; i < NUM_SENSORS; i++) {
        if (result.triggered[i]) {
            continue;  // Already recorded
        }
        if (!(active & (1 << i))) {
            continue;  // Not triggered now
        }

        // Check re-trigger guard
        if (result.sensorsTriggered > 0) {
            uint32_t lastTs = 0;
            for (int j = 0; j < NUM_SENSORS; j++) {
                if (result.triggered[j] && result.timestamps[j] > lastTs) {
                    lastTs = result.timestamps[j];
                }
            }
            if (ts - lastTs < MIN_RETRIGGER_US) {
                continue;  // Too fast, likely noise
            }
        }

        // Record this sensor
        result.triggered[i] = true;
        result.timestamps[i] = ts;
        result.sensorsTriggered++;

        // First trigger starts the run
        if (result.sensorsTriggered == 1) {
            result.runStartMillis = millis();
            state = STATE_MEASURING;
        }
    }

    // Determine direction once we have enough data
    if (result.direction == DIR_UNKNOWN && result.sensorsTriggered >= 2) {
        if (result.triggered[0] && result.triggered[NUM_SENSORS - 1]) {
            result.direction = (result.timestamps[0] < result.timestamps[NUM_SENSORS - 1])
                ? DIR_A_TO_B : DIR_B_TO_A;
        } else if (result.triggered[0]) {
            result.direction = DIR_A_TO_B;  // End A fired first
        } else if (result.triggered[NUM_SENSORS - 1]) {
            result.direction = DIR_B_TO_A;  // End B fired first
        }
    }

    // Check if all sensors have fired
    if (result.sensorsTriggered >= NUM_SENSORS) {
        // Calculate total run duration
        uint32_t first = UINT32_MAX, last = 0;
        for (int i = 0; i < NUM_SENSORS; i++) {
            if (result.triggered[i]) {
                if (result.timestamps[i] < first) first = result.timestamps[i];
                if (result.timestamps[i] > last) last = result.timestamps[i];
            }
        }
        result.runDurationUs = last - first;
        state = STATE_COMPLETE;
        return true;
    }

    return false;
}
