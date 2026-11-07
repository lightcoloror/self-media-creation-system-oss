from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("archive_lifecycle", ROOT / "scripts/artifact_lifecycle.py")
lifecycle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lifecycle)


class VideoArchivePolicyTests(unittest.TestCase):
    def assessment(self):
        return {"project_id": "synthetic", "restore_goal": "Change subtitle and outro",
                "factors": {key: False for key in lifecycle._read_json(lifecycle.ARCHIVE_POLICY)["upgrade_factors"]}}

    def test_default_rework_does_not_claim_checks_or_upload(self):
        plan = lifecycle.build_archive_plan(self.assessment())
        self.assertEqual(plan["selected_level"], "rework")
        self.assertTrue(plan["assessment_complete"])
        self.assertFalse(plan["archive_complete"])
        self.assertFalse(plan["rebuild_verified"])
        self.assertFalse(plan["uploaded"])
        self.assertTrue(all(x["status"] == "not_run" for x in plan["required_checks"]))

    def test_each_material_upgrade_factor_selects_reproducible(self):
        for factor in self.assessment()["factors"]:
            with self.subTest(factor=factor):
                data = self.assessment()
                data["factors"][factor] = True
                plan = lifecycle.build_archive_plan(data)
                self.assertEqual(plan["selected_level"], "reproducible")
                self.assertIn("rebuild_declared_scope_in_relocated_directory", [x["check"] for x in plan["required_checks"]])

    def test_unassessed_factors_stay_unknown_not_false(self):
        plan = lifecycle.build_archive_plan({"project_id": "demo", "restore_goal": "rework"})
        self.assertEqual(plan["selected_level"], "rework")
        self.assertFalse(plan["assessment_complete"])
        self.assertEqual(len(plan["unknown_factors"]), 5)

    def test_simple_requires_reason_and_source_reference(self):
        data = self.assessment() | {"selected_level": "simple"}
        with self.assertRaises(lifecycle.LifecycleError):
            lifecycle.build_archive_plan(data)
        data["decision_reason"] = "Only replay required"
        with self.assertRaises(lifecycle.LifecycleError):
            lifecycle.build_archive_plan(data)
        data["original_backup_reference"] = "private-catalog:synthetic-source"
        plan = lifecycle.build_archive_plan(data)
        self.assertEqual(plan["selected_level"], "simple")
        self.assertFalse(plan["original_backup_verified"])

    def test_checkpoint_exception_needs_visible_reason(self):
        data = self.assessment() | {"selected_level": "rework"}
        data["factors"]["dependency_sensitive_effects"] = True
        with self.assertRaises(lifecycle.LifecycleError):
            lifecycle.build_archive_plan(data)
        data["decision_reason"] = "Only audio will change; locked effect master is sufficient"
        self.assertTrue(lifecycle.build_archive_plan(data)["recommendation_overridden"])

    def test_missing_layer_is_reported_not_reconstructed_or_approved(self):
        data = self.assessment() | {"missing_materials": ["opening narration source"]}
        plan = lifecycle.build_archive_plan(data)
        self.assertEqual(plan["missing_materials"], data["missing_materials"])
        self.assertFalse(plan["archive_complete"])

    def test_rejects_claimed_acceptance_and_wrong_factor_types(self):
        for extra in [{"uploaded": True}, {"factors": {"cross_machine_rebuild": "false"}},
                      {"factors": {"typo": True}}, {"project_id": " "}]:
            with self.subTest(extra=extra), self.assertRaises(lifecycle.LifecycleError):
                lifecycle.build_archive_plan(self.assessment() | extra)

    def test_tiers_inherit_earlier_materials(self):
        plan = lifecycle.build_archive_plan(self.assessment() | {"selected_level": "reproducible", "decision_reason": "Explicit long-term rebuild choice"})
        self.assertIn("final_media", plan["required_material_groups"])
        self.assertIn("adopted_fine_cuts", plan["required_material_groups"])
        self.assertIn("executable_entrypoint", plan["required_material_groups"])

    def test_cli_writes_only_plan_and_refuses_existing_output(self):
        data = self.assessment()
        with patch.object(lifecycle, "_read_json", wraps=lifecycle._read_json) as read, patch.object(lifecycle, "_write_json_atomic") as write, patch.object(lifecycle.Path, "exists", return_value=False):
            def load(path):
                return data if str(path) == "assessment.json" else json.loads(path.read_text(encoding="utf-8"))
            read.side_effect = load
            with patch("builtins.print"):
                self.assertEqual(lifecycle.main(["archive-plan", "--assessment", "assessment.json", "--output", "plan.json"]), 0)
            write.assert_called_once()
            self.assertEqual(write.call_args.args[1]["status"], "planning_only")
        with patch.object(lifecycle.Path, "exists", return_value=True), patch.object(lifecycle, "_write_json_atomic") as write, patch("builtins.print"):
            self.assertEqual(lifecycle.main(["archive-plan", "--assessment", "assessment.json", "--output", "plan.json"]), 2)
            write.assert_not_called()


if __name__ == "__main__":
    unittest.main()
