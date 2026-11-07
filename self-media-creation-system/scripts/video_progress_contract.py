"""Progress selection/reservation/delivery adapter over the existing MVP component.

No rendering or human approval is performed by this module. Every delivery path
rechecks current references instead of trusting a checklist or a passed label.
"""
from __future__ import annotations
import hashlib
import copy
import json
import sys
from pathlib import Path
import cover_workbench as covers

ROOT=Path(__file__).resolve().parents[1]
SCHEMA='self-media.video-progress-contract.v1'
HUMAN_CHECKS=('progress_start_end_correct','progress_chapter_boundaries_correct',
              'progress_mobile_readable','progress_unobscured')


def component():
    source=ROOT.parent/'ai-video-tools-20260708/mvp-video-pipeline/src'
    if not (source/'video_creation_pipeline/progress_overlay.py').is_file():
        raise ValueError('mvp_progress_component_unavailable')
    if str(source) not in sys.path:sys.path.insert(0,str(source))
    from video_creation_pipeline import progress_overlay
    return progress_overlay


def basis(manifest):
    covers.bound(manifest['edited_media'])
    encoded=json.dumps(manifest['timeline'],sort_keys=True,ensure_ascii=False,allow_nan=False).encode()
    value={'edited_sha256':manifest['edited_media']['sha256'],
           'timeline_sha256':hashlib.sha256(encoded).hexdigest()}
    if manifest.get('script_ref'):
        covers.bound(manifest['script_ref']);value['script_sha256']=manifest['script_ref']['sha256']
    return value


def program_source(manifest,config):
    """The overlay may follow subtitle/audio renders, but never another project."""
    target=config.get('program_ref') or manifest['edited_media']
    covers.bound(target)
    if _same(target,manifest['edited_media']):return target
    previous=manifest['edited_media']
    from video_creation_pipeline.execution_receipts import validate_ffmpeg_execution_receipt
    for ref in manifest.get('render_chain_refs',[]):
        step=covers.read(covers.bound(ref));validate_ffmpeg_execution_receipt(step)
        if step.get('status')!='completed' or not any(_same(row['artifact'],previous) for row in step.get('inputs',[])):
            raise ValueError('progress_program_lineage_invalid')
        candidates=[row['artifact'] for row in step.get('outputs',[]) if row.get('role')=='candidate']
        if len(candidates)!=1:raise ValueError('progress_program_lineage_candidate_required')
        previous=candidates[0];covers.bound(previous)
        if _same(previous,target):return target
    raise ValueError('progress_program_lineage_required')


def _plan(manifest,config):
    refs={key:covers.bound(config[key]) for key in ('packaging_ref','layout_ref','spec_ref')}
    # Layout paths are relative to this explicitly declared, fixed local root.
    root=Path(config['workspace_root'])
    if not root.is_absolute() or not root.is_dir():raise ValueError('progress_workspace_required')
    script=config.get('script_ref') or manifest.get('script_ref')
    if script:covers.bound(script)
    if config.get('script_ref') and manifest.get('script_ref') and not _same(config['script_ref'],manifest['script_ref']):
        raise ValueError('progress_script_binding_conflict')
    plan=component().build(covers.bound(program_source(manifest,config)),refs['packaging_ref'],
        refs['layout_ref'],refs['spec_ref'],root,script_ref=script)
    if abs(plan['output']['duration_s']-manifest['timeline']['duration_seconds'])>.05:
        raise ValueError('progress_timeline_duration_mismatch')
    return plan


def select(manifest,decision,reason,*,packaging_ref=None,layout_ref=None,spec_ref=None,workspace_root=None,program_ref=None,script_ref=None):
    if decision not in ('use','not_used'):raise ValueError('progress_decision_required')
    if not isinstance(reason,str) or not reason.strip():raise ValueError('progress_reason_required')
    value={'schema':SCHEMA,'decision':decision,'reason':reason.strip(),'basis':basis(manifest),
           'result_ref':None}
    if decision=='use':
        if any(v is None for v in (packaging_ref,layout_ref,spec_ref,workspace_root)):
            raise ValueError('progress_reservation_inputs_required')
        value.update(packaging_ref=packaging_ref,layout_ref=layout_ref,spec_ref=spec_ref,
                     workspace_root=str(Path(workspace_root).resolve()),program_ref=program_ref or manifest['edited_media'],
                     script_ref=script_ref or manifest.get('script_ref'))
        plan=_plan(manifest,value)
        value['reservation']=copy.deepcopy({'rect':plan['geometry']['rect'],'clock':plan['output'],
                              'layout_check':plan['layout_check']})
    return value


def _same(left,right):
    return left['sha256']==right['sha256'] and Path(left['path']).resolve()==Path(right['path']).resolve()


