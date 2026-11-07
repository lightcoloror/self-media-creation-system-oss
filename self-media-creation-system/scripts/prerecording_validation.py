"""Thin draft-phase adapter. Never requires or opens recorded media."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


STUDIO = Path(__file__).resolve().parents[2] / "content-studio-poc"
SELF_MEDIA = Path(__file__).resolve().parents[1]


def _module(name):
    path = STUDIO / "scripts" / (name + ".py")
    spec = importlib.util.spec_from_file_location("prerecord_" + name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    sys.path.insert(0, str(STUDIO / "scripts"))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(STUDIO / "scripts"))
    return module


def validate_outputs(api, handoff_path, receipt_path, handoff, receipt):
    """Validate declared results, not the Agent's mental process or human identity."""
    case = _module("case_video_script_adapter")
    fail = api.AgentEntryError
    manifest_path = handoff_path.parent / handoff["context"]["manifest"]["path"]
    manifest = api.load_json(manifest_path)
    inputs = {row["source_role"]: (manifest_path.parent / row["path"]).resolve()
              for row in manifest["artifacts"]}
    outputs = {}
    for ref in receipt["outputs"]:
        path = receipt_path.parent / ref["path"]
        value = api.load_json(path)
        version = value.get("schema_version")
        if version in outputs:
            raise fail("duplicate_output_contract", str(version))
        outputs[version] = (path, value)
    expected = set(handoff["step"]["output_contract"].split("+"))
    if set(outputs) != expected:
        raise fail("output_contract_mismatch", "expected exact prerecording artifacts")
    for version, (_, value) in outputs.items():
        schema_root = SELF_MEDIA if version in {"short-video-timing-evidence.v1", "author-writing-revision.v1"} else STUDIO
        api.validate_document(value, schema_root / "schemas" / (version + ".schema.json"), "prerecord_output")
    capsule = api.load_json(handoff_path.parent / handoff["capsule"]["path"])
    synthetic = capsule["provenance"]["synthetic_only"]
    fact = api.load_json(inputs["fact_card_ref"])
    if fact.get("synthetic_only") != synthetic or any(value.get("synthetic_only") != synthetic for _, value in outputs.values()):
        raise fail("data_classification_drift", "request, fact card and outputs must agree")
    fact_ref = {"artifact_id": fact["fact_card_id"], "schema_version": fact["schema_version"],
                "sha256": case.research_adapter.sha256_value(fact)}
    # Later steps must actually consume the previous step's output, not an unrelated
    # artifact accompanied by a valid but irrelevant receipt.
    previous = handoff.get("previous_receipt")
    if previous:
        previous_path = handoff_path.parent / previous["path"]
        prior = api.load_json(previous_path)
        prior_outputs = {(previous_path.parent / row["path"]).resolve(): row["sha256"] for row in prior["outputs"]}
        required_role = {"review-prerecord-draft": "case-video-script", "complete-prerecord-voice": "initial-draft-review",
                         "verify-prerecord-timing": "case-video-script", "review-interview-guide": "interview-guide"}[handoff["step"]["step_id"]]
        consumed = inputs[required_role]
        if consumed not in prior_outputs or api.sha256_file(consumed) != prior_outputs[consumed]:
            raise fail("predecessor_output_not_consumed", required_role)
    step = handoff["step"]["step_id"]
    decision = api._validate_creation_context(manifest_path, capsule, handoff["step"])
    route = "story-arc" if decision and decision["primary_route"] == "story" else "direct-answer"
    story_path = inputs.get("story-design-card")
    gate = _module("initial_draft_quality_gate")
    try:
        if step == "draft-prerecord-case":
            script = outputs["case-video-script.v1"][1]
            if script.get("pre_voice") is not True:
                raise fail("draft_cannot_self_approve", "first draft must await voice review")
            if script["inputs"]["fact_card_ref"] != fact_ref:
                raise fail("fact_revision_drift", "draft references a different fact revision")
            case._validate_canonical_fact_card(fact)
            case._validate_sensitive_and_risky_language(script, fact)
            if route == "story-arc":
                if script.get("structure_route") != route:
                    raise fail("story_route_mismatch", "story draft must retain the selected story route")
                gate.load_story_card(script, story_path, owner_root=SELF_MEDIA)
            elif script.get("structure_route", route) != route:
                raise fail("story_route_mismatch", "draft route differs from the current selection")
            segments = {row["segment_id"]: row for row in script["segments"]}
            advances = script["editorial_plan"]["section_advances"]
            if len(segments) != len(script["segments"]) or len(advances) != len(segments) or {r["segment_id"] for r in advances} != set(segments):
                raise fail("editorial_coverage_missing", "every segment needs one anchored information advance")
            if len({r["new_information"].strip() for r in advances}) != len(advances):
                raise fail("editorial_progression_repeated", "a repeated summary is not progression")
            for row in advances:
                if row["spoken_span"] not in segments[row["segment_id"]]["spoken_text"]:
                    raise fail("editorial_span_unbound", row["segment_id"])
            known = {r["fact_id"] for r in fact.get("facts", [])}
            for row in segments.values():
                if not synthetic and row["role"] != "cta" and not row.get("fact_refs"):
                    raise fail("segment_fact_refs_missing", row["segment_id"])
                if set(row.get("fact_refs", [])) - known:
                    raise fail("segment_fact_ref_unknown", row["segment_id"])
        elif step == "review-prerecord-draft":
            validate_cta_input(inputs)
            review = outputs["case-video-initial-draft-review.v1"]
            gate.validate_initial_draft_review(
                script_path=inputs["case-video-script"], review_path=review[0], require_approved=True,
                structure_route=route, story_card_path=story_path, story_owner_root=SELF_MEDIA)
            if review[1]["input_fact_card_ref"] != fact_ref:
                raise fail("fact_revision_drift", "review does not bind the current fact card")
        elif step == "complete-prerecord-voice":
            script = outputs["case-video-script.v1"][1]
            voice = outputs["case-video-human-voice-receipt.v1"][1]
            initial = api.load_json(inputs["initial-draft-review"])
            base = api.load_json(inputs["case-video-script"])
            request = api.load_json(inputs["human-voice-request"])
            api.validate_document(request, STUDIO / "schemas/case-video-human-voice-request.v1.schema.json", "human_voice_request")
            semantic = request.get("semantic_review")
            if not semantic:
                raise fail("editorial_evidence_required", "new prerecording completion needs anchored semantic review, not only lexical checks")
            voice_basis = api.load_json(inputs["voice_profile_ref"])
            expected_basis = {"artifact_id": voice_basis.get("artifact_id"), "schema_version": voice_basis.get("schema_version"),
                              "sha256": case.research_adapter.sha256_value(voice_basis)}
            if semantic["voice_basis"] != expected_basis:
                raise fail("voice_basis_drift", "semantic review must bind the actual author voice profile")
            _module("human_voice_gate").validate_editorial_evidence(base, script, request)
            if voice.get("semantic_review_sha256") != case.research_adapter.sha256_value(semantic):
                raise fail("editorial_evidence_drift", "voice receipt must bind current semantic review")
            gate.validate_initial_draft_review(
                script_path=inputs["case-video-script"], review_path=inputs["initial-draft-review"], require_approved=True,
                structure_route=route, story_card_path=story_path, story_owner_root=SELF_MEDIA)
            if script.get("pre_voice") or script["inputs"]["fact_card_ref"] != fact_ref:
                raise fail("recording_candidate_incomplete", "voice or fact revision missing")
            if voice["input_body_sha256"] != case.research_adapter.sha256_value(case.stable_body_payload(base)):
                raise fail("voice_input_revision_drift", "voice receipt uses a different draft")
            if voice["initial_draft_review_ref"]["sha256"] != case.research_adapter.sha256_value(initial):
                raise fail("initial_review_revision_drift", "voice receipt uses another editorial review")
            case._validate_human_voice_receipt(voice, script)
            case._validate_sensitive_and_risky_language(script, fact)
            if route == "story-arc":
                card = gate.load_story_card(script, story_path, owner_root=SELF_MEDIA)
                findings = gate.narrative_realization.validate(
                    script, semantic.get("story_realization"), card, gate._body_sha256(script))
                if findings:
                    raise fail("story_realization_unresolved", ", ".join(findings))
        elif step == "verify-prerecord-timing":
            validate_cta_input(inputs)
            timing_path, timing_receipt = outputs["short-video-timing-evidence.v1"]
            spec = importlib.util.spec_from_file_location(
                "prerecord_short_video_timing_evidence", SELF_MEDIA / "scripts" / "short_video_timing_evidence.py"
            )
            timing = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(timing)
            timing.validate_receipt_value(timing_receipt)
            if timing_receipt["stage"] != "prerecording-script" or timing_receipt["media_binding"] is not None:
                raise fail("stage_evidence_mismatch", "prerecord step cannot accept final-cut timing evidence")
            if timing_receipt["script_binding"]["sha256"] != api.sha256_file(inputs["case-video-script"]):
                raise fail("script_timing_revision_drift", "timing evidence uses another script revision")
            timing_input = inputs["timing-input"]
            current_timing = api.load_json(timing_input)
            if current_timing["structure_route"] != route:
                raise fail("story_route_mismatch", "timing evidence route differs from the current selection")
            if route == "story-arc":
                gate.load_story_card(api.load_json(inputs["case-video-script"]), story_path, owner_root=SELF_MEDIA)
                if timing_receipt["story_design_binding"]["sha256"] != api.sha256_file(story_path):
                    raise fail("story_realization_card_drift", "timing uses a different story card")
            if timing_receipt["input_binding"]["sha256"] != api.sha256_file(timing_input):
                raise fail("timing_input_revision_drift", "timing evidence uses another observation input")
        elif step == "draft-interview-guide":
            guide = outputs["case-interview-guide.v1"][1]
            _validate_guide(api, guide, fact, fact_ref)
        elif step == "review-interview-guide":
            guide = api.load_json(inputs["interview-guide"])
            api.validate_document(guide, STUDIO / "schemas/case-interview-guide.v1.schema.json", "interview_guide")
            _validate_guide(api, guide, fact, fact_ref)
            review = outputs["case-interview-guide-review.v1"][1]
            if review["guide_id"] != guide["guide_id"] or review["guide_sha256"] != case.research_adapter.sha256_value(guide):
                raise fail("guide_review_drift", "questions changed after review")
            expected_actor = "synthetic-fixture-author" if synthetic else "author"
            if review["reviewer"] != expected_actor:
                raise fail("guide_reviewer_mismatch", "synthetic review cannot approve real questions")
            if review["decision"] != "approved_questions_only" or any(r["status"] != "clear" for r in review["checks"]):
                raise fail("guide_review_pending", "draft remains editable; no approved-question handoff")
            if {r["check_id"] for r in review["checks"]} != {"non_leading_questions", "privacy", "fact_premises", "spoken_clarity"}:
                raise fail("guide_review_incomplete", "missing question review check")
            questions = {r["question_id"]: r for r in guide["questions"]}
            for row in review["checks"]:
                if row["question_id"] not in questions or row["question_span"] not in questions[row["question_id"]]["question"]:
                    raise fail("guide_review_unbound", row["question_id"])
    except fail:
        raise
    except (ValueError, KeyError, RuntimeError) as error:
        raise fail(getattr(error, "code", "prerecord_gate_failed"), str(error)) from error


def validate_cta_input(inputs):
    """A non-conversion cta_product gate does not decide interaction CTA."""
    import cta_review
    import cover_workbench
    if 'cta-plan' not in inputs:
        raise ValueError('cta_plan_required_for_script_review')
    return cta_review.checked_plan(cover_workbench.reference(inputs['cta-plan']),
        script_ref=cover_workbench.reference(inputs['case-video-script']))


def _validate_guide(api, guide, fact, fact_ref):
    if guide["fact_card_ref"] != fact_ref:
        raise api.AgentEntryError("fact_revision_drift", "question premises use another fact card")
    facts = {r["fact_id"]: r for r in fact.get("facts", [])}
    ids = [r["question_id"] for r in guide["questions"]]
    if len(set(ids)) != len(ids):
        raise api.AgentEntryError("duplicate_question", "question IDs must be unique")
    for question in guide["questions"]:
        for ref in question["premise_fact_ids"]:
            if ref not in facts or (not guide["synthetic_only"] and facts[ref].get("status") != "confirmed"):
                raise api.AgentEntryError("unconfirmed_question_premise", ref)
