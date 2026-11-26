"""Evidence-bound video delivery subflow; reuse existing inspectors, never publish.

No ASR model, renderer, automatic human approval or private-media discovery here.
The same live audit backs both CLI completion and publication-desk delivery.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib
import json
import math
import os
import sys
import re
import shutil
import types
import uuid
from pathlib import Path
from jsonschema import Draft202012Validator, ValidationError

import publication_desk as desk
import cover_workbench as covers
import cover_strategy
import runtime_paths
import video_progress_contract as progress
import video_material_use as materials
import cta_review as cta
import video_frame_safety as framing

ROOT = Path(__file__).resolve().parents[1]
VKP = ROOT.parent / 'video-knowledge-pipeline'
SCHEMA = 'self-media.video-delivery.v1'
HUMAN_CHECKS = ('full_video_watched', 'full_audio_listened', 'burned_subtitles_correct',
                'mobile_readable', 'cards_and_subjects_unobscured', 'audio_joins_balanced',
                'story_and_copy_correct', 'privacy_checked')
VIDEO_DELIVERY_ACTIONS = (
    'materials-bind', 'materials-redraw', 'materials-card-replace', 'materials-check',
    'pacing-check', 'pacing-bind', 'overlays-bind', 'overlays-check', 'rough-cut-bind',
    'init', 'context', 'preflight', 'render', 'check', 'deliver', 'progress-select',
    'cta-init', 'cta-bind', 'context-bind', 'observe-final', 'identity-select',
    'bgm-select', 'performance-init', 'performance-bind', 'performance-review-template',
    'rebind-copy-acceptance', 'frame-safety-bind', 'frame-postcheck',
)
PERFORMANCE_AREAS = ('speech_boundaries', 'speech_levels', 'music_balance',
                     'subtitle_readability', 'visual_focus', 'delivery_pacing')


def _mvp_src_root():
    env_root = os.environ.get('SELF_MEDIA_SUBTITLE_RUNTIME_ROOT', '').strip()
    if env_root:
        candidate = Path(env_root).resolve() / 'src'
        if (candidate / 'video_creation_pipeline/execution_receipts.py').is_file():
            return candidate
    snapshot = ROOT / 'runtime_dependencies/subtitle-mvp/src'
    if (snapshot / 'video_creation_pipeline/execution_receipts.py').is_file():
        return snapshot
    if ROOT.parent.name == 'self-media-source':
        import cover_methods
        dev_src = cover_methods.workspace_root(ROOT) / 'ai-video-tools-20260708/mvp-video-pipeline/src'
        if (dev_src / 'video_creation_pipeline/execution_receipts.py').is_file():
            return dev_src
    source = ROOT.parent / 'ai-video-tools-20260708/mvp-video-pipeline/src'
    if not (source / 'video_creation_pipeline/execution_receipts.py').is_file():
        raise ValueError('existing_renderer_unavailable')
    return source


def describe_capabilities():
    return {
        'entrypoint': 'python scripts/self_media_agent.py video-delivery',
        'script_entrypoint': 'python scripts/video_delivery.py',
        'actions': list(VIDEO_DELIVERY_ACTIONS),
        'cta_review': 'Separate interaction/acquisition decisions; no mandatory CTA. Reuse one plan from script review through final-media landing acceptance.',
        'performance_review': 'Current cue plan and final observations required; applied feedback needs change evidence. Pacing may remain untested; no mandatory audience recruitment or editor route.',
        'progress_overlay': 'explicit use/not_used decision; default script headings and independent navigation font presets; checked reservation, actual render/layout evidence and current human checks required',
        'subtitle_burn_reconciliation': 'Both .srt/.vtt and .ass dialogue/timecode/style lines, managed fontsdir bundles, and 3-path render lineage are reconciled against pack_ref during guarded render and delivery audit.',
        'subtitle_runtime_src': str(_mvp_src_root()),
        'subtitle_runtime_release': os.environ.get('SELF_MEDIA_ACTIVE_RELEASE') or None,
        'subtitle_style_default': 'stroke_shadow_default',
        'guide': 'docs/video-delivery.md',
        'workflow_count': 5,
        'draft_render_is_complete': False,
        'automatic_publish': False,
    }


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     allow_nan=False).encode('utf-8')).hexdigest()


def bound(ref):
    return covers.bound(ref)


def read_ref(ref):
    value = covers.read(bound(ref))
    if not isinstance(value, dict):
        raise ValueError('object_required')
    return value


def vkp_modules():
    # Reuse the installed sibling source; never import executable paths from JSON.
    source = VKP / 'src'
    if not (source / 'video_knowledge_pipeline/subtitle_coverage.py').is_file():
        raise ValueError('vkp_subtitle_coverage_unavailable')
    if str(source) not in sys.path:
        sys.path.insert(0, str(source))
    from video_knowledge_pipeline.subtitle_coverage import check_subtitles
    from video_knowledge_pipeline.video import probe_video
    return check_subtitles, probe_video


def renderer_module():
    # Keep existing legacy mvp-video-pipeline root for render receipts, layout, and progress modules.
    source = ROOT.parent / 'ai-video-tools-20260708/mvp-video-pipeline/src'
    if not (source / 'video_creation_pipeline/execution_receipts.py').is_file():
        raise ValueError('existing_renderer_unavailable')
    if str(source) not in sys.path:
        sys.path.insert(0, str(source))
    from video_creation_pipeline import execution_receipts
    return execution_receipts


def subtitle_modules():
    src_root = _mvp_src_root()
    pkg_dir = src_root / 'video_creation_pipeline'
    pkg_name = '_subtitle_mvp_runtime'
    existing = sys.modules.get(pkg_name)
    if existing is None or getattr(existing, '_mvp_src_root', None) != str(src_root):
        for mod_key in [k for k in list(sys.modules) if k == pkg_name or k.startswith(pkg_name + '.')]:
            sys.modules.pop(mod_key, None)
        pkg = types.ModuleType(pkg_name)
        pkg.__path__ = [str(pkg_dir)]
        pkg.__package__ = pkg_name
        pkg._mvp_src_root = str(src_root)
        sys.modules[pkg_name] = pkg
    return (
        importlib.import_module(f'{pkg_name}.subtitle_sequence'),
        importlib.import_module(f'{pkg_name}.subtitle_styles'),
        importlib.import_module(f'{pkg_name}.subtitle_readability'),
        importlib.import_module(f'{pkg_name}.remotion_project'),
    )


def init(project_id):
    if not isinstance(project_id, str) or not project_id.strip():
        raise ValueError('project_id_required')
    return dict(schema=SCHEMA, project_id=project_id, edited_media=None, script_ref=None,
                facts=dict(story='', do_not_infer=[], feedback=[], no_prior_feedback_reason=''),
                timeline=dict(duration_seconds=None, segments=[], expected_audio=[]),
                subtitles=dict(request_ref=None, pack_ref=None, asr_ref=None, review_ref=None, render_file_ref=None),
                render_receipt_ref=None, desk_ref=None, cover_review_ref=None,
                material_intake_ref=None, material_final_review_ref=None,
                rough_cut_delivery_ref=None, rough_cut_acceptance_ref=None, overlay_assessment_ref=None,
                acceptance_ref=None, rough_audio_review_ref=None, cta_plan_ref=None, pacing_report_ref=None,
                performance_plan_ref=None,
                identity_overlay=dict(decision='undecided',reason='',source_ref=None),
                background_music=dict(decision='undecided',reason='',plan_ref=None),
                progress_overlay=dict(schema=progress.SCHEMA,decision='undecided',reason='',basis=None,result_ref=None))


def context(manifest):
    if manifest.get('schema') != SCHEMA or not str(manifest.get('project_id', '')).strip():
        raise ValueError('video_delivery_schema_or_project_required')
    facts = manifest['facts']
    if not isinstance(facts.get('story'), str) or not facts['story'].strip():
        raise ValueError('story_required')
    if not isinstance(facts.get('do_not_infer'), list) or not all(
            isinstance(x, str) and x.strip() for x in facts['do_not_infer']):
        raise ValueError('explicit_do_not_infer_list_required')
    rows = facts.get('feedback')
    if not isinstance(rows, list):
        raise ValueError('feedback_inventory_required')
    if not rows and not str(facts.get('no_prior_feedback_reason', '')).strip():
        raise ValueError('prior_feedback_or_explicit_none_reason_required')
    seen, recovered = set(), []
    for row in rows:
        if not isinstance(row.get('id'), str) or not row['id'].strip() or row['id'] in seen:
            raise ValueError('duplicate_or_missing_feedback_id')
        seen.add(row['id'])
        path = bound(row['ref'])
        if path.stat().st_size > 2_000_000:
            raise ValueError('feedback_too_large_use_bounded_export')
        text = path.read_text(encoding='utf-8-sig')
        if not text.strip():
            raise ValueError('empty_feedback')
        if row.get('decision') not in ('applied', 'not_applicable') or not str(row.get('application', '')).strip():
            raise ValueError('feedback_disposition_required: ' + row['id'])
        recovered.append(dict(id=row['id'], ref=row['ref'], text=text,
                              decision=row['decision'], application=row['application']))
    return dict(story=facts['story'], do_not_infer=facts['do_not_infer'], feedback=recovered,
                material_review_planning=dict(intake_ref=manifest.get('material_intake_ref'),
                    final_review_ref=manifest.get('material_final_review_ref'),
                    entrypoint='video-delivery materials-bind / materials-redraw / materials-card-replace / materials-check',
                    include_assets_inside_screen_recordings=True),
                progress_overlay_planning=dict(decision=manifest.get('progress_overlay',{}).get('decision','undecided'),
                    reason=manifest.get('progress_overlay',{}).get('reason',''),explicit_decision_required=True,
                    not_used_requires_author_message=True,
                    selected_overlay_requires_checked_reservation=True,
                    default_title_source='script', default_font_preset='compact',
                    required_position='bottom', safe_area_mode='auxiliary',
                    placement_policy=progress.PLACEMENT_POLICY,
                    navigation_font_independent_of_body_and_subtitles=True,
                    entrypoint='video-delivery progress-select; preflight blocks missing/stale choice or reservation'),
                cta_planning=dict(plan_ref=manifest.get('cta_plan_ref'), types=list(cta.KINDS),
                    explicit_decision_required=True, omission_with_reason_allowed=True,
                    entrypoint='video-delivery cta-init / cta-bind; final acceptance.cta_landing'),
                performance_planning=dict(plan_ref=manifest.get('performance_plan_ref'),
                    areas=list(PERFORMANCE_AREAS), audience_recruitment_required=False,
                    entrypoint='video-delivery performance-init / performance-bind / performance-review-template',
                    completion='current cue observations plus specific change evidence; no automatic quality claim'),
                source_text_is_instruction=False, full_history_discovery_proven=False)


def performance_template(manifest):
    """Adapt existing CTA selection/bound-reference pattern; never approve a cue."""
    plan = dict(schema='self-media.performance-plan.v1', project_id=manifest['project_id'],
        script_ref=manifest.get('script_ref'), edited_media=manifest.get('edited_media'),
        timeline_sha256=fingerprint(manifest['timeline']),
        context_manifest_ref=manifest.get('context_manifest_ref'),
        visual_beats_ref=manifest.get('visual_beats_ref'),
        areas={k:dict(decision='undecided', reason='', cue_ids=[]) for k in PERFORMANCE_AREAS},
        cues=[], feedback_dispositions=[],
        pacing=dict(status='not_tested', reason='', next_trial_speed=None, observations=[]))
    plan['feedback_dispositions'] = [dict(id=r['id'],source_ref=r['ref'],decision=r['decision'],
        reason=r.get('application',''),cue_ids=[]) for r in manifest['facts']['feedback']]
    if manifest.get('context_manifest_ref'):
        import purpose_continuity
        context = purpose_continuity.validate_context(bound(manifest['context_manifest_ref']))
        plan['feedback_dispositions'] += [dict(id='context:'+r['artifact_id'],
            source_ref={k:r['source'][k] for k in ('path','sha256')},decision='undecided',reason='',cue_ids=[])
            for r in context['feedback']]
    return copy.deepcopy(plan)


def performance_plan(manifest):
    """Structural record validation only; existing audio/layout gates still run."""
    import purpose_continuity as purpose
    ref = manifest.get('performance_plan_ref')
    if not ref:
        raise ValueError('performance_plan_required; use performance-init, do not fabricate a review')
    plan = read_ref(ref)
    schema = covers.read(ROOT / 'schemas/video-performance-plan.v1.schema.json')
    try:
        Draft202012Validator(schema).validate(plan)
    except ValidationError as error:
        raise ValueError('performance_schema_invalid: '+error.message) from error
    for key in ('project_id', 'script_ref', 'edited_media', 'context_manifest_ref'):
        if plan[key] != manifest.get(key):
            raise ValueError('performance_binding_drift: '+key)
    if plan['timeline_sha256'] != fingerprint(manifest['timeline']):
        raise ValueError('performance_timeline_drift')
    script_path = bound(plan['script_ref'])
    if script_path.stat().st_size > 2_000_000:
        raise ValueError('performance_script_too_large')
    script = script_path.read_text(encoding='utf-8-sig')
    bound(plan['edited_media'])
    purpose_context = purpose.validate_context(bound(plan['context_manifest_ref']))
    duration = number(manifest['timeline']['duration_seconds'])
    ids, by_id = set(), {}
    for cue in plan['cues']:
        if cue['id'] in ids:
            raise ValueError('duplicate_performance_cue')
        ids.add(cue['id']); by_id[cue['id']] = cue
        if cue['quote'] not in script:
            raise ValueError('performance_script_anchor_missing: '+cue['id'])
        purpose.text(cue['quote'], 'script anchor')
        purpose.text(cue['source_quote'], 'decision source anchor')
        for key in ('intent', 'decision', 'reason', 'expected_result', 'scope'):
            purpose.text(cue[key], 'cue '+cue['id']+' '+key)
        source = bound(cue['source_ref'])
        if source.stat().st_size > 2_000_000 or cue['source_quote'] not in source.read_text(encoding='utf-8-sig'):
            raise ValueError('performance_source_anchor_missing')
        if not 0 <= number(cue['start_seconds']) < number(cue['end_seconds']) <= duration:
            raise ValueError('performance_cue_outside_current_timeline')
        if cue['requires_change']:
            if not cue.get('before_ref'):
                raise ValueError('performance_before_evidence_required')
            bound(cue['before_ref'])
    assigned = set()
    for area, choice in plan['areas'].items():
        purpose.text(choice['reason'], area+' selection reason')
        if choice['decision'] == 'undecided':
            raise ValueError('performance_area_undecided: '+area)
        if choice['decision'] == 'use' and not choice['cue_ids']:
            raise ValueError('performance_area_cues_required: '+area)
        if choice['decision'] == 'not_needed' and choice['cue_ids']:
            raise ValueError('performance_unused_area_has_cues')
        for cue_id in choice['cue_ids']:
            if cue_id not in by_id or by_id[cue_id]['area'] != area or cue_id in assigned:
                raise ValueError('performance_area_cue_mismatch')
            assigned.add(cue_id)
    if assigned != ids:
        raise ValueError('performance_unassigned_cues')
    # Reuse the existing semantic-editorial artifact validator where that route
    # was selected. External editors may supply their own sourced cues instead.
    beat_ref = plan.get('visual_beats_ref')
    if manifest.get('visual_beats_ref') and beat_ref != manifest['visual_beats_ref']:
        raise ValueError('performance_existing_visual_plan_lost')
    if beat_ref:
        renderer_module()
        from video_creation_pipeline.semantic_editorial import validate_editorial_artifact
        beats = read_ref(beat_ref)
        if beats.get('schema') != 'video_creation_pipeline.editorial_visual_beats.v1':
            raise ValueError('performance_visual_beats_required')
        validate_editorial_artifact(beats)
        selected = [c for c in plan['cues'] if c.get('beat_id')]
        if (len({c['beat_id'] for c in selected}) != len(selected) or
                {c['beat_id'] for c in selected} != {b['scene_id'] for b in beats['beats']}):
            raise ValueError('performance_existing_visual_coverage_required')
        for beat in beats['beats']:
            cue = next(c for c in selected if c['beat_id']==beat['scene_id'])
            if beat['status']=='review_required':
                raise ValueError('performance_existing_visual_review_pending')
            if (cue['start_seconds'] != beat['start_s'] or cue['end_seconds'] != beat['end_s'] or
                    cue['intent'] != beat['semantic_trigger'] or cue['expected_result'] != beat['information_advance']):
                raise ValueError('performance_existing_visual_meaning_or_timing_drift')
    elif any(c.get('beat_id') for c in plan['cues']):
        raise ValueError('performance_visual_beat_reference_missing')
    facts = {r['id']:r for r in manifest['facts']['feedback']}
    for row in purpose_context['feedback']:
        key = 'context:'+row['artifact_id']
        if key in facts:
            raise ValueError('performance_feedback_id_collision')
        facts[key] = dict(ref={k:row['source'][k] for k in ('path','sha256')})
    rows = plan['feedback_dispositions']
    if len({r['id'] for r in rows}) != len(rows) or {r['id'] for r in rows} != set(facts):
        raise ValueError('performance_feedback_coverage_required')
    for row in rows:
        original = facts[row['id']]
        if row['source_ref'] != original['ref'] or ('decision' in original and row['decision'] != original['decision']):
            raise ValueError('performance_feedback_source_or_decision_drift')
        bound(row['source_ref']); purpose.text(row['reason'], 'feedback disposition')
        if not set(row['cue_ids']) <= ids or (row['decision']=='applied' and not row['cue_ids']):
            raise ValueError('applied_feedback_requires_performance_cues')
        if row['decision']=='applied' and not any(by_id[i]['requires_change'] for i in row['cue_ids']):
            raise ValueError('applied_feedback_requires_change_evidence_not_only_review')
    pace = plan['pacing']
    purpose.text(pace['reason'], 'pacing decision and limits')
    observations = pace['observations']
    if (pace['status']=='not_tested') != (len(observations)==0):
        raise ValueError('pacing_status_must_match_supplied_observations')
    observation_ids = set()
    if pace['next_trial_speed'] is not None:
        number(pace['next_trial_speed'])
    for row in observations:
        number(row['speed'])
        number(row['start_seconds']); number(row['end_seconds'])
        if row['id'] in observation_ids:
            raise ValueError('duplicate_pacing_observation')
        observation_ids.add(row['id'])
        if row['media_ref'] != plan['edited_media']:
            raise ValueError('pacing_observation_for_other_media')
        bound(row['evidence_ref'])
        if not 0 <= row['start_seconds'] < row['end_seconds'] <= duration:
            raise ValueError('pacing_observation_range_invalid')
        if row['skip_at_seconds'] is not None and not row['start_seconds'] <= row['skip_at_seconds'] <= row['end_seconds']:
            raise ValueError('pacing_skip_outside_observation')
        purpose.text(row['gist_response'], 'actual gist response; unknown must remain unknown')
        purpose.text(row['note'], 'pacing observation limits')
    return plan


def performance_review_template(manifest, video_ref):
    plan = performance_plan(manifest)
    return dict(plan_sha256=manifest['performance_plan_ref']['sha256'], video_sha256=video_ref['sha256'],
        observations=[dict(cue_id=c['id'], start_seconds=c['start_seconds'], end_seconds=c['end_seconds'],
            status='pending', observation='', change_note='', after_evidence_ref=None) for c in plan['cues']])


def performance_landing(manifest, video_ref, acceptance):
    """Do not promote declared listening/seeing into automated perception."""
    import purpose_continuity as purpose
    plan = performance_plan(manifest)
    review = acceptance.get('performance_review', {})
    if (not isinstance(review, dict) or
            review.get('plan_sha256') != manifest['performance_plan_ref']['sha256'] or
            review.get('video_sha256') != video_ref['sha256']):
        raise ValueError('current_performance_final_review_required')
    bound(video_ref)
    rows = review.get('observations', [])
    if (not isinstance(rows, list) or
            any(not isinstance(r, dict) or not isinstance(r.get('cue_id'), str) for r in rows) or
            len({r.get('cue_id') for r in rows}) != len(rows) or
            {r.get('cue_id') for r in rows} != {c['id'] for c in plan['cues']}):
        raise ValueError('performance_observation_coverage_required')
    for cue in plan['cues']:
        row = next(r for r in rows if r['cue_id']==cue['id'])
        if row.get('status') != 'observed_as_planned':
            raise ValueError('performance_cue_unresolved: '+cue['id'])
        if any(row.get(k) != cue[k] for k in ('start_seconds','end_seconds')):
            raise ValueError('performance_observation_time_drift')
        purpose.text(row.get('observation'), 'what was actually heard/seen at this cue')
        evidence = read_ref(row.get('after_evidence_ref'))
        if (evidence.get('video_ref') != video_ref or evidence.get('cue_id') != cue['id'] or
                evidence.get('plan_sha256') != review['plan_sha256'] or
                evidence.get('observation') != row['observation'] or
                any(evidence.get(k) != cue[k] for k in ('start_seconds','end_seconds'))):
            raise ValueError('performance_evidence_not_bound_to_current_cue_and_final')
        if cue['requires_change']:
            purpose.text(row.get('change_note'), 'actual modification, not only inspection')
            if (cue['before_ref']['sha256'] in {video_ref['sha256'], row['after_evidence_ref']['sha256']} or
                    evidence.get('before_ref') != cue['before_ref'] or evidence.get('change_note') != row['change_note']):
                raise ValueError('performance_revision_evidence_required')
    return dict(status='current_execution_and_review_records_complete', cue_count=len(rows),
        automatic_perceptual_verification=False, audience_effect_verified=False,
        pacing_status=plan['pacing']['status'], pacing_generalization='not_established',
        route_forced=False, publish_authorized=False)


def number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError('finite_time_required')
    return float(value)


def timeline(manifest):
    return validate_timeline(manifest['timeline'], manifest['edited_media'])


def validate_timeline(value, media):
    """Validate one clock against its own encoded media, including declared padding."""
    _, probe = vkp_modules()
    meta = probe(bound(media))
    duration = number(value['duration_seconds'])
    if duration <= 0 or abs(meta.duration_seconds - duration) > .05:
        raise ValueError('timeline_duration_mismatch')
    segments = value['segments']
    if not isinstance(segments, list) or not segments:
        raise ValueError('timeline_segments_required')
    cursor, indexed, media_meta = 0., {}, {}
    for row in segments:
        sid = row['id']
        if not isinstance(sid, str) or not sid or sid in indexed:
            raise ValueError('timeline_segment_id_invalid')
        start, end = number(row['target_start']), number(row['target_end'])
        if abs(start - cursor) > .001 or end <= start or end > duration + .001:
            raise ValueError('timeline_gap_overlap_or_range')
        path = bound(row['source_ref'])
        a, b, rate = number(row['source_start']), number(row['source_end']), number(row['speed'])
        if a < 0 or b <= a or rate <= 0 or abs((b-a)/rate - (end-start)) > .05:
            raise ValueError('source_target_mapping_invalid')
        key = str(path.resolve())
        if key not in media_meta:
            media_meta[key] = probe(path)
        if b > media_meta[key].duration_seconds + .05:
            raise ValueError('source_range_exceeds_media')
        if not str(row.get('purpose', '')).strip():
            raise ValueError('segment_purpose_required')
        indexed[sid] = row
        cursor = end
    padding = number(value.get('trailing_media_padding_seconds', 0))
    if not 0 <= padding <= .5 or abs(cursor + padding - duration) > .001:
        raise ValueError('timeline_tail_unmapped')
    # Explicit empty list is allowed for silent videos; never assume unknown = silent.
    if not isinstance(value.get('expected_audio'), list):
        raise ValueError('expected_audio_inventory_required')
    projected = []
    for sound in value['expected_audio']:
        row = indexed[sound['segment_id']]
        a, b = number(sound['source_start']), number(sound['source_end'])
        if not row['source_start'] <= a < b <= row['source_end']:
            raise ValueError('audio_source_range_invalid')
        if sound.get('kind') not in ('speech', 'singing', 'vocalization'):
            raise ValueError('known_audio_kind_required')
        projected.append(dict(start_seconds=round(row['target_start']+(a-row['source_start'])/row['speed'], 6),
                              end_seconds=round(row['target_start']+(b-row['source_start'])/row['speed'], 6),
                              kind=sound['kind']))
    return dict(duration_seconds=duration, expected_audio=projected, trailing_media_padding_seconds=padding)


def final_timeline(manifest, final=None):
    import video_final_timeline
    if final is None:
        final = desk.normalize(read_ref(manifest['desk_ref']))['items'][0]['video']
    return video_final_timeline.check(manifest, final, validate_timeline)


def subtitle_check(manifest, mapped):
    config = manifest['subtitles']
    if mapped['expected_audio'] and not config.get('asr_ref'):
        raise ValueError('full_edited_audio_asr_required')
    request_path, pack_path = bound(config['request_ref']), bound(config['pack_ref'])
    request = covers.read(request_path)
    if Path(request['source_path']).resolve() != bound(manifest['edited_media']).resolve():
        raise ValueError('coverage_source_path_mismatch')
    if request['source_sha256'] != manifest['edited_media']['sha256']:
        raise ValueError('coverage_source_identity_mismatch')
    actual = [{k: r[k] for k in ('start_seconds', 'end_seconds', 'kind')}
              for r in request.get('expected_audio', [])]
    if sorted(actual, key=fingerprint) != sorted(mapped['expected_audio'], key=fingerprint):
        raise ValueError('known_audio_missing_from_coverage_request')
    check, _ = vkp_modules()
    result = check(request_path, pack_path,
                   asr_path=bound(config['asr_ref']) if config.get('asr_ref') else None,
                   review_path=bound(config['review_ref']) if config.get('review_ref') else None)
    return result


EXTERNAL_EDITOR_RECEIPT_SCHEMA = 'self-media.external-editor-export-receipt.v1'
SUPPORTED_EXTERNAL_EDITORS = {'openchatcut', 'jianying', 'capcut', 'premiere', 'davinci_resolve'}


def _validate_render_step(step):
    schema = step.get('schema')
    if schema == 'video_creation_pipeline.ffmpeg_execution_receipt.v1':
        renderer_module().validate_ffmpeg_execution_receipt(step)
        if step.get('status') != 'completed' or step.get('outlet_id') != 'video_creation_pipeline.single_ffmpeg_outlet':
            raise ValueError('existing_renderer_completed_receipt_required')
        return
    if schema == EXTERNAL_EDITOR_RECEIPT_SCHEMA:
        if step.get('status') != 'completed' or step.get('editor') not in SUPPORTED_EXTERNAL_EDITORS:
            raise ValueError('external_editor_completed_receipt_required')
        proj_ref = step.get('project_file_ref')
        if not isinstance(proj_ref, dict) or bound(proj_ref).stat().st_size == 0:
            raise ValueError('external_editor_project_snapshot_required')
        inputs = step.get('inputs')
        outputs = step.get('outputs')
        if not isinstance(inputs, list) or not inputs or not isinstance(outputs, list) or not outputs:
            raise ValueError('external_editor_inputs_and_outputs_required')
        for item in inputs + outputs:
            if not isinstance(item, dict) or not isinstance(item.get('artifact'), dict):
                raise ValueError('external_editor_artifact_binding_required')
            bound(item['artifact'])
        return
    raise ValueError('existing_renderer_completed_receipt_required')


def render_check(manifest):
    data = desk.normalize(read_ref(manifest['desk_ref']))
    platform_report = desk.check_platforms(data, 'preparation')
    if not platform_report['complete']:
        raise ValueError('platform_requirements_incomplete: ' + json.dumps(platform_report['issues'], ensure_ascii=False))
    packaging = desk.check_packaging(data)
    if not packaging['complete']:
        raise ValueError('packaging_requirements_incomplete: '+json.dumps(packaging['issues'],ensure_ascii=False))
    if data['project_id'] != manifest['project_id'] or len(data['items']) != 1:
        raise ValueError('delivery_requires_matching_single_video_desk')
    final = data['items'][0]['video']
    final_path = bound(final)
    receipt = read_ref(manifest['render_receipt_ref'])
    _validate_render_step(receipt)
    def contains(rows, expected):
        return any(r.get('artifact', {}).get('sha256') == expected['sha256'] and
                   Path(r['artifact']['path']).resolve() == Path(expected['path']).resolve()
                   for r in rows)
    # Rendering can have multiple intermediate steps (e.g. external NLE export or burn then audio balance).
    chain = [read_ref(ref) for ref in manifest.get('render_chain_refs', [])] + [receipt]
    previous = manifest['edited_media']
    for index, step in enumerate(chain):
        _validate_render_step(step)
        if not contains(step.get('inputs', []), previous):
            raise ValueError('render_lineage_mismatch')
        candidates = [r['artifact'] for r in step.get('outputs', []) if r.get('role') in ('candidate', 'fine_cut_preview')]
        if len(candidates) != 1:
            raise ValueError('one_render_candidate_output_required')
        previous = candidates[0]
        bound(previous)
    if not contains(receipt.get('outputs', []), final):
        raise ValueError('desk_video_not_render_output')
    _, probe = vkp_modules()
    meta = probe(final_path)
    if (not meta.width or not meta.height or
            abs(meta.duration_seconds - final_timeline(manifest, final)['duration_seconds']) > .05):
        raise ValueError('final_media_geometry_or_duration_invalid')
    assets = desk.inspect_assets(data)
    if not assets or any(r['status'] != 'verified' for r in assets):
        raise ValueError('desk_assets_missing_changed_or_unhashed')
    editorial = data.get('editorial_context', {})
    if any(editorial.get(k) != manifest['facts'][k] for k in ('story','do_not_infer')):
        raise ValueError('desk_story_not_bound_to_current_facts')
    for key, platform in data['items'][0]['platforms'].items():
        for name in (('body', 'tags') if not desk.platform_policy()['platforms'][key].get('separate_title', True) else ('title', 'body', 'tags')):
            if not platform['fields'][name].strip():
                raise ValueError('publication_copy_incomplete: ' + name)
    return data


def media_acceptance_fingerprint(manifest):
    value = copy.deepcopy(manifest)
    for ignored in (
        'acceptance_ref',
        'context_manifest_ref',
        'final_audio_measurement_ref',
        'final_audio_auto',
        'pacing_report_ref',
        'desk_ref',
        'cover_review_ref',
    ):
        value.pop(ignored, None)
    return fingerprint(value)


def _ass_timestamp_seconds(token):
    match = re.fullmatch(r'(\d+):(\d{1,2}):(\d{1,2}(?:\.\d+)?)', token.strip())
    if not match:
        raise ValueError('invalid_ass_timestamp: ' + token)
    return int(match[1]) * 3600.0 + int(match[2]) * 60.0 + float(match[3])


def parse_ass_dialogue_cues(ass_text):
    import video_overlay_selection as overlays

    columns = ['Layer', 'Start', 'End', 'Style', 'Name', 'MarginL', 'MarginR', 'MarginV', 'Effect', 'Text']
    in_events = False
    cues = []
    badge_style_tokens = ('badge', 'overlay', 'watermark', 'disclaimer', 'identity', 'progress', 'disclosure', 'ai_label', 'title_card', 'card')
    for raw_line in ass_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith('[') and line.endswith(']'):
            in_events = line.casefold() == '[events]'
            continue
        if not in_events:
            continue
        if line.startswith('Format:'):
            parsed_cols = [c.strip() for c in line[7:].split(',')]
            if 'Text' in parsed_cols and 'Start' in parsed_cols and 'End' in parsed_cols:
                columns = parsed_cols
            continue
        if not line.startswith('Dialogue:'):
            continue
        parts = line[9:].lstrip().split(',', len(columns) - 1)
        if len(parts) != len(columns):
            raise ValueError('invalid_ass_dialogue_columns')
        row = dict(zip(columns, parts))
        style = row.get('Style', '').strip()
        style_cf = style.casefold()
        raw_text = row.get('Text', '')
        has_animation = bool(re.search(r'\\(?:move|t\s*\()', raw_text))
        has_override = bool(re.search(r'\{[^}]*\\[^}]*\}', raw_text))
        override_blocks = re.findall(r'\{([^}]*)\}', raw_text)
        raw_clean = re.sub(r'\{[^}]*\}', '', raw_text)
        clean_text = raw_clean.replace('\\N', ' ').replace('\\n', ' ')
        clean_norm = ' '.join(clean_text.split())
        if any(tok in style_cf for tok in badge_style_tokens):
            continue
        if overlays._medical_badge(clean_norm) or re.search(r'执业(?:证)?编号[：:]', clean_norm):
            continue
        if re.fullmatch(r'(?i)(?:ai(?:\s*[-_]\s*assisted|\s*[-_]\s*generated|\s*辅助创作|\s*生成)?|人工智能(?:辅助|生成)?(?:内容)?)', clean_norm):
            continue
        if not clean_norm:
            continue
        cues.append(dict(
            start=round(_ass_timestamp_seconds(row['Start']), 3),
            end=round(_ass_timestamp_seconds(row['End']), 3),
            text=clean_norm,
            raw_clean_text=raw_clean,
            override_blocks=override_blocks,
            style=style,
            has_animation=has_animation,
            has_override=has_override,
        ))
    return cues


def parse_ass_script_and_styles(ass_text):
    info = {}
    styles = {}
    section = None
    columns = None
    for raw_line in ass_text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(';'):
            continue
        if line.startswith('[') and line.endswith(']'):
            section = line.casefold()
            columns = None
            continue
        if section == '[script info]' and ':' in line:
            k, v = line.split(':', 1)
            info[k.strip().casefold()] = v.strip()
        elif section == '[v4+ styles]':
            if line.startswith('Format:'):
                columns = [c.strip() for c in line[7:].split(',')]
            elif line.startswith('Style:') and columns:
                parts = [p.strip() for p in line[6:].lstrip().split(',', len(columns) - 1)]
                if len(parts) != len(columns):
                    raise ValueError('invalid_ass_style_columns')
                row = dict(zip(columns, parts))
                styles[row.get('Name', '').strip()] = row
    return info, styles


def _verify_font_bundle_ref(font_bundle_ref, *, project_root=None, job_inputs=None):
    if not isinstance(font_bundle_ref, dict):
        raise ValueError('unbound_subtitle_fontsdir')
    bundle_path = bound(font_bundle_ref)
    bundle = read_ref(font_bundle_ref)
    if bundle.get('schema') != 'video_creation_pipeline.subtitle_font_bundle.v1':
        raise ValueError('unbound_subtitle_fontsdir')
    raw_dir = bundle.get('fonts_dir')
    if not isinstance(raw_dir, str) or not raw_dir.strip():
        raise ValueError('unbound_subtitle_fontsdir')
    fonts_dir = Path(raw_dir).resolve()
    if not fonts_dir.is_dir():
        raise ValueError('unbound_subtitle_fontsdir')
    if project_root is not None:
        proj = Path(project_root).resolve()
        if not fonts_dir.is_relative_to(proj):
            raise ValueError('unbound_subtitle_fontsdir')
    manifested = bundle.get('files')
    if not isinstance(manifested, list) or not manifested:
        raise ValueError('unbound_subtitle_fontsdir')
    expected_map = {}
    font_refs = []
    for entry in manifested:
        rel = entry.get('relative_path')
        if not isinstance(rel, str) or not rel.strip() or '/' in rel or '\\' in rel or rel in ('.', '..'):
            raise ValueError('unbound_subtitle_fontsdir')
        fp = (fonts_dir / rel).resolve()
        if not fp.is_file() or fp.parent != fonts_dir:
            raise ValueError('unbound_subtitle_fontsdir')
        actual_ref = covers.reference(fp)
        if fp.stat().st_size != int(entry.get('bytes', -1)) or actual_ref['sha256'] != entry.get('sha256'):
            raise ValueError('unbound_subtitle_fontsdir')
        expected_map[rel] = actual_ref
        font_refs.append(actual_ref)
    actual_files = {p.name for p in fonts_dir.iterdir() if p.is_file() or p.is_symlink()}
    if actual_files != set(expected_map):
        raise ValueError('unbound_subtitle_fontsdir')
    if job_inputs is not None:
        def has_artifact(target_ref):
            return any(
                Path(r.get('artifact', {}).get('path', '')).resolve() == Path(target_ref['path']).resolve()
                and r.get('artifact', {}).get('sha256') == target_ref['sha256']
                for r in job_inputs
            )
        if not has_artifact(font_bundle_ref) or any(not has_artifact(fr) for fr in font_refs):
            raise ValueError('unbound_subtitle_fontsdir')
    return {**bundle, 'fonts_dir_resolved': fonts_dir, 'bundle_path': bundle_path, 'font_refs': font_refs}


def _is_v2_subtitle_manifest(manifest):
    sub_cfg = manifest.get('subtitles') or {}
    return bool(
        sub_cfg.get('contract_version') == 'v2'
        or sub_cfg.get('source_route')
        or sub_cfg.get('font_bundle_ref')
        or sub_cfg.get('style_preset')
    )


def _check_no_duplicate_prefix_text(text):
    match = re.match(r'^\s*([^\s：:]{1,20})\s*[：:]\s*([^\s：:]{1,20})\s*[：:]', str(text or ''))
    if match and match.group(1) == match.group(2):
        raise ValueError('duplicate_subtitle_speaker_prefix')


def _parse_ass_color(token):
    match = re.fullmatch(r'&H([0-9A-Fa-f]{2})([0-9A-Fa-f]{2})([0-9A-Fa-f]{2})([0-9A-Fa-f]{2})&?', str(token or '').strip())
    if not match:
        raise ValueError('invalid_ass_color_token: ' + str(token))
    alpha = int(match.group(1), 16)
    b = int(match.group(2), 16)
    g = int(match.group(3), 16)
    r = int(match.group(4), 16)
    return alpha, r, g, b


def _ass_1c_to_hex(token):
    match = re.fullmatch(r'&H([0-9A-Fa-f]{2})([0-9A-Fa-f]{2})([0-9A-Fa-f]{2})&?', str(token or '').strip())
    if not match:
        return None
    b, g, r = match.group(1), match.group(2), match.group(3)
    return f"#{r.upper()}{g.upper()}{b.upper()}"


def _wcag_contrast_rgb(rgb1, rgb2):
    def _lum(rgb):
        def _c(v):
            x = v / 255.0
            return x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4
        return 0.2126 * _c(rgb[0]) + 0.7152 * _c(rgb[1]) + 0.0722 * _c(rgb[2])
    l1, l2 = _lum(rgb1), _lum(rgb2)
    return (max(l1, l2) + 0.05) / (min(l1, l2) + 0.05)


def _validate_override_block_tokens(block, *, exp_event=None, border_style=1, min_font_px=48.0):
    """Lexical token-level whitelist check for every ASS {...} override tag."""
    tokens = re.findall(r'\\[^\\]+', block)
    if not tokens and block.strip():
        raise ValueError('invalid_subtitle_inline_override: unparsed_block')
    allowed_colors = None
    allowed_sizes = None
    if exp_event is not None:
        allowed_sizes = {int(exp_event['base_font_px'])}
        if exp_event.get('emphasis_font_px') is not None:
            allowed_sizes.add(int(exp_event['emphasis_font_px']))
        allowed_colors = {str(exp_event['base_color_hex']).upper()}
        if exp_event.get('emphasis_color_hex'):
            allowed_colors.add(str(exp_event['emphasis_color_hex']).upper())
        if exp_event.get('tone_color_hex'):
            allowed_colors.add(str(exp_event['tone_color_hex']).upper())
    for tok in tokens:
        t = tok.strip()
        if t in ('\\b0', '\\b700'):
            continue
        m_fs = re.fullmatch(r'\\fs([0-9]+(?:\.[0-9]+)?)', t)
        if m_fs:
            fs_val = float(m_fs.group(1))
            if fs_val < min_font_px - 1e-6:
                raise ValueError('invalid_subtitle_inline_override: font_shrunk')
            if allowed_sizes is not None and round(fs_val) not in allowed_sizes:
                raise ValueError('invalid_subtitle_inline_override: unapproved_font_size')
            continue
        m_1c = re.fullmatch(r'\\1c(&H[0-9A-Fa-f]{6}&)', t)
        if m_1c:
            hx = _ass_1c_to_hex(m_1c.group(1))
            if allowed_colors is not None and hx not in allowed_colors:
                raise ValueError('invalid_subtitle_inline_override: unapproved_color')
            continue
        if border_style == 3:
            if re.fullmatch(r'\\xbord(?:0|[1-9][0-9]*)', t) or re.fullmatch(r'\\ybord[1-9][0-9]*', t):
                continue
        raise ValueError('invalid_subtitle_inline_override: forbidden_tag_' + t)


def verify_audio_timeline_alignment(source_probe, delivered_probe, *, max_offset_s=0.02):
    """Verify sample rate, channels, duration/samples, start PTS, and AV offset beyond raw audio hashes."""
    for key in ('sample_rate', 'channels'):
        if source_probe.get(key) != delivered_probe.get(key):
            raise ValueError(f'audio_timeline_stream_mismatch: {key}')
    src_dur = float(source_probe.get('duration_s', 0.0))
    del_dur = float(delivered_probe.get('duration_s', 0.0))
    if abs(src_dur - del_dur) > max_offset_s:
        raise ValueError('audio_timeline_duration_mismatch')
    src_pts = float(source_probe.get('audio_start_pts_s', 0.0))
    del_pts = float(delivered_probe.get('audio_start_pts_s', 0.0))
    if abs(src_pts - del_pts) > max_offset_s:
        raise ValueError('audio_timeline_offset_mismatch')
    src_av = float(source_probe.get('audio_start_pts_s', 0.0)) - float(source_probe.get('video_start_pts_s', 0.0))
    del_av = float(delivered_probe.get('audio_start_pts_s', 0.0)) - float(delivered_probe.get('video_start_pts_s', 0.0))
    if abs(src_av - del_av) > max_offset_s:
        raise ValueError('audio_timeline_av_sync_offset_mismatch')
    return {'aligned': True, 'audio_start_pts_delta_s': round(del_pts - src_pts, 4), 'av_offset_delta_s': round(del_av - src_av, 4)}


def _verify_ass_style_and_overrides(ass_content, observed, expected_cues, *, preset_id, bundle, expected_plan=None):
    info, styles = parse_ass_script_and_styles(ass_content)
    try:
        play_x = int(info.get('playresx', '0'))
        play_y = int(info.get('playresy', '0'))
    except ValueError as exc:
        raise ValueError('invalid_ass_playres') from exc
    if play_x <= 0 or play_y <= 0:
        raise ValueError('invalid_ass_playres')
    if preset_id in ('stroke_shadow_default', 'box_stroke_bs4') or expected_plan is not None:
        if info.get('ycbcr matrix', '').casefold() != 'tv.709':
            raise ValueError('missing_ass_ycbcr_tv709_matrix')
    min_font_px = 48.0 * min(play_x, play_y) / 1080.0
    expected_families = {bundle.get('family'), bundle.get('localized_family')} - {None, ''}
    active_styles = {obs['style'] for obs in observed}
    if not active_styles and 'Default' in styles:
        active_styles = {'Default'}
    detected_bs = 1
    for style_name in active_styles:
        st = styles.get(style_name)
        if not st:
            raise ValueError('missing_ass_style_definition: ' + style_name)
        fontname = st.get('Fontname', '').strip()
        if not fontname or fontname.casefold() == 'arial':
            raise ValueError('forbidden_arial_or_empty_subtitle_font: ' + fontname)
        if expected_families and fontname not in expected_families:
            raise ValueError('unbound_subtitle_font_family: ' + fontname)
        try:
            fontsize = float(st.get('Fontsize', '0'))
            border_style = int(st.get('BorderStyle', '0'))
            outline = float(st.get('Outline', '0'))
            shadow = float(st.get('Shadow', '0'))
            scale_x = float(st.get('ScaleX', '100'))
            scale_y = float(st.get('ScaleY', '100'))
        except ValueError as exc:
            raise ValueError('invalid_ass_style_numeric_field') from exc
        if fontsize < min_font_px - 1e-6 or scale_x < 100.0 - 1e-6 or scale_y < 100.0 - 1e-6:
            raise ValueError('subtitle_font_below_minimum')
        detected_bs = border_style
        pa, pr, pg, pb = _parse_ass_color(st.get('PrimaryColour', ''))
        if pa != 0:
            raise ValueError('subtitle_primary_color_must_be_opaque')
        oa, or_, og, ob = _parse_ass_color(st.get('OutlineColour', ''))
        ba, br, bg_, bb = _parse_ass_color(st.get('BackColour', ''))
        if preset_id == 'stroke_shadow_default':
            if border_style != 1:
                raise ValueError('invalid_subtitle_backing_style')
            if outline < 3.0 - 1e-6 or oa > 0x20 or max(or_, og, ob) > 48:
                raise ValueError('invalid_subtitle_outline_backing')
            if shadow < 1.5 - 1e-6 or max(br, bg_, bb) > 48:
                raise ValueError('invalid_subtitle_shadow_backing')
            backing_rgb = (or_, og, ob)
        elif preset_id == 'box_stroke_bs4':
            if border_style != 4:
                raise ValueError('invalid_subtitle_backing_style')
            if outline < 1.5 - 1e-6 or oa > 0x20 or max(or_, og, ob) > 48:
                raise ValueError('invalid_subtitle_outline_backing')
            if shadow < 6.0 - 1e-6 or not (0x26 <= ba <= 0x80) or max(br, bg_, bb) > 48:
                raise ValueError('invalid_subtitle_box_color_or_opacity')
            backing_rgb = (or_, og, ob)
        elif preset_id == 'accessible_box_a':
            if border_style != 3:
                raise ValueError('invalid_subtitle_backing_style')
            if oa == 0 or not 0x26 <= oa <= 0x73 or max(or_, og, ob) > 48:
                raise ValueError('invalid_subtitle_box_color_or_opacity')
            if outline < 4:
                raise ValueError('invalid_subtitle_box_padding')
            alpha_op = 1.0 - oa / 255.0
            backing_rgb = (
                round(alpha_op * or_ + (1.0 - alpha_op) * 255.0),
                round(alpha_op * og + (1.0 - alpha_op) * 255.0),
                round(alpha_op * ob + (1.0 - alpha_op) * 255.0),
            )
        elif preset_id == 'outline_v2_c':
            if border_style != 1:
                raise ValueError('invalid_subtitle_backing_style')
            min_outline = max(4.0, round(min(play_x, play_y) * 0.005))
            if outline < min_outline or oa > 0x20 or max(or_, og, ob) > 96:
                raise ValueError('invalid_subtitle_outline_backing')
            backing_rgb = (or_, og, ob)
        else:
            raise ValueError('unknown_subtitle_style_preset: ' + str(preset_id))

        contrast = _wcag_contrast_rgb((pr, pg, pb), backing_rgb)
        if contrast < 4.5:
            raise ValueError(f'subtitle_primary_color_contrast_below_floor: {contrast:.2f}:1')

    if expected_plan is not None:
        for obs, exp_ev in zip(observed, expected_plan['expected_events']):
            for block in obs.get('override_blocks', ()):
                _validate_override_block_tokens(block, exp_event=exp_ev, border_style=detected_bs, min_font_px=min_font_px)
    else:
        for obs, exp in zip(observed, expected_cues):
            motion = exp.get('motion', 'none')
            if motion == 'none':
                for block in obs.get('override_blocks', ()):
                    _validate_override_block_tokens(block, exp_event=None, border_style=detected_bs, min_font_px=min_font_px)
    return dict(play_res_x=play_x, play_res_y=play_y, min_font_px=min_font_px, styles=sorted(active_styles))


def _expected_cue_display_text(exp, subtitle_sequence):
    if exp.get('display_text'):
        return str(exp['display_text'])
    spoken = str(exp.get('spoken_text') if exp.get('spoken_text') is not None else exp.get('text', ''))
    prefix_raw = exp.get('speaker_prefix')
    if prefix_raw is None and (exp.get('offscreen_speaker') or exp.get('show_speaker_prefix')) and exp.get('speaker'):
        prefix_raw = exp.get('speaker')
    sound_raw = exp.get('sound_event') if exp.get('sound_event') is not None else exp.get('non_speech')
    if prefix_raw is None and sound_raw is None:
        return spoken
    prefix = subtitle_sequence._normalize_speaker_prefix(prefix_raw)
    sound = subtitle_sequence._normalize_sound_event(sound_raw)
    return subtitle_sequence.assemble_display_text(
        spoken_text=spoken,
        speaker_prefix=prefix,
        sound_token=sound,
        sound_position=str(exp.get('sound_position') or 'prefix'),
    )


def parse_ass_all_visible_texts(ass_text):
    columns = ['Layer', 'Start', 'End', 'Style', 'Name', 'MarginL', 'MarginR', 'MarginV', 'Effect', 'Text']
    in_events = False
    rows = []
    for raw_line in ass_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith('[') and line.endswith(']'):
            in_events = line.casefold() == '[events]'
            continue
        if not in_events:
            continue
        if line.startswith('Format:'):
            parsed_cols = [c.strip() for c in line[7:].split(',')]
            if 'Text' in parsed_cols and 'Start' in parsed_cols and 'End' in parsed_cols:
                columns = parsed_cols
            continue
        if not line.startswith('Dialogue:'):
            continue
        parts = line[9:].lstrip().split(',', len(columns) - 1)
        if len(parts) != len(columns):
            continue
        row = dict(zip(columns, parts))
        clean = re.sub(r'\{[^}]*\}', '', row.get('Text', '')).replace('\\N', ' ').replace('\\n', ' ')
        clean_norm = ' '.join(clean.split())
        if clean_norm:
            rows.append(dict(style=row.get('Style', '').strip(), text=clean_norm))
    return rows


def _scan_burned_text_violations(manifest, visible_texts):
    do_not_infer = list((manifest.get('facts') or {}).get('do_not_infer') or [])
    forbidden = []
    if manifest.get('desk_ref'):
        try:
            desk_doc = read_ref(manifest['desk_ref'])
            forbidden = list((desk_doc.get('editorial_context') or {}).get('forbidden_public_phrases') or [])
        except Exception:
            forbidden = []
    sub_cfg = manifest.get('subtitles') or {}
    corrections = {}
    if isinstance(sub_cfg.get('typo_corrections'), dict):
        corrections.update(sub_cfg['typo_corrections'])
    if sub_cfg.get('typo_corrections_ref'):
        corrections.update(read_ref(sub_cfg['typo_corrections_ref']))
    for entry in visible_texts:
        txt = entry['text']
        for term in do_not_infer + forbidden:
            if isinstance(term, str) and term.strip() and term in txt:
                raise ValueError(f"burn_overlay_or_subtitle_text_violation: {term} in [{entry['style']}]")
        for typo, expected in corrections.items():
            if isinstance(typo, str) and typo.strip() and typo in txt:
                raise ValueError(f"burn_overlay_or_subtitle_typo_detected: {typo} (expected {expected}) in [{entry['style']}]")


def _srt_timestamp_seconds(token):
    match = re.fullmatch(r'(?:(\d+):)?(\d{1,2}):(\d{1,2})(?:[,.](\d{1,3}))?', str(token or '').strip())
    if not match:
        raise ValueError('invalid_subtitle_timestamp: ' + str(token))
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2))
    seconds = int(match.group(3))
    ms_text = (match.group(4) or '0').ljust(3, '0')
    return round(hours * 3600.0 + minutes * 60.0 + seconds + int(ms_text) / 1000.0, 3)


def _parse_raw_srt_vtt_cues(subtitle_path):
    raw_text = Path(subtitle_path).read_text(encoding='utf-8-sig')
    normalized = raw_text.replace('\r\n', '\n').replace('\r', '\n').strip()
    if not normalized:
        return []
    blocks = re.split(r'\n{2,}', normalized)
    cues = []
    for block in blocks:
        lines = [ln.rstrip() for ln in block.split('\n') if ln.strip()]
        if not lines:
            continue
        if lines[0].upper().startswith('WEBVTT') or lines[0].upper().startswith(('NOTE', 'STYLE', 'REGION')):
            continue
        ts_idx = None
        for idx, line in enumerate(lines):
            if '-->' in line:
                ts_idx = idx
                break
        if ts_idx is None:
            continue
        left, right = [part.strip() for part in lines[ts_idx].split('-->', 1)]
        right_ts = right.split()[0]
        body_lines = lines[ts_idx + 1 :]
        raw_clean = '\n'.join(body_lines)
        cues.append(dict(
            start=_srt_timestamp_seconds(left),
            end=_srt_timestamp_seconds(right_ts),
            text=' '.join(' '.join(line.split()) for line in body_lines),
            raw_clean_text=raw_clean,
        ))
    return cues


def _expected_cues_from_pack(pack):
    expected_cues = [c for row in pack.get('requests', []) for c in row.get('subtitle_cues', [])]
    if not expected_cues:
        expected_cues = list(pack.get('cues', []))
    return expected_cues


def _cue_bounds_seconds(cue):
    start_val = cue['start_seconds'] if 'start_seconds' in cue else cue['start_s']
    end_val = cue['end_seconds'] if 'end_seconds' in cue else cue['end_s']
    return float(start_val), float(end_val)


def _verify_ass_against_cues(
    manifest,
    subtitle,
    expected_cues,
    *,
    time_offset=0.0,
    preset_id=None,
    bundle=None,
    v2_mode=False,
    sub_seq_mod=None,
    local_duration_limit=None,
    expected_plan=None,
):
    import video_overlay_selection as overlays

    ass_content = Path(subtitle).read_text(encoding='utf-8-sig')
    overlay_result = overlays.check_ass(overlays.for_manifest(manifest), Path(subtitle))
    observed = parse_ass_dialogue_cues(ass_content)
    _scan_burned_text_violations(manifest, parse_ass_all_visible_texts(ass_content))

    if expected_plan is not None:
        exp_events = list(expected_plan.get('expected_events') or [])
        if len(observed) != len(exp_events):
            raise ValueError('burn_file_disagrees_with_expected_plan_event_count')
        speech_by_cue = {}
        for obs, exp_ev in zip(observed, exp_events):
            _check_no_duplicate_prefix_text(obs['text'])
            if local_duration_limit is not None:
                if obs['start'] < -1e-6 or obs['end'] > float(local_duration_limit) + 0.06:
                    raise ValueError('segment_ass_timestamp_exceeds_scene_bounds')
            obs_global_start = round(obs['start'] + float(time_offset), 3)
            obs_global_end = round(obs['end'] + float(time_offset), 3)
            if abs(obs_global_start - float(exp_ev['start_s'])) > 0.02 or abs(obs_global_end - float(exp_ev['end_s'])) > 0.02:
                raise ValueError('burn_file_disagrees_with_expected_plan_timing')
            vis_dur = round(obs['end'] - obs['start'], 3)
            if vis_dur < 0.50 - 1e-6:
                raise ValueError('burn_file_subsegment_below_minimum_duration')
            if float(exp_ev.get('sub_segment_cps', 0.0)) > 9.0 + 1e-6:
                raise ValueError('burn_file_subsegment_exceeds_cps')
            if obs['style'] != exp_ev['style_name']:
                raise ValueError('burn_file_disagrees_with_expected_plan_style')
            obs_norm_lines = obs['raw_clean_text'].replace('\\n', '\\N').split('\\N')
            if obs_norm_lines != list(exp_ev['expected_visible_lines']):
                raise ValueError('burn_file_disagrees_with_expected_plan_text')
            if obs['has_animation']:
                raise ValueError('burn_file_unauthorized_animation')
            cid = exp_ev['source_cue_id']
            speech_by_cue.setdefault(cid, []).append(exp_ev.get('speech_reconstruction', ''))
        for exp_c in expected_cues:
            cid = exp_c.get('cue_id')
            if cid and cid in speech_by_cue:
                rebuilt = ''.join(speech_by_cue[cid])
                if rebuilt != exp_c.get('spoken_text', exp_c.get('text', '')):
                    raise ValueError('expected_plan_speech_reconstruction_mismatch')
        style_audit = None
        if v2_mode or bundle is not None:
            sub_cfg = manifest.get('subtitles') or {}
            eff_bundle = bundle if bundle is not None else _verify_font_bundle_ref(sub_cfg.get('font_bundle_ref'))
            eff_preset = str(preset_id or expected_plan.get('preset_id') or sub_cfg.get('style_preset') or 'stroke_shadow_default')
            style_audit = _verify_ass_style_and_overrides(
                ass_content, observed, expected_cues, preset_id=eff_preset, bundle=eff_bundle, expected_plan=expected_plan
            )
        return dict(
            format='ass',
            subtitle_sha256=covers.reference(subtitle)['sha256'],
            cue_count=len(observed),
            delivery_status=expected_plan.get('delivery_status', 'PASS'),
            fallback_reasons=list(expected_plan.get('fallback_reasons') or []),
            overlay=overlay_result,
            style_audit=style_audit,
            observed_cues=observed,
        )

    if len(observed) != len(expected_cues):
        raise ValueError('burn_file_disagrees_with_reviewed_cues')
    speaker_styles = {}
    for obs, exp in zip(observed, expected_cues):
        _check_no_duplicate_prefix_text(obs['text'])
        if local_duration_limit is not None:
            if obs['start'] < -1e-6 or obs['end'] > float(local_duration_limit) + 0.06:
                raise ValueError('segment_ass_timestamp_exceeds_scene_bounds')
        exp_start, exp_end = _cue_bounds_seconds(exp)
        obs_global_start = obs['start'] + float(time_offset)
        obs_global_end = obs['end'] + float(time_offset)
        if abs(obs_global_start - exp_start) > 0.06 or abs(obs_global_end - exp_end) > 0.06:
            raise ValueError('burn_file_disagrees_with_reviewed_cues')
        if v2_mode or exp.get('layout_breaks') is not None or '\\N' in obs.get('raw_clean_text', ''):
            if sub_seq_mod is None:
                sub_seq_mod, _, _, _ = subtitle_modules()
            exp_display = _expected_cue_display_text(exp, sub_seq_mod)
            matched, _ = sub_seq_mod.reconcile_observed_lines(
                obs['raw_clean_text'], exp_display, exp.get('layout_breaks')
            )
            if not matched:
                raise ValueError('burn_file_disagrees_with_reviewed_cues')
        else:
            exp_norm = ' '.join(str(exp.get('text', '')).split())
            if obs['text'] != exp_norm:
                raise ValueError('burn_file_disagrees_with_reviewed_cues')
        speaker = exp.get('speaker')
        if speaker:
            prev_style = speaker_styles.setdefault(speaker, obs['style'])
            if prev_style != obs['style']:
                raise ValueError('burn_file_disagrees_with_reviewed_cues')
        motion = exp.get('motion', 'none')
        if motion == 'none' and obs['has_animation']:
            raise ValueError('burn_file_disagrees_with_reviewed_cues')
        if motion != 'none' and not (obs['has_override'] or obs['has_animation'] or obs['style'].casefold() not in {'default', 'dialogue', 'subtitle', 'subtitles'}):
            raise ValueError('burn_file_disagrees_with_reviewed_cues')
    style_audit = None
    if v2_mode:
        sub_cfg = manifest.get('subtitles') or {}
        eff_bundle = bundle if bundle is not None else _verify_font_bundle_ref(sub_cfg.get('font_bundle_ref'))
        eff_preset = str(preset_id or sub_cfg.get('style_preset') or 'stroke_shadow_default')
        style_audit = _verify_ass_style_and_overrides(
            ass_content, observed, expected_cues, preset_id=eff_preset, bundle=eff_bundle
        )
    return dict(
        format='ass',
        subtitle_sha256=covers.reference(subtitle)['sha256'],
        cue_count=len(observed),
        delivery_status='PASS',
        overlay=overlay_result,
        style_audit=style_audit,
        observed_cues=observed,
    )


def _verify_srt_vtt_against_cues(manifest, subtitle, expected_cues, *, v2_mode=False, sub_seq_mod=None):
    subtitle = Path(subtitle)
    suffix = subtitle.suffix.lower()
    if v2_mode:
        parsed_rows = _parse_raw_srt_vtt_cues(subtitle)
        _scan_burned_text_violations(manifest, [dict(style='subtitle', text=row['text']) for row in parsed_rows])
        if len(parsed_rows) != len(expected_cues):
            raise ValueError('burn_file_disagrees_with_reviewed_cues')
        if sub_seq_mod is None:
            sub_seq_mod, _, _, _ = subtitle_modules()
        for obs, exp in zip(parsed_rows, expected_cues):
            _check_no_duplicate_prefix_text(obs['raw_clean_text'])
            exp_start, exp_end = _cue_bounds_seconds(exp)
            if abs(round(obs['start'], 3) - round(exp_start, 3)) > 0.06 or abs(
                round(obs['end'], 3) - round(exp_end, 3)
            ) > 0.06:
                raise ValueError('burn_file_disagrees_with_reviewed_cues')
            exp_display = _expected_cue_display_text(exp, sub_seq_mod)
            matched, _ = sub_seq_mod.reconcile_observed_lines(
                obs['raw_clean_text'], exp_display, exp.get('layout_breaks')
            )
            if not matched:
                raise ValueError('burn_file_disagrees_with_reviewed_cues')
        return dict(format=suffix.lstrip('.'), subtitle_sha256=covers.reference(subtitle)['sha256'], cue_count=len(parsed_rows))

    from video_knowledge_pipeline.transcript import parse_transcript

    parsed_cues = parse_transcript(subtitle)
    _scan_burned_text_violations(manifest, [dict(style='subtitle', text=' '.join(c.text.split())) for c in parsed_cues])
    if len(parsed_cues) != len(expected_cues):
        raise ValueError('burn_file_disagrees_with_reviewed_cues')
    for parsed_cue, exp in zip(parsed_cues, expected_cues):
        _check_no_duplicate_prefix_text(parsed_cue.text)
        exp_start, exp_end = _cue_bounds_seconds(exp)
        if abs(round(parsed_cue.start, 3) - round(exp_start, 3)) > 0.06 or abs(
            round(parsed_cue.end, 3) - round(exp_end, 3)
        ) > 0.06:
            raise ValueError('burn_file_disagrees_with_reviewed_cues')
        if exp.get('layout_breaks') is not None or '\n' in parsed_cue.text:
            if sub_seq_mod is None:
                sub_seq_mod, _, _, _ = subtitle_modules()
            exp_display = _expected_cue_display_text(exp, sub_seq_mod)
            matched, _ = sub_seq_mod.reconcile_observed_lines(
                parsed_cue.text, exp_display, exp.get('layout_breaks')
            )
            if not matched:
                raise ValueError('burn_file_disagrees_with_reviewed_cues')
        else:
            if ' '.join(parsed_cue.text.split()) != ' '.join(exp['text'].split()):
                raise ValueError('burn_file_disagrees_with_reviewed_cues')
    return dict(format=suffix.lstrip('.'), subtitle_sha256=covers.reference(subtitle)['sha256'], cue_count=len(parsed_cues))


def verify_subtitle_burn_file(manifest, subtitle_path=None):
    ref = manifest.get('subtitles', {}).get('render_file_ref')
    if subtitle_path is None:
        if ref is None:
            raise ValueError('subtitle_burn_file_not_bound')
        subtitle = bound(ref)
    else:
        subtitle = Path(subtitle_path)
    pack = read_ref(manifest['subtitles']['pack_ref'])
    expected_cues = _expected_cues_from_pack(pack)
    v2_mode = _is_v2_subtitle_manifest(manifest)
    sub_seq_mod, _, _, _ = subtitle_modules() if v2_mode else (None, None, None, None)
    suffix = subtitle.suffix.lower()
    if suffix == '.ass':
        res = _verify_ass_against_cues(
            manifest, subtitle, expected_cues, v2_mode=v2_mode, sub_seq_mod=sub_seq_mod
        )
        res.pop('observed_cues', None)
        return res
    if suffix in ('.srt', '.vtt'):
        return _verify_srt_vtt_against_cues(
            manifest, subtitle, expected_cues, v2_mode=v2_mode, sub_seq_mod=sub_seq_mod
        )
    raise ValueError('unsupported_subtitle_burn_format: ' + suffix)


def _decode_ffmpeg_filter_path(token):
    return str(token).replace(r'\:', ':').replace(r'\\', '\\')


def _extract_subtitle_filter_calls(command):
    if not isinstance(command, list):
        return []
    calls = []
    filter_flags = {'-vf', '-af', '-filter:v', '-filter_complex'}
    call_re = re.compile(
        r"(?:^|(?<=[,;\]]))\s*(?:\[[^\]]+\]\s*)*(subtitles|ass)=(?:filename=)?'([^']+)'((?::(?:fontsdir|force_style)='[^']*')*)(?:\s*\[[^\]]+\])*(?=\s*(?:[,;]|$))"
    )
    for idx, tok in enumerate(command):
        if tok not in filter_flags or idx + 1 >= len(command):
            continue
        expr = str(command[idx + 1])
        has_sub_kw = bool(re.search(r'(?i)(?:^|[,;\]\s])(?:subtitles|ass)\s*=', expr))
        has_fontsdir = bool(re.search(r'(?i)fontsdir', expr))
        if not has_sub_kw:
            if has_fontsdir:
                raise ValueError('unbound_filter_file_not_allowed')
            continue
        if tok == '-af':
            raise ValueError('use_bound_standalone_subtitle_filter')
        matches = list(call_re.finditer(expr))
        raw_count = len(re.findall(r'(?i)(?:^|[,;\]\s])(?:subtitles|ass)\s*=', expr))
        if not matches or len(matches) != raw_count:
            if has_fontsdir:
                raise ValueError('unbound_filter_file_not_allowed')
            raise ValueError('use_bound_standalone_subtitle_filter')
        expr_calls = []
        for m in matches:
            filter_name, raw_sub, opts_tail = m.group(1), m.group(2), m.group(3)
            opts = re.findall(r":(fontsdir|force_style)='([^']*)'", opts_tail)
            if sum(len(k) + len(v) + 4 for k, v in opts) != len(opts_tail):
                if has_fontsdir:
                    raise ValueError('unbound_filter_file_not_allowed')
                raise ValueError('use_bound_standalone_subtitle_filter')
            opt_map = {}
            for k, v in opts:
                if k in opt_map:
                    raise ValueError('use_bound_standalone_subtitle_filter')
                opt_map[k] = v
            expr_calls.append(dict(
                flag=tok,
                filter=filter_name,
                subtitle_path=Path(_decode_ffmpeg_filter_path(raw_sub)).resolve(),
                fontsdir_path=Path(_decode_ffmpeg_filter_path(opt_map['fontsdir'])).resolve() if 'fontsdir' in opt_map and opt_map['fontsdir'].strip() else None,
                fontsdir_present='fontsdir' in opt_map,
                force_style=opt_map.get('force_style'),
            ))
        unquoted_expr = re.sub(r"'[^']*'", "''", expr)
        if len(re.findall(r'(?i)fontsdir', unquoted_expr)) != sum(1 for c in expr_calls if c['fontsdir_present']):
            raise ValueError('unbound_filter_file_not_allowed')
        calls.extend(expr_calls)
    return calls


def _reconcile_sidecar_srt(manifest):
    sub_cfg = manifest.get('subtitles') or {}
    srt_ref = sub_cfg.get('sidecar_srt_ref')
    if not isinstance(srt_ref, dict):
        raise ValueError('sidecar_srt_ref_required')
    srt_path = bound(srt_ref)
    if srt_path.suffix.lower() not in ('.srt', '.vtt'):
        raise ValueError('sidecar_srt_invalid_format')
    pack = read_ref(sub_cfg['pack_ref'])
    expected_cues = _expected_cues_from_pack(pack)
    sub_seq_mod, _, _, _ = subtitle_modules()
    res = _verify_srt_vtt_against_cues(
        manifest, srt_path, expected_cues, v2_mode=True, sub_seq_mod=sub_seq_mod
    )
    return {**res, 'ref': srt_ref, 'path_resolved': srt_path.resolve()}


def _ref_in_list(target_ref, ref_list):
    if not isinstance(target_ref, dict) or not isinstance(target_ref.get('path'), str):
        return False
    target_path = Path(target_ref['path']).resolve()
    target_sha = target_ref.get('sha256')
    return any(
        isinstance(item, dict)
        and isinstance(item.get('path'), str)
        and Path(item['path']).resolve() == target_path
        and item.get('sha256') == target_sha
        for item in (ref_list or [])
    )


def _step_has_artifact(step, ref):
    if not isinstance(ref, dict) or not isinstance(ref.get('path'), str):
        return False
    target_path = Path(ref['path']).resolve()
    target_sha = ref.get('sha256')
    return any(
        isinstance(row.get('artifact'), dict)
        and isinstance(row['artifact'].get('path'), str)
        and Path(row['artifact']['path']).resolve() == target_path
        and row['artifact'].get('sha256') == target_sha
        for row in step.get('inputs', [])
    )


def _audit_v2_subtitle_lineage(manifest, *, chain_receipts, final_ref):
    sub_cfg = manifest.get('subtitles') or {}
    source_route = sub_cfg.get('source_route')
    if source_route not in ('audio_timeline_segmented', 'video_delivery_clean_burn', 'remotion_rendered'):
        raise ValueError('invalid_subtitle_source_route')
    sub_seq_mod, sub_styles_mod, _, remotion_mod = subtitle_modules()
    preset_id = str(sub_cfg.get('style_preset') or 'stroke_shadow_default')
    if preset_id not in ('accessible_box_a', 'outline_v2_c', 'stroke_shadow_default', 'box_stroke_bs4'):
        raise ValueError('unknown_subtitle_style_preset: ' + preset_id)

    sidecar = _reconcile_sidecar_srt(manifest)
    request = read_ref(sub_cfg['request_ref'])
    ev_files = request.get('evidence_files', [])
    pack = read_ref(sub_cfg['pack_ref'])
    expected_cues = _expected_cues_from_pack(pack)

    step_calls = [(step, _extract_subtitle_filter_calls(step.get('command'))) for step in chain_receipts]
    burn_steps = [(step, calls) for step, calls in step_calls if calls]

    if source_route == 'video_delivery_clean_burn':
        burned_ref = sub_cfg.get('render_file_ref')
        if not isinstance(burned_ref, dict):
            raise ValueError('subtitle_burn_file_not_bound')
        if not _ref_in_list(burned_ref, ev_files):
            raise ValueError('subtitle_file_not_in_coverage_review_fingerprint')
        burned_path = bound(burned_ref)
        if burned_path.suffix.lower() != '.ass':
            raise ValueError('v2_clean_burn_requires_ass_file')
        verified = verify_subtitle_burn_file(manifest)
        if len(burn_steps) > 1:
            raise ValueError('double_subtitle_burn_not_allowed_for_source_route')
        if not burn_steps:
            raise ValueError('missing_subtitle_burn_receipt_step')
        burn_step, calls = burn_steps[0]
        if len(calls) != 1:
            raise ValueError('use_bound_standalone_subtitle_filter')
        call = calls[0]
        if call['force_style'] is not None:
            raise ValueError('force_style_not_allowed_for_managed_ass')
        if call['subtitle_path'] != burned_path.resolve() or not _step_has_artifact(burn_step, burned_ref):
            raise ValueError('render_subtitle_file_not_bound')
        bundle = _verify_font_bundle_ref(sub_cfg.get('font_bundle_ref'), job_inputs=burn_step.get('inputs', []))
        if not call['fontsdir_present'] or call['fontsdir_path'] != bundle['fonts_dir_resolved']:
            raise ValueError('unbound_subtitle_fontsdir')
        return dict(
            source_route=source_route,
            style_preset=preset_id,
            sidecar_srt=sidecar['subtitle_sha256'],
            burned_subtitles=verified,
            font_sha256=bundle['files'][0]['sha256'],
        )

    if burn_steps:
        raise ValueError('double_subtitle_burn_not_allowed_for_source_route')

    if source_route == 'audio_timeline_segmented':
        if sub_cfg.get('render_file_ref') is not None:
            rf = sub_cfg['render_file_ref']
            rf_path = bound(rf)
            if rf_path.suffix.lower() == '.ass':
                raise ValueError('double_subtitle_burn_not_allowed_for_source_route')
            if not _ref_in_list(rf, ev_files):
                raise ValueError('subtitle_file_not_in_coverage_review_fingerprint')
        elif not _ref_in_list(sub_cfg.get('sidecar_srt_ref'), ev_files):
            raise ValueError('subtitle_file_not_in_coverage_review_fingerprint')
        at_ref = sub_cfg.get('audio_timeline_manifest_ref')
        if not isinstance(at_ref, dict):
            raise ValueError('audio_timeline_manifest_ref_required')
        at_manifest = read_ref(at_ref)
        if (at_manifest.get('schema') != 'video_creation_pipeline.audio_timeline_render.v1'
                or at_manifest.get('subtitle_source_route') != 'audio_timeline_segmented'):
            raise ValueError('invalid_audio_timeline_manifest')
        at_srt = at_manifest.get('sidecar_srt')
        if (not isinstance(at_srt, dict)
                or bound(at_srt).resolve() != sidecar['path_resolved']
                or at_srt.get('sha256') != sidecar['subtitle_sha256']):
            raise ValueError('audio_timeline_sidecar_srt_mismatch')
        concat_ref = at_manifest.get('concat_receipt')
        concat_rec = read_ref(concat_ref)
        _validate_render_step(concat_rec)
        if concat_rec.get('operation') != 'concat':
            raise ValueError('audio_timeline_concat_receipt_invalid')
        cand_ref = at_manifest.get('candidate') or {}
        cand_path = bound(cand_ref).resolve()
        concat_outs = [r['artifact'] for r in concat_rec.get('outputs', []) if r.get('role') in ('candidate', 'media')]
        if not concat_outs or Path(concat_outs[0]['path']).resolve() != cand_path or concat_outs[0].get('sha256') != cand_ref.get('sha256'):
            raise ValueError('audio_timeline_candidate_concat_mismatch')
        edited_ref = manifest['edited_media']
        edited_match = (
            Path(edited_ref['path']).resolve() == cand_path and edited_ref.get('sha256') == cand_ref.get('sha256')
        )
        final_match = bool(
            final_ref and Path(final_ref['path']).resolve() == cand_path and final_ref.get('sha256') == cand_ref.get('sha256')
        )
        chain_consumed = any(_step_has_artifact(step, cand_ref) for step in chain_receipts)
        if not (edited_match or final_match or chain_consumed):
            raise ValueError('audio_timeline_candidate_not_bound_to_delivery')
        manifest_bundle = None
        if sub_cfg.get('font_bundle_ref') is not None:
            manifest_bundle = _verify_font_bundle_ref(sub_cfg['font_bundle_ref'])
        segments = at_manifest.get('segments') or []
        seg_receipts = at_manifest.get('segment_receipts') or []
        if not segments or len(segments) != len(seg_receipts):
            raise ValueError('audio_timeline_segment_receipts_mismatch')
        concat_inputs = concat_rec.get('inputs', [])
        if len(concat_inputs) != len(seg_receipts):
            raise ValueError('audio_timeline_concat_segment_count_mismatch')
        global_cursor = 0
        for idx, (seg_row, seg_rec) in enumerate(zip(segments, seg_receipts)):
            if seg_rec.get('scene_id') != seg_row.get('scene_id'):
                raise ValueError('audio_timeline_segment_order_mismatch')
            seg_render_rec = read_ref(seg_rec.get('render_receipt'))
            _validate_render_step(seg_render_rec)
            seg_cand = [r['artifact'] for r in seg_render_rec.get('outputs', []) if r.get('role') in ('candidate', 'media')]
            if (len(seg_cand) != 1
                    or Path(concat_inputs[idx]['artifact']['path']).resolve() != Path(seg_cand[0]['path']).resolve()
                    or concat_inputs[idx]['artifact'].get('sha256') != seg_cand[0].get('sha256')):
                raise ValueError('audio_timeline_segment_concat_lineage_mismatch')
            seg_ass_ref = seg_rec.get('subtitle_ass')
            seg_ass_path = bound(seg_ass_ref)
            seg_bundle = _verify_font_bundle_ref(
                seg_rec.get('font_bundle_manifest'), job_inputs=seg_render_rec.get('inputs', [])
            )
            if manifest_bundle is not None and seg_bundle['files'][0]['sha256'] != manifest_bundle['files'][0]['sha256']:
                raise ValueError('audio_timeline_font_bundle_mismatch')
            seg_calls = _extract_subtitle_filter_calls(seg_render_rec.get('command'))
            if len(seg_calls) != 1 or seg_calls[0]['force_style'] is not None:
                raise ValueError('invalid_audio_timeline_segment_subtitle_filter')
            if seg_calls[0]['subtitle_path'] != seg_ass_path.resolve() or not _step_has_artifact(seg_render_rec, seg_ass_ref):
                raise ValueError('render_subtitle_file_not_bound')
            if not seg_calls[0]['fontsdir_present'] or seg_calls[0]['fontsdir_path'] != seg_bundle['fonts_dir_resolved']:
                raise ValueError('unbound_subtitle_fontsdir')
            font_ev = read_ref(seg_rec.get('font_load_evidence'))
            if (font_ev.get('verified') is not True
                    or font_ev.get('expected_filename') != seg_bundle['files'][0]['relative_path']
                    or font_ev.get('expected_postscript_name') != seg_bundle.get('postscript_name')):
                raise ValueError('audio_timeline_font_load_evidence_unverified')
            seg_start = float(seg_row['start_s'])
            seg_dur = float(seg_row['end_s']) - seg_start
            seg_cues = list(seg_row.get('subtitles') or [])
            if global_cursor + len(seg_cues) > len(expected_cues):
                raise ValueError('burn_file_disagrees_with_reviewed_cues')
            seg_expected_global = expected_cues[global_cursor : global_cursor + len(seg_cues)]
            global_cursor += len(seg_cues)
            _verify_ass_against_cues(
                manifest,
                seg_ass_path,
                seg_expected_global,
                time_offset=seg_start,
                preset_id=preset_id,
                bundle=seg_bundle,
                v2_mode=True,
                sub_seq_mod=sub_seq_mod,
                local_duration_limit=seg_dur,
            )
        if global_cursor != len(expected_cues):
            raise ValueError('burn_file_disagrees_with_reviewed_cues')
        return dict(
            source_route=source_route,
            style_preset=preset_id,
            sidecar_srt=sidecar['subtitle_sha256'],
            segment_count=len(seg_receipts),
            cue_count=global_cursor,
        )

    # Path 3: remotion_rendered
    if sub_cfg.get('render_file_ref') is not None:
        rf = sub_cfg['render_file_ref']
        if bound(rf).suffix.lower() == '.ass':
            raise ValueError('double_subtitle_burn_not_allowed_for_source_route')
        if not _ref_in_list(rf, ev_files):
            raise ValueError('subtitle_file_not_in_coverage_review_fingerprint')
    elif not _ref_in_list(sub_cfg.get('sidecar_srt_ref'), ev_files):
        raise ValueError('subtitle_file_not_in_coverage_review_fingerprint')
    rem_ref = sub_cfg.get('remotion_run_receipt_ref')
    if not isinstance(rem_ref, dict):
        raise ValueError('remotion_run_receipt_ref_required')
    rem_receipt = read_ref(rem_ref)
    if rem_receipt.get('schema') != 'video_creation_pipeline.remotion_run_receipt.v1':
        raise ValueError('invalid_remotion_run_receipt_schema')
    remotion_mod.validate_remotion_run_receipt(rem_receipt)
    norm_rec = rem_receipt.get('ffmpeg_receipt')
    if isinstance(norm_rec, dict) and Path(str(norm_rec.get('path', ''))).is_file():
        norm_data = read_ref(norm_rec)
        if _extract_subtitle_filter_calls(norm_data.get('command')):
            raise ValueError('double_subtitle_burn_not_allowed_for_source_route')
    sub_rt = rem_receipt.get('subtitle_runtime') or {}
    if sub_rt.get('browser_font_load_verified') is not True:
        raise ValueError('remotion_browser_font_load_not_verified')
    events = sub_rt.get('browser_font_load_events') or []
    if not any(evt.get('status') == 'loaded' and evt.get('sha256') == sub_rt.get('font_sha256') for evt in events):
        raise ValueError('remotion_browser_font_load_not_verified')
    if sub_rt.get('preset_id') != preset_id:
        raise ValueError('remotion_subtitle_preset_mismatch')
    if sub_cfg.get('font_bundle_ref') is not None:
        bundle = _verify_font_bundle_ref(sub_cfg['font_bundle_ref'])
        if sub_rt.get('font_sha256') != bundle['files'][0]['sha256']:
            raise ValueError('remotion_subtitle_font_mismatch')
    else:
        resolved_font = sub_styles_mod.resolve_managed_font(sub_rt.get('font_id'))
        if sub_rt.get('font_sha256') != resolved_font['sha256']:
            raise ValueError('remotion_subtitle_font_mismatch')
    rem_sub = sub_rt.get('subtitle_artifact')
    if (not isinstance(rem_sub, dict)
            or bound(rem_sub).resolve() != sidecar['path_resolved']
            or rem_sub.get('sha256') != sidecar['subtitle_sha256']):
        raise ValueError('remotion_subtitle_artifact_mismatch')
    rem_cand = rem_receipt.get('candidate_video') or {}
    rem_cand_path = bound(rem_cand).resolve()
    edited_ref = manifest['edited_media']
    edited_match = (
        Path(edited_ref['path']).resolve() == rem_cand_path and edited_ref.get('sha256') == rem_cand.get('sha256')
    )
    chain_consumed = any(_step_has_artifact(step, rem_cand) for step in chain_receipts)
    if not (edited_match or chain_consumed):
        raise ValueError('remotion_candidate_not_bound_to_delivery')
    return dict(
        source_route=source_route,
        style_preset=preset_id,
        sidecar_srt=sidecar['subtitle_sha256'],
        font_sha256=sub_rt.get('font_sha256'),
        browser_font_load_verified=True,
    )


def acceptance_fingerprint(manifest):
    value = copy.deepcopy(manifest)
    value.pop('acceptance_ref', None)
    # Context metadata has its own live requirement gate below. A provenance-only
    # binding must not discard unchanged, media-bound human observations.
    value.pop('context_manifest_ref', None)
    # The measurement is checked live against the final file independently.
    # Adding it does not change the reviewed media, layout or copy.
    value.pop('final_audio_measurement_ref', None)
    value.pop('final_audio_auto', None)
    value.pop('pacing_report_ref', None)
    return fingerprint(value)


def confirmation_sources(receipt, current_fingerprint, required_checks):
    rows = receipt.get('confirmation_sources', [])
    if not isinstance(rows, list):
        raise ValueError('human_confirmation_sources_list_required')
    coverage = set()
    references = []
    for row in rows:
        if not isinstance(row, dict) or row.get('input_fingerprint') != current_fingerprint:
            raise ValueError('human_confirmation_source_version_mismatch')
        scope = row.get('checks')
        if (not isinstance(scope, list) or not scope
                or any(not isinstance(name, str) or name not in required_checks
                       or receipt.get(name) is not True for name in scope)):
            raise ValueError('human_confirmation_source_check_scope_invalid')
        source_path = bound(row['source_ref'])
        if source_path.stat().st_size > 2_000_000:
            raise ValueError('human_confirmation_source_too_large')
        source = read_ref(row['source_ref'])
        quote = row.get('quote')
        if (source.get('role') != 'user' or not isinstance(source.get('text'), str)
                or not isinstance(quote, str) or not quote.strip() or quote not in source['text']):
            raise ValueError('human_confirmation_source_user_quote_required')
        coverage.update(scope)
        references.append(dict(source_ref=row['source_ref'], quote_sha256=hashlib.sha256(quote.encode('utf-8')).hexdigest(),
                               declared_checks=scope, exact_user_quote_present=True))
    return dict(status='bound_source_quotes' if rows else 'not_supplied',
                input_fingerprint=current_fingerprint, sources=references,
                declared_checks=sorted(coverage),
                checks_without_source=sorted(set(required_checks) - coverage),
                identity_authenticated=False, actual_watching_proven=False,
                quote_semantics_automatically_verified=False)


def final_audio_plan(manifest):
    config = manifest['final_audio_auto']
    if not isinstance(config, dict) or config.get('audio_stream') != '0:a:0':
        raise ValueError('final_audio_requires_explicit_supported_stream_0:a:0')
    return bound(config['plan_ref']).resolve()


def final_audio_check(manifest, data):
    if data is None:
        raise ValueError('current_render_required_for_final_audio')
    final = data['items'][0]['video']
    ref = manifest['final_audio_measurement_ref']
    if bound(ref).stat().st_size != ref.get('bytes'):
        raise ValueError('final_audio_measurement_size_mismatch')
    verification = read_ref(ref)
    measured = verification.get('mastered_audio')
    if (not isinstance(measured, dict) or measured.get('sha256') != final['sha256']
            or bound(measured).resolve() != bound(final).resolve()):
        raise ValueError('final_audio_verification_media_mismatch')
    renderer_module()
    from video_creation_pipeline.audio_mastering import validate_audio_mastering_output_verification
    validate_audio_mastering_output_verification(verification)
    if manifest.get('final_audio_auto') is not None:
        plan = verification['source_plan']
        if (Path(plan['path']).resolve() != final_audio_plan(manifest)
                or plan['sha256'] != manifest['final_audio_auto']['plan_ref']['sha256']):
            raise ValueError('final_audio_verification_plan_mismatch')
    if verification['readiness']['technical_ready'] is not True:
        raise ValueError('final_audio_verification_not_technical_ready')
    return dict(status='verified', audio_stream='0:a:0', media_sha256=final['sha256'],
                integrated_lufs=verification['measurements']['input_i'],
                true_peak_dbtp=verification['measurements']['input_tp'])


def attach_final_audio_measurement(manifest, output):
    # This runs only on deliver after the existing non-audio checks pass.
    final = desk.normalize(read_ref(manifest['desk_ref']))['items'][0]['video']
    media = bound(final).resolve()
    plan = final_audio_plan(manifest)
    parent = output.parent.resolve(strict=True)
    cache = parent / 'final-audio-evidence'
    key = fingerprint(dict(media=str(media), media_sha256=final['sha256'],
                           plan=str(plan), plan_sha256=manifest['final_audio_auto']['plan_ref']['sha256'],
                           stream='0:a:0'))
    run = cache / key
    for directory in (cache, run):
        if directory.resolve() != directory:
            raise ValueError('final_audio_evidence_directory_must_not_redirect')
    cache.mkdir(exist_ok=True)
    renderer_module()
    from video_creation_pipeline.audio_mastering import measure_final_audio
    from video_creation_pipeline.contract_io import atomic_write_json

    report = run / 'loudnorm-output-verification.json'
    # A run directory is claimed once. An interrupted run keeps its logs and
    # must not be treated as a completed measurement or restarted implicitly.
    try:
        run.mkdir()
    except FileExistsError:
        if not report.is_file() or report.resolve() != report:
            raise ValueError('final_audio_measurement_run_incomplete: ' + str(run))
        origin = 'reused'
    else:
        produced = Path(measure_final_audio(media, plan, run)).resolve()
        if produced != report or not report.is_file():
            raise ValueError('unexpected_final_audio_measurement_output')
        origin = 'measured'
    ref = dict(**covers.reference(report), bytes=report.stat().st_size)
    manifest['final_audio_measurement_ref'] = ref
    derived = run / ('delivery-' + uuid.uuid4().hex + '.json')
    atomic_write_json(manifest, derived)
    return derived, ref, origin


def final_sample_times(manifest, duration):
    times = {0.0, round(duration/2, 3), round(max(0, duration-.1), 3)}
    if manifest.get('final_layout_ref'):
        layout = read_ref(manifest['final_layout_ref'])
        for element in layout['elements']:
            if element['role'] == 'subtitle':
                continue
            for point in (element['start_seconds'], element['end_seconds']):
                if .05 < point < duration-.1:
                    times.update((round(point-.02,3),round(point+.02,3)))
    cap_cfg = manifest.get('final_subtitles') or manifest.get('subtitles') or {}
    if cap_cfg.get('render_file_ref') and not _is_v2_subtitle_manifest(manifest):
        import video_caption_quality
        _, cues = video_caption_quality.final_cues(manifest)
        times.update(video_caption_quality.sample_times(cues))
    if len(times) > 144:
        raise ValueError('final_layout_requires_bounded_transition_samples')
    times.update(framing.final_samples(manifest, duration))
    return sorted(times)


def identity_selection(manifest):
    identity=manifest.get('identity_overlay',{})
    if identity.get('decision') not in ('required','not_applicable') or not str(identity.get('reason','')).strip():
        raise ValueError('insurance_identity_applicability_decision_required')
    if identity['decision']=='required':
        source=read_ref(identity.get('source_ref'))
        if any(not isinstance(source.get(role),str) or not source[role].strip()
               for role in ('identity','institution','license_number')):
            raise ValueError('insurance_identity_source_values_required')
    return dict(decision=identity['decision'],reason=identity['reason'],
                source_ref=identity.get('source_ref'),applied_in_final_media=False)


def bgm_selection(manifest):
    choice=manifest.get('background_music',{})
    if choice.get('decision') not in ('use','not_used') or not str(choice.get('reason','')).strip():
        raise ValueError('explicit_BGM_use_or_omission_decision_required')
    if choice['decision']=='not_used':
        return dict(decision='not_used',reason=choice['reason'],final_listening_required=True)
    plan=read_ref(choice.get('plan_ref'))
    renderer_module()
    from video_creation_pipeline.music_diversity import build_music_arrangement_report
    report=build_music_arrangement_report(plan['layers'],plan['asset_sources'])
    if not report['layers']:
        raise ValueError('BGM_use_requires_actual_layers_not_prepared_files')
    if any(row['timeline_start_s']+row['duration_s']>final_timeline(manifest)['duration_seconds']+.05 for row in report['layers']):
        raise ValueError('BGM_arrangement_exceeds_current_timeline')
    if report['status']!='passed':
        raise ValueError('BGM_arrangement_blocked: '+','.join(row['code'] for row in report['violations']))
    sources=[]
    for asset_id in sorted({row['asset_id'] for row in report['layers']}):
        raw=plan['asset_sources'][asset_id]
        source=raw.get('artifact_ref') or dict(path=raw.get('path',''),sha256=raw['sha256'])
        bound(source)
        if source['sha256']!=raw['sha256']:
            raise ValueError('BGM_source_hash_disagrees_with_arrangement')
        sources.append(dict(asset_id=asset_id,artifact_ref=source))
    return dict(decision='use',plan_ref=choice['plan_ref'],arrangement_report=report,
                source_refs=sources,
                scope='existing source-hash/interval metadata guard; final mix listening remains required')


def observe_final(manifest, output_dir):
    """Adapt VKP's existing frame extractor, never render a replacement movie."""
    data = desk.normalize(read_ref(manifest['desk_ref']))
    if data['project_id'] != manifest['project_id'] or len(data['items']) != 1:
        raise ValueError('matching_single_video_desk_required_for_final_observation')
    video = data['items'][0]['video']
    source = bound(video)
    _, probe = vkp_modules()
    meta = probe(source)
    times = final_sample_times(manifest, meta.duration_seconds)
    approved = framing.final_samples(manifest, meta.duration_seconds)
    plan_ref = manifest.get('frame_safety_plan_ref')
    if plan_ref:
        result = framing.for_delivery(manifest, framing.probe_media)
        framing.check_final_media(source, result, framing.probe_media)
    frames = capture_final_frames(source, manifest['project_id'], times, output_dir)
    packet = dict(schema='self-media.final-observations.v1',project_id=manifest['project_id'],
        video_ref=video,layout_ref=manifest.get('final_layout_ref'),frames=frames,
        inspector='video_knowledge_pipeline.video.extract_segment_frames',
        human_approved=False, automatic_ocr=False)
    if plan_ref:
        framing.check_decoded_frames(frames, result['canvas'])
        packet.update(frame_safety_plan_ref=plan_ref, approved_sample_times_seconds=approved)
    desk.write_new(Path(output_dir)/'observations.json',packet)
    return packet


