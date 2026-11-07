"""Read-only linkage of candidates, manual outcomes and governed publication records.

Emits review candidates, never writes the operating store or the outcome ledger.
Synthetic tracker gates are unchanged. Codex / GPT-6 Astra, 2026-09-12.
"""
from __future__ import annotations
import argparse,copy,hashlib,json,sys,math
from datetime import timedelta
from pathlib import Path
import candidate_feedback_batch as batch
import publication_feedback_tracker as tracker
import content_operations_cycle as cycle

ROOT=Path(__file__).resolve().parents[1]; W=ROOT.parent
import outcome_contract as ledger

class LinkError(ValueError):
    def __init__(self,code):super().__init__(code);self.code=code
def require(ok,code):
    if not ok:raise LinkError(code)
def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def text(v):return json.dumps(v,ensure_ascii=False,sort_keys=True,indent=2)+'\n'
def resolve(ref):
    require(isinstance(ref,str) and not Path(ref).is_absolute() and '..' not in Path(ref).parts,'unsafe_ref')
    p=(W/ref).resolve();require(p.is_relative_to(W) and p!=W,'unsafe_ref');return p
def bound(row,code='evidence_hash_drift'):
    require(isinstance(row,dict) and set(row)=={'ref','sha256'},'time_evidence_required')
    p=resolve(row['ref']);require(p.is_file() and sha(p)==row['sha256'],code);return read(p)
def match_event(event,binding):
    require(all(event.get(k)==binding[k] for k in ('content_id','closure_run_id','account_id')),'event_binding_drift')

def binding_for(candidate_ref,candidate_sha256,account_id=None):
    row={'ref':candidate_ref,'sha256':candidate_sha256};c=bound(row,'candidate_hash_drift')
    tracker.validate_schema(c,tracker.CONTENT_SCHEMA,'candidate')
    meta=c['channels']['article'].get('platform_metadata',{})
    run=(meta.get('outcome_feedback_binding') or meta.get('qrp_candidate_binding') or {}).get('closure_run_id')
    require(bool(run),'closure_binding_missing')
    if account_id is not None:
        require(account_id in c.get('operating_refs',{}).get('account_ids',[]),'account_reference_drift')
    return {'candidate':row,'content_id':c['content_id'],'closure_run_id':run,'account_id':account_id}

def outcome_candidate(request,binding):
    out=ledger.adapt_call_record({'task_type':'content_candidate_review','tool_id':'content-outcome-feedback-link',
        'model':{'deployment':'local','provider':'not_applicable','name':'not_applicable'},
        'candidate_sha256':binding['candidate']['sha256']},binding['closure_run_id'],binding['content_id'])
    out['contract']['version']='content-outcome-feedback-overlay.v1'
    # This is a candidate descriptor, not evidence of a provider invocation.
    out.pop('promptfoo_observation',None)
    out['contract'].pop('call_record_hash',None)
    out['contract']['candidate_binding_sha256']=tracker.canonical_sha256(binding)
    out['contract']['receipt_ref']=binding['candidate']['ref']
    out['final_outcome']={'status':'pending_review','evidence_refs':['candidate-sha256:'+binding['candidate']['sha256']],
        'checked_at':request['submitted_at']}
    event=request['outcome']
    if event is not None:
        match_event(event,binding)
        require(event['decision'] in ledger.OUTCOMES,'invalid_decision')
        require(event.get('time_saved_minutes') is None,'savings_not_measured')
        decided=tracker.parse_time(event['decided_at'],'decided_at')
        require(decided<=tracker.parse_time(request['submitted_at'],'submitted_at'),'future_event')
        durations=[]
        for edit in event['edits']:
            if edit.get('measurement_kind')=='manual_duration_report':
                require(set(edit)=={'measurement_kind','duration_seconds','category','reason','reported_at','evidence'},'duration_report_shape')
                value=edit['duration_seconds']
                require(value is None or type(value) in (int,float) and math.isfinite(value) and 0<=value<=86400,'invalid_reported_duration')
                require(bool(edit.get('reason')) and bool(edit.get('category')),'rework_reason_required')
                require(tracker.parse_time(edit['reported_at'],'reported_at')<=decided,'edit_after_decision')
                evidence=bound(edit['evidence']);match_event(evidence,binding)
                require(all(evidence.get(k)==edit[k] for k in ('measurement_kind','duration_seconds','category','reason','reported_at')),'time_evidence_drift')
                durations.append(value)
                continue
            start=tracker.parse_time(edit['started_at'],'edit.started_at');end=tracker.parse_time(edit['ended_at'],'edit.ended_at')
            require(end>=start,'negative_duration');require(end<=decided,'edit_after_decision')
            require(bool(edit.get('reason')) and bool(edit.get('category')),'rework_reason_required')
            evidence=bound(edit.get('evidence'))
            match_event(evidence,binding)
            require(all(evidence.get(k)==edit[k] for k in ('started_at','ended_at','category','reason')),'time_evidence_drift')
            durations.append((end-start).total_seconds())
        ev=bound(event['evidence']);match_event(ev,binding)
        require(ev.get('decision')==event['decision'] and ev.get('decided_at')==event['decided_at'],'decision_evidence_drift')
        require(not event['edits'] or event['decision']=='adopted_with_edits','edit_decision_mismatch')
        require(event['decision']!='adopted_with_edits' or bool(event['edits']),'edit_evidence_required')
        out['human_outcome']=event['decision']
        out['edit_effort']={'modification_count':len(event['edits']) if event['edits'] else None,
            'duration_seconds':sum(durations) if durations and all(v is not None for v in durations) else None,'categories':sorted({e['category'] for e in event['edits']})}
        out['work_pattern']['rework_cause']=event.get('rework_reason') or 'unknown'
        out['final_outcome']['evidence_refs'].append('manual-event-sha256:'+event['evidence']['sha256'])
    errors=ledger.validate(out);require(not errors,'native_outcome_contract_invalid')
    return out

