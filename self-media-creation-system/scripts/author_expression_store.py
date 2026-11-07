#!/usr/bin/env python3
"""Local author expression evidence, immutable briefs and append-only revisions.

This store verifies explicit record bindings, not the identity of a human or the
semantic fidelity of prose. Only an explicit, exact-fragment author declaration
makes a real sample retrievable. Revisions never become samples automatically.
No network, model, knowledge-base, publication or source-file writes occur here.
"""
from __future__ import annotations

import argparse
import copy
import difflib
import hashlib
import json
import sqlite3
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STORE = ROOT / ".runtime" / "author-expression" / "store.sqlite3"
VERSION = "author-expression-record.v1"
APPLICATION_ID = 0x41584531  # AXE1; do not attach these tables to an unrelated database.
PRIVACY = {"non_sensitive", "deidentified"}
ACTORS = {"author", "assistant", "synthetic_fixture"}
LIMITATION = "Records verify declarations and exact text bindings; they do not authenticate a human or prove semantic fidelity."


class AuthorExpressionError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def fail(code: str, message: str) -> None:
    raise AuthorExpressionError(code, message)


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def text_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def shape(value: Any, required: set[str], optional: set[str] | None = None, label: str = "input") -> None:
    if not isinstance(value, dict) or not required <= value.keys() or set(value) - required - (optional or set()):
        fail("invalid_shape", f"{label}: required={sorted(required)}, optional={sorted(optional or set())}")


def string(value: Any, label: str, maximum: int = 10000, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or len(value) > maximum or (not allow_empty and not value.strip()) or "\x00" in value:
        fail("invalid_text", label)
    return value


def choice(value: Any, allowed: set[str], label: str) -> None:
    if not isinstance(value, str) or value not in allowed:
        fail("invalid_choice", f"{label}: {sorted(allowed)}")


def boolean(value: Any, label: str) -> None:
    if type(value) is not bool:
        fail("invalid_boolean", label)


def sha(value: Any, label: str) -> None:
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        fail("invalid_sha256", label)


def identity(payload: dict[str, Any]) -> None:
    for field in ("account_id", "genre", "source_ref"):
        string(payload[field], field, 1000)
    boolean(payload["synthetic_only"], "synthetic_only")
    choice(payload["privacy_status"], PRIVACY, "privacy_status")


def author_actor(actor: str, synthetic: bool) -> None:
    expected = "synthetic_fixture" if synthetic else "author"
    if actor != expected:
        fail("author_confirmation_required", f"expected {expected}; assistant declarations cannot confirm author intent")


def store_path(store: Path) -> Path:
    raw = Path(store)
    path = (raw if raw.is_absolute() else ROOT / raw).resolve()
    if not path.is_relative_to(ROOT.resolve()) or path == ROOT.resolve():
        fail("store_outside_repository", "store must resolve inside self-media-creation-system")
    if path.suffix not in {".sqlite3", ".sqlite", ".db"}:
        fail("store_extension_invalid", "use a local .sqlite3, .sqlite or .db file")
    return path


@contextmanager
def database(store: Path, write: bool = False) -> Iterator[sqlite3.Connection | None]:
    path = store_path(store)
    if not path.exists() and not write:
        yield None
        return
    if write:
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path) if write else path.as_uri() + "?mode=ro", uri=not write, timeout=15)
    conn.row_factory = sqlite3.Row
    try:
        if write:
            conn.execute("BEGIN IMMEDIATE")
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            application_id = conn.execute("PRAGMA application_id").fetchone()[0]
            tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            if not (version == 0 and application_id == 0 and not tables) and (version != 1 or application_id != APPLICATION_ID):
                fail("store_version_unsupported", "not an author-expression v1 store")
            conn.execute("CREATE TABLE IF NOT EXISTS records (seq INTEGER PRIMARY KEY AUTOINCREMENT, record_id TEXT NOT NULL UNIQUE, record_type TEXT NOT NULL, content_id TEXT, body TEXT NOT NULL)")
            conn.execute("CREATE INDEX IF NOT EXISTS records_content ON records(content_id, seq)")
            conn.execute("PRAGMA user_version=1")
            conn.execute(f"PRAGMA application_id={APPLICATION_ID}")
        elif conn.execute("PRAGMA user_version").fetchone()[0] != 1 or conn.execute("PRAGMA application_id").fetchone()[0] != APPLICATION_ID:
            fail("store_version_unsupported", "not an author-expression v1 store")
        yield conn
        if write:
            conn.commit()
    except Exception:
        if write:
            conn.rollback()
        raise
    finally:
        conn.close()


