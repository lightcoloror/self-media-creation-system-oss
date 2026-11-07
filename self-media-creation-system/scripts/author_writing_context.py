#!/usr/bin/env python3
"""Bind the author expression store to existing drafting and human-review steps.

Text equality is evidence, not a semantic judgment. The existing human voice
review records all judgment decisions; this adapter never silently softens prose.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))
import author_expression_store as store_api

WRITING_STEPS = {
    "draft-one-observation", "build-evidence-draft", "project-case-script",
    "draft-prerecord-case", "draft-interview-guide", "complete-human-voice-gate",
    "complete-prerecord-voice",
}
REVIEW_STEPS = {
    "confirm-author-voice", "approve-exact-package", "complete-human-voice-gate",
    "complete-prerecord-voice", "review-interview-guide",
}
BODY_INPUTS = {
    "confirm-author-voice": "moments-candidate",
    "approve-exact-package": "frozen-body",
    "review-interview-guide": "interview-guide",
}
CONTEXT_VERSION = "author-writing-context.v1"
REVISION_VERSION = "author-writing-revision.v1"


class AuthorWritingError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def fail(code, message):
    raise AuthorWritingError(code, message)


def bounded(path):
    path = Path(path)
    result = (path if path.is_absolute() else ROOT / path).resolve()
    if not result.is_relative_to(ROOT.resolve()) or result == ROOT.resolve():
        fail("author_path_outside_repository", str(path))
    return result


def load(path):
    value = json.loads(bounded(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        fail("author_artifact_invalid", "JSON object required")
    return value


def file_sha(path):
    return hashlib.sha256(bounded(path).read_bytes()).hexdigest()


def sign(value):
    value = copy.deepcopy(value)
    value.pop("payload_sha256", None)
    value["payload_sha256"] = store_api.canonical_sha256(value)
    return value


def check_signed(value, version):
    unsigned = dict(value)
    digest = unsigned.pop("payload_sha256", None)
    if value.get("schema_version") != version or digest != store_api.canonical_sha256(unsigned):
        fail("author_artifact_hash_drift", version)
    if value.get("publication_authorized") is not False or type(value.get("synthetic_only")) is not bool:
        fail("author_boundary_drift", "classification and publication boundary required")


def ref(path):
    target = bounded(path)
    return {"path": target.relative_to(ROOT).as_posix(), "sha256": file_sha(target)}


def checked_ref(value):
    if set(value) != {"path", "sha256"} or Path(value["path"]).is_absolute():
        fail("author_reference_invalid", "repository-relative path and hash required")
    target = bounded(value["path"])
    if file_sha(target) != value["sha256"]:
        fail("author_source_hash_drift", value["path"])
    return target


def write_exact(path, value):
    target = bounded(path)
    data = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if target.read_bytes() != data:
            fail("author_output_exists", "choose a new artifact path for a new version")
    else:
        with target.open("xb") as handle:
            handle.write(data)


def record_ref(record):
    return {"record_id": record["record_id"], "record_sha256": record["record_sha256"]}


def checked_record(store, value, record_type):
    record = store_api.get_record(store, value["record_id"])
    if record["record_type"] != record_type or record["record_sha256"] != value["record_sha256"]:
        fail("author_record_drift", record_type)
    return record


def prepare_context(store, brief_payload, request_id):
    store_api.string(request_id, "request_id", 100)
    store = store_api.store_path(store)
    brief = store_api.create_brief(store, brief_payload)
    recall = store_api.query_samples(store, brief["account_id"], brief["genre"], brief["synthetic_only"])
    return sign({
        "schema_version": CONTEXT_VERSION, "request_id": request_id,
        "store_path": store.relative_to(ROOT).as_posix(),
        "brief_ref": record_ref(brief), "author_brief": brief["payload"],
        "recall": recall, "synthetic_only": brief["synthetic_only"],
        "policy": "Preserve original judgment. Keep risk advice separate. Only exact author-confirmed fragments are samples; cross-genre samples guide style only. Never invent author feedback.",
        "publication_authorized": False,
    })


def validate_context(path, request_id=None, synthetic_only=None):
    context = load(path)
    check_signed(context, CONTEXT_VERSION)
    if request_id is not None and context["request_id"] != request_id:
        fail("author_request_mismatch", "context belongs to another request")
    if synthetic_only is not None and context["synthetic_only"] is not synthetic_only:
        fail("author_classification_mismatch", "synthetic evidence cannot substitute for real author evidence")
    store = store_api.store_path(context["store_path"])
    brief = checked_record(store, context["brief_ref"], "brief")
    if brief["payload"] != context["author_brief"] or brief["synthetic_only"] is not context["synthetic_only"]:
        fail("author_brief_mismatch", "original judgment was changed")
    recall = context["recall"]
    if any(recall.get(k) != brief[k] for k in ("account_id", "genre", "synthetic_only")):
        fail("author_recall_mismatch", "sample context identity drifted")
    samples = recall["samples"]
    if len(samples) > 5 or len({s["record_id"] for s in samples}) != len(samples):
        fail("author_recall_mismatch", "sample selection must be bounded and unique")
    store_api.validate_sample_selection(store, [s["record_id"] for s in samples], brief["account_id"], brief["synthetic_only"])
    for selected in samples:
        sample = checked_record(store, record_ref(selected), "sample")
        expected = dict(sample, usage_scope="same_genre_expression" if sample["genre"] == brief["genre"] else "style_only_cross_genre")
        if selected != expected:
            fail("author_recall_mismatch", "selected fragment or usage scope changed")
    return context


def draft_text(path, _seen=None):
    """Project supported drafts deterministically; reject unknown JSON bodies."""
    path = bounded(path)
    seen = set(_seen or ())
    if path in seen:
        fail("author_body_reference_cycle", str(path))
    seen.add(path)
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() != ".json":
        return text
    value = json.loads(text)
    if not isinstance(value, dict):
        fail("author_draft_shape_unknown", "draft JSON must be an object")
    if value.get("schema_version") == "case-video-script.v1":
        return "\n".join(row["spoken_text"] for row in value["segments"])
    if value.get("schema_version") == "case-interview-guide.v1":
        return "\n".join([value["purpose"], *[line for row in value["questions"] for line in [row["question"], *row["follow_ups"]]]])
    if value.get("schema_version") == "0.2" and "composition" in value:
        def body_of(row, field, reference):
            if isinstance(row.get(field), str) and row[field]:
                return row[field]
            if isinstance(row.get(reference), str) and row[reference]:
                relative = Path(row[reference])
                target = (path.parent / relative).resolve()
                if relative.is_absolute() or not target.is_relative_to(path.parent):
                    fail("author_body_reference_escape", reference)
                return draft_text(target, seen)
            return ""
        body = body_of(value["composition"], "canonical_body", "canonical_body_ref")
        parts = [body] if body else []
        for channel, variant in sorted(value.get("channels", {}).items()):
            channel_body = body_of(variant, "body", "body_ref")
            if channel_body:
                parts.append("\n".join([f"[{channel}]", *[variant[k] for k in ("title", "hook") if variant.get(k)], channel_body, variant.get("cta", "")]).rstrip())
        if not parts:
            fail("author_full_body_required", "summary-only content cannot stand in for a full draft")
        return "\n\n".join(parts)
    for field in ("body", "text", "markdown", "body_markdown"):
        if isinstance(value.get(field), str):
            return value[field]
    fail("author_draft_shape_unknown", "export the complete author-visible body to a UTF-8 .md file and bind that file")


def revision_envelope(store, context_path, draft_path, payload):
    context = validate_context(context_path)
    store = store_api.store_path(store)
    if store != store_api.store_path(context["store_path"]):
        fail("author_store_mismatch", "revision must use the context store")
    brief = context["author_brief"]
    value = copy.deepcopy(payload)
    after = draft_text(draft_path)
    for field, expected in {"brief_id": context["brief_ref"]["record_id"], "content_id": brief["content_id"], "after": after}.items():
        if field in value and value[field] != expected:
            fail("author_revision_input_mismatch", field)
        value[field] = expected
    revision = store_api.record_revision(store, value)
    return sign({
        "schema_version": REVISION_VERSION, "request_id": context["request_id"],
        "synthetic_only": context["synthetic_only"], "context_ref": ref(context_path),
        "draft_ref": ref(draft_path), "revision_ref": record_ref(revision),
        "review_ref": None, "publication_authorized": False,
    })


def validate_revision(path, require_review=False, require_current=True):
    envelope = load(path)
    check_signed(envelope, REVISION_VERSION)
    context = validate_context(checked_ref(envelope["context_ref"]), envelope["request_id"], envelope["synthetic_only"])
    store = store_api.store_path(context["store_path"])
    revision = checked_record(store, envelope["revision_ref"], "revision")
    if revision["brief_id"] != context["brief_ref"]["record_id"] or revision["synthetic_only"] is not context["synthetic_only"]:
        fail("author_revision_brief_mismatch", "revision changed author scope")
    draft = checked_ref(envelope["draft_ref"])
    if revision["payload"]["after"] != draft_text(draft):
        fail("author_revision_body_mismatch", "recorded revision is not the actual draft")
    if require_review and envelope.get("review_ref") is None:
        fail("author_review_required", "record the author's decisions on this exact revision")
    if require_review and require_current:
        current = store_api.store_status(store, revision["content_id"]).get("current_revision")
        if not current or current["record_id"] != revision["record_id"]:
            fail("author_revision_stale", "a newer revision requires its own author decision")
    if envelope.get("review_ref") is not None:
        review = checked_record(store, envelope["review_ref"], "review")
        if review["revision_id"] != revision["record_id"] or review["payload"]["revision_sha256"] != revision["record_sha256"]:
            fail("author_review_stale", "review belongs to another revision")
    return envelope


def attach_review(store, envelope_path, review_payload):
    envelope = validate_revision(envelope_path)
    context = validate_context(checked_ref(envelope["context_ref"]))
    if store_api.store_path(store) != store_api.store_path(context["store_path"]):
        fail("author_store_mismatch", "review must use the context store")
    expected = {"revision_id": envelope["revision_ref"]["record_id"], "revision_sha256": envelope["revision_ref"]["record_sha256"]}
    value = copy.deepcopy(review_payload)
    for key, val in expected.items():
        if key in value and value[key] != val:
            fail("author_review_stale", key)
        value[key] = val
    review = store_api.review_revision(store, value)
    envelope["review_ref"] = record_ref(review)
    return sign(envelope)


def manifest_inputs(manifest_path):
    manifest = load(manifest_path)
    result = {}
    for row in manifest["artifacts"]:
        role = row.get("source_role")
        if role in result:
            fail("author_duplicate_role", str(role))
        target = (bounded(manifest_path).parent / row["path"]).resolve()
        if not target.is_relative_to(bounded(manifest_path).parent):
            fail("author_path_outside_manifest", role)
        result[role] = (target, row)
    return result


def validate_context_manifest(manifest_path, capsule, step, historical=False):
    step_id = step["step_id"]
    if step_id not in WRITING_STEPS | REVIEW_STEPS:
        return
    inputs = manifest_inputs(manifest_path)
    for role in ["author-writing-context"] + (["author-revision-review"] if step_id in REVIEW_STEPS else []):
        if role not in inputs:
            fail("author_context_missing", role)
        path, row = inputs[role]
        if row.get("expected_sha256") != file_sha(path) or row.get("load_mode") == "on_failure":
            fail("author_context_unbound", role)
    context_path = inputs["author-writing-context"][0]
    context = validate_context(context_path, capsule["request_id"], capsule["provenance"]["synthetic_only"])
    import editorial_integrity
    editorial_integrity.require_preflight(context_path)
    identity = capsule["provenance"].get("author_identity")
    if not isinstance(identity, dict) or set(identity) != {"account_id", "genre"}:
        fail("author_identity_missing", "the creation request must declare its author account and genre")
    if any(identity[key] != context["author_brief"][key] for key in identity):
        fail("author_identity_mismatch", "author context belongs to a different account or genre")
    # Free-text profiles are style references. When the existing account artifact
    # declares a machine account_id, it must agree too; do not infer IDs from prose.
    if "account_ip" in inputs and inputs["account_ip"][0].suffix.lower() == ".json":
        account = load(inputs["account_ip"][0])
        if "account_id" in account and account["account_id"] != identity["account_id"]:
            fail("author_account_profile_mismatch", "request and account profile identify different accounts")
    if step_id in REVIEW_STEPS:
        reviewed = validate_revision(inputs["author-revision-review"][0], True, require_current=not historical)
        if reviewed["context_ref"] != ref(context_path):
            fail("author_review_context_mismatch", "review and drafting context differ")
        body_role = BODY_INPUTS.get(step_id)
        if body_role and (body_role not in inputs or draft_text(inputs[body_role][0]) != draft_text(checked_ref(reviewed["draft_ref"]))):
            fail("author_review_body_mismatch", "human gate must consume the reviewed body")


def validate_output_artifacts(handoff_path, receipt_path, handoff, receipt, capsule, historical=False):
    step_id = handoff["step"]["step_id"]
    if step_id not in WRITING_STEPS | REVIEW_STEPS:
        return
    manifest_path = (bounded(handoff_path).parent / handoff["context"]["manifest"]["path"]).resolve()
    inputs = manifest_inputs(manifest_path)
    if step_id not in WRITING_STEPS:
        import editorial_integrity
        return editorial_integrity.status(inputs["author-revision-review"][0], historical=historical)
    envelopes = []
    output_paths = []
    primary_paths = []
    primary_version = {"draft-one-observation": "moments-candidate.v1", "build-evidence-draft": "0.2", "draft-interview-guide": "case-interview-guide.v1"}.get(step_id, "case-video-script.v1")
    for output_ref in receipt["outputs"]:
        path = (bounded(receipt_path).parent / output_ref["path"]).resolve()
        output_paths.append(path)
        if path.suffix.lower() == ".json":
            value = load(path)
            if value.get("schema_version") == REVISION_VERSION:
                envelopes.append(path)
            elif value.get("schema_version") == primary_version:
                primary_paths.append(path)
    if len(envelopes) != 1:
        fail("author_revision_output_missing", "exactly one persisted revision envelope is required")
    envelope = validate_revision(envelopes[0], step_id in REVIEW_STEPS, require_current=not historical)
    if envelope["context_ref"] != ref(inputs["author-writing-context"][0]):
        fail("author_revision_context_mismatch", "output binds a different author brief")
    if envelope["request_id"] != capsule["request_id"] or envelope["synthetic_only"] is not capsule["provenance"]["synthetic_only"]:
        fail("author_request_mismatch", "output belongs to another request")
    # The draft itself must be one of the actual owner outputs. A sidecar cannot
    # claim success for an unrelated hidden file while the delivered copy differs.
    if not any(file_sha(p) == envelope["draft_ref"]["sha256"] for p in output_paths if p != envelopes[0]):
        fail("author_revision_not_delivered", "include the exact draft in receipt.outputs")
    if not primary_paths and step_id == "draft-one-observation":
        primary_paths = [p for p in output_paths if p.suffix.lower() in {".md", ".txt"}]
    if len(primary_paths) != 1 or file_sha(primary_paths[0]) != envelope["draft_ref"]["sha256"]:
        fail("author_primary_draft_mismatch", "revision must bind the one declared primary draft, not an extra sidecar")
    if step_id in REVIEW_STEPS:
        approved = validate_revision(inputs["author-revision-review"][0], True, require_current=not historical)
        if approved["revision_ref"] != envelope["revision_ref"] or approved["review_ref"] != envelope["review_ref"]:
            fail("author_review_stale", "output differs from the author-reviewed revision")
    import editorial_integrity
    return editorial_integrity.status(envelopes[0], historical=historical)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("prepare", "revision", "review"):
        cmd = commands.add_parser(name)
        cmd.add_argument("--store", type=Path, default=store_api.DEFAULT_STORE)
        cmd.add_argument("--input", type=Path, required=True)
        cmd.add_argument("--output", type=Path, required=True)
        if name == "prepare":
            cmd.add_argument("--request-id", required=True)
        elif name == "revision":
            cmd.add_argument("--context", type=Path, required=True)
            cmd.add_argument("--draft", type=Path, required=True)
        else:
            cmd.add_argument("--revision", type=Path, required=True)
    check = commands.add_parser("check")
    group = check.add_mutually_exclusive_group(required=True)
    group.add_argument("--context", type=Path)
    group.add_argument("--revision", type=Path)
    check.add_argument("--require-review", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            result = prepare_context(args.store, load(args.input), args.request_id)
        elif args.command == "revision":
            result = revision_envelope(args.store, args.context, args.draft, load(args.input))
        elif args.command == "review":
            result = attach_review(args.store, args.revision, load(args.input))
        else:
            result = validate_context(args.context) if args.context else validate_revision(args.revision, args.require_review)
        if hasattr(args, "output"):
            write_exact(args.output, result)
        print(json.dumps({"status": "passed", "schema_version": result["schema_version"], "output": str(getattr(args, "output", "")), "publication_authorized": False}, ensure_ascii=False))
        return 0
    except (ValueError, KeyError, TypeError, OSError, sqlite3.Error) as error:
        print(json.dumps({"status": "blocked", "code": getattr(error, "code", "author_artifact_invalid"), "message": str(error)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
