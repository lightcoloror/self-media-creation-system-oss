#!/usr/bin/env python3
"""Run all local self-media schemas, synthetic fixtures, migrations, and tests."""

from __future__ import annotations

import argparse
import copy
import functools
import importlib.util
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = ROOT.parent


def controlled_subprocess_env() -> dict[str, str]:
    """Keep Python and test temp writes inside a repository-owned runtime root."""

    temp_root = ROOT / ".runtime" / "test-temp"
    pycache_root = ROOT / ".runtime" / "python-cache"
    temp_root.mkdir(parents=True, exist_ok=True)
    pycache_root.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    for key in ("TMPDIR", "TEMP", "TMP"):
        env[key] = str(temp_root)
    env["TEST_TMP_ROOT"] = str(temp_root)
    env["PYTHONPYCACHEPREFIX"] = str(pycache_root)
    return env
OPERATIONS_SCRIPT = ROOT / "scripts" / "operations_contract_regression.py"
OPERATIONS_SPEC = importlib.util.spec_from_file_location("operations_contract_regression", OPERATIONS_SCRIPT)
assert OPERATIONS_SPEC and OPERATIONS_SPEC.loader
OPERATIONS = importlib.util.module_from_spec(OPERATIONS_SPEC)
OPERATIONS_SPEC.loader.exec_module(OPERATIONS)

SCENARIO_SCRIPT = ROOT / "scripts" / "operations_scenario_suite.py"
SCENARIO_SPEC = importlib.util.spec_from_file_location("operations_scenario_suite", SCENARIO_SCRIPT)
assert SCENARIO_SPEC and SCENARIO_SPEC.loader
SCENARIOS = importlib.util.module_from_spec(SCENARIO_SPEC)
SCENARIO_SPEC.loader.exec_module(SCENARIOS)

HIGH_FREQUENCY_SCRIPT = ROOT / "scripts" / "high_frequency_topic_loop.py"
HIGH_FREQUENCY_SPEC = importlib.util.spec_from_file_location("high_frequency_topic_loop", HIGH_FREQUENCY_SCRIPT)
assert HIGH_FREQUENCY_SPEC and HIGH_FREQUENCY_SPEC.loader
HIGH_FREQUENCY = importlib.util.module_from_spec(HIGH_FREQUENCY_SPEC)
HIGH_FREQUENCY_SPEC.loader.exec_module(HIGH_FREQUENCY)

VIBE_FIXTURE_SCRIPT = ROOT / "scripts" / "vibe_living_synthetic_fixture_pack.py"
VIBE_FIXTURE_SPEC = importlib.util.spec_from_file_location(
    "vibe_living_synthetic_fixture_pack", VIBE_FIXTURE_SCRIPT
)
assert VIBE_FIXTURE_SPEC and VIBE_FIXTURE_SPEC.loader
VIBE_FIXTURE = importlib.util.module_from_spec(VIBE_FIXTURE_SPEC)
VIBE_FIXTURE_SPEC.loader.exec_module(VIBE_FIXTURE)

PUBLICATION_FEEDBACK_SCRIPT = ROOT / "scripts" / "publication_feedback_tracker.py"
PUBLICATION_FEEDBACK_SPEC = importlib.util.spec_from_file_location(
    "publication_feedback_tracker", PUBLICATION_FEEDBACK_SCRIPT
)
assert PUBLICATION_FEEDBACK_SPEC and PUBLICATION_FEEDBACK_SPEC.loader
PUBLICATION_FEEDBACK = importlib.util.module_from_spec(PUBLICATION_FEEDBACK_SPEC)
PUBLICATION_FEEDBACK_SPEC.loader.exec_module(PUBLICATION_FEEDBACK)

PLATFORM_METRICS_SCRIPT = ROOT / "scripts" / "platform_metrics_intake.py"
PLATFORM_METRICS_SPEC = importlib.util.spec_from_file_location(
    "platform_metrics_intake", PLATFORM_METRICS_SCRIPT
)
assert PLATFORM_METRICS_SPEC and PLATFORM_METRICS_SPEC.loader
PLATFORM_METRICS = importlib.util.module_from_spec(PLATFORM_METRICS_SPEC)
PLATFORM_METRICS_SPEC.loader.exec_module(PLATFORM_METRICS)

PUBLICATION_FREEZE_SCRIPT = ROOT / "scripts" / "publication_version_freeze.py"
PUBLICATION_FREEZE_SPEC = importlib.util.spec_from_file_location(
    "publication_version_freeze", PUBLICATION_FREEZE_SCRIPT
)
assert PUBLICATION_FREEZE_SPEC and PUBLICATION_FREEZE_SPEC.loader
PUBLICATION_FREEZE = importlib.util.module_from_spec(PUBLICATION_FREEZE_SPEC)
PUBLICATION_FREEZE_SPEC.loader.exec_module(PUBLICATION_FREEZE)

CONTENT_OPERATIONS_CYCLE_SCRIPT = ROOT / "scripts" / "content_operations_cycle.py"

CONTENT_PACKAGING_REVIEW_SCRIPT = ROOT / "scripts" / "content_packaging_review.py"
CONTENT_PACKAGING_REVIEW_SPEC = importlib.util.spec_from_file_location(
    "content_packaging_review", CONTENT_PACKAGING_REVIEW_SCRIPT
)
assert CONTENT_PACKAGING_REVIEW_SPEC and CONTENT_PACKAGING_REVIEW_SPEC.loader
CONTENT_PACKAGING_REVIEW = importlib.util.module_from_spec(CONTENT_PACKAGING_REVIEW_SPEC)
CONTENT_PACKAGING_REVIEW_SPEC.loader.exec_module(CONTENT_PACKAGING_REVIEW)

