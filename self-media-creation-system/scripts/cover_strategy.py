"""Evidence-backed editorial selection, not a video-understanding model or renderer.

An Agent supplies reviewed observations/angles. Selection scores are transparent
editorial heuristics, never CTR estimates. All execution/publication gates remain.
"""
from __future__ import annotations
import copy
import itertools
import math

import cover_workbench as w

SIGNALS={'emotion','relationship','discovery','character','reaction','sequence','demonstration',
         'reversal','contrast','before_after','wordplay','metaphor','explanation','evidence','result'}
ROLES={'context','reaction','demonstration','outcome','detail','concept'}
STRATEGIES=[
    dict(id='real-moment',name='真实瞬间',route='photo-editorial',recipe='photo-caption',family='single-photo',
         signals=['emotion','relationship','discovery','character','reaction'],kinds=['photo'],minimum=1,maximum=1),
    dict(id='story-sequence',name='前后叙事',route='photo-collage',recipe='storyboard',family='sequence',
         signals=['sequence','demonstration','reversal'],kinds=['photo'],minimum=2,maximum=3,relation='temporal'),
    dict(id='real-comparison',name='真实对照',route='photo-collage',recipe='comparison',family='comparison',
         signals=['contrast','before_after'],kinds=['photo'],minimum=2,maximum=2,relation='comparison'),
    dict(id='type-metaphor',name='概念与图文反差',route='type-led',recipe='type-symbol',family='concept-symbol',
         signals=['wordplay','metaphor','contrast','explanation'],kinds=[],minimum=0,maximum=0),
    dict(id='evidence-focus',name='证据或操作界面',route='evidence-ui',recipe='evidence-focus',family='evidence',
         signals=['evidence','result'],kinds=['evidence'],minimum=1,maximum=1),
    dict(id='character-cutout',name='真实主体抠图',route='cutout-poster',recipe='cutout-type',family='cutout',
         signals=['character','reaction','emotion'],kinds=['reviewed_cutout'],minimum=1,maximum=1),
    dict(id='hybrid-metaphor',name='真实人物与概念装饰',route='hybrid',recipe=None,family='hybrid',
         signals=['wordplay','metaphor'],kinds=['photo','generated_decoration'],minimum=2,maximum=2),
    dict(id='ai-concept',name='AI 概念插画',route='ai-illustration',recipe=None,family='illustration',
         signals=['wordplay','metaphor','explanation'],kinds=[],minimum=0,maximum=0),
]


def _text(value, field):
    if not isinstance(value,str) or not value.strip() or len(value)>5000:
        raise ValueError('strategy_text_required: '+field)
    return value


def _ids(values, allowed, field, minimum=1):
    if not isinstance(values,list) or len(values)<minimum or any(not isinstance(x,str) for x in values) or len(set(values))!=len(values) or set(values)-set(allowed):
        raise ValueError('strategy_invalid_ids: '+field)
    return values


def init(route_path):
    rp=w.read(route_path);w.plan(rp['brief'])
    return dict(schema='self-media.cover-strategy-request.v1',project_id=rp['project_id'],route_plan_ref=w.reference(route_path),
        analysis=dict(synopsis='',evidence=[],angles=[]),
        policy=dict(selection_mode='all_applicable',min_angles=2,min_layout_families=2),candidate_only=True,manual_publish_only=True,
        instruction='Agent inspects current video, reviewed transcript and user corrections. Populate grounded angles and observations, not genre keywords alone. Never invent source review or image-generation consent.')


