"""Reusable offline publication desk. No platform executor or record-store writes."""

from __future__ import annotations

import argparse

import base64

import mimetypes

import copy

import hashlib

import html

import json

import unicodedata

import re

from datetime import datetime, timezone, timedelta

from pathlib import Path



ROOT = Path(__file__).resolve().parents[1]

SCHEMA = 'local-publication-desk.v2'

ALIASES = {'wechat_video': 'weixin_channels', 'wechat_channels': 'weixin_channels'}

STATUSES = {'prepared', 'planned', 'scheduled', 'published'}

DESK_PLATFORMS = ('douyin', 'xiaohongshu', 'weixin_channels', 'kuaishou', 'bilibili', 'weibo')





def platform_policy():

    return json.loads((ROOT/'config/publication-platforms.v1.json').read_text(encoding='utf-8'))





def platform_requirements(key):

    policy = platform_policy()

    profile = policy['platforms'][key]

    return dict(policy['common_checks'], **profile['checks'])





def policy_digest(policy=None):

    """Bind functional content, not only a hand-maintained version label."""

    value = copy.deepcopy(platform_policy() if policy is None else policy)

    for name in ('baseline_source', 'source', 'evidence_status'):

        value.pop(name, None)

    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,

                                     separators=(',', ':')).encode('utf8')).hexdigest()





def generation_identity():

    css=(ROOT/'templates/publication-desk/manual-desk.css').read_text(encoding='utf8')

    js=(ROOT/'templates/publication-desk/manual-desk.js').read_text(encoding='utf8')

    return dict(policy_sha256=policy_digest(),template_sha256=hashlib.sha256((css+js).encode()).hexdigest(),

        renderer_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())





def verify_page_build(data_path,build_path):

    import cover_workbench as covers

    build=covers.read(build_path)

    if build.get('schema_version')!='self-media.publication-page-build.v1':

        raise ValueError('publication_page_build_required')

    if covers.bound(build['data_ref']).resolve()!=Path(data_path).resolve() or build['generation_identity']!=generation_identity():

        raise ValueError('publication_page_build_stale_data_or_consumer')

    page=covers.bound(build['page_ref']).read_text(encoding='utf8')

    match=re.search(r'<script id="desk-data" type="application/json">(.*?)</script>',page,re.S)

    if not match or json.loads(match[1])!=covers.read(data_path):

        raise ValueError('publication_page_disagrees_with_current_data')

    if any((ROOT/path).read_text(encoding='utf8') not in page for path in ('templates/publication-desk/manual-desk.css','templates/publication-desk/manual-desk.js')):

        raise ValueError('publication_page_did_not_use_current_template')

    return dict(status='current_generated_page',page_ref=build['page_ref'],data_ref=build['data_ref'],

                generation_identity=build['generation_identity'],scope='actual_html_data_template_and_hashes; not human or live-account approval')





def check_policy_basis(key, name, policy=None):

    """Same bounded rule projection as manual-desk.js; preserve unaffected checks."""

    policy = platform_policy() if policy is None else policy

    profile = policy['platforms'][key]

    keys = []

    if name == 'current_specs':

        keys = list(profile)

    elif name in ('crop_preview', 'cover_slots', 'cover_pk'):

        keys = ['cover_mode', 'cover_ratios', 'native_cover_test']

    elif name in ('short_title_rules', 'title_restored', 'submission', 'disclosure'):

        keys = ['field_limits', 'short_title', 'short_title_allowed_symbols', 'separate_title', 'copy_mode']

    elif name in ('schedule', 'schedule_change'):

        keys = ['historical_notes']

    result = dict(description=profile.get('checks', {}).get(name, policy['common_checks'].get(name)),

                  dependencies=policy['check_dependencies'][name],

                  profile={k: copy.deepcopy(profile[k]) for k in keys if k in profile})

    if name in ('crop_preview', 'cover_slots', 'cover_pk', 'current_specs'):

        result['ratio_tolerance'] = policy['ratio_tolerance']

    return result





def platform_cover_ids(item, key):

    """Primary cover and PK candidates have distinct roles; include both in checks."""

    p = item['platforms'][key]

    main = p.get('cover_test', {}).get('main_cover_id') if p.get('cover_test', {}).get('requested') else None

    return list(dict.fromkeys(([main] if main else []) + p.get('cover_ids', [])))





def prepare_platforms(data):

    """Populate missing review tasks, never fabricate completed checks or delete content."""

    for item in data['items']:

        for key, p in item['platforms'].items():

            if key not in DESK_PLATFORMS:

                raise ValueError('unsupported_platform: '+key)

            if platform_policy()['platforms'][key]['short_title']:

                p['fields'].setdefault('short_title', '')

            if not platform_policy()['platforms'][key].get('separate_title', True) and not p['fields'].get('title'):

                p['fields'].pop('title', None)

            checks = p.setdefault('platform_checks', {})

            for name in platform_requirements(key):

                checks.setdefault(name, dict(status='pending', evidence='', checked_at=''))

    return data





def platform_check_snapshot(item, key, name):

    """Bind account checks to only the inputs relevant to that check."""

    policy = platform_policy()

    p = item['platforms'][key]

    f, r = p['fields'], p['record']

    assets = {c['id']: c for c in item['covers']}

    candidates = copy.deepcopy(item.get('cover_pk', {}))

    if p.get('cover_test'):

        candidates['platform_cover_test'] = copy.deepcopy(p['cover_test'])

    values = dict(account=r.get('account',''), video=item['video'], copy=f,

        covers=[assets[cid] for cid in platform_cover_ids(item, key)], tags=f.get('tags',''),

        title=f.get('title',''), short_title=f.get('short_title',''),

        collection={k:f.get(k,'') for k in ('collection_name','collection_description')},

        schedule={k:r.get(k,'') for k in ('planned_at','scheduled_for')},

        cover_candidates=candidates)

    return dict(policy_version=policy['version'], platform=key, policy_basis=check_policy_basis(key, name, policy),

                inputs={k:copy.deepcopy(values[k]) for k in policy['check_dependencies'][name]})





