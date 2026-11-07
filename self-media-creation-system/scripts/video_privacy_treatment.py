#!/usr/bin/env python3
"""Evaluate hash-bound voice/face choices without rendering or publishing media."""

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
DECISION_SCHEMA_PATH = ROOT / "schemas" / "video-privacy-treatment-decision.v1.schema.json"
REVIEW_SCHEMA_PATH = ROOT / "schemas" / "customer-video-effect-review.v1.schema.json"
GATE_SCHEMA_PATH = ROOT / "schemas" / "prepublication-privacy-gate.v1.schema.json"

INVALIDATIONS = {
    "voice": {
        "audio_lock",
        "final_review",
        "loudness",
        "packaging",
        "subtitle_timing",
    },
    "face": {
        "final_review",
        "packaging",
        "picture_lock",
        "privacy_review",
        "protected_region_review",
    },
    "mask_strength": {
        "final_review",
        "packaging",
        "picture_lock",
        "privacy_review",
        "protected_region_review",
    },
    "motion": {
        "final_review",
        "motion_timing",
        "packaging",
        "picture_lock",
        "protected_region_review",
    },
    "segment": {
        "audio_lock",
        "final_review",
        "loudness",
        "motion_timing",
        "packaging",
        "picture_lock",
        "subtitle_timing",
        "timeline_lock",
    },
}

REVIEW_CHANGE_KINDS = {
    "voice": {"audio"},
    "face": {"mask", "visual_source"},
    "mask_strength": {"mask"},
    "motion": {"timing", "visual_source"},
    "segment": {"audio", "timing", "visual_source"},
}


