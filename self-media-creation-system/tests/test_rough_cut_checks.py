"""Unit and regression tests for rough cut timeline, coverage and triage checks."""
from __future__ import annotations

import array
import hashlib
import json
import math
import shutil
import sys
import unittest
import uuid
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import rough_cut_checks as rcc


class TestRoughCutChecks(unittest.TestCase):
    def test_timeline_rows_valid(self):
        doc = {
            "segments": [
                {
                    "source_ref": {"path": "raw1.mp4", "sha256": "a" * 64},
                    "source_start": 0.0,
                    "source_end": 5.0,
                    "target_start": 0.0,
                    "target_end": 5.0,
                },
                {
                    "source_ref": {"path": "raw1.mp4", "sha256": "a" * 64},
                    "source_start": 10.0,
                    "source_end": 15.0,
                    "target_start": 5.0,
                    "target_end": 10.0,
                },
            ]
        }
        rows = rcc.timeline_rows(doc)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["target_start"], 0.0)
        self.assertEqual(rows[1]["target_start"], 5.0)

    def test_timeline_rows_gap_rejected(self):
        doc = {
            "segments": [
                {
                    "source_ref": {"path": "raw1.mp4", "sha256": "a" * 64},
                    "source_start": 0.0,
                    "source_end": 5.0,
                    "target_start": 0.0,
                    "target_end": 5.0,
                },
                {
                    "source_ref": {"path": "raw1.mp4", "sha256": "a" * 64},
                    "source_start": 10.0,
                    "source_end": 15.0,
                    "target_start": 6.0,  # discontinuity > 0.002
                    "target_end": 11.0,
                },
            ]
        }
        with self.assertRaises(ValueError):
            rcc.timeline_rows(doc)

    def test_source_coverage_gaps_not_declared(self):
        doc = {
            "segments": [
                {
                    "source_ref": {"path": "raw.mp4", "sha256": "a" * 64},
                    "source_start": 5.0,
                    "source_end": 10.0,
                    "target_start": 0.0,
                    "target_end": 5.0,
                }
            ]
        }
        res = rcc.source_coverage_gaps(doc)
        self.assertFalse(res["checked"])
        self.assertEqual(res["uncovered_gaps"], [])

    def test_source_coverage_gaps_detected(self):
        doc = {
            "source_duration_seconds": 20.0,
            "segments": [
                {
                    "source_ref": {"path": "raw.mp4", "sha256": "a" * 64},
                    "source_start": 5.0,
                    "source_end": 10.0,
                    "target_start": 0.0,
                    "target_end": 5.0,
                }
            ],
        }
        res = rcc.source_coverage_gaps(doc, min_gap_seconds=1.5)
        self.assertTrue(res["checked"])
        # Gap before: 0 to 5 (5.0s > 1.5s), Gap after: 10 to 20 (10.0s > 1.5s)
        self.assertEqual(len(res["uncovered_gaps"]), 2)
        self.assertEqual(res["uncovered_gaps"][0]["source_start"], 0.0)
        self.assertEqual(res["uncovered_gaps"][0]["source_end"], 5.0)
        self.assertEqual(res["uncovered_gaps"][1]["source_start"], 10.0)
        self.assertEqual(res["uncovered_gaps"][1]["source_end"], 20.0)

    def test_source_coverage_gaps_cleared_by_discarded_ranges(self):
        doc = {
            "source_duration_seconds": 20.0,
            "segments": [
                {
                    "source_ref": {"path": "raw.mp4", "sha256": "a" * 64},
                    "source_start": 5.0,
                    "source_end": 10.0,
                    "target_start": 0.0,
                    "target_end": 5.0,
                }
            ],
            "discarded_ranges": [
                {"start": 0.0, "end": 5.0, "reason": "预录口误重录弃用"},
                {"start": 10.0, "end": 20.0, "reason": "废片"},
            ],
        }
        res = rcc.source_coverage_gaps(doc, min_gap_seconds=1.5)
        self.assertTrue(res["checked"])
        self.assertEqual(res["uncovered_gaps"], [])

    def test_discarded_range_missing_reason_rejected(self):
        doc = {
            "source_duration_seconds": 20.0,
            "segments": [
                {
                    "source_ref": {"path": "raw.mp4", "sha256": "a" * 64},
                    "source_start": 0.0,
                    "source_end": 5.0,
                    "target_start": 0.0,
                    "target_end": 5.0,
                }
            ],
            "discarded_ranges": [{"start": 5.0, "end": 20.0, "reason": "  "}],
        }
        with self.assertRaises(ValueError):
            rcc.source_coverage_gaps(doc)

    def test_review_items_includes_coverage_gaps(self):
        audit = {
            "candidate": {"path": "candidate.mp4", "sha256": "c" * 64},
            "technical": {"duration": 10.0, "candidates": []},
            "comparison": {"changes": [], "omitted_phrase_candidates": [], "repetition_candidates": []},
            "source_coverage": {
                "checked": True,
                "uncovered_gaps": [
                    {"source_sha256": "a" * 64, "source_start": 0.0, "source_end": 4.0, "gap_seconds": 4.0}
                ],
            },
        }
        items = rcc.review_items(audit)
        self.assertEqual(len(items), 1)
        self.assertIn("核对未覆盖区间", items[0]["review_question"])
        self.assertIn("aaaaaaaaaaaa", items[0]["review_question"])
        self.assertIn("4.0s", items[0]["reference_text"])


