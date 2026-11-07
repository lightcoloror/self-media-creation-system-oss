#!/usr/bin/env python3
"""Offline-only regression for the existing self-media operating contracts."""

from __future__ import annotations

import argparse
import copy
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker


WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
SYSTEM_ROOT = Path(__file__).resolve().parents[1]
OPERATIONS_ROOT = WORKSPACE_ROOT / "docs" / "content-creation-system" / "operations"
CONTENT_SCHEMA = WORKSPACE_ROOT / "docs" / "content-creation-system" / "content-item.schema.json"
REGRESSION_SCHEMA = SYSTEM_ROOT / "schemas" / "operations-regression.v1.schema.json"
DEFAULT_FIXTURE = SYSTEM_ROOT / "fixtures" / "operations-contract-regression.v1.synthetic.json"


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def schema_errors(document: Any, schema: dict[str, Any], label: str) -> list[str]:
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    return [
        f"{label}: {'.'.join(str(part) for part in error.path) or '$'}: {error.message}"
        for error in sorted(validator.iter_errors(document), key=lambda error: list(error.path))
    ]


def parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value)


def migrate_legacy_feedback(legacy: dict[str, Any]) -> dict[str, Any]:
    """Return an in-memory-only migration; it never writes back to source files."""
    signal_status = legacy["signal_status"]
    content_status = {
        "not-observed": "not-observed",
        "no_signal": "content_no_signal",
        "observed": "observed",
    }[signal_status]
    return {
        "signal_status": signal_status,
        "platform_signals": copy.deepcopy(legacy["platform_signals"]),
        "business_signals": copy.deepcopy(legacy["business_signals"]),
        "qualitative_feedback": copy.deepcopy(legacy.get("qualitative_feedback", [])),
        "learning_decision": legacy["learning_decision"],
        "content_signal_status": content_status,
        "business_signal_status": "not-observed",
        "measurement_layers": {
            "admission": [],
            "attraction": [],
            "consumption": [],
            "value": [],
            "negative_feedback": [],
            "business": [],
        },
    }


def derive_customer_conclusions(_content_feedback: dict[str, Any]) -> list[str]:
    """Keep customer conclusions out of content-only evidence by design."""
    return []


