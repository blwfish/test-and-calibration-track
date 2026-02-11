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
    test_load_cell/   Load cell conversion tests (9 cases)
    test_vibration/   Vibration analysis tests (10 cases)
    test_audio/       Audio dB conversion tests (11 cases)
docs/               Specifications and design documents
scripts/            JMRI bridge and orchestration scripts
  jmri_throttle_bridge.py   Jython script for JMRI (MQTT→DCC throttle + roster + CV)
  loco_control.py           Python CLI for loco control, roster queries, CV programming
  calibrate_speed.py        Automated speed calibration sweep with JMRI auto-import
  calibration_db.py         SQLite database for calibration data
  jmri_config.py            Auto-detect MQTT broker/prefix from JMRI profile XML
  audio_calibrate.py        Match decoder volume to fleet reference via CV adjustment
  decoder_volume.py         Decoder volume CV knowledge base (LokSound, Tsunami2, etc.)
  test_calibration_db.py    Tests for calibration_db (34 cases)
  test_jmri_bridge.py       Tests for JMRI bridge protocol + config reader (21 cases)
  test_audio_calibrate.py   Tests for audio calibration + decoder lookup (34 cases)
hardware/
  kicad/            PCB design files
  3d-prints/        Sensor plug and bracket STL/STEP files
calibration-data/   Output JSON + SQLite database from calibration runs (gitignored)
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
| Track SW1 | GPIO 25 | Layout/Prog switch sense (HIGH = prog) |
| Track SW2 | GPIO 26 | DCC/DC switch sense (HIGH = DC) |
| UART0 (console) | GPIO 1, 3 | Reserved |

Sensor pins are on MCP23017 GPA0-GPA7, GPB0-GPB7 with 10k external pullups.

## MQTT Interface

All topics under `{prefix}/speed-cal/{name}/`:

| Topic suffix | Direction | Description |
|-------------|-----------|-------------|
| `arm` | to ESP32 | Arm sensors for next pass |
| `stop` | to ESP32 | Cancel/disarm |
| `status` | to/from ESP32 | Request/publish status |
| `tare` | to ESP32 | Tare (zero) load cell |
| `load` | to/from ESP32 | Request/publish load cell reading |
| `vibration` | to/from ESP32 | Start capture / publish analysis |
| `audio` | to/from ESP32 | Start capture / publish analysis |
| `result` | from ESP32 | Speed measurement JSON |
| `pull_test` | from ESP32 | Pull test results JSON |
| `track_mode` | from ESP32 | Track switch mode JSON |
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

### JMRI Roster & CV Topics

| Topic | Direction | Description |
|-------|-----------|-------------|
| `/cova/speed-cal/roster/query` | to JMRI | Query roster: JSON `{"roster_id"}` or `{"address"}` |
| `/cova/speed-cal/roster/info` | from JMRI | Roster query result: JSON with entries |
| `/cova/speed-cal/roster/import_profile` | to JMRI | Import speed profile: JSON with speed entries |
| `/cova/speed-cal/roster/import_status` | from JMRI | Import result: JSON `{"success", "entries_imported"}` |
| `/cova/speed-cal/cv/read` | to JMRI | Read CV: JSON `{"cv": N}` or `{"cvs": [...]}` |
| `/cova/speed-cal/cv/write` | to JMRI | Write CV: JSON `{"cv": N, "value": V}` |
| `/cova/speed-cal/cv/result` | from JMRI | CV result: JSON `{"cv", "value", "status"}` |

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
- **Track safety switches (optional)** — two 3PDT switches (SW1: layout/prog,
  SW2: DCC/DC) with 3rd pole to GPIO 25/26 for sensing. Three derived modes:
  LAYOUT (blocks all operations), PROG_DCC (normal calibration), PROG_DC
  (mechanical testing only, DCC disabled). Configurable via NVS — all interlocks
  bypass when switches not installed.

## JMRI Integration

Requires JMRI with two connections configured:
1. **SPROG** (or other DCC command station) — default for Throttle
2. **MQTT** — same Mosquitto broker as ESP32, blank channel prefix

