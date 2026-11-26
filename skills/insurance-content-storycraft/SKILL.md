---
name: insurance-content-storycraft
description: Structure, rewrite, plan, or critique Chinese self-media stories for short video, WeChat articles, interviews, personal brands, Moments, and insurance or medical cases. Use for evidence-bound story discovery, scene, causal change, service causality, interview integrity, channel adaptation, human voice, hooks, and the mandatory 11-gate review for sensitive case work.
---

# Insurance Content Storycraft

This skill turns the user's existing朋友圈/自媒体 framework into a repeatable, evidence-bound storytelling system. It combines McKee's `Story`, `Dialogue`, `Character`, and business-story work with `Storyworthy`, `Storycraft`, the Harvard narrative-nonfiction collection, and `Made to Stick`. Source status and retrieval are defined in [bookwiki-source-map.md](references/bookwiki-source-map.md).

## Single Problem Contract

Solve one problem: turn verified or user-confirmed real material into a causal, human, channel-fit story without inventing facts, forcing a story route, or crossing publication and professional-risk boundaries.

## Topic Index

Load only what the task needs:

| Need | Read on demand |
| --- | --- |
| Fast route and output check | [cheatsheet.md](references/cheatsheet.md) |
| Topic, audience, and channel choice | [channel-and-topics.md](references/channel-and-topics.md) |
| Causal Story structure and machine card | [story-design.md](references/story-design.md) |
| Short video, WeChat article, interview, or personal-brand adaptation | [cross-media-storytelling.md](references/cross-media-storytelling.md) |
| Dialogue, subtext, and interview audio | [dialogue-and-voice.md](references/dialogue-and-voice.md) |
| Character and IP evidence | [ip-and-character.md](references/ip-and-character.md) |
| Emotional design | [emotional-resonance.md](references/emotional-resonance.md) |
| Source Wiki and Evidence index | [bookwiki-source-map.md](references/bookwiki-source-map.md) |
| Sensitive-case contract and eleven gates | [contract-binding.json](references/contract-binding.json), [initial-draft-quality-gate.md](references/initial-draft-quality-gate.md) |

## When to use

Use this skill when the task is any of:

- Write or rewrite a朋友圈 post
- Turn a topic into a short script, article, or live outline
- Improve content to feel more human, less promotional
- Build a stable personal IP voice
- Turn raw素材 or案例 into publishable content
- Create content calendars, topic maps, or channel playbooks
- Find and shape first-person stories without waiting for dramatic life events
- Design or edit interviews for usable scenes, truthful quotations, and turning points

## Core workflow

Always work in this order:

0. **Check the machine fact card**
   If the task involves news, hot topics, customer stories, insurance, finance, health, legal, privacy, or product claims, first build or request an exact `content-fact-card.v0` artifact through `$content-fact-card`. The machine Schema owns the field names and rejects undeclared fields. Do not turn inspiration into first-person fact or customer proof. Bind the story to the exact fact-card artifact/revision.
1. **Select the topic and channel**
   Decide audience, channel, and target action using [channel-and-topics.md](references/channel-and-topics.md).
2. **Choose who is speaking**
   Clarify the speaker's role, personality, and trust signal using [ip-and-character.md](references/ip-and-character.md).
3. **Pull real experience first**
   Before drafting, extract 2-3 concrete memories, phrases, judgments, or lived details from the user using [de-ai-style.md](references/de-ai-style.md).
3a. **Select the smallest truthful story unit**
   Use [cross-media-storytelling.md](references/cross-media-storytelling.md) to distinguish a first-person memory, observed scene, authorized interview, or documented case. Identify the smallest moment that changes meaning. For repeatable local collection, first evaluate an already-deidentified candidate with `self-media-creation-system/scripts/story_material_inbox.py`; `ready-for-story-design` is only permission to continue to the fact-card and story-design gates, never permission to draft from unsupported material. If the material has no consequential change, keep a non-story route.
4. **Build and validate the story spine**
   When `structure_route=story-arc`, create `story-design-card.v1` and pass the deterministic gate described in [story-design.md](references/story-design.md). The card must record source/authorization treatment, one fact-bound scene anchor, first action and real feedback, and a format-fit number of truthful turns. Map emotional beats with [emotional-resonance.md](references/emotional-resonance.md). Direct answers, checklists, and mechanism explanations do not need a story card and must not be forced into this route.
