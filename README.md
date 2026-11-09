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

Read [public owner boundaries](docs/public-owner-boundaries.md). The complete first-party MVP owner is separately published and pinned; it is
not bundled into this workspace. local-rough-cut P0 is not a substitute.
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

## Public video owner connection (0.1.1)

The existing lock now selects Studio v0.1.3, VKP v0.1.2 and full first-party MVP
v0.8.1. Keep the indicated owner directory names; MVP installs as
`video-creation-pipeline`, not as a package called `mvp-video-pipeline`. The
optional requirements file pins those same public source commits. Its Git
installation route remains unverified on this Windows host; local acceptance
uses reviewed wheels and actual public Git objects/bytes.

`tools/public_toolchain.py init` still only writes the existing local registry,
refuses an existing one and does not clone/install/launch an Owner. `discover`
checks checkout identity separately from runtime. A source checkout matching its
pin is not approval to render, call models, handle private data or publish.

The public Governance v0.1.1 contract distribution is at
`https://github.com/lightcoloror/codex-local-governance-oss`, commit
`ba0bca6632979a35881583d531f4637593e2e66c`; its root bundle digest is
`cf97adbb27a97bee1fb846954721f671e1a922a2a2f3b7e130f234cdac652994`.
It is an optional metadata reference, not a newly registered execution Owner.
Its native review-packet integrations remain undistributed. P1 of
local-rough-cut remains outside this release and requires separate user review.

The pinned VKP also supplies the existing subtitle coverage consumer required
by the main video delivery path. The bounded synthetic composition passed
95 tests and 58 subtests; one explicit browser regression was not run. This
does not prove the separate VKP context-manifest script integration or any
real-media/author/platform outcome. Those limits remain visible in the Owner
boundaries and acceptance record.

## Native context and draft/cue owner pins (0.1.2)

The existing lock now selects VKP v0.1.3 and ContentStudio v0.1.4, alongside
full MVP v0.8.1. VKP's installed context decision API has eight native synthetic
handoff tests; Studio's four draft/cue adapters have66 Python checks and a
bounded2-second MP4/ASS native test. These separate Owner results are not a
claim that every command or complete private workflow has run here. The main
registry still reports runtime_verified=false until actual per-use evidence.
No Owner is cloned/installed/launched by discovery. The existing prerequisites,
purpose/fact/privacy/author gates and separate rough-cut P1 review remain.

For video routes, use Python >=3.12 and install the selected Owners' declared dependencies into the chosen environment. A clean pinned source checkout does not supply packages such as psutil by itself; the toolchain initializer performs no dependency installation.

## Current Studio Owner pin (0.1.4)

The existing lock selects released Studio0.1.8, including the existing synthetic
feedback intake, offline CMS/diagram contracts and explicit-runtime handdraw
planning adapters. Studio's scoped source/native/install receipts are separate
Owner evidence. No upstream gallery/image/style-index payload is bundled there;
the attribution license and unverified legacy rights remain explicit.

Main resolver/runtime source is unchanged. Discovery remains
runtime_verified=false; no command, browser, model, image generation, cleanup or
publication is launched/authorized by a source pin. Original research/author/
privacy/platform boundaries and separately review-gated rough-cutP1 remain.

## Historical provenance and unbundled references

`PROVENANCE.json` preserves 508 selected-file hashes from public snapshot
`34f6c1322391bc92253d763b9e03677402a2b869`; all 508 match that snapshot.
It is historical source provenance, not a current-tree integrity manifest.
For later revisions, use the chosen Git commit and tree. Original source hashes
and attribution are retained; they do not prove later runtime or rights approval.

Some historical validation/research records, operator brand/editing contracts,
and operator-dependent instructions are not distributed. The named
commercial-medical-insurance topic discovery card and the local grill-me
upstream/adaptation notes are now provided as public method references, adapted
from current first-party working Markdown with explicit source and adaptation
qualifications. The topic card keeps its commercial-medical-insurance scope,
search expressions and filter conditions, but replaces a private hardcoded
research-ledger path with an operator-provided authorized research
workspace/ledger. The grill-me note corrects the current upstream wording and
records that the exact historical local adoption revision is unverified; the
current MIT license does not prove an older adoption pin. Neither reference is
a claimed historical Git blob, and neither was verified as a live research or
interview run. Historical validation/research reports and operator-dependent
instructions remain unbundled and require the applicable external material.
The public adaptation was prepared on 2026-11-08 with DeepSeek Harness
(observed runtime ID deepseek-flash; precise internal version unverified);
original method authorship and the 2026-07-22 review date are unchanged.
Fewer broken links do not mean those methods, historical checks or real content
workflows were verified.

## Synthetic 50590 Fixture Generator

A portable fixture generator reproduces the byte-stable synthetic 50590 owner-review fixtures:

- Script: [`self-media-creation-system/scripts/generate_content_contract_50590_fixtures.py`](self-media-creation-system/scripts/generate_content_contract_50590_fixtures.py)
- Test Suite: [`self-media-creation-system/tests/test_portable_50590_generator.py`](self-media-creation-system/tests/test_portable_50590_generator.py)
- Shipped Baseline: [`self-media-creation-system/fixtures/declared-synthetic-baseline.json`](self-media-creation-system/fixtures/declared-synthetic-baseline.json)
- Documentation: [`docs/content-creation-system/portable-50590-generator.md`](docs/content-creation-system/portable-50590-generator.md)
- Provenance: [`FIXTURE_GENERATOR_PROVENANCE.json`](FIXTURE_GENERATOR_PROVENANCE.json)

### Usage

Run the 12-test suite directly from the repository root:
```
python self-media-creation-system/tests/test_portable_50590_generator.py -f
```

Generate fixtures into a target directory:
```
python self-media-creation-system/scripts/generate_content_contract_50590_fixtures.py --baseline self-media-creation-system/fixtures/declared-synthetic-baseline.json --output-dir <output-directory>
```

Scope is strictly synthetic fixture reproduction under Apache-2.0; it confers no production publishing authority or live workflow approval.


### Local publication platform panel runner source

The unchanged local panel browser runner is available with an existing synthetic fixture builder and an [operator guide](self-media-creation-system/docs/publication-platform-panels-runner.md). This source edition has syntax and dependency checks only; browser assertions, media playback, actual accounts and publishing remain unverified.
