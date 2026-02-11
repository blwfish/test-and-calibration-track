#!/usr/bin/env python3
"""Tests for calibration_db.py"""

import os
import tempfile
import unittest

from calibration_db import CalibrationDB


class TestCalibrationDB(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.db = CalibrationDB(self.tmp.name)

    def tearDown(self):
        self.db.close()
        os.unlink(self.tmp.name)

    # --- Loco tests ---

    def test_create_loco(self):
        loco_id = self.db.get_or_create_loco("SP 4449", 4449)
        self.assertIsInstance(loco_id, int)
        self.assertGreater(loco_id, 0)

    def test_get_or_create_returns_same_id(self):
        id1 = self.db.get_or_create_loco("SP 4449", 4449)
        id2 = self.db.get_or_create_loco("SP 4449", 4449)
        self.assertEqual(id1, id2)

    def test_get_or_create_updates_decoder_type(self):
        self.db.get_or_create_loco("SP 4449", 4449, decoder_type="Tsunami2")
        loco = self.db.get_loco("SP 4449")
        self.assertEqual(loco["decoder_type"], "Tsunami2")

        self.db.get_or_create_loco("SP 4449", 4449, decoder_type="LokSound 5")
        loco = self.db.get_loco("SP 4449")
        self.assertEqual(loco["decoder_type"], "LokSound 5")

    def test_get_loco_not_found(self):
        self.assertIsNone(self.db.get_loco("nonexistent"))

    def test_list_locos(self):
        self.db.get_or_create_loco("SP 4449", 4449)
        self.db.get_or_create_loco("UP 844", 844)
        locos = self.db.list_locos()
        self.assertEqual(len(locos), 2)
        roster_ids = [l["roster_id"] for l in locos]
        self.assertIn("SP 4449", roster_ids)
        self.assertIn("UP 844", roster_ids)

    def test_audio_reference(self):
        self.db.get_or_create_loco("SP 4449", 4449)
        self.db.get_or_create_loco("UP 844", 844)

        self.assertIsNone(self.db.get_audio_reference())

        self.db.set_audio_reference("SP 4449")
        ref = self.db.get_audio_reference()
        self.assertEqual(ref["roster_id"], "SP 4449")

        # Setting a new reference clears the old one
        self.db.set_audio_reference("UP 844")
        ref = self.db.get_audio_reference()
        self.assertEqual(ref["roster_id"], "UP 844")
        old = self.db.get_loco("SP 4449")
        self.assertEqual(old["is_audio_reference"], 0)

    # --- Run tests ---

    def test_create_and_get_run(self):
        loco_id = self.db.get_or_create_loco("SP 4449", 4449)
        run_id = self.db.create_run(loco_id, "speed", direction="both",
                                    step_increment=5, settle_ms=3000)
        self.assertGreater(run_id, 0)

        run = self.db.get_run(run_id)
        self.assertEqual(run["loco_id"], loco_id)
        self.assertEqual(run["run_type"], "speed")
        self.assertEqual(run["direction"], "both")
        self.assertEqual(run["step_increment"], 5)
        self.assertEqual(run["complete"], 0)

    def test_complete_run(self):
        loco_id = self.db.get_or_create_loco("SP 4449", 4449)
        run_id = self.db.create_run(loco_id, "speed")
        self.db.complete_run(run_id, duration_sec=120.5)

        run = self.db.get_run(run_id)
        self.assertEqual(run["complete"], 1)
        self.assertAlmostEqual(run["duration_sec"], 120.5)

    def test_abort_run(self):
        loco_id = self.db.get_or_create_loco("SP 4449", 4449)
        run_id = self.db.create_run(loco_id, "speed")
        self.db.abort_run(run_id, duration_sec=45.0)

        run = self.db.get_run(run_id)
        self.assertEqual(run["aborted"], 1)

    def test_list_runs(self):
        lid1 = self.db.get_or_create_loco("SP 4449", 4449)
        lid2 = self.db.get_or_create_loco("UP 844", 844)
        self.db.create_run(lid1, "speed")
        self.db.create_run(lid1, "full")
        self.db.create_run(lid2, "speed")

        all_runs = self.db.list_runs()
        self.assertEqual(len(all_runs), 3)

        sp_runs = self.db.list_runs(roster_id="SP 4449")
        self.assertEqual(len(sp_runs), 2)

        speed_runs = self.db.list_runs(run_type="speed")
        self.assertEqual(len(speed_runs), 2)

    def test_get_latest_run(self):
        loco_id = self.db.get_or_create_loco("SP 4449", 4449)
        r1 = self.db.create_run(loco_id, "speed")
        self.db.complete_run(r1)
        r2 = self.db.create_run(loco_id, "speed")
        self.db.complete_run(r2)

        latest = self.db.get_latest_run("SP 4449")
        self.assertEqual(latest["id"], r2)

    def test_get_latest_run_complete_only(self):
        loco_id = self.db.get_or_create_loco("SP 4449", 4449)
        r1 = self.db.create_run(loco_id, "speed")
        self.db.complete_run(r1)
        r2 = self.db.create_run(loco_id, "speed")
        # r2 not completed

        latest = self.db.get_latest_run("SP 4449", complete_only=True)
        self.assertEqual(latest["id"], r1)

    # --- Speed entries ---

    def test_add_and_get_entries(self):
        loco_id = self.db.get_or_create_loco("SP 4449", 4449)
        run_id = self.db.create_run(loco_id, "full")

        self.db.add_speed_entry(run_id, speed_step=10, throttle_pct=7.9,
                                speed_mph=5.2, pull_grams=2.1,
                                vib_peak_to_peak=150, vib_rms=42.3,
                                audio_rms_db=-45.0, audio_peak_db=-38.0)
        self.db.add_speed_entry(run_id, speed_step=20, throttle_pct=15.9,
                                speed_mph=12.1, pull_grams=5.3)

        entries = self.db.get_speed_entries(run_id)
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0]["speed_step"], 10)
        self.assertAlmostEqual(entries[0]["speed_mph"], 5.2)
        self.assertAlmostEqual(entries[0]["audio_rms_db"], -45.0)
        self.assertEqual(entries[1]["speed_step"], 20)
        self.assertIsNone(entries[1]["audio_rms_db"])

    def test_add_entries_batch(self):
        loco_id = self.db.get_or_create_loco("SP 4449", 4449)
        run_id = self.db.create_run(loco_id, "full")

        entries = [
            {"speed_step": 5, "throttle_pct": 4.0, "speed_mph": 2.1},
            {"speed_step": 10, "throttle_pct": 7.9, "speed_mph": 5.2,
             "pull_grams": 3.0, "audio_rms_db": -42.0},
            {"speed_step": 15, "throttle_pct": 11.9, "speed_mph": 8.7},
        ]
        self.db.add_speed_entries_batch(run_id, entries)

        stored = self.db.get_speed_entries(run_id)
        self.assertEqual(len(stored), 3)
        self.assertAlmostEqual(stored[1]["pull_grams"], 3.0)

    def test_entry_replace_on_duplicate(self):
        loco_id = self.db.get_or_create_loco("SP 4449", 4449)
        run_id = self.db.create_run(loco_id, "speed")

        self.db.add_speed_entry(run_id, speed_step=10, speed_mph=5.0)
        self.db.add_speed_entry(run_id, speed_step=10, speed_mph=5.5)

        entries = self.db.get_speed_entries(run_id)
        self.assertEqual(len(entries), 1)
        self.assertAlmostEqual(entries[0]["speed_mph"], 5.5)

    # --- Motion thresholds ---

    def test_motion_thresholds(self):
        loco_id = self.db.get_or_create_loco("SP 4449", 4449)
        run_id = self.db.create_run(loco_id, "speed")

        self.db.set_motion_threshold(run_id, "forward", 6)
        self.db.set_motion_threshold(run_id, "reverse", 8)

        thresholds = self.db.get_motion_thresholds(run_id)
        self.assertEqual(thresholds["forward"], 6)
        self.assertEqual(thresholds["reverse"], 8)

    # --- Audio adjustments ---

    def test_audio_adjustment(self):
        lid = self.db.get_or_create_loco("SP 4449", 4449)
        ref_run = self.db.create_run(lid, "full")
        test_run = self.db.create_run(lid, "full")

        adj_id = self.db.add_audio_adjustment(
            test_run, ref_run, delta_db=3.5,
            recommended_cv=63, recommended_value=96
        )
        self.assertGreater(adj_id, 0)

        self.db.mark_adjustment_applied(adj_id)
        row = self.db.conn.execute(
            "SELECT applied, applied_timestamp FROM audio_adjustments WHERE id = ?",
            (adj_id,)
        ).fetchone()
        self.assertEqual(row["applied"], 1)
        self.assertIsNotNone(row["applied_timestamp"])

    # --- Query helpers ---

    def test_audio_curve(self):
        lid = self.db.get_or_create_loco("SP 4449", 4449)
        run_id = self.db.create_run(lid, "full")
        self.db.add_speed_entry(run_id, 10, audio_rms_db=-45.0)
        self.db.add_speed_entry(run_id, 20, audio_rms_db=-40.0)
        self.db.add_speed_entry(run_id, 30)  # No audio

        curve = self.db.get_audio_curve(run_id)
        self.assertEqual(len(curve), 2)
        self.assertEqual(curve[0]["speed_step"], 10)

    def test_pull_curve(self):
        lid = self.db.get_or_create_loco("SP 4449", 4449)
        run_id = self.db.create_run(lid, "full")
        self.db.add_speed_entry(run_id, 10, pull_grams=2.1)
        self.db.add_speed_entry(run_id, 20, pull_grams=5.3)

        curve = self.db.get_pull_curve(run_id)
        self.assertEqual(len(curve), 2)

    def test_speed_profile(self):
        lid = self.db.get_or_create_loco("SP 4449", 4449)
        run_id = self.db.create_run(lid, "speed")
        self.db.add_speed_entry(run_id, 10, throttle_pct=7.9, speed_mph=5.2)
        self.db.add_speed_entry(run_id, 20, throttle_pct=15.9, speed_mph=12.1)

        profile = self.db.get_speed_profile(run_id)
        self.assertEqual(len(profile), 2)
        self.assertAlmostEqual(profile[0]["speed_mph"], 5.2)

    def test_compare_audio_to_reference(self):
        lid1 = self.db.get_or_create_loco("SP 4449", 4449)
        lid2 = self.db.get_or_create_loco("UP 844", 844)
        ref_run = self.db.create_run(lid1, "full")
        test_run = self.db.create_run(lid2, "full")

        # Reference: -45, -40, -38 dB at steps 10, 20, 30
        self.db.add_speed_entry(ref_run, 10, audio_rms_db=-45.0)
        self.db.add_speed_entry(ref_run, 20, audio_rms_db=-40.0)
        self.db.add_speed_entry(ref_run, 30, audio_rms_db=-38.0)

        # Test loco: 3 dB louder across the board
        self.db.add_speed_entry(test_run, 10, audio_rms_db=-42.0)
        self.db.add_speed_entry(test_run, 20, audio_rms_db=-37.0)
        self.db.add_speed_entry(test_run, 30, audio_rms_db=-35.0)

        delta = self.db.compare_audio_to_reference(test_run, ref_run)
        self.assertAlmostEqual(delta, 3.0, places=1)

    def test_compare_audio_no_overlap(self):
        lid = self.db.get_or_create_loco("SP 4449", 4449)
        r1 = self.db.create_run(lid, "full")
        r2 = self.db.create_run(lid, "full")
        self.db.add_speed_entry(r1, 10, audio_rms_db=-45.0)
        self.db.add_speed_entry(r2, 20, audio_rms_db=-40.0)

        delta = self.db.compare_audio_to_reference(r2, r1)
        self.assertIsNone(delta)

    # --- Context manager ---

    def test_context_manager(self):
        with CalibrationDB(self.tmp.name) as db:
            lid = db.get_or_create_loco("Test", 99)
            self.assertGreater(lid, 0)

    # --- Schema versioning ---

    def test_schema_version(self):
        row = self.db.conn.execute("SELECT version FROM schema_version").fetchone()
        self.assertEqual(row["version"], 1)

    def test_reopen_existing_db(self):
        """Opening an existing DB should not fail or re-create tables."""
        loco_id = self.db.get_or_create_loco("SP 4449", 4449)
        self.db.close()

        db2 = CalibrationDB(self.tmp.name)
        loco = db2.get_loco("SP 4449")
        self.assertIsNotNone(loco)
        self.assertEqual(loco["id"], loco_id)
        db2.close()


if __name__ == "__main__":
    unittest.main()
