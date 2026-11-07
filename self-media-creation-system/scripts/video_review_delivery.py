"""Deliver editing-recipe/material reviews through VKP source-time ranges only."""
from __future__ import annotations

import argparse
import importlib
import json
import hashlib
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PURPOSES = ("rough_cut_recipe", "fine_cut_recipe", "material_requirement")
POLICY = {
    "policy_id": "source-time-range-review-v1",
    "surface": "targeted-review.html",
    "review_access_mode": "source_time_range",
    "media_export_allowed": False,
    "production_requires_separate_explicit_user_request": True,
}
ROOT_FIELDS = {"schema_version", "scope", "requests", "presentation_requirements"}
ROW_FIELDS = {
    "review_id", "source_path", "artifact_sha256", "workflow_stage", "review_lane",
    "playback_mode", "review_start_seconds", "review_end_seconds", "issue_start_seconds",
    "issue_end_seconds", "review_purpose", "review_question", "reference_text", "status",
    "decision_labels", "review_access_mode", "full_source_review", "subtitle_cues",
    "audio_time_position",
    "expected_dialogue", "no_dialogue_reason",
}


def presentation_check(request: dict, purpose: str) -> dict:
    """Validate the actual cues that the canonical player receives, not a style promise."""
    requirements = request.get('presentation_requirements')
    if requirements is None:
        if purpose == 'fine_cut_recipe':
            raise ValueError('fine_cut_presentation_requirements_required')
        return dict(applicable=False, human_approved=False)
    if not isinstance(requirements, dict) or set(requirements) != {'required_layers', 'animated_speakers', 'style_reason'}:
        raise ValueError('presentation_requirements_invalid')
    layers, animated = requirements['required_layers'], requirements['animated_speakers']
    if (not isinstance(layers, list) or not set(layers) <= {'dialogue','age','context'}
            or not isinstance(animated, list) or not set(animated) <= {'child','father','neutral'}
            or not isinstance(requirements['style_reason'],str) or not requirements['style_reason'].strip()):
        raise ValueError('presentation_requirements_invalid')
    policy_path = ROOT / 'schemas/typography-gates.v1.policy.json'
    raw = policy_path.read_bytes()
    roles = json.loads(raw)['profiles']['semantic_motion_1080x1920']['roles']
    minimums = {k: roles[v]['min_font_px'] for k,v in {'dialogue':'subtitle','context':'body','age':'label'}.items()}
    speaker_sizes, observed_speakers, checked = {}, set(), 0
    for row in request['requests']:
        cues = row.get('subtitle_cues', [])
        if not isinstance(cues, list) or any(not isinstance(c,dict) for c in cues) or not set(layers) <= {c.get('layer','dialogue') for c in cues}:
            raise ValueError('required_text_layer_missing: '+row['review_id'])
        for cue in cues:
            a,b=cue.get('start_seconds'),cue.get('end_seconds')
            if (not isinstance(cue.get('text'),str) or not cue['text'].strip()
                    or any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in (a,b))
                    or not row['review_start_seconds'] <= a < b <= row['review_end_seconds']):
                raise ValueError('preview_cue_text_or_time_invalid: '+row['review_id'])
        expected = row.get('expected_dialogue')
        if not isinstance(expected, list) or (not expected and not str(row.get('no_dialogue_reason','')).strip()):
            raise ValueError('dialogue_inventory_or_explicit_none_required: '+row['review_id'])
        for spoken in expected:
            if not isinstance(spoken, dict) or not all(k in spoken for k in ('text','speaker','start_seconds','end_seconds')):
                raise ValueError('expected_dialogue_invalid')
            if not isinstance(spoken['text'],str) or not spoken['text'].strip() or spoken['speaker'] not in ('child','father','neutral'):
                raise ValueError('expected_dialogue_invalid')
            a, b = spoken['start_seconds'], spoken['end_seconds']
            if (any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in (a,b))
                    or not row['review_start_seconds'] <= a < b <= row['review_end_seconds']):
                raise ValueError('expected_dialogue_time_invalid')
            if spoken.get('omission_reason','').strip():
                continue
            if not any(c.get('layer','dialogue') == 'dialogue' and c.get('text') == spoken['text']
                       and c.get('speaker') == spoken['speaker']
                       and abs(c['start_seconds']-a) <= .02 and abs(c['end_seconds']-b) <= .02 for c in cues):
                raise ValueError('expected_dialogue_not_in_preview: '+spoken['text'])
        for cue in cues:
            layer, speaker = cue.get('layer','dialogue'), cue.get('speaker','neutral')
            if layer not in minimums or speaker not in {'child','father','neutral'}:
                raise ValueError('cue_layer_or_speaker_invalid')
            size = cue.get('font_size_1080', 48 if layer=='age' else 96 if speaker=='child' else 76)
            if isinstance(size,bool) or not isinstance(size,(float,int)) or not math.isfinite(size) or size < minimums[layer]:
                raise ValueError('text_below_existing_typography_minimum: '+row['review_id'])
            emphasis = str(cue.get('emphasis_reason','')).strip()
            if layer == 'dialogue':
                observed_speakers.add(speaker)
                if speaker in animated and cue.get('motion','none') == 'none':
                    raise ValueError('requested_motion_missing: '+row['review_id'])
                if speaker in speaker_sizes and speaker_sizes[speaker] != size and not emphasis:
                    raise ValueError('speaker_style_changed_without_emphasis_reason: '+speaker)
                if not emphasis:
                    speaker_sizes.setdefault(speaker,size)
            checked += 1
    if not set(animated) <= observed_speakers:
        raise ValueError('requested_animated_speaker_missing')
    return dict(applicable=True, checked_cues=checked, typography_policy_sha256=hashlib.sha256(raw).hexdigest(),
                required_layers=layers, animated_speakers=animated, human_approved=False,
                actual_playback_and_export_verification_required=True)


