"""Read-only selection inside the existing resolve entry; not another workflow engine.

The Agent supplies a bounded assessment of the user's requested deliverable. This
module selects existing consumers and recovers their current state. It does not
classify free text, execute commands, dispatch threads or create production state.
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import runtime_paths

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


def _editorial_author_chain(agent, request, refs, result, action, cmd, *, primary_entry, guide, is_article=False, pre_gate=None):
    """Read existing author records and select one consumer, without a new store."""
    import author_writing_context as author
    import editorial_integrity as editorial
    context = result['editorial_context']
    # Preserve existing article preflight hashes; managed handoffs additionally bind request ID.
    binding = agent.sha256_value(dict(topic=context['topic_selection'],
        purpose=context['purpose_source'], audience=context['audience_source'],
        feedback=context['feedback'], content_id=context['content_id'],
        creation=request['current']['creation_decision'],
        content_format=result['content_format'], platform=result['platform']))
    result['entry_binding'] = binding
    result['consumer_context_ref'] = request['current']['context_manifest']
    topic_facets = (result.get('framework_decision') or {}).get('topic_facets')
    topic_decision_ref = request.get('current', {}).get('topic_decision')
    if topic_facets is not None:
        handoff = result.setdefault('writing_handoff', {})
        handoff.update(
            topic_facets=copy.deepcopy(topic_facets),
            topic_decision_ref=copy.deepcopy(topic_decision_ref),
            note='Draft from confirmed topic_facets; C04 editorial review must anchor the main element, supporting element relations, and dominant action in the actual draft.',
        )
    if is_article:
        result['completion_boundary'] = 'Editorial author-review package only; layout, rendered inspection and manual publication remain separate.'
    else:
        result['completion_boundary'] = 'Draft editorial and author-review check only; final media, packaging and manual publication remain separate.'
    def author_cmd(*args):
        return runtime_paths.managed_self_argv(ROOT, 'scripts/author_writing_context.py', *args)
    prepare_args = ['prepare', '--store', '<existing-author-store>', '--input', '<author-brief.json>',
                    '--request-id', request['request_id']]
    if topic_facets is not None and 'topic_decision' in refs:
        prepare_args.extend(['--topic-decision', str(refs['topic_decision'])])
    if 'fact_card' in refs:
        prepare_args.extend(['--fact-card', str(refs['fact_card'])])
    if 'plain_language_plan' in refs:
        prepare_args.extend(['--plain-language-plan', str(refs['plain_language_plan'])])
    prepare_args.extend(['--output', '<new-author-context.json>'])
    if 'author_context' not in refs:
        action(primary_entry, '复用作者上下文；先查找本稿已有记录，不重建作者库。',
            author_cmd(*prepare_args), guide, ['author_context'])
        return
    try:
        author_context = author.validate_context(refs['author_context'], request['request_id'])
    except author.AuthorWritingError as error:
        raise agent.AgentEntryError(error.code, str(error)) from error
    if author_context['author_brief']['content_id'] != context['content_id']:
        raise agent.AgentEntryError('article_content_mismatch' if is_article else 'editorial_content_mismatch',
                                    'Author and purpose must identify the same content')
    if topic_facets is not None:
        if 'topic_decision_ref' not in author_context:
            action(primary_entry, '作者上下文缺少已绑定的选题分面决定；复用已有记录并补充 --topic-decision 后重试。',
                author_cmd(*prepare_args), guide, ['author_context_with_topic_facets'])
            return
        bound_decision = author.checked_ref(author_context['topic_decision_ref']).resolve()
        expected_decision = Path(topic_decision_ref['path']).resolve() if topic_decision_ref else None
        if (expected_decision is None or bound_decision != expected_decision
                or author_context['topic_decision_ref']['sha256'] != topic_decision_ref['sha256']
                or author_context.get('topic_facets') != topic_facets):
            raise agent.AgentEntryError('editorial_topic_facets_mismatch',
                'Author context topic_facets must match the bound topic_decision')
    current_refs = request.get('current', {})
    if 'fact_card' in refs or (pre_gate and pre_gate.get('needs_fact_lock')):
        if 'fact_card' in refs and 'fact_card_ref' not in author_context:
            action(primary_entry, '作者上下文缺少已锁定的事实卡绑定；补充 --fact-card 后重试。',
                author_cmd(*prepare_args), guide, ['author_context_with_fact_card'])
            return
        if 'fact_card' in refs and 'fact_card_ref' in author_context:
            bound_fc = author.checked_ref(author_context['fact_card_ref']).resolve()
            if bound_fc != refs['fact_card'].resolve() or author_context['fact_card_ref']['sha256'] != current_refs['fact_card']['sha256']:
                raise agent.AgentEntryError('editorial_fact_card_mismatch',
                    'Author context fact_card_ref must match the locked current.fact_card')
    if 'plain_language_plan' in refs and pre_gate and pre_gate.get('plan_applicable'):
        if 'plain_language_plan_ref' not in author_context:
            action(primary_entry, '作者上下文缺少通俗化计划绑定；补充 --plain-language-plan 后重试。',
                author_cmd(*prepare_args), guide, ['author_context_with_plain_language_plan'])
            return
        bound_plan = author.checked_ref(author_context['plain_language_plan_ref']).resolve()
        if bound_plan != refs['plain_language_plan'].resolve() or author_context['plain_language_plan_ref']['sha256'] != current_refs['plain_language_plan']['sha256']:
            raise agent.AgentEntryError('editorial_plain_language_plan_mismatch',
                'Author context plain_language_plan_ref must match current.plain_language_plan')
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
        action(primary_entry, '沿用七项写前判断，核对本次选题与平台后绑定当前 entry_binding；不能自动填通过。',
            cmd('review-integrity','preflight','--context',refs['author_context'],'--input','<current-preparation.json>'),
            guide, ['current_preflight_with_entry_binding'])
        return
    if 'author_revision' not in refs:
        action(primary_entry, '先复用或实际完成稿件，再登记该稿作者版本；命令只登记，不写正文。',
            author_cmd('revision','--store',author.store_api.store_path(author_context['store_path']),
                '--context',refs['author_context'],'--draft','<actual-current-draft.md>',
                '--input','<revision-reasons.json>','--output','<new-author-revision.json>'),
            guide, ['author_revision'])
        return
    revision = author.validate_revision(refs['author_revision'])
    if revision['context_ref'] != author.ref(refs['author_context']):
        raise agent.AgentEntryError('article_revision_context_mismatch' if is_article else 'editorial_revision_context_mismatch',
                                    'Revision belongs to another author context')
    draft = author.checked_ref(revision['draft_ref'])
    body = context['current_body']
    if not body or Path(body['path']).resolve() != draft or body['sha256'] != revision['draft_ref']['sha256']:
        raise agent.AgentEntryError('article_current_body_mismatch' if is_article else 'editorial_current_body_mismatch',
                                    'Bind the actual current draft in the purpose manifest')
    try:
        status = editorial.check_draft(draft, refs['author_revision'])
    except author.AuthorWritingError as error:
        if error.code != 'editorial_review_missing':
            raise
        status = dict(checks_complete=False, required_issues_closed=False, missing_checks=sorted(editorial.CHECKS))
    result['editorial_status'] = status
    if is_article:
        result['article_editorial_status'] = status
    if status.get('is_current_revision') is False:
        raise agent.AgentEntryError('article_revision_stale' if is_article else 'editorial_revision_stale',
                                    'Select the current author revision, not an old accepted copy')
    ready = all(status.get(k) for k in ('checks_complete','required_issues_closed',
                'preparation_complete','purpose_continuity_complete','facet_realization_complete',
                'plain_language_complete','observations_complete'))
    if not ready:
        action(primary_entry, '实际检查或修改未完成项，再写入同版编辑证据；有效旧项可复用。',
            cmd('review-integrity','record','--revision',refs['author_revision'],'--input','<current-editorial-review.json>'),
            guide, ['current_editorial_checks_and_required_issue_resolution'])
        return
    package = dict(draft=dict(path=str(draft),sha256=revision['draft_ref']['sha256']),
        revision=request['current']['author_revision'], topic=context['topic_selection'],
        content_format=result['content_format'], platform=result['platform'],
        editorial=status, published=False, final_media_verified=False)
    if topic_facets is not None:
        package['topic_facets'] = copy.deepcopy(topic_facets)
    if 'plain_language_guidance' in (result.get('writing_handoff') or {}):
        package['plain_language_guidance'] = copy.deepcopy(result['writing_handoff']['plain_language_guidance'])
    if is_article:
        package['remaining_steps'] = ['platform_layout','rendered_output_review','manual_publication']
        result['article_review_package'] = package
        action(primary_entry, '当前稿编辑证据已核验，作者决定单独保留；不把审核包当成最终成品。',
            cmd('review-integrity','check','--revision',refs['author_revision'],'--require-complete'), guide)
        if not status.get('author_confirmation_recorded'):
            result['status'] = 'awaiting_author'
            result['next_action'] = dict(kind='human_review', selected_not_executed=True,
                reason='Review this exact draft; do not create an author confirmation on their behalf.',
                draft=str(draft), revision=str(refs['author_revision']))
            result['article_review_package']['remaining_steps'].insert(0,'author_decision')
        import article_delivery
        article_delivery.select_next(agent, request, refs, result, action, cmd)
    else:
        result['draft_review_package'] = package
        if not status.get('author_confirmation_recorded'):
            action(primary_entry, '当前稿编辑证据已核验，作者决定单独保留；不把审核包当成最终成品。',
                cmd('review-integrity','check','--revision',refs['author_revision'],'--require-complete'), guide)
            result['status'] = 'awaiting_author'
            result['next_action'] = dict(kind='human_review', selected_not_executed=True,
                reason='Review this exact draft; do not create an author confirmation on their behalf.',
                draft=str(draft), revision=str(refs['author_revision']))
        else:
            action(primary_entry, '当前稿编辑与作者确认已绑定，可进入后续制作或发布台；不自动渲染或发布。',
                cmd('review-integrity','check','--revision',refs['author_revision'],'--require-complete'), guide)


def article_next(agent, request, refs, result, action, cmd, pre_gate=None):
    """Read existing author records and select one consumer, without a new store."""
    return _editorial_author_chain(
        agent, request, refs, result, action, cmd,
        primary_entry='article_editorial',
        guide='docs/article-editorial-connection.md',
        is_article=True,
        pre_gate=pre_gate,
    )


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
        return runtime_paths.managed_self_argv(ROOT, 'scripts/self_media_agent.py', *args)

    def _compute_gate_signals():
        risk_flags = dict(request.get('risk_flags') or {})
        trusted_domains = set()
        for dom_src in (
            (docs.get('creation_context') or {}).get('topic_domain'),
            (docs.get('context_manifest') or {}).get('editorial_context', {}).get('topic_domain'),
            request.get('topic_domain'),
            (docs.get('fact_card') or {}).get('domain'),
        ):
            if isinstance(dom_src, str) and dom_src.strip():
                trusted_domains.add(dom_src.strip())
        # Explicit false flags cannot override risks indicated by a bound context.
        if 'case' in trusted_domains or risk_flags.get('customer_case') is True:
            risk_flags['customer_case'] = True
        if 'insurance' in trusted_domains or risk_flags.get('insurance_terms') is True:
            risk_flags['insurance_terms'] = True
        if ({'medical', 'health'} & trusted_domains) or risk_flags.get('medical_claims') is True:
            risk_flags['medical_claims'] = True
        serious_domains = {'insurance', 'medical', 'health', 'science', 'finance'}
        science_domains = {'medical', 'health', 'science'}
        has_production_artifact = any(
            k in refs for k in (
                'author_revision', 'article_item', 'article_render_manifest',
                'delivery_manifest', 'publication_data', 'package_receipt', 'rough_cut_delivery',
            )
        )
        has_drafting_artifact = has_production_artifact or ('author_context' in refs) or ('topic_decision' in refs)
        explicit_pl_refs = any(
            k in refs for k in (
                'plain_language_plan', 'plain_language_review', 'translation_review', 'clause_explanation',
            )
        )
        serious_professional = bool(
            risk_flags.get('serious_professional') is True
            or risk_flags.get('insurance_terms') is True
            or (trusted_domains & serious_domains)
        )
        science_claims = bool(
            risk_flags.get('science_claims') is True
            or (trusted_domains & science_domains)
            or (
                isinstance(docs.get('science_review'), dict)
                and docs['science_review'].get('schema_version') == 'science-popularization-review.v1'
            )
        )
        active_pl_scope = (kind in CREATIVE) or ('fact_card' in refs) or explicit_pl_refs or has_production_artifact
        needs_fact_lock = active_pl_scope and bool(
            risk_flags.get('fact_confirmation_required') is True
            or risk_flags.get('requires_plain_language') is True
            or serious_professional
            or science_claims
            or ('fact_card' in refs)
            or explicit_pl_refs
            or (has_drafting_artifact and risk_flags.get('medical_claims') is True)
        )
        needs_plain_language = active_pl_scope and bool(
            risk_flags.get('requires_plain_language') is True
            or serious_professional
            or science_claims
            or explicit_pl_refs
            or (has_drafting_artifact and risk_flags.get('medical_claims') is True)
        )
        return dict(
            risk_flags=risk_flags,
            trusted_domains=trusted_domains,
            has_production_artifact=has_production_artifact,
            has_drafting_artifact=has_drafting_artifact,
            serious_professional=serious_professional,
            science_claims=science_claims,
            needs_fact_lock=needs_fact_lock,
            needs_plain_language=needs_plain_language,
        )

    def _collect_consumer_surfaces(pl_gate):
        surfaces = {}
        if 'article_item' in docs:
            item = docs['article_item']
            bits = [item.get('title', '')]
            comp = item.get('composition') or {}
            if isinstance(comp.get('canonical_body'), str):
                bits.append(comp['canonical_body'])
            for ch in (item.get('channels') or {}).values():
                if isinstance(ch, dict):
                    bits.extend([ch.get('title', ''), ch.get('hook', ''), ch.get('cta', ''), ch.get('body', '')])
            joined = '\n'.join(str(b).strip() for b in bits if isinstance(b, str) and b.strip())
            if joined:
                surfaces['article_item'] = joined
        if 'publication_data' in docs:
            pdata = docs['publication_data']
            pbits = []
            for it in pdata.get('items') or []:
                if isinstance(it, dict):
                    pbits.append(str(it.get('title', '')))
                    for p in (it.get('platforms') or {}).values():
                        if isinstance(p, dict):
                            pbits.extend(str(p.get(k, '')) for k in ('title', 'caption', 'description', 'body', 'opening_text'))
                    for card in (it.get('graphic_cards') or it.get('cards') or []):
                        if isinstance(card, dict):
                            pbits.extend(str(card.get(k, '')) for k in ('title', 'text', 'caption', 'headline'))
            joined_pub = '\n'.join(b.strip() for b in pbits if isinstance(b, str) and b.strip())
            if joined_pub:
                surfaces['publication_data'] = joined_pub
        if 'delivery_manifest' in docs:
            dm = docs['delivery_manifest']
            import cover_workbench as covers
            dbits = []
            sub_cfg = dm.get('subtitles') or {}
            if isinstance(sub_cfg.get('pack_ref'), dict) and sub_cfg['pack_ref'].get('path'):
                try:
                    pack = covers.read(covers.bound(sub_cfg['pack_ref']))
                    dbits.extend(str(c.get('text', '')) for row in pack.get('requests', []) for c in row.get('subtitle_cues', []))
                except Exception:
                    pass
            if isinstance(sub_cfg.get('render_file_ref'), dict) and sub_cfg['render_file_ref'].get('path'):
                try:
                    dbits.append(pl_gate._extract_surface_text(covers.bound(sub_cfg['render_file_ref'])))
                except Exception:
                    pass
            if isinstance(dm.get('cover_review_ref'), dict) and dm['cover_review_ref'].get('path'):
                try:
                    cov = covers.read(covers.bound(dm['cover_review_ref']))
                    dbits.extend(str(cov.get(k, '')) for k in ('title', 'headline') if cov.get(k))
                except Exception:
                    pass
            joined_dm = '\n'.join(b.strip() for b in dbits if isinstance(b, str) and b.strip())
            if joined_dm:
                surfaces['delivery_manifest'] = joined_dm
        return surfaces

    def _evaluate_pre_draft_handoff():
        import plain_language_gate as pl_gate
        sig = _compute_gate_signals()
        state = {
            'needs_fact_lock': sig['needs_fact_lock'],
            'needs_plain_language': sig['needs_plain_language'],
            'plan_applicable': False,
            'fact_card_ok': False,
            'fact_card_doc': None,
            'plan_doc': None,
        }
        ctx_editorial = (docs.get('context_manifest') or {}).get('editorial_context') or {}
        cid = ctx_editorial.get('content_id') or (docs.get('fact_card') or {}).get('content_id') or request['request_id']
        topic_text = ((ctx_editorial.get('topic_selection') or {}).get('topic') or request.get('selection_basis') or '')
        audience_text = ((ctx_editorial.get('audience_source') or {}).get('quote') or '')
        purpose_text = ((ctx_editorial.get('purpose_source') or {}).get('quote') or '')
        if 'fact_card' in refs or sig['needs_fact_lock']:
            fc_doc = docs.get('fact_card')
            err_msg = None
            if 'fact_card' in refs:
                try:
                    fc_doc, fc_meta = pl_gate.validate_fact_card_lock(
                        refs['fact_card'],
                        expected_content_id=ctx_editorial.get('content_id'),
                        expected_sha256=current['fact_card']['sha256'],
                    )
                    state['fact_card_ok'] = True
                    state['fact_card_doc'] = fc_doc
                    result['fact_card_status'] = {'status': 'locked_for_draft', **fc_meta}
                except pl_gate.PlainLanguageError as error:
                    err_msg = str(error)
                    result['fact_card_status'] = {'status': 'blocked', 'code': error.code, 'message': err_msg}
            else:
                result['fact_card_status'] = {'status': 'missing', 'code': 'fact_card_missing'}
            if not state['fact_card_ok']:
                result['fact_confirmation_checklist'] = pl_gate.build_fact_confirmation_checklist(
                    content_id=str(cid),
                    topic=str(topic_text),
                    audience=str(audience_text),
                    purpose=str(purpose_text),
                    fact_card=fc_doc,
                    fact_card_path=refs.get('fact_card'),
                    risk_flags=sig['risk_flags'],
                    error_reason=err_msg,
                )
        if 'plain_language_plan' in refs:
            try:
                plan_doc, fc_from_plan = pl_gate.validate_plan(
                    docs['plain_language_plan'],
                    expected_request_id=request['request_id'],
                    expected_content_id=ctx_editorial.get('content_id'),
                    risk_flags=sig['risk_flags'],
                    trusted_domains=sig['trusted_domains'],
                    base_dir=refs['plain_language_plan'].parent,
                )
                state['plan_doc'] = plan_doc
                if plan_doc.get('applicability') == 'applicable':
                    state['plan_applicable'] = True
                    guidance = pl_gate.build_writing_guidance(plan_doc, state['fact_card_doc'] or fc_from_plan)
                    handoff = result.setdefault('writing_handoff', {})
                    handoff['plain_language_guidance'] = guidance
                    if 'fact_card' in current:
                        handoff['fact_card_ref'] = copy.deepcopy(current['fact_card'])
                    handoff['plain_language_plan_ref'] = copy.deepcopy(current['plain_language_plan'])
            except pl_gate.PlainLanguageError:
                pass
        return state

    def finish():
        import plain_language_gate as pl_gate
        import serious_content_translation_gate as trans_gate

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

        sig = _compute_gate_signals()
        risk_flags = sig['risk_flags']
        trusted_domains = sig['trusted_domains']
        has_production_artifact = sig['has_production_artifact']
        expected_proj = (
            result.get('project_id')
            or request.get('project_id')
            or (docs.get('creation_context') or {}).get('project_id')
        )
        expected_req_id = request.get('request_id')
        editorial_ctx = result.get('editorial_context') or {}
        expected_content_id = editorial_ctx.get('content_id')

        def risk_review_ok(doc, allowed_decisions):
            if not isinstance(doc, dict):
                return False
            # Require an explicit decision field; generic display or pipeline status cannot pass.
            decision = doc.get('decision')
            if not isinstance(decision, str) or decision not in allowed_decisions:
                return False
            # Require at least one explicit binding (request_id or project_id) to prevent cross-project reuse.
            doc_proj = doc.get('project_id')
            doc_req_id = doc.get('request_id')
            has_proj = isinstance(doc_proj, str) and bool(doc_proj.strip())
            has_req = isinstance(doc_req_id, str) and bool(doc_req_id.strip())
            if not has_proj and not has_req:
                return False
            if has_proj and (not expected_proj or doc_proj != expected_proj):
                return False
            if has_req and (not expected_req_id or doc_req_id != expected_req_id):
                return False
            return True

        current_body_ref = (
            (result.get('article_review_package') or {}).get('draft')
            or (result.get('draft_review_package') or {}).get('draft')
            or editorial_ctx.get('current_body')
            or (docs.get('author_revision') or {}).get('draft_ref')
        )
        current_body_path = None
        current_body_sha = None
        if isinstance(current_body_ref, dict) and current_body_ref.get('path'):
            try:
                current_body_path = pl_gate.resolve_artifact_path(current_body_ref['path'], base_dir=ROOT)
                current_body_sha = current_body_ref.get('sha256')
            except pl_gate.PlainLanguageError:
                current_body_path = None

        diagnostics = []
        gate_missing = []

        def _add_gate_missing(code):
            if code not in gate_missing:
                gate_missing.append(code)

        # 1. Fact card confirmation checklist & lock
        fc_doc = None
        fc_locked = False
        if 'fact_card' in refs or sig['needs_fact_lock']:
            err_reason = None
            if 'fact_card' in refs:
                try:
                    fc_doc, fc_meta = pl_gate.validate_fact_card_lock(
                        refs['fact_card'],
                        expected_content_id=expected_content_id,
                        expected_sha256=current['fact_card']['sha256'],
                    )
                    fc_locked = True
                    result['fact_card_status'] = {'status': 'locked_for_draft', **fc_meta}
                except pl_gate.PlainLanguageError as error:
                    err_reason = str(error)
                    result['fact_card_status'] = {'status': 'blocked', 'code': error.code, 'message': err_reason}
                    diagnostics.append({'gate': 'fact_card', 'code': error.code, 'message': err_reason})
                    _add_gate_missing('locked_fact_card_for_draft')
            else:
                result['fact_card_status'] = {'status': 'missing', 'code': 'fact_card_missing'}
                _add_gate_missing('locked_fact_card_for_draft')
            if not fc_locked:
                topic_text = ((editorial_ctx.get('topic_selection') or {}).get('topic') or request.get('selection_basis') or '')
                audience_text = ((editorial_ctx.get('audience_source') or {}).get('quote') or '')
                purpose_text = ((editorial_ctx.get('purpose_source') or {}).get('quote') or '')
                result['fact_confirmation_checklist'] = pl_gate.build_fact_confirmation_checklist(
                    content_id=str(expected_content_id or (docs.get('fact_card') or {}).get('content_id') or request['request_id']),
                    topic=str(topic_text),
                    audience=str(audience_text),
                    purpose=str(purpose_text),
                    fact_card=fc_doc or docs.get('fact_card'),
                    fact_card_path=refs.get('fact_card'),
                    risk_flags=risk_flags,
                    error_reason=err_reason,
                )

        # 2. Pre-draft plain-language plan
        valid_plan = None
        pl_status = {}
        if 'plain_language_plan' in refs or sig['needs_plain_language']:
            if 'plain_language_plan' in refs:
                try:
                    valid_plan, fc_from_plan = pl_gate.validate_plan(
                        docs['plain_language_plan'],
                        expected_request_id=request['request_id'],
                        expected_content_id=expected_content_id,
                        risk_flags=risk_flags,
                        trusted_domains=trusted_domains,
                        base_dir=refs['plain_language_plan'].parent,
                    )
                    pl_status['plan'] = 'passed'
                    pl_status['applicability'] = valid_plan['applicability']
                    if valid_plan['applicability'] == 'applicable':
                        guidance = pl_gate.build_writing_guidance(valid_plan, fc_doc or fc_from_plan)
                        handoff = result.setdefault('writing_handoff', {})
                        handoff['plain_language_guidance'] = guidance
                        if 'fact_card' in current:
                            handoff['fact_card_ref'] = copy.deepcopy(current['fact_card'])
                        handoff['plain_language_plan_ref'] = copy.deepcopy(current['plain_language_plan'])
                except pl_gate.PlainLanguageError as error:
                    pl_status['plan'] = 'blocked'
                    diagnostics.append({'gate': 'plain_language_plan', 'code': error.code, 'message': str(error)})
                    _add_gate_missing('plain_language_plan')
            else:
                pl_status['plan'] = 'missing'
                _add_gate_missing('plain_language_plan')

        # 3. Legacy + formal risk gates
        active_risk_gates = []
        if risk_flags.get('medical_claims') is True or sig['science_claims']:
            active_risk_gates.append('science_popularization_review')
            sci_doc = docs.get('science_review')
            if isinstance(sci_doc, dict) and sci_doc.get('schema_version') == 'science-popularization-review.v1':
                try:
                    pl_gate.validate_formal_science_review(
                        refs['science_review'],
                        expected_content_id=expected_content_id,
                        expected_body_path=current_body_path if has_production_artifact else None,
                        expected_body_sha256=current_body_sha if (has_production_artifact and current_body_path is None) else None,
                    )
                    result['risk_review_verification_level'] = 'formal_schema_verified'
                except pl_gate.PlainLanguageError as error:
                    diagnostics.append({'gate': 'science_popularization_review', 'code': error.code, 'message': str(error)})
                    _add_gate_missing('science_popularization_review')
                    _add_gate_missing('formal_science_popularization_review')
            elif has_production_artifact or sig['science_claims'] or sig['serious_professional'] or risk_flags.get('requires_plain_language') is True:
                _add_gate_missing('formal_science_popularization_review')
                if not risk_review_ok(sci_doc, {'approved', 'pass', 'passed'}):
                    _add_gate_missing('science_popularization_review')
            else:
                result.setdefault('risk_review_verification_level', 'pre_draft_binding_only')
                if not risk_review_ok(sci_doc, {'approved', 'pass', 'passed'}):
                    _add_gate_missing('science_popularization_review')
        if risk_flags.get('customer_case') is True or risk_flags.get('minor_subject') is True:
            active_risk_gates.append('privacy_treatment_review')
            if not risk_review_ok(docs.get('privacy_review'), {'approved', 'pass', 'passed', 'not_applicable'}):
                _add_gate_missing('privacy_treatment_review')
        if risk_flags.get('third_party_copyright') is True:
            active_risk_gates.append('rights_authorization_review')
            if not risk_review_ok(docs.get('rights_review'), {'approved', 'pass', 'passed'}):
                _add_gate_missing('rights_authorization_review')
        if risk_flags.get('insurance_terms') is True:
            active_risk_gates.append('insurance_compliance_disclosure')
            if not risk_review_ok(docs.get('insurance_review'), {'approved', 'pass', 'passed'}):
                _add_gate_missing('insurance_compliance_review')

        # 4. Serious content translation gate (precheck before draft; full review on draft/production)
        if sig['serious_professional'] or 'translation_review' in refs:
            active_risk_gates.append('serious_content_translation_review')
            trans_doc = docs.get('translation_review')
            if 'translation_review' not in refs:
                _add_gate_missing('serious_content_translation_review')
                pl_status['translation'] = 'missing'
            elif isinstance(trans_doc, dict) and trans_doc.get('schema_version') == 'serious-content-translation-precheck.v1':
                if has_production_artifact:
                    pl_status['translation'] = 'blocked'
                    diagnostics.append({'gate': 'serious_content_translation_review', 'code': 'translation_postcreative_required', 'message': '草稿/交付阶段不能只提供写前 precheck，必须提供完整的 serious-content-translation-review.v1'})
                    _add_gate_missing('serious_content_translation_review')
                else:
                    try:
                        trans_gate.validate_precheck_receipt(refs['translation_review'])
                        if expected_content_id and trans_doc.get('content_id') != expected_content_id:
                            raise ValueError('translation precheck content_id mismatch')
                        pl_status['translation'] = 'precheck_passed'
                    except Exception as error:
                        pl_status['translation'] = 'blocked'
                        diagnostics.append({'gate': 'serious_content_translation_review', 'code': getattr(error, 'code', 'translation_precheck_invalid'), 'message': str(error)})
                        _add_gate_missing('serious_content_translation_review')
            else:
                try:
                    pl_gate.validate_formal_translation_review(
                        refs['translation_review'],
                        expected_content_id=expected_content_id,
                        expected_body_path=current_body_path if has_production_artifact else None,
                        expected_body_sha256=current_body_sha if (has_production_artifact and current_body_path is None) else None,
                        expected_plan=valid_plan,
                    )
                    pl_status['translation'] = 'passed'
                except pl_gate.PlainLanguageError as error:
                    pl_status['translation'] = 'blocked'
                    diagnostics.append({'gate': 'serious_content_translation_review', 'code': error.code, 'message': str(error)})
                    _add_gate_missing('serious_content_translation_review')

        # 5. Post-draft plain-language review & multi-surface cross-check
        plan_explicit_na = isinstance(valid_plan, dict) and valid_plan.get('applicability') == 'not_applicable'
        requires_pl_review = ('plain_language_review' in refs) or (
            has_production_artifact and (sig['needs_plain_language'] or 'plain_language_plan' in refs) and not plan_explicit_na
        )
        if requires_pl_review:
            active_risk_gates.append('plain_language_review')
            if 'plain_language_review' not in refs:
                pl_status['review'] = 'missing'
                _add_gate_missing('plain_language_review')
            else:
                extra_surfaces = _collect_consumer_surfaces(pl_gate)
                try:
                    pl_gate.validate_review(
                        docs['plain_language_review'],
                        expected_request_id=request['request_id'],
                        expected_content_id=expected_content_id,
                        expected_body_path=current_body_path,
                        expected_body_sha256=None if current_body_path is not None else current_body_sha,
                        expected_plan_ref=current.get('plain_language_plan'),
                        expected_fact_card_ref=current.get('fact_card'),
                        extra_surface_texts=extra_surfaces,
                        base_dir=refs['plain_language_review'].parent,
                        require_passed=True,
                    )
                    pl_status['review'] = 'passed'
                    result['plain_language_review_findings'] = []
                except pl_gate.PlainLanguageError as error:
                    pl_status['review'] = 'blocked'
                    result['plain_language_review_findings'] = error.details or [{'code': error.code, 'message': str(error)}]
                    diagnostics.append({'gate': 'plain_language_review', 'code': error.code, 'message': str(error)})
                    _add_gate_missing('plain_language_review')

        # 6. Insurance clause explanation validation
        if 'clause_explanation' in refs or (has_production_artifact and risk_flags.get('insurance_terms') is True and 'insurance' in trusted_domains):
            active_risk_gates.append('insurance_clause_explanation_review')
            if 'clause_explanation' not in refs:
                _add_gate_missing('insurance_clause_explanation_review')
            else:
                cdoc = docs['clause_explanation']
                if isinstance(cdoc, dict) and cdoc.get('applicability') == 'not_applicable':
                    if not isinstance(cdoc.get('reason'), str) or not cdoc['reason'].strip():
                        diagnostics.append({'gate': 'clause_explanation', 'code': 'clause_explanation_reason_missing', 'message': 'not_applicable 必须填写 reason'})
                        _add_gate_missing('insurance_clause_explanation_review')
                else:
                    clause_errs = pl_gate.validate_clause_explanation(refs['clause_explanation'])
                    if clause_errs:
                        diagnostics.append({'gate': 'clause_explanation', 'code': 'clause_explanation_semantic_error', 'message': '; '.join(clause_errs)})
                        _add_gate_missing('insurance_clause_explanation_review')

        for item in gate_missing:
            if item not in result['missing_inputs']:
                result['missing_inputs'].append(item)
        if pl_status:
            result['plain_language_status'] = pl_status
        if diagnostics:
            result['plain_language_diagnostics'] = diagnostics

        if result.get('primary_entry') in {'creation_route', 'travel_experience', 'canonical_format_adapter', 'video_delivery', 'video_review', 'rough_cut_post_check', 'publication_desk'} and result.get('workflow_goal') is None:
            completed_stages = []
            pre_draft_blockers = {'locked_fact_card_for_draft', 'plain_language_plan'}
            post_draft_blockers = {
                'locked_fact_card_for_draft', 'plain_language_plan', 'plain_language_review',
                'serious_content_translation_review', 'science_popularization_review',
                'formal_science_popularization_review', 'insurance_compliance_review',
                'insurance_clause_explanation_review', 'privacy_treatment_review', 'rights_authorization_review',
            }
            if 'context_manifest' in refs and 'creation_decision' in refs and not (pre_draft_blockers & set(result['missing_inputs'])):
                completed_stages.append('stage_1_charter')
            editorial_status = result.get('editorial_status')
            stage_2_artifact_present = ('author_revision' in refs) or ('rough_cut_delivery' in refs and 'rough_cut_acceptance' in refs)
            if 'author_revision' in refs and editorial_status is not None:
                stage_2_verified = (editorial_status.get('may_advance') is True) and not (post_draft_blockers & set(result['missing_inputs']))
                stage_2_detail = {
                    'status': 'completed' if stage_2_verified else 'pending_review',
                    'artifact_present': True,
                    'verified': stage_2_verified,
                }
            elif 'author_revision' in refs and result.get('writing_handoff') is not None:
                stage_2_verified = False
                stage_2_detail = {
                    'status': 'pending_review',
                    'artifact_present': True,
                    'verified': False,
                }
            else:
                stage_2_verified = stage_2_artifact_present and not (post_draft_blockers & set(result['missing_inputs']))
                stage_2_detail = {'status': 'completed' if stage_2_verified else 'pending'}
            if stage_2_verified:
                completed_stages.append('stage_2_production')

            stage_3_artifact_present = ('delivery_manifest' in refs) or ('publication_page_build' in refs)
            stage_3_verified = False
            stage_3_reason = None
            if 'delivery_manifest' in refs:
                m = docs.get('delivery_manifest') or {}
                try:
                    import cover_workbench as covers
                    import video_delivery
                    if not isinstance(m, dict) or m.get('schema') != 'self-media.video-delivery.v1':
                        raise ValueError('invalid_delivery_manifest_schema')
                    acc_ref = m.get('acceptance_ref')
                    render_refs = ([m['render_receipt_ref']] if m.get('render_receipt_ref') else []) + list(m.get('render_chain_refs') or [])
                    if not isinstance(acc_ref, dict) or not render_refs or not all(isinstance(r, dict) for r in render_refs):
                        raise ValueError('delivery_acceptance_or_render_ref_missing')
                    for r in render_refs:
                        covers.bound(r)
                    acc_path = covers.bound(acc_ref)
                    acc_doc = covers.read(acc_path)
                    expected_fp = video_delivery.acceptance_fingerprint(m)
                    if (
                        not isinstance(acc_doc, dict)
                        or acc_doc.get('schema') != 'self-media.video-acceptance.v1'
                        or acc_doc.get('reviewer_kind') != 'human'
                        or acc_doc.get('decision') != 'pass'
                        or not str(acc_doc.get('reviewer', '')).strip()
                        or not str(acc_doc.get('reviewed_at', '')).strip()
                        or acc_doc.get('input_fingerprint') != expected_fp
                    ):
                        raise ValueError('delivery_acceptance_unverified_or_fingerprint_mismatch')
                    if post_draft_blockers & set(result['missing_inputs']):
                        raise ValueError('plain_language_or_risk_gates_blocked')
                    stage_3_verified = True
                except (ValueError, KeyError, TypeError, OSError, json.JSONDecodeError) as err:
                    stage_3_verified = False
                    stage_3_reason = str(err)
            elif 'publication_page_build' in refs:
                b = docs.get('publication_page_build') or {}
                try:
                    import cover_workbench as covers
                    import publication_desk as desk
                    if not isinstance(b, dict) or b.get('schema_version') != 'self-media.publication-page-build.v1':
                        raise ValueError('invalid_publication_page_build_schema')
                    page_ref = b.get('page_ref')
                    if not isinstance(page_ref, dict):
                        raise ValueError('publication_page_ref_missing')
                    if 'publication_data' in refs:
                        if result.get('page_build', {}).get('status') == 'stale':
                            raise ValueError('publication_page_build_stale')
                        desk.verify_page_build(refs['publication_data'], refs['publication_page_build'])
                    page_p = covers.bound(page_ref)
                    content = page_p.read_text(encoding='utf-8')
                    if 'data-state="verified_at_generation"' not in content or 'data-state="draft"' in content:
                        raise ValueError('publication_page_not_verified_at_generation')
                    if post_draft_blockers & set(result['missing_inputs']):
                        raise ValueError('plain_language_or_risk_gates_blocked')
                    stage_3_verified = True
                except (ValueError, KeyError, TypeError, OSError, json.JSONDecodeError) as err:
                    stage_3_verified = False
                    stage_3_reason = str(err)

            if stage_3_verified:
                completed_stages.append('stage_3_final_audit')

            all_stages = ['stage_1_charter', 'stage_2_production', 'stage_3_final_audit', 'stage_4_manual_publish']
            current_stage = next((s for s in all_stages if s not in completed_stages), 'stage_4_manual_publish')
            stage_entrypoints = {
                'stage_1_charter': runtime_paths.managed_self_argv(ROOT, 'scripts/self_media_agent.py', 'creation-route'),
                'stage_2_production': (
                    runtime_paths.managed_self_argv(ROOT, 'scripts/self_media_agent.py', 'authoring')
                    if kind == 'script'
                    else runtime_paths.managed_self_argv(ROOT, 'scripts/self_media_agent.py', 'video-review', 'post-cut', '--help')
                ),
                'stage_3_final_audit': runtime_paths.managed_self_argv(ROOT, 'scripts/self_media_agent.py', 'video-delivery'),
                'stage_4_manual_publish': runtime_paths.managed_self_argv(ROOT, 'scripts/publication_desk.py', 'render', '--help'),
            }
            stage_3_detail = {
                'status': 'completed' if 'stage_3_final_audit' in completed_stages else ('pending_review' if stage_3_artifact_present else 'pending'),
                'artifact_present': stage_3_artifact_present,
                'verified': stage_3_verified,
            }
            if stage_3_reason and not stage_3_verified:
                stage_3_detail['reason'] = stage_3_reason
            stage_details = {
                'stage_1_charter': {'status': 'completed' if 'stage_1_charter' in completed_stages else 'pending'},
                'stage_2_production': stage_2_detail,
                'stage_3_final_audit': stage_3_detail,
                'stage_4_manual_publish': {'status': 'completed' if 'stage_4_manual_publish' in completed_stages else 'pending'},
            }
            lightweight = {
                'mode': 'four_stage_general',
                'stages': all_stages,
                'completed_stages': completed_stages,
                'current_stage': current_stage,
                'stage_details': stage_details,
                'next_stage_command': stage_entrypoints[current_stage],
                'stage_entrypoints': stage_entrypoints,
                'publication_mode': 'manual_fill_via_publication_desk_only',
                'active_risk_gates': list(dict.fromkeys(active_risk_gates)),
            }
            if (result.get('writing_handoff') or {}).get('topic_facets') is not None:
                lightweight['topic_facets_bound'] = True
            if (result.get('writing_handoff') or {}).get('plain_language_guidance') is not None:
                lightweight['plain_language_guidance_bound'] = True
            result['lightweight_workflow'] = lightweight
        elif active_risk_gates:
            result['active_risk_gates'] = list(dict.fromkeys(active_risk_gates))
        if result['missing_inputs']:
            result['status'] = 'needs_context'
        result['payload_sha256']=agent.sha256_value(result)
        return result

    pre_gate_state = _evaluate_pre_draft_handoff()

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
    # Final routing may not infer that rough-cut review happened from a later artifact.
    final_manifest = docs.get("delivery_manifest") if kind == "finished_video" else None
    if kind == "fine_cut_review" or final_manifest is not None or (
            kind == "finished_video" and "rough_cut_delivery" in docs):
        import rough_cut_checks as checks
        current_review = docs.get("review_request", {})
        registration = current.get("rough_cut_delivery")
        acceptance = current.get("rough_cut_acceptance")
        candidate = current_review.get("rough_cut_candidate")
        if final_manifest is not None:
            registration = final_manifest.get("rough_cut_delivery_ref") or registration
            acceptance = final_manifest.get("rough_cut_acceptance_ref") or acceptance
            candidate = final_manifest.get("edited_media")
            for key, value in (("rough_cut_delivery", registration), ("rough_cut_acceptance", acceptance)):
                if key in current and current[key] != value:
                    raise agent.AgentEntryError("rough_cut_binding_conflict", key)
        if not registration:
            action("rough_cut_post_check", "缺当前粗剪登记。用实际导出的媒体、定稿和时间表恢复复核。",
                   cmd("video-review", "post-cut", "--candidate", "<current-rough-cut>",
                       "--timeline", "<current-timeline>", "--script", "<approved-script>",
                       "--identity", "<current-project-identity.json>", "--output-dir", "<new-review-dir>", "--serve", "--open"),
                   "docs/source-time-range-review.md", ["rough_cut_delivery"])
            return finish()
        try:
            registered = checks.registration(registration)
            if candidate is None and (final_manifest is not None or current_review):
                raise ValueError("rough_cut_current_candidate_required")
            if candidate is not None and candidate != registered["candidate"]:
                raise ValueError("rough_cut_registration_candidate_mismatch")
            if not acceptance:
                action("rough_cut_post_check", "当前粗剪还需要 VKP 对稿、技术检查与疑点处理。",
                       cmd("video-review", "post-cut", "--registration", registration["path"],
                           "--candidate", registered["candidate"]["path"], "--timeline", registered["timeline_map"]["path"],
                           "--script", ((final_manifest or {}).get("script_ref") or {}).get("path", "<approved-script>"),
                           "--identity", "<current-project-identity.json>", "--output-dir", "<new-review-dir>", "--serve", "--open"),
                       "docs/source-time-range-review.md", ["rough_cut_acceptance"])
                return finish()
            if kind == "fine_cut_review" and current_review:
                checks.check_fine_request(current_review, refs["review_request"], registration, acceptance)
            else:
                checks.require_current(registration, acceptance, candidate=candidate,
                                       script=(final_manifest or {}).get("script_ref"),
                                       timeline=(final_manifest or {}).get("timeline"))
        except (ValueError, OSError, TypeError, KeyError) as exc:
            raise agent.AgentEntryError("rough_cut_check_blocked", str(exc)) from exc
        if final_manifest is not None and (not final_manifest.get("rough_cut_delivery_ref") or
                                           not final_manifest.get("rough_cut_acceptance_ref")):
            action("video_delivery", "把当前粗剪和复核回执绑定到交付清单，供成片入口再次校验。",
                   cmd("video-delivery", "rough-cut-bind", "--input", refs["delivery_manifest"],
                       "--rough-cut-delivery", registration["path"], "--rough-cut-acceptance", acceptance["path"],
                       "--output", "<new-delivery-manifest.json>"),
                   "docs/source-time-range-review.md", ["delivery_manifest_rough_cut_binding"])
            return finish()
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
        argv=[sys.executable,wrapper,'select-delivery','--plan',str(refs.get('spoken_edit_plan','<spoken-edit-plan.json>')),
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
                cmd('video-review','prepare','--purpose',purpose,'--request',refs['review_request'],'--output-dir','<new-review-dir>','--serve','--open',
                    *(['--rough-cut-delivery',registration['path'],'--rough-cut-acceptance',acceptance['path']]
                      if kind=='fine_cut_review' else [])),
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
            argv=runtime_paths.managed_self_argv(ROOT,'scripts/publication_desk.py',operation,'--input',refs['publication_data'])
            argv+=['--output','<new-desk-data.json>'] if needs_upgrade else ['--stage','preparation']
            if page_stale and not needs_upgrade:
                argv=runtime_paths.managed_self_argv(ROOT,'scripts/publication_desk.py','render','--input',refs['publication_data'],'--output','<new-current-page.html>')
            elif 'publication_page_build' in refs and not needs_upgrade:
                argv+=['--page-build',str(refs['publication_page_build'])]
            action('publication_desk','先同步旧数据和当前生成页；有当前页面证据才检查发布准备。',argv,'docs/publication-desk.md')
            result['migration_required']=needs_upgrade or page_stale
            result['page_regeneration_required']=page_stale
        return finish()
    if kind=='cover_options' and 'cover_brief' in refs:
        action('covers','用已绑定的当前封面 brief 和目的要求进入原封面计划入口。',
            runtime_paths.managed_self_argv(ROOT,'scripts/cover_workbench.py','plan','--input',refs['cover_brief'],'--output','<new-cover-route-plan.json>'),
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
            runtime_paths.managed_self_argv(ROOT,'scripts/artifact_lifecycle.py','archive-policy','--help'),'docs/video-archive-levels.md')
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
            if any(item.get('kind')=='theory' for item in docs['topic_decision'].get('framework_decision',{}).get('facet_elements',[])):
                result['theory_grounding_hint'] = dict(
                    skills=['dbs-theory-grounding', 'dbs-standard-answer'],
                    runbook=str(ROOT.parent/'docs/content-creation-system/routing/skill-invocation-runbook.md'),
                    note='On-demand theory grounding / counterexample audit only; unverified primary origins stay supplement and never replace fact verification.',
                )
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
            topic_facets = (result.get('framework_decision') or {}).get('topic_facets')
            if topic_facets is not None:
                handoff = result.setdefault('writing_handoff', {})
                handoff.update(
                    topic_facets=copy.deepcopy(topic_facets),
                    topic_decision_ref=copy.deepcopy(current.get('topic_decision')),
                    note='Draft or plan Vlog from confirmed topic_facets; keep travel-experience workflow independent of case-story recipes.',
                )
            action('travel_experience','复用独立体验/Vlog工作单与现有素材工具；不冒充五条受管配方中的案例视频。',guide='docs/travel-experience-vlog-workflow.md')
            result['automatic_analysis_started']=False
        elif kind=='article':
            try:
                article_next(agent,request,refs,result,action,cmd,pre_gate=pre_gate_state)
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
            topic_facets = (result.get('framework_decision') or {}).get('topic_facets')
            if topic_facets is not None or 'author_context' in refs or 'author_revision' in refs:
                try:
                    _editorial_author_chain(
                        agent, request, refs, result, action, cmd,
                        primary_entry='canonical_format_adapter',
                        guide=str(ROOT.parent/'docs/content-creation-system/routing/format-adapter-playbooks.md'),
                        is_article=False,
                        pre_gate=pre_gate_state,
                    )
                except ValueError as error:
                    if isinstance(error, agent.AgentEntryError):
                        raise
                    raise agent.AgentEntryError(getattr(error, 'code', 'editorial_invalid'), str(error)) from error
                result['format_adapter']=by_format.get(content_format)
            else:
                action('canonical_format_adapter','使用既有文体适配与作者表达要求，不借用不适用的案例配方。',
                    guide=str(ROOT.parent/'docs/content-creation-system/routing/format-adapter-playbooks.md'),
                    missing=[] if content_format else ['content_format'])
                result['format_adapter']=by_format.get(content_format)
                if not content_format:
                    result['available_formats']=list(by_format)
        return finish()
    raise agent.AgentEntryError('entry_selection_unresolved',kind)