SERIOUS_TRANSLATION_GATE_SCRIPT = ROOT / "scripts" / "serious_content_translation_gate.py"
SERIOUS_TRANSLATION_GATE_SPEC = importlib.util.spec_from_file_location(
    "serious_content_translation_gate", SERIOUS_TRANSLATION_GATE_SCRIPT
)
assert SERIOUS_TRANSLATION_GATE_SPEC and SERIOUS_TRANSLATION_GATE_SPEC.loader
SERIOUS_TRANSLATION_GATE = importlib.util.module_from_spec(SERIOUS_TRANSLATION_GATE_SPEC)
SERIOUS_TRANSLATION_GATE_SPEC.loader.exec_module(SERIOUS_TRANSLATION_GATE)

SCIENCE_POPULARIZATION_GATE_SCRIPT = ROOT / "scripts" / "science_popularization_gate.py"
SCIENCE_POPULARIZATION_GATE_SPEC = importlib.util.spec_from_file_location(
    "science_popularization_gate", SCIENCE_POPULARIZATION_GATE_SCRIPT
)
assert SCIENCE_POPULARIZATION_GATE_SPEC and SCIENCE_POPULARIZATION_GATE_SPEC.loader
SCIENCE_POPULARIZATION_GATE = importlib.util.module_from_spec(SCIENCE_POPULARIZATION_GATE_SPEC)
SCIENCE_POPULARIZATION_GATE_SPEC.loader.exec_module(SCIENCE_POPULARIZATION_GATE)

TOPIC_ANGLE_DECISION_SCRIPT = ROOT / "scripts" / "topic_angle_decision.py"
TOPIC_ANGLE_DECISION_SPEC = importlib.util.spec_from_file_location(
    "topic_angle_decision", TOPIC_ANGLE_DECISION_SCRIPT
)
assert TOPIC_ANGLE_DECISION_SPEC and TOPIC_ANGLE_DECISION_SPEC.loader
TOPIC_ANGLE_DECISION = importlib.util.module_from_spec(TOPIC_ANGLE_DECISION_SPEC)
TOPIC_ANGLE_DECISION_SPEC.loader.exec_module(TOPIC_ANGLE_DECISION)

STORY_FIVE_QUESTION_SCRIPT = ROOT / "scripts" / "story_five_question_adapter.py"
STORY_FIVE_QUESTION_SPEC = importlib.util.spec_from_file_location(
    "story_five_question_adapter", STORY_FIVE_QUESTION_SCRIPT
)
assert STORY_FIVE_QUESTION_SPEC and STORY_FIVE_QUESTION_SPEC.loader
STORY_FIVE_QUESTION = importlib.util.module_from_spec(STORY_FIVE_QUESTION_SPEC)
STORY_FIVE_QUESTION_SPEC.loader.exec_module(STORY_FIVE_QUESTION)

CROSS_PLATFORM_FACT_GATE_SCRIPT = ROOT / "scripts" / "cross_platform_fact_consistency_gate.py"
CROSS_PLATFORM_FACT_GATE_SPEC = importlib.util.spec_from_file_location(
    "cross_platform_fact_consistency_gate", CROSS_PLATFORM_FACT_GATE_SCRIPT
)
assert CROSS_PLATFORM_FACT_GATE_SPEC and CROSS_PLATFORM_FACT_GATE_SPEC.loader
CROSS_PLATFORM_FACT_GATE = importlib.util.module_from_spec(CROSS_PLATFORM_FACT_GATE_SPEC)
CROSS_PLATFORM_FACT_GATE_SPEC.loader.exec_module(CROSS_PLATFORM_FACT_GATE)

STORY_DESIGN_GATE_SCRIPT = ROOT / "scripts" / "story_design_gate.py"
STORY_DESIGN_GATE_SPEC = importlib.util.spec_from_file_location(
    "story_design_gate", STORY_DESIGN_GATE_SCRIPT
)
assert STORY_DESIGN_GATE_SPEC and STORY_DESIGN_GATE_SPEC.loader
STORY_DESIGN_GATE = importlib.util.module_from_spec(STORY_DESIGN_GATE_SPEC)
STORY_DESIGN_GATE_SPEC.loader.exec_module(STORY_DESIGN_GATE)

SHORT_VIDEO_TIMING_SCRIPT = ROOT / "scripts" / "short_video_timing_evidence.py"
SHORT_VIDEO_TIMING_SPEC = importlib.util.spec_from_file_location(
    "short_video_timing_evidence", SHORT_VIDEO_TIMING_SCRIPT
)
assert SHORT_VIDEO_TIMING_SPEC and SHORT_VIDEO_TIMING_SPEC.loader
SHORT_VIDEO_TIMING = importlib.util.module_from_spec(SHORT_VIDEO_TIMING_SPEC)
SHORT_VIDEO_TIMING_SPEC.loader.exec_module(SHORT_VIDEO_TIMING)

