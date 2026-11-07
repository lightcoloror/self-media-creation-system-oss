#!/usr/bin/env python3
"""Append-only daily content-operations adapter over the canonical contracts.

The adapter records manual publication, observation, deidentified interaction,
human lead review, and draft operating-review operations.  It reuses the
existing publication-feedback helpers and the workspace atomic 14-contract
set.  It never opens a platform, contacts anyone, writes CRM, or publishes.
"""

from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import os
import re
import shutil
import sys
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = ROOT.parent
SCRIPTS_ROOT = Path(__file__).resolve().parent
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

import publication_feedback_tracker as tracker  # noqa: E402


CONTRACT_VALIDATOR_PATH = WORKSPACE_ROOT / "scripts" / "validate-content-operations.py"
CONTRACT_ROOT = WORKSPACE_ROOT / "docs" / "content-creation-system"
CONTENT_SCHEMA = CONTRACT_ROOT / "content-item.schema.json"
DEFAULT_FIXTURE_ROOT = ROOT / "fixtures" / "content-operations-cycle-v1"
PRIVATE_STORE_ROOTS = (
    ROOT / ".runtime" / "content-operations",
    ROOT / "tests" / ".runtime" / "content-operations",
)
STORE_METADATA_FILE = "store-metadata.json"
STORE_ANCHOR_FILE = "store-anchor.json"
STORE_METADATA_VERSION = "content-operations-cycle.store-metadata.v1"
STORE_ANCHOR_VERSION = "content-operations-cycle.store-anchor.v1"
STORE_CHECKPOINT_VERSION = "content-operations-cycle.external-checkpoint.v1"
STORE_CHECKPOINT_FILE = "anchor-journal.jsonl"
HEAD_FILES = {
    "publication-event": "publication-events.json",
    "performance-snapshot": "performance-snapshots.json",
    "interaction-event": "interaction-events.json",
    "lead-event": "lead-events.json",
    "experiment-run": "experiment-runs.json",
    "diagnostic-run": "diagnostic-runs.json",
    "resource-ledger-event": "resource-ledger-events.json",
    "revenue-attribution-event": "revenue-attribution-events.json",
    "account-continuity-plan": "account-continuity-plans.json",
    "account-security-event": "account-security-events.json",
    "operating-review": "operating-reviews.json",
}
JOURNAL_SCHEMA_VERSION = "content-operations-cycle.journal.v1"
HEADS_SCHEMA_VERSION = "content-operations-cycle.heads.v1"
INPUT_VERSIONS = {
    "record-publication": "content-operations-cycle.publication-input.v1",
    "record-publication-edit": "content-operations-cycle.publication-edit-input.v1",
    "record-publication-delete": "content-operations-cycle.publication-delete-input.v1",
    "record-publication-restore": "content-operations-cycle.publication-restore-input.v1",
    "record-snapshot": "content-operations-cycle.snapshot-input.v1",
    "record-interaction": "content-operations-cycle.interaction-input.v1",
    "review-lead": "content-operations-cycle.lead-review-input.v1",
    "record-experiment": "content-operations-cycle.experiment-input.v1",
    "record-diagnostic": "content-operations-cycle.diagnostic-input.v1",
    "record-resource": "content-operations-cycle.resource-input.v1",
    "record-revenue": "content-operations-cycle.revenue-input.v1",
    "record-continuity": "content-operations-cycle.continuity-input.v1",
    "record-security": "content-operations-cycle.security-input.v1",
    "build-review": "content-operations-cycle.review-input.v1",
}
CONTRACT_RECORD_OPERATIONS = {
    "record-experiment": ("experiment-run", "experiment_run_id"),
    "record-diagnostic": ("diagnostic-run", "diagnostic_run_id"),
    "record-resource": ("resource-ledger-event", "resource_event_id"),
    "record-revenue": ("revenue-attribution-event", "revenue_event_id"),
    "record-continuity": ("account-continuity-plan", "continuity_plan_id"),
    "record-security": ("account-security-event", "security_event_id"),
}
DATA_CLASSIFICATIONS = {"synthetic-only", "deidentified-operational"}
HEX_SHA256 = re.compile(r"^[a-f0-9]{64}$")
REVIEW_CREDENTIAL_AUTHORITY = {
    "execution_authorized": False,
    "publication_authority": "never",
    "external_send_authorized": False,
    "crm_write_authorized": False,
    "contact_authorized": False,
}
OBVIOUS_SENSITIVE_PATTERNS = (
    re.compile(r"(?i)https?://\S+"),
    re.compile(r"(?i)(?<![A-Z0-9._%+-])[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}(?![A-Z0-9._%+-])"),
    re.compile(r"(?<![0-9A-Za-z])1[3-9][0-9]{9}(?![0-9A-Za-z])"),
    re.compile(r"(?<![0-9A-Za-z])[0-9]{17}[0-9Xx](?![0-9A-Za-z])"),
    re.compile(r"(?i)(?:[A-Z]:[\\/]|\\\\|/home/|/Users/)"),
)


class CycleError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def load_contract_validator() -> Any:
    spec = importlib.util.spec_from_file_location(
        "content_operations_contract_validator", CONTRACT_VALIDATOR_PATH
    )
    if spec is None or spec.loader is None:
        raise CycleError("contract_validator_unavailable", str(CONTRACT_VALIDATOR_PATH))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CONTRACT_VALIDATOR = load_contract_validator()


def json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json_text(value), encoding="utf-8", newline="\n")


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise CycleError("artifact_missing", str(path)) from error
    except json.JSONDecodeError as error:
        raise CycleError("invalid_json", f"{path}: {error}") from error
    if not isinstance(value, dict):
        raise CycleError("invalid_json_root", f"{path} must contain an object")
    return value


def canonical_hash(value: Any) -> str:
    return tracker.canonical_sha256(value)


def is_reparse_point(path: Path) -> bool:
    if not path.exists() and not path.is_symlink():
        return False
    try:
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
    except OSError as error:
        raise CycleError("unsafe_store_path", str(path)) from error
    return path.is_symlink() or bool(attributes & 0x400)


def allowed_store_root(path: Path) -> tuple[Path, Path]:
    candidate = path if path.is_absolute() else Path.cwd() / path
    candidate = Path(os.path.abspath(candidate))
    for configured in PRIVATE_STORE_ROOTS:
        root = Path(os.path.abspath(configured))
        if root.exists() and is_reparse_point(root):
            raise CycleError("store_root_reparse_prohibited", str(root))
        try:
            relative = candidate.relative_to(root)
        except ValueError:
            continue
        if not relative.parts:
            raise CycleError("store_root_prohibited", str(candidate))
        current = root
        for part in relative.parts:
            if current.exists() and is_reparse_point(current):
                raise CycleError("store_reparse_prohibited", str(current))
            current = current / part
        if current.exists() and is_reparse_point(current):
            raise CycleError("store_reparse_prohibited", str(current))
        resolved_root = root.resolve(strict=False)
        resolved_candidate = candidate.resolve(strict=False)
        try:
            resolved_candidate.relative_to(resolved_root)
        except ValueError as error:
            raise CycleError("store_escape", str(candidate)) from error
        return root, candidate
    raise CycleError("store_outside_private_root", str(candidate))


def validate_store_location(
    store: Path,
    *,
    require_metadata: bool = False,
) -> Path:
    _, candidate = allowed_store_root(store)
    if candidate.exists():
        if not candidate.is_dir() or is_reparse_point(candidate):
            raise CycleError("unsafe_store_path", str(candidate))
        if require_metadata and not (candidate / STORE_METADATA_FILE).is_file():
            raise CycleError("existing_nonstore_directory", str(candidate))
    return candidate


def validate_store_tree(store: Path) -> None:
    """Reject links/reparse points anywhere inside an existing governed store."""
    if not store.exists():
        return
    for path in store.rglob("*"):
        if is_reparse_point(path):
            raise CycleError("store_tree_reparse_prohibited", str(path))


def safe_rmtree(path: Path) -> None:
    _, candidate = allowed_store_root(path)
    if not candidate.exists():
        return
    if not candidate.is_dir() or is_reparse_point(candidate):
        raise CycleError("unsafe_remove_target", str(candidate))
    shutil.rmtree(candidate)


def safe_rename(source: Path, target: Path) -> None:
    _, safe_source = allowed_store_root(source)
    _, safe_target = allowed_store_root(target)
    if not safe_source.exists() or not safe_source.is_dir() or is_reparse_point(safe_source):
        raise CycleError("unsafe_rename_source", str(safe_source))
    if safe_target.exists() or safe_target.is_symlink():
        raise CycleError("unsafe_rename_target", str(safe_target))
    safe_source.rename(safe_target)


def reject_obvious_sensitive_values(value: Any, label: str = "input") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            reject_obvious_sensitive_values(child, f"{label}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            reject_obvious_sensitive_values(child, f"{label}[{index}]")
    elif isinstance(value, str):
        for pattern in OBVIOUS_SENSITIVE_PATTERNS:
            if pattern.search(value):
                raise CycleError("obvious_sensitive_value", label)


def require_exact_keys(
    value: Any,
    required: set[str],
    optional: set[str],
    label: str,
) -> None:
    if not isinstance(value, dict):
        raise CycleError("invalid_shape", f"{label} must be an object")
    missing = required - set(value)
    extra = set(value) - required - optional
    if missing:
        raise CycleError("missing_required_field", f"{label} missing {sorted(missing)}")
    if extra:
        raise CycleError("unexpected_field", f"{label} extra {sorted(extra)}")


def validate_common_input(entry: dict[str, Any], operation_type: str) -> None:
    tracker.reject_sensitive_keys(entry)
    reject_obvious_sensitive_values(entry)
    expected = INPUT_VERSIONS[operation_type]
    if entry.get("schema_version") != expected:
        raise CycleError("schema_version_drift", f"expected {expected}")
    if entry.get("data_classification") not in DATA_CLASSIFICATIONS:
        raise CycleError("invalid_data_classification", operation_type)
    validate_privacy_review(entry, operation_type)


def parse_time(value: Any, label: str) -> Any:
    try:
        return tracker.parse_time(value, label)
    except tracker.TrackerError as error:
        raise CycleError(error.code, str(error)) from error


def resolve_source(ref: str, expected_sha256: str, label: str) -> tuple[Path, dict[str, Any]]:
    try:
        path = tracker.resolve_repo_ref(ref)
    except tracker.TrackerError as error:
        raise CycleError(error.code, str(error)) from error
    observed = tracker.sha256_file(path)
    if observed != expected_sha256:
        raise CycleError("stale_source_artifact", f"{label} hash drift")
    return path, load_json(path)


def validate_instance(instance: Any, schema: dict[str, Any], label: str) -> None:
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(instance), key=lambda item: [str(part) for part in item.path])
    if errors:
        location = ".".join(str(part) for part in errors[0].path) or "$"
        raise CycleError("schema_validation_failed", f"{label}.{location}: {errors[0].message}")


def load_contract_set() -> dict[str, Any]:
    try:
        return CONTRACT_VALIDATOR.load_contract_set(CONTRACT_ROOT)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise CycleError("atomic_contract_set_invalid", str(error)) from error


