from __future__ import annotations

import json
import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "content_diagnosis.py"
FIXTURE = ROOT / "fixtures" / "content-bundle.v1.fixture.json"


class ContentDiagnosisCliTests(unittest.TestCase):
    def run_cli(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run([sys.executable, str(CLI), *arguments], cwd=ROOT, text=True, capture_output=True, check=False)

    def test_fixture_produces_batch_dry_run_without_external_execution(self) -> None:
        completed = self.run_cli("--input", str(FIXTURE))
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result["schema_version"], "analysis-result.v1")
        self.assertEqual(result["engine"], {"id": "self-media-offline-rules-p0", "version": "1.0.0", "network_calls": 0, "models_called": [], "comments_simulated": False, "published": False})
        self.assertEqual(len(result["items"]), 1)
        self.assertEqual({role["role_id"] for role in result["items"][0]["roles"]}, {"clarity-reader", "route-adapter", "evidence-safety", "voice-visual"})

    def test_validate_only_uses_the_same_contract(self) -> None:
        completed = self.run_cli("--input", str(FIXTURE), "--validate-only")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout)["valid"], True)

    def test_privacy_block_does_not_echo_direct_identifier(self) -> None:
        bundle = json.loads(FIXTURE.read_text(encoding="utf-8"))
        bundle["items"][0]["content"]["body"] = "请联系 13800138000 了解详情。"
        bundle["privacy"]["content_text_may_contain_personal_data"] = True
        source = ROOT / ".test-runtime" / "privacy-input.json"
        source.parent.mkdir(exist_ok=True)
        source.write_text(json.dumps(bundle, ensure_ascii=False), encoding="utf-8")
        self.addCleanup(source.unlink, missing_ok=True)
        completed = self.run_cli("--input", str(source))
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        blocks = {item["id"] for item in result["items"][0]["findings"] if item["severity"] == "block"}
        self.assertIn("privacy-review-required", blocks)
        self.assertIn("privacy-direct-identifier", blocks)
        self.assertNotIn("13800138000", json.dumps(result, ensure_ascii=False))

    def test_rejects_comment_url_and_nonopaque_profile_fields(self) -> None:
        bundle = json.loads(FIXTURE.read_text(encoding="utf-8"))
        bundle["items"][0]["comments"] = []
        bundle["items"][0]["profile_id"] = "display-name"
        source = ROOT / ".test-runtime" / "invalid-input.json"
        source.parent.mkdir(exist_ok=True)
        source.write_text(json.dumps(bundle, ensure_ascii=False), encoding="utf-8")
        self.addCleanup(source.unlink, missing_ok=True)
        completed = self.run_cli("--input", str(source))
        self.assertEqual(completed.returncode, 2)
        self.assertIn("prohibited", completed.stderr)
        self.assertIn("opaque", completed.stderr)


    def test_batch_keeps_each_opaque_input_reference(self) -> None:
        bundle = json.loads(FIXTURE.read_text(encoding="utf-8"))
        second = json.loads(json.dumps(bundle["items"][0]))
        second["content_id"] = "content-demo-002"
        bundle["items"].append(second)
        source = ROOT / ".test-runtime" / "batch-input.json"
        source.parent.mkdir(exist_ok=True)
        source.write_text(json.dumps(bundle, ensure_ascii=False), encoding="utf-8")
        self.addCleanup(source.unlink, missing_ok=True)
        completed = self.run_cli("--input", str(source))
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result["summary"]["item_count"], 2)
        self.assertEqual([item["input_ref"]["content_id"] for item in result["items"]], ["content-demo-001", "content-demo-002"])

    def test_search_question_requires_structure_route_not_reframing(self) -> None:
        bundle = json.loads(FIXTURE.read_text(encoding="utf-8"))
        context = bundle["items"][0]["routing_context"]
        context["content_job"] = "question-answer"
        context["primary_goal"] = "search-discovery"
        source = ROOT / ".test-runtime" / "missing-question-structure-route.json"
        source.parent.mkdir(exist_ok=True)
        source.write_text(json.dumps(bundle, ensure_ascii=False), encoding="utf-8")
        self.addCleanup(source.unlink, missing_ok=True)
        completed = self.run_cli("--input", str(source))
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        findings = {item["id"] for item in result["items"][0]["findings"]}
        self.assertIn("question-structure-route-missing", findings)

    def test_complete_decision_reframe_avoids_missing_warning(self) -> None:
        bundle = json.loads(FIXTURE.read_text(encoding="utf-8"))
        context = bundle["items"][0]["routing_context"]
        context.update({
            "content_job": "question-answer",
            "primary_goal": "search-discovery",
            "question_structure_route": "decision-reframe",
            "audience_entry_question": "有医保还需要商业医疗险吗？",
            "surface_answer": "不一定，先看已有保障后的缺口。",
            "professional_core_question": "医保报完后是否仍有家庭难以承担且保险能补上的费用？",
            "client_decision": "决定需要补、暂缓还是换方向。",
            "scope_boundary": "公费医疗等特殊待遇另篇讨论。",
            "public_expertise_level": "client-usable",
        })
        source = ROOT / ".test-runtime" / "complete-topic-reframing.json"
        source.parent.mkdir(exist_ok=True)
        source.write_text(json.dumps(bundle, ensure_ascii=False), encoding="utf-8")
        self.addCleanup(source.unlink, missing_ok=True)
        completed = self.run_cli("--input", str(source))
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        findings = {item["id"] for item in result["items"][0]["findings"]}
        self.assertNotIn("topic-reframing-incomplete", findings)
        self.assertNotIn("question-structure-route-missing", findings)

    def test_direct_answer_does_not_require_professional_core_question(self) -> None:
        bundle = json.loads(FIXTURE.read_text(encoding="utf-8"))
        context = bundle["items"][0]["routing_context"]
        context.update({
            "content_job": "question-answer",
            "primary_goal": "search-discovery",
            "question_structure_route": "direct-answer",
            "audience_entry_question": "医疗险理赔要准备哪些材料？",
            "surface_answer": "先按合同和保险公司的材料清单准备。",
            "scope_boundary": "具体材料以个案和保险公司通知为准。",
        })
        source = ROOT / ".test-runtime" / "complete-direct-answer.json"
        source.parent.mkdir(exist_ok=True)
        source.write_text(json.dumps(bundle, ensure_ascii=False), encoding="utf-8")
        self.addCleanup(source.unlink, missing_ok=True)
        completed = self.run_cli("--input", str(source))
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        findings = {item["id"] for item in result["items"][0]["findings"]}
        self.assertNotIn("topic-reframing-incomplete", findings)
        self.assertNotIn("question-structure-route-missing", findings)
        self.assertNotIn("direct-answer-incomplete", findings)

    def test_question_can_use_scenario_branch_as_body_route(self) -> None:
        bundle = json.loads(FIXTURE.read_text(encoding="utf-8"))
        context = bundle["items"][0]["routing_context"]
        context.update({
            "content_job": "question-answer",
            "primary_goal": "search-discovery",
            "question_structure_route": "direct-answer",
            "structure_route": "scenario-branch",
            "structure_route_note": "答案取决于已有保障、家庭承受能力和就医需求。",
            "audience_entry_question": "有医保还需要商业医疗险吗？",
            "surface_answer": "不同家庭的答案不同。",
            "scope_boundary": "特殊单位待遇另行判断。",
        })
        source = ROOT / ".test-runtime" / "scenario-branch-question.json"
        source.parent.mkdir(exist_ok=True)
        source.write_text(json.dumps(bundle, ensure_ascii=False), encoding="utf-8")
        self.addCleanup(source.unlink, missing_ok=True)
        completed = self.run_cli("--input", str(source))
        self.assertEqual(completed.returncode, 0, completed.stderr)
        findings = {item["id"] for item in json.loads(completed.stdout)["items"][0]["findings"]}
        self.assertNotIn("question-structure-route-missing", findings)
        self.assertNotIn("manual-route-override-not-applied", findings)

    def test_invalid_structure_route_is_rejected(self) -> None:
        bundle = json.loads(FIXTURE.read_text(encoding="utf-8"))
        bundle["items"][0]["routing_context"]["structure_route"] = "one-template-for-everything"
        source = ROOT / ".test-runtime" / "invalid-structure-route.json"
        source.parent.mkdir(exist_ok=True)
        source.write_text(json.dumps(bundle, ensure_ascii=False), encoding="utf-8")
        self.addCleanup(source.unlink, missing_ok=True)
        completed = self.run_cli("--input", str(source), "--validate-only")
        self.assertEqual(completed.returncode, 2)
        self.assertIn("structure_route is invalid", completed.stderr)

    def test_human_route_override_mismatch_is_visible(self) -> None:
        bundle = json.loads(FIXTURE.read_text(encoding="utf-8"))
        context = bundle["items"][0]["routing_context"]
        context.update({
            "structure_route": "case-review",
            "manual_route_override": {
                "stage": "draft",
                "from": "case-review",
                "to": "mechanism-explanation",
                "reason": "现有证据更适合解释因果关系。",
                "changed_by": "human",
            },
        })
        source = ROOT / ".test-runtime" / "manual-route-override-mismatch.json"
        source.parent.mkdir(exist_ok=True)
        source.write_text(json.dumps(bundle, ensure_ascii=False), encoding="utf-8")
        self.addCleanup(source.unlink, missing_ok=True)
        completed = self.run_cli("--input", str(source))
        self.assertEqual(completed.returncode, 0, completed.stderr)
        findings = {item["id"] for item in json.loads(completed.stdout)["items"][0]["findings"]}
        self.assertIn("manual-route-override-not-applied", findings)

    def test_series_item_that_requires_another_item_is_blocked_early(self) -> None:
        bundle = json.loads(FIXTURE.read_text(encoding="utf-8"))
        context = bundle["items"][0]["routing_context"]
        context.update({
            "planning_scope": "series",
            "series_question": "家庭保障怎么逐步梳理？",
            "current_piece_decision": "本条说明如何先找齐已有保单。",
        })
        bundle["items"][0]["content"]["body"] = "接着上一集，具体做法下期再讲。"
        result = importlib.util.spec_from_file_location(
            "content_diagnosis_direct", CLI
        )
        assert result and result.loader
        module = importlib.util.module_from_spec(result)
        result.loader.exec_module(module)
        diagnosed = module.diagnose(bundle)
        findings = {item["id"]: item for item in diagnosed["items"][0]["findings"]}
        self.assertEqual("block", findings["series-item-not-standalone"]["severity"])

    def test_self_contained_series_item_avoids_dependency_block(self) -> None:
        bundle = json.loads(FIXTURE.read_text(encoding="utf-8"))
        context = bundle["items"][0]["routing_context"]
        context.update({
            "planning_scope": "series",
            "series_question": "家庭保障怎么逐步梳理？",
            "current_piece_decision": "本条说明如何先找齐已有保单。",
        })
        bundle["items"][0]["content"]["body"] = (
            "先把每份保单找齐，再按保障对象和责任整理到一张表里。"
            "这样就能独立看清已有保障。下一条讨论理赔材料，这是另一个问题。"
        )
        result = importlib.util.spec_from_file_location(
            "content_diagnosis_direct_complete", CLI
        )
        assert result and result.loader
        module = importlib.util.module_from_spec(result)
        result.loader.exec_module(module)
        diagnosed = module.diagnose(bundle)
        findings = {item["id"] for item in diagnosed["items"][0]["findings"]}
        self.assertNotIn("series-item-not-standalone", findings)

if __name__ == "__main__":
    unittest.main()
