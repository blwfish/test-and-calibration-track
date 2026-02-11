#!/usr/bin/env python3
"""Tests for calibration_db.py"""

import os
import sqlite3
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

    # --- Consist tests ---

    def test_set_consist(self):
        self.db.get_or_create_loco("VGN Triplex", 100)
        self.db.set_consist("VGN Triplex", [
            {"member_address": 101, "role": "sound", "position": 0,
             "notes": "front engine"},
            {"member_address": 102, "role": "sound", "position": 1,
             "notes": "rear engine"},
            {"member_address": 103, "role": "silent", "position": 2,
             "notes": "center engine"},
        ])

        self.assertTrue(self.db.is_consist("VGN Triplex"))
        members = self.db.get_consist_members("VGN Triplex")
        self.assertEqual(len(members), 3)
        self.assertEqual(members[0]["member_address"], 101)
        self.assertEqual(members[0]["role"], "sound")
        self.assertEqual(members[0]["notes"], "front engine")
        self.assertEqual(members[2]["role"], "silent")

    def test_consist_sound_members(self):
        self.db.get_or_create_loco("VGN Triplex", 100)
        self.db.set_consist("VGN Triplex", [
            {"member_address": 101, "role": "sound", "position": 0},
            {"member_address": 102, "role": "sound", "position": 1},
            {"member_address": 103, "role": "silent", "position": 2},
        ])

        sound = self.db.get_consist_sound_members("VGN Triplex")
        self.assertEqual(len(sound), 2)
        addrs = [m["member_address"] for m in sound]
        self.assertIn(101, addrs)
        self.assertIn(102, addrs)
        self.assertNotIn(103, addrs)

    def test_consist_replaces_members(self):
        self.db.get_or_create_loco("VGN Triplex", 100)
        self.db.set_consist("VGN Triplex", [
            {"member_address": 101, "role": "sound"},
            {"member_address": 102, "role": "sound"},
        ])

        # Redefine with different members
        self.db.set_consist("VGN Triplex", [
            {"member_address": 201, "role": "sound"},
            {"member_address": 202, "role": "silent"},
            {"member_address": 203, "role": "sound"},
        ])

        members = self.db.get_consist_members("VGN Triplex")
        self.assertEqual(len(members), 3)
        self.assertEqual(members[0]["member_address"], 201)

    def test_is_consist_false_for_single_loco(self):
        self.db.get_or_create_loco("SP 4449", 4449)
        self.assertFalse(self.db.is_consist("SP 4449"))

    def test_consist_member_roster_id(self):
        """Members can optionally reference their own roster entries."""
        self.db.get_or_create_loco("VGN Triplex", 100)
        self.db.get_or_create_loco("VGN Front", 101)
        self.db.set_consist("VGN Triplex", [
            {"member_address": 101, "member_roster_id": "VGN Front",
             "role": "sound", "position": 0},
            {"member_address": 102, "role": "sound", "position": 1},
        ])

        members = self.db.get_consist_members("VGN Triplex")
        self.assertEqual(members[0]["member_roster_id"], "VGN Front")
        self.assertIsNone(members[1]["member_roster_id"])

    def test_consist_not_found_raises(self):
        with self.assertRaises(ValueError):
            self.db.set_consist("nonexistent", [
                {"member_address": 101, "role": "sound"},
            ])

    # --- Audio adjustments with member_address ---

    def test_audio_adjustment_per_member(self):
        """Audio adjustments can target specific consist members."""
        lid = self.db.get_or_create_loco("VGN Triplex", 100)
        self.db.set_consist("VGN Triplex", [
            {"member_address": 101, "role": "sound"},
            {"member_address": 102, "role": "sound"},
        ])

        ref_run = self.db.create_run(lid, "full")
        test_run = self.db.create_run(lid, "full")

        # Different adjustment per decoder
        adj1 = self.db.add_audio_adjustment(
            test_run, ref_run, delta_db=2.5,
            recommended_cv=63, recommended_value=90,
            member_address=101
        )
        adj2 = self.db.add_audio_adjustment(
            test_run, ref_run, delta_db=-1.5,
            recommended_cv=63, recommended_value=110,
            member_address=102
        )
        self.assertGreater(adj1, 0)
        self.assertGreater(adj2, 0)
        self.assertNotEqual(adj1, adj2)

        # Filter by member
        adjs_101 = self.db.get_audio_adjustments(test_run, member_address=101)
        self.assertEqual(len(adjs_101), 1)
        self.assertAlmostEqual(adjs_101[0]["master_volume_delta_db"], 2.5)

        adjs_102 = self.db.get_audio_adjustments(test_run, member_address=102)
        self.assertEqual(len(adjs_102), 1)
        self.assertAlmostEqual(adjs_102[0]["master_volume_delta_db"], -1.5)

        # Get all adjustments
        all_adjs = self.db.get_audio_adjustments(test_run)
        self.assertEqual(len(all_adjs), 2)

    def test_audio_adjustment_without_member(self):
        """Single-decoder locos still work without member_address."""
        lid = self.db.get_or_create_loco("SP 4449", 4449)
        ref_run = self.db.create_run(lid, "full")
        test_run = self.db.create_run(lid, "full")

        adj_id = self.db.add_audio_adjustment(
            test_run, ref_run, delta_db=3.5,
            recommended_cv=63, recommended_value=96
        )

        adjs = self.db.get_audio_adjustments(test_run)
        self.assertEqual(len(adjs), 1)
        self.assertIsNone(adjs[0]["member_address"])
        self.assertAlmostEqual(adjs[0]["master_volume_delta_db"], 3.5)

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
        self.assertEqual(row["version"], 2)

    def test_reopen_existing_db(self):
        """Opening an existing DB should not fail or re-create tables."""
        loco_id = self.db.get_or_create_loco("SP 4449", 4449)
        self.db.close()

        db2 = CalibrationDB(self.tmp.name)
        loco = db2.get_loco("SP 4449")
        self.assertIsNotNone(loco)
        self.assertEqual(loco["id"], loco_id)
        db2.close()

    def test_migrate_v1_to_v2(self):
        """Simulate a v1 database and verify migration adds consist support."""
        self.db.close()
        # Remove existing and create a v1-only database
        os.unlink(self.tmp.name)
        conn = sqlite3.connect(self.tmp.name)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        # Create v1 schema (no consist_members, no is_consist, no member_address)
        conn.executescript("""
            CREATE TABLE schema_version (version INTEGER NOT NULL);
            INSERT INTO schema_version (version) VALUES (1);

            CREATE TABLE locos (
                id INTEGER PRIMARY KEY,
                roster_id TEXT UNIQUE NOT NULL,
                address INTEGER NOT NULL,
                decoder_type TEXT,
                is_audio_reference INTEGER DEFAULT 0,
                notes TEXT,
                created TEXT NOT NULL,
                updated TEXT NOT NULL
            );

            CREATE TABLE calibration_runs (
                id INTEGER PRIMARY KEY,
                loco_id INTEGER NOT NULL REFERENCES locos(id),
                run_type TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                direction TEXT,
                step_increment INTEGER,
                settle_ms INTEGER,
                firmware_version TEXT,
                complete INTEGER DEFAULT 0,
                aborted INTEGER DEFAULT 0,
                duration_sec REAL,
                notes TEXT
            );

            CREATE TABLE speed_entries (
                run_id INTEGER NOT NULL REFERENCES calibration_runs(id),
                speed_step INTEGER NOT NULL,
                throttle_pct REAL,
                speed_mph REAL,
                pull_grams REAL,
                vib_peak_to_peak INTEGER,
                vib_rms REAL,
                audio_rms_db REAL,
                audio_peak_db REAL,
                PRIMARY KEY (run_id, speed_step)
            );

            CREATE TABLE motion_thresholds (
                run_id INTEGER NOT NULL REFERENCES calibration_runs(id),
                direction TEXT NOT NULL,
                threshold_step INTEGER NOT NULL,
                PRIMARY KEY (run_id, direction)
            );

            CREATE TABLE audio_adjustments (
                id INTEGER PRIMARY KEY,
                run_id INTEGER NOT NULL REFERENCES calibration_runs(id),
                reference_run_id INTEGER REFERENCES calibration_runs(id),
                master_volume_delta_db REAL,
                recommended_cv INTEGER,
                recommended_value INTEGER,
                applied INTEGER DEFAULT 0,
                applied_timestamp TEXT
            );
        """)
        # Add some v1 data
        conn.execute(
            "INSERT INTO locos (roster_id, address, created, updated) "
            "VALUES ('SP 4449', 4449, '2024-01-01', '2024-01-01')"
        )
        conn.commit()
        conn.close()

        # Now open with CalibrationDB — should trigger migration
        db2 = CalibrationDB(self.tmp.name)

        # Verify migration happened
        row = db2.conn.execute("SELECT version FROM schema_version").fetchone()
        self.assertEqual(row[0], 2)

        # Existing data preserved
        loco = db2.get_loco("SP 4449")
        self.assertIsNotNone(loco)
        self.assertEqual(loco["is_consist"], 0)

        # New consist features work
        db2.set_consist("SP 4449", [
            {"member_address": 101, "role": "sound"},
        ])
        self.assertTrue(db2.is_consist("SP 4449"))
        members = db2.get_consist_members("SP 4449")
        self.assertEqual(len(members), 1)

        # member_address on audio_adjustments works
        lid = loco["id"]
        run_id = db2.create_run(lid, "full")
        adj_id = db2.add_audio_adjustment(run_id, run_id, delta_db=1.0,
                                           member_address=101)
        adjs = db2.get_audio_adjustments(run_id, member_address=101)
        self.assertEqual(len(adjs), 1)

        db2.close()


if __name__ == "__main__":
    unittest.main()
