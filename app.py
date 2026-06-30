"""
app.py — Provenance Guard Flask API

Endpoints:
  POST /submit              — Submit content for attribution analysis
  POST /appeal              — Contest a classification decision
  POST /verify              — Request a Provenance Certificate (verified human)
  GET  /certificate/<id>    — Retrieve a certificate for a piece of content
  GET  /stats               — Analytics dashboard (detection patterns, appeal rate, etc.)
  GET  /log                 — View recent audit log entries
  GET  /health              — Health check
"""

import uuid
from flask import Flask, request, jsonify
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from classifier import run_detection_pipeline
from confidence import evaluate
from appeals import submit_appeal
from certificate import issue_certificate, get_certificate
from analytics import get_stats
from auditor import log_decision, get_log_entries, get_decision
from config import (
    RATE_LIMIT_SUBMIT, RATE_LIMIT_APPEAL,
    MAX_CONTENT_CHARS, MIN_CONTENT_CHARS,
)

app = Flask(__name__)

# ── Rate limiting ──────────────────────────────────────────────────────────
# Keyed by remote IP address.
# Limits are documented in README and config.py.
limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    default_limits=[],          # no global default; limits are per-route
    storage_uri="memory://",    # in-memory store — fine for single-process dev
)


# ── POST /submit ───────────────────────────────────────────────────────────

@app.route("/submit", methods=["POST"])
@limiter.limit(RATE_LIMIT_SUBMIT)
def submit():
    """
    Submit a piece of text content for attribution analysis.

    Request JSON:
      {
        "content": "The text to analyze...",
        "ensemble": false       (optional — use 3-signal ensemble)
      }

    Response JSON:
      {
        "content_id":      "uuid string",
        "verdict":         "ai" | "human" | "uncertain",
        "confidence":      0.0–1.0,
        "raw_score":       0.0–1.0,
        "signals": {
          "llm":           { "score": ..., "label": ..., "explanation": ... },
          "stylometric":   { "score": ..., "label": ..., "explanation": ... }
        },
        "label": {
          "heading":       "...",
          "badge":         "...",
          "icon":          "...",
          "body":          "...",
          "detail":        "...",
          "appeal_note":   "..."
        }
      }
    """
    data = request.get_json(silent=True) or {}

    # Accept both "text" (Milestone 3 spec field) and "content" (our internal name)
    content = data.get("text") or data.get("content", "")
    creator_id = data.get("creator_id", "anonymous").strip() or "anonymous"
    ensemble = bool(data.get("ensemble", False))

    # ── Input validation ───────────────────────────────────────────────────
    if not isinstance(content, str) or not content.strip():
        return jsonify({"error": "Field 'content' is required and must be a non-empty string."}), 400

    if len(content) < MIN_CONTENT_CHARS:
        return jsonify({
            "error": f"Content is too short. Minimum {MIN_CONTENT_CHARS} characters required."
        }), 400

    if len(content) > MAX_CONTENT_CHARS:
        return jsonify({
            "error": f"Content exceeds maximum length of {MAX_CONTENT_CHARS} characters."
        }), 400

    # ── Detection pipeline ─────────────────────────────────────────────────
    detection = run_detection_pipeline(content, ensemble=ensemble)
    result = evaluate(detection["final_score"])

    # ── Generate content ID and log ────────────────────────────────────────
    content_id = str(uuid.uuid4())
    llm_score = detection["signals"].get("llm", {}).get("score")
    stylo_score = detection["signals"].get("stylometric", {}).get("score")

    log_decision(
        content_id=content_id,
        verdict=result.verdict,
        confidence=result.confidence_score,
        raw_score=result.raw_score,
        llm_score=llm_score,
        stylometric_score=stylo_score,
        content_preview=content[:300],
        creator_id=creator_id,
    )

    # ── Response ───────────────────────────────────────────────────────────
    return jsonify({
        "content_id": content_id,
        "creator_id": creator_id,
        # "attribution" mirrors "verdict" — the field name used in Milestone 3 spec
        "attribution": result.verdict,
        "verdict": result.verdict,
        "confidence": result.confidence_score,
        "raw_score": result.raw_score,
        "signals": detection["signals"],
        "weights": detection["weights"],
        "label": result.label,
        "status": "classified",
    }), 200


# ── POST /appeal ───────────────────────────────────────────────────────────

@app.route("/appeal", methods=["POST"])
@limiter.limit(RATE_LIMIT_APPEAL)
def appeal():
    """
    Submit an appeal for a misclassified piece of content.

    Request JSON:
      {
        "content_id": "uuid of the original submission",
        "reason":     "Why the creator believes the classification is wrong"
      }

    Response JSON:
      {
        "success":          true | false,
        "message":          "...",
        "content_id":       "...",       (on success)
        "original_verdict": "...",       (on success)
        "new_status":       "under_review"  (on success)
      }
    """
    data = request.get_json(silent=True) or {}
    content_id = data.get("content_id", "").strip()
    # Accept both "reason" and "creator_reasoning" (CodePath spec field name)
    reason = (data.get("reason") or data.get("creator_reasoning") or "").strip()

    if not content_id:
        return jsonify({"error": "Field 'content_id' is required."}), 400
    if not reason:
        return jsonify({"error": "Field 'reason' is required."}), 400

    result = submit_appeal(content_id, reason)

    # Mirror CodePath guide shape: content_id + status + message at top level
    if result["success"]:
        return jsonify({
            "content_id": content_id,
            "status": "under_review",
            "message": result["message"],
            "original_verdict": result.get("original_verdict"),
            "success": True,
        }), 200
    else:
        return jsonify(result), 400


