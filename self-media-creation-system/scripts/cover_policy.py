"""Check cover text and preview/final coverage without rendering or publishing."""

import unicodedata
from collections import Counter


FINAL_RATIOS = ('3:4', '9:16', '4:3', '16:9')


def check_ratios(stage, ratios):
    if not isinstance(ratios, (list, tuple)) or any(r not in FINAL_RATIOS for r in ratios):
        raise ValueError('invalid_cover_ratios')
    if len(ratios) != len(set(ratios)):
        raise ValueError('duplicate_cover_ratio')
    if stage == 'preview':
        if not 1 <= len(ratios) <= 2:
            raise ValueError('preview_requires_one_or_two_ratios_per_style')
    elif stage == 'final':
        if set(ratios) != set(FINAL_RATIOS):
            missing = [r for r in FINAL_RATIOS if r not in ratios]
            raise ValueError('final_requires_four_cover_ratios: missing ' + ', '.join(missing))
    else:
        raise ValueError('invalid_cover_stage')


def text_key(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError('cover_text_must_be_nonempty')
    return ''.join(unicodedata.normalize('NFKC', value).casefold().split())


def validate_labels(labels):
    if not isinstance(labels, dict):
        raise ValueError('cover_approved_labels_must_be_text_to_reason')
    keys = set()
    for text, reason in labels.items():
        key = text_key(text)
        text_key(reason)
        if key in keys:
            raise ValueError('duplicate_cover_approved_label: ' + text)
        keys.add(key)
    return keys


def check_text(observed, headline, approved_labels, *, context):
    """Observed entries are semantic text groups, not line breaks or metadata."""
    if not isinstance(observed, list) or not observed:
        raise ValueError('cover_visible_text_review_required: ' + context)
    headline_key = text_key(headline)
    approved = validate_labels(approved_labels)
    seen = Counter()
    for value in observed:
        key = text_key(value)
        seen[key] += 1
        if (key != headline_key and key not in approved) or seen[key] > 1:
            raise ValueError(f'cover_unapproved_or_duplicate_visible_text: {context}: {value}')
    if headline_key not in seen:
        raise ValueError('cover_headline_missing_or_changed: ' + context)


def check_plan_text(plan, headline, approved_labels):
    """Check authored layers. The rendered image review also checks raster text."""
    render = plan['render_spec']
    for profile, layout in render['profile_layouts'].items():
        layers = layout.get('cover_layers', {}).get('layers')
        if layers is not None:
            rows = [layer for layer in layers if layer.get('type') == 'text']
        elif 'photo_editorial' in layout:
            rows = layout['photo_editorial'].get('text_nodes', [])
        else:
            rows = [{'role': 'overlay', 'text': headline}]
            rows.extend({'text': text} for text in render.get('helper_labels', []))
        title = ''.join(row['text'] for row in rows if row.get('role') == 'overlay')
        observed = [title] if title else []
        observed.extend(row['text'] for row in rows if row.get('role') != 'overlay')
        check_text(observed, headline, approved_labels,
                   context=f"{plan['candidate']['candidate_id']}/{profile}")


def check_privacy_references(candidate, candidate_id):
    """Fail-closed guard: self portrait references must be background-stripped, never raw bedroom/monitor originals."""
    import cover_workbench as w

    refs = []
    if candidate.get('identity_reference_ref'):
        refs.append(('candidate.identity_reference_ref', candidate['identity_reference_ref'], candidate.get('background_stripped')))
    for idx, row in enumerate(candidate.get('identity_references') or []):
        if isinstance(row, dict) and row.get('ref'):
            refs.append((f'candidate.identity_references[{idx}]', row['ref'], row.get('background_stripped')))
        elif isinstance(row, dict) and row.get('path'):
            refs.append((f'candidate.identity_references[{idx}]', row, row.get('background_stripped')))
    for label, ref, stripped in refs:
        bound_path = w.bound(ref)
        norm_p = str(bound_path).replace('\\', '/').casefold()
        if stripped is False:
            raise ValueError(f'cover_unstripped_private_reference: {candidate_id}/{label}')
        if 'canonical-unmirrored' in norm_p and stripped is not True:
            raise ValueError(f'cover_unstripped_private_reference: {candidate_id}/{label}: raw canonical-unmirrored portrait must be background-stripped first')
        if stripped is not True and not any(tok in norm_p for tok in ('nobg', 'stripped', 'cutout', 'matting')):
            raise ValueError(f'cover_privacy_strip_attestation_required: {candidate_id}/{label}')
    return len(refs)


def check_single_master(candidate, candidate_id, *, require_single_master=False):
    """Fail-closed guard: all ratios of one cover candidate must share ONE locked visual master plate."""
    import cover_workbench as w

    images = candidate['images']
    cand_master = candidate.get('master_plate_ref')
    has_any_master = cand_master is not None or any(
        isinstance(row, dict) and row.get('master_plate_ref') is not None for row in images.values()
    )
    if not require_single_master and not has_any_master:
        return None
    digests = set()
    for ratio, row in images.items():
        mref = row.get('master_plate_ref') if isinstance(row, dict) else None
        if mref is None:
            mref = cand_master
        if not isinstance(mref, dict) or not mref.get('path') or not mref.get('sha256'):
            raise ValueError(f'cover_candidate_master_plate_missing: {candidate_id}/{ratio}')
        w.bound(mref)
        digests.add(mref['sha256'].lower())
    if len(digests) != 1:
        raise ValueError(f'cover_candidate_master_plate_mismatch: {candidate_id}: all ratios of one candidate must derive from a single visual master')
    return next(iter(digests))


def package_check(path, *, require_single_master=None):
    """Review actual PNGs from either the workbench or another local renderer."""
    import cover_workbench as w
    from cover_strategy import _check_image

    data = w.read(path)
    if data.get('schema') != 'self-media.cover-package-review.v1':
        raise ValueError('invalid_cover_package_schema')
    stage = data.get('stage')
    if stage not in ('preview', 'final'):
        raise ValueError('invalid_cover_stage')
    if require_single_master is None:
        # Final stage always requires a locked single visual master (no self-declared JSON bypass).
        enforce_master = (stage == 'final') or bool(data.get('require_single_master'))
    else:
        enforce_master = bool(require_single_master)
    project_id = w.safe_id(data['project_id'])
    text_key(data['reviewer'])
    candidates = data['candidates']
    if not isinstance(candidates, list) or not candidates:
        raise ValueError('cover_review_candidates_required')
    if stage == 'final':
        if len(candidates) != 1:
            raise ValueError('final_requires_one_confirmed_style')
        choice = resolve_choice(data['style_choice'], project_id)
        candidate = candidates[0]
        if candidate.get('id') != choice['id'] or candidate.get('style_id') != choice['style_id']:
            raise ValueError('final_cover_style_differs_from_confirmed_preview')
    rows = []
    seen = set()
    for candidate in candidates:
        candidate_id = w.safe_id(candidate['id'])
        style_id = w.safe_id(candidate['style_id'])
        if candidate_id in seen:
            raise ValueError('duplicate_cover_candidate')
        seen.add(candidate_id)
        headline = candidate['headline']
        labels = candidate.get('approved_labels', {})
        validate_labels(labels)
        images = candidate['images']
        if not isinstance(images, dict):
            raise ValueError('cover_images_must_be_keyed_by_ratio')
        check_ratios(stage, list(images))
        check_privacy_references(candidate, candidate_id)
        master_sha = check_single_master(candidate, candidate_id, require_single_master=enforce_master)
        checked = {}
        for ratio, row in images.items():
            if row.get('visual_passed') is not True:
                raise ValueError(f'cover_visual_review_required: {candidate_id}/{ratio}')
            _check_image(row['image_ref'], ratio)
            check_text(row.get('visible_text'), headline, labels, context=f'{candidate_id}/{ratio}')
            checked[ratio] = row['image_ref']
        entry = dict(id=candidate_id, style_id=style_id, headline=headline, images=checked)
        if master_sha is not None:
            entry['single_master_verified'] = True
            entry['master_plate_sha256'] = master_sha
        rows.append(entry)
    return dict(schema='self-media.cover-package-check.v1', project_id=project_id, stage=stage,
                status='preview_reviewed' if stage == 'preview' else 'final_cover_package_complete',
                package_ref=w.reference(path), candidates=rows,
                visible_text_check='reviewer_transcription_checked_against_approved_copy',
                publish_authorized=False)


def resolve_choice(choice, project_id):
    import cover_workbench as w

    text_key(choice['user_confirmation'])
    candidate_id = w.safe_id(choice['candidate_id'])
    preview_path = w.bound(choice['preview_package_ref'])
    # Reject a non-preview reference before recursion.
    if w.read(preview_path).get('stage') != 'preview':
        raise ValueError('confirmed_style_requires_preview_package')
    preview = package_check(preview_path)
    if preview['project_id'] != project_id:
        raise ValueError('confirmed_cover_style_project_mismatch')
    for candidate in preview['candidates']:
        if candidate['id'] == candidate_id:
            return candidate
    raise ValueError('confirmed_cover_style_not_in_preview')
