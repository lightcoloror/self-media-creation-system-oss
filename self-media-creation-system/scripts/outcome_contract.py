"""First-party pure outcome contract excerpt; no ledger reads, writes or provider calls.

Public edition Apache-2.0. Source symbols and hashes are recorded in shared-resource-provenance.json.
"""
from __future__ import annotations
import hashlib
import json
import re
from typing import Any

SCHEMA_VERSION = "tool_model_fit.outcome_ledger.v1"

OUTCOMES = {"adopted", "adopted_with_edits", "discarded", "no_decision"}

DIMENSIONS = ("quality", "latency", "stability", "cost", "privacy", "context", "structured_output", "substitutability")

RISK_DOMAINS = {"customer", "insurance", "health", "legal", "financial", "high_risk_other"}

FORBIDDEN_KEYS = re.compile(r"(?:prompt(?:_body|_text)?|api[_-]?key|secret|password|token|authorization|cookie|customer|patient|policy_number|medical|health_detail)", re.I)

SAFE_PRIVACY_KEYS = {"prompt_body_stored", "promptfoo_observation", "tokenUsage"}

SECRET_VALUE = re.compile(r"(?:sk-[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9]{20,}|Bearer\s+[A-Za-z0-9._-]{20,})")

def has_forbidden(value: Any) -> bool:
    if isinstance(value, dict):
        return any((str(key) not in SAFE_PRIVACY_KEYS and FORBIDDEN_KEYS.search(str(key))) or has_forbidden(child) for key, child in value.items())
    if isinstance(value, list):
        return any(has_forbidden(child) for child in value)
    return isinstance(value, str) and bool(SECRET_VALUE.search(value))

def validate(record: Any) -> list[str]:
    if not isinstance(record, dict):
        return ["record must be object"]
    if "__parse_error__" in record:
        return [record["__parse_error__"]]
    errors = []
    required = ("schema_version", "closure_run_id", "work_id", "task_type", "tool_id", "model", "contract", "human_outcome", "edit_effort", "time_saved_estimate", "dimensions", "work_pattern", "review", "diminishing_return", "privacy", "final_outcome")
    errors.extend(f"missing: {key}" for key in required if key not in record)
    if errors:
        return errors
    if record["schema_version"] != SCHEMA_VERSION:
        errors.append("invalid: schema_version")
    if record["human_outcome"] not in OUTCOMES:
        errors.append("invalid: human_outcome")
    model = record["model"]
    if not isinstance(model, dict) or not model.get("provider") or not model.get("name"):
        errors.append("invalid: model provider/name must be explicit or not_applicable")
    contract = record["contract"]
    if not isinstance(contract, dict) or not contract.get("version"):
        errors.append("invalid: contract.version")
    edit = record["edit_effort"]
    if not isinstance(edit, dict) or not isinstance(edit.get("categories"), list):
        errors.append("invalid: edit_effort")
    estimate = record["time_saved_estimate"]
    if not isinstance(estimate, dict) or estimate.get("estimate_basis") not in {"measured_local", "human_retrospective", "unknown"}:
        errors.append("invalid: time_saved_estimate.estimate_basis")
    elif estimate.get("minutes") is None and estimate.get("estimate_basis") != "unknown":
        errors.append("fail_closed: missing time estimate must use unknown basis")
    elif estimate.get("minutes") is not None and (estimate.get("estimate_basis") == "unknown" or not estimate.get("evidence_ref")):
        errors.append("fail_closed: quantified time estimate requires basis and evidence_ref")
    dimensions = record["dimensions"]
    if not isinstance(dimensions, dict) or set(dimensions) != set(DIMENSIONS):
        errors.append("invalid: dimensions must contain the eight required fields")
    review = record["review"]
    diminishing = record["diminishing_return"]
    if not isinstance(review, dict) or not isinstance(diminishing, dict):
        errors.append("invalid: review or diminishing_return")
    else:
        if diminishing.get("automatic_stop_allowed") is not False:
            errors.append("fail_closed: automatic stop is never allowed")
        allowed_stop_reasons = {"style_only", "low_probability_edge", "repeated_feedback"}
        reasons = set(diminishing.get("reason_codes", []))
        only_style_rounds = "style_only" not in reasons or review.get("style_only_finding_count", 0) >= review.get("review_round_count", 0)
        if diminishing.get("status") == "stop_candidate" and (review.get("review_round_count", 0) < 1 or review.get("new_material_finding_count", 0) != 0 or not reasons or not reasons.issubset(allowed_stop_reasons) or not only_style_rounds):
            errors.append("fail_closed: stop candidate requires only style/edge/repeated feedback and no new material")
        if review.get("risk_domain") in RISK_DOMAINS and diminishing.get("status") == "stop_candidate" and "human_confirmation_required" not in record.get("final_outcome", {}).get("evidence_refs", []):
            errors.append("fail_closed: high-risk stop candidate requires human_confirmation_required evidence ref")
    privacy = record["privacy"]
    if privacy != {"contains_sensitive_data": False, "prompt_body_stored": False, "external_provider_called": False}:
        errors.append("fail_closed: privacy flags must all be false")
    final = record["final_outcome"]
    if not isinstance(final, dict) or not final.get("evidence_refs") or not final.get("checked_at"):
        errors.append("invalid: final_outcome evidence_refs and checked_at required")
    if has_forbidden(record):
        errors.append("fail_closed: sensitive field name or credential-shaped value")
    return errors

