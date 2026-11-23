# Browser Regression Source Collection Reference Guide

Target location: `self-media-creation-system/docs/browser-regression-source-collection.md`
License: Apache-2.0

## 1. Purpose
This document provides reference documentation for five first-party CommonJS browser regression scripts located in `../tests/`. These scripts preserve historical, current, and conditional browser-level regression assertions across publication workbench components, cover generation flows, and review interfaces.

This collection is distributed strictly as source code under Apache-2.0. It is **not** a turnkey runnable test suite. The scripts contain a mixture of current platform contracts, legacy UI fixtures, and conditional branches. Publishing this generic source does not require historical runtime recreation or rebuilding removed UI elements. Separate current entrypoints exist in `../tests/publication-platform-panels.cjs` and `../tests/publication-current-projects.cjs` and are neither modified nor replaced by this collection.

## 2. Five-Entry Specification Table

| Script (`../tests/...`) | Positional Arguments (argv) | Browser Runtime | Inputs Expected | Outputs Produced | Status (Current / Legacy / Conditional) |
|---|---|---|---|---|---|
| `content-cover-browser.cjs` | `argv[2]`: Playwright module<br>`argv[3]`: Chromium executable<br>`argv[4]`: Page directory | Explicit browser executable | `PAGE_DIRECTORY/封面比较与发布辅助页.html`<br>`PAGE_DIRECTORY/publication-data.json`<br>Local PNG images (3 candidates × 4 ratios) | `PAGE_DIRECTORY/content-matrix-desktop.png` and `content-matrix-mobile.png`<br>`PAGE_DIRECTORY/synthetic-saved-page.html`<br>`PAGE_DIRECTORY/content-browser-verification.json` (exclusive creation) | **Mixed**: Central cover matrix/shelf is legacy; JSON persistence, overflow checks, and network/error guards remain current. |
| `cover-workbench-browser.cjs` | `argv[2]`: Playwright module<br>`argv[3]`: Page HTML<br>`argv[4]`: Chromium executable<br>`argv[5]`: Screenshot path | Explicit browser executable | Single workbench HTML file (`PAGE_HTML`) with fixed 6-candidate scenario | Screenshot written to `SCREENSHOT_PATH` | **Mixed**: Removed PK gallery is legacy; export JSON data contract, prepared status, and field counts remain current. |
| `publication-desk-browser.cjs` | `argv[2]`: Playwright module<br>`argv[3]`: Single-item HTML<br>`argv[4]` (opt): Screenshot path<br>`argv[5]` (opt): 8-item HTML | Playwright default Chromium | `SINGLE_ITEM_HTML`<br>Optional 8-item HTML fixtures<br>Requires `../templates/publication-desk/manual-desk.js` | `os.tmpdir()` downloads/exports<br>Optional screenshot at `SCREENSHOT_PATH` | **Mixed**: Collection overview and PK gallery are legacy; platform card counts, scheduling, and JSON export/import are current. |
| `video-delivery-browser.cjs` | `argv[2]`: Playwright module<br>`argv[3]`: Complete HTML<br>`argv[4]`: Draft HTML<br>`argv[5]`: Import JSON | Playwright default Chromium | `COMPLETE_HTML`<br>`DRAFT_HTML`<br>`IMPORT_JSON` | Saved HTML copy at `<COMPLETE_HTML>.saved.html` (beside input) | **Current / Conditional**: Existing per-platform fields and draft-reset checks are retained; the complete-delivery scenario needs separately supplied, bound receipts and media. |
| `workflow-application-browser.cjs` | `argv[2]`: Playwright module<br>`argv[3]`: Input HTML<br>`argv[4]`: Output directory<br>`argv[5]` (opt): Review URL | Playwright default Chromium | `INPUT_HTML`<br>Optional external VKP review player endpoint (`REVIEW_URL`) | Reports, screenshots, and downloaded exports in `OUTPUT_DIR` | **Mixed / Conditional**: Data/copy checks remain useful; the old `.cover-shelf` assertions need their historical scenario. The optional review-player branch requires the appropriate external AGPL VKP surface, media and local-font behavior. |

## 3. Exact Command Invocations (Documentation Only — Never Executed)
The invocations below illustrate the non-normalized CLI signatures of each script. They are provided for specification documentation only; no dependencies or fixtures are pre-installed, and no test execution has taken place.

