"""Regressions for extra cover copy and preview-to-final promotion."""

import copy
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import cover_policy as policy
import cover_workbench as workbench


class CoverPolicyTests(unittest.TestCase):
    def test_baked_and_layer_text(self):
        headline = '有医保了，还要买商业医疗险？'
        visible = ['有医保了，还要买\n商业医疗险?', '结算示意']
        allowed = {'结算示意': '说明图中纸张的用途'}
        policy.check_text(visible, headline, allowed, context='cover/3:4')
        for extra in ['AI', 'AI 画面', '生成 AI 画面', '灿哥诊风险', '其他无关角标']:
            with self.subTest(extra=extra), self.assertRaisesRegex(ValueError, 'unapproved'):
                policy.check_text(visible + [extra], headline, allowed, context='cover/3:4')
        with self.assertRaisesRegex(ValueError, 'unapproved'):
            policy.check_text([headline[:-1]], headline, allowed, context='cover/3:4')
        policy.check_text(['AI怎么用？', 'AI 生成示意图'], 'AI怎么用？',
                          {'AI生成示意图': '用户明确要求标注该插图'}, context='cover/3:4')
        plan = dict(candidate=dict(candidate_id='cover'), render_spec=dict(profile_layouts={
            'vertical_profile_3_4': {'cover_layers': {'layers': [
                {'type': 'text', 'role': 'overlay', 'text': headline},
                {'type': 'text', 'role': 'attribution', 'text': '灿哥诊风险'},
            ]}}
        }))
        with self.assertRaisesRegex(ValueError, 'unapproved'):
            policy.check_plan_text(plan, headline, allowed)

    def test_init_sets_preview_and_plan_rejects_overproduction(self):
        brief = workbench.init('test-project', 'Fixture', stage='preview')
        brief.update(promise='fixture', facts=['fixture'])
        self.assertEqual(brief['cover_stage'], 'preview')
        workbench.plan(brief)
        brief['requested_ratios'] = list(policy.FINAL_RATIOS)
        with self.assertRaisesRegex(ValueError, 'preview_requires_one_or_two'):
            workbench.plan(brief)

    def test_final_requires_confirmed_style_current_images_and_all_four_ratios(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            images = {}
            for ratio in policy.FINAL_RATIOS:
                a, b = map(int, ratio.split(':'))
                path = root / (ratio.replace(':', '-') + '.png')
                scale = (480 + min(a, b) - 1) // min(a, b)
                Image.new('RGB', (scale * a, scale * b)).save(path)
                images[ratio] = dict(image_ref=workbench.reference(path), visual_passed=True,
                                     visible_text=['Synthetic headline?'])
            master_path = root / 'master.png'
            Image.new('RGB', (1920, 1080), (20, 22, 24)).save(master_path)
            card = dict(id='A', style_id='perspective', headline='Synthetic headline?',
                        master_plate_ref=workbench.reference(master_path), images=images)
            preview = dict(schema='self-media.cover-package-review.v1', project_id='test-project',
                           stage='preview', reviewer='fixture', candidates=[dict(card, images={'3:4': images['3:4']})])
            preview_path = root / 'preview.json'
            workbench.write(preview_path, preview)
            self.assertEqual(policy.package_check(preview_path)['status'], 'preview_reviewed')
            final = dict(preview, stage='final', candidates=[card], style_choice=dict(
                candidate_id='A', user_confirmation='Synthetic fixture choice',
                preview_package_ref=workbench.reference(preview_path)))
            final_path = root / 'final.json'
            workbench.write(final_path, final)
            self.assertEqual(policy.package_check(final_path)['status'], 'final_cover_package_complete')
            checks = [
                ('missing', lambda d: d['candidates'][0]['images'].pop('9:16'), 'final_requires_four.*9:16'),
                ('missing-master', lambda d: d['candidates'][0].pop('master_plate_ref'), 'cover_candidate_master_plate_missing'),
                ('replaced-style', lambda d: d['candidates'][0].update(style_id='other'), 'style_differs'),
                ('copy', lambda d: d['candidates'][0]['images']['4:3']['visible_text'].append('AI 画面'), 'unapproved'),
                ('unchecked', lambda d: d['candidates'][0]['images']['16:9'].pop('visible_text'), 'visible_text_review_required'),
            ]
            for name, change, message in checks:
                changed = copy.deepcopy(final)
                change(changed)
                path = root / (name + '.json')
                workbench.write(path, changed)
                with self.subTest(name=name), self.assertRaisesRegex(ValueError, message):
                    policy.package_check(path)
            Path(images['4:3']['image_ref']['path']).write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'changed_artifact'):
                policy.package_check(final_path)
