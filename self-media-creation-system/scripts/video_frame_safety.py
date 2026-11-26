"""Validate displayed media geometry and measured compositor bounds before review."""
from __future__ import annotations

import hashlib
import json
import math
import sys
from fractions import Fraction
from pathlib import Path

import cover_workbench as covers

SCHEMA = 'self-media.video-frame-safety.v1'
ROLES = {'flower', 'subtitle', 'evidence_card', 'animation'}
STAGES = {'program', 'animation_render', 'animation_insert'}


def probe_media(path):
    source = Path(__file__).resolve().parents[2] / 'ai-video-tools-20260708/mvp-video-pipeline/src'
    if not (source / 'video_creation_pipeline/execution_receipts.py').is_file():
        raise ValueError('frame_safety_existing_media_probe_unavailable')
    if str(source) not in sys.path:
        sys.path.insert(0, str(source))
    from video_creation_pipeline.execution_receipts import probe_media_metadata

    return probe_media_metadata(path)


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError('frame_safety_finite_number_required')
    return value


def display_geometry(metadata):
    """Display-matrix rotation takes precedence over legacy rotate tags."""
    from video_creation_pipeline.production_presets import media_facts

    facts = media_facts(metadata)
    stream = next(s for s in metadata['streams'] if s.get('codec_type') == 'video')
    width, height = facts['width'], facts['height']
    rotation = facts['rotation_degrees'] % 360
    try:
        raw_sar = stream.get('sample_aspect_ratio')
        sar = Fraction(str(raw_sar).replace(':', '/')) if raw_sar not in (None, 'N/A', '') else Fraction(1)
    except (ValueError, ZeroDivisionError) as error:
        raise ValueError('frame_safety_invalid_sample_aspect_ratio') from error
    if min(width, height, sar) <= 0 or rotation not in (0, 90, 180, 270):
        raise ValueError('frame_safety_invalid_display_geometry')
    ratio = Fraction(width, height) * sar
    if rotation in (90, 270):
        width, height = height, width
        ratio = 1 / ratio
    return dict(coded_size=[facts['width'], facts['height']], oriented_size=[width, height],
                rotation_degrees=facts['rotation_degrees'], sample_aspect_ratio=str(sar),
                display_aspect_ratio=str(ratio), duration_seconds=facts['duration_s'])


def check_media(path, canvas, probe):
    facts = display_geometry(probe(path))
    if Fraction(facts['display_aspect_ratio']) != Fraction(*canvas):
        raise ValueError(f'frame_safety_display_aspect_mismatch: {Path(path).name} '
                         f'{facts["display_aspect_ratio"]} vs {Fraction(*canvas)}')
    return facts


def _rectangle(rect, canvas, label):
    if not isinstance(rect, list) or len(rect) != 4:
        raise ValueError('frame_safety_measured_rect_required: ' + label)
    left, top, right, bottom = map(_number, rect)
    width, height = canvas
    if (not left < right or not top < bottom or min(left, top) < -1e-6
            or right > width + 1e-6 or bottom > height + 1e-6):
        raise ValueError('frame_safety_overlay_out_of_frame: ' + label)


def review_payload_hash(request):
    value = {key: item for key, item in request.items() if key != 'frame_safety_plan_ref'}
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    return hashlib.sha256(data.encode('utf-8')).hexdigest()


def _artifact_key(ref, *, relative_to=None):
    path = Path(ref['path'])
    if relative_to is not None and not path.is_absolute():
        path = relative_to / path
    return path.resolve(), ref['sha256']


