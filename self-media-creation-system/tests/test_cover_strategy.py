"""Synthetic planning contracts; no family media, video inference or model calls."""
import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import cover_workbench as w
import cover_strategy as s
import cover_design as d


class CoverStrategyTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.brief=w.init('synthetic-current-project','Synthetic video')
        self.brief.update(promise='synthetic editorial exercise',facts=['not real media'],content_kind='family')
        self.assets=[]
        for i,kind in enumerate(['photo','photo','evidence']):
            p=self.root/f'asset-{i}.bin';p.write_bytes(('synthetic-'+str(i)).encode())
            self.assets.append(dict(id='a'+str(i),kind=kind,artifact=w.reference(p),generated=False,
                local_use_approved=True,privacy_reviewed=True,subject_reviewed=True,protected_regions=[]))
        self.brief['assets']=self.assets
        p=self.root/'observation.txt';p.write_text('Synthetic reviewed observations, no actual child.',encoding='utf8')
        self.source=w.reference(p)
        self.counter=0

    def request(self, tutorial=False):
        self.counter+=1
        rp=self.root/f'route-{self.counter}.json';w.write(rp,w.plan(self.brief))
        req=s.init(rp)
        ev=[dict(id='e0',kind='visual',source_ref=self.assets[0]['artifact'],observation='first synthetic moment',
                 confidence='agent_observed',asset_ids=['a0'],role='demonstration',time_range_s=[10,11]),
            dict(id='e1',kind='visual',source_ref=self.assets[1]['artifact'],observation='second synthetic moment',
                 confidence='agent_observed',asset_ids=['a1'],role='reaction',time_range_s=[20,21]),
            dict(id='e2',kind='human_review',source_ref=self.source,observation='reviewed synthetic meaning contrast',
                 confidence='human_confirmed',asset_ids=[],role='context')]
        angles=[dict(id='warm',label='温情发现',hook='记住日常的歌',signals=['relationship','discovery'],evidence_ids=['e0'],priority=3),
                dict(id='story',label='示范后的反差',hook='教完仍有自己的版本',signals=['sequence','reversal'],evidence_ids=['e0','e1','e2'],priority=4,
                     relation=dict(kind='temporal',evidence_ids=['e0','e1'],explanation='synthetic temporal order')),
                dict(id='pun',label='意思和谐音',hook='梦变成面',signals=['wordplay'],evidence_ids=['e2'],priority=5)]
        if tutorial:
            ev.append(dict(id='e3',kind='visual',source_ref=self.assets[2]['artifact'],observation='synthetic interface evidence',
                           confidence='agent_observed',asset_ids=['a2'],role='detail'))
            angles=[dict(id='proof',label='操作证据',hook='看到实际界面',signals=['evidence'],evidence_ids=['e3'],priority=5),
                    dict(id='explain',label='解释原理',hook='一眼理解机制',signals=['explanation'],evidence_ids=['e2'],priority=4)]
            req['policy']=dict(target_count=2,min_angles=2,min_layout_families=2)
        req['analysis']=dict(synopsis='synthetic current-video content',evidence=ev,angles=angles)
        return req

    def save(self,obj,name='request'):
        self.counter+=1;p=self.root/f'{name}-{self.counter}.json';w.write(p,obj);return p

    def test_selects_three_content_driven_different_treatments(self):
        result=s.select(self.save(self.request()))
        self.assertEqual(result['status'],'ready_for_design')
        self.assertEqual({c['strategy_id'] for c in result['selected']},{'real-moment','story-sequence','type-metaphor'})
        self.assertEqual(len({c['angle_id'] for c in result['selected']}),3)
        self.assertTrue(all(c['evidence_ids'] and c['selection_reason'] for c in result['selected']))
        self.assertEqual(result['required_ratios'],['3:4','9:16','16:9','4:3'])
        self.assertFalse(result['rendered']);self.assertFalse(result['human_quality_approved'])

    def test_tutorial_selects_different_set_not_family_templates(self):
        result=s.select(self.save(self.request(tutorial=True)))
        self.assertEqual(result['status'],'ready_for_design')
        self.assertEqual({c['strategy_id'] for c in result['selected']},{'evidence-focus','type-metaphor'})

    def test_default_count_is_derived_and_can_exceed_three(self):
        self.brief['ai_authorization']=dict(allowed=True,user_quote='Synthetic permission only')
        req=self.request()
        self.assertNotIn('target_count',req['policy'])
        result=s.select(self.save(req))
        self.assertEqual(len(result['selected']),4)
        self.assertEqual(result['selection_scope']['mode'],'all_applicable')
        self.assertIn('ai-concept',{c['strategy_id'] for c in result['selected']})
        self.assertFalse(result['selection_scope']['count_is_user_limit'])

    def test_legacy_count_stays_explicit_and_replay_compatible(self):
        req=self.request();req['policy']=dict(target_count=2,min_angles=2,min_layout_families=2)
        result=s.select(self.save(req))
        self.assertEqual(len(result['selected']),2)
        self.assertNotIn('selection_scope',result)
        req['policy']['selection_mode']='all_applicable'
        with self.assertRaisesRegex(ValueError,'ambiguous_selection_policy'):s.select(self.save(req))

    def test_empty_applicable_set_does_not_invent_filler(self):
        req=self.request();req['analysis']['angles']=[dict(id='proof',label='No inputs',hook='Synthetic only',signals=['evidence'],evidence_ids=['e2'],priority=1)]
        result=s.select(self.save(req))
        self.assertEqual(result['selected'],[])
        self.assertNotEqual(result['status'],'ready_for_design')
        self.assertEqual(result['selection_scope']['selected_count'],0)

    def test_not_applicable_missing_and_duplicate_are_distinct(self):
        req=self.request();req['analysis']['angles'][0]['signals'].append('character')
        result=s.select(self.save(req));states={r['status'] for r in result['dispositions']}
        self.assertIn('not_applicable',states);self.assertIn('missing_inputs',states)
        self.assertTrue(any('ai_opt_in' in d.get('missing',[]) for d in result['dispositions']))
        self.assertFalse(any(c['route']=='cutout-poster' for c in result['selected']))

    def test_reviewed_evidence_and_valid_times_required(self):
        for mode in ['blank','reference','asr','time','signal']:
            req=self.request()
            if mode=='blank':req['analysis']['synopsis']=''
            if mode=='reference':req['analysis']['angles'][0]['evidence_ids']=['missing']
            if mode=='asr':req['analysis']['evidence'][2]['confidence']='asr_candidate'
            if mode=='time':req['analysis']['evidence'][0]['time_range_s']=[20,10]
            if mode=='signal':req['analysis']['angles'][0]['signals']=['invented']
            with self.subTest(mode=mode),self.assertRaises(ValueError):s.select(self.save(req))

    def test_sequence_needs_distinct_frames_and_relation(self):
        for mode in ['same_frame','no_relation','same_visual_role']:
            req=self.request()
            if mode=='same_frame':req['analysis']['evidence'][1]['asset_ids']=['a0']
            elif mode=='no_relation':del req['analysis']['angles'][1]['relation']
            else:
                req['analysis']['evidence'][1]['role']='demonstration'
                # Nonvisual context must not provide fake visual diversity.
                req['analysis']['angles'][1]['relation']['evidence_ids'].append('e2')
            result=s.select(self.save(req))
            self.assertEqual(result['status'],'ready_for_design')
            self.assertEqual(len(result['selected']),2)
            self.assertFalse(any(c['strategy_id']=='story-sequence' for c in result['selected']))

    def test_stale_source_or_tampered_selection_rejected(self):
        rp=self.save(self.request());result=s.select(rp);plan=self.save(result,'plan')
        s.verify(w.reference(plan),result['route_plan_ref'])
        tampered=copy.deepcopy(result);tampered['selected'].pop()
        with self.assertRaisesRegex(ValueError,'strategy_plan_drift'):s.verify(w.reference(self.save(tampered,'tampered')),result['route_plan_ref'])
        Path(self.source['path']).write_text('changed',encoding='utf8')
        with self.assertRaisesRegex(ValueError,'changed'):s.verify(w.reference(plan),result['route_plan_ref'])

    def test_titles_fonts_colors_do_not_make_new_photographic_composition(self):
        def vp(cid,x=0,width=1,sha='a'*64):
            return dict(candidate=dict(candidate_id=cid),assets=[dict(asset_id='p',artifact=dict(sha256=sha))],
                        render_spec=dict(profile_layouts={'vertical_profile_3_4':dict(media=[dict(asset_id='p',box=dict(x=x,y=0,width=width,height=1))],
                          photo_editorial=dict(text_nodes=[dict(text=cid,font_px=144,color='#FFFFFF')]))}))
        with self.assertRaisesRegex(ValueError,'lookalike_composition'):s.check_layout_diversity([vp('a'),vp('b',.01,.99)])
        s.check_layout_diversity([vp('a'),vp('b',.5,.5)])
        s.check_layout_diversity([vp('a'),vp('b',sha='b'*64)])

    def test_contract_binding_rejects_ratio_and_candidate_substitution(self):
        result=s.select(self.save(self.request()));ref=w.reference(self.save(result,'plan'))
        selected=result['selected']
        def specs():
            return dict(strategy_plan_ref=ref,route_plan_ref=result['route_plan_ref'],candidates=[dict(id=c['id'],route=c['route']) for c in selected])
        assets={a['id']:a for a in self.brief['assets']}
        plans={c['id']:dict(assets=[dict(asset_id=a,artifact=assets[a]['artifact']) for a in c['asset_ids']],profiles=[dict(profile_id=pid) for pid in ['vertical_profile_3_4','vertical_first_frame_9_16','bilibili_16_9','bilibili_4_3']],render_spec=dict(profile_layouts={})) for c in selected}
        # Bindings are checked separately from renderer-specific geometry validation.
        s.check_binding(specs(),self.brief,plans,check_layouts=False)
        bad=specs();bad['candidates'].pop()
        with self.assertRaisesRegex(ValueError,'selected_concept_set'):s.check_binding(bad,self.brief,plans,check_layouts=False)
        plans[selected[0]['id']]['profiles'].pop()
        with self.assertRaisesRegex(ValueError,'required_ratio'):s.check_binding(specs(),self.brief,plans,check_layouts=False)

    def test_profile_assets_and_recipe_cannot_disagree_with_selection(self):
        result=s.select(self.save(self.request()));ref=w.reference(self.save(result,'plan'))
        selected=result['selected'];assets={a['id']:a for a in self.assets}
        spec=dict(strategy_plan_ref=ref,route_plan_ref=result['route_plan_ref'],candidates=[dict(id=c['id'],route=c['route'],design_method=c['recipe']) for c in selected])
        pids=['vertical_profile_3_4','vertical_first_frame_9_16','bilibili_16_9','bilibili_4_3']
        plans={c['id']:dict(candidate=dict(candidate_id=c['id']),assets=[dict(asset_id=a,artifact=assets[a]['artifact']) for a in c['asset_ids']],
            profiles=[dict(profile_id=p) for p in pids],render_spec=dict(profile_layouts={p:dict(media=[dict(asset_id=a,box=dict(x=i*.5,y=0,width=.45,height=1)) for i,a in enumerate(c['asset_ids'])]) for p in pids})) for c in selected}
        s.check_binding(spec,self.brief,plans)
        photo=next(c for c in selected if c['strategy_id']=='real-moment')
        bad=copy.deepcopy(plans);bad[photo['id']]['assets'][0]['artifact']=self.assets[1]['artifact']
        with self.assertRaisesRegex(ValueError,'asset_identity'):s.check_binding(spec,self.brief,bad)
        bad=copy.deepcopy(plans);bad[photo['id']]['render_spec']['profile_layouts'][pids[0]]['media']=[]
        with self.assertRaisesRegex(ValueError,'missing_in_profile'):s.check_binding(spec,self.brief,bad)
        bad=copy.deepcopy(spec);bad['candidates'][0]['design_method']='different-recipe'
        with self.assertRaisesRegex(ValueError,'recipe_substitution'):s.check_binding(bad,self.brief,plans)

    def test_hybrid_selects_both_asset_kinds_not_two_photographs(self):
        decoration=self.root/'decoration.bin';decoration.write_bytes(b'fictional generated decoration')
        self.brief['assets'].append(dict(id='decoration',kind='generated_decoration',artifact=w.reference(decoration),generated=True,local_use_approved=True,privacy_reviewed=True))
        self.brief['ai_authorization']=dict(allowed=True,user_quote='Synthetic authorization fixture only')
        req=self.request();req['analysis']['evidence'][2]['asset_ids']=['a0','a1','decoration']
        req['policy']=dict(target_count=1,min_angles=1,min_layout_families=1)
        req['analysis']['angles']=[dict(id='hybrid',label='Mixed concept',hook='Synthetic mixed inputs',signals=['wordplay','metaphor'],evidence_ids=['e2'],priority=5)]
        result=s.select(self.save(req))
        proposals=result['selected']+result['dispositions']
        hybrid=next(c for c in proposals if c['strategy_id']=='hybrid-metaphor')
        self.assertNotEqual(hybrid.get('status'),'missing_inputs')

    def test_new_brief_requires_strategy_but_legacy_is_explicit(self):
        self.assertEqual(self.brief['workflow_version'],2)
        with self.assertRaisesRegex(ValueError,'strategy_plan_required'):s.check_binding({},self.brief,{})
        self.assertEqual(s.check_binding({},dict(workflow_version=1),{}),None)

    def desk(self):
        from PIL import Image
        result=s.select(self.save(self.request()));plan=self.save(result,'plan')
        data=w.desk.new_project(self.brief['project_id'],'Synthetic package')
        item=data['items'][0]
        item['cover_pk']=dict(strategy_plan_ref=w.reference(plan),required_ratios=result['required_ratios'],candidates=[],selected=None)
        ratios={'3:4':(480,640),'9:16':(480,854),'16:9':(854,480),'4:3':(640,480)}
        # Dimension choices must satisfy the same ratio tolerance as collection.
        ratios['9:16']=(540,960);ratios['16:9']=(960,540)
        for i,c in enumerate(result['selected']):
            byratio={}
            for j,(ratio,size) in enumerate(ratios.items()):
                path=self.root/f'cover-{i}-{j}.png';Image.new('RGB',size,(30+i*60,70+j*30,120)).save(path)
                aid=f'cover-{i}-{j}';item['covers'].append(dict(id=aid,**w.reference(path)));byratio[ratio]=aid
            item['cover_pk']['candidates'].append(dict(id=c['id'],cover_by_ratio=byratio))
        return data,result

    def passed_review(self,data):
        path=self.save(data,'desk');review=s.review_init(path)
        review['reviewer']='synthetic test assertions, not real visual approval'
        for row in review['images']:
            row.update(semantic_correct=True,mobile_readable=True,subject_safe=True,observation='fixture only')
        for row in review['pairs']:row.update(different=True,observation='fixture only')
        return review

    def test_output_matrix_and_review_must_cover_every_ratio(self):
        data,result=self.desk();review=self.passed_review(data)
        report=s.review_check(self.save(review,'review'))
        self.assertEqual(report['images'],12);self.assertEqual(report['distinctness_checks'],12)
        self.assertFalse(report['human_quality_approved']);self.assertFalse(report['publish_authorized'])
        for change in ['missing_image','missing_pair','unchecked','wrong_hash','blank_observation']:
            bad=copy.deepcopy(review)
            if change=='missing_image':bad['images'].pop()
            if change=='missing_pair':bad['pairs'].pop()
            if change=='unchecked':bad['images'][0]['mobile_readable']=None
            if change=='wrong_hash':bad['images'][0]['image_ref']['sha256']='0'*64
            if change=='blank_observation':bad['pairs'][0]['observation']=''
            with self.subTest(change=change),self.assertRaises(ValueError):s.review_check(self.save(bad,'bad'))
        del data['items'][0]['cover_pk']['candidates'][0]['cover_by_ratio']['16:9']
        with self.assertRaisesRegex(ValueError,'missing_ratio'):s.review_init(self.save(data,'partial'))

    def test_copied_png_and_changed_pixels_invalidate_review(self):
        data,result=self.desk();item=data['items'][0]
        item['cover_pk']['candidates'][1]['cover_by_ratio']['3:4']=item['cover_pk']['candidates'][0]['cover_by_ratio']['3:4']
        with self.assertRaisesRegex(ValueError,'duplicate_rendered_image'):s.review_init(self.save(data,'duplicate-image'))
        data,result=self.desk();review=self.passed_review(data);path=self.save(review,'review')
        Path(review['images'][0]['image_ref']['path']).write_bytes(b'not the reviewed PNG')
        with self.assertRaisesRegex(ValueError,'changed'):s.review_check(path)

    def test_partial_matrix_never_complete_and_invalid_pixels_rejected(self):
        data,selection=self.desk();item=data['items'][0];byid={a['id']:a for a in item['covers']}
        images={c['id']:{r:byid[aid] for r,aid in c['cover_by_ratio'].items()} for c in item['cover_pk']['candidates']}
        report=s.delivery(selection,images);self.assertTrue(report['rendered_matrix_complete']);self.assertFalse(report['complete'])
        del images[selection['selected'][0]['id']]['4:3']
        self.assertEqual(s.delivery(selection,images)['status'],'incomplete_ratios')
        a=next(iter(next(iter(images.values())).values()));Path(a['path']).write_bytes(b'not a PNG');a.update(w.reference(a['path']))
        with self.assertRaises((ValueError,OSError)):s.delivery(selection,images)

    def test_design_init_binds_selected_cards_and_blocks_unplanned_v2(self):
        request=self.request();route=w.bound(request['route_plan_ref'])
        with self.assertRaisesRegex(ValueError,'strategy_plan_required'):d.init(route)
        selection=s.select(self.save(request));plan=self.save(selection,'plan');master=d.init(route,plan)
        self.assertEqual({c['id'] for c in master['candidates']},{c['id'] for c in selection['selected']})
        self.assertEqual(master['strategy_plan_ref'],w.reference(plan))
        self.assertTrue(all(c['headline']=='' for c in master['candidates']))

    def test_agent_discovery_keeps_content_selection_in_default_flow(self):
        result=subprocess.run([sys.executable,'-B',str(w.ROOT/'scripts/self_media_agent.py'),'covers'],
                              cwd=w.ROOT,capture_output=True,text=True,encoding='utf8',check=True,timeout=10)
        entry=json.loads(result.stdout)
        for action in ['strategy-init','strategy-plan','review-init','review-check']:
            self.assertIn(action,entry['actions'])
        self.assertTrue((w.ROOT/entry['selection_guide']).is_file())
        self.assertEqual(entry['workflow_count'],5)
        self.assertFalse(entry['new_renderer']);self.assertFalse(entry['automatic_upload']);self.assertFalse(entry['automatic_publish'])


if __name__=='__main__':unittest.main()
