"""Schema meta-validation and synthetic payload contract tests for Cover IR v1 and Performance Plan v1."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

import jsonschema

SCHEMAS_DIR = Path(__file__).resolve().parents[1] / "schemas"


def _load_schema(name: str) -> dict:
    return json.loads((SCHEMAS_DIR / name).read_text(encoding="utf-8"))


class CoverAndPerformanceSchemaTests(unittest.TestCase):
    def test_schemas_are_valid_json_sanitized_and_valid_metaschema(self):
        cir = _load_schema("cover-ir.v1.schema.json")
        vpp = _load_schema("video-performance-plan.v1.schema.json")
        self.assertEqual(cir.get("$id"), "https://local.invalid/schemas/cover-ir.v1.schema.json")
        self.assertTrue(cir.get("$id", "").startswith("https://local.invalid/"))

        jsonschema.Draft7Validator.check_schema(cir)
        jsonschema.Draft202012Validator.check_schema(vpp)

    def test_cover_ir_valid_and_negative_cases(self):
        cir = _load_schema("cover-ir.v1.schema.json")
        valid_instance = {
            "schemaVersion": "1.0.0",
            "document": {
                "id": "synthetic_cover_001",
                "revision": 1,
                "updatedAt": "2026-11-22T11:00:00Z",
                "canvas": {"width": 1080, "height": 1440, "aspectRatio": "3:4"},
            },
            "metadata": {
                "topic": "synthetic tutorial cover",
                "track": "track_c_typography_only",
            },
            "assets": [
                {"id": "bg_1", "type": "image", "path": "assets/bg.png"}
            ],
            "layers": [
                {
                    "id": "headline_1",
                    "role": "headline",
                    "type": "text",
                    "zIndex": 1,
                    "position": {"x": 80, "y": 140, "width": 920, "height": 220},
                }
            ],
            "constraints": {
                "platformSafeZones": {
                    "platform": "xhs",
                    "scene": "double_column_feed",
                    "exclusions": [
                        {
                            "id": "top_right_tag",
                            "type": "rect",
                            "level": "hard_block",
                            "normalizedRect": [0.86, 0.02, 0.12, 0.08],
                        }
                    ],
                }
            },
        }
        jsonschema.validate(instance=valid_instance, schema=cir)

        missing_constraints = copy.deepcopy(valid_instance)
        del missing_constraints["constraints"]
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(instance=missing_constraints, schema=cir)

        extra_root = copy.deepcopy(valid_instance)
        extra_root["unexpected_field"] = True
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(instance=extra_root, schema=cir)

    def test_video_performance_plan_valid_and_negative_cases(self):
        vpp = _load_schema("video-performance-plan.v1.schema.json")
        ref_a = {"path": "script.md", "sha256": "a" * 64}
        area_entry = {"decision": "use", "reason": "synthetic check", "cue_ids": ["cue_1"]}
        valid_plan = {
            "schema": "self-media.performance-plan.v1",
            "project_id": "proj-001",
            "script_ref": ref_a,
            "edited_media": {"path": "rough.mp4", "sha256": "b" * 64},
            "context_manifest_ref": {"path": "context.json", "sha256": "c" * 64},
            "timeline_sha256": "d" * 64,
            "areas": {
                "speech_boundaries": area_entry,
                "speech_levels": area_entry,
                "music_balance": area_entry,
                "subtitle_readability": area_entry,
                "visual_focus": area_entry,
                "delivery_pacing": area_entry,
            },
            "cues": [
                {
                    "id": "cue_1",
                    "area": "delivery_pacing",
                    "kind": "pacing",
                    "quote": "synthetic quote",
                    "start_seconds": 0.0,
                    "end_seconds": 2.5,
                    "intent": "clarity",
                    "decision": "keep",
                    "reason": "synthetic reason",
                    "expected_result": "smooth transition",
                    "scope": "intro",
                    "source_ref": ref_a,
                    "source_quote": "synthetic source",
                    "requires_change": False,
                    "before_ref": None,
                }
            ],
            "feedback_dispositions": [
                {
                    "id": "fb_1",
                    "source_ref": {"path": "fb.json", "sha256": "e" * 64},
                    "decision": "not_applicable",
                    "reason": "synthetic fixture",
                    "cue_ids": ["cue_1"],
                }
            ],
            "pacing": {
                "status": "not_tested",
                "reason": "initial baseline",
                "next_trial_speed": None,
                "observations": [],
            },
            "visual_beats_ref": None,
        }
        jsonschema.validate(instance=valid_plan, schema=vpp)

        wrong_schema = copy.deepcopy(valid_plan)
        wrong_schema["schema"] = "wrong.schema.v1"
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(instance=wrong_schema, schema=vpp)

        bad_sha = copy.deepcopy(valid_plan)
        bad_sha["timeline_sha256"] = "not-a-sha256"
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(instance=bad_sha, schema=vpp)


if __name__ == "__main__":
    unittest.main()