def review_packet(record: dict[str, Any]) -> dict[str, Any]:
    errors = validate(record)
    if errors:
        return {"status": "rejected", "errors": errors, "execution_authorized": False}
    review = record["review"]
    diminishing = record["diminishing_return"]
    high_risk = review["risk_domain"] in RISK_DOMAINS
    stop_candidate = diminishing["status"] == "stop_candidate"
    return {"schema_version": "tool_model_fit.outcome_review_packet.v1", "closure_run_id": record["closure_run_id"], "work_id": record["work_id"], "status": "human_confirmation_required" if high_risk and stop_candidate else ("stop_candidate" if stop_candidate else "continue_review"), "automatic_stop_allowed": False, "execution_authorized": False, "reason_codes": diminishing["reason_codes"], "high_risk_domain": review["risk_domain"] if high_risk else None, "evidence_refs": record["final_outcome"]["evidence_refs"]}

def adapt_call_record(record: dict[str, Any], closure_run_id: str, work_id: str) -> dict[str, Any]:
    model = record.get("model", {})
    performance = record.get("performance", {})
    if record.get("input", {}).get("contains_sensitive_data") is True:
        raise ValueError("fail_closed: cannot adapt sensitive call record")
    if model.get("deployment") in {"external", "hybrid"}:
        raise ValueError("fail_closed: cannot adapt external or hybrid provider call record")
    source_bytes = json.dumps(record, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return {"schema_version": SCHEMA_VERSION, "closure_run_id": closure_run_id, "work_id": work_id, "task_type": record.get("task_type", "unknown"), "tool_id": record.get("tool_id", "unknown"), "model": {"provider": model.get("provider") or "not_applicable", "name": model.get("name") or "not_applicable", "family": None}, "contract": {"version": "call-record.v0.1-overlay", "call_record_hash": "sha256:" + hashlib.sha256(source_bytes).hexdigest(), "receipt_ref": None}, "human_outcome": "no_decision", "edit_effort": {"modification_count": None, "duration_seconds": None, "categories": []}, "time_saved_estimate": {"minutes": None, "estimate_basis": "unknown", "evidence_ref": None}, "dimensions": {name: None for name in DIMENSIONS}, "work_pattern": {"repeated_work": False, "duplicate_output": False, "rework_cause": "unknown"}, "review": {"review_round_count": 0, "new_material_finding_count": 0, "style_only_finding_count": 0, "risk_domain": "none"}, "diminishing_return": {"status": "not_applicable", "reason_codes": [], "automatic_stop_allowed": False}, "privacy": {"contains_sensitive_data": False, "prompt_body_stored": False, "external_provider_called": False}, "final_outcome": {"status": "unknown", "evidence_refs": ["call_record_hash_only"], "checked_at": "1970-01-01T00:00:00Z"}, "promptfoo_observation": {"latencyMs": performance.get("latency_ms"), "tokenUsage": performance.get("token_usage"), "cost": performance.get("cost"), "success": record.get("final_outcome", {}).get("status") == "success"}}
