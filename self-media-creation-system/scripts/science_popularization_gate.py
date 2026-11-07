#!/usr/bin/env python3
"""Validate a science-popularization review without writing or publishing content."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "schemas" / "science-popularization-review.v1.schema.json"
SOURCE_CARD = ROOT / "docs" / "references" / "cast-science-popularization-guide-2026.v1.json"
FIXTURE = ROOT / "fixtures" / "science-popularization-review-v1" / "synthetic.input.json"
RECIPES = ROOT / "recipes" / "self-media-recipes.v1.json"
BINDING = ROOT / "routing-binding.v1.json"
OUTPUT_ROOTS = (
    ROOT / ".runtime" / "science-popularization-review",
    ROOT / "tests" / ".runtime" / "science-popularization-review",
)
AUTHORITY = {
    "publish_authorized": False,
    "execution_authorized": False,
    "external_send_authorized": False,
}
SHA256_RE = re.compile(r"^[a-f0-9]{64}$")


class ScienceReviewError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ScienceReviewError("artifact_missing", str(path)) from error
    except json.JSONDecodeError as error:
        raise ScienceReviewError("invalid_json", str(error)) from error
    if not isinstance(value, dict):
        raise ScienceReviewError("invalid_shape", "JSON root must be an object")
    return value


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def text_sha256(path: Path) -> str:
    normalized = path.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def exact_keys(value: Any, expected: set[str], label: str) -> None:
    if not isinstance(value, dict) or set(value) != expected:
        raise ScienceReviewError("invalid_shape", f"{label} fields must be {sorted(expected)}")


def resolve_ref(value: Any) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ScienceReviewError("invalid_reference", "reference must be a non-empty repository-relative path")
    candidate = Path(value)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ScienceReviewError("invalid_reference", value)
    resolved = (ROOT / candidate).resolve()
    if not resolved.is_relative_to(ROOT.resolve()) or not resolved.is_file():
        raise ScienceReviewError("artifact_missing", value)
    return resolved


def validate_source_card(path: Path = SOURCE_CARD) -> dict[str, Any]:
    card = load_json(path)
    required = {
        "schema_version", "source_id", "title", "issuing_body", "document_date",
        "official_page_published_at", "official_page_url", "source_type",
        "verification_status", "checked_at", "checked_by", "retrieval",
        "admitted_uses", "authority_limits", "adoption_status",
    }
    exact_keys(card, required, "source_card")
    expected = {
        "schema_version": "reference-source-card.v1",
        "source_id": "cast-science-popularization-guide-2026",
        "title": "科技工作者科普创作指南",
        "issuing_body": "中国科协办公厅",
        "document_date": "2026-04-15",
        "official_page_published_at": "2026-04-17",
        "official_page_url": "https://www.cast.org.cn/xw/tzgg/KXPJ/art/2026/art_f5ab20b92cdf424e8683c31c19ec95fe.html",
        "source_type": "official-guidance",
        "verification_status": "verified-primary-source",
        "adoption_status": "active-local-operational-reference",
    }
    for key, expected_value in expected.items():
        if card.get(key) != expected_value:
            raise ScienceReviewError("source_card_drift", key)
    required_limits = {
        "not-a-medical-diagnosis-or-treatment-standard",
        "not-an-insurance-contract-or-regulatory-source",
        "not-a-platform-growth-or-ranking-guide",
        "not-a-substitute-for-current-domain-evidence",
    }
    if not required_limits.issubset(set(card.get("authority_limits") or [])):
        raise ScienceReviewError("source_authority_overreach", "reference limits are incomplete")
    return card


def routing_errors(
    recipes: dict[str, Any] | None = None,
    binding: dict[str, Any] | None = None,
) -> list[str]:
    recipes = load_json(RECIPES) if recipes is None else recipes
    binding = load_json(BINDING) if binding is None else binding
    indexed = {
        str(row.get("recipe_id") or ""): row
        for row in recipes.get("recipes") or []
        if isinstance(row, dict)
    }
    required_recipe_gates = {
        "moments-short-post": "science-popularization-review-if-science-claim",
        "xhs-evidence-graphic": "science-popularization-review-if-science-claim",
        "case-video-candidate": "science-popularization-review-if-science-claim",
        "context-efficient-rework": "science-popularization-review-invalidated-if-science-text-changed",
    }
    errors = []
    for recipe_id, gate in required_recipe_gates.items():
        if gate not in set((indexed.get(recipe_id) or {}).get("quality_gates") or []):
            errors.append(f"missing recipe routing {recipe_id}:{gate}")
    extension_paths = {
        str(row.get("path") or "")
        for row in binding.get("operational_extensions") or []
        if isinstance(row, dict)
    }
    if "schemas/science-popularization-review.v1.schema.json" not in extension_paths:
        errors.append("operational extension is not registered")
    return errors


def validate_input(value: dict[str, Any]) -> dict[str, Any]:
    expected = {
        "generated_at", "content_id", "content_domains", "body_binding",
        "source_card_ref", "scientific_review", "audience_readability_review", "ai_assistance",
    }
    exact_keys(value, expected, "input")
    if not isinstance(value["content_id"], str) or len(value["content_id"].strip()) < 3:
        raise ScienceReviewError("content_id_invalid", str(value["content_id"]))
    domains = value["content_domains"]
    allowed_domains = {"science", "technology", "health", "medicine", "insurance-medical-cross"}
    if not isinstance(domains, list) or not domains or len(domains) != len(set(domains)) or not set(domains).issubset(allowed_domains):
        raise ScienceReviewError("content_domain_invalid", str(domains))

    body = value["body_binding"]
    exact_keys(body, {"body_ref", "body_sha256"}, "body_binding")
    if not isinstance(body["body_sha256"], str) or not SHA256_RE.fullmatch(body["body_sha256"]):
        raise ScienceReviewError("body_hash_invalid", str(body["body_sha256"]))
    if text_sha256(resolve_ref(body["body_ref"])) != body["body_sha256"]:
        raise ScienceReviewError("body_hash_drift", "frozen body changed after review")

    source_path = resolve_ref(value["source_card_ref"])
    if source_path != SOURCE_CARD.resolve():
        raise ScienceReviewError("source_card_not_canonical", value["source_card_ref"])
    validate_source_card(source_path)

    scientific = value["scientific_review"]
    scientific_keys = {
        "decision", "claims_checked_against_current_authoritative_sources",
        "source_ledger_complete", "data_and_citation_currency_checked",
        "concepts_and_definitions_checked", "ai_output_not_used_as_evidence",
        "individual_case_not_generalized", "controversy_status",
        "material_limitations_visible", "subject_matter_review_status", "evidence_refs",
    }
    exact_keys(scientific, scientific_keys, "scientific_review")
    if scientific["decision"] != "passed":
        raise ScienceReviewError("scientific_review_blocked", "scientific review must pass")
    boolean_checks = scientific_keys - {"decision", "controversy_status", "subject_matter_review_status", "evidence_refs"}
    if any(scientific[key] is not True for key in boolean_checks):
        raise ScienceReviewError("scientific_review_incomplete", "all scientific integrity checks must pass")
    if scientific["subject_matter_review_status"] != "passed":
        raise ScienceReviewError("subject_matter_review_missing", "science and health claims require a human subject-matter check")
    if scientific["controversy_status"] not in {"none", "represented"}:
        raise ScienceReviewError("controversy_unresolved", str(scientific["controversy_status"]))
    evidence_refs = scientific["evidence_refs"]
    if not isinstance(evidence_refs, list) or not evidence_refs:
        raise ScienceReviewError("evidence_missing", "at least one current evidence reference is required")
    for ref in evidence_refs:
        resolve_ref(ref)
    if scientific["controversy_status"] == "represented" and len(set(evidence_refs)) < 2:
        raise ScienceReviewError("controversy_coverage_missing", "represented controversy needs at least two evidence references")

    audience = value["audience_readability_review"]
    audience_keys = {
        "decision", "primary_audience", "reviewer_roles", "jargon_explained",
        "structure_and_information_density_fit", "feedback_resolved", "review_evidence_refs",
    }
    exact_keys(audience, audience_keys, "audience_readability_review")
    if audience["decision"] != "passed":
        raise ScienceReviewError("audience_review_blocked", "readability review must pass")
    if not isinstance(audience["primary_audience"], str) or not audience["primary_audience"].strip():
        raise ScienceReviewError("audience_missing", "primary audience is required")
    roles = audience["reviewer_roles"]
    if not isinstance(roles, list) or "target-audience-representative" not in roles:
        raise ScienceReviewError("target_audience_review_missing", "a target-audience representative must review the frozen body")
    if any(audience[key] is not True for key in ("jargon_explained", "structure_and_information_density_fit", "feedback_resolved")):
        raise ScienceReviewError("audience_review_incomplete", "readability findings must be resolved")
    review_refs = audience["review_evidence_refs"]
    if not isinstance(review_refs, list) or not review_refs:
        raise ScienceReviewError("audience_review_evidence_missing", "readability review evidence is required")
    for ref in review_refs:
        resolve_ref(ref)

    ai = value["ai_assistance"]
    ai_keys = {
        "used", "functions", "nonpublic_or_sensitive_input_provided",
        "input_deidentification_status", "factual_output_review",
        "disclosure_assessment", "disclosure_rationale",
    }
    exact_keys(ai, ai_keys, "ai_assistance")
    if not isinstance(ai["used"], bool):
        raise ScienceReviewError("ai_usage_invalid", "used must be boolean")
    if ai["nonpublic_or_sensitive_input_provided"] is not False:
        raise ScienceReviewError("ai_sensitive_input_blocked", "nonpublic or sensitive input must not enter the AI route")
    if not isinstance(ai["disclosure_rationale"], str) or not ai["disclosure_rationale"].strip():
        raise ScienceReviewError("ai_disclosure_assessment_missing", "a current labeling assessment is required")
    if ai["used"]:
        if ai["functions"] == ["none"] or ai["input_deidentification_status"] != "passed" or ai["factual_output_review"] != "passed":
            raise ScienceReviewError("ai_review_incomplete", "AI-assisted text requires deidentification and factual review")
        if ai["disclosure_assessment"] == "no-ai-used":
            raise ScienceReviewError("ai_disclosure_inconsistent", "AI use cannot be recorded as no-ai-used")
    else:
        if ai["functions"] != ["none"] or ai["disclosure_assessment"] != "no-ai-used":
            raise ScienceReviewError("ai_usage_inconsistent", "no-AI input must use the no-AI markers")
    return copy.deepcopy(value)


def create_receipt(input_path: Path) -> dict[str, Any]:
    value = validate_input(load_json(input_path))
    payload = {
        "schema_version": "science-popularization-review.v1",
        "review_id": "science-review-" + canonical_sha256(value)[:24],
        "generated_at": value["generated_at"],
        "artifact_status": "candidate-only",
        "publication_boundary": "manual-only",
        "content_id": value["content_id"],
        "content_domains": value["content_domains"],
        "body_binding": value["body_binding"],
        "source_basis": {
            "source_id": "cast-science-popularization-guide-2026",
            "source_card_ref": value["source_card_ref"],
            "use_role": "methodology-quality-baseline",
            "authority_limits_preserved": True,
        },
        "scientific_review": value["scientific_review"],
        "audience_readability_review": value["audience_readability_review"],
        "ai_assistance": value["ai_assistance"],
        "gate_status": "passed",
        "release_status": "review-required",
        "next_gate": "author-plus-subject-matter-check",
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
        raise ScienceReviewError("receipt_hash_drift", "receipt changed after review")
    if text_sha256(resolve_ref(value["body_binding"]["body_ref"])) != value["body_binding"]["body_sha256"]:
        raise ScienceReviewError("body_hash_drift", "frozen body changed after review")
    validate_source_card(resolve_ref(value["source_basis"]["source_card_ref"]))


def write_receipt(path: Path, value: dict[str, Any]) -> str:
    resolved = path.resolve()
    if not any(resolved.is_relative_to(root.resolve()) for root in OUTPUT_ROOTS):
        raise ScienceReviewError("output_path_prohibited", "output must stay under a review runtime root")
    encoded = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as handle:
            handle.write(encoded)
        return "created"
    except FileExistsError:
        if path.read_bytes() != encoded:
            raise ScienceReviewError("output_conflict", "existing output differs")
        return "already-identical"


def check() -> dict[str, Any]:
    first = create_receipt(FIXTURE)
    second = create_receipt(FIXTURE)
    if canonical_bytes(first) != canonical_bytes(second):
        raise ScienceReviewError("non_deterministic", "fixture output is not stable")
    validate_receipt(first)
    errors = routing_errors()
    if errors:
        raise ScienceReviewError("routing_incomplete", "; ".join(errors))
    return {"status": "passed", "idempotency": "byte-stable", "review_id": first["review_id"]}


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
            print(json.dumps({"status": write_receipt(args.output, receipt), "review_id": receipt["review_id"]}, ensure_ascii=False))
        elif args.command == "validate":
            validate_receipt(load_json(args.receipt))
            print(json.dumps({"status": "passed"}))
        else:
            print(json.dumps(check(), ensure_ascii=False, sort_keys=True))
        return 0
    except Exception as error:
        code = error.code if isinstance(error, ScienceReviewError) else "validation_failed"
        print(json.dumps({"status": "blocked", "code": code, "message": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
