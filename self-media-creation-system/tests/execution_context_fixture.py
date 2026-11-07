"""Adapt the existing entry-selection purpose fixture; synthetic content only."""
import copy
import hashlib
import json
from pathlib import Path


def reference(path):
    return dict(path=str(Path(path).resolve()),sha256=hashlib.sha256(Path(path).read_bytes()).hexdigest())


def make_context(root, assertions=(), name='synthetic-execution-context'):
    root=Path(root)
    source=root/(name+'-source.json')
    source.write_text(json.dumps(dict(purpose='Synthetic purpose: preserve the approved meaning.',
        audience='Synthetic first-time viewers.', requirement='Synthetic sourced requirement; no real author approval.'),ensure_ascii=False),encoding='utf8')
    rows=[]
    for assertion in assertions:
        row=copy.deepcopy(assertion)
        row.setdefault('source',dict(artifact_id='context-source',quote='Synthetic sourced requirement; no real author approval.'))
        row.setdefault('decision','use')
        row.setdefault('reason','Synthetic regression of a previously lost requirement.')
        rows.append(row)
    data=dict(schema_version='self-media-context-input.v1',task_id='synthetic-closure-01',stage='publication-review',
        budget=dict(max_inline_bytes=4096),artifacts=[dict(artifact_id='context-source',role='source_manifest',
            path=source.name,expected_sha256=reference(source)['sha256'],load_mode='reference')],
        editorial_context=dict(version=1,content_id=name,
            purpose=dict(artifact_id='context-source',quote='Synthetic purpose: preserve the approved meaning.'),
            audience=dict(artifact_id='context-source',quote='Synthetic first-time viewers.'),
            stage_duty='Keep sourced synthetic requirements at the real consumer.',current_body_artifact_id='context-source',
            feedback=[],feedback_note='No real author feedback in this fixture.',consumer_assertions=rows))
    path=root/(name+'.json')
    path.write_text(json.dumps(data,ensure_ascii=False),encoding='utf8')
    return reference(path)