def publication_record(request,binding):
    ref=request['publication']
    if ref is None:return None
    require(binding['account_id'] is not None,'account_required')
    store=resolve(ref['store_ref'])
    cycle.validate_store_strict(store)
    records=cycle.read_journal(store)
    expected='synthetic-only' if request['data_classification']=='synthetic-only' else 'deidentified-operational'
    require(all(r['data_classification']==expected for r in records),'classification_drift')
    events=[r['payload']['event'] for r in records if r['operation_type']=='record-publication'
        and r['payload']['event']['publication_id']==ref['publication_id']]
    require(len(events)==1,'publication_receipt_missing')
    event=events[0]
    require(event['content_id']==binding['content_id'] and event['account_id']==binding['account_id'],'publication_binding_drift')
    record=next(r for r in records if r['operation_type']=='record-publication' and r['payload']['event']==event)
    source=record['payload']['source_objects']
    require(source['content_item_sha256']==binding['candidate']['sha256'],'published_candidate_hash_drift')
    changes=[r['payload']['event'] for r in records if isinstance(r.get('payload',{}).get('event'),dict)
        and r['payload']['event'].get('publication_id')==event['publication_id']]
    require(cycle.publication_state(changes,'publication')=='published','publication_not_active')
    require(tracker.parse_time(event['recorded_at'],'recorded_at')<=tracker.parse_time(request['submitted_at'],'submitted_at'),'future_publication')
    return event

def native_request_reviews(request,binding):
    reviews=[]
    validators={'record-publication':cycle.validate_publication_input,'record-snapshot':cycle.validate_snapshot_input,
                'build-review':cycle.validate_review_input}
    for row in request.get('native_requests',[]):
        operation=row['operation'];require(operation in validators,'unsupported_native_operation')
        entry=bound(row['input'])
        expected='synthetic-only' if request['data_classification']=='synthetic-only' else 'deidentified-operational'
        require(entry.get('data_classification')==expected,'classification_drift')
        if 'content_id' in entry:require(entry['content_id']==binding['content_id'],'event_binding_drift')
        if 'account_id' in entry:require(entry['account_id']==binding['account_id'],'event_binding_drift')
        if 'account_ids' in entry:require(entry['account_ids']==[binding['account_id']],'event_binding_drift')
        if operation=='record-publication':
            require(entry['source_objects']['content_item_sha256']==binding['candidate']['sha256'],'candidate_binding_drift')
        if operation=='record-snapshot':
            require(request['publication'] is not None and entry['publication_id']==request['publication']['publication_id'],
                    'publication_binding_drift')
        try:
            validators[operation](entry)
            status='native_input_valid_pending_manual_record'
        except cycle.CycleError as e:
            if e.code!='privacy_review_required':raise
            status='privacy_review_required'
        reviews.append({'operation':operation,'input':row['input'],'status':status,'record_performed':False,
            'entrypoint':'self-media-creation-system/scripts/content_operations_cycle.py'})
    return reviews