def capture_final_frames(source, project_id, times, output_dir):
    vkp_modules()
    output_dir = Path(output_dir)
    if not output_dir.is_absolute() or output_dir.exists():
        raise ValueError('final_observation_requires_new_absolute_output_directory')
    from video_knowledge_pipeline.models import EvidenceSegment
    from video_knowledge_pipeline.video import extract_segment_frames
    segments = [EvidenceSegment(id=f'final-{i:03}',video_id=project_id,start=t,end=t+.001,
                    midpoint=t,signals=['final_delivery_layout_sample']) for i,t in enumerate(times)]
    output_dir.mkdir(parents=True)
    extract_segment_frames(source,output_dir,segments)
    return [dict(time_seconds=s.midpoint,frame_ref=covers.reference(s.frame_paths[0])) for s in segments]


def frame_postcheck(plan_ref, video, output_dir):
    checked = framing.check_ref(plan_ref, framing.probe_media)
    source = bound(video)
    facts = framing.check_final_media(source, checked, framing.probe_media)
    times = framing.final_samples(dict(frame_safety_plan_ref=plan_ref), facts['duration_seconds'])
    rows = capture_final_frames(source, checked['project_id'], times, output_dir)
    framing.check_decoded_frames(rows, checked['canvas'])
    packet = dict(schema='self-media.final-frame-safety.v1', status='sampled', video_ref=video, plan_ref=plan_ref,
                  canvas=checked['canvas'], frames=rows, rendered_layer_review_pending=True)
    desk.write_new(Path(output_dir)/'frame-safety.json', packet)
    return packet


