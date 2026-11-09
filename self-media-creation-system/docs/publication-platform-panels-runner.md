# Local publication platform panel browser runner — source edition

`tests/publication-platform-panels.cjs` checks a declared local, single-item, five-platform publication-desk scenario. It uses the existing `templates/publication-desk/manual-desk.js` and the existing public `tests/build_publication_panel_fixture.py`. It does not open a platform publishing console or upload content. No new renderer, route, player, fixture generator or approval gate is introduced.

The source is unchanged from a previously reviewed first-party working snapshot, SHA-256 `0294a575cd8aa3a5e53638fc4dd17b0a46d3cadf3ce8f3b11d733ee59318bc4e`. It is not represented as a fixed historical Git blob. The four existing public dependencies were hash-matched to the accepted static review. Root Apache-2.0 applies to this source; no Playwright, browser, font or media payload is bundled by this increment.

## Existing prerequisites and synthetic inputs

Use an existing suitable Node runtime, a trusted operator-selected Playwright module, and an already installed Microsoft Edge available through Playwright's `msedge` channel. The runner has no browser-executable argument: it retains `chromium.launch({headless:true, channel:'msedge'})`. The public fixture builder also needs an existing Python/Pillow and its existing publication-desk dependencies. No install or browser setup is performed by this source edition.

The public builder creates synthetic PNG covers, `fixture.json`, `fixture.html`, `primary-fixture.png` and an intentionally unplayable MP4 placeholder. Its small images and placeholder exercise file references and page elements; they are not approved covers or playable video deliverables. Use only this synthetic scenario or an explicitly reviewed compatible local input, not real accounts, customer records or manuscripts.

## Command shape

Run from the repository root. These examples were **not executed** for this source publication. Replace the illustrative Playwright path with an existing trusted module path and choose new caller-owned output directories; do not overwrite an existing project.

```powershell
$fixtureOutput = Join-Path (Get-Location) 'synthetic-panel-fixture'
$results = Join-Path (Get-Location) 'synthetic-panel-results'
$playwrightModule = 'C:/operator-supplied-runtime/node_modules/playwright'
python -B .\self-media-creation-system\tests\build_publication_panel_fixture.py $fixtureOutput
node .\self-media-creation-system\tests\publication-platform-panels.cjs $playwrightModule (Join-Path $fixtureOutput 'fixture.html') $results
```

The positional arguments after the script are the trusted Playwright module, input HTML, result directory, and optional primary PNG. If the last argument is omitted, the runner selects `primary-fixture.png` beside the input HTML. Its relative require of the desk logic works from the public module's existing tests/templates layout.

## What the existing assertions cover

The runner checks the five platform panels and their initial disclosure state, per-platform video element/path fields and assigned cover IDs, expand/collapse behavior, an independent primary image versus A/B/F test slots, per-platform candidate selections, exported JSON preservation, saved-page reopening and horizontal overflow at a 412-pixel viewport. Existing assertions and the three-candidate/five-platform scenario constants are preserved. They do not establish that every project or current platform account uses those counts or rules.

Displayed image IDs are compared with the platform's permitted ID list. This runner does **not** decode images, verify natural aspect ratios or minimum cover size, or test video playback. Taking screenshots is not visual-quality acceptance. It is a bounded existing component, not the proposed extended P1 round-trip/preparation test plan, the full nine-suite migration, a complete-delivery audit, CTA review or VKP player acceptance.

The code navigates file URLs in a fresh browser context, aborts and records page HTTP(S) request attempts using its existing route, and asserts that no such attempts or page errors were collected. This is not an operating-system or all-protocol network sandbox, and does not authorize arbitrary untrusted HTML or use of signed-in browser profiles.

## Outputs and failure limits

If actually run, it writes screenshots, edited JSON, a saved HTML page and `browser-report.json` under the caller's result directory. It does not anonymize input pages: using private pages could place private content in those outputs. No such pages were loaded in this batch.

Module loading and browser launch occur before the main try/catch. Bootstrap or close/write failures can leave no final report; retain the original stderr/exit and stop the affected step rather than weakening security settings, changing permissions or trying a different runtime to bypass a refusal. A generated report's `status: passed`, if achieved in a future run, covers only this runner's assertions. Its existing `uploads:false` and `published:false` fields are not evidence of a real publication or human acceptance.

## Actual verification and remaining conditions

This source edition reused the exact accepted static source review, checked the public dependency hashes and relative imports, reviewed the source/documentation for sensitive references, and ran **only** nonexecuting `node --check` with Node `v22.17.1` (exit 0). The source was not required or executed; the fixture builder, browser, screenshots and page assertions were not run. No installed-package, actual runtime, UI, account, real content, image geometry, media or publishing acceptance is claimed.
