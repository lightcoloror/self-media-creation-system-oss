#!/usr/bin/env python3
"""Validate that platform adaptations share one fact revision without contradiction.

This is a thin, deterministic binding check. It does not extract claims from copy,
write platform variants, approve compliance, or authorize publication.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = REPOSITORY_ROOT.parent
SCHEMA = REPOSITORY_ROOT / "schemas" / "cross-platform-fact-consistency-review.v1.schema.json"
FIXTURE = REPOSITORY_ROOT / "fixtures" / "cross-platform-fact-consistency-v1" / "synthetic.input.json"
OUTPUT_ROOTS = (
    REPOSITORY_ROOT / ".runtime" / "cross-platform-fact-consistency",
    REPOSITORY_ROOT / "tests" / ".runtime" / "cross-platform-fact-consistency",
)
AUTHORITY = {
    "publish_authorized": False,
    "execution_authorized": False,
    "external_send_authorized": False,
}
SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
ABSOLUTE_PATH_RE = re.compile(r"(?:[A-Za-z]:[\\/]|^[/\\])")


class CrossPlatformFactError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def sha256_text_file(path: Path) -> str:
    normalized = path.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise CrossPlatformFactError("artifact_missing", str(path)) from error
    except json.JSONDecodeError as error:
        raise CrossPlatformFactError("invalid_json", str(error)) from error
    if not isinstance(value, dict):
        raise CrossPlatformFactError("invalid_shape", "JSON root must be an object")
    return value


def exact_keys(value: Any, expected: set[str], label: str) -> None:
    if not isinstance(value, dict) or set(value) != expected:
        raise CrossPlatformFactError("invalid_shape", f"{label} fields must be {sorted(expected)}")


def require_sha256(value: Any, label: str) -> str:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise CrossPlatformFactError("hash_invalid", f"{label} must be lowercase SHA-256")
    return value


def parse_time(value: Any, label: str) -> datetime:
    if not isinstance(value, str):
        raise CrossPlatformFactError("invalid_datetime", f"{label} must be an ISO-8601 string")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise CrossPlatformFactError("invalid_datetime", f"{label}: {value}") from error
    if parsed.tzinfo is None:
        raise CrossPlatformFactError("invalid_datetime", f"{label} must include timezone")
    return parsed


def resolve_workspace_ref(ref: Any) -> Path:
    if not isinstance(ref, str) or not ref or ABSOLUTE_PATH_RE.search(ref) or "://" in ref:
        raise CrossPlatformFactError("unsafe_ref", "references must be workspace-relative")
    raw = Path(ref)
    if raw.is_absolute() or ".." in raw.parts:
        raise CrossPlatformFactError("unsafe_ref", "reference leaves workspace")
    path = (WORKSPACE_ROOT / raw).resolve()
    try:
        path.relative_to(WORKSPACE_ROOT.resolve())
    except ValueError as error:
        raise CrossPlatformFactError("unsafe_ref", "reference leaves workspace") from error
    if not path.is_file():
        raise CrossPlatformFactError("artifact_missing", ref)
    return path


def validate_bound_text(ref: Any, expected_hash: Any, label: str) -> None:
    path = resolve_workspace_ref(ref)
    if sha256_text_file(path) != require_sha256(expected_hash, label):
        raise CrossPlatformFactError("source_hash_drift", f"{label} no longer matches {ref}")


def validate_fact_binding(binding: Any, canonical: dict[str, Any], label: str) -> None:
    exact_keys(binding, {"fact_card_ref", "fact_card_sha256", "revision_id"}, label)
    if binding != canonical:
        raise CrossPlatformFactError("mixed_fact_revision", f"{label} differs from canonical_fact_binding")


def validate_input(value: dict[str, Any]) -> dict[str, Any]:
    exact_keys(
        value,
        {"schema_version", "generated_at", "content_family_id", "canonical_fact_binding", "canonical_claims", "variants", "decision"},
        "input",
    )
    if value["schema_version"] != "cross-platform-fact-consistency-input.v1":
        raise CrossPlatformFactError("schema_version_unsupported", str(value["schema_version"]))
    parse_time(value["generated_at"], "generated_at")
    if not isinstance(value["content_family_id"], str) or not value["content_family_id"].strip():
        raise CrossPlatformFactError("content_family_id_invalid", "content_family_id is required")
    if value["decision"] != "passed":
        raise CrossPlatformFactError("human_review_required", "the declared cross-platform review must pass")

    canonical_binding = value["canonical_fact_binding"]
    exact_keys(canonical_binding, {"fact_card_ref", "fact_card_sha256", "revision_id"}, "canonical_fact_binding")
    if not isinstance(canonical_binding["revision_id"], str) or not canonical_binding["revision_id"].strip():
        raise CrossPlatformFactError("fact_revision_invalid", "revision_id is required")
    validate_bound_text(
        canonical_binding["fact_card_ref"],
        canonical_binding["fact_card_sha256"],
        "canonical_fact_binding.fact_card_sha256",
    )

    canonical_claims = value["canonical_claims"]
    if not isinstance(canonical_claims, list) or not canonical_claims:
        raise CrossPlatformFactError("canonical_claims_missing", "at least one canonical claim is required")
    claims_by_id: dict[str, dict[str, Any]] = {}
    for index, claim in enumerate(canonical_claims):
        exact_keys(claim, {"fact_id", "normalized_claim", "normalized_claim_sha256", "required_core"}, f"canonical_claims[{index}]")
        fact_id = claim["fact_id"]
        if not isinstance(fact_id, str) or not fact_id.strip() or fact_id in claims_by_id:
            raise CrossPlatformFactError("canonical_fact_id_invalid", str(fact_id))
        normalized_claim = claim["normalized_claim"]
        if not isinstance(normalized_claim, str) or not normalized_claim.strip():
            raise CrossPlatformFactError("normalized_claim_invalid", fact_id)
        declared_claim_hash = require_sha256(claim["normalized_claim_sha256"], f"canonical_claims[{index}].normalized_claim_sha256")
        if hashlib.sha256(normalized_claim.encode("utf-8")).hexdigest() != declared_claim_hash:
            raise CrossPlatformFactError("normalized_claim_hash_drift", fact_id)
        if not isinstance(claim["required_core"], bool):
            raise CrossPlatformFactError("required_core_invalid", fact_id)
        claims_by_id[fact_id] = claim

    variants = value["variants"]
    if not isinstance(variants, list) or len(variants) < 2:
        raise CrossPlatformFactError("platform_comparison_missing", "at least two platform variants are required")
    seen_platforms: set[str] = set()
    canonical_ids = set(claims_by_id)
    for index, variant in enumerate(variants):
        exact_keys(variant, {"platform", "artifact_ref", "artifact_sha256", "fact_binding", "claims"}, f"variants[{index}]")
        platform = variant["platform"]
        if not isinstance(platform, str) or not platform.strip() or platform in seen_platforms:
            raise CrossPlatformFactError("platform_duplicate_or_invalid", str(platform))
        seen_platforms.add(platform)
        validate_bound_text(variant["artifact_ref"], variant["artifact_sha256"], f"variants[{index}].artifact_sha256")
        validate_fact_binding(variant["fact_binding"], canonical_binding, f"variants[{index}].fact_binding")

        variant_claims = variant["claims"]
        if not isinstance(variant_claims, list):
            raise CrossPlatformFactError("variant_claims_invalid", platform)
        bound_ids: set[str] = set()
        for claim_index, binding in enumerate(variant_claims):
            exact_keys(binding, {"fact_id", "state", "normalized_claim_sha256", "omission_reason"}, f"variants[{index}].claims[{claim_index}]")
            fact_id = binding["fact_id"]
            if fact_id in bound_ids:
                raise CrossPlatformFactError("variant_fact_id_duplicate", f"{platform}:{fact_id}")
            if fact_id not in claims_by_id:
                raise CrossPlatformFactError("undeclared_platform_claim", f"{platform}:{fact_id}")
            bound_ids.add(fact_id)
            state = binding["state"]
            if state == "present":
                if binding["omission_reason"] is not None:
                    raise CrossPlatformFactError("claim_binding_inconsistent", f"{platform}:{fact_id}")
                if binding["normalized_claim_sha256"] != claims_by_id[fact_id]["normalized_claim_sha256"]:
                    raise CrossPlatformFactError("cross_platform_claim_drift", f"{platform}:{fact_id}")
            elif state == "omitted-for-density":
                if claims_by_id[fact_id]["required_core"]:
                    raise CrossPlatformFactError("core_claim_omitted", f"{platform}:{fact_id}")
                if binding["normalized_claim_sha256"] is not None or binding["omission_reason"] not in {"density", "format", "duration"}:
                    raise CrossPlatformFactError("claim_binding_inconsistent", f"{platform}:{fact_id}")
            else:
                raise CrossPlatformFactError("claim_state_invalid", f"{platform}:{fact_id}")
        if bound_ids != canonical_ids:
            missing = sorted(canonical_ids - bound_ids)
            raise CrossPlatformFactError("variant_claim_ledger_incomplete", f"{platform} missing {missing}")
    return copy.deepcopy(value)


def create_receipt(input_path: Path) -> dict[str, Any]:
    value = validate_input(load_json(input_path))
    payload = {
        "schema_version": "cross-platform-fact-consistency-review.v1",
        "review_id": "cross-platform-facts-" + canonical_sha256(value)[:24],
        "generated_at": value["generated_at"],
        "artifact_status": "candidate-only",
        "publication_boundary": "manual-only",
        "content_family_id": value["content_family_id"],
        "canonical_fact_binding": value["canonical_fact_binding"],
        "canonical_claims": value["canonical_claims"],
        "variants": value["variants"],
        "consistency_status": "passed",
        "release_status": "review-required",
        "next_gate": "platform-packaging-and-human-review",
        "authority": AUTHORITY,
    }
    payload["receipt_payload_sha256"] = canonical_sha256(payload)
    Draft202012Validator(load_json(SCHEMA), format_checker=FormatChecker()).validate(payload)
    return payload


def validate_receipt(value: dict[str, Any]) -> None:
    Draft202012Validator(load_json(SCHEMA), format_checker=FormatChecker()).validate(value)
    unsigned = copy.deepcopy(value)
    digest = unsigned.pop("receipt_payload_sha256")
    if canonical_sha256(unsigned) != digest:
        raise CrossPlatformFactError("receipt_hash_drift", "receipt payload changed after review")
    validate_bound_text(
        value["canonical_fact_binding"]["fact_card_ref"],
        value["canonical_fact_binding"]["fact_card_sha256"],
        "canonical_fact_binding.fact_card_sha256",
    )
    for index, variant in enumerate(value["variants"]):
        validate_bound_text(variant["artifact_ref"], variant["artifact_sha256"], f"variants[{index}].artifact_sha256")


def write_receipt(path: Path, value: dict[str, Any]) -> str:
    resolved = path.resolve()
    if not any(resolved.is_relative_to(root.resolve()) for root in OUTPUT_ROOTS):
        raise CrossPlatformFactError("output_path_prohibited", "output must stay under a gate runtime root")
    encoded = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as handle:
            handle.write(encoded)
        return "created"
    except FileExistsError:
        if path.read_bytes() != encoded:
            raise CrossPlatformFactError("output_conflict", "existing output differs")
        return "already-identical"


def check() -> dict[str, Any]:
    first = create_receipt(FIXTURE)
    second = create_receipt(FIXTURE)
    if canonical_bytes(first) != canonical_bytes(second):
        raise CrossPlatformFactError("non_deterministic", "fixture output is not stable")
    validate_receipt(first)
    return {"status": "passed", "idempotency": "byte-stable", "review_id": first["review_id"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create")
    create.add_argument("--input", type=Path, required=True)
    create.add_argument("--output", type=Path, required=True)
    verify = sub.add_parser("validate")
    verify.add_argument("--receipt", type=Path, required=True)
    sub.add_parser("check")
    args = parser.parse_args()
    try:
        if args.command == "create":
            receipt = create_receipt(args.input)
            status = write_receipt(args.output, receipt)
            print(json.dumps({"status": status, "review_id": receipt["review_id"]}, ensure_ascii=False))
        elif args.command == "validate":
            validate_receipt(load_json(args.receipt))
            print(json.dumps({"status": "passed"}))
        else:
            print(json.dumps(check(), ensure_ascii=False, sort_keys=True))
        return 0
    except (CrossPlatformFactError, Exception) as error:
        code = error.code if isinstance(error, CrossPlatformFactError) else "validation_failed"
        print(json.dumps({"status": "blocked", "code": code, "message": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
