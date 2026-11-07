"""Native-cover-test preparation, distinct from ratio slots and live submission."""
import copy, hashlib, json, sys, tempfile, unittest
from pathlib import Path
from datetime import datetime, timedelta, timezone
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import publication_desk as desk


class ParallelCoverTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();root=Path(self.temp.name)
        self.data=desk.new_project('synthetic-parallel-covers','Synthetic cover test')
        self.item=self.data['items'][0]
        main_path=root/'independent-main.png';Image.new('RGB',(480,640),(10,20,30)).save(main_path)
        self.item['covers'].append(dict(id='main-independent',path=str(main_path),sha256=hashlib.sha256(main_path.read_bytes()).hexdigest()))
        self.item['platforms']['xiaohongshu']['cover_test']={'requested':False,'main_cover_id':'main-independent'}
        candidates=[]
        for number,cid in enumerate(('A','B','F')):
            mapping={}
            for ratio,size in {'3:4':(480,640),'4:3':(640,480),'16:9':(960,540)}.items():
                aid=cid+'_'+ratio.replace(':','x');path=root/(aid+'.png')
                Image.new('RGB',size,(40+number*60,80,120)).save(path)
                self.item['covers'].append(dict(id=aid,path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
                mapping[ratio]=aid
            candidates.append(dict(id=cid,name=cid,title='Synthetic title',hypothesis='Synthetic comparison',cover_by_ratio=mapping))
        self.item['cover_pk'].update(candidates=candidates,required_ratios=['3:4','4:3','16:9'])
        self.item['cover_pk']['platform_ratios']['kuaishou']=['3:4']
        for key,p in self.item['platforms'].items():
            p['fields'].update(body='Synthetic body',tags='#synthetic')
            if 'title' in p['fields']:p['fields']['title']='Synthetic'
            if key=='weixin_channels':p['fields']['short_title']='Synthetic'
            ratios=self.item['cover_pk']['platform_ratios'][key]
            p['cover_ids']=[candidates[0]['cover_by_ratio'][r] for r in ratios]

    def tearDown(self):self.temp.cleanup()
    def codes(self,stage='preparation'):
        return [r['code'] for r in desk.check_platforms(self.data,stage)['issues']]
    def apply(self,ids=('A','B','F'),platform_key=None):
        desk.apply_cover_test_selection(self.item,ids,platform_key=platform_key)
    def confirm_synthetic_submission(self):
        today=datetime.now(timezone(timedelta(hours=8))).date().isoformat()
        for key,p in self.item['platforms'].items():
            p['cover_test'].update(interface_status='confirmed',interface_evidence='synthetic test evidence only',checked_at=today,confirmed_candidate_limit=3)
            for name,c in p['platform_checks'].items():
                c.update(status='confirmed',evidence='synthetic test only',checked_at=today,input_snapshot=desk.platform_check_snapshot(self.item,key,name))

    def test_existing_single_cover_rules_unchanged(self):
        self.assertTrue(desk.check_platforms(self.data,'preparation')['complete'])
        self.item['platforms']['kuaishou']['cover_ids']=['A_3x4','B_3x4']
        self.assertIn('choose_one_cover',self.codes())

    def test_three_creatives_are_not_six_ratio_variants(self):
        self.item['cover_pk']['selected_at']='synthetic-prior-selection'
        self.apply();desk.validate(self.data)
        self.assertNotIn('selected_at',self.item['cover_pk'])
        self.assertIsNone(self.item['cover_pk']['selected'])
        self.assertEqual(self.item['cover_pk']['test_candidate_ids'],['A','B','F'])
        plan=desk.cover_test_plan(self.item,'bilibili')
        self.assertEqual(len(plan['variants']),3)
        self.assertEqual(len(self.item['platforms']['bilibili']['cover_ids']),6)
        self.assertTrue(desk.check_platforms(self.data,'preparation')['complete'])
        self.assertTrue(desk.check_packaging(self.data)['complete'])

    def test_one_ratio_platform_can_prepare_three_parallel_creatives(self):
        self.apply();p=self.item['platforms']['kuaishou']
        self.assertEqual(p['cover_ids'],['A_3x4','B_3x4','F_3x4'])
        self.assertNotIn('choose_one_cover',self.codes())
        self.assertEqual(desk.cover_test_plan(self.item,'kuaishou')['ratios'],['3:4'])

    def test_one_ratio_platform_cannot_call_two_ratios_a_test(self):
        self.apply();p=self.item['platforms']['kuaishou']
        p['cover_test']['ratios']=['3:4','4:3']
        self.assertIn('cover_test_plan_invalid',self.codes())

    def test_missing_ratio_of_one_variant_is_not_hidden_by_other_variants(self):
        self.apply();self.item['cover_pk']['candidates'][1]['cover_by_ratio'].pop('16:9')
        self.assertIn('cover_test_plan_invalid',self.codes())

    def test_single_or_duplicate_candidate_rejected_without_mutation(self):
        for ids in [('A',),('A','A'),('A','unknown')]:
            before=copy.deepcopy(self.item)
            with self.assertRaises(ValueError):self.apply(ids)
            self.assertEqual(self.item,before)

    def test_local_preparation_never_confirms_live_account_feature(self):
        self.apply();self.assertTrue(desk.check_platforms(self.data,'preparation')['complete'])
        pending=[r for r in desk.check_platforms(self.data,'submission')['issues'] if r['code']=='cover_test_interface_pending']
        self.assertEqual(len(pending),5)
        self.assertTrue(all(p['cover_test']['interface_status']=='pending' for p in self.item['platforms'].values()))

    def test_live_count_limit_and_current_evidence_are_required(self):
        self.apply();self.confirm_synthetic_submission()
        self.assertTrue(desk.check_platforms(self.data,'submission')['complete'])
        self.item['platforms']['kuaishou']['cover_test']['confirmed_candidate_limit']=2
        self.assertIn('cover_test_candidate_limit',self.codes('submission'))
        self.assertIn('cover_test_candidate_limit',self.codes('preparation'))
        self.item['platforms']['kuaishou']['cover_test']['checked_at']='2000-01-01'
        self.assertIn('cover_test_interface_pending',self.codes('submission'))

    def test_platform_can_use_two_of_the_three_author_candidates(self):
        self.apply();self.apply(('A','F'),platform_key='kuaishou')
        self.assertEqual(self.item['platforms']['kuaishou']['cover_ids'],['A_3x4','F_3x4'])
        self.assertEqual(len(self.item['platforms']['xiaohongshu']['cover_test']['candidate_ids']),3)
        self.assertEqual(self.item['cover_pk']['test_candidate_ids'],['A','B','F'])
        self.assertTrue(desk.check_platforms(self.data,'preparation')['complete'])

    def test_changed_test_candidates_invalidate_prior_related_evidence(self):
        self.apply();self.confirm_synthetic_submission()
        self.apply(('A','F'),platform_key='kuaishou')
        stale=[r for r in desk.check_platforms(self.data,'submission')['issues'] if r['code']=='platform_check_inputs_changed']
        self.assertTrue(any(r['platform']=='kuaishou' and r['detail'].startswith('cover_pk') for r in stale))
        self.assertFalse(any(r['platform']=='weixin_channels' for r in stale))

    def test_winner_or_wrong_upload_assignment_cannot_bypass_test_rules(self):
        self.apply();self.item['cover_pk']['selected']='F'
        self.assertIn('cover_test_plan_invalid',self.codes())
        self.item['cover_pk']['selected']=None
        self.item['platforms']['xiaohongshu']['cover_ids']=['A_3x4','A_3x4','F_3x4']
        self.assertIn('cover_test_plan_invalid',self.codes())

    def test_mode_and_candidates_roundtrip_with_same_public_copy(self):
        before=copy.deepcopy({k:p['fields'] for k,p in self.item['platforms'].items()})
        self.apply();saved=json.loads(json.dumps(self.data));desk.validate(saved)
        self.assertEqual(saved['items'][0]['cover_pk']['selection_mode'],'parallel_test')
        self.assertEqual({k:p['fields'] for k,p in saved['items'][0]['platforms'].items()},before)

    def test_xhs_primary_is_additional_to_three_candidates(self):
        self.apply();plan=desk.cover_test_plan(self.item,'xiaohongshu')
        self.assertEqual(plan['main_cover_id'],'main-independent')
        self.assertEqual(plan['total_cover_count'],4)
        self.assertEqual(plan['max_candidates'],3)
        self.assertEqual(len(plan['candidate_ids']),3)
        self.assertEqual(len(desk.platform_cover_ids(self.item,'xiaohongshu')),4)
        self.assertTrue(desk.check_platforms(self.data,'preparation')['complete'])

    def test_xhs_missing_primary_is_not_hidden_by_three_candidates(self):
        self.apply();self.item['platforms']['xiaohongshu']['cover_test']['main_cover_id']=''
        self.assertIn('main_cover_required',self.codes())

    def test_xhs_primary_cannot_also_be_a_pk_candidate(self):
        self.apply();self.item['platforms']['xiaohongshu']['cover_test']['main_cover_id']='A_3x4'
        with self.assertRaisesRegex(ValueError,'main_cover_must_differ'):
            desk.cover_test_plan(self.item,'xiaohongshu')

    def test_xhs_may_use_one_pk_candidate_beside_primary(self):
        self.apply();self.apply(('A',),platform_key='xiaohongshu')
        plan=desk.cover_test_plan(self.item,'xiaohongshu')
        self.assertEqual(plan['total_cover_count'],2)
        self.assertTrue(desk.check_platforms(self.data,'preparation')['complete'])

    def test_xhs_four_pk_candidates_rejected_without_mutation(self):
        self.apply();self.item['cover_pk']['candidates'].append(dict(self.item['cover_pk']['candidates'][0],id='fourth'))
        self.item['cover_pk']['test_candidate_ids'].append('fourth')
        before=copy.deepcopy(self.item)
        with self.assertRaisesRegex(ValueError,'pk_candidate_limit_exceeded'):
            self.apply(('A','B','F','fourth'),platform_key='xiaohongshu')
        self.assertEqual(self.item,before)

    def test_xhs_primary_change_invalidates_crop_evidence(self):
        self.apply();self.confirm_synthetic_submission()
        self.item['platforms']['xiaohongshu']['cover_test']['main_cover_id']=''
        stale=[i for i in desk.check_platforms(self.data,'submission')['issues'] if i['code']=='platform_check_inputs_changed']
        self.assertTrue(any(i['platform']=='xiaohongshu' and i['detail'].startswith('crop_preview') for i in stale))
        self.assertFalse(any(i['platform']=='douyin' for i in stale))

if __name__=='__main__':unittest.main()
