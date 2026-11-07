from __future__ import annotations

import csv
import copy
import importlib.util
import json
import shutil
import unittest
from pathlib import Path

from openpyxl import Workbook


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "platform_metrics_intake.py"
SPEC = importlib.util.spec_from_file_location("platform_metrics_intake", SCRIPT)
assert SPEC and SPEC.loader
INTAKE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(INTAKE)


class PlatformMetricsIntakeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = ROOT / "tests" / ".runtime" / "platform-metrics-intake" / self._testMethodName
        shutil.rmtree(self.root, ignore_errors=True)
        self.root.mkdir(parents=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def write_xlsx(self, name: str, rows: list[list[object]], title_row: bool = False) -> Path:
        path = self.root / name
        workbook = Workbook()
        sheet = workbook.active
        if title_row:
            sheet.append(["synthetic export"] * len(rows[0]))
        for row in rows:
            sheet.append(row)
        workbook.save(path)
        workbook.close()
        return path

    def write_csv(self, name: str, rows: list[list[object]]) -> Path:
        path = self.root / name
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            csv.writer(handle).writerows(rows)
        return path

    def sources(self) -> dict[str, Path]:
        xhs = self.write_xlsx(
            "xhs.xlsx",
            [
                ["笔记标题", "首次发布时间", "体裁", "曝光", "观看量", "封面点击率", "点赞", "评论", "收藏", "涨粉", "分享", "人均观看时长", "弹幕"],
                ["synthetic note", "2026-09-01 20:00", "视频", 100, 20, 0.035, 2, 1, 3, 1, 1, 18, 0],
            ],
            title_row=True,
        )
        wechat = self.write_csv(
            "wechat.csv",
            [
                ["视频描述", "发布时间", "完播率", "平均播放时长", "播放量", "推荐", "喜欢", "评论量", "分享量", "关注量", "转发聊天和朋友圈"],
                ["synthetic video\nbody omitted", "2026/09/01", "12.5%", "20秒", 200, 4, 2, 1, 1, 1, 1],
            ],
        )
        douyin_items = self.write_xlsx(
            "douyin-items.xlsx",
            [
                ["作品名称", "发布时间", "播放量", "完播率", "5s完播率", "封面点击率", "2s跳出率", "平均播放时长", "点赞量", "分享量", "评论量", "收藏量", "主页访问量", "粉丝增量"],
                ["synthetic douyin item", "2026-09-01 20:00", 300, "0.0125", "0.42", "-", "0.31", "9.5", 3, 1, 1, 2, 4, 1],
            ],
        )
        douyin_daily = self.write_xlsx(
            "douyin-account-daily.xlsx",
            [
                ["日期", "投稿量", "总播放量", "总点赞量", "总分享量", "总评论量", "5秒完播率", "2秒跳出率", "封面点击率", "平均播放时长"],
                ["2026-09-01", 1, 300, 3, 1, 1, "42%", "31%", "4%", "9s"],
            ],
        )
        kuaishou_items = self.write_xlsx(
            "kuaishou-items.xlsx",
            [
                ["作品", "发布时间", "播放量", "完播率", "评论量", "点赞量", "收藏量", "涨粉量"],
                ["synthetic kuaishou item", "2026-09-01 20:00", 400, "--", 1, 4, 2, 1],
            ],
        )
        kuaishou_daily = self.write_xlsx(
            "kuaishou-account-daily.xlsx",
            [
                ["日期", "播放量", "完播率", "净增粉丝量", "评论量", "点赞量", "分享量", "作品量"],
                ["2026-09-01", 400, "0%", -1, 1, 4, 1, 1],
                ["2026-09-02", 500, "0%", 2, 0, 2, 0, 0],
            ],
        )
        bilibili = self.write_csv(
            "bilibili.csv",
            [
                ["视频标题", "发布时间", "播放量", "封标点击率", "粉丝点击率", "游客点击率", "3秒跳出率", "涨粉量", "取关量", "点赞量", "评论量", "弹幕量", "收藏量", "投币量", "转发量", "平均播放进度"],
                ["synthetic bilibili video", "2026-09-01", 80, "2星", "2星", "2星", "30%", 1, 0, 2, 1, 0, 1, 0, 1, "20%"],
            ],
        )
        return {
            "xiaohongshu_items": xhs,
            "wechat_channels_items": wechat,
            "douyin_items": douyin_items,
            "douyin_account_daily": douyin_daily,
            "kuaishou_items": kuaishou_items,
            "kuaishou_account_daily": kuaishou_daily,
            "bilibili_items": bilibili,
        }

    def test_five_platforms_and_seven_export_profiles_preserve_grain_and_semantics(self) -> None:
        value = INTAKE.build_intake(self.sources(), "2026-09-03T18:30:00+08:00")
        INTAKE.validate_intake(value)
        self.assertEqual(7, len(value["sources"]))
        self.assertIn("douyin_account_daily:account-day-data-not-attributed-to-content", value["warnings"])
        self.assertIn("kuaishou_account_daily:completion-rate-all-zero-semantic-confirmation-required", value["warnings"])
        self.assertIn("bilibili_items:non-percent-star-fields-retained-as-unmapped", value["warnings"])
        xhs = next(item for item in value["records"] if item["platform"] == "xiaohongshu")
        click = next(item for item in xhs["metrics"] if item["metric_key"] == "cover_click_rate")
        self.assertEqual(3.5, click["value"])
        dy_item = next(item for item in value["records"] if item["export_profile"] == "douyin_items")
        dy_completion = next(item for item in dy_item["metrics"] if item["metric_key"] == "completion_rate")
        self.assertEqual(1.25, dy_completion["value"])
        self.assertEqual("direct-platform-item", dy_item["attribution_status"])
        ks_item = next(item for item in value["records"] if item["export_profile"] == "kuaishou_items")
        ks_completion = next(item for item in ks_item["metrics"] if item["metric_key"] == "completion_rate")
        self.assertIsNone(ks_completion["value"])
        self.assertEqual("source-empty", ks_completion["semantic_status"])
        ks_daily = next(item for item in value["records"] if item["export_profile"] == "kuaishou_account_daily")
        net = next(item for item in ks_daily["metrics"] if item["metric_key"] == "net_follower_change")
        self.assertEqual(-1, net["value"])
        self.assertEqual("not-attributed-to-content", ks_daily["attribution_status"])

    def test_output_is_deterministic_and_does_not_copy_absolute_paths(self) -> None:
        sources = self.sources()
        first = INTAKE.build_intake(sources, "2026-09-03T18:30:00+08:00")
        second = INTAKE.build_intake(sources, "2026-09-03T18:30:00+08:00")
        self.assertEqual(first, second)
        serialized = json.dumps(first, ensure_ascii=False)
        self.assertNotIn(str(self.root), serialized)
        self.assertTrue(all("/" not in item["basename"] and "\\" not in item["basename"] for item in first["sources"]))

    def test_hash_drift_fails_closed(self) -> None:
        value = INTAKE.build_intake(self.sources(), "2026-09-03T18:30:00+08:00")
        value["records"][0]["metrics"][0]["value"] = 999
        with self.assertRaises(INTAKE.MetricsIntakeError) as caught:
            INTAKE.validate_intake(value)
        self.assertEqual("payload_hash_drift", caught.exception.code)

    def test_account_day_cannot_be_promoted_to_content_attribution(self) -> None:
        value = INTAKE.build_intake(self.sources(), "2026-09-03T18:30:00+08:00")
        item = next(row for row in value["records"] if row["source_grain"] == "account_day")
        item["attribution_status"] = "direct-platform-item"
        unsigned = copy.deepcopy(value)
        unsigned.pop("payload_sha256")
        value["payload_sha256"] = INTAKE.hashlib.sha256(INTAKE.canonical_bytes(unsigned)).hexdigest()
        with self.assertRaises(INTAKE.MetricsIntakeError) as caught:
            INTAKE.validate_intake(value)
        self.assertEqual("content_attribution_inferred", caught.exception.code)

    def test_duplicate_export_profile_source_is_rejected(self) -> None:
        with self.assertRaises(INTAKE.MetricsIntakeError) as caught:
            INTAKE.parse_sources(["douyin_items=a.xlsx", "douyin_items=b.xlsx"])
        self.assertEqual("duplicate_export_profile_source", caught.exception.code)

    def test_legacy_aliases_resolve_to_account_daily_profiles(self) -> None:
        parsed = INTAKE.parse_sources(["douyin=a.xlsx", "kuaishou=b.xlsx"])
        self.assertEqual({"douyin_account_daily", "kuaishou_account_daily"}, set(parsed))

    def template_intake(self, rows):
        path = self.write_csv('official-template.csv', rows)
        return INTAKE.build_intake({'wechat_official_template_v1': path}, '2026-09-17T21:00:00+08:00')

    def template_headers(self):
        return ['format_version', 'source_grain', 'date', 'read_users', 'delivered_users', 'open_rate_percent']

    def test_official_template_preserves_unverified_account_day_scope(self):
        value = self.template_intake([self.template_headers(), ['wechat-account-day-template.v1', 'account_day', '2026-09-17', 20, 100, '20%']])
        row = value['records'][0]
        self.assertEqual('template_only', row['compatibility_status'])
        self.assertEqual('not-attributed-to-content', row['attribution_status'])
        self.assertIsNone(row['content_label'])
        self.assertIn('wechat_official_template_v1:template-only-not-verified-official-export', value['warnings'])

    def test_empty_template_still_validates_headers(self):
        self.assertEqual([], self.template_intake([self.template_headers()])['records'])
        with self.assertRaises(INTAKE.MetricsIntakeError) as caught:
            self.template_intake([['wrong-header']])
        self.assertEqual('template_format_mismatch', caught.exception.code)

    def test_template_rejects_malformed_rows_and_invalid_metrics(self):
        base = ['wechat-account-day-template.v1', 'account_day', '2026-09-17', 20, 100, '20%']
        cases = [(0, 'v2'), (1, 'content_item'), (2, '2026-02-30'), (3, '1.5'), (3, '101'), (3, 'NaN'), (4, '0'), (5, '101%'), (5, '30%')]
        for index, value in cases:
            with self.subTest(index=index, value=value):
                row = base.copy(); row[index] = value
                with self.assertRaises(INTAKE.MetricsIntakeError):
                    self.template_intake([self.template_headers(), row])
        with self.assertRaises(INTAKE.MetricsIntakeError):
            self.template_intake([self.template_headers(), base + ['unexpected']])

    def test_template_unknown_metrics_remain_unknown(self):
        value = self.template_intake([self.template_headers(), ['wechat-account-day-template.v1', 'account_day', '2026-09-17', '-', '-', '-']])
        self.assertTrue(all(m['value'] is None for m in value['records'][0]['metrics']))


if __name__ == "__main__":
    unittest.main()