def final_layout_check(manifest, data):
    """Wire existing layout policy to the actual final media and decoded frames."""
    if data is None:
        raise ValueError('current_render_required_for_final_layout')
    final = data['items'][0]['video']
    layout_ref = manifest.get('final_layout_ref')
    if layout_ref is None:
        raise ValueError('final_layout_evidence_required_including_default_AI_disclosure')
    renderer_module()
    from video_creation_pipeline.final_layout_safety import validate_final_layout_path
    path = bound(layout_ref)
    root = Path(manifest.get('layout_workspace_root',path.parent)).resolve()
    layout = read_ref(layout_ref)
    if (layout['candidate']['expected_sha256'] != final['sha256'] or
            (root/layout['candidate']['path']).resolve() != bound(final).resolve() or
            abs(layout['duration_seconds']-final_timeline(manifest, final)['duration_seconds']) > .05):
        raise ValueError('final_layout_belongs_to_other_media_or_timeline')
    import video_overlay_selection as overlays
    result = validate_final_layout_path(path,root)
    medical_layout = overlays.check_layout(overlays.for_manifest(manifest), layout)
    result.setdefault('medical_disclosure', medical_layout)
    identity_selection(manifest)
    identity = manifest['identity_overlay']
    if identity['decision'] == 'required':
        source = read_ref(identity.get('source_ref'))
        for role in ('identity','institution','license_number'):
            expected = source.get(role)
            if not isinstance(expected,str) or not expected.strip():
                raise ValueError('identity_source_value_required: '+role)
            rows = sorted((e for e in layout['elements'] if e['role']==role),key=lambda e:e['start_seconds'])
            cursor = 0.0
            for row in rows:
                if expected not in row.get('text','') or row['start_seconds'] > cursor+1e-6:
                    raise ValueError('identity_text_or_continuous_coverage_missing: '+role)
                cursor=max(cursor,row['end_seconds'])
            if cursor < layout['duration_seconds']-1e-6:
                raise ValueError('identity_text_or_continuous_coverage_missing: '+role)
    packet = read_ref(manifest.get('final_observations_ref'))
    if (packet.get('schema') != 'self-media.final-observations.v1' or packet.get('project_id') != manifest['project_id']
            or packet.get('video_ref') != final or packet.get('layout_ref') != layout_ref):
        raise ValueError('final_observations_media_or_layout_changed')
    _, probe = vkp_modules()
    duration = probe(bound(final)).duration_seconds
    expected = final_sample_times(manifest, duration)
    rows = packet.get('frames',[])
    if [r.get('time_seconds') for r in rows] != expected:
        raise ValueError('final_observations_need_head_middle_tail_and_layout_transitions')
    plan_ref = manifest.get('frame_safety_plan_ref')
    if plan_ref:
        approved = framing.final_samples(manifest, duration)
        if packet.get('frame_safety_plan_ref') != plan_ref or packet.get('approved_sample_times_seconds') != approved:
            raise ValueError('final_observations_missing_current_approved_frame_safety_samples')
    for row in rows:
        bound(row['frame_ref'])
    # A hash of an arbitrary picture is insufficient: reproduce samples from the
    # current final video using the same existing inspector and compare bytes.
    scratch_base = runtime_paths.runtime_root(ROOT) / 'test-temp'
    scratch = scratch_base / ('final-observe-' + uuid.uuid4().hex)
    try:
        fresh = observe_final(manifest, scratch.resolve())
        if [r['frame_ref']['sha256'] for r in fresh['frames']] != [r['frame_ref']['sha256'] for r in rows]:
            raise ValueError('final_observation_frames_not_from_current_media')
    finally:
        if scratch.is_dir() and not scratch.is_symlink() and scratch.resolve().is_relative_to(scratch_base.resolve()):
            shutil.rmtree(scratch)
    return dict(**result, frame_samples_verified=len(rows),identity_decision=identity['decision'],
                actual_visual_meaning_requires_human_review=True,automatic_ocr=False)