def contract_set_identity() -> dict[str, str]:
    manifest = load_contract_set()["manifest"]
    return {
        "schema_version": manifest["schema_version"],
        "contract_set_id": manifest["contract_set_id"],
        "contract_set_version": manifest["contract_set_version"],
        "canonical_json_sha256": canonical_hash(manifest),
    }


def validate_sha256(value: Any, label: str) -> None:
    if not isinstance(value, str) or HEX_SHA256.fullmatch(value) is None:
        raise CycleError("invalid_sha256", label)


def resolve_review_credential(
    *,
    ref: str,
    expected_sha256: str,
    expected_schema_version: str,
    expected_reviewer: str,
    expected_reviewed_at: str,
    expected_decision: str,
    expected_operation_type: str,
    expected_scope_sha256: str,
    label: str,
) -> dict[str, Any]:
    validate_sha256(expected_sha256, f"{label}.receipt_sha256")
    try:
        path = tracker.resolve_repo_ref(ref)
    except tracker.TrackerError as error:
        raise CycleError("receipt_unresolvable", f"{label}: {error}") from error
    if tracker.sha256_file(path) != expected_sha256:
        raise CycleError("receipt_hash_drift", label)
    credential = load_json(path)
    tracker.reject_sensitive_keys(credential)
    reject_obvious_sensitive_values(credential)
    require_exact_keys(
        credential,
        {
            "schema_version",
            "reviewer_ref",
            "reviewed_at",
            "decision",
            "operation_type",
            "scope_sha256",
            "authority",
        },
        set(),
        label,
    )
    if credential["schema_version"] != expected_schema_version:
        raise CycleError("receipt_schema_drift", label)
    parse_time(credential["reviewed_at"], f"{label}.reviewed_at")
    if (
        credential["reviewer_ref"] != expected_reviewer
        or credential["reviewed_at"] != expected_reviewed_at
    ):
        raise CycleError("receipt_identity_drift", label)
    if credential["decision"] != expected_decision:
        raise CycleError("receipt_decision_drift", label)
    if credential["operation_type"] != expected_operation_type:
        raise CycleError("receipt_operation_drift", label)
    validate_sha256(credential["scope_sha256"], f"{label}.scope_sha256")
    if credential["scope_sha256"] != expected_scope_sha256:
        raise CycleError("receipt_scope_drift", label)
    if credential["authority"] != REVIEW_CREDENTIAL_AUTHORITY:
        raise CycleError("receipt_authority_escalation", label)
    return credential


def validate_privacy_review(entry: dict[str, Any], operation_type: str) -> None:
    review = entry.get("privacy_review")
    if entry["data_classification"] == "deidentified-operational" and review is None:
        raise CycleError("privacy_review_required", operation_type)
    if review is None:
        return
    require_exact_keys(
        review,
        {"reviewer_ref", "receipt_ref", "receipt_sha256", "reviewed_at", "scope_sha256"},
        set(),
        f"{operation_type}.privacy_review",
    )
    if not review["reviewer_ref"] or not review["receipt_ref"]:
        raise CycleError("privacy_review_required", operation_type)
    validate_sha256(review["receipt_sha256"], f"{operation_type}.privacy_review.receipt_sha256")
    validate_sha256(review["scope_sha256"], f"{operation_type}.privacy_review.scope_sha256")
    parse_time(review["reviewed_at"], f"{operation_type}.privacy_review.reviewed_at")
    scoped_input = copy.deepcopy(entry)
    scoped_input.pop("privacy_review", None)
    if review["scope_sha256"] != canonical_hash(scoped_input):
        raise CycleError("privacy_scope_hash_drift", operation_type)
    resolve_review_credential(
        ref=review["receipt_ref"],
        expected_sha256=review["receipt_sha256"],
        expected_schema_version="content-operations-cycle.privacy-review-credential.v1",
        expected_reviewer=review["reviewer_ref"],
        expected_reviewed_at=review["reviewed_at"],
        expected_decision="passed",
        expected_operation_type=operation_type,
        expected_scope_sha256=review["scope_sha256"],
        label=f"{operation_type}.privacy_review.receipt",
    )


def publication_identity(entry: dict[str, Any]) -> tuple[str, str]:
    publication_id = tracker.stable_operation_id("pub", f"publication|{entry['publication_key']}")
    return publication_id, f"publication:{publication_id}"


def publication_change_identity(event: dict[str, Any]) -> str:
    return f"publication-event:{event['event_id']}"


def snapshot_identity(entry: dict[str, Any]) -> tuple[str, str]:
    snapshot_id = tracker.stable_operation_id(
        "snap", f"snapshot|{entry['publication_id']}|{entry['window_label']}"
    )
    return snapshot_id, f"snapshot:{entry['publication_id']}:{entry['window_label']}"


def interaction_identity(entry: dict[str, Any]) -> tuple[str, str]:
    interaction_id = tracker.stable_operation_id("int", f"interaction|{entry['interaction_key']}")
    return interaction_id, f"interaction:{interaction_id}"


def lead_review_identity(entry: dict[str, Any]) -> str:
    return f"lead-review:{entry['interaction_event_id']}"


def operating_review_identity(entry: dict[str, Any]) -> tuple[str, str]:
    accounts = ",".join(sorted(entry["account_ids"]))
    source_revision = entry["source_checkpoint"]["journal_chain_sha256"]
    seed = (
        f"review|{entry['review_type']}|{entry['period']['start']}|"
        f"{entry['period']['end']}|{accounts}|{source_revision}"
    )
    review_id = tracker.stable_operation_id("review", seed)
    return review_id, f"operating-review:{review_id}"


def validate_publication_input(entry: dict[str, Any]) -> tuple[dict[str, Any], str]:
    validate_common_input(entry, "record-publication")
    require_exact_keys(
        entry,
        {
            "schema_version", "data_classification", "publication_key", "source_objects",
            "content_id", "account_id", "platform", "occurred_at", "recorded_at", "title",
            "channel_variant", "freeze_status", "evidence_status",
        },
        {
            "body_ref", "body_sha256", "cover_refs", "media_refs", "cta",
            "unavailable_reason", "reason", "privacy_review", "platform_content_id",
            "canonical_url", "replaces_deleted_event_id",
        },
        "publication-input",
    )
    if entry["freeze_status"] not in {"complete", "partial", "unavailable"}:
        raise CycleError("invalid_freeze_status", entry["freeze_status"])
    if entry["freeze_status"] == "complete" and (
        not entry.get("body_ref") or not entry.get("body_sha256")
    ):
        raise CycleError("missing_body_evidence", "complete freeze requires body_ref and body_sha256")
    if entry["freeze_status"] != "complete" and not entry.get("unavailable_reason"):
        raise CycleError("missing_unavailable_reason", "partial/unavailable freeze requires a reason")
    occurred_at = parse_time(entry["occurred_at"], "publication-input.occurred_at")
    recorded_at = parse_time(entry["recorded_at"], "publication-input.recorded_at")
    if recorded_at < occurred_at:
        raise CycleError("time_order", "publication recorded_at is before occurred_at")
    if entry["freeze_status"] == "complete":
        try:
            body_path = tracker.resolve_repo_ref(entry["body_ref"])
        except tracker.TrackerError as error:
            raise CycleError(error.code, str(error)) from error
        validate_sha256(entry["body_sha256"], "publication-input.body_sha256")
        if tracker.sha256_file(body_path) != entry["body_sha256"]:
            raise CycleError("stale_body_artifact", entry["body_ref"])
    source = entry["source_objects"]
    require_exact_keys(
        source,
        {
            "goal_ref",
            "goal_sha256",
            "account_ref",
            "account_sha256",
            "topic_ref",
            "topic_sha256",
            "content_item_ref",
            "content_item_sha256",
        },
        set(),
        "publication-input.source_objects",
    )
    _, goal = resolve_source(source["goal_ref"], source["goal_sha256"], "operating-goal")
    _, account = resolve_source(source["account_ref"], source["account_sha256"], "account")
    _, topic = resolve_source(source["topic_ref"], source["topic_sha256"], "topic")
    _, content = resolve_source(
        source["content_item_ref"], source["content_item_sha256"], "content-item"
    )
    contract_set = load_contract_set()
    validate_instance(goal, contract_set["schemas"]["operating-goal"], "source.operating-goal")
    validate_instance(account, contract_set["schemas"]["account"], "source.account")
    validate_instance(topic, contract_set["schemas"]["topic"], "source.topic")
    validate_instance(content, load_json(CONTENT_SCHEMA), "source.content-item")
    if account.get("account_id") != entry["account_id"]:
        raise CycleError("account_reference_drift", "publication account does not match source")
    if entry["account_id"] not in goal.get("account_ids", []):
        raise CycleError("goal_account_reference_drift", "publication account is outside source goal")
    goal_id = goal.get("goal_id")
    if goal_id not in account.get("goal_ids", []):
        raise CycleError("goal_account_reference_drift", "source account does not reference source goal")
    if goal_id not in topic.get("goal_ids", []):
        raise CycleError("goal_topic_reference_drift", "source topic does not reference source goal")
    if account.get("platform") != entry["platform"]:
        raise CycleError("platform_reference_drift", "publication platform does not match account")
    if content.get("content_id") != entry["content_id"]:
        raise CycleError("content_reference_drift", "publication content does not match source")
    operating_refs = content.get("operating_refs", {})
    if entry["account_id"] not in operating_refs.get("account_ids", []):
        raise CycleError("account_reference_drift", "publication account does not match content")
    topic_refs = operating_refs.get("topic_ids", [])
    if topic.get("topic_id") not in topic_refs:
        raise CycleError("topic_reference_drift", "publication topic does not match content")
    publication_id, identity_key = publication_identity(entry)
    event = {
        "schema_version": "0.1",
        "event_id": tracker.stable_operation_id("evt", f"event|{publication_id}|1"),
        "publication_id": publication_id,
        "event_sequence": 1,
        "content_id": entry["content_id"],
        "version_id": tracker.stable_operation_id("ver", f"version|{publication_id}|1"),
        "account_id": entry["account_id"],
        "platform": entry["platform"],
        "platform_content_id": entry.get("platform_content_id"),
        "canonical_url": entry.get("canonical_url"),
        "event_type": "published",
        "occurred_at": entry["occurred_at"],
        "recorded_at": entry["recorded_at"],
        "actor_type": "user",
        "evidence_status": entry["evidence_status"],
        "supersedes_event_id": entry.get("replaces_deleted_event_id"),
        "reason": entry.get("reason"),
        "frozen_version": {
            "title": entry["title"],
            "channel_variant": entry["channel_variant"],
            "freeze_status": entry["freeze_status"],
            "body_ref": entry.get("body_ref"),
            "body_sha256": entry.get("body_sha256"),
            "cover_refs": entry.get("cover_refs", []),
            "media_refs": entry.get("media_refs", []),
            "cta": entry.get("cta"),
            "unavailable_reason": entry.get("unavailable_reason"),
            "frozen_at": entry["recorded_at"],
        },
    }
    validate_instance(event, contract_set["schemas"]["publication-event"], "publication-event")
    return {
        "data_classification": entry["data_classification"],
        "privacy_review": copy.deepcopy(entry.get("privacy_review")),
        "event": event,
        "source_objects": copy.deepcopy(source),
    }, identity_key


