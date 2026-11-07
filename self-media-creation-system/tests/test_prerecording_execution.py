"""Synthetic draft preparation and fail-closed progression, without recorded media."""
from __future__ import annotations
import copy
import importlib.util
import json
import os
import shutil
import sys
import unittest
import uuid
from pathlib import Path
import editorial_fixture

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import self_media_agent as agent
import prerecording_validation as prep

FIX = prep.STUDIO / "fixtures/case-video-script-v1"


class PrerecordingExecutionTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(os.environ.get("TEST_TMP_ROOT", str(ROOT / "outputs/test-temp"))) / ("prerecord-" + uuid.uuid4().hex)
        self.root.mkdir(parents=True)
        self.fact = self.load("synthetic-fact-card.json")
        self.fact_path = self.write("fact.json", self.fact)
        self.stub = self.write("context.json", {"synthetic_only": True, "status": "unknown", "note": "合成场景，尚未录制，无客户回答。"})
        self.voice = prep._module("human_voice_gate")
        self.voice_basis = {"artifact_id": "synthetic-voice-profile", "schema_version": "voice-profile.v1", "synthetic_only": True,
                            "note": "合成语料：先说发生了什么，再讲具体做法，不替客户作决定。"}
        self.voice_path = self.write("voice-profile.json", self.voice_basis)
        self.authoring = agent._load_author_writing_context()
        self.author_store = self.root / "isolated-author-test.sqlite3"
        self.author_counter = 0
        self.author_last_text = ""
        self.author_envelopes = {}
        timing_spec = importlib.util.spec_from_file_location(
            "prerecord_test_timing", ROOT / "scripts" / "short_video_timing_evidence.py"
        )
        self.timing = importlib.util.module_from_spec(timing_spec)
        timing_spec.loader.exec_module(self.timing)

    def tearDown(self):
        shutil.rmtree(self.root)

    def load(self, name):
        return agent.load_json(FIX / name)

    def write(self, name, value):
        path = self.root / name
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return path

    def resolve(self, kind="spoken_script"):
        req = {"schema_version": "self-media-agent-request.v1", "request_id": "synthetic-prerecord-001",
               "workflow_goal": "case_video_candidate", "creation_phase": "prerecording", "preparation_kind": kind,
               "author_identity": {"account_id": "synthetic-author-account", "genre": kind},
               "synthetic_only": True, "available_inputs": ["account_ip", "primary_audience", "topic_question", "fact_card_ref", "authorization_status", "voice_profile_ref"], "input_refs": []}
        self.capsule = agent.resolve_request(req)
        self.capsule_path = self.write("capsule.json", self.capsule)
        context = self.authoring.prepare_context(self.author_store, {
            "content_id": "synthetic-prerecord-" + kind,
            "account_id": "synthetic-author-account", "genre": kind,
            "synthetic_only": True, "privacy_status": "non_sensitive",
            "source_ref": "synthetic-test:explicitly-no-author-judgment", "judgments": [],
        }, self.capsule["request_id"])
        self.author_context = self.write("author-context-" + kind + ".json", context)
        editorial_fixture.preparation(self.author_context)
        return req

    def author_revision(self, draft_path, reviewed=False):
        key = (str(draft_path), agent.sha256_file(draft_path))
        envelope = self.author_envelopes.get(key)
        if envelope is None:
            self.author_counter += 1
            value = self.authoring.revision_envelope(self.author_store, self.author_context, draft_path, {
                "before": self.author_last_text,
                "reasons": [{"actor": "synthetic_fixture", "source_ref": "synthetic-test:revision",
                             "text": "Synthetic test draft revision; no real author approval or samples."}],
                "source_ref": "synthetic-test:revision", "privacy_status": "non_sensitive",
            })
            envelope = self.write(f"author-revision-{self.author_counter}.json", value)
            editorial_fixture.review(envelope)
            self.author_last_text = self.authoring.draft_text(draft_path)
            self.author_envelopes[key] = envelope
        if reviewed and agent.load_json(envelope).get("review_ref") is None:
            self.author_counter += 1
            value = self.authoring.attach_review(self.author_store, envelope, {
                "actor": "synthetic_fixture", "source_ref": "synthetic-test:explicit-review",
                "decisions": [],
            })
            envelope = self.write(f"author-reviewed-{self.author_counter}.json", value)
            self.author_envelopes[key] = envelope
        return envelope

    def handoff(self, index, supplied=None, previous=None, inspect=False):
        step = self.capsule["step_index"][index]
        inputs = {role: self.stub for role in step["input_roles"]}
        creation = agent._load_creation_route()
        if self.capsule.get("creation_phase") == "prerecording":
            context = creation.load(ROOT / "fixtures/creation-route-v1/same-day-activity-highlights.context.json")
            context.update({"task_id": self.capsule["request_id"], "topic_domain": "case",
                "primary_intent": "explain-or-answer", "material_state": "planned",
                "material_summary": "Synthetic prerecord explanation/interview test; no recorded result.",
                "assessment_reason": "Prepare evidence-bound explanatory prose or open interview questions.",
                "source_refs": ["synthetic-prerecord-fixture"]})
            inputs["creation-route-context"] = self.write("creation-route-context.json", context)
            inputs["creation-route-decision"] = self.write("creation-route-decision.json", creation.resolve(context))
        if "fact_card_ref" in inputs:
            inputs["fact_card_ref"] = self.fact_path
        if "voice_profile_ref" in inputs:
            inputs["voice_profile_ref"] = self.voice_path
        inputs["author-writing-context"] = self.author_context
        inputs.update(supplied or {})
        if 'cta-plan' in inputs and 'cta-plan' not in (supplied or {}):
            import cta_review, cover_workbench
            plan=cta_review.empty_plan('synthetic-prerecord-cta', cover_workbench.reference(inputs['case-video-script']))
            for choice in plan['decisions'].values():
                choice.update(decision='not_used', reason='Synthetic scenario has no independently requested CTA of this type.')
            rows=agent.load_json(inputs['case-video-script']).get('segments',[])
            ctas=[r for r in rows if r.get('role')=='cta']
            if ctas:
                plan['decisions']['acquisition'].update(decision='use', reason='Record the existing synthetic service invitation explicitly.',
                    service_boundary='Synthetic review only; no promised insurance outcome or free service.',
                    placements=[dict(id=r['segment_id'],location='video_spoken',text=r['spoken_text'],reason='Retain the existing final service boundary.') for r in ctas])
            inputs['cta-plan']=self.write('cta-plan-'+str(index)+'.json',plan)
        if "author-revision-review" in inputs and "author-revision-review" not in (supplied or {}):
            if "interview-guide" in inputs:
                inputs["author-revision-review"] = self.author_revision(inputs["interview-guide"], reviewed=True)
        manifest = {"schema_version": "self-media-context-input.v1", "task_id": self.capsule["request_id"],
                    "stage": step["context_stage"], "budget": {"max_inline_bytes": 12000}, "artifacts": [
                        {"artifact_id": "input-" + str(i), "role": "source_manifest", "source_role": role,
                         "path": path.name, "load_mode": "reference", "expected_sha256": agent.sha256_file(path)}
                        for i, (role, path) in enumerate(inputs.items())]}
        editorial_fixture.bind_stage_purpose(manifest, self.root,
            agent.load_json(self.author_context)["author_brief"]["content_id"],
            "Carry the invented prerecording explanation through synthetic step " + step["step_id"] + ".",
            inputs.get("case-video-script", inputs.get("interview-guide")))
        mpath = self.write(f"manifest-{index}.json", manifest)
        hpath = self.root / f"handoff-{index}.json"
        agent.prepare_step_handoff(self.capsule_path, step["step_id"], mpath,
                                   self.root / f"context-{index}.json", hpath, previous, inspect)
        return hpath

    def receipt(self, handoff, paths, status=None):
        h = agent.load_json(handoff)
        paths = list(paths)
        if h["step"]["step_id"] in self.authoring.WRITING_STEPS and status != "blocked":
            for path in paths[:]:
                try:
                    schema = agent.load_json(path).get("schema_version")
                except (agent.AgentEntryError, ValueError):
                    continue
                if schema in {"case-video-script.v1", "case-interview-guide.v1"}:
                    paths.append(self.author_revision(path))
                    break
        if paths and status != "blocked":
            stage_review = editorial_fixture.stage_purpose_review(handoff, paths[0])
            if stage_review is not None:
                paths.append(stage_review)
        value = {"schema_version": "self-media-step-output-receipt.v1",
                 "status": status or ("human_gate_recorded" if h["step"]["interface"] == "human_gate" else "candidate_ready"),
                 "handoff": {"path": handoff.name, "sha256": agent.sha256_file(handoff)},
                 "step_id": h["step"]["step_id"], "tool_id": h["step"]["tool_id"], "output_contract": h["step"]["output_contract"],
                 "outputs": [{"path": p.name, "sha256": agent.sha256_file(p)} for p in paths], "boundaries": h["boundaries"]}
        value["payload_sha256"] = agent.sha256_value(value)
        return self.write(h["step"]["step_id"] + "-receipt.json", value)

    def script(self):
        value = self.load("synthetic-case-video-script.pre-voice.json")
        value.update(pre_voice=True, selected_hook_id=None, hook_candidates=[], skill_stage_receipts=[], interview_slots=[])
        value["inputs"].pop("human_voice_receipt_ref", None)
        value["editorial_plan"] = {"audience_entry": "家庭遇到问题时，需要分清谁处理哪一步。", "service_scope": "仅核对约定和材料，不决定治疗或承诺理赔。",
                                   "abandonment_risk": "抽象服务措辞让观众难以理解具体发生了什么。", "response": "在下一轮人声编辑中改成具体行动和实际问题。",
                                   "section_advances": [{"segment_id": r["segment_id"], "spoken_span": r["spoken_text"],
                                                         "new_information": r["segment_id"] + " 本段独立提供的信息：" + r["purpose"]}
                                                        for r in value["segments"]]}
        return value

    def guide(self):
        return {"schema_version": "case-interview-guide.v1", "guide_id": "interview-guide-synthetic-001", "synthetic_only": True,
                "mode": "draft_only", "purpose": "了解虚构受访者在资料整理时的困惑。", "audience": "需要整理信息的虚构家庭",
                "fact_card_ref": {"artifact_id": self.fact["fact_card_id"], "schema_version": self.fact["schema_version"],
                                  "sha256": self.voice.research_adapter.sha256_value(self.fact)},
                "questions": [{"question_id": "q-01", "question": "当时整理资料，哪一步最让你困惑？", "purpose": "了解具体困难，不预设满意或不满。",
                               "follow_ups": ["你当时尝试了什么办法？"], "premise_fact_ids": []}],
                "unknowns": ["尚未采访，不知道受访者会如何回答。"], "production_notes": ["录制前另行核对知情授权，不代表已授权。"],
                "review_status": "required", "publication_boundary": "manual-only"}

    def test_draft_and_interview_routes_need_no_recorded_media_or_answers(self):
        for kind in ("spoken_script", "interview_guide"):
            req = self.resolve(kind)
            self.assertEqual("routing_ready", self.capsule["status"])
            self.assertEqual(self.capsule, agent.resolve_request(req))
            forbidden = {"source_media_ref", "source_subject_manifest", "local_edit_manifests", "production_run_lock"}
            self.assertFalse(forbidden.intersection(self.capsule["required_inputs"]))
            self.assertFalse(any("source_media" in step["input_roles"] for step in self.capsule["step_index"]))

    def test_production_still_requires_media(self):
        req = self.resolve()
        req.pop("preparation_kind")
        req["creation_phase"] = "production"
        capsule = agent.resolve_request(req)
        self.assertEqual("blocked_missing_inputs", capsule["status"])
        self.assertIn("source_media_ref", capsule["missing_inputs"])

    def test_selected_story_cannot_skip_design_before_draft(self):
        self.resolve()
        script = self.script()
        script["structure_route"] = "story-arc"
        script_path = self.write("story-draft.json", script)
        route = agent._load_creation_route()
        context = route.load(ROOT / "fixtures/creation-route-v1/same-day-activity-highlights.context.json")
        context.update(task_id=self.capsule["request_id"], primary_intent="causal-change",
                       avoid_forced_story=False, causal_change={"status": "supported", "evidence_refs": ["synthetic:choice"]})
        context_path = self.write("story-context.json", context)
        decision_path = self.write("story-decision.json", route.resolve(context))
        handoff = self.handoff(0, {"creation-route-context": context_path, "creation-route-decision": decision_path})
        receipt = self.receipt(handoff, [script_path])
        with self.assertRaises(agent.AgentEntryError) as caught:
            agent.verify_step_output(handoff, receipt)
        self.assertEqual("story_design_required", caught.exception.code)

    def test_required_skill_inputs_cannot_be_dropped_or_faked(self):
        self.resolve()
        self.assertEqual(agent.load_canonical_routing()["manifest"]["contract_set_version"], self.capsule["canonical_route"]["contract_set_version"])
        path = self.handoff(0)
        value = agent.load_json(path)
        self.assertEqual(4, len(value["required_reading"]))
        value["required_reading"][0]["sha256"] = "0" * 64
        value.pop("payload_sha256")
        value["payload_sha256"] = agent.sha256_value(value)
        self.write(path.name, value)
        with self.assertRaises(agent.AgentEntryError) as err:
            agent.validate_step_handoff(path)
        self.assertEqual("method_source_drift", err.exception.code)

    def test_interview_method_routed_for_both_creation_routes_only_when_needed(self):
        skill = ROOT / "skills/material-interview/SKILL.md"
        for route in ("story", "expository"):
            with self.subTest(route=route):
                sources = agent._prerecord_method_sources(route, "interview_guide")
                matches = [row for row in sources if row["source_id"] == "material-interview"]
                self.assertEqual(1, len(matches))
                self.assertEqual(skill.relative_to(ROOT.parent).as_posix(), matches[0]["workspace_relative_path"])
                self.assertEqual(agent.sha256_file(skill), matches[0]["sha256"])
                spoken = agent._prerecord_method_sources(route, "spoken_script")
                self.assertNotIn("material-interview", [row["source_id"] for row in spoken])
        self.assertEqual("skills/material-interview/SKILL.md", agent.authoring_capability()["material_interview"]["skill"])

    def test_interview_handoff_rejects_removed_or_stale_method_reference(self):
        self.resolve("interview_guide")
        path = self.handoff(0)
        original = agent.load_json(path)
        self.assertIn("material-interview", [row["source_id"] for row in original["required_reading"]])
        self.assertEqual(original, agent.validate_step_handoff(path))
        for corruption in ("remove", "hash"):
            with self.subTest(corruption=corruption):
                value = copy.deepcopy(original)
                if corruption == "remove":
                    value["required_reading"] = [row for row in value["required_reading"] if row["source_id"] != "material-interview"]
                else:
                    next(row for row in value["required_reading"] if row["source_id"] == "material-interview")["sha256"] = "0" * 64
                value.pop("payload_sha256")
                value["payload_sha256"] = agent.sha256_value(value)
                self.write(path.name, value)
                with self.assertRaises(agent.AgentEntryError) as err:
                    agent.validate_step_handoff(path)
                self.assertEqual("method_source_drift", err.exception.code)

    def test_actual_spoken_draft_review_voice_chain_and_stable_repeat(self):
        self.resolve()
        script_path = self.write("draft.json", self.script())
        h1 = self.handoff(0)
        r1 = self.receipt(h1, [script_path])
        result = agent.verify_step_output(h1, r1)
        self.assertEqual("prerecord_contract_and_existing_gates", result["validation_scope"])
        self.assertFalse(result["proves_skill_execution_or_editorial_quality"])
        review_path = self.write("initial-review.json", self.load("synthetic-initial-draft-review.v1.json"))
        h2 = self.handoff(1, {"case-video-script": script_path}, r1)
        r2 = self.receipt(h2, [review_path])
        self.assertTrue(agent.verify_step_output(h2, r2)["ok"])
        request = self.load("synthetic-human-voice-rewrite-request.v1.json")
        base = agent.load_json(script_path)
        after = copy.deepcopy(base)
        by_id = {row["segment_id"]: row for row in after["segments"]}
        for operation in request["rewrite_operations"]:
            by_id[operation["segment_id"]]["spoken_text"] = operation["replacement_text"]
        body = lambda value: self.voice.research_adapter.sha256_value(self.voice.case_adapter.stable_body_payload(value))
        request["semantic_review"] = {
            "input_body_sha256": body(base), "output_body_sha256": body(after), "reviewer_kind": "synthetic_fixture",
            "voice_basis": {"artifact_id": self.voice_basis["artifact_id"], "schema_version": self.voice_basis["schema_version"],
                            "sha256": self.voice.research_adapter.sha256_value(self.voice_basis)},
            "checks": [{"check_id": key, "segment_id": "segment-01", "before_span": base["segments"][0]["spoken_text"],
                        "after_span": after["segments"][0]["spoken_text"], "status": "resolved" if key == "author_voice_fit" else "clear",
                        "reason": "合成样例逐句核对，具体问题取代整齐对称句，仍保留事实与服务范围。"} for key in sorted(self.voice.SEMANTIC_CHECKS)]}
        request_path = self.write("voice-request.json", request)
        output = self.root / "voiced.json"
        voice_receipt = self.root / "voice-receipt.json"
        kwargs = dict(base_script_path=script_path, initial_draft_review_path=review_path, request_path=request_path,
                      fact_card_path=self.fact_path, output_script_path=output, output_receipt_path=voice_receipt)
        self.voice.apply_human_voice_gate(**kwargs)
        authored = self.author_revision(output, reviewed=True)
        h3 = self.handoff(2, {"case-video-script": script_path, "initial-draft-review": review_path,
                             "human-voice-request": request_path, "author-revision-review": authored}, r2)
        r3 = self.receipt(h3, [output, voice_receipt])
        self.assertTrue(agent.verify_step_output(h3, r3)["ok"])
        first = (output.read_bytes(), voice_receipt.read_bytes())
        self.voice.apply_human_voice_gate(**kwargs)
        self.assertEqual(first, (output.read_bytes(), voice_receipt.read_bytes()))
        self.assertFalse(agent.load_json(output)["pre_voice"])
        self.assertFalse(list(self.root.glob("*.mp4")))
        timing_input = self.timing.load_json(self.timing.FIXTURES[0])
        payoff = next(row for row in timing_input["timeline"] if "main-payoff" in row["roles"])
        payoff.update(start_seconds=4, end_seconds=12)
        timing_input.update(measured_duration_seconds=14, timeline=[timing_input["timeline"][0], payoff])
        timing_input["script_binding"] = {
            "owner": "self-media-creation-system",
            "path": output.resolve().relative_to(ROOT.resolve()).as_posix(),
            "sha256": agent.sha256_file(output),
        }
        timing_input_path = self.write("prerecord-timing-input.json", timing_input)
        h4 = self.handoff(3, {"case-video-script": output, "timing-input": timing_input_path}, r3)
        timing_receipt_path = self.write("prerecord-timing-receipt.json", self.timing.create_receipt(timing_input_path))
        r4 = self.receipt(h4, [timing_receipt_path])
        timing_result = agent.verify_step_output(h4, r4)
        self.assertTrue(timing_result["ok"])
        self.assertEqual("prerecord_contract_and_existing_gates", timing_result["validation_scope"])
        timing_receipt = agent.load_json(timing_receipt_path)
        self.assertEqual("prerecording-script", timing_receipt["stage"])
        self.assertEqual(1, timing_receipt["observed_metrics"]["information_advance_count"])
        self.assertFalse(list(self.root.glob("*.mp4")))

    def test_interview_questions_and_review_without_answers(self):
        self.resolve("interview_guide")
        guide = self.guide()
        path = self.write("guide.json", guide)
        h1 = self.handoff(0)
        r1 = self.receipt(h1, [path])
        self.assertTrue(agent.verify_step_output(h1, r1)["ok"])
        h2 = self.handoff(1, {"interview-guide": path}, r1)
        review = {"schema_version": "case-interview-guide-review.v1", "guide_id": guide["guide_id"],
                  "guide_sha256": self.voice.research_adapter.sha256_value(guide), "synthetic_only": True,
                  "reviewer": "synthetic-fixture-author", "reviewed_at": "2026-09-04T13:00:00Z", "decision": "approved_questions_only",
                  "authority": "questions_only_no_recording_or_publication_authority",
                  "checks": [{"check_id": key, "question_id": "q-01", "question_span": guide["questions"][0]["question"],
                              "status": "clear", "reason": "合成审核明确检查了问题，不预设受访者答案或公开授权。"}
                             for key in ("non_leading_questions", "privacy", "fact_premises", "spoken_clarity")]}
        reviewed = self.write("guide-review.json", review)
        r2 = self.receipt(h2, [reviewed])
        self.assertTrue(agent.verify_step_output(h2, r2)["ok"])
        review["checks"][0]["status"] = "blocked"
        self.write(reviewed.name, review)
        r2 = self.receipt(h2, [reviewed])
        with self.assertRaisesRegex(agent.AgentEntryError, "no approved-question"):
            agent.verify_step_output(h2, r2)

    def test_skip_blocked_empty_drift_and_inspection_fail_closed(self):
        self.resolve()
        script = self.write("draft.json", self.script())
        with self.assertRaises(agent.AgentEntryError) as skip:
            self.handoff(1, {"case-video-script": script})
        self.assertEqual("previous_step_required", skip.exception.code)
        h = self.handoff(0)
        r = self.receipt(h, [script], "blocked")
        self.assertFalse(agent.verify_step_output(h, r)["ok"])
        with self.assertRaises(agent.AgentEntryError) as blocked:
            self.handoff(1, {"case-video-script": script}, r)
        self.assertEqual("previous_step_blocked", blocked.exception.code)
        r = self.receipt(h, [])
        with self.assertRaises(agent.AgentEntryError):
            agent.verify_step_output(h, r)
        empty = self.root / "empty.json"
        empty.write_bytes(b"")
        r = self.receipt(h, [empty])
        with self.assertRaises(agent.AgentEntryError) as err:
            agent.verify_step_output(h, r)
        self.assertEqual("output_artifact_empty", err.exception.code)
        r = self.receipt(h, [script])
        self.handoff(1, {"case-video-script": script}, r)
        script.write_text("{}", encoding="utf-8")
        with self.assertRaises(agent.AgentEntryError):
            self.handoff(1, {"case-video-script": script}, r)
        hi = self.handoff(0, inspect=True)
        with self.assertRaises(agent.AgentEntryError) as err:
            agent.validate_step_handoff(hi)
        self.assertEqual("inspection_not_execution", err.exception.code)

    def test_fake_transcript_or_unconfirmed_premises_not_accepted_as_guide(self):
        self.resolve("interview_guide")
        h = self.handoff(0)
        for field in ("answer", "transcript", "source_media", "publication_authorized"):
            guide = self.guide()
            guide[field] = "invented"
            r = self.receipt(h, [self.write("guide.json", guide)])
            with self.assertRaises(agent.AgentEntryError):
                agent.verify_step_output(h, r)
        guide = self.guide()
        guide["questions"][0]["premise_fact_ids"] = ["missing-fact"]
        r = self.receipt(h, [self.write("guide.json", guide)])
        with self.assertRaises(agent.AgentEntryError) as err:
            agent.verify_step_output(h, r)
        self.assertEqual("unconfirmed_question_premise", err.exception.code)

    def test_plan_without_matching_spans_or_self_approved_draft_rejected(self):
        self.resolve()
        h = self.handoff(0)
        for mutation in (lambda v: v.update(pre_voice=False),
                         lambda v: v["editorial_plan"]["section_advances"][0].update(spoken_span="不存在的句段。"),
                         lambda v: v["inputs"]["fact_card_ref"].update(sha256="0" * 64),
                         lambda v: v["editorial_plan"]["section_advances"].pop()):
            value = self.script()
            mutation(value)
            r = self.receipt(h, [self.write("draft.json", value)])
            with self.assertRaises(agent.AgentEntryError):
                agent.verify_step_output(h, r)

    def test_wrong_output_contract_and_substituted_predecessor_rejected(self):
        self.resolve()
        h1 = self.handoff(0)
        r = self.receipt(h1, [self.write("fake.json", {"schema_version": "invented", "synthetic_only": True})])
        with self.assertRaises(agent.AgentEntryError):
            agent.verify_step_output(h1, r)
        draft = self.write("draft.json", self.script())
        r1 = self.receipt(h1, [draft])
        substitute = self.write("other-draft.json", self.script())
        h2 = self.handoff(1, {"case-video-script": substitute}, r1)
        review = self.write("review.json", self.load("synthetic-initial-draft-review.v1.json"))
        r2 = self.receipt(h2, [review])
        with self.assertRaises(agent.AgentEntryError) as err:
            agent.verify_step_output(h2, r2)
        self.assertEqual("predecessor_output_not_consumed", err.exception.code)


if __name__ == "__main__":
    unittest.main()
