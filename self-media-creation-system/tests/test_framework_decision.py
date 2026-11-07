from __future__ import annotations

import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


GATE = module('framework_decision_test', ROOT / 'scripts/topic_angle_decision.py')
AGENT = module('framework_agent_test', ROOT / 'scripts/self_media_agent.py')


class FrameworkDecisionTests(unittest.TestCase):
    def setUp(self):
        self.value = GATE.load_json(ROOT / 'fixtures/topic-angle-decision-v2/synthetic.input.json')

    def confirmed(self):
        self.value['human_review'] = {'status': 'confirmed', 'reviewer': 'human',
                                     'decision_confirmed': True, 'notes': 'Synthetic human state for fixture testing only.'}

    def route(self, outcome):
        d = self.value['framework_decision']
        d['outcome'] = outcome
        if outcome in ['reframe', 'defer']:
            self.value['selected_angle_id'] = None
            for a in self.value['angle_candidates']:
                a.update(selection_status='not-selected', selection_reason=None,
                         rejection_reason='Not appropriate under this synthetic goal.')
        if outcome == 'reframe':
            d.update(rewrite_scope='full', planned_changes=['revise-body'])
        if outcome == 'supplement':
            d['missing_material'] = ['Verify the missing claim against an original source.']
            d['assessments'][0]['material_support'] = 'needs-material'
            self.value['angle_candidates'][0]['evidence_readiness'] = 'blocked'

    def receipt(self):
        return GATE.create_receipt_from_value(self.value)

    def blocked(self, code):
        with self.assertRaises(GATE.TopicAngleError) as error:
            self.receipt()
        self.assertEqual(error.exception.code, code)

    def test_four_outcomes_are_valid_but_only_confirmed_continue_reaches_draft(self):
        base = copy.deepcopy(self.value)
        for outcome in ['continue', 'reframe', 'supplement', 'defer']:
            with self.subTest(outcome=outcome):
                self.value = copy.deepcopy(base)
                self.route(outcome)
                self.assertFalse(GATE.continuation(self.receipt())['may_continue'])
                self.confirmed()
                receipt = self.receipt()
                self.assertEqual(GATE.continuation(receipt)['may_continue'], outcome == 'continue')
                self.assertEqual(GATE.continuation(receipt, stage='research')['may_continue'], outcome in ['continue', 'supplement'])
                self.assertFalse(any(receipt['authority'].values()))

    def test_all_rejected_is_valid_and_does_not_force_a_winner(self):
        self.route('defer')
        self.assertIsNone(self.receipt()['selected_angle_id'])

    def test_continue_requires_material_and_explained_cost(self):
        self.value['framework_decision']['assessments'][0]['worth_cost'] = 'unknown'
        self.blocked('framework_not_ready')

    def test_known_business_mismatch_cannot_be_overridden_by_reach(self):
        d = self.value['framework_decision']
        d.update(business_mode='known', offer='Synthetic service', buyer='Synthetic buyer')
        d['assessments'][0]['business_fit'] = 'mismatch'
        self.blocked('framework_business_mismatch')

    def test_consultation_cannot_ignore_unknown_service(self):
        self.value['editorial_goal']['primary_goal'] = 'consultation'
        self.value['framework_decision']['business_mode'] = 'unknown'
        self.blocked('business_context_missing')

    def test_personal_trust_does_not_require_conversion(self):
        self.confirmed()
        self.assertTrue(GATE.continuation(self.receipt())['may_continue'])

    def test_fixed_media_cannot_silently_authorize_rewriting(self):
        self.route('reframe')
        self.value['framework_decision']['allowed_changes'] = ['package-only']
        self.blocked('framework_scope_exceeded')

    def test_each_candidate_needs_its_own_assessment(self):
        self.value['framework_decision']['assessments'].pop()
        self.blocked('framework_comparison_incomplete')

    def test_missing_material_and_full_rewrite_are_not_continue(self):
        self.route('supplement')
        self.value['framework_decision']['missing_material'] = []
        self.blocked('missing_material_unspecified')

    def test_current_material_hash_and_receipt_hash_are_checked(self):
        original = copy.deepcopy(self.value)
        self.value['framework_decision']['current_artifact']['sha256'] = '0' * 64
        self.blocked('framework_material_drift')
        self.value = original
        receipt = self.receipt()
        receipt['framework_decision']['next_action'] = 'Tampered action'
        with self.assertRaisesRegex(GATE.TopicAngleError, 'changed after creation'):
            GATE.continuation(receipt)

    def test_v1_is_readable_but_not_a_framework_pass(self):
        receipt = GATE.create_receipt(GATE.FIXTURE)
        GATE.validate_receipt(receipt)
        with self.assertRaises(GATE.TopicAngleError) as error:
            GATE.continuation(receipt)
        self.assertEqual(error.exception.code, 'legacy_framework_review_required')

    def test_managed_entry_consumes_decision_instead_of_presence_only(self):
        runtime = ROOT / 'tests/.runtime'
        runtime.mkdir(parents=True, exist_ok=True)
        p = runtime / 'framework-consumer'
        p.mkdir(exist_ok=True)
        if p.is_dir():
            manifest = {'artifacts': [{'source_role': 'topic-angle-decision', 'path': 'decision.json'}]}
            (p/'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
            step = {'step_id': 'build-evidence-draft'}
            (p/'decision.json').write_text(json.dumps(self.receipt()), encoding='utf-8')
            with self.assertRaises(AGENT.AgentEntryError) as error:
                AGENT._validate_framework_context(p/'manifest.json', step)
            self.assertEqual(error.exception.code, 'framework_return_required')
            self.confirmed()
            (p/'decision.json').write_text(json.dumps(self.receipt()), encoding='utf-8')
            AGENT._validate_framework_context(p/'manifest.json', step)
            self.route('supplement')
            (p/'decision.json').write_text(json.dumps(self.receipt()), encoding='utf-8')
            AGENT._validate_framework_context(p/'manifest.json', {'step_id': 'produce-verified-research-output'})
            with self.assertRaises(AGENT.AgentEntryError):
                AGENT._validate_framework_context(p/'manifest.json', step)


if __name__ == '__main__':
    unittest.main()
