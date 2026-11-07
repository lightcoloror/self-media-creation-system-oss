"""Create wholly synthetic feedback inputs using the existing native record writer."""
from __future__ import annotations
import copy
import json
import uuid
from datetime import timedelta
from pathlib import Path

import outcome_feedback_link as link


def create_fixture():
    root = link.ROOT / 'tests/.runtime/content-operations' / ('outcome-fixture-' + uuid.uuid4().hex)
    root.mkdir(parents=True)
    fixture = link.ROOT / 'fixtures/content-operations-cycle-v1'
    pub = link.read(fixture / 'record-publication.input.json')
    assert pub['data_classification'] == 'synthetic-only'
    goal = link.read(link.ROOT / pub['source_objects']['goal_ref'])
    account = link.read(link.ROOT / pub['source_objects']['account_ref'])
    topic = link.read(link.ROOT / pub['source_objects']['topic_ref'])
    item = copy.deepcopy(link.read(link.ROOT / 'fixtures/operations-contract-regression.v1.synthetic.json')['content_item'])
    content_id = 'synthetic-outcome-echo-garden-001'
    run_id = 'synthetic-outcome-review-001'
    item.update(content_id=content_id, tags=['synthetic-only'])
    item['channels'] = {'article': {'status': 'draft', 'title': item['title'],
        'body': item['composition']['canonical_summary'],
        'platform_metadata': {'outcome_feedback_binding': {'closure_run_id': run_id}}}}
    item['operating_refs'] = {'account_ids': [account['account_id']], 'topic_ids': [topic['topic_id']],
                              'publication_ids': [], 'experiment_ids': []}
    topic.update(title='虚构回声花园观察卡', audience_problem='仅验证虚构对象关系，不对应真实客户。')
    pub.update(content_id=content_id, publication_key='synthetic-outcome-echo-garden-publication',
               title=item['title'])

    def write(name, value):
        path = root / name
        path.write_text(link.text(value), encoding='utf-8')
        return path

    for kind, value in [('goal', goal), ('account', account), ('topic', topic), ('content_item', item)]:
        filename = 'content-item.json' if kind == 'content_item' else kind + '.json'
        path = write(filename, value)
        pub['source_objects'][kind + '_ref'] = path.relative_to(link.ROOT).as_posix()
        pub['source_objects'][kind + '_sha256'] = link.sha(path)
    pub_path = write('native-publication.json', pub)
    store = root / 'store'
    link.cycle.record_from_input(store, 'record-publication', pub_path)
    records = link.cycle.read_journal(store)
    event = records[0]['payload']['event']
    candidate = root / 'content-item.json'
    binding = link.binding_for(candidate.relative_to(link.W).as_posix(), link.sha(candidate), account['account_id'])
    common = {key: binding[key] for key in ('content_id', 'closure_run_id', 'account_id')}
    edit = dict(started_at='2026-08-10T10:00:00+08:00', ended_at='2026-08-10T10:05:00+08:00',
                category='synthetic-layout', reason='Invented correction for a contract regression.')

    def reference(path):
        return {'ref': path.relative_to(link.W).as_posix(), 'sha256': link.sha(path)}

    edit['evidence'] = reference(write('edit-evidence.json', {**common, **edit}))
    outcome = {**common, 'decision': 'adopted_with_edits', 'decided_at': '2026-08-10T10:10:00+08:00',
               'edits': [edit], 'time_saved_minutes': None, 'rework_reason': 'synthetic-fixture-only'}
    outcome['evidence'] = reference(write('decision-evidence.json',
        {**common, 'decision': outcome['decision'], 'decided_at': outcome['decided_at']}))
    observations = []
    published = link.tracker.parse_time(event['occurred_at'], 'published')
    for label, hours in [('early', 60), ('d7', 168)]:
        at = (published + timedelta(hours=hours)).isoformat()
        observation = {'window_label': label, 'as_of': at, 'captured_at': at,
            'data_completeness': 'unavailable', 'layers': {key: 'not_observed' for key in link.tracker.LAYERS},
            'metrics': [], 'business_events': []}
        observations.append({**common, 'publication_id': event['publication_id'], 'observation': observation})
    native_review = link.read(fixture / 'build-review.input.json')
    native_review['account_ids'] = [account['account_id']]
    native_review['source_checkpoint'] = link.cycle.source_checkpoint(records)
    write('native-build-review.json', native_review)
    native_snapshot = link.read(fixture / 'record-snapshot-early.input.json')
    native_snapshot['publication_id'] = event['publication_id']
    write('native-snapshot-early.json', native_snapshot)
    request = {'schema_version': 'content-outcome-feedback-input.v1', 'data_classification': 'synthetic-only',
        'submitted_at': '2026-08-18T12:00:00+08:00', 'binding': binding, 'outcome': outcome,
        'publication': {'store_ref': store.relative_to(link.W).as_posix(), 'publication_id': event['publication_id']},
        'observations': observations, 'native_requests': []}
    path = write('request.json', request)
    result = link.build(request)
    assert result['status'] == 'pending_human_review'
    assert not any(result['authority'].values())
    return path
