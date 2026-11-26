"""Validate the editorial applicability decision for a video's current script."""
import math
import re
from pathlib import Path

from rough_cut_checks import bound, load, ref, spoken_body

SCHEMA = "self-media.video-overlay-selection.v1"
MEDICAL_TEXT = "医学科普｜内容仅供参考，不替代个体诊疗建议。"
IDENTITY_ROLES = {"identity", "institution", "license_number"}
AI_STAGES = {"script", "editing", "illustration", "video", "voice", "music", "other"}
MEDICAL_CATEGORIES = {"clinical_explanation", "clinical_guidance", "cost_or_coverage_context", "no_medical_subject"}
INSURANCE_CATEGORIES = {"insurance_discussion", "no_insurance_subject"}


def _reason(value):
    if not isinstance(value, str) or len(value.strip()) < 3:
        raise ValueError("overlay_assessment_reason_required")
    return value.strip()


def assess(plan, script_ref):
    if not isinstance(plan, dict) or plan.get("schema") != SCHEMA:
        raise ValueError("video_overlay_assessment_required")
    if plan.get("script_ref") != script_ref or not script_ref:
        raise ValueError("video_overlay_assessment_stale_script")
    body = spoken_body(bound(script_ref))
    choices = {}
    for kind, allowed in (("medical", MEDICAL_CATEGORIES), ("insurance", INSURANCE_CATEGORIES)):
        source = plan.get(kind)
        if not isinstance(source, dict):
            raise ValueError("video_overlay_content_category_required: " + kind)
        category = source.get("category")
        if category not in allowed:
            raise ValueError("video_overlay_content_category_required: " + kind)
        evidence = source.get("evidence_quotes")
        if (not isinstance(evidence, list) or not evidence or any(
                not isinstance(quote, str) or len(quote.strip()) < 5 or quote not in body for quote in evidence)):
            raise ValueError("video_overlay_requires_current_body_quotes: " + kind)
        required = category in {"clinical_explanation", "clinical_guidance", "insurance_discussion"}
        choices[kind] = {"decision": "required" if required else "not_applicable", "reason": _reason(source.get("reason"))}
        if kind == "medical":
            choices[kind]["text"] = MEDICAL_TEXT if required else ""
            if "windows" in source:
                if not required:
                    raise ValueError("medical_windows_require_applicable_content")
                windows = source["windows"]
                if not isinstance(windows, list) or not windows:
                    raise ValueError("medical_windows_required")
                end = -1
                for window in windows:
                    if (not isinstance(window, dict) or window.get("quote") not in evidence
                            or not all(type(window.get(k)) in (int, float) and math.isfinite(window[k])
                                       for k in ("start_seconds", "end_seconds"))
                            or not 0 <= window["start_seconds"] < window["end_seconds"]
                            or window["start_seconds"] <= end):
                        raise ValueError("medical_windows_must_be_ordered_and_anchored_to_script")
                    end = window["end_seconds"]
                rect = source.get("rect")
                if (not isinstance(rect, dict) or set(rect) != {"x", "y", "width", "height"}
                        or any(type(v) not in (int, float) or not math.isfinite(v) for v in rect.values())
                        or not all(0 <= rect[k] < 1 for k in ("x", "y"))
                        or not 0 < rect["width"] <= 1 - rect["x"]
                        or not 0 < rect["height"] <= 1 - rect["y"]):
                    raise ValueError("medical_windows_require_locked_layout_rect")
                choices[kind].update(windows=windows, rect=rect)
    ai = plan.get("ai")
    if not isinstance(ai, dict):
        raise ValueError("video_overlay_ai_production_basis_required")
    mode, stages = ai.get("mode"), ai.get("stages")
    if (mode not in {"ai_assisted", "ai_generated", "no_ai"} or not isinstance(stages, list)
            or any(not isinstance(stage, str) or stage not in AI_STAGES for stage in stages)
            or len(set(stages)) != len(stages) or bool(stages) != (mode != "no_ai")):
        raise ValueError("video_overlay_ai_production_basis_required")
    choices["ai"] = {"mode": mode, "stages": stages, "reason": _reason(ai.get("reason"))}
    return choices


