#!/usr/bin/env python3
"""Bound self-media context without weakening evidence or review gates."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from jsonschema import Draft202012Validator, FormatChecker


SCHEMA_VERSION = "self-media-context-efficiency.v1"
DEFAULT_EXCLUDED_DIRS = {
    ".git",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    "__pycache__",
    "node_modules",
    "dist",
    "build",
    "coverage",
    "outputs",
    "logs",
    "tmp",
    "temp",
}
DEFAULT_TEXT_EXTENSIONS = {
    ".css",
    ".csv",
    ".html",
    ".js",
    ".json",
    ".jsx",
    ".md",
    ".mjs",
    ".py",
    ".ps1",
    ".scss",
    ".svg",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".yaml",
    ".yml",
}
LOCKED_ROLES = {
    "fact_baseline",
    "approved_script",
    "user_correction",
    "privacy_authorization",
    "medical_insurance_boundary",
    "source_manifest",
}
ERROR_MARKERS = ("error", "failed", "failure", "exception", "traceback", "fatal")
ROUGH_CUT_WORKSPACE_V2 = "video_creation_pipeline.rough_cut_workspace.v2"
FFMPEG_OUTLET_ID = "video_creation_pipeline.single_ffmpeg_outlet"
MVP_VIDEO_REVIEW_POLICY_ID = "video-review-resource-guard-v1"
MVP_VIDEO_REVIEW_EXECUTION_RECEIPT_SCHEMA = (
    "video_creation_pipeline.video_review_execution_receipt.v1"
)
MVP_VIDEO_REVIEW_QA_REPORT_SCHEMA = "video_creation_pipeline.video_review_qa_report.v1"
EXECUTION_POLICY_REF = {
    "canonical_owner": FFMPEG_OUTLET_ID,
    "policy_id": MVP_VIDEO_REVIEW_POLICY_ID,
    "heavy_media_concurrency": 1,
    "full_decode_once_per": "exact_media_sha256_and_check_profile_sha256",
    "proxy_first": False,
    "limited_rework_scope": "changed_windows_only",
    "cached_report_analysis_parallel_allowed": True,
}
PROXY_PROFILE = {"enabled": False, "reason": "source_time_range_review"}
CHANGE_INVALIDATIONS = {
    "audio": {"asr", "subtitle_timing", "loudness", "privacy", "final_decode"},
    "timing": {"subtitle_timing", "motion_timing", "total_duration", "privacy", "final_decode"},
    "visual_source": {"rights", "keyframes", "privacy", "final_decode"},
    "mask": {"keyframes", "privacy", "final_decode"},
    "subtitle": {"subtitle_timing", "mobile_readability", "privacy", "final_decode"},
    "speed": {"asr", "subtitle_timing", "motion_timing", "loudness", "privacy", "final_decode"},
    "recompression": {"keyframes", "privacy", "final_decode"},
}
ROOT = Path(__file__).resolve().parents[1]


class ContextEfficiencyError(RuntimeError):
    """Fail-closed contract error."""


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def token_proxy(byte_count: int) -> int:
    """A deterministic size proxy, not a provider billing-token claim."""
    return math.ceil(byte_count / 4)


def validate_schema_file(value: Any, schema_name: str) -> None:
    schema_path = ROOT / "schemas" / schema_name
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(value), key=lambda error: list(error.path))
    if errors:
        raise ContextEfficiencyError(
            f"schema_validation_failed:{schema_name}:{errors[0].message}"
        )


def is_excluded(path: Path, root: Path, excluded_dirs: set[str]) -> bool:
    try:
        relative_parts = path.relative_to(root).parts[:-1]
    except ValueError:
        return True
    lowered = {part.lower() for part in relative_parts}
    return bool(lowered & excluded_dirs)


def iter_text_files(
    root: Path,
    excluded_dirs: set[str],
    extensions: set[str],
    max_files: int,
) -> Iterable[Path]:
    yielded = 0
    for path in root.rglob("*"):
        if yielded >= max_files:
            break
        if not path.is_file() or path.is_symlink():
            continue
        if is_excluded(path, root, excluded_dirs):
            continue
        if path.suffix.lower() not in extensions:
            continue
        yielded += 1
        yield path


def bounded_search(
    root: Path,
    query: str,
    output: Path,
    *,
    regex: bool = False,
    case_sensitive: bool = False,
    max_hits: int = 5000,
    max_files: int = 50000,
    max_file_bytes: int = 2_000_000,
    preview_count: int = 5,
    excluded_dirs: set[str] | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    if not root.is_dir():
        raise ContextEfficiencyError("search_root_missing")
    excluded_dirs = {item.lower() for item in (excluded_dirs or DEFAULT_EXCLUDED_DIRS)}
    flags = 0 if case_sensitive else re.IGNORECASE
    pattern = re.compile(query if regex else re.escape(query), flags)
    hits: list[dict[str, Any]] = []
    scanned_files = 0
    skipped_oversize = 0
    read_errors = 0
    truncated = False
    for path in iter_text_files(root, excluded_dirs, DEFAULT_TEXT_EXTENSIONS, max_files):
        scanned_files += 1
        try:
            if path.stat().st_size > max_file_bytes:
                skipped_oversize += 1
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            read_errors += 1
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            if not pattern.search(line):
                continue
            hits.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "line": line_number,
                    "preview": line.strip()[:240],
                }
            )
            if len(hits) >= max_hits:
                truncated = True
                break
        if truncated:
            break
    artifact = {
        "schema_version": SCHEMA_VERSION,
        "operation": "bounded_search",
        "root": root.as_posix(),
        "query_sha256": sha256_bytes(query.encode("utf-8")),
        "regex": regex,
        "case_sensitive": case_sensitive,
        "excluded_directories": sorted(excluded_dirs),
        "limits": {
            "max_hits": max_hits,
            "max_files": max_files,
            "max_file_bytes": max_file_bytes,
        },
        "summary": {
            "status": "refine_query_required" if truncated else "complete",
            "scanned_files": scanned_files,
            "hit_count": len(hits),
            "skipped_oversize_files": skipped_oversize,
            "read_errors": read_errors,
            "truncated": truncated,
        },
        "hits": hits,
    }
    artifact["artifact_sha256"] = sha256_bytes(canonical_json_bytes(artifact))
    write_json(output, artifact)
    return {
        **artifact["summary"],
        "artifact_path": output.resolve().as_posix(),
        "artifact_sha256": artifact["artifact_sha256"],
        "preview_hits": hits[:preview_count],
    }


def resolve_manifest_path(manifest_path: Path, relative_path: str) -> Path:
    candidate = Path(relative_path)
    if candidate.is_absolute():
        raise ContextEfficiencyError("absolute_artifact_path_prohibited")
    resolved = (manifest_path.parent / candidate).resolve()
    try:
        resolved.relative_to(manifest_path.parent.resolve())
    except ValueError as error:
        raise ContextEfficiencyError("artifact_path_escape_prohibited") from error
    return resolved


def build_context_pack(manifest_path: Path, output: Path) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    validate_schema_file(manifest, "context-input-manifest.v1.schema.json")
    if manifest.get("schema_version") != "self-media-context-input.v1":
        raise ContextEfficiencyError("manifest_schema_version_unsupported")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise ContextEfficiencyError("artifacts_required")
    budget = manifest.get("budget") or {}
    max_inline_bytes = int(budget.get("max_inline_bytes", 20000))
    if max_inline_bytes <= 0:
        raise ContextEfficiencyError("inline_budget_invalid")
    manifest_sha256 = sha256_file(manifest_path)
    rows: list[dict[str, Any]] = []
    seen_hashes: dict[str, str] = {}
    inline_bytes = 0
    reference_bytes = 0
    duplicate_bytes = 0
    for item in artifacts:
        if not isinstance(item, dict):
            raise ContextEfficiencyError("artifact_entry_invalid")
        role = str(item.get("role") or "").strip()
        load_mode = str(item.get("load_mode") or "").strip()
        relative_path = str(item.get("path") or "").strip()
        if load_mode not in {"inline", "reference", "on_failure"}:
            raise ContextEfficiencyError("load_mode_invalid")
        if role in LOCKED_ROLES and load_mode == "on_failure":
            raise ContextEfficiencyError("locked_role_cannot_be_on_failure")
        path = resolve_manifest_path(manifest_path, relative_path)
        if not path.is_file():
            raise ContextEfficiencyError("artifact_missing")
        size = path.stat().st_size
        digest = sha256_file(path)
        expected = str(item.get("expected_sha256") or "").strip()
        if role in LOCKED_ROLES and not expected:
            raise ContextEfficiencyError("locked_role_expected_sha256_required")
        if expected and expected != digest:
            raise ContextEfficiencyError("artifact_hash_drift")
        duplicate_of = seen_hashes.get(digest)
        if duplicate_of:
            duplicate_bytes += size
        else:
            seen_hashes[digest] = relative_path
            if load_mode == "inline":
                inline_bytes += size
            else:
                reference_bytes += size
        rows.append(
            {
                "artifact_id": item.get("artifact_id"),
                "role": role,
                "source_role": item.get("source_role"),
                "path": relative_path,
                "load_mode": load_mode,
                "sha256": digest,
                "bytes": size,
                "duplicate_of": duplicate_of,
                "fetch_condition": item.get("fetch_condition"),
            }
        )
    if inline_bytes > max_inline_bytes:
        raise ContextEfficiencyError("inline_budget_exceeded")
    prior_generated_at = None
    if output.is_file():
        try:
            prior = json.loads(output.read_text(encoding="utf-8"))
            prior_without_hash = dict(prior)
            prior_hash = prior_without_hash.pop("receipt_payload_sha256", None)
            if (
                prior.get("manifest_sha256") == manifest_sha256
                and prior_hash == sha256_bytes(canonical_json_bytes(prior_without_hash))
            ):
                prior_generated_at = prior.get("generated_at")
        except (OSError, ValueError, json.JSONDecodeError):
            prior_generated_at = None
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "operation": "build_context_pack",
        "manifest_sha256": manifest_sha256,
        "task_id": manifest.get("task_id"),
        "stage": manifest.get("stage"),
        "generated_at": prior_generated_at or utc_now(),
        "status": "ready",
        "budget": {
            "max_inline_bytes": max_inline_bytes,
            "inline_bytes": inline_bytes,
            "inline_token_proxy": token_proxy(inline_bytes),
            "reference_bytes": reference_bytes,
            "duplicate_bytes_avoided": duplicate_bytes,
        },
        "locked_roles": sorted(LOCKED_ROLES),
        "artifacts": rows,
        "boundaries": {
            "facts_removed": False,
            "privacy_or_authorization_removed": False,
            "automatic_publication": False,
            "full_logs_inline": False,
        },
    }
    receipt["receipt_payload_sha256"] = sha256_bytes(canonical_json_bytes(receipt))
    write_json(output, receipt)
    return receipt


def validate_context_pack(manifest_path: Path, receipt_path: Path) -> dict[str, Any]:
    """Recheck the manifest, receipt seal, and every referenced artifact without rewriting."""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    validate_schema_file(manifest, "context-input-manifest.v1.schema.json")
    receipt_without_hash = dict(receipt)
    expected = receipt_without_hash.pop("receipt_payload_sha256", None)
    if expected != sha256_bytes(canonical_json_bytes(receipt_without_hash)):
        raise ContextEfficiencyError("context_receipt_integrity_failed")
    if receipt.get("manifest_sha256") != sha256_file(manifest_path):
        raise ContextEfficiencyError("context_manifest_hash_drift")
    if receipt.get("task_id") != manifest.get("task_id") or receipt.get("stage") != manifest.get("stage"):
        raise ContextEfficiencyError("context_receipt_identity_drift")
    rows = receipt.get("artifacts")
    if not isinstance(rows, list) or len(rows) != len(manifest["artifacts"]):
        raise ContextEfficiencyError("context_receipt_artifact_count_drift")
    for item, row in zip(manifest["artifacts"], rows):
        path = resolve_manifest_path(manifest_path, item["path"])
        if not path.is_file() or sha256_file(path) != row.get("sha256"):
            raise ContextEfficiencyError("context_artifact_hash_drift")
        if (
            row.get("artifact_id") != item.get("artifact_id")
            or row.get("role") != item.get("role")
            or row.get("source_role") != item.get("source_role")
            or row.get("load_mode") != item.get("load_mode")
        ):
            raise ContextEfficiencyError("context_artifact_binding_drift")
    return receipt


def summarize_log(log_path: Path, output: Path | None, tail_lines: int = 30) -> dict[str, Any]:
    if not log_path.is_file():
        raise ContextEfficiencyError("log_missing")
    text = log_path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    error_indexes = [
        index for index, line in enumerate(lines) if any(marker in line.lower() for marker in ERROR_MARKERS)
    ]
    if error_indexes:
        pivot = error_indexes[-1]
        start = max(0, pivot - tail_lines)
        end = min(len(lines), pivot + tail_lines + 1)
        excerpt = lines[start:end]
    else:
        excerpt = lines[-tail_lines:]
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "operation": "summarize_log",
        "status": "error_detected" if error_indexes else "no_error_marker",
        "log_path": log_path.resolve().as_posix(),
        "log_sha256": sha256_file(log_path),
        "log_bytes": log_path.stat().st_size,
        "line_count": len(lines),
        "error_marker_count": len(error_indexes),
        "excerpt": excerpt,
        "full_log_inlined": False,
    }
    if output:
        write_json(output, receipt)
        receipt["receipt_path"] = output.resolve().as_posix()
    return receipt


def decide_asr(audio_path: Path, previous_path: Path | None, output: Path, changed_windows: list[str]) -> dict[str, Any]:
    if not audio_path.is_file():
        raise ContextEfficiencyError("audio_missing")
    current_hash = sha256_file(audio_path)
    previous_hash = None
    if previous_path:
        previous = json.loads(previous_path.read_text(encoding="utf-8"))
        previous_hash = previous.get("audio_sha256")
    if previous_hash == current_hash:
        decision = "reuse_existing_asr"
        reason = "audio_sha256_unchanged"
    elif changed_windows:
        decision = "rerun_changed_windows_with_context"
        reason = "audio_changed_and_windows_declared"
    else:
        decision = "rerun_full_asr"
        reason = "audio_changed_without_safe_window_boundary"
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "operation": "decide_asr",
        "status": "ready",
        "audio_path": audio_path.resolve().as_posix(),
        "audio_sha256": current_hash,
        "previous_audio_sha256": previous_hash,
        "decision": decision,
        "reason": reason,
        "changed_windows": changed_windows,
        "context_padding_seconds": 2 if changed_windows else None,
        "transcript_truth_authority_changed": False,
    }
    write_json(output, receipt)
    return receipt


def _finite_number(value: Any, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise ContextEfficiencyError(f"{label}_invalid") from error
    if not math.isfinite(number):
        raise ContextEfficiencyError(f"{label}_invalid")
    return number


def _artifact_from_manifest(manifest_path: Path, item: Any, label: str) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise ContextEfficiencyError(f"{label}_artifact_invalid")
    relative_path = str(item.get("path") or "").strip()
    expected = str(item.get("expected_sha256") or "").strip()
    if not relative_path or len(expected) != 64:
        raise ContextEfficiencyError(f"{label}_artifact_binding_required")
    path = resolve_manifest_path(manifest_path, relative_path)
    if not path.is_file():
        raise ContextEfficiencyError(f"{label}_artifact_missing")
    actual = sha256_file(path)
    if actual != expected:
        raise ContextEfficiencyError(f"{label}_artifact_hash_drift")
    return {"path": relative_path, "sha256": actual, "bytes": path.stat().st_size}


def _normalize_windows(values: Any, duration: float, label: str) -> list[dict[str, Any]]:
    if not isinstance(values, list):
        raise ContextEfficiencyError(f"{label}_windows_invalid")
    normalized: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for row in values:
        if not isinstance(row, dict):
            raise ContextEfficiencyError(f"{label}_window_invalid")
        window_id = str(row.get("window_id") or "").strip()
        start = _finite_number(row.get("start_seconds"), f"{label}_window_start")
        end = _finite_number(row.get("end_seconds"), f"{label}_window_end")
        if not window_id or window_id in seen_ids or start < 0 or end <= start or end > duration:
            raise ContextEfficiencyError(f"{label}_window_invalid")
        seen_ids.add(window_id)
        normalized.append(
            {
                "window_id": window_id,
                "start_seconds": round(start, 3),
                "end_seconds": round(end, 3),
                "reason": str(row.get("reason") or "").strip(),
            }
        )
    normalized.sort(key=lambda item: (item["start_seconds"], item["end_seconds"]))
    for left, right in zip(normalized, normalized[1:]):
        if right["start_seconds"] < left["end_seconds"]:
            raise ContextEfficiencyError(f"{label}_windows_overlap")
    return normalized


def _inside_any_window(timestamp: float, windows: list[dict[str, Any]]) -> bool:
    return any(row["start_seconds"] <= timestamp <= row["end_seconds"] for row in windows)


def _review_timecode(seconds: float) -> str:
    milliseconds = int(round(seconds * 1000))
    minutes, remainder = divmod(milliseconds, 60_000)
    whole_seconds, millis = divmod(remainder, 1000)
    return f"{minutes:02d}:{whole_seconds:02d}.{millis:03d}"


def _human_review_lane(change_kinds: list[str]) -> tuple[str, str]:
    groups: set[str] = set()
    for kind in change_kinds:
        if kind in {"audio", "speed"}:
            groups.add("audio")
        elif kind == "subtitle":
            groups.add("subtitle")
        elif kind == "mask":
            groups.add("privacy")
        elif kind in {"visual_source", "recompression"}:
            groups.add("picture")
        else:
            groups.add("mixed")
    lane = next(iter(groups)) if len(groups) == 1 else "mixed"
    playback = {
        "audio": "audio_only",
        "picture": "muted",
        "privacy": "frame_step",
    }.get(lane, "normal")
    return lane, playback


def _build_human_review_requests(
    *,
    mode: str,
    duration: float,
    source_sha256: str,
    changed_windows: list[dict[str, Any]],
    change_kinds: list[str],
) -> list[dict[str, Any]]:
    if mode == "initial_review":
        return [
            {
                "review_id": "human-full-candidate",
                "source_window_id": "full-candidate",
                "artifact_sha256": source_sha256,
                "issue_start_seconds": 0.0,
                "issue_end_seconds": round(duration, 3),
                "review_start_seconds": 0.0,
                "review_end_seconds": round(duration, 3),
                "timecode_start": _review_timecode(0),
                "timecode_end": _review_timecode(duration),
                "workflow_stage": "final_publication_review",
                "review_lane": "publication",
                "review_purpose": "final audience review of the exact candidate hash",
                "review_question": "Does the exact final candidate communicate naturally and safely as a whole?",
                "playback_mode": "normal",
                "review_access_mode": "source_time_range",
                "decision_options": ["pass", "needs_rework", "uncertain"],
            }
        ]

    lane, playback = _human_review_lane(change_kinds)
    requests: list[dict[str, Any]] = []
    for window in changed_windows:
        issue_start = window["start_seconds"]
        issue_end = window["end_seconds"]
        padded_start = max(0.0, issue_start - 2.0)
        padded_end = min(duration, issue_end + 3.0)
        part_start = padded_start
        part = 1
        while part_start < padded_end:
            part_end = min(padded_end, part_start + 15.0)
            review_id = f"human-{window['window_id']}-part{part:02d}"
            requests.append(
                {
                    "review_id": review_id,
                    "source_window_id": window["window_id"],
                    "artifact_sha256": source_sha256,
                    "issue_start_seconds": issue_start,
                    "issue_end_seconds": issue_end,
                    "review_start_seconds": round(part_start, 3),
                    "review_end_seconds": round(part_end, 3),
                    "timecode_start": _review_timecode(part_start),
                    "timecode_end": _review_timecode(part_end),
                    "workflow_stage": "limited_rework_acceptance",
                    "review_lane": lane,
                    "review_purpose": window["reason"],
                    "review_question": window["reason"],
                    "playback_mode": playback,
                    "review_access_mode": "source_time_range",
                    "decision_options": ["pass", "needs_rework", "uncertain"],
                }
            )
            part_start = part_end
            part += 1
    return requests


def build_video_review_plan(manifest_path: Path, output: Path) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    validate_schema_file(manifest, "video-review-input.v1.schema.json")
    if manifest.get("schema_version") != "self-media-video-review-input.v1":
        raise ContextEfficiencyError("video_review_manifest_schema_unsupported")
    task_id = str(manifest.get("task_id") or "").strip()
    mode = str(manifest.get("mode") or "").strip()
    if not task_id or mode not in {"initial_review", "limited_rework"}:
        raise ContextEfficiencyError("video_review_identity_invalid")

    source = _artifact_from_manifest(manifest_path, manifest.get("source_media"), "source_media")
    duration = _finite_number((manifest.get("source_media") or {}).get("duration_seconds"), "source_duration")
    if duration <= 0:
        raise ContextEfficiencyError("source_duration_invalid")
    source["duration_seconds"] = round(duration, 3)
    decision_sheet = _artifact_from_manifest(
        manifest_path, manifest.get("decision_sheet"), "decision_sheet"
    )
    rough_cut = _artifact_from_manifest(
        manifest_path, manifest.get("rough_cut_workspace"), "rough_cut_workspace"
    )
    rough_cut_payload = json.loads(
        resolve_manifest_path(manifest_path, rough_cut["path"]).read_text(encoding="utf-8")
    )
    if rough_cut_payload.get("schema") != ROUGH_CUT_WORKSPACE_V2:
        raise ContextEfficiencyError("rough_cut_workspace_v2_required")
    rough_cut["schema"] = ROUGH_CUT_WORKSPACE_V2

    changed = _normalize_windows(manifest.get("changed_windows", []), duration, "changed")
    frozen = _normalize_windows(manifest.get("frozen_windows", []), duration, "frozen")
    if mode == "initial_review" and (changed or frozen):
        raise ContextEfficiencyError("initial_review_must_cover_full_timeline")
    if mode == "limited_rework" and (not changed or not frozen):
        raise ContextEfficiencyError("limited_rework_requires_changed_and_frozen_windows")
    for changed_row in changed:
        if any(
            changed_row["start_seconds"] < frozen_row["end_seconds"]
            and frozen_row["start_seconds"] < changed_row["end_seconds"]
            for frozen_row in frozen
        ):
            raise ContextEfficiencyError("changed_and_frozen_windows_overlap")

    acceptance_values = manifest.get("acceptance_frame_timestamps")
    if not isinstance(acceptance_values, list) or not 3 <= len(acceptance_values) <= 5:
        raise ContextEfficiencyError("acceptance_frames_must_be_three_to_five")
    acceptance = [round(_finite_number(value, "acceptance_frame_timestamp"), 3) for value in acceptance_values]
    if len(set(acceptance)) != len(acceptance) or any(value < 0 or value > duration for value in acceptance):
        raise ContextEfficiencyError("acceptance_frame_timestamp_invalid")
    acceptance.sort()
    if mode == "limited_rework" and any(not _inside_any_window(value, changed) for value in acceptance):
        raise ContextEfficiencyError("acceptance_frames_must_target_changed_windows")

    kinds = manifest.get("change_kinds") or []
    if not isinstance(kinds, list) or any(value not in CHANGE_INVALIDATIONS for value in kinds):
        raise ContextEfficiencyError("change_kinds_invalid")
    if mode == "limited_rework" and not kinds:
        raise ContextEfficiencyError("limited_rework_change_kinds_required")
    if mode == "initial_review" and kinds:
        raise ContextEfficiencyError("initial_review_change_kinds_prohibited")
    invalidations = sorted({gate for kind in kinds for gate in CHANGE_INVALIDATIONS[kind]})
    human_review_requests = _build_human_review_requests(
        mode=mode,
        duration=duration,
        source_sha256=source["sha256"],
        changed_windows=changed,
        change_kinds=kinds,
    )

    plan = {
        "schema_version": "self-media-video-review-plan.v1",
        "plan_id": f"review-{task_id}",
        "task_id": task_id,
        "mode": mode,
        "inputs": {
            "source_media": source,
            "decision_sheet": decision_sheet,
            "rough_cut_workspace": rough_cut,
        },
        "review_scope": {
            "render_scope": "full_timeline_source" if mode == "initial_review" else "changed_windows_only",
            "changed_windows": changed,
            "frozen_windows": frozen,
            "acceptance_frame_timestamps": acceptance,
            "change_kinds": sorted(set(kinds)),
        },
        "human_review_requests": human_review_requests,
        "review_interface": {
            "tool_id": "video-knowledge-pipeline",
            "surface": "targeted-review",
            "delivery": "source_time_range_manifest",
        },
        "loading_strategy": {
            "proxy_first": False,
            "full_resolution_inline": True,
            "full_resolution_load_condition": "source_time_range_review",
        },
        "proxy_profile": dict(PROXY_PROFILE),
        "owner_binding": {
            "tool_id": "mvp-video-pipeline",
            "rough_cut_contract": ROUGH_CUT_WORKSPACE_V2,
            "material_cli": "video-material-workflow",
            "ffmpeg_outlet": FFMPEG_OUTLET_ID,
            "execution_authority": "explicit_executor_handoff_required",
        },
        "execution_policy_ref": dict(EXECUTION_POLICY_REF),
        "downstream_invalidations": invalidations,
        "required_checks": [
            "source_full_decode",
            "acceptance_frames_reviewed",
            "privacy_candidate_review",
            "normal_speed_human_review",
            "final_candidate_full_qa_after_source_review",
        ],
        "authority_boundary": {
            "plan_only": True,
            "media_rendered": False,
            "final_candidate_approved": False,
            "automatic_publish": False,
            "second_ffmpeg_orchestrator_created": False,
        },
    }
    plan["plan_payload_sha256"] = sha256_bytes(canonical_json_bytes(plan))
    validate_schema_file(plan, "video-review-plan.v1.schema.json")
    write_json(output, plan)
    return plan


def _verify_receipt_artifact(receipt_path: Path, item: Any, label: str) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise ContextEfficiencyError(f"{label}_receipt_artifact_invalid")
    relative_path = str(item.get("path") or "").strip()
    expected = str(item.get("sha256") or "").strip()
    path = resolve_manifest_path(receipt_path, relative_path)
    if not path.is_file() or len(expected) != 64 or sha256_file(path) != expected:
        raise ContextEfficiencyError(f"{label}_receipt_artifact_drift")
    return {"path": relative_path, "sha256": expected, "bytes": path.stat().st_size}


def _load_receipt_json_artifact(
    receipt_path: Path, item: Any, label: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    artifact = _verify_receipt_artifact(receipt_path, item, label)
    path = resolve_manifest_path(receipt_path, artifact["path"])
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ContextEfficiencyError(f"{label}_receipt_artifact_invalid")
    return artifact, payload


def _verify_mvp_payload_seal(payload: dict[str, Any], field: str, label: str) -> None:
    expected = payload.get(field)
    without_hash = dict(payload)
    without_hash.pop(field, None)
    if expected != sha256_bytes(canonical_json_bytes(without_hash)):
        raise ContextEfficiencyError(f"{label}_integrity_failed")


def verify_video_review_receipt(plan_path: Path, receipt_path: Path, output: Path) -> dict[str, Any]:
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if "execution_policy_ref" not in plan:
        raise ContextEfficiencyError("video_review_execution_policy_required")
    if not receipt.get("candidate_media_sha256"):
        raise ContextEfficiencyError("video_review_candidate_hash_required")
    if "execution_policy_ref" not in receipt:
        raise ContextEfficiencyError("video_review_execution_policy_required")
    evidence = receipt.get("mvp_execution_evidence")
    if not isinstance(evidence, dict) or not evidence.get("execution_receipt"):
        raise ContextEfficiencyError("video_review_mvp_execution_receipt_required")
    validate_schema_file(plan, "video-review-plan.v1.schema.json")
    validate_schema_file(receipt, "video-review-execution-receipt.v1.schema.json")
    if plan.get("schema_version") != "self-media-video-review-plan.v1":
        raise ContextEfficiencyError("video_review_plan_schema_unsupported")
    expected_plan_hash = plan.get("plan_payload_sha256")
    plan_without_hash = dict(plan)
    plan_without_hash.pop("plan_payload_sha256", None)
    if expected_plan_hash != sha256_bytes(canonical_json_bytes(plan_without_hash)):
        raise ContextEfficiencyError("video_review_plan_integrity_failed")
    if receipt.get("schema_version") != "self-media-video-review-execution-receipt.v1":
        raise ContextEfficiencyError("video_review_receipt_schema_unsupported")
    expected_receipt_hash = receipt.get("receipt_payload_sha256")
    receipt_without_hash = dict(receipt)
    receipt_without_hash.pop("receipt_payload_sha256", None)
    if expected_receipt_hash != sha256_bytes(canonical_json_bytes(receipt_without_hash)):
        raise ContextEfficiencyError("video_review_receipt_integrity_failed")
    if receipt.get("plan_payload_sha256") != expected_plan_hash:
        raise ContextEfficiencyError("video_review_receipt_plan_drift")
    if (
        plan.get("execution_policy_ref") != EXECUTION_POLICY_REF
        or receipt.get("execution_policy_ref") != EXECUTION_POLICY_REF
    ):
        raise ContextEfficiencyError("video_review_execution_policy_invalid")
    candidate_sha256 = plan.get("inputs", {}).get("source_media", {}).get("sha256")
    if not candidate_sha256 or receipt.get("candidate_media_sha256") != candidate_sha256:
        raise ContextEfficiencyError("video_review_candidate_hash_drift")
    if receipt.get("executor_tool_id") != "mvp-video-pipeline" or receipt.get("ffmpeg_outlet") != FFMPEG_OUTLET_ID:
        raise ContextEfficiencyError("video_review_owner_binding_invalid")
    scope = receipt.get("rendered_scope") or {}
    plan_scope = plan["review_scope"]
    if scope.get("render_scope") != plan_scope["render_scope"]:
        raise ContextEfficiencyError("video_review_render_scope_drift")
    if scope.get("changed_window_ids") != [row["window_id"] for row in plan_scope["changed_windows"]]:
        raise ContextEfficiencyError("video_review_changed_window_drift")
    if receipt.get("proxy_profile") != plan.get("proxy_profile"):
        raise ContextEfficiencyError("video_review_proxy_profile_drift")

    _, execution = _load_receipt_json_artifact(
        receipt_path, evidence.get("execution_receipt"), "mvp_execution_receipt"
    )
    if execution.get("schema") != MVP_VIDEO_REVIEW_EXECUTION_RECEIPT_SCHEMA:
        raise ContextEfficiencyError("video_review_mvp_execution_receipt_schema_invalid")
    _verify_mvp_payload_seal(execution, "receipt_sha256", "mvp_execution_receipt")
    for field in ("status", "disposition", "media_sha256", "check_profile_sha256", "cache_key"):
        if execution.get(field) != evidence.get(field):
            raise ContextEfficiencyError(f"video_review_mvp_{field}_drift")
    expected_cache_key = sha256_bytes(
        canonical_json_bytes(
            {
                "media_sha256": evidence.get("media_sha256"),
                "check_profile_sha256": evidence.get("check_profile_sha256"),
            }
        )
    )
    if (
        evidence.get("media_sha256") != candidate_sha256
        or evidence.get("cache_key")
        != expected_cache_key
        or execution.get("automatic_retry") is not False
        or evidence.get("automatic_retry") is not False
        or (execution.get("resource_guard") or {}).get("policy_id")
        != MVP_VIDEO_REVIEW_POLICY_ID
    ):
        raise ContextEfficiencyError("video_review_mvp_execution_policy_invalid")

    status = receipt.get("status")
    if status == "blocked":
        if (
            evidence.get("status") != "blocked"
            or evidence.get("disposition") != "not_run"
            or evidence.get("reason") != "resource_pressure_pause_required"
            or execution.get("reason") != "resource_pressure_pause_required"
            or execution.get("qa_report") is not None
        ):
            raise ContextEfficiencyError("video_review_resource_block_invalid")
        verification = {
            "schema_version": "self-media-video-review-verification.v1",
            "status": "verified_blocked",
            "task_id": plan["task_id"],
            "plan_payload_sha256": expected_plan_hash,
            "receipt_payload_sha256": expected_receipt_hash,
            "final_candidate_render_allowed": False,
            "full_final_qa_required": True,
            "downstream_gates_to_rerun": plan["downstream_invalidations"],
            "publication_boundary": "manual_only",
            "automatic_retry": False,
        }
        verification["verification_payload_sha256"] = sha256_bytes(
            canonical_json_bytes(verification)
        )
        write_json(output, verification)
        return verification

    if evidence.get("status") != "completed" or execution.get("status") != "completed":
        raise ContextEfficiencyError("video_review_mvp_execution_incomplete")
    resource_decision = (execution.get("resource_guard") or {}).get("decision")
    if evidence.get("disposition") == "performed" and (
        evidence.get("reusable_evidence_available") is True
        or resource_decision == "cache_reused"
    ):
        raise ContextEfficiencyError("video_review_reusable_full_decode_repeated")
    if evidence.get("disposition") == "reused" and (
        evidence.get("reusable_evidence_available") is not True
        or resource_decision != "cache_reused"
        or not isinstance(execution.get("cache_receipt"), dict)
    ):
        raise ContextEfficiencyError("video_review_reuse_evidence_missing")
    qa_artifact, qa_report = _load_receipt_json_artifact(
        receipt_path, evidence.get("qa_report"), "mvp_qa_report"
    )
    if qa_report.get("schema") != MVP_VIDEO_REVIEW_QA_REPORT_SCHEMA:
        raise ContextEfficiencyError("video_review_mvp_qa_report_schema_invalid")
    _verify_mvp_payload_seal(qa_report, "report_sha256", "mvp_qa_report")
    for field in ("media_sha256", "check_profile_sha256", "cache_key"):
        if qa_report.get(field) != evidence.get(field):
            raise ContextEfficiencyError(f"video_review_mvp_qa_{field}_drift")
    execution_qa_ref = execution.get("qa_report") or {}
    if execution_qa_ref.get("sha256") != qa_artifact["sha256"]:
        raise ContextEfficiencyError("video_review_mvp_qa_receipt_binding_drift")
    qa_scope = qa_report.get("scope") or {}
    execution_scope = execution.get("scope") or {}
    if qa_scope != execution_scope or qa_scope.get("render_scope") != plan_scope["render_scope"]:
        raise ContextEfficiencyError("video_review_mvp_scope_drift")
    if qa_scope.get("changed_windows") != plan_scope["changed_windows"]:
        raise ContextEfficiencyError("video_review_mvp_changed_window_drift")
    if plan.get("mode") == "limited_rework":
        if qa_scope.get("full_timeline_scanned") is not False:
            raise ContextEfficiencyError("video_review_limited_rework_full_scan_prohibited")
        commands = qa_report.get("commands")
        expected_ids = {row["window_id"] for row in plan_scope["changed_windows"]}
        if (
            not isinstance(commands, list)
            or {row.get("window_id") for row in commands if isinstance(row, dict)} != expected_ids
            or any(
                not isinstance(row, dict)
                or not isinstance(row.get("command"), list)
                or "-ss" not in row["command"]
                or "-t" not in row["command"]
                for row in commands
            )
        ):
            raise ContextEfficiencyError("video_review_limited_rework_scan_scope_invalid")
    elif qa_scope.get("full_timeline_scanned") is not True:
        raise ContextEfficiencyError("video_review_initial_full_scan_evidence_required")

    artifacts = receipt.get("artifacts") or {}
    source_ref = _verify_receipt_artifact(receipt_path, artifacts.get("source_media"), "source_media")
    if (source_ref["sha256"] != candidate_sha256 or
        resolve_manifest_path(receipt_path, source_ref["path"]) !=
        resolve_manifest_path(plan_path, plan["inputs"]["source_media"]["path"])):
        raise ContextEfficiencyError("review_must_reference_original_source_not_proxy")
    _verify_receipt_artifact(receipt_path, artifacts.get("execution_log"), "execution_log")
    frames = artifacts.get("acceptance_frames")
    if not isinstance(frames, list) or [row.get("timestamp_seconds") for row in frames if isinstance(row, dict)] != plan_scope["acceptance_frame_timestamps"]:
        raise ContextEfficiencyError("acceptance_frame_binding_drift")
    for index, frame in enumerate(frames):
        _verify_receipt_artifact(receipt_path, frame, f"acceptance_frame_{index}")

    expected_requests = plan.get("human_review_requests") or []
    expected_request_ids = [row["review_id"] for row in expected_requests]
    clip_requests = [row for row in expected_requests if row.get("review_access_mode") == "independent_clip"]
    review_clips = artifacts.get("human_review_clips", [])
    if not isinstance(review_clips, list) or [row.get("review_id") for row in review_clips if isinstance(row, dict)] != [row["review_id"] for row in clip_requests]:
        raise ContextEfficiencyError("human_review_clip_binding_drift")
    for index, (clip, request) in enumerate(zip(review_clips, clip_requests)):
        _verify_receipt_artifact(receipt_path, clip, f"human_review_clip_{index}")
        if (
            clip.get("start_seconds") != request["review_start_seconds"]
            or clip.get("end_seconds") != request["review_end_seconds"]
        ):
            raise ContextEfficiencyError("human_review_clip_range_drift")

    status = receipt.get("status")
    if status not in {"pass", "limited_rework", "reject"}:
        raise ContextEfficiencyError("video_review_status_invalid")
    checks = receipt.get("checks") or {}
    required_checks = {
        "source_full_decode_passed",
        "acceptance_frames_reviewed",
        "privacy_candidate_reviewed",
        "normal_speed_human_reviewed",
    }
    if set(checks) != required_checks or any(not isinstance(value, bool) for value in checks.values()):
        raise ContextEfficiencyError("video_review_checks_invalid")
    human = receipt.get("human_review") or {}
    results = human.get("request_results")
    if not isinstance(results, list) or [row.get("review_id") for row in results if isinstance(row, dict)] != expected_request_ids:
        raise ContextEfficiencyError("human_review_result_binding_drift")
    if any(row.get("decision") not in {"pass", "needs_rework", "uncertain"} for row in results):
        raise ContextEfficiencyError("human_review_result_invalid")
    if status == "pass" and (not all(checks.values()) or human.get("confirmed") is not True):
        raise ContextEfficiencyError("video_review_pass_requires_human_confirmation")
    if status == "pass" and any(row.get("decision") != "pass" for row in results):
        raise ContextEfficiencyError("video_review_pass_requires_all_requests_passed")
    boundary = receipt.get("authority_boundary") or {}
    if (
        boundary.get("final_candidate_rendered") is not False
        or boundary.get("automatic_publish") is not False
        or boundary.get("full_log_inlined") is not False
    ):
        raise ContextEfficiencyError("video_review_receipt_boundary_invalid")

    verification = {
        "schema_version": "self-media-video-review-verification.v1",
        "status": f"verified_{status}",
        "task_id": plan["task_id"],
        "plan_payload_sha256": expected_plan_hash,
        "receipt_payload_sha256": expected_receipt_hash,
        "final_candidate_render_allowed": status == "pass",
        "full_final_qa_required": True,
        "downstream_gates_to_rerun": plan["downstream_invalidations"],
        "publication_boundary": "manual_only",
    }
    verification["verification_payload_sha256"] = sha256_bytes(canonical_json_bytes(verification))
    write_json(output, verification)
    return verification


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    search = subparsers.add_parser("search", help="Bound a local text search and write full hits to disk.")
    search.add_argument("--root", type=Path, required=True)
    search.add_argument("--query", required=True)
    search.add_argument("--output", type=Path, required=True)
    search.add_argument("--regex", action="store_true")
    search.add_argument("--case-sensitive", action="store_true")
    search.add_argument("--max-hits", type=int, default=5000)
    search.add_argument("--max-files", type=int, default=50000)
    search.add_argument("--max-file-bytes", type=int, default=2_000_000)
    search.add_argument("--preview-count", type=int, default=5)

    pack = subparsers.add_parser("pack", help="Validate a compact context loading manifest.")
    pack.add_argument("--manifest", type=Path, required=True)
    pack.add_argument("--output", type=Path, required=True)

    logs = subparsers.add_parser("summarize-log", help="Return only a bounded diagnostic excerpt.")
    logs.add_argument("--log", type=Path, required=True)
    logs.add_argument("--output", type=Path)
    logs.add_argument("--tail-lines", type=int, default=30)

    asr = subparsers.add_parser("decide-asr", help="Reuse ASR only when the audio hash is unchanged.")
    asr.add_argument("--audio", type=Path, required=True)
    asr.add_argument("--previous-receipt", type=Path)
    asr.add_argument("--output", type=Path, required=True)
    asr.add_argument("--changed-window", action="append", default=[])

    video_plan = subparsers.add_parser(
        "plan-video-review", help="Bind proxy review and limited rework to the existing video owner."
    )
    video_plan.add_argument("--manifest", type=Path, required=True)
    video_plan.add_argument("--output", type=Path, required=True)

    video_verify = subparsers.add_parser(
        "verify-video-review", help="Verify the executor receipt before final candidate rendering."
    )
    video_verify.add_argument("--plan", type=Path, required=True)
    video_verify.add_argument("--receipt", type=Path, required=True)
    video_verify.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    # Keep compact receipts readable when Windows inherits a legacy console code page.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    args = parse_args()
    try:
        if args.command == "search":
            result = bounded_search(
                args.root,
                args.query,
                args.output,
                regex=args.regex,
                case_sensitive=args.case_sensitive,
                max_hits=args.max_hits,
                max_files=args.max_files,
                max_file_bytes=args.max_file_bytes,
                preview_count=args.preview_count,
            )
        elif args.command == "pack":
            result = build_context_pack(args.manifest, args.output)
        elif args.command == "summarize-log":
            result = summarize_log(args.log, args.output, args.tail_lines)
        elif args.command == "decide-asr":
            result = decide_asr(args.audio, args.previous_receipt, args.output, args.changed_window)
        elif args.command == "plan-video-review":
            result = build_video_review_plan(args.manifest, args.output)
        else:
            result = verify_video_review_receipt(args.plan, args.receipt, args.output)
    except (ContextEfficiencyError, OSError, ValueError, json.JSONDecodeError, re.error) as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps({"ok": True, "result": result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
