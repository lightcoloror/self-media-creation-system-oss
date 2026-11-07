#!/usr/bin/env python3
"""Build and validate three offline synthetic operating journeys from one fixture."""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OPERATIONS_SCRIPT = ROOT / "scripts" / "operations_contract_regression.py"
OPERATIONS_SPEC = importlib.util.spec_from_file_location("operations_contract_regression", OPERATIONS_SCRIPT)
assert OPERATIONS_SPEC and OPERATIONS_SPEC.loader
OPERATIONS = importlib.util.module_from_spec(OPERATIONS_SPEC)
OPERATIONS_SPEC.loader.exec_module(OPERATIONS)

DEFAULT_MATRIX = ROOT / "fixtures" / "operations-contract-regression.v1.scenarios.synthetic.json"
REQUIRED_SCENARIO_KEYS = {
    "scenario_id",
    "theme_key",
    "title",
    "topic_status",
    "content_status",
    "terminal_event_type",
    "expected_publication_state",
    "content_signal_status",
    "business_signal_status",
    "journey_trace",
    "ids",
    "expected_bundle_sha256",
}
REQUIRED_ID_KEYS = {
    "account_id",
    "topic_id",
    "publication_id",
    "prepared_event_id",
    "version_id",
    "published_event_id",
    "early_snapshot_id",
    "terminal_event_id",
    "d7_snapshot_id",
}
EXPECTED_JOURNEY_PREFIX = ["private-candidate", "public-rewrite", "prepared", "published"]


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _replace_exact(value: Any, mapping: dict[str, str]) -> Any:
    if isinstance(value, dict):
        return {key: _replace_exact(item, mapping) for key, item in value.items()}
    if isinstance(value, list):
        return [_replace_exact(item, mapping) for item in value]
    if isinstance(value, str):
        return mapping.get(value, value)
    return value


def derive_publication_state(events: list[dict[str, Any]]) -> str:
    state = "not-published"
    for event in events:
        event_type = event["event_type"]
        if event_type == "prepared":
            state = "prepared"
        elif event_type == "published":
            state = "published"
        elif event_type == "deleted":
            state = "deleted"
        elif event_type == "restored":
            state = "published"
        elif event_type in {"hidden", "restricted", "appeal-submitted"}:
            state = event_type
        elif event_type == "edited":
            state = state
    return state


def build_scenario_bundle(base: dict[str, Any], scenario: dict[str, Any]) -> dict[str, Any]:
    base_events = base["publication_events"]
    base_snapshots = base["performance_snapshots"]
    ids = scenario["ids"]
    mapping = {
        base["account"]["account_id"]: ids["account_id"],
        base["topic"]["topic_id"]: ids["topic_id"],
        base["content_item"]["content_id"]: f"synthetic-{scenario['scenario_id']}",
        base_events[0]["publication_id"]: ids["publication_id"],
        base_events[0]["event_id"]: ids["prepared_event_id"],
        base_events[0]["version_id"]: ids["version_id"],
        base_events[1]["event_id"]: ids["published_event_id"],
        base_snapshots[0]["snapshot_id"]: ids["early_snapshot_id"],
        base_snapshots[1]["snapshot_id"]: ids["d7_snapshot_id"],
    }
    bundle = _replace_exact(copy.deepcopy(base), mapping)
    bundle["fixture_id"] = f"fixture_{scenario['scenario_id']}"

    bundle["account"]["display_name"] = f"虚构回归账号：{scenario['theme_key']}"
    bundle["account"]["positioning"]["summary"] = f"仅验证 {scenario['scenario_id']} 经营事件链。"
    bundle["topic"]["title"] = scenario["title"]
    bundle["topic"]["status"] = scenario["topic_status"]
    bundle["topic"]["audience_problem"] = "只验证私域候选到公域改写、发布事件、快照和复盘的稳定引用。"

    content = bundle["content_item"]
    content["title"] = scenario["title"]
    content["status"] = scenario["content_status"]
    content["intent"]["topic"] = scenario["title"]
    content["intent"]["content_object"] = "一条完全虚构、由私域候选改写而来的公域测试内容。"
    content["composition"]["canonical_summary"] = f"{scenario['title']}；仅用于经营合同回归。"
    content["operating_plan"]["private_validation"] = {
        "channel": "private_conversation",
        "status": "feedback-recorded",
        "note": "完全虚构的私域候选阶段；没有真实聊天或用户。",
    }
    content["operating_plan"]["public_adaptations"] = {
        "primary": {
            "platform": "xiaohongshu",
            "role": "search-discovery-checklist",
            "status": "published",
            "content_variant": f"synthetic-{scenario['scenario_id']}-public-v1",
            "selection_reason": "只模拟从私域候选到公域改写的状态链，不代表真实发布。",
        }
    }

    published = bundle["publication_events"][1]
    published["frozen_version"]["title"] = scenario["title"]
    published["frozen_version"]["channel_variant"] = f"synthetic-{scenario['scenario_id']}-public-v1"
    if scenario["terminal_event_type"] == "deleted":
        bundle["publication_events"].append(
            {
                "schema_version": "0.1",
                "event_id": ids["terminal_event_id"],
                "publication_id": ids["publication_id"],
                "event_sequence": 3,
                "content_id": content["content_id"],
                "version_id": ids["version_id"],
                "account_id": ids["account_id"],
                "platform": "synthetic-platform",
                "platform_content_id": None,
                "canonical_url": None,
                "event_type": "deleted",
                "occurred_at": "2026-01-13T09:01:00+08:00",
                "recorded_at": "2026-01-13T09:02:00+08:00",
                "actor_type": "local-tool",
                "evidence_status": "local-record",
                "supersedes_event_id": ids["published_event_id"],
                "reason": "合成删除事件；保留此前事件和快照，不代表真实平台操作。",
            }
        )

    feedback = content["feedback"]
    feedback["content_signal_status"] = scenario["content_signal_status"]
    feedback["business_signal_status"] = scenario["business_signal_status"]
    if scenario["content_signal_status"] == "observed":
        feedback["signal_status"] = "observed"
        feedback["platform_signals"] = {"synthetic.impressions": 56, "synthetic.saves": 4}
        feedback["learning_decision"] = "retain"
        for layer in ("attraction", "consumption", "value"):
            feedback["measurement_layers"][layer] = [
                {"name": f"synthetic_{layer}_observed", "value": 1, "source": "fixture"}
            ]
    if scenario["business_signal_status"] == "observed":
        feedback["business_signals"] = {"synthetic.valid_question": 1}
        feedback["measurement_layers"]["business"] = [
            {
                "name": "synthetic_valid_question",
                "value": 1,
                "source": "fixture",
                "note": "完全虚构，只证明业务信号需要独立证据。",
            }
        ]

    review_by_layer = {review["layer"]: review for review in bundle["reviews"]}
    if scenario["content_signal_status"] == "observed":
        for layer in ("attraction", "consumption", "value"):
            review_by_layer[layer]["signal_status"] = "observed"
            review_by_layer[layer]["note"] = "观察到完全虚构的内容信号。"
    if scenario["business_signal_status"] == "observed":
        review_by_layer["business"]["signal_status"] = "observed"
        review_by_layer["business"]["note"] = "只记录完全虚构且有独立证据的业务信号。"
    return bundle


