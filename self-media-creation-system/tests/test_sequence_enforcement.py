from __future__ import annotations

import copy
import importlib.util
import json
import shutil
import subprocess
import sys
import unittest
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import purpose_continuity as PURPOSE
SCRIPT = ROOT / "scripts" / "self_media_agent.py"
SPEC = importlib.util.spec_from_file_location("self_media_agent_sequence", SCRIPT)
assert SPEC and SPEC.loader
AGENT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AGENT)


class SequenceEnforcementTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = ROOT / "outputs" / "test-temp" / ("sequence-enforcement-" + uuid.uuid4().hex)
        self.root.mkdir(parents=True, exist_ok=True)
        request = AGENT.load_json(AGENT.RECIPE_FIXTURES["moments-short-post"])
        self.capsule = AGENT.resolve_request(request)
        self.capsule_path = self.root / "capsule.json"
        AGENT.write_or_print(self.capsule, self.capsule_path)

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def _complete_step(self, step: dict, previous_receipt: Path | None) -> Path:
        artifacts = []
        for index, source_role in enumerate(step["input_roles"]):
            source = self.root / ('shared-purpose-source.json' if index == 0 else f"{step['step_id']}-input-{index}.json")
            payload = {"synthetic_only": True, "purpose": "Synthetic transport purpose.",
                       "audience": "Synthetic test readers."}
            if index != 0:
                payload['source_role'] = source_role
            raw = json.dumps(payload)
            if source.exists():
                self.assertEqual(source.read_text(encoding='utf-8'), raw)
            else:
                source.write_text(raw, encoding='utf-8')
            artifacts.append(
                {
                    "artifact_id": f"{step['step_id']}-input-{index}",
                    "role": "source_manifest",
                    "source_role": source_role,
                    "path": source.name,
                    "load_mode": "reference",
                    "expected_sha256": AGENT.sha256_file(source),
                }
            )
        manifest_path = self.root / f"{step['step_id']}-context.json"
        self.assertTrue(artifacts, 'This sequence fixture must carry an actual recipe input role')
        anchor_id = artifacts[0]['artifact_id']
        editorial_context = dict(version=1, content_id='synthetic-sequence-only',
            purpose=dict(artifact_id=anchor_id, quote='Synthetic transport purpose.'),
            audience=dict(artifact_id=anchor_id, quote='Synthetic test readers.'),
            stage_duty='Only exercise transport at ' + step['step_id'],
            current_body_artifact_id=anchor_id, feedback=[],
            feedback_note='No real author feedback or approval in this synthetic fixture.')
        manifest_path.write_text(
            json.dumps(
                {
                    "schema_version": "self-media-context-input.v1",
                    "task_id": self.capsule["request_id"],
                    "stage": step["context_stage"],
                    "budget": {"max_inline_bytes": 4096},
                    "artifacts": artifacts,
                    "editorial_context": editorial_context,
                }
            ),
            encoding="utf-8",
        )
        handoff_path = self.root / f"{step['step_id']}-handoff.json"
        handoff = AGENT.prepare_step_handoff(
            self.capsule_path,
            step["step_id"],
            manifest_path,
            self.root / f"{step['step_id']}-context-receipt.json",
            handoff_path,
            previous_receipt,
        )
        output = self.root / f"{step['step_id']}-candidate.json"
        output.write_text('{"synthetic_only":true}', encoding="utf-8")
        review = self.root / f"{step['step_id']}-purpose-review.json"
        review.write_text(json.dumps(dict(schema_version=PURPOSE.REVIEW_SCHEMA,
            context_ref=dict(path=manifest_path.name, sha256=AGENT.sha256_file(manifest_path)),
            artifact_ref=dict(path=output.name, sha256=AGENT.sha256_file(output)),
            quote=output.read_text(encoding='utf-8'),
            purpose_alignment=dict(stage_duty=editorial_context['stage_duty'],
                contribution='Synthetic transport only; no content improvement is claimed.',
                misunderstanding_risk='Do not confuse a transport receipt with author agreement or prose quality.',
                tradeoff='Retain the placeholder for sequence testing; real writing still requires author inputs.'),
            feedback_resolutions=[], disposition='retained', reason='Inert synthetic sequence fixture only.'
        )), encoding='utf-8')
        receipt = {
            "schema_version": "self-media-step-output-receipt.v1",
            "status": "human_gate_recorded" if step["interface"] == "human_gate" else "candidate_ready",
            "handoff": {"path": handoff_path.name, "sha256": AGENT.sha256_file(handoff_path)},
            "step_id": step["step_id"],
            "tool_id": step["tool_id"],
            "output_contract": step["output_contract"],
            "outputs": [{"path": output.name, "sha256": AGENT.sha256_file(output)},
                        {"path": review.name, "sha256": AGENT.sha256_file(review)}],
            "boundaries": copy.deepcopy(self.capsule["boundaries"]),
        }
        receipt["payload_sha256"] = AGENT.sha256_value(receipt)
        receipt_path = self.root / f"{step['step_id']}-receipt.json"
        AGENT.write_or_print(receipt, receipt_path)
        return receipt_path

    def test_status_exposes_exactly_one_next_step(self) -> None:
        initial = AGENT.derive_sequence_status(self.capsule_path, [])
        self.assertEqual(initial["sequence_state"], "next_step_required")
        self.assertEqual(initial["next_step"]["step_id"], self.capsule["step_index"][0]["step_id"])
        self.assertEqual(initial["accepted_steps"], [])
        self.assertFalse(initial["completion"]["managed_pipeline_completion_claim_allowed"])

        first_receipt = self._complete_step(self.capsule["step_index"][0], None)
        advanced = AGENT.derive_sequence_status(self.capsule_path, [first_receipt])
        self.assertEqual(advanced["next_step"]["step_id"], self.capsule["step_index"][1]["step_id"])
        self.assertEqual([row["step_id"] for row in advanced["accepted_steps"]], [self.capsule["step_index"][0]["step_id"]])
        self.assertEqual(advanced["semantic_evidence_pending"], [self.capsule["step_index"][0]["step_id"]])

    def test_incomplete_or_reordered_receipts_fail_closed(self) -> None:
        with self.assertRaises(AGENT.AgentEntryError) as incomplete:
            AGENT.require_sequence_complete(self.capsule_path, [])
        self.assertEqual(incomplete.exception.code, "sequence_incomplete")

        first = self._complete_step(self.capsule["step_index"][0], None)
        second = self._complete_step(self.capsule["step_index"][1], first)
        with self.assertRaises(AGENT.AgentEntryError) as reordered:
            AGENT.derive_sequence_status(self.capsule_path, [second, first])
        self.assertEqual(reordered.exception.code, "sequence_receipt_order")

    def test_paper_chain_cannot_skip_creative_and_author_inputs(self) -> None:
        receipts = []
        previous = None
        for step in self.capsule["step_index"]:
            if step["step_id"] in AGENT._load_author_writing_context().WRITING_STEPS:
                # A transport-only placeholder is no longer enough to enter a
                # writing step. Preserve the real gate, rather than fabricating
                # an author store and claiming a paper-complete chain.
                with self.assertRaises(AGENT.AgentEntryError) as missing:
                    self._complete_step(step, previous)
                self.assertEqual(missing.exception.code, "creation_route_required")
                break
            previous = self._complete_step(step, previous)
            receipts.append(previous)
        else:
            self.fail("fixture no longer exercises the writing boundary")
        status = AGENT.derive_sequence_status(self.capsule_path, receipts)
        self.assertEqual(status["sequence_state"], "next_step_required")
        self.assertFalse(status["completion"]["all_steps_recorded"])
        self.assertFalse(status["completion"]["all_owner_semantics_verified"])
        self.assertFalse(status["completion"]["managed_pipeline_completion_claim_allowed"])
        with self.assertRaises(AGENT.AgentEntryError) as pending:
            AGENT.require_sequence_complete(self.capsule_path, receipts)
        self.assertEqual(pending.exception.code, "sequence_incomplete")

    def test_cli_reports_next_step_and_blocks_premature_completion(self) -> None:
        status = subprocess.run(
            [sys.executable, "-B", str(SCRIPT), "sequence-status", "--capsule", str(self.capsule_path)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(status.returncode, 0, status.stderr or status.stdout)
        self.assertEqual(json.loads(status.stdout)["sequence_state"], "next_step_required")
        blocked = subprocess.run(
            [
                sys.executable,
                "-B",
                str(SCRIPT),
                "sequence-status",
                "--capsule",
                str(self.capsule_path),
                "--require-complete",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(blocked.returncode, 2)
        self.assertEqual(json.loads(blocked.stdout)["error_code"], "sequence_incomplete")


if __name__ == "__main__":
    unittest.main()
