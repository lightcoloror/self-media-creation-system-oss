---
name: content-fact-card
description: Build or revise the exact content-fact-card.v0 JSON contract before Chinese self-media, insurance, medical, financial, legal, customer-case, or hot-topic drafting. Use when facts, evidence, uncertainty, privacy, rights, quantitative scope, corrections, or downstream invalidation must be fail-closed.
---

# Content Fact Card

Create the canonical fact gate before drafting. This skill does not write the public-facing post.

## Authority

The machine contract is owned by Content Studio:

- contract: `content-fact-card.v0`
- schema: `content-studio-poc/schemas/content-fact-card.v0.schema.json`
- binding: [contract-binding.json](references/contract-binding.json)
- valid synthetic example: [synthetic-content-fact-card.v0.json](references/synthetic-content-fact-card.v0.json)

When this prose conflicts with the bound Schema, the Schema wins. Do not invent a parallel YAML or JSON shape. A machine fact card must contain only Schema-defined fields because the Schema uses `additionalProperties: false`.

## Non-negotiable rule

Do not draft the final post first. Establish a revisioned fact card, separate facts from unknowns, decide what cannot be claimed, run all five gates, and bind downstream work to the exact revision.

Never promote an AI synthesis, old script, transcript guess, peer post, or inspiration into a verified fact. The user's latest explicit correction outranks machine summaries and old drafts, but objective dates, payments, diagnoses, policy wording, and public claims still need appropriate evidence.

## Workflow

1. Identify the content object.
   - Set stable `fact_card_id` and `content_id`.
   - Set `synthetic_only` truthfully. Never label real material synthetic.

2. Establish revision state.
   - Use `revision_id` for versioned work.
   - Use `canonical_status: locked_for_draft` only after actors, actions, order, numbers, unknowns, privacy, rights, and forbidden wording have been reviewed.
   - A correction creates a new revision and a `correction_log` entry; the old revision becomes `superseded`.

3. Rank source precedence.
   - For objective events and values, prefer contemporaneous primary records.
   - For feelings, intent, preference, or lived experience, prefer the speaker's latest explicit confirmation.
   - Record precedence in `source_precedence`; do not add free-form source fields outside the Schema.

4. Create `facts` with stable IDs.
   - Keep similar actions distinct: consultation is not treatment booking; contacting a hospital is not scheduling; preference is not a final decision.
   - Each fact must contain `fact_id`, `text`, and at least one structured `evidence_refs` item.
   - Use optional actor, action, sequence, status, allowed wording, forbidden paraphrases, confirmation time, and privacy class when supported.

5. Scope every important number.
   - For statistics, estimates, ratios, totals, ranges, or individual monetary cases, add `quantitative_scope`.
   - State region, period, population, event or condition, measurement window, metric type, denominator, value nature, what the number supports, and what it does not support.
   - A derived estimate also requires derivation and assumptions. Never turn a scenario stress test or individual case into a population conclusion.

6. Record evidence lifecycle and rights.
   - Use `usage_status` to distinguish active, supporting, background, and retired evidence.
   - A retired reference requires `retirement_reason`.
   - When reuse rights matter, record reuse mode, license status, attribution, and boundaries under `rights`.
   - A screenshot, crop, redrawn chart, quote, and link are different reuse decisions.

7. Preserve uncertainty and prohibitions.
   - Put missing, unresolved, or contradictory points in `unknowns`.
   - Put unsupported promises, universal claims, privacy-sensitive wording, and misleading causal claims in `forbidden_claims`.
   - Do not smooth unknowns into confident public copy.

8. Run the five machine gates.
   - `fact`
   - `privacy`
   - `medical_insurance`
   - `authorization`
   - `rights`

   Each gate is exactly `pass`, `needs-review`, or `blocked`. Any `blocked` gate stops downstream drafting. High-risk real material normally remains human-reviewed even when all fields validate.

9. Hand off by artifact reference.
   - Story work may enter `insurance-content-storycraft` only after the required gates permit it.
   - Language polishing may enter a human-voice step only after the body is structurally approved.
   - Downstream scripts, hooks, covers, subtitles, and review receipts must retain the exact fact-card artifact/revision reference.

10. Invalidate downstream artifacts after correction.
    - Set `downstream_effect` to `invalidate-derived-artifacts`.
    - Re-run affected story, voice, hook, visual, and review stages against the new revision.

## Exact machine-output skeleton

Use valid JSON, not prose pretending to be JSON:

```json
{
  "schema_version": "content-fact-card.v0",
  "fact_card_id": "fact-card-example-001",
  "content_id": "content.example-001",
  "synthetic_only": true,
  "revision_id": "fact-rev-example-001",
  "canonical_status": "draft",
  "source_precedence": ["reviewed synthetic primary record"],
  "facts": [
    {
      "fact_id": "fact-001",
      "text": "A fictional household created a policy inventory.",
      "fact_type": "objective-event",
      "status": "confirmed",
      "privacy_class": "public",
      "evidence_refs": [
        {
          "ref_type": "evidence",
          "ref_id": "evidence-synthetic-001",
          "usage_status": "active",
          "rights": {
            "reuse_mode": "not-for-publication",
            "license_status": "not-applicable",
            "attribution": "synthetic fixture"
          }
        }
      ]
    }
  ],
  "unknowns": [],
  "forbidden_claims": ["Do not present the synthetic example as a real customer result."],
  "gates": {
    "fact": "pass",
    "privacy": "pass",
    "medical_insurance": "pass",
    "authorization": "pass",
    "rights": "pass"
  }
}
```

Reader, purpose, channel, status prose, and recommended next Skill belong in the surrounding content brief or routing record unless the canonical Schema later adds them. Do not smuggle them into the fact-card object.

## Fail-closed cases

Block or keep `needs-review` when any of these apply:

- evidence cannot support the actor, action, chronology, number, quote, or causal link;
- a public statistic lacks denominator, period, population, or value nature;
- a customer/patient story lacks de-identification or publication authorization;
- rights for an image, screenshot, quote, chart, or media excerpt are unclear;
- wording implies guaranteed underwriting, claim, treatment, legal, financial, or investment outcomes;
- product suitability or treatment superiority is generalized from one case;
- an old fact revision or retired evidence remains in a downstream draft.

## Boundaries

All outputs are local planning/review artifacts. This Skill grants no authority to publish, upload, contact customers, write CRM or knowledge bases, or call external Providers.

