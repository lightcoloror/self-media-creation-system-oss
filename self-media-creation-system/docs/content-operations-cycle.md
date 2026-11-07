# Daily content operations cycle

Metadata: Codex (GPT-5.6 Sol), 2026-08-27 09:06:51 +08:00.

Update: Codex (GPT-5.6 Sol), 2026-08-28 13:20:16 +08:00 — added fixed,
manual-only publication change recording and delete/repost lineage checks.

## Outcome

`scripts/content_operations_cycle.py` is a thin, manual-entry adapter between a
real-world content publication and the existing self-media operating contracts.
It records what a human says happened; it never visits a platform, publishes,
contacts anyone, writes CRM, or invokes a provider.

Agent discovery is now explicit. Whenever a human reports an actual publication,
platform metrics, a platform diagnostic, or a deidentified interaction/business
event, run `python scripts/self_media_agent.py operations` first. The result points
back to these fixed commands and distinguishes direct event recording from the
later `publication_feedback_review` workflow. This prevents real observations
from remaining only in chat because the Agent found the retrospective route but
not the recorder.

The adapter does **not** define another content state machine or another set of
schemas. It reuses:

- `scripts/publication_feedback_tracker.py` for stable IDs, early/day-seven
  windows, privacy key rejection, metric-layer mapping, timestamps, and hashes;
- the workspace `operations-contract-set.v1.json` atomic manifest and its 14
  canonical schemas;
- the workspace `validate-content-operations.py` privacy and cross-object
  semantics, including publication/snapshot windows, lead continuity, six-layer
  review, and business-signal isolation.

## Fixed commands

```text
record-publication --store <private-store> --input <json>
record-publication-edit    --store <private-store> --input <json>
record-publication-delete  --store <private-store> --input <json>
record-publication-restore --store <private-store> --input <json>
record-snapshot    --store <private-store> --input <early-or-d7-json>
record-interaction --store <private-store> --input <json>
review-lead        --store <private-store> --input <confirm-or-reject-json>
record-experiment  --store <private-store> --input <json>
record-diagnostic  --store <private-store> --input <json>
record-resource    --store <private-store> --input <json>
record-revenue     --store <private-store> --input <json>
record-continuity  --store <private-store> --input <json>
record-security    --store <private-store> --input <json>
build-review       --store <private-store> --input <json>
validate-store     --store <private-store>
rebuild-heads      --store <private-store>
demo               --store <synthetic-store>
check
```

Examples:

```powershell
python scripts/content_operations_cycle.py check
python scripts/content_operations_cycle.py demo `
  --store tests/.runtime/content-operations/manual-demo
python scripts/content_operations_cycle.py record-publication `
  --store .runtime/content-operations/my-private-store `
  --input fixtures/content-operations-cycle-v1/record-publication.input.json
python scripts/content_operations_cycle.py validate-store `
  --store .runtime/content-operations/my-private-store
```

Inputs use exact, versioned field sets. There is no raw command envelope and no
free-form operation selector. The edit/delete/restore event type is fixed by
the selected subcommand and cannot be supplied or changed in the input. This
keeps the writable surface small. An Agent
capsule should initially expose only `build-review` followed by a human gate;
record/rebuild/validate operations remain explicit CLI actions until a governed
operation-selector contract exists.

## Journal and transaction model

The store is deliberately simple:

```text
<store>/
  store-metadata.json             # classification + atomic contract-set sentinel
  store-anchor.json               # in-store count/tail/chain projection
  journal/00000001-op_....json  # immutable operation facts
  heads/publication-events.json
  heads/performance-snapshots.json
  heads/interaction-events.json
  heads/lead-events.json
  heads/experiment-runs.json
  heads/diagnostic-runs.json
  heads/resource-ledger-events.json
  heads/revenue-attribution-events.json
  heads/account-continuity-plans.json
  heads/account-security-events.json
  heads/operating-reviews.json
  heads/source-context.json
  heads/manifest.json

<store-parent>/.<store-name>.control/
  anchor-journal.jsonl            # append-only monotonic checkpoint outside swap domain
```

Stores are accepted only below `.runtime/content-operations/` or
`tests/.runtime/content-operations/`; those two roots themselves, existing
non-store directories, and symlink/junction paths are rejected. Each journal
record carries a full-record hash, previous-record hash, data classification,
and the canonical atomic contract-set identity/hash. Replaying the identical payload returns
`already_recorded`; reusing that identity with a different payload returns
`operation_conflict`. A write is assembled in a sibling staging directory,
validated against the entire journal and canonical cross-object rules, then
swapped into place. A failed validation deletes staging and leaves the previous
store byte-for-byte unchanged.

