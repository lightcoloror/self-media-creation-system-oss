"""Read-only selection inside the existing resolve entry; not another workflow engine.

The Agent supplies a bounded assessment of the user's requested deliverable. This
module selects existing consumers and recovers their current state. It does not
classify free text, execute commands, dispatch threads or create production state.
"""
from __future__ import annotations

import copy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / 'schemas/self-media-work-request.v1.schema.json'
GUIDE = 'docs/workflow-entry-selection.md'
CREATIVE = {'script','interview_guide','article','graphic_note','short_post','video_plan','visualization','finished_video'}
REVIEW_PURPOSE = {'rough_cut_review':'rough_cut_recipe','fine_cut_review':'fine_cut_recipe','material_review':'material_requirement'}


def entry_binding(agent, request, result):
    context = result['editorial_context']
    return agent.sha256_value(dict(request_id=request['request_id'], topic=context['topic_selection'],
        purpose=context['purpose_source'], audience=context['audience_source'],
        feedback=context['feedback'], content_id=context['content_id'],
        creation=request['current']['creation_decision'],
        content_format=result['content_format'], platform=result['platform']))


def article_next(agent, request, refs, result, action, cmd):
    """Read existing author records and select one consumer, without a new store."""
    import author_writing_context as author
    import editorial_integrity as editorial
    guide = 'docs/article-editorial-connection.md'
    context = result['editorial_context']
    # Preserve existing article preflight hashes; managed handoffs additionally bind request ID.
    binding = agent.sha256_value(dict(topic=context['topic_selection'],
        purpose=context['purpose_source'], audience=context['audience_source'],
        feedback=context['feedback'], content_id=context['content_id'],
        creation=request['current']['creation_decision'],
        content_format=result['content_format'], platform=result['platform']))
    result['entry_binding'] = binding
    result['consumer_context_ref'] = request['current']['context_manifest']
    result['completion_boundary'] = 'Editorial author-review package only; layout, rendered inspection and manual publication remain separate.'
    def author_cmd(*args):
        return ['python', str(ROOT/'scripts/author_writing_context.py'), *map(str,args)]
    if 'author_context' not in refs:
        action('article_editorial', '复用作者上下文；先查找本稿已有记录，不重建作者库。',
            author_cmd('prepare','--store','<existing-author-store>', '--input','<author-brief.json>',
                       '--request-id',request['request_id'],'--output','<new-author-context.json>'),
            guide, ['author_context'])
        return
    author_context = author.validate_context(refs['author_context'], request['request_id'])
    if author_context['author_brief']['content_id'] != context['content_id']:
        raise agent.AgentEntryError('article_content_mismatch', 'Author and purpose must identify the same content')
    # Missing/stale preparation selects the existing preflight, never a passing fixture.
    try:
        editorial.require_preflight(refs['author_context'])
        _, preparation = editorial.preflight(refs['author_context'])
    except author.AuthorWritingError as error:
        if error.code not in {'editorial_preflight_missing','editorial_preflight_stale',
                'editorial_preflight_feedback_pending','editorial_preparation_pending'}:
            raise
        preparation = {}
    if preparation.get('entry_binding') != binding:
        action('article_editorial', '沿用七项写前判断，核对本次选题与平台后绑定当前 entry_binding；不能自动填通过。',
            cmd('review-integrity','preflight','--context',refs['author_context'],'--input','<current-preparation.json>'),
            guide, ['current_preflight_with_entry_binding'])
        return
    if 'author_revision' not in refs:
        action('article_editorial', '先复用或实际完成稿件，再登记该稿作者版本；命令只登记，不写正文。',
            author_cmd('revision','--store',author.store_api.store_path(author_context['store_path']),
                '--context',refs['author_context'],'--draft','<actual-current-draft.md>',
                '--input','<revision-reasons.json>','--output','<new-author-revision.json>'),
            guide, ['author_revision'])
        return
    revision = author.validate_revision(refs['author_revision'])
    if revision['context_ref'] != author.ref(refs['author_context']):
        raise agent.AgentEntryError('article_revision_context_mismatch', 'Revision belongs to another author context')
    draft = author.checked_ref(revision['draft_ref'])
    body = context['current_body']
    if not body or Path(body['path']).resolve() != draft or body['sha256'] != revision['draft_ref']['sha256']:
        raise agent.AgentEntryError('article_current_body_mismatch', 'Bind the actual current draft in the purpose manifest')
    try:
        status = editorial.check_draft(draft, refs['author_revision'])
    except author.AuthorWritingError as error:
        if error.code != 'editorial_review_missing':
            raise
        status = dict(checks_complete=False, required_issues_closed=False, missing_checks=sorted(editorial.CHECKS))
    result['article_editorial_status'] = status
    if status.get('is_current_revision') is False:
        raise agent.AgentEntryError('article_revision_stale', 'Select the current author revision, not an old accepted copy')
    ready = all(status.get(k) for k in ('checks_complete','required_issues_closed',
                'preparation_complete','purpose_continuity_complete','observations_complete'))
    if not ready:
        action('article_editorial', '实际检查或修改未完成项，再写入同版编辑证据；有效旧项可复用。',
            cmd('review-integrity','record','--revision',refs['author_revision'],'--input','<current-editorial-review.json>'),
            guide, ['current_editorial_checks_and_required_issue_resolution'])
        return
    result['article_review_package'] = dict(draft=dict(path=str(draft),sha256=revision['draft_ref']['sha256']),
        revision=request['current']['author_revision'], topic=context['topic_selection'],
        content_format=result['content_format'], platform=result['platform'],
        editorial=status, remaining_steps=['platform_layout','rendered_output_review','manual_publication'],
        published=False, final_media_verified=False)
    action('article_editorial', '当前稿编辑证据已核验，作者决定单独保留；不把审核包当成最终成品。',
        cmd('review-integrity','check','--revision',refs['author_revision'],'--require-complete'), guide)
    if not status.get('author_confirmation_recorded'):
        result['status'] = 'awaiting_author'
        result['next_action'] = dict(kind='human_review', selected_not_executed=True,
            reason='Review this exact draft; do not create an author confirmation on their behalf.',
            draft=str(draft), revision=str(refs['author_revision']))
        result['article_review_package']['remaining_steps'].insert(0,'author_decision')
    import article_delivery
    article_delivery.select_next(agent, request, refs, result, action, cmd)