def guarded_render(path, job_path):
    """Only an explicit render action executes an existing local FFmpeg job.

    Keep the existing single outlet and live resource guard; do not accept shell
    scripts, environment changes, providers or arbitrary executables as jobs.
    """
    report = audit(path, 'preflight')
    if not report['preflight_ready']:
        return report
    manifest = covers.read(path)
    job = covers.read(job_path)
    if job.get('schema') != 'self-media.local-render-job.v1':
        raise ValueError('local_render_job_schema_required')
    if job.get('preflight_fingerprint') != report['acceptance_fingerprint']:
        raise ValueError('render_job_stale_preflight')
    root = Path(job['project_root'])
    if not root.is_absolute() or not root.is_dir():
        raise ValueError('existing_private_project_root_required')
    root = root.resolve()
    items, _ = materials.intake(manifest)
    materials.check_render_inputs(items, [job])
    refs = job['inputs']
    inputs = [dict(role=r['role'], path=str(bound(r['artifact']))) for r in refs]
    edited = bound(manifest['edited_media']).resolve()
    if edited not in {Path(r['path']).resolve() for r in inputs}:
        raise ValueError('render_job_missing_edited_source')
    output, receipt = Path(job['output']), Path(job['receipt'])
    for target in (output, receipt):
        if not target.is_absolute() or target.exists() or not target.resolve().is_relative_to(root):
            raise ValueError('render_outputs_must_be_new_and_inside_project')
    if output.resolve() == receipt.resolve() or output.suffix.lower() not in ('.mp4', '.mkv', '.mov'):
        raise ValueError('render_output_or_receipt_invalid')
    command = job['command']
    if (not isinstance(command, list) or not all(isinstance(x, str) for x in command)
            or not command or command[0] != 'ffmpeg' or command[-1] != str(output)
            or '-y' in command or '-n' not in command):
        raise ValueError('existing_ffmpeg_no_overwrite_command_required')
    # A constrained one-input/one-output transcode/burn surface. Complex assembly
    # remains in existing tools before this finalization subflow.
    options = {'-hide_banner': 0, '-nostdin': 0, '-n': 0, '-i': 1, '-map': 1,
               '-vf': 1, '-af': 1, '-c:v': 1, '-c:a': 1, '-b:a': 1, '-b:v': 1,
               '-crf': 1, '-preset': 1, '-pix_fmt': 1, '-ar': 1, '-ac': 1,
               '-movflags': 1, '-threads': 1, '-v': 1, '-loglevel': 1}
    index, media_inputs = 1, []
    while index < len(command)-1:
        flag = command[index]
        if flag not in options or index + options[flag] >= len(command)-1:
            raise ValueError('unsupported_render_option: ' + flag)
        if flag == '-i':
            media_inputs.append(Path(command[index+1]).resolve())
        if flag in ('-vf', '-af'):
            expression = command[index+1]
            # Reject filter-source/file-I/O constructs and external transports.
            if re.search(r'(?i)(movie|amovie|sendcmd|asendcmd|zmq|ladspa|lv2|http|https|tcp|udp|concat|\\n|\\r)', expression):
                raise ValueError('render_filter_external_source_not_allowed')
            if re.search(r'(?i)(textfile|fontfile|file=)', expression):
                raise ValueError('unbound_filter_file_not_allowed')
            has_sub_kw = bool(re.search(r'(?i)(?:^|[,;\]\s])(?:subtitles|ass)\s*=', expression))
            has_fontsdir = bool(re.search(r'(?i)fontsdir', expression))
            if not has_sub_kw:
                if has_fontsdir:
                    raise ValueError('unbound_filter_file_not_allowed')
            else:
                if flag != '-vf':
                    raise ValueError('use_bound_standalone_subtitle_filter')
                v2_mode = _is_v2_subtitle_manifest(manifest)
                sub_cfg = manifest.get('subtitles') or {}
                if v2_mode and sub_cfg.get('source_route') in ('audio_timeline_segmented', 'remotion_rendered'):
                    raise ValueError('double_subtitle_burn_not_allowed_for_source_route')
                match = re.fullmatch(
                    r"(?:subtitles|ass)=(?:filename=)?'([^']+)'((?::(?:fontsdir|force_style)='[^']*')*)",
                    expression,
                )
                if not match:
                    if has_fontsdir:
                        raise ValueError('unbound_filter_file_not_allowed')
                    raise ValueError('use_bound_standalone_subtitle_filter')
                opts_tail = match[2]
                opts = re.findall(r":(fontsdir|force_style)='([^']*)'", opts_tail)
                if sum(len(k) + len(v) + 4 for k, v in opts) != len(opts_tail):
                    if re.search(r'(?i)fontsdir', opts_tail):
                        raise ValueError('unbound_filter_file_not_allowed')
                    raise ValueError('use_bound_standalone_subtitle_filter')
                opt_map = {}
                for k, v in opts:
                    if k in opt_map:
                        raise ValueError('use_bound_standalone_subtitle_filter')
                    opt_map[k] = v
                if len(re.findall(r'(?i)fontsdir', opts_tail)) != (1 if 'fontsdir' in opt_map else 0):
                    raise ValueError('unbound_filter_file_not_allowed')
                ref = sub_cfg.get('render_file_ref')
                subtitle = bound(ref)
                decoded = _decode_ffmpeg_filter_path(match[1])
                if Path(decoded).resolve() != subtitle.resolve() or not _step_has_artifact({'inputs': refs}, ref):
                    raise ValueError('render_subtitle_file_not_bound')
                request = read_ref(sub_cfg['request_ref'])
                if not _ref_in_list(ref, request.get('evidence_files', [])):
                    raise ValueError('subtitle_file_not_in_coverage_review_fingerprint')
                if v2_mode:
                    if sub_cfg.get('source_route') != 'video_delivery_clean_burn':
                        raise ValueError('invalid_subtitle_source_route_for_burn')
                    if subtitle.suffix.lower() != '.ass':
                        raise ValueError('v2_clean_burn_requires_ass_file')
                    if 'force_style' in opt_map:
                        raise ValueError('force_style_not_allowed_for_managed_ass')
                    if 'fontsdir' not in opt_map or not opt_map['fontsdir'].strip():
                        raise ValueError('unbound_subtitle_fontsdir')
                    bundle = _verify_font_bundle_ref(sub_cfg.get('font_bundle_ref'), project_root=root, job_inputs=refs)
                    decoded_fd = _decode_ffmpeg_filter_path(opt_map['fontsdir'])
                    if Path(decoded_fd).resolve() != bundle['fonts_dir_resolved']:
                        raise ValueError('unbound_subtitle_fontsdir')
                    if sub_cfg.get('sidecar_srt_ref') is not None:
                        _reconcile_sidecar_srt(manifest)
                elif 'fontsdir' in opt_map:
                    _verify_font_bundle_ref(sub_cfg.get('font_bundle_ref'), project_root=root, job_inputs=refs)
                verify_subtitle_burn_file(manifest, subtitle)
        index += 1 + options[flag]
    if media_inputs != [edited]:
        raise ValueError('final_render_requires_one_edited_input')
    # Snapshot all job dependencies immediately before execution. Receipt itself
    # also binds them; fresh delivery validation never relies on this report alone.
    for r in refs:
        bound(r['artifact'])
    import artifact_lifecycle
    disk = artifact_lifecycle.preflight(argparse.Namespace(
        manifest=bound(job['lifecycle_manifest_ref']), workspace_root=root, now=None,
        output_class='large_or_unknown', estimated_output_bytes=job['estimated_output_bytes'], core_root=None))
    if disk['status'] != 'passed':
        return dict(status='blocked', complete=False, next_action='resource_disk_preflight', disk=disk,
                    publish_authorized=False, execution_authorized=False)
    rendered = renderer_module().execute_ffmpeg_with_receipt('render', command, inputs,
        [dict(role='candidate', path=str(output))], receipt,
        timeout_s=number(job.get('timeout_seconds', 120)), guard_resource=True)
    result = dict(status='rendered_pending_delivery_review', complete=False, publish_authorized=False,
                render_receipt_ref=covers.reference(receipt), output_ref=covers.reference(output),
                preflight_fingerprint=report['acceptance_fingerprint'], disk=disk, outlet_id=rendered['outlet_id'])
    plan_ref = manifest.get('frame_safety_plan_ref')
    if plan_ref:
        observation_dir = receipt.parent / (receipt.stem + '-frame-safety')
        try:
            frame_postcheck(plan_ref, result['output_ref'], observation_dir)
        except (OSError, ValueError, KeyError, TypeError, ImportError, RuntimeError) as error:
            return {**result, 'status': 'blocked', 'next_action': 'frame-postcheck',
                    'frame_safety_error': str(error)}
        result['frame_safety_ref'] = covers.reference(observation_dir/'frame-safety.json')
    return result


