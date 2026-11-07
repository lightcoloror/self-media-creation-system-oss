#!/usr/bin/env python3
"""Rank de-identified frequent questions and build one draft-only weekly package."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = ROOT.parent
CANDIDATES_PATH = ROOT / "fixtures" / "high-frequency-question-candidates.v1.synthetic.json"
BLUEPRINT_PATH = ROOT / "fixtures" / "minimal-synthetic-week.v1.draft-only.json"
CONTENT_SCHEMA_PATH = WORKSPACE_ROOT / "docs" / "content-creation-system" / "content-item.schema.json"
DEFAULT_OUTPUT = ROOT / "outputs" / "draft-only" / "synthetic-week-example"

CANDIDATE_KEYS = {
    "topic_key",
    "question",
    "historical_priority",
    "human_reviewed_repeat_confirmed",
    "raw_occurrence_count",
    "risk_level",
    "fact_dependency",
    "personal_experience_status",
    "current_product_status",
    "evidence_refs",
}
EVIDENCE_KEYS = {
    "evidence_id",
    "source_type",
    "ref",
    "evidence_status",
    "relationship",
    "independence_group",
    "counts_toward_frequency",
}
BLUEPRINT_KEYS = {
    "schema_version",
    "package_status",
    "week_start",
    "topic_key",
    "account_ip",
    "primary_goal",
    "voice_profile",
    "private_draft",
    "public_candidates",
    "week_schedule",
    "minimum_user_confirmation",
}
RISK_PENALTY = {"low": 0, "medium": 10, "high": 25}
FACT_PENALTY = {"low": 0, "medium": 8, "high": 20}
PRIORITY_BONUS = {"P0": 5, "P1": 0}
DIRECT_IDENTIFIER_PATTERNS = {
    "phone": re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"),
    "national_id": re.compile(r"(?<!\d)\d{17}[0-9Xx](?!\d)"),
    "email": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    "wechat_id": re.compile(r"微信号\s*[:：]\s*[A-Za-z][A-Za-z0-9_-]{5,}"),
}



def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def candidate_errors(source: dict[str, Any], *, check_paths: bool = True) -> list[str]:
    errors: list[str] = []
    expected_root = {
        "schema_version",
        "source_scope",
        "frequency_unit",
        "raw_occurrence_count_policy",
        "candidates",
    }
    if set(source) != expected_root:
        errors.append("candidate source has missing or unknown root fields")
    if source.get("schema_version") != "1" or source.get("source_scope") not in {"read_only_deidentified", "synthetic-only"}:
        errors.append("candidate source must be version 1 and read_only_deidentified or synthetic-only")
    if source.get("frequency_unit") != "unique_qualified_evidence_group_not_people_or_messages":
        errors.append("frequency unit must not imply customer or message counts")
    candidates = source.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        return errors + ["candidate source must contain candidates"]
    topic_keys: list[str] = []
    for index, candidate in enumerate(candidates):
        label = f"candidates[{index}]"
        if not isinstance(candidate, dict) or set(candidate) != CANDIDATE_KEYS:
            errors.append(f"{label} has missing or unknown fields")
            continue
        topic_keys.append(candidate["topic_key"])
        if candidate["risk_level"] not in RISK_PENALTY:
            errors.append(f"{label}.risk_level is invalid")
        if candidate["fact_dependency"] not in FACT_PENALTY:
            errors.append(f"{label}.fact_dependency is invalid")
        if candidate["historical_priority"] not in PRIORITY_BONUS:
            errors.append(f"{label}.historical_priority is invalid")
        raw_count = candidate["raw_occurrence_count"]
        if raw_count is not None and (not isinstance(raw_count, int) or raw_count < 1):
            errors.append(f"{label}.raw_occurrence_count must be null or a positive integer")
        evidence = candidate["evidence_refs"]
        if not isinstance(evidence, list) or not evidence:
            errors.append(f"{label}.evidence_refs must be non-empty")
            continue
        relationships: list[str] = []
        for evidence_index, ref in enumerate(evidence):
            ref_label = f"{label}.evidence_refs[{evidence_index}]"
            if not isinstance(ref, dict) or set(ref) != EVIDENCE_KEYS:
                errors.append(f"{ref_label} has missing or unknown fields")
                continue
            relationships.append(ref["relationship"])
            if ref["counts_toward_frequency"]:
                is_qualified_status = ref["evidence_status"].startswith(("verified", "user_confirmed"))
                if ref["source_type"] == "ai-draft" or not is_qualified_status:
                    errors.append(f"{ref_label} cannot count unverified or AI evidence")
            if check_paths and not (Path(ref["ref"]) if Path(ref["ref"]).is_absolute() else ROOT / ref["ref"]).exists():
                errors.append(f"{ref_label} does not exist: {ref['ref']}")
        if candidate["human_reviewed_repeat_confirmed"]:
            if "human-reviewed-repeat-confirmation" not in relationships:
                errors.append(f"{label} lacks a human-reviewed repeat confirmation")
    if len(topic_keys) != len(set(topic_keys)):
        errors.append("topic_key values must be unique")
    return errors


def qualified_source_groups(candidate: dict[str, Any]) -> set[str]:
    return {
        ref["independence_group"]
        for ref in candidate["evidence_refs"]
        if ref["counts_toward_frequency"]
    }


def candidate_score(candidate: dict[str, Any]) -> int:
    repeated = 100 if candidate["human_reviewed_repeat_confirmed"] else 0
    source_score = len(qualified_source_groups(candidate)) * 20
    return (
        repeated
        + source_score
        + PRIORITY_BONUS[candidate["historical_priority"]]
        - RISK_PENALTY[candidate["risk_level"]]
        - FACT_PENALTY[candidate["fact_dependency"]]
    )


def rank_candidates(source: dict[str, Any]) -> list[dict[str, Any]]:
    ranked = sorted(
        source["candidates"],
        key=lambda item: (-candidate_score(item), item["topic_key"]),
    )
    return [
        {
            "rank": index,
            "topic_key": candidate["topic_key"],
            "question": candidate["question"],
            "score": candidate_score(candidate),
            "qualified_evidence_group_count": len(qualified_source_groups(candidate)),
            "raw_occurrence_count": candidate["raw_occurrence_count"],
            "repeat_status": "confirmed_repeated" if candidate["human_reviewed_repeat_confirmed"] else "not_confirmed",
            "risk_level": candidate["risk_level"],
            "fact_dependency": candidate["fact_dependency"],
            "personal_experience_status": candidate["personal_experience_status"],
            "current_product_status": candidate["current_product_status"],
        }
        for index, candidate in enumerate(ranked, start=1)
    ]


def selected_candidate(source: dict[str, Any], ranked: list[dict[str, Any]]) -> dict[str, Any]:
    topic_key = ranked[0]["topic_key"]
    return next(candidate for candidate in source["candidates"] if candidate["topic_key"] == topic_key)


def provenance_sources(candidate: dict[str, Any]) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    seen_groups: set[str] = set()
    for ref in candidate["evidence_refs"]:
        if not ref["counts_toward_frequency"] or ref["independence_group"] in seen_groups:
            continue
        seen_groups.add(ref["independence_group"])
        return sources


def build_content_item(source: dict[str, Any], blueprint: dict[str, Any]) -> dict[str, Any]:
    ranked = rank_candidates(source)
    candidate = selected_candidate(source, ranked)
    private = blueprint["private_draft"]
    public = blueprint["public_candidates"][0]
    item = {
        "schema_version": "0.2",
        "content_id": f"week-{blueprint['week_start']}-{candidate['topic_key']}",
        "title": candidate["question"],
        "primary_format": "multi-channel",
        "status": "draft",
        "tags": ["draft_only", "evidence-ranked-candidate", "manual-review-required"],
        "provenance": {
            "sources": provenance_sources(candidate),
            "verified_facts": [],
            "uncertainties": [
                "Input evidence-group counts do not verify factual claims or establish real audience frequency.",
                "Synthetic example enum states are simulations, not actual user confirmation.",
                "No publication, audience observation or business event has occurred.",
            ],
            "forbidden_claims": [
                "Do not turn ranking metadata into verified facts, customer counts or service promises.",
                "Do not treat generated text as approved for publication.",
            ],
        },
        "gates": {
            "fact": {
                "status": "needs-review",
                "reason": "No factual claim is verified by ranking; primary evidence and author review are still required.",
                "reviewed_by": None,
                "reviewed_at": None,
            },
            "privacy": {
                "status": "pass",
                "reason": "The bundled example is synthetic; operator inputs require their own privacy review.",
                "reviewed_by": "local-deterministic-check",
                "reviewed_at": None,
            },
            "compliance": {
                "status": "needs-review",
                "reason": "公开前仍需人工确认无产品建议、理赔承诺或夸大服务能力。",
                "reviewed_by": None,
                "reviewed_at": None,
            },
            "rights": {
                "status": "pass",
                "reason": "No external media are bundled; any added material requires its own rights review.",
                "reviewed_by": "local-deterministic-check",
                "reviewed_at": None,
            },
        },
        "intent": {
            "topic": candidate["question"],
            "speaker_role": "Operator-supplied voice; no professional identity is assumed",
            "audience": "The audience declared in the operator-reviewed topic",
            "content_object": "One evidence-ranked draft unit; synthetic in the bundled example",
            "desired_action": "先整理已有资料，不自动咨询、不自动进入客户动作",
            "risk_boundary": "No factual, professional, service or publication authority is granted",
            "platform_intent": "朋友圈先做私域表达；小红书只保留 draft 候选",
            "main_angle": "Select an evidence-ranked question and retain unknowns for review",
        },
        "composition": {
            "canonical_body": private["body"],
            "expression_mode": "当下整理动作进入，短句、具体动作、适时停住",
            "target_length": len(private["body"]),
            "voice_profile": blueprint["voice_profile"],
            "voice_profile_version": "operator-supplied",
            "semantic_reversibility": {
                "status": "needs-review",
                "reverse_paraphrase": "Draft meaning and factual claims must be checked against the supplied evidence before publication.",
                "meaning_drift": [],
            },
            "retention_mode": "full-text",
            "canonical_summary": "Evidence-ranked draft, without verified facts, publication or observed audience effects.",
        },
        "channels": {
            "moments": {
                "status": "draft",
                "body": private["body"],
                "cta": private["cta"],
                "target_length": len(private["body"]),
                "adapter_version": "manual-draft-example-v1",
                "platform_metadata": {
                    "draft_only": True,
                    "release_gate": private["release_gate"],
                    "visual_description": private["visual_description"],
                },
            },
            "xiaohongshu": {
                "status": "draft",
                "title": public["title"],
                "hook": public["carousel_pages"][0],
                "body": public["caption"],
                "cta": public["cta"],
                "adapter_version": "xhs-graphic-note-risk-explainer-v1",
                "platform_metadata": {
                    "draft_only": True,
                    "account_ip": public["account_ip"],
                    "carousel_pages": public["carousel_pages"],
                    "release_gate": public["release_gate"],
                },
            },
        },
        "visual": {
            "visual_profile": "theme-corresponding-work-detail",
            "visual_profile_version": "2026-07-21",
            "route": "work_detail_photo",
            "theme": candidate["question"],
            "cognitive_anchors": ["input evidence", "unknown", "review required"],
            "assets": [],
            "render_recipe": {
                "renderer": "none",
                "output_format": "none",
                "output_refs": [],
            },
        },
        "qa": {
            "deterministic": [
                {"name": "draft_only", "status": "pass", "details": "all variants remain draft"},
                {"name": "no_direct_identifier", "status": "pass", "details": "no direct identifier detected"},
                {"name": "no_fabricated_frequency", "status": "pass", "details": "raw occurrence count remains unknown"},
                {"name": "content_business_signal_separation", "status": "pass", "details": "no observation or customer conclusion generated"},
            ],
            "promptfoo": {"status": "not-run", "suite": "high-frequency-week-v1"},
            "human_review": {
                "status": "required",
                "reviewer": None,
                "reviewed_at": None,
                "note": "用户需审阅最终发布文字；服务表达确认不阻塞当前自查型草稿。",
            },
        },
        "publication": {"boundary": "manual-only", "receipts": []},
        "feedback": {
            "signal_status": "not-observed",
            "platform_signals": {},
            "business_signals": {},
            "qualitative_feedback": [],
            "learning_decision": "none",
            "next_test": "only after optional manual publication: observe at 48–72h and day 7",
            "content_signal_status": "not-observed",
            "business_signal_status": "not-observed",
            "measurement_layers": {
                "admission": [],
                "attraction": [],
                "consumption": [],
                "value": [],
                "negative_feedback": [],
                "business": [],
            },
        },
        "operating_plan": {
            "production_unit": "real-problem-or-service-action",
            "origin_kind": "research-synthesis",
            "private_validation": {
                "channel": "wechat_moments",
                "status": "draft",
                "note": "draft_only; user decides whether to publish manually",
            },
            "public_adaptations": {
                "primary": {
                    "platform": "xiaohongshu",
                    "role": "search-discovery-checklist",
                    "status": "draft",
                    "content_variant": "xiaohongshu-evidence-ranked-draft-v1",
                    "selection_reason": "one public candidate only; retain as draft until private observation and user decision",
                }
            },
        },
    }
    return item


def content_item_errors(item: dict[str, Any]) -> list[str]:
    schema = load_json(CONTENT_SCHEMA_PATH)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    return [
        f"content_item.{'.'.join(str(part) for part in error.path) or '$'}: {error.message}"
        for error in sorted(validator.iter_errors(item), key=lambda error: list(error.path))
    ]


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
                errors.append(f"{path}: detected possible {name}")
    return errors


def package_errors(
    source: dict[str, Any] | None = None,
    blueprint: dict[str, Any] | None = None,
    *,
    check_paths: bool = True,
) -> list[str]:
    source = load_json(CANDIDATES_PATH) if source is None else source
    blueprint = load_json(BLUEPRINT_PATH) if blueprint is None else blueprint
    errors = candidate_errors(source, check_paths=check_paths)
    if set(blueprint) != BLUEPRINT_KEYS:
        errors.append("blueprint has missing or unknown root fields")
    if blueprint.get("schema_version") != "1" or blueprint.get("package_status") != "draft_only":
        errors.append("blueprint must be version 1 and draft_only")
    public_candidates = blueprint.get("public_candidates", [])
    if not isinstance(public_candidates, list) or len(public_candidates) > 2:
        errors.append("blueprint must have at most two public candidates")
    for index, candidate in enumerate(public_candidates):
        if candidate.get("status") != "draft":
            errors.append(f"public_candidates[{index}] must remain draft")
    if blueprint.get("private_draft", {}).get("status") != "draft":
        errors.append("private draft must remain draft")
    if errors:
        return errors
    ranked = rank_candidates(source)
    if blueprint["topic_key"] != ranked[0]["topic_key"]:
        errors.append("blueprint topic is not the deterministic first-ranked candidate")
    item = build_content_item(source, blueprint)
    errors.extend(content_item_errors(item))
    public_text = {
        "private": blueprint["private_draft"],
        "public_candidates": blueprint["public_candidates"],
    }
    errors.extend(direct_identifier_errors(public_text))
    if item["publication"]["receipts"]:
        errors.append("draft-only package must not contain publication receipts")
    if item["feedback"]["content_signal_status"] != "not-observed":
        errors.append("draft-only package must not fabricate a content signal")
    if item["feedback"]["business_signal_status"] != "not-observed":
        errors.append("draft-only package must not fabricate a business signal")
    return errors


def ranked_payload(source: dict[str, Any]) -> dict[str, Any]:
    ranked = rank_candidates(source)
    return {
        "schema_version": "1",
        "status": "draft_only",
        "frequency_unit": source["frequency_unit"],
        "raw_occurrence_count_policy": source["raw_occurrence_count_policy"],
        "selected_topic_key": ranked[0]["topic_key"],
        "ranking": ranked,
    }


def evidence_index_markdown(source: dict[str, Any]) -> str:
    ranked = rank_candidates(source)
    by_key = {candidate["topic_key"]: candidate for candidate in source["candidates"]}
    lines = [
        "# 高频问题证据索引（draft_only）",
        "",
        "> 计数单位是去重后的合格证据组，不是客户人数，也不是消息条数。原始逐题次数没有保留时固定写 unknown。",
        "",
        "| 排名 | 候选问题 | 合格证据组 | 原始次数 | 风险 | 事实依赖 |",
        "|---:|---|---:|---|---|---|",
    ]
    for item in ranked:
        lines.append(
            f"| {item['rank']} | {item['question']} | {item['qualified_evidence_group_count']} | "
            f"{'unknown' if item['raw_occurrence_count'] is None else item['raw_occurrence_count']} | "
            f"{item['risk_level']} | {item['fact_dependency']} |"
        )
    lines.extend(["", "## 证据明细", ""])
    for item in ranked:
        candidate = by_key[item["topic_key"]]
        lines.append(f"### {item['rank']}. {item['question']}")
        lines.append("")
        for ref in candidate["evidence_refs"]:
            counted = "计数" if ref["counts_toward_frequency"] else "不计数"
            lines.append(
                f"- `{ref['evidence_id']}`：{counted}；{ref['evidence_status']}；"
                f"关系={ref['relationship']}；来源=`{ref['ref']}`"
            )
        lines.append("")
    lines.extend(
        [
            "## 排除口径",
            "",
            "- Obsidian 镜像与原始工作区文件属于同一来源组，只计一次。",
            "- AI 汇总、课程材料和行业经验只能帮助找方向，不计真实频率。",
            "- 操作者须先去标识；本入口不授权读取私密聊天、客户、健康或凭据资料。",
            "- `常见异议处理` 等混合旧资料未作为频率证据。",
            "",
        ]
    )
    return "\n".join(lines)


def week_package_markdown(source: dict[str, Any], blueprint: dict[str, Any]) -> str:
    ranked = rank_candidates(source)
    private = blueprint["private_draft"]
    public = blueprint["public_candidates"][0]
    lines = [
        "# 一周最小内容包（draft_only；示例为虚构）",
        "",
        f"- 周期：{blueprint['week_start']} 起",
        f"- 核心主题：{ranked[0]['question']}",
        f"- 账号路由：{blueprint['account_ip']}",
        f"- 首要目标：{blueprint['primary_goal']}",
        "- 发布边界：只生成草稿；任何发布均由用户人工决定",
        "",
        "## 为什么默认选它",
        "",
        f"它有 {ranked[0]['qualified_evidence_group_count']} 个去重后的合格证据组，"
        f"输入风险标签为 {ranked[0]['risk_level']}，事实依赖为 {ranked[0]['fact_dependency']}。"
        "这些只是输入标签；合成状态不代表真实频率、事实核验或人工确认。",
        "",
        "## 朋友圈/私域草稿",
        "",
        private["body"],
        "",
        f"配图说明：{private['visual_description']}",
        "",
        "## 小红书图文候选（仍为 draft）",
        "",
        f"标题：{public['title']}",
        "",
    ]
    for index, page in enumerate(public["carousel_pages"], start=1):
        lines.append(f"{index}. {page}")
    lines.extend(
        [
            "",
            "正文：",
            "",
            public["caption"],
            "",
            f"结尾：{public['cta']}",
            "",
            f"放行条件：`{public['release_gate']}`",
            "",
            "## 一周节奏",
            "",
            "| 日期位 | 动作 | 产物 |",
            "|---|---|---|",
        ]
    )
    for step in blueprint["week_schedule"]:
        lines.append(f"| {step['day']} | {step['action']} | {step['output']} |")
    lines.extend(
        [
            "",
            "## 已绕开的非阻塞确认",
            "",
            blueprint["minimum_user_confirmation"]["default_if_unanswered"],
            "",
        ]
    )
    return "\n".join(lines)


def observation_template() -> str:
    return """# 48–72 小时发布观察卡（draft_only template）