def cover_test_plan(item, key, policy=None):

    """Describe parallel creative variants separately from each variant's ratio slots.



    This is a local upload plan, never evidence that an account exposes native PK.

    """

    policy = policy or platform_policy()

    p, pk = item['platforms'][key], item.get('cover_pk', {})

    test = p.get('cover_test', {})

    if not test.get('requested'):

        return None

    if pk.get('selection_mode') != 'parallel_test' or pk.get('selected'):

        raise ValueError('parallel_test_requires_no_selected_winner')

    ids = test.get('candidate_ids', [])

    profile = policy['platforms'][key]

    native = profile.get('native_cover_test', {})

    minimum = native.get('min_candidates', 2)

    if not isinstance(ids, list) or len(ids) < minimum or len(set(ids)) != len(ids):

        raise ValueError('parallel_test_requires_two_or_more_distinct_candidates')

    if native.get('max_candidates') and len(ids) > native['max_candidates']:

        raise ValueError('pk_candidate_limit_exceeded')

    selected = pk.get('test_candidate_ids', [])

    candidates = {c['id']:c for c in pk.get('candidates', [])}

    if any(cid not in candidates or cid not in selected for cid in ids):

        raise ValueError('parallel_test_unknown_or_unselected_candidate')

    ratios = test.get('ratios', [])

    if not isinstance(ratios, list) or not ratios or len(set(ratios)) != len(ratios):

        raise ValueError('parallel_test_ratios_required')

    if any(r not in profile['cover_ratios'] for r in ratios):

        raise ValueError('parallel_test_ratio_not_in_platform_baseline')

    if profile['cover_mode'] == 'one' and len(ratios) != 1:

        raise ValueError('parallel_test_one_ratio_per_variant')

    if profile['cover_mode'] == 'all' and set(ratios) != set(profile['cover_ratios']):

        raise ValueError('parallel_test_variant_missing_ratio_slots')

    assets = {a['id']:a for a in item['covers']}

    variants, expected = [], []

    for cid in ids:

        c = candidates[cid]

        covers = {r:c['cover_by_ratio'].get(r) for r in ratios}

        if any(aid not in assets for aid in covers.values()):

            raise ValueError('parallel_test_variant_asset_missing: '+cid)

        expected.extend(covers.values())

        variants.append(dict(candidate_id=cid, name=c.get('name',cid), covers=covers))

    if len(set(expected)) != len(expected) or p.get('cover_ids', []) != expected:

        raise ValueError('parallel_test_cover_assignment_mismatch')

    result = dict(candidate_ids=ids, ratios=ratios, variants=variants,

                  interface_status=test.get('interface_status','pending'))

    if native.get('layout') == 'main_plus_candidates':

        main = test.get('main_cover_id')

        if main and main not in assets:

            raise ValueError('main_cover_asset_missing')

        if main and (main in expected or any(assets[main].get('sha256') and

                assets[main]['sha256'] == assets[aid].get('sha256') for aid in expected)):

            raise ValueError('main_cover_must_differ_from_pk_candidates')

        result.update(layout='main_plus_candidates', main_cover_id=main or None,

                      max_candidates=native['max_candidates'], total_cover_count=len(expected) + bool(main))

    return result





def apply_cover_test_selection(item, candidate_ids, policy=None, platform_key=None):

    """Bind the author's simultaneous candidates without choosing a winner."""

    policy = policy or platform_policy()

    pk = item['cover_pk']

    ids = list(candidate_ids)

    candidates = {c['id']:c for c in pk.get('candidates', [])}

    minimum = policy['platforms'].get(platform_key, {}).get('native_cover_test', {}).get('min_candidates', 2)

    if len(ids) < minimum or len(set(ids)) != len(ids) or any(cid not in candidates for cid in ids):

        raise ValueError('parallel_test_requires_known_distinct_candidates')

    if platform_key is not None and (platform_key not in item['platforms'] or any(cid not in pk.get('test_candidate_ids',[]) for cid in ids)):

        raise ValueError('parallel_test_platform_subset_invalid')

    updated = copy.deepcopy(item)

    updated['cover_pk'].update(selection_mode='parallel_test', selected=None)

    updated['cover_pk'].pop('selected_at',None)

    if platform_key is None:

        updated['cover_pk']['test_candidate_ids']=ids

    for key, p in updated['platforms'].items():

        if platform_key is not None and key != platform_key:

            continue

        profile = policy['platforms'][key]

        ratios = pk.get('platform_ratios', {}).get(key)

        if not ratios:

            ratios = (['3:4'] if '3:4' in profile['cover_ratios'] else profile['cover_ratios'][:1]) if profile['cover_mode']=='one' else profile['cover_ratios'][:]

        test = p.setdefault('cover_test', {})

        test.update(requested=True, candidate_ids=ids[:], ratios=list(ratios))

        test.setdefault('interface_status','pending')

        test.setdefault('interface_evidence','')

        test.setdefault('checked_at','')

        p['cover_ids'] = [candidates[cid]['cover_by_ratio'].get(r) for cid in ids for r in ratios]

        cover_test_plan(updated, key, policy)

    item.clear();item.update(updated)

    return item





