# Self-media creation system: public workspace

This is the existing self-media framework in a portable workspace layout. It
selects a deliverable, audience and purpose, carries sourced feedback through
the applicable stages, and keeps research, author decisions and manual
publication boundaries distinct. No second router, database or renderer is added.

This is the reviewed first-party source edition, with private originals and
histories excluded. Its offline public-workspace suite passed 811 tests and
284 subtests, with 44 explicit skips. The complete contract checker also passed.
Read ACCEPTANCE.md for unavailable integrations and evidence boundaries; this
selected edition is not completion of the original full-project review.

## Layout

- `self-media-creation-system/`: framework scripts, schemas, templates and tests.
- `docs/content-creation-system/routing/`: the single 1.9.1 routing authority.
- `skills/`: generic first-party craft/editor contracts, without personal corpora.
- `tools/`: local metadata registry configuration and fixed public owner pins.

The shared `scripts/validate-content-operations.py` and
`docs/content-creation-system/operations-contract-set.v1.json` retain the existing
14-component operations contract mechanism. Public examples are explicitly
synthetic; see the operations README and PUBLIC-PROVENANCE.json. From the outer
workspace, `python scripts/validate-content-operations.py` validates only the
local synthetic contract set, without platform access or execution authority.

Legacy account/brand IDs in contracts are symbolic compatibility names, not
account identifiers or permission to impersonate an author. Use your own evidence,
identity, author confirmation and separately configured channel portfolio.

## Configure an isolated local workspace

Use an existing Python 3.12+ interpreter and an independent virtual environment.
Install `requirements.txt` into that environment. From the outer workspace:

```text
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
.venv/Scripts/python.exe tools/public_toolchain.py init
.venv/Scripts/python.exe tools/public_toolchain.py discover content-creation-system
```

On non-Windows systems use `.venv/bin/python`. The configuration helper creates
only an ignored local `tool-registry.json`, refuses to overwrite one, and never
clones, installs, runs owners or copies an approved channel strategy.

The fixed public owner commits are in `tools/public_toolchain.lock.json`. Obtain
only the owners needed for your chosen route, in the indicated sibling directories.
For the current synthetic cold-start tests, the QRP schema owner is needed under
`question-research-poc/`; ContentStudio core is needed under `content-studio-poc/`
for case/timing fixture bindings. Check each owner's own installation instructions.
For case/source-contract acceptance, install the fixed public owner packages in
`requirements-owners.txt` into the same venv; ContentStudio's declared Markdown
and QRP dependencies are required even when its validator is loaded from source.
The helper reports absent/unverified owners honestly. The complete pinned Git
installation path has not been tested on this Windows host; acceptance uses the
same reviewed public wheels and separately materialized public source trees.

## Existing entry points

From `self-media-creation-system/`, using the same environment:

```text
python scripts/self_media_agent.py capabilities
python scripts/self_media_agent.py doctor
python scripts/self_media_agent.py resolve --request fixtures/agent-entry/moments-short-post.request.json
python scripts/self_media_agent.py operations
```

These commands inspect metadata or resolve a synthetic route. `routing_ready` and
`metadata_contracts_ready` do not mean that content was written, evidence verified,
an external owner ran, or a human approved publication. With the indicated public
source owners configured, `python scripts/check_self_media_contracts.py --no-tests`
runs the existing complete public contract checker. `python -m pytest
self-media-creation-system/tests tests tools/test_public_toolchain.py` from the
outer workspace runs the public suite; explicitly missing owners remain skipped
or blocked, rather than being replaced by fabricated implementations.

Use purpose/audience/current-body references and stage duties from the current
context manifest. Carry the same sourced feedback into stage reviews. Choose the
applicable route; the canonical order is not a universal checklist. A transport
receipt cannot establish prose quality, emotion, author agreement or audience effect.

## Public scope and limitations

Private manuscripts, recordings, customer/health data, personal voice corpora,
real account portfolios, STATE, private inventories and operational receipts are
excluded. Two newly invented fixtures replace excluded working examples; their
confirmed/verified enum values are artificial unit-test states only.

Read [public owner boundaries](docs/public-owner-boundaries.md). The complete MVP
workflow consumer is not bundled, and local-rough-cut P0 is not a substitute.
Missing owner code or evidence blocks the corresponding route. No live model,
service, UI, real media, customer contact or platform publication was validated.

First-party public edition: Apache-2.0. Retained MIT notices are in `licenses/` and
`NOTICE`. Third-party Skills, gallery assets, fonts, music, models and binaries are
not distributed. See `SCAN-FINDINGS.json` for exact synthetic scanner exceptions;
default secret rules remain enabled. A clean scan is not proof of complete review.

The ContentStudio pin includes the source/installed WeChat formatter adapter.
Its separate external renderer is optional and not cloned or installed by
this framework. Main source, shared operations, selected source contracts and
synthetic feedback handoffs reuse the existing mechanisms. Platform publishing
is manual; actual content, evidence, authorship and channel authorization
must be supplied and reviewed for each use.
