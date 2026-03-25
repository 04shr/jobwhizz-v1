"""
JobWhiz Lab — PostgreSQL DB Helper
Uses psycopg2 with connection pooling. All queries return list-of-dicts.
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
            if params:
                cur.execute(sql, params)
            else:
                cur.execute(sql)
            rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def execute(sql, params=None):
    """Execute INSERT/UPDATE/DELETE. Returns lastrowid via RETURNING id."""
    conn = get_db()
    last_id = None
    with conn:
        with conn.cursor() as cur:
            if params:
                cur.execute(sql, params)
            else:
                cur.execute(sql)
            try:
                last_id = cur.fetchone()[0]
            except Exception:
                pass
    conn.close()
    return last_id
