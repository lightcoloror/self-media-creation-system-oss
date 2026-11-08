# Agent discovery details — 2026-08-28

Updated: 2026-08-28 17:01:08 +08:00
Acting tool/model: Codex (GPT-5.6 Sol)

This is the detailed companion to `../AGENT_DISCOVERY.md`. The short file remains the bounded cold-start surface; load only the section needed by the active, hash-bound handoff. This document preserves the complete pre-compaction discovery content below and records the guarded executor detail added during compaction. Canonical machine authority remains in `agent-tool-manifest.v1.json`, `recipes/self-media-recipes.v1.json`, the schemas, and the registered owner discovery returned by `prepare-step`.

Current-entry clarification, 2026-10-25 21:34:37 +08:00, Codex (GPT-6): [task selection](workflow-entry-selection.md) selects an existing recipe or shared subflow from the requested deliverable. Historical goal lists below describe managed recipes only. Human recipe/material review uses original source time ranges; older proxy-first wording is superseded by [source review](source-time-range-review.md). Historical provenance and receipt identities remain unchanged.

## Derived sequence enforcement

After every accepted output receipt, run `self_media_agent.py sequence-status` and execute only the returned `next_step`. Before a managed-pipeline completion claim, rerun it with every ordered receipt and `--require-complete`. This is a read-only cursor over the existing capsule/handoff/receipt chain, not another workflow state machine. It rejects missing, reordered, cross-capsule, stale, blocked, or merely transport-validated completion evidence. Full commands and status semantics are in [`agent-sequence-enforcement-2026-09-05.md`](agent-sequence-enforcement-2026-09-05.md).

## Context-efficient-rework guarded execute-review route

After `resolve` and `prepare-step`, the `context-efficient-rework` recipe uses these exact machine entries in order:

```text
python scripts/context_efficiency.py plan-video-review --manifest <input.json> --output <plan.json>
python scripts/context_manifest_consumer.py decide-asr --handoff <handoff.json> --audio <audio> --previous-receipt <receipt.json> --output <asr-decision.json>
python scripts/context_manifest_consumer.py execute-review --plan <plan.json> --cache-dir <managed-cache-dir> --output <mvp-execution-receipt.json>
python scripts/context_efficiency.py verify-video-review --plan <plan.json> --receipt <receipt.json> --output <verification.json>
```

`execute-review` belongs to the registered `mvp-video-pipeline` tool and may run only through the prepared tool handoff; this is not an instruction to send another thread a message. Its policy is `video-review-resource-guard-v1`: heavy-media concurrency is one; a full decode is reused for the exact media SHA-256 plus check-profile SHA-256; human review uses original-source time ranges without proxy/clip exports; limited technical rework scans only planned changed windows; cached-report analysis may parallelize; and resource pressure fails closed with no automatic retry. The self-media verifier requires the exact candidate hash, matching policy, MVP execution receipt, shared QA report, and unchanged authority boundary before final candidate rendering. A limited rework receipt that repeats reusable full-decode work or scans the full timeline is rejected. Final human QA and manual publication remain mandatory.

## Artifact lifecycle and large-video cleanup

Use the existing lifecycle controller; do not delete large video outputs ad hoc:

```text
python scripts/artifact_lifecycle.py doctor
python scripts/artifact_lifecycle.py preflight --manifest <manifest.json> --workspace-root <workspace> --output-class <small_known|large_or_unknown> --estimated-output-bytes <bytes-for-large-output> --receipt <preflight.json>
python scripts/artifact_lifecycle.py register --manifest <manifest.json> --workspace-root <workspace> --artifact-id <id> --video-id <video-id> --path <relative-file> --kind <kind> --status created --retain-reason <reason> --receipt <register.json>
python scripts/artifact_lifecycle.py transition --manifest <manifest.json> --workspace-root <workspace> --artifact-id <id> --status <qa_pass|qa_fail|superseded> --reason <reason> --receipt <transition.json>
python scripts/artifact_lifecycle.py lock --manifest <manifest.json> --workspace-root <workspace> --artifact-id <id> --reason <approval-scope> --receipt <lock.json>
python scripts/artifact_lifecycle.py plan-gc --manifest <manifest.json> --workspace-root <workspace> --phase quarantine --task-close --receipt <plan.json>
python scripts/artifact_lifecycle.py apply-gc --manifest <manifest.json> --workspace-root <workspace> --plan <plan.json> --phase quarantine --receipt <receipt.json>
```

