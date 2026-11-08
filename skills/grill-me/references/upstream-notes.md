# Upstream Notes

## Provenance

- Repository: `https://github.com/mattpocock/skills`
- Upstream skills: `skills/productivity/grill-me` and `skills/productivity/grilling`
- License: MIT, copyright 2026 Matt Pocock
- Reviewed: 2026-07-22
- Public adaptation: DeepSeek Harness (observed runtime ID `deepseek-flash`; precise internal version unverified), 2026-11-08. The 2026-07-22 review date and the original local adoption remain unchanged.
- Current public pin from the frozen task source provenance (2026-11-08; not re-fetched live):
  `4ae2317ddb22b046e26455e4f9c9b3aaaf62212d`
  - `LICENSE`: https://github.com/mattpocock/skills/blob/4ae2317ddb22b046e26455e4f9c9b3aaaf62212d/LICENSE
  - `skills/productivity/grill-me/SKILL.md`: https://github.com/mattpocock/skills/blob/4ae2317ddb22b046e26455e4f9c9b3aaaf62212d/skills/productivity/grill-me/SKILL.md
  - `skills/productivity/grilling/SKILL.md`: https://github.com/mattpocock/skills/blob/4ae2317ddb22b046e26455e4f9c9b3aaaf62212d/skills/productivity/grilling/SKILL.md

At this current pin, upstream `grill-me` is a thin, user-invoked wrapper that calls the reusable `grilling` skill. Current upstream `grilling` is not a one-question-at-a-time interview: it maps the plan or design as a tree, computes a frontier of questions whose prerequisites are already settled, asks the whole frontier in numbered rounds with a recommended answer per question, waits for the user's answers, and then recomputes the next round. It also dispatches a fresh-context sub-agent to find environment facts instead of asking the user for facts it can look up, and leaves the decisions to the user until shared understanding is reached.

The earlier statement that the upstream core "asks one question at a time" is inaccurate for the current upstream; it is corrected here and may have described an older revision that was not re-verified. The exact local historical adoption revision is unverified: the current MIT license does not prove which older upstream revision was adopted locally, and this note does not claim that every historical upstream revision was verified.

## Local Adaptation

The local version inlines the core because cross-skill invocation metadata is not equally reliable across agent runtimes. It also adds:

- Consequential-question filtering.
- Explicit stop phrases and a no-overquestioning boundary.
- A compact decision closeout.
- Separation of facts, assumptions, recommendations, and user decisions.
- A privacy boundary for environment exploration.
- Local routing to `brainstorming` or `writing-plans` after clarification.

The local adaptation deliberately does not copy the current upstream round/frontier mechanism, its multi-question rounds, or its sub-agent fact dispatch. The main local `material-interview` skill (`self-media-creation-system/skills/material-interview/SKILL.md`) is a local single-neutral-question content interview for self-media material, not design grilling. This note therefore does not recommend story answers, does not ask the user to wait for an exhaustive question frontier, and does not auto-launch sub-agents.

Do not treat upstream invocation fields such as `disable-model-invocation` as portable authorization. The local description, UI policy, runtime route, and workspace safety rules control invocation and execution.

## Scope of this note

This is a first-party compatibility and provenance note. It installs or enables no Skill, is not the upstream Skill text, and does not distribute any upstream Skill implementation. The consumer local skill files remain byte-identical; this note only documents lineage, the current pinned public source, and known limits.
