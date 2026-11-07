#!/usr/bin/env python3
"""Deterministic, candidate-only evidence-to-content loop for small agents.

This module is deliberately a thin owner-local orchestrator.  It consumes the
existing research-output/content-item/routing/human-voice contracts, produces
review candidates, and never calls a model, publisher, platform account, CRM,
or knowledge base.
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

from jsonschema import Draft202012Validator

import canonical_routing as current_routing


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = REPO_ROOT.parent
ROUTING_ROOT = WORKSPACE_ROOT / "docs" / "content-creation-system" / "routing"
ROUTING_SET = ROUTING_ROOT / "routing-contract-set.v1.json"
PLATFORM_OVERLAYS = ROUTING_ROOT / "platform-overlays.json"
CONTENT_ITEM_SCHEMA = WORKSPACE_ROOT / "docs" / "content-creation-system" / "content-item.schema.json"
CONTENT_STUDIO_SCRIPTS = WORKSPACE_ROOT / "content-studio-poc" / "scripts"
INPUT_SCHEMA = REPO_ROOT / "schemas" / "small-model-content-loop-input.v1.schema.json"
COMPACT_HANDOFF = REPO_ROOT / "fixtures" / "small-model-content-loop-v1" / "compact-handoff.v1.json"
HUMAN_VOICE_SKILL = WORKSPACE_ROOT / "skills" / "human-voice-editor" / "SKILL.md"
HUMAN_VOICE_RULEBOOK = WORKSPACE_ROOT / "skills" / "human-voice-editor" / "references" / "rulebook.md"

INPUT_SCHEMA_VERSION = "small-model-content-loop-input.v1"
OUTPUT_SCHEMA_VERSION = "small-model-content-loop-run.v1"
_ROUTING_BINDING = current_routing.load_binding()
ROUTING_CONTRACT_ID = _ROUTING_BINDING["canonical_contract_set_id"]
ROUTING_CONTRACT_VERSION = _ROUTING_BINDING["canonical_contract_set_version"]
FACT_STATUSES = {
    "verified_source",
    "verified_position",
    "framework_application",
    "agent_inference",
    "unverified",
}
TARGET_PLATFORM_IDS = (
    "wechat-article@0.2",
    "wechat-moments@0.2",
    "xiaohongshu@0.2",
    "wechat-video@0.2",
    "zhihu@0.2",
    "bilibili@0.2",
)
STAGES = ("preflight", "candidate", "variants", "gates", "review")
FORBIDDEN_FINAL_STATES = {"final", "finalized", "published", "publish-ready", "release-ready"}
FORBIDDEN_PRIVACY_KEYS = {
    "customer_name",
    "display_name",
    "phone",
    "mobile",
    "contact",
    "policy_number",
    "health_details",
    "account_url",
    "platform_token",
    "cookie",
    "secret",
}
SERIES_MARKERS = ("第1集", "第2集", "第3集", "第一集", "第二集", "上一集", "下一集", "上集", "下集")


class LoopError(RuntimeError):
    def __init__(self, code: str, message: str, *, stage: str = "preflight") -> None:
        super().__init__(message)
        self.code = code
        self.stage = stage


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LoopError("input_unreadable", f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise LoopError("input_invalid", f"JSON root must be an object: {path}")
    return value


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_value(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalized_text(path: Path) -> str:
    """Return UTF-8 text with platform-independent line endings."""
    return path.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")


def normalized_sha256(path: Path) -> str:
    """Hash versioned text contracts without binding them to LF or CRLF checkout policy."""
    return hashlib.sha256(normalized_text(path).encode("utf-8")).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def repo_relative(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError as exc:
        raise LoopError("path_outside_repo", f"path must stay inside self-media repository: {path}") from exc


def resolve_repo_ref(ref: str) -> Path:
    if not ref or Path(ref).is_absolute():
        raise LoopError("path_not_portable", f"repository-relative path required: {ref!r}")
    path = (REPO_ROOT / ref).resolve()
    repo_relative(path)
    return path


def validate_json(instance: dict[str, Any], schema_path: Path, code: str) -> None:
    schema = load_json(schema_path)
    errors = sorted(Draft202012Validator(schema).iter_errors(instance), key=lambda item: list(item.absolute_path))
    if errors:
        first = errors[0]
        location = "/".join(str(part) for part in first.absolute_path) or "<root>"
        raise LoopError(code, f"{location}: {first.message}")


def scan_privacy(value: Any, path: str = "$") -> list[str]:
    hits: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            lowered = str(key).lower()
            if lowered in FORBIDDEN_PRIVACY_KEYS:
                hits.append(f"{path}.{key}")
            hits.extend(scan_privacy(child, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            hits.extend(scan_privacy(child, f"{path}[{index}]"))
    return hits


def load_routing() -> tuple[dict[str, Any], dict[str, Any], dict[str, dict[str, Any]]]:
    try:
        loaded = current_routing.load_contracts()
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise LoopError("routing_contract_drift", str(error)) from error
    contract_set = loaded["manifest"]
    if contract_set.get("contract_set_id") != ROUTING_CONTRACT_ID:
        raise LoopError("routing_contract_drift", "unexpected routing contract id")
    if contract_set.get("contract_set_version") != ROUTING_CONTRACT_VERSION:
        raise LoopError("routing_version_drift", "registered routing version differs from the canonical binding")
    overlays = loaded["components"]["platform_overlays"]
    by_id = {item["id"]: item for item in overlays.get("overlays", [])}
    if len(by_id) != 12:
        raise LoopError("platform_catalog_drift", f"expected 12 registered platforms, found {len(by_id)}")
    missing = sorted(set(TARGET_PLATFORM_IDS) - set(by_id))
    if missing:
        raise LoopError("required_route_missing", f"missing required platform routes: {missing}")
    return contract_set, overlays, by_id


def evidence_graph(research: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    if research.get("completeness", {}).get("ready_for_answer") is not True:
        raise LoopError("evidence_not_ready", "evidence bundle is not ready for an answer")
    guarded = research.get("guarded_final_answer", {})
    if guarded.get("status") != "verified" or guarded.get("ready") is not True:
        raise LoopError("evidence_not_verified", "guarded final answer is not verified")
    if guarded.get("blocking_gates"):
        raise LoopError("evidence_blocking_gate", "evidence bundle contains blocking gates")
    if research.get("contradictions"):
        unresolved = [item for item in research["contradictions"] if item.get("resolution_status") not in {"resolved", "rejected"}]
        if unresolved:
            raise LoopError("unresolved_contradiction", "evidence bundle contains unresolved contradictions")
    if research.get("unknowns"):
        raise LoopError("evidence_unknowns_present", "evidence bundle contains unresolved unknowns")
    if research.get("provenance", {}).get("offline_only") is not True:
        raise LoopError("offline_boundary_missing", "evidence provenance must be offline_only")
    claims = {item["claim_id"]: item for item in research.get("claims", [])}
    evidence = {item["evidence_id"]: item for item in research.get("evidence", [])}
    sources = {item["source_id"]: item for item in research.get("sources", [])}
    return claims, evidence, sources


def validate_claim_units(request: dict[str, Any], research: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    claims, evidence, _sources = evidence_graph(research)
    units = request.get("claim_units", [])
    if not units:
        raise LoopError("claim_units_missing", "at least one claim unit is required")
    warnings: list[str] = []
    validated: list[dict[str, Any]] = []
    for unit in units:
        status = unit.get("fact_status")
        if status not in FACT_STATUSES:
            raise LoopError("fact_status_invalid", f"unsupported fact status: {status}")
        if status == "unverified":
            raise LoopError("needs_source", f"unverified claim requires a source: {unit.get('unit_id')}")
        if status == "agent_inference":
            if unit.get("human_review_required") is not True:
                raise LoopError("inference_unlabelled", "agent inference must require human review")
            warnings.append(f"agent inference requires human review: {unit['unit_id']}")
        if status == "framework_application" and not unit.get("framework_ref"):
            raise LoopError("framework_ref_missing", "framework application requires framework_ref")
        claim_id = unit.get("claim_id")
        evidence_ids = unit.get("evidence_ids", [])
        if status == "verified_source":
            claim = claims.get(claim_id)
            if not claim or claim.get("review_status") != "verified" or claim.get("evidence_status") != "verified":
                raise LoopError("verified_claim_missing", f"verified claim not found: {claim_id}")
            if not evidence_ids:
                raise LoopError("evidence_ref_missing", f"claim has no evidence refs: {claim_id}")
            for evidence_id in evidence_ids:
                item = evidence.get(evidence_id)
                if not item:
                    raise LoopError("evidence_ref_missing", f"unknown evidence ref: {evidence_id}")
                if item.get("evidence_status") != "verified" or item.get("review_status") != "reviewed":
                    raise LoopError("evidence_not_verified", f"evidence is not verified: {evidence_id}")
                if item.get("ai_synthesis") is True or item.get("relation") != "supports":
                    raise LoopError("evidence_relation_invalid", f"evidence cannot support a fact: {evidence_id}")
        if status == "verified_position" and unit.get("position_confirmed") is not True:
            raise LoopError("position_not_confirmed", "verified_position requires explicit position confirmation")
        validated.append(unit)
    return validated, warnings


def canonical_body(seed: dict[str, Any]) -> str:
    parts = [seed["opening"].strip()]
    for section in seed["sections"]:
        parts.append(f"{section['heading'].strip()}\n{section['body'].strip()}")
    parts.append(seed["boundary"].strip())
    return "\n\n".join(parts)


def validate_voice(request: dict[str, Any], body: str) -> dict[str, Any]:
    attestation = request.get("human_voice_attestation", {})
    if attestation.get("mode") != "synthetic_fixture_attestation":
        raise LoopError("human_voice_confirmation_missing", "synthetic fixture voice attestation is required", stage="gates")
    if attestation.get("read_aloud_completed") is not True:
        raise LoopError("read_aloud_missing", "read-aloud receipt is required", stage="gates")
    if attestation.get("author_voice_confirmed") is not True:
        raise LoopError("author_voice_unconfirmed", "author voice confirmation is required", stage="gates")
    if attestation.get("body_sha256") != hashlib.sha256(body.encode("utf-8")).hexdigest():
        raise LoopError("human_voice_body_hash_drift", "voice attestation is stale for the candidate body", stage="gates")
    if str(CONTENT_STUDIO_SCRIPTS) not in sys.path:
        sys.path.insert(0, str(CONTENT_STUDIO_SCRIPTS))
    try:
        import human_voice_gate  # type: ignore
    except Exception as exc:  # pragma: no cover - environment failure path
        raise LoopError("human_voice_adapter_unavailable", str(exc), stage="gates") from exc
    diagnosis = human_voice_gate.diagnose_human_voice(body)
    if diagnosis.get("issue_codes"):
        raise LoopError("human_voice_semantic_gate_blocked", f"human voice issues remain: {diagnosis['issue_codes']}", stage="gates")
    return diagnosis


def base_ref_list(units: list[dict[str, Any]], research: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    source_ids = {claim["claim_id"]: claim.get("source_ids", []) for claim in research.get("claims", [])}
    for unit in units:
        if unit.get("claim_id"):
            refs.append(f"claim://{unit['claim_id']}")
        refs.extend(f"evidence://{item}" for item in unit.get("evidence_ids", []))
        refs.extend(f"source://{item}" for item in source_ids.get(unit.get("claim_id"), []))
    return sorted(set(refs))


def build_candidate(request: dict[str, Any], evidence_ref: str, units: list[dict[str, Any]], research: dict[str, Any]) -> dict[str, Any]:
    seed = request["canonical_seed"]
    body = canonical_body(seed)
    refs = base_ref_list(units, research)
    verified_facts = [unit["text"] for unit in units if unit["fact_status"] == "verified_source"]
    uncertainties = [unit["text"] for unit in units if unit["fact_status"] in {"framework_application", "agent_inference"}]
    checks = [
        {"name": "evidence-reference-graph", "status": "pass", "details": f"Preserved {len(refs)} evidence/source refs."},
        {"name": "synthetic-only-boundary", "status": "pass", "details": "No real customer, product, account, or publication data is admitted."},
        {"name": "manual-publication-boundary", "status": "pass", "details": "Output remains candidate_only and manual-only."},
    ]
    candidate = {
        "schema_version": "0.2",
        "content_id": request["content_id"],
        "title": seed["title"],
        "primary_format": "multi-channel",
        "status": "candidate",
        "created_at": request["fixture_time"],
        "updated_at": request["fixture_time"],
        "tags": ["candidate-only", "draft-only", "manual-only", "synthetic-only"],
        "provenance": {
            "sources": [{"source_type": "workspace-file", "ref": evidence_ref, "evidence_status": "verified", "note": "Synthetic research-output.v1 evidence bundle."}],
            "verified_facts": verified_facts,
            "uncertainties": uncertainties,
            "forbidden_claims": ["Do not present this synthetic fixture as a real case, real frequency, product recommendation, or platform rule."],
        },
        "gates": {
            "fact": {"status": "needs-review", "reason": "Deterministic source graph passed; final factual review remains human."},
            "privacy": {"status": "pass", "reason": "Synthetic-only input and privacy scan passed.", "reviewed_by": "small-model-content-loop", "reviewed_at": request["fixture_time"]},
            "compliance": {"status": "needs-review", "reason": "Insurance/medical compliance review remains required before any manual publication."},
            "rights": {"status": "needs-review", "reason": "No media was generated; any later visual asset requires rights review."},
        },
        "intent": {
            "topic": request["topic"],
            "speaker_role": "insurance decision explainer",
            "audience": request["audience"],
            "content_object": "evidence-bound synthetic candidate",
            "desired_action": "help the reader know what to verify before a claim",
            "risk_boundary": seed["boundary"],
            "platform_intent": "candidate variants for manual review only",
            "main_angle": seed["opening"],
            "structure_route": "tool-action",
            "planning_scope": "single",
            "current_piece_decision": "Each platform variant must stand alone and must not be numbered as an episode.",
        },
        "composition": {
            "canonical_body": body,
            "expression_mode": "evidence-led plain-language explanation",
            "retention_mode": "full-text",
            "canonical_summary": seed["summary"],
            "voice_profile": "voice/synthetic-human-reviewed",
            "voice_profile_version": "1.0",
            "semantic_reversibility": {"status": "needs-review", "reverse_paraphrase": seed["summary"], "meaning_drift": []},
        },
        "visual": {
            "visual_profile": "visual/candidate-only-evidence-led",
            "visual_profile_version": "0.1",
            "route": "none",
            "theme": "synthetic-claims-preparation",
            "cognitive_anchors": [seed["title"], seed["summary"]],
            "assets": [],
            "render_recipe": {"renderer": "none", "output_format": "none", "output_refs": []},
        },
        "qa": {
            "deterministic": checks,
            "human_review": {"status": "required", "reviewer": None, "reviewed_at": None, "note": "Fact, compliance, author voice, and platform packaging require human review."},
        },
        "publication": {"boundary": "manual-only", "receipts": []},
        "feedback": {"signal_status": "not-observed", "platform_signals": {}, "business_signals": {}, "learning_decision": "none", "content_signal_status": "not-observed", "business_signal_status": "not-observed", "next_test": "Human review only; no automatic publication or feedback collection."},
    }
    validate_json(candidate, CONTENT_ITEM_SCHEMA, "content_item_invalid")
    return candidate


def build_variants(request: dict[str, Any], candidate: dict[str, Any], refs: list[str], routes: dict[str, dict[str, Any]]) -> dict[str, Any]:
    seed = request["canonical_seed"]
    opening = seed["opening"]
    core = "\n\n".join(section["body"] for section in seed["sections"])
    boundary = seed["boundary"]
    definitions = {
        "wechat-article@0.2": ("longform-article", f"{opening}\n\n{core}\n\n{boundary}"),
        "wechat-moments@0.2": ("moments-short-text", f"最近用一份完全虚构的材料重新梳理了理赔准备。\n{opening}\n{core}\n{boundary}"),
        "xiaohongshu@0.2": ("graphic-note", f"{opening}\n\n可以先按这几项核对：\n{core}\n\n{boundary}"),
        "wechat-video@0.2": ("short-video-narration", f"{opening}\n接下来只说三件真正需要提前确认的事。\n{core}\n{boundary}"),
        "zhihu@0.2": ("longform-article", f"先说结论：{seed['summary']}\n\n{opening}\n\n{core}\n\n{boundary}"),
        "bilibili@0.2": ("long-video", f"这条内容单独回答一个问题：{request['topic']}\n{opening}\n\n{core}\n\n{boundary}"),
    }
    variants = []
    for platform_id in TARGET_PLATFORM_IDS:
        format_id, body = definitions[platform_id]
        if any(marker in candidate["title"] or marker in body for marker in SERIES_MARKERS):
            raise LoopError("standalone_variant_failed", f"series marker found in {platform_id}", stage="variants")
        variants.append(
            {
                "platform_id": platform_id,
                "overlay_role": routes[platform_id]["role"],
                "format": format_id,
                "title": candidate["title"],
                "opening": opening,
                "body": body,
                "evidence_refs": refs,
                "fact_statuses": sorted({unit["fact_status"] for unit in request["claim_units"]}),
                "standalone": True,
                "series_numbering": "prohibited",
                "status": "candidate_only",
                "publication_boundary": "manual-only",
            }
        )
    return {
        "schema_version": "platform-fit-variants.v1",
        "content_id": candidate["content_id"],
        "routing_contract": {"id": ROUTING_CONTRACT_ID, "version": ROUTING_CONTRACT_VERSION, "platform_count": 12},
        "generated_platforms": list(TARGET_PLATFORM_IDS),
        "validated_only_platforms": sorted(set(routes) - set(TARGET_PLATFORM_IDS)),
        "variants": variants,
        "status": "candidate_only",
    }


def build_gate_report(request: dict[str, Any], candidate: dict[str, Any], variants: dict[str, Any], claim_warnings: list[str]) -> dict[str, Any]:
    body = candidate["composition"]["canonical_body"]
    privacy_hits = scan_privacy(request)
    if privacy_hits:
        raise LoopError("privacy_field_detected", f"forbidden privacy fields: {privacy_hits}", stage="gates")
    requested = request.get("requested_final_state", "candidate")
    if requested in FORBIDDEN_FINAL_STATES:
        raise LoopError("premature_finalize_forbidden", f"requested state is not authorized: {requested}", stage="gates")
    if candidate["publication"]["boundary"] != "manual-only" or candidate["status"] != "candidate":
        raise LoopError("publication_boundary_bypassed", "candidate/manual-only boundary changed", stage="gates")
    if any(not item.get("standalone") for item in variants["variants"]):
        raise LoopError("standalone_variant_failed", "every generated platform variant must stand alone", stage="gates")
    diagnosis = validate_voice(request, body)
    return {
        "schema_version": "small-model-content-gate-report.v1",
        "content_id": candidate["content_id"],
        "status": "review_required",
        "checks": {
            "fact": {"status": "pass", "warnings": claim_warnings},
            "privacy": {"status": "pass", "hits": []},
            "compliance": {"status": "review_required", "reason": "insurance/medical content remains subject to human review"},
            "human_voice": {"status": "pass", "diagnostics": diagnosis, "read_aloud": "synthetic_fixture_completed", "author_voice": "synthetic_fixture_confirmed"},
            "standalone_variants": {"status": "pass", "count": len(variants["variants"])},
            "publication": {"status": "blocked", "boundary": "manual-only", "execution_authorized": False},
        },
    }


def build_review_packet(run_id: str, candidate: dict[str, Any], variants: dict[str, Any], gate_report: dict[str, Any], refs: list[str]) -> dict[str, Any]:
    return {
        "schema_version": "small-model-content-review-packet.v1",
        "facade_contract": "review-packet.v1",
        "closure_run_id": run_id,
        "content_id": candidate["content_id"],
        "status": "review_required",
        "metadata": {"execution_authorized": False, "external_io_performed": False, "candidate_only": True},
        "payload": {
            "suggested_points": [
                "核对事实、证据引用和 needs_source 标记是否准确。",
                "朗读并确认是否像本人说话，且六个平台版本都能独立成立。",
                "确认保险合规、隐私和素材权利后，再由人工决定是否发布。",
            ],
            "discarded_or_not_started": "未生成图片、未调用模型、未登录平台、未发布、未联系客户。",
            "decision_question": "是否进入人工逐平台审稿，而不是发布？",
            "evidence_status": "candidate",
            "evidence_refs": refs + [f"closure://{run_id}", f"content://{candidate['content_id']}"],
        },
        "artifact_refs": {"candidate": "artifacts/canonical-content-candidate.json", "variants": "artifacts/platform-fit-variants.json", "gates": "artifacts/gate-report.json"},
    }


def receipt_payload(run_id: str, stage: str, checked_at: str, inputs: dict[str, str], outputs: dict[str, str], status: str = "pass") -> dict[str, Any]:
    payload = {
        "schema_version": "small-model-content-stage-receipt.v1",
        "closure_run_id": run_id,
        "stage": stage,
        "status": status,
        "checked_at": checked_at,
        "input_sha256": inputs,
        "output_sha256": outputs,
        "retry_count": 0,
        "external_io_performed": False,
        "execution_authorized": False,
    }
    payload["receipt_sha256"] = sha256_value(payload)
    return payload


def make_manifest(run_id: str, request_ref: str, input_hash: str, checked_at: str) -> dict[str, Any]:
    return {
        "schema_version": OUTPUT_SCHEMA_VERSION,
        "closure_run_id": run_id,
        "request_ref": request_ref,
        "input_sha256": input_hash,
        "status": "running",
        "current_stage": None,
        "completed_stages": [],
        "stage_receipts": {},
        "failure_point": None,
        "error": None,
        "resume_entry": None,
        "contract_versions": {"routing": ROUTING_CONTRACT_VERSION, "content_item": "0.2", "review_packet_facade": "v1"},
        "checked_at": checked_at,
        "retry_policy": {"automatic_retries": 0},
        "boundaries": {"candidate_only": True, "draft_only": True, "review_required": True, "publication": "manual-only", "external_io": False},
    }


def record_stage(run_root: Path, manifest: dict[str, Any], stage: str, inputs: dict[str, str], output_paths: list[Path]) -> None:
    outputs = {repo_relative(path): sha256_file(path) for path in output_paths}
    receipt = receipt_payload(manifest["closure_run_id"], stage, manifest["checked_at"], inputs, outputs)
    receipt_path = run_root / "receipts" / f"{stage}.receipt.json"
    write_json(receipt_path, receipt)
    manifest["current_stage"] = stage
    manifest["completed_stages"].append(stage)
    manifest["stage_receipts"][stage] = {"ref": repo_relative(receipt_path), "sha256": sha256_file(receipt_path)}
    write_json(run_root / "run-manifest.json", manifest)


def preflight_request(request: dict[str, Any], input_path: Path) -> tuple[dict[str, Any], list[dict[str, Any]], list[str], dict[str, dict[str, Any]], str]:
    validate_json(request, INPUT_SCHEMA, "input_schema_invalid")
    if request.get("schema_version") != INPUT_SCHEMA_VERSION:
        raise LoopError("input_schema_version_invalid", "unsupported loop input schema")
    if request.get("synthetic_only") is not True:
        raise LoopError("synthetic_only_required", "only fully synthetic input is accepted")
    if request.get("requested_final_state", "candidate") not in {"candidate", "review_required"}:
        raise LoopError("premature_finalize_forbidden", "only candidate/review_required output is authorized")
    privacy_hits = scan_privacy(request)
    if privacy_hits:
        raise LoopError("privacy_field_detected", f"forbidden privacy fields: {privacy_hits}")
    binding = request.get("contract_binding", {})
    expected = {
        "routing_set_sha256": normalized_sha256(ROUTING_SET),
        "content_item_schema_sha256": normalized_sha256(CONTENT_ITEM_SCHEMA),
        "human_voice_skill_sha256": normalized_sha256(HUMAN_VOICE_SKILL),
        "human_voice_rulebook_sha256": normalized_sha256(HUMAN_VOICE_RULEBOOK),
    }
    for key, actual in expected.items():
        if binding.get(key) != actual:
            raise LoopError("contract_hash_drift", f"{key} drifted")
    if binding.get("routing_contract_version") != ROUTING_CONTRACT_VERSION:
        raise LoopError("routing_version_drift", "routing contract version changed")
    _contract_set, _overlays, routes = load_routing()
    evidence_binding = request.get("evidence_bundle", {})
    evidence_path = resolve_repo_ref(evidence_binding.get("path", ""))
    if normalized_sha256(evidence_path) != evidence_binding.get("sha256"):
        raise LoopError("source_hash_drift", "evidence bundle hash changed")
    research = load_json(evidence_path)
    if research.get("research_id") != evidence_binding.get("research_id"):
        raise LoopError("evidence_identity_drift", "research id does not match binding")
    units, warnings = validate_claim_units(request, research)
    seed = request.get("canonical_seed", {})
    for key in ("title", "opening", "summary", "boundary", "sections"):
        if not seed.get(key):
            raise LoopError("canonical_seed_invalid", f"canonical seed missing {key}")
    body = canonical_body(seed)
    if request.get("human_voice_attestation", {}).get("body_sha256") != hashlib.sha256(body.encode("utf-8")).hexdigest():
        raise LoopError("human_voice_body_hash_drift", "voice attestation does not bind the canonical seed")
    repo_relative(input_path)
    return research, units, warnings, routes, repo_relative(evidence_path)


def run_loop(input_path: Path, run_root: Path, closure_run_id: str | None = None, pause_after: str | None = None) -> dict[str, Any]:
    input_path = input_path.resolve()
    run_root = run_root.resolve()
    repo_relative(input_path)
    repo_relative(run_root)
    request = load_json(input_path)
    input_hash = sha256_value(request)
    run_id = closure_run_id or request.get("closure_run_id") or f"smcl-{input_hash[:20]}"
    if not re.fullmatch(r"smcl-[a-z0-9-]{8,64}", run_id):
        raise LoopError("closure_run_id_invalid", "closure_run_id must match smcl-[a-z0-9-]{8,64}")
    manifest_path = run_root / "run-manifest.json"
    if manifest_path.exists():
        prior = load_json(manifest_path)
        if prior.get("closure_run_id") != run_id or prior.get("input_sha256") != input_hash:
            raise LoopError("closure_run_identity_drift", "run root is bound to a different input or closure_run_id")
        if prior.get("status") == "completed":
            return {"status": "already_completed", "closure_run_id": run_id, "manifest": repo_relative(manifest_path), "manifest_sha256": sha256_file(manifest_path)}
    run_root.mkdir(parents=True, exist_ok=True)
    manifest = make_manifest(run_id, repo_relative(input_path), input_hash, request.get("fixture_time", "1970-01-01T00:00:00Z"))
    write_json(manifest_path, manifest)
    try:
        research, units, warnings, routes, evidence_ref = preflight_request(request, input_path)
        preflight_artifact = {
            "schema_version": "small-model-content-preflight.v1",
            "closure_run_id": run_id,
            "input_sha256": input_hash,
            "routing_contract": {"id": ROUTING_CONTRACT_ID, "version": ROUTING_CONTRACT_VERSION, "platform_count": len(routes)},
            "evidence_bundle": {"ref": evidence_ref, "sha256": request["evidence_bundle"]["sha256"], "status": "verified"},
            "fact_statuses_supported": sorted(FACT_STATUSES),
            "status": "pass",
        }
        preflight_path = run_root / "artifacts" / "preflight.json"
        write_json(preflight_path, preflight_artifact)
        record_stage(run_root, manifest, "preflight", {"request": input_hash}, [preflight_path])
        if pause_after == "preflight":
            return pause_run(run_root, manifest)

        candidate = build_candidate(request, evidence_ref, units, research)
        candidate_path = run_root / "artifacts" / "canonical-content-candidate.json"
        write_json(candidate_path, candidate)
        record_stage(run_root, manifest, "candidate", {"preflight": sha256_file(preflight_path)}, [candidate_path])
        if pause_after == "candidate":
            return pause_run(run_root, manifest)

        refs = base_ref_list(units, research)
        variants = build_variants(request, candidate, refs, routes)
        variants_path = run_root / "artifacts" / "platform-fit-variants.json"
        write_json(variants_path, variants)
        record_stage(run_root, manifest, "variants", {"candidate": sha256_file(candidate_path)}, [variants_path])
        if pause_after == "variants":
            return pause_run(run_root, manifest)

        gate_report = build_gate_report(request, candidate, variants, warnings)
        gate_path = run_root / "artifacts" / "gate-report.json"
        write_json(gate_path, gate_report)
        record_stage(run_root, manifest, "gates", {"candidate": sha256_file(candidate_path), "variants": sha256_file(variants_path)}, [gate_path])
        if pause_after == "gates":
            return pause_run(run_root, manifest)

        review = build_review_packet(run_id, candidate, variants, gate_report, refs)
        review_path = run_root / "artifacts" / "review-packet.json"
        write_json(review_path, review)
        record_stage(run_root, manifest, "review", {"gates": sha256_file(gate_path)}, [review_path])
        manifest["status"] = "completed"
        manifest["current_stage"] = "review"
        manifest["resume_entry"] = None
        manifest["output_sha256"] = {
            "candidate": sha256_file(candidate_path),
            "variants": sha256_file(variants_path),
            "gates": sha256_file(gate_path),
            "review_packet": sha256_file(review_path),
        }
        write_json(manifest_path, manifest)
        return {"status": "completed", "closure_run_id": run_id, "manifest": repo_relative(manifest_path), "manifest_sha256": sha256_file(manifest_path), "review_packet": repo_relative(review_path)}
    except LoopError as exc:
        manifest["status"] = "blocked"
        manifest["failure_point"] = exc.stage
        manifest["error"] = {"code": exc.code, "message": str(exc)}
        manifest["resume_entry"] = None
        write_json(manifest_path, manifest)
        failure = {"schema_version": "small-model-content-failure.v1", "closure_run_id": run_id, "failure_point": exc.stage, "error_code": exc.code, "message": str(exc), "automatic_retries": 0, "status": "blocked"}
        write_json(run_root / "failure.json", failure)
        raise


def pause_run(run_root: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    manifest["status"] = "paused"
    manifest["resume_entry"] = f"python -B scripts/small_model_content_loop.py resume --run-root {repo_relative(run_root)}"
    write_json(run_root / "run-manifest.json", manifest)
    return {"status": "paused", "closure_run_id": manifest["closure_run_id"], "completed_stages": manifest["completed_stages"], "resume_entry": manifest["resume_entry"]}


def resume_loop(run_root: Path) -> dict[str, Any]:
    manifest_path = run_root.resolve() / "run-manifest.json"
    manifest = load_json(manifest_path)
    if manifest.get("status") != "paused":
        if manifest.get("status") == "completed":
            return {"status": "already_completed", "closure_run_id": manifest["closure_run_id"], "manifest": repo_relative(manifest_path), "manifest_sha256": sha256_file(manifest_path)}
        raise LoopError("resume_not_available", f"run status is {manifest.get('status')}")
    input_path = resolve_repo_ref(manifest["request_ref"])
    return run_loop(input_path, run_root.resolve(), manifest["closure_run_id"], pause_after=None)


def apply_mutation(value: dict[str, Any], dotted_path: str, replacement: Any) -> None:
    parts = dotted_path.split(".")
    current: Any = value
    for part in parts[:-1]:
        current = current[int(part)] if isinstance(current, list) else current[part]
    leaf = parts[-1]
    if isinstance(current, list):
        current[int(leaf)] = replacement
    else:
        current[leaf] = replacement


def check_negative_cases(cases_path: Path, run_root: Path) -> dict[str, Any]:
    cases_path = cases_path.resolve()
    run_root = run_root.resolve()
    repo_relative(cases_path)
    repo_relative(run_root)
    catalog = load_json(cases_path)
    base_path = resolve_repo_ref(catalog.get("base_fixture", ""))
    base = load_json(base_path)
    results: list[dict[str, Any]] = []
    for item in catalog.get("cases", []):
        case_id = item["case_id"]
        mutant = copy.deepcopy(base)
        apply_mutation(mutant, item["mutation"]["path"], item["mutation"].get("value"))
        input_path = run_root / "negative-inputs" / f"{case_id}.json"
        write_json(input_path, mutant)
        case_root = run_root / "cases" / case_id
        observed: str | None = None
        try:
            run_loop(input_path, case_root, closure_run_id=f"smcl-negative-{case_id}")
        except LoopError as exc:
            observed = exc.code
        expected = item.get("expected_errors", [])
        passed = observed in expected
        results.append({"case_id": case_id, "status": "pass" if passed else "fail", "observed_error": observed, "expected_errors": expected, "automatic_retries": 0})
    status = "pass" if len(results) >= 5 and all(item["status"] == "pass" for item in results) else "blocked"
    report = {
        "schema_version": "small-model-content-negative-report.v1",
        "status": status,
        "case_count": len(results),
        "results": results,
        "automatic_retries": 0,
        "boundaries": {"synthetic_only": True, "network": False, "provider_calls": False, "publication": "manual-only"},
    }
    report_path = run_root / "negative-report.json"
    write_json(report_path, report)
    if status != "pass":
        raise LoopError("negative_expectation_failed", "one or more negative cases did not fail closed")
    return {"status": "pass", "case_count": len(results), "report": repo_relative(report_path), "report_sha256": sha256_file(report_path)}


def doctor() -> dict[str, Any]:
    checks: dict[str, Any] = {}
    required = {
        "routing_contract_set": ROUTING_SET,
        "platform_overlays": PLATFORM_OVERLAYS,
        "content_item_schema": CONTENT_ITEM_SCHEMA,
        "loop_input_schema": INPUT_SCHEMA,
        "compact_handoff": COMPACT_HANDOFF,
        "human_voice_skill": HUMAN_VOICE_SKILL,
        "human_voice_rulebook": HUMAN_VOICE_RULEBOOK,
    }
    for name, path in required.items():
        checks[name] = {"status": "pass" if path.is_file() else "blocked", "ref": path.relative_to(WORKSPACE_ROOT).as_posix() if path.is_relative_to(WORKSPACE_ROOT) else str(path)}
    try:
        _contract, _overlays, routes = load_routing()
        checks["routing_semantics"] = {"status": "pass", "contract_version": ROUTING_CONTRACT_VERSION, "platform_count": len(routes)}
    except LoopError as exc:
        checks["routing_semantics"] = {"status": "blocked", "error_code": exc.code, "message": str(exc)}
    status = "pass" if all(item["status"] == "pass" for item in checks.values()) else "blocked"
    return {"schema_version": "small-model-content-loop-doctor.v1", "status": status, "checks": checks, "boundaries": {"provider_calls": False, "network": False, "publication": "manual-only", "automatic_retries": 0}}


def cli() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor")
    run = sub.add_parser("run")
    run.add_argument("--input", type=Path, required=True)
    run.add_argument("--run-root", type=Path, required=True)
    run.add_argument("--closure-run-id")
    run.add_argument("--pause-after", choices=STAGES)
    resume = sub.add_parser("resume")
    resume.add_argument("--run-root", type=Path, required=True)
    negatives = sub.add_parser("check-negatives")
    negatives.add_argument("--cases", type=Path, required=True)
    negatives.add_argument("--run-root", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "doctor":
            result = doctor()
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            return 0 if result["status"] == "pass" else 2
        if args.command == "run":
            result = run_loop(args.input, args.run_root, args.closure_run_id, args.pause_after)
        elif args.command == "check-negatives":
            result = check_negative_cases(args.cases, args.run_root)
        else:
            result = resume_loop(args.run_root)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except LoopError as exc:
        print(json.dumps({"status": "blocked", "error_code": exc.code, "failure_point": exc.stage, "message": str(exc), "automatic_retries": 0}, ensure_ascii=False, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(cli())