PUBLICATION_CHANGE_TYPES = {
    "record-publication-edit": "edited",
    "record-publication-delete": "deleted",
    "record-publication-restore": "restored",
}

PUBLICATION_STATE_TRANSITIONS = {
    ("start", "prepared"): "prepared",
    ("start", "published"): "published",
    ("prepared", "published"): "published",
    ("published", "edited"): "published",
    ("published", "hidden"): "hidden",
    ("published", "deleted"): "deleted",
    ("published", "restricted"): "restricted",
    ("hidden", "deleted"): "deleted",
    ("hidden", "restored"): "published",
    ("restricted", "appeal-submitted"): "restricted",
    ("restricted", "deleted"): "deleted",
    ("restricted", "restored"): "published",
    ("deleted", "restored"): "published",
}


def publication_state(events: list[dict[str, Any]], label: str) -> str:
    state = "start"
    for event in sorted(events, key=lambda item: item["event_sequence"]):
        transition = (state, event["event_type"])
        if transition not in PUBLICATION_STATE_TRANSITIONS:
            raise CycleError(
                "publication_transition_invalid",
                f"{label}: {state} -> {event['event_type']}",
            )
        state = PUBLICATION_STATE_TRANSITIONS[transition]
    return state


def validate_publication_change_input(
    store: Path,
    entry: dict[str, Any],
    operation_type: str,
) -> tuple[dict[str, Any], str]:
    validate_common_input(entry, operation_type)
    event_type = PUBLICATION_CHANGE_TYPES[operation_type]
    required = {
        "schema_version", "data_classification", "publication_id", "source_event_id",
        "occurred_at", "recorded_at", "evidence_status", "reason",
    }
    optional = {"platform_content_id", "canonical_url", "privacy_review"}
    if event_type == "edited":
        required.update({"title", "channel_variant", "freeze_status"})
        optional.update({
            "body_ref", "body_sha256", "cover_refs", "media_refs", "cta",
            "unavailable_reason",
        })
    require_exact_keys(entry, required, optional, f"{operation_type}-input")
    if not isinstance(entry["reason"], str) or not entry["reason"].strip():
        raise CycleError("change_reason_required", operation_type)
    occurred_at = parse_time(entry["occurred_at"], f"{operation_type}.occurred_at")
    recorded_at = parse_time(entry["recorded_at"], f"{operation_type}.recorded_at")
    if recorded_at < occurred_at:
        raise CycleError("time_order", f"{operation_type} recorded_at is before occurred_at")
    if event_type == "edited":
        if entry["freeze_status"] not in {"complete", "partial", "unavailable"}:
            raise CycleError("invalid_freeze_status", entry["freeze_status"])
        if entry["freeze_status"] == "complete" and (
            not entry.get("body_ref") or not entry.get("body_sha256")
        ):
            raise CycleError(
                "missing_body_evidence",
                "complete edit freeze requires body_ref and body_sha256",
            )
        if entry["freeze_status"] != "complete" and not entry.get("unavailable_reason"):
            raise CycleError(
                "missing_unavailable_reason",
                "partial/unavailable edit freeze requires a reason",
            )
        if entry["freeze_status"] == "complete":
            try:
                body_path = tracker.resolve_repo_ref(entry["body_ref"])
            except tracker.TrackerError as error:
                raise CycleError(error.code, str(error)) from error
            validate_sha256(entry["body_sha256"], f"{operation_type}.body_sha256")
            if tracker.sha256_file(body_path) != entry["body_sha256"]:
                raise CycleError("stale_body_artifact", entry["body_ref"])

    store = validate_store_location(store, require_metadata=True)
    recover_store(store)
    validate_store_strict(store)
    events = build_heads(read_journal(store))["publication-event"]
    group = [item for item in events if item["publication_id"] == entry["publication_id"]]
    if not group:
        raise CycleError("publication_missing", entry["publication_id"])
    group = sorted(group, key=lambda item: item["event_sequence"])
    source = next(
        (item for item in group if item["event_id"] == entry["source_event_id"]),
        None,
    )
    if source is None:
        raise CycleError("publication_source_missing", entry["source_event_id"])
    prefix = [
        item for item in group
        if item["event_sequence"] <= source["event_sequence"]
    ]
    state = publication_state(prefix, entry["publication_id"])
    allowed_states = {
        "edited": {"published"},
        "deleted": {"published", "hidden", "restricted"},
        "restored": {"deleted", "hidden", "restricted"},
    }[event_type]
    if state not in allowed_states:
        raise CycleError(
            "publication_transition_invalid",
            f"{entry['publication_id']}: {state} -> {event_type}",
        )
    expected_sequence = source["event_sequence"] + 1
    existing_next = next(
        (item for item in group if item["event_sequence"] == expected_sequence),
        None,
    )
    if existing_next is None and source["event_id"] != group[-1]["event_id"]:
        raise CycleError("publication_source_not_latest", entry["source_event_id"])
    if occurred_at < parse_time(source["occurred_at"], f"{operation_type}.source.occurred_at"):
        raise CycleError("time_order", f"{operation_type} occurred before source event")
    sequence = expected_sequence
    event_id = tracker.stable_operation_id(
        "evt", f"event|{entry['publication_id']}|{sequence}"
    )
    event = {
        "schema_version": "0.1",
        "event_id": event_id,
        "publication_id": entry["publication_id"],
        "event_sequence": sequence,
        "content_id": source["content_id"],
        "version_id": (
            tracker.stable_operation_id(
                "ver", f"version|{entry['publication_id']}|{sequence}"
            )
            if event_type == "edited"
            else source["version_id"]
        ),
        "account_id": source["account_id"],
        "platform": source["platform"],
        "platform_content_id": entry.get(
            "platform_content_id", source.get("platform_content_id")
        ),
        "canonical_url": entry.get("canonical_url", source.get("canonical_url")),
        "event_type": event_type,
        "occurred_at": entry["occurred_at"],
        "recorded_at": entry["recorded_at"],
        "actor_type": "user",
        "evidence_status": entry["evidence_status"],
        "supersedes_event_id": source["event_id"],
        "reason": entry["reason"],
    }
    if event_type == "edited":
        event["frozen_version"] = {
            "title": entry["title"],
            "channel_variant": entry["channel_variant"],
            "freeze_status": entry["freeze_status"],
            "body_ref": entry.get("body_ref"),
            "body_sha256": entry.get("body_sha256"),
            "cover_refs": entry.get("cover_refs", []),
            "media_refs": entry.get("media_refs", []),
            "cta": entry.get("cta"),
            "unavailable_reason": entry.get("unavailable_reason"),
            "frozen_at": entry["recorded_at"],
        }
    validate_instance(
        event,
        load_contract_set()["schemas"]["publication-event"],
        "publication-event",
    )
    return {
        "data_classification": entry["data_classification"],
        "privacy_review": copy.deepcopy(entry.get("privacy_review")),
        "event": event,
    }, publication_change_identity(event)


def validate_snapshot_input(entry: dict[str, Any]) -> tuple[dict[str, Any], str]:
    validate_common_input(entry, "record-snapshot")
    require_exact_keys(
        entry,
        {
            "schema_version", "data_classification", "publication_id", "as_of", "captured_at",
            "window_label", "timezone", "metric_dictionary_version", "source_type",
            "data_completeness", "metrics",
        },
        {"missing_reasons", "notes", "privacy_review"},
        "snapshot-input",
    )
    if entry["window_label"] not in tracker.WINDOW_BOUNDS_HOURS:
        raise CycleError("invalid_window", "only early or d7 may be recorded by the daily adapter")
    as_of = parse_time(entry["as_of"], "snapshot-input.as_of")
    captured_at = parse_time(entry["captured_at"], "snapshot-input.captured_at")
    if captured_at < as_of or (captured_at - as_of).total_seconds() > 24 * 3600:
        raise CycleError("stale_observation", "captured_at must be within 24h after as_of")
    metrics: list[dict[str, Any]] = []
    for index, metric in enumerate(entry["metrics"]):
        require_exact_keys(
            metric,
            {"metric_key", "value", "unit"},
            {"dimensions", "unavailable_reason"},
            f"snapshot-input.metrics[{index}]",
        )
        layer = tracker.CONTENT_METRIC_LAYERS.get(metric["metric_key"])
        if layer is None:
            raise CycleError("unknown_metric_key", metric["metric_key"])
        try:
            tracker.validate_metric(
                {
                    "layer": layer,
                    "metric_key": metric["metric_key"],
                    "value": metric["value"],
                    "unit": metric["unit"],
                },
                f"snapshot-input.metrics[{index}]",
            )
        except tracker.TrackerError as error:
            raise CycleError(error.code, str(error)) from error
        if metric["value"] is None and not metric.get("unavailable_reason"):
            raise CycleError("missing_unavailable_reason", f"metric {metric['metric_key']}")
        metrics.append(copy.deepcopy(metric))
    if entry["data_completeness"] == "unavailable" and any(
        metric["value"] is not None for metric in metrics
    ):
        raise CycleError("unavailable_metric_has_value", "unavailable snapshot has a metric value")
    snapshot_id, identity_key = snapshot_identity(entry)
    snapshot = {
        "schema_version": "0.1",
        "snapshot_id": snapshot_id,
        "publication_id": entry["publication_id"],
        "as_of": entry["as_of"],
        "captured_at": entry["captured_at"],
        "window_label": entry["window_label"],
        "timezone": entry["timezone"],
        "metric_dictionary_version": entry["metric_dictionary_version"],
        "source_type": entry["source_type"],
        "data_completeness": entry["data_completeness"],
        "missing_reasons": entry.get("missing_reasons", []),
        "metrics": metrics,
        "notes": entry.get("notes", ""),
    }
    validate_instance(snapshot, load_contract_set()["schemas"]["performance-snapshot"], "snapshot")
    return {
        "data_classification": entry["data_classification"],
        "privacy_review": copy.deepcopy(entry.get("privacy_review")),
        "snapshot": snapshot,
    }, identity_key


