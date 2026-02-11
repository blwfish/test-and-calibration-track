#!/usr/bin/env python3
"""
Automated Locomotive Speed Calibration

Runs a full calibration sweep on a DCC locomotive using the ESP32 sensor array
and JMRI throttle bridge. Produces a speed table JSON mapping each DCC speed
step to actual scale speed.

Workflow:
  1. Acquire throttle via JMRI bridge
  2. Binary search for start-of-motion threshold (forward & reverse)
  3. Sweep speed steps, arm sensors, collect results
  4. Output calibration JSON

Prerequisites:
  pip3 install paho-mqtt

  Running:
  - JMRI with SPROG program track connection (default for Throttle)
  - MQTT connection to same Mosquitto broker
  - jmri_throttle_bridge.py loaded in JMRI
  - ESP32 sensor array powered and connected to MQTT

Usage:
  python3 calibrate_speed.py --address 3
  python3 calibrate_speed.py --address 1234 --broker 10.0.0.5 --dry-run
  python3 calibrate_speed.py --address 3 --skip-start-of-motion --min-step 10
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone

# Import sibling modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from loco_control import LocoController, resolve_mqtt_args
from calibration_db import CalibrationDB


# --- Constants ---
HO_SCALE_FACTOR = 87.1
DEFAULT_SENSOR_SPACING_MM = 100.0
START_OF_MOTION_LOW = 1
START_OF_MOTION_HIGH = 20


def step_to_throttle(step):
    """Convert DCC speed step (1-126) to throttle fraction (0.0-1.0)."""
    return step / 126.0


def step_to_pct(step):
    """Convert DCC speed step to throttle percentage."""
    return round(step / 126.0 * 100.0, 1)


class SpeedCalibrator:
    """Orchestrates a full speed calibration run."""

    def __init__(self, ctrl, args):
        self.ctrl = ctrl
        self.args = args
        self.direction_forward = True  # Current shuttle direction
        self.results = []              # Collected speed table entries
        self.start_of_motion = None    # Dict with forward/reverse thresholds
        self.start_time = time.time()
        self.total_passes = 0
        self.aborted = False

    def log(self, msg):
        """Print a timestamped log message."""
        elapsed = time.time() - self.start_time
        mins, secs = divmod(int(elapsed), 60)
        print(f"[{mins:02d}:{secs:02d}] {msg}")

    def wait_for_result(self, timeout):
        """Wait for a sensor result message. Returns parsed JSON or None."""
        self.ctrl.last_result = None
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.ctrl.last_result is not None:
                try:
                    return json.loads(self.ctrl.last_result)
                except json.JSONDecodeError:
                    return None
            time.sleep(0.1)
        return None

    def toggle_direction(self):
        """Switch shuttle direction."""
        self.direction_forward = not self.direction_forward
        if self.direction_forward:
            self.ctrl.forward()
        else:
            self.ctrl.reverse()

    def direction_str(self):
        """Current direction as string."""
        return "fwd" if self.direction_forward else "rev"

    def arm_and_measure(self, timeout):
        """Arm sensors and wait for a result. Returns parsed result or None."""
        if self.args.dry_run:
            self.log(f"  [dry-run] arm sensors, wait {timeout}s for result")
            return {"sensors_triggered": 4, "avg_speed_mph": "42.0",
                    "direction": "A-B", "duration_ms": 1250.0,
                    "speeds_mph": ["41.5", "42.0", "42.5"]}

        self.ctrl.arm_sensors()
        return self.wait_for_result(timeout)

    def set_speed(self, step):
        """Set locomotive speed by DCC step number."""
        throttle = step_to_throttle(step)
        if self.args.dry_run:
            self.log(f"  [dry-run] speed step {step} (throttle {throttle:.3f})")
        else:
            self.ctrl.speed(throttle)

    def stop_loco(self):
        """Stop the locomotive."""
        if not self.args.dry_run:
            self.ctrl.stop()

    def find_start_of_motion(self):
        """Binary search for minimum speed step producing movement."""
        self.log("=== Start-of-motion detection ===")

        forward_start = self._search_threshold("forward")
        reverse_start = self._search_threshold("reverse")

        self.start_of_motion = {
            "forward_step": forward_start,
            "reverse_step": reverse_start,
            "forward_throttle_pct": step_to_pct(forward_start),
            "reverse_throttle_pct": step_to_pct(reverse_start),
        }

        self.log(f"Start-of-motion: forward={forward_start}, reverse={reverse_start}")
        return self.start_of_motion

    def _search_threshold(self, direction):
        """Binary search for start-of-motion in one direction."""
        self.log(f"Searching {direction} start-of-motion...")

        # Set direction
        if direction == "forward":
            self.direction_forward = True
            if not self.args.dry_run:
                self.ctrl.forward()
        else:
            self.direction_forward = False
            if not self.args.dry_run:
                self.ctrl.reverse()

        time.sleep(0.5)

        low = START_OF_MOTION_LOW
        high = START_OF_MOTION_HIGH
        best = high  # Fallback: assume start at high bound

        while low <= high:
            mid = (low + high) // 2
            self.log(f"  Probing step {mid} ({direction})...")

            self.set_speed(mid)
            time.sleep(3)  # Brief settle

            result = self.arm_and_measure(timeout=15)

            self.stop_loco()
            time.sleep(2)  # Let loco stop before next probe

            triggered = 0
            if result:
                triggered = result.get("sensors_triggered", 0)

            if triggered >= 2:
                self.log(f"  Step {mid}: MOVEMENT ({triggered} sensors)")
                best = mid
                high = mid - 1  # Try lower
            else:
                self.log(f"  Step {mid}: no movement")
                low = mid + 1   # Need more power

        self.log(f"  {direction} threshold: step {best}")
        return best

    def run_sweep(self):
        """Execute the full speed step sweep."""
        args = self.args

        # Determine starting step
        if self.start_of_motion and not args.skip_start_of_motion:
            effective_min = min(
                self.start_of_motion["forward_step"],
                self.start_of_motion["reverse_step"]
            )
        else:
            effective_min = args.min_step

        total_steps = len(range(effective_min, args.max_step + 1, args.step_inc))
        self.log(f"=== Speed sweep: steps {effective_min}-{args.max_step} "
                 f"(inc {args.step_inc}, {total_steps} steps) ===")

        # Set initial direction
        self.direction_forward = True
        if not args.dry_run:
            self.ctrl.forward()
        time.sleep(0.5)

        step_num = 0
        sweep_start = time.time()

        for step in range(effective_min, args.max_step + 1, args.step_inc):
            step_num += 1

            # Determine passes for this step
            if (self.start_of_motion and
                    step <= effective_min + args.low_range):
                num_passes = args.low_passes
            else:
                num_passes = args.passes

            # ETA calculation
            if step_num > 1:
                elapsed = time.time() - sweep_start
                per_step = elapsed / (step_num - 1)
                remaining = per_step * (total_steps - step_num + 1)
                eta_min = int(remaining // 60)
                eta_sec = int(remaining % 60)
                eta_str = f" ETA {eta_min}m{eta_sec:02d}s"
            else:
                eta_str = ""

            self.log(f"[step {step}/{args.max_step}] "
                     f"throttle={step_to_throttle(step):.3f} "
                     f"({num_passes} pass{'es' if num_passes > 1 else ''})"
                     f"{eta_str}")

            pass_results = []
            audio_data = None

            for p in range(num_passes):
                # Set direction for this pass
                dir_str = self.direction_str()

                # Set speed and settle
                self.set_speed(step)
                settle = args.settle
                if not args.dry_run:
                    time.sleep(settle)
                else:
                    self.log(f"  [dry-run] settle {settle}s")

                # Capture audio on first pass (loco at steady speed)
                if p == 0 and getattr(args, 'audio', False):
                    if args.dry_run:
                        audio_data = {"rms_db": -42.0, "peak_db": -35.0}
                        self.log(f"  [dry-run] Audio: rms=-42.0 dB")
                    else:
                        audio_data = self.ctrl.wait_for_audio(timeout=5.0)
                        if audio_data:
                            self.log(f"  Audio: rms={audio_data.get('rms_db')} dB, "
                                     f"peak={audio_data.get('peak_db')} dB")

                # Arm and measure
                result = self.arm_and_measure(timeout=args.timeout)
                self.total_passes += 1

                if result and "avg_speed_mph" in result:
                    speed = result.get("avg_speed_mph", "?")
                    sensors = result.get("sensors_triggered", "?")
                    direction = result.get("direction", "?")
                    self.log(f"  Pass {p+1}: {speed} mph {direction} "
                             f"({sensors} sensors) [{dir_str}]")
                    pass_results.append(result)
                else:
                    self.log(f"  Pass {p+1}: NO DETECTION [{dir_str}]")
                    pass_results.append(None)

                # Stop and reverse for shuttle
                self.stop_loco()
                if not args.dry_run:
                    time.sleep(1)
                self.toggle_direction()
                if not args.dry_run:
                    time.sleep(1)

            # Aggregate results for this step
            entry = self._aggregate_step(step, pass_results, audio_data)
            self.results.append(entry)

        # Stop loco at end
        self.stop_loco()
        self.log("=== Sweep complete ===")

    def _aggregate_step(self, step, pass_results, audio_data=None):
        """Aggregate multiple passes for a single speed step."""
        valid = [r for r in pass_results if r and "avg_speed_mph" in r]

        entry = {
            "speed_step": step,
            "throttle_pct": step_to_pct(step),
            "passes": len(pass_results),
            "valid_passes": len(valid),
        }

        # Audio data (captured once per step)
        if audio_data:
            entry["audio_rms_db"] = audio_data.get("rms_db")
            entry["audio_peak_db"] = audio_data.get("peak_db")

        if valid:
            # Average the speed across passes
            speeds = []
            for r in valid:
                try:
                    speeds.append(float(r["avg_speed_mph"]))
                except (ValueError, TypeError):
                    pass

            if speeds:
                entry["avg_scale_mph"] = round(sum(speeds) / len(speeds), 1)

            # Use the last valid pass for interval detail
            last = valid[-1]
            entry["direction"] = last.get("direction", "unknown")
            if "speeds_mph" in last:
                entry["interval_speeds_mph"] = [
                    float(s) if isinstance(s, str) else s
                    for s in last["speeds_mph"]
                ]

            # Store all raw passes for later analysis
            entry["raw_passes"] = valid
        else:
            entry["avg_scale_mph"] = None
            entry["direction"] = "none"
            entry["error"] = "no_detection"

        return entry

    def build_output(self):
        """Build the complete calibration output JSON."""
        duration = time.time() - self.start_time

        # Compute summary statistics
        valid_entries = [e for e in self.results if e.get("avg_scale_mph") is not None]
        speeds = [e["avg_scale_mph"] for e in valid_entries]

        summary = {
            "total_steps_measured": len(self.results),
            "valid_steps": len(valid_entries),
            "total_passes": self.total_passes,
            "duration_sec": round(duration, 1),
        }

        if speeds:
            summary["min_reliable_speed_mph"] = min(speeds)
            summary["max_speed_mph"] = max(speeds)

        if self.start_of_motion:
            summary["min_speed_step_forward"] = self.start_of_motion["forward_step"]
            summary["min_speed_step_reverse"] = self.start_of_motion["reverse_step"]
            summary["dead_steps_forward"] = self.start_of_motion["forward_step"] - 1
            summary["dead_steps_reverse"] = self.start_of_motion["reverse_step"] - 1

        # Find speed at midpoint and max
        step_63 = next((e for e in self.results if e["speed_step"] == 63), None)
        step_126 = next((e for e in self.results if e["speed_step"] == 126), None)
        if step_63 and step_63.get("avg_scale_mph"):
            summary["speed_at_step_63_mph"] = step_63["avg_scale_mph"]
        if step_126 and step_126.get("avg_scale_mph"):
            summary["speed_at_step_126_mph"] = step_126["avg_scale_mph"]

        output = {
            "address": self.args.address,
            "date": datetime.now(timezone.utc).isoformat(),
            "scale": "HO",
            "scale_factor": HO_SCALE_FACTOR,
            "sensor_spacing_mm": DEFAULT_SENSOR_SPACING_MM,
            "start_of_motion": self.start_of_motion,
            "speed_table": self.results,
            "summary": summary,
        }

        if self.aborted:
            output["aborted"] = True
            output["abort_reason"] = "user_interrupt"

        return output

    def save_output(self, output):
        """Save calibration results to JSON file."""
        path = self.args.output
        if not path:
            os.makedirs("calibration-data", exist_ok=True)
            path = f"calibration-data/speed_table_{self.args.address}.json"

        # Don't overwrite existing — add timestamp suffix
        if os.path.exists(path):
            base, ext = os.path.splitext(path)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            path = f"{base}_{ts}{ext}"

        with open(path, "w") as f:
            json.dump(output, f, indent=2)

        self.log(f"Results saved to {path}")
        return path

    def save_to_db(self, db, output):
        """Store calibration results in the SQLite database."""
        args = self.args
        roster_id = args.roster_id or f"addr:{args.address}"
        duration = output.get("summary", {}).get("duration_sec")

        loco_id = db.get_or_create_loco(roster_id, args.address)
        run_id = db.create_run(
            loco_id, run_type="speed",
            direction="both",
            step_increment=args.step_inc,
            settle_ms=int(args.settle * 1000),
        )

        # Store motion thresholds
        if self.start_of_motion:
            db.set_motion_threshold(run_id, "forward",
                                    self.start_of_motion["forward_step"])
            db.set_motion_threshold(run_id, "reverse",
                                    self.start_of_motion["reverse_step"])

        # Store speed entries
        for entry in self.results:
            db.add_speed_entry(
                run_id,
                speed_step=entry["speed_step"],
                throttle_pct=entry.get("throttle_pct"),
                speed_mph=entry.get("avg_scale_mph"),
                audio_rms_db=entry.get("audio_rms_db"),
                audio_peak_db=entry.get("audio_peak_db"),
            )

        if self.aborted:
            db.abort_run(run_id, duration_sec=duration)
        else:
            db.complete_run(run_id, duration_sec=duration)

        self.log(f"Stored in DB: loco '{roster_id}' run #{run_id}")
        return run_id

    def validate_roster(self):
        """Check that the roster_id exists in JMRI. Returns True if OK or skipped."""
        args = self.args
        if not args.roster_id or args.no_validate_roster or args.dry_run:
            if args.dry_run and args.roster_id:
                self.log(f"[dry-run] Would validate roster entry '{args.roster_id}'")
            return True

        self.log(f"Validating roster entry '{args.roster_id}'...")
        result = self.ctrl.query_roster(roster_id=args.roster_id)
        if result and result.get("found"):
            entry = result["entries"][0]
            self.log(f"  Roster: {entry['roster_id']}, addr={entry.get('address')}, "
                     f"decoder={entry.get('decoder_model', '?')}")
            # Update CalibrationDB with decoder type from roster
            if entry.get("decoder_model"):
                db = CalibrationDB(args.db)
                try:
                    db.get_or_create_loco(
                        args.roster_id, args.address,
                        decoder_type=entry["decoder_model"])
                finally:
                    db.close()
            return True
        elif result:
            self.log(f"  WARNING: {result.get('error', 'Roster entry not found')}")
            self.log("  Profile import will fail after calibration")
            return True  # warning only, don't abort
        else:
            self.log("  WARNING: No response from JMRI bridge (timeout)")
            self.log("  Is jmri_throttle_bridge.py running?")
            return True  # warning only

    def import_to_jmri(self, output):
        """Import the speed profile into the JMRI roster entry."""
        args = self.args
        roster_id = args.roster_id
        if not roster_id:
            self.log("Skipping JMRI import: no --roster-id specified")
            return False

        speed_table = output.get("speed_table", [])
        if not speed_table:
            self.log("Skipping JMRI import: no speed data")
            return False

        # Build import entries: forward + reverse per step
        entries = []
        for step_data in speed_table:
            speed_mph = step_data.get("avg_scale_mph")
            if speed_mph is None:
                continue
            speed_step = step_data["speed_step"]
            entries.append({"speed_step": speed_step, "speed_mph": speed_mph,
                            "direction": "forward"})
            entries.append({"speed_step": speed_step, "speed_mph": speed_mph,
                            "direction": "reverse"})

        self.log(f"Importing {len(entries)} speed entries to JMRI roster '{roster_id}'...")
        result = self.ctrl.import_speed_profile(
            roster_id, entries,
            scale_factor=output.get("scale_factor", HO_SCALE_FACTOR),
            clear_existing=True, timeout=30.0)

        if result and result.get("success"):
            self.log(f"  JMRI import OK: {result.get('entries_imported')} entries")
            return True
        elif result:
            self.log(f"  JMRI import FAILED: {result.get('error', 'unknown')}")
            return False
        else:
            self.log("  JMRI import FAILED: no response (timeout)")
            return False

    def compare_audio_to_reference(self, db_path="calibration-data/calibration.db"):
        """Compare this run's audio to the fleet reference and print recommendation."""
        args = self.args
        db = CalibrationDB(db_path)
        try:
            ref = db.get_audio_reference()
            if not ref:
                self.log("No audio reference loco set — skip comparison")
                self.log("  Set one with: audio_calibrate.py --set-reference ROSTER_ID")
                return

            ref_run = db.get_latest_run(ref["roster_id"], complete_only=True)
            target_run = db.get_latest_run(args.roster_id, complete_only=True)
            if not ref_run or not target_run:
                self.log("Audio comparison skipped: missing run data")
                return

            delta = db.compare_audio_to_reference(target_run["id"], ref_run["id"])
            if delta is None:
                self.log("Audio comparison skipped: no overlapping audio data")
                return

            self.log(f"\n=== Audio Comparison ===")
            self.log(f"  vs reference '{ref['roster_id']}': {delta:+.1f} dB")
            if abs(delta) > 1.0:
                self.log(f"  Run: audio_calibrate.py --roster-id '{args.roster_id}' --apply")
            else:
                self.log(f"  Within tolerance (< 1 dB)")
        finally:
            db.close()

    def run(self):
        """Execute the full calibration sequence."""
        args = self.args

        self.log(f"Speed Calibration — Address {args.address}")
        self.log(f"Broker: {args.broker}:{args.port}")
        if args.dry_run:
            self.log("*** DRY RUN — no MQTT messages will be sent ***")

        # Connect to MQTT
        if not args.dry_run:
            if not self.ctrl.connect():
                self.log("ERROR: Failed to connect to MQTT broker")
                return False
            time.sleep(1)

            # Validate roster entry before starting
            self.validate_roster()

            # Acquire throttle
            self.log(f"Acquiring throttle for address {args.address}...")
            if not self.ctrl.acquire(args.address):
                self.log("ERROR: Failed to acquire throttle")
                return False
            time.sleep(0.5)
        else:
            self.log("[dry-run] Would connect and acquire throttle")
            self.validate_roster()

        try:
            # Phase 1: Start-of-motion detection
            if not args.skip_start_of_motion:
                self.find_start_of_motion()
            else:
                self.log("Skipping start-of-motion detection")
                self.start_of_motion = None

            # Phase 2: Full speed sweep
            self.run_sweep()

        except KeyboardInterrupt:
            self.log("\n!!! INTERRUPTED — stopping loco and saving partial results")
            self.aborted = True
            self.stop_loco()

        # Save results (JSON)
        output = self.build_output()
        path = self.save_output(output)

        # Save results (SQLite)
        db = CalibrationDB(args.db)
        try:
            self.save_to_db(db, output)
        finally:
            db.close()

        # Import to JMRI roster
        if not args.no_import_profile and not self.aborted and not args.dry_run:
            self.import_to_jmri(output)
        elif args.dry_run and args.roster_id and not args.no_import_profile:
            self.log(f"[dry-run] Would import speed profile to JMRI roster '{args.roster_id}'")

        # Audio comparison
        if getattr(args, 'compare_audio', False) and args.roster_id:
            self.compare_audio_to_reference(db_path=args.db)

        # Summary
        summary = output.get("summary", {})
        self.log("=== Calibration Summary ===")
        self.log(f"  Address: {args.address}")
        self.log(f"  Steps measured: {summary.get('valid_steps', 0)} / "
                 f"{summary.get('total_steps_measured', 0)}")
        self.log(f"  Total passes: {summary.get('total_passes', 0)}")
        self.log(f"  Duration: {summary.get('duration_sec', 0):.0f}s")
        if "min_reliable_speed_mph" in summary:
            self.log(f"  Speed range: {summary['min_reliable_speed_mph']:.1f} - "
                     f"{summary.get('max_speed_mph', 0):.1f} mph")
        if self.start_of_motion:
            self.log(f"  Start-of-motion: fwd={self.start_of_motion['forward_step']}, "
                     f"rev={self.start_of_motion['reverse_step']}")
        self.log(f"  Output: {path}")

        # Cleanup
        if not args.dry_run:
            self.ctrl.release()
            time.sleep(0.3)
            self.ctrl.disconnect()

        return True