def for_manifest(manifest):
    pointer = manifest.get("overlay_assessment_ref")
    if not pointer:
        raise ValueError("video_overlay_assessment_required")
    choices = assess(load(bound(pointer)), manifest.get("script_ref"))
    saved_medical = manifest.get("medical_overlay")
    if saved_medical is not None and (not isinstance(saved_medical, dict) or
            {key: value for key, value in saved_medical.items() if key != "script_ref"} != choices["medical"]):
        raise ValueError("medical_disclosure_selection_or_text_drift")
    identity = manifest.get("identity_overlay")
    if not isinstance(identity, dict) or identity.get("decision") != choices["insurance"]["decision"]:
        raise ValueError("video_overlay_insurance_decision_drift")
    return choices


def _medical_badge(text, *, overlay_style=False):
    # Overlay/badge styles treat any '医学科普' mention as a medical badge event (catches '医学科普（仅供参考）').
    # Dialogue styles only flag structured disclaimer badges (requiring separator after '医学科普' or full disclaimer phrase)
    # so spoken lines like '这是一条医学科普视频' or ending in '医学科普' are never false-flagged.
    if overlay_style:
        return bool(re.search(r"医学科普|不替代个体诊疗建议", text))
    return bool(re.search(r"医学科普\s*[｜|:：（(]|不替代个体诊疗建议", text))


def check_ass(choices, path, *, dialogue_styles=None, external_caption_only=False):
    labels = []
    medical_rows = []
    lines = Path(path).read_text(encoding="utf-8-sig").splitlines()
    # Parse [Events] Format dynamically (matching video_caption_quality.burned_cues); fall back to standard 10-field ASS.
    fields = ["layer", "start", "end", "style", "name", "marginl", "marginr", "marginv", "effect", "text"]
    in_events = False
    for line in lines:
        if line.startswith("["):
            in_events = line.strip().casefold() == "[events]"
        elif in_events and line.startswith("Format:"):
            parsed = [k.strip().lower() for k in line.split(":", 1)[1].split(",")]
            if parsed and parsed[-1] == "text" and {"start", "end", "style"} <= set(parsed):
                fields = parsed
            break
    ignored_styles = {"dialogue", "subtitle", "subtitles", "default"} | {s.casefold() for s in (dialogue_styles or ())}
    for line in lines:
        if line.startswith("Dialogue:"):
            parts = line.split(":", 1)[1].split(",", len(fields) - 1)
            if len(parts) == len(fields):
                event = dict(zip(fields, parts))
                text = re.sub(r"\{[^}]*\}", "", event["text"]).replace(r"\N", "")
                style = event["style"].strip().casefold()
                is_overlay = style not in ignored_styles
                if _medical_badge(text, overlay_style=is_overlay):
                    if choices["medical"]["decision"] == "required" and MEDICAL_TEXT not in text:
                        raise ValueError("video_overlay_medical_text_mismatch")
                    from video_caption_quality import _clock
                    medical_rows.append(dict(start_seconds=_clock(event["start"]), end_seconds=_clock(event["end"])))
                # A complete badge copied into a generic style must still be caught.
                if is_overlay or _medical_badge(text, overlay_style=False):
                    labels.append(text)
    combined = "".join(labels)
    contains = {"medical": bool(medical_rows),
                "insurance": bool(re.search(r"执业(?:证)?编号[：:]", combined)),
                "ai": bool(re.search(r"(?i)(?<![a-z])ai(?![a-z])|人工智能", combined))}
    required = {"medical": choices["medical"]["decision"] == "required",
                "insurance": choices["insurance"]["decision"] == "required",
                "ai": choices["ai"]["mode"] != "no_ai"}
    for kind, enabled in required.items():
        if external_caption_only:
            # External caption ASS may leave required overlays to separate verified layout layers,
            # but MUST still block inapplicable overlays present inside the ASS.
            if contains[kind] and not enabled:
                raise ValueError("video_overlay_ass_applicability_mismatch: " + kind)
        elif contains[kind] != enabled:
            raise ValueError("video_overlay_ass_applicability_mismatch: " + kind)
    if required["medical"] and (not external_caption_only or medical_rows) and MEDICAL_TEXT not in combined:
        raise ValueError("video_overlay_medical_text_mismatch")
    if "windows" in choices["medical"] and (not external_caption_only or medical_rows):
        verify_windows(choices["medical"]["windows"], medical_rows, tolerance=.0051)
    return {"ass_ref": ref(path), "layers": required}


