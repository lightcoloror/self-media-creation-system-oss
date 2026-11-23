"""Offline unit tests for generate_contact_sheet using synthetic RGB covers."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

try:
    import cv2
    import numpy as np
except ImportError as exc:
    raise unittest.SkipTest(f"Optional CV dependency not installed: {exc}") from exc
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from generate_contact_sheet import (  # noqa: E402
    build_contact_sheet,
    evaluate_180px_legibility_gates,
    get_default_font,
    load_platform_overlays,
    render_panel_grayscale,
    render_panel_overlay,
    render_panel_thumbnail,
    srgb_to_relative_luminance,
)


def _make_synthetic_high_contrast_cover(width: int = 720, height: int = 960) -> np.ndarray:
    """Create a synthetic high-contrast cover poster with bold broad features that survive 180px downscale."""
    img = Image.new("RGB", (width, height), (18, 26, 46))
    draw = ImageDraw.Draw(img)
    # Bright banner occupying upper title area (~25% of canvas) and large bright accent card below (~25% of canvas)
    draw.rounded_rectangle(
        [int(width * 0.08), int(height * 0.08), int(width * 0.92), int(height * 0.34)],
        radius=24,
        fill=(242, 245, 248),
    )
    font = get_default_font(max(36, width // 9))
    draw.text((int(width * 0.14), int(height * 0.15)), "COVER CHECK", fill=(15, 23, 42), font=font)
    draw.rounded_rectangle(
        [int(width * 0.12), int(height * 0.50), int(width * 0.88), int(height * 0.80)],
        radius=24,
        fill=(225, 232, 240),
    )
    arr = np.array(img, dtype=np.uint8)
    # Mild anti-aliasing comparable to rendered vector graphics so 180px WebP roundtrip retains Laplacian energy
    return cv2.GaussianBlur(arr, (5, 5), 1.2)


class ContactSheetTests(unittest.TestCase):
    def test_srgb_to_relative_luminance(self):
        black = np.zeros((4, 4, 3), dtype=np.uint8)
        white = np.full((4, 4, 3), 255, dtype=np.uint8)
        self.assertAlmostEqual(float(srgb_to_relative_luminance(black).mean()), 0.0, places=6)
        self.assertAlmostEqual(float(srgb_to_relative_luminance(white).mean()), 1.0, places=5)

    def test_evaluate_180px_legibility_gates_pass_and_low_contrast_fail(self):
        high = _make_synthetic_high_contrast_cover()
        res_pass = evaluate_180px_legibility_gates(high, expected_headline="")
        self.assertTrue(res_pass["passed"], f"Expected high-contrast PASS, got {res_pass}")
        self.assertGreaterEqual(res_pass["local_wcag_contrast"], 3.0)
        self.assertGreaterEqual(res_pass["hf_counter_survival"], 0.15)

        flat = np.full((480, 360, 3), [120, 120, 120], dtype=np.uint8)
        res_fail = evaluate_180px_legibility_gates(flat, expected_headline="")
        self.assertFalse(res_fail["passed"])
        self.assertLess(res_fail["local_wcag_contrast"], 3.0)

    def test_load_platform_overlays_and_panel_renderers(self):
        for plat in ("bilibili", "xiaohongshu", "douyin", "weixin_channels"):
            overlays = load_platform_overlays(plat)
            self.assertGreater(len(overlays), 0)
        self.assertEqual(load_platform_overlays("unknown_platform"), [])

        base_img = Image.fromarray(_make_synthetic_high_contrast_cover(360, 480))
        ov_img, warnings = render_panel_overlay(base_img, load_platform_overlays("bilibili"))
        self.assertEqual(ov_img.size, (360, 480))
        self.assertGreater(len(warnings), 0)

        thumb_img = render_panel_thumbnail(base_img, target_thumb_w=180)
        self.assertEqual(thumb_img.size, (360, 480))

        gray_img, ratio = render_panel_grayscale(base_img)
        self.assertEqual(gray_img.size, (360, 480))
        self.assertGreater(ratio, 3.0)

    def test_build_contact_sheet_and_cli_json(self):
        script = SCRIPTS_DIR / "generate_contact_sheet.py"
        with tempfile.TemporaryDirectory() as td:
            td_p = Path(td)
            in_png = td_p / "cover.png"
            out_png = td_p / "sheet.png"
            Image.fromarray(_make_synthetic_high_contrast_cover(720, 960)).save(in_png)

            manifest = build_contact_sheet(in_png, platform_key="xiaohongshu", output_path=out_png)
            self.assertTrue(out_png.is_file())
            self.assertEqual(manifest["schema"], "self-media.cover-contact-sheet-receipt.v1")
            self.assertEqual(manifest["grid"], "2x2")
            self.assertEqual(manifest["metrics"]["verdict"], "PASS")
            with Image.open(out_png) as sheet_im:
                self.assertEqual(sheet_im.size, (720 * 2 + 16 * 3, 960 * 2 + 16 * 3 + 120 + 60))

            cli_out = td_p / "cli_sheet.png"
            proc = subprocess.run(
                [sys.executable, "-X", "utf8", "-B", str(script), str(in_png), "-p", "douyin", "-o", str(cli_out), "--json"],
                capture_output=True, text=True, encoding="utf-8", check=True,
            )
            payload = json.loads(proc.stdout)
            self.assertTrue(cli_out.is_file())
            self.assertEqual(payload["platform"], "douyin")
            self.assertEqual(payload["metrics"]["verdict"], "PASS")


if __name__ == "__main__":
    unittest.main()