Run `scripts/jmri_throttle_bridge.py` inside JMRI (Scripting > Run Script).
It subscribes to MQTT command topics and translates to DCC throttle calls,
roster queries, speed profile imports, and CV read/write operations.

## Orchestration

MQTT broker address, port, and topic prefix are auto-detected from the JMRI
profile XML (`~/.jmri/...profile.xml`). CLI flags `--broker`, `--port`,
`--prefix` override auto-detection.

`scripts/loco_control.py` — interactive CLI for testing:
```bash
pip3 install paho-mqtt
python3 scripts/loco_control.py --address 3
python3 scripts/loco_control.py --broker 192.168.68.250 --address 3  # manual override
```

`scripts/calibrate_speed.py` — automated calibration sweep:
```bash
python3 scripts/calibrate_speed.py --address 3 --roster-id "SP 4449"
python3 scripts/calibrate_speed.py --address 3 --dry-run  # preview without MQTT
python3 scripts/calibrate_speed.py --address 3 --no-import-profile  # skip JMRI import
python3 scripts/calibrate_speed.py --address 3 --roster-id "SP 4449" --audio  # capture audio
python3 scripts/calibrate_speed.py --address 3 --roster-id "SP 4449" --compare-audio  # + compare
```
1. Binary search for start-of-motion threshold (forward & reverse)
2. Sweep speed steps with multi-pass averaging at low speeds
3. Optional audio capture at each step (`--audio`)
4. Output calibration JSON to `calibration-data/`
5. Store results in SQLite database (`calibration-data/calibration.db`)
6. Auto-import speed profile into JMRI roster (when `--roster-id` given)
7. Shuttle track: alternates direction each pass

`scripts/audio_calibrate.py` — match decoder volume to fleet reference:
```bash
python3 scripts/audio_calibrate.py --set-reference "SP 4449"   # designate reference
python3 scripts/audio_calibrate.py --list                      # fleet audio overview
python3 scripts/audio_calibrate.py --roster-id "UP 844"        # show recommendation
python3 scripts/audio_calibrate.py --roster-id "UP 844" --apply  # write CV
python3 scripts/audio_calibrate.py --roster-id "UP 844" --dry-run  # preview only
```
Compares target loco audio levels to fleet reference, looks up decoder volume CV
(LokSound 5: CV 63, Tsunami2/Econami: CV 128, Digitrax: CV 58, BLI: CV 161,
TCS: CV 128), and computes/applies the adjustment.

## Calibration Database

SQLite database (`calibration-data/calibration.db`) stores all calibration data,
keyed by JMRI roster ID for joining with DecoderPro roster entries.

Tables: `locos`, `consist_members`, `calibration_runs`, `speed_entries`, `motion_thresholds`, `audio_adjustments`

Consist support: multi-decoder locos (e.g. VGN Triplex with 3 decoders) can be
defined with `set_consist()`. Pull tests run on the consist as a whole; audio
is measured per decoder individually, then adjusted per-member via
`member_address` on `audio_adjustments`. Schema v2 with migration from v1.

```python
from calibration_db import CalibrationDB
db = CalibrationDB()
db.get_or_create_loco("SP 4449", address=4449, decoder_type="LokSound 5")
runs = db.list_runs(roster_id="SP 4449")
entries = db.get_speed_entries(run_id)
delta = db.compare_audio_to_reference(test_run_id, ref_run_id)

# Consist support
db.set_consist("VGN Triplex", [
    {"member_address": 101, "role": "sound", "notes": "front engine"},
    {"member_address": 102, "role": "sound", "notes": "rear engine"},
    {"member_address": 103, "role": "silent", "notes": "center engine"},
])
db.add_audio_adjustment(run_id, ref_run_id, delta_db=2.5, member_address=101)
```

Run tests:
```bash
python3 scripts/test_calibration_db.py    # 34 calibration DB tests
python3 scripts/test_jmri_bridge.py       # 21 JMRI bridge/config tests
python3 scripts/test_audio_calibrate.py   # 34 audio calibration tests
```

## Related Projects

- **esp32-config** — shares MQTT infrastructure and MCP23017 patterns
- **track_geometry_car** — similar ESP32+sensor instrumentation approach
- **JMRI** — provides DCC throttle control and roster speed profiles

