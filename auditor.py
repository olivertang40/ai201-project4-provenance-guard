"""
auditor.py — Structured audit logging for Provenance Guard

Uses SQLite (built into Python) to store every attribution decision and appeal.
SQLite is simpler than JSONL for querying, and still fully file-based with no
extra setup needed.
"""

import sqlite3
import os
from datetime import datetime, timezone
from config import DB_FILE, LOG_DIR


def _get_db() -> sqlite3.Connection:
    """Open (or create) the SQLite database and ensure tables exist."""
    os.makedirs(LOG_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    _create_tables(conn)
    return conn


def _create_tables(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS decisions (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            content_id      TEXT NOT NULL,
            timestamp       TEXT NOT NULL,
            verdict         TEXT NOT NULL,
            confidence      REAL NOT NULL,
            raw_score       REAL NOT NULL,
            llm_score       REAL,
            stylometric_score REAL,
            content_preview TEXT,
            creator_id      TEXT NOT NULL DEFAULT 'anonymous',
            status          TEXT NOT NULL DEFAULT 'classified'
        );

        CREATE TABLE IF NOT EXISTS appeals (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            content_id      TEXT NOT NULL,
            timestamp       TEXT NOT NULL,
            creator_reason  TEXT NOT NULL,
            original_verdict TEXT NOT NULL,
            status          TEXT NOT NULL DEFAULT 'under_review'
        );
    """)
    conn.commit()


def log_decision(
    content_id: str,
    verdict: str,
    confidence: float,
    raw_score: float,
    llm_score: float | None,
    stylometric_score: float | None,
    content_preview: str,
    creator_id: str = "anonymous",
) -> None:
    """Record an attribution decision to the audit log."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn = _get_db()
    conn.execute(
        """INSERT INTO decisions
           (content_id, timestamp, verdict, confidence, raw_score,
            llm_score, stylometric_score, content_preview, creator_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            content_id, ts, verdict, confidence, raw_score,
            llm_score, stylometric_score, content_preview[:300], creator_id,
        ),
    )
    conn.commit()
    conn.close()
    print(f"[AUDIT] {ts} | id={content_id} | creator={creator_id} | verdict={verdict} | score={raw_score:.2f}")


def log_appeal(content_id: str, creator_reason: str, original_verdict: str) -> None:
    """Record an appeal and update the decision status to 'under_review'."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn = _get_db()
    conn.execute(
        """INSERT INTO appeals (content_id, timestamp, creator_reason, original_verdict)
           VALUES (?, ?, ?, ?)""",
        (content_id, ts, creator_reason, original_verdict),
    )
    conn.execute(
        "UPDATE decisions SET status = 'under_review' WHERE content_id = ?",
        (content_id,),
    )
    conn.commit()
    conn.close()
    print(f"[APPEAL] {ts} | id={content_id} | original={original_verdict}")


def get_log_entries(limit: int = 50) -> list[dict]:
    """Return the most recent audit log entries as a list of dicts."""
    conn = _get_db()
    rows = conn.execute(
        "SELECT * FROM decisions ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    entries = [dict(r) for r in rows]
    for entry in entries:
        entry["attribution"] = entry["verdict"]
    return entries


def get_decision(content_id: str) -> dict | None:
    """Fetch a single decision by content_id, or None if not found."""
    conn = _get_db()
    row = conn.execute(
        "SELECT * FROM decisions WHERE content_id = ? ORDER BY id DESC LIMIT 1",
        (content_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None
