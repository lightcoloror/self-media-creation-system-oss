# Initial-draft quality gate

Use this gate immediately after the Storycraft first draft and before detailed spoken-language rewriting, `dbs-content`, `dbs-ai-check`, `dbs-hook`, trial shooting, or publishing preparation.

The machine contract is `case-video-initial-draft-review.v1`. Its Schema and validator are bound in [contract-binding.json](contract-binding.json). If this prose conflicts with the machine contract, the Schema and validator win.

## Exact fixed order

1. `fact_evidence` — facts, chronology, numbers, quotations, corrections, evidence, and fact-card revision are traceable.
2. `single_task` — one primary audience, question, and service capability remain.
3. `service_causality` — a concrete creator action changes the process; praise does not substitute for action.
4. `interview_integrity` — audio context, timecodes, quotation boundaries, and objective-record separation are preserved.
5. `distribution_compliance` — content classification, current/future rules, institution review, authorized account/person route, advertising and AI-label duties are recorded without assuming a private-domain or education exemption.
6. `medical_insurance` — no medical-decision substitution, treatment-superiority generalization, policy promise, or unreviewed service implication appears.
7. `privacy_authorization` — service consent and publication consent are separate; subject/patient scope, face, voice, health, claim data, redaction, withdrawal, and final-cut approval are recorded.
8. `title_opening_alignment` — title, opening, body, and CTA make the same supportable promise.
9. `voice_ai_trace` — the preliminary spoken-language check catches stagey turns, symmetry, abstract praise, and uniform rhythm.
10. `cta_product` — CTA and paid/included service boundaries match the proven capability and minimum next step.
11. `production_series` — the piece stands alone, avoids neighboring-episode duplication, assigns audio/visual roles, and has a feasible test variable.

All eleven gates must be present. The validator owns the exact `reviewed_check_ids` for each gate; do not shorten or rename them in machine receipts.

`interview_integrity` may be `not_applicable` only when the script has no interview slot. `cta_product` may be `not_applicable` only when the goal is not acquisition, consultation, or conversion. No other gate may be `not_applicable`.

## Decisive reverse test

Remove the creator's actions and reread the draft.

- If the same result still follows, the story fails `service_causality` for acquisition use.
- If the process breaks because a specific act of organizing, checking, communicating, coordinating, or following up disappears, the service role is causally visible.

Do not repair a failed reverse test by adding “I was professional” or a customer compliment. Restore the actual action, its immediate consequence, and its boundary.

## Three decisions

- `approved_for_voice_pipeline`: every required gate passes and the exact body may enter voice rewriting.
- `return_for_revision`: one or more gates need revision; return to the story spine or fact card.
- `blocked_from_downstream`: evidence, distribution, authorization, privacy, medical, or insurance risk is unresolved; stop.

Approval binds both the exact stable-body SHA-256 and the exact fact-card artifact reference. Any body or fact-card revision change invalidates the receipt and requires a new review.

## Relationship to later tools

- `dbs-content` diagnoses clarity after the structure is viable; it is not the structure owner.
- `dbs-ai-check` identifies AI-like language; it cannot restore evidence or service causality.
- `human-voice-editor` changes wording only after approval.
- `dbs-hook` runs after the rewritten body is read aloud and author-confirmed; it cannot add facts or repair a weak body.
- Final high-risk review still checks the finished script, evidence, distribution route, authorization, media rights, and manual publication boundary.

For serious short video, passing the eleven gates is necessary but not sufficient for attention readiness. The same frozen body must also pass `serious-content-translation-review.v1`: protagonist goal or reader task visible, concrete stakes visible, scene/dialogue/direct utility preserved, information progression present, completion payoff present, takeaway or next use present, and service causality fitting the target action. Failure returns to story/angle design rather than wording polish.

## Minimum review record

Use `case-video-initial-draft-review.v1` and `scripts/initial_draft_quality_gate.py`. Record draft identity, stable-body hash, fact-card artifact reference, content goal, every exact gate and check ID, findings, remediation, evidence, reviewer, review time, one of the three decisions, and `publication_boundary: manual-only`.

## Boundaries

Passing this gate authorizes only the next local editorial stage. It does not prove clinical truth, insurance eligibility, claim outcome, publication authorization, distribution compliance approval, real usage, upload authority, or account action authority.

## Update record

### 2026-11-02 20:20:00 +08:00 | Codex (gpt-6.1-sol)

- New CLI reviews require `--structure-route story-arc|direct-answer`. A story review also supplies `--story-card <current-card.json>` and maps every planned element to actual current sentences in `story_realization`; see [story-design.md](story-design.md) and [the workflow guide](../../../self-media-creation-system/docs/story-realization-review.md).
- Voice rewriting requires a fresh map in `semantic_review.story_realization` against the rewritten body. Missing, stale or unanchored evidence returns for revision. Dialogue may be inapplicable with a reason; mandatory story elements cannot be skipped.
- Managed validation checks exact fact-card/schema/validator/matcher pins in `contract-binding.json`; a missing or drifted pin blocks. This checks versions and declared evidence, not semantic truth or audience effect.

### 2026-08-24 23:30:00 +08:00 | Codex (GPT-5.6 Sol)

- Intent: keep human-readable Storycraft guidance identical to the current machine gate.
- Decision: document all eleven exact gate IDs and add the missing distribution-compliance gate.
- Reason: a ten-gate guide allowed smaller agents to omit a mandatory machine field.
- Evidence: bound Content Studio Schema and validator.
- Effective scope: post-Storycraft pre-voice reviews.
- Rollback: restore the old ten-gate guide only as historical provenance, never as executable guidance.
