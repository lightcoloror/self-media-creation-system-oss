"""Evidence-bound video delivery subflow; reuse existing inspectors, never publish.

No ASR model, renderer, automatic human approval or private-media discovery here.
The same live audit backs both CLI completion and publication-desk delivery.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import sys
import re
import shutil
import uuid
from pathlib import Path

import publication_desk as desk
import cover_workbench as covers
import cover_strategy
import video_progress_contract as progress
import cta_review as cta

ROOT = Path(__file__).resolve().parents[1]
VKP = ROOT.parent / 'video-knowledge-pipeline'
SCHEMA = 'self-media.video-delivery.v1'
HUMAN_CHECKS = ('full_video_watched', 'full_audio_listened', 'burned_subtitles_correct',
                'mobile_readable', 'cards_and_subjects_unobscured', 'audio_joins_balanced',
                'story_and_copy_correct', 'privacy_checked')


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
    source = ROOT.parent / 'ai-video-tools-20260708/mvp-video-pipeline/src'
    if not (source / 'video_creation_pipeline/execution_receipts.py').is_file():
        raise ValueError('existing_renderer_unavailable')
    if str(source) not in sys.path:
        sys.path.insert(0, str(source))
    from video_creation_pipeline import execution_receipts
    return execution_receipts


def init(project_id):
    if not isinstance(project_id, str) or not project_id.strip():
        raise ValueError('project_id_required')
    return dict(schema=SCHEMA, project_id=project_id, edited_media=None, script_ref=None,
                facts=dict(story='', do_not_infer=[], feedback=[], no_prior_feedback_reason=''),
                timeline=dict(duration_seconds=None, segments=[], expected_audio=[]),
                subtitles=dict(request_ref=None, pack_ref=None, asr_ref=None, review_ref=None, render_file_ref=None),
                render_receipt_ref=None, desk_ref=None, cover_review_ref=None,
                acceptance_ref=None, rough_audio_review_ref=None, cta_plan_ref=None,
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
                progress_overlay_planning=dict(decision=manifest.get('progress_overlay',{}).get('decision','undecided'),
                    reason=manifest.get('progress_overlay',{}).get('reason',''),explicit_decision_required=True,
                    selected_overlay_requires_checked_reservation=True,
                    default_title_source='script', default_font_preset='compact',
                    navigation_font_independent_of_body_and_subtitles=True,
                    entrypoint='video-delivery progress-select; preflight blocks missing/stale choice or reservation'),
                cta_planning=dict(plan_ref=manifest.get('cta_plan_ref'), types=list(cta.KINDS),
                    explicit_decision_required=True, omission_with_reason_allowed=True,
                    entrypoint='video-delivery cta-init / cta-bind; final acceptance.cta_landing'),
                source_text_is_instruction=False, full_history_discovery_proven=False)


def number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError('finite_time_required')
    return float(value)


def timeline(manifest):
    """Flattened constant-speed segments, including pauses/inserts, not guessed offsets."""
    _, probe = vkp_modules()
    edited = bound(manifest['edited_media'])
    meta = probe(edited)
    value = manifest['timeline']
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
    if abs(cursor - duration) > .001:
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
    return dict(duration_seconds=duration, expected_audio=projected)


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
    if (receipt.get('schema') != 'video_creation_pipeline.ffmpeg_execution_receipt.v1'
            or receipt.get('status') != 'completed'
            or receipt.get('outlet_id') != 'video_creation_pipeline.single_ffmpeg_outlet'):
        raise ValueError('existing_renderer_completed_receipt_required')
    def contains(rows, expected):
        return any(r.get('artifact', {}).get('sha256') == expected['sha256'] and
                   Path(r['artifact']['path']).resolve() == Path(expected['path']).resolve()
                   for r in rows)
    # Rendering can have multiple intermediate steps (e.g. burn then audio balance).
    chain = [read_ref(ref) for ref in manifest.get('render_chain_refs', [])] + [receipt]
    previous = manifest['edited_media']
    for index, step in enumerate(chain):
        renderer_module().validate_ffmpeg_execution_receipt(step)
        if (step.get('schema') != receipt['schema'] or step.get('status') != 'completed'
                or step.get('outlet_id') != receipt['outlet_id'] or not contains(step.get('inputs', []), previous)):
            raise ValueError('render_lineage_mismatch')
        candidates = [r['artifact'] for r in step.get('outputs', []) if r.get('role') == 'candidate']
        if len(candidates) != 1:
            raise ValueError('one_render_candidate_output_required')
        previous = candidates[0]
        bound(previous)
    if not contains(receipt.get('outputs', []), final):
        raise ValueError('desk_video_not_render_output')
    _, probe = vkp_modules()
    meta = probe(final_path)
    if (not meta.width or not meta.height or
            abs(meta.duration_seconds - manifest['timeline']['duration_seconds']) > .05):
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


def acceptance_fingerprint(manifest):
    value = copy.deepcopy(manifest)
    value.pop('acceptance_ref', None)
    # Context metadata has its own live requirement gate below. A provenance-only
    # binding must not discard unchanged, media-bound human observations.
    value.pop('context_manifest_ref', None)
    return fingerprint(value)


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
    if len(times) > 72:
        raise ValueError('final_layout_requires_bounded_transition_samples')
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
    if any(row['timeline_start_s']+row['duration_s']>manifest['timeline']['duration_seconds']+.05 for row in report['layers']):
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
    output_dir = Path(output_dir)
    if not output_dir.is_absolute() or output_dir.exists():
        raise ValueError('final_observation_requires_new_absolute_output_directory')
    times = final_sample_times(manifest,meta.duration_seconds)
    from video_knowledge_pipeline.models import EvidenceSegment
    from video_knowledge_pipeline.video import extract_segment_frames
    segments = [EvidenceSegment(id=f'final-{i:03}',video_id=manifest['project_id'],start=t,end=t+.001,
                    midpoint=t,signals=['final_delivery_layout_sample']) for i,t in enumerate(times)]
    output_dir.mkdir(parents=True)
    extract_segment_frames(source,output_dir,segments)
    packet = dict(schema='self-media.final-observations.v1',project_id=manifest['project_id'],
        video_ref=video,layout_ref=manifest.get('final_layout_ref'),
        frames=[dict(time_seconds=s.midpoint,frame_ref=covers.reference(s.frame_paths[0])) for s in segments],
        inspector='video_knowledge_pipeline.video.extract_segment_frames',
        human_approved=False, automatic_ocr=False)
    desk.write_new(output_dir/'observations.json',packet)
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
            abs(layout['duration_seconds']-manifest['timeline']['duration_seconds']) > .05):
        raise ValueError('final_layout_belongs_to_other_media_or_timeline')
    result = validate_final_layout_path(path,root)
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
    expected = final_sample_times(manifest,probe(bound(final)).duration_seconds)
    rows = packet.get('frames',[])
    if [r.get('time_seconds') for r in rows] != expected:
        raise ValueError('final_observations_need_head_middle_tail_and_layout_transitions')
    for row in rows:
        bound(row['frame_ref'])
    # A hash of an arbitrary picture is insufficient: reproduce samples from the
    # current final video using the same existing inspector and compare bytes.
    scratch = ROOT/'.test-runtime'/('final-observe-'+uuid.uuid4().hex)
    try:
        fresh = observe_final(manifest,scratch.resolve())
        if [r['frame_ref']['sha256'] for r in fresh['frames']] != [r['frame_ref']['sha256'] for r in rows]:
            raise ValueError('final_observation_frames_not_from_current_media')
    finally:
        if scratch.is_dir() and not scratch.is_symlink() and scratch.resolve().is_relative_to((ROOT/'.test-runtime').resolve()):
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
            if re.search(r'(?i)(textfile|fontfile|fontsdir|file=)', expression):
                raise ValueError('unbound_filter_file_not_allowed')
            if 'subtitles=' in expression or expression.startswith('ass='):
                match = re.fullmatch(r"(?:subtitles|ass)='([^']+)'(?::force_style='[^']*')?", expression)
                if not match:
                    raise ValueError('use_bound_standalone_subtitle_filter')
                ref = manifest['subtitles'].get('render_file_ref')
                subtitle = bound(ref)
                decoded = match[1].replace(r'\:', ':').replace(r'\\', '\\')
                if Path(decoded).resolve() != subtitle.resolve() or not any(r['artifact'] == ref for r in refs):
                    raise ValueError('render_subtitle_file_not_bound')
                request = read_ref(manifest['subtitles']['request_ref'])
                if ref not in request.get('evidence_files', []):
                    raise ValueError('subtitle_file_not_in_coverage_review_fingerprint')
                if subtitle.suffix.lower() in ('.srt', '.vtt'):
                    from video_knowledge_pipeline.transcript import parse_transcript
                    observed = [(round(c.start, 3), round(c.end, 3), ' '.join(c.text.split()))
                                for c in parse_transcript(subtitle)]
                    pack = read_ref(manifest['subtitles']['pack_ref'])
                    expected = [(round(c['start_seconds'], 3), round(c['end_seconds'], 3), ' '.join(c['text'].split()))
                                for c in pack['requests'][0]['subtitle_cues']]
                    if observed != expected:
                        raise ValueError('burn_file_disagrees_with_reviewed_cues')
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
    return dict(status='rendered_pending_delivery_review', complete=False, publish_authorized=False,
                render_receipt_ref=covers.reference(receipt), output_ref=covers.reference(output),
                preflight_fingerprint=report['acceptance_fingerprint'], disk=disk, outlet_id=rendered['outlet_id'])


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
    run('context', lambda: context(manifest))
    run('cta_selection_and_position', lambda: cta.checked_plan(manifest.get('cta_plan_ref'), project_id=manifest['project_id'], script_ref=manifest.get('script_ref'), require_timing=True))
    mapped = run('timeline', lambda: timeline(manifest))
    run('progress_selection_and_reservation', lambda: progress.check(manifest,'preflight'))
    run('insurance_identity_selection', lambda: identity_selection(manifest))
    result['bgm_selection']=run('BGM_selection_and_arrangement',lambda:bgm_selection(manifest))
    if mapped is not None:
        result['rough_audio'] = run('rough_cut_segment_speech_levels', lambda: rough_audio_check(manifest, mapped))
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
    result['preflight_ready'] = all(r['status'] == 'passed' for r in result['checks'])
    if phase == 'delivery':
        data=run('render_and_desk', lambda: render_check(manifest))
        result['final_layout'] = run('final_media_layout_and_observations',lambda:final_layout_check(manifest,data))
        run('progress_render_and_layout', lambda: progress.check(manifest,'delivery',data['items'][0]['video'] if data else None))
        def check_cover():
            review = read_ref(manifest['cover_review_ref'])
            if review.get('desk_ref') != manifest['desk_ref']:
                raise ValueError('cover_review_for_other_desk')
            return cover_strategy.review_check(bound(manifest['cover_review_ref']))
        run('covers', check_cover)
        def check_acceptance():
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
            observed = receipt.get('final_layout_review',{})
            if (result['final_layout'] is None or observed.get('video_sha256') != data['items'][0]['video']['sha256']
                    or observed.get('layout_sha256') != manifest.get('final_layout_ref',{}).get('sha256')
                    or observed.get('observations_sha256') != manifest.get('final_observations_ref',{}).get('sha256')
                    or observed.get('rendered_elements_verified') is not True
                    or observed.get('mobile_readable') is not True):
                raise ValueError('actual_final_layout_human_observations_required')
            if result['final_layout']['ai_disclosure']['required'] and observed.get('ai_label_visible') is not True:
                raise ValueError('actual_final_AI_label_human_review_required')
            if result['final_layout']['identity_decision']=='required' and observed.get('identity_text_checked') is not True:
                raise ValueError('actual_final_insurance_identity_human_review_required')
            if manifest.get('background_music',{}).get('decision')=='use':
                music=receipt.get('bgm_review',{})
                if (music.get('video_sha256')!=data['items'][0]['video']['sha256']
                        or music.get('plan_sha256')!=manifest['background_music']['plan_ref']['sha256']
                        or music.get('balance_checked') is not True or music.get('arrangement_listened') is not True):
                    raise ValueError('actual_final_BGM_balance_and_arrangement_listening_required')
            result['cta_landing'] = cta.check_delivery(manifest, data, receipt)
        run('human_acceptance', check_acceptance)
    def requirements():
        import purpose_continuity
        reference = manifest.get('context_manifest_ref')
        if phase == 'delivery' and reference is None:
            raise ValueError('current_execution_context_required; bind existing purpose/feedback, do not restart production')
        return purpose_continuity.check_consumer(reference, 'video_delivery', dict(
            phase=phase, manifest=manifest, checks=copy.deepcopy(result['checks']),
            final_media=data['items'][0]['video'] if phase=='delivery' and data is not None else None))
    result['requirement_report'] = run('current_execution_requirements', requirements)
    ok = all(r['status'] == 'passed' for r in result['checks'])
    result.update(status=('preflight_ready' if phase == 'preflight' else 'complete_local_candidate') if ok else 'blocked',
                  complete=ok and phase == 'delivery')
    result['next_action'] = next((r['stage'] for r in result['checks'] if r['status'] != 'passed'),
                                 'existing_resource_gated_renderer' if phase == 'preflight' else 'human_platform_review')
    return result


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=['init', 'context', 'preflight', 'render', 'check', 'deliver', 'progress-select', 'cta-init', 'cta-bind', 'context-bind', 'observe-final', 'identity-select', 'bgm-select'])
    p.add_argument('--input', type=Path)
    p.add_argument('--output', type=Path)
    p.add_argument('--project-id')
    p.add_argument('--context-manifest',type=Path)
    p.add_argument('--output-dir',type=Path)
    p.add_argument('--plan', type=Path, help='Existing CTA plan, shared with the publication desk')
    p.add_argument('--render-job', type=Path)
    p.add_argument('--decision',choices=['use','not_used','required','not_applicable'])
    p.add_argument('--identity-source',type=Path)
    p.add_argument('--reason')
    p.add_argument('--packaging',type=Path)
    p.add_argument('--layout',type=Path)
    p.add_argument('--spec',type=Path)
    p.add_argument('--workspace-root',type=Path)
    p.add_argument('--program',type=Path,help='Progress input after prior bound renders; defaults to edited_media')
    p.add_argument('--script',type=Path,help='Current video script; progress headings default to this bound source')
    args = p.parse_args(argv)
    try:
        if args.action == 'init':
            if not args.output:
                raise ValueError('new_output_required')
            desk.write_new(args.output, init(args.project_id))
            result = dict(status='template_created', complete=False)
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
                program_ref=covers.reference(args.program) if args.program else None)
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
                if not result['complete']:
                    print(json.dumps(result, ensure_ascii=False)); return 2
                if not args.output:
                    raise ValueError('new_output_required')
                manifest = covers.read(args.input)
                page = desk.render(read_ref(manifest['desk_ref']), delivery_manifest=args.input)
                desk.write_new(args.output, page)
            elif args.output:
                desk.write_new(args.output, result)
        print(json.dumps(result, ensure_ascii=False))
        return 2 if result.get('status') == 'blocked' else 0
    except (OSError, ValueError, KeyError, TypeError, ImportError) as error:
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


