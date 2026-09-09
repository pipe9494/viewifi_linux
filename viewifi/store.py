"""Event storage in SQLite (stdlib) — powers the daily digest and the
routine watch that compares yesterday against the trailing week."""

import sqlite3
import time
from datetime import datetime

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts INTEGER NOT NULL,
    level TEXT NOT NULL,
    rssi REAL,
    variance REAL,
    classification TEXT,
    zone TEXT,
    notified INTEGER DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);
"""


class EventStore:
    def __init__(self, path):
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def add(self, level, rssi, variance, classification, zone, notified=True):
        self.conn.execute(
            "INSERT INTO events (ts, level, rssi, variance, classification, zone, notified)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (int(time.time() * 1000), level, rssi, variance, classification, zone,
             1 if notified else 0),
        )
        self.conn.commit()

    def count_today(self):
        midnight = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        cur = self.conn.execute(
            "SELECT COUNT(*) FROM events WHERE ts >= ?",
            (int(midnight.timestamp() * 1000),),
        )
        return cur.fetchone()[0]

    def recent(self, n=15):
        cur = self.conn.execute(
            "SELECT ts, level, rssi, variance, classification, zone FROM events"
            " ORDER BY ts DESC LIMIT ?", (n,),
        )
        return cur.fetchall()

    def day_summary(self, day_start_ms):
        """Counts per level for the 24h starting at day_start_ms."""
        cur = self.conn.execute(
            "SELECT level, COUNT(*) FROM events WHERE ts >= ? AND ts < ?"
            " GROUP BY level",
            (day_start_ms, day_start_ms + 86_400_000),
        )
        return dict(cur.fetchall())

    def hourly_counts(self, day_start_ms):
        """[24] counts for that day."""
        counts = [0] * 24
        cur = self.conn.execute(
            "SELECT ts FROM events WHERE ts >= ? AND ts < ?",
            (day_start_ms, day_start_ms + 86_400_000),
        )
        for (ts,) in cur.fetchall():
            counts[datetime.fromtimestamp(ts / 1000).hour] += 1
        return counts
