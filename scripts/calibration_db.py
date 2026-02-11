"""
Calibration Database — SQLite storage for locomotive calibration data.

Stores speed profiles, drawbar pull curves, vibration baselines, and audio
levels for each locomotive. Keyed by JMRI roster ID so results can be joined
with DecoderPro roster entries.

Schema:
  locos              — one row per locomotive (thin join anchor to roster)
  consist_members    — links consist locos to their member decoder addresses
  calibration_runs   — one row per test session
  speed_entries      — per-speed-step measurements (speed, pull, vib, audio)
  motion_thresholds  — start-of-motion steps per direction
  audio_adjustments  — computed volume CV deltas vs. reference loco

Usage:
  from calibration_db import CalibrationDB

  db = CalibrationDB("calibration-data/calibration.db")
  loco_id = db.get_or_create_loco("SP 4449", address=4449)
  run_id = db.create_run(loco_id, "full", direction="both", step_increment=5)
  db.add_speed_entry(run_id, speed_step=50, throttle_pct=39.7,
                     speed_mph=35.2, pull_grams=12.3,
                     vib_peak_to_peak=180, vib_rms=42.5,
                     audio_rms_db=-38.7, audio_peak_db=-30.2)
  db.complete_run(run_id)
"""

import os
import sqlite3
from datetime import datetime, timezone
from typing import Optional


