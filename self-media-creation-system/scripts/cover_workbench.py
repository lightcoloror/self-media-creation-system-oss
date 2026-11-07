"""Multi-route cover orchestration. Reuses pipeline Still + offline publication desk.

No image renderer, model downloader, external provider caller or publisher lives here.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import shutil
import struct
import subprocess
import sys
from pathlib import Path

import publication_desk as desk
import cover_methods
import cover_colors

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PIPE = ROOT.parent / 'ai-video-tools-20260708/mvp-video-pipeline'
RATIOS = {'vertical_profile_3_4':'3:4', 'vertical_first_frame_9_16':'9:16',
          'bilibili_16_9':'16:9', 'youtube_16_9':'16:9', 'bilibili_4_3':'4:3'}


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def digest(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def reference(path):
    p = Path(path).resolve()
    return dict(path=str(p), sha256=digest(p))


def bound(ref):
    p = Path(ref['path'])
    if not p.is_absolute() or not p.is_file() or digest(p) != ref['sha256']:
        raise ValueError('missing_or_changed_artifact: ' + str(p))
    return p


def write(path, value):
    desk.write_new(Path(path), value)


def catalog():
    return read(ROOT / 'config/cover-routes.v1.json')


def safe_id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}', value):
        raise ValueError('invalid_id')
    return value


def init(project_id, title):
    return dict(schema='self-media.cover-brief.v1', workflow_version=2, project_id=safe_id(project_id), title=title,
                promise='', facts=[], forbidden_claims=[], requested_ratios=['3:4','9:16','16:9','4:3'],
                ai_authorization=dict(allowed=False, user_quote=''), assets=[], routes=[],
                content_kind='generic', method_ids=[],
                note='Agent fills this from the current project; paths and facts must not be copied from a previous project.')


def cover_requirements(reference, brief, **actual):
    import purpose_continuity
    return purpose_continuity.check_consumer(reference,'covers',dict(brief=brief,**actual))


def plan(brief, context_ref=None):
    previous=brief.get('context_manifest_ref')
    if previous and context_ref and previous!=context_ref:
        import purpose_continuity
        purpose_continuity.check_transition(purpose_continuity.validate_context(bound(previous)),
            purpose_continuity.validate_context(bound(context_ref)))
    if brief.get('schema') != 'self-media.cover-brief.v1':
        raise ValueError('unsupported_brief')
    if type(brief.get('workflow_version',1)) is not int or brief.get('workflow_version',1) not in (1,2):
        raise ValueError('invalid_cover_workflow_version')
    safe_id(brief['project_id'])
    if not brief.get('title') or not brief.get('promise') or not brief.get('facts'):
        raise ValueError('truthful_title_promise_facts_required')
    ratios = brief['requested_ratios']
    if not ratios or len(set(ratios)) != len(ratios) or set(ratios) - set(RATIOS.values()):
        raise ValueError('invalid_requested_ratios')
    assets = brief.get('assets', [])
    ids = set()
    for a in assets:
        if safe_id(a['id']) in ids:
            raise ValueError('duplicate_asset')
        ids.add(a['id'])
        bound(a['artifact'])
        if a.get('local_use_approved') is not True or a.get('privacy_reviewed') is not True:
            raise ValueError('unreviewed_asset')
    kinds = {a['kind'] for a in assets}
    available = set(kinds)
    if len([a for a in assets if a['kind']=='photo']) >= 2:
        available.add('multiple_photos')
    auth = brief.get('ai_authorization', {})
    if auth.get('allowed') is True and str(auth.get('user_quote', '')).strip():
        available.add('ai_opt_in')
    requested = brief.get('routes') or [r['id'] for r in catalog()['routes']]
    if len(set(requested)) != len(requested) or set(requested) - {r['id'] for r in catalog()['routes']}:
        raise ValueError('invalid_routes')
    rows = []
    for route in catalog()['routes']:
        missing = sorted(set(route['needs']) - available)
        rows.append(dict(**route, selected=route['id'] in requested, missing=missing,
                         status='needs_inputs' if missing else 'ready_for_design_not_rendered'))
    context_ref=context_ref or brief.get('context_manifest_ref')
    requirement_report=cover_requirements(context_ref,brief)
    return dict(schema='self-media.cover-route-plan.v1', project_id=brief['project_id'],
                brief=copy.deepcopy(brief), routes=rows, candidate_only=True,
                context_manifest_ref=context_ref, requirement_report=requirement_report,
                content_selection_required=brief.get('workflow_version',1)>=2,
                method_plan=cover_methods.select(brief, rows),
                next_step='Author genuinely different design cards, then compile existing visual plans; native AI is an Agent step, not a CLI subprocess.',
                human_quality_approved=False, publish_authorized=False)


def doctor(pipe):
    src = pipe / 'src/video_creation_pipeline'
    modules = ['case_cover_visual_plan.py','photo_layout.py','remotion_project.py','remotion_skill_handoff.py','cover_layers.py']
    return dict(schema='self-media.cover-doctor.v1', mode='read_only_static',
                pipeline_root=str(pipe), modules={m:(src/m).is_file() for m in modules},
                render_entry=str(pipe/'scripts/remotion_skill.py'),
                node=shutil.which('node'), ffmpeg=shutil.which('ffmpeg'),
                native_imagegen='agent_tool_required_not_callable_from_this_cli',
                cutout='accepts_reviewed_local_RGBA_asset; rembg_runtime_and_model_not_probed',
                service_started=False, network_called=False, runtime_verified=False)


def validate_spec(spec):
    if spec.get('schema') != 'self-media.cover-build.v1':
        raise ValueError('unsupported_build_spec')
    route_plan = read(bound(spec['route_plan_ref']))
    if route_plan.get('brief_ref') and read(bound(route_plan['brief_ref'])) != route_plan['brief']:
        raise ValueError('brief_drift')
    current = plan(route_plan['brief'],route_plan.get('context_manifest_ref'))  # Recheck assets and opt-in, not a historical green flag.
    cover_requirements(current.get('context_manifest_ref'),current['brief'],build=spec)
    if spec['project_id'] != current['project_id']:
        raise ValueError('project_mismatch')
    if spec.get('design_master_ref'):
        master = read(bound(spec['design_master_ref']))
        if master.get('project_id') != spec['project_id']:
            raise ValueError('design_master_project_mismatch')
    routes = {r['id']:r for r in current['routes']}
    ids = set()
    signatures = set()
    if not spec.get('candidates'):
        raise ValueError('candidates_required')
    for c in spec['candidates']:
        if safe_id(c['id']) in ids:
            raise ValueError('duplicate_candidate')
        ids.add(c['id'])
        route = routes.get(c['route'])
        if not route or not route['selected'] or route['missing']:
            raise ValueError('route_not_ready: '+c['route'])
        for key in ('name','hypothesis','composition','strength','risk'):
            if not str(c.get(key,'')).strip():
                raise ValueError('design_card_missing: '+key)
        # Same production recipe + same arrangement is a variant, not another route.
        signature = (c['route'], c['composition'].strip())
        if signature in signatures:
            raise ValueError('duplicate_design_not_a_distinct_candidate')
        signatures.add(signature)
        if c.get('color_selection') is not None:
            cover_colors.validate(c['color_selection'])
        if route['engine'] == 'remotion':
            vp = read(bound(c['visual_plan_ref']))
            if c.get('color_selection') is not None or vp.get('color_selection') is not None:
                cover_colors.validate_plan(vp, c.get('color_selection'))
            if vp['candidate']['candidate_id'] != c['id']:
                raise ValueError('visual_candidate_mismatch')
            generated = [a for a in vp['assets'] if a.get('generated') is True]
            if generated and c['route'] != 'hybrid':
                raise ValueError('generated_asset_in_non_ai_route')
            if c['route'] == 'hybrid' and not generated:
                raise ValueError('hybrid_missing_generated_asset')
            declared = {a['artifact']['sha256']:a['kind'] for a in current['brief']['assets']}
            for a in vp['assets']:
                if a.get('availability')=='available' and a.get('source_kind')!='typography_only':
                    if a['artifact']['sha256'] not in declared:
                        raise ValueError('visual_asset_not_in_brief')
            used = [declared.get(a.get('artifact',{}).get('sha256')) for a in vp['assets']]
            if c['route']=='photo-collage' and used.count('photo')<2:
                raise ValueError('collage_requires_two_real_photos')
            required_kind={'photo-editorial':'photo','hybrid':'photo','evidence-ui':'evidence','cutout-poster':'reviewed_cutout'}.get(c['route'])
            if required_kind and required_kind not in used:
                raise ValueError('route_asset_mismatch')
        else:
            if c.get('reference_uploads') != []:
                raise ValueError('native_ai_route_disallows_reference_upload_in_v1')
            bound(c['prompt_ref'])
            if not c.get('outputs'):
                raise ValueError('native_generation_not_completed')
    import cover_strategy
    plans={c['id']:read(bound(c['visual_plan_ref'])) for c in spec['candidates'] if c['route']!='ai-illustration'}
    cover_strategy.check_binding(spec,current['brief'],plans)
    return current


def pipeline_import(pipe):
    sys.path.insert(0, str(pipe/'src'))


def compile_project(spec_path, out, pipe, runtime, skill_root):
    spec = read(spec_path)
    validate_spec(spec)
    pipeline_import(pipe)
    from video_creation_pipeline.contract_io import artifact_reference
    from video_creation_pipeline.case_cover_visual_plan import validate_case_cover_visual_plan
    from video_creation_pipeline.remotion_skill_handoff import build_remotion_skill_handoff, write_remotion_skill_handoff
    from video_creation_pipeline.remotion_project import materialize_remotion_project
    visual = [c for c in spec['candidates'] if c['route'] != 'ai-illustration']
    if not visual:
        raise ValueError('no_local_compositions; use collect for completed native outputs')
    safe = bound(spec['safe_layout_ref']) if spec.get('safe_layout_ref') else None
    packaging = bound(spec['packaging_ref'])
    for c in visual:
        validate_case_cover_visual_plan(read(bound(c['visual_plan_ref'])), safe_media_layout_path=safe)
    out.mkdir(parents=True, exist_ok=False)
    collection = out/'visual-plans.json'
    write(collection, dict(schema='lucas.case_cover_visual_plan_collection.v1', candidate_only=True,
                           plans=[artifact_reference(bound(c['visual_plan_ref']), 'cover plan') for c in visual]))
    handoff = build_remotion_skill_handoff(skill_root, packaging, composition_id='CoverWorkbench',
                safe_media_layout_path=safe, case_cover_visual_plan_collection_path=collection)
    hp = write_remotion_skill_handoff(handoff, out/'handoff.json')
    result = materialize_remotion_project(hp, runtime, out/'remotion',
                      license_basis='individual', include_safe_layout_media=bool(safe))
    receipt = dict(schema='self-media.cover-compile.v1', spec_ref=reference(spec_path),
                   files={k:str(v) for k,v in result.items()}, rendered=False, publish_authorized=False)
    write(out/'compile-receipt.json', receipt)
    return receipt


def png_size(path):
    # Header inspection only; does not edit images or stand in for visual review.
    with Path(path).open('rb') as f:
        header = f.read(24)
    if len(header)!=24 or header[:8]!=b'\x89PNG\r\n\x1a\n' or header[12:16]!=b'IHDR':
        raise ValueError('not_a_png')
    return struct.unpack('>II', header[16:24])


def collect(spec_path, receipt_paths, desk_path, item_id, out, pipe=DEFAULT_PIPE):
    import cover_strategy
    spec = read(spec_path)
    rp = validate_spec(spec)
    selection=cover_strategy.verify(spec['strategy_plan_ref'],spec['route_plan_ref']) if spec.get('strategy_plan_ref') else None
    candidates = {c['id']:c for c in spec['candidates']}
    images = {cid:{} for cid in candidates}
    refs = []
    def add(cid, ratio, artifact, evidence):
        if ratio not in rp['brief']['requested_ratios'] or ratio in images[cid]:
            raise ValueError('unexpected_or_duplicate_ratio')
        path = bound(artifact)
        w,h = png_size(path)
        a,b = map(int, ratio.split(':'))
        if min(w,h)<480 or abs(w/h-a/b) > .002:
            raise ValueError('image_ratio_or_resolution_mismatch')
        images[cid][ratio] = dict(id=cid+'_'+ratio.replace(':','x'), label=candidates[cid]['name']+' '+ratio,
                    **reference(path), width=w, height=h, production_evidence=evidence,
                    visual_review='pending', human_selected=False)
    for receipt_path in receipt_paths:
        r = read(receipt_path)
        if r.get('schema')!='video_creation_pipeline.remotion_cover_run_receipt.v1' or r.get('status')!='completed_candidate_only':
            raise ValueError('not_a_completed_render_receipt')
        pipeline_import(pipe)
        from video_creation_pipeline.remotion_project import validate_remotion_cover_run_receipt
        validate_remotion_cover_run_receipt(r)
        manifest = read(bound(r['source_manifest']))
        collection = read(bound(manifest['inputs']['case_cover_visual_plan_collection']))
        rendered_plans = {ref['sha256'] for ref in collection['plans']}
        refs.append(reference(receipt_path))
        for output in r['outputs']:
            cid = output['candidate_id']
            if cid not in candidates or candidates[cid]['route']=='ai-illustration':
                raise ValueError('render_candidate_not_in_spec')
            if candidates[cid]['visual_plan_ref']['sha256'] not in rendered_plans:
                raise ValueError('render_plan_does_not_match_spec')
            add(cid, RATIOS[output['profile_id']], output['candidate_image'], reference(receipt_path))
    for cid,c in candidates.items():
        if c['route']=='ai-illustration':
            for output in c['outputs']:
                add(cid, output['ratio'], output['artifact'], dict(provider='native_imagegen',
                          prompt_ref=c['prompt_ref'], execution='agent_generated_then_imported'))
        if not images[cid]:
            raise ValueError('candidate_has_no_image: '+cid)
    delivery=cover_strategy.delivery(selection,images)
    data = desk.normalize(read(desk_path), str(desk_path))
    if data['project_id'] != spec['project_id']:
        raise ValueError('desk_project_mismatch')
    matches = [i for i in data['items'] if i['id']==item_id]
    if len(matches)!=1:
        raise ValueError('desk_item_not_found')
    item = matches[0]
    # Preserve prior assets, selections and human records as history; no automatic selection.
    item.setdefault('cover_history', []).append(dict(covers=copy.deepcopy(item['covers']), cover_pk=copy.deepcopy(item.get('cover_pk'))))
    existing = {a['id']:a for a in item['covers']}
    for row in images.values():
        for a in row.values():
            if a['id'] in existing and existing[a['id']] != a:
                raise ValueError('cover_id_collision')
            existing[a['id']] = a
    item['covers'] = list(existing.values())
    item['cover_pk'] = dict(recommended=spec.get('recommended','未指定'), selected=None,
          required_ratios=rp['brief']['requested_ratios'], platform_ratios=spec.get('platform_ratios', {}),
          candidates=[dict(id=cid, name=c['name'], route=c['route'],
             title=c.get('title') or (read(bound(c['visual_plan_ref']))['candidate']['title'] if c.get('visual_plan_ref') else rp['brief']['title']),
             hypothesis=c['hypothesis'], strength=c['strength'], risk=c['risk'],
             design_method=c.get('design_method'), source_methods=c.get('source_methods', []),
             color_selection=c.get('color_selection'),
             generative_model_used=c.get('generative_model_used', c['route'] in ('hybrid','ai-illustration')),
             segmentation_model_used=c.get('segmentation_model_used'),
             cover_by_ratio={ratio:a['id'] for ratio,a in images[cid].items()},
             missing_ratios=[r for r in rp['brief']['requested_ratios'] if r not in images[cid]]) for cid,c in candidates.items()])
    item['cover_pk']['delivery']=delivery
    if selection:
        item['cover_pk']['strategy_plan_ref']=spec['strategy_plan_ref']
        item['cover_pk']['strategy_dispositions']=selection['dispositions']
        decisions={c['id']:c for c in selection['selected']}
        for c in item['cover_pk']['candidates']:
            decision=decisions[c['id']]
            c.update(angle=decision['angle_label'],selection_reason=decision['selection_reason'],
                     evidence_ids=decision['evidence_ids'],layout_family=decision['layout_family'])
    data['revision'] = int(data.get('revision',1))+1
    requirement_report=cover_requirements(rp.get('context_manifest_ref'),rp['brief'],build=spec,publication_data=data)
    out.mkdir(parents=True, exist_ok=False)
    write(out/'publication-data.json', data)
    write(out/'封面比较与发布辅助页.html', desk.render(data))
    report = dict(schema='self-media.cover-collection.v1', spec_ref=reference(spec_path),
                  source_desk_ref=reference(desk_path), render_receipts=refs,
                  candidates=len(candidates), images=sum(map(len,images.values())),
                  routes=sorted({c['route'] for c in candidates.values()}),
                  missing={cid:[r for r in rp['brief']['requested_ratios'] if r not in row] for cid,row in images.items()},
                  generated_visuals_are_not_real_scenes=True, rendered_file_checks='hash_png_header_ratio',
                  delivery=delivery, requirement_report=requirement_report,
                  human_quality_approved=False, ctr_validated=False, publish_authorized=False)
    write(out/'collection-receipt.json', report)
    return report


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=['catalog','methods','styles','doctor','init','plan','strategy-init','strategy-plan','review-init','review-check','design-recipes','design-init','design-build','compile','render','collect'])
    p.add_argument('--query', default=''); p.add_argument('--template-id')
    p.add_argument('--pipeline-root',type=Path,default=DEFAULT_PIPE)
    p.add_argument('--input',type=Path); p.add_argument('--output',type=Path)
    p.add_argument('--project-id'); p.add_argument('--title')
    p.add_argument('--strategy-plan',type=Path)
    p.add_argument('--runtime-source',type=Path); p.add_argument('--skill-root',type=Path)
    p.add_argument('--browser',type=Path); p.add_argument('--receipt',type=Path,action='append',default=[])
    p.add_argument('--desk',type=Path); p.add_argument('--item-id',default='main')
    p.add_argument('--context-manifest',type=Path)
    args=p.parse_args(argv)
    try:
        if args.action=='catalog': result=catalog()
        elif args.action=='methods': result=cover_methods.inventory()
        elif args.action=='styles': result=cover_methods.styles(args.query, args.template_id)
        elif args.action=='doctor': result=doctor(args.pipeline_root)
        elif args.action in ('strategy-init','strategy-plan','review-init','review-check'):
            import cover_strategy
            if not args.input or not args.output:raise ValueError('input_and_output_required')
            if args.action=='strategy-init':result=cover_strategy.init(args.input)
            elif args.action=='strategy-plan':result=cover_strategy.select(args.input)
            elif args.action=='review-init':result=cover_strategy.review_init(args.input,args.item_id)
            else:result=cover_strategy.review_check(args.input)
            write(args.output,result)
        elif args.action=='design-recipes':
            import cover_design
            result=cover_design.recipes()
        elif args.action in ('design-init','design-build'):
            import cover_design
            if not args.input or not args.output: raise ValueError('input_and_output_required')
            if args.action=='design-init':
                result=cover_design.init(args.input,args.strategy_plan);write(args.output,result)
            else: result=cover_design.build(args.input,args.output,args.pipeline_root)
        elif args.action=='init':
            if not args.output or not args.title: raise ValueError('output_and_title_required')
            result=init(args.project_id,args.title);write(args.output,result)
        elif args.action=='plan':
            if not args.input or not args.output: raise ValueError('input_and_output_required')
            result=plan(read(args.input),reference(args.context_manifest) if args.context_manifest else None);result['brief_ref']=reference(args.input);write(args.output,result)
        elif args.action=='compile':
            if not all([args.input,args.output,args.runtime_source,args.skill_root]): raise ValueError('compile_arguments_required')
            result=compile_project(args.input,args.output,args.pipeline_root,args.runtime_source,args.skill_root)
        elif args.action=='render':
            if not all([args.input,args.runtime_source,args.browser]): raise ValueError('render_arguments_required')
            command=[sys.executable,str(args.pipeline_root/'scripts/remotion_skill.py'),'run-covers',
                     '--manifest',str(args.input),'--runtime-source',str(args.runtime_source),
                     '--browser',str(args.browser),'--timeout','60']
            # The existing outlet owns resource admission, installed-runtime checks and receipts.
            return subprocess.run(command,check=False).returncode
        else:
            if not all([args.input,args.desk,args.output]): raise ValueError('collect_arguments_required')
            result=collect(args.input,args.receipt,args.desk,args.item_id,args.output,args.pipeline_root)
        print(json.dumps(result,ensure_ascii=False,indent=2));return 0
    except (OSError,ValueError,KeyError,TypeError,ImportError) as exc:
        print(json.dumps(dict(status='blocked',error=str(exc),publish_authorized=False),ensure_ascii=False));return 2


if __name__=='__main__':
    if hasattr(sys.stdout,'reconfigure'): sys.stdout.reconfigure(encoding='utf-8')
    raise SystemExit(main())
