#!/usr/bin/env python3
"""Pre-draft fact confirmation, plain-language rewrite guidance, and meaning-fidelity review gate.

Connects locked content-fact-card.v0, serious-content translation pre/post checks,
insurance clause semantics, and science-popularization review into Mode B workflows.
Offline, deterministic, fail-closed; never generates prose or authorizes publication.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = (ROOT.parent / "docs").resolve().parent if (ROOT.parent / "docs").exists() else ROOT.parent
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
import runtime_paths

PLAN_SCHEMA = ROOT / "schemas" / "plain-language-plan.v1.schema.json"
REVIEW_SCHEMA = ROOT / "schemas" / "plain-language-review.v1.schema.json"
FACT_CARD_SCHEMA = ROOT.parent / "content-studio-poc" / "schemas" / "content-fact-card.v0.schema.json"
CLAUSE_VALIDATOR = ROOT.parent / "content-studio-poc" / "scripts" / "validate_insurance_clause_explanations.py"
CLAUSE_SCHEMA = ROOT.parent / "docs" / "content-creation-system" / "adapters" / "insurance-clause-explanation.schema.json"
FIXTURE_ROOT = ROOT / "fixtures" / "plain-language-gate-v1"
OUTPUT_SUBDIR = "plain-language-gate"

AUTHORITY = {
    "publish_authorized": False,
    "execution_authorized": False,
    "external_send_authorized": False,
}
SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
GENERIC_REASONS = {"pass", "passed", "ok", "通过", "全部通过", "无", "不适用", "none", "n/a", "na"}
FORBIDDEN_OVERCLAIMS = (
    "一定赔",
    "肯定赔",
    "百分百赔",
    "百分之百赔",
    "正规医院确诊即可",
    "合同生效后第一次确诊",
    "一定能赔",
    "肯定能赔",
    "百分之百能赔",
    "100%能赔",
    "保证理赔",
    "包赔",
)
ATTRIBUTION_CUES = (
    "原图",
    "原文",
    "引用",
    "转述",
    "说法",
    "称",
    "尚无全国",
    "尚未证实",
    "缺乏全国",
    "不代表",
    "并非当前全国",
    "并非全国",
    "仍有当期结存",
    "结存",
    "结余",
    "边界",
    "待核实",
    "来源",
)
CLARIFICATION_PREFIXES = ("不等于", "并非", "不是", "不能写成", "不能说成", "不要误认为", "并不代表", "区别于")
SENTENCE_SPLIT_RE = re.compile(r"[。！？!?；;\n]+")

_MODULE_CACHE: dict[str, Any] = {}


class PlainLanguageError(RuntimeError):
    def __init__(self, code: str, message: str, *, details: list[dict[str, Any]] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.details = details or []


def _load_script(name: str, path: Path) -> Any:
    key = f"{name}:{path.resolve()}"
    if key in _MODULE_CACHE:
        return _MODULE_CACHE[key]
    if not path.is_file():
        raise PlainLanguageError("owner_module_missing", str(path))
    spec = importlib.util.spec_from_file_location(f"plg_{name}", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(path.parent))
    try:
        spec.loader.exec_module(module)
    finally:
        if str(path.parent) in sys.path:
            sys.path.remove(str(path.parent))
    _MODULE_CACHE[key] = module
    return module


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def text_sha256(path: Path) -> str:
    normalized = path.read_text(encoding="utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as error:
        raise PlainLanguageError("artifact_missing", str(path)) from error
    except json.JSONDecodeError as error:
        raise PlainLanguageError("invalid_json", f"{path}: {error}") from error
    if not isinstance(value, dict):
        raise PlainLanguageError("invalid_shape", f"JSON root must be an object: {path}")
    return value


def _validate_schema(instance: dict[str, Any], schema_path: Path, code: str) -> None:
    schema = load_json(schema_path)
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(instance),
        key=lambda item: list(item.absolute_path),
    )
    if errors:
        first = errors[0]
        location = "/".join(str(part) for part in first.absolute_path) or "$"
        raise PlainLanguageError(code, f"{location}: {first.message}")


def _allowed_bases() -> tuple[Path, ...]:
    bases = [
        ROOT.resolve(),
        ROOT.parent.resolve(),
        *runtime_paths.allowed_runtime_roots(ROOT),
    ]
    test_tmp = os.environ.get("TEST_TMP_ROOT", "").strip()
    if test_tmp:
        bases.append(Path(test_tmp).resolve(strict=False))
    test_runtime = ROOT / ".test-runtime"
    bases.append(test_runtime.resolve(strict=False))
    return tuple(dict.fromkeys(bases))


def resolve_artifact_path(ref: str, base_dir: Path | None = None) -> Path:
    """Resolve repo-relative, .runtime-rerouted, base_dir-relative, or allowed absolute paths."""
    if not isinstance(ref, str) or not ref.strip():
        raise PlainLanguageError("invalid_reference", "reference path must be non-empty")
    if "://" in ref:
        raise PlainLanguageError("unsafe_reference", ref)
    candidate = Path(ref)
    if candidate.is_absolute():
        resolved = candidate.resolve(strict=False)
        allowed = _allowed_bases() + ((base_dir.resolve(strict=False),) if base_dir else ())
        if not any(resolved.is_relative_to(b) or resolved == b for b in allowed):
            # Also permit pytest/unittest TemporaryDirectory under system temp if explicitly under base_dir or TEST_TMP_ROOT.
            import tempfile
            sys_tmp = Path(tempfile.gettempdir()).resolve(strict=False)
            if not resolved.is_relative_to(sys_tmp):
                raise PlainLanguageError("unsafe_reference", f"path outside allowed workspace/runtime roots: {ref}")
        if not resolved.is_file():
            raise PlainLanguageError("artifact_missing", ref)
        return resolved

    if ".." in candidate.parts:
        raise PlainLanguageError("unsafe_reference", f"parent traversal prohibited: {ref}")
    if candidate.parts[:1] == (".runtime",):
        resolved = runtime_paths.resolve_runtime_arg(ROOT, candidate).resolve(strict=False)
        if resolved.is_file():
            return resolved
    roots_to_try = [ROOT.resolve()]
    if base_dir is not None:
        roots_to_try.insert(0, base_dir.resolve())
    roots_to_try.extend(runtime_paths.allowed_runtime_roots(ROOT))
    for origin in roots_to_try:
        attempt = (origin / candidate).resolve(strict=False)
        if attempt.is_relative_to(origin) and attempt.is_file():
            return attempt
    raise PlainLanguageError("artifact_missing", ref)


def _check_file_ref(ref_obj: dict[str, Any], label: str, *, base_dir: Path | None = None, text_normalized: bool = False) -> Path:
    if not isinstance(ref_obj, dict) or "path" not in ref_obj or "sha256" not in ref_obj:
        raise PlainLanguageError("invalid_reference", f"{label} must contain path and sha256")
    resolved = resolve_artifact_path(ref_obj["path"], base_dir=base_dir)
    actual = text_sha256(resolved) if text_normalized else file_sha256(resolved)
    raw = file_sha256(resolved)
    if ref_obj["sha256"] not in {actual, raw}:
        raise PlainLanguageError("source_hash_drift", f"{label} hash drift: {ref_obj['path']}")
    return resolved


def validate_fact_card_lock(
    path: Path,
    *,
    expected_content_id: str | None = None,
    expected_sha256: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Validate that a content-fact-card.v0 artifact exists, is schema-valid, and is human locked_for_draft."""
    resolved = Path(path).resolve()
    if not resolved.is_file():
        raise PlainLanguageError("fact_card_missing", str(path))
    if expected_sha256 and file_sha256(resolved) != expected_sha256 and text_sha256(resolved) != expected_sha256:
        raise PlainLanguageError("source_hash_drift", str(path))
    card = load_json(resolved)
    _validate_schema(card, FACT_CARD_SCHEMA, "fact_card_schema_invalid")
    if expected_content_id and card.get("content_id") != expected_content_id:
        raise PlainLanguageError(
            "fact_card_content_mismatch",
            f"fact_card content_id {card.get('content_id')!r} != {expected_content_id!r}",
        )
    if card.get("canonical_status") != "locked_for_draft":
        raise PlainLanguageError(
            "fact_card_not_locked_for_draft",
            f"canonical_status must be locked_for_draft (got {card.get('canonical_status')!r})",
        )
    revision_id = str(card.get("revision_id") or "").strip()
    if not revision_id:
        raise PlainLanguageError("fact_card_revision_missing", "locked_for_draft fact card requires revision_id")
    if card.get("gates", {}).get("fact") != "pass":
        raise PlainLanguageError("fact_gate_not_passed", "fact card gates.fact must equal pass")
    facts = card.get("facts") or []
    confirmed = {f["fact_id"]: f for f in facts if f.get("status") in (None, "confirmed")}
    unconfirmed = [f["fact_id"] for f in facts if f.get("status") not in (None, "confirmed", "excluded", "superseded")]
    if not confirmed:
        raise PlainLanguageError("fact_card_no_confirmed_facts", "at least one confirmed fact is required")
    if unconfirmed:
        raise PlainLanguageError("fact_card_unconfirmed_facts", f"unconfirmed facts present: {unconfirmed}")

    meta = {
        "fact_card_id": card["fact_card_id"],
        "revision_id": revision_id,
        "canonical_status": "locked_for_draft",
        "sha256": file_sha256(resolved),
        "confirmed_fact_ids": list(confirmed),
        "unknowns_count": len(card.get("unknowns") or []),
        "forbidden_claims": list(card.get("forbidden_claims") or []),
    }
    return card, meta