def check_platforms(data, stage='submission'):

    """Fail closed on omitted platform work. Read image geometry, never trust ratio labels."""

    if stage not in ('preparation', 'submission'):

        raise ValueError('invalid_platform_check_stage')

    policy = platform_policy()

    issues = []

    def issue(item, key, code, detail):

        issues.append(dict(item_id=item['id'], platform=key, code=code, detail=detail))

    for item in data['items']:

        target = data.get('target_platforms')

        if not target:

            issue(item, '*', 'platform_scope_missing', '请先升级项目并明确本次平台集合')

        elif set(item['platforms']) != set(target):

            issue(item, '*', 'platform_scope_mismatch', '缺少或多出平台：'+', '.join(sorted(set(item['platforms']) ^ set(target))))

        covers = {c['id']: c for c in item['covers']}

        for key, p in item['platforms'].items():

            profile = policy['platforms'][key]

            testing = p.get('cover_test', {}).get('requested') is True

            test_plan = None

            if testing:

                try:

                    test_plan = cover_test_plan(item, key, policy)

                except (ValueError, KeyError, TypeError) as error:

                    issue(item, key, 'cover_test_plan_invalid', str(error))

                limit = p['cover_test'].get('confirmed_candidate_limit')

                minimum = profile.get('native_cover_test', {}).get('min_candidates', 2)

                if limit is not None and (type(limit) is not int or limit < minimum or (test_plan and limit < len(test_plan['candidate_ids']))):

                    issue(item, key, 'cover_test_candidate_limit', '计划候选数超过已核对名额，或名额记录无效')

                if profile.get('native_cover_test', {}).get('main_required') and not p['cover_test'].get('main_cover_id'):

                    issue(item, key, 'main_cover_required', '请选择1张主封面；主封面不计入最多3张PK候选')

            for field, limit in profile.get('field_limits', {}).items():

                if len(p['fields'].get(field, '')) > limit:

                    issue(item, key, 'baseline_field_too_long', f'{field}: {limit}')

            if profile.get('short_title_allowed_symbols'):

                invalid = [c for c in p['fields'].get('short_title','') if not

                           (c.isspace() or unicodedata.category(c)[0] in 'LN' or c in profile['short_title_allowed_symbols'])]

                if invalid: issue(item, key, 'short_title_symbol_not_allowed', ''.join(invalid))

            required = (['body', 'tags'] if not profile.get('separate_title', True) else ['title', 'body', 'tags']) + (['short_title'] if profile['short_title'] else [])

            if not profile.get('separate_title', True) and p['fields'].get('title'):

                issue(item, key, 'separate_title_not_applicable', '本平台无普通标题字段，请按平台配置填写')

            for field in required:

                if not p['fields'].get(field, '').strip():

                    issue(item, key, 'missing_field', field)

            ratios = []

            for cid in platform_cover_ids(item, key):

                try:

                    from PIL import Image

                    with Image.open(covers[cid]['path']) as im:

                        w, h = im.size

                        im.verify()

                    with Image.open(covers[cid]['path']) as im:

                        im.load()

                    found = next((r for r in profile['cover_ratios']

                                  if abs((w/h)/(int(r.split(':')[0])/int(r.split(':')[1]))-1)

                                  <= policy['ratio_tolerance']), None)

                    if found:

                        ratios.append(found)

                    else:

                        issue(item, key, 'wrong_cover_ratio', f'{cid}: {w}x{h}')

                except (OSError, ValueError, KeyError, ImportError):

                    issue(item, key, 'unreadable_cover_geometry', cid)

            if profile['cover_mode'] == 'unverified':

                issue(item, key, 'platform_profile_unverified', '封面规格尚未核准')

            elif profile['cover_mode'] == 'all' and not set(profile['cover_ratios']) <= set(ratios):

                issue(item, key, 'missing_cover_slots', ', '.join(r for r in profile['cover_ratios'] if r not in ratios))

            elif profile['cover_mode'] == 'one' and not testing and len(p.get('cover_ids', [])) != 1:

                issue(item, key, 'choose_one_cover', '请选择一张适用封面；PK候选另行审核')

            if stage == 'preparation':

                continue

            if testing:

                test = p['cover_test']

                today = datetime.now(timezone(timedelta(hours=8))).date().isoformat()

                if (test.get('interface_status') != 'confirmed' or not str(test.get('interface_evidence','')).strip()

                        or test.get('checked_at') != today):

                    issue(item, key, 'cover_test_interface_pending', '核对当前账号原生封面PK入口、候选名额与实际接收数量；不能把本地计划当已开启')

            for name in platform_requirements(key):

                check = p.get('platform_checks', {}).get(name, {})

                status = check.get('status')

                valid = status == 'confirmed' or (status == 'not_applicable' and name in policy['optional_checks'])

                if not valid or not str(check.get('evidence', '')).strip():

                    issue(item, key, 'platform_check_pending', name)

                elif name == 'current_specs' and check.get('checked_at') != datetime.now(timezone(timedelta(hours=8))).date().isoformat():

                    issue(item, key, 'current_specs_stale', '需记录当日账号界面核验日期 YYYY-MM-DD')

                elif check.get('input_snapshot') != platform_check_snapshot(item,key,name):

                    issue(item, key, 'platform_check_inputs_changed', name+'：当前输入与已核验内容不一致，或旧记录未绑定输入')

    return dict(policy_version=policy['version'], stage=stage, complete=not issues, issues=issues)





def record():

    return dict(status='prepared', account='', planned_at='', scheduled_for='', published_at='', url='', notes='')





def empty_comparison(selected):

    profiles = platform_policy()['platforms']

    return dict(requested=True, candidates=[], recommended='', selected='',

        required_ratios=list(dict.fromkeys(r for k in selected for r in profiles[k]['cover_ratios'])),

        platform_ratios={k: profiles[k]['cover_ratios'][:1] if profiles[k]['cover_mode']=='one'

                         else profiles[k]['cover_ratios'][:] for k in selected})





def new_project(project_id, title, platforms=None):

    """Fresh blank project; never copy another project's facts or publication state."""

    if not project_id or not title:

        raise ValueError('project_id_and_title_required')

    selected = list(platform_policy()['default_platforms'] if platforms is None else platforms)

    selected = [ALIASES.get(k, k) for k in selected]

    if not selected or len(selected) != len(set(selected)) or any(k not in DESK_PLATFORMS for k in selected):

        raise ValueError('invalid_platform_selection')

    data = dict(schema_version=SCHEMA, project_id=project_id, title=title, revision=1, rules=[],

                target_platforms=selected, platform_policy_version=platform_policy()['version'],

                platform_policy_sha256=policy_digest(),

                items=[dict(id='main', title=title, video=dict(path='', sha256=''), covers=[], cover_pk=empty_comparison(selected), cta_plan_ref=None,

                            platforms={k: dict(fields=dict(title='', body='', tags='', collection_name='', collection_description=''), cover_ids=[], record=record())

                                       for k in selected})])

    prepare_platforms(data)

    validate(data)

    return data