def check_layout(choices, layout):
    medical = choices["medical"]
    declaration = {key: medical[key] for key in ("decision", "reason", "text")}
    if "medical_disclosure" in layout and layout["medical_disclosure"] != declaration:
        raise ValueError("medical_disclosure_selection_or_text_drift")
    if layout.get("ai_disclosure") != choices["ai"]:
        raise ValueError("video_overlay_layout_ai_decision_drift")
    elements = layout.get("elements", [])
    identity = {row["role"] for row in elements if row["role"] in IDENTITY_ROLES}
    if choices["insurance"]["decision"] == "not_applicable" and identity:
        raise ValueError("video_overlay_layout_inapplicable_insurance")
    candidates = [row for row in elements if row["role"] == "disclaimer" and _medical_badge(row.get("text", ""))]
    if medical["decision"] == "not_applicable":
        if candidates:
            raise ValueError("video_overlay_layout_inapplicable_medical")
        return {"required": False, **medical}
    if "windows" in medical:
        verify_windows(medical["windows"], candidates, duration=layout["duration_seconds"])
        if any(row["text"] != medical["text"] or row["rect"] != medical["rect"] for row in candidates):
            raise ValueError("medical_badge_text_or_locked_position_drift")
        return {"required": True, **medical, "full_duration_covered": False}
    cursor = 0.0
    for row in sorted(candidates, key=lambda row: row["start_seconds"]):
        if row["text"] != medical["text"] or row["start_seconds"] > cursor + 1e-6:
            raise ValueError("video_overlay_medical_text_or_coverage_missing")
        cursor = max(cursor, row["end_seconds"])
    if cursor < layout["duration_seconds"] - 1e-6:
        raise ValueError("video_overlay_medical_text_or_coverage_missing")
    return {"required": True, **medical}


def verify_windows(windows, rows, *, duration=None, tolerance=1e-6):
    actual = []
    for row in sorted(rows, key=lambda row: row["start_seconds"]):
        start, stop = row["start_seconds"], row["end_seconds"]
        if not 0 <= start < stop or (duration is not None and stop > duration + tolerance):
            raise ValueError("medical_badge_time_outside_final_timeline")
        if actual and start <= actual[-1][1] + tolerance:
            actual[-1][1] = max(actual[-1][1], stop)
        else:
            actual.append([start, stop])
    expected = [[row["start_seconds"], row["end_seconds"]] for row in windows]
    if len(actual) != len(expected) or any(abs(a - b) > tolerance
            for pair_a, pair_b in zip(actual, expected) for a, b in zip(pair_a, pair_b)):
        raise ValueError("medical_badge_coverage_differs_from_locked_windows")


def geometry_layout(choices, layout):
    medical = check_layout(choices, layout)
    if "windows" not in medical:
        return layout, medical
    # The dependency applies full-duration coverage. Use the already validated
    # interval policy while retaining its geometry, collision and AI checks.
    geometry = dict(layout, medical_disclosure=dict(decision="not_applicable", text="",
                    reason="Temporally scoped coverage verified against the overlay assessment."))
    return geometry, medical


def validate_final_layout(choices, layout, root):
    from video_creation_pipeline.final_layout_safety import validate_final_layout as check_geometry

    geometry, medical = geometry_layout(choices, layout)
    report = check_geometry(geometry, root)
    if "windows" in medical:
        report["medical_disclosure"] = medical
    return report
