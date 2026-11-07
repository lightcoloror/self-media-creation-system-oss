#!/usr/bin/env python3
"""Capture de-identified story moments without creating a second content lifecycle.

The ledger is append-only candidate evidence. It never drafts copy, contacts a
person, reads a knowledge base, or authorizes publication. A ready observation
may be promoted only through the existing fact-card and story-design gates.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "schemas" / "story-material-observation.v1.schema.json"
FIXTURE = ROOT / "fixtures" / "story-material-observation-v1" / "synthetic.input.json"
DEFAULT_LEDGER = ROOT / "research-ledgers" / "story-material-observations.v1.jsonl"
AUTHORITY = {
    "publish_authorized": False,
    "execution_authorized": False,
    "external_send_authorized": False,
}
FIELD_NAMES = {
    "protagonist_goal", "prior_balance", "inciting_event", "first_attempt",
    "unexpected_feedback", "hardest_choice", "final_result_and_cost",
    "sensory_detail", "audience_meaning",
}
CORE_STORY_FIELDS = FIELD_NAMES - {"sensory_detail"}


class StoryMaterialError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise StoryMaterialError("artifact_missing", str(path)) from error
    except json.JSONDecodeError as error:
        raise StoryMaterialError("invalid_json", str(error)) from error
    if not isinstance(value, dict):
        raise StoryMaterialError("invalid_shape", "JSON root must be an object")
    return value


def exact_keys(value: Any, expected: set[str], label: str) -> None:
    if not isinstance(value, dict) or set(value) != expected:
        raise StoryMaterialError("invalid_shape", f"{label} fields must be {sorted(expected)}")


def validate_field(name: str, value: Any) -> None:
    exact_keys(value, {"status", "text", "fact_refs"}, f"fields.{name}")
    status, text, refs = value["status"], value["text"], value["fact_refs"]
    if status not in {"supplied", "unknown"}:
        raise StoryMaterialError("field_status_invalid", name)
    if status == "unknown" and (text is not None or refs):
        raise StoryMaterialError("unknown_field_has_content", name)
    if status == "supplied" and (not isinstance(text, str) or not text.strip() or not refs):
        raise StoryMaterialError("supplied_field_missing_evidence", name)


def validate_input(value: dict[str, Any]) -> dict[str, Any]:
    expected = {
        "schema_version", "captured_at", "story_source_mode", "source_ref", "source_hash",
        "authorization_status", "identity_treatment", "evidence_status", "privacy_status",
        "fields", "quotation", "created_by", "synthetic_only",
    }
    exact_keys(value, expected, "input")
    if value["schema_version"] != "story-material-input.v1":
        raise StoryMaterialError("schema_version_unsupported", str(value["schema_version"]))
    if value["privacy_status"] != "passed":
        raise StoryMaterialError("privacy_not_cleared", "story material must be de-identified before capture")
    if value["authorization_status"] == "blocked":
        raise StoryMaterialError("authorization_blocked", "blocked material cannot enter the ledger")
    if value["story_source_mode"] == "authorized-interview" and value["authorization_status"] != "confirmed":
        raise StoryMaterialError("interview_authorization_missing", "interview material requires confirmed authorization")
    if value["identity_treatment"] == "authorized-identifiable" and value["authorization_status"] != "confirmed":
        raise StoryMaterialError("identity_authorization_missing", "identifiable material requires confirmed authorization")
    if not isinstance(value["source_ref"], str) or not value["source_ref"] or ".." in value["source_ref"]:
        raise StoryMaterialError("unsafe_source_ref", "use an opaque manual or fixture reference")
    if len(value["source_hash"]) != 64 or any(char not in "0123456789abcdef" for char in value["source_hash"]):
        raise StoryMaterialError("source_hash_invalid", "source_hash must be lowercase SHA-256")

    fields = value["fields"]
    exact_keys(fields, FIELD_NAMES, "fields")
    for name, field in fields.items():
        validate_field(name, field)

    quotation = value["quotation"]
    exact_keys(quotation, {"mode", "text", "fact_refs"}, "quotation")
    if quotation["mode"] == "none" and (quotation["text"] is not None or quotation["fact_refs"]):
        raise StoryMaterialError("unused_quote_has_content", "quotation mode none cannot carry text")
    if quotation["mode"] != "none":
        if not isinstance(quotation["text"], str) or not quotation["text"].strip() or not quotation["fact_refs"]:
            raise StoryMaterialError("quotation_evidence_missing", "a quotation or paraphrase needs text and evidence refs")
    if quotation["mode"] == "confirmed-exact" and value["authorization_status"] != "confirmed":
        raise StoryMaterialError("exact_quote_authorization_missing", "exact quotation requires confirmed authorization")
    return copy.deepcopy(value)


def create_record_from_value(raw_value: dict[str, Any]) -> dict[str, Any]:
    value = validate_input(raw_value)
    missing = sorted(name for name in CORE_STORY_FIELDS if value["fields"][name]["status"] == "unknown")
    ready = not missing and value["evidence_status"] in {"user-confirmed", "verified-source"}
    payload = copy.deepcopy(value)
    payload["schema_version"] = "story-material-observation.v1"
    payload["material_id"] = "storymat-" + canonical_sha256(value)[:24]
    payload["content_status"] = "candidate-only"
    payload["story_route_readiness"] = "ready-for-story-design" if ready else "incomplete"
    payload["missing_story_fields"] = missing
    payload["authority"] = AUTHORITY
    payload["record_sha256"] = canonical_sha256(payload)
    Draft202012Validator(load_json(SCHEMA), format_checker=FormatChecker()).validate(payload)
    return payload


def create_record(path: Path) -> dict[str, Any]:
    return create_record_from_value(load_json(path))


def validate_record(value: dict[str, Any]) -> None:
    Draft202012Validator(load_json(SCHEMA), format_checker=FormatChecker()).validate(value)
    unsigned = copy.deepcopy(value)
    digest = unsigned.pop("record_sha256")
    if canonical_sha256(unsigned) != digest:
        raise StoryMaterialError("record_hash_drift", "story material changed after capture")
    input_value = copy.deepcopy(value)
    for key in ("material_id", "content_status", "story_route_readiness", "missing_story_fields", "authority", "record_sha256"):
        input_value.pop(key)
    input_value["schema_version"] = "story-material-input.v1"
    expected = create_record_from_value(input_value)
    if canonical_bytes(expected) != canonical_bytes(value):
        raise StoryMaterialError("record_semantic_drift", "derived readiness no longer matches the input")


def append_record(ledger: Path, record: dict[str, Any]) -> str:
    resolved = ledger.resolve()
    try:
        resolved.relative_to(ROOT.resolve())
    except ValueError as error:
        raise StoryMaterialError("ledger_path_prohibited", "ledger must stay inside the repository") from error
    if ledger.exists():
        for line in ledger.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            existing = json.loads(line)
            if existing.get("material_id") == record["material_id"]:
                if existing.get("record_sha256") != record["record_sha256"]:
                    raise StoryMaterialError("material_id_collision", record["material_id"])
                return "already-recorded"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with ledger.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
    return "recorded"


def check() -> dict[str, Any]:
    first = create_record(FIXTURE)
    second = create_record(FIXTURE)
    if canonical_bytes(first) != canonical_bytes(second):
        raise StoryMaterialError("non_deterministic", "fixture output is not byte-stable")
    validate_record(first)
    return {
        "status": "passed",
        "idempotency": "byte-stable",
        "material_id": first["material_id"],
        "readiness": first["story_route_readiness"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    evaluate = sub.add_parser("evaluate")
    evaluate.add_argument("--input", type=Path, required=True)
    capture = sub.add_parser("capture")
    capture.add_argument("--input", type=Path, required=True)
    capture.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    verify = sub.add_parser("validate")
    verify.add_argument("--record", type=Path, required=True)
    sub.add_parser("check")
    args = parser.parse_args()
    try:
        if args.command == "evaluate":
            print(json.dumps(create_record(args.input), ensure_ascii=False, sort_keys=True, indent=2))
        elif args.command == "capture":
            record = create_record(args.input)
            print(json.dumps({"status": append_record(args.ledger, record), "material_id": record["material_id"]}, ensure_ascii=False))
        elif args.command == "validate":
            validate_record(load_json(args.record))
            print(json.dumps({"status": "passed"}))
        else:
            print(json.dumps(check(), ensure_ascii=False, sort_keys=True))
        return 0
    except (StoryMaterialError, Exception) as error:
        code = error.code if isinstance(error, StoryMaterialError) else "validation_failed"
        print(json.dumps({"status": "blocked", "code": code, "message": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
