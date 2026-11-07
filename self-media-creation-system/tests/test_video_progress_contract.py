import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
import video_delivery as delivery
import video_progress_contract as progress


class ProgressContractTests(unittest.TestCase):
    def test_missing_owner_reports_unavailable(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(progress, 'ROOT', Path(tmp)/'framework'):
                with self.assertRaisesRegex(ValueError, 'mvp_progress_component_unavailable'):
                    progress.component()

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        media=self.root/'edited.mp4';media.write_bytes(b'synthetic, not real video')
        self.manifest=delivery.init('synthetic-progress-project')
        self.manifest.update(edited_media=delivery.covers.reference(media),timeline={'duration_seconds':6,'segments':[],'expected_audio':[]})

    def test_init_does_not_silently_opt_out(self):
        self.assertEqual(self.manifest['progress_overlay']['decision'],'undecided')
        with self.assertRaisesRegex(ValueError,'progress_decision_required'):
            progress.check(self.manifest,'preflight')

    def test_planning_context_exposes_the_unresolved_choice(self):
        self.manifest['facts'].update(story='Synthetic planning context',no_prior_feedback_reason='No previous feedback for this fixture')
        context=delivery.context(self.manifest)
        self.assertEqual(context['progress_overlay_planning']['decision'],'undecided')
        self.assertTrue(context['progress_overlay_planning']['explicit_decision_required'])
        self.assertEqual(context['progress_overlay_planning']['default_title_source'],'script')
        self.assertEqual(context['progress_overlay_planning']['default_font_preset'],'compact')
        self.assertTrue(context['progress_overlay_planning']['navigation_font_independent_of_body_and_subtitles'])

    def test_explicit_not_used_requires_reason_and_current_binding(self):
        with self.assertRaisesRegex(ValueError,'reason'):
            progress.select(self.manifest,'not_used','')
        self.manifest['progress_overlay']=progress.select(self.manifest,'not_used','Synthetic immersion clip; a progress label would distract')
        self.assertEqual(progress.check(self.manifest,'delivery')['status'],'not_used_explicitly')
        self.manifest['timeline']['duration_seconds']=7
        with self.assertRaisesRegex(ValueError,'stale'):
            progress.check(self.manifest,'preflight')

    def test_missing_progress_blocks_the_actual_preflight_entry(self):
        self.manifest.pop('progress_overlay')
        path=self.root/'manifest.json';path.write_text(json.dumps(self.manifest),encoding='utf-8')
        with patch.object(delivery,'context',return_value={}),patch.object(delivery,'timeline',return_value={'expected_audio':[]}),patch.object(delivery,'subtitle_check',return_value={'findings':[],'render_ready':True}):
            report=delivery.audit(path,'preflight')
        self.assertFalse(report['preflight_ready'])
        self.assertTrue(any(r['stage']=='progress_selection_and_reservation' and r['status']=='blocked' for r in report['checks']))

    def test_selection_cannot_substitute_for_a_render(self):
        self.manifest['progress_overlay']=progress.select(self.manifest,'not_used','Synthetic no-overlay fixture')
        self.manifest['progress_overlay'].update(decision='use',reason='A chapter guide is necessary')
        with self.assertRaises((ValueError,KeyError,TypeError)):
            progress.check(self.manifest,'delivery')

    def use_config(self):
        refs={}
        for name in ('packaging','layout','spec'):
            path=self.root/(name+'.json');path.write_text('{}',encoding='utf-8');refs[name+'_ref']=delivery.covers.reference(path)
        plan={'geometry':{'rect':{'x':.1,'y':.1,'width':.8,'height':.06}},
              'output':{'duration_s':6,'fps':24,'frames':144},'layout_check':{'status':'passed'}}
        with patch.object(progress,'_plan',return_value=plan):
            config=progress.select(self.manifest,'use','Synthetic chapter navigation',workspace_root=self.root,**refs)
        self.manifest['progress_overlay']=config
        return plan

    def test_use_requires_real_reservation_inputs(self):
        with self.assertRaisesRegex(ValueError,'reservation_inputs'):
            progress.select(self.manifest,'use','Show playback position')

    def test_reservation_is_recomputed_and_cannot_be_faked_by_status(self):
        plan=self.use_config()
        with patch.object(progress,'_plan',return_value=plan):
            self.assertEqual(progress.check(self.manifest,'preflight')['status'],'selection_and_reservation_checked')
            self.manifest['progress_overlay']['reservation']['rect']['y']=.9
            with self.assertRaisesRegex(ValueError,'reservation_stale'):
                progress.check(self.manifest,'preflight')

    def test_a_checked_reservation_still_requires_an_actual_render(self):
        plan=self.use_config()
        with patch.object(progress,'_plan',return_value=plan):
            with self.assertRaisesRegex(ValueError,'render_result_required'):
                progress.check(self.manifest,'delivery',self.manifest['edited_media'])

    def test_old_templates_do_not_pass_by_omission(self):
        self.manifest['progress_overlay']=progress.select(self.manifest,'not_used','Explicit no-overlay fixture')
        self.manifest['progress_overlay']['reason']=''
        with self.assertRaisesRegex(ValueError,'reason'):
            progress.check(self.manifest,'delivery')

    def rendered_stub(self,plan):
        path=self.root/'progress-plan.json';path.write_text('{}',encoding='utf-8')
        value={'schema':progress.component().SCHEMA+'.result','technical_status':'passed',
            'candidate':self.manifest['edited_media'],'plan':delivery.covers.reference(path),'decoded_frames':144}
        result=self.root/'progress-result.json';result.write_text(json.dumps(value),encoding='utf-8')
        self.manifest['progress_overlay']['result_ref']=delivery.covers.reference(result)

    @unittest.skipUnless((progress.ROOT.parent/'ai-video-tools-20260708/mvp-video-pipeline/src/video_creation_pipeline/progress_overlay.py').is_file(), 'Full MVP progress owner is not public; integration remains unverified')
    def test_passed_labels_without_execution_evidence_cannot_pass(self):
        plan=self.use_config();self.rendered_stub(plan)
        with patch.object(progress,'_plan',return_value=plan),patch.object(progress.component(),'validate',return_value=plan):
            with self.assertRaisesRegex(ValueError,'render_evidence_required'):
                progress.check(self.manifest,'delivery',self.manifest['edited_media'])

    @unittest.skipUnless((progress.ROOT.parent/'ai-video-tools-20260708/mvp-video-pipeline/src/video_creation_pipeline/progress_overlay.py').is_file(), 'Full MVP progress owner is not public; integration remains unverified')
    def test_a_progress_render_for_another_final_video_cannot_pass(self):
        plan=self.use_config();self.rendered_stub(plan)
        other=self.root/'other.mp4';other.write_bytes(b'other project final')
        with patch.object(progress,'_plan',return_value=plan),patch.object(progress.component(),'validate',return_value=plan):
            with self.assertRaisesRegex(ValueError,'not_in_final_candidate'):
                progress.check(self.manifest,'delivery',delivery.covers.reference(other))

    @unittest.skipUnless((progress.ROOT.parent/'ai-video-tools-20260708/mvp-video-pipeline/src/video_creation_pipeline/progress_overlay.py').is_file(), 'Full MVP progress owner is not public; integration remains unverified')
    def test_a_previous_progress_plan_does_not_cover_a_new_layout(self):
        plan=self.use_config();self.rendered_stub(plan)
        changed=copy.deepcopy(plan);changed['geometry']['rect']['y']=.2
        with patch.object(progress,'_plan',return_value=plan),patch.object(progress.component(),'validate',return_value=changed):
            with self.assertRaisesRegex(ValueError,'render_plan_stale'):
                progress.check(self.manifest,'delivery',self.manifest['edited_media'])

    @unittest.skipUnless((progress.ROOT.parent/'ai-video-tools-20260708/mvp-video-pipeline/src/video_creation_pipeline/progress_overlay.py').is_file(), 'Full MVP progress owner is not public; integration remains unverified')
    def test_unrelated_intermediate_program_requires_verified_lineage(self):
        other=self.root/'unrelated.mp4';other.write_bytes(b'unrelated rendered program')
        progress.component()
        with self.assertRaisesRegex(ValueError,'program_lineage_required'):
            progress.program_source(self.manifest,{'program_ref':delivery.covers.reference(other)})

    def test_new_video_script_requires_a_new_progress_selection(self):
        script=self.root/'script.md';script.write_text('## Current title\n',encoding='utf-8')
        self.manifest['script_ref']=delivery.covers.reference(script)
        self.manifest['progress_overlay']=progress.select(self.manifest,'not_used','Synthetic explicit choice')
        script.write_text('## Updated title\n',encoding='utf-8')
        self.manifest['script_ref']=delivery.covers.reference(script)
        with self.assertRaisesRegex(ValueError,'decision_stale'):
            progress.check(self.manifest,'preflight')

    @unittest.skipUnless((progress.ROOT.parent/'ai-video-tools-20260708/mvp-video-pipeline/src/video_creation_pipeline/progress_overlay.py').is_file(), 'Full MVP progress owner is not public; integration remains unverified')
    def test_shared_plan_receives_the_bound_video_script(self):
        script=self.root/'script.md';script.write_text('## Original title\n',encoding='utf-8')
        self.manifest['script_ref']=delivery.covers.reference(script)
        plan=self.use_config()
        with patch.object(progress.component(),'build',return_value=plan) as build:
            progress._plan(self.manifest,self.manifest['progress_overlay'])
        self.assertEqual(build.call_args.kwargs['script_ref'],self.manifest['script_ref'])


if __name__=='__main__':unittest.main()
