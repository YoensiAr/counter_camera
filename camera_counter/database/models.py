EVENTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    local_day TEXT NOT NULL,
    local_hour TEXT NOT NULL,
    event_type TEXT NOT NULL CHECK(event_type IN ('entry','exit')),
    track_id INTEGER NOT NULL,
    source TEXT NOT NULL,
    confidence REAL NOT NULL CHECK(confidence BETWEEN 0 AND 1),
    direction TEXT NOT NULL,
    session_id TEXT NOT NULL REFERENCES sessions(id),
    crossing_index INTEGER NOT NULL DEFAULT 0,
    UNIQUE(session_id, track_id, event_type, crossing_index)
);
"""

SCHEMA = (
    """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY, started_at TEXT NOT NULL, ended_at TEXT, source TEXT NOT NULL
);
"""
    + EVENTS_SCHEMA
    + """
CREATE INDEX IF NOT EXISTS events_day ON events(local_day, id);
CREATE TABLE IF NOT EXISTS counters (
    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
    entries INTEGER NOT NULL DEFAULT 0,
    exits INTEGER NOT NULL DEFAULT 0,
    reset_event_id INTEGER NOT NULL DEFAULT 0,
    reset_at TEXT,
    uncertain INTEGER NOT NULL DEFAULT 0 CHECK(uncertain IN (0,1)),
    uncertainty_reason TEXT NOT NULL DEFAULT ''
);
INSERT OR IGNORE INTO counters(singleton) VALUES(1);
CREATE TABLE IF NOT EXISTS resets (
    id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL,
    previous_entries INTEGER NOT NULL, previous_exits INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS visitors (
    id TEXT PRIMARY KEY,
    model_id TEXT NOT NULL,
    template BLOB NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    entry_counted INTEGER NOT NULL DEFAULT 0 CHECK(entry_counted IN (0,1)),
    exit_counted INTEGER NOT NULL DEFAULT 0 CHECK(exit_counted IN (0,1)),
    face_ready INTEGER NOT NULL DEFAULT 1 CHECK(face_ready IN (0,1))
);
CREATE INDEX IF NOT EXISTS visitors_expiry ON visitors(expires_at);
CREATE TABLE IF NOT EXISTS visitor_bodies (
    visitor_id TEXT PRIMARY KEY REFERENCES visitors(id) ON DELETE CASCADE,
    model_id TEXT NOT NULL,
    template BLOB NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS visitor_events (
    event_id INTEGER PRIMARY KEY REFERENCES events(id) ON DELETE CASCADE,
    status TEXT NOT NULL CHECK(status IN ('pending','new','returning','unverified','disabled')),
    visitor_id TEXT REFERENCES visitors(id) ON DELETE SET NULL,
    reason TEXT NOT NULL DEFAULT '',
    similarity REAL,
    resolved_at TEXT,
    counted INTEGER NOT NULL DEFAULT 0 CHECK(counted IN (0,1)),
    evidence TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS visitor_events_status ON visitor_events(status);
"""
)
