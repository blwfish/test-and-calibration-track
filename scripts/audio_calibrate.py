#!/usr/bin/env python3
"""
Audio Calibration — Match locomotive decoder volume to fleet reference.

Compares a target loco's audio levels (from its latest calibration run)
to a reference loco, computes the master volume CV delta, and optionally
writes the new value via JMRI service mode programming.

Prerequisites:
  pip3 install paho-mqtt

  Calibration data must already exist:
    python3 calibrate_speed.py --address X --roster-id "NAME" --audio

  A reference loco must be designated:
    python3 audio_calibrate.py --set-reference "NAME"

Usage:
  python3 audio_calibrate.py --roster-id "SP 4449"
  python3 audio_calibrate.py --roster-id "SP 4449" --apply
  python3 audio_calibrate.py --roster-id "SP 4449" --reference-id "UP 844"
  python3 audio_calibrate.py --set-reference "UP 844"
  python3 audio_calibrate.py --list
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from calibration_db import CalibrationDB
from decoder_volume import lookup_decoder, compute_new_cv

try:
    from loco_control import LocoController, resolve_mqtt_args
except ImportError:
    LocoController = None
    resolve_mqtt_args = None


def mean_audio(curve):
    """Mean audio_rms_db from a list of {speed_step, audio_rms_db} dicts."""
    if not curve:
        return None
    vals = [p["audio_rms_db"] for p in curve if p.get("audio_rms_db") is not None]
    return sum(vals) / len(vals) if vals else None


def grade_volume(mean_db, median, p25, p75):
    """Assign a volume grade based on fleet statistics."""
    if median is None or mean_db is None:
        return "unknown"
    if mean_db > median + 10:
        return "EXCESSIVE"
    if mean_db > p75:
        return "loud"
    if mean_db < p25:
        return "quiet"
    return "normal"


def percentile(sorted_vals, pct):
    """Simple percentile from a sorted list."""
    if not sorted_vals:
        return None
    idx = int(len(sorted_vals) * pct / 100.0)
    idx = max(0, min(idx, len(sorted_vals) - 1))
    return sorted_vals[idx]


def list_fleet_audio(db):
    """List all locos with audio data and volume grades."""
    locos = db.list_locos()
    if not locos:
        print("No locos in database")
        return

    # Collect audio means for each loco
    entries = []
    for loco in locos:
        run = db.get_latest_run(loco["roster_id"], complete_only=True)
        mean_db = None
        if run:
            curve = db.get_audio_curve(run["id"])
            mean_db = mean_audio(curve)
        entries.append({"loco": loco, "mean_db": mean_db})

    # Compute fleet statistics
    db_values = sorted(e["mean_db"] for e in entries if e["mean_db"] is not None)
    if db_values:
        median = percentile(db_values, 50)
        p25 = percentile(db_values, 25)
        p75 = percentile(db_values, 75)
    else:
        median = p25 = p75 = None

    # Print table
    ref = db.get_audio_reference()
    ref_id = ref["roster_id"] if ref else None

    print(f"{'Roster ID':<20} {'Addr':>5} {'Decoder':<20} {'Audio dB':>9} "
          f"{'Grade':<10} {'Ref':>3}")
    print("-" * 72)

    for e in entries:
        loco = e["loco"]
        rid = loco["roster_id"]
        addr = loco["address"]
        dec = (loco.get("decoder_type") or "")[:20]
        is_ref = "*" if rid == ref_id else ""

        if e["mean_db"] is not None:
            db_str = f"{e['mean_db']:.1f}"
            g = grade_volume(e["mean_db"], median, p25, p75)
        else:
            db_str = "---"
            g = "no data"

        print(f"{rid:<20} {addr:>5} {dec:<20} {db_str:>9} {g:<10} {is_ref:>3}")

    if median is not None:
        print(f"\nFleet: median={median:.1f} dB, 25th={p25:.1f}, "
              f"75th={p75:.1f} ({len(db_values)} locos with audio)")


def set_reference(db, roster_id):
    """Mark a loco as the fleet audio reference."""
    loco = db.get_loco(roster_id)
    if not loco:
        print(f"ERROR: Loco '{roster_id}' not found in database")
        return False

    # Verify audio data exists
    run = db.get_latest_run(roster_id, complete_only=True)
    if run:
        curve = db.get_audio_curve(run["id"])
        if not curve:
            print(f"WARNING: No audio data for '{roster_id}' — run calibration with --audio")
    else:
        print(f"WARNING: No completed runs for '{roster_id}'")

    db.set_audio_reference(roster_id)
    print(f"Audio reference set to '{roster_id}'")
    return True


def compare_and_recommend(db, ctrl, target_roster_id, ref_roster_id,
                          dry_run=False, apply=False):
    """Compare target loco audio to reference and recommend CV change."""
    # 1. Look up locos
    target = db.get_loco(target_roster_id)
    if not target:
        print(f"ERROR: Loco '{target_roster_id}' not found in database")
        return False

    ref = db.get_loco(ref_roster_id)
    if not ref:
        print(f"ERROR: Reference loco '{ref_roster_id}' not found")
        return False

    # 2. Get latest runs
    target_run = db.get_latest_run(target_roster_id, complete_only=True)
    ref_run = db.get_latest_run(ref_roster_id, complete_only=True)

    if not target_run:
        print(f"ERROR: No completed runs for '{target_roster_id}'")
        return False
    if not ref_run:
        print(f"ERROR: No completed runs for '{ref_roster_id}'")
        return False

    # 3. Verify audio data
    target_curve = db.get_audio_curve(target_run["id"])
    ref_curve = db.get_audio_curve(ref_run["id"])
    if not target_curve:
        print(f"ERROR: No audio data in run #{target_run['id']} for '{target_roster_id}'")
        print("  Re-run calibration with --audio flag")
        return False
    if not ref_curve:
        print(f"ERROR: No audio data in run #{ref_run['id']} for '{ref_roster_id}'")
        return False

    # 4. Compare
    delta_db = db.compare_audio_to_reference(target_run["id"], ref_run["id"])
    if delta_db is None:
        print("ERROR: No overlapping speed steps between runs")
        return False

    target_mean = mean_audio(target_curve)
    ref_mean = mean_audio(ref_curve)

    print(f"Audio comparison: '{target_roster_id}' vs reference '{ref_roster_id}'")
    if target_mean is not None:
        print(f"  Target mean:    {target_mean:.1f} dB")
    if ref_mean is not None:
        print(f"  Reference mean: {ref_mean:.1f} dB")
    delta_dir = "(target is LOUDER)" if delta_db > 0 else (
        "(target is QUIETER)" if delta_db < 0 else "(matched)")
    print(f"  Delta:          {delta_db:+.1f} dB {delta_dir}")

    # 5. Decoder lookup
    decoder_type = target.get("decoder_type")
    if not decoder_type:
        print(f"\n  WARNING: No decoder type set for '{target_roster_id}'")
        print("  Cannot compute CV recommendation without decoder info")
        adj_id = db.add_audio_adjustment(
            target_run["id"], ref_run["id"], delta_db=delta_db)
        print(f"  Stored delta in adjustment #{adj_id}")
        return True

    vol_info = lookup_decoder(decoder_type)
    if not vol_info:
        print(f"\n  WARNING: Decoder '{decoder_type}' not in volume CV table")
        print("  Known: LokSound 5, Tsunami2, Econami, Digitrax SDH, "
              "BLI Paragon, TCS WOWSound")
        adj_id = db.add_audio_adjustment(
            target_run["id"], ref_run["id"], delta_db=delta_db)
        print(f"  Stored delta in adjustment #{adj_id}")
        return True

    cv_num = vol_info["cv"]
    cv_min = vol_info["min"]
    cv_max = vol_info["max"]

    print(f"\n  Decoder: {decoder_type} -> {vol_info['decoder_name']}")
    print(f"  Volume CV: {cv_num} (range {cv_min}-{cv_max})")

    # 6. Read current CV value
    if dry_run:
        current_cv = vol_info["default"]
        print(f"  [dry-run] Assuming CV {cv_num} = {current_cv} (default)")
    else:
        if ctrl is None:
            print("  ERROR: MQTT not available — cannot read CV")
            return False
        print(f"  Reading CV {cv_num}...")
        result = ctrl.read_cv(cv_num, timeout=30.0)
        if not result or result.get("status") != "OK":
            status = result.get("status", "timeout") if result else "timeout"
            print(f"  ERROR: CV read failed ({status})")
            print("  Is the loco on the programming track?")
            return False
        current_cv = result["value"]
        print(f"  Current CV {cv_num} = {current_cv}")

    # 7. Compute new value
    new_cv = compute_new_cv(current_cv, delta_db, cv_min, cv_max)

    print(f"  Recommended: CV {cv_num} = {new_cv} (was {current_cv})")
    if new_cv == current_cv:
        print(f"  No change needed (delta {delta_db:+.1f} dB rounds to same value)")

    # 8. Store recommendation
    adj_id = db.add_audio_adjustment(
        target_run["id"], ref_run["id"], delta_db=delta_db,
        recommended_cv=cv_num, recommended_value=new_cv)
    print(f"  Stored adjustment #{adj_id}")

    # 9. Apply if requested
    if apply and not dry_run and new_cv != current_cv:
        if ctrl is None:
            print("  ERROR: MQTT not available — cannot write CV")
            return False
        print(f"\n  Writing CV {cv_num} = {new_cv}...")
        result = ctrl.write_cv(cv_num, new_cv, timeout=30.0)
        if result and result.get("status") == "OK":
            print(f"  CV {cv_num} written successfully")
            db.mark_adjustment_applied(adj_id)
        else:
            status = result.get("status", "timeout") if result else "timeout"
            print(f"  ERROR: CV write failed ({status})")
            return False
    elif apply and dry_run:
        print(f"\n  [dry-run] Would write CV {cv_num} = {new_cv}")

    return True


def main():
    parser = argparse.ArgumentParser(
        description="Audio Calibration — Match decoder volume to fleet reference",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --list
  %(prog)s --set-reference "SP 4449"
  %(prog)s --roster-id "UP 844"
  %(prog)s --roster-id "UP 844" --apply
  %(prog)s --roster-id "UP 844" --reference-id "SP 4449"
  %(prog)s --roster-id "UP 844" --dry-run
        """)

    parser.add_argument("--roster-id", default=None,
                        help="Target loco roster ID to calibrate")
    parser.add_argument("--reference-id", default=None,
                        help="Reference loco roster ID (uses DB default if omitted)")
    parser.add_argument("--set-reference", default=None, metavar="ROSTER_ID",
                        help="Mark a loco as the fleet audio reference")
    parser.add_argument("--list", action="store_true",
                        help="List all locos with audio data and volume grades")
    parser.add_argument("--apply", action="store_true",
                        help="Write the recommended CV value to the decoder")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show recommendations without MQTT (assumes default CV)")
    parser.add_argument("--broker", default=None,
                        help="MQTT broker address (auto-detected from JMRI config)")
    parser.add_argument("--port", type=int, default=None,
                        help="MQTT broker port (auto-detected from JMRI config)")
    parser.add_argument("--prefix", default=None,
                        help="MQTT topic prefix (auto-detected from JMRI config)")
    parser.add_argument("--db", default="calibration-data/calibration.db",
                        help="SQLite database path")

    args = parser.parse_args()

    db = CalibrationDB(args.db)

    try:
        # --set-reference
        if args.set_reference:
            set_reference(db, args.set_reference)
            return

        # --list
        if args.list:
            list_fleet_audio(db)
            return

        # --roster-id (main operation)
        if not args.roster_id:
            parser.print_help()
            print("\nERROR: --roster-id, --list, or --set-reference required")
            sys.exit(1)

        # Determine reference
        ref_id = args.reference_id
        if not ref_id:
            ref = db.get_audio_reference()
            if not ref:
                print("ERROR: No audio reference loco set")
                print("  Set one with: --set-reference ROSTER_ID")
                sys.exit(1)
            ref_id = ref["roster_id"]

        # Connect to MQTT if needed (for CV read/write)
        ctrl = None
        if not args.dry_run:
            if LocoController is None:
                print("ERROR: paho-mqtt not installed. Run: pip3 install paho-mqtt")
                print("  Use --dry-run to see recommendations without MQTT")
                sys.exit(1)
            if resolve_mqtt_args is not None:
                resolve_mqtt_args(args)
            ctrl = LocoController(args.broker, args.port, prefix=args.prefix)
            if not ctrl.connect():
                print("ERROR: Failed to connect to MQTT broker")
                sys.exit(1)
            import time
            time.sleep(0.5)

        success = compare_and_recommend(
            db, ctrl, args.roster_id, ref_id,
            dry_run=args.dry_run, apply=args.apply)

        if ctrl:
            ctrl.disconnect()

        sys.exit(0 if success else 1)

    finally:
        db.close()


if __name__ == "__main__":
    main()