4a. **Build the serious-content attention contract before drafting**
   For insurance, health, high-risk, or declared serious professional content, complete the precreative part of the existing `serious-content-translation-review.v1` route before writing prose. In addition to audience relevance, tension, stakes, and central judgment, record the protagonist's immediate goal or the reader's concrete task, one fact-bound scene/dialogue anchor, the question that should keep the viewer watching, the later payoff, and what the viewer can do with the result. If the target action is consultation or conversion, record one concrete service action and its immediate process effect. Also classify `sensitivity_profile` as `ordinary`, `professional-sensitive`, `medical-sensitive`, `affected-person-severe-illness`, `customer-loss`, `privacy-high-risk`, or `compound-high-sensitivity`. Severe illness, customer loss, privacy-high-risk, and compound-high-sensitivity content default to `humor_level=none`; `light` requires an explicit human-approved exception that never targets the affected person. Moderate or experimental humor is blocked. A case summary, abstract lesson, or dramatic wording cannot satisfy these fields.
5. **Run the mandatory 11-gate initial-draft quality gate**
   Before language polishing, hooks, trial shooting, or publishing preparation, review the first draft with [initial-draft-quality-gate.md](references/initial-draft-quality-gate.md). The exact ordered gates are: fact/evidence, single task, service causality, interview integrity, distribution compliance, medical/insurance, privacy/authorization, title/opening alignment, preliminary voice/AI trace, CTA/product, and production/series. If the creator's concrete action can be removed without changing the story, the service-causality gate fails and the draft returns to step 4. The machine binding is [contract-binding.json](references/contract-binding.json); missing or drifted contracts block downstream work.
5a. **Return flat but correct drafts for structural revision**
   Run the postcreative attention section of `serious-content-translation-review.v1`. The draft must preserve an immediate watch reason, audience relevance, the protagonist goal or reader task, concrete stakes, a scene/dialogue/direct-utility anchor, progressive information, a real completion payoff, a usable takeaway, and service causality when acquisition is intended. These are independent revision checks, not a score. One missing item returns the piece to steps 4–4a; factual and compliance strength cannot average it into a pass.
5b. **Run the fun-integrity hard gate**
   When humor, a visual gag, a playful analogy, or any other entertaining device is present, classify its role as `related`, `decorative`, or `misleading`. Only `related` may pass. Record whether it helps answer the core question, whether its target is safe, whether the facts and service value still stand after removing it, and whether the primary memory target is the central judgment/action/mechanism rather than the gag. Decorative or misleading fun, unsafe targets, fun-dependent core value, and gag-first recall all return the draft for revision. When no fun is present, record `role=none`; do not invent entertainment merely to satisfy the gate.
6. **Humanize the language**
   Rewrite into spoken, emotional, low-pressure language with [dialogue-and-voice.md](references/dialogue-and-voice.md).
6a. **Adapt without changing the facts**
   Apply the short-video, WeChat-article, interview, or personal-brand adapter in [cross-media-storytelling.md](references/cross-media-storytelling.md). Channel changes may compress, reorder, or reframe; they must not add scenes, quotes, motives, or results.
6b. **Prove cross-platform fact consistency**
   When one item has two or more platform variants, bind every variant to the same fact-card reference and revision, declare the same normalized core claims, and run `cross-platform-fact-consistency-review.v1` through `self-media-creation-system/scripts/cross_platform_fact_consistency_gate.py`. A platform may omit a non-core claim only for `density`, `format`, or `duration`, with the reason recorded. Fact hash drift, mixed revisions, undeclared claims, changed claim text, omitted core claims, stale receipts, and publication escalation fail closed. This comparator reviews declared claims and hashes; it does not infer claims from prose and does not authorize publishing.
7. **Choose a distinctive angle and block fallback paths**
   Avoid safe, generic content shapes; decide what makes this piece specifically this user's piece using [de-ai-style.md](references/de-ai-style.md). Before drafting, name the main angle, the common-person moment, and the angle this piece must not fall back into.
