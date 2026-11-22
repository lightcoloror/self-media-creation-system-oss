#!/usr/bin/env python3
"""Unified check-result structure, anti-hollow validation, and checkpoint projection."""
from __future__ import annotations

import re
from typing import Any

CHECK_STATUSES = ("passed", "failed", "blocked", "not_required", "stale")
SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
HOLLOW_KEYS = {"synthetic_only", "ok", "status", "placeholder"}
DISALLOWED_HUMAN_ACTORS = {"", "assistant", "ai", "agent", "bot", "auto", "synthetic_auto"}


def make_check_result(
    check_id: str,
    status: str,
    *,
    artifact_hash: str | None = None,
    input_hashes: dict[str, str] | None = None,
    findings: list[dict[str, Any]] | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a normalized verification result for existing manifests and audit outputs."""
    if status not in CHECK_STATUSES:
        raise ValueError(f"invalid_check_status:{status}")
    return {
        "check_id": str(check_id),
        "status": status,
        "artifact_hash": artifact_hash,
        "input_hashes": dict(input_hashes or {}),
        "findings": list(findings or []),
        **({"details": dict(details)} if details else {}),
    }


def is_hollow_payload(value: Any) -> bool:
    """Detect empty or placeholder-only JSON outputs lacking real semantic/progress bindings."""
    if value is None:
        return True
    if isinstance(value, (list, str)):
        return len(value) == 0
    if not isinstance(value, dict):
        return False
    if not value:
        return True
    if value.get("placeholder") is True:
        return True
    keys = set(value.keys())
    has_schema = isinstance(value.get("schema_version"), str) or isinstance(value.get("schema"), str)
    if not has_schema and keys <= HOLLOW_KEYS:
        return True
    return False


def validate_human_gate_credential(value: Any, *, step_id: str | None = None) -> tuple[bool, str]:
    """Verify a human_gate artifact carries concrete reviewer, time, decision, and artifact hash."""
    if not isinstance(value, dict) or is_hollow_payload(value):
        return False, "hollow_human_gate_output"
    schema = value.get("schema_version") or value.get("schema")
    if not isinstance(schema, str) or not schema.strip():
        return False, "human_gate_schema_missing"
    reviewer = value.get("reviewer") or value.get("reviewed_by")
    if not isinstance(reviewer, str) or reviewer.strip().lower() in DISALLOWED_HUMAN_ACTORS:
        return False, "human_reviewer_required"
    reviewed_at = value.get("reviewed_at") or value.get("confirmed_at") or value.get("checked_at")
    if not isinstance(reviewed_at, str) or not reviewed_at.strip():
        return False, "human_reviewed_at_required"
    decision = value.get("decision") or value.get("status")
    if decision not in {"approved", "pass", "passed", "confirmed", "synthetic_confirmed"}:
        return False, f"human_gate_decision_not_approved:{decision}"
    if step_id and value.get("step_id") and value.get("step_id") != step_id:
        return False, "human_gate_step_mismatch"
    hash_fields = (
        "artifact_sha256",
        "target_sha256",
        "input_fingerprint",
        "package_sha256",
        "revision_sha256",
        "output_sha256",
        "video_sha256",
    )
    has_hash = any(
        isinstance(value.get(field), str) and SHA256_RE.fullmatch(value[field]) is not None
        for field in hash_fields
    )
    if not has_hash:
        target_ref = value.get("target_ref") or value.get("artifact_ref") or {}
        if isinstance(target_ref, dict):
            has_hash = isinstance(target_ref.get("sha256"), str) and SHA256_RE.fullmatch(target_ref["sha256"]) is not None
    if not has_hash:
        return False, "human_gate_artifact_hash_missing"
    return True, "human_gate_credential_bound"


def classify_step_checkpoint(step_id: str) -> str:
    """Map fine-grained recipe steps to the three terminal governance checkpoints."""
    charter_steps = {
        "verify-canonical-route",
        "propose-editorial-angle",
        "confirm-editorial-angle",
        "discover-research-owner",
        "produce-verified-research-output",
        "verify-production-run-lock",
        "capture-initial-privacy-treatment",
        "plan-bounded-review",
    }
    delivery_steps = {
        "approve-exact-package",
        "verify-frozen-package",
        "handoff-manual-publication",
        "verify-privacy-redaction-binding",
        "record-customer-video-effect-review",
        "evaluate-prepublication-privacy",
        "confirm-manual-publication-or-rework",
        "review-operating-draft",
        "verify-bounded-review",
        "final-human-qa",
    }
    if step_id in charter_steps:
        return "charter_checkpoint"
    if step_id in delivery_steps:
        return "joint_delivery_checkpoint"
    return "master_review_checkpoint"


def summarize_sequence_checkpoints(steps: list[dict[str, Any]], accepted_steps: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize fine steps into the 3 terminal checkpoints without creating parallel state."""
    accepted_by_id = {row["step_id"]: row for row in accepted_steps}
    summary: dict[str, dict[str, Any]] = {}
    for cp in ("charter_checkpoint", "master_review_checkpoint", "joint_delivery_checkpoint"):
        bucket = [step["step_id"] for step in steps if classify_step_checkpoint(step["step_id"]) == cp]
        if not bucket:
            summary[cp] = {"status": "not_required", "total_steps": 0, "verified_steps": 0}
            continue
        recorded = [sid for sid in bucket if sid in accepted_by_id]
        verified = [sid for sid in recorded if accepted_by_id[sid].get("workflow_step_completed")]
        if len(verified) == len(bucket):
            status = "passed"
        elif len(recorded) > 0:
            status = "in_progress"
        else:
            status = "pending"
        summary[cp] = {
            "status": status,
            "total_steps": len(bucket),
            "recorded_steps": len(recorded),
            "verified_steps": len(verified),
        }
    return summary
