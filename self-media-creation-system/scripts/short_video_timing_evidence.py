#!/usr/bin/env python3
"""Bind short-video timing heuristics to an observed read-aloud or final cut.

This is a sidecar validator inside the existing self-media workflow.  It does
not write a script, inspect a platform account, publish, or claim that a
prerecording observation proves the timing of the later edited video.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import math
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parent
STUDIO = WORKSPACE / "content-studio-poc"
INPUT_SCHEMA = ROOT / "schemas" / "short-video-timing-evidence-input.v1.schema.json"
RECEIPT_SCHEMA = ROOT / "schemas" / "short-video-timing-evidence.v1.schema.json"
PROFILE_PATH = ROOT / "config" / "short-video-timing-profile.v1.json"
FIXTURE_ROOT = ROOT / "fixtures" / "short-video-timing-evidence-v1"
FIXTURES = (
    FIXTURE_ROOT / "synthetic-prerecord.input.json",
    FIXTURE_ROOT / "synthetic-final-cut.input.json",
)
OUTPUT_ROOTS = (
    ROOT / ".runtime" / "short-video-timing-evidence",
    ROOT / "tests" / ".runtime" / "short-video-timing-evidence",
)
OWNER_ROOTS = {
    "self-media-creation-system": ROOT,
    "content-studio-poc": STUDIO,
}
AUTHORITY = {
    "publish_authorized": False,
    "execution_authorized": False,
    "external_send_authorized": False,
}


class TimingEvidenceError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def probe_media_file(path: Path) -> dict[str, Any]:
    """Reuse the existing release-freeze ffprobe implementation for real final cuts."""

    spec = importlib.util.spec_from_file_location(
        "timing_publication_version_freeze",
        ROOT / "scripts" / "publication_version_freeze.py",
    )
    assert spec and spec.loader
    freezer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(freezer)
    try:
        return freezer.probe_media_file(path)
    except Exception as error:
        code = getattr(error, "code", "media_probe_failed")
        raise TimingEvidenceError(code, str(error)) from error


def json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise TimingEvidenceError("artifact_missing", str(path)) from error
    except json.JSONDecodeError as error:
        raise TimingEvidenceError("invalid_json", f"{path}: {error}") from error
    if not isinstance(value, dict):
        raise TimingEvidenceError("invalid_shape", f"{path} must contain an object")
    return value


def validate_schema(value: dict[str, Any], schema_path: Path, label: str) -> None:
    schema = load_json(schema_path)
    Draft202012Validator.check_schema(schema)
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(value),
        key=lambda error: list(error.path),
    )
    if errors:
        error = errors[0]
        location = ".".join(str(part) for part in error.path) or "$"
        raise TimingEvidenceError("schema_invalid", f"{label}.{location}: {error.message}")


def resolve_owner_ref(ref: dict[str, Any], label: str) -> Path:
    owner = ref["owner"]
    base = OWNER_ROOTS.get(owner)
    if base is None or not base.is_dir():
        raise TimingEvidenceError("owner_unavailable", f"{label}: {owner}")
    raw = Path(ref["path"])
    if raw.is_absolute() or ".." in raw.parts:
        raise TimingEvidenceError("artifact_ref_escape", label)
    target = (base / raw).resolve()
    try:
        target.relative_to(base.resolve())
    except ValueError as error:
        raise TimingEvidenceError("artifact_ref_escape", label) from error
    if not target.is_file():
        raise TimingEvidenceError("artifact_missing", f"{label}: {ref['path']}")
    if sha256_file(target) != ref["sha256"]:
        raise TimingEvidenceError("source_hash_drift", label)
    return target


def input_ref(path: Path) -> dict[str, str]:
    try:
        relative = path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError as error:
        raise TimingEvidenceError("input_outside_owner", "timing input must stay in the self-media repository") from error
    return {"owner": "self-media-creation-system", "path": relative, "sha256": sha256_file(path)}


def normalized(value: str) -> str:
    return " ".join(value.split())


def load_profile(binding: dict[str, Any]) -> dict[str, Any]:
    path = resolve_owner_ref(binding, "timing_profile_binding")
    if path.resolve() != PROFILE_PATH.resolve():
        raise TimingEvidenceError("timing_profile_not_canonical", "use the repository-owned timing profile")
    profile = load_json(path)
    expected_top = {"schema_version", "profile_id", "status", "applies_to", "thresholds", "interpretation"}
    if set(profile) != expected_top:
        raise TimingEvidenceError("timing_profile_invalid", "unexpected profile fields")
    if profile["schema_version"] != "short-video-timing-profile.v1" or profile["profile_id"] != "current-operating-hypothesis":
        raise TimingEvidenceError("timing_profile_invalid", "profile identity drifted")
    if profile["status"] != "operating-hypothesis-not-platform-fact" or profile["applies_to"] != "short-video-narration":
        raise TimingEvidenceError("timing_heuristic_promoted", "timing values are operating hypotheses, not platform facts")
    thresholds = profile["thresholds"]
    required = {
        "audience_stake_max_seconds", "reason_to_continue_max_seconds",
        "first_information_advance_max_seconds", "information_advance_gap_max_seconds",
        "main_payoff_max_completion_ratio", "minimum_information_advances",
    }
    if set(thresholds) != required or any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in thresholds.values()):
        raise TimingEvidenceError("timing_profile_invalid", "threshold fields are incomplete")
    interpretation = profile["interpretation"]
    if interpretation != {
        "faster_advances_allowed": True,
        "main_payoff_may_appear_earlier": True,
        "thresholds_are_platform_guarantees": False,
        "final_cut_must_be_measured_separately": True,
    }:
        raise TimingEvidenceError("timing_profile_invalid", "profile interpretation drifted")
    return profile


def load_script(binding: dict[str, Any], content_id: str) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    path = resolve_owner_ref(binding, "script_binding")
    script = load_json(path)
    schema = STUDIO / "schemas" / "case-video-script.v1.schema.json"
    if not schema.is_file():
        raise TimingEvidenceError("owner_schema_unavailable", str(schema))
    validate_schema(script, schema, "case_video_script")
    if script["content_id"] != content_id:
        raise TimingEvidenceError("content_identity_drift", "script content_id differs from timing input")
    segments = {row["segment_id"]: row for row in script["segments"]}
    if len(segments) != len(script["segments"]):
        raise TimingEvidenceError("duplicate_script_segment", "script segment IDs must be unique")
    return script, segments


def load_story_design(
    binding: dict[str, Any] | None,
    structure_route: str,
    content_id: str,
) -> dict[str, Any] | None:
    if structure_route == "direct-answer":
        if binding is not None:
            raise TimingEvidenceError("story_binding_unexpected", "direct-answer timing does not invent a story card")
        return None
    if binding is None:
        raise TimingEvidenceError("story_binding_required", "story-arc timing must bind the actual Story Design Card")
    path = resolve_owner_ref(binding, "story_design_binding")
    if binding["owner"] != "self-media-creation-system":
        raise TimingEvidenceError("story_binding_owner_invalid", "Story Design Card is owned by self-media")
    spec = importlib.util.spec_from_file_location("timing_story_design_gate", ROOT / "scripts" / "story_design_gate.py")
    assert spec and spec.loader
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    story = load_json(path)
    try:
        gate.validate_receipt(story)
    except Exception as error:
        raise TimingEvidenceError("story_design_invalid", str(error)) from error
    if story["content_id"] != content_id:
        raise TimingEvidenceError("content_identity_drift", "Story Design Card content_id differs from timing input")
    if story["format_design"]["format_id"] != "short-video-narration" or not isinstance(story["timing_design"], dict):
        raise TimingEvidenceError("story_timing_not_applicable", "bound story must use the short-video profile")
    return story


def effective_thresholds(profile: dict[str, Any], story: dict[str, Any] | None) -> dict[str, float | int]:
    source = profile["thresholds"]
    values: dict[str, float | int] = {
        "audience_stake_max_seconds": source["audience_stake_max_seconds"],
        "reason_to_continue_max_seconds": source["reason_to_continue_max_seconds"],
        "first_information_advance_max_seconds": source["first_information_advance_max_seconds"],
        "information_advance_gap_max_seconds": source["information_advance_gap_max_seconds"],
        "main_payoff_max_completion_ratio": source["main_payoff_max_completion_ratio"],
        "minimum_information_advances": int(source["minimum_information_advances"]),
    }
    if story is not None:
        design = story["timing_design"]
        values.update(
            audience_stake_max_seconds=min(values["audience_stake_max_seconds"], design["audience_stake_visible_by_second"]),
            reason_to_continue_max_seconds=min(values["reason_to_continue_max_seconds"], design["reason_to_continue_visible_by_second"]),
            first_information_advance_max_seconds=min(values["first_information_advance_max_seconds"], design["first_information_advance_by_second"]),
            information_advance_gap_max_seconds=min(values["information_advance_gap_max_seconds"], design["maximum_gap_between_advances_seconds"]),
            main_payoff_max_completion_ratio=min(values["main_payoff_max_completion_ratio"], design["main_payoff_by_completion_ratio"]),
        )
    return values


def validate_timeline(
    value: dict[str, Any],
    segments: dict[str, dict[str, Any]],
    thresholds: dict[str, float | int],
) -> tuple[dict[str, Any], dict[str, Any]]:
    duration = float(value["measured_duration_seconds"])
    if not math.isfinite(duration):
        raise TimingEvidenceError("duration_invalid", "measured duration must be finite")
    rows = value["timeline"]
    ids = [row["entry_id"] for row in rows]
    if len(ids) != len(set(ids)):
        raise TimingEvidenceError("duplicate_timeline_entry", "timeline entry IDs must be unique")
    previous_end = -1.0
    for row in rows:
        start = float(row["start_seconds"])
        end = float(row["end_seconds"])
        if not all(math.isfinite(item) for item in (start, end)) or end <= start or end > duration:
            raise TimingEvidenceError("timeline_bounds_invalid", row["entry_id"])
        if start < previous_end:
            raise TimingEvidenceError("timeline_order_invalid", "timeline entries must be ordered and non-overlapping")
        previous_end = end
        segment = segments.get(row["segment_id"])
        if segment is None:
            raise TimingEvidenceError("timeline_segment_unknown", row["segment_id"])
        anchor = normalized(row["script_anchor"])
        if anchor not in normalized(segment["spoken_text"]):
            raise TimingEvidenceError("script_anchor_unbound", row["entry_id"])
        if row["alignment_status"] == "exact":
            if anchor not in normalized(row["observed_text"]):
                raise TimingEvidenceError("observed_anchor_unbound", row["entry_id"])
            if row["review_note"] is not None:
                raise TimingEvidenceError("alignment_review_unexpected", row["entry_id"])
        elif not isinstance(row["review_note"], str) or not row["review_note"].strip():
            raise TimingEvidenceError("alignment_review_missing", row["entry_id"])

    by_role: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        for role in row["roles"]:
            by_role.setdefault(role, []).append(row)
    for role in ("audience-stake", "reason-to-continue", "information-advance", "main-payoff"):
        if not by_role.get(role):
            raise TimingEvidenceError("timing_role_missing", role)
    if len(by_role["main-payoff"]) != 1:
        raise TimingEvidenceError("main_payoff_ambiguous", "exactly one main payoff is required")
    if "information-advance" not in by_role["main-payoff"][0]["roles"]:
        raise TimingEvidenceError("main_payoff_not_information_advance", "main payoff must advance the current item")

    advances = sorted(float(row["start_seconds"]) for row in by_role["information-advance"])
    if value["structure_route"] == "direct-answer" and len(advances) == 1:
        # One observed answer can also be the whole payoff. Keep the profile
        # minimum in multi-advance receipts so saved evidence replays as before.
        thresholds = {**thresholds, "minimum_information_advances": 1}
    if len(advances) < int(thresholds["minimum_information_advances"]):
        raise TimingEvidenceError("information_advance_count_low", str(len(advances)))
    gaps = [right - left for left, right in zip(advances, advances[1:])]
    gaps.append(duration - advances[-1])
    maximum_gap = max(gaps)
    stake = min(float(row["start_seconds"]) for row in by_role["audience-stake"])
    reason = min(float(row["start_seconds"]) for row in by_role["reason-to-continue"])
    first_advance = advances[0]
    payoff = float(by_role["main-payoff"][0]["start_seconds"])
    payoff_ratio = payoff / duration
    checks = (
        (stake <= thresholds["audience_stake_max_seconds"], "audience_stake_too_late"),
        (reason <= thresholds["reason_to_continue_max_seconds"], "reason_to_continue_too_late"),
        (first_advance <= thresholds["first_information_advance_max_seconds"], "first_advance_too_late"),
        (maximum_gap <= thresholds["information_advance_gap_max_seconds"], "information_advance_gap_too_long"),
        (payoff_ratio <= thresholds["main_payoff_max_completion_ratio"], "main_payoff_too_late"),
    )
    for passed, code in checks:
        if not passed:
            raise TimingEvidenceError(code, "observed timing did not satisfy the current operating hypothesis")

    continuity = value["continuity_binding"]
    continuity_rows = by_role.get("continuity-promise", [])
    surface = continuity["surface_mode"]
    entry_id = continuity["timeline_entry_id"]
    assessment = continuity["assessment"]
    if surface in {"spoken", "caption"}:
        if assessment != "explicitly-delivered" or entry_id is None or entry_id not in {row["entry_id"] for row in continuity_rows}:
            raise TimingEvidenceError("continuity_binding_missing", "an explicit promise must bind one observed timeline entry")
    elif surface == "profile-consistency":
        if assessment != "profile-only-not-spoken" or entry_id is not None or continuity_rows:
            raise TimingEvidenceError("continuity_surface_drift", "profile consistency is not an observed spoken promise")
    elif assessment != "intentionally-not-surfaced" or entry_id is not None or continuity_rows:
        raise TimingEvidenceError("continuity_surface_drift", "not-surfaced content cannot claim an observed promise")

    metrics = {
        "audience_stake_seconds": round(stake, 3),
        "reason_to_continue_seconds": round(reason, 3),
        "first_information_advance_seconds": round(first_advance, 3),
        "maximum_information_advance_gap_seconds": round(maximum_gap, 3),
        "information_advance_count": len(advances),
        "main_payoff_seconds": round(payoff, 3),
        "main_payoff_completion_ratio": round(payoff_ratio, 6),
        "thresholds": copy.deepcopy(thresholds),
    }
    continuity_result = {"surface_mode": surface, "status": assessment, "timeline_entry_id": entry_id}
    return metrics, continuity_result


def create_receipt_from_value(value: dict[str, Any], *, source_ref: dict[str, str]) -> dict[str, Any]:
    validate_schema(value, INPUT_SCHEMA, "timing_input")
    if value["authority"] != AUTHORITY:
        raise TimingEvidenceError("authority_escalation", "timing evidence grants no execution or publication authority")
    profile = load_profile(value["timing_profile_binding"])
    script, segments = load_script(value["script_binding"], value["content_id"])
    story = load_story_design(value["story_design_binding"], value["structure_route"], value["content_id"])
    thresholds = effective_thresholds(profile, story)
    if story is not None and story["timing_design"]["target_duration_seconds"] != script["target_duration_seconds"]:
        raise TimingEvidenceError("target_duration_drift", "script and Story Design Card target durations differ")

    media = value["media_binding"]
    duration_verification = "observed-read-aloud-timecode"
    if value["stage"] == "prerecording-script":
        if media is not None or value["measurement_basis"] != "observed-read-aloud-timecode":
            raise TimingEvidenceError("stage_evidence_mismatch", "prerecord timing uses an observed read-aloud and no media")
    else:
        if media is None or value["measurement_basis"] != "final-cut-timed-transcript":
            raise TimingEvidenceError("stage_evidence_mismatch", "final-cut timing requires an exact media binding and timed transcript")
        media_path = resolve_owner_ref(media, "media_binding")
        if abs(float(media["duration_seconds"]) - float(value["measured_duration_seconds"])) > 0.001:
            raise TimingEvidenceError("media_duration_drift", "timed transcript duration differs from the bound final media")
        if value["synthetic_only"]:
            duration_verification = "synthetic-fixture-declared"
        else:
            probed = probe_media_file(media_path)
            if probed["sha256"] != media["sha256"]:
                raise TimingEvidenceError("media_probe_hash_drift", "ffprobe target differs from the bound final media")
            if abs(float(probed["duration_seconds"]) - float(media["duration_seconds"])) > 0.01:
                raise TimingEvidenceError("media_probe_duration_drift", "ffprobe duration differs from the bound final media")
            duration_verification = "ffprobe-observed"

    metrics, continuity = validate_timeline(value, segments, thresholds)
    seed = canonical_sha256({"input": source_ref, "stage": value["stage"], "content_id": value["content_id"]})
    receipt: dict[str, Any] = {
        "schema_version": "short-video-timing-evidence.v1",
        "evidence_id": f"timing-evidence-{seed[:24]}",
        "generated_at": value["checked_at"],
        "artifact_status": "candidate-only",
        "publication_boundary": "manual-only",
        "content_id": value["content_id"],
        "stage": value["stage"],
        "synthetic_only": value["synthetic_only"],
        "input_binding": copy.deepcopy(source_ref),
        "script_binding": copy.deepcopy(value["script_binding"]),
        "timing_profile_binding": copy.deepcopy(value["timing_profile_binding"]),
        "story_design_binding": copy.deepcopy(value["story_design_binding"]),
        "media_binding": copy.deepcopy(media),
        "measurement_basis": value["measurement_basis"],
        "duration_verification": duration_verification,
        "measured_duration_seconds": value["measured_duration_seconds"],
        "observed_metrics": metrics,
        "continuity_result": continuity,
        "gate_result": "passed",
        "authority": copy.deepcopy(AUTHORITY),
    }
    receipt["receipt_payload_sha256"] = canonical_sha256(receipt)
    validate_schema(receipt, RECEIPT_SCHEMA, "timing_receipt")
    return receipt


def create_receipt(path: Path) -> dict[str, Any]:
    return create_receipt_from_value(load_json(path), source_ref=input_ref(path))


def validate_receipt_value(receipt: dict[str, Any]) -> dict[str, Any]:
    validate_schema(receipt, RECEIPT_SCHEMA, "timing_receipt")
    unsigned = copy.deepcopy(receipt)
    expected_payload = unsigned.pop("receipt_payload_sha256")
    if expected_payload != canonical_sha256(unsigned):
        raise TimingEvidenceError("receipt_hash_drift", "timing receipt payload changed")
    source_path = resolve_owner_ref(receipt["input_binding"], "input_binding")
    expected = create_receipt(source_path)
    if receipt != expected:
        raise TimingEvidenceError("receipt_source_drift", "receipt no longer matches its hash-bound observation input")
    return {
        "status": "passed",
        "evidence_id": receipt["evidence_id"],
        "stage": receipt["stage"],
        "artifact_status": "candidate-only",
        "publication_boundary": "manual-only",
        "execution_authorized": False,
    }


def validate_receipt(path: Path) -> dict[str, Any]:
    return validate_receipt_value(load_json(path))


def allowed_output(path: Path) -> Path:
    candidate = path.resolve()
    if not any(_is_relative_to(candidate, root.resolve()) for root in OUTPUT_ROOTS):
        raise TimingEvidenceError("output_path_prohibited", "timing receipt must stay under a managed runtime root")
    return candidate


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def write_idempotent(path: Path, value: dict[str, Any]) -> str:
    data = json_text(value).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as handle:
            handle.write(data)
        return "created"
    except FileExistsError:
        if not path.is_file() or path.read_bytes() != data:
            raise TimingEvidenceError("output_conflict", "existing timing receipt differs")
        return "already-identical"


def check() -> dict[str, Any]:
    rows = []
    for fixture in FIXTURES:
        first = create_receipt(fixture)
        second = create_receipt(fixture)
        if canonical_bytes(first) != canonical_bytes(second):
            raise TimingEvidenceError("non_deterministic_output", fixture.name)
        validate_receipt_value(first)
        rows.append({"fixture": fixture.relative_to(ROOT).as_posix(), "stage": first["stage"], "evidence_id": first["evidence_id"]})
    return {
        "status": "passed",
        "fixtures": rows,
        "idempotency": "byte-stable",
        "prerecord_does_not_prove_final_cut": True,
        "publication_boundary": "manual-only",
        "execution_authorized": False,
    }


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    commands = value.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create")
    create.add_argument("--input", required=True, type=Path)
    create.add_argument("--output", required=True, type=Path)
    validate = commands.add_parser("validate")
    validate.add_argument("--receipt", required=True, type=Path)
    commands.add_parser("check")
    return value


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "create":
            receipt = create_receipt(args.input.resolve())
            output = allowed_output(args.output)
            status = write_idempotent(output, receipt)
            result = {"status": status, "evidence_id": receipt["evidence_id"], "stage": receipt["stage"], "publication_boundary": "manual-only"}
        elif args.command == "validate":
            result = validate_receipt(args.receipt.resolve())
        else:
            result = check()
        print(json_text(result), end="")
        return 0
    except TimingEvidenceError as error:
        print(json_text({"status": "blocked", "code": error.code, "message": str(error)}), end="", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
