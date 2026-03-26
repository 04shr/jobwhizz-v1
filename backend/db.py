"""
JobWhiz Lab — PostgreSQL DB Helper

Schema changes vs previous version:
  - jobs table gains: salary_min, salary_is_predicted columns
  - New tables: resume_sessions, resume_job_matches
    (stores every resume analysis so we can do aggregate analytics)
"""

import os
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()


def get_db():
    return psycopg2.connect(
        host=os.getenv("DB_HOST"),
        port=int(os.getenv("DB_PORT", 5432)),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        dbname=os.getenv("DB_NAME"),
        sslmode=os.getenv("DB_SSLMODE", "require"),
    )


def query(sql, params=None):
    """Execute a SELECT and return list of dicts."""
    conn = get_db()
    with conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params or [])
            rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def execute(sql, params=None):
    """Execute INSERT/UPDATE/DELETE. Returns id if RETURNING id used."""
    conn = get_db()
    last_id = None
    with conn:
        with conn.cursor() as cur:
            cur.execute(sql, params or [])
            try:
                last_id = cur.fetchone()[0]
            except Exception:
                pass
    conn.close()
    return last_id


# ─────────────────────────────────────────────────────────────────
# SCHEMA MIGRATION
# Run once after deploying this version.
# Safe to re-run — all statements use IF NOT EXISTS / ADD COLUMN IF NOT EXISTS.
# ─────────────────────────────────────────────────────────────────
MIGRATION_SQL = """
-- ── jobs table: new salary columns ────────────────────────────────
ALTER TABLE jobs
    ADD COLUMN IF NOT EXISTS salary_min          NUMERIC(10,2),
    ADD COLUMN IF NOT EXISTS salary_is_predicted BOOLEAN DEFAULT TRUE;

-- ── resume_sessions: one row per candidate analysis session ────────
CREATE TABLE IF NOT EXISTS resume_sessions (
    id               SERIAL PRIMARY KEY,
    session_token    VARCHAR(64) UNIQUE NOT NULL,   -- random uuid, returned to frontend
    detected_role    VARCHAR(255),
    years_experience INT,
    education        TEXT,
    top_skills       TEXT[],                         -- parsed skills from resume
    summary          TEXT,                           -- one-sentence profile summary
    created_at       TIMESTAMPTZ DEFAULT NOW()
    -- Note: we deliberately do NOT store raw resume text for privacy
);

-- ── resume_job_matches: one row per (session, job, tone) analysis ──
CREATE TABLE IF NOT EXISTS resume_job_matches (
    id               SERIAL PRIMARY KEY,
    session_id       INT REFERENCES resume_sessions(id) ON DELETE CASCADE,
    job_id           INT REFERENCES jobs(id) ON DELETE SET NULL,
    tone             VARCHAR(20) DEFAULT 'normal',
    match_score      INT,                            -- 0–100 from Groq
    matched_skills   TEXT[],
    missing_skills   TEXT[],
    ats_flags        TEXT[],
    pros             TEXT[],
    cons             TEXT[],
    action_items     TEXT[],
    summary          TEXT,
    one_liner        TEXT,
    created_at       TIMESTAMPTZ DEFAULT NOW()
);

-- ── indexes for aggregate analytics queries ────────────────────────
CREATE INDEX IF NOT EXISTS idx_matches_session   ON resume_job_matches(session_id);
CREATE INDEX IF NOT EXISTS idx_matches_job        ON resume_job_matches(job_id);
CREATE INDEX IF NOT EXISTS idx_matches_score      ON resume_job_matches(match_score);
CREATE INDEX IF NOT EXISTS idx_sessions_role      ON resume_sessions(detected_role);
CREATE INDEX IF NOT EXISTS idx_sessions_created   ON resume_sessions(created_at);
"""


def run_migrations():
    """Apply schema migrations. Call once on startup or manually."""
    conn = get_db()
    with conn:
        with conn.cursor() as cur:
            cur.execute(MIGRATION_SQL)
    conn.close()
    print("Migrations applied successfully.")


if __name__ == "__main__":
    run_migrations()