# ── GET /log ───────────────────────────────────────────────────────────────

@app.route("/log", methods=["GET"])
def log():
    """
    Return recent audit log entries.

    Query params:
      limit (int, default 20, max 100) — number of entries to return

    Response JSON:
      {
        "count": N,
        "entries": [ { ...decision fields... }, ... ]
      }
    """
    try:
        limit = min(int(request.args.get("limit", 20)), 100)
    except ValueError:
        limit = 20

    entries = get_log_entries(limit=limit)
    # Shape matches CodePath guide: {"entries": [...]}
    # "count" is a convenience bonus — not required by the spec
    return jsonify({"entries": entries, "count": len(entries)}), 200


# ── GET /health ────────────────────────────────────────────────────────────

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "provenance-guard"}), 200


# ── POST /verify ───────────────────────────────────────────────────────────

@app.route("/verify", methods=["POST"])
@limiter.limit("5 per hour")
def verify():
    """
    Request a Provenance Certificate for a human-classified piece of content.

    This is the verification step a creator completes to earn a
    'Verified Human' credential on their work. The certificate is
    DISTINCT from the automated transparency label — it requires the
    creator to actively attest authorship.

    Requirements:
      - content_id must exist and have verdict = "human"
      - confidence must be >= 0.40 (some signal required)
      - attestation must be >= 20 characters

    Request JSON:
      {
        "content_id":  "uuid from /submit response",
        "creator_id":  "creator identifier",
        "attestation": "I wrote this poem over three weeks, drawing from
                        personal experience during my time living in Kyoto."
      }

    Response JSON (success):
      {
        "success":    true,
        "cert_id":    "uuid",
        "content_id": "...",
        "creator_id": "...",
        "issued_at":  "ISO 8601",
        "message":    "Certificate issued...",
        "label": {
          "heading":      "✅ Verified Human-Written",
          "badge":        "VERIFIED HUMAN",
          "icon":         "🏅",
          "body":         "...",
          "detail":       "...",
          "creator_note": "...",
          "cert_id":      "...",
          "issued_at":    "..."
        }
      }
    """
    data = request.get_json(silent=True) or {}
    content_id  = data.get("content_id", "").strip()
    creator_id  = data.get("creator_id", "anonymous").strip() or "anonymous"
    attestation = data.get("attestation", "").strip()

    if not content_id:
        return jsonify({"error": "Field 'content_id' is required."}), 400
    if not attestation:
        return jsonify({"error": "Field 'attestation' is required."}), 400

    # Look up the original decision
    decision = get_decision(content_id)
    if decision is None:
        return jsonify({"error": f"No decision found for content_id '{content_id}'."}), 404

    result = issue_certificate(content_id, creator_id, attestation, decision)

    status_code = 200 if result["success"] else 400
    return jsonify(result), status_code


# ── GET /certificate/<content_id> ──────────────────────────────────────────

@app.route("/certificate/<content_id>", methods=["GET"])
def certificate(content_id: str):
    """
    Retrieve the Provenance Certificate for a piece of content.

    Returns the certificate with its verified-human label if one exists,
    or 404 if no certificate has been issued for this content.

    The certificate label is DISTINGUISHABLE from the standard transparency
    label: badge = "VERIFIED HUMAN" (vs "HUMAN-WRITTEN"), icon = 🏅 (vs ✍️),
    and includes cert_id + issued_at fields.

    Response JSON (found):
      {
        "cert_id":    "uuid",
        "content_id": "...",
        "creator_id": "...",
        "issued_at":  "ISO 8601",
        "label": { "heading": "✅ Verified Human-Written", "badge": "VERIFIED HUMAN", ... }
      }
    """
    cert = get_certificate(content_id)
    if cert is None:
        return jsonify({
            "error": "No certificate found for this content.",
            "content_id": content_id,
        }), 404
    return jsonify(cert), 200


# ── GET /stats ─────────────────────────────────────────────────────────────

@app.route("/stats", methods=["GET"])
def stats():
    """
    Analytics dashboard — detection patterns and platform health metrics.

    Returns 5 metrics:
      1. detection_pattern  — ratio of ai/human/uncertain verdicts
      2. appeal_stats       — total appeals and appeal rate
      3. confidence_stats   — avg confidence by verdict + distribution
      4. recent_24h         — submissions and appeals in last 24 hours
      5. certificates_issued — total verified-human certificates

    Response JSON:
      {
        "generated_at":        "ISO 8601",
        "total_submissions":   N,
        "detection_pattern":   { "ai": N, "human": N, "uncertain": N,
                                 "ai_pct": %, "human_pct": %, "uncertain_pct": % },
        "appeal_stats":        { "total_appeals": N, "appeal_rate": 0.0–1.0,
                                 "appeal_rate_pct": % },
        "confidence_stats":    { "overall_avg": 0.0–1.0, "by_verdict": {...},
                                 "high_confidence": N, "med_confidence": N,
                                 "low_confidence": N },
        "recent_24h":          { "submissions": N, "appeals": N },
        "certificates_issued": N
      }
    """
    return jsonify(get_stats()), 200


# ── Entry point ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app.run(debug=True, port=5000)
