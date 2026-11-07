"""Actual existing selectors and SQLite consumers; synthetic, offline, no models."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'scripts'), str(ROOT/'tests')]
import self_media_agent as agent
import author_writing_context as author
import editorial_integrity as gate
import test_entry_selection as entry_fixtures
import test_editorial_integrity as integrity_fixtures


class ConnectionsTests(unittest.TestCase):
    ref = entry_fixtures.EntrySelectionTests.ref
    request = entry_fixtures.EntrySelectionTests.request
    creative = entry_fixtures.EntrySelectionTests.creative
    purpose_context = entry_fixtures.EntrySelectionTests.purpose_context

    def setUp(self):
        root = Path(os.environ.get('TEST_TMP_ROOT', ROOT/'.test-runtime'))
        root.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=root)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.serial = 0

    def req(self, kind='article', platform=None):
        current = self.creative(topic_domain='explanation', primary_intent='explain-or-answer')
        req = self.request(kind, current=current)
        if platform is not None: req['platform'] = platform
        return req

    def manifest(self, req, change):
        ref = req['current']['context_manifest']
        value = json.loads(Path(ref['path']).read_text(encoding='utf8'))
        change(value)
        req['current']['context_manifest'] = self.ref(value)
        return req

    def test_missing_topic_or_platform_stops_without_guessing(self):
        req = self.req()
        self.manifest(req, lambda m:m['editorial_context'].pop('topic_selection'))
        req.pop('platform')
        result = agent.resolve_request(req)
        self.assertIn('topic_selection_in_context_manifest', result['missing_inputs'])
        self.assertIn('platform', result['missing_inputs'])
        self.assertIsNone(result['workflow_goal'])
        self.assertFalse(result['commands_executed'])

    def test_candidate_and_deferred_are_not_adopted(self):
        for status in ('candidate','deferred'):
            req = self.req()
            self.manifest(req, lambda m:m['editorial_context']['topic_selection'].update(adoption=status))
            result = agent.resolve_request(req)
            self.assertEqual('needs_context', result['status'])
            self.assertIn('topic_adoption_basis_for_selected_task',result['missing_inputs'])

    def test_exact_topic_anchor_and_source_hash_are_enforced(self):
        req = self.req()
        self.manifest(req, lambda m:m['editorial_context']['topic_selection']['adoption_source'].update(quote='not in source'))
        with self.assertRaises(ValueError): agent.resolve_request(req)
        req = self.req()
        self.manifest(req, lambda m:m['artifacts'][0].update(expected_sha256='0'*64))
        with self.assertRaises(ValueError): agent.resolve_request(req)

    def test_three_origins_are_preserved_not_relabelled_user(self):
        for origin in ('user_assigned','agent_proposed','tool_trial','existing_topic'):
            req = self.req()
            self.manifest(req, lambda m:m['editorial_context']['topic_selection'].update(origin=origin))
            self.assertEqual(origin, agent.resolve_request(req)['editorial_context']['topic_selection']['origin'])

    def test_article_platforms_are_independent_and_no_wechat_fallback(self):
        for platform in ('wechat-article','zhihu','toutiao'):
            value = agent.resolve_request(self.req(platform=platform))
            self.assertEqual(platform+'@0.2',value['platform_overlay'])
            self.assertEqual('longform-article@0.2',value['format_adapter'])
            self.assertEqual('article_editorial',value['primary_entry'])

    def test_graphic_and_short_post_only_use_matching_managed_recipe(self):
        for kind,platform,expected in [('graphic_note','xiaohongshu','xhs_evidence_graphic'),
                ('graphic_note','zhihu',None),('short_post','wechat-moments','moments_short_post'),
                ('short_post','weibo',None)]:
            value=agent.resolve_request(self.req(kind,platform))
            self.assertEqual(expected,value['workflow_goal'])
            self.assertEqual(platform,value['platform'])

    def test_unknown_platform_and_all_fixed_format_conflicts_rejected(self):
        for kind,platform,fmt in [('article','invented','longform-article'),
                ('article','xiaohongshu','longform-article'),('graphic_note','zhihu','longform-article'),
                ('short_post','weibo','graphic-note')]:
            req=self.req(kind,platform); req['content_format']=fmt
            with self.assertRaises(agent.AgentEntryError): agent.resolve_request(req)

    def setup_article(self):
        fixture=integrity_fixtures.IntegrityTests('test_A09_retained_reason_and_exact_author_confirmation')
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        req=self.req()
        req['request_id']='synthetic-request'
        for key in ('creation_context','creation_decision'):
            value=json.loads(Path(req['current'][key]['path']).read_text(encoding='utf8'))
            if key=='creation_context':
                value['task_id']=req['request_id']; context=value
            else:
                import creation_route
                value=creation_route.resolve(context)
            req['current'][key]=self.ref(value)
        def update(m):
            m['task_id']=req['request_id']
            m['editorial_context']['content_id']='synthetic-content'
            # All manifest files are co-located; the actual author draft stays in its existing store root.
            draft=author.checked_ref(author.load(fixture.revision)['draft_ref'])
            # Use a manifest inside the fixture root to obey the existing path bound.
            m['artifacts'].append(dict(artifact_id='article-draft',role='source_manifest',path=draft.name,
                expected_sha256=agent.sha256_file(draft),load_mode='reference'))
            m['editorial_context']['current_body_artifact_id']='article-draft'
        m=json.loads(Path(req['current']['context_manifest']['path']).read_text(encoding='utf8'))
        # Copy only synthetic purpose evidence beside the existing synthetic draft.
        for row in m['artifacts']:
            original=Path(req['current']['context_manifest']['path']).parent/row['path']
            target=fixture.root/('purpose-'+original.name)
            target.write_bytes(original.read_bytes()); row['path']=target.name
        update(m)
        manifest=fixture.write(m)
        req['current']['context_manifest']=dict(path=str(manifest),sha256=agent.sha256_file(manifest))
        req['current']['author_context']=dict(path=str(fixture.context),sha256=agent.sha256_file(fixture.context))
        req['current']['author_revision']=dict(path=str(fixture.revision),sha256=agent.sha256_file(fixture.revision))
        binding=agent.resolve_request(req)['entry_binding']
        fixture.pre['entry_binding']=binding
        gate.record_preflight(fixture.context,fixture.pre)
        return req,fixture

    def test_existing_draft_advances_to_real_editorial_consumer_not_rewrite(self):
        req,fx=self.setup_article()
        value=agent.resolve_request(req)
        self.assertIn('record',value['next_action']['argv'])
        self.assertIn(str(fx.revision),value['next_action']['argv'])
        self.assertNotIn('prepare',value['next_action']['argv'])

    def test_complete_checks_produce_package_but_never_author_confirmation(self):
        req,fx=self.setup_article()
        gate.record_review(fx.revision,fx.data())
        before=author.file_sha(fx.revision)
        value=agent.resolve_request(req)
        self.assertEqual('awaiting_author',value['status'])
        self.assertEqual('human_review',value['next_action']['kind'])
        self.assertFalse(value['article_review_package']['editorial']['author_confirmation_recorded'])
        self.assertFalse(value['publication_authority'])
        self.assertEqual(before,author.file_sha(fx.revision))

    def test_missing_check_or_required_issue_cannot_produce_ready_package(self):
        for mode in ('missing','issue'):
            req,fx=self.setup_article(); data=fx.data()
            if mode=='missing': data['checks']=data['checks'][:-1]
            else: fx.add_issue(data)
            gate.record_review(fx.revision,data)
            value=agent.resolve_request(req)
            self.assertEqual('needs_context',value['status'])
            self.assertNotIn('article_review_package',value)

    def test_platform_or_adoption_change_invalidates_preflight_binding(self):
        req,fx=self.setup_article()
        req['platform']='zhihu'
        value=agent.resolve_request(req)
        self.assertIn('current_preflight_with_entry_binding',value['missing_inputs'])
        self.assertIn('preflight',value['next_action']['argv'])

    def test_wrong_author_content_or_revision_cannot_be_used(self):
        req,fx=self.setup_article()
        self.manifest(req,lambda m:m['editorial_context'].update(content_id='wrong'))
        with self.assertRaises(agent.AgentEntryError): agent.resolve_request(req)

    def test_changed_topic_basis_invalidates_existing_preparation(self):
        req,fx=self.setup_article()
        path=Path(req['current']['context_manifest']['path'])
        value=json.loads(path.read_text(encoding='utf8'))
        value['editorial_context']['topic_selection']['adoption_basis']='A changed synthetic adoption reason.'
        updated=fx.write(value)
        req['current']['context_manifest']=dict(path=str(updated),sha256=agent.sha256_file(updated))
        self.assertIn('current_preflight_with_entry_binding',agent.resolve_request(req)['missing_inputs'])

    def test_supplied_author_confirmation_is_consumed_not_final_media(self):
        req,fx=self.setup_article(); gate.record_review(fx.revision,fx.data())
        fx.confirm()
        req['current']['author_revision']=dict(path=str(fx.revision),sha256=agent.sha256_file(fx.revision))
        value=agent.resolve_request(req)
        self.assertEqual('selected',value['status'])
        self.assertTrue(value['article_editorial_status']['author_confirmation_recorded'])
        self.assertFalse(value['article_review_package']['final_media_verified'])
        self.assertFalse(value['publication_authority'])

    def test_unrelated_framework_receipt_is_not_silently_adopted(self):
        req=self.req()
        req['current']['topic_decision']=self.ref(dict(schema_version='topic-angle-decision.v2'))
        with self.assertRaises(agent.AgentEntryError) as caught: agent.resolve_request(req)
        self.assertEqual('topic_decision_binding_mismatch',caught.exception.code)

    def test_bound_pending_framework_is_checked_by_existing_consumer(self):
        import topic_angle_decision
        req=self.req()
        value=topic_angle_decision.load_json(ROOT/'fixtures/topic-angle-decision-v2/synthetic.input.json')
        receipt=topic_angle_decision.create_receipt_from_value(value)
        decision=self.ref(receipt)
        req['current']['topic_decision']=decision
        def update(m):
            m['artifacts'].append(dict(artifact_id='framework-current',role='source_manifest',
                path=Path(decision['path']).name,expected_sha256=decision['sha256'],load_mode='reference'))
            m['editorial_context']['topic_selection']['decision_artifact_id']='framework-current'
        self.manifest(req,update)
        result=agent.resolve_request(req)
        self.assertFalse(result['framework_decision']['may_continue'])
        self.assertIn('current_framework_decision_permits_drafting',result['missing_inputs'])
        self.assertEqual('pending',json.loads(Path(decision['path']).read_text(encoding='utf8'))['human_review']['status'])

    def test_declared_framework_artifact_cannot_be_omitted(self):
        req=self.req()
        decision=self.ref(dict(schema_version='topic-angle-decision.v2'))
        def update(m):
            m['artifacts'].append(dict(artifact_id='framework-current',role='source_manifest',
                path=Path(decision['path']).name,expected_sha256=decision['sha256'],load_mode='reference'))
            m['editorial_context']['topic_selection']['decision_artifact_id']='framework-current'
        self.manifest(req,update)
        self.assertIn('topic_decision',agent.resolve_request(req)['missing_inputs'])

    def test_stale_revision_does_not_resume_a_previously_complete_copy(self):
        req,fx=self.setup_article(); gate.record_review(fx.revision,fx.data())
        fx.rev('A new synthetic draft.',fx.text)
        with self.assertRaises(agent.AgentEntryError) as caught: agent.resolve_request(req)
        self.assertIn(caught.exception.code, {'article_revision_stale','editorial_revision_stale'})

    @unittest.skipUnless((ROOT.parent/'invoke_main.py').is_file(), 'Requires the registered runtime launcher')
    def test_registered_launcher_consumes_existing_review_and_preserves_store(self):
        req,fx=self.setup_article(); gate.record_review(fx.revision,fx.data())
        path=Path(self.ref(req)['path']); output=self.root/'selection.json'
        before=agent.sha256_file(fx.db)
        run=subprocess.run([sys.executable,'-B',str(ROOT.parent/'invoke_main.py'),'self',
            'scripts/self_media_agent.py','resolve','--request',str(path),'--output',str(output)],
            capture_output=True,text=True,encoding='utf8',timeout=30)
        self.assertEqual(2,run.returncode,run.stdout+run.stderr)
        self.assertEqual('awaiting_author',json.loads(output.read_text(encoding='utf8'))['status'])
        self.assertEqual(before,agent.sha256_file(fx.db))


if __name__=='__main__': unittest.main()
