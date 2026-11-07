from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "artifact_lifecycle.py"
SPEC = importlib.util.spec_from_file_location("artifact_lifecycle", SCRIPT)
assert SPEC and SPEC.loader
LIFECYCLE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LIFECYCLE)


class ArtifactLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = ROOT / ".test-runtime-artifact-lifecycle" / self._testMethodName
        if self.root.exists():
            shutil.rmtree(self.root)
        self.root.mkdir(parents=True)
        self.manifest = self.root / "artifact-lifecycle.json"
        LIFECYCLE.init_manifest(
            argparse.Namespace(
                manifest=str(self.manifest),
                workspace_root=str(self.root),
                manifest_id="lifecycle-test-001",
                workspace_ref="synthetic-test",
                quarantine_dir=".artifact-quarantine",
                authorize_automatic_purge=True,
                now="2026-08-28T00:00:00Z",
            )
        )

    def tearDown(self) -> None:
        if self.root.exists():
            shutil.rmtree(self.root)

    def write_file(self, name: str, value: bytes = b"synthetic-video") -> None:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value)

    def manifest_value(self) -> dict:
        return json.loads(self.manifest.read_text(encoding="utf-8"))

    def write_manifest(self, value: dict) -> None:
        LIFECYCLE._write_json_atomic(self.manifest, value, LIFECYCLE.MANIFEST_SCHEMA)

    def register(
        self,
        artifact_id: str,
        path: str,
        *,
        kind: str = "candidate",
        status: str = "candidate",
        depends_on: list[str] | None = None,
        referenced_by: list[str] | None = None,
        retain_reason: str | None = "synthetic test artifact",
        failure_reason: str | None = None,
        user_rejected: bool = False,
        approve_purge: bool = False,
        now: str = "2026-08-28T00:00:00Z",
    ) -> dict:
        return LIFECYCLE.register_artifact(
            argparse.Namespace(
                manifest=str(self.manifest),
                workspace_root=str(self.root),
                artifact_id=artifact_id,
                video_id="video-001",
                path=path,
                kind=kind,
                status=status,
                source_sha256=None,
                depends_on=depends_on,
                referenced_by=referenced_by,
                retain_reason=retain_reason,
                failure_reason=failure_reason,
                user_rejected=user_rejected,
                approve_purge=approve_purge,
                now=now,
            )
        )

    def plan(
        self,
        *,
        phase: str = "quarantine",
        task_close: bool = False,
        now: str = "2026-09-02T00:00:00Z",
    ) -> dict:
        return LIFECYCLE.build_gc_plan(
            argparse.Namespace(
                manifest=str(self.manifest),
                workspace_root=str(self.root),
                phase=phase,
                task_close=task_close,
                now=now,
            )
        )

    def apply(self, plan: dict, *, phase: str, now: str = "2026-09-02T00:00:00Z") -> dict:
        plan_path = self.root / f"plan-{phase}.json"
        LIFECYCLE._write_json_atomic(plan_path, plan, LIFECYCLE.RECEIPT_SCHEMA)
        return LIFECYCLE.apply_gc(
            argparse.Namespace(
                manifest=str(self.manifest),
                workspace_root=str(self.root),
                plan=str(plan_path),
                phase=phase,
                now=now,
            )
        )

    def test_large_file_requires_retain_reason(self) -> None:
        self.write_file("large.mp4", b"0123456789")
        value = self.manifest_value()
        value["policy"]["large_file_threshold_bytes"] = 5
        self.write_manifest(value)
        with self.assertRaises(LIFECYCLE.LifecycleError) as error:
            self.register("large-001", "large.mp4", retain_reason=None)
        self.assertEqual(error.exception.code, "large_artifact_reason_required")

    def test_register_computes_source_hash_when_not_supplied(self) -> None:
        self.write_file("candidate.mp4", b"candidate-bytes")
        receipt = self.register("candidate-001", "candidate.mp4")
        artifact = self.manifest_value()["artifacts"][0]
        self.assertEqual(
            artifact["source_sha256"],
            LIFECYCLE._sha256(self.root / "candidate.mp4"),
        )
        self.assertEqual(receipt["status"], "passed")

    def test_unknown_dependency_fails_closed(self) -> None:
        self.write_file("candidate.mp4")
        with self.assertRaises(LIFECYCLE.LifecycleError) as error:
            self.register("candidate-001", "candidate.mp4", depends_on=["missing-001"])
        self.assertEqual(error.exception.code, "unknown_dependency")

    def test_protected_source_cannot_be_failed_or_quarantined(self) -> None:
        self.write_file("raw.mp4")
        self.register("raw-001", "raw.mp4", kind="raw_source", status="created")
        with self.assertRaises(LIFECYCLE.LifecycleError) as error:
            LIFECYCLE.transition_artifact(
                argparse.Namespace(
                    manifest=str(self.manifest),
                    workspace_root=str(self.root),
                    artifact_id="raw-001",
                    status="qa_fail",
                    reason="must remain protected",
                    superseded_by=None,
                    user_rejected=False,
                    approve_purge=False,
                    now="2026-08-28T01:00:00Z",
                )
            )
        self.assertEqual(error.exception.code, "protected_artifact_transition")

    def test_lock_supersedes_old_candidates_but_keeps_latest_review_version(self) -> None:
        for number in range(1, 4):
            self.write_file(f"candidate-{number}.mp4", f"candidate-{number}".encode())
            self.register(
                f"candidate-00{number}",
                f"candidate-{number}.mp4",
                now=f"2026-08-28T0{number}:00:00Z",
            )
        receipt = LIFECYCLE.lock_artifact(
            argparse.Namespace(
                manifest=str(self.manifest),
                workspace_root=str(self.root),
                artifact_id="candidate-003",
                reason="user locked this candidate",
                now="2026-08-28T04:00:00Z",
            )
        )
        self.assertEqual(receipt["items"][0]["superseded"], ["candidate-001"])
        states = {item["artifact_id"]: item["status"] for item in self.manifest_value()["artifacts"]}
        self.assertEqual(states["candidate-001"], "superseded")
        self.assertEqual(states["candidate-002"], "candidate")
        self.assertEqual(states["candidate-003"], "locked")

    def test_reference_protection_blocks_quarantine(self) -> None:
        self.write_file("failed.mp4")
        self.register(
            "failed-001", "failed.mp4", status="qa_fail",
            failure_reason="render failed", referenced_by=["recipe.json"]
        )
        plan = self.plan()
        self.assertEqual(plan["items"], [])
        self.assertEqual(plan["blocked"][0]["reason"], "still_referenced")

    def test_two_phase_quarantine_then_purge(self) -> None:
        self.write_file("failed.mp4")
        self.register(
            "failed-001",
            "failed.mp4",
            status="qa_fail",
            failure_reason="user rejected visible defect",
            user_rejected=True,
            approve_purge=True,
        )
        quarantine_plan = self.plan(now="2026-09-02T00:00:00Z")
        self.assertEqual([item["artifact_id"] for item in quarantine_plan["items"]], ["failed-001"])
        receipt = self.apply(quarantine_plan, phase="quarantine")
        self.assertEqual(receipt["status"], "passed")
        self.assertFalse((self.root / "failed.mp4").exists())
        quarantined = self.manifest_value()["artifacts"][0]
        self.assertTrue((self.root / quarantined["path"]).exists())
        purge_plan = self.plan(phase="purge", now="2026-09-03T00:00:00Z")
        purge_receipt = self.apply(purge_plan, phase="purge", now="2026-09-03T00:00:00Z")
        self.assertEqual(purge_receipt["status"], "passed")
        self.assertEqual(self.manifest_value()["artifacts"][0]["status"], "purged")

    def test_stale_plan_fails_closed(self) -> None:
        self.write_file("failed.mp4")
        self.register("failed-001", "failed.mp4", status="qa_fail", failure_reason="bad render")
        plan = self.plan()
        self.write_file("other.mp4")
        self.register("other-001", "other.mp4")
        with self.assertRaises(LIFECYCLE.LifecycleError) as error:
            self.apply(plan, phase="quarantine")
        self.assertEqual(error.exception.code, "stale_gc_plan")

    def test_quarantined_artifact_can_be_restored_without_overwrite(self) -> None:
        self.write_file("failed.mp4")
        self.register("failed-001", "failed.mp4", status="qa_fail", failure_reason="bad render")
        receipt = self.apply(self.plan(), phase="quarantine")
        self.assertEqual(receipt["status"], "passed")
        restore = LIFECYCLE.restore_artifact(
            argparse.Namespace(
                manifest=str(self.manifest),
                workspace_root=str(self.root),
                artifact_id="failed-001",
                status="candidate",
                reason="operator recovered the candidate",
                now="2026-09-02T01:00:00Z",
            )
        )
        self.assertEqual(restore["status"], "passed")
        self.assertTrue((self.root / "failed.mp4").exists())
        artifact = self.manifest_value()["artifacts"][0]
        self.assertEqual(artifact["status"], "candidate")
        self.assertIsNone(artifact["delete_after"])

    def test_task_close_collects_only_disposable_kinds(self) -> None:
        self.write_file("cache.bin")
        self.write_file("candidate.mp4")
        self.register("cache-001", "cache.bin", kind="cache", status="created")
        self.register("candidate-001", "candidate.mp4", kind="candidate", status="candidate")
        plan = self.plan(task_close=True, now="2026-08-28T01:00:00Z")
        self.assertEqual([item["artifact_id"] for item in plan["items"]], ["cache-001"])

    def test_preflight_blocks_when_intermediate_budget_is_exceeded(self) -> None:
        self.write_file("candidate.mp4", b"0123456789")
        self.register("candidate-001", "candidate.mp4")
        value = self.manifest_value()
        value["policy"]["task_intermediate_limit_bytes"] = 5
        self.write_manifest(value)
        receipt = LIFECYCLE.preflight(
            argparse.Namespace(
                manifest=str(self.manifest),
                workspace_root=str(self.root),
                now="2026-08-28T01:00:00Z",
            )
        )
        self.assertEqual(receipt["status"], "blocked")
        self.assertTrue(receipt["metrics"]["safe_gc_required"])

    def test_small_known_output_is_warning_only_with_two_gib_free(self) -> None:
        with patch(
            "shutil.disk_usage",
            return_value=SimpleNamespace(
                total=100 * 1024**3,
                used=98 * 1024**3,
                free=2 * 1024**3,
            ),
        ):
            receipt = LIFECYCLE.preflight(
                argparse.Namespace(
                    manifest=str(self.manifest),
                    workspace_root=str(self.root),
                    output_class="small_known",
                    estimated_output_bytes=None,
                    core_root=str(ROOT.parent / "artifact-lifecycle-core"),
                    now="2026-08-29T00:00:00Z",
                )
            )
        self.assertEqual(receipt["status"], "passed")
        self.assertEqual(receipt["metrics"]["warning_codes"], ["low_disk_allowed"])
        self.assertEqual(receipt["metrics"]["minimum_free_bytes"], 512 * 1024**2)

    def test_large_output_without_estimate_fails_closed(self) -> None:
        receipt = LIFECYCLE.preflight(
            argparse.Namespace(
                manifest=str(self.manifest),
                workspace_root=str(self.root),
                output_class="large_or_unknown",
                estimated_output_bytes=None,
                core_root=str(ROOT.parent / "artifact-lifecycle-core"),
                now="2026-08-29T00:00:00Z",
            )
        )
        self.assertEqual(receipt["status"], "blocked")
        self.assertIn(
            "blocked_output_estimate_required",
            {item["reason"] for item in receipt["blocked"]},
        )

    def test_estimated_output_uses_shared_headroom_formula(self) -> None:
        with patch(
            "shutil.disk_usage",
            return_value=SimpleNamespace(
                total=100 * 1024**3,
                used=int(97.5 * 1024**3),
                free=int(2.5 * 1024**3),
            ),
        ):
            receipt = LIFECYCLE.preflight(
                argparse.Namespace(
                    manifest=str(self.manifest),
                    workspace_root=str(self.root),
                    output_class="large_or_unknown",
                    estimated_output_bytes=2 * 1024**3,
                    core_root=str(ROOT.parent / "artifact-lifecycle-core"),
                    now="2026-08-29T00:00:00Z",
                )
            )
        self.assertEqual(receipt["status"], "blocked")
        self.assertIn("blocked_low_disk", {item["reason"] for item in receipt["blocked"]})
        self.assertEqual(receipt["metrics"]["required_free_bytes"], 3 * 1024**3)

    def test_legacy_ratio_manifest_is_read_but_not_enforced(self) -> None:
        value = self.manifest_value()
        for key in (
            "minimum_free_bytes",
            "warning_free_bytes",
            "output_headroom_multiplier",
        ):
            value["policy"].pop(key)
        value["policy"]["min_free_ratio"] = 0.95
        self.write_manifest(value)
        with patch(
            "shutil.disk_usage",
            return_value=SimpleNamespace(
                total=100 * 1024**3,
                used=98 * 1024**3,
                free=2 * 1024**3,
            ),
        ):
            receipt = LIFECYCLE.preflight(
                argparse.Namespace(
                    manifest=str(self.manifest),
                    workspace_root=str(self.root),
                    output_class="small_known",
                    estimated_output_bytes=None,
                    core_root=str(ROOT.parent / "artifact-lifecycle-core"),
                    now="2026-08-29T00:00:00Z",
                )
            )
        self.assertEqual(receipt["status"], "passed")
        self.assertTrue(receipt["metrics"]["legacy_min_free_ratio_ignored"])

    def test_lock_is_idempotent(self) -> None:
        self.write_file("candidate.mp4")
        self.register("candidate-001", "candidate.mp4")
        args = argparse.Namespace(
            manifest=str(self.manifest),
            workspace_root=str(self.root),
            artifact_id="candidate-001",
            reason="approved master",
            now="2026-08-28T01:00:00Z",
        )
        LIFECYCLE.lock_artifact(args)
        receipt = LIFECYCLE.lock_artifact(args)
        self.assertTrue(receipt["items"][0]["idempotent"])


if __name__ == "__main__":
    unittest.main()
