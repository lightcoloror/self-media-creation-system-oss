from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import shutil
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


ROUTE = module("creation_route_test", ROOT / "scripts/creation_route.py")
AGENT = module("creation_route_agent_test", ROOT / "scripts/self_media_agent.py")


class CreationRouteTests(unittest.TestCase):
    @contextmanager
    def workspace(self):
        base = (ROOT / "outputs/test-temp").resolve()
        root = base / ("creation-route-test-" + uuid.uuid4().hex)
        root.mkdir(parents=True)
        try:
            yield root
        finally:
            if root.is_relative_to(base) and root != base:
                shutil.rmtree(root)

    def context(self, **changes):
        value = ROUTE.load(ROOT / "fixtures/creation-route-v1/same-day-activity-highlights.context.json")
        value.update(changes)
        return value

    def manifest(self, root, context):
        artifacts = []
        for name, content, role in (
            ("context.json", context, "creation-route-context"),
            ("decision.json", ROUTE.resolve(context), "creation-route-decision"),
        ):
            path = root / name
            path.write_text(json.dumps(content, ensure_ascii=False), encoding="utf-8")
            artifacts.append({"artifact_id": role, "role": "source_manifest", "source_role": role,
                "path": name, "load_mode": "reference", "expected_sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
        target = root / "manifest.json"
        target.write_text(json.dumps({"artifacts": artifacts}), encoding="utf-8")
        return target

    def test_fictional_route_selects_highlights_without_claiming_media_review(self):
        decision = ROUTE.resolve(self.context())
        self.assertEqual((decision["primary_route"], decision["vlog_style"]), ("travel-experience", "activity-highlights"))
        self.assertEqual(decision["story_design_applicability"], "not-applicable")
        self.assertEqual(decision["status"], "ready")
        self.assertFalse(decision["publication_authority"])
        self.assertIn("未声称已重新观看", decision["assessment_reason"])

    def test_all_six_vlog_forms_are_independent_of_causal_evidence(self):
        mapping = ROUTE.load(ROUTE.POLICY_PATH)["intent_to_vlog_style"]
        for intent, style in mapping.items():
            with self.subTest(intent=intent):
                value = ROUTE.resolve(self.context(primary_intent=intent))
                self.assertEqual(value["status"], "ready")
                self.assertEqual(value["vlog_style"], style)
                self.assertEqual(value["story_design_applicability"], "not-applicable")
                self.assertEqual(value["shared_material_analysis"], ROUTE.resolve(self.context())["shared_material_analysis"])

    def test_supported_change_alone_does_not_convert_an_activity_vlog_to_story(self):
        value = ROUTE.resolve(self.context(causal_change={"status": "supported", "evidence_refs": ["source-001:20-60"]}))
        self.assertEqual(value["primary_route"], "travel-experience")

    def test_real_story_still_selects_existing_story_route(self):
        value = ROUTE.resolve(self.context(primary_intent="causal-change", avoid_forced_story=False,
            causal_change={"status": "supported", "evidence_refs": ["human-review:action-feedback-change"]}))
        self.assertEqual(value["primary_route"], "story")
        self.assertEqual(value["status"], "ready")
        self.assertEqual(value["story_design_applicability"], "required")

    def test_explicit_story_without_causal_evidence_cannot_continue(self):
        value = ROUTE.resolve(self.context(requested_route="story", avoid_forced_story=False))
        self.assertEqual(value["status"], "needs-evidence")
        with self.assertRaises(ROUTE.CreationRouteError):
            ROUTE.check(value)

    def test_travel_topic_and_old_material_are_not_enough_to_pick_a_form(self):
        value = ROUTE.resolve(self.context(primary_intent="unknown"))
        self.assertEqual(value["status"], "needs-context")
        self.assertIsNone(value["primary_route"])

    def test_user_explicit_form_can_override_automatic_form(self):
        value = ROUTE.resolve(self.context(requested_vlog_style="atmospheric-montage"))
        self.assertEqual(value["vlog_style"], "atmospheric-montage")

    def test_avoid_forced_story_conflict_cannot_silently_pass(self):
        value = ROUTE.resolve(self.context(primary_intent="causal-change",
            causal_change={"status": "supported", "evidence_refs": ["source-001"]}))
        self.assertEqual(value["status"], "needs-context")

    def test_planned_vlog_needs_no_fake_recorded_result(self):
        value = ROUTE.resolve(self.context(material_state="planned"))
        self.assertEqual(value["status"], "ready")

    def test_technical_rework_and_explanation_are_distinct(self):
        self.assertEqual(ROUTE.resolve(self.context(task_kind="technical-rework"))["primary_route"], "technical-rework")
        self.assertEqual(ROUTE.resolve(self.context(primary_intent="explain-or-answer"))["primary_route"], "expository")

    def test_new_feedback_or_goal_invalidates_previous_decision(self):
        context = self.context()
        decision = ROUTE.resolve(context)
        revised = self.context(primary_intent="preserve-experience", revision_id="new-review")
        with self.assertRaises(ROUTE.CreationRouteError) as error:
            ROUTE.check(decision, revised)
        self.assertEqual(error.exception.code, "creation_route_context_drift")
        self.assertEqual(ROUTE.resolve(revised)["vlog_style"], "chronological-diary")

    def test_policy_or_decision_drift_and_wrong_task_are_rejected(self):
        context = self.context()
        decision = ROUTE.resolve(context)
        for field in ("primary_route", "story_design_applicability", "policy_sha256"):
            bad = copy.deepcopy(decision)
            bad[field] = "changed"
            with self.assertRaises(ROUTE.CreationRouteError):
                ROUTE.check(bad, context)
        with self.assertRaises(ROUTE.CreationRouteError) as error:
            ROUTE.check(decision, context, "different-task")
        self.assertEqual(error.exception.code, "creation_route_task_mismatch")

    def test_writing_consumer_requires_decision_and_current_context(self):
        with self.workspace() as root:
            target = root / "manifest.json"
            target.write_text('{"artifacts":[]}', encoding="utf-8")
            with self.assertRaises(AGENT.AgentEntryError) as error:
                AGENT._validate_creation_context(target, {"request_id": "fixture-task"}, {"step_id": "draft-prerecord-case"})
            self.assertEqual(error.exception.code, "creation_route_required")

    def test_managed_writing_consumes_expository_but_rejects_vlog_case_substitution(self):
        with self.workspace() as root:
            context = self.context(primary_intent="explain-or-answer")
            target = self.manifest(root, context)
            value = AGENT._validate_creation_context(target, {"request_id": context["task_id"]}, {"step_id": "draft-prerecord-case"})
            self.assertEqual(value["primary_route"], "expository")
            target = self.manifest(root, self.context())
            with self.assertRaises(AGENT.AgentEntryError) as error:
                AGENT._validate_creation_context(target, {"request_id": context["task_id"]}, {"step_id": "project-case-script"})
            self.assertEqual(error.exception.code, "creation_route_wrong_workflow")

    def test_managed_writing_rejects_rehashed_stale_decision_and_file_drift(self):
        with self.workspace() as root:
            context = self.context(primary_intent="explain-or-answer")
            target = self.manifest(root, context)
            (root / "context.json").write_text(json.dumps(self.context()), encoding="utf-8")
            manifest = ROUTE.load(target)
            manifest["artifacts"][0]["expected_sha256"] = hashlib.sha256((root / "context.json").read_bytes()).hexdigest()
            target.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaises(ROUTE.CreationRouteError) as error:
                ROUTE.check_manifest(target, context["task_id"], {"step_id": "build-evidence-draft"})
            self.assertEqual(error.exception.code, "creation_route_context_drift")
            (root / "decision.json").write_text('{}', encoding="utf-8")
            with self.assertRaises(ROUTE.CreationRouteError) as error:
                ROUTE.check_manifest(target, context["task_id"], {"step_id": "build-evidence-draft"})
            self.assertEqual(error.exception.code, "creation_route_artifact_drift")

    def test_prerecord_reading_no_longer_unconditionally_loads_story_skill(self):
        explanatory = AGENT._prerecord_method_sources("expository")
        story = AGENT._prerecord_method_sources("story")
        self.assertNotIn("local-insurance-storycraft", {row["source_id"] for row in explanatory})
        self.assertIn("local-insurance-storycraft", {row["source_id"] for row in story})

    def test_capabilities_make_independent_route_discoverable(self):
        value = AGENT.capabilities()["creation_routing"]
        self.assertTrue(value["mandatory_before_creative_work"])
        self.assertTrue(value["vlog_is_independent_of_case_recipe"])


if __name__ == "__main__":
    unittest.main()
