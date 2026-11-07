#!/usr/bin/env python3
"""Offline P0 bridge for content-bundle.v1 -> analysis-result.v1.

The bridge is deterministic. It never calls a model, network service, NoteRx,
publisher, analytics service, or real-comment source.
"""

from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))
from content_review_rules import has_series_dependency

FIXTURE = ROOT / "fixtures" / "content-bundle.v1.fixture.json"
CANONICAL_ROUTING_PATH = ROOT / "scripts" / "canonical_routing.py"
CANONICAL_ROUTING_SPEC = importlib.util.spec_from_file_location(
    "self_media_canonical_routing", CANONICAL_ROUTING_PATH
)
assert CANONICAL_ROUTING_SPEC and CANONICAL_ROUTING_SPEC.loader
CANONICAL_ROUTING = importlib.util.module_from_spec(CANONICAL_ROUTING_SPEC)
CANONICAL_ROUTING_SPEC.loader.exec_module(CANONICAL_ROUTING)
CANONICAL_ROUTING_SET = CANONICAL_ROUTING.load_contracts()
CANONICAL_ROUTER = CANONICAL_ROUTING_SET["components"]["task_router"]
PLATFORMS = set(CANONICAL_ROUTER["enums"]["platform"])
SOURCE_TYPES = {"user-confirmed", "local-logseq-fact", "obsidian-synthesis", "ai-draft", "official-source", "candidate-evidence", "published-content", "unknown"}
EVIDENCE_STATUSES = {"verified", "candidate", "unknown"}
PRIVACY_STATUSES = {"cleared", "deidentified", "not-applicable", "unknown"}
STRUCTURE_ROUTES = set(CANONICAL_ROUTER["enums"]["structure_route"])
ROUTING_FIELDS = set(CANONICAL_ROUTER["required_inputs"]) | set(
    CANONICAL_ROUTER["output_contract"]
)
ROLES = {
    "clarity-reader": "检查读者是否能在开头理解主要信息与内容边界。",
    "route-adapter": "检查格式、平台、受众和首要目标是否提供了可执行路由。",
    "evidence-safety": "检查事实来源、隐私状态以及医疗保险风险提示。",
    "voice-visual": "检查已确认声纹和视觉路线是否被明确交代。",
}
PHONE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
ID_RE = re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")
PROFILE_RE = re.compile(r"^profile-[a-f0-9]{64}$")
HIGH_RISK_TERMS = ("理赔", "赔付", "保单", "核保", "治疗", "疾病", "质子", "癌症")
PROMISE_TERMS = ("保证", "必赔", "全额赔", "一定赔", "100%赔", "治愈", "最好")


class ContractError(ValueError):
    pass


def require_string(mapping: dict[str, Any], key: str, errors: list[str], *, allow_empty: bool = False) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        errors.append(f"{key} must be a {'string' if allow_empty else 'non-empty string'}")
        return ""
    return value