```text
# 1. content-cover-browser.cjs (Explicit browser binary and directory target)
node ../tests/content-cover-browser.cjs <PLAYWRIGHT_MODULE> <BROWSER_EXECUTABLE> <PAGE_DIRECTORY>

# 2. cover-workbench-browser.cjs (Explicit browser binary and explicit screenshot output)
node ../tests/cover-workbench-browser.cjs <PLAYWRIGHT_MODULE> <PAGE_HTML> <BROWSER_EXECUTABLE> <SCREENSHOT_PATH>

# 3. publication-desk-browser.cjs (Default Chromium; optional multi-item scenarios)
node ../tests/publication-desk-browser.cjs <PLAYWRIGHT_MODULE> <SINGLE_ITEM_HTML> [<SCREENSHOT_PATH>] [<EIGHT_ITEM_HTML>]

# 4. video-delivery-browser.cjs (Default Chromium; writes .saved.html alongside input)
node ../tests/video-delivery-browser.cjs <PLAYWRIGHT_MODULE> <COMPLETE_HTML> <DRAFT_HTML> <IMPORT_JSON>

# 5. workflow-application-browser.cjs (Default Chromium; recursive output directory; optional review URL)
node ../tests/workflow-application-browser.cjs <PLAYWRIGHT_MODULE> <INPUT_HTML> <OUTPUT_DIR> [<REVIEW_URL>]
```

## 4. Current Public Dependencies and Fixture Limits
The underlying repository at fixed public base `4348b1f` includes the following relevant source files:
- Renderer & logic scripts: `../scripts/publication_desk.py`, `../scripts/cover_workbench.py`, `../scripts/cover_strategy.py`
- Templates: `../templates/publication-desk/manual-desk.js`, `../templates/publication-desk/manual-desk.css`
- Fixture generation: `../tests/build_publication_panel_fixture.py`
- Current standalone regression suites: `../tests/publication-platform-panels.cjs`, `../tests/publication-current-projects.cjs`

### Fixture Limitations
- `build_publication_panel_fixture.py` supplies a real current-platform-panel synthetic fixture generator. Its existence does not establish that every historical PK/matrix scenario, exact multi-ratio dataset, complete media pack or human-bound delivery fixture has been supplied and verified for these five entries.
- Complete video delivery status verification in `video-delivery-browser.cjs` requires upstream context bindings and human approval receipts that are not bundled.
- Historical test outputs and private client data are excluded. Users must supply synthetic fixtures matching the scenario schemas.

## 5. Security, Isolation, and Unverified Behaviors
1. **Network Interception Limits**:
   - Four scripts register `^https?:` route handlers that abort matching requests. The workflow application script instead uses the URL-prefix exception described below; it is not a parsed origin/path allowlist.
   - In `workflow-application-browser.cjs`, route handling uses `url.startsWith(reviewURL)`. If `REVIEW_URL` is omitted, all HTTP(S) requests are aborted. **Caution**: Passing an empty string (`""`) matches all URLs and allows all requests through; an empty string must never be used to claim network isolation.
   - Script-level route aborting does not constitute operating system sandbox enforcement, DNS isolation, or process network confinement.
2. **File System Behavior**:
   - Several scripts write outputs adjacent to inputs (e.g., `<COMPLETE_HTML>.saved.html`) or inside `os.tmpdir()`. These writes can overwrite existing files at target paths.
   - Output paths are not isolated sandboxes. Operators must provide disposable synthetic directories.
3. **Execution Claims**:
   - Console `PASS` strings and report JSON flags (`status: 'passed'`) represent internal script completion conditions, not independent auditing or platform publication readiness.
   - No browser launch, runtime test execution, or network communication was performed in this source collection batch. Tests not run remain unverified.

## 6. Source, License, and Privacy Boundaries
- **License**: The scripts and documentation are licensed under Apache-2.0.
- **External Dependencies**: The optional review player branch in `workflow-application-browser.cjs` refers to functionality from the external Video Knowledge Pipeline (VKP) project under AGPL-3.0. This collection does not vendor VKP code, relicense AGPL components, or bundle external assets.
- **Fonts & Binaries**: Local font aliases such as `ReviewYouYuan` (referencing `local(YouYuan)` / `local(幼圆)`) rely on host operating system fonts; no font binaries or font licenses are distributed. Neither Chromium nor Playwright packages are included.
- **Privacy**: No private hostnames, client media, manuscripts, or proprietary credentials are contained within these sources.
## Recorded Verification for This Source Collection

All five source hashes match the earlier fully reviewed first-party snapshot.
Node 22.17.1 performed five sequential `--check` syntax checks, each exiting 0.
These commands did not import the modules, load Playwright or launch a browser.
The renderer, JS/CSS, workbench and public synthetic fixture-generator hashes
also match the earlier review. Eight referenced public dependency paths exist
at the stated fixed base; source presence is not runtime proof.

The 112 physical assertion-related anchors in the earlier five-file review are
source metadata, not 112 executed cases. Console strings and report flags have
not been produced by this batch. No fixture, browser, media, account, upload,
publication, network isolation or human approval has been validated here.

The invocation paths above are relative to this guide's `docs` directory.
Replace placeholders with actual caller-owned paths; the displayed placeholders
are specifications, not literal shell commands or automatic run instructions.
