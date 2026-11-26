# Story Design

## Current draft realization gate (2026-11-02 20:20:00 +08:00, Codex gpt-6.1-sol)

For managed prerecording stories, read [the existing workflow's sentence review](../../../self-media-creation-system/docs/story-realization-review.md). Keep `structure_route=story-arc` on the script and add the actual `story-design-card` to the context manifest. The initial review's `story_realization` maps every planned goal, event, choice, turn and emotion cue to current spoken spans and shared fact IDs. Missing material returns for revision; it never authorizes invented dialogue. Recheck the rewritten body in `semantic_review.story_realization`, using the same current card. Evidence completeness is not proof of the editor's judgment or audience response.

## What a story is

A story is not a chronology, a case summary, or an explanation with a client at the beginning. It is a causal sequence in which:

1. someone wants a concrete result;
2. an event disrupts the prior state;
3. reality creates a gap between expectation and result;
4. pressure narrows the available choices;
5. a choice, revelation, reversal, or consequence changes the value state;
6. the ending establishes a new state while leaving honest uncertainty visible.

Use `story-arc` only when these elements exist. A checklist, definition, direct answer, or mechanism explanation should keep its own route instead of being forced into a story.

## Mandatory story-design card

Before drafting any `story-arc`, create and pass `story-design-card.v1` through:

```text
self-media-creation-system/scripts/story_design_gate.py
```

The card binds every factual beat to the locked fact card. Missing, unsupported, or drifted facts block drafting. It records:

- protagonist and immediate goal;
- source mode, authorization, identity treatment, and quotation treatment;
- story category and the selected format profile;
- one fact-bound scene anchor;
- inciting incident;
- expectation/reality gap;
- first action and the real feedback it received;
- pressure and real alternatives;
- choice and tradeoff;
- a format-fit number of turning points;
- climax or revelation as a value change;
- resolution and remaining uncertainty;
- emotional beats and their evidence mode;
- the short explanation and boundary that follow the story.

Turn counts are format-aware. A short video or Moments micro-story may use one to three truthful turns and should carry one central change. Longform may use up to six turns when each one changes meaning. Do not add a second turn merely to satisfy a template.

The card also records advisory editorial diagnostics. `causal_link_status` checks whether the sequence is causally connected rather than merely chronological. The six stickiness dimensions translate `Simple, Unexpected, Concrete, Credible, Emotional, Stories` into visible review states. `causal_trim_status` asks whether removable material was tested without prescribing a fixed deletion percentage. These diagnostics may warn; they do not override factual, privacy, authorization, or professional-risk gates.

## Scene and beat test

Every beat must do at least one job: increase or redirect pressure; reveal a choice; change what the audience understands; change the value state; or deliver a consequence. If a beat only repeats background, remove it or move it to the explanation.

## Pressure-choice test

Character is shown through action under pressure, not through labels such as “professional”, “responsible”, or “anxious”. Record what the person wanted, what blocked the easy route, which real alternatives existed, what was chosen, what it cost or left unresolved, and which fact or authorized quote proves it.

If removing the creator's action does not change the process or result, service causality fails. If there is pressure but no consequential choice, the material may be a process explanation rather than a story.

## Turning points and value shifts

A turning point must change meaning, direction, or stakes. Use small truthful shifts in insurance and health stories:

- “ready to buy” → “first clarify the current situation”;
- “waiting for reimbursement” → “knowing the next claim step”;
- “documents scattered” → “a reviewable inventory”;
- “assuming treatment ended the work” → “seeing that preparation began earlier”.

Do not inflate a routine step into rescue, transformation, or guaranteed relief.

## Short-video story reveal

Story reveal does not mean withholding all value. For short video:

1. within two seconds, preview a concrete result, number, choice conflict, or decisive scene;
2. do not reveal the complete judgment yet;
3. progress through causal beats rather than background exposition;
4. let the central judgment emerge near the story close;
5. follow with two to four sentences of explanation and boundary.

This preserves the existing attention gate while avoiding empty suspense.

Story validity is not the same as distribution readiness. A causal story can still feel flat when it begins as a case summary, hides what the person wants, contains no concrete cost, or resolves no question opened for the viewer. Before drafting a serious short video, the registered serious-content translation precheck must also record:

- the protagonist's immediate goal or the reader's concrete task;
- one scene, line, number, choice, or consequence that can be delivered immediately;
- the concrete cost, delay, blockage, or tradeoff at stake;
- at least three information advances for a story-reveal route;
- the question opened for completion and the later payoff;
- the takeaway or next use;
- for consultation or conversion content, the creator's service action and its immediate process effect.

Do not average these dimensions into a score. If the opening, progression, payoff, or required service causality is missing, return to the story spine.

## Format-specific checks

- `short-video-narration` and `moments-short-text`: one central change and one to three turning points.
- `longform-article`: explicitly plan alternation between scene and understanding.
- `interview-video`: use `authorized-interview`, confirm authorization, and separate the action layer from the meaning layer.
- every format: the item must make sense without another episode; series numbering is not a substitute for context.

These are machine-checked by `story_design_gate.py`. The prose adapter may still choose rhythm, exact sequence, and emphasis within those boundaries.

## Ending test

The climax is the most meaningful action or revelation, not a slogan. The resolution states what is different now, what remains unknown, what the story can illustrate, and what it cannot prove. Do not replace resolution with a universal moral, hard CTA, or product promise.

## Publication learning plan

Before release review, choose at most one story variable to observe: opening speed, protagonist desire, unexpected feedback, pressure choice, ending value shift, title promise, or whether comments recall the story versus only the point. Bind it to the existing early 48–72 hour and day-7 performance snapshots. These are content signals and candidate explanations only; a single item cannot establish causality or create a customer/business conclusion.

## Update record

### 2026-09-03 19:12:00 +08:00 | Codex (GPT-5.6 Sol)

- Added evidence-bound source handling, scene anchors, action-feedback gaps, format-specific turning-point bounds, interview layers, and advisory craft diagnostics.

### 2026-09-03 16:30:05 +08:00 | Codex (GPT-5.6 Sol)

- Added a distribution-readiness bridge to the existing serious-content translation gate so a structurally valid story cannot pass merely as a complete case summary.
