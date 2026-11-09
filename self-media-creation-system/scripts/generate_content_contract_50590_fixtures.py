#!/usr/bin/env python3
"""Generate byte-stable synthetic fixtures for the 50590 owner review.

Portable CLI migration: the historical generator inferred one workspace baseline
and wrote two implicit fixture paths. This portable component requires the caller
to name the baseline explicitly (``--baseline``) and the destination directory
explicitly (``--output-dir``). Generated payload content, ordering, schema
versions and synthetic flags are preserved from the historical generator.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path


POSITIVE_FILENAME = "content-contract-50590-owner.v1.json"
NEGATIVE_FILENAME = "content-contract-50590-owner.v1.negative-cases.json"


FIRST = {
    "audience_entry_question": "家庭已经有基础保障时，真正要决定什么？",
    "client_decision": "决定继续补充、暂缓，或先处理现金流问题。",
    "hidden_assumptions": ["保额越多越好", "所有家庭的优先顺序相同"],
    "professional_core_question": "现有风险缺口是否超过家庭可承受范围？",
    "public_expertise_level": "client-usable",
    "question_structure_route": "decision-reframe",
    "scope_boundary": "这是完全虚构的结构 fixture，不构成产品或个案建议。",
    "surface_answer": "先看缺口、现金流和家庭优先事项，再决定是否补充。"
}

SECOND = {
    "current_piece_decision": "本篇只解释决策顺序，不推荐产品。",
    "manual_route_override": {
        "stage": "draft",
        "from": "direct-answer",
        "to": "decision-reframe",
        "reason": "人工判断本篇应先澄清家庭决策任务。",
        "changed_by": "human"
    },
    "next_piece_candidates": ["怎样盘点现金流", "怎样记录已有保障"],
    "planning_scope": "single",
    "series_question": "家庭保障应该按什么顺序梳理？",
    "structure_route": "decision-reframe",
    "structure_route_note": "先回答表面问题，再向前重构一层。"
}


class BaselineError(ValueError):
    """The explicitly selected baseline cannot be used as a fixture baseline."""


def load_baseline(path: Path) -> dict:
    """Read the selected baseline exactly once and validate its top/intent shape."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise BaselineError(f"baseline is not valid JSON: {error}") from error
    if not isinstance(payload, dict):
        raise BaselineError("baseline JSON top level must be an object")
    if not isinstance(payload.get("intent"), dict):
        raise BaselineError("baseline intent must be an object")
    return payload


def clone_with(baseline: dict, field: str | None = None, value: object | None = None) -> dict:
    payload = copy.deepcopy(baseline)
    if field is not None:
        payload["intent"][field] = copy.deepcopy(value)
    return payload


def temporary_path(path: Path) -> Path:
    return path.with_suffix(path.suffix + ".tmp")


