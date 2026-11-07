#!/usr/bin/env python3
"""Create a compact immutable description of the exact manual publication version."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "schemas" / "publication-version-freeze.v1.schema.json"
FIXTURE = ROOT / "fixtures" / "publication-version-freeze-v1" / "synthetic.input.json"
OUTPUT_ROOTS = (ROOT / ".runtime" / "publication-version-freeze", ROOT / "tests" / ".runtime" / "publication-version-freeze")
AUTHORITY = {"publish_authorized": False, "external_send_authorized": False, "execution_authorized": False}


class FreezeError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise FreezeError("artifact_missing", str(path)) from error
    except json.JSONDecodeError as error:
        raise FreezeError("invalid_json", str(error)) from error
    if not isinstance(value, dict):
        raise FreezeError("invalid_json_root", str(path))
    return value


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def probe_media_file(path: Path) -> dict[str, Any]:
    """Read duration and digest from the exact local release file without copying it."""

    if not path.is_file():
        raise FreezeError("media_file_missing", str(path))
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise FreezeError("ffprobe_unavailable", "ffprobe is required to read the release duration")
    completed = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if completed.returncode != 0:
        raise FreezeError("media_probe_failed", completed.stderr.strip() or path.name)
    try:
        duration = round(float(completed.stdout.strip()), 3)
    except ValueError as error:
        raise FreezeError("media_duration_invalid", completed.stdout.strip()) from error
    if duration <= 0:
        raise FreezeError("media_duration_invalid", str(duration))
    return {"sha256": sha256_file(path), "duration_seconds": duration, "media_copy_stored": False}


def exact_keys(value: Any, expected: set[str], label: str) -> None:
    if not isinstance(value, dict) or set(value) != expected:
        raise FreezeError("invalid_shape", f"{label} fields must be {sorted(expected)}")


def validate_input(value: dict[str, Any]) -> None:
    exact_keys(
        value,
        {"schema_version", "frozen_at", "content_id", "source_content_ref", "capacity_mode", "platforms", "title", "cover", "opening", "body_sha256", "media", "publication_boundary"},
        "input",
    )
    if value["schema_version"] != "publication-version-freeze-input.v1":
        raise FreezeError("schema_version_unsupported", str(value["schema_version"]))
    try:
        frozen_at = datetime.fromisoformat(value["frozen_at"])
    except (TypeError, ValueError) as error:
        raise FreezeError("frozen_at_invalid", str(value.get("frozen_at"))) from error
    if frozen_at.tzinfo is None:
        raise FreezeError("frozen_at_invalid", "timezone required")
    if value["capacity_mode"] != "single-master-synchronized":
        raise FreezeError("capacity_mode_drift", "current operation freezes one synchronized master")
    if value["publication_boundary"] != "manual-only":
        raise FreezeError("publication_boundary_drift", "freeze cannot authorize publication")
    if not isinstance(value["platforms"], list) or not value["platforms"] or len(value["platforms"]) != len(set(value["platforms"])):
        raise FreezeError("platforms_invalid", "at least one unique platform is required")
    ref = value["source_content_ref"]
    if not isinstance(ref, str) or Path(ref).is_absolute() or ".." in Path(ref).parts or ":" in ref:
        raise FreezeError("source_ref_unsafe", "source_content_ref must remain repository-relative")
    exact_keys(value["cover"], {"headline", "visual_description", "image_copy_stored"}, "cover")
    if value["cover"]["image_copy_stored"] is not False:
        raise FreezeError("image_copy_prohibited", "store only cover text and visual description")
    exact_keys(value["opening"], {"first_two_sentences"}, "opening")
    sentences = value["opening"]["first_two_sentences"]
    if not isinstance(sentences, list) or not 1 <= len(sentences) <= 2 or not all(isinstance(item, str) and item.strip() for item in sentences):
        raise FreezeError("opening_invalid", "freeze one or two actual opening sentences")
    exact_keys(value["media"], {"sha256", "duration_seconds", "media_copy_stored"}, "media")
    if value["media"]["media_copy_stored"] is not False:
        raise FreezeError("media_copy_prohibited", "store only media hash and duration")
    if not isinstance(value["media"]["duration_seconds"], (int, float)) or isinstance(value["media"]["duration_seconds"], bool) or value["media"]["duration_seconds"] <= 0:
        raise FreezeError("duration_invalid", "duration_seconds must be positive")
    for key in ("body_sha256",):
        if not isinstance(value[key], str) or len(value[key]) != 64 or any(char not in "0123456789abcdef" for char in value[key]):
            raise FreezeError("hash_invalid", key)
    media_hash = value["media"]["sha256"]
    if not isinstance(media_hash, str) or len(media_hash) != 64 or any(char not in "0123456789abcdef" for char in media_hash):
        raise FreezeError("hash_invalid", "media.sha256")


def create(value: dict[str, Any], media_path: Path | None = None) -> dict[str, Any]:
    if media_path is not None:
        value = copy.deepcopy(value)
        value["media"] = probe_media_file(media_path)
    validate_input(value)
    payload = copy.deepcopy(value)
    payload["schema_version"] = "publication-version-freeze.v1"
    payload["artifact_status"] = "frozen-candidate"
    payload["opening"]["sha256"] = digest(payload["opening"]["first_two_sentences"])
    payload["authority"] = AUTHORITY
    payload["freeze_id"] = "publication-freeze-" + digest(value)[:24]
    payload["payload_sha256"] = digest(payload)
    validate_receipt(payload)
    return payload


def validate_receipt(value: dict[str, Any]) -> None:
    schema = load_json(SCHEMA)
    Draft202012Validator.check_schema(schema)
    errors = list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(value))
    if errors:
        raise FreezeError("schema_validation_failed", errors[0].message)
    unsigned = copy.deepcopy(value)
    observed = unsigned.pop("payload_sha256")
    if digest(unsigned) != observed:
        raise FreezeError("payload_hash_drift", "freeze changed after capture")
    if value["opening"]["sha256"] != digest(value["opening"]["first_two_sentences"]):
        raise FreezeError("opening_hash_drift", "opening text no longer matches its hash")


def write(path: Path, value: dict[str, Any]) -> None:
    resolved = path.resolve()
    if not any(resolved.is_relative_to(root.resolve()) for root in OUTPUT_ROOTS):
        raise FreezeError("output_path_prohibited", str(path))
    resolved.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if not resolved.exists() or resolved.read_text(encoding="utf-8") != encoded:
        resolved.write_text(encoded, encoding="utf-8", newline="\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    create_parser = sub.add_parser("create")
    create_parser.add_argument("--input", type=Path, required=True)
    create_parser.add_argument("--output", type=Path, required=True)
    create_parser.add_argument("--media-file", type=Path, help="derive duration and SHA-256 from the exact local release file")
    validate_parser = sub.add_parser("validate")
    validate_parser.add_argument("--input", type=Path, required=True)
    probe_parser = sub.add_parser("probe-media")
    probe_parser.add_argument("--media-file", type=Path, required=True)
    sub.add_parser("check")
    args = parser.parse_args(argv)
    try:
        if args.command == "create":
            value = create(load_json(args.input), media_path=args.media_file)
            write(args.output, value)
            result = {"status": "created", "freeze_id": value["freeze_id"]}
        elif args.command == "validate":
            value = load_json(args.input)
            validate_receipt(value)
            result = {"status": "passed", "freeze_id": value["freeze_id"]}
        elif args.command == "probe-media":
            result = {"status": "passed", "basename": args.media_file.name, "media": probe_media_file(args.media_file)}
        else:
            first = create(load_json(FIXTURE))
            second = create(load_json(FIXTURE))
            if first != second:
                raise FreezeError("non_deterministic", "fixture output changed across runs")
            result = {"status": "passed", "freeze_id": first["freeze_id"], "idempotency": "byte-stable"}
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except FreezeError as error:
        print(json.dumps({"status": "blocked", "code": error.code, "message": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