def decode(row: sqlite3.Row) -> dict[str, Any]:
    try:
        record = json.loads(row["body"])
    except (json.JSONDecodeError, TypeError, RecursionError) as error:
        fail("record_corrupt", f"invalid stored JSON: {type(error).__name__}")
    if not isinstance(record, dict) or not {"record_id", "record_type", "record_sha256", "payload"} <= record.keys() or not isinstance(record["payload"], dict):
        fail("record_corrupt", "stored record is not an author-expression object")
    expected = record.pop("record_sha256", None)
    try:
        actual = canonical_sha256(record)
    except (TypeError, ValueError, RecursionError):
        fail("record_corrupt", "stored record cannot be represented canonically")
    if actual != expected:
        fail("record_hash_mismatch", row["record_id"])
    record["record_sha256"] = expected
    if record["record_id"] != row["record_id"] or record["record_type"] != row["record_type"] or record.get("content_id") != row["content_id"]:
        fail("record_index_mismatch", row["record_id"])
    return record


def rows(conn: sqlite3.Connection | None, content_id: str | None = None) -> list[dict[str, Any]]:
    if conn is None:
        return []
    cursor = conn.execute("SELECT * FROM records ORDER BY seq") if content_id is None else conn.execute("SELECT * FROM records WHERE content_id=? ORDER BY seq", (content_id,))
    return [decode(row) for row in cursor]


def fetch(conn: sqlite3.Connection | None, record_id: str, record_type: str | None = None) -> dict[str, Any]:
    string(record_id, "record_id", 100)
    row = conn.execute("SELECT * FROM records WHERE record_id=?", (record_id,)).fetchone() if conn else None
    if row is None:
        fail("record_missing", record_id)
    record = decode(row)
    if record_type and record["record_type"] != record_type:
        fail("record_type_mismatch", f"{record_id}: expected {record_type}")
    return record


def append(conn: sqlite3.Connection, record_type: str, payload: dict[str, Any], derived: dict[str, Any]) -> dict[str, Any]:
    record_id = record_type + "-" + canonical_sha256(payload)
    prior = conn.execute("SELECT * FROM records WHERE record_id=?", (record_id,)).fetchone()
    if prior:
        record = decode(prior)
        if record["payload"] != payload:
            fail("record_id_collision", record_id)
        return record
    record = {"schema_version": VERSION, "record_id": record_id, "record_type": record_type,
              "recorded_at": datetime.now(timezone.utc).isoformat(), "payload": copy.deepcopy(payload),
              "limitation": LIMITATION, "publish_authorized": False, **derived}
    for name in ("account_id", "genre", "content_id", "synthetic_only"):
        if name in payload:
            record[name] = payload[name]
    record[record_type + "_id"] = record_id
    record["record_sha256"] = canonical_sha256(record)
    conn.execute("INSERT INTO records(record_id,record_type,content_id,body) VALUES (?,?,?,?)", (record_id, record_type, record.get("content_id"), canonical_bytes(record).decode("utf-8")))
    return record


def get_record(store: Path, record_id: str) -> dict[str, Any]:
    with database(store) as conn:
        return fetch(conn, record_id)


