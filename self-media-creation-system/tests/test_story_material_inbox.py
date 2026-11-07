from __future__ import annotations

import copy
import importlib.util
import json
import unittest
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "story_material_inbox.py"
SPEC = importlib.util.spec_from_file_location("story_material_inbox", SCRIPT)
assert SPEC and SPEC.loader
INBOX = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(INBOX)
FIXTURE = ROOT / "fixtures" / "story-material-observation-v1" / "synthetic.input.json"


class StoryMaterialInboxTests(unittest.TestCase):
    def load(self) -> dict:
        return json.loads(FIXTURE.read_text(encoding="utf-8"))

    def assert_code(self, value: dict, code: str) -> None:
        with self.assertRaises(INBOX.StoryMaterialError) as caught:
            INBOX.validate_input(value)
        self.assertEqual(code, caught.exception.code)

    def test_ready_fixture_is_deterministic_candidate_only(self) -> None:
        one = INBOX.create_record(FIXTURE)
        two = INBOX.create_record(FIXTURE)
        self.assertEqual(one, two)
        self.assertEqual("ready-for-story-design", one["story_route_readiness"])
        self.assertEqual("candidate-only", one["content_status"])
        self.assertFalse(any(one["authority"].values()))
        INBOX.validate_record(one)

    def test_missing_core_field_stays_incomplete(self) -> None:
        value = self.load()
        value["fields"]["hardest_choice"] = {"status": "unknown", "text": None, "fact_refs": []}
        record = INBOX.create_record_from_value(value)
        self.assertEqual("incomplete", record["story_route_readiness"])
        self.assertEqual(["hardest_choice"], record["missing_story_fields"])

    def test_sensory_detail_is_optional_but_cannot_be_invented(self) -> None:
        value = self.load()
        self.assertEqual("ready-for-story-design", INBOX.create_record_from_value(value)["story_route_readiness"])
        value["fields"]["sensory_detail"] = {"status": "supplied", "text": "a vivid invented detail", "fact_refs": []}
        self.assert_code(value, "supplied_field_missing_evidence")

    def test_privacy_and_authorization_fail_closed(self) -> None:
        value = self.load()
        value["privacy_status"] = "blocked"
        self.assert_code(value, "privacy_not_cleared")
        value = self.load()
        value["story_source_mode"] = "authorized-interview"
        self.assert_code(value, "interview_authorization_missing")
        value = self.load()
        value["quotation"] = {"mode": "confirmed-exact", "text": "synthetic quote", "fact_refs": ["fact-01"]}
        self.assert_code(value, "exact_quote_authorization_missing")

    def test_append_is_idempotent_and_hash_bound(self) -> None:
        record = INBOX.create_record(FIXTURE)
        runtime_root = ROOT / "tests" / ".runtime" / "story-material-tests"
        runtime_root.mkdir(parents=True, exist_ok=True)
        ledger = runtime_root / f"story-material-{uuid.uuid4().hex}.jsonl"
        try:
            self.assertEqual("recorded", INBOX.append_record(ledger, record))
            self.assertEqual("already-recorded", INBOX.append_record(ledger, record))
            drift = copy.deepcopy(record)
            drift["record_sha256"] = "0" * 64
            with self.assertRaises(INBOX.StoryMaterialError) as caught:
                INBOX.append_record(ledger, drift)
            self.assertEqual("material_id_collision", caught.exception.code)
        finally:
            if ledger.exists():
                ledger.unlink()

    def test_unknown_fields_and_recomputed_semantic_drift_are_rejected(self) -> None:
        value = self.load()
        value["unexpected"] = True
        self.assert_code(value, "invalid_shape")
        record = INBOX.create_record(FIXTURE)
        record["story_route_readiness"] = "incomplete"
        unsigned = copy.deepcopy(record)
        unsigned.pop("record_sha256")
        record["record_sha256"] = INBOX.canonical_sha256(unsigned)
        with self.assertRaises(INBOX.StoryMaterialError) as caught:
            INBOX.validate_record(record)
        self.assertEqual("record_semantic_drift", caught.exception.code)


if __name__ == "__main__":
    unittest.main()
