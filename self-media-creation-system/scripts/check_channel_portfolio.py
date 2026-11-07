#!/usr/bin/env python3
"""Validate the active channel portfolio against existing routing contracts."""

from __future__ import annotations

import json
import argparse
import importlib.util
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]
PORTFOLIO_PATH = ROOT / "channel-portfolio.v1.json"
SCHEMA_PATH = ROOT / "schemas" / "channel-portfolio.v1.schema.json"
COVERAGE_FIXTURE_PATH = ROOT / "fixtures" / "platform-coverage.v1.synthetic.json"
CANONICAL_ROUTING_PATH = ROOT / "scripts" / "canonical_routing.py"
CANONICAL_ROUTING_SPEC = importlib.util.spec_from_file_location(
    "self_media_canonical_routing", CANONICAL_ROUTING_PATH
)
assert CANONICAL_ROUTING_SPEC and CANONICAL_ROUTING_SPEC.loader
CANONICAL_ROUTING = importlib.util.module_from_spec(CANONICAL_ROUTING_SPEC)
CANONICAL_ROUTING_SPEC.loader.exec_module(CANONICAL_ROUTING)


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return value


def validate(
    portfolio_override: dict[str, Any] | None = None,
    coverage_fixture_override: dict[str, Any] | None = None,
) -> list[str]:
    errors: list[str] = []
    if portfolio_override is None and not PORTFOLIO_PATH.is_file():
        return ["operator channel portfolio is not configured; a synthetic fixture cannot establish active approval"]
    portfolio = load_json(PORTFOLIO_PATH) if portfolio_override is None else portfolio_override
    coverage_fixture = (
        load_json(COVERAGE_FIXTURE_PATH)
        if coverage_fixture_override is None
        else coverage_fixture_override
    )
    schema = load_json(SCHEMA_PATH)
    try:
        routing = CANONICAL_ROUTING.load_contracts()
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return [f"canonical routing: {error}"]
    router = routing["components"]["task_router"]
    adapters = routing["components"]["format_adapters"]
    overlays = routing["components"]["platform_overlays"]

    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    for error in sorted(validator.iter_errors(portfolio), key=lambda item: list(item.path)):
        path = ".".join(str(part) for part in error.path) or "$"
        errors.append(f"schema:{path}: {error.message}")

    router_platforms = set(router["enums"]["platform"])
    router_formats = set(router["enums"]["format"])
    router_accounts = set(router["enums"]["account_ip"])
    router_jobs = set(router["enums"]["content_job"])
    overlay_ids = {entry["id"] for entry in overlays["overlays"]}
    adapter_ids = {entry["id"] for entry in adapters["adapters"]}

    if coverage_fixture.get("synthetic_only") is not True:
        errors.append("platform coverage fixture must remain synthetic_only")
    if coverage_fixture.get("authority") != "test-expectation-only-not-a-platform-enum-source":
        errors.append("platform coverage fixture must not become an authoritative platform enum")
    if len(router_platforms) != 12:
        errors.append(f"canonical task-router must expose 12 platforms, found {len(router_platforms)}")
    fixture_cases = coverage_fixture.get("platform_cases", [])
    fixture_platforms = [case.get("platform") for case in fixture_cases if isinstance(case, dict)]
    if len(fixture_platforms) != len(set(fixture_platforms)):
        errors.append("platform coverage fixture contains duplicate platform cases")
    if set(fixture_platforms) != router_platforms:
        errors.append("platform coverage fixture must mirror the canonical task-router platforms")
    fixture_by_platform = {
        case["platform"]: case for case in fixture_cases if isinstance(case, dict) and case.get("platform")
    }

    channels = portfolio["channels"]
    channel_platforms = [entry["platform"] for entry in channels]
    if len(channel_platforms) != len(set(channel_platforms)):
        errors.append("channels must not contain duplicate platforms")
    if set(channel_platforms) != router_platforms:
        errors.append("channel portfolio must cover every task-router platform exactly once")

    for entry in channels:
        if entry["overlay_ref"] not in overlay_ids:
            errors.append(f"unknown overlay_ref: {entry['overlay_ref']}")
        unknown_formats = set(entry["primary_formats"]) - router_formats
        if unknown_formats:
            errors.append(f"{entry['platform']} has unknown formats: {sorted(unknown_formats)}")
        unknown_accounts = set(entry["account_ips"]) - router_accounts
        if unknown_accounts:
            errors.append(f"{entry['platform']} has unknown accounts: {sorted(unknown_accounts)}")
        runtime = entry.get("acquisition_runtime")
        if not isinstance(runtime, dict):
            errors.append(f"{entry['platform']} acquisition/runtime truth is missing")
            continue
        if runtime.get("execution_authority") != "none":
            errors.append(f"{entry['platform']} acquisition runtime grants execution authority")
        if runtime.get("account_access") != "not-authorized":
            errors.append(f"{entry['platform']} acquisition runtime grants account access")
        expected = fixture_by_platform.get(entry["platform"])
        if expected is not None:
            actual_truth = {
                "priority": entry.get("priority"),
                "acquisition_mode": runtime.get("acquisition_mode"),
                "runtime_status": runtime.get("runtime_status"),
                "real_media_download": runtime.get("real_media_download"),
            }
            expected_truth = {key: expected.get(key) for key in actual_truth}
            if actual_truth != expected_truth:
                errors.append(f"acquisition/runtime fixture drift: {entry['platform']}")

    current_stage = portfolio.get("current_stage") or {}
    expected_sync = {"xiaohongshu", "wechat-video", "douyin", "kuaishou", "bilibili"}
    declared_sync = set(current_stage.get("synchronized_public_platforms") or [])
    active_sync = {
        entry["platform"]
        for entry in channels
        if entry.get("current_distribution_status") == "active-synchronized-master"
    }
    if current_stage.get("distribution_mode") != "manual-synchronized-frozen-master":
        errors.append("current capacity must remain manual synchronized frozen master")
    if declared_sync != expected_sync or active_sync != expected_sync:
        errors.append("current synchronized platform set must match the five user-confirmed video platforms")
    if portfolio.get("weekly_core_unit", {}).get("same-copy-cross-posting") != "manual-synchronized-frozen-master":
        errors.append("same frozen master synchronization must remain allowed in the current capacity stage")

    for rule in portfolio["format_decision_rules"]:
        for adapter_ref in rule["adapter_ref"].split("|"):
            if adapter_ref not in adapter_ids:
                errors.append(f"unknown adapter_ref: {adapter_ref}")

    ip_accounts = {entry["account_ip"] for entry in portfolio["ip_routes"]}
    if ip_accounts != router_accounts:
        errors.append("ip_routes must cover every task-router account_ip exactly once")
    for route in portfolio["ip_routes"]:
        unknown_platforms = set(route["primary_platforms"]) - router_platforms
        unknown_formats = set(route["primary_formats"]) - router_formats
        unknown_jobs = set(route["content_jobs"]) - router_jobs
        if unknown_platforms:
            errors.append(f"{route['account_ip']} has unknown primary platforms: {sorted(unknown_platforms)}")
        if unknown_formats:
            errors.append(f"{route['account_ip']} has unknown primary formats: {sorted(unknown_formats)}")
        if unknown_jobs:
            errors.append(f"{route['account_ip']} has unknown content jobs: {sorted(unknown_jobs)}")

    stage_ref = router.get("defaults", {}).get("channel_portfolio_ref")
    if stage_ref != "self-media-creation-system/channel-portfolio.v1.json#current_stage":
        errors.append("task-router default channel_portfolio_ref is missing or stale")
    order = router.get("routing_order", [])
    if "channel-portfolio-and-stage" not in order:
        errors.append("task-router routing_order does not include channel portfolio selection")
    elif order.index("channel-portfolio-and-stage") > order.index("format-adapter"):
        errors.append("channel portfolio selection must happen before format adapter selection")

    if portfolio["publication_boundary"] != router.get("defaults", {}).get("publication_boundary"):
        errors.append("publication boundary must remain manual-only")
    if portfolio["weekly_core_unit"]["public_adaptation_max"] != router.get("defaults", {}).get("public_adaptation_max"):
        errors.append("public adaptation max must remain aligned with the canonical limit of two")
    adaptation_scope = "distinct-platform-variants-only-excludes-identical-frozen-master-sync"
    if portfolio["weekly_core_unit"].get("public_adaptation_max_scope") != adaptation_scope:
        errors.append("public adaptation max must apply only to distinct platform variants")
    if router.get("defaults", {}).get("public_adaptation_max_semantics") != adaptation_scope:
        errors.append("canonical public adaptation scope is missing or stale")
    if router.get("defaults", {}).get("current_capacity_distribution_mode") != "one-frozen-master-manual-synchronous-distribution":
        errors.append("canonical task-router current capacity mode is missing or stale")
    if portfolio["feedback_policy"]["private_feedback_gate"] != "helpful-not-required":
        errors.append("private feedback must not become a mandatory public publication gate")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--portfolio", type=Path, help="Explicit operator portfolio or review-only synthetic example")
    args = parser.parse_args()
    errors = validate(load_json(args.portfolio) if args.portfolio else None)
    if errors:
        print("Channel portfolio check failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print(
        "PASS: channel portfolio extension is compatible with the registered canonical routing set; "
        "router order, adapter refs, overlays, IP routes, and manual-only structure are valid; "
        "this does not establish active approval or runtime capability."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
