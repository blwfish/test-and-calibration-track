#!/usr/bin/env python3
"""
Tests for audio calibration: decoder volume lookup, CV computation,
volume grading, and integration with CalibrationDB.

Run:  python3 scripts/test_audio_calibrate.py
"""

import os
import sys
import tempfile
import unittest

# Add scripts dir to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from decoder_volume import (
    DECODER_VOLUME_TABLE,
    lookup_decoder,
    compute_new_cv,
)
from audio_calibrate import grade_volume, mean_audio, percentile
from calibration_db import CalibrationDB


class TestDecoderVolumeLookup(unittest.TestCase):
    """Tests for decoder family -> volume CV lookup."""

    def test_exact_match_loksound5(self):
        info = lookup_decoder("LokSound 5")
        self.assertIsNotNone(info)
        self.assertEqual(info["cv"], 63)
        self.assertEqual(info["max"], 192)
        self.assertEqual(info["decoder_name"], "LokSound 5")

    def test_exact_match_tsunami2(self):
        info = lookup_decoder("SoundTraxx Tsunami2")
        self.assertIsNotNone(info)
        self.assertEqual(info["cv"], 128)
        self.assertEqual(info["max"], 255)

    def test_fuzzy_match_case_insensitive(self):
        info = lookup_decoder("ESU LOKSOUND 5 XL")
        self.assertIsNotNone(info)
        self.assertEqual(info["cv"], 63)
        self.assertEqual(info["decoder_name"], "LokSound 5")

    def test_fuzzy_match_substring(self):
        """JMRI might return 'Tsunami2 TSU-2200' — should still match."""
        info = lookup_decoder("Tsunami2 TSU-2200")
        self.assertIsNotNone(info)
        self.assertEqual(info["cv"], 128)

    def test_fuzzy_match_bli_paragon(self):
        info = lookup_decoder("BLI Paragon4 Sound")
        self.assertIsNotNone(info)
        self.assertEqual(info["cv"], 161)

    def test_unknown_decoder_returns_none(self):
        info = lookup_decoder("Acme SuperSound 3000")
        self.assertIsNone(info)

    def test_empty_decoder_returns_none(self):
        self.assertIsNone(lookup_decoder(""))
        self.assertIsNone(lookup_decoder(None))

    def test_all_known_decoders_have_required_fields(self):
        for name, info in DECODER_VOLUME_TABLE.items():
            self.assertIn("cv", info, f"{name} missing cv")
            self.assertIn("min", info, f"{name} missing min")
            self.assertIn("max", info, f"{name} missing max")
            self.assertIn("default", info, f"{name} missing default")
            self.assertIn("family_match", info, f"{name} missing family_match")
            self.assertGreater(info["max"], info["min"],
                               f"{name} max <= min")

    def test_digitrax_coarse_range(self):
        info = lookup_decoder("Digitrax SDH166D")
        self.assertIsNotNone(info)
        self.assertEqual(info["cv"], 58)
        self.assertEqual(info["max"], 15)

    def test_tcs_wowsound(self):
        info = lookup_decoder("TCS WOWSound V5")
        self.assertIsNotNone(info)
        self.assertEqual(info["cv"], 128)


