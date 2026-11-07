"""CTA orchestration regression, synthetic files only; no posting or semantic AI."""
import contextlib
import copy
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import cta_review as cta
import publication_desk as desk
import video_delivery as video
import cover_workbench as files
import prerecording_validation as prerecord


class CtaReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.script=self.root/'script.md';self.script.write_text('A story. What mattered to you?',encoding='utf8')
        self.media=self.root/'synthetic.mp4';self.media.write_bytes(b'synthetic metadata fixture only, not encoded video')
        self.plan=cta.empty_plan('p',files.reference(self.script))
        for row in self.plan['decisions'].values():row.update(decision='not_used',reason='This synthetic story ends at its own payoff; no additional action needed.')
        self.data=desk.new_project('p','Synthetic',['douyin'])
        self.item=self.data['items'][0];self.item['video']=files.reference(self.media)
        self.item['platforms']['douyin']['fields'].update(body='A story. What mattered to you?',pinned_comment='')
        self.manifest={'project_id':'p','script_ref':files.reference(self.script),'timeline':{'duration_seconds':3}}
        self.serial=0
        self.bind()

    def bind(self):
        self.serial+=1;p=self.root/f'plan-{self.serial}.json';p.write_text(json.dumps(self.plan),encoding='utf8')
        self.item['cta_plan_ref']=files.reference(p);self.manifest['cta_plan_ref']=files.reference(p)
        return p

    def use(self,location='publication_body',kind='interaction'):
        row=dict(id='question',location=location,text='What mattered to you?',reason='Ask after the story payoff without interrupting it.')
        if location in cta.COPY_LOCATIONS:row['platform']='douyin'
        else:row.update(start_seconds=2,end_seconds=2.8)
        self.plan['decisions'][kind].update(decision='use',reason='Invite a relevant response.',placements=[row])
        self.bind();return row

    def acceptance(self):
        return {'cta_landing':dict(plan_sha256=self.manifest['cta_plan_ref']['sha256'],
            video_sha256=self.item['video']['sha256'],unplanned_cta_absent=True,prepared_copy_reviewed=True,
            notes='Synthetic contract observation of final cut and prepared fields; not real editorial approval.',observations=[])}

    def test_none_is_valid_but_missing_decision_is_not(self):
        self.assertTrue(desk.check_cta(self.data)['complete'])
        self.assertTrue(cta.check_delivery(self.manifest,self.data,self.acceptance())['complete'])
        for edit in ('missing','undecided','no_reason','contradiction'):
            with self.subTest(edit=edit):
                p=copy.deepcopy(self.plan)
                if edit=='missing':p['decisions'].pop('interaction')
                elif edit=='undecided':p['decisions']['interaction']['decision']='undecided'
                elif edit=='no_reason':p['decisions']['interaction']['reason']=' '
                else:p['decisions']['interaction']['placements']=[{}]
                with self.assertRaises(ValueError):cta.check_plan(p)

    def test_interaction_in_description_does_not_require_video_cta(self):
        self.use()
        self.assertTrue(desk.check_cta(self.data)['complete'])
        result=cta.check_delivery(self.manifest,self.data,self.acceptance())
        self.assertEqual(result['video_placements'],0)
        self.item['platforms']['douyin']['fields']['body']='Question removed.'
        self.assertFalse(desk.check_cta(self.data)['complete'])

    def test_comment_is_only_prepared_not_posted_and_location_matters(self):
        self.use('pinned_comment')
        self.assertFalse(desk.check_cta(self.data)['complete'])
        self.item['platforms']['douyin']['fields']['pinned_comment']='What mattered to you?'
        report=cta.check_item(self.item,'p')
        self.assertIn('comments_not_posted',report['scope'])
        self.plan['decisions']['interaction']['placements'][0]['platform']='bilibili';self.bind()
        self.assertFalse(desk.check_cta(self.data)['complete'])

    def test_acquisition_needs_its_own_service_boundary(self):
        self.use(kind='acquisition')
        self.assertFalse(desk.check_cta(self.data)['complete'])
        self.plan['decisions']['acquisition']['service_boundary']='Only explain documented options; no outcome promise.';self.bind()
        self.assertTrue(desk.check_cta(self.data)['complete'])
        self.plan['decisions'].pop('interaction');self.bind()
        self.assertFalse(desk.check_cta(self.data)['complete'])

    def test_script_and_plan_drift_block_old_decisions(self):
        p=self.bind();p.write_text(p.read_text()+' ',encoding='utf8')
        self.assertFalse(desk.check_cta(self.data)['complete'])
        self.bind();self.script.write_text('changed script',encoding='utf8')
        self.assertFalse(desk.check_cta(self.data)['complete'])

    def test_spoken_script_and_position_required(self):
        self.use('video_spoken');self.assertTrue(desk.check_cta(self.data)['complete'])
        row=self.plan['decisions']['interaction']['placements'][0]
        row['text']='Unrecorded invented speech';self.bind()
        self.assertFalse(desk.check_cta(self.data)['complete'])
        row['location']='video_overlay';row['start_seconds']=float('nan');self.bind()
        self.assertFalse(desk.check_cta(self.data)['complete'])

    def test_video_landing_requires_observed_text_time_and_artifact(self):
        row=self.use('video_overlay');receipt=self.acceptance()
        with self.assertRaisesRegex(ValueError,'coverage_mismatch'):cta.check_delivery(self.manifest,self.data,receipt)
        evidence=self.root/'frame-observation.txt';evidence.write_text('Synthetic frame evidence only',encoding='utf8')
        observed={k:v for k,v in row.items() if k!='reason'}
        observed.update(evidence_ref=files.reference(evidence),evidence_note='Synthetic overlay seen in the specified final-cut window.')
        receipt['cta_landing']['observations']=[observed]
        self.assertTrue(cta.check_delivery(self.manifest,self.data,receipt)['complete'])
        for field,value in [('text','Wrong phrase'),('location','video_spoken'),('start_seconds',1),('end_seconds',3.5)]:
            bad=copy.deepcopy(receipt);bad['cta_landing']['observations'][0][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):cta.check_delivery(self.manifest,self.data,bad)
        evidence.write_text('changed',encoding='utf8')
        with self.assertRaises(ValueError):cta.check_delivery(self.manifest,self.data,receipt)

    def test_no_cta_still_requires_observed_absence_not_plan_only(self):
        for patch in ({'unplanned_cta_absent':False},{'prepared_copy_reviewed':False},{'notes':''},{'plan_sha256':'0'*64},{'video_sha256':'0'*64}):
            receipt=self.acceptance();receipt['cta_landing'].update(patch)
            with self.subTest(patch=patch),self.assertRaises(ValueError):cta.check_delivery(self.manifest,self.data,receipt)
        with self.assertRaisesRegex(ValueError,'landing_review_required'):cta.check_delivery(self.manifest,self.data,{})

    def test_desk_plan_and_final_video_cannot_be_swapped(self):
        receipt=self.acceptance();self.manifest['cta_plan_ref']={'path':'other','sha256':'0'*64}
        with self.assertRaisesRegex(ValueError,'plan_mismatch'):cta.check_delivery(self.manifest,self.data,receipt)
        self.manifest['cta_plan_ref']=self.item['cta_plan_ref'];self.media.write_bytes(b'new file')
        with self.assertRaises(ValueError):cta.check_delivery(self.manifest,self.data,receipt)

    def test_prerecord_consumer_uses_same_current_script(self):
        with self.assertRaisesRegex(ValueError,'cta_plan_required'):prerecord.validate_cta_input({'case-video-script':self.script})
        path=self.bind();inputs={'case-video-script':self.script,'cta-plan':path}
        prerecord.validate_cta_input(inputs)
        other=self.root/'other.md';other.write_text('other',encoding='utf8');inputs['case-video-script']=other
        with self.assertRaisesRegex(ValueError,'script_revision_mismatch'):prerecord.validate_cta_input(inputs)

    def test_cli_init_bind_and_draft_display_do_not_auto_approve(self):
        initial=self.root/'initial.json';manifest=self.root/'manifest.json';output=self.root/'bound.json'
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(video.main(['cta-init','--project-id','p','--script',str(self.script),'--output',str(initial)]),0)
            self.assertEqual(video.main(['cta-init','--project-id','p','--script',str(self.script),'--output',str(initial)]),2)
            pending=json.loads(initial.read_text());self.assertEqual(pending['decisions']['interaction']['decision'],'undecided')
            manifest.write_text(json.dumps(dict(video.init('p'),acceptance_ref={'old':'review'})),encoding='utf8')
            self.assertEqual(video.main(['cta-bind','--input',str(manifest),'--plan',str(initial),'--output',str(output)]),2)
            self.assertEqual(video.main(['cta-bind','--input',str(manifest),'--plan',str(self.bind()),'--output',str(output)]),0)
        self.assertIsNone(json.loads(output.read_text())['acceptance_ref'])
        self.assertIn('CTA',desk.render(self.data))
        self.item.pop('cta_plan_ref');self.assertFalse(desk.check_cta(self.data)['complete'])
        self.assertIn('CTA选择/位置复核待完成',desk.render(self.data))


if __name__=='__main__':unittest.main()
