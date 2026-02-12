#include "mcp23017.h"
#include "mqtt_log.h"

bool mcp23017_write_reg(uint8_t reg, uint8_t value) {
    Wire.beginTransmission(MCP23017_ADDR);
    Wire.write(reg);
    Wire.write(value);
    uint8_t err = Wire.endTransmission();
    if (err != 0) {
        logErrorf("MCP23017: I2C write error %d (reg 0x%02X)", err, reg);
        return false;
    }
    return true;
}

uint8_t mcp23017_read_reg(uint8_t reg) {
    Wire.beginTransmission(MCP23017_ADDR);
    Wire.write(reg);
    uint8_t err = Wire.endTransmission();
    if (err != 0) {
        logErrorf("MCP23017: I2C write error %d (reg 0x%02X)", err, reg);
        return 0xFF;
    }
    Wire.requestFrom((uint8_t)MCP23017_ADDR, (uint8_t)1);
    if (Wire.available() < 1) {
        logErrorf("MCP23017: I2C read error (reg 0x%02X)", reg);
        return 0xFF;
    }
    return Wire.read();
}

bool mcp23017_init() {
    // Check device is present
    Wire.beginTransmission(MCP23017_ADDR);
    if (Wire.endTransmission() != 0) {
        return false;
    }

    // Build input mask for our sensors (GPA0 through GPA[NUM_SENSORS-1])
    uint8_t sensorMask = (1 << NUM_SENSORS) - 1;  // e.g., 0x0F for 4 sensors

    // IOCON: MIRROR=1 (INTA=INTB mirrored), INTPOL=0 (active-low)
    // BANK=0 (sequential registers), ODR=0 (active driver)
    mcp23017_write_reg(MCP_IOCON, 0x40);

    // Port A: sensor pins as inputs
    mcp23017_write_reg(MCP_IODIRA, 0xFF);
    // Port B: all inputs (unused, but safe default)
    mcp23017_write_reg(MCP_IODIRB, 0xFF);

    // No internal pullups — we use external 10k pullups
    mcp23017_write_reg(MCP_GPPUA, 0x00);
    mcp23017_write_reg(MCP_GPPUB, 0x00);

    // No polarity inversion — TCRT5000 with pullup reads HIGH when clear,
    // LOW when locomotive is over sensor. We detect falling edges.
    mcp23017_write_reg(MCP_IPOLA, 0x00);

    // Interrupt-on-change for sensor pins only
    mcp23017_write_reg(MCP_GPINTENA, sensorMask);
    mcp23017_write_reg(MCP_GPINTENB, 0x00);

    // Compare against default value (HIGH = no detection)
    // INTCON=1 means compare to DEFVAL, not previous value
    mcp23017_write_reg(MCP_INTCONA, sensorMask);
    mcp23017_write_reg(MCP_DEFVALA, sensorMask);  // Default = all HIGH (no loco)

    // Read INTCAP and GPIO to clear any pending interrupt
    mcp23017_read_reg(MCP_INTCAPA);
    mcp23017_read_reg(MCP_GPIOA);

    return true;
}

uint8_t mcp23017_read_interrupt() {
    // INTCAPA captures port state at time of interrupt — reading clears it
    return mcp23017_read_reg(MCP_INTCAPA);
}

uint8_t mcp23017_read_sensors() {
    return mcp23017_read_reg(MCP_GPIOA);
}
