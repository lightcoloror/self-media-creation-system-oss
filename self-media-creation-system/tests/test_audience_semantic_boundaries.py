"""Synthetic counterexamples: mechanical validity is not editorial quality."""
import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import content_packaging_review as packaging
import self_media_agent as agent


class AudienceBoundaries(unittest.TestCase):
    def setUp(self):
        self.review = dict(
            audience_question='How?', entry_strategy='search-intent',
            title_cover_opening_same_promise=True, context_excerpt='Context.',
            progression_excerpts=['Answer.'], core_answer_excerpt='Answer.',
            payoff_excerpt='Answer.', current_item_payoff_delivered=True,
            insurance_entry_mode='not-applicable', prior_item_required=False,
            future_item_required_for_payoff=False)

    def check(self, body='Context. Answer.', title='How?', opening='Context.'):
        return packaging.validate_standalone_review(
            self.review, title=title, opening_text=opening, body_text=body)

    def test_one_real_advance_is_enough(self):
        self.check()

    def test_more_than_eight_real_advances_allowed(self):
        self.review['progression_excerpts'] = [f'Point {n}.' for n in range(12)]
        self.check('Context. ' + ' '.join(self.review['progression_excerpts']) + ' Answer.')

    def test_complete_record_cannot_use_title_as_answer(self):
        with self.assertRaises(packaging.PackagingReviewError) as error:
            self.check(body='Context.', title='How? Answer.')
        self.assertEqual(error.exception.code, 'payoff_not_in_content')

    def test_nested_anchors_are_not_two_advances(self):
        self.review['progression_excerpts'] = ['Answer.', 'swer.']
        with self.assertRaises(packaging.PackagingReviewError) as error:
            self.check()
        self.assertEqual(error.exception.code, 'information_progression_missing')

    def test_complete_flags_cannot_hide_withheld_payoff(self):
        with self.assertRaises(packaging.PackagingReviewError):
            self.check('Context. Answer. 答案下期揭晓')

    def test_empty_progression_still_rejected(self):
        self.review['progression_excerpts'] = []
        with self.assertRaises(packaging.PackagingReviewError):
            self.check()

    def test_semantically_empty_prose_is_not_claimed_as_quality(self):
        # Both quotes exist, but merely restate a claim. Do not build a lexical
        # classifier that pretends to establish their meaning or persuasion.
        self.review.update(progression_excerpts=['It helps.', 'It is useful.'],
                           core_answer_excerpt='It helps.', payoff_excerpt='It is useful.')
        self.check('Context. It helps. It is useful.')
        receipt = packaging.create_receipt(packaging.DEFAULT_INPUT)
        result = packaging.validate_receipt_value(receipt)
        self.assertFalse(result['proves_editorial_quality'])
        self.assertFalse(result['proves_conversion'])

    def test_all_existing_writing_and_review_steps_receive_guidance(self):
        catalog = json.loads((ROOT / 'recipes/self-media-recipes.v1.json').read_text(encoding='utf-8'))
        authoring = agent._load_author_writing_context()
        applicable = authoring.WRITING_STEPS | authoring.REVIEW_STEPS
        count = 0
        for recipe in catalog['recipes']:
            for step in recipe['steps']:
                if step['step_id'] not in applicable:
                    continue
                for route in ('story', 'expository', 'travel-experience'):
                    with self.subTest(recipe=recipe['recipe_id'], step=step['step_id'], route=route):
                        purpose = {'purpose_source': 'same source', 'audience_source': 'same audience'}
                        result = agent._execution_brief(step, dict(primary_route=route,
                            guide='existing-guide', story_design_applicability='selected'), purpose)
                        self.assertEqual(result['purpose_context'], purpose)
                        self.assertIn('reach, trust and action', result['instruction'])
                        self.assertIn('no mandatory acquisition CTA', result['instruction'])
                        self.assertIn('Route=' + route, result['instruction'])
                count += 1
        self.assertGreater(count, 0)


if __name__ == '__main__':
    unittest.main()
