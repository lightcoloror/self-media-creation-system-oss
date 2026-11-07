from __future__ import annotations

import copy
import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "story_five_question_adapter.py"
SPEC = importlib.util.spec_from_file_location("story_five_question_adapter", SCRIPT)
assert SPEC and SPEC.loader
ADAPTER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ADAPTER)


class StoryFiveQuestionAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.base = ADAPTER.load_json(ADAPTER.FIXTURE)

    def assert_blocked(self, value: dict, code: str) -> None:
        with self.assertRaises(ADAPTER.FiveQuestionError) as caught:
            ADAPTER.create_receipt_from_value(value)
        self.assertEqual(caught.exception.code, code)

    def test_valid_mapping_is_deterministic_and_reuses_story_card(self) -> None:
        first = ADAPTER.create_receipt_from_value(self.base)
        second = ADAPTER.create_receipt_from_value(self.base)
        self.assertEqual(ADAPTER.canonical_bytes(first), ADAPTER.canonical_bytes(second))
        self.assertEqual(first["target_contract"], "story-design-card.v1")
        self.assertEqual(first["field_mapping"], ADAPTER.FIELD_MAPPING)
        self.assertEqual(first["artifact_status"], "candidate-only")
        self.assertFalse(any(first["authority"].values()))
        ADAPTER.validate_receipt(first)

    def test_invented_obstacle_fails_closed(self) -> None:
        value = copy.deepcopy(self.base)
        value["answers"]["obstacle"]["text"] = "An obstacle invented outside the Story Design Card."
        self.assert_blocked(value, "answer_not_in_story_card")

    def test_invented_stakes_fails_closed(self) -> None:
        value = copy.deepcopy(self.base)
        value["answers"]["stakes"]["text"] = "A fabricated severe consequence."
        self.assert_blocked(value, "answer_not_in_story_card")

    def test_fact_reference_drift_fails_closed(self) -> None:
        value = copy.deepcopy(self.base)
        value["answers"]["goal"]["fact_refs"] = ["fact-99"]
        self.assert_blocked(value, "answer_fact_ref_drift")

    def test_story_card_hash_drift_fails_closed(self) -> None:
        value = copy.deepcopy(self.base)
        value["story_card_input_sha256"] = "0" * 64
        self.assert_blocked(value, "story_card_hash_drift")

    def test_negative_fixture_catalog_is_bounded(self) -> None:
        fixture = json.loads((ROOT / "fixtures" / "story-five-question-adapter-v1" / "negative-cases.json").read_text(encoding="utf-8"))
        self.assertEqual(len(fixture["cases"]), 4)
        self.assertTrue(all(item["expected_code"] for item in fixture["cases"]))


if __name__ == "__main__":
    unittest.main()