SCHEMA_VERSION = 2

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS locos (
    id INTEGER PRIMARY KEY,
    roster_id TEXT UNIQUE NOT NULL,
    address INTEGER NOT NULL,
    decoder_type TEXT,
    is_audio_reference INTEGER DEFAULT 0,
    is_consist INTEGER DEFAULT 0,
    notes TEXT,
    created TEXT NOT NULL,
    updated TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS consist_members (
    id INTEGER PRIMARY KEY,
    consist_loco_id INTEGER NOT NULL REFERENCES locos(id),
    member_roster_id TEXT,
    member_address INTEGER NOT NULL,
    role TEXT NOT NULL DEFAULT 'sound',
    position INTEGER NOT NULL DEFAULT 0,
    notes TEXT,
    UNIQUE(consist_loco_id, member_address)
);

CREATE TABLE IF NOT EXISTS calibration_runs (
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

CREATE TABLE IF NOT EXISTS speed_entries (
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

CREATE TABLE IF NOT EXISTS motion_thresholds (
    run_id INTEGER NOT NULL REFERENCES calibration_runs(id),
    direction TEXT NOT NULL,
    threshold_step INTEGER NOT NULL,
    PRIMARY KEY (run_id, direction)
);

CREATE TABLE IF NOT EXISTS audio_adjustments (
    id INTEGER PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES calibration_runs(id),
    reference_run_id INTEGER REFERENCES calibration_runs(id),
    member_address INTEGER,
    master_volume_delta_db REAL,
    recommended_cv INTEGER,
    recommended_value INTEGER,
    applied INTEGER DEFAULT 0,
    applied_timestamp TEXT
);

CREATE INDEX IF NOT EXISTS idx_runs_loco ON calibration_runs(loco_id);
CREATE INDEX IF NOT EXISTS idx_runs_timestamp ON calibration_runs(timestamp);
CREATE INDEX IF NOT EXISTS idx_entries_run ON speed_entries(run_id);
CREATE INDEX IF NOT EXISTS idx_consist_members ON consist_members(consist_loco_id);
"""


class CalibrationDB:
    """SQLite-backed calibration data store."""

    def __init__(self, db_path: str = "calibration-data/calibration.db"):
        self.db_path = db_path

        # Ensure parent directory exists
        parent = os.path.dirname(db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)

        self.conn = sqlite3.connect(db_path)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.row_factory = sqlite3.Row

        self._ensure_schema()

    def _ensure_schema(self):
        """Create tables if they don't exist, handle migrations."""
        cursor = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
        )
        if cursor.fetchone() is None:
            # Fresh database
            self.conn.executescript(SCHEMA_SQL)
            self.conn.execute(
                "INSERT INTO schema_version (version) VALUES (?)",
                (SCHEMA_VERSION,)
            )
            self.conn.commit()
        else:
            row = self.conn.execute("SELECT version FROM schema_version").fetchone()
            if row and row[0] < SCHEMA_VERSION:
                self._migrate(row[0])

    def _migrate(self, from_version: int):
        """Run schema migrations."""
        if from_version < 2:
            self._migrate_v1_to_v2()

    def _migrate_v1_to_v2(self):
        """Add consist support: consist_members table, is_consist flag, member_address."""
        self.conn.executescript("""
            ALTER TABLE locos ADD COLUMN is_consist INTEGER DEFAULT 0;

            CREATE TABLE IF NOT EXISTS consist_members (
                id INTEGER PRIMARY KEY,
                consist_loco_id INTEGER NOT NULL REFERENCES locos(id),
                member_roster_id TEXT,
                member_address INTEGER NOT NULL,
                role TEXT NOT NULL DEFAULT 'sound',
                position INTEGER NOT NULL DEFAULT 0,
                notes TEXT,
                UNIQUE(consist_loco_id, member_address)
            );

            CREATE INDEX IF NOT EXISTS idx_consist_members
                ON consist_members(consist_loco_id);

            ALTER TABLE audio_adjustments ADD COLUMN member_address INTEGER;
        """)
        self.conn.execute(
            "UPDATE schema_version SET version = ?", (2,)
        )
        self.conn.commit()

    def close(self):
        """Close the database connection."""
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    # --- Loco management ---

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def get_or_create_loco(self, roster_id: str, address: int,
                           decoder_type: Optional[str] = None,
                           notes: Optional[str] = None) -> int:
        """Get existing loco by roster_id, or create a new one. Returns loco id."""
        row = self.conn.execute(
            "SELECT id FROM locos WHERE roster_id = ?", (roster_id,)
        ).fetchone()

        if row:
            # Update fields that may have changed
            updates = {"updated": self._now_iso(), "address": address}
            if decoder_type is not None:
                updates["decoder_type"] = decoder_type
            set_clause = ", ".join(f"{k} = ?" for k in updates)
            self.conn.execute(
                f"UPDATE locos SET {set_clause} WHERE id = ?",
                (*updates.values(), row["id"])
            )
            self.conn.commit()
            return row["id"]

        now = self._now_iso()
        cursor = self.conn.execute(
            "INSERT INTO locos (roster_id, address, decoder_type, notes, created, updated) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (roster_id, address, decoder_type, notes, now, now)
        )
        self.conn.commit()
        return cursor.lastrowid

    def get_loco(self, roster_id: str) -> Optional[dict]:
        """Get loco by roster_id. Returns dict or None."""
        row = self.conn.execute(
            "SELECT * FROM locos WHERE roster_id = ?", (roster_id,)
        ).fetchone()
        return dict(row) if row else None

    def list_locos(self) -> list:
        """List all locos."""
        rows = self.conn.execute(
            "SELECT * FROM locos ORDER BY roster_id"
        ).fetchall()
        return [dict(r) for r in rows]

    def set_audio_reference(self, roster_id: str, is_reference: bool = True):
        """Mark/unmark a loco as the audio reference."""
        try:
            if is_reference:
                # Clear any existing reference first
                self.conn.execute(
                    "UPDATE locos SET is_audio_reference = 0, updated = ? "
                    "WHERE is_audio_reference = 1",
                    (self._now_iso(),)
                )
            self.conn.execute(
                "UPDATE locos SET is_audio_reference = ?, updated = ? "
                "WHERE roster_id = ?",
                (1 if is_reference else 0, self._now_iso(), roster_id)
            )
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def get_audio_reference(self) -> Optional[dict]:
        """Get the loco marked as audio reference, if any."""
        row = self.conn.execute(
            "SELECT * FROM locos WHERE is_audio_reference = 1"
        ).fetchone()
        return dict(row) if row else None

    # --- Consist management ---

    def set_consist(self, roster_id: str, members: list):
        """Define a consist and its member decoders.

        Marks the loco as a consist and replaces any existing members.

        members: list of dicts with keys:
            member_address (int, required): DCC address of this decoder
            member_roster_id (str, optional): roster ID if member has its own entry
            role (str, optional): 'sound', 'silent', or 'motor' (default: 'sound')
            position (int, optional): ordering within consist (default: 0)
            notes (str, optional): e.g. "front engine", "rear engine"
        """
        loco = self.conn.execute(
            "SELECT id FROM locos WHERE roster_id = ?", (roster_id,)
        ).fetchone()
        if not loco:
            raise ValueError(f"Loco '{roster_id}' not found")

        loco_id = loco["id"]

        try:
            # Mark as consist
            self.conn.execute(
                "UPDATE locos SET is_consist = 1, updated = ? WHERE id = ?",
                (self._now_iso(), loco_id)
            )

            # Replace existing members
            self.conn.execute(
                "DELETE FROM consist_members WHERE consist_loco_id = ?",
                (loco_id,)
            )

            for m in members:
                self.conn.execute(
                    "INSERT INTO consist_members "
                    "(consist_loco_id, member_roster_id, member_address, role, position, notes) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (loco_id, m.get("member_roster_id"), m["member_address"],
                     m.get("role", "sound"), m.get("position", 0), m.get("notes"))
                )

            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def get_consist_members(self, roster_id: str) -> list:
        """Get all members of a consist. Returns list of dicts, ordered by position."""
        rows = self.conn.execute(
            """
            SELECT cm.* FROM consist_members cm
            JOIN locos l ON cm.consist_loco_id = l.id
            WHERE l.roster_id = ?
            ORDER BY cm.position
            """,
            (roster_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def get_consist_sound_members(self, roster_id: str) -> list:
        """Get only sound-decoder members of a consist."""
        rows = self.conn.execute(
            """
            SELECT cm.* FROM consist_members cm
            JOIN locos l ON cm.consist_loco_id = l.id
            WHERE l.roster_id = ? AND cm.role = 'sound'
            ORDER BY cm.position
            """,
            (roster_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def is_consist(self, roster_id: str) -> bool:
        """Check whether a loco is a consist."""
        row = self.conn.execute(
            "SELECT is_consist FROM locos WHERE roster_id = ?", (roster_id,)
        ).fetchone()
        return bool(row and row["is_consist"])

    # --- Calibration runs ---

    def create_run(self, loco_id: int, run_type: str,
                   direction: Optional[str] = None,
                   step_increment: Optional[int] = None,
                   settle_ms: Optional[int] = None,
                   firmware_version: Optional[str] = None,
                   notes: Optional[str] = None) -> int:
        """Create a new calibration run. Returns run id."""
        cursor = self.conn.execute(
            "INSERT INTO calibration_runs "
            "(loco_id, run_type, timestamp, direction, step_increment, "
            " settle_ms, firmware_version, notes) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (loco_id, run_type, self._now_iso(), direction, step_increment,
             settle_ms, firmware_version, notes)
        )
        self.conn.commit()
        return cursor.lastrowid

    def complete_run(self, run_id: int, duration_sec: Optional[float] = None):
        """Mark a run as complete."""
        self.conn.execute(
            "UPDATE calibration_runs SET complete = 1, duration_sec = ? WHERE id = ?",
            (duration_sec, run_id)
        )
        self.conn.commit()

    def abort_run(self, run_id: int, duration_sec: Optional[float] = None):
        """Mark a run as aborted."""
        self.conn.execute(
            "UPDATE calibration_runs SET aborted = 1, duration_sec = ? WHERE id = ?",
            (duration_sec, run_id)
        )
        self.conn.commit()

    def get_run(self, run_id: int) -> Optional[dict]:
        """Get a calibration run by id."""
        row = self.conn.execute(
            "SELECT * FROM calibration_runs WHERE id = ?", (run_id,)
        ).fetchone()
        return dict(row) if row else None

    def list_runs(self, roster_id: Optional[str] = None,
                  run_type: Optional[str] = None,
                  limit: int = 50) -> list:
        """List calibration runs, optionally filtered."""
        sql = """
            SELECT r.*, l.roster_id, l.address
            FROM calibration_runs r
            JOIN locos l ON r.loco_id = l.id
            WHERE 1=1
        """
        params = []
        if roster_id:
            sql += " AND l.roster_id = ?"
            params.append(roster_id)
        if run_type:
            sql += " AND r.run_type = ?"
            params.append(run_type)
        sql += " ORDER BY r.timestamp DESC LIMIT ?"
        params.append(limit)

        rows = self.conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def get_latest_run(self, roster_id: str,
                       run_type: Optional[str] = None,
                       complete_only: bool = True) -> Optional[dict]:
        """Get the most recent run for a loco."""
        sql = """
            SELECT r.* FROM calibration_runs r
            JOIN locos l ON r.loco_id = l.id
            WHERE l.roster_id = ?
        """
        params = [roster_id]
        if run_type:
            sql += " AND r.run_type = ?"
            params.append(run_type)
        if complete_only:
            sql += " AND r.complete = 1"
        sql += " ORDER BY r.timestamp DESC LIMIT 1"

        row = self.conn.execute(sql, params).fetchone()
        return dict(row) if row else None

    # --- Speed entries ---

    def add_speed_entry(self, run_id: int, speed_step: int,
                        throttle_pct: Optional[float] = None,
                        speed_mph: Optional[float] = None,
                        pull_grams: Optional[float] = None,
                        vib_peak_to_peak: Optional[int] = None,
                        vib_rms: Optional[float] = None,
                        audio_rms_db: Optional[float] = None,
                        audio_peak_db: Optional[float] = None):
        """Add a single speed step measurement to a run."""
        self.conn.execute(
            "INSERT OR REPLACE INTO speed_entries "
            "(run_id, speed_step, throttle_pct, speed_mph, pull_grams, "
            " vib_peak_to_peak, vib_rms, audio_rms_db, audio_peak_db) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (run_id, speed_step, throttle_pct, speed_mph, pull_grams,
             vib_peak_to_peak, vib_rms, audio_rms_db, audio_peak_db)
        )
        self.conn.commit()

    def add_speed_entries_batch(self, run_id: int, entries: list):
        """Add multiple speed entries at once.

        entries: list of dicts with keys matching speed_entries columns.
        """
        for e in entries:
            self.conn.execute(
                "INSERT OR REPLACE INTO speed_entries "
                "(run_id, speed_step, throttle_pct, speed_mph, pull_grams, "
                " vib_peak_to_peak, vib_rms, audio_rms_db, audio_peak_db) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (run_id, e.get("speed_step"), e.get("throttle_pct"),
                 e.get("speed_mph"), e.get("pull_grams"),
                 e.get("vib_peak_to_peak"), e.get("vib_rms"),
                 e.get("audio_rms_db"), e.get("audio_peak_db"))
            )
        self.conn.commit()

    def get_speed_entries(self, run_id: int) -> list:
        """Get all speed entries for a run, ordered by step."""
        rows = self.conn.execute(
            "SELECT * FROM speed_entries WHERE run_id = ? ORDER BY speed_step",
            (run_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    # --- Motion thresholds ---

    def set_motion_threshold(self, run_id: int, direction: str, threshold_step: int):
        """Record start-of-motion threshold for a direction."""
        self.conn.execute(
            "INSERT OR REPLACE INTO motion_thresholds "
            "(run_id, direction, threshold_step) VALUES (?, ?, ?)",
            (run_id, direction, threshold_step)
        )
        self.conn.commit()

    def get_motion_thresholds(self, run_id: int) -> dict:
        """Get motion thresholds for a run. Returns {direction: step}."""
        rows = self.conn.execute(
            "SELECT direction, threshold_step FROM motion_thresholds WHERE run_id = ?",
            (run_id,)
        ).fetchall()
        return {r["direction"]: r["threshold_step"] for r in rows}

    # --- Audio adjustments ---

    def add_audio_adjustment(self, run_id: int, reference_run_id: int,
                             delta_db: float,
                             recommended_cv: Optional[int] = None,
                             recommended_value: Optional[int] = None,
                             member_address: Optional[int] = None) -> int:
        """Record a computed audio adjustment. Returns adjustment id.

        member_address: if set, targets a specific decoder within a consist.
            When None, applies to the loco as a whole (single-decoder or consist overall).
        """
        cursor = self.conn.execute(
            "INSERT INTO audio_adjustments "
            "(run_id, reference_run_id, member_address, master_volume_delta_db, "
            " recommended_cv, recommended_value) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (run_id, reference_run_id, member_address, delta_db,
             recommended_cv, recommended_value)
        )
        self.conn.commit()
        return cursor.lastrowid

    def get_audio_adjustments(self, run_id: int,
                               member_address: Optional[int] = None) -> list:
        """Get audio adjustments for a run, optionally filtered by member address."""
        if member_address is not None:
            rows = self.conn.execute(
                "SELECT * FROM audio_adjustments WHERE run_id = ? AND member_address = ?",
                (run_id, member_address)
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM audio_adjustments WHERE run_id = ?",
                (run_id,)
            ).fetchall()
        return [dict(r) for r in rows]

    def mark_adjustment_applied(self, adjustment_id: int):
        """Mark an audio adjustment as written to the loco."""
        self.conn.execute(
            "UPDATE audio_adjustments SET applied = 1, applied_timestamp = ? WHERE id = ?",
            (self._now_iso(), adjustment_id)
        )
        self.conn.commit()

    # --- Query helpers ---

    def get_audio_curve(self, run_id: int) -> list:
        """Get audio RMS dB vs speed step for a run."""
        rows = self.conn.execute(
            "SELECT speed_step, audio_rms_db FROM speed_entries "
            "WHERE run_id = ? AND audio_rms_db IS NOT NULL "
            "ORDER BY speed_step",
            (run_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def get_pull_curve(self, run_id: int) -> list:
        """Get pull force vs speed step for a run."""
        rows = self.conn.execute(
            "SELECT speed_step, pull_grams FROM speed_entries "
            "WHERE run_id = ? AND pull_grams IS NOT NULL "
            "ORDER BY speed_step",
            (run_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def get_vibration_curve(self, run_id: int) -> list:
        """Get vibration vs speed step for a run."""
        rows = self.conn.execute(
            "SELECT speed_step, vib_peak_to_peak, vib_rms FROM speed_entries "
            "WHERE run_id = ? AND vib_rms IS NOT NULL "
            "ORDER BY speed_step",
            (run_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def get_speed_profile(self, run_id: int) -> list:
        """Get speed (mph) vs speed step for a run (for JMRI roster import)."""
        rows = self.conn.execute(
            "SELECT speed_step, throttle_pct, speed_mph FROM speed_entries "
            "WHERE run_id = ? AND speed_mph IS NOT NULL "
            "ORDER BY speed_step",
            (run_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def compare_audio_to_reference(self, run_id: int, reference_run_id: int) -> Optional[float]:
        """Compare a run's audio curve to the reference. Returns mean delta dB.

        Positive means the run is louder than reference.
        Only compares speed steps present in both runs.
        """
        rows = self.conn.execute(
            """
            SELECT AVG(t.audio_rms_db - r.audio_rms_db) as delta_db
            FROM speed_entries t
            JOIN speed_entries r ON t.speed_step = r.speed_step
            WHERE t.run_id = ? AND r.run_id = ?
              AND t.audio_rms_db IS NOT NULL
              AND r.audio_rms_db IS NOT NULL
            """,
            (run_id, reference_run_id)
        ).fetchone()
        return rows["delta_db"] if rows and rows["delta_db"] is not None else None