class PrivacyTreatmentError(ValueError):
    """Stable fail-closed error for the local privacy-treatment evaluator."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def load_json(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, json.JSONDecodeError) as error:
        raise PrivacyTreatmentError("artifact_unreadable", f"{path.name}: {error}") from error
    if not isinstance(value, dict):
        raise PrivacyTreatmentError("schema_validation_failed", f"{path.name} must contain an object")
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise PrivacyTreatmentError("artifact_unreadable", f"{path}: {error}") from error
    return digest.hexdigest()


def _validate(document: dict[str, Any], schema_path: Path, label: str) -> None:
    schema = load_json(schema_path)
    try:
        Draft202012Validator.check_schema(schema)
    except Exception as error:
        raise PrivacyTreatmentError("schema_invalid", f"{schema_path.name}: {error}") from error
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(document), key=lambda item: list(item.path))
    if errors:
        messages = [
            f"{label}: {'.'.join(str(part) for part in error.path) or '$'}: {error.message}"
            for error in errors
        ]
        raise PrivacyTreatmentError("schema_validation_failed", "; ".join(messages))


def _resolve_local(workspace_root: Path, relative_path: str) -> Path:
    root = workspace_root.resolve()
    target = (root / relative_path).resolve()
    try:
        target.relative_to(root)
    except ValueError as error:
        raise PrivacyTreatmentError("artifact_outside_workspace", relative_path) from error
    if not target.is_file():
        raise PrivacyTreatmentError("artifact_unreadable", f"missing local artifact: {relative_path}")
    return target


def _verify_artifact(workspace_root: Path, artifact: dict[str, Any], label: str) -> None:
    target = _resolve_local(workspace_root, artifact["path"])
    if sha256_file(target) != artifact["expected_sha256"]:
        raise PrivacyTreatmentError("source_hash_drift", f"{label}: {artifact['path']}")


def _validate_decision(decision: dict[str, Any], workspace_root: Path) -> dict[str, dict[str, Any]]:
    _validate(decision, DECISION_SCHEMA_PATH, "treatment_decision")
    _verify_artifact(workspace_root, decision["source_media"], "source_media")
    _verify_artifact(workspace_root, decision["subject_manifest"], "subject_manifest")
    for role, artifact in decision["local_edit_state"].items():
        if artifact is not None:
            _verify_artifact(workspace_root, artifact, role)

    subjects: dict[str, dict[str, Any]] = {}
    has_undecided = False
    assigned_face_tracks: set[str] = set()
    assigned_identity_refs: set[str] = set()
    for subject in decision["subjects"]:
        subject_ref = subject["subject_ref"]
        if subject_ref in subjects:
            raise PrivacyTreatmentError("decision_inconsistent", f"duplicate subject_ref: {subject_ref}")
        subjects[subject_ref] = subject
        if not subject["speaker_segment_refs"] and not subject["face_track_refs"]:
            raise PrivacyTreatmentError(
                "decision_inconsistent",
                f"{subject_ref} must reference speaker segments or face tracks",
            )
        voice = subject["voice_treatment"]
        face = subject["face_treatment"]
        identity_status = subject["identity_match_status"]
        has_undecided = (
            has_undecided
            or voice["action"] == "undecided"
            or face["action"] == "undecided"
            or identity_status == "undecided"
        )

        duplicated_tracks = assigned_face_tracks.intersection(subject["face_track_refs"])
        if duplicated_tracks:
            raise PrivacyTreatmentError(
                "decision_inconsistent",
                f"face tracks assigned to multiple subjects: {sorted(duplicated_tracks)}",
            )
        assigned_face_tracks.update(subject["face_track_refs"])

        duplicated_identity_refs = assigned_identity_refs.intersection(subject["identity_reference_refs"])
        if duplicated_identity_refs:
            raise PrivacyTreatmentError(
                "decision_inconsistent",
                f"identity references assigned to multiple subjects: {sorted(duplicated_identity_refs)}",
            )
        assigned_identity_refs.update(subject["identity_reference_refs"])

        if subject["face_track_refs"] and identity_status == "confirmed":
            if not subject["identity_reference_refs"]:
                raise PrivacyTreatmentError(
                    "identity_not_confirmed",
                    f"{subject_ref} face tracks require confirmed identity references",
                )
        if voice["action"] == "convert_same_gender_range" and not voice.get("local_recipe_ref"):
            raise PrivacyTreatmentError(
                "decision_inconsistent",
                f"{subject_ref} voice conversion requires a local recipe reference",
            )
        if face["action"] == "mosaic" and not face.get("local_recipe_ref"):
            raise PrivacyTreatmentError(
                "decision_inconsistent",
                f"{subject_ref} mosaic requires a local recipe reference",
            )
        if face["action"] == "mosaic":
            if not subject["face_track_refs"] or not subject["visible_window_refs"]:
                raise PrivacyTreatmentError(
                    "identity_not_confirmed",
                    f"{subject_ref} mosaic requires face tracks and frame-reviewed visible windows",
                )
            if decision["local_edit_state"]["identity_reference_manifest"] is None:
                raise PrivacyTreatmentError(
                    "identity_not_confirmed",
                    "mosaic requires an identity-reference manifest",
                )
            if decision["local_edit_state"]["visible_window_manifest"] is None:
                raise PrivacyTreatmentError(
                    "identity_not_confirmed",
                    "mosaic requires a frame-reviewed visible-window manifest",
                )

    status = decision["customer_choice_status"]
    policy = decision["preview_policy"]
    if status == "confirmed" and (has_undecided or policy != "customer_preview"):
        raise PrivacyTreatmentError(
            "decision_inconsistent",
            "confirmed choices require complete subject actions and customer_preview",
        )
    if status == "undecided" and (not has_undecided or policy != "internal_preview_only"):
        raise PrivacyTreatmentError(
            "decision_inconsistent",
            "undecided choices require an undecided action and internal_preview_only",
        )
    return subjects


def _validate_review(
    review: dict[str, Any],
    decision_path: Path,
    workspace_root: Path,
    subjects: dict[str, dict[str, Any]],
    decision: dict[str, Any],
) -> None:
    _validate(review, REVIEW_SCHEMA_PATH, "customer_effect_review")
    decision_sha256 = sha256_file(decision_path)
    if review["decision_sha256"] != decision_sha256:
        raise PrivacyTreatmentError("decision_hash_mismatch", "review is not bound to the supplied decision file")
    _verify_artifact(workspace_root, review["candidate"], "candidate")

    qa = review["privacy_render_qa"]
    _verify_artifact(workspace_root, qa["verification_artifact"], "privacy_render_qa")
    if qa["candidate_sha256"] != review["candidate"]["expected_sha256"]:
        raise PrivacyTreatmentError(
            "privacy_qa_candidate_mismatch",
            "privacy render QA is not bound to the supplied candidate",
        )
    if qa["status"] != "passed":
        raise PrivacyTreatmentError("privacy_render_qa_failed", "privacy render QA requires rework")
    if not qa["target_faces_complete"]:
        raise PrivacyTreatmentError("privacy_render_qa_failed", "a target face is not fully protected")
    if not qa["non_target_faces_unaffected"]:
        raise PrivacyTreatmentError("privacy_render_qa_failed", "a non-target face was affected")

    overlay_status = qa["authorization_overlay_status"]
    overlay_policy = decision["authorization_overlay_policy"]
    if overlay_policy == "required_with_face_window" and overlay_status != "passed":
        raise PrivacyTreatmentError(
            "privacy_render_qa_failed",
            "authorization overlay must use the same visible-window boundary as the face treatment",
        )
    if overlay_policy == "not_applicable" and overlay_status != "not_applicable":
        raise PrivacyTreatmentError(
            "privacy_render_qa_failed",
            "authorization overlay status must be not_applicable for this decision",
        )

    expected_window_checks = {
        (subject_ref, visible_window_ref)
        for subject_ref, subject in subjects.items()
        if subject["face_treatment"]["action"] == "mosaic"
        for visible_window_ref in subject["visible_window_refs"]
    }
    seen_window_checks: set[tuple[str, str]] = set()
    for check in qa["window_checks"]:
        subject_ref = check["subject_ref"]
        if subject_ref not in subjects:
            raise PrivacyTreatmentError(
                "privacy_render_qa_failed",
                f"unknown QA subject_ref: {subject_ref}",
            )
        visible_window_ref = check["visible_window_ref"]
        if visible_window_ref not in subjects[subject_ref]["visible_window_refs"]:
            raise PrivacyTreatmentError(
                "privacy_render_qa_failed",
                f"QA window is not assigned to {subject_ref}: {visible_window_ref}",
            )
        key = (subject_ref, visible_window_ref)
        if key in seen_window_checks:
            raise PrivacyTreatmentError(
                "privacy_render_qa_failed",
                f"duplicate QA window check: {subject_ref}/{visible_window_ref}",
            )
        seen_window_checks.add(key)
        if check["first_visible_target_protected"] != "passed":
            raise PrivacyTreatmentError("privacy_render_qa_failed", f"first visible frame failed: {key}")
        if check["midpoint_target_protected"] != "passed":
            raise PrivacyTreatmentError("privacy_render_qa_failed", f"midpoint frame failed: {key}")
        if check["last_visible_target_protected"] != "passed":
            raise PrivacyTreatmentError("privacy_render_qa_failed", f"last visible frame failed: {key}")
        if "failed" in {
            check["pre_entry_non_target_clear"],
            check["post_exit_non_target_clear"],
        }:
            raise PrivacyTreatmentError("privacy_render_qa_failed", f"non-target boundary failed: {key}")
    if seen_window_checks != expected_window_checks:
        missing = sorted(expected_window_checks - seen_window_checks)
        unexpected = sorted(seen_window_checks - expected_window_checks)
        raise PrivacyTreatmentError(
            "privacy_render_qa_failed",
            f"QA window coverage mismatch; missing={missing}, unexpected={unexpected}",
        )

    result = review["result"]
    changes = review["requested_changes"]
    if result == "request_changes" and not changes:
        raise PrivacyTreatmentError("review_inconsistent", "request_changes requires at least one changed window")
    if result != "request_changes" and changes:
        raise PrivacyTreatmentError("review_inconsistent", f"{result} cannot include changed windows")
    duration = review["candidate"]["duration_seconds"]
    seen_change_ids: set[str] = set()
    for change in changes:
        if change["change_id"] in seen_change_ids:
            raise PrivacyTreatmentError("review_inconsistent", f"duplicate change_id: {change['change_id']}")
        seen_change_ids.add(change["change_id"])
        if change["subject_ref"] not in subjects:
            raise PrivacyTreatmentError(
                "review_inconsistent",
                f"unknown subject_ref: {change['subject_ref']}",
            )
        if change["end_seconds"] <= change["start_seconds"]:
            raise PrivacyTreatmentError(
                "review_inconsistent",
                f"invalid changed window: {change['change_id']}",
            )
        if change["end_seconds"] > duration:
            raise PrivacyTreatmentError(
                "review_inconsistent",
                f"changed window exceeds candidate duration: {change['change_id']}",
            )


def _recipe_fallback(change: dict[str, Any], subject: dict[str, Any]) -> str | None:
    if change.get("local_recipe_ref"):
        return change["local_recipe_ref"]
    if change["kind"] == "voice":
        return subject["voice_treatment"].get("local_recipe_ref")
    if change["kind"] in {"face", "mask_strength"}:
        return subject["face_treatment"].get("local_recipe_ref")
    return None


def _rework_request(
    decision: dict[str, Any],
    review: dict[str, Any],
    subjects: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    invalidations: set[str] = set()
    change_kinds: set[str] = set()
    changed_windows = []
    for change in review["requested_changes"]:
        invalidations.update(INVALIDATIONS[change["kind"]])
        change_kinds.update(REVIEW_CHANGE_KINDS[change["kind"]])
        changed_windows.append(
            {
                "window_id": change["change_id"],
                "subject_ref": change["subject_ref"],
                "kind": change["kind"],
                "start_seconds": change["start_seconds"],
                "end_seconds": change["end_seconds"],
                "requested_action": change["requested_action"],
                "reason_summary": change["reason_summary"],
                "local_recipe_ref": _recipe_fallback(change, subjects[change["subject_ref"]]),
            }
        )
    return {
        "mode": "limited_rework",
        "recalculation_scope": "changed_windows_only",
        "frozen_scope": "all_unlisted_windows",
        "source_candidate": review["candidate"],
        "local_edit_state": decision["local_edit_state"],
        "changed_windows": changed_windows,
        "change_kinds": sorted(change_kinds),
        "downstream_invalidations": sorted(invalidations),
        "required_followups": [
            "revise-treatment-decision",
            "rerender-changed-windows",
            "run-vkp-targeted-review",
            "obtain-new-customer-confirmation",
        ],
        "review_interface": {
            "tool_id": "video-knowledge-pipeline",
            "surface": "targeted-review",
            "delivery": "source_time_range_manifest",
        },
    }


def evaluate(
    decision_path: Path,
    review_path: Path,
    workspace_root: Path,
    *,
    evaluated_at: str | None = None,
) -> dict[str, Any]:
    decision = load_json(decision_path)
    review = load_json(review_path)
    subjects = _validate_decision(decision, workspace_root)
    _validate_review(review, decision_path, workspace_root, subjects, decision)

    result = review["result"]
    if result == "withdrawn":
        status = "withdrawn"
        stop_reasons = ["customer-withdrew-candidate"]
        rework_request = None
    elif result == "request_changes":
        status = "limited_rework_required"
        stop_reasons = ["limited-rework-required", "new-customer-confirmation-required"]
        rework_request = _rework_request(decision, review, subjects)
    elif decision["customer_choice_status"] == "undecided":
        status = "internal_preview_only"
        stop_reasons = ["privacy-treatment-undecided", "customer-confirmation-not-publication-valid"]
        rework_request = None
    else:
        status = "customer_confirmed_candidate"
        stop_reasons = []
        rework_request = None

    decision_sha256 = sha256_file(decision_path)
    review_sha256 = sha256_file(review_path)
    gate = {
        "schema_version": "self-media-prepublication-privacy-gate.v1",
        "gate_id": f"privacy-gate-{review_sha256[:16]}",
        "evaluated_at": evaluated_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "decision_sha256": decision_sha256,
        "review_sha256": review_sha256,
        "candidate": review["candidate"],
        "status": status,
        "manual_publication_eligible": status == "customer_confirmed_candidate",
        "automatic_publish": False,
        "customer_contact_performed_by_system": False,
        "reuse_local_recipes": True,
        "stop_reasons": stop_reasons,
        "rework_request": rework_request,
    }
    _validate(gate, GATE_SCHEMA_PATH, "prepublication_privacy_gate")
    return gate


def write_json(document: dict[str, Any], output_path: Path | None) -> None:
    encoded = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
    if output_path is None:
        print(encoded, end="")
        return
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(encoded, encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    evaluate_parser = subparsers.add_parser("evaluate", help="evaluate one decision and customer review")
    evaluate_parser.add_argument("--decision", type=Path, required=True)
    evaluate_parser.add_argument("--review", type=Path, required=True)
    evaluate_parser.add_argument("--workspace-root", type=Path, required=True)
    evaluate_parser.add_argument("--output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        gate = evaluate(args.decision, args.review, args.workspace_root)
        write_json(gate, args.output)
    except PrivacyTreatmentError as error:
        print(json.dumps({"ok": False, "error_code": error.code, "message": str(error)}), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
