from __future__ import annotations

import copy
import importlib.util
import json
import shutil
import unittest
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "video_privacy_treatment.py"
SPEC = importlib.util.spec_from_file_location("video_privacy_treatment", SCRIPT)
assert SPEC and SPEC.loader
TREATMENT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TREATMENT)


class VideoPrivacyTreatmentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = ROOT / "outputs" / "test-temp" / ("privacy-treatment-" + uuid.uuid4().hex)
        self.root.mkdir(parents=True, exist_ok=True)
        self.refs: dict[str, dict[str, str]] = {}
        for name, content in {
            "source.mp4": b"synthetic source media",
            "subjects.json": b'{"subjects":["subject-a"]}',
            "source.edl": b"synthetic edl",
            "speaker-segments.json": b'{"speaker":"speaker-a"}',
            "face-tracks.json": b'{"face":"face-a"}',
            "identity-references.json": b'{"identity":"identity-a"}',
            "visible-windows.json": b'{"window":"window-a"}',
            "mask-recipes.json": b'{"recipe":"mask-soft"}',
            "voice-recipes.json": b'{"recipe":"cantonese-male-f0"}',
            "motion-recipes.json": b'{"recipe":"motion-default"}',
            "candidate.mp4": b"synthetic candidate media",
            "privacy-render-qa.json": b'{"qa":"synthetic-frame-review"}',
        }.items():
            path = self.root / name
            path.write_bytes(content)
            self.refs[name] = {
                "path": name,
                "expected_sha256": TREATMENT.sha256_file(path),
            }

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def _decision(self, *, undecided: bool) -> dict:
        voice_action = "undecided" if undecided else "convert_same_gender_range"
        face_action = "undecided" if undecided else "mosaic"
        voice_treatment = {"action": voice_action}
        face_treatment = {"action": face_action}
        if not undecided:
            voice_treatment["local_recipe_ref"] = "voice/cantonese-male-same-range-f0"
            face_treatment["local_recipe_ref"] = "mask/face-track-soft-mosaic"
        return {
            "schema_version": "self-media-video-privacy-treatment-decision.v1",
            "decision_id": "privacy-decision-001",
            "revision": 1,
            "supersedes_decision_sha256": None,
            "recorded_at": "2026-08-24T12:00:00Z",
            "recorded_by_role": "human_editor",
            "customer_choice_status": "undecided" if undecided else "confirmed",
            "preview_policy": "internal_preview_only" if undecided else "customer_preview",
            "authorization_overlay_policy": "required_with_face_window",
            "source_media": self.refs["source.mp4"],
            "subject_manifest": self.refs["subjects.json"],
            "local_edit_state": {
                "source_edl": self.refs["source.edl"],
                "speaker_segments": self.refs["speaker-segments.json"],
                "face_tracks": self.refs["face-tracks.json"],
                "identity_reference_manifest": self.refs["identity-references.json"],
                "visible_window_manifest": self.refs["visible-windows.json"],
                "mask_recipe_catalog": self.refs["mask-recipes.json"],
                "voice_recipe_catalog": self.refs["voice-recipes.json"],
                "motion_recipe_catalog": self.refs["motion-recipes.json"],
            },
            "subjects": [
                {
                    "subject_ref": "subject-a",
                    "role": "customer_interviewee",
                    "speaker_segment_refs": ["speaker-a"],
                    "face_track_refs": ["face-a"],
                    "identity_reference_refs": [] if undecided else ["identity-a"],
                    "visible_window_refs": [] if undecided else ["window-a"],
                    "identity_match_status": "undecided" if undecided else "confirmed",
                    "voice_treatment": voice_treatment,
                    "face_treatment": face_treatment,
                }
            ],
            "customer_contact_performed_by_system": False,
            "raw_customer_text_stored": False,
        }

    def _write_decision(self, *, undecided: bool) -> Path:
        path = self.root / "decision.json"
        path.write_text(json.dumps(self._decision(undecided=undecided)), encoding="utf-8")
        return path

    def _review(self, decision_path: Path, *, result: str, changes: list[dict] | None = None) -> dict:
        return {
            "schema_version": "self-media-customer-video-effect-review.v1",
            "review_id": "effect-review-001",
            "reviewed_at": "2026-08-24T12:30:00Z",
            "recorded_by_role": "human_project_owner",
            "candidate": {
                **self.refs["candidate.mp4"],
                "duration_seconds": 60.0,
            },
            "decision_sha256": TREATMENT.sha256_file(decision_path),
            "privacy_render_qa": {
                "qa_id": "privacy-qa-001",
                "candidate_sha256": self.refs["candidate.mp4"]["expected_sha256"],
                "status": "passed",
                "target_faces_complete": True,
                "non_target_faces_unaffected": True,
                "authorization_overlay_status": "passed",
                "window_checks": [
                    {
                        "subject_ref": "subject-a",
                        "visible_window_ref": "window-a",
                        "pre_entry_non_target_clear": "passed",
                        "first_visible_target_protected": "passed",
                        "midpoint_target_protected": "passed",
                        "last_visible_target_protected": "passed",
                        "post_exit_non_target_clear": "passed",
                    }
                ]
                if not self._decision_is_undecided(decision_path)
                else [],
                "verification_artifact": self.refs["privacy-render-qa.json"],
            },
            "result": result,
            "requested_changes": changes or [],
            "customer_contact_performed_by_system": False,
            "raw_customer_text_stored": False,
        }

    def _decision_is_undecided(self, decision_path: Path) -> bool:
        return json.loads(decision_path.read_text(encoding="utf-8"))["customer_choice_status"] == "undecided"

    def _write_review(self, review: dict) -> Path:
        path = self.root / "review.json"
        path.write_text(json.dumps(review), encoding="utf-8")
        return path

    def test_undecided_choices_remain_internal_preview_only(self) -> None:
        decision_path = self._write_decision(undecided=True)
        review_path = self._write_review(self._review(decision_path, result="confirmed"))
        gate = TREATMENT.evaluate(
            decision_path,
            review_path,
            self.root,
            evaluated_at="2026-08-24T13:00:00Z",
        )
        self.assertEqual(gate["status"], "internal_preview_only")
        self.assertFalse(gate["manual_publication_eligible"])
        self.assertFalse(gate["automatic_publish"])
        self.assertIsNone(gate["rework_request"])

    def test_explicit_same_gender_voice_and_mosaic_can_pass_exact_candidate(self) -> None:
        decision_path = self._write_decision(undecided=False)
        review_path = self._write_review(self._review(decision_path, result="confirmed"))
        gate = TREATMENT.evaluate(decision_path, review_path, self.root)
        self.assertEqual(gate["status"], "customer_confirmed_candidate")
        self.assertTrue(gate["manual_publication_eligible"])
        self.assertFalse(gate["automatic_publish"])

    def test_requested_changes_become_local_recipe_limited_rework(self) -> None:
        decision_path = self._write_decision(undecided=False)
        changes = [
            {
                "change_id": "voice-12-18",
                "subject_ref": "subject-a",
                "kind": "voice",
                "start_seconds": 12.0,
                "end_seconds": 18.0,
                "requested_action": "reduce conversion strength and preserve original F0",
                "reason_summary": "customer wants a voice closer to the original",
            },
            {
                "change_id": "mask-21-24",
                "subject_ref": "subject-a",
                "kind": "mask_strength",
                "start_seconds": 21.0,
                "end_seconds": 24.0,
                "requested_action": "increase mosaic strength",
                "reason_summary": "side profile is still recognizable",
            },
            {
                "change_id": "motion-33-36",
                "subject_ref": "subject-a",
                "kind": "motion",
                "start_seconds": 33.0,
                "end_seconds": 36.0,
                "requested_action": "restore the stored motion recipe",
                "local_recipe_ref": "motion/original-callout-v2",
                "reason_summary": "late overlay change should not affect other shots",
            },
        ]
        review_path = self._write_review(
            self._review(decision_path, result="request_changes", changes=changes)
        )
        gate = TREATMENT.evaluate(decision_path, review_path, self.root)
        self.assertEqual(gate["status"], "limited_rework_required")
        self.assertFalse(gate["manual_publication_eligible"])
        rework = gate["rework_request"]
        self.assertEqual(rework["recalculation_scope"], "changed_windows_only")
        self.assertEqual(rework["frozen_scope"], "all_unlisted_windows")
        self.assertEqual(len(rework["changed_windows"]), 3)
        self.assertEqual(
            rework["changed_windows"][0]["local_recipe_ref"],
            "voice/cantonese-male-same-range-f0",
        )
        self.assertEqual(
            rework["changed_windows"][1]["local_recipe_ref"],
            "mask/face-track-soft-mosaic",
        )
        self.assertTrue(rework["local_edit_state"]["source_edl"])
        self.assertIn("audio_lock", rework["downstream_invalidations"])
        self.assertIn("privacy_review", rework["downstream_invalidations"])
        self.assertIn("motion_timing", rework["downstream_invalidations"])
        self.assertEqual(rework["review_interface"]["surface"], "targeted-review")
        self.assertTrue(gate["reuse_local_recipes"])

    def test_stale_decision_or_candidate_hash_fails_closed(self) -> None:
        decision_path = self._write_decision(undecided=False)
        review = self._review(decision_path, result="confirmed")
        review["decision_sha256"] = "0" * 64
        review_path = self._write_review(review)
        with self.assertRaises(TREATMENT.PrivacyTreatmentError) as decision_error:
            TREATMENT.evaluate(decision_path, review_path, self.root)
        self.assertEqual(decision_error.exception.code, "decision_hash_mismatch")

        review = self._review(decision_path, result="confirmed")
        review["candidate"]["expected_sha256"] = "0" * 64
        review_path = self._write_review(review)
        with self.assertRaises(TREATMENT.PrivacyTreatmentError) as candidate_error:
            TREATMENT.evaluate(decision_path, review_path, self.root)
        self.assertEqual(candidate_error.exception.code, "source_hash_drift")

    def test_withdrawn_candidate_stops(self) -> None:
        decision_path = self._write_decision(undecided=False)
        review_path = self._write_review(self._review(decision_path, result="withdrawn"))
        gate = TREATMENT.evaluate(decision_path, review_path, self.root)
        self.assertEqual(gate["status"], "withdrawn")
        self.assertFalse(gate["manual_publication_eligible"])
        self.assertIn("customer-withdrew-candidate", gate["stop_reasons"])

    def test_confirmed_mosaic_without_identity_reference_fails_closed(self) -> None:
        decision = self._decision(undecided=False)
        decision["subjects"][0]["identity_reference_refs"] = []
        decision_path = self.root / "decision.json"
        decision_path.write_text(json.dumps(decision), encoding="utf-8")
        review_path = self._write_review(self._review(decision_path, result="confirmed"))
        with self.assertRaises(TREATMENT.PrivacyTreatmentError) as error:
            TREATMENT.evaluate(decision_path, review_path, self.root)
        self.assertEqual(error.exception.code, "identity_not_confirmed")

    def test_wrong_person_or_missing_boundary_frame_fails_closed(self) -> None:
        decision_path = self._write_decision(undecided=False)
        review = self._review(decision_path, result="confirmed")
        review["privacy_render_qa"]["non_target_faces_unaffected"] = False
        review_path = self._write_review(review)
        with self.assertRaises(TREATMENT.PrivacyTreatmentError) as wrong_person_error:
            TREATMENT.evaluate(decision_path, review_path, self.root)
        self.assertEqual(wrong_person_error.exception.code, "privacy_render_qa_failed")

        review = self._review(decision_path, result="confirmed")
        review["privacy_render_qa"]["window_checks"][0]["first_visible_target_protected"] = "failed"
        review_path = self._write_review(review)
        with self.assertRaises(TREATMENT.PrivacyTreatmentError) as boundary_error:
            TREATMENT.evaluate(decision_path, review_path, self.root)
        self.assertEqual(boundary_error.exception.code, "privacy_render_qa_failed")

    def test_missing_window_qa_cannot_pass(self) -> None:
        decision_path = self._write_decision(undecided=False)
        review = self._review(decision_path, result="confirmed")
        review["privacy_render_qa"]["window_checks"] = []
        review_path = self._write_review(review)
        with self.assertRaises(TREATMENT.PrivacyTreatmentError) as error:
            TREATMENT.evaluate(decision_path, review_path, self.root)
        self.assertEqual(error.exception.code, "privacy_render_qa_failed")

    def test_same_face_track_cannot_be_customer_and_interviewer(self) -> None:
        decision = self._decision(undecided=False)
        decision["subjects"].append(
            {
                "subject_ref": "subject-interviewer",
                "role": "interviewer_creator",
                "speaker_segment_refs": ["speaker-interviewer"],
                "face_track_refs": ["face-a"],
                "identity_reference_refs": ["identity-interviewer"],
                "visible_window_refs": ["window-interviewer"],
                "identity_match_status": "confirmed",
                "voice_treatment": {"action": "keep_original"},
                "face_treatment": {"action": "keep_visible"},
            }
        )
        decision_path = self.root / "decision.json"
        decision_path.write_text(json.dumps(decision), encoding="utf-8")
        review_path = self._write_review(self._review(decision_path, result="confirmed"))
        with self.assertRaises(TREATMENT.PrivacyTreatmentError) as error:
            TREATMENT.evaluate(decision_path, review_path, self.root)
        self.assertEqual(error.exception.code, "decision_inconsistent")

    def test_authorization_overlay_must_match_customer_face_windows(self) -> None:
        decision_path = self._write_decision(undecided=False)
        review = self._review(decision_path, result="confirmed")
        review["privacy_render_qa"]["authorization_overlay_status"] = "failed"
        review_path = self._write_review(review)
        with self.assertRaises(TREATMENT.PrivacyTreatmentError) as error:
            TREATMENT.evaluate(decision_path, review_path, self.root)
        self.assertEqual(error.exception.code, "privacy_render_qa_failed")


if __name__ == "__main__":
    unittest.main()
