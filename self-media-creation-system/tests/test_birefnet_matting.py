"""Offline unit tests for birefnet_matting deterministic fallback, decontamination, and bbox geometry."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from birefnet_matting import (  # noqa: E402
    compute_subject_bbox,
    decontaminate_edges,
    preprocess_image,
    run_matting,
    sigmoid,
)


def _synthetic_portrait_rgb(w: int = 320, h: int = 400) -> Image.Image:
    arr = np.full((h, w, 3), [30, 60, 120], dtype=np.uint8)
    arr[60:360, 90:230] = [210, 175, 155]
    return Image.fromarray(arr, mode="RGB")


class BiRefNetMattingTests(unittest.TestCase):
    def test_sigmoid_and_preprocess_shapes(self):
        vals = sigmoid(np.array([-10.0, 0.0, 10.0], dtype=np.float32))
        self.assertAlmostEqual(float(vals[1]), 0.5, places=6)
        self.assertGreater(float(vals[0]), 0.0)
        self.assertLess(float(vals[2]), 1.0)

        img = _synthetic_portrait_rgb(240, 320)
        tensor, orig_size = preprocess_image(img, target_size=(128, 128))
        self.assertEqual(orig_size, (240, 320))
        self.assertEqual(tensor.shape, (1, 3, 128, 128))
        self.assertEqual(tensor.dtype, np.float32)

    def test_decontaminate_edges_and_bbox_metrics(self):
        img = _synthetic_portrait_rgb(200, 300)
        arr_a = np.zeros((300, 200), dtype=np.uint8)
        arr_a[40:260, 50:150] = 255
        alpha = Image.fromarray(arr_a, mode="L")

        rgba = decontaminate_edges(img, alpha)
        self.assertEqual(rgba.mode, "RGBA")
        self.assertEqual(rgba.size, (200, 300))

        meta = compute_subject_bbox(alpha)
        self.assertEqual(meta["bbox"], [50, 40, 99, 219])
        self.assertEqual(len(meta["normalizedBbox"]), 4)
        self.assertGreater(meta["area_ratio"], 0.3)
        self.assertGreater(meta["chest_anchor_y"], meta["head_top_y"])

        empty_meta = compute_subject_bbox(Image.new("L", (100, 100), 0))
        self.assertEqual(empty_meta["area_ratio"], 0.0)
        self.assertEqual(empty_meta["bbox"], [0, 0, 100, 100])

    def test_run_matting_offline_fallback_and_cli_json(self):
        script = SCRIPTS_DIR / "birefnet_matting.py"
        with tempfile.TemporaryDirectory() as td:
            td_p = Path(td)
            in_png = td_p / "input.png"
            out_a = td_p / "out_decontam.png"
            out_b = td_p / "out_raw.png"
            _synthetic_portrait_rgb(240, 320).save(in_png)

            rec_a = run_matting(in_png, out_a, model_path=None, decontaminate=True)
            self.assertEqual(rec_a["schema"], "self-media.birefnet-matting-receipt.v1")
            self.assertEqual(rec_a["engine"], "Synthetic_Deterministic_Fallback")
            self.assertTrue(rec_a["decontaminated"])
            self.assertTrue(out_a.is_file())
            with Image.open(out_a) as im_a:
                self.assertEqual(im_a.mode, "RGBA")
                self.assertEqual(im_a.size, (240, 320))

            proc = subprocess.run(
                [sys.executable, "-X", "utf8", "-B", str(script), str(in_png), "-o", str(out_b), "--no-decontaminate", "--json"],
                capture_output=True, text=True, encoding="utf-8", check=True,
            )
            rec_b = json.loads(proc.stdout)
            self.assertFalse(rec_b["decontaminated"])
            self.assertEqual(rec_b["engine"], "Synthetic_Deterministic_Fallback")
            self.assertTrue(out_b.is_file())


if __name__ == "__main__":
    unittest.main()
