"""Prepare generic synthetic media and unmocked safe-layout/compiler integration.

No family media, downloading, renderer launch or publication. Caller supplies the
already installed upstream tools. All artifacts go to a new caller output folder.
"""
import argparse
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import cover_workbench as w
import cover_design as d
from PIL import Image,ImageDraw


def prepare(out,engine,pipe):
    out=Path(out).resolve();out.mkdir(parents=True,exist_ok=False)
    media=out/'synthetic-assets';media.mkdir()
    for i in range(5):
        im=Image.new('RGBA',(800,600),(242,232-i*8,207+i*7,255) if i!=3 else (0,0,0,0))
        draw=ImageDraw.Draw(im)
        draw.rounded_rectangle((100+i*15,130,650,480),radius=35,fill=(35+i*22,110,140,255))
        draw.ellipse((300,35+i*10,450,185+i*10),fill=(227,151,66,255))
        draw.line((110,530,680,530),fill=(40,60,70,255),width=8)
        im.save(media/f'synthetic-{i}.png')
    w.pipeline_import(pipe)
    from video_creation_pipeline.photo_layout import build_photo_media_preflight,build_safe_media_layout_plan,write_photo_layout_contract
    from video_creation_pipeline.contract_io import artifact_reference
    pre=build_photo_media_preflight(media);write_photo_layout_contract(pre,out/'preflight.json')
    safe=build_safe_media_layout_plan(out/'preflight.json',engine,asset_ids=[a['asset_id'] for a in pre['assets']],width=1920,height=1080)
    write_photo_layout_contract(safe,out/'safe-layout.json')
    assets=[]
    for i,a in enumerate(pre['assets']):
        assets.append(dict(id=a['asset_id'],kind='reviewed_cutout' if i==3 else 'evidence' if i==4 else 'photo',artifact=a['source_asset'],
             local_use_approved=True,privacy_reviewed=True,generated=False,subject_reviewed=True,
             protected_regions=[d.box(.125,.05,.73,.8)],cutout_reviewed=i==3,
             verified_focus='Synthetic shapes only, not real evidence' if i==4 else None,
             segmentation_model_used=False,provenance=dict(synthetic=True,source='Pillow primitive fixture, not generated-model output')))
    brief=w.init('generic-cover-smoke','通用封面合成验证')
    brief.update(workflow_version=1,promise='验证旧版七配方排版而非内容选案',facts=['全部素材为几何合成图，不代表真实人物或证据'],assets=assets,
                 requested_ratios=['3:4','16:9'],routes=sorted({r['route'] for r in d.recipes()['recipes']}))
    w.write(out/'brief.json',brief);rp=w.plan(brief);rp['brief_ref']=w.reference(out/'brief.json');w.write(out/'routes.json',rp)
    packaging=dict(schema='video_creation_pipeline.video_packaging_plan.v1',aspect_ratio='16:9',output=dict(width=1920,height=1080,fps=30),
        scenes=[dict(scene_id='synthetic',story_segment_ref='synthetic',start_s=0,end_s=1,evidence_refs=['synthetic:geometry'])],status='candidate_only')
    w.write(out/'packaging.json',packaging)
    master=d.init(out/'routes.json');master.update(account='通用设计测试（非真实账号）',packaging_ref=artifact_reference(out/'packaging.json','synthetic packaging'),safe_layout_ref=artifact_reference(out/'safe-layout.json','safe layout'))
    master['color_selection']=dict(mode='content',account=master['account'],
        palette=dict(background='#FFF8EF',foreground='#382B25',accent='#87511D'),
        content_basis=['synthetic geometry only'],rationale='Explicit synthetic fixture colors, not a default for real projects.')
    for r in d.recipes()['recipes']:
        ids=[a['id'] for a in assets if a['kind'] in r['kinds']][:r['max_assets']]
        master['candidates'].append(dict(id=r['id'],recipe=r['id'],name=r['name'],title='合成测试：'+r['name'],headline='设计测试',
           asset_ids=ids,labels=['步骤'+str(i+1) for i in range(len(ids))],relation_basis='Synthetic demonstration order only',
           hypothesis='验证 '+r['name'],composition=r['mechanism'],strength='素材、字号、图层可追溯',risk='不是视觉质量或真实素材验收'))
    w.write(out/'master.json',master)
    receipt=d.build(out/'master.json',out/'design',pipe)
    w.write(out/'desk.json',w.desk.new_project(brief['project_id'],brief['title']))
    print(receipt)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--engine',type=Path,required=True);p.add_argument('--pipeline',type=Path,default=w.DEFAULT_PIPE)
    a=p.parse_args();prepare(a.output,a.engine,a.pipeline)
