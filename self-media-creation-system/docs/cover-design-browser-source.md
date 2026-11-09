# Legacy Cover PK Layout Smoke Script Reference Guide

## Overview
This guide documents the standalone first-party Apache-2.0 legacy cover PK-layout browser smoke source. It serves as a historical source reference; current platform pages no longer call the old PK gallery, and there is no requirement to rebuild it. Specified counts (7 candidates, 2 ratios, 6 collection fields) are scenario-specific smoke test parameters rather than platform-wide policies.

## Invocation & Positional CLI Arguments
The script must be invoked with three explicit positional arguments:
```text
node self-media-creation-system/tests/cover-design-browser.cjs <pw> <browserPath> <reviewDir>
```
1. `pw` (string): Absolute package directory or CommonJS entry point of a `require`-compatible Playwright module exporting `{ chromium }` (do NOT pass `package.json`).
2. `browserPath` (string): Absolute filesystem path to an explicit Chromium browser binary.
3. `reviewDir` (string): Absolute path to an operator-supplied, fully synthetic review directory.

Playwright and the browser are operator-provided runtimes; publishing this source increment does not install or launch them.

## Input & Output Contracts
The operator-supplied `reviewDir` must contain:
- `封面比较与发布辅助页.html` (entry HTML)
- `publication-data.json` (metadata JSON)
- Synthetic images referenced by the page, supplying seven images for each of two ratios (14 decoded placements; the script does not require 14 unique files).
This source increment does not distribute that legacy fixture, images, Playwright, or a browser runtime.

Outputs:
- Writes `smoke-3x4.png` and `smoke-16x9.png` directly into `reviewDir`, potentially overwriting existing files. Operators must run this only against disposable synthetic copies.

## Verification Steps & Assertions
1. **Desktop Viewport**: Initializes at 1440x1000 and asserts exactly 7 `.pk-card` elements exist.
2. **Ratio Checks**: Evaluates ratios `3:4` (expected 0.75) and `16:9` (expected 16/9):
   - Awaits `img.decode()` across all 7 images.
   - Asserts absolute aspect ratio tolerance `Math.abs(naturalWidth / naturalHeight - expected) < .002` (absolute difference, not percentage).
   - Captures `.cover-pk` screenshots to `smoke-3x4.png` and `smoke-16x9.png`.
3. **Mobile Viewport**: Resizes to 390x844 and asserts no horizontal overflow (`scrollWidth <= innerWidth + 1`).
4. **Metadata & Governance**:
   - Asserts exactly 6 input fields with label `合集名称` (`exact: true`).
   - Reads `publication-data.json`: asserts `items[0].cover_pk.selected === null` (no auto-selection), and for all candidates `design_method` is truthy and `generative_model_used === false`.
5. **Runtime Guards & Limitations**:
   - Listens to `pageerror` (asserted empty).
   - Intercepts and aborts `^https?:` requests (asserted empty). Note: Route interception does not provide complete OS/sandbox network isolation.
   - `chromium.launch` precedes the script's `try` block; launch failure reaches the outer error handler (exit 1) before that `finally`. No structured receipt is written; library cleanup is not established by this source review.
   - The final console `PASS` message is conditional output upon complete run, not proof of prior execution.

## Evidence limits
The source is byte-identical to the previously reviewed working snapshot and passes a Node syntax check. No browser run or fixture rendering was performed. Metadata assertions check supplied values; they do not establish real image provenance, actual model use, or licensing. The HTTP(S) route hook attempts to abort matching requests and records them; it is not proof of complete file, context, or OS isolation.
