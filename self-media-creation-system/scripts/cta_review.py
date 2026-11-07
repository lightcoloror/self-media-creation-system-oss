"""CTA decisions and landing checks inside existing script/desk/video gates.

Reuse cover_workbench's bound artifacts, the desk's actual fields, and the final
acceptance's observations. No text classifier, renderer, publishing or auto approval.
"""
from __future__ import annotations
import json
import math
from pathlib import Path

SCHEMA = 'self-media.cta-plan.v1'
KINDS = ('interaction', 'acquisition')
VIDEO_LOCATIONS = ('video_spoken', 'video_overlay')
COPY_LOCATIONS = {'publication_body': 'body', 'pinned_comment': 'pinned_comment'}


def text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError('cta_text_required: ' + label)
    return value


def bound(ref):
    # Lazy import: cover_workbench also uses publication_desk's write-once helper.
    import cover_workbench
    if not isinstance(ref, dict) or not ref.get('path') or not ref.get('sha256'):
        raise ValueError('cta_bound_reference_required')
    return cover_workbench.bound(ref)


def load(ref):
    path = bound(ref)
    if path.stat().st_size > 2_000_000:
        raise ValueError('cta_metadata_too_large')
    return json.loads(path.read_text(encoding='utf-8-sig'))


def empty_plan(project_id, script_ref=None):
    return dict(schema=SCHEMA, project_id=project_id, script_ref=script_ref,
                decisions={kind: dict(decision='undecided', reason='', placements=[]) for kind in KINDS})


def times(row, required=False):
    values = [row.get('start_seconds'), row.get('end_seconds')]
    if values == [None, None] and not required:
        return None
    if any(isinstance(v, bool) or not isinstance(v, (float, int)) or not math.isfinite(v) for v in values):
        raise ValueError('cta_finite_time_range_required')
    if values[0] < 0 or values[1] <= values[0]:
        raise ValueError('cta_time_range_invalid')
    return values


def check_plan(plan, project_id=None, script_ref=None, require_timing=False):
    if not isinstance(plan, dict) or plan.get('schema') != SCHEMA:
        raise ValueError('cta_plan_required')
    text(plan.get('project_id'), 'project_id')
    if project_id is not None and plan['project_id'] != project_id:
        raise ValueError('cta_project_mismatch')
    if script_ref is not None and plan.get('script_ref') != script_ref:
        raise ValueError('cta_script_revision_mismatch')
    script = bound(plan.get('script_ref'))
    if script.stat().st_size > 2_000_000:
        raise ValueError('cta_script_too_large')
    body = script.read_text(encoding='utf-8-sig')
    if script.suffix.lower() == '.json':
        value = json.loads(body)
        # Reuse the existing case-video-script's spoken segments, not metadata.
        body = '\n'.join(r['spoken_text'] for r in value.get('segments', []) if 'spoken_text' in r)
    decisions = plan.get('decisions')
    if not isinstance(decisions, dict) or set(decisions) != set(KINDS):
        raise ValueError('cta_both_types_required')
    seen, placements = set(), []
    for kind, decision in decisions.items():
        if not isinstance(decision, dict) or decision.get('decision') not in ('use', 'not_used'):
            raise ValueError('cta_decision_required: ' + kind)
        text(decision.get('reason'), kind + '.reason')
        rows = decision.get('placements')
        if not isinstance(rows, list) or bool(rows) != (decision['decision'] == 'use'):
            raise ValueError('cta_placements_disagree_with_decision: ' + kind)
        if kind == 'acquisition' and rows:
            text(decision.get('service_boundary'), 'acquisition.service_boundary')
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError('cta_placement_object_required')
            ident = text(row.get('id'), 'placement.id')
            if ident in seen:
                raise ValueError('cta_duplicate_placement_id')
            seen.add(ident)
            location = row.get('location')
            if location not in (*VIDEO_LOCATIONS, *COPY_LOCATIONS):
                raise ValueError('cta_location_required: ' + ident)
            phrase = text(row.get('text'), ident + '.text')
            text(row.get('reason'), ident + '.position_reason')
            if location in VIDEO_LOCATIONS:
                if row.get('platform') is not None:
                    raise ValueError('cta_video_location_cannot_target_platform')
                times(row, require_timing)
                if location == 'video_spoken' and phrase not in body:
                    raise ValueError('cta_spoken_text_missing_from_script: ' + ident)
            else:
                text(row.get('platform'), ident + '.platform')
                if 'start_seconds' in row or 'end_seconds' in row:
                    raise ValueError('cta_copy_location_cannot_have_video_time')
            placements.append(dict(row, kind=kind))
    return placements