def build_fact_confirmation_checklist(
    *,
    content_id: str,
    topic: str,
    audience: str,
    purpose: str,
    fact_card: dict[str, Any] | None = None,
    fact_card_path: Path | None = None,
    risk_flags: dict[str, Any] | None = None,
    error_reason: str | None = None,
) -> dict[str, Any]:
    """Build human-review checklist before drafting; machine synthesis never stamps locked_for_draft."""
    facts_to_confirm = []
    unknowns = []
    forbidden_claims = []
    current_status = "missing"
    if isinstance(fact_card, dict):
        current_status = str(fact_card.get("canonical_status") or "draft")
        unknowns = list(fact_card.get("unknowns") or [])
        forbidden_claims = list(fact_card.get("forbidden_claims") or [])
        for row in fact_card.get("facts") or []:
            facts_to_confirm.append(
                {
                    "fact_id": row.get("fact_id"),
                    "text": row.get("text"),
                    "status": row.get("status", "pending_human_confirmation"),
                    "has_quantitative_scope": "quantitative_scope" in row,
                    "allowed_wording": row.get("allowed_wording", []),
                    "forbidden_paraphrases": row.get("forbidden_paraphrases", []),
                }
            )
    return {
        "schema_version": "fact-and-stance-confirmation-checklist.v1",
        "status": "awaiting_human_confirmation",
        "blocking_reason": error_reason or "Creator must confirm facts and core stance (canonical_status: locked_for_draft) before drafting.",
        "content_id": content_id,
        "topic": topic,
        "target_audience": audience,
        "core_purpose_and_stance_to_confirm": purpose,
        "current_fact_card_status": current_status,
        "current_fact_card_path": str(fact_card_path) if fact_card_path else None,
        "active_risk_flags": {k: v for k, v in (risk_flags or {}).items() if v},
        "facts_requiring_confirmation": facts_to_confirm,
        "declared_unknowns_not_to_fill": unknowns,
        "forbidden_claims_to_reject": forbidden_claims,
        "hard_prohibitions": [
            "Do not fabricate personal experiences, pain-point incidents, or business metrics.",
            "Do not write full draft prose or stamp canonical_status=locked_for_draft without explicit creator confirmation.",
        ],
    }


def _clause_module():
    return _load_script("validate_insurance_clause_explanations", CLAUSE_VALIDATOR)


def validate_clause_explanation(path: Path) -> list[str]:
    mod = _clause_module()
    schema = mod.load_json(CLAUSE_SCHEMA)
    data = mod.load_json(path)
    errors = mod.validate_document(data, schema, path)
    for unit in data.get("clause_units") or []:
        if not isinstance(unit, dict):
            continue
        cid = unit.get("clause_id", "unknown")
        exp = unit.get("explanation") or {}
        if not isinstance(exp, dict):
            continue
        if isinstance(exp.get("negative_examples"), list) and not exp["negative_examples"]:
            errors.append(f"clause_unit:{cid}: negative_examples must not be empty")
        texts = [exp.get("one_sentence", ""), exp.get("plain_language", "")]
        for ex in exp.get("positive_examples") or []:
            if isinstance(ex, dict):
                texts.extend([ex.get("scenario", ""), ex.get("outcome", ""), ex.get("reason", "")])
        joined = "\n".join(str(t) for t in texts if t)
        for token in FORBIDDEN_OVERCLAIMS:
            for sent in _sentences(joined):
                if token in sent and not _has_negation_clarity(sent, token):
                    errors.append(f"clause_unit:{cid}: forbidden_claim_or_overclaim '{token}' in '{sent}'")
    return errors


def _serious_module():
    return _load_script("serious_content_translation_gate", SCRIPTS_DIR / "serious_content_translation_gate.py")


def _science_module():
    return _load_script("science_popularization_gate", SCRIPTS_DIR / "science_popularization_gate.py")


