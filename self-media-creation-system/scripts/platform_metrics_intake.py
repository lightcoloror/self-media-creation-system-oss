#!/usr/bin/env python3
"""Normalize manual exports from five platforms without inventing comparability.

The adapter reads local CSV/XLSX files only. It distinguishes an export profile
from a platform so item-level and account-day exports can coexist. It preserves
source grain, keeps account-day exports out of content attribution, and never
opens a platform or publishes content.
"""

from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import json
import math
import re
import sys
import warnings
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from jsonschema import Draft202012Validator, FormatChecker
from openpyxl import load_workbook


ROOT = Path(__file__).resolve().parents[1]
MAPPING_PATH = ROOT / "config" / "platform-metric-mappings.v1.json"
SCHEMA_PATH = ROOT / "schemas" / "platform-metrics-intake.v1.schema.json"
OUTPUT_ROOTS = (ROOT / ".runtime" / "platform-metrics-intake", ROOT / "tests" / ".runtime" / "platform-metrics-intake")
BOUNDARIES = {
    "offline_only": True,
    "platform_access_performed": False,
    "content_attribution_inferred": False,
    "cross_platform_metric_equivalence_assumed": False,
    "publication_authorized": False,
    "raw_comments_included": False,
}
PLATFORMS = {"xiaohongshu", "wechat_channels", "douyin", "kuaishou", "bilibili", "wechat_official_account"}


class MetricsIntakeError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise MetricsIntakeError("artifact_missing", str(path)) from error
    except json.JSONDecodeError as error:
        raise MetricsIntakeError("invalid_json", str(error)) from error
    if not isinstance(value, dict):
        raise MetricsIntakeError("invalid_json_root", str(path))
    return value


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def scalar_display(value: Any) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def compact_label(value: Any) -> str | None:
    display = scalar_display(value)
    if display is None:
        return None
    return display.splitlines()[0].strip()[:240]


def parse_number(value: Any, normalizer: str, empty_values: set[str] | None = None) -> float | int | None:
    if value is None or value == "" or str(value).strip() in (empty_values or set()):
        return None
    if isinstance(value, bool):
        raise MetricsIntakeError("invalid_metric_value", str(value))
    if normalizer in {"number", "signed_number"}:
        parsed = float(value)
    elif normalizer == "ratio_to_percent":
        parsed = float(value) * 100.0
    elif normalizer == "ratio_or_percent":
        display = str(value).strip()
        parsed = float(display.removesuffix("%"))
        if not display.endswith("%") and abs(parsed) <= 1:
            parsed *= 100.0
    elif normalizer == "percent_text":
        parsed = float(str(value).strip().removesuffix("%"))
    elif normalizer == "seconds_text":
        parsed = float(re.sub(r"(?:秒|s)$", "", str(value).strip(), flags=re.IGNORECASE))
    else:
        raise MetricsIntakeError("normalizer_unknown", normalizer)
    if normalizer != "signed_number" and parsed < 0:
        raise MetricsIntakeError("unexpected_negative_metric", f"{value} for {normalizer}")
    if not math.isfinite(parsed):
        raise MetricsIntakeError("invalid_metric_value", "finite numbers required")
    if parsed.is_integer():
        return int(parsed)
    return round(parsed, 6)


