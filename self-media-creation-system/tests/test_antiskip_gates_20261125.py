"""Positive & negative regression tests for 2026-11-25 anti-skip hard gates.

Covers:
1. editorial_integrity.check_fact_card: locked_for_draft + explicit human_confirmation required.
2. cover_policy.check_single_master & check_privacy_references: single visual master across all ratios + stripped portrait reference required.
3. publication_desk.verify_delivery_html / verify-html CLI: rejects hand-written static HTML and accepts genuine publication_desk.py builds.
"""
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import cover_policy
import cover_workbench as cw
import editorial_integrity as ei
import publication_desk as desk
import video_caption_quality as captions
import video_overlay_selection as overlays
import video_pacing as pacing


def _make_png(path: Path, size: tuple[int, int], color: tuple[int, int, int]) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path)
    return cw.reference(path)


class AntiSkipGatesTests(unittest.TestCase):
    # ---- 1. Fact-card human confirmation hard gate ----
    def test_fact_card_rejects_unlocked_or_boolean_confirmation_and_accepts_locked(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            unlocked = root / "fact-unlocked.json"
            unlocked.write_text(json.dumps({
                "schema": "content-fact-card.v0",
                "content_id": "demo-01",
                "canonical_status": "draft",
                "human_confirmation": "已核对",
            }), encoding="utf-8")
            with self.assertRaises(ValueError) as ctx:
                ei.check_fact_card(unlocked)
            self.assertIn("locked_for_draft", str(ctx.exception))

            bool_confirm = root / "fact-bool.json"
            bool_confirm.write_text(json.dumps({
                "schema": "content-fact-card.v0",
                "content_id": "demo-01",
                "canonical_status": "locked_for_draft",
                "human_confirmation": True,
            }), encoding="utf-8")
            with self.assertRaises(ValueError):
                ei.check_fact_card(bool_confirm)

            # Non-string quote (e.g. quote: 42) must also be rejected
            num_quote = root / "fact-num-quote.json"
            num_quote.write_text(json.dumps({
                "schema": "content-fact-card.v0",
                "content_id": "demo-01",
                "canonical_status": "locked_for_draft",
                "human_confirmation": {"quote": 42},
            }), encoding="utf-8")
            with self.assertRaises(ValueError):
                ei.check_fact_card(num_quote)

            valid = root / "fact-locked.json"
            valid.write_text(json.dumps({
                "schema": "content-fact-card.v0",
                "content_id": "demo-01",
                "canonical_status": "locked_for_draft",
                "human_confirmation": {"quote": "事实无误，可以写稿", "confirmed_at": "2026-11-25T10:00:00+08:00"},
            }, ensure_ascii=False), encoding="utf-8")
            res = ei.check_fact_card(valid, content_id="demo-01")
            self.assertTrue(res["locked"])
            self.assertEqual(res["canonical_status"], "locked_for_draft")

            # CLI --require-fact-card without --fact-card must block (exit 2)
            draft = root / "draft.md"
            draft.write_text("测试正文", encoding="utf-8")
            rc_missing = ei.main(["check-draft", "--draft", str(draft), "--require-fact-card"])
            self.assertEqual(rc_missing, 2)
            rc_ok = ei.main(["check-draft", "--draft", str(draft), "--require-fact-card", "--fact-card", str(valid)])
            self.assertEqual(rc_ok, 0)

    # ---- 2. Cover single-master & privacy-strip hard gates ----
    def test_cover_single_master_rejects_split_outfits_and_accepts_unified_master(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            master_a = _make_png(root / "master_a.png", (1920, 1080), (20, 22, 24))
            master_b = _make_png(root / "master_b.png", (1080, 1440), (40, 44, 48))
            img_3x4 = _make_png(root / "c_3x4.png", (1080, 1440), (21, 22, 24))
            img_9x16 = _make_png(root / "c_9x16.png", (1080, 1920), (22, 22, 24))
            img_4x3 = _make_png(root / "c_4x3.png", (1440, 1080), (23, 22, 24))
            img_16x9 = _make_png(root / "c_16x9.png", (1920, 1080), (24, 22, 24))

            preview = root / "preview.json"
            preview.write_text(json.dumps({
                "schema": "self-media.cover-package-review.v1",
                "project_id": "demo-cover",
                "stage": "preview",
                "reviewer": "creator",
                "candidates": [{
                    "id": "ai1",
                    "style_id": "ai-reference-dark",
                    "headline": "测试标题",
                    "images": {
                        "3:4": {"image_ref": img_3x4, "visual_passed": True, "visible_text": ["测试标题"]},
                    },
                }],
            }, ensure_ascii=False), encoding="utf-8")

            # Negative: split masters (3:4/9:16 use master_b, 4:3/16:9 use master_a) must FAIL
            split_final = root / "final-split.json"
            split_final.write_text(json.dumps({
                "schema": "self-media.cover-package-review.v1",
                "project_id": "demo-cover",
                "stage": "final",
                "reviewer": "creator",
                "style_choice": {
                    "candidate_id": "ai1",
                    "user_confirmation": "选ai1",
                    "preview_package_ref": cw.reference(preview),
                },
                "candidates": [{
                    "id": "ai1",
                    "style_id": "ai-reference-dark",
                    "headline": "测试标题",
                    "images": {
                        "3:4": {"image_ref": img_3x4, "master_plate_ref": master_b, "visual_passed": True, "visible_text": ["测试标题"]},
                        "9:16": {"image_ref": img_9x16, "master_plate_ref": master_b, "visual_passed": True, "visible_text": ["测试标题"]},
                        "4:3": {"image_ref": img_4x3, "master_plate_ref": master_a, "visual_passed": True, "visible_text": ["测试标题"]},
                        "16:9": {"image_ref": img_16x9, "master_plate_ref": master_a, "visual_passed": True, "visible_text": ["测试标题"]},
                    },
                }],
            }, ensure_ascii=False), encoding="utf-8")
            with self.assertRaises(ValueError) as ctx:
                cover_policy.package_check(split_final, require_single_master=True)
            self.assertIn("cover_candidate_master_plate_mismatch", str(ctx.exception))

            # Positive: all 4 ratios share master_a -> PASS with single_master_verified=True
            unified_final = root / "final-unified.json"
            unified_final.write_text(json.dumps({
                "schema": "self-media.cover-package-review.v1",
                "project_id": "demo-cover",
                "stage": "final",
                "reviewer": "creator",
                "style_choice": {
                    "candidate_id": "ai1",
                    "user_confirmation": "选ai1",
                    "preview_package_ref": cw.reference(preview),
                },
                "candidates": [{
                    "id": "ai1",
                    "style_id": "ai-reference-dark",
                    "headline": "测试标题",
                    "master_plate_ref": master_a,
                    "images": {
                        "3:4": {"image_ref": img_3x4, "visual_passed": True, "visible_text": ["测试标题"]},
                        "9:16": {"image_ref": img_9x16, "visual_passed": True, "visible_text": ["测试标题"]},
                        "4:3": {"image_ref": img_4x3, "visual_passed": True, "visible_text": ["测试标题"]},
                        "16:9": {"image_ref": img_16x9, "visual_passed": True, "visible_text": ["测试标题"]},
                    },
                }],
            }, ensure_ascii=False), encoding="utf-8")
            receipt = cover_policy.package_check(unified_final, require_single_master=True)
            self.assertEqual(receipt["status"], "final_cover_package_complete")
            self.assertTrue(receipt["candidates"][0]["single_master_verified"])
            self.assertEqual(receipt["candidates"][0]["master_plate_sha256"], master_a["sha256"])

    def test_cover_privacy_reference_rejects_raw_unmirrored_portrait(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            raw_ref = _make_png(root / "canonical-unmirrored" / "raw.png", (600, 800), (100, 100, 100))
            nobg_ref = _make_png(root / "cutouts" / "portrait_nobg.png", (600, 800), (128, 128, 128))
            img_3x4 = _make_png(root / "out_3x4.png", (1080, 1440), (20, 20, 20))

            bad_pkg = root / "bad-priv.json"
            bad_pkg.write_text(json.dumps({
                "schema": "self-media.cover-package-review.v1",
                "project_id": "demo-priv",
                "stage": "preview",
                "reviewer": "creator",
                "candidates": [{
                    "id": "c1",
                    "style_id": "ai-reference-dark",
                    "headline": "标题",
                    "identity_reference_ref": raw_ref,
                    "images": {"3:4": {"image_ref": img_3x4, "visual_passed": True, "visible_text": ["标题"]}},
                }],
            }, ensure_ascii=False), encoding="utf-8")
            with self.assertRaises(ValueError) as ctx:
                cover_policy.package_check(bad_pkg)
            self.assertIn("cover_unstripped_private_reference", str(ctx.exception))

            ok_pkg = root / "ok-priv.json"
            ok_pkg.write_text(json.dumps({
                "schema": "self-media.cover-package-review.v1",
                "project_id": "demo-priv",
                "stage": "preview",
                "reviewer": "creator",
                "candidates": [{
                    "id": "c1",
                    "style_id": "ai-reference-dark",
                    "headline": "标题",
                    "identity_reference_ref": nobg_ref,
                    "background_stripped": True,
                    "images": {"3:4": {"image_ref": img_3x4, "visual_passed": True, "visible_text": ["标题"]}},
                }],
            }, ensure_ascii=False), encoding="utf-8")
            res = cover_policy.package_check(ok_pkg)
            self.assertEqual(res["status"], "preview_reviewed")

    # ---- 3. Anti-handwritten-HTML publication desk gate ----
    def test_publication_desk_verify_html_rejects_handwritten_and_accepts_rendered(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            handwritten = root / "handwritten-desk.html"
            handwritten.write_text("<html><body><h1>Hand-written fake desk</h1></body></html>", encoding="utf-8")
            with self.assertRaises(ValueError) as ctx:
                desk.verify_delivery_html(handwritten)
            self.assertIn("handwritten_or_unbound_publication_desk", str(ctx.exception))
            self.assertEqual(desk.main(["verify-html", "--input", str(handwritten)]), 2)

            # Genuine render via publication_desk.py CLI -> verify-html passes!
            data_in = root / "desk.json"
            out_html = root / "desk-official.html"
            self.assertEqual(desk.main(["init", "--project-id", "demo-desk", "--title", "测试项目", "--output", str(data_in)]), 0)
            self.assertEqual(desk.main(["render", "--input", str(data_in), "--output", str(out_html)]), 0)
            self.assertEqual(desk.main(["verify-html", "--input", str(out_html)]), 0)

            # Multi-item desk must fail closed on single-video submission check
            multi = desk.new_project("demo-multi", "多条测试", ["kuaishou"])
            multi["items"].append(dict(multi["items"][0], id="second"))
            with self.assertRaisesRegex(ValueError, "submission_single_video_desk_required"):
                desk.check_delivery_bundle(data_in, multi, out_html.with_suffix(".build.json"))

    # ---- 4. P0-1: Multi-chunk VKP absolute-ms timestamps (incl. offset=0.8s) & BGM merged speech-gap check ----
    def test_pacing_multi_chunk_absolute_ms_and_bgm_speech_gaps(self):
        # Test exact ChatGPT boundary: offset=0.8s with absolute 0.95s must NOT become 1.75s!
        raw_small = {
            "result": [{
                "chunk_offset_seconds": 0.8,
                "chunk_core_start_seconds": 0.8,
                "chunk_core_end_seconds": 5.0,
                "words": ["长词"],
                "timestamp": [[950.0, 2950.0]],  # 2.0s spoken word: must NOT count as a pause
            }]
        }
        spans_small = pacing.speech_spans(raw_small, duration=5.0)
        self.assertAlmostEqual(spans_small[0][0], 0.95, places=3)
        self.assertEqual(pacing.speech_gap_ranges(spans_small), [])

        raw = {
            "result": [
                {
                    "chunk_offset_seconds": 0.0,
                    "chunk_core_start_seconds": 0.0,
                    "chunk_core_end_seconds": 300.0,
                    "words": ["你", "好"],
                    "timestamp": [[1000.0, 1200.0], [1500.0, 1700.0]],
                },
                {
                    "chunk_offset_seconds": 295.0,
                    "chunk_core_start_seconds": 300.0,
                    "chunk_core_end_seconds": 590.5,
                    "words": ["测", "试"],
                    "timestamp": [[301000.0, 301200.0], [303500.0, 303700.0]],
                },
            ]
        }
        spans = pacing.speech_spans(raw, duration=590.5)
        self.assertAlmostEqual(spans[2][0], 301.0, places=2)
        gaps = pacing.speech_gap_ranges(spans)
        self.assertTrue(any(g["seconds"] >= 1.5 for g in gaps))
        # When BGM has 1 mix silence AND 1 separate BGM-masked speech gap, BOTH must be reviewed!
        mix_pauses = [dict(start=5.0, end=6.8, seconds=1.8)]
        bgm_gaps = [dict(start=20.0, end=22.0, seconds=2.0)]
        only_mix_reviewed = {"long_pause_review": {"video_sha256": "abc123", "retained_pauses": [{"start": 5.0, "end": 6.8, "reason": "ok"}]}}
        with self.assertRaisesRegex(ValueError, "unresolved_long_pauses"):
            pacing.check_long_pauses({"pauses": mix_pauses, "speech_gaps": bgm_gaps}, only_mix_reviewed, "abc123", has_bgm=True)
        both_reviewed = {"long_pause_review": {"video_sha256": "abc123", "retained_pauses": [
            {"start": 5.0, "end": 6.8, "reason": "mix"}, {"start": 20.0, "end": 22.0, "reason": "bgm gap"}
        ]}}
        pacing.check_long_pauses({"pauses": mix_pauses, "speech_gaps": bgm_gaps}, both_reviewed, "abc123", has_bgm=True)

    # ---- 5. P0-2 & P1-2: Cross-cue merge punctuation drop & prefix-collision caption path rejected ----
    def test_caption_cross_cue_merge_punctuation_drop_blocked(self):
        source = [
            dict(start_seconds=0.2, end_seconds=1.0, text="你好，"),
            dict(start_seconds=3.0, end_seconds=3.8, text="世界。"),
        ]
        segments = [
            dict(target_start=0.0, source_start=0.0, source_end=1.0, speed=1.0),
            dict(target_start=1.0, source_start=3.0, source_end=4.0, speed=1.0),
        ]
        merged_missing_punct = [dict(start_seconds=0.2, end_seconds=1.8, text="你好世界。")]
        with self.assertRaisesRegex(ValueError, "caption_punctuation_changed_at_retained_edit_join"):
            captions.check_edit_punctuation(source, merged_missing_punct, segments)
        merged_kept_punct = [dict(start_seconds=0.2, end_seconds=1.8, text="你好，世界。")]
        captions.check_edit_punctuation(source, merged_kept_punct, segments)
        # Prefix-collision caption filename must NOT match
        with tempfile.TemporaryDirectory() as td:
            sub = Path(td) / "sub.ass"
            other = Path(td) / "sub.ass.bak"
            sub.write_text("", encoding="utf-8")
            other.write_text("", encoding="utf-8")
            self.assertFalse(captions._arg_references_caption(f"ass='{other.as_posix()}'", sub))
            self.assertTrue(captions._arg_references_caption(f"ass='{sub.as_posix()}'", sub))

    # ---- 6. P1-1: ASS multi-window partial medical badge & parenthesized medical text outside window rejected ----
    def test_overlay_ass_rejects_partial_medical_badge_in_second_window(self):
        with tempfile.TemporaryDirectory() as td:
            ass = Path(td) / "scoped.ass"
            ass.write_text(
                "[Events]\n"
                "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
                f"Dialogue: 0,0:00:01.00,0:00:02.00,Badge,,0,0,0,,{overlays.MEDICAL_TEXT}\n"
                "Dialogue: 0,0:00:04.00,0:00:05.00,Badge,,0,0,0,,医学科普（仅供参考）\n"
                "Dialogue: 0,0:00:00.00,0:00:06.00,Badge,,0,0,0,,内容由AI辅助生成。\n",
                encoding="utf-8",
            )
            choices = {
                "medical": {
                    "decision": "required",
                    "text": overlays.MEDICAL_TEXT,
                    "windows": [
                        {"start_seconds": 1.0, "end_seconds": 2.0, "quote": "q1"},
                        {"start_seconds": 4.0, "end_seconds": 5.0, "quote": "q2"},
                    ],
                },
                "insurance": {"decision": "not_applicable"},
                "ai": {"mode": "ai_assisted"},
            }
            with self.assertRaisesRegex(ValueError, "video_overlay_medical_text_mismatch"):
                overlays.check_ass(choices, ass)

            # Normal spoken dialogue mentioning '医学科普' must NOT be false-flagged as a medical badge!
            normal_ass = Path(td) / "normal.ass"
            normal_ass.write_text(
                "[Events]\n"
                "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
                "Dialogue: 0,0:00:00.20,0:00:02.00,Default,,0,0,0,,这是一条医学科普视频\n"
                f"Dialogue: 0,0:00:01.00,0:00:02.00,Badge,,0,0,0,,{overlays.MEDICAL_TEXT}\n"
                f"Dialogue: 0,0:00:04.00,0:00:05.00,Badge,,0,0,0,,{overlays.MEDICAL_TEXT}\n"
                "Dialogue: 0,0:00:00.00,0:00:06.00,Badge,,0,0,0,,内容由AI辅助生成。\n",
                encoding="utf-8",
            )
            self.assertTrue(overlays.check_ass(choices, normal_ass)["layers"]["medical"])

    # ---- 7. Round-3 boundary counterexamples (pacing coords/endpoints/0.2s gap, filename=, rebreaks, fact-card schema/sha) ----
    def test_round3_counterexamples(self):
        # Unknown timestamp_coordinate rejected
        with self.assertRaisesRegex(ValueError, "pacing_unknown_timestamp_coordinate"):
            pacing.speech_spans({"timestamp_coordinate": "weird", "result": [{"chunk_offset_seconds": 0, "chunk_core_start_seconds": 0, "chunk_core_end_seconds": 5, "words": ["a"], "timestamp": [[100, 200]]}]}, 5.0)
        # Word ending at 3.8s in a 3.0s video rejected (both endpoints checked)
        with self.assertRaisesRegex(ValueError, "pacing_vkp_word_timestamp_out_of_bounds"):
            pacing.speech_spans({"result": [{"chunk_offset_seconds": 0, "chunk_core_start_seconds": 0, "chunk_core_end_seconds": 3.0, "words": ["a"], "timestamp": [[2000, 3800]]}]}, 3.0)
        # Two pauses separated by 0.2s speech must NOT be merged into one
        merged = pacing._merge_pause_intervals([(1.0, 2.6), (2.8, 4.5)])
        self.assertEqual(merged, [(1.0, 2.6), (2.8, 4.5)])

        # subtitles=filename=... accepted; -metadata comment="ass=..." ignored; relative path without cwd rejected
        with tempfile.TemporaryDirectory() as td:
            sub = Path(td) / "sub.ass"
            sub.write_text("", encoding="utf-8")
            self.assertTrue(captions._arg_references_caption(f"subtitles=filename='{sub.as_posix()}'", sub))
            self.assertFalse(captions._arg_references_caption("subtitles='sub.ass'", sub, cwd=None))
            self.assertTrue(captions._arg_references_caption("subtitles='sub.ass'", sub, cwd=td))
            cmd_meta = ["ffmpeg", "-i", "in.mp4", "-metadata", f"comment=ass='{sub.as_posix()}'", "out.mp4"]
            self.assertEqual(list(captions._extract_filter_expressions(cmd_meta)), [])

        # Legitimate rebreak with explicit accepted_edit_rebreaks passes; 3rd-cue outer merge dropping punct fails
        source = [
            dict(start_seconds=0.2, end_seconds=1.0, text="我们先说。"),
            dict(start_seconds=3.0, end_seconds=3.8, text="下一步再做。"),
        ]
        segments = [
            dict(target_start=0.0, source_start=0.0, source_end=1.0, speed=1.0),
            dict(target_start=1.0, source_start=3.0, source_end=4.0, speed=1.0),
        ]
        rebroken = [dict(start_seconds=0.2, end_seconds=1.8, text="我们先说，下一步再做。")]
        captions.check_edit_punctuation(
            source, rebroken, segments,
            accepted_rebreaks=[{"cut_seconds": 1.0, "source_text": "我们先说。下一步再做。", "final_text": "我们先说，下一步再做。", "reason": "自然顺句"}],
        )
        outer_merged_drop = [dict(start_seconds=0.2, end_seconds=2.8, text="我们先说下一步再做还有第三句。")]
        with self.assertRaisesRegex(ValueError, "caption_punctuation_changed_at_retained_edit_join"):
            captions.check_edit_punctuation(source, outer_merged_drop, segments)

        # Unregistered fact-card schema & null sha256 rejected
        with tempfile.TemporaryDirectory() as td:
            bad_schema = Path(td) / "bad-schema.json"
            bad_schema.write_text(json.dumps({
                "schema": "content-fact-card.v99",
                "content_id": "demo-01",
                "canonical_status": "locked_for_draft",
                "human_confirmation": {"quote": "ok"},
            }), encoding="utf-8")
            with self.assertRaises(ValueError):
                ei.check_fact_card(bad_schema)
            with self.assertRaises(ValueError):
                ei.check_fact_card(bad_schema, expected_sha256="not-a-hex")

    # ---- 8. Round-4 boundary counterexamples ----
    def test_round4_counterexamples(self):
        # 1) VKP chunk boundary: chunk starting at 295s with absolute 1.0-1.2s word must fail closed
        bad_chunk_vkp = {
            "result": [
                {
                    "chunk_offset_seconds": 0.0,
                    "chunk_core_start_seconds": 0.0,
                    "chunk_core_end_seconds": 300.0,
                    "words": ["你"],
                    "timestamp": [[1000.0, 1200.0]],
                },
                {
                    "chunk_offset_seconds": 295.0,
                    "chunk_core_start_seconds": 300.0,
                    "chunk_core_end_seconds": 590.5,
                    "words": ["错"],
                    "timestamp": [[1000.0, 1200.0]],
                },
            ]
        }
        with self.assertRaisesRegex(ValueError, "pacing_vkp_word_outside_chunk_bounds"):
            pacing.speech_spans(bad_chunk_vkp, duration=590.5)

        # 2) Caption filter: -filter:v:0 accepted, drawtext=text='ass=...' rejected, opening quote drop blocked
        with tempfile.TemporaryDirectory() as td:
            sub = Path(td) / "sub.ass"
            sub.write_text("", encoding="utf-8")
            cmd_fv0 = ["ffmpeg", "-i", "in.mp4", "-filter:v:0", f"ass='{sub.as_posix()}'", "out.mp4"]
            exprs = list(captions._extract_filter_expressions(cmd_fv0))
            self.assertEqual(len(exprs), 1)
            self.assertTrue(captions._arg_references_caption(exprs[0], sub))
            self.assertFalse(captions._arg_references_caption(f"drawtext=text='ass={sub.as_posix()}'", sub))
            self.assertTrue(captions._arg_references_caption(f"scale=1080:1920,subtitles=filename='{sub.as_posix()}'", sub))

        src_q = [
            dict(start_seconds=0.2, end_seconds=1.0, text="“你好，”"),
            dict(start_seconds=3.0, end_seconds=3.8, text="世界。"),
        ]
        segs_q = [
            dict(target_start=0.0, source_start=0.0, source_end=1.0, speed=1.0),
            dict(target_start=1.0, source_start=3.0, source_end=4.0, speed=1.0),
        ]
        dropped_open_quote = [dict(start_seconds=0.2, end_seconds=1.8, text="你好，”世界。")]
        with self.assertRaisesRegex(ValueError, "caption_punctuation_changed_at_retained_edit_join"):
            captions.check_edit_punctuation(src_q, dropped_open_quote, segs_q)

        # 3) Medical overlay ASS: custom dialogue_styles=['SpeakerA'] & dialogue ending in '医学科普' NOT false-flagged
        with tempfile.TemporaryDirectory() as td:
            ass = Path(td) / "custom_dialogue.ass"
            ass.write_text(
                "[Events]\n"
                "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
                "Dialogue: 0,0:00:00.20,0:00:01.00,SpeakerA,,0,0,0,,这是一条医学科普视频\n"
                "Dialogue: 0,0:00:02.00,0:00:03.00,Default,,0,0,0,,今天讲医学科普\n"
                f"Dialogue: 0,0:00:01.00,0:00:02.00,Badge,,0,0,0,,{overlays.MEDICAL_TEXT}\n"
                "Dialogue: 0,0:00:00.00,0:00:06.00,Badge,,0,0,0,,内容由AI辅助生成。\n",
                encoding="utf-8",
            )
            choices = {
                "medical": {
                    "decision": "required",
                    "text": overlays.MEDICAL_TEXT,
                    "windows": [{"start_seconds": 1.0, "end_seconds": 2.0, "quote": "q1"}],
                },
                "insurance": {"decision": "not_applicable"},
                "ai": {"mode": "ai_assisted"},
            }
            self.assertTrue(overlays.check_ass(choices, ass, dialogue_styles=["SpeakerA"])["layers"]["medical"])

        # 4) Cover single-master: legacy_no_master_plate: true in JSON MUST NOT bypass stage='final'
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            img_3x4 = _make_png(root / "c_3x4.png", (1080, 1440), (21, 22, 24))
            img_9x16 = _make_png(root / "c_9x16.png", (1080, 1920), (22, 22, 24))
            img_4x3 = _make_png(root / "c_4x3.png", (1440, 1080), (23, 22, 24))
            img_16x9 = _make_png(root / "c_16x9.png", (1920, 1080), (24, 22, 24))
            preview = root / "preview.json"
            preview.write_text(json.dumps({
                "schema": "self-media.cover-package-review.v1",
                "project_id": "demo-legacy-bypass",
                "stage": "preview",
                "reviewer": "creator",
                "candidates": [{
                    "id": "ai1",
                    "style_id": "ai-reference-dark",
                    "headline": "测试标题",
                    "images": {"3:4": {"image_ref": img_3x4, "visual_passed": True, "visible_text": ["测试标题"]}},
                }],
            }, ensure_ascii=False), encoding="utf-8")
            bypass_final = root / "final-bypass.json"
            bypass_final.write_text(json.dumps({
                "schema": "self-media.cover-package-review.v1",
                "project_id": "demo-legacy-bypass",
                "stage": "final",
                "legacy_no_master_plate": True,
                "reviewer": "creator",
                "style_choice": {
                    "candidate_id": "ai1",
                    "user_confirmation": "选ai1",
                    "preview_package_ref": cw.reference(preview),
                },
                "candidates": [{
                    "id": "ai1",
                    "style_id": "ai-reference-dark",
                    "headline": "测试标题",
                    "images": {
                        "3:4": {"image_ref": img_3x4, "visual_passed": True, "visible_text": ["测试标题"]},
                        "9:16": {"image_ref": img_9x16, "visual_passed": True, "visible_text": ["测试标题"]},
                        "4:3": {"image_ref": img_4x3, "visual_passed": True, "visible_text": ["测试标题"]},
                        "16:9": {"image_ref": img_16x9, "visual_passed": True, "visible_text": ["测试标题"]},
                    },
                }],
            }, ensure_ascii=False), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "cover_candidate_master_plate_missing"):
                cover_policy.package_check(bypass_final)

        # 5) Editorial integrity: revision_envelope & evaluate block missing fact_card_ref (historical=False), allow historical=True
        import shutil
        import uuid
        import author_writing_context as awc

        repo_root = Path(__file__).resolve().parents[1]
        tmp_root = (repo_root / ".test-runtime" / ("antiskip-r4-" + uuid.uuid4().hex)).resolve()
        tmp_root.mkdir(parents=True)
        try:
            db = tmp_root / "synthetic.sqlite3"
            src = tmp_root / "source.md"
            src.write_text("Synthetic source text for Round-4 test.", encoding="utf-8")
            ctx_data = awc.prepare_context(db, {
                "content_id": "r4-content", "account_id": "r4-author", "genre": "spoken_script",
                "synthetic_only": True, "privacy_status": "non_sensitive", "source_ref": "synthetic:r4",
                "judgments": [],
            }, "r4-request")
            ctx_path = tmp_root / "context.json"
            ctx_path.write_text(json.dumps(ctx_data, ensure_ascii=False), encoding="utf-8")
            ev = {**awc.ref(src), "quote": "Synthetic source text"}
            legacy_pre = {
                "route": "expository", "actor": "synthetic_fixture", "source": ev,
                "items": [{"id": k, "state": "ready", "reason": "Synthetic " + k, "evidence": [ev]} for k in sorted(ei.PRE)],
            }
            # Record a legacy no-fact-card preflight (simulating pre-gate historical record)
            ei.record_preflight(ctx_path, legacy_pre)
            draft = tmp_root / "draft.md"
            draft.write_text("测试正文", encoding="utf-8")
            rev_payload = {
                "before": "旧稿",
                "reasons": [{"text": "r4", "actor": "synthetic_fixture", "source_ref": "synthetic:r4"}],
                "source_ref": "synthetic:r4",
                "privacy_status": "non_sensitive",
            }
            # Current drafting (historical=False) MUST block revision_envelope without fact_card_ref
            with self.assertRaisesRegex(Exception, "fact_card_ref"):
                awc.revision_envelope(db, ctx_path, draft, rev_payload)
            # Historical replay via validate_context_manifest(historical=True) MUST succeed
            manifest_path = tmp_root / "manifest.json"
            manifest_path.write_text(json.dumps({
                "artifacts": [{
                    "source_role": "author-writing-context",
                    "path": "context.json",
                    "expected_sha256": awc.file_sha(ctx_path),
                    "load_mode": "reference",
                }]
            }, ensure_ascii=False), encoding="utf-8")
            capsule = {
                "request_id": "r4-request",
                "provenance": {
                    "synthetic_only": True,
                    "author_identity": {"account_id": "r4-author", "genre": "spoken_script"},
                },
            }
            writing_step = {"step_id": sorted(awc.WRITING_STEPS)[0]}
            awc.validate_context_manifest(manifest_path, capsule, writing_step, historical=True)
            with self.assertRaisesRegex(Exception, "fact_card_ref"):
                awc.validate_context_manifest(manifest_path, capsule, writing_step, historical=False)
            # Historical revision envelope passes when historical=True, but evaluate(..., historical=False) blocks advancement
            hist_env = awc.revision_envelope(db, ctx_path, draft, rev_payload, historical=True)
            env_path = tmp_root / "rev.json"
            env_path.write_text(json.dumps(hist_env, ensure_ascii=False), encoding="utf-8")
            with self.assertRaisesRegex(Exception, "fact_card_ref"):
                ei.evaluate(env_path, {}, historical=False)
        finally:
            shutil.rmtree(tmp_root, ignore_errors=True)

    # ---- 9. Round-5 boundary counterexamples ----
    def test_round5_counterexamples(self):
        # 1) VKP inverted/non-finite core range rejected
        inverted_vkp = {
            "result": [{
                "chunk_offset_seconds": 0.0,
                "chunk_core_start_seconds": 10.0,
                "chunk_core_end_seconds": 5.0,
                "chunk_end_seconds": 12.0,
                "words": ["词"],
                "timestamp": [[1000.0, 1200.0]],
            }]
        }
        with self.assertRaisesRegex(ValueError, "pacing_vkp_chunk_bounds_invalid"):
            pacing.speech_spans(inverted_vkp, duration=15.0)
        nan_vkp = {
            "result": [{
                "chunk_offset_seconds": 0.0,
                "chunk_core_start_seconds": 0.0,
                "chunk_core_end_seconds": float("nan"),
                "words": ["词"],
                "timestamp": [[1000.0, 1200.0]],
            }]
        }
        with self.assertRaisesRegex(ValueError, "pacing_vkp_chunk_bounds_invalid"):
            pacing.speech_spans(nan_vkp, duration=15.0)

        # 2) Abandoned -filter_complex subtitle branch rejected; mapped branch accepted; unchanged opening-quote merge accepted
        with tempfile.TemporaryDirectory() as td:
            sub = Path(td) / "sub.ass"
            sub.write_text("", encoding="utf-8")
            cmd_abandoned = [
                "ffmpeg", "-i", "in.mp4",
                "-filter_complex", f"[0:v]ass='{sub.as_posix()}'[burned];[0:v]copy[clean]",
                "-map", "[clean]", "out.mp4",
            ]
            self.assertFalse(captions._command_burns_caption_to_mapped_video(cmd_abandoned, sub))
            cmd_mapped = [
                "ffmpeg", "-i", "in.mp4",
                "-filter_complex", f"[0:v]ass='{sub.as_posix()}'[burned];[0:v]copy[clean]",
                "-map", "[burned]", "out.mp4",
            ]
            self.assertTrue(captions._command_burns_caption_to_mapped_video(cmd_mapped, sub))
            cmd_vf = ["ffmpeg", "-i", "in.mp4", "-vf", f"ass='{sub.as_posix()}'", "out.mp4"]
            self.assertTrue(captions._command_burns_caption_to_mapped_video(cmd_vf, sub))

        src_quote_merge = [
            dict(start_seconds=0.2, end_seconds=1.0, text="他说，"),
            dict(start_seconds=3.0, end_seconds=3.8, text="“你好。”"),
        ]
        segs_qm = [
            dict(target_start=0.0, source_start=0.0, source_end=1.0, speed=1.0),
            dict(target_start=1.0, source_start=3.0, source_end=4.0, speed=1.0),
        ]
        merged_unchanged = [dict(start_seconds=0.2, end_seconds=1.8, text="他说，“你好。”")]
        captions.check_edit_punctuation(src_quote_merge, merged_unchanged, segs_qm)

        # 3) External caption ASS with separate AI overlay passes external_caption_only=True, while inapplicable overlay still fails
        with tempfile.TemporaryDirectory() as td:
            ass = Path(td) / "dialogue_only.ass"
            ass.write_text(
                "[Events]\n"
                "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
                "Dialogue: 0,0:00:00.20,0:00:01.00,SpeakerA,,0,0,0,,第一句\n"
                "Dialogue: 0,0:00:01.20,0:00:02.00,Default,,0,0,0,,第二句\n",
                encoding="utf-8",
            )
            choices = {
                "medical": {"decision": "not_applicable"},
                "insurance": {"decision": "not_applicable"},
                "ai": {"mode": "ai_assisted"},
            }
            self.assertTrue(overlays.check_ass(choices, ass, dialogue_styles=["SpeakerA"], external_caption_only=True)["layers"]["ai"])
            # Unified dialogue_styles includes both SpeakerA and Default
            expected_cues = [
                {"start_seconds": 0.2, "end_seconds": 1.0, "text": "第一句"},
                {"start_seconds": 1.2, "end_seconds": 2.0, "text": "第二句"},
            ]
            captions.verify_burned_cues(ass, expected_cues, set(captions.DEFAULT_STYLES) | {"speakera"})
            # Inapplicable insurance badge inside external ASS is still blocked
            bad_ass = Path(td) / "inapplicable.ass"
            bad_ass.write_text(
                "[Events]\n"
                "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
                "Dialogue: 0,0:00:00.20,0:00:01.00,Badge,,0,0,0,,执业证编号：123456\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "video_overlay_ass_applicability_mismatch: insurance"):
                overlays.check_ass(choices, bad_ass, external_caption_only=True)

        # 4) Fact card replaced after review -> status() MUST fail with fact_card_changed
        import shutil
        import uuid
        import author_writing_context as awc
        import editorial_fixture as ef

        repo_root = Path(__file__).resolve().parents[1]
        tmp_root = (repo_root / ".test-runtime" / ("antiskip-r5-" + uuid.uuid4().hex)).resolve()
        tmp_root.mkdir(parents=True)
        try:
            db = tmp_root / "synthetic.sqlite3"
            src = tmp_root / "source.md"
            src.write_text("Synthetic source for Round-5 fact-card replacement test.", encoding="utf-8")
            ctx_data = awc.prepare_context(db, {
                "content_id": "r5-content", "account_id": "r5-author", "genre": "spoken_script",
                "synthetic_only": True, "privacy_status": "non_sensitive", "source_ref": "synthetic:r5",
                "judgments": [],
            }, "r5-request")
            ctx_path = tmp_root / "context.json"
            ctx_path.write_text(json.dumps(ctx_data, ensure_ascii=False), encoding="utf-8")
            ev = {**awc.ref(src), "quote": "Synthetic source for Round-5"}
            fc_a = tmp_root / "fact-a.json"
            fc_a.write_text(json.dumps({
                "schema": "content-fact-card.v0",
                "content_id": "r5-content",
                "canonical_status": "locked_for_draft",
                "human_confirmation": {"quote": "Fact A confirmed"},
                "facts": ["fact A"],
            }, ensure_ascii=False), encoding="utf-8")
            pre_a = {
                "route": "expository", "actor": "synthetic_fixture", "source": ev,
                "fact_card_ref": awc.ref(fc_a),
                "items": [{"id": k, "state": "ready", "reason": "Synthetic " + k, "evidence": [ev]} for k in sorted(ei.PRE)],
            }
            ei.record_preflight(ctx_path, pre_a)
            draft = tmp_root / "draft.md"
            draft.write_text("测试正文第一版，用于验证事实卡替换后旧评审失效。", encoding="utf-8")
            rev_payload = {
                "before": "旧稿",
                "reasons": [{"text": "r5", "actor": "synthetic_fixture", "source_ref": "synthetic:r5"}],
                "source_ref": "synthetic:r5",
                "privacy_status": "non_sensitive",
            }
            env = awc.revision_envelope(db, ctx_path, draft, rev_payload)
            env_path = tmp_root / "rev.json"
            env_path.write_text(json.dumps(env, ensure_ascii=False), encoding="utf-8")
            # Record full review under Fact Card A
            assessment = {
                "request_id": env["request_id"], "draft_ref": env["draft_ref"], "route": "expository", "phase": "draft",
                "previous_review_id": None, "feedback_ids": [], "changes": [],
                "actor": "synthetic_fixture", "source": ev, "issues": [],
                "observations": {"readthrough": None, "final_media": None},
                "checks": [{
                    "id": c, "state": "retained", "scope": "script-text", "quote": "测试正文第一版",
                    "reason": "Synthetic check " + c, "evidence": [ev], "issue_ids": [], "reuse_from": None,
                } for c in sorted(ei.CHECKS)],
            }
            assessment["checks"][0]["purpose_alignment"] = {
                "stage_duty": "Explain synthetic draft meaning.",
                "contribution": "Carries synthetic statement.",
                "misunderstanding_risk": "Synthetic fixture only.",
                "tradeoff": "Minimal fixture.",
            }
            ei.record_review(env_path, assessment)
            # Now replace fact card with a different locked Fact Card B in a new preflight
            fc_b = tmp_root / "fact-b.json"
            fc_b.write_text(json.dumps({
                "schema": "content-fact-card.v0",
                "content_id": "r5-content",
                "canonical_status": "locked_for_draft",
                "human_confirmation": {"quote": "Fact B confirmed"},
                "facts": ["fact B (changed)"],
            }, ensure_ascii=False), encoding="utf-8")
            pre_b = dict(pre_a, fact_card_ref=awc.ref(fc_b))
            ei.record_preflight(ctx_path, pre_b)
            with self.assertRaisesRegex(Exception, "fact_card_ref|fact card"):
                ei.status(env_path)
        finally:
            shutil.rmtree(tmp_root, ignore_errors=True)

        # 5) Cover single-master: build spec locks Master A, review rows claim Master B -> MUST fail
        import cover_strategy as cs
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            master_a = _make_png(root / "master_a.png", (1920, 1080), (20, 22, 24))
            master_b = _make_png(root / "master_b.png", (1920, 1080), (60, 62, 64))
            # Build minimal final desk + cover_build_ref + review where spec locks master_a and review claims master_b
            brief_path = root / "brief.json"
            route_path = root / "route.json"
            # Directly verify conflict guard via cover_policy/cover_strategy review_check using synthetic desk/spec
            # Verify via cover_strategy.review_check by patching review_init so we test the exact master-conflict block
            from unittest.mock import patch
            img_3x4 = _make_png(root / "c_3x4.png", (1080, 1440), (21, 22, 24))
            img_9x16 = _make_png(root / "c_9x16.png", (1080, 1920), (22, 22, 24))
            img_4x3 = _make_png(root / "c_4x3.png", (1440, 1080), (23, 22, 24))
            img_16x9 = _make_png(root / "c_16x9.png", (1920, 1080), (24, 22, 24))
            spec_path = root / "spec.json"
            spec_path.write_text(json.dumps({
                "candidates": [{
                    "id": "ai1",
                    "master_plate_ref": master_a,
                    "outputs": [
                        {"ratio": "3:4"}, {"ratio": "9:16"}, {"ratio": "4:3"}, {"ratio": "16:9"},
                    ],
                }]
            }), encoding="utf-8")
            desk_path = root / "desk.json"
            desk_data = desk.new_project("r5-cover", "封面母版冲突测试")
            item = desk_data["items"][0]
            item["covers"] = [
                dict(id="c34", **img_3x4), dict(id="c916", **img_9x16),
                dict(id="c43", **img_4x3), dict(id="c169", **img_16x9),
            ]
            item["cover_pk"] = {
                "cover_stage": "final",
                "cover_build_ref": cw.reference(spec_path),
                "strategy_plan_ref": {"path": str(spec_path), "sha256": cw.reference(spec_path)["sha256"]},
                "candidates": [{
                    "id": "ai1",
                    "cover_by_ratio": {"3:4": "c34", "9:16": "c916", "4:3": "c43", "16:9": "c169"},
                }],
            }
            desk_path.write_text(json.dumps(desk_data, ensure_ascii=False), encoding="utf-8")
            rows = [
                {
                    "candidate_id": "ai1", "ratio": r, "image_ref": ref,
                    "master_plate_ref": master_b,
                    "semantic_correct": True, "mobile_readable": True, "subject_safe": True,
                    "observation": "ok", "visible_text": ["标题"],
                    "headline": "标题", "approved_labels": {},
                }
                for r, ref in [("3:4", img_3x4), ("9:16", img_9x16), ("4:3", img_4x3), ("16:9", img_16x9)]
            ]
            review_path = root / "review.json"
            review_path.write_text(json.dumps({
                "schema": "self-media.cover-visual-review.v1",
                "desk_ref": cw.reference(desk_path),
                "strategy_plan_ref": item["cover_pk"]["strategy_plan_ref"],
                "item_id": item["id"],
                "cover_stage": "final",
                "reviewer_kind": "agent",
                "reviewer": "synthetic-agent",
                "images": rows,
                "pairs": [],
            }, ensure_ascii=False), encoding="utf-8")
            expected_stub = {
                "strategy_plan_ref": item["cover_pk"]["strategy_plan_ref"],
                "cover_stage": "final",
                "images": rows,
                "pairs": [],
            }
            with patch.object(cs, "review_init", return_value=expected_stub):
                with self.assertRaisesRegex(ValueError, "cover_candidate_master_plate_mismatch"):
                    cs.review_check(review_path)

    # ---- 10. Round-6 boundary counterexamples ----
    def test_round6_counterexamples(self):
        # 1) Overlapping VKP core ranges across two chunks rejected
        overlap_core_vkp = {
            "result": [
                {
                    "chunk_offset_seconds": 0.0,
                    "chunk_core_start_seconds": 0.0,
                    "chunk_core_end_seconds": 6.0,
                    "chunk_end_seconds": 8.0,
                    "words": ["词"],
                    "timestamp": [[4700.0, 4900.0]],
                },
                {
                    "chunk_offset_seconds": 4.0,
                    "chunk_core_start_seconds": 4.5,
                    "chunk_core_end_seconds": 10.0,
                    "chunk_end_seconds": 10.0,
                    "words": ["词"],
                    "timestamp": [[4700.0, 4900.0]],
                },
            ]
        }
        with self.assertRaisesRegex(ValueError, "pacing_vkp_overlapping_core_ranges"):
            pacing.speech_spans(overlap_core_vkp, duration=12.0)

        # 2) Abandoned caption branch next to unlabeled delivery stream AND overwritten -vf null both rejected
        with tempfile.TemporaryDirectory() as td:
            sub = Path(td) / "sub.ass"
            sub.write_text("", encoding="utf-8")
            cmd_unlabeled_bypass = [
                "ffmpeg", "-i", "in.mp4",
                "-filter_complex", f"[0:v]ass='{sub.as_posix()}'[burned];[0:v]null",
                "out.mp4",
            ]
            self.assertFalse(captions._command_burns_caption_to_mapped_video(cmd_unlabeled_bypass, sub))
            cmd_overwritten_vf = [
                "ffmpeg", "-i", "in.mp4",
                "-vf", f"ass='{sub.as_posix()}'",
                "-vf", "null",
                "out.mp4",
            ]
            self.assertFalse(captions._command_burns_caption_to_mapped_video(cmd_overwritten_vf, sub))
            cmd_map_raw_stream = [
                "ffmpeg", "-i", "in.mp4",
                "-filter_complex", f"[0:v]ass='{sub.as_posix()}'[burned]",
                "-map", "0:v",
                "out.mp4",
            ]
            self.assertFalse(captions._command_burns_caption_to_mapped_video(cmd_map_raw_stream, sub))

        # 3) Non-medical external ASS with bare '医学科普' on Badge style MUST be blocked
        with tempfile.TemporaryDirectory() as td:
            bad_med = Path(td) / "bad_med.ass"
            bad_med.write_text(
                "[Events]\n"
                "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
                "Dialogue: 0,0:00:00.20,0:00:01.00,Badge,,0,0,0,,医学科普\n",
                encoding="utf-8",
            )
            non_med_choices = {
                "medical": {"decision": "not_applicable"},
                "insurance": {"decision": "not_applicable"},
                "ai": {"mode": "no_ai"},
            }
            with self.assertRaisesRegex(ValueError, "video_overlay_ass_applicability_mismatch: medical"):
                overlays.check_ass(non_med_choices, bad_med, external_caption_only=True)

        # 4) Cover single-master: build spec omits master_plate_ref, review fills it -> MUST fail
        import cover_strategy as cs
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            master_a = _make_png(root / "master_a.png", (1920, 1080), (20, 22, 24))
            img_3x4 = _make_png(root / "c_3x4.png", (1080, 1440), (21, 22, 24))
            img_9x16 = _make_png(root / "c_9x16.png", (1080, 1920), (22, 22, 24))
            img_4x3 = _make_png(root / "c_4x3.png", (1440, 1080), (23, 22, 24))
            img_16x9 = _make_png(root / "c_16x9.png", (1920, 1080), (24, 22, 24))
            spec_path = root / "spec_no_master.json"
            spec_path.write_text(json.dumps({
                "candidates": [{
                    "id": "ai1",
                    "outputs": [{"ratio": "3:4"}, {"ratio": "9:16"}, {"ratio": "4:3"}, {"ratio": "16:9"}],
                }]
            }), encoding="utf-8")
            desk_path = root / "desk.json"
            desk_data = desk.new_project("r6-cover", "无构建母版测试")
            item = desk_data["items"][0]
            item["covers"] = [
                dict(id="c34", **img_3x4), dict(id="c916", **img_9x16),
                dict(id="c43", **img_4x3), dict(id="c169", **img_16x9),
            ]
            item["cover_pk"] = {
                "cover_stage": "final",
                "cover_build_ref": cw.reference(spec_path),
                "strategy_plan_ref": {"path": str(spec_path), "sha256": cw.reference(spec_path)["sha256"]},
                "candidates": [{
                    "id": "ai1",
                    "cover_by_ratio": {"3:4": "c34", "9:16": "c916", "4:3": "c43", "16:9": "c169"},
                }],
            }
            desk_path.write_text(json.dumps(desk_data, ensure_ascii=False), encoding="utf-8")
            rows = [
                {
                    "candidate_id": "ai1", "ratio": r, "image_ref": ref,
                    "master_plate_ref": master_a,
                    "semantic_correct": True, "mobile_readable": True, "subject_safe": True,
                    "observation": "ok", "visible_text": ["标题"],
                    "headline": "标题", "approved_labels": {},
                }
                for r, ref in [("3:4", img_3x4), ("9:16", img_9x16), ("4:3", img_4x3), ("16:9", img_16x9)]
            ]
            review_path = root / "review.json"
            review_path.write_text(json.dumps({
                "schema": "self-media.cover-visual-review.v1",
                "desk_ref": cw.reference(desk_path),
                "strategy_plan_ref": item["cover_pk"]["strategy_plan_ref"],
                "item_id": item["id"],
                "cover_stage": "final",
                "reviewer_kind": "agent",
                "reviewer": "synthetic-agent",
                "images": rows,
                "pairs": [],
            }, ensure_ascii=False), encoding="utf-8")
            expected_stub = {
                "strategy_plan_ref": item["cover_pk"]["strategy_plan_ref"],
                "cover_stage": "final",
                "images": rows,
                "pairs": [],
            }
            with patch.object(cs, "review_init", return_value=expected_stub):
                with self.assertRaisesRegex(ValueError, "cover_candidate_master_plate_missing"):
                    cs.review_check(review_path)

        # 5) Legacy revision envelope + review receipt both missing fact_card_sha256 -> status(historical=False) MUST fail
        import shutil
        import uuid
        import author_writing_context as awc

        repo_root = Path(__file__).resolve().parents[1]
        tmp_root = (repo_root / ".test-runtime" / ("antiskip-r6-" + uuid.uuid4().hex)).resolve()
        tmp_root.mkdir(parents=True)
        try:
            db = tmp_root / "synthetic.sqlite3"
            src = tmp_root / "source.md"
            src.write_text("Synthetic source for Round-6 legacy missing binding.", encoding="utf-8")
            ctx_data = awc.prepare_context(db, {
                "content_id": "r6-content", "account_id": "r6-author", "genre": "spoken_script",
                "synthetic_only": True, "privacy_status": "non_sensitive", "source_ref": "synthetic:r6",
                "judgments": [],
            }, "r6-request")
            ctx_path = tmp_root / "context.json"
            ctx_path.write_text(json.dumps(ctx_data, ensure_ascii=False), encoding="utf-8")
            ev = {**awc.ref(src), "quote": "Synthetic source for Round-6"}
            legacy_pre = {
                "route": "expository", "actor": "synthetic_fixture", "source": ev,
                "items": [{"id": k, "state": "ready", "reason": "Synthetic " + k, "evidence": [ev]} for k in sorted(ei.PRE)],
            }
            ei.record_preflight(ctx_path, legacy_pre)
            draft = tmp_root / "draft.md"
            draft.write_text("历史旧稿正文。", encoding="utf-8")
            rev_payload = {
                "before": "旧稿",
                "reasons": [{"text": "r6", "actor": "synthetic_fixture", "source_ref": "synthetic:r6"}],
                "source_ref": "synthetic:r6",
                "privacy_status": "non_sensitive",
            }
            # Historical revision envelope has NO fact_card_sha256
            hist_env = awc.revision_envelope(db, ctx_path, draft, rev_payload, historical=True)
            self.assertNotIn("fact_card_sha256", hist_env)
            env_path = tmp_root / "rev.json"
            env_path.write_text(json.dumps(hist_env, ensure_ascii=False), encoding="utf-8")
            # Now add a locked fact card in preflight; formal evaluate/status MUST reject unbound legacy envelope
            fc = tmp_root / "fact.json"
            fc.write_text(json.dumps({
                "schema": "content-fact-card.v0",
                "content_id": "r6-content",
                "canonical_status": "locked_for_draft",
                "human_confirmation": {"quote": "Confirmed"},
            }, ensure_ascii=False), encoding="utf-8")
            ei.record_preflight(ctx_path, dict(legacy_pre, fact_card_ref=awc.ref(fc)))
            with self.assertRaisesRegex(Exception, "fact_card_ref"):
                ei.evaluate(env_path, {}, historical=False)
        finally:
            shutil.rmtree(tmp_root, ignore_errors=True)

    # ---- 11. Round-7 boundary counterexamples (VKP same-chunk multi-record + real FFmpeg mixed filter & nullsink) ----
    def test_round7_counterexamples(self):
        # 1) VKP: same chunk_index with multiple record_index rows sharing one core range MUST PASS
        same_chunk_multi_rec = {
            "result": [
                {
                    "chunk_index": 0,
                    "record_index": 0,
                    "chunk_offset_seconds": 0.0,
                    "chunk_core_start_seconds": 0.0,
                    "chunk_core_end_seconds": 10.0,
                    "chunk_end_seconds": 12.0,
                    "words": ["第一句"],
                    "timestamp": [[1000.0, 2000.0]],
                },
                {
                    "chunk_index": 0,
                    "record_index": 1,
                    "chunk_offset_seconds": 0.0,
                    "chunk_core_start_seconds": 0.0,
                    "chunk_core_end_seconds": 10.0,
                    "chunk_end_seconds": 12.0,
                    "words": ["第二句"],
                    "timestamp": [[4000.0, 5000.0]],
                },
                {
                    "chunk_index": 1,
                    "record_index": 0,
                    "chunk_offset_seconds": 8.0,
                    "chunk_core_start_seconds": 10.0,
                    "chunk_core_end_seconds": 20.0,
                    "chunk_end_seconds": 20.0,
                    "words": ["第三句"],
                    "timestamp": [[11000.0, 12000.0]],
                },
            ]
        }
        spans = pacing.speech_spans(same_chunk_multi_rec, duration=20.0)
        self.assertEqual(len(spans), 3)

        # Conflicting core bounds within the SAME chunk_index MUST FAIL
        inconsistent_same_chunk = {
            "result": [
                {
                    "chunk_index": 0, "record_index": 0,
                    "chunk_offset_seconds": 0.0, "chunk_core_start_seconds": 0.0, "chunk_core_end_seconds": 10.0,
                    "words": ["a"], "timestamp": [[1000.0, 1200.0]],
                },
                {
                    "chunk_index": 0, "record_index": 1,
                    "chunk_offset_seconds": 0.0, "chunk_core_start_seconds": 0.0, "chunk_core_end_seconds": 8.0,
                    "words": ["b"], "timestamp": [[2000.0, 2200.0]],
                },
            ]
        }
        with self.assertRaisesRegex(ValueError, "pacing_vkp_chunk_bounds_inconsistent"):
            pacing.speech_spans(inconsistent_same_chunk, duration=15.0)

        # 2) FFmpeg mixed -vf / -filter:v:0 override (BOTH orders) + nullsink side-branch (with real FFmpeg execution if available)
        import shutil
        import subprocess
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            sub = root / "sub.ass"
            sub.write_text(
                "[Script Info]\nScriptType: v4.00+\nPlayResX: 320\nPlayResY: 180\n\n"
                "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
                "Style: Default,Arial,24,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,1,0,2,10,10,10,1\n\n"
                "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
                "Dialogue: 0,0:00:00.00,0:00:01.00,Default,,0,0,0,,TEST\n",
                encoding="utf-8",
            )
            esc_sub = sub.as_posix().replace(":", r"\:")
            cmd_vf_then_v0_null = ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=black:s=320x180:d=0.2",
                                   "-vf", f"ass='{esc_sub}'", "-filter:v:0", "null", str(root / "o1.mp4")]
            cmd_v0_ass_then_vf_null = ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=black:s=320x180:d=0.2",
                                       "-filter:v:0", f"ass='{esc_sub}'", "-vf", "null", str(root / "o2.mp4")]
            cmd_v0_null_then_vf_ass = ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=black:s=320x180:d=0.2",
                                       "-filter:v:0", "null", "-vf", f"ass='{esc_sub}'", str(root / "o3.mp4")]
            cmd_nullsink_valid = ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=black:s=320x180:d=0.2",
                                  "-filter_complex", f"[0:v]split=2[a][b];[a]ass='{esc_sub}';[b]nullsink", str(root / "o4.mp4")]
            self.assertFalse(captions._command_burns_caption_to_mapped_video(cmd_vf_then_v0_null, sub))
            self.assertFalse(captions._command_burns_caption_to_mapped_video(cmd_v0_ass_then_vf_null, sub))
            self.assertTrue(captions._command_burns_caption_to_mapped_video(cmd_v0_null_then_vf_ass, sub))
            self.assertTrue(captions._command_burns_caption_to_mapped_video(cmd_nullsink_valid, sub))
            # Real FFmpeg frame-hash check: both overwritten-by-null orders equal unsubtitled baseline; valid orders differ!
            ffmpeg = shutil.which("ffmpeg")
            if ffmpeg:
                base_out = root / "base.raw"
                o1_out = root / "o1.raw"
                o2_out = root / "o2.raw"
                o3_out = root / "o3.raw"
                o4_out = root / "o4.raw"
                subprocess.run([ffmpeg, "-y", "-f", "lavfi", "-i", "color=c=black:s=320x180:d=0.1", "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", str(base_out)], check=True, capture_output=True)
                subprocess.run([ffmpeg, "-y", "-f", "lavfi", "-i", "color=c=black:s=320x180:d=0.1", "-vf", f"ass='{esc_sub}'", "-filter:v:0", "null", "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", str(o1_out)], check=True, capture_output=True)
                subprocess.run([ffmpeg, "-y", "-f", "lavfi", "-i", "color=c=black:s=320x180:d=0.1", "-filter:v:0", f"ass='{esc_sub}'", "-vf", "null", "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", str(o2_out)], check=True, capture_output=True)
                subprocess.run([ffmpeg, "-y", "-f", "lavfi", "-i", "color=c=black:s=320x180:d=0.1", "-filter:v:0", "null", "-vf", f"ass='{esc_sub}'", "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", str(o3_out)], check=True, capture_output=True)
                subprocess.run([ffmpeg, "-y", "-f", "lavfi", "-i", "color=c=black:s=320x180:d=0.1", "-filter_complex", f"[0:v]split=2[a][b];[a]ass='{esc_sub}';[b]nullsink", "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", str(o4_out)], check=True, capture_output=True)
                self.assertEqual(base_out.read_bytes(), o1_out.read_bytes())
                self.assertEqual(base_out.read_bytes(), o2_out.read_bytes())
                self.assertNotEqual(base_out.read_bytes(), o3_out.read_bytes())
                self.assertNotEqual(base_out.read_bytes(), o4_out.read_bytes())

    # ---- 12. Round-8 boundary counterexamples (FFmpeg -filter:0/-filter override & audio-only -map with unlabeled FC video) ----
    def test_round8_counterexamples(self):
        import shutil
        import subprocess
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            sub = root / "sub.ass"
            sub.write_text(
                "[Script Info]\nScriptType: v4.00+\nPlayResX: 320\nPlayResY: 180\n\n"
                "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
                "Style: Default,Arial,24,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,1,0,2,10,10,10,1\n\n"
                "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
                "Dialogue: 0,0:00:00.00,0:00:01.00,Default,,0,0,0,,TEST\n",
                encoding="utf-8",
            )
            esc_sub = sub.as_posix().replace(":", r"\:")
            av_in = root / "av.mp4"
            vonly_in = root / "vonly.mp4"

            # 1) Trailing -filter:0 null / -filter null / -filter:V null / -vf:1 null override -vf ass=... -> MUST BLOCK
            cmd_f0_override = ["ffmpeg", "-y", "-i", str(av_in), "-vf", f"ass='{esc_sub}'", "-filter:0", "null", str(root / "o_f0.mkv")]
            cmd_f_override = ["ffmpeg", "-y", "-i", str(vonly_in), "-vf", f"ass='{esc_sub}'", "-filter", "null", str(root / "o_f.mkv")]
            cmd_fV_override = ["ffmpeg", "-y", "-i", str(av_in), "-vf", f"ass='{esc_sub}'", "-filter:V", "null", str(root / "o_fV.mkv")]
            cmd_vf1_override = ["ffmpeg", "-y", "-i", str(av_in), "-vf", f"ass='{esc_sub}'", "-vf:1", "null", str(root / "o_vf1.mkv")]
            self.assertFalse(captions._command_burns_caption_to_mapped_video(cmd_f0_override, sub))
            self.assertFalse(captions._command_burns_caption_to_mapped_video(cmd_f_override, sub))
            self.assertFalse(captions._command_burns_caption_to_mapped_video(cmd_fV_override, sub))
            self.assertFalse(captions._command_burns_caption_to_mapped_video(cmd_vf1_override, sub))

            # Reverse order (-filter:0 null then -vf ass=...) and non-overlapping audio filter (-filter:1 anull) -> MUST PASS
            cmd_f0_then_vf_ass = ["ffmpeg", "-y", "-i", str(av_in), "-filter:0", "null", "-vf", f"ass='{esc_sub}'", str(root / "o_rev.mkv")]
            cmd_vf_ass_and_f1_anull = ["ffmpeg", "-y", "-i", str(av_in), "-vf", f"ass='{esc_sub}'", "-filter:1", "anull", str(root / "o_f1a.mkv")]
            self.assertTrue(captions._command_burns_caption_to_mapped_video(cmd_f0_then_vf_ass, sub))
            self.assertTrue(captions._command_burns_caption_to_mapped_video(cmd_vf_ass_and_f1_anull, sub))

            # Audio-first -map 0:a -map 0:v: video is output stream 1, so -filter:0 anull passes while -filter:1 null blocks!
            cmd_afirst_f0_ok = ["ffmpeg", "-y", "-i", str(av_in), "-map", "0:a", "-map", "0:v", "-vf", f"ass='{esc_sub}'", "-filter:0", "anull", str(root / "o_af0.mkv")]
            cmd_afirst_f1_bad = ["ffmpeg", "-y", "-i", str(av_in), "-map", "0:a", "-map", "0:v", "-vf", f"ass='{esc_sub}'", "-filter:1", "null", str(root / "o_af1.mkv")]
            # Optional audio map -map 0:a? may emit 0 streams -> video may be stream 0 -> -filter:0 null MUST BLOCK!
            cmd_opt_a_f0_bad = ["ffmpeg", "-y", "-i", str(vonly_in), "-map", "0:a?", "-map", "0:v", "-vf", f"ass='{esc_sub}'", "-filter:0", "null", str(root / "o_opta.mkv")]
            self.assertTrue(captions._command_burns_caption_to_mapped_video(cmd_afirst_f0_ok, sub))
            self.assertFalse(captions._command_burns_caption_to_mapped_video(cmd_afirst_f1_bad, sub))
            self.assertFalse(captions._command_burns_caption_to_mapped_video(cmd_opt_a_f0_bad, sub))

            # 2) Audio-only -map with unlabeled burned -filter_complex / -lavfi video -> FFmpeg delivers burned video -> MUST PASS
            cmd_fc_unlabeled_map_a = ["ffmpeg", "-y", "-i", str(av_in), "-filter_complex", f"[0:v]ass='{esc_sub}'", "-map", "0:a", str(root / "o_fca.mkv")]
            cmd_lavfi_unlabeled_map_a = ["ffmpeg", "-y", "-i", str(av_in), "-lavfi", f"[0:v]ass='{esc_sub}'", "-map", "0:a:0", str(root / "o_lavfi.mkv")]
            cmd_fc_audio_plus_vf = ["ffmpeg", "-y", "-i", str(av_in), "-filter_complex", "[0:a]anull", "-map", "0:v", "-vf", f"ass='{esc_sub}'", str(root / "o_fcavf.mkv")]
            cmd_fc_concat_map = [
                "ffmpeg", "-y", "-i", str(av_in), "-i", str(av_in),
                "-filter_complex", f"[0:v][0:a][1:v][1:a]concat=n=2:v=1:a=1[vc][ac];[vc]ass='{esc_sub}'[vout]",
                "-map", "[vout]", "-map", "[ac]", str(root / "o_concat.mkv"),
            ]
            self.assertTrue(captions._command_burns_caption_to_mapped_video(cmd_fc_unlabeled_map_a, sub))
            self.assertTrue(captions._command_burns_caption_to_mapped_video(cmd_lavfi_unlabeled_map_a, sub))
            self.assertTrue(captions._command_burns_caption_to_mapped_video(cmd_fc_audio_plus_vf, sub))
            self.assertTrue(captions._command_burns_caption_to_mapped_video(cmd_fc_concat_map, sub))

            # 3) Audio-only -map with NO video stream (e.g. -vf ass + -map 0:a), or extra unsubtitled video stream -> MUST BLOCK
            cmd_vf_map_a_only = ["ffmpeg", "-y", "-i", str(av_in), "-vf", f"ass='{esc_sub}'", "-map", "0:a", str(root / "o_novid.mkv")]
            cmd_fc_unlabeled_plus_map_v = ["ffmpeg", "-y", "-i", str(av_in), "-filter_complex", f"[0:v]ass='{esc_sub}'", "-map", "0:v", str(root / "o_dupv.mkv")]
            cmd_fc_split_unlabeled_null_and_map_burned = [
                "ffmpeg", "-y", "-i", str(av_in),
                "-filter_complex", f"[0:v]split=2[a][b];[a]ass='{esc_sub}'[burned];[b]null",
                "-map", "[burned]", "-map", "0:a", str(root / "o_splitbad.mkv"),
            ]
            cmd_fc_two_graphs_null_first = [
                "ffmpeg", "-y", "-i", str(av_in),
                "-filter_complex", "[0:v]null",
                "-filter_complex", f"[0:v]ass='{esc_sub}'",
                str(root / "o_fc2.mkv"),
            ]
            self.assertFalse(captions._command_burns_caption_to_mapped_video(cmd_vf_map_a_only, sub))
            self.assertFalse(captions._command_burns_caption_to_mapped_video(cmd_fc_unlabeled_plus_map_v, sub))
            self.assertFalse(captions._command_burns_caption_to_mapped_video(cmd_fc_split_unlabeled_null_and_map_burned, sub))
            self.assertFalse(captions._command_burns_caption_to_mapped_video(cmd_fc_two_graphs_null_first, sub))

            # 4) Real FFmpeg frame-hash verification for both Round-8 counterexamples + audio-first & split-bypass cases
            ffmpeg = shutil.which("ffmpeg")
            if ffmpeg:
                subprocess.run([ffmpeg, "-y", "-f", "lavfi", "-i", "color=c=black:s=320x180:d=0.1",
                                "-f", "lavfi", "-i", "sine=f=440:d=0.1", "-c:v", "libx264", "-c:a", "aac", str(av_in)],
                               check=True, capture_output=True)
                subprocess.run([ffmpeg, "-y", "-f", "lavfi", "-i", "color=c=black:s=320x180:d=0.1",
                                "-c:v", "libx264", str(vonly_in)], check=True, capture_output=True)

                def _first_video_frame_bytes(media: Path) -> bytes:
                    raw = media.with_suffix(".raw")
                    subprocess.run([ffmpeg, "-y", "-i", str(media), "-map", "0:v:0", "-frames:v", "1",
                                    "-f", "rawvideo", "-pix_fmt", "rgb24", str(raw)], check=True, capture_output=True)
                    return raw.read_bytes()

                base_mkv = root / "base.mkv"
                subprocess.run([ffmpeg, "-y", "-i", str(av_in), "-c:v", "libx264", "-c:a", "aac", str(base_mkv)],
                               check=True, capture_output=True)
                base_frame = _first_video_frame_bytes(base_mkv)

                for out_name, args, expect_burned, inp in [
                    ("r8_f0_null.mkv", ["-vf", f"ass='{esc_sub}'", "-filter:0", "null"], False, av_in),
                    ("r8_f_null.mkv", ["-vf", f"ass='{esc_sub}'", "-filter", "null"], False, vonly_in),
                    ("r8_fc_map_a.mkv", ["-filter_complex", f"[0:v]ass='{esc_sub}'", "-map", "0:a"], True, av_in),
                    ("r8_afirst_f0_ok.mkv", ["-map", "0:a", "-map", "0:v", "-vf", f"ass='{esc_sub}'", "-filter:0", "anull"], True, av_in),
                    ("r8_afirst_f1_bad.mkv", ["-map", "0:a", "-map", "0:v", "-vf", f"ass='{esc_sub}'", "-filter:1", "null"], False, av_in),
                    ("r8_opt_a_f0_bad.mkv", ["-map", "0:a?", "-map", "0:v", "-vf", f"ass='{esc_sub}'", "-filter:0", "null"], False, vonly_in),
                    ("r8_split_unlabeled_null.mkv", ["-filter_complex", f"[0:v]split=2[a][b];[a]ass='{esc_sub}'[burned];[b]null", "-map", "[burned]", "-map", "0:a"], False, av_in),
                ]:
                    out_p = root / out_name
                    cmd = [ffmpeg, "-y", "-i", str(inp), *args, "-c:v", "libx264", "-c:a", "aac", str(out_p)]
                    subprocess.run(cmd, check=True, capture_output=True)
                    frame_bytes = _first_video_frame_bytes(out_p)
                    self.assertEqual(captions._command_burns_caption_to_mapped_video(cmd, sub), expect_burned, out_name)
                    if expect_burned:
                        self.assertNotEqual(frame_bytes, base_frame, out_name)
                    else:
                        self.assertEqual(frame_bytes, base_frame, out_name)

    # ---- 13. Round-9 boundary counterexamples (multi-video -map 0:v, pre-concat partial burn, numeric map, neg/opt/multi-out) ----
    def test_round9_counterexamples(self):
        import shutil
        import subprocess
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            sub = root / "cue.ass"
            sub.write_text(
                "[Script Info]\nScriptType: v4.00+\nPlayResX: 320\nPlayResY: 180\n\n"
                "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
                "Style: Default,Arial,24,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,1,0,2,10,10,10,1\n\n"
                "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
                "Dialogue: 0,0:00:00.00,0:00:01.20,Default,,0,0,0,,TEST\n",
                encoding="utf-8",
            )
            esc_sub = sub.as_posix().replace(":", r"\:")
            fake_vva = root / "nonexistent-vva.mkv"

            # Command-only checks (even without input files on disk): grouped -map 0:v, pre-concat, enable=0, neg/opt/multi-output
            self.assertFalse(captions._command_burns_caption_to_mapped_video(
                ["ffmpeg", "-i", str(fake_vva), "-map", "0:v", "-vf", f"ass='{esc_sub}'", "-filter:v:1", "null", "out.mkv"], sub))
            self.assertFalse(captions._command_burns_caption_to_mapped_video(
                ["ffmpeg", "-i", str(fake_vva), "-map", "0:v", "-vf", f"ass='{esc_sub}'", "-filter:1", "null", "out.mkv"], sub))
            self.assertFalse(captions._command_burns_caption_to_mapped_video(
                ["ffmpeg", "-i", str(fake_vva), "-filter_complex", f"[0:v:0]ass='{esc_sub}'[a];[a][0:v:1]concat=n=2:v=1:a=0[v]", "-map", "[v]", "out.mkv"], sub))
            self.assertTrue(captions._command_burns_caption_to_mapped_video(
                ["ffmpeg", "-i", str(fake_vva), "-filter_complex", f"[0:v:0][0:v:1]concat=n=2:v=1:a=0,ass='{esc_sub}'[v]", "-map", "[v]", "out.mkv"], sub))
            self.assertFalse(captions._command_burns_caption_to_mapped_video(
                ["ffmpeg", "-i", str(fake_vva), "-vf", f"ass='{esc_sub}':enable=0", "out.mkv"], sub))
            self.assertFalse(captions._command_burns_caption_to_mapped_video(
                ["ffmpeg", "-i", str(fake_vva), "-vf", f"ass='{esc_sub}':filename='other.ass'", "out.mkv"], sub))
            self.assertFalse(captions._command_burns_caption_to_mapped_video(
                ["ffmpeg", "-i", str(fake_vva), "-map", "0:v", "-map", "-0:v:0", "-map", "0:a", "-vf", f"ass='{esc_sub}'", "out.mkv"], sub))
            self.assertFalse(captions._command_burns_caption_to_mapped_video(
                ["ffmpeg", "-i", str(fake_vva), "-map", "0:a", "-map", "0:v?", "-vf", f"ass='{esc_sub}'", "out.mkv"], sub))
            self.assertFalse(captions._command_burns_caption_to_mapped_video(
                ["ffmpeg", "-i", str(fake_vva), "-vf", f"ass='{esc_sub}'", "out1.mkv", "-c:v", "libx264", "out2.mkv"], sub))

            # Real FFmpeg 8.1 encoding + ffprobe stream expansion + formal receipt check
            ffmpeg = shutil.which("ffmpeg")
            if ffmpeg:
                in_av = root / "input-av.mkv"
                in_vva = root / "input-vva.mkv"
                in_a = root / "input-a.mka"
                subprocess.run([ffmpeg, "-y", "-f", "lavfi", "-i", "color=c=black:s=320x180:r=10:d=0.6",
                                "-f", "lavfi", "-i", "sine=f=440:d=0.6", "-c:v", "libx264", "-c:a", "aac", str(in_av)],
                               check=True, capture_output=True)
                subprocess.run([ffmpeg, "-y", "-f", "lavfi", "-i", "color=c=black:s=320x180:r=10:d=0.6",
                                "-f", "lavfi", "-i", "color=c=black:s=320x180:r=10:d=0.6",
                                "-f", "lavfi", "-i", "sine=f=440:d=0.6",
                                "-map", "0:v", "-map", "1:v", "-map", "2:a", "-c:v", "libx264", "-c:a", "aac", str(in_vva)],
                               check=True, capture_output=True)
                subprocess.run([ffmpeg, "-y", "-f", "lavfi", "-i", "sine=f=440:d=0.6", "-c:a", "aac", str(in_a)],
                               check=True, capture_output=True)

                def _frame_at(media: Path, v_stream: int = 0, ss: str = "0.2") -> bytes:
                    raw = root / f"{media.stem}_v{v_stream}_{ss.replace('.', '_')}.raw"
                    subprocess.run([ffmpeg, "-y", "-ss", ss, "-i", str(media), "-map", f"0:v:{v_stream}",
                                    "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", str(raw)],
                                   check=True, capture_output=True)
                    return raw.read_bytes()

                base_frame = _frame_at(in_av, 0, "0.2")

                # P1-1a: grouped -map 0:v with -filter:v:1 null -> v0 burned, v1 bare -> gate MUST REJECT
                out_v1 = root / "grouped-rel.mkv"
                cmd_v1 = [ffmpeg, "-y", "-i", str(in_vva), "-map", "0:v", "-vf", f"ass='{esc_sub}'", "-filter:v:1", "null", "-c:v", "libx264", str(out_v1)]
                subprocess.run(cmd_v1, check=True, capture_output=True)
                self.assertNotEqual(_frame_at(out_v1, 0), base_frame)
                self.assertEqual(_frame_at(out_v1, 1), base_frame)
                self.assertFalse(captions._command_burns_caption_to_mapped_video(cmd_v1, sub))

                # P1-1b: grouped -map 0:v with -filter:1 null -> v0 burned, v1 bare -> gate MUST REJECT
                out_abs1 = root / "grouped-abs.mkv"
                cmd_abs1 = [ffmpeg, "-y", "-i", str(in_vva), "-map", "0:v", "-vf", f"ass='{esc_sub}'", "-filter:1", "null", "-c:v", "libx264", str(out_abs1)]
                subprocess.run(cmd_abs1, check=True, capture_output=True)
                self.assertNotEqual(_frame_at(out_abs1, 0), base_frame)
                self.assertEqual(_frame_at(out_abs1, 1), base_frame)
                self.assertFalse(captions._command_burns_caption_to_mapped_video(cmd_abs1, sub))

                # Positive control for grouped -map 0:v (no override): BOTH v0 and v1 burned -> gate MUST ACCEPT
                out_all = root / "grouped-all.mkv"
                cmd_all = [ffmpeg, "-y", "-i", str(in_vva), "-map", "0:v", "-vf", f"ass='{esc_sub}'", "-c:v", "libx264", str(out_all)]
                subprocess.run(cmd_all, check=True, capture_output=True)
                self.assertNotEqual(_frame_at(out_all, 0), base_frame)
                self.assertNotEqual(_frame_at(out_all, 1), base_frame)
                self.assertTrue(captions._command_burns_caption_to_mapped_video(cmd_all, sub))

                # P1-2: pre-concat partial burn -> 0.2s burned, 0.9s bare -> gate MUST REJECT; post-concat burn -> 0.2s & 0.9s burned -> MUST ACCEPT
                out_c_bad = root / "concat-bad.mkv"
                cmd_c_bad = [ffmpeg, "-y", "-i", str(in_vva), "-filter_complex",
                             f"[0:v:0]ass='{esc_sub}'[a];[a][0:v:1]concat=n=2:v=1:a=0[v]", "-map", "[v]", "-c:v", "libx264", str(out_c_bad)]
                subprocess.run(cmd_c_bad, check=True, capture_output=True)
                self.assertNotEqual(_frame_at(out_c_bad, 0, "0.2"), base_frame)
                self.assertEqual(_frame_at(out_c_bad, 0, "0.9"), base_frame)
                self.assertFalse(captions._command_burns_caption_to_mapped_video(cmd_c_bad, sub))

                out_c_ok = root / "concat-ok.mkv"
                cmd_c_ok = [ffmpeg, "-y", "-i", str(in_vva), "-filter_complex",
                            f"[0:v:0][0:v:1]concat=n=2:v=1:a=0,ass='{esc_sub}'[v]", "-map", "[v]", "-c:v", "libx264", str(out_c_ok)]
                subprocess.run(cmd_c_ok, check=True, capture_output=True)
                self.assertNotEqual(_frame_at(out_c_ok, 0, "0.2"), base_frame)
                self.assertNotEqual(_frame_at(out_c_ok, 0, "0.9"), base_frame)
                self.assertTrue(captions._command_burns_caption_to_mapped_video(cmd_c_ok, sub))

                # P2: numeric audio-first map (-map 0:1 -map 0:0) + -filter:0 anull -> video burned -> gate MUST ACCEPT
                out_num = root / "numeric-afirst.mkv"
                cmd_num = [ffmpeg, "-y", "-i", str(in_av), "-map", "0:1", "-map", "0:0", "-vf", f"ass='{esc_sub}'", "-filter:0", "anull",
                           "-c:v", "libx264", "-c:a", "aac", str(out_num)]
                subprocess.run(cmd_num, check=True, capture_output=True)
                self.assertNotEqual(_frame_at(out_num, 0, "0.2"), base_frame)
                self.assertTrue(captions._command_burns_caption_to_mapped_video(cmd_num, sub))

                # Indexed negative map removing the only video stream -> MUST REJECT; removing 1 of 2 video streams -> MUST ACCEPT
                out_neg = root / "indexed-neg.mkv"
                cmd_neg = [ffmpeg, "-y", "-i", str(in_av), "-map", "0:v", "-map", "-0:v:0", "-map", "0:a", "-vf", f"ass='{esc_sub}'", "-c:a", "aac", str(out_neg)]
                subprocess.run(cmd_neg, check=True, capture_output=True)
                self.assertFalse(captions._command_burns_caption_to_mapped_video(cmd_neg, sub))

                out_neg_keep1 = root / "indexed-neg-keep1.mkv"
                cmd_neg_keep1 = [ffmpeg, "-y", "-i", str(in_vva), "-map", "0:v", "-map", "-0:v:0", "-vf", f"ass='{esc_sub}'", "-c:v", "libx264", str(out_neg_keep1)]
                subprocess.run(cmd_neg_keep1, check=True, capture_output=True)
                self.assertNotEqual(_frame_at(out_neg_keep1, 0, "0.2"), base_frame)
                self.assertTrue(captions._command_burns_caption_to_mapped_video(cmd_neg_keep1, sub))

                # Optional absent video (-i audio_only -map 0:a -map 0:v?) -> MUST REJECT; optional present video -> MUST ACCEPT
                out_opt_absent = root / "opt-absent.mkv"
                cmd_opt_absent = [ffmpeg, "-y", "-i", str(in_a), "-map", "0:a", "-map", "0:v?", "-vf", f"ass='{esc_sub}'", "-c:a", "aac", str(out_opt_absent)]
                subprocess.run(cmd_opt_absent, check=True, capture_output=True)
                self.assertFalse(captions._command_burns_caption_to_mapped_video(cmd_opt_absent, sub))

                out_opt_present = root / "opt-present.mkv"
                cmd_opt_present = [ffmpeg, "-y", "-i", str(in_av), "-map", "0:a", "-map", "0:v?", "-vf", f"ass='{esc_sub}'", "-c:v", "libx264", "-c:a", "aac", str(out_opt_present)]
                subprocess.run(cmd_opt_present, check=True, capture_output=True)
                self.assertNotEqual(_frame_at(out_opt_present, 0, "0.2"), base_frame)
                self.assertTrue(captions._command_burns_caption_to_mapped_video(cmd_opt_present, sub))

                # Multi-output: first burned, second unburned -> standalone REJECT, receipt bound to second REJECT, receipt bound to first ACCEPT
                out_m1 = root / "multi-1.mkv"
                out_m2 = root / "multi-2.mkv"
                cmd_multi = [ffmpeg, "-y", "-i", str(in_av), "-vf", f"ass='{esc_sub}'", "-c:v", "libx264", str(out_m1),
                             "-c:v", "libx264", str(out_m2)]
                subprocess.run(cmd_multi, check=True, capture_output=True)
                self.assertNotEqual(_frame_at(out_m1, 0, "0.2"), base_frame)
                self.assertEqual(_frame_at(out_m2, 0, "0.2"), base_frame)
                self.assertFalse(captions._command_burns_caption_to_mapped_video(cmd_multi, sub))
                self.assertFalse(captions._command_burns_caption_to_mapped_video(cmd_multi, sub, target_outputs=[out_m2]))
                self.assertTrue(captions._command_burns_caption_to_mapped_video(cmd_multi, sub, target_outputs=[out_m1]))

                # End-to-end _receipt_burns_caption with official 5-key ffmpeg_execution_receipt.v1 artifacts
                def _outlet_art(p: Path) -> dict:
                    r = cw.reference(p)
                    return {**r, "bytes": p.stat().st_size, "content_kind": "binary", "canonical_sha256": None}

                sub_ref = cw.reference(sub)
                sub_art = _outlet_art(sub)
                vva_art = _outlet_art(in_vva)
                bad_receipt = {
                    "command": cmd_v1,
                    "inputs": [{"role": "edited_media", "artifact": vva_art}, {"role": "subtitle", "artifact": sub_art}],
                    "outputs": [{"role": "candidate", "artifact": _outlet_art(out_v1)}],
                }
                good_receipt = {
                    "command": cmd_all,
                    "inputs": [{"role": "edited_media", "artifact": vva_art}, {"role": "subtitle", "artifact": sub_art}],
                    "outputs": [{"role": "candidate", "artifact": _outlet_art(out_all)}],
                }
                multi_bad_receipt = {
                    "command": cmd_multi,
                    "inputs": [{"role": "edited_media", "artifact": _outlet_art(in_av)}, {"role": "subtitle", "artifact": sub_art}],
                    "outputs": [{"role": "candidate", "artifact": _outlet_art(out_m2)}],
                }
                concat_bad_receipt = {
                    "command": cmd_c_bad,
                    "inputs": [{"role": "edited_media", "artifact": vva_art}, {"role": "subtitle", "artifact": sub_art}],
                    "outputs": [{"role": "candidate", "artifact": _outlet_art(out_c_bad)}],
                }
                self.assertFalse(captions._receipt_burns_caption(bad_receipt, sub_ref, sub))
                self.assertTrue(captions._receipt_burns_caption(good_receipt, sub_ref, sub))
                self.assertFalse(captions._receipt_burns_caption(multi_bad_receipt, sub_ref, sub))
                self.assertFalse(captions._receipt_burns_caption(concat_bad_receipt, sub_ref, sub))

    # ---- 14. Round-10 boundary counterexamples (-an stream shift, multi-stream lavfi, multi-receipt concat, audio sidecar) ----
    def test_round10_counterexamples(self):
        import shutil
        import subprocess
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            sub = root / "cue.ass"
            sub.write_text(
                "[Script Info]\nScriptType: v4.00+\nPlayResX: 320\nPlayResY: 180\n\n"
                "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
                "Style: Default,Arial,24,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,1,0,2,10,10,10,1\n\n"
                "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
                "Dialogue: 0,0:00:00.00,0:00:01.20,Default,,0,0,0,,TEST\n",
                encoding="utf-8",
            )
            esc_sub = sub.as_posix().replace(":", r"\:")
            ffmpeg = shutil.which("ffmpeg")
            if not ffmpeg:
                return

            in_vva = root / "input-vva.mkv"
            subprocess.run([ffmpeg, "-y", "-f", "lavfi", "-i", "color=c=black:s=320x180:r=10:d=0.6",
                            "-f", "lavfi", "-i", "color=c=black:s=320x180:r=10:d=0.6",
                            "-f", "lavfi", "-i", "sine=f=440:d=0.6",
                            "-map", "0:v", "-map", "1:v", "-map", "2:a", "-c:v", "libx264", "-c:a", "aac", str(in_vva)],
                           check=True, capture_output=True)

            def _frame_at(media: Path, v_stream: int = 0, ss: str = "0.2") -> bytes:
                raw = root / f"{media.stem}_v{v_stream}_{ss.replace('.', '_')}.raw"
                subprocess.run([ffmpeg, "-y", "-ss", ss, "-i", str(media), "-map", f"0:v:{v_stream}",
                                "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", str(raw)],
                               check=True, capture_output=True)
                return raw.read_bytes()

            def _outlet_art(p: Path) -> dict:
                r = cw.reference(p)
                return {**r, "bytes": p.stat().st_size, "content_kind": "binary", "canonical_sha256": None}

            base_frame = _frame_at(in_vva, 0, "0.2")
            sub_ref = cw.reference(sub)
            sub_art = _outlet_art(sub)
            vva_art = _outlet_art(in_vva)

            # P1-1: -an drops explicitly mapped 0:a, shifting 0:v:1 to output stream 1 -> -filter:1 null clobbers v1!
            out_an_bad = root / "dropped-audio-shifts-v1.mkv"
            cmd_an_bad = [ffmpeg, "-y", "-i", str(in_vva), "-map", "0:v:0", "-map", "0:a", "-map", "0:v:1",
                          "-an", "-vf", f"ass='{esc_sub}'", "-filter:1", "null", "-c:v", "libx264", str(out_an_bad)]
            subprocess.run(cmd_an_bad, check=True, capture_output=True)
            self.assertNotEqual(_frame_at(out_an_bad, 0), base_frame)
            self.assertEqual(_frame_at(out_an_bad, 1), base_frame)
            self.assertFalse(captions._command_burns_caption_to_mapped_video(cmd_an_bad, sub))

            out_an_ok = root / "dropped-audio-control.mkv"
            cmd_an_ok = [ffmpeg, "-y", "-i", str(in_vva), "-map", "0:v:0", "-map", "0:a", "-map", "0:v:1",
                         "-an", "-vf", f"ass='{esc_sub}'", "-c:v", "libx264", str(out_an_ok)]
            subprocess.run(cmd_an_ok, check=True, capture_output=True)
            self.assertNotEqual(_frame_at(out_an_ok, 0), base_frame)
            self.assertNotEqual(_frame_at(out_an_ok, 1), base_frame)
            self.assertTrue(captions._command_burns_caption_to_mapped_video(cmd_an_ok, sub))

            # P1-2: Multi-stream lavfi input (2 videos) + -map 0:v -filter:v:1 null -> v1 bare -> MUST REJECT
            lavfi_two = "color=c=black:s=320x180:r=10:d=0.6[out0];color=c=black:s=320x180:r=10:d=0.6[out1]"
            out_lav_bad = root / "lavfi-v1-bare.mkv"
            cmd_lav_bad = [ffmpeg, "-y", "-f", "lavfi", "-i", lavfi_two, "-i", str(in_vva),
                           "-map", "0:v", "-map", "1:a", "-vf", f"ass='{esc_sub}'", "-filter:v:1", "null",
                           "-c:v", "libx264", "-c:a", "aac", str(out_lav_bad)]
            subprocess.run(cmd_lav_bad, check=True, capture_output=True)
            self.assertNotEqual(_frame_at(out_lav_bad, 0), base_frame)
            self.assertEqual(_frame_at(out_lav_bad, 1), base_frame)
            self.assertFalse(captions._command_burns_caption_to_mapped_video(cmd_lav_bad, sub))

            out_lav_ok = root / "lavfi-both-burned.mkv"
            cmd_lav_ok = [ffmpeg, "-y", "-f", "lavfi", "-i", lavfi_two, "-i", str(in_vva),
                          "-map", "0:v", "-map", "1:a", "-vf", f"ass='{esc_sub}'",
                          "-c:v", "libx264", "-c:a", "aac", str(out_lav_ok)]
            subprocess.run(cmd_lav_ok, check=True, capture_output=True)
            self.assertNotEqual(_frame_at(out_lav_ok, 0), base_frame)
            self.assertNotEqual(_frame_at(out_lav_ok, 1), base_frame)
            self.assertTrue(captions._command_burns_caption_to_mapped_video(cmd_lav_ok, sub))

            # P1-3: Multi-step render chain where Pass 1 burns and Pass 2 concats an unburned clip -> MUST REJECT!
            out_p1 = root / "pass1-burned.mkv"
            cmd_p1 = [ffmpeg, "-y", "-i", str(in_vva), "-map", "0:v:0", "-vf", f"ass='{esc_sub}'", "-c:v", "libx264", str(out_p1)]
            subprocess.run(cmd_p1, check=True, capture_output=True)
            r1 = {
                "command": cmd_p1,
                "inputs": [{"role": "edited_media", "artifact": vva_art}, {"role": "subtitle", "artifact": sub_art}],
                "outputs": [{"role": "candidate", "artifact": _outlet_art(out_p1)}],
            }
            out_p2_bad = root / "pass2-concat-bad.mkv"
            cmd_p2_bad = [ffmpeg, "-y", "-i", str(out_p1), "-i", str(in_vva),
                          "-filter_complex", "[0:v][1:v:1]concat=n=2:v=1:a=0[v]", "-map", "[v]", "-c:v", "libx264", str(out_p2_bad)]
            subprocess.run(cmd_p2_bad, check=True, capture_output=True)
            self.assertNotEqual(_frame_at(out_p2_bad, 0, "0.2"), base_frame)
            self.assertEqual(_frame_at(out_p2_bad, 0, "0.9"), base_frame)
            r2_bad = {
                "command": cmd_p2_bad,
                "inputs": [{"role": "edited_media", "artifact": _outlet_art(out_p1)}, {"role": "edited_media", "artifact": vva_art}],
                "outputs": [{"role": "candidate", "artifact": _outlet_art(out_p2_bad)}],
            }
            # Pass 2 audio remux preserving Pass 1 burned video with -c:v copy -> MUST ACCEPT!
            out_p2_preserve = root / "pass2-preserve-remux.mkv"
            cmd_p2_preserve = [ffmpeg, "-y", "-i", str(out_p1), "-i", str(in_vva),
                               "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac", str(out_p2_preserve)]
            subprocess.run(cmd_p2_preserve, check=True, capture_output=True)
            self.assertNotEqual(_frame_at(out_p2_preserve, 0, "0.2"), base_frame)
            r2_preserve = {
                "command": cmd_p2_preserve,
                "inputs": [{"role": "edited_media", "artifact": _outlet_art(out_p1)}, {"role": "edited_media", "artifact": vva_art}],
                "outputs": [{"role": "candidate", "artifact": _outlet_art(out_p2_preserve)}],
            }
            ok1, burned_set = captions._receipt_caption_verified_outputs(r1, sub_ref, sub)
            self.assertTrue(ok1)
            ok2_bad, _ = captions._receipt_caption_verified_outputs(r2_bad, sub_ref, sub, burned_media=frozenset(burned_set))
            self.assertFalse(ok2_bad)
            ok2_ok, _ = captions._receipt_caption_verified_outputs(r2_preserve, sub_ref, sub, burned_media=frozenset(burned_set))
            self.assertTrue(ok2_ok)

            # P2: Multi-output receipt with burned video candidate + diagnostic pure-audio .mka sidecar -> MUST ACCEPT!
            out_vid = root / "cand-with-sidecar.mkv"
            out_mka = root / "cand-with-sidecar.mka"
            cmd_sidecar = [ffmpeg, "-y", "-i", str(in_vva), "-map", "0:v:0", "-vf", f"ass='{esc_sub}'", "-c:v", "libx264", str(out_vid),
                           "-map", "0:a:0", "-c:a", "aac", str(out_mka)]
            subprocess.run(cmd_sidecar, check=True, capture_output=True)
            self.assertNotEqual(_frame_at(out_vid, 0, "0.2"), base_frame)
            r_sidecar = {
                "command": cmd_sidecar,
                "inputs": [{"role": "edited_media", "artifact": vva_art}, {"role": "subtitle", "artifact": sub_art}],
                "outputs": [
                    {"role": "candidate", "artifact": _outlet_art(out_vid)},
                    {"role": "diagnostic", "artifact": _outlet_art(out_mka)},
                ],
            }
            self.assertTrue(captions._command_burns_caption_to_mapped_video(cmd_sidecar, sub))
            self.assertTrue(captions._receipt_burns_caption(r_sidecar, sub_ref, sub))

    # ---- 15. Round-11 boundary counterexamples (selected video role binding, post-burn overlay occlusion, output-side -ss) ----
    def test_round11_counterexamples(self):
        import shutil
        import subprocess
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            sub = root / "cue.ass"
            sub.write_text(
                "[Script Info]\nScriptType: v4.00+\nPlayResX: 320\nPlayResY: 180\n\n"
                "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
                "Style: Default,Arial,24,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,1,0,2,10,10,10,1\n\n"
                "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
                "Dialogue: 0,0:00:00.00,0:00:01.20,Default,,0,0,0,,TEST\n",
                encoding="utf-8",
            )
            esc_sub = sub.as_posix().replace(":", r"\:")
            ffmpeg = shutil.which("ffmpeg")
            if not ffmpeg:
                return

            clean = root / "clean.mkv"
            subprocess.run([ffmpeg, "-y", "-f", "lavfi", "-i", "color=c=black:s=320x180:r=10:d=1.6",
                            "-c:v", "libx264", str(clean)], check=True, capture_output=True)

            def _frame_png_and_box(media: Path, ss: str) -> tuple[Path, list[int] | None]:
                png = root / f"{media.stem}_at_{ss.replace('.', '_')}.png"
                subprocess.run([ffmpeg, "-y", "-ss", ss, "-i", str(media), "-frames:v", "1", str(png)],
                               check=True, capture_output=True)
                with Image.open(png) as im:
                    bbox = im.convert("L").point(lambda p: 255 if p > 120 else 0).getbbox()
                return png, (list(bbox) if bbox else None)

            def _outlet_art(p: Path) -> dict:
                r = cw.reference(p)
                return {**r, "bytes": p.stat().st_size, "content_kind": "binary", "canonical_sha256": None}

            sub_ref = cw.reference(sub)
            sub_art = _outlet_art(sub)
            clean_art = _outlet_art(clean)
            pack = root / "pack.json"
            pack.write_text(json.dumps({
                "requests": [{"subtitle_cues": [{"start_seconds": 0.0, "end_seconds": 1.2, "text": "TEST"}]}]
            }), encoding="utf-8")
            pack_ref = cw.reference(pack)

            # Control fresh burn -> both 0.6s and 1.1s have subtitles
            burned = root / "burned.mkv"
            cmd_burn = [ffmpeg, "-y", "-i", str(clean), "-vf", f"ass='{esc_sub}'", "-c:v", "libx264", str(burned)]
            subprocess.run(cmd_burn, check=True, capture_output=True)
            png_b06, box_b06 = _frame_png_and_box(burned, "0.6")
            _, box_b11 = _frame_png_and_box(burned, "1.1")
            self.assertIsNotNone(box_b06)
            self.assertIsNotNone(box_b11)
            burn_rec_p = root / "burn-receipt.json"
            burn_rec_p.write_text(json.dumps({
                "command": cmd_burn,
                "inputs": [{"role": "edited_media", "artifact": clean_art}, {"role": "subtitle", "artifact": sub_art}],
                "outputs": [{"role": "candidate", "artifact": _outlet_art(burned)}],
            }), encoding="utf-8")
            burn_rec_ref = cw.reference(burn_rec_p)

            def _run_check(final_media: Path, final_rec_ref: dict, chain_refs: list, sample_png: Path, sample_box: list[int]):
                frames = [{"time_seconds": 0.6, "frame_ref": cw.reference(sample_png)}]
                observed = {
                    "video_sha256": cw.reference(final_media)["sha256"],
                    "subtitle_glyph_samples": [{"time_seconds": 0.6, "frame_ref": frames[0]["frame_ref"], "glyph_box": sample_box}],
                }
                manifest = {
                    "subtitles": {"pack_ref": pack_ref, "render_file_ref": sub_ref},
                    "render_chain_refs": chain_refs,
                    "render_receipt_ref": final_rec_ref,
                }
                captions.check(manifest, observed, frames)

            _run_check(burned, burn_rec_ref, [], png_b06, box_b06)

            # P1-1: Same receipt emits burned candidate + broken diagnostic video -> selecting diagnostic MUST FAIL!
            good_out = root / "proper-candidate.mkv"
            diag_out = root / "diagnostic-chosen-as-final.mkv"
            cmd_dual = [
                ffmpeg, "-y", "-i", str(clean),
                "-filter_complex",
                f"[0:v]split=3[a][b][c];[a]ass='{esc_sub}'[good];[b]trim=end=1,setpts=PTS-STARTPTS,ass='{esc_sub}'[first];[c]trim=start=1,setpts=PTS-STARTPTS[second];[first][second]concat=n=2:v=1:a=0[bad]",
                "-map", "[good]", "-c:v", "libx264", str(good_out),
                "-map", "[bad]", "-c:v", "libx264", str(diag_out),
            ]
            subprocess.run(cmd_dual, check=True, capture_output=True)
            png_d06, box_d06 = _frame_png_and_box(diag_out, "0.6")
            _, box_d11 = _frame_png_and_box(diag_out, "1.1")
            self.assertIsNotNone(box_d06)
            self.assertIsNone(box_d11)
            dual_rec_p = root / "dual-receipt.json"
            dual_rec_p.write_text(json.dumps({
                "command": cmd_dual,
                "inputs": [{"role": "edited_media", "artifact": clean_art}, {"role": "subtitle", "artifact": sub_art}],
                "outputs": [
                    {"role": "candidate", "artifact": _outlet_art(good_out)},
                    {"role": "diagnostic", "artifact": _outlet_art(diag_out)},
                ],
            }), encoding="utf-8")
            dual_rec_ref = cw.reference(dual_rec_p)
            with self.assertRaisesRegex(ValueError, "final_caption_file_not_bound_to_subtitle_burn_after_edit"):
                _run_check(diag_out, dual_rec_ref, [], png_d06, box_d06)
            # Selecting the genuine burned candidate passes!
            png_g06, box_g06 = _frame_png_and_box(good_out, "0.6")
            _run_check(good_out, dual_rec_ref, [], png_g06, box_g06)

            # P1-2: Subsequent overlay covering subtitle box (y=120..180) MUST FAIL; disjoint top overlay (y=0..60) MUST PASS!
            fg_bad = root / "overlay-bad.txt"
            fg_bad.write_text("color=c=black:s=320x60:r=10:d=2[bar];[0:v][bar]overlay=x=0:y=120:enable='gte(t,0.8)'[v]", encoding="utf-8")
            ov_bad = root / "overlay-bad.mkv"
            cmd_ov_bad = [ffmpeg, "-y", "-i", str(burned), "-filter_complex_script", str(fg_bad), "-map", "[v]", "-c:v", "libx264", str(ov_bad)]
            subprocess.run(cmd_ov_bad, check=True, capture_output=True)
            png_ob06, box_ob06 = _frame_png_and_box(ov_bad, "0.6")
            _, box_ob11 = _frame_png_and_box(ov_bad, "1.1")
            self.assertIsNotNone(box_ob06)
            self.assertIsNone(box_ob11)
            ov_bad_rec_p = root / "ov-bad-receipt.json"
            ov_bad_rec_p.write_text(json.dumps({
                "command": cmd_ov_bad,
                "inputs": [{"role": "candidate", "artifact": _outlet_art(burned)}, {"role": "filter_graph", "artifact": _outlet_art(fg_bad)}],
                "outputs": [{"role": "candidate", "artifact": _outlet_art(ov_bad)}],
            }), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "final_caption_file_not_bound_to_subtitle_burn_after_edit"):
                _run_check(ov_bad, cw.reference(ov_bad_rec_p), [burn_rec_ref], png_ob06, box_ob06)

            fg_ok = root / "overlay-top.txt"
            fg_ok.write_text("color=c=black:s=320x60:r=10:d=2[bar];[0:v][bar]overlay=x=0:y=0:enable='gte(t,0.8)'[v]", encoding="utf-8")
            ov_ok = root / "overlay-top.mkv"
            cmd_ov_ok = [ffmpeg, "-y", "-i", str(burned), "-filter_complex_script", str(fg_ok), "-map", "[v]", "-c:v", "libx264", str(ov_ok)]
            subprocess.run(cmd_ov_ok, check=True, capture_output=True)
            png_oo06, box_oo06 = _frame_png_and_box(ov_ok, "0.6")
            _, box_oo11 = _frame_png_and_box(ov_ok, "1.1")
            self.assertIsNotNone(box_oo06)
            self.assertIsNotNone(box_oo11)
            ov_ok_rec_p = root / "ov-ok-receipt.json"
            ov_ok_rec_p.write_text(json.dumps({
                "command": cmd_ov_ok,
                "inputs": [{"role": "candidate", "artifact": _outlet_art(burned)}, {"role": "filter_graph", "artifact": _outlet_art(fg_ok)}],
                "outputs": [{"role": "candidate", "artifact": _outlet_art(ov_ok)}],
            }), encoding="utf-8")
            # Under the closed-world template contract, unverified post-burn overlay scripts MUST fail closed
            # (only official byte-verified progress_overlay scripts are permitted after caption burn).
            with self.assertRaisesRegex(ValueError, "final_caption_file_not_bound_to_subtitle_burn_after_edit"):
                _run_check(ov_ok, cw.reference(ov_ok_rec_p), [burn_rec_ref], png_oo06, box_oo06)

            # P1-3: Output-side -ss 0.4 after fresh -vf ass=... shifts subtitles off timeline -> MUST FAIL!
            seek_out = root / "output-seek.mkv"
            cmd_seek = [ffmpeg, "-y", "-i", str(clean), "-vf", f"ass='{esc_sub}'", "-ss", "0.4", "-c:v", "libx264", str(seek_out)]
            subprocess.run(cmd_seek, check=True, capture_output=True)
            png_s06, box_s06 = _frame_png_and_box(seek_out, "0.6")
            _, box_s11 = _frame_png_and_box(seek_out, "1.1")
            self.assertIsNotNone(box_s06)
            self.assertIsNone(box_s11)
            self.assertFalse(captions._command_burns_caption_to_mapped_video(cmd_seek, sub))
            seek_rec_p = root / "seek-receipt.json"
            seek_rec_p.write_text(json.dumps({
                "command": cmd_seek,
                "inputs": [{"role": "edited_media", "artifact": clean_art}, {"role": "subtitle", "artifact": sub_art}],
                "outputs": [{"role": "candidate", "artifact": _outlet_art(seek_out)}],
            }), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "final_caption_file_not_bound_to_subtitle_burn_after_edit"):
                _run_check(seek_out, cw.reference(seek_rec_p), [], png_s06, box_s06)

    # ---- 16. Round-12 boundary counterexamples (intermediate-scale drawbox, dynamic/boxless drawtext, target vs desk/layout conflict) ----
    def test_round12_counterexamples(self):
        import shutil
        import subprocess
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            sub = root / "cue.ass"
            sub.write_text(
                "[Script Info]\nScriptType: v4.00+\nPlayResX: 320\nPlayResY: 180\n\n"
                "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
                "Style: Default,Arial,24,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,1,0,2,10,10,10,1\n\n"
                "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
                "Dialogue: 0,0:00:00.00,0:00:01.20,Default,,0,0,0,,TEST\n",
                encoding="utf-8",
            )
            esc_sub = sub.as_posix().replace(":", r"\:")
            ffmpeg = shutil.which("ffmpeg")
            if not ffmpeg:
                return

            clean = root / "clean.mkv"
            subprocess.run([ffmpeg, "-y", "-f", "lavfi", "-i", "color=c=black:s=320x180:r=10:d=1.6",
                            "-c:v", "libx264", str(clean)], check=True, capture_output=True)

            def _frame_png_and_box(media: Path, ss: str) -> tuple[Path, list[int] | None]:
                png = root / f"{media.stem}_at_{ss.replace('.', '_')}.png"
                subprocess.run([ffmpeg, "-y", "-ss", ss, "-i", str(media), "-frames:v", "1", str(png)],
                               check=True, capture_output=True)
                with Image.open(png) as im:
                    bbox = im.convert("L").point(lambda p: 255 if p > 120 else 0).getbbox()
                return png, (list(bbox) if bbox else None)

            def _outlet_art(p: Path) -> dict:
                r = cw.reference(p)
                return {**r, "bytes": p.stat().st_size, "content_kind": "binary", "canonical_sha256": None}

            sub_ref = cw.reference(sub)
            sub_art = _outlet_art(sub)
            clean_art = _outlet_art(clean)
            pack = root / "pack.json"
            pack.write_text(json.dumps({
                "requests": [{"subtitle_cues": [{"start_seconds": 0.0, "end_seconds": 1.2, "text": "TEST"}]}]
            }), encoding="utf-8")
            pack_ref = cw.reference(pack)

            def _run_check(final_media: Path, final_rec_ref: dict, sample_png: Path, sample_box: list[int],
                           *, extra_manifest=None, target_video=None):
                frames = [{"time_seconds": 0.6, "frame_ref": cw.reference(sample_png)}]
                observed = {
                    "video_sha256": cw.reference(final_media)["sha256"],
                    "subtitle_glyph_samples": [{"time_seconds": 0.6, "frame_ref": frames[0]["frame_ref"], "glyph_box": sample_box}],
                }
                manifest = {
                    "subtitles": {"pack_ref": pack_ref, "render_file_ref": sub_ref},
                    "render_chain_refs": [],
                    "render_receipt_ref": final_rec_ref,
                }
                if extra_manifest:
                    manifest.update(extra_manifest)
                captions.check(manifest, observed, frames, target_video=target_video)

            # Clean baseline burn for identity-conflict checks
            plain_out = root / "plain-burn.mkv"
            cmd_plain = [ffmpeg, "-y", "-i", str(clean), "-vf", f"ass='{esc_sub}'", "-c:v", "libx264", str(plain_out)]
            subprocess.run(cmd_plain, check=True, capture_output=True)
            png_pl06, box_pl06 = _frame_png_and_box(plain_out, "0.6")
            self.assertIsNotNone(box_pl06)
            rec_plain = root / "plain-burn-rec.json"
            rec_plain.write_text(json.dumps({
                "command": cmd_plain,
                "inputs": [{"role": "edited_media", "artifact": clean_art}, {"role": "subtitle", "artifact": sub_art}],
                "outputs": [{"role": "candidate", "artifact": _outlet_art(plain_out)}],
            }), encoding="utf-8")
            _run_check(plain_out, cw.reference(rec_plain), png_pl06, box_pl06)

            # P1-1: Post-burn freeform scale / drawbox MUST FAIL under closed-world template contract
            out_scale_ok = root / "scale-only.mkv"
            cmd_scale_ok = [ffmpeg, "-y", "-i", str(clean), "-vf", f"ass='{esc_sub}',scale=640:360,scale=320:180",
                            "-c:v", "libx264", str(out_scale_ok)]
            subprocess.run(cmd_scale_ok, check=True, capture_output=True)
            png_so06, box_so06 = _frame_png_and_box(out_scale_ok, "0.6")
            _, box_so11 = _frame_png_and_box(out_scale_ok, "1.1")
            self.assertIsNotNone(box_so06)
            self.assertIsNotNone(box_so11)
            rec_so = root / "scale-only-rec.json"
            rec_so.write_text(json.dumps({
                "command": cmd_scale_ok,
                "inputs": [{"role": "edited_media", "artifact": clean_art}, {"role": "subtitle", "artifact": sub_art}],
                "outputs": [{"role": "candidate", "artifact": _outlet_art(out_scale_ok)}],
            }), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "final_caption_file_not_bound_to_subtitle_burn_after_edit"):
                _run_check(out_scale_ok, cw.reference(rec_so), png_so06, box_so06)

            out_scale_bad = root / "scale-drawbox-bad.mkv"
            cmd_scale_bad = [
                ffmpeg, "-y", "-i", str(clean),
                "-vf", f"ass='{esc_sub}',scale=640:360,drawbox=x=0:y=240:w=640:h=120:color=black:t=fill:enable='gte(t,0.8)',scale=320:180",
                "-c:v", "libx264", str(out_scale_bad),
            ]
            subprocess.run(cmd_scale_bad, check=True, capture_output=True)
            png_sb06, box_sb06 = _frame_png_and_box(out_scale_bad, "0.6")
            _, box_sb11 = _frame_png_and_box(out_scale_bad, "1.1")
            self.assertIsNotNone(box_sb06)
            self.assertIsNone(box_sb11)
            rec_sb = root / "scale-bad-rec.json"
            rec_sb.write_text(json.dumps({
                "command": cmd_scale_bad,
                "inputs": [{"role": "edited_media", "artifact": clean_art}, {"role": "subtitle", "artifact": sub_art}],
                "outputs": [{"role": "candidate", "artifact": _outlet_art(out_scale_bad)}],
            }), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "final_caption_file_not_bound_to_subtitle_burn_after_edit"):
                _run_check(out_scale_bad, cw.reference(rec_sb), png_sb06, box_sb06)

            # P1-2: Post-burn freeform drawtext (both dynamic and off-canvas) MUST FAIL under closed-world contract
            font = "C\\:/Windows/Fonts/arial.ttf"
            out_dt_bad = root / "drawtext-bad.mkv"
            cmd_dt_bad = [
                ffmpeg, "-y", "-i", str(clean),
                "-vf", f"ass='{esc_sub}',drawtext=fontfile='{font}':text=X:fontsize=80:fontcolor=black:bordercolor=black:borderw=125:box=0:x=125:y='if(gte(t,0.8),120,-400)'",
                "-c:v", "libx264", str(out_dt_bad),
            ]
            subprocess.run(cmd_dt_bad, check=True, capture_output=True)
            png_db06, box_db06 = _frame_png_and_box(out_dt_bad, "0.6")
            _, box_db11 = _frame_png_and_box(out_dt_bad, "1.1")
            self.assertIsNotNone(box_db06)
            self.assertIsNone(box_db11)
            rec_db = root / "drawtext-bad-rec.json"
            rec_db.write_text(json.dumps({
                "command": cmd_dt_bad,
                "inputs": [{"role": "edited_media", "artifact": clean_art}, {"role": "subtitle", "artifact": sub_art}],
                "outputs": [{"role": "candidate", "artifact": _outlet_art(out_dt_bad)}],
            }), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "final_caption_file_not_bound_to_subtitle_burn_after_edit"):
                _run_check(out_dt_bad, cw.reference(rec_db), png_db06, box_db06)

            out_dt_ok = root / "drawtext-offcanvas.mkv"
            cmd_dt_ok = [
                ffmpeg, "-y", "-i", str(clean),
                "-vf", f"ass='{esc_sub}',drawtext=fontfile='{font}':text=X:fontsize=80:fontcolor=black:bordercolor=black:borderw=125:box=0:x=125:y=-400",
                "-c:v", "libx264", str(out_dt_ok),
            ]
            subprocess.run(cmd_dt_ok, check=True, capture_output=True)
            png_do06, box_do06 = _frame_png_and_box(out_dt_ok, "0.6")
            _, box_do11 = _frame_png_and_box(out_dt_ok, "1.1")
            self.assertIsNotNone(box_do06)
            self.assertIsNotNone(box_do11)
            rec_do = root / "drawtext-ok-rec.json"
            rec_do.write_text(json.dumps({
                "command": cmd_dt_ok,
                "inputs": [{"role": "edited_media", "artifact": clean_art}, {"role": "subtitle", "artifact": sub_art}],
                "outputs": [{"role": "candidate", "artifact": _outlet_art(out_dt_ok)}],
            }), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "final_caption_file_not_bound_to_subtitle_burn_after_edit"):
                _run_check(out_dt_ok, cw.reference(rec_do), png_do06, box_do06)

            # P2: Explicit target_video conflicting with manifest['desk_ref'] OR manifest['final_layout_ref'] MUST FAIL!
            conflict_desk = root / "conflict-desk.json"
            conflict_desk.write_text(json.dumps({"items": [{"video": cw.reference(clean)}]}), encoding="utf-8")
            conflict_layout = root / "conflict-layout.json"
            conflict_layout.write_text(json.dumps({"candidate": {"expected_sha256": cw.reference(clean)["sha256"]}}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "final_caption_file_not_bound_to_subtitle_burn_after_edit"):
                _run_check(plain_out, cw.reference(rec_plain), png_pl06, box_pl06,
                           extra_manifest={"desk_ref": cw.reference(conflict_desk)},
                           target_video=cw.reference(plain_out))
            with self.assertRaisesRegex(ValueError, "final_caption_file_not_bound_to_subtitle_burn_after_edit"):
                _run_check(plain_out, cw.reference(rec_plain), png_pl06, box_pl06,
                           extra_manifest={"final_layout_ref": cw.reference(conflict_layout)},
                           target_video=cw.reference(plain_out))

    # ---- 17. Round-13 boundary counterexamples (force_original_aspect_ratio scale, drawtext y_align=baseline, layout candidate.path conflict) ----
    def test_round13_counterexamples(self):
        import shutil
        import subprocess
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            sub = root / "cue.ass"
            sub.write_text(
                "[Script Info]\nScriptType: v4.00+\nPlayResX: 320\nPlayResY: 180\n\n"
                "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
                "Style: Default,Arial,24,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,1,0,2,10,10,10,1\n\n"
                "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
                "Dialogue: 0,0:00:00.00,0:00:01.20,Default,,0,0,0,,TEST\n",
                encoding="utf-8",
            )
            esc_sub = sub.as_posix().replace(":", r"\:")
            ffmpeg = shutil.which("ffmpeg")
            if not ffmpeg:
                return

            clean = root / "clean.mkv"
            subprocess.run([ffmpeg, "-y", "-f", "lavfi", "-i", "color=c=black:s=320x180:r=10:d=1.6",
                            "-c:v", "libx264", str(clean)], check=True, capture_output=True)

            def _frame_png_and_box(media: Path, ss: str) -> tuple[Path, list[int] | None]:
                png = root / f"{media.stem}_at_{ss.replace('.', '_')}.png"
                subprocess.run([ffmpeg, "-y", "-ss", ss, "-i", str(media), "-frames:v", "1", str(png)],
                               check=True, capture_output=True)
                with Image.open(png) as im:
                    bbox = im.convert("L").point(lambda p: 255 if p > 120 else 0).getbbox()
                return png, (list(bbox) if bbox else None)

            def _outlet_art(p: Path) -> dict:
                r = cw.reference(p)
                return {**r, "bytes": p.stat().st_size, "content_kind": "binary", "canonical_sha256": None}

            sub_ref = cw.reference(sub)
            sub_art = _outlet_art(sub)
            clean_art = _outlet_art(clean)
            pack = root / "pack.json"
            pack.write_text(json.dumps({
                "requests": [{"subtitle_cues": [{"start_seconds": 0.0, "end_seconds": 1.2, "text": "TEST"}]}]
            }), encoding="utf-8")
            pack_ref = cw.reference(pack)

            def _run_check(final_media: Path, final_rec_ref: dict, sample_png: Path, sample_box: list[int],
                           *, extra_manifest=None, target_video=None):
                frames = [{"time_seconds": 0.6, "frame_ref": cw.reference(sample_png)}]
                observed = {
                    "video_sha256": cw.reference(final_media)["sha256"],
                    "subtitle_glyph_samples": [{"time_seconds": 0.6, "frame_ref": frames[0]["frame_ref"], "glyph_box": sample_box}],
                }
                manifest = {
                    "subtitles": {"pack_ref": pack_ref, "render_file_ref": sub_ref},
                    "render_chain_refs": [],
                    "render_receipt_ref": final_rec_ref,
                }
                if extra_manifest:
                    manifest.update(extra_manifest)
                captions.check(manifest, observed, frames, target_video=target_video)

            # Clean baseline burn for layout candidate.path conflict checks
            plain_out = root / "plain-burn.mkv"
            cmd_plain = [ffmpeg, "-y", "-i", str(clean), "-vf", f"ass='{esc_sub}'", "-c:v", "libx264", str(plain_out)]
            subprocess.run(cmd_plain, check=True, capture_output=True)
            png_pl06, box_pl06 = _frame_png_and_box(plain_out, "0.6")
            self.assertIsNotNone(box_pl06)
            rec_plain = root / "plain-burn-rec.json"
            rec_plain.write_text(json.dumps({
                "command": cmd_plain,
                "inputs": [{"role": "edited_media", "artifact": clean_art}, {"role": "subtitle", "artifact": sub_art}],
                "outputs": [{"role": "candidate", "artifact": _outlet_art(plain_out)}],
            }), encoding="utf-8")

            # P1-1: Post-burn freeform scale & drawbox MUST FAIL under closed-world template contract
            out_ratio_ok = root / "ratio-control.mkv"
            cmd_ratio_ok = [
                ffmpeg, "-y", "-i", str(clean),
                "-vf", f"ass='{esc_sub}',scale=640:480:force_original_aspect_ratio=decrease,scale=320:180",
                "-c:v", "libx264", str(out_ratio_ok),
            ]
            subprocess.run(cmd_ratio_ok, check=True, capture_output=True)
            png_ro06, box_ro06 = _frame_png_and_box(out_ratio_ok, "0.6")
            _, box_ro11 = _frame_png_and_box(out_ratio_ok, "1.1")
            self.assertIsNotNone(box_ro06)
            self.assertIsNotNone(box_ro11)
            rec_ro = root / "ratio-control-rec.json"
            rec_ro.write_text(json.dumps({
                "command": cmd_ratio_ok,
                "inputs": [{"role": "edited_media", "artifact": clean_art}, {"role": "subtitle", "artifact": sub_art}],
                "outputs": [{"role": "candidate", "artifact": _outlet_art(out_ratio_ok)}],
            }), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "final_caption_file_not_bound_to_subtitle_burn_after_edit"):
                _run_check(out_ratio_ok, cw.reference(rec_ro), png_ro06, box_ro06)

            out_ratio_bad = root / "aspect-ratio-overrides-requested-size.mkv"
            cmd_ratio_bad = [
                ffmpeg, "-y", "-i", str(clean),
                "-vf", (
                    f"ass='{esc_sub}',scale=640:480:force_original_aspect_ratio=decrease,"
                    "drawbox=x=0:y=240:w=640:h=120:color=black:t=fill:enable='gte(t,0.8)',scale=320:180"
                ),
                "-c:v", "libx264", str(out_ratio_bad),
            ]
            subprocess.run(cmd_ratio_bad, check=True, capture_output=True)
            png_rb06, box_rb06 = _frame_png_and_box(out_ratio_bad, "0.6")
            _, box_rb11 = _frame_png_and_box(out_ratio_bad, "1.1")
            self.assertIsNotNone(box_rb06)
            self.assertIsNone(box_rb11)
            rec_rb = root / "aspect-ratio-bad-rec.json"
            rec_rb.write_text(json.dumps({
                "command": cmd_ratio_bad,
                "inputs": [{"role": "edited_media", "artifact": clean_art}, {"role": "subtitle", "artifact": sub_art}],
                "outputs": [{"role": "candidate", "artifact": _outlet_art(out_ratio_bad)}],
            }), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "final_caption_file_not_bound_to_subtitle_burn_after_edit"):
                _run_check(out_ratio_bad, cw.reference(rec_rb), png_rb06, box_rb06)

            # P1-2: Post-burn drawtext (baseline, text, text_align) ALL fail closed under closed-world contract
            font = "C\\:/Windows/Fonts/arial.ttf"
            out_base_bad = root / "text-baseline-overlaps-subtitle.mkv"
            cmd_base_bad = [
                ffmpeg, "-y", "-i", str(clean),
                "-vf", (
                    f"ass='{esc_sub}',drawtext=fontfile='{font}':text=WWWWWW:fontsize=110:"
                    "fontcolor=black:box=1:boxcolor=black:boxborderw=12:x=0:y=224:"
                    "enable='gte(t,0.8)':y_align=baseline"
                ),
                "-c:v", "libx264", str(out_base_bad),
            ]
            subprocess.run(cmd_base_bad, check=True, capture_output=True)
            png_bb06, box_bb06 = _frame_png_and_box(out_base_bad, "0.6")
            _, box_bb11 = _frame_png_and_box(out_base_bad, "1.1")
            self.assertIsNotNone(box_bb06)
            self.assertIsNone(box_bb11)
            rec_bb = root / "text-baseline-bad-rec.json"
            rec_bb.write_text(json.dumps({
                "command": cmd_base_bad,
                "inputs": [{"role": "edited_media", "artifact": clean_art}, {"role": "subtitle", "artifact": sub_art}],
                "outputs": [{"role": "candidate", "artifact": _outlet_art(out_base_bad)}],
            }), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "final_caption_file_not_bound_to_subtitle_burn_after_edit"):
                _run_check(out_base_bad, cw.reference(rec_bb), png_bb06, box_bb06)

            out_top_ok = root / "text-top-anchor-control.mkv"
            cmd_top_ok = [
                ffmpeg, "-y", "-i", str(clean),
                "-vf", (
                    f"ass='{esc_sub}',drawtext=fontfile='{font}':text=WWWWWW:fontsize=110:"
                    "fontcolor=black:box=1:boxcolor=black:boxborderw=12:x=0:y=224:"
                    "enable='gte(t,0.8)':y_align=text"
                ),
                "-c:v", "libx264", str(out_top_ok),
            ]
            subprocess.run(cmd_top_ok, check=True, capture_output=True)
            png_to06, box_to06 = _frame_png_and_box(out_top_ok, "0.6")
            _, box_to11 = _frame_png_and_box(out_top_ok, "1.1")
            self.assertIsNotNone(box_to06)
            self.assertIsNotNone(box_to11)
            rec_to = root / "text-top-ok-rec.json"
            rec_to.write_text(json.dumps({
                "command": cmd_top_ok,
                "inputs": [{"role": "edited_media", "artifact": clean_art}, {"role": "subtitle", "artifact": sub_art}],
                "outputs": [{"role": "candidate", "artifact": _outlet_art(out_top_ok)}],
            }), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "final_caption_file_not_bound_to_subtitle_burn_after_edit"):
                _run_check(out_top_ok, cw.reference(rec_to), png_to06, box_to06)

            # P2: final_layout_ref candidate.path pointing to a byte-identical DIFFERENT file MUST FAIL;
            # aligned candidate.path against clean burn MUST PASS.
            other_same_bytes = root / "layout-points-to-other-file.mkv"
            shutil.copyfile(plain_out, other_same_bytes)
            plain_sha = cw.reference(plain_out)["sha256"]
            aligned_layout = root / "aligned-layout-path.json"
            aligned_layout.write_text(json.dumps({
                "candidate": {"path": plain_out.name, "expected_sha256": plain_sha},
                "elements": [],
            }), encoding="utf-8")
            other_layout = root / "other-path-same-hash.json"
            other_layout.write_text(json.dumps({
                "candidate": {"path": other_same_bytes.name, "expected_sha256": plain_sha},
                "elements": [],
            }), encoding="utf-8")
            _run_check(plain_out, cw.reference(rec_plain), png_pl06, box_pl06,
                       extra_manifest={"final_layout_ref": cw.reference(aligned_layout)},
                       target_video=cw.reference(plain_out))
            with self.assertRaisesRegex(ValueError, "final_caption_file_not_bound_to_subtitle_burn_after_edit"):
                _run_check(plain_out, cw.reference(rec_plain), png_pl06, box_pl06,
                           extra_manifest={"final_layout_ref": cw.reference(other_layout)},
                           target_video=cw.reference(plain_out))

    # ---- 18. Round-14 boundary counterexamples (synonym option precedence, color positional size, wide-glyph drawtext) ----
    def test_round14_counterexamples(self):
        import shutil
        import subprocess
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            sub = root / "cue.ass"
            sub.write_text(
                "[Script Info]\nScriptType: v4.00+\nPlayResX: 320\nPlayResY: 180\n\n"
                "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
                "Style: Default,Arial,24,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,1,0,2,10,10,10,1\n\n"
                "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
                "Dialogue: 0,0:00:00.00,0:00:01.20,Default,,0,0,0,,TEST\n",
                encoding="utf-8",
            )
            esc_sub = sub.as_posix().replace(":", r"\:")
            ffmpeg = shutil.which("ffmpeg")
            if not ffmpeg:
                return

            clean = root / "clean.mkv"
            subprocess.run([ffmpeg, "-y", "-f", "lavfi", "-i", "color=c=black:s=320x180:r=10:d=1.6",
                            "-c:v", "libx264", str(clean)], check=True, capture_output=True)

            def _frame_png_and_box(media: Path, ss: str) -> tuple[Path, list[int] | None]:
                png = root / f"{media.stem}_at_{ss.replace('.', '_')}.png"
                subprocess.run([ffmpeg, "-y", "-ss", ss, "-i", str(media), "-frames:v", "1", str(png)],
                               check=True, capture_output=True)
                with Image.open(png) as im:
                    bbox = im.convert("L").point(lambda p: 255 if p > 120 else 0).getbbox()
                return png, (list(bbox) if bbox else None)

            def _outlet_art(p: Path) -> dict:
                r = cw.reference(p)
                return {**r, "bytes": p.stat().st_size, "content_kind": "binary", "canonical_sha256": None}

            sub_ref = cw.reference(sub)
            sub_art = _outlet_art(sub)
            clean_art = _outlet_art(clean)
            pack = root / "pack.json"
            pack.write_text(json.dumps({
                "requests": [{"subtitle_cues": [{"start_seconds": 0.0, "end_seconds": 1.2, "text": "TEST"}]}]
            }), encoding="utf-8")
            pack_ref = cw.reference(pack)

            def _run_check(final_media: Path, final_rec_ref: dict, sample_png: Path, sample_box: list[int]):
                frames = [{"time_seconds": 0.6, "frame_ref": cw.reference(sample_png)}]
                observed = {
                    "video_sha256": cw.reference(final_media)["sha256"],
                    "subtitle_glyph_samples": [{"time_seconds": 0.6, "frame_ref": frames[0]["frame_ref"], "glyph_box": sample_box}],
                }
                manifest = {
                    "subtitles": {"pack_ref": pack_ref, "render_file_ref": sub_ref},
                    "render_chain_refs": [],
                    "render_receipt_ref": final_rec_ref,
                }
                captions.check(manifest, observed, frames, target_video=cw.reference(final_media))

            def _encode_and_rec(name: str, extra_args: list[str]) -> tuple[Path, dict, Path, list[int] | None, list[int] | None]:
                out = root / f"{name}.mkv"
                cmd = [ffmpeg, "-y", "-i", str(clean), *extra_args, "-c:v", "libx264", str(out)]
                subprocess.run(cmd, check=True, capture_output=True)
                p06, b06 = _frame_png_and_box(out, "0.6")
                _, b11 = _frame_png_and_box(out, "1.1")
                rec_p = root / f"{name}-rec.json"
                rec_p.write_text(json.dumps({
                    "command": cmd,
                    "inputs": [{"role": "edited_media", "artifact": clean_art}, {"role": "subtitle", "artifact": sub_art}],
                    "outputs": [{"role": "candidate", "artifact": _outlet_art(out)}],
                }), encoding="utf-8")
                return out, cw.reference(rec_p), p06, b06, b11

            # P1-1a: scale synonym last-wins (h=480:height=360 -> actual height 360) -> MUST FAIL
            out, rec, p06, b06, b11 = _encode_and_rec(
                "scale-height-alias",
                ["-vf", f"ass='{esc_sub}',scale=w=640:h=480:height=360:reset_sar=1,drawbox=x=0:y=240:w=640:h=120:color=black:t=fill:enable='gte(t,0.8)',scale=320:180"],
            )
            self.assertIsNotNone(b06)
            self.assertIsNone(b11)
            with self.assertRaisesRegex(ValueError, "final_caption_file_not_bound_to_subtitle_burn_after_edit"):
                _run_check(out, rec, p06, b06)

            # P1-1b: drawbox synonym last-wins (w=20:width=320 -> actual width 320) -> MUST FAIL; narrow control MUST PASS
            out, rec, p06, b06, b11 = _encode_and_rec(
                "drawbox-width-alias",
                ["-vf", f"ass='{esc_sub}',drawbox=x=0:y=130:w=20:width=320:h=50:color=black:t=fill:enable='gte(t,0.8)'"],
            )
            self.assertIsNotNone(b06)
            self.assertIsNone(b11)
            with self.assertRaisesRegex(ValueError, "final_caption_file_not_bound_to_subtitle_burn_after_edit"):
                _run_check(out, rec, p06, b06)

            out, rec, p06, b06, b11 = _encode_and_rec(
                "drawbox-narrow-ok",
                ["-vf", f"ass='{esc_sub}',drawbox=x=0:y=130:w=20:h=50:color=black:t=fill:enable='gte(t,0.8)'"],
            )
            self.assertIsNotNone(b06)
            self.assertIsNotNone(b11)
            with self.assertRaisesRegex(ValueError, "final_caption_file_not_bound_to_subtitle_burn_after_edit"):
                _run_check(out, rec, p06, b06)

            # P1-2: Freeform post-burn overlay (positional or named size) MUST FAIL under closed-world template contract
            out, rec, p06, b06, b11 = _encode_and_rec(
                "overlay-pos-size-bad",
                ["-filter_complex", f"[0:v]ass='{esc_sub}'[base];color=black:640x360:r=10:d=2[plate];[base][plate]overlay=x=0:y=-175:enable='gte(t,0.8)'[v]", "-map", "[v]"],
            )
            self.assertIsNotNone(b06)
            self.assertIsNone(b11)
            with self.assertRaisesRegex(ValueError, "final_caption_file_not_bound_to_subtitle_burn_after_edit"):
                _run_check(out, rec, p06, b06)

            out, rec, p06, b06, b11 = _encode_and_rec(
                "overlay-small-ok",
                ["-filter_complex", f"[0:v]ass='{esc_sub}'[base];color=c=black:s=320x240:r=10:d=2[plate];[base][plate]overlay=x=0:y=-175:enable='gte(t,0.8)'[v]", "-map", "[v]"],
            )
            self.assertIsNotNone(b06)
            self.assertIsNotNone(b11)
            with self.assertRaisesRegex(ValueError, "final_caption_file_not_bound_to_subtitle_burn_after_edit"):
                _run_check(out, rec, p06, b06)

            # P1-3: Freeform post-burn drawtext (including wide Unicode glyph U+2E3B) MUST FAIL under closed-world contract
            sys_root = os.environ.get("SystemRoot") or os.environ.get("WINDIR") or ""
            segoe = Path(sys_root) / "Fonts" / "segoeui.ttf" if sys_root else Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
            if segoe.is_file():
                font = segoe.as_posix().replace(":", r"\:")
                out, rec, p06, b06, b11 = _encode_and_rec(
                    "drawtext-wide-glyph-bad",
                    ["-vf", f"ass='{esc_sub}',drawtext=fontfile='{font}':text=\u2e3b:fontsize=400:fontcolor=black:box=1:boxcolor=black:boxborderw=25:y=140:enable='gte(t,0.8)':x=-560"],
                )
                self.assertIsNotNone(b06)
                self.assertIsNone(b11)
                with self.assertRaisesRegex(ValueError, "final_caption_file_not_bound_to_subtitle_burn_after_edit"):
                    _run_check(out, rec, p06, b06)

                out, rec, p06, b06, b11 = _encode_and_rec(
                    "drawtext-wide-glyph-ok",
                    ["-vf", f"ass='{esc_sub}',drawtext=fontfile='{font}':text=\u2e3b:fontsize=400:fontcolor=black:box=1:boxcolor=black:boxborderw=25:y=140:enable='gte(t,0.8)':x=-900"],
                )
                self.assertIsNotNone(b06)
                self.assertIsNotNone(b11)
                with self.assertRaisesRegex(ValueError, "final_caption_file_not_bound_to_subtitle_burn_after_edit"):
                    _run_check(out, rec, p06, b06)

    # ---- 19. Round-15 closed-world template contract (blocks sendcmd/pre-burn setpts/post-burn drawing; accepts pre-burn watermark + top-layer ass + identity passthrough) ----
    def test_round15_closed_template_guards(self):
        import shutil
        import subprocess
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            sub = root / "cue.ass"
            sub.write_text(
                "[Script Info]\nScriptType: v4.00+\nPlayResX: 320\nPlayResY: 180\n\n"
                "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
                "Style: Default,Arial,24,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,1,0,2,10,10,10,1\n\n"
                "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
                "Dialogue: 0,0:00:00.00,0:00:01.20,Default,,0,0,0,,TEST\n",
                encoding="utf-8",
            )
            esc_sub = sub.as_posix().replace(":", r"\:")
            ffmpeg = shutil.which("ffmpeg")
            if not ffmpeg:
                return

            clean = root / "clean.mkv"
            subprocess.run([ffmpeg, "-y", "-f", "lavfi", "-i", "color=c=black:s=320x180:r=10:d=1.6",
                            "-c:v", "libx264", str(clean)], check=True, capture_output=True)

            def _frame_png_and_box(media: Path, ss: str) -> tuple[Path, list[int] | None]:
                png = root / f"{media.stem}_at_{ss.replace('.', '_')}.png"
                subprocess.run([ffmpeg, "-y", "-ss", ss, "-i", str(media), "-frames:v", "1", str(png)],
                               check=True, capture_output=True)
                with Image.open(png) as im:
                    bbox = im.convert("L").point(lambda p: 255 if p > 120 else 0).getbbox()
                return png, (list(bbox) if bbox else None)

            def _outlet_art(p: Path) -> dict:
                r = cw.reference(p)
                return {**r, "bytes": p.stat().st_size, "content_kind": "binary", "canonical_sha256": None}

            sub_ref = cw.reference(sub)
            sub_art = _outlet_art(sub)
            clean_art = _outlet_art(clean)
            pack = root / "pack.json"
            pack.write_text(json.dumps({
                "requests": [{"subtitle_cues": [{"start_seconds": 0.0, "end_seconds": 1.2, "text": "TEST"}]}]
            }), encoding="utf-8")
            pack_ref = cw.reference(pack)

            def _encode_and_check(name: str, vf_args: list[str], expect_pass: bool):
                out = root / f"{name}.mkv"
                cmd = [ffmpeg, "-y", "-i", str(clean), *vf_args, "-c:v", "libx264", str(out)]
                subprocess.run(cmd, check=True, capture_output=True)
                p06, b06 = _frame_png_and_box(out, "0.6")
                self.assertIsNotNone(b06)
                rec_p = root / f"{name}-rec.json"
                rec_p.write_text(json.dumps({
                    "command": cmd,
                    "inputs": [{"role": "edited_media", "artifact": clean_art}, {"role": "subtitle", "artifact": sub_art}],
                    "outputs": [{"role": "candidate", "artifact": _outlet_art(out)}],
                }), encoding="utf-8")
                frames = [{"time_seconds": 0.6, "frame_ref": cw.reference(p06)}]
                observed = {
                    "video_sha256": cw.reference(out)["sha256"],
                    "subtitle_glyph_samples": [{"time_seconds": 0.6, "frame_ref": frames[0]["frame_ref"], "glyph_box": b06}],
                }
                manifest = {
                    "subtitles": {"pack_ref": pack_ref, "render_file_ref": sub_ref},
                    "render_chain_refs": [],
                    "render_receipt_ref": cw.reference(rec_p),
                }
                if expect_pass:
                    captions.check(manifest, observed, frames, target_video=cw.reference(out))
                else:
                    with self.assertRaisesRegex(ValueError, "final_caption_file_not_bound_to_subtitle_burn_after_edit"):
                        captions.check(manifest, observed, frames, target_video=cw.reference(out))

            font = "C\\:/Windows/Fonts/arial.ttf"
            # 1. Pre-burn watermark + top-layer ass + identity passthrough format=yuv420p -> PASS
            _encode_and_check(
                "preburn-watermark-toplayer-ass",
                ["-vf", f"drawtext=fontfile='{font}':text='AI-assisted':x=16:y=24:fontsize=12:fontcolor=white,ass='{esc_sub}',format=yuv420p"],
                expect_pass=True,
            )
            # 2. Runtime sendcmd mutating downstream drawbox -> BLOCKED (even before burn)
            _encode_and_check(
                "sendcmd-drawbox",
                ["-vf", f"sendcmd=c='0.8 drawbox@plate y 130',ass='{esc_sub}',drawbox@plate=x=0:y=-100:w=320:h=60:color=black:t=fill"],
                expect_pass=False,
            )
            # 3. Runtime sendcmd hidden in disconnected nullsink branch of -filter_complex -> BLOCKED
            _encode_and_check(
                "sendcmd-nullsink",
                ["-filter_complex", f"[0:v]ass='{esc_sub}'[v];color=c=black:s=16x16:r=10:d=1,sendcmd=c='0.8 null foo 1',nullsink", "-map", "[v]"],
                expect_pass=False,
            )
            # 4. Pre-burn setpts shifting ASS clock -> BLOCKED
            _encode_and_check(
                "preburn-setpts-shift",
                ["-vf", f"setpts=PTS+0.5/TB,ass='{esc_sub}'"],
                expect_pass=False,
            )


if __name__ == "__main__":
    unittest.main()
