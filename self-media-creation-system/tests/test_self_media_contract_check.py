from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_self_media_contracts.py"
SPEC = importlib.util.spec_from_file_location("check_self_media_contracts", SCRIPT)
assert SPEC and SPEC.loader
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def operations_fixture() -> dict:
    return load_json(ROOT / "fixtures" / "operations-contract-regression.v1.synthetic.json")


def legacy_fixture() -> dict:
    return load_json(ROOT / "fixtures" / "legacy-feedback.v0.synthetic.json")


class SelfMediaContractCheckTests(unittest.TestCase):
    def test_current_public_owner_schema_drift_is_blocked(self) -> None:
        from unittest.mock import patch
        self.assertEqual(CHECK.validate_public_content_owner(), [])
        original = Path.read_bytes
        owner_path = CHECK.WORKSPACE_ROOT / "content-studio-poc" / "schemas" / "content-item.schema.json"
        def drift(path):
            raw = original(path)
            return raw + b"\n" if path == owner_path else raw
        with patch.object(Path, "read_bytes", drift):
            self.assertTrue(any("differ" in error for error in CHECK.validate_public_content_owner()))

    def test_subprocess_runtime_uses_repository_owned_temp_root(self) -> None:
        env = CHECK.controlled_subprocess_env()
        expected = (ROOT / ".runtime" / "test-temp").resolve()
        self.assertEqual(Path(env["TEMP"]).resolve(), expected)
        self.assertEqual(Path(env["TMP"]).resolve(), expected)
        self.assertEqual(Path(env["TMPDIR"]).resolve(), expected)
        self.assertEqual(Path(env["TEST_TMP_ROOT"]).resolve(), expected)
        self.assertTrue(expected.is_dir())

    def test_single_contract_check_passes_without_test_recursion(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(SCRIPT), "--no-tests"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("PASS:", completed.stdout)

    def test_legacy_v0_fixture_migrates_without_business_inference(self) -> None:
        self.assertEqual(CHECK.validate_legacy_fixture(operations_fixture(), legacy_fixture()), [])

    def test_append_only_content_operations_cycle_is_in_unified_check(self) -> None:
        self.assertEqual(CHECK.validate_content_operations_cycle(), [])

    def test_standalone_item_packaging_gate_is_in_unified_check(self) -> None:
        self.assertEqual(CHECK.validate_content_packaging_review(), [])

    def test_serious_content_translation_gate_is_in_unified_check(self) -> None:
        self.assertEqual(CHECK.validate_serious_content_translation_gate(), [])

    def test_science_popularization_gate_is_in_unified_check(self) -> None:
        self.assertEqual(CHECK.validate_science_popularization_gate(), [])

    def test_editorial_angle_gate_is_in_unified_check(self) -> None:
        self.assertEqual(CHECK.validate_editorial_angle_integration(), [])

    def test_story_five_question_adapter_is_in_unified_check(self) -> None:
        self.assertEqual(CHECK.validate_story_five_question_adapter(), [])

    def test_story_design_gate_is_in_unified_check(self) -> None:
        self.assertEqual(CHECK.validate_story_design_gate(), [])

    def test_measured_video_timing_gate_is_in_unified_check(self) -> None:
        self.assertEqual(CHECK.validate_short_video_timing_evidence(), [])

    def test_five_platform_metric_dictionary_is_in_unified_check(self) -> None:
        self.assertEqual(CHECK.validate_platform_metrics_intake(), [])

    def test_publication_version_freeze_is_in_unified_check(self) -> None:
        self.assertEqual(CHECK.validate_publication_version_freeze(), [])

    def test_unknown_field_is_rejected(self) -> None:
        bundle = operations_fixture()
        bundle["account"]["unknown_field"] = "must-not-pass"
        self.assertTrue(any("unknown_field" in error for error in CHECK.contract_errors(bundle, legacy_fixture())))

    def test_duplicate_publication_event_is_rejected(self) -> None:
        bundle = operations_fixture()
        bundle["publication_events"].append(copy.deepcopy(bundle["publication_events"][1]))
        self.assertTrue(any("duplicate event_id" in error for error in CHECK.contract_errors(bundle, legacy_fixture())))

    def test_unordered_snapshots_are_rejected(self) -> None:
        bundle = operations_fixture()
        bundle["performance_snapshots"] = list(reversed(bundle["performance_snapshots"]))
        self.assertTrue(any("ordered by as_of" in error for error in CHECK.contract_errors(bundle, legacy_fixture())))

    def test_observation_window_boundaries_are_accepted(self) -> None:
        for early, d7 in [
            ("2026-01-07T09:01:00+08:00", "2026-01-11T21:01:00+08:00"),
            ("2026-01-08T09:01:00+08:00", "2026-01-12T21:01:00+08:00"),
        ]:
            with self.subTest(early=early, d7=d7):
                bundle = operations_fixture()
                bundle["performance_snapshots"][0]["as_of"] = early
                bundle["performance_snapshots"][1]["as_of"] = d7
                self.assertEqual(CHECK.contract_errors(bundle, legacy_fixture()), [])

    def test_content_no_signal_cannot_move_to_business_domain(self) -> None:
        bundle = operations_fixture()
        bundle["reviews"][1]["signal_domain"] = "business"
        errors = CHECK.contract_errors(bundle, legacy_fixture())
        self.assertTrue(any("content" in error for error in errors))

    def test_cross_flow_visual_hard_gate_contract_passes(self) -> None:
        self.assertEqual(CHECK.visual_hard_gate_contract_errors(), [])

    def test_cross_flow_visual_hard_gate_fails_when_recipe_gate_is_removed(self) -> None:
        recipes = load_json(ROOT / "recipes" / "self-media-recipes.v1.json")
        target = next(
            row for row in recipes["recipes"] if row["recipe_id"] == "case-video-candidate"
        )
        target["quality_gates"].remove("visual-typography-hard-gate")
        errors = CHECK.visual_hard_gate_contract_errors(recipes=recipes)
        self.assertTrue(any("case-video-candidate" in error for error in errors))

    def test_cross_flow_visual_hard_gate_fails_when_profile_is_missing(self) -> None:
        policy = load_json(CHECK.TYPOGRAPHY_POLICY_PATH)
        policy["profiles"].pop("vertical_profile_3_4")
        errors = CHECK.visual_hard_gate_contract_errors(typography_policy=policy)
        self.assertTrue(any("vertical_profile_3_4" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
