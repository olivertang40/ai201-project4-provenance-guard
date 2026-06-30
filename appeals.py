"""
appeals.py — Appeals workflow for Provenance Guard

Handles creator disputes of attribution decisions.

Flow:
  1. Creator submits POST /appeal with content_id + reason
  2. System validates that the content_id exists in the audit log
  3. Appeal is recorded alongside the original decision
  4. Decision status is updated to "under_review"
  5. No automated re-classification — a human moderator reviews

This is intentionally simple: the point is to give creators a clear path
to contest a classification, not to build a full moderation platform.
"""

from auditor import log_appeal, get_decision
from config import STATUS_UNDER_REVIEW


def submit_appeal(content_id: str, creator_reason: str) -> dict:
    """
    Process a creator's appeal of an attribution decision.

    Args:
        content_id:     The ID of the content being appealed.
        creator_reason: The creator's explanation of why they believe
                        the classification is incorrect.

    Returns:
        A dict with 'success', 'message', and (on success) the updated status.
    """
    if not content_id or not content_id.strip():
        return {"success": False, "message": "content_id is required."}

    if not creator_reason or len(creator_reason.strip()) < 10:
        return {
            "success": False,
            "message": "Please provide a reason of at least 10 characters.",
        }

    # Look up the original decision
    decision = get_decision(content_id)
    if decision is None:
        return {
            "success": False,
            "message": f"No decision found for content_id '{content_id}'.",
        }

    if decision["status"] == STATUS_UNDER_REVIEW:
        return {
            "success": False,
            "message": "An appeal for this content is already under review.",
        }

    original_verdict = decision["verdict"]
    log_appeal(content_id, creator_reason.strip(), original_verdict)

    return {
        "success": True,
        "message": (
            "Your appeal has been submitted. A human moderator will review "
            "your content and reasoning. Status updated to 'under_review'."
        ),
        "content_id": content_id,
        "original_verdict": original_verdict,
        "new_status": STATUS_UNDER_REVIEW,
    }
