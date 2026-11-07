#!/usr/bin/env python3
"""Validate self-media operating schemas, fixtures, and cross-object references."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator, FormatChecker


WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
CONTENT_SYSTEM_ROOT = WORKSPACE_ROOT / "docs" / "content-creation-system"
CONTRACT_SET_MANIFEST = "operations-contract-set.v1.json"
CONTRACT_SET_SCHEMA = "operations-contract-set.v1.schema.json"
EXPECTED_COMPONENTS = (
    "operating-goal",
    "account",
    "topic",
    "publication-event",
    "performance-snapshot",
    "interaction-event",
    "lead-event",
    "experiment-run",
    "resource-ledger-event",
    "revenue-attribution-event",
    "account-continuity-plan",
    "account-security-event",
    "operating-review",
    "diagnostic-run",
)

SIX_SIGNAL_LAYERS = {
    "admission",
    "attraction",
    "consumption",
    "value",
    "negative_feedback",
    "business",
}

SENSITIVE_TEXT_PATTERNS = {
    "phone-number": re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"),
    "email-address": re.compile(
        r"(?i)(?<![A-Z0-9._%+-])[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}(?![A-Z0-9.-])"
    ),
    "windows-absolute-path": re.compile(r"(?i)(?:^|[\s\"'])(?:[A-Z]:[\\/])"),
    "bearer-token": re.compile(r"(?i)\bbearer\s+[A-Z0-9._~+/=-]{8,}"),
    "cookie-header": re.compile(r"(?i)\b(?:cookie|set-cookie)\s*:\s*\S+"),
    "credential-assignment": re.compile(
        r"(?i)\b(?:api[_ -]?key|access[_ -]?token|refresh[_ -]?token|token|secret|"
        r"password|recovery[_ -]?code|backup[_ -]?code)\b\s*[:=]\s*\S+"
    ),
    "known-token-prefix": re.compile(
        r"\b(?:sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,})\b"
    ),
    "private-key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
}

REVIEW_REF_SPECS = {
    "publication_ids": "publication",
    "snapshot_ids": "snapshot",
    "interaction_event_ids": "interaction",
    "lead_event_ids": "lead",
    "experiment_run_ids": "experiment",
    "diagnostic_run_ids": "diagnostic",
    "resource_event_ids": "resource",
    "revenue_event_ids": "revenue",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--contract-set-root",
        type=Path,
        default=CONTENT_SYSTEM_ROOT,
        help="Directory containing the atomic operations contract-set manifest.",
    )
    parser.add_argument(
        "--operations-root",
        type=Path,
        default=CONTENT_SYSTEM_ROOT / "operations",
    )
    parser.add_argument(
        "--content-root",
        type=Path,
        default=CONTENT_SYSTEM_ROOT / "shadow-imports",
    )
    parser.add_argument(
        "--content-example",
        type=Path,
        default=CONTENT_SYSTEM_ROOT / "example-content-item.json",
    )
    parser.add_argument(
        "--diagnostics-root",
        type=Path,
        default=None,
        help="Defaults to the diagnostics directory beside --operations-root.",
    )
    return parser.parse_args()


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


class OperatingContractError(ValueError):
    """Raised when the atomic operating-contract set is missing, mixed, or stale."""


def canonical_json_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ) + "\n"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def expected_artifact_path(component_id: str, artifact_kind: str) -> str:
    base = "diagnostics" if component_id == "diagnostic-run" else "operations"
    if artifact_kind == "schema":
        return f"{base}/{component_id}.schema.json"
    if artifact_kind == "fixture":
        return f"{base}/fixtures/{component_id}.json"
    raise OperatingContractError(f"unknown artifact kind: {artifact_kind}")


def resolve_contract_artifact(root: Path, relative_path: str, label: str) -> Path:
    candidate_relative = Path(relative_path)
    if candidate_relative.is_absolute() or ".." in candidate_relative.parts:
        raise OperatingContractError(f"{label}: mixed or absolute path prohibited")
    candidate = (root / candidate_relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise OperatingContractError(f"{label}: path escapes canonical root") from exc
    return candidate


def schema_contract_version(value: Any) -> Any:
    if not isinstance(value, dict):
        return None
    properties = value.get("properties")
    if not isinstance(properties, dict):
        return None
    schema_version = properties.get("schema_version")
    return schema_version.get("const") if isinstance(schema_version, dict) else None


def load_contract_set(
    root: Path = CONTENT_SYSTEM_ROOT,
    *,
    manifest_value_override: Mapping[str, Any] | None = None,
    artifact_value_overrides: Mapping[tuple[str, str], Any] | None = None,
) -> dict[str, Any]:
    """Load and hash-check the 13 contracts before any semantic validation."""
    root = root.resolve()
    manifest_path = root / CONTRACT_SET_MANIFEST
    manifest_schema_path = root / CONTRACT_SET_SCHEMA
    if not manifest_path.is_file() or not manifest_schema_path.is_file():
        raise OperatingContractError("canonical operations manifest or schema is missing")

    manifest_schema = load_json(manifest_schema_path)
    Draft202012Validator.check_schema(manifest_schema)
    manifest = (
        dict(manifest_value_override)
        if manifest_value_override is not None
        else load_json(manifest_path)
    )
    manifest_errors = sorted(
        Draft202012Validator(
            manifest_schema,
            format_checker=FormatChecker(),
        ).iter_errors(manifest),
        key=lambda item: list(item.path),
    )
    if manifest_errors:
        raise OperatingContractError(
            f"operations manifest schema invalid: {manifest_errors[0].message}"
        )

    components = manifest["components"]
    if set(components) != set(EXPECTED_COMPONENTS):
        raise OperatingContractError("operations component coverage drift")

    value_overrides = dict(artifact_value_overrides or {})
    unknown_overrides = set(value_overrides) - {
        (component_id, artifact_kind)
        for component_id in EXPECTED_COMPONENTS
        for artifact_kind in ("schema", "fixture")
    }
    if unknown_overrides:
        raise OperatingContractError(
            f"unknown operations artifact override: {sorted(unknown_overrides)}"
        )

    schemas: dict[str, dict[str, Any]] = {}
    fixtures: dict[str, Any] = {}
    schema_paths: dict[str, Path] = {}
    fixture_paths: dict[str, Path] = {}
    for component_id in EXPECTED_COMPONENTS:
        component = components[component_id]
        for artifact_kind in ("schema", "fixture"):
            record = component[artifact_kind]
            expected_path = expected_artifact_path(component_id, artifact_kind)
            if record["path"] != expected_path:
                raise OperatingContractError(
                    f"{component_id}.{artifact_kind}: path is not canonical"
                )
            artifact_path = resolve_contract_artifact(
                root,
                record["path"],
                f"{component_id}.{artifact_kind}",
            )
            value = value_overrides.get((component_id, artifact_kind))
            if value is None:
                value = load_json(artifact_path)
            actual_version = (
                schema_contract_version(value)
                if artifact_kind == "schema"
                else value.get("schema_version") if isinstance(value, dict) else None
            )
            if actual_version != record["schema_version"]:
                raise OperatingContractError(
                    f"{component_id}.{artifact_kind}: schema version drift"
                )
            if canonical_json_sha256(value) != record["canonical_json_sha256"]:
                raise OperatingContractError(
                    f"{component_id}.{artifact_kind}: canonical hash drift"
                )
            if artifact_kind == "schema":
                schemas[component_id] = value
                schema_paths[component_id] = artifact_path
            else:
                fixtures[component_id] = value
                fixture_paths[component_id] = artifact_path

    return {
        "manifest": manifest,
        "schemas": schemas,
        "fixtures": fixtures,
        "schema_paths": schema_paths,
        "fixture_paths": fixture_paths,
    }


def validate_document(path: Path, schema: dict[str, Any]) -> list[str]:
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors: list[str] = []
    for error in sorted(validator.iter_errors(load_json(path)), key=lambda value: list(value.path)):
        location = ".".join(str(part) for part in error.path) or "$"
        errors.append(f"{path}: {location}: {error.message}")
    return errors


def fixture_records(value: Any) -> list[dict[str, Any]]:
    """Return semantic-check records while schema validation remains authoritative."""
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def require_time_order(
    start_value: Any,
    end_value: Any,
    label: str,
    errors: list[str],
    *,
    allow_equal: bool = True,
) -> tuple[datetime | None, datetime | None]:
    start = parse_timestamp(start_value)
    end = parse_timestamp(end_value)
    if start is not None and end is not None:
        invalid = end < start if allow_equal else end <= start
        if invalid:
            relation = "before" if allow_equal else "not after"
            errors.append(f"{label}: end is {relation} start")
    return start, end


def duplicate_values(values: list[Any]) -> list[Any]:
    counts = Counter(value for value in values if value is not None)
    return sorted((value for value, count in counts.items() if count > 1), key=str)


def build_index(
    records: list[dict[str, Any]],
    id_field: str,
    label: str,
    errors: list[str],
) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for record in records:
        record_id = record.get(id_field)
        if not isinstance(record_id, str):
            continue
        if record_id in index:
            errors.append(f"{label}.{id_field}: duplicate {record_id}")
            continue
        index[record_id] = record
    return index


def require_reference(
    value: Any,
    known: Any,
    label: str,
    errors: list[str],
    seen_refs: dict[str, set[str]],
    ref_kind: str,
) -> None:
    if value is None:
        return
    text = str(value)
    seen_refs[ref_kind].add(text)
    if value not in known:
        errors.append(f"{label}: unresolved {value}")


def require_references(
    values: Any,
    known: Any,
    label: str,
    errors: list[str],
    seen_refs: dict[str, set[str]],
    ref_kind: str,
) -> None:
    if not isinstance(values, list):
        return
    for value in values:
        require_reference(value, known, label, errors, seen_refs, ref_kind)


def records_share_field(
    records: list[dict[str, Any]], field: str, label: str, errors: list[str]
) -> None:
    values = {record.get(field) for record in records if record.get(field) is not None}
    if len(values) > 1:
        errors.append(f"{label}.{field}: inconsistent values {sorted(values, key=str)}")


def iter_string_values(value: Any, path: str = "$") -> Any:
    """Yield paths and string values without echoing sensitive values in errors."""
    if isinstance(value, dict):
        for key, child in value.items():
            yield from iter_string_values(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from iter_string_values(child, f"{path}[{index}]")
    elif isinstance(value, str):
        yield path, value


def validate_fixture_privacy(fixtures: dict[str, Any], errors: list[str]) -> None:
    """Reject obvious identifiers, credentials, and host paths in portable fixtures."""
    for fixture_kind, fixture in fixtures.items():
        for path, value in iter_string_values(fixture, f"fixture[{fixture_kind}]"):
            for pattern_name, pattern in SENSITIVE_TEXT_PATTERNS.items():
                if pattern.search(value):
                    errors.append(f"{path}: forbidden {pattern_name} in fixture text")


def validate_human_review_receipt(
    record: dict[str, Any],
    state_field: str,
    label: str,
    errors: list[str],
    *,
    earliest_review_value: Any = None,
) -> None:
    """Reinforce that a human-reviewed state is backed by a real receipt and time."""
    if record.get(state_field) != "human-reviewed":
        return
    review = record.get("review")
    if not isinstance(review, dict):
        errors.append(f"{label}.review: required for human-reviewed state")
        return
    if review.get("human_confirmed") is not True:
        errors.append(f"{label}.review.human_confirmed: must be true")
    for field in ("reviewer_ref", "receipt_ref"):
        value = review.get(field)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"{label}.review.{field}: non-empty value required")
    reviewed_at = parse_timestamp(review.get("reviewed_at"))
    if reviewed_at is None:
        errors.append(f"{label}.review.reviewed_at: valid timezone-aware timestamp required")
    earliest_review_at = parse_timestamp(earliest_review_value)
    if (
        reviewed_at is not None
        and earliest_review_at is not None
        and reviewed_at < earliest_review_at
    ):
        errors.append(f"{label}.review.reviewed_at: before source record time")


def validate_cross_object_semantics(
    fixtures: dict[str, Any],
    content_items: list[dict[str, Any]],
    errors: list[str],
) -> dict[str, set[str]]:
    records = {kind: fixture_records(value) for kind, value in fixtures.items()}
    seen_refs: dict[str, set[str]] = defaultdict(set)

    content_index: dict[str, dict[str, Any]] = {}
    for item in content_items:
        content_id = item.get("content_id")
        if not isinstance(content_id, str):
            continue
        if content_id in content_index:
            errors.append(f"content-item.content_id: duplicate {content_id}")
            continue
        content_index[content_id] = item

    goal_index = build_index(
        records.get("operating-goal", []), "goal_id", "operating-goal", errors
    )
    account_index = build_index(records.get("account", []), "account_id", "account", errors)
    topic_index = build_index(records.get("topic", []), "topic_id", "topic", errors)
    snapshot_index = build_index(
        records.get("performance-snapshot", []), "snapshot_id", "performance-snapshot", errors
    )
    interaction_index = build_index(
        records.get("interaction-event", []), "interaction_event_id", "interaction-event", errors
    )
    lead_index = build_index(records.get("lead-event", []), "lead_event_id", "lead-event", errors)
    experiment_index = build_index(
        records.get("experiment-run", []), "experiment_run_id", "experiment-run", errors
    )
    diagnostic_index = build_index(
        records.get("diagnostic-run", []), "diagnostic_run_id", "diagnostic-run", errors
    )
    resource_index = build_index(
        records.get("resource-ledger-event", []), "resource_event_id", "resource-ledger-event", errors
    )
    revenue_index = build_index(
        records.get("revenue-attribution-event", []),
        "revenue_event_id",
        "revenue-attribution-event",
        errors,
    )
    security_index = build_index(
        records.get("account-security-event", []), "security_event_id", "account-security-event", errors
    )
    review_index = build_index(
        records.get("operating-review", []), "operating_review_id", "operating-review", errors
    )
    build_index(
        records.get("account-continuity-plan", []),
        "continuity_plan_id",
        "account-continuity-plan",
        errors,
    )

    for goal in goal_index.values():
        require_references(
            goal.get("account_ids", []),
            account_index,
            "operating-goal.account_ids",
            errors,
            seen_refs,
            "account",
        )
        require_time_order(
            goal.get("period", {}).get("start"),
            goal.get("period", {}).get("end"),
            "operating-goal.period",
            errors,
            allow_equal=False,
        )
        require_time_order(
            goal.get("created_at"),
            goal.get("updated_at"),
            "operating-goal.updated_at",
            errors,
        )
        criterion_ids = [
            criterion.get("criterion_id")
            for criterion in goal.get("success_criteria", [])
            if isinstance(criterion, dict)
        ]
        for duplicate in duplicate_values(criterion_ids):
            errors.append(f"operating-goal.success_criteria.criterion_id: duplicate {duplicate}")
        if goal.get("status") != "draft-only":
            review = goal.get("review")
            if not isinstance(review, dict):
                errors.append("operating-goal.review: required outside draft-only state")
            else:
                reviewed_at = parse_timestamp(review.get("reviewed_at"))
                created_at = parse_timestamp(goal.get("created_at"))
                if reviewed_at is None:
                    errors.append(
                        "operating-goal.review.reviewed_at: valid timezone-aware timestamp required"
                    )
                elif created_at is not None and reviewed_at < created_at:
                    errors.append("operating-goal.review.reviewed_at: before goal creation")

    for account in account_index.values():
        require_references(
            account.get("goal_ids", []),
            goal_index,
            "account.goal_ids",
            errors,
            seen_refs,
            "operating-goal",
        )

    publication_event_index = build_index(
        records.get("publication-event", []), "event_id", "publication-event", errors
    )
    publication_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    publication_sequences: set[tuple[str, Any]] = set()
    for event in records.get("publication-event", []):
        publication_id = event.get("publication_id")
        if isinstance(publication_id, str):
            publication_groups[publication_id].append(event)
            sequence_key = (publication_id, event.get("event_sequence"))
            if sequence_key in publication_sequences:
                errors.append(
                    "publication-event.event_sequence: duplicate "
                    f"{event.get('event_sequence')} for {publication_id}"
                )
            publication_sequences.add(sequence_key)
        require_reference(
            event.get("account_id"),
            account_index,
            "publication-event.account_id",
            errors,
            seen_refs,
            "account",
        )
        require_reference(
            event.get("content_id"),
            content_index,
            "publication-event.content_id",
            errors,
            seen_refs,
            "content",
        )
        require_time_order(
            event.get("occurred_at"),
            event.get("recorded_at"),
            "publication-event.recorded_at",
            errors,
        )
        supersedes = event.get("supersedes_event_id")
        if supersedes is not None:
            require_reference(
                supersedes,
                publication_event_index,
                "publication-event.supersedes_event_id",
                errors,
                seen_refs,
                "publication-event",
            )

    published_at: dict[str, datetime] = {}
    for publication_id, group in publication_groups.items():
        records_share_field(group, "account_id", f"publication-event[{publication_id}]", errors)
        records_share_field(group, "content_id", f"publication-event[{publication_id}]", errors)
        records_share_field(group, "platform", f"publication-event[{publication_id}]", errors)
        sequenced_events = sorted(
            (
                (event.get("event_sequence"), parse_timestamp(event.get("occurred_at")))
                for event in group
                if isinstance(event.get("event_sequence"), int)
            ),
            key=lambda item: item[0],
        )
        previous_event_time: datetime | None = None
        for sequence, event_time in sequenced_events:
            if (
                previous_event_time is not None
                and event_time is not None
                and event_time < previous_event_time
            ):
                errors.append(
                    f"publication-event[{publication_id}].event_sequence: "
                    f"occurred_at moves backwards at sequence {sequence}"
                )
            if event_time is not None:
                previous_event_time = event_time
        published_times = [
            parse_timestamp(event.get("occurred_at"))
            for event in group
            if event.get("event_type") == "published"
        ]
        valid_published_times = [value for value in published_times if value is not None]
        if len(valid_published_times) > 1:
            errors.append(f"publication-event[{publication_id}]: multiple published events")
        if valid_published_times:
            published_at[publication_id] = min(valid_published_times)

    for topic in records.get("topic", []):
        require_references(
            topic.get("goal_ids", []),
            goal_index,
            "topic.goal_ids",
            errors,
            seen_refs,
            "operating-goal",
        )
        require_references(
            topic.get("target_account_ids", []),
            account_index,
            "topic.target_account_ids",
            errors,
            seen_refs,
            "account",
        )
        parent_topic_id = topic.get("parent_topic_id")
        if parent_topic_id is not None:
            require_reference(
                parent_topic_id,
                topic_index,
                "topic.parent_topic_id",
                errors,
                seen_refs,
                "topic",
            )
            if parent_topic_id == topic.get("topic_id"):
                errors.append(f"topic.parent_topic_id: self-reference {parent_topic_id}")

    snapshot_windows: set[tuple[str, str]] = set()
    for snapshot in records.get("performance-snapshot", []):
        publication_id = snapshot.get("publication_id")
        require_reference(
            publication_id,
            publication_groups,
            "performance-snapshot.publication_id",
            errors,
            seen_refs,
            "publication",
        )
        as_of, captured_at = require_time_order(
            snapshot.get("as_of"),
            snapshot.get("captured_at"),
            "performance-snapshot.captured_at",
            errors,
        )
        window_label = snapshot.get("window_label")
        if isinstance(publication_id, str) and isinstance(window_label, str):
            window_key = (publication_id, window_label)
            if window_label in {"early", "d7"} and window_key in snapshot_windows:
                errors.append(
                    f"performance-snapshot.window_label: duplicate {window_label} for {publication_id}"
                )
            snapshot_windows.add(window_key)
        publication_time = published_at.get(str(publication_id))
        if as_of is not None and publication_time is not None:
            elapsed_hours = (as_of - publication_time).total_seconds() / 3600
            if elapsed_hours < 0:
                errors.append("performance-snapshot.as_of: before the publication event")
            if window_label == "early" and not 48 <= elapsed_hours <= 72:
                errors.append(
                    "performance-snapshot.window_label: early must be 48-72 hours after publication"
                )
            if window_label == "d7" and not 156 <= elapsed_hours <= 180:
                errors.append(
                    "performance-snapshot.window_label: d7 must be 156-180 hours after publication"
                )
        metric_keys = [metric.get("metric_key") for metric in snapshot.get("metrics", [])]
        for duplicate in duplicate_values(metric_keys):
            errors.append(f"performance-snapshot.metrics.metric_key: duplicate {duplicate}")

    for interaction in records.get("interaction-event", []):
        require_reference(
            interaction.get("publication_id"),
            publication_groups,
            "interaction-event.publication_id",
            errors,
            seen_refs,
            "publication",
        )
        require_reference(
            interaction.get("account_id"),
            account_index,
            "interaction-event.account_id",
            errors,
            seen_refs,
            "account",
        )
        publication_group = publication_groups.get(interaction.get("publication_id"), [])
        if publication_group and interaction.get("account_id") != publication_group[0].get("account_id"):
            errors.append("interaction-event.account_id: does not match publication account")
        require_time_order(
            interaction.get("occurred_at"),
            interaction.get("recorded_at"),
            "interaction-event.recorded_at",
            errors,
        )
        if interaction.get("lead_promotion_status") == "promoted" and not interaction.get(
            "evidence_refs"
        ):
            errors.append(
                "interaction-event.evidence_refs: promoted interaction requires evidence"
            )

    lead_dedupe_keys: list[Any] = []
    lead_source_ids: list[Any] = []
    for lead in records.get("lead-event", []):
        lead_dedupe_keys.append(lead.get("dedupe_key"))
        lead_source_ids.append(lead.get("source_interaction_event_id"))
        interaction = interaction_index.get(lead.get("source_interaction_event_id"))
        require_reference(
            lead.get("source_interaction_event_id"),
            interaction_index,
            "lead-event.source_interaction_event_id",
            errors,
            seen_refs,
            "interaction",
        )
        require_reference(
            lead.get("source_publication_id"),
            publication_groups,
            "lead-event.source_publication_id",
            errors,
            seen_refs,
            "publication",
        )
        require_reference(
            lead.get("account_id"),
            account_index,
            "lead-event.account_id",
            errors,
            seen_refs,
            "account",
        )
        if interaction is not None:
            if interaction.get("lead_promotion_status") != "promoted":
                errors.append("lead-event.source_interaction_event_id: source was not promoted")
            if lead.get("source_publication_id") != interaction.get("publication_id"):
                errors.append("lead-event.source_publication_id: does not match source interaction")
            if lead.get("account_id") != interaction.get("account_id"):
                errors.append("lead-event.account_id: does not match source interaction")
            source_evidence = {
                value
                for value in interaction.get("evidence_refs", [])
                if isinstance(value, str)
            }
            review_evidence = {
                value
                for value in lead.get("review", {}).get("evidence_refs", [])
                if isinstance(value, str)
            }
            if not source_evidence:
                errors.append("lead-event.source_interaction_event_id: source has no evidence")
            elif not source_evidence.intersection(review_evidence):
                errors.append(
                    "lead-event.review.evidence_refs: must preserve source interaction evidence"
                )
        attribution = lead.get("attribution", {})
        window_start, window_end = require_time_order(
            attribution.get("window_start"),
            attribution.get("window_end"),
            "lead-event.attribution",
            errors,
        )
        interaction_time = parse_timestamp(interaction.get("occurred_at")) if interaction else None
        if (
            window_start is not None
            and window_end is not None
            and interaction_time is not None
            and not window_start <= interaction_time <= window_end
        ):
            errors.append("lead-event.attribution: source interaction is outside attribution window")
        review_time = parse_timestamp(lead.get("review", {}).get("reviewed_at"))
        created_time = parse_timestamp(lead.get("created_at"))
        if interaction_time is not None and review_time is not None and review_time < interaction_time:
            errors.append("lead-event.review.reviewed_at: before source interaction")
        if review_time is not None and created_time is not None and created_time < review_time:
            errors.append("lead-event.created_at: before human review")
        handoff = lead.get("handoff", {})
        if handoff.get("status") == "completed":
            receipt_ref = handoff.get("receipt_ref")
            if not isinstance(receipt_ref, str) or not receipt_ref.strip():
                errors.append(
                    "lead-event.handoff.receipt_ref: completed handoff requires receipt"
                )
    for duplicate in duplicate_values(lead_dedupe_keys):
        errors.append(f"lead-event.dedupe_key: duplicate {duplicate}")
    for duplicate in duplicate_values(lead_source_ids):
        errors.append(f"lead-event.source_interaction_event_id: duplicate promotion {duplicate}")
    promoted_interactions = {
        interaction_id
        for interaction_id, interaction in interaction_index.items()
        if interaction.get("lead_promotion_status") == "promoted"
    }
    missing_promotions = promoted_interactions - set(value for value in lead_source_ids if value)
    for interaction_id in sorted(missing_promotions):
        errors.append(f"interaction-event.lead_promotion_status: promoted without lead {interaction_id}")
    lead_counts_by_interaction = Counter(value for value in lead_source_ids if value)
    for interaction_id in sorted(promoted_interactions):
        if lead_counts_by_interaction[interaction_id] != 1:
            errors.append(
                "interaction-event.lead_promotion_status: promoted interaction must resolve "
                f"exactly one lead {interaction_id}"
            )

    for experiment in records.get("experiment-run", []):
        require_reference(
            experiment.get("account_id"),
            account_index,
            "experiment-run.account_id",
            errors,
            seen_refs,
            "account",
        )
        require_references(
            experiment.get("topic_ids", []),
            topic_index,
            "experiment-run.topic_ids",
            errors,
            seen_refs,
            "topic",
        )
        require_references(
            experiment.get("content_ids", []),
            content_index,
            "experiment-run.content_ids",
            errors,
            seen_refs,
            "content",
        )
        top_publication_ids = experiment.get("publication_ids", [])
        require_references(
            top_publication_ids,
            publication_groups,
            "experiment-run.publication_ids",
            errors,
            seen_refs,
            "publication",
        )
        variant_ids = [variant.get("variant_id") for variant in experiment.get("variants", [])]
        for duplicate in duplicate_values(variant_ids):
            errors.append(f"experiment-run.variants.variant_id: duplicate {duplicate}")
        variant_publication_ids: list[Any] = []
        for variant in experiment.get("variants", []):
            variant_publication_ids.extend(variant.get("publication_ids", []))
            require_references(
                variant.get("publication_ids", []),
                publication_groups,
                f"experiment-run.variants[{variant.get('variant_id')}].publication_ids",
                errors,
                seen_refs,
                "publication",
            )
        for duplicate in duplicate_values(variant_publication_ids):
            errors.append(f"experiment-run.variants.publication_ids: assigned twice {duplicate}")
        if set(top_publication_ids) != set(variant_publication_ids):
            errors.append(
                "experiment-run.publication_ids: must equal the union of variant publication_ids"
            )
        for publication_id in top_publication_ids:
            publication_group = publication_groups.get(publication_id, [])
            if publication_group and publication_group[0].get("account_id") != experiment.get("account_id"):
                errors.append(f"experiment-run.publication_ids: account mismatch {publication_id}")
            if (
                publication_group
                and experiment.get("content_ids")
                and publication_group[0].get("content_id") not in experiment.get("content_ids", [])
            ):
                errors.append(f"experiment-run.publication_ids: content mismatch {publication_id}")
        registered_at = parse_timestamp(experiment.get("registered_at"))
        started_at = parse_timestamp(experiment.get("started_at"))
        completed_at = parse_timestamp(experiment.get("completed_at"))
        base_time = started_at or registered_at
        if registered_at is not None and started_at is not None and started_at < registered_at:
            errors.append("experiment-run.started_at: before registered_at")
        if started_at is not None and completed_at is not None and completed_at < started_at:
            errors.append("experiment-run.completed_at: before started_at")
        if experiment.get("state") in {"running", "completed", "stopped"} and started_at is None:
            errors.append("experiment-run.started_at: required after pre-registration")
        for publication_id in top_publication_ids:
            publication_time = published_at.get(publication_id)
            if (
                publication_time is not None
                and registered_at is not None
                and publication_time < registered_at
            ):
                errors.append(
                    f"experiment-run.publication_ids: published before registration {publication_id}"
                )
            if (
                publication_time is not None
                and started_at is not None
                and publication_time < started_at
            ):
                errors.append(
                    f"experiment-run.publication_ids: published before test start {publication_id}"
                )
        evaluate_after = parse_timestamp(experiment.get("observation_window", {}).get("evaluate_after"))
        minimum_hours = experiment.get("observation_window", {}).get("minimum_hours")
        if base_time is not None and evaluate_after is not None and isinstance(minimum_hours, int):
            if evaluate_after < base_time + timedelta(hours=minimum_hours):
                errors.append(
                    "experiment-run.observation_window: evaluate_after is earlier than minimum_hours"
                )
        conclusion_status = experiment.get("conclusion", {}).get("status")
        if (
            conclusion_status in {"supports", "does-not-support"}
            and evaluate_after is not None
            and completed_at is not None
            and completed_at < evaluate_after
        ):
            errors.append("experiment-run.conclusion: directional conclusion before window ended")
        if (
            experiment.get("state") == "completed"
            and evaluate_after is not None
            and completed_at is not None
            and completed_at < evaluate_after
        ):
            errors.append("experiment-run.completed_at: completed before observation window ended")

    for diagnostic in records.get("diagnostic-run", []):
        require_reference(
            diagnostic.get("account_id"),
            account_index,
            "diagnostic-run.account_id",
            errors,
            seen_refs,
            "account",
        )
        publication_ids = diagnostic.get("publication_ids", [])
        require_references(
            publication_ids,
            publication_groups,
            "diagnostic-run.publication_ids",
            errors,
            seen_refs,
            "publication",
        )
        window_start, window_end = require_time_order(
            diagnostic.get("input_window", {}).get("start"),
            diagnostic.get("input_window", {}).get("end"),
            "diagnostic-run.input_window",
            errors,
            allow_equal=False,
        )
        run_at = parse_timestamp(diagnostic.get("run_at"))
        if window_end is not None and run_at is not None and run_at < window_end:
            errors.append("diagnostic-run.run_at: before input_window.end")
        if (
            isinstance(diagnostic.get("sample_size"), int)
            and diagnostic.get("sample_size") != len(publication_ids)
        ):
            errors.append("diagnostic-run.sample_size: must equal publication_ids count")
        if diagnostic.get("baseline", {}).get("type") == "peer-cohort" and diagnostic.get(
            "baseline", {}
        ).get("cohort_size") is None:
            errors.append("diagnostic-run.baseline.cohort_size: required for peer-cohort")
        for publication_id in publication_ids:
            group = publication_groups.get(publication_id, [])
            if group and group[0].get("account_id") != diagnostic.get("account_id"):
                errors.append(f"diagnostic-run.publication_ids: account mismatch {publication_id}")
            publication_time = published_at.get(publication_id)
            if (
                publication_time is not None
                and window_start is not None
                and window_end is not None
                and not window_start <= publication_time <= window_end
            ):
                errors.append(f"diagnostic-run.publication_ids: outside input_window {publication_id}")
        for finding in diagnostic.get("findings", []):
            if finding.get("confidence") in {"medium", "high"} and not finding.get("evidence_refs"):
                errors.append("diagnostic-run.findings: medium/high confidence requires evidence_refs")
        validate_human_review_receipt(
            diagnostic,
            "report_state",
            "diagnostic-run",
            errors,
            earliest_review_value=diagnostic.get("run_at"),
        )

    for resource in records.get("resource-ledger-event", []):
        require_reference(
            resource.get("account_id"),
            account_index,
            "resource-ledger-event.account_id",
            errors,
            seen_refs,
            "account",
        )
        content_id = resource.get("content_id")
        publication_id = resource.get("publication_id")
        if content_id is not None:
            require_reference(
                content_id,
                content_index,
                "resource-ledger-event.content_id",
                errors,
                seen_refs,
                "content",
            )
        if publication_id is not None:
            require_reference(
                publication_id,
                publication_groups,
                "resource-ledger-event.publication_id",
                errors,
                seen_refs,
                "publication",
            )
            group = publication_groups.get(publication_id, [])
            if group and group[0].get("account_id") != resource.get("account_id"):
                errors.append("resource-ledger-event.account_id: does not match publication")
            if content_id is not None and group and group[0].get("content_id") != content_id:
                errors.append("resource-ledger-event.content_id: does not match publication")

    for revenue in records.get("revenue-attribution-event", []):
        require_reference(
            revenue.get("account_id"),
            account_index,
            "revenue-attribution-event.account_id",
            errors,
            seen_refs,
            "account",
        )
        require_references(
            revenue.get("publication_ids", []),
            publication_groups,
            "revenue-attribution-event.publication_ids",
            errors,
            seen_refs,
            "publication",
        )
        require_references(
            revenue.get("lead_event_ids", []),
            lead_index,
            "revenue-attribution-event.lead_event_ids",
            errors,
            seen_refs,
            "lead",
        )
        for lead_event_id in revenue.get("lead_event_ids", []):
            lead = lead_index.get(lead_event_id)
            if lead and lead.get("account_id") != revenue.get("account_id"):
                errors.append(
                    f"revenue-attribution-event.lead_event_ids: account mismatch {lead_event_id}"
                )
        occurred_at = parse_timestamp(revenue.get("occurred_at"))
        reviewed_at = parse_timestamp(revenue.get("review", {}).get("reviewed_at"))
        if occurred_at is not None and reviewed_at is not None and reviewed_at < occurred_at:
            errors.append("revenue-attribution-event.reviewed_at: before occurred_at")

    for continuity in records.get("account-continuity-plan", []):
        continuity_account_ids = [item.get("account_id") for item in continuity.get("accounts", [])]
        for duplicate in duplicate_values(continuity_account_ids):
            errors.append(f"account-continuity-plan.accounts.account_id: duplicate {duplicate}")
        require_references(
            continuity_account_ids,
            account_index,
            "account-continuity-plan.accounts.account_id",
            errors,
            seen_refs,
            "account",
        )
        recovery_order = continuity.get("recovery_order", [])
        for duplicate in duplicate_values(recovery_order):
            errors.append(f"account-continuity-plan.recovery_order: duplicate {duplicate}")
        if set(recovery_order) != set(value for value in continuity_account_ids if value):
            errors.append(
                "account-continuity-plan.recovery_order: must contain every plan account exactly once"
            )
        reviewed_at = parse_timestamp(continuity.get("reviewed_at"))
        last_verified_at = parse_timestamp(
            continuity.get("backup_state", {}).get("last_verified_at")
        )
        last_drill_at = parse_timestamp(continuity.get("drill", {}).get("last_drill_at"))
        next_due_at = parse_timestamp(continuity.get("drill", {}).get("next_due_at"))
        if (
            reviewed_at is not None
            and last_verified_at is not None
            and last_verified_at > reviewed_at
        ):
            errors.append(
                "account-continuity-plan.backup_state.last_verified_at: after reviewed_at"
            )
        if reviewed_at is not None and last_drill_at is not None and last_drill_at > reviewed_at:
            errors.append("account-continuity-plan.drill.last_drill_at: after reviewed_at")
        if last_drill_at is not None and next_due_at is not None and next_due_at <= last_drill_at:
            errors.append("account-continuity-plan.drill.next_due_at: not after last_drill_at")

    for security in records.get("account-security-event", []):
        require_reference(
            security.get("account_id"),
            account_index,
            "account-security-event.account_id",
            errors,
            seen_refs,
            "account",
        )
        require_time_order(
            security.get("occurred_at"),
            security.get("recorded_at"),
            "account-security-event.recorded_at",
            errors,
        )
        next_review_at = parse_timestamp(security.get("next_review_at"))
        recorded_at = parse_timestamp(security.get("recorded_at"))
        if (
            next_review_at is not None
            and recorded_at is not None
            and next_review_at <= recorded_at
        ):
            errors.append("account-security-event.next_review_at: not after recorded_at")

    review_target_indexes: dict[str, Any] = {
        "publication": publication_groups,
        "snapshot": snapshot_index,
        "interaction": interaction_index,
        "lead": lead_index,
        "experiment": experiment_index,
        "diagnostic": diagnostic_index,
        "resource": resource_index,
        "revenue": revenue_index,
    }
    structured_ref_indexes: dict[str, Any] = {
        "goal_": goal_index,
        "pub_": publication_groups,
        "snap_": snapshot_index,
        "int_": interaction_index,
        "lead_": lead_index,
        "exp_": experiment_index,
        "diag_": diagnostic_index,
        "res_": resource_index,
        "rev_": revenue_index,
    }
    for review in review_index.values():
        review_accounts = set(review.get("account_ids", []))
        require_references(
            review.get("account_ids", []),
            account_index,
            "operating-review.account_ids",
            errors,
            seen_refs,
            "account",
        )
        goal_reviews = review.get("goal_reviews", [])
        goal_review_ids = [
            item.get("goal_id") for item in goal_reviews if isinstance(item, dict)
        ]
        for duplicate in duplicate_values(goal_review_ids):
            errors.append(f"operating-review.goal_reviews.goal_id: duplicate {duplicate}")
        require_references(
            goal_review_ids,
            goal_index,
            "operating-review.goal_reviews.goal_id",
            errors,
            seen_refs,
            "operating-goal",
        )
        require_time_order(
            review.get("period", {}).get("start"),
            review.get("period", {}).get("end"),
            "operating-review.period",
            errors,
            allow_equal=False,
        )
        validate_human_review_receipt(
            review,
            "review_state",
            "operating-review",
            errors,
            earliest_review_value=review.get("created_at"),
        )
        input_refs = review.get("input_refs", {})
        review_input_ids: set[str] = {
            value for value in goal_review_ids if isinstance(value, str)
        }
        for field, target_kind in REVIEW_REF_SPECS.items():
            values = input_refs.get(field, [])
            review_input_ids.update(str(value) for value in values)
            require_references(
                values,
                review_target_indexes[target_kind],
                f"operating-review.input_refs.{field}",
                errors,
                seen_refs,
                target_kind,
            )

        referenced_objects: list[dict[str, Any]] = []
        for publication_id in input_refs.get("publication_ids", []):
            referenced_objects.extend(publication_groups.get(publication_id, []))
        for field, index in (
            ("interaction_event_ids", interaction_index),
            ("lead_event_ids", lead_index),
            ("experiment_run_ids", experiment_index),
            ("diagnostic_run_ids", diagnostic_index),
            ("resource_event_ids", resource_index),
            ("revenue_event_ids", revenue_index),
        ):
            referenced_objects.extend(
                index[value] for value in input_refs.get(field, []) if value in index
            )
        for snapshot_id in input_refs.get("snapshot_ids", []):
            snapshot = snapshot_index.get(snapshot_id)
            if snapshot is not None:
                group = publication_groups.get(snapshot.get("publication_id"), [])
                referenced_objects.extend(group)
        for referenced in referenced_objects:
            account_id = referenced.get("account_id")
            if account_id is not None and account_id not in review_accounts:
                errors.append(
                    f"operating-review.account_ids: missing account for referenced object {account_id}"
                )

        layer_names = [item.get("layer") for item in review.get("layer_summaries", [])]
        for duplicate in duplicate_values(layer_names):
            errors.append(f"operating-review.layer_summaries.layer: duplicate {duplicate}")
        if set(layer_names) != SIX_SIGNAL_LAYERS:
            missing = sorted(SIX_SIGNAL_LAYERS - set(layer_names))
            unexpected = sorted(set(layer_names) - SIX_SIGNAL_LAYERS, key=str)
            errors.append(
                "operating-review.layer_summaries.layer: must contain each of six layers once; "
                f"missing={missing}, unexpected={unexpected}"
            )

        def check_review_evidence(evidence_refs: Any, label: str) -> None:
            if not isinstance(evidence_refs, list):
                return
            for evidence_ref in evidence_refs:
                if not isinstance(evidence_ref, str):
                    continue
                for prefix, index in structured_ref_indexes.items():
                    if evidence_ref.startswith(prefix):
                        if evidence_ref not in index:
                            errors.append(f"{label}: unresolved structured ref {evidence_ref}")
                        elif evidence_ref not in review_input_ids:
                            errors.append(f"{label}: ref not declared in input_refs {evidence_ref}")
                        break

        review_period_start = parse_timestamp(review.get("period", {}).get("start"))
        review_period_end = parse_timestamp(review.get("period", {}).get("end"))
        for goal_review in goal_reviews:
            if not isinstance(goal_review, dict):
                continue
            goal_id = goal_review.get("goal_id")
            goal = goal_index.get(goal_id)
            if goal is None:
                continue
            missing_accounts = set(goal.get("account_ids", [])) - review_accounts
            if missing_accounts:
                errors.append(
                    "operating-review.account_ids: missing goal accounts "
                    f"for {goal_id}: {sorted(missing_accounts)}"
                )
            goal_start = parse_timestamp(goal.get("period", {}).get("start"))
            goal_end = parse_timestamp(goal.get("period", {}).get("end"))
            if (
                review_period_start is not None
                and goal_start is not None
                and review_period_start < goal_start
            ):
                errors.append(f"operating-review.goal_reviews[{goal_id}]: review starts before goal")
            if (
                review_period_end is not None
                and goal_end is not None
                and review_period_end > goal_end
            ):
                errors.append(f"operating-review.goal_reviews[{goal_id}]: review ends after goal")

            expected_criteria = {
                item.get("criterion_id")
                for item in goal.get("success_criteria", [])
                if isinstance(item, dict)
            }
            criterion_results = goal_review.get("criterion_results", [])
            actual_criteria = [
                item.get("criterion_id")
                for item in criterion_results
                if isinstance(item, dict)
            ]
            for duplicate in duplicate_values(actual_criteria):
                errors.append(
                    f"operating-review.goal_reviews[{goal_id}].criterion_id: duplicate {duplicate}"
                )
            if set(actual_criteria) != expected_criteria:
                errors.append(
                    f"operating-review.goal_reviews[{goal_id}].criterion_results: "
                    f"must cover goal criteria exactly; expected={sorted(expected_criteria)}, "
                    f"actual={sorted(set(actual_criteria), key=str)}"
                )

            criterion_statuses = [
                item.get("status") for item in criterion_results if isinstance(item, dict)
            ]
            goal_status = goal_review.get("status")
            if goal_status == "met" and any(status != "met" for status in criterion_statuses):
                errors.append(
                    f"operating-review.goal_reviews[{goal_id}].status: met requires every criterion met"
                )
            if goal_status == "not-met" and "not-met" not in criterion_statuses:
                errors.append(
                    f"operating-review.goal_reviews[{goal_id}].status: not-met requires a not-met criterion"
                )
            if (
                goal_status == "insufficient-evidence"
                and "insufficient-evidence" not in criterion_statuses
            ):
                errors.append(
                    f"operating-review.goal_reviews[{goal_id}].status: "
                    "insufficient-evidence requires an insufficient criterion"
                )
            if goal_status == "not-due" and any(
                status != "not-due" for status in criterion_statuses
            ):
                errors.append(
                    f"operating-review.goal_reviews[{goal_id}].status: "
                    "not-due requires every criterion not-due"
                )
            if goal_status in {"progressing", "met", "not-met"} and not goal_review.get(
                "evidence_refs"
            ):
                errors.append(
                    f"operating-review.goal_reviews[{goal_id}].evidence_refs: "
                    f"required for {goal_status}"
                )
            for criterion_result in criterion_results:
                if not isinstance(criterion_result, dict):
                    continue
                if criterion_result.get("status") in {"met", "not-met"} and not criterion_result.get(
                    "evidence_refs"
                ):
                    errors.append(
                        f"operating-review.goal_reviews[{goal_id}].criterion_results"
                        f"[{criterion_result.get('criterion_id')}].evidence_refs: required for "
                        f"{criterion_result.get('status')}"
                    )
                check_review_evidence(
                    criterion_result.get("evidence_refs", []),
                    f"operating-review.goal_reviews[{goal_id}].criterion_results"
                    f"[{criterion_result.get('criterion_id')}].evidence_refs",
                )
            check_review_evidence(
                goal_review.get("evidence_refs", []),
                f"operating-review.goal_reviews[{goal_id}].evidence_refs",
            )

            if goal_status == "not-met":
                structured_refs = [
                    ref
                    for ref in goal_review.get("evidence_refs", [])
                    if isinstance(ref, str)
                ]
                non_signal_only = bool(structured_refs)
                for ref in structured_refs:
                    if ref.startswith("snap_"):
                        snapshot = snapshot_index.get(ref)
                        if snapshot is not None and snapshot.get("data_completeness") != "unavailable":
                            non_signal_only = False
                    elif ref.startswith("int_"):
                        interaction = interaction_index.get(ref)
                        if interaction is not None and interaction.get("source_type") != "no-signal":
                            non_signal_only = False
                    else:
                        non_signal_only = False
                if non_signal_only:
                    errors.append(
                        f"operating-review.goal_reviews[{goal_id}].status: "
                        "no-signal or unavailable evidence cannot prove not-met"
                    )

        for layer in review.get("layer_summaries", []):
            check_review_evidence(
                layer.get("evidence_refs", []),
                f"operating-review.layer_summaries[{layer.get('layer')}].evidence_refs",
            )
        for decision in review.get("decisions", []):
            check_review_evidence(
                decision.get("evidence_refs", []),
                f"operating-review.decisions[{decision.get('scope')}].evidence_refs",
            )

        referenced_resources = [
            resource_index[value]
            for value in input_refs.get("resource_event_ids", [])
            if value in resource_index
        ]
        expected_resource_summary = {
            "human_time_hours": 0.0,
            "tool_cost": 0.0,
            "external_cost": 0.0,
            "paid_distribution_cost": 0.0,
        }
        resource_cost_fields = {
            "tool-subscription": "tool_cost",
            "external-service": "external_cost",
            "paid-distribution": "paid_distribution_cost",
        }
        currencies: set[str] = set()
        for resource in referenced_resources:
            quantity = resource.get("quantity", {})
            if resource.get("resource_type") == "human-time":
                if quantity.get("unit") != "hours":
                    errors.append(
                        "operating-review.resource_summary: human-time input is not measured in hours"
                    )
                elif isinstance(quantity.get("value"), (int, float)):
                    expected_resource_summary["human_time_hours"] += float(quantity["value"])
            cost = resource.get("cost", {})
            cost_field = resource_cost_fields.get(resource.get("resource_type"))
            if cost_field and isinstance(cost.get("amount"), (int, float)):
                expected_resource_summary[cost_field] += float(cost["amount"])
            if isinstance(cost.get("currency"), str):
                currencies.add(cost["currency"])
        actual_resource_summary = review.get("resource_summary", {})
        for field, expected in expected_resource_summary.items():
            actual = actual_resource_summary.get(field)
            if isinstance(actual, (int, float)) and abs(float(actual) - expected) > 1e-9:
                errors.append(
                    f"operating-review.resource_summary.{field}: {actual} does not match {expected:g}"
                )
        if len(currencies) > 1:
            errors.append("operating-review.resource_summary.currency: mixed input currencies")
        elif currencies and actual_resource_summary.get("currency") not in currencies:
            errors.append("operating-review.resource_summary.currency: does not match resource events")

        referenced_revenue = [
            revenue_index[value]
            for value in input_refs.get("revenue_event_ids", [])
            if value in revenue_index
        ]
        expected_revenue_counts = Counter(
            item.get("attribution_type", "unknown") for item in referenced_revenue
        )
        actual_revenue_summary = review.get("revenue_summary", {})
        for attribution_type, field in (
            ("direct", "direct_count"),
            ("assisted", "assisted_count"),
            ("unknown", "unknown_count"),
        ):
            expected = expected_revenue_counts[attribution_type]
            if actual_revenue_summary.get(field) != expected:
                errors.append(
                    f"operating-review.revenue_summary.{field}: "
                    f"{actual_revenue_summary.get(field)} does not match {expected}"
                )

        business_layers = [
            layer for layer in review.get("layer_summaries", []) if layer.get("layer") == "business"
        ]
        if business_layers:
            business_status = business_layers[0].get("status")
            has_business_input = bool(
                input_refs.get("lead_event_ids") or input_refs.get("revenue_event_ids")
            )
            if has_business_input and business_status != "observed":
                errors.append(
                    "operating-review.layer_summaries[business]: confirmed business input must be observed"
                )
            if not has_business_input and business_status == "observed":
                errors.append(
                    "operating-review.layer_summaries[business]: observed without lead or revenue input"
                )

        require_references(
            review.get("next_experiment_ids", []),
            experiment_index,
            "operating-review.next_experiment_ids",
            errors,
            seen_refs,
            "experiment",
        )

    for item in content_items:
        refs = item.get("operating_refs", {})
        content_id = item.get("content_id")
        require_references(
            refs.get("account_ids", []),
            account_index,
            f"{content_id}.operating_refs.account_ids",
            errors,
            seen_refs,
            "account",
        )
        require_references(
            refs.get("topic_ids", []),
            topic_index,
            f"{content_id}.operating_refs.topic_ids",
            errors,
            seen_refs,
            "topic",
        )
        require_references(
            refs.get("publication_ids", []),
            publication_groups,
            f"{content_id}.operating_refs.publication_ids",
            errors,
            seen_refs,
            "publication",
        )
        require_references(
            refs.get("experiment_ids", []),
            experiment_index,
            f"{content_id}.operating_refs.experiment_ids",
            errors,
            seen_refs,
            "experiment",
        )

    return seen_refs


def main() -> int:
    args = parse_args()
    errors: list[str] = []
    canonical_root = args.contract_set_root.resolve()
    diagnostics_root = args.diagnostics_root or args.operations_root.parent / "diagnostics"
    if args.operations_root.resolve() != canonical_root / "operations":
        errors.append("--operations-root does not match the atomic contract-set root")
    if diagnostics_root.resolve() != canonical_root / "diagnostics":
        errors.append("--diagnostics-root does not match the atomic contract-set root")

    contract_set: dict[str, Any] | None = None
    try:
        contract_set = load_contract_set(canonical_root)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        errors.append(f"atomic operations contract-set invalid: {exc}")

    # The atomic set is the authority for every downstream schema and fixture.
    # Stop here on root/hash/version drift so later semantic checks cannot add
    # misleading reference errors against an empty or mixed contract set.
    if errors or contract_set is None:
        print("Content operations validation failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    schemas: dict[str, dict[str, Any]] = contract_set["schemas"]
    fixtures: dict[str, Any] = contract_set["fixtures"]
    schema_paths: dict[str, Path] = contract_set["schema_paths"]
    fixture_paths: dict[str, Path] = contract_set["fixture_paths"]

    for kind, schema in schemas.items():
        path = schema_paths[kind]
        try:
            Draft202012Validator.check_schema(schema)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            errors.append(f"{path}: invalid schema: {exc}")

    for kind, path in fixture_paths.items():
        if kind not in schemas:
            continue
        try:
            fixtures[kind] = load_json(path)
            errors.extend(validate_document(path, schemas[kind]))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"{path}: invalid fixture: {exc}")

    content_items: list[dict[str, Any]] = []
    for path in sorted(args.content_root.glob("*.json")):
        try:
            content_items.append(load_json(path))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"{path}: invalid content item: {exc}")
    if args.content_example.exists():
        content_items.append(load_json(args.content_example))

    validate_fixture_privacy(fixtures, errors)
    seen_refs = validate_cross_object_semantics(fixtures, content_items, errors)

    if errors:
        print("Content operations validation failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    print(
        f"Validated {len(schemas)} operating schemas, {len(fixtures)} fixtures, "
        f"{len({item.get('content_id') for item in content_items if item.get('content_id')})} "
        "content IDs, and "
        f"{sum(len(values) for values in seen_refs.values())} cross-object references."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