def skill_index(agent):
    """One invocation target per canonical id; preserve stage-specific fragments."""
    contracts=agent.load_canonical_routing()
    registry=contracts['components']['skill_registry']
    aliases=registry.get('legacy_aliases',{})
    def target(name):
        seen=set()
        while name in aliases:
            if name in seen:
                raise agent.AgentEntryError('skill_alias_cycle',name)
            seen.add(name);name=aliases[name]
        return name
    entries={}
    for row in registry['skills']:
        name=target(row['id'])
        entry=entries.setdefault(name,dict(id=name,legacy_aliases=[],applicability_fragments=[],invocation_count=1))
        if name!=row['id']:
            if row['id'] not in entry['legacy_aliases']:entry['legacy_aliases'].append(row['id'])
        else:
            entry['applicability_fragments'].append(copy.deepcopy(row))
    for old in aliases:
        name=target(old)
        if name not in entries or not entries[name]['applicability_fragments']:
            raise agent.AgentEntryError('skill_alias_target_missing',name)
        if old not in entries[name]['legacy_aliases']:entries[name]['legacy_aliases'].append(old)
    return dict(contract_set_version=contracts['manifest']['contract_set_version'],
                source='canonical skill_registry; fragments retain their original applicability, not a universal checklist',
                entries=entries)


def sync_project(agent, state_path, request_path, expected_sha256, receipt_path, *, output=None, apply=False):
    """Bind a latest concrete work request inside an existing STATE, not a new DB."""
    import publication_desk as desk
    import artifact_lifecycle as lifecycle
    import archive_workflow
    from datetime import datetime, timezone
    state_path, request_path, receipt_path = map(lambda p:Path(p).absolute(),(state_path,request_path,receipt_path))
    if archive_workflow.linked(state_path) or archive_workflow.linked(receipt_path):
        raise agent.AgentEntryError('project_sync_link_protected','State/receipt paths cannot traverse shared dependency links')
    if agent.sha256_file(state_path)!=expected_sha256:
        raise agent.AgentEntryError('project_state_drift','State changed since assessment; preserve it and reread')
    if receipt_path.exists() or (apply and output is not None) or (not apply and output is None):
        raise agent.AgentEntryError('project_sync_new_receipt_and_explicit_mode_required','Choose --apply or a new --output')
    old=agent.load_json(state_path)
    request=agent.load_json(request_path)
    agent.validate_document(request,SCHEMA,'current_project_request')
    if request['requested_output']=='continue' or any(k in request.get('current',{}) for k in ('project_state','saved_work_request')):
        raise agent.AgentEntryError('project_sync_concrete_request_required','Bind one concrete current-stage request without recursive checkpoint references')
    selection=resolve(request,agent)
    projects=[];publication={}
    for kind in ('publication_data','delivery_manifest'):
        ref=request.get('current',{}).get(kind)
        if ref:
            if agent.sha256_file(Path(ref['path'])) != ref['sha256']:
                raise agent.AgentEntryError('source_hash_drift',ref['path'])
            document=agent.load_json(Path(ref['path']))
            projects.append(document.get('project_id'))
            if kind=='publication_data':publication=desk.publication_summary(document)
    if not projects or any(not p or p!=projects[0] for p in projects):
        raise agent.AgentEntryError('project_sync_identity_required','Current saved data must agree on a project identity')
    previous=old.get('workflow_current')
    if previous and previous.get('project_id')!=projects[0]:
        raise agent.AgentEntryError('project_sync_identity_conflict','Do not rebind an indexed project to another one')
    index=dict(schema_version='self-media-project-entry.v1',project_id=projects[0],
        request_ref=dict(path=str(request_path),sha256=agent.sha256_file(request_path)),
        requested_output=request['requested_output'],consumer=selection['primary_entry'],
        selection_status=selection['status'],publication_summary=publication,
        updated_at=datetime.now(timezone.utc).isoformat(),commands_executed=False)
    updated=copy.deepcopy(old)
    comparable=lambda value:{k:v for k,v in value.items() if k!='updated_at'}
    changed=previous is None or comparable(previous)!=comparable(index)
    if changed:
        if previous:updated.setdefault('workflow_entry_history',[]).append(copy.deepcopy(previous))
        updated['workflow_current']=index
    target=state_path if apply else Path(output).absolute()
    if archive_workflow.linked(target):
        raise agent.AgentEntryError('project_sync_link_protected',str(target))
    receipt_path.parent.mkdir(parents=True,exist_ok=True)
    desk.write_new(receipt_path.with_suffix('.state-before.json'),old)
    if agent.sha256_file(state_path)!=expected_sha256:
        raise agent.AgentEntryError('project_state_drift','State changed before write; no overwrite performed')
    if apply:
        if changed:lifecycle._write_json_atomic(target,updated)
    else:desk.write_new(target,updated)
    report=dict(schema_version='self-media-project-sync-receipt.v1',status='synced' if changed else 'already_current',
        source_ref=dict(path=str(state_path),sha256=expected_sha256),target_ref=dict(path=str(target),sha256=agent.sha256_file(target)),
        request_ref=index['request_ref'],legacy_values_preserved=all(updated[k]==old[k] for k in old if k not in ('workflow_current','workflow_entry_history')),
        publication_summary=publication,selection=selection,media_changed=False,human_approved=False,published=False)
    desk.write_new(receipt_path,report)
    return report


