#!/usr/bin/env python3
"""Resolve five bounded self-media workflows into compact metadata-only capsules."""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import os
import sys
from types import SimpleNamespace
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "agent-tool-manifest.v1.json"
MANIFEST_SCHEMA_PATH = (
    ROOT.parent
    / "docs"
    / "content-creation-system"
    / "portability"
    / "schemas"
    / "agent-tool-manifest.v1.schema.json"
)
CATALOG_PATH = ROOT / "recipes" / "self-media-recipes.v1.json"
CATALOG_SCHEMA_PATH = ROOT / "schemas" / "self-media-recipe-catalog.v1.schema.json"
REQUEST_SCHEMA_PATH = ROOT / "schemas" / "self-media-agent-request.v1.schema.json"
CAPSULE_SCHEMA_PATH = ROOT / "schemas" / "self-media-task-capsule.v1.schema.json"
CAPSULE_V2_SCHEMA_PATH = ROOT / "schemas" / "self-media-task-capsule.v2.schema.json"
HANDOFF_SCHEMA_PATH = ROOT / "schemas" / "self-media-step-handoff.v1.schema.json"
OUTPUT_RECEIPT_SCHEMA_PATH = ROOT / "schemas" / "self-media-step-output-receipt.v1.schema.json"
SEQUENCE_STATUS_SCHEMA_PATH = ROOT / "schemas" / "self-media-sequence-status.v1.schema.json"
CONTEXT_MANIFEST_SCHEMA_PATH = ROOT / "schemas" / "context-input-manifest.v1.schema.json"
VIDEO_PRIVACY_DECISION_SCHEMA_PATH = ROOT / "schemas" / "video-privacy-treatment-decision.v1.schema.json"
CUSTOMER_VIDEO_EFFECT_REVIEW_SCHEMA_PATH = ROOT / "schemas" / "customer-video-effect-review.v1.schema.json"
PREPUBLICATION_PRIVACY_GATE_SCHEMA_PATH = ROOT / "schemas" / "prepublication-privacy-gate.v1.schema.json"
QRP_RESEARCH_OUTPUT_SCHEMA_PATH = ROOT.parent / "question-research-poc" / "schemas" / "research-output.v1.schema.json"
DISCOVERY_PATH = ROOT / "AGENT_DISCOVERY.md"
FIXTURE_ROOT = ROOT / "fixtures" / "agent-entry"
CANONICAL_ROUTING_PATH = ROOT / "scripts" / "canonical_routing.py"
CONTEXT_EFFICIENCY_PATH = ROOT / "scripts" / "context_efficiency.py"
AUTHOR_WRITING_CONTEXT_PATH = ROOT / "scripts" / "author_writing_context.py"
TOOL_REGISTRY_PATH = ROOT.parent / "tool-registry.json"

STEP_CONTEXT_STAGES = {
    "moments-short-post": ["draft", "research", "research", "draft", "voice-review", "publication-review"],
    "xhs-evidence-graphic": [
        "research", "research", "research", "research", "research", "draft",
        "publication-review", "publication-review", "publication-review",
    ],
    "case-video-candidate": [
        "video",
        "video",
        "draft",
        "voice-review",
        "publication-review",
        "video",
        "video",
        "video",
        "video",
        "publication-review",
        "publication-review",
    ],
    "publication-feedback-review": ["feedback", "feedback"],
    "context-efficient-rework": ["video", "video", "video", "video", "video", "video"],
}

# A recipe names the logical adapter. This table binds it to the existing registered
# owner (or to a repository-local adapter) so a compact capsule cannot silently omit
# the local tool discovery information required at execution time.
REGISTERED_TOOL_OWNERS = {
    "content-creation-system": "content-creation-system",
    "content-studio-poc": "content-creation-system",
    "case-video-script-adapter": "content-creation-system",
    "human-voice-gate": "content-creation-system",
    "content-packaging-review": "content-creation-system",
    "mvp-video-pipeline": "mvp-video-pipeline",
    "video-knowledge-pipeline": "video-knowledge-pipeline",
    "local-tools": "question-research-poc",
    "question-research-poc": "question-research-poc",
}
LOCAL_CONSUMER_COMMANDS = {
    "content-studio-poc": "python scripts/context_manifest_consumer.py --handoff <handoff.json>",
    "mvp-video-pipeline": "python scripts/context_manifest_consumer.py plan-review --handoff <handoff.json> --review-manifest <review-input.json> --output <plan.json>",
    "video-knowledge-pipeline": "python scripts/context_manifest_consumer.py decide-asr --handoff <handoff.json> --audio <audio> --output <asr-decision.json>",
}
INTERNAL_TOOL_SOURCES = {
    "canonical-routing": "scripts/canonical_routing.py",
    "self-media-contract-check": "scripts/check_self_media_contracts.py",
    "publication-feedback-tracker": "scripts/publication_feedback_tracker.py",
    "content-operations-cycle": "scripts/content_operations_cycle.py",
    "content-packaging-review": "scripts/content_packaging_review.py",
    "artifact-lifecycle": "scripts/artifact_lifecycle.py",
    "context-efficiency": "scripts/context_efficiency.py",
    "video-privacy-treatment": "scripts/video_privacy_treatment.py",
    "production-run-lock": "scripts/production_run_lock.py",
    "privacy-redaction-binding": "scripts/privacy_redaction_binding.py",
    "topic-angle-decision": "scripts/topic_angle_decision.py",
    "story-five-question-adapter": "scripts/story_five_question_adapter.py",
    "video-timing": "scripts/short_video_timing_evidence.py",
    "publication-desk": "scripts/publication_desk.py",
    "author-writing-context": "scripts/author_writing_context.py",
    "author-expression-store": "scripts/author_expression_store.py",
}
HUMAN_ONLY_TOOLS = {
    "package-human-review-gate",
    "manual-publication-boundary",
    "signal-review-gate",
    "manual-qa-boundary",
    "subject-privacy-treatment-gate",
    "customer-video-effect-gate",
    "prepublication-privacy-gate",
    "editorial-angle-human-review-gate",
    "interview-guide-human-review",
}

RECIPE_FIXTURES = {
    "moments-short-post": FIXTURE_ROOT / "moments-short-post.request.json",
    "xhs-evidence-graphic": FIXTURE_ROOT / "xhs-evidence-graphic.request.json",
    "case-video-candidate": FIXTURE_ROOT / "case-video-candidate.request.json",
    "publication-feedback-review": FIXTURE_ROOT / "publication-feedback-review.request.json",
    "context-efficient-rework": FIXTURE_ROOT / "context-efficient-rework.request.json",
}

EXPECTED_BOUNDARIES = {
    "publication": "manual-only",
    "external_send": "not-authorized",
    "customer_contact": "not-authorized",
    "crm_write": "not-authorized",
    "knowledge_base_write": "not-authorized",
    "provider_call": "not-authorized-by-this-entry",
}

DIRECT_OPERATIONS = {
    "tool_id": "content-operations-cycle",
    "trigger": (
        "A human reports that content was scheduled or published, supplies platform metrics, "
        "reports a platform diagnostic or warning, or supplies a deidentified interaction, "
        "lead decision, experiment, resource, revenue, continuity, or security event."
    ),
    "discovery_command": "python scripts/self_media_agent.py operations",
    "owner_help_command": "python scripts/content_operations_cycle.py --help",
    "record_commands": {
        "publication": "python scripts/content_operations_cycle.py record-publication --store <private-store> --input <publication-input.json>",
        "publication_edit": "python scripts/content_operations_cycle.py record-publication-edit --store <private-store> --input <publication-edit-input.json>",
        "publication_delete": "python scripts/content_operations_cycle.py record-publication-delete --store <private-store> --input <publication-delete-input.json>",
        "publication_restore": "python scripts/content_operations_cycle.py record-publication-restore --store <private-store> --input <publication-restore-input.json>",
        "snapshot": "python scripts/content_operations_cycle.py record-snapshot --store <private-store> --input <snapshot-input.json>",
        "interaction": "python scripts/content_operations_cycle.py record-interaction --store <private-store> --input <interaction-input.json>",
        "lead_review": "python scripts/content_operations_cycle.py review-lead --store <private-store> --input <lead-review-input.json>",
        "experiment": "python scripts/content_operations_cycle.py record-experiment --store <private-store> --input <experiment-input.json>",
        "diagnostic": "python scripts/content_operations_cycle.py record-diagnostic --store <private-store> --input <diagnostic-input.json>",
        "resource": "python scripts/content_operations_cycle.py record-resource --store <private-store> --input <resource-input.json>",
        "revenue": "python scripts/content_operations_cycle.py record-revenue --store <private-store> --input <revenue-input.json>",
        "continuity": "python scripts/content_operations_cycle.py record-continuity --store <private-store> --input <continuity-input.json>",
        "security": "python scripts/content_operations_cycle.py record-security --store <private-store> --input <security-input.json>",
    },
    "validation_command": "python scripts/content_operations_cycle.py validate-store --store <private-store>",
    "scheduled_content_policy": (
        "A human-reported scheduled date or time is not a publication event. Record it in "
        "the current platform publication package or publishing calendar, preserve date-only "
        "evidence when the exact time was not supplied, and call record-publication only after "
        "the item is live."
    ),
    "scheduled_record_route": (
        "platform-publication-package schedule confirmation; do not invent an exact time, "
        "platform-level confirmation, or published status"
    ),
    "canonical_snapshot_windows_hours": {
        "early": [48, 72],
        "d7": [156, 180],
    },
    "interim_observation_policy": (
        "Metrics reported before 48 hours are provisional evidence. Record the publication "
        "event immediately, do not mislabel the metrics as early or d7, and return the next "
        "eligible capture window plus any missing governed-input requirements."
    ),
    "review_route": (
        "Use workflow_goal=publication_feedback_review only after the append-only operations "
        "store exists and the human requests a six-layer review."
    ),
    "boundaries": {
        "manual_entry_only": True,
        "opens_platform": False,
        "publishes": False,
        "contacts_customer": False,
        "writes_crm": False,
    },
}


