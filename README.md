# Test and Calibration Track

Automated locomotive test and calibration system for HO model railroad. An ESP32 with 16 optical sensors measures actual locomotive speed across all 126 DCC speed steps, producing a calibrated speed table for each locomotive in the fleet.

## What It Does

Place a locomotive on the test track, enter its DCC address, and walk away. The system:

1. Finds the minimum speed step that produces movement (binary search, ~2 minutes)
2. Sweeps through all speed steps, measuring actual speed at each one
3. Records drawbar pull via load cell (tractive effort)
4. Captures vibration signature (mechanism health triage)
5. Measures decoder audio level (volume consistency across fleet)
6. Outputs a calibration JSON and optionally imports it into the JMRI roster

A full calibration run takes ~5-10 minutes per locomotive.

## Why

- **Consisting**: Speed-match locomotives with different decoders for smooth MU operation
- **Warrants & dispatcher**: JMRI uses measured speed profiles for accurate block timing and braking distances
- **Position tracking**: Know actual velocity from commanded speed step for continuous position estimation
- **Fleet triage**: Vibration and audio analysis flags mechanisms that need service and decoders with wrong volume settings

## Current Status

**Phase 1 prototype running.** Firmware v0.3 on ESP32 WROOM-32 with MCP23017 GPIO expander. WiFi web UI, MQTT integration, and JMRI throttle bridge all functional. Awaiting TCRT5000 sensor breakout boards to complete detection testing.

