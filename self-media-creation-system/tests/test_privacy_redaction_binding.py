from __future__ import annotations

import hashlib
import json
import shutil
import sys
import unittest
from pathlib import Path
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
MVP_ROOT = ROOT.parent / "ai-video-tools-20260708" / "mvp-video-pipeline"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(MVP_ROOT / "src"))

if not (MVP_ROOT / "src/video_creation_pipeline/contract_io.py").is_file():
    raise unittest.SkipTest("Full MVP redaction owner is not public; integration remains unverified")

import privacy_redaction_binding as BINDING  # noqa: E402
from video_creation_pipeline.contract_io import artifact_reference, payload_sha256  # noqa: E402


class PrivacyRedactionBindingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = ROOT / ".runtime" / f"privacy-binding-{uuid4().hex}"
        self.root.mkdir(parents=True)
        for name, payload in {
            "source.mp4": b"source",
            "candidate.mp4": b"candidate",
            "subjects.json": b"{}",
            "source.edl": b"edl",
            "speaker.json": b"{}",
            "faces.json": b"{}",
            "identities.json": b"{}",
            "windows.json": b"{}",
            "masks.json": b"{}",
            "voices.json": b"{}",
            "motions.json": b"{}",
            "job.json": b"{}",
            "receipt.json": b"{}",
        }.items():
            (self.root / name).write_bytes(payload)
        self.decision_path = self.root / "decision.json"
        self.zones_path = self.root / "zones.json"
        self.binding_path = self.root / "binding.json"
        self._write_decision()
        self._write_zones(frames=[0, 1, 2])
        self._write_binding()

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def _ref(self, name: str) -> dict:
        path = self.root / name
        return {
            "path": name,
            "expected_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }

    def _write_decision(self) -> None:
        decision = {
            "schema_version": "self-media-video-privacy-treatment-decision.v1",
            "decision_id": "privacy-decision-binding-001",
            "revision": 1,
            "supersedes_decision_sha256": None,
            "recorded_at": "2026-08-29T10:00:00Z",
            "recorded_by_role": "human_editor",
            "customer_choice_status": "confirmed",
            "preview_policy": "customer_preview",
            "authorization_overlay_policy": "required_with_face_window",
            "source_media": self._ref("source.mp4"),
            "subject_manifest": self._ref("subjects.json"),
            "local_edit_state": {
                "source_edl": self._ref("source.edl"),
                "speaker_segments": self._ref("speaker.json"),
                "face_tracks": self._ref("faces.json"),
                "identity_reference_manifest": self._ref("identities.json"),
                "visible_window_manifest": self._ref("windows.json"),
                "mask_recipe_catalog": self._ref("masks.json"),
                "voice_recipe_catalog": self._ref("voices.json"),
                "motion_recipe_catalog": self._ref("motions.json"),
            },
            "subjects": [
                {
                    "subject_ref": "customer-a",
                    "role": "customer_interviewee",
                    "speaker_segment_refs": ["speaker-a"],
                    "face_track_refs": ["human-face-a"],
                    "identity_reference_refs": ["identity-a"],
                    "visible_window_refs": ["window-a"],
                    "identity_match_status": "confirmed",
                    "voice_treatment": {"action": "keep_original"},
                    "face_treatment": {"action": "mosaic", "local_recipe_ref": "mask/soft"},
                }
            ],
            "customer_contact_performed_by_system": False,
            "raw_customer_text_stored": False,
        }
        self.decision_path.write_text(json.dumps(decision), encoding="utf-8")

    def _write_zones(self, *, frames: list[int]) -> None:
        zones = {
            "schema": "video_creation_pipeline.privacy_exclusion_zones.v1",
            "source_media": artifact_reference(self.root / "source.mp4", "source"),
            "redacted_media": artifact_reference(self.root / "candidate.mp4", "candidate"),
            "source_redaction_job": artifact_reference(self.root / "job.json", "job"),
            "source_redaction_receipt": artifact_reference(self.root / "receipt.json", "receipt"),
            "coordinate_space": "redaction_input_normalized",
            "media_clock": {"fps": 30.0, "frame_count": 3, "width": 1080, "height": 1920, "duration_s": 0.1},
            "detector": {
                "tool": "SentryBlur",
                "source_commit": "ded52d269b6e8e19dbbaf79f353426da3a228a98",
                "model_hash": "a" * 64,
                "target_types": ["face"],
                "same_invocation_as_redaction": True,
            },
            "redaction_parameters": {"dilation_px": 16, "temporal_window_frames": 3},
            "scene_cuts": [],
            "tracks": [
                {
                    "track_id": "anonymous-face-a",
                    "target_type": "face",
                    "identity_claimed": False,
                    "zones": [
                        {
                            "frame_index": frame,
                            "pts_s": frame / 30,
                            "confidence": 0.9,
                            "source": "temporal_union",
                            "raw_rect": {"x": 0.1, "y": 0.1, "width": 0.2, "height": 0.2},
                            "effective_rect": {"x": 0.08, "y": 0.08, "width": 0.24, "height": 0.24},
                            "visible": True,
                        }
                        for frame in frames
                    ],
                }
            ],
            "coverage": {
                "status": "complete" if len(frames) == 3 else "review_required",
                "covered_frame_count": len(frames),
                "uncovered_spans": [] if len(frames) == 3 else [{"start_frame": 1, "end_frame": 1, "reason": "fixture gap"}],
                "review_required": len(frames) != 3,
            },
            "authority_boundary": {
                "candidate_only": True,
                "identity_recognition_performed": False,
                "layout_authority": "semantic_motion_plan",
                "publish_allowed": False,
                "final_privacy_rescan_required": True,
            },
        }
        zones["zones_sha256"] = payload_sha256(zones, "zones_sha256")
        self.zones_path.write_text(json.dumps(zones), encoding="utf-8")

    def _write_binding(self) -> None:
        binding = {
            "schema_version": "self-media-privacy-redaction-binding.v1",
            "binding_id": "privacy-binding-fixture-001",
            "created_at": "2026-08-29T10:30:00Z",
            "decision": self._ref("decision.json"),
            "privacy_zones": self._ref("zones.json"),
            "candidate": self._ref("candidate.mp4"),
            "visible_window_manifest": self._ref("windows.json"),
            "subject_bindings": [
                {
                    "subject_ref": "customer-a",
                    "human_face_track_refs": ["human-face-a"],
                    "anonymous_zone_track_refs": ["anonymous-face-a"],
                    "visible_windows": [{"visible_window_ref": "window-a", "start_frame": 0, "end_frame": 2}],
                    "treatment": "mosaic",
                }
            ],
            "authority_boundary": {
                "identity_binding_source": "human_reviewed_subject_manifest",
                "automatic_identity_inference": False,
                "candidate_only": True,
                "publish_allowed": False,
            },
        }
        self.binding_path.write_text(json.dumps(binding), encoding="utf-8")

    def test_human_subject_windows_are_bound_to_every_redacted_frame(self) -> None:
        receipt = BINDING.evaluate(
            self.binding_path,
            self.root,
            MVP_ROOT,
            evaluated_at="2026-08-29T11:00:00Z",
        )
        self.assertEqual("passed", receipt["status"])
        self.assertEqual(3, receipt["subject_results"][0]["covered_frame_count"])
        self.assertFalse(receipt["authority_boundary"]["identity_inferred_by_system"])

    def test_one_uncovered_frame_fails_closed(self) -> None:
        self._write_zones(frames=[0, 2])
        self._write_binding()
        with self.assertRaises(BINDING.PrivacyBindingError) as context:
            BINDING.evaluate(self.binding_path, self.root, MVP_ROOT)
        self.assertEqual("redaction_window_uncovered", context.exception.code)


if __name__ == "__main__":
    unittest.main()
