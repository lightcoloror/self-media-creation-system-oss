#!/usr/bin/env python3
"""Bind human-reviewed subject windows to MVP redaction coverage, fail closed."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]
BINDING_SCHEMA = ROOT / "schemas" / "privacy-redaction-binding.v1.schema.json"
RECEIPT_SCHEMA = ROOT / "schemas" / "privacy-redaction-binding-receipt.v1.schema.json"
DECISION_SCHEMA = ROOT / "schemas" / "video-privacy-treatment-decision.v1.schema.json"


class PrivacyBindingError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PrivacyBindingError("artifact_unreadable", f"{path}: {error}") from error
    if not isinstance(value, dict):
        raise PrivacyBindingError("schema_validation_failed", f"{path} must contain an object")
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise PrivacyBindingError("artifact_unreadable", f"{path}: {error}") from error
    return digest.hexdigest()


def _validate(value: dict[str, Any], schema_path: Path, label: str) -> None:
    schema = load_json(schema_path)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(value), key=lambda item: list(item.path))
    if errors:
        message = "; ".join(
            f"{label}.{'.'.join(str(part) for part in error.path) or '$'}: {error.message}"
            for error in errors
        )
        raise PrivacyBindingError("schema_validation_failed", message)


def _resolve(workspace_root: Path, artifact: dict[str, Any], label: str) -> Path:
    root = workspace_root.resolve()
    target = (root / artifact["path"]).resolve()
    try:
        target.relative_to(root)
    except ValueError as error:
        raise PrivacyBindingError("artifact_outside_workspace", f"{label}: {artifact['path']}") from error
    if not target.is_file():
        raise PrivacyBindingError("artifact_unreadable", f"{label}: {artifact['path']}")
    if sha256_file(target) != artifact["expected_sha256"]:
        raise PrivacyBindingError("source_hash_drift", f"{label}: {artifact['path']}")
    return target


def _load_mvp_contract_io(mvp_root: Path):
    source_root = (mvp_root / "src").resolve()
    if not source_root.is_dir():
        raise PrivacyBindingError("mvp_owner_missing", f"missing MVP source root: {source_root}")
    sys.path.insert(0, str(source_root))
    try:
        from video_creation_pipeline.contract_io import (  # type: ignore
            payload_sha256,
            validate_artifact_reference,
        )
    except Exception as error:
        raise PrivacyBindingError("mvp_owner_unavailable", str(error)) from error
    return payload_sha256, validate_artifact_reference


def _validate_zones(zones: dict[str, Any], mvp_root: Path) -> None:
    schema_path = mvp_root / "src" / "video_creation_pipeline" / "schemas" / "privacy_exclusion_zones.v1.schema.json"
    _validate(zones, schema_path, "privacy_zones")
    payload_sha256, validate_artifact_reference = _load_mvp_contract_io(mvp_root)
    if zones["zones_sha256"] != payload_sha256(zones, "zones_sha256"):
        raise PrivacyBindingError("privacy_zones_integrity_failed", "privacy zones payload hash drifted")
    for key in ("source_media", "redacted_media", "source_redaction_job", "source_redaction_receipt"):
        try:
            validate_artifact_reference(zones[key], f"privacy zones {key}")
        except Exception as error:
            raise PrivacyBindingError("privacy_zones_artifact_drift", str(error)) from error


def evaluate(
    binding_path: Path,
    workspace_root: Path,
    mvp_root: Path,
    *,
    evaluated_at: str | None = None,
) -> dict[str, Any]:
    binding = load_json(binding_path)
    _validate(binding, BINDING_SCHEMA, "binding")
    decision_path = _resolve(workspace_root, binding["decision"], "decision")
    zones_path = _resolve(workspace_root, binding["privacy_zones"], "privacy_zones")
    candidate_path = _resolve(workspace_root, binding["candidate"], "candidate")
    _resolve(workspace_root, binding["visible_window_manifest"], "visible_window_manifest")

    decision = load_json(decision_path)
    _validate(decision, DECISION_SCHEMA, "decision")
    zones = load_json(zones_path)
    _validate_zones(zones, mvp_root)
    if zones["redacted_media"]["sha256"] != binding["candidate"]["expected_sha256"]:
        raise PrivacyBindingError(
            "candidate_hash_mismatch",
            "MVP redacted_media is not the candidate bound for human review",
        )

    decision_subjects = {
        str(row["subject_ref"]): row
        for row in decision["subjects"]
        if row["face_treatment"]["action"] == "mosaic"
    }
    binding_subjects: dict[str, dict[str, Any]] = {}
    for row in binding["subject_bindings"]:
        subject_ref = str(row["subject_ref"])
        if subject_ref in binding_subjects:
            raise PrivacyBindingError("subject_binding_duplicate", subject_ref)
        binding_subjects[subject_ref] = row
    if set(binding_subjects) != set(decision_subjects):
        raise PrivacyBindingError(
            "subject_binding_mismatch",
            f"expected={sorted(decision_subjects)}, actual={sorted(binding_subjects)}",
        )

    zone_tracks = {str(row["track_id"]): row for row in zones["tracks"]}
    results: list[dict[str, Any]] = []
    for subject_ref, row in binding_subjects.items():
        decision_subject = decision_subjects[subject_ref]
        if set(row["human_face_track_refs"]) != set(decision_subject["face_track_refs"]):
            raise PrivacyBindingError("human_face_track_mismatch", subject_ref)
        expected_window_refs = set(decision_subject["visible_window_refs"])
        actual_window_refs = {str(window["visible_window_ref"]) for window in row["visible_windows"]}
        if actual_window_refs != expected_window_refs:
            raise PrivacyBindingError(
                "visible_window_binding_mismatch",
                f"{subject_ref}: expected={sorted(expected_window_refs)}, actual={sorted(actual_window_refs)}",
            )
        selected_tracks: list[dict[str, Any]] = []
        for track_ref in row["anonymous_zone_track_refs"]:
            track = zone_tracks.get(str(track_ref))
            if track is None or track["target_type"] != "face":
                raise PrivacyBindingError("anonymous_zone_track_missing", f"{subject_ref}: {track_ref}")
            selected_tracks.append(track)
        covered = {
            int(zone["frame_index"])
            for track in selected_tracks
            for zone in track["zones"]
            if zone["visible"]
        }
        required: set[int] = set()
        for window in row["visible_windows"]:
            start = int(window["start_frame"])
            end = int(window["end_frame"])
            if end < start:
                raise PrivacyBindingError("visible_window_invalid", f"{subject_ref}: {window['visible_window_ref']}")
            required.update(range(start, end + 1))
        missing = sorted(required.difference(covered))
        if missing:
            preview = missing[:12]
            suffix = "..." if len(missing) > len(preview) else ""
            raise PrivacyBindingError(
                "redaction_window_uncovered",
                f"{subject_ref} lacks mosaic coverage on frames {preview}{suffix}",
            )
        results.append(
            {
                "subject_ref": subject_ref,
                "window_count": len(row["visible_windows"]),
                "required_frame_count": len(required),
                "covered_frame_count": len(required.intersection(covered)),
                "status": "passed",
            }
        )

    receipt = {
        "schema_version": "self-media-privacy-redaction-binding-receipt.v1",
        "binding_id": binding["binding_id"],
        "evaluated_at": evaluated_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "binding_sha256": sha256_file(binding_path),
        "candidate_sha256": sha256_file(candidate_path),
        "privacy_zones_sha256": sha256_file(zones_path),
        "status": "passed",
        "subject_results": results,
        "authority_boundary": {
            "identity_inferred_by_system": False,
            "candidate_only": True,
            "automatic_publish": False,
        },
    }
    _validate(receipt, RECEIPT_SCHEMA, "receipt")
    return receipt


def _write_json(value: dict[str, Any], output: Path | None) -> None:
    text = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    if output is None:
        print(text, end="")
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binding", type=Path, required=True)
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--mvp-root", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        _write_json(evaluate(args.binding, args.workspace_root, args.mvp_root), args.output)
    except PrivacyBindingError as error:
        print(json.dumps({"ok": False, "error_code": error.code, "message": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