def _receipt(ref,operation,source,output):
    path=covers.bound(ref);data=covers.read(path)
    from video_creation_pipeline.execution_receipts import validate_ffmpeg_execution_receipt
    validate_ffmpeg_execution_receipt(data)
    if data.get('status')!='completed' or data.get('operation')!=operation:
        raise ValueError('progress_completed_receipt_required')
    if not any(_same(row['artifact'],source) for row in data.get('inputs',[])):
        raise ValueError('progress_receipt_input_mismatch')
    if not any(_same(row['artifact'],output) for row in data.get('outputs',[])):
        raise ValueError('progress_receipt_output_mismatch')
    return data


def check(manifest,phase,final_media=None):
    if phase not in ('preflight','delivery'):raise ValueError('invalid_progress_phase')
    config=manifest.get('progress_overlay')
    if not isinstance(config,dict) or config.get('decision') not in ('use','not_used'):
        raise ValueError('progress_decision_required: explicitly choose use or not_used')
    if config.get('schema')!=SCHEMA or not isinstance(config.get('reason'),str) or not config['reason'].strip():
        raise ValueError('progress_reason_or_schema_required')
    if config.get('basis')!=basis(manifest):raise ValueError('progress_decision_stale: select against the current edit and timeline')
    if config['decision']=='not_used':
        if config.get('result_ref') or config.get('reservation'):
            raise ValueError('progress_not_used_conflicts_with_render_or_reservation')
        return {'status':'not_used_explicitly','reason':config['reason']}
    if not config.get('reservation'):raise ValueError('progress_reservation_required')
    expected=_plan(manifest,config)
    reservation={'rect':expected['geometry']['rect'],'clock':expected['output'],
                 'layout_check':expected['layout_check']}
    if config['reservation']!=reservation:raise ValueError('progress_reservation_stale')
    if phase=='preflight':return {'status':'selection_and_reservation_checked','reservation':reservation}
    if not config.get('result_ref'):raise ValueError('progress_render_result_required: a plan is not a rendered overlay')
    result_path=covers.bound(config['result_ref']);result=covers.read(result_path)
    if result.get('schema')!=component().SCHEMA+'.result' or result.get('technical_status')!='passed':
        raise ValueError('progress_actual_render_result_required')
    plan=component().validate(covers.bound(result['plan']))
    if plan!=expected:raise ValueError('progress_render_plan_stale')
    candidate=result['candidate'];covers.bound(candidate)
    if final_media is None or not _same(candidate,final_media):
        raise ValueError('progress_not_in_final_candidate')
    if not all(result.get(key) for key in ('render_receipt','decode_receipt','decoded_media','final_layout','layout_receipt')):
        raise ValueError('progress_render_evidence_required')
    rendered=_receipt(result['render_receipt'],'render',program_source(manifest,config),candidate)
    if not any(row.get('role')=='progress_plan' and _same(row['artifact'],result['plan']) for row in rendered['inputs']):
        raise ValueError('progress_render_plan_not_in_receipt')
    graph_ref=next((row['artifact'] for row in rendered['inputs'] if row.get('role')=='filtergraph'),None)
    if not graph_ref:raise ValueError('progress_filtergraph_evidence_required')
    graph_path=covers.bound(graph_ref)
    command=rendered.get('executed_command') or rendered['command']
    if '-filter_complex_script' not in command or Path(command[command.index('-filter_complex_script')+1]).resolve()!=graph_path.resolve():
        raise ValueError('progress_filtergraph_not_executed')
    if graph_path.read_text(encoding='utf-8')!=component().filtergraph(plan,graph_path.parent,write_texts=False):
        raise ValueError('progress_filtergraph_drift')
    for i,chapter in enumerate(plan['chapters']):
        text_path=graph_path.parent/f'chapter-{i:02d}.txt'
        if text_path.read_text(encoding='utf-8')!=chapter['text']:
            raise ValueError('progress_chapter_text_drift')
    _receipt(result['decode_receipt'],'technical_qa',candidate,result['decoded_media'])
    decoded=covers.bound(result['decoded_media'])
    frames=sum(bool(line.strip()) and not line.startswith('#') for line in decoded.read_text().splitlines())
    if frames!=plan['output']['frames'] or frames!=result.get('decoded_frames'):
        raise ValueError('progress_decoded_frame_count_mismatch')
    layout=covers.read(covers.bound(result['final_layout']))
    from video_creation_pipeline.final_layout_safety import validate_final_layout
    checked=validate_final_layout(layout,Path(plan['workspace_root']))
    reported=covers.read(covers.bound(result['layout_receipt']))
    if checked!=reported or checked['candidate_sha256']!=candidate['sha256']:
        raise ValueError('progress_final_layout_evidence_mismatch')
    return {'status':'render_and_layout_verified','candidate':candidate,'decoded_frames':frames,
            'human_review':'checked separately by the current delivery acceptance'}
