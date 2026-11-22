"""Offline unit tests for cover_policy against exported cover_workbench and cover_strategy."""
from __future__ import annotations

import copy
from pathlib import Path
import sys
import tempfile
import unittest

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import cover_policy as policy  # noqa: E402
import cover_workbench as workbench  # noqa: E402


class CoverPolicyTests(unittest.TestCase):
    def test_baked_and_layer_text_validation(self):
        headline = "示例主标题，两个要点怎么看？"
        visible = ["示例主标题，两个要点\n怎么看?", "图表示意"]
        allowed = {"图表示意": "说明图中装饰角标的用途"}
        policy.check_text(visible, headline, allowed, context="cover/3:4")

        for extra in ["AI", "AI 画面", "生成 AI 画面", "无关署名角标", "其他未授权文案"]:
            with self.subTest(extra=extra), self.assertRaisesRegex(ValueError, "unapproved"):
                policy.check_text(visible + [extra], headline, allowed, context="cover/3:4")

        with self.assertRaisesRegex(ValueError, "unapproved"):
            policy.check_text([headline[:-1]], headline, allowed, context="cover/3:4")

        policy.check_text(
            ["视觉对比怎么选？", "AI 生成示意图"],
            "视觉对比怎么选？",
            {"AI生成示意图": "用户明确要求标注该插图"},
            context="cover/3:4",
        )

        plan = dict(
            candidate=dict(candidate_id="cover"),
            render_spec=dict(
                profile_layouts={
                    "vertical_profile_3_4": {
                        "cover_layers": {
                            "layers": [
                                {"type": "text", "role": "overlay", "text": headline},
                                {"type": "text", "role": "attribution", "text": "无关署名角标"},
                            ]
                        }
                    }
                }
            ),
        )
        with self.assertRaisesRegex(ValueError, "unapproved"):
            policy.check_plan_text(plan, headline, allowed)

    def test_check_ratios_preview_and_final_rules(self):
        policy.check_ratios("preview", ["3:4"])
        policy.check_ratios("preview", ["3:4", "9:16"])
        policy.check_ratios("final", list(policy.FINAL_RATIOS))

        with self.assertRaisesRegex(ValueError, "preview_requires_one_or_two"):
            policy.check_ratios("preview", list(policy.FINAL_RATIOS))
        with self.assertRaisesRegex(ValueError, "final_requires_four_cover_ratios"):
            policy.check_ratios("final", ["3:4", "9:16"])
        with self.assertRaisesRegex(ValueError, "duplicate_cover_ratio"):
            policy.check_ratios("preview", ["3:4", "3:4"])
        with self.assertRaisesRegex(ValueError, "invalid_cover_ratios"):
            policy.check_ratios("preview", ["2:1"])

    def test_final_requires_confirmed_style_current_images_and_all_four_ratios(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            images = {}
            for ratio in policy.FINAL_RATIOS:
                a, b = map(int, ratio.split(":"))
                path = root / (ratio.replace(":", "-") + ".png")
                scale = (480 + min(a, b) - 1) // min(a, b)
                Image.new("RGB", (scale * a, scale * b)).save(path)
                images[ratio] = dict(
                    image_ref=workbench.reference(path),
                    visual_passed=True,
                    visible_text=["Synthetic headline?"],
                )

            card = dict(id="A", style_id="perspective", headline="Synthetic headline?", images=images)
            preview = dict(
                schema="self-media.cover-package-review.v1",
                project_id="test-project",
                stage="preview",
                reviewer="fixture",
                candidates=[dict(card, images={"3:4": images["3:4"]})],
            )
            preview_path = root / "preview.json"
            workbench.write(preview_path, preview)
            self.assertEqual(policy.package_check(preview_path)["status"], "preview_reviewed")

            final = dict(
                preview,
                stage="final",
                candidates=[card],
                style_choice=dict(
                    candidate_id="A",
                    user_confirmation="Synthetic fixture choice",
                    preview_package_ref=workbench.reference(preview_path),
                ),
            )
            final_path = root / "final.json"
            workbench.write(final_path, final)
            self.assertEqual(policy.package_check(final_path)["status"], "final_cover_package_complete")

            checks = [
                ("missing", lambda d: d["candidates"][0]["images"].pop("9:16"), "final_requires_four.*9:16"),
                ("replaced-style", lambda d: d["candidates"][0].update(style_id="other"), "style_differs"),
                ("copy", lambda d: d["candidates"][0]["images"]["4:3"]["visible_text"].append("AI 画面"), "unapproved"),
                ("unchecked", lambda d: d["candidates"][0]["images"]["16:9"].pop("visible_text"), "visible_text_review_required"),
            ]
            for name, change, message in checks:
                changed = copy.deepcopy(final)
                change(changed)
                path = root / (name + ".json")
                workbench.write(path, changed)
                with self.subTest(name=name), self.assertRaisesRegex(ValueError, message):
                    policy.package_check(path)

            Path(images["4:3"]["image_ref"]["path"]).write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "changed_artifact"):
                policy.package_check(final_path)


if __name__ == "__main__":
    unittest.main()
