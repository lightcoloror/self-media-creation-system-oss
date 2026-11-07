from __future__ import annotations

import copy
import importlib.util
import json
import sqlite3
import subprocess
import sys
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("author_expression_store", ROOT / "scripts" / "author_expression_store.py")
assert SPEC and SPEC.loader
STORE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(STORE)


class AuthorExpressionTests(unittest.TestCase):
    def setUp(self):
        self.directory = ROOT / ".test-runtime" / "author-expression" / uuid.uuid4().hex
        self.directory.mkdir(parents=True)
        self.store = self.directory / "evidence.sqlite3"

    def tearDown(self):
        # Remove only the exact regular files this test creates, never a tree.
        for path in self.directory.iterdir():
            if path.is_file():
                path.unlink()
        self.directory.rmdir()

    def sample(self, **changes):
        value = {"account_id": "fictional-author", "genre": "moments", "text": "这是合成表达片段，不代表真人。", "kind": "positive",
                 "source_ref": "fixture://source", "source_kind": "author_original", "synthetic_only": True, "privacy_status": "non_sensitive",
                 "confirmation": {"status": "confirmed", "actor": "synthetic_fixture", "source_ref": "fixture://confirmation", "scope": "exact_fragment", "text_sha256": STORE.text_sha256("这是合成表达片段，不代表真人。")}}
        value.update(changes)
        return value

    def brief(self, **changes):
        value = {"content_id": "fictional-content", "account_id": "fictional-author", "genre": "moments", "synthetic_only": True,
                 "privacy_status": "non_sensitive", "source_ref": "fixture://brief", "judgments": [{"id": "j1", "original_text": "我反对这种做法。", "target": "某种虚构做法", "stance": "反对", "intensity": "明确", "basis": "合成观察", "uncertainty": "原因仍不确定"}]}
        value.update(changes)
        return value

    def revision(self, brief, before="我反对这种做法。", after="这种做法值得讨论。", **changes):
        value = {"content_id": brief["content_id"], "brief_id": brief["brief_id"], "before": before, "after": after,
                 "reasons": [{"text": "合成的AI润色建议，不冒充作者解释", "actor": "assistant", "source_ref": "fixture://revision-reason"}],
                 "source_ref": "fixture://revision", "privacy_status": "non_sensitive"}
        value.update(changes)
        return value

    def review(self, revision, **changes):
        value = {"revision_id": revision["revision_id"], "revision_sha256": revision["record_sha256"], "actor": "synthetic_fixture", "source_ref": "fixture://review",
                 "decisions": [{"judgment_id": "j1", "decision": "accepted_change", "reason": "合成测试明确接受弱化", "source_ref": "fixture://decision"}]}
        value.update(changes)
        return value

    def assert_code(self, code, operation, *args):
        with self.assertRaises(STORE.AuthorExpressionError) as raised:
            operation(*args)
        self.assertEqual(code, raised.exception.code)

    def test_nonexistent_read_does_not_create_store(self):
        self.assertEqual(0, STORE.query_samples(self.store, "a", "g")["count"])
        self.assertEqual("empty", STORE.store_status(self.store, "c")["status"])
        self.assertFalse(self.store.exists())

    def test_candidate_cannot_leak_into_recall(self):
        record = STORE.capture_sample(self.store, self.sample(confirmation={"status": "candidate", "actor": "assistant", "source_ref": "fixture://candidate"}))
        self.assertEqual("candidate", record["status"])
        self.assertEqual([], STORE.query_samples(self.store, "fictional-author", "moments", True)["samples"])

    def test_exact_confirmed_fragment_and_negative_reason_are_persisted(self):
        record = STORE.capture_sample(self.store, self.sample(kind="negative", feedback_reason="合成作者觉得像讲课"))
        again = STORE.capture_sample(self.store, self.sample(kind="negative", feedback_reason="合成作者觉得像讲课"))
        self.assertEqual(record, again)
        selected = STORE.query_samples(self.store, "fictional-author", "moments", True)["samples"]
        self.assertEqual("negative", selected[0]["payload"]["kind"])
        self.assertEqual("合成作者觉得像讲课", selected[0]["payload"]["feedback_reason"])
        self.assertEqual(1, STORE.store_status(self.store)["counts"]["sample"])

    def test_no_whole_draft_upgrade_by_reusing_fragment_confirmation(self):
        value = self.sample()
        value["text"] += "这是未获确认的新段落。"
        self.assert_code("confirmation_fragment_mismatch", STORE.capture_sample, self.store, value)
        self.assertFalse(self.store.exists())

    def test_assistant_cannot_confirm_and_real_synthetic_actors_cannot_mix(self):
        for actor in ("assistant", "author"):
            value = self.sample()
            value["confirmation"]["actor"] = actor
            self.assert_code("author_confirmation_required", STORE.capture_sample, self.store, value)
        value = self.sample(synthetic_only=False)
        self.assert_code("author_confirmation_required", STORE.capture_sample, self.store, value)

    def test_account_and_synthetic_isolation_and_genre_priority(self):
        STORE.capture_sample(self.store, self.sample(genre="article", source_ref="fixture://article"))
        STORE.capture_sample(self.store, self.sample(account_id="other"))
        STORE.capture_sample(self.store, self.sample())
        real = self.sample(synthetic_only=False, source_ref="fixture://nonsensitive-real-flag-only")
        real["confirmation"]["actor"] = "author"
        STORE.capture_sample(self.store, real)
        selected = STORE.query_samples(self.store, "fictional-author", "moments", True)["samples"]
        self.assertEqual(2, len(selected))
        self.assertEqual("same_genre_expression", selected[0]["usage_scope"])
        self.assertEqual("style_only_cross_genre", selected[1]["usage_scope"])
        self.assertEqual(1, STORE.query_samples(self.store, "fictional-author", "moments")["count"])

    def test_retraction_is_append_only_and_invalidates_only_selected_sample(self):
        record = STORE.capture_sample(self.store, self.sample())
        STORE.validate_sample_selection(self.store, [record["record_id"]], "fictional-author", True)
        payload = {"sample_id": record["record_id"], "sample_sha256": record["record_sha256"], "actor": "synthetic_fixture", "source_ref": "fixture://retract", "reason": "合成作者撤回"}
        STORE.retract_sample(self.store, payload)
        self.assertEqual(record, STORE.get_record(self.store, record["record_id"]))
        self.assertEqual(0, STORE.query_samples(self.store, "fictional-author", "moments", True)["count"])
        self.assert_code("sample_retracted", STORE.validate_sample_selection, self.store, [record["record_id"]], "fictional-author", True)

    def test_new_top_sample_does_not_invalidate_historical_selection(self):
        record = STORE.capture_sample(self.store, self.sample())
        newer = self.sample(text="新合成片段。", source_ref="fixture://newer")
        newer["confirmation"]["text_sha256"] = STORE.text_sha256(newer["text"])
        STORE.capture_sample(self.store, newer)
        STORE.validate_sample_selection(self.store, [record["record_id"]], "fictional-author", True)

    def test_recall_reserves_positive_and_negative_even_after_many_new_samples(self):
        for older_kind, newer_kind in (("negative", "positive"), ("positive", "negative")):
            account = "fictional-" + older_kind
            old = self.sample(account_id=account, kind=older_kind, genre="article", source_ref="fixture://old", feedback_reason="合成反馈")
            STORE.capture_sample(self.store, old)
            for index in range(6):
                text = f"合成新表达{index}"
                newer = self.sample(account_id=account, kind=newer_kind, text=text, source_ref=f"fixture://new/{index}", feedback_reason="合成反馈")
                newer["confirmation"]["text_sha256"] = STORE.text_sha256(text)
                STORE.capture_sample(self.store, newer)
            selected = STORE.query_samples(self.store, account, "moments", True)["samples"]
            self.assertEqual(5, len(selected))
            self.assertEqual({"positive", "negative"}, {r["payload"]["kind"] for r in selected})
            self.assertEqual("same_genre_expression", selected[0]["usage_scope"])
            self.assertEqual("style_only_cross_genre", selected[-1]["usage_scope"])
            self.assertEqual(older_kind, selected[-1]["payload"]["kind"])
            single = STORE.query_samples(self.store, account, "moments", True, 1)["samples"]
            self.assertEqual(1, len(single))
            self.assertEqual(newer_kind, single[0]["payload"]["kind"])

    def test_brief_is_immutable_idempotent_and_preserves_original_judgment(self):
        record = STORE.create_brief(self.store, self.brief())
        self.assertEqual(record, STORE.create_brief(self.store, self.brief()))
        self.assertEqual("我反对这种做法。", record["judgments"][0]["original_text"])
        changed = self.brief()
        changed["judgments"][0]["stance"] = "支持"
        self.assert_code("brief_immutable", STORE.create_brief, self.store, changed)
        for field, replacement in (("account_id", "different-author"), ("genre", "article"), ("synthetic_only", False)):
            changed = self.brief()
            changed[field] = replacement
            self.assert_code("brief_immutable", STORE.create_brief, self.store, changed)

    def test_concurrent_writers_do_not_duplicate_or_split_brief_scope(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            records = list(pool.map(lambda _: STORE.capture_sample(self.store, self.sample()), range(4)))
        self.assertEqual(1, len({r["record_id"] for r in records}))
        self.assertEqual(1, STORE.store_status(self.store)["counts"]["sample"])
        def create(account):
            try:
                return STORE.create_brief(self.store, self.brief(account_id=account))["status"]
            except STORE.AuthorExpressionError as error:
                return error.code
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(create, ["author-one", "author-two"]))
        self.assertCountEqual(["locked", "brief_immutable"], outcomes)
        self.assertEqual(1, STORE.store_status(self.store)["counts"]["brief"])

    def test_changed_judgment_stays_pending_and_risk_notes_are_separate(self):
        brief = STORE.create_brief(self.store, self.brief())
        value = self.revision(brief, risk_notes=[{"judgment_id": "j1", "category": "style", "note": "合成建议语气更柔和", "source_ref": "fixture://risk"}])
        record = STORE.record_revision(self.store, value)
        self.assertEqual("needs_author_confirmation", record["status"])
        self.assertEqual("needs_author_confirmation", record["judgment_checks"][0]["status"])
        self.assertIn("-我反对这种做法。", record["diff"])
        self.assertIn("+这种做法值得讨论。", record["diff"])
        self.assertEqual(value["after"], record["payload"]["after"])
        self.assertFalse(record["risk_notes_applied_to_text"])
        self.assertEqual(0, STORE.store_status(self.store)["counts"]["sample"])

    def test_preserved_quote_still_requires_semantic_author_review(self):
        brief = STORE.create_brief(self.store, self.brief())
        record = STORE.record_revision(self.store, self.revision(brief, after="我反对这种做法。但是这是我过去的想法。"))
        self.assertEqual("exact_quote_present_review_required", record["judgment_checks"][0]["status"])
        self.assertEqual("needs_author_confirmation", record["status"])
        self.assertEqual("unverified", record["judgment_checks"][0]["semantic_fidelity"])

    def test_revision_chain_and_retry_are_transactional(self):
        brief = STORE.create_brief(self.store, self.brief())
        one = STORE.record_revision(self.store, self.revision(brief))
        two = STORE.record_revision(self.store, self.revision(brief, before=one["payload"]["after"], after="第二版合成稿。"))
        self.assertEqual(one, STORE.record_revision(self.store, self.revision(brief)))
        self.assertEqual(one["record_id"], two["previous_revision_id"])
        self.assert_code("revision_chain_mismatch", STORE.record_revision, self.store, self.revision(brief, after="跳过第二版。"))
        self.assertEqual(2, STORE.store_status(self.store)["counts"]["revision"])

    def test_review_requires_exact_hash_full_decisions_and_right_actor(self):
        brief = STORE.create_brief(self.store, self.brief())
        revision = STORE.record_revision(self.store, self.revision(brief))
        self.assert_code("revision_hash_mismatch", STORE.review_revision, self.store, self.review(revision, revision_sha256="0" * 64))
        self.assert_code("author_confirmation_required", STORE.review_revision, self.store, self.review(revision, actor="assistant"))
        self.assert_code("judgment_decisions_incomplete", STORE.review_revision, self.store, self.review(revision, decisions=[]))
        value = self.review(revision)
        value["decisions"][0]["decision"] = "reject"
        self.assert_code("invalid_choice", STORE.review_revision, self.store, value)
        approved = STORE.review_revision(self.store, self.review(revision))
        self.assertEqual("synthetic_confirmed", approved["status"])
        self.assertFalse(approved["identity_verified"])

    def test_old_review_cannot_approve_next_revision(self):
        brief = STORE.create_brief(self.store, self.brief())
        one = STORE.record_revision(self.store, self.revision(brief))
        STORE.review_revision(self.store, self.review(one))
        self.assertEqual("synthetic_confirmed", STORE.store_status(self.store, brief["content_id"])["status"])
        STORE.record_revision(self.store, self.revision(brief, before=one["payload"]["after"], after="新的合成改稿。"))
        status = STORE.store_status(self.store, brief["content_id"])
        self.assertEqual("needs_author_confirmation", status["status"])
        self.assertIsNone(status["current_review"])

    def test_declared_author_reason_does_not_get_invented_from_ai_reason(self):
        brief = STORE.create_brief(self.store, self.brief())
        value = self.revision(brief)
        record = STORE.record_revision(self.store, value)
        self.assertEqual("assistant", record["payload"]["reasons"][0]["actor"])
        self.assert_code("revision_reason_required", STORE.record_revision, self.store, self.revision(brief, reasons=[]))

    def test_no_judgment_requires_explicit_empty_list_and_review(self):
        brief = STORE.create_brief(self.store, self.brief(judgments=[]))
        revision = STORE.record_revision(self.store, self.revision(brief))
        review = STORE.review_revision(self.store, self.review(revision, decisions=[]))
        self.assertEqual("synthetic_confirmed", review["status"])

    def test_strict_shape_privacy_and_repository_path(self):
        bad = self.sample()
        bad["publish"] = True
        self.assert_code("invalid_shape", STORE.capture_sample, self.store, bad)
        self.assert_code("invalid_choice", STORE.capture_sample, self.store, self.sample(privacy_status="sensitive"))
        self.assert_code("store_outside_repository", STORE.query_samples, ROOT.parent / "outside.sqlite3", "a", "g")
        self.assert_code("invalid_boolean", STORE.query_samples, self.store, "a", "g", 0)

    def test_identity_mismatch_in_revision_is_rejected(self):
        brief = STORE.create_brief(self.store, self.brief())
        self.assert_code("brief_identity_mismatch", STORE.record_revision, self.store, self.revision(brief, account_id="other"))
        self.assert_code("brief_identity_mismatch", STORE.record_revision, self.store, self.revision(brief, synthetic_only=False))

    def test_hash_tampering_is_detected(self):
        record = STORE.capture_sample(self.store, self.sample())
        conn = sqlite3.connect(self.store)
        try:
            tampered = copy.deepcopy(record)
            tampered["payload"]["text"] = "tampered"
            conn.execute("UPDATE records SET body=? WHERE record_id=?", (json.dumps(tampered), record["record_id"]))
            conn.commit()
        finally:
            conn.close()
        self.assert_code("record_hash_mismatch", STORE.query_samples, self.store, "fictional-author", "moments", True)

    def test_does_not_attach_tables_to_an_unrelated_existing_database(self):
        conn = sqlite3.connect(self.store)
        try:
            conn.execute("CREATE TABLE unrelated(data TEXT)")
            conn.commit()
        finally:
            conn.close()
        self.assert_code("store_version_unsupported", STORE.capture_sample, self.store, self.sample())
        conn = sqlite3.connect(self.store)
        try:
            self.assertEqual([("unrelated",)], conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall())
        finally:
            conn.close()

    def test_corrupt_record_returns_structured_error_without_traceback(self):
        sample = STORE.capture_sample(self.store, self.sample())
        conn = sqlite3.connect(self.store)
        try:
            conn.execute("UPDATE records SET body='[]' WHERE record_id=?", (sample["record_id"],))
            conn.commit()
        finally:
            conn.close()
        script = str(ROOT / "scripts" / "author_expression_store.py")
        result = subprocess.run([sys.executable, script, "status", "--store", str(self.store)], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(2, result.returncode)
        self.assertEqual("record_corrupt", json.loads(result.stderr)["error"])
        self.assertNotIn("Traceback", result.stderr)

    def test_cli_cross_process_persistence(self):
        payload = self.directory / "sample.json"
        payload.write_text(json.dumps(self.sample(), ensure_ascii=False), encoding="utf-8")
        script = str(ROOT / "scripts" / "author_expression_store.py")
        added = subprocess.run([sys.executable, script, "sample", "--store", str(self.store), "--input", str(payload)], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(0, added.returncode, added.stderr)
        recalled = subprocess.run([sys.executable, script, "--store", str(self.store), "recall", "--account-id", "fictional-author", "--genre", "moments", "--synthetic-only"], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(0, recalled.returncode, recalled.stderr)
        self.assertEqual(1, json.loads(recalled.stdout)["count"])


if __name__ == "__main__":
    unittest.main()
