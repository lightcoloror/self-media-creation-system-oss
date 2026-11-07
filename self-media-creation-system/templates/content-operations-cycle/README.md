# Content operations cycle input templates

These templates are manual, local-only inputs for
`scripts/content_operations_cycle.py`. They do not authorize publication,
customer contact, CRM writes, provider calls, or platform access.

Start from the executable synthetic examples in
`fixtures/content-operations-cycle-v1/`:

| Operation | Input template |
|---|---|
| `record-publication` | `record-publication.input.json` |
| `record-snapshot` (`early`) | `record-snapshot-early.input.json` |
| `record-snapshot` (`d7`) | `record-snapshot-d7.input.json` |
| `record-interaction` | `record-interaction-business.input.json` or `record-interaction-no-signal.input.json` |
| `review-lead` | `review-lead-confirm.input.json` |
| `build-review` | `build-review.input.json` |

Copy one fixture to a private runtime directory, replace only the values, and
invoke one fixed subcommand. There is deliberately no raw command envelope or
free-form operation selector. Each command validates exact keys and fails
closed on sensitive fields, stale source hashes, window drift, evidence loss,
or identity conflicts.

Minimum real-use fields to provide manually:

- Publication: a stable local `publication_key`, canonical account/topic/content
  references and SHA-256 values, platform label, manual timestamp, frozen title,
  and a reason when the body/media were not retained. A `complete` freeze must
  provide a repository-relative `body_ref` and its actual byte SHA-256.
- Snapshot: the generated `publication_id`, one window (`early` or `d7`), manual
  `as_of`/`captured_at`, completeness, and content metrics only.
- Interaction: a deidentified summary; never raw comments, names, handles,
  contact details, URLs, tracking parameters, or health/contract particulars.
- Lead review: one explicit human receipt reference + SHA-256, consent status,
  attribution type/model, and evidence that intersects the source interaction.
  Only the three canonical qualifying events may be confirmed; this review is
  not a handoff/contact receipt.
- Review: period, account IDs, creation timestamp after the period end, and the
  current `source_checkpoint` from the governed store. Late data requires a new
  review revision rather than silently reusing an old result.
- `deidentified-operational`: a human `privacy_review` receipt with reviewer,
  reference/hash/time and a hash of the exact reviewed input. The machine gate
  catches only obvious prohibited fields/contact/path patterns, not arbitrary
  medical, policy, or indirect-identification details.

The store is an append-only journal plus rebuildable derived heads. Keep it in
`.runtime/content-operations/<store>` (or the test-only equivalent under
`tests/.runtime/content-operations/`). Do not use either root itself and do not
commit real operational data. All CLI receipts remain `manual-only` with no
publication, external-send, contact, CRM, or execution authority.

Metadata: Codex (GPT-5.6 Sol), 2026-08-24.