## Implementation Status

- [x] Phase 1: Hardware build & basic detection (4 sensors on breadboard prototype)
- [ ] Phase 2: Full 16-sensor PCB + MCP23017 interrupt timing
- [x] Phase 3: MQTT integration & speed calculation firmware
- [x] Phase 4: Orchestration script (start-of-motion + full sweep) — software ready, needs hardware test
- [x] Phase 5: Load cell (drawbar pull measurement) — firmware ready, needs hardware test
- [x] Phase 6: Vibration & audio analysis — firmware ready, needs hardware test
- [x] Phase 6b: Automated pull + vibration + audio sweep — firmware state machine + web UI
- [x] Phase 6c: Calibration database (SQLite) — stores all measurement data keyed by roster ID
- [x] Phase 6d: Consist support — multi-decoder locos, per-member audio adjustments, schema v2
- [x] Phase 6e: Track safety switches — layout/prog + DCC/DC sensing, interlocks, web UI
- [x] Phase 7: JMRI roster integration — roster query, speed profile import, CV read/write over MQTT
- [x] Phase 7b: Audio calibration — reference profiles, decoder CV lookup, fleet volume matching
- [ ] Phase 8: Fleet calibration

### Current Status (v0.7)
- Firmware v0.5 running on ESP32 WROOM-32
- MCP23017 at 0x27 responding, interrupt-driven detection working
- WiFi AP+STA mode with captive portal and NVS credential storage
- Web UI with real-time WebSocket status, arm/disarm, WiFi/MQTT config
- Web UI throttle control (speed slider, F0-F8 function buttons, direction, E-STOP)
- Web UI pull + vibration + audio sweep with progress bar and results table
- MQTT connected to Mosquitto broker, full command set (arm/stop/status/tare/load/vibration/audio)
- Speed calculation with direction detection and per-interval analysis
- HX711 load cell driver (bit-banged, EMA smoothing, tare support)
- Piezo vibration capture (ADC, peak-to-peak and RMS analysis)
- INMP441 audio capture (I2S, RMS dB and peak dB analysis)
- Automated pull test state machine: tare → settle → vib capture → audio capture → read → advance
- Track safety switch sensing: two 3PDT switches (layout/prog + DCC/DC) on GPIO 25/26
  - Three derived modes: LAYOUT, PROG_DCC, PROG_DC with safety interlocks
  - Web UI track mode badge, warning banners, button disabling
  - NVS-persistent enable/disable (bypasses all interlocks when switches not installed)
- JMRI roster integration (Phase 7):
  - Roster query via MQTT (by roster ID or DCC address, returns decoder info)
  - Speed profile import via MQTT (calibration results → JMRI RosterSpeedProfile)
  - CV read/write via MQTT (service mode, single + batch, with status feedback)
  - Auto-import after calibration sweep (when --roster-id given)
  - Auto-detect MQTT broker/port/prefix from JMRI profile XML
- Audio calibration (Phase 7b):
  - Audio capture during calibration sweep (--audio flag)
  - Fleet audio comparison with reference loco designation
  - Decoder volume CV lookup (LokSound 5, Tsunami2, Econami, Digitrax, BLI, TCS)
  - dB-to-CV computation and optional auto-apply
  - Volume grading: quiet/normal/loud/EXCESSIVE based on fleet statistics
- 43 native unit tests passing (speed_calc: 13, load_cell: 9, vibration: 10, audio: 11)
- 89 Python tests passing (calibration_db: 34, jmri_bridge: 21, audio_calibrate: 34)
- JMRI Jython throttle bridge with roster, CV, and speed profile import handlers
- Python loco control CLI with sensor, roster, and CV commands
- Automated calibration script with dry-run mode, JMRI auto-import, stores results in SQLite + JSON
- Calibration database (schema v2) with locos, consist_members, runs, speed_entries, motion_thresholds, audio_adjustments
- Calibration track replaces programming track (SPROG program track output)
- Install script for deploying to layout system (`install.sh`)
- Waiting for TCRT5000 LM393 breakout boards + HX711 + piezo + INMP441