def pacing_check(manifest):
    import video_pacing
    report = manifest.get('pacing_report_ref')
    if not report:
        raise ValueError('current_video_pacing_report_required')
    data = desk.normalize(read_ref(manifest['desk_ref']))
    if data['project_id'] != manifest['project_id'] or len(data['items']) != 1:
        raise ValueError('pacing_requires_matching_single_video_desk')
    return video_pacing.check(report, data['items'][0]['video'], manifest['script_ref'],
                              manifest['subtitles']['pack_ref'])


def audit(path, phase='delivery', context_manifest=None):
    if phase not in ('preflight', 'delivery'):
        raise ValueError('invalid_delivery_phase')
    manifest = covers.read(path)
    if context_manifest is not None:
        manifest['context_manifest_ref'] = covers.reference(context_manifest)
    result = dict(schema='self-media.video-delivery-report.v1', phase=phase,
                  project_id=manifest.get('project_id'), status='blocked', complete=False,
                  preflight_ready=False, publish_authorized=False, execution_authorized=False,
                  checks=[], acceptance_fingerprint=acceptance_fingerprint(manifest))
    def run(name, fn):
        try:
            value = fn()
            result['checks'].append(dict(stage=name, status='passed'))
            return value
        except (OSError, ValueError, KeyError, TypeError, ImportError, RuntimeError) as error:
            result['checks'].append(dict(stage=name, status='blocked', reason=str(error)))
            return None
    import rough_cut_checks
    import video_overlay_selection as overlays
    run('context', lambda: context(manifest))
    result['material_intake'] = run('material_intake_before_edit', lambda: materials.check_intake(manifest))
    run('cta_selection_and_position', lambda: cta.checked_plan(manifest.get('cta_plan_ref'), project_id=manifest['project_id'], script_ref=manifest.get('script_ref'), require_timing=True))
    mapped = run('timeline', lambda: timeline(manifest))
    result['progress_selection'] = run('progress_selection_and_reservation', lambda: progress.check(manifest,'preflight'))
    run('insurance_identity_selection', lambda: identity_selection(manifest))
    result['bgm_selection']=run('BGM_selection_and_arrangement',lambda:bgm_selection(manifest))
    if mapped is not None:
        result['rough_audio'] = run('rough_cut_segment_speech_levels', lambda: rough_audio_check(manifest, mapped))
        if manifest.get('final_subtitles'):
            import video_final_timeline
            coverage = run('subtitles', lambda: video_final_timeline.subtitle_check(manifest, subtitle_check))
        else:
            coverage = run('subtitles', lambda: subtitle_check(manifest, mapped))
        if coverage is not None:
            result['subtitle_coverage'] = coverage
            # A known gap requires a corrected cue or an explicit omission, not
            # only a generic "accepted after listening" checkbox.
            gaps = [r for r in coverage['findings'] if r['code'] in (
                'audio_without_caption_or_reason', 'expected_audio_without_caption_or_reason')]
            if not coverage['render_ready'] or gaps:
                result['checks'][-1] = dict(stage='subtitles', status='blocked',
                    reason='current_full_timeline_review_or_caption_resolution_required')
    run('rough_cut_vkp_acceptance', lambda: rough_cut_checks.check_manifest(manifest))
    result['overlay_assessment'] = run('current_body_overlay_applicability', lambda: overlays.for_manifest(manifest))
    result['frame_safety'] = run('frame_safety_before_render', lambda: framing.for_delivery(manifest, framing.probe_media))
    result['performance_plan'] = run('performance_execution_plan', lambda: performance_plan(manifest))
    result['preflight_ready'] = all(r['status'] == 'passed' for r in result['checks'])
    if phase == 'delivery':
        result['final_timeline'] = run('current_final_timeline', lambda: final_timeline(manifest))
        data=run('render_and_desk', lambda: render_check(manifest))
        if _is_v2_subtitle_manifest(manifest) or manifest.get('subtitles', {}).get('render_file_ref') is not None:
            def check_burn_reconciled():
                if _is_v2_subtitle_manifest(manifest):
                    chain_receipts = [read_ref(r) for r in [*manifest.get('render_chain_refs', []), manifest['render_receipt_ref']]]
                    final_ref = data['items'][0]['video'] if data else None
                    return _audit_v2_subtitle_lineage(manifest, chain_receipts=chain_receipts, final_ref=final_ref)
                burned_ref = manifest['subtitles']['render_file_ref']
                verified = verify_subtitle_burn_file(manifest)
                chain_receipts = [read_ref(r) for r in [*manifest.get('render_chain_refs', []), manifest['render_receipt_ref']]]
                sub_inputs = [
                    row.get('artifact', {})
                    for step in chain_receipts
                    for row in step.get('inputs', [])
                    if row.get('role') == 'subtitles' or str(row.get('artifact', {}).get('path', '')).lower().endswith(('.ass', '.srt', '.vtt'))
                ]
                if sub_inputs and not any(art.get('sha256') == burned_ref.get('sha256') for art in sub_inputs):
                    raise ValueError('render_subtitle_file_not_bound')
                return verified
            result['subtitle_burn_reconciliation'] = run('subtitle_burn_reconciliation', check_burn_reconciled)
        def check_material_use():
            if data is None or result['final_timeline'] is None:
                raise ValueError('material_final_review_requires_current_render_and_timeline')
            receipts = [read_ref(ref) for ref in [*manifest.get('render_chain_refs', []), manifest['render_receipt_ref']]]
            items, _ = materials.intake(manifest, require_ready=False)
            materials.check_render_inputs(items, receipts)
            return materials.check_final(manifest, data['items'][0]['video'],
                                         result['final_timeline']['duration_seconds'], renderer_module())
        result['material_final'] = run('material_actual_use_after_export', check_material_use)
        result['video_pacing'] = run('current_final_video_pacing', lambda: pacing_check(manifest))
        if manifest.get('final_audio_measurement_ref') is None:
            result['final_audio'] = dict(status='not_measured')
            if manifest.get('final_audio_auto') is not None:
                plan = run('final_audio_plan', lambda: final_audio_plan(manifest))
                if plan is not None:
                    result['checks'].append(dict(stage='final_audio_verification', status='blocked',
                                                 reason='final_audio_measurement_pending_deliver'))
        else:
            result['final_audio'] = run('final_audio_verification', lambda: final_audio_check(manifest, data))
            if result['final_audio'] is None and manifest.get('final_audio_auto') is not None:
                reason = result['checks'][-1]['reason']
                result['final_audio'] = dict(status='failed' if reason == 'final_audio_verification_not_technical_ready'
                                             else 'unverified', reason=reason)
        result['final_layout'] = run('final_media_layout_and_observations',lambda:final_layout_check(manifest,data))
        result['progress_delivery'] = run('progress_render_and_layout', lambda: progress.check(manifest,'delivery',data['items'][0]['video'] if data else None))
        def check_plain_and_science_gates():
            import plain_language_gate as pl_gate
            ctx_doc = None
            if context_manifest is not None:
                ctx_doc = covers.read(Path(context_manifest))
            elif manifest.get('context_manifest_ref'):
                ctx_doc = read_ref(manifest['context_manifest_ref'])
            topic_domain = ((ctx_doc or {}).get('editorial_context') or {}).get('topic_domain')
            explicit_refs = [
                manifest.get(k) for k in (
                    'plain_language_review_ref', 'translation_review_ref', 'science_review_ref',
                    'clause_explanation_ref', 'fact_card_ref', 'plain_language_plan_ref',
                )
            ]
            serious_domain = str(topic_domain or '').strip() in {'insurance', 'medical', 'health', 'science', 'finance'}
            if not any(explicit_refs) and not serious_domain:
                return {'status': 'not_applicable'}
            fc_ref = manifest.get('fact_card_ref')
            if fc_ref:
                fc_path = bound(fc_ref)
                pl_gate.validate_fact_card_lock(fc_path, expected_sha256=fc_ref.get('sha256'))
            elif serious_domain:
                raise ValueError('locked_fact_card_required_for_video_delivery')
            plan_doc = None
            plan_ref = manifest.get('plain_language_plan_ref')
            if plan_ref:
                plan_path = bound(plan_ref)
                plan_doc = pl_gate.load_json(plan_path)
                pl_gate.validate_plan(plan_doc, trusted_domains={topic_domain} if topic_domain else None, base_dir=plan_path.parent)
            sci_ref = manifest.get('science_review_ref')
            if sci_ref:
                pl_gate.validate_formal_science_review(bound(sci_ref))
            elif str(topic_domain or '').strip() in {'medical', 'health', 'science'}:
                raise ValueError('formal_science_popularization_review_required')
            trans_ref = manifest.get('translation_review_ref')
            if trans_ref:
                pl_gate.validate_formal_translation_review(bound(trans_ref), expected_plan=plan_doc)
            clause_ref = manifest.get('clause_explanation_ref')
            if clause_ref:
                clause_errs = pl_gate.validate_clause_explanation(bound(clause_ref))
                if clause_errs:
                    raise ValueError('clause_explanation_invalid: ' + '; '.join(clause_errs))
            # Gather all visible video surfaces (subtitle cues, burned subtitle file, cover review/desk titles)
            surface_texts = {}
            sub_pack_ref = (manifest.get('subtitles') or {}).get('pack_ref')
            if sub_pack_ref:
                pack = read_ref(sub_pack_ref)
                cues = [str(c.get('text', '')).strip() for row in pack.get('requests', []) for c in row.get('subtitle_cues', []) if str(c.get('text', '')).strip()]
                if cues:
                    surface_texts['subtitle_cues'] = '\n'.join(cues)
            burn_ref = (manifest.get('subtitles') or {}).get('render_file_ref') or (manifest.get('subtitles') or {}).get('sidecar_srt_ref')
            if burn_ref:
                burn_path = bound(burn_ref)
                surface_texts['burned_subtitles'] = pl_gate._extract_surface_text(burn_path)
            if manifest.get('cover_review_ref'):
                cov = read_ref(manifest['cover_review_ref'])
                if cov.get('title') or cov.get('headline'):
                    surface_texts['cover'] = '\n'.join(str(x) for x in (cov.get('title'), cov.get('headline')) if x)
            if data and data.get('items'):
                desk_item = data['items'][0]
                bits = [desk_item.get('title', '')]
                for p in (desk_item.get('platforms') or {}).values():
                    if isinstance(p, dict):
                        bits.extend([p.get('title', ''), p.get('caption', ''), p.get('description', '')])
                desk_text = '\n'.join(str(b).strip() for b in bits if str(b).strip())
                if desk_text:
                    surface_texts['desk_packaging'] = desk_text
            pl_rev_ref = manifest.get('plain_language_review_ref')
            if pl_rev_ref:
                pl_rev_path = bound(pl_rev_ref)
                pl_gate.validate_review(
                    pl_gate.load_json(pl_rev_path),
                    expected_plan_ref=plan_ref,
                    expected_fact_card_ref=fc_ref,
                    extra_surface_texts=surface_texts,
                    base_dir=pl_rev_path.parent,
                    require_passed=True,
                )
            elif plan_doc is None or plan_doc.get('applicability') == 'applicable':
                raise ValueError('plain_language_review_required_for_video_delivery')
            return {'status': 'passed', 'surfaces_checked': sorted(surface_texts)}
        result['plain_language_gates'] = run('plain_language_and_science_gates', check_plain_and_science_gates)
        def check_cover():
            review = read_ref(manifest['cover_review_ref'])
            if review.get('desk_ref') != manifest['desk_ref']:
                raise ValueError('cover_review_for_other_desk')
            return cover_strategy.review_check(bound(manifest['cover_review_ref']))
        result['cover_review'] = run('covers', check_cover)
        result['human_confirmation_source'] = dict(status='not_checked', identity_authenticated=False)
        def check_acceptance():
            if manifest.get('acceptance_ref') is None:
                raise ValueError('current_human_acceptance_required')
            receipt = read_ref(manifest['acceptance_ref'])
            if (receipt.get('schema') != 'self-media.video-acceptance.v1' or
                    receipt.get('input_fingerprint') != result['acceptance_fingerprint'] or
                    receipt.get('reviewer_kind') != 'human' or receipt.get('decision') != 'pass' or
                    not str(receipt.get('reviewer', '')).strip() or not str(receipt.get('reviewed_at', '')).strip()):
                raise ValueError('current_human_acceptance_required')
            required_checks = list(HUMAN_CHECKS)
            if manifest.get('progress_overlay',{}).get('decision')=='use':
                required_checks += [k for k in progress.HUMAN_CHECKS if k!='progress_chapter_boundaries_correct']
                if read_ref(manifest['progress_overlay']['spec_ref'])['mode']=='chapters':
                    required_checks.append('progress_chapter_boundaries_correct')
            pack = read_ref(manifest['subtitles']['pack_ref'])
            cues = [c for row in pack.get('requests',[]) for c in row.get('subtitle_cues',[])]
            if any(c.get('speaker') or c.get('font_size_1080') for c in cues):
                required_checks += ['speaker_styles_consistent', 'preview_export_consistent']
            if any(c.get('motion','none') != 'none' for c in cues):
                required_checks += ['requested_motion_visible']
            for name in required_checks:
                if receipt.get(name) is not True:
                    raise ValueError('human_acceptance_missing: ' + name)
            if data is None:
                raise ValueError('cta_current_render_and_desk_required')
            if result.get('video_pacing') is not None:
                import video_pacing
                video_pacing.check_long_pauses(
                    result['video_pacing'], receipt, data['items'][0]['video']['sha256'],
                    has_bgm=(manifest.get('background_music', {}).get('decision') == 'use'),
                )
            observed = receipt.get('final_layout_review',{})
            if (result['final_layout'] is None or observed.get('video_sha256') != data['items'][0]['video']['sha256']
                    or observed.get('layout_sha256') != manifest.get('final_layout_ref',{}).get('sha256')
                    or observed.get('observations_sha256') != manifest.get('final_observations_ref',{}).get('sha256')
                    or observed.get('rendered_elements_verified') is not True
                    or observed.get('mobile_readable') is not True):
                raise ValueError('actual_final_layout_human_observations_required')
            cap_cfg = manifest.get('final_subtitles') or manifest.get('subtitles') or {}
            burn_ref = cap_cfg.get('render_file_ref')
            final_rec = read_ref(manifest['render_receipt_ref']) if manifest.get('render_receipt_ref') else {}
            is_external_nle = final_rec.get('schema') == 'self-media.external-editor-export-receipt.v1'
            if burn_ref is not None and not is_external_nle:
                import video_caption_quality
                if _is_v2_subtitle_manifest(manifest):
                    if manifest.get('subtitles', {}).get('source_route') == 'video_delivery_clean_burn':
                        references = [*manifest.get('render_chain_refs', []), manifest['render_receipt_ref']]
                        burn_path = bound(burn_ref)
                        sel_path, sel_sha = video_caption_quality._resolve_selected_final_video(
                            manifest, observed, target_video=data['items'][0]['video'],
                        )
                        burned_media = set()
                        final_ok = False
                        for r_idx, r_ref in enumerate(references):
                            r_doc = read_ref(r_ref)
                            is_final_step = (r_idx == len(references) - 1)
                            step_ok, verified_outs = video_caption_quality._receipt_caption_verified_outputs(
                                r_doc, burn_ref, burn_path,
                                burned_media=frozenset(burned_media),
                                exact_target_path=sel_path if is_final_step else None,
                                exact_target_sha=sel_sha if is_final_step else None,
                            )
                            if step_ok:
                                burned_media.update(verified_outs)
                            if is_final_step:
                                final_ok = step_ok
                        if not final_ok:
                            raise ValueError('final_caption_file_not_bound_to_subtitle_burn_after_edit')
                else:
                    packet = read_ref(manifest['final_observations_ref'])
                    video_caption_quality.check(manifest, observed, packet['frames'], target_video=data['items'][0]['video'])
                if Path(bound(burn_ref)).suffix.lower() == '.ass':
                    overlays.check_ass(
                        overlays.for_manifest(manifest),
                        bound(burn_ref),
                        dialogue_styles=cap_cfg.get('dialogue_styles'),
                        external_caption_only=True,
                    )
            if (result['frame_safety'] and observed.get('checked_frame_safety_times_seconds')
                    != result['frame_safety']['sample_times_seconds']):
                raise ValueError('actual_final_approved_frame_safety_samples_review_required')
            if result['final_layout']['ai_disclosure']['required'] and observed.get('ai_label_visible') is not True:
                raise ValueError('actual_final_AI_label_human_review_required')
            if result['final_layout']['medical_disclosure']['required'] and (
                    observed.get('medical_disclaimer_visible') is not True or
                    observed.get('medical_disclaimer_text_checked') is not True):
                raise ValueError('actual_final_medical_disclosure_human_review_required')
            if result['final_layout']['medical_disclosure'].get('windows') and (
                    observed.get('medical_badge_windows_checked') is not True
                    or observed.get('medical_badge_position_checked') is not True):
                raise ValueError('actual_final_scoped_medical_windows_and_position_review_required')
            if result['final_layout']['identity_decision']=='required' and observed.get('identity_text_checked') is not True:
                raise ValueError('actual_final_insurance_identity_human_review_required')
            if manifest.get('background_music',{}).get('decision')=='use':
                music=receipt.get('bgm_review',{})
                if (music.get('video_sha256')!=data['items'][0]['video']['sha256']
                        or music.get('plan_sha256')!=manifest['background_music']['plan_ref']['sha256']
                        or music.get('balance_checked') is not True or music.get('arrangement_listened') is not True):
                    raise ValueError('actual_final_BGM_balance_and_arrangement_listening_required')
            result['cta_landing'] = cta.check_delivery(manifest, data, receipt)
            result['human_confirmation_source'] = confirmation_sources(
                receipt, result['acceptance_fingerprint'], required_checks)
            result['performance_landing'] = performance_landing(manifest, data['items'][0]['video'], receipt)
        run('human_acceptance', check_acceptance)
    def requirements():
        import purpose_continuity
        reference = manifest.get('context_manifest_ref')
        if phase == 'delivery' and reference is None:
            raise ValueError('current_execution_context_required; bind existing purpose/feedback, do not restart production')
        return purpose_continuity.check_consumer(reference, 'video_delivery', dict(
            phase=phase, manifest=manifest, checks=copy.deepcopy(result['checks']),
            performance_plan=result.get('performance_plan'),
            performance_landing=result.get('performance_landing'),
            final_media=data['items'][0]['video'] if phase=='delivery' and data is not None else None))
    result['requirement_report'] = run('current_execution_requirements', requirements)
    ok = all(r['status'] == 'passed' for r in result['checks'])
    result.update(status=('preflight_ready' if phase == 'preflight' else 'complete_local_candidate') if ok else 'blocked',
                  complete=ok and phase == 'delivery')
    result['next_action'] = next((r['stage'] for r in result['checks'] if r['status'] != 'passed'),
                                 'existing_resource_gated_renderer' if phase == 'preflight' else 'human_platform_review')
    stage_commands = {
        'context': 'python scripts/self_media_agent.py video-delivery context --input <manifest.json>',
        'material_intake_before_edit': 'python scripts/self_media_agent.py video-delivery materials-bind --input <manifest.json> --material-intake <intake.json> --output <next.json>',
        'cta_selection_and_position': 'python scripts/self_media_agent.py video-delivery cta-bind --input <manifest.json> --plan <cta.json> --output <next.json>',
        'progress_selection_and_reservation': 'python scripts/self_media_agent.py video-delivery progress-select --input <manifest.json> --decision use|not_used --reason <reason> --output <next.json>',
        'insurance_identity_selection': 'python scripts/self_media_agent.py video-delivery identity-select --input <manifest.json> --decision required|not_applicable --reason <reason> --output <next.json>',
        'BGM_selection_and_arrangement': 'python scripts/self_media_agent.py video-delivery bgm-select --input <manifest.json> --decision use|not_used --reason <reason> --output <next.json>',
        'rough_cut_vkp_acceptance': 'python scripts/self_media_agent.py video-delivery rough-cut-bind --input <manifest.json> --rough-cut-delivery <reg.json> --rough-cut-acceptance <acc.json> --output <next.json>',
        'current_body_overlay_applicability': 'python scripts/self_media_agent.py video-delivery overlays-bind --input <manifest.json> --plan <overlay.json> --output <next.json>',
        'performance_execution_plan': 'python scripts/self_media_agent.py video-delivery performance-bind --input <manifest.json> --plan <performance-plan.json> --output <next.json>',
        'current_final_video_pacing': 'python scripts/self_media_agent.py video-delivery pacing-bind --input <manifest.json> --pacing-report <pacing.json> --output <next.json>',
        'final_media_layout_and_observations': 'python scripts/self_media_agent.py video-delivery observe-final --input <manifest.json> --output-dir <obs-dir>',
        'current_execution_requirements': 'python scripts/self_media_agent.py video-delivery context-bind --input <manifest.json> --context-manifest <ctx.json> --output <next.json>',
        'human_acceptance': 'python scripts/self_media_agent.py video-delivery rebind-copy-acceptance --input <manifest.json> --reviewer <human> --reviewed-at <RFC3339> --output <next.json>',
    }
    result['remediation_commands'] = {
        row['stage']: stage_commands.get(row['stage'], f"python scripts/self_media_agent.py video-delivery {'preflight' if phase == 'preflight' else 'check'} --input <manifest.json>")
        for row in result['checks'] if row['status'] != 'passed'
    }
    return result


