#!/usr/bin/env python3
"""Generate and validate the fully synthetic content-loop fixture pack.

The pack reuses the canonical research-output, content-item, topic, account,
publication-event, and performance-snapshot contracts.  It intentionally does
not define another JSON Schema.  ``synthetic_only`` lives in the fixture
manifest and feedback handoff records because the canonical production
contracts reject unknown properties.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker


SYSTEM_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = SYSTEM_ROOT.parent
FIXTURES_ROOT = SYSTEM_ROOT / "fixtures"
DEFAULT_SEED = FIXTURES_ROOT / "vibe-living-synthetic-loop-v1.seed.json"
DEFAULT_OUTPUT = FIXTURES_ROOT / "vibe-living-synthetic-loop-v1"
CONTENT_STUDIO_ROOT = WORKSPACE_ROOT / "content-studio-poc"
ADAPTER_PATH = CONTENT_STUDIO_ROOT / "scripts" / "research_output_adapter.py"
RESEARCH_SCHEMA = WORKSPACE_ROOT / "question-research-poc" / "schemas" / "research-output.v1.schema.json"
CONTENT_SCHEMA = WORKSPACE_ROOT / "docs" / "content-creation-system" / "content-item.schema.json"
OPERATIONS_ROOT = WORKSPACE_ROOT / "docs" / "content-creation-system" / "operations"
ACCOUNT_SCHEMA = OPERATIONS_ROOT / "account.schema.json"
TOPIC_SCHEMA = OPERATIONS_ROOT / "topic.schema.json"
PUBLICATION_SCHEMA = OPERATIONS_ROOT / "publication-event.schema.json"
SNAPSHOT_SCHEMA = OPERATIONS_ROOT / "performance-snapshot.schema.json"
VIDEO_SCHEMA = CONTENT_STUDIO_ROOT / "schemas" / "content-video-brief.v1.schema.json"
FIXED_CREATED_AT = "2026-08-05T12:00:00+08:00"
CROCKFORD32 = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
QUALIFYING_CRM_EVENTS = {
    "continued_consultation",
    "necessary_documents_provided",
    "next_step_booked",
}


class PackError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise PackError("invalid_json_root", f"{path} must contain a JSON object")
    return value


def json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json_text(value), encoding="utf-8", newline="\n")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def stable_operation_id(prefix: str, seed: str) -> str:
    value = int.from_bytes(hashlib.sha256(seed.encode("utf-8")).digest(), "big") >> 126
    chars: list[str] = []
    for _ in range(26):
        chars.append(CROCKFORD32[value & 31])
        value >>= 5
    return f"{prefix}_{''.join(reversed(chars))}"


def stable_short_id(prefix: str, seed: str, length: int = 20) -> str:
    return f"{prefix}-{hashlib.sha256(seed.encode('utf-8')).hexdigest()[:length]}"


def import_adapter():
    scripts_path = str(CONTENT_STUDIO_ROOT / "scripts")
    if scripts_path not in sys.path:
        sys.path.insert(0, scripts_path)
    spec = importlib.util.spec_from_file_location("research_output_adapter_for_fixture_pack", ADAPTER_PATH)
    if not spec or not spec.loader:
        raise PackError("adapter_unavailable", f"cannot import adapter: {ADAPTER_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate_schema(instance: Any, schema_path: Path, label: str) -> None:
    schema = load_json(schema_path)
    Draft202012Validator.check_schema(schema)
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(instance),
        key=lambda error: [str(part) for part in error.absolute_path],
    )
    if not errors:
        return
    details = []
    for error in errors[:12]:
        where = ".".join(str(part) for part in error.absolute_path) or "$"
        details.append(f"{where}: {error.message}")
    raise PackError("schema_validation_failed", f"{label}: {'; '.join(details)}")


def source_markdown(spec: dict[str, Any]) -> str:
    return (
        "# Fully synthetic insurance question fixture\n\n"
        "synthetic_only: true\n\n"
        f"question_id: {spec['question_id']}\n\n"
        f"question: {spec['question']}\n\n"
        f"fixture_statement: {spec['source_excerpt']}\n\n"
        "This file is not evidence of real-world frequency, product status, customer behavior, or advice.\n"
    )


def build_research_output(spec: dict[str, Any], source_ref: str, source_sha256: str) -> dict[str, Any]:
    slug = spec["slug"]
    source_id = f"source_synthetic_{slug.replace('-', '_')}"
    claim_id = f"claim_synthetic_{slug.replace('-', '_')}"
    evidence_id = f"evidence_synthetic_{slug.replace('-', '_')}"
    research_id = f"research_synthetic_{slug.replace('-', '_')}"
    warning = "synthetic-only fixture; the frequency count and content do not describe real users or markets"
    return {
        "schema": "research-output.v1",
        "schema_version": "1.0.0",
        "research_id": research_id,
        "question": spec["question"],
        "scope": {
            "statement": "Fully synthetic insurance content-loop contract verification.",
            "constraints": ["synthetic-only", "no-external-api", "no-real-product", "no-real-customer"],
        },
        "audience": "synthetic insurance education reader",
        "requested_outputs": ["article", "content-video-brief.v1"],
        "sources": [
            {
                "source_id": source_id,
                "title": f"Synthetic source for {spec['question_id']}",
                "url": None,
                "archive_path": source_ref,
                "source_type": "local_fixture",
                "publisher": "Synthetic Insurance Fixture Lab",
                "fetched_at": FIXED_CREATED_AT,
                "freshness": "not_applicable",
                "hash": {"algorithm": "sha256", "value": source_sha256, "status": "verified"},
                "quality": "good",
                "review_status": "reviewed",
                "ref_status": "resolved",
                "provenance": {
                    "created_at": FIXED_CREATED_AT,
                    "review_refs": [f"review_{source_id}"],
                    "note_fields": {
                        "artifact_sha256": source_sha256,
                        "fetched_at": FIXED_CREATED_AT,
                        "freshness": "not_applicable",
                        "publisher": "Synthetic Insurance Fixture Lab",
                    },
                },
            }
        ],
        "claims": [
            {
                "claim_id": claim_id,
                "text": spec["thesis"],
                "claim_status": "open",
                "review_status": "verified",
                "evidence_status": "verified",
                "evidence_ids": [evidence_id],
                "supporting_evidence_ids": [evidence_id],
                "contradicting_evidence_ids": [],
                "context_evidence_ids": [],
                "source_ids": [source_id],
            }
        ],
        "evidence": [
            {
                "evidence_id": evidence_id,
                "claim_id": claim_id,
                "source_id": source_id,
                "relation": "supports",
                "evidence_status": "verified",
                "review_status": "reviewed",
                "confidence": "high",
                "excerpt": spec["source_excerpt"],
                "observed_at": FIXED_CREATED_AT,
                "source_path": source_ref,
                "artifact_sha256": source_sha256,
                "ai_synthesis": False,
            }
        ],
        "evidence_links": [
            {
                "evidence_id": evidence_id,
                "claim_id": claim_id,
                "source_id": source_id,
                "relation": "supports",
                "evidence_status": "verified",
            }
        ],
        "contradictions": [],
        "unknowns": [],
        "review_status": {
            "overall": "verified",
            "human_review_required": False,
            "events": [
                {
                    "kind": "source",
                    "target_id": source_id,
                    "decision": "good",
                    "reviewer": "synthetic-fixture-reviewer",
                    "reviewed_at": FIXED_CREATED_AT,
                },
                {
                    "kind": "evidence",
                    "target_id": evidence_id,
                    "decision": "verified",
                    "reviewer": "synthetic-fixture-reviewer",
                    "reviewed_at": FIXED_CREATED_AT,
                },
            ],
        },
        "evidence_status": {
            "overall": "verified",
            "counts": {"candidate": 0, "verified": 1, "rejected": 0, "contradictions": 0},
        },
        "completeness": {
            "ready_for_answer": True,
            "blocking_gates": [],
            "warnings": [warning],
            "coverage": {
                "source_count": 1,
                "source_types": ["local_fixture"],
                "unknown_source_quality": 0,
                "claim_count": 1,
                "claims_with_evidence": 1,
                "claims_with_verified_evidence": 1,
                "claims_with_verified_support_evidence": 1,
                "claims_with_counter_or_context": 0,
                "candidate_evidence": 0,
                "poor_source_evidence": 0,
                "review_queue_count": 0,
                "required_review_queue_count": 0,
                "human_review_count": 2,
                "draft_exists": False,
                "gate_audit_passed": False,
            },
        },
        "guarded_final_answer": {
            "status": "verified",
            "ready": True,
            "answer": f"- {spec['thesis']} [claim:{claim_id}; evidence:{evidence_id}; sources:{source_id}]",
            "claim_ids": [claim_id],
            "evidence_ids": [evidence_id],
            "source_ids": [source_id],
            "blocking_gates": [],
            "warnings": [warning],
            "guardrail": "Only synthetic, reviewed, non-synthesis fixture evidence is included; no real-world frequency or suitability conclusion is implied.",
        },
        "media_refs": [],
        "visual_leads": [],
        "quotable_facts": [],
        "provenance": {
            "input_files": [{"path": source_ref, "sha256": source_sha256, "status": "present"}],
            "source_systems": ["synthetic-fixture-generator"],
            "offline_only": True,
            "external_api_called": False,
            "model_memory_used_as_evidence": False,
        },
        "generator": {
            "name": "question-research-poc",
            "component": "research_output",
            "version": "research-output.v1",
        },
        "created_at": FIXED_CREATED_AT,
    }


def build_account(seed: dict[str, Any]) -> dict[str, Any]:
    account_id = stable_operation_id("acct", seed["account_seed"])
    return {
        "schema_version": "0.1",
        "account_id": account_id,
        "platform": "synthetic-surface",
        "platform_account_id": None,
        "display_name": "Synthetic Insurance Content Fixture",
        "account_role": "experiment",
        "status": "planning",
        "goal_ids": ["goal_01ARZ3NDEKTSV4RRFFQ69G5FBC"],
        "positioning": {
            "summary": "Fully synthetic account for offline contract tests only.",
            "audience_segments": ["synthetic insurance education reader"],
            "business_boundary": "No real account, customer, product, publication, or CRM write.",
        },
        "ownership": {
            "owner_ref": "synthetic-fixture",
            "manager_refs": [],
            "access_model": "single-owner",
            "last_permission_review_at": None,
        },
        "security": {
            "mfa_status": "unknown",
            "mfa_method": "unknown",
            "recovery_status": "unknown",
            "backup_codes_status": "unknown",
            "secret_location_class": "not-recorded",
            "last_security_review_at": None,
            "last_recovery_drill_at": None,
            "notes": "No credentials exist for this synthetic account.",
        },
        "source_refs": [
            {
                "ref": "fixture://vibe-living-synthetic-loop-v1/seed",
                "evidence_status": "local-fact",
                "note": "Synthetic fixture seed only.",
            }
        ],
        "created_at": FIXED_CREATED_AT,
        "updated_at": FIXED_CREATED_AT,
    }


def build_topic(spec: dict[str, Any], account_id: str, research_ref: str) -> dict[str, Any]:
    topic_id = stable_operation_id("topic", spec["question_id"])
    return {
        "schema_version": "0.1",
        "topic_id": topic_id,
        "title": spec["question"],
        "status": "qualified",
        "audience_problem": spec["audience_problem"],
        "goal_ids": ["goal_01ARZ3NDEKTSV4RRFFQ69G5FBC"],
        "target_account_ids": [account_id],
        "relationship_types": ["answers-question", "reuses-evidence"],
        "parent_topic_id": None,
        "cluster_key": "synthetic-high-frequency-insurance-questions",
        "evidence_status": "candidate",
        "source_refs": [
            {
                "source_type": "workspace-file",
                "ref": research_ref,
                "evidence_status": "verified",
                "note": "Verified as a synthetic fixture artifact only; it does not prove real-world frequency.",
            }
        ],
        "notes": (
            f"synthetic_frequency_count={spec['synthetic_frequency_count']}; "
            "rank is fixture input, not audience research or platform evidence."
        ),
        "created_at": FIXED_CREATED_AT,
        "updated_at": FIXED_CREATED_AT,
    }


def add_fixture_qa(content: dict[str, Any]) -> None:
    checks = content["qa"]["deterministic"]
    checks.append(
        {
            "name": "synthetic-only-boundary",
            "status": "pass",
            "details": "Fixture contains no real customer, product, account, publication, or platform data.",
        }
    )


def derive_content_snapshots(
    adapter_content: dict[str, Any], account_id: str, topic_id: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    draft = copy.deepcopy(adapter_content)
    draft["status"] = "draft"
    draft["updated_at"] = FIXED_CREATED_AT
    draft["tags"] = sorted(set(draft.get("tags", []) + ["synthetic-only", "draft-only"]))
    draft["operating_refs"] = {"account_ids": [account_id], "topic_ids": [topic_id]}
    draft["channels"]["article"]["status"] = "draft"
    draft["publication"] = {"boundary": "manual-only", "receipts": []}
    draft["feedback"] = {
        "signal_status": "not-observed",
        "platform_signals": {},
        "business_signals": {},
        "learning_decision": "none",
        "content_signal_status": "not-observed",
        "business_signal_status": "not-observed",
        "next_test": "Synthetic publication fixtures are evaluated separately; this draft remains draft_only.",
    }
    add_fixture_qa(draft)

    material = copy.deepcopy(draft)
    material["status"] = "candidate"
    material["tags"] = sorted(set(material["tags"] + ["material-stage"]))
    material["composition"].pop("canonical_body", None)
    material["composition"].pop("canonical_body_ref", None)
    material["composition"]["retention_mode"] = "summary-only"
    material["channels"]["article"]["status"] = "not-started"
    material["channels"]["article"].pop("body_ref", None)
    return material, draft


def publication_times(case_index: int) -> tuple[datetime, datetime, datetime]:
    published = datetime.fromisoformat(FIXED_CREATED_AT) + timedelta(days=case_index * 10, minutes=1)
    return published, published + timedelta(hours=60), published + timedelta(days=7)


def build_performance_snapshots(case: dict[str, Any], publication_id: str, case_index: int) -> list[dict[str, Any]]:
    _, early_time, d7_time = publication_times(case_index)
    if case["feedback_type"] == "no_signal":
        early_metrics = [
            {
                "metric_key": "impressions",
                "value": None,
                "unit": "count",
                "dimensions": {"synthetic": True},
                "unavailable_reason": "Synthetic observation unavailable.",
            }
        ]
        d7_metrics = copy.deepcopy(early_metrics)
        completeness = "unavailable"
        missing = ["Synthetic fixture intentionally provides no observable platform metrics."]
    elif case["feedback_type"] == "ordinary_content_engagement":
        early_metrics = [
            {"metric_key": "views", "value": 120, "unit": "count", "dimensions": {"synthetic": True}},
            {"metric_key": "likes", "value": 8, "unit": "count", "dimensions": {"synthetic": True}},
            {"metric_key": "saves", "value": 3, "unit": "count", "dimensions": {"synthetic": True}},
        ]
        d7_metrics = [
            {"metric_key": "views", "value": 170, "unit": "count", "dimensions": {"synthetic": True}},
            {"metric_key": "likes", "value": 10, "unit": "count", "dimensions": {"synthetic": True}},
            {"metric_key": "saves", "value": 5, "unit": "count", "dimensions": {"synthetic": True}},
        ]
        completeness = "complete"
        missing = []
    else:
        early_metrics = [
            {"metric_key": "views", "value": 90, "unit": "count", "dimensions": {"synthetic": True}},
            {"metric_key": "likes", "value": 4, "unit": "count", "dimensions": {"synthetic": True}},
        ]
        d7_metrics = [
            {"metric_key": "views", "value": 105, "unit": "count", "dimensions": {"synthetic": True}},
            {"metric_key": "likes", "value": 4, "unit": "count", "dimensions": {"synthetic": True}},
        ]
        completeness = "complete"
        missing = []

    snapshots = []
    for label, as_of, metrics in (("early", early_time, early_metrics), ("d7", d7_time, d7_metrics)):
        snapshot = {
            "schema_version": "0.1",
            "snapshot_id": stable_operation_id("snap", f"{case['case_id']}:{label}"),
            "publication_id": publication_id,
            "as_of": as_of.isoformat(),
            "captured_at": (as_of + timedelta(minutes=1)).isoformat(),
            "window_label": label,
            "timezone": "Asia/Shanghai",
            "metric_dictionary_version": "synthetic.content-signals.0.1",
            "source_type": "other",
            "data_completeness": completeness,
            "metrics": metrics,
            "notes": "Fully synthetic metrics for offline contract verification only.",
        }
        if missing:
            snapshot["missing_reasons"] = missing
        snapshots.append(snapshot)
    return snapshots


def build_feedback_record(
    case: dict[str, Any], content_id: str, publication_id: str, snapshots: list[dict[str, Any]]
) -> dict[str, Any]:
    evidence_refs = [f"snapshot:{item['snapshot_id']}" for item in snapshots]
    record: dict[str, Any] = {
        "feedback_contract": "insurance-client-action-recording-decision-2026-06-22",
        "synthetic_only": True,
        "feedback_id": stable_short_id("feedback", case["case_id"]),
        "content_id": content_id,
        "published_content_ref": publication_id,
        "source_service_card_id": f"synthetic-service-card-{case['case_id']}",
        "material_reuse_level": "first_use",
        "feedback_type": case["feedback_type"],
        "sanitized_summary": case["summary"],
        "privacy_status": "synthetic_only",
        "evidence_refs": evidence_refs,
        "signal_layer": case["expected_signal_layer"],
        "content_observation": {
            "status": "content_no_signal" if case["feedback_type"] == "no_signal" else "observed",
            "interpretation": "insufficient-evidence" if case["feedback_type"] == "no_signal" else "content-metrics-only",
        },
        "relationship_signal": {
            "eligible": False,
            "reason": "Views, likes, saves, and no_signal do not establish a relationship signal.",
        },
        "qualifying_business_evidence": [],
        "crm_candidate": {"eligible": False, "reason": "No explicit qualifying business event."},
        "review_status": "reviewed",
        "manual_confirmation_required": False,
        "analysis_only": True,
        "execution_allowed": False,
        "do_not_auto_contact": True,
        "no_geolocation_detail": True,
        "no_time_sequence_fingerprint": True,
        "no_relationship_graph_trace": True,
        "next_waiting_on": "content_review_only",
    }
    if case["feedback_type"] in QUALIFYING_CRM_EVENTS:
        event_ref = f"synthetic-feedback-event:{case['case_id']}:{case['feedback_type']}"
        record["evidence_refs"].append(event_ref)
        record["qualifying_business_evidence"] = [
            {
                "event_type": case["feedback_type"],
                "event_ref": event_ref,
                "review_status": "reviewed_synthetic_evidence",
            }
        ]
        record["crm_candidate"] = {
            "eligible": True,
            "status": "pending_human_confirmation",
            "manual_confirmation_required": True,
            "confirmed": False,
            "reason": "An explicit qualifying synthetic event exists; no CRM record or action is created.",
        }
        record["review_status"] = "pending_human_confirmation"
        record["manual_confirmation_required"] = True
        record["next_waiting_on"] = "human_confirmation"
        record["content_observation"]["interpretation"] = "content-metrics-remain-separate-from-business-evidence"
    return record


def build_publication_case(
    case: dict[str, Any], question_entry: dict[str, Any], draft_path: Path, case_index: int
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    content_id = question_entry["content_id"]
    publication_id = stable_operation_id("pub", case["case_id"])
    version_id = stable_operation_id("ver", f"{case['case_id']}:v1")
    prepared_id = stable_operation_id("evt", f"{case['case_id']}:prepared")
    published_id = stable_operation_id("evt", f"{case['case_id']}:published")
    account_id = question_entry["account_id"]
    published, _, _ = publication_times(case_index)
    draft = load_json(draft_path)
    body_ref = question_entry["article_ref"]
    body_path = draft_path.parent / "adapter" / Path(body_ref).name
    body_sha = sha256_file(body_path)
    events = [
        {
            "schema_version": "0.1",
            "event_id": prepared_id,
            "publication_id": publication_id,
            "event_sequence": 1,
            "content_id": content_id,
            "version_id": version_id,
            "account_id": account_id,
            "platform": "synthetic-surface",
            "platform_content_id": None,
            "canonical_url": None,
            "event_type": "prepared",
            "occurred_at": (published - timedelta(minutes=1)).isoformat(),
            "recorded_at": (published - timedelta(minutes=1)).isoformat(),
            "actor_type": "local-tool",
            "evidence_status": "local-record",
            "supersedes_event_id": None,
            "reason": "Synthetic prepared event; no publication occurred.",
        },
        {
            "schema_version": "0.1",
            "event_id": published_id,
            "publication_id": publication_id,
            "event_sequence": 2,
            "content_id": content_id,
            "version_id": version_id,
            "account_id": account_id,
            "platform": "synthetic-surface",
            "platform_content_id": None,
            "canonical_url": None,
            "event_type": "published",
            "occurred_at": published.isoformat(),
            "recorded_at": published.isoformat(),
            "actor_type": "local-tool",
            "evidence_status": "local-record",
            "supersedes_event_id": prepared_id,
            "reason": "Synthetic published event used only to exercise the feedback contract.",
            "frozen_version": {
                "title": draft["title"],
                "channel_variant": "synthetic-article",
                "freeze_status": "complete",
                "body_ref": body_ref,
                "body_sha256": body_sha,
                "cover_refs": [],
                "media_refs": [],
                "cta": None,
                "unavailable_reason": None,
                "frozen_at": published.isoformat(),
            },
        },
    ]
    snapshots = build_performance_snapshots(case, publication_id, case_index)
    feedback = build_feedback_record(case, content_id, publication_id, snapshots)
    return events, snapshots, feedback


def negative_descriptors() -> dict[str, Any]:
    return {
        "synthetic_only": True,
        "base_pack_ref": "consumer-manifest.json",
        "cases": [
            {
                "id": "no-signal-promoted-to-crm",
                "base_case": "pf-content-no-signal",
                "mutation": "promote_no_signal_to_crm",
                "expected_code": "no_signal_scope_violation",
            },
            {
                "id": "engagement-promoted-to-relationship",
                "base_case": "pf-ordinary-content-engagement",
                "mutation": "promote_metrics_to_relationship",
                "expected_code": "content_metrics_scope_violation",
            },
            {
                "id": "engagement-promoted-to-crm",
                "base_case": "pf-ordinary-content-engagement",
                "mutation": "promote_metrics_to_crm",
                "expected_code": "content_metrics_scope_violation",
            },
            {
                "id": "crm-candidate-without-qualifying-event",
                "base_case": "pf-explicit-business-signal",
                "mutation": "remove_qualifying_business_evidence",
                "expected_code": "crm_candidate_missing_qualifying_evidence",
            },
            {
                "id": "crm-candidate-without-manual-confirmation",
                "base_case": "pf-explicit-business-signal",
                "mutation": "disable_manual_confirmation",
                "expected_code": "crm_candidate_manual_gate_required",
            },
            {
                "id": "non-synthetic-feedback",
                "base_case": "pf-content-no-signal",
                "mutation": "disable_synthetic_only",
                "expected_code": "synthetic_only_required",
            },
        ],
    }


def validate_feedback_record(record: dict[str, Any]) -> None:
    if record.get("synthetic_only") is not True:
        raise PackError("synthetic_only_required", "feedback record must be synthetic_only=true")
    if record.get("analysis_only") is not True or record.get("execution_allowed") is not False:
        raise PackError("execution_boundary_violation", "feedback handoff must remain analysis-only")
    if record.get("do_not_auto_contact") is not True:
        raise PackError("auto_contact_boundary_violation", "feedback handoff must prohibit contact")

    feedback_type = record.get("feedback_type")
    layer = record.get("signal_layer")
    relationship = record.get("relationship_signal", {})
    crm = record.get("crm_candidate", {})
    if feedback_type == "no_signal" and layer != "content_observation":
        raise PackError("no_signal_scope_violation", "content_no_signal must stay in content_observation")
    if feedback_type in {"no_signal", "ordinary_content_engagement"}:
        if relationship.get("eligible") or crm.get("eligible") or layer != "content_observation":
            raise PackError(
                "content_metrics_scope_violation",
                "views, likes, saves, and no_signal cannot create relationship or CRM signals",
            )
    if layer == "crm_candidate":
        evidence = record.get("qualifying_business_evidence", [])
        if not evidence or any(item.get("event_type") not in QUALIFYING_CRM_EVENTS for item in evidence):
            raise PackError(
                "crm_candidate_missing_qualifying_evidence",
                "crm_candidate needs continued consultation, necessary documents, or a booked next step",
            )
        if record.get("manual_confirmation_required") is not True:
            raise PackError("crm_candidate_manual_gate_required", "crm_candidate requires manual confirmation")
        if crm.get("manual_confirmation_required") is not True or crm.get("confirmed") is not False:
            raise PackError("crm_candidate_manual_gate_required", "CRM candidate must stay unconfirmed")
        if crm.get("status") != "pending_human_confirmation":
            raise PackError("crm_candidate_manual_gate_required", "CRM candidate must remain pending")


def apply_negative_mutation(record: dict[str, Any], mutation: str) -> dict[str, Any]:
    candidate = copy.deepcopy(record)
    if mutation == "promote_no_signal_to_crm":
        candidate["signal_layer"] = "crm_candidate"
        candidate["crm_candidate"] = {"eligible": True}
    elif mutation == "promote_metrics_to_relationship":
        candidate["signal_layer"] = "relationship_signal"
        candidate["relationship_signal"] = {"eligible": True}
    elif mutation == "promote_metrics_to_crm":
        candidate["signal_layer"] = "crm_candidate"
        candidate["crm_candidate"] = {"eligible": True}
    elif mutation == "remove_qualifying_business_evidence":
        candidate["qualifying_business_evidence"] = []
    elif mutation == "disable_manual_confirmation":
        candidate["manual_confirmation_required"] = False
        candidate["crm_candidate"]["manual_confirmation_required"] = False
    elif mutation == "disable_synthetic_only":
        candidate["synthetic_only"] = False
    else:
        raise PackError("unknown_negative_mutation", mutation)
    return candidate


def ensure_safe_generated_target(path: Path) -> Path:
    resolved = path.resolve()
    allowed_roots = [(FIXTURES_ROOT).resolve(), (SYSTEM_ROOT / "tests").resolve()]
    if not any(resolved == root or root in resolved.parents for root in allowed_roots):
        raise PackError("unsafe_output_root", f"generated output must stay under fixtures/ or tests/: {resolved}")
    return resolved


def reset_generated_dir(path: Path) -> None:
    resolved = ensure_safe_generated_target(path)
    if resolved.exists():
        shutil.rmtree(resolved)
    resolved.mkdir(parents=True, exist_ok=True)


def generate_pack(seed_path: Path = DEFAULT_SEED, output_root: Path = DEFAULT_OUTPUT) -> dict[str, Any]:
    seed = load_json(seed_path)
    if seed.get("synthetic_only") is not True or seed.get("mode") != "draft_only":
        raise PackError("invalid_seed_boundary", "seed must be synthetic_only and draft_only")
    for required in (RESEARCH_SCHEMA, CONTENT_SCHEMA, ACCOUNT_SCHEMA, TOPIC_SCHEMA, PUBLICATION_SCHEMA, SNAPSHOT_SCHEMA, VIDEO_SCHEMA, ADAPTER_PATH):
        if not required.is_file():
            raise PackError("missing_canonical_dependency", str(required))

    output_root = ensure_safe_generated_target(output_root)
    staging = output_root.with_name(f".{output_root.name}.staging")
    reset_generated_dir(staging)
    adapter = import_adapter()

    account = build_account(seed)
    validate_schema(account, ACCOUNT_SCHEMA, "account")
    write_json(staging / "account.json", account)

    question_entries: list[dict[str, Any]] = []
    by_slug: dict[str, dict[str, Any]] = {}
    for spec in seed["questions"]:
        question_dir = staging / "questions" / spec["slug"]
        source_path = question_dir / "sources" / "synthetic-source.md"
        source_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_text(source_markdown(spec), encoding="utf-8", newline="\n")
        source_ref = "sources/synthetic-source.md"
        research = build_research_output(spec, source_ref, sha256_file(source_path))
        validate_schema(research, RESEARCH_SCHEMA, f"research:{spec['slug']}")
        adapter.validate_research_semantics(research)
        research_path = question_dir / "research-output.v1.json"
        write_json(research_path, research)

        adapter_dir = question_dir / "adapter"
        result = adapter.adapt_research_output(
            research_path,
            adapter_dir,
            RESEARCH_SCHEMA,
            CONTENT_SCHEMA,
            VIDEO_SCHEMA,
        )
        adapter_content_path = next(adapter_dir.glob("*.content-item.json"))
        adapter_content = load_json(adapter_content_path)
        topic = build_topic(
            spec,
            account["account_id"],
            f"fixture://vibe-living-synthetic-loop-v1/questions/{spec['slug']}/research-output.v1.json",
        )
        validate_schema(topic, TOPIC_SCHEMA, f"topic:{spec['slug']}")
        material, draft = derive_content_snapshots(adapter_content, account["account_id"], topic["topic_id"])
        validate_schema(material, CONTENT_SCHEMA, f"material:{spec['slug']}")
        validate_schema(draft, CONTENT_SCHEMA, f"draft:{spec['slug']}")
        write_json(question_dir / "topic.json", topic)
        write_json(question_dir / "material.content-item.json", material)
        write_json(question_dir / "draft.content-item.json", draft)

        article_path = next(adapter_dir.glob("*.article.md"))
        video_path = next(adapter_dir.glob("*.content-video-brief.json"))
        entry = {
            "question_id": spec["question_id"],
            "slug": spec["slug"],
            "synthetic_only": True,
            "frequency_status": "synthetic_priority_only_not_real_frequency",
            "synthetic_frequency_count": spec["synthetic_frequency_count"],
            "account_id": account["account_id"],
            "topic_id": topic["topic_id"],
            "content_id": draft["content_id"],
            "research_output_ref": f"questions/{spec['slug']}/research-output.v1.json",
            "topic_ref": f"questions/{spec['slug']}/topic.json",
            "material_ref": f"questions/{spec['slug']}/material.content-item.json",
            "content_draft_ref": f"questions/{spec['slug']}/draft.content-item.json",
            "article_ref": f"questions/{spec['slug']}/adapter/{article_path.name}",
            "video_brief_ref": f"questions/{spec['slug']}/adapter/{video_path.name}",
            "adapter_status": result["status"],
            "review_status": "human_review_required",
        }
        question_entries.append(entry)
        by_slug[spec["slug"]] = entry

    feedback_entries: list[dict[str, Any]] = []
    for index, case in enumerate(seed["publication_feedback_cases"]):
        question_entry = by_slug[case["question_slug"]]
        case_dir = staging / "publication-feedback" / case["case_id"]
        draft_path = staging / question_entry["content_draft_ref"]
        events, snapshots, feedback = build_publication_case(case, question_entry, draft_path, index)
        for event_index, event in enumerate(events):
            validate_schema(event, PUBLICATION_SCHEMA, f"{case['case_id']}.events[{event_index}]")
        for snapshot_index, snapshot in enumerate(snapshots):
            validate_schema(snapshot, SNAPSHOT_SCHEMA, f"{case['case_id']}.snapshots[{snapshot_index}]")
        validate_feedback_record(feedback)
        write_json(case_dir / "publication-events.json", {"synthetic_only": True, "items": events})
        write_json(case_dir / "performance-snapshots.json", {"synthetic_only": True, "items": snapshots})
        write_json(case_dir / "feedback-handoff.json", feedback)
        feedback_entries.append(
            {
                "case_id": case["case_id"],
                "synthetic_only": True,
                "content_id": question_entry["content_id"],
                "publication_id": events[0]["publication_id"],
                "publication_events_ref": f"publication-feedback/{case['case_id']}/publication-events.json",
                "performance_snapshots_ref": f"publication-feedback/{case['case_id']}/performance-snapshots.json",
                "feedback_handoff_ref": f"publication-feedback/{case['case_id']}/feedback-handoff.json",
                "expected_signal_layer": case["expected_signal_layer"],
                "review_status": feedback["review_status"],
            }
        )

    negatives = negative_descriptors()
    write_json(staging / "negative-cases.json", negatives)
    schema_refs = []
    for path in (RESEARCH_SCHEMA, CONTENT_SCHEMA, ACCOUNT_SCHEMA, TOPIC_SCHEMA, PUBLICATION_SCHEMA, SNAPSHOT_SCHEMA, VIDEO_SCHEMA):
        schema_refs.append(
            {
                "path": path.relative_to(WORKSPACE_ROOT).as_posix(),
                "sha256": sha256_file(path),
            }
        )

    manifest = {
        "fixture_pack": seed["fixture_pack"],
        "synthetic_only": True,
        "mode": "draft_only",
        "generated_at": seed["generated_at"],
        "no_parallel_schema_created": True,
        "canonical_contracts": schema_refs,
        "fixture_classification": {
            "policy": "synthetic_only is carried by this manifest and every handoff record because canonical production schemas use additionalProperties=false.",
            "real_world_frequency_claimed": False,
            "real_customer_data_used": False,
            "real_product_data_used": False,
            "real_account_or_platform_data_used": False,
            "external_api_called": False,
            "published": False,
        },
        "account": {
            "synthetic_only": True,
            "account_id": account["account_id"],
            "artifact_ref": "account.json",
            "contract_ref": "docs/content-creation-system/operations/account.schema.json",
        },
        "questions": question_entries,
        "publication_feedback_cases": feedback_entries,
        "negative_cases_ref": "negative-cases.json",
        "consumer_policy": {
            "content_no_signal_layer": "content_observation",
            "content_metrics_are_relationship_signal": False,
            "content_metrics_are_crm_candidate": False,
            "crm_qualifying_events": sorted(QUALIFYING_CRM_EVENTS),
            "crm_candidate_requires_manual_confirmation": True,
            "analysis_only": True,
            "execution_allowed": False,
            "do_not_auto_contact": True,
        },
        "artifact_index": [],
    }
    artifact_paths = sorted(
        path for path in staging.rglob("*") if path.is_file() and path.name != "consumer-manifest.json"
    )
    manifest["artifact_index"] = [
        {"path": path.relative_to(staging).as_posix(), "sha256": sha256_file(path)}
        for path in artifact_paths
    ]
    write_json(staging / "consumer-manifest.json", manifest)
    validate_pack(staging)

    if output_root.exists():
        shutil.rmtree(output_root)
    staging.replace(output_root)
    return {
        "status": "generated_synthetic_only",
        "output_root": str(output_root),
        "consumer_entry": str(output_root / "consumer-manifest.json"),
        "question_count": len(question_entries),
        "feedback_case_count": len(feedback_entries),
        "payload_sha256": sha256_file(output_root / "consumer-manifest.json"),
    }


def validate_pack(root: Path = DEFAULT_OUTPUT) -> list[str]:
    errors: list[str] = []
    try:
        manifest = load_json(root / "consumer-manifest.json")
        if manifest.get("synthetic_only") is not True or manifest.get("mode") != "draft_only":
            raise PackError("manifest_boundary_violation", "manifest must be synthetic_only and draft_only")
        if manifest.get("no_parallel_schema_created") is not True:
            raise PackError("parallel_schema_violation", "fixture pack must reuse canonical contracts")
        if len(manifest.get("questions", [])) != 5:
            raise PackError("question_count_mismatch", "fixture pack must contain five questions")
        if len(manifest.get("publication_feedback_cases", [])) != 3:
            raise PackError("feedback_case_count_mismatch", "fixture pack must contain three feedback cases")
        account = load_json(root / manifest["account"]["artifact_ref"])
        validate_schema(account, ACCOUNT_SCHEMA, "account")

        for entry in manifest["questions"]:
            if entry.get("synthetic_only") is not True:
                raise PackError("synthetic_only_required", f"question entry {entry.get('question_id')} is not synthetic")
            topic = load_json(root / entry["topic_ref"])
            material = load_json(root / entry["material_ref"])
            draft = load_json(root / entry["content_draft_ref"])
            research = load_json(root / entry["research_output_ref"])
            validate_schema(topic, TOPIC_SCHEMA, entry["topic_ref"])
            validate_schema(material, CONTENT_SCHEMA, entry["material_ref"])
            validate_schema(draft, CONTENT_SCHEMA, entry["content_draft_ref"])
            validate_schema(research, RESEARCH_SCHEMA, entry["research_output_ref"])
            if material["content_id"] != draft["content_id"] or draft["content_id"] != entry["content_id"]:
                raise PackError("content_id_lifecycle_mismatch", entry["question_id"])
            if material["status"] != "candidate" or draft["status"] != "draft":
                raise PackError("content_lifecycle_state_mismatch", entry["question_id"])
            if draft["publication"] != {"boundary": "manual-only", "receipts": []}:
                raise PackError("draft_publication_boundary_violation", entry["question_id"])
            if draft["operating_refs"].get("topic_ids") != [topic["topic_id"]]:
                raise PackError("topic_reference_mismatch", entry["question_id"])

        feedback_by_case: dict[str, dict[str, Any]] = {}
        for entry in manifest["publication_feedback_cases"]:
            if entry.get("synthetic_only") is not True:
                raise PackError("synthetic_only_required", entry["case_id"])
            event_bundle = load_json(root / entry["publication_events_ref"])
            snapshot_bundle = load_json(root / entry["performance_snapshots_ref"])
            feedback = load_json(root / entry["feedback_handoff_ref"])
            if event_bundle.get("synthetic_only") is not True or snapshot_bundle.get("synthetic_only") is not True:
                raise PackError("synthetic_only_required", entry["case_id"])
            for event in event_bundle["items"]:
                validate_schema(event, PUBLICATION_SCHEMA, entry["case_id"])
            for snapshot in snapshot_bundle["items"]:
                validate_schema(snapshot, SNAPSHOT_SCHEMA, entry["case_id"])
            validate_feedback_record(feedback)
            if feedback["signal_layer"] != entry["expected_signal_layer"]:
                raise PackError("feedback_layer_mismatch", entry["case_id"])
            feedback_by_case[entry["case_id"]] = feedback

        negative = load_json(root / manifest["negative_cases_ref"])
        for case in negative["cases"]:
            mutated = apply_negative_mutation(feedback_by_case[case["base_case"]], case["mutation"])
            try:
                validate_feedback_record(mutated)
            except PackError as error:
                if error.code != case["expected_code"]:
                    raise PackError(
                        "negative_case_wrong_failure",
                        f"{case['id']} expected {case['expected_code']} but got {error.code}",
                    ) from error
            else:
                raise PackError("negative_case_not_rejected", case["id"])

        for artifact in manifest["artifact_index"]:
            path = root / artifact["path"]
            if not path.is_file():
                raise PackError("artifact_missing", artifact["path"])
            if sha256_file(path) != artifact["sha256"]:
                raise PackError("artifact_hash_mismatch", artifact["path"])
    except (KeyError, TypeError, ValueError, PackError) as error:
        if isinstance(error, PackError):
            errors.append(f"{error.code}: {error}")
        else:
            errors.append(f"invalid_pack: {error}")
    return errors


def file_map(root: Path) -> dict[str, bytes]:
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def idempotency_check(seed_path: Path = DEFAULT_SEED) -> list[str]:
    run_a = SYSTEM_ROOT / "tests" / ".tmp-vibe-living-pack-a"
    run_b = SYSTEM_ROOT / "tests" / ".tmp-vibe-living-pack-b"
    errors: list[str] = []
    try:
        generate_pack(seed_path, run_a)
        generate_pack(seed_path, run_b)
        if file_map(run_a) != file_map(run_b):
            errors.append("double generation is not byte-for-byte stable")
    finally:
        for path in (run_a, run_b):
            if path.exists():
                shutil.rmtree(path)
    return errors


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    generate = subparsers.add_parser("generate")
    generate.add_argument("--seed", type=Path, default=DEFAULT_SEED)
    generate.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    validate = subparsers.add_parser("validate")
    validate.add_argument("--root", type=Path, default=DEFAULT_OUTPUT)
    check = subparsers.add_parser("check")
    check.add_argument("--seed", type=Path, default=DEFAULT_SEED)
    check.add_argument("--root", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.command == "generate":
            print(json_text(generate_pack(args.seed, args.output_root)), end="")
            return 0
        errors = validate_pack(args.root)
        if args.command == "check":
            errors.extend(idempotency_check(args.seed))
        if errors:
            print(json_text({"status": "failed", "errors": errors}), end="", file=sys.stderr)
            return 1
        print(
            json_text(
                {
                    "status": "passed",
                    "root": str(args.root),
                    "synthetic_only": True,
                    "question_count": 5,
                    "feedback_case_count": 3,
                    "idempotency": "passed" if args.command == "check" else "not-run",
                }
            ),
            end="",
        )
        return 0
    except PackError as error:
        print(json_text({"status": error.code, "message": str(error)}), end="", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
