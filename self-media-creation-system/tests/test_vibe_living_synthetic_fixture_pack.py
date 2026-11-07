from __future__ import annotations

import copy
import importlib.util
import json
import shutil
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "vibe_living_synthetic_fixture_pack.py"
SPEC = importlib.util.spec_from_file_location("vibe_living_synthetic_fixture_pack", MODULE_PATH)
assert SPEC and SPEC.loader
PACK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PACK)


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class VibeLivingSyntheticFixturePackTests(unittest.TestCase):
    def test_default_pack_validates_and_reuses_canonical_contracts(self) -> None:
        self.assertEqual([], PACK.validate_pack(PACK.DEFAULT_OUTPUT))
        manifest = load_json(PACK.DEFAULT_OUTPUT / "consumer-manifest.json")
        self.assertTrue(manifest["synthetic_only"])
        self.assertEqual("draft_only", manifest["mode"])
        self.assertTrue(manifest["no_parallel_schema_created"])
        self.assertEqual(5, len(manifest["questions"]))
        self.assertEqual(3, len(manifest["publication_feedback_cases"]))

    def test_material_and_draft_share_stable_content_id(self) -> None:
        manifest = load_json(PACK.DEFAULT_OUTPUT / "consumer-manifest.json")
        for entry in manifest["questions"]:
            material = load_json(PACK.DEFAULT_OUTPUT / entry["material_ref"])
            draft = load_json(PACK.DEFAULT_OUTPUT / entry["content_draft_ref"])
            self.assertEqual(entry["content_id"], material["content_id"])
            self.assertEqual(material["content_id"], draft["content_id"])
            self.assertEqual("candidate", material["status"])
            self.assertEqual("draft", draft["status"])
            self.assertEqual({"boundary": "manual-only", "receipts": []}, draft["publication"])

    def test_signal_layers_are_strictly_separated(self) -> None:
        manifest = load_json(PACK.DEFAULT_OUTPUT / "consumer-manifest.json")
        records = {
            entry["case_id"]: load_json(PACK.DEFAULT_OUTPUT / entry["feedback_handoff_ref"])
            for entry in manifest["publication_feedback_cases"]
        }
        no_signal = records["pf-content-no-signal"]
        ordinary = records["pf-ordinary-content-engagement"]
        explicit = records["pf-explicit-business-signal"]
        self.assertEqual("content_observation", no_signal["signal_layer"])
        self.assertFalse(no_signal["crm_candidate"]["eligible"])
        self.assertEqual("content_observation", ordinary["signal_layer"])
        self.assertFalse(ordinary["relationship_signal"]["eligible"])
        self.assertFalse(ordinary["crm_candidate"]["eligible"])
        self.assertEqual("crm_candidate", explicit["signal_layer"])
        self.assertTrue(explicit["manual_confirmation_required"])
        self.assertFalse(explicit["crm_candidate"]["confirmed"])
        self.assertEqual("pending_human_confirmation", explicit["crm_candidate"]["status"])

    def test_all_negative_cases_fail_closed_with_expected_code(self) -> None:
        manifest = load_json(PACK.DEFAULT_OUTPUT / "consumer-manifest.json")
        records = {
            entry["case_id"]: load_json(PACK.DEFAULT_OUTPUT / entry["feedback_handoff_ref"])
            for entry in manifest["publication_feedback_cases"]
        }
        descriptors = load_json(PACK.DEFAULT_OUTPUT / manifest["negative_cases_ref"])
        for case in descriptors["cases"]:
            with self.subTest(case=case["id"]):
                mutated = PACK.apply_negative_mutation(records[case["base_case"]], case["mutation"])
                with self.assertRaises(PACK.PackError) as context:
                    PACK.validate_feedback_record(mutated)
                self.assertEqual(case["expected_code"], context.exception.code)

    def test_double_generation_is_byte_for_byte_stable(self) -> None:
        run_a = ROOT / "tests" / ".tmp-vibe-living-test-a"
        run_b = ROOT / "tests" / ".tmp-vibe-living-test-b"
        try:
            PACK.generate_pack(PACK.DEFAULT_SEED, run_a)
            PACK.generate_pack(PACK.DEFAULT_SEED, run_b)
            self.assertEqual(PACK.file_map(run_a), PACK.file_map(run_b))
        finally:
            for path in (run_a, run_b):
                shutil.rmtree(path, ignore_errors=True)

    def test_crm_candidate_cannot_be_auto_confirmed(self) -> None:
        manifest = load_json(PACK.DEFAULT_OUTPUT / "consumer-manifest.json")
        entry = next(
            item for item in manifest["publication_feedback_cases"]
            if item["case_id"] == "pf-explicit-business-signal"
        )
        record = load_json(PACK.DEFAULT_OUTPUT / entry["feedback_handoff_ref"])
        mutated = copy.deepcopy(record)
        mutated["crm_candidate"]["confirmed"] = True
        with self.assertRaises(PACK.PackError) as context:
            PACK.validate_feedback_record(mutated)
        self.assertEqual("crm_candidate_manual_gate_required", context.exception.code)


if __name__ == "__main__":
    unittest.main()