def capture_sample(store: Path, payload: dict[str, Any]) -> dict[str, Any]:
    shape(payload, {"account_id", "genre", "text", "kind", "source_ref", "source_kind", "synthetic_only", "privacy_status", "confirmation"}, {"feedback_reason"})
    identity(payload)
    string(payload["text"], "text", 4000)
    choice(payload["kind"], {"positive", "negative"}, "kind")
    choice(payload["source_kind"], {"author_original", "author_revision", "ai_draft"}, "source_kind")
    if payload["kind"] == "negative":
        string(payload.get("feedback_reason"), "negative samples require feedback_reason")
    elif "feedback_reason" in payload:
        string(payload["feedback_reason"], "feedback_reason")
    confirmation = payload["confirmation"]
    shape(confirmation, {"status", "actor", "source_ref"}, {"scope", "text_sha256"}, "confirmation")
    choice(confirmation["status"], {"candidate", "confirmed"}, "confirmation.status")
    choice(confirmation["actor"], ACTORS, "confirmation.actor")
    string(confirmation["source_ref"], "confirmation.source_ref", 1000)
    if confirmation["status"] == "confirmed":
        author_actor(confirmation["actor"], payload["synthetic_only"])
        if confirmation.get("scope") != "exact_fragment" or confirmation.get("text_sha256") != text_sha256(payload["text"]):
            fail("confirmation_fragment_mismatch", "confirmation must bind only this exact text fragment")
    else:
        if "scope" in confirmation:
            choice(confirmation["scope"], {"exact_fragment"}, "confirmation.scope")
        if "text_sha256" in confirmation and confirmation["text_sha256"] != text_sha256(payload["text"]):
            fail("confirmation_fragment_mismatch", "candidate text hash differs")
    with database(store, True) as conn:
        return append(conn, "sample", payload, {"status": confirmation["status"], "text_sha256": text_sha256(payload["text"]), "scope": "exact_fragment"})


def query_samples(store: Path, account_id: str, genre: str, synthetic_only: bool = False, limit: int = 5) -> dict[str, Any]:
    string(account_id, "account_id", 1000)
    string(genre, "genre", 1000)
    boolean(synthetic_only, "synthetic_only")
    if type(limit) is not int or not 1 <= limit <= 100:
        fail("invalid_limit", "limit must be 1..100")
    with database(store) as conn:
        records = rows(conn)
    retracted = {r["payload"]["sample_id"] for r in records if r["record_type"] == "retraction"}
    selected = [r for r in records if r["record_type"] == "sample" and r["status"] == "confirmed" and r["account_id"] == account_id and r["synthetic_only"] is synthetic_only and r["record_id"] not in retracted]
    # Latest evidence first within a genre; cross-genre records carry no structure authority.
    selected.reverse()
    selected.sort(key=lambda r: r["genre"] != genre)
    eligible = []
    seen: set[tuple[str, str, str]] = set()
    for record in selected:
        key = (record["text_sha256"], record["payload"]["kind"], record["genre"])
        if key in seen:
            continue
        seen.add(key)
        eligible.append(record)
    selected = eligible[:limit]
    # An established "don't write like this" correction must not disappear
    # merely because several newer positive snippets were accepted, or vice versa.
    # Genre/time ranking remains in force within each kind.
    if limit >= 2:
        for kind in ("positive", "negative"):
            if not any(record["payload"]["kind"] == kind for record in selected):
                candidate = next((record for record in eligible if record["payload"]["kind"] == kind), None)
                if candidate:
                    if len(selected) == limit:
                        selected[-1] = candidate
                    else:
                        selected.append(candidate)
    ranks = {record["record_id"]: index for index, record in enumerate(eligible)}
    selected.sort(key=lambda record: ranks[record["record_id"]])
    result = []
    for record in selected:
        item = copy.deepcopy(record)
        item["usage_scope"] = "same_genre_expression" if record["genre"] == genre else "style_only_cross_genre"
        result.append(item)
    return {"status": "ready", "account_id": account_id, "genre": genre, "synthetic_only": synthetic_only, "samples": result, "count": len(result), "limitation": LIMITATION}


