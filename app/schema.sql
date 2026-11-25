-- צפון LIVE – מבנה הנתונים (SQLite בשלב א; הסכמה תואמת מעבר ל-PostgreSQL)
-- כל הזמנים נשמרים כמחרוזת ISO-8601 ב-UTC.

CREATE TABLE IF NOT EXISTS locations (
    id            INTEGER PRIMARY KEY,
    kind          TEXT NOT NULL CHECK (kind IN ('locality','road','junction','region')),
    name_he       TEXT NOT NULL,
    aliases       TEXT NOT NULL DEFAULT '[]',          -- JSON: שמות נוספים (עברית/ערבית/אנגלית)
    lat           REAL,
    lon           REAL,
    coord_quality TEXT NOT NULL DEFAULT 'none' CHECK (coord_quality IN ('verified','approx','none')),
    parent_id     INTEGER REFERENCES locations(id),
    UNIQUE (kind, name_he),
    CHECK ((lat IS NULL) = (lon IS NULL)),
    CHECK (coord_quality = 'none' OR lat IS NOT NULL)
);

CREATE TABLE IF NOT EXISTS sources (
    id             INTEGER PRIMARY KEY,
    name           TEXT NOT NULL,
    kind           TEXT NOT NULL CHECK (kind IN ('telegram','rss','api','website','other')),
    address        TEXT NOT NULL,                      -- כפי שהוזן
    address_norm   TEXT NOT NULL,                      -- מנורמל, למניעת כפילות
    is_official    INTEGER NOT NULL DEFAULT 0,
    coverage       TEXT NOT NULL DEFAULT '[]',         -- JSON: מזהי locations
    wanted_types   TEXT NOT NULL DEFAULT '[]',         -- JSON: סוגי אירועים רצויים
    priority       INTEGER NOT NULL DEFAULT 3 CHECK (priority BETWEEN 1 AND 5),
    enabled        INTEGER NOT NULL DEFAULT 1,
    -- configured = רק הוגדר | verified = בדיקת חיבור הצליחה | ingesting = נקלט מידע אמיתי | error
    status         TEXT NOT NULL DEFAULT 'configured'
                   CHECK (status IN ('configured','verified','ingesting','error')),
    last_check_at  TEXT,
    last_error     TEXT,
    last_ingest_at TEXT,
    ingested_count INTEGER NOT NULL DEFAULT 0,
    is_demo        INTEGER NOT NULL DEFAULT 0,
    created_at     TEXT NOT NULL,
    UNIQUE (kind, address_norm),
    CHECK (status <> 'ingesting' OR ingested_count > 0)
);

CREATE TABLE IF NOT EXISTS raw_reports (
    id           INTEGER PRIMARY KEY,
    source_id    INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    external_id  TEXT NOT NULL,                        -- מזהה ההודעה אצל המקור
    url          TEXT,                                 -- קישור להודעה המקורית
    published_at TEXT NOT NULL,
    ingested_at  TEXT NOT NULL,
    edited_at    TEXT,
    content      TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    lang         TEXT,
    ai_result    TEXT,                                 -- JSON: תוצאת הניתוח (שלב ג)
    noise        TEXT,                                 -- סיבת סינון (שאלה, קצר מדי, פרסומת...) או NULL
    is_demo      INTEGER NOT NULL DEFAULT 0,
    UNIQUE (source_id, external_id)                    -- מניעת קליטה כפולה
);
CREATE INDEX IF NOT EXISTS ix_raw_published ON raw_reports(published_at);
CREATE INDEX IF NOT EXISTS ix_raw_hash ON raw_reports(content_hash);

CREATE TABLE IF NOT EXISTS events (
    id                 INTEGER PRIMARY KEY,
    title              TEXT NOT NULL,
    summary            TEXT NOT NULL DEFAULT '',
    event_type         TEXT NOT NULL CHECK (event_type IN
                       ('security','accident','fire','closure','infrastructure','weather','hazard','medical','earthquake','cyber','health','other')),
    status             TEXT NOT NULL DEFAULT 'new' CHECK (status IN ('new','ongoing','ended','unknown')),
    verification       TEXT NOT NULL DEFAULT 'single_source'
                       CHECK (verification IN ('single_source','multi_source','official','retracted')),
    severity           INTEGER NOT NULL DEFAULT 1 CHECK (severity BETWEEN 1 AND 3),
    location_id        INTEGER REFERENCES locations(id),
    location_precision TEXT NOT NULL DEFAULT 'unknown'
                       CHECK (location_precision IN ('exact','approx','unknown')),
    occurred_at        TEXT,                           -- זמן האירוע עצמו, אם ידוע
    first_reported_at  TEXT NOT NULL,
    updated_at         TEXT NOT NULL,
    published          INTEGER NOT NULL DEFAULT 1,     -- 0 = מושהה עד בדיקה אנושית
    places             TEXT NOT NULL DEFAULT '[]',     -- JSON: כל המקומות שזוהו
    analyzer           TEXT,                           -- איזה מנתח יצר את האירוע (rules-1 / ai-...)
    is_demo            INTEGER NOT NULL DEFAULT 0,
    CHECK (location_id IS NOT NULL OR location_precision = 'unknown')
);
CREATE INDEX IF NOT EXISTS ix_events_updated ON events(updated_at);
CREATE INDEX IF NOT EXISTS ix_events_loc_type ON events(location_id, event_type, first_reported_at);

CREATE TABLE IF NOT EXISTS event_reports (
    event_id      INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    raw_report_id INTEGER NOT NULL UNIQUE REFERENCES raw_reports(id) ON DELETE CASCADE,
    relation      TEXT NOT NULL DEFAULT 'report'
                  CHECK (relation IN ('report','update','copy','contradiction','official','recap')),
    PRIMARY KEY (event_id, raw_report_id)
);

CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY,
    email         TEXT NOT NULL UNIQUE,
    role          TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('user','admin')),
    password_hash TEXT,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS alert_preferences (
    id           INTEGER PRIMARY KEY,
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    location_id  INTEGER REFERENCES locations(id),
    event_type   TEXT,
    min_severity INTEGER NOT NULL DEFAULT 1,
    created_at   TEXT NOT NULL,
    UNIQUE (user_id, location_id, event_type)
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id        INTEGER PRIMARY KEY,
    at        TEXT NOT NULL,
    actor     TEXT NOT NULL,
    action    TEXT NOT NULL,
    entity    TEXT NOT NULL,
    entity_id INTEGER,
    detail    TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS ix_audit_at ON audit_logs(at);
