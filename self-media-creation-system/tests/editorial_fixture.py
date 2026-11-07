"""Invented editorial evidence for isolated integration tests, never production."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import author_writing_context as author
import editorial_integrity as integrity

PURPOSE = "Synthetic purpose: help a reader understand the invented author's declared meaning and its limits."
AUDIENCE = "Synthetic audience: readers of the invented explanation, with no real audience outcome asserted."


def _purpose_source(root):
    source = Path(root) / "synthetic-editorial-source.md"
    if not source.exists():
        source.write_text("Invented test observation. No real author or editorial judgment is asserted. "
                          + PURPOSE + "\n" + AUDIENCE, encoding="utf-8")
    return source


def preparation(context_path, route="expository"):
    context_path = Path(context_path)
    source = _purpose_source(context_path.parent)
    evidence = {**author.ref(source), "quote": PURPOSE}
    integrity.record_preflight(context_path, {"route": route, "actor": "synthetic_fixture", "source": evidence,
        "items": [{"id": k, "state": "ready", "reason": "Synthetic preparation for " + k, "evidence": [evidence]}
                  for k in sorted(integrity.PRE)]})
    return evidence


def bind_stage_purpose(manifest, root, content_id, duty, body_path=None):
    """Add explicit invented purpose to a real managed-chain test manifest."""
    root = Path(root).resolve()
    source = _purpose_source(root)
    purpose_id = "synthetic-editorial-purpose"
    manifest["artifacts"].append({"artifact_id": purpose_id, "role": "source_manifest",
        "source_role": "content-purpose", "path": source.relative_to(root).as_posix(),
        "load_mode": "reference", "expected_sha256": author.ref(source)["sha256"]})
    body_id = None
    if body_path is not None:
        body_path = Path(body_path).resolve()
        body_id = next((row["artifact_id"] for row in manifest["artifacts"]
                        if (root / row["path"]).resolve() == body_path), None)
        if body_id is None:
            body_id = "synthetic-current-body"
            manifest["artifacts"].append({"artifact_id": body_id, "role": "approved_script",
                "source_role": "current-body", "path": body_path.relative_to(root).as_posix(),
                "load_mode": "reference", "expected_sha256": author.ref(body_path)["sha256"]})
    manifest["editorial_context"] = {"version": 1, "content_id": content_id,
        "purpose": {"artifact_id": purpose_id, "quote": PURPOSE},
        "audience": {"artifact_id": purpose_id, "quote": AUDIENCE},
        "stage_duty": duty, "current_body_artifact_id": body_id,
        "feedback": [], "feedback_note": "This isolated synthetic sequence starts with no feedback; later feedback must reopen it."}
    return manifest


def stage_purpose_review(handoff_path, artifact_path):
    """Bind an actual synthetic output without claiming semantic owner execution."""
    handoff_path, artifact_path = Path(handoff_path).resolve(), Path(artifact_path).resolve()
    handoff = author.load(handoff_path)
    if not handoff["execution_brief"].get("purpose_context") or not artifact_path.stat().st_size:
        return None
    context_path = (handoff_path.parent / handoff["context"]["manifest"]["path"]).resolve()
    context = author.load(context_path)["editorial_context"]
    output = handoff_path.with_name(handoff_path.stem + "-purpose-review.json")
    ref = lambda path: {"path": path.relative_to(output.parent).as_posix(), "sha256": author.ref(path)["sha256"]}
    review = {"schema_version": "self-media-stage-purpose-review.v1",
        "context_ref": ref(context_path), "artifact_ref": ref(artifact_path),
        "quote": artifact_path.read_text(encoding="utf-8-sig")[:120],
        "purpose_alignment": {"stage_duty": context["stage_duty"],
            "contribution": "The cited synthetic output carries this step's invented explanation or review record.",
            "misunderstanding_risk": "Transport validation must not be presented as real editorial judgment or audience success.",
            "tradeoff": "Keep the existing route and domain checks; this fixture adds binding evidence, not a prescribed style."},
        "feedback_resolutions": [{"artifact_id": row["artifact_id"], "resolution": "Synthetic feedback explicitly carried into this output record."}
                                 for row in context["feedback"]],
        "disposition": "retained", "reason": "Retain this synthetic transport output while existing owner-specific checks remain required."}
    output.write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")
    return output


def review(envelope_path):
    envelope = author.load(envelope_path)
    context_path = author.checked_ref(envelope["context_ref"])
    context = author.load(context_path)
    evidence = preparation(context_path)
    prior = integrity.latest(integrity.history(context), "editorial_review")
    text = author.draft_text(author.checked_ref(envelope["draft_ref"]))
    assessment = {
        "request_id": envelope["request_id"], "draft_ref": envelope["draft_ref"], "route": "expository", "phase": "draft",
        "previous_review_id": prior["record_id"] if prior else None,
        "feedback_ids": [], "changes": ["wording", "structure", "claims"] if prior else [],
        "actor": "synthetic_fixture" if context["synthetic_only"] else "assistant", "source": evidence, "issues": [],
        "observations": {"readthrough": None, "final_media": None},
        "checks": [{"id": c, "state": "retained", "scope": "script-text", "quote": text[:50],
                    "reason": "Invented scope-specific assessment for " + c, "evidence": [evidence],
                    "issue_ids": [], "reuse_from": None} for c in sorted(integrity.CHECKS)],
    }
    assessment["checks"][0]["purpose_alignment"] = {
        "stage_duty": "Make the invented author's declared meaning understandable in this synthetic draft.",
        "contribution": "The cited draft fragment carries the invented author's statement into the review.",
        "misunderstanding_risk": "The fixture must not be mistaken for real author approval or factual evidence.",
        "tradeoff": "Keep synthetic provenance explicit even when a shorter fixture could omit it.",
    }
    integrity.record_review(envelope_path, assessment)
