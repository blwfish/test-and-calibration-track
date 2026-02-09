# Test and Calibration Track

Automated locomotive test and calibration system for HO model railroad.
ESP32 + 16 TCRT5000 optical sensors measure speed across full DCC speed step range,
plus load cell (drawbar pull), vibration (mechanism health), and audio (decoder volume).

## Project Structure

```
firmware/           PlatformIO project (ESP32, Arduino framework)
  include/          Header files (config.h, pin assignments)
  src/              Implementation (.cpp files)
  data/             LittleFS web UI (future)
  test/             Unit tests (native + embedded)
docs/               Specifications and design documents
scripts/            Python orchestration and JMRI integration scripts
hardware/
  kicad/            PCB design files
  3d-prints/        Sensor plug and bracket STL/STEP files
calibration-data/   Output JSON files from calibration runs (gitignored)
```

## Build Commands

All PlatformIO commands run from `firmware/`:

```bash
# Compile firmware
~/.platformio/penv/bin/pio run

# Flash firmware to ESP32
~/.platformio/penv/bin/pio run -t upload

# Serial monitor (115200 baud)
~/.platformio/penv/bin/pio device monitor

# Run native unit tests (no hardware needed)
~/.platformio/penv/bin/pio test -e native
```

## Hardware

- **MCU**: ESP32-WROOM-32 devkit
- **Sensors**: 16x TCRT5000 reflective optical sensors at 100mm spacing
- **GPIO expander**: MCP23017 (I2C, handles all 16 sensor inputs)
- **Load cell**: 500g beam cell + HX711 ADC (drawbar pull measurement)
- **Vibration**: 27mm piezoelectric disc on ADC1 (mechanism health)
- **Audio**: INMP441 MEMS microphone on I2S0 (decoder volume)
- **Track**: 72" (1829mm) Code 70 flex track on 1/4" plywood base
- **Scale**: HO (1:87.1)

### Pin Budget

| Function | Pins | Notes |
|----------|------|-------|
| I2C (MCP23017) | SDA=GPIO 21, SCL=GPIO 22 | 400kHz, 4.7k pullups |
| MCP23017 INT | GPIO 4 | Interrupt on sensor change |
| HX711 load cell | GPIO 16 (DOUT), GPIO 17 (SCK) | Bit-banged |
| Piezo ADC | GPIO 36 (VP) | ADC1 only (ADC2 conflicts with WiFi) |
| INMP441 mic | GPIO 18 (SCK), 19 (WS), 23 (SD) | I2S0 input |
| UART0 (console) | GPIO 1, 3 | Reserved |

Sensor pins are on MCP23017 GPA0-GPA7, GPB0-GPB7 with 10k external pullups.

## MQTT Interface

All topics under `{prefix}/speed-cal/{name}/`:

| Topic suffix | Direction | Description |
|-------------|-----------|-------------|
| `arm` | to ESP32 | Arm sensors for next pass |
| `stop` | to ESP32 | Cancel/disarm |
| `status` | to ESP32 | Request status |
| `result` | from ESP32 | Speed measurement JSON |
| `vibration` | from ESP32 | Vibration analysis JSON |
| `audio` | from ESP32 | Audio level JSON |
| `load` | from ESP32 | Load cell reading JSON |
| `error` | from ESP32 | Error report |

## Key Design Decisions

- **MCP23017 for sensors** rather than direct GPIO: frees pin budget for HX711,
  INMP441, piezo. INT pin provides hardware-timed trigger; I2C read identifies
  which sensor fired.
- **100mm sensor spacing** over 1500mm span (16 sensors): 15 intervals per pass
  for good averaging, ample low-speed resolution, fits within 72" track with
  run-up room at each end.
- **ESP32 mounts under the track** with everything on one board. All communication
  is WiFi/MQTT — no wired connection to host.
- **Firmware is measurement-only.** Locomotive control (throttle, direction) is
  handled by the orchestration script via JMRI MQTT. ESP32 arms, measures, publishes.

## Orchestration

`scripts/calibrate_speed.py` runs on any machine with MQTT access:
1. Binary search for start-of-motion threshold
2. Sweep speed steps, arm sensors, collect results
3. Output calibration JSON
4. Optionally import into JMRI roster via Jython script

## Related Projects

- **esp32-config** — shares MQTT infrastructure and MCP23017 patterns
- **track_geometry_car** — similar ESP32+sensor instrumentation approach
- **JMRI** — provides DCC throttle control and roster speed profiles

## Implementation Status

- [ ] Phase 1: Hardware build & basic detection (4 sensors on perfboard prototype)
- [ ] Phase 2: Full 16-sensor PCB + MCP23017 interrupt timing
- [ ] Phase 3: MQTT integration & speed calculation firmware
- [ ] Phase 4: Orchestration script (start-of-motion + full sweep)
- [ ] Phase 5: Load cell (drawbar pull measurement)
- [ ] Phase 6: Vibration & audio analysis
- [ ] Phase 7: JMRI roster integration
- [ ] Phase 8: Fleet calibration
