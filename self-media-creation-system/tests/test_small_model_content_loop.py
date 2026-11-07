from __future__ import annotations

import copy
import json
import os
import shutil
import sys
import unittest
import uuid
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import small_model_content_loop as loop  # noqa: E402


BASE_FIXTURE = REPO_ROOT / "fixtures" / "small-model-content-loop-v1" / "input.valid.json"


class SmallModelContentLoopTests(unittest.TestCase):
    def test_registered_route_errors_are_not_replaced_by_legacy_version_loading(self) -> None:
        from unittest.mock import patch
        binding = loop.current_routing.load_binding()
        self.assertEqual(loop.ROUTING_CONTRACT_VERSION, binding["canonical_contract_set_version"])
        with patch.object(loop.current_routing, "load_contracts", side_effect=ValueError("synthetic component hash drift")):
            with self.assertRaises(loop.LoopError) as caught:
                loop.load_routing()
        self.assertEqual(caught.exception.code, "routing_contract_drift")

    def setUp(self) -> None:
        runtime = REPO_ROOT / "tests" / ".runtime"
        runtime.mkdir(parents=True, exist_ok=True)
        self.root = runtime / f"small-model-loop-{os.getpid()}-{uuid.uuid4().hex}"
        self.root.mkdir()
        self.request = json.loads(BASE_FIXTURE.read_text(encoding="utf-8"))

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def write_request(self, value: dict, name: str = "request.json") -> Path:
        path = self.root / name
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return path

    def run_case(self, value: dict, name: str = "run") -> tuple[dict, Path]:
        request_path = self.write_request(value, f"{name}.input.json")
        run_root = self.root / name
        return loop.run_loop(request_path, run_root), run_root

    def assert_error(self, value: dict, code: str, name: str) -> Path:
        request_path = self.write_request(value, f"{name}.input.json")
        run_root = self.root / name
        with self.assertRaises(loop.LoopError) as caught:
            loop.run_loop(request_path, run_root)
        self.assertEqual(caught.exception.code, code)
        failure = json.loads((run_root / "failure.json").read_text(encoding="utf-8"))
        self.assertEqual(failure["error_code"], code)
        self.assertEqual(failure["automatic_retries"], 0)
        return run_root

    def test_doctor_and_positive_candidate_loop(self) -> None:
        self.assertEqual(loop.doctor()["status"], "pass")
        result, run_root = self.run_case(self.request)
        self.assertEqual(result["status"], "completed")
        manifest = json.loads((run_root / "run-manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["completed_stages"], list(loop.STAGES))
        self.assertEqual(manifest["retry_policy"]["automatic_retries"], 0)
        candidate = json.loads((run_root / "artifacts" / "canonical-content-candidate.json").read_text(encoding="utf-8"))
        self.assertEqual(candidate["status"], "candidate")
        self.assertEqual(candidate["publication"]["boundary"], "manual-only")
        variants = json.loads((run_root / "artifacts" / "platform-fit-variants.json").read_text(encoding="utf-8"))
        self.assertEqual(len(variants["variants"]), 6)
        self.assertEqual(variants["routing_contract"]["platform_count"], 12)
        self.assertEqual(len(variants["validated_only_platforms"]), 6)
        self.assertTrue(all(item["standalone"] for item in variants["variants"]))
        self.assertTrue(all(item["evidence_refs"] == variants["variants"][0]["evidence_refs"] for item in variants["variants"]))
        review = json.loads((run_root / "artifacts" / "review-packet.json").read_text(encoding="utf-8"))
        self.assertFalse(review["metadata"]["execution_authorized"])
        self.assertEqual(len(review["payload"]["suggested_points"]), 3)

    def test_pause_resume_and_idempotent_completed_run(self) -> None:
        request_path = self.write_request(self.request, "pause.input.json")
        run_root = self.root / "pause"
        paused = loop.run_loop(request_path, run_root, pause_after="candidate")
        self.assertEqual(paused["status"], "paused")
        self.assertIn("resume", paused["resume_entry"])
        resumed = loop.resume_loop(run_root)
        self.assertEqual(resumed["status"], "completed")
        manifest_path = run_root / "run-manifest.json"
        before = loop.sha256_file(manifest_path)
        repeated = loop.run_loop(request_path, run_root)
        after = loop.sha256_file(manifest_path)
        self.assertEqual(repeated["status"], "already_completed")
        self.assertEqual(before, after)

    def test_same_run_id_with_different_input_fails_closed(self) -> None:
        request_path = self.write_request(self.request, "identity-a.json")
        run_root = self.root / "identity"
        loop.run_loop(request_path, run_root, pause_after="preflight")
        changed = copy.deepcopy(self.request)
        changed["topic"] = "另一个完全虚构的问题"
        changed_path = self.write_request(changed, "identity-b.json")
        with self.assertRaises(loop.LoopError) as caught:
            loop.run_loop(changed_path, run_root)
        self.assertEqual(caught.exception.code, "closure_run_identity_drift")

    def test_source_hash_drift(self) -> None:
        value = copy.deepcopy(self.request)
        value["evidence_bundle"]["sha256"] = "a" * 64
        self.assert_error(value, "source_hash_drift", "source-drift")

    def test_versioned_text_hash_is_line_ending_portable(self) -> None:
        lf_path = self.root / "portable-lf.json"
        crlf_path = self.root / "portable-crlf.json"
        lf_path.write_bytes(b'{"synthetic_only":true}\n')
        crlf_path.write_bytes(b'{"synthetic_only":true}\r\n')
        self.assertNotEqual(loop.sha256_file(lf_path), loop.sha256_file(crlf_path))
        self.assertEqual(loop.normalized_sha256(lf_path), loop.normalized_sha256(crlf_path))

    def test_routing_contract_hash_drift(self) -> None:
        value = copy.deepcopy(self.request)
        value["contract_binding"]["routing_set_sha256"] = "b" * 64
        self.assert_error(value, "contract_hash_drift", "route-drift")

    def test_privacy_field_is_rejected(self) -> None:
        value = copy.deepcopy(self.request)
        value["customer_name"] = "禁止进入夹具的姓名字段"
        self.assert_error(value, "input_schema_invalid", "privacy")

    def test_unverified_fact_requires_source(self) -> None:
        value = copy.deepcopy(self.request)
        value["claim_units"][0]["fact_status"] = "unverified"
        self.assert_error(value, "needs_source", "needs-source")

    def test_fact_status_specific_guards(self) -> None:
        position = copy.deepcopy(self.request)
        position["claim_units"][0]["fact_status"] = "verified_position"
        self.assert_error(position, "position_not_confirmed", "position")

        framework = copy.deepcopy(self.request)
        framework["claim_units"][0]["fact_status"] = "framework_application"
        self.assert_error(framework, "framework_ref_missing", "framework")

        inference = copy.deepcopy(self.request)
        inference["claim_units"][0]["fact_status"] = "agent_inference"
        self.assert_error(inference, "inference_unlabelled", "inference")

    def test_human_voice_hash_drift(self) -> None:
        value = copy.deepcopy(self.request)
        value["human_voice_attestation"]["body_sha256"] = "c" * 64
        self.assert_error(value, "human_voice_body_hash_drift", "voice")

    def test_premature_finalize_is_rejected(self) -> None:
        value = copy.deepcopy(self.request)
        value["requested_final_state"] = "published"
        self.assert_error(value, "premature_finalize_forbidden", "finalize")

    def test_series_numbering_is_rejected(self) -> None:
        value = copy.deepcopy(self.request)
        value["canonical_seed"]["title"] = "第1集：买了保险，理赔前要先核对什么？"
        self.assert_error(value, "standalone_variant_failed", "series")

    def test_registered_negative_catalog(self) -> None:
        cases = REPO_ROOT / "fixtures" / "small-model-content-loop-v1" / "negative-cases.json"
        result = loop.check_negative_cases(cases, self.root / "catalog-negatives")
        self.assertEqual(result["status"], "pass")
        self.assertGreaterEqual(result["case_count"], 5)


if __name__ == "__main__":
    unittest.main()