def rebind_copy_acceptance(manifest_path, output_path, *, reviewer, reviewed_at, previous_manifest_path=None):
    if not str(reviewer or '').strip() or reviewer.strip().casefold() in {'assistant', 'ai', 'agent', 'auto'}:
        raise ValueError('human_reviewer_required')
    if not str(reviewed_at or '').strip():
        raise ValueError('reviewed_at_required')
    manifest = covers.read(manifest_path)
    if manifest.get('acceptance_ref') is None:
        raise ValueError('existing_acceptance_required_for_copy_rebind')
    old_receipt = read_ref(manifest['acceptance_ref'])
    if (old_receipt.get('schema') != 'self-media.video-acceptance.v1'
            or old_receipt.get('decision') != 'pass'
            or old_receipt.get('reviewer_kind') != 'human'):
        raise ValueError('valid_prior_acceptance_required')
    current_media_fp = media_acceptance_fingerprint(manifest)
    if 'media_fingerprint' in old_receipt:
        if old_receipt['media_fingerprint'] != current_media_fp:
            raise ValueError('media_changed_full_acceptance_required')
    elif previous_manifest_path is not None:
        previous = covers.read(previous_manifest_path)
        if old_receipt.get('input_fingerprint') != acceptance_fingerprint(previous):
            raise ValueError('prior_acceptance_fingerprint_mismatch')
        if media_acceptance_fingerprint(previous) != current_media_fp:
            raise ValueError('media_changed_full_acceptance_required')
    else:
        raise ValueError('media_changed_full_acceptance_required')
    # Verify desk & copy against current facts before re-signing acceptance fingerprint.
    data = render_check(manifest)
    new_fp = acceptance_fingerprint(manifest)
    new_receipt = copy.deepcopy(old_receipt)
    new_receipt.update(
        input_fingerprint=new_fp,
        media_fingerprint=current_media_fp,
        reviewer=reviewer,
        reviewed_at=reviewed_at,
        copy_rebound=True,
        preserved_media_observation_from=manifest['acceptance_ref'],
    )
    if 'cta_landing' in new_receipt and isinstance(new_receipt['cta_landing'], dict):
        new_receipt['cta_landing']['prepared_copy_reviewed'] = True
    receipt_path = output_path.with_suffix('.acceptance.json')
    desk.write_new(receipt_path, new_receipt)
    updated_manifest = copy.deepcopy(manifest)
    updated_manifest['acceptance_ref'] = covers.reference(receipt_path)
    desk.write_new(output_path, updated_manifest)
    return dict(
        status='copy_acceptance_rebound',
        media_unchanged=True,
        media_fingerprint=current_media_fp,
        acceptance_fingerprint=new_fp,
        acceptance_ref=updated_manifest['acceptance_ref'],
        manifest_ref=covers.reference(output_path),
        platforms=sorted(data['items'][0]['platforms']),
    )


