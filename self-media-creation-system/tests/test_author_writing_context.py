"""Cross-process author-writing acceptance tests in an isolated local store.

All prose, author declarations and judgments below are invented test fixtures.
Some fixtures deliberately set synthetic_only=False to exercise the production
validation branch; they contain no real author/customer/health information and
must never be written to the default expression store.
"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import unittest
import uuid
from pathlib import Path
import editorial_fixture


ROOT = Path(__file__).resolve().parents[1]
STORE_SCRIPT = ROOT / "scripts" / "author_expression_store.py"
BRIDGE_SCRIPT = ROOT / "scripts" / "author_writing_context.py"
AGENT_SCRIPT = ROOT / "scripts" / "self_media_agent.py"


def sha_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class AuthorWritingContextAcceptanceTests(unittest.TestCase):
    original = "我反对把测试茶杯涂成金色。"
    weakened = "把测试茶杯涂成金色或许值得讨论。"

    def setUp(self) -> None:
        self.test_root = Path(os.environ.get('TEST_TMP_ROOT', ROOT / '.test-runtime')).resolve()
        self.runtime = self.test_root / ("author-writing-context-" + uuid.uuid4().hex)
        self.runtime.mkdir(parents=True)
        self.store = self.runtime / "isolated-test-store.sqlite3"
        self.counter = 0
        self.account = "invented-unit-test-account"
        self.genre = "moments"
        self.request_id = "invented-unit-test-request"
        self.default_store = ROOT / ".runtime" / "author-expression" / "store.sqlite3"
        self.default_before = self.default_store.stat().st_mtime_ns if self.default_store.exists() else None

    def tearDown(self) -> None:
        self.assertEqual(
            self.default_before,
            self.default_store.stat().st_mtime_ns if self.default_store.exists() else None,
            "test suite must not touch the real default store",
        )
        assert self.runtime.resolve().is_relative_to(self.test_root)
        shutil.rmtree(self.runtime)

    def path(self, suffix: str = ".json") -> Path:
        self.counter += 1
        return self.runtime / (f"artifact-{self.counter}" + suffix)

    def write(self, value: dict | list | str, suffix: str = ".json") -> Path:
        path = self.path(suffix)
        path.write_text(value if isinstance(value, str) else json.dumps(value, ensure_ascii=False), encoding="utf-8")
        return path

    def cli(self, script: Path, *args: str | Path, ok: bool = True) -> dict:
        result = subprocess.run(
            [sys.executable, str(script), *(str(value) for value in args)],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
            env={**os.environ, "PYTHONIOENCODING": "utf-8"}, timeout=30,
        )
        text = result.stdout or result.stderr
        if not text.strip() and "--output" in args:
            output = Path(args[args.index("--output") + 1])
            if output.is_file():
                text = output.read_text(encoding="utf-8")
        if ok:
            self.assertEqual(0, result.returncode, text)
        else:
            self.assertNotEqual(0, result.returncode, "invalid input unexpectedly succeeded")
        if not text.strip() and result.returncode == 0:
            return {}
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            self.fail(f"CLI did not return structured JSON: {text}")

    def store_command(self, command: str, payload: dict, ok: bool = True) -> dict:
        return self.cli(STORE_SCRIPT, command, "--store", self.store, "--input", self.write(payload), ok=ok)

    def brief(self, *, content_id: str = "invented-test-content", judgments: bool = True, synthetic: bool = False) -> dict:
        return {
            "content_id": content_id, "account_id": self.account, "genre": self.genre,
            "synthetic_only": synthetic, "privacy_status": "non_sensitive",
            "source_ref": "isolated-test-fixture:invented-author-declaration",
            "judgments": [{
                "id": "judgment-1", "original_text": self.original, "target": "测试茶杯的颜色",
                "stance": "反对", "intensity": "明确反对", "basis": "仅供软件测试的虚构观察",
                "uncertainty": "没有现实世界事实主张",
            }] if judgments else [],
        }

    def sample(self, text: str, *, confirmed: bool = False, negative: bool = False, synthetic: bool = False) -> dict:
        confirmation = {
            "status": "confirmed" if confirmed else "candidate",
            "actor": ("synthetic_fixture" if synthetic else "author") if confirmed else "assistant",
            "source_ref": "isolated-test-fixture:invented-exact-confirmation",
        }
        if confirmed:
            confirmation.update(scope="exact_fragment", text_sha256=sha_text(text))
        value = {
            "account_id": self.account, "genre": self.genre, "text": text,
            "kind": "negative" if negative else "positive", "source_ref": "isolated-test-fixture:sample",
            "source_kind": "author_revision", "synthetic_only": synthetic,
            "privacy_status": "non_sensitive", "confirmation": confirmation,
        }
        if negative:
            value["feedback_reason"] = "这是虚构测试反馈：不采用说教式结尾。"
        return value

    def recall(self, *, synthetic: bool = False) -> dict:
        args = ["recall", "--store", self.store, "--account-id", self.account, "--genre", self.genre]
        if synthetic:
            args.append("--synthetic-only")
        return self.cli(STORE_SCRIPT, *args)

    def prepare(self, brief: dict | None = None) -> tuple[Path, dict]:
        output = self.path()
        self.cli(BRIDGE_SCRIPT, "prepare", "--store", self.store, "--input", self.write(brief or self.brief()),
                 "--request-id", self.request_id, "--output", output)
        editorial_fixture.preparation(output)
        return output, json.loads(output.read_text(encoding="utf-8"))

    def revision(self, context: Path, draft: Path, before: str = "") -> tuple[Path, dict]:
        output = self.path()
        payload = {"before": before, "reasons": [{"text": "完全虚构的集成测试改稿说明。", "actor": "assistant", "source_ref": "isolated-test:revision"}],
                   "source_ref": "isolated-test:revision", "privacy_status": "non_sensitive"}
        self.cli(BRIDGE_SCRIPT, "revision", "--store", self.store, "--context", context, "--draft", draft,
                 "--input", self.write(payload), "--output", output)
        editorial_fixture.review(output)
        return output, json.loads(output.read_text(encoding="utf-8"))

    def reviewed(self, revision: Path) -> tuple[Path, dict]:
        payload = {"actor": "author", "source_ref": "isolated-test:invented-human-review",
                   "decisions": [{"judgment_id": "judgment-1", "decision": "accepted_change",
                                  "reason": "虚构测试作者显式接受这个版本。", "source_ref": "isolated-test:decision"}]}
        output = self.path()
        self.cli(BRIDGE_SCRIPT, "review", "--store", self.store, "--revision", revision,
                 "--input", self.write(payload), "--output", output)
        return output, json.loads(output.read_text(encoding="utf-8"))

    def test_prepare_cold_start_and_next_process_reads_only_confirmed_fragments(self) -> None:
        first_path, first = self.prepare()
        self.assertEqual([], first["recall"]["samples"])
        self.assertEqual(self.original, first["author_brief"]["judgments"][0]["original_text"])
        self.store_command("sample", self.sample("未确认测试候选不应进入提示。"))
        _, second = self.prepare()
        self.assertEqual([], second["recall"]["samples"])
        positive, negative = "已确认测试表达：杯子留白舒服。", "测试反例：由此可见人生应当升华。"
        self.store_command("sample", self.sample(positive, confirmed=True))
        self.store_command("sample", self.sample(negative, confirmed=True, negative=True))
        final_path, final = self.prepare()
        self.assertEqual({positive, negative}, {sample["payload"]["text"] for sample in final["recall"]["samples"]})
        self.assertEqual({"positive", "negative"}, {sample["payload"]["kind"] for sample in final["recall"]["samples"]})
        self.assertEqual([], json.loads(first_path.read_text(encoding="utf-8"))["recall"]["samples"], "old contexts remain unchanged")
        self.cli(BRIDGE_SCRIPT, "check", "--context", final_path)
        _, empty_judgments = self.prepare(self.brief(content_id="invented-no-judgment", judgments=False))
        self.assertEqual([], empty_judgments["author_brief"]["judgments"], "no author judgment may be fabricated")

    def test_revision_cli_binds_complete_draft_and_requires_exact_review(self) -> None:
        context, _ = self.prepare()
        draft = self.write(self.weakened, ".md")
        envelope, value = self.revision(context, draft, self.original)
        self.assertEqual("author_review_required", self.cli(BRIDGE_SCRIPT, "check", "--revision", envelope, "--require-review", ok=False)["code"])
        reviewed, approved = self.reviewed(envelope)
        self.cli(BRIDGE_SCRIPT, "check", "--revision", reviewed, "--require-review")
        self.assertEqual([], self.recall()["samples"], "author draft review does not approve all prose as a style sample")
        next_draft = self.write(self.weakened + "\n又改了一句虚构测试句。", ".md")
        next_envelope, next_value = self.revision(context, next_draft, self.weakened)
        self.assertEqual("author_revision_stale", self.cli(BRIDGE_SCRIPT, "check", "--revision", reviewed, "--require-review", ok=False)["code"],
                         "an intact old review cannot authorize a superseded version")
        bridge = load_module("author_bridge_acceptance", BRIDGE_SCRIPT)
        next_value["review_ref"] = approved["review_ref"]
        transplanted = self.write(bridge.sign(next_value))
        self.assertEqual("author_review_stale", self.cli(BRIDGE_SCRIPT, "check", "--revision", transplanted, "--require-review", ok=False)["code"])
        draft.write_text("替换后的虚构正文", encoding="utf-8")
        self.assertEqual("author_source_hash_drift", self.cli(BRIDGE_SCRIPT, "check", "--revision", reviewed, "--require-review", ok=False)["code"])

    def test_recomputed_envelope_cannot_swap_body_or_escape_repository(self) -> None:
        context, _ = self.prepare()
        draft = self.write(self.original, ".md")
        _, envelope = self.revision(context, draft)
        bridge = load_module("author_bridge_acceptance", BRIDGE_SCRIPT)
        different = self.write("另一个完全不同的虚构测试稿。", ".md")
        wrong = copy.deepcopy(envelope)
        wrong["draft_ref"] = bridge.ref(different)
        self.assertEqual("author_revision_body_mismatch", self.cli(BRIDGE_SCRIPT, "check", "--revision", self.write(bridge.sign(wrong)), ok=False)["code"])
        wrong = copy.deepcopy(envelope)
        wrong["draft_ref"]["path"] = "../outside-test-draft.md"
        self.assertEqual("author_path_outside_repository", self.cli(BRIDGE_SCRIPT, "check", "--revision", self.write(bridge.sign(wrong)), ok=False)["code"])
        unknown = self.write({"unrecognized_draft_body": self.original})
        payload = {"before": "", "reasons": [{"text": "test", "actor": "assistant", "source_ref": "isolated-test"}], "source_ref": "isolated-test", "privacy_status": "non_sensitive"}
        self.assertEqual("author_draft_shape_unknown", self.cli(BRIDGE_SCRIPT, "revision", "--store", self.store,
            "--context", context, "--draft", unknown, "--input", self.write(payload), "--output", self.path(), ok=False)["code"])

    def test_content_item_records_all_channel_bodies_and_detects_external_body_change(self) -> None:
        self.genre = "graphic_note"
        context, _ = self.prepare()
        body = self.write(self.original, ".md")
        channel_body = self.write("虚构小红书版本，也保留原判断。", ".md")
        content = self.write({"schema_version": "0.2", "composition": {"canonical_body_ref": body.name},
                              "channels": {"xhs": {"title": "虚构标题", "hook": "虚构开头", "body_ref": channel_body.name, "cta": "虚构收尾"}}})
        envelope, _ = self.revision(context, content)
        self.cli(BRIDGE_SCRIPT, "check", "--revision", envelope)
        status = self.cli(STORE_SCRIPT, "status", "--store", self.store, "--content-id", self.brief()["content_id"])
        actual = status["current_revision"]["payload"]["after"]
        for expected in (self.original, "[xhs]", "虚构标题", "虚构开头", "虚构小红书版本，也保留原判断。", "虚构收尾"):
            self.assertIn(expected, actual)
        channel_body.write_text("渠道正文被替换成另一个虚构判断。", encoding="utf-8")
        self.assertEqual("author_revision_body_mismatch", self.cli(BRIDGE_SCRIPT, "check", "--revision", envelope, ok=False)["code"])
        bridge = load_module("author_bridge_acceptance", BRIDGE_SCRIPT)
        empty = self.write({"schema_version": "0.2", "composition": {"summary": "a summary is not the full body"}})
        with self.assertRaises(bridge.AuthorWritingError) as caught:
            bridge.draft_text(empty)
        self.assertEqual("author_full_body_required", caught.exception.code)

    def test_same_text_sidecar_cannot_replace_required_native_primary_draft(self) -> None:
        self.genre = "graphic_note"
        context, _ = self.prepare()
        bridge = load_module("author_bridge_acceptance", BRIDGE_SCRIPT)
        content = self.write({"schema_version": "0.2", "composition": {"canonical_body": self.original}, "channels": {}})
        envelope_path, _ = self.revision(context, content)
        capsule = {"request_id": self.request_id, "provenance": {
            "synthetic_only": False, "author_identity": {"account_id": self.account, "genre": self.genre}}}
        manifest = self.write({"artifacts": [{"source_role": "author-writing-context", "path": context.name}]})
        handoff = {"step": {"step_id": "build-evidence-draft"}, "context": {"manifest": {"path": manifest.name}}}
        handoff_path = self.write(handoff)
        receipt_path = self.path()
        def outputs(paths):
            return {"outputs": [{"path": path.name, "sha256": bridge.file_sha(path)} for path in paths]}
        bridge.validate_output_artifacts(handoff_path, receipt_path, handoff, outputs([content, envelope_path]), capsule)
        sidecar = self.write({"schema_version": "unrelated-schema.v1", "body": self.original})
        sidecar_envelope, _ = self.revision(context, sidecar, self.original)
        for paths in ([sidecar, sidecar_envelope], [content, sidecar, sidecar_envelope]):
            with self.subTest(native_primary_present=content in paths):
                with self.assertRaises(bridge.AuthorWritingError) as caught:
                    bridge.validate_output_artifacts(handoff_path, receipt_path, handoff, outputs(paths), capsule)
                self.assertEqual("author_primary_draft_mismatch", caught.exception.code)

    def test_same_request_cannot_use_another_account_or_genre_author_context(self) -> None:
        context_path, _ = self.prepare()
        bridge = load_module("author_bridge_acceptance", BRIDGE_SCRIPT)
        capsule = {"request_id": self.request_id, "provenance": {
            "synthetic_only": False, "author_identity": {"account_id": self.account, "genre": self.genre}}}
        step = {"step_id": "draft-one-observation", "input_roles": ["author-writing-context", "account_ip"], "context_stage": "draft"}
        account_path = self.write({"account_id": self.account, "note": "invented account profile"})
        manifest = self.manifest(capsule, step, {"author-writing-context": context_path, "account_ip": account_path})
        bridge.validate_context_manifest(manifest, capsule, step)
        for field, other in (("account_id", "another-invented-account"), ("genre", "graphic_note")):
            with self.subTest(mismatch=field):
                mismatched = copy.deepcopy(capsule)
                mismatched["provenance"]["author_identity"][field] = other
                with self.assertRaises(bridge.AuthorWritingError) as caught:
                    bridge.validate_context_manifest(manifest, mismatched, step)
                self.assertEqual("author_identity_mismatch", caught.exception.code)
        missing = copy.deepcopy(capsule)
        del missing["provenance"]["author_identity"]
        with self.assertRaises(bridge.AuthorWritingError) as caught:
            bridge.validate_context_manifest(manifest, missing, step)
        self.assertEqual("author_identity_missing", caught.exception.code)
        wrong_account = self.write({"account_id": "another-invented-account"})
        wrong_profile_manifest = self.manifest(capsule, step, {"author-writing-context": context_path, "account_ip": wrong_account})
        with self.assertRaises(bridge.AuthorWritingError) as caught:
            bridge.validate_context_manifest(wrong_profile_manifest, capsule, step)
        self.assertEqual("author_account_profile_mismatch", caught.exception.code)

    def manifest(self, capsule: dict, step: dict, paths: dict[str, Path], *, omit: str | None = None) -> Path:
        artifacts = []
        for index, role in enumerate(dict.fromkeys([*step["input_roles"], *paths])):
            if role == omit:
                continue
            source = paths[role]
            artifacts.append({"artifact_id": f"input-{index}", "role": "source_manifest", "source_role": role,
                              "path": source.name, "load_mode": "reference",
                              "expected_sha256": hashlib.sha256(source.read_bytes()).hexdigest()})
        creation = load_module("author_creation_route_acceptance", ROOT / "scripts/creation_route.py")
        if step["step_id"] in creation.WRITING_STEPS or capsule.get("creation_phase") == "prerecording":
            context = creation.load(ROOT / "fixtures/creation-route-v1/same-day-activity-highlights.context.json")
            context.update({"task_id": capsule["request_id"], "primary_intent": "explain-or-answer",
                "topic_domain": "explanation", "material_summary": "Invented author-writing test material.",
                "assessment_reason": "Explain the synthetic author position; no causal story is asserted.",
                "source_refs": ["synthetic-author-writing-test"]})
            for role, value in (("creation-route-context", context), ("creation-route-decision", creation.resolve(context))):
                source = self.write(value)
                artifacts.append({"artifact_id": role, "role": "source_manifest", "source_role": role,
                    "path": source.name, "load_mode": "reference", "expected_sha256": hashlib.sha256(source.read_bytes()).hexdigest()})
        manifest = {"schema_version": "self-media-context-input.v1", "task_id": capsule["request_id"],
                    "stage": step["context_stage"], "budget": {"max_inline_bytes": 4096}, "artifacts": artifacts}
        editorial_fixture.bind_stage_purpose(manifest, self.runtime, self.brief()["content_id"],
            "Carry the invented author's meaning through synthetic step " + step["step_id"] + ".",
            paths.get("moments-candidate"))
        return self.write(manifest)

    def test_every_drafting_and_review_entry_rejects_missing_author_inputs(self) -> None:
        bridge = load_module("author_bridge_acceptance", BRIDGE_SCRIPT)
        fixtures = [
            "moments-short-post.request.json", "xhs-evidence-graphic.request.json", "case-video-candidate.request.json",
            "prerecord-spoken.request.json", "prerecord-interview.request.json",
        ]
        visited = set()
        placeholder = self.write({"synthetic_only": True, "note": "isolated transport fixture, not owner execution"})
        for fixture in fixtures:
            request = ROOT / "fixtures" / "agent-entry" / fixture
            capsule = self.cli(AGENT_SCRIPT, "resolve", "--request", request)
            capsule_path = self.write(capsule)
            for step in capsule["step_index"]:
                if step["step_id"] not in bridge.WRITING_STEPS | bridge.REVIEW_STEPS:
                    continue
                visited.add(step["step_id"])
                required = {"author-writing-context"}
                if step["step_id"] in bridge.REVIEW_STEPS:
                    required.add("author-revision-review")
                self.assertTrue(required.issubset(step["input_roles"]), step["step_id"])
                for missing in required:
                    with self.subTest(step=step["step_id"], missing=missing):
                        manifest = self.manifest(capsule, step, {role: placeholder for role in step["input_roles"]}, omit=missing)
                        result = self.cli(AGENT_SCRIPT, "prepare-step", "--capsule", capsule_path, "--step-id", step["step_id"],
                                          "--context-manifest", manifest, "--context-receipt", self.path(), "--output", self.path(), ok=False)
                        self.assertEqual("context_roles_missing", result["error_code"])
                        self.assertIn(missing, result["message"])
        self.assertEqual(bridge.WRITING_STEPS | bridge.REVIEW_STEPS, visited, "every registered author path must be exercised")

    def test_moments_cli_handoffs_consume_author_context_and_bound_revision(self) -> None:
        """Author path is real code; unrelated owners use transport-only fixtures.

        This does not claim editorial owner execution or permission to publish.
        """
        self.store_command("sample", self.sample("虚构已确认表达：茶杯还是留白舒服。", confirmed=True))
        context_path, context = self.prepare()
        draft = self.write(self.weakened, ".md")
        revision_path, _ = self.revision(context_path, draft, self.original)
        reviewed_path, _ = self.reviewed(revision_path)
        request = json.loads((ROOT / "fixtures" / "agent-entry" / "moments-short-post.request.json").read_text(encoding="utf-8"))
        request["request_id"] = self.request_id
        request["synthetic_only"] = False  # The entire fixture is still invented and isolated.
        request["author_identity"] = {"account_id": self.account, "genre": self.genre}
        capsule = self.cli(AGENT_SCRIPT, "resolve", "--request", self.write(request))
        capsule_path = self.write(capsule)
        placeholder = self.write({"note": "invented isolated transport-only fixture; no publication or real owner claims"})
        previous = None
        receipts = []
        agent = load_module("author_acceptance_agent", AGENT_SCRIPT)
        observed_writing = False
        for step in capsule["step_index"]:
            paths = {role: placeholder for role in step["input_roles"]}
            if "topic-angle-decision" in paths:
                framework = load_module("author_framework_acceptance", ROOT / "scripts/topic_angle_decision.py")
                angle = framework.load_json(ROOT / "fixtures/topic-angle-decision-v2/synthetic.input.json")
                angle["human_review"] = {"status": "confirmed", "reviewer": "human",
                    "decision_confirmed": True, "notes": "Invented test review only; no real human approval."}
                paths["topic-angle-decision"] = self.write(framework.create_receipt_from_value(angle))
            paths["author-writing-context"] = context_path
            if "author-revision-review" in paths:
                paths["author-revision-review"] = reviewed_path
            if "moments-candidate" in paths:
                paths["moments-candidate"] = draft
            manifest = self.manifest(capsule, step, paths)
            handoff_path, context_receipt_path = self.path(), self.path()
            args = ["prepare-step", "--capsule", capsule_path, "--step-id", step["step_id"],
                    "--context-manifest", manifest, "--context-receipt", context_receipt_path, "--output", handoff_path]
            if previous is not None:
                args.extend(["--previous-receipt", previous])
            self.cli(AGENT_SCRIPT, *args)
            handoff = json.loads(handoff_path.read_text(encoding="utf-8"))
            outputs = [placeholder]
            if step["step_id"] == "draft-one-observation":
                outputs = [draft, revision_path]
                observed_writing = True
                self.assertIn("author-writing-context", handoff["step"]["input_roles"])
                self.assertEqual(1, context["recall"]["count"])
            elif step["step_id"] == "confirm-author-voice":
                outputs = [draft, reviewed_path]
            stage_review = editorial_fixture.stage_purpose_review(handoff_path, outputs[0])
            if stage_review is not None:
                outputs.append(stage_review)
            receipt = {
                "schema_version": "self-media-step-output-receipt.v1",
                "status": "human_gate_recorded" if step["interface"] == "human_gate" else "candidate_ready",
                "handoff": {"path": handoff_path.name, "sha256": agent.sha256_file(handoff_path)},
                "step_id": step["step_id"], "tool_id": step["tool_id"], "output_contract": step["output_contract"],
                "outputs": [{"path": p.name, "sha256": agent.sha256_file(p)} for p in outputs],
                "boundaries": copy.deepcopy(capsule["boundaries"]),
            }
            if step["step_id"] == "draft-one-observation":
                wrong = copy.deepcopy(receipt)
                wrong["outputs"] = [{"path": placeholder.name, "sha256": agent.sha256_file(placeholder)},
                                    {"path": revision_path.name, "sha256": agent.sha256_file(revision_path)}]
                wrong["payload_sha256"] = agent.sha256_value(wrong)
                rejected = self.cli(AGENT_SCRIPT, "verify-step-output", "--handoff", handoff_path,
                                    "--receipt", self.write(wrong), ok=False)
                self.assertEqual("author_revision_not_delivered", rejected["error_code"])
            receipt["payload_sha256"] = agent.sha256_value(receipt)
            previous = self.write(receipt)
            receipts.append(previous)
            verified = self.cli(AGENT_SCRIPT, "verify-step-output", "--handoff", handoff_path, "--receipt", previous)
            self.assertTrue(verified["ok"])
            self.assertFalse(verified["proves_skill_execution_or_editorial_quality"])
        self.assertTrue(observed_writing)
        self.assertEqual(1, self.recall()["count"], "the approved whole draft must not silently become a style sample")
        # A17: covering all editorial checks cannot promote transport-only owners.
        status = agent.derive_sequence_status(capsule_path, receipts)
        self.assertEqual("sequence_complete_owner_semantics_pending", status["sequence_state"])
        with self.assertRaises(agent.AgentEntryError) as pending:
            agent.require_sequence_complete(capsule_path, receipts)
        self.assertEqual("owner_semantics_pending", pending.exception.code)
        # A11 through the formal sequence entry: unchanged text + new feedback.
        import editorial_integrity
        evidence = editorial_fixture.preparation(context_path)
        editorial_integrity.feedback(context_path, {"feedback_id": "new-counterexample", "check_ids": ["C05"], "issue_ids": [],
                                                     "reason": "Invented new phrasing correction", "source": evidence})
        with self.assertRaises(agent.AgentEntryError) as reopened:
            agent.require_sequence_complete(capsule_path, receipts)
        self.assertEqual("purpose_feedback_pending", reopened.exception.code)

    def test_cross_process_empty_store_candidate_and_exact_sample_confirmation(self) -> None:
        self.assertEqual([], self.recall()["samples"])
        self.assertFalse(self.store.exists(), "read-only empty recall should not create a database")
        self.store_command("sample", self.sample("测试片段一：茶杯还是留白舒服。"))
        self.assertEqual([], self.recall()["samples"], "AI candidate must not enter author recall")
        exact = "测试片段一：茶杯还是留白舒服。"
        self.store_command("sample", self.sample(exact, confirmed=True))
        recalled = self.recall()["samples"]
        self.assertEqual([exact], [item["payload"]["text"] for item in recalled])
        self.assertEqual("exact_fragment", recalled[0]["scope"])
        self.assertEqual([], self.recall(synthetic=True)["samples"])

    def test_ai_self_confirmation_and_wrong_exact_fragment_are_rejected(self) -> None:
        value = self.sample("测试精确片段", confirmed=True)
        value["confirmation"]["actor"] = "assistant"
        self.assertEqual("author_confirmation_required", self.store_command("sample", value, ok=False)["error"])
        value = self.sample("测试精确片段", confirmed=True)
        value["confirmation"]["text_sha256"] = "0" * 64
        self.assertEqual("confirmation_fragment_mismatch", self.store_command("sample", value, ok=False)["error"])

    def test_negative_feedback_is_persistent_and_separate_from_positive_adoption(self) -> None:
        value = self.sample("测试反例：所以我们都应该时刻保持深刻思考。", confirmed=True, negative=True)
        result = self.store_command("sample", value)
        self.assertEqual("negative", result["payload"]["kind"])
        recalled = self.recall()["samples"]
        self.assertEqual(1, len(recalled))
        self.assertEqual(value["feedback_reason"], recalled[0]["payload"]["feedback_reason"])

    def test_cross_process_revision_diff_reason_judgment_review_and_stale_review(self) -> None:
        brief = self.store_command("brief", self.brief())
        revised_brief = self.brief()
        revised_brief["judgments"][0]["original_text"] = self.weakened
        self.assertEqual("brief_immutable", self.store_command("brief", revised_brief, ok=False)["error"])
        value = {
            "content_id": brief["content_id"], "brief_id": brief["record_id"],
            "before": self.original, "after": self.weakened,
            "reasons": [{"text": "测试AI建议弱化语气，未获得作者认可。", "actor": "assistant", "source_ref": "isolated-test:edit"}],
            "source_ref": "isolated-test:revision", "privacy_status": "non_sensitive",
            "risk_notes": [{"judgment_id": "judgment-1", "category": "style", "note": "测试语气意见，不构成立场改变授权。", "source_ref": "isolated-test:risk"}],
        }
        missing_reason = copy.deepcopy(value)
        missing_reason["reasons"] = []
        self.assertEqual("revision_reason_required", self.store_command("revision", missing_reason, ok=False)["error"])
        revision = self.store_command("revision", value)
        self.assertIn("-" + self.original, revision["diff"])
        self.assertIn("+" + self.weakened, revision["diff"])
        self.assertEqual("assistant", revision["payload"]["reasons"][0]["actor"])
        self.assertEqual("needs_author_confirmation", revision["judgment_checks"][0]["status"])
        self.assertFalse(revision["risk_notes_applied_to_text"])
        review = {
            "revision_id": revision["record_id"], "revision_sha256": revision["record_sha256"],
            "actor": "assistant", "source_ref": "isolated-test:review",
            "decisions": [{"judgment_id": "judgment-1", "decision": "accepted_change", "reason": "虚构测试声明明确接受此次弱化。", "source_ref": "isolated-test:exact-author-decision"}],
        }
        self.assertEqual("author_confirmation_required", self.store_command("review", review, ok=False)["error"])
        review["actor"] = "author"
        self.store_command("review", review)
        status = self.cli(STORE_SCRIPT, "status", "--store", self.store, "--content-id", brief["content_id"])
        self.assertEqual("author_confirmed", status["status"])
        value["before"], value["after"] = self.weakened, self.original + "\n这是另一次虚构测试改稿。"
        self.store_command("revision", value)
        status = self.cli(STORE_SCRIPT, "status", "--store", self.store, "--content-id", brief["content_id"])
        self.assertEqual("needs_author_confirmation", status["status"])
        self.assertIsNone(status["current_review"], "an old author review must not authorize the new revision")
        self.assertEqual([], self.recall()["samples"], "reviewing a draft is not sample adoption")


if __name__ == "__main__":
    unittest.main()
