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


def inventory(config=None, roots=None):
    config = config or ROOT / 'config/cover-methods.v1.json'
    roots = roots or {'workspace': ROOT.parent, 'codex_skills': ROOT.parent/'optional-skills'}
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


def styles(query='', template_id=None, library=None):
    library = library or inventory()
    entry = next(e for e in library['entries'] if e['id']=='gpt-image-2-style-library')
    if not entry.get('data_ref'):
        raise ValueError('style_library_missing')
    data = read(entry['data_ref']['path'])
    rows = data['templates']
    if template_id:
        rows = [x for x in rows if x['id']==template_id]
        if not rows:
            raise ValueError('unknown_style_template')
    elif query:
        terms = query.casefold().split()
        rows = [x for x in rows if all(t in json.dumps(x, ensure_ascii=False).casefold() for t in terms)]
    return {'schema': 'self-media.cover-style-search.v1', 'source_ref': entry['data_ref'],
            'counts': {k: len(data[k]) for k in ('templates','styles','categories','scenes')},
            'matches': rows, 'generated': False,
            'boundary': 'Local source examples only; model availability, rendering quality and rights are not verified by this search.'}
