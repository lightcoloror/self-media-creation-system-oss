"""Real file/entrypoint regressions for requirements reaching generated artifacts."""
import copy
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import publication_desk as desk
import video_review_delivery as review


class WorkflowApplication(unittest.TestCase):
    def setUp(self):
        parent = ROOT/'.test-runtime'
        parent.mkdir(exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def asset(self, name, color='pink', size=(480,640)):
        path=self.root/name
        Image.new('RGB',size,color).save(path)
        return dict(id=name,label=name,path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest())

    def project(self):
        data=desk.new_project('synthetic-application','合成流程验证',['xiaohongshu'])
        item=data['items'][0]
        item['platforms']['xiaohongshu']['fields'].update(title='未剧透标题',body='测试正文',tags='#测试')
        item['covers']=[self.asset('a.png'),self.asset('b.png','blue')]
        item['platforms']['xiaohongshu']['cover_ids']=['a.png']
        item['cover_pk'].update(candidates=[dict(id=k,name=k,title='方案'+k,hypothesis='测试角度'+k,cover_by_ratio={'3:4':f'{k}.png'}) for k in ('a','b')],recommended='a')
        return data

    def test_upgrade_legacy_fields_preserves_user_content_and_records(self):
        old=desk.new_project('legacy','旧项目',['kuaishou','weixin_channels'])
        old.pop('target_platforms');old.pop('platform_policy_version')
        for p in old['items'][0]['platforms'].values():
            p['fields'].update(title='旧标题不可丢',body='用户编辑的正文')
            p['record'].update(status='scheduled',scheduled_for='2026-10-26T20:00:00+08:00')
        old['items'][0]['platforms']['kuaishou']['fields']['short_title']='不适用短标题'
        before=copy.deepcopy(old)
        upgraded=desk.upgrade(old,platforms=['kuaishou','weixin_channels'])
        self.assertEqual(old,before)
        for k,p in upgraded['items'][0]['platforms'].items():
            self.assertNotIn('title',p['fields'])
            self.assertEqual(p['retired_fields']['title'],'旧标题不可丢')
            self.assertEqual(p['fields']['body'],'用户编辑的正文')
            self.assertEqual(p['record']['status'],'scheduled')
            self.assertEqual(p['record']['published_at'],'')
        saved=copy.deepcopy(upgraded)
        page=desk.render(upgraded)
        embedded=json.loads(re.search(r'id="desk-data" type="application/json">(.*?)</script>',page,re.S)[1])
        summary=embedded.pop('publication_summary')
        self.assertFalse(summary['platform_scope_verified'])
        self.assertEqual(embedded,upgraded)
        self.assertEqual(upgraded,saved)
        self.assertIn('desk-build',page)

    def test_upgrade_handles_unbound_optional_checks_before_page_opens(self):
        data=self.project();p=data['items'][0]['platforms']['xiaohongshu']
        p['platform_checks']['collection'].update(status='not_applicable',evidence='此前明确不使用合集')
        migrated=desk.upgrade(data)
        check=migrated['items'][0]['platforms']['xiaohongshu']['platform_checks']['collection']
        self.assertEqual(check['status'],'pending')
        self.assertEqual(check['previous_evidence'][0]['evidence'],'此前明确不使用合集')

    def test_missing_platform_after_saved_selection_fails(self):
        data=desk.new_project('p','五平台')
        self.assertEqual(len(data['target_platforms']),5)
        del data['items'][0]['platforms']['bilibili']
        self.assertIn('platform_scope_mismatch',[i['code'] for i in desk.check_platforms(data,'preparation')['issues']])

    def test_corrupt_image_is_not_embedded_even_when_header_has_geometry(self):
        data=self.project();cover=data['items'][0]['covers'][0];path=Path(cover['path'])
        path.write_bytes(path.read_bytes()[:50]);cover['sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
        self.assertIn('unreadable_cover_geometry',[i['code'] for i in desk.check_platforms(data,'preparation')['issues']])
        page=desk.render(data)
        previews=json.loads(re.search(r'id="cover-previews" type="application/json">(.*?)</script>',page,re.S)[1])
        self.assertNotIn(str(path),previews)

    def test_actual_images_and_comparison_matrix_not_file_count(self):
        data=self.project();self.assertTrue(desk.check_packaging(data)['complete'])
        item=data['items'][0];item['cover_pk']['candidates'][1]['cover_by_ratio']['3:4']='a.png'
        self.assertIn('cover_candidate_same_image',[r['code'] for r in desk.check_packaging(data)['issues']])
        item['cover_pk']['candidates'][1]['cover_by_ratio']={}
        self.assertIn('cover_candidate_ratio_missing',[r['code'] for r in desk.check_packaging(data)['issues']])
        item['cover_pk']['candidates']=item['cover_pk']['candidates'][:1]
        self.assertIn('cover_comparison_missing',[r['code'] for r in desk.check_packaging(data)['issues']])
        item['cover_pk'].pop('requested')
        self.assertIn('cover_comparison_missing',[r['code'] for r in desk.check_packaging(data)['issues']])

    def test_no_spoiler_rule_checks_active_candidates_and_platform_copy(self):
        data=self.project();data['editorial_context']={'forbidden_public_phrases':['我爱你']}
        data['items'][0]['platforms']['xiaohongshu']['fields']['body']='她说我爱你'
        self.assertIn('forbidden_public_phrase',[r['code'] for r in desk.check_packaging(data)['issues']])

    def test_browser_and_cli_bind_checks_to_the_same_affected_inputs(self):
        data=self.project();item=data['items'][0];key='xiaohongshu';p=item['platforms'][key]
        for name,c in p['platform_checks'].items():
            c.update(status='confirmed',evidence='synthetic only',input_snapshot=desk.platform_check_snapshot(item,key,name))
        program="""
const fs=require('node:fs'), desk=require('./templates/publication-desk/manual-desk.js');
const {data,policy}=JSON.parse(fs.readFileSync(0,'utf8')),item=data.items[0],p=item.platforms.xiaohongshu;
const before=desk.platformCheckSnapshot(item,'xiaohongshu','disclosure',policy);
p.fields.tags='#changed';desk.invalidateChangedChecks(data,policy);
console.log(JSON.stringify({before,checks:p.platform_checks}));
"""
        run=subprocess.run(['node','-e',program],input=json.dumps(dict(data=data,policy=desk.platform_policy())),
                           text=True,encoding='utf8',capture_output=True,check=True,cwd=ROOT)
        result=json.loads(run.stdout)
        self.assertEqual(result['before'],desk.platform_check_snapshot(item,key,'disclosure'))
        self.assertEqual(result['checks']['tags']['status'],'pending')
        self.assertEqual(result['checks']['disclosure']['status'],'pending')
        self.assertEqual(result['checks']['current_specs']['status'],'confirmed')
        self.assertEqual(result['checks']['collection']['status'],'confirmed')
        self.assertEqual(result['checks']['tags']['previous_evidence'][0]['evidence'],'synthetic only')

    def recipe(self):
        speech=dict(text='爸比',speaker='child',start_seconds=1.,end_seconds=2.)
        return dict(presentation_requirements=dict(required_layers=['dialogue'],animated_speakers=['child'],style_reason='已要求动态字幕'),
                    requests=[dict(review_id='one',review_start_seconds=0.,review_end_seconds=3.,expected_dialogue=[speech],
                                   subtitle_cues=[dict(speech,layer='dialogue',motion='bounce',font_size_1080=96)])])

    def test_fine_review_requires_actionable_style_and_dialogue_inputs(self):
        with self.assertRaisesRegex(ValueError,'requirements_required'):
            review.presentation_check({'requests':[]},'fine_cut_recipe')
        request=self.recipe();self.assertEqual(review.presentation_check(request,'fine_cut_recipe')['checked_cues'],1)
        request['requests'][0]['expected_dialogue'].append(dict(text='唉',speaker='father',start_seconds=2.,end_seconds=2.5))
        with self.assertRaisesRegex(ValueError,'expected_dialogue_not_in_preview'):
            review.presentation_check(request,'fine_cut_recipe')

    def test_small_static_or_inconsistent_captions_cannot_pass(self):
        for value,expected in [({'font_size_1080':36},'typography'),({'motion':'none'},'motion_missing')]:
            request=self.recipe();request['requests'][0]['subtitle_cues'][0].update(value)
            with self.assertRaisesRegex(ValueError,expected):review.presentation_check(request,'fine_cut_recipe')
        request=self.recipe();cue=copy.deepcopy(request['requests'][0]['subtitle_cues'][0]);cue['font_size_1080']=110
        request['requests'][0]['subtitle_cues'].append(cue)
        with self.assertRaisesRegex(ValueError,'without_emphasis_reason'):review.presentation_check(request,'fine_cut_recipe')
        cue['emphasis_reason']='这一声大喊特别强调'
        self.assertEqual(review.presentation_check(request,'fine_cut_recipe')['checked_cues'],2)


if __name__=='__main__': unittest.main()