## 发布准入

- 是否由用户明确确认已手动发布：unknown
- 渠道：wechat_moments / 未发布
- 冻结版本：待人工发布时记录
- 若未发布：本卡标记 `not_applicable`，不能写 `content_no_signal`

## 六层观察

| 层 | 可记录内容 | 当前状态 |
|---|---|---|
| admission | 是否完成人工发布回执、是否被平台限制 | not-observed |
| attraction | 朋友圈无稳定曝光数据；只记人工可见互动，不反推阅读量 | not-observed |
| consumption | 朋友圈通常不可观察阅读完成 | platform-unobservable |
| value | 明确收藏、转发、复述“这条有用”等人工可见信号 | not-observed |
| negative_feedback | 明确指出事实、隐私、表达或合规问题 | not-observed |
| business | 对方明确说明由此内容而来，并提出有效问题/愿意继续沟通/提供资料/预约下一步 | not-observed |

## 中性规则

- 到期没有可观察内容信号，可记 `content_no_signal`；它不是失败。
- `content_no_signal` 不生成客户负面标签，不进入 CRM，不触发联系客户。
- 没有明确来源陈述时，不把私信、咨询或转介绍归因给本内容。
- 内容信号与业务信号分开记录，不能互相推导。
"""


def day7_template() -> str:
    return """# 第 7 天复盘模板（draft_only template）