def validate_sample_selection(store: Path, sample_ids: list[str], account_id: str, synthetic_only: bool) -> None:
    """Validate a historical selection without requiring it to remain top-N."""
    string(account_id, "account_id", 1000)
    boolean(synthetic_only, "synthetic_only")
    if not isinstance(sample_ids, list) or any(not isinstance(i, str) for i in sample_ids) or len(set(sample_ids)) != len(sample_ids):
        fail("invalid_sample_selection", "sample_ids must be a unique string list")
    with database(store) as conn:
        retracted = {r["payload"]["sample_id"] for r in rows(conn) if r["record_type"] == "retraction"}
        for sample_id in sample_ids:
            sample = fetch(conn, sample_id, "sample")
            if sample["status"] != "confirmed" or sample["account_id"] != account_id or sample["synthetic_only"] is not synthetic_only:
                fail("sample_selection_mismatch", sample_id)
            if sample_id in retracted:
                fail("sample_retracted", sample_id)


def create_brief(store: Path, payload: dict[str, Any]) -> dict[str, Any]:
    shape(payload, {"content_id", "account_id", "genre", "synthetic_only", "privacy_status", "source_ref", "judgments"})
    identity(payload)
    string(payload["content_id"], "content_id", 200)
    if not isinstance(payload["judgments"], list) or len(payload["judgments"]) > 50:
        fail("invalid_judgments", "judgments must be a list of at most 50 supplied positions; [] is allowed")
    ids = []
    for judgment in payload["judgments"]:
        shape(judgment, {"id", "original_text", "target", "stance", "intensity", "basis", "uncertainty"}, label="judgment")
        for key in judgment:
            string(judgment[key], f"judgment.{key}", 10000, key in {"basis", "uncertainty"})
        ids.append(judgment["id"])
    if len(set(ids)) != len(ids):
        fail("duplicate_judgment_id", "judgment ids must be unique")
    with database(store, True) as conn:
        previous = [r for r in rows(conn, payload["content_id"]) if r["record_type"] == "brief"]
        if previous and previous[0]["payload"] != payload:
            fail("brief_immutable", "content_id already has an immutable brief; use a new content_id for a newly authorized brief")
        return append(conn, "brief", payload, {"status": "locked", "judgments": copy.deepcopy(payload["judgments"])})


