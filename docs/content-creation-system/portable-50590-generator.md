# Portable 50590 fixture generator

This document describes the portable generator component of the public content-contract 50590 fixture toolchain. It is a partial milestone providing byte-stable synthetic test fixture reproduction; it does not replace historical owner-review lineage, facade validation, catalog registration, or production review receipts.

## What it does

`self-media-creation-system/scripts/generate_content_contract_50590_fixtures.py` reproduces the two public synthetic 50590 owner fixture files:

- `self-media-creation-system/fixtures/content-contract-50590-owner.v1.json`
- `self-media-creation-system/fixtures/content-contract-50590-owner.v1.negative-cases.json`

The generated payloads preserve exact historical `FIRST` and `SECOND` field mappings, case ordering, `schema_version` declarations, and `synthetic_only: true` markers. All contained data is strictly synthetic test material.

## Baseline

The generator requires an explicit baseline JSON document via `--baseline`. The live exemplar `docs/content-creation-system/example-content-item.json` is not used: it represents the active schema exemplar rather than the historical 50590 baseline.

The prerequisite baseline is shipped directly in the repository at:

- `self-media-creation-system/fixtures/declared-synthetic-baseline.json`

This file is derived losslessly from the public positive fixture `content-contract-50590-owner.v1.json` at JSON pointer `/positive_cases/legacy_baseline`. Because it is shipped as a repository asset, direct execution of tests and generation requires no preliminary extraction step. The generator deep-copies the selected baseline and never mutates the source file.

### Optional: Deriving a Custom Baseline

For auditability or custom baseline derivation, the synthetic baseline can be re-extracted from the positive golden fixture using Python standard library:

```python
import json
from pathlib import Path

source = Path("self-media-creation-system/fixtures/content-contract-50590-owner.v1.json")
destination = Path("self-media-creation-system/fixtures/declared-synthetic-baseline.json")
baseline = json.loads(source.read_text(encoding="utf-8"))["positive_cases"]["legacy_baseline"]
destination.parent.mkdir(parents=True, exist_ok=True)
destination.write_text(
    json.dumps(baseline, ensure_ascii=False, indent=2) + "\n",
    encoding="utf-8",
    newline="\n",
)
```

This optional extraction is synthetic test setup. It confers no historical authority, adds no new schema definitions, and does not alter canonical validator behavior.

## Commands

### Running the Test Suite
The 12-test unit suite runs directly from the repository root using the shipped synthetic baseline:

```
python self-media-creation-system/tests/test_portable_50590_generator.py -f
```

### Running the Generator
Execute the generator from repository root with explicit `--baseline` and `--output-dir` arguments:

```
python self-media-creation-system/scripts/generate_content_contract_50590_fixtures.py --baseline self-media-creation-system/fixtures/declared-synthetic-baseline.json --output-dir <output-directory>
```

Both arguments are mandatory. The CLI provides no implicit default paths or environment fallbacks.

Expected outputs in `<output-directory>`:
- `content-contract-50590-owner.v1.json` (17 positive cases: 1 legacy baseline, 8 `FIRST` variations, 7 `SECOND` variations, 1 composite `all_fields`)
- `content-contract-50590-owner.v1.negative-cases.json` (26 negative-case matrix entries)

## Failure & Validation Semantics

- **Input Validation:** The baseline must be a valid JSON object containing an `intent` object. Malformed JSON or non-object roots raise `BaselineError` and terminate with exit code 2 before any output directory or file is touched.
- **Path Refusal:** The baseline path must not resolve to either final output file (`content-contract-50590-owner.v1.json`, `content-contract-50590-owner.v1.negative-cases.json`) or their temporary staging paths (`*.tmp`). Path collisions are rejected before writes.
- **I/O Refusal:** System errors such as `FileNotFoundError` or `PermissionError` propagate immediately; they are never suppressed, retried, or converted into false success.
- **Negative Matrix Semantics:** The 26 negative matrix entries include 21 declared schema-invalid rejects, 3 schema-valid facade-rejects, and 2 schema-valid accept controls. These are declared generator test labels, NOT runtime schema or facade validation executions.
- **Write Durability:** Files are written using same-directory temporary files (`.tmp`) followed by atomic rename (`replace`). This does not constitute an `fsync` flush, a two-file atomic transaction, or a TOCTOU concurrency guarantee.

## Scope & Rights

- **Milestone Scope:** Limited to the generator script, the 12-test unit suite, the shipped synthetic baseline, this documentation, and the root provenance record. Historical receipts, lineage bundles, live publishing workflows, and catalog promotions remain unbundled.
- **Verification Qualification:** Technical verification of byte reproducibility only; not an external author approval, content certification, or public release authorization.
- **License:** Distributed under existing Apache-2.0 terms (`LICENSE` and `NOTICE`). No vendored dependencies added.

## Historical Test-Header Note & Exit Code Qualification

### Historical Test-Header Note
The module docstring at `self-media-creation-system/tests/test_portable_50590_generator.py` lines 13–17 describes the earlier overlay as not shipping the baseline and asks the owner to derive it before running.

This text is a historical artifact from the initial three-file source overlay stage. In the current six-path assembled integration, the synthetic baseline is shipped directly at `self-media-creation-system/fixtures/declared-synthetic-baseline.json` (derived from the public `positive_cases/legacy_baseline`). The tested source, test, and baseline files remain byte-frozen to preserve SHA256 integrity. Readers and operators should follow the current repository layout: direct execution (`python self-media-creation-system/tests/test_portable_50590_generator.py -f`) operates out-of-the-box without requiring an external extraction prerequisite.

### Exit Status Assertion Scope
Inspection of `generate_content_contract_50590_fixtures.py` indicates that baseline validation failures (such as input-object or intent-object shape mismatches or alias collision errors) exit with code 2. The twelve-test unit test suite asserts generic non-zero exit status (`returncode != 0`) rather than specifically checking code 2. The documented runtime evidence remains the verified execution under Windows CPython 3.13.5 (12 passed, 0 skipped, exit code 0 on the clean baseline, and 1 expected failure with exit code 1 on the failfast mutant). No new test gates, assertion changes, or re-runs are introduced.