def main(argv=None):
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    if '--describe-json' in raw_argv:
        print(json.dumps(describe_capabilities(), ensure_ascii=False))
        return 0
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=list(VIDEO_DELIVERY_ACTIONS))
    p.add_argument('--input', type=Path)
    p.add_argument('--output', type=Path)
    p.add_argument('--project-id')
    p.add_argument('--context-manifest',type=Path)
    p.add_argument('--output-dir',type=Path)
    p.add_argument('--plan', type=Path, help='Existing CTA plan, shared with the publication desk')
    p.add_argument('--render-job', type=Path)
    p.add_argument('--decision',choices=['use','not_used','required','not_applicable'])
    p.add_argument('--identity-source',type=Path)
    p.add_argument('--progress-omit-source', type=Path,
                   help='Direct user-message JSON explicitly declining the progress bar for this video.')
    p.add_argument('--reason')
    p.add_argument('--packaging',type=Path)
    p.add_argument('--layout',type=Path)
    p.add_argument('--frame-plan', type=Path)
    p.add_argument('--frame-review', type=Path, help='Passed frame-safety receipt from before the review page')
    p.add_argument('--spec',type=Path)
    p.add_argument('--workspace-root',type=Path)
    p.add_argument('--program',type=Path,help='Progress input after prior bound renders; defaults to edited_media')
    p.add_argument('--script',type=Path,help='Current video script; progress headings default to this bound source')
    p.add_argument('--rough-cut-delivery', type=Path)
    p.add_argument('--rough-cut-acceptance', type=Path)
    p.add_argument('--overlay-ass', type=Path)
    p.add_argument('--candidate', type=Path)
    p.add_argument('--material-intake', type=Path)
    p.add_argument('--material-review', type=Path)
    p.add_argument('--redraw-record', type=Path, help='Reviewed provenance for an independently redrawn image')
    p.add_argument('--card-replacement-record', type=Path, help='Whole-card replacement for a recorded text edit')
    p.add_argument('--pacing-subtitles', type=Path, help='Subtitle cues on the final encoded timeline')
    p.add_argument('--pacing-source-subtitles', type=Path, help='Existing delivery subtitle pack if on an earlier timeline')
    p.add_argument('--pacing-vkp-run', type=Path, help='Local VKP run on the final candidate; defaults to running local VKP')
    p.add_argument('--pacing-report', type=Path)
    p.add_argument('--reviewer')
    p.add_argument('--reviewed-at')
    p.add_argument('--previous-manifest', type=Path)
    args = p.parse_args(argv)
    try:
        if args.action == 'init':
            if not args.output:
                raise ValueError('new_output_required')
            desk.write_new(args.output, init(args.project_id))
            result = dict(status='template_created', complete=False)
        elif args.action == 'frame-safety-bind':
            if not all((args.input, args.frame_plan, args.frame_review, args.output)):
                raise ValueError('frame_safety_bind_requires_manifest_plan_review_and_new_output')
            value = covers.read(args.input)
            value['frame_safety_plan_ref'] = covers.reference(args.frame_plan)
            value['frame_safety_review_ref'] = covers.reference(args.frame_review)
            framing.for_delivery(value, framing.probe_media)
            value['acceptance_ref'] = None
            desk.write_new(args.output, value)
            result = dict(status='frame_safety_bound', frame_safety_plan_ref=value['frame_safety_plan_ref'])
        elif args.action == 'frame-postcheck':
            if not all((args.frame_plan, args.candidate, args.output_dir)):
                raise ValueError('frame_postcheck_requires_plan_candidate_and_new_output_directory')
            result = frame_postcheck(covers.reference(args.frame_plan), covers.reference(args.candidate),
                                     args.output_dir.resolve())
        elif args.action == 'rebind-copy-acceptance':
            if not all((args.input, args.output, args.reviewer, args.reviewed_at)):
                raise ValueError('rebind_copy_acceptance_requires_input_output_reviewer_and_reviewed_at')
            result = rebind_copy_acceptance(
                args.input,
                args.output,
                reviewer=args.reviewer,
                reviewed_at=args.reviewed_at,
                previous_manifest_path=args.previous_manifest,
            )
        elif args.action == 'materials-redraw':
            if not all((args.input, args.redraw_record, args.output)):
                raise ValueError('materials_redraw_requires_manifest_record_and_new_output')
            value = covers.read(args.input)
            inventory = materials.redraw_intake(value, covers.reference(args.redraw_record))
            desk.write_new(args.output, inventory)
            result = dict(status='material_redraw_registered', intake_ref=covers.reference(args.output))
        elif args.action == 'materials-card-replace':
            if not all((args.input, args.card_replacement_record, args.output)):
                raise ValueError('materials_card_replace_requires_manifest_record_and_new_output')
            value = covers.read(args.input)
            inventory = materials.card_replace_intake(value, covers.reference(args.card_replacement_record))
            desk.write_new(args.output, inventory)
            result = dict(status='material_card_replacement_registered', intake_ref=covers.reference(args.output))
        elif args.action == 'materials-bind':
            if not all((args.input, args.output, args.material_intake)):
                raise ValueError('materials_bind_requires_manifest_intake_and_new_output')
            value = covers.read(args.input)
            value['material_intake_ref'] = covers.reference(args.material_intake)
            value['material_final_review_ref'] = covers.reference(args.material_review) if args.material_review else None
            items, pending = materials.intake(value, require_ready=False)
            value['acceptance_ref'] = None
            desk.write_new(args.output, value)
            result = dict(status='material_records_bound', complete=False, asset_count=len(items),
                          pending_use_basis=pending, final_review_bound=bool(args.material_review))
        elif args.action == 'materials-check':
            if not args.input:
                raise ValueError('materials_check_requires_manifest')
            value = covers.read(args.input)
            if args.candidate:
                candidate = covers.reference(args.candidate)
                _, probe = vkp_modules()
                result = materials.check_final(value, candidate, probe(bound(candidate)).duration_seconds, renderer_module())
            else:
                result = materials.check_intake(value)
            if args.output:
                desk.write_new(args.output, result)
        elif args.action == 'pacing-check':
            import video_pacing
            if not all((args.candidate, args.script, args.pacing_subtitles, args.output_dir)):
                raise ValueError('pacing_requires_candidate_script_final_subtitles_and_new_output_dir')
            path = video_pacing.prepare(args.candidate, args.script, args.pacing_subtitles,
                                        args.pacing_vkp_run, args.output_dir, args.pacing_source_subtitles)
            result = dict(status='video_pacing_measured', complete=False, pacing_report_ref=covers.reference(path))
        elif args.action == 'pacing-bind':
            if not all((args.input, args.output, args.pacing_report)):
                raise ValueError('pacing_binding_requires_input_report_and_new_output')
            manifest = covers.read(args.input)
            manifest['pacing_report_ref'] = covers.reference(args.pacing_report)
            pacing_check(manifest)
            desk.write_new(args.output, manifest)
            result = dict(status='video_pacing_bound', complete=False)
        elif args.action in ('overlays-bind','overlays-check'):
            import video_overlay_selection as overlays
            if args.plan is None:
                raise ValueError('video_overlay_assessment_required')
            plan_ref = covers.reference(args.plan)
            if args.action == 'overlays-check':
                if args.script is None or args.overlay_ass is None:
                    raise ValueError('overlay_check_requires_current_script_and_ass')
                choices = overlays.assess(read_ref(plan_ref), covers.reference(args.script))
                result = dict(status='overlay_layers_checked', plan_ref=plan_ref,
                              **overlays.check_ass(choices, args.overlay_ass))
                if args.output:
                    desk.write_new(args.output, result)
            else:
                if args.input is None or args.output is None:
                    raise ValueError('overlay_bind_requires_manifest_and_new_output')
                manifest = covers.read(args.input)
                choices = overlays.assess(read_ref(plan_ref), manifest.get('script_ref'))
                identity_source = manifest.get('identity_overlay', {}).get('source_ref')
                manifest['identity_overlay'] = dict(choices['insurance'],
                    source_ref=identity_source if choices['insurance']['decision']=='required' else None)
                manifest['medical_overlay'] = dict(choices['medical'], script_ref=manifest['script_ref'])
                manifest['overlay_assessment_ref'] = plan_ref
                manifest['acceptance_ref'] = None
                desk.write_new(args.output, manifest)
                result = dict(status='overlay_applicability_bound', complete=False)
        elif args.action == 'rough-cut-bind':
            if not all((args.input, args.output, args.rough_cut_delivery, args.rough_cut_acceptance)):
                raise ValueError('rough_cut_binding_inputs_required')
            import rough_cut_checks
            manifest = covers.read(args.input)
            manifest['rough_cut_delivery_ref'] = rough_cut_checks.ref(args.rough_cut_delivery)
            manifest['rough_cut_acceptance_ref'] = rough_cut_checks.ref(args.rough_cut_acceptance)
            rough_cut_checks.check_manifest(manifest)
            manifest['acceptance_ref'] = None
            desk.write_new(args.output, manifest)
            result = dict(status='rough_cut_review_bound', complete=False)
        elif args.action in ('performance-init','performance-bind','performance-review-template'):
            if not args.input or not args.output:
                raise ValueError('performance_existing_manifest_and_new_output_required')
            manifest = covers.read(args.input)
            if args.action == 'performance-init':
                payload = performance_template(manifest)
            elif args.action == 'performance-bind':
                if not args.plan:
                    raise ValueError('performance_plan_path_required')
                manifest['performance_plan_ref'] = covers.reference(args.plan)
                performance_plan(manifest)
                manifest['acceptance_ref'] = None
                payload = manifest
            else:
                data = desk.normalize(read_ref(manifest['desk_ref']))
                if len(data['items']) != 1 or data['project_id'] != manifest['project_id']:
                    raise ValueError('performance_matching_single_video_desk_required')
                payload = performance_review_template(manifest, data['items'][0]['video'])
            desk.write_new(args.output, payload)
            result = dict(status='performance_record_prepared_pending_review', complete=False,
                          audience_effect_verified=False, media_changed=False)
        elif args.action == 'cta-init':
            if not args.output or not args.project_id or not args.script:
                raise ValueError('cta_project_script_and_new_output_required')
            desk.write_new(args.output, cta.empty_plan(args.project_id, covers.reference(args.script)))
            result = dict(status='cta_decisions_pending', complete=False, mandatory_cta=False)
        elif args.action in ('identity-select','bgm-select'):
            if not args.input or not args.output or not args.reason:
                raise ValueError('selection_requires_existing_manifest_reason_and_new_output')
            manifest=covers.read(args.input)
            if args.action=='identity-select':
                manifest['identity_overlay']=dict(decision=args.decision,reason=args.reason,
                    source_ref=covers.reference(args.identity_source) if args.identity_source else None)
                identity_selection(manifest)
            else:
                manifest['background_music']=dict(decision=args.decision,reason=args.reason,
                    plan_ref=covers.reference(args.plan) if args.plan else None)
                bgm_selection(manifest)
            desk.write_new(args.output,manifest)
            result=dict(status='selection_bound_pending_actual_final_review',complete=False)
        elif args.action == 'observe-final':
            if not args.input or not args.output_dir:
                raise ValueError('existing_manifest_and_new_observation_directory_required')
            packet=observe_final(covers.read(args.input),args.output_dir.resolve())
            result=dict(status='observed_pending_human_review',complete=False,
                frames=len(packet['frames']),observations_ref=covers.reference(args.output_dir/'observations.json'))
        elif args.action == 'context-bind':
            if not args.input or not args.output or not args.context_manifest:
                raise ValueError('context_bind_requires_existing_manifest_context_and_new_output')
            manifest = covers.read(args.input)
            import purpose_continuity
            previous=manifest.get('context_manifest_ref')
            current=purpose_continuity.validate_context(args.context_manifest)
            if previous:purpose_continuity.check_transition(purpose_continuity.validate_context(bound(previous)),current)
            manifest['context_manifest_ref'] = covers.reference(args.context_manifest)
            desk.write_new(args.output,manifest)
            result=dict(status='context_bound_pending_live_checks',complete=False,
                human_acceptance_preserved=True, media_changed=False)
        elif args.action == 'cta-bind':
            if not args.input or not args.output or not args.plan:
                raise ValueError('cta_input_plan_and_new_output_required')
            manifest = covers.read(args.input)
            if args.script:
                manifest['script_ref'] = covers.reference(args.script)
            plan_ref = covers.reference(args.plan)
            plan, _ = cta.checked_plan(plan_ref, project_id=manifest['project_id'], script_ref=manifest.get('script_ref'))
            manifest['script_ref'] = plan['script_ref']
            manifest['cta_plan_ref'] = plan_ref
            manifest['acceptance_ref'] = None
            desk.write_new(args.output, manifest)
            result = dict(status='cta_plan_bound_pending_landing', complete=False)
        elif args.action == 'progress-select':
            if not args.input or not args.output:raise ValueError('input_and_new_output_required')
            manifest=covers.read(args.input)
            if args.script:manifest['script_ref']=covers.reference(args.script)
            manifest['progress_overlay']=progress.select(manifest,args.decision,args.reason,
                packaging_ref=covers.reference(args.packaging) if args.packaging else None,
                layout_ref=covers.reference(args.layout) if args.layout else None,
                spec_ref=covers.reference(args.spec) if args.spec else None,workspace_root=args.workspace_root,
                program_ref=covers.reference(args.program) if args.program else None,
                omission_source_ref=covers.reference(args.progress_omit_source) if args.progress_omit_source else None)
            manifest['acceptance_ref']=None
            desk.write_new(args.output,manifest)
            result=dict(status='progress_decision_recorded',complete=False,decision=args.decision)
        elif args.action == 'context':
            result = context(covers.read(args.input))
            if args.output:
                desk.write_new(args.output, result)
        elif args.action == 'render':
            if not args.render_job:
                raise ValueError('explicit_render_job_required')
            result = guarded_render(args.input, args.render_job)
            if args.output:
                desk.write_new(args.output, result)
        else:
            result = audit(args.input, 'preflight' if args.action == 'preflight' else 'delivery',args.context_manifest)
            if args.action == 'deliver':
                manifest = covers.read(args.input)
                delivery_manifest = args.input
                blockers = [row for row in result['checks'] if row['status'] == 'blocked']
                if (len(blockers) == 1
                        and blockers[0]['reason'] == 'final_audio_measurement_pending_deliver'):
                    if not args.output or args.output.exists() or args.output.is_symlink():
                        raise ValueError('new_output_required')
                    if args.context_manifest is not None:
                        manifest['context_manifest_ref'] = covers.reference(args.context_manifest)
                    try:
                        delivery_manifest, ref, origin = attach_final_audio_measurement(manifest, args.output)
                    except (OSError, ValueError, KeyError, TypeError, ImportError, RuntimeError) as error:
                        result['final_audio'] = dict(status='not_measured', reason=str(error))
                        blockers[0]['reason'] = str(error)
                    else:
                        result = audit(delivery_manifest)
                        result['final_audio_measurement_ref'] = ref
                        result['delivery_manifest_ref'] = covers.reference(delivery_manifest)
                        result['final_audio_measurement_origin'] = origin
                if not result['complete']:
                    print(json.dumps(result, ensure_ascii=False)); return 2
                if not args.output:
                    raise ValueError('new_output_required')
                page = desk.render(read_ref(manifest['desk_ref']), delivery_manifest=delivery_manifest)
                desk.write_new(args.output, page)
            elif args.output:
                desk.write_new(args.output, result)
        print(json.dumps(result, ensure_ascii=False))
        return 2 if result.get('status') == 'blocked' else 0
    except (OSError, ValueError, KeyError, TypeError, ImportError, RuntimeError) as error:
        print(json.dumps(dict(status='blocked', complete=False, code=getattr(error,'code',type(error).__name__), reason=str(error)), ensure_ascii=False))
        return 2