def publication_lifecycle_errors(events: list[dict[str, Any]]) -> list[str]:
    """Validate append-only lifecycle order without coupling it to content draft status."""
    errors: list[str] = []
    event_ids = [event["event_id"] for event in events]
    if len(event_ids) != len(set(event_ids)):
        errors.append("publication lifecycle must not contain duplicate event_id values")

    transitions = {
        ("start", "prepared"): "prepared",
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
    state = "start"
    previous_event_id: str | None = None
    previous_occurred_at: datetime | None = None
    for index, event in enumerate(events):
        expected_supersedes = previous_event_id
        if event.get("supersedes_event_id") != expected_supersedes:
            errors.append(
                f"publication lifecycle event {index + 1} must supersede "
                f"{expected_supersedes or 'nothing'}"
            )
        occurred_at = parse_timestamp(event["occurred_at"])
        if previous_occurred_at is not None and occurred_at < previous_occurred_at:
            errors.append("publication lifecycle occurred_at values must be ordered")
        transition = (state, event["event_type"])
        if transition not in transitions:
            errors.append(f"invalid publication lifecycle transition: {state} -> {event['event_type']}")
        else:
            state = transitions[transition]
        previous_event_id = event["event_id"]
        previous_occurred_at = occurred_at
    return errors


def contract_errors(bundle: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    regression_schema = load_json(REGRESSION_SCHEMA)
    content_schema = load_json(CONTENT_SCHEMA)
    operating_schemas = {
        "account": load_json(OPERATIONS_ROOT / "account.schema.json"),
        "topic": load_json(OPERATIONS_ROOT / "topic.schema.json"),
        "publication-event": load_json(OPERATIONS_ROOT / "publication-event.schema.json"),
        "performance-snapshot": load_json(OPERATIONS_ROOT / "performance-snapshot.schema.json"),
    }

    for name, schema in {"regression": regression_schema, "content-item": content_schema, **operating_schemas}.items():
        try:
            Draft202012Validator.check_schema(schema)
        except Exception as exc:  # jsonschema exposes multiple SchemaError subclasses
            errors.append(f"{name}: invalid schema: {exc}")

    errors.extend(schema_errors(bundle, regression_schema, "fixture"))
    if errors:
        return errors

    errors.extend(schema_errors(bundle["account"], operating_schemas["account"], "account"))
    errors.extend(schema_errors(bundle["topic"], operating_schemas["topic"], "topic"))
    errors.extend(schema_errors(bundle["content_item"], content_schema, "content_item"))
    for index, event in enumerate(bundle["publication_events"]):
        errors.extend(schema_errors(event, operating_schemas["publication-event"], f"publication_events[{index}]"))
    for index, snapshot in enumerate(bundle["performance_snapshots"]):
        errors.extend(schema_errors(snapshot, operating_schemas["performance-snapshot"], f"performance_snapshots[{index}]"))
    if errors:
        return errors

    account_id = bundle["account"]["account_id"]
    topic_id = bundle["topic"]["topic_id"]
    content = bundle["content_item"]
    refs = content["operating_refs"]
    if refs.get("account_ids") != [account_id]:
        errors.append("content_item.operating_refs.account_ids must resolve exactly to fixture account")
    if refs.get("topic_ids") != [topic_id]:
        errors.append("content_item.operating_refs.topic_ids must resolve exactly to fixture topic")
    if bundle["topic"].get("target_account_ids") != [account_id]:
        errors.append("topic.target_account_ids must resolve exactly to fixture account")

    events = bundle["publication_events"]
    publication_ids = {event["publication_id"] for event in events}
    if len(publication_ids) != 1:
        errors.append("publication_events must describe exactly one publication lifecycle")
    publication_id = next(iter(publication_ids)) if publication_ids else ""
    if refs.get("publication_ids") != [publication_id]:
        errors.append("content_item.operating_refs.publication_ids must resolve exactly to fixture publication")
    if [event["event_sequence"] for event in events] != list(range(1, len(events) + 1)):
        errors.append("publication_events.event_sequence must be contiguous and ordered")
    errors.extend(publication_lifecycle_errors(events))
    if any(event["content_id"] != content["content_id"] for event in events):
        errors.append("publication_events.content_id must resolve to content_item")
    if any(event["account_id"] != account_id for event in events):
        errors.append("publication_events.account_id must resolve to account")

    published = next((event for event in events if event["event_type"] == "published"), None)
    if published is None:
        return errors + ["published event missing"]
    published_at = parse_timestamp(published["occurred_at"])
    snapshots = bundle["performance_snapshots"]
    labels = {snapshot["window_label"] for snapshot in snapshots}
    if not {"early", "d7"}.issubset(labels):
        errors.append("performance_snapshots must include early and d7 observations")
    for snapshot in snapshots:
        if snapshot["publication_id"] != publication_id:
            errors.append("performance_snapshot.publication_id must resolve to publication lifecycle")
            continue
        elapsed_hours = (parse_timestamp(snapshot["as_of"]) - published_at).total_seconds() / 3600
        if snapshot["window_label"] == "early" and not 48 <= elapsed_hours <= 72:
            errors.append(f"early snapshot must be 48-72h after publication, got {elapsed_hours:g}h")
        if snapshot["window_label"] == "d7" and not 156 <= elapsed_hours <= 180:
            errors.append(f"d7 snapshot must be roughly 7d after publication, got {elapsed_hours:g}h")

    expected_layers = {"admission", "attraction", "consumption", "value", "negative_feedback", "business"}
    actual_layers = {review["layer"] for review in bundle["reviews"]}
    if actual_layers != expected_layers or len(bundle["reviews"]) != len(expected_layers):
        errors.append("reviews must cover the six operating layers exactly once")
    for review in bundle["reviews"]:
        if review["signal_status"] == "content_no_signal" and review["signal_domain"] != "content":
            errors.append("content_no_signal must stay in the content signal domain")
        if review["signal_status"] == "business_no_signal" and review["signal_domain"] != "business":
            errors.append("business_no_signal must stay in the business signal domain")

    feedback = content["feedback"]
    if feedback.get("content_signal_status") == "content_no_signal":
        if derive_customer_conclusions(feedback):
            errors.append("content_no_signal must not create a customer negative conclusion")
        if feedback.get("business_signal_status") not in {"not-observed", "customer_no_response_observed", "observed"}:
            errors.append("business signal status must remain independently classified")

    migrated = migrate_legacy_feedback(bundle["legacy_feedback"])
    migrated_content = copy.deepcopy(content)
    migrated_content["feedback"] = migrated
    errors.extend(schema_errors(migrated_content, content_schema, "legacy_migration.content_item"))
    if migrated["content_signal_status"] != "content_no_signal":
        errors.append("legacy no_signal must migrate to content_no_signal")
    if migrated["business_signal_status"] != "not-observed":
        errors.append("legacy content signal must not fabricate a business conclusion")
    return errors


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    bundle = load_json(args.fixture)
    errors = contract_errors(bundle)
    if errors:
        print("Operations contract regression failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    feedback = bundle["content_item"]["feedback"]
    print(
        "PASS: synthetic lifecycle, 48-72h and d7 snapshots, six-layer review, "
        f"content={feedback['content_signal_status']}, "
        f"business={feedback['business_signal_status']}, "
        "customer-negative-conclusions=0."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