def _load_request(path):
    req=w.read(path)
    if req.get('schema')!='self-media.cover-strategy-request.v1' or req.get('candidate_only') is not True or req.get('manual_publish_only') is not True:
        raise ValueError('invalid_strategy_request')
    rp=w.read(w.bound(req['route_plan_ref']));brief=rp['brief'];current=w.plan(brief)
    if rp.get('brief_ref') and w.read(w.bound(rp['brief_ref']))!=brief:raise ValueError('brief_drift')
    if req.get('project_id')!=current['project_id']:raise ValueError('strategy_project_mismatch')
    analysis=req['analysis'];_text(analysis.get('synopsis'),'synopsis')
    assets={a['id']:a for a in brief['assets']};evidence={};angles={}
    if not isinstance(analysis.get('evidence'),list) or not 1<=len(analysis['evidence'])<=200:raise ValueError('strategy_evidence_required')
    for e in analysis['evidence']:
        eid=w.safe_id(e['id'])
        if eid in evidence:raise ValueError('duplicate_evidence')
        _text(e.get('observation'),'observation');w.bound(e['source_ref'])
        if e.get('kind') not in {'visual','human_review','transcript'} or e.get('role') not in ROLES:raise ValueError('invalid_evidence_kind_or_role')
        if e.get('confidence') not in {'agent_observed','human_confirmed','asr_candidate'}:raise ValueError('invalid_evidence_confidence')
        _ids(e.get('asset_ids'),assets,'evidence_asset_ids',0)
        if e.get('time_range_s') is not None:
            t=e['time_range_s']
            if not isinstance(t,list) or len(t)!=2 or any(isinstance(x,bool) or not isinstance(x,(float,int)) or not math.isfinite(x) for x in t) or not 0<=t[0]<=t[1]:raise ValueError('invalid_evidence_time')
        evidence[eid]=e
    if not isinstance(analysis.get('angles'),list) or not 1<=len(analysis['angles'])<=24:raise ValueError('strategy_angles_required')
    for a in analysis['angles']:
        aid=w.safe_id(a['id'])
        if aid in angles:raise ValueError('duplicate_angle')
        for f in ['label','hook']:_text(a.get(f),f)
        _ids(a.get('signals'),SIGNALS,'angle_signals');_ids(a.get('evidence_ids'),evidence,'angle_evidence')
        if any(evidence[eid]['confidence']=='asr_candidate' for eid in a['evidence_ids']):raise ValueError('unreviewed_asr_is_not_cover_truth')
        if isinstance(a.get('priority'),bool) or not isinstance(a.get('priority'),int) or not 1<=a['priority']<=5:raise ValueError('invalid_angle_priority')
        rel=a.get('relation')
        if rel:
            if rel.get('kind') not in {'temporal','comparison'}:raise ValueError('invalid_relation')
            _ids(rel.get('evidence_ids'),a['evidence_ids'],'relation_evidence',2);_text(rel.get('explanation'),'relation_explanation')
        angles[aid]=a
    policy=req['policy']
    mode=policy.get('selection_mode','fixed_count' if 'target_count' in policy else 'all_applicable')
    if mode not in {'all_applicable','fixed_count'}:raise ValueError('invalid_selection_policy')
    if mode=='all_applicable' and 'target_count' in policy:raise ValueError('ambiguous_selection_policy')
    for key in ['min_angles','min_layout_families']+(['target_count'] if mode=='fixed_count' else []):
        if isinstance(policy.get(key),bool) or not isinstance(policy.get(key),int) or not 1<=policy[key]<=len(STRATEGIES):raise ValueError('invalid_selection_policy')
    if mode=='fixed_count' and max(policy['min_angles'],policy['min_layout_families'])>policy['target_count']:raise ValueError('impossible_selection_policy')
    return req,current,assets,evidence,angles


