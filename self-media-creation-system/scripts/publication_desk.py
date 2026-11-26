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

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_ROOT = Path(__file__).resolve().parent
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

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

    page_bytes=covers.bound(build['page_ref']).read_bytes()

    page=page_bytes.decode('utf8')

    match=re.search(r'<script id="desk-data" type="application/json">(.*?)</script>',page,re.S)

    if not match or json.loads(match[1])!=covers.read(data_path):

        raise ValueError('publication_page_disagrees_with_current_data')

    if any((ROOT/path).read_text(encoding='utf8') not in page for path in ('templates/publication-desk/manual-desk.css','templates/publication-desk/manual-desk.js')):

        raise ValueError('publication_page_did_not_use_current_template')

    delivery_ref=build.get('delivery_manifest_ref')

    package_ref=build.get('package_receipt_ref')

    manifest_path=covers.bound(delivery_ref) if delivery_ref is not None else None

    package_path=covers.bound(package_ref) if package_ref is not None else None

    if page_bytes != render(covers.read(data_path), manifest_path, package_path).encode('utf8'):

        raise PublicationPageBindingError('handwritten_or_unbound_publication_desk: page differs from the official full render')

    return dict(status='current_generated_page',page_ref=build['page_ref'],data_ref=build['data_ref'],

                delivery_manifest_ref=delivery_ref, package_receipt_ref=package_ref,

                delivery_verified=(manifest_path is not None or package_path is not None),

                generation_identity=build['generation_identity'],scope='actual_html_data_template_and_hashes; not human or live-account approval')


class PublicationPageBindingError(ValueError):
    code = 'handwritten_or_unbound_publication_desk'


