#pragma once

#include <Arduino.h>
#include <Wire.h>
#include "config.h"

// Initialize the MCP23017 for sensor input with interrupt-on-change.
// Configures GPA0-GPA(NUM_SENSORS-1) as inputs with interrupt enabled.
// Returns true if device responds on I2C.
bool mcp23017_init();

// Read a single register from the MCP23017.
uint8_t mcp23017_read_reg(uint8_t reg);

// Write a single register on the MCP23017.
void mcp23017_write_reg(uint8_t reg, uint8_t value);

// Read INTCAPA to find which pins triggered the interrupt and clear it.
// Returns bitmask of pins that changed.
uint8_t mcp23017_read_interrupt();

// Read current state of port A (sensor pins).
uint8_t mcp23017_read_sensors();