def upgrade(source, source_ref='', platforms=None):

    """Migrate a saved project, preserving user text/records and retiring invalid fields."""

    data = normalize(source, source_ref, retire_fields=True)

    policy = platform_policy()

    selected = platforms or data.get('target_platforms') or list(dict.fromkeys(

        policy['default_platforms'] + [k for item in data['items'] for k in item['platforms']]))

    selected = [ALIASES.get(k, k) for k in selected]

    template = new_project(data['project_id'], data['title'], selected)

    for item in data['items']:

        # Dropping a platform with saved work is a separate editorial decision.

        if set(item['platforms']) - set(selected):

            raise ValueError('upgrade_would_drop_saved_platform')

        for key in selected:

            item['platforms'].setdefault(key, copy.deepcopy(template['items'][0]['platforms'][key]))

        for p in item['platforms'].values():

            if data.get('platform_policy_version') != policy['version'] and p.get('platform_checks'):

                p.setdefault('previous_platform_checks', []).append(copy.deepcopy(p['platform_checks']))

                p['platform_checks'] = {k: v for k, v in p['platform_checks'].items() if v.get('status') == 'not_applicable'}

        item.setdefault('cover_pk', empty_comparison(selected))

        item['cover_pk'].setdefault('requested', True)

    data['target_platforms'] = selected

    data['platform_policy_version'] = policy['version']

    prepare_platforms(data)

    for item in data['items']:

        for key,p in item['platforms'].items():

            for name,check in p['platform_checks'].items():

                if name not in policy['check_dependencies'] or check.get('status') not in ('confirmed','not_applicable'):

                    continue

                if check.get('input_snapshot') != platform_check_snapshot(item,key,name):

                    previous={k:copy.deepcopy(v) for k,v in check.items() if k!='previous_evidence'}

                    check.setdefault('previous_evidence',[]).append(previous)

                    check['status']='pending'

                    check.pop('input_snapshot',None)

                    check['invalidated_reason']='相关输入或规则已变化，旧核验仅保留为历史'

    data['platform_policy_sha256'] = policy_digest(policy)

    # A stable current project must not acquire a new revision on every resume.

    if data != source:

        data['revision'] = int(data.get('revision', 0)) + 1

    validate(data)

    return data





def capabilities():

    return dict(available=True, schema_version=SCHEMA,

                actions=['init', 'upgrade', 'convert', 'render', 'check', 'operations-handoff'],

                entrypoint='python scripts/publication_desk.py',

                agent_recipe=str(ROOT / 'docs/publication-desk.md'),

                template_policy='shared_renderer_project_data_only',

                requires_previous_project=False, live_execution=False)





def normalize(source, source_ref='', *, retire_fields=False):

    if source.get('schema_version') == SCHEMA:

        data = copy.deepcopy(source)

    elif source.get('schema_version') == 'local-publication-page-draft.v1':

        name = source.get('content_name', '发布准备')

        covers = ([dict(id='cover', label='封面候选', path=source['assets']['cover_path'], sha256='')]

                  if source['assets'].get('cover_path') else [])

        data = dict(schema_version=SCHEMA, project_id=hashlib.sha256(name.encode()).hexdigest()[:16],

                    title=name, revision=1, rules=[], source_ref=source_ref,

                    items=[dict(id='main', title=name,

                        video=dict(path=source['assets']['video_path'], sha256=source.get('candidate_sha256', '')),

                        covers=covers, platforms={ALIASES.get(k,k): dict(fields=copy.deepcopy(v),

                            cover_ids=['cover'] if covers else [], record=record()) for k,v in source['platforms'].items()})])

    elif isinstance(source.get('items'), list) and source['items'] and all('video' in i and 'platforms' in i for i in source['items']):

        data = dict(schema_version=SCHEMA, project_id=hashlib.sha256(source_ref.encode()).hexdigest()[:16],

                    title=source.get('series', {}).get('name') or '系列发布辅助页', revision=1,

                    source_ref=source_ref, source_snapshot=copy.deepcopy(source),

                    rules=[dict(platform=ALIASES.get(k,k), source=source_ref,

                                checked_at=source.get('modified_at', source.get('generated_at','')),

                                scope='历史项目账号界面；使用前复核', status='historical_needs_recheck', values=v)

                           for k,v in source.get('platform_capabilities', {}).items()], items=[])

        for old in source['items']:

            item = dict(id=old['id'], title=old.get('titles', {}).get('short', old['id']),

                        video=copy.deepcopy(old['video']), covers=[], platforms={})

            for ratio, cover in old.get('covers', {}).items():

                item['covers'].append(dict(id=ratio, label=ratio+' 封面', **copy.deepcopy(cover)))

            for key, value in old['platforms'].items():

                fields = dict(title=value.get('title',''), body=value.get('caption',''),

                              tags=(' '.join('#'+t for t in value['topic_candidates']) if 'topic_candidates' in value

                                    else ','.join(value.get('tags',[]))))

                if 'short_title' in value: fields['short_title'] = value['short_title']

                if old.get('pinned_comment'): fields['pinned_comment'] = old['pinned_comment']

                collection = source.get('collection',{}).get('platform_variants',{}).get(key,{})

                for src, dst in [('name','collection_name'), ('description','collection_description')]:

                    if collection.get(src): fields[dst] = collection[src]

                item['platforms'][ALIASES.get(key,key)] = dict(fields=fields,

                    cover_ids=value.get('cover_ratios', [value['cover_ratio']] if value.get('cover_ratio') else []), record=record())

            data['items'].append(item)

    else:

        raise ValueError('unsupported_desk_source')

    if retire_fields:

        for item in data['items']:

            for key, p in item['platforms'].items():

                profile = platform_policy()['platforms'][key]

                for field in (['title'] if not profile.get('separate_title', True) else []) + ([] if profile['short_title'] else ['short_title']):

                    if field in p['fields']:

                        p.setdefault('retired_fields', {})[field] = p['fields'].pop(field)

    validate(data)

    return data