See [Implementation Status](#implementation-status) below for phase details.

## Hardware

### Track
- 72" (1829mm) of Code 70 flex track on 1/4" plywood base
- Dead level, straight, bumpers at each end
- Load cell at one end for drawbar pull measurement

### Sensor Array
- 16x TCRT5000 reflective optical sensors at 100mm (~4") spacing
- 1500mm (59") sensor span with run-up room at each end
- Sensors mounted in 3D-printed plugs pressed into holes in the plywood base
- MCP23017 I2C GPIO expander handles all 16 sensor inputs
- Phase 1 prototype uses 4 sensors on breadboard

### Electronics
- ESP32 WROOM-32 DevKit — mounts under the track, communicates via WiFi/MQTT
- MCP23017 (I2C address 0x27) + sensor breakout boards (LM393, digital output)
- HX711 ADC + 500g beam load cell for tractive effort
- INMP441 MEMS microphone for decoder audio level
- 27mm piezoelectric disc for mechanism vibration

### Bill of Materials

| Qty | Part | Purpose | Status |
|-----|------|---------|--------|
| 16 | TCRT5000 LM393 breakout | Speed detection | Ordered (20x) |
| 1 | ESP32 WROOM-32 DevKit | Controller | In use |
| 1 | MCP23017 breakout | 16-ch GPIO expander | In use |
| 1 | 500g beam load cell | Drawbar pull | Ordered |
| 1 | HX711 breakout | Load cell ADC | Ordered |
| 1 | INMP441 breakout | Decoder audio level | Ordered |
| 1 | 27mm piezo disc | Vibration sensing | Check |
| 1 | PCB or perfboard | Main board | Phase 2 |

## Software

### Firmware (ESP32)
- PlatformIO / Arduino framework
- Interrupt-driven sensor timestamps via MCP23017 INT pin (GPIO 13)
- Speed calculation from sensor transit times with direction detection
- WiFi AP+STA mode with captive portal and NVS credential storage
- Web UI with real-time WebSocket status, arm/disarm controls, WiFi and MQTT config
- MQTT publish of results and status; subscribes to arm/stop/status commands
- 13 native unit tests for speed calculation (runs on desktop, no hardware needed)

### JMRI Throttle Bridge
- `scripts/jmri_throttle_bridge.py` — Jython script that runs inside JMRI
- Subscribes to MQTT command topics, translates to DCC throttle calls via SPROG
- Requires JMRI with both SPROG and MQTT connections configured

### Loco Control CLI
- `scripts/loco_control.py` — Python CLI for interactive locomotive control
- Acquire throttle, set speed/direction, arm sensors, shuttle back and forth
- Useful for testing on roller track

### Orchestration Script (Planned)
- `scripts/calibrate_speed.py` — automated calibration sweep
- Controls locomotive via JMRI throttle bridge
- Collects measurement results from ESP32
- Outputs calibration JSON per locomotive

### JMRI Integration (Planned)
- `scripts/import_speed_profile.py` — Jython script for JMRI
- Imports calibration data into JMRI RosterSpeedProfile
- Speed data consumed by warrants, dispatcher, throttle display

## Architecture

```
                                    WiFi/MQTT
┌──────────────┐    MQTT    ┌──────────────────┐    DCC
│  Calibration ├───────────►│      JMRI        ├──────────► Track
│   Script     │◄───────────│  (throttle ctrl)  │           Power
│  (Python)    │            └──────────────────┘
│              │    MQTT
│              ├───────────►┌──────────────────┐
│              │◄───────────│  ESP32 under      │
└──────────────┘            │  test track       │
                            │                   │
                            │  MCP23017 ← 16x TCRT5000
                            │  HX711   ← load cell
                            │  I2S     ← INMP441 mic
                            │  ADC     ← piezo disc
                            └──────────────────┘
```

## Project Structure

```
firmware/           PlatformIO project (ESP32)
  include/          Header files
  src/              Implementation
  data/             LittleFS web UI (index.html)
  test/             Unit tests (native desktop)
docs/               Specifications and design documents
scripts/            JMRI bridge and orchestration scripts
hardware/
  kicad/            PCB design files
  3d-prints/        Sensor plug and bracket designs
calibration-data/   Output files from calibration runs (gitignored)
```

## Getting Started

### Build & Flash
```bash
cd firmware

# Compile
~/.platformio/penv/bin/pio run

# Flash firmware
~/.platformio/penv/bin/pio run -t upload

# Upload web UI
~/.platformio/penv/bin/pio run -t uploadfs

# Serial monitor
~/.platformio/penv/bin/pio device monitor

# Run unit tests (no hardware needed)
~/.platformio/penv/bin/pio test -e native
```

### Connect
1. ESP32 creates WiFi AP "SpeedCal" on first boot
2. Connect to AP, open `http://192.168.4.1`
3. Configure home WiFi via web UI (device reboots to STA mode)
4. Configure MQTT broker via web UI
5. Arm sensors via web UI or MQTT

### JMRI Setup
1. Add MQTT connection in JMRI: Edit > Preferences > Connections (same broker, blank channel prefix)
2. Keep SPROG as default for Throttle in Preferences > Defaults
3. Run `scripts/jmri_throttle_bridge.py` via Scripting > Run Script
4. Control from `scripts/loco_control.py`:
   ```bash
   pip3 install paho-mqtt
   python3 scripts/loco_control.py --broker 192.168.68.250 --address 3
   ```

See [docs/SPEED_CALIBRATION_SPEC.md](docs/SPEED_CALIBRATION_SPEC.md) for the full system specification.

## Implementation Status

- [x] Phase 1: Hardware build & basic detection (4 sensors on breadboard prototype)
- [ ] Phase 2: Full 16-sensor PCB + MCP23017 interrupt timing
- [x] Phase 3: MQTT integration & speed calculation firmware
- [ ] Phase 4: Orchestration script (start-of-motion + full sweep)
- [ ] Phase 5: Load cell (drawbar pull measurement)
- [ ] Phase 6: Vibration & audio analysis
- [ ] Phase 7: JMRI roster integration
- [ ] Phase 8: Fleet calibration

## Related Projects

- [esp32-config](../esp32-config/) — MQTT device control firmware (shared infrastructure patterns)
- [track_geometry_car](../track_geometry_car/) — Instrumented HO car for track quality surveying
- [JMRI](http://jmri.org/) — Java Model Railroad Interface

## License

MIT