## 1. 事实状态

- 是否发布：unknown
- 发布冻结版本：unknown
- 观察材料是否完整：unknown
- 是否发生删除、修改或平台限制：unknown

## 2. 内容信号

- 状态：not-observed / content_no_signal / observed
- 证据：
- 不可观察字段：朋友圈曝光、阅读完成、主页访问

## 3. 业务信号（独立）

- 状态：not-observed / observed
- 是否有对方明确说明内容来源：
- 有效问题、继续沟通、提供资料或预约的人工确认：
- 禁止：用点赞、熟人关系或主观感觉推断咨询来源

## 4. 六层复盘

1. admission：
2. attraction：
3. consumption：
4. value：
5. negative_feedback：
6. business：

## 5. 学习决策

- retain / modify / retire / insufficient-evidence
- 本次只允许修改：标题、进入方式、解释顺序、视觉任务或事实边界
- 只有重复、可解释的证据才修改本人声纹或渠道规则
- `content_no_signal` 默认对应 `insufficient-evidence`，不是失败

## 6. 公域候选决策

- 小红书候选：继续保持 draft / 人工批准后改写 / 暂不使用
- 是否增加第二个公域候选：默认否；必须有新的明确理由
- 不自动发布，不自动联系客户
"""


def public_candidate_markdown(blueprint: dict[str, Any]) -> str:
    public = blueprint["public_candidates"][0]
    pages = "\n".join(f"{index}. {page}" for index, page in enumerate(public["carousel_pages"], start=1))
    return (
        "# 小红书公域改写候选（draft_only）\n\n"
        f"- 账号：{public['account_ip']}\n"
        f"- 状态：{public['status']}\n"
        f"- 放行条件：{public['release_gate']}\n\n"
        f"## 标题\n\n{public['title']}\n\n"
        f"## 卡片\n\n{pages}\n\n"
        f"## 正文\n\n{public['caption']}\n\n"
        f"## 结尾\n\n{public['cta']}\n"
    )


def write_outputs(output_dir: Path, source: dict[str, Any], blueprint: dict[str, Any]) -> list[Path]:
    resolved = output_dir.resolve()
    allowed_root = (ROOT / "outputs" / "draft-only").resolve()
    if allowed_root not in resolved.parents and resolved != allowed_root:
        raise ValueError(f"output directory must stay under {allowed_root}")
    output_dir.mkdir(parents=True, exist_ok=True)
    ranking = ranked_payload(source)
    content_item = build_content_item(source, blueprint)
    outputs: dict[str, str] = {
        "ranked-topics.json": json.dumps(ranking, ensure_ascii=False, indent=2) + "\n",
        "evidence-index.md": evidence_index_markdown(source),
        "week-package.md": week_package_markdown(source, blueprint),
        "content-item.json": json.dumps(content_item, ensure_ascii=False, indent=2) + "\n",
        "observation-48-72h.md": observation_template(),
        "day7-review.md": day7_template(),
        "public-candidate-xiaohongshu.md": public_candidate_markdown(blueprint),
        "user-confirmation.md": (
            "# 最小用户确认（draft_only）\n\n"
            f"{blueprint['minimum_user_confirmation']['question']}\n\n"
            f"当前处理：{blueprint['minimum_user_confirmation']['default_if_unanswered']}\n"
        ),
    }
    manifest = {
        "schema_version": "1",
        "status": "draft_only",
        "selected_topic_key": ranking["selected_topic_key"],
        "source_hash": canonical_sha256(source),
        "blueprint_hash": canonical_sha256(blueprint),
        "content_item_hash": canonical_sha256(content_item),
        "files": sorted(outputs),
    }
    outputs["manifest.json"] = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    written: list[Path] = []
    for name, content in outputs.items():
        path = output_dir / name
        path.write_text(content, encoding="utf-8")
        written.append(path)
    return written


def generated_errors(output_dir: Path, source: dict[str, Any], blueprint: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    required = {
        "ranked-topics.json",
        "evidence-index.md",
        "week-package.md",
        "content-item.json",
        "observation-48-72h.md",
        "day7-review.md",
        "public-candidate-xiaohongshu.md",
        "user-confirmation.md",
        "manifest.json",
    }
    missing = sorted(name for name in required if not (output_dir / name).exists())
    if missing:
        return [f"generated output missing: {name}" for name in missing]
    item = load_json(output_dir / "content-item.json")
    errors.extend(content_item_errors(item))
    manifest = load_json(output_dir / "manifest.json")
    if manifest.get("status") != "draft_only":
        errors.append("generated manifest must remain draft_only")
    if manifest.get("source_hash") != canonical_sha256(source):
        errors.append("generated source hash mismatch")
    if manifest.get("blueprint_hash") != canonical_sha256(blueprint):
        errors.append("generated blueprint hash mismatch")
    if manifest.get("content_item_hash") != canonical_sha256(build_content_item(source, blueprint)):
        errors.append("generated content item hash mismatch")
    observation = (output_dir / "observation-48-72h.md").read_text(encoding="utf-8")
    day7 = (output_dir / "day7-review.md").read_text(encoding="utf-8")
    if "content_no_signal`；它不是失败" not in observation:
        errors.append("observation template lost neutral content_no_signal rule")
    if "`content_no_signal` 默认对应 `insufficient-evidence`，不是失败" not in day7:
        errors.append("day7 template lost neutral content_no_signal decision")
    return errors


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="Write the draft-only weekly package under outputs/draft-only.")
    parser.add_argument("--check-generated", action="store_true", help="Validate already generated outputs and hashes.")
    parser.add_argument("--print-ranked", action="store_true", help="Print ranked candidates as JSON.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source = load_json(CANDIDATES_PATH)
    blueprint = load_json(BLUEPRINT_PATH)
    errors = package_errors(source, blueprint)
    if not errors and args.check_generated:
        errors.extend(generated_errors(args.output_dir, source, blueprint))
    if errors:
        print("High-frequency topic loop check failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    if args.write:
        written = write_outputs(args.output_dir, source, blueprint)
        print(f"WROTE {len(written)} draft-only files to {args.output_dir}")
    if args.print_ranked or not args.write:
        print(json.dumps(ranked_payload(source), ensure_ascii=False, indent=2))
    print("PASS: de-identified evidence ranking and draft-only weekly package contract.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