def main():
    parser = argparse.ArgumentParser(
        description="Automated Locomotive Speed Calibration",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --address 3
  %(prog)s --address 1234 --broker 10.0.0.5 --passes 2
  %(prog)s --address 3 --dry-run
  %(prog)s --address 3 --skip-start-of-motion --min-step 10 --max-step 50
        """)

    parser.add_argument("--address", type=int, required=True,
                        help="DCC address of locomotive to calibrate")
    parser.add_argument("--broker", default=None,
                        help="MQTT broker address (auto-detected from JMRI config)")
    parser.add_argument("--port", type=int, default=None,
                        help="MQTT broker port (auto-detected from JMRI config)")
    parser.add_argument("--prefix", default=None,
                        help="MQTT topic prefix (auto-detected from JMRI config)")
    parser.add_argument("--min-step", type=int, default=1,
                        help="Starting speed step (default: 1)")
    parser.add_argument("--max-step", type=int, default=126,
                        help="Ending speed step (default: 126)")
    parser.add_argument("--step-inc", type=int, default=1,
                        help="Speed step increment (default: 1)")
    parser.add_argument("--settle", type=float, default=5.0,
                        help="Seconds to wait after speed change (default: 5)")
    parser.add_argument("--passes", type=int, default=1,
                        help="Passes per speed step (default: 1)")
    parser.add_argument("--low-passes", type=int, default=3,
                        help="Passes for low-speed steps near start-of-motion (default: 3)")
    parser.add_argument("--low-range", type=int, default=5,
                        help="Steps above start-of-motion to use --low-passes (default: 5)")
    parser.add_argument("--timeout", type=float, default=90.0,
                        help="Max seconds to wait for sensor result (default: 90)")
    parser.add_argument("--output", default=None,
                        help="Output file path (default: calibration-data/speed_table_ADDR.json)")
    parser.add_argument("--skip-start-of-motion", action="store_true",
                        help="Skip binary search, start sweep at --min-step")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print planned operations without sending MQTT messages")
    parser.add_argument("--roster-id", default=None,
                        help="JMRI roster ID (default: 'addr:ADDRESS')")
    parser.add_argument("--db", default="calibration-data/calibration.db",
                        help="SQLite database path (default: calibration-data/calibration.db)")
    parser.add_argument("--no-import-profile", action="store_true",
                        help="Skip JMRI speed profile import after run")
    parser.add_argument("--no-validate-roster", action="store_true",
                        help="Skip pre-run roster validation")
    parser.add_argument("--audio", action="store_true",
                        help="Capture audio levels at each speed step")
    parser.add_argument("--compare-audio", action="store_true",
                        help="Compare audio to reference after run (implies --audio)")

    args = parser.parse_args()

    # --compare-audio implies --audio
    if args.compare_audio:
        args.audio = True
    resolve_mqtt_args(args)

    # Create controller (won't connect until run())
    ctrl = LocoController(args.broker, args.port, prefix=args.prefix)

    calibrator = SpeedCalibrator(ctrl, args)
    success = calibrator.run()

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