def build(request):
    require(request.get('schema_version')=='content-outcome-feedback-input.v1','schema_version_drift')
    require(request.get('data_classification') in {'synthetic-only','manual-review-candidate'},'classification_required')
    tracker.reject_sensitive_keys(request);cycle.reject_obvious_sensitive_values(request)
    tracker.parse_time(request['submitted_at'],'submitted_at')
    binding=request['binding']
    actual=binding_for(binding['candidate']['ref'],binding['candidate']['sha256'],binding['account_id'])
    require(binding==actual,'candidate_binding_drift')
    candidate=bound(binding['candidate'])
    synthetic='synthetic-only' in candidate.get('tags',[])
    require(synthetic==(request['data_classification']=='synthetic-only'),'classification_drift')
    if request['outcome'] is not None:require(binding['account_id'] is not None,'account_required')
    out=outcome_candidate(request,binding)
    event=publication_record(request,binding)
    observations=request['observations']
    require(event is not None or not observations,'observation_without_publication')
    labels=[o['observation']['window_label'] for o in observations]
    require(len(labels)==len(set(labels)),'duplicate_window')
    windows=[];feedback={'status':'unknown','content_signal_status':'unknown','business_signal_status':'unknown','learning_decision':'insufficient-evidence'}
    tracker_packet=None
    if event:
        published=tracker.parse_time(event['occurred_at'],'published_at')
        for i,o in enumerate(observations):
            match_event(o,binding);require(o['publication_id']==event['publication_id'],'publication_binding_drift')
            tracker.validate_observation(o['observation'],published,i)
            require(tracker.parse_time(o['observation']['captured_at'],'captured_at')<=tracker.parse_time(request['submitted_at'],'submitted_at'),'future_observation')
        for label,(lo,hi) in tracker.WINDOW_BOUNDS_HOURS.items():
            windows.append({'label':label,'opens_at':(published+timedelta(hours=lo)).isoformat(),
                'closes_at':(published+timedelta(hours=hi)).isoformat(),'status':'observed' if label in labels else 'unknown',
                'synthetic_only':synthetic})
        metrics=[m for o in observations for m in o['observation']['metrics']]
        business=[e for o in observations for e in o['observation']['business_events']]
        signal=any(m['value'] is not None for m in metrics)
        feedback={'status':'observations_available' if observations else 'unknown',
            'content_signal_status':'observed' if signal else ('content_no_signal' if observations else 'unknown'),
            'business_signal_status':'observed' if business else 'not-observed',
            'learning_decision':'none' if signal else 'insufficient-evidence','layers':list(tracker.LAYERS),
            'business_event_types':sorted({e['event_type'] for e in business}),'manual_confirmation_required':bool(business)}
        if synthetic and set(labels)==set(tracker.WINDOW_BOUNDS_HOURS):
            # Native tracker operates only on explicitly synthetic source objects.
            source_dir=resolve(binding['candidate']['ref']).parent
            account=read(source_dir/'account.json');topic=read(source_dir/'topic.json')
            item={'publication':{'published_at':event['occurred_at'],'recorded_at':event['recorded_at'],
                'platform':event['platform'],'title':event['frozen_version']['title'],
                'channel_variant':event['frozen_version']['channel_variant'],'body_unavailable_reason':'Synthetic fixture; body not published.'},
                'observations':[o['observation'] for o in observations]}
            ti=batch.build_tracker_input(item,source_dir,account,topic,candidate)
            tracker.validate_input(ti);ids=tracker.build_ids(ti);snaps=tracker.build_snapshots(ti,ids)
            _,_,tracked=tracker.build_tracked_objects(ti,account,topic,candidate,ids,snaps)
            tracker_packet=tracker.build_review_packet(ti,ids,snaps,tracked)
            tracker.validate_schema(tracker_packet,tracker.ATTENTION_SCHEMA,'review-packet')
            require(tracked['feedback']['content_signal_status']==feedback['content_signal_status'],'tracker_signal_drift')
    return {'schema_version':'content-outcome-feedback-review.v1','status':'pending_human_review',
        'data_classification':request['data_classification'],'binding':binding,'outcome_candidate':out,
        'outcome_review':ledger.review_packet(out),'publication':event,'observation_windows':windows,
        'observations':observations,'feedback':feedback,'tracker_review':tracker_packet,
        'native_request_reviews':native_request_reviews(request,binding),'scheduled_tasks':[],
        'topic_feedback_candidate':{'content_id':binding['content_id'],'closure_run_id':binding['closure_run_id'],
            'decision':'insufficient-evidence','rework_reason':out['work_pattern']['rework_cause'],'requires_human_review':True},
        'authority':{'publish_authorized':False,'operating_store_write_performed':False,'outcome_ledger_write_performed':False,
            'crm_write_performed':False,'provider_called':False,'network_called':False},
        'contract_set':cycle.contract_set_identity()}

