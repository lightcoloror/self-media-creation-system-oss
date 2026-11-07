"""Existing QRP export and content consumer, with explicitly bound delivery selection."""
import importlib.util
import contextlib
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
WORKSPACE=(ROOT.parent/'docs').resolve().parent
STUDIO=WORKSPACE/'content-studio-poc'
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'tests'),str(STUDIO/'scripts'),str(WORKSPACE/'scripts')]
import self_media_agent as agent
import saved_research_candidate as candidate
import selected_delivery
import test_editorial_connections as fixtures
import registered_self_media

spec=importlib.util.spec_from_file_location('saved_candidate_test_fixtures',STUDIO/'tests/test_saved_research_candidate.py')
materials=importlib.util.module_from_spec(spec);spec.loader.exec_module(materials)


class ResearchDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.fx=fixtures.ConnectionsTests('runTest');self.fx.setUp()
        self.addCleanup(self.fx.doCleanups)
        self.root=self.fx.root

    def request(self,kind='article',platform='wechat-article'):
        req=self.fx.req(kind,platform)
        return Path(self.fx.ref(req)['path'])

    def test_unselected_research_is_only_intermediate_not_platform_choice(self):
        source=materials.material(self.root,'Search')
        with patch('socket.socket.connect',side_effect=AssertionError('offline')):
            first=candidate.project_candidate(source,self.root,self.root/'candidate',materials.QRP)
        exported=agent.load_json(Path(first['research_output']))
        self.assertEqual(['guarded_answer'],exported['requested_outputs'])
        self.assertEqual('intermediate_research_draft',first['artifact_role'])
        self.assertIsNone(first['platform_selected'])
        before=candidate.inventory(self.root/'candidate')
        second=candidate.project_candidate(source,self.root,self.root/'candidate',materials.QRP)
        self.assertTrue(second['reused']);self.assertEqual(before,candidate.inventory(self.root/'candidate'))

    def test_non_article_selection_never_runs_article_consumer(self):
        source=materials.material(self.root,'A synthetic personal choice')
        request=self.request('graphic_note','zhihu')
        with patch.object(candidate,'consume',side_effect=AssertionError('must not produce article')):
            first=candidate.project_candidate(source,self.root,self.root/'candidate',materials.QRP,work_request=request)
            second=candidate.project_candidate(source,self.root,self.root/'candidate',materials.QRP,work_request=request)
        self.assertEqual('needs_format_adapter',first['status'])
        self.assertEqual('zhihu',first['delivery_selection']['platform'])
        self.assertEqual(['graphic_note'],agent.load_json(Path(first['research_output']))['requested_outputs'])
        self.assertTrue(second['reused'])
        self.assertFalse((self.root/'candidate/candidates').exists())

    def test_selected_article_keeps_platform_and_blocks_route_drift(self):
        source=materials.material(self.root,'A synthetic personal choice')
        request=self.request('article','toutiao')
        first=candidate.project_candidate(source,self.root,self.root/'candidate',materials.QRP,work_request=request)
        self.assertEqual('toutiao',first['platform_selected'])
        self.assertEqual('selected_article_candidate',first['artifact_role'])
        value=agent.load_json(request);value['platform']='zhihu'
        changed=Path(self.fx.ref(value)['path'])
        with self.assertRaisesRegex(ValueError,'input_binding_drift'):
            candidate.project_candidate(source,self.root,self.root/'candidate',materials.QRP,work_request=changed)

    def test_mismatched_topic_rejected_before_any_research_write(self):
        source=materials.material(self.root,'Unrelated question')
        with self.assertRaisesRegex(ValueError,'topic_selection_mismatch'):
            candidate.project_candidate(source,self.root,self.root/'candidate',materials.QRP,work_request=self.request())
        self.assertFalse((self.root/'candidate').exists())

    def test_selected_capture_cli_uses_existing_autoflow_without_article_fallback(self):
        import capture_research_candidate as capture
        spec=importlib.util.spec_from_file_location('capture_fixtures',STUDIO/'tests/test_capture_research_candidate.py')
        fixtures_module=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixtures_module)
        topic,index,_,_=fixtures_module.setup(self.root/'inputs','Search')
        req=self.fx.req('graphic_note','zhihu')
        self.fx.manifest(req,lambda m:m['editorial_context']['topic_selection'].update(topic='Search'))
        request=Path(self.fx.ref(req)['path'])
        args=['--topic',str(topic),'--captures',str(index),'--output-dir',str(self.root/'capture'),
              '--work-request',str(request),'--auto-observations']
        with patch('socket.socket.connect',side_effect=AssertionError('offline')), \
             patch.object(candidate,'consume',side_effect=AssertionError('no article consumer')), \
             contextlib.redirect_stdout(io.StringIO()) as stdout:
            self.assertEqual(2,capture.main(args))
        result=json.loads(stdout.getvalue())
        self.assertEqual('needs_format_adapter',result['status'])
        self.assertEqual('zhihu',result['delivery_selection']['platform'])
        self.assertTrue(Path(result['review_bundle']).is_file())
        self.assertFalse(result['research_complete'])
        self.assertFalse((self.root/'capture/candidate/candidates').exists())

    def test_route_changed_during_consumer_does_not_complete_checkpoint(self):
        source=materials.material(self.root,'A synthetic personal choice')
        request=self.request()
        consume=candidate.consume
        def changed(argv):
            result=consume(argv)
            value=agent.load_json(request);value['platform']='zhihu'
            request.write_text(json.dumps(value),encoding='utf8')
            return result
        with patch.object(candidate,'consume',side_effect=changed):
            with self.assertRaisesRegex(ValueError,'delivery_selection_changed_during_projection'):
                candidate.project_candidate(source,self.root,self.root/'candidate',materials.QRP,work_request=request)
        self.assertFalse(agent.load_json(self.root/'candidate/candidate-state.json').get('complete',False))

    def test_registry_root_mismatch_does_not_fall_back_to_old_checkout(self):
        registry=agent.load_json(registered_self_media.REGISTRY)
        registry['tools']['content-creation-system']['self_media_path']=str(WORKSPACE/'unregistered-old-checkout')
        path=Path(self.fx.ref(registry)['path'])
        with self.assertRaisesRegex(ValueError,'registered_self_media_root_mismatch'):
            registered_self_media.scripts_root(path)

    def test_same_registered_root_for_publishing_and_mode_requirements(self):
        self.assertEqual(ROOT/'scripts',registered_self_media.scripts_root())
        contracts=agent.load_canonical_routing()
        row=next(r for r in contracts['components']['skill_registry']['tool_refs']
                 if r['id']=='content-studio-wechat-article-format-adapter')
        self.assertIn('pending-author-state-preserved',row['mode_requirements']['public-review'])
        self.assertNotIn('synthetic-only-fixture-for-automation',row['requires'])


    @unittest.skipUnless((WORKSPACE/'local-publish-assistant/publication_desk.py').is_file(), 'Private publication wrapper is not distributed; optional integration unverified')
    def test_optional_publication_wrapper_uses_registered_root(self):
        spec=importlib.util.spec_from_file_location('publish_desk_test_wrapper',WORKSPACE/'local-publish-assistant/publication_desk.py')
        wrapper=importlib.util.module_from_spec(spec);spec.loader.exec_module(wrapper)
        self.assertEqual(ROOT,wrapper.ROOT)


if __name__=='__main__':unittest.main()