def select(request_path):
    req,rp,assets,evidence,angles=_load_request(request_path)
    routes={r['id']:r for r in rp['routes']};dispositions=[];eligible=[]
    for angle in angles.values():
        for method in STRATEGIES:
            cid=w.safe_id(angle['id']+'--'+method['id'])
            row=dict(id=cid,angle_id=angle['id'],strategy_id=method['id'],route=method['route'])
            matched=sorted(set(angle['signals'])&set(method['signals']))
            if not matched:
                dispositions.append(dict(**row,status='not_applicable',reason='内容角度没有支持此方法的叙事信号'));continue
            route=routes[method['route']]
            if not route['selected']:
                dispositions.append(dict(**row,status='disabled_route',reason='当前项目未选择该制作路线'));continue
            missing=list(route['missing']);chosen=[];seen=set()
            order=(angle.get('relation') or {}).get('evidence_ids',angle['evidence_ids'])
            for eid in order:
                for aid in evidence[eid]['asset_ids']:
                    a=assets[aid];identity=a['artifact']['sha256']
                    if a['kind'] in method['kinds'] and identity not in seen:
                        chosen.append(aid);seen.add(identity)
            # A mixed route needs one of each required kind, not merely the first
            # N images (which could all be photographs).
            if len(method['kinds'])>1:
                chosen=[next((aid for aid in chosen if assets[aid]['kind']==kind),None) for kind in method['kinds']]
                chosen=[aid for aid in chosen if aid is not None]
            else:chosen=chosen[:method['maximum']]
            if len(chosen)<method['minimum']:missing.append('angle_linked_distinct_assets')
            if set(method['kinds'])-{assets[aid]['kind'] for aid in chosen}:missing.append('angle_linked_asset_kinds')
            if method.get('relation'):
                relation=angle.get('relation',{})
                if relation.get('kind')!=method['relation']:missing.append('grounded_'+method['relation']+'_relation')
                visual_roles={evidence[eid]['role'] for eid in order
                              if evidence[eid]['kind']=='visual' and set(evidence[eid]['asset_ids'])&set(chosen)}
                if len(visual_roles)<2:missing.append('distinct_visual_roles')
            if missing:
                dispositions.append(dict(**row,status='missing_inputs',missing=sorted(set(missing)),reason='适用内容存在，但所需素材、关系证据或授权不完整'));continue
            base=angle['priority']*100+len(matched)*10
            eligible.append(dict(**row,name=angle['label']+' · '+method['name'],angle_label=angle['label'],
                hook=angle['hook'],recipe=method['recipe'],layout_family=method['family'],asset_ids=chosen,
                evidence_ids=angle['evidence_ids'],relation=copy.deepcopy(angle.get('relation')),
                score=base,matched_signals=matched,required_ratios=rp['brief']['requested_ratios'],
                selection_reason='角度「'+angle['label']+'」由 '+', '.join(angle['evidence_ids'])+' 支持；'+method['name']+' 表达 '+', '.join(matched)))
    # Bounded beam search optimizes coverage before editorial priority. It cannot
    # fill a portfolio with multiple names for the same layout family.
    policy=req['policy'];beam=[[]]
    adaptive='target_count' not in policy
    applicable_families={c['layout_family'] for c in eligible}
    target_count=len(applicable_families) if adaptive else policy['target_count']
    def rank(group):
        return (min(len({c['angle_id'] for c in group}),policy['min_angles']),
                min(len({c['layout_family'] for c in group}),policy['min_layout_families']),
                sum(c['score'] for c in group),len({a for c in group for a in c['asset_ids']}))
    for _ in range(target_count):
        expanded={}
        for group in beam:
            families={c['layout_family'] for c in group}
            for c in eligible:
                if c['layout_family'] in families:continue
                proposal=sorted(group+[c],key=lambda x:x['id'])
                expanded[tuple(x['id'] for x in proposal)]=proposal
        if not expanded:break
        beam=sorted(expanded.values(),key=lambda g:(tuple(-v for v in rank(g)),tuple(c['id'] for c in g)))[:64]
    selected=beam[0];ids={c['id'] for c in selected};families={c['layout_family'] for c in selected}
    for c in eligible:
        if c['id'] not in ids:
            dispositions.append(dict(id=c['id'],angle_id=c['angle_id'],strategy_id=c['strategy_id'],route=c['route'],score=c['score'],
                status='redundant_treatment' if c['layout_family'] in families else 'not_selected',
                reason='同一构图族只保留一个代表；按角度覆盖、构图差异及内容优先级取舍'))
    gaps=[]
    if len(selected)<target_count:gaps.append('candidate_count')
    if len({c['angle_id'] for c in selected})<policy['min_angles']:gaps.append('angle_diversity')
    if len(families)<policy['min_layout_families']:gaps.append('layout_diversity')
    result=dict(schema='self-media.cover-strategy-plan.v1',project_id=req['project_id'],request_ref=w.reference(request_path),
        route_plan_ref=req['route_plan_ref'],required_ratios=rp['brief']['requested_ratios'],synopsis=req['analysis']['synopsis'],
        selected=selected,dispositions=dispositions,gaps=gaps,status='needs_more_evidence_or_revised_policy' if gaps else 'ready_for_design',
        score_semantics='Editorial heuristic: diversity coverage before Agent-declared angle priority. Not audience data or CTR prediction.',
        visual_diversity='requires_actual_layout_and_image_review',candidate_only=True,rendered=False,human_quality_approved=False,publish_authorized=False)
    # Keep legacy fixed-count plans byte-for-value replayable. New plans explain
    # their derived count; a new engine or recolor is not another treatment.
    if adaptive:
        result['selection_scope']=dict(mode='all_applicable',registered_methods=len(STRATEGIES),
            eligible_combinations=len(eligible),eligible_families=sorted(applicable_families),
            selected_count=len(selected),count_is_user_limit=False,
            reason='每个内容有依据、输入与授权齐备的构图族保留一个代表；数量由当前证据决定，不预设三套。登记方法库不是所有可能创意的穷举。')
    return result