def validate_interaction_input(entry: dict[str, Any]) -> tuple[dict[str, Any], str]:
    validate_common_input(entry, "record-interaction")
    require_exact_keys(
        entry,
        {
            "schema_version", "data_classification", "interaction_key", "publication_id",
            "account_id", "source_type", "occurred_at", "recorded_at", "deidentified_summary",
            "evidence_status", "evidence_refs", "signal_class", "disposition",
        },
        {"question_category", "business_event_type", "privacy_review"},
        "interaction-input",
    )
    occurred_at = parse_time(entry["occurred_at"], "interaction-input.occurred_at")
    recorded_at = parse_time(entry["recorded_at"], "interaction-input.recorded_at")
    if recorded_at < occurred_at:
        raise CycleError("time_order", "interaction recorded_at is before occurred_at")
    if entry["signal_class"] == "business-candidate":
        if entry["disposition"] != "lead-candidate":
            raise CycleError("signal_escalation", "business candidate must be a lead candidate")
        if entry.get("business_event_type") not in tracker.QUALIFYING_BUSINESS_EVENTS:
            raise CycleError("non_qualifying_business_event", "business candidate is not one of three events")
        if not entry["evidence_refs"]:
            raise CycleError("evidence_required", "business candidate requires evidence")
        promotion = "pending-review"
    elif entry["signal_class"] == "no-signal":
        if entry["source_type"] != "no-signal" or entry["disposition"] != "observe-only":
            raise CycleError("no_signal_escalation", "no-signal must remain observe-only")
        if entry.get("business_event_type") is not None:
            raise CycleError("no_signal_escalation", "no-signal cannot carry a business event")
        promotion = "not-requested"
    else:
        if entry["signal_class"] != "content-observation":
            raise CycleError("invalid_signal_class", entry["signal_class"])
        if entry["disposition"] not in {"observe-only", "content-input", "discard"}:
            raise CycleError("signal_escalation", "content observation cannot become a lead")
        if entry.get("business_event_type") is not None:
            raise CycleError("signal_escalation", "content observation cannot carry a business event")
        promotion = "not-requested"
    interaction_id, identity_key = interaction_identity(entry)
    interaction = {
        "schema_version": "0.1",
        "data_classification": entry["data_classification"],
        "interaction_event_id": interaction_id,
        "publication_id": entry["publication_id"],
        "account_id": entry["account_id"],
        "source_type": entry["source_type"],
        "occurred_at": entry["occurred_at"],
        "recorded_at": entry["recorded_at"],
        "deidentified_summary": entry["deidentified_summary"],
        "question_category": entry.get("question_category"),
        "evidence_status": entry["evidence_status"],
        "evidence_refs": entry["evidence_refs"],
        "signal_class": entry["signal_class"],
        "disposition": entry["disposition"],
        "lead_promotion_status": promotion,
        "privacy": {
            "deidentified": True,
            "raw_text_included": False,
            "direct_identifiers_included": False,
            "retention_class": (
                "synthetic-only" if entry["data_classification"] == "synthetic-only" else "short-summary"
            ),
        },
        "authority": {
            "execution_authorized": False,
            "contact_authorized": False,
            "crm_write_authorized": False,
            "publication_authority": "never",
        },
    }
    validate_instance(interaction, load_contract_set()["schemas"]["interaction-event"], "interaction")
    return {
        "data_classification": entry["data_classification"],
        "privacy_review": copy.deepcopy(entry.get("privacy_review")),
        "interaction": interaction,
        "business_event_type": entry.get("business_event_type"),
    }, identity_key


def validate_lead_review_input(entry: dict[str, Any]) -> tuple[dict[str, Any], str]:
    validate_common_input(entry, "review-lead")
    require_exact_keys(
        entry,
        {
            "schema_version", "data_classification", "interaction_event_id", "decision",
            "reviewer_ref", "reviewed_at", "receipt_ref", "receipt_sha256", "evidence_refs",
        },
        {"consent_status", "attribution_type", "attribution_model", "privacy_review"},
        "lead-review-input",
    )
    if entry["decision"] not in {"confirm", "reject"}:
        raise CycleError("invalid_review_decision", entry["decision"])
    parse_time(entry["reviewed_at"], "lead-review-input.reviewed_at")
    if not entry["reviewer_ref"] or not entry["receipt_ref"]:
        raise CycleError("human_receipt_required", "reviewer and receipt are required")
    validate_sha256(entry["receipt_sha256"], "lead-review-input.receipt_sha256")
    if not entry["evidence_refs"]:
        raise CycleError("evidence_required", "lead review requires evidence")
    if entry["decision"] == "confirm":
        required = ("consent_status", "attribution_type", "attribution_model")
        if any(not entry.get(field) for field in required):
            raise CycleError("explicit_attribution_required", "confirm requires consent and attribution")
    review_scope = copy.deepcopy(entry)
    review_scope.pop("receipt_ref", None)
    review_scope.pop("receipt_sha256", None)
    review_scope_sha256 = canonical_hash(review_scope)
    resolve_review_credential(
        ref=entry["receipt_ref"],
        expected_sha256=entry["receipt_sha256"],
        expected_schema_version="content-operations-cycle.lead-review-credential.v1",
        expected_reviewer=entry["reviewer_ref"],
        expected_reviewed_at=entry["reviewed_at"],
        expected_decision=entry["decision"],
        expected_operation_type="review-lead",
        expected_scope_sha256=review_scope_sha256,
        label="lead-review-input.receipt",
    )
    return {
        "data_classification": entry["data_classification"],
        "privacy_review": copy.deepcopy(entry.get("privacy_review")),
        "review": {
            **copy.deepcopy(entry),
            "review_scope_sha256": review_scope_sha256,
        },
    }, lead_review_identity(entry)


def validate_contract_record_input(
    entry: dict[str, Any], operation_type: str
) -> tuple[dict[str, Any], str]:
    component, id_field = CONTRACT_RECORD_OPERATIONS[operation_type]
    validate_common_input(entry, operation_type)
    require_exact_keys(
        entry,
        {"schema_version", "data_classification", "artifact"},
        {"privacy_review", "decision_review"},
        f"{operation_type}-input",
    )
    artifact = entry["artifact"]
    if not isinstance(artifact, dict):
        raise CycleError("invalid_shape", f"{operation_type}.artifact must be an object")
    if artifact.get("data_classification") != entry["data_classification"]:
        raise CycleError("classification_drift", f"{operation_type}.artifact")
    validate_instance(
        artifact,
        load_contract_set()["schemas"][component],
        f"{operation_type}.artifact",
    )
    decision_review = entry.get("decision_review")
    requires_decision_review = component == "revenue-attribution-event" or (
        component == "diagnostic-run" and artifact.get("report_state") == "human-reviewed"
    )
    if requires_decision_review and decision_review is None:
        raise CycleError("human_receipt_required", f"{operation_type}.decision_review")
    if not requires_decision_review and decision_review is not None:
        raise CycleError("unexpected_review_receipt", operation_type)
    if decision_review is not None:
        require_exact_keys(
            decision_review,
            {"reviewer_ref", "reviewed_at", "receipt_ref", "receipt_sha256", "scope_sha256"},
            set(),
            f"{operation_type}.decision_review",
        )
        artifact_review = artifact["review"]
        artifact_scope_sha256 = canonical_hash(artifact)
        if decision_review["scope_sha256"] != artifact_scope_sha256:
            raise CycleError("review_scope_hash_drift", operation_type)
        resolve_review_credential(
            ref=decision_review["receipt_ref"],
            expected_sha256=decision_review["receipt_sha256"],
            expected_schema_version=(
                "content-operations-cycle.revenue-review-credential.v1"
                if component == "revenue-attribution-event"
                else "content-operations-cycle.diagnostic-review-credential.v1"
            ),
            expected_reviewer=artifact_review["reviewer_ref"],
            expected_reviewed_at=artifact_review["reviewed_at"],
            expected_decision="confirmed",
            expected_operation_type=operation_type,
            expected_scope_sha256=artifact_scope_sha256,
            label=f"{operation_type}.decision_review.receipt",
        )
    return {
        "data_classification": entry["data_classification"],
        "privacy_review": copy.deepcopy(entry.get("privacy_review")),
        "decision_review": copy.deepcopy(decision_review),
        "component": component,
        "artifact": copy.deepcopy(artifact),
    }, f"{component}:{artifact[id_field]}"


def validate_review_input(entry: dict[str, Any]) -> tuple[dict[str, Any], str]:
    validate_common_input(entry, "build-review")
    require_exact_keys(
        entry,
        {
            "schema_version", "data_classification", "review_type", "period", "account_ids",
            "created_at", "source_checkpoint",
        },
        {"scope", "privacy_review"},
        "review-input",
    )
    if entry["review_type"] not in {"weekly", "monthly"}:
        raise CycleError("invalid_review_type", entry["review_type"])
    require_exact_keys(entry["period"], {"start", "end", "timezone"}, set(), "review-input.period")
    start = parse_time(entry["period"]["start"], "review-input.period.start")
    end = parse_time(entry["period"]["end"], "review-input.period.end")
    created = parse_time(entry["created_at"], "review-input.created_at")
    if end <= start:
        raise CycleError("time_order", "review period end must be after start")
    if created < end:
        raise CycleError("time_order", "review cannot be created before period end")
    if not isinstance(entry["account_ids"], list) or not entry["account_ids"]:
        raise CycleError("account_required", "review requires at least one account")
    require_exact_keys(
        entry["source_checkpoint"],
        {"journal_record_count", "tail_record_sha256", "journal_chain_sha256"},
        set(),
        "review-input.source_checkpoint",
    )
    if not isinstance(entry["source_checkpoint"]["journal_record_count"], int):
        raise CycleError("invalid_source_checkpoint", "journal_record_count")
    validate_sha256(entry["source_checkpoint"]["tail_record_sha256"], "review source tail")
    validate_sha256(entry["source_checkpoint"]["journal_chain_sha256"], "review source chain")
    review_id, identity_key = operating_review_identity(entry)
    return {
        "data_classification": entry["data_classification"],
        "privacy_review": copy.deepcopy(entry.get("privacy_review")),
        "review_request": copy.deepcopy(entry),
        "operating_review_id": review_id,
    }, identity_key


def operation_time(operation_type: str, payload: dict[str, Any]) -> str:
    if operation_type == "record-publication" or operation_type in PUBLICATION_CHANGE_TYPES:
        return payload["event"]["recorded_at"]
    if operation_type == "record-snapshot":
        return payload["snapshot"]["captured_at"]
    if operation_type == "record-interaction":
        return payload["interaction"]["recorded_at"]
    if operation_type == "review-lead":
        return payload["review"]["reviewed_at"]
    if operation_type in CONTRACT_RECORD_OPERATIONS:
        component = payload["component"]
        artifact = payload["artifact"]
        field = {
            "experiment-run": "registered_at",
            "diagnostic-run": "run_at",
            "resource-ledger-event": "occurred_at",
            "account-continuity-plan": "reviewed_at",
            "account-security-event": "recorded_at",
        }.get(component)
        if field is not None:
            return artifact[field]
        return artifact["review"]["reviewed_at"]
    return payload["review_request"]["created_at"]


def make_journal_record(
    sequence: int,
    operation_type: str,
    identity_key: str,
    payload: dict[str, Any],
    previous_record_sha256: str | None,
) -> dict[str, Any]:
    payload_sha256 = canonical_hash(payload)
    operation_id = tracker.stable_operation_id("op", f"{operation_type}|{identity_key}")
    record = {
        "schema_version": JOURNAL_SCHEMA_VERSION,
        "sequence": sequence,
        "operation_id": operation_id,
        "operation_type": operation_type,
        "identity_key": identity_key,
        "data_classification": payload["data_classification"],
        "contract_set": contract_set_identity(),
        "previous_record_sha256": previous_record_sha256,
        "payload_sha256": payload_sha256,
        "recorded_at": operation_time(operation_type, payload),
        "payload": payload,
        "authority": {
            "execution_authorized": False,
            "publication_authority": "never",
            "crm_write_authorized": False,
            "external_send_authorized": False,
        },
    }
    record["record_sha256"] = canonical_hash(record)
    return record


