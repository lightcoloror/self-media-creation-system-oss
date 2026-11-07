"""Purpose/feedback bindings inside existing context manifests, not a goal store.

This checks references and editorial records, never audience effects or semantic
truth. Existing Briefs remain the source; no model, database writes or media IO.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import copy
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
GUIDE = 'docs/purpose-continuity.md'
REVIEW_SCHEMA = 'self-media-stage-purpose-review.v1'
ALIGNMENT = {'stage_duty', 'contribution', 'misunderstanding_risk', 'tradeoff'}
CHECK_IDS = {f'C{i:02}' for i in range(1, 10)}


class PurposeError(ValueError):
    def __init__(self, code, message):
        self.code = 'purpose_' + code
        super().__init__(message)


def fail(code, message):
    raise PurposeError(code, message)


def text(value, label):
    if not isinstance(value, str) or not value.strip() or value.strip().lower() in {'pass', 'passed', 'ok', '通过', '已检查'}:
        fail('explanation_missing', label)
    return value


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load(path):
    path = Path(path).resolve()
    if not path.is_file() or path.stat().st_size > 2_000_000:
        fail('metadata_unreadable', str(path))
    return json.loads(path.read_text(encoding='utf-8-sig'))


def bound_path(base, ref):
    if set(ref) != {'path', 'sha256'} or Path(ref['path']).is_absolute():
        fail('reference_invalid', 'Use a relative path and exact sha256')
    path = (Path(base) / ref['path']).resolve()
    if not path.is_relative_to(Path(base).resolve()) or not path.is_file() or path.stat().st_size > 2_000_000:
        fail('reference_invalid', ref['path'])
    if digest(path) != ref['sha256']:
        fail('source_drift', ref['path'])
    return path


def requires_context(step):
    # Routing discovery does not yet express or review the piece itself.
    return step['step_id'] != 'verify-canonical-route'


def validate_context(path, request_id=None, required=True, historical=False):
    path = Path(path).resolve()
    manifest = load(path)
    schema = load(ROOT / 'schemas/context-input-manifest.v1.schema.json')
    errors = list(Draft202012Validator(schema).iter_errors(manifest))
    if errors:
        fail('manifest_invalid', errors[0].message)
    if request_id is not None and manifest['task_id'] != request_id:
        fail('task_mismatch', 'Purpose context belongs to another task')
    context = manifest.get('editorial_context')
    if context is None:
        if required:
            fail('context_missing', 'Supply editorial_context in the existing context manifest')
        return None
    artifacts = {a['artifact_id']: a for a in manifest['artifacts']}
    if len(artifacts) != len(manifest['artifacts']):
        fail('duplicate_artifact', 'Context artifact IDs must be unique')

    def anchor(ref):
        item = artifacts.get(ref['artifact_id'])
        if item is None or item['load_mode'] == 'on_failure' or not item.get('expected_sha256'):
            fail('source_required', ref['artifact_id'])
        target = bound_path(path.parent, dict(path=item['path'], sha256=item['expected_sha256']))
        quote = text(ref['quote'], 'source quote')
        if quote not in target.read_text(encoding='utf-8-sig'):
            fail('anchor_missing', ref['artifact_id'])
        return dict(path=str(target), sha256=item['expected_sha256'], quote=quote)

    purpose = anchor(context['purpose'])
    audience = anchor(context['audience'])
    topic = context.get('topic_selection')
    if topic is not None:
        topic = dict(topic, origin_source=anchor(topic['origin_source']),
                     adoption_source=anchor(topic['adoption_source']))
        text(topic['topic'], 'topic')
        text(topic['adoption_basis'], 'topic adoption basis')
        if 'decision_artifact_id' in topic:
            item = artifacts.get(topic['decision_artifact_id'])
            if not item or item['load_mode']=='on_failure' or not item.get('expected_sha256'):
                fail('topic_decision_missing', 'Bind the actual framework decision in this manifest')
            decision_path = bound_path(path.parent, dict(path=item['path'],sha256=item['expected_sha256']))
            topic['framework_decision_ref'] = dict(path=str(decision_path),sha256=item['expected_sha256'])
    duty = text(context['stage_duty'], 'stage duty')
    text(context['feedback_note'], 'what feedback is known / not supplied')
    feedback = []
    seen = set()
    for row in context['feedback']:
        if row['artifact_id'] in seen:
            fail('duplicate_feedback', row['artifact_id'])
        seen.add(row['artifact_id'])
        feedback.append(dict(artifact_id=row['artifact_id'], source=anchor(row), check_ids=row['check_ids']))
    assertions, assertion_ids = [], set()
    for row in context.get('consumer_assertions', []):
        if row['id'] in assertion_ids:
            fail('duplicate_consumer_assertion', row['id'])
        assertion_ids.add(row['id'])
        text(row['reason'], 'consumer requirement reason')
        # Reuse JSON Schema, not a new rule language. No remote reference loading.
        def local_only(value):
            if isinstance(value, dict):
                for key, child in value.items():
                    if key in ('$ref', '$dynamicRef') and (not isinstance(child, str) or not child.startswith('#')):
                        fail('external_assertion_reference', row['id'])
                    local_only(child)
            elif isinstance(value, list):
                for child in value:
                    local_only(child)
        local_only(row['schema'])
        try:
            Draft202012Validator.check_schema(row['schema'])
        except Exception as error:
            fail('consumer_schema_invalid', row['id'] + ': ' + str(error))
        assertions.append(dict(**{k: row[k] for k in ('id','consumer','decision','reason','schema')},
                               source=anchor(row['source'])))
    declared_feedback = {a['artifact_id'] for a in manifest['artifacts']
                         if a.get('source_role','').startswith('editorial-feedback') or a['role']=='user_correction'}
    if not declared_feedback <= seen:
        fail('feedback_pending', 'A declared feedback artifact was omitted from editorial_context')
    body = None
    if context['current_body_artifact_id'] is not None:
        item = artifacts.get(context['current_body_artifact_id'])
        if item is None or item['load_mode'] == 'on_failure' or not item.get('expected_sha256'):
            fail('body_missing', 'Bind the current body; do not invent an unreached draft')
        target = bound_path(path.parent, dict(path=item['path'], sha256=item['expected_sha256']))
        body = dict(path=str(target), sha256=item['expected_sha256'])

    # When the existing author ledger is supplied, undisclosed registered feedback
    # must not be hidden behind an empty standalone snapshot.
    author_rows = [a for a in manifest['artifacts'] if a.get('source_role') == 'author-writing-context']
    author_store = None
    if author_rows:
        if len(author_rows) != 1:
            fail('author_context_ambiguous', 'One existing author context only')
        a = author_rows[0]
        target = bound_path(path.parent, dict(path=a['path'], sha256=a.get('expected_sha256')))
        import author_writing_context as author
        import editorial_integrity as editorial
        existing = author.validate_context(target)
        author_store = str(author.store_api.store_path(existing['store_path']))
        if existing['author_brief']['content_id'] != context['content_id']:
            fail('content_mismatch', 'Author ledger and purpose refer to different content')
        records = [] if historical else editorial.history(existing)
        preparation = editorial.latest(records, 'editorial_preflight')
        if preparation is not None:
            goal = next(r for r in preparation['payload']['assessment']['items'] if r['id']=='goal_audience')
            evidence_keys = {(str(author.checked_ref({k:ev[k] for k in ('path','sha256')})), ev['sha256'], ev['quote'])
                             for ev in goal['evidence']}
            if (purpose['path'], purpose['sha256'], purpose['quote']) not in evidence_keys:
                fail('preflight_goal_mismatch', 'Manifest purpose must use the same evidence anchor as current C01 preparation')
        supplied = {(r['source']['path'], r['source']['sha256'], r['source']['quote']) for r in feedback}
        for row in records:
            if row['record_type'] == 'editorial_feedback':
                ev = row['payload']['source']
                key = (str(author.checked_ref({k:ev[k] for k in ('path','sha256')})), ev['sha256'], ev['quote'])
                if key not in supplied:
                    fail('feedback_pending', 'Carry all registered author/editorial feedback into the current manifest')
                matching = [r for r in feedback if (r['source']['path'],r['source']['sha256'],r['source']['quote']) == key]
                if not set(row['payload']['check_ids']) <= set().union(*(set(r['check_ids']) for r in matching)):
                    fail('feedback_scope_drift', 'Do not narrow the recorded feedback impact to unrelated checks')
    return dict(context_manifest=dict(path=str(path), sha256=digest(path)), content_id=context['content_id'],
                topic_selection=topic,
                task_id=manifest['task_id'], stage=manifest['stage'], purpose_source=purpose,
                audience_source=audience, stage_duty=duty, current_body=body, feedback=feedback,
                consumer_assertions=assertions,
                feedback_note=context['feedback_note'], automatic_semantic_verification=False,
                author_store_path=author_store,
                feedback_coverage='existing_author_ledger' if author_rows else 'explicit_supplied_snapshot_only',
                route_policy='stage responsibilities do not select a route, structure, line count or call to action')


def check_consumer(reference, consumer, actual):
    """Validate sourced requirements on actual output of an existing consumer.

    This is structural evidence, not visual, semantic or human approval. A null
    legacy reference stays explicitly unknown; it never manufactures a pass.
    """
    if reference is None:
        return dict(status='context_not_bound', checks=[], automatic_semantic_verification=False)
    if not isinstance(reference, dict) or set(reference) != {'path','sha256'}:
        fail('consumer_context_reference_invalid', consumer)
    path = Path(reference['path'])
    if not path.is_absolute() or not path.is_file() or digest(path) != reference['sha256']:
        fail('consumer_context_drift', str(path))
    context = validate_context(path)
    checks = []
    for row in context['consumer_assertions']:
        if row['consumer'] != consumer:
            continue
        status = 'not_applicable'
        if row['decision'] == 'use':
            errors = list(Draft202012Validator(row['schema']).iter_errors(actual))
            if errors:
                first = errors[0]
                fail('consumer_requirement_failed', row['id'] + ' at ' + '/'.join(map(str,first.path)) + ': ' + first.message)
            status = 'passed_structural'
        checks.append(dict(id=row['id'], status=status, source=row['source'], reason=row['reason']))
    report=dict(status='checked_structural', context_ref=reference, content_id=context['content_id'],
                checks=checks, automatic_semantic_verification=False,
                human_approval=False, publication_authorized=False)
    if consumer=='publication_desk':
        report['input_snapshot']={k:copy.deepcopy(v) for k,v in actual.items() if k not in ('revision','modified_at','ui_state')}
    return report


def check_transition(previous, current):
    if previous is None or current is None:
        return
    if previous['content_id'] != current['content_id']:
        fail('content_mismatch', 'Do not switch content identity within the same sequence')
    if previous.get('feedback_coverage') == 'existing_author_ledger':
        if current.get('feedback_coverage') != 'existing_author_ledger' or previous.get('author_store_path') != current.get('author_store_path'):
            fail('feedback_ledger_lost', 'Keep the known author ledger; a standalone snapshot cannot replace its fresh feedback')
    def identity(row):
        return (row['source']['path'], row['source']['sha256'], row['source']['quote'])
    def scopes(rows):
        result = {}
        for row in rows:
            result.setdefault(identity(row), set()).update(row['check_ids'])
        return result
    old, new = scopes(previous['feedback']), scopes(current['feedback'])
    if any(key not in new or not checks <= new[key] for key, checks in old.items()):
        fail('feedback_lost', 'Carry previous feedback forward; do not discard earlier corrections')
    old_assertions = {row['id']: row for row in previous.get('consumer_assertions', [])}
    new_assertions = {row['id']: row for row in current.get('consumer_assertions', [])}
    if any(key not in new_assertions for key in old_assertions):
        fail('consumer_requirement_lost', 'Do not omit an existing sourced requirement in the next stage')
    for key, row in old_assertions.items():
        changed = new_assertions[key]
        if row != changed and row['source'] == changed['source']:
            fail('consumer_requirement_changed_without_source', key)
    if (previous['purpose_source'],previous['audience_source']) != (current['purpose_source'],current['audience_source']):
        if not any(identity(r) not in old and 'C01' in r['check_ids'] for r in current['feedback']):
            fail('goal_change_unexplained', 'Changed purpose/audience requires a sourced C01 decision; do not silently rewrite it')


def validate_review(context_path, review_path, output_paths=None, historical=False):
    context = validate_context(context_path, historical=historical)
    review_path = Path(review_path).resolve()
    review = load(review_path)
    required = {'schema_version', 'context_ref', 'artifact_ref', 'quote', 'purpose_alignment', 'feedback_resolutions', 'disposition', 'reason'}
    if set(review) != required or review['schema_version'] != REVIEW_SCHEMA:
        fail('review_invalid', 'Expected a stage purpose review with explicit evidence and disposition')
    bound_context = bound_path(review_path.parent, review['context_ref'])
    if bound_context != Path(context_path).resolve():
        fail('context_mismatch', 'Review does not consume the supplied current context')
    artifact = bound_path(review_path.parent, review['artifact_ref'])
    if artifact == review_path or artifact == bound_context:
        fail('output_mismatch', 'Review must anchor a separate actual stage output')
    if output_paths is not None and artifact not in {Path(p).resolve() for p in output_paths}:
        fail('output_mismatch', 'Review must anchor an actual output from this step')
    if text(review['quote'], 'actual output anchor') not in artifact.read_text(encoding='utf-8-sig'):
        fail('output_anchor_missing', 'Review quote is absent from the actual output')
    alignment = review['purpose_alignment']
    if not isinstance(alignment, dict) or set(alignment) != ALIGNMENT:
        fail('alignment_missing', 'State duty, contribution, misunderstanding risk and tradeoff')
    for key, value in alignment.items():
        text(value, key)
    if alignment['stage_duty'] != context['stage_duty']:
        fail('duty_drift', 'The review changed the handed-off stage responsibility')
    resolutions = review['feedback_resolutions']
    if not isinstance(resolutions, list) or any(not isinstance(r, dict) or set(r) != {'artifact_id', 'resolution'} for r in resolutions):
        fail('feedback_resolution_missing', 'Use artifact_id and concrete resolution for each supplied feedback item')
    ids = [r['artifact_id'] for r in resolutions]
    if len(ids) != len(set(ids)) or set(ids) != {r['artifact_id'] for r in context['feedback']}:
        fail('feedback_pending', 'Review must account for the complete current feedback snapshot')
    for r in resolutions:
        text(r['resolution'], 'feedback resolution')
    if review['disposition'] not in {'retained', 'revised_verified', 'needs_revision', 'needs_input'}:
        fail('disposition_invalid', 'Use a truthful editorial disposition')
    # A binding report cannot establish that an edit took place. Actual edit
    # closure stays with the existing versioned C01-C09 issue mechanism.
    if review['disposition'] == 'revised_verified':
        fail('edit_evidence_required', 'Use existing editorial issue closure to prove edits; this bridge only records retention or needed work')
    text(review['reason'], 'editorial decision')
    return dict(status='record_complete', context=context, artifact_ref=dict(path=str(artifact),sha256=digest(artifact)),
                disposition=review['disposition'], purpose_record_complete=True,
                may_continue=review['disposition']=='retained', editorial_quality_verified=False,
                author_selection_verified=False, audience_effect_verified=False,
                publication_authorized=False, media_export_authorized=False)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['check-stage'])
    parser.add_argument('--context', type=Path, required=True)
    parser.add_argument('--review', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    try:
        result = validate_review(args.context, args.review) if args.review else dict(status='context_bound', context=validate_context(args.context), purpose_record_complete=False, may_continue=False)
        if args.output:
            args.output.parent.mkdir(parents=True,exist_ok=True)
            with args.output.open('x',encoding='utf-8') as f:
                json.dump(result,f,ensure_ascii=False,indent=2)
        print(json.dumps(result,ensure_ascii=False))
        return 0 if (not args.review or result['may_continue']) else 2
    except (PurposeError, OSError, ValueError, KeyError, TypeError) as e:
        print(json.dumps(dict(status='blocked',error_code=getattr(e,'code','purpose_invalid'),error=str(e)),ensure_ascii=False))
        return 2