def discovery():
    return dict(entrypoint='python scripts/self_media_agent.py resolve --request <task.json> --output <selection.json>',
        input_schema='self-media-work-request.v1', schema_path=str(SCHEMA), guide=GUIDE,
        selection_input='Agent extracts requested_output, topic origin/adoption anchors, explicit format/platform, current artifacts and selection_basis; no workflow_goal required',
        order=['explicit_deliverable','current_saved_state','creation_form_if_applicable','topic_and_independent_format_platform','existing_recipe_or_article_editorial_consumer','next_action'],
        no_new_business_workflow=True, dispatch_authorized=False, commands_executed=False,
        article_guide='docs/article-editorial-connection.md',
        continuation='Re-resolve the current STATE/saved concrete request or use sequence-status for an existing capsule; never infer completion or restart from filenames',
        layers=[
            dict(layer='entry', meaning='本次交付与进度选择', consumer='resolve'),
            dict(layer='creation_form', meaning='故事、体验、说明或技术返工', consumer='creation-route'),
            dict(layer='managed_recipe', meaning='五条已登记的受管执行序列；不是全部自媒体任务', consumer='resolve / prepare-step / sequence-status'),
            dict(layer='shared_subflow', meaning='封面、原片审核、交付、发布页、运营、归档按需复用', consumer='existing subcommands'),
            dict(layer='quality_gate', meaning='所选流程内部的条件检查；不是另一条工作流', consumer='existing gate consumers'),
            dict(layer='owner', meaning='维护归属；直接指派留在当前任务，转发须另有授权', consumer='owner metadata only'),
            dict(layer='legacy', meaning='旧快照和别名只作兼容与历史证据', consumer='canonical routing binding')])