def read_journal(store: Path) -> list[dict[str, Any]]:
    journal = store / "journal"
    if not journal.exists():
        return []
    records = [load_json(path) for path in sorted(journal.glob("*.json"))]
    for expected, record in enumerate(records, start=1):
        require_exact_keys(
            record,
            {
                "schema_version", "sequence", "operation_id", "operation_type", "identity_key",
                "data_classification", "contract_set", "previous_record_sha256", "payload_sha256",
                "record_sha256", "recorded_at", "payload", "authority",
            },
            set(),
            f"journal[{expected}]",
        )
        if record["schema_version"] != JOURNAL_SCHEMA_VERSION or record["sequence"] != expected:
            raise CycleError("journal_sequence_drift", f"expected sequence {expected}")
        expected_previous = records[expected - 2]["record_sha256"] if expected > 1 else None
        if record["previous_record_sha256"] != expected_previous:
            raise CycleError("journal_chain_drift", record["operation_id"])
        if record["data_classification"] not in DATA_CLASSIFICATIONS:
            raise CycleError("invalid_data_classification", record["operation_id"])
        if record["payload"].get("data_classification") != record["data_classification"]:
            raise CycleError("classification_drift", record["operation_id"])
        if record["contract_set"] != contract_set_identity():
            raise CycleError("contract_set_drift", record["operation_id"])
        expected_id = tracker.stable_operation_id(
            "op", f"{record['operation_type']}|{record['identity_key']}"
        )
        if record["operation_id"] != expected_id:
            raise CycleError("journal_identity_drift", record["operation_id"])
        if record["payload_sha256"] != canonical_hash(record["payload"]):
            raise CycleError("journal_payload_hash_drift", record["operation_id"])
        material = copy.deepcopy(record)
        observed_record_hash = material.pop("record_sha256")
        if observed_record_hash != canonical_hash(material):
            raise CycleError("journal_record_hash_drift", record["operation_id"])
        if record.get("authority") != {
            "execution_authorized": False,
            "publication_authority": "never",
            "crm_write_authorized": False,
            "external_send_authorized": False,
        }:
            raise CycleError("authority_drift", record["operation_id"])
    identities = [record["identity_key"] for record in records]
    if len(identities) != len(set(identities)):
        raise CycleError("duplicate_operation_identity", "journal contains duplicate identities")
    classifications = {record["data_classification"] for record in records}
    if len(classifications) > 1:
        raise CycleError("classification_mixing_prohibited", "journal classifications differ")
    return records


def build_operating_review(request: dict[str, Any], heads: dict[str, Any]) -> dict[str, Any]:
    start = parse_time(request["period"]["start"], "review.period.start")
    end = parse_time(request["period"]["end"], "review.period.end")
    created = parse_time(request["created_at"], "review.created_at")
    accounts = set(request["account_ids"])
    publications = [
        event for event in heads["publication-event"]
        if event["event_type"] == "published"
        and event["account_id"] in accounts
        and start <= parse_time(event["occurred_at"], "publication.occurred_at") <= end
        and parse_time(event["recorded_at"], "publication.recorded_at") <= created
    ]
    publication_ids = {event["publication_id"] for event in publications}
    snapshots = [
        item for item in heads["performance-snapshot"]
        if item["publication_id"] in publication_ids
        and parse_time(item["as_of"], "snapshot.as_of") <= created
        and parse_time(item["captured_at"], "snapshot.captured_at") <= created
    ]
    interactions = [
        item for item in heads["interaction-event"]
        if item["publication_id"] in publication_ids
        and parse_time(item["recorded_at"], "interaction.recorded_at") <= created
    ]
    leads = [
        item for item in heads["lead-event"]
        if item["source_publication_id"] in publication_ids
        and parse_time(item["created_at"], "lead.created_at") <= created
    ]
    content_ids = {event["content_id"] for event in publications}
    experiments = [
        item for item in heads["experiment-run"]
        if item["account_id"] in accounts
        and parse_time(item["registered_at"], "experiment.registered_at") <= created
        and (
            publication_ids.intersection(item.get("publication_ids", []))
            or content_ids.intersection(item.get("content_ids", []))
        )
    ]
    diagnostics = [
        item for item in heads["diagnostic-run"]
        if item["account_id"] in accounts
        and parse_time(item["run_at"], "diagnostic.run_at") <= created
        and publication_ids.intersection(item.get("publication_ids", []))
    ]
    resources = [
        item for item in heads["resource-ledger-event"]
        if item["account_id"] in accounts
        and parse_time(item["occurred_at"], "resource.occurred_at") <= created
        and (
            item.get("publication_id") in publication_ids
            or item.get("content_id") in content_ids
        )
    ]
    lead_ids = {item["lead_event_id"] for item in leads}
    revenues = [
        item for item in heads["revenue-attribution-event"]
        if item["account_id"] in accounts
        and parse_time(item["occurred_at"], "revenue.occurred_at") <= created
        and (
            publication_ids.intersection(item.get("publication_ids", []))
            or lead_ids.intersection(item.get("lead_event_ids", []))
        )
    ]
    if not publications:
        raise CycleError("review_input_empty", "review period has no publication")
    goals_by_id: dict[str, dict[str, Any]] = {}
    for context in heads["source-context"]:
        _, goal = resolve_source(
            context["goal_ref"], context["goal_sha256"], "operating-goal"
        )
        validate_instance(
            goal, load_contract_set()["schemas"]["operating-goal"], "source.operating-goal"
        )
        if not accounts.intersection(goal.get("account_ids", [])):
            continue
        goal_start = parse_time(goal["period"]["start"], "goal.period.start")
        goal_end = parse_time(goal["period"]["end"], "goal.period.end")
        if start < goal_start or end > goal_end:
            raise CycleError(
                "goal_review_period_drift",
                f"review period is outside goal {goal['goal_id']}",
            )
        previous = goals_by_id.get(goal["goal_id"])
        if previous is not None and previous != goal:
            raise CycleError("goal_source_conflict", goal["goal_id"])
        goals_by_id[goal["goal_id"]] = goal
    if not goals_by_id:
        raise CycleError("goal_review_missing", "review has no source goal for selected accounts")
    layer_evidence: dict[str, set[str]] = {layer: set() for layer in tracker.LAYERS}
    layer_observed: dict[str, bool] = {layer: False for layer in tracker.LAYERS}
    for snapshot in snapshots:
        for metric in snapshot["metrics"]:
            layer = tracker.CONTENT_METRIC_LAYERS.get(metric["metric_key"])
            if layer is not None and metric["value"] is not None:
                layer_observed[layer] = True
                layer_evidence[layer].add(snapshot["snapshot_id"])
    if leads or revenues:
        layer_observed["business"] = True
        layer_evidence["business"].update(item["lead_event_id"] for item in leads)
        layer_evidence["business"].update(item["revenue_event_id"] for item in revenues)
    summaries = []
    for layer in tracker.LAYERS:
        if layer_observed[layer]:
            status = "observed"
            summary = (
                "存在人工确认的去标识化业务事件。"
                if layer == "business"
                else "该层存在人工录入的可观察内容指标。"
            )
        else:
            status = "insufficient-evidence"
            summary = (
                "没有 lead 或 revenue 输入，不能把内容互动升级为业务结论。"
                if layer == "business"
                else "没有可验证信号；content_no_signal 仅表示证据不足。"
            )
        summaries.append(
            {
                "layer": layer,
                "status": status,
                "summary": summary,
                "evidence_refs": sorted(layer_evidence[layer]),
            }
        )
    input_refs = {
        "publication_ids": sorted(publication_ids),
        "snapshot_ids": sorted(item["snapshot_id"] for item in snapshots),
        "interaction_event_ids": sorted(item["interaction_event_id"] for item in interactions),
        "lead_event_ids": sorted(item["lead_event_id"] for item in leads),
        "experiment_run_ids": sorted(item["experiment_run_id"] for item in experiments),
        "diagnostic_run_ids": sorted(item["diagnostic_run_id"] for item in diagnostics),
        "resource_event_ids": sorted(item["resource_event_id"] for item in resources),
        "revenue_event_ids": sorted(item["revenue_event_id"] for item in revenues),
    }
    decision_refs = sorted(
        input_refs["snapshot_ids"]
        + input_refs["lead_event_ids"]
        + input_refs["diagnostic_run_ids"]
        + input_refs["resource_event_ids"]
        + input_refs["revenue_event_ids"]
    )
    goal_evidence_refs = sorted(
        input_refs["publication_ids"]
        + input_refs["snapshot_ids"]
        + input_refs["interaction_event_ids"]
        + input_refs["lead_event_ids"]
        + input_refs["experiment_run_ids"]
        + input_refs["diagnostic_run_ids"]
        + input_refs["resource_event_ids"]
        + input_refs["revenue_event_ids"]
    )
    currencies = {item["cost"]["currency"] for item in resources}
    if len(currencies) > 1:
        raise CycleError("resource_currency_mixing", ",".join(sorted(currencies)))
    resource_summary = {
        "human_time_hours": sum(
            float(item["quantity"]["value"])
            for item in resources
            if item["resource_type"] == "human-time"
            and item["quantity"]["unit"] == "hours"
        ),
        "tool_cost": sum(
            float(item["cost"]["amount"])
            for item in resources if item["resource_type"] == "tool-subscription"
        ),
        "external_cost": sum(
            float(item["cost"]["amount"])
            for item in resources if item["resource_type"] == "external-service"
        ),
        "paid_distribution_cost": sum(
            float(item["cost"]["amount"])
            for item in resources if item["resource_type"] == "paid-distribution"
        ),
        "currency": next(iter(currencies), "CNY"),
    }
    revenue_summary = {
        "direct_count": sum(item["attribution_type"] == "direct" for item in revenues),
        "assisted_count": sum(item["attribution_type"] == "assisted" for item in revenues),
        "unknown_count": sum(item["attribution_type"] == "unknown" for item in revenues),
        "causal_claim": False,
    }
    goal_reviews = []
    for goal_id in sorted(goals_by_id):
        goal = goals_by_id[goal_id]
        criterion_results = [
            {
                "criterion_id": criterion["criterion_id"],
                "status": "insufficient-evidence",
                "actual_summary": (
                    "已收集本周期的人工发布、观察和互动证据；"
                    "自动流程不替代人工判断该标准是否达成。"
                ),
                "evidence_refs": goal_evidence_refs,
            }
            for criterion in goal["success_criteria"]
        ]
        goal_reviews.append(
            {
                "goal_id": goal_id,
                "status": "insufficient-evidence",
                "summary": "证据链已进入复盘，但目标状态仍等待人工审核。",
                "criterion_results": criterion_results,
                "evidence_refs": goal_evidence_refs,
            }
        )
    return {
        "schema_version": "0.1",
        "data_classification": request["data_classification"],
        "operating_review_id": operating_review_identity(request)[0],
        "review_type": request["review_type"],
        "period": request["period"],
        "account_ids": sorted(request["account_ids"]),
        "goal_reviews": goal_reviews,
        "input_refs": input_refs,
        "layer_summaries": summaries,
        "resource_summary": resource_summary,
        "revenue_summary": revenue_summary,
        "decisions": [
            {
                "scope": request.get("scope", "content-operations-cycle"),
                "decision": "insufficient-evidence",
                "reason": "草稿复盘不自动调整资源；证据不足时保留人工判断。",
                "evidence_refs": decision_refs,
            }
        ],
        "data_gaps": [
            "content_no_signal 只表示证据不足，不表示选题失败或客户负面。"
        ],
        "next_experiment_ids": sorted(
            item["experiment_run_id"]
            for item in experiments
            if item["state"] in {"pre-registered", "running"}
        )[:2],
        "review_state": "draft-only",
        "authority": {
            "execution_authorized": False,
            "publication_authority": "never",
            "crm_write_performed": False,
            "automatic_resource_reallocation": False,
        },
        "created_at": request["created_at"],
    }