def verify(plan_ref, route_ref):
    saved=w.read(w.bound(plan_ref))
    if saved.get('schema')!='self-media.cover-strategy-plan.v1' or saved.get('route_plan_ref')!=route_ref:raise ValueError('strategy_route_mismatch')
    fresh=select(w.bound(saved['request_ref']))
    if fresh!=saved:raise ValueError('strategy_plan_drift')
    if fresh['status']!='ready_for_design':raise ValueError('strategy_selection_incomplete')
    return fresh


def check_layout_diversity(plans):
    """Ignore labels/fonts/colors; near-identical photo layout is not another idea."""
    for a,z in itertools.combinations(plans,2):
        la=a['render_spec']['profile_layouts'];lz=z['render_spec']['profile_layouts']
        for pid in set(la)&set(lz):
            def signature(vp,layout):
                sha={x['asset_id']:x.get('artifact',{}).get('sha256',x['asset_id']) for x in vp['assets']}
                return sorted([(sha[m['asset_id']],tuple(m['box'][k] for k in ['x','y','width','height'])) for m in layout['media']])
            x,y=signature(a,la[pid]),signature(z,lz[pid])
            if x and len(x)==len(y) and all(ax==ay and max(abs(p-q) for p,q in zip(bx,by))<=.04 for (ax,bx),(ay,by) in zip(x,y)):
                raise ValueError('lookalike_composition: '+a['candidate']['candidate_id']+' / '+z['candidate']['candidate_id']+' / '+pid)


def check_binding(spec, brief, plans, check_layouts=True):
    ref=spec.get('strategy_plan_ref')
    if not ref:
        if brief.get('workflow_version',1)>=2:raise ValueError('strategy_plan_required_for_content_driven_workflow')
        return None
    selection=verify(ref,spec['route_plan_ref']);chosen={c['id']:c for c in selection['selected']}
    source_assets={a['id']:a for a in brief['assets']}
    cards={c['id']:c for c in spec['candidates']}
    if len(cards)!=len(spec['candidates']) or set(cards)!=set(chosen):raise ValueError('selected_concept_set_mismatch')
    for cid,c in cards.items():
        expected=chosen[cid]
        if c['route']!=expected['route']:raise ValueError('selected_route_substitution')
        if c.get('design_method') is not None and c['design_method']!=expected['recipe']:raise ValueError('selected_recipe_substitution')
        if cid in plans:
            plan=plans[cid]
            if {a['asset_id'] for a in plan['assets']}!=set(expected['asset_ids']):raise ValueError('selected_assets_substitution')
            for asset in plan['assets']:
                if asset.get('artifact',{}).get('sha256')!=source_assets[asset['asset_id']]['artifact']['sha256']:
                    raise ValueError('selected_asset_identity_substitution')
            ratios=[w.RATIOS[p['profile_id']] for p in plan['profiles']]
            if check_layouts:
                layouts=plan['render_spec']['profile_layouts']
                for profile in plan['profiles']:
                    used={a['asset_id'] for a in layouts[profile['profile_id']]['media']}
                    if used!=set(expected['asset_ids']):raise ValueError('selected_assets_missing_in_profile')
        else:ratios=[a['ratio'] for a in c.get('outputs',[])]
        if len(ratios)!=len(selection['required_ratios']) or set(ratios)!=set(selection['required_ratios']):raise ValueError('required_ratio_set_mismatch')
    if check_layouts:check_layout_diversity(list(plans.values()))
    return selection


def _check_image(asset,ratio):
    from PIL import Image
    path=w.bound(asset)
    with Image.open(path) as im:
        width,height=im.size
        a,b=map(int,ratio.split(':'))
        if im.format!='PNG' or min(width,height)<480 or width*height>40000000 or abs(width/height-a/b)>.002:
            raise ValueError('delivery_image_ratio_or_resolution')
        im.verify()
    with Image.open(path) as im:im.load()


