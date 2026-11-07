#!/usr/bin/env python3
"""Manage self-media artifacts without inventing another renderer or media state machine.

The lifecycle owner keeps compact metadata, produces deterministic cleanup plans,
moves eligible files into a recoverable quarantine, and purges only after both a
retention deadline and explicit policy/artifact approval.  It never inspects media
content and never operates outside the supplied workspace root.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_SCHEMA = ROOT / "schemas" / "artifact-lifecycle-manifest.v2.schema.json"
RECEIPT_SCHEMA = ROOT / "schemas" / "artifact-lifecycle-operation-receipt.v1.schema.json"
ARCHIVE_POLICY = ROOT / "config" / "video-archive-policy.v1.json"
ARCHIVE_ASSESSMENT_SCHEMA = ROOT / "schemas" / "video-archive-assessment.v1.schema.json"
DEFAULT_CORE_ROOT = ROOT.parent / "artifact-lifecycle-core"
CORE_ROOT_ENV = "ARTIFACT_LIFECYCLE_CORE_ROOT"

PROTECTED_KINDS = {
    "raw_source",
    "reviewed_source",
    "fine_cut",
    "locked_master",
    "final",
    "recipe",
}
DISPOSABLE_KINDS = {"proxy", "cache", "frame_extract", "chunk", "browser_profile"}
QUARANTINE_ELIGIBLE = {"qa_fail", "superseded"}
STATUS_TRANSITIONS = {
    "created": {"candidate", "qa_pass", "qa_fail", "locked"},
    "candidate": {"qa_pass", "qa_fail", "locked", "superseded"},
    "qa_pass": {"qa_fail", "locked", "superseded"},
    "qa_fail": {"quarantine"},
    "locked": set(),
    "superseded": {"quarantine"},
    "quarantine": {"candidate", "qa_fail", "superseded", "purged"},
    "purged": set(),
}
DEFAULT_POLICY = {
    "large_file_threshold_bytes": 200 * 1024 * 1024,
    "task_intermediate_limit_bytes": 2 * 1024 * 1024 * 1024,
    "minimum_free_bytes": 512 * 1024 * 1024,
    "warning_free_bytes": 5 * 1024 * 1024 * 1024,
    "output_headroom_multiplier": 1.25,
    "keep_previous_review_versions": 1,
    "retention_hours": {
        "machine_failure": 24,
        "user_rejected": 72,
        "superseded": 72,
        "task_cache": 0,
    },
    "automatic_purge_authorized": False,
}


class LifecycleError(ValueError):
    """Stable fail-closed lifecycle error."""

    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code


def _load_shared_core(core_root: str | Path | None = None) -> Any:
    configured = core_root or os.environ.get(CORE_ROOT_ENV) or DEFAULT_CORE_ROOT
    root = Path(configured).expanduser().resolve()
    module_path = root / "artifact_lifecycle_core.py"
    if not module_path.is_file():
        raise LifecycleError("shared_core_missing", str(module_path))
    digest = hashlib.sha256(module_path.read_bytes()).hexdigest()
    spec = importlib.util.spec_from_file_location(
        f"self_media_artifact_lifecycle_core_{digest[:16]}", module_path
    )
    if spec is None or spec.loader is None:
        raise LifecycleError("shared_core_unloadable", str(module_path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    required = {"LifecycleError", "free_space_status", "read_json", "validate_profiles"}
    missing = sorted(name for name in required if not hasattr(module, name))
    if missing:
        raise LifecycleError("shared_core_incompatible", ",".join(missing))
    return module


def _media_profile(core: Any) -> dict[str, Any]:
    profile_path = (
        Path(core.__file__).resolve().parent
        / "profiles"
        / "artifact-lifecycle-profiles.v1.json"
    )
    try:
        payload = core.read_json(profile_path)
        errors = core.validate_profiles(payload)
    except (OSError, core.LifecycleError) as exc:
        code = getattr(exc, "code", type(exc).__name__)
        detail = getattr(exc, "detail", str(exc))
        raise LifecycleError("shared_media_profile_unreadable", f"{code}: {detail}") from exc
    if errors:
        raise LifecycleError("shared_media_profile_invalid", ";".join(errors))
    profile = next(
        (
            item
            for item in payload.get("profiles", [])
            if item.get("profile_id") == "media"
        ),
        None,
    )
    if profile is None or profile.get("large_output_preflight") is not True:
        raise LifecycleError("shared_media_profile_missing", str(profile_path))
    return {
        "profile_id": "media",
        "minimum_free_bytes": int(profile["minimum_free_bytes"]),
        "warning_free_bytes": int(profile["warning_free_bytes"]),
        "output_headroom_multiplier": float(profile["output_headroom_multiplier"]),
        "cleanup_mode": profile["cleanup_mode"],
        "automatic_purge": bool(profile["automatic_purge"]),
        "source": str(profile_path),
    }


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_now(value: str | None) -> datetime:
    if value is None:
        return _utc_now()
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise LifecycleError("invalid_time", value) from exc
    if parsed.tzinfo is None:
        raise LifecycleError("timezone_required", value)
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LifecycleError("json_unreadable", f"{path}: {exc}") from exc
    if not isinstance(value, dict):
        raise LifecycleError("json_object_required", str(path))
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_sha256(value: dict[str, Any]) -> str:
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _validate(value: dict[str, Any], schema_path: Path) -> None:
    schema = _read_json(schema_path)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(value), key=lambda item: list(item.path))
    if errors:
        first = errors[0]
        location = ".".join(str(item) for item in first.path) or "$"
        raise LifecycleError("schema_validation_failed", f"{location}: {first.message}")


def _write_json_atomic(path: Path, value: dict[str, Any], schema_path: Path | None = None) -> None:
    if schema_path is not None:
        _validate(value, schema_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(temporary, path)


def _resolve_under(root: Path, relative: str, *, must_exist: bool = False) -> Path:
    workspace = root.resolve()
    candidate = (workspace / Path(relative)).resolve()
    try:
        candidate.relative_to(workspace)
    except ValueError as exc:
        raise LifecycleError("path_escapes_workspace", relative) from exc
    if must_exist and not candidate.exists():
        raise LifecycleError("artifact_missing", relative)
    return candidate


def _relative(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise LifecycleError("path_escapes_workspace", str(path)) from exc


def _load_manifest(path: Path) -> dict[str, Any]:
    value = _read_json(path)
    _validate(value, MANIFEST_SCHEMA)
    return value


def _artifact_index(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    paths: set[str] = set()
    for artifact in manifest["artifacts"]:
        artifact_id = artifact["artifact_id"]
        if artifact_id in result:
            raise LifecycleError("duplicate_artifact_id", artifact_id)
        if artifact["status"] != "purged" and artifact["path"] in paths:
            raise LifecycleError("duplicate_live_path", artifact["path"])
        result[artifact_id] = artifact
        if artifact["status"] != "purged":
            paths.add(artifact["path"])
    for artifact in manifest["artifacts"]:
        unknown = [item for item in artifact["depends_on"] if item not in result]
        if unknown:
            raise LifecycleError("unknown_dependency", f"{artifact['artifact_id']}: {unknown}")
    return result


def _operation_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:16]}"


def _receipt(
    *,
    operation_id: str,
    operation: str,
    status: str,
    now: datetime,
    manifest_path: Path,
    before: str | None,
    after: str | None,
    mutated: bool,
    items: list[dict[str, Any]] | None = None,
    blocked: list[dict[str, Any]] | None = None,
    metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": "artifact-lifecycle-operation-receipt.v1",
        "operation_id": operation_id,
        "operation": operation,
        "status": status,
        "created_at": _iso(now),
        "manifest_path": str(manifest_path.resolve()),
        "manifest_sha256_before": before,
        "manifest_sha256_after": after,
        "filesystem_mutation_performed": mutated,
        "items": items or [],
        "blocked": blocked or [],
        "metrics": metrics or {},
    }


def _record_history(
    manifest: dict[str, Any], operation_id: str, now: datetime, action: str,
    artifact_ids: list[str], reason: str,
) -> None:
    manifest["history"].append(
        {
            "operation_id": operation_id,
            "at": _iso(now),
            "action": action,
            "artifact_ids": artifact_ids,
            "reason": reason,
        }
    )
    manifest["revision"] += 1
    manifest["updated_at"] = _iso(now)


def _retention_deadline(manifest: dict[str, Any], now: datetime, reason: str) -> str:
    key = "machine_failure"
    if reason == "user_rejected":
        key = "user_rejected"
    elif reason == "superseded":
        key = "superseded"
    elif reason == "task_cache":
        key = "task_cache"
    hours = manifest["policy"]["retention_hours"][key]
    return _iso(now + timedelta(hours=hours))


def init_manifest(args: argparse.Namespace) -> dict[str, Any]:
    manifest_path = Path(args.manifest)
    if manifest_path.exists():
        raise LifecycleError("manifest_already_exists", str(manifest_path))
    now = _parse_now(args.now)
    workspace_root = Path(args.workspace_root).resolve()
    workspace_root.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": "self-media-artifact-lifecycle-manifest.v2",
        "manifest_id": args.manifest_id,
        "revision": 0,
        "updated_at": _iso(now),
        "workspace_ref": args.workspace_ref or workspace_root.name,
        "quarantine_dir": args.quarantine_dir,
        "policy": DEFAULT_POLICY | {"automatic_purge_authorized": args.authorize_automatic_purge},
        "artifacts": [],
        "history": [],
    }
    _resolve_under(workspace_root, args.quarantine_dir)
    _write_json_atomic(manifest_path, manifest, MANIFEST_SCHEMA)
    return manifest


def register_artifact(args: argparse.Namespace) -> dict[str, Any]:
    manifest_path = Path(args.manifest)
    workspace_root = Path(args.workspace_root).resolve()
    manifest = _load_manifest(manifest_path)
    before = _json_sha256(manifest)
    by_id = _artifact_index(manifest)
    if args.artifact_id in by_id:
        raise LifecycleError("artifact_id_exists", args.artifact_id)
    unknown_dependencies = [item for item in (args.depends_on or []) if item not in by_id]
    if unknown_dependencies:
        raise LifecycleError("unknown_dependency", f"{args.artifact_id}: {unknown_dependencies}")
    source = _resolve_under(workspace_root, args.path, must_exist=True)
    if not source.is_file():
        raise LifecycleError("artifact_not_file", args.path)
    size = source.stat().st_size
    if size >= manifest["policy"]["large_file_threshold_bytes"] and not args.retain_reason:
        raise LifecycleError("large_artifact_reason_required", args.artifact_id)
    now = _parse_now(args.now)
    actual_sha256 = _sha256(source)
    source_sha256 = args.source_sha256 or actual_sha256
    if source_sha256 != actual_sha256:
        raise LifecycleError("source_hash_drift", args.artifact_id)
    artifact = {
        "artifact_id": args.artifact_id,
        "video_id": args.video_id,
        "path": _relative(workspace_root, source),
        "bytes": size,
        "artifact_kind": args.kind,
        "status": args.status,
        "source_sha256": source_sha256,
        "created_at": _iso(now),
        "updated_at": _iso(now),
        "superseded_by": None,
        "depends_on": args.depends_on or [],
        "referenced_by": args.referenced_by or [],
        "retain_reason": args.retain_reason,
        "failure_reason": args.failure_reason,
        "delete_after": None,
        "quarantine_path": None,
        "original_path": None,
        "purge_approved": args.approve_purge,
    }
    if artifact["artifact_kind"] in PROTECTED_KINDS and artifact["status"] in QUARANTINE_ELIGIBLE:
        raise LifecycleError("protected_kind_disposable_status", args.artifact_id)
    if artifact["status"] == "qa_fail":
        if not artifact["failure_reason"]:
            raise LifecycleError("failure_reason_required", args.artifact_id)
        artifact["delete_after"] = _retention_deadline(
            manifest, now, "user_rejected" if args.user_rejected else "machine_failure"
        )
    manifest["artifacts"].append(artifact)
    operation_id = _operation_id("register")
    _record_history(manifest, operation_id, now, "register", [args.artifact_id], args.retain_reason or "registered")
    _write_json_atomic(manifest_path, manifest, MANIFEST_SCHEMA)
    after = _json_sha256(manifest)
    return _receipt(
        operation_id=operation_id,
        operation="register",
        status="passed",
        now=now,
        manifest_path=manifest_path,
        before=before,
        after=after,
        mutated=False,
        items=[{"artifact_id": args.artifact_id, "path": artifact["path"], "bytes": size}],
    )


def transition_artifact(args: argparse.Namespace) -> dict[str, Any]:
    manifest_path = Path(args.manifest)
    manifest = _load_manifest(manifest_path)
    before = _json_sha256(manifest)
    by_id = _artifact_index(manifest)
    if args.artifact_id not in by_id:
        raise LifecycleError("artifact_unknown", args.artifact_id)
    artifact = by_id[args.artifact_id]
    old_status = artifact["status"]
    if args.status == old_status:
        now = _parse_now(args.now)
        return _receipt(
            operation_id=_operation_id("transition-noop"),
            operation="transition",
            status="passed",
            now=now,
            manifest_path=manifest_path,
            before=before,
            after=before,
            mutated=False,
            items=[{"artifact_id": args.artifact_id, "status": old_status, "idempotent": True}],
        )
    if args.status not in STATUS_TRANSITIONS[old_status]:
        raise LifecycleError("invalid_status_transition", f"{old_status} -> {args.status}")
    if artifact["artifact_kind"] in PROTECTED_KINDS and args.status in QUARANTINE_ELIGIBLE | {"quarantine", "purged"}:
        raise LifecycleError("protected_artifact_transition", args.artifact_id)
    if args.status == "qa_fail" and not args.reason:
        raise LifecycleError("failure_reason_required", args.artifact_id)
    if args.status == "superseded":
        if not args.superseded_by or args.superseded_by not in by_id:
            raise LifecycleError("superseding_artifact_required", args.artifact_id)
        artifact["superseded_by"] = args.superseded_by
    now = _parse_now(args.now)
    artifact["status"] = args.status
    artifact["updated_at"] = _iso(now)
    if args.status == "qa_fail":
        artifact["failure_reason"] = args.reason
        artifact["delete_after"] = _retention_deadline(
            manifest, now, "user_rejected" if args.user_rejected else "machine_failure"
        )
    elif args.status == "superseded":
        artifact["delete_after"] = _retention_deadline(manifest, now, "superseded")
    if args.approve_purge:
        artifact["purge_approved"] = True
    operation_id = _operation_id("transition")
    _record_history(manifest, operation_id, now, "transition", [args.artifact_id], args.reason)
    _write_json_atomic(manifest_path, manifest, MANIFEST_SCHEMA)
    return _receipt(
        operation_id=operation_id,
        operation="transition",
        status="passed",
        now=now,
        manifest_path=manifest_path,
        before=before,
        after=_json_sha256(manifest),
        mutated=False,
        items=[{"artifact_id": args.artifact_id, "from": old_status, "to": args.status}],
    )


def lock_artifact(args: argparse.Namespace) -> dict[str, Any]:
    manifest_path = Path(args.manifest)
    manifest = _load_manifest(manifest_path)
    before = _json_sha256(manifest)
    by_id = _artifact_index(manifest)
    selected = by_id.get(args.artifact_id)
    if selected is None:
        raise LifecycleError("artifact_unknown", args.artifact_id)
    if selected["status"] == "locked":
        now = _parse_now(args.now)
        return _receipt(
            operation_id=_operation_id("lock-noop"), operation="lock", status="passed", now=now,
            manifest_path=manifest_path, before=before, after=before, mutated=False,
            items=[{"artifact_id": args.artifact_id, "status": "locked", "idempotent": True}],
        )
    if selected["status"] not in {"created", "candidate", "qa_pass"}:
        raise LifecycleError("artifact_not_lockable", selected["status"])
    now = _parse_now(args.now)
    selected["status"] = "locked"
    selected["updated_at"] = _iso(now)
    selected["retain_reason"] = args.reason
    superseded: list[str] = []
    siblings = [
        item for item in manifest["artifacts"]
        if item["video_id"] == selected["video_id"]
        and item["artifact_id"] != selected["artifact_id"]
        and item["artifact_kind"] not in PROTECTED_KINDS
        and item["status"] in {"candidate", "qa_pass"}
    ]
    siblings.sort(key=lambda item: item["updated_at"], reverse=True)
    keep = manifest["policy"]["keep_previous_review_versions"]
    for item in siblings[keep:]:
        item["status"] = "superseded"
        item["superseded_by"] = selected["artifact_id"]
        item["delete_after"] = _retention_deadline(manifest, now, "superseded")
        item["updated_at"] = _iso(now)
        superseded.append(item["artifact_id"])
    operation_id = _operation_id("lock")
    _record_history(
        manifest, operation_id, now, "lock", [selected["artifact_id"], *superseded], args.reason
    )
    _write_json_atomic(manifest_path, manifest, MANIFEST_SCHEMA)
    return _receipt(
        operation_id=operation_id,
        operation="lock",
        status="passed",
        now=now,
        manifest_path=manifest_path,
        before=before,
        after=_json_sha256(manifest),
        mutated=False,
        items=[{"locked": selected["artifact_id"], "superseded": superseded}],
    )


def _active_referrers(manifest: dict[str, Any], artifact_id: str) -> list[str]:
    referrers: list[str] = []
    for item in manifest["artifacts"]:
        if item["status"] in {"quarantine", "purged"}:
            continue
        if artifact_id in item["depends_on"]:
            referrers.append(item["artifact_id"])
    target = _artifact_index(manifest)[artifact_id]
    referrers.extend(target["referenced_by"])
    return sorted(set(referrers))


def build_gc_plan(args: argparse.Namespace) -> dict[str, Any]:
    manifest_path = Path(args.manifest)
    workspace_root = Path(args.workspace_root).resolve()
    manifest = _load_manifest(manifest_path)
    _artifact_index(manifest)
    now = _parse_now(args.now)
    candidates: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    for artifact in manifest["artifacts"]:
        status = artifact["status"]
        task_close_disposable = args.task_close and artifact["artifact_kind"] in DISPOSABLE_KINDS
        if args.phase == "purge":
            eligible = status == "quarantine"
        else:
            eligible = status in QUARANTINE_ELIGIBLE or task_close_disposable
        if not eligible or status == "purged":
            continue
        reason: str | None = None
        if artifact["artifact_kind"] in PROTECTED_KINDS or status == "locked":
            reason = "protected_artifact"
        referrers = _active_referrers(manifest, artifact["artifact_id"])
        if referrers:
            reason = "still_referenced"
        delete_after = artifact["delete_after"]
        if task_close_disposable and delete_after is None:
            delete_after = _retention_deadline(manifest, now, "task_cache")
        if delete_after is None:
            reason = reason or "delete_after_missing"
        elif _parse_now(delete_after) > now:
            reason = reason or "retention_not_elapsed"
        if args.phase == "purge" and (
            not manifest["policy"]["automatic_purge_authorized"]
            or not artifact["purge_approved"]
        ):
            reason = reason or "purge_not_approved"
        source = _resolve_under(workspace_root, artifact["path"])
        if not source.exists():
            reason = reason or "artifact_missing"
        stat = source.stat() if source.exists() else None
        item = {
            "artifact_id": artifact["artifact_id"],
            "source_path": artifact["path"],
            "bytes": artifact["bytes"],
            "source_size": stat.st_size if stat else None,
            "source_mtime_ns": stat.st_mtime_ns if stat else None,
            "source_sha256": artifact["source_sha256"],
            "delete_after": delete_after,
            "task_close_disposable": task_close_disposable,
        }
        if reason:
            item["reason"] = reason
            item["referrers"] = referrers
            blocked.append(item)
        else:
            candidates.append(item)
    plan = _receipt(
        operation_id=_operation_id("gc-plan"),
        operation=f"plan_gc_{args.phase}",
        status="planned",
        now=now,
        manifest_path=manifest_path,
        before=_json_sha256(manifest),
        after=_json_sha256(manifest),
        mutated=False,
        items=candidates,
        blocked=blocked,
        metrics={"eligible_bytes": sum(item["bytes"] for item in candidates)},
    )
    return plan


def apply_gc(args: argparse.Namespace) -> dict[str, Any]:
    manifest_path = Path(args.manifest)
    workspace_root = Path(args.workspace_root).resolve()
    manifest = _load_manifest(manifest_path)
    before = _json_sha256(manifest)
    plan = _read_json(Path(args.plan))
    _validate(plan, RECEIPT_SCHEMA)
    if plan["operation"] != "plan_gc" or plan["status"] != "planned":
        expected_operation = f"plan_gc_{args.phase}"
        if plan["operation"] != expected_operation or plan["status"] != "planned":
            raise LifecycleError("gc_plan_required", args.plan)
    if Path(plan["manifest_path"]).resolve() != manifest_path.resolve():
        raise LifecycleError("gc_plan_manifest_mismatch", args.plan)
    if plan["manifest_sha256_before"] != before:
        raise LifecycleError("stale_gc_plan", args.plan)
    by_id = _artifact_index(manifest)
    now = _parse_now(args.now)
    changed: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    for planned in plan["items"]:
        artifact = by_id.get(planned["artifact_id"])
        if artifact is None:
            blocked.append({"artifact_id": planned["artifact_id"], "reason": "artifact_unknown"})
            continue
        if args.phase == "quarantine":
            if artifact["status"] not in QUARANTINE_ELIGIBLE and not planned.get("task_close_disposable"):
                blocked.append({"artifact_id": artifact["artifact_id"], "reason": "status_not_quarantine_eligible"})
                continue
            if artifact["artifact_kind"] in PROTECTED_KINDS or _active_referrers(manifest, artifact["artifact_id"]):
                blocked.append({"artifact_id": artifact["artifact_id"], "reason": "protected_or_referenced"})
                continue
            source = _resolve_under(workspace_root, artifact["path"], must_exist=True)
            stat = source.stat()
            if stat.st_size != planned["source_size"] or stat.st_mtime_ns != planned["source_mtime_ns"]:
                blocked.append({"artifact_id": artifact["artifact_id"], "reason": "source_stat_drift"})
                continue
            if artifact["source_sha256"] and _sha256(source) != artifact["source_sha256"]:
                blocked.append({"artifact_id": artifact["artifact_id"], "reason": "source_hash_drift"})
                continue
            destination_rel = (
                Path(manifest["quarantine_dir"]) / artifact["artifact_id"] / source.name
            ).as_posix()
            destination = _resolve_under(workspace_root, destination_rel)
            if destination.exists():
                blocked.append({"artifact_id": artifact["artifact_id"], "reason": "quarantine_destination_exists"})
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(destination))
            artifact["original_path"] = artifact["path"]
            artifact["path"] = destination_rel
            artifact["quarantine_path"] = destination_rel
            artifact["status"] = "quarantine"
            artifact["updated_at"] = _iso(now)
            if artifact["delete_after"] is None:
                artifact["delete_after"] = _retention_deadline(manifest, now, "task_cache")
            changed.append({"artifact_id": artifact["artifact_id"], "to": destination_rel})
        else:
            if artifact["status"] != "quarantine":
                blocked.append({"artifact_id": artifact["artifact_id"], "reason": "not_quarantined"})
                continue
            if not manifest["policy"]["automatic_purge_authorized"] or not artifact["purge_approved"]:
                blocked.append({"artifact_id": artifact["artifact_id"], "reason": "purge_not_approved"})
                continue
            if artifact["delete_after"] is None or _parse_now(artifact["delete_after"]) > now:
                blocked.append({"artifact_id": artifact["artifact_id"], "reason": "retention_not_elapsed"})
                continue
            source = _resolve_under(workspace_root, artifact["path"], must_exist=True)
            if source.is_dir():
                blocked.append({"artifact_id": artifact["artifact_id"], "reason": "directory_purge_not_supported"})
                continue
            source.unlink()
            artifact["status"] = "purged"
            artifact["updated_at"] = _iso(now)
            changed.append({"artifact_id": artifact["artifact_id"], "purged": True})
    operation_id = _operation_id(f"gc-{args.phase}")
    if changed:
        _record_history(
            manifest,
            operation_id,
            now,
            f"gc_{args.phase}",
            [item["artifact_id"] for item in changed],
            f"applied hash-bound {args.phase} plan",
        )
        _write_json_atomic(manifest_path, manifest, MANIFEST_SCHEMA)
    after = _json_sha256(manifest)
    return _receipt(
        operation_id=operation_id,
        operation=f"apply_gc_{args.phase}",
        status="passed" if not blocked else "blocked",
        now=now,
        manifest_path=manifest_path,
        before=before,
        after=after,
        mutated=bool(changed),
        items=changed,
        blocked=blocked,
        metrics={"changed_count": len(changed), "blocked_count": len(blocked)},
    )


def preflight(args: argparse.Namespace) -> dict[str, Any]:
    manifest_path = Path(args.manifest)
    workspace_root = Path(args.workspace_root).resolve()
    manifest = _load_manifest(manifest_path)
    now = _parse_now(args.now)
    intermediate_bytes = sum(
        artifact["bytes"]
        for artifact in manifest["artifacts"]
        if artifact["status"] not in {"quarantine", "purged", "locked"}
        and artifact["artifact_kind"] not in PROTECTED_KINDS
    )
    output_class = getattr(args, "output_class", "large_or_unknown")
    if output_class not in {"small_known", "large_or_unknown"}:
        raise LifecycleError("output_class_invalid", str(output_class))
    estimated_output_bytes = getattr(args, "estimated_output_bytes", None)
    if estimated_output_bytes is not None and (
        isinstance(estimated_output_bytes, bool)
        or not isinstance(estimated_output_bytes, int)
        or estimated_output_bytes < 0
    ):
        raise LifecycleError("estimated_output_bytes_invalid", str(estimated_output_bytes))
    core = _load_shared_core(getattr(args, "core_root", None))
    profile = _media_profile(core)
    try:
        disk = core.free_space_status(
            workspace_root,
            None,
            minimum_free_bytes=profile["minimum_free_bytes"],
            warning_free_bytes=profile["warning_free_bytes"],
            estimated_output_bytes=estimated_output_bytes or 0,
            output_headroom_multiplier=profile["output_headroom_multiplier"],
        )
    except core.LifecycleError as exc:
        raise LifecycleError(exc.code, getattr(exc, "detail", str(exc))) from exc
    blocked: list[dict[str, Any]] = []
    if intermediate_bytes > manifest["policy"]["task_intermediate_limit_bytes"]:
        blocked.append({"reason": "task_intermediate_limit_exceeded", "bytes": intermediate_bytes})
    if output_class == "large_or_unknown" and not estimated_output_bytes:
        blocked.append({"reason": "blocked_output_estimate_required"})
    if disk["status"] == "blocked_low_disk":
        blocked.append(
            {
                "reason": "blocked_low_disk",
                "free_bytes": disk["free_bytes"],
                "required_free_bytes": disk["required_free_bytes"],
            }
        )
    warning_codes = ["low_disk_allowed"] if disk["status"] == "low_disk_allowed" else []
    return _receipt(
        operation_id=_operation_id("preflight"),
        operation="render_preflight",
        status="blocked" if blocked else "passed",
        now=now,
        manifest_path=manifest_path,
        before=_json_sha256(manifest),
        after=_json_sha256(manifest),
        mutated=False,
        blocked=blocked,
        metrics={
            "intermediate_bytes": intermediate_bytes,
            "intermediate_limit_bytes": manifest["policy"]["task_intermediate_limit_bytes"],
            "output_class": output_class,
            "disk_policy_source": profile["source"],
            "disk_policy_mode": disk["policy_mode"],
            "disk_free_bytes": disk["free_bytes"],
            "disk_total_bytes": disk["total_bytes"],
            "disk_free_ratio": disk["free_ratio"],
            "minimum_free_bytes": disk["minimum_free_bytes"],
            "warning_free_bytes": disk["warning_free_bytes"],
            "estimated_output_bytes": disk["estimated_output_bytes"],
            "output_headroom_multiplier": disk["output_headroom_multiplier"],
            "required_free_bytes": disk["required_free_bytes"],
            "warning_codes": warning_codes,
            "legacy_min_free_ratio_ignored": "min_free_ratio" in manifest["policy"],
            "safe_gc_required": bool(blocked),
        },
    )


def restore_artifact(args: argparse.Namespace) -> dict[str, Any]:
    manifest_path = Path(args.manifest)
    workspace_root = Path(args.workspace_root).resolve()
    manifest = _load_manifest(manifest_path)
    before = _json_sha256(manifest)
    artifact = _artifact_index(manifest).get(args.artifact_id)
    if artifact is None:
        raise LifecycleError("artifact_unknown", args.artifact_id)
    if artifact["status"] != "quarantine" or artifact["original_path"] is None:
        raise LifecycleError("artifact_not_quarantined", args.artifact_id)
    source = _resolve_under(workspace_root, artifact["path"], must_exist=True)
    destination = _resolve_under(workspace_root, artifact["original_path"])
    if destination.exists():
        raise LifecycleError("restore_destination_exists", artifact["original_path"])
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(destination))
    now = _parse_now(args.now)
    artifact["path"] = artifact["original_path"]
    artifact["original_path"] = None
    artifact["quarantine_path"] = None
    artifact["status"] = args.status
    artifact["updated_at"] = _iso(now)
    if args.status == "candidate":
        artifact["delete_after"] = None
        artifact["failure_reason"] = None
        artifact["superseded_by"] = None
    operation_id = _operation_id("restore")
    _record_history(
        manifest, operation_id, now, "restore", [args.artifact_id], args.reason
    )
    _write_json_atomic(manifest_path, manifest, MANIFEST_SCHEMA)
    return _receipt(
        operation_id=operation_id,
        operation="restore",
        status="passed",
        now=now,
        manifest_path=manifest_path,
        before=before,
        after=_json_sha256(manifest),
        mutated=True,
        items=[{"artifact_id": args.artifact_id, "restored_to": artifact["path"]}],
    )


def build_archive_plan(assessment: dict[str, Any]) -> dict[str, Any]:
    """Select retention scope only; do not inspect, copy or certify media."""
    _validate(assessment, ARCHIVE_ASSESSMENT_SCHEMA)
    for key in ("project_id", "restore_goal"):
        if not assessment[key].strip():
            raise LifecycleError("archive_context_required", key)
    policy = _read_json(ARCHIVE_POLICY)
    factors = assessment.get("factors", {})
    matched = [key for key in policy["upgrade_factors"] if factors.get(key) is True]
    unknown = [key for key in policy["upgrade_factors"] if factors.get(key) is None]
    recommended = "reproducible" if matched else policy["default_level"]
    selected = assessment.get("selected_level", recommended)
    reason = assessment.get("decision_reason", "").strip()
    if (selected == "simple" or selected != recommended) and not reason:
        raise LifecycleError("archive_decision_reason_required", "Explain a simple archive or a change from the recommendation.")
    backup = assessment.get("original_backup_reference", "").strip()
    if selected == "simple" and not backup:
        raise LifecycleError("archive_original_reference_required", "Simple retention still requires an original/backup reference; its existence must be checked separately.")
    scope = assessment.get("rebuild_scope", "").strip()
    if selected == "reproducible" and not scope:
        scope = assessment["restore_goal"]
    order = ["simple", "rework", "reproducible"]
    included = order[:order.index(selected) + 1]
    return {
        "schema_version": "self-media.video-archive-plan.v1",
        "status": "planning_only",
        "project_id": assessment["project_id"],
        "restore_goal": assessment["restore_goal"],
        "policy_ref": {"path": str(ARCHIVE_POLICY), "sha256": _sha256(ARCHIVE_POLICY)},
        "assessment_sha256": _json_sha256(assessment),
        "recommended_level": recommended,
        "selected_level": selected,
        "selection_reason": reason or ("; ".join(policy["upgrade_factors"][key] for key in matched) if matched else "默认保留可继续返工的素材与配方"),
        "upgrade_factors": matched,
        "unknown_factors": unknown,
        "assessment_complete": not unknown,
        "recommendation_overridden": selected != recommended,
        "original_backup_reference": backup or None,
        "original_backup_verified": False,
        "missing_materials": assessment.get("missing_materials", []),
        "rebuild_scope": scope or None,
        "required_material_groups": [item for level in included for item in policy["levels"][level]["retain"]],
        "required_checks": [{"check": item, "status": "not_run"} for level in included for item in policy["levels"][level]["verify"]],
        "excluded_by_default": policy["exclude_by_default"],
        "always_preserve": policy["always_preserve"],
        "temporary_full_snapshot_guidance": policy["temporary_full_snapshot"],
        "archive_complete": False,
        "integrity_verified": False,
        "rebuild_verified": False,
        "uploaded": False,
        "remote_download_verified": False,
        "media_mutation_performed": False,
        "authorization_granted": False,
        "boundaries": policy["boundaries"],
    }


def _add_common_manifest(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--workspace-root", required=True)
    parser.add_argument("--now")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    doctor = subparsers.add_parser("doctor")
    doctor.add_argument("--core-root")

    subparsers.add_parser("archive-policy", help="Read default archive tiers; no media access")
    archive = subparsers.add_parser("archive-plan", help="Choose archive scope and pending checks; no packing or rendering")
    archive.add_argument("--assessment", required=True)
    archive.add_argument("--output", required=True)

    init = subparsers.add_parser("init")
    _add_common_manifest(init)
    init.add_argument("--manifest-id", required=True)
    init.add_argument("--workspace-ref")
    init.add_argument("--quarantine-dir", default=".artifact-quarantine")
    init.add_argument("--authorize-automatic-purge", action="store_true")

    register = subparsers.add_parser("register")
    _add_common_manifest(register)
    register.add_argument("--artifact-id", required=True)
    register.add_argument("--video-id", required=True)
    register.add_argument("--path", required=True)
    register.add_argument("--kind", choices=sorted({*PROTECTED_KINDS, *DISPOSABLE_KINDS, "candidate", "receipt", "other"}), required=True)
    register.add_argument(
        "--status",
        choices=["created", "candidate", "qa_pass", "qa_fail"],
        default="created",
    )
    register.add_argument("--source-sha256")
    register.add_argument("--depends-on", action="append")
    register.add_argument("--referenced-by", action="append")
    register.add_argument("--retain-reason")
    register.add_argument("--failure-reason")
    register.add_argument("--user-rejected", action="store_true")
    register.add_argument("--approve-purge", action="store_true")
    register.add_argument("--receipt", required=True)

    transition = subparsers.add_parser("transition")
    _add_common_manifest(transition)
    transition.add_argument("--artifact-id", required=True)
    transition.add_argument("--status", choices=sorted(STATUS_TRANSITIONS), required=True)
    transition.add_argument("--reason", required=True)
    transition.add_argument("--superseded-by")
    transition.add_argument("--user-rejected", action="store_true")
    transition.add_argument("--approve-purge", action="store_true")
    transition.add_argument("--receipt", required=True)

    lock = subparsers.add_parser("lock")
    _add_common_manifest(lock)
    lock.add_argument("--artifact-id", required=True)
    lock.add_argument("--reason", required=True)
    lock.add_argument("--receipt", required=True)

    plan = subparsers.add_parser("plan-gc")
    _add_common_manifest(plan)
    plan.add_argument("--phase", choices=["quarantine", "purge"], default="quarantine")
    plan.add_argument("--task-close", action="store_true")
    plan.add_argument("--receipt", required=True)

    apply = subparsers.add_parser("apply-gc")
    _add_common_manifest(apply)
    apply.add_argument("--plan", required=True)
    apply.add_argument("--phase", choices=["quarantine", "purge"], required=True)
    apply.add_argument("--receipt", required=True)

    restore = subparsers.add_parser("restore")
    _add_common_manifest(restore)
    restore.add_argument("--artifact-id", required=True)
    restore.add_argument("--status", choices=["candidate", "qa_fail", "superseded"], default="candidate")
    restore.add_argument("--reason", required=True)
    restore.add_argument("--receipt", required=True)

    check = subparsers.add_parser("preflight")
    _add_common_manifest(check)
    check.add_argument("--core-root")
    check.add_argument(
        "--output-class",
        choices=["small_known", "large_or_unknown"],
        default="large_or_unknown",
    )
    check.add_argument("--estimated-output-bytes", type=int)
    check.add_argument("--receipt", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "archive-policy":
            print(json.dumps(_read_json(ARCHIVE_POLICY), ensure_ascii=False))
            return 0
        if args.command == "archive-plan":
            output = Path(args.output).resolve()
            if output.exists():
                raise LifecycleError("archive_plan_output_exists", str(output))
            result = build_archive_plan(_read_json(Path(args.assessment)))
            _write_json_atomic(output, result)
            print(json.dumps(result, ensure_ascii=False))
            return 0
        if args.command == "doctor":
            Draft202012Validator.check_schema(_read_json(MANIFEST_SCHEMA))
            Draft202012Validator.check_schema(_read_json(RECEIPT_SCHEMA))
            Draft202012Validator.check_schema(_read_json(ARCHIVE_ASSESSMENT_SCHEMA))
            core = _load_shared_core(args.core_root)
            profile = _media_profile(core)
            print(
                json.dumps(
                    {
                        "status": "ready",
                        "schema_version": "artifact-lifecycle-doctor.v1",
                        "manifest_schema": str(MANIFEST_SCHEMA),
                        "receipt_schema": str(RECEIPT_SCHEMA),
                        "default_policy": DEFAULT_POLICY,
                        "video_archive_default_level": _read_json(ARCHIVE_POLICY)["default_level"],
                        "video_archive_policy": str(ARCHIVE_POLICY),
                        "effective_disk_policy": profile,
                        "filesystem_mutation_performed": False,
                    },
                    ensure_ascii=False,
                )
            )
            return 0
        if args.command == "init":
            manifest = init_manifest(args)
            print(json.dumps({"status": "passed", "manifest": str(Path(args.manifest).resolve()), "revision": manifest["revision"]}, ensure_ascii=False))
            return 0
        if args.command == "register":
            result = register_artifact(args)
        elif args.command == "transition":
            result = transition_artifact(args)
        elif args.command == "lock":
            result = lock_artifact(args)
        elif args.command == "plan-gc":
            result = build_gc_plan(args)
        elif args.command == "apply-gc":
            result = apply_gc(args)
        elif args.command == "restore":
            result = restore_artifact(args)
        else:
            result = preflight(args)
        _write_json_atomic(Path(args.receipt), result, RECEIPT_SCHEMA)
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result["status"] != "blocked" else 2
    except LifecycleError as exc:
        print(json.dumps({"status": "blocked", "error_code": exc.code, "detail": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