- Register outputs immediately. Files at least 200 MiB require a retain reason; unprotected task intermediates above 2 GiB block a new render and require safe GC.
- Disk preflight consumes the shared media profile: keep a 512 MiB hard reserve, warn below 5 GiB, and reserve `estimated_output_bytes * 1.25`; large or unknown outputs require an estimate.
- Preserve raw source, reviewed source, fine cut, locked master, final, recipe, provenance, and review artifacts.
- Task close may quarantine eligible intermediates; it does not permanently delete them. Purge needs separate authorization and is disabled by default.

## Complete pre-compaction discovery content

# Self-media Agent entry

This repository is an operational consumer of the registered `content-creation-system` routing contracts. This file is a short discovery surface, not permission to publish, send, contact customers, write CRM/knowledge bases, or call a Provider.

## Start here

```text
python scripts/self_media_agent.py doctor
python scripts/self_media_agent.py capabilities
python scripts/self_media_agent.py operations
python scripts/self_media_agent.py run-example --recipe moments-short-post
python scripts/self_media_agent.py resolve --request <request.json> --output <capsule.json>
python scripts/self_media_agent.py prepare-step --capsule <capsule.json> --step-id <step-id> --context-manifest <manifest.json> --context-receipt <context-receipt.json> --output <handoff.json>
python scripts/self_media_agent.py verify-step-output --handoff <handoff.json> --receipt <step-output-receipt.json>
python scripts/self_media_agent.py resume --receipt <error-receipt.json>
```

## Synthetic small-model candidate loop

This is an owner-local contract exercise, not a sixth business workflow. A small Agent can run it without reading repository source or chat history:

```text
python scripts/small_model_content_loop.py doctor
python scripts/small_model_content_loop.py run --input fixtures/small-model-content-loop-v1/input.valid.json --run-root outputs/<run-id>
python scripts/small_model_content_loop.py run --input fixtures/small-model-content-loop-v1/input.valid.json --run-root outputs/<run-id> --pause-after candidate
python scripts/small_model_content_loop.py resume --run-root outputs/<run-id>
python scripts/small_model_content_loop.py check-negatives --cases fixtures/small-model-content-loop-v1/negative-cases.json --run-root outputs/<negative-run-id>
```

Read only `fixtures/small-model-content-loop-v1/compact-handoff.v1.json` before running. The five stages are `preflight → candidate → variants → gates → review`. The command accepts only repository-relative, hash-bound, fully synthetic evidence. It validates all 12 registered platform routes and generates candidates only for 公众号、朋友圈、小红书、视频号脚本、知乎、B站. Every variant must stand alone and must not use episode numbers. Drift, privacy fields, `unverified` facts, stale human-voice confirmation, or any request to finalize/publish stops with zero automatic retries. Outputs remain `candidate_only / review_required / manual-only`.

The manifest is `agent-tool-manifest.v1.json`. Requests use `schemas/self-media-agent-request.v1.schema.json`; decision capsules use `schemas/self-media-task-capsule.v2.schema.json`; execution handoffs and output receipts use `schemas/self-media-step-handoff.v1.schema.json` and `schemas/self-media-step-output-receipt.v1.schema.json`.

## Immediate post-publication trigger

If a human says content was scheduled or published, gives platform metrics, reports a platform warning/diagnostic, or supplies a deidentified interaction or business event, run `python scripts/self_media_agent.py operations` before analysis. Do not leave the report only in chat and do not start with `publication_feedback_review`.

A human-reported scheduled date or time is not a publication event. Write it to the current platform publication package or publishing calendar, keep the evidence date-only when no exact time was supplied, and do not infer that every platform has been confirmed unless the human says so. Do not call `record-publication` until the item is actually live.

After publication, use the returned fixed `content_operations_cycle.py` command: `record-publication` immediately; `record-snapshot` only at 48–72 hours (`early`) or 156–180 hours (`d7`); the matching fixed command for interactions, diagnostics, experiments, resources, revenue, continuity, or security. Then run `validate-store`. Metrics before 48 hours are provisional: never relabel them as `early`; return the next eligible window and any missing governed input. This direct manual-recording route is not a sixth workflow goal. Use `publication_feedback_review` only after the private append-only store exists and a review is requested.

## Pick exactly one goal

