"""Validate the source inventory before editing and its actual use after export."""
from pathlib import Path
import math
from urllib.parse import urlsplit

import cover_workbench as covers


INTAKE_SCHEMA = 'self-media.video-material-intake.v1'
REVIEW_SCHEMA = 'self-media.video-material-final-review.v1'
REDRAW_SCHEMA = 'self-media.video-material-redraw.v1'
REDRAW_KIND = 'independent_redraw'
REDRAW_CHECKS = ('facts_checked', 'independent_design_checked', 'credit_checked', 'readability_checked')
CARD_REPLACEMENT_SCHEMA = 'self-media.recorded-card-replacement.v1'
CAPTURE_SCHEMA = 'self-media.evidence-image-capture.v1'
CARD_VISUAL_CHECKS = ('text_matches', 'ghosting_clear', 'seams_clear')
RENDER_ASSET_ROLES = {'evidence_overlay', 'overlay_image', 'b_roll', 'broll',
                      'stock_media', 'background_music', 'music_track', 'sound_effect'}


def _read(reference, missing):
    if reference is None:
        raise ValueError(missing)
    value = covers.read(covers.bound(reference))
    if not isinstance(value, dict):
        raise ValueError('material_record_must_be_object')
    return value


def _key(reference):
    return Path(reference['path']).resolve(), reference['sha256']


def _required_text(value):
    return isinstance(value, str) and bool(value.strip())