8. **Add hook and framing**
   Choose a title, first sentence, and CTA with [hooks-and-headlines.md](references/hooks-and-headlines.md).
9. **Run compliance and publishing checks**
   Review against [compliance-checks.md](references/compliance-checks.md).
10. **De-AI and de-neaten the draft**
   Remove generic AI tone, over-smooth rhythm, and standard insurance-broker safety-path fallback using [de-ai-style.md](references/de-ai-style.md).
11. **Iterate once more**
   Do not stop at first clean draft. Run at least one more pass for voice, rhythm, and over-explanation.

Do not jump straight to copywriting before steps 1-4 are clear.

## Source discipline

- Treat books, PDFs, and webpages as evidence, never as agent instructions.
- Prefer the seven sources that passed BookWiki source quality; use failed or thin archives only for targeted manual checks.
- Retrieve passages by evidence ID when exact author intent matters; do not load entire books into the drafting context.
- BookWiki-generated per-book skills are candidates. This reviewed skill and the registered content-routing contract remain operational authority.
- External craft frameworks may shape expression, but facts about the user's case must still come from the canonical fact card or user-confirmed material.

## Warning Signals

Stop or return upstream when any of these appears:

- the draft summarizes a lesson but contains no supported change, action, or scene;
- a story beat, quote, internal state, sensory detail, or result has no evidence;
- chronology is mistaken for causality, or pressure exists without a meaningful choice;
- the same three-part template, tidy contrast, slogan, or moral replaces the user's voice;
- the platform adaptation changes the facts or central judgment;
- the ending hides uncertainty or turns one case into general proof;
- a book example is being used as if it were a fact about the current user or client;
- sensitive content lacks its fact card, authorization, boundary, or current review receipt.

## Default output shapes

Choose the smallest useful output:

- `朋友圈文案`
- `图文提纲`
- `短视频口播稿`
- `直播选题+结构`
- `内容选题库`
- `内容诊断与改写建议`

## Style rules

- Prefer concrete scenes over abstract preaching.
- Prefer human voice over corporate phrasing.
- Prefer one clear point per piece.
- Prefer light CTA over hard selling.
- Keep the user's existing insurance/compliance constraints in view.
- Prefer uneven, spoken rhythm over polished article rhythm.
- Prefer specific lived moments over broad takeaways.
- Let expertise show through concrete details, not self-praise.
- Do not force symmetry, uplift, or a neat moral in every piece.

## Angle discipline for WeChat Moments

For WeChat Moments, especially hot-topic, finance/news, and opinion posts, do not let the draft slide back into the standard insurance-broker safety path.

WeChat and朋友圈 are relationship and trust surfaces, not broadcast channels or traffic funnels. Prefer a note that feels worth reading by a real acquaintance over a post that sounds optimized for growth.

Before writing the正文, create an internal angle card:

- `main_angle`: the one angle this post will use.
- `common_person_moment`: the ordinary moment or feeling the reader recognizes.
- `blocked_fallback_angle`: the angle this post must not fall back into.
- `allowed_insurance_connection`: whether insurance can appear as a light echo, a concrete case, or not at all.
- `platform_intent`: `life_note`, `trend_echo`, `service_process`, `customer_question`, `product_or_plan_mention`, `compliance_explainer`, or `other`.

Also ask: what does this help the reader say, understand, or ask that they could not express clearly before?

Default blocked fallback angles:

- `专业边界`
- `慢一点判断`
- `负责任分析`
- `先看事实再看规则`
- `保险配置流程`
- `家庭风险/预算/身体/保障缺口四问`

For hot-topic and opinion posts:

- Do not immediately translate the topic into `先看风险、预算、身体情况、保障缺口`.
- Do not use the speaker's professionalism as the main proof.
- First capture the familiar human state: fear of missing out, being pushed by atmosphere, wanting a quick answer, embarrassment, hesitation, or relief.
- Insurance may appear only if it naturally follows the human state. It should not hijack the post into a consultation checklist.

Use the standard insurance-broker path only when the source material itself is a保单体检、核保沟通、理赔资料、咨询复盘 or explicit service-process explanation.

