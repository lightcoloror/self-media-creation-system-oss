"""Glue from existing author revisions to Content Studio; no writer or publisher."""
import argparse
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = (ROOT.parent/'docs').resolve().parent
VIEWS = {'desktop', 'mobile', 'mobile_dark'}


def adapter():
    registry = json.loads((WORKSPACE/'tool-registry.json').read_text(encoding='utf8'))
    path = Path(registry['tools']['content-creation-system']['editor_path'])/'scripts/wechat_article_format_adapter.py'
    spec = importlib.util.spec_from_file_location('article_delivery_formatter', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def require(ok, code):
    if not ok:
        raise ValueError(code)


def validate_schema(module, value, schema, label):
    try:
        module._validate_schema(value,schema,label)
    except module.AdapterBlocked as error:
        raise ValueError(str(error)) from error


def binding(selection):
    package = selection['article_review_package']
    return dict(request_id=selection['request_id'], entry_binding=selection['entry_binding'],
                draft_ref=package['draft'], platform=selection['platform'])


def prepare(request_path, output):
    import self_media_agent as agent
    request = agent.load_json(request_path)
    selection = agent.resolve_request(request)
    require('article_review_package' in selection, 'article_editorial_not_ready')
    require(selection['platform']=='wechat-article', 'article_renderer_not_available_for_platform')
    package = selection['article_review_package']
    draft = Path(package['draft']['path'])
    body = draft.read_text(encoding='utf8')
    title = body.splitlines()[0].removeprefix('# ').strip() if body else ''
    require(title and len(title)<=160, 'article_title_required')
    # Unknown review decisions stay unknown. This is the existing Content Studio contract.
    item = dict(schema_version='0.2', content_id=selection['editorial_context']['content_id'],
        title=title, primary_format='longform', status='review', tags=[],
        provenance=dict(sources=[],verified_facts=[],uncertainties=['Content gates require independent review.']),
        gates={k:dict(status='needs-review') for k in ('fact','privacy','compliance','rights')},
        intent=dict(topic=package['topic']['topic'], speaker_role='', audience=selection['editorial_context']['audience_source']['quote'],
                    content_object='article',desired_action='',risk_boundary='Review candidate; no publication authority.'),
        composition=dict(canonical_body=body.strip(),expression_mode='article',retention_mode='full-text',
                         voice_profile='existing-author-draft',semantic_reversibility=dict(status='not-checked')),
        channels=dict(wechat_article=dict(status='review',title=title,body_ref=str(draft),platform_metadata=binding(selection))),
        visual=dict(visual_profile='elegant-minimal',route='none',cognitive_anchors=[],assets=[],
                    render_recipe=dict(renderer='manual',output_format='html')),
        qa=dict(deterministic=[],human_review=dict(status='required')),
        publication=dict(boundary='manual-only',receipts=[]),
        feedback=dict(signal_status='not-observed',platform_signals={},business_signals={},learning_decision='none'))
    module = adapter()
    source = request.get('current',{}).get('article_source_item')
    if source:
        previous = agent.load_json(Path(source['path']))
        validate_schema(module,previous,module.CONTENT_SCHEMA,'source_content_item')
        require(agent.sha256_file(Path(source['path']))==source['sha256'],'article_source_item_drift')
        require(previous['content_id']==item['content_id'] and
                previous['composition'].get('canonical_body','').replace('\r\n','\n').strip()==body.strip(),
                'article_source_item_identity_or_body_drift')
        require(not previous['publication']['receipts'] and previous['status'] in {'draft','review'},'article_source_item_not_unpublished_draft')
        require(previous['qa']['human_review']['status']!='approved' or
                selection['article_editorial_status']['author_confirmation_recorded'],'article_source_author_approval_not_bound')
        # Preserve prior provenance, gates and author state; only adapt the exact body reference.
        previous.setdefault('channels',{})['wechat_article']=item['channels']['wechat_article']
        item=previous
    validate_schema(module,item,module.CONTENT_SCHEMA,'content_item')
    require(agent.sha256_file(draft)==package['draft']['sha256'],'article_draft_changed_during_prepare')
    output=Path(output)
    with output.open('x',encoding='utf8') as handle:
        json.dump(item,handle,ensure_ascii=False,indent=2)
    return dict(status='content_item_prepared',item=dict(path=str(output.resolve()),sha256=agent.sha256_file(output)),
                next_action='Review source/public-material declaration and gates; bind current.article_item. Do not mark author approved.',
                publication_authorized=False)


def rendered(module, item_path, manifest_path, selection):
    import self_media_agent as agent
    manifest = agent.load_json(manifest_path)
    package=selection['article_review_package']
    require(manifest.get('mode')=='public-review-candidate-only' and manifest.get('status')=='review-required', 'article_render_mode_mismatch')
    require(manifest.get('publication_boundary')=='manual-only' and manifest.get('publication_authorized') is False
            and manifest.get('remote_actions_performed') is False, 'article_render_boundary_mismatch')
    require(manifest.get('content_id')==selection['editorial_context']['content_id'] and
            manifest.get('input_markdown_sha256')==package['draft']['sha256'], 'article_render_input_drift')
    folder=Path(manifest_path).parent
    outputs=[]
    for suffix in ('body','preview','dark-preview'):
        receipt_path=folder/f'render-receipt-{suffix}.json'
        receipt=agent.load_json(receipt_path)
        validate_schema(module,receipt,module.RECEIPT_SCHEMA,'render_receipt')
        require(receipt['qa']['result']=='review-required' and all(c['status']=='pass' for c in receipt['qa']['hard_checks'])
                and receipt['source']['commit']==module.PINNED_SOURCE_COMMIT,'article_render_checks_incomplete')
        expected={f'artifact://content-item/{Path(item_path).name}':agent.sha256_file(item_path),
                  f'artifact://wechat-markdown/{Path(package["draft"]["path"]).name}':package['draft']['sha256']}
        require({r['ref']:r['sha256'] for r in receipt['inputs']}==expected, 'article_render_receipt_input_drift')
        require(receipt['content_id']==manifest['content_id'] and receipt['candidate_only'] is True
                and receipt['manual_only'] is True and receipt['renderer']=='wechat-inline-html', 'article_render_receipt_identity_mismatch')
        output=receipt['output']
        path=(folder/output['ref']).resolve()
        require(path.parent==folder.resolve() and path.name==f'wechat-article-{suffix}.html', 'article_render_path_invalid')
        require(agent.sha256_file(path)==output['sha256'], 'article_render_output_drift')
        require(output in manifest.get('outputs',[]), 'article_manifest_receipt_mismatch')
        outputs.append(dict(path=str(path),sha256=output['sha256']))
    require(len(manifest['outputs'])==3,'article_manifest_outputs_invalid')
    return outputs


def visual_review(path, manifest_ref, outputs):
    import self_media_agent as agent
    value=agent.load_json(path)
    require(value.get('render_manifest_ref')==manifest_ref,'article_visual_review_stale')
    views=value.get('views',[])
    require(len(views)==len(VIEWS) and {v.get('view') for v in views}==VIEWS,'article_visual_review_views_missing')
    for row in views:
        expected=outputs[2 if row['view']=='mobile_dark' else 1]
        require(row.get('artifact_ref')==expected,'article_visual_review_wrong_output')
        require(row.get('status')=='pass' and isinstance(row.get('observation'),str) and row['observation'].strip(),
                'article_visual_review_incomplete')
        shot=row.get('evidence_ref',{})
        require(set(shot)=={'path','sha256'} and agent.sha256_file(Path(shot['path']))==shot['sha256'],
                'article_visual_evidence_drift')
        from PIL import Image
        with Image.open(shot['path']) as image:
            image.verify()
    return dict(record_complete=True, human_device_verified=False,
                boundary='Hash-bound observations, not independent verification of visual judgment or device rendering.')


def select_next(agent, request, refs, result, action, cmd):
    package=result['article_review_package']
    guide='docs/article-editorial-connection.md'
    if result['platform']!='wechat-article':
        result['production_next_action']=dict(kind='read_existing_guide',path=str(ROOT/guide),
            selected_not_executed=True,reason='No registered renderer for this selected article platform; do not substitute WeChat or video.')
        if result['article_editorial_status']['author_confirmation_recorded']:
            action('article_layout','保留已选平台；尚无对应文章制作器，不切换平台。',guide=guide,missing=['platform_article_renderer'])
        return
    if 'article_item' not in refs:
        next_action=dict(kind='existing_cli',argv=cmd('article-delivery','prepare','--request','<current-work-request.json>',
            '--output','<new-content-item.json>'),selected_not_executed=True)
        result['production_next_action']=next_action
        if result['article_editorial_status']['author_confirmation_recorded']:
            action('article_layout','从同版稿件准备既有 Content Studio 对象；不自动填内容审核或作者决定。',next_action['argv'],guide)
        return
    module=adapter()
    item=agent.load_json(refs['article_item'])
    channel=item.get('channels',{}).get('wechat_article',{})
    require(channel.get('platform_metadata')==binding(result),'article_item_entry_binding_drift')
    require(item.get('content_id')==result['editorial_context']['content_id'],'article_item_identity_mismatch')
    require(item.get('qa',{}).get('human_review',{}).get('status')!='approved' or
            result['article_editorial_status']['author_confirmation_recorded'],'article_item_author_approval_not_bound')
    try:
        module._validate_item(item,refs['article_item'],Path(package['draft']['path']),'public-review')
        module._public_review_payload(Path(package['draft']['path']).read_text(encoding='utf8'),item['title'])
    except module.AdapterBlocked as error:
        action('article_layout','核对当前内容对象的公开声明与内容门；不得从编辑记录推断隐私通过。',guide=guide,
               missing=[str(error)])
        return
    package['content_item']=request['current']['article_item']
    if 'article_render_manifest' not in refs:
        action('article_layout','调用已有排版器，仅生成同版公开稿候选，不上传。',
            ['python',str(Path(module.__file__)),'render','--mode','public-review','--item',str(refs['article_item']),
             '--markdown',package['draft']['path'],'--markdown-sha256',package['draft']['sha256'],
             '--output-dir','<new-layout-directory>','--checked-at','<actual-RFC3339-time>'],guide)
        return
    outputs=rendered(module,refs['article_item'],refs['article_render_manifest'],result)
    package.update(render_manifest=request['current']['article_render_manifest'], rendered_outputs=outputs,
                   rendered_artifacts_verified=True)
    package['remaining_steps']=[s for s in package['remaining_steps'] if s!='platform_layout']
    if 'article_visual_review' not in refs:
        result['status']='needs_context'
        result['primary_entry']='article_visual_review'
        result['next_action']=dict(kind='visual_review',selected_not_executed=True,outputs=outputs,
            reason='Inspect desktop, mobile and dark preview; bind observations and screenshot hashes. Local preview needs applicable permission.')
        result['missing_inputs']=['article_visual_review']
        result['visual_review_template']=dict(render_manifest_ref=request['current']['article_render_manifest'],
            views=[dict(view=v,artifact_ref=outputs[2 if v=='mobile_dark' else 1],status='pending',observation='',
                        evidence_ref=dict(path='<actual-evidence>',sha256='<sha256>')) for v in sorted(VIEWS)])
        return
    package['visual_review']=visual_review(refs['article_visual_review'],request['current']['article_render_manifest'],outputs)
    package['visual_review_ref']=request['current']['article_visual_review']
    package['remaining_steps']=[s for s in package['remaining_steps'] if s!='rendered_output_review']
    result['status']='awaiting_author' if not result['article_editorial_status']['author_confirmation_recorded'] else 'selected'
    result['primary_entry']='article_author_review_package'
    result['completion_boundary']='Same-version editorial, layout and recorded visual review; device/backend review and manual publication remain separate.'
    result['next_action']=dict(kind='human_review',selected_not_executed=True,
        reason='Review this consolidated article package. No automatic publication or author decision.',draft=package['draft']['path'])


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['prepare','check'])
    parser.add_argument('--request',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args(argv)
    try:
        if args.action=='prepare':
            result=prepare(args.request,args.output)
        else:
            import self_media_agent as agent
            selection=agent.resolve_request(agent.load_json(args.request))
            require('article_review_package' in selection,'article_editorial_not_ready')
            result=selection
            with args.output.open('x',encoding='utf8') as handle:
                json.dump(result,handle,ensure_ascii=False,indent=2)
        print(json.dumps(result,ensure_ascii=False))
        return 0
    except (ValueError,OSError,KeyError,TypeError) as error:
        print(json.dumps(dict(status='blocked',error=str(error)),ensure_ascii=False))
        return 2
