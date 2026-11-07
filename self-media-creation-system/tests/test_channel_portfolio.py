from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_channel_portfolio.py"
SPEC = importlib.util.spec_from_file_location("check_channel_portfolio", SCRIPT)
assert SPEC and SPEC.loader
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)

SYNTHETIC_PORTFOLIO = ROOT / "fixtures" / "channel-portfolio.v1.synthetic.json"

DIAGNOSIS_SCRIPT = ROOT / "scripts" / "content_diagnosis.py"
DIAGNOSIS_SPEC = importlib.util.spec_from_file_location("content_diagnosis_platform_coverage", DIAGNOSIS_SCRIPT)
assert DIAGNOSIS_SPEC and DIAGNOSIS_SPEC.loader
DIAGNOSIS = importlib.util.module_from_spec(DIAGNOSIS_SPEC)
DIAGNOSIS_SPEC.loader.exec_module(DIAGNOSIS)


class ChannelPortfolioTests(unittest.TestCase):
    def test_missing_operator_portfolio_is_blocked_and_example_is_not_approval(self) -> None:
        self.assertFalse(CHECK.PORTFOLIO_PATH.exists())
        self.assertTrue(any("not configured" in error for error in CHECK.validate()))
        example = CHECK.load_json(SYNTHETIC_PORTFOLIO)
        self.assertEqual(example["status"], "superseded")
        self.assertFalse(any(row["status"] == "user-confirmed" for row in example["source_refs"]))

    def test_portfolio_is_consistent_with_existing_router(self) -> None:
        self.assertEqual(CHECK.validate(CHECK.load_json(SYNTHETIC_PORTFOLIO)), [])

    def test_stable_cli_passes(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(SCRIPT), "--portfolio", str(SYNTHETIC_PORTFOLIO)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("PASS: channel portfolio", completed.stdout)

    def test_canonical_twelve_platforms_are_covered_once(self) -> None:
        loaded = CHECK.CANONICAL_ROUTING.load_contracts()
        portfolio = CHECK.load_json(SYNTHETIC_PORTFOLIO)
        canonical = set(loaded["components"]["task_router"]["enums"]["platform"])
        covered = [entry["platform"] for entry in portfolio["channels"]]
        self.assertEqual(len(canonical), 12)
        self.assertEqual(len(covered), 12)
        self.assertEqual(set(covered), canonical)

    def test_synthetic_priority_lanes_and_public_limit_are_consistent(self) -> None:
        portfolio = CHECK.load_json(SYNTHETIC_PORTFOLIO)
        by_platform = {entry["platform"]: entry for entry in portfolio["channels"]}
        self.assertEqual(by_platform["wechat-moments"]["priority"], "P0")
        self.assertEqual(by_platform["xiaohongshu"]["priority"], "P0")
        self.assertEqual(by_platform["wechat-video"]["priority"], "P1")
        self.assertEqual(by_platform["wechat-article"]["priority"], "P2")
        self.assertEqual(by_platform["bilibili"]["priority"], "P2")
        self.assertEqual(by_platform["douyin"]["priority"], "pause")
        self.assertEqual(portfolio["weekly_core_unit"]["public_adaptation_max"], 2)
        self.assertEqual(
            portfolio["weekly_core_unit"]["public_adaptation_max_scope"],
            "distinct-platform-variants-only-excludes-identical-frozen-master-sync",
        )
        self.assertEqual(portfolio["publication_boundary"], "manual-only")

    def test_synthetic_sync_state_covers_five_video_platforms(self) -> None:
        portfolio = CHECK.load_json(SYNTHETIC_PORTFOLIO)
        expected = {"xiaohongshu", "wechat-video", "douyin", "kuaishou", "bilibili"}
        self.assertEqual(portfolio["current_stage"]["distribution_mode"], "manual-synchronized-frozen-master")
        self.assertEqual(set(portfolio["current_stage"]["synchronized_public_platforms"]), expected)
        active = {
            item["platform"]
            for item in portfolio["channels"]
            if item["current_distribution_status"] == "active-synchronized-master"
        }
        self.assertEqual(active, expected)
        self.assertEqual(
            portfolio["weekly_core_unit"]["same-copy-cross-posting"],
            "manual-synchronized-frozen-master",
        )

    def test_current_sync_set_drift_fails_closed(self) -> None:
        portfolio = CHECK.load_json(SYNTHETIC_PORTFOLIO)
        candidate = copy.deepcopy(portfolio)
        candidate["current_stage"]["synchronized_public_platforms"].remove("bilibili")
        errors = CHECK.validate(candidate)
        self.assertTrue(any("synchronized" in error for error in errors), errors)

    def test_every_example_platform_has_no_execution_or_runtime_authority(self) -> None:
        portfolio = CHECK.load_json(SYNTHETIC_PORTFOLIO)
        for entry in portfolio["channels"]:
            runtime = entry["acquisition_runtime"]
            self.assertEqual(runtime["execution_authority"], "none", entry["platform"])
            self.assertEqual(runtime["account_access"], "not-authorized", entry["platform"])
            self.assertTrue(runtime["boundary_note"], entry["platform"])
            self.assertTrue(runtime["evidence_ref"], entry["platform"])
        video = next(entry for entry in portfolio["channels"] if entry["platform"] == "wechat-video")
        self.assertEqual(video["acquisition_runtime"]["runtime_status"], "not-verified")
        self.assertEqual(video["acquisition_runtime"]["real_media_download"], "not-authorized")

    def test_all_canonical_platforms_are_accepted_by_the_diagnosis_input(self) -> None:
        base = json.loads((ROOT / "fixtures" / "content-bundle.v1.fixture.json").read_text(encoding="utf-8"))
        canonical = sorted(DIAGNOSIS.PLATFORMS)
        self.assertEqual(len(canonical), 12)
        for platform in canonical:
            candidate = copy.deepcopy(base)
            candidate["platform"] = platform
            self.assertEqual(DIAGNOSIS.validate_bundle(candidate), [], platform)

    def test_unknown_platform_still_fails_closed(self) -> None:
        base = json.loads((ROOT / "fixtures" / "content-bundle.v1.fixture.json").read_text(encoding="utf-8"))
        base["platform"] = "unregistered-synthetic-platform"
        self.assertIn(
            "platform is not supported by the current task-router contract",
            DIAGNOSIS.validate_bundle(base),
        )

    def test_execution_authority_and_account_access_escalation_fail(self) -> None:
        portfolio = CHECK.load_json(SYNTHETIC_PORTFOLIO)
        execution = copy.deepcopy(portfolio)
        execution["channels"][0]["acquisition_runtime"]["execution_authority"] = "publish"
        self.assertTrue(any("execution_authority" in error for error in CHECK.validate(execution)))

        account = copy.deepcopy(portfolio)
        account["channels"][0]["acquisition_runtime"]["account_access"] = "authorized"
        self.assertTrue(any("account_access" in error for error in CHECK.validate(account)))

    def test_wechat_video_real_runtime_overclaim_fails(self) -> None:
        portfolio = CHECK.load_json(SYNTHETIC_PORTFOLIO)
        candidate = copy.deepcopy(portfolio)
        video = next(entry for entry in candidate["channels"] if entry["platform"] == "wechat-video")
        video["acquisition_runtime"]["runtime_status"] = "available-with-boundaries"
        self.assertIn("acquisition/runtime fixture drift: wechat-video", CHECK.validate(candidate))

    def test_unknown_portfolio_platform_fails_closed(self) -> None:
        portfolio = CHECK.load_json(SYNTHETIC_PORTFOLIO)
        candidate = copy.deepcopy(portfolio)
        candidate["channels"][0]["platform"] = "unregistered-synthetic-platform"
        self.assertIn(
            "channel portfolio must cover every task-router platform exactly once",
            CHECK.validate(candidate),
        )

    def test_public_adaptation_limit_escalation_fails(self) -> None:
        portfolio = CHECK.load_json(SYNTHETIC_PORTFOLIO)
        candidate = copy.deepcopy(portfolio)
        candidate["weekly_core_unit"]["public_adaptation_max"] = 3
        errors = CHECK.validate(candidate)
        self.assertTrue(any("public_adaptation_max" in error for error in errors), errors)
        self.assertIn(
            "public adaptation max must remain aligned with the canonical limit of two",
            errors,
        )

    def test_publication_authority_escalation_fails(self) -> None:
        portfolio = CHECK.load_json(SYNTHETIC_PORTFOLIO)
        candidate = copy.deepcopy(portfolio)
        candidate["publication_boundary"] = "automatic"
        errors = CHECK.validate(candidate)
        self.assertTrue(any("publication_boundary" in error for error in errors), errors)
        self.assertIn("publication boundary must remain manual-only", errors)


if __name__ == "__main__":
    unittest.main()