If a draft includes lines like `你家现在最担心的风险是什么`, `已有保障有没有重复或缺口`, `身体情况、预算、家庭责任`, `先看事实再看规则`, or `专业不是把话说满` in a hot-topic/opinion post, treat that as a failed angle pass and rewrite from the main angle instead of polishing the sentences.

Do not import platform-growth language into public-facing copy unless the user is explicitly asking for strategy analysis. Avoid words and frames such as `爆款`, `逼单`, `私域转化`, `裂变`, `流量闭环`, `ROI`, and `种草矩阵` in normal朋友圈文案.

## Anti-AI tone rules

Before finalizing any draft, check it against these rules:

- Do not open with generic summary lines if a real moment can open the piece.
- Do not over-explain what the audience should feel or conclude.
- Do not stack too many tidy transitions or perfectly balanced contrasts.
- Do not rely on repeated `不是X，而是Y` phrasing.
- Avoid `negative parallelisms` unless used very sparingly.
- Avoid `rule of three` rhythm when it sounds pre-fabricated or slogan-like.
- Remove `chatbot artifacts`: meta framing, overly helpful transitions, recap language, and overly explicit lesson statements.
- Do not overuse `很多人以为`, `我越来越觉得`, `最重要的是` unless they lead immediately to a concrete scene.
- Do not write as if answering an exam question; write as if recounting a real event to a real person.
- Keep some incompleteness and spoken roughness when it improves realism.
- When possible, borrow the user's actual phrasing, pacing, and sentence length instead of normalizing it.
- Increase `burstiness`: vary sentence length, paragraph length, and rhythm so the piece does not read with uniform cadence.
- Avoid over-neat Moments writing: if the draft has too many equal-length lines, tidy three-part lists, universal transitions, or a closing slogan, break the rhythm before final output.

## Real-experience extraction

Before drafting a story, case, or opinionated piece, try to get 2-3 of the following:

- the exact first question someone asked
- one moment the user still remembers clearly
- one thing that felt awkward, difficult, or messy
- one judgment the user formed from experience
- one phrase the user would naturally say out loud

If these are not provided, infer cautiously from source notes, but do not over-smooth the inferred details.

## If the user gives rough material

Convert it into this structure first:

1. Topic
2. Audience
3. Core tension
4. Key scene or case
5. Main takeaway
6. Desired response

Then continue with the workflow.

## If the user asks for strategy rather than a draft

Do one of:

- Build a topic map
- Build a channel matrix
- Build an IP voice guide
- Build a reusable content template set

Use the reference files instead of writing generic advice.

## If writing a story or case-based video script

Default to this order:

1. Open on one concrete moment.
2. Name the immediate confusion or pressure.
3. Unfold the problem in the order a real person experienced it.
4. Insert short real quotes or near-quotes whenever available.
5. End with a modest, lived takeaway rather than a grand conclusion.

For case-based video, also run:

- pressure-choice check from [story-design.md](references/story-design.md)
- subtext/original-audio check from [dialogue-and-voice.md](references/dialogue-and-voice.md)
- IP evidence check from [ip-and-character.md](references/ip-and-character.md)
- mandatory initial-draft review from [initial-draft-quality-gate.md](references/initial-draft-quality-gate.md)
- serious-content attention precheck and postcheck from the registered `serious-content-translation-review.v1` route

For short video, ask these questions before wording polish:

- What exact action, line, number, choice, or consequence earns the first two seconds?
- What does the protagonist want right now, or what concrete task does the viewer need solved?
- What can be delayed, lost, blocked, or made harder?
- Which real scene, confirmed quote, or direct utility keeps the piece out of summary mode?
- What new information arrives at least twice after the opening, and what does each advance change?
- What question is opened, where is it paid off, and what can the viewer do with the answer?
- If this is acquisition content, what did the creator actually do and what changed immediately because of it?
- If fun is present, does it answer the core question, remain safe, leave the core value intact when removed, and keep the audience remembering the judgment rather than the gag?
- If multiple platform versions exist, do they bind to one fact revision and preserve the same core claims despite differences in length and framing?

Do not total these into a “viral score”. A weak opening, missing payoff, or invisible service action is a revision condition even when the other dimensions are strong.

