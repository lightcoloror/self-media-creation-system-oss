"""Cold-start and continuation routes reach existing consumers without execution."""
import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import self_media_agent as agent
import creation_route
import entry_selection
import publication_desk


class EntrySelectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=os.environ.get('TEST_TMP_ROOT', ROOT/'.test-runtime'))
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.serial=0

    def ref(self,value):
        self.serial+=1
        path=self.root/f'metadata-{self.serial}.json'
        path.write_text(json.dumps(value,ensure_ascii=False),encoding='utf8')
        return dict(path=str(path),sha256=agent.sha256_file(path))

    def request(self,kind,**changes):
        if kind in entry_selection.CREATIVE:
            changes.setdefault('platform', {'article':'wechat-article','graphic_note':'xiaohongshu',
                'short_post':'wechat-moments'}.get(kind,'youtube'))
        if kind in {'video_plan','finished_video','interview_guide'}:
            changes.setdefault('content_format','demo-video')
        return dict(schema_version='self-media-work-request.v1',request_id='synthetic-route-01',
                    requested_output=kind,selection_basis='合成入口回归，不是真实创作或授权',**changes)

    def creative(self,**changes):
        context=json.loads((ROOT/'fixtures/creation-route-v1/same-day-activity-highlights.context.json').read_text(encoding='utf8'))
        context.update(task_id='synthetic-route-01',**changes)
        return dict(creation_context=self.ref(context),creation_decision=self.ref(creation_route.resolve(context)),
                    context_manifest=self.purpose_context())

    def purpose_context(self):
        source=self.ref(dict(purpose='Synthetic purpose: understand a personal choice.', audience='Synthetic first-time readers.'))
        path=Path(source['path'])
        return self.ref(dict(schema_version='self-media-context-input.v1',task_id='synthetic-route-01',stage='draft',
            budget=dict(max_inline_bytes=4096),artifacts=[dict(artifact_id='purpose-source',role='source_manifest',
                path=path.name,expected_sha256=source['sha256'],load_mode='reference')],
            editorial_context=dict(version=1,content_id='synthetic-entry-01',
                topic_selection=dict(topic='A synthetic personal choice', origin='tool_trial', adoption='selected',
                    adoption_basis='Explicitly bounded synthetic regression only, not a publication decision.',
                    origin_source=dict(artifact_id='purpose-source',quote='Synthetic purpose: understand a personal choice.'),
                    adoption_source=dict(artifact_id='purpose-source',quote='Synthetic purpose: understand a personal choice.')),
                purpose=dict(artifact_id='purpose-source',quote='Synthetic purpose: understand a personal choice.'),
                audience=dict(artifact_id='purpose-source',quote='Synthetic first-time readers.'),
                stage_duty='Explain the synthetic personal choice without promising a universal answer.',
                current_body_artifact_id='purpose-source',feedback=[],feedback_note='No feedback in this isolated fixture.')))

    def test_discovery_has_one_existing_front_door_and_separate_layers(self):
        info=agent.capabilities()['start_here']
        self.assertIn('self_media_agent.py resolve',info['entrypoint'])
        self.assertTrue(info['no_new_business_workflow'])
        self.assertEqual(len(agent.capabilities()['workflows']),5)
        self.assertEqual(len({r['layer'] for r in info['layers']}),7)

    @unittest.skipUnless((ROOT.parent/'ai-video-tools-20260708/mvp-video-pipeline/src/video_creation_pipeline/spoken_delivery.py').is_file(), 'Full MVP owner is not public; owner-specific integration unverified')
    def test_spoken_plan_delivery_routes_without_restarting_case_workflow(self):
        mvp=ROOT.parent/'ai-video-tools-20260708/mvp-video-pipeline/src'
        if str(mvp) not in sys.path: sys.path.insert(0,str(mvp))
        # This is a routing-only fixture. Actual PCM/leveling execution is
        # exercised by the shared MVP segment-leveling regression suite.
        plan=self.ref(dict(schema='video_creation_pipeline.spoken_edit_plan.v2',source_video={},nle_segments=[]))
        for kind,deliverable,editor,route in [
                ('rough_cut_review','review',None,'source_review'),
                ('rough_cut_video','video',None,'ffmpeg'),
                ('finished_video','video',None,'ffmpeg'),
                ('editable_project','editable_project','premiere','premiere'),
                ('editable_project','editable_project','jianying','jianying')]:
            req=dict(schema='video_creation_pipeline.spoken_delivery_request.v1',
                     deliverable=deliverable,selection_basis='synthetic requested delivery')
            if editor: req['editor']=editor
            with self.subTest(kind=kind,editor=editor), patch('video_creation_pipeline.spoken_delivery.validate_spoken_edit_plan'), patch('video_creation_pipeline.segment_leveling.validate_leveling'):
                result=agent.resolve_request(self.request(kind,current=dict(
                    spoken_edit_plan=plan,spoken_delivery_request=self.ref(req))))
            self.assertEqual(result['primary_entry'],'spoken_delivery')
            self.assertEqual(result['spoken_delivery_selection']['route'],route)
            self.assertIsNone(result['workflow_goal'])
            self.assertIn('select-delivery',result['next_action']['argv'])
            self.assertFalse(result['media_export_authorized'])

    @unittest.skipUnless((ROOT.parent/'ai-video-tools-20260708/mvp-video-pipeline/src/video_creation_pipeline/spoken_delivery.py').is_file(), 'Full MVP owner is not public; owner-specific integration unverified')
    def test_spoken_editor_unknown_stays_missing_and_conflicts_fail(self):
        result=agent.resolve_request(self.request('editable_project'))
        self.assertIn('requested_editor',result['missing_inputs'])
        self.assertNotIn('editor',result['delivery_request_template'])
        plan=self.ref(dict(schema='video_creation_pipeline.spoken_edit_plan.v2'))
        delivery=self.ref(dict(schema='video_creation_pipeline.spoken_delivery_request.v1',
            deliverable='editable_project',editor='jianying',selection_basis='synthetic'))
        with self.assertRaises(agent.AgentEntryError):
            agent.resolve_request(self.request('rough_cut_review',current=dict(spoken_edit_plan=plan,spoken_delivery_request=delivery)))
        with self.assertRaises(agent.AgentEntryError):
            agent.resolve_request(self.request('editable_project',editor='premiere',current=dict(spoken_edit_plan=plan,spoken_delivery_request=delivery)))

    def test_absent_full_mvp_owner_blocks_without_export_or_substitution(self):
        if (ROOT.parent/'ai-video-tools-20260708/mvp-video-pipeline/src/video_creation_pipeline/spoken_delivery.py').is_file():
            self.skipTest('This counterexample requires the owner to be absent')
        value=agent.resolve_request(self.request('rough_cut_video'))
        self.assertEqual(value['status'],'needs_context')
        self.assertIn('full_mvp_spoken_delivery_owner',value['missing_inputs'])
        self.assertFalse(value['commands_executed'])
        self.assertFalse(value['media_export_authorized'])

    def test_retained_spoken_plan_does_not_restart_later_delivery_or_review(self):
        plan=self.ref(dict(schema='video_creation_pipeline.spoken_edit_plan.v2'))
        manifest=self.ref(dict(schema='self-media.video-delivery.v1'))
        for kind in ('finished_video','continue'):
            with self.subTest(kind=kind):
                value=agent.resolve_request(self.request(kind,current=dict(
                    spoken_edit_plan=plan,delivery_manifest=manifest)))
                self.assertEqual(value['primary_entry'],'video_delivery')
                self.assertIn('check',value['next_action']['argv'])
                self.assertNotIn('spoken_delivery_selection',value)
        review=self.ref(dict(schema_version='self-media-human-review-request-pack.v1',
                             requests=[dict(review_id='review-1',status='pending')]))
        value=agent.resolve_request(self.request('rough_cut_review',current=dict(
            spoken_edit_plan=plan,review_request=review)))
        self.assertEqual(value['primary_entry'],'video_review')
        self.assertIn(review['path'],value['next_action']['argv'])
        value=agent.resolve_request(self.request('finished_video',change_scope='technical_only',
            current=dict(spoken_edit_plan=plan)))
        self.assertEqual(value['workflow_goal'],'context_efficient_rework')

    def test_direct_artifacts_do_not_enter_case_or_story_workflow(self):
        for kind,entry in {'publication_page':'publication_desk','cover_options':'covers',
                'title_options':'text_packaging','publication_record':'operations','archive_plan':'artifact_lifecycle',
                'workflow_repair':'workflow_maintenance'}.items():
            with self.subTest(kind=kind):
                value=agent.resolve_request(self.request(kind))
                self.assertEqual(value['primary_entry'],entry)
                self.assertIsNone(value['workflow_goal'])
                self.assertFalse(value['commands_executed'])
                self.assertFalse(value['dispatch_authorized'])

    def test_every_deliverable_returns_one_existing_target_without_writing(self):
        schema=json.loads(entry_selection.SCHEMA.read_text(encoding='utf8'))
        before={str(p.relative_to(self.root)):agent.sha256_file(p) for p in self.root.rglob('*') if p.is_file()}
        for kind in schema['properties']['requested_output']['enum']:
            with self.subTest(kind=kind):
                result=agent.resolve_request(self.request(kind))
                action=result['next_action']
                self.assertIsInstance(action,dict)
                self.assertTrue(action['selected_not_executed'])
                self.assertFalse(result['commands_executed'])
                self.assertFalse(result['media_export_authorized'])
                for guide in result['read_next']:
                    self.assertTrue(Path(guide).is_file(),guide)
                if action['kind']=='existing_cli':
                    self.assertTrue(Path(action['argv'][1]).is_file(),action)
                else:
                    self.assertTrue(Path(action['path']).is_file(),action)
        after={str(p.relative_to(self.root)):agent.sha256_file(p) for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(before,after)

    def test_title_fragments_and_legacy_aliases_are_one_invocation_target(self):
        value=agent.resolve_request(self.request('title_options'))['coordinator']
        self.assertEqual(value['id'],'dbs-title-cover-intro')
        self.assertEqual(value['invocation_count'],1)
        self.assertGreaterEqual(len(value['applicability_fragments']),2)
        self.assertIn('dbs-hook',value['legacy_aliases'])
        index=entry_selection.skill_index(agent)['entries']
        self.assertNotIn('dbs-hook',index)
        self.assertNotIn('dbs-xhs-title',index)

    def test_review_purposes_never_select_export_or_full_rework(self):
        req=dict(schema_version='self-media-human-review-request-pack.v1',requests=[dict(review_id='review-1',status='pending')])
        ref=self.ref(req)
        for kind,purpose in entry_selection.REVIEW_PURPOSE.items():
            result=agent.resolve_request(self.request(kind,current=dict(review_request=ref)))
            self.assertEqual(result['primary_entry'],'video_review')
            self.assertEqual(result['review_purpose'],purpose)
            self.assertIn('source-time-range-review.md',result['read_next'][0])
            self.assertNotIn('render',result['next_action']['argv'])
            self.assertFalse(result['media_export_authorized'])

    def test_saved_desk_has_actionable_check_and_old_desk_migrates(self):
        data=publication_desk.new_project('synthetic-desk','Synthetic')
        ref=self.ref(data)
        result=agent.resolve_request(self.request('publication_page',current=dict(publication_data=ref)))
        self.assertTrue(result['migration_required'])
        self.assertTrue(result['page_regeneration_required'])
        self.assertIn(ref['path'],result['next_action']['argv'])
        self.assertIn('render',result['next_action']['argv'])
        data.pop('target_platforms')
        result=agent.resolve_request(self.request('publication_page',current=dict(publication_data=self.ref(data))))
        self.assertTrue(result['migration_required'])
        self.assertIn('upgrade',result['next_action']['argv'])

    def test_continue_restores_real_capsule_sequence_not_a_second_run(self):
        old=agent.load_json(agent.RECIPE_FIXTURES['moments-short-post'])
        capsule=agent.resolve_request(old)
        current=dict(capsule=self.ref(capsule))
        expected=agent.derive_sequence_status(Path(current['capsule']['path']),[])
        result=agent.resolve_request(self.request('continue',current=current))
        self.assertEqual(result['sequence'],expected)
        self.assertEqual(result['sequence']['next_step']['step_id'],capsule['step_index'][0]['step_id'])
        self.assertEqual(result['primary_entry'],'managed_continuation')
        explicit=agent.resolve_request(self.request('publication_page',current=current))
        self.assertEqual(explicit['primary_entry'],'publication_desk')

    def test_continue_ambiguous_state_does_not_guess(self):
        result=agent.resolve_request(self.request('continue'))
        self.assertEqual(result['status'],'needs_context')
        self.assertEqual(len(result['missing_inputs']),1)
        current=dict(publication_data=self.ref(publication_desk.new_project('p','t')),
                     delivery_manifest=self.ref({'schema':'self-media.video-delivery.v1'}))
        self.assertEqual(agent.resolve_request(self.request('continue',current=current))['status'],'needs_context')

    def test_stale_capsule_is_not_silently_rebased_or_restarted(self):
        capsule=agent.resolve_request(agent.load_json(agent.RECIPE_FIXTURES['moments-short-post']))
        capsule['recipe_detail_ref']['sha256']='0'*64
        capsule.pop('payload_sha256')
        capsule['payload_sha256']=agent.sha256_value(capsule)
        with self.assertRaises(agent.AgentEntryError) as caught:
            agent.resolve_request(self.request('continue',current={'capsule':self.ref(capsule)}))
        self.assertEqual(caught.exception.code,'recipe_detail_drift')
        recovery=agent.resume_receipt({'error_code':caught.exception.code})
        self.assertFalse(recovery['automatic_retry'])
        self.assertIn('Preserve the original capsule',recovery['recovery_action'])

    def test_continue_existing_delivery_does_not_render(self):
        ref=self.ref({'schema':'self-media.video-delivery.v1'})
        value=agent.resolve_request(self.request('continue',current=dict(delivery_manifest=ref)))
        self.assertEqual(value['primary_entry'],'video_delivery')
        self.assertIn('check',value['next_action']['argv'])
        self.assertNotIn('render',value['next_action']['argv'])

    def test_vlog_is_independent_and_has_no_analysis_side_effect(self):
        result=agent.resolve_request(self.request('video_plan',current=self.creative()))
        self.assertEqual(result['primary_entry'],'travel_experience')
        self.assertIsNone(result['workflow_goal'])
        self.assertFalse(result['automatic_analysis_started'])
        self.assertEqual(result['next_action']['kind'],'read_existing_guide')

    def test_missing_context_does_not_route_by_keyword(self):
        request=self.request('script');request['selection_basis']='旅行医学案例视频的标题只是历史名称'
        result=agent.resolve_request(request)
        self.assertEqual(result['primary_entry'],'creation_route')
        self.assertEqual(result['status'],'needs_context')

    def test_generic_script_and_case_prerecording_are_distinct(self):
        base=dict(topic_domain='explanation',primary_intent='explain-or-answer',requested_vlog_style='auto',requested_route='auto')
        value=agent.resolve_request(self.request('script',current=self.creative(**base)))
        self.assertEqual(value['primary_entry'],'canonical_format_adapter')
        base['topic_domain']='case'
        value=agent.resolve_request(self.request('script',content_format='short-video-narration',current=self.creative(**base)))
        self.assertEqual(value['workflow_goal'],'case_video_candidate')
        self.assertEqual(value['creation_phase'],'prerecording')
        self.assertNotIn('source_media_ref',value['required_initial_inputs'])

    def test_technical_rework_does_not_request_new_story(self):
        value=agent.resolve_request(self.request('finished_video',change_scope='technical_only'))
        self.assertEqual(value['workflow_goal'],'context_efficient_rework')
        self.assertIsNone(value['creation_route'])

    def test_generic_video_format_is_not_assumed_to_be_short_narration(self):
        current=self.creative(topic_domain='explanation',primary_intent='explain-or-answer')
        value=agent.resolve_request(self.request('script',current=current))
        self.assertIsNone(value['format_adapter'])
        self.assertIn('content_format',value['missing_inputs'])
        for name in ('demo-video','long-video','live'):
            value=agent.resolve_request(self.request('script',current=current,content_format=name))
            self.assertEqual(value['format_adapter'],name+'@0.2')
            self.assertEqual(value['status'],'selected')

    def test_unknown_or_conflicting_format_is_rejected(self):
        current=self.creative(topic_domain='explanation',primary_intent='explain-or-answer')
        for kind,name in [('script','invented-format'),('article','demo-video')]:
            with self.assertRaises(agent.AgentEntryError):
                agent.resolve_request(self.request(kind,current=current,content_format=name))

    def test_current_context_and_decision_must_match(self):
        refs=self.creative()
        context=json.loads(Path(refs['creation_context']['path']).read_text(encoding='utf8'))
        context['revision_id']='changed'
        refs['creation_context']=self.ref(context)
        with self.assertRaisesRegex(agent.AgentEntryError,'changed|reassess'):
            agent.resolve_request(self.request('video_plan',current=refs))

    def test_bad_hash_unknown_field_and_orphan_receipt_fail_closed(self):
        ref=self.ref({'schema':'synthetic'});Path(ref['path']).write_text('{}',encoding='utf8')
        with self.assertRaises(agent.AgentEntryError):agent.resolve_request(self.request('publication_page',current={'publication_data':ref}))
        with self.assertRaises(agent.AgentEntryError):agent.resolve_request(self.request('finished_video',publish_authorized=True))
        with self.assertRaises(agent.AgentEntryError):agent.resolve_request(self.request('continue',current={'receipts':[self.ref({})]}))

    def test_cli_returns_selected_entry_and_nonzero_for_missing_context(self):
        for kind,code,context in [('cover_options',2,{}),('cover_options',0,dict(context_manifest=self.purpose_context())),('continue',2,{})]:
            ref=self.ref(self.request(kind,current=context))
            run=subprocess.run([sys.executable,'-B',str(ROOT/'scripts/self_media_agent.py'),'resolve','--request',ref['path']],
                               capture_output=True,text=True,encoding='utf8',timeout=20)
            self.assertEqual(run.returncode,code,run.stdout+run.stderr)
            self.assertEqual(json.loads(run.stdout)['schema_version'],'self-media-entry-selection.v1')

    @unittest.skipUnless((ROOT.parent/'scripts/validate-content-visualization-routing.py').is_file(), 'Private thread-routing history is excluded from the public edition')
    def test_visualization_routing_does_not_authorize_thread_dispatch(self):
        run=subprocess.run([sys.executable,'-B',str(ROOT.parent/'scripts/validate-content-visualization-routing.py'),'--query','信息图'],
                           capture_output=True,text=True,encoding='utf8',timeout=20)
        self.assertEqual(run.returncode,0,run.stdout+run.stderr)
        value=json.loads(run.stdout)
        self.assertEqual(value['decision'],'handle_in_current_task_using_registered_tool')
        self.assertFalse(value['dispatch_authorized'])


if __name__=='__main__':unittest.main()
