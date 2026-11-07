# ADR: serious-content translation as a thin review gate

- Status: accepted and promoted through the registered canonical route
- Date: 2026-09-03
- Owner: content-creation-self-media

## Context

The existing system already owns evidence, privacy, human voice, packaging, platform adaptation, and manual publication. The new method adds audience relevance, entry mechanism, sensitivity-aware humor, analogy boundaries, information progression, and misinterpretation review. The original `story-suspense` label was too permissive: an Agent could delay both the answer and the reason to keep watching, causing avoidable opening drop-off.

## Decision

Implement one deterministic, hash-bound `serious-content-translation-review.v1` receipt inside `self-media-creation-system`. The receipt binds a frozen body and records both precreative and postcreative review evidence. It remains `candidate-only`, `review-required`, and `manual-only`.

For narrative cases, replace `story-suspense` with `result-preview-story-reveal`. The first two seconds must contain a real watch reason while withholding only the complete central answer. The central judgment emerges near the story close, followed by a short explanation and boundary.

The same receipt also keeps attention and integrity as independent dimensions. Integrity remains a hard gate. Attention can only return a draft for revision and can never compensate for unsupported facts, privacy failures, or medical/insurance overreach. Each plan records a portfolio role, real tension or direct utility, viewer stakes, central judgment, explanation budget, and a fine-grained sensitivity profile. Severe illness, customer loss, privacy-high-risk, and compound-high-sensitivity profiles default to no humor. Any fun in the frozen draft must be related to the core question, safe in its target, removable without collapsing the core value, and secondary to the intended judgment or action in audience recall.

The gate is included in the repository-wide contract checker. It does not replace the canonical content item, fact card, human-voice gate, packaging receipt, compliance review, or publication workflow.

## Alternatives considered

1. Add all fields directly to the canonical content-item schema. Rejected for this increment because it would require coordinated consumer migration and contract-set promotion.
2. Create a separate content generator or state machine. Rejected because it duplicates existing owners and increases operational complexity.
3. Keep the method as documentation only. Rejected because weak Agents could silently skip the rules.

## Consequences

- Positive: rules are deterministic, fixture-tested, hash-bound, and discoverable through the unified check.
- Trade-off: callers must now supply explicit sensitivity and fun-integrity fields; older receipts are historical and cannot be reused after a material script change.
- Failure mode: a caller may still misdeclare the content analysis, so human subject-matter review remains required; the deterministic gate does not authorize publication.

## Promotion status

The registered route invokes this gate conditionally for insurance, health, high-risk, and explicitly declared serious professional content. Consumers bind versioned contracts and content hashes rather than a repository commit.

## Revision record — 2026-09-03 17:31:30 +08:00 | Codex (GPT-5.6 Sol)

- Intent: promote relevance and sensitivity rules from prose guidance into the existing thin review gate.
- Decision: extend the same receipt rather than create another writing engine; add deterministic negative cases for unsafe sensitivity/humor combinations and decorative or gag-first fun.
- Reason: one authoritative gate is easier for weak agents to discover and harder to bypass than several advisory checklists.
- Evidence: updated schema, validator, synthetic fixtures, focused tests, and registered routing contract 1.6.0.
- Effective scope: new or materially revised serious-content candidates; previous artifacts remain historical.
- Rollback: revert the receipt extension, tests, route binding, and documentation as one atomic change.

## Rollback

Remove the new schema, script, synthetic fixture, tests, quality-gate entries, unified-check hook, and documentation. Existing routes and receipts remain valid because no canonical schema was changed.
