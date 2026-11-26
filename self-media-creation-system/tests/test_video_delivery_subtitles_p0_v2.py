"""Standalone tests for self-media-creation-system video_delivery P0-v2 audit gates (N1, N2, N3, N4, N5, N7, N8)."""
from __future__ import annotations

import copy
import importlib
import os
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))

import video_delivery  # noqa: E402


class VideoDeliverySubtitlesP0V2Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = pathlib.Path(self.tmp.name)
        sub_seq, sub_styles, _, _ = video_delivery.subtitle_modules()
        sub_expr = importlib.import_module(f"{sub_seq.__package__}.subtitle_expression")
        self.EXPRESSIVE_SCHEMA = sub_expr.EXPRESSIVE_SCHEMA
        self.apply_expressive_cues = sub_expr.apply_expressive_cues
        self.build_expected_render_plan = sub_expr.build_expected_render_plan
        self.build_reviewed_subtitle_sequence = sub_seq.build_reviewed_subtitle_sequence
        self.build_ass_document = sub_styles.build_ass_document
        self.materialize_font_bundle = sub_styles.materialize_font_bundle
        self.resolve_subtitle_style = sub_styles.resolve_subtitle_style

        mvp_root = video_delivery._mvp_src_root().parent
        font_candidates = [mvp_root / "fonts"]
        if os.environ.get("SELF_MEDIA_FONTS_DIR"):
            font_candidates.append(pathlib.Path(os.environ["SELF_MEDIA_FONTS_DIR"]))
        sys_root = os.environ.get("SystemRoot") or os.environ.get("WINDIR")
        if sys_root:
            font_candidates.append(pathlib.Path(sys_root) / "Fonts")
        font_search = tuple(p for p in font_candidates if p.is_dir())
        self.scene_colors = {
            "受访者": {"color": "#8EE3FF", "label": "冷青", "color_reason": "Contrast"},
            "旁白": {"color": "#FFB499", "label": "珊瑚", "color_reason": "Contrast"},
        }
        self.style_default = self.resolve_subtitle_style(
            1080, 1920, speaker_colors=self.scene_colors, search_dirs=font_search
        )
        bundle = self.materialize_font_bundle(
            self.style_default["font"],
            self.tmp_path / "fonts",
            manifest_path=self.tmp_path / "font-bundle-manifest.json",
        )
        b_path = pathlib.Path(bundle["bundle_manifest"]["path"])
        self.bundle_verified = video_delivery._verify_font_bundle_ref(
            {"path": str(b_path), "sha256": bundle["bundle_manifest"]["sha256"]}
        )
        self.manifest = {
            "subtitles": {
                "contract_version": "v2",
                "source_route": "audio_timeline_segmented",
                "style_preset": "stroke_shadow_default",
                "font_bundle_ref": {"path": str(b_path), "sha256": bundle["bundle_manifest"]["sha256"]},
            },
            "facts": {"do_not_infer": []},
        }

    def tearDown(self):
        self.tmp.cleanup()

    def _verify(self, ass_path, cues, plan):
        with (
            patch("video_overlay_selection.for_manifest", return_value={}),
            patch("video_overlay_selection.check_ass", return_value={"status": "clean"}),
        ):
            return video_delivery._verify_ass_against_cues(
                self.manifest,
                ass_path,
                cues,
                v2_mode=True,
                preset_id="stroke_shadow_default",
                bundle=self.bundle_verified,
                expected_plan=plan,
            )

    def test_N1_N2_N3_N4_N5_N7_N8_delivery_audit_gates(self):
        seq = self.build_reviewed_subtitle_sequence(
            [{"cue_id": "c1", "start_s": 0.0, "end_s": 6.0, "speaker": "受访者", "speaker_prefix": "受访者：", "spoken_text": "其实这个，条款真的关键"}],
            max_line_units=11,
            total_duration_s=6.0,
        )
        plan = self.build_expected_render_plan(seq, style_spec=self.style_default)
        good_ass = self.tmp_path / "good.ass"
        good_ass.write_text(self.build_ass_document(seq["cues"], self.style_default), encoding="utf-8")
        self.assertEqual(self._verify(good_ass, seq["cues"], plan)["delivery_status"], "PASS")

        # N1: altered text fails despite self-consistent audit
        tampered_ass = self.tmp_path / "n1.ass"
        tampered_ass.write_text(good_ass.read_text(encoding="utf-8").replace("条款真的关键", "条款假关键"), encoding="utf-8")
        with self.assertRaises(ValueError) as ctx1:
            self._verify(tampered_ass, seq["cues"], plan)
        self.assertEqual(str(ctx1.exception), "burn_file_disagrees_with_expected_plan_text")

        # N2: 0.03s squeezed subsegment rejected
        n2_ass = self.tmp_path / "n2.ass"
        n2_ass.write_text(
            good_ass.read_text(encoding="utf-8").replace("0:00:00.00,0:00:06.00", "0:00:05.90,0:00:05.93"),
            encoding="utf-8",
        )
        n2_plan = copy.deepcopy(plan)
        n2_plan["expected_events"][0]["start_s"] = 5.90
        n2_plan["expected_events"][0]["end_s"] = 5.93
        with self.assertRaises(ValueError) as ctx2:
            self._verify(n2_ass, seq["cues"], n2_plan)
        self.assertEqual(str(ctx2.exception), "burn_file_subsegment_below_minimum_duration")

        # N5: illegal tag param / forbidden tag rejected
        for bad_tag, msg in [("{\\fs9999}", "unapproved_font_size"), ("{\\pos(1,1)}", "forbidden_tag_\\pos")]:
            n5_ass = self.tmp_path / "n5.ass"
            n5_ass.write_text(good_ass.read_text(encoding="utf-8").replace("其实这个", f"{bad_tag}其实这个"), encoding="utf-8")
            with self.assertRaises(ValueError) as ctx5:
                self._verify(n5_ass, seq["cues"], plan)
            self.assertIn(msg, str(ctx5.exception))

        # N7: stale expressive -> PASS_WITH_FALLBACK cleanly verified
        stale_plan = self.build_expected_render_plan(
            seq,
            expressive_doc={"schema": self.EXPRESSIVE_SCHEMA, "timeline_duration_s": 99.0, "annotations": [{"annotation_id": "x", "cue_id": "c1", "kind": "tone", "tone_label": "轻笑"}]},
            style_spec=self.style_default,
            requested_features=["tone"],
        )
        self.assertEqual(self._verify(good_ass, seq["cues"], stale_plan)["delivery_status"], "PASS_WITH_FALLBACK")

        # N8: audio PTS offset rejected even when PCM hash matches
        src = {"sample_rate": 48000, "channels": 1, "duration_s": 6.0, "audio_start_pts_s": 0.0, "video_start_pts_s": 0.0}
        shifted = {"sample_rate": 48000, "channels": 1, "duration_s": 6.0, "audio_start_pts_s": 0.12, "video_start_pts_s": 0.0}
        with self.assertRaises(ValueError) as ctx8:
            video_delivery.verify_audio_timeline_alignment(src, shifted)
        self.assertEqual(str(ctx8.exception), "audio_timeline_offset_mismatch")


if __name__ == "__main__":
    unittest.main(verbosity=2)