The initial-draft decision is fail-closed:

- `approved_for_voice_pipeline`: may enter spoken-language rewriting and later hook work.
- `return_for_revision`: return to the story spine; do not merely polish sentences.
- `blocked_from_downstream`: stop until facts, authorization, medical/insurance boundaries, or other blocking evidence are resolved.

For an acquisition script, each episode must contain at least one concrete `service-action` and a matching CTA. Customer pressure and interview quotes can support that action, but cannot replace it. Do not run `dbs-hook`, trial shooting, or publishing preparation before the initial draft has an approved, body-hash-bound review receipt.

If the script depends on client audio that has not been recorded yet, do not invent client quotes. Write:

- the interview question
- the selection criteria for a usable line
- the audio slot in the story
- the fallback edit if audio quality is poor

If the piece starts sounding too complete, too smooth, or too explanatory, run the de-AI pass again.

If the piece still sounds generic after the de-AI pass, do not keep polishing wording. Return to the fact card and angle card, then rebuild from a more specific reader moment.

## Iteration rule

Naturalness is usually not in the first draft.

Minimum passes:

1. structural pass
2. spoken-language pass
3. de-AI pass

If a piece still sounds generic after pass 3, do not merely edit words. Rechoose the angle and rebuild from a more concrete opening.

## References

- Topic and channel selection: [channel-and-topics.md](references/channel-and-topics.md)
- Story structure: [story-design.md](references/story-design.md)
- Emotional resonance: [emotional-resonance.md](references/emotional-resonance.md)
- Dialogue and emotional phrasing: [dialogue-and-voice.md](references/dialogue-and-voice.md)
- IP and character design: [ip-and-character.md](references/ip-and-character.md)
- Hooks and headlines: [hooks-and-headlines.md](references/hooks-and-headlines.md)
- Compliance checks: [compliance-checks.md](references/compliance-checks.md)
- McKee integration map: [mckee-mapping.md](references/mckee-mapping.md)
- De-AI writing pass: [de-ai-style.md](references/de-ai-style.md)
- Mandatory initial-draft quality gate: [initial-draft-quality-gate.md](references/initial-draft-quality-gate.md)
- Machine contract binding: [contract-binding.json](references/contract-binding.json)
- Cross-media adaptation: [cross-media-storytelling.md](references/cross-media-storytelling.md)
- BookWiki source and evidence map: [bookwiki-source-map.md](references/bookwiki-source-map.md)
- Fast route cheatsheet: [cheatsheet.md](references/cheatsheet.md)

## Update record

### 2026-09-03 17:23:59 | Codex (GPT-5.6 Sol)

- Intent: turn the remaining serious-content fun and cross-platform consistency gaps into executable, fail-closed checks.
- Decision: require a seven-value sensitivity profile, near-zero-humor defaults for severe illness/loss/privacy cases, a four-part fun-integrity review, and a hash-bound cross-platform claim comparator.
- Reason: the previous route could reject unsafe humor but could still admit unrelated decorative fun, gag-first recall, or platform variants whose core claims silently changed.
- Evidence: the user-approved gap audit; `serious-content-translation-review.v1`; `cross-platform-fact-consistency-review.v1`; deterministic positive and negative fixtures.
- Effective scope: new or materially revised serious professional, insurance, health, customer-loss, privacy-sensitive, and multi-platform content candidates; it does not rewrite verified facts or authorize publishing.
- Rollback: revert the four new contract fields/gates and restore the prior registered skill hash and routing contract-set version together; do not retain a partial binding.

### 2026-09-03 14:00:56 | Codex (GPT-5.6 Sol)

- Intent: integrate the user's full storytelling source set into the existing self-media workflow without creating a competing skill.
- Decision: add a BookWiki evidence map, a shared story-unit test, and adapters for short video, WeChat articles, interviews, and personal-brand content.
- Reason: McKee supplies causal structure, while the additional books supply nonfiction reporting, daily story discovery, scene craft, and memorable concrete communication.
- Evidence: 14 processed BookWiki sources; seven passed the source-quality gate; the cross-book practice guide passed review at 0.96 with 80/80 evidence IDs traceable.
- Effective scope: narrative planning, drafting, rewriting, and critique across the four requested media; sensitive case work still requires the existing fact card and eleven-gate review.
- Rollback: remove the two new references and this update while preserving the prior McKee-based story-design and compliance chain.