def validate(data):

    if data.get('schema_version') != SCHEMA or not isinstance(data.get('title'),str): raise ValueError('invalid_desk')

    if not isinstance(data.get('project_id'),str) or not data['project_id']: raise ValueError('project_id_required')

    terms=data.get('editorial_context',{}).get('forbidden_public_phrases',[])

    if not isinstance(terms,list) or any(not isinstance(t,str) or not t.strip() for t in terms):

        raise ValueError('invalid_forbidden_public_phrases')

    if 'target_platforms' in data:

        target = data['target_platforms']

        if not isinstance(target, list) or not target or len(target)!=len(set(target)) or any(k not in DESK_PLATFORMS for k in target):

            raise ValueError('invalid_target_platforms')

    items = data.get('items')

    if not isinstance(items,list) or not 1 <= len(items) <= 200: raise ValueError('invalid_items')

    ids=set()

    for item in items:

        if not isinstance(item.get('id'),str) or item['id'] in ids: raise ValueError('duplicate_or_invalid_item_id')

        ids.add(item['id'])

        if not isinstance(item.get('title'),str): raise ValueError('item_title_required')

        pk=item.get('cover_pk')

        if pk is not None:

            if not isinstance(pk,dict) or ('requested' in pk and not isinstance(pk['requested'],bool)):

                raise ValueError('invalid_cover_comparison')

            candidates=pk.get('candidates',[])

            if not isinstance(candidates,list) or any(not isinstance(c,dict) or not isinstance(c.get('id'),str)

                    or not isinstance(c.get('cover_by_ratio',{}),dict) for c in candidates):

                raise ValueError('invalid_cover_candidates')

            ratios=pk.get('required_ratios',[])

            if not isinstance(ratios,list) or any(not isinstance(r,str) or r not in ('3:4','4:3','9:16','16:9','1:1') for r in ratios):

                raise ValueError('invalid_cover_ratios')

            if pk.get('selection_mode','single') not in ('single','parallel_test'):

                raise ValueError('invalid_cover_selection_mode')

            test_ids=pk.get('test_candidate_ids',[])

            if not isinstance(test_ids,list) or any(not isinstance(cid,str) for cid in test_ids):

                raise ValueError('invalid_cover_test_candidates')

        for asset in [item['video'], *item['covers']]:

            if not isinstance(asset.get('path'),str) or len(asset['path']) > 4096: raise ValueError('invalid_path')

            digest=asset.get('sha256','')

            if digest and (len(digest)!=64 or any(c not in '0123456789abcdef' for c in digest.lower())): raise ValueError('invalid_media_hash')

        cover_ids=[c['id'] for c in item['covers']]

        if len(cover_ids)!=len(set(cover_ids)): raise ValueError('duplicate_cover_id')

        if not isinstance(item.get('platforms'),dict) or not item['platforms']: raise ValueError('platforms_required')

        for key, platform in item['platforms'].items():

            if key not in DESK_PLATFORMS: raise ValueError('unsupported_platform: '+key)

            test=platform.get('cover_test')

            if test is not None and (not isinstance(test,dict) or not isinstance(test.get('requested',False),bool)):

                raise ValueError('invalid_platform_cover_test')

            if test and 'main_cover_id' in test and (not isinstance(test['main_cover_id'], str) or

                    (test['main_cover_id'] and test['main_cover_id'] not in cover_ids)):

                raise ValueError('invalid_main_cover_reference')

            fields=platform['fields']

            if key != 'weixin_channels' and 'short_title' in fields:

                raise ValueError('short_title_not_applicable: '+key)

            required_fields = ['body','tags'] if not platform_policy()['platforms'][key].get('separate_title', True) else ['title','body','tags']

            if not all(k in fields for k in required_fields): raise ValueError('missing_fields')

            if not all(isinstance(v,str) and len(v)<=20000 for v in fields.values()): raise ValueError('invalid_text')

            if any(c not in cover_ids for c in platform.get('cover_ids',[])): raise ValueError('unknown_cover')

            r=platform['record']

            if r.get('status') not in STATUSES: raise ValueError('invalid_publication_status')

            if not all(isinstance(r.get(k,''),str) for k in record()): raise ValueError('invalid_record')





def inspect_assets(data):

    result=[]

    for item in data['items']:

        for asset in [item['video'], *item['covers']]:

            path=Path(asset['path']); status='missing'

            if path.is_file():

                if asset.get('sha256'):

                    h=hashlib.sha256()

                    with path.open('rb') as f:

                        for chunk in iter(lambda:f.read(1024*1024),b''): h.update(chunk)

                    status='verified' if h.hexdigest()==asset['sha256'].lower() else 'hash_mismatch'

                else: status='exists_hash_not_supplied'

            result.append(dict(item_id=item['id'],path=asset['path'],status=status))

    return result





