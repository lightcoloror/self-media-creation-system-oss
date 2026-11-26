"""Real local inspectors over synthetic media; never real human/child approval."""
import contextlib
import copy
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import os
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import video_delivery as v
import cover_workbench as w
import publication_desk as desk
import test_cover_strategy as cover_fixture


def _system_font(filename: str) -> str:
    sys_root = os.environ.get('SystemRoot') or os.environ.get('WINDIR') or ''
    if sys_root:
        return (Path(sys_root) / 'Fonts' / filename).as_posix()
    return f'/usr/share/fonts/{filename}'


@unittest.skipUnless(
    (v.ROOT.parent / 'ai-video-tools-20260708/mvp-video-pipeline/src/video_creation_pipeline/execution_receipts.py').is_file(),
    'Full MVP renderer owner is separately supplied; local-rough-cut is not a substitute',
)
@unittest.skipUnless(
    shutil.which('ffmpeg') and shutil.which('ffprobe'),
    'FFmpeg/FFprobe executables are not available on PATH; install FFmpeg to run real media delivery tests',
)
class VideoDeliveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.media_tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.media_tmp.cleanup)
        root = Path(cls.media_tmp.name).resolve()
        cls.source = root / 'source.mp4'
        executor = v.renderer_module()
        ffmpeg = executor.resolve_media_tool('ffmpeg')
        subprocess.run([ffmpeg, '-v', 'error', '-n', '-f', 'lavfi', '-i', 'color=c=blue:s=160x240:r=10',
                        '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000', '-t', '3',
                        '-c:v', 'libx264', '-preset', 'ultrafast', '-threads', '1', '-c:a', 'aac',
                        str(cls.source)], check=True, capture_output=True, timeout=30)
        cls.subtitles = root / 'synthetic.srt'
        cls.subtitles.write_text('1\n00:00:00,100 --> 00:00:00,900\nhello\n\n2\n00:00:02,100 --> 00:00:02,800\noutro\n', encoding='utf8')
        cls.final = root / 'burned.mp4'
        cls.receipt = root / 'render.json'
        arial_escaped = _system_font('arial.ttf').replace(':', r'\:')
        vf = f"drawtext=fontfile='{arial_escaped}':text='AI-assisted':x=16:y=96:fontsize=8:fontcolor=white,"
        vf += "subtitles='" + cls.subtitles.as_posix().replace(':', r'\:') + "'"
        executor.execute_ffmpeg_with_receipt('render',
            ['ffmpeg', '-v', 'error', '-n', '-i', str(cls.source), '-vf', vf,
             '-c:v', 'libx264', '-preset', 'ultrafast', '-threads', '1', '-c:a', 'copy', str(cls.final)],
            [dict(role='candidate', path=str(cls.source)), dict(role='subtitles', path=str(cls.subtitles))],
            [dict(role='candidate', path=str(cls.final))], cls.receipt, timeout_s=30)

    def setUp(self):
        self.helper = cover_fixture.CoverStrategyTests('test_output_matrix_and_review_must_cover_every_ratio')
        self.helper.setUp()
        self.addCleanup(self.helper.doCleanups)
        self.root = self.helper.root
        self.serial = 0
        self.m = v.init(self.helper.brief['project_id'])
        self.m['material_intake_ref'] = w.reference(self.save(dict(
            schema=v.materials.INTAKE_SCHEMA, project_id=self.m['project_id'],
            scope_note='Synthetic source pattern and tone, no imported or embedded media.', assets=[])))
        self.m['background_music']=dict(decision='not_used',reason='Synthetic source tone stands for reviewed dialogue; no background track.')
        from execution_context_fixture import make_context
        self.m['context_manifest_ref']=make_context(self.root)
        self.m['script_ref'] = w.reference(self.subtitles)
        self.bind_overlay_fixture()
        plan = v.cta.empty_plan(self.m['project_id'], self.m['script_ref'])
        for choice in plan['decisions'].values():
            choice.update(decision='not_used', reason='Synthetic teaching fixture ends with its own payoff; no requested action.')
        self.m['cta_plan_ref'] = w.reference(self.save(plan))
        feedback = self.root / 'feedback.json'
        feedback.write_text('{"human_correction":"outro is a separate edit, not a reaction"}', encoding='utf8')
        self.m['facts'] = dict(story='Synthetic teaching and reaction', do_not_infer=['Do not invent an outro reaction'],
            feedback=[dict(id='f1', ref=w.reference(feedback), decision='applied', application='Separate outro in copy')])
        self.m['edited_media'] = w.reference(self.source)
        self.m['timeline'] = dict(duration_seconds=3, segments=[dict(id='s1', source_ref=w.reference(self.source),
            source_start=0, source_end=3, target_start=0, target_end=3, speed=1, purpose='synthetic full cut')],
            expected_audio=[dict(segment_id='s1', source_start=.1, source_end=.9, kind='speech'),
                            dict(segment_id='s1', source_start=2.1, source_end=2.8, kind='speech')])
        fixture_tests = v.ROOT.parent / 'ai-video-tools-20260708/mvp-video-pipeline/tests'
        sys.path.insert(0,str(fixture_tests))
        from segment_level_fixture import make_review
        audio_review=make_review(self.root/'audio-levels',self.source,[dict(start=0,end=3)],
            [dict(start=.1,end=.9),dict(start=2.1,end=2.8)],after_media=self.source)
        self.m['rough_audio_review_ref']=w.reference(self.save(audio_review))
        self.bind_rough_cut_fixture()
        omission = w.reference(self.save({'role':'user','text':'本期不使用内置进度条。'}))
        self.m['progress_overlay']=v.progress.select(
            self.m,'not_used','Synthetic short delivery fixture; explicitly no progress overlay',
            omission_source_ref=omission)
        self.asr = dict(schema='video_knowledge_pipeline.subtitle_asr_observations.v1', status='completed', segments=[
            dict(start_seconds=.1, end_seconds=.9, text='hello'), dict(start_seconds=2.1, end_seconds=2.8, text='outro')])
        asr_path = self.save(self.asr)
        self.req = dict(source_path=str(self.source), source_sha256=w.digest(self.source), duration_seconds=3,
                        asr_binding=dict(source_sha256=w.digest(self.source), asr_sha256=w.digest(asr_path)),
                        observations=[], expected_audio=v.timeline(self.m)['expected_audio'], omissions=[])
        self.pack = dict(requests=[dict(review_id='synthetic-review', artifact_sha256=w.digest(self.source),
                        full_source_review=True, review_start_seconds=0, review_end_seconds=3,
                        subtitle_cues=copy.deepcopy(self.asr['segments']))])
        self.m['subtitles'] = dict(request_ref=w.reference(self.save(self.req)), pack_ref=w.reference(self.save(self.pack)),
                                   asr_ref=w.reference(asr_path), review_ref=None)
        self.approve_coverage()
        self.data, _ = self.helper.desk()
        # Synthetic evidence for the five configured platforms, never real account approval.
        item = self.data['items'][0]
        item['cta_plan_ref'] = self.m['cta_plan_ref']
        item['platforms'].pop('weibo', None)  # optional, no verified ratio profile yet
        self.data['target_platforms'] = list(item['platforms'])
        for option in item['cover_pk']['candidates']:
            option.update(title='Synthetic '+option['id'],hypothesis='Distinct synthetic angle '+option['id'])
        candidate = item['cover_pk']['candidates'][0]['cover_by_ratio']
        from datetime import date
        for key, p in item['platforms'].items():
            profile = desk.platform_policy()['platforms'][key]
            ratios = profile['cover_ratios'][:1] if profile['cover_mode']=='one' else profile['cover_ratios']
            p['cover_ids'] = [candidate[r] for r in ratios]
            if key == 'weixin_channels': p['fields']['short_title']='Synthetic'
            for check in p['platform_checks'].values():
                check.update(status='confirmed', evidence='synthetic fixture only', checked_at=date.today().isoformat())
        self.data['items'][0]['video'] = w.reference(self.final)
        self.data['editorial_context'] = dict(story=self.m['facts']['story'], do_not_infer=self.m['facts']['do_not_infer'])
        for p in self.data['items'][0]['platforms'].values():
            p['fields'].update(title='Synthetic', body='Not a real family', tags='#synthetic')
        self.data['items'][0]['platforms']['kuaishou']['fields'].pop('title',None)
        self.data['items'][0]['platforms']['weixin_channels']['fields'].pop('title',None)
        self.bind_desk()
        self.m['render_receipt_ref'] = w.reference(self.receipt)
        self.accept()

    def save(self, data):
        self.serial += 1
        path = self.root / f'delivery-{self.serial}.json'
        w.write(path, data)
        return path

    def test_material_intake_and_export_stages_block_omissions(self):
        def stage(report, name):
            return next(row for row in report['checks'] if row['stage'] == name)
        self.assertEqual(stage(self.audit(), 'material_actual_use_after_export')['status'], 'passed')
        self.m['material_final_review_ref'] = None
        self.assertEqual(stage(self.audit(), 'material_actual_use_after_export')['reason'],
                         'material_final_review_required')
        self.m['material_intake_ref'] = None
        self.assertEqual(stage(self.audit('preflight'), 'material_intake_before_edit')['reason'],
                         'material_intake_required')

    def approve_coverage(self):
        report = v.subtitle_check(self.m, v.timeline(self.m))
        receipt = dict(input_fingerprint=report['input_fingerprint'], source_sha256=w.digest(self.source),
            review_id='synthetic-review', full_timeline_listened=True, full_timeline_viewed=True,
            reviewer='synthetic fixture only, no real human', reviewed_at='2026-09-27T20:00:00+08:00', decision='pass',
            resolutions={r['finding_id']: dict(decision='accepted_after_listening', reason='fixture only') for r in report['findings']})
        self.m['subtitles']['review_ref'] = w.reference(self.save(receipt))

    def bind_desk(self):
        self.m['material_final_review_ref'] = w.reference(self.save(dict(
            schema=v.materials.REVIEW_SCHEMA, project_id=self.m['project_id'],
            intake_ref=self.m['material_intake_ref'], video=self.data['items'][0]['video'],
            screen_recording_checked=True, reviewer='Synthetic fixture', sample_receipts=[], entries=[])))
        review = self.helper.passed_review(self.data)
        self.m['desk_ref'] = review['desk_ref']
        self.m['cover_review_ref'] = w.reference(self.save(review))

    def accept(self):
        self.bind_final_layout()
        self.bind_pacing_fixture()
        import performance_fixture
        performance_fixture.bind_plan(self.m, self.save)
        value = dict(schema='self-media.video-acceptance.v1', input_fingerprint=v.acceptance_fingerprint(self.m),
                     reviewer_kind='human', reviewer='synthetic contract fixture, not actual approval',
                     reviewed_at='2026-09-27T20:00:00+08:00', decision='pass', **{k: True for k in v.HUMAN_CHECKS})
        value['cta_landing'] = dict(plan_sha256=self.m['cta_plan_ref']['sha256'],
            video_sha256=self.data['items'][0]['video']['sha256'], unplanned_cta_absent=True, prepared_copy_reviewed=True,
            notes='Synthetic cut and prepared copy contain no invitation or offer; not real author approval.', observations=[])
        value['final_layout_review']=dict(video_sha256=self.data['items'][0]['video']['sha256'],
            layout_sha256=self.m['final_layout_ref']['sha256'],observations_sha256=self.m['final_observations_ref']['sha256'],
            rendered_elements_verified=True,mobile_readable=True,ai_label_visible=True,
            evidence='Synthetic gate fixture, not actual human or OCR approval.')
        value['performance_review']=performance_fixture.review(self.m,self.data['items'][0]['video'],self.save)
        self.m['acceptance_ref'] = w.reference(self.save(value))

    def bind_overlay_fixture(self, *, medical="no_medical_subject", insurance="no_insurance_subject"):
        import video_overlay_selection as overlays
        import rough_cut_checks as checks
        script = self.m["script_ref"]
        quote = next(line for line in checks.spoken_body(w.bound(script)).splitlines()
                     if len(line.strip()) >= 5 and "-->" not in line)
        self.overlay_ai = dict(mode="ai_assisted", stages=["editing"], reason="Synthetic editing fixture.")
        assessment = dict(schema=overlays.SCHEMA, script_ref=script, ai=self.overlay_ai,
            medical=dict(category=medical, reason=self.m.get("medical_overlay", {}).get("reason",
                         "Synthetic nonmedical teaching video."), evidence_quotes=[quote]),
            insurance=dict(category=insurance, reason="Synthetic insurance assessment.", evidence_quotes=[quote]))
        self.m["overlay_assessment_ref"] = w.reference(self.save(assessment))

    def bind_final_layout(self):
        final=self.data['items'][0]['video']
        if self.m.get('final_layout_ref'):
            old=v.read_ref(self.m['final_layout_ref'])
            if old['candidate']['expected_sha256']==final['sha256']:
                return
        common=Path(os.path.commonpath([str(self.root),str(Path(final['path']).parent)])).resolve()
        evidence=self.root/'synthetic-layout-evidence.json'
        evidence.write_text('{"scope":"synthetic layout declaration; actual frames separately checked"}',encoding='utf8')
        relative=lambda ref: dict(path=Path(ref['path']).resolve().relative_to(common).as_posix(),expected_sha256=ref['sha256'])
        duration=self.m['timeline']['duration_seconds']
        layout=dict(schema_version='video-final-layout-safety.v1',layout_id='synthetic-final-layout',duration_seconds=duration,ai_disclosure=self.overlay_ai,
            candidate=relative(final),layout_evidence=relative(w.reference(evidence)),required_roles=['ai_label'],
            reserved_regions=v.renderer_module() and __import__('video_creation_pipeline.final_layout_safety',fromlist=['rounded_corner_regions']).rounded_corner_regions(),
            elements=[dict(element_id='synthetic-ai-label',role='ai_label',text='AI-assisted synthetic fixture',
                start_seconds=0,end_seconds=duration,rect=dict(x=.2,y=.1,width=.35,height=.03),critical_content=True)])
        self.m['final_layout_ref']=w.reference(self.save(layout))
        self.m['layout_workspace_root']=str(common)
        self.m['identity_overlay']=dict(decision='not_applicable',reason='Synthetic non-insurance teaching video.')
        self.serial+=1
        output=self.root/f'final-observations-{self.serial}'
        v.observe_final(self.m,output.resolve())
        self.m['final_observations_ref']=w.reference(output/'observations.json')

    def bind_rough_cut_fixture(self):
        # Synthetic gate fixture only. The real encoded tone stands in for speech.
        import rough_cut_checks as checks
        import video_review_delivery as review
        root = self.root / ('rough-proof-' + str(self.serial))
        root.mkdir()
        manifest = self.m
        media, script = manifest['edited_media'], manifest['script_ref']
        timeline = checks.ref(self.save(manifest['timeline']))
        registration = checks.register(media['path'], timeline['path'], root / 'registration.json')
        evidence = checks.ref(self.save({'synthetic_only': True}))
        proof = {'schema': checks.AUDIT_SCHEMA, 'candidate': media, 'script': script, 'timeline': timeline,
                 'registration': registration, 'vkp': [evidence], 'automatic_review': True,
                 'technical': {'duration': 3, 'candidates': [], 'decoder': evidence, 'log': evidence},
                 'comparison': {'changes': [], 'repetition_candidates': [], 'omitted_phrase_candidates': []}}
        audit = root / 'rough-cut-check.json'
        checks.write_new(audit, proof)
        request = root / 'review-request.json'
        checks.write_new(request, {'schema_version': 'self-media-human-review-request-pack.v1',
            'scope': 'post_cut_check:' + checks.ref(audit)['sha256'], 'requests': [checks.automatic_item(proof)]})
        bundle = root / 'review'
        review.prepare(request, bundle, 'rough_cut_recipe')
        manifest['rough_cut_delivery_ref'] = registration
        manifest['rough_cut_acceptance_ref'] = checks.save_automatic_review(audit, bundle)

    def test_formal_delivery_requires_rough_cut_receipt_and_current_timeline(self):
        original = self.m['rough_cut_delivery_ref']
        self.m['rough_cut_delivery_ref'] = None
        row = next(r for r in self.audit()['checks'] if r['stage'] == 'rough_cut_vkp_acceptance')
        self.assertEqual(row['reason'], 'rough_cut_delivery_required')
        self.m['rough_cut_delivery_ref'] = original
        self.m['timeline']['segments'][0]['source_start'] = .02
        row = next(r for r in self.audit()['checks'] if r['stage'] == 'rough_cut_vkp_acceptance')
        self.assertEqual(row['reason'], 'rough_cut_acceptance_timeline_mismatch')

    def test_performance_is_a_live_preflight_and_final_gate(self):
        pending=self.root/'pending-performance-review.json'
        with contextlib.redirect_stdout(io.StringIO()):
            code=v.main(['performance-review-template','--input',str(self.save(self.m)),'--output',str(pending)])
        self.assertEqual(0,code)
        self.assertTrue(all(r['status']=='pending' for r in w.read(pending)['observations']))
        original=self.m['performance_plan_ref']
        self.m['performance_plan_ref']=None
        report=self.audit('preflight')
        self.assertFalse(report['preflight_ready'])
        self.assertTrue(any(c['stage']=='performance_execution_plan' and c['status']=='blocked' for c in report['checks']))
        self.m['performance_plan_ref']=original
        acceptance=w.read(w.bound(self.m['acceptance_ref']))
        acceptance.pop('performance_review')
        self.m['acceptance_ref']=w.reference(self.save(acceptance))
        report=self.audit()
        self.assertFalse(report['complete'])
        self.assertTrue(any(c['stage']=='human_acceptance' and 'performance_final_review_required' in c.get('reason','') for c in report['checks']))

    def test_sourced_performance_requirement_reaches_the_actual_consumer(self):
        from execution_context_fixture import make_context
        schema={'type':'object','required':['performance_plan'],'properties':{
            'performance_plan':{'type':'object','required':['cues'],'properties':{
                'cues':{'type':'array','contains':{'type':'object','required':['kind'],
                    'properties':{'kind':{'const':'emphasis'}}}}}}}}
        self.m['context_manifest_ref']=make_context(self.root,[dict(id='emphasis-required',
            consumer='video_delivery',schema=schema)],name='emphasis-context')
        self.accept()
        report=self.audit()
        self.assertFalse(report['complete'])
        self.assertTrue(any(c['stage']=='current_execution_requirements' and 'emphasis-required' in c.get('reason','') for c in report['checks']))
        plan=v.read_ref(self.m['performance_plan_ref']);plan['cues'][0]['kind']='emphasis'
        self.m['performance_plan_ref']=w.reference(self.save(plan))
        acceptance=v.read_ref(self.m['acceptance_ref'])
        import performance_fixture
        acceptance['performance_review']=performance_fixture.review(self.m,self.data['items'][0]['video'],self.save)
        acceptance['input_fingerprint']=v.acceptance_fingerprint(self.m)
        self.m['acceptance_ref']=w.reference(self.save(acceptance))
        self.assertTrue(self.audit()['complete'])

    def test_cta_plan_and_final_observations_are_separate_delivery_gates(self):
        acceptance = w.read(w.bound(self.m['acceptance_ref']))
        acceptance.pop('cta_landing')
        self.m['acceptance_ref'] = w.reference(self.save(acceptance))
        report = self.audit()
        self.assertFalse(report['complete'])
        self.assertTrue(any(c['stage']=='human_acceptance' and 'cta_final_landing_review_required' in c.get('reason','') for c in report['checks']))
        self.m['cta_plan_ref'] = None
        report = self.audit('preflight')
        self.assertFalse(report['preflight_ready'])
        self.assertEqual(report['next_action'], 'cta_selection_and_position')

    def test_final_layout_missing_cannot_be_replaced_by_prepared_label_files(self):
        self.m['final_layout_ref']=None
        report=self.audit()
        row=next(r for r in report['checks'] if r['stage']=='final_media_layout_and_observations')
        self.assertEqual(row['status'],'blocked')
        self.assertIn('default_AI_disclosure',row['reason'])

    def test_final_frames_must_match_actual_encoded_media_not_arbitrary_pictures(self):
        from PIL import Image
        packet=v.read_ref(self.m['final_observations_ref'])
        path=self.root/'fake-observation.jpg';Image.new('RGB',(160,240),'green').save(path)
        packet['frames'][0]['frame_ref']=w.reference(path)
        self.m['final_observations_ref']=w.reference(self.save(packet))
        report=self.audit()
        row=next(r for r in report['checks'] if r['stage']=='final_media_layout_and_observations')
        self.assertEqual(row['status'],'blocked')
        self.assertIn('not_from_current_media',row['reason'])

    def test_final_insurance_identity_source_alone_does_not_prove_it_was_rendered(self):
        source=self.save(dict(identity='Synthetic author',institution='Synthetic institution',license_number='SYNTHETIC-ONLY'))
        self.m['identity_overlay']=dict(decision='required',reason='Synthetic insurance applicability',source_ref=w.reference(source))
        self.bind_overlay_fixture(insurance='insurance_discussion')
        report=self.audit()
        row=next(r for r in report['checks'] if r['stage']=='final_media_layout_and_observations')
        self.assertEqual(row['status'],'blocked')
        self.assertIn('coverage_missing',row['reason'])

    def test_final_context_and_observations_are_separate_from_old_human_checkboxes(self):
        self.m.pop('context_manifest_ref')
        report=self.audit()
        self.assertFalse(report['complete'])
        self.assertEqual(next(r['status'] for r in report['checks'] if r['stage']=='current_execution_requirements'),'blocked')
        acceptance=w.read(w.bound(self.m['acceptance_ref']));acceptance.pop('final_layout_review')
        self.m['acceptance_ref']=w.reference(self.save(acceptance))
        report=self.audit()
        self.assertEqual(next(r['status'] for r in report['checks'] if r['stage']=='human_acceptance'),'blocked')

    def test_final_BGM_cannot_be_silently_omitted_or_repeat_a_short_passage(self):
        self.m.pop('background_music')
        report=self.audit('preflight')
        self.assertEqual(next(r['status'] for r in report['checks'] if r['stage']=='BGM_selection_and_arrangement'),'blocked')
        plan=dict(layers=[dict(asset_id='same',timeline_start_s=0,duration_s=3,source_start_s=0,source_end_s=.1,loop=True)],
                  asset_sources=dict(same=dict(sha256='a'*64,duration_s=30)))
        self.m['background_music']=dict(decision='use',reason='Synthetic misuse of a very short loop',plan_ref=w.reference(self.save(plan)))
        report=self.audit('preflight')
        self.assertIn('BGM_arrangement_blocked',next(r['reason'] for r in report['checks'] if r['stage']=='BGM_selection_and_arrangement'))

    def test_synthetic_BGM_requires_actual_source_and_current_specific_listening(self):
        plan=dict(layers=[dict(asset_id='synthetic',timeline_start_s=0,duration_s=3,source_start_s=0,source_end_s=3,loop=False)],
            asset_sources=dict(synthetic=dict(**w.reference(self.source),duration_s=3)))
        self.m['background_music']=dict(decision='use',reason='Synthetic metadata fixture, not a real BGM listening approval.',plan_ref=w.reference(self.save(plan)))
        self.assertEqual(v.bgm_selection(self.m)['source_refs'][0]['artifact_ref'],w.reference(self.source))
        self.accept()
        self.assertIn('actual_final_BGM_balance',next(r['reason'] for r in self.audit()['checks'] if r['stage']=='human_acceptance'))
        receipt=v.read_ref(self.m['acceptance_ref'])
        receipt['bgm_review']=dict(video_sha256=self.data['items'][0]['video']['sha256'],
            plan_sha256=self.m['background_music']['plan_ref']['sha256'],balance_checked=True,arrangement_listened=True)
        self.m['acceptance_ref']=w.reference(self.save(receipt))
        self.assertTrue(self.audit()['complete'])
        plan['asset_sources']['synthetic']['path']=str(self.root/'not-an-audio-file.wav')
        self.m['background_music']['plan_ref']=w.reference(self.save(plan))
        with self.assertRaises(ValueError):v.bgm_selection(self.m)

    def audit(self, phase='delivery'):
        return v.audit(self.save(self.m), phase)

    def bind_pacing_fixture(self):
        import video_pacing as pacing
        final = self.data['items'][0]['video']
        pack = w.read(w.bound(self.m['subtitles']['pack_ref']))
        pack['requests'][0]['artifact_sha256'] = final['sha256']
        pack_ref = w.reference(self.save(pack))
        chunks = self.save(dict(source=final))
        raw = self.save(dict(canonical_complete=True, chunk_manifest_path=str(chunks), duration_seconds=3,
            result=[dict(words=['hello', 'outro'], timestamp=[[100,900],[2100,2800]],
                         chunk_offset_seconds=0, chunk_core_start_seconds=0, chunk_core_end_seconds=3)]))
        transcript = self.save(dict(source_path=str(raw), segments=self.asr['segments']))
        run = self.save(dict(schema='video_knowledge_local_video_run.v1', ok=True, selected_media_path=final['path'],
            transcript_path=str(transcript), asr_run=dict(execute=True, provider='sensevoice', raw_output_json=str(raw))))
        log = self.root/'synthetic-pacing.log'
        log.write_text('Synthetic test log', encoding='utf-8')
        log_ref = w.reference(log)
        decoder = self.save(dict(outlet_id=pacing.OUTLET, status='completed', operation='technical_qa',
            command=[pacing.SILENCE_FILTER], inputs=[dict(artifact=final)], outputs=[dict(artifact=log_ref)]))
        refs, metrics = pacing.measure(final, pack, run, 3., '')
        report = dict(schema=pacing.SCHEMA, candidate=final, script=self.m['script_ref'], subtitles=pack_ref,
            source_subtitles=self.m['subtitles']['pack_ref'], vkp=refs, audio_log=log_ref,
            decoder=w.reference(decoder), metrics=metrics)
        self.m['pacing_report_ref'] = w.reference(self.save(report))

    def test_final_pacing_gate_rejects_missing_and_stale_versions(self):
        def stage(report):
            return next(row for row in report['checks'] if row['stage'] == 'current_final_video_pacing')

        self.assertEqual(stage(self.audit())['status'], 'passed')
        report = self.m.pop('pacing_report_ref')
        self.assertEqual(stage(self.audit())['reason'], 'current_video_pacing_report_required')
        self.m['pacing_report_ref'] = report
        self.data['items'][0]['video'] = w.reference(self.source)
        self.bind_desk()
        self.assertEqual(stage(self.audit())['reason'], 'video_pacing_report_is_for_another_version')
        self.data['items'][0]['video'] = w.reference(self.final)
        self.bind_desk()
        self.m['subtitles']['pack_ref'] = w.reference(self.save(dict(self.pack, revision=2)))
        self.assertEqual(stage(self.audit())['reason'], 'video_pacing_report_is_for_another_version')

    def test_real_synthetic_chain_and_cli_delivery(self):
        report = self.audit()
        self.assertTrue(report['complete'], report)
        self.assertFalse(report['publish_authorized'])
        self.assertTrue(self.audit('preflight')['preflight_ready'])
        path = self.save(self.m)
        out = self.root / 'complete.html'
        command = [sys.executable, '-B', str(v.ROOT / 'scripts/self_media_agent.py'), 'video-delivery',
                   'deliver', '--input', str(path), '--output', str(out)]
        run = subprocess.run(command, capture_output=True, text=True, encoding='utf8', timeout=30)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn('verified_at_generation', out.read_text(encoding='utf8'))
        repeated = subprocess.run(command, capture_output=True, timeout=30)
        self.assertEqual(repeated.returncode, 2)

    def test_segment_audio_gate_cannot_be_replaced_by_whole_track_pass(self):
        self.m['rough_audio_review_ref']=None
        self.accept()
        report=self.audit('preflight')
        self.assertFalse(report['preflight_ready'])
        self.assertEqual(report['next_action'],'rough_cut_segment_speech_levels')
        self.assertIn('whole_track_LUFS',next(c['reason'] for c in report['checks'] if c['status']=='blocked'))

    def test_segment_audio_post_measurement_and_current_speech_coverage_required(self):
        original=v.read_ref(self.m['rough_audio_review_ref'])
        self.m['rough_audio_review_ref']=w.reference(self.save({**original,'after_ref':None}))
        self.assertFalse(self.audit('preflight')['preflight_ready'])
        self.m['rough_audio_review_ref']=w.reference(self.save(original))
        self.m['timeline']['expected_audio'][0]['source_start']=.2
        report=self.audit('preflight')
        self.assertEqual(next(c['status'] for c in report['checks'] if c['stage']=='rough_cut_segment_speech_levels'),'blocked')

    def test_multisource_editor_uses_bound_edited_clock_without_forcing_a_route(self):
        from segment_level_fixture import make_review
        timeline=self.m['timeline']
        timeline['segments'][0].update(source_end=1.5,target_end=1.5)
        timeline['segments'].append(dict(id='s2',source_ref=w.reference(self.final),source_start=0,
            source_end=1.5,target_start=1.5,target_end=3,speed=1,purpose='synthetic second source'))
        timeline['expected_audio'][1].update(segment_id='s2',source_start=.6,source_end=1.3)
        mapped=v.timeline(self.m)
        review=make_review(self.root/'multi-audio',self.final,
            [dict(start=0,end=1.5),dict(start=1.5,end=3)],
            [dict(start=r['start_seconds'],end=r['end_seconds']) for r in mapped['expected_audio']],
            after_media=self.source,analysis_clock='edited_timeline')
        review['timeline_ref']=w.reference(self.save(timeline))
        self.m['rough_audio_review_ref']=w.reference(self.save(review))
        self.assertTrue(v.rough_audio_check(self.m,mapped)['rough_cut_audio_accepted'])
        self.m['timeline']['segments'][1]['purpose']='changed timeline version'
        with self.assertRaisesRegex(ValueError,'timeline_binding'): v.rough_audio_check(self.m,mapped)

    def test_actual_subtitle_then_progress_chain_passes_all_delivery_gates(self):
        self.actual_progress_chain('plain')

    def test_actual_script_heading_and_default_navigation_font_render_through_delivery(self):
        self.actual_progress_chain('chapters')

    def actual_progress_chain(self,mode):
        from video_creation_pipeline import progress_overlay
        from video_creation_pipeline.review_resource_guard import ReviewResourcePolicy
        root=Path(os.environ['TEMP']).resolve()
        packaging={'schema':'video_creation_pipeline.video_packaging_plan.v1',
            'output':{'width':160,'height':240,'fps':10},
            'scenes':[{'scene_id':'scene-0','start_s':0,'end_s':3}]}
        spec={'mode':'plain','position':'bottom','margin_x_px':10,'edge_offset_px':8,
            'bar_height_px':4,'track_color':'CCCCCC','fill_color':'196E65',
            'color_reason':'synthetic labelled playback test'}
        if mode=='chapters':
            script=self.root/'video-script.md';script.write_text('# Synthetic video\n## 01｜Opening\nSynthetic speech fixture.\n## 02｜Outcome\n',encoding='utf-8')
            self.m['script_ref']=w.reference(script)
            self.bind_rough_cut_fixture()
            self.bind_overlay_fixture()
            cta_plan=w.read(w.bound(self.m['cta_plan_ref']))
            cta_plan['script_ref']=self.m['script_ref']
            self.m['cta_plan_ref']=w.reference(self.save(cta_plan))
            self.data['items'][0]['cta_plan_ref']=self.m['cta_plan_ref']
            packaging['scenes']=[{'scene_id':'scene-0','start_s':0,'end_s':1.5},
                                 {'scene_id':'scene-1','start_s':1.5,'end_s':3}]
            spec.update(mode='chapters',font_file=_system_font('msyh.ttc'))
        evidence=self.root/'layout-evidence.txt';evidence.write_text('Synthetic subtitle area, not a real-video layout review')
        relative=lambda p:dict(path=p.resolve().relative_to(root).as_posix(),expected_sha256=w.digest(p))
        layout={'schema_version':'video-final-layout-safety.v1','layout_id':'synthetic-progress-delivery',
            'duration_seconds':3,'candidate':relative(self.final),'layout_evidence':relative(evidence),
            'required_roles':['subtitle','ai_label'],'elements':[dict(element_id='synthetic-subtitles',role='subtitle',
            start_seconds=0,end_seconds=3,critical_content=True,rect=dict(x=.1,y=.75,width=.8,height=.15)),
            dict(element_id='synthetic-ai-label',role='ai_label',text='AI-assisted',start_seconds=0,end_seconds=3,
                 critical_content=True,rect=dict(x=.1,y=.4,width=.8,height=.1))],
            'reserved_regions':[dict(region_id=f'corner-{i}',region_kind='rounded_corner',
             rect=dict(x=x,y=y,width=.02,height=.02)) for i,(x,y) in enumerate([(0,0),(.98,0),(0,.98),(.98,.98)])]}
        layout['reserved_regions'].append(dict(region_id='platform-controls',region_kind='platform_overlay',
            rect=dict(x=0,y=.92,width=1,height=.08)))
        pp,sp,lp=self.save(packaging),self.save(spec),self.save(layout)
        self.m['render_chain_refs']=[w.reference(self.receipt)]
        self.m['progress_overlay']=v.progress.select(self.m,'use','Synthetic proof of normal subtitle then progress rendering',
            packaging_ref=w.reference(pp),spec_ref=w.reference(sp),layout_ref=w.reference(lp),
            workspace_root=root,program_ref=w.reference(self.final))
        self.assertEqual(v.progress.check(self.m,'preflight')['status'],'selection_and_reservation_checked')
        plan=progress_overlay.build(self.final,pp,lp,sp,root,script_ref=self.m.get('script_ref'));plan_path=self.save(plan)
        self.assertGreater(plan['geometry']['rect']['y'], .9)
        self.assertIn({'element_id': 'progress-overlay', 'region_id': 'platform-controls'},
                      plan['layout_check']['auxiliary_reserved_region_overlaps'])
        if mode=='chapters':
            self.assertEqual([r['text'] for r in plan['chapters']],['01/02  Opening','02/02  Outcome'])
            self.assertEqual(plan['typography']['preset_id'],'compact')
            self.assertFalse(plan['typography']['body_and_subtitle_minima_applied'])
        output=self.root/'with-progress'
        result=progress_overlay.render(plan_path,output,resource_policy=ReviewResourcePolicy(
            policy_id='synthetic-progress-delivery-chain',min_available_memory_bytes=3*1024**3,
            min_available_memory_percent=10,ffmpeg_threads=1))
        self.m['progress_overlay']['result_ref']=w.reference(output/'result.json')
        self.m['render_receipt_ref']=w.reference(output/'render-receipt.json')
        self.data['items'][0]['video']=w.reference(Path(result['candidate']['path']))
        self.bind_desk();self.accept()
        acceptance=w.read(w.bound(self.m['acceptance_ref']))
        acceptance.update({k:True for k in v.progress.HUMAN_CHECKS if k!='progress_chapter_boundaries_correct'})
        if mode=='chapters':acceptance['progress_chapter_boundaries_correct']=True
        self.m['acceptance_ref']=w.reference(self.save(acceptance))
        report=self.audit()
        self.assertTrue(report['complete'],report)
        self.assertTrue(any(c['stage']=='progress_render_and_layout' and c['status']=='passed' for c in report['checks']))
        self.m['progress_overlay']['result_ref']=None
        self.assertFalse(self.audit()['complete'])

    def test_missing_tail_cannot_be_waived_with_generic_pass(self):
        self.pack['requests'][0]['subtitle_cues'].pop()
        self.m['subtitles']['pack_ref'] = w.reference(self.save(self.pack))
        self.approve_coverage()  # Existing inspector permits recorded listening; wrapper requires explicit omission/cue.
        self.accept()
        result = self.audit('preflight')
        self.assertFalse(result['preflight_ready'])
        self.assertEqual(result['next_action'], 'subtitles')

    def test_stale_subtitle_review_and_changed_feedback(self):
        self.pack['requests'][0]['subtitle_cues'][0]['text'] = 'actual human lyric'
        self.m['subtitles']['pack_ref'] = w.reference(self.save(self.pack))
        self.assertFalse(self.audit()['complete'])
        Path(self.m['facts']['feedback'][0]['ref']['path']).write_text('new correction', encoding='utf8')
        result = self.audit()
        self.assertEqual(result['next_action'], 'context')

    def test_unresolved_feedback_and_missing_history_declaration(self):
        self.m['facts']['feedback'][0]['application'] = ''
        self.assertEqual(self.audit()['next_action'], 'context')
        self.m['facts']['feedback'] = []
        self.assertEqual(self.audit()['next_action'], 'context')

    def test_source_time_mapping_and_known_outro_required(self):
        self.m['timeline']['segments'][0]['target_end'] = 2
        self.assertEqual(self.audit()['next_action'], 'timeline')
        self.m['timeline']['segments'][0]['target_end'] = 3
        self.req['expected_audio'].pop()
        self.m['subtitles']['request_ref'] = w.reference(self.save(self.req))
        self.assertEqual(self.audit()['next_action'], 'subtitles')

    def test_changed_final_and_invalid_renderer_receipt(self):
        broken = w.read(self.receipt); broken['inputs'][0]['artifact']['sha256'] = '0'*64
        self.m['render_receipt_ref'] = w.reference(self.save(broken))
        self.accept()
        self.assertEqual(self.audit()['next_action'], 'render_and_desk')

    def test_missing_ratio_and_stale_cover_review(self):
        del self.data['items'][0]['cover_pk']['candidates'][0]['cover_by_ratio']['4:3']
        new_desk = self.save(self.data)
        review = v.read_ref(self.m['cover_review_ref']); review['desk_ref'] = w.reference(new_desk)
        self.m['desk_ref'] = w.reference(new_desk)
        self.m['cover_review_ref'] = w.reference(self.save(review)); self.accept()
        report=self.audit()
        self.assertEqual(report['next_action'], 'render_and_desk')
        self.assertEqual(next(c for c in report['checks'] if c['stage']=='covers')['status'],'blocked')

    def test_local_delivery_does_not_invent_platform_submission_checks(self):
        for p in self.data['items'][0]['platforms'].values():
            p['platform_checks']={}
        self.bind_desk();self.accept()
        self.assertTrue(self.audit()['complete'])
        self.assertFalse(desk.check_platforms(self.data,'submission')['complete'])

    def test_requested_motion_requires_specific_current_final_observation(self):
        self.pack['requests'][0]['subtitle_cues'][0].update(speaker='child',motion='bounce',font_size_1080=96)
        self.m['subtitles']['pack_ref']=w.reference(self.save(self.pack))
        self.approve_coverage()
        self.assertEqual(self.audit()['next_action'], 'frame_safety_before_render')
        canvas = [160, 240]
        times = [.25]
        composition = w.reference(self.save({'scope': 'synthetic frame measurement'}))
        measured = w.reference(self.save(dict(schema='self-media.compositor-frame-measurements.v1',
            canvas=canvas, composition_ref=composition,
            samples=[dict(time_seconds=.25, bounds={'caption': [12, 180, 148, 220]})])))
        plan = dict(schema=v.framing.SCHEMA, project_id=self.m['project_id'], canvas=canvas, duration_seconds=3,
            composition_ref=composition, sources=[dict(stage='program', artifact_ref=self.m['edited_media'])],
            layers=[dict(id='caption', role='subtitle', start_seconds=.1, end_seconds=.9)],
            sample_times_seconds=times, measurements_ref=measured)
        plan_ref = w.reference(self.save(plan))
        checked = v.framing.check_ref(plan_ref, v.framing.probe_media)
        self.m['frame_safety_plan_ref'] = plan_ref
        self.m['frame_safety_review_ref'] = w.reference(self.save({**checked, 'plan_ref': plan_ref}))
        self.m['final_layout_ref'] = None
        self.accept()
        report=self.audit()
        self.assertEqual(report['next_action'],'human_acceptance')
        self.assertEqual(v.read_ref(self.m['final_observations_ref'])['approved_sample_times_seconds'], times)
        acceptance=v.read_ref(self.m['acceptance_ref'])
        acceptance.update(speaker_styles_consistent=True,preview_export_consistent=True,requested_motion_visible=True)
        acceptance['final_layout_review']['checked_frame_safety_times_seconds'] = times
        self.m['acceptance_ref']=w.reference(self.save(acceptance))
        self.assertTrue(self.audit()['complete'])

    def test_extra_packaging_constraints_reach_actual_delivery(self):
        self.data['editorial_context']['forbidden_public_phrases']=['never reveal this']
        self.bind_desk();self.accept()
        self.assertTrue(self.audit()['complete'])
        self.data['items'][0]['platforms']['xiaohongshu']['fields']['body']='never reveal this'
        self.bind_desk();self.accept()
        report=self.audit()
        self.assertFalse(report['complete'])
        self.assertIn('packaging_requirements_incomplete',str(report['checks']))

    def test_blank_copy_and_fact_drift_block_delivery(self):
        self.data['items'][0]['platforms']['douyin']['fields']['body'] = ''
        self.bind_desk(); self.accept()
        self.assertEqual(self.audit()['next_action'], 'render_and_desk')
        self.data['items'][0]['platforms']['douyin']['fields']['body'] = 'restored'
        self.data['editorial_context']['story'] = 'wrong inherited story'
        self.bind_desk(); self.accept()
        self.assertEqual(self.audit()['next_action'], 'render_and_desk')

    def test_acceptance_binds_copy_version_not_just_video(self):
        self.data['items'][0]['platforms']['douyin']['fields']['title'] = 'new unreviewed title'
        self.bind_desk()
        self.assertEqual(self.audit()['next_action'], 'human_acceptance')

    def test_draft_stays_possible_but_cannot_claim_complete(self):
        page = desk.render(desk.new_project('draft', 'not ready'))
        self.assertIn('data-state="draft"', page)
        self.assertIn('草稿预览', page)
        self.m['acceptance_ref'] = None
        path = self.save(self.m)
        out = self.root / 'must-not-exist.html'
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(v.main(['deliver', '--input', str(path), '--output', str(out)]), 2)
        self.assertFalse(out.exists())

    def render_job(self):
        output = self.root / 'guarded.mp4'
        return dict(schema='self-media.local-render-job.v1',
            preflight_fingerprint=v.acceptance_fingerprint(self.m), project_root=str(self.root),
            inputs=[dict(role='candidate', artifact=w.reference(self.source))],
            output=str(output), receipt=str(self.root/'guarded-receipt.json'),
            command=['ffmpeg','-hide_banner','-n','-i',str(self.source),'-c:v','copy','-c:a','copy',str(output)])

    def test_render_never_executes_without_current_preflight(self):
        self.m['subtitles']['review_ref'] = None
        with mock.patch.object(v.renderer_module(), 'execute_ffmpeg_with_receipt') as execute:
            result = v.guarded_render(self.save(self.m), self.save(self.render_job()))
            self.assertEqual(result['status'], 'blocked')
            execute.assert_not_called()

    def test_render_rejects_shell_overwrite_and_unbound_input(self):
        for kind in ('shell', 'overwrite', 'input', 'stale'):
            job = self.render_job()
            if kind == 'shell': job['command'][0] = 'powershell'
            if kind == 'overwrite': job['command'][2] = '-y'
            if kind == 'input': job['command'][4] = 'https://example.invalid/video.mp4'
            if kind == 'stale': job['preflight_fingerprint'] = '0'*64
            with self.subTest(kind=kind), mock.patch.object(v.renderer_module(), 'execute_ffmpeg_with_receipt') as execute:
                with self.assertRaises(ValueError): v.guarded_render(self.save(self.m), self.save(job))
                execute.assert_not_called()

    def test_guarded_render_delegates_existing_outlet_with_fresh_disk_and_resource_guard(self):
        import artifact_lifecycle
        life = self.root/'lifecycle.json'
        artifact_lifecycle.init_manifest(argparse.Namespace(manifest=life, workspace_root=self.root,
            manifest_id='synthetic-delivery', workspace_ref='synthetic', quarantine_dir='.quarantine',
            authorize_automatic_purge=False, now=None))
        subtitle_ref = w.reference(self.subtitles)
        self.m['subtitles']['render_file_ref'] = subtitle_ref
        self.req['evidence_files'] = [subtitle_ref]
        self.m['subtitles']['request_ref'] = w.reference(self.save(self.req))
        self.approve_coverage()
        job = self.render_job()
        job['inputs'].append(dict(role='subtitles', artifact=subtitle_ref))
        vf = "subtitles='" + self.subtitles.as_posix().replace(':', r'\:') + "'"
        job['command'] = ['ffmpeg','-hide_banner','-n','-i',str(self.source),'-vf',vf,
                          '-c:v','libx264','-preset','ultrafast','-c:a','copy',job['output']]
        job.update(lifecycle_manifest_ref=w.reference(life), estimated_output_bytes=1000000)
        # Actual disk preflight and actual FFmpeg outlet; only the host-pressure
        # sampler is deterministic fixture data. Production never accepts it.
        from video_creation_pipeline import review_resource_guard as resource
        sample = { 'cpu_percent': 0, 'available_memory_bytes': 32*1024**3,
                   'available_memory_percent': 80, 'disk_busy_percent': 0 }
        with mock.patch.object(resource, 'capture_resource_snapshot', return_value=sample):
            result = v.guarded_render(self.save(self.m), self.save(job))
        self.assertEqual(result['status'], 'rendered_pending_delivery_review', result)
        receipt = v.read_ref(result['render_receipt_ref'])
        self.assertIn('resource_guard', receipt)
        self.assertFalse(result['complete'])

    def test_burned_srt_must_match_reviewed_cues(self):
        wrong = self.root/'wrong.srt'
        wrong.write_text('1\n00:00:00,100 --> 00:00:00,900\nwrong transcript\n', encoding='utf8')
        ref = w.reference(wrong)
        self.m['subtitles']['render_file_ref'] = ref
        self.req['evidence_files'] = [ref]
        self.m['subtitles']['request_ref'] = w.reference(self.save(self.req))
        self.approve_coverage()
        job = self.render_job()
        job['inputs'].append(dict(role='subtitles', artifact=ref))
        vf = "subtitles='" + wrong.as_posix().replace(':', r'\:') + "'"
        job['command'][5:5] = ['-vf', vf]
        with mock.patch.object(v.renderer_module(), 'execute_ffmpeg_with_receipt') as execute:
            with self.assertRaisesRegex(ValueError, 'burn_file_disagrees'):
                v.guarded_render(self.save(self.m), self.save(job))
            execute.assert_not_called()

    def test_no_asr_for_known_speech_is_not_silent_success(self):
        self.m['subtitles']['asr_ref'] = None
        self.assertEqual(self.audit()['next_action'], 'subtitles')

    def test_browser_edit_import_save_and_migration_invalidate(self):
        node, playwright = os.getenv('VIDEO_DELIVERY_TEST_NODE'), os.getenv('VIDEO_DELIVERY_TEST_PLAYWRIGHT')
        if not node or not playwright:
            self.skipTest('browser regression needs explicit existing Node and Playwright paths')
        path = self.save(self.m)
        complete = self.root/'complete-browser.html'
        complete.write_text(desk.render(self.data, delivery_manifest=path), encoding='utf8')
        draft = self.root/'draft-browser.html'
        draft.write_text(desk.render(self.data), encoding='utf8')
        run = subprocess.run([node, str(v.ROOT/'tests/video-delivery-browser.cjs'), playwright,
                              str(complete), str(draft), self.m['desk_ref']['path']],
                             capture_output=True, text=True, encoding='utf8', timeout=50)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn('browser_delivery_states_passed', run.stdout)


if __name__ == '__main__':
    unittest.main()