def verify_delivery_html(html_path, data_path=None, build_path=None):
    """Reject hand-written or unbound HTML desks; require genuine publication_desk.py build receipt + official template."""
    html_file = Path(html_path).resolve(strict=True)
    if html_file.suffix.lower() != '.html':
        raise ValueError('publication_desk_html_required')
    build_file = Path(build_path).resolve() if build_path else html_file.with_suffix('.build.json')
    data_file = Path(data_path).resolve() if data_path else html_file.with_suffix('.data.json')
    if not build_file.is_file() or not data_file.is_file():
        raise PublicationPageBindingError('handwritten_or_unbound_publication_desk: missing companion .build.json or .data.json')
    result = verify_page_build(data_file, build_file)
    import cover_workbench as covers
    if covers.bound(result['page_ref']).resolve() != html_file:
        raise PublicationPageBindingError('handwritten_or_unbound_publication_desk: build receipt points to a different html file')
    return result





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

    values = dict(account=r.get('account',''), video=item.get('video', dict(path='', sha256='')), copy=f,

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
    review_items = []

    def issue(item, key, code, detail):

        issues.append(dict(item_id=item['id'], platform=key, code=code, detail=detail))

    for item in data['items']:

        target = data.get('target_platforms')

        kind = item.get('item_kind', 'video')

        if not target:

            issue(item, '*', 'platform_scope_missing', '请先升级项目并明确本次平台集合')

        elif set(item['platforms']) != set(target):

            issue(item, '*', 'platform_scope_mismatch', '缺少或多出平台：'+', '.join(sorted(set(item['platforms']) ^ set(target))))

        covers = {c['id']: c for c in item.get('covers', [])}

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

            skip_video_covers = (kind in ('article', 'moments_short_post') or (kind == 'graphic_note' and bool(item.get('images')) and not item.get('covers')))

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

            if not skip_video_covers:

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

    if len(data.get('target_platforms', [])) >= 2 and (data.get('fact_consistency_receipt_ref') or data.get('fact_consistency_input_ref')):

        try:

            import cross_platform_fact_consistency_gate as fact_gate

            import cover_workbench as cw

            if data.get('fact_consistency_receipt_ref'):

                fact_gate.validate_receipt(cw.read(cw.bound(data['fact_consistency_receipt_ref'])))

            else:

                receipt = fact_gate.create_receipt(cw.bound(data['fact_consistency_input_ref']))

                fact_gate.validate_receipt(receipt)

        except Exception as error:

            issue(data['items'][0], '*', 'cross_platform_fact_inconsistent', str(error))

    elif len(data.get('target_platforms', [])) >= 2:

        for item in data['items']:

            for code, detail, pkey in _inline_multiplatform_fact_issues(data, item):

                if code == 'cross_platform_fact_inconsistent':
                    review_items.append(dict(item_id=item['id'], platform=pkey, code=code, detail=detail))
                else:
                    issue(item, pkey, code, detail)

    for item in data['items']:

        do_not_infer = data.get('editorial_context', {}).get('do_not_infer', [])

        for key, p in item['platforms'].items():

            for fname, ftext in p['fields'].items():

                if any(term and term in ftext for term in do_not_infer):

                    issue(item, key, 'do_not_infer_violated', f'{key} / {fname}')

    return dict(policy_version=policy['version'], stage=stage, complete=not issues,
                issues=issues, review_items=review_items)


_LABELED_FACT_METRIC_RE = re.compile(
    r'(月入|月薪|年薪|收入|保额|保费|免赔额|赔付|理赔|报销|等待期|住院|手术费|花费|自费)'
    r'\s*(?:约|大概|超|超过|近|不到|仅)?\s*[:：为是]?\s*'
    r'([0-9]+(?:\.[0-9]+)?|[一二两三四五六七八九十百千万]+)\s*(万|千|百|亿)?\s*(元|块|天|年|个月|次|%)?'
)


def _parse_cn_number(s: str) -> float | None:
    s = s.strip()
    try:
        return float(s)
    except ValueError:
        pass
    cn_digits = {'零': 0, '一': 1, '二': 2, '两': 2, '三': 3, '四': 4, '五': 5, '六': 6, '七': 7, '八': 8, '九': 9}
    units = {'十': 10, '百': 100, '千': 1000, '万': 10000, '亿': 100000000}
    if not all(c in cn_digits or c in units for c in s):
        return None
    total = 0
    section = 0
    num = 0
    for c in s:
        if c in cn_digits:
            num = cn_digits[c]
        elif c in units:
            unit_val = units[c]
            if unit_val in (10000, 100000000):
                section = (section + (num or (1 if section == 0 and c == '十' else 0))) * unit_val
                total += section
                section = 0
                num = 0
            else:
                section += (num or (1 if not section else 0)) * unit_val
                num = 0
    section += num
    total += section
    return float(total)


def _normalize_cn_metric(num_str, mag_str, unit_str):
    mag_map = {'百': 100.0, '千': 1000.0, '万': 10000.0, '亿': 100000000.0}
    base = _parse_cn_number(num_str)
    if base is None:
        return f'{num_str}{mag_str or ""}{unit_str or ""}'
    mult = mag_map.get(mag_str or '', 1.0)
    if mag_str and mag_str in num_str:
        mult = 1.0
    unit_norm = '元' if unit_str in ('元', '块', '') else (unit_str or '')
    return f'{round(base * mult, 4)}:{unit_norm}'


def _inline_multiplatform_fact_issues(data, item):
    found = []
    metric_by_label = {}
    canonical_facts = data.get('editorial_context', {}).get('canonical_facts', [])
    for key, p in item['platforms'].items():
        combined = '\n'.join(
            str(p['fields'].get(f, ''))
            for f in ('title', 'short_title', 'body')
            if p['fields'].get(f)
        )
        if not combined.strip():
            continue
        for match in _LABELED_FACT_METRIC_RE.finditer(combined):
            label, num_s, mag_s, unit_s = match.groups()
            norm_val = _normalize_cn_metric(num_s, mag_s, unit_s)
            metric_by_label.setdefault(label, {}).setdefault(key, []).append((norm_val, match.group(0).strip()))
        for fact in canonical_facts:
            if isinstance(fact, dict) and fact.get('required_in_all_platforms') and fact.get('anchor'):
                if fact['anchor'] not in combined:
                    found.append(('canonical_fact_missing', f"missing canonical anchor {fact['anchor']}", key))
    for label, per_platform in metric_by_label.items():
        if len(per_platform) < 2:
            continue
        norm_sets = {pk: {v[0] for v in entries} for pk, entries in per_platform.items()}
        all_unique_vals = set().union(*norm_sets.values())
        if len(all_unique_vals) <= 1:
            continue
        all_sets_identical = all(s == next(iter(norm_sets.values())) for s in norm_sets.values())
        if all_sets_identical:
            continue
        summary = ', '.join(
            f"{pk}={'/'.join(raw for _, raw in entries)}"
            for pk, entries in sorted(per_platform.items())
        )
        found.append(('cross_platform_fact_inconsistent', f'{label} 跨平台数值差异: {summary}', '*'))
    return found


def confirm_platform_copy(data, platform_key, evidence='人工核验通过', checked_at=None, item_id='main'):

    item = next((row for row in data['items'] if row['id'] == item_id), None)

    if item is None or platform_key not in item['platforms']:

        raise ValueError('unknown_item_or_platform: ' + str(platform_key))

    stamped = checked_at or datetime.now(timezone(timedelta(hours=8))).date().isoformat()

    checks = item['platforms'][platform_key].setdefault('platform_checks', {})

    checks['submission'] = dict(

        status='confirmed',

        evidence=evidence,

        checked_at=stamped,

        input_snapshot=platform_check_snapshot(item, platform_key, 'submission'),

    )

    return checks['submission']


def platform_copy_statuses(data, item_id='main'):

    item = next((row for row in data['items'] if row['id'] == item_id), None)

    if item is None:

        raise ValueError('unknown_item: ' + str(item_id))

    statuses = {}

    for key, p in item['platforms'].items():

        check = p.get('platform_checks', {}).get('submission', {})

        if check.get('status') != 'confirmed':

            statuses[key] = 'pending'

        elif check.get('input_snapshot') == platform_check_snapshot(item, key, 'submission'):

            statuses[key] = 'passed'

        else:

            statuses[key] = 'stale'

    return statuses


def platform_lifecycle_stages(data, item_id='main'):

    item = next((row for row in data['items'] if row['id'] == item_id), None)

    if item is None:

        raise ValueError('unknown_item: ' + str(item_id))

    copy_states = platform_copy_statuses(data, item_id=item_id)

    stages = {}

    for key, p in item['platforms'].items():

        rec = p.get('record', {})

        status = rec.get('status', 'prepared')

        if status == 'published' and str(rec.get('published_at', '')).strip():

            stages[key] = 'observed' if rec.get('observed_snapshot_id') else 'manually_published'

        elif status in ('planned', 'scheduled'):

            stages[key] = 'handed_off'

        elif copy_states[key] == 'passed':

            stages[key] = 'packaged'

        else:

            stages[key] = 'validated'

    return stages





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

    elif source.get('schema_version') == 'self-media-platform-publication-package.v2':

        pkg_id = source.get('package_id', 'package-v2')

        video_src = source.get('video', {})

        covers_list = []

        platforms_map = {}

        cover_seq = 0

        for entry in source.get('platforms', []):

            raw_pid = entry['platform_id']

            pid = ALIASES.get(raw_pid, raw_pid)

            if pid not in DESK_PLATFORMS:

                continue

            c_ids = []

            for c in entry.get('covers', []):

                cover_seq += 1

                cid = f'pkg-{pid}-{cover_seq}'

                art = c.get('artifact', {})

                covers_list.append(dict(id=cid, label=c.get('ratio', cid), path=art.get('path', ''), sha256=art.get('expected_sha256', '')))

                c_ids.append(cid)

            fields = dict(

                title=entry.get('title', ''),

                body=entry.get('description', ''),

                tags=' '.join(t if t.startswith('#') else f'#{t}' for t in entry.get('tags', [])),

                collection_name=entry.get('collection_name') or '',

                collection_description=entry.get('collection_description') or '',

            )

            if entry.get('short_title') is not None:

                fields['short_title'] = entry['short_title']

            rec = record()

            if entry.get('scheduled_at'):

                rec.update(status='scheduled', scheduled_for=entry['scheduled_at'])

            post_res = entry.get('post_upload_result')

            if isinstance(post_res, dict) and post_res.get('manual_upload_confirmed') is True:

                rec.update(status='published', published_at=post_res.get('checked_at', ''), url=post_res.get('published_item_ref', ''))

            platforms_map[pid] = dict(fields=fields, cover_ids=c_ids, record=rec)

        first_title = next((p['fields'].get('title', '') for p in platforms_map.values() if p['fields'].get('title')), '') or source.get('content_item_ref', pkg_id)

        data = dict(

            schema_version=SCHEMA,

            project_id=pkg_id,

            title=first_title,

            revision=1,

            rules=[],

            target_platforms=list(platforms_map.keys()),

            source_ref=source_ref,

            source_snapshot=copy.deepcopy(source),

            items=[dict(

                id=source.get('content_item_ref', 'main'),

                title=first_title,

                video=dict(path=video_src.get('path', ''), sha256=video_src.get('expected_sha256', '')),

                covers=covers_list,

                platforms=platforms_map,

            )],

        )

    elif isinstance(source.get('items'), list) and source['items'] and all(('video' in i or 'item_kind' in i) and 'platforms' in i for i in source['items']):

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

        item_kind = item.get('item_kind', 'video')

        if item_kind not in ('video', 'graphic_note', 'article', 'moments_short_post'):

            raise ValueError('invalid_item_kind: ' + str(item_kind))

        assets_to_check = list(item.get('covers', []))

        if item_kind == 'video' or item.get('video') is not None:

            if not isinstance(item.get('video'), dict): raise ValueError('invalid_video_asset')

            assets_to_check.append(item['video'])

        if 'images' in item:

            if not isinstance(item['images'], list): raise ValueError('invalid_images_list')

            assets_to_check.extend(item['images'])

        if item_kind == 'graphic_note' and not item.get('images'):

            raise ValueError('graphic_note_images_required')

        if 'body_html' in item and item['body_html'] is not None:

            if not isinstance(item['body_html'], dict): raise ValueError('invalid_body_html_asset')

            assets_to_check.append(item['body_html'])

        if item_kind == 'article' and not item.get('body_html', {}).get('path'):

            raise ValueError('article_body_html_required')

        for asset in assets_to_check:

            if not isinstance(asset.get('path'),str) or len(asset['path']) > 4096: raise ValueError('invalid_path')

            digest=asset.get('sha256','')

            if digest and (len(digest)!=64 or any(c not in '0123456789abcdef' for c in digest.lower())): raise ValueError('invalid_media_hash')

        cover_ids=[c['id'] for c in item.get('covers', [])]

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

        kind = item.get('item_kind', 'video')

        assets = list(item.get('covers', [])) + list(item.get('images', []))

        if item.get('body_html') and (kind == 'article' or item['body_html'].get('path')):

            assets.append(item['body_html'])

        if item.get('video') and (kind == 'video' or item['video'].get('path')):

            assets.insert(0, item['video'])

        for asset in assets:

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

        kind = item.get('item_kind', 'video')

        pk = item.get('cover_pk', {})

        assets = {c['id']: c for c in item.get('covers', [])}

        candidates = pk.get('candidates', [])

        skip_cover_pk = (kind in ('article', 'moments_short_post') or (kind == 'graphic_note' and bool(item.get('images')) and not item.get('covers'))) and not pk

        if not skip_cover_pk and (not pk or (pk.get('requested') is False and not str(pk.get('not_requested_reason','')).strip())):

            issue(item, 'cover_comparison_scope_missing', '明确是否需要多方案；只迁移既有定稿时记录依据')

        if not skip_cover_pk and pk.get('requested') is not False and len(candidates) < 2:

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
        do_not_infer = data.get('editorial_context', {}).get('do_not_infer', [])

        for key, p in item['platforms'].items():

            for name, text in p['fields'].items():

                if any(term and term in text for term in terms):

                    issue(item, 'forbidden_public_phrase', key+' / '+name)

                if any(term and term in text for term in do_not_infer):

                    issue(item, 'do_not_infer_violated', key+' / '+name)

        for c in candidates:

            if any(term and term in c.get('title', '') for term in terms):

                issue(item, 'forbidden_public_phrase', c['id']+' / title')

            if any(term and term in c.get('title', '') for term in do_not_infer):

                issue(item, 'do_not_infer_violated', c['id']+' / title')

    return dict(complete=not issues, issues=issues, proves_visual_quality=False)





def check_cta(data):

    from cta_review import check_item

    issues, items = [], []

    for item in data['items']:

        try:

            items.append(dict(item_id=item['id'], **check_item(item, data['project_id'])))

        except (OSError, ValueError, KeyError, TypeError) as error:

            issues.append(dict(item_id=item['id'], code='cta_review_pending', detail=str(error)))

    snapshot = [dict(id=i['id'], plan_ref=i.get('cta_plan_ref'), video=i.get('video', dict(path='', sha256='')),

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





PLATFORM_QUOTE_KEYWORDS = {
    'douyin': ('抖音', 'douyin', 'dy'),
    'xiaohongshu': ('小红书', 'xiaohongshu', 'xhs'),
    'weixin_channels': ('微信视频号', '视频号', 'weixin_channels', 'sph'),
    'wechat-article': ('微信公众号', '公众号'),
    'bilibili': ('b站', 'bilibili', '哔哩哔哩'),
    'kuaishou': ('快手', 'ks'),
    'weibo': ('微博', 'wb'),
    'zhihu': ('知乎', 'zh'),
}

_QUOTE_PLATFORM_BY_NAME = {name: key for key, names in PLATFORM_QUOTE_KEYWORDS.items() for name in names}
_QUOTE_PLATFORM_RE = re.compile('|'.join(
    rf'(?<![a-z0-9_]){re.escape(name)}(?![a-z0-9_])' if name.isascii() else re.escape(name)
    for name in sorted(_QUOTE_PLATFORM_BY_NAME, key=len, reverse=True)
))
_QUOTE_SENTENCE_RE = re.compile(r'[^。！？!?\n]+[。！？!?]?')
_QUOTE_CLAUSE_RE = re.compile(r'[^，,；;：:。！？!?\n]+')
_QUOTE_INDEFINITE_RE = re.compile(r'如果|假如|若是|要是|有人说|网传|据说|听说|传闻|以为|是否|了吗|吗\s*[。！？!?]?$')
_QUOTE_PENDING_RE = re.compile(
    r'未发|没发|没有.{0,8}发布|发布失败|定时|预约|排期|待发|草稿|撤回|删了|删掉|删除了|取消发布|已取消|'
    r'稍后|即将|计划|准备|打算|将发布|要发布|今天发|明天|后天|不要发|别发|请[^，,；;]{0,12}(?:发布|上传)|'
    r'\b(?:not|scheduled|schedule|draft|will)\b'
)
_QUOTE_COMPLETED_RE = re.compile(
    r'(?:已(?:经)?|完成)(?:手动)?(?:发布|发出|发帖|发)|(?<!转)(?:发布了|发过了|发了)|'
    r'发布成功|发完了|已上线|\b(?:i|we)\s+(?:have\s+)?published\b'
)


def verify_publication_quote_scope(quote: str, platforms: list[str], source_text: str | None = None,
                                   *, allow_unscoped: bool = False) -> None:
    if not isinstance(platforms, list) or (not platforms and not allow_unscoped):
        raise ValueError('publication_fact_platform_scope_invalid')
    source = quote if source_text is None else source_text
    if not isinstance(source, str) or not isinstance(quote, str) or not quote.strip() or quote not in source:
        raise ValueError('publication_fact_requires_bound_user_message')

    requested = set(platforms)
    sentences = list(_QUOTE_SENTENCE_RE.finditer(source))
    for occurrence in re.finditer(re.escape(quote), source):
        for sentence in sentences:
            if sentence.end() <= occurrence.start():
                continue
            text = sentence[0].lower()
            overlaps = sentence.start() < occurrence.end()
            if overlaps and (text.endswith(('?', '？')) or _QUOTE_INDEFINITE_RE.search(text)):
                raise ValueError('publication_fact_scheduled_not_published: quote is not a completed declaration')
            sentence_mentioned = {_QUOTE_PLATFORM_BY_NAME[m[0]] for m in _QUOTE_PLATFORM_RE.finditer(text)}
            for clause in _QUOTE_CLAUSE_RE.finditer(text):
                if not _QUOTE_PENDING_RE.search(clause[0]):
                    continue
                mentioned = {_QUOTE_PLATFORM_BY_NAME[m[0]] for m in _QUOTE_PLATFORM_RE.finditer(clause[0])}
                if not mentioned and not overlaps:
                    mentioned = sentence_mentioned
                if not requested or not mentioned or requested & mentioned:
                    raise ValueError('publication_fact_scheduled_not_published: quote indicates a pending or cancelled release')

    confirmed = set()
    has_completion = False
    for clause in _QUOTE_CLAUSE_RE.findall(quote.lower()):
        if _QUOTE_PENDING_RE.search(clause) or not _QUOTE_COMPLETED_RE.search(clause):
            continue
        has_completion = True
        mentions = list(_QUOTE_PLATFORM_RE.finditer(clause))
        # Mixed, non-parallel mentions require separate declarations for each platform.
        if all(re.fullmatch(r'\s*(?:和|与|及|以及|、|/|&)\s*', clause[left.end():right.start()])
               for left, right in zip(mentions, mentions[1:])):
            confirmed.update(_QUOTE_PLATFORM_BY_NAME[m[0]] for m in mentions)
    missing = requested - confirmed
    if missing or not has_completion:
        raise ValueError('publication_fact_platform_unconfirmed_in_quote: ' + ','.join(sorted(missing)))


def publication_summary(data):
    """Project facts are distinct from per-platform submission or publish authority."""
    recorded=[key for item in data['items'] for key,p in item['platforms'].items() if p['record']['status']=='published']
    result=dict(status='platform_records' if recorded else 'no_record_supplied',
        platforms=list(dict.fromkeys(recorded)),platform_scope_verified=False,publish_authorized=False)
    ref=data.get('publication_fact_ref')
    if ref is not None:
        import cover_workbench as covers
        fact=covers.read(covers.bound(ref))
        expected_video_sha = (data['items'][0].get('video') or {}).get('sha256', '')
        if (fact.get('schema_version')!='self-media.publication-fact.v1' or fact.get('project_id')!=data['project_id']
                or fact.get('kind')!='user_reported_published' or len(data['items'])!=1
                or fact.get('video_sha256', '')!=expected_video_sha):
            raise ValueError('publication_fact_project_or_media_mismatch')
        source=covers.read(covers.bound(fact['source_ref']))
        quote=fact.get('quote')
        if source.get('role')!='user':
            raise ValueError('publication_fact_requires_bound_user_message')
        platforms=fact.get('platforms',[])
        if not isinstance(platforms,list) or any(key not in data['items'][0]['platforms'] for key in platforms):
            raise ValueError('publication_fact_platform_scope_invalid')
        # Existing project-level reports may have no platform scope.
        verify_publication_quote_scope(quote, platforms, source.get('text', ''), allow_unscoped=True)
        result.update(status='user_reported_published',platforms=platforms,
            video_sha256=fact['video_sha256'],
            source_ref=fact['source_ref'],quote=quote,platform_scope_verified=False,
            note='用户报告已发布；未列明的平台不推定已发，旧平台记录保留')
    return result





def _verify_non_video_package(data, package_receipt):
    import cover_workbench as covers
    if len(data['items']) != 1:
        raise ValueError('package_receipt_requires_single_item_desk')
    item = data['items'][0]
    kind = item.get('item_kind', 'video')
    if kind == 'video':
        raise ValueError('video_desk_requires_delivery_manifest_not_package_receipt')
    assets = inspect_assets(data)
    if not assets or any(r['status'] != 'verified' for r in assets):
        raise ValueError('desk_assets_missing_changed_or_unhashed')
    prep = check_platforms(data, 'preparation')
    if not prep['complete']:
        raise ValueError('platform_requirements_incomplete: ' + json.dumps(prep['issues'], ensure_ascii=False))
    pkg_check = check_packaging(data)
    if not pkg_check['complete']:
        raise ValueError('packaging_requirements_incomplete: ' + json.dumps(pkg_check['issues'], ensure_ascii=False))
    if item.get('cta_plan_ref') or kind == 'video':
        cta_check = check_cta(data)
        if not cta_check['complete']:
            raise ValueError('cta_requirements_incomplete: ' + json.dumps(cta_check['issues'], ensure_ascii=False))
    receipt_path = Path(package_receipt).resolve()
    doc = covers.read(receipt_path)
    def _collect_desk_surface_texts():
        texts = {}
        title = str(item.get('title', '')).strip()
        if title:
            texts['desk_title'] = title
        plat_bits = []
        for plat in (item.get('platforms') or {}).values():
            if isinstance(plat, dict):
                sources = [plat]
                if isinstance(plat.get('fields'), dict):
                    sources.append(plat['fields'])
                for src in sources:
                    for k in ('title', 'caption', 'description', 'body', 'opening_text', 'opening'):
                        if isinstance(src.get(k), str) and src[k].strip():
                            plat_bits.append(src[k].strip())
        if plat_bits:
            texts['desk_platforms'] = '\n'.join(plat_bits)
        card_bits = []
        for card_row in (item.get('graphic_cards') or item.get('cards') or []):
            if isinstance(card_row, dict):
                for k in ('title', 'text', 'caption', 'headline'):
                    if isinstance(card_row.get(k), str) and card_row[k].strip():
                        card_bits.append(card_row[k].strip())
        if card_bits:
            texts['desk_graphic_cards'] = '\n'.join(card_bits)
        return texts
    def _verify_optional_plain_language_refs():
        import plain_language_gate as pl_gate
        surfaces = _collect_desk_surface_texts()
        pl_rev_ref = item.get('plain_language_review_ref') or doc.get('plain_language_review_ref')
        sci_rev_ref = item.get('science_review_ref') or doc.get('science_review_ref')
        trans_rev_ref = item.get('translation_review_ref') or doc.get('translation_review_ref')
        clause_ref = item.get('clause_explanation_ref') or doc.get('clause_explanation_ref')
        fc_ref = item.get('fact_card_ref') or doc.get('fact_card_ref')
        if fc_ref and isinstance(fc_ref, dict) and fc_ref.get('path'):
            expected_cid = (doc.get('content_binding') or {}).get('content_id') or (doc.get('editorial_context') or {}).get('content_id')
            pl_gate.validate_fact_card_lock(pl_gate.resolve_artifact_path(fc_ref['path'], base_dir=receipt_path.parent), expected_content_id=expected_cid, expected_sha256=fc_ref.get('sha256'))
        if sci_rev_ref and isinstance(sci_rev_ref, dict) and sci_rev_ref.get('path'):
            pl_gate.validate_formal_science_review(pl_gate.resolve_artifact_path(sci_rev_ref['path'], base_dir=receipt_path.parent))
        if trans_rev_ref and isinstance(trans_rev_ref, dict) and trans_rev_ref.get('path'):
            pl_gate.validate_formal_translation_review(pl_gate.resolve_artifact_path(trans_rev_ref['path'], base_dir=receipt_path.parent))
        if clause_ref and isinstance(clause_ref, dict) and clause_ref.get('path'):
            clause_errs = pl_gate.validate_clause_explanation(pl_gate.resolve_artifact_path(clause_ref['path'], base_dir=receipt_path.parent))
            if clause_errs:
                raise ValueError('clause_explanation_invalid: ' + '; '.join(clause_errs))
        if pl_rev_ref and isinstance(pl_rev_ref, dict) and pl_rev_ref.get('path'):
            pl_path = pl_gate.resolve_artifact_path(pl_rev_ref['path'], base_dir=receipt_path.parent)
            if pl_rev_ref.get('sha256') and pl_gate.file_sha256(pl_path) != pl_rev_ref['sha256']:
                raise ValueError('plain_language_review_hash_drift')
            pl_gate.validate_review(pl_gate.load_json(pl_path), extra_surface_texts=surfaces, base_dir=pl_path.parent, require_passed=True)
    _verify_optional_plain_language_refs()
    if kind == 'article':
        if doc.get('schema_version') == 'self-media-entry-selection.v1':
            blockers = [m for m in doc.get('missing_inputs', []) if m in {
                'locked_fact_card_for_draft', 'plain_language_plan', 'plain_language_review',
                'serious_content_translation_review', 'science_popularization_review',
                'formal_science_popularization_review', 'insurance_compliance_review',
                'insurance_clause_explanation_review',
            }]
            if blockers:
                raise ValueError('article_package_plain_or_risk_gates_blocked: ' + ','.join(blockers))
        pkg = doc.get('article_review_package') if doc.get('schema_version') == 'self-media-entry-selection.v1' else doc
        if not isinstance(pkg, dict) or pkg.get('rendered_artifacts_verified') is not True:
            raise ValueError('article_package_rendered_verification_required')
        if not (pkg.get('visual_review') or {}).get('record_complete'):
            raise ValueError('article_package_visual_review_required')
        if not (pkg.get('editorial') or {}).get('author_confirmation_recorded'):
            raise ValueError('article_package_author_confirmation_required')
        outputs = pkg.get('rendered_outputs') or []
        if not outputs or outputs[0].get('sha256') != (item.get('body_html') or {}).get('sha256'):
            raise ValueError('article_package_body_html_mismatch')
        return '生成时已通过公众号/长文编辑、内联排版与视觉审核交付检查；请人工核对后手动复制发布。'
    if doc.get('schema_version') == 'content-packaging-review.v1':
        import content_packaging_review
        content_packaging_review.validate_receipt(receipt_path)
        if doc.get('plain_language_review') is not None:
            import plain_language_gate as pl_gate
            pl_info = doc['plain_language_review']
            pl_path = pl_gate.resolve_artifact_path(pl_info['review_ref'], base_dir=receipt_path.parent)
            pl_gate.validate_review(pl_gate.load_json(pl_path), extra_surface_texts=_collect_desk_surface_texts(), base_dir=pl_path.parent, require_passed=True)
        return '生成时已通过图文/短帖内容包装与冻结合同检查；请人工核对后手动复制发布。'
    raise ValueError('unsupported_non_video_package_receipt')


def render(data, delivery_manifest=None, package_receipt=None):

    # Adapt saved data at the actual renderer, not merely at an optional CLI.

    # Source files and input objects stay intact; saved HTML carries the upgrade.

    data = upgrade(data)

    data['publication_summary']=publication_summary(data)

    requirement_report = check_context(data)

    # Rendering a usable draft is not proof of complete media delivery. The only

    # complete route reruns current evidence, including filesystem hashes.

    state = 'draft'

    banner = '草稿预览 · 请勿直接复制用于正式发布（未通过完整交付检查；不代表素材、字幕、封面和人工审核齐备）。'

    if delivery_manifest is not None and package_receipt is not None:

        raise ValueError('choose_either_delivery_manifest_or_package_receipt')

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

        banner = '生成时已通过本地视频交付检查；实际上传与发布以手工操作记录为准。外部文件变化需重新检查，修改此页会使本标记失效。'

    elif package_receipt is not None:

        banner = _verify_non_video_package(data, package_receipt)

        state = 'verified_at_generation'

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
    prep_reviews = preparation['review_items']
    if prep_reviews:
        review_details = '；'.join(item['detail'] for item in prep_reviews)
        banner += f' 待人工复核：{len(prep_reviews)} 项。请对照各平台文案检查同一指标和对象（{review_details}）。'

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

    base_title = data['title'] if data['title'].endswith('发布辅助页') else data['title']+' · 发布辅助页'

    page_title = ('[草稿预览] ' + base_title) if state == 'draft' else base_title

    aside_style = (
        'padding:16px;background:#fff0ee;color:#7a1c14;border-bottom:2px solid #c92a2a;font-weight:600'
        if state == 'draft'
        else 'padding:16px;background:#ecf8f1;color:#124b2c;border-bottom:2px solid #2b8a3e'
    )

    return ('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'

            '<meta name="viewport" content="width=device-width,initial-scale=1">'

            '<title>'+html.escape(page_title)+'</title><style>'+css+'</style></head>'

            '<body><details class="generation-status" open><summary>素材状态与生成检查</summary><aside id="delivery-status" data-state="'+state+'" role="status" '

            'style="'+aside_style+'">'

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


def write_render_bundle(path, data, delivery_manifest=None, package_receipt=None):
    import cover_workbench as covers

    path = Path(path)
    sidecar, build_path = path.with_suffix('.data.json'), path.with_suffix('.build.json')
    if any(p.exists() for p in (path, sidecar, build_path)):
        raise ValueError('render_outputs_must_be_new_including_data_and_build')
    data = upgrade(data)
    data['publication_summary'] = publication_summary(data)
    delivery_ref = covers.reference(delivery_manifest) if delivery_manifest is not None else None
    package_ref = covers.reference(package_receipt) if package_receipt is not None else None
    value = render(data, delivery_manifest, package_receipt)
    if delivery_ref is not None:
        covers.bound(delivery_ref)
    if package_ref is not None:
        covers.bound(package_ref)
    write_new(path, value)
    write_new(sidecar, data)
    build = dict(schema_version='self-media.publication-page-build.v1', data_ref=covers.reference(sidecar),
                 page_ref=covers.reference(path), generation_identity=generation_identity(),
                 delivery_manifest_ref=delivery_ref, package_receipt_ref=package_ref)
    write_new(build_path, build)
    return build


def check_delivery_bundle(data_path, data, build_path, delivery_manifest=None):
    if build_path is None:
        raise ValueError('submission_requires_current_publication_page_build')
    if len(data.get('items', [])) != 1:
        raise ValueError('submission_single_video_desk_required')
    import cover_workbench as covers
    if data != covers.read(data_path):
        raise ValueError('submission_requires_the_exact_built_page_data')
    page = verify_page_build(data_path, build_path)
    if not page['delivery_verified']:
        raise ValueError('submission_requires_full_current_video_delivery')
    if delivery_manifest is not None:
        if covers.reference(delivery_manifest) != page['delivery_manifest_ref']:
            raise ValueError('submission_delivery_manifest_differs_from_page_build')
    return dict(page, video_ref=dict(data['items'][0]['video']))





def main(argv=None):

    p=argparse.ArgumentParser(description=__doc__)

    p.add_argument('action',choices=['init','upgrade','convert','render','check','operations-handoff','restore-archive','verify-html'])

    p.add_argument('--input',type=Path); p.add_argument('--output',type=Path)

    p.add_argument('--project-id'); p.add_argument('--title'); p.add_argument('--platforms', nargs='+')

    p.add_argument('--context-manifest',type=Path,help='Carry the bound existing purpose/feedback context into the actual consumer')

    p.add_argument('--publication-fact',type=Path,help='Bound user-reported publication fact; never assume unspecified platforms')

    p.add_argument('--page-build',type=Path,help='Verify the actual generated page against current data/template/policy')

    p.add_argument('--archive',type=Path);p.add_argument('--archive-sha256');p.add_argument('--data-member');p.add_argument('--output-dir',type=Path)

    p.add_argument('--delivery-manifest',type=Path,help='Recheck full video delivery before marking this page complete')

    p.add_argument('--package-receipt',type=Path,help='Recheck verified graphic-note/article package receipt before marking this page complete')

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

        if args.action == 'verify-html':
            if not args.input:
                raise ValueError('input_required')
            result = verify_delivery_html(args.input, build_path=args.page_build)
            print(json.dumps(result, ensure_ascii=True))
            return 0

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

        value=render(data, args.delivery_manifest, args.package_receipt) if args.action=='render' else operations_handoff(data) if args.action=='operations-handoff' else data

        write_new(args.output,value)

        if args.action=='render':

            import cover_workbench as covers

            write_new(sidecar,data)

            request_id='desk-'+hashlib.sha256(data['project_id'].encode()).hexdigest()[:20]

            current=dict(publication_data=covers.reference(sidecar))

            build=dict(schema_version='self-media.publication-page-build.v1',data_ref=current['publication_data'],

                page_ref=covers.reference(args.output),generation_identity=generation_identity(),

                delivery_manifest_ref=covers.reference(args.delivery_manifest) if args.delivery_manifest else None,

                package_receipt_ref=covers.reference(args.package_receipt) if args.package_receipt else None)

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

        print(json.dumps(dict(status=('complete_local_candidate' if (args.delivery_manifest or args.package_receipt) else 'draft_preview')

                              if args.action=='render' else 'ok',

                              items=len(data['items']),output=str(args.output),publication_performed=False,

                              current_data=str(sidecar) if checkpoint else None,

                              saved_work_request=str(request_path) if checkpoint else None,

                              page_build=str(build_path) if checkpoint else None)))

        return 0

    except (OSError,ValueError,KeyError,TypeError) as e:

        print(json.dumps(dict(status='blocked',code=getattr(e,'code',type(e).__name__),detail=str(e)),ensure_ascii=True)); return 2





if __name__=='__main__': raise SystemExit(main())

