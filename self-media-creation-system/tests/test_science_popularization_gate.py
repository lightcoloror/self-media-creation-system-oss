from __future__ import annotations

import copy
import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "science_popularization_gate.py"
SPEC = importlib.util.spec_from_file_location("science_popularization_gate", SCRIPT)
assert SPEC and SPEC.loader
GATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GATE)
FIXTURE = ROOT / "fixtures" / "science-popularization-review-v1" / "synthetic.input.json"


class SciencePopularizationGateTests(unittest.TestCase):
    def load(self) -> dict:
        return json.loads(FIXTURE.read_text(encoding="utf-8"))

    def assert_code(self, value: dict, code: str) -> None:
        with self.assertRaises(GATE.ScienceReviewError) as caught:
            GATE.validate_input(value)
        self.assertEqual(code, caught.exception.code)

    def test_source_card_is_official_and_scope_limited(self) -> None:
        card = GATE.validate_source_card()
        self.assertEqual("verified-primary-source", card["verification_status"])
        self.assertIn("not-an-insurance-contract-or-regulatory-source", card["authority_limits"])
        self.assertIn("not-a-platform-growth-or-ranking-guide", card["authority_limits"])

    def test_valid_fixture_is_deterministic_and_manual_only(self) -> None:
        first = GATE.create_receipt(FIXTURE)
        second = GATE.create_receipt(FIXTURE)
        self.assertEqual(first, second)
        self.assertEqual("review-required", first["release_status"])
        self.assertEqual("author-plus-subject-matter-check", first["next_gate"])
        self.assertFalse(any(first["authority"].values()))
        GATE.validate_receipt(first)

    def test_scientific_review_requires_current_evidence_and_human_check(self) -> None:
        value = self.load()
        value["scientific_review"]["data_and_citation_currency_checked"] = False
        self.assert_code(value, "scientific_review_incomplete")

        value = self.load()
        value["scientific_review"]["subject_matter_review_status"] = "pending"
        self.assert_code(value, "subject_matter_review_missing")

    def test_unresolved_or_undercovered_controversy_fails_closed(self) -> None:
        value = self.load()
        value["scientific_review"]["controversy_status"] = "unresolved"
        self.assert_code(value, "controversy_unresolved")

        value = self.load()
        value["scientific_review"]["controversy_status"] = "represented"
        self.assert_code(value, "controversy_coverage_missing")

    def test_target_audience_review_requires_evidence_and_resolution(self) -> None:
        value = self.load()
        value["audience_readability_review"]["reviewer_roles"] = ["plain-language-editor"]
        self.assert_code(value, "target_audience_review_missing")

        value = self.load()
        value["audience_readability_review"]["feedback_resolved"] = False
        self.assert_code(value, "audience_review_incomplete")

        value = self.load()
        value["audience_readability_review"]["review_evidence_refs"] = []
        self.assert_code(value, "audience_review_evidence_missing")

    def test_ai_sensitive_input_and_unreviewed_output_fail_closed(self) -> None:
        value = self.load()
        value["ai_assistance"]["nonpublic_or_sensitive_input_provided"] = True
        self.assert_code(value, "ai_sensitive_input_blocked")

        value = self.load()
        value["ai_assistance"]["factual_output_review"] = "not-applicable"
        self.assert_code(value, "ai_review_incomplete")

        value = self.load()
        value["ai_assistance"]["disclosure_assessment"] = "no-ai-used"
        self.assert_code(value, "ai_disclosure_inconsistent")

    def tiered(self, level='author-self-check'):
        value=self.load()
        review=value['audience_readability_review']
        roles={'author-self-check':'author','editor-review':'plain-language-editor',
               'target-audience-sample':'target-audience-representative'}
        review.update(review_level=level,reviewer_roles=[roles[level]],
            limitations='Synthetic check only; no audience effect or population inference.',
            evidence_bindings=[dict(path=p,sha256=GATE.text_sha256(GATE.resolve_ref(p))) for p in review['review_evidence_refs']])
        return value

    def test_explicit_tiers_do_not_require_a_representative_for_self_check(self):
        from unittest import mock
        for level in ('author-self-check','editor-review','target-audience-sample'):
            with self.subTest(level=level):
                value=self.tiered(level);GATE.validate_input(value)
                original=GATE.load_json
                with mock.patch.object(GATE,'load_json',side_effect=lambda p: value if p==Path('synthetic-input') else original(p)):
                    receipt=GATE.create_receipt(Path('synthetic-input'))
                GATE.validate_receipt(receipt)
                self.assertFalse(receipt['audience_validation']['audience_effect_verified'])
                self.assertEqual('sample-review-recorded' if level=='target-audience-sample' else 'not-tested',
                                 receipt['audience_validation']['status'])

    def test_self_check_cannot_claim_representative_and_evidence_cannot_drift(self):
        value=self.tiered();value['audience_readability_review']['reviewer_roles'].append('target-audience-representative')
        self.assert_code(value,'audience_tier_misrepresented')
        value=self.tiered();value['audience_readability_review']['evidence_bindings'][0]['sha256']='0'*64
        self.assert_code(value,'audience_evidence_drift')
        value=self.tiered();value['audience_readability_review']['limitations']=''
        self.assert_code(value,'audience_limits_required')

    def test_tier_does_not_waive_scientific_review_or_unresolved_feedback(self):
        value=self.tiered();value['scientific_review']['subject_matter_review_status']='pending'
        self.assert_code(value,'subject_matter_review_missing')
        value=self.tiered();value['audience_readability_review']['feedback_resolved']=False
        self.assert_code(value,'audience_review_incomplete')

    def test_body_and_receipt_drift_fail_closed(self) -> None:
        value = self.load()
        value["body_binding"]["body_sha256"] = "0" * 64
        self.assert_code(value, "body_hash_drift")

        receipt = GATE.create_receipt(FIXTURE)
        changed = copy.deepcopy(receipt)
        changed["content_id"] = "changed-content-id"
        with self.assertRaises(GATE.ScienceReviewError) as caught:
            GATE.validate_receipt(changed)
        self.assertEqual("receipt_hash_drift", caught.exception.code)

    def test_recipe_and_extension_routing_fail_closed(self) -> None:
        recipes = GATE.load_json(GATE.RECIPES)
        binding = GATE.load_json(GATE.BINDING)
        self.assertEqual([], GATE.routing_errors(recipes, binding))

        missing_gate = copy.deepcopy(recipes)
        target = next(row for row in missing_gate["recipes"] if row["recipe_id"] == "xhs-evidence-graphic")
        target["quality_gates"].remove("science-popularization-review-if-science-claim")
        self.assertTrue(any("xhs-evidence-graphic" in error for error in GATE.routing_errors(missing_gate, binding)))

        missing_extension = copy.deepcopy(binding)
        missing_extension["operational_extensions"] = [
            row for row in missing_extension["operational_extensions"]
            if row.get("path") != "schemas/science-popularization-review.v1.schema.json"
        ]
        self.assertIn("operational extension is not registered", GATE.routing_errors(recipes, missing_extension))


if __name__ == "__main__":
    unittest.main()
