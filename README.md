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

### Electronics
- ESP32 DevKit — mounts under the track, communicates via WiFi/MQTT
- MCP23017 + 16x 10k pullup resistors for sensor inputs
- HX711 ADC + 500g beam load cell for tractive effort
- INMP441 MEMS microphone for decoder audio level
- 27mm piezoelectric disc for mechanism vibration
- Single PCB (~60x80mm) carries all electronics

### Bill of Materials

| Qty | Part | Purpose | Have? |
|-----|------|---------|-------|
| 16 | TCRT5000 | Speed detection | Yes (box of 60) |
| 1 | ESP32 DevKit | Controller | Yes |
| 1 | MCP23017 | 16-ch GPIO expander | Yes |
| 16 | 10k resistor | Sensor pullups | Yes |
| 2 | 4.7k resistor | I2C pullups | Yes |
| 1 | 500g beam load cell | Drawbar pull | Ordered |
| 1 | HX711 breakout | Load cell ADC | Ordered |
| 1 | INMP441 breakout | Decoder audio level | Ordered |
| 1 | 27mm piezo disc | Vibration sensing | Check |
| 3 | Resistors + cap | Piezo conditioning | Probably |
| 1 | PCB or perfboard | Main board | Yes |
| 2 | Code 70 flex track | Test track (72") | Yes |
| 1 | 1/4" plywood | Track base | Yes |

## Software

### Firmware (ESP32)
- PlatformIO / Arduino framework
- Interrupt-driven sensor timestamps via MCP23017 INT pin
- Speed calculation from sensor transit times
- MQTT publish of results (speed, vibration, audio, load)
- Arm/measure/publish cycle controlled by orchestration script

### Orchestration Script (Python)
- `scripts/calibrate_speed.py` — runs on any machine with MQTT access
- Controls locomotive via JMRI MQTT throttle interface
- Collects measurement results from ESP32
- Outputs calibration JSON per locomotive

### JMRI Integration
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
  test/             Unit tests
docs/               Specifications and design documents
scripts/            Python orchestration and JMRI integration
hardware/
  kicad/            PCB design files
  3d-prints/        Sensor plug and bracket designs
calibration-data/   Output files from calibration runs (gitignored)
```

## Getting Started

### Phase 1: Prototype (Current)
1. Wire 4 TCRT5000 sensors + MCP23017 on perfboard
2. Mount sensors in test section of track
3. Validate sensor triggering and timing
4. Basic firmware: arm, detect, compute speed, publish via MQTT

See [docs/SPEED_CALIBRATION_SPEC.md](docs/SPEED_CALIBRATION_SPEC.md) for the full system specification.

## Related Projects

- [esp32-config](../esp32-config/) — MQTT device control firmware (shared infrastructure patterns)
- [track_geometry_car](../track_geometry_car/) — Instrumented HO car for track quality surveying
- [JMRI](http://jmri.org/) — Java Model Railroad Interface

## License

MIT
