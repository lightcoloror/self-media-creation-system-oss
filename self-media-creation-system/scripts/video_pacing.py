"""Measure pacing on the encoded video and verify the version-bound report."""

import json
from bisect import bisect_left
import math
from pathlib import Path
import re
from statistics import median

from rough_cut_checks import _mvp, bound, load, ref, run_local_vkp, vkp_transcript, write_new


SCHEMA = 'self-media.video-pacing.v1'
OUTLET = 'video_creation_pipeline.single_ffmpeg_outlet'
SILENCE_FILTER = 'silencedetect=noise=-40dB:d=0.12'
_THRESHOLDS_PATH = Path(__file__).resolve().parents[1] / 'config/video-quality-thresholds.v1.json'


def _load_pacing_thresholds():
    if _THRESHOLDS_PATH.is_file():
        cfg = json.loads(_THRESHOLDS_PATH.read_text(encoding='utf-8')).get('pacing', {})
        return float(cfg.get('long_pause_seconds', 1.5)), float(cfg.get('bgm_speech_gap_seconds', 1.5))
    return 1.5, 1.5


LONG_PAUSE_SECONDS, BGM_SPEECH_GAP_SECONDS = _load_pacing_thresholds()


ALLOWED_TIMESTAMP_COORDS = {None, 'absolute_ms', 'chunk_relative'}


def speech_spans(raw, duration):
    """Return sorted (word_start_s, word_end_s, unit_count) spans using producer coordinate semantics."""
    spans = []
    chunk_core_by_idx = {}
    unindexed_cores = []
    raw_coord = raw.get('timestamp_coordinate')
    if raw_coord not in ALLOWED_TIMESTAMP_COORDS:
        raise ValueError('pacing_unknown_timestamp_coordinate: ' + str(raw_coord))
    for chunk in raw['result']:
        words, timestamps = chunk['words'], chunk['timestamp']
        if len(words) != len(timestamps):
            raise ValueError('pacing_vkp_word_timestamp_count_mismatch')
        chunk_coord = chunk.get('timestamp_coordinate')
        if chunk_coord not in ALLOWED_TIMESTAMP_COORDS:
            raise ValueError('pacing_unknown_timestamp_coordinate: ' + str(chunk_coord))
        if raw_coord and chunk_coord and raw_coord != chunk_coord:
            raise ValueError('pacing_conflicting_timestamp_coordinate')
        effective_coord = chunk_coord or raw_coord or 'absolute_ms'
        offset = float(chunk['chunk_offset_seconds'])
        core_start = float(chunk['chunk_core_start_seconds'])
        core_end = float(chunk['chunk_core_end_seconds'])
        chunk_end = float(chunk.get('chunk_end_seconds', core_end))
        if (
            not all(math.isfinite(v) for v in (offset, core_start, core_end, chunk_end))
            or offset < -0.5
            or chunk_end < offset
            or not (offset - 0.5 <= core_start < core_end <= chunk_end + 0.5)
            or core_end > duration + 0.5
        ):
            raise ValueError('pacing_vkp_chunk_bounds_invalid')
        chunk_idx = chunk.get('chunk_index')
        if chunk_idx is not None:
            if chunk_idx in chunk_core_by_idx:
                prev_cs, prev_ce = chunk_core_by_idx[chunk_idx]
                if abs(prev_cs - core_start) > 1e-6 or abs(prev_ce - core_end) > 1e-6:
                    raise ValueError('pacing_vkp_chunk_bounds_inconsistent')
            else:
                chunk_core_by_idx[chunk_idx] = (core_start, core_end)
        else:
            unindexed_cores.append((core_start, core_end))
        effective_offset = offset if effective_coord == 'chunk_relative' else 0.0
        for word, (start, end) in zip(words, timestamps):
            count = sum(char.isalnum() for char in word)
            s_sec = effective_offset + float(start) / 1000.0
            e_sec = effective_offset + float(end) / 1000.0
            center = 0.5 * (s_sec + e_sec)
            if count and (
                not math.isfinite(s_sec) or not math.isfinite(e_sec)
                or not 0 <= s_sec <= e_sec <= duration + .5
            ):
                raise ValueError('pacing_vkp_word_timestamp_out_of_bounds')
            if count and (s_sec < offset - 0.5 or e_sec > chunk_end + 0.5):
                raise ValueError('pacing_vkp_word_outside_chunk_bounds')
            if count and core_start <= center < core_end:
                spans.append((s_sec, e_sec, count))
    core_ranges = sorted(list(chunk_core_by_idx.values()) + unindexed_cores)
    for (_, prev_end), (next_start, _) in zip(core_ranges, core_ranges[1:]):
        if prev_end > next_start + 1e-6:
            raise ValueError('pacing_vkp_overlapping_core_ranges')
    if not spans:
        raise ValueError('pacing_vkp_word_timestamps_required')
    return sorted(spans, key=lambda item: (item[0], item[1]))


