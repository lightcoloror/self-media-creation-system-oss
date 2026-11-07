from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "operations_scenario_suite.py"
SPEC = importlib.util.spec_from_file_location("operations_scenario_suite_w10", SCRIPT)
assert SPEC and SPEC.loader
SUITE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SUITE)


class W10G72RegressionEdgeTests(unittest.TestCase):
    def test_tampered_expected_hash_is_rejected(self) -> None:
        matrix = SUITE.load_json(SUITE.DEFAULT_MATRIX)
        matrix["scenarios"][0]["expected_bundle_sha256"] = "0" * 64
        scenario = matrix["scenarios"][0]
        base = SUITE.load_json(SUITE.DEFAULT_MATRIX.parent / matrix["base_fixture"])
        actual_hash = SUITE.canonical_sha256(SUITE.build_scenario_bundle(base, scenario))
        self.assertNotEqual(actual_hash, scenario["expected_bundle_sha256"])

    def test_missing_private_to_public_prefix_is_rejected(self) -> None:
        matrix = SUITE.load_json(SUITE.DEFAULT_MATRIX)
        matrix["scenarios"][0]["journey_trace"] = ["published", "d7-review"]
        errors = SUITE.matrix_shape_errors(matrix)
        self.assertTrue(any("private candidate to public rewrite" in error for error in errors))

    def test_content_no_signal_and_observed_business_can_coexist_without_negative_inference(self) -> None:
        matrix = SUITE.load_json(SUITE.DEFAULT_MATRIX)
        base = SUITE.load_json(SUITE.DEFAULT_MATRIX.parent / matrix["base_fixture"])
        scenario = matrix["scenarios"][2]
        bundle = SUITE.build_scenario_bundle(base, scenario)
        feedback = bundle["content_item"]["feedback"]
        feedback["content_signal_status"] = "content_no_signal"
        for layer in ("attraction", "consumption", "value"):
            review = next(item for item in bundle["reviews"] if item["layer"] == layer)
            review["signal_status"] = "content_no_signal"
        self.assertEqual(feedback["business_signal_status"], "observed")
        self.assertEqual(SUITE.OPERATIONS.derive_customer_conclusions(feedback), [])
        self.assertEqual(SUITE.OPERATIONS.contract_errors(bundle), [])


if __name__ == "__main__":
    unittest.main()
