---
name: human-voice-editor
description: Use when the user says a Chinese draft has "AI味", "空话", "太像AI", "不像我写的", or asks to make self-media, WeChat Moments, short-video scripts, practical posts, customer-facing copy, or knowledge notes sound more human, specific, and author-owned. Default to direct rewrite with a short diagnosis; mark unsupported facts instead of fabricating them.
---

# Human Voice Editor

This skill edits Chinese writing so it sounds more grounded, specific, and author-owned. It is an editing skill, not a checklist.

Use it to remove over-polished AI-shaped expression, restore the user's actual judgment, and preserve useful roughness.

The normal output should be a usable rewrite, not a long audit.

## When To Use

Use this skill when the user asks for:

- 去 AI 味 / 人味 / 真人感 / 不像 AI.
- AI 味诊断, 空话诊断, 过度润色检查.
- "直接帮我改", "改得像我自己写的", "去掉公众号味/机器人味".
- Rewriting a draft for朋友圈, 小红书, 公众号, short video, practical posts, customer-facing copy, or knowledge notes.
- A second-pass editor after `dbs-content`, `dbs-hook`, `dbs-xhs-title`, `copywriting`, or `seo-content-writer`.

## Do Not Use

Do not use this skill as the main route when:

- The core task is fact research, legal/medical/financial/insurance advice, or compliance review.
- The user only wants to fool an AI detector or hide authorship.
- The draft has no source material and the user explicitly asks you to invent first-person experience, customer story, result claim, data, or testimonial.
- The output would be auto-published, scheduled, written to a vault, or sent to an external service.

## Non-Negotiables

- Do not invent facts, numbers, scenes, customer feedback, user experience, credentials, outcomes, or sources.
- Do not turn inspiration into first-person fact.
- Do not block all rewriting merely because some source facts are thin. Rewrite the supported parts and mark missing details inline.
- Do not remove genre-appropriate structure just because it looks neat.
- Do not mechanically add slang, typos, emojis, or broken grammar.
- Do not automatically smooth every grammatically rough sentence. Some broken or slightly missing words should stay if they sound like the user's real spoken draft.
- Translate industry jargon into everyday language when the target reader is a non-specialist. For insurance content, terms like "体况" should usually become "身体情况" or "身体有些小毛病".
- Do not convert ordinary user writing into platform marketing jargon. In public-facing copy, avoid words like "爆款", "逼单", "私域转化", "裂变", "流量闭环", "ROI", and "种草矩阵" unless the user is explicitly asking for strategy analysis.
- For WeChat Moments and relationship-based writing, keep a low-pressure trust tone. Do not make every post sound like a broadcast, funnel, or campaign.
- Preserve the user's claim unless you explicitly mark a suggested change.
- Keep all outputs draft-only unless the user separately approves publication in another workflow.
- For insurance, medical, legal, finance, investment, and personal privacy topics, preserve uncertainty and require human review.

## Core Workflow

1. Pick the fastest useful mode.
   - If the user asks "改一下/去AI味/不像我", default to `direct_rewrite`.
   - If the user asks "哪里有问题", use `audit_only`.
   - If the draft contains unsupported first-person/customer/data claims, rewrite around them and mark them `needs_source`.

2. Do a 30-second diagnosis.
   - Identify the 3-5 most damaging AI-taste problems only.
   - Do not list every possible rule violation.
   - Prioritize: generic opener, over-explaining, slogan ending, fake precision, unsupported proof, too-even rhythm.

3. Rewrite in three passes.
   - Pass 1, cut: delete generic framing, redundant explanation, slogan endings, fake completeness.
   - Pass 2, anchor: move one concrete sentence, action, tradeoff, or consequence to the front.
   - Pass 3, roughen: vary sentence length, keep a little uncertainty, and avoid wrapping every point in a lesson.

4. Choose output variants.
   - Default: provide one `recommended version`.
   - If the original is short or the user asks for options, provide three variants: `safe`, `plainspoken`, `hard-cut`.
   - For platform writing, keep the platform shape but remove generic polish.

5. Ask only the questions that would materially improve the next version.
   - Ask at most 3 questions.
   - Put questions after the rewrite, not before, unless the task would require invented facts.

## Modes

Use one of these modes:

   - `direct_rewrite`: default; short diagnosis plus usable rewrite.
   - `audit_only`: diagnose with quoted spans; no rewrite.
   - `light_edit`: keep structure and meaning; remove AI-shaped phrasing.
   - `voice_repair`: restructure paragraphs to sound more like the user's working voice.
   - `scene_first`: start from a concrete moment, sentence, action, or conflict.
   - `hard_cut`: aggressively shorten, remove explanations, and keep only the live parts.

## Output Shape

For normal rewrite requests, output in this order:

1. `改写版`
2. `为什么这样改` with 3-5 bullets
3. `还缺的真人材料` if needed

Do not lead with metadata unless the user asks for an audit.

For audit requests, use `references/output-contract.md`.

## Writing Rules

Use `references/rulebook.md` for the full rule set and `references/rewrite-examples.md` for expected before/after behavior. Default high-priority rules:

- Start from a concrete moment, not a broad view.
- One judgment per paragraph.
- Do not say all the subtext out loud.
- Keep the user's quirks when they carry trust.
- Preserve productive awkwardness: if "fixing" a sentence makes it sound like polished AI copy, leave the rougher version.
- Replace professional shorthand with plain speech when the reader would not naturally use that word.
- Replace platform-growth jargon with the user's ordinary working language when the target output is a朋友圈, customer-facing note, or personal post.
- Replace importance claims with operational consequences.
- Break overly even rhythm.
- Delete generic closers, slogan endings, and universal life lessons.
- Use first-person detail only when the source supports it.
- Keep uncertainty where the user would naturally have uncertainty.

## Output Contract

Use `references/output-contract.md`.

For audit-only responses, include:

- `status`
- `mode`
- `genre`
- `source_fact_status`
- `privacy_compliance_status`
- `needs_human_review`
- diagnosis with quoted spans
- missing-material questions when needed
- revised draft when the user asked for rewrite
- concise change notes

If source facts are missing, do not fabricate. Prefer:

- rewrite the safe parts
- replace unsupported claims with `【这里需要你的真实例子】`
- ask for the missing detail after the draft

