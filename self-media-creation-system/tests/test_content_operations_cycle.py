from __future__ import annotations

import copy
import importlib.util
import json
import os
import shutil
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "content_operations_cycle.py"
SPEC = importlib.util.spec_from_file_location("content_operations_cycle", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
cycle = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cycle)


class ContentOperationsCycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = (
            ROOT / "tests" / ".runtime" / "content-operations" / "unit" /
            f"{os.getpid()}-{self._testMethodName}"
        )
        if self.root.exists():
            cycle.safe_rmtree(self.root)
        self.root.mkdir(parents=True)
        self.store = self.root / "store"

    def tearDown(self) -> None:
        if self.root.exists():
            cycle.safe_rmtree(self.root)

    def fixture(self, name: str) -> Path:
        return ROOT / "fixtures" / "content-operations-cycle-v1" / name

    def input_copy(self, name: str, mutate=None) -> Path:
        value = json.loads(self.fixture(name).read_text(encoding="utf-8"))
        if mutate is not None:
            mutate(value)
        path = self.root / name
        cycle.write_json(path, value)
        return path

    def record_publication(self) -> dict:
        return cycle.record_from_input(
            self.store, "record-publication", self.fixture("record-publication.input.json")
        )

    def record_business_interaction(self) -> dict:
        return cycle.record_from_input(
            self.store,
            "record-interaction",
            self.fixture("record-interaction-business.input.json"),
        )

    def current_review_input(self, *, name: str = "build-review.input.json", mutate=None) -> Path:
        value = json.loads(self.fixture(name).read_text(encoding="utf-8"))
        value["source_checkpoint"] = cycle.source_checkpoint(cycle.read_journal(self.store))
        if mutate is not None:
            mutate(value)
        path = self.root / f"current-{name}"
        cycle.write_json(path, value)
        return path

    def make_deidentified(self, value: dict) -> None:
        value["data_classification"] = "deidentified-operational"
        operation_type = {
            "content-operations-cycle.publication-input.v1": "record-publication",
            "content-operations-cycle.interaction-input.v1": "record-interaction",
        }[value["schema_version"]]
        scope_sha256 = cycle.canonical_hash(value)
        credential = {
            "schema_version": "content-operations-cycle.privacy-review-credential.v1",
            "reviewer_ref": "human-privacy-reviewer",
            "reviewed_at": "2026-08-24T10:00:00+08:00",
            "decision": "passed",
            "operation_type": operation_type,
            "scope_sha256": scope_sha256,
            "authority": copy.deepcopy(cycle.REVIEW_CREDENTIAL_AUTHORITY),
        }
        credential_path = self.root / f"privacy-{operation_type}-{scope_sha256[:12]}.credential.json"
        cycle.write_json(credential_path, credential)
        receipt_ref = credential_path.relative_to(ROOT).as_posix()
        value["privacy_review"] = {
            "reviewer_ref": "human-privacy-reviewer",
            "receipt_ref": receipt_ref,
            "receipt_sha256": cycle.tracker.sha256_file(credential_path),
            "reviewed_at": "2026-08-24T10:00:00+08:00",
            "scope_sha256": scope_sha256,
        }

    def bind_lead_credential(self, review: dict) -> None:
        scope = copy.deepcopy(review)
        scope.pop("receipt_ref", None)
        scope.pop("receipt_sha256", None)
        scope_sha256 = cycle.canonical_hash(scope)
        credential = {
            "schema_version": "content-operations-cycle.lead-review-credential.v1",
            "reviewer_ref": review["reviewer_ref"],
            "reviewed_at": review["reviewed_at"],
            "decision": review["decision"],
            "operation_type": "review-lead",
            "scope_sha256": scope_sha256,
            "authority": copy.deepcopy(cycle.REVIEW_CREDENTIAL_AUTHORITY),
        }
        credential_path = self.root / f"lead-{review['decision']}-{scope_sha256[:12]}.credential.json"
        cycle.write_json(credential_path, credential)
        review["receipt_ref"] = credential_path.relative_to(ROOT).as_posix()
        review["receipt_sha256"] = cycle.tracker.sha256_file(credential_path)

    def test_demo_is_byte_stable_and_replay_is_already_recorded(self) -> None:
        first = cycle.demo(self.store)
        before = cycle.file_map(self.store)
        replay = cycle.demo(self.store)
        self.assertEqual(first["validation"]["journal_records"], 12)
        self.assertTrue(all(item["status"] == "already_recorded" for item in replay["steps"]))
        self.assertEqual(before, cycle.file_map(self.store))
        review = cycle.build_heads(cycle.read_journal(self.store))["operating-review"][0]
        business = next(item for item in review["layer_summaries"] if item["layer"] == "business")
        self.assertEqual(business["status"], "observed")
        self.assertEqual(
            business["evidence_refs"],
            ["lead_KAK2BNN9GGS2NEZAEGS0HGT4KH", "rev_039PT6M02YFA0WE7PSW17NC6C6"],
        )
        self.assertEqual(len(review["goal_reviews"]), 1)
        goal_review = review["goal_reviews"][0]
        self.assertEqual(goal_review["goal_id"], "goal_01ARZ3NDEKTSV4RRFFQ69G5FBC")
        self.assertEqual(goal_review["status"], "insufficient-evidence")
        self.assertEqual(
            [item["criterion_id"] for item in goal_review["criterion_results"]],
            ["criterion_complete-cycle"],
        )
        self.assertEqual(
            review["input_refs"]["experiment_run_ids"],
            ["exp_1Z834ZGZTK191K8X31MRRRG2K5"],
        )
        self.assertEqual(
            review["input_refs"]["diagnostic_run_ids"],
            ["diag_T8A0BKHN0D2EHVWNV9PZTAQRKT"],
        )
        self.assertEqual(review["resource_summary"]["human_time_hours"], 1.5)
        self.assertEqual(review["revenue_summary"]["direct_count"], 1)
        self.assertFalse(review["revenue_summary"]["causal_claim"])
        self.assertEqual(
            review["next_experiment_ids"], ["exp_1Z834ZGZTK191K8X31MRRRG2K5"]
        )
        heads = cycle.build_heads(cycle.read_journal(self.store))
        self.assertEqual(len(heads["account-continuity-plan"]), 1)
        self.assertEqual(len(heads["account-security-event"]), 1)

    def test_demo_rejects_non_synthetic_fixture_before_writing(self) -> None:
        fixture_root = self.root / "fixture-root"
        shutil.copytree(self.fixture("record-publication.input.json").parent, fixture_root)
        publication = cycle.load_json(fixture_root / "record-publication.input.json")
        publication["data_classification"] = "deidentified-operational"
        cycle.write_json(fixture_root / "record-publication.input.json", publication)
        with self.assertRaises(cycle.CycleError) as raised:
            cycle.demo(self.store, fixture_root)
        self.assertEqual(raised.exception.code, "demo_non_synthetic_fixture")
        self.assertFalse(self.store.exists())

    def test_publication_requires_current_goal_source(self) -> None:
        missing = self.input_copy(
            "record-publication.input.json",
            lambda value: value["source_objects"].pop("goal_ref"),
        )
        with self.assertRaises(cycle.CycleError) as raised:
            cycle.record_from_input(self.store, "record-publication", missing)
        self.assertEqual(raised.exception.code, "missing_required_field")

        stale = self.input_copy(
            "record-publication.input.json",
            lambda value: value["source_objects"].__setitem__("goal_sha256", "0" * 64),
        )
        with self.assertRaises(cycle.CycleError) as raised:
            cycle.record_from_input(self.store, "record-publication", stale)
        self.assertEqual(raised.exception.code, "stale_source_artifact")

    def test_publication_goal_must_cover_source_account(self) -> None:
        goal = json.loads(
            self.fixture("operating-goal.source.json").read_text(encoding="utf-8")
        )
        goal["account_ids"] = ["acct_00000000000000000000000000"]
        goal_path = self.root / "goal-account-drift.json"
        cycle.write_json(goal_path, goal)
        request = json.loads(
            self.fixture("record-publication.input.json").read_text(encoding="utf-8")
        )
        request["source_objects"]["goal_ref"] = goal_path.relative_to(ROOT).as_posix()
        request["source_objects"]["goal_sha256"] = cycle.tracker.sha256_file(goal_path)
        request_path = self.root / "goal-account-drift.input.json"
        cycle.write_json(request_path, request)
        with self.assertRaises(cycle.CycleError) as raised:
            cycle.record_from_input(self.store, "record-publication", request_path)
        self.assertEqual(raised.exception.code, "goal_account_reference_drift")

    def test_same_identity_with_changed_payload_is_conflict(self) -> None:
        self.record_publication()
        changed = self.input_copy(
            "record-publication.input.json",
            lambda value: value.__setitem__("title", "A different synthetic title"),
        )
        with self.assertRaisesRegex(cycle.CycleError, "publication:pub_") as raised:
            cycle.record_from_input(self.store, "record-publication", changed)
        self.assertEqual(raised.exception.code, "operation_conflict")
        self.assertEqual(cycle.validate_store_strict(self.store)["journal_records"], 1)

    def test_manual_publication_change_chain_is_append_only_and_idempotent(self) -> None:
        self.record_publication()
        edit = cycle.record_from_input(
            self.store,
            "record-publication-edit",
            self.fixture("record-publication-edit.input.json"),
        )
        self.assertEqual(edit["status"], "recorded")
        self.assertEqual(
            cycle.record_from_input(
                self.store,
                "record-publication-edit",
                self.fixture("record-publication-edit.input.json"),
            )["status"],
            "already_recorded",
        )
        cycle.record_from_input(
            self.store,
            "record-publication-delete",
            self.fixture("record-publication-delete.input.json"),
        )
        cycle.record_from_input(
            self.store,
            "record-publication-restore",
            self.fixture("record-publication-restore.input.json"),
        )
        events = sorted(
            cycle.build_heads(cycle.read_journal(self.store))["publication-event"],
            key=lambda item: item["event_sequence"],
        )
        self.assertEqual(
            [item["event_type"] for item in events],
            ["published", "edited", "deleted", "restored"],
        )
        self.assertEqual([item["event_sequence"] for item in events], [1, 2, 3, 4])
        self.assertEqual(
            [item.get("supersedes_event_id") for item in events],
            [None, events[0]["event_id"], events[1]["event_id"], events[2]["event_id"]],
        )
        self.assertIn("frozen_version", events[1])
        self.assertNotIn("frozen_version", events[2])
        self.assertEqual(cycle.validate_store_strict(self.store)["journal_records"], 4)

    def test_delete_and_repost_links_old_and_new_publications(self) -> None:
        self.record_publication()
        delete_input = self.input_copy(
            "record-publication-delete.input.json",
            lambda value: value.__setitem__(
                "source_event_id", "evt_695VG7TNBTD0XWWV2VGB9FWKBK"
            ),
        )
        cycle.record_from_input(
            self.store, "record-publication-delete", delete_input
        )
        cycle.record_from_input(
            self.store,
            "record-publication",
            self.fixture("record-publication-repost.input.json"),
        )
        events = cycle.build_heads(cycle.read_journal(self.store))["publication-event"]
        old_deleted = next(item for item in events if item["event_type"] == "deleted")
        new_published = next(
            item
            for item in events
            if item["event_type"] == "published"
            and item["publication_id"] != old_deleted["publication_id"]
        )
        self.assertEqual(new_published["supersedes_event_id"], old_deleted["event_id"])
        self.assertEqual(new_published["content_id"], old_deleted["content_id"])
        self.assertEqual(new_published["account_id"], old_deleted["account_id"])
        self.assertEqual(cycle.validate_store_strict(self.store)["journal_records"], 3)

    def test_publication_changes_fail_closed_without_free_operation_selector(self) -> None:
        self.record_publication()
        free_selector = self.input_copy(
            "record-publication-edit.input.json",
            lambda value: value.__setitem__("event_type", "deleted"),
        )
        with self.assertRaises(cycle.CycleError) as raised:
            cycle.record_from_input(
                self.store, "record-publication-edit", free_selector
            )
        self.assertEqual(raised.exception.code, "unexpected_field")

        premature_restore = self.input_copy(
            "record-publication-restore.input.json",
            lambda value: value.__setitem__(
                "source_event_id", "evt_695VG7TNBTD0XWWV2VGB9FWKBK"
            ),
        )
        with self.assertRaises(cycle.CycleError) as raised:
            cycle.record_from_input(
                self.store, "record-publication-restore", premature_restore
            )
        self.assertEqual(raised.exception.code, "publication_transition_invalid")
        self.assertEqual(cycle.validate_store_strict(self.store)["journal_records"], 1)

    def test_repost_requires_terminal_deleted_source(self) -> None:
        self.record_publication()
        invalid = self.input_copy(
            "record-publication-repost.input.json",
            lambda value: value.__setitem__(
                "replaces_deleted_event_id", "evt_695VG7TNBTD0XWWV2VGB9FWKBK"
            ),
        )
        before = cycle.file_map(self.store)
        with self.assertRaises(cycle.CycleError) as raised:
            cycle.record_from_input(self.store, "record-publication", invalid)
        self.assertEqual(raised.exception.code, "replacement_chain_invalid")
        self.assertEqual(before, cycle.file_map(self.store))

    def test_early_and_d7_are_distinct_windows(self) -> None:
        self.record_publication()
        cycle.record_from_input(
            self.store, "record-snapshot", self.fixture("record-snapshot-early.input.json")
        )
        cycle.record_from_input(
            self.store, "record-snapshot", self.fixture("record-snapshot-d7.input.json")
        )
        heads = cycle.build_heads(cycle.read_journal(self.store))
        self.assertEqual([item["window_label"] for item in heads["performance-snapshot"]], ["early", "d7"])

    def test_window_drift_rolls_back_without_partial_commit(self) -> None:
        self.record_publication()
        before = cycle.file_map(self.store)
        invalid = self.input_copy(
            "record-snapshot-early.input.json",
            lambda value: value.__setitem__("as_of", "2026-08-12T07:00:00+08:00"),
        )
        with self.assertRaises(cycle.CycleError) as raised:
            cycle.record_from_input(self.store, "record-snapshot", invalid)
        self.assertEqual(raised.exception.code, "cross_object_validation_failed")
        self.assertEqual(before, cycle.file_map(self.store))

    def test_confirm_is_atomic_and_creates_exactly_one_lead(self) -> None:
        self.record_publication()
        self.record_business_interaction()
        result = cycle.record_from_input(
            self.store, "review-lead", self.fixture("review-lead-confirm.input.json")
        )
        self.assertEqual(result["status"], "recorded")
        heads = cycle.build_heads(cycle.read_journal(self.store))
        self.assertEqual(heads["interaction-event"][0]["lead_promotion_status"], "promoted")
        self.assertEqual(len(heads["lead-event"]), 1)
        self.assertFalse(heads["lead-event"][0]["authority"]["execution_authorized"])
        self.assertEqual(heads["lead-event"][0]["handoff"]["status"], "not-started")
        self.assertIsNone(heads["lead-event"][0]["handoff"]["receipt_ref"])
        self.assertEqual(
            heads["lead-event"][0]["review"]["receipt_ref"],
            "fixtures/content-operations-cycle-v1/lead-review-confirm.credential.json",
        )
        self.assertEqual(
            heads["lead-event"][0]["review"]["receipt_sha256"],
            "f2aeac272319c87129aa1d452184a38040fb8e234f8635d3b01d9bd396f6a20c",
        )
        self.assertRegex(heads["lead-event"][0]["review"]["review_scope_sha256"], r"^[a-f0-9]{64}$")
        replay = cycle.record_from_input(
            self.store, "review-lead", self.fixture("review-lead-confirm.input.json")
        )
        self.assertEqual(replay["status"], "already_recorded")
        self.assertEqual(len(cycle.build_heads(cycle.read_journal(self.store))["lead-event"]), 1)

    def test_reject_marks_interaction_and_creates_no_lead(self) -> None:
        self.record_publication()
        interaction_path = self.input_copy(
            "record-interaction-business.input.json",
            lambda value: value.__setitem__("interaction_key", "synthetic-next-step-booked-reject-001"),
        )
        interaction = json.loads(interaction_path.read_text(encoding="utf-8"))
        interaction["business_event_type"] = "next_step_booked"
        interaction["evidence_refs"] = ["fixture:event:next-step-booked-reject-001"]
        cycle.write_json(interaction_path, interaction)
        cycle.record_from_input(self.store, "record-interaction", interaction_path)
        review = json.loads(self.fixture("review-lead-confirm.input.json").read_text(encoding="utf-8"))
        review["interaction_event_id"] = "int_BCC89NC2Q0N180AGBEE83HZ1S2"
        review["decision"] = "reject"
        review["evidence_refs"] = ["fixture:event:next-step-booked-reject-001"]
        self.bind_lead_credential(review)
        review_path = self.root / "review-reject.json"
        cycle.write_json(review_path, review)
        cycle.record_from_input(self.store, "review-lead", review_path)
        heads = cycle.build_heads(cycle.read_journal(self.store))
        self.assertEqual(heads["interaction-event"][0]["lead_promotion_status"], "rejected")
        self.assertEqual(heads["lead-event"], [])

    def test_content_observation_cannot_smuggle_business_event(self) -> None:
        self.record_publication()
        invalid = self.input_copy(
            "record-interaction-business.input.json",
            lambda value: value.update(
                {"signal_class": "content-observation", "disposition": "content-input"}
            ),
        )
        with self.assertRaises(cycle.CycleError) as raised:
            cycle.record_from_input(self.store, "record-interaction", invalid)
        self.assertEqual(raised.exception.code, "signal_escalation")

    def test_lead_requires_human_receipt_and_matching_evidence(self) -> None:
        self.record_publication()
        self.record_business_interaction()
        missing_receipt = self.input_copy(
            "review-lead-confirm.input.json",
            lambda value: value.__setitem__("receipt_ref", ""),
        )
        with self.assertRaises(cycle.CycleError) as raised:
            cycle.record_from_input(self.store, "review-lead", missing_receipt)
        self.assertEqual(raised.exception.code, "human_receipt_required")
        mismatched_value = json.loads(
            self.fixture("review-lead-confirm.input.json").read_text(encoding="utf-8")
        )
        mismatched_value["evidence_refs"] = ["fixture:event:unrelated"]
        self.bind_lead_credential(mismatched_value)
        mismatched = self.root / "review-lead-mismatched-evidence.json"
        cycle.write_json(mismatched, mismatched_value)
        with self.assertRaises(cycle.CycleError) as raised:
            cycle.record_from_input(self.store, "review-lead", mismatched)
        self.assertEqual(raised.exception.code, "evidence_continuity")
        missing_hash = self.input_copy(
            "review-lead-confirm.input.json",
            lambda value: value.pop("receipt_sha256"),
        )
        with self.assertRaises(cycle.CycleError) as raised:
            cycle.record_from_input(self.store, "review-lead", missing_hash)
        self.assertEqual(raised.exception.code, "missing_required_field")
        missing_consent = self.input_copy(
            "review-lead-confirm.input.json",
            lambda value: value.pop("consent_status"),
        )
        with self.assertRaises(cycle.CycleError) as raised:
            cycle.record_from_input(self.store, "review-lead", missing_consent)
        self.assertEqual(raised.exception.code, "explicit_attribution_required")

    def test_lead_receipt_bytes_scope_and_authority_are_fail_closed(self) -> None:
        self.record_publication()
        self.record_business_interaction()

        missing = self.input_copy(
            "review-lead-confirm.input.json",
            lambda value: value.update(
                {"receipt_ref": "fixtures/content-operations-cycle-v1/missing.credential.json",
                 "receipt_sha256": "0" * 64}
            ),
        )
        with self.assertRaises(cycle.CycleError) as raised:
            cycle.record_from_input(self.store, "review-lead", missing)
        self.assertEqual(raised.exception.code, "receipt_unresolvable")

        elevated = json.loads(
            self.fixture("review-lead-confirm.input.json").read_text(encoding="utf-8")
        )
        self.bind_lead_credential(elevated)
        elevated_credential_path = cycle.tracker.resolve_repo_ref(elevated["receipt_ref"])
        elevated_credential = json.loads(elevated_credential_path.read_text(encoding="utf-8"))
        elevated_credential["authority"]["execution_authorized"] = True
        cycle.write_json(elevated_credential_path, elevated_credential)
        elevated["receipt_sha256"] = cycle.tracker.sha256_file(elevated_credential_path)
        elevated_path = self.root / "lead-authority-escalation.json"
        cycle.write_json(elevated_path, elevated)
        with self.assertRaises(cycle.CycleError) as raised:
            cycle.record_from_input(self.store, "review-lead", elevated_path)
        self.assertEqual(raised.exception.code, "receipt_authority_escalation")

        scope_drift = json.loads(
            self.fixture("review-lead-confirm.input.json").read_text(encoding="utf-8")
        )
        self.bind_lead_credential(scope_drift)
        scope_credential_path = cycle.tracker.resolve_repo_ref(scope_drift["receipt_ref"])
        scope_credential = json.loads(scope_credential_path.read_text(encoding="utf-8"))
        scope_credential["scope_sha256"] = "0" * 64
        cycle.write_json(scope_credential_path, scope_credential)
        scope_drift["receipt_sha256"] = cycle.tracker.sha256_file(scope_credential_path)
        scope_path = self.root / "lead-scope-drift.json"
        cycle.write_json(scope_path, scope_drift)
        with self.assertRaises(cycle.CycleError) as raised:
            cycle.record_from_input(self.store, "review-lead", scope_path)
        self.assertEqual(raised.exception.code, "receipt_scope_drift")

    def test_no_signal_review_remains_insufficient_evidence(self) -> None:
        self.record_publication()
        cycle.record_from_input(
            self.store,
            "record-interaction",
            self.fixture("record-interaction-no-signal.input.json"),
        )
        cycle.record_from_input(self.store, "build-review", self.current_review_input())
        review = cycle.build_heads(cycle.read_journal(self.store))["operating-review"][0]
        self.assertEqual(review["review_state"], "draft-only")
        self.assertTrue(all(item["status"] == "insufficient-evidence" for item in review["layer_summaries"]))
        self.assertEqual(review["revenue_summary"]["direct_count"], 0)

    def test_rebuild_restores_heads_but_not_a_tampered_journal(self) -> None:
        cycle.demo(self.store)
        anchor_before = (self.store / cycle.STORE_ANCHOR_FILE).read_bytes()
        head_path = self.store / "heads" / "performance-snapshots.json"
        head = json.loads(head_path.read_text(encoding="utf-8"))
        head["items"] = []
        cycle.write_json(head_path, head)
        with self.assertRaises(cycle.CycleError) as raised:
            cycle.validate_store_strict(self.store)
        self.assertEqual(raised.exception.code, "head_drift")
        cycle.rebuild_store_heads(self.store)
        self.assertEqual(cycle.validate_store_strict(self.store)["status"], "passed")
        self.assertEqual(anchor_before, (self.store / cycle.STORE_ANCHOR_FILE).read_bytes())
        journal = sorted((self.store / "journal").glob("*.json"))[0]
        record = json.loads(journal.read_text(encoding="utf-8"))
        record["payload"]["event"]["frozen_version"]["title"] = "tampered"
        cycle.write_json(journal, record)
        with self.assertRaises(cycle.CycleError) as raised:
            cycle.rebuild_store_heads(self.store)
        self.assertEqual(raised.exception.code, "journal_payload_hash_drift")

    def test_sensitive_raw_comment_is_fail_closed(self) -> None:
        self.record_publication()
        invalid = self.input_copy(
            "record-interaction-no-signal.input.json",
            lambda value: value.__setitem__("comment_text", "synthetic raw text must not enter"),
        )
        with self.assertRaises((cycle.CycleError, cycle.tracker.TrackerError)):
            cycle.record_from_input(self.store, "record-interaction", invalid)

    def test_active_lock_prevents_recovery_from_deleting_staging(self) -> None:
        lock = self.store.with_name(f".{self.store.name}.lock")
        staging = self.store.with_name(f".{self.store.name}.staging.synthetic")
        lock.write_text("synthetic lock", encoding="utf-8")
        staging.mkdir()
        marker = staging / "marker.txt"
        marker.write_text("must survive", encoding="utf-8")
        with self.assertRaises(cycle.CycleError) as raised:
            cycle.recover_store(self.store)
        self.assertEqual(raised.exception.code, "store_locked")
        self.assertTrue(marker.exists())

    def test_check_runs_two_independent_stores(self) -> None:
        result = cycle.check()
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["idempotency"], "byte-stable")
        self.assertFalse(result["execution_authorized"])

    def test_store_is_restricted_and_requires_governance_sentinel(self) -> None:
        with self.assertRaises(cycle.CycleError) as raised:
            cycle.record_from_input(
                ROOT / "outside-content-operations",
                "record-publication",
                self.fixture("record-publication.input.json"),
            )
        self.assertEqual(raised.exception.code, "store_outside_private_root")
        with self.assertRaises(cycle.CycleError) as raised:
            cycle.record_from_input(
                ROOT / "tests" / ".runtime" / "content-operations",
                "record-publication",
                self.fixture("record-publication.input.json"),
            )
        self.assertEqual(raised.exception.code, "store_root_prohibited")
        with self.assertRaises(cycle.CycleError) as raised:
            cycle.record_from_input(
                self.root,
                "record-publication",
                self.fixture("record-publication.input.json"),
            )
        self.assertEqual(raised.exception.code, "existing_nonstore_directory")
        self.record_publication()
        self.assertTrue((self.store / cycle.STORE_METADATA_FILE).is_file())
        self.assertTrue((self.store / cycle.STORE_ANCHOR_FILE).is_file())
        self.assertTrue(cycle.checkpoint_file(self.store).is_file())

    def test_store_reparse_point_is_rejected_when_supported(self) -> None:
        target = self.root / "target"
        target.mkdir()
        linked = self.root / "linked-store"
        try:
            linked.symlink_to(target, target_is_directory=True)
        except OSError:
            self.skipTest("directory symlink creation is unavailable")
        with self.assertRaises(cycle.CycleError) as raised:
            cycle.record_from_input(
                linked, "record-publication", self.fixture("record-publication.input.json")
            )
        self.assertIn(raised.exception.code, {"store_reparse_prohibited", "store_escape"})

    def test_recovery_preserves_ambiguous_and_corrupt_candidates(self) -> None:
        self.record_publication()
        backup = self.store.with_name(f".{self.store.name}.backup")
        shutil.copytree(self.store, backup)
        with self.assertRaises(cycle.CycleError) as raised:
            cycle.recover_store(self.store)
        self.assertEqual(raised.exception.code, "recovery_ambiguous")
        self.assertTrue(self.store.exists())
        self.assertTrue(backup.exists())
        cycle.safe_rmtree(backup)
        shutil.copytree(self.store, backup)
        cycle.safe_rmtree(self.store)
        anchor = cycle.load_json(backup / cycle.STORE_ANCHOR_FILE)
        anchor["journal_record_count"] += 1
        cycle.write_json(backup / cycle.STORE_ANCHOR_FILE, anchor)
        with self.assertRaises(cycle.CycleError) as raised:
            cycle.recover_store(self.store)
        self.assertEqual(raised.exception.code, "store_anchor_drift")
        self.assertFalse(self.store.exists())
        self.assertTrue(backup.exists())

    def test_anchor_detects_deleted_tail_before_rebuild(self) -> None:
        cycle.demo(self.store)
        sorted((self.store / "journal").glob("*.json"))[-1].unlink()
        remaining = cycle.read_journal(self.store)
        cycle.write_store_anchor(self.store, remaining)
        with self.assertRaises(cycle.CycleError) as raised:
            cycle.rebuild_store_heads(self.store)
        self.assertEqual(raised.exception.code, "external_checkpoint_drift")

    def test_external_checkpoint_truncation_and_hash_tamper_are_fail_closed(self) -> None:
        cycle.demo(self.store)
        checkpoint_path = cycle.checkpoint_file(self.store)
        lines = checkpoint_path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 12)

        checkpoint_path.write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8", newline="\n")
        with self.assertRaises(cycle.CycleError) as raised:
            cycle.validate_store_strict(self.store)
        self.assertEqual(raised.exception.code, "external_checkpoint_drift")

        checkpoint_path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
        tampered = json.loads(lines[-1])
        tampered["tail_record_sha256"] = "0" * 64
        lines[-1] = json.dumps(tampered, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        checkpoint_path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
        with self.assertRaises(cycle.CycleError) as raised:
            cycle.validate_store_strict(self.store)
        self.assertEqual(raised.exception.code, "checkpoint_hash_drift")

    def test_full_record_hash_and_store_identity_are_verified(self) -> None:
        self.record_publication()
        metadata_path = self.store / cycle.STORE_METADATA_FILE
        metadata = cycle.load_json(metadata_path)
        original_metadata = copy.deepcopy(metadata)
        metadata["store_id"] = "store_00000000000000000000000000"
        cycle.write_json(metadata_path, metadata)
        with self.assertRaises(cycle.CycleError) as raised:
            cycle.validate_store_strict(self.store)
        self.assertEqual(raised.exception.code, "store_identity_drift")
        cycle.write_json(metadata_path, original_metadata)
        journal = sorted((self.store / "journal").glob("*.json"))[0]
        record = cycle.load_json(journal)
        original_record = copy.deepcopy(record)
        record["contract_set"]["canonical_json_sha256"] = "0" * 64
        cycle.write_json(journal, record)
        with self.assertRaises(cycle.CycleError) as raised:
            cycle.validate_store_strict(self.store)
        self.assertEqual(raised.exception.code, "contract_set_drift")
        cycle.write_json(journal, original_record)
        record = copy.deepcopy(original_record)
        record["recorded_at"] = "2026-08-10T09:06:00+08:00"
        cycle.write_json(journal, record)
        with self.assertRaises(cycle.CycleError) as raised:
            cycle.validate_store_strict(self.store)
        self.assertEqual(raised.exception.code, "journal_record_hash_drift")

    def test_idempotent_replay_strictly_validates_existing_store(self) -> None:
        self.record_publication()
        manifest = self.store / "heads" / "manifest.json"
        value = cycle.load_json(manifest)
        value["journal_record_count"] = 99
        cycle.write_json(manifest, value)
        with self.assertRaises(cycle.CycleError) as raised:
            self.record_publication()
        self.assertEqual(raised.exception.code, "head_drift")

    def test_classification_and_human_privacy_review_are_fail_closed(self) -> None:
        missing = self.input_copy(
            "record-publication.input.json",
            lambda value: value.__setitem__("data_classification", "deidentified-operational"),
        )
        with self.assertRaises(cycle.CycleError) as raised:
            cycle.record_from_input(self.store, "record-publication", missing)
        self.assertEqual(raised.exception.code, "privacy_review_required")
        drift = self.input_copy("record-publication.input.json", self.make_deidentified)
        drift_value = cycle.load_json(drift)
        drift_value["title"] = "changed after privacy review"
        cycle.write_json(drift, drift_value)
        with self.assertRaises(cycle.CycleError) as raised:
            cycle.record_from_input(self.store, "record-publication", drift)
        self.assertEqual(raised.exception.code, "privacy_scope_hash_drift")
        accepted = self.input_copy("record-publication.input.json", self.make_deidentified)
        deidentified_store = self.root / "deidentified-store"
        self.assertEqual(
            cycle.record_from_input(deidentified_store, "record-publication", accepted)["status"],
            "recorded",
        )

        fake_receipt = self.input_copy("record-publication.input.json", self.make_deidentified)
        fake_value = json.loads(fake_receipt.read_text(encoding="utf-8"))
        fake_value["privacy_review"]["receipt_ref"] = (
            "fixtures/content-operations-cycle-v1/missing-privacy.credential.json"
        )
        fake_value["privacy_review"]["receipt_sha256"] = "0" * 64
        cycle.write_json(fake_receipt, fake_value)
        with self.assertRaises(cycle.CycleError) as raised:
            cycle.record_from_input(self.root / "fake-privacy-store", "record-publication", fake_receipt)
        self.assertEqual(raised.exception.code, "receipt_unresolvable")
        self.record_publication()
        deidentified = self.input_copy("record-interaction-no-signal.input.json", self.make_deidentified)
        with self.assertRaises(cycle.CycleError) as raised:
            cycle.record_from_input(self.store, "record-interaction", deidentified)
        self.assertEqual(raised.exception.code, "classification_mixing_prohibited")

    def test_obvious_contact_url_and_absolute_path_are_rejected(self) -> None:
        for summary in (
            "Call 13800138000",
            "See https://example.test/private",
            r"Local artifact C:\\Users\\Example\\private.txt",
        ):
            invalid = self.input_copy(
                "record-interaction-no-signal.input.json",
                lambda value, text=summary: value.__setitem__("deidentified_summary", text),
            )
            with self.assertRaises(cycle.CycleError) as raised:
                cycle.record_from_input(self.store, "record-interaction", invalid)
            self.assertEqual(raised.exception.code, "obvious_sensitive_value")

    def test_complete_freeze_requires_resolvable_body_and_real_hash(self) -> None:
        def complete(value: dict) -> None:
            value["publication_key"] = "synthetic-complete-freeze-001"
            value["freeze_status"] = "complete"
            value.pop("unavailable_reason")
            value["body_ref"] = "fixtures/content-operations-cycle-v1/synthetic-body.md"
            value["body_sha256"] = "9d4343490e744667091336ba5322b428b5451ceffcb9756334053ec25488bf9d"

        valid = self.input_copy("record-publication.input.json", complete)
        self.assertEqual(cycle.record_from_input(self.store, "record-publication", valid)["status"], "recorded")
        missing = self.input_copy(
            "record-publication.input.json",
            lambda value: (value.__setitem__("freeze_status", "complete"), value.pop("unavailable_reason")),
        )
        with self.assertRaises(cycle.CycleError) as raised:
            cycle.record_from_input(self.root / "missing-body-store", "record-publication", missing)
        self.assertEqual(raised.exception.code, "missing_body_evidence")
        stale = self.input_copy("record-publication.input.json", complete)
        stale_value = cycle.load_json(stale)
        stale_value["body_sha256"] = "0" * 64
        cycle.write_json(stale, stale_value)
        with self.assertRaises(cycle.CycleError) as raised:
            cycle.record_from_input(self.root / "stale-body-store", "record-publication", stale)
        self.assertEqual(raised.exception.code, "stale_body_artifact")

    def test_revenue_requires_real_scoped_human_receipt(self) -> None:
        missing = self.input_copy(
            "record-revenue.input.json", lambda value: value.pop("decision_review")
        )
        with self.assertRaises(cycle.CycleError) as raised:
            cycle.record_from_input(self.store, "record-revenue", missing)
        self.assertEqual(raised.exception.code, "human_receipt_required")

        unresolved = self.input_copy(
            "record-revenue.input.json",
            lambda value: value["decision_review"].update({
                "receipt_ref": "fixtures/content-operations-cycle-v1/missing-revenue.credential.json",
                "receipt_sha256": "0" * 64,
            }),
        )
        with self.assertRaises(cycle.CycleError) as raised:
            cycle.record_from_input(self.store, "record-revenue", unresolved)
        self.assertEqual(raised.exception.code, "receipt_unresolvable")

    def test_revenue_receipt_cannot_grant_authority(self) -> None:
        request = cycle.load_json(self.fixture("record-revenue.input.json"))
        credential = cycle.load_json(self.fixture("revenue-review-confirm.credential.json"))
        credential["authority"]["execution_authorized"] = True
        credential_path = self.root / "revenue-authority-escalation.credential.json"
        cycle.write_json(credential_path, credential)
        request["decision_review"]["receipt_ref"] = credential_path.relative_to(ROOT).as_posix()
        request["decision_review"]["receipt_sha256"] = cycle.tracker.sha256_file(credential_path)
        request_path = self.root / "revenue-authority-escalation.input.json"
        cycle.write_json(request_path, request)
        with self.assertRaises(cycle.CycleError) as raised:
            cycle.record_from_input(self.store, "record-revenue", request_path)
        self.assertEqual(raised.exception.code, "receipt_authority_escalation")

    def test_outer_contract_reference_drift_rolls_back(self) -> None:
        self.record_publication()
        before = cycle.file_map(self.store)
        invalid = self.input_copy(
            "record-resource.input.json",
            lambda value: value["artifact"].__setitem__(
                "publication_id", "pub_00000000000000000000000000"
            ),
        )
        with self.assertRaises(cycle.CycleError) as raised:
            cycle.record_from_input(self.store, "record-resource", invalid)
        self.assertEqual(raised.exception.code, "cross_object_validation_failed")
        self.assertEqual(before, cycle.file_map(self.store))

    def test_publication_source_platform_and_account_must_match(self) -> None:
        platform = self.input_copy(
            "record-publication.input.json",
            lambda value: value.__setitem__("platform", "different-synthetic-surface"),
        )
        with self.assertRaises(cycle.CycleError) as raised:
            cycle.record_from_input(self.store, "record-publication", platform)
        self.assertEqual(raised.exception.code, "platform_reference_drift")
        account = self.input_copy(
            "record-publication.input.json",
            lambda value: value.__setitem__("account_id", "acct_00000000000000000000000000"),
        )
        with self.assertRaises(cycle.CycleError) as raised:
            cycle.record_from_input(self.store, "record-publication", account)
        self.assertEqual(raised.exception.code, "account_reference_drift")

    def test_late_data_requires_explicit_review_revision(self) -> None:
        cycle.demo(self.store)
        cycle.record_from_input(
            self.store, "record-interaction", self.fixture("record-interaction-no-signal.input.json")
        )
        with self.assertRaises(cycle.CycleError) as raised:
            cycle.record_from_input(self.store, "build-review", self.fixture("build-review.input.json"))
        self.assertEqual(raised.exception.code, "source_head_drift")
        revision = self.current_review_input()
        result = cycle.record_from_input(self.store, "build-review", revision)
        self.assertEqual(result["status"], "recorded")
        self.assertEqual(len(cycle.build_heads(cycle.read_journal(self.store))["operating-review"]), 2)

    def test_review_excludes_events_recorded_after_created_at(self) -> None:
        self.record_publication()
        future = self.input_copy(
            "record-interaction-no-signal.input.json",
            lambda value: value.update({
                "interaction_key": "synthetic-future-no-signal-001",
                "occurred_at": "2026-08-19T09:15:00+08:00",
                "recorded_at": "2026-08-19T09:20:00+08:00",
            }),
        )
        cycle.record_from_input(self.store, "record-interaction", future)
        cycle.record_from_input(self.store, "build-review", self.current_review_input())
        review = cycle.build_heads(cycle.read_journal(self.store))["operating-review"][0]
        self.assertEqual(review["input_refs"]["interaction_event_ids"], [])

    def test_exact_window_boundaries_are_accepted(self) -> None:
        cases = (
            ("early", "2026-08-12T09:00:00+08:00"),
            ("early", "2026-08-13T09:00:00+08:00"),
            ("d7", "2026-08-16T21:00:00+08:00"),
            ("d7", "2026-08-17T21:00:00+08:00"),
        )
        for index, (window, as_of) in enumerate(cases):
            store = self.root / f"boundary-{index}"
            cycle.record_from_input(
                store, "record-publication", self.fixture("record-publication.input.json")
            )
            source = "record-snapshot-early.input.json" if window == "early" else "record-snapshot-d7.input.json"
            path = self.input_copy(
                source,
                lambda value, w=window, timestamp=as_of: value.update({
                    "window_label": w,
                    "as_of": timestamp,
                    "captured_at": timestamp,
                }),
            )
            self.assertEqual(cycle.record_from_input(store, "record-snapshot", path)["status"], "recorded")


if __name__ == "__main__":
    unittest.main()
