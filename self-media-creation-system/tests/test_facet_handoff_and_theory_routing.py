"""Regression tests for confirmed topic_facets handoff, C04 realization, and on-demand theory routing."""
from __future__ import annotations

import copy
import json
import os
import shutil
import sys
import unittest
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
TESTS = ROOT / "tests"
for entry in (SCRIPTS, TESTS):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

import author_writing_context as author  # noqa: E402
import creation_route  # noqa: E402
import editorial_fixture  # noqa: E402
import editorial_integrity as gate  # noqa: E402
import entry_selection  # noqa: E402
import self_media_agent as agent  # noqa: E402
import topic_angle_decision as fad  # noqa: E402


DRAFT_TEXT = "\n".join([
    "# Synthetic Family Policy Checklist",
    "I want to build a model.",
    "It is a plan, not an existing product.",
    "First inventory what policies the family already holds before comparing any new coverage.",
    "The family realized nobody could list all existing policies together.",
    "Judgment: compare nothing until the existing list is complete.",
])


class FacetHandoffAndTheoryRoutingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.test_root = Path(os.environ.get("TEST_TMP_ROOT", ROOT / ".test-runtime")).resolve()
        self.root = self.test_root / f"facet-handoff-{uuid.uuid4().hex}"
        self.root.mkdir(parents=True, exist_ok=True)
        self.serial = 0
        self.db = self.root / "isolated-author.sqlite3"
        self.default_store = ROOT / ".runtime" / "author-expression" / "store.sqlite3"
        self.default_before = self.default_store.stat().st_mtime_ns if self.default_store.exists() else None

    def tearDown(self) -> None:
        self.assertEqual(
            self.default_before,
            self.default_store.stat().st_mtime_ns if self.default_store.exists() else None,
            "tests must never modify the default author expression store",
        )
        assert self.root.resolve().is_relative_to(self.test_root)
        shutil.rmtree(self.root, ignore_errors=True)

    def write(self, data: dict | list | str, suffix: str = ".json") -> Path:
        self.serial += 1
        path = self.root / f"artifact-{self.serial}{suffix}"
        payload = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False, indent=2) + "\n"
        path.write_text(payload, encoding="utf-8")
        return path

    def ref(self, data: dict | list | str, suffix: str = ".json") -> dict[str, str]:
        path = self.write(data, suffix=suffix)
        return {"path": str(path), "sha256": agent.sha256_file(path)}

    def confirmed_decision_input(self, *, with_theory: bool = False, verify_theory: bool = True) -> dict:
        raw = fad.load_json(ROOT / "fixtures/topic-angle-decision-v2/synthetic.input.json")
        raw["human_review"] = {
            "status": "confirmed",
            "reviewer": "human",
            "decision_confirmed": True,
            "notes": "Synthetic human confirmation for unit tests only.",
        }
        if with_theory:
            element = raw["framework_decision"]["facet_elements"][1]
            element["kind"] = "theory"
            element["theory_boundary"] = "Synthetic explanatory framing of one household inventory case, not a universal law."
            if verify_theory:
                ev = dict(
                    raw["evidence_registry"][0],
                    evidence_id="evidence-synthetic-theory",
                    source_kind="synthetic-fixture",
                    status="verified_source",
                    fact_support_eligible=True,
                    synthetic_only=True,
                )
                raw["evidence_registry"].append(ev)
                element["evidence_refs"] = ["evidence-synthetic-theory"]
            else:
                element["evidence_refs"] = ["evidence-topic-observation"]
        return raw

    def make_decision_ref(self, *, confirmed: bool = True, outcome: str = "continue", with_theory: bool = False) -> tuple[Path, dict[str, str]]:
        raw = self.confirmed_decision_input(with_theory=with_theory, verify_theory=True)
        if not confirmed:
            raw["human_review"] = {
                "status": "pending",
                "reviewer": "not-yet",
                "decision_confirmed": False,
                "notes": "Pending decision for negative test.",
            }
        if outcome == "reframe":
            raw["framework_decision"]["outcome"] = "reframe"
            raw["framework_decision"]["rewrite_scope"] = "partial"
            raw["framework_decision"]["planned_changes"] = ["revise-body"]
            raw["selected_angle_id"] = None
            for cand in raw["angle_candidates"]:
                cand.update(selection_status="not-selected", selection_reason=None, rejection_reason="Reframe needed.")
        receipt = fad.create_receipt_from_value(raw)
        path = self.write(receipt)
        return path, {"path": str(path), "sha256": agent.sha256_file(path)}

    def setup_editorial_piece(
        self,
        *,
        kind: str = "article",
        platform: str = "wechat-article",
        content_format: str | None = None,
        request_id: str = "synthetic-facet-req-01",
        with_topic_decision: bool = True,
        bind_author_topic_decision: bool = True,
        with_theory: bool = False,
        draft_text: str = DRAFT_TEXT,
    ) -> dict:
        source_path = self.write(
            "Synthetic purpose: help families inventory existing policies. Audience: families with multiple policies. Evidence: a plan, not an existing product.",
            ".md",
        )
        source_sha = agent.sha256_file(source_path)

        draft_path = self.write(draft_text, ".md")
        draft_sha = agent.sha256_file(draft_path)

        creative_ctx = json.loads(
            (ROOT / "fixtures/creation-route-v1/same-day-activity-highlights.context.json").read_text(encoding="utf-8")
        )
        creative_ctx.update(
            task_id=request_id,
            topic_domain="explanation",
            primary_intent="explain-or-answer",
            requested_vlog_style="auto",
            requested_route="auto",
        )
        creative_decision_ref = self.ref(creation_route.resolve(creative_ctx))
        creative_ctx_ref = self.ref(creative_ctx)

        decision_path = None
        decision_ref = None
        if with_topic_decision:
            decision_path, decision_ref = self.make_decision_ref(with_theory=with_theory)

        artifacts = [
            {
                "artifact_id": "purpose-source",
                "role": "source_manifest",
                "path": source_path.name,
                "expected_sha256": source_sha,
                "load_mode": "reference",
            },
            {
                "artifact_id": "current-draft",
                "role": "source_manifest",
                "path": draft_path.name,
                "expected_sha256": draft_sha,
                "load_mode": "reference",
            },
        ]
        topic_selection = {
            "topic": "先盘点家庭现有保单，再决定是否加保",
            "origin": "tool_trial",
            "adoption": "selected",
            "adoption_basis": "Bounded synthetic test adoption with confirmed framework facets.",
            "origin_source": {"artifact_id": "purpose-source", "quote": "help families inventory existing policies"},
            "adoption_source": {"artifact_id": "purpose-source", "quote": "help families inventory existing policies"},
        }
        if decision_ref is not None:
            artifacts.append({
                "artifact_id": "framework-current",
                "role": "source_manifest",
                "path": Path(decision_ref["path"]).name,
                "expected_sha256": decision_ref["sha256"],
                "load_mode": "reference",
            })
            topic_selection["decision_artifact_id"] = "framework-current"

        manifest_data = {
            "schema_version": "self-media-context-input.v1",
            "task_id": request_id,
            "stage": "draft",
            "budget": {"max_inline_bytes": 4096},
            "artifacts": artifacts,
            "editorial_context": {
                "version": 1,
                "content_id": f"synthetic-{request_id}",
                "topic_selection": topic_selection,
                "purpose": {"artifact_id": "purpose-source", "quote": "help families inventory existing policies"},
                "audience": {"artifact_id": "purpose-source", "quote": "families with multiple policies"},
                "stage_duty": "Inventory existing household policies before any new comparison.",
                "current_body_artifact_id": "current-draft",
                "feedback": [],
                "feedback_note": "No feedback in this isolated synthetic test.",
            },
        }
        manifest_ref = self.ref(manifest_data)

        current = {
            "creation_context": creative_ctx_ref,
            "creation_decision": creative_decision_ref,
            "context_manifest": manifest_ref,
        }
        if decision_ref is not None:
            current["topic_decision"] = decision_ref

        req = {
            "schema_version": "self-media-work-request.v1",
            "request_id": request_id,
            "requested_output": kind,
            "platform": platform,
            "selection_basis": "Synthetic regression for topic_facets handoff and C04 verification.",
            "current": current,
        }
        if content_format is not None:
            req["content_format"] = content_format

        author_ctx_data = author.prepare_context(
            self.db,
            {
                "content_id": f"synthetic-{request_id}",
                "account_id": "synthetic-facet-author",
                "genre": "article" if kind == "article" else "spoken_script",
                "synthetic_only": True,
                "privacy_status": "non_sensitive",
                "source_ref": "synthetic:facet-handoff-source",
                "judgments": [],
            },
            request_id,
            topic_decision_path=decision_path if (with_topic_decision and bind_author_topic_decision) else None,
        )
        author_ctx_path = self.write(author_ctx_data)

        source_ev = {**author.ref(source_path), "quote": "a plan, not an existing product"}
        purpose_ev = {**author.ref(source_path), "quote": "help families inventory existing policies"}
        fact_card_path = self.write({
            "schema": "content-fact-card.v0",
            "content_id": f"synthetic-{request_id}",
            "canonical_status": "locked_for_draft",
            "human_confirmation": {"quote": "Synthetic facet handoff fact confirmation"},
        })
        pre_data = {
            "route": "expository",
            "actor": "synthetic_fixture",
            "source": source_ev,
            "fact_card_ref": author.ref(fact_card_path),
            "items": [
                {
                    "id": item_id,
                    "state": "ready",
                    "reason": f"Synthetic preflight ready for {item_id}",
                    "evidence": [purpose_ev if item_id == "goal_audience" else source_ev],
                }
                for item_id in sorted(gate.PRE)
            ],
        }
        gate.record_preflight(author_ctx_path, pre_data)
        revision_data = author.revision_envelope(
            self.db,
            author_ctx_path,
            draft_path,
            {
                "before": "",
                "reasons": [{"actor": "assistant", "text": "Synthetic initial draft", "source_ref": "test:revision"}],
                "source_ref": "test:revision",
                "privacy_status": "non_sensitive",
            },
        )
        revision_path = self.write(revision_data)

        return {
            "req": req,
            "source_path": source_path,
            "source_ev": source_ev,
            "purpose_ev": purpose_ev,
            "draft_path": draft_path,
            "decision_path": decision_path,
            "decision_ref": decision_ref,
            "author_ctx_path": author_ctx_path,
            "pre_data": pre_data,
            "revision_path": revision_path,
        }

    def build_review_payload(self, state: dict, *, omit_facet_realization: bool = False) -> dict:
        env = author.load(state["revision_path"])
        ctx = author.load(state["author_ctx_path"])
        records = gate.history(ctx)
        previous = gate.latest(records, "editorial_review")
        checks = []
        for cid in sorted(gate.CHECKS):
            row = {
                "id": cid,
                "state": "retained",
                "scope": "script-text",
                "quote": "It is a plan, not an existing product.",
                "reason": f"Draft retains verified framing boundary for {cid}",
                "evidence": [state["purpose_ev"] if cid == "C01" else state["source_ev"]],
                "issue_ids": [],
                "reuse_from": None,
            }
            if cid == "C01":
                row["purpose_alignment"] = {
                    "stage_duty": "Help families inventory existing policies first.",
                    "contribution": "Anchors the opening before any product comparison.",
                    "misunderstanding_risk": "Readers might otherwise jump straight to comparing plans.",
                    "tradeoff": "Delay product commentary to establish the prerequisite inventory step.",
                }
            if cid == "C04" and not omit_facet_realization:
                row["facet_realization"] = {
                    "angle_id": "angle-first-inventory",
                    "dominant_action": "judgment",
                    "main_element": {
                        "element_id": "element-inventory-first",
                        "quote": "First inventory what policies the family already holds",
                        "assessment": "Opening directive centers the piece on policy inventory before purchase.",
                    },
                    "supporting_elements": [
                        {
                            "element_id": "element-family-observation",
                            "relation": "illustrates",
                            "status": "realized",
                            "quote": "nobody could list all existing policies together",
                            "assessment": "Household observation directly illustrates why inventory comes first.",
                        }
                    ],
                    "dominant_action_check": {
                        "quote": "compare nothing until the existing list is complete",
                        "assessment": "Expresses the actionable judgment criterion unambiguously.",
                    },
                }
            checks.append(row)
        return {
            "request_id": state["req"]["request_id"],
            "draft_ref": env["draft_ref"],
            "phase": "draft",
            "route": "expository",
            "previous_review_id": previous["record_id"] if previous else None,
            "feedback_ids": [r["record_id"] for r in records if r["record_type"] == "editorial_feedback"],
            "changes": [],
            "actor": "synthetic_fixture",
            "source": state["source_ev"],
            "issues": [],
            "observations": {"readthrough": None, "final_media": None},
            "checks": checks,
        }

    def test_article_topic_facets_handoff_and_c04_validation(self) -> None:
        # 1. Missing author_context emits writing_handoff + --topic-decision in prepare argv
        state = self.setup_editorial_piece(kind="article", platform="wechat-article")
        res0 = agent.resolve_request(state["req"])
        self.assertEqual(res0["status"], "needs_context")
        self.assertIn("writing_handoff", res0)
        self.assertEqual(res0["writing_handoff"]["topic_facets"]["main_element"]["element_id"], "element-inventory-first")
        self.assertIn("--topic-decision", res0["next_action"]["argv"])
        self.assertIn(str(state["decision_path"]), res0["next_action"]["argv"])

        # 2. author_context prepared without --topic-decision returns author_context_with_topic_facets
        unbound_state = self.setup_editorial_piece(
            kind="article", platform="wechat-article", bind_author_topic_decision=False
        )
        req_unbound = copy.deepcopy(unbound_state["req"])
        req_unbound["current"]["author_context"] = {
            "path": str(unbound_state["author_ctx_path"]),
            "sha256": agent.sha256_file(unbound_state["author_ctx_path"]),
        }
        res_unbound = agent.resolve_request(req_unbound)
        self.assertEqual(res_unbound["status"], "needs_context")
        self.assertIn("author_context_with_topic_facets", res_unbound["missing_inputs"])
        self.assertIn("--topic-decision", res_unbound["next_action"]["argv"])

        # 3. author_context bound to a DIFFERENT topic_decision fails closed with editorial_topic_facets_mismatch
        other_decision_path, _ = self.make_decision_ref(with_theory=True)
        wrong_ctx_path = self.write(
            author.prepare_context(
                self.db,
                {
                    "content_id": f"synthetic-{state['req']['request_id']}",
                    "account_id": "synthetic-facet-author",
                    "genre": "article",
                    "synthetic_only": True,
                    "privacy_status": "non_sensitive",
                    "source_ref": "synthetic:facet-handoff-source",
                    "judgments": [],
                },
                state["req"]["request_id"],
                topic_decision_path=other_decision_path,
            )
        )
        req_mismatch = copy.deepcopy(state["req"])
        req_mismatch["current"]["author_context"] = {
            "path": str(wrong_ctx_path),
            "sha256": agent.sha256_file(wrong_ctx_path),
        }
        with self.assertRaises(agent.AgentEntryError) as mismatch_err:
            agent.resolve_request(req_mismatch)
        self.assertEqual(mismatch_err.exception.code, "editorial_topic_facets_mismatch")

        # 4. Author context guards against pending/corrupt/tampered decisions and facet drift
        pending_path, _ = self.make_decision_ref(confirmed=False)
        with self.assertRaises(author.AuthorWritingError) as err:
            author.prepare_context(
                self.db,
                {
                    "content_id": f"synthetic-{state['req']['request_id']}",
                    "account_id": "synthetic-facet-author",
                    "genre": "article",
                    "synthetic_only": True,
                    "privacy_status": "non_sensitive",
                    "source_ref": "synthetic:facet-handoff-source",
                    "judgments": [],
                },
                "synthetic-pending-req",
                topic_decision_path=pending_path,
            )
        self.assertEqual(err.exception.code, "author_topic_decision_not_ready")

        bad_json_path = self.write("{not valid json", ".json")
        with self.assertRaises(author.AuthorWritingError) as err:
            author.prepare_context(
                self.db,
                {
                    "content_id": f"synthetic-{state['req']['request_id']}",
                    "account_id": "synthetic-facet-author",
                    "genre": "article",
                    "synthetic_only": True,
                    "privacy_status": "non_sensitive",
                    "source_ref": "synthetic:facet-handoff-source",
                    "judgments": [],
                },
                "synthetic-bad-req",
                topic_decision_path=bad_json_path,
            )
        self.assertEqual(err.exception.code, "author_topic_decision_invalid")

        signed_ctx = author.load(state["author_ctx_path"])
        tampered_facets_ctx = copy.deepcopy(signed_ctx)
        tampered_facets_ctx["topic_facets"]["dominant_action"] = "concept"
        tampered_facets_path = self.write(author.sign(tampered_facets_ctx))
        with self.assertRaises(author.AuthorWritingError) as err:
            author.validate_context(tampered_facets_path)
        self.assertEqual(err.exception.code, "author_topic_facets_drift")

        unbound_signed = copy.deepcopy(signed_ctx)
        unbound_signed.pop("topic_decision_ref")
        unbound_signed_path = self.write(author.sign(unbound_signed))
        with self.assertRaises(author.AuthorWritingError) as err:
            author.validate_context(unbound_signed_path)
        self.assertEqual(err.exception.code, "author_topic_facets_unbound")

        # Tampering file bytes of referenced decision triggers author_source_hash_drift
        temp_dec_path, _ = self.make_decision_ref()
        temp_ctx_path = self.write(
            author.prepare_context(
                self.db,
                {
                    "content_id": f"synthetic-{state['req']['request_id']}",
                    "account_id": "synthetic-facet-author",
                    "genre": "article",
                    "synthetic_only": True,
                    "privacy_status": "non_sensitive",
                    "source_ref": "synthetic:facet-handoff-source",
                    "judgments": [],
                },
                "synthetic-tamper-req",
                topic_decision_path=temp_dec_path,
            )
        )
        temp_dec_path.write_text(temp_dec_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        with self.assertRaises(author.AuthorWritingError) as err:
            author.validate_context(temp_ctx_path)
        self.assertEqual(err.exception.code, "author_source_hash_drift")

        # 5. Bind valid preflight + entry_binding & author_revision, then test all C04 facet_realization gates
        req_with_ctx = copy.deepcopy(state["req"])
        req_with_ctx["current"]["author_context"] = {
            "path": str(state["author_ctx_path"]),
            "sha256": agent.sha256_file(state["author_ctx_path"]),
        }
        binding = agent.resolve_request(req_with_ctx)["entry_binding"]
        pre = copy.deepcopy(state["pre_data"])
        pre["entry_binding"] = binding
        gate.record_preflight(state["author_ctx_path"], pre)

        # Negative C04 cases
        missing_fr = self.build_review_payload(state, omit_facet_realization=True)
        with self.assertRaises(author.AuthorWritingError) as err:
            gate.record_review(state["revision_path"], missing_fr)
        self.assertEqual(err.exception.code, "editorial_facet_review_missing")

        wrong_scope = self.build_review_payload(state)
        c04 = next(c for c in wrong_scope["checks"] if c["id"] == "C04")
        c01 = next(c for c in wrong_scope["checks"] if c["id"] == "C01")
        c01["facet_realization"] = copy.deepcopy(c04["facet_realization"])
        with self.assertRaises(author.AuthorWritingError) as err:
            gate.record_review(state["revision_path"], wrong_scope)
        self.assertEqual(err.exception.code, "editorial_facet_review_scope")

        negative_mutations = [
            ("editorial_facet_anchor_missing", lambda fr: fr["main_element"].update(quote="not in draft at all")),
            ("editorial_facet_supporting_coverage", lambda fr: fr["supporting_elements"].clear()),
            ("editorial_facet_supporting_relation_drift", lambda fr: fr["supporting_elements"][0].update(relation="context")),
            ("editorial_facet_angle_drift", lambda fr: fr.update(angle_id="angle-other")),
            ("editorial_facet_action_drift", lambda fr: fr.update(dominant_action="concept")),
            ("editorial_facet_reason_missing", lambda fr: fr["dominant_action_check"].update(assessment="passed")),
            ("editorial_facet_anchor_missing", lambda fr: fr["dominant_action_check"].update(quote="missing action quote")),
        ]
        for expected_code, mutate in negative_mutations:
            with self.subTest(expected_code=expected_code):
                payload = self.build_review_payload(state)
                c04_row = next(c for c in payload["checks"] if c["id"] == "C04")
                mutate(c04_row["facet_realization"])
                with self.assertRaises(author.AuthorWritingError) as err:
                    gate.record_review(state["revision_path"], payload)
                self.assertEqual(err.exception.code, expected_code)

        # Supporting element omitted_with_reason with empty quote and non-generic assessment succeeds in evaluate
        omitted_payload = self.build_review_payload(state)
        next(c for c in omitted_payload["checks"] if c["id"] == "C04")["facet_realization"]["supporting_elements"][0].update(
            status="omitted_with_reason",
            quote="",
            assessment="Condensed out of this short version after verifying the reader already understands the gap.",
        )
        omitted_eval, *_ = gate.evaluate(state["revision_path"], omitted_payload)
        self.assertTrue(omitted_eval["facet_realization_complete"])

        # Valid facet_realization recorded -> awaiting_author, article_review_package.topic_facets present
        rec = gate.record_review(state["revision_path"], self.build_review_payload(state))
        self.assertTrue(rec["facet_realization_complete"])
        self.assertFalse(rec["may_advance"])

        req_full = copy.deepcopy(req_with_ctx)
        req_full["current"]["author_revision"] = {
            "path": str(state["revision_path"]),
            "sha256": agent.sha256_file(state["revision_path"]),
        }
        res_awaiting = agent.resolve_request(req_full)
        self.assertEqual(res_awaiting["status"], "awaiting_author")
        self.assertFalse(res_awaiting["publication_authority"])
        self.assertEqual(
            res_awaiting["article_review_package"]["topic_facets"]["main_element"]["element_id"],
            "element-inventory-first",
        )
        self.assertTrue(res_awaiting["article_editorial_status"]["facet_realization_complete"])

        # 6. carry_over(): unaffected change preserves C04 reuse_from and rejects tampering;
        # deleted anchor quote in new draft invalidates C04 and populates scaffold.
        reuse_out = self.root / "carry-reuse.json"
        reused = gate.carry_over(state["revision_path"], ["media"], reuse_out, actor="synthetic_fixture")
        self.assertIn("C04", reused["carried_over_checks"])
        reused_tpl = json.loads(reuse_out.read_text(encoding="utf-8"))
        tampered_reuse = copy.deepcopy(reused_tpl)
        c04_reuse = next(c for c in tampered_reuse["checks"] if c["id"] == "C04")
        c04_reuse["facet_realization"]["dominant_action_check"]["assessment"] = "Edited without re-evaluating."
        with self.assertRaises(author.AuthorWritingError) as err:
            gate.record_review(state["revision_path"], tampered_reuse)
        self.assertEqual(err.exception.code, "editorial_reuse_changed")

        trimmed_text = DRAFT_TEXT.replace(
            "The family realized nobody could list all existing policies together.\n",
            "The household checked each folder slowly.\n",
        )
        new_draft_path = self.write(trimmed_text, ".md")
        new_rev_data = author.revision_envelope(
            self.db,
            state["author_ctx_path"],
            new_draft_path,
            {
                "before": DRAFT_TEXT,
                "reasons": [{"actor": "assistant", "text": "Removed supporting sentence", "source_ref": "test:revision-2"}],
                "source_ref": "test:revision-2",
                "privacy_status": "non_sensitive",
            },
        )
        new_rev_path = self.write(new_rev_data)
        carry_out = self.root / "carry-invalidated.json"
        carried = gate.carry_over(new_rev_path, ["wording"], carry_out, actor="synthetic_fixture")
        self.assertIn("C04", carried["affected_checks_requiring_evaluation"])
        c04_new = next(c for c in carried["template"]["checks"] if c["id"] == "C04")
        self.assertEqual(c04_new["state"], "unchecked")
        self.assertIsNone(c04_new["reuse_from"])
        self.assertEqual(c04_new["facet_realization"]["angle_id"], "angle-first-inventory")
        self.assertEqual(c04_new["facet_realization"]["main_element"]["element_id"], "element-inventory-first")
        self.assertEqual(c04_new["facet_realization"]["supporting_elements"][0]["element_id"], "element-family-observation")

    def test_general_script_four_stage_topic_facets_handoff(self) -> None:
        state = self.setup_editorial_piece(
            kind="script",
            platform="douyin",
            content_format="short-video-narration",
            request_id="synthetic-script-facet-01",
        )
        # Missing author_context -> writing_handoff + --topic-decision + topic_facets_bound
        res0 = agent.resolve_request(state["req"])
        self.assertEqual(res0["primary_entry"], "canonical_format_adapter")
        self.assertEqual(res0["status"], "needs_context")
        self.assertIn("writing_handoff", res0)
        self.assertIn("--topic-decision", res0["next_action"]["argv"])
        self.assertTrue(res0["lightweight_workflow"]["topic_facets_bound"])

        # With author_context + entry_binding preflight + author_revision (before editorial review)
        req_rev = copy.deepcopy(state["req"])
        req_rev["current"]["author_context"] = {
            "path": str(state["author_ctx_path"]),
            "sha256": agent.sha256_file(state["author_ctx_path"]),
        }
        binding = agent.resolve_request(req_rev)["entry_binding"]
        pre = copy.deepcopy(state["pre_data"])
        pre["entry_binding"] = binding
        gate.record_preflight(state["author_ctx_path"], pre)

        req_rev["current"]["author_revision"] = {
            "path": str(state["revision_path"]),
            "sha256": agent.sha256_file(state["revision_path"]),
        }
        res_prereview = agent.resolve_request(req_rev)
        s2_pre = res_prereview["lightweight_workflow"]["stage_details"]["stage_2_production"]
        self.assertEqual(s2_pre["status"], "pending_review")
        self.assertFalse(s2_pre["verified"])

        # After C04 editorial review, before author confirmation
        gate.record_review(state["revision_path"], self.build_review_payload(state))
        res_awaiting = agent.resolve_request(req_rev)
        self.assertEqual(res_awaiting["status"], "awaiting_author")
        self.assertIn("draft_review_package", res_awaiting)
        self.assertEqual(
            res_awaiting["draft_review_package"]["topic_facets"]["main_element"]["element_id"],
            "element-inventory-first",
        )
        self.assertTrue(res_awaiting["editorial_status"]["facet_realization_complete"])
        s2_mid = res_awaiting["lightweight_workflow"]["stage_details"]["stage_2_production"]
        self.assertEqual(s2_mid["status"], "pending_review")
        self.assertFalse(s2_mid["verified"])

        # After author confirmation attaches to this exact revision
        confirmed_rev_data = author.attach_review(
            self.db,
            state["revision_path"],
            {"actor": "synthetic_fixture", "source_ref": "test:explicit-confirmation", "decisions": []},
        )
        confirmed_rev_path = self.write(confirmed_rev_data)
        req_confirmed = copy.deepcopy(req_rev)
        req_confirmed["current"]["author_revision"] = {
            "path": str(confirmed_rev_path),
            "sha256": agent.sha256_file(confirmed_rev_path),
        }
        # Re-record review on the confirmed envelope? Wait: revision_ref record_id is identical so existing review already covers it!
        res_done = agent.resolve_request(req_confirmed)
        self.assertEqual(res_done["status"], "selected")
        self.assertTrue(res_done["editorial_status"]["may_advance"])
        s2_done = res_done["lightweight_workflow"]["stage_details"]["stage_2_production"]
        self.assertEqual(s2_done["status"], "completed")
        self.assertTrue(s2_done["verified"])
        self.assertIn("stage_2_production", res_done["lightweight_workflow"]["completed_stages"])

    def test_theory_grounding_on_demand_routing_and_staged_title_preserved(self) -> None:
        index = entry_selection.skill_index(agent)
        entries = index["entries"]
        self.assertEqual(index["contract_set_version"], "1.9.2")

        for sid in ("dbs-standard-answer", "dbs-theory-grounding"):
            self.assertIn(sid, entries)
            self.assertEqual(entries[sid]["invocation_count"], 1)
            self.assertEqual(entries[sid]["applicability_fragments"][0]["status"], "on-demand")

        self.assertIn("dbs-title-cover-intro", entries)
        self.assertEqual(entries["dbs-title-cover-intro"]["invocation_count"], 1)
        self.assertGreaterEqual(len(entries["dbs-title-cover-intro"]["applicability_fragments"]), 2)

        # Confirmed decision containing a theory element emits hints in resolve() and review_facets()
        state = self.setup_editorial_piece(kind="article", platform="wechat-article", with_theory=True)
        resolved = agent.resolve_request(state["req"])
        self.assertIn("theory_grounding_hint", resolved)
        self.assertEqual(
            resolved["theory_grounding_hint"]["skills"],
            ["dbs-theory-grounding", "dbs-standard-answer"],
        )

        decision_doc = fad.load_json(state["decision_path"])
        facet_report = fad.review_facets(decision_doc)
        self.assertEqual(
            facet_report["theory_grounding_skills"],
            ["dbs-theory-grounding", "dbs-standard-answer"],
        )

        # Unverified theory element continues to fail closed with on-demand & supplement guidance
        unverified_input = self.confirmed_decision_input(with_theory=True, verify_theory=False)
        with self.assertRaises(fad.TopicAngleError) as err:
            fad.create_receipt_from_value(unverified_input)
        self.assertEqual(err.exception.code, "facet_theory_source_unverified")
        self.assertIn("dbs-theory-grounding", str(err.exception))
        self.assertIn("dbs-standard-answer", str(err.exception))
        self.assertIn("supplement", str(err.exception))

    def test_managed_recipe_validate_context_manifest_enforces_topic_facets_binding(self) -> None:
        prepare_cmd = agent.authoring_capability()["commands"]["prepare_context"]
        self.assertIn("--topic-decision", prepare_cmd)

        decision_path, _ = self.make_decision_ref()
        other_decision_path, _ = self.make_decision_ref(with_theory=True)
        brief = {
            "content_id": "synthetic-managed-facet-content",
            "account_id": "synthetic-managed-author",
            "genre": "spoken_script",
            "synthetic_only": True,
            "privacy_status": "non_sensitive",
            "source_ref": "synthetic:managed-facet-source",
            "judgments": [],
        }
        source = self.write("Managed synthetic source: a plan, not an existing product.", ".md")
        source_ev = {**author.ref(source), "quote": "a plan, not an existing product"}
        preflight_payload = {
            "route": "expository",
            "actor": "synthetic_fixture",
            "source": source_ev,
            "items": [
                {
                    "id": item_id,
                    "state": "ready",
                    "reason": f"Synthetic managed preflight ready for {item_id}",
                    "evidence": [source_ev],
                }
                for item_id in sorted(gate.PRE)
            ],
        }

        unbound_ctx = self.write(
            author.prepare_context(self.db, {**brief, "content_id": "managed-unbound"}, "synthetic-managed-req-01")
        )
        bound_ctx = self.write(
            author.prepare_context(
                self.db,
                {**brief, "content_id": "managed-bound"},
                "synthetic-managed-req-01",
                topic_decision_path=decision_path,
            )
        )
        wrong_ctx = self.write(
            author.prepare_context(
                self.db,
                {**brief, "content_id": "managed-wrong"},
                "synthetic-managed-req-01",
                topic_decision_path=other_decision_path,
            )
        )
        for ctx_path in (unbound_ctx, bound_ctx, wrong_ctx):
            ctx_cid = author.load(ctx_path)["author_brief"]["content_id"]
            fc_path = self.write({
                "schema": "content-fact-card.v0",
                "content_id": ctx_cid,
                "canonical_status": "locked_for_draft",
                "human_confirmation": {"quote": f"Synthetic managed fact confirmation for {ctx_cid}"},
            })
            gate.record_preflight(ctx_path, {**preflight_payload, "fact_card_ref": author.ref(fc_path)})

        capsule = {
            "request_id": "synthetic-managed-req-01",
            "provenance": {
                "synthetic_only": True,
                "author_identity": {"account_id": "synthetic-managed-author", "genre": "spoken_script"},
            },
        }

        for role, step_id in (
            ("topic-angle-decision", "draft-one-observation"),
            ("topic-angle-decision-if-upstream-selected", "project-case-script"),
        ):
            with self.subTest(role=role, step_id=step_id):
                step = {"step_id": step_id, "input_roles": [role, "author-writing-context"], "context_stage": "draft"}

                def make_manifest(ctx_path: Path, dec_path: Path) -> Path:
                    return self.write({
                        "schema_version": "self-media-context-input.v1",
                        "task_id": "synthetic-managed-req-01",
                        "stage": "draft",
                        "budget": {"max_inline_bytes": 4096},
                        "artifacts": [
                            {
                                "artifact_id": "dec",
                                "role": "source_manifest",
                                "source_role": role,
                                "path": dec_path.name,
                                "load_mode": "reference",
                                "expected_sha256": agent.sha256_file(dec_path),
                            },
                            {
                                "artifact_id": "ctx",
                                "role": "source_manifest",
                                "source_role": "author-writing-context",
                                "path": ctx_path.name,
                                "load_mode": "reference",
                                "expected_sha256": agent.sha256_file(ctx_path),
                            },
                        ],
                    })

                unbound_manifest = make_manifest(unbound_ctx, decision_path)
                with self.assertRaises(author.AuthorWritingError) as err:
                    author.validate_context_manifest(unbound_manifest, capsule, step)
                self.assertEqual(err.exception.code, "author_topic_facets_unbound")
                author.validate_context_manifest(unbound_manifest, capsule, step, historical=True)

                wrong_manifest = make_manifest(wrong_ctx, decision_path)
                with self.assertRaises(author.AuthorWritingError) as err:
                    author.validate_context_manifest(wrong_manifest, capsule, step)
                self.assertEqual(err.exception.code, "author_topic_decision_mismatch")

                pending_path, _ = self.make_decision_ref(confirmed=False)
                pending_manifest = make_manifest(bound_ctx, pending_path)
                with self.assertRaises(author.AuthorWritingError) as err:
                    author.validate_context_manifest(pending_manifest, capsule, step)
                self.assertEqual(err.exception.code, "author_topic_decision_not_ready")

                valid_manifest = make_manifest(bound_ctx, decision_path)
                author.validate_context_manifest(valid_manifest, capsule, step)

    def test_c04_findings_allows_truthful_incomplete_facets_without_advancing(self) -> None:
        incomplete_draft = "\n".join([
            "# Incomplete Synthetic Draft",
            "I want to build a model.",
            "It is a plan, not an existing product.",
            "The family realized nobody could list all existing policies together.",
        ])
        state = self.setup_editorial_piece(
            kind="script",
            platform="douyin",
            content_format="short-video-narration",
            request_id="synthetic-script-findings-01",
            draft_text=incomplete_draft,
        )
        req_rev = copy.deepcopy(state["req"])
        req_rev["current"]["author_context"] = {
            "path": str(state["author_ctx_path"]),
            "sha256": agent.sha256_file(state["author_ctx_path"]),
        }
        binding = agent.resolve_request(req_rev)["entry_binding"]
        pre = copy.deepcopy(state["pre_data"])
        pre["entry_binding"] = binding
        gate.record_preflight(state["author_ctx_path"], pre)

        # Even if author confirmed the revision envelope separately, incomplete C04 findings must block advance
        confirmed_rev = self.write(
            author.attach_review(
                self.db,
                state["revision_path"],
                {"actor": "synthetic_fixture", "source_ref": "test:confirm-for-findings-test", "decisions": []},
            )
        )
        state["revision_path"] = confirmed_rev
        req_rev["current"]["author_revision"] = {
            "path": str(confirmed_rev),
            "sha256": agent.sha256_file(confirmed_rev),
        }
        rev_record_id = author.load(confirmed_rev)["revision_ref"]["record_id"]

        # Case A: state="findings" + omitted facet_realization + required issue -> records truthfully, cannot advance
        omitted_findings = self.build_review_payload(state, omit_facet_realization=True)
        c04_a = next(c for c in omitted_findings["checks"] if c["id"] == "C04")
        c04_a.update(
            state="findings",
            issue_ids=["FACET-01"],
            reason="Initial draft omits both main element and dominant judgment action.",
        )
        omitted_findings["issues"] = [{
            "id": "FACET-01",
            "first_revision": rev_record_id,
            "check_ids": ["C04"],
            "required": True,
            "state": "open",
            "before": "It is a plan, not an existing product.",
            "after": "",
            "reason": "Main inventory element and judgment call are still missing.",
            "verification": [],
            "reopened_by": [],
            "verified_draft_sha256": None,
        }]
        rec_a = gate.record_review(confirmed_rev, omitted_findings)
        self.assertTrue(rec_a["checks_complete"])
        self.assertFalse(rec_a["facet_realization_complete"])
        self.assertFalse(rec_a["may_advance"])

        resolved_a = agent.resolve_request(req_rev)
        self.assertEqual(resolved_a["status"], "needs_context")
        self.assertIn("current_editorial_checks_and_required_issue_resolution", resolved_a["missing_inputs"])
        self.assertNotIn("draft_review_package", resolved_a)
        self.assertEqual(resolved_a["lightweight_workflow"]["stage_details"]["stage_2_production"]["status"], "pending_review")

        # Case B: state="findings" + explicit missing/empty facet_realization even with required=False issue -> blocks advance
        opt_state = self.setup_editorial_piece(
            kind="script",
            platform="douyin",
            content_format="short-video-narration",
            request_id="synthetic-script-findings-opt-01",
            draft_text=incomplete_draft,
        )
        gate.record_preflight(opt_state["author_ctx_path"], opt_state["pre_data"])
        opt_rev = self.write(
            author.attach_review(
                self.db,
                opt_state["revision_path"],
                {"actor": "synthetic_fixture", "source_ref": "test:confirm-opt-findings", "decisions": []},
            )
        )
        opt_state["revision_path"] = opt_rev
        opt_rev_id = author.load(opt_rev)["revision_ref"]["record_id"]

        explicit_missing = self.build_review_payload(opt_state)
        c04_b = next(c for c in explicit_missing["checks"] if c["id"] == "C04")
        c04_b.update(
            state="findings",
            issue_ids=["FACET-OPT-01"],
            reason="Recorded per-facet gaps: supporting observation is present, main and action are missing.",
        )
        c04_b["facet_realization"] = {
            "angle_id": "angle-first-inventory",
            "dominant_action": "judgment",
            "main_element": {
                "element_id": "element-inventory-first",
                "quote": "",
                "assessment": "Main inventory recommendation is not yet drafted in this revision.",
            },
            "supporting_elements": [{
                "element_id": "element-family-observation",
                "relation": "illustrates",
                "status": "missing",
                "quote": "",
                "assessment": "Placeholder observation still needs sharper tie-in once main element is drafted.",
            }],
            "dominant_action_check": {
                "quote": "",
                "assessment": "Actionable judgment criterion is still missing from the draft.",
            },
        }
        explicit_missing["issues"] = [{
            "id": "FACET-OPT-01",
            "first_revision": opt_rev_id,
            "check_ids": ["C04"],
            "required": False,
            "state": "open",
            "before": "It is a plan, not an existing product.",
            "after": "",
            "reason": "Testing non-required open issue cannot bypass incomplete facet realization.",
            "verification": [],
            "reopened_by": [],
            "verified_draft_sha256": None,
        }]
        rec_b = gate.record_review(opt_rev, explicit_missing)
        self.assertFalse(rec_b["facet_realization_complete"])
        self.assertFalse(rec_b["may_advance"])

        # Case C: fake non-empty quote under state="findings" still fails closed
        fake_quote = copy.deepcopy(explicit_missing)
        fake_quote["previous_review_id"] = rec_b["record"]["record_id"]
        next(c for c in fake_quote["checks"] if c["id"] == "C04")["facet_realization"]["main_element"]["quote"] = "fabricated text"
        with self.assertRaises(author.AuthorWritingError) as err:
            gate.evaluate(opt_rev, fake_quote)
        self.assertEqual(err.exception.code, "editorial_facet_anchor_missing")

        # Case D: retained still rejects missing/empty facet anchors
        for bad_kind in ("empty_main", "missing_status"):
            retained_bad = self.build_review_payload(opt_state)
            retained_bad["previous_review_id"] = rec_b["record"]["record_id"]
            retained_bad["issues"] = copy.deepcopy(explicit_missing["issues"])
            c04_d = next(c for c in retained_bad["checks"] if c["id"] == "C04")
            if bad_kind == "empty_main":
                c04_d["facet_realization"]["main_element"]["quote"] = ""
            else:
                c04_d["facet_realization"]["supporting_elements"][0]["status"] = "missing"
                c04_d["facet_realization"]["supporting_elements"][0]["quote"] = ""
            with self.assertRaises(ValueError):
                gate.evaluate(opt_rev, retained_bad)

        # Case E: complete valid anchors under state="findings" (with existing full draft) sets facet_realization_complete=True
        full_state = self.setup_editorial_piece(
            kind="script",
            platform="douyin",
            content_format="short-video-narration",
            request_id="synthetic-script-findings-02",
        )
        gate.record_preflight(full_state["author_ctx_path"], full_state["pre_data"])
        full_rev_id = author.load(full_state["revision_path"])["revision_ref"]["record_id"]
        full_findings = self.build_review_payload(full_state)
        next(c for c in full_findings["checks"] if c["id"] == "C04").update(
            state="findings",
            issue_ids=["STRUCT-01"],
            reason="All facet anchors exist, but paragraph pacing between lines 3 and 4 still needs tightening.",
        )
        full_findings["issues"] = [{
            "id": "STRUCT-01",
            "first_revision": full_rev_id,
            "check_ids": ["C04"],
            "required": True,
            "state": "open",
            "before": "It is a plan, not an existing product.",
            "after": "",
            "reason": "Tighten transition sentence.",
            "verification": [],
            "reopened_by": [],
            "verified_draft_sha256": None,
        }]
        res_e, *_ = gate.evaluate(full_state["revision_path"], full_findings)
        self.assertTrue(res_e["facet_realization_complete"])
        self.assertFalse(res_e["may_advance"])

    def test_managed_verify_step_blocks_incomplete_c04_and_attaches_theory_hint(self) -> None:
        decision_path, _ = self.make_decision_ref(with_theory=True)
        brief = {
            "content_id": "synthetic-moments-c04-content",
            "account_id": "synthetic-moments-author",
            "genre": "moments",
            "synthetic_only": True,
            "privacy_status": "non_sensitive",
            "source_ref": "synthetic:moments-c04-source",
            "judgments": [],
        }
        author_ctx = self.write(
            author.prepare_context(self.db, brief, "synthetic-moments-c04-req", topic_decision_path=decision_path)
        )
        source_ev = editorial_fixture.preparation(author_ctx)
        draft_path = self.write(DRAFT_TEXT, ".md")
        revision_path = self.write(
            author.revision_envelope(
                self.db,
                author_ctx,
                draft_path,
                {
                    "before": "",
                    "reasons": [{"actor": "assistant", "text": "Synthetic draft", "source_ref": "test:moments-draft"}],
                    "source_ref": "test:moments-draft",
                    "privacy_status": "non_sensitive",
                },
            )
        )

        request = json.loads(
            (ROOT / "fixtures/agent-entry/moments-short-post.request.json").read_text(encoding="utf-8")
        )
        request["request_id"] = "synthetic-moments-c04-req"
        request["synthetic_only"] = True
        request["author_identity"] = {"account_id": "synthetic-moments-author", "genre": "moments"}
        capsule = agent.resolve_request(request)
        capsule_path = self.write(capsule)

        placeholder = self.write({"synthetic_only": True, "note": "isolated transport fixture"})
        creative_ctx = json.loads(
            (ROOT / "fixtures/creation-route-v1/same-day-activity-highlights.context.json").read_text(encoding="utf-8")
        )
        creative_ctx.update(
            task_id="synthetic-moments-c04-req",
            topic_domain="explanation",
            primary_intent="explain-or-answer",
            requested_vlog_style="auto",
            requested_route="auto",
        )
        route_ctx_path = self.write(creative_ctx)
        route_dec_path = self.write(creation_route.resolve(creative_ctx))

        def build_step_manifest(step: dict, extra: dict[str, Path] | None = None, body: Path | None = None) -> Path:
            role_paths = {role: placeholder for role in step["input_roles"]}
            role_paths["topic-angle-decision"] = decision_path
            role_paths["author-writing-context"] = author_ctx
            if step["step_id"] in creation_route.WRITING_STEPS:
                role_paths["creation-route-context"] = route_ctx_path
                role_paths["creation-route-decision"] = route_dec_path
            if extra:
                role_paths.update(extra)
            manifest = {
                "schema_version": "self-media-context-input.v1",
                "task_id": "synthetic-moments-c04-req",
                "stage": step["context_stage"],
                "budget": {"max_inline_bytes": 4096},
                "artifacts": [
                    {
                        "artifact_id": f"in-{idx}",
                        "role": "source_manifest",
                        "source_role": role,
                        "path": path.name,
                        "load_mode": "reference",
                        "expected_sha256": agent.sha256_file(path),
                    }
                    for idx, (role, path) in enumerate(role_paths.items())
                ],
            }
            editorial_fixture.bind_stage_purpose(
                manifest,
                self.root,
                "synthetic-moments-c04-content",
                f"Carry synthetic purpose through {step['step_id']}.",
                body,
            )
            return self.write(manifest)

        prev_receipt: Path | None = None
        for step in capsule["step_index"][:3]:
            mpath = build_step_manifest(step)
            hpath = self.root / f"{step['step_id']}-handoff.json"
            handoff = agent.prepare_step_handoff(
                capsule_path,
                step["step_id"],
                mpath,
                self.root / f"{step['step_id']}-ctx-rcpt.json",
                hpath,
                prev_receipt,
            )
            out_paths = [placeholder]
            review_out = editorial_fixture.stage_purpose_review(hpath, placeholder)
            if review_out is not None:
                out_paths.append(review_out)
            rcpt = {
                "schema_version": "self-media-step-output-receipt.v1",
                "status": "human_gate_recorded" if step["interface"] == "human_gate" else "candidate_ready",
                "handoff": {"path": hpath.name, "sha256": agent.sha256_file(hpath)},
                "step_id": step["step_id"],
                "tool_id": step["tool_id"],
                "output_contract": step["output_contract"],
                "outputs": [{"path": p.name, "sha256": agent.sha256_file(p)} for p in out_paths],
                "boundaries": copy.deepcopy(capsule["boundaries"]),
            }
            rcpt["payload_sha256"] = agent.sha256_value(rcpt)
            prev_receipt = self.write(rcpt)
            self.assertTrue(agent.verify_step_output(hpath, prev_receipt)["ok"])

        draft_step = capsule["step_index"][3]
        self.assertEqual(draft_step["step_id"], "draft-one-observation")
        draft_manifest = build_step_manifest(draft_step)
        draft_handoff_path = self.root / "draft-step-handoff.json"
        draft_handoff = agent.prepare_step_handoff(
            capsule_path,
            "draft-one-observation",
            draft_manifest,
            self.root / "draft-step-ctx-rcpt.json",
            draft_handoff_path,
            prev_receipt,
        )
        self.assertEqual(
            draft_handoff["execution_brief"]["theory_grounding_hint"]["skills"],
            ["dbs-theory-grounding", "dbs-standard-answer"],
        )
        self.assertEqual(agent.validate_step_handoff(draft_handoff_path)["handoff_id"], draft_handoff["handoff_id"])

        draft_stage_review = editorial_fixture.stage_purpose_review(draft_handoff_path, draft_path)
        draft_outputs = [draft_path, revision_path]
        if draft_stage_review is not None:
            draft_outputs.append(draft_stage_review)
        draft_rcpt_data = {
            "schema_version": "self-media-step-output-receipt.v1",
            "status": "candidate_ready",
            "handoff": {"path": draft_handoff_path.name, "sha256": agent.sha256_file(draft_handoff_path)},
            "step_id": draft_step["step_id"],
            "tool_id": draft_step["tool_id"],
            "output_contract": draft_step["output_contract"],
            "outputs": [{"path": p.name, "sha256": agent.sha256_file(p)} for p in draft_outputs],
            "boundaries": copy.deepcopy(capsule["boundaries"]),
        }
        draft_rcpt_data["payload_sha256"] = agent.sha256_value(draft_rcpt_data)
        draft_rcpt_path = self.write(draft_rcpt_data)

        # Incomplete C04 findings even with required=False issue must fail verify_step_output & _validate_previous_step
        env = author.load(revision_path)
        rev_record_id = env["revision_ref"]["record_id"]
        incomplete_payload = {
            "request_id": "synthetic-moments-c04-req",
            "draft_ref": env["draft_ref"],
            "phase": "draft",
            "route": "expository",
            "previous_review_id": None,
            "feedback_ids": [],
            "changes": [],
            "actor": "synthetic_fixture",
            "source": source_ev,
            "observations": {"readthrough": None, "final_media": None},
            "issues": [{
                "id": "M-FACET-01",
                "first_revision": rev_record_id,
                "check_ids": ["C04"],
                "required": False,
                "state": "open",
                "before": "It is a plan, not an existing product.",
                "after": "",
                "reason": "Main inventory facet missing; non-required flag cannot bypass gate.",
                "verification": [],
                "reopened_by": [],
                "verified_draft_sha256": None,
            }],
            "checks": [
                {
                    "id": cid,
                    "state": "findings" if cid == "C04" else "retained",
                    "scope": "script-text",
                    "quote": "It is a plan, not an existing product.",
                    "reason": f"Synthetic check reason for {cid}",
                    "evidence": [source_ev],
                    "issue_ids": ["M-FACET-01"] if cid == "C04" else [],
                    "reuse_from": None,
                    **(
                        {
                            "purpose_alignment": {
                                "stage_duty": "Keep purpose visible.",
                                "contribution": "Direct synthetic framing.",
                                "misunderstanding_risk": "Could mistake draft plan for shipped capability.",
                                "tradeoff": "Keep wording explicit.",
                            }
                        }
                        if cid == "C01"
                        else {}
                    ),
                }
                for cid in sorted(gate.CHECKS)
            ],
        }
        rec1 = gate.record_review(revision_path, incomplete_payload)
        self.assertFalse(rec1["facet_realization_complete"])

        blocked_verify = agent.verify_step_output(draft_handoff_path, draft_rcpt_path)
        self.assertFalse(blocked_verify["ok"])
        self.assertEqual(blocked_verify["status"], "blocked")
        self.assertFalse(blocked_verify["editorial_integrity"]["facet_realization_complete"])

        confirm_step = capsule["step_index"][4]
        reviewed_env = self.write(
            author.attach_review(
                self.db,
                revision_path,
                {"actor": "synthetic_fixture", "source_ref": "test:moments-confirm", "decisions": []},
            )
        )
        confirm_manifest = build_step_manifest(
            confirm_step,
            extra={"moments-candidate": draft_path, "author-revision-review": reviewed_env},
            body=draft_path,
        )
        with self.assertRaises(agent.AgentEntryError) as blocked_next:
            agent.prepare_step_handoff(
                capsule_path,
                "confirm-author-voice",
                confirm_manifest,
                self.root / "confirm-ctx-rcpt.json",
                self.root / "confirm-handoff.json",
                draft_rcpt_path,
            )
        self.assertEqual(blocked_next.exception.code, "previous_step_blocked")

        # Complete C04 facet_realization + close issue -> verify_step_output succeeds
        complete_payload = copy.deepcopy(incomplete_payload)
        complete_payload["previous_review_id"] = rec1["record"]["record_id"]
        complete_payload["issues"][0].update(
            state="retained",
            after="It is a plan, not an existing product.",
            reason="Verified retention with full facet realization anchors.",
            verification=[source_ev],
            verified_draft_sha256=env["draft_ref"]["sha256"],
        )
        next(c for c in complete_payload["checks"] if c["id"] == "C04").update(
            state="retained",
            issue_ids=["M-FACET-01"],
            facet_realization={
                "angle_id": "angle-first-inventory",
                "dominant_action": "judgment",
                "main_element": {
                    "element_id": "element-inventory-first",
                    "quote": "First inventory what policies the family already holds",
                    "assessment": "Opening anchors the piece on policy inventory.",
                },
                "supporting_elements": [{
                    "element_id": "element-family-observation",
                    "relation": "illustrates",
                    "status": "realized",
                    "quote": "nobody could list all existing policies together",
                    "assessment": "Observation directly illustrates why inventory comes first.",
                }],
                "dominant_action_check": {
                    "quote": "compare nothing until the existing list is complete",
                    "assessment": "Judgment boundary is explicit.",
                },
            },
        )
        rec2 = gate.record_review(revision_path, complete_payload)
        self.assertTrue(rec2["facet_realization_complete"])
        passed_verify = agent.verify_step_output(draft_handoff_path, draft_rcpt_path)
        self.assertTrue(passed_verify["ok"])

    def test_prerecord_case_step_optionally_consumes_topic_facets(self) -> None:
        request = json.loads((ROOT / "fixtures/agent-entry/prerecord-spoken.request.json").read_text(encoding="utf-8"))
        req_id = request["request_id"]
        decision_path, _ = self.make_decision_ref()
        brief = {
            "content_id": "synthetic-prerecord-facet-content",
            "account_id": request["author_identity"]["account_id"],
            "genre": request["author_identity"]["genre"],
            "synthetic_only": True,
            "privacy_status": "non_sensitive",
            "source_ref": "synthetic:prerecord-facet-source",
            "judgments": [],
        }
        unbound_ctx = self.write(author.prepare_context(self.db, {**brief, "content_id": "pre-unbound"}, req_id))
        bound_ctx = self.write(
            author.prepare_context(
                self.db, {**brief, "content_id": "pre-bound"}, req_id, topic_decision_path=decision_path
            )
        )
        editorial_fixture.preparation(unbound_ctx)
        editorial_fixture.preparation(bound_ctx)

        capsule = agent.resolve_request(request)
        capsule_path = self.write(capsule)
        step = capsule["step_index"][0]
        self.assertEqual(step["step_id"], "draft-prerecord-case")

        placeholder = self.write({"synthetic_only": True, "note": "isolated prerecord stub"})
        creative_ctx = json.loads(
            (ROOT / "fixtures/creation-route-v1/same-day-activity-highlights.context.json").read_text(encoding="utf-8")
        )
        creative_ctx.update(
            task_id=req_id,
            topic_domain="case",
            primary_intent="explain-or-answer",
            material_state="planned",
            material_summary="Synthetic prerecord test material.",
            assessment_reason="Explain prerecord question cleanly.",
            source_refs=["synthetic-prerecord-fixture"],
        )
        route_ctx = self.write(creative_ctx)
        route_dec = self.write(creation_route.resolve(creative_ctx))

        def make_prerecord_manifest(ctx_path: Path, content_id: str, *, include_decision: bool) -> Path:
            role_paths = {role: placeholder for role in step["input_roles"]}
            role_paths["author-writing-context"] = ctx_path
            role_paths["creation-route-context"] = route_ctx
            role_paths["creation-route-decision"] = route_dec
            if include_decision:
                role_paths["topic-angle-decision"] = decision_path
            manifest = {
                "schema_version": "self-media-context-input.v1",
                "task_id": req_id,
                "stage": step["context_stage"],
                "budget": {"max_inline_bytes": 12000},
                "artifacts": [
                    {
                        "artifact_id": f"pre-{idx}",
                        "role": "source_manifest",
                        "source_role": role,
                        "path": path.name,
                        "load_mode": "reference",
                        "expected_sha256": agent.sha256_file(path),
                    }
                    for idx, (role, path) in enumerate(role_paths.items())
                ],
            }
            editorial_fixture.bind_stage_purpose(
                manifest, self.root, content_id, "Carry synthetic prerecord purpose cleanly."
            )
            return self.write(manifest)

        # Without topic-angle-decision -> still works cleanly with no topic_facets
        plain_hpath = self.root / "prerecord-plain-handoff.json"
        plain_handoff = agent.prepare_step_handoff(
            capsule_path,
            "draft-prerecord-case",
            make_prerecord_manifest(unbound_ctx, "pre-unbound", include_decision=False),
            self.root / "prerecord-plain-ctx.json",
            plain_hpath,
        )
        self.assertNotIn("topic_facets", plain_handoff["execution_brief"])

        # With topic-angle-decision + unbound author_context -> fail closed
        with self.assertRaises(agent.AgentEntryError) as err:
            agent.prepare_step_handoff(
                capsule_path,
                "draft-prerecord-case",
                make_prerecord_manifest(unbound_ctx, "pre-unbound", include_decision=True),
                self.root / "prerecord-bad-ctx.json",
                self.root / "prerecord-bad-handoff.json",
            )
        self.assertEqual(err.exception.code, "author_topic_facets_unbound")

        # With topic-angle-decision + bound author_context -> passes and emits topic_facets
        facet_hpath = self.root / "prerecord-facet-handoff.json"
        facet_handoff = agent.prepare_step_handoff(
            capsule_path,
            "draft-prerecord-case",
            make_prerecord_manifest(bound_ctx, "pre-bound", include_decision=True),
            self.root / "prerecord-facet-ctx.json",
            facet_hpath,
        )
        self.assertEqual(
            facet_handoff["execution_brief"]["topic_facets"]["main_element"]["element_id"],
            "element-inventory-first",
        )
        self.assertEqual(agent.validate_step_handoff(facet_hpath)["handoff_id"], facet_handoff["handoff_id"])

    def test_travel_experience_vlog_emits_writing_handoff_without_forcing_author_store(self) -> None:
        decision_path, decision_ref = self.make_decision_ref()
        vlog_ctx = json.loads(
            (ROOT / "fixtures/creation-route-v1/same-day-activity-highlights.context.json").read_text(encoding="utf-8")
        )
        vlog_ctx["task_id"] = "synthetic-vlog-facet-01"
        vlog_dec = creation_route.resolve(vlog_ctx)
        self.assertEqual(vlog_dec["primary_route"], "travel-experience")

        source_path = self.write("Synthetic vlog purpose: share the walk. Audience: viewers planning a trip.", ".md")
        manifest_ref = self.ref({
            "schema_version": "self-media-context-input.v1",
            "task_id": "synthetic-vlog-facet-01",
            "stage": "draft",
            "budget": {"max_inline_bytes": 4096},
            "artifacts": [
                {
                    "artifact_id": "purpose-source",
                    "role": "source_manifest",
                    "path": source_path.name,
                    "expected_sha256": agent.sha256_file(source_path),
                    "load_mode": "reference",
                },
                {
                    "artifact_id": "framework-current",
                    "role": "source_manifest",
                    "path": decision_path.name,
                    "expected_sha256": decision_ref["sha256"],
                    "load_mode": "reference",
                },
            ],
            "editorial_context": {
                "version": 1,
                "content_id": "synthetic-vlog-content",
                "topic_selection": {
                    "topic": "用Vlog记录保单整理前的真实生活触发瞬间",
                    "origin": "tool_trial",
                    "adoption": "selected",
                    "adoption_basis": "Bounded synthetic Vlog regression with confirmed facets.",
                    "origin_source": {"artifact_id": "purpose-source", "quote": "share the walk"},
                    "adoption_source": {"artifact_id": "purpose-source", "quote": "share the walk"},
                    "decision_artifact_id": "framework-current",
                },
                "purpose": {"artifact_id": "purpose-source", "quote": "share the walk"},
                "audience": {"artifact_id": "purpose-source", "quote": "viewers planning a trip"},
                "stage_duty": "Show the real experience before listing takeaways.",
                "current_body_artifact_id": None,
                "feedback": [],
                "feedback_note": "No feedback in this isolated synthetic Vlog test.",
            },
        })
        req = {
            "schema_version": "self-media-work-request.v1",
            "request_id": "synthetic-vlog-facet-01",
            "requested_output": "video_plan",
            "content_format": "demo-video",
            "platform": "youtube",
            "selection_basis": "Synthetic Vlog regression with bound topic_facets.",
            "current": {
                "creation_context": self.ref(vlog_ctx),
                "creation_decision": self.ref(vlog_dec),
                "context_manifest": manifest_ref,
                "topic_decision": decision_ref,
            },
        }
        resolved = agent.resolve_request(req)
        self.assertEqual(resolved["primary_entry"], "travel_experience")
        self.assertFalse(resolved["automatic_analysis_started"])
        self.assertEqual(
            resolved["writing_handoff"]["topic_facets"]["main_element"]["element_id"],
            "element-inventory-first",
        )
        self.assertTrue(resolved["lightweight_workflow"]["topic_facets_bound"])


if __name__ == "__main__":
    unittest.main()