def resolve(request, agent):
    agent.validate_document(request, SCHEMA, 'work_request')
    current = request.get('current', {})
    refs, docs = {}, {}

    def read_ref(ref):
        if not Path(ref['path']).is_absolute():
            raise agent.AgentEntryError('selection_absolute_path_required',ref['path'])
        path = Path(ref['path']).resolve()
        if not path.is_file() or path.stat().st_size > 2_000_000:
            raise agent.AgentEntryError('selection_metadata_unreadable', str(path))
        if agent.sha256_file(path) != ref['sha256']:
            raise agent.AgentEntryError('source_hash_drift', str(path))
        return path, agent.load_json(path)

    for key, ref in current.items():
        if key == 'receipts':
            refs[key] = [read_ref(r)[0] for r in ref]
        else:
            refs[key], docs[key] = read_ref(ref)
    project_ids = {docs[key].get('project_id') for key in ('publication_data','delivery_manifest') if key in docs}
    project_ids.discard(None)
    if len(project_ids)>1:
        raise agent.AgentEntryError('selection_project_identity_conflict','Current artifacts belong to different projects')
    if current.get('receipts') and 'capsule' not in refs:
        raise agent.AgentEntryError('selection_receipts_without_capsule', 'Use the capsule that owns these receipts')
    kind = request['requested_output']
    result = dict(schema_version='self-media-entry-selection.v1', request_id=request['request_id'],
        requested_output=kind, status='selected', primary_entry=None, workflow_goal=None,
        selection_basis=request['selection_basis'], reason='', next_action=None, missing_inputs=[],
        working_directory=str(ROOT),
        read_next=[], creation_route=None, commands_executed=False, dispatch_authorized=False,
        media_export_authorized=False, publication_authority=False,
        boundaries=copy.deepcopy(agent.EXPECTED_BOUNDARIES),
        input_sha256=agent.sha256_value(request), selector_sha256=agent.sha256_file(Path(__file__)))
    if project_ids:result['project_id']=next(iter(project_ids))

    def action(entry, reason, command=None, guide=None, missing=()):
        result.update(primary_entry=entry, reason=reason, missing_inputs=list(missing))
        if missing:
            result['status']='needs_context'
        if guide:
            guide=str((ROOT/guide).resolve())
        if command:
            result['next_action']=dict(kind='existing_cli', argv=command, selected_not_executed=True)
        elif guide:
            result['next_action']=dict(kind='read_existing_guide', path=guide, selected_not_executed=True)
        if guide:
            result['read_next']=[guide]

    def cmd(*args):
        return ['python', str(ROOT/'scripts/self_media_agent.py'), *map(str,args)]

    def finish():
        # Selection remains the original route. Purpose is shared context, not a
        # second selector or a requirement to rewrite a locked body.
        needs_purpose = kind in CREATIVE | {'title_options', 'cover_options', 'fine_cut_review', 'performance_review'}
        if request.get('change_scope') == 'technical_only' and result.get('workflow_goal') == 'context_efficient_rework':
            needs_purpose = False
        if 'context_manifest' in refs:
            import purpose_continuity
            try:
                result['editorial_context'] = purpose_continuity.validate_context(refs['context_manifest'],request['request_id'])
            except purpose_continuity.PurposeError as error:
                raise agent.AgentEntryError(error.code, str(error)) from error
            if kind in {'title_options','cover_options'} and result['editorial_context']['current_body'] is None:
                result['missing_inputs'].append('current_body_in_context_manifest')
            # Pass the same reference to actual consumers, not only the selector.
            if result['primary_entry'] in {'publication_desk','video_delivery','video_review','covers'} and result.get('next_action',{}).get('kind')=='existing_cli':
                argv = result['next_action']['argv']
                if '--context-manifest' not in argv and any(value in argv for value in ('check','upgrade','prepare','render','plan')):
                    argv += ['--context-manifest', str(refs['context_manifest'])]
                result['consumer_context_ref'] = current['context_manifest']
        elif needs_purpose:
            result['missing_inputs'].append('context_manifest_with_editorial_context')
        if needs_purpose or 'context_manifest' in refs:
            result['read_next'].append(str(ROOT/'docs/purpose-continuity.md'))
            result['purpose_completion'] = 'context_only; use review-integrity check-stage on actual output; not semantic or audience verification'
        if result['missing_inputs']:
            result['status'] = 'needs_context'
        result['payload_sha256']=agent.sha256_value(result)
        return result

    def managed(goal, phase='production', preparation_kind='spoken_script'):
        catalog=agent.load_catalog()
        recipe=agent._recipe_for_goal(catalog,goal,phase,preparation_kind)
        result.update(workflow_goal=goal, recipe_id=recipe['recipe_id'], creation_phase=phase,
            required_initial_inputs=recipe['required_initial_inputs'])
        if phase=='prerecording':
            result['preparation_kind']=preparation_kind
        if 'managed_request' in docs:
            old=docs['managed_request']
            if old.get('request_id') != request['request_id']:
                raise agent.AgentEntryError('managed_request_identity_mismatch','Saved recipe belongs to another task')
            if old.get('workflow_goal') != goal or old.get('creation_phase','production') != phase or (phase=='prerecording' and old.get('preparation_kind','spoken_script') != preparation_kind):
                raise agent.AgentEntryError('selected_entry_conflict','Saved recipe request conflicts with the requested output; do not relabel it')
            agent.validate_request(old)
            if goal in {'moments_short_post','xhs_evidence_graphic','case_video_candidate'}:
                binding = entry_binding(agent, request, result)
                if old.get('entry_binding') != binding:
                    action('managed_recipe','旧请求缺少或不匹配当前选题/形态/平台绑定；保存以下模板为新请求后重解，不执行旧请求。',
                        guide=GUIDE,missing=['managed_request_with_current_entry_binding'])
                    result['request_template'] = {**copy.deepcopy(old), 'entry_binding':binding}
                    result['template_is_incomplete'] = False
                    return
            action('managed_recipe', '按当前交付选择已有受管配方；其输入、顺序与完成门保持原实现。',
                cmd('resolve','--request',refs['managed_request'],'--output','<new-capsule.json>'), GUIDE)
        else:
            action('managed_recipe','已选定已有配方；由 Agent 恢复其已有输入，不让用户选择工作流名。',
                guide=GUIDE, missing=['managed_request'])
            result['request_template']=dict(schema_version='self-media-agent-request.v1',request_id=request['request_id'],
                workflow_goal=goal, synthetic_only=False, available_inputs=[],input_refs=[])
            if goal in {'moments_short_post','xhs_evidence_graphic','case_video_candidate'}:
                result['request_template']['entry_binding'] = entry_binding(agent, request, result)
            if phase=='prerecording':
                result['request_template'].update(creation_phase=phase,preparation_kind=preparation_kind)
            result['template_is_incomplete']=True

    # An explicit deliverable overrides an unrelated old capsule. Only a bare
    # continuation resumes the sequence; it never silently restarts one.
    if kind=='continue':
        if 'project_state' in docs:
            index = docs['project_state'].get('workflow_current',{})
            if index.get('schema_version') != 'self-media-project-entry.v1' or not index.get('request_ref'):
                action('project_state_sync','旧 STATE 缺少当前请求引用；先恢复真实阶段并用 sync-project 绑定，不从文件名猜进度。',
                    guide=GUIDE,missing=['latest_concrete_work_request_bound_to_project_state'])
                return finish()
            if 'saved_work_request' in current and current['saved_work_request'] != index['request_ref']:
                raise agent.AgentEntryError('continuation_context_conflict','Project state and explicit saved request disagree')
            continued = copy.deepcopy(request)
            continued['current'].pop('project_state')
            continued['current']['saved_work_request']=index['request_ref']
            value=resolve(continued,agent)
            if value.get('project_id') is not None and value['project_id'] != index.get('project_id'):
                raise agent.AgentEntryError('project_sync_identity_conflict','Current request does not belong to this project state')
            value['project_state_ref']=current['project_state']
            value['project_status']=copy.deepcopy(index.get('publication_summary',{}))
            value['input_sha256']=agent.sha256_value(request)
            value.pop('payload_sha256',None)
            value['payload_sha256']=agent.sha256_value(value)
            return value
        if 'capsule' in refs:
            sequence=agent.derive_sequence_status(refs['capsule'],refs.get('receipts',[]))
            result['sequence']=sequence
            action('managed_continuation','使用现有 capsule 和有序回执得出的唯一下一步；不新建流程。',
                cmd('sequence-status','--capsule',refs['capsule'],*[v for path in refs.get('receipts',[]) for v in ('--receipt',path)]),
                'docs/agent-sequence-enforcement-2026-09-05.md')
            return finish()
        if 'error_receipt' in docs:
            result['recovery']=agent.resume_receipt(docs['error_receipt'])
            action('existing_recovery','沿用原错误恢复入口，不自动重试。',cmd('resume','--receipt',refs['error_receipt']))
            return finish()
        if 'saved_work_request' in docs:
            # The existing work request is the checkpoint; no extra stage store
            # or filename/time heuristic. Re-resolve consumers under current code.
            saved = copy.deepcopy(docs['saved_work_request'])
            if saved.get('schema_version') != 'self-media-work-request.v1' or saved.get('requested_output') == 'continue':
                raise agent.AgentEntryError('continuation_concrete_request_required',
                    'Bind the latest concrete work request, not another continuation or cached command')
            recovered = saved.setdefault('current', {})
            if 'saved_work_request' in recovered:
                raise agent.AgentEntryError('continuation_checkpoint_cycle', 'Concrete checkpoints cannot contain another checkpoint')
            if 'project_state' in recovered:
                raise agent.AgentEntryError('continuation_checkpoint_cycle','Concrete request cannot point back to its project state')
            for key, ref in current.items():
                if key == 'saved_work_request':
                    continue
                if key in recovered and recovered[key] != ref:
                    raise agent.AgentEntryError('continuation_context_conflict',
                        'Current ' + key + ' conflicts with saved state; explicitly select the changed deliverable')
                recovered[key] = copy.deepcopy(ref)
            value = resolve(saved, agent)
            value.update(request_id=request['request_id'], requested_output='continue',
                recovered_output=saved['requested_output'], input_sha256=agent.sha256_value(request),
                continuation_source=dict(request_ref=current['saved_work_request'],
                    original_request_id=saved['request_id'],
                    current_consumer_resolved=True, previous_commands_replayed=False,
                    author_decisions_inherited='bound context/feedback only; never approval from filenames'))
            value.pop('payload_sha256', None)
            value['payload_sha256'] = agent.sha256_value(value)
            return value
        candidates=[k for k in ('publication_data','delivery_manifest','review_request') if k in refs]
        if len(candidates)==1 and candidates[0]!='review_request':
            kind={'publication_data':'publication_page','delivery_manifest':'finished_video'}[candidates[0]]
            result['recovered_output']=kind
        else:
            action('resume_current_artifact','“继续”需要当前进度或明确当前交付；不能按旧文件名猜测。',
                guide=GUIDE,missing=['current_capsule_or_explicit_requested_output'])
            return finish()

    # Spoken delivery is a shared consumer of an already compiled plan. A
    # deliverable picks the route; a legacy plan's next_action never picks it.
    spoken_kinds={'rough_cut_review':'review', 'rough_cut_video':'video',
                  'finished_video':'video', 'editable_project':'editable_project'}
    # A retained source plan must not restart an already prepared review,
    # final-delivery check or technical rework.
    use_existing_stage=(
        (kind=='rough_cut_review' and 'review_request' in docs)
        or (kind=='finished_video' and ('delivery_manifest' in docs or request.get('change_scope')=='technical_only')))
    if kind in spoken_kinds and not use_existing_stage and ('spoken_edit_plan' in docs or kind in ('rough_cut_video','editable_project')):
        import sys
        mvp=ROOT.parent/'ai-video-tools-20260708/mvp-video-pipeline'
        if str(mvp/'src') not in sys.path:
            sys.path.insert(0,str(mvp/'src'))
        if not (mvp/'src/video_creation_pipeline/spoken_delivery.py').is_file():
            action('missing_spoken_delivery_owner',
                   'The complete spoken-delivery owner is unavailable; do not substitute local-rough-cut P0.',
                   guide=GUIDE, missing=['full_mvp_spoken_delivery_owner'])
            result['external_owner_status']='not-available-in-this-public-workspace'
            return finish()
        from video_creation_pipeline import spoken_delivery
        from video_creation_pipeline.errors import ContractError
        wrapper=str(mvp/'scripts/spoken_rough_cut.py')
        missing=[]
        if 'spoken_edit_plan' not in docs:
            missing.append('spoken_edit_plan')
        if 'spoken_delivery_request' in docs:
            delivery=docs['spoken_delivery_request']
            try:
                spoken_delivery.validate_delivery_request(delivery)
            except ContractError as exc:
                raise agent.AgentEntryError('spoken_delivery_invalid',str(exc)) from exc
            if delivery['deliverable']!=spoken_kinds[kind]:
                raise agent.AgentEntryError('spoken_delivery_conflict','Saved delivery request conflicts with this requested output')
            if request.get('editor') and delivery.get('editor')!=request['editor']:
                raise agent.AgentEntryError('spoken_delivery_conflict','Saved editor conflicts with this request')
            if 'spoken_edit_plan' in docs:
                try:
                    result['spoken_delivery_selection']=spoken_delivery.select_delivery(refs['spoken_edit_plan'],refs['spoken_delivery_request'])
                except ContractError as exc:
                    raise agent.AgentEntryError('spoken_delivery_invalid',str(exc)) from exc
        else:
            template=dict(schema=spoken_delivery.REQUEST_SCHEMA,deliverable=spoken_kinds[kind],selection_basis=request['selection_basis'])
            if kind=='editable_project':
                if request.get('editor'): template['editor']=request['editor']
                else: missing.append('requested_editor')
            result['delivery_request_template']=template
            missing.append('spoken_delivery_request')
        argv=['python',wrapper,'select-delivery','--plan',str(refs.get('spoken_edit_plan','<spoken-edit-plan.json>')),
              '--request',str(refs.get('spoken_delivery_request','<delivery-request.json>')),'--output','<new-selection.json>']
        action('spoken_delivery','按交付需求选择原片审核、直接视频或指定编辑器工程；不执行旧配方的剪映下一步。',argv,
               str(mvp/'docs/spoken-delivery-routing.md'),missing)
        result['working_directory']=str(mvp)
        if kind=='finished_video':
            result['completion_boundary']='本步骤只产生原声净剪候选；字幕/动效包装和最终交付检查仍须后续完成。'
        return finish()

    # Review, packaging and operations are shared stages, not reasons to start a
    # case-video/story recipe or change the selected creative form.
    if kind in REVIEW_PURPOSE:
        purpose=REVIEW_PURPOSE[kind]
        if 'review_request' in docs:
            import video_review_delivery
            video_review_delivery.validate_request(docs['review_request'],purpose)
            action('video_review','审核使用原片时间区间；不进入媒体导出流程。',
                cmd('video-review','prepare','--purpose',purpose,'--request',refs['review_request'],'--output-dir','<new-review-dir>'),
                'docs/source-time-range-review.md')
        else:
            action('video_review','先恢复原片、时间与已保存审核要求，不先剪审核片。',cmd('video-review'),
                'docs/source-time-range-review.md',['review_request'])
        result.update(review_purpose=purpose,review_access_mode='source_time_range')
        return finish()
    if kind=='publication_page':
        import publication_desk as desk
        if 'publication_data' not in docs:
            action('publication_desk','发布辅助页复用现有共享生成器，不重跑创作或视频制作。',cmd('publication-desk'),'docs/publication-desk.md',['publication_data'])
        else:
            data=docs['publication_data']
            migrated=desk.upgrade(data)
            comparable=copy.deepcopy(migrated); comparable['revision']=data.get('revision')
            needs_upgrade=comparable!=data
            page_stale='publication_page_build' not in refs
            if page_stale:
                result['page_build']=dict(status='missing',reason='No bound generated page; render once with the current consumer')
            if 'publication_page_build' in refs:
                try:
                    result['page_build']=desk.verify_page_build(refs['publication_data'],refs['publication_page_build'])
                except (ValueError,OSError,KeyError) as error:
                    page_stale=True
                    result['page_build']=dict(status='stale',reason=str(error),old_ref=current['publication_page_build'])
            operation='upgrade' if needs_upgrade else 'render' if page_stale else 'check'
            argv=['python',str(ROOT/'scripts/publication_desk.py'),operation,'--input',str(refs['publication_data'])]
            argv+=['--output','<new-desk-data.json>'] if needs_upgrade else ['--stage','preparation']
            if page_stale and not needs_upgrade:
                argv=['python',str(ROOT/'scripts/publication_desk.py'),'render','--input',str(refs['publication_data']),'--output','<new-current-page.html>']
            elif 'publication_page_build' in refs and not needs_upgrade:
                argv+=['--page-build',str(refs['publication_page_build'])]
            action('publication_desk','先同步旧数据和当前生成页；有当前页面证据才检查发布准备。',argv,'docs/publication-desk.md')
            result['migration_required']=needs_upgrade or page_stale
            result['page_regeneration_required']=page_stale
        return finish()
    if kind=='cover_options' and 'cover_brief' in refs:
        action('covers','用已绑定的当前封面 brief 和目的要求进入原封面计划入口。',
            ['python',str(ROOT/'scripts/cover_workbench.py'),'plan','--input',str(refs['cover_brief']),'--output','<new-cover-route-plan.json>'],
            'docs/content-driven-covers.md')
        return finish()
    simple={
        'cover_options':('covers','现有封面工作台负责方案与比例，不启动完整脚本或剪辑流程。','covers','docs/content-driven-covers.md'),
        'publication_record':('operations','先记录用户提供的定时、发布或指标事实；不把记录任务转成复盘。','operations','docs/manual-publication-feedback-tracking.md'),
    }
    if kind in simple:
        entry,reason,sub,guide=simple[kind];action(entry,reason,cmd(sub),guide);return finish()
    if kind=='title_options':
        result['coordinator']=skill_index(agent)['entries']['dbs-title-cover-intro']
        action('text_packaging','标题、封面文字与开头共用现有协调入口；仅改文案不生成封面图或整段脚本。',
            guide=str(ROOT.parent/'docs/content-creation-system/routing/skill-invocation-runbook.md'))
        return finish()
    if kind=='archive_plan':
        action('artifact_lifecycle','沿用现有归档分级及计划，不从头制作或直接清理。',
            ['python',str(ROOT/'scripts/artifact_lifecycle.py'),'archive-policy','--help'],'docs/video-archive-levels.md')
        return finish()
    if kind=='workflow_repair':
        action('workflow_maintenance','这是现有流程代码与入口维护，不是创作新作品或转发 Owner 的授权。',cmd('doctor'),GUIDE)
        return finish()
    if kind=='performance_review':
        managed('publication_feedback_review');return finish()
    if kind=='finished_video' and 'delivery_manifest' in docs:
        if docs['delivery_manifest'].get('schema')!='self-media.video-delivery.v1':
            raise agent.AgentEntryError('selection_delivery_manifest_invalid','Expected current delivery manifest')
        action('video_delivery','已有制作合同从当前交付检查继续，不自动重做分析或渲染。',
            cmd('video-delivery','check','--input',refs['delivery_manifest']),'docs/video-delivery.md')
        return finish()
    if request.get('change_scope')=='technical_only' and kind in ('video_plan','finished_video'):
        managed('context_efficient_rework');return finish()

    if kind in CREATIVE:
        if 'creation_context' not in docs:
            action('creation_route','新写或重新策划先由 Agent 根据已有目标和素材判断表达形式，不按“视频”一词强套案例流程。',
                cmd('creation-route'),'docs/creation-route-selection.md',['creation_context'])
            return finish()
        route=agent._load_creation_route()
        context=docs['creation_context']
        if context.get('task_id')!=request['request_id']:
            raise agent.AgentEntryError('creation_route_task_mismatch','Current creative context belongs to another task')
        decision=route.resolve(context)
        if 'creation_decision' in docs:
            route.check(docs['creation_decision'],context,request['request_id'])
        result['creation_route']=dict(primary_route=decision['primary_route'],vlog_style=decision['vlog_style'],status=decision['status'])
        if decision['status']!='ready' or 'creation_decision' not in docs:
            action('creation_route','先补齐并保存当前表达形式判断；未知材料不构造为已通过。',
                cmd('creation-route','resolve','--input',refs['creation_context'],'--output','<creation-decision.json>'),
                'docs/creation-route-selection.md',['ready_creation_decision'])
            result['issues']=decision['issues'];return finish()
        if decision['primary_route']=='technical-rework':
            if kind not in ('video_plan','finished_video'):
                raise agent.AgentEntryError('selected_entry_conflict','Technical rework cannot replace a new writing task')
            managed('context_efficient_rework');return finish()
        contracts=agent.load_canonical_routing()['components']
        by_format={row['format']:row['id'] for row in contracts['format_adapters']['adapters']}
        fixed={'article':'longform-article','graphic_note':'graphic-note','short_post':'moments-short-text'}
        content_format=request.get('content_format',fixed.get(kind))
        if content_format is not None and content_format not in by_format:
            raise agent.AgentEntryError('unknown_content_format','Use an existing canonical format')
        if kind in fixed and content_format!=fixed[kind]:
            raise agent.AgentEntryError('selected_entry_conflict','Requested output conflicts with the supplied content format')
        overlays={row['id'].split('@')[0]:row for row in contracts['platform_overlays']['overlays']}
        platform=request.get('platform')
        if platform is not None and platform not in overlays:
            raise agent.AgentEntryError('unknown_platform','Choose an existing canonical platform, never infer one')
        if platform and content_format and content_format not in overlays[platform]['formats']:
            raise agent.AgentEntryError('platform_format_conflict','Selected platform does not support this registered format')
        result.update(content_format=content_format,format_adapter=by_format.get(content_format),platform=platform,
                      platform_overlay=overlays[platform]['id'] if platform else None)
        missing=[]
        if not content_format: missing.append('content_format')
        if not platform: missing.append('platform')
        topic = None
        if 'context_manifest' in refs:
            import purpose_continuity
            result['editorial_context']=purpose_continuity.validate_context(refs['context_manifest'],request['request_id'])
            topic=result['editorial_context']['topic_selection']
            if not topic: missing.append('topic_selection_in_context_manifest')
            elif topic['adoption']!='selected': missing.append('topic_adoption_basis_for_selected_task')
        else:
            missing.append('context_manifest_with_topic_selection')
        if 'topic_decision' in docs:
            import topic_angle_decision
            if not topic or topic.get('framework_decision_ref') != current['topic_decision']:
                raise agent.AgentEntryError('topic_decision_binding_mismatch','Bind this exact decision through topic_selection.decision_artifact_id')
            try:
                result['framework_decision']=topic_angle_decision.continuation(docs['topic_decision'])
            except topic_angle_decision.TopicAngleError as error:
                raise agent.AgentEntryError(error.code,str(error)) from error
            if not result['framework_decision']['may_continue']:
                missing.append('current_framework_decision_permits_drafting')
        elif topic and topic.get('framework_decision_ref'):
            missing.append('topic_decision')
        if missing:
            action('canonical_format_adapter','从当前指派或已存决定补齐缺项；不默认平台、不替作者采用选题。',
                   guide='docs/article-editorial-connection.md',missing=missing)
            if not content_format: result['available_formats']=list(by_format)
            result['available_platforms']=[name for name,row in overlays.items() if not content_format or content_format in row['formats']]
            return finish()
        if decision['primary_route']=='travel-experience':
            if kind not in ('script','video_plan','finished_video'):
                raise agent.AgentEntryError('selected_entry_conflict','Vlog form conflicts with requested deliverable')
            action('travel_experience','复用独立体验/Vlog工作单与现有素材工具；不冒充五条受管配方中的案例视频。',guide='docs/travel-experience-vlog-workflow.md')
            result['automatic_analysis_started']=False
        elif kind=='article':
            try:
                article_next(agent,request,refs,result,action,cmd)
            except ValueError as error:
                if isinstance(error,agent.AgentEntryError): raise
                raise agent.AgentEntryError(getattr(error,'code','article_editorial_invalid'),str(error)) from error
        elif kind=='short_post' and platform=='wechat-moments': managed('moments_short_post')
        elif kind=='graphic_note' and platform=='xiaohongshu': managed('xhs_evidence_graphic')
        elif kind=='interview_guide' or (kind=='script' and context['topic_domain']=='case'):
            managed('case_video_candidate','prerecording','interview_guide' if kind=='interview_guide' else 'spoken_script')
        elif kind=='finished_video' and context['topic_domain']=='case': managed('case_video_candidate')
        elif kind=='visualization':
            action('content_studio_visual','在当前任务使用既有 Content Studio 视觉路由；归属信息不构成跨线程发送授权。',
                guide=str(ROOT.parent/'docs/local-tools/content-creation-system-AGENT_DISCOVERY.md'))
        else:
            adapters=agent.load_canonical_routing()['components']['format_adapters']['adapters']
            by_format={row['format']:row['id'] for row in adapters}
            content_format=request.get('content_format',fixed.get(kind))
            if content_format is not None and content_format not in by_format:
                raise agent.AgentEntryError('unknown_content_format','Use an existing canonical format; do not invent an adapter')
            if kind=='article' and content_format!='longform-article':
                raise agent.AgentEntryError('selected_entry_conflict','Article output conflicts with the supplied content format')
            action('canonical_format_adapter','使用既有文体适配与作者表达要求，不借用不适用的案例配方。',
                guide=str(ROOT.parent/'docs/content-creation-system/routing/format-adapter-playbooks.md'),
                missing=[] if content_format else ['content_format'])
            result['format_adapter']=by_format.get(content_format)
            if not content_format:
                result['available_formats']=list(by_format)
        return finish()
    raise agent.AgentEntryError('entry_selection_unresolved',kind)
