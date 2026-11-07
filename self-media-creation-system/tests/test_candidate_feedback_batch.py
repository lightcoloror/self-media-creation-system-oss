from __future__ import annotations

import copy
import shutil
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import candidate_feedback_batch as batch  # noqa: E402


TEST_OUTPUT = ROOT / ".runtime" / "candidate-feedback-batch-test"
FIXTURE_ROOT = ROOT / ".runtime" / "candidate-feedback-batch-fixture"
PLAN = FIXTURE_ROOT / "candidate-feedback-batch-plan.v1.json"
ACCOUNT = ROOT / "fixtures" / "vibe-living-synthetic-loop-v1" / "account.json"
CANDIDATE_TEMPLATE = (
    ROOT
    / "fixtures"
    / "vibe-living-synthetic-loop-v1"
    / "questions"
    / "claims-preparation"
    / "draft.content-item.json"
)


def repo_ref(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def observations(published_day: int, mode: str) -> list[dict]:
    base_layers = {
        "admission": "not_observed",
        "attraction": "not_observed",
        "consumption": "not_observed",
        "value": "not_observed",
        "negative_feedback": "not_observed",
        "business": "not_observed",
    }
    if mode == "no-signal":
        early_layers = dict(base_layers)
        d7_layers = dict(base_layers)
        completeness = "unavailable"
        early_metrics: list[dict] = []
        d7_metrics: list[dict] = []
        business_events: list[dict] = []
    else:
        early_layers = {key: "observed" for key in base_layers}
        d7_layers = dict(early_layers)
        if mode == "content-only":
            early_layers["business"] = "not_observed"
            d7_layers["business"] = "not_observed"
            business_events = []
        else:
            business_events = [
                {
                    "event_type": "continued_consultation",
                    "event_ref": f"synthetic-event:continued-consultation-{published_day}",
                    "occurred_at": f"2026-08-{published_day + 2:02d}T20:00:00+08:00",
                }
            ]
        completeness = "complete"
        early_metrics = [
            {"layer": "attraction", "metric_key": "views", "value": 41, "unit": "count"},
            {"layer": "consumption", "metric_key": "retention_3s_rate", "value": 78, "unit": "percent"},
            {"layer": "value", "metric_key": "saves", "value": 3, "unit": "count"},
        ]
        d7_metrics = [
            {"layer": "attraction", "metric_key": "views", "value": 76, "unit": "count"},
            {"layer": "consumption", "metric_key": "retention_3s_rate", "value": 79, "unit": "percent"},
            {"layer": "value", "metric_key": "saves", "value": 6, "unit": "count"},
        ]
    return [
        {
            "window_label": "early",
            "as_of": f"2026-08-{published_day + 2:02d}T22:00:00+08:00",
            "captured_at": f"2026-08-{published_day + 2:02d}T22:10:00+08:00",
            "data_completeness": completeness,
            "layers": early_layers,
            "metrics": early_metrics,
            "business_events": business_events,
        },
        {
            "window_label": "d7",
            "as_of": f"2026-08-{published_day + 7:02d}T10:00:00+08:00",
            "captured_at": f"2026-08-{published_day + 7:02d}T10:10:00+08:00",
            "data_completeness": completeness,
            "layers": d7_layers,
            "metrics": d7_metrics,
            "business_events": business_events,
        },
    ]


class CandidateFeedbackBatchTests(unittest.TestCase):
    def setUp(self) -> None:
        for path in (FIXTURE_ROOT, TEST_OUTPUT):
            if path.exists():
                shutil.rmtree(path)
        FIXTURE_ROOT.mkdir(parents=True)
        candidate_pack = FIXTURE_ROOT / "CANDIDATE-PACK.md"
        candidate_pack.write_text(
            "# Synthetic candidate pack\n\nOffline fixture only; no account or platform action.\n",
            encoding="utf-8",
            newline="\n",
        )
        candidate_receipt = FIXTURE_ROOT / "candidate-receipt.json"
        batch.write_json(
            candidate_receipt,
            {
                "schema_version": "synthetic-candidate-receipt.v1",
                "synthetic_only": True,
                "external_action_performed": False,
            },
        )
        item_specs = [
            (
                "policy-inventory",
                "topic_1RNQ220TWEF0K9RGMTYS1B47WB",
                "家里买过好几份保险，怎么整理才不容易漏？",
                "Synthetic reader needs a non-product-first way to inventory family policies.",
                1,
                "no-signal",
            ),
            (
                "claim-contact",
                "topic_8M8Q9T4FAA15S6H55ZTVND7VQ7",
                "人身险出险后，第一通电话到底该打给谁？",
                "Synthetic reader needs a safe first-step framework after an incident.",
                2,
                "content-only",
            ),
            (
                "medical-vs-critical",
                "topic_039PT6M02YFA0WE7PSW17NC6C6",
                "医疗险和重疾险，只能二选一吗？",
                "Synthetic reader needs a framework for distinguishing two insurance roles.",
                3,
                "business-signal",
            ),
        ]
        items: list[dict] = []
        template = batch.load_json(CANDIDATE_TEMPLATE)
        for key, topic_id, title, audience_problem, day, mode in item_specs:
            source = FIXTURE_ROOT / "candidates" / key
            candidate_path = source / "canonical-content-candidate.json"
            run_manifest_path = source / "run-manifest.json"
            review_packet_path = source / "review-packet.json"
            candidate = copy.deepcopy(template)
            candidate["content_id"] = f"synthetic-feedback-{key}"
            candidate["title"] = title
            candidate["status"] = "candidate"
            candidate["tags"] = sorted(set(candidate.get("tags", [])) | {"synthetic-only"})
            batch.write_json(candidate_path, candidate)
            batch.write_json(
                run_manifest_path,
                {"schema_version": "synthetic-run-manifest.v1", "synthetic_only": True, "status": "candidate"},
            )
            batch.write_json(
                review_packet_path,
                {"schema_version": "synthetic-review-packet.v1", "synthetic_only": True, "status": "review-required"},
            )
            items.append(
                {
                    "key": key,
                    "topic_id": topic_id,
                    "title": title,
                    "audience_problem": audience_problem,
                    "candidate_ref": repo_ref(candidate_path),
                    "candidate_sha256": batch.sha256_file(candidate_path),
                    "run_manifest_ref": repo_ref(run_manifest_path),
                    "run_manifest_sha256": batch.sha256_file(run_manifest_path),
                    "review_packet_ref": repo_ref(review_packet_path),
                    "review_packet_sha256": batch.sha256_file(review_packet_path),
                    "publication": {
                        "published_at": f"2026-08-{day:02d}T10:00:00+08:00",
                        "recorded_at": f"2026-08-{day:02d}T10:05:00+08:00",
                        "platform": "synthetic-surface",
                        "title": title,
                        "channel_variant": "synthetic-candidate-feedback-validation",
                        "body_unavailable_reason": (
                            "Synthetic fixture only; no platform body, URL, identifier, account or external action exists."
                        ),
                    },
                    "observations": observations(day, mode),
                }
            )
        batch.write_json(
            PLAN,
            {
                "schema_version": "candidate-feedback-batch-plan.v1",
                "synthetic_only": True,
                "batch_id": "synthetic-candidate-feedback-portable",
                "generated_at": "2026-08-31T10:00:00+08:00",
                "account_template_ref": repo_ref(ACCOUNT),
                "account_template_sha256": batch.sha256_file(ACCOUNT),
                "candidate_pack_ref": repo_ref(candidate_pack),
                "candidate_pack_sha256": batch.sha256_file(candidate_pack),
                "candidate_receipt_ref": repo_ref(candidate_receipt),
                "candidate_receipt_sha256": batch.sha256_file(candidate_receipt),
                "items": items,
            },
        )

    def tearDown(self) -> None:
        for path in (FIXTURE_ROOT, TEST_OUTPUT):
            if path.exists():
                shutil.rmtree(path)

    def test_three_candidates_generate_and_rerun_idempotently(self) -> None:
        result = batch.check(PLAN, TEST_OUTPUT)
        self.assertEqual("passed", result["status"])
        manifest = batch.load_json(TEST_OUTPUT / "candidate-feedback-batch.manifest.v1.json")
        self.assertEqual(3, len(manifest["chains"]))
        self.assertFalse(manifest["boundaries"]["external_action_performed"])
        self.assertFalse(manifest["boundaries"]["crm_write_performed"])
        self.assertFalse(manifest["boundaries"]["real_usage_proof"])
        no_signal = next(item for item in manifest["chains"] if item["key"] == "policy-inventory")
        self.assertEqual("content_no_signal", no_signal["feedback_status"]["content"])
        self.assertEqual("not-observed", no_signal["feedback_status"]["business"])

    def test_candidate_hash_drift_is_fail_closed(self) -> None:
        plan = batch.load_json(PLAN)
        plan["items"][0]["candidate_sha256"] = "0" * 64
        with self.assertRaisesRegex(batch.BatchError, "expected") as raised:
            batch.validate_plan(plan)
        self.assertEqual("candidate_hash_drift", raised.exception.code)

    def test_platform_drift_and_early_window_drift_are_rejected(self) -> None:
        plan = batch.load_json(PLAN)
        platform_drift = copy.deepcopy(plan)
        platform_drift["items"][0]["publication"]["platform"] = "wrong-synthetic-surface"
        with self.assertRaises(batch.BatchError) as platform_error:
            batch.validate_plan(platform_drift)
        self.assertEqual("platform_reference_drift", platform_error.exception.code)

        early_drift = copy.deepcopy(plan)
        early_drift["items"][0]["observations"][0]["as_of"] = "2026-08-02T09:00:00+08:00"
        account, items = batch.validate_plan(early_drift)
        item, candidate = items[0]
        source = TEST_OUTPUT / "scratch"
        source.mkdir(parents=True)
        topic = batch.build_topic(item, account["account_id"], early_drift["generated_at"])
        content = batch.build_content(item, candidate, account["account_id"])
        batch.write_json(source / "account.json", account)
        batch.write_json(source / "topic.json", topic)
        batch.write_json(source / "content-item.json", content)
        entry = batch.build_tracker_input(item, source, account, topic, content)
        with self.assertRaises(batch.tracker.TrackerError) as early_error:
            batch.tracker.validate_input(entry)
        self.assertEqual("window_drift", early_error.exception.code)

    def test_manual_receipt_cannot_claim_external_action(self) -> None:
        batch.generate(PLAN, TEST_OUTPUT)
        manifest_path = TEST_OUTPUT / "candidate-feedback-batch.manifest.v1.json"
        manifest = batch.load_json(manifest_path)
        manifest["chains"][0]["manual_receipt"]["external_action_performed"] = True
        batch.write_json(manifest_path, manifest)
        with self.assertRaises(batch.BatchError) as raised:
            batch.validate(TEST_OUTPUT)
        self.assertEqual("external_action_forbidden", raised.exception.code)


if __name__ == "__main__":
    unittest.main()