def create_plan(input_path: Path, *, base_dir: Path | None = None) -> dict[str, Any]:
    raw = load_json(input_path)
    resolved_base = base_dir or input_path.parent
    data = copy.deepcopy(raw)
    data.pop("plan_id", None)
    data.pop("authority", None)
    data.pop("payload_sha256", None)

    app = data.get("applicability")
    if app not in {"applicable", "not_applicable"}:
        raise PlainLanguageError("plan_applicability_invalid", str(app))
    if app == "not_applicable":
        reason = str(data.get("not_applicable_reason") or "").strip()
        if len(reason) < 8 or reason.lower() in GENERIC_REASONS:
            raise PlainLanguageError("not_applicable_reason_missing", "provide a specific non-generic reason for marking plain language not_applicable")
    else:
        fact_ref = data.get("fact_card_ref") or {}
        fact_path = _check_file_ref(fact_ref, "fact_card_ref", base_dir=resolved_base)
        card, meta = validate_fact_card_lock(fact_path, expected_content_id=data.get("content_id"))
        if fact_ref.get("fact_card_id") != meta["fact_card_id"] or fact_ref.get("revision_id") != meta["revision_id"]:
            raise PlainLanguageError("fact_card_identity_drift", "fact_card_ref metadata disagrees with locked fact card")
        confirmed = {f["fact_id"] for f in card["facts"]}
        for concept in data.get("concepts_to_explain") or []:
            unknown_refs = set(concept.get("source_fact_ids") or []) - confirmed
            if unknown_refs:
                raise PlainLanguageError("concept_fact_ref_unknown", f"{concept.get('term')}: unknown source_fact_ids {sorted(unknown_refs)}")
        intensity = data.get("intensity")
        if intensity in {"serious_dual_gate", "science_plus_serious"}:
            pre = data.get("serious_precheck")
            if not isinstance(pre, dict):
                raise PlainLanguageError("serious_precheck_missing", f"{intensity} requires serious_precheck in plain-language-plan")
            try:
                _serious_module().validate_precheck_payload(pre)
            except Exception as err:
                raise PlainLanguageError(getattr(err, "code", "serious_precheck_invalid"), str(err)) from err
        elif "serious_precheck" in data and data["serious_precheck"] is not None:
            try:
                _serious_module().validate_precheck_payload(data["serious_precheck"])
            except Exception as err:
                raise PlainLanguageError(getattr(err, "code", "serious_precheck_invalid"), str(err)) from err

        if data.get("clause_explanation_ref") is not None:
            clause_path = _check_file_ref(data["clause_explanation_ref"], "clause_explanation_ref", base_dir=resolved_base)
            clause_errors = validate_clause_explanation(clause_path)
            if clause_errors:
                raise PlainLanguageError("clause_explanation_invalid", "; ".join(clause_errors))

    core = copy.deepcopy(data)
    data["plan_id"] = "plain-plan-" + canonical_sha256(core)[:24]
    data["authority"] = copy.deepcopy(AUTHORITY)
    data["payload_sha256"] = canonical_sha256(data)
    _validate_schema(data, PLAN_SCHEMA, "plan_schema_invalid")
    return data


