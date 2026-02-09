# Locomotive Speed Calibration System

## Overview

A dedicated calibration track with an array of optical sensors that measures the actual speed of locomotives across the full range of DCC speed steps. The system produces a speed table for each locomotive: a mapping from speed step to actual scale speed, plus acceleration and deceleration profiles.

This data enables:
- **Consisting:** Accurate speed-matching of locomotives with different decoders
- **Position tracking:** Knowing actual velocity from the commanded speed step allows continuous position estimation between block boundaries
- **Audio correlation:** Speed-dependent foreground audio (wheel/rail noise) matched to real locomotive velocity
- **Physics simulation:** Measured acceleration curves feed the steam throttle boiler model

## Design Principles

- Fully automated — operator places loco on track, selects address, walks away
- Uses existing esp32-config infrastructure (MQTT, sensor polling, configuration)
- Minimal hardware — TCRT5000 optical sensors already supported in firmware
- Results published via MQTT and stored for JMRI integration
- Non-destructive addition to existing firmware (new device type, no changes to existing code)

---

## Hardware

### Sensor Array

16 TCRT5000 reflective optical sensors mounted between the rails at known, fixed spacing along a straight section of track.

**Geometry:**
- Total track length: 72" (1829mm) — two pieces of Code 70 flex track on 1/4" plywood base
- Sensor spacing: 100mm (~4") apart
- Sensor array span: 1500mm (59") for 16 sensors
- Run-up room: ~150mm (6") at each end for bumpers and load cell
- Track must be dead level — any grade introduces gravity error

**Why 16 sensors at 100mm:**
- 15 intervals per pass for excellent averaging (standard error ~1.46x better than 8 sensors)
- Enough density to see acceleration within a single pass
- 100mm spacing keeps trigger-point uncertainty (<1mm) well below 2% of spacing
- 1500mm total span gives good accuracy at high speeds
- Redundancy — a missed detection on one or two sensors doesn't lose the run
- Only uses 16 of 60 available TCRT5000 sensors

**Mounting:**
- Each bare TCRT5000 is mounted in a 3D-printed cylindrical plug (high-speed resin)
- Plugs press-fit into 1/4" (6.35mm) holes drilled in the plywood base between the rails
- Sensor faces upward through the roadbed; ties cut at center if necessary for clearance
- Trigger when locomotive underframe passes overhead (reflective detection)

### Track Requirements

- 72" (1829mm) straight, level section — two pieces of Code 70 flex track
- 1/4" plywood base
- DCC power on the track (connected to command station via JMRI)
- No turnouts or curves within the sensor array
- Bumpers at each end; load cell mounted at one bumper end

### Electrical

- 16 TCRT5000 sensors wired to an MCP23017 I2C GPIO expander
- MCP23017 interrupt output (INTA or INTB) wired to ESP32 GPIO for hardware-timed triggers
- 10k external pullup resistor on each sensor input (MCP23017 internal pullups are too weak)
- 4.7k pullups on I2C bus (SDA, SCL)
- HX711 load cell ADC on two GPIO pins (bit-banged clock + data)
- ESP32 board mounts under the track — all communication via WiFi/MQTT
- Power via USB
- UART RX reserved for future RDM6300 RFID reader (not part of this spec)

### Pin Budget

| Function | Pins | Notes |
|----------|------|-------|
| I2C bus (MCP23017) | SDA=GPIO 21, SCL=GPIO 22 | 400kHz, 4.7k external pullups |
| MCP23017 INT | GPIO 4 | Interrupt on any sensor change — provides timestamp |
| HX711 load cell | GPIO 16 (DOUT), GPIO 17 (SCK) | Bit-banged protocol |
| Piezo vibration sensor | GPIO 36 (VP) | ADC1 input (ADC2 conflicts with WiFi) |
| INMP441 MEMS mic | GPIO 18 (SCK), 19 (WS), 23 (SD) | I2S0 input peripheral |
| WiFi | (internal) | |
| MQTT | (via WiFi) | |
| UART0 (console) | GPIO 1, 3 | Reserved |
| Future RFID (RDM6300) | 1 GPIO (UART RX) | Reserve but don't allocate yet |

Sensor assignment on MCP23017:

| MCP23017 Pin | Sensor |
|-------------|--------|
| GPA0 | Sensor 0 (nearest end A / load cell end) |
| GPA1 | Sensor 1 |
| GPA2 | Sensor 2 |
| GPA3 | Sensor 3 |
| GPA4 | Sensor 4 |
| GPA5 | Sensor 5 |
| GPA6 | Sensor 6 |
| GPA7 | Sensor 7 |
| GPB0 | Sensor 8 |
| GPB1 | Sensor 9 |
| GPB2 | Sensor 10 |
| GPB3 | Sensor 11 |
| GPB4 | Sensor 12 |
| GPB5 | Sensor 13 |
| GPB6 | Sensor 14 |
| GPB7 | Sensor 15 (nearest end B) |

---

## Firmware

### New Device Type

Add a speed calibration sensor array as a new device type within the existing esp32-config firmware architecture.

**New constants in `config.h`:**

```c
// Speed calibration
#define USE_SPEED_CAL -1000

#define SPEED_CAL_MAX_SENSORS 16
#define SPEED_CAL_DEFAULT_SPACING_MM 100
#define SPEED_CAL_DETECTION_TIMEOUT_MS 60000   // Max time to wait for a pass
#define SPEED_CAL_MIN_INTERVAL_US 1000         // Ignore re-triggers faster than 1ms
#define SPEED_CAL_HO_SCALE_FACTOR 87.1         // HO scale ratio
```

**New data structure:**

```c
struct speed_cal_t {
  int sensorCount;                              // Number of sensors (1-16)
  // Sensors are on MCP23017 GPA0-7, GPB0-7; no direct GPIO pins needed
  float sensorSpacingMm;                        // Distance between adjacent sensors
  float scaleFactor;                             // Model scale ratio (87.1 for HO)
  char mqttName[MAX_MQTT_NAME];                 // e.g., "speed-cal"

  // Runtime state
  volatile uint32_t timestamps[SPEED_CAL_MAX_SENSORS];  // micros() at each trigger
  volatile bool triggered[SPEED_CAL_MAX_SENSORS];        // Has this sensor fired?
  bool runActive;                               // Currently measuring a pass
  int direction;                                // Detected direction: +1 or -1
  uint32_t runStartTime;                        // millis() when first sensor fired
};
```

### Detection Logic

**Interrupt-driven timestamps via MCP23017:**
- MCP23017 INTA/INTB pin triggers ESP32 hardware interrupt on GPIO 4
- ISR records `micros()` timestamp and sets flag
- Main loop reads MCP23017 over I2C to identify which sensor(s) changed
- Timestamp is accurate to ISR latency (~1-2 us), not I2C read time
- Edge case: two sensors triggering within one I2C read cycle — resolved by
  reading the interrupt capture register (INTCAP) which latches state at interrupt time

**Run detection:**
1. Run starts when any sensor triggers after an idle period
2. Direction determined by which end fires first (sensor 0 vs sensor 7)
3. Run ends when:
   - All sensors have triggered, OR
   - Timeout expires (`SPEED_CAL_DETECTION_TIMEOUT_MS`), OR
   - A `stop` command is received
4. After run completes, compute velocities and publish results
5. Reset state for next run

**Velocity calculation:**

For each pair of adjacent triggered sensors:
```
interval_us = timestamp[i+1] - timestamp[i]
velocity_mm_per_sec = sensor_spacing_mm / (interval_us / 1_000_000.0)
scale_speed_mph = velocity_mm_per_sec * scale_factor * 3600.0 / (1_000_000.0 * 1.609344)
```

Or more simply:
```
scale_speed_smph = (spacing_mm * scale_factor * 0.002237) / (interval_us / 1_000_000.0)
```

Where 0.002237 converts mm/sec to mph.

**Direction detection:**
- If sensor 0 triggers before sensor 7: direction = A→B (+1)
- If sensor 7 triggers before sensor 0: direction = B→A (-1)
- Timestamps are reordered to always report in direction of travel

### Automated Calibration Sequence

The ESP32 does not drive the locomotive — JMRI (or a script on the M4) does that via DCC. The ESP32's role is purely measurement: detect sensor triggers, compute speeds, and publish results. The orchestration script handles the sequencing.

However, the firmware does support a `run` mode where it arms the sensors and waits for a pass, then publishes the result. The script workflow is:

```
Script sets speed step 1 on loco via JMRI/MQTT
Script publishes: {prefix}/speed-cal/{name}/arm
  → Firmware arms sensors, waits for pass
Loco enters sensor array, triggers sensors
Firmware computes speeds
Firmware publishes result to: {prefix}/speed-cal/{name}/result
Script records result
Script sets speed step 2
Script re-arms sensors
... repeat through speed step 126
Script publishes: {prefix}/speed-cal/{name}/stop
```

---

## MQTT Interface

### Topics

| Topic | Direction | Payload | Description |
|-------|-----------|---------|-------------|
| `{prefix}/speed-cal/{name}/arm` | → ESP32 | (empty) | Arm sensors for next pass |
| `{prefix}/speed-cal/{name}/stop` | → ESP32 | (empty) | Cancel active run, disarm |
| `{prefix}/speed-cal/{name}/status` | → ESP32 | (empty) | Request current status |
| `{prefix}/speed-cal/{name}/result` | ESP32 → | JSON | Measurement result (see below) |
| `{prefix}/speed-cal/{name}/status` | ESP32 → | JSON | Status response |
| `{prefix}/speed-cal/{name}/error` | ESP32 → | JSON | Error report |

### Result Payload

Published after each completed pass:

```json
{
  "direction": "A-B",
  "sensors_triggered": 16,
  "timestamps_us": [0, 64300, 128100, 192800, 256500, 320900, 385100, 449200, 513800, 578100, 642500, 706800, 771200, 835400, 899900, 964100],
  "intervals_us": [64300, 63800, 64700, 63700, 64400, 64200, 64100, 64600, 64300, 64400, 64300, 64400, 64200, 64500, 64200],
  "velocities_mm_s": [1555.2, 1567.4, 1545.6, 1570.0, 1552.8, 1557.6, 1560.1, 1548.6, 1555.2, 1552.8, 1555.2, 1552.8, 1557.6, 1550.4, 1557.6],
  "scale_speeds_mph": [30.6, 30.8, 30.4, 30.9, 30.6, 30.7, 30.7, 30.5, 30.6, 30.6, 30.6, 30.6, 30.7, 30.5, 30.7],
  "avg_scale_speed_mph": 30.6,
  "timestamp": 1706900000
}
```

**Field descriptions:**
- `timestamps_us`: Microsecond offsets from first trigger, in direction of travel
- `intervals_us`: Time between each adjacent sensor pair
- `velocities_mm_s`: Measured velocity for each interval (model scale, not prototype)
- `scale_speeds_mph`: Prototype speed in mph for each interval
- `avg_scale_speed_mph`: Mean prototype speed across all intervals
- `timestamp`: Unix epoch seconds (from NTP if available, else uptime)

### Status Payload

```json
{
  "state": "armed",
  "sensors": 8,
  "spacing_mm": 75,
  "scale_factor": 87.1,
  "sensors_triggered": 0,
  "uptime_ms": 123456
}
```

States: `idle`, `armed`, `measuring`, `complete`

### Error Payload

```json
{
  "error": "timeout",
  "sensors_triggered": 3,
  "message": "Run timed out after 60000ms with only 3 of 8 sensors triggered"
}
```

---

## Configuration

### JSON Configuration

```json
{
  "speed_cal": {
    "name": "speed-cal",
    "spacing_mm": 100,
    "scale_factor": 87.1,
    "sensor_count": 16,
    "mcp23017_addr": "0x20",
    "mcp23017_int_pin": 4,
    "hx711_dout_pin": 16,
    "hx711_sck_pin": 17
  }
}
```

### MQTT Configuration

**Add:** `{prefix}/config/{board}/speed-cal/add`

```json
{
  "name": "speed-cal",
  "spacing_mm": 100,
  "scale_factor": 87.1,
  "sensor_count": 16,
  "mcp23017_addr": "0x20",
  "mcp23017_int_pin": 4
}
```

**Delete:** `{prefix}/config/{board}/speed-cal/delete`

```json
{"name": "speed-cal"}
```

---

## Orchestration Script

A Python script (run on the M4 or any machine with MQTT and JMRI access) automates the full calibration sweep. This is **not** part of the ESP32 firmware — it runs externally.

### `calibrate_speed.py`

```
Usage: calibrate_speed.py --address <dcc_address> [options]

Options:
  --address      DCC address of locomotive to calibrate (required)
  --broker       MQTT broker address (default: localhost)
  --prefix       MQTT topic prefix (default: /cova)
  --cal-name     Speed-cal device name (default: speed-cal)
  --min-step     Starting speed step (default: 1)
  --max-step     Ending speed step (default: 126)
  --step-inc     Speed step increment (default: 1)
  --settle-sec   Seconds to wait after speed change (default: 5)
  --passes       Number of passes per speed step (default: 1)
  --output       Output file path (default: speed_table_{address}.json)
  --jmri-topic   JMRI MQTT throttle topic pattern (default: cab/{0}/throttle)
```

### Script Workflow

**Phase 0: Start-of-motion detection**

Before the full sweep, the script finds the minimum speed step that produces actual movement. This avoids wasting time on dead steps and establishes the minimum reliable operating speed for the roster entry.

```python
# Binary search for start-of-motion threshold
def find_start_of_motion(address, direction):
    """Find the lowest speed step that produces detectable movement."""
    low, high = 1, 20  # Most locos start moving below step 20
    start_step = high   # Fallback

    while low <= high:
        mid = (low + high) // 2

        publish(f"cab/{address}/throttle", str(step_to_percent(mid)))
        sleep(3)  # Brief settle

        publish(f"{prefix}/speed-cal/{cal_name}/arm", "")
        result = wait_for_message(
            f"{prefix}/speed-cal/{cal_name}/result", timeout=15)

        publish(f"cab/{address}/throttle", "0")
        sleep(2)  # Stop before next test

        if result and result["sensors_triggered"] >= 2:
            start_step = mid  # This step produces movement
            high = mid - 1    # Try lower
        else:
            low = mid + 1     # Need more power

        # Reverse direction for shuttle track
        publish(f"cab/{address}/direction", toggle_direction())
        sleep(1)

    return start_step

forward_start = find_start_of_motion(address, "FORWARD")
reverse_start = find_start_of_motion(address, "REVERSE")
```

This typically takes 8–10 probes (under 2 minutes) and identifies the threshold to within ±1 speed step. The result is recorded in the output as `min_speed_step_forward` and `min_speed_step_reverse`, and passed to JMRI as the minimum reliable operating speed via `RosterSpeedProfile.setMinMaxLimits()`.

For the low-speed steps just above the threshold (start through start+5), the script runs 3 passes per step and averages, since these measurements are inherently noisier.

**Full sweep**

```python
# Start sweep from the detected start-of-motion step
effective_min = min(forward_start, reverse_start)

for step in range(effective_min, max_step + 1, step_inc):
    passes = 3 if step <= effective_min + 5 else num_passes

    for p in range(passes):
        # Set locomotive speed via JMRI MQTT
        publish(f"cab/{address}/throttle", str(step_to_percent(step)))

        # Wait for locomotive to reach steady state
        sleep(settle_sec)

        # Arm the sensor array
        publish(f"{prefix}/speed-cal/{cal_name}/arm", "")

        # Wait for result (loco passes through sensors)
        result = wait_for_message(
            f"{prefix}/speed-cal/{cal_name}/result", timeout=90)

        if result:
            record(step, result, direction=current_direction)
        else:
            record(step, {"error": "no_detection"})

        # If using a shuttle track: reverse direction
        publish(f"cab/{address}/direction", toggle_direction())
        sleep(2)  # Brief pause for direction change

# Stop locomotive
publish(f"cab/{address}/throttle", "0")
```

### Output Format

```json
{
  "address": 1234,
  "decoder": "TCS WOW121",
  "date": "2026-02-06T14:30:00Z",
  "scale": "HO",
  "scale_factor": 87.1,
  "sensor_spacing_mm": 75,
  "start_of_motion": {
    "forward_step": 7,
    "reverse_step": 9,
    "forward_throttle_pct": 5.6,
    "reverse_throttle_pct": 7.1,
    "notes": "Reverse requires higher step; typical for this mechanism"
  },
  "speed_table": [
    {
      "speed_step": 1,
      "percent": 1,
      "avg_scale_mph": 2.3,
      "interval_speeds_mph": [2.1, 2.2, 2.3, 2.4, 2.3, 2.4, 2.3],
      "direction": "A-B",
      "passes": 1
    },
    {
      "speed_step": 2,
      "percent": 2,
      "avg_scale_mph": 4.1,
      "interval_speeds_mph": [3.9, 4.0, 4.1, 4.2, 4.1, 4.2, 4.1],
      "direction": "B-A",
      "passes": 1
    }
  ],
  "acceleration_profile": {
    "description": "Measured from step changes during calibration",
    "samples": [
      {
        "from_step": 0,
        "to_step": 1,
        "time_to_stable_sec": 3.2,
        "interval_speeds_during_accel": [0.5, 1.2, 1.8, 2.1, 2.3]
      }
    ]
  },
  "summary": {
    "min_speed_step_forward": 7,
    "min_speed_step_reverse": 9,
    "min_reliable_speed_mph": 2.3,
    "max_speed_mph": 92.4,
    "speed_at_step_63_mph": 45.2,
    "speed_at_step_126_mph": 92.4,
    "linearity": 0.97,
    "dead_steps_forward": 6,
    "dead_steps_reverse": 8
  }
}
```

### Acceleration Measurement

Because the array has 8 sensors, a single pass during acceleration reveals the speed profile *within* that pass. The script can exploit this:

1. With loco stopped, set speed step N
2. Immediately arm sensors
3. The loco accelerates through the array
4. The 7 interval velocities show the acceleration curve
5. Repeat at different starting/ending speed steps to build a full acceleration model

The `settle_sec` parameter controls whether you're measuring steady-state speed (long settle) or acceleration (zero settle).

---

## Accuracy Considerations

### Sources of Error

| Source | Magnitude | Mitigation |
|--------|-----------|------------|
| Sensor spacing measurement | ±0.5mm | Measure carefully; use PCB with fixed spacing |
| Sensor trigger point variation | ±1mm per sensor | Use consistent mounting; triggers are relative so offset cancels |
| Timer resolution (`micros()`) | ±4 us on ESP32 | Negligible at model railroad speeds |
| Loco speed variation (hunting) | 1-5% of speed | Multiple intervals per pass average this out |
| Track grade | Proportional to slope | Level the track |
| Wheel slip (at very low speeds) | Variable | Note in results; below step ~3 may be unreliable |
| DCC signal noise on sensor pins | Rare | Debounce handles this; TCRT5000 is optical not electrical |

### Expected Accuracy

At typical HO operating speeds (scale 20-60 mph):
- Speed measurement accuracy: ±2-3%
- Repeatability between passes: ±1-2%
- Sufficient for consisting, audio correlation, and position tracking

At very low speeds (scale <5 mph):
- Accuracy degrades due to motor cogging and wheel slip
- Longer measurement intervals partially compensate
- Mark these results as lower confidence in output

---

## Vibration Analysis (Mechanism Health)

### Concept

A piezoelectric disc bonded to the underside of the rail or roadbed captures structure-borne vibration as the locomotive passes through the sensor array. Since the loco is already moving at known, controlled speeds, the vibration data can be correlated to RPM and analyzed for mechanical health indicators.

This turns the calibration track into a triage tool: run the fleet through, sort by noise level, and prioritize which mechanisms need service before investing in a decoder install.

### What It Detects

| Condition | Vibration Signature |
|-----------|-------------------|
| **Worn gears** | Broadband whine/grind, amplitude increases with speed |
| **Bad motor bearings** | High-frequency noise, present at all speeds |
| **Wheel flat spots** | Periodic thumps at frequency proportional to speed |
| **Driver quartering issues** | Uneven torque pulses, most audible at low speed |
| **Loose components** | Rattles/buzzes that appear above a threshold speed |
| **Dry mechanism** | Higher overall noise floor vs. lubricated baseline |

### Hardware

- **Sensor:** 27mm piezoelectric disc (~$0.10), bonded to underside of roadbed or rail web with cyanoacrylate
- **Signal conditioning:** Simple voltage divider (two resistors) to keep signal within ESP32 ADC range (0–3.3V), plus a small capacitor for DC blocking
- **ADC pin:** One ESP32 ADC1 channel (ADC2 conflicts with WiFi)
- **Placement:** Center of the sensor array, between sensors 3 and 4, where the loco is at steady speed

### Firmware Addition

```c
// Vibration analysis config (added to speed_cal_t)
int vibrationPin;                    // ADC pin for piezo (-1 = not installed)
bool vibrationEnabled;               // Feature enable flag
```

**Sampling:** During each pass (while `runActive` is true), sample the ADC at 8kHz using a timer interrupt or DMA. Store samples in a circular buffer. At 8kHz, a pass at scale 30mph (~100mm/sec in HO) across the 525mm array takes ~5.2 seconds = ~42,000 samples = ~84KB at 16-bit — well within ESP32 memory.

**Processing (on-chip):**
1. Compute RMS amplitude (overall noise level)
2. Run a simple FFT (256 or 512 point) on windowed segments
3. Identify dominant frequency peaks
4. Correlate peak frequencies to wheel RPM (known from speed measurement)
5. Flag anomalies: peaks that don't correlate to expected harmonics

### Output

Added to the per-pass result and summarized in the calibration JSON:

```json
"mechanism_health": {
  "overall_grade": "fair",
  "noise_floor_rms": 142,
  "noise_by_speed": [
    {"step": 20, "rms": 85, "peak_freq_hz": 220, "peak_amplitude": 45},
    {"step": 60, "rms": 195, "peak_freq_hz": 660, "peak_amplitude": 120},
    {"step": 100, "rms": 310, "peak_freq_hz": 1100, "peak_amplitude": 185}
  ],
  "anomalies": [
    {
      "type": "gear_noise",
      "severity": "moderate",
      "speed_range": [15, 126],
      "description": "Broadband noise rising with speed, consistent with worn worm gear"
    }
  ],
  "comparison": {
    "fleet_percentile": 72,
    "note": "Noisier than 72% of tested fleet"
  }
}
```

**Grading:** Simple thresholds based on fleet statistics — after several locos have been tested, the script can compute percentile rankings. Grades:
- **good**: Below fleet median RMS
- **fair**: Above median but below 75th percentile
- **poor**: Above 75th percentile or any anomaly flagged
- **service**: Specific defect pattern detected (flat spot, bearing, etc.)

### Signal Conditioning Circuit

```
Piezo disc ──┬── 1MΩ ──┬── ESP32 ADC pin (GPIO 36)
             │         │
           100kΩ     10nF
             │         │
            GND       GND
```

The 1MΩ resistor biases the signal, the 100kΩ forms a voltage divider to keep peaks within ADC range, and the 10nF cap blocks DC offset from the piezo. Total parts cost: ~$0.15.

---

## Audio Analysis (Decoder Sound Level)

### Concept

An INMP441 MEMS microphone mounted near the track captures airborne sound from the locomotive's decoder speaker during the calibration pass. This provides:

- **Volume measurement:** SPL at idle and across the speed range — immediately flags locos whose decoder volume was reset to factory defaults (looking at you, BLI Paragon)
- **Sound character profiling:** Frequency content of the decoder output at each speed step — chuff rate, motor sounds, bell/whistle levels
- **Before/after comparison:** Re-run after decoder CV changes to verify the effect without subjective listening
- **Fleet consistency:** Ensure all locos are at comparable volume levels so one doesn't blast the room when the layout powers on

### Hardware

- **Sensor:** INMP441 MEMS microphone breakout (~$1-2), digital I2S output
- **Mounting:** On a small standoff near the center of the sensor array, aimed at the track, ~20-30mm from rail top
- **Interface:** ESP32 I2S input (3 pins: SCK, WS, SD)
- **No analog conditioning needed** — the INMP441 outputs digital PCM directly via I2S

### Firmware Addition

```c
// Audio analysis config (added to speed_cal_t)
int audioSckPin;                     // I2S clock pin (-1 = not installed)
int audioWsPin;                      // I2S word select pin
int audioSdPin;                      // I2S data pin
bool audioEnabled;                   // Feature enable flag
```

**Sampling:** The INMP441 runs at standard I2S rates. Sample at 16kHz (sufficient for decoder speaker output, which rolls off well below 8kHz). During each pass, capture audio into a buffer alongside the vibration data.

**Processing (on-chip):**
1. Compute RMS amplitude (overall volume level, approximating SPL)
2. Peak level detection (loudest moment during the pass)
3. Optional: FFT for frequency content at idle (chuff rate, prime mover tone)

**Key distinction from the piezo:** The MEMS mic captures what a *person* hears — the decoder speaker output through the air. The piezo captures what the *track* feels — mechanical vibration. They're complementary, not redundant.

### Output

```json
"audio_analysis": {
  "idle_rms": 1850,
  "idle_peak": 2940,
  "idle_level_db": 62,
  "at_speed": [
    {"step": 20, "rms": 2100, "level_db": 64},
    {"step": 60, "rms": 2450, "level_db": 67},
    {"step": 100, "rms": 2800, "level_db": 70}
  ],
  "volume_grade": "loud",
  "fleet_percentile": 92,
  "notes": "12dB above fleet median at idle; likely factory default volume"
}
```

**Volume grading:**
- **quiet**: Below 25th percentile
- **normal**: 25th–75th percentile
- **loud**: Above 75th percentile
- **excessive**: >10dB above fleet median — flag for volume adjustment

### Pin Sharing with Future I2S Audio Output

The pin budget already reserves 3 GPIO for "Future I2S audio" output (BCLK, WS, DOUT). The INMP441 *input* uses different I2S peripheral pins (the ESP32 has two I2S peripherals). So both can coexist:

| I2S Peripheral | Direction | Use | Pins |
|----------------|-----------|-----|------|
| I2S0 | Input | INMP441 mic | SCK=GPIO 18, WS=GPIO 19, SD=GPIO 23 |
| I2S1 | Output | Future audio playback | BCLK, WS, DOUT (reserved) |

---

## JMRI Roster Integration

### RosterSpeedProfile

Every locomotive in the JMRI roster has an optional `RosterSpeedProfile` that stores exactly what the calibration track measures. The profile lives inside the roster entry XML file (in `~/.jmri/roster/{loco}.xml`):

```xml
<speedprofile>
  <overRunTimeForward>150.5</overRunTimeForward>
  <overRunTimeReverse>145.2</overRunTimeReverse>
  <speeds>
    <speed>
      <step>8</step>
      <forward>5.23</forward>
      <reverse>5.15</reverse>
    </speed>
    <speed>
      <step>16</step>
      <forward>15.67</forward>
      <reverse>15.42</reverse>
    </speed>
  </speeds>
</speedprofile>
```

**Data format:**
- `step`: Throttle setting × 1000 (integer, range 0–1000)
- `forward` / `reverse`: Actual track speed in **mm/sec**
- `overRunTimeForward` / `overRunTimeReverse`: Momentum overshoot in milliseconds (how far the loco coasts after throttle is cut — measured during deceleration profiling)

### Conversion from Calibration Output

```python
# Convert calibration JSON → JMRI RosterSpeedProfile format
MMS_PER_SCALE_MPH = 1.0 / 0.00223694  # ~447.04 mm/sec per scale mph

for entry in speed_table:
    step = entry["speed_step"]
    throttle = step / 126.0                         # 0.0–1.0
    jmri_key = round(throttle * 1000)               # 0–1000
    speed_mms = entry["avg_scale_mph"] / (scale_factor * 0.00223694)
    # → store as <step>{jmri_key}</step> <forward>{speed_mms}</forward>
```

The deceleration profiling (Phase 4) directly provides the `overRunTimeForward` and `overRunTimeReverse` values — measure coast-down from a known speed through the sensor array, compute how long the loco takes to stop.

### Import Script (`import_speed_profile.py`)

A Jython script that runs inside JMRI to load calibration data into a roster entry:

```python
import jmri
import json

def importSpeedProfile(roster_id, calibration_file):
    """Load calibration JSON into a JMRI roster entry's speed profile."""
    roster = jmri.jmrit.roster.Roster.getDefault()
    entry = roster.getEntryForId(roster_id)

    if entry is None:
        print("Roster entry '{}' not found".format(roster_id))
        return

    with open(calibration_file) as f:
        cal = json.load(f)

    sp = entry.getSpeedProfile()
    if sp is None:
        sp = jmri.jmrit.roster.RosterSpeedProfile(entry)
        entry.setSpeedProfile(sp)

    scale_factor = cal["scale_factor"]

    for measurement in cal["speed_table"]:
        step = measurement["speed_step"]
        throttle = step / 126.0
        speed_mph = measurement["avg_scale_mph"]
        speed_mms = speed_mph / (scale_factor * 0.00223694)

        direction = measurement.get("direction", "A-B")
        if direction == "A-B":
            sp.setForwardSpeed(throttle, speed_mms)
        else:
            sp.setReverseSpeed(throttle, speed_mms)

    # Set momentum overshoot if available
    if "deceleration" in cal:
        sp.setOverRunTimeForward(cal["deceleration"].get("forward_ms", 0))
        sp.setOverRunTimeReverse(cal["deceleration"].get("reverse_ms", 0))

    entry.updateFile()
    roster.writeRoster()
    print("Speed profile imported for {}".format(roster_id))
```

### What Consumes the Speed Profile

Once the profile is in the roster, these JMRI systems use it automatically:

| System | How It Uses the Speed Profile |
|--------|-------------------------------|
| **Warrants** | Calculates throttle settings for target speeds, block traversal times, and braking distances |
| **Dispatcher / AutoActiveTrain** | Sets accurate throttle positions based on speed limits from signal aspects |
| **Throttle display** | Shows actual scale MPH/KPH instead of raw throttle percentage |
| **Speed matching (consisting)** | Finds equivalent throttle settings across different locos for matched MU operation |
| **Block timing** | Estimates time to traverse blocks for occupancy prediction |

### Full Calibration-to-Roster Pipeline

```
Loco on calibration track
        ↓
calibrate_speed.py sweeps speed steps 1–126
  via MQTT: cab/{addr}/throttle, cab/{addr}/direction
        ↓
ESP32 sensor array measures actual speed per step
  publishes: {prefix}/speed-cal/{name}/result
        ↓
Script collects results → speed_table_{addr}.json
        ↓
import_speed_profile.py (Jython in JMRI)
  reads JSON, writes RosterSpeedProfile
        ↓
Roster entry saved with measured speed profile
        ↓
Warrants, dispatcher, throttle display, audio engine
  all use measured data instead of guesses
```

---

## Other Integration Points

### Position Tracking

Given a speed table for locomotive at address `addr`:

```
current_speed_step = value from cab/{addr}/throttle
actual_speed_mph = lookup(speed_table, current_speed_step)
actual_speed_mm_s = actual_speed_mph / (scale_factor * 0.002237)
position_delta_mm = actual_speed_mm_s * elapsed_seconds
```

Combined with reporter data (RFID tag detection at known locations), this provides continuous position estimation between detection points.

### Audio Engine

The COVA audio architecture uses speed-correlated playback for wheel/rail noise. Currently, speed is estimated from the throttle setting. With a calibrated speed table, the audio engine uses measured velocity instead — so a loco that runs fast at low speed steps gets appropriately faster wheel sound.

### Steam Throttle

The Phase 3 boiler simulation in the steam throttle design needs to know actual wheel speed to model load. With the calibration data available via MQTT or the roster, the simulation uses real physics instead of assumptions about how throttle percentage maps to speed.

---

## Bill of Materials

| Qty | Part | Purpose | Have? | Est. Cost |
|-----|------|---------|-------|-----------|
| 16 | TCRT5000 reflective sensor | Speed detection | Yes (box of 60) | $8 |
| 1 | ESP32 DevKit | Controller | Yes | $5 |
| 1 | MCP23017 DIP | 16-ch GPIO expander for sensors | Yes | $2 |
| 16 | 10k resistor | Sensor pullups | Yes | $1 |
| 2 | 4.7k resistor | I2C pullups | Yes | $0.10 |
| 2 | Code 70 flex track (36" ea) | Test track (72" total) | Yes | (existing) |
| 1 | 1/4" plywood (~8" x 76") | Track base | Yes | (existing) |
| 1 | 500g beam load cell | Drawbar pull measurement | Ordered | $4 |
| 1 | HX711 breakout | Load cell ADC | Ordered | $1 |
| 1 | INMP441 MEMS mic breakout | Decoder sound level measurement | Ordered | $2 |
| 1 | 27mm piezoelectric disc | Vibration sensing | Check | $0.10 |
| 3 | Resistors + capacitor | Piezo signal conditioning | Probably | $0.05 |
| 16 | 3D printed sensor plugs | Sensor mounting in plywood base | Print | $2 (resin) |
| 1 | PCB or perfboard | Main electronics board (~60x80mm) | Yes | $3 |
| - | Wire, headers, connectors | Assembly | Yes | $3 |
| | | **Total (new purchases)** | | **~$10** |

---

## Implementation Plan

### Phase 1: Prototype — 4 Sensors on Perfboard
- Wire 4 TCRT5000 sensors + MCP23017 on perfboard with ESP32 DevKit
- Design and print sensor plug for 1/4" plywood base
- Mount 4 sensors in a short test section of track
- Implement MCP23017 interrupt-driven timestamp capture
- Implement arm/measure/publish cycle
- Verify sensor triggering with a locomotive passed by hand
- Validate timing accuracy and trigger reliability
- **Estimated effort:** 4-6 hours

### Phase 2: Full 16-Sensor Build
- Design PCB in KiCad (~60x80mm) with all electronics
- Fab PCB (JLCPCB or equivalent)
- Build 72" track on plywood base, drill sensor holes
- Print 16 sensor plugs, install sensors
- Wire and test all 16 channels
- **Estimated effort:** 8-12 hours (including PCB fab lead time)

### Phase 3: MQTT Integration & Speed Calculation
- Add `speed_cal_t` device type to firmware
- Implement MQTT command interface (arm, stop, status)
- Implement velocity calculation and result publishing
- Add configuration support (add/delete via MQTT and JSON)
- Test with DCC-powered locomotive at various speeds
- **Estimated effort:** 6-8 hours

### Phase 4: Orchestration Script — Start-of-Motion & Sweep
- Write `calibrate_speed.py`
- Implement binary search for start-of-motion threshold (forward and reverse)
- Record minimum reliable operating speed for roster import
- Implement JMRI MQTT throttle control for full speed step sweep
- Multi-pass averaging for low-speed steps (start through start+5)
- Skip dead steps below start-of-motion threshold
- Implement result collection and output file generation
- Test full automated calibration on one locomotive
- **Estimated effort:** 6-8 hours

### Phase 5: Load Cell — Drawbar Pull Measurement
- Mount 500g beam load cell at bumper end with 3D-printed bracket
- Wire HX711 breakout to ESP32 (GPIO 16/17)
- Implement tare and continuous reading during active passes
- Publish load data via MQTT alongside speed data
- Calibrate with known weights
- **Estimated effort:** 3-4 hours

### Phase 6: Vibration & Audio Analysis
- Wire piezo disc and signal conditioning circuit
- Implement 8kHz ADC sampling during active passes (timer interrupt or DMA)
- Compute RMS amplitude per pass
- Implement basic FFT (256-point) for frequency analysis
- Correlate peak frequencies to wheel RPM from speed data
- Add `mechanism_health` section to output JSON
- Wire INMP441 MEMS mic on I2S0 input
- Implement 16kHz I2S audio capture during passes and at idle
- Compute audio RMS/peak levels, approximate dB
- Add `audio_analysis` section to output JSON
- Establish fleet baselines after 5+ locos tested; compute percentile grades for both
- **Estimated effort:** 6-8 hours

### Phase 7: Acceleration & Deceleration Profiling
- Add acceleration measurement mode to script (zero settle time)
- Capture intra-pass velocity variation as acceleration data
- Add deceleration measurement (set speed to 0, measure coast-down through array)
- Compute `overRunTimeForward` and `overRunTimeReverse` for JMRI momentum compensation
- Include acceleration profiles in output format
- **Estimated effort:** 3-4 hours

### Phase 8: JMRI Roster Integration
- Write `import_speed_profile.py` Jython script
- Import speed table into `RosterSpeedProfile` (forward and reverse speeds in mm/sec)
- Set `overRunTimeForward` / `overRunTimeReverse` from deceleration profiling
- Set minimum reliable operating speed via `setMinMaxLimits()`
- Verify data appears in JMRI throttle display (scale MPH readout)
- Verify warrants can use imported profile for block timing
- **Estimated effort:** 3-4 hours

### Phase 9: Fleet Calibration
- Calibrate full fleet (~40 locos, estimated 3-5 minutes each)
- Import all results into JMRI roster
- Cross-validate: consist test with two speed-matched locomotives
- Connect calibration data to audio engine speed correlation
- Document per-locomotive notes (dead steps, quirks, decoder differences)
- **Estimated effort:** 4-6 hours

**Total estimated effort:** 32-46 hours

---

## Success Criteria

- [ ] 8 sensors reliably detect locomotive passes in both directions
- [ ] Start-of-motion binary search completes in under 2 minutes and identifies threshold within ±1 step
- [ ] Speed measurement accuracy within ±3% of reference (hand-timed pass over known distance)
- [ ] Full calibration (start-of-motion + sweep) completes unattended in under 10 minutes per locomotive
- [ ] Results are repeatable — same loco, same run, within ±2%
- [ ] Acceleration profile captures visible speed change within a single pass
- [ ] Output file is valid JSON and contains all fields specified above
- [ ] At least 5 locomotives calibrated and cross-validated (consist test at matched speeds)
- [ ] Vibration RMS correlates with speed (higher speed = higher RMS for same loco)
- [ ] Vibration analysis can distinguish a known-good mechanism from a known-noisy one
- [ ] Audio analysis detects decoder sound at idle and across speed range
- [ ] Audio level measurement can identify a loco at factory-default volume vs. a properly adjusted one
- [ ] Calibration data successfully consumed by at least one downstream system (JMRI, audio, or position tracking)

---

## Future Enhancements

- **RDM6300 RFID reader** on the same board — automatically identify which locomotive is on the test track without manual address entry
- **Continuous monitoring mode** — leave the sensor array powered on a mainline section and passively log speeds of all traffic
- **Decoder CV optimization** — script adjusts momentum CVs and re-measures until desired acceleration curve is achieved
- **Web UI** — add a calibration page to the esp32-config GUI showing real-time sensor triggers and speed graph
- **Multi-scale support** — configurable scale factor for N, HO, S, O gauge
- **Dynamometer (tractive effort)** — 500g load cell + HX711 included in main design (Phase 5). Measures drawbar pull at each speed step, stall force, and adhesion limits
