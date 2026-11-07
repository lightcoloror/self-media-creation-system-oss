from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import shutil
import unittest
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "topic_discovery_inbox.py"
SPEC = importlib.util.spec_from_file_location("topic_discovery_inbox", SCRIPT)
assert SPEC and SPEC.loader
INBOX = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(INBOX)


class TopicDiscoveryInboxTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = ROOT / "tests" / ".runtime" / f"topic-discovery-{uuid.uuid4().hex}"
        self.runtime.mkdir(parents=True)
        self.ledger = self.runtime / "observations.jsonl"
        self.output = self.runtime / "bundle"

    def tearDown(self) -> None:
        shutil.rmtree(self.runtime, ignore_errors=True)

    def fixture_events(self) -> list[dict]:
        source = ROOT / "fixtures" / "topic-discovery-inbox-v1" / "observations.seed.jsonl"
        self.ledger.write_text(source.read_text(encoding="utf-8"), encoding="utf-8", newline="\n")
        return INBOX.load_ledger(self.ledger)

    def capture_args(self, **overrides: object) -> argparse.Namespace:
        values = {
            "question": "家里买过几份保险，应该先怎么整理？",
            "source_lane": "customer-question",
            "source_ref": "fixture://manual/capture-1",
            "source_hash": None,
            "independence_group": "synthetic-capture-group-1",
            "topic_key": "policy-inventory-first",
            "signal_id": None,
            "observed_at": "2026-09-01T09:00:00+08:00",
            "audience_hint": "买过保险但说不清已有保障的家庭",
            "account_ip": "cange-risk-diagnosis",
            "priority": "P0",
            "risk": "low",
            "fact_dependency": "low",
            "personal_experience_status": "unknown_not_required",
            "current_product_status": "not_applicable",
            "evidence_status": "user_confirmed",
            "privacy_passed": True,
            "counts_toward_frequency": True,
            "content_signal_only": False,
            "cluster_reviewed": True,
            "repeat_confirmed": False,
            "synthetic_only": True,
        }
        values.update(overrides)
        return argparse.Namespace(**values)

    def test_synthetic_fixture_is_valid(self) -> None:
        events = self.fixture_events()
        self.assertEqual(len(events), 5)
        self.assertTrue(all(INBOX.observation_errors(event) == [] for event in events))

    def test_capture_is_idempotent(self) -> None:
        event = INBOX.build_observation(self.capture_args())
        first = INBOX.append_observation(self.ledger, event)
        second = INBOX.append_observation(self.ledger, event)
        self.assertEqual(first["status"], "appended")
        self.assertEqual(second["status"], "already_exists")
        self.assertEqual(len(INBOX.load_ledger(self.ledger)), 1)

    def test_existing_empty_ledger_can_accept_first_event(self) -> None:
        self.ledger.write_text("", encoding="utf-8")
        event = INBOX.build_observation(self.capture_args())
        result = INBOX.append_observation(self.ledger, event)
        self.assertEqual(result["status"], "appended")

    def test_same_signal_id_with_changed_payload_fails_closed(self) -> None:
        event = INBOX.build_observation(self.capture_args())
        INBOX.append_observation(self.ledger, event)
        changed = copy.deepcopy(event)
        changed["risk_level"] = "high"
        with self.assertRaises(INBOX.DiscoveryError) as raised:
            INBOX.append_observation(self.ledger, changed)
        self.assertEqual(raised.exception.code, "signal_id_drift")

    def test_direct_identifier_is_rejected(self) -> None:
        args = self.capture_args(question="请联系我13800138000帮忙看保单")
        with self.assertRaisesRegex(INBOX.DiscoveryError, "phone"):
            INBOX.build_observation(args)

    def test_agent_candidate_cannot_count_toward_frequency(self) -> None:
        event = INBOX.build_observation(self.capture_args())
        event["created_by"] = "agent_candidate"
        errors = INBOX.observation_errors(event)
        self.assertTrue(any("agent candidate" in error for error in errors))

    def test_strategy_gap_cannot_count_toward_frequency(self) -> None:
        with self.assertRaises(INBOX.DiscoveryError) as raised:
            INBOX.build_observation(self.capture_args(source_lane="strategy-gap"))
        self.assertEqual(raised.exception.code, "observation_invalid")
        self.assertIn("strategy gap", str(raised.exception))

    def test_same_independence_group_does_not_inflate_frequency(self) -> None:
        events = self.fixture_events()
        duplicate = copy.deepcopy(events[0])
        duplicate["signal_id"] = "sig_synthetic-policy-duplicate"
        duplicate["source_hash"] = "f" * 64
        duplicate["repeat_confirmation"] = "not_confirmed"
        duplicate["cluster_review_status"] = "deterministic_exact"
        source = INBOX.observations_to_candidate_source(events + [duplicate], self.ledger)
        ranker = INBOX.load_ranker()
        candidate = next(item for item in source["candidates"] if item["topic_key"] == "policy-inventory-first")
        self.assertEqual(len(ranker.qualified_source_groups(candidate)), 2)

    def test_repeat_confirmation_is_human_only(self) -> None:
        event = INBOX.build_observation(self.capture_args(repeat_confirmed=True, cluster_reviewed=True))
        self.assertEqual(event["repeat_confirmation"], "human_confirmed")
        event["created_by"] = "deterministic_adapter"
        errors = INBOX.observation_errors(event)
        self.assertTrue(any("repeat confirmation" in error for error in errors))

    def test_generated_candidate_snapshot_reuses_existing_ranker(self) -> None:
        events = self.fixture_events()
        source = INBOX.observations_to_candidate_source(events, self.ledger)
        ranker = INBOX.load_ranker()
        self.assertEqual(ranker.candidate_errors(source, check_paths=True), [])
        ranking = ranker.ranked_payload(source)
        self.assertEqual(ranking["selected_topic_key"], "policy-inventory-first")
        policy = ranking["ranking"][0]
        self.assertEqual(policy["qualified_evidence_group_count"], 2)

    def test_qualification_separates_strategy_gap_from_ready_topic(self) -> None:
        events = self.fixture_events()
        source = INBOX.observations_to_candidate_source(events, self.ledger)
        ranking = INBOX.load_ranker().ranked_payload(source)
        result = INBOX.qualification_payload(ranking, events)
        self.assertEqual(result["recommended_topic_key"], "policy-inventory-first")
        strategy = next(item for item in result["items"] if item["topic_key"] == "kos-cold-start-question-gap")
        self.assertEqual(strategy["qualification_status"], "candidate_only")

    def test_bundle_is_deterministic_and_manual_only(self) -> None:
        self.fixture_events()
        first = INBOX.build_bundle(self.ledger, self.output)
        second = INBOX.build_bundle(self.ledger, self.output)
        self.assertEqual(first["manifest_sha256"], second["manifest_sha256"])
        self.assertEqual(second["status"], "already_completed")
        manifest = json.loads((self.output / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["boundaries"]["publication"], "manual-only")
        self.assertFalse(manifest["boundaries"]["knowledge_base_scanned"])
        qualification = json.loads((self.output / "qualified-topics.json").read_text(encoding="utf-8"))
        self.assertEqual(qualification["recommended_topic_key"], "policy-inventory-first")

    def test_input_drift_fails_closed(self) -> None:
        events = self.fixture_events()
        INBOX.build_bundle(self.ledger, self.output)
        events[0]["deidentified_question"] += "（变化）"
        events[0]["normalized_question"] = INBOX.normalize_question(events[0]["deidentified_question"])
        self.ledger.write_text("\n".join(INBOX.canonical_json(event) for event in events) + "\n", encoding="utf-8")
        with self.assertRaises(INBOX.DiscoveryError) as raised:
            INBOX.validate_bundle(self.output)
        self.assertEqual(raised.exception.code, "input_ledger_drift")


if __name__ == "__main__":
    unittest.main()