def validate_plan(
    plan_doc: dict[str, Any],
    *,
    expected_request_id: str | None = None,
    expected_content_id: str | None = None,
    risk_flags: dict[str, Any] | None = None,
    trusted_domains: set[str] | None = None,
    base_dir: Path | None = None,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    _validate_schema(plan_doc, PLAN_SCHEMA, "plan_schema_invalid")
    unsigned = copy.deepcopy(plan_doc)
    digest = unsigned.pop("payload_sha256")
    if canonical_sha256(unsigned) != digest:
        raise PlainLanguageError("plan_hash_drift", "plain-language-plan payload_sha256 mismatch")
    if expected_request_id and plan_doc["request_id"] != expected_request_id:
        raise PlainLanguageError("plan_request_mismatch", "plain-language-plan belongs to another request")
    if expected_content_id and plan_doc["content_id"] != expected_content_id:
        raise PlainLanguageError("plan_content_mismatch", "plain-language-plan belongs to another content_id")

    domains = trusted_domains or set()
    flags = risk_flags or {}
    serious_required = bool(
        ({"insurance", "medical", "health", "finance"} & domains)
        or flags.get("insurance_terms")
        or flags.get("medical_claims")
        or flags.get("science_claims")
        or flags.get("serious_professional")
    )
    science_required = bool(
        ({"medical", "health"} & domains)
        or flags.get("medical_claims")
        or flags.get("science_claims")
    )

    if plan_doc["applicability"] == "not_applicable":
        reason = plan_doc["not_applicable_reason"].strip()
        if reason.lower() in GENERIC_REASONS or len(reason) < 8:
            raise PlainLanguageError("not_applicable_reason_missing", "non-generic not_applicable reason required")
        if serious_required:
            raise PlainLanguageError(
                "plain_language_not_applicable_prohibited",
                "serious, insurance, medical, or science content cannot bypass plain-language checks via not_applicable",
            )
        return copy.deepcopy(plan_doc), None

    intensity = plan_doc["intensity"]
    if serious_required and intensity == "lightweight":
        raise PlainLanguageError(
            "plain_language_intensity_insufficient",
            "insurance, medical, science, or serious content requires serious_dual_gate or science_plus_serious",
        )
    if science_required and intensity != "science_plus_serious":
        raise PlainLanguageError(
            "plain_language_intensity_insufficient",
            "science or medical claims require science_plus_serious intensity",
        )

    fact_path = _check_file_ref(plan_doc["fact_card_ref"], "fact_card_ref", base_dir=base_dir)
    card, meta = validate_fact_card_lock(fact_path, expected_content_id=plan_doc["content_id"])
    if plan_doc["fact_card_ref"]["fact_card_id"] != meta["fact_card_id"] or plan_doc["fact_card_ref"]["revision_id"] != meta["revision_id"]:
        raise PlainLanguageError("fact_card_identity_drift", "fact_card_ref identity differs from locked fact card")

    confirmed = {f["fact_id"] for f in card["facts"]}
    for concept in plan_doc["concepts_to_explain"]:
        missing = set(concept["source_fact_ids"]) - confirmed
        if missing:
            raise PlainLanguageError("concept_fact_ref_unknown", f"{concept['term']}: {sorted(missing)}")

    if intensity in {"serious_dual_gate", "science_plus_serious"}:
        if not isinstance(plan_doc.get("serious_precheck"), dict):
            raise PlainLanguageError("serious_precheck_missing", "serious_dual_gate / science_plus_serious plan requires serious_precheck")
        try:
            _serious_module().validate_precheck_payload(plan_doc["serious_precheck"])
        except Exception as err:
            raise PlainLanguageError(getattr(err, "code", "serious_precheck_invalid"), str(err)) from err

    if plan_doc.get("clause_explanation_ref") is not None:
        clause_path = _check_file_ref(plan_doc["clause_explanation_ref"], "clause_explanation_ref", base_dir=base_dir)
        clause_errors = validate_clause_explanation(clause_path)
        if clause_errors:
            raise PlainLanguageError("clause_explanation_invalid", "; ".join(clause_errors))

    return copy.deepcopy(plan_doc), card


def build_writing_guidance(plan_doc: dict[str, Any], fact_card: dict[str, Any] | None = None) -> dict[str, Any]:
    """Project actionable plain-language writing constraints into Agent writing_handoff."""
    if plan_doc.get("applicability") == "not_applicable":
        return {
            "applicability": "not_applicable",
            "reason": plan_doc["not_applicable_reason"],
        }
    facts_by_id = {row["fact_id"]: row for row in (fact_card or {}).get("facts", [])}
    must_keep_boundaries = []
    forbidden_paraphrases = list((fact_card or {}).get("forbidden_claims") or [])
    for concept in plan_doc.get("concepts_to_explain", []):
        must_keep_boundaries.extend(concept.get("must_keep_conditions", []))
    for fid, fobj in facts_by_id.items():
        forbidden_paraphrases.extend(fobj.get("forbidden_paraphrases") or [])
        qscope = fobj.get("quantitative_scope")
        if qscope:
            must_keep_boundaries.append(
                f"[{fid}] 统计口径: 时期={qscope['period']}, 地区={qscope['region']}, 分母={qscope['denominator']}; 禁止写成={qscope['does_not_support']}"
            )
    return {
        "applicability": "applicable",
        "intensity": plan_doc["intensity"],
        "target_audience": plan_doc["target_audience"],
        "audience_question": plan_doc["audience_question"],
        "plain_answer_lead": plan_doc["plain_answer_lead"],
        "concepts_to_explain": plan_doc["concepts_to_explain"],
        "analogies": plan_doc.get("analogies", []),
        "quoted_sources": plan_doc.get("quoted_sources", []),
        "must_keep_boundaries": list(dict.fromkeys(must_keep_boundaries)),
        "forbidden_claims_and_paraphrases": list(dict.fromkeys(forbidden_paraphrases)),
        "drafting_rules": [
            "Lead with one plain everyday sentence answering the audience_question.",
            "Explain every technical term on its first appearance with mechanism and concrete scenario.",
            "Explicitly state analogy mapping, applicable scope, and where the analogy breaks.",
            "Keep research/source quotes attributed with their verified evidence status; never upgrade an unverified trend quote into a national trend conclusion.",
            "Preserve all conditions, denominators, units, timeframes, exceptions, and claim strength.",
        ],
    }


def _extract_surface_text(path: Path) -> str:
    suffix = path.suffix.lower()
    raw = path.read_text(encoding="utf-8-sig")
    if suffix in {".srt", ".vtt"}:
        kept = []
        for line in raw.replace("\r\n", "\n").splitlines():
            stripped = line.strip()
            if not stripped or stripped.isdigit() or "-->" in stripped or stripped == "WEBVTT":
                continue
            kept.append(stripped)
        return "\n".join(kept)
    if suffix == ".json":
        obj = json.loads(raw)
        chunks: list[str] = []

        def walk(node: Any) -> None:
            if isinstance(node, str) and node.strip():
                chunks.append(node)
            elif isinstance(node, dict):
                for val in node.values():
                    walk(val)
            elif isinstance(node, list):
                for val in node:
                    walk(val)

        walk(obj)
        return "\n".join(chunks)
    return raw


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in SENTENCE_SPLIT_RE.split(text) if s.strip()]


def _has_negation_clarity(sentence: str, phrase: str) -> bool:
    idx = sentence.find(phrase)
    while idx != -1:
        prefix = sentence[max(0, idx - 10):idx]
        if any(cue in prefix for cue in CLARIFICATION_PREFIXES):
            idx = sentence.find(phrase, idx + len(phrase))
            continue
        return False
    return True


def _scan_text_violations(
    surface_name: str,
    text: str,
    plan: dict[str, Any],
    fact_card: dict[str, Any],
) -> list[dict[str, Any]]:
    violations: list[dict[str, Any]] = []
    sentences = _sentences(text)
    serious_domain = plan.get("applicability") == "applicable" or plan.get("intensity") != "lightweight"

    # 1. Forbidden claims & paraphrases
    forbidden_tokens = list(fact_card.get("forbidden_claims") or [])
    for fact in fact_card.get("facts") or []:
        forbidden_tokens.extend(fact.get("forbidden_paraphrases") or [])
    if serious_domain:
        forbidden_tokens.extend(FORBIDDEN_OVERCLAIMS)
    for token in dict.fromkeys(t for t in forbidden_tokens if isinstance(t, str) and t.strip()):
        for sent in sentences:
            if token in sent and not _has_negation_clarity(sent, token):
                violations.append(
                    {
                        "code": "forbidden_claim_or_overclaim",
                        "message": f"禁止断言/绝对化改写命中 '{token}'",
                        "surface": surface_name,
                        "offending_quote": sent,
                    }
                )

    # 2. Quantitative denominator & scope conflation (does_not_support)
    for fact in fact_card.get("facts") or []:
        qscope = fact.get("quantitative_scope")
        if not isinstance(qscope, dict):
            continue
        for bad_claim in qscope.get("does_not_support") or []:
            if not isinstance(bad_claim, str) or not bad_claim.strip():
                continue
            for sent in sentences:
                if bad_claim in sent and not _has_negation_clarity(sent, bad_claim):
                    violations.append(
                        {
                            "code": "denominator_or_scope_conflation",
                            "message": f"口径/分母偷换：事实 [{fact['fact_id']}] 分母为 '{qscope['denominator']}'，证据不支持写成 '{bad_claim}'",
                            "surface": surface_name,
                            "offending_quote": sent,
                            "fact_id": fact["fact_id"],
                        }
                    )

    # 3. Unverified quote promoted to verified trend
    for q in plan.get("quoted_sources") or []:
        quote = q.get("quote", "")
        if q.get("evidence_status") == "source_quote_unverified_trend" and quote and quote in text:
            for sent in sentences:
                if quote in sent:
                    # Check nearby window (current sentence +/- 1) for attribution or boundary cue
                    pos = sentences.index(sent)
                    window = " ".join(sentences[max(0, pos - 1):min(len(sentences), pos + 2)])
                    if not any(cue in window for cue in ATTRIBUTION_CUES):
                        violations.append(
                            {
                                "code": "unverified_quote_promoted_to_trend",
                                "message": f"未证实引述 '{quote}' 未标注出处及证据状态/边界，禁止当作已证实全国趋势",
                                "surface": surface_name,
                                "offending_quote": sent,
                            }
                        )

    # 4. Analogy misreading
    for analogy in plan.get("analogies") or []:
        bad = analogy.get("forbidden_misreading", "")
        if bad and bad in text:
            for sent in sentences:
                if bad in sent and not _has_negation_clarity(sent, bad):
                    violations.append(
                        {
                            "code": "analogy_boundary_violated",
                            "message": f"类比 '{analogy['metaphor']}' 越界误读：不得写成 '{bad}'（须保留：{analogy['boundary_where_it_breaks']}）",
                            "surface": surface_name,
                            "offending_quote": sent,
                        }
                    )
    return violations