class TestComputeNewCV(unittest.TestCase):
    """Tests for dB delta -> CV value computation."""

    def test_no_change_zero_delta(self):
        new = compute_new_cv(180, delta_db=0.0, cv_min=0, cv_max=192)
        self.assertEqual(new, 180)

    def test_reduce_by_6db(self):
        """6 dB louder -> halve amplitude -> halve CV."""
        new = compute_new_cv(200, delta_db=6.0, cv_min=0, cv_max=255)
        # 200 * 10^(-6/20) = 200 * 0.5012 = 100.2 -> 100
        self.assertEqual(new, 100)

    def test_increase_by_6db(self):
        """-6 dB delta = target is quieter -> increase CV."""
        new = compute_new_cv(100, delta_db=-6.0, cv_min=0, cv_max=255)
        # 100 * 10^(6/20) = 100 * 1.995 = 199.5 -> 200
        self.assertEqual(new, 200)

    def test_clamp_to_max(self):
        new = compute_new_cv(200, delta_db=-20.0, cv_min=0, cv_max=255)
        # 200 * 10^(20/20) = 200 * 10 = 2000, clamped to 255
        self.assertEqual(new, 255)

    def test_clamp_to_min(self):
        new = compute_new_cv(10, delta_db=40.0, cv_min=0, cv_max=255)
        # 10 * 10^(-40/20) = 10 * 0.01 = 0.1 -> 0
        self.assertEqual(new, 0)

    def test_small_delta_rounds_correctly(self):
        """1 dB delta on a coarse Digitrax decoder (0-15)."""
        new = compute_new_cv(15, delta_db=1.0, cv_min=0, cv_max=15)
        # 15 * 10^(-1/20) = 15 * 0.891 = 13.37 -> 13
        self.assertEqual(new, 13)

    def test_zero_current_cv(self):
        new = compute_new_cv(0, delta_db=-6.0, cv_min=0, cv_max=255)
        self.assertEqual(new, 0)

    def test_negative_delta_small(self):
        """Target 3 dB quieter -> increase by ~1.41x."""
        new = compute_new_cv(100, delta_db=-3.0, cv_min=0, cv_max=255)
        # 100 * 10^(3/20) = 100 * 1.4125 = 141
        self.assertEqual(new, 141)


class TestVolumeGrading(unittest.TestCase):
    """Tests for volume grade assignment."""

    def test_grade_normal(self):
        self.assertEqual(grade_volume(-40.0, median=-42.0, p25=-45.0, p75=-38.0),
                         "normal")

    def test_grade_quiet(self):
        self.assertEqual(grade_volume(-50.0, median=-42.0, p25=-45.0, p75=-38.0),
                         "quiet")

    def test_grade_loud(self):
        self.assertEqual(grade_volume(-35.0, median=-42.0, p25=-45.0, p75=-38.0),
                         "loud")

    def test_grade_excessive(self):
        self.assertEqual(grade_volume(-30.0, median=-42.0, p25=-45.0, p75=-38.0),
                         "EXCESSIVE")

    def test_grade_no_stats(self):
        self.assertEqual(grade_volume(-40.0, median=None, p25=None, p75=None),
                         "unknown")

    def test_grade_no_mean(self):
        self.assertEqual(grade_volume(None, median=-42.0, p25=-45.0, p75=-38.0),
                         "unknown")


class TestHelpers(unittest.TestCase):
    """Tests for utility functions."""

    def test_mean_audio_basic(self):
        curve = [{"speed_step": 10, "audio_rms_db": -40.0},
                 {"speed_step": 20, "audio_rms_db": -38.0}]
        self.assertAlmostEqual(mean_audio(curve), -39.0)

    def test_mean_audio_empty(self):
        self.assertIsNone(mean_audio([]))
        self.assertIsNone(mean_audio(None))

    def test_percentile_basic(self):
        vals = [-50, -45, -42, -38, -35]
        self.assertEqual(percentile(vals, 50), -42)
        self.assertEqual(percentile(vals, 0), -50)

    def test_percentile_empty(self):
        self.assertIsNone(percentile([], 50))


