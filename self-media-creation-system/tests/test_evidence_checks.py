"""Pure-stdlib unit tests for scripts/evidence_checks.py."""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from evidence_checks import (  # noqa: E402
    CHECK_STATUSES,
    classify_step_checkpoint,
    is_hollow_payload,
    make_check_result,
    summarize_sequence_checkpoints,
    validate_human_gate_credential,
)


class EvidenceChecksTests(unittest.TestCase):
    def test_make_check_result_valid_and_invalid(self):
        for st in CHECK_STATUSES:
            res = make_check_result("step_a", st, artifact_hash="a" * 64, details={"k": 1})
            self.assertEqual(res["status"], st)
            self.assertEqual(res["details"], {"k": 1})
        with self.assertRaises(ValueError):
            make_check_result("step_a", "unknown_status")

    def test_is_hollow_payload(self):
        self.assertTrue(is_hollow_payload(None))
        self.assertTrue(is_hollow_payload({}))
        self.assertTrue(is_hollow_payload([]))
        self.assertTrue(is_hollow_payload(""))
        self.assertTrue(is_hollow_payload({"placeholder": True, "schema": "x.v1"}))
        self.assertTrue(is_hollow_payload({"ok": True, "status": "passed"}))
        self.assertFalse(is_hollow_payload({"schema_version": "check.v1", "ok": True}))
        self.assertFalse(is_hollow_payload({"notes": "substantive content"}))

    def test_validate_human_gate_credential_accepts_bound_and_rejects_defects(self):
        valid = {
            "schema": "self-media.human-gate.v1",
            "reviewer": "human_editor_a",
            "reviewed_at": "2026-11-22T10:00:00+08:00",
            "decision": "approved",
            "step_id": "final-human-qa",
            "artifact_sha256": "b" * 64,
        }
        self.assertEqual(validate_human_gate_credential(valid, step_id="final-human-qa"), (True, "human_gate_credential_bound"))

        nested_hash = {
            "schema_version": "v1",
            "reviewed_by": "editor_b",
            "confirmed_at": "2026-11-22T10:01:00+08:00",
            "status": "confirmed",
            "target_ref": {"sha256": "c" * 64},
        }
        self.assertEqual(validate_human_gate_credential(nested_hash), (True, "human_gate_credential_bound"))

        self.assertEqual(validate_human_gate_credential({"ok": True})[1], "hollow_human_gate_output")
        self.assertEqual(validate_human_gate_credential({"reviewer": "ed", "details": 1})[1], "human_gate_schema_missing")
        for actor in ("", "assistant", "ai", "agent", "bot", "auto", "synthetic_auto"):
            bad = dict(valid, reviewer=actor)
            self.assertEqual(validate_human_gate_credential(bad)[1], "human_reviewer_required")
        self.assertEqual(validate_human_gate_credential({**valid, "reviewed_at": ""})[1], "human_reviewed_at_required")
        self.assertEqual(validate_human_gate_credential({**valid, "decision": "pending"})[1], "human_gate_decision_not_approved:pending")
        self.assertEqual(validate_human_gate_credential(valid, step_id="other-step")[1], "human_gate_step_mismatch")
        self.assertEqual(validate_human_gate_credential({**valid, "artifact_sha256": "not-sha256"})[1], "human_gate_artifact_hash_missing")

    def test_classify_and_summarize_sequence_checkpoints(self):
        self.assertEqual(classify_step_checkpoint("verify-canonical-route"), "charter_checkpoint")
        self.assertEqual(classify_step_checkpoint("final-human-qa"), "joint_delivery_checkpoint")
        self.assertEqual(classify_step_checkpoint("draft-outline"), "master_review_checkpoint")

        steps = [
            {"step_id": "verify-canonical-route"},
            {"step_id": "draft-outline"},
            {"step_id": "edit-script"},
        ]
        s_inprog = summarize_sequence_checkpoints(
            steps,
            [
                {"step_id": "verify-canonical-route", "workflow_step_completed": True},
                {"step_id": "draft-outline", "workflow_step_completed": True},
            ],
        )
        self.assertEqual(s_inprog["charter_checkpoint"]["status"], "passed")
        self.assertEqual(s_inprog["master_review_checkpoint"]["status"], "in_progress")
        self.assertEqual(s_inprog["joint_delivery_checkpoint"]["status"], "not_required")

        s_pending = summarize_sequence_checkpoints([{"step_id": "final-human-qa"}], [])
        self.assertEqual(s_pending["joint_delivery_checkpoint"]["status"], "pending")


if __name__ == "__main__":
    unittest.main()
