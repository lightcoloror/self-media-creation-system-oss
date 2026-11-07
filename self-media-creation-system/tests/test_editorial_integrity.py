"""Synthetic execution-integrity scenarios; isolated existing author store only."""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import author_writing_context as author
import editorial_integrity as gate


class IntegrityTests(unittest.TestCase):
    def setUp(self):
        self.test_root = Path(os.environ.get('TEST_TMP_ROOT', ROOT / '.test-runtime')).resolve()
        self.root = self.test_root / ("integrity-" + uuid.uuid4().hex)
        self.root.mkdir(parents=True)
        self.db = self.root / "synthetic.sqlite3"
        self.n = 0
        self.source = self.write("Synthetic source: a plan, not an existing product. Exact author declaration for tests only.", ".md")
        self.context = self.write(author.prepare_context(self.db, {
            "content_id": "synthetic-content", "account_id": "synthetic-author", "genre": "spoken_script",
            "synthetic_only": True, "privacy_status": "non_sensitive", "source_ref": "synthetic:source",
            "judgments": [],
        }, "synthetic-request"))
        self.pre = {"route": "expository", "actor": "synthetic_fixture", "source": self.ev(),
                    "items": [{"id": k, "state": "ready", "reason": "Synthetic preparation decision: " + k,
                               "evidence": [self.ev()]} for k in sorted(gate.PRE)]}
        gate.record_preflight(self.context, self.pre)
        self.text = "I want to build a model.\nIt is a plan, not an existing product."
        self.revision = self.rev(self.text)

    def tearDown(self):
        assert self.root.resolve().is_relative_to(self.test_root)
        shutil.rmtree(self.root)

    def write(self, data, suffix=".json"):
        self.n += 1
        p = self.root / (str(self.n) + suffix)
        p.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")
        return p

    def ev(self):
        return {**author.ref(self.source), "quote": "a plan, not an existing product"}

    def rev(self, text, before=""):
        draft = self.write(text, ".md")
        return self.write(author.revision_envelope(self.db, self.context, draft, {
            "before": before, "reasons": [{"actor": "assistant", "text": "Synthetic revision", "source_ref": "test:revision"}],
            "source_ref": "test:revision", "privacy_status": "non_sensitive"}))

    def data(self):
        env = author.load(self.revision)
        context = author.load(self.context)
        records = gate.history(context)
        previous = gate.latest(records, "editorial_review")
        data = {"request_id": "synthetic-request", "draft_ref": env["draft_ref"], "phase": "draft", "route": "expository",
                "previous_review_id": previous["record_id"] if previous else None,
                "feedback_ids": [r["record_id"] for r in records if r["record_type"] == "editorial_feedback"],
                "changes": [], "actor": "synthetic_fixture", "source": self.ev(), "issues": [],
                "observations": {"readthrough": None, "final_media": None},
                "checks": [{"id": c, "state": "retained", "scope": "script-text", "quote": "It is a plan",
                            "reason": "This exact draft preserves the planned status: " + c, "evidence": [self.ev()],
                            "issue_ids": [], "reuse_from": None} for c in sorted(gate.CHECKS)]}
        data["checks"][0]["purpose_alignment"] = {
            "stage_duty": "Help readers understand the proposed project and its present limits.",
            "contribution": "The current sentence identifies it as a plan instead of an existing product.",
            "misunderstanding_risk": "A reader could otherwise take the aspiration as a completed capability.",
            "tradeoff": "Retain the modest wording even though a completed-product claim would sound stronger.",
        }
        return data

    def confirm(self):
        self.revision = self.write(author.attach_review(self.db, self.revision, {
            "actor": "synthetic_fixture", "source_ref": "test:explicit-exact-confirmation", "decisions": []}))

    def add_issue(self, data):
        data["issues"] = [{"id": "OPEN-01", "first_revision": author.load(self.revision)["revision_ref"]["record_id"],
                           "check_ids": ["C03"], "required": True, "state": "open", "before": "I want to build a model.",
                           "after": "", "reason": "Opening promises too much", "verification": [], "reopened_by": [], "verified_draft_sha256": None}]
        row = next(c for c in data["checks"] if c["id"] == "C03")
        row.update(state="findings", issue_ids=["OPEN-01"])

    def test_A01_A02_missing_author_or_ai_check(self):
        for missing in ["C05", "C06"]:
            d = self.data(); d["checks"] = [c for c in d["checks"] if c["id"] != missing]
            result, *_ = gate.evaluate(self.revision, d)
            self.assertFalse(result["checks_complete"])
            self.assertFalse(result["may_advance"])
            self.assertEqual([missing], result["missing_checks"])

    def test_A03_generic_pass_without_evidence(self):
        for patch in [{"reason": "passed"}, {"evidence": []}]:
            d = self.data(); d["checks"][0].update(patch)
            with self.assertRaises(ValueError):
                gate.record_review(self.revision, d)

    def test_A04_wrong_task_or_digest(self):
        for key, val in [("request_id", "another-task"), ("draft_ref", {"path": "wrong", "sha256": "a" * 64})]:
            d = self.data(); d[key] = val
            with self.assertRaisesRegex(ValueError, "exact draft"):
                gate.record_review(self.revision, d)

    def test_A05_reordered_same_sentences_invalidates_reuse(self):
        old = gate.record_review(self.revision, self.data())
        self.revision = self.rev("\n".join(reversed(self.text.splitlines())), self.text)
        d = self.data(); d["changes"] = ["wording"]
        next(c for c in d["checks"] if c["id"] == "C03")["reuse_from"] = old["record"]["record_id"]
        with self.assertRaises(author.AuthorWritingError) as error:
            gate.record_review(self.revision, d)
        self.assertEqual("editorial_reuse_stale", error.exception.code)

    def test_A06_changed_claim_cannot_inherit_author_confirmation(self):
        self.confirm(); gate.record_review(self.revision, self.data())
        new = self.text.replace("want to build", "have built")
        self.revision = self.rev(new, self.text)
        d = self.data(); d["changes"] = ["claims"]
        result = gate.record_review(self.revision, d)
        self.assertFalse(result["author_confirmation_recorded"])
        self.assertFalse(result["may_advance"])

    def test_A07_A12_check_complete_not_issue_closed(self):
        self.confirm(); d = self.data(); self.add_issue(d)
        result = gate.record_review(self.revision, d)
        self.assertTrue(result["checks_complete"])
        self.assertFalse(result["required_issues_closed"])
        self.assertFalse(result["may_advance"])

    def test_A08_lost_issue_and_history_reset_rejected(self):
        d = self.data(); self.add_issue(d); gate.record_review(self.revision, d)
        with self.assertRaisesRegex(ValueError, "OPEN-01"):
            gate.record_review(self.revision, self.data())
        d["previous_review_id"] = None
        with self.assertRaisesRegex(ValueError, "latest review"):
            gate.record_review(self.revision, d)

    def test_A09_retained_reason_and_exact_author_confirmation(self):
        self.confirm(); result = gate.record_review(self.revision, self.data())
        self.assertTrue(result["may_advance"])
        self.assertTrue(gate.status(self.revision)["may_advance"])
        self.assertFalse(result["proves_editorial_quality"])

    def test_A10_no_final_media_required_for_script(self):
        self.confirm(); d = self.data()
        row = next(c for c in d["checks"] if c["id"] == "C09")
        row.update(state="not_applicable", scope="actual_media", quote="", reason="No external media exists at this drafting stage; actual media review remains later.",
                   text_review={"quote": "It is a plan", "reason": "The script makes no completed-project claim or personal disclosure.", "evidence": [self.ev()]})
        self.assertTrue(gate.record_review(self.revision, d)["may_advance"])

    def test_A11_feedback_invalidates_unchanged_text(self):
        self.confirm(); gate.record_review(self.revision, self.data())
        gate.feedback(self.context, {"feedback_id": "f1", "check_ids": ["C05"], "issue_ids": [],
                                     "reason": "This exact phrasing needs reconsideration", "source": self.ev()})
        with self.assertRaisesRegex(ValueError, "new review"):
            gate.status(self.revision)
        d = self.data(); next(c for c in d["checks"] if c["id"] == "C05")["reuse_from"] = d["previous_review_id"]
        with self.assertRaises(author.AuthorWritingError) as error:
            gate.record_review(self.revision, d)
        self.assertEqual("editorial_reuse_stale", error.exception.code)

    def test_A13_missing_confirmation_is_pending(self):
        result = gate.record_review(self.revision, self.data())
        self.assertTrue(result["checks_complete"])
        self.assertFalse(result["may_advance"])

    def test_A14_estimate_cannot_replace_actual_readthrough(self):
        self.confirm(); d = self.data(); d["phase"] = "readthrough"
        self.assertFalse(gate.evaluate(self.revision, d)[0]["may_advance"])
        d["observations"]["readthrough"] = {"kind": "estimated", "artifact": author.ref(self.source), "source": self.ev()}
        with self.assertRaisesRegex(ValueError, "estimated"):
            gate.record_review(self.revision, d)

    def test_A15_valid_reuse_and_source_drift(self):
        gate.record_review(self.revision, self.data())
        self.revision = self.rev(self.text + "\nA small wording change.", self.text)
        d = self.data(); d["changes"] = ["wording"]
        next(c for c in d["checks"] if c["id"] == "C02")["reuse_from"] = d["previous_review_id"]
        self.assertTrue(gate.record_review(self.revision, d)["checks_complete"])
        self.source.write_text("changed source", encoding="utf-8")
        with self.assertRaises(ValueError):
            gate.status(self.revision)

    def test_A16_boolean_cannot_confirm_author(self):
        d = self.data(); d["author"] = True
        with self.assertRaises(ValueError):
            gate.record_review(self.revision, d)
        with self.assertRaises(ValueError):
            author.attach_review(self.db, self.revision, {"actor": "assistant", "source_ref": "test:fake", "decisions": []})

    def test_A18_routes_do_not_require_insurance_or_story(self):
        for route in sorted(gate.ROUTES):
            self.pre["route"] = route
            gate.record_preflight(self.context, self.pre)
            d = self.data(); d["route"] = route
            self.assertTrue(gate.evaluate(self.revision, d)[0]["checks_complete"])

    def test_preparation_missing_and_no_reason_not_applicable(self):
        self.pre["items"][0]["state"] = "missing_input"
        gate.record_preflight(self.context, self.pre)
        with self.assertRaises(author.AuthorWritingError):
            gate.require_preflight(self.context)
        d = self.data(); d["checks"][0].update(state="not_applicable", reason="")
        with self.assertRaises(ValueError):
            gate.record_review(self.revision, d)

    def test_closed_issue_must_bind_current_draft_and_reopen_on_feedback(self):
        self.confirm(); d = self.data(); self.add_issue(d)
        issue = d["issues"][0]
        issue.update(state="retained", after="I want to build a model.",
                     verification=[self.ev()], verified_draft_sha256=d["draft_ref"]["sha256"])
        self.assertTrue(gate.record_review(self.revision, d)["may_advance"])
        raised = gate.feedback(self.context, {"feedback_id": "f1", "check_ids": ["C03"], "issue_ids": ["OPEN-01"],
                                  "reason": "New counterexample to the retained opening", "source": self.ev()})
        new = self.data(); new["issues"] = copy.deepcopy(d["issues"])
        next(c for c in new["checks"] if c["id"] == "C03").update(state="findings", issue_ids=["OPEN-01"])
        with self.assertRaises(author.AuthorWritingError) as error:
            gate.record_review(self.revision, new)
        self.assertEqual("editorial_issue_not_reopened", error.exception.code)
        new["issues"][0].update(state="open", reopened_by=[raised["record_id"]])
        self.assertFalse(gate.record_review(self.revision, new)["may_advance"])

    def test_no_actual_edit_cannot_be_called_revised_verified(self):
        d = self.data(); self.add_issue(d)
        d["issues"][0].update(state="fixed", after="I want to build a model.", verification=[self.ev()],
                              verified_draft_sha256=d["draft_ref"]["sha256"])
        with self.assertRaises(author.AuthorWritingError) as error:
            gate.record_review(self.revision, d)
        self.assertEqual("editorial_no_actual_edit", error.exception.code)

    def test_goal_feedback_requires_updated_preparation(self):
        gate.feedback(self.context, {"feedback_id": "goal", "check_ids": ["C01"], "issue_ids": [],
                                    "reason": "Audience changed", "source": self.ev()})
        with self.assertRaises(author.AuthorWritingError):
            gate.require_preflight(self.context)
        gate.record_preflight(self.context, self.pre)
        gate.require_preflight(self.context)

    def test_goal_cannot_be_not_applicable_and_pending_goal_cannot_advance(self):
        goal = next(r for r in self.pre["items"] if r["id"] == "goal_audience")
        goal["state"] = "not_applicable"
        with self.assertRaises(author.AuthorWritingError) as error:
            gate.record_preflight(self.context, self.pre)
        self.assertEqual("editorial_goal_not_applicable", error.exception.code)
        goal["state"] = "missing_input"
        gate.record_preflight(self.context, self.pre)
        with self.assertRaises(author.AuthorWritingError):
            gate.require_preflight(self.context)
        self.confirm()
        result = gate.evaluate(self.revision, self.data())[0]
        self.assertFalse(result["purpose_continuity_complete"])
        self.assertFalse(result["may_advance"])

    def test_C01_requires_the_preflight_purpose_source(self):
        other = self.write("An unrelated source contains the same phrase: a plan, not an existing product.", ".md")
        data = self.data()
        data["checks"][0]["evidence"] = [{**author.ref(other), "quote": "a plan, not an existing product"}]
        with self.assertRaises(author.AuthorWritingError) as error:
            gate.record_review(self.revision, data)
        self.assertEqual("editorial_purpose_source_missing", error.exception.code)

    def test_current_C01_cannot_skip_actual_output_as_not_applicable(self):
        data = self.data()
        data['checks'][0].update(state='not_applicable', quote='')
        with self.assertRaises(author.AuthorWritingError) as caught:
            gate.record_review(self.revision, data)
        self.assertEqual(caught.exception.code, 'editorial_purpose_not_applicable')

    def test_C01_requires_specific_stage_duty_and_contribution(self):
        data = self.data()
        del data["checks"][0]["purpose_alignment"]
        with self.assertRaises(author.AuthorWritingError) as error:
            gate.record_review(self.revision, data)
        self.assertEqual("editorial_purpose_alignment_missing", error.exception.code)
        for key in gate.PURPOSE_FIELDS:
            for value in ["", "passed"]:
                data = self.data(); data["checks"][0]["purpose_alignment"][key] = value
                with self.assertRaises(ValueError):
                    gate.record_review(self.revision, data)

    def test_same_purpose_allows_indirect_contribution_and_multiple_routes(self):
        # These are editorial declarations, not a prediction of audience response.
        for route, contribution in [
            ("story", "An honest number draws the intended readers into a process explained later."),
            ("expository", "The opening identifies the reader question; the body explains the reasoning."),
            ("travel-experience", "A quiet pause preserves room tone and lets the viewer experience the place."),
        ]:
            self.pre["route"] = route
            self.pre['items'][0]['reason'] = 'Explicit current synthetic route decision: ' + route
            gate.record_preflight(self.context, self.pre)
            self.revision = self.rev(self.text, self.text)
            data = self.data(); data["route"] = route
            data["checks"][0]["purpose_alignment"]["contribution"] = contribution
            result = gate.evaluate(self.revision, data)[0]
            self.assertTrue(result["purpose_continuity_complete"])
            self.assertFalse(result["proves_editorial_quality"])
            if route == "story":
                self.assertFalse(result["story_realization_complete"])
                self.assertFalse(result["may_advance"])

    def test_historical_review_without_new_alignment_is_not_upgraded(self):
        self.confirm()
        data = self.data(); del data["checks"][0]["purpose_alignment"]
        # Replay the legacy shape without writing a fabricated current review.
        result = gate.evaluate(self.revision, data, historical=True)[0]
        self.assertTrue(result["checks_complete"])
        self.assertFalse(result["purpose_continuity_complete"])
        self.assertFalse(result["may_advance"])
        with self.assertRaises(author.AuthorWritingError):
            gate.evaluate(self.revision, data)

    def test_purpose_alignment_cannot_change_under_reuse(self):
        gate.record_review(self.revision, self.data())
        data = self.data()
        row = data["checks"][0]; row["reuse_from"] = data["previous_review_id"]
        row["purpose_alignment"]["stage_duty"] = "A different stage responsibility needs a fresh assessment."
        with self.assertRaises(author.AuthorWritingError) as error:
            gate.record_review(self.revision, data)
        self.assertEqual("editorial_reuse_changed", error.exception.code)

    def test_purpose_feedback_invalidates_current_alignment_but_media_feedback_allows_reuse(self):
        self.confirm(); gate.record_review(self.revision, self.data())
        gate.feedback(self.context, {"feedback_id": "media-only", "check_ids": ["C07"], "issue_ids": [],
                                    "reason": "Recheck a subtitle typo only", "source": self.ev()})
        data = self.data(); data["checks"][0]["reuse_from"] = data["previous_review_id"]
        result = gate.record_review(self.revision, data)
        self.assertTrue(result["purpose_continuity_complete"])
        self.assertTrue(result["may_advance"])
        gate.feedback(self.context, {"feedback_id": "purpose-change", "check_ids": ["C01"], "issue_ids": [],
                                    "reason": "The intended audience has changed", "source": self.ev()})
        with self.assertRaises(author.AuthorWritingError):
            gate.status(self.revision)
        gate.record_preflight(self.context, self.pre)
        data = self.data(); data["checks"][0]["reuse_from"] = data["previous_review_id"]
        with self.assertRaises(author.AuthorWritingError) as error:
            gate.record_review(self.revision, data)
        self.assertEqual("editorial_reuse_stale", error.exception.code)

    def test_final_media_cannot_skip_rights_or_use_text_as_recording(self):
        d = self.data(); d["phase"] = "final_media"
        d["checks"][-1]["state"] = "not_applicable"
        with self.assertRaises(author.AuthorWritingError):
            gate.record_review(self.revision, d)
        d["checks"][-1]["state"] = "retained"
        for c in d["checks"]:
            if c["id"] in {"C07", "C09"}: c["scope"] = "final_media"
        d["observations"]["final_media"] = {"kind": "observed", "artifact": author.ref(self.source), "source": self.ev()}
        with self.assertRaisesRegex(ValueError, "actual recording"):
            gate.record_review(self.revision, d)

    def test_feedback_does_not_reuse_old_author_confirmation(self):
        self.confirm(); gate.record_review(self.revision, self.data())
        gate.feedback(self.context, {"feedback_id": "voice", "check_ids": ["C05"], "issue_ids": [],
                                    "reason": "Author corrects the previously accepted voice", "source": self.ev()})
        result = gate.record_review(self.revision, self.data())
        self.assertTrue(result["checks_complete"])
        self.assertFalse(result["author_confirmation_recorded"])
        self.assertFalse(result["may_advance"])
        self.revision = self.write(author.attach_review(self.db, self.revision, {
            "actor": "synthetic_fixture", "source_ref": "test:new-explicit-confirmation-after-feedback", "decisions": []}))
        self.assertTrue(gate.status(self.revision)["may_advance"])

    def test_registered_cli_rejects_missing_check_and_allows_grounded_retention(self):
        self.confirm(); d = self.data(); d["checks"] = [c for c in d["checks"] if c["id"] != "C05"]
        gate.record_review(self.revision, d)
        command = [sys.executable, "-B", str(ROOT / "scripts/self_media_agent.py"), "review-integrity", "check",
                   "--revision", str(self.revision), "--require-complete"]
        bad = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", timeout=15)
        self.assertEqual(2, bad.returncode, bad.stderr)
        self.assertEqual(["C05"], json.loads(bad.stdout)["missing_checks"])
        gate.record_review(self.revision, self.data())
        good = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", timeout=15)
        self.assertEqual(0, good.returncode, good.stdout + good.stderr)
        self.assertTrue(json.loads(good.stdout)["may_advance"])

    def test_read_only_manuscript_admission_does_not_invent_records(self):
        draft = author.checked_ref(author.load(self.revision)["draft_ref"])
        before = gate.history(author.load(self.context))
        result = gate.check_draft(draft)
        self.assertIsNone(result["checks_complete"])
        self.assertFalse(result["may_advance"])
        self.assertEqual(before, gate.history(author.load(self.context)))

    def test_historical_preparation_does_not_use_later_route(self):
        old_revision = self.revision
        gate.record_review(self.revision, self.data())
        self.pre["route"] = "story"
        gate.record_preflight(self.context, self.pre)
        self.revision = self.rev(self.text + "\nA second synthetic paragraph.", self.text)
        data = self.data(); data.update(route="story", changes=["goal"])
        gate.record_review(self.revision, data)
        self.assertTrue(gate.status(old_revision, historical=True)["checks_complete"])
        with self.assertRaises(author.AuthorWritingError):
            gate.status(old_revision)

    def test_story_text_gate_requires_current_card_and_all_sentence_elements(self):
        import importlib.util
        import prerecording_validation
        owner_spec = importlib.util.spec_from_file_location("text_story_fixture", ROOT / "scripts/story_design_gate.py")
        owner = importlib.util.module_from_spec(owner_spec); owner_spec.loader.exec_module(owner)
        raw = owner.load_json(ROOT / "fixtures/story-design-card-v1/synthetic.input.json")
        raw["content_id"] = "synthetic-content"
        card = owner.create_receipt_from_value(raw)
        card_path = self.write(card)
        n = prerecording_validation._module("initial_draft_quality_gate").narrative_realization
        script = {"content_id": card["content_id"], "segments": [
            {"segment_id": f"text-{i:04}", "spoken_text": line,
             "fact_refs": card["fact_binding"]["allowed_fact_ids"]}
            for i, line in enumerate(self.text.splitlines(), 1)]}
        import hashlib
        value = n.template(script, card, hashlib.sha256(self.text.encode()).hexdigest())
        spans = [("text-0001", self.text.splitlines()[0]), ("text-0002", "It is a plan"),
                 ("text-0002", "not an existing product.")]
        for i, item in enumerate(value["elements"]):
            sid, span = spans[i % len(spans)]
            item.update(status="clear", judgment="Invented transport evidence for this synthetic test element.",
                anchors=[{"segment_id": sid, "spoken_span": span,
                          "fact_refs": n.required_elements(card)[item["element_id"]][:1]}])
        for item in value["craft"].values():
            item.update(status="not_applicable", judgment="No confirmed quotation is part of this invented text fixture.")
        row = {"story_card_ref": author.ref(card_path), "story_realization": value}
        context = author.load(self.context)
        self.assertTrue(gate.story_text_review(context, self.text, row))
        self.assertFalse(gate.story_text_review(context, self.text, {}))
        value["elements"].pop()
        with self.assertRaises(author.AuthorWritingError) as caught:
            gate.story_text_review(context, self.text, row)
        self.assertEqual("editorial_story_realization_coverage", caught.exception.code)


if __name__ == "__main__":
    unittest.main(verbosity=2)