def check_packaging(data):

    """Check requested comparisons, actual images and literal packaging constraints."""

    issues = []

    def issue(item, code, detail):

        issues.append(dict(item_id=item['id'], platform='*', code=code, detail=detail))

    for item in data['items']:

        pk = item.get('cover_pk', {})

        assets = {c['id']: c for c in item['covers']}

        candidates = pk.get('candidates', [])

        if not pk or (pk.get('requested') is False and not str(pk.get('not_requested_reason','')).strip()):

            issue(item, 'cover_comparison_scope_missing', '明确是否需要多方案；只迁移既有定稿时记录依据')

        if pk.get('requested') is not False and len(candidates) < 2:

            issue(item, 'cover_comparison_missing', '已要求多方案比较；同一设计的多个比例不算多个创意')

        if candidates:

            needed = {r for k in item['platforms'] for r in platform_policy()['platforms'][k]['cover_ratios']

                      if platform_policy()['platforms'][k]['cover_mode']=='all'}

            if not pk.get('required_ratios') or not needed <= set(pk['required_ratios']):

                issue(item, 'cover_comparison_ratios_missing', '候选比较缺少目标平台比例')

            ids = [c['id'] for c in candidates]

            if len(set(ids)) != len(ids):

                issue(item, 'cover_candidate_duplicate', '候选编号重复')

            for role in ('recommended', 'selected'):

                if pk.get(role) and pk[role] not in ids:

                    issue(item, 'cover_choice_missing', role)

            seen = {}

            for c in candidates:

                if not c.get('title') or not (c.get('hypothesis') or c.get('selection_reason')):

                    issue(item, 'cover_comparison_reason_missing', c['id'])

                for ratio in pk.get('required_ratios', []):

                    asset = assets.get(c.get('cover_by_ratio', {}).get(ratio))

                    if not asset:

                        issue(item, 'cover_candidate_ratio_missing', c['id']+' / '+ratio)

                        continue

                    try:

                        import cover_strategy

                        cover_strategy._check_image(asset, ratio)

                        identity = (ratio, asset['sha256'])

                        if identity in seen and seen[identity] != c['id']:

                            issue(item, 'cover_candidate_same_image', seen[identity]+' / '+c['id'])

                        seen[identity] = c['id']

                    except (ValueError, OSError, KeyError, ImportError) as error:

                        issue(item, 'cover_candidate_image_invalid', c['id']+' / '+ratio+': '+str(error))

        terms = data.get('editorial_context', {}).get('forbidden_public_phrases', [])

        for key, p in item['platforms'].items():

            for name, text in p['fields'].items():

                if any(term and term in text for term in terms):

                    issue(item, 'forbidden_public_phrase', key+' / '+name)

        for c in candidates:

            if any(term and term in c.get('title', '') for term in terms):

                issue(item, 'forbidden_public_phrase', c['id']+' / title')

    return dict(complete=not issues, issues=issues, proves_visual_quality=False)





def check_cta(data):

    from cta_review import check_item

    issues, items = [], []

    for item in data['items']:

        try:

            items.append(dict(item_id=item['id'], **check_item(item, data['project_id'])))

        except (OSError, ValueError, KeyError, TypeError) as error:

            issues.append(dict(item_id=item['id'], code='cta_review_pending', detail=str(error)))

    snapshot = [dict(id=i['id'], plan_ref=i.get('cta_plan_ref'), video=i['video'],

                     fields={k:p['fields'] for k,p in i['platforms'].items()}) for i in data['items']]

    return dict(complete=not issues, issues=issues, items=items, input_snapshot=snapshot)





def check_context(data):

    import purpose_continuity

    return purpose_continuity.check_consumer(data.get('context_manifest_ref'), 'publication_desk', data)





def bind_context(data,path):

    import purpose_continuity as purpose

    import cover_workbench as covers

    new=covers.reference(path)

    old=data.get('context_manifest_ref')

    if old and old!=new:

        purpose.check_transition(purpose.validate_context(covers.bound(old)),purpose.validate_context(path))

    data['context_manifest_ref']=new

    return check_context(data)





def publication_summary(data):

    """Project facts are distinct from per-platform submission or publish authority."""

    recorded=[key for item in data['items'] for key,p in item['platforms'].items() if p['record']['status']=='published']

    result=dict(status='platform_records' if recorded else 'no_record_supplied',

        platforms=list(dict.fromkeys(recorded)),platform_scope_verified=False,publish_authorized=False)

    ref=data.get('publication_fact_ref')

    if ref is not None:

        import cover_workbench as covers

        fact=covers.read(covers.bound(ref))

        if (fact.get('schema_version')!='self-media.publication-fact.v1' or fact.get('project_id')!=data['project_id']

                or fact.get('kind')!='user_reported_published' or len(data['items'])!=1

                or fact.get('video_sha256')!=data['items'][0]['video'].get('sha256')):

            raise ValueError('publication_fact_project_or_media_mismatch')

        source=covers.read(covers.bound(fact['source_ref']))

        quote=fact.get('quote')

        if source.get('role')!='user' or not isinstance(quote,str) or not quote.strip() or quote not in source.get('text',''):

            raise ValueError('publication_fact_requires_bound_user_message')

        platforms=fact.get('platforms',[])

        if not isinstance(platforms,list) or any(key not in data['items'][0]['platforms'] for key in platforms):

            raise ValueError('publication_fact_platform_scope_invalid')

        result.update(status='user_reported_published',platforms=platforms,

            video_sha256=fact['video_sha256'],

            source_ref=fact['source_ref'],quote=quote,platform_scope_verified=False,

            note='用户报告已发布；未列明的平台不推定已发，旧平台记录保留')

    return result





