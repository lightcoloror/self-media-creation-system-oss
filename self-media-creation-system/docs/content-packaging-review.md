# Frozen-body content packaging review

Updated: 2026-08-27 10:10:40 +08:00
Acting tool/model: Codex (GPT-5.6 Sol)

## Purpose

`content-packaging-review.v1` is a thin evidence receipt for one reviewed
combination of:

- frozen body bytes;
- `content_id` and platform;
- title;
- cover brief;
- opening text hash;
- a structured standalone-item review bound to the frozen opening and body.

The receipt also binds the repository-relative reviewed-input JSON and its real
SHA-256. This keeps the opening hash verifiable without copying the opening
text into the receipt.

It does not introduce another content state machine. It does not publish,
schedule, send, call a provider, or authorize execution. Every generated
artifact remains `candidate-only` and `manual-only`.

## Order of operations

1. Freeze the body artifact and calculate its real SHA-256.
2. Finalize the proposed title, cover brief, and opening.
3. Record the audience question, necessary context, core answer, and current
   item's payoff as anchors from the frozen title/opening/body. Confirm that neither
   a prior item nor a future item is required to understand that payoff.
4. Choose one reviewed audience-entry strategy. Confirm that title, cover, and
   opening make the same promise, and bind the applicable distinct information
   advances in their real content order. For insurance, explicitly choose
   `life-context-first` or `search-intent-direct`; do not force one route onto
   every task.
5. A human reviews that exact package and its data classification. The existing
   human-review credential records its scope hash, reviewer, review time,
   decision, and false authority flags.
6. For `deidentified-operational`, a separate privacy-review credential must
   cover that exact package. `synthetic-only` uses `privacy_review: null`.
7. Create and validate the packaging receipt.

Changing any body byte, title, cover field, or opening invalidates the scope.
The package must be reviewed again; an old receipt cannot be carried forward.

## Batch editing and staggered release

Batch production and release are separate decisions. It is valid to script,
shoot, and fully edit an entire series in one batch. The workflow does not
require later items to remain as rough cuts.

Each completed video is frozen as its own body artifact. Before its manual
release, review that video's exact title, cover, and opening against the current
body hash. Normal feedback from an earlier item may change the later item's
title, cover, or opening package without reopening the whole edit. Re-edit the
finished video only when the feedback reveals a factual, privacy, compliance,
or material comprehension problem; a changed body then receives a new hash and
a new packaging review.

Every series item must be packaged as a standalone promise and deliverable. The
reviewed input must identify four non-empty text anchors that really occur in the
frozen title/opening/body: the audience question, necessary context, core answer, and
the current item's payoff. Both `prior_item_required` and
`future_item_required_for_payoff` must be `false`. Phrases that explicitly make
understanding depend on a previous item or withhold the answer until a later
item fail closed.

Audience-facing titles and covers may contain sequence labels such as
`第1集`, `第二期`, `EP03`, `Episode 3`, or `Part 3`. A number alone does not
establish dependency. A shared series name is
also allowed. Explicit withholding of the promised answer remains invalid in
this standalone-item adapter. This is not a ban on ordered teaching steps such as
`第1步` inside one standalone topic. It is also acceptable to mention a separate
future topic after this item has already delivered its own answer and payoff.

## Appeal, engagement, and satisfaction mapping

The gate does not guess a platform score. It makes the audience path reviewable:

- **Appeal:** `audience_question` plus one `entry_strategy` (`life-problem`,
  `choice-conflict`, `counterintuitive-result`, `specific-loss`,
  `specific-number`, `identity-situation`, `search-intent`, or
  `other-reviewed`), with `title_cover_opening_same_promise: true`.
- **Engagement:** `progression_excerpts` binds one or more distinct advances in
  the order they occur. More cuts do not substitute for new information.
- **Satisfaction:** `core_answer_excerpt`, `payoff_excerpt`, and
  `current_item_payoff_delivered: true` prove that this item answers its own
  promise. Facts, privacy, medical/insurance boundaries, and voice remain in
  their existing quality gates.

`insurance_entry_mode` records the actual choice. Broad-discovery content may
use `life-context-first`; a genuine search-intent answer may use
`search-intent-direct`. The system does not blindly delay the word “insurance”.

## Position in the existing pipeline

1. **Topic and research:** choose the audience problem and entry strategy as an
   operating hypothesis. Verified claims and unknowns still come from the
   existing research/evidence owner.
2. **Draft and voice:** write the real information advances, then complete the
   existing human-voice gate. A body change invalidates downstream packaging.
3. **Packaging:** freeze the body and run this review. `xhs-evidence-graphic`
   and `case-video-candidate` cannot hand off production while this receipt is
   missing or stale.
4. **Production and release:** render against the reviewed promise; publication
   remains manual-only. A title, cover, opening, or body change requires a new
   exact-package review.
5. **Observation:** use the existing 48–72 hour and day-7 operations snapshots.
   Attraction, consumption, value, negative feedback, and business signals stay
   separate; `content_no_signal` remains neutral.

## Stable CLI

From the repository root:

```powershell
python scripts/content_packaging_review.py create `
  --input fixtures/content-packaging-review-v1/synthetic.input.json `
  --output tests/.runtime/content-packaging-review/manual-receipt.json

python scripts/content_packaging_review.py validate `
  --receipt tests/.runtime/content-packaging-review/manual-receipt.json

