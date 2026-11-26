"""Regression tests for rotation, measured clipping, and same-time delivery sampling."""
import json
import sys
import shutil
import unittest
import uuid
from pathlib import Path
from unittest.mock import Mock, patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
import cover_workbench as covers
import video_delivery as delivery
import video_frame_safety as framing
import video_review_delivery as review

delivery.renderer_module()


def metadata(width, height, rotation=None, sar='1:1', tag=None):
    stream = dict(codec_type='video', width=width, height=height, sample_aspect_ratio=sar)
    if rotation is not None:
        stream['side_data_list'] = [{'rotation': rotation}]
    if tag is not None:
        stream['tags'] = {'rotate': str(tag)}
    return {'streams': [stream], 'format': {'duration': '8'}}


class FrameSafetyTests(unittest.TestCase):
    def setUp(self):
        parent = SCRIPTS.parent / '.test-runtime'
        parent.mkdir(exist_ok=True)
        self.root = parent.resolve() / ('frame-safety-' + uuid.uuid4().hex)
        self.root.mkdir()
        self.addCleanup(shutil.rmtree, self.root)
        self.program = self.save('program.mp4', {})
        self.render = self.save('animation.mp4', {})
        self.insert = self.save('insert.mp4', {})
        self.compose = self.save('composition.json', {'version': 'current'})
        self.times = [2.01, 2.5, 2.97]
        self.plan = dict(schema=framing.SCHEMA, project_id='fixture', canvas=[1080, 1920],
                         composition_ref=self.compose, duration_seconds=8,
                         sources=[dict(stage=stage, artifact_ref=ref) for stage, ref in (
                             ('program', self.program), ('animation_render', self.render),
                             ('animation_insert', self.insert))],
                         sample_times_seconds=self.times,
                         layers=[dict(id=role, role=role, start_seconds=2, end_seconds=3)
                                 for role in ('flower', 'subtitle', 'evidence_card', 'animation')])
        self.measured = dict(schema='self-media.compositor-frame-measurements.v1',
                             composition_ref=self.compose, canvas=self.plan['canvas'],
                             samples=[dict(time_seconds=t, bounds={row['id']: [10, 10, 100, 100]
                                           for row in self.plan['layers']}) for t in self.times])
        self.probe = Mock(side_effect=lambda path: metadata(1920, 1080, -90)
                          if path == Path(self.program['path']) else metadata(1080, 1920))

    def save(self, name, value):
        path = self.root / name
        path.write_text(json.dumps(value), encoding='utf-8')
        return covers.reference(path)

    def plan_ref(self):
        self.plan['measurements_ref'] = self.save('measured.json', self.measured)
        return self.save('plan.json', self.plan)

    def test_display_matrix_before_rotate_tag_and_anamorphic_pixels(self):
        facts = framing.display_geometry(metadata(1920, 1080, -90, tag=0))
        self.assertEqual(facts['oriented_size'], [1080, 1920])
        self.assertEqual(facts['display_aspect_ratio'], '9/16')
        self.assertEqual(framing.display_geometry(metadata(1440, 1080, sar='4:3', tag=90))['display_aspect_ratio'], '9/16')
        for invalid in (metadata(1920, 1080, 45), metadata(1920, 1080, 0, sar='1:0')):
            with self.assertRaises(ValueError):
                framing.display_geometry(invalid)

    def test_blocks_wrong_aspect_at_either_animation_stage(self):
        ref = self.plan_ref()
        for source in (self.render, self.insert):
            with self.subTest(source=Path(source['path']).name):
                def probe(path):
                    return metadata(1920, 1080) if path == Path(source['path']) else self.probe(path)
                with self.assertRaisesRegex(ValueError, 'display_aspect_mismatch'):
                    framing.check_ref(ref, probe)
        checked = framing.check_ref(ref, self.probe)
        self.assertEqual(checked['sample_times_seconds'], self.times)
        self.assertEqual(checked['checked_layer_count'], 4)

    def test_blocks_real_bound_outside_canvas_and_missing_measurement(self):
        boxes = self.measured['samples'][1]['bounds']
        for role, rect in (('flower', [-2, 20, 100, 200]), ('subtitle', [20, 1790, 800, 1930]),
                           ('evidence_card', [30, 100, 1081, 160])):
            with self.subTest(role=role):
                old = boxes[role]
                boxes[role] = rect
                with self.assertRaisesRegex(ValueError, f'overlay_out_of_frame: {role}'):
                    framing.check_ref(self.plan_ref(), self.probe)
                boxes[role] = old
        boxes.pop('evidence_card')
        with self.assertRaisesRegex(ValueError, 'missing_or_unlisted_measured_overlay'):
            framing.check_ref(self.plan_ref(), self.probe)

    def test_fine_review_blocks_before_page_and_accepts_after_fix(self):
        request = dict(schema_version='self-media-human-review-request-pack.v1', requests=[
            dict(review_id='a', source_path=self.program['path'], artifact_sha256=self.program['sha256'],
                 review_start_seconds=4, review_end_seconds=5, expected_dialogue=[],
                 no_dialogue_reason='Silent testing example',
                 subtitle_cues=[dict(text='test', start_seconds=4, end_seconds=5)])],
            presentation_requirements=dict(required_layers=['dialogue'], animated_speakers=[], style_reason='fixture'))
        self.plan['review_payload_sha256'] = framing.review_payload_hash(request)
        self.plan['review_program_starts'] = {'a': 2}
        boxes = self.measured['samples'][1]['bounds']
        original = boxes['flower']
        boxes['flower'] = [-5, 0, 80, 80]
        request['frame_safety_plan_ref'] = self.plan_ref()
        path = Path(self.save('request.json', request)['path'])
        output = self.root / 'review'
        preparer = Mock(return_value={'status': 'prepared', 'media_copies_created': 0})
        with patch('rough_cut_checks.check_fine_request'), patch.object(framing, 'probe_media', self.probe):
            with self.assertRaisesRegex(ValueError, 'overlay_out_of_frame'):
                review.prepare(path, output, 'fine_cut_recipe', preparer=preparer)
            preparer.assert_not_called()
            self.assertFalse(output.exists())
            boxes['flower'] = original
            request['frame_safety_plan_ref'] = self.plan_ref()
            self.save('request.json', request)
            result = review.prepare(path, output, 'fine_cut_recipe', preparer=preparer)
            self.assertEqual(result['frame_safety']['sample_times_seconds'], self.times)
            preparer.assert_called_once()

    def test_postcheck_extracts_same_times_and_checks_decoded_dimensions(self):
        from PIL import Image

        plan_ref = self.plan_ref()
        final = self.save('final.mp4', {})
        output = self.root / 'final-observations'

        def capture(source, project, times, output_dir):
            self.assertEqual((source, project, times), (Path(final['path']), 'fixture', self.times))
            output_dir.mkdir()
            rows = []
            for index, seconds in enumerate(times):
                file = output_dir / f'{index}.png'
                Image.new('RGB', (1080, 1920)).save(file)
                rows.append(dict(time_seconds=seconds, frame_ref=covers.reference(file)))
            return rows

        with patch.object(framing, 'probe_media', self.probe), patch.object(delivery, 'capture_final_frames', side_effect=capture):
            result = delivery.frame_postcheck(plan_ref, final, output)
        self.assertEqual(result['plan_ref'], plan_ref)
        self.assertEqual(result['video_ref'], final)
        self.assertTrue(result['rendered_layer_review_pending'])
        self.assertEqual([row['time_seconds'] for row in result['frames']], self.times)
        with self.assertRaisesRegex(ValueError, 'decoded_frame_canvas_mismatch'):
            framing.check_decoded_frames(result['frames'], [1920, 1080])

    def test_delivery_rejects_unreviewed_plan_revision(self):
        plan_ref = self.plan_ref()
        receipt = framing.check_ref(plan_ref, self.probe)
        manifest = dict(project_id='fixture', edited_media=self.program, frame_safety_plan_ref=plan_ref)
        with self.assertRaisesRegex(ValueError, 'pre_review_receipt_required'):
            framing.for_delivery(manifest, self.probe)
        manifest['frame_safety_review_ref'] = self.save('review-receipt.json', {**receipt, 'plan_ref': plan_ref})
        self.assertEqual(framing.for_delivery(manifest, self.probe)['sample_times_seconds'], self.times)
        self.plan['project_id'] = 'new-revision'
        manifest['project_id'] = 'new-revision'
        manifest['frame_safety_plan_ref'] = self.plan_ref()
        with self.assertRaisesRegex(ValueError, 'pre_review_receipt_does_not_match_current_plan'):
            framing.for_delivery(manifest, self.probe)


if __name__ == '__main__':
    unittest.main()
