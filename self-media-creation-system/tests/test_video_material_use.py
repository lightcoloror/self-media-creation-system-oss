import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import cover_workbench as covers
import video_material_use as materials


class MaterialUseTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.renderer = Mock()
        self.video = self.artifact('video.mp4', b'synthetic video')
        frame = self.artifact('frame.jpg', b'synthetic frame')
        self.asset = dict(id='article-excerpt', entry_method='screen_recording',
                          original_ref=self.artifact('original.png', b'original'),
                          adopted_ref=self.artifact('cropped.png', b'cropped'),
                          source='https://example.invalid/article', processing='Crop the relevant panel and mask identifiers.',
                          use_basis=dict(decision='supported', reason='Synthetic use-basis fixture.',
                                         evidence_ref=self.artifact('basis.txt', b'synthetic evidence')))
        self.manifest = dict(project_id='material-test')
        self.write_intake()
        self.receipt = dict(status='completed', operation='frame_extract', inputs=[dict(artifact=self.video)],
                            outputs=[dict(role='frame', artifact=frame, media_time_s=1)])
        self.review = dict(schema=materials.REVIEW_SCHEMA, project_id=self.manifest['project_id'],
                           intake_ref=self.manifest['material_intake_ref'], video=self.video,
                           screen_recording_checked=True, reviewer='Synthetic reviewer fixture',
                           sample_receipts=[self.json_ref('frames', self.receipt)], entries=[
                               dict(id=self.asset['id'], decision='present', ranges=[
                                   dict(start_seconds=.8, end_seconds=1.7, sample_seconds=1, frame_ref=frame,
                                        credit='visible_checked', processing_checked=True, observation='Synthetic observation.')])])
        self.write_review()

    def artifact(self, name, data):
        path = self.root / name
        path.write_bytes(data)
        return covers.reference(path)

    def json_ref(self, name, data):
        return self.artifact(name + '.json', json.dumps(data).encode())

    def write_intake(self):
        self.manifest['material_intake_ref'] = self.json_ref('intake', dict(
            schema=materials.INTAKE_SCHEMA, project_id=self.manifest['project_id'],
            scope_note='Includes the screenshots embedded in the recording.', assets=[self.asset]))

    def write_review(self):
        self.manifest['material_final_review_ref'] = self.json_ref('review', self.review)

    def final(self):
        return materials.check_final(self.manifest, self.video, 2, self.renderer)

    def test_registered_screen_capture_and_actual_frame_pass(self):
        self.assertEqual(materials.check_intake(self.manifest)['screen_recording_asset_count'], 1)
        self.assertEqual(self.final()['use_ranges'], 1)
        self.renderer.validate_ffmpeg_execution_receipt.assert_called_once()

    def test_missing_and_pending_intake_block(self):
        self.manifest['material_intake_ref'] = None
        with self.assertRaisesRegex(ValueError, 'material_intake_required'):
            materials.check_intake(self.manifest)
        self.asset['use_basis'] = dict(decision='pending', reason='Source URL exists, basis pending.')
        self.write_intake()
        with self.assertRaisesRegex(ValueError, 'material_use_basis_pending'):
            materials.check_intake(self.manifest)

    def test_supported_requires_evidence_and_adopted_file_cannot_change(self):
        proof = self.asset['use_basis'].pop('evidence_ref')
        self.write_intake()
        with self.assertRaisesRegex(ValueError, 'material_use_basis_evidence_required'):
            materials.check_intake(self.manifest)
        self.asset['use_basis']['evidence_ref'] = proof
        self.write_intake()
        Path(self.asset['adopted_ref']['path']).write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'missing_or_changed_artifact'):
            materials.check_intake(self.manifest)

    def test_old_video_or_intake_cannot_approve_the_current_export(self):
        old_video = self.video
        self.video = self.artifact('new-video.mp4', b'new export')
        with self.assertRaisesRegex(ValueError, 'material_final_review_for_other_video'):
            self.final()
        self.video = old_video
        self.asset['processing'] = 'New version of image processing.'
        self.write_intake()
        with self.assertRaisesRegex(ValueError, 'material_final_review_for_other_intake'):
            self.final()

    def test_missing_asset_or_arbitrary_frame_cannot_pass(self):
        entry = self.review['entries'].pop()
        self.write_review()
        with self.assertRaisesRegex(ValueError, 'cover_each_registered_asset'):
            self.final()
        self.review['entries'].append(entry)
        entry['ranges'][0]['frame_ref'] = self.artifact('arbitrary.jpg', b'arbitrary')
        self.write_review()
        with self.assertRaisesRegex(ValueError, 'frame_not_proven'):
            self.final()

    def test_review_needs_current_frame_at_in_range_time_and_proof_of_treatment(self):
        use = self.review['entries'][0]['ranges'][0]
        use['sample_seconds'] = 1.8
        self.write_review()
        with self.assertRaisesRegex(ValueError, 'time_range'):
            self.final()
        use.update(sample_seconds=1, processing_checked=False)
        self.write_review()
        with self.assertRaisesRegex(ValueError, 'processing_review_pending'):
            self.final()
        use['processing_checked'] = True
        self.receipt['inputs'][0]['artifact'] = self.artifact('stale.mp4', b'stale')
        self.review['sample_receipts'] = [self.json_ref('frames', self.receipt)]
        self.write_review()
        with self.assertRaisesRegex(ValueError, 'frame_receipt_for_other_video'):
            self.final()

    def test_render_receipt_catches_unregistered_overlay(self):
        inputs = [dict(role='evidence_overlay', artifact=self.asset['adopted_ref'])]
        items, _ = materials.intake(self.manifest)
        materials.check_render_inputs(items, [dict(inputs=inputs)])
        with self.assertRaisesRegex(ValueError, 'material_render_input_not_registered'):
            materials.check_render_inputs({}, [dict(inputs=inputs)])

    def redraw_fixture(self):
        self.asset.update(entry_method='timeline_asset', use_basis=dict(decision='pending', reason='Original pending.'))
        self.write_intake()
        return dict(schema=materials.REDRAW_SCHEMA, project_id=self.manifest['project_id'], asset_id=self.asset['id'],
                    source=self.asset['source'], reference_ref=self.asset['original_ref'],
                    fact_source_url='https://example.invalid/facts',
                    editable_ref=self.artifact('redraw.html', b'<figure>New graph</figure>'),
                    rendered_ref=self.artifact('redrawn.png', b'synthetic redrawn bitmap'),
                    fallback_reason='Direct use is unsuitable.', reviewer='Synthetic reviewer',
                    review_notes='Checked the source facts, design, credit and readable layout.',
                    checks={name: True for name in materials.REDRAW_CHECKS})

    def test_redraw_replaces_pending_asset_and_only_new_image_can_enter_render(self):
        proof = self.redraw_fixture()
        old = self.manifest['material_intake_ref']
        updated = materials.redraw_intake(self.manifest, self.json_ref('redraw', proof))
        self.assertEqual(covers.read(covers.bound(old))['assets'][0]['use_basis']['decision'], 'pending')
        self.manifest['material_intake_ref'] = self.json_ref('redrawn-intake', updated)
        items, _ = materials.intake(self.manifest)
        self.assertEqual(items[self.asset['id']]['original_ref'], self.asset['original_ref'])
        self.assertEqual(materials.check_intake(self.manifest)['independent_redraw_count'], 1)
        materials.check_render_inputs(items, [dict(inputs=[dict(role='evidence_overlay', artifact=proof['rendered_ref'])])])
        with self.assertRaisesRegex(ValueError, 'material_render_input_not_registered'):
            materials.check_render_inputs(items, [dict(inputs=[dict(role='evidence_overlay', artifact=proof['reference_ref'])])])

    def test_copy_or_wrong_source_or_incomplete_checks_cannot_replace_original(self):
        proof = self.redraw_fixture()
        copy = self.artifact('copy.png', b'original')
        for change, error in ((dict(rendered_ref=copy), 'requires_distinct'),
                              (dict(source='https://example.invalid/other'), 'source_mismatch'),
                              (dict(checks={}), 'checks_incomplete'), (dict(editable_ref=None), 'editable_source_required'),
                              (dict(fact_source_url=None), 'fact_source_url_required')):
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, error):
                materials.redraw_intake(self.manifest, self.json_ref('redraw', dict(proof, **change)))

    def test_redraw_stale_editable_or_missing_final_credit_blocks(self):
        proof = self.redraw_fixture()
        new_intake = materials.redraw_intake(self.manifest, self.json_ref('redraw', proof))
        current = self.json_ref('redrawn-intake', new_intake)
        self.manifest['material_intake_ref'] = current
        self.review['intake_ref'] = current
        segment = self.review['entries'][0]['ranges'][0]
        segment['credit'] = 'not_required'
        self.write_review()
        with self.assertRaisesRegex(ValueError, 'redraw_visible_credit_required'):
            self.final()
        segment['credit'] = 'visible_checked'
        self.write_review()
        self.assertEqual(self.final()['use_ranges'], 1)
        Path(proof['editable_ref']['path']).write_bytes(b'uncaptured source edit')
        with self.assertRaisesRegex(ValueError, 'missing_or_changed_artifact'):
            materials.check_intake(self.manifest)

    def recorded_card_fixture(self):
        self.asset['card_replacement_ref'] = None
        self.write_intake()
        recording_html = self.artifact('recording.html', b'<div id="card">Before</div>')
        edited = self.artifact('recording-revised.html', b'<div id="card">After</div>')
        new_card = self.artifact('whole-card.png', b'synthetic full card')
        capture = self.json_ref('card-capture', dict(schema=materials.CAPTURE_SCHEMA, editable_ref=edited,
            rendered_ref=new_card, selector='#card', width=800, height=120))
        return dict(schema=materials.CARD_REPLACEMENT_SCHEMA, project_id=self.manifest['project_id'],
                    asset_id=self.asset['id'], reference_ref=self.asset['original_ref'], recording_html_ref=recording_html,
                    editable_ref=edited, rendered_ref=new_card, method='html_recapture', capture_ref=capture,
                    whole_card_checked=True)

    def test_declared_recorded_edit_waits_for_whole_card_from_revised_recording_html(self):
        proof = self.recorded_card_fixture()
        with self.assertRaisesRegex(ValueError, 'material_use_basis_pending'):
            materials.check_intake(self.manifest)
        new_intake = materials.card_replace_intake(self.manifest, self.json_ref('card-edit', proof))
        self.manifest['material_intake_ref'] = self.json_ref('card-intake', new_intake)
        items, _ = materials.intake(self.manifest)
        picked = items[self.asset['id']]
        self.assertEqual(picked['original_ref'], self.asset['original_ref'])
        self.assertEqual(picked['adopted_ref'], proof['rendered_ref'])
        self.assertEqual(picked['use_basis'], self.asset['use_basis'])
        self.assertEqual(materials.check_intake(self.manifest)['recorded_card_replacement_count'], 1)
        with self.assertRaisesRegex(ValueError, 'material_render_input_not_registered'):
            materials.check_render_inputs(items, [dict(inputs=[dict(role='overlay_image', artifact=self.asset['adopted_ref'])])])

    def test_recorded_card_requires_source_and_matching_capture_and_rejects_partial_patch(self):
        proof = self.recorded_card_fixture()
        wrong_png = self.artifact('other.png', b'not the captured image')
        for changes, error in ((dict(recording_html_ref=None), 'recording_html_required'),
                               (dict(recording_html_ref=proof['editable_ref']), 'requires_revised_recording_html'),
                               (dict(capture_ref=None), 'html_capture_required'),
                               (dict(rendered_ref=wrong_png), 'html_capture_mismatch'),
                               (dict(whole_card_checked=False), 'requires_new_whole_card'),
                               (dict(method='delogo'), 'requires_html_recapture'),
                               (dict(method='recreated_card'), 'documented_recreation')):
            with self.subTest(changes=changes), self.assertRaisesRegex(ValueError, error):
                materials.card_replace_intake(self.manifest, self.json_ref('card-edit', dict(proof, **changes)))

    def test_export_checks_ghosting_seams_and_text_for_each_replaced_range(self):
        proof = self.recorded_card_fixture()
        updated = materials.card_replace_intake(self.manifest, self.json_ref('card-edit', proof))
        current = self.json_ref('card-intake', updated)
        self.manifest['material_intake_ref'] = current
        self.review['intake_ref'] = current
        segment = self.review['entries'][0]['ranges'][0]
        for check in materials.CARD_VISUAL_CHECKS:
            with self.subTest(check=check):
                segment['card_visual_checks'] = dict.fromkeys(materials.CARD_VISUAL_CHECKS, True)
                segment['card_visual_checks'][check] = False
                self.write_review()
                with self.assertRaisesRegex(ValueError, 'material_card_visual_review_incomplete'):
                    self.final()
        segment['card_visual_checks'] = dict.fromkeys(materials.CARD_VISUAL_CHECKS, True)
        self.write_review()
        self.assertEqual(self.final()['use_ranges'], 1)
