# Speed Calibration Tools

Automated locomotive speed calibration, drawbar pull measurement, and audio
analysis for HO model railroad. Works with JMRI and an ESP32 sensor array.

## What's Here

```
~/speed-cal/
  calibrate          Launcher: automated calibration sweep
  loco               Launcher: interactive loco control CLI
  scripts/           Python modules
    calibrate_speed.py   Automated speed step sweep with multi-pass averaging
    loco_control.py      Interactive CLI for manual testing
    calibration_db.py    SQLite database for storing calibration results
  jmri/
    jmri_throttle_bridge.py   Runs inside JMRI, translates MQTT to DCC throttle
  calibration-data/   Output directory for calibration results (JSON + SQLite)
  README.md           This file
```

## Prerequisites

- **JMRI** installed in `/Applications/JMRI`
- **SPROG** (or other DCC command station) connected and working
- **Mosquitto** MQTT broker running (typically on the same machine or LAN)
- **ESP32 sensor array** powered and connected to the same MQTT broker
- **Python 3** with `paho-mqtt` (installed automatically by `install.sh`)

## Setup

### 1. JMRI Configuration

JMRI needs two connections configured in **Edit > Preferences > Connections**:

1. **SPROG** (or your command station) — set as default for **Throttle** in
   Preferences > Defaults
2. **MQTT** — pointing at the same Mosquitto broker the ESP32 uses.
   Set the channel prefix to blank (default since JMRI 5.1.2).

### 2. Load the Throttle Bridge

Every time you start JMRI for calibration work:

1. **Scripting > Run Script**
2. Select `~/speed-cal/jmri/jmri_throttle_bridge.py`
3. The JMRI script output window will show "Throttle bridge started"

The bridge runs as a background thread inside JMRI. It subscribes to MQTT
command topics and translates them into DCC throttle commands.

### 3. ESP32 Sensor Array

Make sure the ESP32 is:
- Powered on and connected to WiFi
- Connected to the same MQTT broker
- Sensor array positioned on the calibration track

You can check ESP32 status at its web UI (find its IP via your router or
the serial console).

## Usage

### Interactive Loco Control

For manual testing — put a loco on the track and drive it:

```bash
~/speed-cal/loco --address 3 --broker 192.168.68.250
```

Commands at the prompt:
- `speed N` — set speed step (0-126)
- `forward` / `reverse` — set direction
- `stop` — speed 0
- `estop` — emergency stop
- `arm` — arm sensors for a speed measurement
- `tare` — zero the load cell
- `load` — read drawbar pull
- `vib` — capture vibration sample
- `audio` — capture audio sample
- `quit` — release throttle and exit

### Automated Calibration Sweep

Full calibration run — finds start-of-motion, sweeps all speed steps:

```bash
# Basic run
~/speed-cal/calibrate --address 3 --broker 192.168.68.250

# With JMRI roster ID (for database storage)
~/speed-cal/calibrate --address 3 --roster-id "SP 4449" --broker 192.168.68.250

# Dry run (no MQTT, preview what would happen)
~/speed-cal/calibrate --address 3 --dry-run

# Skip start-of-motion search, start from step 10
~/speed-cal/calibrate --address 3 --skip-start-of-motion --min-step 10
```

Results are saved to:
- `~/speed-cal/calibration-data/` — JSON files per run
- `~/speed-cal/calibration-data/calibration.db` — SQLite database with all runs

### MQTT Broker

The default broker address is `localhost`. Override with `--broker`:

```bash
~/speed-cal/loco --broker 192.168.68.250 --address 3
```

The ESP32, JMRI, and these scripts all need to reach the same broker.

## Troubleshooting

**"paho-mqtt not installed"**
```bash
python3 -m pip install --user paho-mqtt
```

**Throttle bridge not responding**
- Check JMRI script output window for errors
- Verify MQTT connection is active in JMRI (Edit > Preferences > Connections)
- Check broker is reachable: `mosquitto_sub -h 192.168.68.250 -t '#' -v`

**No sensor readings**
- Check ESP32 web UI for MQTT connection status
- Verify sensors are armed (`arm` command in loco CLI)
- Check ESP32 serial console for errors

**Calibration data location**
All results are stored in `~/speed-cal/calibration-data/`. The SQLite database
(`calibration.db`) accumulates data across runs. JSON files are one-per-run.

## Updating

To update to a newer version, re-run `install.sh` from the source repo.
Your calibration data in `~/speed-cal/calibration-data/` is preserved.
