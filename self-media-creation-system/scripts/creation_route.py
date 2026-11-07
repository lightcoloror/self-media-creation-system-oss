#!/usr/bin/env python3
"""Resolve and validate an evidence-based Agent assessment before creative work.

The Agent reads user intent and material evidence. This local code validates its
structured assessment; it neither calls an AI Provider nor understands raw media.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "config/creation-routes.v1.json"
SCHEMA_PATH = ROOT / "schemas/creation-route-context.v1.schema.json"
WRITING_STEPS = {
    "draft-one-observation", "build-evidence-draft", "project-case-script",
    "draft-prerecord-case", "draft-interview-guide",
}


class CreationRouteError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def load(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise CreationRouteError("creation_route_invalid", "Expected a JSON object")
    return value


def digest(value: object) -> str:
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def resolve(context: dict) -> dict:
    schema = load(SCHEMA_PATH)
    Draft202012Validator(schema).validate(context)
    policy = load(POLICY_PATH)
    intent = context["primary_intent"]
    request = context["requested_route"]
    style_map = policy["intent_to_vlog_style"]
    supported = context["causal_change"]["status"] == "supported"
    route = None
    style = None
    status = "ready"
    issues = []
    if context["task_kind"] == "technical-rework":
        route = "technical-rework"
        reason = "本次仅是技术修改；不重设创作形式。"
    elif request != "auto":
        route = request
        reason = "依照本次明确选定的主路由。"
    elif intent in style_map:
        route = "travel-experience"
        reason = "首要目标是体验、信息或感官呈现，采用对应 Vlog 形态。"
    elif intent == "causal-change":
        route = "story"
        reason = "首要表达对象是有证据支持的真实因果变化。"
    elif intent == "explain-or-answer":
        route = "expository"
        reason = "首要任务是解释或回答问题，采用现有说明路线。"
    elif context["requested_vlog_style"] != "auto":
        route = "travel-experience"
        reason = "本次明确指定了 Vlog 成片形态。"
    else:
        status = "needs-context"
        reason = "当前观看任务未明确；题材或已有故事模板不足以决定路由。"
        issues.append("AI 需从现有指令和素材中补出主要观看任务；仅缺少关键偏好时再询问用户。")

    if route == "story":
        if context["avoid_forced_story"]:
            status = "needs-context"
            issues.append("本次避免强套故事的要求与故事路由选择冲突，需重新评估。")
        if not supported:
            status = "needs-evidence" if status == "ready" else status
            issues.append("故事路线缺少真实因果变化的证据；不得补造冲突、结局、心理或对白。")
        if context["requested_vlog_style"] != "auto":
            status = "needs-context"
            issues.append("当前主路由与指定 Vlog 形态不一致；先选择主路线，再决定局部组合。")
    if route == "travel-experience":
        style = context["requested_vlog_style"]
        if style == "auto":
            style = style_map.get(intent)
        if style is None:
            status = "needs-context"
            issues.append("需根据观看任务选择 Vlog 形态，不自动改成讲故事。")
        if context["material_state"] == "unknown":
            status = "needs-context"
            issues.append("需区分已拍素材、拍前计划或混合素材。")
    if route == "expository" and context["requested_vlog_style"] != "auto":
        status = "needs-context"
        issues.append("说明主路由与指定 Vlog 形态不一致，需重新评估。")

    alternatives = []
    for candidate in ("story", "travel-experience", "expository"):
        if candidate == route:
            continue
        if candidate == "story":
            explanation = "仅真实因果变化成为主表达任务且有证据时进入；刺激、同日行程或标题不能单独触发。"
        elif candidate == "travel-experience":
            explanation = "适用于随行、活动精彩片段、攻略、体验评述、氛围或观察；不要求戏剧弧线。"
        else:
            explanation = "适用于以解释、回答或工具信息为首要任务的内容。"
        alternatives.append({"route": candidate, "reason": explanation})
    decision = {
        "schema_version": "creation-route-decision.v1",
        "task_id": context["task_id"], "revision_id": context["revision_id"],
        "status": status, "primary_route": route, "vlog_style": style,
        "reason": reason, "assessment_reason": context["assessment_reason"],
        "alternatives": alternatives, "issues": issues,
        "story_design_applicability": "required" if route == "story" else "not-applicable",
        "shared_material_analysis": policy["shared_material_analysis"],
        "quality_focus": policy["routes"][route]["quality_focus"] if route else [],
        "guide": policy["routes"][route]["guide"] if route else "docs/creation-route-selection.md",
        "context": copy.deepcopy(context), "context_sha256": digest(context),
        "policy_sha256": digest(policy),
        "semantic_review": "agent-assessment-not-media-or-fact-verification",
        "publication_authority": False,
    }
    decision["payload_sha256"] = digest(decision)
    return decision


def check(decision: dict, current_context: dict | None = None, task_id: str | None = None) -> dict:
    context = decision.get("context")
    if not isinstance(context, dict):
        raise CreationRouteError("creation_route_invalid", "Decision has no assessed context")
    if decision != resolve(context):
        raise CreationRouteError("creation_route_drift", "Decision or routing policy changed; resolve current context again")
    if current_context is not None and digest(current_context) != decision["context_sha256"]:
        raise CreationRouteError("creation_route_context_drift", "Goal, material, style or user correction changed; reassess")
    if task_id is not None and task_id != decision["task_id"]:
        raise CreationRouteError("creation_route_task_mismatch", "Decision belongs to another task")
    if decision["status"] != "ready":
        raise CreationRouteError("creation_route_not_ready", "; ".join(decision["issues"]))
    return decision


def check_manifest(manifest_path: Path, task_id: str, step: dict, *, require_selection: bool = False) -> dict | None:
    if step["step_id"] not in WRITING_STEPS and not require_selection:
        return None
    manifest = load(manifest_path)
    items = manifest["artifacts"]
    decisions = [a for a in items if a.get("source_role") == "creation-route-decision"]
    contexts = [a for a in items if a.get("source_role") == "creation-route-context"]
    if len(decisions) != 1 or len(contexts) != 1:
        raise CreationRouteError("creation_route_required", "Writing needs one route decision and one current route context")
    values = []
    for artifact in (decisions[0], contexts[0]):
        target = (manifest_path.parent / artifact["path"]).resolve()
        if not target.is_relative_to(manifest_path.parent.resolve()) or not target.is_file():
            raise CreationRouteError("creation_route_path_invalid", artifact["path"])
        expected = artifact.get("expected_sha256")
        if not expected or hashlib.sha256(target.read_bytes()).hexdigest() != expected:
            raise CreationRouteError("creation_route_artifact_drift", artifact["path"])
        values.append(load(target))
    decision = check(values[0], values[1], task_id)
    if decision["primary_route"] == "technical-rework":
        raise CreationRouteError("creation_route_incompatible", "Technical rework cannot authorize a new writing step")
    if decision["primary_route"] == "travel-experience":
        raise CreationRouteError("creation_route_wrong_workflow", "Use the independent Vlog workflow, not a case/graphic/short-post recipe")
    return decision


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("catalog")
    build = sub.add_parser("resolve")
    build.add_argument("--input", type=Path, required=True)
    build.add_argument("--output", type=Path)
    verify = sub.add_parser("check")
    verify.add_argument("--decision", type=Path, required=True)
    verify.add_argument("--current-context", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.action == "catalog":
            result = load(POLICY_PATH)
        elif args.action == "resolve":
            result = resolve(load(args.input))
        else:
            value = check(load(args.decision), load(args.current_context))
            result = {"ok": True, "primary_route": value["primary_route"], "vlog_style": value["vlog_style"]}
        text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        if getattr(args, "output", None):
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(text, encoding="utf-8")
        else:
            print(text, end="")
        return 0 if result.get("status", "ready") == "ready" else 2
    except (ValueError, OSError, ValidationError) as error:
        print(json.dumps({"ok": False, "error_code": getattr(error, "code", "creation_route_invalid"), "message": str(error)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
