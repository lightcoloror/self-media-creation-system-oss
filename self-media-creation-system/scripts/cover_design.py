"""Portable, account-neutral design masters compiled to existing CoverStill plans.

Only orchestration/layout data: no rasterizer, browser, model, or installation.
The expanded JSON is the editable master; it is not a drag-and-drop editor.
"""
import copy
from pathlib import Path

import cover_workbench as w
import cover_colors


def recipes():
    return w.read(w.ROOT / 'config/cover-design-recipes.v1.json')


def init(route_path, strategy_path=None):
    rp = w.read(route_path)
    current = w.plan(rp['brief'])
    master = dict(schema='self-media.cover-design.v1', project_id=current['project_id'],
                route_plan_ref=w.reference(route_path), account='',
                packaging_ref=None, safe_layout_ref=None,
                color_selection=cover_colors.starter(),
                candidates=[], candidate_only=True, manual_publish_only=True,
                note='Fill color_selection for this content/account (or independently on each candidate). No universal brand palette. Add candidates: id, recipe, name, title, headline, hypothesis, composition, strength, risk, asset_ids, labels, relation_basis. No prior project copied.')
    if strategy_path:
        import cover_strategy
        master['strategy_plan_ref']=w.reference(strategy_path)
        selection=cover_strategy.verify(master['strategy_plan_ref'],master['route_plan_ref'])
        for c in selection['selected']:
            master['candidates'].append(dict(id=c['id'],recipe=c['recipe'],name=c['name'],title=rp['brief']['title'],headline='',
                hypothesis=c['hook'],composition='',strength=c['selection_reason'],risk='',asset_ids=c['asset_ids'],labels=[],
                relation_basis=(c.get('relation') or {}).get('explanation',''),
                design_instruction='Fill headline/composition/risk and labels; author each required ratio. A selected native AI/hybrid route with recipe=null uses its existing visual-plan/native-imagegen outlet, not design-build.'))
    elif rp['brief'].get('workflow_version',1)>=2:
        raise ValueError('strategy_plan_required: use strategy-init and strategy-plan before design-init')
    return master


def box(x, y, width, height):
    return dict(x=x, y=y, width=width, height=height)


def wrap(text, font, width):
    """Conservative starting wrap. Reject rather than shrink below phone minimum."""
    result = []
    for paragraph in text.split('\n'):
        line, units = '', 0
        for char in paragraph:
            weight = .65 if ord(char) < 128 else 1.05
            if line and (units + weight) * font > width:
                result.append(line)
                line, units = '', 0
            line += char
            units += weight
        result.append(line)
    return '\n'.join(result)


def default_layout(recipe, candidate, assets, profile, palette, gate):
    width, height = profile['width'], profile['height']
    portrait = height > width
    title = box(.07, .055, .86, .26 if portrait else .25)
    layers, media = [], []

    def text(lid, value, role, rect):
        font = gate['roles'][role]
        rendered = wrap(value, font, rect['width'] * width)
        if len(rendered.split('\n')) * font * 1.12 > rect['height'] * height:
            raise ValueError('text_does_not_fit_shorten_or_edit_layout: ' + lid)
        layers.append(dict(id=lid, type='text', text=rendered, role=role, box=rect,
                           font_px=font, color=palette['foreground']))

    count = len(assets)
    rid = recipe['id']
    if rid == 'type-symbol':
        title = box(.09, .15, .82, .42)
        layers.extend([dict(id='accent',type='ellipse',box=box(.68,.69,.18,.13),color=palette['accent']),
                       dict(id='line',type='line',box=box(.1,.72,.48,.03),color=palette['accent'])])
        boxes = []
    elif rid in ('comparison', 'storyboard'):
        if portrait:
            step = .59 / count
            boxes = [box(.08, .36 + i*step, .84, step-.07) for i in range(count)]
        else:
            step = .88 / count
            boxes = [box(.06+i*step, .39, step-.03, .41) for i in range(count)]
    elif rid == 'cutout-type' and not portrait:
        title = box(.07,.16,.41,.63)
        boxes = [box(.53,.09,.4,.8)]
    else:
        boxes = [box(.1,.36,.8,.5)]
    for i, (asset, rect) in enumerate(zip(assets, boxes)):
        if rid == 'cutout-type':
            layers.append(dict(id='subject-background',type='ellipse',box=rect,color=palette['accent']))
        media.append(dict(asset_id=asset['id'],box=rect,fit_mode='contain',crop_allowed=False))
        layers.append(dict(id='image-'+str(i),type='image',asset_id=asset['id'],box=rect,
                           subject_reviewed=asset.get('subject_reviewed') is True,
                           protected_regions=asset.get('protected_regions', [])))
        if rid in ('comparison','storyboard'):
            r = box(rect['x'],rect['y']+rect['height']+.008,rect['width'],.047 if portrait else .08)
            text('caption-'+str(i),candidate['labels'][i],'media_label',r)
    if rid == 'photo-doodle':
        layers.extend([dict(id='doodle-line',type='line',box=box(.13,.9,.28,.015),color=palette['accent']),
                       dict(id='doodle-dot',type='ellipse',box=box(.81,.895,.035,.025),color=palette['accent'])])
    text('headline', candidate['headline'], 'overlay', title)
    return dict(text_box=title,text_align='left',media=media,
                cover_layers=dict(schema='local.cover_layers.v1',background=palette['background'],
                                  generative_model_used=False,layers=layers))


