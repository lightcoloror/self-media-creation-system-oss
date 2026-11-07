"""Synthetic purpose/feedback contracts; no media, live authors or publishing.

The managed-chain test proves transport through the existing first route step,
not semantic review or end-to-end content production. Ledger mocks isolate the
feedback bridge from the separately tested author-ledger persistence owner.
"""
import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import creation_route
import purpose_continuity as purpose
import self_media_agent as agent


class PurposeContinuityTests(unittest.TestCase):
    def setUp(self):
        runtime = Path(os.environ.get('TEST_TMP_ROOT', str(ROOT / '.test-runtime')))
        runtime.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(prefix='purpose-contract-', dir=runtime)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.task_id = 'synthetic-purpose-contract-01'
        self.purpose_quote = '让第一次独立旅行的人理解路线取舍。'
        self.audience_quote = '受众是第一次独立旅行的成年人。'
        self.duty = '标题如实建立理解路线取舍的期待，不代替正文给出完整解释。'
        self.brief = self.write('brief.md', self.purpose_quote + '\n' + self.audience_quote)
        self.body = self.write('body.md', '合成正文：我比较了两条路线，保留了更适合自己的那条。')

    def write(self, name, value):
        path = self.root / name
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2)
                        if isinstance(value, (dict, list)) else value, encoding='utf-8')
        return path

    def ref(self, path, absolute=False):
        return dict(path=str(path) if absolute else path.relative_to(self.root).as_posix(),
                    sha256=purpose.digest(path))

    def artifact(self, artifact_id, path, role='source_manifest', source_role=None):
        result = dict(artifact_id=artifact_id, role=role,
                      path=path.relative_to(self.root).as_posix(), load_mode='reference',
                      expected_sha256=purpose.digest(path))
        if source_role:
            result['source_role'] = source_role
        return result

    def manifest(self, name='context.json', feedback=False, task_id=None, duty=None):
        value = dict(schema_version='self-media-context-input.v1',
                     task_id=task_id or self.task_id, stage='visual',
                     budget=dict(max_inline_bytes=4096), artifacts=[
                         self.artifact('purpose', self.brief, source_role='content-purpose'),
                         self.artifact('body', self.body, 'approved_script', 'current-body')],
                     editorial_context=dict(version=1, content_id='synthetic-content-01',
                         purpose=dict(artifact_id='purpose', quote=self.purpose_quote),
                         audience=dict(artifact_id='purpose', quote=self.audience_quote),
                         stage_duty=duty or self.duty, current_body_artifact_id='body',
                         feedback=[], feedback_note='只有本合成样例明确提供的反馈，未声称查询其他记录。'))
        if feedback:
            correction = self.write('feedback.md', '不要把路线取舍写成适用于所有人的唯一答案。')
            value['artifacts'].append(self.artifact('feedback-one', correction, 'user_correction', 'editorial-feedback-one'))
            value['editorial_context']['feedback'].append(dict(
                artifact_id='feedback-one', quote=correction.read_text(encoding='utf-8'), check_ids=['C01', 'C05']))
        return self.write(name, value)

    def review(self, context, name='review.json', disposition='retained', output=None):
        output = output or self.write('candidate.md', '两条路线，我为什么留下这一条')
        value = purpose.load(context)['editorial_context']
        return self.write(name, dict(schema_version=purpose.REVIEW_SCHEMA,
            context_ref=self.ref(context), artifact_ref=self.ref(output),
            quote=output.read_text(encoding='utf-8'),
            purpose_alignment=dict(stage_duty=value['stage_duty'],
                contribution='实际成稿把期待限定在个人路线取舍，接回正文解释。',
                misunderstanding_risk='避免把个人取舍误读成普遍路线推荐。',
                tradeoff='保留具体数字作为入口，解释留给正文，不强加咨询转化。'),
            feedback_resolutions=[dict(artifact_id=row['artifact_id'],
                resolution='已对照实际输出，保留个人适用范围；并未声称编辑过原稿。')
                for row in value['feedback']],
            disposition=disposition, reason='本阶段职责已说明，按实际产物记录保留决定。'))

    def assertPurposeError(self, code, call):
        with self.assertRaises(purpose.PurposeError) as caught:
            call()
        self.assertEqual(caught.exception.code, 'purpose_' + code)

    def work_request(self, kind, current):
        return dict(schema_version='self-media-work-request.v1', request_id=self.task_id,
                    requested_output=kind, selection_basis='合成目的传递测试，无执行或发布授权。', current=current)

    def test_same_source_quote_and_hash_are_bound_without_goal_store(self):
        context = self.manifest()
        value = purpose.validate_context(context, self.task_id)
        self.assertEqual(value['purpose_source'], dict(path=str(self.brief),
            sha256=purpose.digest(self.brief), quote=self.purpose_quote))
        self.assertEqual(value['audience_source']['path'], value['purpose_source']['path'])
        self.assertEqual(value['context_manifest'], self.ref(context, absolute=True))
        self.assertEqual(value['current_body'], self.ref(self.body, absolute=True))
        self.assertFalse(value['automatic_semantic_verification'])
        self.assertEqual(value['feedback_coverage'], 'explicit_supplied_snapshot_only')

    def test_missing_purpose_hash_quote_and_referenced_body_fail(self):
        original = purpose.load(self.manifest())
        cases = [
            ('purpose', lambda x: x['editorial_context'].pop('purpose'), 'manifest_invalid'),
            ('hash', lambda x: x['artifacts'][0].pop('expected_sha256'), 'source_required'),
            ('quote', lambda x: x['editorial_context']['purpose'].pop('quote'), 'manifest_invalid'),
            ('body', lambda x: x['editorial_context'].update(current_body_artifact_id='absent-body'), 'body_missing'),
        ]
        for name, mutate, code in cases:
            with self.subTest(field=name):
                value = copy.deepcopy(original)
                mutate(value)
                path = self.write(name + '-invalid.json', value)
                self.assertPurposeError(code, lambda: purpose.validate_context(path))

    def test_absent_context_is_optional_only_when_explicitly_requested(self):
        context = self.manifest()
        value = purpose.load(context)
        value.pop('editorial_context')
        self.write(context.name, value)
        self.assertPurposeError('context_missing', lambda: purpose.validate_context(context))
        self.assertIsNone(purpose.validate_context(context, required=False))

    def test_wrong_source_quote_and_changed_source_bytes_fail(self):
        context = self.manifest()
        original = purpose.load(context)
        bad = copy.deepcopy(original)
        bad['editorial_context']['purpose']['quote'] = '来源里不存在的目的。'
        self.write(context.name, bad)
        self.assertPurposeError('anchor_missing', lambda: purpose.validate_context(context))
        self.write(context.name, original)
        self.write(self.brief.name, self.brief.read_text(encoding='utf-8') + '\n新增目标')
        self.assertPurposeError('source_drift', lambda: purpose.validate_context(context))

    def test_new_feedback_cannot_reuse_review_bound_to_old_context(self):
        old = self.manifest('old-context.json')
        review = self.review(old)
        current = self.manifest('current-context.json', feedback=True)
        self.assertPurposeError('context_mismatch', lambda: purpose.validate_review(current, review))

    def test_declared_feedback_and_review_resolution_cannot_be_omitted(self):
        context = self.manifest(feedback=True)
        value = purpose.load(context)
        value['editorial_context']['feedback'] = []
        omitted = self.write('omitted.json', value)
        self.assertPurposeError('feedback_pending', lambda: purpose.validate_context(omitted))
        review = self.review(context)
        value = purpose.load(review)
        value['feedback_resolutions'] = []
        self.write(review.name, value)
        self.assertPurposeError('feedback_pending', lambda: purpose.validate_review(context, review))

    def test_user_correction_requires_feedback_without_new_source_role_prefix(self):
        context = self.manifest(feedback=True)
        original = purpose.load(context)
        for source_role in (None, 'legacy-user-correction'):
            with self.subTest(source_role=source_role):
                value = copy.deepcopy(original)
                artifact = value['artifacts'][-1]
                artifact.pop('source_role')
                if source_role:
                    artifact['source_role'] = source_role
                value['editorial_context']['feedback'] = []
                self.write(context.name, value)
                self.assertPurposeError('feedback_pending', lambda: purpose.validate_context(context))
                value['editorial_context']['feedback'] = copy.deepcopy(original['editorial_context']['feedback'])
                self.write(context.name, value)
                self.assertEqual(len(purpose.validate_context(context)['feedback']), 1)

    def test_registered_feedback_check_scope_cannot_be_narrowed(self):
        context = self.manifest(feedback=True)
        value = purpose.load(context)
        author = self.write('author-context.json', {'synthetic_owner_placeholder': True})
        value['artifacts'].append(self.artifact('author-context', author, source_role='author-writing-context'))
        value['editorial_context']['feedback'][0]['check_ids'] = ['C07']
        self.write(context.name, value)
        feedback = self.root / 'feedback.md'
        event = dict(record_type='editorial_feedback', payload=dict(
            source=dict(path='synthetic-feedback.md', sha256=purpose.digest(feedback),
                        quote=feedback.read_text(encoding='utf-8')), check_ids=['C01', 'C05']))
        # Only the other owner's history/loading is mocked; bridge checks use real files/hashes.
        store = self.root / 'synthetic-unused-author-store'
        with patch('author_writing_context.validate_context', return_value={
                'author_brief': {'content_id': 'synthetic-content-01'}, 'store_path': str(store)}), \
             patch('author_writing_context.store_api.store_path', return_value=store), \
             patch('editorial_integrity.history', return_value=[event]), \
             patch('author_writing_context.checked_ref', return_value=feedback):
            self.assertPurposeError('feedback_scope_drift', lambda: purpose.validate_context(context))
            value['editorial_context']['feedback'][0]['check_ids'] = ['C01', 'C05']
            self.write(context.name, value)
            resolved = purpose.validate_context(context)
            self.assertEqual(resolved['feedback_coverage'], 'existing_author_ledger')
            self.assertEqual(resolved['author_store_path'], str(store))

    def test_transition_keeps_known_ledger_and_rejects_snapshot_downgrade_or_store_switch(self):
        previous = purpose.validate_context(self.manifest(feedback=True))
        # Synthetic in-memory transition records; no store is created or read.
        previous.update(feedback_coverage='existing_author_ledger',
                        author_store_path=str(self.root / 'synthetic-store-a'))
        retained = copy.deepcopy(previous)
        retained['stage_duty'] = '下一阶段用画面解释相同路线取舍。'
        purpose.check_transition(previous, retained)
        downgraded = copy.deepcopy(previous)
        downgraded.update(feedback_coverage='explicit_supplied_snapshot_only', author_store_path=None)
        switched = copy.deepcopy(previous)
        switched['author_store_path'] = str(self.root / 'synthetic-store-b')
        for label, current in [('snapshot', downgraded), ('other-store', switched)]:
            with self.subTest(change=label):
                self.assertPurposeError('feedback_ledger_lost', lambda: purpose.check_transition(previous, current))

    def test_manifest_purpose_matches_latest_preflight_evidence_without_upgrading_early_or_historical_context(self):
        context = self.manifest()
        value = purpose.load(context)
        author = self.write('author-context.json', {'synthetic_owner_placeholder': True})
        value['artifacts'].append(self.artifact('author-context', author, source_role='author-writing-context'))
        self.write(context.name, value)
        store = self.root / 'synthetic-unused-author-store'
        same = dict(path=self.brief.name, sha256=purpose.digest(self.brief), quote=self.purpose_quote)
        wrong_quote = dict(same, quote=self.audience_quote)
        other = self.write('other-brief.md', self.brief.read_text(encoding='utf-8'))
        wrong_path = dict(same, path=other.name)
        wrong_hash = dict(same, sha256='0' * 64)

        def record(evidence):
            return dict(record_type='editorial_preflight', payload=dict(assessment=dict(items=[
                dict(id='goal_audience', state='ready', evidence=evidence)])))

        # Store loading and evidence-owner resolution are isolated; no real store is read.
        with patch('author_writing_context.validate_context', return_value={
                'author_brief': {'content_id': 'synthetic-content-01'}, 'store_path': str(store)}), \
             patch('author_writing_context.store_api.store_path', return_value=store), \
             patch('author_writing_context.checked_ref', side_effect=lambda ref: self.root / ref['path']), \
             patch('editorial_integrity.history') as history:
            with self.subTest(case='latest-has-one-exact-anchor'):
                history.return_value = [record([wrong_quote]), record([wrong_path, same])]
                result = purpose.validate_context(context)
                self.assertEqual(result['purpose_source']['quote'], self.purpose_quote)
                self.assertFalse(result['automatic_semantic_verification'])
            for label, mismatch in [('quote', wrong_quote), ('path', wrong_path), ('hash', wrong_hash)]:
                with self.subTest(latest_mismatch=label):
                    history.return_value = [record([same]), record([mismatch])]
                    self.assertPurposeError('preflight_goal_mismatch', lambda: purpose.validate_context(context))
            with self.subTest(case='no-preflight-remains-early-context'):
                history.return_value = []
                result = purpose.validate_context(context)
                self.assertEqual(result['feedback_coverage'], 'existing_author_ledger')
                self.assertFalse(result['automatic_semantic_verification'])
                self.assertNotIn('may_continue', result)
            with self.subTest(case='historical-does-not-upgrade-to-current-preflight'):
                history.return_value = [record([wrong_quote])]
                history.reset_mock()
                result = purpose.validate_context(context, historical=True)
                history.assert_not_called()
                self.assertFalse(result['automatic_semantic_verification'])
                self.assertNotIn('may_continue', result)

    def test_transition_accepts_reordered_or_expanded_checks_but_not_reduced_or_replaced_source(self):
        previous = purpose.validate_context(self.manifest(feedback=True))
        for checks in (['C05', 'C01'], ['C05', 'C07', 'C01']):
            with self.subTest(allowed_checks=checks):
                current = copy.deepcopy(previous)
                current['feedback'][0]['check_ids'] = checks
                purpose.check_transition(previous, current)
        reduced = copy.deepcopy(previous)
        reduced['feedback'][0]['check_ids'] = ['C01']
        replaced = copy.deepcopy(previous)
        replaced['feedback'][0]['source']['sha256'] = '0' * 64
        for label, current in [('reduced', reduced), ('replaced-source', replaced)]:
            with self.subTest(blocked_change=label):
                self.assertPurposeError('feedback_lost', lambda: purpose.check_transition(previous, current))

    def test_transition_rejects_lost_feedback_and_silent_goal_change(self):
        previous = purpose.validate_context(self.manifest(feedback=True))
        current = copy.deepcopy(previous)
        current['feedback'] = []
        self.assertPurposeError('feedback_lost', lambda: purpose.check_transition(previous, current))
        current = copy.deepcopy(previous)
        current['purpose_source']['quote'] = '默改成追求最大观看量。'
        self.assertPurposeError('goal_change_unexplained', lambda: purpose.check_transition(previous, current))

    def test_sourced_goal_feedback_and_new_stage_duty_allow_transition(self):
        previous = purpose.validate_context(self.manifest('previous.json'))
        current_path = self.manifest('next.json', feedback=True, duty='画面帮助观众看清路线差异，不重复整段口播。')
        new_goal = self.write('new-goal.md', '目的调整为解释不同路线各自适合什么情况。')
        value = purpose.load(current_path)
        value['artifacts'].append(self.artifact('new-goal', new_goal, source_role='updated-content-purpose'))
        value['editorial_context']['purpose'] = dict(artifact_id='new-goal', quote=new_goal.read_text(encoding='utf-8'))
        self.write(current_path.name, value)
        current = purpose.validate_context(current_path)
        purpose.check_transition(previous, current)
        self.assertNotEqual(previous['stage_duty'], current['stage_duty'])

    def test_title_and_cover_keep_independent_routes_without_creation_rerun(self):
        context = self.manifest()
        before = purpose.digest(self.body)
        with patch('creation_route.resolve', side_effect=AssertionError('Independent packaging must not rerun creation selection')):
            for kind, entry in [('title_options', 'text_packaging'), ('cover_options', 'covers')]:
                with self.subTest(kind=kind):
                    result = agent.resolve_request(self.work_request(kind, dict(context_manifest=self.ref(context, True))))
                    self.assertEqual(result['primary_entry'], entry)
                    self.assertIsNone(result['workflow_goal'])
                    self.assertEqual(result['status'], 'selected')
                    self.assertFalse(result['commands_executed'])
                    self.assertFalse(result['media_export_authorized'])
        self.assertEqual(before, purpose.digest(self.body))

    def test_technical_only_cannot_exempt_packaging_but_keeps_real_technical_rework(self):
        for kind, entry in [('title_options', 'text_packaging'), ('cover_options', 'covers')]:
            with self.subTest(kind=kind):
                request = self.work_request(kind, {})
                request['change_scope'] = 'technical_only'
                result = agent.resolve_request(request)
                self.assertEqual(result['primary_entry'], entry)
                self.assertEqual(result['status'], 'needs_context')
                self.assertIn('context_manifest_with_editorial_context', result['missing_inputs'])
                request['current'] = dict(context_manifest=self.ref(self.manifest(), True))
                self.assertEqual(agent.resolve_request(request)['status'], 'selected')
        for kind in ('video_plan', 'finished_video'):
            with self.subTest(technical_deliverable=kind):
                request = self.work_request(kind, {})
                request['change_scope'] = 'technical_only'
                result = agent.resolve_request(request)
                self.assertEqual(result['workflow_goal'], 'context_efficient_rework')
                self.assertNotIn('context_manifest_with_editorial_context', result['missing_inputs'])
                self.assertFalse(result['commands_executed'])

    def test_title_and_cover_require_current_body_but_early_context_can_be_bound(self):
        context = self.manifest()
        value = purpose.load(context)
        value['editorial_context']['current_body_artifact_id'] = None
        self.write(context.name, value)
        self.assertIsNone(purpose.validate_context(context)['current_body'])
        for kind in ('title_options', 'cover_options'):
            with self.subTest(kind=kind):
                result = agent.resolve_request(self.work_request(kind, dict(context_manifest=self.ref(context, True))))
                self.assertEqual(result['status'], 'needs_context')
                self.assertIn('current_body_in_context_manifest', result['missing_inputs'])

    def test_story_and_expository_keep_selected_creation_form(self):
        manifest = self.manifest()
        for route, intent in [('story', 'causal-change'), ('expository', 'explain-or-answer')]:
            with self.subTest(route=route):
                assessment = dict(schema_version='creation-route-context.v1', task_id=self.task_id,
                    revision_id='synthetic-route-v1', task_kind='create', topic_domain='explanation',
                    primary_intent=intent, requested_route=route, requested_vlog_style='auto',
                    material_state='existing', material_summary='合成的两次路线选择记录。',
                    assessment_reason='按本合成任务表达职责选择，不代表真实内容判断。',
                    avoid_forced_story=False, causal_change=dict(status='supported', evidence_refs=['synthetic-route-change']),
                    source_refs=['synthetic-route-change'])
                assessed = self.write(route + '-assessment.json', assessment)
                decision = self.write(route + '-decision.json', creation_route.resolve(assessment))
                current = dict(context_manifest=self.ref(manifest, True),
                    creation_context=self.ref(assessed, True), creation_decision=self.ref(decision, True))
                request = self.work_request('article', current)
                result = agent.resolve_request(request)
                self.assertEqual(result['creation_route']['primary_route'], route)
                self.assertEqual(result['primary_entry'], 'canonical_format_adapter')
                self.assertEqual(result['editorial_context']['purpose_source']['quote'], self.purpose_quote)

    def test_actual_title_expectation_mismatch_stays_needs_revision(self):
        context = self.manifest()
        output = self.write('overpromising-title.md', '两天就能搞定所有人的最佳旅行路线')
        review = self.review(context, disposition='needs_revision', output=output)
        value = purpose.load(review)
        value['reason'] = '标题承诺通用最佳路线，但正文只解释个人选择；需改标题期待。'
        self.write(review.name, value)
        result = purpose.validate_review(context, review, [output, review])
        self.assertTrue(result['purpose_record_complete'])
        self.assertFalse(result['may_continue'])
        self.assertFalse(result['editorial_quality_verified'])

    def test_numeric_hook_natural_lines_and_pauses_can_be_retained_for_duty(self):
        variants = [
            ('数字入口', '两条路线，我为什么留下这一条', '数字具体化选择规模，正文兑现比较理由。'),
            ('自然分行', '两条路线\n我比较了时间和体力\n最后留下一条', '三行按语义呼吸，不硬套四行或固定字数。'),
            ('停顿', '我以为会选短的。\n[停顿]\n后来把体力也算进去了。', '停顿给理解判断变化留出气口，不强迫添加情绪。'),
        ]
        for index, (label, text, duty) in enumerate(variants):
            with self.subTest(choice=label):
                context = self.manifest(f'choice-{index}.json', duty=duty)
                output = self.write(f'choice-{index}.md', text)
                review = self.review(context, f'choice-{index}-review.json', output=output)
                result = purpose.validate_review(context, review)
                self.assertTrue(result['may_continue'])
                self.assertEqual(result['disposition'], 'retained')
                self.assertFalse(result['author_selection_verified'])
                self.assertFalse(result['audience_effect_verified'])

    def test_record_cannot_claim_edit_verified_or_switch_stage_duty(self):
        context = self.manifest()
        review = self.review(context, disposition='revised_verified')
        self.assertPurposeError('edit_evidence_required', lambda: purpose.validate_review(context, review))
        value = purpose.load(review)
        value['disposition'] = 'retained'
        value['purpose_alignment']['stage_duty'] = '擅自把标题职责改成保证转化。'
        self.write(review.name, value)
        self.assertPurposeError('duty_drift', lambda: purpose.validate_review(context, review))

    def test_review_must_anchor_actual_step_output(self):
        context = self.manifest()
        review = self.review(context)
        other = self.write('other.md', '另一份无关产物')
        self.assertPurposeError('output_mismatch', lambda: purpose.validate_review(context, review, [other]))
        value = purpose.load(review)
        value['quote'] = '产物中不存在的理想修改'
        self.write(review.name, value)
        self.assertPurposeError('output_anchor_missing', lambda: purpose.validate_review(context, review))

    def test_context_itself_cannot_be_presented_as_reviewed_output(self):
        context = self.manifest()
        review = self.review(context, output=context)
        self.assertPurposeError('output_mismatch', lambda: purpose.validate_review(context, review, [context, review]))

    def test_local_check_stage_cli_is_read_only_for_all_sources(self):
        context = self.manifest(feedback=True)
        review = self.review(context, disposition='needs_revision')
        before = {p.name: purpose.digest(p) for p in self.root.iterdir() if p.is_file()}
        env = os.environ.copy()
        env['PYTHONDONTWRITEBYTECODE'] = '1'
        result = subprocess.run([sys.executable, '-B', str(ROOT / 'scripts/self_media_agent.py'),
            'review-integrity', 'check-stage', '--context', str(context), '--review', str(review)],
            cwd=ROOT, env=env, capture_output=True, text=True, encoding='utf-8', timeout=30)
        self.assertEqual(result.returncode, 2, result.stderr + result.stdout)
        report = json.loads(result.stdout)
        self.assertEqual(report['disposition'], 'needs_revision')
        self.assertFalse(report['may_continue'])
        self.assertFalse(report['publication_authorized'])
        self.assertFalse(report['media_export_authorized'])
        after = {p.name: purpose.digest(p) for p in self.root.iterdir() if p.is_file()}
        self.assertEqual(before, after)

    def managed_chain(self, disposition='retained', include_review=True):
        request = agent.load_json(agent.RECIPE_FIXTURES['xhs-evidence-graphic'])
        capsule = self.write('capsule.json', agent.resolve_request(request))
        context = self.manifest(task_id=request['request_id'])
        value = purpose.load(context)
        value['stage'] = 'research'
        routing = self.write('routing-binding.json', agent.load_json(ROOT / 'routing-binding.v1.json'))
        value['artifacts'].append(self.artifact('routing-binding', routing, source_role='routing-binding'))
        self.write(context.name, value)
        handoff_path = self.root / 'handoff.json'
        handoff = agent.prepare_step_handoff(capsule, 'verify-canonical-route', context,
            self.root / 'context-receipt.json', handoff_path)
        validated = agent.validate_step_handoff(handoff_path)
        self.assertEqual(validated['execution_brief']['purpose_context']['purpose_source']['quote'], self.purpose_quote)
        output = self.write('candidate.md', '合成路由传输检查：保留当前目的，未验收内容质量。')
        outputs = [self.ref(output)]
        if include_review:
            review = self.review(context, disposition=disposition, output=output)
            outputs.append(self.ref(review))
        receipt = dict(schema_version='self-media-step-output-receipt.v1', status='candidate_ready',
            handoff=self.ref(handoff_path), step_id=handoff['step']['step_id'],
            tool_id=handoff['step']['tool_id'], output_contract=handoff['step']['output_contract'],
            outputs=outputs, boundaries=copy.deepcopy(handoff['boundaries']))
        receipt['payload_sha256'] = agent.sha256_value(receipt)
        receipt_path = self.write('output-receipt.json', receipt)
        return handoff_path, receipt_path

    def test_prepare_validate_verify_transports_context_without_business_completion(self):
        handoff, receipt = self.managed_chain()
        result = agent.verify_step_output(handoff, receipt)
        self.assertTrue(result['ok'])
        self.assertEqual(result['validation_scope'], 'transport_and_sequence_only')
        self.assertFalse(result['workflow_step_completed'])
        self.assertFalse(result['proves_skill_execution_or_editorial_quality'])

    def test_managed_verify_blocks_complete_record_that_needs_revision(self):
        handoff, receipt = self.managed_chain(disposition='needs_revision')
        result = agent.verify_step_output(handoff, receipt)
        self.assertFalse(result['ok'])
        self.assertEqual(result['status'], 'blocked')
        self.assertFalse(result['purpose_review']['may_continue'])

    def test_managed_verify_requires_review_of_actual_output(self):
        handoff, receipt = self.managed_chain(include_review=False)
        with self.assertRaises(agent.AgentEntryError) as caught:
            agent.verify_step_output(handoff, receipt)
        self.assertEqual(caught.exception.code, 'purpose_review_required')

    def test_research_output_count_excludes_purpose_review_but_not_other_json(self):
        handoff_path, receipt_path = self.managed_chain()
        handoff = purpose.load(handoff_path)
        handoff['step']['step_id'] = 'produce-verified-research-output'
        research = self.write('synthetic-research.json', {'synthetic_owner_placeholder': True})
        review = self.review(self.root / 'context.json', output=research)
        receipt = purpose.load(receipt_path)
        receipt['step_id'] = handoff['step']['step_id']
        receipt['outputs'] = [self.ref(research), self.ref(review)]
        receipt.pop('payload_sha256')
        receipt['payload_sha256'] = agent.sha256_value(receipt)
        self.write(receipt_path.name, receipt)
        # Exercise verify's real receipt/hash/purpose binding and JSON dispatch.
        # The route preconditions and research/author owner checks are mocked:
        # this is an adapter integration test, not completed research evidence.
        with patch.object(agent, 'validate_step_handoff', return_value=handoff), \
             patch.object(agent, '_load_author_writing_context') as author_owner, \
             patch.object(agent, '_validate_research_output_artifact', return_value={'synthetic': True}) as validate_research:
            author_owner.return_value.validate_output_artifacts.return_value = None
            result = agent.verify_step_output(handoff_path, receipt_path)
            self.assertTrue(result['ok'])
            self.assertTrue(result['purpose_review']['may_continue'])
            validate_research.assert_called_once_with(research)
            extra = self.write('extra-research.json', {'another_synthetic_placeholder': True})
            receipt['outputs'].append(self.ref(extra))
            receipt.pop('payload_sha256')
            receipt['payload_sha256'] = agent.sha256_value(receipt)
            self.write(receipt_path.name, receipt)
            with self.assertRaises(agent.AgentEntryError) as caught:
                agent.verify_step_output(handoff_path, receipt_path)
            self.assertEqual(caught.exception.code, 'research_output_missing_or_blocked')
            self.assertEqual(validate_research.call_count, 1)


if __name__ == '__main__':
    unittest.main()