def write(path: Path, value: dict) -> None:
    rendered = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    temporary = temporary_path(path)
    temporary.write_text(rendered, encoding="utf-8", newline="\n")
    temporary.replace(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="generate_content_contract_50590_fixtures.py",
        description="Generate the byte-stable synthetic 50590 owner-review fixture files.",
    )
    parser.add_argument("--baseline", required=True, type=Path, help="explicit baseline content-item JSON file to deep-copy")
    parser.add_argument("--output-dir", required=True, type=Path, help="directory that receives the two generated fixture files")
    args = parser.parse_args(argv)

    positive_path = args.output_dir / POSITIVE_FILENAME
    negative_path = args.output_dir / NEGATIVE_FILENAME
    protected_paths = (
        positive_path,
        negative_path,
        temporary_path(positive_path),
        temporary_path(negative_path),
    )

    try:
        baseline_path = args.baseline.resolve()
        if baseline_path in tuple(path.resolve() for path in protected_paths):
            raise BaselineError(
                "baseline resolves to an output or temporary output file and would be overwritten: "
                f"{baseline_path}"
            )
        baseline = load_baseline(args.baseline)
    except BaselineError as error:
        print(f"{parser.prog}: error: {error}", file=sys.stderr)
        return 2

    cases = {"legacy_baseline": clone_with(baseline)}
    for field, value in FIRST.items():
        cases[field] = clone_with(baseline, field, value)
    for field, value in SECOND.items():
        cases[field] = clone_with(baseline, field, value)
    all_fields = clone_with(baseline)
    all_fields["intent"].update(copy.deepcopy(FIRST))
    all_fields["intent"].update(copy.deepcopy(SECOND))
    cases["all_fields"] = all_fields

    positive = {
        "schema_version": "content-contract-50590-owner-fixture.v1",
        "synthetic_only": True,
        "positive_cases": cases,
    }
    negative = {
        "schema_version": "content-contract-50590-owner-negative-fixture.v1",
        "synthetic_only": True,
        "cases": [
            {"id": "invalid_audience_entry_question", "kind": "field_negative", "field": "audience_entry_question", "operations": [{"action": "set", "path": "intent.audience_entry_question", "value": 7}], "expect_schema_valid": False, "expect_facade_accepted": False},
            {"id": "invalid_client_decision", "kind": "field_negative", "field": "client_decision", "operations": [{"action": "set", "path": "intent.client_decision", "value": ["not", "a", "string"]}], "expect_schema_valid": False, "expect_facade_accepted": False},
            {"id": "invalid_hidden_assumptions", "kind": "field_negative", "field": "hidden_assumptions", "operations": [{"action": "set", "path": "intent.hidden_assumptions", "value": "not-an-array"}], "expect_schema_valid": False, "expect_facade_accepted": False},
            {"id": "invalid_professional_core_question", "kind": "field_negative", "field": "professional_core_question", "operations": [{"action": "set", "path": "intent.professional_core_question", "value": False}], "expect_schema_valid": False, "expect_facade_accepted": False},
            {"id": "invalid_public_expertise_level", "kind": "field_negative", "field": "public_expertise_level", "operations": [{"action": "set", "path": "intent.public_expertise_level", "value": "automatic-expert"}], "expect_schema_valid": False, "expect_facade_accepted": False},
            {"id": "invalid_question_structure_route", "kind": "field_negative", "field": "question_structure_route", "operations": [{"action": "set", "path": "intent.question_structure_route", "value": "auto-route"}], "expect_schema_valid": False, "expect_facade_accepted": False},
            {"id": "invalid_scope_boundary", "kind": "field_negative", "field": "scope_boundary", "operations": [{"action": "set", "path": "intent.scope_boundary", "value": {"publication_authorized": True}}], "expect_schema_valid": False, "expect_facade_accepted": False},
            {"id": "invalid_surface_answer", "kind": "field_negative", "field": "surface_answer", "operations": [{"action": "set", "path": "intent.surface_answer", "value": None}], "expect_schema_valid": False, "expect_facade_accepted": False},
            {"id": "invalid_current_piece_decision", "kind": "field_negative", "field": "current_piece_decision", "operations": [{"action": "set", "path": "intent.current_piece_decision", "value": 0}], "expect_schema_valid": False, "expect_facade_accepted": False},
            {"id": "override_nonhuman", "kind": "field_negative", "field": "manual_route_override", "operations": [{"action": "set", "path": "intent.manual_route_override.changed_by", "value": "agent"}], "expect_schema_valid": False, "expect_facade_accepted": False},
            {"id": "invalid_next_piece_candidates", "kind": "field_negative", "field": "next_piece_candidates", "operations": [{"action": "set", "path": "intent.next_piece_candidates", "value": "not-an-array"}], "expect_schema_valid": False, "expect_facade_accepted": False},
            {"id": "invalid_planning_scope", "kind": "field_negative", "field": "planning_scope", "operations": [{"action": "set", "path": "intent.planning_scope", "value": "auto-publish"}], "expect_schema_valid": False, "expect_facade_accepted": False},
            {"id": "invalid_series_question", "kind": "field_negative", "field": "series_question", "operations": [{"action": "set", "path": "intent.series_question", "value": []}], "expect_schema_valid": False, "expect_facade_accepted": False},
            {"id": "invalid_structure_route", "kind": "field_negative", "field": "structure_route", "operations": [{"action": "set", "path": "intent.structure_route", "value": "automatic-send"}], "expect_schema_valid": False, "expect_facade_accepted": False},
            {"id": "invalid_structure_route_note", "kind": "field_negative", "field": "structure_route_note", "operations": [{"action": "set", "path": "intent.structure_route_note", "value": False}], "expect_schema_valid": False, "expect_facade_accepted": False},
            {"id": "override_missing_reason", "operations": [{"action": "delete", "path": "intent.manual_route_override.reason"}], "expect_schema_valid": False, "expect_facade_accepted": False},
            {"id": "override_unknown_stage", "operations": [{"action": "set", "path": "intent.manual_route_override.stage", "value": "publish"}], "expect_schema_valid": False, "expect_facade_accepted": False},
            {"id": "publication_boundary_automatic", "operations": [{"action": "set", "path": "publication.boundary", "value": "automatic"}], "expect_schema_valid": False, "expect_facade_accepted": False},
            {"id": "publication_receipt_attached", "operations": [{"action": "set", "path": "publication.receipts", "value": [{"channel": "synthetic", "published_at": "2026-08-14T00:00:00Z"}]}], "expect_schema_valid": True, "expect_facade_accepted": False},
            {"id": "status_publish_ready", "operations": [{"action": "set", "path": "status", "value": "publish-ready"}], "expect_schema_valid": True, "expect_facade_accepted": False},
            {"id": "status_published", "operations": [{"action": "set", "path": "status", "value": "published"}], "expect_schema_valid": True, "expect_facade_accepted": False},
            {"id": "execution_authorized_extra", "operations": [{"action": "set", "path": "execution_authorized", "value": True}], "expect_schema_valid": False, "expect_facade_accepted": False},
            {"id": "privacy_gate_removed", "operations": [{"action": "delete", "path": "gates.privacy"}], "expect_schema_valid": False, "expect_facade_accepted": False},
            {"id": "privacy_gate_blocked_preserved", "operations": [{"action": "set", "path": "gates.privacy.status", "value": "blocked"}], "expect_schema_valid": True, "expect_facade_accepted": True},
            {"id": "review_gate_needs_review_preserved", "operations": [{"action": "set", "path": "gates.compliance.status", "value": "needs-review"}], "expect_schema_valid": True, "expect_facade_accepted": True},
            {"id": "unknown_intent_field", "operations": [{"action": "set", "path": "intent.send_externally", "value": True}], "expect_schema_valid": False, "expect_facade_accepted": False}
        ]
    }

    args.output_dir.mkdir(parents=True, exist_ok=True)
    write(positive_path, positive)
    write(negative_path, negative)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