| `workflow_goal` | Recipe | Use when |
|---|---|---|
| `moments_short_post` | `moments-short-post` | One reviewed observation should become a short Moments candidate. |
| `xhs_evidence_graphic` | `xhs-evidence-graphic` | One audience question needs evidence research and a graphic-note candidate. |
| `case_video_candidate` | `case-video-candidate` | A reviewed case content item should become a de-identified video-script handoff. |
| `publication_feedback_review` | `publication-feedback-review` | An existing manual operations store needs a draft six-layer review and final human judgment. |
| `context_efficient_rework` | `context-efficient-rework` | Existing media should be reviewed or revised only in affected windows. |

Do not infer a sixth goal. If the task does not fit, stop and ask the human owner to choose or extend the canonical contracts.

## Reading rule

1. Read this file, the request, and the compact decision capsule.
2. Do not execute from the capsule alone. Run `prepare-step` for the selected step.
3. `prepare-step` reads current `tool-registry.json`/`AGENT_DISCOVERY` or the repository-owned source and adds the tool entry, command names, boundaries, discovery hash, full step instruction, and a context receipt.
4. Load only the step handoff's inline context; load reference or failure-only artifacts only under their recorded condition.
5. Never inline items listed under `never_inline`; use hash-bound references. Full logs stay reference-only unless the step fails.

## Routing rule

`routing-binding.v1.json` atomically binds `../docs/content-creation-system/routing`. Never load the five deprecated root JSON snapshots, never mix roots, and never silently fall back when the registered contract set is missing or stale.

## Execution rule

- Follow `step_index` in order and stop on the first failed gate.
- Every existing-owner step requires a valid `self-media-step-handoff.v1`; missing local tool discovery, source roles, context receipt, or a stale hash fails closed.
- The next step requires a valid `self-media-step-output-receipt.v1`; the capsule is not a substitute for an execution receipt.
- A `cli` step is an explicit existing command, not a shell template to improvise around.
- An `agent_task` is a bounded deliverable; it does not grant Provider or external action authority.
- A `human_gate` cannot be self-approved by an Agent.
- `draft_only`, `candidate_only`, and `publish-ready` never mean published.
- Operations journals, packaging credentials, and derived heads are hash-bound; never edit them manually.
- A series may be fully edited in one batch, but every item still needs its own pre-release packaging review. Each item must bind an audience question, reviewed entry strategy, necessary context, two or more ordered information advances, core answer, and current-item payoff to the frozen title/opening/body. Title, cover, and opening must make the same promise; neither a prior item nor a future item may be required. Insurance explicitly chooses life-context-first or search-intent-direct instead of applying one hook formula everywhere. Keep order in internal metadata; never put episode/part numbers in the audience-facing title or cover. A separate next-topic teaser is allowed only after the current payoff is complete.
- Recipe/material review opens the original source at explicit time ranges through `video-review` / `targeted-review`; do not export proxy or review clips. Full-resolution media is not loaded inline. Actual final-media QA uses the explicitly requested existing candidate and its exact hash.
- Every time-bound rendered-video review uses VKP `targeted-review`, an exact candidate hash, and explicit time ranges; text-only fact review remains in writing.
- Case media requires human-bound subject identity, orientation, voice/face treatment, visible-window privacy QA, and exact customer-review hashes. Detection alone never proves identity.
- Amounts, cross-language subtitles, artifact lifecycle, final-layout safety, typography, title/cover, and manual platform packaging follow their registered owners and fail closed when required evidence is missing.
- Detailed commands and execution boundaries are in `docs/Agent执行详细边界与路由指针-2026-08-26.md`; load only the section needed by the active step.

## Recovery rule

Use the stable error code from a receipt with `resume`. It returns one recovery action and always sets `automatic_retry=false`. Unknown errors require human triage; do not retry or invent a workaround.

Operations-store recovery details are in `docs/Agent执行详细边界与路由指针-2026-08-26.md`.

## Hard boundaries

- Publication: `manual-only`.
- External send, customer contact, CRM and knowledge-base writes: `not-authorized`.
- Provider calls: `not-authorized-by-this-entry`.
- Candidate evidence and AI synthesis cannot become verified facts.
- `content_no_signal` is a neutral content observation, never a customer or business conclusion.
- Raw customer, health, policy, interview, full-media, secret, and platform-token material must not enter fixtures or compact capsules.

The full system README is supporting documentation. It is not required for the five cold-start paths above.

## Update record

### 2026-09-03 19:12:00 +08:00 | Codex (GPT-5.6 Sol)

- Moved detailed operational material out of the cold-start entry so `AGENT_DISCOVERY.md` stays within the weak-Agent size budget while preserving all existing boundaries and commands here.