class TestIntegration(unittest.TestCase):
    """Integration tests using a real (temp) CalibrationDB."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "test.db")
        self.db = CalibrationDB(self.db_path)

    def tearDown(self):
        self.db.close()
        if os.path.exists(self.db_path):
            os.unlink(self.db_path)
        os.rmdir(self.tmpdir)

    def _create_loco_with_audio(self, roster_id, address, decoder_type=None,
                                 audio_db=-40.0):
        """Helper: create a loco, a run, and audio entries."""
        loco_id = self.db.get_or_create_loco(
            roster_id, address, decoder_type=decoder_type)
        run_id = self.db.create_run(loco_id, run_type="speed", direction="both")
        # Add entries at steps 10, 20, 30 with audio
        for step in [10, 20, 30]:
            self.db.add_speed_entry(
                run_id, speed_step=step, throttle_pct=step / 1.26,
                speed_mph=step * 0.5,
                audio_rms_db=audio_db + step * 0.1,  # slight ramp
                audio_peak_db=audio_db + step * 0.1 + 5.0)
        self.db.complete_run(run_id)
        return loco_id, run_id

    def test_set_and_get_reference(self):
        self._create_loco_with_audio("Ref Loco", 100)
        self.db.set_audio_reference("Ref Loco")
        ref = self.db.get_audio_reference()
        self.assertIsNotNone(ref)
        self.assertEqual(ref["roster_id"], "Ref Loco")

    def test_compare_audio_delta(self):
        """Two locos with different audio levels produce correct delta."""
        self._create_loco_with_audio("Ref", 100, audio_db=-40.0)
        self._create_loco_with_audio("Target", 200, audio_db=-34.0)

        ref_run = self.db.get_latest_run("Ref", complete_only=True)
        target_run = self.db.get_latest_run("Target", complete_only=True)

        delta = self.db.compare_audio_to_reference(target_run["id"], ref_run["id"])
        # Target is ~6 dB louder (entries are -34+step*0.1 vs -40+step*0.1)
        self.assertAlmostEqual(delta, 6.0, places=1)

    def test_compare_no_audio_data(self):
        """Loco with no audio entries -> None."""
        loco_id = self.db.get_or_create_loco("NoAudio", 300)
        run_id = self.db.create_run(loco_id, run_type="speed")
        self.db.add_speed_entry(run_id, speed_step=10, speed_mph=5.0)
        self.db.complete_run(run_id)

        self._create_loco_with_audio("Ref", 100, audio_db=-40.0)
        ref_run = self.db.get_latest_run("Ref", complete_only=True)
        target_run = self.db.get_latest_run("NoAudio", complete_only=True)

        curve = self.db.get_audio_curve(target_run["id"])
        self.assertEqual(len(curve), 0)

    def test_audio_adjustment_stored(self):
        """add_audio_adjustment stores and retrieves correctly."""
        self._create_loco_with_audio("Ref", 100, audio_db=-40.0)
        self._create_loco_with_audio("Target", 200, audio_db=-34.0)

        ref_run = self.db.get_latest_run("Ref")
        target_run = self.db.get_latest_run("Target")

        adj_id = self.db.add_audio_adjustment(
            target_run["id"], ref_run["id"], delta_db=6.0,
            recommended_cv=63, recommended_value=90)

        adjs = self.db.get_audio_adjustments(target_run["id"])
        self.assertEqual(len(adjs), 1)
        self.assertAlmostEqual(adjs[0]["master_volume_delta_db"], 6.0)
        self.assertEqual(adjs[0]["recommended_cv"], 63)
        self.assertEqual(adjs[0]["recommended_value"], 90)
        self.assertEqual(adjs[0]["applied"], 0)

    def test_mark_adjustment_applied(self):
        self._create_loco_with_audio("Ref", 100)
        self._create_loco_with_audio("Target", 200)
        ref_run = self.db.get_latest_run("Ref")
        target_run = self.db.get_latest_run("Target")

        adj_id = self.db.add_audio_adjustment(
            target_run["id"], ref_run["id"], delta_db=3.0)
        self.db.mark_adjustment_applied(adj_id)

        adjs = self.db.get_audio_adjustments(target_run["id"])
        self.assertEqual(adjs[0]["applied"], 1)
        self.assertIsNotNone(adjs[0]["applied_timestamp"])

    def test_fleet_grading_with_data(self):
        """Fleet with 5 locos at different levels grades correctly."""
        levels = [-50, -45, -42, -38, -30]
        for i, db_val in enumerate(levels):
            self._create_loco_with_audio(f"Loco{i}", 100 + i, audio_db=db_val)

        # Compute fleet stats manually
        means = []
        for i, db_val in enumerate(levels):
            run = self.db.get_latest_run(f"Loco{i}")
            curve = self.db.get_audio_curve(run["id"])
            m = mean_audio(curve)
            means.append(m)

        means_sorted = sorted(means)
        median = percentile(means_sorted, 50)
        p25 = percentile(means_sorted, 25)
        p75 = percentile(means_sorted, 75)

        # The loudest (-30 + ramp) should be EXCESSIVE (>10 dB above median)
        self.assertEqual(grade_volume(means[-1], median, p25, p75), "EXCESSIVE")
        # The quietest should be quiet
        self.assertEqual(grade_volume(means[0], median, p25, p75), "quiet")


if __name__ == "__main__":
    unittest.main()
