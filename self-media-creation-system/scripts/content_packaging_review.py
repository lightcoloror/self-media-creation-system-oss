#!/usr/bin/env python3
"""Create and validate frozen-body content-packaging review receipts.

This is a deliberately thin, local adapter. It binds a body artifact to one
title, cover brief, and opening after a pre-existing human review credential.
It never publishes, sends, calls a provider, or grants execution authority.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))
from content_review_rules import has_series_dependency

SCHEMA = ROOT / "schemas" / "content-packaging-review.v1.schema.json"
FIXTURE_ROOT = ROOT / "fixtures" / "content-packaging-review-v1"
DEFAULT_INPUT = FIXTURE_ROOT / "synthetic.input.json"
DEFAULT_EXPECTED = FIXTURE_ROOT / "synthetic.expected.json"
DEIDENTIFIED_INPUT = FIXTURE_ROOT / "deidentified-operational.input.json"
DEIDENTIFIED_EXPECTED = FIXTURE_ROOT / "deidentified-operational.expected.json"
OUTPUT_ROOTS = (
    ROOT / ".runtime" / "content-packaging-review",
    ROOT / "tests" / ".runtime" / "content-packaging-review",
)

SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
ABSOLUTE_PATH_RE = re.compile(
    r"(?:[A-Za-z]:[\\/]|\\\\[^\\]|(?<![\w:/])/(?!/)[A-Za-z0-9._~-]+(?:[/\\][^\s<>'\"`]+)*)",
    re.IGNORECASE,
)
SECRET_VALUE_RE = re.compile(
    r"(?:-----BEGIN [A-Z ]*PRIVATE KEY-----|"
    r"\bBearer\s+[A-Za-z0-9._~+/-]{12,}|"
    r"\b(?:ghp_|github_pat_|glpat-|sk-|xox[baprs]-)[A-Za-z0-9_-]{10,}|"
    r"\bAIza[0-9A-Za-z_-]{20,}|"
    r"\b(?:api[_-]?key|access[_-]?token|auth[_-]?token|aws[_-]?secret[_-]?access[_-]?key|"
    r"client[_-]?secret|cookie|password|"
    r"private[_-]?key|refresh[_-]?token|secret[_-]?access[_-]?key|session[_-]?token|"
    r"webhook[_-]?secret)\s*[:=]\s*\S+)",
    re.IGNORECASE,
)
FORBIDDEN_KEYS = {
    "api_key",
    "apikey",
    "access_token",
    "token",
    "secret",
    "client_secret",
    "password",
    "cookie",
    "authorization",
    "raw_customer_text",
    "customer_name",
    "phone",
    "email",
}
SENSITIVE_REF_PARTS = {
    ".git",
    ".env",
    "secret",
    "secrets",
    "private",
    "customers",
    "customer-data",
    "crm",
    "tokens",
}
AUTHORITY = {
    "publish_authorized": False,
    "execution_authorized": False,
    "external_send_authorized": False,
}
SERIES_SEQUENCE_LABEL_RE = re.compile(
    r"(?:"
    r"第\s*(?:\d{1,3}|[一二三四五六七八九十百零〇两]+)\s*(?:集|期|篇|讲|回)"
    r"|(?<![A-Za-z0-9])(?:ep(?:isode)?|part)\s*[.：:#/_-]?\s*0*\d{1,3}(?![A-Za-z0-9])"
    r")",
    re.IGNORECASE,
)


class PackagingReviewError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return sha256_bytes(canonical_bytes(value))


def json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise PackagingReviewError("artifact_missing", str(path)) from error
    except json.JSONDecodeError as error:
        raise PackagingReviewError("invalid_json", f"{path}: {error}") from error
    if not isinstance(value, dict):
        raise PackagingReviewError("invalid_json_root", f"{path} must contain an object")
    return value


def write_json(path: Path, value: Any) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json_text(value), encoding="utf-8", newline="\n")
    except OSError as error:
        raise PackagingReviewError("artifact_write_failed", f"{path}: {error}") from error


def write_receipt_idempotent(path: Path, value: Any) -> str:
    """Write once, accept the same bytes, and reject conflicting old evidence."""

    encoded = json_text(value).encode("utf-8")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with path.open("xb") as handle:
                handle.write(encoded)
            return "created"
        except FileExistsError:
            if not path.is_file():
                raise PackagingReviewError("output_path_prohibited", "receipt output must be a file path")
            if path.read_bytes() != encoded:
                raise PackagingReviewError("output_conflict", "existing receipt bytes differ; choose a new output ref")
            return "already-identical"
    except PackagingReviewError:
        raise
    except OSError as error:
        raise PackagingReviewError("artifact_write_failed", f"{path}: {error}") from error


def require_exact_keys(value: Any, required: set[str], label: str) -> None:
    if not isinstance(value, dict):
        raise PackagingReviewError("invalid_shape", f"{label} must be an object")
    missing = required - set(value)
    extra = set(value) - required
    if missing:
        raise PackagingReviewError("missing_required_field", f"{label} missing: {sorted(missing)}")
    if extra:
        raise PackagingReviewError("unexpected_field", f"{label} extra: {sorted(extra)}")


def require_sha256(value: Any, label: str) -> str:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise PackagingReviewError("invalid_sha256", f"{label} must be a lowercase SHA-256")
    return value


def parse_time(value: Any, label: str) -> datetime:
    if not isinstance(value, str):
        raise PackagingReviewError("invalid_datetime", f"{label} must be an ISO-8601 string")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise PackagingReviewError("invalid_datetime", f"{label}: {value}") from error
    if parsed.tzinfo is None:
        raise PackagingReviewError("invalid_datetime", f"{label} must include an offset")
    return parsed


def reject_sensitive_values(value: Any, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key.lower() in FORBIDDEN_KEYS:
                raise PackagingReviewError("sensitive_field", f"forbidden field {path}.{key}")
            reject_sensitive_values(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            reject_sensitive_values(child, f"{path}[{index}]")
    elif isinstance(value, str):
        if ABSOLUTE_PATH_RE.search(value) or value.lower().startswith("file://"):
            raise PackagingReviewError("sensitive_path", f"absolute or local path at {path}")
        if SECRET_VALUE_RE.search(value):
            raise PackagingReviewError("secret_detected", f"credential-like value at {path}")


def reject_secret_bytes(value: bytes, label: str) -> None:
    text = value.decode("utf-8", errors="ignore")
    if ABSOLUTE_PATH_RE.search(text) or "file://" in text.lower():
        raise PackagingReviewError("sensitive_path", f"absolute or local path in {label}")
    if SECRET_VALUE_RE.search(text):
        raise PackagingReviewError("secret_detected", f"credential-like value in {label}")


def resolve_repo_ref(ref: Any, label: str) -> Path:
    if not isinstance(ref, str) or not ref:
        raise PackagingReviewError("invalid_artifact_ref", f"{label} must be a non-empty repo-relative ref")
    if ABSOLUTE_PATH_RE.search(ref) or ref.startswith(("/", "\\", "file://")) or "://" in ref:
        raise PackagingReviewError("sensitive_path", f"{label} must not be absolute")
    raw = Path(ref)
    if raw.is_absolute() or ".." in raw.parts:
        raise PackagingReviewError("artifact_ref_escape", f"{label} leaves the repository")
    if any(part.lower() in SENSITIVE_REF_PARTS for part in raw.parts):
        raise PackagingReviewError("sensitive_path", f"{label} targets a prohibited path")
    candidate = (ROOT / raw).resolve()
    try:
        candidate.relative_to(ROOT.resolve())
    except ValueError as error:
        raise PackagingReviewError("artifact_ref_escape", f"{label} leaves the repository") from error
    if not candidate.is_file():
        raise PackagingReviewError("artifact_missing", f"{label}: {ref}")
    return candidate


def repo_ref_for_path(path: Path, label: str) -> str:
    candidate = path.resolve()
    try:
        ref = candidate.relative_to(ROOT.resolve()).as_posix()
    except ValueError as error:
        raise PackagingReviewError("artifact_ref_escape", f"{label} must stay inside the repository") from error
    resolve_repo_ref(ref, label)
    return ref


def resolve_output_path(path: Path, receipt: dict[str, Any]) -> Path:
    candidate = path.resolve()
    allowed = False
    for root in OUTPUT_ROOTS:
        try:
            candidate.relative_to(root.resolve())
            allowed = True
            break
        except ValueError:
            continue
    if not allowed:
        raise PackagingReviewError(
            "output_path_prohibited",
            "receipt output must stay under .runtime/content-packaging-review or tests/.runtime/content-packaging-review",
        )
    source_refs = [
        receipt["reviewed_input_binding"]["input_ref"],
        receipt["content_binding"]["body_ref"],
        receipt["human_review"]["credential_ref"],
    ]
    if receipt["privacy_review"] is not None:
        source_refs.append(receipt["privacy_review"]["credential_ref"])
    if candidate in {resolve_repo_ref(ref, "receipt source ref") for ref in source_refs}:
        raise PackagingReviewError("output_overwrites_source", "receipt output cannot replace a reviewed source artifact")
    if candidate.exists() and not candidate.is_file():
        raise PackagingReviewError("output_path_prohibited", "receipt output must be a file path")
    return candidate


def cover_brief(value: Any, label: str = "cover_brief") -> dict[str, Any]:
    require_exact_keys(value, {"headline", "visual_direction", "supporting_text"}, label)
    if not isinstance(value["headline"], str) or not value["headline"].strip():
        raise PackagingReviewError("invalid_packaging", f"{label}.headline is required")
    if not isinstance(value["visual_direction"], str) or not value["visual_direction"].strip():
        raise PackagingReviewError("invalid_packaging", f"{label}.visual_direction is required")
    if value["supporting_text"] is not None and not isinstance(value["supporting_text"], str):
        raise PackagingReviewError("invalid_packaging", f"{label}.supporting_text must be string or null")
    return copy.deepcopy(value)


def reject_series_sequence_label(title: str, cover: dict[str, Any]) -> None:
    """Keep every public-facing series item understandable on its own.

    Retain this public helper name for callers; numbering alone is allowed.
    Reject only an explicit dependency on another item.
    """

    audience_facing = {
        "title": title,
        "cover_brief.headline": cover["headline"],
        "cover_brief.supporting_text": cover["supporting_text"],
    }
    for label, raw_value in audience_facing.items():
        if raw_value is None:
            continue
        normalized = unicodedata.normalize("NFKC", raw_value)
        if has_series_dependency(normalized):
            raise PackagingReviewError(
                "series_dependency_prohibited",
                f"{label} explicitly depends on another item; an episode number alone is allowed",
            )


def normalize_for_excerpt(value: str) -> str:
    """Normalize spacing without changing the reviewed wording."""

    return " ".join(unicodedata.normalize("NFKC", value).split())


def validate_standalone_review(
    value: Any,
    *,
    title: str,
    opening_text: str,
    body_text: str,
    label: str = "standalone_review",
) -> dict[str, Any]:
    """Require evidence that one item pays off without another series item.

    The assessment is deliberately small and human-authored.  Four reviewed
    text anchors must be present in the exact frozen title/opening/body, while dependency flags
    must remain false.  The deterministic phrase check catches explicit
    handoffs such as "先看上一集" or "答案下期揭晓"; it does not forbid a
    self-contained item from mentioning a separate future topic.
    """

    require_exact_keys(
        value,
        {
            "audience_question",
            "entry_strategy",
            "title_cover_opening_same_promise",
            "context_excerpt",
            "progression_excerpts",
            "core_answer_excerpt",
            "payoff_excerpt",
            "current_item_payoff_delivered",
            "insurance_entry_mode",
            "prior_item_required",
            "future_item_required_for_payoff",
        },
        label,
    )
    for key in (
        "audience_question",
        "context_excerpt",
        "core_answer_excerpt",
        "payoff_excerpt",
    ):
        text = value[key]
        if not isinstance(text, str) or not text.strip():
            raise PackagingReviewError("standalone_review_incomplete", f"{label}.{key} is required")
        if len(text) > 1000:
            raise PackagingReviewError("standalone_review_incomplete", f"{label}.{key} is too long")
    for key in ("prior_item_required", "future_item_required_for_payoff"):
        if value[key] is not False:
            raise PackagingReviewError(
                "series_item_not_standalone",
                f"{label}.{key} must be false before packaging review can pass",
            )
    if value["entry_strategy"] not in {
        "life-problem",
        "choice-conflict",
        "counterintuitive-result",
        "specific-loss",
        "specific-number",
        "identity-situation",
        "search-intent",
        "other-reviewed",
    }:
        raise PackagingReviewError(
            "audience_entry_strategy_invalid",
            f"{label}.entry_strategy must name one reviewed audience entry",
        )
    if value["insurance_entry_mode"] not in {
        "life-context-first",
        "search-intent-direct",
        "not-applicable",
    }:
        raise PackagingReviewError(
            "insurance_entry_mode_invalid",
            f"{label}.insurance_entry_mode must preserve the chosen route",
        )
    if value["title_cover_opening_same_promise"] is not True:
        raise PackagingReviewError(
            "packaging_promise_misaligned",
            "title, cover, and opening must make the same promise before review can pass",
        )
    if value["current_item_payoff_delivered"] is not True:
        raise PackagingReviewError(
            "current_item_payoff_missing",
            "the current item must deliver its own payoff before review can pass",
        )

    combined = normalize_for_excerpt(f"{title}\n{opening_text}\n{body_text}")
    for key in ("audience_question", "context_excerpt", "core_answer_excerpt", "payoff_excerpt"):
        excerpt = normalize_for_excerpt(value[key])
        if excerpt not in combined:
            raise PackagingReviewError(
                "standalone_excerpt_missing",
                f"{label}.{key} is not present in the frozen title, opening, or body",
            )

    progression = value["progression_excerpts"]
    if not isinstance(progression, list) or not progression:
        raise PackagingReviewError(
            "information_progression_incomplete",
            f"{label}.progression_excerpts must contain the actual ordered text anchors, at least one",
        )
    normalized_progression: list[str] = []
    for index, excerpt_value in enumerate(progression):
        if not isinstance(excerpt_value, str) or not excerpt_value.strip() or len(excerpt_value) > 1000:
            raise PackagingReviewError(
                "information_progression_incomplete",
                f"{label}.progression_excerpts[{index}] must be a non-empty text anchor",
            )
        normalized_progression.append(normalize_for_excerpt(excerpt_value))
    if len(set(normalized_progression)) != len(normalized_progression):
        raise PackagingReviewError(
            "information_progression_incomplete",
            f"{label}.progression_excerpts must be distinct",
        )
    # Titles are promises, not evidence that the body delivers an answer.
    delivered = normalize_for_excerpt(f"{opening_text}\n{body_text}")
    for key in ("core_answer_excerpt", "payoff_excerpt"):
        if normalize_for_excerpt(value[key]) not in delivered:
            raise PackagingReviewError("payoff_not_in_content", f"{label}.{key} occurs only in packaging")
    cursor = 0
    for index, excerpt in enumerate(normalized_progression):
        position = delivered.find(excerpt, cursor)
        if position < 0:
            raise PackagingReviewError(
                "information_progression_missing",
                f"{label}.progression_excerpts[{index}] is missing or out of order in the frozen content",
            )
        cursor = position + len(excerpt)

    audience_text = "\n".join((title, opening_text, body_text))
    if has_series_dependency(audience_text):
        raise PackagingReviewError(
            "series_dependency_prohibited",
            "the item explicitly requires another episode or withholds its payoff for a later item",
        )
    return copy.deepcopy(value)


def review_scope(
    content_id: str,
    platform: str,
    data_classification: str,
    body_ref: str,
    body_sha256: str,
    title_sha256: str,
    cover_brief_sha256: str,
    opening_sha256: str,
    standalone_review_sha256: str,
) -> str:
    return canonical_sha256(
        {
            "schema_version": "content-packaging-review-scope.v1",
            "content_id": content_id,
            "platform": platform,
            "data_classification": data_classification,
            "body_ref": body_ref,
            "body_sha256": body_sha256,
            "title_sha256": title_sha256,
            "cover_brief_sha256": cover_brief_sha256,
            "opening_sha256": opening_sha256,
            "standalone_review_sha256": standalone_review_sha256,
        }
    )


def privacy_scope(data_classification: str, review_scope_sha256: str) -> str:
    return canonical_sha256(
        {
            "schema_version": "content-packaging-privacy-scope.v1",
            "data_classification": data_classification,
            "review_scope_sha256": review_scope_sha256,
        }
    )


def validate_authority(value: Any, label: str) -> None:
    if value != AUTHORITY:
        raise PackagingReviewError("authority_escalation", f"{label} must not grant publish, execution, or send authority")


def validate_human_credential(
    review: dict[str, Any], expected_scope: str
) -> dict[str, Any]:
    require_exact_keys(
        review,
        {"credential_ref", "credential_sha256", "reviewer", "reviewed_at"},
        "human_review",
    )
    require_sha256(review["credential_sha256"], "human_review.credential_sha256")
    path = resolve_repo_ref(review["credential_ref"], "human_review.credential_ref")
    if sha256_file(path) != review["credential_sha256"]:
        raise PackagingReviewError("credential_hash_drift", "human review credential bytes changed")
    credential = load_json(path)
    reject_sensitive_values(credential, "human_credential")
    require_exact_keys(
        credential,
        {"schema_version", "reviewer", "reviewed_at", "decision", "review_scope_sha256", "authority"},
        "human_credential",
    )
    if credential["schema_version"] != "content-packaging-human-review-credential.v1":
        raise PackagingReviewError("credential_schema_mismatch", "human review credential schema is unsupported")
    if credential["reviewer"] != review["reviewer"] or credential["reviewed_at"] != review["reviewed_at"]:
        raise PackagingReviewError("credential_identity_drift", "human review metadata differs from credential")
    parse_time(credential["reviewed_at"], "human_credential.reviewed_at")
    if credential["decision"] != "approved":
        raise PackagingReviewError("human_review_not_approved", "human review credential is not approved")
    require_sha256(credential["review_scope_sha256"], "human_credential.review_scope_sha256")
    if credential["review_scope_sha256"] != expected_scope:
        raise PackagingReviewError("review_scope_drift", "title, cover, opening, body, content, or platform differs from human review")
    validate_authority(credential["authority"], "human_credential.authority")
    return {
        "credential_ref": review["credential_ref"],
        "credential_sha256": review["credential_sha256"],
        "reviewer": review["reviewer"],
        "reviewed_at": review["reviewed_at"],
        "decision": "approved",
        "review_scope_sha256": expected_scope,
    }


def validate_privacy_credential(
    review: Any, data_classification: str, expected_scope: str
) -> dict[str, Any] | None:
    if data_classification == "synthetic-only":
        if review is not None:
            raise PackagingReviewError("unexpected_privacy_review", "synthetic-only input must use privacy_review: null")
        return None
    if review is None:
        raise PackagingReviewError("privacy_review_required", "deidentified-operational input requires a privacy review receipt")
    require_exact_keys(
        review,
        {"credential_ref", "credential_sha256", "reviewer", "reviewed_at"},
        "privacy_review",
    )
    require_sha256(review["credential_sha256"], "privacy_review.credential_sha256")
    path = resolve_repo_ref(review["credential_ref"], "privacy_review.credential_ref")
    if sha256_file(path) != review["credential_sha256"]:
        raise PackagingReviewError("privacy_credential_hash_drift", "privacy review credential bytes changed")
    credential = load_json(path)
    reject_sensitive_values(credential, "privacy_credential")
    require_exact_keys(
        credential,
        {"schema_version", "reviewer", "reviewed_at", "decision", "privacy_scope_sha256", "authority"},
        "privacy_credential",
    )
    if credential["schema_version"] != "content-packaging-privacy-review-credential.v1":
        raise PackagingReviewError("credential_schema_mismatch", "privacy credential schema is unsupported")
    if credential["reviewer"] != review["reviewer"] or credential["reviewed_at"] != review["reviewed_at"]:
        raise PackagingReviewError("credential_identity_drift", "privacy review metadata differs from credential")
    parse_time(credential["reviewed_at"], "privacy_credential.reviewed_at")
    if credential["decision"] != "passed":
        raise PackagingReviewError("privacy_review_not_passed", "privacy review credential is not passed")
    require_sha256(credential["privacy_scope_sha256"], "privacy_credential.privacy_scope_sha256")
    if credential["privacy_scope_sha256"] != expected_scope:
        raise PackagingReviewError("privacy_scope_drift", "privacy credential does not cover this exact package")
    validate_authority(credential["authority"], "privacy_credential.authority")
    return {
        "credential_ref": review["credential_ref"],
        "credential_sha256": review["credential_sha256"],
        "reviewer": review["reviewer"],
        "reviewed_at": review["reviewed_at"],
        "decision": "passed",
        "privacy_scope_sha256": expected_scope,
    }


def schema_errors(value: Any) -> list[str]:
    schema = load_json(SCHEMA)
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    return [
        f"{'.'.join(str(part) for part in error.absolute_path) or '$'}: {error.message}"
        for error in sorted(validator.iter_errors(value), key=lambda item: [str(part) for part in item.absolute_path])
    ]


def validate_schema(value: Any) -> None:
    errors = schema_errors(value)
    if errors:
        raise PackagingReviewError("schema_validation_failed", errors[0])


def validate_input(value: dict[str, Any]) -> None:
    reject_sensitive_values(value)
    require_exact_keys(
        value,
        {
            "schema_version",
            "content_id",
            "platform",
            "body_ref",
            "body_sha256",
            "title",
            "cover_brief",
            "opening_text",
            "standalone_review",
            "data_classification",
            "human_review",
            "privacy_review",
        },
        "input",
    )
    if value["schema_version"] != "content-packaging-review-input.v1":
        raise PackagingReviewError("schema_version_mismatch", str(value["schema_version"]))
    for key in ("content_id", "platform", "title", "opening_text"):
        if not isinstance(value[key], str) or not value[key].strip():
            raise PackagingReviewError("missing_required_field", f"input.{key} must be non-empty")
    if value["data_classification"] not in {"synthetic-only", "deidentified-operational"}:
        raise PackagingReviewError("classification_invalid", str(value["data_classification"]))
    require_sha256(value["body_sha256"], "input.body_sha256")
    cover = cover_brief(value["cover_brief"])
    reject_series_sequence_label(value["title"], cover)
    standalone = value["standalone_review"]
    if not isinstance(standalone, dict):
        raise PackagingReviewError("standalone_review_incomplete", "input.standalone_review must be an object")


def _create_receipt_from_value(
    value: dict[str, Any], *, input_ref: str, input_sha256: str
) -> dict[str, Any]:
    validate_input(value)
    require_sha256(input_sha256, "reviewed_input_binding.input_sha256")
    input_path = resolve_repo_ref(input_ref, "reviewed_input_binding.input_ref")
    if sha256_file(input_path) != input_sha256:
        raise PackagingReviewError("input_hash_drift", "reviewed package input bytes changed")
    reject_secret_bytes(input_path.read_bytes(), "reviewed package input")
    body_path = resolve_repo_ref(value["body_ref"], "body_ref")
    observed_body_sha = sha256_file(body_path)
    if observed_body_sha != value["body_sha256"]:
        raise PackagingReviewError("body_hash_drift", f"expected {value['body_sha256']}, got {observed_body_sha}")
    reject_secret_bytes(body_path.read_bytes(), "body artifact")
    body_text = body_path.read_text(encoding="utf-8")
    title_sha = sha256_bytes(value["title"].encode("utf-8"))
    cover = cover_brief(value["cover_brief"])
    cover_sha = canonical_sha256(cover)
    opening_sha = sha256_bytes(value["opening_text"].encode("utf-8"))
    standalone = validate_standalone_review(
        value["standalone_review"],
        title=value["title"],
        opening_text=value["opening_text"],
        body_text=body_text,
    )
    standalone_sha = canonical_sha256(standalone)
    scope_sha = review_scope(
        value["content_id"],
        value["platform"],
        value["data_classification"],
        value["body_ref"],
        observed_body_sha,
        title_sha,
        cover_sha,
        opening_sha,
        standalone_sha,
    )
    human = validate_human_credential(value["human_review"], scope_sha)
    privacy_scope_sha = privacy_scope(value["data_classification"], scope_sha)
    privacy = validate_privacy_credential(value["privacy_review"], value["data_classification"], privacy_scope_sha)
    generated_at = human["reviewed_at"]
    if privacy is not None and parse_time(privacy["reviewed_at"], "privacy_review.reviewed_at") > parse_time(
        generated_at, "human_review.reviewed_at"
    ):
        generated_at = privacy["reviewed_at"]
    identity_hash = canonical_sha256(
        {
            "review_scope_sha256": scope_sha,
            "reviewed_input_sha256": input_sha256,
            "human_credential_sha256": human["credential_sha256"],
            "privacy_credential_sha256": None if privacy is None else privacy["credential_sha256"],
        }
    )
    receipt: dict[str, Any] = {
        "schema_version": "content-packaging-review.v1",
        "receipt_id": f"packaging-review-{identity_hash[:24]}",
        "generated_at": generated_at,
        "artifact_status": "candidate-only",
        "publication_boundary": "manual-only",
        "data_classification": value["data_classification"],
        "reviewed_input_binding": {
            "input_ref": input_ref,
            "input_sha256": input_sha256,
        },
        "content_binding": {
            "content_id": value["content_id"],
            "platform": value["platform"],
            "body_ref": value["body_ref"],
            "body_sha256": observed_body_sha,
        },
        "packaging": {
            "title": value["title"],
            "title_sha256": title_sha,
            "cover_brief": cover,
            "cover_brief_sha256": cover_sha,
            "opening_sha256": opening_sha,
            "standalone_review_sha256": standalone_sha,
        },
        "human_review": human,
        "privacy_review": privacy,
        "authority": copy.deepcopy(AUTHORITY),
    }
    receipt["receipt_payload_sha256"] = canonical_sha256(receipt)
    validate_receipt_value(receipt)
    return receipt


def create_receipt(input_path: Path) -> dict[str, Any]:
    input_ref = repo_ref_for_path(input_path, "reviewed package input")
    return _create_receipt_from_value(
        load_json(input_path),
        input_ref=input_ref,
        input_sha256=sha256_file(input_path),
    )


def validate_receipt_value(receipt: dict[str, Any]) -> dict[str, Any]:
    validate_schema(receipt)
    reject_sensitive_values(receipt)
    expected_payload_sha = canonical_sha256({key: value for key, value in receipt.items() if key != "receipt_payload_sha256"})
    if receipt["receipt_payload_sha256"] != expected_payload_sha:
        raise PackagingReviewError("receipt_hash_drift", "receipt payload hash does not match")
    validate_authority(receipt["authority"], "receipt.authority")

    input_binding = receipt["reviewed_input_binding"]
    input_path = resolve_repo_ref(input_binding["input_ref"], "reviewed_input_binding.input_ref")
    if sha256_file(input_path) != input_binding["input_sha256"]:
        raise PackagingReviewError("input_hash_drift", "reviewed package input bytes changed after review")
    reject_secret_bytes(input_path.read_bytes(), "reviewed package input")
    reviewed_input = load_json(input_path)
    validate_input(reviewed_input)
    if reviewed_input["data_classification"] != receipt["data_classification"]:
        raise PackagingReviewError("classification_drift", "receipt classification differs from reviewed input")

    binding = receipt["content_binding"]
    expected_binding = {
        "content_id": reviewed_input["content_id"],
        "platform": reviewed_input["platform"],
        "body_ref": reviewed_input["body_ref"],
        "body_sha256": reviewed_input["body_sha256"],
    }
    if binding != expected_binding:
        raise PackagingReviewError("content_binding_drift", "content binding differs from reviewed input")
    body_path = resolve_repo_ref(binding["body_ref"], "content_binding.body_ref")
    observed_body_sha = sha256_file(body_path)
    if observed_body_sha != binding["body_sha256"]:
        raise PackagingReviewError("body_hash_drift", "frozen body bytes changed after review")
    reject_secret_bytes(body_path.read_bytes(), "body artifact")
    package = receipt["packaging"]
    expected_opening_sha = sha256_bytes(reviewed_input["opening_text"].encode("utf-8"))
    if package["opening_sha256"] != expected_opening_sha:
        raise PackagingReviewError("opening_hash_drift", "opening differs from reviewed input")
    if package["title"] != reviewed_input["title"] or package["cover_brief"] != reviewed_input["cover_brief"]:
        raise PackagingReviewError("packaging_input_drift", "title or cover differs from reviewed input")
    if sha256_bytes(package["title"].encode("utf-8")) != package["title_sha256"]:
        raise PackagingReviewError("title_hash_drift", "title bytes do not match title_sha256")
    if canonical_sha256(package["cover_brief"]) != package["cover_brief_sha256"]:
        raise PackagingReviewError("cover_hash_drift", "cover brief does not match cover_brief_sha256")
    standalone = validate_standalone_review(
        reviewed_input["standalone_review"],
        title=reviewed_input["title"],
        opening_text=reviewed_input["opening_text"],
        body_text=body_path.read_text(encoding="utf-8"),
    )
    expected_standalone_sha = canonical_sha256(standalone)
    if package["standalone_review_sha256"] != expected_standalone_sha:
        raise PackagingReviewError(
            "standalone_review_hash_drift",
            "standalone review differs from the hash-bound reviewed input",
        )
    scope_sha = review_scope(
        binding["content_id"],
        binding["platform"],
        receipt["data_classification"],
        binding["body_ref"],
        binding["body_sha256"],
        package["title_sha256"],
        package["cover_brief_sha256"],
        package["opening_sha256"],
        package["standalone_review_sha256"],
    )
    human = validate_human_credential(reviewed_input["human_review"], scope_sha)
    if receipt["human_review"] != human:
        raise PackagingReviewError("human_review_drift", "human review receipt fields changed")
    privacy_scope_sha = privacy_scope(receipt["data_classification"], scope_sha)
    privacy = validate_privacy_credential(
        reviewed_input["privacy_review"], receipt["data_classification"], privacy_scope_sha
    )
    if receipt["privacy_review"] != privacy:
        raise PackagingReviewError("privacy_review_drift", "privacy review receipt fields changed")
    expected_generated_at = human["reviewed_at"]
    if privacy is not None and parse_time(privacy["reviewed_at"], "privacy_review.reviewed_at") > parse_time(
        expected_generated_at, "human_review.reviewed_at"
    ):
        expected_generated_at = privacy["reviewed_at"]
    if receipt["generated_at"] != expected_generated_at:
        raise PackagingReviewError("generated_at_drift", "generated_at is not bound to the latest review")
    identity_hash = canonical_sha256(
        {
            "review_scope_sha256": scope_sha,
            "reviewed_input_sha256": input_binding["input_sha256"],
            "human_credential_sha256": human["credential_sha256"],
            "privacy_credential_sha256": None if privacy is None else privacy["credential_sha256"],
        }
    )
    if receipt["receipt_id"] != f"packaging-review-{identity_hash[:24]}":
        raise PackagingReviewError("receipt_id_drift", "receipt_id does not match reviewed package")
    return {
        "status": "passed",
        "receipt_id": receipt["receipt_id"],
        "verification_scope": "structural_binding_only",
        "proves_editorial_quality": False,
        "proves_conversion": False,
        "artifact_status": "candidate-only",
        "publication_boundary": "manual-only",
        "execution_authorized": False,
    }


def validate_receipt(path: Path) -> dict[str, Any]:
    return validate_receipt_value(load_json(path))


def check() -> dict[str, Any]:
    checks: list[dict[str, str]] = []
    for input_path, expected_path in (
        (DEFAULT_INPUT, DEFAULT_EXPECTED),
        (DEIDENTIFIED_INPUT, DEIDENTIFIED_EXPECTED),
    ):
        first = create_receipt(input_path)
        second = create_receipt(input_path)
        if canonical_bytes(first) != canonical_bytes(second):
            raise PackagingReviewError("non_deterministic_output", f"repeated create differs: {input_path.name}")
        expected = load_json(expected_path)
        if first != expected:
            raise PackagingReviewError("fixture_drift", f"generated receipt differs: {input_path.name}")
        validate_receipt_value(expected)
        checks.append(
            {
                "fixture": input_path.relative_to(ROOT).as_posix(),
                "receipt_id": first["receipt_id"],
                "idempotency": "byte-stable",
            }
        )
    return {
        "status": "passed",
        "fixtures": checks,
        "idempotency": "byte-stable",
        "artifact_status": "candidate-only",
        "publication_boundary": "manual-only",
        "execution_authorized": False,
    }


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    sub = value.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create", help="create a receipt from an exact reviewed package input")
    create.add_argument("--input", type=Path, required=True)
    create.add_argument("--output", type=Path, required=True)
    validate = sub.add_parser("validate", help="validate receipt, body, and credential hashes")
    validate.add_argument("--receipt", type=Path, required=True)
    sub.add_parser("check", help="run the deterministic synthetic fixture check")
    return value


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "create":
            receipt = create_receipt(args.input.resolve())
            output = resolve_output_path(args.output, receipt)
            write_status = write_receipt_idempotent(output, receipt)
            result = {
                "status": write_status,
                "receipt_ref": output.relative_to(ROOT.resolve()).as_posix(),
                "receipt_id": receipt["receipt_id"],
                "artifact_status": "candidate-only",
                "publication_boundary": "manual-only",
                "execution_authorized": False,
            }
        elif args.command == "validate":
            result = validate_receipt(args.receipt.resolve())
        else:
            result = check()
        result.update(verification_scope="structural_binding_only",
                      proves_editorial_quality=False, proves_conversion=False)
        print(json_text(result), end="")
        return 0
    except PackagingReviewError as error:
        print(json_text({"status": "blocked", "code": error.code, "message": str(error)}), end="", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