Metadata: Codex (GPT-5.6 Sol), 2026-09-03 19:12:00 +08:00.


## Archive decision entry (relocated 2026-10-24 by Codex)

2026-10-12 17:42:15 +08:00 | Codex (GPT-6): At video project close, default to a **rework archive**, assess actual recovery needs for a reproducible archive, and record exceptions. Follow [archive levels](video-archive-levels.md), read `python scripts/artifact_lifecycle.py archive-policy`, then run `archive-plan --assessment <json> --output <new-plan.json>` before collecting archive materials or planning cleanup. A plan is not a completed archive, rebuild receipt, upload or deletion authority. Reuse existing asset IDs and lifecycle manifests.


## Framework decision entry (relocated 2026-10-24 by Codex)

`topic-angle-decision.v2` follows topic observations: compare audience, value, business fit, evidence and cost; choose continue/reframe/supplement/defer. Only confirmed continue reaches drafting; supplement reaches research then reassessment. `prepare-step` enforces this. v1 proves no framework review. See [four routes](../topic-reframing-playbook.md). Story five questions are a fact-preserving view of `story-design-card.v1`. Keep one central change and truthful turns. Applicable serious-video/cross-platform gates remain required. Receipts never grant publication authority.


## CTA push entry details

2026-10-29 | Codex. Intent: keep the entry discoverable. Decision: relocate these four remote-base paragraphs verbatim. Reason: the existing entry exceeded 9 KiB. Evidence: bounded-entry regression. Scope: navigation only; prior rules and attribution remain.

Contracts: `agent-tool-manifest.v1.json`. `python scripts/self_media_agent.py authoring`: [author guide](author-expression-workflow.md). `python scripts/self_media_agent.py publication-desk`: [desk](publication-desk.md). [Covers](content-driven-covers.md), [delivery](video-delivery.md). Plain desk=draft; delivery rechecks. Added: author/page 2026-09-26, Codex GPT-6 Astra; covers 09-26, delivery 09-27, Codex.

- Hash-bound journals, credentials, derived heads, packages, and media receipts are never manually edited. Recipe/material review uses original source hashes and time ranges through `self_media_agent.py video-review` and VKP `targeted-review`, without proxy/clip exports. Fine-cut reviews also require the presentation/dialogue inputs in [the existing review guide](source-time-range-review.md); output cues are checked after generation. Case media also requires human-bound identity and visible-window privacy evidence. Missing required evidence fails closed.

Video packaging: `video-delivery context` exposes the current progress choice; `progress-select` records `use` or `not_used` with a reason. Missing/stale choice or checked reservation blocks preflight; selected overlays also require actual render/decode/final-layout evidence bound to the final video before delivery. [Contract and migration](video-delivery.md#进度条选用预留与实际交付2026-10-28). 2026-10-28 08:48:47 +08:00, Codex GPT-6. 意图：避免跨项目漏条；决策：进入原交付入口；理由：待办不证明执行；证据：历史记录声称33项交付回归及私有项目编码候选；原回执未随公开版分发，非本轮公开版实测；生效范围：统一视频交付，明确不使用仍允许。

2026-10-28 09:18:10 +08:00, Codex GPT-6. Video progress defaults are runtime code: bind the video script with `video-delivery progress-select --script`; chapter labels reuse script H2 headings, and independent navigation presets select16/20/24px on540 short edge. Body/subtitle minima do not apply to progress. Historical implementation/evidence reference: `progress-script-title-navigation-defaults-20261028.md` (not included in this public edition; the historical reference is not public runtime evidence). 意图：默认同源；决策：接原组件/CLI；理由：避免各项目重复填标题或被正文门限约束；证据：历史记录声称76项通过、1项跳过及私有项目CLI；原回执未随公开版分发，非本轮公开版实测；生效范围：进度导航，其他字号规则保持。


## Public navigation clarification (0.1.5)

2026-11-08T03:16:00.794804+00:00; Codex (exact runtime model not independently verified).
Eight relative links now resolve to files already in this public snapshot.
One missing historical MVP reference is identified as not distributed, with
its filename retained for the separate source-scope audit. Historical private
test counts above remain attributed historical claims; they are not new tests,
public runtime proof, or permission to render, call models, review real media,
clean artifacts, approve facts/privacy, or publish content. No runtime source,
schema, route, Owner pin, dependency, safety setting or historical author changed.