def check(plan, probe, *, required_sources=(), required_roles=(), required_windows=()):
    if plan.get('schema') != SCHEMA or not str(plan.get('project_id', '')).strip():
        raise ValueError('frame_safety_plan_schema_and_project_required')
    canvas = plan.get('canvas')
    if (not isinstance(canvas, list) or len(canvas) != 2
            or any(type(size) is not int or size <= 0 for size in canvas)):
        raise ValueError('frame_safety_target_canvas_required')
    covers.bound(plan['composition_ref'])
    raw_sources = plan['sources']
    if not isinstance(raw_sources, list) or not raw_sources:
        raise ValueError('frame_safety_actual_video_sources_required')
    checked, stages, refs = [], set(), set()
    geometries = {}
    for row in raw_sources:
        stage = row['stage']
        if stage not in STAGES:
            raise ValueError('frame_safety_video_stage_invalid')
        ref = row['artifact_ref']
        key = _artifact_key(ref)
        if key not in geometries:
            geometries[key] = check_media(covers.bound(ref), canvas, probe)
        checked.append(dict(stage=stage, artifact_ref=ref, **geometries[key]))
        stages.add(stage)
        refs.add(key)
    animation_stages = {'animation_render', 'animation_insert'}
    if 'program' not in stages or (stages & animation_stages and not animation_stages <= stages):
        raise ValueError('frame_safety_requires_program_and_both_animation_stages_if_used')
    if not set(required_sources) <= refs:
        raise ValueError('frame_safety_current_review_or_render_source_missing')

    duration = _number(plan['duration_seconds'])
    times = [_number(t) for t in plan['sample_times_seconds']]
    if (duration <= 0 or not times or times != sorted(set(times))
            or any(not 0 <= t < duration or round(t, 3) != t for t in times)):
        raise ValueError('frame_safety_requires_unique_ordered_millisecond_timeline_samples')
    layers = {}
    for layer in plan['layers']:
        name, role = layer['id'], layer['role']
        start, end = _number(layer['start_seconds']), _number(layer['end_seconds'])
        if not name or name in layers or role not in ROLES or not 0 <= start < end <= duration:
            raise ValueError('frame_safety_invalid_layer_or_interval')
        active = [t for t in times if start <= t < end]
        if not active:
            raise ValueError('frame_safety_layer_without_sample: ' + name)
        if not set(layer.get('motion_extrema_seconds', [])) <= set(active):
            raise ValueError('frame_safety_motion_extrema_without_sample: ' + name)
        if role != 'subtitle' and end - start >= .12:
            if len(active) < 3 or active[0] - start > min(.05, (end-start)/3) or end - active[-1] > min(.05, (end-start)/3):
                raise ValueError('frame_safety_requires_entry_hold_exit: ' + name)
        layers[name] = (role, set(active))
    if not set(required_roles) <= {role for role, _ in layers.values()}:
        raise ValueError('frame_safety_required_overlay_layer_missing')
    for role, start, end in required_windows:
        if not any(layer['role'] == role and layer['start_seconds'] <= start
                   and layer['end_seconds'] >= end for layer in plan['layers']):
            raise ValueError(f'frame_safety_layer_does_not_cover_review_cue: {role} {start}–{end}')
    has_animation_layer = any(role == 'animation' for role, _ in layers.values())
    if bool(stages & animation_stages) != has_animation_layer:
        raise ValueError('frame_safety_animation_stage_and_insertion_bounds_required')

    evidence = covers.read(covers.bound(plan['measurements_ref']))
    if (evidence.get('schema') != 'self-media.compositor-frame-measurements.v1'
            or evidence.get('composition_ref') != plan['composition_ref']
            or evidence.get('canvas') != canvas):
        raise ValueError('frame_safety_measurements_for_other_composition_or_canvas')
    rows = evidence['samples']
    if [row['time_seconds'] for row in rows] != times:
        raise ValueError('frame_safety_measurement_times_do_not_match')
    for row in rows:
        t = row['time_seconds']
        boxes = row['bounds']
        visible = {name for name, (_, active) in layers.items() if t in active}
        if set(boxes) != visible:
            raise ValueError(f'frame_safety_missing_or_unlisted_measured_overlay: {t}s')
        for name, rect in boxes.items():
            _rectangle(rect, canvas, f'{layers[name][0]} {name} {t}s')
    return dict(status='passed', project_id=plan['project_id'], canvas=canvas, duration_seconds=duration,
                composition_ref=plan['composition_ref'], measurements_ref=plan['measurements_ref'],
                sources=checked, sample_times_seconds=times, checked_layer_count=len(layers))


def check_ref(ref, probe, **kwargs):
    if not ref:
        raise ValueError('frame_safety_plan_required_before_review_or_render')
    return check(covers.read(covers.bound(ref)), probe, **kwargs)


