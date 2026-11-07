"""Regression shapes from three retrospectives; all content is synthetic.

Exercise existing consumers rather than creating a parallel workflow engine.
"""
import copy
import json
import sys
import unittest
import shutil
import uuid
import subprocess
import zipfile
import stat
import os
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import publication_desk as desk
import self_media_agent as agent
import purpose_continuity as purpose
from execution_context_fixture import make_context


class ContinuationClosureTests(unittest.TestCase):
    def setUp(self):
        base = (ROOT / '.test-runtime').resolve()
        base.mkdir(exist_ok=True)
        self.root = base / ('closure-' + uuid.uuid4().hex)
        self.root.mkdir()
        def cleanup():
            if self.root.is_relative_to(base) and self.root.name.startswith('closure-'):
                shutil.rmtree(self.root)
        self.addCleanup(cleanup)
        self.serial = 0

    def ref(self, value):
        self.serial += 1
        path = self.root / f'metadata-{self.serial}.json'
        path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf8')
        return dict(path=str(path), sha256=agent.sha256_file(path))

    def request(self, kind, **current):
        return dict(schema_version='self-media-work-request.v1', request_id='synthetic-closure-01',
                    requested_output=kind, selection_basis='Synthetic persisted request, not a real author approval',
                    current=current)

    def test_continue_uses_current_consumer_and_preserves_bound_author_constraints(self):
        for identity in ('synthetic-rwe', 'synthetic-parents', 'synthetic-dad-love'):
            with self.subTest(identity=identity):
                data = desk.new_project(identity, 'Synthetic saved publication')
                data['editorial_context'] = dict(forbidden_public_phrases=['Synthetic spoiler'],
                    story='Synthetic approved story', do_not_infer=['Never infer publication'])
                data_ref = self.ref(data)
                saved_ref = self.ref(self.request('publication_page', publication_data=data_ref))
                value = agent.resolve_request(self.request('continue', saved_work_request=saved_ref))
                self.assertEqual(value['primary_entry'], 'publication_desk')
                self.assertEqual(value['recovered_output'], 'publication_page')
                self.assertFalse(value['continuation_source']['previous_commands_replayed'])
                self.assertFalse(value['commands_executed'])
                self.assertIn('render', value['next_action']['argv'])

    def test_continue_cannot_replace_saved_current_data_silently(self):
        old = self.ref(desk.new_project('synthetic-saved', 'Saved'))
        newer = self.ref(desk.new_project('synthetic-conflict', 'Other'))
        saved = self.ref(self.request('publication_page', publication_data=old))
        with self.assertRaises(agent.AgentEntryError) as raised:
            agent.resolve_request(self.request('continue', saved_work_request=saved, publication_data=newer))
        self.assertEqual(raised.exception.code, 'continuation_context_conflict')

    def test_actual_default_render_checkpoint_reuses_current_page_and_detects_consumer_drift(self):
        source=self.ref(desk.new_project('synthetic-page-build','Synthetic build'))
        page=self.root/'current.html'
        run=subprocess.run([sys.executable,str(ROOT/'scripts/self_media_agent.py'),'publication-desk','render',
            '--input',source['path'],'--output',str(page)],capture_output=True,text=True,encoding='utf8',timeout=30)
        self.assertEqual(run.returncode,0,run.stdout+run.stderr)
        output=json.loads(run.stdout)
        checkpoint=self.ref(json.loads(Path(output['saved_work_request']).read_text(encoding='utf8')))
        request=self.request('continue',saved_work_request=checkpoint)
        current=agent.resolve_request(request)
        self.assertFalse(current['migration_required'])
        self.assertIn('check',current['next_action']['argv'])
        self.assertIn('--page-build',current['next_action']['argv'])
        with patch.object(desk,'generation_identity',return_value=dict(policy_sha256='changed')):
            stale=agent.resolve_request(request)
        self.assertTrue(stale['page_regeneration_required'])
        self.assertIn('render',stale['next_action']['argv'])
        page.write_text(page.read_text(encoding='utf8')+'<p>changed</p>',encoding='utf8')
        self.assertTrue(agent.resolve_request(request)['page_regeneration_required'])

    def test_covers_default_plan_consumes_sourced_rules_and_keeps_the_binding(self):
        import cover_workbench as covers
        context=make_context(self.root,[dict(id='no-claim',consumer='covers',schema={
            'properties':{'brief':{'properties':{'title':{'not':{'pattern':'SPOILER'}}}}}})])
        brief=covers.init('synthetic-cover','SPOILER')
        brief.update(promise='Synthetic promise',facts=['Synthetic fact'],routes=['typography'])
        # Use an existing ready route id; the rule is checked by plan, not a new gate engine.
        brief['routes']=[covers.catalog()['routes'][0]['id']]
        with self.assertRaises(purpose.PurposeError):covers.plan(brief,context)
        brief['title']='Synthetic title'
        planned=covers.plan(brief,context)
        self.assertEqual(planned['context_manifest_ref'],context)
        self.assertEqual(planned['requirement_report']['checks'][0]['status'],'passed_structural')
        routed=agent.resolve_request(self.request('cover_options',cover_brief=self.ref(brief),context_manifest=context))
        self.assertEqual(routed['primary_entry'],'covers')
        self.assertIn('--context-manifest',routed['next_action']['argv'])

    def test_stale_checkpoint_or_cyclic_continuation_is_rejected(self):
        saved = self.ref(self.request('continue'))
        with self.assertRaises(agent.AgentEntryError) as raised:
            agent.resolve_request(self.request('continue', saved_work_request=saved))
        self.assertEqual(raised.exception.code, 'continuation_concrete_request_required')
        Path(saved['path']).write_text('{}', encoding='utf8')
        with self.assertRaises(agent.AgentEntryError) as raised:
            agent.resolve_request(self.request('continue', saved_work_request=saved))
        self.assertEqual(raised.exception.code, 'source_hash_drift')

    def test_formal_resolve_passes_same_context_to_real_publication_consumer(self):
        data_ref=self.ref(desk.new_project('synthetic-bridge','Synthetic bridge'))
        context=make_context(self.root)
        request=self.ref(self.request('publication_page',publication_data=data_ref,context_manifest=context))
        run=subprocess.run([sys.executable,str(ROOT/'scripts/self_media_agent.py'),'resolve','--request',request['path']],
            capture_output=True,text=True,encoding='utf8',timeout=30)
        self.assertEqual(run.returncode,0,run.stdout+run.stderr)
        value=json.loads(run.stdout)
        self.assertEqual(value['consumer_context_ref'],context)
        args=value['next_action']['argv']
        self.assertEqual(args[args.index('--context-manifest')+1],context['path'])

    def test_real_renderer_refuses_sourced_copy_requirement_violation(self):
        context=make_context(self.root,[dict(id='public-copy',consumer='publication_desk',schema={
            'properties':{'items':{'items':{'properties':{'platforms':{'additionalProperties':{
                'properties':{'fields':{'properties':{'body':{'not':{'pattern':'SPOILER'}}}}}}}}}}}})])
        data=desk.new_project('synthetic-no-spoiler','Synthetic no spoiler')
        data['items'][0]['platforms']['douyin']['fields']['body']='SPOILER'
        source=self.ref(data)
        page=self.root/'must-not-exist.html'
        run=subprocess.run([sys.executable,str(ROOT/'scripts/publication_desk.py'),'render',
            '--input',source['path'],'--output',str(page),'--context-manifest',context['path']],
            capture_output=True,text=True,encoding='utf8',timeout=30)
        self.assertEqual(run.returncode,2,run.stdout+run.stderr)
        self.assertIn('purpose_consumer_requirement_failed',run.stdout)
        self.assertFalse(page.exists())

    def test_explicit_sourced_exception_does_not_force_an_unwanted_feature(self):
        context=make_context(self.root,[dict(id='no-navigation',consumer='video_delivery',
            decision='not_applicable',schema={'required':['impossible-feature']})])
        report=purpose.check_consumer(context,'video_delivery',{})
        self.assertEqual(report['checks'][0]['status'],'not_applicable')
        self.assertFalse(report['human_approval'])

    def test_followup_context_cannot_lose_or_weaken_a_sourced_requirement(self):
        before=make_context(self.root,[dict(id='keep-layer',consumer='video_review',schema={'required':['requests']})])
        first=purpose.validate_context(before['path'])
        after=copy.deepcopy(first);after['consumer_assertions']=[]
        with self.assertRaises(purpose.PurposeError) as raised:purpose.check_transition(first,after)
        self.assertEqual(raised.exception.code,'purpose_consumer_requirement_lost')
        after=copy.deepcopy(first);after['consumer_assertions'][0]['schema']={}
        with self.assertRaises(purpose.PurposeError) as raised:purpose.check_transition(first,after)
        self.assertEqual(raised.exception.code,'purpose_consumer_requirement_changed_without_source')

    def test_context_metadata_does_not_erase_unchanged_media_human_evidence(self):
        import video_delivery
        original=video_delivery.init('synthetic-media-bound')
        original['edited_media']=dict(path='synthetic.mp4',sha256='a'*64)
        updated=copy.deepcopy(original);updated['context_manifest_ref']=make_context(self.root)
        self.assertEqual(video_delivery.acceptance_fingerprint(original),video_delivery.acceptance_fingerprint(updated))
        updated['edited_media']['sha256']='b'*64
        self.assertNotEqual(video_delivery.acceptance_fingerprint(original),video_delivery.acceptance_fingerprint(updated))

    def test_user_reported_publication_is_not_lost_or_expanded_to_five_platforms(self):
        data=desk.new_project('synthetic-user-fact','Synthetic report')
        data['items'][0]['video']['sha256']='a'*64
        source=self.ref(dict(role='user',text='Synthetic user: I have published this video.'))
        fact=self.ref(dict(schema_version='self-media.publication-fact.v1',project_id=data['project_id'],
            kind='user_reported_published',video_sha256='a'*64,platforms=[],
            source_ref=source,quote='I have published this video.'))
        data['publication_fact_ref']=fact
        summary=desk.publication_summary(data)
        self.assertEqual(summary['status'],'user_reported_published')
        self.assertEqual(summary['platforms'],[])
        self.assertFalse(summary['platform_scope_verified'])
        self.assertTrue(all(p['record']['status']=='prepared' for p in data['items'][0]['platforms'].values()))
        page=desk.render(data)
        self.assertIn('用户已报告发布',page)
        self.assertNotIn('未上传、未发布',page)
        data['items'][0]['video']['sha256']='b'*64
        with self.assertRaisesRegex(ValueError,'media_mismatch'):desk.render(data)

    def archive_case(self, link=False):
        import hashlib
        data=desk.new_project('synthetic-old-archive','Synthetic old archive')
        payload=b'Synthetic media bytes: archive metadata test, not a playable movie'
        data['items'][0]['video']=dict(path='D:/deleted/synthetic.mp4',sha256=hashlib.sha256(payload).hexdigest())
        archive=self.root/'old-project.zip'
        with zipfile.ZipFile(archive,'w') as package:
            package.writestr('old/desk.json',json.dumps(data))
            if link:
                info=zipfile.ZipInfo('old/synthetic.mp4');info.create_system=3;info.external_attr=(stat.S_IFLNK|0o777)<<16
                package.writestr(info,payload)
            else:package.writestr('old/synthetic.mp4',payload)
        return archive,hashlib.sha256(archive.read_bytes()).hexdigest(),data

    def test_formal_archive_restore_rebinds_hashed_assets_without_changing_source(self):
        archive,digest,original=self.archive_case()
        output=self.root/'restored'
        run=subprocess.run([sys.executable,str(ROOT/'scripts/self_media_agent.py'),'publication-desk','restore-archive',
            '--archive',str(archive),'--archive-sha256',digest,'--data-member','old/desk.json','--output-dir',str(output)],
            capture_output=True,text=True,encoding='utf8',timeout=30)
        self.assertEqual(run.returncode,0,run.stdout+run.stderr)
        data=json.loads((output/'publication-data.json').read_text(encoding='utf8'))
        video=data['items'][0]['video']
        self.assertTrue(Path(video['path']).is_file())
        self.assertEqual(video['sha256'],original['items'][0]['video']['sha256'])
        self.assertEqual(data['items'][0]['platforms'],desk.upgrade(original)['items'][0]['platforms'])
        self.assertTrue(json.loads(run.stdout)['original_archive_unchanged'])
        self.assertFalse(json.loads(run.stdout)['rebuild_verified'])

    def test_archive_restore_rejects_changed_archive_and_dependency_link(self):
        import archive_workflow,artifact_lifecycle
        archive,digest,_=self.archive_case(link=True)
        target=self.root/'must-not-exist'
        with self.assertRaisesRegex(ValueError,'dependency_link'):
            archive_workflow.restore_publication(artifact_lifecycle,dict(path=str(archive),sha256=digest),'old/desk.json',target)
        self.assertFalse(target.exists())
        with self.assertRaisesRegex(ValueError,'changed_or_linked'):
            archive_workflow.restore_publication(artifact_lifecycle,dict(path=str(archive),sha256='f'*64),'old/desk.json',target)

    def test_legacy_state_sync_preserves_every_old_value_and_continue_uses_current_request(self):
        import entry_selection
        data=self.ref(desk.new_project('synthetic-state-sync','Synthetic old state'))
        request=self.ref(self.request('publication_page',publication_data=data))
        old=dict(locked_media='synthetic-frozen-v5',accepted_choices=['no-navigation','keep-small-caption-error'],
                 publicationPreparation=dict(published=False),owner_notes='must remain unchanged')
        state=self.ref(old);receipt=self.root/'state-sync.json';output=self.root/'state-current.json'
        value=entry_selection.sync_project(agent,state['path'],request['path'],state['sha256'],receipt,output=output)
        current=json.loads(output.read_text(encoding='utf8'))
        self.assertTrue(all(current[key]==value for key,value in old.items()))
        self.assertTrue(value['legacy_values_preserved'])
        state_ref=dict(path=str(output),sha256=agent.sha256_file(output))
        selected=agent.resolve_request(self.request('continue',project_state=state_ref))
        self.assertEqual(selected['primary_entry'],'publication_desk')
        self.assertEqual(selected['project_state_ref'],state_ref)
        self.assertEqual(Path(state['path']).read_text(encoding='utf8'),json.dumps(old,ensure_ascii=False))

    def test_state_sync_drift_and_foreign_rebind_are_rejected_without_mutation(self):
        import entry_selection
        data=self.ref(desk.new_project('synthetic-state-sync','Synthetic old state'))
        request=self.ref(self.request('publication_page',publication_data=data))
        state=self.ref(dict(workflow_current=dict(schema_version='self-media-project-entry.v1',project_id='other-project')))
        original=Path(state['path']).read_bytes()
        for checksum,code in [('f'*64,'project_state_drift'),(state['sha256'],'project_sync_identity_conflict')]:
            with self.assertRaises(agent.AgentEntryError) as raised:
                entry_selection.sync_project(agent,state['path'],request['path'],checksum,self.root/(code+'.json'),apply=True)
            self.assertEqual(raised.exception.code,code)
            self.assertEqual(Path(state['path']).read_bytes(),original)


