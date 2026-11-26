# Self-media Agent entry
`content-creation-system`; no publish/send/contact/CRM/KB/Provider authority. [Details](docs/agent-discovery-details-2026-08-28.md).

## Stable entry
- **Start**: `resolve` + `self-media-work-request.v1` selects one consumer or lightweight 4-stage flow from deliverable/artifacts/risks ([guide](docs/workflow-entry-selection.md)). Legacy `self-media-agent-request.v1` resolves managed recipes.
- **Media & overlays**: `video-delivery materials-bind|materials-redraw|materials-card-replace|materials-check`; screen-card edits start from actual HTML; bottom safe-zone progress bars require usage evidence and subtitle/badge collision checks ([video delivery](docs/video-delivery.md)).
- **Video motion & style code discovery**: before authoring custom animations or transitions, query `mvp-video-pipeline` `scripts/semantic_editorial.py motion-find` (checks `T1` local verified cases + Shotcraft + Lemo with preview stills), unpack full import closure via `motion-unpack`, and verify `motion_reference_binding.v1` via `motion-binding-check` ([mvp entry](../ai-video-tools-20260708/mvp-video-pipeline/AGENT_DISCOVERY.md)).
- **Creation & review**: `python scripts/self_media_agent.py creation-route` ([form](docs/creation-route-selection.md), [Vlog](docs/travel-experience-vlog-workflow.md)); `authoring` ([workflow](docs/author-expression-workflow.md)); `review-integrity --help` ([C01-C09](docs/editorial-execution-integrity.md)); `research-capture` ([rules](docs/research-capture-execution.md)); `cta` ([contract](docs/cta-selection-and-landing.md)); speech leveling ([doc](../ai-video-tools-20260708/mvp-video-pipeline/docs/rough-cut-segment-leveling.md)); VKP source-time-range rough-cut review uses `video-review pre-review-audio-audit` (16 kHz audio-only WAV, zero intermediate video + VKP secondary ASR + 25ms edge RMS auto-fix, `verified_keep` triage, final post-cut playback edges; never dump raw cuts or export intermediate MP4s — [rule](docs/source-time-range-review.md)).

```text
python scripts/self_media_agent.py doctor
python scripts/self_media_agent.py capabilities
python scripts/self_media_agent.py operations
python scripts/self_media_agent.py run-example --recipe moments-short-post
python scripts/self_media_agent.py resolve --request <task.json> --output <selection-or-capsule.json>
python scripts/self_media_agent.py prepare-step --capsule <capsule.json> --step-id <step-id> --context-manifest <manifest.json> --context-receipt <context-receipt.json> --output <handoff.json>
python scripts/self_media_agent.py verify-step-output --handoff <handoff.json> --receipt <step-output-receipt.json>
python scripts/self_media_agent.py sequence-status --capsule <capsule.json> [--receipt <receipt.json> ...] [--require-complete]
python scripts/self_media_agent.py resume --receipt <error-receipt.json>
```
Contracts: `agent-tool-manifest.v1.json`. `python scripts/self_media_agent.py authoring`; `python scripts/self_media_agent.py publication-desk`: [desk](docs/publication-desk.md), [covers](docs/content-driven-covers.md), [delivery](docs/video-delivery.md).

Performance: `video-delivery performance-init / performance-bind / performance-review-template`; cue plans, change evidence and final observations. [Closure, pacing limits and readability tiers](docs/production-performance-closure-20261030.md). No automatic audience validation or historical receipt upgrade; scientific review remains required.

## Immediate post-publication trigger
Scheduling/publication, metrics, warnings or deidentified interaction/business events: first use `python scripts/self_media_agent.py operations`, not review or chat-only notes.
Scheduling is not publication; record supplied dates, never invent confirmation. `content_operations_cycle.py`: `record-publication` only when live; `record-snapshot` at 48-72h (`early`) or 156-180h (`d7`); then `validate-store`. Earlier metrics are provisional; review requires existing private store.

## Managed recipes only: one goal after entry selection
| `workflow_goal` | Recipe | Route |
|---|---|---|
| `moments_short_post` | `moments-short-post` | Reviewed observation -> short Moments candidate. |
| `xhs_evidence_graphic` | `xhs-evidence-graphic` | Audience question -> evidence research -> graphic-note candidate. |
| `case_video_candidate` | `case-video-candidate` | Reviewed case item -> deidentified video-script handoff. |
| `publication_feedback_review` | `publication-feedback-review` | Existing operations store -> draft six-layer review -> human gate. |
| `context_efficient_rework` | `context-efficient-rework` | Existing media -> affected-window review/revision only. |

Only managed recipes use these five goals. `resolve` selects subflows, general 4-stage flow, or Vlog; `continue` resumes saved progress. Context-efficient rework uses `prepare-step` guarded commands ([rules](docs/agent-discovery-details-2026-08-28.md)).

## Routing, creation gates, and execution
- Read this file, request and capsule. `routing-binding.v1.json` atomically binds `../docs/content-creation-system/routing`. Never mix roots or execute stale releases.
- `prepare-step` supplies context receipt & hashes; `sequence-status` exposes single `next_step`; `--require-complete` enforces semantic/progress verification (hollow placeholders fail closed; `human_gate` binds artifact hash).
- Old desk data: `publication-desk upgrade`; copy edits invalidate only the modified platform ([closure plan](docs/plans/2026-10-29-three-video-workflow-closure.md)).
- Conditional gates (enabled by declared/content risks): medical/science ([gate](docs/中国科协科技工作者科普创作指南接入说明-2026-09-03.md)), privacy/redaction windows ([review](docs/source-time-range-review.md)), timing before/after production, interviews ([material-interview](skills/material-interview/SKILL.md)). Never manually edit hash-bound receipts.
- `resume`: one recovery action per error code, no auto-retry; detailed pointers: `docs/Agent执行详细边界与路由指针-2026-08-26.md`.

## Hard boundaries
- Publication is `manual-only`; `draft_only`/`candidate_only`/`publish-ready` never mean published.
- External send, customer contact, CRM, KB writes and provider calls are `not-authorized`.
- Candidate evidence/AI synthesis cannot become verified facts; `content_no_signal` is neutral.
- Raw customer, health, policy, interview, full-media, secret and token data never enter fixtures/capsules.

## Artifact lifecycle
Video close defaults to rework archive: [archive levels](docs/video-archive-levels.md), `archive-policy`, `archive-plan --assessment <json> --output <new-plan.json>`, `artifact_lifecycle.py doctor`, [lean gate](docs/lean-archive-backup-cleanup.md). No ad hoc deletion.
