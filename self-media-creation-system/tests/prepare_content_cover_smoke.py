"""Unmocked content-selection -> four-ratio design smoke, entirely synthetic.

Reuses the existing safe-layout and renderer fixture. No real video understanding
or quality claims are made from colored primitive test media.
"""
import argparse
from pathlib import Path
import prepare_cover_design_smoke as seed
import cover_workbench as w
import cover_strategy as s
import cover_design as d


def prepare(out,engine,pipe):
    out=Path(out).resolve();out.mkdir(parents=True,exist_ok=False)
    seed.prepare(out/'seed',engine,pipe)
    brief=w.read(out/'seed/brief.json')
    brief.update(workflow_version=2,project_id='content-cover-smoke',requested_ratios=['3:4','9:16','16:9','4:3'])
    w.write(out/'brief.json',brief);route=w.plan(brief);route['brief_ref']=w.reference(out/'brief.json');w.write(out/'routes.json',route)
    req=s.init(out/'routes.json');photos=[a for a in brief['assets'] if a['kind']=='photo'][:2]
    w.write(out/'synthetic-observations.md','Synthetic observations only. Demonstration followed by reaction; fictional wordplay fixture. Not user approval or a real event.')
    req['analysis']=dict(synopsis='Synthetic setup, response and wordplay; no actual person or event.',
        evidence=[dict(id='setup',kind='visual',source_ref=photos[0]['artifact'],observation='Synthetic demonstration shape',confidence='agent_observed',asset_ids=[photos[0]['id']],role='demonstration',time_range_s=[1,2]),
                  dict(id='response',kind='visual',source_ref=photos[1]['artifact'],observation='Synthetic response shape',confidence='agent_observed',asset_ids=[photos[1]['id']],role='reaction',time_range_s=[4,5]),
                  dict(id='meaning',kind='transcript',source_ref=w.reference(out/'synthetic-observations.md'),observation='Fictional wordplay',confidence='agent_observed',asset_ids=[],role='concept')],
        angles=[dict(id='moment',label='瞬间',hook='合成瞬间',signals=['emotion'],evidence_ids=['setup'],priority=3),
                dict(id='sequence',label='过程',hook='合成前后',signals=['sequence'],evidence_ids=['setup','response'],priority=4,relation=dict(kind='temporal',evidence_ids=['setup','response'],explanation='Declared synthetic order')),
                dict(id='meaning',label='概念',hook='合成谐音',signals=['wordplay'],evidence_ids=['meaning'],priority=5)])
    w.write(out/'strategy-request.json',req);selection=s.select(out/'strategy-request.json');w.write(out/'strategy-plan.json',selection)
    master=d.init(out/'routes.json',out/'strategy-plan.json')
    master.update(account='合成测试账号',packaging_ref=w.reference(out/'seed/packaging.json'),safe_layout_ref=w.reference(out/'seed/safe-layout.json'))
    master['color_selection']=dict(mode='content',account=master['account'],
        palette=dict(background='#FFF8EF',foreground='#382B25',accent='#87511D'),
        content_basis=['fictional demonstration and wordplay fixture'],
        rationale='Explicit synthetic test palette, not a default for real videos.')
    for c in master['candidates']:
        c.update(headline='测试封面',composition=c['recipe']+' synthetic geometry',risk='Synthetic rendering only, not aesthetic acceptance')
        c['labels']=['步骤'+str(i+1) for i in range(len(c['asset_ids']))]
    w.write(out/'master.json',master);d.build(out/'master.json',out/'design',pipe)
    desk=w.desk.new_project(brief['project_id'],'内容选案合成验证')
    desk['items'][0]['platforms']['douyin']['fields']['body']='Preserve synthetic publication copy'
    w.write(out/'desk.json',desk)
    print({'selected':[c['id'] for c in selection['selected']],'profiles':4,'rendered':False})


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--engine',type=Path,required=True);p.add_argument('--pipeline',type=Path,default=w.DEFAULT_PIPE)
    a=p.parse_args();prepare(a.output,a.engine,a.pipeline)