def speech_points(raw, duration):
    points = []
    for s_sec, e_sec, count in speech_spans(raw, duration):
        center = 0.5 * (s_sec + e_sec)
        points.extend([center] * count)
    return sorted(points)


def pause_ranges(log, duration):
    ranges = []
    start = None
    for kind, time in re.findall(r'silence_(start|end):\s*(-?\d+(?:\.\d+)?)', log):
        when = min(duration, max(0.0, float(time)))
        if kind == 'start':
            start = when
        elif start is not None:
            ranges.append((start, when))
            start = None
    if start is not None:
        ranges.append((start, duration))
    merged = []
    for start, end in ranges:
        if merged and start - merged[-1][1] <= .05:
            merged[-1][1] = end
        else:
            merged.append([start, end])
    return [dict(start=round(a, 3), end=round(b, 3), seconds=round(b - a, 3))
            for a, b in merged if b - a >= .9]


def measure(candidate, pack, run, duration, log):
    _, refs = vkp_transcript(candidate, run)
    spans = speech_spans(load(bound(refs[1])), duration)
    points = sorted(0.5 * (s + e) for s, e, count in spans for _ in range(count))
    window = min(10.0, duration)
    final_start = duration - window
    starts = sorted({0.0, final_start, *(t for t in points if t < final_start)})
    windows = [dict(start=round(t, 3), end=round(t + window, 3),
                    units_per_minute=round((bisect_left(points, t + window) - bisect_left(points, t)) * 60 / window))
               for t in starts]
    windows.sort(key=lambda row: (-row['units_per_minute'], row['start']))
    peaks = []
    for row in windows:
        if all(row['start'] >= prior['end'] or row['end'] <= prior['start'] for prior in peaks):
            peaks.append(row)
        if len(peaks) == 5:
            break
    requests = pack['requests']
    if len(requests) != 1 or requests[0]['artifact_sha256'] != candidate['sha256']:
        raise ValueError('pacing_subtitles_must_reference_current_render')
    if not requests[0]['full_source_review'] or abs(float(requests[0]['review_end_seconds']) - duration) > .5:
        raise ValueError('pacing_subtitles_must_cover_final_timeline')
    reading = []
    for cue in requests[0]['subtitle_cues']:
        start, end = float(cue['start_seconds']), float(cue['end_seconds'])
        count = sum(char.isalnum() for char in cue['text'])
        if not 0 <= start < end <= duration + .1:
            raise ValueError('pacing_caption_outside_final_timeline')
        if count:
            reading.append(dict(start=start, end=end, chars_per_second=round(count / (end - start), 2)))
    if not reading:
        raise ValueError('pacing_subtitle_cues_required_for_speech')
    return refs, dict(duration_seconds=duration, speech_units=len(points),
                      units_per_minute=round(len(points) * 60 / duration), local_peaks=peaks,
                      pauses=pause_ranges(log, duration), speech_gaps=speech_gap_ranges(spans),
                      subtitle_cue_count=len(reading),
                      subtitle_median_chars_per_second=median(row['chars_per_second'] for row in reading),
                      densest_subtitles=sorted(reading, key=lambda row: -row['chars_per_second'])[:5])


def prepare(candidate_path, script_path, subtitles, run, output, source_subtitles=None):
    candidate, script, pack_ref = map(ref, (candidate_path, script_path, subtitles))
    pack = load(bound(pack_ref))
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    media = Path(candidate['path'])
    if run is None:
        run = run_local_vkp(media, output / 'vkp')
    asr_refs = vkp_transcript(candidate, run)[1]
    duration = float(load(bound(asr_refs[1]))['duration_seconds'])
    mvp = _mvp()
    media_duration = float(mvp.probe_media_metadata(media)['format']['duration'])
    if not math.isfinite(duration) or duration <= 0 or abs(duration - media_duration) > .5:
        raise ValueError('pacing_vkp_duration_does_not_match_render')
    log, receipt = output / 'pacing-decode.log', output / 'pacing-decode-receipt.json'
    mvp.execute_ffmpeg_with_receipt(
        'technical_qa',
        ['ffmpeg', '-nostdin', '-v', 'info', '-xerror', '-i', str(media),
         '-map', '0:v:0', '-map', '0:a:0', '-af', SILENCE_FILTER, '-f', 'null', '-'],
        [{'role': 'candidate', 'path': media}], [{'role': 'decode_log', 'path': log}], receipt,
        capture_log_path=log, guard_resource=True, timeout_s=3600,
    )
    refs, metrics = measure(candidate, pack, run, duration, log.read_text(encoding='utf-8', errors='replace'))
    report = dict(schema=SCHEMA, candidate=candidate, script=script, subtitles=pack_ref,
                  source_subtitles=ref(source_subtitles) if source_subtitles else pack_ref, vkp=refs,
                  audio_log=ref(log), decoder=ref(receipt), metrics=metrics)
    path = output / 'video-pacing-report.json'
    write_new(path, report)
    return path