class TestPreReviewAudioAudit(unittest.TestCase):
    def setUp(self) -> None:
        root_runtime = Path(__file__).resolve().parents[1] / ".test-runtime"
        root_runtime.mkdir(exist_ok=True)
        self.tmp = (root_runtime / f"pre-review-audit-{uuid.uuid4().hex}").resolve()
        self.tmp.mkdir()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    @staticmethod
    def _write_tone_wav(path: Path, duration_s: float, active_spans: list[tuple[float, float]]) -> dict[str, str]:
        sr = 16000
        n = int(round(duration_s * sr))
        samples = array.array("h", [0] * n)
        for start_s, end_s in active_spans:
            lo = max(0, int(round(start_s * sr)))
            hi = min(n, int(round(end_s * sr)))
            for i in range(lo, hi):
                samples[i] = int(round(4500.0 * math.sin(2.0 * math.pi * 440.0 * i / sr)))
        if sys.byteorder != "little":
            samples.byteswap()
        with wave.open(str(path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sr)
            wf.writeframes(samples.tobytes())
        return rcc.ref(path)

    @staticmethod
    def _fake_vkp_runner(segments: list[dict]):
        def runner(concat_wav: Path, vkp_dir: Path) -> Path:
            vkp_dir.mkdir(parents=True, exist_ok=True)
            concat_ref = rcc.ref(concat_wav)
            manifest_path = vkp_dir / "chunk-manifest.json"
            manifest_path.write_text(json.dumps({"source": concat_ref}, ensure_ascii=False), encoding="utf-8")
            raw_path = vkp_dir / "sensevoice-raw.json"
            raw_path.write_text(
                json.dumps({"chunk_manifest_path": str(manifest_path), "canonical_complete": True}, ensure_ascii=False),
                encoding="utf-8",
            )
            transcript_path = vkp_dir / "transcript.json"
            transcript_path.write_text(
                json.dumps({"source_path": str(raw_path), "segments": segments}, ensure_ascii=False),
                encoding="utf-8",
            )
            run_path = vkp_dir / "video-knowledge-run.json"
            run_path.write_text(
                json.dumps({
                    "schema": "video_knowledge_local_video_run.v1",
                    "ok": True,
                    "selected_media_path": str(concat_wav),
                    "transcript_path": str(transcript_path),
                    "asr_run": {"execute": True, "provider": "sensevoice", "raw_output_json": str(raw_path)},
                }, ensure_ascii=False),
                encoding="utf-8",
            )
            return run_path
        return runner

    def _build_fixture(self) -> tuple[Path, Path, Path]:
        # Active tone inside speech windows; silence everywhere else gives real -120 dB valleys vs -20 dB edges.
        wav_path = self.tmp / "source.wav"
        src_ref = self._write_tone_wav(wav_path, 34.0, [
            (0.60, 5.90),   # Seg 0: quiet cut 0.50..6.00 (opening macro boundary)
            (7.10, 12.90),  # Seg 1: quiet cut 7.00..13.00 -> verified_keep
            (14.10, 19.90), # Seg 2: cut_in=14.20 is HOT (inside 14.10..19.90 speech); valley at 14.00
            (21.10, 24.40), # Seg 3: short 3.5s cut 21.00..24.50 -> single merged full card on ASR mismatch/bleed
            (26.10, 32.20), # Seg 4: intentional_hot_out at 32.00 + force_review (closing macro boundary)
        ])
        identity_path = self.tmp / "identity.json"
        identity_path.write_text(json.dumps({"topic": "synthetic-topic", "video_id": "vid-01"}), encoding="utf-8")
        script_path = self.tmp / "script.md"
        script_path.write_text("开场你好\n第二句正常\n第三句完整开头\n第四句短保留\n结尾再见\n", encoding="utf-8")
        timeline_path = self.tmp / "timeline.json"
        timeline_path.write_text(json.dumps({
            "source_duration_seconds": 34.0,
            "segments": [
                {
                    "source_ref": src_ref,
                    "source_start": 0.50,
                    "source_end": 6.00,
                    "first_text": "开场你好",
                    "last_text": "第一句结束",
                    "subtitle_cues": [
                        {"start_seconds": 0.60, "end_seconds": 1.80, "text": "开场你好"},
                        {"start_seconds": 5.50, "end_seconds": 5.90, "text": "末尾字幕不应越界"},
                    ],
                },
                {
                    "source_ref": src_ref,
                    "source_start": 7.00,
                    "source_end": 13.00,
                    "first_text": "第二句正常",
                    "last_text": "正常结束",
                },
                {
                    "source_ref": src_ref,
                    "source_end": 20.00,
                    "source_start": 14.20,
                    "first_text": "第三句完整",
                    "last_text": "第三句结束",
                },
                {
                    "source_ref": src_ref,
                    "source_start": 21.00,
                    "source_end": 24.50,
                    "full_text": "第四句短保留",
                    "next_deleted_text": "废话连篇",
                },
                {
                    "source_ref": src_ref,
                    "source_start": 26.00,
                    "source_end": 32.00,
                    "first_text": "第五句开始",
                    "last_text": "结尾再见",
                    "intentional_hot_out": True,
                    "force_review": True,
                    "insert_beep_after_seconds": 0.45,
                },
            ],
            "discarded_ranges": [
                {"start": 0.0, "end": 0.50, "reason": "片头静默"},
                {"start": 6.00, "end": 7.00, "reason": "换气"},
                {"start": 13.00, "end": 14.00, "reason": "废句"},
                {"start": 20.00, "end": 21.00, "reason": "重录"},
                {"start": 24.50, "end": 26.00, "reason": "废话连篇"},
                {"start": 32.00, "end": 34.00, "reason": "结尾后废音"},
            ],
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        return timeline_path, script_path, identity_path

    def test_pre_review_audio_audit_autofixes_filters_verified_keep_and_locks_final_edges(self) -> None:
        timeline_path, script_path, identity_path = self._build_fixture()
        captured_requests = []

        def fake_preparer(req_path: Path, out_dir: Path) -> dict:
            out_dir.mkdir(parents=True, exist_ok=True)
            req = json.loads(req_path.read_text(encoding="utf-8-sig"))
            captured_requests.append(req)
            pack_path = out_dir / "targeted-review-pack.json"
            decisions_path = out_dir / "targeted-review-decisions.json"
            html_path = out_dir / "targeted-review.html"
            pack_path.write_text("{}", encoding="utf-8")
            decisions_path.write_text("{}", encoding="utf-8")
            html_path.write_text("<html></html>", encoding="utf-8")
            return {
                "status": "prepared",
                "media_copies_created": 0,
                "bundle_dir": str(out_dir),
                "review_html": str(html_path),
                "pack_path": str(pack_path),
                "decisions_path": str(decisions_path),
            }

        # Note Seg 2 pulled in ~14.02-14.09 -> +0.18s shift, so Seg 0..4 concat offsets align cleanly:
        vkp_segments = [
            {"start": 0.1, "end": 5.4, "text": "开场你好 第一句结束"},
            {"start": 5.6, "end": 11.4, "text": "第二句正常 正常结束"},
            {"start": 11.6, "end": 17.5, "text": "第三句完整 第三句结束"},
            {"start": 17.6, "end": 20.9, "text": "句短保留废话"},  # missing head "第四" + bleed "废话"
            {"start": 21.1, "end": 27.0, "text": "第五句开始 结尾再见"},
        ]
        out_dir = self.tmp / "audit-out"
        res = rcc.pre_review_audio_audit(
            timeline_path,
            out_dir,
            script_path=script_path,
            identity_path=identity_path,
            auto_fix_edges=True,
            vkp_runner=self._fake_vkp_runner(vkp_segments),
            preparer=fake_preparer,
        )
        self.assertEqual(res["status"], "needs_review")
        self.assertEqual(res["media_copies_created"], 0)
        self.assertFalse(res["media_export_authorized"])
        self.assertEqual(res["segment_count"], 5)
        self.assertEqual(res["verified_keep_count"], 2)
        self.assertEqual(res["auto_fixed_count"], 1)
        self.assertEqual(res["review_card_count"], 3)
        self.assertEqual(list(out_dir.rglob("*.mp4")), [])

        with wave.open(res["concat_audio_wav"], "rb") as wf:
            self.assertEqual((wf.getnchannels(), wf.getsampwidth(), wf.getframerate()), (1, 2, 16000))

        audit = json.loads(Path(res["audit"]).read_text(encoding="utf-8"))
        self.assertEqual(audit["schema"], rcc.PRE_REVIEW_AUDIT_SCHEMA)
        self.assertIsNotNone(audit["script_comparison"])
        self.assertEqual(audit["findings"][1]["disposition"], "verified_keep")
        self.assertEqual(audit["findings"][1]["flags"], [])

        seg2 = audit["findings"][2]
        self.assertLess(seg2["cut_in"], 14.20)
        self.assertLessEqual(seg2["in_edge_rms_db"], -36.0)
        self.assertIsNotNone(seg2["auto_fixed_in"])
        self.assertEqual(seg2["disposition"], "verified_keep")
        self.assertEqual(seg2["flags"], [])

        seg4 = audit["findings"][4]
        self.assertEqual(seg4["cut_out"], 32.00)  # intentional_hot_out respected

        self.assertEqual(len(captured_requests), 1)
        req = captured_requests[0]
        self.assertEqual(req["project_identity"], {"topic": "synthetic-topic", "video_id": "vid-01"})
        by_id = {c["review_id"]: c for c in req["requests"]}
        self.assertEqual(set(by_id), {
            "pre-review-000-in",
            "pre-review-003-full",
            "pre-review-004-out",
        })
        # Rule 2/3/4/5: post-cut boundaries locked to actual cut_in / cut_out; cues clamped inside window
        c0 = by_id["pre-review-000-in"]
        self.assertEqual(c0["review_start_seconds"], 0.50)
        self.assertEqual(c0["review_end_seconds"], 5.00)
        self.assertEqual(len(c0["subtitle_cues"]), 1)

        c3 = by_id["pre-review-003-full"]
        self.assertEqual(c3["review_start_seconds"], 21.00)
        self.assertEqual(c3["review_end_seconds"], 24.50)

        c4 = by_id["pre-review-004-out"]
        self.assertEqual(c4["review_start_seconds"], 28.00)
        self.assertEqual(c4["review_end_seconds"], 32.00)

    def test_pre_review_audio_audit_no_autofix_flags_hot_edge(self) -> None:
        timeline_path, _, _ = self._build_fixture()
        vkp_segments = [
            {"start": 0.1, "end": 5.4, "text": "开场你好 第一句结束"},
            {"start": 5.6, "end": 11.4, "text": "第二句正常 正常结束"},
            {"start": 11.6, "end": 17.3, "text": "第三句完整 第三句结束"},
            {"start": 17.4, "end": 20.8, "text": "第四句短保留"},
            {"start": 21.0, "end": 27.0, "text": "第五句开始 结尾再见"},
        ]

        def noop_preparer(req_path: Path, out_dir: Path) -> dict:
            out_dir.mkdir(parents=True, exist_ok=True)
            return {"status": "prepared", "media_copies_created": 0, "bundle_dir": str(out_dir)}

        out_dir = self.tmp / "audit-no-fix"
        res = rcc.pre_review_audio_audit(
            timeline_path,
            out_dir,
            auto_fix_edges=False,
            vkp_runner=self._fake_vkp_runner(vkp_segments),
            preparer=noop_preparer,
        )
        audit = json.loads(Path(res["audit"]).read_text(encoding="utf-8"))
        self.assertEqual(res["auto_fixed_count"], 0)
        seg2 = audit["findings"][2]
        self.assertEqual(seg2["cut_in"], 14.20)
        self.assertIn("hot_in_edge", seg2["flags"])


if __name__ == "__main__":
    unittest.main()
