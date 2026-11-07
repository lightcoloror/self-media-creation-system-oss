#!/usr/bin/env python3
"""Thin, deterministic gate for translating serious content for broad audiences.

The gate binds a frozen body to a reviewed audience-entry plan and post-draft
safety assessment.  It does not write copy, call a model, approve compliance,
or authorize publication.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "schemas" / "serious-content-translation-review.v1.schema.json"
FIXTURE = ROOT / "fixtures" / "serious-content-translation-v1" / "synthetic.input.json"
OUTPUT_ROOTS = (
    ROOT / ".runtime" / "serious-content-translation",
    ROOT / "tests" / ".runtime" / "serious-content-translation",
)
AUTHORITY = {
    "publish_authorized": False,
    "execution_authorized": False,
    "external_send_authorized": False,
}
SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
ABSOLUTE_PATH_RE = re.compile(r"(?:[A-Za-z]:[\\/]|^[/\\])")


class TranslationGateError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def sha256_text_file(path: Path) -> str:
    """Hash UTF-8 text after normalizing platform line endings to LF."""
    normalized = path.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise TranslationGateError("artifact_missing", str(path)) from error
    except json.JSONDecodeError as error:
        raise TranslationGateError("invalid_json", str(error)) from error
    if not isinstance(value, dict):
        raise TranslationGateError("invalid_shape", "JSON root must be an object")
    return value


def exact_keys(value: Any, expected: set[str], label: str) -> None:
    if not isinstance(value, dict):
        raise TranslationGateError("invalid_shape", f"{label} must be an object")
    if set(value) != expected:
        raise TranslationGateError("invalid_shape", f"{label} fields must be {sorted(expected)}")


def parse_time(value: Any, label: str) -> datetime:
    if not isinstance(value, str):
        raise TranslationGateError("invalid_datetime", f"{label} must be an ISO-8601 string")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise TranslationGateError("invalid_datetime", f"{label}: {value}") from error
    if parsed.tzinfo is None:
        raise TranslationGateError("invalid_datetime", f"{label} must include timezone")
    return parsed


def resolve_ref(ref: Any) -> Path:
    if not isinstance(ref, str) or not ref or ABSOLUTE_PATH_RE.search(ref) or "://" in ref:
        raise TranslationGateError("unsafe_body_ref", "body_ref must be repository-relative")
    raw = Path(ref)
    if raw.is_absolute() or ".." in raw.parts:
        raise TranslationGateError("unsafe_body_ref", "body_ref leaves repository")
    path = (ROOT / raw).resolve()
    try:
        path.relative_to(ROOT.resolve())
    except ValueError as error:
        raise TranslationGateError("unsafe_body_ref", "body_ref leaves repository") from error
    if not path.is_file():
        raise TranslationGateError("artifact_missing", ref)
    return path


def validate_input(value: dict[str, Any]) -> dict[str, Any]:
    exact_keys(
        value,
        {"schema_version", "generated_at", "content_id", "risk_class", "sensitivity_profile", "content_nature", "body_binding", "precreative_gate", "translation_plan", "postcreative_gate"},
        "input",
    )
    if value["schema_version"] != "serious-content-translation-review-input.v1":
        raise TranslationGateError("schema_version_unsupported", str(value["schema_version"]))
    if value["risk_class"] not in {"ordinary", "insurance-health", "high-risk"}:
        raise TranslationGateError("risk_class_invalid", str(value["risk_class"]))
    sensitivity_profile = value["sensitivity_profile"]
    sensitivity_profiles = {
        "ordinary", "professional-sensitive", "medical-sensitive",
        "affected-person-severe-illness", "customer-loss", "privacy-high-risk",
        "compound-high-sensitivity",
    }
    if sensitivity_profile not in sensitivity_profiles:
        raise TranslationGateError("sensitivity_profile_invalid", str(sensitivity_profile))
    if value["risk_class"] == "ordinary" and sensitivity_profile not in {"ordinary", "professional-sensitive"}:
        raise TranslationGateError("risk_sensitivity_mismatch", "ordinary risk cannot carry a high-sensitivity profile")
    if value["risk_class"] == "high-risk" and sensitivity_profile == "ordinary":
        raise TranslationGateError("risk_sensitivity_mismatch", "high-risk content cannot declare ordinary sensitivity")
    if value["content_nature"] not in {"education", "opinion", "case-review", "product-marketing", "individual-advice", "medical-insurance-cross"}:
        raise TranslationGateError("content_nature_invalid", str(value["content_nature"]))

    body_binding = value["body_binding"]
    exact_keys(body_binding, {"body_ref", "body_sha256"}, "body_binding")
    body = resolve_ref(body_binding["body_ref"])
    if not isinstance(body_binding["body_sha256"], str) or not SHA256_RE.fullmatch(body_binding["body_sha256"]):
        raise TranslationGateError("body_hash_invalid", "body_sha256 must be lowercase SHA-256")
    if sha256_text_file(body) != body_binding["body_sha256"]:
        raise TranslationGateError("body_hash_drift", "frozen body no longer matches reviewed hash")

    pre = value["precreative_gate"]
    exact_keys(pre, {"audience_decision", "evidence_spine_status", "privacy_status", "risk_boundary", "reviewed_at", "decision"}, "precreative_gate")
    if pre["decision"] != "passed" or pre["evidence_spine_status"] != "verified":
        raise TranslationGateError("precreative_gate_blocked", "evidence spine must be verified before creative work")
    if pre["privacy_status"] not in {"cleared", "not-applicable"}:
        raise TranslationGateError("privacy_gate_blocked", "privacy must be cleared before creative work")
    pre_time = parse_time(pre["reviewed_at"], "precreative_gate.reviewed_at")

    plan = value["translation_plan"]
    exact_keys(
        plan,
        {
            "content_role", "real_tension", "viewer_stakes", "central_judgment",
            "explanation_budget", "life_relevance", "protagonist_goal_or_reader_task",
            "scene_or_dialogue_anchor", "completion_question", "completion_payoff",
            "takeaway_or_next_use", "target_action", "service_action",
            "service_action_effect", "entry_mechanism", "humor_level", "humor_target",
            "sensitive_humor_exception",
            "information_advances", "story_reveal_contract", "analogy",
        },
        "translation_plan",
    )
    if plan["content_role"] not in {"growth", "trust", "tool", "professional"}:
        raise TranslationGateError("content_role_invalid", str(plan["content_role"]))
    if plan["content_role"] in {"growth", "trust"} and not (isinstance(plan["real_tension"], str) and plan["real_tension"].strip()):
        raise TranslationGateError("real_tension_missing", "growth and trust content require an evidence-backed tension")
    if plan["real_tension"] is not None and not (isinstance(plan["real_tension"], str) and plan["real_tension"].strip()):
        raise TranslationGateError("real_tension_invalid", "real_tension must be null or a non-empty string")
    for key in (
        "viewer_stakes", "central_judgment", "life_relevance",
        "protagonist_goal_or_reader_task", "scene_or_dialogue_anchor",
        "completion_question", "completion_payoff", "takeaway_or_next_use",
    ):
        if not isinstance(plan[key], str) or not plan[key].strip():
            raise TranslationGateError("attention_plan_missing", key)
    if plan["completion_question"].strip().casefold() == plan["completion_payoff"].strip().casefold():
        raise TranslationGateError(
            "completion_loop_missing",
            "the payoff must advance or answer the question opened for the viewer",
        )
    if plan["target_action"] not in {"understand", "save", "share", "discuss", "consult", "convert"}:
        raise TranslationGateError("target_action_invalid", str(plan["target_action"]))
    service_action = plan["service_action"]
    service_effect = plan["service_action_effect"]
    for key, item in (("service_action", service_action), ("service_action_effect", service_effect)):
        if item is not None and (not isinstance(item, str) or not item.strip()):
            raise TranslationGateError("service_causality_invalid", key)
    if (service_action is None) != (service_effect is None):
        raise TranslationGateError(
            "service_causality_incomplete",
            "service action and its immediate effect must be recorded together",
        )
    if plan["target_action"] in {"consult", "convert"} and service_action is None:
        raise TranslationGateError(
            "acquisition_service_causality_missing",
            "consultation or conversion content must show a concrete service action and its effect",
        )
    budget = plan["explanation_budget"]
    exact_keys(budget, {"level", "max_professional_concepts", "max_boundaries"}, "translation_plan.explanation_budget")
    limits = {"short": 2, "medium": 3, "deep": 5}
    if budget["level"] not in limits:
        raise TranslationGateError("explanation_budget_invalid", str(budget["level"]))
    if any(not isinstance(budget[key], int) or not 1 <= budget[key] <= limits[budget["level"]] for key in ("max_professional_concepts", "max_boundaries")):
        raise TranslationGateError("explanation_budget_exceeded", "declared explanation exceeds the selected budget")
    if plan["entry_mechanism"] == "story-suspense":
        raise TranslationGateError(
            "legacy_story_suspense_requires_migration",
            "use result-preview-story-reveal with a two-second watch reason",
        )
    if plan["entry_mechanism"] not in {"life-problem", "choice-conflict", "counterintuitive-result", "result-preview-story-reveal", "role-dialogue", "prop-demo", "light-humor", "search-intent-direct"}:
        raise TranslationGateError("entry_mechanism_invalid", str(plan["entry_mechanism"]))
    if plan["humor_level"] not in {"none", "light", "moderate", "experimental"}:
        raise TranslationGateError("humor_level_invalid", str(plan["humor_level"]))
    if plan["humor_target"] not in {"none", "self", "jargon", "mechanism", "common-reasoning-error"}:
        raise TranslationGateError("humor_target_unsafe", str(plan["humor_target"]))
    humor_exception = plan["sensitive_humor_exception"]
    if humor_exception is not None:
        exact_keys(
            humor_exception,
            {"reason", "affected_person_targeted", "human_approved"},
            "translation_plan.sensitive_humor_exception",
        )
        if not isinstance(humor_exception["reason"], str) or not humor_exception["reason"].strip():
            raise TranslationGateError("sensitive_humor_exception_invalid", "reason is required")
        if humor_exception["affected_person_targeted"] is not False or humor_exception["human_approved"] is not True:
            raise TranslationGateError("sensitive_humor_exception_invalid", "the affected person must not be targeted and human approval is required")
    advances = plan["information_advances"]
    if not isinstance(advances, list) or len(advances) < 2 or not all(isinstance(item, str) and item.strip() for item in advances):
        raise TranslationGateError("information_progression_missing", "at least two information advances are required")
    story = plan["story_reveal_contract"]
    if plan["entry_mechanism"] == "result-preview-story-reveal":
        if not isinstance(story, dict):
            raise TranslationGateError("story_reveal_contract_missing", "the story route requires a two-second opening contract")
        exact_keys(story, {"opening_watch_reason", "central_judgment_timing", "post_story_explanation", "empty_suspense_prohibited"}, "translation_plan.story_reveal_contract")
        opening = story["opening_watch_reason"]
        exact_keys(opening, {"type", "text", "target_seconds", "central_answer_disclosed", "body_fulfills_opening"}, "story_reveal_contract.opening_watch_reason")
        if opening["type"] not in {"result-glimpse", "concrete-number", "counterintuitive-change", "choice-conflict", "key-question", "decisive-scene"}:
            raise TranslationGateError("opening_watch_reason_invalid", str(opening["type"]))
        if not isinstance(opening["text"], str) or not opening["text"].strip():
            raise TranslationGateError("opening_watch_reason_missing", "the opening must contain a concrete reason to keep watching")
        if not isinstance(opening["target_seconds"], (int, float)) or not 0.5 <= opening["target_seconds"] <= 2:
            raise TranslationGateError("opening_too_late", "the watch reason must land within two seconds")
        if opening["central_answer_disclosed"] is not False:
            raise TranslationGateError("central_answer_revealed_too_early", "preview the stakes, not the whole answer")
        if opening["body_fulfills_opening"] is not True:
            raise TranslationGateError("opening_body_mismatch", "the story must fulfill the opening promise")
        if story["central_judgment_timing"] != "near-story-close":
            raise TranslationGateError("story_reveal_timing_invalid", "the central judgment should emerge near the story close")
        explanation = story["post_story_explanation"]
        exact_keys(explanation, {"sentence_count", "boundary_included"}, "story_reveal_contract.post_story_explanation")
        if not isinstance(explanation["sentence_count"], int) or not 2 <= explanation["sentence_count"] <= 4:
            raise TranslationGateError("post_story_explanation_invalid", "use two to four explanation sentences")
        if explanation["boundary_included"] is not True:
            raise TranslationGateError("post_story_boundary_missing", "the post-story explanation must retain the necessary boundary")
        if story["empty_suspense_prohibited"] is not True:
            raise TranslationGateError("empty_suspense_prohibited", "do not ask viewers to wait without an immediate watch reason")
        if len(advances) < 3:
            raise TranslationGateError(
                "story_progression_too_short",
                "a short story reveal needs at least three distinct information advances",
            )
    elif story is not None:
        raise TranslationGateError("story_reveal_contract_unexpected", "story_reveal_contract is only for result-preview-story-reveal")
    analogy = plan["analogy"]
    if analogy is not None:
        exact_keys(analogy, {"metaphor", "mapping", "boundary"}, "translation_plan.analogy")
        if not all(isinstance(analogy[key], str) and analogy[key].strip() for key in analogy):
            raise TranslationGateError("analogy_boundary_missing", "metaphor, mapping and boundary are all required")
    if value["risk_class"] == "high-risk" and plan["humor_level"] not in {"none", "light"}:
        raise TranslationGateError("high_risk_humor_too_strong", "high-risk content permits none or light humor only")
    if value["risk_class"] == "insurance-health" and plan["humor_level"] == "experimental":
        raise TranslationGateError("insurance_health_humor_too_strong", "experimental humor is not allowed")
    near_zero_profiles = {
        "affected-person-severe-illness", "customer-loss", "privacy-high-risk",
        "compound-high-sensitivity",
    }
    if sensitivity_profile in near_zero_profiles:
        if plan["humor_level"] == "none":
            if humor_exception is not None:
                raise TranslationGateError("sensitive_humor_exception_unexpected", "no exception is needed when humor is absent")
        elif plan["humor_level"] == "light" and humor_exception is not None:
            pass
        else:
            raise TranslationGateError(
                "sensitive_profile_humor_requires_exception",
                "severe illness, customer loss, and privacy-high-risk content defaults to no humor; light humor requires an explicit human-approved exception",
            )
    elif humor_exception is not None:
        raise TranslationGateError("sensitive_humor_exception_unexpected", "exception is only valid for a near-zero-humor sensitivity profile")
    if (plan["humor_level"] == "none") != (plan["humor_target"] == "none"):
        raise TranslationGateError("humor_level_target_mismatch", "none humor and none target must be declared together")

    post = value["postcreative_gate"]
    exact_keys(post, {"reviewed_at", "decision", "key_boundary_in_body", "source_detail_available_in_package", "safe_action_present", "individual_case_generalized", "misinterpretation_scenarios", "scores", "attention_review", "fun_integrity_review"}, "postcreative_gate")
    if parse_time(post["reviewed_at"], "postcreative_gate.reviewed_at") < pre_time:
        raise TranslationGateError("gate_order_invalid", "postcreative review cannot precede precreative review")
    if post["decision"] != "passed":
        raise TranslationGateError("postcreative_gate_blocked", "postcreative review must pass")
    for key in ("key_boundary_in_body", "source_detail_available_in_package", "safe_action_present"):
        if post[key] is not True:
            raise TranslationGateError("postcreative_requirement_missing", key)
    if post["individual_case_generalized"] is not False:
        raise TranslationGateError("individual_case_generalized", "an individual result cannot become a general promise")
    if not isinstance(post["misinterpretation_scenarios"], list) or not post["misinterpretation_scenarios"]:
        raise TranslationGateError("misinterpretation_review_missing", "at least one likely misinterpretation is required")
    scores = post["scores"]
    exact_keys(scores, {"evidence", "boundary", "safety"}, "postcreative_gate.scores")
    if not all(isinstance(scores[key], int) and 1 <= scores[key] <= 5 for key in scores):
        raise TranslationGateError("score_invalid", "scores must be integers from 1 to 5")
    if value["risk_class"] in {"insurance-health", "high-risk"}:
        failed = [key for key in ("evidence", "boundary", "safety") if scores[key] < 4]
        if failed:
            raise TranslationGateError("high_risk_hard_gate_failed", ",".join(failed))
    attention = post["attention_review"]
    attention_keys = {
        "decision",
        "opening_watch_reason_present",
        "audience_relevance_immediate",
        "protagonist_goal_or_reader_task_visible",
        "concrete_stakes_visible",
        "scene_or_dialogue_anchor_preserved",
        "tension_or_direct_utility_present",
        "information_progression_present",
        "completion_payoff_present",
        "takeaway_or_next_use_present",
        "service_causality_fit",
        "central_judgment_clear",
        "explanation_within_budget",
        "title_cover_opening_aligned",
    }
    exact_keys(attention, attention_keys, "postcreative_gate.attention_review")
    if attention["decision"] != "passed" or any(attention[key] is not True for key in attention_keys - {"decision"}):
        raise TranslationGateError("attention_review_revision_required", "attention may trigger revision but cannot offset an integrity failure")
    fun = post["fun_integrity_review"]
    exact_keys(
        fun,
        {"fun_present", "role", "helps_answer_core_question", "humor_target_safe", "core_value_survives_without_fun", "primary_memory_target"},
        "postcreative_gate.fun_integrity_review",
    )
    if not isinstance(fun["fun_present"], bool):
        raise TranslationGateError("fun_review_invalid", "fun_present must be boolean")
    if fun["role"] not in {"none", "related", "decorative", "misleading"}:
        raise TranslationGateError("fun_role_invalid", str(fun["role"]))
    if fun["role"] in {"decorative", "misleading"}:
        raise TranslationGateError("fun_role_blocked", "decorative or misleading fun must be removed or redesigned")
    if fun["role"] == "none":
        if fun["fun_present"] is not False or fun["helps_answer_core_question"] is not None:
            raise TranslationGateError("fun_review_inconsistent", "no-fun content must use fun_present=false and helps_answer_core_question=null")
    else:
        if fun["fun_present"] is not True or fun["helps_answer_core_question"] is not True:
            raise TranslationGateError("fun_not_serving_content", "related fun must directly help answer the core question")
    if plan["humor_level"] != "none" and fun["fun_present"] is not True:
        raise TranslationGateError("fun_review_inconsistent", "declared humor must be reviewed as present")
    if fun["humor_target_safe"] is not True:
        raise TranslationGateError("humor_target_unsafe", "the finished draft targets an unsafe person or group")
    if fun["core_value_survives_without_fun"] is not True:
        raise TranslationGateError("core_value_depends_on_fun", "facts, answer, and service value must survive removal of the fun device")
    if fun["primary_memory_target"] not in {"central-judgment", "action", "mechanism", "gag"}:
        raise TranslationGateError("fun_memory_target_invalid", str(fun["primary_memory_target"]))
    if fun["primary_memory_target"] == "gag":
        raise TranslationGateError("gag_over_core_judgment", "the intended memory must be the judgment, action, or mechanism rather than the gag")
    return copy.deepcopy(value)


def create_receipt(input_path: Path) -> dict[str, Any]:
    value = validate_input(load_json(input_path))
    payload = {
        "schema_version": "serious-content-translation-review.v1",
        "review_id": "serious-translation-" + canonical_sha256(value)[:24],
        "generated_at": value["generated_at"],
        "artifact_status": "candidate-only",
        "publication_boundary": "manual-only",
        "content_id": value["content_id"],
        "risk_class": value["risk_class"],
        "sensitivity_profile": value["sensitivity_profile"],
        "content_nature": value["content_nature"],
        "body_binding": value["body_binding"],
        "precreative_gate": value["precreative_gate"],
        "translation_plan": value["translation_plan"],
        "postcreative_gate": value["postcreative_gate"],
        "review_dimensions": {
            "integrity_gate_status": "passed",
            "attention_gate_status": "passed",
            "aggregation_policy": "independent-no-averaging",
        },
        "gate_status": "passed",
        "release_status": "review-required",
        "next_gate": "author-review" if value["risk_class"] == "ordinary" else "author-plus-subject-matter-check",
        "authority": AUTHORITY,
    }
    payload["receipt_payload_sha256"] = canonical_sha256(payload)
    Draft202012Validator(load_json(SCHEMA), format_checker=FormatChecker()).validate(payload)
    return payload


def validate_receipt(value: dict[str, Any]) -> None:
    Draft202012Validator(load_json(SCHEMA), format_checker=FormatChecker()).validate(value)
    unsigned = copy.deepcopy(value)
    digest = unsigned.pop("receipt_payload_sha256")
    if canonical_sha256(unsigned) != digest:
        raise TranslationGateError("receipt_hash_drift", "receipt payload changed after review")
    body = resolve_ref(value["body_binding"]["body_ref"])
    if sha256_text_file(body) != value["body_binding"]["body_sha256"]:
        raise TranslationGateError("body_hash_drift", "frozen body changed after review")


def write_receipt(path: Path, value: dict[str, Any]) -> str:
    resolved = path.resolve()
    if not any(resolved.is_relative_to(root.resolve()) for root in OUTPUT_ROOTS):
        raise TranslationGateError("output_path_prohibited", "output must stay under a gate runtime root")
    encoded = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as handle:
            handle.write(encoded)
        return "created"
    except FileExistsError:
        if path.read_bytes() != encoded:
            raise TranslationGateError("output_conflict", "existing output differs")
        return "already-identical"


def check() -> dict[str, Any]:
    first = create_receipt(FIXTURE)
    second = create_receipt(FIXTURE)
    if canonical_bytes(first) != canonical_bytes(second):
        raise TranslationGateError("non_deterministic", "fixture output is not stable")
    validate_receipt(first)
    return {"status": "passed", "idempotency": "byte-stable", "review_id": first["review_id"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create")
    create.add_argument("--input", type=Path, required=True)
    create.add_argument("--output", type=Path, required=True)
    verify = sub.add_parser("validate")
    verify.add_argument("--receipt", type=Path, required=True)
    sub.add_parser("check")
    args = parser.parse_args()
    try:
        if args.command == "create":
            receipt = create_receipt(args.input)
            status = write_receipt(args.output, receipt)
            print(json.dumps({"status": status, "review_id": receipt["review_id"]}, ensure_ascii=False))
        elif args.command == "validate":
            validate_receipt(load_json(args.receipt))
            print(json.dumps({"status": "passed"}))
        else:
            print(json.dumps(check(), ensure_ascii=False, sort_keys=True))
        return 0
    except (TranslationGateError, Exception) as error:
        code = error.code if isinstance(error, TranslationGateError) else "validation_failed"
        print(json.dumps({"status": "blocked", "code": code, "message": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
