SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS password_resets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    token_hash TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    used INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    exam_type TEXT NOT NULL,
    mode TEXT NOT NULL,
    status TEXT NOT NULL,
    stage TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    roleplay_score INTEGER,
    topic_talk_score INTEGER,
    picture_score INTEGER,
    total_score INTEGER,
    strongest_area TEXT,
    weakest_area TEXT,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS transcripts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    attempt_id INTEGER NOT NULL,
    stage TEXT NOT NULL,
    turn_index INTEGER NOT NULL,
    speaker TEXT NOT NULL,
    prompt_id TEXT,
    text TEXT NOT NULL,
    duration_ms INTEGER,
    speech_metrics_json TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (attempt_id) REFERENCES attempts(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS prompt_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    prompt_id TEXT NOT NULL,
    meaning_key TEXT NOT NULL,
    task TEXT NOT NULL,
    used_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS markings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    attempt_id INTEGER NOT NULL UNIQUE,
    analysis_json TEXT NOT NULL,
    scores_json TEXT NOT NULL,
    justification_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (attempt_id) REFERENCES attempts(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    attempt_id INTEGER NOT NULL UNIQUE,
    strengths_json TEXT NOT NULL,
    weaknesses_json TEXT NOT NULL,
    lost_marks_json TEXT NOT NULL,
    recommendations_json TEXT NOT NULL,
    examiner_comments TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (attempt_id) REFERENCES attempts(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS self_evaluations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    attempt_id INTEGER NOT NULL UNIQUE,
    confidence INTEGER,
    fluency INTEGER,
    difficulty INTEGER,
    struggled_with TEXT,
    improve_next TEXT,
    satisfaction INTEGER,
    student_notes TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (attempt_id) REFERENCES attempts(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS gathered_info (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    topic TEXT NOT NULL,
    information TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_attempts_user ON attempts(user_id, completed_at);
CREATE INDEX IF NOT EXISTS idx_prompt_usage_user ON prompt_usage(user_id, task);
CREATE INDEX IF NOT EXISTS idx_transcripts_attempt ON transcripts(attempt_id);
CREATE INDEX IF NOT EXISTS idx_gathered_info_user ON gathered_info(user_id, created_at);
"""