def render(data, delivery_manifest=None):

    # Adapt saved data at the actual renderer, not merely at an optional CLI.

    # Source files and input objects stay intact; saved HTML carries the upgrade.

    data = upgrade(data)

    data['publication_summary']=publication_summary(data)

    requirement_report = check_context(data)

    # Rendering a usable draft is not proof of complete media delivery. The only

    # complete route reruns current evidence, including filesystem hashes.

    state = 'draft'

    banner = '草稿预览 · 未通过完整视频交付检查；不代表素材、字幕、封面和人工审核齐备。'

    if delivery_manifest is not None:

        import video_delivery

        manifest = video_delivery.covers.read(delivery_manifest)

        declared=upgrade(video_delivery.read_ref(manifest['desk_ref']))

        declared['publication_summary']=publication_summary(declared)

        if declared != data:

            raise ValueError('delivery_manifest_desk_mismatch')

        report = video_delivery.audit(delivery_manifest)

        if not report['complete']:

            raise ValueError('video_delivery_blocked: ' + report['next_action'])

        state = 'verified_at_generation'

        banner = '生成时已通过本地视频交付检查；实际上传与发布以记录为准。外部文件变化需重新检查，修改此页会使本标记失效。'

    else:

        assets = inspect_assets(data)

        pending = sum(r['status'] != 'verified' for r in assets)

        banner += f' 素材待核验：{pending} 项。'

    platform_report = check_platforms(data)

    preparation = check_platforms(data, 'preparation')

    packaging = check_packaging(data)

    cta = check_cta(data)
    banner += (' CTA选择/位置已复核；允许有理由地不采用。' if cta['complete'] else ' CTA选择/位置复核待完成。')

    banner += (' 本地平台适配检查通过（按已记录规则）。' if preparation['complete'] else f" 本地适配缺项：{len(preparation['issues'])} 项。")

    banner += (' 用户已报告发布，平台范围及链接待核对；本地旧记录保留。' if data['publication_summary']['status']=='user_reported_published'

        else ' 上传界面确认与本地适配分开记录；本页不执行上传或发布。')

    encoded=json.dumps(data,ensure_ascii=False).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')

    css=(ROOT/'templates/publication-desk/manual-desk.css').read_text(encoding='utf-8')

    js=(ROOT/'templates/publication-desk/manual-desk.js').read_text(encoding='utf-8')

    public_policy = platform_policy()

    public_policy.pop('baseline_source', None)  # local provenance path is not another project's page content

    previews = {}

    for item in data['items']:

        for cover in item['covers']:

            path = Path(cover['path'])

            mime = mimetypes.guess_type(str(path))[0]

            if path.is_file() and mime in ('image/png','image/jpeg','image/webp') and path.stat().st_size <= 32*1024*1024:

                try:

                    from PIL import Image

                    raw = path.read_bytes()

                    digest = hashlib.sha256(raw).hexdigest()

                    if cover.get('sha256') and cover['sha256'].lower() != digest:

                        continue

                    with Image.open(path) as image:

                        image.verify()

                    with Image.open(path) as image:

                        image.load()

                        width, height = image.size

                    previews[cover['path']] = dict(data_url='data:'+mime+';base64,'+base64.b64encode(raw).decode('ascii'),

                        sha256=digest, width=width, height=height)

                except (OSError, ValueError, ImportError):

                    continue

    build = dict(revision=data.get('revision'), policy_version=public_policy['version'], policy_sha256=policy_digest(public_policy),

                 data_sha256=hashlib.sha256(encoded.encode()).hexdigest(),

                 template_sha256=hashlib.sha256((css+js).encode()).hexdigest(),

                 preparation=preparation, packaging=packaging, cta=cta, requirement_report=requirement_report)

    return ('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'

            '<meta name="viewport" content="width=device-width,initial-scale=1">'

            '<title>'+html.escape(data['title'] if data['title'].endswith('发布辅助页') else data['title']+' · 发布辅助页')+'</title><style>'+css+'</style></head>'

            '<body><details class="generation-status"><summary>素材状态与生成检查</summary><aside id="delivery-status" data-state="'+state+'" role="status" '

            'style="padding:16px;background:#fff4d6;color:#332600;border-bottom:2px solid #b58023">'

            +html.escape(banner)+'</aside></details><div id="desk"></div><script id="desk-data" type="application/json">'+encoded+

            '</script><script id="platform-policy" type="application/json">'

            +json.dumps(public_policy, ensure_ascii=False).replace('<', '\\u003c')

            +'</script><script id="cover-previews" type="application/json">'

            +json.dumps(previews,ensure_ascii=False).replace('<','\\u003c')

            +'</script><script id="desk-build" type="application/json">'

            +json.dumps(build,ensure_ascii=False).replace('<','\\u003c')

            +'</script><script>'+js+'</script></body></html>')





def operations_handoff(data):

    """Export observations, not fabricated canonical publication events."""

    entries=[]

    for item in data['items']:

        for key,p in item['platforms'].items():

            r=p['record']

            if r['status']=='prepared': continue

            missing=[]

            if r['status']=='published':

                missing=[k for k in ['account','published_at','url'] if not r.get(k)]

                missing += ['canonical_source_objects','data_classification','privacy_review_if_required']

            entries.append(dict(item_id=item['id'], platform=key, record=copy.deepcopy(r),

                route='content_operations_cycle.record-publication' if r['status']=='published' else 'publication_package_schedule_only',

                missing_fields=missing, executable=False))

    return dict(schema_version='publication-desk.operations-handoff.v1', project_id=data['project_id'],

                publication_events_written=False, entries=entries, entrypoint='python scripts/self_media_agent.py operations')





def write_new(path, value):

    path.parent.mkdir(parents=True,exist_ok=True)

    with path.open('x',encoding='utf-8',newline='\n') as f:

        f.write(value if isinstance(value,str) else json.dumps(value,ensure_ascii=False,indent=2)+'\n')





