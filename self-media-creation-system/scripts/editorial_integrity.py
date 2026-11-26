"""Version-bound editorial evidence in the EXISTING append-only author store.

Evidence coverage is not editorial truth, human authentication or permission to
publish. This module never calls a model, reads a knowledge base or edits a draft.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path

import author_writing_context as author
import author_expression_store as store

CHECKS = {f"C{i:02}" for i in range(1, 10)}
PRE = {"goal_audience", "materials", "facts", "author_expression", "angle", "promise", "production"}
STATES = {"unchecked", "findings", "revised_verified", "retained", "not_applicable", "missing_input"}
DONE = {"findings", "revised_verified", "retained", "not_applicable"}
ROUTES = {"expository", "story", "travel-experience", "text"}
PHASES = {"draft", "readthrough", "final_media"}
PURPOSE_FIELDS = {"stage_duty", "contribution", "misunderstanding_risk", "tradeoff"}
GENERIC_REASONS = {"pass", "passed", "ok", "通过", "全部通过", "已读skill"}
IMPACT = {
    "wording": {"C01", "C04", "C05", "C06"},
    "structure": {"C03", "C04", "C07", "C08"},
    "claims": {"C02", "C05", "C07", "C09"},
    "promise": {"C01", "C03", "C08"},
    "media": {"C07", "C09"},
    "goal": CHECKS,
}


def fail(code, message):
    author.fail("editorial_" + code, message)


def evidence(ref):
    """A source-bound quote, not a bare path or a generic 'passed' statement."""
    store.shape(ref, {"path", "sha256", "quote"})
    target = author.checked_ref({k: ref[k] for k in ("path", "sha256")})
    store.string(ref["quote"], "evidence.quote")
    if ref["quote"] not in target.read_text(encoding="utf-8"):
        fail("anchor_missing", ref["path"])


def evidence_list(values):
    if not isinstance(values, list) or not values:
        fail("evidence_missing", "at least one hash-bound source quote is required")
    for value in values:
        evidence(value)


def keyed(values, field, allowed=None):
    if not isinstance(values, list):
        fail("invalid_rows", field)
    result = {}
    for row in values:
        if not isinstance(row, dict) or field not in row:
            fail("invalid_rows", field)
        key = store.string(row[field], field)
        if key in result or (allowed is not None and key not in allowed):
            fail("duplicate_or_unknown", key)
        result[key] = row
    return result


def history(context):
    with store.database(store.store_path(context["store_path"])) as conn:
        return store.rows(conn, context["author_brief"]["content_id"])


def latest(records, kind):
    return next((row for row in reversed(records) if row["record_type"] == kind), None)


def story_text_review(context, text, row):
    """Reuse the story card and sentence matcher for articles/Moments/plain text."""
    if not row.get("story_card_ref") or not row.get("story_realization"):
        return False
    root = Path(__file__).resolve().parents[1]
    import prerecording_validation
    module = prerecording_validation._module("initial_draft_quality_gate")
    module.validate_storycraft_binding()
    spec = importlib.util.spec_from_file_location("editorial_story_card", root / "scripts/story_design_gate.py")
    owner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(owner)
    card = author.load(author.checked_ref(row["story_card_ref"]))
    owner.validate_receipt(card)
    if card["content_id"] != context["author_brief"]["content_id"]:
        fail("story_content_drift", "story card belongs to another content item")
    if (card["story_source"]["identity_treatment"] == "synthetic") != context["synthetic_only"]:
        fail("story_classification_drift", "synthetic story design cannot approve real content")
    script = {"content_id": card["content_id"], "segments": [
        {"segment_id": f"text-{i:04}", "spoken_text": line,
         "fact_refs": card["fact_binding"]["allowed_fact_ids"]}
        for i, line in enumerate((line for line in text.splitlines() if line.strip()), 1)]}
    try:
        unresolved = module.narrative_realization.validate(script, row["story_realization"], card,
            hashlib.sha256(text.encode("utf-8")).hexdigest())
    except ValueError as error:
        fail(getattr(error, "code", "story_review_invalid"), str(error))
    return not unresolved


def identity(context):
    return {k: context["author_brief"][k] for k in ("content_id", "account_id", "genre", "synthetic_only")}


def facet_text_review(context, text, row, *, allow_incomplete=False):
    """Verify C04 anchors against bound topic_facets when present."""
    facets = context.get("topic_facets")
    if facets is None:
        return True
    review = row.get("facet_realization")
    if review is None:
        if allow_incomplete:
            return False
        fail("facet_review_missing", "C04 requires facet_realization anchors when topic_facets are bound")
    store.shape(
        review,
        {"angle_id", "dominant_action", "main_element", "supporting_elements", "dominant_action_check"},
        label="facet_realization",
    )
    if review["angle_id"] != facets["angle_id"]:
        fail("facet_angle_drift", "C04 facet_realization angle_id differs from bound topic_facets")
    if review["dominant_action"] != facets["dominant_action"]:
        fail("facet_action_drift", "C04 facet_realization dominant_action differs from bound topic_facets")

    complete = True
    main = review["main_element"]
    store.shape(main, {"element_id", "quote", "assessment"}, label="facet_realization.main_element")
    if main["element_id"] != facets["main_element"]["element_id"]:
        fail("facet_main_element_mismatch", "C04 main_element differs from bound topic_facets")
    main_assessment = store.string(main["assessment"], "facet_realization.main_element.assessment")
    if main_assessment.strip().lower() in GENERIC_REASONS:
        fail("facet_reason_missing", main["element_id"])
    main_quote = store.string(main["quote"], "facet_realization.main_element.quote", allow_empty=allow_incomplete)
    if not main_quote.strip():
        complete = False
    elif main_quote not in text:
        fail("facet_anchor_missing", main["element_id"])

    supporting = review["supporting_elements"]
    if not isinstance(supporting, list):
        fail("facet_supporting_coverage", "supporting_elements must be a list")
    expected = {item["element_id"]: item["relation"] for item in facets["supporting_elements"]}
    allowed_statuses = {"realized", "omitted_with_reason", "missing"} if allow_incomplete else {"realized", "omitted_with_reason"}
    seen_ids = []
    for item in supporting:
        store.shape(
            item,
            {"element_id", "relation", "status", "quote", "assessment"},
            label="facet_realization.supporting_elements",
        )
        eid = store.string(item["element_id"], "facet_realization.supporting_elements.element_id")
        if eid not in expected or eid in seen_ids:
            fail("facet_supporting_coverage", eid)
        seen_ids.append(eid)
        if item["relation"] != expected[eid]:
            fail("facet_supporting_relation_drift", eid)
        store.choice(item["status"], allowed_statuses, "facet_realization.supporting_elements.status")
        assessment = store.string(item["assessment"], f"facet_realization.supporting_elements.{eid}.assessment")
        if assessment.strip().lower() in GENERIC_REASONS:
            fail("facet_reason_missing", eid)
        quote = store.string(
            item["quote"],
            f"facet_realization.supporting_elements.{eid}.quote",
            allow_empty=(item["status"] in {"omitted_with_reason", "missing"} or allow_incomplete),
        )
        if item["status"] == "missing":
            complete = False
            if quote.strip() and quote not in text:
                fail("facet_anchor_missing", eid)
        elif item["status"] == "realized":
            if not quote.strip():
                complete = False
            elif quote not in text:
                fail("facet_anchor_missing", eid)
        elif quote.strip() and quote not in text:
            fail("facet_anchor_missing", eid)
    if set(seen_ids) != set(expected):
        fail("facet_supporting_coverage", ",".join(sorted(set(expected) - set(seen_ids))))

    action_check = review["dominant_action_check"]
    store.shape(action_check, {"quote", "assessment"}, label="facet_realization.dominant_action_check")
    action_assessment = store.string(action_check["assessment"], "facet_realization.dominant_action_check.assessment")
    if action_assessment.strip().lower() in GENERIC_REASONS:
        fail("facet_reason_missing", "dominant_action_check")
    action_quote = store.string(action_check["quote"], "facet_realization.dominant_action_check.quote", allow_empty=allow_incomplete)
    if not action_quote.strip():
        complete = False
    elif action_quote not in text:
        fail("facet_anchor_missing", "dominant_action_check")
    return complete


def preflight(context_path, payload=None, records=None, historical=False):
    context = author.validate_context(context_path)
    records = history(context) if records is None else records
    if payload is None:
        record = latest(records, "editorial_preflight")
        if record is None:
            fail("preflight_missing", "record the seven preparation decisions before writing")
        payload = record["payload"]
        if payload["context_ref"] != author.ref(context_path):
            fail("preflight_stale", "preparation belongs to another context")
        feedback_ids = [r["record_id"] for r in records if r["record_type"] == "editorial_feedback"
                        and "C01" in r["payload"]["check_ids"]]
        if payload.get("goal_feedback_ids", []) != feedback_ids:
            fail("preflight_feedback_pending", "goal/requirements feedback needs an updated preparation assessment")
        data = payload["assessment"]
    else:
        data = payload
    store.shape(data, {"route", "items", "actor", "source"}, {"entry_binding", "fact_card_ref"})
    if "fact_card_ref" in data:
        fref = data["fact_card_ref"]
        if not isinstance(fref, dict) or not isinstance(fref.get("path"), str) or not isinstance(fref.get("sha256"), str):
            fail("fact_card_ref_invalid", "fact_card_ref must provide path and sha256")
        digest = fref["sha256"].strip().lower()
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            fail("fact_card_hash_invalid", "fact_card_ref.sha256 must be a 64-char hex digest")
        target = author.checked_ref(fref)
        check_fact_card(target, expected_sha256=digest, content_id=context["author_brief"]["content_id"])
    if "entry_binding" in data:
        binding = data["entry_binding"]
        if not isinstance(binding, str) or len(binding) != 64 or any(c not in "0123456789abcdef" for c in binding):
            fail("entry_binding_invalid", "expected current selection binding SHA256")
    store.choice(data["route"], ROUTES, "route")
    store.string(data["actor"], "actor")
    evidence(data["source"])
    items = keyed(data["items"], "id", PRE)
    if set(items) != PRE:
        fail("preflight_missing", ",".join(sorted(PRE - set(items))))
    for key, row in items.items():
        store.shape(row, {"id", "state", "reason", "evidence"})
        store.choice(row["state"], {"ready", "not_applicable", "missing_input"}, "preflight.state")
        if not historical and key == "goal_audience" and row["state"] == "not_applicable":
            fail("goal_not_applicable", "the current purpose and audience cannot be marked not applicable")
        store.string(row["reason"], key)
        evidence_list(row["evidence"])
    return context, data


def record_preflight(context_path, payload):
    context, data = preflight(context_path, payload)
    value = {**identity(context), "context_ref": author.ref(context_path), "assessment": data,
             "goal_feedback_ids": [r["record_id"] for r in history(context) if r["record_type"] == "editorial_feedback"
                                   and "C01" in r["payload"]["check_ids"]]}
    with store.database(store.store_path(context["store_path"]), True) as conn:
        return store.append(conn, "editorial_preflight", value, {})


def require_preflight(context_path, *, historical=False):
    context, data = preflight(context_path, historical=historical)
    missing = [r["id"] for r in data["items"] if r["state"] == "missing_input"
               or (r["id"] == "goal_audience" and r["state"] != "ready")]
    if missing:
        fail("preparation_pending", ",".join(missing))
    effective_fc = data.get("fact_card_ref") or context.get("fact_card_ref")
    if not historical and effective_fc is None:
        fail("fact_card_required", "formal drafting requires a locked fact_card_ref in preflight")
    if effective_fc is not None and "fact_card_ref" not in data:
        return {**data, "fact_card_ref": effective_fc}
    return data


def feedback(context_path, payload):
    context = author.validate_context(context_path)
    store.shape(payload, {"feedback_id", "check_ids", "issue_ids", "reason", "source"})
    store.string(payload["feedback_id"], "feedback_id")
    store.string(payload["reason"], "reason")
    if not isinstance(payload["check_ids"], list) or not payload["check_ids"] or not set(payload["check_ids"]) <= CHECKS:
        fail("feedback_scope", "explicit affected check IDs required")
    if not isinstance(payload["issue_ids"], list):
        fail("feedback_scope", "issue_ids must be a list")
    for key in payload["issue_ids"]:
        store.string(key, "issue_id")
    evidence(payload["source"])
    value = {**identity(context), "request_id": context["request_id"], **payload}
    with store.database(store.store_path(context["store_path"]), True) as conn:
        existing = [r for r in store.rows(conn, value["content_id"]) if r["record_type"] == "editorial_feedback" and r["payload"]["feedback_id"] == payload["feedback_id"]]
        if existing and existing[0]["payload"] != value:
            fail("feedback_id_conflict", payload["feedback_id"])
        return store.append(conn, "editorial_feedback", value, {})


def purpose_alignment(row, preparation, historical=False):
    """Check source continuity and an editorial explanation, never its semantics.

    A title may attract attention while the body explains; atmosphere, silence
    and other indirect contributions are valid descriptions. No route, wording,
    layout or commercial outcome is selected by this structural check.
    """
    goal = keyed(preparation["items"], "id")["goal_audience"]
    shared = any(ref in goal["evidence"] for ref in row["evidence"])
    alignment = row.get("purpose_alignment")
    if not shared or alignment is None:
        if historical:
            return False  # Legacy playback is not proof of the new obligation.
        fail("purpose_source_missing" if not shared else "purpose_alignment_missing",
             "C01 requires the same purpose source and a stage-specific contribution assessment")
    store.shape(alignment, PURPOSE_FIELDS, label="purpose_alignment")
    for key, value in alignment.items():
        store.string(value, "purpose_alignment." + key)
        if value.strip().lower() in GENERIC_REASONS:
            fail("purpose_alignment_missing", key + " requires a specific editorial explanation")
    return goal["state"] == "ready"


def evaluate(envelope_path, data, records=None, historical=False):
    envelope = author.validate_revision(envelope_path)
    context_path = author.checked_ref(envelope["context_ref"])
    context, preparation = preflight(context_path, records=records if historical else None, historical=historical)
    effective_fc = preparation.get("fact_card_ref") or context.get("fact_card_ref")
    if not historical and effective_fc is None:
        fail("fact_card_required", "formal review/advancement requires a locked fact_card_ref in preflight")
    if not historical and effective_fc is not None:
        current_fc_sha = effective_fc["sha256"].lower()
        env_fc_sha = (envelope.get("fact_card_sha256") or "").lower()
        if env_fc_sha != current_fc_sha:
            fail("fact_card_changed", "formal review/advancement requires revision envelope bound to current locked fact_card_ref")
    records = history(context) if records is None else records
    revision = author.checked_record(store.store_path(context["store_path"]), envelope["revision_ref"], "revision")
    current = latest(records, "revision")
    if not historical and (current is None or current["record_id"] != revision["record_id"]):
        fail("revision_stale", "only the latest recorded draft can advance")
    store.shape(data, {"request_id", "draft_ref", "phase", "route", "previous_review_id", "feedback_ids", "changes", "checks", "issues", "actor", "source", "observations"}, {"plain_language_review_ref"})
    if data["request_id"] != envelope["request_id"] or data["draft_ref"] != envelope["draft_ref"]:
        fail("version_mismatch", "review must bind this request and exact draft")
    store.choice(data["phase"], PHASES, "phase")
    if data["route"] != preparation["route"]:
        fail("route_mismatch", "use the current preparation route")
    store.string(data["actor"], "actor")
    if not context["synthetic_only"] and data["actor"] == "synthetic_fixture":
        fail("synthetic_review", "synthetic evidence cannot complete a real review")
    evidence(data["source"])
    if not isinstance(data["changes"], list) or not set(data["changes"]) <= set(IMPACT):
        fail("change_scope", "unknown change kind")
    previous = latest(records, "editorial_review")
    if data["previous_review_id"] != (previous["record_id"] if previous else None):
        fail("history_gap", "carry the latest review, including still-open issues")
    feedbacks = [r for r in records if r["record_type"] == "editorial_feedback"]
    expected_feedback = [r["record_id"] for r in feedbacks]
    if data["feedback_ids"] != expected_feedback:
        fail("feedback_pending", "new feedback requires a new review even when text is unchanged")
    old = previous["payload"]["assessment"] if previous else None
    text = author.draft_text(author.checked_ref(envelope["draft_ref"]))
    affected = set().union(*(IMPACT[c] for c in data["changes"])) if data["changes"] else set()
    if old and old["draft_ref"] != data["draft_ref"]:
        if not data["changes"]:
            fail("change_scope", "a changed draft requires impact classification")
        affected |= IMPACT["wording"]
        old_text = previous["payload"]["draft_text"]
        old_lines, new_lines = old_text.splitlines(), text.splitlines()
        shared = set(old_lines) & set(new_lines)
        if len(old_lines) != len(new_lines) or [s for s in old_lines if s in shared] != [s for s in new_lines if s in shared]:
            affected |= IMPACT["structure"]
    if old and (old["phase"] != data["phase"] or old["route"] != data["route"]):
        affected |= CHECKS
    newly_raised = [r for r in feedbacks if not old or r["record_id"] not in old["feedback_ids"]]
    for row in newly_raised:
        affected.update(row["payload"]["check_ids"])
    checks = keyed(data["checks"], "id", CHECKS)
    old_checks = keyed(old["checks"], "id") if old else {}
    purpose_complete = False
    story_complete = data["route"] != "story"
    facets_complete = context.get("topic_facets") is None
    plan_ref = context.get("plain_language_plan_ref")
    plan_applicable = False
    if plan_ref is not None:
        import plain_language_gate as pl_gate
        plan_path = author.checked_ref(plan_ref)
        plan_doc = pl_gate.load_json(plan_path)
        plan_applicable = plan_doc.get("applicability") == "applicable"
    pl_review_ref = data.get("plain_language_review_ref")
    if historical and not pl_review_ref and not plan_applicable:
        plain_language_complete = True
    elif not plan_applicable and not pl_review_ref:
        plain_language_complete = True
    elif pl_review_ref is None:
        plain_language_complete = False
    else:
        import plain_language_gate as pl_gate
        if not isinstance(pl_review_ref, dict) or not pl_review_ref.get("path") or not pl_review_ref.get("sha256"):
            fail("plain_language_review_invalid", "plain_language_review_ref must be a hash-bound reference object")
        rev_path = author.checked_ref(pl_review_ref)
        try:
            pl_gate.validate_review(
                pl_gate.load_json(rev_path),
                expected_request_id=data["request_id"],
                expected_content_id=context["author_brief"]["content_id"],
                expected_body_path=author.checked_ref(envelope["draft_ref"]),
                expected_plan_ref=plan_ref,
                expected_fact_card_ref=context.get("fact_card_ref"),
                base_dir=rev_path.parent,
            )
        except (pl_gate.PlainLanguageError, json.JSONDecodeError) as error:
            fail(getattr(error, "code", "plain_language_review_invalid"), str(error))
        plain_language_complete = True
    for key, row in checks.items():
        store.shape(row, {"id", "state", "scope", "quote", "reason", "evidence", "issue_ids", "reuse_from"}, {"text_review", "purpose_alignment", "story_card_ref", "story_realization", "facet_realization"})
        if key != "C04" and ("story_card_ref" in row or "story_realization" in row):
            fail("story_review_scope", "story sentence review belongs to the existing structure check C04")
        if key != "C04" and "facet_realization" in row:
            fail("facet_review_scope", "topic facet realization review belongs to C04")
        if key != "C01" and "purpose_alignment" in row:
            fail("purpose_alignment_scope", "the common purpose assessment belongs to C01")
        store.choice(row["state"], STATES, "check.state")
        if key == 'C01' and row['state'] == 'not_applicable' and not historical:
            fail('purpose_not_applicable', 'Current C01 must assess the actual output against its purpose')
        store.string(row["scope"], "scope")
        if not isinstance(row["issue_ids"], list):
            fail("issue_refs", key)
        if row["state"] in DONE:
            if key == "C04" and data["route"] == "story" and not historical:
                story_complete = story_text_review(context, text, row)
            if key == "C04" and context.get("topic_facets") is not None:
                allow_incomplete = row["state"] == "findings"
                if not historical:
                    facets_complete = facet_text_review(context, text, row, allow_incomplete=allow_incomplete)
                else:
                    facets_complete = facet_text_review(context, text, row, allow_incomplete=allow_incomplete) if row.get("facet_realization") else False
            store.string(row["reason"], "specific reasoning")
            if row["reason"].strip().lower() in GENERIC_REASONS:
                fail("reason_missing", key)
            evidence_list(row["evidence"])
            if key == "C01":
                purpose_complete = purpose_alignment(row, preparation, historical=historical)
            if row["state"] != "not_applicable":
                store.string(row["quote"], "current draft anchor")
                if row["quote"] not in text:
                    fail("anchor_missing", key)
            elif key in {"C01", "C02", "C03", "C04", "C05", "C06", "C08"}:
                fail("not_applicable_scope", key + " requires an assessment even when no issue is found")
            elif data["phase"] == "final_media":
                fail("not_applicable_scope", "actual final media requires C07/C09 review")
            elif key in {"C07", "C09"}:
                # Missing footage only defers the media portion. It cannot erase
                # the text/plan review for privacy, claims or spoken clarity.
                if row["scope"] != "actual_media" or "text_review" not in row:
                    fail("text_review_missing", key)
                text_review = row["text_review"]
                store.shape(text_review, {"quote", "reason", "evidence"})
                store.string(text_review["quote"], "text review anchor")
                store.string(text_review["reason"], "text review reasoning")
                if text_review["quote"] not in text:
                    fail("anchor_missing", key)
                evidence_list(text_review["evidence"])
            if data["phase"] == "final_media" and key in {"C07", "C09"} and row["scope"] != "final_media":
                fail("media_review_missing", key)
        if row["reuse_from"] is not None:
            if not previous or row["reuse_from"] != previous["record_id"] or key not in old_checks or key in affected:
                fail("reuse_stale", key)
            # Applicability reason is new; original evidence and findings stay exact.
            prior = old_checks[key]
            for field in ("state", "scope", "quote", "evidence", "issue_ids", "text_review", "purpose_alignment", "story_card_ref", "story_realization", "facet_realization"):
                if row.get(field) != prior.get(field):
                    fail("reuse_changed", key + ":" + field)
            store.string(row["reason"], "current-version applicability")
    issues = keyed(data["issues"], "id")
    old_issues = keyed(old["issues"], "id") if old else {}
    if not set(old_issues) <= set(issues):
        fail("issue_lost", ",".join(sorted(set(old_issues) - set(issues))))
    reopen = {key for r in newly_raised for key in r["payload"]["issue_ids"]}
    if not reopen <= set(issues):
        fail("feedback_issue_lost", ",".join(sorted(reopen - set(issues))))
    for key, row in issues.items():
        store.shape(row, {"id", "first_revision", "check_ids", "required", "state", "before", "after", "reason", "verification", "reopened_by", "verified_draft_sha256"})
        store.boolean(row["required"], "required")
        store.choice(row["state"], {"open", "deferred", "fixed", "retained"}, "issue.state")
        store.string(row["before"], "original finding")
        store.string(row["reason"], "disposition")
        if not isinstance(row["check_ids"], list) or not row["check_ids"] or not set(row["check_ids"]) <= set(checks):
            fail("issue_refs", key)
        if key in old_issues:
            prior = old_issues[key]
            if row["first_revision"] != prior["first_revision"] or row["before"] != prior["before"] or (prior["required"] and not row["required"]):
                fail("issue_history_changed", key)
        elif row["first_revision"] != revision["record_id"]:
            fail("issue_origin", key)
        if key in reopen and not set(r["record_id"] for r in newly_raised if key in r["payload"]["issue_ids"]) <= set(row["reopened_by"]):
            fail("issue_not_reopened", key)
        if row["state"] in {"fixed", "retained"}:
            if row["verified_draft_sha256"] != envelope["draft_ref"]["sha256"]:
                fail("issue_verification_stale", key)
            evidence_list(row["verification"])
            store.string(row["after"], "current disposition anchor")
            if row["after"] not in text:
                fail("issue_verification_anchor", key)
            if row["state"] == "fixed" and row["before"] == row["after"]:
                fail("no_actual_edit", "use retained with reasons, not fixed: " + key)
            if any(checks[c]["state"] not in DONE for c in row["check_ids"]):
                fail("issue_not_verified", key)
            if key in reopen and old_issues.get(key, {}).get("verification") == row["verification"]:
                fail("issue_recheck_required", key)
        for c in row["check_ids"]:
            if key not in checks[c]["issue_ids"]:
                fail("issue_refs", key)
    for key, row in checks.items():
        if not set(row["issue_ids"]) <= set(issues) or (row["state"] == "findings" and not row["issue_ids"]):
            fail("issue_refs", key)
        if row["state"] == "revised_verified" and not any(issues[i]["state"] == "fixed" for i in row["issue_ids"]):
            fail("no_actual_edit", key)
    store.shape(data["observations"], {"readthrough", "final_media"})
    for kind, value in data["observations"].items():
        if value is not None:
            store.shape(value, {"kind", "artifact", "source"})
            if value["kind"] != "observed":
                fail("observation_required", "estimated durations are not observed evidence")
            actual = author.checked_ref(value["artifact"])
            if actual.suffix.lower() not in {".wav", ".mp3", ".m4a", ".mp4", ".mov", ".webm", ".flac"}:
                fail("observation_media_missing", "a script/report cannot substitute for an actual recording")
            evidence(value["source"])
    coverage = set(checks) == CHECKS
    execution = coverage and all(r["state"] in DONE for r in checks.values())
    pending = [key for key, r in issues.items() if r["required"] and r["state"] not in {"fixed", "retained"}]
    preparation_complete = all(r["state"] != "missing_input" for r in preparation["items"])
    observation_complete = data["phase"] == "draft" or data["observations"][data["phase"]] is not None
    author_confirmed = envelope.get("review_ref") is not None
    if author_confirmed:
        author.validate_revision(envelope_path, True, require_current=not historical)
        confirmation_history = records if historical else history(context)
        confirmation_index = next((i for i, r in enumerate(confirmation_history)
                                   if r["record_id"] == envelope["review_ref"]["record_id"]), -1)
        if any(r["record_type"] == "editorial_feedback" and set(r["payload"]["check_ids"]) & {"C01", "C05"}
               for r in confirmation_history[confirmation_index + 1:]):
            author_confirmed = False
    return {"records_complete": coverage, "checks_complete": execution,
            "required_issues_closed": not pending, "preparation_complete": preparation_complete,
            "purpose_continuity_complete": purpose_complete,
            "story_realization_complete": story_complete,
            "facet_realization_complete": facets_complete,
            "plain_language_complete": plain_language_complete,
            "author_confirmation_recorded": author_confirmed, "observations_complete": observation_complete,
            "may_advance": (not historical and execution and not pending and preparation_complete
                            and purpose_complete and story_complete and facets_complete
                            and plain_language_complete and observation_complete and author_confirmed),
            "missing_checks": sorted(CHECKS - set(checks)), "open_required_issues": pending,
            "phase": data["phase"], "proves_editorial_quality": False,
            "publication_authorized": False}, context, revision, text


def record_review(envelope_path, data):
    result, context, revision, text = evaluate(envelope_path, data)
    envelope = author.load(envelope_path)
    context_path = author.checked_ref(envelope["context_ref"])
    _, preparation = preflight(context_path)
    effective_fc = preparation.get("fact_card_ref") or context.get("fact_card_ref")
    fc_sha = effective_fc["sha256"].lower() if isinstance(effective_fc, dict) and effective_fc.get("sha256") else None
    value = {**identity(context), "revision_id": revision["record_id"], "assessment": data,
             "draft_text": text, "envelope_ref": author.ref(envelope_path), "fact_card_sha256": fc_sha}
    with store.database(store.store_path(context["store_path"]), True) as conn:
        records = store.rows(conn, revision["content_id"])
        current = latest(records, "editorial_review")
        if data["previous_review_id"] != (current["record_id"] if current else None):
            fail("history_race", "review changed; reload current evidence")
        # Recheck revision/feedback inside the write transaction as well.
        result, _, _, _ = evaluate(envelope_path, data, records)
        record = store.append(conn, "editorial_review", value, {})
    return {"record": author.record_ref(record), **result}


def status(envelope_path, historical=False):
    envelope = author.validate_revision(envelope_path)
    context_path = author.checked_ref(envelope["context_ref"])
    context = author.validate_context(context_path)
    records = history(context)
    record = latest([r for r in records if r["record_type"] != "editorial_review" or
                     r["payload"]["revision_id"] == envelope["revision_ref"]["record_id"]], "editorial_review")
    if record is None or record["payload"]["revision_id"] != envelope["revision_ref"]["record_id"]:
        fail("review_missing", "no current-version editorial review; old checks cannot imply completion")
    # Replay against the prior history; subsequently appended feedback invalidates
    # old success even if the document bytes and revision ID have not changed.
    before = records[:records.index(record)]
    if not historical:
        before += [r for r in records[records.index(record)+1:] if r["record_type"] in {"revision", "editorial_feedback"}]
    result, _, _, _ = evaluate(envelope_path, record["payload"]["assessment"], before, historical=historical)
    if not historical:
        _, latest_prep = preflight(context_path, records=records, historical=False)
        latest_fc_ref = latest_prep.get("fact_card_ref") or context.get("fact_card_ref") or {}
        latest_fc = str(latest_fc_ref.get("sha256") or "").lower()
        review_fc = str(record["payload"].get("fact_card_sha256") or "").lower()
        env_fc = str(envelope.get("fact_card_sha256") or "").lower()
        if not latest_fc or review_fc != latest_fc or env_fc != latest_fc:
            fail("fact_card_changed", "fact card binding missing or changed after review; re-review required before advancing")
    current = latest(records, "revision")
    return {"record": author.record_ref(record), "historical_only": historical,
            "is_current_revision": current is not None and current["record_id"] == envelope["revision_ref"]["record_id"], **result}


ALLOWED_FACT_CARD_SCHEMAS = {
    "content-fact-card.v0",
    "content-fact-card.v1",
    "self-media.content-fact-card.v0",
    "self-media.content-fact-card.v1",
}


def check_fact_card(fact_card_path, *, expected_sha256=None, content_id=None):
    """Fail-closed gate: drafting/editorial review requires a human-locked content-fact-card."""
    path = Path(fact_card_path).resolve(strict=True)
    if path.stat().st_size > 2_000_000:
        fail("fact_card_too_large", "fact card JSON exceeds 2 MB limit")
    # Single-read byte load + digest + parse to eliminate TOCTOU double-read drift.
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if expected_sha256 is not None:
        if not isinstance(expected_sha256, str) or len(expected_sha256) != 64 or any(c not in "0123456789abcdef" for c in expected_sha256.lower()):
            fail("fact_card_hash_invalid", "expected_sha256 must be a 64-char hex digest")
        if digest != expected_sha256.lower():
            fail("fact_card_hash_mismatch", f"expected {expected_sha256}, got {digest}")
    card = json.loads(raw.decode("utf-8-sig"))
    if not isinstance(card, dict):
        fail("fact_card_invalid", "fact card must be a JSON object")
    schema = card.get("schema") if isinstance(card.get("schema"), str) else card.get("schema_version")
    if schema not in ALLOWED_FACT_CARD_SCHEMAS:
        fail("fact_card_schema_invalid", f"unsupported fact card schema: {schema!r}")
    if card.get("canonical_status") != "locked_for_draft":
        fail("fact_card_not_locked", f"canonical_status must be 'locked_for_draft', got {card.get('canonical_status')!r}")
    if "human_confirmation" in card:
        confirm = card.get("human_confirmation")
        if isinstance(confirm, bool) or confirm is None:
            fail("fact_card_confirmation_missing", "explicit human_confirmation quote/object required (bare boolean rejected)")
        if isinstance(confirm, str):
            if not confirm.strip():
                fail("fact_card_confirmation_missing", "human_confirmation string cannot be empty")
        elif isinstance(confirm, dict):
            raw_quote = confirm.get("quote") if "quote" in confirm else confirm.get("text")
            if not isinstance(raw_quote, str) or not raw_quote.strip():
                fail("fact_card_confirmation_missing", "human_confirmation.quote must be a non-empty string")
        else:
            fail("fact_card_confirmation_missing", "invalid human_confirmation format")
    else:
        # Also allow Mode B plain_language_gate locked cards (gates.fact == 'pass' + confirmed facts + revision_id).
        has_pl_lock = (
            isinstance(card.get("gates"), dict)
            and card["gates"].get("fact") == "pass"
            and bool(str(card.get("revision_id") or "").strip())
            and isinstance(card.get("facts"), list)
            and any(isinstance(f, dict) and f.get("status") in (None, "confirmed") for f in card["facts"])
        )
        if not has_pl_lock:
            fail("fact_card_confirmation_missing", "explicit human_confirmation quote/object required (bare boolean rejected)")
    if content_id is not None:
        card_cid = card.get("content_id")
        if not isinstance(card_cid, str) or card_cid != content_id:
            fail("fact_card_content_mismatch", f"fact card content_id {card_cid!r} != expected {content_id!r}")
    return {
        "fact_card_ref": {"path": str(path), "sha256": digest},
        "canonical_status": "locked_for_draft",
        "locked": True,
    }


def check_draft(draft_path, envelope_path=None):
    """Read-only admission for an existing manuscript, without importing samples.

