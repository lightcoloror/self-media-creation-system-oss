import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
import cover_methods as m
import cover_workbench as w


class CoverMethodsTests(unittest.TestCase):
    def routes(self):
        return [dict(id=r['id'], selected=True, missing=list(r['needs'])) for r in w.catalog()['routes']]

    def library(self):
        # Synthetic availability; independent of developer-machine skills.
        data=m.read(m.ROOT/'config/cover-methods.v1.json')
        for e in data['entries']:
            e.update(source_ref={'path':'synthetic/SKILL.md','sha256':'fixture'} if e['path'] else None,
                     source_status='fixture' if e['path'] else 'missing_or_unresolved')
        return data

    def test_family_vs_tutorial(self):
        def ids(kind):
            p=m.select({'content_kind':kind},self.routes(),self.library())
            return {x['id'] for r in p['routes'] for x in r['methods']}
        self.assertIn('charlie-thumbnail',ids('family'))
        self.assertIn('personal-editorial-illustrations',ids('family'))
        self.assertNotIn('atutun-xhs-cover',ids('family'))
        self.assertIn('atutun-xhs-cover',ids('tutorial'))
        self.assertNotIn('lucas-case-cover-craft',ids('family'))

    def test_unknown_duplicates_and_bad_kind_fail(self):
        for brief in ({'method_ids':['invented']}, {'method_ids':['gbro-cover-design']*2},
                      {'method_ids':'gbro-cover-design'}, {'content_kind':'typo'}):
            with self.assertRaises(ValueError):m.select(brief,self.routes(),self.library())

    def test_missing_source_and_outside_scope_not_promoted(self):
        p=m.select({'content_kind':'family','method_ids':['claude-youtube-thumbnail','atutun-xhs-cover']}, self.routes(),self.library())
        rows={e['id']:e for e in p['routes'][0]['methods']}
        self.assertEqual(rows['claude-youtube-thumbnail']['status'],'blocked_missing_source')
        self.assertTrue(rows['atutun-xhs-cover']['scope_warning'])
        self.assertFalse(p['rendered']); self.assertFalse(p['design_completed'])

    def test_non_ai_route_not_replaced_and_unselected_omitted(self):
        routes=self.routes()
        for r in routes:r['selected']=r['id']=='photo-editorial'
        p=m.select({'content_kind':'family'},routes,self.library())
        self.assertEqual([x['route'] for x in p['routes']],['photo-editorial'])
        self.assertNotIn('baoyu-cover-image',{e['id'] for e in p['routes'][0]['methods']})
        self.assertIn('photo',p['routes'][0]['route_missing_inputs'])

    def test_inventory_fingerprints_and_missing_files(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); (root/'one.md').write_text('fixture',encoding='utf-8')
            config=root/'catalog.json'
            config.write_text(json.dumps({'entries':[{'id':'one','root':'test','path':'one.md'},
                                                       {'id':'two','root':'test','path':'absent.md'}]}),encoding='utf-8')
            data=m.inventory(config,{'test':root})
            self.assertEqual(data['counts'],{'registered':2,'located':1})
            old=data['entries'][0]['source_ref']['sha256']
            (root/'one.md').write_text('changed',encoding='utf-8')
            self.assertNotEqual(old,m.inventory(config,{'test':root})['entries'][0]['source_ref']['sha256'])
            self.assertIsNone(data['entries'][1]['source_ref'])

    def test_managed_release_reads_workspace_method_sources(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            runtime = root / 'local-tools-runtime'
            release = runtime / 'self-media-releases' / '2026.11.23-001' / 'self-media-creation-system'
            source = runtime / 'self-media-source' / 'self-media-creation-system'
            method = root / 'source-reviews' / 'cover-method' / 'SKILL.md'
            method.parent.mkdir(parents=True)
            method.write_text('fixture', encoding='utf-8')
            config = root / 'catalog.json'
            config.write_text(json.dumps({'entries': [{'id': 'cover-method', 'root': 'workspace',
                                                        'path': method.relative_to(root).as_posix()}]}),
                              encoding='utf-8')
            for repo in (release, source, root / 'self-media-creation-system'):
                with self.subTest(repo=repo), patch.object(m, 'ROOT', repo):
                    data = m.inventory(config)
                    self.assertEqual(data['counts'], {'registered': 1, 'located': 1})
                    self.assertEqual(data['entries'][0]['source_ref']['path'], str(method.resolve()))

    def test_style_search_uses_real_structure_no_generation(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'style.json'
            p.write_text(json.dumps({'templates':[{'id':'fixture','title':{'zh':'测试绘本'},'exampleCases':[7]}],
                                     'styles':['test'],'categories':[],'scenes':[]}),encoding='utf-8')
            library={'entries':[{'id':'gpt-image-2-style-library','data_ref':m.ref(p)}]}
            result=m.styles('绘本',library=library)
            self.assertEqual(result['matches'][0]['exampleCases'],[7])
            self.assertFalse(result['generated'])
            self.assertEqual(m.styles('not-found',library=library)['matches'],[])
            with self.assertRaisesRegex(ValueError,'unknown_style'):m.styles(template_id='absent',library=library)
            library['entries'][0]['data_ref']=None
            with self.assertRaisesRegex(ValueError,'missing'):m.styles(library=library)

    def test_legacy_brief_and_ai_gate(self):
        brief=w.init('fixture','fixture');brief.update(promise='fixture',facts=['synthetic'])
        brief.pop('content_kind');brief.pop('method_ids')
        result=w.plan(brief)
        self.assertEqual(result['method_plan']['content_kind'],'generic')
        self.assertIn('ai_opt_in',next(r for r in result['routes'] if r['id']=='ai-illustration')['missing'])

    def test_multi_source_style_search_keeps_provenance(self):
        with tempfile.TemporaryDirectory() as td:
            workspace = Path(td)
            repo = workspace / 'self-media-creation-system'
            (repo / 'config').mkdir(parents=True)
            source = workspace / 'playbook.md'
            source.write_text('fixture', encoding='utf-8')
            cards = [{'id': 'fixture-vertical', 'title': {'zh': '竖版叠压'}, 'source_path': source.name, 'source_line': 1}]
            (repo / 'config/cover-style-references.v1.json').write_text(
                json.dumps({'sources': {'fixture-cover': cards}}), encoding='utf-8')
            library = {'entries': [{'id': 'fixture-cover', 'source_ref': m.ref(source)}]}
            with patch.object(m, 'ROOT', repo):
                result = m.styles('叠压', library=library, source='fixture-cover')
                self.assertEqual(result['matches'][0]['source_ref'], m.ref(source))
                self.assertEqual(result['matches'][0]['source_id'], 'fixture-cover')
                self.assertEqual(m.styles(template_id='fixture-vertical', library=library)['matches'], result['matches'])
                with self.assertRaisesRegex(ValueError, 'unknown_style_source'):
                    m.styles(library=library, source='unknown')


if __name__=='__main__':unittest.main()