def matrix_shape_errors(matrix: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if set(matrix) != {"schema_version", "synthetic_only", "base_fixture", "scenarios"}:
        errors.append("scenario matrix must contain only schema_version, synthetic_only, base_fixture, scenarios")
    if matrix.get("schema_version") != "1" or matrix.get("synthetic_only") is not True:
        errors.append("scenario matrix must be schema_version=1 and synthetic_only=true")
    scenarios = matrix.get("scenarios")
    if not isinstance(scenarios, list) or len(scenarios) != 3:
        return errors + ["scenario matrix must contain exactly three synthetic scenarios"]
    scenario_ids: list[str] = []
    theme_keys: list[str] = []
    for index, scenario in enumerate(scenarios):
        label = f"scenarios[{index}]"
        if not isinstance(scenario, dict) or set(scenario) != REQUIRED_SCENARIO_KEYS:
            errors.append(f"{label} has missing or unknown fields")
            continue
        scenario_ids.append(scenario["scenario_id"])
        theme_keys.append(scenario["theme_key"])
        if set(scenario["ids"]) != REQUIRED_ID_KEYS:
            errors.append(f"{label}.ids has missing or unknown fields")
        if scenario["journey_trace"][:4] != EXPECTED_JOURNEY_PREFIX:
            errors.append(f"{label}.journey_trace must start with private candidate to public rewrite and publication")
    if len(scenario_ids) != len(set(scenario_ids)):
        errors.append("scenario_id values must be unique")
    if len(theme_keys) != len(set(theme_keys)):
        errors.append("theme_key values must be unique")
    return errors


def scenario_matrix_errors(matrix_path: Path = DEFAULT_MATRIX) -> list[str]:
    matrix = load_json(matrix_path)
    errors = matrix_shape_errors(matrix)
    if errors:
        return errors
    base_path = matrix_path.parent / matrix["base_fixture"]
    base = load_json(base_path)
    for scenario in matrix["scenarios"]:
        label = scenario["scenario_id"]
        bundle = build_scenario_bundle(base, scenario)
        errors.extend(f"{label}: {error}" for error in OPERATIONS.contract_errors(bundle))
        state = derive_publication_state(bundle["publication_events"])
        if state != scenario["expected_publication_state"]:
            errors.append(f"{label}: expected publication state {scenario['expected_publication_state']}, got {state}")
        if bundle["content_item"]["status"] != scenario["content_status"]:
            errors.append(f"{label}: content status does not match scenario expectation")
        public = bundle["content_item"]["operating_plan"]["public_adaptations"]["primary"]
        if public["status"] != "published":
            errors.append(f"{label}: public rewrite must be represented independently from content status")
        digest = canonical_sha256(bundle)
        if digest != scenario["expected_bundle_sha256"]:
            errors.append(f"{label}: idempotency hash mismatch; expected {scenario['expected_bundle_sha256']}, got {digest}")
        feedback = bundle["content_item"]["feedback"]
        if feedback["content_signal_status"] == "content_no_signal":
            if OPERATIONS.derive_customer_conclusions(feedback):
                errors.append(f"{label}: content_no_signal created a customer conclusion")
    return errors


def calculated_hashes(matrix_path: Path = DEFAULT_MATRIX) -> dict[str, str]:
    matrix = load_json(matrix_path)
    base = load_json(matrix_path.parent / matrix["base_fixture"])
    return {
        scenario["scenario_id"]: canonical_sha256(build_scenario_bundle(base, scenario))
        for scenario in matrix["scenarios"]
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix", type=Path, default=DEFAULT_MATRIX)
    parser.add_argument("--print-hashes", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.print_hashes:
        print(json.dumps(calculated_hashes(args.matrix), ensure_ascii=False, indent=2))
        return 0
    errors = scenario_matrix_errors(args.matrix)
    if errors:
        print("Synthetic operations scenario suite failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("PASS: three synthetic themes, private-to-public replay, snapshots, reviews, and hashes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
