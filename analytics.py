"""
analytics.py — Analytics dashboard data for Provenance Guard

Stretch Feature: Provides a simple view of detection patterns and platform health.

Three required metrics (+ extras):
  1. Detection pattern  — ratio of ai / human / uncertain verdicts
  2. Appeal rate        — what fraction of classified content gets appealed
  3. Average confidence — how certain the system is on average (by verdict type)

Additional metrics included:
  4. Confidence distribution — breakdown of high/medium/low confidence decisions
  5. Recent activity         — submissions in the last 24 hours
"""

import sqlite3
import os
from datetime import datetime, timezone, timedelta
from config import DB_FILE, LOG_DIR


def _get_db() -> sqlite3.Connection:
    os.makedirs(LOG_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def get_stats() -> dict:
    """
    Compute all analytics metrics from the audit log.
    Returns a dict suitable for jsonify().
    """
    conn = _get_db()

    # ── Total decisions ────────────────────────────────────────────────────
    total = conn.execute("SELECT COUNT(*) FROM decisions").fetchone()[0]

    # ── Detection pattern: verdict breakdown ───────────────────────────────
    verdict_rows = conn.execute(
        "SELECT verdict, COUNT(*) as count FROM decisions GROUP BY verdict"
    ).fetchall()
    verdict_counts = {r["verdict"]: r["count"] for r in verdict_rows}
    ai_count       = verdict_counts.get("ai", 0)
    human_count    = verdict_counts.get("human", 0)
    uncertain_count = verdict_counts.get("uncertain", 0)

    # ── Appeal rate ────────────────────────────────────────────────────────
    total_appeals = conn.execute("SELECT COUNT(*) FROM appeals").fetchone()[0]
    appeal_rate = round(total_appeals / total, 4) if total > 0 else 0.0

    # ── Average confidence by verdict ─────────────────────────────────────
    avg_conf_rows = conn.execute(
        "SELECT verdict, AVG(confidence) as avg_conf FROM decisions GROUP BY verdict"
    ).fetchall()
    avg_confidence_by_verdict = {
        r["verdict"]: round(r["avg_conf"], 4) for r in avg_conf_rows
    }
    overall_avg_confidence = conn.execute(
        "SELECT AVG(confidence) FROM decisions"
    ).fetchone()[0]
    overall_avg_confidence = round(overall_avg_confidence, 4) if overall_avg_confidence else 0.0

    # ── Confidence distribution ────────────────────────────────────────────
    # High: confidence >= 0.60, Medium: 0.30-0.60, Low: < 0.30
    high_conf  = conn.execute("SELECT COUNT(*) FROM decisions WHERE confidence >= 0.60").fetchone()[0]
    med_conf   = conn.execute("SELECT COUNT(*) FROM decisions WHERE confidence >= 0.30 AND confidence < 0.60").fetchone()[0]
    low_conf   = conn.execute("SELECT COUNT(*) FROM decisions WHERE confidence < 0.30").fetchone()[0]

    # ── Recent activity (last 24 hours) ───────────────────────────────────
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")
    recent_submissions = conn.execute(
        "SELECT COUNT(*) FROM decisions WHERE timestamp >= ?", (cutoff,)
    ).fetchone()[0]
    recent_appeals = conn.execute(
        "SELECT COUNT(*) FROM appeals WHERE timestamp >= ?", (cutoff,)
    ).fetchone()[0]

    # ── Certificate stats ──────────────────────────────────────────────────
    try:
        total_certs = conn.execute("SELECT COUNT(*) FROM certificates").fetchone()[0]
    except Exception:
        total_certs = 0

    conn.close()

    return {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total_submissions": total,

        # Metric 1: Detection pattern
        "detection_pattern": {
            "ai":       ai_count,
            "human":    human_count,
            "uncertain": uncertain_count,
            "ai_pct":       round(ai_count / total * 100, 1) if total else 0,
            "human_pct":    round(human_count / total * 100, 1) if total else 0,
            "uncertain_pct": round(uncertain_count / total * 100, 1) if total else 0,
        },

        # Metric 2: Appeal rate
        "appeal_stats": {
            "total_appeals": total_appeals,
            "appeal_rate":   appeal_rate,
            "appeal_rate_pct": round(appeal_rate * 100, 1),
        },

        # Metric 3: Average confidence (by verdict + overall)
        "confidence_stats": {
            "overall_avg":      overall_avg_confidence,
            "by_verdict":       avg_confidence_by_verdict,
            "high_confidence":  high_conf,   # >= 0.60
            "med_confidence":   med_conf,    # 0.30 – 0.60
            "low_confidence":   low_conf,    # < 0.30
        },

        # Metric 4: Recent activity (24h)
        "recent_24h": {
            "submissions": recent_submissions,
            "appeals":     recent_appeals,
        },

        # Metric 5: Certificates issued
        "certificates_issued": total_certs,
    }
