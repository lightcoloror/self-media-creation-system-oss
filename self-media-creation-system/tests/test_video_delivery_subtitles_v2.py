"""Tests for v2 accessible subtitle contracts in video_delivery.py."""
from __future__ import annotations

import argparse
import copy
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import cover_workbench as w
import publication_desk as desk
import test_cover_strategy as cover_fixture
import video_delivery as v


class VideoDeliverySubtitlesV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.media_tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.media_tmp.cleanup)
        root = Path(cls.media_tmp.name).resolve()
        executor = v.renderer_module()
        cls.ffmpeg = executor.resolve_media_tool('ffmpeg')
        cls.source = root / 'clean-1080p.mp4'
        cls.wav = root / 'voice-6s.wav'
        with wave.open(str(cls.wav), 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(24000)
            wf.writeframes(b'\x02\x00' * (24000 * 6))
        subprocess.run(
            [
                cls.ffmpeg, '-v', 'error', '-n',
                '-f', 'lavfi', '-i', 'color=c=white:s=1920x1080:r=30:d=6',
                '-i', str(cls.wav),
                '-c:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p',
                '-threads', '1', '-c:a', 'aac', '-ar', '24000', '-ac', '1',
                '-shortest', str(cls.source),
            ],
            check=True,
            capture_output=True,
            timeout=60,
        )

    def setUp(self):
        self.helper = cover_fixture.CoverStrategyTests('test_output_matrix_and_review_must_cover_every_ratio')
        self.helper.setUp()
        self.addCleanup(self.helper.doCleanups)
        self.root = self.helper.root
        self.serial = 0

        sub_seq, sub_styles, _, _ = v.subtitle_modules()
        self.sub_seq = sub_seq
        self.sub_styles = sub_styles

        self.raw_cues = [
            {
                'cue_id': 'cue-01',
                'start_seconds': 0.2,
                'end_seconds': 2.7,
                'text': '第3条免赔额先看清',
                'spoken_text': '第3条免赔额先看清',
                'speaker': '采访者',
                'offscreen_speaker': True,
            },
            {
                'cue_id': 'cue-02',
                'start_seconds': 3.2,
                'end_seconds': 5.6,
                'text': '保留原始票据与合同',
                'spoken_text': '保留原始票据与合同',
                'sound_event': '门铃提示',
            },
        ]
        self.style_a = sub_styles.resolve_subtitle_style(1920, 1080, preset_id='accessible_box_a')
        self.sequence = sub_seq.build_reviewed_subtitle_sequence(
            self.raw_cues,
            max_line_units=self.style_a['max_line_units'],
            total_duration_s=6.0,
        )
        self.cues_for_pack = []
        for raw, norm in zip(self.raw_cues, self.sequence['cues']):
            self.cues_for_pack.append({
                **raw,
                'speaker_prefix': norm['speaker_prefix'],
                'sound_event': norm['sound_event'],
                'display_text': norm['display_text'],
                'render_lines': norm['render_lines'],
                'layout_breaks': norm['layout_breaks'],
            })

    def save(self, data):
        self.serial += 1
        path = self.root / f'v2-delivery-{self.serial}.json'
        w.write(path, data)
        return path

    def _build_base_manifest(self, *, media_path, srt_path, ai_mode='ai_assisted', extra_evidence=()):
        import rough_cut_checks as checks
        import video_overlay_selection as overlays
        import video_review_delivery as review
        from datetime import date

        self.m = v.init(self.helper.brief['project_id'])
        self.m['material_intake_ref'] = w.reference(self.save(dict(
            schema=v.materials.INTAKE_SCHEMA,
            project_id=self.m['project_id'],
            scope_note='Synthetic v2 subtitle delivery fixture.',
            assets=[],
        )))
        self.m['background_music'] = dict(
            decision='not_used',
            reason='Synthetic voice-only fixture; no BGM track.',
        )
        from execution_context_fixture import make_context
        self.m['context_manifest_ref'] = make_context(self.root)
        self.m['script_ref'] = w.reference(srt_path)

        ai_cfg = (
            dict(mode='no_ai', stages=[], reason='Synthetic local deterministic fixture without AI generation.')
            if ai_mode == 'no_ai'
            else dict(mode='ai_assisted', stages=['editing'], reason='Synthetic editing fixture.')
        )
        self.overlay_ai = ai_cfg
        assessment = dict(
            schema=overlays.SCHEMA,
            script_ref=self.m['script_ref'],
            ai=ai_cfg,
            medical=dict(
                category='no_medical_subject',
                reason='Synthetic nonmedical insurance clause reading.',
                evidence_quotes=['第3条免赔额先看清'],
            ),
            insurance=dict(
                category='no_insurance_subject',
                reason='Synthetic fixture without commercial product recommendation.',
                evidence_quotes=['第3条免赔额先看清'],
            ),
        )
        self.m['overlay_assessment_ref'] = w.reference(self.save(assessment))
        plan = v.cta.empty_plan(self.m['project_id'], self.m['script_ref'])
        for choice in plan['decisions'].values():
            choice.update(decision='not_used', reason='Synthetic test clip has no CTA.')
        self.m['cta_plan_ref'] = w.reference(self.save(plan))

        fb = self.root / 'feedback.json'
        fb.write_text('{"note":"keep clause exact"}', encoding='utf-8')
        self.m['facts'] = dict(
            story='Synthetic clause reading',
            do_not_infer=['禁止出现夸大收益词'],
            feedback=[dict(id='f1', ref=w.reference(fb), decision='applied', application='Use clause text')],
        )
        self.m['edited_media'] = w.reference(media_path)
        self.m['timeline'] = dict(
            duration_seconds=6.0,
            segments=[dict(
                id='s1',
                source_ref=w.reference(media_path),
                source_start=0.0,
                source_end=6.0,
                target_start=0.0,
                target_end=6.0,
                speed=1.0,
                purpose='full synthetic 6s dual scene',
            )],
            expected_audio=[
                dict(segment_id='s1', source_start=0.2, source_end=2.7, kind='speech'),
                dict(segment_id='s1', source_start=3.2, source_end=5.6, kind='speech'),
            ],
        )

        fixture_tests = v.ROOT.parent / 'ai-video-tools-20260708/mvp-video-pipeline/tests'
        if str(fixture_tests) not in sys.path:
            sys.path.insert(0, str(fixture_tests))
        from segment_level_fixture import make_review
        audio_review = make_review(
            self.root / f'audio-levels-{self.serial}',
            media_path,
            [dict(start=0, end=6)],
            [dict(start=0.2, end=2.7), dict(start=3.2, end=5.6)],
            after_media=media_path,
        )
        self.m['rough_audio_review_ref'] = w.reference(self.save(audio_review))

        rough_dir = self.root / f'rough-{self.serial}'
        rough_dir.mkdir()
        tl_ref = checks.ref(self.save(self.m['timeline']))
        reg = checks.register(media_path, tl_ref['path'], rough_dir / 'registration.json')
        ev = checks.ref(self.save({'synthetic_only': True}))
        proof = {
            'schema': checks.AUDIT_SCHEMA,
            'candidate': self.m['edited_media'],
            'script': self.m['script_ref'],
            'timeline': tl_ref,
            'registration': reg,
            'vkp': [ev],
            'automatic_review': True,
            'technical': {'duration': 6.0, 'candidates': [], 'decoder': ev, 'log': ev},
            'comparison': {'changes': [], 'repetition_candidates': [], 'omitted_phrase_candidates': []},
        }
        audit_p = rough_dir / 'rough-audit.json'
        checks.write_new(audit_p, proof)
        req_p = rough_dir / 'review-req.json'
        checks.write_new(req_p, {
            'schema_version': 'self-media-human-review-request-pack.v1',
            'scope': 'post_cut_check:' + checks.ref(audit_p)['sha256'],
            'requests': [checks.automatic_item(proof)],
        })
        bundle = rough_dir / 'review'
        review.prepare(req_p, bundle, 'rough_cut_recipe')
        self.m['rough_cut_delivery_ref'] = reg
        self.m['rough_cut_acceptance_ref'] = checks.save_automatic_review(audit_p, bundle)

        omission = w.reference(self.save({'role': 'user', 'text': '本期不使用内置进度条。'}))
        self.m['progress_overlay'] = v.progress.select(
            self.m, 'not_used', 'Synthetic clip omits progress bar.', omission_source_ref=omission
        )
        self.m['identity_overlay'] = dict(decision='not_applicable', reason='Non-commercial test fixture.')

        self.asr = dict(
            schema='video_knowledge_pipeline.subtitle_asr_observations.v1',
            status='completed',
            segments=[
                dict(start_seconds=0.2, end_seconds=2.7, text='第3条免赔额先看清'),
                dict(start_seconds=3.2, end_seconds=5.6, text='保留原始票据与合同'),
            ],
        )
        asr_path = self.save(self.asr)
        ev_refs = [w.reference(srt_path)] + list(extra_evidence)
        self.req = dict(
            source_path=str(media_path),
            source_sha256=w.digest(media_path),
            duration_seconds=6.0,
            asr_binding=dict(source_sha256=w.digest(media_path), asr_sha256=w.digest(asr_path)),
            observations=[],
            expected_audio=v.timeline(self.m)['expected_audio'],
            omissions=[],
            evidence_files=ev_refs,
        )
        self.pack = dict(requests=[dict(
            review_id='synthetic-v2-review',
            artifact_sha256=w.digest(media_path),
            full_source_review=True,
            review_start_seconds=0,
            review_end_seconds=6.0,
            subtitle_cues=copy.deepcopy(self.cues_for_pack),
        )])
        self.m['subtitles'] = dict(
            request_ref=w.reference(self.save(self.req)),
            pack_ref=w.reference(self.save(self.pack)),
            asr_ref=w.reference(asr_path),
            review_ref=None,
            render_file_ref=None,
        )
        cov = v.subtitle_check(self.m, v.timeline(self.m))
        cov_review = dict(
            input_fingerprint=cov['input_fingerprint'],
            source_sha256=w.digest(media_path),
            review_id='synthetic-v2-review',
            full_timeline_listened=True,
            full_timeline_viewed=True,
            reviewer='synthetic fixture only',
            reviewed_at='2026-11-24T12:00:00+08:00',
            decision='pass',
            resolutions={
                r['finding_id']: dict(decision='accepted_after_listening', reason='fixture')
                for r in cov['findings']
            },
        )
        self.m['subtitles']['review_ref'] = w.reference(self.save(cov_review))

        self.data, _ = self.helper.desk()
        item = self.data['items'][0]
        item['cta_plan_ref'] = self.m['cta_plan_ref']
        item['platforms'].pop('weibo', None)
        self.data['target_platforms'] = list(item['platforms'])
        for option in item['cover_pk']['candidates']:
            option.update(title='Synthetic ' + option['id'], hypothesis='Distinct ' + option['id'])
        cand = item['cover_pk']['candidates'][0]['cover_by_ratio']
        for key, p in item['platforms'].items():
            profile = desk.platform_policy()['platforms'][key]
            ratios = profile['cover_ratios'][:1] if profile['cover_mode'] == 'one' else profile['cover_ratios']
            p['cover_ids'] = [cand[r] for r in ratios]
            if key == 'weixin_channels':
                p['fields']['short_title'] = 'Synthetic'
            for chk in p['platform_checks'].values():
                chk.update(status='confirmed', evidence='fixture', checked_at=date.today().isoformat())
        self.data['editorial_context'] = dict(
            story=self.m['facts']['story'],
            do_not_infer=self.m['facts']['do_not_infer'],
        )
        for p in item['platforms'].values():
            p['fields'].update(title='Synthetic', body='Clause reading test', tags='#synthetic')
        item['platforms']['kuaishou']['fields'].pop('title', None)
        item['platforms']['weixin_channels']['fields'].pop('title', None)

        if str(v.ROOT.parent / 'ai-video-tools-20260708/mvp-video-pipeline/tests') not in sys.path:
            sys.path.insert(0, str(v.ROOT.parent / 'ai-video-tools-20260708/mvp-video-pipeline/tests'))
        import performance_fixture
        performance_fixture.bind_plan(self.m, self.save)

    def _finalize_delivery(self, final_video: Path, receipt_path: Path):
        import performance_fixture
        import video_pacing as pacing

        self.data['items'][0]['video'] = w.reference(final_video)
        self.m['material_final_review_ref'] = w.reference(self.save(dict(
            schema=v.materials.REVIEW_SCHEMA,
            project_id=self.m['project_id'],
            intake_ref=self.m['material_intake_ref'],
            video=self.data['items'][0]['video'],
            screen_recording_checked=True,
            reviewer='Synthetic fixture',
            sample_receipts=[],
            entries=[],
        )))
        cov_rev = self.helper.passed_review(self.data)
        self.m['desk_ref'] = cov_rev['desk_ref']
        self.m['cover_review_ref'] = w.reference(self.save(cov_rev))
        self.m['render_receipt_ref'] = w.reference(receipt_path)

        final = self.data['items'][0]['video']
        common = Path(os.path.commonpath([str(self.root), str(final_video.parent)])).resolve()
        ev = self.root / f'layout-ev-{self.serial}.json'
        ev.write_text('{"synthetic":true}', encoding='utf-8')
        rel = lambda ref: dict(
            path=Path(ref['path']).resolve().relative_to(common).as_posix(),
            expected_sha256=ref['sha256'],
        )
        reserved = v.renderer_module() and __import__(
            'video_creation_pipeline.final_layout_safety', fromlist=['rounded_corner_regions']
        ).rounded_corner_regions()
        elements = []
        req_roles = []
        if self.overlay_ai['mode'] != 'no_ai':
            req_roles = ['ai_label']
            elements.append(dict(
                element_id='ai-lbl',
                role='ai_label',
                text='AI辅助创作',
                start_seconds=0.0,
                end_seconds=6.0,
                rect=dict(x=0.2, y=0.08, width=0.35, height=0.04),
                critical_content=True,
            ))
        else:
            req_roles = ['subtitle']
            elements.append(dict(
                element_id='sub-band',
                role='subtitle',
                start_seconds=0.0,
                end_seconds=6.0,
                rect=dict(x=0.15, y=0.78, width=0.70, height=0.12),
                critical_content=True,
            ))
        layout = dict(
            schema_version='video-final-layout-safety.v1',
            layout_id='v2-final-layout',
            duration_seconds=6.0,
            ai_disclosure=self.overlay_ai,
            candidate=rel(final),
            layout_evidence=rel(w.reference(ev)),
            required_roles=req_roles,
            reserved_regions=reserved,
            elements=elements,
        )
        self.m['final_layout_ref'] = w.reference(self.save(layout))
        self.m['layout_workspace_root'] = str(common)
        self.serial += 1
        obs_dir = self.root / f'obs-{self.serial}'
        v.observe_final(self.m, obs_dir.resolve())
        self.m['final_observations_ref'] = w.reference(obs_dir / 'observations.json')

        pack = w.read(w.bound(self.m['subtitles']['pack_ref']))
        pack['requests'][0]['artifact_sha256'] = final['sha256']
        pack_ref = w.reference(self.save(pack))
        chunks = self.save(dict(source=final))
        raw = self.save(dict(
            canonical_complete=True,
            chunk_manifest_path=str(chunks),
            duration_seconds=6.0,
            result=[dict(
                words=['第3条免赔额先看清', '保留原始票据与合同'],
                timestamp=[[200, 2700], [3200, 5600]],
                chunk_offset_seconds=0.0,
                chunk_core_start_seconds=0.0,
                chunk_core_end_seconds=6.0,
            )],
        ))
        transcript = self.save(dict(source_path=str(raw), segments=self.asr['segments']))
        asr_run = self.save(dict(
            schema='video_knowledge_local_video_run.v1',
            ok=True,
            selected_media_path=final['path'],
            transcript_path=str(transcript),
            asr_run=dict(execute=True, provider='sensevoice', raw_output_json=str(raw)),
        ))
        log = self.root / f'pacing-{self.serial}.log'
        log.write_text('ok', encoding='utf-8')
        log_ref = w.reference(log)
        dec = self.save(dict(
            outlet_id=pacing.OUTLET,
            status='completed',
            operation='technical_qa',
            command=[pacing.SILENCE_FILTER],
            inputs=[dict(artifact=final)],
            outputs=[dict(artifact=log_ref)],
        ))
        refs, metrics = pacing.measure(final, pack, asr_run, 6.0, '')
        self.m['pacing_report_ref'] = w.reference(self.save(dict(
            schema=pacing.SCHEMA,
            candidate=final,
            script=self.m['script_ref'],
            subtitles=pack_ref,
            source_subtitles=self.m['subtitles']['pack_ref'],
            vkp=refs,
            audio_log=log_ref,
            decoder=w.reference(dec),
            metrics=metrics,
        )))

        if str(v.ROOT.parent / 'ai-video-tools-20260708/mvp-video-pipeline/tests') not in sys.path:
            sys.path.insert(0, str(v.ROOT.parent / 'ai-video-tools-20260708/mvp-video-pipeline/tests'))
        performance_fixture.bind_plan(self.m, self.save)
        acc = dict(
            schema='self-media.video-acceptance.v1',
            input_fingerprint=v.acceptance_fingerprint(self.m),
            reviewer_kind='human',
            reviewer='synthetic contract fixture only',
            reviewed_at='2026-11-24T12:00:00+08:00',
            decision='pass',
            speaker_styles_consistent=True,
            preview_export_consistent=True,
            **{k: True for k in v.HUMAN_CHECKS},
        )
        acc['cta_landing'] = dict(
            plan_sha256=self.m['cta_plan_ref']['sha256'],
            video_sha256=final['sha256'],
            unplanned_cta_absent=True,
            prepared_copy_reviewed=True,
            notes='Synthetic fixture.',
            observations=[],
        )
        acc['final_layout_review'] = dict(
            video_sha256=final['sha256'],
            layout_sha256=self.m['final_layout_ref']['sha256'],
            observations_sha256=self.m['final_observations_ref']['sha256'],
            rendered_elements_verified=True,
            mobile_readable=True,
            ai_label_visible=(self.overlay_ai['mode'] != 'no_ai'),
            evidence='Synthetic fixture.',
        )
        acc['performance_review'] = performance_fixture.review(self.m, final, self.save)
        self.m['acceptance_ref'] = w.reference(self.save(acc))

    def _prepare_clean_burn_fixture(self, *, preset_id='accessible_box_a', font_id='dengxian_bold_static', include_ai_badge=True):
        cjk_work = self.root / '测试 字幕' / f'输出 目录-{preset_id}-{font_id}'
        cjk_work.mkdir(parents=True, exist_ok=True)
        srt_path = cjk_work / 'whole video.srt'
        srt_path.write_text(self.sub_seq.export_whole_srt(self.sequence), encoding='utf-8')
        style_spec = self.sub_styles.resolve_subtitle_style(1920, 1080, preset_id=preset_id, font_id=font_id)
        fonts_dir = cjk_work / 'managed_fonts'
        bundle = self.sub_styles.materialize_font_bundle(
            style_spec['font'],
            fonts_dir,
            manifest_path=cjk_work / 'font-bundle-manifest.json',
        )
        ass_text = self.sub_styles.build_ass_document(self.sequence['cues'], style_spec)
        if include_ai_badge:
            ass_text = ass_text.replace(
                '[Events]\n',
                'Style: BadgeAI,DengXian,36,&H00FFFFFF,&H000000FF,&H00101010,&H00000000,-1,0,0,0,100,100,0,0,1,3,0,9,40,40,40,1\n[Events]\n',
            ) + 'Dialogue: 0,0:00:00.00,0:00:06.00,BadgeAI,,0,0,0,,AI辅助创作\n'
        ass_path = cjk_work / '主字幕 样式.ass'
        ass_path.write_text(ass_text, encoding='utf-8')

        self._build_base_manifest(media_path=self.source, srt_path=srt_path, ai_mode='ai_assisted' if include_ai_badge else 'no_ai')
        self.m['subtitles'].update(
            contract_version='v2',
            source_route='video_delivery_clean_burn',
            style_preset=preset_id,
            render_file_ref=w.reference(ass_path),
            sidecar_srt_ref=w.reference(srt_path),
            font_bundle_ref=w.reference(Path(bundle['bundle_manifest']['path'])),
        )
        self.req['evidence_files'] = [w.reference(ass_path), w.reference(srt_path)]
        self.m['subtitles']['request_ref'] = w.reference(self.save(self.req))
        cov = v.subtitle_check(self.m, v.timeline(self.m))
        cov_rev = v.read_ref(self.m['subtitles']['review_ref'])
        cov_rev['input_fingerprint'] = cov['input_fingerprint']
        cov_rev['resolutions'] = {
            r['finding_id']: dict(decision='accepted_after_listening', reason='fixture')
            for r in cov['findings']
        }
        self.m['subtitles']['review_ref'] = w.reference(self.save(cov_rev))
        return cjk_work, ass_path, srt_path, bundle

    def _clean_burn_job(self, work_dir: Path, ass_path: Path, bundle: dict, out_name='burned-v2.mp4'):
        import artifact_lifecycle

        life = work_dir / 'lifecycle.json'
        if not life.exists():
            artifact_lifecycle.init_manifest(argparse.Namespace(
                manifest=life, workspace_root=self.root, manifest_id='v2-clean-burn',
                workspace_ref='synthetic', quarantine_dir='.quarantine',
                authorize_automatic_purge=False, now=None,
            ))
        output = work_dir / out_name
        receipt = work_dir / (Path(out_name).stem + '-receipt.json')
        vf = self.sub_styles.build_ass_ffmpeg_filter(ass_path, bundle['fonts_dir'])
        return dict(
            schema='self-media.local-render-job.v1',
            preflight_fingerprint=v.acceptance_fingerprint(self.m),
            project_root=str(self.root),
            inputs=[
                dict(role='candidate', artifact=self.m['edited_media']),
                dict(role='subtitles', artifact=w.reference(ass_path)),
                dict(role='subtitle_font', artifact=w.reference(Path(bundle['font_file']['path']))),
                dict(role='subtitle_font_bundle', artifact=w.reference(Path(bundle['bundle_manifest']['path']))),
            ],
            output=str(output),
            receipt=str(receipt),
            lifecycle_manifest_ref=w.reference(life),
            estimated_output_bytes=2_000_000,
            command=[
                'ffmpeg', '-hide_banner', '-nostdin', '-n',
                '-i', str(self.source), '-vf', vf,
                '-c:v', 'libx264', '-preset', 'ultrafast', '-c:a', 'copy',
                str(output),
            ],
        )

    def test_path2_clean_burn_guarded_render_cjk_path_and_style_c(self):
        cjk_work, ass_path, _, bundle = self._prepare_clean_burn_fixture(preset_id='accessible_box_a')
        job = self._clean_burn_job(cjk_work, ass_path, bundle)
        sample = {'cpu_percent': 0, 'available_memory_bytes': 32 * 1024**3, 'available_memory_percent': 80, 'disk_busy_percent': 0}
        from video_creation_pipeline import review_resource_guard as resource
        with mock.patch.object(resource, 'capture_resource_snapshot', return_value=sample):
            rendered = v.guarded_render(self.save(self.m), self.save(job))
        self.assertEqual(rendered['status'], 'rendered_pending_delivery_review', rendered)
        self._finalize_delivery(Path(job['output']), Path(job['receipt']))
        report = v.audit(self.save(self.m), 'delivery')
        self.assertTrue(report['complete'], report)
        self.assertEqual(report['subtitle_burn_reconciliation']['source_route'], 'video_delivery_clean_burn')
        self.assertEqual(report['subtitle_burn_reconciliation']['style_preset'], 'accessible_box_a')

        # Style C (outline_v2_c) with Alibaba static font also passes cleanly.
        cjk_work_c, ass_c, _, bundle_c = self._prepare_clean_burn_fixture(
            preset_id='outline_v2_c', font_id='alibaba_puhuiti_55_regular', include_ai_badge=False
        )
        job_c = self._clean_burn_job(cjk_work_c, ass_c, bundle_c, out_name='burned-style-c.mp4')
        with mock.patch.object(resource, 'capture_resource_snapshot', return_value=sample):
            rendered_c = v.guarded_render(self.save(self.m), self.save(job_c))
        self.assertEqual(rendered_c['status'], 'rendered_pending_delivery_review', rendered_c)
        self._finalize_delivery(Path(job_c['output']), Path(job_c['receipt']))
        report_c = v.audit(self.save(self.m), 'delivery')
        self.assertTrue(report_c['complete'], report_c)
        self.assertEqual(report_c['subtitle_burn_reconciliation']['style_preset'], 'outline_v2_c')

    def test_guarded_render_rejections(self):
        cjk_work, ass_path, _, bundle = self._prepare_clean_burn_fixture()
        base_job = self._clean_burn_job(cjk_work, ass_path, bundle)

        # 1. Arbitrary fontsdir outside bundle / project root
        bad = copy.deepcopy(base_job)
        bad['command'][7] = f"subtitles=filename='{self.sub_styles.ffmpeg_filter_escape(ass_path)}':fontsdir='C\\:/Windows/Fonts'"
        with self.assertRaisesRegex(ValueError, 'unbound_subtitle_fontsdir'):
            v.guarded_render(self.save(self.m), self.save(bad))

        # 2. fontsdir in non-subtitle filter
        bad = copy.deepcopy(base_job)
        bad['command'][7] = "drawtext=text='hi':fontsdir='C\\:/Windows/Fonts'"
        with self.assertRaisesRegex(ValueError, 'unbound_filter_file_not_allowed'):
            v.guarded_render(self.save(self.m), self.save(bad))

        # 3. Missing force_style prohibition on managed ASS
        bad = copy.deepcopy(base_job)
        bad['command'][7] = self.sub_styles.build_ass_ffmpeg_filter(ass_path, bundle['fonts_dir']) + ":force_style='Fontsize=20'"
        with self.assertRaisesRegex(ValueError, 'force_style_not_allowed_for_managed_ass'):
            v.guarded_render(self.save(self.m), self.save(bad))

        # 4. Missing font from job['inputs']
        bad = copy.deepcopy(base_job)
        bad['inputs'] = [row for row in bad['inputs'] if row['role'] != 'subtitle_font']
        with self.assertRaisesRegex(ValueError, 'unbound_subtitle_fontsdir'):
            v.guarded_render(self.save(self.m), self.save(bad))

        # 5. Extra untracked file inside fonts_dir
        stray = Path(bundle['fonts_dir']) / 'untracked.ttf'
        stray.write_bytes(b'fake-font')
        try:
            with self.assertRaisesRegex(ValueError, 'unbound_subtitle_fontsdir'):
                v.guarded_render(self.save(self.m), self.save(base_job))
        finally:
            stray.unlink()

        # 6. Double burn rejection when source_route is audio_timeline_segmented or remotion_rendered
        for route in ('audio_timeline_segmented', 'remotion_rendered'):
            m_copy = copy.deepcopy(self.m)
            m_copy['subtitles']['source_route'] = route
            job_dbl = copy.deepcopy(base_job)
            job_dbl['preflight_fingerprint'] = v.acceptance_fingerprint(m_copy)
            with self.assertRaisesRegex(ValueError, 'double_subtitle_burn_not_allowed_for_source_route'):
                v.guarded_render(self.save(m_copy), self.save(job_dbl))

    def test_ass_style_inline_override_sequence_and_overlay_rejections(self):
        cjk_work, ass_path, srt_path, _ = self._prepare_clean_burn_fixture(include_ai_badge=True)
        orig_ass = ass_path.read_text(encoding='utf-8')

        cases = [
            ('arial_font', orig_ass.replace('Style: Default,DengXian,', 'Style: Default,Arial,'), 'forbidden_arial_or_empty_subtitle_font'),
            ('shrunk_fontsize', orig_ass.replace('Style: Default,DengXian,59,', 'Style: Default,DengXian,32,'), 'subtitle_font_below_minimum'),
            ('shrunk_scalex', orig_ass.replace(',100,100,0,0,', ',70,100,0,0,'), 'subtitle_font_below_minimum'),
            ('inline_fs', orig_ass.replace('第3条免赔额', r'{\fs32}第3条免赔额'), 'invalid_subtitle_inline_override'),
            ('inline_fn', orig_ass.replace('第3条免赔额', r'{\fnArial}第3条免赔额'), 'invalid_subtitle_inline_override'),
            ('inline_bord0', orig_ass.replace('第3条免赔额', r'{\bord0}第3条免赔额'), 'invalid_subtitle_inline_override'),
            ('inline_3a_ff', orig_ass.replace('第3条免赔额', r'{\3a&HFF&}第3条免赔额'), 'invalid_subtitle_inline_override'),
            ('inline_fscx', orig_ass.replace('第3条免赔额', r'{\fscx75}第3条免赔额'), 'invalid_subtitle_inline_override'),
            ('opaque_box', orig_ass.replace('&H59101010', '&H00101010'), 'invalid_subtitle_box_color_or_opacity'),
            ('bare_white', re.sub(r',3,\d+(?:\.\d+)?,0,', ',1,0,0,', orig_ass).replace('&H59101010', '&HFFFFFFFF'), 'invalid_subtitle_backing_style|invalid_subtitle_outline_backing'),
            ('duplicate_prefix', orig_ass.replace('采访者：第3条', '采访者：采访者：第3条'), 'duplicate_subtitle_speaker_prefix'),
            ('do_not_infer_subtitle', orig_ass.replace('第3条免赔额先看清', '禁止出现夸大收益词'), 'burn_overlay_or_subtitle_text_violation'),
            ('do_not_infer_badge', orig_ass.replace('AI辅助创作', 'AI辅助创作 禁止出现夸大收益词'), 'burn_overlay_or_subtitle_text_violation'),
        ]
        for label, content, err_pat in cases:
            with self.subTest(case=label):
                bad_ass = cjk_work / f'bad-{label}.ass'
                bad_ass.write_text(content, encoding='utf-8')
                with self.assertRaisesRegex(ValueError, err_pat):
                    v.verify_subtitle_burn_file(self.m, bad_ass)

        # Bare white under outline_v2_c preset fails invalid_subtitle_outline_backing explicitly
        m_c = copy.deepcopy(self.m)
        m_c['subtitles']['style_preset'] = 'outline_v2_c'
        bare_c = cjk_work / 'bad-bare-white-c.ass'
        bare_c.write_text(re.sub(r',3,\d+(?:\.\d+)?,0,', ',1,0,0,', orig_ass).replace('&H59101010', '&HFFFFFFFF'), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'invalid_subtitle_outline_backing'):
            v.verify_subtitle_burn_file(m_c, bare_c)

        # Typo correction check
        self.m['subtitles']['typo_corrections'] = {'免赔额': '免赔比例'}
        with self.assertRaisesRegex(ValueError, 'burn_overlay_or_subtitle_typo_detected'):
            v.verify_subtitle_burn_file(self.m, ass_path)
        self.m['subtitles'].pop('typo_corrections')

        # Missing required medical badge in ASS caught cleanly
        m_med = copy.deepcopy(self.m)
        ass_ov = v.read_ref(m_med['overlay_assessment_ref'])
        ass_ov['medical'].update(category='clinical_explanation', reason='Clinical clause explanation test.')
        m_med['overlay_assessment_ref'] = w.reference(self.save(ass_ov))
        with self.assertRaisesRegex(ValueError, 'video_overlay_ass_applicability_mismatch: medical'):
            v.verify_subtitle_burn_file(m_med, ass_path)

        # Tampered sidecar SRT fails audit
        bad_srt = cjk_work / 'bad.srt'
        bad_srt.write_text('1\n00:00:00,200 --> 00:00:02,700\n被篡改的字幕\n', encoding='utf-8')
        m_srt = copy.deepcopy(self.m)
        m_srt['subtitles']['sidecar_srt_ref'] = w.reference(bad_srt)
        with self.assertRaisesRegex(ValueError, 'burn_file_disagrees_with_reviewed_cues'):
            v._reconcile_sidecar_srt(m_srt)

    def test_path2_audit_missing_or_double_burn_receipts(self):
        cjk_work, ass_path, srt_path, bundle = self._prepare_clean_burn_fixture()
        plain_out = cjk_work / 'plain-copy.mp4'
        plain_rec = cjk_work / 'plain-rec.json'
        v.renderer_module().execute_ffmpeg_with_receipt(
            'transcode',
            ['ffmpeg', '-v', 'error', '-n', '-i', str(self.source), '-c:v', 'copy', '-c:a', 'copy', str(plain_out)],
            [dict(role='edited_media', path=str(self.source))],
            [dict(role='candidate', path=str(plain_out))],
            plain_rec,
            timeout_s=30,
        )
        self._build_base_manifest(media_path=self.source, srt_path=srt_path)
        # Rebind v2 fields pointing to ass_path + plain_rec (0 burn steps!)
        self._finalize_delivery(plain_out, plain_rec)
        # Re-prepare cleanly over the finalized manifest to check Path 2 missing burn step
        m2 = copy.deepcopy(self.m)
        m2['subtitles'].update(
            contract_version='v2',
            source_route='video_delivery_clean_burn',
            style_preset='accessible_box_a',
            render_file_ref=w.reference(ass_path),
            sidecar_srt_ref=w.reference(cjk_work / 'whole video.srt'),
            font_bundle_ref=w.reference(Path(bundle['bundle_manifest']['path'])),
        )
        req = v.read_ref(m2['subtitles']['request_ref'])
        req['evidence_files'] = [m2['subtitles']['render_file_ref'], m2['subtitles']['sidecar_srt_ref']]
        m2['subtitles']['request_ref'] = w.reference(self.save(req))
        with self.assertRaisesRegex(ValueError, 'missing_subtitle_burn_receipt_step'):
            v._audit_v2_subtitle_lineage(
                m2,
                chain_receipts=[v.read_ref(m2['render_receipt_ref'])],
                final_ref=self.data['items'][0]['video'],
            )

        # Two burn receipts in chain -> double burn rejected
        burn_job = self._clean_burn_job(cjk_work, ass_path, bundle, out_name='b1.mp4')
        fake_step = dict(
            inputs=burn_job['inputs'],
            command=burn_job['command'],
            outputs=[dict(role='candidate', artifact=w.reference(plain_out))],
        )
        with self.assertRaisesRegex(ValueError, 'double_subtitle_burn_not_allowed_for_source_route'):
            v._audit_v2_subtitle_lineage(
                m2,
                chain_receipts=[fake_step, fake_step],
                final_ref=self.data['items'][0]['video'],
            )

    def test_path1_audio_timeline_segmented_delivery_and_negatives(self):
        audio_timeline = self.sub_seq  # import sibling cleanly via package name
        import importlib
        at_mod = importlib.import_module(f'{self.sub_seq.__package__}.audio_timeline')

        at_work = self.root / 'path1-at'
        at_work.mkdir()
        pp = at_work / 'packaging.json'
        bp = at_work / 'binding.json'
        prov = at_work / 'prov.json'
        prov.write_text('{}', encoding='utf-8')
        pp.write_text(json.dumps({
            'schema': 'video_creation_pipeline.video_packaging_plan.v1',
            'status': 'candidate_only',
            'output': {'width': 1920, 'height': 1080, 'fps': 30},
            'scenes': [
                {'scene_id': 'scene-1', 'start_s': 0.0, 'end_s': 3.0},
                {'scene_id': 'scene-2', 'start_s': 3.0, 'end_s': 6.0},
            ],
        }), encoding='utf-8')
        sub_pack_file = at_work / 'subtitle-pack.json'
        sub_pack_file.write_text(json.dumps({'requests': [{'subtitle_cues': self.raw_cues}]}), encoding='utf-8')
        bp.write_text(json.dumps({
            'schema': 'video_creation_pipeline.audio_timeline_binding.v1',
            'packaging': at_mod.artifact_reference(pp, 'packaging'),
            'audio': at_mod.artifact_reference(self.wav, 'audio'),
            'subtitle_pack': at_mod.artifact_reference(sub_pack_file, 'subtitle pack'),
            'segments': [
                {
                    'scene_id': 'scene-1',
                    'visual': at_mod.artifact_reference(self.source, 'visual'),
                    'provenance': at_mod.artifact_reference(prov, 'provenance'),
                    'semantic_description': 'Scene 1',
                    'visual_start_s': 0.0,
                },
                {
                    'scene_id': 'scene-2',
                    'visual': at_mod.artifact_reference(self.source, 'visual'),
                    'provenance': at_mod.artifact_reference(prov, 'provenance'),
                    'semantic_description': 'Scene 2',
                    'visual_start_s': 0.0,
                },
            ],
        }), encoding='utf-8')

        rendered = at_mod.compose(pp, bp, at_work / 'cache', at_work / 'out')
        at_manifest_path = at_work / 'out' / 'manifest.json'
        cand_path = Path(rendered['candidate']['path'])
        srt_path = Path(rendered['sidecar_srt']['path'])

        final_path = at_work / 'delivered-path1.mp4'
        final_rec = at_work / 'final-remux-receipt.json'
        v.renderer_module().execute_ffmpeg_with_receipt(
            'transcode',
            ['ffmpeg', '-v', 'error', '-n', '-i', str(cand_path), '-c:v', 'copy', '-c:a', 'copy', str(final_path)],
            [dict(role='edited_media', path=str(cand_path))],
            [dict(role='candidate', path=str(final_path))],
            final_rec,
            timeout_s=30,
        )

        self._build_base_manifest(media_path=cand_path, srt_path=srt_path, ai_mode='no_ai')
        # Match timeline duration cleanly against composed 6s candidate (timeline has segment s1=6.0s on cand_path)
        self.m['subtitles'].update(
            contract_version='v2',
            source_route='audio_timeline_segmented',
            style_preset='stroke_shadow_default',
            sidecar_srt_ref=w.reference(srt_path),
            audio_timeline_manifest_ref=w.reference(at_manifest_path),
        )
        self._finalize_delivery(final_path, final_rec)
        report = v.audit(self.save(self.m), 'delivery')
        self.assertTrue(report['complete'], report)
        self.assertEqual(report['subtitle_burn_reconciliation']['source_route'], 'audio_timeline_segmented')
        self.assertEqual(report['subtitle_burn_reconciliation']['segment_count'], 2)

        # Negative 1: scene-2 ASS timestamp accidentally global instead of scene-local
        at_m = w.read(at_manifest_path)
        seg2_ass = Path(at_m['segment_receipts'][1]['subtitle_ass']['path'])
        orig_seg2_ass = seg2_ass.read_text(encoding='utf-8')
        seg2_rec_path = Path(at_m['segment_receipts'][1]['render_receipt']['path'])
        orig_seg2_rec_text = seg2_rec_path.read_text(encoding='utf-8')
        seg2_ass.write_text(orig_seg2_ass.replace('0:00:00.20', '0:00:03.20').replace('0:00:02.60', '0:00:05.60'), encoding='utf-8')
        at_m['segment_receipts'][1]['subtitle_ass'] = w.reference(seg2_ass)
        seg2_rec = w.read(seg2_rec_path)
        for row in seg2_rec['inputs']:
            if row['role'] == 'subtitle':
                row['artifact'] = at_mod.artifact_reference(seg2_ass, 'subtitle ass')
        seg2_rec['receipt_sha256'] = v.renderer_module().payload_sha256(seg2_rec, 'receipt_sha256')
        seg2_rec_path.write_text(json.dumps(seg2_rec), encoding='utf-8')
        at_m['segment_receipts'][1]['render_receipt'] = w.reference(seg2_rec_path)
        bad_at_m = at_work / 'manifest-bad-ts.json'
        bad_at_m.write_text(json.dumps(at_m), encoding='utf-8')
        m_bad_ts = copy.deepcopy(self.m)
        m_bad_ts['subtitles']['audio_timeline_manifest_ref'] = w.reference(bad_at_m)
        with self.assertRaisesRegex(ValueError, 'burn_file_disagrees_with_reviewed_cues|segment_ass_timestamp_exceeds_scene_bounds'):
            v._audit_v2_subtitle_lineage(
                m_bad_ts,
                chain_receipts=[v.read_ref(m_bad_ts['render_receipt_ref'])],
                final_ref=self.data['items'][0]['video'],
            )
        seg2_ass.write_text(orig_seg2_ass, encoding='utf-8')
        seg2_rec_path.write_text(orig_seg2_rec_text, encoding='utf-8')

        # Negative 2: mocked_runner font load evidence rejected in delivery audit
        at_m_font = w.read(at_manifest_path)
        ev_bad = at_work / 'font-ev-mocked.json'
        ev_bad.write_text(json.dumps({
            'verified': 'mocked_runner',
            'expected_filename': 'Dengb.ttf',
            'expected_postscript_name': 'DengXian-Bold',
        }), encoding='utf-8')
        at_m_font['segment_receipts'][0]['font_load_evidence'] = w.reference(ev_bad)
        bad_at_font = at_work / 'manifest-bad-font.json'
        bad_at_font.write_text(json.dumps(at_m_font), encoding='utf-8')
        m_bad_font = copy.deepcopy(self.m)
        m_bad_font['subtitles']['audio_timeline_manifest_ref'] = w.reference(bad_at_font)
        with self.assertRaisesRegex(ValueError, 'audio_timeline_font_load_evidence_unverified'):
            v._audit_v2_subtitle_lineage(
                m_bad_font,
                chain_receipts=[v.read_ref(m_bad_font['render_receipt_ref'])],
                final_ref=self.data['items'][0]['video'],
            )

        # Negative 3: downstream double burn in chain
        fake_burn_step = dict(
            inputs=[],
            command=['ffmpeg', '-n', '-i', str(cand_path), '-vf', "subtitles='x.srt'", str(final_path)],
            outputs=[],
        )
        with self.assertRaisesRegex(ValueError, 'double_subtitle_burn_not_allowed_for_source_route'):
            v._audit_v2_subtitle_lineage(
                self.m,
                chain_receipts=[fake_burn_step],
                final_ref=self.data['items'][0]['video'],
            )

    def test_path3_remotion_rendered_delivery_and_negatives(self):
        rem_mod = self.sub_styles  # same isolated package
        import importlib
        handoff_mod = importlib.import_module(f'{self.sub_seq.__package__}.remotion_skill_handoff')
        remotion_mod = importlib.import_module(f'{self.sub_seq.__package__}.remotion_project')

        rem_work = self.root / 'path3-remotion'
        skills = rem_work / 'skills'
        skills.mkdir(parents=True)
        (skills / 'package.json').write_text(json.dumps({'name': '@remotion/skills', 'version': '4.0.513'}), encoding='utf-8')
        for rel in (
            'skills/remotion-best-practices/SKILL.md',
            'skills/remotion-markup/SKILL.md',
            'skills/remotion-interactivity/SKILL.md',
            'skills/remotion-render/SKILL.md',
            'skills/remotion-studio/SKILL.md',
            'skills/remotion-captions/SKILL.md',
        ):
            p = skills / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text('ok', encoding='utf-8')
        runtime = rem_work / 'runtime'
        for sub, pkg in (('core', 'remotion'), ('cli', '@remotion/cli')):
            p = runtime / 'packages' / sub / 'package.json'
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps({'name': pkg, 'version': '4.0.477'}), encoding='utf-8')
        (runtime / 'LICENSE.md').write_text('license', encoding='utf-8')

        pkg_plan = rem_work / 'packaging.json'
        pkg_plan.write_text(json.dumps({
            'schema': 'video_creation_pipeline.video_packaging_plan.v1',
            'status': 'candidate_only',
            'output': {'width': 1920, 'height': 1080, 'fps': 30},
            'scenes': [
                {'scene_id': 'scene-1', 'start_s': 0.0, 'end_s': 3.0},
                {'scene_id': 'scene-2', 'start_s': 3.0, 'end_s': 6.0},
            ],
        }), encoding='utf-8')
        srt_path = rem_work / 'subtitles.srt'
        srt_path.write_text(self.sub_seq.export_whole_srt(self.sequence), encoding='utf-8')
        project_dir = rem_work / 'project'

        with (
            mock.patch.object(handoff_mod, '_git_head', return_value=handoff_mod.REMOTION_SKILLS_COMMIT),
            mock.patch.object(remotion_mod, '_git_head', return_value=remotion_mod.REMOTION_RUNTIME_COMMIT),
        ):
            ho = handoff_mod.build_remotion_skill_handoff(skills, pkg_plan, composition_id='SubV2', subtitle_path=srt_path)
            ho_path = handoff_mod.write_remotion_skill_handoff(ho, rem_work / 'handoff.json')
            mat = remotion_mod.materialize_remotion_project(ho_path, runtime, project_dir, license_basis='individual')

        # Populate offline node_modules package descriptors & dummy chrome binary
        (project_dir / 'package-lock.json').write_text('{"lockfileVersion":3}', encoding='utf-8')
        for pkg_name, pkg_ver in remotion_mod._RUNTIME_PACKAGES.items():
            pj = project_dir / 'node_modules' / Path(*pkg_name.split('/')) / 'package.json'
            pj.parent.mkdir(parents=True, exist_ok=True)
            pj.write_text(json.dumps({'name': pkg_name, 'version': pkg_ver}), encoding='utf-8')
        cli_js = project_dir / 'node_modules/@remotion/cli/remotion-cli.js'
        cli_js.parent.mkdir(parents=True, exist_ok=True)
        cli_js.write_text('console.log("ok")', encoding='utf-8')
        browser_exe = rem_work / 'fake-chrome.exe'
        browser_exe.write_bytes(b'MZ')

        man = w.read(mat['manifest'])
        font_sha = man['subtitle_materialization']['project_font']['sha256']

        def fake_run_remotion(cli, rem_args, cwd, timeout_s):
            if rem_args[0] == 'render':
                out_staging = Path(rem_args[3])
                out_staging.parent.mkdir(parents=True, exist_ok=True)
                subprocess.run(
                    [
                        self.ffmpeg, '-v', 'error', '-y',
                        '-f', 'lavfi', '-i', 'color=c=white:s=1920x1080:r=30:d=6',
                        '-c:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p',
                        '-threads', '1', str(out_staging),
                    ],
                    check=True,
                    capture_output=True,
                    timeout=30,
                )
                return {
                    'output': '[subtitle-font-loaded] ' + json.dumps({
                        'status': 'loaded',
                        'family': 'DengXian',
                        'weight': 700,
                        'sha256': font_sha,
                    }),
                }
            return {'output': 'SubV2'}

        with (
            mock.patch.object(handoff_mod, '_git_head', return_value=handoff_mod.REMOTION_SKILLS_COMMIT),
            mock.patch.object(remotion_mod, '_git_head', return_value=remotion_mod.REMOTION_RUNTIME_COMMIT),
            mock.patch.object(remotion_mod, '_run_remotion', side_effect=fake_run_remotion),
        ):
            rem_receipt = remotion_mod.run_remotion_candidate(mat['manifest'], runtime, browser_path=browser_exe)

            rem_receipt_path = project_dir / 'remotion-run-receipt.json'
            cand_video = Path(rem_receipt['candidate_video']['path'])
            final_video = rem_work / 'muxed-final.mp4'
            mux_rec = rem_work / 'mux-receipt.json'
            v.renderer_module().execute_ffmpeg_with_receipt(
                'transcode',
                ['ffmpeg', '-v', 'error', '-n', '-i', str(cand_video), '-i', str(self.wav),
                 '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'copy', '-c:a', 'aac', '-shortest', str(final_video)],
                [dict(role='edited_media', path=str(cand_video)), dict(role='audio', path=str(self.wav))],
                [dict(role='candidate', path=str(final_video))],
                mux_rec,
                timeout_s=30,
            )

            self._build_base_manifest(media_path=cand_video, srt_path=srt_path, ai_mode='no_ai')
            self.m['subtitles'].update(
                contract_version='v2',
                source_route='remotion_rendered',
                style_preset='stroke_shadow_default',
                sidecar_srt_ref=w.reference(srt_path),
                remotion_run_receipt_ref=w.reference(rem_receipt_path),
            )
            self._finalize_delivery(final_video, mux_rec)
            report = v.audit(self.save(self.m), 'delivery')
            self.assertTrue(report['complete'], report)
            self.assertTrue(report['subtitle_burn_reconciliation']['browser_font_load_verified'])

            # Negative: tampered browser_font_load_verified -> blocked
            bad_rem = copy.deepcopy(rem_receipt)
            bad_rem['subtitle_runtime']['browser_font_load_verified'] = False
            bad_rem['receipt_sha256'] = remotion_mod.payload_sha256(bad_rem, 'receipt_sha256')
            bad_rem_path = rem_work / 'bad-rem-receipt.json'
            bad_rem_path.write_text(json.dumps(bad_rem), encoding='utf-8')
            m_bad_rem = copy.deepcopy(self.m)
            m_bad_rem['subtitles']['remotion_run_receipt_ref'] = w.reference(bad_rem_path)
            with self.assertRaises((ValueError, Exception)):
                v._audit_v2_subtitle_lineage(
                    m_bad_rem,
                    chain_receipts=[v.read_ref(m_bad_rem['render_receipt_ref'])],
                    final_ref=self.data['items'][0]['video'],
                )

            # Negative: downstream double burn on Remotion route -> blocked
            with self.assertRaisesRegex(ValueError, 'double_subtitle_burn_not_allowed_for_source_route'):
                v._audit_v2_subtitle_lineage(
                    self.m,
                    chain_receipts=[dict(inputs=[], command=['ffmpeg', '-n', '-i', str(cand_video), '-vf', "subtitles='x.srt'", str(final_video)], outputs=[])],
                    final_ref=self.data['items'][0]['video'],
                )

    def test_video_final_timeline_preserved_with_v2_burn(self):
        cjk_work, ass_path, _, bundle = self._prepare_clean_burn_fixture(include_ai_badge=False)
        edit_basis_ref = w.reference(self.save(dict(
            accepted_rough_input=self.m['edited_media'],
            segments=[dict(start=0.0, end=6.0, speed=1.0, target=0.0, name='full cut')],
        )))
        trimmed = cjk_work / 'trimmed.mp4'
        trim_rec = cjk_work / 'trim-receipt.json'
        v.renderer_module().execute_ffmpeg_with_receipt(
            'transcode',
            [
                'ffmpeg', '-v', 'error', '-n', '-i', str(self.source),
                '-filter_complex', '[0:v]split=1[src0];[src0]trim=start=0.0:end=6.0,setpts=(PTS-STARTPTS)/1.0[v];[0:a]asplit=1[aud0];[aud0]atrim=start=0.0:end=6.0,asetpts=PTS-STARTPTS,atempo=1.0[a]',
                '-map', '[v]', '-map', '[a]', '-c:v', 'libx264', '-preset', 'ultrafast', '-c:a', 'aac',
                str(trimmed),
            ],
            [dict(role='edited_media', path=str(self.source)), dict(role='edit_plan', path=edit_basis_ref['path'])],
            [dict(role='candidate', path=str(trimmed))],
            trim_rec,
            timeout_s=60,
        )
        burned = cjk_work / 'burned-ft.mp4'
        burn_rec = cjk_work / 'burn-ft-receipt.json'
        vf = self.sub_styles.build_ass_ffmpeg_filter(ass_path, bundle['fonts_dir'])
        v.renderer_module().execute_ffmpeg_with_receipt(
            'render',
            ['ffmpeg', '-hide_banner', '-nostdin', '-n', '-i', str(trimmed), '-vf', vf,
             '-c:v', 'libx264', '-preset', 'ultrafast', '-c:a', 'copy', str(burned)],
            [
                dict(role='candidate', path=str(trimmed)),
                dict(role='subtitles', path=str(ass_path)),
                dict(role='subtitle_font', path=bundle['font_file']['path']),
                dict(role='subtitle_font_bundle', path=bundle['bundle_manifest']['path']),
            ],
            [dict(role='candidate', path=str(burned))],
            burn_rec,
            timeout_s=60,
        )
        self.m['render_chain_refs'] = [w.reference(trim_rec)]
        self._finalize_delivery(burned, burn_rec)
        tl_seg = dict(
            id='final-001',
            source_ref=self.m['edited_media'],
            source_start=0.0,
            source_end=6.0,
            target_start=0.0,
            target_end=6.0,
            speed=1.0,
            purpose='full cut',
        )
        ft_expected_audio = [dict(row, segment_id='final-001') for row in self.m['timeline']['expected_audio']]
        self.m['final_timeline_ref'] = w.reference(self.save(dict(
            schema='self-media.final-timeline.v1',
            project_id=self.m['project_id'],
            source_media=self.m['edited_media'],
            candidate=self.data['items'][0]['video'],
            edit_plan_ref=edit_basis_ref,
            edit_render_receipt_ref=w.reference(trim_rec),
            timeline=dict(duration_seconds=6.0, segments=[tl_seg], expected_audio=ft_expected_audio, trailing_media_padding_seconds=0.0),
        )))
        acc = v.read_ref(self.m['acceptance_ref'])
        acc['input_fingerprint'] = v.acceptance_fingerprint(self.m)
        self.m['acceptance_ref'] = w.reference(self.save(acc))
        report = v.audit(self.save(self.m), 'delivery')
        self.assertTrue(report['complete'], report)
        self.assertEqual(report['final_timeline']['timeline_ref'], self.m['final_timeline_ref'])


if __name__ == '__main__':
    unittest.main()