class AgentEntryError(ValueError):
    """A stable, fail-closed error from the metadata-only Agent entry."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def load_json(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, json.JSONDecodeError) as error:
        raise AgentEntryError("artifact_unreadable", f"{path.name}: {error}") from error
    if not isinstance(value, dict):
        raise AgentEntryError("schema_validation_failed", f"{path.name} must contain a JSON object")
    return value


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_value(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def schema_errors(document: Any, schema: dict[str, Any], label: str) -> list[str]:
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    return [
        f"{label}: {'.'.join(str(part) for part in error.path) or '$'}: {error.message}"
        for error in sorted(validator.iter_errors(document), key=lambda item: list(item.path))
    ]


def validate_document(document: Any, schema_path: Path, label: str) -> None:
    schema = load_json(schema_path)
    try:
        Draft202012Validator.check_schema(schema)
    except Exception as error:
        raise AgentEntryError("schema_invalid", f"{schema_path.name}: {error}") from error
    errors = schema_errors(document, schema, label)
    if errors:
        raise AgentEntryError("schema_validation_failed", "; ".join(errors))


def load_canonical_routing() -> dict[str, Any]:
    spec = importlib.util.spec_from_file_location("self_media_canonical_routing", CANONICAL_ROUTING_PATH)
    if not spec or not spec.loader:
        raise AgentEntryError("canonical_route_missing", "canonical routing loader cannot be imported")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    try:
        return module.load_contracts()
    except Exception as error:
        raise AgentEntryError("canonical_route_missing", str(error)) from error


def _load_context_efficiency():
    spec = importlib.util.spec_from_file_location("self_media_context_efficiency", CONTEXT_EFFICIENCY_PATH)
    if not spec or not spec.loader:
        raise AgentEntryError("context_contract_missing", "context efficiency loader cannot be imported")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_author_writing_context():
    """Load the existing writing adapter without giving the entry write authority."""
    spec = importlib.util.spec_from_file_location("self_media_author_writing_context", AUTHOR_WRITING_CONTEXT_PATH)
    if not spec or not spec.loader:
        raise AgentEntryError("author_context_unavailable", str(AUTHOR_WRITING_CONTEXT_PATH))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except (OSError, ImportError) as error:
        raise AgentEntryError("author_context_unavailable", str(error)) from error
    return module


def _validate_author_context(manifest_path: Path, capsule: dict[str, Any], step: dict[str, Any], historical: bool = False) -> None:
    try:
        _load_author_writing_context().validate_context_manifest(manifest_path, capsule, step, historical=historical)
    except AgentEntryError:
        raise
    except Exception as error:
        raise AgentEntryError(getattr(error, "code", "author_context_invalid"), str(error)) from error


def _validate_framework_context(manifest_path: Path, step: dict[str, Any]) -> None:
    """Consume the editorial decision before drafting; receipt presence is insufficient."""
    stage_by_step = {
        "draft-one-observation": "draft", "build-evidence-draft": "draft",
        "project-case-script": "draft", "discover-research-owner": "research",
        "produce-verified-research-output": "research",
    }
    if step["step_id"] not in stage_by_step:
        return
    manifest = load_json(manifest_path)
    refs = [a for a in manifest["artifacts"] if a.get("source_role") in {
        "topic-angle-decision", "topic-angle-decision-if-upstream-selected"}]
    if not refs and step["step_id"] == "project-case-script":
        return  # Existing case-only routes retain their explicitly conditional applicability.
    if len(refs) != 1:
        raise AgentEntryError("framework_decision_required", "one current v2 framework decision is required before this step")
    spec = importlib.util.spec_from_file_location("self_media_framework_gate", ROOT / "scripts/topic_angle_decision.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    path = (manifest_path.parent / refs[0]["path"]).resolve()
    if refs[0].get("expected_sha256") and sha256_file(path) != refs[0]["expected_sha256"]:
        raise AgentEntryError("framework_receipt_drift", refs[0]["path"])
    try:
        result = module.continuation(load_json(path), stage=stage_by_step[step["step_id"]])
    except Exception as error:
        raise AgentEntryError(getattr(error, "code", "framework_decision_invalid"), str(error)) from error
    if not result["may_continue"]:
        raise AgentEntryError("framework_return_required", json.dumps(result, ensure_ascii=False))


def _load_creation_route():
    spec = importlib.util.spec_from_file_location("self_media_creation_route", ROOT / "scripts/creation_route.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _validate_creation_context(manifest_path: Path, capsule: dict[str, Any], step: dict[str, Any]):
    try:
        return _load_creation_route().check_manifest(manifest_path, capsule["request_id"], step,
            require_selection=capsule.get("creation_phase") == "prerecording")
    except Exception as error:
        raise AgentEntryError(getattr(error, "code", "creation_route_invalid"), str(error)) from error


def _purpose_context(manifest_path, capsule, step, *, historical=False):
    import purpose_continuity
    try:
        return purpose_continuity.validate_context(manifest_path, capsule['request_id'],
            required=purpose_continuity.requires_context(step) and not historical, historical=historical)
    except purpose_continuity.PurposeError as error:
        raise AgentEntryError(error.code, str(error)) from error


def _execution_brief(full_step: dict[str, Any], decision: dict[str, Any] | None, purpose=None) -> dict[str, Any]:
    instruction = full_step["instruction"]
    authoring = _load_author_writing_context()
    if full_step["step_id"] in authoring.WRITING_STEPS | authoring.REVIEW_STEPS:
        instruction += "\nFollow docs/editorial-execution-integrity.md; preserve preparation, feedback/issues and author approval."
        instruction += (
            "\nRead structure-route-playbook.md#观众路径: reach, trust and action in existing checks; "
            "no mandatory acquisition CTA."
        )
    if decision:
        if decision["primary_route"] != "story":
            instruction = instruction.replace("fact-card and storycraft Skills", "fact-card and selected-route methods")
        instruction += (
            f"\nRoute={decision['primary_route']}; read {decision['guide']}; "
            f"story-design={decision['story_design_applicability']}; selected route only."
        )
    result = {"instruction": instruction, "command": full_step.get("command"), "stop_on_error": True}
    if purpose is not None:
        result['purpose_context'] = purpose
    return result


def _tool_descriptor(tool_id: str, *, detailed: bool) -> dict[str, Any]:
    if tool_id in HUMAN_ONLY_TOOLS:
        return {
            "tool_id": tool_id,
            "discovery_mode": "human_gate",
            "execution_authority": "human-only",
        }
    internal = INTERNAL_TOOL_SOURCES.get(tool_id)
    if internal:
        source = ROOT / internal
        if not source.is_file():
            raise AgentEntryError("tool_discovery_missing", f"internal tool source missing: {tool_id}")
        descriptor = {
            "tool_id": tool_id,
            "discovery_mode": "repository_internal",
            "execution_authority": "bounded-local-only",
        }
        if detailed:
            descriptor["source_ref"] = {"path": internal, "sha256": sha256_file(source)}
        return descriptor
    registry_id = REGISTERED_TOOL_OWNERS.get(tool_id)
    if not registry_id:
        raise AgentEntryError("tool_discovery_missing", f"tool has no registered or internal owner: {tool_id}")
    registry = load_json(TOOL_REGISTRY_PATH)
    entry = (registry.get("tools") or {}).get(registry_id)
    if not isinstance(entry, dict):
        raise AgentEntryError("tool_discovery_missing", f"registered tool is missing: {registry_id}")
    descriptor = {
        "tool_id": tool_id,
        "discovery_mode": "registered_owner",
        "registry_tool_id": registry_id,
        "execution_authority": "existing-owner-boundary",
    }
    if detailed:
        discovery = Path(str(entry.get("discovery_markdown") or ""))
        if not discovery.is_file():
            raise AgentEntryError("tool_discovery_missing", f"discovery document is missing: {registry_id}")
        descriptor.update(
            {
                "registry_entry_sha256": sha256_value(entry),
                "discovery_ref": {
                    "symbol": f"tool-registry://{registry_id}/AGENT_DISCOVERY",
                    "sha256": sha256_file(discovery),
                },
                "discovery_command": f"python ../tools/public_toolchain.py discover {registry_id}",
                "preferred_interfaces": sorted(entry.get("preferred_interfaces") or []),
                "command_names": sorted((entry.get("commands") or {}).keys()),
                "boundary_summary": list(entry.get("avoid_or_boundary") or [])[:4],
            }
        )
        if tool_id in LOCAL_CONSUMER_COMMANDS:
            descriptor["consumer_command"] = LOCAL_CONSUMER_COMMANDS[tool_id]
    return descriptor


def validate_manifest() -> dict[str, Any]:
    manifest = load_json(MANIFEST_PATH)
    validate_document(manifest, MANIFEST_SCHEMA_PATH, "agent_tool_manifest")
    if manifest["executionAuthority"] != "none_metadata_only":
        raise AgentEntryError("boundary_drift", "Agent entry execution authority drifted")
    return manifest


def load_catalog() -> dict[str, Any]:
    catalog = load_json(CATALOG_PATH)
    validate_document(catalog, CATALOG_SCHEMA_PATH, "recipe_catalog")
    if catalog["boundaries"] != EXPECTED_BOUNDARIES:
        raise AgentEntryError("boundary_drift", "recipe catalog boundaries drifted")
    recipes = catalog["recipes"]
    recipe_ids = [recipe["recipe_id"] for recipe in recipes]
    goals = [recipe["workflow_goal"] for recipe in recipes]
    if len(set(recipe_ids)) != len(recipe_ids) or len(set(goals)) != len(goals):
        raise AgentEntryError("recipe_catalog_invalid", "recipe ids and workflow goals must be unique")
    if set(recipe_ids) != set(RECIPE_FIXTURES):
        raise AgentEntryError("recipe_catalog_invalid", "the catalog must expose exactly the five supported recipes")
    policy = catalog.get("route_execution_policy") or {}
    if policy != {
        "mode": "selected-recipe-subset-only",
        "canonical_order_is_universal_checklist": False,
        "skip_reason_required": True,
        "unknown_applicability": "fail-closed",
    }:
        raise AgentEntryError("recipe_catalog_invalid", "route execution must use only the applicable recipe subset")
    for recipe in recipes:
        if recipe["steps"][-1]["interface"] != "human_gate":
            raise AgentEntryError("boundary_drift", f"{recipe['recipe_id']} must end at a human gate")
        for step in recipe["steps"]:
            if step["interface"] != "cli":
                continue
            command = step["command"]
            lowered = f" {command.lower()} "
            if any(token in lowered for token in (" publish ", " upload ", " send ", " post ")):
                raise AgentEntryError("boundary_drift", f"{recipe['recipe_id']} contains an external-action command")
            if any(token in command for token in (";", "&&", "||", "|", "\n", "\r")):
                raise AgentEntryError("boundary_drift", f"{recipe['recipe_id']} contains a chained command")
    authoring = _load_author_writing_context()
    for recipe in recipes:
        preparation = recipe.get("prerecording") or {}
        all_steps = recipe["steps"] + preparation.get("steps", []) + preparation.get("interview_steps", [])
        for step in all_steps:
            author_roles = set()
            if step["step_id"] in authoring.WRITING_STEPS | authoring.REVIEW_STEPS:
                author_roles.add("author-writing-context")
            if step["step_id"] in authoring.REVIEW_STEPS:
                author_roles.add("author-revision-review")
            if not author_roles.issubset(step["input_roles"]):
                raise AgentEntryError("author_route_incomplete", step["step_id"])
            if step["step_id"] in authoring.WRITING_STEPS and "author-writing-revision.v1" not in step["output_contract"].split("+"):
                raise AgentEntryError("author_route_incomplete", step["step_id"])
    feedback = next(item for item in recipes if item["recipe_id"] == "publication-feedback-review")
    if len(feedback["steps"]) != 2:
        raise AgentEntryError(
            "recipe_catalog_invalid",
            "publication feedback must have one CLI step and one human gate",
        )
    first, final = feedback["steps"]
    if first["interface"] != "cli" or first["tool_id"] != "content-operations-cycle":
        raise AgentEntryError(
            "recipe_catalog_invalid",
            "publication feedback must use the content operations cycle",
        )
    if final["interface"] != "human_gate":
        raise AgentEntryError("boundary_drift", "publication feedback must end at a human gate")
    if any(step["tool_id"] == "publication-feedback-tracker" for step in feedback["steps"]):
        raise AgentEntryError(
            "recipe_catalog_invalid",
            "the legacy publication tracker is regression-only, not the primary recipe",
        )
    graphic = next(item for item in recipes if item["recipe_id"] == "xhs-evidence-graphic")
    graphic_steps = {step["step_id"]: step for step in graphic["steps"]}
    graphic_order = [step["step_id"] for step in graphic["steps"]]
    required_graphic_order = [
        "discover-research-owner",
        "produce-verified-research-output",
        "build-evidence-draft",
    ]
    if any(step not in graphic_order for step in required_graphic_order) or [
        graphic_order.index(step) for step in required_graphic_order
    ] != sorted(graphic_order.index(step) for step in required_graphic_order):
        raise AgentEntryError("recipe_catalog_invalid", "xhs evidence drafting must follow verified research execution")
    research_step = graphic_steps["produce-verified-research-output"]
    if research_step["tool_id"] != "question-research-poc" or research_step["output_contract"] != "research-output.v1":
        raise AgentEntryError("recipe_catalog_invalid", "xhs research must use the registered research-output.v1 owner")
    case_video = next(item for item in recipes if item["recipe_id"] == "case-video-candidate")
    expected_case_steps = [
        "verify-production-run-lock",
        "capture-initial-privacy-treatment",
        "project-case-script",
        "complete-human-voice-gate",
        "verify-case-audience-path",
        "handoff-video-owner",
        "final-timing",
        "verify-privacy-redaction-binding",
        "record-customer-video-effect-review",
        "evaluate-prepublication-privacy",
        "confirm-manual-publication-or-rework",
    ]
    if [step["step_id"] for step in case_video["steps"]] != expected_case_steps:
        raise AgentEntryError(
            "recipe_catalog_invalid",
            "case video must preserve the initial treatment, customer review, and prepublication gate order",
        )
    case_steps_by_id = {step["step_id"]: step for step in case_video["steps"]}
    human_voice = case_steps_by_id["complete-human-voice-gate"]
    audience_path = case_steps_by_id["verify-case-audience-path"]
    if (
        human_voice["interface"] != "human_gate"
        or human_voice["tool_id"] != "human-voice-gate"
        or audience_path["interface"] != "cli"
        or audience_path["tool_id"] != "content-packaging-review"
    ):
        raise AgentEntryError(
            "recipe_catalog_invalid",
            "case video audience-path approval must precede the packaging validator",
        )
    final_timing = case_steps_by_id["final-timing"]
    if final_timing["interface"] != "cli" or final_timing["tool_id"] != "video-timing":
        raise AgentEntryError("recipe_catalog_invalid", "case video final cut must pass measured timing evidence")
    if expected_case_steps.index("handoff-video-owner") > expected_case_steps.index("final-timing"):
        raise AgentEntryError("recipe_catalog_invalid", "final-cut timing cannot run before a video candidate exists")
    if case_steps_by_id["evaluate-prepublication-privacy"]["tool_id"] != "video-privacy-treatment":
        raise AgentEntryError(
            "recipe_catalog_invalid",
            "case video prepublication evaluation must use the local privacy-treatment evaluator",
        )
    interview_steps = (case_video.get("prerecording") or {}).get("interview_steps") or []
    if len(interview_steps) != 2 or interview_steps[-1].get("tool_id") != "interview-guide-human-review":
        raise AgentEntryError("recipe_catalog_invalid", "interview guide review must use its dedicated human review gate")
    prerecord_steps = (case_video.get("prerecording") or {}).get("steps") or []
    if not prerecord_steps or prerecord_steps[-1].get("step_id") != "verify-prerecord-timing":
        raise AgentEntryError("recipe_catalog_invalid", "spoken prerecording must end with observed read-aloud timing evidence")
    return catalog


def validate_input_refs(request: dict[str, Any]) -> None:
    available = set(request["available_inputs"])
    seen_roles: set[str] = set()
    root = ROOT.resolve()
    for ref in request["input_refs"]:
        role = ref["role"]
        if role not in available:
            raise AgentEntryError("input_ref_unbound", f"input ref role is not listed as available: {role}")
        if role in seen_roles:
            raise AgentEntryError("input_ref_duplicate", f"duplicate input ref role: {role}")
        seen_roles.add(role)
        target = (ROOT / ref["path"]).resolve()
        try:
            target.relative_to(root)
        except ValueError as error:
            raise AgentEntryError("input_ref_outside_repository", f"input ref escaped repository: {role}") from error
        if not target.is_file():
            raise AgentEntryError("artifact_unreadable", f"input ref is missing: {role}")
        if sha256_file(target) != ref["sha256"]:
            raise AgentEntryError("source_hash_drift", f"input ref hash drifted: {role}")


def validate_request(request: dict[str, Any]) -> None:
    validate_document(request, REQUEST_SCHEMA_PATH, "agent_request")
    if request.get("creation_phase") == "prerecording" and request["workflow_goal"] != "case_video_candidate":
        raise AgentEntryError("creation_phase_mismatch", "prerecording is a phase of case_video_candidate, not a sixth goal")
    if request.get("preparation_kind") and request.get("creation_phase") != "prerecording":
        raise AgentEntryError("creation_phase_mismatch", "preparation_kind requires prerecording")
    expected_genre = {
        "moments_short_post": "moments",
        "xhs_evidence_graphic": "graphic_note",
        "case_video_candidate": request.get("preparation_kind", "spoken_script") if request.get("creation_phase") == "prerecording" else "spoken_script",
    }.get(request["workflow_goal"])
    if expected_genre is not None and request["author_identity"]["genre"] != expected_genre:
        raise AgentEntryError("author_genre_mismatch", f"this workflow requires genre={expected_genre}")
    validate_input_refs(request)


def _recipe_for_goal(catalog: dict[str, Any], goal: str, phase: str = "production", kind: str = "spoken_script") -> dict[str, Any]:
    matches = [recipe for recipe in catalog["recipes"] if recipe["workflow_goal"] == goal]
    if len(matches) != 1:
        raise AgentEntryError("workflow_goal_unresolved", f"workflow goal must resolve to exactly one recipe: {goal}")
    recipe = copy.deepcopy(matches[0])
    if phase == "prerecording":
        if "prerecording" not in recipe:
            raise AgentEntryError("creation_phase_mismatch", goal)
        recipe.update(recipe["prerecording"])
        if kind == "interview_guide":
            recipe["steps"] = recipe["interview_steps"]
            recipe["outputs"] = ["case-interview-guide.v1", "case-interview-guide-review.v1"]
        recipe["quality_gates"] = ["draft_only", "fact-unknowns-preserved", "no-invented-interview-answer", "editorial-review", "no-recording-required-for-writing", "manual-publication"]
        recipe["stop_conditions"] = ["draft-ready-for-review", "review-pending", "no-publication-authority"]
    return recipe


def _capsule_recipe(catalog: dict[str, Any], capsule: dict[str, Any]) -> dict[str, Any]:
    base = next(item for item in catalog["recipes"] if item["recipe_id"] == capsule["recipe_id"])
    return _recipe_for_goal(catalog, base["workflow_goal"], capsule.get("creation_phase", "production"), capsule.get("preparation_kind", "spoken_script"))


def _capsule_payload(request: dict[str, Any], catalog: dict[str, Any], recipe: dict[str, Any], canonical_version: str) -> dict[str, Any]:
    required = sorted(recipe["required_initial_inputs"])
    provided = sorted(request["available_inputs"])
    missing = sorted(set(required) - set(provided))
    request_sha = sha256_value(request)
    capsule_seed = sha256_value({"request_sha256": request_sha, "recipe_id": recipe["recipe_id"]})
    stages = STEP_CONTEXT_STAGES.get(recipe["recipe_id"])
    if request.get("creation_phase") == "prerecording":
        stages = ["draft", "draft"] if request.get("preparation_kind") == "interview_guide" else ["draft", "draft", "voice-review", "voice-review"]
    if not stages or len(stages) != len(recipe["steps"]):
        raise AgentEntryError("recipe_catalog_invalid", f"context stages are incomplete: {recipe['recipe_id']}")
    step_index = []
    tool_index = []
    for step, stage in zip(recipe["steps"], stages):
        step_index.append(
            {
                "step_id": step["step_id"],
                "interface": step["interface"],
                "tool_id": step["tool_id"],
                "context_stage": stage,
                "input_roles": sorted(step["input_roles"]),
                "output_contract": step["output_contract"],
                "stop_on_error": True,
                "handoff_required": True,
                "output_receipt_required": True,
            }
        )
        tool_index.append({"step_id": step["step_id"], **_tool_descriptor(step["tool_id"], detailed=False)})
    capsule: dict[str, Any] = {
        "schema_version": "self-media-task-capsule.v2",
        "capsule_id": f"capsule-{capsule_seed[:16]}",
        "request_id": request["request_id"],
        "status": "blocked_missing_inputs" if missing else "routing_ready",
        "recipe_id": recipe["recipe_id"],
        "creation_phase": request.get("creation_phase", "production"),
        "canonical_route": {
            "contract_set_id": "registered-content-routing",
            "contract_set_version": canonical_version,
            "load_policy": "whole-contract-set-only",
            "legacy_fallback": False,
        },
        "recipe_detail_ref": {
            "path": "recipes/self-media-recipes.v1.json",
            "sha256": sha256_file(CATALOG_PATH),
        },
        "required_inputs": required,
        "provided_inputs": provided,
        "missing_inputs": missing,
        "context_loading": {
            "always_load": sorted(recipe["always_load"]),
            "on_demand": sorted(recipe["on_demand"]),
            "never_inline": sorted(recipe["never_inline"]),
            "capsule_max_bytes": catalog["context_defaults"]["capsule_max_bytes"],
            "tool_receipt_max_bytes": catalog["context_defaults"]["tool_receipt_max_bytes"],
            "handoff_required": True,
        },
        "route_application": {
            "mode": catalog["route_execution_policy"]["mode"],
            "canonical_order_is_universal_checklist": False,
            "applicable_steps": [step["step_id"] for step in recipe["steps"]],
            "skipped_steps": [],
            "skip_reason_required": True,
            "unknown_applicability": "fail-closed",
        },
        "step_index": step_index,
        "tool_index": tool_index,
        "quality_gates": sorted(recipe["quality_gates"]),
        "outputs": sorted(recipe["outputs"]),
        "stop_conditions": sorted(recipe["stop_conditions"]),
        "boundaries": copy.deepcopy(catalog["boundaries"]),
        "recovery_codes": sorted(catalog["error_catalog"]),
        "provenance": {
            "request_sha256": request_sha,
            "recipe_catalog_version": catalog["catalog_version"],
            "synthetic_only": request["synthetic_only"],
            "input_refs": copy.deepcopy(request["input_refs"]),
        },
    }
    if request.get("creation_phase") == "prerecording":
        capsule["preparation_kind"] = request.get("preparation_kind", "spoken_script")
    if "author_identity" in request:
        capsule["provenance"]["author_identity"] = copy.deepcopy(request["author_identity"])
    capsule["payload_sha256"] = sha256_value(capsule)
    return capsule


def resolve_request(request: dict[str, Any]) -> dict[str, Any]:
    if request.get('schema_version') == 'self-media-work-request.v1':
        import entry_selection
        from jsonschema.exceptions import ValidationError
        try:
            return entry_selection.resolve(request, SimpleNamespace(**globals()))
        except AgentEntryError:
            raise
        except (ValueError, OSError, KeyError, TypeError, ValidationError) as error:
            raise AgentEntryError(getattr(error,'code','entry_selection_invalid'),str(error)) from error
    validate_request(request)
    route = load_canonical_routing()
    catalog = load_catalog()
    recipe = _recipe_for_goal(catalog, request["workflow_goal"], request.get("creation_phase", "production"), request.get("preparation_kind", "spoken_script"))
    capsule = _capsule_payload(request, catalog, recipe, route["manifest"]["contract_set_version"])
    validate_document(capsule, CAPSULE_V2_SCHEMA_PATH, "task_capsule")
    encoded = canonical_bytes(capsule)
    maximum = catalog["context_defaults"]["capsule_max_bytes"]
    if len(encoded) > maximum:
        raise AgentEntryError("capsule_size_exceeded", f"task capsule is {len(encoded)} bytes; maximum is {maximum}")
    return capsule


def validate_capsule_hash(capsule: dict[str, Any]) -> bool:
    expected = capsule.get("payload_sha256")
    candidate = copy.deepcopy(capsule)
    candidate.pop("payload_sha256", None)
    return isinstance(expected, str) and expected == sha256_value(candidate)


def _relative_ref(owner: Path, target: Path) -> dict[str, str]:
    try:
        relative = target.resolve().relative_to(owner.parent.resolve()).as_posix()
    except ValueError as error:
        raise AgentEntryError("handoff_path_boundary", "handoff artifacts must share one run root") from error
    return {"path": relative, "sha256": sha256_file(target)}


def _load_valid_capsule(path: Path) -> dict[str, Any]:
    capsule = load_json(path)
    validate_document(capsule, CAPSULE_V2_SCHEMA_PATH, "task_capsule")
    if not validate_capsule_hash(capsule):
        raise AgentEntryError("capsule_hash_drift", "task capsule payload hash drifted")
    if capsule["status"] != "routing_ready":
        raise AgentEntryError("capsule_not_ready", "task capsule is not ready for a step handoff")
    if capsule["recipe_detail_ref"]["sha256"] != sha256_file(CATALOG_PATH):
        raise AgentEntryError("recipe_detail_drift", "recipe detail hash drifted")
    if capsule["canonical_route"]["contract_set_version"] != load_canonical_routing()["manifest"]["contract_set_version"]:
        raise AgentEntryError("canonical_route_version_drift", "re-resolve the capsule against the current registered contract set")
    return capsule


def _prerecord_method_sources(creation_route: str = "expository", preparation_kind: str | None = None) -> list[dict[str, str]]:
    """Expose canonical method inputs, not a claim that an Agent has read them."""
    workspace = ROOT.parent.resolve()
    registry_path = workspace / "docs/content-creation-system/routing/skill-registry.json"
    rows = {row["id"]: row for row in load_json(registry_path)["skills"]}
    sources = []
    source_ids = ["local-content-fact-card"]
    if creation_route == "story":
        source_ids.append("local-insurance-storycraft")
    for source_id in source_ids:
        loader = rows[source_id]["loader"]
        target = (registry_path.parent / loader["skill_path"]).resolve()
        try:
            target.relative_to(workspace)
        except ValueError as error:
            # Registered runtime uses a skills junction. Preserve its workspace
            # alias, while admitting only descendants of that exact skill root.
            skill_root = (workspace / "skills").resolve()
            if not target.is_relative_to(skill_root):
                raise AgentEntryError("method_source_outside_workspace", source_id) from error
            target = workspace / "skills" / target.relative_to(skill_root)
        if not target.is_file():
            raise AgentEntryError("method_source_missing", source_id)
        normalized = hashlib.sha256(target.read_text(encoding="utf-8").replace("\r\n", "\n").encode("utf-8")).hexdigest()
        if loader["skill_sha256"] not in {sha256_file(target), normalized}:
            raise AgentEntryError("method_source_drift", source_id)
        sources.append((source_id, target))
    if preparation_kind == "interview_guide":
        target = ROOT / "skills/material-interview/SKILL.md"
        if not target.is_file():
            raise AgentEntryError("method_source_missing", "material-interview")
        sources.append(("material-interview", target))
    if creation_route != "story":
        sources.append(("selected-creation-route", ROOT / "structure-route-playbook.md"))
    sources += [
        ("skill-invocation-runbook", registry_path.parent / "skill-invocation-runbook.md"),
        ("human-voice-editor", workspace / "skills/human-voice-editor/SKILL.md"),
    ]
    return [{"source_id": source_id, "workspace_relative_path": target.relative_to(workspace).as_posix(),
             "sha256": sha256_file(target), "load_policy": "read_full_before_task; follow_referenced_instruction_routing"}
            for source_id, target in sources]


def prepare_step_handoff(
    capsule_path: Path,
    step_id: str,
    context_manifest_path: Path,
    context_receipt_path: Path,
    output: Path,
    previous_receipt: Path | None = None,
    inspection_only: bool = False,
) -> dict[str, Any]:
    capsule = _load_valid_capsule(capsule_path)
    matches = [item for item in capsule["step_index"] if item["step_id"] == step_id]
    if len(matches) != 1:
        raise AgentEntryError("step_unresolved", f"step is not present in capsule: {step_id}")
    step = matches[0]
    manifest = load_json(context_manifest_path)
    validate_document(manifest, CONTEXT_MANIFEST_SCHEMA_PATH, "context_manifest")
    if manifest["task_id"] != capsule["request_id"] or manifest["stage"] != step["context_stage"]:
        raise AgentEntryError("context_identity_drift", "context task or stage does not match the capsule step")
    source_roles = sorted(
        {
            str(item.get("source_role") or "").strip()
            for item in manifest["artifacts"]
            if str(item.get("source_role") or "").strip()
        }
    )
    if len(source_roles) != len(manifest["artifacts"]):
        raise AgentEntryError(
            "context_source_role_missing",
            "every step artifact must declare its recipe input role in source_role",
        )
    missing = sorted(set(step["input_roles"]) - set(source_roles))
    if missing:
        raise AgentEntryError("context_roles_missing", ",".join(missing))
    if not inspection_only:
        creation_decision = _validate_creation_context(context_manifest_path, capsule, step)
        _validate_framework_context(context_manifest_path, step)
        _validate_author_context(context_manifest_path, capsule, step)
    else:
        creation_decision = None
    if step_id == "confirm-manual-publication-or-rework" and not inspection_only:
        _validate_release_timing_inputs(context_manifest_path)
    if previous_receipt:
        _relative_ref(output, previous_receipt)
    if not inspection_only:
        _validate_previous_step(capsule, step_id, previous_receipt)
    purpose = _purpose_context(context_manifest_path, capsule, step) if not inspection_only else None
    if previous_receipt and purpose is not None:
        import purpose_continuity
        prior_handoff = load_json(_receipt_handoff_path(previous_receipt))
        try:
            purpose_continuity.check_transition(prior_handoff['execution_brief'].get('purpose_context'), purpose)
        except purpose_continuity.PurposeError as error:
            raise AgentEntryError(error.code, str(error)) from error
    shared = _load_context_efficiency()
    try:
        context_receipt = shared.build_context_pack(context_manifest_path, context_receipt_path)
    except Exception as error:
        raise AgentEntryError("context_receipt_failed", str(error)) from error
    if context_receipt.get("status") != "ready":
        raise AgentEntryError("context_receipt_failed", "context receipt is not ready")
    tool_contract = _tool_descriptor(step["tool_id"], detailed=True)
    catalog = load_catalog()
    recipe = _capsule_recipe(catalog, capsule)
    full_step = next(item for item in recipe["steps"] if item["step_id"] == step_id)
    execution_brief = _execution_brief(full_step, creation_decision, purpose)
    seed = sha256_value(
        {
            "capsule": capsule["payload_sha256"],
            "step_id": step_id,
            "manifest": sha256_file(context_manifest_path),
            "receipt": sha256_file(context_receipt_path),
            "tool": tool_contract,
            "execution_brief": execution_brief,
            "previous_receipt": sha256_file(previous_receipt) if previous_receipt else None,
            "inspection_only": inspection_only,
        }
    )
    handoff = {
        "schema_version": "self-media-step-handoff.v1",
        "handoff_id": f"handoff-{seed[:16]}",
        "status": "inspection_only" if inspection_only else "ready_for_existing_owner",
        "capsule": _relative_ref(output, capsule_path),
        "request_id": capsule["request_id"],
        "recipe_id": capsule["recipe_id"],
        "step": copy.deepcopy(step),
        "tool_contract": tool_contract,
        "execution_brief": execution_brief,
        "context": {
            "manifest": _relative_ref(output, context_manifest_path),
            "receipt": _relative_ref(output, context_receipt_path),
            "source_roles": source_roles,
            "missing_roles": [],
            "receipt_required_before_execution": True,
        },
        "boundaries": copy.deepcopy(capsule["boundaries"]),
    }
    if previous_receipt:
        handoff["previous_receipt"] = _relative_ref(output, previous_receipt)
    if capsule.get("creation_phase") == "prerecording":
        handoff["required_reading"] = _prerecord_method_sources(creation_decision["primary_route"] if creation_decision else "expository", capsule.get("preparation_kind"))
    handoff["payload_sha256"] = sha256_value(handoff)
    validate_document(handoff, HANDOFF_SCHEMA_PATH, "step_handoff")
    write_or_print(handoff, output)
    return handoff


def validate_step_handoff(path: Path, expected_tool_id: str | None = None, *, allow_inspection: bool = False, historical: bool = False) -> dict[str, Any]:
    handoff = load_json(path)
    validate_document(handoff, HANDOFF_SCHEMA_PATH, "step_handoff")
    if handoff["status"] == "inspection_only" and not allow_inspection:
        raise AgentEntryError("inspection_not_execution", "inspection handoff cannot authorize an owner step")
    candidate = copy.deepcopy(handoff)
    expected = candidate.pop("payload_sha256")
    if expected != sha256_value(candidate):
        raise AgentEntryError("handoff_hash_drift", "step handoff payload hash drifted")
    if expected_tool_id and handoff["step"]["tool_id"] != expected_tool_id:
        raise AgentEntryError("handoff_tool_mismatch", "step handoff targets another tool")
    for label, ref in (
        ("capsule", handoff["capsule"]),
        ("context_manifest", handoff["context"]["manifest"]),
        ("context_receipt", handoff["context"]["receipt"]),
    ):
        target = (path.parent / ref["path"]).resolve()
        try:
            target.relative_to(path.parent.resolve())
        except ValueError as error:
            raise AgentEntryError("handoff_path_boundary", label) from error
        if not target.is_file() or sha256_file(target) != ref["sha256"]:
            raise AgentEntryError("handoff_artifact_drift", label)
    shared = _load_context_efficiency()
    try:
        shared.validate_context_pack(
            (path.parent / handoff["context"]["manifest"]["path"]).resolve(),
            (path.parent / handoff["context"]["receipt"]["path"]).resolve(),
        )
    except Exception as error:
        raise AgentEntryError("context_receipt_drift", f"context_receipt_drift: {error}") from error
    if handoff["status"] != "inspection_only" and handoff["step"]["step_id"] == "confirm-manual-publication-or-rework":
        _validate_release_timing_inputs((path.parent / handoff["context"]["manifest"]["path"]).resolve())
    capsule = _load_valid_capsule((path.parent / handoff["capsule"]["path"]).resolve())
    step = next((item for item in capsule["step_index"] if item["step_id"] == handoff["step"]["step_id"]), None)
    if step != handoff["step"] or capsule["request_id"] != handoff["request_id"]:
        raise AgentEntryError("handoff_capsule_drift", "handoff no longer matches its capsule")
    if handoff["status"] != "inspection_only":
        creation_decision = _validate_creation_context((path.parent / handoff["context"]["manifest"]["path"]).resolve(), capsule, step)
        _validate_framework_context((path.parent / handoff["context"]["manifest"]["path"]).resolve(), step)
        _validate_author_context((path.parent / handoff["context"]["manifest"]["path"]).resolve(), capsule, step, historical=historical)
    else:
        creation_decision = None
    if capsule.get("creation_phase") == "prerecording" and handoff.get("required_reading") != _prerecord_method_sources(creation_decision["primary_route"] if creation_decision else "expository", capsule.get("preparation_kind")):
        raise AgentEntryError("method_source_drift", "selected route Skill/runbook references are missing or stale")
    current_tool = _tool_descriptor(step["tool_id"], detailed=True)
    if current_tool != handoff["tool_contract"]:
        raise AgentEntryError("tool_discovery_drift", "registered/local tool discovery changed")
    catalog = load_catalog()
    recipe = _capsule_recipe(catalog, capsule)
    full_step = next(item for item in recipe["steps"] if item["step_id"] == step["step_id"])
    purpose = _purpose_context((path.parent / handoff['context']['manifest']['path']).resolve(), capsule, step,
                               historical=historical) if handoff['status'] != 'inspection_only' else None
    expected_brief = _execution_brief(full_step, creation_decision, purpose)
    if handoff["execution_brief"] != expected_brief:
        raise AgentEntryError("recipe_detail_drift", "step execution detail drifted")
    if handoff["status"] != "inspection_only":
        previous = handoff.get("previous_receipt")
        previous_path = (path.parent / previous["path"]).resolve() if previous else None
        if previous_path:
            _relative_ref(path, previous_path)
        if previous and (not previous_path.is_file() or sha256_file(previous_path) != previous["sha256"]):
            raise AgentEntryError("previous_receipt_drift", "previous step receipt changed")
        _validate_previous_step(capsule, step["step_id"], previous_path, historical=historical)
        if previous_path and purpose is not None:
            import purpose_continuity
            prior = load_json(_receipt_handoff_path(previous_path))
            try:
                purpose_continuity.check_transition(prior['execution_brief'].get('purpose_context'),purpose)
            except purpose_continuity.PurposeError as error:
                raise AgentEntryError(error.code,str(error)) from error
    return handoff


def _validate_previous_step(capsule: dict[str, Any], step_id: str, previous_path: Path | None, *, historical: bool = False) -> None:
    ids = [row["step_id"] for row in capsule["step_index"]]
    index = ids.index(step_id)
    if index == 0:
        if previous_path is not None:
            raise AgentEntryError("unexpected_previous_step", "first step has no predecessor")
        return
    if previous_path is None:
        raise AgentEntryError("previous_step_required", ids[index - 1])
    receipt = load_json(previous_path)
    validate_document(receipt, OUTPUT_RECEIPT_SCHEMA_PATH, "previous_receipt")
    if receipt.get("step_id") != ids[index - 1]:
        raise AgentEntryError("previous_step_order", "cannot skip or substitute a predecessor")
    prior_handoff = (previous_path.parent / receipt.get("handoff", {}).get("path", "")).resolve()
    try:
        prior_handoff.relative_to(previous_path.parent.resolve())
    except ValueError as error:
        raise AgentEntryError("handoff_path_boundary", "previous handoff escaped the run root") from error
    prior = load_json(prior_handoff)
    validate_document(prior, HANDOFF_SCHEMA_PATH, "previous_handoff")
    if prior.get("request_id") != capsule["request_id"] or prior.get("recipe_id") != capsule["recipe_id"]:
        raise AgentEntryError("previous_step_identity_drift", "receipt belongs to another task")
    prior_capsule_path = (prior_handoff.parent / prior["capsule"]["path"]).resolve()
    _relative_ref(prior_handoff, prior_capsule_path)
    if load_json(prior_capsule_path).get("payload_sha256") != capsule["payload_sha256"]:
        raise AgentEntryError("previous_step_identity_drift", "receipt belongs to another capsule revision")
    # Index equality above strictly decreases at each recursive call: no new lifecycle store.
    result = verify_step_output(prior_handoff, previous_path, historical=True)
    if not result["ok"]:
        raise AgentEntryError("previous_step_blocked", ids[index - 1])
    if not historical:
        # Historical chain membership is not permission to ignore newly received
        # feedback on the current draft. Find the closest writing/review receipt.
        probe_path, probe_handoff, probe_result = previous_path, prior, result
        while True:
            editorial = probe_result.get("editorial_integrity")
            if editorial is not None:
                if editorial["is_current_revision"]:
                    # The immutable chain has already been validated above. Only
                    # refresh mutable editorial evidence; do not recursively
                    # revalidate every ancestor a second time.
                    probe_receipt = load_json(probe_path)
                    probe_handoff_path = (probe_path.parent / probe_receipt["handoff"]["path"]).resolve()
                    try:
                        verified = _load_author_writing_context().validate_output_artifacts(
                            probe_handoff_path, probe_path, probe_handoff, probe_receipt, capsule)
                    except Exception as error:
                        raise AgentEntryError(getattr(error, "code", "editorial_invalid"), str(error)) from error
                    fields = ["records_complete", "checks_complete", "required_issues_closed", "preparation_complete", "observations_complete"]
                    fields.append('purpose_continuity_complete')
                    if probe_handoff["step"]["step_id"] in _load_author_writing_context().REVIEW_STEPS:
                        fields.append("author_confirmation_recorded")
                    if not all(verified[field] for field in fields):
                        raise AgentEntryError("previous_step_blocked", probe_handoff["step"]["step_id"])
                break
            ancestor = probe_handoff.get("previous_receipt")
            if not ancestor:
                break
            probe_path = (probe_path.parent / ancestor["path"]).resolve()
            ancestor_handoff = _receipt_handoff_path(probe_path)
            probe_handoff = load_json(ancestor_handoff)
            probe_result = verify_step_output(ancestor_handoff, probe_path, historical=True)


def _validate_research_output_artifact(path: Path) -> dict[str, Any]:
    if not QRP_RESEARCH_OUTPUT_SCHEMA_PATH.is_file():
        raise AgentEntryError("research_output_missing_or_blocked", "canonical research-output.v1 schema is unavailable")
    research = load_json(path)
    validate_document(research, QRP_RESEARCH_OUTPUT_SCHEMA_PATH, "research_output")
    completeness = research.get("completeness") or {}
    guarded = research.get("guarded_final_answer") or {}
    blockers = completeness.get("blocking_gates") or []
    if (
        completeness.get("ready_for_answer") is not True
        or blockers
        or guarded.get("status") != "verified"
        or guarded.get("ready") is not True
        or guarded.get("answer") is None
    ):
        raise AgentEntryError(
            "research_output_missing_or_blocked",
            "research output did not pass completeness and guarded-answer readiness",
        )
    return research


def _load_video_timing_module() -> Any:
    spec = importlib.util.spec_from_file_location(
        "short_video_timing_evidence_for_agent", ROOT / "scripts" / "short_video_timing_evidence.py"
    )
    assert spec and spec.loader
    timing = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(timing)
    return timing


def _validate_release_timing_inputs(manifest_path: Path) -> None:
    manifest = load_json(manifest_path)
    sources = {
        row["source_role"]: (manifest_path.parent / row["path"]).resolve()
        for row in manifest["artifacts"]
    }
    if "video-candidate" not in sources or "timing-evidence" not in sources:
        raise AgentEntryError("timing_evidence_missing", "release handoff requires exact video and timing evidence")
    timing = _load_video_timing_module()
    evidence = load_json(sources["timing-evidence"])
    try:
        timing.validate_receipt_value(evidence)
    except Exception as error:
        raise AgentEntryError(getattr(error, "code", "timing_evidence_invalid"), str(error)) from error
    if evidence["stage"] != "final-cut" or evidence["media_binding"] is None:
        raise AgentEntryError("stage_evidence_mismatch", "release requires final-cut timing evidence")
    if evidence["media_binding"]["sha256"] != sha256_file(sources["video-candidate"]):
        raise AgentEntryError("media_timing_revision_drift", "release candidate differs from final timing evidence")


def _validate_final_cut_timing_output(handoff_path: Path, receipt_path: Path, handoff: dict[str, Any], receipt: dict[str, Any]) -> None:
    matching = [ref for ref in receipt["outputs"] if ref["path"].lower().endswith(".json")]
    if len(matching) != 1:
        raise AgentEntryError("timing_evidence_missing", "exactly one JSON timing evidence receipt is required")
    timing = _load_video_timing_module()
    evidence_path = (receipt_path.parent / matching[0]["path"]).resolve()
    evidence = load_json(evidence_path)
    try:
        timing.validate_receipt_value(evidence)
    except Exception as error:
        raise AgentEntryError(getattr(error, "code", "timing_evidence_invalid"), str(error)) from error
    if evidence["stage"] != "final-cut" or evidence["media_binding"] is None:
        raise AgentEntryError("stage_evidence_mismatch", "production requires final-cut timing evidence")
    manifest_path = (handoff_path.parent / handoff["context"]["manifest"]["path"]).resolve()
    manifest = load_json(manifest_path)
    sources = {
        row["source_role"]: (manifest_path.parent / row["path"]).resolve()
        for row in manifest["artifacts"]
    }
    if evidence["script_binding"]["sha256"] != sha256_file(sources["case-video-script"]):
        raise AgentEntryError("script_timing_revision_drift", "final timing evidence uses another script revision")
    if evidence["media_binding"]["sha256"] != sha256_file(sources["video-candidate"]):
        raise AgentEntryError("media_timing_revision_drift", "final timing evidence uses another video candidate")
    if evidence["input_binding"]["sha256"] != sha256_file(sources["timing-input"]):
        raise AgentEntryError("timing_input_revision_drift", "final timing evidence uses another observation input")


def verify_step_output(handoff_path: Path, receipt_path: Path, *, historical: bool = False) -> dict[str, Any]:
    handoff = validate_step_handoff(handoff_path, historical=historical)
    receipt = load_json(receipt_path)
    validate_document(receipt, OUTPUT_RECEIPT_SCHEMA_PATH, "step_output_receipt")
    candidate = copy.deepcopy(receipt)
    expected = candidate.pop("payload_sha256")
    if expected != sha256_value(candidate):
        raise AgentEntryError("output_receipt_hash_drift", "step output receipt hash drifted")
    ref = receipt["handoff"]
    target = (receipt_path.parent / ref["path"]).resolve()
    if target != handoff_path.resolve() or not target.is_file() or sha256_file(target) != ref["sha256"]:
        raise AgentEntryError("output_receipt_handoff_drift", "output receipt is not bound to this handoff")
    for key in ("step_id", "tool_id", "output_contract"):
        if receipt[key] != handoff["step"][key]:
            raise AgentEntryError("output_receipt_step_drift", key)
    if receipt["boundaries"] != handoff["boundaries"]:
        raise AgentEntryError("boundary_drift", "output receipt changed the authority boundary")
    for ref in receipt["outputs"]:
        output = (receipt_path.parent / ref["path"]).resolve()
        try:
            output.relative_to(receipt_path.parent.resolve())
        except ValueError as error:
            raise AgentEntryError("handoff_path_boundary", "output") from error
        if not output.is_file() or sha256_file(output) != ref["sha256"]:
            raise AgentEntryError("output_artifact_drift", ref["path"])
        if output.stat().st_size == 0:
            raise AgentEntryError("output_artifact_empty", ref["path"])
    if receipt["status"] == "blocked":
        return {"ok": False, "status": "blocked", "handoff_id": handoff["handoff_id"]}
    expected_status = "human_gate_recorded" if handoff["step"]["interface"] == "human_gate" else "candidate_ready"
    if receipt["status"] != expected_status:
        raise AgentEntryError("output_status_mismatch", "human review cannot be substituted by a candidate status")
    capsule = load_json((handoff_path.parent / handoff["capsule"]["path"]).resolve())
    try:
        editorial = _load_author_writing_context().validate_output_artifacts(handoff_path, receipt_path, handoff, receipt, capsule, historical=historical)
    except AgentEntryError:
        raise
    except Exception as error:
        raise AgentEntryError(getattr(error, "code", "author_revision_invalid"), str(error)) from error
    if editorial is not None:
        required = ["records_complete", "checks_complete", "required_issues_closed", "preparation_complete", "observations_complete"]
        if not historical:
            required.append('purpose_continuity_complete')
        if handoff["step"]["step_id"] in _load_author_writing_context().REVIEW_STEPS:
            required.append("author_confirmation_recorded")
        if not all(editorial[field] for field in required):
            return {"ok": False, "status": "blocked", "handoff_id": handoff["handoff_id"],
                    "editorial_integrity": editorial, "proves_skill_execution_or_editorial_quality": False}
    purpose_review = None
    purpose_review_paths = set()
    if handoff['execution_brief'].get('purpose_context') is not None:
        import purpose_continuity
        output_paths = [(receipt_path.parent / ref['path']).resolve() for ref in receipt['outputs']]
        reviews = []
        for p in output_paths:
            if p.suffix.lower()=='.json' and p.stat().st_size<=2_000_000:
                value = load_json(p)
                if isinstance(value,dict) and value.get('schema_version')==purpose_continuity.REVIEW_SCHEMA:
                    reviews.append(p)
        if len(reviews)!=1:
            raise AgentEntryError('purpose_review_required','Exactly one stage review must anchor an actual output and current purpose/feedback')
        purpose_review_paths = set(reviews)
        try:
            check = purpose_continuity.validate_review((handoff_path.parent / handoff['context']['manifest']['path']).resolve(),reviews[0],output_paths,historical=historical)
        except purpose_continuity.PurposeError as error:
            raise AgentEntryError(error.code,str(error)) from error
        if not check['may_continue']:
            return {'ok':False,'status':'blocked','handoff_id':handoff['handoff_id'],'purpose_review':check}
        purpose_review = check
    scope = "transport_and_sequence_only"
    workflow_step_completed = False
    completion_claim = "handoff-validated-owner-semantics-unverified"
    if handoff["step"]["step_id"] == "produce-verified-research-output":
        matching = [ref for ref in receipt["outputs"] if ref["path"].lower().endswith(".json")
                    and (receipt_path.parent / ref['path']).resolve() not in purpose_review_paths]
        if len(matching) != 1:
            raise AgentEntryError("research_output_missing_or_blocked", "exactly one JSON research output is required")
        _validate_research_output_artifact((receipt_path.parent / matching[0]["path"]).resolve())
        scope = "research_output_schema_and_answer_readiness"
        workflow_step_completed = True
        completion_claim = "verified-research-output-admitted"
    if handoff["step"]["step_id"] == "final-timing":
        _validate_final_cut_timing_output(handoff_path, receipt_path, handoff, receipt)
        scope = "final_cut_timing_schema_hash_and_observed_thresholds"
        workflow_step_completed = True
        completion_claim = "final-cut-timing-evidence-validated"
    if capsule.get("creation_phase") == "prerecording":
        spec = importlib.util.spec_from_file_location("prerecording_validation", ROOT / "scripts/prerecording_validation.py")
        adapter = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(adapter)
        contract_receipt = dict(receipt, outputs=[ref for ref in receipt['outputs']
            if (receipt_path.parent / ref['path']).resolve() not in purpose_review_paths])
        adapter.validate_outputs(SimpleNamespace(**globals()), handoff_path, receipt_path, handoff, contract_receipt)
        scope = "prerecord_contract_and_existing_gates"
        workflow_step_completed = True
        completion_claim = "prerecord-contract-and-required-human-gates-validated"
    return {
        "ok": True,
        "status": receipt["status"],
        "handoff_id": handoff["handoff_id"],
        "validation_scope": scope,
        "workflow_step_completed": workflow_step_completed,
        "completion_claim": completion_claim,
        "proves_skill_execution_or_editorial_quality": False,
        "editorial_integrity": editorial,
        "purpose_review": purpose_review,
    }


def _receipt_handoff_path(receipt_path: Path) -> Path:
    receipt = load_json(receipt_path)
    validate_document(receipt, OUTPUT_RECEIPT_SCHEMA_PATH, "step_output_receipt")
    ref = receipt["handoff"]
    target = (receipt_path.parent / ref["path"]).resolve()
    try:
        target.relative_to(receipt_path.parent.resolve())
    except ValueError as error:
        raise AgentEntryError("handoff_path_boundary", "sequence receipt handoff") from error
    if not target.is_file() or sha256_file(target) != ref["sha256"]:
        raise AgentEntryError("output_receipt_handoff_drift", "sequence receipt handoff changed")
    return target


def derive_sequence_status(capsule_path: Path, receipt_paths: list[Path]) -> dict[str, Any]:
    """Derive one allowed next step from existing receipts; persist no parallel state."""

    capsule = _load_valid_capsule(capsule_path)
    steps = capsule["step_index"]
    if len(receipt_paths) > len(steps):
        raise AgentEntryError("sequence_receipt_order", "more receipts were supplied than recipe steps")

    accepted: list[dict[str, Any]] = []
    semantics_pending: list[str] = []
    blocked_step: dict[str, Any] | None = None
    author_steps = _load_author_writing_context().WRITING_STEPS | _load_author_writing_context().REVIEW_STEPS
    current_author_index = max((i for i, row in enumerate(steps[:len(receipt_paths)]) if row["step_id"] in author_steps), default=-1)
    for index, receipt_path in enumerate(receipt_paths):
        handoff_path = _receipt_handoff_path(receipt_path)
        handoff = validate_step_handoff(handoff_path, historical=index != current_author_index)
        expected_step = steps[index]
        if handoff["step"]["step_id"] != expected_step["step_id"]:
            raise AgentEntryError(
                "sequence_receipt_order",
                f"expected {expected_step['step_id']} at receipt position {index + 1}",
            )
        bound_capsule = load_json((handoff_path.parent / handoff["capsule"]["path"]).resolve())
        if bound_capsule.get("payload_sha256") != capsule["payload_sha256"]:
            raise AgentEntryError("previous_step_identity_drift", "sequence receipt belongs to another capsule revision")

        verification = verify_step_output(handoff_path, receipt_path, historical=index != current_author_index)
        if not verification["ok"]:
            if index != len(receipt_paths) - 1:
                raise AgentEntryError("sequence_receipt_order", "receipts cannot continue after a blocked step")
            blocked_step = {
                "step_id": expected_step["step_id"],
                "receipt_sha256": sha256_file(receipt_path),
                "handoff_id": verification["handoff_id"],
            }
            break
        accepted.append(
            {
                "step_id": expected_step["step_id"],
                "receipt_sha256": sha256_file(receipt_path),
                "handoff_id": verification["handoff_id"],
                "validation_scope": verification["validation_scope"],
                "workflow_step_completed": verification["workflow_step_completed"],
            }
        )
        if not verification["workflow_step_completed"]:
            semantics_pending.append(expected_step["step_id"])

    next_step = None
    if blocked_step is None and len(accepted) < len(steps):
        next_step = copy.deepcopy(steps[len(accepted)])

    all_steps_recorded = blocked_step is None and len(accepted) == len(steps)
    all_owner_semantics_verified = all_steps_recorded and not semantics_pending
    if blocked_step is not None:
        state = "blocked"
    elif not all_steps_recorded:
        state = "next_step_required"
    elif semantics_pending:
        state = "sequence_complete_owner_semantics_pending"
    else:
        state = "sequence_complete"
    status = {
        "schema_version": "self-media-sequence-status.v1",
        "capsule_id": capsule["capsule_id"],
        "request_id": capsule["request_id"],
        "recipe_id": capsule["recipe_id"],
        "sequence_state": state,
        "accepted_steps": accepted,
        "next_step": next_step,
        "blocked_step": blocked_step,
        "semantic_evidence_pending": semantics_pending,
        "completion": {
            "all_steps_recorded": all_steps_recorded,
            "all_owner_semantics_verified": all_owner_semantics_verified,
            "managed_pipeline_completion_claim_allowed": all_owner_semantics_verified,
        },
        "publication_authority": False,
    }
    status["payload_sha256"] = sha256_value(status)
    validate_document(status, SEQUENCE_STATUS_SCHEMA_PATH, "sequence_status")
    return status


def require_sequence_complete(capsule_path: Path, receipt_paths: list[Path]) -> dict[str, Any]:
    status = derive_sequence_status(capsule_path, receipt_paths)
    if status["sequence_state"] == "blocked":
        raise AgentEntryError("previous_step_blocked", status["blocked_step"]["step_id"])
    if not status["completion"]["all_steps_recorded"]:
        raise AgentEntryError("sequence_incomplete", status["next_step"]["step_id"])
    if not status["completion"]["all_owner_semantics_verified"]:
        raise AgentEntryError("owner_semantics_pending", ",".join(status["semantic_evidence_pending"]))
    return status


def doctor() -> dict[str, Any]:
    validate_manifest()
    Draft202012Validator.check_schema(load_json(SEQUENCE_STATUS_SCHEMA_PATH))
    catalog = load_catalog()
    route = load_canonical_routing()
    if not DISCOVERY_PATH.is_file():
        raise AgentEntryError("discovery_missing", "AGENT_DISCOVERY.md is missing")
    discovery_text = DISCOVERY_PATH.read_text(encoding="utf-8")
    if len(discovery_text.splitlines()) > 100 or len(discovery_text.encode("utf-8")) > 9216:
        raise AgentEntryError("discovery_too_large", "AGENT_DISCOVERY.md must remain at most 100 lines and 9 KiB")
    required_operations_markers = (
        "Immediate post-publication trigger",
        "python scripts/self_media_agent.py operations",
        "record-publication",
        "record-snapshot",
        "48",
        "156",
    )
    missing_markers = [item for item in required_operations_markers if item not in discovery_text]
    if missing_markers:
        raise AgentEntryError(
            "operations_discovery_missing",
            f"direct content-operations trigger is incomplete: {missing_markers}",
        )
    authoring = authoring_capability()
    if authoring["discovery_command"] not in discovery_text:
        raise AgentEntryError("author_discovery_missing", "authoring capability must be reachable from AGENT_DISCOVERY.md")
    desk_info = publication_desk_capability()
    if desk_info["discovery_command"] not in discovery_text:
        raise AgentEntryError("publication_desk_discovery_missing", "publication desk must be discoverable")
    registry = load_json(TOOL_REGISTRY_PATH)
    registry_entry = (registry.get("tools") or {}).get("content-creation-system") or {}
    registry_cli = registry_entry.get("cli") or {}
    import entry_selection
    Draft202012Validator.check_schema(load_json(entry_selection.SCHEMA))
    if "self-media-work-request.v1" not in discovery_text or "self_media_resolve" not in registry_cli:
        raise AgentEntryError("task_selection_discovery_missing", "Current task selection must be reachable from discovery and the registry")
    selection_probe = resolve_request({
        "schema_version": "self-media-work-request.v1", "request_id": "synthetic-selection-doctor",
        "requested_output": "workflow_repair", "selection_basis": "Synthetic metadata-only entry probe",
    })
    if selection_probe["primary_entry"] != "workflow_maintenance" or selection_probe["commands_executed"]:
        raise AgentEntryError("task_selection_probe_failed", "Task selection did not return the existing maintenance entry")
    required_registry_commands = {
        "self_media_operations",
        "content_operations_help",
        "content_operations_record_publication",
        "content_operations_record_snapshot",
        "content_operations_validate_store",
    }
    missing_registry_commands = sorted(required_registry_commands - set(registry_cli))
    if missing_registry_commands:
        raise AgentEntryError(
            "operations_registry_missing",
            f"tool registry is missing content-operations commands: {missing_registry_commands}",
        )
    capsules = []
    for recipe_id, fixture_path in RECIPE_FIXTURES.items():
        capsule = resolve_request(load_json(fixture_path))
        if capsule["recipe_id"] != recipe_id or capsule["status"] != "routing_ready":
            raise AgentEntryError("cold_start_failed", f"synthetic cold start failed: {recipe_id}")
        if not validate_capsule_hash(capsule):
            raise AgentEntryError("capsule_hash_drift", f"capsule hash failed: {recipe_id}")
        capsules.append(capsule)
    tool_ids = sorted(
        {
            step["tool_id"]
            for recipe in catalog["recipes"]
            for step in recipe["steps"]
        }
    )
    tool_contracts = [_tool_descriptor(tool_id, detailed=True) for tool_id in tool_ids]
    largest = max(len(canonical_bytes(capsule)) for capsule in capsules)
    return {
        "schema_version": "self-media-agent-doctor.v1",
        "ok": True,
        "status": "metadata_contracts_ready",
        "external_runtime_verification": "not-performed",
        "canonical_route": {
            "contract_set_id": route["manifest"]["contract_set_id"],
            "contract_set_version": route["manifest"]["contract_set_version"],
            "load_policy": catalog["canonical_parent"]["load_policy"],
        },
        "recipes": sorted(RECIPE_FIXTURES),
        "cold_start_paths_passed": len(capsules),
        "tool_contracts_resolved": len(tool_contracts),
        "registered_tool_contracts": sum(
            item["discovery_mode"] == "registered_owner" for item in tool_contracts
        ),
        "consumer_commands_resolved": sum("consumer_command" in item for item in tool_contracts),
        "direct_operations_discoverable": True,
        "task_selection_discoverable": True,
        "task_selection_uses_existing_resolve": True,
        "direct_operations_tool_id": DIRECT_OPERATIONS["tool_id"],
        "direct_operations_registry_commands": len(required_registry_commands),
        "authoring_discoverable": True,
        "author_writing_steps": len(authoring["writing_steps"]),
        "author_review_steps": len(authoring["review_steps"]),
        "source_role_required_for_step_handoff": True,
        "derived_sequence_gate_ready": True,
        "largest_capsule_bytes": largest,
        "capsule_max_bytes": catalog["context_defaults"]["capsule_max_bytes"],
        "tool_receipt_max_bytes": catalog["context_defaults"]["tool_receipt_max_bytes"],
        "boundaries": copy.deepcopy(catalog["boundaries"]),
        "proves_current_online": False,
        "proves_publication_authority": False,
        "proves_fact_or_author_approval": False,
    }


def capabilities() -> dict[str, Any]:
    catalog = load_catalog()
    import entry_selection
    return {
        "schema_version": "self-media-agent-capabilities.v1",
        "entry_mode": "metadata-only",
        "start_here": entry_selection.discovery(),
        "workflows": [
            {
                "workflow_goal": recipe["workflow_goal"],
                "recipe_id": recipe["recipe_id"],
                "required_initial_inputs": sorted(recipe["required_initial_inputs"]),
            }
            for recipe in catalog["recipes"]
        ],
        "direct_operations": copy.deepcopy(DIRECT_OPERATIONS),
        "publication_desk": publication_desk_capability(),
        "video_delivery": {"entrypoint": "python scripts/self_media_agent.py video-delivery",
                           "guide": "docs/video-delivery.md", "automatic_publish": False},
        "video_review": {
            "entrypoint": "python scripts/self_media_agent.py video-review",
            "guide": "docs/source-time-range-review.md",
            "purposes": ["rough_cut_recipe", "fine_cut_recipe", "material_requirement"],
            "surface": "targeted-review.html", "review_access_mode": "source_time_range",
            "media_export_allowed": False,
            "production_requires_separate_explicit_user_request": True,
        },
        "authoring": authoring_capability(),
        "creation_routing": {
            "entrypoint": "python scripts/self_media_agent.py creation-route",
            "guide": "docs/creation-route-selection.md",
            "policy": "config/creation-routes.v1.json",
            "mandatory_before_creative_work": True,
            "routes": ["story", "travel-experience", "expository", "technical-rework"],
            "vlog_is_independent_of_case_recipe": True,
            "selection_actor": "Agent assesses current intent and evidence; local CLI validates the assessment",
        },
        "recording_preparation": {
            "workflow_goal": "case_video_candidate", "creation_phase": "prerecording",
            "preparation_kind": ["spoken_script", "interview_guide"],
            "requires_recorded_media": False, "draft_can_have_unknowns": True,
            "completion_is_not_recording_or_publication_authority": True,
            "guide": "docs/prerecording-and-execution-gates.md",
        },
        "sequence_enforcement": {
            "command": "python scripts/self_media_agent.py sequence-status --capsule <capsule.json> [--receipt <receipt.json> ...]",
            "completion_flag": "--require-complete",
            "next_step_count": 1,
            "persistent_parallel_state": False,
            "transport_only_is_managed_completion": False,
            "guide": "docs/agent-sequence-enforcement-2026-09-05.md",
        },
        "boundaries": copy.deepcopy(catalog["boundaries"]),
    }


def publication_desk_capability() -> dict[str, Any]:
    """Discover the local copy/paste desk, not a sixth workflow or a live publisher."""
    for relative in ("scripts/publication_desk.py", "templates/publication-desk/manual-desk.js",
                     "templates/publication-desk/manual-desk.css", "docs/publication-desk.md"):
        if not (ROOT / relative).is_file():
            raise AgentEntryError("publication_desk_missing", relative)
    return {
        "schema_version": "self-media-publication-desk-capability.v1",
        "status": "discoverable", "tool_id": "publication-desk",
        "discovery_command": "python scripts/self_media_agent.py publication-desk",
        "guide": "docs/publication-desk.md", "input_contract": "local-publication-desk.v2",
        "commands": {
            "init": "python scripts/publication_desk.py init --project-id <unique-id> --title <name> --output <new-project.json>",
            "upgrade": "python scripts/publication_desk.py upgrade --input <latest-saved-project.json> --output <new-revision.json> [--platforms <confirmed-platforms> ...]",
            "convert": "python scripts/publication_desk.py convert --input <supported-project.json> --output <new-project.json>",
            "check": "python scripts/publication_desk.py check --stage preparation --input <project.json> --output <new-check.json>",
            "submission_check": "python scripts/publication_desk.py check --stage submission --input <project.json> --output <new-submission-check.json>",
            "render": "python scripts/publication_desk.py render --input <project.json> --output <new-page.html>",
            "verify_current_page": "python scripts/publication_desk.py check --stage preparation --input <page.data.json> --page-build <page.build.json>",
            "restore_archive": "python scripts/publication_desk.py restore-archive --archive <archive.zip> --archive-sha256 <sha256> --data-member <saved-data-member> --output-dir <new-workspace>",
            "sync_project": "python scripts/self_media_agent.py sync-project --state <STATE.json> --request <page.work-request.json> --expected-state-sha256 <sha256> --receipt <new-receipt.json> --apply",
            "operations_handoff": "python scripts/publication_desk.py operations-handoff --input <project.json> --output <new-observations.json>",
        },
        "template_policy": "shared_renderer_project_data_only", "requires_previous_project": False,
        "platform_policy": "config/publication-platforms.v1.json",
        "mandatory_platform_gate": "check validates per-platform fields, actual image ratios and explicit review dispositions; video-delivery blocks incomplete checks",
        "workflow_count": 5, "auto_pipeline_hook": False,
        "complete_delivery_requires": "video-delivery live audit; render alone is draft_preview",
        "render_sidecars": "Current data, work-request and page-build hashes; continue rechecks current policy/template/renderer. Missing/stale page evidence requires regeneration, not media re-edit.",
        "boundaries": {"local_files_only": True, "opens_platform": False, "uploads": False,
                       "publishes": False, "writes_operations_store": False, "publication": "manual-only"},
    }


def operations_capability() -> dict[str, Any]:
    """Return the direct manual recording route before any retrospective workflow."""

    _tool_descriptor(DIRECT_OPERATIONS["tool_id"], detailed=True)
    return {
        "schema_version": "self-media-direct-operations.v1",
        "status": "discoverable",
        **copy.deepcopy(DIRECT_OPERATIONS),
    }


def authoring_capability() -> dict[str, Any]:
    """Discover author sample, judgment and revision tools within existing recipes."""
    authoring = _load_author_writing_context()
    _tool_descriptor("author-expression-store", detailed=True)
    return {
        "schema_version": "self-media-authoring-capability.v1",
        "status": "discoverable",
        "discovery_command": "python scripts/self_media_agent.py authoring",
        "guide": "docs/author-expression-workflow.md",
        "material_interview": {
            "skill": "skills/material-interview/SKILL.md",
            "load_policy": "read_full_before_live_material_interview_or_interview_guide",
            "modes": ["experience", "viewpoint", "formal_interview_guide"],
            "ordinary_chat_requires_managed_recording_task": False,
        },
        "creation_route_preflight": "python scripts/self_media_agent.py creation-route resolve --input <current-context.json> --output <decision.json>",
        "context_tool": "scripts/author_writing_context.py",
        "context_help_command": "python scripts/author_writing_context.py --help",
        "execution_integrity": {
            "command": "python scripts/self_media_agent.py review-integrity --help",
            "guide": "docs/editorial-execution-integrity.md",
            "preparation_required": True, "checks": [f"C{i:02}" for i in range(1, 10)],
            "storage": "existing-author-expression-records",
            "quality_is_not_automatically_proven": True,
        },
        "store_tool": "scripts/author_expression_store.py",
        "store_help_command": "python scripts/author_expression_store.py --help",
        "commands": {
            "prepare_context": "python scripts/author_writing_context.py prepare --store <store.sqlite3> --input <brief.json> --request-id <request-id> --output <author-context.json>",
            "bind_revision": "python scripts/author_writing_context.py revision --store <store.sqlite3> --input <revision.json> --context <author-context.json> --draft <draft.json> --output <author-revision.json>",
            "bind_review": "python scripts/author_writing_context.py review --store <store.sqlite3> --input <review.json> --revision <author-revision.json> --output <author-reviewed.json>",
            "check_context": "python scripts/author_writing_context.py check --context <author-context.json>",
            "check_review": "python scripts/author_writing_context.py check --revision <author-reviewed.json> --require-review",
            "sample": "python scripts/author_expression_store.py sample --store <store.sqlite3> --input <sample.json>",
            "brief": "python scripts/author_expression_store.py brief --store <store.sqlite3> --input <brief.json>",
            "recall": "python scripts/author_expression_store.py recall --store <store.sqlite3> --account-id <account> --genre <genre>",
            "revision": "python scripts/author_expression_store.py revision --store <store.sqlite3> --input <revision.json>",
            "review": "python scripts/author_expression_store.py review --store <store.sqlite3> --input <review.json>",
            "retract": "python scripts/author_expression_store.py retract --store <store.sqlite3> --input <retraction.json>",
            "status": "python scripts/author_expression_store.py status --store <store.sqlite3>",
        },
        "writing_steps": sorted(authoring.WRITING_STEPS),
        "review_steps": sorted(authoring.REVIEW_STEPS),
        "required_writing_role": "author-writing-context",
        "required_review_role": "author-revision-review",
        "revision_contract": "author-writing-revision.v1",
        "cold_start_policy": "Empty approved-sample recall is valid; never fabricate author samples or judgments.",
        "author_judgment_policy": "Preserve source judgments; record risks and alternatives separately. Changed meaning requires exact revision review.",
        "sample_adoption_policy": "Only explicitly selected and author-confirmed spans enter positive recall; approving a draft is not whole-draft sample adoption.",
        "workflow_count": 5,
        "boundaries": copy.deepcopy(EXPECTED_BOUNDARIES),
    }


def resume_receipt(receipt: dict[str, Any]) -> dict[str, Any]:
    error_code = receipt.get("error_code")
    if not isinstance(error_code, str) or not error_code:
        raise AgentEntryError("resume_receipt_invalid", "receipt must contain a non-empty error_code")
    catalog = load_catalog()
    recovery = catalog["error_catalog"].get(error_code)
    if recovery is None:
        raise AgentEntryError("unknown_error_requires_human", f"no automatic recovery is registered for: {error_code}")
    return {
        "schema_version": "self-media-agent-resume.v1",
        "status": "human_action_required",
        "error_code": error_code,
        "recovery_action": recovery["recovery_action"],
        "automatic_retry": False,
    }


def write_or_print(value: dict[str, Any], output: Path | None) -> None:
    rendered = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if output is None:
        print(rendered, end="")
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(rendered, encoding="utf-8", newline="\n")
        temporary.replace(output)
    finally:
        if temporary.exists():
            temporary.unlink()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("doctor", help="Validate local discovery, recipes, canonical routing, fixtures, and boundaries without writing.")
    subparsers.add_parser("capabilities", help="List bounded workflow goals plus the direct post-publication recording route.")
    subparsers.add_parser("operations", help="Show when and how to use the append-only manual content-operations recorder.")
    capture = subparsers.add_parser("research-capture", help="Reuse the webpage ledger and inspect bounded acquisition evidence; no fetching or browser launch.")
    capture.add_argument("capture_args", nargs=argparse.REMAINDER)
    publication = subparsers.add_parser("publication-desk", help="Discover or run the reusable offline publication desk; no platform actions.")
    publication.add_argument("desk_args", nargs=argparse.REMAINDER)
    delivery = subparsers.add_parser("video-delivery", help="Run mandatory local video delivery checks; no publishing.")
    delivery.add_argument("delivery_args", nargs=argparse.REMAINDER)
    subparsers.add_parser("covers", help="Discover multi-route cover production within the existing video workflow.")
    subparsers.add_parser("authoring", help="Discover persistent author samples, judgments and revision review inside existing workflows.")
    integrity = subparsers.add_parser("review-integrity", help="Record preparation, per-version checks and feedback in the existing author store; no publication.")
    integrity.add_argument("integrity_args", nargs=argparse.REMAINDER)
    article = subparsers.add_parser("article-delivery", help="Connect existing editorial records to article layout and review; no publishing.")
    article.add_argument("article_args", nargs=argparse.REMAINDER)
    creation = subparsers.add_parser("creation-route", help="Select story, independent Vlog, explanation or technical-rework route before creating content.")
    creation.add_argument("route_args", nargs=argparse.REMAINDER)
    review = subparsers.add_parser("video-review", help="Review rough/fine editing recipes or materials by original time ranges; never export review media.")
    review.add_argument("review_args", nargs=argparse.REMAINDER)
    resolve = subparsers.add_parser("resolve", help="Select an existing entry by deliverable/current state, or resolve a managed recipe request into its capsule.")
    resolve.add_argument("--request", type=Path, required=True)
    resolve.add_argument("--output", type=Path)
    sync = subparsers.add_parser("sync-project", help="Bind an existing project's latest concrete request and sourced facts; no media or approval changes.")
    sync.add_argument("--state", type=Path, required=True)
    sync.add_argument("--request", type=Path, required=True)
    sync.add_argument("--expected-state-sha256", required=True)
    sync.add_argument("--receipt", type=Path, required=True)
    sync.add_argument("--output", dest="state_output", type=Path)
    sync.add_argument("--apply", action="store_true")
    prepare = subparsers.add_parser("prepare-step", help="Build and bind the mandatory context receipt for one existing-owner step.")
    prepare.add_argument("--capsule", type=Path, required=True)
    prepare.add_argument("--step-id", required=True)
    prepare.add_argument("--context-manifest", type=Path, required=True)
    prepare.add_argument("--context-receipt", type=Path, required=True)
    prepare.add_argument("--output", type=Path, required=True)
    prepare.add_argument("--previous-receipt", type=Path)
    prepare.add_argument("--inspect-only", action="store_true", help="Read step detail without execution authority; consumers reject this handoff.")
    verify = subparsers.add_parser("verify-step-output", help="Verify an existing owner output receipt before the next step.")
    verify.add_argument("--handoff", type=Path, required=True)
    verify.add_argument("--receipt", type=Path, required=True)
    sequence = subparsers.add_parser("sequence-status", help="Derive the only allowed next step from ordered receipts; optionally require complete owner-verified execution.")
    sequence.add_argument("--capsule", type=Path, required=True)
    sequence.add_argument("--receipt", type=Path, action="append", default=[])
    sequence.add_argument("--require-complete", action="store_true")
    sequence.add_argument("--output", type=Path)
    example = subparsers.add_parser("run-example", help="Resolve one of the five synthetic cold-start examples.")
    example.add_argument("--recipe", choices=sorted(RECIPE_FIXTURES), required=True)
    example.add_argument("--output", type=Path)
    resume = subparsers.add_parser("resume", help="Map one stable error receipt to one bounded human recovery action.")
    resume.add_argument("--receipt", type=Path, required=True)
    resume.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    try:
        if args.command == "doctor":
            write_or_print(doctor(), None)
        elif args.command == "capabilities":
            write_or_print(capabilities(), None)
        elif args.command == "operations":
            write_or_print(operations_capability(), None)
        elif args.command == "research-capture":
            import research_capture
            return research_capture.main(args.capture_args or ['policy'])
        elif args.command == "sync-project":
            import entry_selection
            result=entry_selection.sync_project(sys.modules[__name__],args.state,args.request,
                args.expected_state_sha256,args.receipt,output=args.state_output,apply=args.apply)
            write_or_print(result,None)
        elif args.command == "publication-desk":
            if args.desk_args:
                import publication_desk
                return publication_desk.main(args.desk_args)
            write_or_print(publication_desk_capability(), None)
        elif args.command == "video-delivery":
            if not args.delivery_args:
                write_or_print({"entrypoint": "python scripts/self_media_agent.py video-delivery",
                    "actions": ["init", "context", "context-bind", "identity-select", "bgm-select", "progress-select", "cta-init", "cta-bind", "observe-final", "preflight", "render", "check", "deliver"],
                    "cta_review": "Separate interaction/acquisition decisions; no mandatory CTA. Reuse one plan from script review through final-media landing acceptance.",
                    "progress_overlay": "explicit use/not_used decision; default script headings and independent navigation font presets; checked reservation, actual render/layout evidence and current human checks required",
                    "guide": "docs/video-delivery.md", "workflow_count": 5,
                    "draft_render_is_complete": False, "automatic_publish": False}, None)
            else:
                import video_delivery
                return video_delivery.main(args.delivery_args)
        elif args.command == "covers":
            write_or_print({"entrypoint":"python scripts/cover_workbench.py", "guide":"docs/cover-workbench.md",
                "actions":["catalog","methods","styles","doctor","init","plan","strategy-init","strategy-plan","design-recipes","design-init","design-build","compile","render","collect","review-init","review-check"],
                "default_flow":"content evidence -> distinct angle/treatment selection -> per-ratio design -> render -> matrix and visual review",
                "selection_guide":"docs/content-driven-covers.md",
                "color_policy":"No universal palette. Choose colors for current content, emotion and source imagery; brand colors require explicit account/content applicability. Candidate palettes may differ; ratio derivatives share each candidate's palette.",
                "color_guide":"docs/generic-cover-design.md#配色选择与账号边界",
                "agent_responsibility":"Inspect actual video and human corrections; author grounded content signals. CLI does not understand video or predict CTR.",
                "workflow_count":5,"new_renderer":False,"automatic_upload":False,"automatic_publish":False}, None)
        elif args.command == "authoring":
            write_or_print(authoring_capability(), None)
        elif args.command == "review-integrity":
            if args.integrity_args and args.integrity_args[0]=='check-stage':
                import purpose_continuity
                return purpose_continuity.main(args.integrity_args)
            import editorial_integrity
            return editorial_integrity.main(args.integrity_args)
        elif args.command == "creation-route":
            return _load_creation_route().main(args.route_args or ["catalog"])
        elif args.command == "article-delivery":
            import article_delivery
            return article_delivery.main(args.article_args)
        elif args.command == "video-review":
            import video_review_delivery
            return video_review_delivery.main(args.review_args or ["policy"])
        elif args.command == "resolve":
            selection=resolve_request(load_json(args.request))
            write_or_print(selection, args.output)
            if selection.get('schema_version')=='self-media-entry-selection.v1' and selection['status']!='selected':
                return 2
        elif args.command == "run-example":
            write_or_print(resolve_request(load_json(RECIPE_FIXTURES[args.recipe])), args.output)
        elif args.command == "prepare-step":
            prepare_step_handoff(args.capsule, args.step_id, args.context_manifest, args.context_receipt, args.output, args.previous_receipt, args.inspect_only)
        elif args.command == "verify-step-output":
            result = verify_step_output(args.handoff, args.receipt)
            write_or_print(result, None)
            if not result["ok"]:
                return 2
        elif args.command == "sequence-status":
            result = (
                require_sequence_complete(args.capsule, args.receipt)
                if args.require_complete
                else derive_sequence_status(args.capsule, args.receipt)
            )
            write_or_print(result, args.output)
        elif args.command == "resume":
            write_or_print(resume_receipt(load_json(args.receipt)), args.output)
        else:
            raise AgentEntryError("unsupported_command", str(args.command))
    except AgentEntryError as error:
        write_or_print(
            {
                "schema_version": "self-media-agent-error.v1",
                "ok": False,
                "error_code": error.code,
                "message": str(error),
                "automatic_retry": False,
            },
            getattr(args, "output", None),
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
