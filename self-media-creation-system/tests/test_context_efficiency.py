from __future__ import annotations

import importlib.util
import json
import os
import shutil
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "context_efficiency.py"
SPEC = importlib.util.spec_from_file_location("context_efficiency", SCRIPT)
assert SPEC and SPEC.loader
CTX = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CTX)


@contextmanager
def managed_temp_dir():
    root = Path(os.environ.get("TEST_TMP_ROOT", ROOT / ".test-runtime"))
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"context-efficiency-{uuid.uuid4().hex}"
    path.mkdir()
    try:
        yield path
    finally:
        shutil.rmtree(path)


class ContextEfficiencyTests(unittest.TestCase):
    def test_review_receipt_cannot_substitute_a_copied_media_even_with_same_hash(self):
        with managed_temp_dir() as temp:
            manifest_path, _ = self._video_review_fixture(temp)
            plan_path = temp / "plan.json"
            plan = CTX.build_video_review_plan(manifest_path, plan_path)
            receipt_path, receipt = self._video_review_receipt(temp, plan)
            copied = temp / "unnecessary-review-export.mp4"
            copied.write_bytes((temp / "source.mp4").read_bytes())
            receipt["artifacts"]["source_media"] = {"path": copied.name, "sha256": CTX.sha256_file(copied)}
            receipt.pop("receipt_payload_sha256", None)
            receipt["receipt_payload_sha256"] = CTX.sha256_bytes(CTX.canonical_json_bytes(receipt))
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            with self.assertRaisesRegex(CTX.ContextEfficiencyError, "original_source_not_proxy"):
                CTX.verify_video_review_receipt(plan_path, receipt_path, temp / "verified.json")

    def _video_review_fixture(self, temp: Path, *, limited: bool = False):
        media = temp / "source.mp4"
        media.write_bytes(b"synthetic-video-source")
        decision = temp / "decision.json"
        decision.write_text('{"status":"approved"}', encoding="utf-8")
        rough = temp / "rough.json"
        rough.write_text(
            json.dumps({"schema": CTX.ROUGH_CUT_WORKSPACE_V2, "workspace_sha256": "synthetic"}),
            encoding="utf-8",
        )
        changed = (
            [{"window_id": "window-01", "start_seconds": 10, "end_seconds": 20, "reason": "subtitle repair"}]
            if limited
            else []
        )
        frozen = (
            [{"window_id": "frozen-01", "start_seconds": 0, "end_seconds": 9.5, "reason": "accepted"}]
            if limited
            else []
        )
        manifest = {
            "schema_version": "self-media-video-review-input.v1",
            "task_id": "synthetic-video-review",
            "mode": "limited_rework" if limited else "initial_review",
            "source_media": {"path": media.name, "expected_sha256": CTX.sha256_file(media), "duration_seconds": 30},
            "decision_sheet": {"path": decision.name, "expected_sha256": CTX.sha256_file(decision)},
            "rough_cut_workspace": {"path": rough.name, "expected_sha256": CTX.sha256_file(rough)},
            "changed_windows": changed,
            "frozen_windows": frozen,
            "acceptance_frame_timestamps": [11, 15, 19] if limited else [3, 15, 27],
            "change_kinds": ["subtitle"] if limited else [],
        }
        manifest_path = temp / "video-review-input.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        return manifest_path, manifest

    def _video_review_receipt(
        self,
        temp: Path,
        plan: dict,
        *,
        confirmed: bool = True,
        disposition: str = "performed",
        reusable_evidence_available: bool | None = None,
        full_timeline_scanned: bool | None = None,
    ):
        (temp / "execution.log").write_text("synthetic pass", encoding="utf-8")
        frames = []
        for index, timestamp in enumerate(plan["review_scope"]["acceptance_frame_timestamps"]):
            path = temp / f"frame-{index}.jpg"
            path.write_bytes(f"frame-{timestamp}".encode())
            frames.append({"path": path.name, "sha256": CTX.sha256_file(path), "timestamp_seconds": timestamp})
        media_sha256 = plan["inputs"]["source_media"]["sha256"]
        check_profile_sha256 = CTX.sha256_bytes(
            CTX.canonical_json_bytes({"profile": "synthetic-video-review"})
        )
        cache_key = CTX.sha256_bytes(
            CTX.canonical_json_bytes(
                {
                    "media_sha256": media_sha256,
                    "check_profile_sha256": check_profile_sha256,
                }
            )
        )
        if full_timeline_scanned is None:
            full_timeline_scanned = plan["mode"] == "initial_review"
        scope = {
            "render_scope": plan["review_scope"]["render_scope"],
            "changed_windows": plan["review_scope"]["changed_windows"],
            "full_timeline_scanned": full_timeline_scanned,
            "scanned_duration_seconds": plan["inputs"]["source_media"]["duration_seconds"],
        }
        commands = []
        if plan["mode"] == "limited_rework":
            for row in plan["review_scope"]["changed_windows"]:
                commands.append(
                    {
                        "window_id": row["window_id"],
                        "start_seconds": row["start_seconds"],
                        "end_seconds": row["end_seconds"],
                        "command": ["ffmpeg", "-ss", str(row["start_seconds"]), "-t", str(row["end_seconds"] - row["start_seconds"]), "-i", "source.mp4", "-f", "null", "-"],
                    }
                )
        else:
            commands.append({"window_id": "full-candidate", "start_seconds": 0, "end_seconds": 30, "command": ["ffmpeg", "-i", "source.mp4", "-f", "null", "-"]})
        qa_report = {
            "schema": CTX.MVP_VIDEO_REVIEW_QA_REPORT_SCHEMA,
            "status": "pass",
            "media_sha256": media_sha256,
            "check_profile_sha256": check_profile_sha256,
            "cache_key": cache_key,
            "scope": scope,
            "detectors": {},
            "commands": commands,
            "authority_boundary": {"source_media_modified": False, "automatic_publish": False},
        }
        qa_report["report_sha256"] = CTX.sha256_bytes(CTX.canonical_json_bytes(qa_report))
        qa_path = temp / "mvp-qa-report.json"
        qa_path.write_text(json.dumps(qa_report), encoding="utf-8")
        qa_ref = {"path": qa_path.name, "sha256": CTX.sha256_file(qa_path)}
        cache_path = temp / "mvp-cache-receipt.json"
        cache_path.write_text('{"status":"synthetic"}', encoding="utf-8")
        execution = {
            "schema": CTX.MVP_VIDEO_REVIEW_EXECUTION_RECEIPT_SCHEMA,
            "status": "completed",
            "disposition": disposition,
            "media_sha256": media_sha256,
            "check_profile_sha256": check_profile_sha256,
            "cache_key": cache_key,
            "scope": scope,
            "cache_receipt": {"path": cache_path.name, "sha256": CTX.sha256_file(cache_path)},
            "qa_report": qa_ref,
            "automatic_retry": False,
            "resource_guard": {
                "policy_id": CTX.MVP_VIDEO_REVIEW_POLICY_ID,
                "decision": "cache_reused" if disposition == "reused" else "executed",
            },
            "authority_boundary": {"automatic_publish": False},
        }
        execution["receipt_sha256"] = CTX.sha256_bytes(CTX.canonical_json_bytes(execution))
        execution_path = temp / "mvp-execution-receipt.json"
        execution_path.write_text(json.dumps(execution), encoding="utf-8")
        receipt = {
            "schema_version": "self-media-video-review-execution-receipt.v1",
            "plan_payload_sha256": plan["plan_payload_sha256"],
            "candidate_media_sha256": media_sha256,
            "execution_policy_ref": plan["execution_policy_ref"],
            "executor_tool_id": "mvp-video-pipeline",
            "ffmpeg_outlet": CTX.FFMPEG_OUTLET_ID,
            "status": "pass",
            "rendered_scope": {
                "render_scope": plan["review_scope"]["render_scope"],
                "changed_window_ids": [row["window_id"] for row in plan["review_scope"]["changed_windows"]],
            },
            "proxy_profile": plan["proxy_profile"],
            "mvp_execution_evidence": {
                "status": "completed",
                "disposition": disposition,
                "media_sha256": media_sha256,
                "check_profile_sha256": check_profile_sha256,
                "cache_key": cache_key,
                "reusable_evidence_available": (
                    disposition == "reused"
                    if reusable_evidence_available is None
                    else reusable_evidence_available
                ),
                "execution_receipt": {
                    "path": execution_path.name,
                    "sha256": CTX.sha256_file(execution_path),
                },
                "qa_report": qa_ref,
                "automatic_retry": False,
            },
            "artifacts": {
                "source_media": {"path": "source.mp4", "sha256": CTX.sha256_file(temp / "source.mp4")},
                "acceptance_frames": frames,
                "execution_log": {"path": "execution.log", "sha256": CTX.sha256_file(temp / "execution.log")},
            },
            "checks": {
                "source_full_decode_passed": True,
                "acceptance_frames_reviewed": True,
                "privacy_candidate_reviewed": True,
                "normal_speed_human_reviewed": True,
            },
            "human_review": {
                "confirmed": confirmed,
                "confirmed_by": "synthetic-human-reviewer",
                "reviewed_at": "2026-08-22T00:00:00Z",
                "request_results": [
                    {"review_id": row["review_id"], "decision": "pass"}
                    for row in plan["human_review_requests"]
                ],
            },
            "authority_boundary": {
                "final_candidate_rendered": False,
                "automatic_publish": False,
                "full_log_inlined": False,
            },
        }
        receipt["receipt_payload_sha256"] = CTX.sha256_bytes(CTX.canonical_json_bytes(receipt))
        path = temp / "execution-receipt.json"
        path.write_text(json.dumps(receipt), encoding="utf-8")
        return path, receipt

    def _video_review_blocked_receipt(self, temp: Path, plan: dict):
        media_sha256 = plan["inputs"]["source_media"]["sha256"]
        check_profile_sha256 = CTX.sha256_bytes(b"synthetic-check-profile")
        cache_key = CTX.sha256_bytes(
            CTX.canonical_json_bytes(
                {
                    "media_sha256": media_sha256,
                    "check_profile_sha256": check_profile_sha256,
                }
            )
        )
        execution = {
            "schema": CTX.MVP_VIDEO_REVIEW_EXECUTION_RECEIPT_SCHEMA,
            "status": "blocked",
            "disposition": "not_run",
            "media_sha256": media_sha256,
            "check_profile_sha256": check_profile_sha256,
            "cache_key": cache_key,
            "scope": {
                "render_scope": plan["review_scope"]["render_scope"],
                "changed_windows": plan["review_scope"]["changed_windows"],
                "full_timeline_scanned": False,
                "scanned_duration_seconds": 0,
            },
            "cache_receipt": None,
            "qa_report": None,
            "automatic_retry": False,
            "reason": "resource_pressure_pause_required",
            "resource_guard": {"policy_id": CTX.MVP_VIDEO_REVIEW_POLICY_ID},
            "authority_boundary": {"automatic_publish": False},
        }
        execution["receipt_sha256"] = CTX.sha256_bytes(CTX.canonical_json_bytes(execution))
        execution_path = temp / "mvp-blocked-receipt.json"
        execution_path.write_text(json.dumps(execution), encoding="utf-8")
        receipt = {
            "schema_version": "self-media-video-review-execution-receipt.v1",
            "plan_payload_sha256": plan["plan_payload_sha256"],
            "candidate_media_sha256": media_sha256,
            "execution_policy_ref": plan["execution_policy_ref"],
            "executor_tool_id": "mvp-video-pipeline",
            "ffmpeg_outlet": CTX.FFMPEG_OUTLET_ID,
            "status": "blocked",
            "rendered_scope": {
                "render_scope": plan["review_scope"]["render_scope"],
                "changed_window_ids": [row["window_id"] for row in plan["review_scope"]["changed_windows"]],
            },
            "proxy_profile": plan["proxy_profile"],
            "mvp_execution_evidence": {
                "status": "blocked",
                "disposition": "not_run",
                "media_sha256": media_sha256,
                "check_profile_sha256": check_profile_sha256,
                "cache_key": cache_key,
                "reusable_evidence_available": False,
                "execution_receipt": {"path": execution_path.name, "sha256": CTX.sha256_file(execution_path)},
                "reason": "resource_pressure_pause_required",
                "automatic_retry": False,
            },
            "authority_boundary": {
                "final_candidate_rendered": False,
                "automatic_publish": False,
                "full_log_inlined": False,
            },
        }
        receipt["receipt_payload_sha256"] = CTX.sha256_bytes(CTX.canonical_json_bytes(receipt))
        path = temp / "blocked-execution-receipt.json"
        path.write_text(json.dumps(receipt), encoding="utf-8")
        return path, receipt

    def test_bounded_search_excludes_dependencies_and_returns_summary_only(self) -> None:
        with managed_temp_dir() as temp:
            (temp / "src").mkdir()
            (temp / "src" / "main.py").write_text("needle here\n", encoding="utf-8")
            (temp / "node_modules").mkdir()
            (temp / "node_modules" / "huge.js").write_text("needle\n" * 1000, encoding="utf-8")
            output = temp / "search.json"
            summary = CTX.bounded_search(temp, "needle", output)
            artifact = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(summary["hit_count"], 1)
            self.assertEqual(len(summary["preview_hits"]), 1)
            self.assertEqual(artifact["hits"][0]["path"], "src/main.py")

    def test_search_marks_limit_instead_of_dumping_unbounded_hits(self) -> None:
        with managed_temp_dir() as temp:
            (temp / "many.md").write_text("hit\n" * 50, encoding="utf-8")
            summary = CTX.bounded_search(temp, "hit", temp / "search.json", max_hits=7)
            self.assertTrue(summary["truncated"])
            self.assertEqual(summary["status"], "refine_query_required")
            self.assertEqual(summary["hit_count"], 7)

    def test_context_pack_preserves_locked_hashes_and_deduplicates(self) -> None:
        with managed_temp_dir() as temp:
            content = "confirmed fact\n"
            (temp / "fact.md").write_text(content, encoding="utf-8")
            (temp / "copy.md").write_text(content, encoding="utf-8")
            digest = CTX.sha256_file(temp / "fact.md")
            manifest = {
                "schema_version": "self-media-context-input.v1",
                "task_id": "synthetic-context-test",
                "stage": "research",
                "budget": {"max_inline_bytes": 1000},
                "artifacts": [
                    {"artifact_id": "fact", "role": "fact_baseline", "path": "fact.md", "load_mode": "inline", "expected_sha256": digest},
                    {"artifact_id": "copy", "role": "working_draft", "path": "copy.md", "load_mode": "inline"},
                ],
            }
            manifest_path = temp / "manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            receipt = CTX.build_context_pack(manifest_path, temp / "receipt.json")
            stored_bytes = (temp / "fact.md").stat().st_size
            self.assertEqual(receipt["budget"]["inline_bytes"], stored_bytes)
            self.assertEqual(receipt["budget"]["duplicate_bytes_avoided"], stored_bytes)

    def test_locked_role_cannot_be_hidden_until_failure(self) -> None:
        with managed_temp_dir() as temp:
            (temp / "fact.md").write_text("fact", encoding="utf-8")
            digest = CTX.sha256_file(temp / "fact.md")
            manifest = {
                "schema_version": "self-media-context-input.v1",
                "task_id": "synthetic-context-test",
                "stage": "research",
                "budget": {"max_inline_bytes": 1000},
                "artifacts": [{"artifact_id": "fact", "role": "fact_baseline", "path": "fact.md", "load_mode": "on_failure", "expected_sha256": digest}],
            }
            path = temp / "manifest.json"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(CTX.ContextEfficiencyError, "locked_role_cannot_be_on_failure"):
                CTX.build_context_pack(path, temp / "receipt.json")

    def test_manifest_schema_rejects_absolute_and_parent_paths(self) -> None:
        schema = json.loads((ROOT / "schemas" / "context-input-manifest.v1.schema.json").read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema)
        base = {
            "schema_version": "self-media-context-input.v1",
            "task_id": "synthetic-context-test",
            "stage": "video",
            "budget": {"max_inline_bytes": 1000},
            "artifacts": [{"artifact_id": "log", "role": "full_log", "path": "log.txt", "load_mode": "on_failure"}],
        }
        self.assertFalse(list(validator.iter_errors(base)))
        for bad_path in ["D:/private.txt", "../private.txt", "/private.txt"]:
            candidate = json.loads(json.dumps(base))
            candidate["artifacts"][0]["path"] = bad_path
            self.assertTrue(list(validator.iter_errors(candidate)), bad_path)

    def test_log_summary_keeps_full_log_out_of_receipt(self) -> None:
        with managed_temp_dir() as temp:
            log = temp / "render.log"
            log.write_text("ok\n" * 100 + "ERROR render failed\n" + "detail\n" * 100, encoding="utf-8")
            summary = CTX.summarize_log(log, temp / "summary.json", tail_lines=3)
            self.assertFalse(summary["full_log_inlined"])
            self.assertLess(len(summary["excerpt"]), 10)
            self.assertEqual(summary["status"], "error_detected")

    def test_asr_is_reused_only_for_identical_audio_hash(self) -> None:
        with managed_temp_dir() as temp:
            audio = temp / "audio.wav"
            audio.write_bytes(b"synthetic-audio")
            first = CTX.decide_asr(audio, None, temp / "first.json", [])
            reused = CTX.decide_asr(audio, temp / "first.json", temp / "second.json", [])
            self.assertEqual(first["decision"], "rerun_full_asr")
            self.assertEqual(reused["decision"], "reuse_existing_asr")
            audio.write_bytes(b"synthetic-audio-changed")
            changed = CTX.decide_asr(audio, temp / "second.json", temp / "third.json", ["12.0-18.0"])
            self.assertEqual(changed["decision"], "rerun_changed_windows_with_context")
            self.assertEqual(changed["context_padding_seconds"], 2)

    def test_video_review_schemas_are_valid(self) -> None:
        for name in (
            "video-review-input.v1.schema.json",
            "video-review-plan.v1.schema.json",
            "video-review-execution-receipt.v1.schema.json",
        ):
            schema = json.loads((ROOT / "schemas" / name).read_text(encoding="utf-8"))
            Draft202012Validator.check_schema(schema)

    def test_initial_video_review_uses_original_and_existing_video_owner(self) -> None:
        with managed_temp_dir() as temp:
            manifest_path, manifest = self._video_review_fixture(temp)
            schema = json.loads((ROOT / "schemas" / "video-review-input.v1.schema.json").read_text(encoding="utf-8"))
            self.assertFalse(list(Draft202012Validator(schema).iter_errors(manifest)))
            plan = CTX.build_video_review_plan(manifest_path, temp / "plan.json")
            self.assertEqual(plan["review_scope"]["render_scope"], "full_timeline_source")
            self.assertEqual(
                plan["loading_strategy"]["full_resolution_load_condition"],
                "source_time_range_review",
            )
            self.assertTrue(plan["loading_strategy"]["full_resolution_inline"])
            self.assertFalse(plan["loading_strategy"]["proxy_first"])
            self.assertEqual(plan["proxy_profile"], {"enabled": False, "reason": "source_time_range_review"})
            self.assertEqual(plan["owner_binding"]["ffmpeg_outlet"], CTX.FFMPEG_OUTLET_ID)
            self.assertEqual(plan["execution_policy_ref"], CTX.EXECUTION_POLICY_REF)
            self.assertEqual(plan["execution_policy_ref"]["heavy_media_concurrency"], 1)
            self.assertEqual(
                plan["execution_policy_ref"]["full_decode_once_per"],
                "exact_media_sha256_and_check_profile_sha256",
            )
            self.assertTrue(plan["authority_boundary"]["plan_only"])
            self.assertFalse(plan["authority_boundary"]["media_rendered"])
            request = plan["human_review_requests"][0]
            self.assertEqual(request["timecode_start"], "00:00.000")
            self.assertEqual(request["timecode_end"], "00:30.000")
            self.assertEqual(request["artifact_sha256"], plan["inputs"]["source_media"]["sha256"])
            self.assertEqual(request["review_access_mode"], "source_time_range")
            self.assertEqual(plan["review_interface"]["surface"], "targeted-review")
            self.assertEqual(request["workflow_stage"], "final_publication_review")
            self.assertTrue(request["review_question"])

    def test_limited_rework_only_invalidates_downstream_changed_scope(self) -> None:
        with managed_temp_dir() as temp:
            manifest_path, _ = self._video_review_fixture(temp, limited=True)
            plan = CTX.build_video_review_plan(manifest_path, temp / "plan.json")
            self.assertEqual(plan["review_scope"]["render_scope"], "changed_windows_only")
            self.assertEqual([row["window_id"] for row in plan["review_scope"]["changed_windows"]], ["window-01"])
            self.assertIn("subtitle_timing", plan["downstream_invalidations"])
            self.assertNotIn("asr", plan["downstream_invalidations"])
            request = plan["human_review_requests"][0]
            self.assertEqual(request["review_start_seconds"], 8.0)
            self.assertEqual(request["review_end_seconds"], 23.0)
            self.assertEqual(request["timecode_start"], "00:08.000")
            self.assertEqual(request["timecode_end"], "00:23.000")
            self.assertEqual(request["review_lane"], "subtitle")
            self.assertEqual(request["playback_mode"], "normal")

    def test_video_review_rejects_overlap_and_off_window_frames(self) -> None:
        with managed_temp_dir() as temp:
            manifest_path, manifest = self._video_review_fixture(temp, limited=True)
            manifest["frozen_windows"][0]["end_seconds"] = 12
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(CTX.ContextEfficiencyError, "changed_and_frozen_windows_overlap"):
                CTX.build_video_review_plan(manifest_path, temp / "plan.json")
            manifest["frozen_windows"][0]["end_seconds"] = 9.5
            manifest["acceptance_frame_timestamps"] = [2, 15, 19]
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(CTX.ContextEfficiencyError, "acceptance_frames_must_target_changed_windows"):
                CTX.build_video_review_plan(manifest_path, temp / "plan.json")

    def test_long_human_review_window_is_split_into_bounded_exact_ranges(self) -> None:
        with managed_temp_dir() as temp:
            manifest_path, manifest = self._video_review_fixture(temp, limited=True)
            manifest["changed_windows"] = [
                {"window_id": "window-01", "start_seconds": 10, "end_seconds": 28, "reason": "long repair"}
            ]
            manifest["acceptance_frame_timestamps"] = [11, 20, 27]
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            plan = CTX.build_video_review_plan(manifest_path, temp / "plan.json")
            requests = plan["human_review_requests"]
            self.assertEqual(len(requests), 2)
            self.assertTrue(
                all(row["review_end_seconds"] - row["review_start_seconds"] <= 15 for row in requests)
            )
            self.assertEqual(requests[0]["review_start_seconds"], 8.0)
            self.assertEqual(requests[-1]["review_end_seconds"], 30.0)

    def test_video_review_rejects_input_hash_drift(self) -> None:
        with managed_temp_dir() as temp:
            manifest_path, _ = self._video_review_fixture(temp)
            (temp / "decision.json").write_text("changed", encoding="utf-8")
            with self.assertRaisesRegex(CTX.ContextEfficiencyError, "decision_sheet_artifact_hash_drift"):
                CTX.build_video_review_plan(manifest_path, temp / "plan.json")

    def test_video_review_pass_requires_human_checks_and_keeps_final_qa(self) -> None:
        with managed_temp_dir() as temp:
            manifest_path, _ = self._video_review_fixture(temp, limited=True)
            plan_path = temp / "plan.json"
            plan = CTX.build_video_review_plan(manifest_path, plan_path)
            receipt_path, _ = self._video_review_receipt(temp, plan)
            result = CTX.verify_video_review_receipt(plan_path, receipt_path, temp / "verified.json")
            self.assertTrue(result["final_candidate_render_allowed"])
            self.assertTrue(result["full_final_qa_required"])
            self.assertEqual(result["publication_boundary"], "manual_only")

    def test_video_review_reuses_exact_qa_evidence_and_blocks_resource_retry(self) -> None:
        with managed_temp_dir() as temp:
            manifest_path, _ = self._video_review_fixture(temp)
            plan_path = temp / "plan.json"
            plan = CTX.build_video_review_plan(manifest_path, plan_path)
            receipt_path, _ = self._video_review_receipt(temp, plan, disposition="reused")
            result = CTX.verify_video_review_receipt(plan_path, receipt_path, temp / "verified.json")
            self.assertTrue(result["final_candidate_render_allowed"])

        with managed_temp_dir() as temp:
            manifest_path, _ = self._video_review_fixture(temp)
            plan_path = temp / "plan.json"
            plan = CTX.build_video_review_plan(manifest_path, plan_path)
            receipt_path, receipt = self._video_review_blocked_receipt(temp, plan)
            self.assertFalse(receipt["mvp_execution_evidence"]["automatic_retry"])
            result = CTX.verify_video_review_receipt(plan_path, receipt_path, temp / "verified.json")
            self.assertEqual(result["status"], "verified_blocked")
            self.assertFalse(result["automatic_retry"])

    def test_video_review_rejects_redundant_decode_and_limited_full_scan(self) -> None:
        with managed_temp_dir() as temp:
            manifest_path, _ = self._video_review_fixture(temp)
            plan_path = temp / "plan.json"
            plan = CTX.build_video_review_plan(manifest_path, plan_path)
            receipt_path, _ = self._video_review_receipt(
                temp,
                plan,
                disposition="performed",
                reusable_evidence_available=True,
            )
            with self.assertRaisesRegex(CTX.ContextEfficiencyError, "reusable_full_decode_repeated"):
                CTX.verify_video_review_receipt(plan_path, receipt_path, temp / "verified.json")

        with managed_temp_dir() as temp:
            manifest_path, _ = self._video_review_fixture(temp, limited=True)
            plan_path = temp / "plan.json"
            plan = CTX.build_video_review_plan(manifest_path, plan_path)
            receipt_path, _ = self._video_review_receipt(
                temp, plan, full_timeline_scanned=True
            )
            with self.assertRaisesRegex(CTX.ContextEfficiencyError, "limited_rework_full_scan_prohibited"):
                CTX.verify_video_review_receipt(plan_path, receipt_path, temp / "verified.json")

    def test_video_review_rejects_missing_candidate_policy_or_mvp_receipt(self) -> None:
        with managed_temp_dir() as temp:
            manifest_path, _ = self._video_review_fixture(temp)
            plan_path = temp / "plan.json"
            plan = CTX.build_video_review_plan(manifest_path, plan_path)
            receipt_path, receipt = self._video_review_receipt(temp, plan)
            for field, error in (
                ("candidate_media_sha256", "candidate_hash_required"),
                ("execution_policy_ref", "execution_policy_required"),
                ("mvp_execution_evidence", "mvp_execution_receipt_required"),
            ):
                candidate = json.loads(json.dumps(receipt))
                candidate.pop(field)
                receipt_path.write_text(json.dumps(candidate), encoding="utf-8")
                with self.assertRaisesRegex(CTX.ContextEfficiencyError, error):
                    CTX.verify_video_review_receipt(plan_path, receipt_path, temp / "verified.json")

    def test_video_review_rejects_unconfirmed_pass_wrong_outlet_and_artifact_drift(self) -> None:
        with managed_temp_dir() as temp:
            manifest_path, _ = self._video_review_fixture(temp)
            plan_path = temp / "plan.json"
            plan = CTX.build_video_review_plan(manifest_path, plan_path)
            receipt_path, receipt = self._video_review_receipt(temp, plan, confirmed=False)
            with self.assertRaisesRegex(CTX.ContextEfficiencyError, "pass_requires_human_confirmation"):
                CTX.verify_video_review_receipt(plan_path, receipt_path, temp / "verified.json")
            receipt["human_review"]["confirmed"] = True
            receipt["ffmpeg_outlet"] = "second_outlet"
            receipt["receipt_payload_sha256"] = CTX.sha256_bytes(
                CTX.canonical_json_bytes({key: value for key, value in receipt.items() if key != "receipt_payload_sha256"})
            )
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            with self.assertRaisesRegex(CTX.ContextEfficiencyError, "schema_validation_failed"):
                CTX.verify_video_review_receipt(plan_path, receipt_path, temp / "verified.json")
            receipt["ffmpeg_outlet"] = CTX.FFMPEG_OUTLET_ID
            receipt["receipt_payload_sha256"] = CTX.sha256_bytes(
                CTX.canonical_json_bytes({key: value for key, value in receipt.items() if key != "receipt_payload_sha256"})
            )
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            (temp / "source.mp4").write_bytes(b"tampered")
            with self.assertRaisesRegex(CTX.ContextEfficiencyError, "source_media_receipt_artifact_drift"):
                CTX.verify_video_review_receipt(plan_path, receipt_path, temp / "verified.json")

    def test_video_review_rejects_missing_or_failed_exact_human_review_request(self) -> None:
        with managed_temp_dir() as temp:
            manifest_path, _ = self._video_review_fixture(temp, limited=True)
            plan_path = temp / "plan.json"
            plan = CTX.build_video_review_plan(manifest_path, plan_path)
            receipt_path, receipt = self._video_review_receipt(temp, plan)
            receipt["human_review"]["request_results"][0]["decision"] = "needs_rework"
            receipt["receipt_payload_sha256"] = CTX.sha256_bytes(
                CTX.canonical_json_bytes({key: value for key, value in receipt.items() if key != "receipt_payload_sha256"})
            )
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            with self.assertRaisesRegex(CTX.ContextEfficiencyError, "all_requests_passed"):
                CTX.verify_video_review_receipt(plan_path, receipt_path, temp / "verified.json")

            receipt["human_review"]["request_results"][0]["decision"] = "pass"
            receipt["human_review"]["request_results"][0]["review_id"] = "wrong-review-id"
            receipt["receipt_payload_sha256"] = CTX.sha256_bytes(
                CTX.canonical_json_bytes({key: value for key, value in receipt.items() if key != "receipt_payload_sha256"})
            )
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            with self.assertRaisesRegex(CTX.ContextEfficiencyError, "human_review_result_binding_drift"):
                CTX.verify_video_review_receipt(plan_path, receipt_path, temp / "verified.json")


if __name__ == "__main__":
    unittest.main()