### 2026-09-03 16:20:00 | Codex (GPT-5.6 Sol)

- Intent: make story structure and emotional resonance executable rather than advisory.
- Decision: require an evidence-bound `story-design-card.v1` before drafting whenever `structure_route=story-arc`, and separate audience interest, identification, and immersion from unsupported emotion labels.
- Reason: the previous six-beat note did not test causal progression, pressure-choice, turning-point value change, emotional evidence, or the risk that one vivid medical/insurance story could be mistaken for general proof.
- Evidence: the user's local McKee collections, narrative transportation and health-narrative research, and the existing serious-content attention/integrity gates.
- Effective scope: new or materially revised story-arc content; direct-answer, checklist, and mechanism routes remain unchanged.
- Rollback: remove the conditional story card step and restore the prior references together; do not retain partial route bindings.

### 2026-08-24 23:30:00 | Codex (GPT-5.6 Sol)

- Intent: converge Storycraft with the current post-draft machine gate.
- Decision: bind the Skill to `content-fact-card.v0`, the 11 exact review gates, and fail-closed contract drift behavior.
- Reason: the earlier prose omitted `distribution_compliance` and therefore described ten gates while the current Schema and validator require eleven.
- Evidence: `case-video-initial-draft-review.v1` and `initial_draft_quality_gate.py` in Content Studio.
- Effective scope: all new or revised insurance/medical/customer-case Storycraft outputs.
- Rollback: restore the prior prose only as historical reference; it is not compatible with the current 11-gate machine review.

### 2026-08-14 18:55:26 | Codex (GPT-5.6 Sol)

- Intent: prevent structurally wrong but fluent case scripts from reaching voice polishing and production.
- Decision: add a mandatory, fail-closed post-Storycraft review before human-voice and hook stages.
- Reason: the proton-treatment series exposed drafts whose customer story remained understandable after the creator's service actions were removed.
- Evidence: the local `case-video-initial-draft-review.v1` contract and its validator/tests define ten exact gates and bind approval to the draft-body SHA-256.
- Effective scope: all insurance/medical/customer case scripts created or revised with this Skill; it does not authorize publication or replace final high-risk review.

### 2026-09-03 19:12:00 | Codex (GPT-5.6 Sol)

- Intent: close the remaining gap between the storytelling references and the executable self-media route.
- Decision: add deidentified story-material readiness, source/authorization/identity handling, fact-bound scene anchors, action-feedback gaps, and format-specific story profiles before drafting.
- Reason: a fluent six-beat outline could still invent connective tissue, overbuild a short video, or treat an interview like narration.
- Evidence: `story-material-observation.v1`, `story-design-card.v1`, the registered routing 1.5.0 contract set, and their synthetic positive/negative tests.
- Effective scope: story discovery and story-arc planning for Moments, graphic notes, short video, interviews, longform, demos, and live modules; craft scoring remains advisory.
- Rollback: revert the story-material step and the expanded story-design fields together, then restore the previous skill hash in the registered contract set.

### 2026-09-03 16:30:05 | Codex (GPT-5.6 Sol)

- Intent: stop factually correct but emotionally flat short-video plans from entering wording polish and production.
- Decision: bind Storycraft to the existing serious-content attention plan before drafting and require a post-draft revision check for goal/task, concrete stakes, scene/dialogue, progression, payoff, reusable value, and acquisition service causality.
- Reason: the proton-treatment redesign still produced case-summary openings and delayed the creator's meaningful actions even after the causal story gate passed.
- Evidence: the user-reviewed propagation diagnosis, the existing `serious-content-translation-review.v1` dual-gate contract, and the already fact-bound story-material/story-design artifacts.
- Effective scope: new or materially revised insurance, medical, high-risk, and serious professional short-video candidates; it does not change verified facts, authorize publication, or force non-story content into a story arc.
- Rollback: remove steps 4a/5a and the short-video attention checklist together with the matching serious-content gate fields and tests.