def validate_bundle(bundle: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(bundle, dict):
        return ["root must be an object"]
    expected_top = {"schema_version", "bundle_id", "created_at", "platform", "privacy", "items"}
    unknown_top = set(bundle) - expected_top
    if unknown_top:
        errors.append(f"unknown top-level fields: {', '.join(sorted(unknown_top))}")
    if bundle.get("schema_version") != "content-bundle.v1":
        errors.append("schema_version must be content-bundle.v1")
    for key in ("bundle_id", "created_at"):
        require_string(bundle, key, errors)
    if bundle.get("platform") not in PLATFORMS:
        errors.append("platform is not supported by the current task-router contract")
    privacy = bundle.get("privacy")
    required_privacy = {"local_only": True, "mode": "dry_run", "comments_included": False, "metrics_included": False, "raw_media_included": False}
    if not isinstance(privacy, dict):
        errors.append("privacy must be an object")
    else:
        if set(privacy) != set(required_privacy) | {"content_text_may_contain_personal_data"}:
            errors.append("privacy fields must exactly match content-bundle.v1")
        for key, expected in required_privacy.items():
            if privacy.get(key) != expected:
                errors.append(f"privacy.{key} must be {expected!r}")
        if not isinstance(privacy.get("content_text_may_contain_personal_data"), bool):
            errors.append("privacy.content_text_may_contain_personal_data must be boolean")
    items = bundle.get("items")
    if not isinstance(items, list) or not items:
        errors.append("items must be a non-empty array")
        return errors
    for index, item in enumerate(items):
        prefix = f"items[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{prefix} must be an object")
            continue
        allowed_item = {"profile_id", "content_id", "content", "routing_context", "evidence_refs"}
        extra = set(item) - allowed_item
        if extra:
            errors.append(f"{prefix} has prohibited fields: {', '.join(sorted(extra))}")
        profile_id = item.get("profile_id")
        if not isinstance(profile_id, str) or not PROFILE_RE.fullmatch(profile_id):
            errors.append(f"{prefix}.profile_id must be an opaque profile-<sha256> identifier")
        require_string(item, "content_id", errors)
        content = item.get("content")
        if not isinstance(content, dict):
            errors.append(f"{prefix}.content must be an object")
        else:
            if set(content) != {"title", "body", "visual_description", "tags"}:
                errors.append(f"{prefix}.content fields must exactly match content-bundle.v1")
            for key in ("title", "body", "visual_description"):
                require_string(content, key, errors, allow_empty=True)
            if not isinstance(content.get("tags"), list) or not all(isinstance(tag, str) for tag in content.get("tags", [])):
                errors.append(f"{prefix}.content.tags must be an array of strings")
        context = item.get("routing_context")
        if context is not None and not isinstance(context, dict):
            errors.append(f"{prefix}.routing_context must be an object when supplied")
        elif isinstance(context, dict) and set(context) - ROUTING_FIELDS:
            errors.append(f"{prefix}.routing_context has prohibited fields")
        if isinstance(context, dict):
            structure_route = context.get("structure_route")
            if structure_route is not None and structure_route not in STRUCTURE_ROUTES:
                errors.append(f"{prefix}.routing_context.structure_route is invalid")
            if structure_route == "custom" and not isinstance(context.get("structure_route_note"), str):
                errors.append(f"{prefix}.routing_context.structure_route_note is required for custom")
            planning_scope = context.get("planning_scope")
            if planning_scope is not None and planning_scope not in {"single", "series"}:
                errors.append(f"{prefix}.routing_context.planning_scope is invalid")
            if planning_scope == "series":
                for field in ("series_question", "current_piece_decision"):
                    if not isinstance(context.get(field), str) or not context[field].strip():
                        errors.append(f"{prefix}.routing_context.{field} is required for series")
            next_pieces = context.get("next_piece_candidates")
            if next_pieces is not None and (not isinstance(next_pieces, list) or not all(isinstance(value, str) and value.strip() for value in next_pieces)):
                errors.append(f"{prefix}.routing_context.next_piece_candidates must be an array of non-empty strings")
            override = context.get("manual_route_override")
            if override is not None:
                required_override = {"stage", "from", "to", "reason", "changed_by"}
                if not isinstance(override, dict) or set(override) != required_override:
                    errors.append(f"{prefix}.routing_context.manual_route_override fields are invalid")
                elif (
                    override.get("stage") not in {"topic", "research", "outline", "draft", "review"}
                    or override.get("changed_by") != "human"
                    or any(not isinstance(override.get(field), str) or not override[field].strip() for field in ("from", "to", "reason"))
                ):
                    errors.append(f"{prefix}.routing_context.manual_route_override values are invalid")
        refs = item.get("evidence_refs")
        if not isinstance(refs, list):
            errors.append(f"{prefix}.evidence_refs must be an array")
        else:
            for ref_index, ref in enumerate(refs):
                if not isinstance(ref, dict):
                    errors.append(f"{prefix}.evidence_refs[{ref_index}] must be an object")
                    continue
                if set(ref) - {"ref_id", "source_type", "status", "privacy_status", "claim_scope"}:
                    errors.append(f"{prefix}.evidence_refs[{ref_index}] has prohibited fields")
                for key in ("ref_id", "source_type", "status", "privacy_status"):
                    require_string(ref, key, errors)
                if ref.get("source_type") not in SOURCE_TYPES:
                    errors.append(f"{prefix}.evidence_refs[{ref_index}].source_type is invalid")
                if ref.get("status") not in EVIDENCE_STATUSES:
                    errors.append(f"{prefix}.evidence_refs[{ref_index}].status is invalid")
                if ref.get("privacy_status") not in PRIVACY_STATUSES:
                    errors.append(f"{prefix}.evidence_refs[{ref_index}].privacy_status is invalid")
    return errors


def make_finding(fid: str, severity: str, category: str, issue: str, refs: list[str], recommendation: str, confidence: str, reason: str) -> dict[str, Any]:
    return {"id": fid, "severity": severity, "category": category, "issue": issue, "evidence_refs": refs, "recommendation": recommendation, "confidence": confidence, "confidence_reason": reason}


