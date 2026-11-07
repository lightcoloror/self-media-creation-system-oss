from __future__ import annotations

import copy
import importlib.util
import json
import os
import shutil
import unittest
import uuid
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


TIMING = load_module("short_video_timing_evidence", ROOT / "scripts" / "short_video_timing_evidence.py")
STORY = load_module("story_design_gate_for_timing_test", ROOT / "scripts" / "story_design_gate.py")
FIXTURE = ROOT / "fixtures" / "short-video-timing-evidence-v1" / "synthetic-prerecord.input.json"
FINAL_FIXTURE = ROOT / "fixtures" / "short-video-timing-evidence-v1" / "synthetic-final-cut.input.json"
STORY_INPUT = ROOT / "fixtures" / "story-design-card-v1" / "synthetic.input.json"


class ShortVideoTimingEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        base = Path(os.environ.get("TEST_TMP_ROOT", str(ROOT / "tests" / ".runtime")))
        self.runtime = base / ("timing-evidence-" + uuid.uuid4().hex)
        self.runtime.mkdir(parents=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.runtime)

    @staticmethod
    def load(path: Path = FIXTURE) -> dict:
        return json.loads(path.read_text(encoding="utf-8"))

    def write(self, name: str, value: dict) -> Path:
        path = self.runtime / name
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return path

    def ref(self, path: Path, owner: str = "self-media-creation-system") -> dict:
        base = ROOT if owner == "self-media-creation-system" else TIMING.STUDIO
        return {"owner": owner, "path": path.resolve().relative_to(base.resolve()).as_posix(), "sha256": TIMING.sha256_file(path)}

    def assert_code(self, value: dict, code: str) -> None:
        path = self.write("invalid.input.json", value)
        with self.assertRaises(TIMING.TimingEvidenceError) as caught:
            TIMING.create_receipt(path)
        self.assertEqual(code, caught.exception.code)

    def test_two_stages_are_byte_stable_and_distinct(self) -> None:
        result = TIMING.check()
        self.assertEqual("passed", result["status"])
        self.assertTrue(result["prerecord_does_not_prove_final_cut"])
        prerecord = TIMING.create_receipt(FIXTURE)
        final = TIMING.create_receipt(FINAL_FIXTURE)
        self.assertEqual("prerecording-script", prerecord["stage"])
        self.assertIsNone(prerecord["media_binding"])
        self.assertEqual("observed-read-aloud-timecode", prerecord["duration_verification"])
        self.assertEqual("final-cut", final["stage"])
        self.assertIsNotNone(final["media_binding"])
        self.assertEqual("synthetic-fixture-declared", final["duration_verification"])
        self.assertNotEqual(prerecord["evidence_id"], final["evidence_id"])
        self.assertFalse(any(final["authority"].values()))
        self.assertEqual(2, prerecord["observed_metrics"]["thresholds"]["minimum_information_advances"])

    def test_actual_observed_thresholds_fail_closed(self) -> None:
        cases = []
        value = self.load()
        value["timeline"][0]["start_seconds"] = 2.1
        cases.append((value, "audience_stake_too_late"))
        value = self.load()
        value["timeline"][1]["start_seconds"] = 18
        value["timeline"][1]["end_seconds"] = 22
        value["timeline"][2]["start_seconds"] = 22
        cases.append((value, "first_advance_too_late"))
        value = self.load()
        value["timeline"][5]["start_seconds"] = 55
        value["timeline"][5]["end_seconds"] = 59
        cases.append((value, "information_advance_gap_too_long"))
        value = self.load()
        for row in value["timeline"]:
            row["roles"] = [role for role in row["roles"] if role != "main-payoff"]
        value["timeline"][-1]["roles"].append("main-payoff")
        cases.append((value, "main_payoff_too_late"))
        value = self.load()
        payoff = next(row for row in value["timeline"] if "main-payoff" in row["roles"])
        payoff["roles"] = ["main-payoff"]
        value["timeline"] = [value["timeline"][0], payoff]
        cases.append((value, "timing_role_missing"))
        for candidate, code in cases:
            self.assert_code(candidate, code)

    def test_timeline_must_bind_exact_script_and_observed_words(self) -> None:
        value = self.load()
        value["timeline"][0]["script_anchor"] = "脚本中不存在的句子"
        self.assert_code(value, "script_anchor_unbound")
        value = self.load()
        value["timeline"][0]["observed_text"] = "说了另一句话"
        self.assert_code(value, "observed_anchor_unbound")
        value = self.load()
        value["script_binding"]["sha256"] = "0" * 64
        self.assert_code(value, "source_hash_drift")

    def test_prerecord_and_final_cut_evidence_cannot_be_substituted(self) -> None:
        value = self.load()
        value["stage"] = "final-cut"
        self.assert_code(value, "schema_invalid")
        value = self.load(FINAL_FIXTURE)
        value["media_binding"]["duration_seconds"] = 87
        self.assert_code(value, "media_duration_drift")

    def test_real_final_cut_duration_must_come_from_ffprobe(self) -> None:
        value = self.load(FINAL_FIXTURE)
        value["synthetic_only"] = False
        expected = {
            "sha256": value["media_binding"]["sha256"],
            "duration_seconds": value["media_binding"]["duration_seconds"],
            "media_copy_stored": False,
        }
        path = self.write("real-final-cut.input.json", value)
        with mock.patch.object(TIMING, "probe_media_file", return_value=expected) as probe:
            receipt = TIMING.create_receipt(path)
        probe.assert_called_once()
        self.assertEqual("ffprobe-observed", receipt["duration_verification"])

        expected["duration_seconds"] += 1
        with mock.patch.object(TIMING, "probe_media_file", return_value=expected):
            with self.assertRaises(TIMING.TimingEvidenceError) as caught:
                TIMING.create_receipt(path)
        self.assertEqual("media_probe_duration_drift", caught.exception.code)

    def test_continuity_claim_needs_an_actual_anchor_when_surfaced(self) -> None:
        value = self.load()
        value["continuity_binding"] = {
            "surface_mode": "spoken",
            "timeline_entry_id": "beat-09",
            "assessment": "explicitly-delivered",
        }
        self.assert_code(value, "continuity_binding_missing")
        value["timeline"][-1]["roles"].append("continuity-promise")
        receipt = TIMING.create_receipt(self.write("explicit-continuity.input.json", value))
        self.assertEqual("explicitly-delivered", receipt["continuity_result"]["status"])

    def test_story_route_binds_the_exact_story_card_and_tighter_profile(self) -> None:
        story_input = json.loads(STORY_INPUT.read_text(encoding="utf-8"))
        story_input["content_id"] = self.load()["content_id"]
        story_input["timing_design"]["target_duration_seconds"] = 90
        story_input["timing_design"]["main_payoff_by_completion_ratio"] = 0.75
        story_receipt = STORY.create_receipt_from_value(story_input)
        story_path = self.write("story-card.json", story_receipt)
        value = self.load()
        value["structure_route"] = "story-arc"
        value["story_design_binding"] = self.ref(story_path)
        receipt = TIMING.create_receipt(self.write("story-route.input.json", value))
        self.assertEqual(self.ref(story_path), receipt["story_design_binding"])
        self.assertEqual(12, receipt["observed_metrics"]["thresholds"]["information_advance_gap_max_seconds"])
        single_advance = copy.deepcopy(value)
        payoff = next(row for row in single_advance["timeline"] if "main-payoff" in row["roles"])
        payoff.update(start_seconds=4, end_seconds=12)
        single_advance.update(measured_duration_seconds=14, timeline=[single_advance["timeline"][0], payoff])
        self.assert_code(single_advance, "information_advance_count_low")
        story_receipt["content_id"] = "different-content"
        story_receipt["receipt_payload_sha256"] = STORY.canonical_sha256({k: v for k, v in story_receipt.items() if k != "receipt_payload_sha256"})
        changed = self.write("wrong-story-card.json", story_receipt)
        value["story_design_binding"] = self.ref(changed)
        self.assert_code(value, "content_identity_drift")

    def test_receipt_reloads_hash_bound_input(self) -> None:
        path = self.write("stable.input.json", self.load())
        receipt = TIMING.create_receipt(path)
        TIMING.validate_receipt_value(receipt)
        changed = self.load()
        changed["timeline"][0]["observed_text"] += " changed"
        self.write("stable.input.json", changed)
        with self.assertRaises(TIMING.TimingEvidenceError) as caught:
            TIMING.validate_receipt_value(receipt)
        self.assertEqual("source_hash_drift", caught.exception.code)


if __name__ == "__main__":
    unittest.main()
