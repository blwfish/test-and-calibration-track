# Test and Calibration Track

Automated locomotive test and calibration system for HO model railroad.
ESP32 + 16 TCRT5000 optical sensors measure speed across full DCC speed step range,
plus load cell (drawbar pull), vibration (mechanism health), and audio (decoder volume).

## Project Structure

```
firmware/           PlatformIO project (ESP32, Arduino framework)
  include/          Header files (config.h, pin assignments)
  src/              Implementation (.cpp files)
  data/             LittleFS web UI (index.html served to browser)
  test/             Unit tests (native desktop, no hardware needed)
    stubs/          Arduino.h stub for native compilation
    test_speed_calc/  Speed calculation tests (13 cases)
docs/               Specifications and design documents
scripts/            JMRI bridge and orchestration scripts
  jmri_throttle_bridge.py   Jython script for JMRI (MQTT→DCC throttle)
  loco_control.py           Python CLI for loco control and testing
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

# Upload web UI filesystem (must do after changing data/index.html)
~/.platformio/penv/bin/pio run -t uploadfs

# Serial monitor (115200 baud, bidirectional)
~/.platformio/penv/bin/pio device monitor

# Run native unit tests (no hardware needed)
~/.platformio/penv/bin/pio test -e native
```

## Hardware

- **MCU**: ESP32-WROOM-32 devkit (wide form factor, female jumper wires)
- **Sensors**: 16x TCRT5000 reflective optical sensors at 100mm spacing
  - Phase 1 prototype: 4 sensors on breadboard
  - Using LM393 breakout boards (no trimpot, digital output)
- **GPIO expander**: MCP23017 (I2C address 0x27, all addr pins HIGH)
- **Load cell**: 500g beam cell + HX711 ADC (drawbar pull measurement)
- **Vibration**: 27mm piezoelectric disc on ADC1 (mechanism health)
- **Audio**: INMP441 MEMS microphone on I2S0 (decoder volume)
- **Track**: 72" (1829mm) Code 70 flex track on 1/4" plywood base
- **Scale**: HO (1:87.1)

### Pin Budget

| Function | Pins | Notes |
|----------|------|-------|
| I2C (MCP23017) | SDA=GPIO 21, SCL=GPIO 22 | 400kHz, no external pullups needed |
| MCP23017 INT | GPIO 13 | Interrupt on sensor change (moved from GPIO 4, strapping pin) |
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

Default config: prefix=`/cova`, name=`speed-cal`, broker port 1883.
Configurable via web UI at `/api/mqtt` or NVS.

### JMRI Throttle Bridge Topics

| Topic | Direction | Description |
|-------|-----------|-------------|
| `/cova/speed-cal/throttle/acquire` | to JMRI | Acquire throttle: "ADDRESS [L\|S]" |
| `/cova/speed-cal/throttle/speed` | to JMRI | Set speed: "0.0" to "1.0" |
| `/cova/speed-cal/throttle/direction` | to JMRI | "FORWARD" or "REVERSE" |
| `/cova/speed-cal/throttle/stop` | to JMRI | Stop (speed=0) |
| `/cova/speed-cal/throttle/estop` | to JMRI | Emergency stop |
| `/cova/speed-cal/throttle/release` | to JMRI | Release throttle |
| `/cova/speed-cal/throttle/status` | from JMRI | Status/ack messages |

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
- **GPIO 13 for MCP23017 INT** — GPIO 4 is a strapping pin that interferes with
  flash upload when connected.
- **No I2C pullups needed** — MCP23017 breakout board has them on-board.
- **TCRT5000 breakout boards (LM393)** — digital output, no trimpot, built-in
  pullups. Bare TCRT5000 sensors would need external resistor networks.

## JMRI Integration

Requires JMRI with two connections configured:
1. **SPROG** (or other DCC command station) — default for Throttle
2. **MQTT** — same Mosquitto broker as ESP32, blank channel prefix

Run `scripts/jmri_throttle_bridge.py` inside JMRI (Scripting > Run Script).
It subscribes to MQTT command topics and translates to DCC throttle calls.

## Orchestration

`scripts/loco_control.py` — interactive CLI for testing:
```bash
pip3 install paho-mqtt
python3 scripts/loco_control.py --broker 192.168.68.250 --address 3
```

`scripts/calibrate_speed.py` (future) runs on any machine with MQTT access:
1. Binary search for start-of-motion threshold
2. Sweep speed steps, arm sensors, collect results
3. Output calibration JSON
4. Optionally import into JMRI roster via Jython script

## Related Projects

- **esp32-config** — shares MQTT infrastructure and MCP23017 patterns
- **track_geometry_car** — similar ESP32+sensor instrumentation approach
- **JMRI** — provides DCC throttle control and roster speed profiles

## Implementation Status

- [x] Phase 1: Hardware build & basic detection (4 sensors on breadboard prototype)
- [ ] Phase 2: Full 16-sensor PCB + MCP23017 interrupt timing
- [x] Phase 3: MQTT integration & speed calculation firmware
- [ ] Phase 4: Orchestration script (start-of-motion + full sweep)
- [ ] Phase 5: Load cell (drawbar pull measurement)
- [ ] Phase 6: Vibration & audio analysis
- [ ] Phase 7: JMRI roster integration
- [ ] Phase 8: Fleet calibration

### Phase 1 Status (current)
- Firmware v0.3 running on ESP32 WROOM-32
- MCP23017 at 0x27 responding, interrupt-driven detection working
- WiFi AP+STA mode with captive portal and NVS credential storage
- Web UI with real-time WebSocket status, arm/disarm, WiFi config, MQTT config
- MQTT connected to Mosquitto broker, subscribes to arm/stop/status commands
- Speed calculation with direction detection and per-interval analysis
- 13 native unit tests passing (speed_calc)
- JMRI Jython throttle bridge script ready
- Python loco control CLI ready
- Waiting for TCRT5000 LM393 breakout boards (sensors currently floating)
