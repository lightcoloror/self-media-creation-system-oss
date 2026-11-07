#!/usr/bin/env python3
"""Create and verify a hash-bound tool/rule lock for one production run."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]
SPEC_SCHEMA = ROOT / "schemas" / "production-run-lock-spec.v1.schema.json"
LOCK_SCHEMA = ROOT / "schemas" / "production-run-lock.v1.schema.json"
VERIFICATION_SCHEMA = ROOT / "schemas" / "production-run-lock-verification.v1.schema.json"


class ProductionRunLockError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ProductionRunLockError("artifact_unreadable", f"{path}: {error}") from error
    if not isinstance(value, dict):
        raise ProductionRunLockError("schema_validation_failed", f"{path} must contain an object")
    return value


def _validate(value: dict[str, Any], schema_path: Path, label: str) -> None:
    schema = load_json(schema_path)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(value), key=lambda item: list(item.path))
    if errors:
        raise ProductionRunLockError(
            "schema_validation_failed",
            "; ".join(f"{label}: {error.message}" for error in errors),
        )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def payload_sha256(value: dict[str, Any], excluded: str) -> str:
    payload = {key: item for key, item in value.items() if key != excluded}
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _resolve(workspace_root: Path, relative_path: str) -> Path:
    root = workspace_root.resolve()
    target = (root / relative_path).resolve()
    try:
        target.relative_to(root)
    except ValueError as error:
        raise ProductionRunLockError("artifact_outside_workspace", relative_path) from error
    if not target.is_file():
        raise ProductionRunLockError("artifact_unreadable", relative_path)
    return target


def _file_record(workspace_root: Path, path: Path) -> dict[str, Any]:
    return {
        "path": path.relative_to(workspace_root.resolve()).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def _git_state(owner_root: Path) -> tuple[str | None, str]:
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=owner_root,
            text=True,
            capture_output=True,
            timeout=5,
            check=True,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            cwd=owner_root,
            text=True,
            capture_output=True,
            timeout=5,
            check=True,
        ).stdout.strip()
        return commit or None, "dirty" if status else "clean"
    except (OSError, subprocess.SubprocessError):
        return None, "unversioned"


def create_lock(
    spec_path: Path,
    workspace_root: Path,
    *,
    created_at: str | None = None,
) -> dict[str, Any]:
    spec = load_json(spec_path)
    _validate(spec, SPEC_SCHEMA, "spec")
    root = workspace_root.resolve()
    components = []
    for component in spec["components"]:
        owner_root = (root / component["owner_root"]).resolve()
        try:
            owner_root.relative_to(root)
        except ValueError as error:
            raise ProductionRunLockError("artifact_outside_workspace", component["owner_root"]) from error
        commit, worktree_state = _git_state(owner_root)
        components.append(
            {
                "tool_id": component["tool_id"],
                "owner_root": owner_root.relative_to(root).as_posix(),
                "source_commit": commit,
                "worktree_state": worktree_state,
                "entrypoints": [
                    _file_record(root, _resolve(root, str(Path(component["owner_root"]) / value)))
                    for value in component["entrypoints"]
                ],
            }
        )
    lock = {
        "schema_version": "self-media-production-run-lock.v1",
        "run_id": spec["run_id"],
        "recipe_id": spec["recipe_id"],
        "lock_scope": spec["lock_scope"],
        "created_at": created_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "components": components,
        "rule_files": [_file_record(root, _resolve(root, value)) for value in spec["rule_files"]],
        "drift_policy": {
            "on_any_hash_change": "invalidate-downstream-candidates-and-start-new-run",
            "active_run_can_absorb_code_changes": False,
        },
        "authority_boundary": {
            "local_only": True,
            "candidate_only": True,
            "upload_allowed": False,
            "publish_allowed": False,
        },
    }
    lock["lock_sha256"] = payload_sha256(lock, "lock_sha256")
    _validate(lock, LOCK_SCHEMA, "lock")
    return lock


def verify_lock(lock_path: Path, workspace_root: Path) -> dict[str, Any]:
    lock = load_json(lock_path)
    _validate(lock, LOCK_SCHEMA, "lock")
    if lock["lock_sha256"] != payload_sha256(lock, "lock_sha256"):
        raise ProductionRunLockError("lock_integrity_failed", "production run lock payload drifted")
    root = workspace_root.resolve()
    records = [record for component in lock["components"] for record in component["entrypoints"]]
    records.extend(lock["rule_files"])
    for record in records:
        path = _resolve(root, record["path"])
        if path.stat().st_size != record["bytes"] or sha256_file(path) != record["sha256"]:
            raise ProductionRunLockError(
                "production_toolchain_drift",
                f"{record['path']} changed; invalidate downstream candidates and start a new run",
            )
    receipt = {
        "schema_version": "self-media-production-run-lock-verification.v1",
        "run_id": lock["run_id"],
        "lock_sha256": lock["lock_sha256"],
        "status": "passed",
        "verified_file_count": len(records),
        "automatic_publish": False,
    }
    _validate(receipt, VERIFICATION_SCHEMA, "verification")
    return receipt


def _write(value: dict[str, Any], output: Path | None) -> None:
    text = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    if output is None:
        print(text, end="")
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create")
    create.add_argument("--spec", type=Path, required=True)
    create.add_argument("--workspace-root", type=Path, required=True)
    create.add_argument("--output", type=Path, required=True)
    verify = sub.add_parser("verify")
    verify.add_argument("--lock", type=Path, required=True)
    verify.add_argument("--workspace-root", type=Path, required=True)
    verify.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "create":
            _write(create_lock(args.spec, args.workspace_root), args.output)
        else:
            _write(verify_lock(args.lock, args.workspace_root), args.output)
    except ProductionRunLockError as error:
        print(json.dumps({"ok": False, "error_code": error.code, "message": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