def apply_record(heads: dict[str, Any], record: dict[str, Any]) -> None:
    operation = record["operation_type"]
    payload = record["payload"]
    if operation == "record-publication":
        heads["publication-event"].append(copy.deepcopy(payload["event"]))
        heads["source-context"].append(copy.deepcopy(payload["source_objects"]))
    elif operation in PUBLICATION_CHANGE_TYPES:
        heads["publication-event"].append(copy.deepcopy(payload["event"]))
    elif operation == "record-snapshot":
        heads["performance-snapshot"].append(copy.deepcopy(payload["snapshot"]))
    elif operation == "record-interaction":
        heads["interaction-event"].append(copy.deepcopy(payload["interaction"]))
        heads["interaction-business-type"][payload["interaction"]["interaction_event_id"]] = payload.get(
            "business_event_type"
        )
    elif operation == "review-lead":
        request = payload["review"]
        interaction = next(
            (
                item for item in heads["interaction-event"]
                if item["interaction_event_id"] == request["interaction_event_id"]
            ),
            None,
        )
        if interaction is None:
            raise CycleError("interaction_missing", request["interaction_event_id"])
        if interaction["lead_promotion_status"] != "pending-review":
            raise CycleError("interaction_not_reviewable", request["interaction_event_id"])
        if request["data_classification"] != interaction["data_classification"]:
            raise CycleError("classification_drift", request["interaction_event_id"])
        source_evidence = set(interaction.get("evidence_refs", []))
        if not source_evidence.intersection(request["evidence_refs"]):
            raise CycleError("evidence_continuity", "lead review must preserve source evidence")
        if parse_time(request["reviewed_at"], "lead-review.reviewed_at") < parse_time(
            interaction["occurred_at"], "interaction.occurred_at"
        ):
            raise CycleError("time_order", "lead review is before interaction")
        if request["decision"] == "reject":
            interaction["lead_promotion_status"] = "rejected"
            return
        business_event_type = heads["interaction-business-type"].get(
            interaction["interaction_event_id"]
        )
        if business_event_type not in tracker.QUALIFYING_BUSINESS_EVENTS:
            raise CycleError("non_qualifying_business_event", interaction["interaction_event_id"])
        interaction["lead_promotion_status"] = "promoted"
        lead_id = tracker.stable_operation_id(
            "lead", f"lead|{interaction['interaction_event_id']}"
        )
        dedupe = tracker.sha256_bytes(
            f"{interaction['interaction_event_id']}|{business_event_type}".encode("utf-8")
        )
        publication = next(
            event for event in heads["publication-event"]
            if event["publication_id"] == interaction["publication_id"]
            and event["event_type"] == "published"
        )
        heads["lead-event"].append(
            {
                "schema_version": "0.1",
                "data_classification": interaction["data_classification"],
                "lead_event_id": lead_id,
                "source_interaction_event_id": interaction["interaction_event_id"],
                "source_publication_id": interaction["publication_id"],
                "account_id": interaction["account_id"],
                "business_event_type": business_event_type,
                "dedupe_key": f"lead-dedupe:{dedupe}",
                "review": {
                    "human_confirmed": True,
                    "decision": "confirmed-lead",
                    "reviewer_ref": request["reviewer_ref"],
                    "reviewed_at": request["reviewed_at"],
                    "receipt_ref": request["receipt_ref"],
                    "receipt_sha256": request["receipt_sha256"],
                    "review_scope_sha256": request["review_scope_sha256"],
                    "evidence_refs": request["evidence_refs"],
                },
                "consent_status": request["consent_status"],
                "attribution": {
                    "type": request["attribution_type"],
                    "window_start": publication["occurred_at"],
                    "window_end": request["reviewed_at"],
                    "model": request["attribution_model"],
                },
                "handoff": {
                    "status": "not-started",
                    "next_step_summary": None,
                    "receipt_ref": None,
                },
                "privacy": {
                    "deidentified": True,
                    "raw_message_included": False,
                    "direct_identifiers_included": False,
                },
                "authority": {
                    "execution_authorized": False,
                    "crm_write_performed": False,
                    "do_not_auto_contact": True,
                    "publication_authority": "never",
                },
                "created_at": request["reviewed_at"],
            }
        )
    elif operation in CONTRACT_RECORD_OPERATIONS:
        heads[payload["component"]].append(copy.deepcopy(payload["artifact"]))
    elif operation == "build-review":
        heads["operating-review"].append(
            build_operating_review(payload["review_request"], heads)
        )
    else:
        raise CycleError("unknown_operation", operation)


def build_heads(records: list[dict[str, Any]]) -> dict[str, Any]:
    heads: dict[str, Any] = {
        **{kind: [] for kind in HEAD_FILES},
        "source-context": [],
        "interaction-business-type": {},
    }
    for record in records:
        apply_record(heads, record)
    for key in HEAD_FILES:
        id_field = {
            "publication-event": "event_id",
            "performance-snapshot": "snapshot_id",
            "interaction-event": "interaction_event_id",
            "lead-event": "lead_event_id",
            "experiment-run": "experiment_run_id",
            "diagnostic-run": "diagnostic_run_id",
            "resource-ledger-event": "resource_event_id",
            "revenue-attribution-event": "revenue_event_id",
            "account-continuity-plan": "continuity_plan_id",
            "account-security-event": "security_event_id",
            "operating-review": "operating_review_id",
        }[key]
        heads[key] = sorted(heads[key], key=lambda item: item[id_field])
    contexts: dict[tuple[str, str], dict[str, Any]] = {}
    for context in heads["source-context"]:
        key = (
            context["goal_ref"],
            context["account_ref"],
            context["topic_ref"],
            context["content_item_ref"],
        )
        previous = contexts.get(key)
        if previous is not None and previous != context:
            raise CycleError("source_context_conflict", str(key))
        contexts[key] = context
    heads["source-context"] = [contexts[key] for key in sorted(contexts)]
    return heads


def serialized_heads(records: list[dict[str, Any]], heads: dict[str, Any]) -> dict[str, Any]:
    files: dict[str, Any] = {
        filename: {"schema_version": HEADS_SCHEMA_VERSION, "items": heads[kind]}
        for kind, filename in HEAD_FILES.items()
    }
    files["source-context.json"] = {
        "schema_version": HEADS_SCHEMA_VERSION,
        "items": heads["source-context"],
    }
    files["manifest.json"] = {
        "schema_version": HEADS_SCHEMA_VERSION,
        "journal_record_count": len(records),
        "journal_chain_sha256": canonical_hash(
            [record["record_sha256"] for record in records]
        ),
        "counts": {kind: len(heads[kind]) for kind in HEAD_FILES},
        "boundaries": {
            "manual_publication_only": True,
            "external_io_performed": False,
            "crm_write_performed": False,
            "execution_authorized": False,
        },
    }
    return files


def expected_store_anchor(records: list[dict[str, Any]]) -> dict[str, Any]:
    if not records:
        raise CycleError("empty_store", "a governed store must contain at least one record")
    return {
        "schema_version": STORE_ANCHOR_VERSION,
        "journal_record_count": len(records),
        "tail_record_sha256": records[-1]["record_sha256"],
        "journal_chain_sha256": canonical_hash(
            [record["record_sha256"] for record in records]
        ),
        "data_classification": records[0]["data_classification"],
        "contract_set": contract_set_identity(),
        "authority": {
            "execution_authorized": False,
            "publication_authority": "never",
            "crm_write_authorized": False,
            "external_send_authorized": False,
        },
    }


def make_store_metadata(first_record: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": STORE_METADATA_VERSION,
        "store_id": tracker.stable_operation_id(
            "store", f"store|{first_record['operation_id']}|{first_record['data_classification']}"
        ),
        "data_classification": first_record["data_classification"],
        "contract_set": contract_set_identity(),
        "boundaries": {
            "manual_publication_only": True,
            "execution_authorized": False,
            "crm_write_authorized": False,
            "external_send_authorized": False,
        },
    }


def validate_store_control(store: Path, records: list[dict[str, Any]]) -> None:
    if not records:
        raise CycleError("empty_store", "a governed store must contain at least one record")
    metadata = load_json(store / STORE_METADATA_FILE)
    anchor = load_json(store / STORE_ANCHOR_FILE)
    require_exact_keys(
        metadata,
        {"schema_version", "store_id", "data_classification", "contract_set", "boundaries"},
        set(),
        "store-metadata",
    )
    if metadata["schema_version"] != STORE_METADATA_VERSION:
        raise CycleError("store_metadata_version_drift", metadata["schema_version"])
    expected_store_id = tracker.stable_operation_id(
        "store", f"store|{records[0]['operation_id']}|{records[0]['data_classification']}"
    )
    if metadata["store_id"] != expected_store_id:
        raise CycleError("store_identity_drift", metadata["store_id"])
    if metadata["data_classification"] != records[0]["data_classification"]:
        raise CycleError("classification_drift", "store metadata")
    if metadata["contract_set"] != contract_set_identity():
        raise CycleError("contract_set_drift", "store metadata")
    if metadata["boundaries"] != {
        "manual_publication_only": True,
        "execution_authorized": False,
        "crm_write_authorized": False,
        "external_send_authorized": False,
    }:
        raise CycleError("authority_drift", "store metadata")
    expected = expected_store_anchor(records)
    if anchor != expected:
        raise CycleError("store_anchor_drift", STORE_ANCHOR_FILE)


def write_store_anchor(store: Path, records: list[dict[str, Any]]) -> None:
    write_json(store / STORE_ANCHOR_FILE, expected_store_anchor(records))


def checkpoint_control_root(store: Path) -> Path:
    store = validate_store_location(store)
    control = store.with_name(f".{store.name}.control")
    allowed_store_root(control)
    if control.exists():
        if not control.is_dir() or is_reparse_point(control):
            raise CycleError("unsafe_checkpoint_path", str(control))
        validate_store_tree(control)
    return control


def checkpoint_file(store: Path) -> Path:
    return checkpoint_control_root(store) / STORE_CHECKPOINT_FILE


def checkpoint_projection(checkpoint: dict[str, Any]) -> dict[str, Any]:
    return {
        "journal_record_count": checkpoint["journal_record_count"],
        "tail_record_sha256": checkpoint["tail_record_sha256"],
        "journal_chain_sha256": checkpoint["journal_chain_sha256"],
    }