def record_revision(store: Path, payload: dict[str, Any]) -> dict[str, Any]:
    shape(payload, {"content_id", "brief_id", "before", "after", "reasons", "source_ref", "privacy_status"}, {"risk_notes", "account_id", "genre", "synthetic_only"})
    for key in ("content_id", "brief_id", "source_ref"):
        string(payload[key], key, 1000)
    string(payload["before"], "before", 200000, True)
    string(payload["after"], "after", 200000)
    choice(payload["privacy_status"], PRIVACY, "privacy_status")
    if not isinstance(payload["reasons"], list) or not 1 <= len(payload["reasons"]) <= 100:
        fail("revision_reason_required", "record supplied reasons with their actual actor; do not invent author explanations")
    for reason in payload["reasons"]:
        shape(reason, {"text", "actor", "source_ref"}, label="reason")
        string(reason["text"], "reason.text")
        choice(reason["actor"], ACTORS, "reason.actor")
        string(reason["source_ref"], "reason.source_ref", 1000)
    notes = payload.get("risk_notes", [])
    if not isinstance(notes, list) or len(notes) > 100:
        fail("invalid_risk_notes", "risk_notes must be a list")
    for note in notes:
        shape(note, {"judgment_id", "category", "note", "source_ref"}, label="risk_note")
        for key in note:
            string(note[key], f"risk_note.{key}")
        choice(note["category"], {"fact_uncertainty", "privacy", "legal", "safety", "style", "other"}, "risk_note.category")
    with database(store, True) as conn:
        brief = fetch(conn, payload["brief_id"], "brief")
        if brief["content_id"] != payload["content_id"]:
            fail("brief_content_mismatch", "revision content_id differs from brief")
        for key in ("account_id", "genre", "synthetic_only"):
            if key in payload and (type(payload[key]) is not type(brief[key]) or payload[key] != brief[key]):
                fail("brief_identity_mismatch", key)
        expected_actor = "synthetic_fixture" if brief["synthetic_only"] else "author"
        for reason in payload["reasons"]:
            if reason["actor"] not in {"assistant", expected_actor}:
                fail("reason_identity_mismatch", "real and synthetic author reasons cannot mix")
        judgment_ids = {j["id"] for j in brief["judgments"]}
        if any(n["judgment_id"] not in judgment_ids for n in notes):
            fail("risk_judgment_missing", "risk notes must reference a recorded judgment")
        revisions = [r for r in rows(conn, payload["content_id"]) if r["record_type"] == "revision"]
        duplicate = next((r for r in revisions if r["payload"] == payload), None)
        if duplicate:
            return duplicate
        if revisions and revisions[-1]["payload"]["after"] != payload["before"]:
            fail("revision_chain_mismatch", "before must equal the previous revision's complete after text")
        checks = []
        for judgment in brief["judgments"]:
            original = judgment["original_text"]
            present = original in payload["after"]
            checks.append({"judgment_id": judgment["id"], "original_text": original,
                           "original_text_sha256": text_sha256(original), "before_quote_present": original in payload["before"],
                           "after_quote_present": present, "status": "exact_quote_present_review_required" if present else "needs_author_confirmation",
                           "semantic_fidelity": "unverified", "target": judgment["target"], "stance": judgment["stance"],
                           "intensity": judgment["intensity"], "basis": judgment["basis"], "uncertainty": judgment["uncertainty"]})
        diff = "\n".join(difflib.unified_diff(payload["before"].splitlines(), payload["after"].splitlines(), fromfile="before", tofile="after", lineterm=""))
        # Text hashes also expose changes such as a trailing newline absent from a line diff.
        derived = {"status": "needs_author_confirmation", "brief_id": brief["record_id"],
                   "account_id": brief["account_id"], "genre": brief["genre"], "synthetic_only": brief["synthetic_only"],
                   "before_sha256": text_sha256(payload["before"]), "after_sha256": text_sha256(payload["after"]),
                   "previous_revision_id": revisions[-1]["record_id"] if revisions else None,
                   "diff": diff, "judgment_checks": checks, "risk_notes": copy.deepcopy(notes),
                   "risk_notes_applied_to_text": False}
        return append(conn, "revision", payload, derived)


def review_revision(store: Path, payload: dict[str, Any]) -> dict[str, Any]:
    shape(payload, {"revision_id", "revision_sha256", "actor", "source_ref", "decisions"})
    string(payload["revision_id"], "revision_id", 100)
    sha(payload["revision_sha256"], "revision_sha256")
    string(payload["source_ref"], "source_ref", 1000)
    if not isinstance(payload["decisions"], list):
        fail("invalid_decisions", "decisions must be a list")
    for decision in payload["decisions"]:
        shape(decision, {"judgment_id", "decision", "reason", "source_ref"}, label="decision")
        for key in decision:
            string(decision[key], f"decision.{key}")
        choice(decision["decision"], {"preserved", "accepted_change"}, "decision.decision")
    with database(store, True) as conn:
        revision = fetch(conn, payload["revision_id"], "revision")
        if revision["record_sha256"] != payload["revision_sha256"]:
            fail("revision_hash_mismatch", "review must bind the exact revision")
        author_actor(payload["actor"], revision["synthetic_only"])
        expected = {j["judgment_id"] for j in revision["judgment_checks"]}
        supplied = [j["judgment_id"] for j in payload["decisions"]]
        if len(set(supplied)) != len(supplied) or set(supplied) != expected:
            fail("judgment_decisions_incomplete", "each original judgment needs one explicit decision")
        # 'preserved' may cover a faithful paraphrase; this remains the author's
        # declaration, never a semantic classifier or proof of a human action.
        status = "synthetic_confirmed" if revision["synthetic_only"] else "author_confirmed"
        return append(conn, "review", payload, {"status": status, "review_status": status,
                      "content_id": revision["content_id"], "account_id": revision["account_id"], "genre": revision["genre"],
                      "synthetic_only": revision["synthetic_only"], "revision_id": revision["record_id"],
                      "after_sha256": revision["after_sha256"], "identity_verified": False, "semantic_fidelity": "author_declared"})


