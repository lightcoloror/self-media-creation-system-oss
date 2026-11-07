from __future__ import annotations

import copy
import importlib.util
import shutil
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "high_frequency_topic_loop.py"
SPEC = importlib.util.spec_from_file_location("high_frequency_topic_loop", SCRIPT)
assert SPEC and SPEC.loader
LOOP = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LOOP)


def source_fixture() -> dict:
    return LOOP.load_json(LOOP.CANDIDATES_PATH)


def blueprint_fixture() -> dict:
    return LOOP.load_json(LOOP.BLUEPRINT_PATH)


class HighFrequencyTopicLoopTests(unittest.TestCase):
    def test_synthetic_fixture_passes_contract(self) -> None:
        self.assertEqual(LOOP.package_errors(), [])

    def test_selection_is_deterministic_and_risk_adjusted(self) -> None:
        ranking = LOOP.rank_candidates(source_fixture())
        self.assertEqual(ranking[0]["topic_key"], "synthetic-information-inventory")
        self.assertEqual(ranking[0]["qualified_evidence_group_count"], 2)
        self.assertGreater(ranking[0]["score"], ranking[1]["score"])

    def test_mirror_source_does_not_inflate_frequency(self) -> None:
        source = source_fixture()
        selected = next(item for item in source["candidates"] if item["topic_key"] == "synthetic-information-inventory")
        self.assertEqual(len(LOOP.qualified_source_groups(selected)), 2)
        self.assertEqual(sum(1 for ref in selected["evidence_refs"] if ref["counts_toward_frequency"]), 2)

    def test_raw_occurrence_count_remains_unknown(self) -> None:
        source = source_fixture()
        self.assertTrue(all(item["raw_occurrence_count"] is None for item in source["candidates"]))

    def test_ai_draft_cannot_be_promoted_to_counting_evidence(self) -> None:
        source = source_fixture()
        candidate = next(item for item in source["candidates"] if item["topic_key"] == "synthetic-contrast")
        candidate["evidence_refs"][1]["counts_toward_frequency"] = True
        errors = LOOP.candidate_errors(source, check_paths=False)
        self.assertTrue(any("cannot count unverified or AI evidence" in error for error in errors))

    def test_existing_content_item_schema_is_reused(self) -> None:
        item = LOOP.build_content_item(source_fixture(), blueprint_fixture())
        self.assertEqual(LOOP.content_item_errors(item), [])
        self.assertEqual(item["status"], "draft")
        self.assertEqual(item["publication"]["boundary"], "manual-only")
        self.assertEqual(item["publication"]["receipts"], [])
        self.assertEqual(item["feedback"]["content_signal_status"], "not-observed")
        self.assertEqual(item["feedback"]["business_signal_status"], "not-observed")

    def test_ranking_does_not_inject_verified_history_or_official_claims(self) -> None:
        source = source_fixture()
        self.assertEqual(source["source_scope"], "synthetic-only")
        item = LOOP.build_content_item(source, blueprint_fixture())
        self.assertEqual(item["provenance"]["verified_facts"], [])
        self.assertFalse(any(row["source_type"] == "official-web" for row in item["provenance"]["sources"]))
        self.assertTrue(all(row["evidence_status"] == "unverified" for row in item["provenance"]["sources"]))
        self.assertEqual(item["gates"]["fact"]["status"], "needs-review")
        self.assertEqual(item["qa"]["human_review"]["status"], "required")
        # Even rank labels that simulate human confirmation cannot verify facts.
        source["candidates"][0]["question"] = "An unrelated invented topic"
        changed = LOOP.build_content_item(source, blueprint_fixture())
        self.assertEqual(changed["title"], "An unrelated invented topic")
        self.assertEqual(changed["provenance"]["verified_facts"], [])


    def test_unconfirmed_service_expression_is_non_blocking_self_help_copy(self) -> None:
        blueprint = blueprint_fixture()
        self.assertIn("不阻塞当前草稿", blueprint["minimum_user_confirmation"]["default_if_unanswered"])
        public = blueprint["public_candidates"][0]
        self.assertNotIn("我提供", public["caption"])
        self.assertNotIn("我的服务", public["caption"])

    def test_public_candidates_are_limited_and_draft_only(self) -> None:
        blueprint = blueprint_fixture()
        duplicate = copy.deepcopy(blueprint["public_candidates"][0])
        blueprint["public_candidates"].extend([duplicate, duplicate])
        errors = LOOP.package_errors(source_fixture(), blueprint, check_paths=False)
        self.assertTrue(any("at most two public candidates" in error for error in errors))

    def test_direct_identifier_is_rejected(self) -> None:
        blueprint = blueprint_fixture()
        blueprint["private_draft"]["body"] += " 联系邮箱 test@example.com"
        errors = LOOP.package_errors(source_fixture(), blueprint, check_paths=False)
        self.assertTrue(any("email" in error for error in errors))

    def test_hash_is_deterministic_and_content_sensitive(self) -> None:
        source = source_fixture()
        self.assertEqual(LOOP.canonical_sha256(source), LOOP.canonical_sha256(copy.deepcopy(source)))
        changed = copy.deepcopy(source)
        changed["candidates"][0]["question"] += "（变更）"
        self.assertNotEqual(LOOP.canonical_sha256(source), LOOP.canonical_sha256(changed))

    def test_generated_bundle_preserves_neutral_no_signal_rule(self) -> None:
        self.assertIn("content_no_signal", LOOP.observation_template())
        self.assertIn("insufficient-evidence", LOOP.day7_template())


if __name__ == "__main__":
    unittest.main()
