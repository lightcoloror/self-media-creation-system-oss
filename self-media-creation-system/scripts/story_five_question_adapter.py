#!/usr/bin/env python3
"""Project five story questions onto the existing Story Design Card input.

The adapter proves that each short answer already exists in the bound story card.
It cannot introduce a new story fact, state, workflow, or publication authority.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "schemas" / "story-five-question-adapter.v1.schema.json"
FIXTURE = ROOT / "fixtures" / "story-five-question-adapter-v1" / "synthetic.input.json"
OUTPUT_ROOTS = (ROOT / ".runtime", ROOT / "outputs" / "test-temp", ROOT / "tests" / ".runtime")
FIELD_MAPPING = {
    "protagonist": ["protagonist.role"],
    "goal": ["protagonist.immediate_goal"],
    "obstacle": ["pressure[*].description"],
    "stakes": ["choice_under_pressure.cost_or_tradeoff"],
    "why_now": ["inciting_incident.event"],
}
AUTHORITY = {
    "publication": False,
    "external_send": False,
    "customer_contact": False,
    "crm_write": False,
    "knowledge_base_write": False,
}


class FiveQuestionError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise FiveQuestionError("json_root_invalid", f"expected object: {path}")
    return value


def resolve_repo_ref(ref: str) -> Path:
    candidate = Path(ref)
    if candidate.is_absolute() or ":" in ref or ref.startswith(("http://", "https://", "file://")):
        raise FiveQuestionError("reference_scope_invalid", ref)
    resolved = (ROOT / candidate).resolve()
    if not resolved.is_relative_to(ROOT.resolve()) or not resolved.is_file():
        raise FiveQuestionError("reference_missing", ref)
    return resolved


def load_story_gate() -> Any:
    path = ROOT / "scripts" / "story_design_gate.py"
    spec = importlib.util.spec_from_file_location("story_design_gate_for_five_questions", path)
    if spec is None or spec.loader is None:
        raise FiveQuestionError("story_gate_unavailable", str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def exact_keys(value: Any, expected: set[str], label: str) -> None:
    if not isinstance(value, dict) or set(value) != expected:
        raise FiveQuestionError("field_set_invalid", f"{label} fields do not match the contract")


def validate_input(value: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    exact_keys(value, {"schema_version", "generated_at", "story_card_input_ref", "story_card_input_sha256", "answers"}, "input")
    if value["schema_version"] != "story-five-question-input.v1":
        raise FiveQuestionError("schema_version_unsupported", str(value["schema_version"]))
    exact_keys(value["answers"], set(FIELD_MAPPING), "answers")
    for name, answer in value["answers"].items():
        exact_keys(answer, {"text", "fact_refs"}, f"answers.{name}")
        if not isinstance(answer["text"], str) or not answer["text"].strip():
            raise FiveQuestionError("answer_empty", name)
        if not isinstance(answer["fact_refs"], list) or not answer["fact_refs"]:
            raise FiveQuestionError("answer_fact_refs_missing", name)

    story_path = resolve_repo_ref(value["story_card_input_ref"])
    if file_sha256(story_path) != value["story_card_input_sha256"]:
        raise FiveQuestionError("story_card_hash_drift", value["story_card_input_ref"])
    story = load_json(story_path)
    try:
        load_story_gate().validate_input(story)
    except Exception as error:
        raise FiveQuestionError("story_card_input_invalid", str(error)) from error

    checks = {
        "protagonist": [(story["protagonist"]["role"], story["protagonist"]["goal_fact_refs"])],
        "goal": [(story["protagonist"]["immediate_goal"], story["protagonist"]["goal_fact_refs"])],
        "obstacle": [(item["description"], item["fact_refs"]) for item in story["pressure"]],
        "stakes": [(story["choice_under_pressure"]["cost_or_tradeoff"], story["choice_under_pressure"]["fact_refs"])],
        "why_now": [(story["inciting_incident"]["event"], story["inciting_incident"]["fact_refs"])],
    }
    for name, possibilities in checks.items():
        answer = value["answers"][name]
        matching = [refs for text, refs in possibilities if text == answer["text"]]
        if not matching:
            raise FiveQuestionError("answer_not_in_story_card", name)
        if not any(set(answer["fact_refs"]).issubset(set(refs)) for refs in matching):
            raise FiveQuestionError("answer_fact_ref_drift", name)
    return copy.deepcopy(value), story


def validate_schema(value: dict[str, Any]) -> None:
    errors = sorted(
        Draft202012Validator(load_json(SCHEMA), format_checker=FormatChecker()).iter_errors(value),
        key=lambda item: list(item.absolute_path),
    )
    if errors:
        first = errors[0]
        location = "/".join(str(part) for part in first.absolute_path) or "$"
        raise FiveQuestionError("receipt_schema_invalid", f"{location}: {first.message}")


def create_receipt_from_value(raw_value: dict[str, Any]) -> dict[str, Any]:
    value, _story = validate_input(raw_value)
    payload = copy.deepcopy(value)
    payload["schema_version"] = "story-five-question-adapter.v1"
    payload["adapter_id"] = "story-five-" + canonical_sha256(value)[:24]
    payload["target_contract"] = "story-design-card.v1"
    payload["field_mapping"] = copy.deepcopy(FIELD_MAPPING)
    payload["artifact_status"] = "candidate-only"
    payload["publication_boundary"] = "manual-only"
    payload["authority"] = copy.deepcopy(AUTHORITY)
    payload["receipt_payload_sha256"] = canonical_sha256(payload)
    validate_schema(payload)
    return payload


def create_receipt(path: Path) -> dict[str, Any]:
    return create_receipt_from_value(load_json(path))


def validate_receipt(value: dict[str, Any]) -> None:
    validate_schema(value)
    unsigned = copy.deepcopy(value)
    digest = unsigned.pop("receipt_payload_sha256")
    if canonical_sha256(unsigned) != digest:
        raise FiveQuestionError("receipt_hash_drift", "adapter receipt changed after creation")
    restored = copy.deepcopy(value)
    for key in ("adapter_id", "target_contract", "field_mapping", "artifact_status", "publication_boundary", "authority", "receipt_payload_sha256"):
        restored.pop(key)
    restored["schema_version"] = "story-five-question-input.v1"
    validate_input(restored)


def write_receipt(path: Path, value: dict[str, Any]) -> str:
    resolved = path.resolve()
    if not any(resolved.is_relative_to(root.resolve()) for root in OUTPUT_ROOTS):
        raise FiveQuestionError("output_path_prohibited", "output must stay under .runtime, tests/.runtime, or outputs/test-temp")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n")
    return "created"


def check() -> dict[str, Any]:
    first = create_receipt(FIXTURE)
    second = create_receipt(FIXTURE)
    if canonical_bytes(first) != canonical_bytes(second):
        raise FiveQuestionError("non_deterministic", "fixture output is not byte-stable")
    validate_receipt(first)
    return {"status": "passed", "idempotency": "byte-stable", "adapter_id": first["adapter_id"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create")
    create.add_argument("--input", type=Path, required=True)
    create.add_argument("--output", type=Path, required=True)
    validate = sub.add_parser("validate")
    validate.add_argument("--receipt", type=Path, required=True)
    sub.add_parser("check")
    args = parser.parse_args()
    try:
        if args.command == "create":
            receipt = create_receipt(args.input)
            print(json.dumps({"status": write_receipt(args.output, receipt), "adapter_id": receipt["adapter_id"]}, ensure_ascii=False))
        elif args.command == "validate":
            validate_receipt(load_json(args.receipt))
            print(json.dumps({"status": "passed"}, ensure_ascii=False))
        else:
            print(json.dumps(check(), ensure_ascii=False, sort_keys=True))
        return 0
    except FiveQuestionError as error:
        print(json.dumps({"status": "blocked", "code": error.code, "message": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2
    except Exception as error:
        print(json.dumps({"status": "blocked", "code": "validation_failed", "message": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