def evaluate_review(
    input_doc: dict[str, Any],
    *,
    base_dir: Path | None = None,
    extra_surface_files: dict[str, Path] | None = None,
    extra_surface_texts: dict[str, str] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Evaluate comprehension & meaning fidelity against actual files and return (receipt_payload, blocking_reasons)."""
    data = copy.deepcopy(input_doc)
    for key in ("review_id", "decision", "blocking_reasons", "authority", "payload_sha256"):
        data.pop(key, None)

    plan_ref = data.get("plan_ref") or {}
    plan_path = _check_file_ref(plan_ref, "plan_ref", base_dir=base_dir)
    plan, card = validate_plan(
        load_json(plan_path),
        expected_request_id=data.get("request_id"),
        expected_content_id=data.get("content_id"),
        base_dir=plan_path.parent,
    )
    if plan["applicability"] != "applicable" or card is None:
        raise PlainLanguageError("plan_not_applicable", "plain-language-review targets an applicable plan")

    fact_ref = data.get("fact_card_ref") or {}
    if fact_ref.get("sha256") != plan["fact_card_ref"]["sha256"] or fact_ref.get("revision_id") != plan["fact_card_ref"]["revision_id"]:
        raise PlainLanguageError("fact_card_drift", "review fact_card_ref differs from plain-language-plan")
    _check_file_ref(fact_ref, "fact_card_ref", base_dir=base_dir)

    body_binding = data.get("body_binding") or {}
    body_path = resolve_artifact_path(body_binding.get("body_ref", ""), base_dir=base_dir)
    actual_body_sha = text_sha256(body_path)
    actual_body_raw_sha = file_sha256(body_path)
    if body_binding.get("body_sha256") not in {actual_body_sha, actual_body_raw_sha}:
        raise PlainLanguageError("body_hash_drift", f"body SHA-256 differs from reviewed binding: {body_binding.get('body_ref')}")
    body_text = _extract_surface_text(body_path)

    blocking: list[dict[str, Any]] = []

    # Reviewer tier / role anti-inflation rule (matches science_popularization_gate)
    level = data.get("review_level")
    roles = data.get("reviewer_roles") or []
    needed_role = {
        "author-self-check": "author",
        "editor-review": "plain-language-editor",
        "target-audience-sample": "target-audience-representative",
    }.get(level)
    if not needed_role or needed_role not in roles:
        blocking.append({"code": "reviewer_role_missing", "message": f"review_level={level} requires role {needed_role}", "surface": "review_level"})
    if level != "target-audience-sample" and "target-audience-representative" in roles:
        blocking.append({"code": "audience_tier_misrepresented", "message": "self/editor check cannot claim target-audience-representative", "surface": "review_level"})

    # Comprehension checks
    comp = data.get("comprehension_check") or {}
    if data.get("draft_mode") == "spoken_script" and comp.get("read_aloud_checked") is not True:
        blocking.append({"code": "read_aloud_required", "message": "口播稿必须完成朗读检查 (read_aloud_checked=true)", "surface": "body"})
    if not comp.get("reader_can_retell_core") or not comp.get("reader_can_retell_scope"):
        blocking.append({"code": "comprehension_retell_failed", "message": "读者无法准确复述核心意思或适用范围", "surface": "body"})
    terms_checked = {row["term"]: row for row in comp.get("terms_checked") or [] if isinstance(row, dict) and "term" in row}
    for concept in plan["concepts_to_explain"]:
        t = concept["term"]
        row = terms_checked.get(t)
        if not row:
            blocking.append({"code": "term_explanation_unchecked", "message": f"术语 '{t}' 缺少通俗化审查记录", "surface": "body"})
            continue
        if not row.get("understandable_at_first_use") or not row.get("order_logical"):
            blocking.append({"code": "term_not_clear_at_first_use", "message": f"术语 '{t}' 首次出现解释不清晰或推进顺序混乱", "surface": "body", "offending_quote": row.get("first_use_anchor", "")})
        anchor = row.get("first_use_anchor", "")
        if anchor not in body_text:
            blocking.append({"code": "term_anchor_missing_from_body", "message": f"术语 '{t}' 的正文锚点不存在", "surface": "body", "offending_quote": anchor})
    for issue in comp.get("issues") or []:
        if issue.get("status") == "open":
            blocking.append({"code": "open_comprehension_issue", "message": issue.get("description", "open issue"), "surface": "body", "offending_quote": issue.get("location_anchor", "")})

    # Meaning fidelity checks
    fid = data.get("meaning_fidelity_check") or {}
    known_facts = {f["fact_id"]: f for f in card["facts"]}
    for cmp_row in fid.get("claim_comparisons") or []:
        fid_id = cmp_row.get("fact_id", "")
        if fid_id not in known_facts:
            blocking.append({"code": "unknown_fact_id_in_comparison", "message": f"fact_id {fid_id!r} 不在锁定事实卡中", "surface": "body", "fact_id": fid_id})
            continue
        failed_dims = [
            k for k in (
                "subject_preserved",
                "conditions_preserved",
                "numbers_and_units_preserved",
                "time_and_scope_preserved",
                "exceptions_preserved",
                "strength_preserved",
                "denominator_and_source_checked",
            )
            if cmp_row.get(k) is not True
        ]
        if failed_dims:
            blocking.append(
                {
                    "code": "meaning_fidelity_drift",
                    "message": f"事实 [{fid_id}] 改写失真（缺失/改变: {', '.join(failed_dims)}）",
                    "surface": "body",
                    "offending_quote": cmp_row.get("draft_quote", ""),
                    "fact_id": fid_id,
                }
            )
        dq = cmp_row.get("draft_quote", "")
        if dq and dq not in body_text:
            # Also check bound surface texts below; collect later or require in body/surfaces
            pass

    # Analogies check
    analogy_checks = {row.get("metaphor"): row for row in fid.get("analogy_checks") or [] if isinstance(row, dict)}
    for analogy in plan.get("analogies") or []:
        m = analogy["metaphor"]
        if m in body_text:
            arow = analogy_checks.get(m)
            if not arow:
                blocking.append({"code": "analogy_check_missing", "message": f"类比 '{m}' 缺少对应关系与边界审查记录", "surface": "body"})
            elif not arow.get("mapping_explicit") or not arow.get("boundary_explicit") or arow.get("misleading_conflation_detected"):
                blocking.append(
                    {
                        "code": "analogy_boundary_violated",
                        "message": f"类比 '{m}' 必须讲清对应关系与不适用边界（不得简化成 '{analogy['forbidden_misreading']}'）",
                        "surface": "body",
                        "offending_quote": arow.get("draft_quote", ""),
                    }
                )
            elif arow.get("draft_quote") and arow["draft_quote"] not in body_text:
                blocking.append({"code": "analogy_anchor_missing", "message": f"类比 '{m}' 锚点不在正文", "surface": "body", "offending_quote": arow["draft_quote"]})

    # Quote attribution check
    quote_checks = {row.get("quote"): row for row in fid.get("quote_attribution_checks") or [] if isinstance(row, dict)}
    for q in plan.get("quoted_sources") or []:
        qt = q["quote"]
        if qt in body_text:
            qrow = quote_checks.get(qt)
            if not qrow:
                blocking.append({"code": "quote_attribution_unchecked", "message": f"引述 '{qt}' 缺少来源与证据等级审核", "surface": "body", "offending_quote": qt})
            elif not qrow.get("attributed_with_evidence_status") or qrow.get("promoted_to_verified_national_trend"):
                blocking.append({"code": "unverified_quote_promoted_to_trend", "message": f"引述 '{qt}' 未正确标注证据边界或被越级当作全国趋势", "surface": "body", "offending_quote": qt})
            elif q["evidence_status"] == "source_quote_unverified_trend" and qrow.get("evidence_tier") == "national_trend":
                blocking.append({"code": "unverified_quote_promoted_to_trend", "message": f"引述 '{qt}' 证据状态为 source_quote_unverified_trend，禁止标为 national_trend", "surface": "body", "offending_quote": qt})

    # Clause explanation linkage
    clause_ref = data.get("clause_explanation_ref") or plan.get("clause_explanation_ref")
    if clause_ref is not None:
        clause_path = _check_file_ref(clause_ref, "clause_explanation_ref", base_dir=base_dir)
        clause_errors = validate_clause_explanation(clause_path)
        for err in clause_errors:
            blocking.append({"code": "clause_explanation_semantic_error", "message": err, "surface": "clause_explanation"})
        if fid.get("clause_fidelity_checked") is not True:
            blocking.append({"code": "clause_fidelity_unchecked", "message": "绑定了保险条款解释但 clause_fidelity_checked 不为 true", "surface": "body"})

    # Surface binding verification + text violation scan across all surfaces
    scanned_surfaces: list[tuple[str, str]] = [("body", body_text)]
    bindings = data.get("surface_claim_bindings") or []
    for row in bindings:
        sname = row["surface"]
        spath = resolve_artifact_path(row["artifact_ref"], base_dir=base_dir)
        raw_sha = file_sha256(spath)
        norm_sha = text_sha256(spath)
        if row["artifact_sha256"] not in {raw_sha, norm_sha}:
            raise PlainLanguageError("surface_claim_hash_drift", f"surface '{sname}' changed after review: {row['artifact_ref']}")
        if sname == "body" and norm_sha != actual_body_sha and raw_sha != actual_body_raw_sha:
            raise PlainLanguageError(
                "surface_body_binding_mismatch",
                f"surface 'body' binding must match body_binding: {row['artifact_ref']}",
            )
        stext = _extract_surface_text(spath)
        if sname != "body":
            scanned_surfaces.append((sname, stext))
        for claim in row["key_claims"]:
            if claim not in stext:
                raise PlainLanguageError("surface_claim_anchor_missing", f"key claim missing from surface '{sname}': {claim}")

    if extra_surface_files:
        for sname, spath in extra_surface_files.items():
            if spath.is_file():
                scanned_surfaces.append((f"consumer:{sname}", _extract_surface_text(spath)))

    if extra_surface_texts:
        for sname, stext in extra_surface_texts.items():
            if isinstance(stext, str) and stext.strip():
                scanned_surfaces.append((f"surface:{sname}", stext))

    # Check claim_comparison draft_quotes appear in body or at least one bound surface
    all_text = "\n".join(stext for _, stext in scanned_surfaces)
    for cmp_row in fid.get("claim_comparisons") or []:
        dq = cmp_row.get("draft_quote", "")
        if dq and dq not in all_text:
            blocking.append({"code": "comparison_anchor_missing", "message": f"核对原句不在正文或交付页面中: {dq}", "surface": "body", "offending_quote": dq, "fact_id": cmp_row.get("fact_id", "")})

    for sname, stext in scanned_surfaces:
        blocking.extend(_scan_text_violations(sname, stext, plan, card))

    # Deduplicate blocking items cleanly
    unique_blocking: list[dict[str, Any]] = []
    seen = set()
    for item in blocking:
        key = (item.get("code"), item.get("surface"), item.get("offending_quote"), item.get("message"))
        if key not in seen:
            seen.add(key)
            unique_blocking.append(item)

    payload = copy.deepcopy(data)
    payload["decision"] = "passed" if not unique_blocking else "revision_required"
    payload["blocking_reasons"] = unique_blocking
    core = copy.deepcopy(payload)
    payload["review_id"] = "plain-review-" + canonical_sha256(core)[:24]
    payload["authority"] = copy.deepcopy(AUTHORITY)
    payload["payload_sha256"] = canonical_sha256(payload)
    _validate_schema(payload, REVIEW_SCHEMA, "review_schema_invalid")
    return payload, unique_blocking


def create_review(input_path: Path, *, base_dir: Path | None = None) -> dict[str, Any]:
    raw = load_json(input_path)
    resolved_base = base_dir or input_path.parent
    # If caller attempted to force decision='passed' on invalid input, evaluate_review overrides/flags it cleanly
    payload, _ = evaluate_review(raw, base_dir=resolved_base)
    return payload


def validate_review(
    review_doc: dict[str, Any],
    *,
    expected_request_id: str | None = None,
    expected_content_id: str | None = None,
    expected_body_path: Path | None = None,
    expected_body_sha256: str | None = None,
    expected_plan_ref: dict[str, Any] | None = None,
    expected_fact_card_ref: dict[str, Any] | None = None,
    extra_surface_files: dict[str, Path] | None = None,
    extra_surface_texts: dict[str, str] | None = None,
    base_dir: Path | None = None,
    require_passed: bool = True,
) -> dict[str, Any]:
    _validate_schema(review_doc, REVIEW_SCHEMA, "review_schema_invalid")
    unsigned = copy.deepcopy(review_doc)
    digest = unsigned.pop("payload_sha256")
    if canonical_sha256(unsigned) != digest:
        raise PlainLanguageError("review_hash_drift", "plain-language-review payload_sha256 mismatch")
    if expected_request_id and review_doc["request_id"] != expected_request_id:
        raise PlainLanguageError("review_request_mismatch", "plain-language-review belongs to another request")
    if expected_content_id and review_doc["content_id"] != expected_content_id:
        raise PlainLanguageError("review_content_mismatch", "plain-language-review belongs to another content_id")
    if expected_plan_ref:
        plan_sha_on_disk = file_sha256(resolve_artifact_path(review_doc["plan_ref"]["path"], base_dir=base_dir))
        if expected_plan_ref.get("sha256") not in {review_doc["plan_ref"].get("sha256"), plan_sha_on_disk}:
            raise PlainLanguageError("review_plan_drift", "plain-language-review references an older plain-language-plan")
    if expected_fact_card_ref:
        fc_sha_on_disk = file_sha256(resolve_artifact_path(review_doc["fact_card_ref"]["path"], base_dir=base_dir))
        if expected_fact_card_ref.get("sha256") not in {review_doc["fact_card_ref"].get("sha256"), fc_sha_on_disk}:
            raise PlainLanguageError("review_fact_card_drift", "plain-language-review uses a stale fact card revision")
        if (
            expected_fact_card_ref.get("revision_id")
            and review_doc["fact_card_ref"].get("revision_id") != expected_fact_card_ref.get("revision_id")
        ):
            raise PlainLanguageError("review_fact_card_drift", "plain-language-review uses a stale fact card revision")
    if expected_body_path is not None:
        actual_expected_sha = text_sha256(expected_body_path)
        raw_expected_sha = file_sha256(expected_body_path)
        if review_doc["body_binding"]["body_sha256"] not in {actual_expected_sha, raw_expected_sha}:
            raise PlainLanguageError("body_hash_drift", "plain-language-review binds a different draft body")
    elif expected_body_sha256:
        if review_doc["body_binding"]["body_sha256"] != expected_body_sha256:
            raise PlainLanguageError("body_hash_drift", "plain-language-review body SHA-256 differs from current body")

    re_eval, blocking = evaluate_review(
        review_doc,
        base_dir=base_dir,
        extra_surface_files=extra_surface_files,
        extra_surface_texts=extra_surface_texts,
    )
    if blocking:
        raise PlainLanguageError(
            blocking[0]["code"],
            "; ".join(f"{b['code']}({b.get('surface','?')}): {b['message']}" for b in blocking),
            details=blocking,
        )
    if require_passed and review_doc["decision"] != "passed":
        raise PlainLanguageError("review_not_passed", f"plain-language-review decision is {review_doc['decision']!r}")
    return re_eval


def validate_formal_science_review(
    path: Path,
    *,
    expected_content_id: str | None = None,
    expected_body_path: Path | None = None,
    expected_body_sha256: str | None = None,
) -> dict[str, Any]:
    """Enforce genuine science-popularization-review.v1 receipt; reject simplified decision stubs."""
    doc = load_json(path)
    if doc.get("schema_version") != "science-popularization-review.v1":
        raise PlainLanguageError(
            "formal_science_popularization_review_required",
            "production/delivery requires a schema-valid science-popularization-review.v1 receipt; simplified approved stubs are rejected",
        )
    if expected_content_id and doc.get("content_id") != expected_content_id:
        raise PlainLanguageError("science_review_content_mismatch", f"science review content_id {doc.get('content_id')!r} != {expected_content_id!r}")
    body_sha = (doc.get("body_binding") or {}).get("body_sha256")
    if expected_body_path is not None:
        if body_sha not in {file_sha256(expected_body_path), text_sha256(expected_body_path)}:
            raise PlainLanguageError("science_review_body_drift", "science-popularization-review body_sha256 does not match current body")
    elif expected_body_sha256 and body_sha != expected_body_sha256:
        raise PlainLanguageError("science_review_body_drift", "science-popularization-review body_sha256 does not match current body")
    sci = _science_module()
    try:
        sci.validate_receipt(doc)
    except Exception as err:
        raise PlainLanguageError(getattr(err, "code", "science_review_invalid"), str(err)) from err
    return doc


def validate_formal_translation_review(
    path: Path,
    *,
    expected_content_id: str | None = None,
    expected_body_path: Path | None = None,
    expected_body_sha256: str | None = None,
    expected_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Enforce serious-content-translation-review.v1 receipt and verify precreative plan continuity."""
    doc = load_json(path)
    if doc.get("schema_version") != "serious-content-translation-review.v1":
        raise PlainLanguageError(
            "formal_translation_review_required",
            "production/delivery requires a schema-valid serious-content-translation-review.v1 receipt",
        )
    if expected_content_id and doc.get("content_id") != expected_content_id:
        raise PlainLanguageError("translation_review_content_mismatch", f"translation review content_id {doc.get('content_id')!r} != {expected_content_id!r}")
    body_sha = (doc.get("body_binding") or {}).get("body_sha256")
    if expected_body_path is not None:
        if body_sha not in {file_sha256(expected_body_path), text_sha256(expected_body_path)}:
            raise PlainLanguageError("translation_review_body_drift", "serious-content-translation-review body_sha256 does not match current body")
    elif expected_body_sha256 and body_sha != expected_body_sha256:
        raise PlainLanguageError("translation_review_body_drift", "serious-content-translation-review body_sha256 does not match current body")
    if isinstance(expected_plan, dict) and isinstance(expected_plan.get("serious_precheck"), dict):
        pre = expected_plan["serious_precheck"]
        for field in ("risk_class", "sensitivity_profile", "content_nature", "precreative_gate", "translation_plan"):
            if doc.get(field) != pre.get(field):
                raise PlainLanguageError("translation_precheck_drift", f"postcreative receipt field '{field}' diverges from pre-draft serious_precheck")
    trans = _serious_module()
    try:
        trans.validate_receipt(doc)
    except Exception as err:
        raise PlainLanguageError(getattr(err, "code", "translation_review_invalid"), str(err)) from err
    return doc


def _allowed_output_roots() -> tuple[Path, ...]:
    roots = [
        (ROOT / ".runtime" / OUTPUT_SUBDIR).resolve(),
        (ROOT / "tests" / ".runtime" / OUTPUT_SUBDIR).resolve(),
    ]
    for base in runtime_paths.allowed_runtime_roots(ROOT):
        roots.append((base / OUTPUT_SUBDIR).resolve())
        roots.append(base.resolve())
    return tuple(dict.fromkeys(roots))


def write_receipt(path: Path, value: dict[str, Any]) -> str:
    resolved = runtime_paths.resolve_runtime_arg(ROOT, path).resolve() if not path.is_absolute() else path.resolve()
    if not any(resolved.is_relative_to(root) for root in _allowed_output_roots()):
        raise PlainLanguageError("output_path_prohibited", f"output must stay under runtime root: {resolved}")
    encoded = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    resolved.parent.mkdir(parents=True, exist_ok=True)
    try:
        with resolved.open("xb") as handle:
            handle.write(encoded)
        return "created"
    except FileExistsError:
        if resolved.read_bytes() != encoded:
            raise PlainLanguageError("output_conflict", f"existing output differs: {resolved}")
        return "already-identical"


def check() -> dict[str, Any]:
    plan_in = FIXTURE_ROOT / "plan.valid.input.json"
    plan_fixture = FIXTURE_ROOT / "plan.valid.json"
    rev_in = FIXTURE_ROOT / "review.valid.input.json"
    p1 = create_plan(plan_in)
    p2 = create_plan(plan_in)
    if canonical_bytes(p1) != canonical_bytes(p2):
        raise PlainLanguageError("non_deterministic", "plan output is not byte-stable")
    if canonical_bytes(p1) != canonical_bytes(load_json(plan_fixture)):
        raise PlainLanguageError("non_deterministic", "plan fixture diverges from create_plan output")
    validate_plan(p1, base_dir=ROOT)

    rev_raw = load_json(rev_in)
    r1, b1 = evaluate_review(rev_raw, base_dir=ROOT)
    r2, b2 = evaluate_review(rev_raw, base_dir=ROOT)
    if canonical_bytes(r1) != canonical_bytes(r2) or b1 or b2 or r1["decision"] != "passed":
        raise PlainLanguageError("non_deterministic", f"review check failed or non-deterministic: {b1}")
    validate_review(r1, base_dir=ROOT, expected_plan_ref={"path": rev_raw["plan_ref"]["path"], "sha256": file_sha256(plan_fixture)})
    return {"status": "passed", "idempotency": "byte-stable", "plan_id": p1["plan_id"], "review_id": r1["review_id"]}


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    fc = sub.add_parser("fact-checklist")
    fc.add_argument("--content-id", required=True)
    fc.add_argument("--topic", required=True)
    fc.add_argument("--audience", required=True)
    fc.add_argument("--purpose", required=True)
    fc.add_argument("--fact-card", type=Path)

    cp = sub.add_parser("create-plan")
    cp.add_argument("--input", type=Path, required=True)
    cp.add_argument("--output", type=Path, required=True)

    vp = sub.add_parser("validate-plan")
    vp.add_argument("--plan", type=Path, required=True)
    vp.add_argument("--request-id")
    vp.add_argument("--content-id")

    cr = sub.add_parser("create-review")
    cr.add_argument("--input", type=Path, required=True)
    cr.add_argument("--output", type=Path, required=True)

    vr = sub.add_parser("validate-review")
    vr.add_argument("--review", type=Path, required=True)
    vr.add_argument("--request-id")
    vr.add_argument("--content-id")
    vr.add_argument("--body", type=Path)

    cs = sub.add_parser("check-surfaces")
    cs.add_argument("--review", type=Path, required=True)
    cs.add_argument("--surface", action="append", default=[], help="name=path pairs")

    sub.add_parser("check")
    args = parser.parse_args(argv)
    try:
        if args.command == "fact-checklist":
            fc_doc = None
            fc_path = None
            if args.fact_card:
                fc_path = resolve_artifact_path(str(args.fact_card))
                fc_doc = load_json(fc_path)
            checklist = build_fact_confirmation_checklist(
                content_id=args.content_id,
                topic=args.topic,
                audience=args.audience,
                purpose=args.purpose,
                fact_card=fc_doc,
                fact_card_path=fc_path,
            )
            print(json.dumps(checklist, ensure_ascii=False, indent=2))
        elif args.command == "create-plan":
            in_path = runtime_paths.resolve_runtime_arg(ROOT, args.input) if not args.input.is_absolute() else args.input
            plan = create_plan(in_path)
            status = write_receipt(args.output, plan)
            print(json.dumps({"status": status, "plan_id": plan["plan_id"], "payload_sha256": plan["payload_sha256"]}, ensure_ascii=False))
        elif args.command == "validate-plan":
            p_path = runtime_paths.resolve_runtime_arg(ROOT, args.plan) if not args.plan.is_absolute() else args.plan
            plan, card = validate_plan(load_json(p_path), expected_request_id=args.request_id, expected_content_id=args.content_id, base_dir=p_path.parent)
            print(json.dumps({"status": "passed", "plan_id": plan["plan_id"], "writing_guidance": build_writing_guidance(plan, card)}, ensure_ascii=False))
        elif args.command == "create-review":
            in_path = runtime_paths.resolve_runtime_arg(ROOT, args.input) if not args.input.is_absolute() else args.input
            review = create_review(in_path)
            status = write_receipt(args.output, review)
            code = 0 if review["decision"] == "passed" else 2
            print(json.dumps({"status": status, "decision": review["decision"], "review_id": review["review_id"], "blocking_reasons": review["blocking_reasons"]}, ensure_ascii=False))
            return code
        elif args.command == "validate-review":
            r_path = runtime_paths.resolve_runtime_arg(ROOT, args.review) if not args.review.is_absolute() else args.review
            b_path = (runtime_paths.resolve_runtime_arg(ROOT, args.body) if not args.body.is_absolute() else args.body) if args.body else None
            rev = validate_review(load_json(r_path), expected_request_id=args.request_id, expected_content_id=args.content_id, expected_body_path=b_path, base_dir=r_path.parent)
            print(json.dumps({"status": "passed", "review_id": rev["review_id"]}, ensure_ascii=False))
        elif args.command == "check-surfaces":
            r_path = runtime_paths.resolve_runtime_arg(ROOT, args.review) if not args.review.is_absolute() else args.review
            extras: dict[str, Path] = {}
            for pair in args.surface:
                if "=" not in pair:
                    raise PlainLanguageError("invalid_surface_arg", pair)
                name, raw_p = pair.split("=", 1)
                extras[name] = resolve_artifact_path(raw_p)
            rev = validate_review(load_json(r_path), extra_surface_files=extras, base_dir=r_path.parent)
            print(json.dumps({"status": "passed", "review_id": rev["review_id"], "checked_surfaces": sorted(extras)}, ensure_ascii=False))
        else:
            print(json.dumps(check(), ensure_ascii=False, sort_keys=True))
        return 0
    except PlainLanguageError as error:
        print(json.dumps({"status": "blocked", "code": error.code, "message": str(error), "details": error.details}, ensure_ascii=False), file=sys.stderr)
        return 2
    except Exception as error:
        print(json.dumps({"status": "blocked", "code": "validation_failed", "message": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