STORY_MATERIAL_INBOX_SCRIPT = ROOT / "scripts" / "story_material_inbox.py"
STORY_MATERIAL_INBOX_SPEC = importlib.util.spec_from_file_location(
    "story_material_inbox", STORY_MATERIAL_INBOX_SCRIPT
)
assert STORY_MATERIAL_INBOX_SPEC and STORY_MATERIAL_INBOX_SPEC.loader
STORY_MATERIAL_INBOX = importlib.util.module_from_spec(STORY_MATERIAL_INBOX_SPEC)
STORY_MATERIAL_INBOX_SPEC.loader.exec_module(STORY_MATERIAL_INBOX)

CANONICAL_ROUTING_SCRIPT = ROOT / "scripts" / "canonical_routing.py"
CANONICAL_ROUTING_SPEC = importlib.util.spec_from_file_location(
    "canonical_routing", CANONICAL_ROUTING_SCRIPT
)
assert CANONICAL_ROUTING_SPEC and CANONICAL_ROUTING_SPEC.loader
CANONICAL_ROUTING = importlib.util.module_from_spec(CANONICAL_ROUTING_SPEC)
CANONICAL_ROUTING_SPEC.loader.exec_module(CANONICAL_ROUTING)

CHANNEL_PORTFOLIO_SCRIPT = ROOT / "scripts" / "check_channel_portfolio.py"
CHANNEL_PORTFOLIO_SPEC = importlib.util.spec_from_file_location(
    "check_channel_portfolio", CHANNEL_PORTFOLIO_SCRIPT
)
assert CHANNEL_PORTFOLIO_SPEC and CHANNEL_PORTFOLIO_SPEC.loader
CHANNEL_PORTFOLIO = importlib.util.module_from_spec(CHANNEL_PORTFOLIO_SPEC)
CHANNEL_PORTFOLIO_SPEC.loader.exec_module(CHANNEL_PORTFOLIO)

AGENT_ENTRY_SCRIPT = ROOT / "scripts" / "self_media_agent.py"
AGENT_ENTRY_SPEC = importlib.util.spec_from_file_location("self_media_agent", AGENT_ENTRY_SCRIPT)
assert AGENT_ENTRY_SPEC and AGENT_ENTRY_SPEC.loader
AGENT_ENTRY = importlib.util.module_from_spec(AGENT_ENTRY_SPEC)
AGENT_ENTRY_SPEC.loader.exec_module(AGENT_ENTRY)

SMALL_MODEL_LOOP_SCRIPT = ROOT / "scripts" / "small_model_content_loop.py"
SMALL_MODEL_LOOP_SPEC = importlib.util.spec_from_file_location(
    "small_model_content_loop", SMALL_MODEL_LOOP_SCRIPT
)
assert SMALL_MODEL_LOOP_SPEC and SMALL_MODEL_LOOP_SPEC.loader
SMALL_MODEL_LOOP = importlib.util.module_from_spec(SMALL_MODEL_LOOP_SPEC)
SMALL_MODEL_LOOP_SPEC.loader.exec_module(SMALL_MODEL_LOOP)

CASE_GOVERNANCE_SCRIPT = ROOT / "scripts" / "case_governance_contracts.py"
CASE_GOVERNANCE_SPEC = importlib.util.spec_from_file_location(
    "case_governance_contracts", CASE_GOVERNANCE_SCRIPT
)
assert CASE_GOVERNANCE_SPEC and CASE_GOVERNANCE_SPEC.loader
CASE_GOVERNANCE = importlib.util.module_from_spec(CASE_GOVERNANCE_SPEC)
CASE_GOVERNANCE_SPEC.loader.exec_module(CASE_GOVERNANCE)

OPERATIONS_FIXTURE = ROOT / "fixtures" / "operations-contract-regression.v1.synthetic.json"
LEGACY_FIXTURE = ROOT / "fixtures" / "legacy-feedback.v0.synthetic.json"
LEGACY_SCHEMA = ROOT / "schemas" / "legacy-feedback.v0.schema.json"
DIAGNOSIS_FIXTURE = ROOT / "fixtures" / "content-bundle.v1.fixture.json"
BASELINE_OPERATIONS_VALIDATOR = WORKSPACE_ROOT / "scripts" / "validate-content-operations.py"
BASELINE_OPERATIONS_TESTS = WORKSPACE_ROOT / "tests"
QUALITY_GATES_PATH = ROOT.parent / "docs" / "content-creation-system" / "routing" / "quality-gates.json"
RECIPES_PATH = ROOT / "recipes" / "self-media-recipes.v1.json"
TYPOGRAPHY_POLICY_PATH = ROOT / "schemas" / "typography-gates.v1.policy.json"



def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def schema_errors(document: Any, schema: dict[str, Any], label: str) -> list[str]:
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    return [
        f"{label}: {'.'.join(str(part) for part in error.path) or '$'}: {error.message}"
        for error in sorted(validator.iter_errors(document), key=lambda error: list(error.path))
    ]


