from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "case_governance_contracts.py"
SPEC = importlib.util.spec_from_file_location("case_governance_contracts", SCRIPT)
assert SPEC and SPEC.loader
GOVERNANCE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GOVERNANCE)


class CaseGovernanceContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = ROOT / ".test-runtime-case-governance" / self._testMethodName
        if self.root.exists():
            shutil.rmtree(self.root)
        self.root.mkdir(parents=True)
        for name, value in {
            "evidence.txt": b"synthetic evidence",
            "source.wav": b"synthetic audio",
            "raw.mp4": b"synthetic raw media",
            "rejected.mp4": b"synthetic rejected media",
            "final.mp4": b"synthetic final media",
            "cover-3x4.png": b"synthetic cover 3x4",
            "cover-9x16.png": b"synthetic cover 9x16",
        }.items():
            (self.root / name).write_bytes(value)

    def tearDown(self) -> None:
        if self.root.exists():
            shutil.rmtree(self.root)

    def artifact(self, name: str) -> dict[str, str]:
        value = (self.root / name).read_bytes()
        return {"path": name, "expected_sha256": hashlib.sha256(value).hexdigest()}

    def write_json(self, name: str, value: dict) -> dict[str, str]:
        (self.root / name).write_text(
            json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        return self.artifact(name)

    def evidence(self) -> dict[str, str]:
        return {**self.artifact("evidence.txt"), "evidence_kind": "claim_notice"}

    def financial(self) -> dict:
        return {
            "schema_version": "self-media-case-financial-facts.v1",
            "ledger_id": "ledger-001",
            "case_ref": "case-001",
            "updated_at": "2026-08-26T23:20:00+08:00",
            "verification_owner": "human-reviewer",
            "facts": [
                {
                    "fact_id": "claim-001",
                    "stage": "first-stage",
                    "scope": "insurance_claim",
                    "amount_role": "reimbursement",
                    "currency": "CNY",
                    "exact_amount": 78744.51,
                    "evidence_status": "document_and_user_verified",
                    "source_refs": [self.evidence()],
                    "related_fact_refs": [],
                    "public_wording": {
                        "text": "七万八千多",
                        "precision": "approximate",
                        "lower_bound": 78000,
                        "upper_bound_exclusive": 79000
                    }
                }
            ]
        }

    def localized(self) -> dict:
        return {
            "schema_version": "self-media-localized-subtitle-review.v1",
            "receipt_id": "subtitle-review-001",
            "reviewed_at": "2026-08-26T23:20:00+08:00",
            "reviewer": "human-reviewer",
            "source_media": self.artifact("source.wav"),
            "source_language": "yue-Hans",
            "source_dialect": "Cantonese",
            "display_language": "zh-Hans",
            "timing_authority": "source_audio_utterance_boundaries",
            "display_timing_policy": "inherit_source_utterance",
            "machine_translation_is_timing_authority": False,
            "segments": [
                {
                    "segment_id": "seg-001",
                    "speaker_ref": "customer-001",
                    "start_seconds": 1.0,
                    "end_seconds": 2.5,
                    "source_text": "粤语原文",
                    "display_text": "普通话译文",
                    "review_status": "human_confirmed",
                    "high_risk_tags": ["insurance", "amount"]
                },
                {
                    "segment_id": "seg-002",
                    "speaker_ref": "customer-001",
                    "start_seconds": 2.5,
                    "end_seconds": 4.0,
                    "source_text": "第二句粤语",
                    "display_text": "第二句普通话",
                    "review_status": "human_confirmed",
                    "high_risk_tags": ["none"]
                }
            ],
            "status": "human_confirmed"
        }

    def lifecycle(self) -> dict:
        return {
            "schema_version": "self-media-artifact-lifecycle-manifest.v1",
            "manifest_id": "lifecycle-001",
            "updated_at": "2026-08-26T23:20:00+08:00",
            "workspace_ref": "synthetic-workspace",
            "artifacts": [
                {
                    "artifact_id": "raw-001",
                    **self.artifact("raw.mp4"),
                    "status": "raw_source",
                    "locked": True,
                    "customer_sensitive": True,
                    "parent_sha256s": [],
                    "superseded_by": None
                },
                {
                    "artifact_id": "rejected-001",
                    **self.artifact("rejected.mp4"),
                    "status": "rejected",
                    "locked": False,
                    "customer_sensitive": False,
                    "parent_sha256s": [],
                    "superseded_by": None
                }
            ],
            "deletion_request": None
        }

    def publication(self) -> dict:
        common_rules = {
            "source_status": "user_confirmed_current_authenticated_ui",
            "checked_at": "2026-08-26T23:20:00+08:00",
            "title_max_characters": 20,
            "short_title_max_characters": 16,
            "collection_name_max_characters": 10,
            "collection_description_max_characters": 100,
            "required_cover_ratios": ["3:4", "9:16"],
            "minimum_cover_candidates": 2,
            "maximum_cover_candidates": 10,
            "collection_cover_required": False,
            "required_collection_cover_ratios": [],
            "minimum_schedule_lead_minutes": 120,
            "maximum_schedule_lead_minutes": 20160,
            "schedule_change_policy": "unknown_must_recheck",
            "schedule_change_route": None,
            "schedule_restricted_submission_types": [],
            "collection_creation_during_publish_supported": False,
            "attach_during_publish_requires_existing_collection": True,
            "post_publish_add_to_collection_supported": True,
            "temporary_title_field_tag_recognition": True,
            "final_title_restore_required": True
        }
        return {
            "schema_version": "self-media-platform-publication-package.v1",
            "package_id": "publication-001",
            "content_item_ref": "content-001",
            "created_at": "2026-08-26T20:00:00+08:00",
            "video": self.artifact("final.mp4"),
            "automatic_publish": False,
            "publication_mode": "manual_only",
            "platforms": [
                {
                    "platform_id": "xiaohongshu",
                    "enabled": True,
                    "title": "一个合规短标题",
                    "short_title": "短标题",
                    "description": "自然表达的合成简介。",
                    "tags": ["保险服务", "就医协助"],
                    "collection_name": "真实案例",
                    "collection_description": "去标识化的真实服务案例。",
                    "collection_cover": None,
                    "scheduled_at": "2026-08-26T22:30:00+08:00",
                    "covers": [
                        {"ratio": "3:4", "artifact": self.artifact("cover-3x4.png")},
                        {"ratio": "9:16", "artifact": self.artifact("cover-9x16.png")}
                    ],
                    "rules": common_rules,
                    "human_preview_status": "passed",
                    "copy_human_review_status": "passed"
                }
            ]
        }

    def publication_v2(self, phase: str = "release_candidate") -> dict:
        document = self.publication()
        document["schema_version"] = "self-media-platform-publication-package.v2"
        document["package_phase"] = phase
        video = document["video"]
        privacy_gate = {
            "schema_version": "self-media-prepublication-privacy-gate.v1",
            "gate_id": "privacy-gate-synthetic-001",
            "evaluated_at": "2026-08-26T23:20:00+08:00",
            "decision_sha256": "1" * 64,
            "review_sha256": "2" * 64,
            "candidate": {
                **video,
                "duration_seconds": 12.5,
            },
            "status": "customer_confirmed_candidate",
            "manual_publication_eligible": True,
            "automatic_publish": False,
            "customer_contact_performed_by_system": False,
            "reuse_local_recipes": True,
            "stop_reasons": [],
            "rework_request": None,
        }
        document["privacy_gate"] = self.write_json("privacy-gate.json", privacy_gate)
        for platform in document["platforms"]:
            platform["correction_route"] = {
                "source_status": "user_confirmed_current_authenticated_ui",
                "checked_at": "2026-08-26T23:20:00+08:00",
                "scope": "current_account_and_item",
                "source_replacement_support": "supported",
                "on_source_error": "replace_source",
                "preserve_metrics_before_action": True,
                "replacement_requires_re_review": True,
                "deletion_irreversible": None,
            }
            platform["post_upload_plan"] = {
                "status": "ready",
                "checks": [
                    "playback",
                    "audio",
                    "subtitles",
                    "cover",
                    "privacy",
                    "metadata",
                ],
                "failure_route": "use_platform_correction_route",
                "record_via": "content_operations_cycle.record-publication",
            }
            platform["post_upload_result"] = None
        scope = GOVERNANCE.publication_release_scope(document)
        document["release_scope_sha256"] = scope
        reviews = {}
        for review_kind in (
            "customer_final_cut",
            "institution_final_publication",
            "account_operator",
        ):
            reviewer = f"{review_kind}-reviewer"
            reviewed_at = "2026-08-26T23:25:00+08:00"
            credential = {
                "schema_version": "self-media-publication-release-credential.v1",
                "approval_kind": review_kind,
                "reviewer": reviewer,
                "reviewed_at": reviewed_at,
                "decision": "approved",
                "release_scope_sha256": scope,
                "authority": {
                    "automatic_publish": False,
                    "execution_authorized": False,
                    "external_send_authorized": False,
                },
            }
            credential_artifact = self.write_json(
                f"{review_kind}.credential.json", credential
            )
            reviews[review_kind] = {
                "status": "approved",
                "credential": {
                    "credential_ref": credential_artifact["path"],
                    "credential_sha256": credential_artifact["expected_sha256"],
                    "reviewer": reviewer,
                    "reviewed_at": reviewed_at,
                },
                "reason": None,
            }
        document["release_reviews"] = reviews
        if phase == "post_upload_checked":
            document["platforms"][0]["post_upload_result"] = {
                "checked_at": "2026-08-27T00:10:00+08:00",
                "checker": "human-operator",
                "published_item_ref": "synthetic-platform-item-001",
                "manual_upload_confirmed": True,
                "checks": {
                    "playback": "passed",
                    "audio": "passed",
                    "subtitles": "passed",
                    "cover": "passed",
                    "privacy": "passed",
                    "metadata": "passed",
                },
                "correction_required": False,
                "failure_route_used": "none",
                "automatic_action_performed": False,
            }
        return document

    def rewrite_release_credential(
        self, document: dict, review_kind: str, mutate
    ) -> None:
        reference = document["release_reviews"][review_kind]["credential"]
        path = self.root / reference["credential_ref"]
        value = json.loads(path.read_text(encoding="utf-8"))
        mutate(value)
        path.write_text(
            json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        reference["credential_sha256"] = self.artifact(path.name)["expected_sha256"]

    def rescope_release_credentials(self, document: dict) -> None:
        scope = GOVERNANCE.publication_release_scope(document)
        document["release_scope_sha256"] = scope
        for review_kind in (
            "customer_final_cut",
            "institution_final_publication",
            "account_operator",
        ):
            self.rewrite_release_credential(
                document,
                review_kind,
                lambda value, release_scope=scope: value.update(
                    {"release_scope_sha256": release_scope}
                ),
            )

    def test_financial_roles_and_public_wording_pass(self) -> None:
        receipt = GOVERNANCE.validate_financial(self.financial(), self.root)
        self.assertEqual(receipt["amount_roles"], ["reimbursement"])

    def test_financial_scope_mismatch_fails_closed(self) -> None:
        document = self.financial()
        document["facts"][0]["scope"] = "cashflow"
        with self.assertRaises(GOVERNANCE.CaseGovernanceError) as error:
            GOVERNANCE.validate_financial(document, self.root)
        self.assertEqual(error.exception.code, "amount_role_scope_mismatch")

    def test_financial_public_wording_must_contain_exact_amount(self) -> None:
        document = self.financial()
        document["facts"][0]["public_wording"]["upper_bound_exclusive"] = 78001
        with self.assertRaises(GOVERNANCE.CaseGovernanceError) as error:
            GOVERNANCE.validate_financial(document, self.root)
        self.assertEqual(error.exception.code, "public_amount_range_mismatch")

    def test_localized_translation_inherits_source_timing(self) -> None:
        receipt = GOVERNANCE.validate_localized_subtitles(self.localized(), self.root)
        self.assertEqual(receipt["timing_authority"], "source_audio_utterance_boundaries")

    def test_localized_overlap_fails_closed(self) -> None:
        document = self.localized()
        document["segments"][1]["start_seconds"] = 2.0
        with self.assertRaises(GOVERNANCE.CaseGovernanceError) as error:
            GOVERNANCE.validate_localized_subtitles(document, self.root)
        self.assertEqual(error.exception.code, "subtitle_segments_overlap")

    def test_lifecycle_without_delete_request_passes(self) -> None:
        receipt = GOVERNANCE.validate_lifecycle(self.lifecycle(), self.root)
        self.assertIsNone(receipt["deletion_plan"])

    def test_lifecycle_protected_source_cannot_be_deleted(self) -> None:
        document = self.lifecycle()
        document["deletion_request"] = {
            "request_id": "delete-001",
            "requested_at": "2026-08-26T23:20:00+08:00",
            "mode": "quarantine_only",
            "target_artifact_ids": ["raw-001"],
            "user_approved": True,
            "approver": "user",
            "approved_at": "2026-08-26T23:21:00+08:00"
        }
        with self.assertRaises(GOVERNANCE.CaseGovernanceError) as error:
            GOVERNANCE.validate_lifecycle(document, self.root)
        self.assertEqual(error.exception.code, "deletion_target_locked")

    def test_lifecycle_rejected_artifact_returns_quarantine_plan_only(self) -> None:
        document = self.lifecycle()
        document["deletion_request"] = {
            "request_id": "delete-002",
            "requested_at": "2026-08-26T23:20:00+08:00",
            "mode": "quarantine_only",
            "target_artifact_ids": ["rejected-001"],
            "user_approved": True,
            "approver": "user",
            "approved_at": "2026-08-26T23:21:00+08:00"
        }
        receipt = GOVERNANCE.validate_lifecycle(document, self.root)
        self.assertFalse(receipt["deletion_plan"]["filesystem_mutation_performed"])

    def test_publication_package_passes_without_publishing(self) -> None:
        receipt = GOVERNANCE.validate_publication(self.publication(), self.root)
        self.assertEqual(receipt["publication_mode"], "manual_only")
        self.assertFalse(receipt["automatic_publish"])

    def test_publication_title_limit_fails_closed(self) -> None:
        document = self.publication()
        document["platforms"][0]["title"] = "这是一条明显超过当前平台声明限制的很长很长很长标题"
        with self.assertRaises(GOVERNANCE.CaseGovernanceError) as error:
            GOVERNANCE.validate_publication(document, self.root)
        self.assertEqual(error.exception.code, "platform_title_limit_failed")

    def test_publication_pending_copy_review_fails_closed(self) -> None:
        document = self.publication()
        document["platforms"][0]["copy_human_review_status"] = "pending"
        with self.assertRaises(GOVERNANCE.CaseGovernanceError) as error:
            GOVERNANCE.validate_publication(document, self.root)
        self.assertEqual(error.exception.code, "platform_copy_review_pending")

    def test_publication_cover_candidate_maximum_fails_closed(self) -> None:
        document = self.publication()
        document["platforms"][0]["rules"]["maximum_cover_candidates"] = 1
        with self.assertRaises(GOVERNANCE.CaseGovernanceError) as error:
            GOVERNANCE.validate_publication(document, self.root)
        self.assertEqual(error.exception.code, "platform_cover_candidates_exceeded")

    def test_publication_required_collection_cover_fails_closed(self) -> None:
        document = self.publication()
        document["platforms"][0]["rules"]["collection_cover_required"] = True
        document["platforms"][0]["rules"]["required_collection_cover_ratios"] = ["3:4"]
        with self.assertRaises(GOVERNANCE.CaseGovernanceError) as error:
            GOVERNANCE.validate_publication(document, self.root)
        self.assertEqual(error.exception.code, "platform_collection_cover_missing")

    def test_publication_schedule_horizon_fails_closed(self) -> None:
        document = self.publication()
        document["platforms"][0]["rules"]["maximum_schedule_lead_minutes"] = 120
        with self.assertRaises(GOVERNANCE.CaseGovernanceError) as error:
            GOVERNANCE.validate_publication(document, self.root)
        self.assertEqual(error.exception.code, "platform_schedule_horizon_failed")

    def test_publication_temporary_tag_workflow_requires_title_restore(self) -> None:
        document = self.publication()
        document["platforms"][0]["rules"]["final_title_restore_required"] = False
        with self.assertRaises(GOVERNANCE.CaseGovernanceError) as error:
            GOVERNANCE.validate_publication(document, self.root)
        self.assertEqual(error.exception.code, "platform_final_title_restore_missing")

    def test_publication_collection_route_requires_existing_collection_gate(self) -> None:
        document = self.publication()
        document["platforms"][0]["rules"]["attach_during_publish_requires_existing_collection"] = False
        with self.assertRaises(GOVERNANCE.CaseGovernanceError) as error:
            GOVERNANCE.validate_publication(document, self.root)
        self.assertEqual(error.exception.code, "platform_existing_collection_gate_missing")

    def test_publication_release_v2_passes_without_publishing(self) -> None:
        receipt = GOVERNANCE.validate_publication_release(
            self.publication_v2(), self.root
        )
        self.assertTrue(receipt["manual_publication_eligible"])
        self.assertFalse(receipt["automatic_publish"])
        self.assertEqual(receipt["package_phase"], "release_candidate")

    def test_publication_release_v2_privacy_gate_must_match_exact_video(self) -> None:
        document = self.publication_v2()
        gate_path = self.root / document["privacy_gate"]["path"]
        gate = json.loads(gate_path.read_text(encoding="utf-8"))
        gate["candidate"].update(self.artifact("raw.mp4"))
        document["privacy_gate"] = self.write_json("privacy-gate.json", gate)
        document["release_scope_sha256"] = GOVERNANCE.publication_release_scope(document)
        with self.assertRaises(GOVERNANCE.CaseGovernanceError) as error:
            GOVERNANCE.validate_publication_release(document, self.root)
        self.assertEqual(error.exception.code, "privacy_gate_candidate_drift")

    def test_publication_release_v2_privacy_gate_hash_drift_fails_closed(self) -> None:
        document = self.publication_v2()
        gate_path = self.root / document["privacy_gate"]["path"]
        gate_path.write_text(
            gate_path.read_text(encoding="utf-8") + "\n",
            encoding="utf-8",
            newline="\n",
        )
        with self.assertRaises(GOVERNANCE.CaseGovernanceError) as error:
            GOVERNANCE.validate_publication_release(document, self.root)
        self.assertEqual(error.exception.code, "source_hash_drift")

    def test_publication_release_v2_copy_change_invalidates_scope(self) -> None:
        document = self.publication_v2()
        document["platforms"][0]["title"] = "另一个短标题"
        with self.assertRaises(GOVERNANCE.CaseGovernanceError) as error:
            GOVERNANCE.validate_publication_release(document, self.root)
        self.assertEqual(error.exception.code, "publication_release_scope_drift")

    def test_publication_release_v2_pending_approval_fails_closed(self) -> None:
        document = self.publication_v2()
        document["release_reviews"]["institution_final_publication"] = {
            "status": "pending",
            "credential": None,
            "reason": "institutional final review has not been recorded",
        }
        with self.assertRaises(GOVERNANCE.CaseGovernanceError) as error:
            GOVERNANCE.validate_publication_release(document, self.root)
        self.assertEqual(error.exception.code, "publication_approval_pending")

    def test_publication_release_v2_credential_scope_drift_fails_closed(self) -> None:
        document = self.publication_v2()
        self.rewrite_release_credential(
            document,
            "customer_final_cut",
            lambda value: value.update({"release_scope_sha256": "0" * 64}),
        )
        with self.assertRaises(GOVERNANCE.CaseGovernanceError) as error:
            GOVERNANCE.validate_publication_release(document, self.root)
        self.assertEqual(error.exception.code, "publication_approval_scope_drift")

    def test_publication_release_v2_credential_cannot_escalate_authority(self) -> None:
        document = self.publication_v2()

        def escalate(value: dict) -> None:
            value["authority"]["execution_authorized"] = True

        self.rewrite_release_credential(document, "account_operator", escalate)
        with self.assertRaises(GOVERNANCE.CaseGovernanceError) as error:
            GOVERNANCE.validate_publication_release(document, self.root)
        self.assertEqual(error.exception.code, "authority_escalation")

    def test_publication_release_v2_unknown_correction_route_fails_closed(self) -> None:
        document = self.publication_v2()
        document["platforms"][0]["correction_route"][
            "source_replacement_support"
        ] = "unknown"
        self.rescope_release_credentials(document)
        with self.assertRaises(GOVERNANCE.CaseGovernanceError) as error:
            GOVERNANCE.validate_publication_release(document, self.root)
        self.assertEqual(
            error.exception.code, "platform_correction_capability_unverified"
        )

    def test_publication_release_v2_correction_route_must_match_capability(self) -> None:
        document = self.publication_v2()
        document["platforms"][0]["correction_route"]["on_source_error"] = (
            "delete_and_repost"
        )
        self.rescope_release_credentials(document)
        with self.assertRaises(GOVERNANCE.CaseGovernanceError) as error:
            GOVERNANCE.validate_publication_release(document, self.root)
        self.assertEqual(error.exception.code, "platform_correction_route_mismatch")

    def test_publication_release_v2_delete_repost_preserves_metrics(self) -> None:
        document = self.publication_v2()
        route = document["platforms"][0]["correction_route"]
        route["source_replacement_support"] = "unsupported"
        route["on_source_error"] = "delete_and_repost"
        route["preserve_metrics_before_action"] = False
        self.rescope_release_credentials(document)
        with self.assertRaises(GOVERNANCE.CaseGovernanceError) as error:
            GOVERNANCE.validate_publication_release(document, self.root)
        self.assertEqual(
            error.exception.code, "platform_metrics_preservation_missing"
        )

    def test_publication_release_v2_post_upload_plan_must_be_complete(self) -> None:
        document = self.publication_v2()
        document["platforms"][0]["post_upload_plan"]["checks"].remove("privacy")
        self.rescope_release_credentials(document)
        with self.assertRaises(GOVERNANCE.CaseGovernanceError) as error:
            GOVERNANCE.validate_publication_release(document, self.root)
        self.assertEqual(
            error.exception.code, "post_upload_verification_plan_incomplete"
        )

    def test_publication_post_upload_v2_passes_after_manual_checks(self) -> None:
        receipt = GOVERNANCE.validate_publication_post_upload(
            self.publication_v2("post_upload_checked"), self.root
        )
        self.assertEqual(receipt["status"], "passed")
        self.assertFalse(receipt["automatic_action_performed"])

    def test_publication_post_upload_v2_requires_each_enabled_result(self) -> None:
        document = self.publication_v2("post_upload_checked")
        document["platforms"][0]["post_upload_result"] = None
        with self.assertRaises(GOVERNANCE.CaseGovernanceError) as error:
            GOVERNANCE.validate_publication_post_upload(document, self.root)
        self.assertEqual(error.exception.code, "post_upload_result_missing")

    def test_publication_post_upload_v2_failed_check_routes_to_correction(self) -> None:
        document = self.publication_v2("post_upload_checked")
        result = document["platforms"][0]["post_upload_result"]
        result["checks"]["privacy"] = "failed"
        result["correction_required"] = True
        result["failure_route_used"] = "replace_source"
        receipt = GOVERNANCE.validate_publication_post_upload(document, self.root)
        self.assertEqual(receipt["status"], "rework_required")
        self.assertEqual(receipt["rework_platforms"], ["xiaohongshu"])

    def test_case_video_route_keeps_all_governance_gates(self) -> None:
        from canonical_routing import load_contracts
        quality = load_contracts()["components"]["quality_gates"]
        recipes = json.loads(
            (ROOT / "recipes" / "self-media-recipes.v1.json").read_text(encoding="utf-8")
        )
        hard = quality["hard_gates"]
        self.assertIn(
            "amount-semantic-role-separated-and-evidence-bound", hard["fact"]
        )
        self.assertIn(
            "cross-language-review-receipt-hash-bound", hard["audio_subtitle"]
        )
        self.assertIn(
            "artifact-lifecycle-delete-guard", hard["technical_integrity"]
        )
        self.assertIn(
            "final-layout-all-critical-layers-rounded-corner-and-collision-check",
            hard["visual_usability"],
        )
        self.assertIn(
            "platform-package-current-rules-and-human-copy-review-bound",
            hard["publication"],
        )
        case_recipe = next(
            row for row in recipes["recipes"] if row["recipe_id"] == "case-video-candidate"
        )
        step_ids = {step["step_id"] for step in case_recipe["steps"]}
        self.assertTrue(
            {
                "verify-production-run-lock",
                "capture-initial-privacy-treatment",
                "project-case-script",
                "handoff-video-owner",
                "final-timing",
                "verify-privacy-redaction-binding",
                "confirm-manual-publication-or-rework",
            }.issubset(step_ids)
        )
        final = next(
            step
            for step in case_recipe["steps"]
            if step["step_id"] == "confirm-manual-publication-or-rework"
        )
        self.assertIn("lifecycle lock receipt", final["instruction"])
        handoff = next(
            step for step in case_recipe["steps"] if step["step_id"] == "handoff-video-owner"
        )
        self.assertIn("lifecycle preflight", handoff["instruction"])
        timing = next(
            step for step in case_recipe["steps"] if step["step_id"] == "final-timing"
        )
        self.assertIn("timed transcript", timing["instruction"])
        self.assertEqual("short-video-timing-evidence.v1", timing["output_contract"])
        self.assertIn("timing-evidence", final["input_roles"])
        for gate in {
            "case-governance-contracts",
            "final-layout-safety",
            "platform-publication-package",
        }:
            self.assertIn(gate, case_recipe["quality_gates"])


if __name__ == "__main__":
    unittest.main()
