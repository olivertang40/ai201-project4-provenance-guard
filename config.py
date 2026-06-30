"""
config.py — Provenance Guard configuration and constants
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ── API ────────────────────────────────────────────────────────────────────
GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
LLM_MODEL: str = "llama-3.3-70b-versatile"

# ── Database / Logging ─────────────────────────────────────────────────────
DB_FILE: str = "logs/provenance.db"
LOG_DIR: str = "logs"

# ── Classification thresholds ──────────────────────────────────────────────
# Confidence scores above HIGH_THRESHOLD → high-confidence label
# Confidence scores below LOW_THRESHOLD  → uncertain label
HIGH_CONFIDENCE_THRESHOLD: float = 0.75
LOW_CONFIDENCE_THRESHOLD: float = 0.55

# ── Signal weights (must sum to 1.0) ──────────────────────────────────────
# Used when STRETCH_ENSEMBLE is False (2-signal mode)
SIGNAL_WEIGHT_LLM: float = 0.60        # LLM-as-judge signal
SIGNAL_WEIGHT_STYLOMETRIC: float = 0.40  # Stylometric heuristics signal

# Ensemble (stretch) mode — 3-signal weights
SIGNAL_WEIGHT_LLM_ENSEMBLE: float = 0.50
SIGNAL_WEIGHT_STYLOMETRIC_ENSEMBLE: float = 0.30
SIGNAL_WEIGHT_PERPLEXITY_ENSEMBLE: float = 0.20

# ── Rate limiting ──────────────────────────────────────────────────────────
# 10 submissions per minute per IP  — realistic for a creative-writing user;
# adversarial flood attempts would need > 100 RPM to overwhelm the system.
# 100 submissions per hour per IP   — generous daily cap for prolific writers.
RATE_LIMIT_SUBMIT: str = "10 per minute;100 per hour"

# 30 appeals per day per IP — appeals are intentional, manual actions;
# abuse is unlikely to exceed single digits per genuine creator.
RATE_LIMIT_APPEAL: str = "30 per day"

# ── Content limits ─────────────────────────────────────────────────────────
MAX_CONTENT_CHARS: int = 10_000   # ~2 500 words — reasonable for a poem/excerpt
MIN_CONTENT_CHARS: int = 50       # Avoid noise on trivially short inputs

# ── Appeal statuses ───────────────────────────────────────────────────────
STATUS_PENDING: str = "pending"
STATUS_UNDER_REVIEW: str = "under_review"
STATUS_RESOLVED: str = "resolved"
