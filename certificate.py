"""
certificate.py — Provenance Certificate ("Verified Human") for Provenance Guard

Stretch Feature: A creator earns a verified-human certificate by completing
an additional verification step on content that was classified as human-written.

Design
──────
Verification flow:
  1. Creator submits POST /verify with:
       - content_id  : a submission that received verdict="human"
       - creator_id  : the creator's identifier
       - attestation : a short personal statement about the work
  2. System checks:
       - content_id exists and has verdict="human"
       - The confidence score is >= CERT_MIN_CONFIDENCE (0.50)
         (we require at least some signal, not just a borderline case)
       - No certificate has already been issued for this content_id
  3. Issues a certificate: a UUID token stored in SQLite
  4. Marks the content with a "verified_human" badge

GET /certificate/<content_id>
  Returns the certificate details and a displayable verified label,
  or 404 if no certificate exists for that content.

Certificate label (distinct from the standard transparency label):
  badge:   "VERIFIED HUMAN"
  heading: "✅ Verified Human-Written"
  body:    "The creator has verified authorship of this content through
            our attestation process. This certificate supplements the
            system's automated classification."
  issued:  ISO 8601 timestamp
  cert_id: UUID

What makes this different from the standard human label:
  Standard label: automated signal output, no creator involvement
  Certificate:    creator actively attested + content passed human threshold
                  → stronger claim, different badge, separate audit trail
"""

import sqlite3
import uuid
import os
from datetime import datetime, timezone
from config import DB_FILE, LOG_DIR

# Minimum confidence required to issue a certificate
# (raw_score must be <= 0.25 for human verdict, confidence >= this value)
CERT_MIN_CONFIDENCE: float = 0.40


def _get_db() -> sqlite3.Connection:
    os.makedirs(LOG_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    _ensure_cert_table(conn)
    return conn


def _ensure_cert_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS certificates (
            cert_id     TEXT PRIMARY KEY,
            content_id  TEXT NOT NULL,
            creator_id  TEXT NOT NULL,
            attestation TEXT NOT NULL,
            issued_at   TEXT NOT NULL,
            raw_score   REAL NOT NULL,
            confidence  REAL NOT NULL
        )
    """)
    conn.commit()


def issue_certificate(
    content_id: str,
    creator_id: str,
    attestation: str,
    decision: dict,
) -> dict:
    """
    Issue a provenance certificate for a human-verified piece of content.

    Args:
        content_id:   The content being certified.
        creator_id:   The creator claiming authorship.
        attestation:  A short personal statement from the creator.
        decision:     The original decision dict from the audit log.

    Returns:
        dict with success, cert_id, and the displayable certificate label.
    """
    # Validate: must be human verdict
    if decision["verdict"] != "human":
        return {
            "success": False,
            "message": (
                f"Certificates can only be issued for content classified as human-written. "
                f"This content was classified as '{decision['verdict']}'."
            ),
        }

    # Validate: confidence must meet minimum threshold
    confidence = decision.get("confidence", 0.0)
    if confidence < CERT_MIN_CONFIDENCE:
        return {
            "success": False,
            "message": (
                f"The human classification confidence ({confidence:.2f}) is below the "
                f"minimum required for certification ({CERT_MIN_CONFIDENCE:.2f}). "
                "The system is not confident enough in the human verdict to certify it."
            ),
        }

    # Validate: attestation must be substantive
    if not attestation or len(attestation.strip()) < 20:
        return {
            "success": False,
            "message": "Attestation must be at least 20 characters.",
        }

    conn = _get_db()

    # Check for duplicate certificate
    existing = conn.execute(
        "SELECT cert_id FROM certificates WHERE content_id = ?",
        (content_id,),
    ).fetchone()
    if existing:
        conn.close()
        return {
            "success": False,
            "message": "A certificate has already been issued for this content.",
            "cert_id": existing["cert_id"],
        }

    # Issue the certificate
    cert_id = str(uuid.uuid4())
    issued_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    conn.execute(
        """INSERT INTO certificates
           (cert_id, content_id, creator_id, attestation, issued_at, raw_score, confidence)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            cert_id, content_id, creator_id, attestation.strip(),
            issued_at, decision["raw_score"], confidence,
        ),
    )
    conn.commit()
    conn.close()

    print(f"[CERT] {issued_at} | cert={cert_id} | content={content_id} | creator={creator_id}")

    return {
        "success": True,
        "cert_id": cert_id,
        "content_id": content_id,
        "creator_id": creator_id,
        "issued_at": issued_at,
        "message": "Certificate issued. This content is now marked as Verified Human-Written.",
        "label": _build_cert_label(cert_id, issued_at, creator_id),
    }


def get_certificate(content_id: str) -> dict | None:
    """
    Retrieve a certificate by content_id.
    Returns the certificate dict with its displayable label, or None.
    """
    conn = _get_db()
    row = conn.execute(
        "SELECT * FROM certificates WHERE content_id = ?",
        (content_id,),
    ).fetchone()
    conn.close()

    if not row:
        return None

    cert = dict(row)
    cert["label"] = _build_cert_label(
        cert["cert_id"], cert["issued_at"], cert["creator_id"]
    )
    return cert


def _build_cert_label(cert_id: str, issued_at: str, creator_id: str) -> dict:
    """
    Build the displayable verified-human certificate label.

    This is DISTINCT from the standard transparency label:
    - Standard:    automated signal output, no creator involvement
    - Certificate: creator actively attested + content passed human threshold
    """
    return {
        "heading": "✅ Verified Human-Written",
        "badge": "VERIFIED HUMAN",
        "icon": "🏅",
        "body": (
            "The creator has verified authorship of this content through "
            "our attestation process. This certificate supplements the "
            "system's automated classification."
        ),
        "detail": (
            f"Certificate ID: {cert_id[:8]}... — "
            f"Issued: {issued_at}. "
            "Creator completed an additional verification step confirming "
            "human authorship beyond automated signals."
        ),
        "creator_note": (
            f"Verified by creator '{creator_id}'. "
            "This is a creator-attested label, not a guarantee of authorship."
        ),
        "cert_id": cert_id,
        "issued_at": issued_at,
    }