def checked_plan(ref, **kwargs):
    plan = load(ref)
    return plan, check_plan(plan, **kwargs)


def check_item(item, project_id):
    plan, placements = checked_plan(item.get('cta_plan_ref'), project_id=project_id)
    for row in placements:
        if row['location'] in COPY_LOCATIONS:
            platform = item['platforms'].get(row['platform'])
            if platform is None:
                raise ValueError('cta_target_platform_missing: ' + row['id'])
            actual = platform['fields'].get(COPY_LOCATIONS[row['location']], '')
            if row['text'] not in actual:
                raise ValueError('cta_text_not_at_planned_location: ' + row['id'])
    return dict(complete=True, decisions=plan['decisions'], plan_ref=item['cta_plan_ref'],
                scope='prepared_copy_fields_only; video_landing_requires_final_acceptance; comments_not_posted')


def check_delivery(manifest, data, acceptance):
    item = data['items'][0]
    if item.get('cta_plan_ref') != manifest.get('cta_plan_ref'):
        raise ValueError('cta_desk_and_video_plan_mismatch')
    plan, rows = checked_plan(manifest.get('cta_plan_ref'), project_id=manifest['project_id'],
                              script_ref=manifest.get('script_ref'), require_timing=True)
    check_item(item, manifest['project_id'])
    bound(item['video'])
    review = acceptance.get('cta_landing')
    if not isinstance(review, dict):
        raise ValueError('cta_final_landing_review_required')
    if (review.get('plan_sha256') != manifest['cta_plan_ref']['sha256'] or
            review.get('video_sha256') != item['video']['sha256']):
        raise ValueError('cta_landing_review_stale')
    if review.get('unplanned_cta_absent') is not True:
        raise ValueError('cta_unplanned_content_not_resolved')
    if review.get('prepared_copy_reviewed') is not True:
        raise ValueError('cta_actual_prepared_copy_review_required')
    # The existing final human acceptance verifies the complete viewing and identity.
    # Even a not_used plan needs actual absence observations, not an unchecked default.
    text(review.get('notes'), 'actual video and prepared-copy observations, including absence')
    observations = review.get('observations')
    if not isinstance(observations, list) or any(not isinstance(r, dict) for r in observations):
        raise ValueError('cta_observations_required')
    indexed = {r.get('id'): r for r in observations}
    wanted = {r['id']: r for r in rows if r['location'] in VIDEO_LOCATIONS}
    if len(indexed) != len(observations) or set(indexed) != set(wanted):
        raise ValueError('cta_actual_placement_coverage_mismatch')
    duration = manifest['timeline']['duration_seconds']
    for ident, planned in wanted.items():
        observed = indexed[ident]
        if observed.get('location') != planned['location'] or observed.get('text') != planned['text']:
            raise ValueError('cta_observed_text_or_location_mismatch: ' + ident)
        actual, expected = times(observed, True), times(planned, True)
        if max(actual[1], expected[1]) > duration or any(abs(a-b) > .25 for a,b in zip(actual, expected)):
            raise ValueError('cta_actual_timing_mismatch: ' + ident)
        evidence = bound(observed.get('evidence_ref'))
        if evidence.stat().st_size == 0:
            raise ValueError('cta_empty_landing_evidence')
        text(observed.get('evidence_note'), 'what was heard/seen in final media')
    return dict(complete=True, video_placements=len(wanted),
                scope='hash_bound_final_observations_and_local_copy; not_automated_semantic_or_online_verification')