Heads are derived cache files. `rebuild-heads` regenerates them from the
append-only journal without rewriting either anchor. The external checkpoint
records every committed count/tail/chain and links each entry to the previous
checkpoint hash; it is never copied into or rewritten with the swappable store.
Deleting a journal tail and recomputing the in-store anchor therefore still
fails against the external monotonic checkpoint. Rebuild cannot repair a
changed/deleted journal record: anchor, chain, record/payload hash, identity,
contract-set, classification, sequence, or authority drift remains fail-closed.

The external checkpoint protects against accidental deletion and same-store
rewrites. It is not a cryptographic identity or WORM system: an attacker who
can rewrite both the private store and its sibling control directory can still
forge local history. Cross-trust use requires a signed/HMAC or independently
retained checkpoint ledger.

## Daily sequence

1. After a human publication, run `record-publication` with a stable local key,
   manual timestamp, account/topic/content references, and their current hashes.
   The adapter stores no platform token or customer text.
   If the human later reports a platform-side change, use exactly one matching
   fixed command:
   - `record-publication-edit` appends an `edited` event and a newly frozen
     version;
   - `record-publication-delete` appends a `deleted` event;
   - `record-publication-restore` appends a `restored` event only from a deleted,
     hidden, or restricted state.
   Every input names the exact latest source event. Event sequence, identity,
   supersession, source publication, timestamps, and transition are validated;
   an edit cannot be relabelled as a delete by adding an `event_type` field.
   For delete-and-repost, first append `deleted` to the old publication. Then
   call `record-publication` with a new stable `publication_key` and
   `replaces_deleted_event_id` equal to that terminal deleted event. The result
   is an old-publication `deleted` event plus a new-publication `published`
   event linked through `supersedes_event_id`.
2. At 48–72 hours, run `record-snapshot` with `window_label=early`.
3. At day seven (156–180 hours), run `record-snapshot` with
   `window_label=d7`. The two windows are distinct identities and cannot
   overwrite one another.
   Metrics reported before 48 hours are provisional observations. Do not rename
   a 12-hour or 24-hour observation to `early`; record the publication event,
   report the next eligible window, and retain any still-missing governed input
   as an explicit gap rather than inventing it.
4. Record a deidentified observation with `record-interaction`:
   - `content-observation`: content evidence only;
   - `no-signal`: `observe-only`, meaning evidence is insufficient;
   - `business-candidate`: pending human review only.
5. Use `review-lead` only for a pending business candidate. `confirm` requires
   explicit consent status, attribution type/model, reviewer, evidence,
   receipt reference and receipt SHA-256. The referenced credential must be a
   real repository-private JSON artifact whose bytes, reviewer, time, decision,
   operation, scope hash, and non-execution authority all match. It atomically
   changes the interaction to `promoted` and creates exactly one canonical lead;
   `reject` changes it to `rejected` and creates no lead. The human review
   receipt is evidence for the decision; the downstream handoff receipt stays
   `null` and `not-started` until a separate human workflow acts.
6. Use one fixed record command per existing canonical operating object when
   that evidence actually exists: experiment pre-registration, diagnostic run,
   time/cost record, human-confirmed revenue attribution, continuity plan, or
   security review. These commands append canonical objects; they do not run an
   experiment, diagnose an account automatically, spend money, rotate a
   credential, contact a customer, write CRM, or act on an account.
   `record-revenue` and any `human-reviewed` diagnostic additionally require an
   actual repository-private decision credential bound to the exact artifact
   hash and false authority flags.
7. Run `build-review` after the weekly/monthly period ends. It creates a
   canonical `operating-review` with six layers and `review_state=draft-only`.
   The input must carry the current journal source checkpoint. Late-arriving
   data makes an older request fail with `source_head_drift`; rebuilding then
   requires an explicit new revision/checkpoint. Events recorded after the
   review's `created_at` are not absorbed.

## Signal and lead boundaries

Only these canonical business events are eligible for human confirmation:

- `continued_consultation`
- `necessary_documents_provided`
- `next_step_booked`

Confirmation requires a non-empty human `reviewer_ref`, `receipt_ref`,
`receipt_sha256`, explicit consent/attribution fields, and evidence that
intersects the source interaction. It does not authorize contact,
execution, publication, CRM write, or a claim about causation. Likes, views,
saves, shares, questions, and silence remain content observations.