def read_external_checkpoints(store: Path) -> list[dict[str, Any]]:
    path = checkpoint_file(store)
    if not path.exists():
        return []
    checkpoints: list[dict[str, Any]] = []
    previous_hash: str | None = None
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise CycleError("checkpoint_unreadable", str(path)) from error
    if not lines:
        raise CycleError("checkpoint_empty", str(path))
    for index, line in enumerate(lines, start=1):
        try:
            checkpoint = json.loads(line)
        except json.JSONDecodeError as error:
            raise CycleError("checkpoint_invalid_json", f"{path}:{index}: {error}") from error
        require_exact_keys(
            checkpoint,
            {
                "schema_version", "checkpoint_sequence", "store_id",
                "journal_record_count", "tail_record_sha256", "journal_chain_sha256",
                "data_classification", "contract_set", "prev_checkpoint_sha256",
                "phase", "authority", "checkpoint_sha256",
            },
            set(),
            f"external-checkpoint[{index}]",
        )
        if checkpoint["schema_version"] != STORE_CHECKPOINT_VERSION:
            raise CycleError("checkpoint_version_drift", str(index))
        if checkpoint["checkpoint_sequence"] != index:
            raise CycleError("checkpoint_sequence_drift", str(index))
        if checkpoint["journal_record_count"] != index:
            raise CycleError("checkpoint_count_drift", str(index))
        validate_sha256(checkpoint["tail_record_sha256"], f"checkpoint[{index}].tail")
        validate_sha256(checkpoint["journal_chain_sha256"], f"checkpoint[{index}].chain")
        if checkpoint["prev_checkpoint_sha256"] != previous_hash:
            raise CycleError("checkpoint_chain_drift", str(index))
        if checkpoint["phase"] != "committed":
            raise CycleError("checkpoint_phase_drift", str(index))
        if checkpoint["authority"] != {
            "execution_authorized": False,
            "publication_authority": "never",
            "crm_write_authorized": False,
            "external_send_authorized": False,
        }:
            raise CycleError("checkpoint_authority_drift", str(index))
        checkpoint_hash = checkpoint["checkpoint_sha256"]
        validate_sha256(checkpoint_hash, f"checkpoint[{index}].checkpoint_sha256")
        body = copy.deepcopy(checkpoint)
        body.pop("checkpoint_sha256")
        if canonical_hash(body) != checkpoint_hash:
            raise CycleError("checkpoint_hash_drift", str(index))
        previous_hash = checkpoint_hash
        checkpoints.append(checkpoint)
    return checkpoints


def validate_external_checkpoint(
    control_store: Path,
    records: list[dict[str, Any]],
    metadata: dict[str, Any],
    *,
    allow_next: bool = False,
) -> None:
    checkpoints = read_external_checkpoints(control_store)
    if not checkpoints:
        if allow_next and len(records) == 1:
            return
        raise CycleError("external_checkpoint_missing", str(checkpoint_file(control_store)))
    latest = checkpoints[-1]
    if latest["store_id"] != metadata["store_id"]:
        raise CycleError("checkpoint_store_drift", metadata["store_id"])
    if latest["data_classification"] != metadata["data_classification"]:
        raise CycleError("checkpoint_classification_drift", metadata["store_id"])
    if latest["contract_set"] != metadata["contract_set"]:
        raise CycleError("checkpoint_contract_drift", metadata["store_id"])
    current = source_checkpoint(records)
    latest_projection = checkpoint_projection(latest)
    if current == latest_projection:
        return
    if allow_next and len(records) == latest["journal_record_count"] + 1:
        if source_checkpoint(records[:-1]) == latest_projection:
            return
    raise CycleError("external_checkpoint_drift", metadata["store_id"])