def _time(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError('material_range_requires_finite_seconds')
    return value


def _redraw_proof(project_id, row, reference):
    proof = _read(reference, 'material_redraw_evidence_required')
    item_id = row['id']
    if (proof.get('schema') != REDRAW_SCHEMA or proof.get('project_id') != project_id
            or proof.get('asset_id') != item_id or proof.get('source') != row['source']):
        raise ValueError('material_redraw_project_asset_or_source_mismatch: ' + item_id)
    for field, item_field in (('reference_ref', 'original_ref'), ('rendered_ref', 'adopted_ref')):
        if proof.get(field) != row[item_field]:
            raise ValueError('material_redraw_artifact_mismatch: ' + item_id)
    editable = proof.get('editable_ref')
    if not isinstance(editable, dict):
        raise ValueError('material_redraw_editable_source_required: ' + item_id)
    covers.bound(editable)
    if len({row['original_ref']['sha256'], row['adopted_ref']['sha256'], editable['sha256']}) != 3:
        raise ValueError('material_redraw_requires_distinct_original_editable_and_rendered: ' + item_id)
    if not all(_required_text(proof.get(key)) for key in ('fallback_reason', 'reviewer', 'review_notes')):
        raise ValueError('material_redraw_reason_reviewer_and_notes_required: ' + item_id)
    fact_source = proof.get('fact_source_url')
    if not _required_text(fact_source):
        raise ValueError('material_redraw_fact_source_url_required: ' + item_id)
    url = urlsplit(fact_source)
    if url.scheme not in ('http', 'https') or not url.hostname:
        raise ValueError('material_redraw_fact_source_url_required: ' + item_id)
    checks = proof.get('checks')
    if not isinstance(checks, dict) or any(checks.get(key) is not True for key in REDRAW_CHECKS):
        raise ValueError('material_redraw_checks_incomplete: ' + item_id)
    return proof


def redraw_intake(manifest, reference):
    """Adopt a reviewed redraw in a new inventory while retaining its reference image."""
    data = _read(manifest.get('material_intake_ref'), 'material_intake_required')
    items, _ = intake(manifest, require_ready=False)
    proof = _read(reference, 'material_redraw_evidence_required')
    item_id = proof.get('asset_id')
    if item_id not in items:
        raise ValueError('material_redraw_unknown_asset')
    old = items[item_id]
    if not isinstance(proof.get('rendered_ref'), dict):
        raise ValueError('material_redraw_rendered_image_required: ' + item_id)
    covers.bound(proof['rendered_ref'])
    if not _required_text(proof.get('fallback_reason')):
        raise ValueError('material_redraw_fallback_reason_required: ' + item_id)
    row = dict(old, adopted_ref=proof['rendered_ref'], processing='按原文独立重绘，原图留作核对。',
               use_basis=dict(decision='supported', kind=REDRAW_KIND,
                              reason=proof['fallback_reason'], evidence_ref=reference))
    _redraw_proof(manifest['project_id'], row, reference)
    data['assets'] = [row if item['id'] == item_id else item for item in data['assets']]
    return data


def _card_replacement_proof(project_id, row, reference):
    proof = _read(reference, 'material_card_replacement_required')
    item_id = row['id']
    if (row['entry_method'] != 'screen_recording' or proof.get('schema') != CARD_REPLACEMENT_SCHEMA
            or proof.get('project_id') != project_id or proof.get('asset_id') != item_id
            or proof.get('reference_ref') != row['original_ref'] or proof.get('rendered_ref') != row['adopted_ref']):
        raise ValueError('material_card_replacement_project_asset_or_file_mismatch: ' + item_id)
    if proof.get('whole_card_checked') is not True or row['adopted_ref']['sha256'] == row['original_ref']['sha256']:
        raise ValueError('material_card_requires_new_whole_card: ' + item_id)
    editable = proof.get('editable_ref')
    if not isinstance(editable, dict):
        raise ValueError('material_card_editable_source_required: ' + item_id)
    editable_path = covers.bound(editable)
    if proof.get('method') == 'html_recapture':
        recording_html = proof.get('recording_html_ref')
        if not isinstance(recording_html, dict) or covers.bound(recording_html).suffix.lower() != '.html':
            raise ValueError('material_card_recording_html_required: ' + item_id)
        if recording_html['sha256'] == editable['sha256']:
            raise ValueError('material_card_requires_revised_recording_html: ' + item_id)
        capture = _read(proof.get('capture_ref'), 'material_card_html_capture_required: ' + item_id)
        if (editable_path.suffix.lower() != '.html' or capture.get('schema') != CAPTURE_SCHEMA
                or capture.get('editable_ref') != editable or capture.get('rendered_ref') != row['adopted_ref']
                or not _required_text(capture.get('selector'))):
            raise ValueError('material_card_html_capture_mismatch: ' + item_id)
    elif proof.get('method') != 'recreated_card' or not _required_text(proof.get('html_unavailable_reason')):
        raise ValueError('material_card_requires_html_recapture_or_documented_recreation: ' + item_id)


def card_replace_intake(manifest, reference):
    """Register a complete replacement for a text-bearing card in a screen recording."""
    data = _read(manifest.get('material_intake_ref'), 'material_intake_required')
    items, _ = intake(manifest, require_ready=False)
    proof = _read(reference, 'material_card_replacement_required')
    item_id = proof.get('asset_id')
    if item_id not in items:
        raise ValueError('material_card_replacement_unknown_asset')
    if not isinstance(proof.get('rendered_ref'), dict):
        raise ValueError('material_card_replacement_image_required: ' + item_id)
    covers.bound(proof['rendered_ref'])
    row = dict(items[item_id], adopted_ref=proof['rendered_ref'], card_replacement_ref=reference,
               processing='录屏文字变更，使用重新绘制或重新截图的整张卡片替换。')
    _card_replacement_proof(manifest['project_id'], row, reference)
    if row['use_basis'].get('kind') == REDRAW_KIND:
        _redraw_proof(manifest['project_id'], row, row['use_basis'].get('evidence_ref'))
    data['assets'] = [row if item['id'] == item_id else item for item in data['assets']]
    return data


def intake(manifest, *, require_ready=True):
    data = _read(manifest.get('material_intake_ref'), 'material_intake_required')
    if data.get('schema') != INTAKE_SCHEMA or data.get('project_id') != manifest['project_id']:
        raise ValueError('material_intake_project_or_schema_mismatch')
    if not _required_text(data.get('scope_note')) or not isinstance(data.get('assets'), list):
        raise ValueError('material_intake_scope_and_assets_required')
    items, pending = {}, []
    for row in data['assets']:
        item_id = row['id']
        if not _required_text(item_id) or item_id in items:
            raise ValueError('material_id_missing_or_duplicate')
        if row.get('entry_method') not in ('timeline_asset', 'screen_recording'):
            raise ValueError('material_entry_method_required: ' + item_id)
        if not _required_text(row.get('source')) or not _required_text(row.get('processing')):
            raise ValueError('material_source_and_processing_required: ' + item_id)
        covers.bound(row.get('original_ref'))
        covers.bound(row.get('adopted_ref'))
        basis = row['use_basis']
        if basis.get('decision') not in ('supported', 'pending') or not _required_text(basis.get('reason')):
            raise ValueError('material_use_basis_required: ' + item_id)
        evidence = basis.get('evidence_ref')
        if basis.get('kind') == REDRAW_KIND:
            _redraw_proof(manifest['project_id'], row, evidence)
        elif evidence is not None:
            covers.bound(evidence)
        if basis['decision'] == 'supported' and evidence is None:
            raise ValueError('material_use_basis_evidence_required: ' + item_id)
        if row.get('card_replacement_ref') is not None:
            _card_replacement_proof(manifest['project_id'], row, row['card_replacement_ref'])
        if basis['decision'] == 'pending' or ('card_replacement_ref' in row and row['card_replacement_ref'] is None):
            pending.append(item_id)
        items[item_id] = row
    if require_ready and pending:
        raise ValueError('material_use_basis_pending: ' + ', '.join(pending))
    return items, pending


def check_intake(manifest):
    items, _ = intake(manifest)
    return dict(status='intake_checked', asset_count=len(items),
                screen_recording_asset_count=sum(x['entry_method'] == 'screen_recording' for x in items.values()),
                independent_redraw_count=sum(x['use_basis'].get('kind') == REDRAW_KIND for x in items.values()),
                recorded_card_replacement_count=sum(x.get('card_replacement_ref') is not None for x in items.values()),
                autonomous_rights_verification=False)


def check_render_inputs(items, render_receipts):
    registered = {_key(row['adopted_ref']) for row in items.values()}
    for receipt in render_receipts:
        for row in receipt.get('inputs', []):
            if row['role'] in RENDER_ASSET_ROLES and _key(row['artifact']) not in registered:
                raise ValueError('material_render_input_not_registered: ' + Path(row['artifact']['path']).name)


def _sample_index(references, candidate, renderer):
    samples = {}
    for reference in references:
        receipt = _read(reference, 'material_frame_receipt_required')
        renderer.validate_ffmpeg_execution_receipt(receipt)
        if (receipt.get('status') != 'completed' or receipt.get('operation') != 'frame_extract'
                or len(receipt.get('inputs', [])) != 1
                or _key(receipt['inputs'][0]['artifact']) != _key(candidate)):
            raise ValueError('material_frame_receipt_for_other_video')
        for row in receipt['outputs']:
            if row['role'] == 'frame':
                samples.setdefault(_key(row['artifact']), set()).add(_time(row['media_time_s']))
    return samples


def check_layout_inventory(layout, cues, source_ranges):
    elements = {row['element_id']: row for row in layout['elements']}
    if any(not _required_text(row.get('source_text')) for row in source_ranges):
        raise ValueError('protected_source_label_requires_expected_visible_text')
    required = [(cue['id'], cue) for cue in cues if cue['area'] == 'visual_focus' and cue['kind'] == 'evidence']
    required += [(row.get('source_layout_id'), row) for row in source_ranges]
    for element_id, segment in required:
        row = elements.get(element_id)
        if (not row or row['role'] != 'information_motion' or row['critical_content'] is not True
                or not row.get('text', '').strip()
                or (segment.get('source_text') and segment['source_text'].strip() not in row['text'])
                or row['start_seconds'] > segment['start_seconds'] + 1e-6
                or row['end_seconds'] < segment['end_seconds'] - 1e-6):
            raise ValueError('selected_evidence_or_source_label_missing_from_protected_layout: ' + str(element_id))
    return len({element_id for element_id, _ in required})


def check_final(manifest, candidate, duration, renderer):
    items, pending = intake(manifest, require_ready=False)
    review = _read(manifest.get('material_final_review_ref'), 'material_final_review_required')
    if review.get('schema') != REVIEW_SCHEMA or review.get('project_id') != manifest['project_id']:
        raise ValueError('material_final_review_project_or_schema_mismatch')
    if review.get('intake_ref') != manifest['material_intake_ref']:
        raise ValueError('material_final_review_for_other_intake')
    if _key(review['video']) != _key(candidate):
        raise ValueError('material_final_review_for_other_video')
    covers.bound(candidate)
    if (review.get('screen_recording_checked') is not True or not _required_text(review.get('reviewer'))
            or not isinstance(review.get('entries'), list) or not isinstance(review.get('sample_receipts'), list)):
        raise ValueError('material_final_inventory_and_screen_recording_review_required')
    reviewed_ids = [row['id'] for row in review['entries']]
    if len(reviewed_ids) != len(set(reviewed_ids)) or set(reviewed_ids) != set(items):
        raise ValueError('material_final_review_must_cover_each_registered_asset')
    samples = _sample_index(review['sample_receipts'], candidate, renderer)
    uses = 0
    for row in review['entries']:
        item_id = row['id']
        item = items[item_id]
        if row.get('decision') == 'removed':
            if not _required_text(row.get('reason')) or row.get('ranges') != []:
                raise ValueError('material_removed_requires_reason_and_no_ranges: ' + item_id)
            continue
        ranges = row.get('ranges')
        if row.get('decision') != 'present' or not isinstance(ranges, list) or not ranges:
            raise ValueError('material_actual_use_needs_time_range: ' + item_id)
        previous_end = 0
        for segment in ranges:
            start = _time(segment['start_seconds'])
            end = _time(segment['end_seconds'])
            time = _time(segment['sample_seconds'])
            if not previous_end <= start <= time < end <= _time(duration):
                raise ValueError('material_invalid_or_overlapping_time_range: ' + item_id)
            previous_end = end
            frame = segment['frame_ref']
            if time not in samples.get(_key(frame), ()):
                raise ValueError('material_frame_not_proven_at_reported_time: ' + item_id)
            covers.bound(frame)
            if (segment.get('credit') not in ('visible_checked', 'not_required')
                    or not _required_text(segment.get('observation'))
                    or segment.get('processing_checked') is not True):
                raise ValueError('material_source_label_or_processing_review_pending: ' + item_id)
            if item['use_basis'].get('kind') == REDRAW_KIND and segment['credit'] != 'visible_checked':
                raise ValueError('material_redraw_visible_credit_required: ' + item_id)
            if item.get('card_replacement_ref') is not None:
                checks = segment.get('card_visual_checks')
                if not isinstance(checks, dict) or any(checks.get(key) is not True for key in CARD_VISUAL_CHECKS):
                    raise ValueError('material_card_visual_review_incomplete: ' + item_id)
            uses += 1
    if pending:
        raise ValueError('material_use_basis_pending: ' + ', '.join(pending))
    return dict(status='actual_use_review_checked', asset_count=len(items), use_ranges=uses,
                observed_video_sha256=candidate['sha256'], automatic_visual_recognition=False,
                publish_authorized=False)