def validate_legacy_fixture(bundle: dict[str, Any], legacy: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    schema = load_json(LEGACY_SCHEMA)
    try:
        Draft202012Validator.check_schema(schema)
    except Exception as error:
        return [f"legacy schema invalid: {error}"]
    errors.extend(schema_errors(legacy, schema, "legacy_fixture"))
    if errors:
        return errors
    migrated = OPERATIONS.migrate_legacy_feedback(legacy["feedback"])
    candidate = copy.deepcopy(bundle["content_item"])
    candidate["feedback"] = migrated
    content_schema = OPERATIONS.load_json(OPERATIONS.CONTENT_SCHEMA)
    errors.extend(OPERATIONS.schema_errors(candidate, content_schema, "legacy_migration.content_item"))
    if legacy["feedback"]["signal_status"] == "no_signal":
        if migrated["content_signal_status"] != "content_no_signal":
            errors.append("legacy no_signal did not migrate to content_no_signal")
        if migrated["business_signal_status"] != "not-observed":
            errors.append("legacy no_signal must not fabricate a business conclusion")
    return errors


def additional_lifecycle_errors(bundle: dict[str, Any]) -> list[str]:
    """Checks that are deliberately stricter than individual object schemas."""
    errors: list[str] = []
    events = bundle["publication_events"]
    event_ids = [event["event_id"] for event in events]
    if len(event_ids) != len(set(event_ids)):
        errors.append("publication_events must not contain duplicate event_id values")
    snapshots = bundle["performance_snapshots"]
    observed = [datetime.fromisoformat(snapshot["as_of"]) for snapshot in snapshots]
    if observed != sorted(observed):
        errors.append("performance_snapshots must be ordered by as_of ascending")
    return errors


def validate_diagnosis_fixture() -> list[str]:
    diagnosis_path = ROOT / "scripts" / "content_diagnosis.py"
    spec = importlib.util.spec_from_file_location("content_diagnosis", diagnosis_path)
    assert spec and spec.loader
    diagnosis = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(diagnosis)
    return diagnosis.validate_bundle(load_json(DIAGNOSIS_FIXTURE))


def validate_baseline_operations_fixture() -> list[str]:
    completed = subprocess.run(
        [sys.executable, str(BASELINE_OPERATIONS_VALIDATOR)],
        cwd=WORKSPACE_ROOT,
        capture_output=True,
        text=True,
        check=False,
        env=controlled_subprocess_env(),
    )
    if completed.returncode == 0:
        return []
    output = (completed.stderr or completed.stdout).strip()
    return [f"baseline_operations: {output or 'validator failed without output'}"]


@functools.lru_cache(maxsize=1)
def validate_content_operations_cycle() -> list[str]:
    """Run the canonical append-only operations-cycle smoke check.

    The cycle owns its private test stores and recovery checks.  Invoking its
    stable CLI here keeps the repository-wide checker independent from the
    cycle module's implementation details and prevents a second orchestration
    path from emerging inside this file.
    """
    completed = subprocess.run(
        [sys.executable, str(CONTENT_OPERATIONS_CYCLE_SCRIPT), "check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        env=controlled_subprocess_env(),
    )
    if completed.returncode == 0:
        return []
    output = (completed.stderr or completed.stdout).strip()
    return [f"content_operations_cycle: {output or 'check failed without output'}"]


def validate_content_packaging_review() -> list[str]:
    """Run the frozen-body promise and standalone-item packaging gate."""

    try:
        result = CONTENT_PACKAGING_REVIEW.check()
    except Exception as error:
        return [f"content_packaging_review: {error}"]
    if result.get("status") != "passed" or result.get("idempotency") != "byte-stable":
        return ["content_packaging_review: deterministic fixture check did not pass"]
    return []


def validate_serious_content_translation_gate() -> list[str]:
    """Run the dual-gate broad-audience translation contract check."""

    try:
        result = SERIOUS_TRANSLATION_GATE.check()
    except Exception as error:
        return [f"serious_content_translation_gate: {error}"]
    if result.get("status") != "passed" or result.get("idempotency") != "byte-stable":
        return ["serious_content_translation_gate: deterministic fixture check did not pass"]
    quality = load_json(QUALITY_GATES_PATH)
    configured = set(quality.get("professional_translation_gates") or [])
    required = {
        "precreative-evidence-spine-and-content-nature-reviewed",
        "life-relevance-and-audience-decision-recorded",
        "sensitivity-profile-recorded",
        "humor-strength-fits-sensitivity",
        "near-zero-humor-profile-defaults-to-none-unless-human-exception",
        "humor-target-does-not-exploit-affected-person",
        "analogy-mapping-and-boundary-recorded",
        "postcreative-misinterpretation-review",
        "fun-is-related-not-decorative-or-misleading",
        "fun-helps-answer-core-question",
        "core-value-survives-without-fun",
        "primary-memory-target-is-not-gag",
        "source-detail-retained-in-publication-package",
        "high-risk-evidence-boundary-safety-minimum-met",
    }
    missing = sorted(required - configured)
    if missing:
        return ["serious_content_translation_gate: missing quality gates " + ", ".join(missing)]
    return []


def validate_science_popularization_gate() -> list[str]:
    """Run the science, audience-readability, and AI-safety review extension."""

    try:
        result = SCIENCE_POPULARIZATION_GATE.check()
    except Exception as error:
        return [f"science_popularization_gate: {error}"]
    if result.get("status") != "passed" or result.get("idempotency") != "byte-stable":
        return ["science_popularization_gate: deterministic fixture check did not pass"]

    return [f"science_popularization_gate: {error}" for error in SCIENCE_POPULARIZATION_GATE.routing_errors()]


def validate_editorial_angle_integration() -> list[str]:
    """Run the material-to-angle gate and prove recipe/canonical-extension discovery."""

    errors: list[str] = []
    try:
        result = TOPIC_ANGLE_DECISION.check()
    except Exception as error:
        return [f"topic_angle_decision: {error}"]
    if result.get("status") != "passed" or result.get("idempotency") != "byte-stable":
        errors.append("topic_angle_decision: deterministic fixture check did not pass")

    binding = load_json(ROOT / "routing-binding.v1.json")
    roles = {item.get("role") for item in binding.get("operational_extensions", [])}
    for role in {"topic-angle-editorial-decision", "story-five-question-view-adapter"} - roles:
        errors.append(f"editorial_angle_integration: missing operational extension {role}")

    catalog = load_json(ROOT / "recipes" / "self-media-recipes.v1.json")
    recipes = {item["recipe_id"]: item for item in catalog["recipes"]}
    for recipe_id in ("moments-short-post", "xhs-evidence-graphic"):
        step_ids = [item["step_id"] for item in recipes[recipe_id]["steps"]]
        if "propose-editorial-angle" not in step_ids or "confirm-editorial-angle" not in step_ids:
            errors.append(f"editorial_angle_integration: {recipe_id} bypasses angle proposal or human review")
    case_gates = set(recipes["case-video-candidate"]["quality_gates"])
    if "story-five-question-is-view-over-story-card" not in case_gates:
        errors.append("editorial_angle_integration: case video can bypass the Story Design Card view boundary")
    return errors


def validate_story_five_question_adapter() -> list[str]:
    """Prove that the compact five-question lens remains bound to Story Design Card."""

    try:
        result = STORY_FIVE_QUESTION.check()
    except Exception as error:
        return [f"story_five_question_adapter: {error}"]
    if result.get("status") != "passed" or result.get("idempotency") != "byte-stable":
        return ["story_five_question_adapter: deterministic fixture check did not pass"]
    return []


def validate_cross_platform_fact_consistency_gate() -> list[str]:
    """Run the shared-fact-revision check for multiple platform adaptations."""

    try:
        result = CROSS_PLATFORM_FACT_GATE.check()
    except Exception as error:
        return [f"cross_platform_fact_consistency_gate: {error}"]
    if result.get("status") != "passed" or result.get("idempotency") != "byte-stable":
        return ["cross_platform_fact_consistency_gate: deterministic fixture check did not pass"]
    configured = set(load_json(QUALITY_GATES_PATH).get("cross_platform_fact_consistency_gates") or [])
    required = {
        "one-canonical-fact-revision-shared-by-all-platforms",
        "present-claims-match-canonical-normalized-claim-hash",
        "core-claims-cannot-be-omitted-for-density",
        "optional-omissions-have-density-format-or-duration-reason",
        "undeclared-platform-claims-fail-closed",
    }
    missing = sorted(required - configured)
    return [] if not missing else ["cross_platform_fact_consistency_gate: missing quality gates " + ", ".join(missing)]


def validate_story_design_gate() -> list[str]:
    """Run the conditional evidence-bound story/emotion design gate."""

    try:
        result = STORY_DESIGN_GATE.check()
    except Exception as error:
        return [f"story_design_gate: {error}"]
    if result.get("status") != "passed" or result.get("idempotency") != "byte-stable":
        return ["story_design_gate: deterministic fixture check did not pass"]
    required = {
        "deidentified-story-material-readiness-visible",
        "story-source-mode-authorization-identity-and-quote-treatment-recorded",
        "story-causality-not-chronology-only",
        "fact-bound-scene-anchor-recorded",
        "first-action-and-real-feedback-recorded",
        "pressure-choice-and-tradeoff-recorded",
        "turn-count-and-central-change-fit-format",
        "longform-scene-meaning-alternation-planned-when-applicable",
        "interview-action-and-meaning-layers-separated-when-applicable",
        "turning-points-change-value-state",
        "character-revealed-by-evidence-backed-choice",
        "emotion-beats-bound-to-observable-cue-confirmed-quote-or-author-reaction",
        "audience-identification-bridge-evidence-status-visible",
        "no-invented-internal-state-dialogue-or-sensory-detail",
        "medical-insurance-emotion-intensity-proportionate",
        "individual-story-is-illustration-not-population-proof",
        "story-and-post-story-explanation-separated",
        "causal-link-stickiness-and-trim-diagnostics-visible-but-advisory",
        "one-story-variable-bound-to-early-and-d7-content-signals-without-causal-upgrade",
    }
    configured = set(load_json(QUALITY_GATES_PATH).get("story_emotion_design_gates") or [])
    missing = sorted(required - configured)
    return [] if not missing else ["story_design_gate: missing quality gates " + ", ".join(missing)]


def validate_short_video_timing_evidence() -> list[str]:
    """Prove that timing declarations are measured twice in the existing case-video route."""

    errors: list[str] = []
    try:
        result = SHORT_VIDEO_TIMING.check()
    except Exception as error:
        return [f"short_video_timing_evidence: {error}"]
    if result.get("status") != "passed" or result.get("idempotency") != "byte-stable":
        errors.append("short_video_timing_evidence: deterministic fixture check did not pass")
    if result.get("prerecord_does_not_prove_final_cut") is not True:
        errors.append("short_video_timing_evidence: prerecord evidence was promoted to final-cut proof")
    catalog = load_json(RECIPES_PATH)
    case = next(row for row in catalog["recipes"] if row["recipe_id"] == "case-video-candidate")
    prerecord_steps = [row["step_id"] for row in case["prerecording"]["steps"]]
    production_steps = [row["step_id"] for row in case["steps"]]
    if not prerecord_steps or prerecord_steps[-1] != "verify-prerecord-timing":
        errors.append("short_video_timing_evidence: prerecord observed timing is not the final recording-candidate gate")
    if "final-timing" not in production_steps:
        errors.append("short_video_timing_evidence: final cut can bypass measured timing")
    elif production_steps.index("final-timing") <= production_steps.index("handoff-video-owner"):
        errors.append("short_video_timing_evidence: final-cut timing runs before video-owner output")
    final = case["steps"][-1]
    if "timing-evidence" not in final["input_roles"]:
        errors.append("short_video_timing_evidence: manual publication handoff is not bound to final timing evidence")
    return errors


def validate_platform_metrics_intake() -> list[str]:
    """Validate five platforms and their versioned export profiles offline."""

    errors: list[str] = []
    mapping = load_json(PLATFORM_METRICS.MAPPING_PATH)
    if mapping.get("schema_version") != "platform-metric-mappings.v1":
        errors.append("platform_metrics_intake: mapping version drift")
    profiles = mapping.get("export_profiles")
    if not isinstance(profiles, dict) or not profiles:
        errors.append("platform_metrics_intake: export_profiles are required")
        return errors
    try:
        schema = load_json(PLATFORM_METRICS.SCHEMA_PATH)
        Draft202012Validator.check_schema(schema)
    except Exception as error:
        errors.append(f"platform_metrics_intake: schema invalid: {error}")
    supported_content_metrics = set(PUBLICATION_FEEDBACK.CONTENT_METRIC_LAYERS)
    observed_platforms = {config.get("platform") for config in profiles.values() if isinstance(config, dict)}
    if observed_platforms != PLATFORM_METRICS.PLATFORMS:
        errors.append("platform_metrics_intake: exactly five platforms must remain covered")
    for export_profile, config in profiles.items():
        platform = config.get("platform")
        if config.get("source_grain") not in {"content_item", "account_day"}:
            errors.append(f"platform_metrics_intake: invalid grain for {export_profile}")
        for source_key, definition in (config.get("metrics") or {}).items():
            if not isinstance(definition, list) or len(definition) != 3:
                errors.append(f"platform_metrics_intake: invalid mapping for {export_profile}:{source_key}")
                continue
            metric_key = definition[0]
            if config.get("source_grain") == "content_item" and metric_key not in supported_content_metrics:
                errors.append(f"platform_metrics_intake: unregistered content metric {export_profile}:{metric_key}")
    return errors


def validate_publication_version_freeze() -> list[str]:
    """Run the exact title/cover/opening/duration/media-hash freeze check."""

    try:
        result = PUBLICATION_FREEZE.create(load_json(PUBLICATION_FREEZE.FIXTURE))
        PUBLICATION_FREEZE.validate_receipt(result)
    except Exception as error:
        return [f"publication_version_freeze: {error}"]
    if result.get("publication_boundary") != "manual-only" or any(result.get("authority", {}).values()):
        return ["publication_version_freeze: authority boundary drift"]
    return []


def validate_story_material_inbox() -> list[str]:
    """Run the append-only de-identified story-material candidate check."""

    try:
        result = STORY_MATERIAL_INBOX.check()
    except Exception as error:
        return [f"story_material_inbox: {error}"]
    if result.get("status") != "passed" or result.get("idempotency") != "byte-stable":
        return ["story_material_inbox: deterministic fixture check did not pass"]
    if result.get("readiness") != "ready-for-story-design":
        return ["story_material_inbox: synthetic complete fixture was not ready"]
    return []








def validate_public_content_owner() -> list[str]:
    """Compare the current reviewed owner schema, without claiming historical receipts."""
    owner = WORKSPACE_ROOT / "content-studio-poc" / "schemas" / "content-item.schema.json"
    shared = WORKSPACE_ROOT / "docs" / "content-creation-system" / "content-item.schema.json"
    if not owner.is_file():
        return ["public_content_owner: fixed public ContentStudio source checkout is missing"]
    if owner.read_bytes() != shared.read_bytes():
        return ["public_content_owner: content-item schema bytes differ from the explicit public owner"]
    return []


def validate_canonical_routing() -> list[str]:
    try:
        CANONICAL_ROUTING.load_contracts()
    except Exception as error:
        return [f"canonical_routing: {error}"]
    return []


def validate_channel_portfolio() -> list[str]:
    # This is an explicitly superseded synthetic compatibility example. The
    # actual operator portfolio is separately supplied and never copied here.
    fixture = load_json(ROOT / "fixtures" / "channel-portfolio.v1.synthetic.json")
    if fixture.get("status") != "superseded":
        return ["channel_portfolio: public fixture must not claim active user approval"]
    return [f"channel_portfolio: {error}" for error in CHANNEL_PORTFOLIO.validate(fixture)]



def validate_agent_entry() -> list[str]:
    try:
        receipt = AGENT_ENTRY.doctor()
    except Exception as error:
        return [f"self_media_agent: {error}"]
    if receipt.get("ok") is not True or receipt.get("cold_start_paths_passed") != 5:
        return ["self_media_agent: five-path cold-start doctor did not pass"]
    return []


def validate_case_governance_contracts() -> list[str]:
    """Validate the thin reusable contracts without reading real case data."""

    errors: list[str] = []
    expected = {
        "financial",
        "localized_subtitles",
        "lifecycle",
        "publication",
        "publication_release",
        "publication_post_upload",
    }
    if set(CASE_GOVERNANCE.SCHEMAS) != expected:
        errors.append("case_governance: validator/schema routing is incomplete")
        return errors
    for kind, schema_path in CASE_GOVERNANCE.SCHEMAS.items():
        try:
            schema = load_json(schema_path)
            Draft202012Validator.check_schema(schema)
        except Exception as error:
            errors.append(f"case_governance: {kind}: {error}")
    v2_path = ROOT / "schemas" / "platform-publication-package.v2.schema.json"
    for kind in ("publication_release", "publication_post_upload"):
        if CASE_GOVERNANCE.SCHEMAS.get(kind) != v2_path:
            errors.append(f"case_governance: {kind} is not routed to publication v2")
    return errors


def case_governance_routing_errors(
    quality: dict[str, Any] | None = None,
    recipes: dict[str, Any] | None = None,
) -> list[str]:
    """Fail closed if the new contracts stop participating in the case route."""

    errors: list[str] = []
    quality = load_json(QUALITY_GATES_PATH) if quality is None else quality
    recipes = load_json(RECIPES_PATH) if recipes is None else recipes
    hard_gates = quality.get("hard_gates") or {}
    expected_checks = {
        "fact": "amount-semantic-role-separated-and-evidence-bound",
        "audio_subtitle": "cross-language-review-receipt-hash-bound",
        "technical_integrity": "artifact-lifecycle-delete-guard",
        "visual_usability": "final-layout-all-critical-layers-rounded-corner-and-collision-check",
        "publication": "platform-package-current-rules-and-human-copy-review-bound",
    }
    for category, check in expected_checks.items():
        if check not in set(hard_gates.get(category) or []):
            errors.append(f"case_governance: {category} is missing {check}")
    indexed = {
        str(row.get("recipe_id") or ""): row
        for row in recipes.get("recipes") or []
        if isinstance(row, dict)
    }
    case_recipe = indexed.get("case-video-candidate") or {}
    for value in {
        "case-governance-contracts",
        "final-layout-safety",
        "platform-publication-package",
        "production-run-lock",
        "paragraph-fact-routing",
        "privacy-redaction-binding",
        "isolated-segment-motion-before-concat",
    }:
        if value not in set(case_recipe.get("quality_gates") or []):
            errors.append(f"case_governance: case-video-candidate is missing {value}")
    for value in {
        "case_financial_facts",
        "localized_subtitle_review",
        "final_layout_safety_receipt",
        "platform_publication_package",
        "privacy_redaction_binding",
        "privacy_redaction_binding_receipt",
    }:
        if value not in set(case_recipe.get("on_demand") or []):
            errors.append(f"case_governance: case-video-candidate on_demand is missing {value}")
    return errors


def visual_hard_gate_contract_errors(
    quality: dict[str, Any] | None = None,
    recipes: dict[str, Any] | None = None,
    typography_policy: dict[str, Any] | None = None,
) -> list[str]:
    """Fail closed when cross-flow visual gate routing loses its owner contract.

    Intent: make the typography/readability requirements executable at the
    orchestration layer. Decision: this checker verifies owner/profile/gate
    presence only; renderer-side computed-style measurement remains in MVP
    Video and Content Studio. Reason/evidence/scope are recorded in
    docs/自媒体视觉字号硬门禁-2026-08-26.md.
    """
    errors: list[str] = []
    quality = load_json(QUALITY_GATES_PATH) if quality is None else quality
    recipes = load_json(RECIPES_PATH) if recipes is None else recipes
    typography_policy = (
        load_json(TYPOGRAPHY_POLICY_PATH)
        if typography_policy is None
        else typography_policy
    )

    hard_gates = quality.get("hard_gates")
    if not isinstance(hard_gates, dict):
        return ["visual_hard_gates: quality-gates hard_gates must be an object"]
    required_categories = {
        "fact",
        "privacy",
        "rights",
        "visual_usability",
        "audio_subtitle",
        "technical_integrity",
        "content_promise",
        "publication",
    }
    missing_categories = sorted(required_categories.difference(hard_gates))
    if missing_categories:
        errors.append(
            "visual_hard_gates: missing categories " + ", ".join(missing_categories)
        )
    visual_checks = set(hard_gates.get("visual_usability") or [])
    for required in {
        "canonical-typography-policy-hash-bound",
        "actual-rendered-font-evidence-bound-to-exact-artifact",
        "all-role-minimum-font-sizes-passed",
        "target-preview-readability-passed",
        "no-text-overflow-crop-collision-or-silent-crop",
        "missing-stale-or-under-threshold-visual-evidence-fails-closed",
    }:
        if required not in visual_checks:
            errors.append(f"visual_hard_gates: missing visual check {required}")

    recipe_rows = recipes.get("recipes")
    if not isinstance(recipe_rows, list):
        errors.append("visual_hard_gates: recipes must be a list")
    else:
        required_recipe_gates = {
            "xhs-evidence-graphic": "visual-typography-hard-gate",
            "case-video-candidate": "visual-typography-hard-gate",
            "context-efficient-rework": "visual-typography-hard-gate-if-text-changed",
        }
        indexed = {
            str(row.get("recipe_id") or ""): row
            for row in recipe_rows
            if isinstance(row, dict)
        }
        for recipe_id, gate in required_recipe_gates.items():
            gates = set((indexed.get(recipe_id) or {}).get("quality_gates") or [])
            if gate not in gates:
                errors.append(
                    f"visual_hard_gates: recipe {recipe_id} is missing {gate}"
                )

    if typography_policy.get("schema") != "lucas.typography_gates.v1":
        errors.append("visual_hard_gates: canonical typography policy schema is invalid")
    profiles = typography_policy.get("profiles")
    required_profiles = {
        "youtube_16_9",
        "bilibili_16_9",
        "bilibili_4_3",
        "vertical_profile_3_4",
        "vertical_first_frame_9_16",
        "semantic_motion_1080x1920",
        "social_card_1080x1440",
        "article_html_mobile",
        "article_html_desktop",
    }
    if not isinstance(profiles, dict):
        errors.append("visual_hard_gates: canonical typography profiles must be an object")
    else:
        missing_profiles = sorted(required_profiles.difference(profiles))
        if missing_profiles:
            errors.append(
                "visual_hard_gates: missing typography profiles "
                + ", ".join(missing_profiles)
            )
        for profile_id in sorted(required_profiles.intersection(profiles)):
            profile = profiles[profile_id]
            if not isinstance(profile, dict) or profile.get("hard_gate") is not True:
                errors.append(
                    f"visual_hard_gates: profile {profile_id} must set hard_gate=true"
                )
            if not isinstance(profile, dict) or not isinstance(profile.get("roles"), dict):
                errors.append(
                    f"visual_hard_gates: profile {profile_id} must define role minima"
                )
    return errors


def contract_errors(
    bundle: dict[str, Any] | None = None,
    legacy: dict[str, Any] | None = None,
) -> list[str]:
    bundle = load_json(OPERATIONS_FIXTURE) if bundle is None else bundle
    legacy = load_json(LEGACY_FIXTURE) if legacy is None else legacy
    return (
        OPERATIONS.contract_errors(bundle)
        + additional_lifecycle_errors(bundle)
        + validate_legacy_fixture(bundle, legacy)
        + [f"scenario_suite: {error}" for error in SCENARIOS.scenario_matrix_errors()]
        + [f"high_frequency_loop: {error}" for error in HIGH_FREQUENCY.package_errors()]
        + [
            f"vibe_living_synthetic_pack: {error}"
            for error in VIBE_FIXTURE.validate_pack(VIBE_FIXTURE.DEFAULT_OUTPUT)
        ]
        + [
            f"publication_feedback_tracker: {error}"
            for error in PUBLICATION_FEEDBACK.validate_pack(PUBLICATION_FEEDBACK.DEFAULT_OUTPUT)
        ]
        + validate_content_operations_cycle()
        + validate_story_material_inbox()
        + validate_editorial_angle_integration()
        + validate_story_five_question_adapter()
        + validate_story_design_gate()
        + validate_short_video_timing_evidence()
        + validate_platform_metrics_intake()
        + validate_publication_version_freeze()
        + validate_serious_content_translation_gate()
        + validate_science_popularization_gate()
        + validate_cross_platform_fact_consistency_gate()
        + validate_content_packaging_review()
        + [f"content_bundle: {error}" for error in validate_diagnosis_fixture()]
        + validate_baseline_operations_fixture()
        + validate_public_content_owner()
        + validate_canonical_routing()
        + validate_channel_portfolio()
        + validate_agent_entry()
        + ([] if SMALL_MODEL_LOOP.doctor().get("status") == "pass" else ["small_model_content_loop: doctor blocked"])
        + validate_case_governance_contracts()
        + case_governance_routing_errors()
        + visual_hard_gate_contract_errors()
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-tests", action="store_true", help="Only validate schemas, fixtures, and migration; skip unittest discovery.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    errors = contract_errors()
    if errors:
        print("Self-media contract check failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print(
        "PASS: schemas, three synthetic operating journeys, lifecycle checks, "
        "legacy migration, high-frequency draft-only loop, manual publication feedback, "
        "append-only content operations cycle and story-material inbox, material-to-angle editorial decisions, "
        "five-question Story Design Card mapping, evidence-bound story/emotion design and measured prerecord/final-cut timing, "
        "five-platform metric intake and exact manual publication-version freeze, "
        "serious-content dual-gate translation review, science-popularization review, "
        "and cross-platform fact consistency, "
        "frozen-body standalone-item packaging review, "
        "content-bundle contract, byte-matched current public ContentStudio schema, "
        "and the registered "
        "canonical routing contract set with a superseded synthetic twelve-platform portfolio, "
        "plus five compact weak-Agent cold-start paths and the owner-local small-model "
        "evidence-to-candidate loop."
    )
    if args.no_tests:
        return 0
    result = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", str(ROOT / "tests"), "-v"],
        cwd=ROOT,
        check=False,
        env=controlled_subprocess_env(),
    )
    if result.returncode:
        return result.returncode
    baseline_tests = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", str(BASELINE_OPERATIONS_TESTS), "-p", "test_content_operations_contracts.py", "-v"],
        cwd=WORKSPACE_ROOT,
        check=False,
        env=controlled_subprocess_env(),
    )
    return baseline_tests.returncode


if __name__ == "__main__":
    raise SystemExit(main())
