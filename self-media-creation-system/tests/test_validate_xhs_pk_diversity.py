"""Offline unit tests for validate_xhs_pk_diversity using synthetic RGB arrays."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

try:
    import numpy as np
except ImportError as exc:
    raise unittest.SkipTest(f"Optional CV dependency not installed: {exc}") from exc
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from validate_xhs_pk_diversity import (  # noqa: E402
    VALID_ARCHETYPES,
    compute_spatial_gradient_signature,
    validate_xhs_pk_quartet,
)


def _make_orthogonal_synthetic_quartet() -> list[np.ndarray]:
    """Build 4 synthetic 320x320 RGB images occupying disjoint HSV bins and quadrants."""
    imgs: list[np.ndarray] = []

    # Slot 0: Red high-V/high-S backdrop + top-left vertical stripes (hue~0, s_bin=7, v_bin=7)
    im0 = np.full((320, 320, 3), [240, 20, 20], dtype=np.uint8)
    for x in range(0, 140, 8):
        im0[0:140, x : x + 4] = [250, 22, 22]
    # Add high-contrast pattern strictly inside top-left quadrant using inverted brightness edge only locally
    im0[20:120, 20:120:8] = [230, 18, 18]
    im0[20:120, 24:120:8] = [10, 10, 10]
    imgs.append(im0)

    # Slot 1: Green mid-V/mid-S backdrop + top-right checkerboard (hue=60, s_bin=4, v_bin=5)
    im1 = np.full((320, 320, 3), [75, 175, 75], dtype=np.uint8)
    for y in range(20, 120, 16):
        for x in range(200, 300, 16):
            if ((x + y) // 16) % 2 == 0:
                im1[y : y + 12, x : x + 12] = [78, 182, 78]
            else:
                im1[y : y + 12, x : x + 12] = [18, 52, 18]
    imgs.append(im1)

    # Slot 2: Blue low-mid V/S backdrop + bottom-left horizontal bars (hue=120, s_bin=2, v_bin=3)
    im2 = np.full((320, 320, 3), [85, 85, 115], dtype=np.uint8)
    for y in range(200, 300, 8):
        im2[y : y + 4, 20:120] = [30, 30, 58]
    imgs.append(im2)

    # Slot 3: Dark cyan low-V/low-S backdrop + bottom-right grid (hue=90, s_bin=1, v_bin=1)
    im3 = np.full((320, 320, 3), [40, 50, 50], dtype=np.uint8)
    for d in range(200, 300, 12):
        im3[d : d + 6, 200:300] = [15, 22, 22]
        im3[200:300, d : d + 6] = [15, 22, 22]
    imgs.append(im3)

    return imgs


class XhsPkDiversityValidatorTests(unittest.TestCase):
    def test_spatial_gradient_signature_properties(self):
        flat = np.full((160, 160, 3), 128, dtype=np.uint8)
        flat_sig = compute_spatial_gradient_signature(flat)
        self.assertEqual(flat_sig.shape, (16,))
        self.assertAlmostEqual(float(flat_sig.sum()), 0.0, places=5)

        quartet = _make_orthogonal_synthetic_quartet()
        sig0 = compute_spatial_gradient_signature(quartet[0])
        self.assertEqual(sig0.shape, (16,))
        self.assertAlmostEqual(float(sig0.sum()), 1.0, places=5)

    def test_validate_orthogonal_quartet_passes(self):
        quartet = _make_orthogonal_synthetic_quartet()
        res = validate_xhs_pk_quartet(quartet, archetypes=list(VALID_ARCHETYPES))
        self.assertTrue(res["passed"], f"Expected PASS, got: {res}")
        self.assertEqual(res["status"], "PASS")
        self.assertEqual(res["violations"], [])
        self.assertLessEqual(res["max_pairwise_cos"], 0.68)
        self.assertGreaterEqual(res["min_spatial_l1"], 0.40)
        self.assertGreater(res["dpp_diversity_volume"], 0.0)
        self.assertEqual(len(res["pair_matrix"]), 6)

    def test_validate_collapsed_quartet_fails(self):
        base = _make_orthogonal_synthetic_quartet()[0]
        identical = [base.copy() for _ in range(4)]
        res = validate_xhs_pk_quartet(identical, archetypes=list(VALID_ARCHETYPES))
        self.assertFalse(res["passed"])
        self.assertEqual(res["status"], "PK_VARIANCE_COLLAPSE")
        self.assertGreaterEqual(len(res["violations"]), 2)
        self.assertGreater(res["max_pairwise_cos"], 0.68)
        self.assertLess(res["min_spatial_l1"], 0.40)

    def test_validation_argument_errors(self):
        quartet = _make_orthogonal_synthetic_quartet()
        with self.assertRaises(ValueError):
            validate_xhs_pk_quartet(quartet[:3])
        with self.assertRaises(ValueError):
            validate_xhs_pk_quartet(quartet, archetypes=["a", "b", "c"])
        with self.assertRaises(ValueError):
            validate_xhs_pk_quartet(quartet, archetypes=["a", "a", "b", "c"])

    def test_cli_json_output_passes_with_synthetic_pngs(self):
        script = SCRIPTS_DIR / "validate_xhs_pk_diversity.py"
        quartet = _make_orthogonal_synthetic_quartet()
        with tempfile.TemporaryDirectory() as td:
            paths = []
            for idx, arr in enumerate(quartet):
                p = Path(td) / f"synthetic_slot_{idx}.png"
                Image.fromarray(arr).save(p)
                paths.append(str(p))

            proc = subprocess.run(
                [sys.executable, "-X", "utf8", "-B", str(script), *paths, "--json"],
                capture_output=True, text=True, encoding="utf-8", check=True,
            )
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["status"], "PASS")
            self.assertTrue(payload["passed"])
            self.assertEqual(len(payload["violations"]), 0)


if __name__ == "__main__":
    unittest.main()
