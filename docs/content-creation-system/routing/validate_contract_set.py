#!/usr/bin/env python3
"""Validate the registered content routing suite as one atomic contract set."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parent
MANIFEST_NAME = "routing-contract-set.v1.json"
SCHEMA_NAME = "routing-contract-set.v1.schema.json"
COMPONENT_FILES = {
    "task_router": "task-router.json",
    "format_adapters": "format-adapters.json",
    "platform_overlays": "platform-overlays.json",
    "skill_registry": "skill-registry.json",
    "quality_gates": "quality-gates.json",
}


class RoutingContractError(ValueError):
    """Raised when the routing suite is missing, stale, or mixed."""


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise RoutingContractError(f"{path.name} must contain a JSON object")
    return value


def canonical_json_sha256(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_contract_set(
    root: Path = ROOT,
    component_overrides: Mapping[str, Path] | None = None,
    component_value_overrides: Mapping[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    manifest_path = root / MANIFEST_NAME
    schema_path = root / SCHEMA_NAME
    if not manifest_path.is_file() or not schema_path.is_file():
        raise RoutingContractError("canonical routing manifest or schema is missing")

    manifest = load_json(manifest_path)
    schema = load_json(schema_path)
    Draft202012Validator.check_schema(schema)
    schema_errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(manifest),
        key=lambda item: list(item.path),
    )
    if schema_errors:
        raise RoutingContractError(f"routing manifest schema invalid: {schema_errors[0].message}")

    overrides = dict(component_overrides or {})
    value_overrides = dict(component_value_overrides or {})
    unknown_overrides = set(overrides) - set(COMPONENT_FILES)
    if unknown_overrides:
        raise RoutingContractError(f"unknown component override: {sorted(unknown_overrides)}")
    unknown_value_overrides = set(value_overrides) - set(COMPONENT_FILES)
    if unknown_value_overrides:
        raise RoutingContractError(f"unknown component value override: {sorted(unknown_value_overrides)}")

    loaded: dict[str, dict[str, Any]] = {}
    for component_id, expected_name in COMPONENT_FILES.items():
        record = manifest["components"][component_id]
        if record["path"] != expected_name:
            raise RoutingContractError(f"{component_id} path is not canonical")
        path = overrides.get(component_id, root / record["path"]).resolve()
        if path.parent != root or path.name != record["path"]:
            raise RoutingContractError(f"mixed routing root prohibited: {component_id}")
        value = value_overrides.get(component_id)
        if value is None:
            value = load_json(path)
        elif not isinstance(value, dict):
            raise RoutingContractError(f"{component_id} value override must be an object")
        if value.get("schema_version") != record["schema_version"]:
            raise RoutingContractError(f"{component_id} schema version drift")
        if canonical_json_sha256(value) != record["canonical_json_sha256"]:
            raise RoutingContractError(f"{component_id} canonical hash drift")
        loaded[component_id] = value

    router = loaded["task_router"]
    if router.get("execution_boundary") != manifest["boundaries"]["execution"]:
        raise RoutingContractError("task router execution boundary drift")
    if router.get("defaults", {}).get("publication_boundary") != "manual-only":
        raise RoutingContractError("task router publication boundary drift")
    if router.get("output_contract", {}).get("publication_authority") != "never":
        raise RoutingContractError("task router unexpectedly grants publication authority")
    override_contract = str(router.get("output_contract", {}).get("manual_route_override", ""))
    if "never-publish-send-execute-authority" not in override_contract:
        raise RoutingContractError("manual route override boundary is missing")

    route_order = router.get("routing_order", [])
    selection_step = "per-task-creation-route-selection"
    if selection_step not in route_order or route_order.index(selection_step) >= route_order.index("optional-structure-route"):
        raise RoutingContractError("creation route selection must precede structure selection")
    defaults = router.get("defaults", {})
    if "travel-experience" not in defaults.get("creation_routes", []):
        raise RoutingContractError("independent travel experience route is missing")
    if "story-design-not-applicable" not in defaults.get("travel_experience_route", ""):
        raise RoutingContractError("Vlog route must not inherit mandatory story design")
    for field in ("creation_route_decision_ref", "creation_route_context_ref", "creation_route", "vlog_style"):
        if field not in router.get("output_contract", {}):
            raise RoutingContractError(f"creation route output field missing: {field}")
    required_scope_order = [
        "source-intake",
        "task-type",
        "account-ip",
        "content-job-and-single-primary-goal",
        "primary-audience",
        "channel-portfolio-and-stage",
        "format-adapter",
        "platform-overlay",
        "conditional-research-plan-execute-and-verified-output",
        "conditional-canonical-fact-card",
        "conditional-fact-revision-lock",
    ]
    if any(step not in route_order for step in required_scope_order):
        raise RoutingContractError("scope, verified research, and fact route stages are missing")
    if [route_order.index(step) for step in required_scope_order] != sorted(route_order.index(step) for step in required_scope_order):
        raise RoutingContractError("scope must precede format/platform, verified research, and fact locking")
    required_design_order = [
        "format-adapter",
        "platform-overlay",
        "voice-profile",
        "visual-profile",
        "design-context-review",
        "brand-asset-spec-if-needed",
        "visual-role-map",
    ]
    if any(step not in route_order for step in required_design_order):
        raise RoutingContractError("format, platform, voice, visual, or design stages are missing")
    if [route_order.index(step) for step in required_design_order] != sorted(route_order.index(step) for step in required_design_order):
        raise RoutingContractError("format and platform selection must precede detailed design work")
    story_material = "conditional-story-material-readiness"
    story_design = "conditional-story-design-card"
    serious_pre = "conditional-serious-content-translation-precheck"
    serious_post = "conditional-serious-content-translation-postcheck"
    cross_platform = "conditional-cross-platform-fact-consistency"
    required_route_steps = [story_material, story_design, serious_pre, "specialized-skills", "post-freeze-hook", serious_post, cross_platform, "final-quality-gates"]
    if any(step not in route_order for step in required_route_steps):
        raise RoutingContractError("serious content translation route stages are missing")
    if [route_order.index(step) for step in required_route_steps] != sorted(route_order.index(step) for step in required_route_steps):
        raise RoutingContractError("serious content translation route order is invalid")
    output_contract = router.get("output_contract", {})
    required_execution_defaults = {
        "route_execution_mode": "selected-recipe-applicable-subset-only",
        "canonical_routing_order_role": "precedence-not-universal-checklist",
        "skip_receipt_policy": "explicit-reason-required",
        "unknown_applicability": "fail-closed",
        "research_output_gate": "verified-research-output-or-explicit-not-applicable",
        "fact_card_requirement": "required-before-factual-draft-or-explicit-not-applicable-for-pure-observation",
        "current_capacity_distribution_mode": "one-frozen-master-manual-synchronous-distribution",
        "distinct_public_variant_generation": "deferred-nonblocking",
        "public_adaptation_max_semantics": "distinct-platform-variants-only-excludes-identical-frozen-master-sync",
    }
    for field, expected in required_execution_defaults.items():
        if router.get("defaults", {}).get(field) != expected:
            raise RoutingContractError(f"task router execution default drift: {field}")
    for field in (
        "applicable_route_steps",
        "skipped_route_steps_with_reason",
        "research_output_ref",
        "research_readiness_status",
        "distribution_mode",
        "frozen_master_ref",
    ):
        if field not in output_contract:
            raise RoutingContractError(f"task router output field missing: {field}")
    for field in (
        "story_material_ref",
        "story_material_readiness",
        "story_design_card_ref",
        "story_design_gate_status",
        "content_nature",
        "sensitivity_profile",
        "serious_content_translation_precheck_ref",
        "serious_content_translation_review_ref",
        "serious_content_translation_gate_status",
        "fun_integrity_review_status",
        "cross_platform_fact_consistency_review_ref",
        "cross_platform_fact_consistency_status",
        "story_reveal_contract_ref",
        "content_role",
        "real_tension",
        "viewer_stakes",
        "central_judgment",
        "explanation_budget",
        "attention_review_status",
    ):
        if field not in output_contract:
            raise RoutingContractError(f"serious content translation output field missing: {field}")

    quality = loaded["quality_gates"]
    story_quality = set(quality.get("story_emotion_design_gates") or [])
    required_story_design = {
        "deidentified-story-material-readiness-visible",
        "story-source-mode-authorization-identity-and-quote-treatment-recorded",
        "story-causality-not-chronology-only",
        "fact-bound-scene-anchor-recorded",
        "first-action-and-real-feedback-recorded",
        "pressure-choice-and-tradeoff-recorded",
        "turn-count-and-central-change-fit-format",
        "turning-points-change-value-state",
        "emotion-beats-bound-to-observable-cue-confirmed-quote-or-author-reaction",
        "individual-story-is-illustration-not-population-proof",
    }
    if not required_story_design.issubset(story_quality):
        raise RoutingContractError("story and emotional resonance quality contract is missing")
    serious_quality = quality.get("serious_content_translation_gates")
    if not isinstance(serious_quality, dict) or set(serious_quality) != {"applicability", "precreative", "postcreative", "attention", "authority"}:
        raise RoutingContractError("serious content translation quality contract is missing")
    if "no-publish-send-or-execution-authority" not in serious_quality.get("authority", []):
        raise RoutingContractError("serious content translation authority boundary is missing")
    required_story_gates = {
        "result-preview-story-reveal-used-instead-of-slow-story-suspense",
        "two-second-watch-reason-recorded-for-story-route",
        "complete-answer-not-disclosed-in-story-opening",
        "protagonist-goal-or-reader-task-recorded",
        "scene-or-dialogue-anchor-recorded",
        "completion-question-and-payoff-recorded",
        "takeaway-or-next-use-recorded",
        "target-action-recorded",
        "acquisition-service-action-and-effect-recorded-when-applicable",
        "story-route-has-at-least-three-information-advances",
    }
    if not required_story_gates.issubset(set(serious_quality.get("precreative", []))):
        raise RoutingContractError("result-preview story reveal gates are missing")
    if router.get("defaults", {}).get("story_reveal_mode") != "result-preview-plus-story-reveal-never-empty-suspense":
        raise RoutingContractError("story reveal default permits slow or empty suspense")
    if router.get("defaults", {}).get("attention_integrity_policy") != "independent-no-averaging-integrity-hard-attention-revision":
        raise RoutingContractError("attention and integrity are not independently gated")
    if "failure-returns-for-revision-not-score-compensation" not in serious_quality.get("attention", []):
        raise RoutingContractError("attention revision boundary is missing")
    required_fun_gates = {
        "fun-is-related-not-decorative-or-misleading",
        "fun-helps-answer-core-question-when-present",
        "core-value-survives-without-fun",
        "primary-memory-target-is-not-gag",
    }
    if not required_fun_gates.issubset(set(serious_quality.get("postcreative", []))):
        raise RoutingContractError("serious content fun integrity gates are missing")
    required_sensitivity_gates = {
        "sensitivity-profile-recorded",
        "near-zero-humor-profile-defaults-to-none-unless-human-exception",
    }
    if not required_sensitivity_gates.issubset(set(serious_quality.get("precreative", []))):
        raise RoutingContractError("serious content sensitivity gates are missing")
    cross_quality = set(quality.get("cross_platform_fact_consistency_gates") or [])
    required_cross_quality = {
        "one-canonical-fact-revision-shared-by-all-platforms",
        "present-claims-match-canonical-normalized-claim-hash",
        "core-claims-cannot-be-omitted-for-density",
        "optional-omissions-have-density-format-or-duration-reason",
        "undeclared-platform-claims-fail-closed",
        "variant-artifact-and-fact-card-hashes-bound",
        "manual-only-no-publication-authority",
    }
    if not required_cross_quality.issubset(cross_quality):
        raise RoutingContractError("cross-platform fact consistency quality contract is missing")
    required_attention_gates = {
        "protagonist-goal-or-reader-task-visible",
        "concrete-stakes-visible",
        "scene-or-dialogue-anchor-preserved",
        "completion-payoff-present",
        "takeaway-or-next-use-present",
        "service-causality-fits-target-action",
    }
    if not required_attention_gates.issubset(set(serious_quality.get("attention", []))):
        raise RoutingContractError("serious content attention readiness gates are missing")

    tool_refs = {item.get("id"): item for item in loaded["skill_registry"].get("tool_refs", [])}
    serious_tool = tool_refs.get("self-media-serious-content-translation-gate")
    if not isinstance(serious_tool, dict) or serious_tool.get("authority") != "candidate-review-only":
        raise RoutingContractError("serious content translation tool binding is missing")
    if "automatic-publication" not in serious_tool.get("not_for", []):
        raise RoutingContractError("serious content translation tool publication boundary is missing")
    cross_tool = tool_refs.get("self-media-cross-platform-fact-consistency-gate")
    if not isinstance(cross_tool, dict) or cross_tool.get("authority") != "candidate-review-only":
        raise RoutingContractError("cross-platform fact consistency tool binding is missing")
    if "automatic-publication" not in cross_tool.get("not_for", []):
        raise RoutingContractError("cross-platform fact consistency publication boundary is missing")
    story_tool = tool_refs.get("self-media-story-design-gate")
    if not isinstance(story_tool, dict) or story_tool.get("authority") != "candidate-review-only":
        raise RoutingContractError("story design tool binding is missing")
    if "publication" not in story_tool.get("not_for", []):
        raise RoutingContractError("story design tool publication boundary is missing")
    story_material_tool = tool_refs.get("self-media-story-material-inbox")
    if not isinstance(story_material_tool, dict) or story_material_tool.get("authority") != "append-only-candidate-local":
        raise RoutingContractError("story material tool binding is missing")
    if "publication" not in story_material_tool.get("not_for", []):
        raise RoutingContractError("story material tool publication boundary is missing")

    serious_extension = next(
        (item for item in manifest.get("compatible_extensions", []) if item.get("id") == "serious-content-translation-review.v1"),
        None,
    )
    if not isinstance(serious_extension, dict) or serious_extension.get("may_replace_canonical_component") is not False:
        raise RoutingContractError("serious content translation extension binding is missing")
    workspace_extension = (root.parents[2] / serious_extension["path"]).resolve()
    if not workspace_extension.is_file():
        raise RoutingContractError("serious content translation receipt schema is missing")
    cross_extension = next(
        (item for item in manifest.get("compatible_extensions", []) if item.get("id") == "cross-platform-fact-consistency-review.v1"),
        None,
    )
    if not isinstance(cross_extension, dict) or cross_extension.get("may_replace_canonical_component") is not False:
        raise RoutingContractError("cross-platform fact consistency extension binding is missing")
    if not (root.parents[2] / cross_extension["path"]).resolve().is_file():
        raise RoutingContractError("cross-platform fact consistency schema is missing")
    story_extension = next(
        (item for item in manifest.get("compatible_extensions", []) if item.get("id") == "story-design-card.v1"),
        None,
    )
    if not isinstance(story_extension, dict) or story_extension.get("may_replace_canonical_component") is not False:
        raise RoutingContractError("story design extension binding is missing")
    if not (root.parents[2] / story_extension["path"]).resolve().is_file():
        raise RoutingContractError("story design card schema is missing")
    story_material_extension = next(
        (item for item in manifest.get("compatible_extensions", []) if item.get("id") == "story-material-observation.v1"),
        None,
    )
    if not isinstance(story_material_extension, dict) or story_material_extension.get("may_replace_canonical_component") is not False:
        raise RoutingContractError("story material extension binding is missing")
    if not (root.parents[2] / story_material_extension["path"]).resolve().is_file():
        raise RoutingContractError("story material observation schema is missing")

    adapter_formats = {item["format"] for item in loaded["format_adapters"].get("adapters", [])}
    overlay_platforms = {item["id"].rsplit("@", 1)[0] for item in loaded["platform_overlays"].get("overlays", [])}
    if adapter_formats != set(router["enums"]["format"]):
        raise RoutingContractError("format adapter coverage drift")
    adapters_by_format = {item["format"]: item for item in loaded["format_adapters"].get("adapters", [])}
    short_story = adapters_by_format.get("short-video-narration", {}).get("story_profile", {})
    if short_story.get("turning_points") != "1-3" or short_story.get("central_change_count") != 1:
        raise RoutingContractError("short-video story profile drift")
    longform_story = adapters_by_format.get("longform-article", {}).get("story_profile", {})
    if longform_story.get("scene_meaning_alternation") != "planned":
        raise RoutingContractError("longform scene-meaning profile drift")
    interview_story = adapters_by_format.get("interview-video", {}).get("story_profile", {})
    if interview_story.get("source_mode") != "authorized-interview" or interview_story.get("action_meaning_layers") != "separated":
        raise RoutingContractError("interview story profile drift")
    if overlay_platforms != set(router["enums"]["platform"]):
        raise RoutingContractError("platform overlay coverage drift")

    workspace_root = root.parents[2]
    skills_root = (workspace_root / "skills").resolve()
    registry_skills = {item.get("id"): item for item in loaded["skill_registry"].get("skills", [])}
    expected_local_skills = {
        "local-content-fact-card": "content-fact-card",
        "local-insurance-storycraft": "insurance-content-storycraft",
    }
    for registry_id, skill_id in expected_local_skills.items():
        record = registry_skills.get(registry_id)
        if not isinstance(record, dict):
            raise RoutingContractError(f"{registry_id} deterministic loader is missing")
        loader = record.get("loader")
        if not isinstance(loader, dict):
            raise RoutingContractError(f"{registry_id} deterministic loader is missing")
        if loader.get("deployment_mode") != "copy-only" or loader.get("on_mismatch") != "fail-closed":
            raise RoutingContractError(f"{registry_id} loader boundary drift")

        skill_path = (root / str(loader.get("skill_path", ""))).resolve()
        binding_path = (root / str(loader.get("contract_binding_path", ""))).resolve()
        expected_skill_root = (skills_root / skill_id).resolve()
        if not skill_path.is_relative_to(expected_skill_root) or skill_path.name != "SKILL.md":
            raise RoutingContractError(f"{registry_id} skill path escapes the deployed Skill root")
        if not binding_path.is_relative_to(expected_skill_root) or binding_path.name != "contract-binding.json":
            raise RoutingContractError(f"{registry_id} binding path escapes the deployed Skill root")
        if not skill_path.is_file() or not binding_path.is_file():
            raise RoutingContractError(f"{registry_id} deployed Skill or binding is missing")
        if file_sha256(skill_path) != loader.get("skill_sha256"):
            raise RoutingContractError(f"{registry_id} deployed Skill hash drift")
        if file_sha256(binding_path) != loader.get("contract_binding_sha256"):
            raise RoutingContractError(f"{registry_id} contract binding hash drift")
        binding = load_json(binding_path)
        if binding.get("skill_id") != skill_id or binding.get("on_missing_or_drift") != "fail-closed":
            raise RoutingContractError(f"{registry_id} contract binding identity drift")
        if binding.get("publication_authority") != "none" or binding.get("external_send_authority") != "none":
            raise RoutingContractError(f"{registry_id} contract binding grants forbidden authority")

    return {"manifest": manifest, "components": loaded}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    try:
        result = load_contract_set(args.root)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"BLOCKED: {error}")
        return 1
    print(
        f"PASS: registered-content-routing {result['manifest']['contract_set_version']} "
        "is atomic, hash-bound, manual-only, and rejects mixed roots."
    )
    print(canonical_json_sha256(result["manifest"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