def diagnose_item(item: dict[str, Any], platform: str, privacy: dict[str, Any]) -> dict[str, Any]:
    content = item["content"]
    context = item.get("routing_context") or {}
    refs = item["evidence_refs"]
    ref_ids = [ref["ref_id"] for ref in refs]
    text = "\n".join([content["title"], content["body"], content["visual_description"], " ".join(content["tags"])])
    findings: list[dict[str, Any]] = []
    role_ids: dict[str, list[str]] = {role: [] for role in ROLES}

    def add(role: str, value: dict[str, Any]) -> None:
        findings.append(value)
        role_ids[role].append(value["id"])

    if not content["title"].strip():
        add("clarity-reader", make_finding("clarity-title-missing", "warning", "clarity", "标题为空，读者无法预判内容承诺。", [], "用一句准确标题说明本篇解决的具体问题；不要用未经验证的结果承诺替代标题。", "high", "输入标题为空。"))
    if not content["body"].strip():
        add("clarity-reader", make_finding("clarity-body-missing", "block", "clarity", "正文为空，无法进行内容诊断。", [], "补充待审核正文后再运行诊断。", "high", "输入正文为空。"))
    elif len(content["body"].strip()) < 30:
        add("clarity-reader", make_finding("clarity-body-thin", "info", "clarity", "正文较短，可能缺少情境、主要判断或必要边界。", [], "确认短文是否已包含一件具体事或一个主要判断；案例或科普应补上必要边界。", "medium", "依据字符长度作保守提示，不评价传播效果。"))

    # Voice/visual absence has its own shared-role finding below.
    route_fields = ("account_ip", "content_job", "primary_audience", "primary_goal", "format")
    missing = [field for field in route_fields if not isinstance(context.get(field), str) or not context[field].strip()]
    if missing:
        add("route-adapter", make_finding("route-context-incomplete", "warning", "route", "路由上下文不完整，无法确认应使用的形态适配与质量门。", [], f"补充 routing_context：{', '.join(missing)}。平台不是文体，需先确定内容形态。", "high", "缺少当前 task-router 的关键字段。"))
    if context.get("format") == "moments-short-text" and platform != "wechat-moments":
        add("route-adapter", make_finding("route-format-platform-mismatch", "warning", "route", "朋友圈短文格式与非朋友圈平台组合，需要人工确认是否为跨平台改写。", [], "保留同一事实底座，但按目标平台重新选择格式适配器，不要直接复制发布。", "high", "format 与 platform 的当前合同组合不一致。"))

    structure_route = context.get("structure_route")
    if structure_route == "custom" and not str(context.get("structure_route_note", "")).strip():
        add("route-adapter", make_finding(
            "custom-structure-route-note-missing", "warning", "route",
            "自定义结构路线缺少展开顺序或选择理由。",
            [],
            "在 structure_route_note 中写清本篇的展开顺序，以及为什么现有路线不适合。",
            "high", "structure_route 明确为 custom。"
        ))
    if context.get("planning_scope") == "series" and not str(context.get("current_piece_decision", "")).strip():
        add("route-adapter", make_finding(
            "series-current-piece-missing", "warning", "route",
            "系列规划尚未限定本篇只解决的一个问题。",
            [],
            "补充 current_piece_decision，并为本篇单独选择内容任务与结构路线。",
            "high", "planning_scope 明确为 series。"
        ))
    if has_series_dependency(
        "\n".join((content["title"], content["body"]))
    ):
        add("route-adapter", make_finding(
            "series-item-not-standalone", "block", "route",
            "本条显式依赖上一条，或把本条承诺的答案留到下一条，不能独立成立。",
            [],
            "补齐本条必要情境、核心判断和回报；系列顺序只留在内部日历，不要求观众先看其他内容。",
            "high", "正文或标题出现明确的跨条依赖表达。"
        ))
    override = context.get("manual_route_override")
    if isinstance(override, dict) and structure_route and override.get("to") != structure_route:
        add("route-adapter", make_finding(
            "manual-route-override-not-applied", "warning", "route",
            "人工改道记录的目标路线与当前结构路线不一致。",
            [],
            "以人工决定为准更新 structure_route，并重跑受影响的提纲、标题承诺和质量门。",
            "high", "manual_route_override.to 与 structure_route 不一致。"
        ))

    question_route_required = context.get("content_job") == "question-answer" or context.get("primary_goal") == "search-discovery"
    question_route = context.get("question_structure_route")
    if question_route_required and question_route not in {"direct-answer", "decision-reframe"}:
        add("route-adapter", make_finding(
            "question-structure-route-missing", "warning", "route",
            "问答型内容尚未选择直接回答或条件式重构。",
            [],
            "先判断原问题是否已经准确：准确则 direct-answer；只有遗漏关键前提且会影响决定时才选 decision-reframe。",
            "high", "content_job 为 question-answer 或 primary_goal 为 search-discovery，但未选择有效 question_structure_route。"
        ))

    if question_route == "direct-answer":
        direct_fields = ("audience_entry_question", "surface_answer", "scope_boundary")
        missing_direct = [field for field in direct_fields if not isinstance(context.get(field), str) or not context[field].strip()]
        if missing_direct:
            add("route-adapter", make_finding(
                "direct-answer-incomplete", "warning", "route",
                "直接回答路线缺少原问题、答案或必要边界。",
                [],
                f"补充直接回答字段：{', '.join(missing_direct)}；不要无必要地另造专业核心问题。",
                "high", "question_structure_route 明确为 direct-answer。"
            ))

    if question_route == "decision-reframe":
        reframing_fields = ("audience_entry_question", "surface_answer", "professional_core_question", "client_decision", "scope_boundary")
        missing_reframing = [field for field in reframing_fields if not isinstance(context.get(field), str) or not context[field].strip()]
        if missing_reframing:
            add("route-adapter", make_finding(
                "topic-reframing-incomplete", "warning", "route",
                "条件式重构路线尚未完整区分流量入口、真正问题和客户决定。",
                [],
                f"补充条件式重构字段：{', '.join(missing_reframing)}；先短答表面问题，再只向前重构一层。",
                "high", "question_structure_route 明确为 decision-reframe。"
            ))

    if question_route_required and context.get("public_expertise_level") == "peer-technical":
        add("clarity-reader", make_finding(
            "professional-distance-review", "info", "clarity",
            "搜索发现内容选择了同行技术级表达，需要复核是否符合本篇目标受众。",
            [],
            "如果目标受众确为同行可以保留；否则删去不帮助目标客户完成本篇任务的复杂度。",
            "medium", "问答或搜索发现内容的 public_expertise_level 明确设为 peer-technical。"
        ))

    unknown_refs = [ref["ref_id"] for ref in refs if ref.get("status") != "verified"]
    if unknown_refs:
        add("evidence-safety", make_finding("evidence-unverified", "warning", "evidence", "存在候选或未知证据，不能把相关结论写成既定事实。", unknown_refs, "保留不确定性，补充用户确认或权威来源；未核实前改成问题、经历或待核说明。", "high", "evidence_refs 明确标为 candidate 或 unknown。"))
    if not refs:
        add("evidence-safety", make_finding("evidence-none", "block", "evidence", "没有证据引用，事实状态无法追溯。", [], "至少加入来源状态、隐私状态和适用范围；AI 草稿不能作为事实来源。", "high", "输入 evidence_refs 为空。"))
    privacy_unknown = [ref["ref_id"] for ref in refs if ref.get("privacy_status") == "unknown"]
    if privacy_unknown or privacy["content_text_may_contain_personal_data"]:
        refs_to_show = privacy_unknown
        add("evidence-safety", make_finding("privacy-review-required", "block", "privacy", "证据隐私状态未知或采集端标记正文可能含个人数据。", refs_to_show, "在发布前完成授权或不可逆去标识，并检查组合后的时间线不会重新识别当事人。", "high", "来自 evidence_refs 或 bundle.privacy 的明确标记。"))
    if PHONE_RE.search(text) or ID_RE.search(text):
        add("evidence-safety", make_finding("privacy-direct-identifier", "block", "privacy", "检测到疑似直接身份标识；结果不回显匹配内容。", [], "删除或脱敏手机号、身份证号及任何可定位信息后再诊断。", "high", "本地正则检测到高风险数字模式。"))
    if any(term in text for term in HIGH_RISK_TERMS):
        add("evidence-safety", make_finding("medical-insurance-review", "warning", "medical-insurance", "文本可能涉及医疗或保险事项，必须区分服务解释、合同条件与医疗决定。", ref_ids, "补充适用条件与不确定性；不要替代医生决定，不承诺核保、赔付或治疗结果。", "medium", "基于风险关键词的本地提示，需人工复核语境。"))
    if any(term in text for term in PROMISE_TERMS):
        add("evidence-safety", make_finding("unsupported-promise-risk", "warning", "evidence", "文本出现可能被理解为绝对结果或优劣判断的措辞。", ref_ids, "核对每个结果性表述的证据与边界；不能证实的改为具体经历或删除。", "low", "关键词可能有多义，工具不替代人工语义判断。"))

    if not content["visual_description"].strip():
        add("voice-visual", make_finding("visual-description-missing", "warning", "voice-visual", "未提供视觉说明，无法检查信息是否只依赖颜色或图像。", [], "补充画面主体、文字等价信息、版权来源与可读性说明。", "high", "输入 visual_description 为空。"))
    if not isinstance(context.get("voice_visual_route"), str) or not context.get("voice_visual_route", "").strip():
        add("voice-visual", make_finding("voice-visual-route-missing", "warning", "voice-visual", "未指定声纹与视觉路线，无法检查是否误用泛化 AI 腔调或固定视觉皮肤。", [], "指定已确认的声纹与主题相关视觉路线；不同主题按受众与阅读任务选择视觉方式。", "high", "缺少 voice_visual_route。"))
        role_ids["route-adapter"].append("voice-visual-route-missing")

    roles = [{"role_id": role, "purpose": purpose, "finding_ids": role_ids[role]} for role, purpose in ROLES.items()]
    challenges: list[str] = []
    if any(value["severity"] == "block" for value in findings):
        challenges.append("证据与隐私角色要求先解除 block，再讨论表达优化。")
    if any(value["category"] == "route" for value in findings) and any(value["category"] == "voice-visual" for value in findings):
        challenges.append("路由与声纹角色共同要求：不要把平台模板当作个人表达。")
    return {
        "input_ref": {"profile_id": item["profile_id"], "content_id": item["content_id"]},
        "roles": roles,
        "cross_review": {"summary": "离线规则诊断完成；仅供人工审核，不代表内容质量、推荐权重或真实用户反馈。", "challenges": challenges},
        "findings": findings,
        "warnings": ["未调用线上模型或 NoteRx 服务。", "未模拟真实评论、未发布、未计算爆款或推荐分数。"],
    }


