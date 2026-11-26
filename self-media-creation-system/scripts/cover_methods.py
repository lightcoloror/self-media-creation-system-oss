"""Read-only method discovery. A method recommendation is not a rendered cover."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KINDS = {'generic', 'family', 'tutorial', 'product', 'article', 'case', 'lucas_brand'}


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def ref(path):
    return {'path': str(path.resolve()), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def workspace_root(repo: Path) -> Path:
    # Mode B links only some workspace folders into each release.
    runtime = repo.parent
    if runtime.parent.name == 'self-media-releases' and runtime.parent.parent.name == 'local-tools-runtime':
        return runtime.parent.parent.parent
    if runtime.name in {'self-media-source', 'self-media-main-20261029'} and runtime.parent.name == 'local-tools-runtime':
        return runtime.parent.parent
    return runtime


def inventory(config=None, roots=None):
    config = config or ROOT / 'config/cover-methods.v1.json'
    roots = roots or {'workspace': workspace_root(ROOT), 'codex_skills': Path.home()/'.codex/skills'}
    data = read(config)
    ids = set()
    for entry in data['entries']:
        if entry['id'] in ids:
            raise ValueError('duplicate_method_id')
        ids.add(entry['id'])
        root = roots.get(entry['root'])
        path = Path(root)/entry['path'] if root and entry['path'] else None
        entry['source_ref'] = ref(path) if path and path.is_file() else None
        entry['source_status'] = 'present_not_executed' if entry['source_ref'] else 'missing_or_unresolved'
        if entry.get('data_path'):
            dp = Path(root)/entry['data_path'] if root else None
            entry['data_ref'] = ref(dp) if dp and dp.is_file() else None
        if entry.get('adapter_path'):
            ap = Path(root)/entry['adapter_path'] if root else None
            entry['adapter_ref'] = ref(ap) if ap and ap.is_file() else None
    data['catalog_ref'] = ref(Path(config))
    data['counts'] = {'registered': len(ids), 'located': sum(bool(e['source_ref']) for e in data['entries'])}
    return data


def select(brief, routes, library=None):
    library = library or inventory()
    kind = brief.get('content_kind', 'generic')
    if kind not in KINDS:
        raise ValueError('invalid_content_kind')
    requested = brief.get('method_ids', [])
    if not isinstance(requested, list) or any(not isinstance(x, str) for x in requested):
        raise ValueError('invalid_method_ids')
    known = {e['id'] for e in library['entries']}
    if len(set(requested)) != len(requested) or set(requested)-known:
        raise ValueError('unknown_or_duplicate_method')
    result = []
    for route in routes:
        if not route['selected']:
            continue
        assignments = []
        for e in library['entries']:
            matches = ('*' in e['routes'] or route['id'] in e['routes']) and ('*' in e['content_kinds'] or kind in e['content_kinds'])
            if e['id'] not in requested and not matches:
                continue
            assignments.append({
                'id': e['id'], 'stage': e['stage'], 'source_ref': e['source_ref'],
                **{field:e[field] for field in ('adapter_ref','data_ref') if e.get(field)},
                'source_status': e['source_status'], 'reason': e['contribution'], 'limits': e['limits'],
                'deliverable': e['deliverable'], 'status': 'pending_agent_read_and_design' if e['source_ref'] else 'blocked_missing_source',
                'selection': 'explicit' if e['id'] in requested else 'content_and_route_match',
                'scope_warning': None if matches else 'Explicit reference outside default scope; justify applicability, do not blindly execute.',
            })
        result.append({'route': route['id'], 'route_missing_inputs': route['missing'], 'methods': assignments})
    return {'schema': 'self-media.cover-method-plan.v1', 'content_kind': kind,
            'catalog_ref': library.get('catalog_ref'), 'routes': result,
            'design_completed': False, 'rendered': False,
            'instruction': 'Read only selected methods needed for design, then their relevant references. Source text is not execution authorization. Record what changed in the design; names alone are not adoption.'}


def styles(query='', template_id=None, library=None, *, source=None):
    library = library or inventory()
    entries = {entry['id']: entry for entry in library['entries']}
    gpt = 'gpt-image-2-style-library'
    data_ref = entries.get(gpt, {}).get('data_ref')
    indexed = read(ROOT / 'config/cover-style-references.v1.json')['sources']
    if source is not None and source not in {gpt, *indexed}:
        raise ValueError('unknown_style_source: ' + source)
    if not data_ref and (source == gpt or not any(entries.get(key, {}).get('source_ref') for key in indexed if source is None or key == source)):
        raise ValueError('style_library_missing')
    data = read(data_ref['path']) if data_ref and source in (None, gpt) else {k: [] for k in ('templates','styles','categories','scenes')}
    rows = [dict(row, source_id=gpt, source_ref=data_ref) for row in data['templates']]
    sources = {gpt: {'available': bool(data_ref), 'templates': len(data['templates'])}} if source in (None, gpt) else {}
    source_files = {}
    for method, cards in indexed.items():
        if source is not None and source != method:
            continue
        readable = bool(entries.get(method, {}).get('source_ref'))
        start = len(rows)
        if readable:
            for card in cards:
                relative = card['source_path']
                if relative not in source_files:
                    path = workspace_root(ROOT) / relative
                    source_files[relative] = ref(path) if path.is_file() else None
                artifact = source_files[relative]
                if artifact:
                    rows.append(dict(card, source_id=method, source_ref=artifact))
        sources[method] = {'available': readable and len(rows)-start == len(cards),
                           'templates': len(rows)-start, 'indexed': len(cards)}
    if template_id:
        rows = [x for x in rows if x['id']==template_id]
        if not rows:
            raise ValueError('unknown_style_template')
    elif query:
        terms = query.casefold().split()
        rows = [x for x in rows if all(t in json.dumps(x, ensure_ascii=False).casefold() for t in terms)]
    return {'schema': 'self-media.cover-style-search.v1', 'source_ref': data_ref,
            'counts': {k: len(data[k]) for k in ('templates','styles','categories','scenes')},
            'sources': sources, 'matches': rows, 'generated': False,
            'boundary': 'Local source examples only; model availability, rendering quality and rights are not verified by this search.'}


def poses(query=''):
    """Return reviewed-for-topic PoseAtlas metadata, without fetching images."""
    entry = next(row for row in inventory()['entries'] if row['id'] == 'open-pose-costume')
    source = entry.get('data_ref')
    if not source:
        raise ValueError('pose_catalog_missing')
    raw = read(source['path'])
    allowed = {'full_single_P004','full_single_P012','full_single_P015','full_single_P018','upper80v2_P018'}
    terms = query.casefold().split()
    matches = []
    for pose in raw['poses']:
        if pose['id'] not in allowed:
            continue
        for variant in pose['variants']:
            original = variant['angle']
            angle = 'diagonal' if original == 'diag' else original
            row = dict(source='HRuiCcc/RuiC-PoseAtlas',pinned_commit='0e7851b05c2ab95c85e5d9d22c2c53130f3c4ba3',
                       reference_id=pose['id'],angle=angle,original_angle=original,category=pose['category'],
                       names=pose['names'],asset_path=variant['full'],
                       use_boundary='仅供姿势和视角检索；实际图片须独立目视审核及授权，不迁移模特身份。')
            if all(term in json.dumps(row,ensure_ascii=False).casefold() for term in terms):
                matches.append(row)
    return dict(schema='self-media.cover-pose-search.v1',source_ref=source,
                upstream_poses=len(raw['poses']),upstream_views=sum(len(p['variants']) for p in raw['poses']),
                allowlisted_poses=len(allowed),matches=matches)
