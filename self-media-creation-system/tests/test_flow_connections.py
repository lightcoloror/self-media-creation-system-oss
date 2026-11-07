"""Synthetic cross-consumer regression; no browser, accounts or real author decision."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'tests')]
import self_media_agent as agent
import article_delivery as delivery
import editorial_integrity as gate
import test_editorial_connections as fixtures
import test_editorial_integrity as integrity


class FlowConnectionsTests(unittest.TestCase):
    def setUp(self):
        self.fx=fixtures.ConnectionsTests('runTest')
        self.fx.setUp()
        self.addCleanup(self.fx.doCleanups)
        self.root=self.fx.root

    def ref(self,value):
        return self.fx.ref(value)

    def article(self):
        original=integrity.IntegrityTests.rev
        def titled(fx,text,before=''):
            return original(fx,'# Synthetic title\n\n'+text,before)
        with patch.object(integrity.IntegrityTests,'rev',titled):
            req,fx=self.fx.setup_article()
        gate.record_review(fx.revision,fx.data())
        return req,fx

    def item(self,req):
        path=self.root/'item.json'
        delivery.prepare(Path(self.ref(req)['path']),path)
        item=agent.load_json(path)
        # Explicitly synthetic public/privacy decision; never a real author's approval.
        item['tags']=['public-material-review']
        item['gates']['privacy']={'status':'pass','reviewed_by':'synthetic-fixture'}
        path.write_text(json.dumps(item),encoding='utf8')
        req['current']['article_item']=dict(path=str(path),sha256=agent.sha256_file(path))
        return path

    def test_other_task_never_reaches_managed_capsule(self):
        req=self.fx.req('short_post','wechat-moments')
        old=agent.load_json(agent.RECIPE_FIXTURES['moments-short-post'])
        old['request_id']='wrong-synthetic-task'
        req['current']['managed_request']=self.ref(old)
        with self.assertRaisesRegex(ValueError,'another task'):
            agent.resolve_request(req)

    def test_saved_request_needs_binding_and_changed_topic_invalidates_it(self):
        req=self.fx.req('short_post','wechat-moments')
        old=agent.load_json(agent.RECIPE_FIXTURES['moments-short-post']);old['request_id']=req['request_id']
        req['current']['managed_request']=self.ref(old)
        first=agent.resolve_request(req)
        self.assertEqual('needs_context',first['status'])
        req['current']['managed_request']=self.ref(first['request_template'])
        self.assertEqual('existing_cli',agent.resolve_request(req)['next_action']['kind'])
        self.fx.manifest(req,lambda m:m['editorial_context']['topic_selection'].update(adoption_basis='Changed synthetic purpose'))
        self.assertEqual('needs_context',agent.resolve_request(req)['status'])

    def test_prepare_uses_current_draft_without_promoting_any_gates(self):
        req,fx=self.article()
        before=Path(fx.revision).read_bytes()
        path=self.root/'prepared.json'
        result=delivery.prepare(Path(self.ref(req)['path']),path)
        item=agent.load_json(path)
        self.assertEqual('content_item_prepared',result['status'])
        self.assertEqual({'needs-review'},{g['status'] for g in item['gates'].values()})
        self.assertEqual([],item['tags'])
        self.assertEqual('required',item['qa']['human_review']['status'])
        self.assertEqual(before,Path(fx.revision).read_bytes())
        req['current']['article_item']=dict(path=str(path),sha256=agent.sha256_file(path))
        self.assertIn('public_material_declaration_required',agent.resolve_request(req)['missing_inputs'])

    def test_selected_platform_never_becomes_wechat_by_fallback(self):
        req,fx=self.article()
        req['platform']='zhihu'
        binding=agent.resolve_request(req)['entry_binding']
        fx.pre['entry_binding']=binding;gate.record_preflight(fx.context,fx.pre)
        with self.assertRaisesRegex(ValueError,'renderer_not_available'):
            delivery.prepare(Path(self.ref(req)['path']),self.root/'not-created.json')
        self.assertFalse((self.root/'not-created.json').exists())

    def test_existing_source_item_preserves_evidence_and_rejects_unbound_approval(self):
        req,fx=self.article()
        source=self.item(req)
        original=agent.load_json(source)
        req['current'].pop('article_item')
        req['current']['article_source_item']=dict(path=str(source),sha256=agent.sha256_file(source))
        target=self.root/'reused-item.json'
        delivery.prepare(Path(self.ref(req)['path']),target)
        prepared=agent.load_json(target)
        for key in ('provenance','gates','qa','tags','publication'):
            self.assertEqual(original[key],prepared[key])
        original['qa']['human_review']['status']='approved'
        source.write_text(json.dumps(original),encoding='utf8')
        req['current']['article_source_item']['sha256']=agent.sha256_file(source)
        rejected=self.root/'rejected.json'
        with self.assertRaisesRegex(ValueError,'article_source_author_approval_not_bound'):
            delivery.prepare(Path(self.ref(req)['path']),rejected)
        self.assertFalse(rejected.exists())

    def test_item_from_old_binding_cannot_be_used(self):
        req,fx=self.article();path=self.item(req)
        item=agent.load_json(path);item['channels']['wechat_article']['platform_metadata']['request_id']='other-task'
        path.write_text(json.dumps(item),encoding='utf8')
        req['current']['article_item']['sha256']=agent.sha256_file(path)
        with self.assertRaisesRegex(ValueError,'article_item_entry_binding_drift'):
            agent.resolve_request(req)

    def test_actual_formatter_then_same_output_review_and_drift(self):
        req,fx=self.article();self.item(req)
        selection=agent.resolve_request(req)
        self.assertEqual('article_layout',selection['primary_entry'])
        argv=selection['next_action']['argv'][2:]
        argv[argv.index('--output-dir')+1]=str(self.root/'render')
        argv[argv.index('--checked-at')+1]='2026-10-29T00:00:00Z'
        module=delivery.adapter()
        with patch('socket.socket.connect',side_effect=AssertionError('offline')):
            module.render(module.build_parser().parse_args(argv))
        manifest=self.root/'render/manifest.json'
        req['current']['article_render_manifest']=dict(path=str(manifest),sha256=agent.sha256_file(manifest))
        result=agent.resolve_request(req)
        self.assertEqual('article_visual_review',result['primary_entry'])
        review=result['visual_review_template']
        from PIL import Image
        evidence=self.root/'synthetic-observation.png'
        Image.new('RGB',(20,20),'white').save(evidence)
        for row in review['views']:
            row.update(status='pass',observation='Synthetic contract observation, not real visual acceptance.',
                       evidence_ref=dict(path=str(evidence),sha256=agent.sha256_file(evidence)))
        req['current']['article_visual_review']=self.ref(review)
        complete=agent.resolve_request(req)
        self.assertEqual('article_author_review_package',complete['primary_entry'])
        self.assertEqual('awaiting_author',complete['status'])
        self.assertFalse(complete['publication_authority'])
        self.assertFalse(complete['article_review_package']['editorial']['author_confirmation_recorded'])
        self.assertNotIn('platform_layout',complete['article_review_package']['remaining_steps'])
        broken=json.loads(json.dumps(review));broken['views']=broken['views'][:2]
        req['current']['article_visual_review']=self.ref(broken)
        with self.assertRaisesRegex(ValueError,'views_missing'):agent.resolve_request(req)
        req['current']['article_visual_review']=self.ref(review)
        output=Path(review['views'][0]['artifact_ref']['path']);output.write_text('Changed after review')
        with self.assertRaisesRegex(ValueError,'output_drift'):agent.resolve_request(req)

    def test_missing_output_cannot_be_counted_as_rendered(self):
        req,fx=self.article();self.item(req)
        req['current']['article_render_manifest']=self.ref(dict(mode='public-review-candidate-only',status='review-required',
            publication_boundary='manual-only',publication_authorized=False,remote_actions_performed=False,
            content_id='synthetic-content',input_markdown_sha256=agent.resolve_request(req)['article_review_package']['draft']['sha256']))
        with self.assertRaisesRegex(agent.AgentEntryError,'render-receipt-body'):agent.resolve_request(req)


if __name__=='__main__':unittest.main()