def check(report_ref, candidate, script, subtitles):
    if not report_ref:
        raise ValueError('current_video_pacing_report_required')
    report = load(bound(report_ref))
    if report.get('schema') != SCHEMA or [report.get(key) for key in ('candidate', 'script', 'source_subtitles')] != [candidate, script, subtitles]:
        raise ValueError('video_pacing_report_is_for_another_version')
    bound(candidate)
    bound(script)
    bound(subtitles)
    pack = load(bound(report['subtitles']))
    receipt = load(bound(report['decoder']))
    log_ref = report['audio_log']
    def contains(entries, expected):
        return any(all(row['artifact'].get(k) == v for k, v in expected.items()) for row in entries)
    if (receipt.get('outlet_id') != OUTLET or receipt.get('operation') != 'technical_qa'
            or receipt.get('status') != 'completed' or SILENCE_FILTER not in receipt['command']
            or not contains(receipt['inputs'], candidate) or not contains(receipt['outputs'], log_ref)):
        raise ValueError('current_video_pacing_decode_receipt_required')
    log = bound(log_ref).read_text(encoding='utf-8', errors='replace')
    run_ref, raw_ref, *_ = report['vkp']
    duration = float(load(bound(raw_ref))['duration_seconds'])
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError('pacing_vkp_duration_invalid')
    refs, metrics = measure(candidate, pack, bound(run_ref), duration, log)
    saved_metrics = report['metrics']
    # Backward compatibility for legacy v1 pacing receipts generated before speech_gaps existed.
    comparable = metrics if 'speech_gaps' in saved_metrics else {k: v for k, v in metrics.items() if k != 'speech_gaps'}
    if refs != report['vkp'] or comparable != saved_metrics:
        raise ValueError('video_pacing_measurements_changed')
    return metrics


def speech_gap_ranges(spans, min_seconds=BGM_SPEECH_GAP_SECONDS):
    """Measure inter-word silence from previous word END to next word START (never flags a long spoken word)."""
    gaps = []
    if not spans:
        return gaps
    prev_end = spans[0][1]
    for s_sec, e_sec, _ in spans[1:]:
        if s_sec - prev_end >= min_seconds:
            gaps.append(dict(start=round(prev_end, 3), end=round(s_sec, 3), seconds=round(s_sec - prev_end, 3)))
        prev_end = max(prev_end, e_sec)
    return gaps


def _merge_pause_intervals(intervals):
    """Deduplicate only genuinely overlapping pause intervals (never merge two pauses separated by speech)."""
    if not intervals:
        return []
    merged = []
    for a, b in sorted(intervals):
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    return merged


def check_long_pauses(metrics, acceptance, candidate_sha256, *, has_bgm=False):
    required = [(row['start'], row['end']) for row in metrics['pauses']
                if row['seconds'] >= LONG_PAUSE_SECONDS]
    if has_bgm and metrics.get('speech_gaps'):
        gap_intervals = [(row['start'], row['end']) for row in metrics['speech_gaps']
                         if row['seconds'] >= BGM_SPEECH_GAP_SECONDS]
        # Merge & deduplicate mix silences with BGM-masked speech gaps instead of skipping when pauses != [].
        required = _merge_pause_intervals(required + gap_intervals)
    if not required:
        return
    review = acceptance.get('long_pause_review', {})
    rows = review.get('retained_pauses', [])
    if (review.get('video_sha256') != candidate_sha256 or not isinstance(rows, list)
            or any(not isinstance(row, dict) or not isinstance(row.get('reason'), str)
                   or not row['reason'].strip() for row in rows)
            or sorted((row.get('start'), row.get('end')) for row in rows) != required):
        raise ValueError('unresolved_long_pauses_in_final_media: ' + str(required))
