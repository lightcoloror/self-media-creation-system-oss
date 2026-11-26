import copy
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
import cover_workbench as w


class CoverWorkbenchTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.brief=w.init('test-project','Synthetic, not family media')
        self.brief.update(workflow_version=1,promise='Synthetic legacy workflow test',facts=['fixture only'])

    def file(self,name,data=b'fixture'):
        p=self.root/name;p.write_bytes(data);return w.reference(p)

    def test_no_ai_without_explicit_opt_in(self):
        rows={r['id']:r for r in w.plan(self.brief)['routes']}
        self.assertIn('ai_opt_in',rows['ai-illustration']['missing'])
        self.assertIn('photo',rows['photo-editorial']['missing'])
        self.assertEqual(rows['type-led']['status'],'ready_for_design_not_rendered')
        self.assertEqual(rows['cutout-poster']['missing'],['reviewed_cutout'])

    def test_hash_privacy_and_duplicate_asset_gates(self):
        a=dict(id='photo',kind='photo',artifact=self.file('photo.png'),local_use_approved=True,privacy_reviewed=True)
        self.brief['assets']=[a]
        self.assertFalse(next(r for r in w.plan(self.brief)['routes'] if r['id']=='photo-editorial')['missing'])
        a['privacy_reviewed']=False
        with self.assertRaisesRegex(ValueError,'unreviewed'):w.plan(self.brief)
        a['privacy_reviewed']=True;self.brief['assets'].append(copy.deepcopy(a))
        with self.assertRaisesRegex(ValueError,'duplicate'):w.plan(self.brief)
        self.brief['assets'].pop();Path(a['artifact']['path']).write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'changed'):w.plan(self.brief)

    def ai_spec(self):
        self.brief['ai_authorization']=dict(allowed=True,user_quote='测试夹具明确允许 AI 生图')
        rp=self.root/'routes.json';w.write(rp,w.plan(self.brief))
        # Header-only synthetic PNG; never claimed to be a rendered/decodable image.
        artifact=self.file('synthetic-header.png',b'\x89PNG\r\n\x1a\n'+b'\x00\x00\x00\rIHDR'+struct.pack('>II',1080,1440))
        c=dict(id='A',name='fixture',route='ai-illustration',hypothesis='fixture',composition='fixture',strength='fixture',risk='fixture',
               reference_uploads=[],prompt_ref=self.file('prompt.md'),outputs=[dict(ratio='3:4',artifact=artifact)])
        return dict(schema='self-media.cover-build.v1',project_id='test-project',route_plan_ref=w.reference(rp),candidates=[c])

    def test_generated_input_and_design_uniqueness(self):
        spec=self.ai_spec();w.validate_spec(spec)
        spec['candidates'][0]['reference_uploads']=['private-face.jpg']
        with self.assertRaisesRegex(ValueError,'reference_upload'):w.validate_spec(spec)
        spec['candidates'][0]['reference_uploads']=[]
        second=copy.deepcopy(spec['candidates'][0]);second['id']='B';spec['candidates'].append(second)
        with self.assertRaisesRegex(ValueError,'duplicate_design'):w.validate_spec(spec)

    def test_collection_missing_ratio_and_preserve_desk(self):
        spec=self.ai_spec();sp=self.root/'build.json';w.write(sp,spec)
        dp=self.root/'desk.json';data=w.desk.new_project('test-project','Fixture')
        data['items'][0]['platforms']['douyin']['fields']['body']='keep this human edit'
        w.write(dp,data);out=self.root/'review'
        r=w.collect(sp,[],dp,'main',out)
        self.assertEqual(r['images'],1);self.assertEqual(r['missing']['A'],['9:16','16:9','4:3'])
        saved=w.read(out/'publication-data.json')
        self.assertIsNone(saved['items'][0]['cover_pk']['selected'])
        self.assertEqual(saved['items'][0]['platforms']['douyin']['fields']['body'],'keep this human edit')
        self.assertIn('collection_name',saved['items'][0]['platforms']['douyin']['fields'])
        self.assertFalse(r['human_quality_approved']);self.assertFalse(r['ctr_validated'])
        with self.assertRaises(FileExistsError):w.collect(sp,[],dp,'main',out)

    def test_reference_route_binds_approved_non_person_references_through_collection(self):
        from PIL import Image
        source = self.root/'original.png'
        Image.new('RGB',(64,64),'white').save(source)
        ref = dict(id='object', kind='generation_reference', reference_role='object',
                   artifact=w.reference(source), local_use_approved=True, privacy_reviewed=True,
                   generation_use_approved=False)
        self.brief['assets'] = [ref]
        row = next(r for r in w.plan(self.brief)['routes'] if r['id']=='ai-reference')
        self.assertEqual(row['missing'], ['ai_opt_in', 'approved_generation_reference'])
        ref['generation_use_approved'] = True
        spec = self.ai_spec()
        card = spec['candidates'][0]
        card.update(route='ai-reference', generation_reference_ids=['unknown'])
        with self.assertRaisesRegex(ValueError, 'unapproved_or_missing'):
            w.validate_spec(spec)
        card['generation_reference_ids'] = ['object']
        w.validate_spec(spec)
        sp=self.root/'native-reference.json';w.write(sp,spec)
        dp=self.root/'reference-desk.json';w.write(dp,w.desk.new_project('test-project','Fixture'))
        out=self.root/'reference-review'
        receipt = w.collect(sp,[],dp,'main',out)
        self.assertEqual(receipt['routes'], ['ai-reference'])
        saved=w.read(out/'publication-data.json')['items'][0]
        references=[dict(id='object', role='object', artifact=ref['artifact'])]
        self.assertEqual(receipt['generation_references']['A'], references)
        self.assertEqual(saved['covers'][0]['production_evidence']['generation_references'], references)
        self.assertEqual(saved['cover_pk']['candidates'][0]['generation_references'], references)
        self.assertIsNone(saved['cover_pk']['selected'])

    def test_identity_requires_consent_and_source_is_an_image(self):
        from PIL import Image
        source = self.root/'identity.png'
        Image.new('RGB',(64,64),'white').save(source)
        ref = dict(id='test-identity',kind='generation_reference',reference_role='identity',artifact=w.reference(source),
                   local_use_approved=True,privacy_reviewed=True,generation_use_approved=True)
        self.brief['assets'] = [ref]
        with self.assertRaisesRegex(ValueError,'identity_reference_subject_scope_required'):
            w.plan(self.brief)
        ref.update(subject_scope='authorized_other',consent_quote='仅合成测试',use_boundary='合成测试，不涉及实际人物')
        w.plan(self.brief)
        ref['artifact'] = self.file('not-a-picture.txt')
        with self.assertRaisesRegex(ValueError,'invalid_generation_reference_image'):
            w.plan(self.brief)

    def test_ratio_mismatch_and_missing_output_rejected(self):
        spec=self.ai_spec();spec['candidates'][0]['outputs'][0]['ratio']='16:9'
        sp=self.root/'s.json';w.write(sp,spec)
        dp=self.root/'d.json';w.write(dp,w.desk.new_project('test-project','Fixture'))
        with self.assertRaisesRegex(ValueError,'ratio_or_resolution'):w.collect(sp,[],dp,'main',self.root/'bad')
        spec['candidates'][0]['outputs']=[]
        with self.assertRaisesRegex(ValueError,'not_completed'):w.validate_spec(spec)

    def test_png_header_and_init_do_not_render(self):
        with self.assertRaises(ValueError):w.png_size(self.file('not-image')['path'])
        self.assertFalse(w.doctor(w.DEFAULT_PIPE)['runtime_verified'])
        with self.assertRaises(ValueError):w.init('../escape','bad')
        with self.assertRaises(ValueError):w.plan(w.init('blank','blank'))


if __name__=='__main__':unittest.main()
