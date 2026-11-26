"""Comprehensive positive and adversarial negative test suite for workflow anti-skip/omission improvements (2026-11-19)."""
from __future__ import annotations

import copy
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import author_expression_store as store
import author_writing_context as author
import creation_route
import editorial_integrity as editorial
import entry_selection
import publication_desk as desk
import rough_cut_checks as rcc
import runtime_paths
import self_media_agent as agent
import video_delivery as delivery


class WorkflowAntiSkipRegressionTests(unittest.TestCase):
    def setUp(self):
        test_tmp = Path(os.environ.get("TEST_TMP_ROOT", ROOT / ".test-runtime"))
        test_tmp.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=test_tmp)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.serial = 0

    def ref(self, value: dict) -> dict[str, str]:
        self.serial += 1
        path = self.root / f"fixture-{self.serial}.json"
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        return {"path": str(path), "sha256": agent.sha256_file(path)}

    # -------------------------------------------------------------------------
    # G01: Mode B CLI & Module Resolution Closure
    # -------------------------------------------------------------------------
    def test_g01_managed_self_argv_routing(self):
        old_env = os.environ.get(runtime_paths.ENV_ACTIVE_RELEASE)
        try:
            if runtime_paths.ENV_ACTIVE_RELEASE in os.environ:
                del os.environ[runtime_paths.ENV_ACTIVE_RELEASE]
            argv = runtime_paths.managed_self_argv(ROOT, "scripts/publication_desk.py", "doctor")
            self.assertEqual(argv[0], sys.executable)
            self.assertEqual(Path(argv[1]).resolve(), (ROOT / "scripts/publication_desk.py").resolve())
            self.assertTrue(Path(argv[1]).is_file())

            os.environ[runtime_paths.ENV_ACTIVE_RELEASE] = "2026.11.18-002"
            argv_rel = runtime_paths.managed_self_argv(ROOT, "scripts/publication_desk.py", "doctor")
            self.assertEqual(argv_rel[0], sys.executable)
            self.assertIn("invoke_main.py", argv_rel[1])
            self.assertIn("--require-release", argv_rel)
            self.assertIn("2026.11.18-002", argv_rel)
            self.assertIn("scripts/publication_desk.py", argv_rel)
        finally:
            if old_env is not None:
                os.environ[runtime_paths.ENV_ACTIVE_RELEASE] = old_env
            elif runtime_paths.ENV_ACTIVE_RELEASE in os.environ:
                del os.environ[runtime_paths.ENV_ACTIVE_RELEASE]

    # -------------------------------------------------------------------------
    # G02: Insurance Terms Gate & Topic Domain Case Auto Risk Flag
    # -------------------------------------------------------------------------
    def test_g02_insurance_terms_fail_closed(self):
        req = {
            "schema_version": "self-media-work-request.v1",
            "request_id": "test-insurance-01",
            "requested_output": "article",
            "platform": "wechat-article",
            "selection_basis": "合成测试",
            "risk_flags": {"insurance_terms": True},
            "current": {},
        }
        res = entry_selection.resolve(req, agent)
        self.assertEqual(res["status"], "needs_context")
        self.assertIn("insurance_compliance_review", res["missing_inputs"])

        # Passing an approved insurance review bound to this request satisfies the gate
        ins_review = self.ref({
            "decision": "approved",
            "request_id": "test-insurance-01",
            "reviewer": "ComplianceOfficer",
            "scope": "insurance_terms",
        })
        req["current"]["insurance_review"] = ins_review
        res_approved = entry_selection.resolve(req, agent)
        self.assertNotIn("insurance_compliance_review", res_approved.get("missing_inputs", []))
        req["current"]["insurance_review"] = {**ins_review, "sha256": "f" * 64}
        with self.assertRaises(agent.AgentEntryError) as failure:
            entry_selection.resolve(req, agent)
        self.assertEqual(failure.exception.code, "source_hash_drift")

    def test_g02_case_topic_auto_risk_flag(self):
        base_ctx = json.loads((ROOT / "fixtures/creation-route-v1/same-day-activity-highlights.context.json").read_text(encoding="utf-8"))
        base_ctx.update(task_id="case-test-01", topic_domain="case")
        req = {
            "schema_version": "self-media-work-request.v1",
            "request_id": "case-test-01",
            "requested_output": "finished_video",
            "content_format": "demo-video",
            "selection_basis": "合成案例测试",
            "current": {
                "creation_context": self.ref(base_ctx),
            },
        }
        res = entry_selection.resolve(req, agent)
        self.assertEqual(res["status"], "needs_context")
        self.assertIn("privacy_treatment_review", res["missing_inputs"])

    # -------------------------------------------------------------------------
    # G03: Cross-Platform Metric Contradiction & do_not_infer
    # -------------------------------------------------------------------------
    def test_g03_cross_platform_metric_contradiction_detected(self):
        project = desk.new_project("metric-test", "测试数值跨平台一致性", ["douyin", "xiaohongshu"])
        item = project["items"][0]
        item["platforms"]["douyin"]["fields"]["body"] = "真实记录：普通人月入200元也能理财。"
        item["platforms"]["xiaohongshu"]["fields"]["body"] = "真实记录：普通人月入2万元也能理财。"
        report = desk.check_platforms(project, "preparation")
        issues = [iss for iss in report["review_items"] if iss.get("code") == "cross_platform_fact_inconsistent"]
        self.assertTrue(len(issues) > 0)
        self.assertIn("数值差异", issues[0]["detail"])
        self.assertNotIn("cross_platform_fact_inconsistent", [issue["code"] for issue in report["issues"]])
        html = desk.render(project)
        self.assertIn("待人工复核", html)
        self.assertIn("跨平台数值差异", html)

    def test_g03_cross_platform_metric_consistent_passes(self):
        project = desk.new_project("metric-test-pass", "测试数值一致通过", ["douyin", "xiaohongshu"])
        item = project["items"][0]
        item["platforms"]["douyin"]["fields"]["body"] = "真实记录：普通人月入200元也能理财。"
        item["platforms"]["xiaohongshu"]["fields"]["body"] = "真实记录：普通人月入200元也能理财。"
        report = desk.check_platforms(project, "preparation")
        metric_issues = [iss for iss in report["review_items"] if iss["code"] == "cross_platform_fact_inconsistent"]
        self.assertEqual(metric_issues, [])

    def test_g03_do_not_infer_violation_in_copy(self):
        project = desk.new_project("do-not-infer-test", "测试禁止推断短语", ["douyin"])
        project["editorial_context"] = {"do_not_infer": ["稳赚不赔", "保本高收益"]}
        item = project["items"][0]
        item["platforms"]["douyin"]["fields"]["body"] = "只要坚持这个策略，稳赚不赔不是梦。"
        report = desk.check_platforms(project, "preparation")
        issues = [iss for iss in report["issues"] if iss.get("code") == "do_not_infer_violated"]
        self.assertTrue(len(issues) > 0)
        self.assertEqual(issues[0]["detail"], "douyin / body")

    def test_g03_heuristic_review_keeps_preparation_complete(self):
        data = desk.new_project("metric-review-test", "人工核对不同方案的数值", ["douyin", "xiaohongshu"])
        item = data["items"][0]
        item["item_kind"] = "article"
        for key, text in (("douyin", "甲方案保额100万元"), ("xiaohongshu", "乙方案保额200万元")):
            fields = item["platforms"][key]["fields"]
            fields.update(body=text, tags="#合成测试")
            if desk.platform_policy()["platforms"][key].get("separate_title", True):
                fields["title"] = "合成测试"
        report = desk.check_platforms(data, "preparation")
        self.assertTrue(report["complete"], report["issues"])
        self.assertEqual([item["code"] for item in report["review_items"]], ["cross_platform_fact_inconsistent"])

    # -------------------------------------------------------------------------
    # G04a: Draft Banner & Open Details in publication_desk
    # -------------------------------------------------------------------------
    def test_g04a_draft_preview_banner_and_open_details(self):
        project = desk.new_project("draft-preview-test", "测试草稿预览警示", ["douyin"])
        html = desk.render(project)
        self.assertIn('<details class="generation-status" open>', html)
        self.assertIn("data-state=\"draft\"", html)
        self.assertIn("<title>[草稿预览]", html)
        self.assertIn("草稿预览", html)
        self.assertIn("请勿直接复制用于正式发布", html)

    # -------------------------------------------------------------------------
    # G04b: Burned Subtitle / Overlay Text Scanner
    # -------------------------------------------------------------------------
    def test_g04b_burned_subtitle_do_not_infer_and_typo_scanner(self):
        ass_with_forbidden = """[Script Info]
Title: Test
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Title_Card,Arial,20,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,1,0,2,10,10,10,1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:01.00,0:00:03.00,Title_Card,,0,0,0,,稳赚不赔的理财秘籍
"""
        visible_forbidden = delivery.parse_ass_all_visible_texts(ass_with_forbidden)
        self.assertEqual(len(visible_forbidden), 1)
        manifest_forbidden = {"facts": {"do_not_infer": ["稳赚不赔"]}}
        with self.assertRaisesRegex(ValueError, "burn_overlay_or_subtitle_text_violation"):
            delivery._scan_burned_text_violations(manifest_forbidden, visible_forbidden)

        ass_with_typo = """[Script Info]
Title: Test Typo
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:01.00,0:00:03.00,Default,,0,0,0,,欢迎收看图与最新一期节目
"""
        visible_typo = delivery.parse_ass_all_visible_texts(ass_with_typo)
        self.assertEqual(len(visible_typo), 1)
        manifest_typo = {"subtitles": {"typo_corrections": {"图与": "图语家"}}}
        with self.assertRaisesRegex(ValueError, "burn_overlay_or_subtitle_typo_detected"):
            delivery._scan_burned_text_violations(manifest_typo, visible_typo)

    # -------------------------------------------------------------------------
    # G05: Four-Stage General Workflow Progression
    # -------------------------------------------------------------------------
    def test_g05_four_stage_general_flow_progression(self):
        req = {
            "schema_version": "self-media-work-request.v1",
            "request_id": "flow-progress-01",
            "requested_output": "script",
            "platform": "douyin",
            "content_format": "spoken-script",
            "selection_basis": "合成流转测试",
            "current": {},
        }
        res0 = entry_selection.resolve(req, agent)
        lw0 = res0.get("lightweight_workflow")
        self.assertIsNotNone(lw0)
        self.assertEqual(lw0["mode"], "four_stage_general")
        self.assertEqual(lw0["current_stage"], "stage_1_charter")
        self.assertEqual(lw0["completed_stages"], [])
        self.assertEqual(lw0["publication_mode"], "manual_fill_via_publication_desk_only")

        # Stage 2: Bind creation_decision and context_manifest
        src = self.ref({"purpose": "Synthetic purpose: explain principles.", "audience": "Synthetic audience."})
        purpose_manifest = self.ref({
            "schema_version": "self-media-context-input.v1",
            "task_id": "flow-progress-01",
            "stage": "draft",
            "budget": {"max_inline_bytes": 4096},
            "artifacts": [{"artifact_id": "purpose-source", "role": "source_manifest", "path": Path(src["path"]).name, "expected_sha256": src["sha256"], "load_mode": "reference"}],
            "editorial_context": {
                "version": 1,
                "content_id": "test-c1",
                "topic_selection": {
                    "topic": "Personal choice",
                    "origin": "tool_trial",
                    "adoption": "selected",
                    "adoption_basis": "Synthetic test only",
                    "origin_source": {"artifact_id": "purpose-source", "quote": "Synthetic purpose: explain principles."},
                    "adoption_source": {"artifact_id": "purpose-source", "quote": "Synthetic purpose: explain principles."},
                },
                "purpose": {"artifact_id": "purpose-source", "quote": "Synthetic purpose: explain principles."},
                "audience": {"artifact_id": "purpose-source", "quote": "Synthetic audience."},
                "stage_duty": "Explain principles simply.",
                "current_body_artifact_id": "purpose-source",
                "feedback": [],
                "feedback_note": "No feedback in this fixture.",
            },
        })
        decision = self.ref({"status": "ready", "primary_route": "expository", "vlog_style": "chronological-diary"})
        req["current"]["context_manifest"] = purpose_manifest
        req["current"]["creation_decision"] = decision
        res1 = entry_selection.resolve(req, agent)
        lw1 = res1["lightweight_workflow"]
        self.assertEqual(lw1["current_stage"], "stage_2_production")
        self.assertEqual(lw1["completed_stages"], ["stage_1_charter"])

    # -------------------------------------------------------------------------
    # G07: External Editor Export Receipt Validation
    # -------------------------------------------------------------------------
    def test_g07_external_editor_receipt_validation(self):
        proj_file = self.root / "openchatcut_project.occ"
        proj_file.write_text("dummy occ project json", encoding="utf-8")
        raw_vid = self.root / "raw.mp4"
        raw_vid.write_text("dummy raw video", encoding="utf-8")
        out_vid = self.root / "exported.mp4"
        out_vid.write_text("dummy exported video", encoding="utf-8")

        receipt = {
            "schema": delivery.EXTERNAL_EDITOR_RECEIPT_SCHEMA,
            "editor": "openchatcut",
            "status": "completed",
            "project_file_ref": {"path": str(proj_file), "sha256": agent.sha256_file(proj_file)},
            "inputs": [{"role": "rough_cut", "artifact": {"path": str(raw_vid), "sha256": agent.sha256_file(raw_vid)}}],
            "outputs": [{"role": "candidate", "artifact": {"path": str(out_vid), "sha256": agent.sha256_file(out_vid)}}],
        }
        delivery._validate_render_step(receipt)

        bad_editor = copy.deepcopy(receipt)
        bad_editor["editor"] = "unknown_nle"
        with self.assertRaises(ValueError):
            delivery._validate_render_step(bad_editor)

        bad_hash = copy.deepcopy(receipt)
        bad_hash["project_file_ref"]["sha256"] = "1" * 64
        with self.assertRaises(ValueError):
            delivery._validate_render_step(bad_hash)

    # -------------------------------------------------------------------------
    # G08: Non-Video Package Receipt Verification
    # -------------------------------------------------------------------------
    def test_g08_article_package_receipt_verification(self):
        article_desk = desk.new_project("article-desk-test", "测试文章排版验收", ["xiaohongshu"])
        article_desk["items"][0]["item_kind"] = "article"
        article_desk["items"][0]["cover_pk"] = {"requested": False, "not_requested_reason": "图文长文无封面PK"}
        body_file = self.root / "article_body.html"
        body_file.write_text("<p>文章正文内容</p>", encoding="utf-8")
        body_sha = hashlib.sha256(body_file.read_bytes()).hexdigest()
        article_desk["items"][0]["body_html"] = {"path": str(body_file), "sha256": body_sha}
        article_desk["items"][0]["platforms"]["xiaohongshu"]["fields"]["title"] = "文章标题"
        article_desk["items"][0]["platforms"]["xiaohongshu"]["fields"]["body"] = "文章正文内容"
        article_desk["items"][0]["platforms"]["xiaohongshu"]["fields"]["tags"] = "理财,笔记"

        package_doc = {
            "schema_version": "self-media-entry-selection.v1",
            "article_review_package": {
                "rendered_artifacts_verified": True,
                "visual_review": {"record_complete": True},
                "editorial": {"author_confirmation_recorded": True},
                "rendered_outputs": [{"path": str(body_file), "sha256": body_sha}],
            },
        }
        pkg_file = self.root / "article_package.json"
        pkg_file.write_text(json.dumps(package_doc, ensure_ascii=False), encoding="utf-8")

        html = desk.render(article_desk, package_receipt=str(pkg_file))
        self.assertIn("data-state=\"verified_at_generation\"", html)
        self.assertNotIn("请勿直接复制用于正式发布", html)

        bad_pkg = copy.deepcopy(package_doc)
        bad_pkg["article_review_package"]["rendered_outputs"][0]["sha256"] = "0" * 64
        bad_pkg_file = self.root / "bad_pkg.json"
        bad_pkg_file.write_text(json.dumps(bad_pkg, ensure_ascii=False), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "article_package_body_html_mismatch"):
            desk.render(article_desk, package_receipt=str(bad_pkg_file))

    # -------------------------------------------------------------------------
    # G09a: mark-published Atomic Recording
    # -------------------------------------------------------------------------
    def test_g09a_mark_published_atomic_flow(self):
        project = desk.new_project("mark-pub-test", "测试发布记录", ["douyin", "xiaohongshu"])
        desk_path = self.root / "desk.json"
        desk.write_new(desk_path, project)

        msg_path = self.root / "user_msg.json"
        msg_path.write_text(json.dumps({
            "role": "user",
            "text": "今天上午已经在抖音和小红书手动发布了这一版，请记录。",
        }, ensure_ascii=False), encoding="utf-8")

        out_dir = self.root / "pub-output"
        receipt = agent.mark_published(
            desk_path=desk_path,
            platforms=["douyin", "xiaohongshu"],
            user_message_path=msg_path,
            quote="已经在抖音和小红书手动发布了这一版",
            output_dir=out_dir,
        )
        self.assertEqual(receipt["status"], "manual_publication_recorded")
        self.assertEqual(receipt["publication_mode"], "manual_fill_only_no_ai_prefill")
        self.assertEqual(receipt["early_snapshot_window_hours"], [48, 72])
        self.assertTrue((out_dir / "publication-fact.json").is_file())
        self.assertTrue((out_dir / "publication-data.published.json").is_file())
        self.assertTrue((out_dir / "publication.work-request.json").is_file())

    def _g09_state_fixture(self, label):
        quote = "抖音已经发布了这一版"
        desk_path = self.ref(desk.new_project(f"pub-{label}", "合成发布记录", ["douyin"]))["path"]
        message = self.ref({"role": "user", "text": quote})
        state = self.ref({"owner_notes": "旧值保留", "publicationPreparation": {"published": False}})
        root = self.root / label
        root.mkdir()
        (root / "existing.txt").write_bytes(b"keep")
        return dict(
            desk_path=Path(desk_path), platforms=["douyin"], user_message_path=Path(message["path"]),
            quote=quote, output_dir=root, state_path=Path(state["path"]), expected_state_sha256=state["sha256"],
        )

    def test_g09_partial_write_rolls_back_only_owned_outputs(self):
        exclusive_name = "rename" if os.name == "nt" else "link"
        exclusive_write, atomic_replace = getattr(os, exclusive_name), os.replace
        for failed_name in ("publication-data.published.json", "state-sync-receipt.json", "STATE"):
            with self.subTest(failed_name=failed_name):
                args = self._g09_state_fixture(failed_name)
                original_state = args["state_path"].read_bytes()
                receipt_output = self.root / f"optional-{failed_name}"

                def exclusive(src, dst):
                    if Path(dst).name == failed_name:
                        raise OSError("synthetic publication write failure")
                    return exclusive_write(src, dst)

                def replace(src, dst):
                    if failed_name == "STATE" and Path(dst) == args["state_path"]:
                        raise OSError("synthetic publication write failure")
                    return atomic_replace(src, dst)

                with patch.object(os, exclusive_name, side_effect=exclusive), patch.object(os, "replace", side_effect=replace):
                    with self.assertRaisesRegex(OSError, "synthetic publication write failure"):
                        agent.mark_published(**args, receipt_output=receipt_output)
                self.assertEqual(args["state_path"].read_bytes(), original_state)
                self.assertEqual({child.name for child in args["output_dir"].iterdir()}, {"existing.txt"})
                self.assertEqual((args["output_dir"] / "existing.txt").read_bytes(), b"keep")
                self.assertFalse(receipt_output.exists())
                self.assertFalse(list(self.root.glob(".mark-published-*")))
                receipt = agent.mark_published(**args, receipt_output=receipt_output)
                self.assertEqual(receipt["status"], "manual_publication_recorded")
                self.assertTrue(receipt_output.is_file())

    def test_g09_state_drift_preserves_newer_state_and_rolls_back(self):
        args = self._g09_state_fixture("state-drift")
        original_sync = entry_selection.sync_project
        newer = b'{"owner_notes":"newer"}'

        def write_newer_state(*pos, **kw):
            result = original_sync(*pos, **kw)
            args["state_path"].write_bytes(newer)
            return result

        with patch.object(entry_selection, "sync_project", side_effect=write_newer_state):
            with self.assertRaises(agent.AgentEntryError) as failure:
                agent.mark_published(**args)
        self.assertEqual(failure.exception.code, "project_state_drift")
        self.assertEqual(args["state_path"].read_bytes(), newer)
        self.assertEqual({path.name for path in args["output_dir"].iterdir()}, {"existing.txt"})

    def test_g09_state_receipt_references_final_files_in_both_modes(self):
        for apply in (True, False):
            with self.subTest(apply=apply):
                args = self._g09_state_fixture(f"state-{apply}")
                old_bytes = args["state_path"].read_bytes()
                target = args["state_path"] if apply else self.root / "state-projection.json"
                receipt_output = self.root / f"complete-{apply}.json"
                state_flags = {"apply_state": True} if apply else {"state_output": target}
                receipt = agent.mark_published(**args, **state_flags, receipt_output=receipt_output)
                report = agent.load_json(args["output_dir"] / "state-sync-receipt.json")
                request = Path(report["request_ref"]["path"])
                self.assertEqual(agent.load_json(receipt_output), receipt)
                self.assertEqual(report, receipt["state_sync_receipt"])
                self.assertEqual(report["target_ref"], {"path": str(target), "sha256": agent.sha256_file(target)})
                self.assertEqual(request, args["output_dir"] / "publication.work-request.json")
                self.assertEqual(report["request_ref"]["sha256"], agent.sha256_file(request))
                current = agent.load_json(request)["current"]["publication_data"]
                data = agent.load_json(Path(current["path"]))
                self.assertEqual(agent.sha256_file(Path(current["path"])), current["sha256"])
                self.assertEqual(desk.publication_summary(data)["platforms"], ["douyin"])
                updated = agent.load_json(target)
                self.assertEqual(updated["workflow_current"]["request_ref"], report["request_ref"])
                self.assertEqual(updated["owner_notes"], "旧值保留")
                self.assertFalse(updated["publicationPreparation"]["published"])
                self.assertEqual(agent.load_json(args["output_dir"] / "state-sync-receipt.state-before.json"),
                                 json.loads(old_bytes))
                if not apply:
                    self.assertEqual(args["state_path"].read_bytes(), old_bytes)
                before_repeat = target.read_bytes()
                with self.assertRaises(agent.AgentEntryError) as failure:
                    agent.mark_published(**args, **state_flags, receipt_output=receipt_output)
                self.assertEqual(failure.exception.code, "mark_published_output_exists")
                self.assertEqual(target.read_bytes(), before_repeat)

    def test_g09_cli_optional_receipt_uses_the_same_commit(self):
        args = self._g09_state_fixture("cli-state")
        output = self.root / "cli-receipt.json"
        argv = [
            "self_media_agent.py", "mark-published", "--desk", str(args["desk_path"]),
            "--platforms", *args["platforms"], "--user-message", str(args["user_message_path"]),
            "--quote", args["quote"], "--output-dir", str(args["output_dir"]),
            "--state", str(args["state_path"]), "--expected-state-sha256", args["expected_state_sha256"],
            "--apply", "--output", str(output),
        ]
        with patch.object(sys, "argv", argv):
            self.assertEqual(agent.main(), 0)
        receipt = agent.load_json(output)
        self.assertEqual(receipt["status"], "manual_publication_recorded")
        self.assertEqual(receipt["state_sync_receipt"]["target_ref"]["sha256"], agent.sha256_file(args["state_path"]))
        originals = (output.read_bytes(), args["state_path"].read_bytes())
        error_output = io.StringIO()
        with patch.object(sys, "argv", argv), redirect_stdout(error_output):
            self.assertEqual(agent.main(), 2)
        self.assertEqual(json.loads(error_output.getvalue())["error_code"], "mark_published_output_exists")
        self.assertEqual((output.read_bytes(), args["state_path"].read_bytes()), originals)

    # -------------------------------------------------------------------------
    # G09b: editorial_integrity carry-over
    # -------------------------------------------------------------------------
    def test_g09b_editorial_integrity_carry_over(self):
        db_path = self.root / "synthetic.sqlite3"
        source_file = self.root / "source.md"
        source_file.write_text("Synthetic source: a plan, not an existing product. Exact author declaration.", encoding="utf-8")
        source_ev = {**author.ref(source_file), "quote": "a plan, not an existing product"}

        context_data = author.prepare_context(db_path, {
            "content_id": "synth-c01",
            "account_id": "synth-acc",
            "genre": "spoken_script",
            "synthetic_only": True,
            "privacy_status": "non_sensitive",
            "source_ref": "synth:source",
            "judgments": [],
        }, "synth-req")
        context_file = self.root / "author_context.json"
        context_file.write_text(json.dumps(context_data, ensure_ascii=False), encoding="utf-8")

        fact_card_file = self.root / "synthetic-fact-card.json"
        fact_card_file.write_text(json.dumps({
            "schema": "content-fact-card.v0",
            "content_id": "synth-c01",
            "canonical_status": "locked_for_draft",
            "human_confirmation": {"quote": "Synthetic G09b fact confirmation"},
        }, ensure_ascii=False), encoding="utf-8")
        preflight_data = {
            "route": "expository",
            "actor": "synthetic_fixture",
            "source": source_ev,
            "fact_card_ref": author.ref(fact_card_file),
            "items": [{"id": k, "state": "ready", "reason": "Preparation: " + k, "evidence": [source_ev]}
                      for k in sorted(editorial.PRE)],
        }
        editorial.record_preflight(context_file, preflight_data)

        # Revision 1
        draft1_file = self.root / "draft1.md"
        draft1_file.write_text("I want to build a model.\nIt is a plan, not an existing product.\nConclusion.", encoding="utf-8")
        rev1_envelope = author.revision_envelope(db_path, context_file, draft1_file, {
            "before": "",
            "reasons": [{"actor": "assistant", "text": "Draft 1", "source_ref": "test:rev"}],
            "source_ref": "test:rev",
            "privacy_status": "non_sensitive",
        })
        rev1_file = self.root / "rev1.json"
        rev1_file.write_text(json.dumps(rev1_envelope, ensure_ascii=False), encoding="utf-8")

        # Review 1
        review1_checks = [{
            "id": c,
            "state": "retained",
            "scope": "script-text",
            "quote": "It is a plan",
            "reason": "Preserves planned status: " + c,
            "evidence": [source_ev],
            "issue_ids": [],
            "reuse_from": None,
        } for c in sorted(editorial.CHECKS)]
        review1_checks[0]["purpose_alignment"] = {
            "stage_duty": "Help readers understand proposed project.",
            "contribution": "Identifies as plan instead of product.",
            "misunderstanding_risk": "Could mistake aspiration for product.",
            "tradeoff": "Retain modest wording.",
        }
        review1_data = {
            "request_id": "synth-req",
            "draft_ref": rev1_envelope["draft_ref"],
            "phase": "draft",
            "route": "expository",
            "previous_review_id": None,
            "feedback_ids": [],
            "changes": [],
            "actor": "synthetic_fixture",
            "source": source_ev,
            "issues": [],
            "observations": {"readthrough": None, "final_media": None},
            "checks": review1_checks,
        }
        rec1 = editorial.record_review(rev1_file, review1_data)
        self.assertTrue(rec1["checks_complete"])

        # Revision 2 (Wording polish)
        draft2_file = self.root / "draft2.md"
        draft2_file.write_text("I want to build a model.\nIt is a plan, not an existing product with polished wording.\nConclusion.", encoding="utf-8")
        rev2_envelope = author.revision_envelope(db_path, context_file, draft2_file, {
            "before": draft1_file.read_text(encoding="utf-8"),
            "reasons": [{"actor": "assistant", "text": "Draft 2 polish", "source_ref": "test:rev2"}],
            "source_ref": "test:rev2",
            "privacy_status": "non_sensitive",
        })
        rev2_file = self.root / "rev2.json"
        rev2_file.write_text(json.dumps(rev2_envelope, ensure_ascii=False), encoding="utf-8")

        # Carry-over for Revision 2 with changes=["wording"]
        template_file = self.root / "carry_over_template.json"
        carry_res = editorial.carry_over(rev2_file, ["wording"], template_file, actor="synthetic_fixture")
        self.assertEqual(carry_res["status"], "carry_over_template_generated")
        self.assertIn("C02", carry_res["carried_over_checks"])
        self.assertIn("C03", carry_res["carried_over_checks"])
        self.assertIn("C01", carry_res["affected_checks_requiring_evaluation"])
        self.assertIn("C04", carry_res["affected_checks_requiring_evaluation"])

        # Fill affected checks and record review 2
        tpl = carry_res["template"]
        for chk in tpl["checks"]:
            if chk["id"] in carry_res["affected_checks_requiring_evaluation"]:
                chk["state"] = "retained"
                chk["quote"] = "It is a plan"
                chk["reason"] = f"Re-checked after wording change for {chk['id']}"
                chk["evidence"] = [source_ev]
                if chk["id"] == "C01":
                    chk["purpose_alignment"] = {
                        "stage_duty": "Help readers understand proposed project.",
                        "contribution": "Identifies as plan instead of product.",
                        "misunderstanding_risk": "Could mistake aspiration for product.",
                        "tradeoff": "Retain modest wording.",
                    }
        rec2 = editorial.record_review(rev2_file, tpl)
        self.assertTrue(rec2["checks_complete"])

    # -------------------------------------------------------------------------
    # G02: Residual Loophole Fixes & Auto Risk Flags
    # -------------------------------------------------------------------------
    def test_g02_insurance_identity_overlay_does_not_bypass_terms_review(self):
        manifest_with_identity = self.ref({
            "schema": "self-media.video-delivery.v1",
            "identity_overlay": {"decision": "required", "reason": "Mandatory identity badge"},
        })
        req = {
            "schema_version": "self-media-work-request.v1",
            "request_id": "test-insurance-loophole-01",
            "requested_output": "finished_video",
            "platform": "douyin",
            "selection_basis": "合成防绕过测试",
            "risk_flags": {"insurance_terms": True},
            "current": {
                "delivery_manifest": manifest_with_identity,
            },
        }
        res = entry_selection.resolve(req, agent)
        self.assertEqual(res["status"], "needs_context")
        self.assertIn("insurance_compliance_review", res["missing_inputs"])

    def test_g02_topic_domain_insurance_and_medical_auto_risk_flags(self):
        base_ctx = json.loads((ROOT / "fixtures/creation-route-v1/same-day-activity-highlights.context.json").read_text(encoding="utf-8"))
        base_ctx.update(task_id="topic-ins-01", topic_domain="insurance")
        req_ins = {
            "schema_version": "self-media-work-request.v1",
            "request_id": "topic-ins-01",
            "requested_output": "article",
            "platform": "wechat-article",
            "selection_basis": "合成保险选题域测试",
            "current": {
                "creation_context": self.ref(base_ctx),
            },
        }
        res_ins = entry_selection.resolve(req_ins, agent)
        self.assertIn("insurance_compliance_review", res_ins["missing_inputs"])

        base_ctx_med = dict(base_ctx, task_id="topic-med-01", topic_domain="medical")
        req_med = {
            "schema_version": "self-media-work-request.v1",
            "request_id": "topic-med-01",
            "requested_output": "article",
            "platform": "wechat-article",
            "selection_basis": "合成医疗选题域测试",
            "current": {
                "creation_context": self.ref(base_ctx_med),
            },
        }
        res_med = entry_selection.resolve(req_med, agent)
        self.assertIn("science_popularization_review", res_med["missing_inputs"])

    def test_g02_insurance_review_rejects_bare_not_applicable_and_badge_status(self):
        # 1. 裸 not_applicable 不能在明确涉及保险条款时冒充通过
        req_na = {
            "schema_version": "self-media-work-request.v1",
            "request_id": "test-ins-na-01",
            "requested_output": "article",
            "platform": "wechat-article",
            "selection_basis": "合成保险裸not_applicable拦截测试",
            "risk_flags": {"insurance_terms": True},
            "current": {
                "insurance_review": self.ref({"decision": "not_applicable"}),
            },
        }
        res_na = entry_selection.resolve(req_na, agent)
        self.assertEqual(res_na["status"], "needs_context")
        self.assertIn("insurance_compliance_review", res_na["missing_inputs"])

        # 2. 仅有角标/元数据 status（如 status='passed'）缺少合规 decision 不能冒充审核通过
        req_status = {
            "schema_version": "self-media-work-request.v1",
            "request_id": "test-ins-status-01",
            "requested_output": "article",
            "platform": "wechat-article",
            "selection_basis": "合成角标status冒充拦截测试",
            "risk_flags": {"insurance_terms": True},
            "current": {
                "insurance_review": self.ref({"status": "passed"}),
            },
        }
        res_status = entry_selection.resolve(req_status, agent)
        self.assertEqual(res_status["status"], "needs_context")
        self.assertIn("insurance_compliance_review", res_status["missing_inputs"])

        # 3. 跨项目/不同项目证据必须阻断
        manifest = self.ref({
            "schema": "self-media.video-delivery.v1",
            "project_id": "proj-alpha",
        })
        req_proj_conflict = {
            "schema_version": "self-media-work-request.v1",
            "request_id": "test-ins-proj-conflict-01",
            "requested_output": "finished_video",
            "platform": "douyin",
            "selection_basis": "合成跨项目保险证据拦截测试",
            "risk_flags": {"insurance_terms": True},
            "current": {
                "delivery_manifest": manifest,
                "insurance_review": self.ref({"decision": "approved", "project_id": "proj-beta"}),
            },
        }
        res_conflict = entry_selection.resolve(req_proj_conflict, agent)
        self.assertEqual(res_conflict["status"], "needs_context")
        self.assertIn("insurance_compliance_review", res_conflict["missing_inputs"])

    def test_g02_explicit_false_cannot_bypass_domain_risk_gate(self):
        # 1. 即使显式关闭旗标，已绑定的保险选题域仍须触发审核
        base_ctx = json.loads((ROOT / "fixtures/creation-route-v1/same-day-activity-highlights.context.json").read_text(encoding="utf-8"))
        base_ctx.update(task_id="topic-ins-conflict-01", topic_domain="insurance")
        req_override = {
            "schema_version": "self-media-work-request.v1",
            "request_id": "topic-ins-conflict-01",
            "requested_output": "article",
            "platform": "wechat-article",
            "selection_basis": "合成显式False及冲突题材绕过防御测试",
            "risk_flags": {"insurance_terms": False},  # 显式 False 尝试掩盖
            "current": {
                "creation_context": self.ref(base_ctx),
            },
        }
        res_override = entry_selection.resolve(req_override, agent)
        self.assertEqual(res_override["status"], "needs_context")
        self.assertIn("insurance_compliance_review", res_override["missing_inputs"])

        # 2. 单一正常财务题材（finance）未声明保险条款时不无端升级为保险合规审核
        base_ctx_fin = json.loads((ROOT / "fixtures/creation-route-v1/same-day-activity-highlights.context.json").read_text(encoding="utf-8"))
        base_ctx_fin.update(task_id="topic-fin-01", topic_domain="finance")
        req_fin = {
            "schema_version": "self-media-work-request.v1",
            "request_id": "topic-fin-01",
            "requested_output": "article",
            "platform": "wechat-article",
            "selection_basis": "合成单一财务题材不强化测试",
            "current": {
                "creation_context": self.ref(base_ctx_fin),
            },
        }
        res_fin = entry_selection.resolve(req_fin, agent)
        self.assertNotIn("insurance_compliance_review", res_fin.get("missing_inputs", []))

    # -------------------------------------------------------------------------
    # G09: Residual Loophole Fixes - Scheduled Message & Platform Quote Binding
    # -------------------------------------------------------------------------
    def test_g09_scheduled_message_rejected_by_mark_published(self):
        project = desk.new_project("mark-pub-sched-test", "测试定时稿拦截", ["xiaohongshu"])
        desk_path = self.root / "desk-sched.json"
        desk.write_new(desk_path, project)

        msg_path = self.root / "user_msg_sched.json"
        msg_path.write_text(json.dumps({
            "role": "user",
            "text": "小红书已经设了定时，还没发布",
        }, ensure_ascii=False), encoding="utf-8")

        out_dir = self.root / "pub-output-sched"
        with self.assertRaises(agent.AgentEntryError) as cm:
            agent.mark_published(
                desk_path=desk_path,
                platforms=["xiaohongshu"],
                user_message_path=msg_path,
                quote="小红书已经设了定时，还没发布",
                output_dir=out_dir,
            )
        self.assertEqual(cm.exception.code, "publication_fact_scheduled_not_published")
        self.assertFalse(out_dir.exists() and any(out_dir.iterdir()))

    def test_g09_unconfirmed_platform_in_quote_rejected(self):
        project = desk.new_project("mark-pub-unconf-test", "测试未提及平台拦截", ["douyin", "xiaohongshu"])
        desk_path = self.root / "desk-unconf.json"
        desk.write_new(desk_path, project)

        msg_path = self.root / "user_msg_unconf.json"
        msg_path.write_text(json.dumps({
            "role": "user",
            "text": "小红书已经手动发布了这一版，请记录。",
        }, ensure_ascii=False), encoding="utf-8")

        out_dir = self.root / "pub-output-unconf"
        with self.assertRaises(agent.AgentEntryError) as cm:
            agent.mark_published(
                desk_path=desk_path,
                platforms=["douyin", "xiaohongshu"],
                user_message_path=msg_path,
                quote="小红书已经手动发布了这一版",
                output_dir=out_dir,
            )
        self.assertEqual(cm.exception.code, "publication_fact_platform_unconfirmed_in_quote")
        self.assertFalse(out_dir.exists() and any(out_dir.iterdir()))

    def test_g09_quote_binds_completed_action_to_exact_platform(self):
        valid = (
            ("已经在抖音和小红书手动发布了这一版", ["douyin", "xiaohongshu"], None),
            ("抖音已发，小红书已发", ["douyin", "xiaohongshu"], None),
            ("我发了抖音", ["douyin"], None),
            ("抖音已发", ["douyin"], "抖音已发。小红书设置明天发。"),
            ("抖音已发", ["douyin"], "抖音已发，小红书还没发。"),
            ("微信视频号已手动发布", ["weixin_channels"], None),
            ("视频号发布成功", ["weixin_channels"], None),
        )
        for quote, platforms, source in valid:
            with self.subTest(quote=quote, platforms=platforms):
                desk.verify_publication_quote_scope(quote, platforms, source)
        pending = "publication_fact_scheduled_not_published"
        scope = "publication_fact_platform_unconfirmed_in_quote"
        invalid = (
            ("抖音请手动发布", ["douyin"], None, pending),
            ("小红书今天发", ["xiaohongshu"], None, pending),
            ("小红书设置明天发", ["xiaohongshu"], None, pending),
            ("抖音已发布", ["douyin"], "抖音已发布？", pending),
            ("抖音已发布", ["douyin"], "如果抖音已发布，记录一下。", pending),
            ("抖音已发布", ["douyin"], "有人说抖音已发布，但实际还在排期。", pending),
            ("抖音已发", ["douyin"], "抖音已发，但还没发出去。", pending),
            ("抖音已发", ["douyin"], "抖音已发。更正：还没发。", pending),
            ("全平台已发", ["douyin"], None, scope),
            ("I have published it today", ["douyin"], None, scope),
            ("我在TikTok发布了", ["douyin"], None, scope),
            ("抖音转发 小红书已发布", ["douyin", "xiaohongshu"], None, scope),
            ("抖音已发", [], None, "publication_fact_platform_scope_invalid"),
        )
        for quote, platforms, source, expected in invalid:
            with self.subTest(quote=quote, source=source):
                with self.assertRaisesRegex(ValueError, expected):
                    desk.verify_publication_quote_scope(quote, platforms, source)

    def test_g09_clipped_source_cannot_write_or_reopen_as_published(self):
        args = self._g09_state_fixture("clipped-source")
        source = self.ref({"role": "user", "text": "抖音已经发布了这一版吗？我只设了定时。"})
        args["user_message_path"] = Path(source["path"])
        initial_state = args["state_path"].read_bytes()
        with self.assertRaises(agent.AgentEntryError) as failure:
            agent.mark_published(**args)
        self.assertEqual(failure.exception.code, "publication_fact_scheduled_not_published")
        self.assertEqual(args["state_path"].read_bytes(), initial_state)
        self.assertEqual({path.name for path in args["output_dir"].iterdir()}, {"existing.txt"})

        data = agent.load_json(args["desk_path"])
        for platforms in (["douyin"], []):
            with self.subTest(platforms=platforms):
                data["publication_fact_ref"] = self.ref({
                    "schema_version": "self-media.publication-fact.v1",
                    "project_id": data["project_id"],
                    "kind": "user_reported_published",
                    "video_sha256": "",
                    "source_ref": source,
                    "quote": args["quote"],
                    "platforms": platforms,
                })
                with self.assertRaisesRegex(ValueError, "publication_fact_scheduled_not_published"):
                    desk.publication_summary(data)

    # -------------------------------------------------------------------------
    # G03: Chinese & Arabic Number Normalization & Multi-Tier Metrics
    # -------------------------------------------------------------------------
    def test_g03_cross_platform_number_normalization_chinese_and_arabic(self):
        project = desk.new_project("metric-cn-test", "测试中文大写与阿拉伯数字等价", ["douyin", "xiaohongshu"])
        item = project["items"][0]
        item["platforms"]["douyin"]["fields"]["body"] = "真实记录：普通人保额20万元也能理财。"
        item["platforms"]["xiaohongshu"]["fields"]["body"] = "真实记录：普通人保额 20 万元也能理财。"
        report = desk.check_platforms(project, "preparation")
        metric_issues = [iss for iss in report["review_items"] if iss["code"] == "cross_platform_fact_inconsistent"]
        self.assertEqual(metric_issues, [])

    def test_g03_multi_tier_metric_sets_consistency(self):
        project = desk.new_project("multi-tier-test", "测试多方案保额一致", ["douyin", "xiaohongshu"])
        item = project["items"][0]
        item["platforms"]["douyin"]["fields"]["body"] = "方案说明：基础版保额10万，尊享版保额50万。"
        item["platforms"]["xiaohongshu"]["fields"]["body"] = "方案说明：基础版保额10万，尊享版保额50万。"
        report = desk.check_platforms(project, "preparation")
        metric_issues = [iss for iss in report["review_items"] if iss["code"] == "cross_platform_fact_inconsistent"]
        self.assertEqual(metric_issues, [])

    # -------------------------------------------------------------------------
    # G06: Multi-Source Undeclared Duration Coverage
    # -------------------------------------------------------------------------
    def test_g06_rough_cut_coverage_multiple_sources_undeclared(self):
        timeline_doc = {
            "source_duration_seconds": 60.0,
            "sources": [{"sha256": "a" * 64, "duration_seconds": 60.0}],
            "segments": [
                {"source_ref": {"path": "raw_a.mp4", "sha256": "a" * 64}, "source_start": 0.0, "source_end": 60.0, "target_start": 0.0, "target_end": 60.0},
                {"source_ref": {"path": "raw_b.mp4", "sha256": "b" * 64}, "source_start": 0.0, "source_end": 10.0, "target_start": 60.0, "target_end": 70.0},
            ],
            "discarded_ranges": [],
        }
        coverage = rcc.source_coverage_gaps(timeline_doc)
        self.assertFalse(coverage["checked"])
        self.assertFalse(coverage["all_sources_declared"])
        self.assertIn("b" * 64, coverage["undeclared_sources"])
        self.assertTrue(coverage["review_needed"])
        timeline_doc["sources"] = []
        unbound_duration = rcc.source_coverage_gaps(timeline_doc)
        self.assertEqual(unbound_duration["undeclared_sources"], ["a" * 64, "b" * 64])

        audit = {
            "candidate": {"path": "cand.mp4", "sha256": "c" * 64},
            "technical": {"duration": 70.0, "candidates": []},
            "comparison": {"changes": [], "omitted_phrase_candidates": [], "repetition_candidates": []},
            "source_coverage": coverage,
        }
        items = rcc.review_items(audit)
        undeclared_items = [it for it in items if "未登记总时长的原片素材" in it["review_question"]]
        self.assertTrue(len(undeclared_items) > 0)

    def test_g06_unbound_discarded_range_is_a_manual_review(self):
        first, second = "a" * 64, "b" * 64
        discarded = {"start": 10.0, "end": 20.0, "reason": "合成弃用区间"}
        coverage = rcc.source_coverage_gaps({
            "sources": [{"sha256": sha, "duration_seconds": 20.0} for sha in (first, second)],
            "segments": [
                {"source_ref": {"path": f"{sha[0]}.mp4", "sha256": sha},
                 "source_start": 0.0, "source_end": 10.0, "target_start": start, "target_end": start + 10.0}
                for sha, start in ((first, 0.0), (second, 10.0))
            ],
            "discarded_ranges": [discarded],
        })
        self.assertTrue(coverage["review_needed"])
        self.assertEqual(coverage["unassigned_discarded_ranges"], [discarded])
        self.assertEqual({gap["source_sha256"] for gap in coverage["uncovered_gaps"]}, {first, second})
        items = rcc.review_items({
            "candidate": {"path": "cand.mp4", "sha256": "c" * 64},
            "technical": {"duration": 20.0, "candidates": []},
            "comparison": {"changes": [], "omitted_phrase_candidates": [], "repetition_candidates": []},
            "source_coverage": coverage,
        })
        self.assertTrue(any("尚未绑定原片" in item["review_question"] for item in items))

    # -------------------------------------------------------------------------
    # G05: Stage 3 Final Audit Requires Verification Evidence
    # -------------------------------------------------------------------------
    def test_g05_stage_3_final_audit_requires_verified_manifest_not_just_presence(self):
        src = self.ref({"purpose": "Synthetic purpose", "audience": "Synthetic audience"})
        purpose_manifest = self.ref({
            "schema_version": "self-media-context-input.v1",
            "task_id": "flow-progress-stage3",
            "stage": "draft",
            "budget": {"max_inline_bytes": 4096},
            "artifacts": [{"artifact_id": "purpose-source", "role": "source_manifest", "path": Path(src["path"]).name, "expected_sha256": src["sha256"], "load_mode": "reference"}],
            "editorial_context": {
                "version": 1,
                "content_id": "test-c1",
                "topic_selection": {
                    "topic": "Personal choice",
                    "origin": "tool_trial",
                    "adoption": "selected",
                    "adoption_basis": "Synthetic test only",
                    "origin_source": {"artifact_id": "purpose-source", "quote": "Synthetic purpose"},
                    "adoption_source": {"artifact_id": "purpose-source", "quote": "Synthetic purpose"},
                },
                "purpose": {"artifact_id": "purpose-source", "quote": "Synthetic purpose"},
                "audience": {"artifact_id": "purpose-source", "quote": "Synthetic audience"},
                "stage_duty": "Explain principles simply.",
                "current_body_artifact_id": "purpose-source",
                "feedback": [],
                "feedback_note": "No feedback in this fixture.",
            },
        })
        decision = self.ref({"status": "ready", "primary_route": "expository", "vlog_style": "chronological-diary"})
        author_rev = self.ref({"revision": 1, "body": "Draft revision text"})
        unverified_manifest = self.ref({
            "schema": "self-media.video-delivery.v1",
            "identity_overlay": {"decision": "required"},
        })
        req = {
            "schema_version": "self-media-work-request.v1",
            "request_id": "flow-progress-stage3",
            "requested_output": "script",
            "platform": "douyin",
            "content_format": "spoken-script",
            "selection_basis": "合成交付审核测试",
            "current": {
                "context_manifest": purpose_manifest,
                "creation_decision": decision,
                "author_revision": author_rev,
                "delivery_manifest": unverified_manifest,
            },
        }
        res = entry_selection.resolve(req, agent)
        lw = res.get("lightweight_workflow")
        self.assertIsNotNone(lw)
        self.assertIn("stage_1_charter", lw["completed_stages"])
        self.assertIn("stage_2_production", lw["completed_stages"])
        self.assertNotIn("stage_3_final_audit", lw["completed_stages"])
        self.assertEqual(lw["current_stage"], "stage_3_final_audit")
        self.assertEqual(lw["stage_details"]["stage_3_final_audit"]["status"], "pending_review")
        self.assertTrue(lw["stage_details"]["stage_3_final_audit"]["artifact_present"])
        self.assertFalse(lw["stage_details"]["stage_3_final_audit"]["verified"])

    # -------------------------------------------------------------------------
    # G02 & G09 Second-Order Adversarial Closures (2026-11-20 Evening)
    # -------------------------------------------------------------------------
    def test_g02_risk_reviews_require_explicit_binding_and_decision(self):
        unbound = self.ref({"decision": "approved"})
        status_only = self.ref({"status": "approved", "request_id": "test-bind-all-01"})
        wrong_req = self.ref({"decision": "approved", "request_id": "other-request-99"})
        wrong_proj_no_expected = self.ref({"decision": "approved", "project_id": "proj-unverified"})
        valid = self.ref({"decision": "approved", "request_id": "test-bind-all-01"})

        for review_ref in (unbound, status_only, wrong_req, wrong_proj_no_expected):
            req = {
                "schema_version": "self-media-work-request.v1",
                "request_id": "test-bind-all-01",
                "requested_output": "article",
                "platform": "wechat-article",
                "selection_basis": "合成风险门强绑定测试",
                "risk_flags": {
                    "insurance_terms": True,
                    "medical_claims": True,
                    "customer_case": True,
                    "third_party_copyright": True,
                },
                "current": {
                    "insurance_review": review_ref,
                    "science_review": review_ref,
                    "privacy_review": review_ref,
                    "rights_review": review_ref,
                },
            }
            res = entry_selection.resolve(req, agent)
            self.assertEqual(res["status"], "needs_context")
            for gate in (
                "insurance_compliance_review",
                "science_popularization_review",
                "privacy_treatment_review",
                "rights_authorization_review",
            ):
                self.assertIn(gate, res["missing_inputs"])

        req_ok = {
            "schema_version": "self-media-work-request.v1",
            "request_id": "test-bind-all-01",
            "requested_output": "article",
            "platform": "wechat-article",
            "selection_basis": "合成风险门强绑定正例",
            "risk_flags": {
                "insurance_terms": True,
                "medical_claims": True,
                "customer_case": True,
                "third_party_copyright": True,
            },
            "current": {
                "insurance_review": valid,
                "science_review": valid,
                "privacy_review": valid,
                "rights_review": valid,
            },
        }
        res_ok = entry_selection.resolve(req_ok, agent)
        for gate in (
            "insurance_compliance_review",
            "science_popularization_review",
            "privacy_treatment_review",
            "rights_authorization_review",
        ):
            self.assertNotIn(gate, res_ok.get("missing_inputs", []))

    def test_g09_casual_subsequent_correction_sentence_blocked_and_other_platform_preserved(self):
        # 1. 口语更正句（不以“实际上/更正”开头）含定时信号，截断第一句也必须拦截
        with self.assertRaisesRegex(ValueError, "publication_fact_scheduled_not_published"):
            desk.verify_publication_quote_scope(
                "小红书已经发布了",
                ["xiaohongshu"],
                "小红书已经发布了。不对，刚看错后台了，其实是定时。",
            )
        # 2. 后续句提到已删除/取消，必须拦截
        with self.assertRaisesRegex(ValueError, "publication_fact_scheduled_not_published"):
            desk.verify_publication_quote_scope(
                "小红书已经发布了",
                ["xiaohongshu"],
                "小红书已经发布了。刚发现有错别字删掉了。",
            )
        # 3. 后续句明确只谈另一个平台未发，不应误拦已发布的小红书
        desk.verify_publication_quote_scope(
            "小红书已经发布了",
            ["xiaohongshu"],
            "小红书已经发布了。抖音还没发，明天再发。",
        )

    def test_g05_stage_3_delivery_manifest_requires_bound_files_and_matching_acceptance_fingerprint(self):
        src = self.ref({"purpose": "Synthetic purpose", "audience": "Synthetic audience"})
        purpose_manifest = self.ref({
            "schema_version": "self-media-context-input.v1",
            "task_id": "flow-stage3-bound-01",
            "stage": "draft",
            "budget": {"max_inline_bytes": 4096},
            "artifacts": [{"artifact_id": "purpose-source", "role": "source_manifest", "path": Path(src["path"]).name, "expected_sha256": src["sha256"], "load_mode": "reference"}],
            "editorial_context": {
                "version": 1,
                "content_id": "test-c1",
                "topic_selection": {
                    "topic": "Personal choice",
                    "origin": "tool_trial",
                    "adoption": "selected",
                    "adoption_basis": "Synthetic test only",
                    "origin_source": {"artifact_id": "purpose-source", "quote": "Synthetic purpose"},
                    "adoption_source": {"artifact_id": "purpose-source", "quote": "Synthetic purpose"},
                },
                "purpose": {"artifact_id": "purpose-source", "quote": "Synthetic purpose"},
                "audience": {"artifact_id": "purpose-source", "quote": "Synthetic audience"},
                "stage_duty": "Explain principles simply.",
                "current_body_artifact_id": "purpose-source",
                "feedback": [],
                "feedback_note": "No feedback in this fixture.",
            },
        })
        decision = self.ref({"status": "ready", "primary_route": "expository", "vlog_style": "chronological-diary"})
        author_rev = self.ref({"revision": 1, "body": "Draft revision text"})

        def resolve_with_manifest(manifest_dict):
            req = {
                "schema_version": "self-media-work-request.v1",
                "request_id": "flow-stage3-bound-01",
                "requested_output": "script",
                "platform": "douyin",
                "content_format": "spoken-script",
                "selection_basis": "合成阶段三实文件核验测试",
                "current": {
                    "context_manifest": purpose_manifest,
                    "creation_decision": decision,
                    "author_revision": author_rev,
                    "delivery_manifest": self.ref(manifest_dict),
                },
            }
            return entry_selection.resolve(req, agent)["lightweight_workflow"]

        # 1. Fake/non-existent paths must NOT pass stage 3
        lw_fake = resolve_with_manifest({
            "schema": "self-media.video-delivery.v1",
            "acceptance_ref": {"path": "fake", "sha256": "0" * 64},
            "render_receipt_ref": {"path": "fake2", "sha256": "1" * 64},
        })
        self.assertFalse(lw_fake["stage_details"]["stage_3_final_audit"]["verified"])
        self.assertEqual(lw_fake["stage_details"]["stage_3_final_audit"]["status"], "pending_review")
        self.assertEqual(lw_fake["current_stage"], "stage_3_final_audit")

        render_ref = self.ref({"schema": "video_creation_pipeline.ffmpeg_execution_receipt.v1", "status": "completed"})
        base_manifest = {
            "schema": "self-media.video-delivery.v1",
            "project_id": "stage3-proj-01",
            "render_receipt_ref": render_ref,
        }
        expected_fp = delivery.acceptance_fingerprint(base_manifest)

        # 2. Stale/mismatched fingerprint acceptance must NOT pass stage 3
        stale_acc_ref = self.ref({
            "schema": "self-media.video-acceptance.v1",
            "reviewer_kind": "human",
            "decision": "pass",
            "reviewer": "Owner",
            "reviewed_at": "2026-11-20T12:00:00+08:00",
            "input_fingerprint": "f" * 64,
        })
        lw_stale = resolve_with_manifest({**base_manifest, "acceptance_ref": stale_acc_ref})
        self.assertFalse(lw_stale["stage_details"]["stage_3_final_audit"]["verified"])
        self.assertEqual(lw_stale["stage_details"]["stage_3_final_audit"]["status"], "pending_review")

        # 3. Rejected decision with matching fingerprint must NOT pass stage 3
        reject_acc_ref = self.ref({
            "schema": "self-media.video-acceptance.v1",
            "reviewer_kind": "human",
            "decision": "reject",
            "reviewer": "Owner",
            "reviewed_at": "2026-11-20T12:00:00+08:00",
            "input_fingerprint": expected_fp,
        })
        lw_reject = resolve_with_manifest({**base_manifest, "acceptance_ref": reject_acc_ref})
        self.assertFalse(lw_reject["stage_details"]["stage_3_final_audit"]["verified"])

        # 4. Tampered acceptance hash must NOT pass stage 3
        valid_acc_ref = self.ref({
            "schema": "self-media.video-acceptance.v1",
            "reviewer_kind": "human",
            "decision": "pass",
            "reviewer": "Owner",
            "reviewed_at": "2026-11-20T12:00:00+08:00",
            "input_fingerprint": expected_fp,
        })
        lw_tampered = resolve_with_manifest({
            **base_manifest,
            "acceptance_ref": {**valid_acc_ref, "sha256": "a" * 64},
        })
        self.assertFalse(lw_tampered["stage_details"]["stage_3_final_audit"]["verified"])

        # 5. Valid bound render receipt + matching human pass acceptance advances to stage 4
        lw_ok = resolve_with_manifest({**base_manifest, "acceptance_ref": valid_acc_ref})
        self.assertTrue(lw_ok["stage_details"]["stage_3_final_audit"]["verified"])
        self.assertEqual(lw_ok["stage_details"]["stage_3_final_audit"]["status"], "completed")
        self.assertIn("stage_3_final_audit", lw_ok["completed_stages"])
        self.assertEqual(lw_ok["current_stage"], "stage_4_manual_publish")

    def test_g05_stage_3_publication_page_build_requires_hash_bound_verified_html(self):
        src = self.ref({"purpose": "Synthetic purpose", "audience": "Synthetic audience"})
        purpose_manifest = self.ref({
            "schema_version": "self-media-context-input.v1",
            "task_id": "flow-stage3-page-01",
            "stage": "draft",
            "budget": {"max_inline_bytes": 4096},
            "artifacts": [{"artifact_id": "purpose-source", "role": "source_manifest", "path": Path(src["path"]).name, "expected_sha256": src["sha256"], "load_mode": "reference"}],
            "editorial_context": {
                "version": 1,
                "content_id": "test-c1",
                "topic_selection": {
                    "topic": "Personal choice",
                    "origin": "tool_trial",
                    "adoption": "selected",
                    "adoption_basis": "Synthetic test only",
                    "origin_source": {"artifact_id": "purpose-source", "quote": "Synthetic purpose"},
                    "adoption_source": {"artifact_id": "purpose-source", "quote": "Synthetic purpose"},
                },
                "purpose": {"artifact_id": "purpose-source", "quote": "Synthetic purpose"},
                "audience": {"artifact_id": "purpose-source", "quote": "Synthetic audience"},
                "stage_duty": "Explain principles simply.",
                "current_body_artifact_id": "purpose-source",
                "feedback": [],
                "feedback_note": "No feedback in this fixture.",
            },
        })
        decision = self.ref({"status": "ready", "primary_route": "expository", "vlog_style": "chronological-diary"})
        author_rev = self.ref({"revision": 1, "body": "Draft revision text"})

        draft_html = self.root / "draft-page.html"
        draft_html.write_text('<div data-state="draft">draft</div>', encoding="utf-8")
        verified_html = self.root / "verified-page.html"
        verified_html.write_text('<div data-state="verified_at_generation">ok</div>', encoding="utf-8")

        def resolve_with_build(build_dict):
            req = {
                "schema_version": "self-media-work-request.v1",
                "request_id": "flow-stage3-page-01",
                "requested_output": "script",
                "platform": "douyin",
                "content_format": "spoken-script",
                "selection_basis": "合成发布页阶段三核验",
                "current": {
                    "context_manifest": purpose_manifest,
                    "creation_decision": decision,
                    "author_revision": author_rev,
                    "publication_page_build": self.ref(build_dict),
                },
            }
            return entry_selection.resolve(req, agent)["lightweight_workflow"]

        # Draft page stays pending_review
        lw_draft = resolve_with_build({
            "schema_version": "self-media.publication-page-build.v1",
            "page_ref": {"path": str(draft_html), "sha256": agent.sha256_file(draft_html)},
        })
        self.assertFalse(lw_draft["stage_details"]["stage_3_final_audit"]["verified"])
        self.assertEqual(lw_draft["stage_details"]["stage_3_final_audit"]["status"], "pending_review")

        # Hash-tampered verified page stays pending_review
        lw_tampered = resolve_with_build({
            "schema_version": "self-media.publication-page-build.v1",
            "page_ref": {"path": str(verified_html), "sha256": "0" * 64},
        })
        self.assertFalse(lw_tampered["stage_details"]["stage_3_final_audit"]["verified"])

        # Bound verified_at_generation page completes stage 3
        lw_ok = resolve_with_build({
            "schema_version": "self-media.publication-page-build.v1",
            "page_ref": {"path": str(verified_html), "sha256": agent.sha256_file(verified_html)},
        })
        self.assertTrue(lw_ok["stage_details"]["stage_3_final_audit"]["verified"])
        self.assertEqual(lw_ok["current_stage"], "stage_4_manual_publish")


if __name__ == "__main__":
    unittest.main()
