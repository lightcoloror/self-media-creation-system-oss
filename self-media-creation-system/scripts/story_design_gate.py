#!/usr/bin/env python3
"""Validate evidence-bound story structure and emotional resonance before drafting.

This gate is conditional: direct answers and checklists do not need a story card.
It does not generate copy, infer private feelings, approve compliance, or authorize
publication.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "schemas" / "story-design-card.v1.schema.json"
FIXTURE = ROOT / "fixtures" / "story-design-card-v1" / "synthetic.input.json"
TIMING_PROFILE = ROOT / "config" / "short-video-timing-profile.v1.json"
OUTPUT_ROOTS = (
    ROOT / ".runtime" / "story-design",
    ROOT / "tests" / ".runtime" / "story-design",
)
AUTHORITY = {
    "publish_authorized": False,
    "execution_authorized": False,
    "external_send_authorized": False,
}
FORMAT_TURN_BOUNDS = {
    "moments-short-text": (1, 3),
    "graphic-note": (1, 4),
    "short-video-narration": (1, 3),
    "demo-video": (1, 4),
    "interview-video": (1, 4),
    "long-video": (1, 6),
    "live": (1, 4),
    "longform-article": (1, 6),
}
ABSOLUTE_PATH_RE = re.compile(r"(?:[A-Za-z]:[\\/]|^[/\\])")


class StoryDesignError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def text_sha256(path: Path) -> str:
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise StoryDesignError("artifact_missing", str(path)) from error
    except json.JSONDecodeError as error:
        raise StoryDesignError("invalid_json", str(error)) from error
    if not isinstance(value, dict):
        raise StoryDesignError("invalid_shape", "JSON root must be an object")
    return value


def exact_keys(value: Any, expected: set[str], label: str) -> None:
    if not isinstance(value, dict) or set(value) != expected:
        raise StoryDesignError("invalid_shape", f"{label} fields must be {sorted(expected)}")


def timing_profile_thresholds() -> dict[str, Any]:
    """Load the same operating hypothesis used by measured timing evidence."""

    profile = load_json(TIMING_PROFILE)
    exact_keys(
        profile,
        {"schema_version", "profile_id", "status", "applies_to", "thresholds", "interpretation"},
        "short_video_timing_profile",
    )
    if (
        profile["schema_version"] != "short-video-timing-profile.v1"
        or profile["profile_id"] != "current-operating-hypothesis"
        or profile["status"] != "operating-hypothesis-not-platform-fact"
        or profile["applies_to"] != "short-video-narration"
    ):
        raise StoryDesignError("timing_profile_invalid", "short-video profile identity or epistemic status drifted")
    thresholds = profile["thresholds"]
    exact_keys(
        thresholds,
        {
            "audience_stake_max_seconds", "reason_to_continue_max_seconds",
            "first_information_advance_max_seconds", "information_advance_gap_max_seconds",
            "main_payoff_max_completion_ratio", "minimum_information_advances",
        },
        "short_video_timing_profile.thresholds",
    )
    if profile["interpretation"].get("thresholds_are_platform_guarantees") is not False:
        raise StoryDesignError("timing_heuristic_promoted", "timing thresholds are not platform guarantees")
    return thresholds


def resolve_ref(ref: Any) -> Path:
    if not isinstance(ref, str) or not ref or ABSOLUTE_PATH_RE.search(ref) or "://" in ref:
        raise StoryDesignError("unsafe_fact_ref", "fact_card_ref must be repository-relative")
    raw = Path(ref)
    if raw.is_absolute() or ".." in raw.parts:
        raise StoryDesignError("unsafe_fact_ref", "fact_card_ref leaves repository")
    path = (ROOT / raw).resolve()
    try:
        path.relative_to(ROOT.resolve())
    except ValueError as error:
        raise StoryDesignError("unsafe_fact_ref", "fact_card_ref leaves repository") from error
    if not path.is_file():
        raise StoryDesignError("artifact_missing", ref)
    return path


def all_fact_refs(value: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    refs.extend(value["story_source"]["fact_refs"])
    refs.extend(value["protagonist"]["goal_fact_refs"])
    refs.extend(value["protagonist"]["internal_state_fact_refs"])
    for key in (
        "scene_anchor", "inciting_incident", "expectation_gap", "attempt_and_feedback",
        "choice_under_pressure", "climax", "resolution",
    ):
        refs.extend(value[key]["fact_refs"])
    for item in value["pressure"] + value["turning_points"]:
        refs.extend(item["fact_refs"])
    for item in value["emotional_design"]["emotion_beats"]:
        refs.extend(item["fact_refs"])
    return refs


def build_diagnostic_warnings(value: dict[str, Any]) -> list[str]:
    """Return advisory craft findings without turning flexible heuristics into hard gates."""
    warnings: list[str] = []
    diagnostics = value["editorial_diagnostics"]
    if diagnostics["causal_link_status"] != "causal-order-clear":
        warnings.append("causal-link-needs-editorial-review")
    if diagnostics["causal_trim_status"] != "passed":
        warnings.append("causal-trim-review-not-passed")
    for dimension, status in diagnostics["stickiness"].items():
        if status == "needs-review":
            warnings.append(f"stickiness-{dimension}-needs-review")
    strategy = value["production_strategy"]
    if strategy["platform_specific_variants"] == "deferred-capacity":
        warnings.append("platform-specific-variants-deferred-capacity")
    if strategy["single_variable_experiment"] == "deferred-capacity":
        warnings.append("single-variable-experiment-deferred-capacity")
    if value["continuity_value"]["surface_mode"] == "not-surfaced-this-item":
        warnings.append("continuity-value-not-surfaced-this-item")
    return sorted(warnings)


def validate_input(value: dict[str, Any]) -> dict[str, Any]:
    expected = {
        "schema_version", "generated_at", "content_id", "risk_class", "structure_route",
        "fact_binding", "story_source", "story_category", "story_purpose", "format_design",
        "production_strategy", "timing_design", "continuity_value",
        "protagonist", "audience_bridge", "scene_anchor", "inciting_incident",
        "expectation_gap", "attempt_and_feedback", "pressure", "choice_under_pressure",
        "turning_points", "climax", "resolution", "emotional_design", "explanation_bridge",
        "editorial_diagnostics", "publication_learning_plan", "review",
    }
    exact_keys(value, expected, "input")
    if value["schema_version"] != "story-design-card-input.v1":
        raise StoryDesignError("schema_version_unsupported", str(value["schema_version"]))
    if value["structure_route"] != "story-arc":
        raise StoryDesignError("story_route_not_selected", "a story card is only valid for story-arc")
    if value["risk_class"] not in {"ordinary", "insurance-health", "high-risk"}:
        raise StoryDesignError("risk_class_invalid", str(value["risk_class"]))

    source = value["story_source"]
    exact_keys(
        source,
        {"mode", "authorization_status", "identity_treatment", "quote_treatment", "fact_refs"},
        "story_source",
    )
    if source["authorization_status"] == "blocked":
        raise StoryDesignError("story_source_not_authorized", "blocked source material cannot enter story design")
    if source["mode"] == "authorized-interview" and source["authorization_status"] != "confirmed":
        raise StoryDesignError("interview_authorization_missing", "interview stories require confirmed authorization")
    if source["identity_treatment"] == "authorized-identifiable" and source["authorization_status"] != "confirmed":
        raise StoryDesignError("identity_authorization_missing", "identifiable treatment requires confirmed authorization")

    format_design = value["format_design"]
    exact_keys(
        format_design,
        {"format_id", "standalone", "central_change_count", "scene_meaning_alternation", "interview_action_meaning_layers"},
        "format_design",
    )
    format_id = format_design["format_id"]
    if format_id not in FORMAT_TURN_BOUNDS:
        raise StoryDesignError("format_profile_unknown", str(format_id))
    if format_design["standalone"] is not True:
        raise StoryDesignError("story_not_standalone", "each item must work without another episode")
    if format_id in {"short-video-narration", "moments-short-text"} and format_design["central_change_count"] != 1:
        raise StoryDesignError("micro_story_too_many_changes", "short social stories carry one central change")
    if format_id == "longform-article" and format_design["scene_meaning_alternation"] != "planned":
        raise StoryDesignError("longform_scene_meaning_missing", "longform stories must alternate scene and understanding")
    if format_id == "interview-video":
        if format_design["interview_action_meaning_layers"] != "separated":
            raise StoryDesignError("interview_layers_missing", "interview stories must separate action and meaning layers")
        if source["mode"] != "authorized-interview":
            raise StoryDesignError("interview_source_mode_invalid", "interview-video requires authorized-interview source mode")

    strategy = value["production_strategy"]
    exact_keys(
        strategy,
        {"current_mode", "platform_specific_variants", "single_variable_experiment", "distribution_rule", "release_freeze_contract", "future_trigger"},
        "production_strategy",
    )
    if strategy["current_mode"] == "single-master-synchronized":
        if strategy["platform_specific_variants"] != "deferred-capacity":
            raise StoryDesignError("production_strategy_conflict", "single-master mode defers platform-specific variants")
        if strategy["distribution_rule"] != "same-frozen-master-manual-multi-platform":
            raise StoryDesignError("distribution_rule_conflict", "single-master mode must distribute one frozen master manually")
    if strategy["current_mode"] == "platform-specific-variants":
        if strategy["platform_specific_variants"] != "active":
            raise StoryDesignError("production_strategy_conflict", "platform-specific mode requires active variants")
        if strategy["distribution_rule"] != "platform-specific-frozen-variants":
            raise StoryDesignError("distribution_rule_conflict", "platform variants require separately frozen variants")

    timing = value["timing_design"]
    if format_id == "short-video-narration":
        if not isinstance(timing, dict):
            raise StoryDesignError("short_video_timing_missing", "short-video narration requires a timing design")
        exact_keys(
            timing,
            {"profile_basis", "target_duration_seconds", "audience_stake_visible_by_second", "reason_to_continue_visible_by_second", "first_information_advance_by_second", "maximum_gap_between_advances_seconds", "main_payoff_by_completion_ratio", "heuristic_not_platform_fact"},
            "timing_design",
        )
        thresholds = timing_profile_thresholds()
        if timing["audience_stake_visible_by_second"] > thresholds["audience_stake_max_seconds"]:
            raise StoryDesignError("audience_stake_too_late", "short-video audience stake exceeds the current operating profile")
        if timing["reason_to_continue_visible_by_second"] > thresholds["reason_to_continue_max_seconds"]:
            raise StoryDesignError("reason_to_continue_too_late", "short-video continuation reason exceeds the current operating profile")
        if timing["first_information_advance_by_second"] > thresholds["first_information_advance_max_seconds"]:
            raise StoryDesignError("first_advance_too_late", "short-video first evidence or change exceeds the current operating profile")
        if timing["maximum_gap_between_advances_seconds"] > thresholds["information_advance_gap_max_seconds"]:
            raise StoryDesignError("information_advance_gap_invalid", "short-video information gap exceeds the current operating profile")
        if timing["main_payoff_by_completion_ratio"] > thresholds["main_payoff_max_completion_ratio"]:
            raise StoryDesignError("main_payoff_too_late", "the main payoff exceeds the current completion-ratio profile")
        if timing["heuristic_not_platform_fact"] is not True:
            raise StoryDesignError("timing_heuristic_promoted", "timing thresholds are operating hypotheses, not platform facts")
    elif timing is not None:
        raise StoryDesignError("timing_profile_not_applicable", "non-short-video formats must use a format-specific adapter")

    continuity = value["continuity_value"]
    exact_keys(
        continuity,
        {"current_item_value", "future_value_promise", "target_audience", "surface_mode", "mechanical_follow_request_prohibited", "promise_status"},
        "continuity_value",
    )
    if continuity["current_item_value"].strip().casefold() == continuity["future_value_promise"].strip().casefold():
        raise StoryDesignError("continuity_value_not_distinct", "future value must add a reason to return beyond this item's answer")
    if continuity["mechanical_follow_request_prohibited"] is not True:
        raise StoryDesignError("mechanical_follow_request", "continuity value cannot be replaced by a mechanical follow request")

    binding = value["fact_binding"]
    exact_keys(binding, {"fact_card_ref", "fact_revision_id", "fact_card_sha256", "allowed_fact_ids"}, "fact_binding")
    fact_path = resolve_ref(binding["fact_card_ref"])
    if text_sha256(fact_path) != binding["fact_card_sha256"]:
        raise StoryDesignError("fact_card_hash_drift", "fact card changed after story design")
    fact_document = load_json(fact_path)
    actual_ids = {row.get("fact_id") for row in fact_document.get("facts", []) if isinstance(row, dict)}
    allowed = set(binding["allowed_fact_ids"])
    if not allowed or not allowed.issubset(actual_ids):
        raise StoryDesignError("allowed_fact_missing", "allowed facts must exist in the bound fact card")
    unsupported = sorted(set(all_fact_refs(value)) - allowed)
    if unsupported:
        raise StoryDesignError("unsupported_story_fact", ",".join(unsupported))

    protagonist = value["protagonist"]
    exact_keys(protagonist, {"role", "immediate_goal", "goal_fact_refs", "internal_state_status", "internal_state_fact_refs"}, "protagonist")
    if protagonist["internal_state_status"] == "not-used" and protagonist["internal_state_fact_refs"]:
        raise StoryDesignError("internal_state_evidence_unexpected", "unused internal state cannot carry evidence")
    if protagonist["internal_state_status"] != "not-used" and not protagonist["internal_state_fact_refs"]:
        raise StoryDesignError("invented_internal_state", "internal states require author confirmation or a source quote")

    bridge = value["audience_bridge"]
    exact_keys(bridge, {"shared_situation", "recognition_basis", "validation_status"}, "audience_bridge")
    if bridge["recognition_basis"] == "agent-hypothesis" and bridge["validation_status"] != "needs-validation":
        raise StoryDesignError("audience_hypothesis_promoted", "an agent hypothesis cannot be presented as audience evidence")

    scene = value["scene_anchor"]
    exact_keys(scene, {"beat_id", "detail_type", "observable_detail", "fact_refs"}, "scene_anchor")

    gap = value["expectation_gap"]
    if gap["expected_outcome"].strip().casefold() == gap["actual_outcome"].strip().casefold():
        raise StoryDesignError("expectation_gap_missing", "expected and actual outcomes must differ")
    attempt = value["attempt_and_feedback"]
    exact_keys(
        attempt,
        {"beat_id", "first_action", "expected_feedback", "actual_feedback", "fact_refs"},
        "attempt_and_feedback",
    )
    if attempt["expected_feedback"].strip().casefold() == attempt["actual_feedback"].strip().casefold():
        raise StoryDesignError("unexpected_feedback_missing", "the first action must meet a different real response")
    choice = value["choice_under_pressure"]
    if choice["chosen_action"] not in choice["options"]:
        raise StoryDesignError("choice_not_grounded", "chosen_action must be one declared option")

    turns = value["turning_points"]
    minimum_turns, maximum_turns = FORMAT_TURN_BOUNDS[format_id]
    if not minimum_turns <= len(turns) <= maximum_turns:
        raise StoryDesignError(
            "turn_count_not_fit_format",
            f"{format_id} requires {minimum_turns}-{maximum_turns} turning points",
        )
    if any(item["before_value"].strip().casefold() == item["after_value"].strip().casefold() for item in turns):
        raise StoryDesignError("value_shift_missing", "each turning point must change value")
    if not any(item["function"] in {"reversal", "revelation", "decision"} for item in turns):
        raise StoryDesignError("turning_point_missing", "at least one decision, revelation, or reversal is required")

    beat_ids = {
        scene["beat_id"], value["inciting_incident"]["beat_id"], gap["beat_id"], attempt["beat_id"],
        choice["beat_id"], value["climax"]["beat_id"],
    }
    beat_ids.update(item["beat_id"] for item in value["pressure"] + turns)
    for emotion in value["emotional_design"]["emotion_beats"]:
        if emotion["beat_ref"] not in beat_ids:
            raise StoryDesignError("emotion_beat_unbound", emotion["beat_ref"])
        if value["risk_class"] in {"insurance-health", "high-risk"} and emotion["intensity"] == "high":
            raise StoryDesignError("high_risk_emotion_too_strong", "medical and insurance emotion must remain proportionate")
        if emotion["evidence_mode"] == "confirmed-quote" and not emotion["fact_refs"]:
            raise StoryDesignError("quote_evidence_missing", "quoted emotion needs a fact reference")

    explanation = value["explanation_bridge"]
    if explanation["story_role"] != "illustration-not-population-proof":
        raise StoryDesignError("case_generalized", "a story cannot substitute for population or contract evidence")
    if not 2 <= explanation["sentence_budget"] <= 4:
        raise StoryDesignError("explanation_budget_invalid", "post-story explanation must use two to four sentences")

    diagnostics = value["editorial_diagnostics"]
    exact_keys(diagnostics, {"causal_link_status", "stickiness", "causal_trim_status"}, "editorial_diagnostics")
    exact_keys(
        diagnostics["stickiness"],
        {"simple", "unexpected", "concrete", "credible", "emotional", "story"},
        "editorial_diagnostics.stickiness",
    )

    learning = value["publication_learning_plan"]
    exact_keys(
        learning,
        {"experiment_status", "primary_variable", "one_variable_only", "observation_windows", "metric_keys", "content_signal_only", "causal_claim_prohibited"},
        "publication_learning_plan",
    )
    if learning["one_variable_only"] is not True:
        raise StoryDesignError("learning_plan_multiple_variables", "compare at most one story variable per item")
    if learning["observation_windows"] != ["early-48-72h", "d7"]:
        raise StoryDesignError("learning_plan_window_drift", "use the existing early and day-7 observation windows")
    if learning["content_signal_only"] is not True or learning["causal_claim_prohibited"] is not True:
        raise StoryDesignError("learning_plan_signal_upgrade", "story performance is a noncausal content signal")
    if learning["experiment_status"] == "deferred-capacity" and learning["primary_variable"] != "none":
        raise StoryDesignError("deferred_experiment_has_variable", "a deferred experiment must not claim an active test variable")
    if learning["experiment_status"] == "planned" and learning["primary_variable"] == "none":
        raise StoryDesignError("planned_experiment_missing_variable", "a planned experiment requires one declared variable")
    if strategy["single_variable_experiment"] == "deferred-capacity" and learning["experiment_status"] != "deferred-capacity":
        raise StoryDesignError("experiment_status_conflict", "capacity-deferred strategy must keep the publication experiment deferred")

    review = value["review"]
    required_review = {
        "causal_not_chronological", "choice_reveals_character", "emotion_is_evidence_bound",
        "audience_bridge_is_honest", "climax_changes_value", "story_and_explanation_separated", "decision",
    }
    exact_keys(review, required_review, "review")
    if review["decision"] != "passed" or any(review[key] is not True for key in required_review - {"decision"}):
        raise StoryDesignError("story_review_failed", "all story design checks must pass")
    return copy.deepcopy(value)


def create_receipt_from_value(raw_value: dict[str, Any]) -> dict[str, Any]:
    value = validate_input(raw_value)
    payload = copy.deepcopy(value)
    payload["schema_version"] = "story-design-card.v1"
    payload["card_id"] = "story-card-" + canonical_sha256(value)[:24]
    payload["artifact_status"] = "candidate-only"
    payload["publication_boundary"] = "manual-only"
    payload["authority"] = AUTHORITY
    payload["diagnostic_warnings"] = build_diagnostic_warnings(value)
    payload["receipt_payload_sha256"] = canonical_sha256(payload)
    Draft202012Validator(load_json(SCHEMA), format_checker=FormatChecker()).validate(payload)
    return payload


def create_receipt(input_path: Path) -> dict[str, Any]:
    return create_receipt_from_value(load_json(input_path))


def validate_receipt(value: dict[str, Any]) -> None:
    Draft202012Validator(load_json(SCHEMA), format_checker=FormatChecker()).validate(value)
    unsigned = copy.deepcopy(value)
    digest = unsigned.pop("receipt_payload_sha256")
    if canonical_sha256(unsigned) != digest:
        raise StoryDesignError("receipt_hash_drift", "story design card changed after review")
    input_value = copy.deepcopy(value)
    for key in ("card_id", "artifact_status", "publication_boundary", "authority", "receipt_payload_sha256", "diagnostic_warnings"):
        input_value.pop(key)
    input_value["schema_version"] = "story-design-card-input.v1"
    validated_input = validate_input(input_value)
    if value["diagnostic_warnings"] != build_diagnostic_warnings(validated_input):
        raise StoryDesignError("diagnostic_warning_drift", "advisory diagnostics no longer match the reviewed input")
    fact_path = resolve_ref(value["fact_binding"]["fact_card_ref"])
    if text_sha256(fact_path) != value["fact_binding"]["fact_card_sha256"]:
        raise StoryDesignError("fact_card_hash_drift", "fact card changed after story design")


def write_receipt(path: Path, value: dict[str, Any]) -> str:
    resolved = path.resolve()
    if not any(resolved.is_relative_to(root.resolve()) for root in OUTPUT_ROOTS):
        raise StoryDesignError("output_path_prohibited", "output must stay under a gate runtime root")
    encoded = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.write_bytes(encoded)
        return "created"
    except OSError as error:
        raise StoryDesignError("output_write_failed", str(error)) from error


def check() -> dict[str, Any]:
    first = create_receipt(FIXTURE)
    second = create_receipt(FIXTURE)
    if canonical_bytes(first) != canonical_bytes(second):
        raise StoryDesignError("non_deterministic", "fixture output is not stable")
    validate_receipt(first)
    return {"status": "passed", "idempotency": "byte-stable", "card_id": first["card_id"]}


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
            print(json.dumps({"status": write_receipt(args.output, receipt), "card_id": receipt["card_id"]}, ensure_ascii=False))
        elif args.command == "validate":
            validate_receipt(load_json(args.receipt))
            print(json.dumps({"status": "passed"}))
        else:
            print(json.dumps(check(), ensure_ascii=False, sort_keys=True))
        return 0
    except (StoryDesignError, Exception) as error:
        code = error.code if isinstance(error, StoryDesignError) else "validation_failed"
        print(json.dumps({"status": "blocked", "code": code, "message": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
