"""End-to-end acceptance tests for plain-language workflows, locked fact cards, and multi-surface gates."""

from __future__ import annotations

import copy
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
TESTS = ROOT / "tests"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))

import article_delivery as article_delivery_mod  # noqa: E402
import author_writing_context as author_mod  # noqa: E402
import content_packaging_review as pkg_mod  # noqa: E402
import editorial_integrity as integrity_mod  # noqa: E402
import entry_selection as entry_mod  # noqa: E402
import plain_language_gate as pl_mod  # noqa: E402
import publication_desk as desk_mod  # noqa: E402
import science_popularization_gate as sci_mod  # noqa: E402
import self_media_agent as agent_mod  # noqa: E402
import serious_content_translation_gate as trans_mod  # noqa: E402
import topic_angle_decision as topic_mod  # noqa: E402
import video_delivery as video_mod  # noqa: E402
import test_editorial_connections as conn_tests  # noqa: E402
import test_editorial_integrity as integrity_tests  # noqa: E402
import test_video_delivery as video_tests  # noqa: E402


PLAIN_FIXTURES = ROOT / "fixtures" / "plain-language-gate-v1"
TRANS_FIXTURE = ROOT / "fixtures" / "serious-content-translation-v1" / "synthetic.input.json"
SCI_FIXTURE = ROOT / "fixtures" / "science-popularization-review-v1" / "synthetic.input.json"
PKG_FIXTURE = ROOT / "fixtures" / "content-packaging-review-v1" / "synthetic.input.json"
CLAUSE_FIXTURE = ROOT.parent / "content-studio-poc" / "fixtures" / "insurance-clause-explanation.renxin-baobei6.json"


CLEAN_DRG_BODY = (
    "# 住院报销先看懂这两件事\n\n"
    "先用一句大白话回答：住院结算时，DRG/DIP主要是医保给医院算账的规则，不是限制你个人只能报一个固定金额。\n\n"
    "很多人看到DRG/DIP会疑惑，它更像医保部门给医院的一份治疗‘套餐价’——注意这个类比只用来理解医保按病组向医院整体结算，"
    "不适用于个人自费兜底判断，而且遇到复杂危重症还有特例单议或除外支付机制。\n\n"
    "同时看报销比例时，政策范围内支付比例只按医保目录和政策范围内医疗费用做分母计算，受起付线、封顶线及目录外自费影响。\n"
)


def _new_video_harness():
    class _VideoHarness(video_tests.VideoDeliveryTests):
        def runTest(self):
            pass

    _VideoHarness.setUpClass()
    return _VideoHarness


class PlainLanguageWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.runtime_parent = ROOT / "tests" / ".runtime" / "plain-language-workflow-20261124"
        if cls.runtime_parent.exists():
            shutil.rmtree(cls.runtime_parent)
        cls.runtime_parent.mkdir(parents=True, exist_ok=True)

    @classmethod
    def tearDownClass(cls) -> None:
        if cls.runtime_parent.exists():
            shutil.rmtree(cls.runtime_parent)

    def setUp(self) -> None:
        self.work = self.runtime_parent / f"{os.getpid()}-{self._testMethodName}"
        if self.work.exists():
            shutil.rmtree(self.work)
        self.work.mkdir(parents=True, exist_ok=True)
        self.conn = conn_tests.ConnectionsTests("runTest")
        self.conn.setUp()
        self.addCleanup(self.conn.doCleanups)

    def tearDown(self) -> None:
        if self.work.exists():
            shutil.rmtree(self.work)

    def _write_json(self, name: str, payload: dict) -> Path:
        path = self.work / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
        return path

    def _ref(self, path: Path) -> dict[str, str]:
        return {"path": str(path.resolve()), "sha256": agent_mod.sha256_file(path)}

    def _rel_ref(self, path: Path) -> str:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()

    def _locked_fact_card(
        self,
        *,
        content_id: str,
        canonical_status: str = "locked_for_draft",
        name: str = "fact-card.json",
    ) -> Path:
        card = json.loads((PLAIN_FIXTURES / "locked-fact-card.json").read_text(encoding="utf-8"))
        card["content_id"] = content_id
        card["canonical_status"] = canonical_status
        return self._write_json(name, card)

    def _create_plan_for(
        self,
        *,
        request_id: str,
        content_id: str,
        fact_card_path: Path,
        quoted_sources: list | None = None,
        intensity: str = "lightweight",
        name: str = "plain-plan.json",
    ) -> Path:
        plan_in = json.loads((PLAIN_FIXTURES / "plan.valid.input.json").read_text(encoding="utf-8"))
        fc = json.loads(fact_card_path.read_text(encoding="utf-8"))
        plan_in["request_id"] = request_id
        plan_in["content_id"] = content_id
        plan_in["intensity"] = intensity
        plan_in["fact_card_ref"] = {
            "path": self._rel_ref(fact_card_path),
            "sha256": agent_mod.sha256_file(fact_card_path),
            "fact_card_id": fc["fact_card_id"],
            "revision_id": fc["revision_id"],
        }
        if quoted_sources is not None:
            plan_in["quoted_sources"] = quoted_sources
        if intensity in {"serious_dual_gate", "science_plus_serious"}:
            raw_t = json.loads(TRANS_FIXTURE.read_text(encoding="utf-8"))
            plan_in["serious_precheck"] = {
                k: raw_t[k] for k in ("risk_class", "sensitivity_profile", "content_nature", "precreative_gate", "translation_plan")
            }
        in_path = self._write_json(f"{name}.input.json", plan_in)
        plan_doc = pl_mod.create_plan(in_path, base_dir=ROOT)
        return self._write_json(name, plan_doc)

    def _create_translation_precheck(self, *, content_id: str, name: str = "trans-precheck.json") -> Path:
        raw = json.loads(TRANS_FIXTURE.read_text(encoding="utf-8"))
        pre_in = {
            "schema_version": "serious-content-translation-precheck-input.v1",
            "generated_at": raw["generated_at"],
            "content_id": content_id,
            "risk_class": raw["risk_class"],
            "sensitivity_profile": raw["sensitivity_profile"],
            "content_nature": raw["content_nature"],
            "precreative_gate": raw["precreative_gate"],
            "translation_plan": raw["translation_plan"],
        }
        in_path = self._write_json(f"{name}.input.json", pre_in)
        receipt = trans_mod.create_precheck_receipt(in_path)
        return self._write_json(name, receipt)

    def _create_translation_review(self, *, content_id: str, body_path: Path, name: str = "trans-review.json") -> Path:
        raw = json.loads(TRANS_FIXTURE.read_text(encoding="utf-8"))
        raw["content_id"] = content_id
        raw["body_binding"]["body_ref"] = self._rel_ref(body_path)
        raw["body_binding"]["body_sha256"] = trans_mod.sha256_text_file(body_path)
        in_path = self._write_json(f"{name}.input.json", raw)
        receipt = trans_mod.create_receipt(in_path)
        return self._write_json(name, receipt)

    def _create_science_review(self, *, content_id: str, body_path: Path, name: str = "sci-review.json") -> Path:
        raw = json.loads(SCI_FIXTURE.read_text(encoding="utf-8"))
        raw["content_id"] = content_id
        raw["body_binding"]["body_ref"] = self._rel_ref(body_path)
        raw["body_binding"]["body_sha256"] = sci_mod.text_sha256(body_path)
        in_path = self._write_json(f"{name}.input.json", raw)
        receipt = sci_mod.create_receipt(in_path)
        return self._write_json(name, receipt)

    def _create_plain_review(
        self,
        *,
        request_id: str,
        content_id: str,
        plan_path: Path,
        fact_card_path: Path,
        body_path: Path,
        clause_path: Path | None = None,
        extra_surfaces: list[dict] | None = None,
        quote_attribution_checks: list[dict] | None = None,
        name: str = "plain-review.json",
    ) -> Path:
        raw = json.loads((PLAIN_FIXTURES / "review.valid.input.json").read_text(encoding="utf-8"))
        fc = json.loads(fact_card_path.read_text(encoding="utf-8"))
        raw["request_id"] = request_id
        raw["content_id"] = content_id
        raw["plan_ref"] = {"path": self._rel_ref(plan_path), "sha256": agent_mod.sha256_file(plan_path)}
        raw["fact_card_ref"] = {
            "path": self._rel_ref(fact_card_path),
            "sha256": agent_mod.sha256_file(fact_card_path),
            "fact_card_id": fc["fact_card_id"],
            "revision_id": fc["revision_id"],
        }
        body_sha = pl_mod.text_sha256(body_path)
        raw["body_binding"] = {"body_ref": self._rel_ref(body_path), "body_sha256": body_sha}
        raw["surface_claim_bindings"] = extra_surfaces or [
            {
                "surface": "body",
                "artifact_ref": self._rel_ref(body_path),
                "artifact_sha256": body_sha,
                "key_claims": [
                    "DRG/DIP主要是医保给医院算账的规则",
                    "政策范围内支付比例只按医保目录和政策范围内医疗费用做分母计算",
                ],
            }
        ]
        if quote_attribution_checks is not None:
            raw["meaning_fidelity_check"]["quote_attribution_checks"] = quote_attribution_checks
        if clause_path is not None:
            raw["clause_explanation_ref"] = {"path": self._rel_ref(clause_path), "sha256": agent_mod.sha256_file(clause_path)}
        in_path = self._write_json(f"{name}.input.json", raw)
        doc = pl_mod.create_review(in_path, base_dir=ROOT)
        return self._write_json(name, doc)

    @staticmethod
    def _review_decisions_for(brief: dict) -> dict:
        return {
            "actor": "synthetic_fixture",
            "source_ref": "test:author-review",
            "decisions": [
                {
                    "judgment_id": j["id"],
                    "decision": "preserved",
                    "reason": "Kept original boundary cleanly",
                    "source_ref": "test:author-review",
                }
                for j in brief.get("judgments") or []
            ],
        }

    def test_case1_unlocked_or_missing_fact_card_blocks_entry_author_and_delivery(self) -> None:
        req = self.conn.req("article", "wechat-article")
        req["risk_flags"] = {"insurance_terms": True, "requires_plain_language": True}
        res_missing = entry_mod.resolve(req, agent_mod)
        self.assertEqual(res_missing["status"], "needs_context")
        self.assertIn("locked_fact_card_for_draft", res_missing["missing_inputs"])
        self.assertEqual(res_missing["fact_confirmation_checklist"]["schema_version"], "fact-and-stance-confirmation-checklist.v1")
        self.assertTrue(res_missing["fact_confirmation_checklist"]["hard_prohibitions"])

        ctx = json.loads(Path(req["current"]["context_manifest"]["path"]).read_text(encoding="utf-8"))
        cid = ctx["editorial_context"]["content_id"]
        draft_fc = self._locked_fact_card(content_id=cid, canonical_status="draft", name="draft-fc.json")
        req["current"]["fact_card"] = self._ref(draft_fc)
        res_draft = entry_mod.resolve(req, agent_mod)
        self.assertEqual(res_draft["status"], "needs_context")
        self.assertEqual(res_draft["fact_card_status"]["status"], "blocked")
        self.assertIn("locked_fact_card_for_draft", res_draft["missing_inputs"])
        self.assertTrue(res_draft["fact_confirmation_checklist"]["facts_requiring_confirmation"])

        store = self.work / "author-store.sqlite3"
        brief = {
            "account_id": "acct-test",
            "genre": "explanation",
            "content_id": cid,
            "synthetic_only": True,
            "privacy_status": "non_sensitive",
            "source_ref": "synthetic:source",
            "judgments": [],
        }
        with self.assertRaises(author_mod.AuthorWritingError) as err:
            author_mod.prepare_context(store, brief, req["request_id"], fact_card_path=draft_fc)
        self.assertEqual(err.exception.code, "fact_card_not_locked_for_draft")

        req_path = self._write_json("req-blocked.json", req)
        with self.assertRaisesRegex(ValueError, "article_gates_blocked"):
            article_delivery_mod.prepare(req_path, self.work / "blocked-item.json")

    def test_case2_full_pass_across_entry_author_integrity_article_packaging_and_desk(self) -> None:
        original = integrity_tests.IntegrityTests.rev
        def with_clean_body(fx, text, before=""):
            return original(fx, CLEAN_DRG_BODY, before)
        with patch.object(integrity_tests.IntegrityTests, "rev", with_clean_body):
            req, fx = self.conn.setup_article()

        ctx_path = Path(req["current"]["context_manifest"]["path"])
        ctx_doc = json.loads(ctx_path.read_text(encoding="utf-8"))
        cid = ctx_doc["editorial_context"]["content_id"]
        fc_path = self._locked_fact_card(content_id=cid)
        plan_path = self._create_plan_for(request_id=req["request_id"], content_id=cid, fact_card_path=fc_path, intensity="science_plus_serious")
        precheck_path = self._create_translation_precheck(content_id=cid)

        topic_in = json.loads((ROOT / "fixtures" / "topic-angle-decision-v2" / "synthetic.input.json").read_text(encoding="utf-8"))
        topic_in["human_review"].update(status="confirmed", reviewer="human", decision_confirmed=True)
        topic_in_path = self._write_json("topic-v2.input.json", topic_in)
        topic_dec_path = self._write_json("topic-v2.json", topic_mod.create_receipt(topic_in_path))

        seed_body = self.work / "seed.md"
        seed_body.write_text(CLEAN_DRG_BODY, encoding="utf-8", newline="\n")
        import creation_route as route_mod
        med_ctx = json.loads(Path(req["current"]["creation_context"]["path"]).read_text(encoding="utf-8"))
        med_ctx["topic_domain"] = "medical"
        med_ctx_path = self._write_json("med-creation-ctx.json", med_ctx)
        med_dec_path = self._write_json("med-creation-dec.json", route_mod.resolve(med_ctx))
        pre_req = copy.deepcopy(req)
        for k in ("author_context", "author_revision"):
            pre_req["current"].pop(k, None)
        pre_req["risk_flags"] = {"medical_claims": True, "serious_professional": True, "requires_plain_language": True}
        pre_req["current"].update(
            creation_context=self._ref(med_ctx_path),
            creation_decision=self._ref(med_dec_path),
            fact_card=self._ref(fc_path),
            plain_language_plan=self._ref(plan_path),
            translation_review=self._ref(precheck_path),
            science_review=self._ref(self._create_science_review(content_id=cid, body_path=seed_body)),
            topic_decision=self._ref(topic_dec_path),
        )
        orig_manifest_path = Path(pre_req["current"]["context_manifest"]["path"])
        manifest_dir = orig_manifest_path.parent
        topic_dec_in_manifest = manifest_dir / "topic-v2-bound.json"
        topic_dec_in_manifest.write_text(topic_dec_path.read_text(encoding="utf-8"), encoding="utf-8", newline="\n")
        topic_dec_ref = self._ref(topic_dec_in_manifest)
        pre_req["current"]["topic_decision"] = topic_dec_ref
        manifest_obj = json.loads(orig_manifest_path.read_text(encoding="utf-8"))
        manifest_obj["artifacts"].append({
            "artifact_id": "topic-dec-v2",
            "role": "decision_sheet",
            "path": "topic-v2-bound.json",
            "expected_sha256": topic_dec_ref["sha256"],
            "load_mode": "reference",
        })
        manifest_obj["editorial_context"]["topic_selection"]["decision_artifact_id"] = "topic-dec-v2"
        new_manifest_path = manifest_dir / "context-manifest-with-topic.json"
        new_manifest_path.write_text(json.dumps(manifest_obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
        pre_req["current"]["context_manifest"] = self._ref(new_manifest_path)
        pre_res = entry_mod.resolve(pre_req, agent_mod)
        self.assertIn("plain_language_guidance", pre_res.get("writing_handoff", {}))
        self.assertIn("topic_facets", pre_res.get("writing_handoff", {}))

        store = self.work / "pass-store.sqlite3"
        orig_ctx = json.loads(Path(req["current"]["author_context"]["path"]).read_text(encoding="utf-8"))
        new_ctx = author_mod.prepare_context(
            store, orig_ctx["author_brief"], req["request_id"],
            fact_card_path=fc_path, plain_language_plan_path=plan_path,
        )
        new_ctx_path = self._write_json("author-ctx-bound.json", new_ctx)
        body_path = Path(author_mod.checked_ref(json.loads(Path(fx.revision).read_text(encoding="utf-8"))["draft_ref"]))
        binding_req = copy.deepcopy(req)
        binding_req["current"] = {
            "creation_context": self._ref(med_ctx_path),
            "creation_decision": self._ref(med_dec_path),
            "context_manifest": copy.deepcopy(req["current"]["context_manifest"]),
        }
        binding = entry_mod.resolve(binding_req, agent_mod)["entry_binding"]
        pre_payload = copy.deepcopy(fx.pre)
        pre_payload["entry_binding"] = binding
        pre_payload["fact_card_ref"] = author_mod.ref(fc_path)
        integrity_mod.record_preflight(new_ctx_path, pre_payload)
        rev_env = author_mod.revision_envelope(
            store, new_ctx_path, body_path,
            {
                "before": "",
                "reasons": [{"actor": "assistant", "text": "Bind plain-language plan", "source_ref": "test:revision"}],
                "source_ref": "test:revision",
                "privacy_status": "non_sensitive",
            },
        )
        rev_path = self._write_json("rev-bound.json", rev_env)
        author_rev = author_mod.attach_review(store, rev_path, self._review_decisions_for(orig_ctx["author_brief"]))
        rev_reviewed_path = self._write_json("rev-reviewed.json", author_rev)

        sci_rev_path = self._create_science_review(content_id=cid, body_path=body_path)
        trans_rev_path = self._create_translation_review(content_id=cid, body_path=body_path)
        pl_rev_path = self._create_plain_review(
            request_id=req["request_id"], content_id=cid, plan_path=plan_path,
            fact_card_path=fc_path, body_path=body_path,
        )
        review_input = fx.data()
        review_input["request_id"] = req["request_id"]
        review_input["draft_ref"] = author_mod.ref(body_path)
        review_input["plain_language_review_ref"] = author_mod.ref(pl_rev_path)
        anchor = "DRG/DIP主要是医保给医院算账的规则"
        for chk in review_input["checks"]:
            chk["quote"] = anchor
            if "text_review" in chk:
                chk["text_review"]["quote"] = anchor
        rec_res = integrity_mod.record_review(rev_reviewed_path, review_input)
        self.assertTrue(rec_res["plain_language_complete"])
        self.assertTrue(rec_res["may_advance"])

        req["risk_flags"] = {"medical_claims": True, "serious_professional": True, "requires_plain_language": True}
        req["current"].update(
            creation_context=self._ref(med_ctx_path),
            creation_decision=self._ref(med_dec_path),
            author_context=self._ref(new_ctx_path),
            author_revision=self._ref(rev_reviewed_path),
            fact_card=self._ref(fc_path),
            plain_language_plan=self._ref(plan_path),
            plain_language_review=self._ref(pl_rev_path),
            science_review=self._ref(sci_rev_path),
            translation_review=self._ref(trans_rev_path),
        )
        final_res = entry_mod.resolve(req, agent_mod)
        self.assertEqual(final_res["status"], "selected")
        self.assertEqual(final_res["missing_inputs"], [])
        self.assertEqual(final_res["risk_review_verification_level"], "formal_schema_verified")
        self.assertNotIn("fact_confirmation_checklist", final_res)

        item_out = self.work / "article-item.json"
        req_file = self._write_json("req-pass.json", req)
        prep_res = article_delivery_mod.prepare(req_file, item_out)
        self.assertEqual(prep_res["status"], "content_item_prepared")

    def test_case3_overclaim_denominator_analogy_and_unverified_quote_blocked(self) -> None:
        cid = "synthetic-drg-plain-case3"
        req_id = "req-case3-01"
        fc_path = self._locked_fact_card(content_id=cid)
        plan_path = self._create_plan_for(
            request_id=req_id,
            content_id=cid,
            fact_card_path=fc_path,
            intensity="lightweight",
            quoted_sources=[{
                "quote": "某地试点单病种人均自付下降15%",
                "source_ref": "2026合成地方案例纪要",
                "evidence_status": "source_quote_unverified_trend",
                "allowed_use_boundary": "仅说明局部合成案例观察，不得当作全国趋势",
            }],
        )

        # (a) Lightweight plan STILL blocks "一定赔"
        bad_md_1 = self.work / "bad1.md"
        bad_md_1.write_text(CLEAN_DRG_BODY + "\n补充一句：买了商业补充医疗险住院就一定赔。\n", encoding="utf-8", newline="\n")
        rev1_path = self._create_plain_review(
            request_id=req_id, content_id=cid, plan_path=plan_path, fact_card_path=fc_path,
            body_path=bad_md_1, quote_attribution_checks=[], name="rev1.json",
        )
        rev1 = json.loads(rev1_path.read_text(encoding="utf-8"))
        self.assertEqual(rev1["decision"], "revision_required")
        self.assertTrue(any(r["code"] == "forbidden_claim_or_overclaim" for r in rev1["blocking_reasons"]))

        # (b) Denominator swap "总账单报销比例"
        bad_md_2 = self.work / "bad2.md"
        bad_md_2.write_text(CLEAN_DRG_BODY + "\n很多人以为这是按总账单报销比例来算的。\n", encoding="utf-8", newline="\n")
        rev2_path = self._create_plain_review(
            request_id=req_id, content_id=cid, plan_path=plan_path, fact_card_path=fc_path,
            body_path=bad_md_2, name="rev2.json",
        )
        rev2 = json.loads(rev2_path.read_text(encoding="utf-8"))
        self.assertEqual(rev2["decision"], "revision_required")
        self.assertTrue(any(r["code"] == "denominator_or_scope_conflation" for r in rev2["blocking_reasons"]))

        # (c) Unverified quote without attribution cue
        bad_md_3 = self.work / "bad3.md"
        bad_md_3.write_text(CLEAN_DRG_BODY + "\n某地试点单病种人均自付下降15%已经说明全面降费。\n", encoding="utf-8", newline="\n")
        rev3_path = self._create_plain_review(
            request_id=req_id, content_id=cid, plan_path=plan_path, fact_card_path=fc_path,
            body_path=bad_md_3, name="rev3.json",
        )
        rev3 = json.loads(rev3_path.read_text(encoding="utf-8"))
        self.assertEqual(rev3["decision"], "revision_required")
        self.assertTrue(any(r["code"] in {"unverified_quote_promoted_to_trend", "quote_attribution_unchecked"} for r in rev3["blocking_reasons"]))

    def test_case4_subtitle_title_cover_and_desk_copy_tamper_fails_closed(self) -> None:
        # (a) ContentPackagingReview: clean body, tainted title
        inp = json.loads(PKG_FIXTURE.read_text(encoding="utf-8"))
        body_path = self.work / "pkg-body.md"
        body_path.write_text(CLEAN_DRG_BODY, encoding="utf-8", newline="\n")
        cid = "synthetic-pkg-surface-01"
        inp["content_id"] = cid
        inp["body_ref"] = self._rel_ref(body_path)
        inp["body_sha256"] = agent_mod.sha256_file(body_path)
        fc_path = self._locked_fact_card(content_id=cid, name="pkg-fc.json")
        plan_path = self._create_plan_for(request_id="req-pkg-01", content_id=cid, fact_card_path=fc_path, name="pkg-plan.json")
        pl_rev_path = self._create_plain_review(
            request_id="req-pkg-01", content_id=cid, plan_path=plan_path,
            fact_card_path=fc_path, body_path=body_path, name="pkg-pl-rev.json",
        )
        inp["plain_language_review"] = {
            "review_ref": self._rel_ref(pl_rev_path),
            "review_sha256": agent_mod.sha256_file(pl_rev_path),
            "review_id": json.loads(pl_rev_path.read_text(encoding="utf-8"))["review_id"],
            "decision": "passed",
        }
        inp["fact_card_ref"] = {
            "path": self._rel_ref(fc_path),
            "sha256": agent_mod.sha256_file(fc_path),
            "fact_card_id": "fact-card-synthetic-drg-01",
            "revision_id": "fact-rev-synthetic-drg-001",
        }
        inp["standalone_review"].update(
            audience_question="住院报销看懂政策范围内支付比例",
            context_excerpt="住院结算时，DRG/DIP主要是医保给医院算账的规则，不是限制你个人只能报一个固定金额。",
            progression_excerpts=[
                "DRG/DIP主要是医保给医院算账的规则",
                "注意这个类比只用来理解医保按病组向医院整体结算，不适用于个人自费兜底判断",
                "政策范围内支付比例只按医保目录和政策范围内医疗费用做分母计算",
            ],
            core_answer_excerpt="DRG/DIP主要是医保给医院算账的规则，不是限制你个人只能报一个固定金额。",
            payoff_excerpt="政策范围内支付比例只按医保目录和政策范围内医疗费用做分母计算，受起付线、封顶线及目录外自费影响。",
        )
        inp["title"] = "DRG改革后住院生病就一定赔"
        inp["cover_brief"]["headline"] = "住院结算怎么算"
        inp["opening_text"] = "DRG/DIP主要是医保给医院算账的规则。"
        bad_in_path = self._write_json("tainted-title.input.json", inp)
        with self.assertRaises(pkg_mod.PackagingReviewError) as pkg_err:
            pkg_mod.create_receipt(bad_in_path)
        self.assertEqual(pkg_err.exception.code, "forbidden_claim_or_overclaim")

        # Clean packaging passes -> tampered desk title blocked by publication_desk
        inp["title"] = "住院报销看懂政策范围内支付比例"
        inp["standalone_review"]["audience_question"] = inp["title"]
        cov = pkg_mod.cover_brief(inp["cover_brief"])
        standalone = pkg_mod.validate_standalone_review(
            inp["standalone_review"], title=inp["title"], opening_text=inp["opening_text"], body_text=CLEAN_DRG_BODY
        )
        scope = pkg_mod.review_scope(
            inp["content_id"], inp["platform"], inp["data_classification"], inp["body_ref"],
            inp["body_sha256"], pkg_mod.sha256_bytes(inp["title"].encode("utf-8")),
            pkg_mod.canonical_sha256(cov), pkg_mod.sha256_bytes(inp["opening_text"].encode("utf-8")),
            pkg_mod.canonical_sha256(standalone),
        )
        cred = {
            "schema_version": "content-packaging-human-review-credential.v1",
            "reviewer": inp["human_review"]["reviewer"],
            "reviewed_at": inp["human_review"]["reviewed_at"],
            "decision": "approved",
            "review_scope_sha256": scope,
            "authority": {"publish_authorized": False, "execution_authorized": False, "external_send_authorized": False},
        }
        cred_path = self._write_json("human-cred.json", cred)
        inp["human_review"]["credential_ref"] = self._rel_ref(cred_path)
        inp["human_review"]["credential_sha256"] = agent_mod.sha256_file(cred_path)
        clean_in_path = self._write_json("clean-pkg.input.json", inp)
        ok_receipt = pkg_mod.create_receipt(clean_in_path)
        receipt_path = self._write_json("clean-pkg-receipt.json", ok_receipt)

        desk_data = desk_mod.new_project("proj-pl-01", "DRG", ["douyin"])
        desk_item = desk_data["items"][0]
        desk_item["item_kind"] = "graphic_note"
        img = self.work / "card.png"
        from PIL import Image
        Image.new("RGB", (1080, 1440), "white").save(img)
        desk_item["images"] = [{"path": str(img), "sha256": agent_mod.sha256_file(img)}]
        desk_item["cover_pk"] = {}
        desk_item["platforms"]["douyin"]["fields"].update(title="所有医院费用全部报销", body="正文合规", tags="#医保 #DRG")
        for chk in desk_item["platforms"]["douyin"]["platform_checks"].values():
            chk.update(status="confirmed", evidence="synthetic", checked_at="2026-11-24")
        with self.assertRaises(pl_mod.PlainLanguageError) as desk_err:
            desk_mod._verify_non_video_package(desk_data, receipt_path)
        self.assertEqual(desk_err.exception.code, "denominator_or_scope_conflation")

        # (b) VideoDelivery: clean body, tainted .srt subtitle fails audit()
        vh_cls = _new_video_harness()
        vh = vh_cls("runTest")
        vh.setUp()
        self.addCleanup(vh.doCleanups)
        self.addCleanup(vh_cls.doClassCleanups)
        v_body = self.work / "video-body.md"
        v_body.write_text(CLEAN_DRG_BODY, encoding="utf-8", newline="\n")
        tainted_srt = self.work / "tainted.srt"
        tainted_srt.write_text("1\n00:00:00,100 --> 00:00:01,500\n买了就一定赔，放心住院。\n", encoding="utf-8", newline="\n")
        v_fc = self._locked_fact_card(content_id="video-pl-01", name="v-fc.json")
        v_plan = self._create_plan_for(request_id="req-v-01", content_id="video-pl-01", fact_card_path=v_fc, name="v-plan.json")
        v_rev = self._create_plain_review(request_id="req-v-01", content_id="video-pl-01", plan_path=v_plan, fact_card_path=v_fc, body_path=v_body, name="v-rev.json")
        v_sci = self._create_science_review(content_id="video-pl-01", body_path=v_body, name="v-sci.json")
        v_trans = self._create_translation_review(content_id="video-pl-01", body_path=v_body, name="v-trans.json")
        vh.m["fact_card_ref"] = {"path": str(v_fc), "sha256": agent_mod.sha256_file(v_fc)}
        vh.m["plain_language_plan_ref"] = {"path": str(v_plan), "sha256": agent_mod.sha256_file(v_plan)}
        vh.m["plain_language_review_ref"] = {"path": str(v_rev), "sha256": agent_mod.sha256_file(v_rev)}
        vh.m["science_review_ref"] = {"path": str(v_sci), "sha256": agent_mod.sha256_file(v_sci)}
        vh.m["translation_review_ref"] = {"path": str(v_trans), "sha256": agent_mod.sha256_file(v_trans)}
        vh.m["subtitles"]["render_file_ref"] = {"path": str(tainted_srt), "sha256": agent_mod.sha256_file(tainted_srt)}
        acc_path = Path(vh.m["acceptance_ref"]["path"])
        acc = json.loads(acc_path.read_text(encoding="utf-8"))
        acc["input_fingerprint"] = video_mod.acceptance_fingerprint(vh.m)
        acc_path.write_text(json.dumps(acc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        vh.m["acceptance_ref"]["sha256"] = agent_mod.sha256_file(acc_path)
        manifest_path = self._write_json("video-manifest.json", vh.m)
        report = video_mod.audit(manifest_path)
        self.assertFalse(report["complete"])
        pl_stage = next(r for r in report["checks"] if r["stage"] == "plain_language_and_science_gates")
        self.assertEqual(pl_stage["status"], "blocked")
        self.assertIn("forbidden_claim_or_overclaim", pl_stage["reason"])

    def test_case5_bare_approved_science_stub_blocked_at_production(self) -> None:
        req, _ = self.conn.setup_article()
        ctx_path = Path(req["current"]["context_manifest"]["path"])
        cid = json.loads(ctx_path.read_text(encoding="utf-8"))["editorial_context"]["content_id"]
        fc_path = self._locked_fact_card(content_id=cid, name="c5-fc.json")
        plan_path = self._create_plan_for(request_id=req["request_id"], content_id=cid, fact_card_path=fc_path, name="c5-plan.json")
        req["risk_flags"] = {"medical_claims": True}
        req["current"].update(
            fact_card=self._ref(fc_path),
            plain_language_plan=self._ref(plan_path),
            science_review=self._ref(self._write_json("stub-sci.json", {"schema": "science-review.v1", "decision": "approved", "request_id": req["request_id"]})),
        )
        res = entry_mod.resolve(req, agent_mod)
        self.assertEqual(res["status"], "needs_context")
        self.assertIn("formal_science_popularization_review", res["missing_inputs"])

    def test_case6_clause_explanation_blocks_missing_not_covered_examples(self) -> None:
        valid_copy = json.loads(CLAUSE_FIXTURE.read_text(encoding="utf-8"))
        valid_path = self._write_json("valid-clause.json", valid_copy)
        self.assertEqual(pl_mod.validate_clause_explanation(valid_path), [])

        bad_copy = copy.deepcopy(valid_copy)
        bad_copy["clause_units"][0]["explanation"]["negative_examples"] = []
        bad_copy["clause_units"][0]["explanation"]["plain_language"] += " 发生风险就一定赔。"
        bad_path = self._write_json("bad-clause.json", bad_copy)
        errs = pl_mod.validate_clause_explanation(bad_path)
        self.assertTrue(any("negative_examples" in e for e in errs))
        self.assertTrue(any("一定赔" in e for e in errs))

    def test_case7_carry_over_invalidates_plain_language_review_and_mode_b_runtime(self) -> None:
        original = integrity_tests.IntegrityTests.rev
        def with_clean_body(fx, text, before=""):
            return original(fx, CLEAN_DRG_BODY, before)
        with patch.object(integrity_tests.IntegrityTests, "rev", with_clean_body):
            req, fx = self.conn.setup_article()

        ctx = json.loads(Path(req["current"]["context_manifest"]["path"]).read_text(encoding="utf-8"))
        cid = ctx["editorial_context"]["content_id"]
        fc_path = self._locked_fact_card(content_id=cid, name="c7-fc.json")
        plan_path = self._create_plan_for(request_id=req["request_id"], content_id=cid, fact_card_path=fc_path, name="c7-plan.json")
        store = self.work / "c7-store.sqlite3"
        orig_ctx = json.loads(Path(req["current"]["author_context"]["path"]).read_text(encoding="utf-8"))
        new_ctx_path = self._write_json(
            "c7-ctx.json",
            author_mod.prepare_context(store, orig_ctx["author_brief"], req["request_id"], fact_card_path=fc_path, plain_language_plan_path=plan_path),
        )
        body_v1 = self.work / "c7-v1.md"
        body_v1.write_text(CLEAN_DRG_BODY, encoding="utf-8", newline="\n")
        rev_payload_base = {
            "before": "",
            "reasons": [{"actor": "assistant", "text": "v1", "source_ref": "test:revision"}],
            "source_ref": "test:revision",
            "privacy_status": "non_sensitive",
        }
        binding = entry_mod.resolve({**req, "current": {k: req["current"][k] for k in ("creation_context", "creation_decision", "context_manifest")}}, agent_mod)["entry_binding"]
        pre = copy.deepcopy(fx.pre)
        pre["entry_binding"] = binding
        pre["fact_card_ref"] = author_mod.ref(fc_path)
        integrity_mod.record_preflight(new_ctx_path, pre)
        rev1 = self._write_json("c7-rev1.json", author_mod.revision_envelope(store, new_ctx_path, body_v1, rev_payload_base))
        rev1_reviewed = self._write_json("c7-rev1-ok.json", author_mod.attach_review(store, rev1, self._review_decisions_for(orig_ctx["author_brief"])))
        pl_rev1 = self._create_plain_review(request_id=req["request_id"], content_id=cid, plan_path=plan_path, fact_card_path=fc_path, body_path=body_v1, name="c7-plrev1.json")
        d = fx.data()
        d["request_id"] = req["request_id"]
        d["draft_ref"] = author_mod.ref(body_v1)
        d["plain_language_review_ref"] = author_mod.ref(pl_rev1)
        for chk in d["checks"]:
            chk["quote"] = "DRG/DIP主要是医保给医院算账的规则"
            if "text_review" in chk:
                chk["text_review"]["quote"] = "DRG/DIP主要是医保给医院算账的规则"
        integrity_mod.record_review(rev1_reviewed, d)

        body_v2 = self.work / "c7-v2.md"
        body_v2.write_text(CLEAN_DRG_BODY + "\n新增一行通俗解释。\n", encoding="utf-8", newline="\n")
        rev2_payload = {
            "before": CLEAN_DRG_BODY,
            "reasons": [{"actor": "assistant", "text": "v2", "source_ref": "test:revision"}],
            "source_ref": "test:revision",
            "privacy_status": "non_sensitive",
        }
        rev2 = self._write_json("c7-rev2.json", author_mod.revision_envelope(store, new_ctx_path, body_v2, rev2_payload))
        carry = integrity_mod.carry_over(rev2, ["wording"], self.work / "carry.json")
        self.assertTrue(carry["plain_language_review_invalidated"])
        self.assertIsNone(carry["template"]["plain_language_review_ref"])

        c01_orig = next(c for c in d["checks"] if c["id"] == "C01")
        c01_purpose = copy.deepcopy(c01_orig["purpose_alignment"])
        c01_evidence = copy.deepcopy(c01_orig["evidence"])
        for chk in carry["template"]["checks"]:
            if chk["state"] == "unchecked":
                chk["state"] = "retained"
                chk["quote"] = "新增一行通俗解释"
                chk["reason"] = "人工核对了新增句子"
                ev = {**author_mod.ref(body_v2), "quote": "新增一行通俗解释"}
                chk["evidence"] = (c01_evidence + [ev]) if chk["id"] == "C01" else [ev]
                if chk["id"] == "C01":
                    chk["purpose_alignment"] = copy.deepcopy(c01_purpose)
                if "text_review" in chk:
                    chk["text_review"] = {"quote": "新增一行通俗解释", "reason": "文本清晰", "evidence": [ev]}
        eval_res, _, _, _ = integrity_mod.evaluate(rev2, carry["template"])
        self.assertFalse(eval_res["plain_language_complete"])
        self.assertFalse(eval_res["may_advance"])

        with tempfile.TemporaryDirectory() as rt_home:
            with patch.dict(os.environ, {"SELF_MEDIA_RUNTIME_HOME": rt_home}):
                out_file = Path(rt_home) / "plain-plan-rt.json"
                pl_mod.write_receipt(out_file, json.loads(plan_path.read_text(encoding="utf-8")))
                self.assertTrue(out_file.is_file())
                resolved = pl_mod.resolve_artifact_path(".runtime/plain-plan-rt.json")
                self.assertEqual(resolved, out_file.resolve())

    def test_case8_surface_body_mismatch_and_duplicate_surface_bindings(self) -> None:
        cid = "synthetic-drg-plain-case8"
        req_id = "req-case8-01"
        fc_path = self._locked_fact_card(content_id=cid, name="c8-fc.json")
        plan_path = self._create_plan_for(request_id=req_id, content_id=cid, fact_card_path=fc_path, name="c8-plan.json")
        fc = json.loads(fc_path.read_text(encoding="utf-8"))

        body_clean = self.work / "c8-clean.md"
        body_clean.write_text(CLEAN_DRG_BODY, encoding="utf-8", newline="\n")
        body_bad = self.work / "c8-bad.md"
        body_bad.write_text(CLEAN_DRG_BODY + "\n补充一句：买了就一定赔，按总账单报销比例算。\n", encoding="utf-8", newline="\n")

        sub_bad = self.work / "c8-sub-bad.srt"
        sub_bad.write_text(
            "1\n00:00:00,000 --> 00:00:02,000\nDRG/DIP主要是医保给医院算账的规则\n\n"
            "2\n00:00:02,100 --> 00:00:04,000\n住院就一定赔，放心买。\n",
            encoding="utf-8",
            newline="\n",
        )
        sub_clean = self.work / "c8-sub-clean.srt"
        sub_clean.write_text(
            "1\n00:00:00,000 --> 00:00:02,000\nDRG/DIP主要是医保给医院算账的规则\n",
            encoding="utf-8",
            newline="\n",
        )

        raw = json.loads((PLAIN_FIXTURES / "review.valid.input.json").read_text(encoding="utf-8"))
        raw["request_id"] = req_id
        raw["content_id"] = cid
        raw["plan_ref"] = {"path": self._rel_ref(plan_path), "sha256": agent_mod.sha256_file(plan_path)}
        raw["fact_card_ref"] = {
            "path": self._rel_ref(fc_path),
            "sha256": agent_mod.sha256_file(fc_path),
            "fact_card_id": fc["fact_card_id"],
            "revision_id": fc["revision_id"],
        }

        mismatch = copy.deepcopy(raw)
        mismatch["body_binding"] = {"body_ref": self._rel_ref(body_bad), "body_sha256": pl_mod.text_sha256(body_bad)}
        mismatch["surface_claim_bindings"] = [
            {
                "surface": "body",
                "artifact_ref": self._rel_ref(body_clean),
                "artifact_sha256": pl_mod.text_sha256(body_clean),
                "key_claims": ["DRG/DIP主要是医保给医院算账的规则"],
            }
        ]
        mismatch_in = self._write_json("c8-mismatch.input.json", mismatch)
        with self.assertRaises(pl_mod.PlainLanguageError) as err:
            pl_mod.create_review(mismatch_in, base_dir=ROOT)
        self.assertEqual(err.exception.code, "surface_body_binding_mismatch")

        dup_sub = copy.deepcopy(raw)
        dup_sub["body_binding"] = {"body_ref": self._rel_ref(body_clean), "body_sha256": pl_mod.text_sha256(body_clean)}
        dup_sub["surface_claim_bindings"] = [
            {
                "surface": "subtitle",
                "artifact_ref": self._rel_ref(sub_bad),
                "artifact_sha256": pl_mod.text_sha256(sub_bad),
                "key_claims": ["DRG/DIP主要是医保给医院算账的规则"],
            },
            {
                "surface": "subtitle",
                "artifact_ref": self._rel_ref(sub_clean),
                "artifact_sha256": pl_mod.text_sha256(sub_clean),
                "key_claims": ["DRG/DIP主要是医保给医院算账的规则"],
            },
        ]
        dup_sub_in = self._write_json("c8-dup-sub.input.json", dup_sub)
        dup_res = pl_mod.create_review(dup_sub_in, base_dir=ROOT)
        self.assertEqual(dup_res["decision"], "revision_required")
        self.assertTrue(any(r["code"] == "forbidden_claim_or_overclaim" for r in dup_res["blocking_reasons"]))


if __name__ == "__main__":
    unittest.main()