def diagnose(bundle: dict[str, Any]) -> dict[str, Any]:
    errors = validate_bundle(bundle)
    if errors:
        raise ContractError("; ".join(errors))
    results = [diagnose_item(item, bundle["platform"], bundle["privacy"]) for item in bundle["items"]]
    all_findings = [finding for item in results for finding in item["findings"]]
    block_count = sum(finding["severity"] == "block" for finding in all_findings)
    return {
        "schema_version": "analysis-result.v1",
        "result_id": f"analysis-{bundle['bundle_id']}",
        "bundle_id": bundle["bundle_id"],
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "review_required" if block_count else "completed",
        "mode": "dry_run",
        "engine": {"id": "self-media-offline-rules-p0", "version": "1.0.0", "network_calls": 0, "models_called": [], "comments_simulated": False, "published": False},
        "summary": {"item_count": len(results), "finding_count": len(all_findings), "block_count": block_count, "human_review_required": True},
        "items": results,
    }


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ContractError(f"input does not exist: {path}") from error
    except json.JSONDecodeError as error:
        raise ContractError(f"input is not valid JSON: {error.msg}") from error
    if not isinstance(value, dict):
        raise ContractError("input root must be an object")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline content-bundle.v1 diagnostic bridge")
    parser.add_argument("--input", type=Path, default=FIXTURE, help="Deidentified content-bundle.v1 JSON; defaults to the offline fixture.")
    parser.add_argument("--output", type=Path, help="Write analysis-result.v1 JSON atomically. Omit to print JSON to stdout.")
    parser.add_argument("--validate-only", action="store_true", help="Validate input without creating an analysis result.")
    args = parser.parse_args(argv)
    try:
        bundle = load_json(args.input)
        errors = validate_bundle(bundle)
        if errors:
            raise ContractError("; ".join(errors))
        if args.validate_only:
            print(json.dumps({"valid": True, "schema_version": "content-bundle.v1", "mode": "dry_run"}, ensure_ascii=False))
            return 0
        result = diagnose(bundle)
    except ContractError as error:
        print(f"contract error: {error}", file=sys.stderr)
        return 2
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.output.with_suffix(args.output.suffix + ".tmp")
        temporary.write_text(rendered, encoding="utf-8")
        temporary.replace(args.output)
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
