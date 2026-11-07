#!/usr/bin/env python3
"""Validate a material -> angle -> editorial-goal -> topic candidate decision.

This is a thin, deterministic gate over existing topic observations. It does not
scrape platforms, rank with an alleged platform formula, draft content, or publish.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "schemas" / "topic-angle-decision.v1.schema.json"
SCHEMA_V2 = ROOT / "schemas" / "topic-angle-decision.v2.schema.json"
OBSERVATION_SCHEMA = ROOT / "schemas" / "topic-observation.v1.schema.json"
FIXTURE = ROOT / "fixtures" / "topic-angle-decision-v1" / "synthetic.input.json"
OUTPUT_ROOTS = (ROOT / ".runtime", ROOT / "outputs" / "test-temp", ROOT / "tests" / ".runtime")
VERIFIED_FACT_STATUSES = {"verified_source", "verified_position", "user_confirmed"}
FACT_SOURCE_KINDS = {"official-source", "contract-clause", "user-confirmed", "synthetic-fixture"}
MANIPULATIVE_FLAGS = {
    "fabricated-conflict",
    "outrage-targeting",
    "fear-escalation",
    "unsupported-authority",
    "customer-case-unverified",
}
AUTHORITY = {
    "publication": False,
    "external_send": False,
    "customer_contact": False,
    "crm_write": False,
    "knowledge_base_write": False,
}


class TopicAngleError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TopicAngleError("json_root_invalid", f"expected object: {path}")
    return value


def exact_keys(value: Any, expected: set[str], label: str) -> None:
    if not isinstance(value, dict) or set(value) != expected:
        raise TopicAngleError("field_set_invalid", f"{label} fields do not match the contract")


def resolve_repo_ref(ref: str) -> Path:
    candidate = Path(ref)
    if candidate.is_absolute() or ":" in ref or ref.startswith(("http://", "https://", "file://")):
        raise TopicAngleError("reference_scope_invalid", f"only repository-relative references are accepted: {ref}")
    resolved = (ROOT / candidate).resolve()
    if not resolved.is_relative_to(ROOT.resolve()) or not resolved.is_file():
        raise TopicAngleError("reference_missing", ref)
    return resolved


def validate_json_schema(value: dict[str, Any], schema_path: Path, code: str) -> None:
    errors = sorted(
        Draft202012Validator(load_json(schema_path), format_checker=FormatChecker()).iter_errors(value),
        key=lambda item: list(item.absolute_path),
    )
    if errors:
        first = errors[0]
        location = "/".join(str(part) for part in first.absolute_path) or "$"
        raise TopicAngleError(code, f"{location}: {first.message}")


def validate_source_observations(value: dict[str, Any]) -> None:
    signal_ids: set[str] = set()
    for item in value["source_observations"]:
        path = resolve_repo_ref(item["ref"])
        if file_sha256(path) != item["sha256"]:
            raise TopicAngleError("source_observation_hash_drift", item["ref"])
        observation = load_json(path)
        validate_json_schema(observation, OBSERVATION_SCHEMA, "source_observation_schema_invalid")
        if observation["signal_id"] != item["signal_id"]:
            raise TopicAngleError("source_observation_identity_drift", item["ref"])
        if observation["privacy_status"] != "passed":
            raise TopicAngleError("source_observation_privacy_blocked", item["ref"])
        if item["signal_id"] in signal_ids:
            raise TopicAngleError("duplicate_source_observation", item["signal_id"])
        signal_ids.add(item["signal_id"])


def validate_evidence_registry(value: dict[str, Any]) -> dict[str, dict[str, Any]]:
    registry: dict[str, dict[str, Any]] = {}
    for item in value["evidence_registry"]:
        evidence_id = item["evidence_id"]
        if evidence_id in registry:
            raise TopicAngleError("duplicate_evidence_id", evidence_id)
        path = resolve_repo_ref(item["ref"])
        if file_sha256(path) != item["sha256"]:
            raise TopicAngleError("evidence_hash_drift", item["ref"])
        if item["source_kind"] in {"comment", "public-post", "search-query", "secondary-summary", "topic-observation"} and item["fact_support_eligible"]:
            raise TopicAngleError("discovery_signal_promoted_to_fact", evidence_id)
        if item["fact_support_eligible"]:
            if item["status"] not in VERIFIED_FACT_STATUSES or item["source_kind"] not in FACT_SOURCE_KINDS:
                raise TopicAngleError("fact_evidence_not_verified", evidence_id)
        registry[evidence_id] = item
    return registry


def validate_input(value: dict[str, Any]) -> dict[str, Any]:
    is_v2 = value.get("schema_version") == "topic-angle-decision-input.v2"
    exact_keys(
        value,
        {
            "schema_version", "generated_at", "source_observations", "material", "editorial_goal",
            "evidence_registry", "angle_candidates", "selected_angle_id", "heuristic_policy", "human_review",
        } | ({"framework_decision"} if is_v2 else set()),
        "input",
    )
    if value["schema_version"] not in {"topic-angle-decision-input.v1", "topic-angle-decision-input.v2"}:
        raise TopicAngleError("schema_version_unsupported", str(value["schema_version"]))

    validate_source_observations(value)
    registry = validate_evidence_registry(value)

    material = value["material"]
    if material["source_type"] == "customer-case" and material["case_truth_status"] not in {"user-confirmed-deidentified", "synthetic-only"}:
        raise TopicAngleError("customer_case_unverified", "customer cases require user confirmation and de-identification or must be synthetic")
    if material["source_type"] == "synthetic" and (material["synthetic_only"] is not True or material["case_truth_status"] != "synthetic-only"):
        raise TopicAngleError("synthetic_material_mislabeled", "synthetic material must remain synthetic-only")

    policy = value["heuristic_policy"]
    if policy != {
        "mode": "transparent-advisory-only",
        "fixed_platform_weights_prohibited": True,
        "platform_fact_claim": False,
        "causal_claim_prohibited": True,
    }:
        raise TopicAngleError("heuristic_promoted_to_platform_fact", "reach and novelty assessments are hypotheses, never platform weights")

    candidates = value["angle_candidates"]
    if not 3 <= len(candidates) <= 8:
        raise TopicAngleError("angle_count_invalid", "one material must expose at least three distinct angle candidates")
    by_id = {item["angle_id"]: item for item in candidates}
    if len(by_id) != len(candidates):
        raise TopicAngleError("duplicate_angle_id", "angle ids must be unique")
    proposed = [item for item in candidates if item["selection_status"] == "proposed"]
    no_selection = is_v2 and value["framework_decision"]["outcome"] in {"reframe", "defer"}
    if no_selection and (proposed or value["selected_angle_id"] is not None):
        raise TopicAngleError("selected_angle_mismatch", "reframe/defer must leave all angles unselected")
    if not no_selection and (len(proposed) != 1 or proposed[0]["angle_id"] != value["selected_angle_id"]):
        raise TopicAngleError("selected_angle_mismatch", "exactly one proposed angle must match selected_angle_id")

    selected = proposed[0] if proposed else None
    if selected:
        validate_selected_angle(selected, allow_missing=is_v2 and value["framework_decision"]["outcome"] == "supplement")

    for angle in candidates:
        if angle["compliance_risk"] != angle["risk"]["level"]:
            raise TopicAngleError("compliance_risk_mismatch", angle["angle_id"])
        missing = sorted(set(angle["evidence_refs"]) - set(registry))
        if missing:
            raise TopicAngleError("angle_evidence_ref_missing", ",".join(missing))
        if angle["reach_hypothesis"]["claim_as_platform_fact"] is not False:
            raise TopicAngleError("reach_hypothesis_promoted", angle["angle_id"])
        if angle["selection_status"] == "proposed" and angle["claim_mode"] == "factual-claim":
            for ref in angle["evidence_refs"]:
                evidence = registry[ref]
                if not evidence["fact_support_eligible"] or evidence["status"] not in VERIFIED_FACT_STATUSES:
                    if not (is_v2 and value["framework_decision"]["outcome"] == "supplement"):
                        raise TopicAngleError("factual_angle_lacks_verified_evidence", f"{angle['angle_id']}:{ref}")

    review = value["human_review"]
    confirmation = "decision_confirmed" if is_v2 else "selection_confirmed"
    if review["status"] == "confirmed":
        if review["reviewer"] != "human" or review[confirmation] is not True:
            raise TopicAngleError("human_review_invalid", "confirmed decision requires an explicit human reviewer")
    elif review["reviewer"] != "not-yet" or review[confirmation] is not False:
        raise TopicAngleError("human_review_invalid", "pending review cannot claim confirmation")
    if is_v2:
        validate_framework(value, registry)
    return copy.deepcopy(value)


def validate_selected_angle(selected: dict[str, Any], *, allow_missing: bool = False) -> None:
    if selected["editorial_alignment"] == "off-goal":
        code = "high_reach_off_goal_selected" if selected["reach_hypothesis"]["level"] == "high" else "off_goal_angle_selected"
        raise TopicAngleError(code, "reach potential cannot override the declared editorial goal")
    if selected["evidence_readiness"] == "blocked" and not allow_missing:
        raise TopicAngleError("selected_angle_evidence_blocked", "an angle with blocked evidence readiness cannot proceed to human review")
    if selected["hook_hypothesis"]["support_status"] == "unsupported" and not allow_missing:
        raise TopicAngleError("unsupported_hook_selected", "contrast or conflict in the opening must be supported by the body or evidence")
    if set(selected["risk"]["flags"]) & MANIPULATIVE_FLAGS:
        raise TopicAngleError("manipulative_or_unverified_angle", "fabricated conflict, fear, outrage, false authority, and unverified cases are prohibited")



def validate_framework(value: dict[str, Any], registry: dict[str, Any]) -> None:
    decision = value["framework_decision"]
    current = decision["current_artifact"]
    if file_sha256(resolve_repo_ref(current["ref"])) != current["sha256"]:
        raise TopicAngleError("framework_material_drift", current["ref"])
    assessed = {row["angle_id"]: row for row in decision["assessments"]}
    if len(assessed) != len(decision["assessments"]) or set(assessed) != {a["angle_id"] for a in value["angle_candidates"]}:
        raise TopicAngleError("framework_comparison_incomplete", "every candidate needs its own audience/promise/business/cost assessment")
    for row in decision["assessments"]:
        if not set(row["evidence_refs"]) <= set(registry):
            raise TopicAngleError("framework_evidence_missing", row["angle_id"])
    if not set(decision["planned_changes"]) <= set(decision["allowed_changes"]):
        raise TopicAngleError("framework_scope_exceeded", "planned changes exceed the stated production scope")
    if decision["rewrite_scope"] != "none" and "revise-body" not in decision["planned_changes"]:
        raise TopicAngleError("framework_scope_exceeded", "rewriting requires a permitted body revision")
    if decision["business_mode"] == "known" and (not decision["offer"] or not decision["buyer"]):
        raise TopicAngleError("business_context_missing", "known offer and buyer must be concrete")
    if value["editorial_goal"]["primary_goal"] == "consultation" and decision["business_mode"] != "known" and decision["outcome"] == "continue":
        raise TopicAngleError("business_context_missing", "a consultation goal requires a known offer and intended buyer")
    selected = assessed.get(value["selected_angle_id"])
    if decision["outcome"] == "continue":
        angle = next(a for a in value["angle_candidates"] if a["angle_id"] == value["selected_angle_id"])
        if decision["missing_material"] or selected["material_support"] != "sufficient" or selected["worth_cost"] != "yes" or angle["evidence_readiness"] != "ready-for-framing":
            raise TopicAngleError("framework_not_ready", "continue needs sufficient material and an explained worthwhile cost")
        if selected["business_fit"] == "mismatch" or (decision["business_mode"] == "known" and selected["business_fit"] not in {"matched", "indirect"}):
            raise TopicAngleError("framework_business_mismatch", "reach alone cannot override audience/business mismatch")
        if decision["rewrite_scope"] == "full":
            raise TopicAngleError("framework_rewrite_required", "a full rewrite must return through reframe and reassessment")
    if decision["outcome"] == "supplement" and not decision["missing_material"]:
        raise TopicAngleError("missing_material_unspecified", "specify what evidence/research/recording is needed")
    if decision["outcome"] == "reframe" and decision["rewrite_scope"] == "none":
        raise TopicAngleError("rewrite_scope_missing", "state whether reframing changes part or all of the draft")


def continuation(value: dict[str, Any], *, stage: str = "draft") -> dict[str, Any]:
    """Return an editorial route, never execution/publication authority."""
    validate_receipt(value)
    if value["schema_version"] != "topic-angle-decision.v2":
        raise TopicAngleError("legacy_framework_review_required", "v1 remains readable but does not prove the new framework judgment")
    decision = value["framework_decision"]
    outcome = decision["outcome"]
    allowed = (outcome == "continue" or (outcome == "supplement" and stage == "research")) and value["human_review"]["status"] == "confirmed"
    return {"status": "ready-for-existing-gates" if allowed else "return-required", "outcome": outcome,
            "may_continue": allowed, "next_action": decision["next_action"], "resume_condition": decision["resume_condition"],
            "human_review": value["human_review"]["status"], "authority": copy.deepcopy(AUTHORITY)}


def create_receipt_from_value(raw_value: dict[str, Any]) -> dict[str, Any]:
    value = validate_input(raw_value)
    payload = copy.deepcopy(value)
    payload["schema_version"] = value["schema_version"].replace("-input", "")
    payload["decision_id"] = "angle-decision-" + canonical_sha256(value)[:24]
    payload["artifact_status"] = "candidate-only"
    payload["publication_boundary"] = "manual-only"
    payload["authority"] = copy.deepcopy(AUTHORITY)
    payload["receipt_payload_sha256"] = canonical_sha256(payload)
    validate_json_schema(payload, SCHEMA_V2 if payload["schema_version"].endswith(".v2") else SCHEMA, "receipt_schema_invalid")
    return payload


def create_receipt(path: Path) -> dict[str, Any]:
    return create_receipt_from_value(load_json(path))


def validate_receipt(value: dict[str, Any]) -> None:
    is_v2 = value.get("schema_version") == "topic-angle-decision.v2"
    validate_json_schema(value, SCHEMA_V2 if is_v2 else SCHEMA, "receipt_schema_invalid")
    unsigned = copy.deepcopy(value)
    digest = unsigned.pop("receipt_payload_sha256")
    if canonical_sha256(unsigned) != digest:
        raise TopicAngleError("receipt_hash_drift", "decision receipt changed after creation")
    restored = copy.deepcopy(value)
    for key in ("decision_id", "artifact_status", "publication_boundary", "authority", "receipt_payload_sha256"):
        restored.pop(key)
    restored["schema_version"] = "topic-angle-decision-input.v2" if is_v2 else "topic-angle-decision-input.v1"
    validate_input(restored)


def write_receipt(path: Path, value: dict[str, Any]) -> str:
    resolved = path.resolve()
    if not any(resolved.is_relative_to(root.resolve()) for root in OUTPUT_ROOTS):
        raise TopicAngleError("output_path_prohibited", "output must stay under .runtime, tests/.runtime, or outputs/test-temp")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n")
    return "created"


def check() -> dict[str, Any]:
    first = create_receipt(FIXTURE)
    second = create_receipt(FIXTURE)
    if canonical_bytes(first) != canonical_bytes(second):
        raise TopicAngleError("non_deterministic", "fixture output is not byte-stable")
    validate_receipt(first)
    current = create_receipt(ROOT / "fixtures/topic-angle-decision-v2/synthetic.input.json")
    validate_receipt(current)
    if canonical_bytes(current) != canonical_bytes(create_receipt(ROOT / "fixtures/topic-angle-decision-v2/synthetic.input.json")):
        raise TopicAngleError("non_deterministic", "v2 fixture changed across identical inputs")
    return {"status": "passed", "idempotency": "byte-stable", "decision_id": first["decision_id"],
            "current_version": "topic-angle-decision.v2", "pending_review_blocks_draft": not continuation(current)["may_continue"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create")
    create.add_argument("--input", type=Path, required=True)
    create.add_argument("--output", type=Path, required=True)
    validate = sub.add_parser("validate")
    validate.add_argument("--receipt", type=Path, required=True)
    next_step = sub.add_parser("next-step")
    next_step.add_argument("--receipt", type=Path, required=True)
    next_step.add_argument("--stage", choices=["draft", "research"], default="draft")
    sub.add_parser("check")
    args = parser.parse_args()
    try:
        if args.command == "create":
            receipt = create_receipt(args.input)
            print(json.dumps({"status": write_receipt(args.output, receipt), "decision_id": receipt["decision_id"]}, ensure_ascii=False))
        elif args.command == "next-step":
            result = continuation(load_json(args.receipt), stage=args.stage)
            print(json.dumps(result, ensure_ascii=False))
            return 0 if result["may_continue"] else 2
        elif args.command == "validate":
            validate_receipt(load_json(args.receipt))
            print(json.dumps({"status": "passed"}, ensure_ascii=False))
        else:
            print(json.dumps(check(), ensure_ascii=False, sort_keys=True))
        return 0
    except TopicAngleError as error:
        print(json.dumps({"status": "blocked", "code": error.code, "message": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2
    except Exception as error:  # fail closed on malformed JSON, schema, or filesystem input
        print(json.dumps({"status": "blocked", "code": "validation_failed", "message": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