`content_no_signal` is represented by a `no-signal` interaction. In the review,
missing observations remain `insufficient-evidence`; they do not mean a topic
failed or a customer is negative. The business layer is `observed` only when a
canonical lead or human-confirmed revenue input exists. Revenue attribution is
always a count in the review, never proof that content caused revenue; amount
may remain withheld and `causal_claim` is always false.

## Privacy and source integrity

- Publication source objects are existing account/topic/content artifacts,
  referenced by repository-relative path and byte SHA-256.
- The machine gate rejects prohibited raw fields and obvious URLs, email/mobile/
  ID-number patterns, and absolute local paths. It **does not claim to detect
  arbitrary health details, policy/contract facts, or every indirect identifier**.
- Interaction text must be a short deidentified summary; real operational data
  belongs only in a private runtime store, never fixtures or Git.
- Every `deidentified-operational` input therefore requires a human
  `privacy_review` credential with reviewer/ref/hash/time and a scope hash bound
  to that exact input. The adapter resolves and hashes the actual credential
  file and rejects execution/publication/contact/CRM authority. A missing file,
  zero/fabricated hash, post-review edit, or authority escalation fails closed.
- One store has one data classification and one current atomic contract set;
  mixing or downgrading either is rejected.
- All committed examples are `synthetic-only` and use no platform, customer,
  product, provider, or CRM data.

## Validation and recovery

```powershell
python -B -m unittest discover -s tests -p test_content_operations_cycle.py -v
python -B -m unittest discover -s tests -p test_publication_feedback_tracker.py -v
python scripts/content_operations_cycle.py check
python ../scripts/validate-content-operations.py
```

Recovery:

1. Stop issuing record commands for the affected store.
2. Run `validate-store`.
3. If the error is `head_drift`, run `rebuild-heads`, then validate again.
4. If internal/external anchor, journal chain/record/payload hash, classification, contract set,
   identity, sequence, or authority drift is reported,
   preserve the store for audit and restore from a trusted backup. Do not edit
   the journal in place.
5. A lone strictly valid backup/staging candidate can be recovered. Store+
   backup coexistence, multiple candidates, or any corrupt candidate is
   preserved and fails closed as ambiguous; a good backup is never deleted
   before validation. The global system temp directory and ACLs are never changed.

## Change rationale

### Intent

Close the operational gap between manual publishing and evidence-safe weekly
review without introducing platform automation or customer/CRM inference.

### Decision

Add a thin fixed-command CLI with an append-only journal, rebuildable heads,
stable identities, atomic directory staging, explicit human lead/revenue
receipts, six canonical outer-object adapters, and canonical draft-only review
output. Publication changes reuse the canonical `publication-event` event types;
they do not add another lifecycle schema or a platform-operation executor.

### Reason

The existing schemas and publication tracker already express the correct IDs,
windows, privacy rules, signal classes, and review semantics. A small adapter is
safer and easier to audit than a database, scheduler, raw command runner, or
parallel state machine.

### Evidence

- Canonical atomic 14-contract manifest and its workspace validator.
- Existing publication-feedback tracker helpers and its regression suite.
- Synthetic positive/negative tests covering replay, conflict, exact window
  boundaries/drift, atomic rollback, lead confirm/reject, explicit receipts and
  attribution, evidence continuity, no-signal review, late-data review revision,
  store/backup ambiguity, chain/anchor tamper, classification/contract binding,
  human privacy scope receipts, fixed private roots, experiment/diagnostic/
  resource/revenue/continuity/security cross-references, receipt authority
  escalation, resource/revenue summaries, and independent-run stability.
- Synthetic publication-change tests covering `published → edited → deleted →
  restored`, rejection of free event selectors, invalid transitions, stale
  source events, atomic rollback, and the cross-publication
  `deleted → published` replacement chain.

### Effective scope

Local manual content-operations recording and synthetic/offline validation in
this repository. It grants no publishing, external-send, customer-contact,
provider, knowledge-base, or CRM authority.

### Rollback

Revert the cycle adapter, tests, synthetic fixtures, and this document together;
do not remove only an individual head type from an existing runtime store. No
parallel domain schema or state machine was added. For a runtime store, retain
or archive the append-only journal; derived heads may be discarded and rebuilt
only with a version of the adapter that understands every recorded component.