Missing supplied evidence is not proof that no one has reviewed the manuscript.
"""
    path = Path(draft_path).resolve(strict=True)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if envelope_path is None:
        return {"draft_sha256": digest, "status": "evidence_not_supplied", "may_advance": False,
                "missing_evidence": ["author-writing-revision", "current-editorial-review"],
                "checks_complete": None, "author_confirmation_recorded": None,
                "proves_editorial_quality": False, "publication_authorized": False}
    envelope = author.validate_revision(envelope_path)
    if author.checked_ref(envelope["draft_ref"]) != path or envelope["draft_ref"]["sha256"] != digest:
        fail("version_mismatch", "supplied manuscript is not the reviewed draft")
    return {"draft_sha256": digest, **status(envelope_path)}


def carry_over(revision_path, changes, output_path=None, actor=None):
    """Generate a clean editorial review template carrying over unaffected C01-C09 checks."""
    envelope = author.validate_revision(revision_path)
    context_path = author.checked_ref(envelope["context_ref"])
    context, preparation = preflight(context_path)
    records = history(context)
    revision = author.checked_record(store.store_path(context["store_path"]), envelope["revision_ref"], "revision")
    current = latest(records, "revision")
    if current is None or current["record_id"] != revision["record_id"]:
        fail("revision_stale", "carry-over must target the latest recorded draft")
    previous = latest(records, "editorial_review")
    if previous is None:
        fail("history_gap", "carry-over requires a previous editorial review in the author store")
    if not isinstance(changes, list) or not changes or not set(changes) <= set(IMPACT):
        fail("change_scope", "changes must be a non-empty list of valid change kinds: " + ", ".join(sorted(IMPACT)))
    old = previous["payload"]["assessment"]
    feedbacks = [r for r in records if r["record_type"] == "editorial_feedback"]
    expected_feedback = [r["record_id"] for r in feedbacks]
    text = author.draft_text(author.checked_ref(envelope["draft_ref"]))
    affected = set().union(*(IMPACT[c] for c in changes)) if changes else set()
    if old and old.get("draft_ref") != envelope["draft_ref"]:
        affected |= IMPACT["wording"]
        old_text = previous["payload"]["draft_text"]
        old_lines, new_lines = old_text.splitlines(), text.splitlines()
        shared = set(old_lines) & set(new_lines)
        if len(old_lines) != len(new_lines) or [s for s in old_lines if s in shared] != [s for s in new_lines if s in shared]:
            affected |= IMPACT["structure"]
    if old and (old.get("phase") != "draft" or old.get("route") != preparation["route"]):
        affected |= CHECKS
    newly_raised = [r for r in feedbacks if not old or r["record_id"] not in old.get("feedback_ids", [])]
    for row in newly_raised:
        affected.update(row["payload"]["check_ids"])

    old_checks = keyed(old["checks"], "id")
    new_checks = []
    for cid in sorted(CHECKS):
        prior = old_checks.get(cid)
        if prior and cid not in affected:
            quote = prior.get("quote", "")
            facet_quotes = []
            if cid == "C04" and isinstance(prior.get("facet_realization"), dict):
                fr = prior["facet_realization"]
                for q in (
                    (fr.get("main_element") or {}).get("quote"),
                    (fr.get("dominant_action_check") or {}).get("quote"),
                    *(item.get("quote") for item in (fr.get("supporting_elements") or []) if isinstance(item, dict)),
                ):
                    if isinstance(q, str) and q:
                        facet_quotes.append(q)
            if quote and quote not in text:
                affected.add(cid)
            elif prior.get("text_review") and prior["text_review"].get("quote") and prior["text_review"]["quote"] not in text:
                affected.add(cid)
            elif any(q not in text for q in facet_quotes):
                affected.add(cid)
            else:
                row = copy.deepcopy(prior)
                row["reuse_from"] = previous["record_id"]
                row["reason"] = f"Unchanged by {','.join(changes)}; carried over from {previous['record_id']}"
                new_checks.append(row)
                continue
        scope = prior.get("scope") if prior else ("actual_media" if cid in {"C07", "C09"} else "draft_text")
        row = {
            "id": cid,
            "state": "unchecked",
            "scope": scope,
            "quote": "",
            "reason": "",
            "evidence": [],
            "issue_ids": copy.deepcopy(prior.get("issue_ids", [])) if prior else [],
            "reuse_from": None,
        }
        if cid == "C01":
            row["purpose_alignment"] = {f: "" for f in PURPOSE_FIELDS}
        elif cid == "C04":
            if preparation["route"] == "story":
                row["story_card_ref"] = ""
                row["story_realization"] = ""
            if context.get("topic_facets"):
                facets = context["topic_facets"]
                row["facet_realization"] = {
                    "angle_id": facets["angle_id"],
                    "dominant_action": facets["dominant_action"],
                    "main_element": {
                        "element_id": facets["main_element"]["element_id"],
                        "quote": "",
                        "assessment": "",
                    },
                    "supporting_elements": [
                        {
                            "element_id": item["element_id"],
                            "relation": item["relation"],
                            "status": "realized",
                            "quote": "",
                            "assessment": "",
                        }
                        for item in facets["supporting_elements"]
                    ],
                    "dominant_action_check": {"quote": "", "assessment": ""},
                }
        elif cid in {"C07", "C09"}:
            row["text_review"] = {"quote": "", "reason": "", "evidence": []}
        new_checks.append(row)

    old_issues = old.get("issues", [])
    carried_issues = []
    for issue in old_issues:
        iss = copy.deepcopy(issue)
        all_unaffected = not any(c in affected for c in iss.get("check_ids", []))
        if iss.get("state") in {"fixed", "retained"}:
            if all_unaffected and iss.get("after", "") in text:
                iss["verified_draft_sha256"] = envelope["draft_ref"]["sha256"]
            else:
                iss["state"] = "open"
                iss["verified_draft_sha256"] = ""
        carried_issues.append(iss)

    reopen_keys = {key for r in newly_raised for key in r["payload"]["issue_ids"]}
    existing_issue_ids = {iss["id"] for iss in carried_issues}
    for r in newly_raised:
        for iid in r["payload"]["issue_ids"]:
            if iid in existing_issue_ids:
                iss = next(x for x in carried_issues if x["id"] == iid)
                iss["state"] = "open"
                iss["reopened_by"] = list(dict.fromkeys(iss.get("reopened_by", []) + [r["record_id"]]))
            else:
                carried_issues.append({
                    "id": iid,
                    "first_revision": envelope["revision_ref"]["record_id"],
                    "check_ids": sorted(list(r["payload"]["check_ids"])),
                    "required": True,
                    "state": "open",
                    "before": r["payload"]["reason"],
                    "after": "",
                    "reason": f"Raised by feedback {r['record_id']}",
                    "verification": [],
                    "reopened_by": [r["record_id"]],
                    "verified_draft_sha256": "",
                })

    observations = copy.deepcopy(old.get("observations", {"readthrough": None, "final_media": None}))
    substantive_changes = bool(set(changes) & {"facts", "claims", "structure", "wording", "goal", "promise"})
    plain_language_invalidated = substantive_changes or (old.get("draft_ref") != envelope["draft_ref"])

    template = {
        "request_id": envelope["request_id"],
        "draft_ref": envelope["draft_ref"],
        "phase": old.get("phase", "draft"),
        "route": preparation["route"],
        "previous_review_id": previous["record_id"],
        "feedback_ids": expected_feedback,
        "changes": sorted(list(changes)),
        "checks": new_checks,
        "issues": carried_issues,
        "actor": actor or old.get("actor", "editorial_reviewer"),
        "source": copy.deepcopy(old.get("source")),
        "observations": observations,
    }
    if old.get("plain_language_review_ref") is not None or context.get("plain_language_plan_ref") is not None:
        template["plain_language_review_ref"] = (
            copy.deepcopy(old["plain_language_review_ref"])
            if (not plain_language_invalidated and old.get("plain_language_review_ref") is not None)
            else None
        )

    if output_path is not None:
        out = Path(output_path).resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        rendered = json.dumps(template, ensure_ascii=False, indent=2) + "\n"
        temp = out.with_name(f".{out.name}.tmp")
        temp.write_text(rendered, encoding="utf-8")
        temp.replace(out)

    return {
        "status": "carry_over_template_generated",
        "previous_review_id": previous["record_id"],
        "carried_over_checks": [c["id"] for c in new_checks if c.get("reuse_from")],
        "affected_checks_requiring_evaluation": sorted(list(affected)),
        "plain_language_review_invalidated": plain_language_invalidated,
        "output": str(output_path) if output_path else None,
        "template": template,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["preflight", "feedback", "record", "check", "check-draft", "carry-over"])
    parser.add_argument("--context", type=Path)
    parser.add_argument("--revision", type=Path)
    parser.add_argument("--draft", type=Path)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--changes", nargs="+", choices=sorted(IMPACT))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--actor")
    parser.add_argument("--fact-card", type=Path)
    parser.add_argument("--require-fact-card", action="store_true")
    parser.add_argument("--require-complete", action="store_true")
    args = parser.parse_args(argv)
    try:
        fact_card_receipt = None
        if args.require_fact_card and not args.fact_card:
            fail("fact_card_required", "--fact-card is required when --require-fact-card is set")
        if args.fact_card:
            fact_card_receipt = check_fact_card(args.fact_card)
        if args.action == "check-draft":
            if not args.draft:
                fail("arguments", "--draft required")
            result = check_draft(args.draft, args.revision)
        elif args.action in {"preflight", "feedback"}:
            if not args.context or not args.input:
                fail("arguments", "--context and --input required")
            fn = record_preflight if args.action == "preflight" else feedback
            result = {"record": author.record_ref(fn(args.context, author.load(args.input)))}
        elif args.action == "carry-over":
            if not args.revision or not args.changes or not args.output:
                fail("arguments", "--revision, --changes and --output required for carry-over")
            result = carry_over(args.revision, args.changes, args.output, actor=args.actor)
        else:
            if not args.revision or (args.action == "record" and not args.input):
                fail("arguments", "--revision and record --input required")
            result = record_review(args.revision, author.load(args.input)) if args.action == "record" else status(args.revision)
        if fact_card_receipt is not None:
            result["fact_card_gate"] = fact_card_receipt
        print(json.dumps(result, ensure_ascii=False))
        return 2 if args.require_complete and not result.get("may_advance", False) else 0
    except (ValueError, KeyError, TypeError, OSError) as error:
        print(json.dumps({"status": "blocked", "code": getattr(error, "code", "editorial_invalid"), "message": str(error)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
