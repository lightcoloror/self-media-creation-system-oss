"""Unit tests for visual overflow calculation and platform safe-zone SVG generation."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from calculate_visual_overflow import calculate_visual_overflow, test_overflow_cases  # noqa: E402
from generate_safe_zone_svg import generate_svg_overlay, get_default_platform_overlays  # noqa: E402


class VisualOverflowTests(unittest.TestCase):
    def test_stroke_alignments(self):
        center = calculate_visual_overflow(stroke_width=10.0, stroke_alignment="center")
        outside = calculate_visual_overflow(stroke_width=10.0, stroke_alignment="outside")
        inside = calculate_visual_overflow(stroke_width=10.0, stroke_alignment="inside")

        self.assertEqual(center.left, 11)  # 5 + 2 + 4
        self.assertEqual(outside.left, 16)  # 10 + 2 + 4
        self.assertEqual(inside.left, 6)  # 0 + 2 + 4
        self.assertGreater(outside.max_padding, center.max_padding)
        self.assertGreater(center.max_padding, inside.max_padding)

    def test_directional_shadow_offsets_and_spread(self):
        pos = calculate_visual_overflow(
            stroke_width=0.0,
            shadow_blur=10.0,
            shadow_offset_x=6.0,
            shadow_offset_y=8.0,
            shadow_spread=3.0,
        )
        self.assertGreater(pos.right, pos.left)
        self.assertGreater(pos.bottom, pos.top)
        self.assertEqual(pos.max_padding, max(pos.left, pos.right, pos.top, pos.bottom))

        neg = calculate_visual_overflow(
            stroke_width=0.0,
            shadow_blur=10.0,
            shadow_offset_x=-6.0,
            shadow_offset_y=-8.0,
            shadow_spread=3.0,
        )
        self.assertGreater(neg.left, neg.right)
        self.assertGreater(neg.top, neg.bottom)

    def test_rounding_ceil_and_builtin_cases(self):
        r = calculate_visual_overflow(stroke_width=3.0, antialias_padding=2.0, extra_padding=4.0)
        # stroke_outward = 1.5 -> + 6.0 = 7.5 -> ceil = 8
        self.assertEqual(r.left, 8)
        self.assertEqual(r.max_padding, 8)
        test_overflow_cases()


class SafeZoneSvgTests(unittest.TestCase):
    def test_default_platform_overlays_loaded_from_config(self):
        config_path = ROOT / "config" / "platform-cover-overlays.v1.json"
        self.assertTrue(config_path.is_file())
        data = json.loads(config_path.read_text(encoding="utf-8"))
        self.assertEqual(data.get("schema"), "self-media.platform-cover-overlays.v1")

        for platform in ("bilibili", "xiaohongshu", "douyin", "weixin_channels"):
            overlays = get_default_platform_overlays(platform)
            self.assertGreater(len(overlays), 0, f"missing overlays for {platform}")
            for item in overlays:
                rect = item["normalizedRect"]
                self.assertEqual(len(rect), 4)
                for coord in rect:
                    self.assertGreaterEqual(coord, 0.0)
                    self.assertLessEqual(coord, 1.0)

        self.assertEqual(get_default_platform_overlays("unknown_platform"), [])

    def test_generate_svg_overlay_elements_and_xml_validity(self):
        exclusions = [
            {
                "id": "top_badge",
                "level": "hard_block",
                "normalizedRect": [0.8, 0.05, 0.15, 0.1],
                "reason": "badge_area",
            },
            {
                "id": "device_edge",
                "level": "device_envelope_warn",
                "normalizedPoints": [[0.0, 0.9], [1.0, 0.9], [1.0, 1.0], [0.0, 1.0]],
            },
            {
                "id": "legacy_box",
                "level": "hard_block",
                "coordinates": [10, 20, 100, 40],
            },
        ]
        faces = [{"id": "subject_1", "points": [[100, 100], [300, 100], [300, 400], [100, 400]]}]

        svg_str = generate_svg_overlay(
            width=1080,
            height=1440,
            exclusions=exclusions,
            face_protections=faces,
            platform_name="xiaohongshu",
            scene_name="Synthesis",
        )
        root = ET.fromstring(svg_str)
        self.assertTrue(root.tag.endswith("svg"))
        self.assertEqual(root.attrib["width"], "1080")
        self.assertEqual(root.attrib["height"], "1440")
        self.assertIn("#EF4444", svg_str)
        self.assertIn("#F59E0B", svg_str)
        self.assertIn("#3B82F6", svg_str)
        self.assertIn("[PROTECTED] subject_1", svg_str)
        self.assertIn("<polygon", svg_str)

    def test_cli_platform_and_cover_ir_modes(self):
        script = SCRIPTS_DIR / "generate_safe_zone_svg.py"
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            out1 = td_path / "bili.svg"
            res1 = subprocess.run(
                [sys.executable, "-X", "utf8", "-B", str(script), "--platform", "bilibili", "--width", "1280", "--height", "720", "--output", str(out1)],
                capture_output=True, text=True, encoding="utf-8", check=True,
            )
            self.assertEqual(res1.returncode, 0)
            root1 = ET.fromstring(out1.read_text(encoding="utf-8"))
            self.assertEqual(root1.attrib["width"], "1280")
            self.assertEqual(root1.attrib["height"], "720")

            ir_path = td_path / "synthetic_cover_ir.json"
            ir_payload = {
                "document": {"canvas": {"width": 900, "height": 1200}},
                "constraints": {
                    "platformSafeZones": {
                        "platform": "douyin",
                        "scene": "TestCard",
                        "exclusions": [
                            {"id": "corner_tag", "level": "hard_block", "normalizedRect": [0.85, 0.02, 0.12, 0.08], "reason": "corner"}
                        ],
                    },
                    "faceProtection": [
                        {"id": "synthetic_face", "points": [[200, 200], [400, 200], [400, 500], [200, 500]]}
                    ],
                },
            }
            ir_path.write_text(json.dumps(ir_payload, ensure_ascii=False), encoding="utf-8")
            out2 = td_path / "from_ir.svg"
            res2 = subprocess.run(
                [sys.executable, "-X", "utf8", "-B", str(script), "--cover-ir", str(ir_path), "--output", str(out2)],
                capture_output=True, text=True, encoding="utf-8", check=True,
            )
            self.assertEqual(res2.returncode, 0)
            svg2 = out2.read_text(encoding="utf-8")
            root2 = ET.fromstring(svg2)
            self.assertEqual(root2.attrib["width"], "900")
            self.assertEqual(root2.attrib["height"], "1200")
            self.assertIn("DOUYIN (TestCard)", svg2)
            self.assertIn("[PROTECTED] synthetic_face", svg2)


if __name__ == "__main__":
    unittest.main()
