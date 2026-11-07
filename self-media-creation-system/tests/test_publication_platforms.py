"""Regression cases for the repeated platform omissions; no live account actions."""
import sys, tempfile, unittest, copy
from pathlib import Path
from datetime import date
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import publication_desk as desk
import video_delivery
from PIL import Image

class PlatformGate(unittest.TestCase):
    def test_channels_only_short_title(self):
        data=desk.new_project('p','t',['weixin_channels'])
        fields=data['items'][0]['platforms']['weixin_channels']['fields']
        self.assertNotIn('title',fields)
        self.assertIn('short_title',fields)
        with tempfile.TemporaryDirectory() as tmp:
            data=self.fixture(Path(tmp))
            data['items'][0]['platforms']['weixin_channels']['fields']['title']='wrong'
            self.assertIn('separate_title_not_applicable',[x['code'] for x in desk.check_platforms(data,'preparation')['issues']])

    def test_kuaishou_has_description_not_separate_title(self):
        data=desk.new_project('p','t',['kuaishou'])
        self.assertNotIn('title',data['items'][0]['platforms']['kuaishou']['fields'])
        with tempfile.TemporaryDirectory() as tmp:
            data=self.fixture(Path(tmp))
            data['items'][0]['platforms']['kuaishou']['fields']['title']='incorrect'
            self.assertIn('separate_title_not_applicable',[x['code'] for x in desk.check_platforms(data,'preparation')['issues']])

    def fixture(self, root):
        data=desk.new_project('synthetic','Synthetic',['douyin','xiaohongshu','weixin_channels','kuaishou','bilibili'])
        item=data['items'][0]
        for ratio,size in {'3:4':(30,40),'4:3':(40,30),'16:9':(160,90)}.items():
            path=root/(ratio.replace(':','x')+'.png');Image.new('RGB',size).save(path)
            item['covers'].append(dict(id=ratio,path=str(path),sha256=''))
        for key,p in item['platforms'].items():
            p['fields'].update(title='Synthetic',body='Synthetic',tags='synthetic')
            if key in ('kuaishou','weixin_channels'):p['fields'].pop('title',None)
            if key=='weixin_channels':p['fields']['short_title']='Synthetic'
            profile=desk.platform_policy()['platforms'][key]
            p['cover_ids']=profile['cover_ratios'][:1] if profile['cover_mode']=='one' else profile['cover_ratios'][:]
            for name,c in p['platform_checks'].items():
                c.update(status='confirmed',evidence='synthetic',checked_at=date.today().isoformat(),
                         input_snapshot=desk.platform_check_snapshot(item,key,name))
        return data

    def test_short_title_only_channels_and_unknown_platform_blocked(self):
        data=desk.new_project('p','t')
        for k,p in data['items'][0]['platforms'].items():self.assertEqual('short_title' in p['fields'],k=='weixin_channels')
        data['items'][0]['platforms']['douyin']['fields']['short_title']='wrong'
        with self.assertRaisesRegex(ValueError,'short_title_not_applicable'):desk.validate(data)
        # The default renderer adapts an old saved field instead of exposing an
        # unusable input box; its text remains available as historical data.
        migrated=desk.upgrade(data)
        self.assertNotIn('short_title',migrated['items'][0]['platforms']['douyin']['fields'])
        self.assertEqual(migrated['items'][0]['platforms']['douyin']['retired_fields']['short_title'],
                         data['items'][0]['platforms']['douyin']['fields']['short_title'])
        self.assertIn('desk-data',desk.render(data))
        with self.assertRaises(ValueError):desk.new_project('p','t',['unknown'])

    def test_missing_slot_fake_label_and_choose_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            data=self.fixture(Path(tmp));self.assertTrue(desk.check_platforms(data)['complete'])
            bad=copy.deepcopy(data);bad['items'][0]['platforms']['bilibili']['cover_ids']=['4:3']
            self.assertIn('missing_cover_slots',[i['code'] for i in desk.check_platforms(bad)['issues']])
            bad=copy.deepcopy(data);bad['items'][0]['covers'][2]['path']=bad['items'][0]['covers'][0]['path']
            self.assertFalse(desk.check_platforms(bad)['complete']) # filename/id cannot substitute for pixels
            bad=copy.deepcopy(data);bad['items'][0]['platforms']['kuaishou']['cover_ids']=['4:3','3:4']
            self.assertIn('choose_one_cover',[i['code'] for i in desk.check_platforms(bad)['issues']])

    def test_omitted_stale_or_blank_evidence_blocks_completion(self):
        with tempfile.TemporaryDirectory() as tmp:
            data=self.fixture(Path(tmp));p=data['items'][0]['platforms']['weixin_channels']
            p['platform_checks']['current_specs']['checked_at']='2026-08-28'
            self.assertIn('current_specs_stale',[i['code'] for i in desk.check_platforms(data)['issues']])
            p['platform_checks']={}
            data['items'][0]['platforms']['douyin']['fields']['body']=''
            with patch.object(video_delivery,'read_ref',return_value=data):
                with self.assertRaisesRegex(ValueError,'platform_requirements_incomplete'):
                    video_delivery.render_check({'desk_ref':{}})
            self.assertIn('draft',desk.render(data)) # draft allowed, never complete

    def test_optional_not_applicable_requires_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            data=self.fixture(Path(tmp));c=data['items'][0]['platforms']['douyin']['platform_checks']['collection']
            c.update(status='not_applicable',evidence='single item, no collection')
            self.assertTrue(desk.check_platforms(data)['complete'])
            c['evidence']='';self.assertFalse(desk.check_platforms(data)['complete'])

    def test_preparation_checks_limits_and_symbols_without_faking_submission(self):
        with tempfile.TemporaryDirectory() as tmp:
            data=self.fixture(Path(tmp))
            for p in data['items'][0]['platforms'].values():p['platform_checks']={}
            self.assertTrue(desk.check_platforms(data,'preparation')['complete'])
            self.assertFalse(desk.check_platforms(data)['complete'])
            p=data['items'][0]['platforms']['weixin_channels']
            p['fields']['short_title']='同一个滑梯，十个月后'
            self.assertIn('short_title_symbol_not_allowed',[x['code'] for x in desk.check_platforms(data,'preparation')['issues']])
            p['fields']['short_title']='同一个滑梯 十个月后'
            data['items'][0]['platforms']['xiaohongshu']['fields']['title']='长'*21
            self.assertIn('baseline_field_too_long',[x['code'] for x in desk.check_platforms(data,'preparation')['issues']])

    def test_changed_copy_cannot_reuse_its_upload_checks(self):
        with tempfile.TemporaryDirectory() as tmp:
            data=self.fixture(Path(tmp));p=data['items'][0]['platforms']['xiaohongshu']
            p['fields']['body']='new copy'
            issues=desk.check_platforms(data)['issues']
            self.assertEqual([(i['platform'],i['code'],i['detail'].split('：')[0]) for i in issues],
                             [('xiaohongshu','platform_check_inputs_changed','disclosure')])
            self.assertTrue(desk.check_platforms(data,'preparation')['complete'])

if __name__=='__main__':unittest.main()
