# Output Contract

Use this contract when the user asks for diagnosis or when risk is high. For ordinary "去AI味/帮我改" requests, use the direct rewrite shape first.

## Direct Rewrite Shape

Default response:

```markdown
## 改写版

<usable revised draft>

## 为什么这样改

- <3-5 concrete changes>

## 还缺的真人材料

- <only if needed>
```

If the user asks for options or the draft is short:

```markdown
## 推荐版

<draft>

## 更口语版

<draft>

## 狠删版

<draft>
```

Keep the diagnosis short. The rewrite is the main product.

## Diagnosis First

```text
status: diagnosis_only | blocked_or_questions_first | draft_ready
mode: direct_rewrite | audit_only | light_edit | voice_repair | scene_first | hard_cut
genre:
source_fact_status: confirmed | partial | missing | inspiration_only
privacy_compliance_status: clear | needs_review | high_risk
needs_human_review: true
```

Then provide:

```markdown
## AI Taste Diagnosis

| Span | Tier | Problem | Fix |
|---|---|---|---|
| quoted text | strict / voice / source | concise diagnosis | concrete edit direction |
```

Use short quoted spans, not long reproductions.

## Questions First

If the source is too thin, still rewrite safe parts when possible. Ask 2-3 targeted questions after the rewrite.

Good questions:

- 这件事最具体的一幕是什么? 你当时看见/听见了什么?
- 这段里哪一句判断是你真的愿意署名的?
- 有没有一个真实客户/朋友/同事的原话, 可以脱敏后使用?
- 你最犹豫或最不确定的地方是什么?
- 这个内容最后希望读者做一个什么小动作?

Do not ask broad questions like "请提供更多背景".

## Rewrite Output

Rewrite when the user's intent is clear. If facts are unsupported, mark them instead of inventing.

```markdown
## Revised Draft

<draft>

## What Changed

- Cut:
- Kept:
- Added from source:
- Still needs human review:
```

If no source-backed detail is available for a necessary factual claim:

```text
status: blocked_or_questions_first
reason: missing_source_for_human_detail
```

If the draft can still be improved without that factual claim:

```text
status: draft_ready_with_placeholders
placeholder: 【这里需要你的真实例子】
```

## Before / After Requirement

For expression-focused work, include a minimal before/after trace:

```markdown
## Before / After Check

Before: <short quoted span>
After: <short revised span>
Why: <one sentence>
```

## Risk Language

For insurance, medical, legal, finance, investment, or personal privacy topics, include:

```text
high_stakes_review: required
claim_strength: unchanged | weakened | marked_needs_source
```

Never strengthen a high-stakes claim during a human-voice edit.
