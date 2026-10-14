-- Pe3k SQLite schema. All timestamps are UTC ISO-8601 strings: YYYY-MM-DDTHH:MM:SSZ
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS devices (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    name                 TEXT    NOT NULL,
    ip_address           TEXT    NOT NULL UNIQUE,
    mac_address          TEXT    UNIQUE,                 -- normalised AA:BB:CC:DD:EE:FF, optional
    device_type          TEXT    NOT NULL DEFAULT 'other',
    trusted              INTEGER NOT NULL DEFAULT 1,
    monitoring_enabled   INTEGER NOT NULL DEFAULT 1,
    status               TEXT    NOT NULL DEFAULT 'unknown',  -- unknown | online | unstable | offline
    last_latency_ms      REAL,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    last_checked         TEXT,
    last_seen            TEXT,
    notes                TEXT    NOT NULL DEFAULT '',
    date_added           TEXT    NOT NULL,
    updated_at           TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_devices_status ON devices(status);

CREATE TABLE IF NOT EXISTS monitor_logs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id    INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    checked_at   TEXT    NOT NULL,
    success      INTEGER NOT NULL,
    latency_ms   REAL,
    status_after TEXT    NOT NULL,
    attempts     INTEGER NOT NULL DEFAULT 1,
    error        TEXT
);
CREATE INDEX IF NOT EXISTS idx_monitor_logs_device_time ON monitor_logs(device_id, checked_at);
CREATE INDEX IF NOT EXISTS idx_monitor_logs_time ON monitor_logs(checked_at);

CREATE TABLE IF NOT EXISTS alerts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_type   TEXT    NOT NULL,                 -- unknown_device | device_offline
    severity     TEXT    NOT NULL DEFAULT 'warning', -- info | warning | critical
    status       TEXT    NOT NULL DEFAULT 'open',  -- open | ignored | resolved | trusted
    dedup_key    TEXT    NOT NULL,
    device_id    INTEGER REFERENCES devices(id) ON DELETE SET NULL,
    ip_address   TEXT,
    mac_address  TEXT,
    hostname     TEXT,
    vendor       TEXT,
    engine       TEXT,
    message      TEXT    NOT NULL,
    occurrences  INTEGER NOT NULL DEFAULT 1,
    first_seen   TEXT    NOT NULL,
    last_seen    TEXT    NOT NULL,
    resolved_at  TEXT,
    resolution   TEXT
);
-- Only one *active* (open or ignored) alert per dedup key.
CREATE UNIQUE INDEX IF NOT EXISTS ux_alerts_active_key
    ON alerts(dedup_key) WHERE status IN ('open', 'ignored');
CREATE INDEX IF NOT EXISTS idx_alerts_status ON alerts(status, last_seen);

CREATE TABLE IF NOT EXISTS bandwidth_logs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    recorded_at     TEXT    NOT NULL,
    interface       TEXT    NOT NULL,
    interval_seconds REAL   NOT NULL,
    bytes_recv      INTEGER NOT NULL,   -- bytes received during the interval
    bytes_sent      INTEGER NOT NULL,   -- bytes sent during the interval
    rx_mbps         REAL    NOT NULL,   -- average download rate over the interval
    tx_mbps         REAL    NOT NULL,   -- average upload rate over the interval
    counter_recv    INTEGER,            -- raw OS counter at sample time
    counter_sent    INTEGER
);
CREATE INDEX IF NOT EXISTS idx_bandwidth_time ON bandwidth_logs(recorded_at);

CREATE TABLE IF NOT EXISTS settings (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scan_logs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at      TEXT    NOT NULL,
    finished_at     TEXT,
    engine          TEXT    NOT NULL,
    subnet          TEXT,
    trigger         TEXT    NOT NULL DEFAULT 'scheduled',  -- scheduled | manual
    status          TEXT    NOT NULL,                      -- running | success | error | skipped
    hosts_found     INTEGER NOT NULL DEFAULT 0,
    unknown_found   INTEGER NOT NULL DEFAULT 0,
    cached_found    INTEGER NOT NULL DEFAULT 0,                -- hosts added from the OS ARP cache
    duration_ms     INTEGER,
    error           TEXT
);
CREATE INDEX IF NOT EXISTS idx_scan_logs_time ON scan_logs(started_at);
