import sys
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import cover_depth_fusion as cdf
import cover_design as d
import cover_workbench as w

w.pipeline_import(w.DEFAULT_PIPE)
from video_creation_pipeline.cover_layers import validate_cover_layers
from video_creation_pipeline.errors import ContractError


def _synthetic_studio_plate(width: int = 900, height: int = 1200) -> np.ndarray:
    """Create a synthetic warm-ivory studio plate with a dark centered-lower person silhouette."""
    img = np.full((height, width, 3), (218, 229, 236), dtype=np.uint8)  # warm ivory BGR
    # Dark torso + head rising cleanly to y = 38% (leaves generous top masthead zone)
    cv2.ellipse(img, (int(width * 0.58), int(height * 0.72)), (int(width * 0.24), int(height * 0.30)), 0, 0, 360, (42, 46, 40), -1)
    cv2.circle(img, (int(width * 0.58), int(height * 0.44)), int(width * 0.10), (32, 34, 38), -1)
    # Dark prop on lower-left
    cv2.rectangle(img, (int(width * 0.10), int(height * 0.65)), (int(width * 0.32), int(height * 0.94)), (48, 52, 56), -1)
    return img


class CoverDepthFusionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_depth_fusion_contract_allows_verified_cutout_within_budget_and_blocks_excess(self):
        from test_cover_design import layer_fixture

        plan = layer_fixture("magazine-depth-fusion", "vertical_profile_3_4")
        validate_cover_layers(plan)

        # Exceeding 0.22 max_glyph_occlusion_ratio must fail closed
        bad_occ = layer_fixture("magazine-depth-fusion", "vertical_profile_3_4")
        img_layer = next(x for x in bad_occ["render_spec"]["profile_layouts"]["vertical_profile_3_4"]["cover_layers"]["layers"] if x["type"] == "image")
        img_layer["depth_fusion"]["measured_max_char_occlusion"] = 0.31
        with self.assertRaisesRegex(ContractError, "glyph occlusion"):
            validate_cover_layers(bad_occ)

        # Missing alpha_matte_verified must fail closed
        bad_alpha = layer_fixture("magazine-depth-fusion", "vertical_profile_3_4")
        img_layer2 = next(x for x in bad_alpha["render_spec"]["profile_layouts"]["vertical_profile_3_4"]["cover_layers"]["layers"] if x["type"] == "image")
        img_layer2["depth_fusion"]["alpha_matte_verified"] = False
        with self.assertRaisesRegex(ContractError, "alpha matte"):
            validate_cover_layers(bad_alpha)

        # Adding a later rect that covers protected face region must STILL fail closed
        bad_face = layer_fixture("magazine-depth-fusion", "vertical_profile_3_4")
        layers = bad_face["render_spec"]["profile_layouts"]["vertical_profile_3_4"]["cover_layers"]["layers"]
        layers.append(dict(id="bad-cta", type="rect", box=d.box(0.2, 0.4, 0.5, 0.3), color="#C45638"))
        with self.assertRaisesRegex(ContractError, "protected subject"):
            validate_cover_layers(bad_face)

    def test_measure_text_occlusion_detects_clear_vs_occluded(self):
        alpha = np.zeros((1440, 1080), dtype=np.float32)
        res_clear = cdf.measure_text_occlusion(
            alpha_fg=alpha,
            lines=["降低启动阻力", "踢飞剪辑杂务"],
            font_path=cdf.DEFAULT_FONT_BOLD,
            font_px=150,
            x0=46,
            y_positions=[100, 260],
        )
        self.assertTrue(res_clear["passed"])
        self.assertEqual(res_clear["max_char_occlusion"], 0.0)

        # Block right half of line 2 heavily -> must fail occlusion gate
        alpha[260:420, 620:980] = 1.0
        res_blocked = cdf.measure_text_occlusion(
            alpha_fg=alpha,
            lines=["降低启动阻力", "踢飞剪辑杂务"],
            font_path=cdf.DEFAULT_FONT_BOLD,
            font_px=150,
            x0=46,
            y_positions=[100, 260],
            max_glyph_occlusion_ratio=0.22,
        )
        self.assertFalse(res_blocked["passed"])
        self.assertGreater(res_blocked["max_char_occlusion"], 0.22)

    def test_birefnet_backend_requires_explicit_checkpoint_no_silent_download(self):
        plate = _synthetic_studio_plate(300, 400)
        with self.assertRaises(ValueError):
            cdf.extract_foreground_alpha(plate, backend="birefnet_onnx", model_path=None)
        with self.assertRaises(FileNotFoundError):
            cdf.extract_foreground_alpha(plate, backend="birefnet_onnx", model_path=self.root / "missing.onnx")

    def test_render_four_ratios_from_single_master_with_receipts(self):
        plate_path = self.root / "master.png"
        cdf.save_png(plate_path, _synthetic_studio_plate())

        for ratio in ("3:4", "9:16", "16:9", "4:3"):
            out_png = self.root / f"out_{ratio.replace(':', 'x')}.png"
            rec = cdf.render_magazine_depth_cover(
                master_path=plate_path,
                out_png=out_png,
                ratio=ratio,
                tag="测试｜单母版",
                top_lines=["降低启动阻力", "踢飞剪辑杂务"],
                cta_main="开源直接拿走",
                cta_sub="不搞一键爆款 · 全流程实测",
                matting_backend="studio_cyclorama_lab",
                max_glyph_occlusion_ratio=0.22,
            )
            self.assertTrue(out_png.is_file())
            self.assertTrue(Path(rec["mobile_200px_thumb"]).is_file())
            self.assertTrue(rec["occlusion_audit"]["passed"], f"Ratio {ratio} failed: {rec['occlusion_audit']}")
            self.assertEqual(rec["dimensions"], list(cdf.RATIO_DIMS[ratio]))
            self.assertLessEqual(rec["depth_fusion_contract"]["measured_max_char_occlusion"], 0.22)


if __name__ == "__main__":
    unittest.main()
