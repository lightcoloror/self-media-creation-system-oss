"""Real local inspectors over synthetic media; never real human/child approval."""
import contextlib
import copy
import io
import json
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


class VideoDeliveryAvailabilityTests(unittest.TestCase):
    def test_missing_full_owner_is_blocked_without_rough_cut_substitution(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(v, 'ROOT', Path(tmp) / 'framework'):
                with self.assertRaisesRegex(ValueError, 'existing_renderer_unavailable'):
                    v.renderer_module()


@unittest.skipUnless(
    (v.ROOT.parent / 'ai-video-tools-20260708/mvp-video-pipeline/src/video_creation_pipeline/execution_receipts.py').is_file(),
    'Full MVP renderer owner is separately supplied; local-rough-cut is not a substitute',
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
        vf = "subtitles='" + cls.subtitles.as_posix().replace(':', r'\:') + "'"
        vf += ",drawtext=fontfile='C\\:/Windows/Fonts/arial.ttf':text='AI-assisted':x=16:y=96:fontsize=8:fontcolor=white"
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
        self.m['background_music']=dict(decision='not_used',reason='Synthetic source tone stands for reviewed dialogue; no background track.')
        from execution_context_fixture import make_context
        self.m['context_manifest_ref']=make_context(self.root)
        self.m['script_ref'] = w.reference(self.subtitles)
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
        self.m['progress_overlay']=v.progress.select(self.m,'not_used','Synthetic short delivery fixture; explicitly no progress overlay')
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

    def approve_coverage(self):
        report = v.subtitle_check(self.m, v.timeline(self.m))
        receipt = dict(input_fingerprint=report['input_fingerprint'], source_sha256=w.digest(self.source),
            review_id='synthetic-review', full_timeline_listened=True, full_timeline_viewed=True,
            reviewer='synthetic fixture only, no real human', reviewed_at='2026-09-27T20:00:00+08:00', decision='pass',
            resolutions={r['finding_id']: dict(decision='accepted_after_listening', reason='fixture only') for r in report['findings']})
        self.m['subtitles']['review_ref'] = w.reference(self.save(receipt))

    def bind_desk(self):
        review = self.helper.passed_review(self.data)
        self.m['desk_ref'] = review['desk_ref']
        self.m['cover_review_ref'] = w.reference(self.save(review))

    def accept(self):
        self.bind_final_layout()
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
        self.m['acceptance_ref'] = w.reference(self.save(value))

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
        layout=dict(schema_version='video-final-layout-safety.v1',layout_id='synthetic-final-layout',duration_seconds=duration,
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
        spec={'mode':'plain','position':'top','margin_x_px':10,'edge_offset_px':8,
            'bar_height_px':4,'track_color':'CCCCCC','fill_color':'196E65',
            'color_reason':'synthetic labelled playback test'}
        if mode=='chapters':
            script=self.root/'video-script.md';script.write_text('# Synthetic video\n## 01｜Opening\n## 02｜Outcome\n',encoding='utf-8')
            self.m['script_ref']=w.reference(script)
            cta_plan=w.read(w.bound(self.m['cta_plan_ref']))
            cta_plan['script_ref']=self.m['script_ref']
            self.m['cta_plan_ref']=w.reference(self.save(cta_plan))
            self.data['items'][0]['cta_plan_ref']=self.m['cta_plan_ref']
            packaging['scenes']=[{'scene_id':'scene-0','start_s':0,'end_s':1.5},
                                 {'scene_id':'scene-1','start_s':1.5,'end_s':3}]
            spec.update(mode='chapters',font_file='C:/Windows/Fonts/msyh.ttc')
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
        pp,sp,lp=self.save(packaging),self.save(spec),self.save(layout)
        self.m['render_chain_refs']=[w.reference(self.receipt)]
        self.m['progress_overlay']=v.progress.select(self.m,'use','Synthetic proof of normal subtitle then progress rendering',
            packaging_ref=w.reference(pp),spec_ref=w.reference(sp),layout_ref=w.reference(lp),
            workspace_root=root,program_ref=w.reference(self.final))
        self.assertEqual(v.progress.check(self.m,'preflight')['status'],'selection_and_reservation_checked')
        plan=progress_overlay.build(self.final,pp,lp,sp,root,script_ref=self.m.get('script_ref'));plan_path=self.save(plan)
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
        self.approve_coverage();self.accept()
        report=self.audit()
        self.assertEqual(report['next_action'],'human_acceptance')
        acceptance=v.read_ref(self.m['acceptance_ref'])
        acceptance.update(speaker_styles_consistent=True,preview_export_consistent=True,requested_motion_visible=True)
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