def retract_sample(store: Path, payload: dict[str, Any]) -> dict[str, Any]:
    shape(payload, {"sample_id", "sample_sha256", "actor", "source_ref", "reason"})
    for key in ("sample_id", "source_ref", "reason"):
        string(payload[key], key)
    sha(payload["sample_sha256"], "sample_sha256")
    with database(store, True) as conn:
        sample = fetch(conn, payload["sample_id"], "sample")
        if sample["record_sha256"] != payload["sample_sha256"]:
            fail("sample_hash_mismatch", "retraction must bind the exact sample")
        author_actor(payload["actor"], sample["synthetic_only"])
        return append(conn, "retraction", payload, {"status": "retracted", "account_id": sample["account_id"], "genre": sample["genre"], "synthetic_only": sample["synthetic_only"]})


def store_status(store: Path, content_id: str | None = None) -> dict[str, Any]:
    if content_id is not None:
        string(content_id, "content_id", 200)
    with database(store) as conn:
        records = rows(conn, content_id)
    kinds = {name: sum(r["record_type"] == name for r in records) for name in ("sample", "brief", "revision", "review", "retraction")}
    result: dict[str, Any] = {"status": "ready", "counts": kinds, "content_id": content_id, "limitation": LIMITATION}
    if content_id is not None:
        for name in ("brief", "revision"):
            values = [r for r in records if r["record_type"] == name]
            result["current_" + name] = values[-1] if values else None
        revision = result["current_revision"]
        reviews = [r for r in records if r["record_type"] == "review" and revision and r["revision_id"] == revision["record_id"]]
        result["current_review"] = reviews[-1] if reviews else None
        result["status"] = result["current_review"]["status"] if reviews else "needs_author_confirmation" if revision else "brief_locked" if result["current_brief"] else "empty"
    return result


def load_input(path: Path) -> dict[str, Any]:
    if path.stat().st_size > 2_000_000:
        fail("input_too_large", "JSON input exceeds 2 MB")
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except RecursionError:
        fail("invalid_shape", "JSON input is nested too deeply")
    if not isinstance(value, dict):
        fail("invalid_shape", "JSON input must be an object")
    return value


def main(argv: list[str] | None = None) -> int:
    # Stable UTF-8 JSON on Windows redirected pipes as well as interactive shells.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", type=Path, default=DEFAULT_STORE)
    subs = parser.add_subparsers(dest="command", required=True)
    for name in ("sample", "brief", "revision", "review", "retract"):
        sub = subs.add_parser(name)
        sub.add_argument("--store", type=Path, default=argparse.SUPPRESS)
        sub.add_argument("--input", type=Path, required=True)
    recall = subs.add_parser("recall")
    recall.add_argument("--store", type=Path, default=argparse.SUPPRESS)
    recall.add_argument("--account-id", required=True)
    recall.add_argument("--genre", required=True)
    recall.add_argument("--synthetic-only", action="store_true")
    recall.add_argument("--limit", type=int, default=5)
    status = subs.add_parser("status")
    status.add_argument("--store", type=Path, default=argparse.SUPPRESS)
    status.add_argument("--content-id")
    args = parser.parse_args(argv)
    try:
        if args.command == "recall":
            result = query_samples(args.store, args.account_id, args.genre, args.synthetic_only, args.limit)
        elif args.command == "status":
            result = store_status(args.store, args.content_id)
        else:
            operation = {"sample": capture_sample, "brief": create_brief, "revision": record_revision, "review": review_revision, "retract": retract_sample}[args.command]
            result = operation(args.store, load_input(args.input))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (AuthorExpressionError, OSError, sqlite3.Error, json.JSONDecodeError, UnicodeError) as error:
        print(json.dumps({"status": "error", "error": getattr(error, "code", type(error).__name__), "message": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
