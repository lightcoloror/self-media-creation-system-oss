# Public self-media Agent entry

The existing metadata/contract entry selects a deliverable and applicable route.
Run commands below from `self-media-creation-system/`. First configure the local
registry from the outer workspace with `python tools/public_toolchain.py init`.
No metadata, example or fixture grants model, account, contact or publication authority.

## Existing entry

`self-media-work-request.v1` selects an existing consumer; legacy requests select
one of the five managed recipes. Missing evidence fails closed.

```text
python scripts/self_media_agent.py doctor
python scripts/self_media_agent.py capabilities
python scripts/self_media_agent.py resolve --request <task.json> --output <selection.json>
python scripts/self_media_agent.py creation-route
python scripts/self_media_agent.py authoring
python scripts/self_media_agent.py publication-desk
python scripts/self_media_agent.py operations
```

Only use the selected route. Stage order is not a universal checklist. Real facts,
privacy treatment and scoped author confirmation are required by applicable gates.
The generic editor method is not a personal author profile.

## Immediate post-publication trigger

For a human-reported publication or metrics event, use
`python scripts/self_media_agent.py operations`. `record-publication` records an
actual human-reported live item, not a scheduled item. `record-snapshot` uses
48-72h early or 156-180h d7 windows; earlier metrics are provisional. A local record
does not publish, open platforms or establish a business result.

## Boundaries and continuation

Use `prepare-step`, exact input hashes and `verify-step-output`; use
`sequence-status` for the one valid next step. Transport does not prove semantic
review. Human gates cannot be self-approved. Retain purpose, audience, stage duty
and sourced feedback through the existing context and review contracts.

`doctor` covers metadata and synthetic resolution only. It does not run external
owners. See [public owner boundaries](../docs/public-owner-boundaries.md) for
unavailable consumers and fixed public commits. Full MVP is not bundled and
local-rough-cut P0 is not an equivalent workflow consumer.

Real manuscripts, recordings, author corpora, customer/health information,
operational receipts, STATE and private inventories are excluded. Candidate-only
research never becomes verified facts through schema or hash success.