def delivery(selection, images):
    if selection is None:return dict(status='legacy_selection_unassessed',complete=False)
    matrix={c['id']:{r:('rendered_pending_visual_review' if r in images[c['id']] else 'missing') for r in selection['required_ratios']} for c in selection['selected']}
    complete=all(v!='missing' for row in matrix.values() for v in row.values())
    hashes={}
    for cid,row in images.items():
        for ratio,asset in row.items():
            _check_image(asset,ratio)
            key=(ratio,asset['sha256'])
            if key in hashes:raise ValueError('duplicate_rendered_image: '+hashes[key]+' / '+cid)
            hashes[key]=cid
    return dict(status='rendered_pending_visual_review' if complete else 'incomplete_ratios',matrix=matrix,
        required_ratios=selection['required_ratios'],rendered_matrix_complete=complete,complete=False,
        human_quality_approved=False,publish_authorized=False)


def review_init(desk_path,item_id='main'):
    data=w.desk.normalize(w.read(desk_path));matches=[i for i in data['items'] if i['id']==item_id]
    if len(matches)!=1:raise ValueError('review_item_not_found')
    item=matches[0]
    pk=item['cover_pk']
    if not pk.get('strategy_plan_ref'):raise ValueError('content_selection_required_before_review')
    saved=w.read(w.bound(pk['strategy_plan_ref']));selection=verify(pk['strategy_plan_ref'],saved['route_plan_ref'])
    byid={a['id']:a for a in item['covers']};images={};rows=[]
    for c in pk['candidates']:
        if c['id'] in images:raise ValueError('duplicate_review_candidate')
        images[c['id']]={}
        for ratio in selection['required_ratios']:
            aid=c['cover_by_ratio'].get(ratio)
            if aid is None:raise ValueError('missing_ratio_before_visual_review')
            a=byid[aid];w.bound(a);images[c['id']][ratio]=a
            rows.append(dict(candidate_id=c['id'],ratio=ratio,image_ref=dict(path=a['path'],sha256=a['sha256']),
                semantic_correct=None,mobile_readable=None,subject_safe=None,observation=''))
    if set(images)!={c['id'] for c in selection['selected']}:raise ValueError('review_selected_concept_set_mismatch')
    delivery(selection,images)
    pairs=[dict(a=a,b=b,ratio=r,different=None,observation='') for a,b in itertools.combinations(sorted(images),2) for r in selection['required_ratios']]
    return dict(schema='self-media.cover-visual-review.v1',desk_ref=w.reference(desk_path),strategy_plan_ref=pk['strategy_plan_ref'],item_id=item_id,
        reviewer_kind='agent',reviewer='',images=rows,pairs=pairs,review_instructions='Inspect actual full-size and phone-size images, not JSON. Semantic truth and visible distinctness require direct inspection. This never sets human adoption.')


def review_check(path):
    review=w.read(path)
    if review.get('schema')!='self-media.cover-visual-review.v1' or review.get('reviewer_kind')!='agent':raise ValueError('agent_visual_review_required_no_human_approval_inference')
    _text(review.get('reviewer'),'reviewer')
    expected=review_init(w.bound(review['desk_ref']),review['item_id'])
    if review.get('strategy_plan_ref')!=expected['strategy_plan_ref']:raise ValueError('review_strategy_drift')
    for key,identity,checks in [('images',lambda x:(x['candidate_id'],x['ratio'],x['image_ref']['path'],x['image_ref']['sha256']),['semantic_correct','mobile_readable','subject_safe']),
                                ('pairs',lambda x:(x['a'],x['b'],x['ratio']),['different'])]:
        actual=review.get(key,[])
        if len(actual)!=len(expected[key]) or {identity(x) for x in actual}!={identity(x) for x in expected[key]}:raise ValueError('visual_review_coverage_or_hash_mismatch')
        for row in actual:
            _text(row.get('observation'),'visual_observation')
            if any(row.get(field) is not True for field in checks):raise ValueError('visual_review_not_passed')
    return dict(schema='self-media.cover-delivery-check.v1',status='complete_candidate_package_pending_human_selection',
        review_ref=w.reference(path),images=len(review['images']),distinctness_checks=len(review['pairs']),
        agent_visual_review_passed=True,human_quality_approved=False,publish_authorized=False)