def rough_audio_check(manifest, mapped):
    """All editor routes share measured segment acceptance, separate from final LUFS."""
    speech = [r for r in mapped['expected_audio'] if r['kind'] == 'speech']
    if not speech:
        return dict(status='not_applicable', reason='explicit timeline inventory contains no speech')
    renderer_module()  # Resolve the existing local MVP package; no renderer runs.
    from video_creation_pipeline.segment_leveling import load_report, validate_leveling, speech_groups
    from video_creation_pipeline.contract_io import artifact_reference
    if not manifest.get('rough_audio_review_ref'):
        raise ValueError('rough_cut_segment_leveling_before_after_evidence_required_whole_track_LUFS_is_insufficient')
    review = read_ref(manifest.get('rough_audio_review_ref'))
    before = load_report(review.get('before_ref'))
    rows = manifest['timeline']['segments']
    # Only cuts with spoken content are leveled; music-only inserts remain intact.
    spoken_ids = {r['segment_id'] for r in manifest['timeline']['expected_audio'] if r['kind']=='speech'}
    rows = [r for r in rows if r['id'] in spoken_ids]
    source = before['source_media']
    timeline_clock = before['analysis_clock'] == 'edited_timeline'
    if timeline_clock and read_ref(review.get('timeline_ref')) != manifest['timeline']:
        raise ValueError('segment_audio_current_timeline_binding_required')
    if timeline_clock or source['sha256'] == manifest['edited_media']['sha256']:
        keeps = [dict(start=r['target_start'], end=r['target_end']) for r in rows]
        windows = [dict(start=r['start_seconds'], end=r['end_seconds']) for r in speech]
    else:
        if any(r['source_ref']['sha256'] != source['sha256'] or abs(r['speed']-1) > 1e-7 for r in rows):
            raise ValueError('segment_audio_source_or_speed_changed_remeasure_current_dialogue_timeline')
        keeps = [dict(start=r['source_start'], end=r['source_end']) for r in rows]
        windows = [dict(start=r['source_start'],end=r['source_end']) for r in manifest['timeline']['expected_audio'] if r['kind']=='speech']
    _, groups = speech_groups(keeps, windows)
    if before['speech_windows'] != [w for group in groups for w in group]:
        raise ValueError('segment_audio_speech_coverage_changed_or_incomplete')
    return validate_leveling(review, keeps=keeps, require_after=True,
        output_segments=[dict(start=r['target_start'],end=r['target_end']) for r in rows],
        measured_media=artifact_reference(bound(manifest['edited_media']), 'current edited media'))

if __name__ == '__main__':
    raise SystemExit(main())
