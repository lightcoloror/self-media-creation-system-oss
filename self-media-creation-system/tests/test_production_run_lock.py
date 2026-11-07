from __future__ import annotations

import json
import shutil
import sys
import unittest
from pathlib import Path
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import production_run_lock as RUN_LOCK  # noqa: E402


class ProductionRunLockTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = ROOT / ".runtime" / f"production-lock-{uuid4().hex}"
        (self.root / "owner").mkdir(parents=True)
        (self.root / "owner" / "entry.py").write_text("print('v1')\n", encoding="utf-8")
        (self.root / "rule.json").write_text("{}\n", encoding="utf-8")
        self.spec_path = self.root / "spec.json"
        self.spec_path.write_text(
            json.dumps(
                {
                    "schema_version": "self-media-production-run-lock-spec.v1",
                    "run_id": "run-fixture-001",
                    "recipe_id": "case-video-candidate",
                    "lock_scope": "toolchain-and-static-rules-only",
                    "components": [
                        {
                            "tool_id": "fixture-owner",
                            "owner_root": "owner",
                            "entrypoints": ["entry.py"],
                        }
                    ],
                    "rule_files": ["rule.json"],
                }
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_lock_is_stable_and_verifies_exact_files(self) -> None:
        lock = RUN_LOCK.create_lock(
            self.spec_path,
            self.root,
            created_at="2026-08-29T12:00:00Z",
        )
        lock_path = self.root / "lock.json"
        lock_path.write_text(json.dumps(lock), encoding="utf-8")
        receipt = RUN_LOCK.verify_lock(lock_path, self.root)
        self.assertEqual("passed", receipt["status"])
        self.assertEqual(2, receipt["verified_file_count"])
        self.assertFalse(lock["drift_policy"]["active_run_can_absorb_code_changes"])
        self.assertEqual("toolchain-and-static-rules-only", lock["lock_scope"])
        self.assertNotIn("script", lock)
        self.assertNotIn("video", lock)
        self.assertNotIn("privacy", lock)

    def test_tool_change_invalidates_active_run(self) -> None:
        lock = RUN_LOCK.create_lock(
            self.spec_path,
            self.root,
            created_at="2026-08-29T12:00:00Z",
        )
        lock_path = self.root / "lock.json"
        lock_path.write_text(json.dumps(lock), encoding="utf-8")
        (self.root / "owner" / "entry.py").write_text("print('v2')\n", encoding="utf-8")
        with self.assertRaises(RUN_LOCK.ProductionRunLockError) as context:
            RUN_LOCK.verify_lock(lock_path, self.root)
        self.assertEqual("production_toolchain_drift", context.exception.code)

    def test_lock_scope_cannot_claim_script_media_or_privacy(self) -> None:
        spec = json.loads(self.spec_path.read_text(encoding="utf-8"))
        spec["lock_scope"] = "script-media-privacy-and-toolchain"
        self.spec_path.write_text(json.dumps(spec), encoding="utf-8")
        with self.assertRaises(RUN_LOCK.ProductionRunLockError) as context:
            RUN_LOCK.create_lock(self.spec_path, self.root)
        self.assertEqual("schema_validation_failed", context.exception.code)


if __name__ == "__main__":
    unittest.main()