def main(argv=None):

    p=argparse.ArgumentParser(description=__doc__)

    p.add_argument('action',choices=['init','upgrade','convert','render','check','operations-handoff','restore-archive'])

    p.add_argument('--input',type=Path); p.add_argument('--output',type=Path)

    p.add_argument('--project-id'); p.add_argument('--title'); p.add_argument('--platforms', nargs='+')

    p.add_argument('--context-manifest',type=Path,help='Carry the bound existing purpose/feedback context into the actual consumer')

    p.add_argument('--publication-fact',type=Path,help='Bound user-reported publication fact; never assume unspecified platforms')

    p.add_argument('--page-build',type=Path,help='Verify the actual generated page against current data/template/policy')

    p.add_argument('--archive',type=Path);p.add_argument('--archive-sha256');p.add_argument('--data-member');p.add_argument('--output-dir',type=Path)

    p.add_argument('--delivery-manifest',type=Path,help='Recheck full video delivery before marking this page complete')

    p.add_argument('--stage',choices=['preparation','submission'],default='submission',help='Check local adaptation separately from actual upload UI checks')

    args=p.parse_args(argv)

    try:

        if args.action == 'restore-archive':

            if not args.archive or not args.archive_sha256 or not args.data_member or not args.output_dir:

                raise ValueError('bound_archive_data_member_and_new_output_directory_required')

            import archive_workflow, artifact_lifecycle

            result=archive_workflow.restore_publication(artifact_lifecycle,

                dict(path=str(args.archive.resolve()),sha256=args.archive_sha256),args.data_member,args.output_dir)

            print(json.dumps(result,ensure_ascii=True));return 0

        if args.action == 'init':

            if args.input or not args.output: raise ValueError('init_requires_new_output_not_input')

            data = new_project(args.project_id, args.title, args.platforms)

            write_new(args.output, data)

            print(json.dumps(dict(status='template_created', items=1, output=str(args.output),

                                  requires_project_content=True, publication_performed=False)))

            return 0

        if not args.input: raise ValueError('input_required')

        if args.action == 'upgrade':

            if not args.output: raise ValueError('output_required')

            data = upgrade(json.loads(args.input.read_text(encoding='utf-8-sig')),str(args.input.resolve()),args.platforms)

            if args.context_manifest:

                bind_context(data,args.context_manifest)

            if args.publication_fact:

                import cover_workbench as covers

                data['publication_fact_ref']=covers.reference(args.publication_fact)

                data['publication_summary']=publication_summary(data)

            write_new(args.output,data)

            print(json.dumps(dict(status='project_upgraded_pending_checks',output=str(args.output),publication_performed=False)))

            return 0

        data=normalize(json.loads(args.input.read_text(encoding='utf-8-sig')),str(args.input.resolve()))

        if args.context_manifest:

            bind_context(data,args.context_manifest)

        if args.publication_fact:

            import cover_workbench as covers

            data['publication_fact_ref']=covers.reference(args.publication_fact)

        data['publication_summary']=publication_summary(data)

        requirement_report=check_context(data)

        if args.action=='check':

            rows=inspect_assets(data)

            platforms=check_platforms(data,args.stage)

            packaging=check_packaging(data)

            cta=check_cta(data)

            page_report=verify_page_build(args.input,args.page_build) if args.page_build else None

            report=dict(status='ok' if platforms['complete'] and packaging['complete'] and cta['complete'] and all(r['status']=='verified' for r in rows) else 'needs_attention', assets=rows, platforms=platforms, packaging=packaging, cta=cta, requirement_report=requirement_report,

                generated_page=page_report,page_verified=page_report is not None)

            if args.output: write_new(args.output,report)

            print(json.dumps(report,ensure_ascii=True)); return 0 if report['status']=='ok' else 2

        if not args.output: raise ValueError('output_required')

        checkpoint = None

        if args.action=='render':

            # The actual generated page and recovery request share the upgraded

            # data; callers do not have to remember an extra migration step.

            data=upgrade(data)

            data['publication_summary']=publication_summary(data)

            sidecar=args.output.with_suffix('.data.json')

            request_path=args.output.with_suffix('.work-request.json')

            build_path=args.output.with_suffix('.build.json')

            if any(path.exists() for path in (args.output,sidecar,request_path,build_path)):

                raise ValueError('render_outputs_must_be_new_including_data_and_checkpoint')

            # Validate the checkpoint contract before creating any output. Real

            # hashes are substituted only after the corresponding file is saved.

            import cover_workbench as covers

            request_id='desk-'+hashlib.sha256(data['project_id'].encode()).hexdigest()[:20]

            if data.get('context_manifest_ref'):

                request_id=covers.read(covers.bound(data['context_manifest_ref']))['task_id']

            draft_current=dict(publication_data=dict(path=str(sidecar.resolve()),sha256='0'*64),

                publication_page_build=dict(path=str(build_path.resolve()),sha256='0'*64))

            if data.get('context_manifest_ref'):draft_current['context_manifest']=data['context_manifest_ref']

            checkpoint=dict(schema_version='self-media-work-request.v1',request_id=request_id,

                requested_output='publication_page',selection_basis='Resume the actual generated desk; no publication authority.',current=draft_current)

            from jsonschema import Draft202012Validator

            errors=list(Draft202012Validator(json.loads((ROOT/'schemas/self-media-work-request.v1.schema.json').read_text(encoding='utf8'))).iter_errors(checkpoint))

            if errors:raise ValueError('render_checkpoint_invalid: '+errors[0].message)

        value=render(data, args.delivery_manifest) if args.action=='render' else operations_handoff(data) if args.action=='operations-handoff' else data

        write_new(args.output,value)

        if args.action=='render':

            import cover_workbench as covers

            write_new(sidecar,data)

            request_id='desk-'+hashlib.sha256(data['project_id'].encode()).hexdigest()[:20]

            current=dict(publication_data=covers.reference(sidecar))

            build=dict(schema_version='self-media.publication-page-build.v1',data_ref=current['publication_data'],

                page_ref=covers.reference(args.output),generation_identity=generation_identity())

            write_new(build_path,build)

            current['publication_page_build']=covers.reference(build_path)

            if data.get('context_manifest_ref'):

                current['context_manifest']=data['context_manifest_ref']

                request_id=covers.read(covers.bound(data['context_manifest_ref']))['task_id']

            checkpoint=dict(schema_version='self-media-work-request.v1',request_id=request_id,

                requested_output='publication_page',selection_basis='Resume this actual generated desk and preserve its current authored data; no upload or publication authority.',

                current=current)

            from jsonschema import Draft202012Validator

            Draft202012Validator(json.loads((ROOT/'schemas/self-media-work-request.v1.schema.json').read_text(encoding='utf8'))).validate(checkpoint)

            write_new(request_path,checkpoint)

        print(json.dumps(dict(status=('complete_local_candidate' if args.delivery_manifest else 'draft_preview')

                              if args.action=='render' else 'ok',

                              items=len(data['items']),output=str(args.output),publication_performed=False,

                              current_data=str(sidecar) if checkpoint else None,

                              saved_work_request=str(request_path) if checkpoint else None,

                              page_build=str(build_path) if checkpoint else None)))

        return 0

    except (OSError,ValueError,KeyError,TypeError) as e:

        print(json.dumps(dict(status='blocked',code=getattr(e,'code',type(e).__name__),detail=str(e)),ensure_ascii=True)); return 2





if __name__=='__main__': raise SystemExit(main())

