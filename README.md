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

**v0.7 — Firmware and software feature-complete through Phase 7b.** ESP32 WROOM-32 with MCP23017 GPIO expander, HX711 load cell, INMP441 microphone, and piezo vibration sensor. WiFi web UI with real-time WebSocket status, MQTT integration, JMRI throttle bridge with roster/CV support, automated calibration sweep with SQLite storage, and audio calibration for fleet volume matching. 43 native C++ tests + 89 Python tests passing. Awaiting TCRT5000 sensor breakout boards and remaining hardware for full integration testing.

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
- HX711 load cell driver (bit-banged, EMA smoothing, tare, NVS calibration factor)
- Piezo vibration capture (ADC, peak-to-peak and RMS analysis)
- INMP441 audio capture (I2S, RMS dB and peak dB analysis)
- Automated pull test state machine: tare → settle → vib → audio → read → advance
- Track safety switch sensing (layout/prog + DCC/DC) with configurable interlocks
- WiFi AP+STA mode with captive portal and NVS credential storage
- Web UI with real-time WebSocket status, throttle control, pull test sweep, WiFi/MQTT config
- MQTT publish of results and status; subscribes to arm/stop/status/tare/load/vibration/audio
- 43 native unit tests (speed_calc: 13, load_cell: 9, vibration: 10, audio: 11)

### JMRI Throttle Bridge
- `scripts/jmri_throttle_bridge.py` — Jython script that runs inside JMRI
- Subscribes to MQTT command topics, translates to DCC throttle calls via SPROG
- Roster query, speed profile import, CV read/write over MQTT
- Requires JMRI with both SPROG and MQTT connections configured

### Loco Control CLI
- `scripts/loco_control.py` — Python CLI for interactive locomotive control
- Acquire throttle, set speed/direction, arm sensors, shuttle back and forth
- Roster query, CV read/write, sensor commands
- Useful for testing on roller track

### Calibration Sweep
- `scripts/calibrate_speed.py` — automated calibration sweep
- Binary search for start-of-motion threshold, full speed step sweep
- Multi-pass averaging at low speeds, optional audio capture
- Stores results in SQLite database and JSON files
- Auto-imports speed profile into JMRI roster

### Audio Calibration
- `scripts/audio_calibrate.py` — match decoder volume to fleet reference
- Decoder volume CV lookup (LokSound 5, Tsunami2, Econami, Digitrax, BLI, TCS)
- dB-to-CV computation with optional auto-apply via JMRI CV write

### Calibration Database
- `scripts/calibration_db.py` — SQLite storage for all calibration data
- Schema v2 with consist support for multi-decoder locos
- 89 Python tests (calibration_db: 34, jmri_bridge: 21, audio_calibrate: 34)

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
  include/          Header files (config.h, pin assignments)
  src/              Implementation (.cpp files)
  data/             LittleFS web UI (index.html)
  test/             Unit tests (native desktop, 43 tests)
docs/               Specifications and design documents
scripts/            JMRI bridge, orchestration, and calibration scripts
  requirements.txt  Python dependencies
hardware/
  kicad/            PCB design files
  3d-prints/        Sensor plug and bracket designs
calibration-data/   Output JSON + SQLite database (gitignored)
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
   pip3 install -r scripts/requirements.txt
   python3 scripts/loco_control.py --broker 192.168.68.250 --address 3
   ```

See [docs/SPEED_CALIBRATION_SPEC.md](docs/SPEED_CALIBRATION_SPEC.md) for the full system specification.

## Implementation Status

- [x] Phase 1: Hardware build & basic detection (4 sensors on breadboard prototype)
- [ ] Phase 2: Full 16-sensor PCB + MCP23017 interrupt timing
- [x] Phase 3: MQTT integration & speed calculation firmware
- [x] Phase 4: Orchestration script (start-of-motion + full sweep) — software ready, needs hardware test
- [x] Phase 5: Load cell (drawbar pull measurement) — firmware ready, needs hardware test
- [x] Phase 6: Vibration & audio analysis — firmware ready, needs hardware test
- [x] Phase 6b: Automated pull + vibration + audio sweep with web UI
- [x] Phase 6c: Calibration database (SQLite, schema v2 with consist support)
- [x] Phase 6d: Track safety switches with interlocks
- [x] Phase 7: JMRI roster integration (roster query, speed profile import, CV read/write)
- [x] Phase 7b: Audio calibration (fleet volume matching, decoder CV lookup)
- [ ] Phase 8: Fleet calibration

## Related Projects

- [esp32-config](../esp32-config/) — MQTT device control firmware (shared infrastructure patterns)
- [track_geometry_car](../track_geometry_car/) — Instrumented HO car for track quality surveying
- [JMRI](http://jmri.org/) — Java Model Railroad Interface

## License

MIT
