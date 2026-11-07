import copy
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import cover_design as d
import cover_workbench as w
if not (Path(w.DEFAULT_PIPE) / 'src/video_creation_pipeline/cover_layers.py').is_file():
    raise unittest.SkipTest('Full MVP cover renderer owner is not public; integration remains unverified')
w.pipeline_import(w.DEFAULT_PIPE)
from video_creation_pipeline.contract_io import artifact_reference
from video_creation_pipeline.cover_layers import validate_cover_layers
from video_creation_pipeline.case_cover_visual_plan import PROFILE_DIMENSIONS
from video_creation_pipeline.typography_gates import build_typography_gate
from video_creation_pipeline.errors import ContractError
from PIL import Image


def card(recipe, ids):
    return dict(id=recipe,recipe=recipe,name='合成测试 '+recipe,title='独立项目测试标题',headline='设计测试',
                hypothesis='fixture',composition=recipe,strength='fixture',risk='not human reviewed',
                asset_ids=ids,labels=['样本'+str(i+1) for i in range(len(ids))],relation_basis='synthetic order, no real claims')


def layer_fixture(recipe='photo-caption',profile='vertical_profile_3_4'):
    r=next(r for r in d.recipes()['recipes'] if r['id']==recipe)
    assets=[dict(id='a'+str(i),kind=r['kinds'][0],subject_reviewed=True,protected_regions=[d.box(.2,.2,.5,.5)]) for i in range(r['max_assets'])]
    width,height=PROFILE_DIMENSIONS[profile]
    p=dict(profile_id=profile,width=width,height=height,safe_zone=d.box(.04,.04,.92,.92))
    gate=build_typography_gate(profile,width=width,height=height)
    layout=d.default_layout(r,card(recipe,[a['id'] for a in assets]),assets,p,dict(background='#F7F3EA',foreground='#243238',accent='#C85A35'),gate)
    return dict(visual_route={},assets=[dict(asset_id=a['id'],generated=False,use_approved=True,privacy_reviewed=True,dimensions=[800,600]) for a in assets],profiles=[p],render_spec=dict(profile_layouts={profile:layout}))


class CoverDesignTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)

    def project(self, recipe='type-symbol', name='independent-project'):
        r=next(r for r in d.recipes()['recipes'] if r['id']==recipe)
        brief=w.init(name,'新项目');brief.update(workflow_version=1,promise='synthetic legacy renderer fixture',facts=['synthetic'],routes=[r['route']])
        for i in range(r['max_assets']):
            path=self.root/f'image-{i}.png'
            im=Image.new('RGBA',(800,600),(30+i*50,110,140,255))
            if r['kinds']==['reviewed_cutout']:im.putpixel((0,0),(0,0,0,0))
            im.save(path)
            brief['assets'].append(dict(id='a'+str(i),kind=r['kinds'][0],artifact=artifact_reference(path,'synthetic'),
                local_use_approved=True,privacy_reviewed=True,generated=False,subject_reviewed=True,
                protected_regions=[d.box(.2,.2,.5,.5)],cutout_reviewed=True,verified_focus='synthetic'))
        w.write(self.root/'route.json',w.plan(brief))
        master=d.init(self.root/'route.json');master['account']='独立测试账号'
        master['color_selection']=dict(mode='content',account=master['account'],
            palette=dict(background='#FFF8EF',foreground='#382B25',accent='#87511D'),
            content_basis=['synthetic shapes'],rationale='Explicit synthetic fixture colors, not a production default.')
        w.write(self.root/'pack.json',{'synthetic':True});master['packaging_ref']=w.reference(self.root/'pack.json')
        if brief['assets']:
            w.write(self.root/'safe.json',dict(placements=[dict(asset_id=a['id'],source_asset=a['artifact']) for a in brief['assets']]))
            master['safe_layout_ref']=w.reference(self.root/'safe.json')
        master['candidates']=[card(recipe,[a['id'] for a in brief['assets']])]
        return master

    def save_build(self, master, name='result'):
        path=self.root/(name+'.json');w.write(path,master)
        return d.build(path,self.root/name)

    def test_seven_recipes_five_profiles(self):
        for r in d.recipes()['recipes']:
            for profile in PROFILE_DIMENSIONS:
                with self.subTest(recipe=r['id'],profile=profile):validate_cover_layers(layer_fixture(r['id'],profile))

    def test_real_type_only_contract_all_four_ratios_and_roundtrip(self):
        master=self.project();receipt=self.save_build(master)
        self.assertFalse(receipt['rendered']);self.assertEqual(receipt['profiles'],4)
        spec=w.read(self.root/'result/build.json');w.validate_spec(spec)
        vp=w.read(w.bound(spec['candidates'][0]['visual_plan_ref']))
        self.assertEqual(vp['brand']['account'],'独立测试账号')
        expanded=w.read(self.root/'result/editable-master.json')
        self.assertEqual(len(expanded['candidates'][0]['profile_layouts']),4)
        self.save_build(expanded,'roundtrip')
        with self.assertRaises(FileExistsError):d.build(self.root/'result.json',self.root/'result')

    def test_all_media_design_compilers_with_isolated_safe_contract(self):
        # Safe-plan geometry engine is tested upstream; this isolates design->plan
        # binding. The browser smoke uses unmocked safe-plan generation separately.
        for r in d.recipes()['recipes']:
            if not r['min_assets']:continue
            with self.subTest(recipe=r['id']), tempfile.TemporaryDirectory() as td:
                self.root=Path(td);master=self.project(r['id'])
                with patch('video_creation_pipeline.case_cover_visual_plan.validate_safe_media_layout_plan'):
                    self.save_build(master)
                self.assertFalse(w.read(self.root/'result/design-build-receipt.json')['generative_model_used'])

    def test_missing_approval_and_generated_inputs(self):
        for field,value in [('generated',True),('subject_reviewed',False)]:
            with tempfile.TemporaryDirectory() as td:
                self.root=Path(td);m=self.project('photo-caption')
                rp=w.read(self.root/'route.json');rp['brief']['assets'][0][field]=value
                path=self.root/'bad-route.json';w.write(path,rp);m['route_plan_ref']=w.reference(path)
                with self.assertRaises(ValueError):self.save_build(m)

    def test_wrong_project_empty_account_and_unknown_recipe(self):
        for field,value in [('project_id','other'),('account','')]:
            with tempfile.TemporaryDirectory() as td:
                self.root=Path(td);m=self.project();m[field]=value
                with self.assertRaises(ValueError):self.save_build(m)
        with tempfile.TemporaryDirectory() as td:
            self.root=Path(td);m=self.project();m['candidates'][0]['recipe']='unknown'
            with self.assertRaises(ValueError):self.save_build(m)

    def test_layer_safety_and_no_remote_code(self):
        for case in ('font','url','type','overlap','nan','text-overflow','unreviewed','duplicate','hidden'):
            p=layer_fixture();layers=p['render_spec']['profile_layouts']['vertical_profile_3_4']['cover_layers']['layers']
            headline=layers[-1]
            if case=='font':headline['font_px']=20
            if case=='url':headline['color']='url(https://invalid)'
            if case=='type':headline['type']='script'
            if case=='overlap':headline['box']=d.box(.2,.5,.5,.2)
            if case=='nan':headline['font_px']=float('nan')
            if case=='text-overflow':headline['text']='很长的文字'*50
            if case=='unreviewed':layers[0]['subject_reviewed']=False
            if case=='duplicate':headline['id']=layers[0]['id']
            if case=='hidden':layers.append(dict(id='cover-text',type='rect',box=headline['box'],color='#FFFFFF'))
            with self.subTest(case=case),self.assertRaises(ContractError):validate_cover_layers(p)

    def test_long_title_does_not_shrink(self):
        m=self.project();m['candidates'][0]['headline']='过长的标题不能自动缩小'*20
        with self.assertRaisesRegex(ValueError,'does_not_fit'):self.save_build(m)

    def test_authorized_hybrid_layers_keep_truth_and_subject_gates(self):
        def fixture():
            p=layer_fixture('type-symbol');pid='vertical_profile_3_4'
            real=dict(asset_id='real',generated=False,use_approved=True,privacy_reviewed=True,dimensions=[800,600])
            decor=dict(asset_id='decor',generated=True,use_approved=True,privacy_reviewed=True,dimensions=[800,600],role='decoration',source_kind='generated_editorial_visual')
            p['assets']=[real,decor]
            p['image_generation']=dict(authorization_status='explicit-user-authorized',request_text='AI生图 synthetic fixture only')
            boxes=[d.box(.05,.3,.4,.4),d.box(.6,.3,.3,.3)]
            layers=[dict(id=a['asset_id'],type='image',asset_id=a['asset_id'],box=b,subject_reviewed=True,protected_regions=[d.box(.2,.2,.5,.5)] if i==0 else []) for i,(a,b) in enumerate(zip(p['assets'],boxes))]
            layers += [dict(id='headline',type='text',text='测试',box=d.box(.08,.08,.80,.13),font_px=144,color='#243238',role='overlay'),dict(id='disclosure',type='text',text='AI 概念装饰',box=d.box(.08,.9,.80,.05),font_px=30,color='#243238',role='ai_disclosure')]
            p['render_spec']['profile_layouts'][pid]=dict(media=[dict(asset_id=a['asset_id'],box=b) for a,b in zip(p['assets'],boxes)],cover_layers=dict(schema='local.cover_layers.v1',background='#FFFFFF',generative_model_used=True,layers=layers))
            return p
        validate_cover_layers(fixture())
        for mode in ['auth','declaration','role','disclosure','face']:
            p=fixture();scene=p['render_spec']['profile_layouts']['vertical_profile_3_4']['cover_layers']
            if mode=='auth':p['image_generation']={}
            if mode=='declaration':scene['generative_model_used']=False
            if mode=='role':p['assets'][1]['role']='trust'
            if mode=='disclosure':scene['layers'].pop()
            if mode=='face':scene['layers'][-2]['box']=d.box(.1,.4,.8,.2)
            with self.subTest(mode=mode),self.assertRaises(ContractError):validate_cover_layers(p)

    def test_two_projects_do_not_inherit_brand_or_text(self):
        for pid,account,title in [('travel-demo','旅行测试','行程测试'),('tutorial-demo','教程测试','方法测试')]:
            with tempfile.TemporaryDirectory() as td:
                self.root=Path(td);m=self.project(name=pid);m['account']=account;m['color_selection']['account']=account;m['candidates'][0]['headline']=title
                self.save_build(m)
                spec=w.read(self.root/'result/build.json');self.assertEqual(spec['project_id'],pid)
                vp=w.read(w.bound(spec['candidates'][0]['visual_plan_ref']))
                self.assertEqual(vp['brand']['account'],account);self.assertEqual(vp['candidate']['overlay_text'],title)

    def test_editable_master_cannot_erase_subject_regions(self):
        m=self.project('photo-caption')
        with patch('video_creation_pipeline.case_cover_visual_plan.validate_safe_media_layout_plan'):
            self.save_build(m)
        expanded=w.read(self.root/'result/editable-master.json')
        expanded['candidates'][0]['profile_layouts']['vertical_profile_3_4']['cover_layers']['layers'][0]['protected_regions']=[]
        with self.assertRaisesRegex(ValueError,'protected_regions_drift'):self.save_build(expanded,'bad-override')

    def test_new_master_has_no_universal_palette(self):
        self.project()
        master=d.init(self.root/'route.json')
        self.assertNotIn('palette',master)
        self.assertEqual(master['color_selection']['palette'],{})
        self.assertEqual(master['color_selection']['mode'],'content')

    def test_explicit_content_palette_and_legacy_roundtrip(self):
        master=self.project()
        palette=master.pop('color_selection')['palette'];master['palette']=palette
        self.save_build(master)
        self.assertNotIn('color_selection',w.read(self.root/'result/build.json')['candidates'][0])
        self.save_build(w.read(self.root/'result/editable-master.json'),'legacy-replay')

    def test_each_candidate_can_choose_its_own_palette(self):
        master=self.project();second=copy.deepcopy(master['candidates'][0])
        second.update(id='second',headline='另一个方案',composition='different explicit fixture')
        second['color_selection']=dict(mode='content',account=master['account'],
            palette=dict(background='#F8F5FF',foreground='#352944',accent='#752A56'),
            content_basis=['second synthetic concept'],rationale='A distinct, explicitly chosen test palette.')
        master['candidates'].append(second);self.save_build(master)
        records=w.read(self.root/'result/build.json')['candidates']
        self.assertNotEqual(records[0]['color_selection']['palette'],records[1]['color_selection']['palette'])
        for row in records:
            plan=w.read(w.bound(row['visual_plan_ref']))
            d.cover_colors.validate_plan(plan,row['color_selection'])

    def test_color_rationale_and_account_cannot_be_implicit(self):
        for key,value,error in [('rationale','','rationale_required'),('content_basis',[],'content_basis_required'),
                ('account','别的账号','account_mismatch'),('palette',{},'palette_required')]:
            with self.subTest(key=key),tempfile.TemporaryDirectory() as td:
                self.root=Path(td);m=self.project();m['color_selection'][key]=value
                with self.assertRaisesRegex(ValueError,error):self.save_build(m)

    def test_brand_palette_is_opt_in_scoped_and_bound(self):
        m=self.project();m['color_selection']['mode']='brand'
        with self.assertRaisesRegex(ValueError,'brand_color_scope'):self.save_build(m)
        w.write(self.root/'brand.json',{'account':m['account'],'synthetic':True})
        m['color_selection'].update(brand_applies_to_content=True,brand_ref=w.reference(self.root/'brand.json'))
        self.save_build(m,'scoped-brand')

    def test_changing_color_metadata_alone_cannot_reuse_old_layers(self):
        m=self.project();self.save_build(m)
        expanded=w.read(self.root/'result/editable-master.json')
        expanded['color_selection']['palette']['foreground']='#133355'
        with self.assertRaisesRegex(ValueError,'color_selection_layer_drift'):self.save_build(expanded,'bad-colors')

    def test_direct_build_rechecks_color_binding(self):
        m=self.project();self.save_build(m)
        spec=w.read(self.root/'result/build.json');spec['candidates'][0]['color_selection']['rationale']='changed only card'
        with self.assertRaisesRegex(ValueError,'color_selection_plan_drift'):w.validate_spec(spec)

    def test_comparison_basis_and_fake_transparency(self):
        m=self.project('comparison');m['candidates'][0]['relation_basis']=''
        with self.assertRaisesRegex(ValueError,'relation_basis'):self.save_build(m)
        with tempfile.TemporaryDirectory() as td:
            self.root=Path(td);m=self.project('cutout-type')
            Image.new('RGB',(800,600),'white').save(self.root/'opaque.png')
            rp=w.read(self.root/'route.json');rp['brief']['assets'][0]['artifact']=artifact_reference(self.root/'opaque.png','opaque')
            w.write(self.root/'bad-route.json',rp);m['route_plan_ref']=w.reference(self.root/'bad-route.json')
            with self.assertRaisesRegex(ValueError,'transparent'):self.save_build(m)


if __name__=='__main__':unittest.main()
