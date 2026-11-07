# Serious-content translation gate

This thin gate implements the broad-audience translation rules for serious insurance, medical, and financial content. It does not create another content state machine.

## Position in the route

```text
audience question and decision
-> precreative evidence/privacy/risk gate
-> sensitivity profile and humor default
-> entry mechanism and information progression
-> draft and human-voice rewrite
-> frozen body and post-freeze hook
-> postcreative misinterpretation/safety gate
-> fun-integrity review
-> existing content-packaging review
-> existing human/institution review
-> manual publication
```

The output remains `candidate-only / review-required / manual-only`.

The frozen Markdown body uses a SHA-256 over UTF-8 text with CRLF/CR normalized to LF. This keeps the same reviewed text stable across Windows, archives, and Linux clones; no other characters are normalized.

## Story reveal route

The former slow `story-suspense` route is retired. Use `result-preview-story-reveal`:

```text
title/cover promise
-> a real result glimpse, number, conflict, question, or decisive scene within two seconds
-> story progression without stating the full answer
-> central judgment emerges near the story close
-> two to four explanation sentences with the necessary boundary
```

The opening gives a reason to keep watching but must not disclose the complete answer. Empty suspense, “watch until the end”, a delayed context dump, or a body that does not fulfill the opening fails closed. Other entry mechanisms keep `story_reveal_contract: null`.

## Attention and integrity are independent

Every serious-content plan records one portfolio role (`growth`, `trust`, `tool`, or `professional`), the viewer stakes, one central judgment, and an explanation budget. Growth and trust pieces additionally require a real, evidence-backed tension; a tool or professional piece may instead enter through direct utility.

The plan must also state the protagonist's immediate goal or the reader's concrete task, one scene/dialogue anchor, the completion question and payoff, a takeaway or next use, and the intended audience action. Consultation or conversion content must name one concrete service action and its immediate effect. The gate rejects a one-line “hook plus answer” story route: `result-preview-story-reveal` needs at least three distinct information advances.

The post-draft review has two independent dimensions:

- Integrity is a hard gate: evidence, privacy, causality, medical/insurance boundaries, and non-generalization must pass.
- Attention is a revision gate: immediate relevance, a concrete watch reason, visible goal/task, concrete stakes, a preserved scene/dialogue/direct-utility anchor, progression, completion payoff, reusable value, service causality when applicable, a clear judgment, explanation-budget compliance, and title/cover/opening alignment must pass before the candidate moves on.

These dimensions are never averaged. Strong attention cannot compensate for an integrity failure; strong integrity does not excuse an opening that gives the audience no reason to continue.

## Sensitivity and fun integrity

The broad `risk_class` is supplemented by a content-specific `sensitivity_profile`: ordinary, professional-sensitive, medical-sensitive, affected-person severe illness, customer loss, privacy high-risk, or compound high-sensitivity. Severe illness, loss, privacy, and compound cases default to no humor. Light humor needs a recorded human-approved exception and must never target the affected person; moderate and experimental humor are blocked.

When fun is present, the frozen draft must classify it as related, decorative, or misleading. Only related fun may pass. The review separately checks that it helps answer the core question, has a safe target, leaves the factual and service value intact when removed, and does not make the gag the primary memory target. These are hard revision conditions, not advisory scores.

## Why these checks are structural

These fields are not a “viral score”. They block recurring failure modes that ordinary copy polishing cannot repair:

- a complete case summary with no immediate scene;
- a list of events that never shows what the person is trying to accomplish;
- abstract “pressure” without a concrete cost or blocked next step;
- an opening question that is never paid off;
- customer distress standing in for the creator's actual service action;
- a useful conclusion with no clear save, share, discussion, or consultation use.

If one of these is missing, revise the angle, story spine, or information order. Do not add emotional adjectives, exaggerate medical/insurance risk, or hide facts merely to create suspense.

## Change rationale — 2026-09-03 16:30:05 +08:00

- Intent: make propagation tension and emotional resonance executable without weakening evidence or compliance controls.
- Decision: extend the existing serious-content review rather than add a new state machine; require goal/task, scene/dialogue, completion loop, takeaway, target action, and conditional acquisition service causality in both planning and post-draft review.
- Reason: the proton-treatment redesign passed causal story checks but still read as a complete case summary and delayed the most meaningful service actions.
- Evidence: the user-reviewed twelve-dimension diagnosis, existing Storycraft fact-bound story design, and the current attention/integrity split.
- Effective scope: serious insurance, health, high-risk, and declared professional candidates; previous receipts remain historical and must be rerun before reuse after a script change.
- Rollback: remove the added fields, validator rules, tests, documentation, and route gate names as one change set.

## Change rationale — 2026-09-03 17:31:30 +08:00

- Intent: close the remaining gap between safe humor and relevant, trust-preserving fun.
- Decision: add a seven-value sensitivity profile, near-zero-humor defaults, explicit light-humor exceptions, and a four-part frozen-draft fun-integrity review.
- Reason: checking only the humor target could still admit irrelevant decoration, fun-dependent explanations, or a memorable gag that displaced the professional judgment.
- Evidence: the user-approved gap audit and the method note `专业严肃内容的趣味化与信任平衡-2026-09-02.md`.
- Effective scope: serious professional, insurance, health, severe-illness, customer-loss, and privacy-sensitive candidate content.
- Rollback: remove the new schema fields, validator branches, fixtures, tests, quality-gate names, and Storycraft binding together.

## Stable command

```text
python scripts/serious_content_translation_gate.py check
python scripts/serious_content_translation_gate.py create --input fixtures/serious-content-translation-v1/synthetic.input.json --output .runtime/serious-content-translation/review.json
python scripts/serious_content_translation_gate.py validate --receipt .runtime/serious-content-translation/review.json
```

## Decisions

- Intent: turn the Obsidian method into deterministic routing evidence.
- Decision: add one thin hash-bound review receipt instead of a writing engine or state machine.
- Reason: existing fact, human-voice, packaging, privacy, compliance, and publication owners remain authoritative.
- Evidence: `专业严肃内容的趣味化与信任平衡-2026-09-02.md` and the existing `content-packaging-review` contract.
- Effective scope: candidate content review only; no provider call, publication, external send, or compliance approval.
- Rollback: remove this gate's schema, script, fixtures, tests, route references, and unified-check hook.
