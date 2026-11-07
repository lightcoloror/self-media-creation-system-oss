from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


diagnosis = load_module("content_diagnosis")
packaging = load_module("content_packaging_review")


class ContentReviewConsistencyTests(unittest.TestCase):
    def bundle(self):
        return json.loads((ROOT / "fixtures/content-bundle.v1.fixture.json").read_text(encoding="utf-8"))

    def test_one_missing_voice_route_is_one_finding_shared_by_both_roles(self):
        bundle = self.bundle()
        del bundle["items"][0]["routing_context"]["voice_visual_route"]
        result = diagnosis.diagnose(bundle)
        item = result["items"][0]
        findings = [row["id"] for row in item["findings"]]
        self.assertEqual(1, findings.count("voice-visual-route-missing"))
        self.assertNotIn("route-context-incomplete", findings)
        roles = {row["role_id"]: row["finding_ids"] for row in item["roles"]}
        for role in ("route-adapter", "voice-visual"):
            self.assertIn("voice-visual-route-missing", roles[role])
        self.assertEqual(len(set(findings)), result["summary"]["finding_count"])
        self.assertNotIn("路由与声纹角色共同要求", " ".join(item["cross_review"]["challenges"]))
        schema = json.loads((ROOT / "schemas/analysis-result.v1.schema.json").read_text(encoding="utf-8"))
        Draft202012Validator(schema).validate(result)

    def test_other_missing_route_fields_still_have_a_separate_action(self):
        bundle = self.bundle()
        context = bundle["items"][0]["routing_context"]
        del context["voice_visual_route"]
        del context["account_ip"]
        result = diagnosis.diagnose(bundle)
        findings = {row["id"]: row for row in result["items"][0]["findings"]}
        self.assertIn("voice-visual-route-missing", findings)
        route = findings["route-context-incomplete"]
        self.assertIn("account_ip", route["recommendation"])
        self.assertNotIn("voice_visual_route", route["recommendation"])

    def test_early_and_frozen_checks_agree_without_series_label(self):
        package = json.loads(packaging.DEFAULT_INPUT.read_text(encoding="utf-8"))
        body = (ROOT / package["body_ref"]).read_text(encoding="utf-8")
        cases = (
            ("接着上一集，具体做法下期再讲。", True),
            ("没看过上一期就看不懂。", True),
            ("Watch episode 2 first.", True),
            ("ＷＡＴＣＨ ＥＰＩＳＯＤＥ ２ ＦＩＲＳＴ", True),
            ("Continued from the previous part.", True),
            ("The answer will be in the next episode.", True),
            ("答案\n下期\n揭晓。", True),
            ("本条内容完整。下一条讨论理赔材料，这是另一个问题。", False),
        )
        for text, dependent in cases:
            for planning_scope in (None, "single", "series"):
                with self.subTest(text=text, planning_scope=planning_scope):
                    bundle = self.bundle()
                    context = bundle["items"][0]["routing_context"]
                    if planning_scope is not None:
                        context["planning_scope"] = planning_scope
                    if planning_scope == "series":
                        context.update(series_question="家庭保障怎么整理？", current_piece_decision="先整理已有保单。")
                    bundle["items"][0]["content"]["body"] = body + "\n" + text
                    result = diagnosis.diagnose(bundle)
                    findings = {row["id"]: row for row in result["items"][0]["findings"]}
                    self.assertEqual(dependent, "series-item-not-standalone" in findings)
                    if dependent:
                        self.assertEqual("block", findings["series-item-not-standalone"]["severity"])
                    try:
                        packaging.validate_standalone_review(
                            package["standalone_review"], title=package["title"],
                            opening_text=package["opening_text"], body_text=body + "\n" + text,
                        )
                    except packaging.PackagingReviewError as error:
                        self.assertTrue(dependent)
                        self.assertEqual("series_dependency_prohibited", error.code)
                    else:
                        self.assertFalse(dependent)


if __name__ == "__main__":
    unittest.main()