def persist(root,texts,stop_after=None):
    root=Path(root).resolve()
    require(root.is_relative_to(W) and root!=W,'output_outside_workspace')
    for name,value in texts.items():
        p=(root/name).resolve();require(p.is_relative_to(root) and p!=root,'unsafe_output')
        require(not p.exists() or p.is_file() and p.read_bytes()==value.encode(),'output_hash_drift')
    root.mkdir(parents=True,exist_ok=True);count=0
    for name,value in texts.items():
        p=root/name
        if not p.exists():
            with p.open('xb') as f:f.write(value.encode())
            count+=1
            if count==stop_after:return 'paused'
    return 'complete'

def prepare(input_path,expected_sha256,output,stop_after=None):
    require(sha(input_path)==expected_sha256,'input_hash_drift')
    request=read(input_path);review=build(request)
    state=persist(output,{'request.json':text(request),'review-packet.json':text(review),
        'outcome-candidate.json':text(review['outcome_candidate']),
        'receipt.json':text({'schema_version':'content-outcome-feedback-conversion.v1','input_sha256':expected_sha256,
            'adapter_sha256':sha(Path(__file__)),'status':'candidate_only','binding':review['binding'],
            'review_sha256':hashlib.sha256(text(review).encode()).hexdigest(),'authority':review['authority']})},stop_after)
    return {'status':state,'review_packet':str(Path(output)/'review-packet.json')}

def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
    m=sub.add_parser('map-candidate');m.add_argument('--candidate-ref',required=True);m.add_argument('--sha256',required=True);m.add_argument('--account-id')
    m.add_argument('--submitted-at',required=True);m.add_argument('--output',type=Path,required=True)
    r=sub.add_parser('prepare');r.add_argument('--input',type=Path,required=True);r.add_argument('--sha256',required=True);r.add_argument('--output',type=Path,required=True);r.add_argument('--stop-after',type=int)
    a=p.parse_args()
    try:
        if a.command=='map-candidate':
            binding=binding_for(a.candidate_ref,a.sha256,a.account_id)
            request={'schema_version':'content-outcome-feedback-input.v1','data_classification':'manual-review-candidate',
                'submitted_at':a.submitted_at,'binding':binding,'outcome':None,'publication':None,'observations':[],'native_requests':[]}
            review=build(request);persist(a.output,{'request.json':text(request),'review-packet.json':text(review)})
            result={'status':'mapped_no_decision','review_packet':str(a.output/'review-packet.json')}
        else:result=prepare(a.input,a.sha256,a.output,a.stop_after)
        print(json.dumps(result))
    except (ValueError,KeyError,TypeError,OSError,tracker.TrackerError,cycle.CycleError,batch.BatchError) as e:
        print(json.dumps({'status':'blocked','code':getattr(e,'code','invalid_input'),'detail':str(e)}));return 2
    return 0
if __name__=='__main__':raise SystemExit(main())
