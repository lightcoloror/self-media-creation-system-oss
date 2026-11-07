#!/usr/bin/env python3
"""Append de-identified topic signals and build an explainable weekly candidate snapshot.

This is a thin ingress layer for the existing high-frequency topic ranker.  It
does not create another topic lifecycle, scan private knowledge bases, call a
provider, open a platform, write content, contact customers, or publish.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import sys
import unicodedata
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas" / "topic-observation.v1.schema.json"
DEFAULT_LEDGER = ROOT / "research-ledgers" / "topic-observations.v1.jsonl"
DEFAULT_OUTPUT = ROOT / "outputs" / "draft-only" / "continuous-topic-discovery"
ALLOWED_WRITE_ROOTS = (
    (ROOT / "research-ledgers").resolve(),
    (ROOT / ".runtime").resolve(),
    (ROOT / "outputs" / "draft-only").resolve(),
    (ROOT / "tests" / ".runtime").resolve(),
)
DIRECT_IDENTIFIER_PATTERNS = {
    "phone": re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"),
    "national_id": re.compile(r"(?<!\d)\d{17}[0-9Xx](?!\d)"),
    "email": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    "wechat_id": re.compile(r"微信号\s*[:：]\s*[A-Za-z][A-Za-z0-9_-]{5,}"),
}
RISK_ORDER = {"low": 0, "medium": 1, "high": 2}
FACT_ORDER = {"low": 0, "medium": 1, "high": 2}
LANE_RELATIONSHIP = {
    "customer-question": "observed-customer-question",
    "service-event": "observed-service-event",
    "publication-feedback": "deidentified-publication-feedback",
    "public-discovery": "public-discovery-only",
    "knowledge-allowlist": "allowlisted-knowledge-signal",
    "strategy-gap": "strategy-gap-not-frequency-evidence",
}


class DiscoveryError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def load_ranker() -> Any:
    path = ROOT / "scripts" / "high_frequency_topic_loop.py"
    spec = importlib.util.spec_from_file_location("high_frequency_topic_loop_for_discovery", path)
    if not spec or not spec.loader:
        raise DiscoveryError("ranker_unavailable", str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def safe_write_path(path: Path) -> Path:
    resolved = path.resolve()
    if not any(resolved == root or root in resolved.parents for root in ALLOWED_WRITE_ROOTS):
        raise DiscoveryError("write_path_outside_allowed_roots", str(path))
    if resolved.exists() and resolved.is_symlink():
        raise DiscoveryError("write_path_symlink_prohibited", str(path))
    return resolved


def safe_input_path(path: Path) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(ROOT.resolve())
    except ValueError as error:
        raise DiscoveryError("input_path_outside_repository", str(path)) from error
    if not resolved.is_file():
        raise DiscoveryError("input_missing", str(path))
    if resolved.is_symlink():
        raise DiscoveryError("input_symlink_prohibited", str(path))
    return resolved


def load_schema() -> dict[str, Any]:
    value = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise DiscoveryError("schema_invalid", str(SCHEMA_PATH))
    return value


def normalize_question(question: str) -> str:
    normalized = unicodedata.normalize("NFKC", question).strip().lower()
    normalized = re.sub(r"\s+", "", normalized)
    normalized = re.sub(r"[，。！？；：、,.!?;:'\"“”‘’（）()\[\]{}<>《》]", "", normalized)
    return normalized


def derived_topic_key(normalized_question: str) -> str:
    return f"topic-{hashlib.sha256(normalized_question.encode('utf-8')).hexdigest()[:16]}"


def derived_signal_id(identity: dict[str, Any]) -> str:
    return f"sig_{canonical_sha256(identity)[:24]}"


def direct_identifier_errors(value: Any, path: str = "$") -> list[str]:
    errors: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            errors.extend(direct_identifier_errors(item, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            errors.extend(direct_identifier_errors(item, f"{path}[{index}]"))
    elif isinstance(value, str):
        for name, pattern in DIRECT_IDENTIFIER_PATTERNS.items():
            if pattern.search(value):
                errors.append(f"{path}: possible {name}")
    return errors


def observation_errors(value: dict[str, Any]) -> list[str]:
    validator = Draft202012Validator(load_schema(), format_checker=FormatChecker())
    errors = [
        f"{'.'.join(str(part) for part in error.path) or '$'}: {error.message}"
        for error in sorted(validator.iter_errors(value), key=lambda error: list(error.path))
    ]
    errors.extend(direct_identifier_errors(value))
    if value.get("normalized_question") != normalize_question(value.get("deidentified_question", "")):
        errors.append("normalized_question does not match deterministic normalization")
    if value.get("privacy_status") != "passed" and value.get("frequency_eligible"):
        errors.append("privacy-blocked observation cannot count toward frequency")
    if value.get("created_by") == "agent_candidate" and value.get("frequency_eligible"):
        errors.append("agent candidate cannot count toward frequency")
    if value.get("evidence_status") in {"candidate", "unverified"} and value.get("frequency_eligible"):
        errors.append("candidate or unverified evidence cannot count toward frequency")
    if value.get("source_lane") == "strategy-gap" and value.get("frequency_eligible"):
        errors.append("strategy gap cannot count as observed audience frequency")
    if value.get("repeat_confirmation") == "human_confirmed":
        if value.get("created_by") != "human" or value.get("cluster_review_status") != "human_confirmed":
            errors.append("repeat confirmation requires a human-created, human-confirmed cluster")
    if value.get("fact_support_eligible"):
        if value.get("evidence_status") not in {"verified_source", "verified_position"}:
            errors.append("fact support requires verified source or verified position")
        if value.get("source_lane") in {"customer-question", "service-event", "publication-feedback", "strategy-gap"}:
            errors.append("demand or strategy signal cannot become factual support")
    return errors


def load_ledger(path: Path, *, allow_missing: bool = False) -> list[dict[str, Any]]:
    if not path.exists():
        if allow_missing:
            return []
        raise DiscoveryError("ledger_missing", str(path))
    if not path.is_file():
        raise DiscoveryError("ledger_not_file", str(path))
    events: list[dict[str, Any]] = []
    by_id: dict[str, str] = {}
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as error:
            raise DiscoveryError("ledger_json_invalid", f"line {line_number}: {error}") from error
        if not isinstance(value, dict):
            raise DiscoveryError("ledger_event_not_object", f"line {line_number}")
        errors = observation_errors(value)
        if errors:
            raise DiscoveryError("observation_invalid", f"line {line_number}: {'; '.join(errors)}")
        digest = canonical_sha256(value)
        signal_id = value["signal_id"]
        if signal_id in by_id:
            if by_id[signal_id] != digest:
                raise DiscoveryError("signal_id_drift", signal_id)
            continue
        by_id[signal_id] = digest
        events.append(value)
    if not events and allow_missing:
        return []
    if not events:
        raise DiscoveryError("ledger_empty", str(path))
    return sorted(events, key=lambda item: (item["observed_at"], item["signal_id"]))


def build_observation(args: argparse.Namespace) -> dict[str, Any]:
    question = args.question.strip()
    normalized = normalize_question(question)
    if not normalized:
        raise DiscoveryError("question_empty_after_normalization", question)
    topic_key = args.topic_key or derived_topic_key(normalized)
    source_hash = args.source_hash or hashlib.sha256(
        f"{args.source_ref}\n{normalized}".encode("utf-8")
    ).hexdigest()
    identity = {
        "source_lane": args.source_lane,
        "source_ref": args.source_ref,
        "source_hash": source_hash,
        "independence_group": args.independence_group,
        "normalized_question": normalized,
    }
    value = {
        "schema_version": "topic-observation.v1",
        "signal_id": args.signal_id or derived_signal_id(identity),
        "observed_at": args.observed_at or datetime.now().astimezone().isoformat(timespec="seconds"),
        "source_lane": args.source_lane,
        "source_ref": args.source_ref,
        "source_hash": source_hash,
        "independence_group": args.independence_group,
        "topic_key": topic_key,
        "deidentified_question": question,
        "normalized_question": normalized,
        "audience_hint": args.audience_hint,
        "account_ip_hint": args.account_ip,
        "historical_priority": args.priority,
        "risk_level": args.risk,
        "fact_dependency": args.fact_dependency,
        "personal_experience_status": args.personal_experience_status,
        "current_product_status": args.current_product_status,
        "evidence_status": args.evidence_status,
        "frequency_eligible": args.counts_toward_frequency,
        "fact_support_eligible": False,
        "privacy_status": "passed" if args.privacy_passed else "blocked",
        "content_signal_only": args.content_signal_only,
        "cluster_review_status": "human_confirmed" if args.cluster_reviewed else "deterministic_exact",
        "repeat_confirmation": "human_confirmed" if args.repeat_confirmed else "not_confirmed",
        "created_by": "human",
        "synthetic_only": args.synthetic_only,
    }
    errors = observation_errors(value)
    if errors:
        raise DiscoveryError("observation_invalid", "; ".join(errors))
    return value


def append_observation(path: Path, value: dict[str, Any]) -> dict[str, Any]:
    path = safe_write_path(path)
    existing = load_ledger(path, allow_missing=True) if path.exists() else []
    for event in existing:
        if event["signal_id"] == value["signal_id"]:
            if canonical_sha256(event) != canonical_sha256(value):
                raise DiscoveryError("signal_id_drift", value["signal_id"])
            return {"status": "already_exists", "signal_id": value["signal_id"], "ledger": str(path)}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(canonical_json(value) + "\n")
    loaded = load_ledger(path)
    if not any(event["signal_id"] == value["signal_id"] for event in loaded):
        raise DiscoveryError("append_verification_failed", value["signal_id"])
    return {"status": "appended", "signal_id": value["signal_id"], "ledger": str(path)}


def eligible_for_frequency(event: dict[str, Any]) -> bool:
    return (
        event["frequency_eligible"]
        and event["privacy_status"] == "passed"
        and event["created_by"] != "agent_candidate"
        and event["evidence_status"] in {"user_confirmed", "verified_source", "verified_position"}
        and event["source_lane"] != "strategy-gap"
    )


def conservative_value(events: list[dict[str, Any]], key: str, order: dict[str, int]) -> str:
    return max((event[key] for event in events), key=lambda value: order[value])


def stable_status(events: list[dict[str, Any]], key: str) -> str:
    values = sorted({event[key] for event in events})
    return values[0] if len(values) == 1 else "mixed_requires_human_review"


def observations_to_candidate_source(events: list[dict[str, Any]], ledger_path: Path) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        groups[event["topic_key"]].append(event)
    candidates: list[dict[str, Any]] = []
    ledger_ref = str(ledger_path.resolve())
    for topic_key in sorted(groups):
        cluster = sorted(groups[topic_key], key=lambda item: (item["signal_id"], item["observed_at"]))
        human_questions = [event for event in cluster if event["cluster_review_status"] == "human_confirmed"]
        representative = (human_questions or cluster)[0]
        repeated = any(event["repeat_confirmation"] == "human_confirmed" for event in cluster)
        refs: list[dict[str, Any]] = []
        for event in cluster:
            relation = (
                "human-reviewed-repeat-confirmation"
                if event["repeat_confirmation"] == "human_confirmed"
                else LANE_RELATIONSHIP[event["source_lane"]]
            )
            refs.append(
                {
                    "evidence_id": event["signal_id"],
                    "source_type": "ai-draft" if event["created_by"] == "agent_candidate" else "workspace-file",
                    "ref": ledger_ref,
                    "evidence_status": event["evidence_status"],
                    "relationship": relation,
                    "independence_group": event["independence_group"],
                    "counts_toward_frequency": eligible_for_frequency(event),
                }
            )
        candidates.append(
            {
                "topic_key": topic_key,
                "question": representative["deidentified_question"],
                "historical_priority": "P0" if any(event["historical_priority"] == "P0" for event in cluster) else "P1",
                "human_reviewed_repeat_confirmed": repeated,
                "raw_occurrence_count": None,
                "risk_level": conservative_value(cluster, "risk_level", RISK_ORDER),
                "fact_dependency": conservative_value(cluster, "fact_dependency", FACT_ORDER),
                "personal_experience_status": stable_status(cluster, "personal_experience_status"),
                "current_product_status": stable_status(cluster, "current_product_status"),
                "evidence_refs": refs,
            }
        )
    return {
        "schema_version": "1",
        "source_scope": "read_only_deidentified",
        "frequency_unit": "unique_qualified_evidence_group_not_people_or_messages",
        "raw_occurrence_count_policy": "unknown_unless_explicitly_preserved_by_source",
        "candidates": candidates,
    }


def qualification_payload(ranking: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any]:
    by_topic: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        by_topic[event["topic_key"]].append(event)
    items: list[dict[str, Any]] = []
    for ranked in ranking["ranking"]:
        cluster = by_topic[ranked["topic_key"]]
        service_event_ready = any(
            event["source_lane"] == "service-event"
            and eligible_for_frequency(event)
            and event["cluster_review_status"] == "human_confirmed"
            for event in cluster
        )
        repeated_ready = (
            ranked["repeat_status"] == "confirmed_repeated"
            and ranked["qualified_evidence_group_count"] >= 1
        )
        multi_source_ready = ranked["qualified_evidence_group_count"] >= 2
        qualified = repeated_ready or multi_source_ready or service_event_ready
        reasons: list[str] = []
        if repeated_ready:
            reasons.append("human_confirmed_repeat")
        if multi_source_ready:
            reasons.append("two_or_more_independent_qualified_groups")
        if service_event_ready:
            reasons.append("human_confirmed_high_value_service_event")
        if not qualified:
            reasons.append("needs_more_independent_demand_evidence_or_human_service_event_confirmation")
        items.append(
            {
                "rank": ranked["rank"],
                "topic_key": ranked["topic_key"],
                "question": ranked["question"],
                "qualification_status": "qualified_for_human_review" if qualified else "candidate_only",
                "qualification_reasons": reasons,
                "qualified_evidence_group_count": ranked["qualified_evidence_group_count"],
                "score": ranked["score"],
            }
        )
    qualified_items = [item for item in items if item["qualification_status"] == "qualified_for_human_review"]
    return {
        "schema_version": "topic-qualification.v1",
        "status": "draft_only",
        "qualified_count": len(qualified_items),
        "candidate_only_count": len(items) - len(qualified_items),
        "recommended_topic_key": qualified_items[0]["topic_key"] if qualified_items else None,
        "items": items,
    }


def weekly_markdown(
    ranking: dict[str, Any], qualification: dict[str, Any], events: list[dict[str, Any]]
) -> str:
    as_of = max(event["observed_at"] for event in events)
    qualified = [
        item for item in qualification["items"]
        if item["qualification_status"] == "qualified_for_human_review"
    ]
    candidate_only = [
        item for item in qualification["items"]
        if item["qualification_status"] == "candidate_only"
    ]
    lines = [
        "# 持续选题发现周报（draft_only）",
        "",
        f"- 截止：{as_of}",
        f"- 可排序观察主题：{len(ranking['ranking'])}",
        f"- 已通过资格门：{len(qualified)}",
        "- 频次单位：相互独立的合格证据组，不是客户人数或消息条数",
        "- 边界：仅供人工选题；不自动写稿或发布",
        "",
        "## 建议人工晋级的 Top 5",
        "",
    ]
    for item in qualified[:5]:
        lines.extend(
            [
                f"### {item['rank']}. {item['question']}",
                "",
                f"- topic_key：`{item['topic_key']}`",
                f"- 排序分：{item['score']}",
                f"- 独立合格来源组：{item['qualified_evidence_group_count']}",
                f"- 资格理由：{', '.join(item['qualification_reasons'])}",
                "",
            ]
        )
    if not qualified:
        lines.extend(["当前没有题目通过资格门；不要为了填满周报自动降级门槛。", ""])
    lines.extend(["## 仍需补证据的观察候选", ""])
    for item in candidate_only[:5]:
        lines.extend(
            [
                f"- {item['question']}（独立合格来源组：{item['qualified_evidence_group_count']}）",
            ]
        )
    lines.append("")
    lines.extend(
        [
            "## 人工晋级前检查",
            "",
            "- 是否与当前账号、受众和唯一首要目标匹配？",
            "- 是否需要补官方事实或合同证据？",
            "- 是否与最近发布内容重复，或确有新角度？",
            "- 是否仍然彻底脱敏？",
            "",
        ]
    )
    return "\n".join(lines)


def build_bundle(ledger: Path, output: Path) -> dict[str, Any]:
    ledger = safe_input_path(ledger)
    output = safe_write_path(output)
    events = load_ledger(ledger)
    source = observations_to_candidate_source(events, ledger)
    ranker = load_ranker()
    errors = ranker.candidate_errors(source, check_paths=True)
    if errors:
        raise DiscoveryError("candidate_snapshot_invalid", "; ".join(errors))
    ranking = ranker.ranked_payload(source)
    qualification = qualification_payload(ranking, events)
    files = {
        "candidate-source.json": json.dumps(source, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        "ranked-topics.json": json.dumps(ranking, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        "qualified-topics.json": json.dumps(qualification, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        "weekly-topics.md": weekly_markdown(ranking, qualification, events),
    }
    manifest = {
        "schema_version": "topic-discovery-bundle.v1",
        "status": "draft_only",
        "as_of": max(event["observed_at"] for event in events),
        "input_ledger_ref": ledger.relative_to(ROOT.resolve()).as_posix(),
        "input_ledger_sha256": sha256_file(ledger),
        "observation_count": len(events),
        "candidate_count": len(source["candidates"]),
        "candidate_source_sha256": canonical_sha256(source),
        "ranking_sha256": canonical_sha256(ranking),
        "qualification_sha256": canonical_sha256(qualification),
        "selected_topic_key": qualification["recommended_topic_key"],
        "boundaries": {
            "knowledge_base_scanned": False,
            "platform_accessed": False,
            "provider_called": False,
            "content_generated": False,
            "publication": "manual-only",
        },
        "files": sorted([*files, "manifest.json"]),
    }
    files["manifest.json"] = json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    output.mkdir(parents=True, exist_ok=True)
    wrote_any = False
    for name, content in files.items():
        path = output / name
        if path.exists():
            if path.read_text(encoding="utf-8") != content:
                raise DiscoveryError("output_drift", str(path))
            continue
        path.write_text(content, encoding="utf-8", newline="\n")
        wrote_any = True
    validate_bundle(output)
    return {
        "status": "completed" if wrote_any else "already_completed",
        "selected_topic_key": manifest["selected_topic_key"],
        "observation_count": len(events),
        "candidate_count": len(source["candidates"]),
        "manifest": str(output / "manifest.json"),
        "manifest_sha256": sha256_file(output / "manifest.json"),
    }


def validate_bundle(output: Path) -> None:
    output = safe_write_path(output)
    manifest_path = output / "manifest.json"
    if not manifest_path.is_file():
        raise DiscoveryError("manifest_missing", str(manifest_path))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("status") != "draft_only" or manifest.get("boundaries", {}).get("publication") != "manual-only":
        raise DiscoveryError("boundary_drift", str(manifest_path))
    ledger = safe_input_path(ROOT / manifest["input_ledger_ref"])
    if sha256_file(ledger) != manifest["input_ledger_sha256"]:
        raise DiscoveryError("input_ledger_drift", str(ledger))
    source = json.loads((output / "candidate-source.json").read_text(encoding="utf-8"))
    ranking = json.loads((output / "ranked-topics.json").read_text(encoding="utf-8"))
    qualification = json.loads((output / "qualified-topics.json").read_text(encoding="utf-8"))
    if canonical_sha256(source) != manifest["candidate_source_sha256"]:
        raise DiscoveryError("candidate_source_drift", str(output))
    if canonical_sha256(ranking) != manifest["ranking_sha256"]:
        raise DiscoveryError("ranking_drift", str(output))
    if canonical_sha256(qualification) != manifest["qualification_sha256"]:
        raise DiscoveryError("qualification_drift", str(output))
    ranker = load_ranker()
    errors = ranker.candidate_errors(source, check_paths=True)
    if errors:
        raise DiscoveryError("candidate_snapshot_invalid", "; ".join(errors))


def doctor() -> dict[str, Any]:
    schema = load_schema()
    ranker = load_ranker()
    return {
        "schema_version": "topic-discovery-doctor.v1",
        "status": "pass",
        "schema_id": schema["$id"],
        "ranker_reused": str(Path(ranker.__file__).resolve()),
        "default_ledger": str(DEFAULT_LEDGER),
        "default_output": str(DEFAULT_OUTPUT),
        "boundaries": {
            "knowledge_base_scan": "not-authorized-by-this-cli",
            "platform_access": False,
            "provider_calls": False,
            "content_generation": False,
            "publication": "manual-only",
        },
    }


def add_capture_arguments(command: argparse.ArgumentParser) -> None:
    command.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    command.add_argument("--question", required=True)
    command.add_argument("--source-lane", required=True, choices=[
        "customer-question", "service-event", "publication-feedback", "public-discovery",
        "knowledge-allowlist", "strategy-gap",
    ])
    command.add_argument("--source-ref", required=True)
    command.add_argument("--source-hash")
    command.add_argument("--independence-group", required=True)
    command.add_argument("--topic-key")
    command.add_argument("--signal-id")
    command.add_argument("--observed-at")
    command.add_argument("--audience-hint", default="需要理解相关保险决策的普通家庭")
    command.add_argument("--account-ip", default="cange-risk-diagnosis", choices=[
        "cange-risk-diagnosis", "cange-growth", "dual-account-shared", "personal-wechat-moments",
    ])
    command.add_argument("--priority", default="P1", choices=["P0", "P1"])
    command.add_argument("--risk", default="medium", choices=["low", "medium", "high"])
    command.add_argument("--fact-dependency", default="medium", choices=["low", "medium", "high"])
    command.add_argument("--personal-experience-status", default="unknown_not_required")
    command.add_argument("--current-product-status", default="unknown_requires_fact_review")
    command.add_argument("--evidence-status", default="user_confirmed", choices=[
        "user_confirmed", "verified_source", "verified_position", "candidate", "unverified",
    ])
    command.add_argument("--privacy-passed", action="store_true")
    command.add_argument("--counts-toward-frequency", action="store_true")
    command.add_argument("--content-signal-only", action="store_true")
    command.add_argument("--cluster-reviewed", action="store_true")
    command.add_argument("--repeat-confirmed", action="store_true")
    command.add_argument("--synthetic-only", action="store_true")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    add_capture_arguments(commands.add_parser("capture", help="Append one explicitly de-identified signal."))
    build = commands.add_parser("build", help="Build a deterministic candidate snapshot and weekly Top 5.")
    build.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    build.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    validate = commands.add_parser("validate-bundle")
    validate.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    commands.add_parser("doctor")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.command == "capture":
            result = append_observation(args.ledger, build_observation(args))
        elif args.command == "build":
            result = build_bundle(args.ledger, args.output)
        elif args.command == "validate-bundle":
            validate_bundle(args.output)
            result = {"status": "pass", "output": str(args.output)}
        else:
            result = doctor()
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except DiscoveryError as error:
        print(json.dumps({"status": error.code, "message": str(error)}, ensure_ascii=False, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