class PublicationMigrationClosureTests(unittest.TestCase):
    def test_javascript_and_python_use_the_same_rule_basis_including_same_version_changes(self):
        node=os.environ.get('SELF_MEDIA_TEST_NODE') or shutil.which('node')
        if not node:self.skipTest('Existing Node required; no installation during tests')
        data=desk.new_project('synthetic-parity','Synthetic rules')
        script="const fs=require('node:fs'),m=require(process.argv[1]),v=JSON.parse(fs.readFileSync(0,'utf8'));console.log(JSON.stringify(v.rows.map(([k,n])=>m.platformCheckSnapshot(v.item,k,n,v.policy))));"
        for mutate in (False,True):
            policy=desk.platform_policy()
            if mutate:policy['platforms']['douyin']['field_limits']['title']=999
            item=data['items'][0]
            rows=[(key,name) for key,p in item['platforms'].items() for name in p['platform_checks']]
            with patch.object(desk,'platform_policy',return_value=policy):
                expected=[desk.platform_check_snapshot(item,key,name) for key,name in rows]
            run=subprocess.run([node,'-e',script,str(ROOT/'templates/publication-desk/manual-desk.js')],
                input=json.dumps(dict(item=item,policy=policy,rows=rows)),capture_output=True,text=True,encoding='utf8',timeout=15)
            self.assertEqual(run.returncode,0,run.stderr)
            self.assertEqual(json.loads(run.stdout),expected)

    def old_project(self):
        data = desk.new_project('synthetic-old-project', '合成迁移测试，不是真实作品')
        data.pop('platform_policy_sha256', None)
        item = data['items'][0]
        for key, platform in item['platforms'].items():
            platform['fields']['body'] = 'Synthetic author text must survive.'
            platform['record'].update(status='planned', planned_at='2026-10-29')
        item['platforms']['kuaishou']['fields']['title'] = 'Synthetic retired title, retain as history'
        return data

    def test_policy_change_without_version_bump_invalidates_only_affected_checks(self):
        data = desk.new_project('synthetic-policy-drift', 'Synthetic rules')
        item = data['items'][0]
        name = next(iter(item['platforms']['douyin']['platform_checks']))
        before = desk.platform_check_snapshot(item, 'douyin', name)
        policy = desk.platform_policy()
        changed = copy.deepcopy(policy)
        changed['platforms']['douyin']['field_limits']['title'] = 999
        with patch.object(desk, 'platform_policy', return_value=changed):
            after = desk.platform_check_snapshot(item, 'douyin', name)
        self.assertNotEqual(before, after, 'A version label alone cannot bind mutable policy content')
        tag_before = desk.platform_check_snapshot(item, 'douyin', 'tags')
        with patch.object(desk, 'platform_policy', return_value=changed):
            self.assertEqual(tag_before, desk.platform_check_snapshot(item, 'douyin', 'tags'))

    def test_default_render_migrates_old_data_and_preserves_author_records(self):
        old = self.old_project()
        original = copy.deepcopy(old)
        page = desk.render(old)
        embedded = page.split('<script id="desk-data" type="application/json">', 1)[1].split('</script>', 1)[0]
        current = json.loads(embedded)
        self.assertEqual(old, original, 'Rendering cannot mutate the old source object')
        self.assertIn('platform_policy_sha256', current)
        self.assertEqual(current['items'][0]['platforms']['kuaishou']['retired_fields']['title'],
                         original['items'][0]['platforms']['kuaishou']['fields']['title'])
        self.assertEqual(current['items'][0]['platforms']['douyin']['record'],
                         original['items'][0]['platforms']['douyin']['record'])
        self.assertEqual(current['items'][0]['platforms']['douyin']['fields']['body'],
                         'Synthetic author text must survive.')

    def test_upgrade_is_idempotent_so_continue_does_not_loop_forever(self):
        first = desk.upgrade(self.old_project())
        self.assertEqual(desk.upgrade(first), first)


if __name__ == '__main__':
    unittest.main()