def append_external_checkpoint(store: Path, records: list[dict[str, Any]]) -> None:
    store = validate_store_location(store, require_metadata=True)
    metadata = load_json(store / STORE_METADATA_FILE)
    checkpoints = read_external_checkpoints(store)
    if checkpoints:
        validate_external_checkpoint(store, records, metadata, allow_next=True)
        if len(records) != checkpoints[-1]["journal_record_count"] + 1:
            raise CycleError("checkpoint_non_monotonic_append", metadata["store_id"])
        previous_hash = checkpoints[-1]["checkpoint_sha256"]
    else:
        if len(records) != 1:
            raise CycleError("checkpoint_bootstrap_drift", metadata["store_id"])
        previous_hash = None
    anchor = expected_store_anchor(records)
    body = {
        "schema_version": STORE_CHECKPOINT_VERSION,
        "checkpoint_sequence": len(checkpoints) + 1,
        "store_id": metadata["store_id"],
        "journal_record_count": anchor["journal_record_count"],
        "tail_record_sha256": anchor["tail_record_sha256"],
        "journal_chain_sha256": anchor["journal_chain_sha256"],
        "data_classification": metadata["data_classification"],
        "contract_set": metadata["contract_set"],
        "prev_checkpoint_sha256": previous_hash,
        "phase": "committed",
        "authority": {
            "execution_authorized": False,
            "publication_authority": "never",
            "crm_write_authorized": False,
            "external_send_authorized": False,
        },
    }
    checkpoint = {**body, "checkpoint_sha256": canonical_hash(body)}
    path = checkpoint_file(store)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(checkpoint, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as error:
        raise CycleError("checkpoint_append_failed", str(path)) from error
    validate_external_checkpoint(store, records, metadata)


def source_checkpoint(records: list[dict[str, Any]]) -> dict[str, Any]:
    anchor = expected_store_anchor(records)
    return {
        "journal_record_count": anchor["journal_record_count"],
        "tail_record_sha256": anchor["tail_record_sha256"],
        "journal_chain_sha256": anchor["journal_chain_sha256"],
    }


def require_source_checkpoint(request: dict[str, Any], records: list[dict[str, Any]]) -> None:
    if request["source_checkpoint"] != source_checkpoint(records):
        raise CycleError("source_head_drift", "build-review source checkpoint is not current")


def write_heads(store: Path, records: list[dict[str, Any]], heads: dict[str, Any]) -> None:
    root = store / "heads"
    if root.exists():
        safe_rmtree(root)
    root.mkdir(parents=True)
    for name, value in serialized_heads(records, heads).items():
        write_json(root / name, value)


def load_actual_heads(store: Path) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for kind, filename in HEAD_FILES.items():
        result[kind] = load_json(store / "heads" / filename).get("items")
    result["source-context"] = load_json(store / "heads" / "source-context.json").get("items")
    result["manifest"] = load_json(store / "heads" / "manifest.json")
    return result


def validate_publication_event_chains(events: list[dict[str, Any]]) -> None:
    event_index = {event["event_id"]: event for event in events}
    groups: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        groups.setdefault(event["publication_id"], []).append(event)
    terminal_by_publication = {
        publication_id: max(group, key=lambda item: item["event_sequence"])
        for publication_id, group in groups.items()
    }
    for publication_id, group in groups.items():
        ordered = sorted(group, key=lambda item: item["event_sequence"])
        expected_sequences = list(range(1, len(ordered) + 1))
        if [item["event_sequence"] for item in ordered] != expected_sequences:
            raise CycleError("publication_sequence_gap", publication_id)
        first = ordered[0]
        replacement_source_id = first.get("supersedes_event_id")
        if replacement_source_id is not None:
            source = event_index.get(replacement_source_id)
            if (
                first["event_type"] != "published"
                or source is None
                or source["event_type"] != "deleted"
                or source["publication_id"] == publication_id
                or terminal_by_publication[source["publication_id"]]["event_id"] != source["event_id"]
                or any(
                    first[field] != source[field]
                    for field in ("account_id", "content_id", "platform")
                )
            ):
                raise CycleError(
                    "replacement_chain_invalid",
                    f"{publication_id} must replace a terminal deleted publication",
                )
        for previous, current in zip(ordered, ordered[1:]):
            if current.get("supersedes_event_id") != previous["event_id"]:
                raise CycleError(
                    "publication_supersedes_drift",
                    f"{current['event_id']} must supersede {previous['event_id']}",
                )
        publication_state(ordered, publication_id)


def validate_heads_semantics(heads: dict[str, Any]) -> None:
    contract_set = load_contract_set()
    for kind in HEAD_FILES:
        schema = contract_set["schemas"][kind]
        for index, item in enumerate(heads[kind]):
            validate_instance(item, schema, f"{kind}[{index}]")
    validate_publication_event_chains(heads["publication-event"])
    accounts: list[dict[str, Any]] = []
    goals: list[dict[str, Any]] = []
    topics: list[dict[str, Any]] = []
    content_items: list[dict[str, Any]] = []
    for context in heads["source-context"]:
        _, goal = resolve_source(
            context["goal_ref"], context["goal_sha256"], "operating-goal"
        )
        _, account = resolve_source(context["account_ref"], context["account_sha256"], "account")
        _, topic = resolve_source(context["topic_ref"], context["topic_sha256"], "topic")
        _, content = resolve_source(
            context["content_item_ref"], context["content_item_sha256"], "content-item"
        )
        validate_instance(
            goal, contract_set["schemas"]["operating-goal"], "source.operating-goal"
        )
        validate_instance(account, contract_set["schemas"]["account"], "source.account")
        validate_instance(topic, contract_set["schemas"]["topic"], "source.topic")
        validate_instance(content, load_json(CONTENT_SCHEMA), "source.content-item")
        goals.append(goal)
        accounts.append(account)
        topics.append(topic)
        content_items.append(content)
    fixtures: dict[str, Any] = {component: [] for component in CONTRACT_VALIDATOR.EXPECTED_COMPONENTS}
    fixtures["operating-goal"] = list(
        {item["goal_id"]: item for item in goals}.values()
    )
    fixtures["account"] = list(
        {item["account_id"]: item for item in accounts}.values()
    )
    fixtures["topic"] = list(
        {item["topic_id"]: item for item in topics}.values()
    )
    for kind in HEAD_FILES:
        fixtures[kind] = heads[kind]
    errors: list[str] = []
    CONTRACT_VALIDATOR.validate_fixture_privacy(fixtures, errors)
    CONTRACT_VALIDATOR.validate_cross_object_semantics(fixtures, content_items, errors)
    if errors:
        raise CycleError("cross_object_validation_failed", errors[0])


def validate_store_strict(
    store: Path,
    *,
    compare_heads: bool = True,
    checkpoint_store: Path | None = None,
    allow_checkpoint_next: bool = False,
    check_external_checkpoint: bool = True,
) -> dict[str, Any]:
    store = validate_store_location(store, require_metadata=True)
    validate_store_tree(store)
    records = read_journal(store)
    validate_store_control(store, records)
    if check_external_checkpoint:
        validate_external_checkpoint(
            checkpoint_store or store,
            records,
            load_json(store / STORE_METADATA_FILE),
            allow_next=allow_checkpoint_next,
        )
    heads = build_heads(records)
    validate_heads_semantics(heads)
    expected = serialized_heads(records, heads)
    if compare_heads:
        for name, value in expected.items():
            actual = load_json(store / "heads" / name)
            if actual != value:
                raise CycleError("head_drift", name)
    return {
        "status": "passed",
        "journal_records": len(records),
        "counts": expected["manifest.json"]["counts"],
        "execution_authorized": False,
    }


def recover_store(store: Path) -> None:
    store = validate_store_location(store)
    lock = store.with_name(f".{store.name}.lock")
    if lock.exists():
        raise CycleError("store_locked", str(lock))
    backup = store.with_name(f".{store.name}.backup")
    staging_paths = sorted(store.parent.glob(f".{store.name}.staging.*"))
    if store.exists() and backup.exists():
        validate_store_strict(store)
        validate_store_strict(backup, checkpoint_store=store)
        raise CycleError("recovery_ambiguous", "store and backup are both valid; both were preserved")
    if staging_paths and (store.exists() or backup.exists() or len(staging_paths) > 1):
        if store.exists():
            validate_store_strict(store)
        if backup.exists():
            validate_store_strict(backup, checkpoint_store=store)
        for staging in staging_paths:
            validate_store_strict(staging, checkpoint_store=store)
        raise CycleError("recovery_ambiguous", "multiple recovery candidates were preserved")
    if not store.exists() and backup.exists():
        validate_store_strict(backup, checkpoint_store=store)
        safe_rename(backup, store)
    elif not store.exists() and len(staging_paths) == 1:
        validate_store_strict(staging_paths[0], checkpoint_store=store)
        safe_rename(staging_paths[0], store)


@contextmanager
def store_lock(store: Path) -> Iterator[None]:
    store = validate_store_location(store)
    store.parent.mkdir(parents=True, exist_ok=True)
    lock = store.with_name(f".{store.name}.lock")
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as error:
        raise CycleError("store_locked", str(lock)) from error
    os.close(descriptor)
    try:
        yield
    finally:
        lock.unlink(missing_ok=True)


def swap_store(store: Path, staging: Path, *, checkpoint_mode: str) -> None:
    store = validate_store_location(store)
    staging = validate_store_location(staging, require_metadata=True)
    backup = store.with_name(f".{store.name}.backup")
    if backup.exists():
        raise CycleError("stale_backup", str(backup))
    if store.exists():
        safe_rename(store, backup)
    try:
        safe_rename(staging, store)
    except BaseException:
        if backup.exists() and not store.exists():
            safe_rename(backup, store)
        raise
    try:
        validate_store_strict(store, check_external_checkpoint=False)
        records = read_journal(store)
        if checkpoint_mode == "advance":
            append_external_checkpoint(store, records)
        elif checkpoint_mode == "same":
            validate_external_checkpoint(
                store, records, load_json(store / STORE_METADATA_FILE)
            )
        else:
            raise CycleError("invalid_checkpoint_mode", checkpoint_mode)
    except BaseException:
        if store.exists():
            safe_rmtree(store)
        if backup.exists():
            safe_rename(backup, store)
        raise
    if backup.exists():
        safe_rmtree(backup)


def commit_operation(
    store: Path,
    operation_type: str,
    identity_key: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    store = validate_store_location(store)
    recover_store(store)
    with store_lock(store):
        if store.exists():
            validate_store_strict(store)
            records = read_journal(store)
        else:
            records = []
        if records and records[0]["data_classification"] != payload["data_classification"]:
            raise CycleError("classification_mixing_prohibited", identity_key)
        payload_sha256 = canonical_hash(payload)
        for record in records:
            if record["identity_key"] != identity_key:
                continue
            if record["payload_sha256"] == payload_sha256:
                if operation_type == "build-review":
                    request = payload["review_request"]
                    if record["sequence"] != len(records):
                        raise CycleError("source_head_drift", "late data followed the stored review")
                    prefix = records[: record["sequence"] - 1]
                    require_source_checkpoint(request, prefix)
                return {
                    "status": "already_recorded",
                    "operation_id": record["operation_id"],
                    "identity_key": identity_key,
                    "journal_sequence": record["sequence"],
                }
            raise CycleError("operation_conflict", identity_key)
        if operation_type == "build-review":
            require_source_checkpoint(payload["review_request"], records)
        previous_record_sha256 = records[-1]["record_sha256"] if records else None
        record = make_journal_record(
            len(records) + 1,
            operation_type,
            identity_key,
            payload,
            previous_record_sha256,
        )
        staging = store.with_name(f".{store.name}.staging.{record['operation_id']}")
        if staging.exists():
            safe_rmtree(staging)
        if store.exists():
            shutil.copytree(store, staging)
        else:
            staging.mkdir(parents=True)
        try:
            if not (staging / STORE_METADATA_FILE).exists():
                write_json(staging / STORE_METADATA_FILE, make_store_metadata(record))
            write_json(
                staging / "journal" / f"{record['sequence']:08d}-{record['operation_id']}.json",
                record,
            )
            staged_records = read_journal(staging)
            heads = build_heads(staged_records)
            write_store_anchor(staging, staged_records)
            write_heads(staging, staged_records, heads)
            validate_store_strict(
                staging,
                checkpoint_store=store,
                allow_checkpoint_next=True,
            )
            swap_store(store, staging, checkpoint_mode="advance")
        except BaseException:
            if staging.exists():
                safe_rmtree(staging)
            raise
        return {
            "status": "recorded",
            "operation_id": record["operation_id"],
            "identity_key": identity_key,
            "journal_sequence": record["sequence"],
        }


def record_from_input(store: Path, operation_type: str, input_path: Path) -> dict[str, Any]:
    entry = load_json(input_path)
    if operation_type == "record-publication":
        payload, identity = validate_publication_input(entry)
    elif operation_type in PUBLICATION_CHANGE_TYPES:
        payload, identity = validate_publication_change_input(store, entry, operation_type)
    elif operation_type == "record-snapshot":
        payload, identity = validate_snapshot_input(entry)
    elif operation_type == "record-interaction":
        payload, identity = validate_interaction_input(entry)
    elif operation_type == "review-lead":
        payload, identity = validate_lead_review_input(entry)
    elif operation_type in CONTRACT_RECORD_OPERATIONS:
        payload, identity = validate_contract_record_input(entry, operation_type)
    elif operation_type == "build-review":
        payload, identity = validate_review_input(entry)
    else:
        raise CycleError("unknown_operation", operation_type)
    return commit_operation(store, operation_type, identity, payload)


def rebuild_store_heads(store: Path) -> dict[str, Any]:
    store = validate_store_location(store, require_metadata=True)
    recover_store(store)
    with store_lock(store):
        # Journal + immutable root anchor are authoritative.  Rebuild is allowed
        # to repair derived heads, but never a journal/anchor/control failure.
        validate_store_strict(store, compare_heads=False)
        records = read_journal(store)
        staging = store.with_name(f".{store.name}.staging.rebuild")
        if staging.exists():
            safe_rmtree(staging)
        if store.exists():
            shutil.copytree(store, staging)
        else:
            raise CycleError("artifact_missing", str(store))
        try:
            heads = build_heads(records)
            write_heads(staging, records, heads)
            validate_store_strict(staging, checkpoint_store=store)
            swap_store(store, staging, checkpoint_mode="same")
        except BaseException:
            if staging.exists():
                safe_rmtree(staging)
            raise
    return {"status": "heads_rebuilt", "journal_records": len(records)}


def file_map(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def demo(store: Path, fixture_root: Path = DEFAULT_FIXTURE_ROOT) -> dict[str, Any]:
    steps = [
        ("record-publication", "record-publication.input.json"),
        ("record-snapshot", "record-snapshot-early.input.json"),
        ("record-snapshot", "record-snapshot-d7.input.json"),
        ("record-interaction", "record-interaction-business.input.json"),
        ("review-lead", "review-lead-confirm.input.json"),
        ("record-experiment", "record-experiment.input.json"),
        ("record-diagnostic", "record-diagnostic.input.json"),
        ("record-resource", "record-resource.input.json"),
        ("record-revenue", "record-revenue.input.json"),
        ("record-continuity", "record-continuity.input.json"),
        ("record-security", "record-security.input.json"),
        ("build-review", "build-review.input.json"),
    ]
    for _, filename in steps:
        if load_json(fixture_root / filename).get("data_classification") != "synthetic-only":
            raise CycleError("demo_non_synthetic_fixture", filename)
    results = [
        record_from_input(store, operation, fixture_root / filename)
        for operation, filename in steps
    ]
    validation = validate_store_strict(store)
    return {
        "status": "demo_passed",
        "steps": results,
        "validation": validation,
        "synthetic_only": all(
            record["data_classification"] == "synthetic-only"
            for record in read_journal(store)
        ),
        "execution_authorized": False,
    }


def check(fixture_root: Path = DEFAULT_FIXTURE_ROOT) -> dict[str, Any]:
    temp_root = (
        ROOT / "tests" / ".runtime" / "content-operations" /
        f"check-{os.getpid()}-{uuid.uuid4().hex}"
    )
    run_a = temp_root / "a"
    run_b = temp_root / "b"
    try:
        first = demo(run_a, fixture_root)
        replay = demo(run_a, fixture_root)
        second = demo(run_b, fixture_root)
        if not all(step["status"] == "already_recorded" for step in replay["steps"]):
            raise CycleError("idempotency_failed", "demo replay was not already_recorded")
        if file_map(run_a) != file_map(run_b):
            raise CycleError("idempotency_failed", "independent demos differ")
        return {
            "status": "passed",
            "journal_records": first["validation"]["journal_records"],
            "idempotency": "byte-stable",
            "synthetic_only": True,
            "execution_authorized": False,
        }
    finally:
        if temp_root.exists():
            safe_rmtree(temp_root)


def add_command_authority(result: dict[str, Any]) -> dict[str, Any]:
    result["authority"] = {
        "execution_authorized": False,
        "publication_mode": "manual-only",
        "crm_write_authorized": False,
        "external_send_authorized": False,
    }
    return result


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in (
        "record-publication", "record-publication-edit", "record-publication-delete",
        "record-publication-restore", "record-snapshot", "record-interaction", "review-lead",
        "record-experiment", "record-diagnostic", "record-resource", "record-revenue",
        "record-continuity", "record-security", "build-review"
    ):
        item = subparsers.add_parser(command)
        item.add_argument("--store", type=Path, required=True)
        item.add_argument("--input", type=Path, required=True)
    validate = subparsers.add_parser("validate-store")
    validate.add_argument("--store", type=Path, required=True)
    rebuild = subparsers.add_parser("rebuild-heads")
    rebuild.add_argument("--store", type=Path, required=True)
    demo_parser = subparsers.add_parser("demo")
    demo_parser.add_argument("--store", type=Path, required=True)
    demo_parser.add_argument("--fixture-root", type=Path, default=DEFAULT_FIXTURE_ROOT)
    check_parser = subparsers.add_parser("check")
    check_parser.add_argument("--fixture-root", type=Path, default=DEFAULT_FIXTURE_ROOT)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.command in INPUT_VERSIONS:
            result = record_from_input(args.store, args.command, args.input)
        elif args.command == "validate-store":
            recover_store(args.store)
            result = validate_store_strict(args.store)
        elif args.command == "rebuild-heads":
            result = rebuild_store_heads(args.store)
        elif args.command == "demo":
            result = demo(args.store, args.fixture_root)
        else:
            result = check(args.fixture_root)
        print(json_text(add_command_authority(result)), end="")
        return 0
    except (CycleError, tracker.TrackerError) as error:
        code = error.code if hasattr(error, "code") else "tracker_error"
        print(
            json_text(add_command_authority({"status": code, "message": str(error)})),
            end="",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