def build(master_path, out, pipe=w.DEFAULT_PIPE):
    """Validate inputs/layouts first; bind final file contracts in a new directory.

    A late binding failure leaves FAILED.json, never a successful build receipt.
    """
    from PIL import Image
    master_path, out = Path(master_path), Path(out)
    master = w.read(master_path)
    if master.get('schema') != 'self-media.cover-design.v1' or master.get('candidate_only') is not True or master.get('manual_publish_only') is not True:
        raise ValueError('invalid_design_master')
    rp = w.read(w.bound(master['route_plan_ref']))
    brief = rp['brief']
    if rp.get('brief_ref') and w.read(w.bound(rp['brief_ref'])) != brief:
        raise ValueError('brief_drift')
    current = w.plan(brief)
    if current['project_id'] != master['project_id']:
        raise ValueError('design_project_mismatch')
    if not isinstance(master.get('account'),str) or not master['account'].strip():
        raise ValueError('account_required_no_previous_project_default')
    w.bound(master['packaging_ref'])
    safe = w.bound(master['safe_layout_ref']) if master.get('safe_layout_ref') else None
    source_assets = {a['id']:a for a in brief['assets']}
    catalog = {r['id']:r for r in recipes()['recipes']}
    routes = {r['id']:r for r in current['routes']}
    cards = master.get('candidates')
    if not isinstance(cards,list) or not cards or len(cards)>12:
        raise ValueError('one_to_twelve_design_candidates_required')
    w.pipeline_import(pipe)
    from video_creation_pipeline.case_cover_visual_plan import PROFILE_DIMENSIONS
    from video_creation_pipeline.cover_layers import validate_cover_layers, color
    from video_creation_pipeline.typography_gates import build_typography_gate
    profile_ids = {ratio:pid for pid,ratio in w.RATIOS.items() if pid!='youtube_16_9'}
    titles, plans, records, seen, signatures = [], [], [], set(), set()
    for c in cards:
        palette, color_selection = cover_colors.resolve(master, c)
        for key in ('background','foreground','accent'):color(palette[key])
        cid = w.safe_id(c['id'])
        if cid in seen:raise ValueError('duplicate_candidate')
        seen.add(cid)
        recipe = catalog.get(c.get('recipe'))
        if not recipe:raise ValueError('unknown_design_recipe')
        route = routes[recipe['route']]
        if not route['selected'] or route['missing']:raise ValueError('design_route_not_ready')
        for key in ('name','title','headline','hypothesis','composition','strength','risk'):
            if not isinstance(c.get(key),str) or not c[key].strip():raise ValueError('design_field_required: '+key)
        aids = c.get('asset_ids',[])
        if not isinstance(aids,list) or len(set(aids))!=len(aids) or not recipe['min_assets']<=len(aids)<=recipe['max_assets']:
            raise ValueError('recipe_asset_count')
        if any(a not in source_assets for a in aids):raise ValueError('design_asset_unknown')
        selected = [source_assets[aid] for aid in aids]
        if len({a['artifact']['sha256'] for a in selected}) != len(selected):
            raise ValueError('same_asset_not_distinct_story_frames')
        bound_assets = []
        for a in selected:
            if a['kind'] not in recipe['kinds'] or a.get('generated') is not False:
                raise ValueError('non_generated_asset_kind_required')
            path = w.bound(a['artifact'])
            with Image.open(path) as im:
                im.load()
                dimensions = list(im.size)
                if a['kind']=='reviewed_cutout':
                    if 'A' not in im.getbands() or im.getchannel('A').getextrema()[0]==255 or a.get('cutout_reviewed') is not True:
                        raise ValueError('reviewed_transparent_cutout_required')
            if a.get('subject_reviewed') is not True or not isinstance(a.get('protected_regions'),list):raise ValueError('subject_review_required')
            if a['kind']=='evidence' and not a.get('verified_focus'):raise ValueError('verified_evidence_focus_required')
            bound_assets.append(dict(asset_id=a['id'],source_kind='local_image',role='source',availability='available',
                 artifact=a['artifact'],generated=False,use_approved=True,privacy_reviewed=True,external_upload_allowed=False,dimensions=dimensions))
        if recipe['id'] in ('comparison','storyboard'):
            if not isinstance(c.get('labels'),list) or len(c['labels'])!=len(aids) or any(not isinstance(t,str) or not t.strip() for t in c['labels']) or not c.get('relation_basis'):
                raise ValueError('labels_and_relation_basis_required')
        signature=(c['recipe'],tuple(aids),c['headline'],c.get('composition'))
        if signature in signatures:raise ValueError('duplicate_design_variant')
        signatures.add(signature)
        profiles, layouts = [], {}
        for ratio in brief['requested_ratios']:
            pid = profile_ids[ratio];width,height=PROFILE_DIMENSIONS[pid]
            profile=dict(profile_id=pid,width=width,height=height,safe_zone=box(.04,.04,.92,.92))
            profiles.append(profile)
            gate=build_typography_gate(pid,width=width,height=height)
            layouts[pid]=(copy.deepcopy(c['profile_layouts'][pid]) if pid in c.get('profile_layouts',{})
                          else default_layout(recipe,c,selected,profile,palette,gate))
            # Edited master may reflow, but cannot silently replace the headline.
            actual=''.join(x.get('text','') for x in layouts[pid].get('cover_layers',{}).get('layers',[]) if x.get('type')=='text' and x.get('role')=='overlay')
            if ''.join(actual.split())!=''.join(c['headline'].split()):raise ValueError('headline_drift')
            for layer in layouts[pid].get('cover_layers',{}).get('layers',[]):
                if layer.get('type')=='image':
                    original=source_assets.get(layer.get('asset_id'),{})
                    if layer.get('protected_regions') != original.get('protected_regions') or layer.get('subject_reviewed') is not True:
                        raise ValueError('protected_regions_drift_from_reviewed_source')
        if set(c.get('profile_layouts',{}))-set(layouts):raise ValueError('unexpected_profile_layout')
        vp=dict(schema='lucas.case_cover_visual_plan.v1',candidate_only=True,manual_publish_only=True,
            candidate=dict(candidate_id=cid,title=c['title'],overlay_text=c['headline'],strategy='curiosity',promise=c['hypothesis']),
            brand=dict(account=master['account'],palette=palette),
            visual_route=dict(composition_strategy='typography_only' if not aids else 'editorial_metaphor',hero_element_count=min(2,max(1,len(aids))),primary_reading_target=c['headline']),
            assets=bound_assets,profiles=profiles,render_spec=dict(kind='structure',graphic_kind='none',profile_layouts=layouts),
            render_handoff=dict(renderer='existing_remotion_still',new_renderer_created=False))
        validate_cover_layers(vp)
        if color_selection:
            vp['color_selection'] = color_selection
            cover_colors.validate_plan(vp, color_selection)
        titles.append(dict(id=cid,selected=dict(publication_title=c['title'],cover_overlay=[c['headline']])))
        plans.append(vp)
        records.append(dict(id=cid,name=c['name'],route=recipe['route'],title=c['title'],hypothesis=c['hypothesis'],composition=c['composition'],strength=c['strength'],risk=c['risk'],
            design_method=c['recipe'],source_methods=recipe['sources'],generative_model_used=False,
            segmentation_model_used=(True if any(a.get('segmentation_model_used') is True for a in selected)
                 else None if any(a['kind']=='reviewed_cutout' and a.get('segmentation_model_used') is None for a in selected) else False)))
        if color_selection:records[-1]['color_selection'] = color_selection
    if any(p['assets'] for p in plans) and safe is None:raise ValueError('safe_layout_required')
    # Validate geometry/asset contracts before writing final artifacts. The upstream
    # validator binds titles by artifact; title binding is done immediately below.
    if out.exists():raise FileExistsError(out)
    out.mkdir(parents=True)
    try:
        from video_creation_pipeline.contract_io import artifact_reference
        from video_creation_pipeline.case_cover_visual_plan import validate_case_cover_visual_plan
        w.write(out/'title-packages.json',dict(candidate_only=True,manual_publish_only=True,items=titles))
        for vp,record in zip(plans,records):
            vp['title_cover_plan_ref']=artifact_reference(out/'title-packages.json','title packages')
            validate_case_cover_visual_plan(vp,safe_media_layout_path=safe)
            path=out/(record['id']+'.visual-plan.json');w.write(path,vp)
            record['visual_plan_ref']=w.reference(path)
        expanded=copy.deepcopy(master)
        for c,vp in zip(expanded['candidates'],plans):c['profile_layouts']=vp['render_spec']['profile_layouts']
        w.write(out/'editable-master.json',expanded)
        spec=dict(schema='self-media.cover-build.v1',project_id=master['project_id'],route_plan_ref=master['route_plan_ref'],packaging_ref=master['packaging_ref'],
                  candidates=records,design_master_ref=w.reference(out/'editable-master.json'),platform_ratios=master.get('platform_ratios',{}))
        if master.get('strategy_plan_ref'):spec['strategy_plan_ref']=master['strategy_plan_ref']
        if safe:spec['safe_layout_ref']=master['safe_layout_ref']
        w.validate_spec(spec)
        w.write(out/'build.json',spec)
        receipt=dict(schema='self-media.cover-design-build.v1',input_ref=w.reference(master_path),build_ref=w.reference(out/'build.json'),
                     editable_master_ref=spec['design_master_ref'],candidates=len(records),profiles=len(brief['requested_ratios']),
                     renderer='existing_remotion_still',rendered=False,generative_model_used=False,human_quality_approved=False,publish_authorized=False)
        w.write(out/'design-build-receipt.json',receipt)
        return receipt
    except Exception as exc:
        w.write(out/'FAILED.json',dict(status='incomplete_do_not_render',error=str(exc)))
        raise
