from __future__ import annotations

import copy
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import unittest
import uuid
from unittest import mock
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "self_media_agent.py"
SPEC = importlib.util.spec_from_file_location("self_media_agent", SCRIPT)
assert SPEC and SPEC.loader
AGENT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AGENT)


class SelfMediaAgentTests(unittest.TestCase):
    def test_manifest_and_schemas_are_valid(self) -> None:
        manifest = AGENT.load_json(AGENT.MANIFEST_PATH)
        AGENT.validate_document(manifest, AGENT.MANIFEST_SCHEMA_PATH, "manifest")
        for schema_path in (
            AGENT.CATALOG_SCHEMA_PATH,
            AGENT.REQUEST_SCHEMA_PATH,
            AGENT.CAPSULE_SCHEMA_PATH,
            AGENT.CAPSULE_V2_SCHEMA_PATH,
            AGENT.HANDOFF_SCHEMA_PATH,
            AGENT.OUTPUT_RECEIPT_SCHEMA_PATH,
            AGENT.SEQUENCE_STATUS_SCHEMA_PATH,
            AGENT.CONTEXT_MANIFEST_SCHEMA_PATH,
            AGENT.VIDEO_PRIVACY_DECISION_SCHEMA_PATH,
            AGENT.CUSTOMER_VIDEO_EFFECT_REVIEW_SCHEMA_PATH,
            AGENT.PREPUBLICATION_PRIVACY_GATE_SCHEMA_PATH,
            AGENT.QRP_RESEARCH_OUTPUT_SCHEMA_PATH,
            ROOT / "schemas" / "short-video-timing-evidence-input.v1.schema.json",
            ROOT / "schemas" / "short-video-timing-evidence.v1.schema.json",
        ):
            Draft202012Validator.check_schema(AGENT.load_json(schema_path))

    def test_doctor_reports_five_bounded_cold_starts(self) -> None:
        receipt = AGENT.doctor()
        self.assertTrue(receipt["ok"])
        self.assertEqual(receipt["status"], "metadata_contracts_ready")
        self.assertEqual(receipt["external_runtime_verification"], "not-performed")
        self.assertEqual(receipt["cold_start_paths_passed"], 5)
        self.assertGreaterEqual(receipt["tool_contracts_resolved"], 10)
        self.assertEqual(receipt["consumer_commands_resolved"], 3)
        self.assertTrue(receipt["direct_operations_discoverable"])
        self.assertEqual(receipt["direct_operations_tool_id"], "content-operations-cycle")
        self.assertEqual(receipt["direct_operations_registry_commands"], 5)
        self.assertTrue(receipt["source_role_required_for_step_handoff"])
        self.assertTrue(receipt["derived_sequence_gate_ready"])
        self.assertLessEqual(receipt["largest_capsule_bytes"], receipt["capsule_max_bytes"])
        self.assertFalse(receipt["proves_current_online"])
        self.assertFalse(receipt["proves_publication_authority"])

    def test_human_publication_report_has_a_direct_machine_discoverable_route(self) -> None:
        route = AGENT.operations_capability()
        self.assertEqual(route["status"], "discoverable")
        self.assertEqual(route["tool_id"], "content-operations-cycle")
        self.assertIn("record-publication", route["record_commands"]["publication"])
        self.assertIn("record-publication-edit", route["record_commands"]["publication_edit"])
        self.assertIn("record-publication-delete", route["record_commands"]["publication_delete"])
        self.assertIn("record-publication-restore", route["record_commands"]["publication_restore"])
        self.assertIn("record-snapshot", route["record_commands"]["snapshot"])
        self.assertIn("not a publication event", route["scheduled_content_policy"])
        self.assertIn("date-only", route["scheduled_content_policy"])
        self.assertIn("do not invent", route["scheduled_record_route"])
        self.assertEqual(route["canonical_snapshot_windows_hours"]["early"], [48, 72])
        self.assertEqual(route["canonical_snapshot_windows_hours"]["d7"], [156, 180])
        self.assertIn("provisional", route["interim_observation_policy"])
        self.assertFalse(route["boundaries"]["opens_platform"])
        self.assertFalse(route["boundaries"]["publishes"])

    def test_capabilities_separates_direct_recording_from_retrospective_review(self) -> None:
        value = AGENT.capabilities()
        self.assertEqual(value["direct_operations"]["tool_id"], "content-operations-cycle")
        feedback = next(
            item for item in value["workflows"]
            if item["workflow_goal"] == "publication_feedback_review"
        )
        self.assertEqual(feedback["recipe_id"], "publication-feedback-review")
        self.assertIn("only after", value["direct_operations"]["review_route"])
        self.assertEqual(value["sequence_enforcement"]["next_step_count"], 1)
        self.assertFalse(value["sequence_enforcement"]["persistent_parallel_state"])
        self.assertFalse(value["sequence_enforcement"]["transport_only_is_managed_completion"])

    def test_authoring_is_discoverable_within_five_existing_workflows(self) -> None:
        value = AGENT.capabilities()
        authoring = value["authoring"]
        self.assertEqual(5, len(value["workflows"]))
        self.assertEqual(5, authoring["workflow_count"])
        self.assertEqual("discoverable", authoring["status"])
        self.assertEqual("author-writing-context", authoring["required_writing_role"])
        self.assertEqual("author-revision-review", authoring["required_review_role"])
        self.assertIn("Empty approved-sample recall", authoring["cold_start_policy"])
        self.assertIn("author-confirmed spans", authoring["sample_adoption_policy"])
        self.assertEqual(AGENT.EXPECTED_BOUNDARIES, authoring["boundaries"])

    def test_creative_requests_require_explicit_author_identity(self) -> None:
        for recipe_id in ("moments-short-post", "xhs-evidence-graphic", "case-video-candidate"):
            with self.subTest(recipe_id=recipe_id):
                request = AGENT.load_json(AGENT.RECIPE_FIXTURES[recipe_id])
                request.pop("author_identity")
                with self.assertRaises(AGENT.AgentEntryError) as caught:
                    AGENT.resolve_request(request)
                self.assertEqual("schema_validation_failed", caught.exception.code)
        for recipe_id in ("publication-feedback-review", "context-efficient-rework"):
            request = AGENT.load_json(AGENT.RECIPE_FIXTURES[recipe_id])
            self.assertNotIn("author_identity", request)
            self.assertNotIn("author_identity", AGENT.resolve_request(request)["provenance"])

    def test_genre_matches_workflow_and_author_identity_is_hash_bound(self) -> None:
        fixtures = [AGENT.RECIPE_FIXTURES[name] for name in ("moments-short-post", "xhs-evidence-graphic", "case-video-candidate")]
        fixtures += [ROOT / "fixtures/agent-entry/prerecord-spoken.request.json", ROOT / "fixtures/agent-entry/prerecord-interview.request.json"]
        for fixture in fixtures:
            with self.subTest(fixture=fixture.name):
                request = AGENT.load_json(fixture)
                capsule = AGENT.resolve_request(request)
                self.assertEqual(request["author_identity"], capsule["provenance"]["author_identity"])
                capsule["provenance"]["author_identity"]["account_id"] = "other-account"
                self.assertFalse(AGENT.validate_capsule_hash(capsule))
                request["author_identity"]["genre"] = "graphic_note" if request["author_identity"]["genre"] != "graphic_note" else "moments"
                with self.assertRaises(AGENT.AgentEntryError) as caught:
                    AGENT.resolve_request(request)
                self.assertEqual("author_genre_mismatch", caught.exception.code)

    def test_author_account_cannot_be_blank(self) -> None:
        request = AGENT.load_json(AGENT.RECIPE_FIXTURES["moments-short-post"])
        for account in ("", "   "):
            request["author_identity"]["account_id"] = account
            with self.assertRaises(AGENT.AgentEntryError) as caught:
                AGENT.resolve_request(request)
            self.assertEqual("schema_validation_failed", caught.exception.code)

    def test_all_writing_and_author_review_routes_require_persistent_inputs(self) -> None:
        authoring = AGENT.authoring_capability()
        catalog = AGENT.load_catalog()
        seen_writing, seen_review = set(), set()
        for recipe in catalog["recipes"]:
            prerecord = recipe.get("prerecording") or {}
            for step in recipe["steps"] + prerecord.get("steps", []) + prerecord.get("interview_steps", []):
                step_id = step["step_id"]
                if step_id in authoring["writing_steps"]:
                    seen_writing.add(step_id)
                    self.assertIn("author-writing-context", step["input_roles"])
                    self.assertIn("author-writing-revision.v1", step["output_contract"].split("+"))
                if step_id in authoring["review_steps"]:
                    seen_review.add(step_id)
                    self.assertIn("author-writing-context", step["input_roles"])
                    self.assertIn("author-revision-review", step["input_roles"])
        self.assertEqual(set(authoring["writing_steps"]), seen_writing)
        self.assertEqual(set(authoring["review_steps"]), seen_review)

    def test_catalog_cannot_silently_drop_author_judgment_protection(self) -> None:
        catalog = AGENT.load_json(AGENT.CATALOG_PATH)
        moments = next(row for row in catalog["recipes"] if row["recipe_id"] == "moments-short-post")
        draft = next(row for row in moments["steps"] if row["step_id"] == "draft-one-observation")
        draft["input_roles"].remove("author-writing-context")
        real_load = AGENT.load_json
        with mock.patch.object(AGENT, "load_json", side_effect=lambda path: catalog if path == AGENT.CATALOG_PATH else real_load(path)):
            with self.assertRaises(AGENT.AgentEntryError) as caught:
                AGENT.load_catalog()
        self.assertEqual("author_route_incomplete", caught.exception.code)

    def test_all_fixtures_resolve_to_expected_compact_capsules(self) -> None:
        capsule_schema = AGENT.load_json(AGENT.CAPSULE_V2_SCHEMA_PATH)
        validator = Draft202012Validator(capsule_schema, format_checker=FormatChecker())
        for recipe_id, fixture_path in AGENT.RECIPE_FIXTURES.items():
            with self.subTest(recipe_id=recipe_id):
                capsule = AGENT.resolve_request(AGENT.load_json(fixture_path))
                self.assertEqual(capsule["status"], "routing_ready")
                self.assertEqual(capsule["recipe_id"], recipe_id)
                self.assertFalse(list(validator.iter_errors(capsule)))
                self.assertTrue(AGENT.validate_capsule_hash(capsule))
                self.assertNotIn("steps", capsule)
                self.assertNotIn("error_recovery", capsule)
                self.assertTrue(all(item["handoff_required"] for item in capsule["step_index"]))
                self.assertEqual(capsule["route_application"]["mode"], "selected-recipe-subset-only")
                self.assertFalse(capsule["route_application"]["canonical_order_is_universal_checklist"])
                self.assertEqual(capsule["route_application"]["skipped_steps"], [])
                self.assertTrue(capsule["route_application"]["skip_reason_required"])
                self.assertEqual(len(capsule["tool_index"]), len(capsule["step_index"]))
                self.assertLessEqual(
                    len(AGENT.canonical_bytes(capsule)),
                    capsule["context_loading"]["capsule_max_bytes"],
                )

    def test_double_resolve_is_byte_stable(self) -> None:
        request = AGENT.load_json(AGENT.RECIPE_FIXTURES["xhs-evidence-graphic"])
        first = AGENT.resolve_request(request)
        second = AGENT.resolve_request(copy.deepcopy(request))
        self.assertEqual(AGENT.canonical_bytes(first), AGENT.canonical_bytes(second))

    def test_missing_input_blocks_without_inventing_it(self) -> None:
        request = AGENT.load_json(AGENT.RECIPE_FIXTURES["moments-short-post"])
        request["available_inputs"].remove("voice_profile_ref")
        capsule = AGENT.resolve_request(request)
        self.assertEqual(capsule["status"], "blocked_missing_inputs")
        self.assertEqual(capsule["missing_inputs"], ["voice_profile_ref"])
        self.assertNotIn("voice_profile_ref", capsule["provided_inputs"])

    def test_unknown_goal_fails_schema_validation(self) -> None:
        request = AGENT.load_json(AGENT.RECIPE_FIXTURES["moments-short-post"])
        request["workflow_goal"] = "invent_a_new_workflow"
        with self.assertRaises(AGENT.AgentEntryError) as caught:
            AGENT.resolve_request(request)
        self.assertEqual(caught.exception.code, "schema_validation_failed")

    def test_stale_input_reference_fails_closed(self) -> None:
        request = AGENT.load_json(AGENT.RECIPE_FIXTURES["moments-short-post"])
        request["input_refs"] = [
            {
                "role": "voice_profile_ref",
                "path": "fixtures/agent-entry/moments-short-post.request.json",
                "sha256": "0" * 64,
            }
        ]
        with self.assertRaises(AGENT.AgentEntryError) as caught:
            AGENT.resolve_request(request)
        self.assertEqual(caught.exception.code, "source_hash_drift")

    def test_unbound_and_duplicate_refs_fail_closed(self) -> None:
        fixture_path = AGENT.RECIPE_FIXTURES["moments-short-post"]
        digest = AGENT.sha256_file(fixture_path)
        relative = fixture_path.relative_to(ROOT).as_posix()
        request = AGENT.load_json(fixture_path)
        request["input_refs"] = [{"role": "unknown_role", "path": relative, "sha256": digest}]
        with self.assertRaises(AGENT.AgentEntryError) as unbound:
            AGENT.resolve_request(request)
        self.assertEqual(unbound.exception.code, "input_ref_unbound")

        request = AGENT.load_json(fixture_path)
        ref = {"role": "voice_profile_ref", "path": relative, "sha256": digest}
        request["input_refs"] = [ref, copy.deepcopy(ref)]
        with self.assertRaises(AGENT.AgentEntryError) as duplicate:
            AGENT.resolve_request(request)
        self.assertEqual(duplicate.exception.code, "input_ref_duplicate")

    def test_capsule_hash_detects_tampering(self) -> None:
        capsule = AGENT.resolve_request(
            AGENT.load_json(AGENT.RECIPE_FIXTURES["publication-feedback-review"])
        )
        capsule["boundaries"]["publication"] = "automatic"
        self.assertFalse(AGENT.validate_capsule_hash(capsule))
        errors = AGENT.schema_errors(
            capsule,
            AGENT.load_json(AGENT.CAPSULE_V2_SCHEMA_PATH),
            "tampered_capsule",
        )
        self.assertTrue(any("manual-only" in error for error in errors))

    def test_boundaries_and_human_stop_are_invariant(self) -> None:
        catalog = AGENT.load_catalog()
        self.assertEqual(catalog["boundaries"], AGENT.EXPECTED_BOUNDARIES)
        for recipe in catalog["recipes"]:
            with self.subTest(recipe=recipe["recipe_id"]):
                self.assertEqual(recipe["steps"][-1]["interface"], "human_gate")
                for step in recipe["steps"]:
                    if step["interface"] == "cli":
                        command = f" {step['command'].lower()} "
                        for forbidden in (" publish ", " upload ", " send ", " post "):
                            self.assertNotIn(forbidden, command)
        feedback = next(
            recipe
            for recipe in catalog["recipes"]
            if recipe["recipe_id"] == "publication-feedback-review"
        )
        self.assertEqual(len(feedback["steps"]), 2)
        self.assertEqual(feedback["steps"][0]["interface"], "cli")
        self.assertEqual(feedback["steps"][0]["tool_id"], "content-operations-cycle")
        self.assertEqual(feedback["steps"][-1]["interface"], "human_gate")
        self.assertNotIn(
            "publication-feedback-tracker",
            {step["tool_id"] for step in feedback["steps"]},
        )
        graphic = next(
            recipe for recipe in catalog["recipes"] if recipe["recipe_id"] == "xhs-evidence-graphic"
        )
        package_verify = next(
            step for step in graphic["steps"] if step["step_id"] == "verify-frozen-package"
        )
        self.assertEqual(package_verify["interface"], "cli")
        self.assertEqual(package_verify["tool_id"], "content-packaging-review")
        self.assertIn("content_packaging_review.py create", package_verify["command"])
        self.assertEqual(
            AGENT._tool_descriptor("content-packaging-review", detailed=True)["discovery_mode"],
            "repository_internal",
        )
        self.assertEqual(graphic["steps"][-1]["tool_id"], "manual-publication-boundary")
        graphic_steps = [step["step_id"] for step in graphic["steps"]]
        self.assertLess(
            graphic_steps.index("discover-research-owner"),
            graphic_steps.index("produce-verified-research-output"),
        )
        self.assertLess(
            graphic_steps.index("produce-verified-research-output"),
            graphic_steps.index("build-evidence-draft"),
        )
        research_step = next(step for step in graphic["steps"] if step["step_id"] == "produce-verified-research-output")
        self.assertEqual(research_step["tool_id"], "question-research-poc")
        self.assertEqual(research_step["output_contract"], "research-output.v1")
        for recipe_id, downstream_step in (
            ("moments-short-post", "draft-one-observation"),
            ("xhs-evidence-graphic", "discover-research-owner"),
        ):
            recipe = next(item for item in catalog["recipes"] if item["recipe_id"] == recipe_id)
            step_ids = [item["step_id"] for item in recipe["steps"]]
            self.assertLess(step_ids.index("propose-editorial-angle"), step_ids.index("confirm-editorial-angle"))
            self.assertLess(step_ids.index("confirm-editorial-angle"), step_ids.index(downstream_step))
            self.assertIn("editorial-goal-alignment", recipe["quality_gates"])
        self.assertEqual(
            AGENT._tool_descriptor("topic-angle-decision", detailed=True)["discovery_mode"],
            "repository_internal",
        )
        self.assertEqual(
            AGENT._tool_descriptor("editorial-angle-human-review-gate", detailed=True)["execution_authority"],
            "human-only",
        )
        case_video = next(
            recipe for recipe in catalog["recipes"] if recipe["recipe_id"] == "case-video-candidate"
        )
        self.assertEqual(
            [step["step_id"] for step in case_video["steps"]],
            [
                "verify-production-run-lock",
                "capture-initial-privacy-treatment",
                "project-case-script",
                "complete-human-voice-gate",
                "verify-case-audience-path",
                "handoff-video-owner",
                "final-timing",
                "verify-privacy-redaction-binding",
                "record-customer-video-effect-review",
                "evaluate-prepublication-privacy",
                "confirm-manual-publication-or-rework",
            ],
        )
        audience_path_verify = next(
            step for step in case_video["steps"] if step["step_id"] == "verify-case-audience-path"
        )
        self.assertEqual(audience_path_verify["interface"], "cli")
        self.assertEqual(audience_path_verify["tool_id"], "content-packaging-review")
        self.assertIn("content_packaging_review.py create", audience_path_verify["command"])
        final_timing = next(
            step for step in case_video["steps"] if step["step_id"] == "final-timing"
        )
        self.assertEqual("video-timing", final_timing["tool_id"])
        self.assertIn("short_video_timing_evidence.py create", final_timing["command"])
        self.assertEqual(
            "verify-prerecord-timing",
            case_video["prerecording"]["steps"][-1]["step_id"],
        )
        self.assertEqual(case_video["steps"][-1]["interface"], "human_gate")
        self.assertEqual(
            case_video["prerecording"]["interview_steps"][-1]["tool_id"],
            "interview-guide-human-review",
        )
        self.assertEqual(
            AGENT._tool_descriptor("video-privacy-treatment", detailed=True)["discovery_mode"],
            "repository_internal",
        )
        self.assertEqual(
            AGENT._tool_descriptor("subject-privacy-treatment-gate", detailed=True)["execution_authority"],
            "human-only",
        )

    def test_research_output_requires_schema_and_answer_readiness(self) -> None:
        canonical = ROOT.parent / "question-research-poc" / "tests" / "fixtures" / "research-output-v1" / "canonical" / "research-output.v1.json"
        admitted = AGENT._validate_research_output_artifact(canonical)
        self.assertTrue(admitted["completeness"]["ready_for_answer"])
        blocked = copy.deepcopy(admitted)
        blocked["completeness"]["ready_for_answer"] = False
        blocked["guarded_final_answer"]["status"] = "blocked"
        blocked["guarded_final_answer"]["ready"] = False
        blocked["guarded_final_answer"]["answer"] = None
        root = ROOT / "outputs" / "test-temp" / ("blocked-research-" + uuid.uuid4().hex)
        root.mkdir(parents=True, exist_ok=True)
        try:
            path = root / "research-output.v1.json"
            path.write_text(json.dumps(blocked, ensure_ascii=False), encoding="utf-8")
            with self.assertRaises(AGENT.AgentEntryError) as caught:
                AGENT._validate_research_output_artifact(path)
            self.assertEqual(caught.exception.code, "research_output_missing_or_blocked")
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_final_timing_semantics_bind_exact_script_media_and_observation(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "timing_for_agent_integration_test", ROOT / "scripts" / "short_video_timing_evidence.py"
        )
        assert spec and spec.loader
        timing = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(timing)
        runtime = ROOT / "outputs" / "test-temp" / ("final-timing-" + uuid.uuid4().hex)
        runtime.mkdir(parents=True)
        try:
            value = AGENT.load_json(
                ROOT / "fixtures" / "short-video-timing-evidence-v1" / "synthetic-final-cut.input.json"
            )
            payoff = next(row for row in value["timeline"] if "main-payoff" in row["roles"])
            payoff.update(start_seconds=4, end_seconds=12)
            value.update(measured_duration_seconds=14, timeline=[value["timeline"][0], payoff])
            value["media_binding"]["duration_seconds"] = 14
            script_source = timing.resolve_owner_ref(value["script_binding"], "script_binding")
            media_source = timing.resolve_owner_ref(value["media_binding"], "media_binding")
            script_path = runtime / "script.json"
            media_path = runtime / "final-cut.bin"
            script_path.write_bytes(script_source.read_bytes())
            media_path.write_bytes(media_source.read_bytes())
            value["script_binding"] = {
                "owner": "self-media-creation-system",
                "path": script_path.relative_to(ROOT).as_posix(),
                "sha256": AGENT.sha256_file(script_path),
            }
            value["media_binding"].update(
                path=media_path.relative_to(ROOT).as_posix(), sha256=AGENT.sha256_file(media_path)
            )
            input_path = runtime / "timing-input.json"
            input_path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            evidence_path = runtime / "timing-evidence.json"
            evidence = timing.create_receipt(input_path)
            self.assertEqual(1, evidence["observed_metrics"]["information_advance_count"])
            evidence_path.write_text(
                json.dumps(evidence, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            manifest_path = runtime / "manifest.json"
            manifest = {
                "artifacts": [
                    {"source_role": "case-video-script", "path": script_path.name},
                    {"source_role": "video-candidate", "path": media_path.name},
                    {"source_role": "timing-input", "path": input_path.name},
                ]
            }
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            handoff_path = runtime / "handoff.json"
            handoff = {"context": {"manifest": {"path": manifest_path.name}}}
            receipt_path = runtime / "step-receipt.json"
            receipt = {"outputs": [{"path": evidence_path.name}]}
            AGENT._validate_final_cut_timing_output(handoff_path, receipt_path, handoff, receipt)

            release_manifest_path = runtime / "release-manifest.json"
            release_manifest = {
                "artifacts": [
                    {"source_role": "video-candidate", "path": media_path.name},
                    {"source_role": "timing-evidence", "path": evidence_path.name},
                ]
            }
            release_manifest_path.write_text(json.dumps(release_manifest), encoding="utf-8")
            AGENT._validate_release_timing_inputs(release_manifest_path)

            alternate = runtime / "different-final-cut.bin"
            alternate.write_bytes(b"different candidate")
            manifest["artifacts"][1]["path"] = alternate.name
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaises(AGENT.AgentEntryError) as caught:
                AGENT._validate_final_cut_timing_output(handoff_path, receipt_path, handoff, receipt)
            self.assertEqual("media_timing_revision_drift", caught.exception.code)
            release_manifest["artifacts"][0]["path"] = alternate.name
            release_manifest_path.write_text(json.dumps(release_manifest), encoding="utf-8")
            with self.assertRaises(AGENT.AgentEntryError) as release_error:
                AGENT._validate_release_timing_inputs(release_manifest_path)
            self.assertEqual("media_timing_revision_drift", release_error.exception.code)
        finally:
            shutil.rmtree(runtime, ignore_errors=True)

    def test_recipe_cli_rejects_shell_command_chaining(self) -> None:
        root = ROOT / "outputs" / "test-temp" / ("recipe-chain-" + uuid.uuid4().hex)
        root.mkdir(parents=True, exist_ok=True)
        original = AGENT.CATALOG_PATH
        try:
            catalog = AGENT.load_json(original)
            recipe = next(item for item in catalog["recipes"] if item["recipe_id"] == "moments-short-post")
            recipe["steps"][0]["command"] += "; python unexpected.py"
            candidate = root / "catalog.json"
            candidate.write_text(json.dumps(catalog), encoding="utf-8")
            AGENT.CATALOG_PATH = candidate
            with self.assertRaises(AGENT.AgentEntryError) as caught:
                AGENT.load_catalog()
            self.assertEqual(caught.exception.code, "boundary_drift")
        finally:
            AGENT.CATALOG_PATH = original
            shutil.rmtree(root, ignore_errors=True)

    def test_resume_never_automatically_retries(self) -> None:
        receipt = AGENT.resume_receipt({"error_code": "source_hash_drift"})
        self.assertEqual(receipt["status"], "human_action_required")
        self.assertFalse(receipt["automatic_retry"])
        with self.assertRaises(AGENT.AgentEntryError) as unknown:
            AGENT.resume_receipt({"error_code": "mystery_failure"})
        self.assertEqual(unknown.exception.code, "unknown_error_requires_human")

    def test_discovery_is_short_and_has_no_personal_absolute_path(self) -> None:
        text = AGENT.DISCOVERY_PATH.read_text(encoding="utf-8")
        self.assertLessEqual(len(text.splitlines()), 100)
        self.assertLessEqual(len(text.encode("utf-8")), 9216)
        self.assertNotIn("C:\\Users\\", text)
        self.assertNotIn("D:\\used-by-codex", text)

    def test_metadata_contains_no_secret_or_personal_path(self) -> None:
        paths = [
            AGENT.MANIFEST_PATH,
            AGENT.CATALOG_PATH,
            AGENT.REQUEST_SCHEMA_PATH,
            AGENT.CATALOG_SCHEMA_PATH,
            AGENT.CAPSULE_SCHEMA_PATH,
            AGENT.CAPSULE_V2_SCHEMA_PATH,
            AGENT.HANDOFF_SCHEMA_PATH,
            AGENT.OUTPUT_RECEIPT_SCHEMA_PATH,
            AGENT.SEQUENCE_STATUS_SCHEMA_PATH,
            AGENT.VIDEO_PRIVACY_DECISION_SCHEMA_PATH,
            AGENT.CUSTOMER_VIDEO_EFFECT_REVIEW_SCHEMA_PATH,
            AGENT.PREPUBLICATION_PRIVACY_GATE_SCHEMA_PATH,
            ROOT / "config" / "short-video-timing-profile.v1.json",
            ROOT / "schemas" / "short-video-timing-evidence-input.v1.schema.json",
            ROOT / "schemas" / "short-video-timing-evidence.v1.schema.json",
            ROOT / "fixtures" / "short-video-timing-evidence-v1" / "synthetic-prerecord.input.json",
            ROOT / "fixtures" / "short-video-timing-evidence-v1" / "synthetic-final-cut.input.json",
            *AGENT.RECIPE_FIXTURES.values(),
        ]
        forbidden = ("api_key", "access_token", "bearer ", "cookie=", "c:\\users\\", "d:\\used-by-codex")
        for path in paths:
            with self.subTest(path=path.name):
                lowered = path.read_text(encoding="utf-8").lower()
                for token in forbidden:
                    self.assertNotIn(token, lowered)

    def _handoff_run(self):
        root = ROOT / "outputs" / "test-temp" / ("step-handoff-" + uuid.uuid4().hex)
        root.mkdir(parents=True, exist_ok=True)
        request = AGENT.load_json(AGENT.RECIPE_FIXTURES["xhs-evidence-graphic"])
        capsule = AGENT.resolve_request(request)
        capsule_path = root / "capsule.json"
        AGENT.write_or_print(capsule, capsule_path)
        source = root / "inputs.json"
        source.write_text('{"synthetic":true,"claim":"fixture only"}', encoding="utf-8")
        digest = AGENT.sha256_file(source)
        manifest_path = root / "context-manifest.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "schema_version": "self-media-context-input.v1",
                    "task_id": request["request_id"],
                    "stage": "draft",
                    "budget": {"max_inline_bytes": 4096},
                    "artifacts": [
                        {
                            "artifact_id": "topic",
                            "role": "topic_question",
                            "source_role": "topic_question",
                            "path": source.name,
                            "load_mode": "inline",
                            "expected_sha256": digest,
                        },
                        {
                            "artifact_id": "audience",
                            "role": "primary_audience",
                            "source_role": "primary_audience",
                            "path": source.name,
                            "load_mode": "reference",
                            "expected_sha256": digest,
                        },
                        {
                            "artifact_id": "research",
                            "role": "research_output",
                            "source_role": "research_output_ref",
                            "path": source.name,
                            "load_mode": "reference",
                            "expected_sha256": digest,
                        },
                        {
                            "artifact_id": "framework-context",
                            "role": "source_manifest",
                            "source_role": "topic-angle-decision",
                            "path": source.name,
                            "load_mode": "reference",
                            "expected_sha256": digest,
                        },
                        {
                            "artifact_id": "author-context",
                            "role": "source_manifest",
                            "source_role": "author-writing-context",
                            "path": source.name,
                            "load_mode": "reference",
                            "expected_sha256": digest,
                        },
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        context_receipt = root / "context-receipt.json"
        handoff_path = root / "handoff.json"
        handoff = AGENT.prepare_step_handoff(
            capsule_path,
            "build-evidence-draft",
            manifest_path,
            context_receipt,
            handoff_path,
            inspection_only=True,
        )
        return root, source, handoff_path, handoff

    def test_step_handoff_materializes_tool_discovery_and_is_idempotent(self) -> None:
        root, _, handoff_path, first = self._handoff_run()
        try:
            self.assertEqual(first["status"], "inspection_only")
            self.assertEqual(first["tool_contract"]["registry_tool_id"], "content-creation-system")
            self.assertEqual(
                first["tool_contract"]["discovery_command"],
            "python ../tools/public_toolchain.py discover content-creation-system",
            )
            self.assertIn("--handoff", first["tool_contract"]["consumer_command"])
            self.assertIn("verified research claims", first["execution_brief"]["instruction"])
            second = AGENT.prepare_step_handoff(
                root / "capsule.json",
                "build-evidence-draft",
                root / "context-manifest.json",
                root / "context-receipt.json",
                handoff_path,
                inspection_only=True,
            )
            self.assertEqual(AGENT.canonical_bytes(first), AGENT.canonical_bytes(second))
            self.assertEqual(AGENT.validate_step_handoff(handoff_path, allow_inspection=True)["handoff_id"], first["handoff_id"])
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_generic_owner_receipt_proves_transport_not_semantic_completion(self) -> None:
        root = ROOT / "outputs" / "test-temp" / ("transport-only-" + uuid.uuid4().hex)
        root.mkdir(parents=True, exist_ok=True)
        try:
            request = AGENT.load_json(AGENT.RECIPE_FIXTURES["xhs-evidence-graphic"])
            capsule = AGENT.resolve_request(request)
            capsule_path = root / "capsule.json"
            AGENT.write_or_print(capsule, capsule_path)
            source = root / "routing-binding.json"
            source.write_text((ROOT / "routing-binding.v1.json").read_text(encoding="utf-8"), encoding="utf-8")
            manifest_path = root / "context-manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "schema_version": "self-media-context-input.v1",
                        "task_id": request["request_id"],
                        "stage": "research",
                        "budget": {"max_inline_bytes": 4096},
                        "artifacts": [
                            {
                                "artifact_id": "routing-binding",
                                "role": "source_manifest",
                                "source_role": "routing-binding",
                                "path": source.name,
                                "load_mode": "reference",
                                "expected_sha256": AGENT.sha256_file(source),
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            handoff_path = root / "handoff.json"
            handoff = AGENT.prepare_step_handoff(
                capsule_path,
                "verify-canonical-route",
                manifest_path,
                root / "context-receipt.json",
                handoff_path,
            )
            artifact = root / "candidate.json"
            artifact.write_text('{"ok":true}', encoding="utf-8")
            receipt = {
                "schema_version": "self-media-step-output-receipt.v1",
                "status": "candidate_ready",
                "handoff": {"path": handoff_path.name, "sha256": AGENT.sha256_file(handoff_path)},
                "step_id": handoff["step"]["step_id"],
                "tool_id": handoff["step"]["tool_id"],
                "output_contract": handoff["step"]["output_contract"],
                "outputs": [{"path": artifact.name, "sha256": AGENT.sha256_file(artifact)}],
                "boundaries": copy.deepcopy(handoff["boundaries"]),
            }
            receipt["payload_sha256"] = AGENT.sha256_value(receipt)
            receipt_path = root / "output-receipt.json"
            AGENT.write_or_print(receipt, receipt_path)
            result = AGENT.verify_step_output(handoff_path, receipt_path)
            self.assertTrue(result["ok"])
            self.assertFalse(result["workflow_step_completed"])
            self.assertEqual(result["validation_scope"], "transport_and_sequence_only")
            self.assertEqual(result["completion_claim"], "handoff-validated-owner-semantics-unverified")
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_all_five_workflows_materialize_every_step_with_tool_and_context_receipts(self) -> None:
        for recipe_id, fixture_path in AGENT.RECIPE_FIXTURES.items():
            root = ROOT / "outputs" / "test-temp" / ("all-step-handoff-" + uuid.uuid4().hex)
            root.mkdir(parents=True, exist_ok=True)
            try:
                request = AGENT.load_json(fixture_path)
                capsule = AGENT.resolve_request(request)
                capsule_path = root / "capsule.json"
                AGENT.write_or_print(capsule, capsule_path)
                for step in capsule["step_index"]:
                    step_root = root / step["step_id"]
                    step_root.mkdir()
                    step_capsule_path = step_root / "capsule.json"
                    AGENT.write_or_print(capsule, step_capsule_path)
                    artifacts = []
                    for index, source_role in enumerate(step["input_roles"]):
                        source = step_root / f"input-{index}.json"
                        source.write_text(
                            json.dumps({"synthetic_only": True, "source_role": source_role}),
                            encoding="utf-8",
                        )
                        artifacts.append(
                            {
                                "artifact_id": f"input-{index}",
                                "role": "source_manifest",
                                "source_role": source_role,
                                "path": source.name,
                                "load_mode": "reference",
                                "expected_sha256": AGENT.sha256_file(source),
                            }
                        )
                    manifest_path = step_root / "context-manifest.json"
                    manifest_path.write_text(
                        json.dumps(
                            {
                                "schema_version": "self-media-context-input.v1",
                                "task_id": request["request_id"],
                                "stage": step["context_stage"],
                                "budget": {"max_inline_bytes": 4096},
                                "artifacts": artifacts,
                            }
                        ),
                        encoding="utf-8",
                    )
                    handoff_path = step_root / "handoff.json"
                    handoff = AGENT.prepare_step_handoff(
                        step_capsule_path,
                        step["step_id"],
                        manifest_path,
                        step_root / "context-receipt.json",
                        handoff_path,
                        inspection_only=True,
                    )
                    self.assertEqual(
                        AGENT.validate_step_handoff(handoff_path, allow_inspection=True)["handoff_id"],
                        handoff["handoff_id"],
                    )
                    self.assertIn("discovery_mode", handoff["tool_contract"])
                    candidate = step_root / "candidate.json"
                    candidate.write_text('{"synthetic_only":true}', encoding="utf-8")
                    receipt = {
                        "schema_version": "self-media-step-output-receipt.v1",
                        "status": "human_gate_recorded" if step["interface"] == "human_gate" else "candidate_ready",
                        "handoff": {"path": handoff_path.name, "sha256": AGENT.sha256_file(handoff_path)},
                        "step_id": step["step_id"],
                        "tool_id": step["tool_id"],
                        "output_contract": step["output_contract"],
                        "outputs": [{"path": candidate.name, "sha256": AGENT.sha256_file(candidate)}],
                        "boundaries": copy.deepcopy(capsule["boundaries"]),
                    }
                    receipt["payload_sha256"] = AGENT.sha256_value(receipt)
                    receipt_path = step_root / "output-receipt.json"
                    AGENT.write_or_print(receipt, receipt_path)
                    with self.assertRaises(AGENT.AgentEntryError) as caught:
                        AGENT.verify_step_output(handoff_path, receipt_path)
                    self.assertEqual("inspection_not_execution", caught.exception.code)
            finally:
                shutil.rmtree(root, ignore_errors=True)

    def test_step_handoff_fails_on_missing_role_and_later_artifact_drift(self) -> None:
        root, source, handoff_path, _ = self._handoff_run()
        try:
            source.write_text("drift", encoding="utf-8")
            with self.assertRaises(AGENT.AgentEntryError) as drift:
                AGENT.validate_step_handoff(handoff_path, allow_inspection=True)
            self.assertEqual(drift.exception.code, "context_receipt_drift")

            manifest = AGENT.load_json(root / "context-manifest.json")
            manifest["artifacts"] = manifest["artifacts"][:-1]
            (root / "context-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaises(AGENT.AgentEntryError) as missing:
                AGENT.prepare_step_handoff(
                    root / "capsule.json",
                    "build-evidence-draft",
                    root / "context-manifest.json",
                    root / "new-context-receipt.json",
                    root / "new-handoff.json",
                )
            self.assertEqual(missing.exception.code, "context_roles_missing")
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_output_receipt_must_bind_handoff_and_manual_boundaries(self) -> None:
        root, _, handoff_path, handoff = self._handoff_run()
        try:
            artifact = root / "candidate.json"
            artifact.write_text('{"status":"draft_only"}', encoding="utf-8")
            receipt = {
                "schema_version": "self-media-step-output-receipt.v1",
                "status": "candidate_ready",
                "handoff": {"path": handoff_path.name, "sha256": AGENT.sha256_file(handoff_path)},
                "step_id": handoff["step"]["step_id"],
                "tool_id": handoff["step"]["tool_id"],
                "output_contract": handoff["step"]["output_contract"],
                "outputs": [{"path": artifact.name, "sha256": AGENT.sha256_file(artifact)}],
                "boundaries": copy.deepcopy(handoff["boundaries"]),
            }
            receipt["payload_sha256"] = AGENT.sha256_value(receipt)
            receipt_path = root / "output-receipt.json"
            AGENT.write_or_print(receipt, receipt_path)
            with self.assertRaises(AGENT.AgentEntryError) as caught:
                AGENT.verify_step_output(handoff_path, receipt_path)
            self.assertEqual("inspection_not_execution", caught.exception.code)
            receipt["boundaries"]["publication"] = "automatic"
            receipt["payload_sha256"] = AGENT.sha256_value({k: v for k, v in receipt.items() if k != "payload_sha256"})
            AGENT.write_or_print(receipt, receipt_path)
            with self.assertRaises(AGENT.AgentEntryError):
                AGENT.verify_step_output(handoff_path, receipt_path)
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_cli_doctor_capabilities_and_example(self) -> None:
        commands = (
            [sys.executable, "-B", str(SCRIPT), "doctor"],
            [sys.executable, "-B", str(SCRIPT), "capabilities"],
            [sys.executable, "-B", str(SCRIPT), "authoring"],
            [sys.executable, "-B", str(SCRIPT), "run-example", "--recipe", "context-efficient-rework"],
        )
        for command in commands:
            with self.subTest(command=command[-1]):
                completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding='utf-8', check=False)
                self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)
                self.assertIsInstance(json.loads(completed.stdout), dict)


if __name__ == "__main__":
    unittest.main()
