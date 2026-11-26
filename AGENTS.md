# AGENTS.md — Self-Media Creation System (OSS)

This repository is the orchestration workspace for the open-source self-media creation system (`self-media-creation-system-oss`). Coding agents (Codex, Claude Code, Cursor, Antigravity, etc.) operating in this workspace MUST follow the workflow and safety gates below instead of bypassing scripts with ad-hoc chat drafting or hand-written outputs.

## 1. Mandatory Managed Entrypoint

- Start every topic framing, drafting, script review, rough-cut audio/video review, cover preparation, or publication-desk task through the managed CLI:
  ```bash
  python -B self-media-creation-system/scripts/self_media_agent.py <subcommand> ...
  ```
- Before starting substantive work in a fresh workspace, run read-only diagnostics:
  ```bash
  python -B self-media-creation-system/scripts/self_media_agent.py doctor
  python -B self-media-creation-system/scripts/self_media_agent.py capabilities
  ```
- Do not bypass the state machine by drafting directly in chat, running ad-hoc `ffmpeg` commands outside the delivery pipeline, or hand-writing static HTML publication desks.

## 2. Anti-Skip & Human Fact-Confirmation Hard Gate

- **Lock topic facets first**: complete `entry_selection` / `topic-angle-decision` before moving into drafting.
- **Human fact confirmation (`locked_for_draft`)**: before entering Step 3 (drafting or rewriting), present an explicit **Fact & Core Stance Confirmation Checklist** (based on `skills/content-fact-card/SKILL.md`) to the human creator.
- Until the creator explicitly confirms and the fact card is stamped `canonical_status: locked_for_draft`, do NOT fabricate personal experiences, case incidents, or business metrics, and do NOT bypass the fail-closed drafting block.
- **Autonomous progression on `BLOCKED`**: when a gate script returns `BLOCKED` or reports missing prerequisites, inspect the structured error/status output, generate or repair the missing prerequisite artifacts autonomously (except where explicit human confirmation is required), and re-run the check until green. Never skip or silence a failing gate.

## 3. Quality Review & Verification Before Delivery

- Run the required editorial/compliance/anti-skip checks (including `C04` review and `check_self_media_contracts.py` when contracts/schemas change) before claiming a deliverable is ready.
- Never claim a check passed without actually running it and observing exit code `0`. Keep synthetic/fixture evidence distinct from real-world publication or live-service verification.

## 4. Managed Publication Desk & Manual-Only Boundary

- For any local publication desk / release-prep page, ALWAYS use the official generator:
  ```bash
  python -B self-media-creation-system/scripts/publication_desk.py init -> check --stage preparation -> render -> check --page-build
  ```
  backed by `self-media-creation-system/config/publication-platforms.v1.json` and `self-media-creation-system/templates/publication-desk/manual-desk.*`. Never hand-write custom static HTML.
- Respect the `manual-only` publication red line: prepare structured packages and checklists for human review and manual posting; never automate account login, CAPTCHA bypass, or unattended publishing.

## 5. Companion Toolchain & Privacy Guardrails

- Before invoking cross-repo capabilities (`mvp-video-pipeline`, `video-knowledge-pipeline`, `content-visual-studio`, `question-research-poc`, `artifact-lifecycle-core`, `ai-research-workflow`, `web-content-fetcher`), verify local availability via:
  ```bash
  python -B tools/public_toolchain.py init
  python -B tools/public_toolchain.py discover <owner>
  ```
  and match the pinned commits in `tools/public_toolchain.lock.json` and `requirements-owners.txt`.
- Never commit personal media assets, real customer/medical records, API keys, cookies, or machine-specific absolute paths into the repository. Configure local fonts, matting weights, and runtime directories through environment variables (`SELF_MEDIA_FONTS_DIR`, `COVER_DEPTH_FUSION_FONT`, `RVM_ROOT`, `SELF_MEDIA_RUNTIME_HOME`).