def read_csv_rows(path: Path, header_row: int, strict: bool = False, expected_headers: set[str] | None = None) -> list[tuple[int, dict[str, Any]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        raw_rows = list(csv.reader(handle))
    if len(raw_rows) < header_row:
        raise MetricsIntakeError("header_missing", path.name)
    headers = [str(item).strip() for item in raw_rows[header_row - 1]]
    if strict and (len(headers)!=len(set(headers)) or any(not h for h in headers)):
        raise MetricsIntakeError('template_header_invalid','duplicate or empty header')
    if expected_headers is not None and set(headers) != expected_headers:
        raise MetricsIntakeError('template_format_mismatch', 'Template headers must match even when there are no data rows')
    rows: list[tuple[int, dict[str, Any]]] = []
    for source_row, values in enumerate(raw_rows[header_row:], start=header_row + 1):
        if not any(value != "" for value in values):
            continue
        if strict and len(values)!=len(headers):
            raise MetricsIntakeError('template_row_width_invalid',str(source_row))
        padded = values + [""] * max(0, len(headers) - len(values))
        rows.append((source_row, dict(zip(headers, padded))))
    return rows


def read_xlsx_rows(path: Path, header_row: int) -> list[tuple[int, dict[str, Any]]]:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        sheet = workbook.active
        header_values = next(sheet.iter_rows(min_row=header_row, max_row=header_row, values_only=True))
        headers = [str(item).strip() if item is not None else "" for item in header_values]
        rows: list[tuple[int, dict[str, Any]]] = []
        for source_row, values in enumerate(sheet.iter_rows(min_row=header_row + 1, values_only=True), start=header_row + 1):
            if not any(value not in (None, "") for value in values):
                continue
            rows.append((source_row, dict(zip(headers, values))))
        return rows
    finally:
        workbook.close()


def read_rows(path: Path, config: dict[str, Any]) -> list[tuple[int, dict[str, Any]]]:
    if not path.is_file():
        raise MetricsIntakeError("artifact_missing", str(path))
    expected_suffix = ".xlsx" if config["file_type"] == "xlsx" else ".csv"
    if path.suffix.lower() != expected_suffix:
        raise MetricsIntakeError("file_type_mismatch", f"{path.name} must be {expected_suffix}")
    if config["file_type"] == "xlsx":
        return read_xlsx_rows(path, config["header_row"])
    template = config.get('compatibility_status') == 'template_only'
    expected = {"format_version", "source_grain", config["time_field"], *config["metrics"]} if template else None
    return read_csv_rows(path, config["header_row"], strict=template, expected_headers=expected)


def normalize_records(export_profile: str, rows: Iterable[tuple[int, dict[str, Any]]], config: dict[str, Any]) -> list[dict[str, Any]]:
    platform = config["platform"]
    grain = config["source_grain"]
    attribution = "direct-platform-item" if grain == "content_item" else "not-attributed-to-content"
    empty_values = {str(item).strip() for item in config.get("empty_values", [])}
    records: list[dict[str, Any]] = []
    for source_row, row in rows:
        template = config.get("compatibility_status") == "template_only"
        if template:
            expected = {"format_version", "source_grain", config["time_field"], *config["metrics"]}
            if set(row) != expected or row.get("format_version") != config["format_version"] or row.get("source_grain") != grain:
                raise MetricsIntakeError("template_format_mismatch", "Use the explicit v1 account-day template; official export compatibility is unverified")
            try:
                datetime.strptime(str(row[config["time_field"]]), "%Y-%m-%d")
            except ValueError as error:
                raise MetricsIntakeError("template_date_invalid", "date must be YYYY-MM-DD") from error
        metrics: list[dict[str, Any]] = []
        for source_key, (metric_key, unit, normalizer) in config["metrics"].items():
            if source_key not in row:
                raise MetricsIntakeError("required_header_missing", f"{platform}:{source_key}")
            raw = row[source_key]
            parsed = parse_number(raw, normalizer, empty_values)
            if template and parsed is not None and (unit == "count" and (type(parsed) is not int or parsed < 0) or unit == "percent" and not 0 <= parsed <= 100):
                raise MetricsIntakeError("template_metric_range", source_key)
            metrics.append(
                {
                    "metric_key": metric_key,
                    "source_metric_key": source_key,
                    "source_value_display": scalar_display(raw),
                    "value": parsed,
                    "unit": unit,
                    "semantic_status": "source-empty" if parsed is None else "mapped",
                }
            )
        metrics.sort(key=lambda item: item["metric_key"])
        if template:
            values = {m['metric_key']:m['value'] for m in metrics}
            numerator, denominator, rate = (values[k] for k in ('read_users','delivered_users','open_rate'))
            if numerator is not None and denominator is not None and numerator > denominator:
                raise MetricsIntakeError('template_denominator_mismatch', 'read_users exceeds delivered_users')
            if rate is not None and (numerator is None or denominator is None or denominator == 0 or abs(rate - numerator / denominator * 100) > 0.01):
                raise MetricsIntakeError('template_denominator_mismatch', 'open_rate requires read_users / delivered_users * 100')
        records.append(
            {
                "export_profile": export_profile,
                "platform": platform,
                "source_row": source_row,
                "source_grain": grain,
                "attribution_status": attribution,
                "content_label": compact_label(row.get(config.get("label_field"))) if config.get("label_field") else None,
                "observed_time": scalar_display(row.get(config["time_field"])),
                "metrics": metrics,
            }
        )
        if template:
            records[-1].update(compatibility_status='template_only', format_version=config['format_version'])
    return records


def semantic_warnings(export_profile: str, config: dict[str, Any], records: list[dict[str, Any]]) -> list[str]:
    found: list[str] = []
    if config.get('compatibility_status') == 'template_only':
        found.append(f'{export_profile}:template-only-not-verified-official-export')
    if config["source_grain"] == "account_day":
        found.append(f"{export_profile}:account-day-data-not-attributed-to-content")
    if config.get("unmapped_semantic_fields"):
        found.append(f"{export_profile}:non-percent-star-fields-retained-as-unmapped")
    for check in config.get("semantic_checks", []):
        values = [
            metric["value"]
            for record in records
            for metric in record["metrics"]
            if metric["metric_key"] == check["metric_key"] and metric["value"] is not None
        ]
        if check["condition"] == "all_zero" and values and all(value == 0 for value in values):
            found.append(f"{export_profile}:{check['warning']}")
            for record in records:
                for metric in record["metrics"]:
                    if metric["metric_key"] == check["metric_key"]:
                        metric["semantic_status"] = "requires-confirmation"
    return found


def parse_sources(values: list[str]) -> dict[str, Path]:
    mapping = load_json(MAPPING_PATH)
    profiles = mapping.get("export_profiles") or {}
    aliases = mapping.get("legacy_source_aliases") or {}
    parsed: dict[str, Path] = {}
    for value in values:
        supplied_profile, separator, raw_path = value.partition("=")
        export_profile = aliases.get(supplied_profile, supplied_profile)
        if not separator or export_profile not in profiles or not raw_path:
            raise MetricsIntakeError("source_argument_invalid", value)
        if export_profile in parsed:
            raise MetricsIntakeError("duplicate_export_profile_source", export_profile)
        parsed[export_profile] = Path(raw_path)
    return parsed


def build_intake(sources: dict[str, Path], captured_at: str) -> dict[str, Any]:
    try:
        parsed_time = datetime.fromisoformat(captured_at)
    except ValueError as error:
        raise MetricsIntakeError("captured_at_invalid", captured_at) from error
    if parsed_time.tzinfo is None:
        raise MetricsIntakeError("captured_at_invalid", "captured_at requires timezone")
    mapping = load_json(MAPPING_PATH)
    if mapping.get("schema_version") != "platform-metric-mappings.v1":
        raise MetricsIntakeError("mapping_version_drift", str(mapping.get("schema_version")))
    source_rows: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    found_warnings: list[str] = []
    profiles = mapping.get("export_profiles")
    if not isinstance(profiles, dict):
        raise MetricsIntakeError("mapping_profiles_missing", "export_profiles")
    for export_profile, path in sorted(sources.items()):
        config = profiles.get(export_profile)
        if not isinstance(config, dict):
            raise MetricsIntakeError("export_profile_mapping_missing", export_profile)
        platform = config.get("platform")
        if platform not in PLATFORMS:
            raise MetricsIntakeError("platform_mapping_invalid", str(platform))
        rows = read_rows(path, config)
        platform_records = normalize_records(export_profile, rows, config)
        records.extend(platform_records)
        found_warnings.extend(semantic_warnings(export_profile, config, platform_records))
        grain = config["source_grain"]
        source_rows.append(
            {
                "export_profile": export_profile,
                "platform": platform,
                "basename": path.name,
                "sha256": sha256_file(path),
                "source_grain": grain,
                "attribution_status": "direct-platform-item" if grain == "content_item" else "not-attributed-to-content",
                "header_row": config["header_row"],
                "row_count": len(platform_records),
            }
        )
        if config.get('compatibility_status') == 'template_only':
            source_rows[-1].update(compatibility_status='template_only', format_version=config['format_version'])
    seed = {"captured_at": captured_at, "mapping_sha256": sha256_file(MAPPING_PATH), "sources": source_rows}
    payload: dict[str, Any] = {
        "schema_version": "platform-metrics-intake.v1",
        "intake_id": "metrics-intake-" + hashlib.sha256(canonical_bytes(seed)).hexdigest()[:24],
        "captured_at": captured_at,
        "mapping_version": "platform-metric-mappings.v1",
        "sources": source_rows,
        "records": records,
        "warnings": sorted(set(found_warnings)),
        "boundaries": BOUNDARIES,
    }
    payload["payload_sha256"] = hashlib.sha256(canonical_bytes(payload)).hexdigest()
    validate_intake(payload)
    return payload


def validate_intake(value: dict[str, Any]) -> None:
    schema = load_json(SCHEMA_PATH)
    Draft202012Validator.check_schema(schema)
    errors = list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(value))
    if errors:
        raise MetricsIntakeError("schema_validation_failed", errors[0].message)
    unsigned = copy.deepcopy(value)
    digest = unsigned.pop("payload_sha256")
    if hashlib.sha256(canonical_bytes(unsigned)).hexdigest() != digest:
        raise MetricsIntakeError("payload_hash_drift", "intake changed after normalization")
    if any(item["source_grain"] == "account_day" and item["attribution_status"] != "not-attributed-to-content" for item in value["records"]):
        raise MetricsIntakeError("content_attribution_inferred", "account-day exports cannot be assigned to a content item")
    for item in value['sources'] + value['records']:
        if item['platform']=='wechat_official_account' and (item.get('compatibility_status')!='template_only' or item.get('format_version')!='wechat-account-day-template.v1' or item['source_grain']!='account_day' or item.get('content_label') is not None):
            raise MetricsIntakeError('template_authority_drift', 'WeChat official-account input remains template_only and account_day')


def safe_output(path: Path) -> Path:
    resolved = path.resolve()
    if not any(resolved.is_relative_to(root.resolve()) for root in OUTPUT_ROOTS):
        raise MetricsIntakeError("output_path_prohibited", str(path))
    return resolved


def write_intake(path: Path, value: dict[str, Any]) -> None:
    resolved = safe_output(path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if resolved.exists() and resolved.read_text(encoding="utf-8") == encoded:
        return
    resolved.write_text(encoded, encoding="utf-8", newline="\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    import_parser = subparsers.add_parser("import")
    import_parser.add_argument("--source", action="append", required=True, help="export-profile=local-file; legacy five-platform aliases remain accepted")
    import_parser.add_argument("--captured-at", required=True)
    import_parser.add_argument("--output", type=Path, required=True)
    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("--input", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "import":
            value = build_intake(parse_sources(args.source), args.captured_at)
            write_intake(args.output, value)
            result = {"status": "created", "intake_id": value["intake_id"], "record_count": len(value["records"]), "warning_count": len(value["warnings"])}
        else:
            value = load_json(args.input)
            validate_intake(value)
            result = {"status": "passed", "intake_id": value["intake_id"]}
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except MetricsIntakeError as error:
        print(json.dumps({"status": "blocked", "code": error.code, "message": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
