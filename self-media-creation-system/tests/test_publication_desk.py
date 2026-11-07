import copy
import hashlib
import json
import re
import tempfile
import unittest
import contextlib
import io
import importlib.util
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("repo_publication_desk", ROOT / "scripts/publication_desk.py")
desk = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(desk)


def draft():
    return dict(schema_version='local-publication-page-draft.v1', content_name='Synthetic project',
                assets=dict(video_path='D:/synthetic-only/video.mp4',cover_path='D:/synthetic-only/cover.jpg'),
                platforms={'douyin':dict(title='Synthetic title',body='Synthetic body',tags='#synthetic')})


class DurableDesk(unittest.TestCase):
    def test_new_project_is_independent_and_blank(self):
        a=desk.new_project('project-a','全新项目 A')
        b=desk.new_project('project-b','全新项目 B')
        self.assertEqual(set(a['items'][0]['platforms']),set(desk.platform_policy()['default_platforms']))
        a['items'][0]['platforms']['douyin']['fields']['title']='只属于 A'
        self.assertEqual(b['items'][0]['platforms']['douyin']['fields']['title'],'')
        self.assertNotIn('source_snapshot',b)
        for platform in b['items'][0]['platforms'].values():
            self.assertEqual(platform['fields']['collection_name'],'')
            self.assertEqual(platform['fields']['collection_description'],'')
        self.assertEqual(b['items'][0]['video']['path'],'')
        self.assertEqual(desk.inspect_assets(b)[0]['status'],'missing')
        self.assertEqual(desk.new_project('p','t',['wechat_video'])['items'][0]['platforms'].keys(),{'weixin_channels'})
        for bad in [[],['unknown'],['wechat_video','weixin_channels']]:
            with self.assertRaises(ValueError): desk.new_project('p','t',bad)

    def test_cli_reuse_from_scratch_and_discovery(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()) as output:
            source=Path(tmp)/'new.json';page=Path(tmp)/'new.html'
            args=['init','--project-id','unrelated-new-project','--title','新的视频项目',
                  '--platforms','douyin','bilibili','--output',str(source)]
            self.assertEqual(desk.main(args),0)
            self.assertEqual(desk.main(args),2)  # refuse overwrite
            self.assertEqual(desk.main(['check','--input',str(source)]),2) # blank is not ready
            payload=json.loads(source.read_text(encoding='utf-8'))
            media=Path(tmp)/'synthetic.mp4';media.write_bytes(b'synthetic asset, not a playable video')
            payload['items'][0]['video']=dict(path=str(media),sha256=hashlib.sha256(media.read_bytes()).hexdigest())
            payload['items'][0]['platforms']['douyin']['fields'].update(title='全新标题',body='当前项目简介',tags='#合成测试')
            source.write_text(json.dumps(payload,ensure_ascii=False),encoding='utf-8')
            self.assertEqual(desk.main(['check','--input',str(source)]),2) # a video alone does not complete platform work
            self.assertEqual(desk.main(['render','--input',str(source),'--output',str(page)]),0)
            self.assertIn('新的视频项目',page.read_text(encoding='utf-8'))
            self.assertIn('全新标题',page.read_text(encoding='utf-8'))
            self.assertNotIn('划船歌',page.read_text(encoding='utf-8'))
            self.assertEqual(desk.main(['render','--output',str(page)]),2)
            output.seek(0);output.truncate()
            info=desk.capabilities()
            self.assertIn('init',info['actions'])
            self.assertTrue(Path(info['agent_recipe']).is_file())

    def test_edited_data_roundtrip_and_escaping(self):
        data=desk.normalize(draft()); data['items'][0]['platforms']['douyin']['fields']['title']='</script> & test'
        data['items'][0]['platforms']['douyin']['record']['status']='scheduled'
        page=desk.render(data)
        saved=json.loads(re.search(r'id="desk-data" type="application/json">(.*?)</script>',page,re.S)[1])
        # Default generation upgrades legacy data but preserves authored copy,
        # scheduling and the original object; saved HTML is the current project.
        self.assertEqual(saved['items'][0]['platforms']['douyin']['fields']['title'], '</script> & test')
        self.assertEqual(saved['items'][0]['platforms']['douyin']['record'], data['items'][0]['platforms']['douyin']['record'])
        self.assertEqual(desk.upgrade(saved), saved)
        self.assertNotIn('platform_policy_sha256', data)
        self.assertNotIn('</script> & test',page)
        self.assertNotIn('20260826-eight-cover-user-selected',page)

    def test_schedule_does_not_become_publication(self):
        data=desk.normalize(draft()); p=data['items'][0]['platforms']['douyin'];p['record'].update(status='scheduled',scheduled_for='2026-10-01')
        result=desk.operations_handoff(data)
        self.assertEqual(result['entries'][0]['route'],'publication_package_schedule_only')
        self.assertFalse(result['publication_events_written'])
        p['record']['status']='published'
        pending=desk.operations_handoff(data)['entries'][0]
        self.assertIn('published_at',pending['missing_fields']); self.assertFalse(pending['executable'])

    def test_hash_mismatch_and_missing_file_reported(self):
        data=desk.normalize(draft())
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'sample.mp4';path.write_bytes(b'synthetic')
            data['items'][0]['video']=dict(path=str(path),sha256=hashlib.sha256(b'synthetic').hexdigest())
            self.assertEqual(desk.inspect_assets(data)[0]['status'],'verified')
            path.write_bytes(b'changed');self.assertEqual(desk.inspect_assets(data)[0]['status'],'hash_mismatch')
            path.unlink();self.assertEqual(desk.inspect_assets(data)[0]['status'],'missing')

    def test_legacy_adapter_preserves_source_and_optional_fields(self):
        old={'items':[{'id':'one','video':{'path':'D:/synthetic.mp4','sha256':''},'covers':{},
                      'platforms':{'wechat_video':{'title':'t','caption':'c','topic_candidates':['x'],'short_title':'s'}}}],
             'publishing_schedule':{'planned':'2026-10-01'},'platform_capabilities':{'wechat_video':{'limit':16}},'generated_at':'2026-08-28'}
        data=desk.normalize(old,'synthetic-source.json')
        self.assertEqual(data['source_snapshot'],old)
        self.assertEqual(data['items'][0]['platforms']['weixin_channels']['fields']['short_title'],'s')
        self.assertEqual(data['rules'][0]['status'],'historical_needs_recheck')
        self.assertEqual(data['items'][0]['platforms']['weixin_channels']['record']['status'],'prepared')

    def test_no_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'draft.json';desk.write_new(p,{'keep':True})
            with self.assertRaises(FileExistsError):desk.write_new(p,{})
            self.assertEqual(json.loads(p.read_text()),{'keep':True})
