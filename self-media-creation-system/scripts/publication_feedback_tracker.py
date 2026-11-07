#!/usr/bin/env python3
"""Build and validate a manual-publication feedback tracking pack.

The adapter is deliberately local and synthetic-only.  It converts a minimal
manual entry into the existing account/topic/content-item/publication-event/
performance-snapshot contracts and an existing review-packet.v1 compatible
human-review intake.  It never opens a platform, calls an API, publishes,
contacts anyone, or writes CRM data.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = ROOT.parent
OPERATIONS_ROOT = WORKSPACE_ROOT / "docs" / "content-creation-system" / "operations"
ACCOUNT_SCHEMA = OPERATIONS_ROOT / "account.schema.json"
TOPIC_SCHEMA = OPERATIONS_ROOT / "topic.schema.json"
PUBLICATION_SCHEMA = OPERATIONS_ROOT / "publication-event.schema.json"
SNAPSHOT_SCHEMA = OPERATIONS_ROOT / "performance-snapshot.schema.json"
CONTENT_SCHEMA = WORKSPACE_ROOT / "docs" / "content-creation-system" / "content-item.schema.json"
ATTENTION_SCHEMA = ROOT / "schemas" / "review-intake.v0.2.schema.json"
DEFAULT_INPUT = ROOT / "templates" / "manual-publication-feedback-input.v1.synthetic.json"
DEFAULT_OUTPUT = ROOT / "fixtures" / "manual-publication-feedback-v1"
DEFAULT_NEGATIVE_CASES = ROOT / "fixtures" / "manual-publication-feedback-v1.negative-cases.json"

CROCKFORD32 = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
WINDOW_BOUNDS_HOURS = {"early": (48.0, 72.0), "d7": (156.0, 180.0)}
LAYERS = (
    "admission",
    "attraction",
    "consumption",
    "value",
    "negative_feedback",
    "business",
)
CONTENT_METRIC_LAYERS = {
    "admission.status": "admission",
    "impressions": "attraction",
    "views": "attraction",
    "reach": "attraction",
    "clicks": "attraction",
    "cover_click_rate": "attraction",
    "watch_time": "consumption",
    "average_watch_time": "consumption",
    "average_play_progress": "consumption",
    "completion_rate": "consumption",
    "retention_2s_rate": "consumption",
    "bounce_2s_rate": "consumption",
    "bounce_3s_rate": "consumption",
    "retention_3s_rate": "consumption",
    "retention_5s_rate": "consumption",
    "retention_10s_rate": "consumption",
    "major_dropoff_second": "consumption",
    "read_depth": "consumption",
    "likes": "value",
    "saves": "value",
    "shares": "value",
    "private_forwards": "value",
    "comments": "value",
    "danmaku": "value",
    "recommendations": "value",
    "meaningful_comments": "value",
    "follows": "value",
    "profile_visits": "value",
    "attributed_new_followers": "value",
    "net_follower_change": "value",
    "follows_per_1000_views": "value",
    "profile_visit_rate": "value",
    "profile_follow_conversion_rate": "value",
    "coins": "value",
    "hides": "negative_feedback",
    "reports": "negative_feedback",
    "unfollows": "negative_feedback",
    "negative_feedback_count": "negative_feedback",
}
DERIVED_CONTENT_METRICS = {
    "follows_per_1000_views": ("attributed_new_followers", "views", 1000.0, "other"),
    "profile_visit_rate": ("profile_visits", "views", 100.0, "percent"),
    "profile_follow_conversion_rate": (
        "attributed_new_followers",
        "profile_visits",
        100.0,
        "percent",
    ),
}
PERCENT_METRICS = {
    "cover_click_rate",
    "average_play_progress",
    "completion_rate",
    "retention_2s_rate",
    "bounce_2s_rate",
    "bounce_3s_rate",
    "retention_3s_rate",
    "retention_5s_rate",
    "retention_10s_rate",
    "profile_visit_rate",
    "profile_follow_conversion_rate",
}
COUNT_METRICS = {
    "impressions",
    "views",
    "reach",
    "clicks",
    "likes",
    "saves",
    "shares",
    "private_forwards",
    "comments",
    "danmaku",
    "recommendations",
    "meaningful_comments",
    "follows",
    "profile_visits",
    "attributed_new_followers",
    "net_follower_change",
    "coins",
    "hides",
    "reports",
    "unfollows",
    "negative_feedback_count",
}
SIGNED_COUNT_METRICS = {"net_follower_change"}
QUALIFYING_BUSINESS_EVENTS = {
    "continued_consultation",
    "necessary_documents_provided",
    "next_step_booked",
}
FORBIDDEN_INPUT_KEYS = {
    "raw_comment",
    "raw_comments",
    "comment_text",
    "customer_name",
    "display_name",
    "phone",
    "email",
    "canonical_url",
    "platform_content_id",
    "tracking_url",
    "token",
    "cookie",
    "secret",
    "crm_status",
    "customer_conclusion",
}


class TrackerError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise TrackerError("artifact_missing", str(path)) from error
    except json.JSONDecodeError as error:
        raise TrackerError("invalid_json", f"{path}: {error}") from error
    if not isinstance(value, dict):
        raise TrackerError("invalid_json_root", f"{path} must contain an object")
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


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256_bytes(payload)


def stable_operation_id(prefix: str, seed: str) -> str:
    value = int.from_bytes(hashlib.sha256(seed.encode("utf-8")).digest(), "big") >> 126
    chars: list[str] = []
    for _ in range(26):
        chars.append(CROCKFORD32[value & 31])
        value >>= 5
    return f"{prefix}_{''.join(reversed(chars))}"


def stable_short_id(prefix: str, seed: str, length: int = 20) -> str:
    return f"{prefix}-{hashlib.sha256(seed.encode('utf-8')).hexdigest()[:length]}"


def parse_time(value: Any, label: str) -> datetime:
    if not isinstance(value, str):
        raise TrackerError("invalid_datetime", f"{label} must be an ISO-8601 string")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise TrackerError("invalid_datetime", f"{label}: {value}") from error
    if parsed.tzinfo is None:
        raise TrackerError("invalid_datetime", f"{label} must include a timezone offset")
    return parsed


def require_exact_keys(value: Any, required: set[str], label: str) -> None:
    if not isinstance(value, dict):
        raise TrackerError("invalid_shape", f"{label} must be an object")
    actual = set(value)
    missing = required - actual
    extra = actual - required
    if missing:
        raise TrackerError("missing_required_field", f"{label} missing: {sorted(missing)}")
    if extra:
        raise TrackerError("unexpected_field", f"{label} extra: {sorted(extra)}")


def reject_sensitive_keys(value: Any, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key.lower() in FORBIDDEN_INPUT_KEYS:
                raise TrackerError("privacy_boundary_violation", f"forbidden field {path}.{key}")
            reject_sensitive_keys(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            reject_sensitive_keys(child, f"{path}[{index}]")
    elif isinstance(value, str):
        lowered = value.lower()
        if "utm_" in lowered or "access_token=" in lowered or "cookie=" in lowered:
            raise TrackerError("privacy_boundary_violation", f"tracking or credential text at {path}")


def resolve_repo_ref(ref: str) -> Path:
    if not isinstance(ref, str) or not ref:
        raise TrackerError("invalid_artifact_ref", "source artifact ref must be a non-empty string")
    candidate = (ROOT / ref).resolve()
    try:
        candidate.relative_to(ROOT.resolve())
    except ValueError as error:
        raise TrackerError("invalid_artifact_ref", f"ref leaves repository: {ref}") from error
    if not candidate.is_file():
        raise TrackerError("artifact_missing", ref)
    return candidate


def schema_errors(instance: Any, schema_path: Path, label: str) -> list[str]:
    schema = load_json(schema_path)
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    return [
        f"{label}: {'.'.join(str(part) for part in error.absolute_path) or '$'}: {error.message}"
        for error in sorted(validator.iter_errors(instance), key=lambda item: [str(part) for part in item.absolute_path])
    ]


def validate_schema(instance: Any, schema_path: Path, label: str) -> None:
    errors = schema_errors(instance, schema_path, label)
    if errors:
        raise TrackerError("schema_validation_failed", errors[0])


def source_artifacts(entry: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    source = entry["source_objects"]
    resolved: dict[str, tuple[Path, dict[str, Any]]] = {}
    for name in ("account", "topic", "content_item"):
        path = resolve_repo_ref(source[f"{name}_ref"])
        observed = sha256_file(path)
        expected = source[f"{name}_sha256"]
        if observed != expected:
            raise TrackerError("stale_source_artifact", f"{name} expected {expected}, got {observed}")
        resolved[name] = (path, load_json(path))
    account = resolved["account"][1]
    topic = resolved["topic"][1]
    content = resolved["content_item"][1]
    validate_schema(account, ACCOUNT_SCHEMA, "source.account")
    validate_schema(topic, TOPIC_SCHEMA, "source.topic")
    validate_schema(content, CONTENT_SCHEMA, "source.content_item")
    if content.get("content_id") != entry["content_id"]:
        raise TrackerError("content_reference_drift", "manual entry content_id does not match source content-item")
    if account.get("account_id") not in content.get("operating_refs", {}).get("account_ids", []):
        raise TrackerError("account_reference_drift", "source content-item does not reference the account")
    if topic.get("topic_id") not in content.get("operating_refs", {}).get("topic_ids", []):
        raise TrackerError("topic_reference_drift", "source content-item does not reference the topic")
    if account.get("account_id") not in topic.get("target_account_ids", []):
        raise TrackerError("account_reference_drift", "source topic does not target the account")
    if entry["synthetic_only"] is True:
        if "synthetic-only" not in content.get("tags", []):
            raise TrackerError("synthetic_source_required", "content-item is not marked synthetic-only")
        if "synthetic" not in account.get("display_name", "").lower():
            raise TrackerError("synthetic_source_required", "account is not clearly synthetic")
    return account, topic, content


def validate_metric(metric: Any, label: str) -> None:
    require_exact_keys(metric, {"layer", "metric_key", "value", "unit"}, label)
    key = metric["metric_key"]
    layer = metric["layer"]
    if key not in CONTENT_METRIC_LAYERS or CONTENT_METRIC_LAYERS[key] != layer:
        raise TrackerError("metric_layer_mismatch", f"{key} cannot be assigned to {layer}")
    if layer == "business":
        raise TrackerError("signal_escalation", "platform metrics cannot enter the business layer")
    if key in DERIVED_CONTENT_METRICS:
        raise TrackerError("derived_metric_is_computed", f"{key} is computed from raw metrics")
    value = metric["value"]
    if value is not None and (not isinstance(value, (int, float)) or isinstance(value, bool)):
        raise TrackerError("invalid_metric", f"{label}.value must be null or a number")
    if value is not None and value < 0 and key not in SIGNED_COUNT_METRICS:
        raise TrackerError("invalid_metric", f"{label}.value must be non-negative for {key}")
    if metric["unit"] not in {"count", "ratio", "percent", "seconds", "currency", "other"}:
        raise TrackerError("invalid_metric", f"{label}.unit is invalid")
    if key in PERCENT_METRICS and metric["unit"] != "percent":
        raise TrackerError("metric_unit_mismatch", f"{key} must use percent")
    if value is not None and key in PERCENT_METRICS and value > 100:
        raise TrackerError("invalid_metric", f"{key} cannot exceed 100 percent")
    if key in COUNT_METRICS and metric["unit"] != "count":
        raise TrackerError("metric_unit_mismatch", f"{key} must use count")
    if value is not None and key in COUNT_METRICS and not float(value).is_integer():
        raise TrackerError("invalid_metric", f"{key} must be an integer count")


def validate_metric_set(metrics: list[dict[str, Any]], label: str) -> None:
    keys = [metric["metric_key"] for metric in metrics]
    if len(keys) != len(set(keys)):
        raise TrackerError("duplicate_metric", label)
    values = {metric["metric_key"]: metric["value"] for metric in metrics}
    retention = [values.get(key) for key in ("retention_2s_rate", "retention_3s_rate", "retention_5s_rate", "retention_10s_rate")]
    observed = [value for value in retention if value is not None]
    if len(observed) >= 2 and observed != sorted(observed, reverse=True):
        raise TrackerError("retention_order_invalid", "shorter-window retention cannot be below longer-window retention")


def derive_metrics(metrics: list[dict[str, Any]]) -> list[dict[str, Any]]:
    values = {metric["metric_key"]: metric["value"] for metric in metrics}
    derived: list[dict[str, Any]] = []
    for key, (numerator_key, denominator_key, multiplier, unit) in DERIVED_CONTENT_METRICS.items():
        numerator = values.get(numerator_key)
        denominator = values.get(denominator_key)
        if numerator is None or denominator is None or denominator <= 0:
            continue
        derived.append(
            {
                "metric_key": key,
                "value": round((numerator / denominator) * multiplier, 6),
                "unit": unit,
                "dimensions": {
                    "layer": CONTENT_METRIC_LAYERS[key],
                    "synthetic": True,
                    "derived": True,
                    "numerator": numerator_key,
                    "denominator": denominator_key,
                },
            }
        )
    return derived


def validate_observation(observation: Any, publication_time: datetime, index: int) -> None:
    label = f"observations[{index}]"
    require_exact_keys(
        observation,
        {"window_label", "as_of", "captured_at", "data_completeness", "layers", "metrics", "business_events"},
        label,
    )
    window = observation["window_label"]
    if window not in WINDOW_BOUNDS_HOURS:
        raise TrackerError("invalid_window", f"{label}.window_label must be early or d7")
    as_of = parse_time(observation["as_of"], f"{label}.as_of")
    captured = parse_time(observation["captured_at"], f"{label}.captured_at")
    elapsed = (as_of - publication_time).total_seconds() / 3600
    minimum, maximum = WINDOW_BOUNDS_HOURS[window]
    if not minimum <= elapsed <= maximum:
        raise TrackerError("window_drift", f"{window} is {elapsed:g}h after publication")
    capture_lag = (captured - as_of).total_seconds() / 3600
    if capture_lag < 0 or capture_lag > 24:
        raise TrackerError("stale_observation", f"{window} captured {capture_lag:g}h after as_of")
    if observation["data_completeness"] not in {"complete", "partial", "unavailable"}:
        raise TrackerError("invalid_completeness", label)
    require_exact_keys(observation["layers"], set(LAYERS), f"{label}.layers")
    for layer, status in observation["layers"].items():
        if status not in {"observed", "not_observed"}:
            raise TrackerError("invalid_layer_status", f"{label}.layers.{layer}")
    if not isinstance(observation["metrics"], list):
        raise TrackerError("invalid_shape", f"{label}.metrics must be an array")
    for metric_index, metric in enumerate(observation["metrics"]):
        validate_metric(metric, f"{label}.metrics[{metric_index}]")
    validate_metric_set(observation["metrics"], f"{label}.metrics")
    if observation["data_completeness"] == "unavailable" and any(
        metric["value"] is not None for metric in observation["metrics"]
    ):
        raise TrackerError("unavailable_metric_has_value", label)
    events = observation["business_events"]
    if not isinstance(events, list):
        raise TrackerError("invalid_shape", f"{label}.business_events must be an array")
    for event_index, event in enumerate(events):
        require_exact_keys(event, {"event_type", "event_ref", "occurred_at"}, f"{label}.business_events[{event_index}]")
        if event["event_type"] not in QUALIFYING_BUSINESS_EVENTS:
            raise TrackerError("signal_escalation", "only explicit qualifying events may enter the business layer")
        if not str(event["event_ref"]).startswith("synthetic-event:"):
            raise TrackerError("privacy_boundary_violation", "fixture business event refs must be synthetic")
        parse_time(event["occurred_at"], f"{label}.business_events[{event_index}].occurred_at")
    if bool(events) != (observation["layers"]["business"] == "observed"):
        raise TrackerError("business_layer_mismatch", f"{label}.layers.business must match qualifying events")


def validate_input(entry: dict[str, Any]) -> None:
    reject_sensitive_keys(entry)
    require_exact_keys(
        entry,
        {
            "schema_version",
            "synthetic_only",
            "mode",
            "content_id",
            "source_objects",
            "publication",
            "privacy",
            "observations",
        },
        "input",
    )
    if entry["schema_version"] != "manual-publication-feedback-input.v1":
        raise TrackerError("schema_version_mismatch", str(entry["schema_version"]))
    if entry["synthetic_only"] is not True or entry["mode"] != "manual_entry_only":
        raise TrackerError("synthetic_only_required", "this adapter currently accepts synthetic manual entries only")
    require_exact_keys(
        entry["source_objects"],
        {
            "account_ref",
            "account_sha256",
            "topic_ref",
            "topic_sha256",
            "content_item_ref",
            "content_item_sha256",
        },
        "source_objects",
    )
    require_exact_keys(
        entry["publication"],
        {"published_at", "recorded_at", "platform", "title", "channel_variant", "body_unavailable_reason"},
        "publication",
    )
    published = parse_time(entry["publication"]["published_at"], "publication.published_at")
    recorded = parse_time(entry["publication"]["recorded_at"], "publication.recorded_at")
    if recorded < published:
        raise TrackerError("recorded_before_publication", "recorded_at cannot precede published_at")
    if not entry["publication"]["platform"] or not entry["publication"]["title"]:
        raise TrackerError("missing_required_field", "publication platform and title are required")
    require_exact_keys(
        entry["privacy"],
        {"raw_comments_included", "tracking_parameters_included", "direct_identifiers_included", "customer_text_included"},
        "privacy",
    )
    if any(entry["privacy"].values()):
        raise TrackerError("privacy_boundary_violation", "manual tracking input must not include raw/private data")
    observations = entry["observations"]
    if not isinstance(observations, list) or len(observations) != 2:
        raise TrackerError("window_missing", "exactly early and d7 observations are required")
    windows = [item.get("window_label") if isinstance(item, dict) else None for item in observations]
    if len(set(windows)) != len(windows):
        raise TrackerError("duplicate_window", "observation window labels must be unique")
    if set(windows) != set(WINDOW_BOUNDS_HOURS):
        raise TrackerError("window_missing", "early and d7 observations are required")
    for index, observation in enumerate(observations):
        validate_observation(observation, published, index)
    source_artifacts(entry)


def build_ids(entry: dict[str, Any]) -> dict[str, str]:
    seed = f"{entry['content_id']}:{entry['publication']['published_at']}:{entry['publication']['platform']}"
    return {
        "publication_id": stable_operation_id("pub", seed),
        "event_id": stable_operation_id("evt", f"{seed}:published"),
        "version_id": stable_operation_id("ver", f"{seed}:version"),
        "early_snapshot_id": stable_operation_id("snap", f"{seed}:early"),
        "d7_snapshot_id": stable_operation_id("snap", f"{seed}:d7"),
    }


def build_publication_event(entry: dict[str, Any], account: dict[str, Any], ids: dict[str, str]) -> dict[str, Any]:
    publication = entry["publication"]
    return {
        "schema_version": "0.1",
        "event_id": ids["event_id"],
        "publication_id": ids["publication_id"],
        "event_sequence": 1,
        "content_id": entry["content_id"],
        "version_id": ids["version_id"],
        "account_id": account["account_id"],
        "platform": publication["platform"],
        "platform_content_id": None,
        "canonical_url": None,
        "event_type": "published",
        "occurred_at": publication["published_at"],
        "recorded_at": publication["recorded_at"],
        "actor_type": "user",
        "evidence_status": "manual-observation",
        "supersedes_event_id": None,
        "reason": "Synthetic manual-entry fixture; no platform account or API was accessed.",
        "frozen_version": {
            "title": publication["title"],
            "channel_variant": publication["channel_variant"],
            "freeze_status": "partial",
            "body_ref": None,
            "body_sha256": None,
            "cover_refs": [],
            "media_refs": [],
            "cta": None,
            "unavailable_reason": publication["body_unavailable_reason"],
            "frozen_at": publication["published_at"],
        },
    }


def build_snapshots(entry: dict[str, Any], ids: dict[str, str]) -> list[dict[str, Any]]:
    snapshots: list[dict[str, Any]] = []
    for observation in sorted(entry["observations"], key=lambda item: parse_time(item["as_of"], "as_of")):
        window = observation["window_label"]
        metrics = [
            {
                "metric_key": metric["metric_key"],
                "value": metric["value"],
                "unit": metric["unit"],
                "dimensions": {"layer": metric["layer"], "synthetic": True},
                **(
                    {"unavailable_reason": "Synthetic fixture has no observable platform value."}
                    if metric["value"] is None
                    else {}
                ),
            }
            for metric in observation["metrics"]
        ]
        metrics.extend(derive_metrics(metrics))
        snapshot = {
            "schema_version": "0.1",
            "snapshot_id": ids[f"{window}_snapshot_id"],
            "publication_id": ids["publication_id"],
            "as_of": observation["as_of"],
            "captured_at": observation["captured_at"],
            "window_label": window,
            "timezone": "Asia/Shanghai",
            "metric_dictionary_version": "cold-start-content-signals.1.1",
            "source_type": "other",
            "data_completeness": observation["data_completeness"],
            "metrics": metrics,
            "notes": "Synthetic manual observation; no live platform access.",
        }
        if observation["data_completeness"] != "complete":
            snapshot["missing_reasons"] = ["Manual observation was partial or unavailable."]
        snapshots.append(snapshot)
    return snapshots


def validate_derived_snapshot_metrics(entry: dict[str, Any], snapshots: list[dict[str, Any]]) -> None:
    observations = {item["window_label"]: item for item in entry["observations"]}
    for snapshot in snapshots:
        window = snapshot["window_label"]
        if snapshot["data_completeness"] == "unavailable" and all(
            metric["value"] is None for metric in snapshot["metrics"]
        ):
            continue
        expected = derive_metrics(observations[window]["metrics"])
        actual = [
            metric
            for metric in snapshot["metrics"]
            if metric["metric_key"] in DERIVED_CONTENT_METRICS
        ]
        if actual != expected:
            raise TrackerError("derived_metric_drift", window)
        keys = [metric["metric_key"] for metric in snapshot["metrics"]]
        if len(keys) != len(set(keys)):
            raise TrackerError("duplicate_metric", f"snapshot.{window}")


def build_tracked_objects(
    entry: dict[str, Any],
    account: dict[str, Any],
    topic: dict[str, Any],
    content: dict[str, Any],
    ids: dict[str, str],
    snapshots: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    published_at = entry["publication"]["published_at"]
    tracked_account = copy.deepcopy(account)
    tracked_account["status"] = "active"
    tracked_account["updated_at"] = published_at
    tracked_topic = copy.deepcopy(topic)
    tracked_topic["status"] = "published"
    tracked_topic["updated_at"] = published_at
    tracked_content = copy.deepcopy(content)
    tracked_content["status"] = "feedback"
    tracked_content["updated_at"] = max(snapshot["captured_at"] for snapshot in snapshots)
    tracked_content["publication"] = {
        "boundary": "manual-only",
        "receipts": [
            {
                "channel": entry["publication"]["platform"],
                "published_at": published_at,
                "url_or_id": None,
                "published_by": "synthetic-fixture-user",
            }
        ],
    }
    refs = tracked_content.setdefault("operating_refs", {})
    refs["publication_ids"] = [ids["publication_id"]]
    for channel in tracked_content.get("channels", {}).values():
        if isinstance(channel, dict) and "status" in channel:
            channel["status"] = "published"

    any_content_signal = any(metric["value"] is not None for snapshot in snapshots for metric in snapshot["metrics"])
    business_events = [
        event
        for observation in entry["observations"]
        for event in observation["business_events"]
    ]
    measurements: dict[str, list[dict[str, Any]]] = {layer: [] for layer in LAYERS}
    snapshot_ids = {snapshot["window_label"]: snapshot["snapshot_id"] for snapshot in snapshots}
    for observation in entry["observations"]:
        window = observation["window_label"]
        source = f"snapshot:{snapshot_ids[window]}"
        for layer in LAYERS:
            measurements[layer].append(
                {
                    "name": f"{window}.{layer}",
                    "value": observation["layers"][layer],
                    "source": source,
                    "note": "Synthetic aggregate observation; no raw comments or customer data.",
                }
            )
    platform_signals = {
        snapshot["window_label"]: {
            metric["metric_key"]: metric["value"] for metric in snapshot["metrics"]
        }
        for snapshot in snapshots
    }
    tracked_content["feedback"] = {
        "signal_status": "observed" if any_content_signal else "no_signal",
        "platform_signals": platform_signals,
        "business_signals": {
            "qualifying_event_types": sorted({event["event_type"] for event in business_events}),
            "manual_confirmation_required": bool(business_events),
            "crm_write_performed": False,
        },
        "qualitative_feedback": [],
        "learning_decision": "none" if any_content_signal else "insufficient-evidence",
        "next_test": "Human review only; do not infer customer sentiment or write CRM state.",
        "content_signal_status": "observed" if any_content_signal else "content_no_signal",
        "business_signal_status": "observed" if business_events else "not-observed",
        "measurement_layers": measurements,
    }
    return tracked_account, tracked_topic, tracked_content


def build_review_packet(
    entry: dict[str, Any], ids: dict[str, str], snapshots: list[dict[str, Any]], content: dict[str, Any]
) -> dict[str, Any]:
    content_status = content["feedback"]["content_signal_status"]
    business_status = content["feedback"]["business_signal_status"]
    refs = [f"publication-event:{ids['event_id']}"] + [
        f"performance-snapshot:{snapshot['snapshot_id']}" for snapshot in snapshots
    ]
    return {
        "receipt_id": stable_short_id("review", ids["publication_id"]),
        "title": "Synthetic manual publication feedback review",
        "lane": "vibe-living-pending-acceptance",
        "owner_ref": "vibe-living-owner",
        "priority": "P2",
        "risk": "low",
        "requested_status": "review",
        "today_goal": False,
        "next_action": "Review the synthetic pack only; no publication, contact, or CRM write is authorized.",
        "waiting_on": "vibe-living-owner-acceptance",
        "review_packet": {
            "suggested_points": [
                "Confirm the manual publication event is the sole time origin and both required windows are present.",
                f"Confirm content status={content_status}; views, likes, saves, and shares remain content signals only.",
                f"Confirm business status={business_status}; any qualifying event still requires human confirmation before CRM use.",
            ],
            "discarded_or_not_started": "No platform login/API read, raw comments, customer identity, relationship inference, CRM write, or publishing action was started.",
            "decision_question": "Accept this synthetic tracking pack into the vibe-living pending-verification queue?",
            "evidence_status": "reviewed",
            "evidence_refs": refs,
        },
        "metadata": {
            "facade_contract": "review-packet.v1",
            "native_contract": "attention-review-packet.v0.1",
            "producer": "self-media-creation-system",
            "consumer": "vibe-living",
            "queue_state": "pending_acceptance",
            "synthetic_only": True,
            "execution_authorized": False,
            "external_io_performed": False,
            "publication_boundary": "manual-only",
            "crm_write_performed": False,
            "input_sha256": canonical_sha256(entry),
        },
    }


def negative_descriptors() -> dict[str, Any]:
    return {
        "fixture_contract": "manual-publication-feedback-negative-cases.v1",
        "synthetic_only": True,
        "cases": [
            {"id": "stale-source-hash", "stage": "input", "mutation": "stale_source_hash", "expected_code": "stale_source_artifact"},
            {"id": "missing-day7-window", "stage": "input", "mutation": "missing_d7", "expected_code": "window_missing"},
            {"id": "duplicate-window", "stage": "input", "mutation": "duplicate_window", "expected_code": "duplicate_window"},
            {"id": "early-window-drift", "stage": "input", "mutation": "early_window_drift", "expected_code": "window_drift"},
            {"id": "stale-capture", "stage": "input", "mutation": "stale_capture", "expected_code": "stale_observation"},
            {"id": "raw-comment-field", "stage": "input", "mutation": "raw_comment", "expected_code": "privacy_boundary_violation"},
            {"id": "tracking-parameter", "stage": "input", "mutation": "tracking_parameter", "expected_code": "privacy_boundary_violation"},
            {"id": "like-promoted-to-business", "stage": "input", "mutation": "like_as_business", "expected_code": "signal_escalation"},
            {"id": "duplicate-metric", "stage": "input", "mutation": "duplicate_metric", "expected_code": "duplicate_metric"},
            {"id": "manual-derived-metric", "stage": "input", "mutation": "manual_derived_metric", "expected_code": "derived_metric_is_computed"},
            {"id": "retention-order-invalid", "stage": "input", "mutation": "retention_order_invalid", "expected_code": "retention_order_invalid"},
            {"id": "duplicate-publication-event", "stage": "output", "mutation": "duplicate_publication_event", "expected_code": "duplicate_publication_event"},
            {"id": "duplicate-performance-snapshot", "stage": "output", "mutation": "duplicate_snapshot", "expected_code": "duplicate_snapshot"},
            {"id": "derived-metric-drift", "stage": "output", "mutation": "derived_metric_drift", "expected_code": "derived_metric_drift"},
            {"id": "content-no-signal-promoted", "stage": "output", "mutation": "no_signal_customer_negative", "expected_code": "no_signal_escalation"},
        ],
    }


def apply_input_mutation(entry: dict[str, Any], mutation: str) -> dict[str, Any]:
    candidate = copy.deepcopy(entry)
    if mutation == "stale_source_hash":
        candidate["source_objects"]["content_item_sha256"] = "0" * 64
    elif mutation == "missing_d7":
        candidate["observations"] = [item for item in candidate["observations"] if item["window_label"] != "d7"]
    elif mutation == "duplicate_window":
        candidate["observations"][1]["window_label"] = "early"
    elif mutation == "early_window_drift":
        early = next(item for item in candidate["observations"] if item["window_label"] == "early")
        early["as_of"] = "2026-08-09T11:00:00+08:00"
        early["captured_at"] = "2026-08-09T11:10:00+08:00"
    elif mutation == "stale_capture":
        early = next(item for item in candidate["observations"] if item["window_label"] == "early")
        early["captured_at"] = "2026-08-10T00:00:00+08:00"
    elif mutation == "raw_comment":
        candidate["raw_comments"] = ["synthetic-looking but raw comment text is forbidden"]
    elif mutation == "tracking_parameter":
        candidate["publication"]["body_unavailable_reason"] = "https://example.invalid/?utm_source=fixture"
    elif mutation == "like_as_business":
        early = next(item for item in candidate["observations"] if item["window_label"] == "early")
        early["layers"]["business"] = "observed"
        early["business_events"] = [
            {
                "event_type": "liked",
                "event_ref": "synthetic-event:like",
                "occurred_at": early["as_of"],
            }
        ]
    elif mutation == "duplicate_metric":
        early = next(item for item in candidate["observations"] if item["window_label"] == "early")
        early["metrics"].append(copy.deepcopy(early["metrics"][0]))
    elif mutation == "manual_derived_metric":
        early = next(item for item in candidate["observations"] if item["window_label"] == "early")
        early["metrics"].append(
            {"layer": "value", "metric_key": "profile_visit_rate", "value": 7.5, "unit": "percent"}
        )
    elif mutation == "retention_order_invalid":
        early = next(item for item in candidate["observations"] if item["window_label"] == "early")
        for metric in early["metrics"]:
            if metric["metric_key"] == "retention_5s_rate":
                metric["value"] = 90
    else:
        raise TrackerError("unknown_mutation", mutation)
    return candidate


def apply_output_mutation(root: Path, mutation: str) -> None:
    if mutation == "duplicate_publication_event":
        path = root / "publication-events.json"
        bundle = load_json(path)
        bundle["items"].append(copy.deepcopy(bundle["items"][0]))
        write_json(path, bundle)
    elif mutation == "duplicate_snapshot":
        path = root / "performance-snapshots.json"
        bundle = load_json(path)
        bundle["items"][1]["snapshot_id"] = bundle["items"][0]["snapshot_id"]
        write_json(path, bundle)
    elif mutation == "derived_metric_drift":
        path = root / "performance-snapshots.json"
        bundle = load_json(path)
        early = next(item for item in bundle["items"] if item["window_label"] == "early")
        derived = next(item for item in early["metrics"] if item["metric_key"] == "profile_visit_rate")
        derived["value"] = derived["value"] + 1
        write_json(path, bundle)
    elif mutation == "no_signal_customer_negative":
        snapshots_path = root / "performance-snapshots.json"
        snapshots = load_json(snapshots_path)
        for snapshot in snapshots["items"]:
            snapshot["data_completeness"] = "unavailable"
            snapshot["missing_reasons"] = ["Synthetic no-signal mutation."]
            for metric in snapshot["metrics"]:
                metric["value"] = None
                metric["unavailable_reason"] = "Synthetic no-signal mutation."
        write_json(snapshots_path, snapshots)
        path = root / "content-item.json"
        content = load_json(path)
        for values in content["feedback"]["platform_signals"].values():
            for key in values:
                values[key] = None
        content["feedback"]["content_signal_status"] = "content_no_signal"
        content["feedback"]["signal_status"] = "no_signal"
        content["feedback"]["learning_decision"] = "insufficient-evidence"
        content["feedback"]["business_signal_status"] = "customer_no_response_observed"
        content["feedback"]["business_signals"]["customer_conclusion"] = "negative"
        write_json(path, content)
    else:
        raise TrackerError("unknown_mutation", mutation)


def generate_pack(input_path: Path = DEFAULT_INPUT, output_root: Path = DEFAULT_OUTPUT) -> dict[str, Any]:
    entry = load_json(input_path)
    validate_input(entry)
    account, topic, content = source_artifacts(entry)
    ids = build_ids(entry)
    event = build_publication_event(entry, account, ids)
    snapshots = build_snapshots(entry, ids)
    tracked_account, tracked_topic, tracked_content = build_tracked_objects(
        entry, account, topic, content, ids, snapshots
    )
    review_packet = build_review_packet(entry, ids, snapshots, tracked_content)

    staging = output_root.with_name(f".{output_root.name}.staging")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    write_json(staging / "manual-input.json", entry)
    write_json(staging / "account.json", tracked_account)
    write_json(staging / "topic.json", tracked_topic)
    write_json(staging / "content-item.json", tracked_content)
    write_json(staging / "publication-events.json", {"synthetic_only": True, "items": [event]})
    write_json(staging / "performance-snapshots.json", {"synthetic_only": True, "items": snapshots})
    write_json(staging / "review-packet.json", review_packet)
    negative_cases = load_json(DEFAULT_NEGATIVE_CASES)
    if negative_cases != negative_descriptors():
        raise TrackerError("negative_fixture_drift", "committed negative cases drifted from the adapter")
    write_json(staging / "negative-cases.json", negative_cases)

    contract_refs = {
        "account": ACCOUNT_SCHEMA,
        "topic": TOPIC_SCHEMA,
        "content-item": CONTENT_SCHEMA,
        "publication-event": PUBLICATION_SCHEMA,
        "performance-snapshot": SNAPSHOT_SCHEMA,
        "review-packet-intake": ATTENTION_SCHEMA,
    }
    manifest = {
        "schema_version": "manual-publication-feedback-pack.v1",
        "synthetic_only": True,
        "mode": "manual_entry_only",
        "dispatch_id": "SYNTHETIC-PUBLICATION-FEEDBACK-EXAMPLE",
        "content_id": entry["content_id"],
        "account_id": tracked_account["account_id"],
        "topic_id": tracked_topic["topic_id"],
        "publication_id": ids["publication_id"],
        "input_sha256": canonical_sha256(entry),
        "window_policy_hours": {"early": [48, 72], "d7": [156, 180]},
        "signal_policy": {
            "layers": list(LAYERS),
            "content_metrics_are_business_signals": False,
            "content_no_signal_is_customer_negative": False,
            "business_qualifying_events": sorted(QUALIFYING_BUSINESS_EVENTS),
            "crm_write_authorized": False,
        },
        "boundaries": {
            "manual_publication_only": True,
            "platform_access_performed": False,
            "external_io_performed": False,
            "raw_comments_included": False,
            "customer_data_included": False,
            "execution_authorized": False,
        },
        "contracts": [
            {
                "name": name,
                "path": path.relative_to(WORKSPACE_ROOT).as_posix(),
                "sha256": sha256_file(path),
            }
            for name, path in contract_refs.items()
        ],
        "artifacts": [],
    }
    artifacts = sorted(path for path in staging.iterdir() if path.is_file() and path.name != "manifest.json")
    manifest["artifacts"] = [
        {"path": path.name, "sha256": sha256_file(path)} for path in artifacts
    ]
    write_json(staging / "manifest.json", manifest)
    validate_pack_strict(staging)
    if output_root.exists():
        shutil.rmtree(output_root)
    staging.replace(output_root)
    return {
        "status": "generated_synthetic_manual_tracking_pack",
        "output_root": str(output_root),
        "publication_id": ids["publication_id"],
        "review_packet_ref": str(output_root / "review-packet.json"),
        "manifest_sha256": sha256_file(output_root / "manifest.json"),
    }


def validate_pack_strict(root: Path = DEFAULT_OUTPUT) -> None:
    manifest = load_json(root / "manifest.json")
    if manifest.get("synthetic_only") is not True or manifest.get("mode") != "manual_entry_only":
        raise TrackerError("boundary_violation", "pack must be synthetic manual-entry only")
    if manifest.get("boundaries", {}).get("execution_authorized") is not False:
        raise TrackerError("execution_boundary_violation", "tracking pack cannot authorize execution")
    input_entry = load_json(root / "manual-input.json")
    validate_input(input_entry)
    if canonical_sha256(input_entry) != manifest.get("input_sha256"):
        raise TrackerError("input_hash_mismatch", "manifest input hash drifted")

    account = load_json(root / "account.json")
    topic = load_json(root / "topic.json")
    content = load_json(root / "content-item.json")
    events_bundle = load_json(root / "publication-events.json")
    snapshots_bundle = load_json(root / "performance-snapshots.json")
    review = load_json(root / "review-packet.json")
    validate_schema(account, ACCOUNT_SCHEMA, "account")
    validate_schema(topic, TOPIC_SCHEMA, "topic")
    validate_schema(content, CONTENT_SCHEMA, "content-item")
    validate_schema(review, ATTENTION_SCHEMA, "review-packet")

    events = events_bundle.get("items")
    if events_bundle.get("synthetic_only") is not True or not isinstance(events, list) or not events:
        raise TrackerError("publication_event_missing", "one synthetic publication event is required")
    event_ids = [event.get("event_id") for event in events if isinstance(event, dict)]
    if len(event_ids) != len(set(event_ids)) or len(events) != 1:
        raise TrackerError("duplicate_publication_event", "exactly one unique publication event is allowed")
    event = events[0]
    validate_schema(event, PUBLICATION_SCHEMA, "publication-event")
    if event["event_type"] != "published" or event["actor_type"] != "user":
        raise TrackerError("publication_boundary_violation", "manual published event is required")
    if event.get("canonical_url") is not None or event.get("platform_content_id") is not None:
        raise TrackerError("privacy_boundary_violation", "fixture must not contain platform identifiers or URLs")
    if event["publication_id"] != manifest["publication_id"]:
        raise TrackerError("publication_reference_drift", "event publication_id drifted")

    snapshots = snapshots_bundle.get("items")
    if snapshots_bundle.get("synthetic_only") is not True or not isinstance(snapshots, list) or len(snapshots) != 2:
        raise TrackerError("window_missing", "exactly two snapshots are required")
    snapshot_ids = [snapshot.get("snapshot_id") for snapshot in snapshots if isinstance(snapshot, dict)]
    if len(snapshot_ids) != len(set(snapshot_ids)):
        raise TrackerError("duplicate_snapshot", "snapshot ids must be unique")
    if [snapshot["as_of"] for snapshot in snapshots] != sorted(snapshot["as_of"] for snapshot in snapshots):
        raise TrackerError("snapshot_order_drift", "snapshots must be ordered by as_of")
    if {snapshot["window_label"] for snapshot in snapshots} != set(WINDOW_BOUNDS_HOURS):
        raise TrackerError("window_missing", "early and d7 snapshots are required")
    publication_time = parse_time(event["occurred_at"], "publication-event.occurred_at")
    for snapshot in snapshots:
        validate_schema(snapshot, SNAPSHOT_SCHEMA, f"snapshot.{snapshot.get('window_label')}")
        if snapshot["publication_id"] != event["publication_id"]:
            raise TrackerError("publication_reference_drift", "snapshot publication_id drifted")
        as_of = parse_time(snapshot["as_of"], "snapshot.as_of")
        elapsed = (as_of - publication_time).total_seconds() / 3600
        minimum, maximum = WINDOW_BOUNDS_HOURS[snapshot["window_label"]]
        if not minimum <= elapsed <= maximum:
            raise TrackerError("window_drift", f"{snapshot['window_label']} is {elapsed:g}h after publication")
    validate_derived_snapshot_metrics(input_entry, snapshots)

    refs = content.get("operating_refs", {})
    if refs.get("account_ids") != [account["account_id"]]:
        raise TrackerError("account_reference_drift", "tracked content account ref drifted")
    if refs.get("topic_ids") != [topic["topic_id"]]:
        raise TrackerError("topic_reference_drift", "tracked content topic ref drifted")
    if refs.get("publication_ids") != [event["publication_id"]]:
        raise TrackerError("publication_reference_drift", "tracked content publication ref drifted")
    if content.get("status") != "feedback" or content.get("publication", {}).get("boundary") != "manual-only":
        raise TrackerError("content_lifecycle_drift", "content must be feedback/manual-only")
    feedback = content.get("feedback", {})
    measurements = feedback.get("measurement_layers", {})
    if set(measurements) != set(LAYERS):
        raise TrackerError("six_layer_review_missing", "all six measurement layers are required")
    any_content_signal = any(metric.get("value") is not None for snapshot in snapshots for metric in snapshot["metrics"])
    expected_content_status = "observed" if any_content_signal else "content_no_signal"
    if feedback.get("content_signal_status") != expected_content_status:
        raise TrackerError("content_signal_mismatch", "content signal status does not match snapshots")
    business = feedback.get("business_signals", {})
    event_types = set(business.get("qualifying_event_types", []))
    if not event_types.issubset(QUALIFYING_BUSINESS_EVENTS):
        raise TrackerError("signal_escalation", "non-qualifying event entered business signals")
    if expected_content_status == "content_no_signal":
        if feedback.get("learning_decision") != "insufficient-evidence":
            raise TrackerError("no_signal_escalation", "content_no_signal must remain insufficient evidence")
        if feedback.get("business_signal_status") == "customer_no_response_observed":
            raise TrackerError("no_signal_escalation", "content_no_signal cannot become a customer conclusion")
        if "customer_conclusion" in business:
            raise TrackerError("no_signal_escalation", "customer conclusion is forbidden")
    if business.get("crm_write_performed") is not False:
        raise TrackerError("crm_boundary_violation", "tracking pack cannot write CRM state")

    packet = review.get("review_packet", {})
    if len(packet.get("suggested_points", [])) != 3:
        raise TrackerError("review_packet_invalid", "review packet must contain exactly three points")
    if not isinstance(packet.get("decision_question"), str):
        raise TrackerError("review_packet_invalid", "review packet has at most one string decision question")
    metadata = review.get("metadata", {})
    if metadata.get("synthetic_only") is not True or metadata.get("execution_authorized") is not False:
        raise TrackerError("review_packet_boundary_violation", "review packet cannot authorize execution")
    if metadata.get("consumer") != "vibe-living" or metadata.get("queue_state") != "pending_acceptance":
        raise TrackerError("review_packet_consumer_drift", "review packet must remain pending vibe-living acceptance")

    for artifact in manifest.get("artifacts", []):
        path = root / artifact["path"]
        if not path.is_file():
            raise TrackerError("artifact_missing", artifact["path"])
        if sha256_file(path) != artifact["sha256"]:
            raise TrackerError("artifact_hash_mismatch", artifact["path"])


def validate_pack(root: Path = DEFAULT_OUTPUT) -> list[str]:
    try:
        validate_pack_strict(root)
    except TrackerError as error:
        return [f"{error.code}: {error}"]
    return []


def file_map(root: Path) -> dict[str, bytes]:
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def idempotency_check(input_path: Path = DEFAULT_INPUT) -> list[str]:
    run_a = ROOT / "tests" / ".tmp-publication-feedback-a"
    run_b = ROOT / "tests" / ".tmp-publication-feedback-b"
    try:
        generate_pack(input_path, run_a)
        generate_pack(input_path, run_b)
        if file_map(run_a) != file_map(run_b):
            return ["double generation is not byte-for-byte stable"]
        return []
    finally:
        shutil.rmtree(run_a, ignore_errors=True)
        shutil.rmtree(run_b, ignore_errors=True)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    generate = subparsers.add_parser("generate", help="import one synthetic manual entry into a tracking pack")
    generate.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    generate.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    validate = subparsers.add_parser("validate", help="validate an existing tracking pack")
    validate.add_argument("--root", type=Path, default=DEFAULT_OUTPUT)
    check = subparsers.add_parser("check", help="validate and run the byte-stable double generation check")
    check.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    check.add_argument("--root", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.command == "generate":
            print(json_text(generate_pack(args.input, args.output)), end="")
            return 0
        errors = validate_pack(args.root)
        if args.command == "check":
            errors.extend(idempotency_check(args.input))
        if errors:
            print(json_text({"status": "failed", "errors": errors}), end="", file=sys.stderr)
            return 1
        print(
            json_text(
                {
                    "status": "passed",
                    "root": str(args.root),
                    "synthetic_only": True,
                    "windows": ["early", "d7"],
                    "idempotency": "passed" if args.command == "check" else "not-run",
                    "execution_authorized": False,
                }
            ),
            end="",
        )
        return 0
    except TrackerError as error:
        print(json_text({"status": error.code, "message": str(error)}), end="", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