def for_review(request, request_path, purpose, probe):
    cues = [cue for row in request['requests'] for cue in row.get('subtitle_cues', [])]
    ref = request.get('frame_safety_plan_ref')
    if not ref and not (purpose == 'fine_cut_recipe' or (purpose == 'material_requirement' and cues)):
        return None
    if not ref:
        raise ValueError('frame_safety_plan_required_before_review_or_render')
    plan = covers.read(covers.bound(ref))
    if plan.get('review_payload_sha256') != review_payload_hash(request):
        raise ValueError('frame_safety_measurements_do_not_match_review_request')
    sources = {_artifact_key({'path': row['source_path'], 'sha256': row['artifact_sha256']},
                             relative_to=request_path.parent) for row in request['requests']}
    roles = {'dialogue': 'subtitle', 'age': 'flower', 'context': 'flower'}
    program_starts = plan.get('review_program_starts', {})
    windows = []
    for row in request['requests']:
        row_cues = row.get('subtitle_cues', [])
        if not row_cues:
            continue
        start = _number(program_starts[row['review_id']])
        for cue in row_cues:
            window = [round(start + cue[key] - row['review_start_seconds'], 3)
                      for key in ('start_seconds', 'end_seconds')]
            windows.append((roles[cue.get('layer', 'dialogue')], *window))
    return check(plan, probe, required_sources=sources,
                 required_roles={role for role, _, _ in windows}, required_windows=windows)


def for_delivery(manifest, probe):
    ref = manifest.get('frame_safety_plan_ref')
    roles, windows = set(), []
    role_map = {'evidence_focus': 'evidence_card', 'information_motion': 'animation'}
    if manifest.get('final_layout_ref'):
        layout = covers.read(covers.bound(manifest['final_layout_ref']))
        for layer in layout['elements']:
            role = role_map.get(layer['role'])
            if role:
                roles.add(role)
                windows.append((role, layer['start_seconds'], layer['end_seconds']))
    pack_ref = manifest.get('subtitles', {}).get('pack_ref')
    if pack_ref:
        pack = covers.read(covers.bound(pack_ref))
        if any(cue.get('motion', 'none') != 'none'
               for row in pack.get('requests', []) for cue in row.get('subtitle_cues', [])
               if isinstance(cue, dict)):
            roles.add('subtitle')
    if not ref and not roles:
        return None
    if ref and manifest.get('final_layout_ref'):
        for layer in layout['elements']:
            if layer['role'] == 'subtitle':
                windows.append(('subtitle', layer['start_seconds'], layer['end_seconds']))
    source = _artifact_key(manifest['edited_media'])
    result = check_ref(ref, probe, required_sources={source}, required_roles=roles, required_windows=windows)
    if result['project_id'] != manifest['project_id']:
        raise ValueError('frame_safety_plan_for_other_project')
    review_ref = manifest.get('frame_safety_review_ref')
    if not review_ref:
        raise ValueError('frame_safety_pre_review_receipt_required')
    receipt = covers.read(covers.bound(review_ref))
    if receipt != {**result, 'plan_ref': ref}:
        raise ValueError('frame_safety_pre_review_receipt_does_not_match_current_plan')
    return result


def check_final_media(source, checked, probe):
    facts = check_media(source, checked['canvas'], probe)
    if abs(facts['duration_seconds'] - checked['duration_seconds']) > .1:
        raise ValueError('frame_safety_final_duration_differs_from_reviewed_timeline')
    return facts


def final_samples(manifest, duration):
    ref = manifest.get('frame_safety_plan_ref')
    if not ref:
        return []
    times = covers.read(covers.bound(ref))['sample_times_seconds']
    if any(t >= duration for t in times):
        raise ValueError('frame_safety_approved_sample_outside_final_timeline')
    return times


def check_decoded_frames(rows, canvas):
    from PIL import Image

    for row in rows:
        with Image.open(covers.bound(row['frame_ref'])) as image:
            if image.size != tuple(canvas):
                raise ValueError(f'frame_safety_decoded_frame_canvas_mismatch: {row["time_seconds"]}s')