python scripts/content_packaging_review.py check
```

`check` is offline, runs both `synthetic-only` and synthetic
`deidentified-operational` fixtures, writes no receipt, and proves byte-stable
repeated creation for both classifications.

`create` writes only below `.runtime/content-packaging-review` or
`tests/.runtime/content-packaging-review`. It cannot overwrite a body or review
credential. An identical existing receipt is accepted idempotently; different
existing bytes block instead of being overwritten. CLI output reports only a
repository-relative receipt ref. Move a human-accepted candidate elsewhere only through the
separate manual handoff that owns that destination.

If a process crash leaves a partial runtime receipt, validation and the next
create attempt fail closed. After verifying the exact repository-local runtime
path, remove that one partial candidate manually and rerun `create`; never relax
ACLs or overwrite it in place.

## Credential contract

The adapter consumes credentials; it does not mint approval. A human-review
credential has these exact fields:

```json
{
  "schema_version": "content-packaging-human-review-credential.v1",
  "reviewer": "human reviewer reference",
  "reviewed_at": "2026-08-24T11:00:00+08:00",
  "decision": "approved",
  "review_scope_sha256": "<exact package scope>",
  "authority": {
    "publish_authorized": false,
    "execution_authorized": false,
    "external_send_authorized": false
  }
}
```

The input must bind that credential by repository-relative ref, real file
SHA-256, reviewer, and review time. `deidentified-operational` additionally
requires the analogous
`content-packaging-privacy-review-credential.v1` with `decision: passed` and
`privacy_scope_sha256`.

## Fail-closed boundaries

Creation or validation blocks on:

- missing, absolute, escaping, sensitive, or stale artifact refs;
- a body hash that does not match current bytes;
- a title, cover, opening, content ID, platform, or body that differs from the
  reviewed scope;
- an audience-facing title or cover that explicitly withholds this item's
  payoff until another item (an episode number alone is allowed);
- a missing standalone audience question, context, core-answer, or payoff
  text anchor, or an anchor that is absent from the frozen title/opening/body;
- no reviewed audience-entry strategy, a title/cover/opening promise mismatch,
  no ordered information advance, overlapping anchors, or a missing current-item payoff;
- `prior_item_required: true`, `future_item_required_for_payoff: true`, or copy
  that explicitly depends on an earlier item or withholds this item's payoff;
- a changed reviewed-input JSON, or a data-classification downgrade;
- missing, changed, rejected, or metadata-drifted human credentials;
- missing or drifted privacy credentials for operational material;
- unknown fields at any validated contract layer;
- credential-shaped secrets (including common AWS, Slack, GitHub/GitLab and
  bearer forms) or Windows/POSIX local absolute paths;
- receipt, title, cover, standalone-review, credential, or scope hash drift;
- any attempt to grant publishing, execution, or external-send authority.

The receipt intentionally stores the opening hash rather than the opening text.
It preserves the exact approval binding while avoiding another copy of the
content. The original reviewed opening remains in the hash-bound reviewed
input; changing that input invalidates the receipt.

The credential proves local file integrity and reviewed-scope consistency. It
is not cryptographic proof of a human identity. Cross-trust-domain use would
need a separate human-controlled approval ledger, signature, or trusted reviewer
registry; none is created here.

## Change rationale

### 2026-11-05 applicability correction

Intent: remove arbitrary numbering/count restrictions without adding gates.
Decision: allow numbered items and one or more ordered, non-overlapping anchors;
retain explicit withheld-payoff detection. Answers/payoffs must occur in the
opening/body, not exclusively in the title. Reason: counts and numbering do not
establish quality. Evidence: `test_audience_semantic_boundaries.py` and existing
packaging regressions. Scope: current runtime adapter, not historical receipts.
Validation reports structural_binding_only and explicitly denies proof of
editorial quality or conversion. A vacuous but complete record may still be
structurally valid: actual meaning remains the existing editorial review's job.
Atmospheric Vlogs do not need this answer-oriented adapter or an acquisition CTA.
Author: Codex; exact runtime model not independently verified.

- **Intent:** make title-cover-opening review invalid as soon as frozen body or
  packaging changes, and turn standalone series consumption into an executable
  gate rather than a writing reminder.
- **Decision:** add one receipt schema and a local validator/creator, without a
  workflow or publishing state machine; allow full-batch editing while blocking
  episode-number labels and previous/next-item dependencies.
- **Reason:** packaging is an approval artifact, not execution authority.
- **Evidence:** real body and reviewed-input SHA-256, four anchors and ordered
  information advances bound to the frozen content, promise-alignment and
  payoff flags, explicit false dependency flags, human credential SHA-256,
  classification-aware review scope, mandatory privacy scope for operational
  material, and deterministic receipt hash.
- **Effective scope:** local candidate preparation plus the existing
  `xhs-evidence-graphic` and `case-video-candidate` post-body-freeze review
  gates.
- **Rollback:** revert the packaging schema/script/fixtures/tests/docs together
  with the XHS recipe, Agent discovery, and repository manifest entries. No
  domain state machine or publishing authority was added.