def validate_request(request: dict, purpose: str) -> None:
    if purpose not in PURPOSES:
        raise ValueError("review_purpose_unsupported")
    if not isinstance(request, dict) or request.get("schema_version") != "self-media-human-review-request-pack.v1":
        raise ValueError("source_time_range_request_required")
    if set(request) - ROOT_FIELDS:
        raise ValueError("review_export_or_unknown_root_fields_prohibited")
    rows = request.get("requests")
    if not isinstance(rows, list) or not rows:
        raise ValueError("review_requests_required")
    for row in rows:
        if not isinstance(row, dict) or set(row) - ROW_FIELDS:
            raise ValueError("review_export_or_unknown_item_fields_prohibited")
        if row.get("review_access_mode", "source_time_range") != "source_time_range":
            raise ValueError("review_media_export_prohibited_use_source_time_range")
        if row.get("status", "pending") != "pending":
            raise ValueError("review_initial_human_decision_must_be_pending")
    # VKP validates source hash, source existence, finite bounds and UI schema.
    # There is deliberately no --force/--export/authorization boolean here.


def prepare(request_path: Path, output_dir: Path, purpose: str, *, preparer=None, context_manifest=None) -> dict:
    request_path = request_path.resolve()
    request = json.loads(request_path.read_text(encoding="utf-8-sig"))
    validate_request(request, purpose)
    presentation = presentation_check(request, purpose)
    context_ref = None
    if context_manifest is not None:
        import purpose_continuity
        context_ref = dict(path=str(Path(context_manifest).resolve()),sha256=purpose_continuity.digest(context_manifest))
        purpose_continuity.check_consumer(context_ref, 'video_review', request)
    canonical = preparer is None
    if preparer is None:
        vkp_src = ROOT.parent / "video-knowledge-pipeline" / "src"
        if not (vkp_src / "video_knowledge_pipeline" / "targeted_review.py").is_file():
            raise ValueError("canonical_vkp_targeted_review_unavailable_no_export_fallback")
        sys.path.insert(0, str(vkp_src))
        preparer = importlib.import_module("video_knowledge_pipeline.targeted_review").prepare_targeted_review_pack
    receipt = preparer(request_path, output_dir)
    if receipt.get("status") != "prepared" or receipt.get("media_copies_created") != 0:
        raise ValueError("review_delivery_not_zero_copy")
    requirement_report = None
    if context_ref is not None:
        # Check the generated pack, not merely the request/plan before conversion.
        import purpose_continuity
        pack = json.loads((output_dir/'targeted-review-pack.json').read_text(encoding='utf-8-sig'))
        requirement_report = purpose_continuity.check_consumer(context_ref, 'video_review', pack)
        (output_dir/'requirement-check.json').write_text(json.dumps(requirement_report,ensure_ascii=False,indent=2),encoding='utf8')
    if canonical and presentation['applicable']:
        pack = json.loads((output_dir/'targeted-review-pack.json').read_text(encoding='utf-8-sig'))
        by_id = {row['review_id']:row for row in pack['requests']}
        for row in request['requests']:
            actual = by_id[row['review_id']].get('subtitle_cues',[])
            expected = row.get('subtitle_cues',[])
            def same(a, e):
                return all(math.isclose(a.get(k, -1), v, rel_tol=0, abs_tol=.000501)
                           if k in ('start_seconds','end_seconds') else a.get(k)==v for k,v in e.items())
            if len(actual)!=len(expected) or not all(same(a,e) for a,e in zip(actual,expected)):
                raise ValueError('review_renderer_dropped_cue_properties')
        (output_dir/'presentation-check.json').write_text(json.dumps(dict(presentation,
            source_request_sha256=pack['source_request_sha256'],pack_payload_sha256=pack['pack_payload_sha256']),
            ensure_ascii=False,indent=2),encoding='utf-8')
    return {**receipt, "review_purpose": purpose, "delivery_policy": dict(POLICY),
            "presentation_check": presentation, "requirement_report": requirement_report,
            "media_export_authorized": False, "human_review_completed": False}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("policy")
    p = sub.add_parser("prepare")
    p.add_argument("--request", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--purpose", choices=PURPOSES, required=True)
    p.add_argument("--context-manifest", type=Path)
    args = parser.parse_args(argv)
    try:
        result = dict(POLICY) if args.action == "policy" else prepare(args.request, args.output_dir, args.purpose, context_manifest=args.context_manifest)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({"status": "blocked", "code":getattr(exc,'code',type(exc).__name__), "error": str(exc), "media_export_authorized": False}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
