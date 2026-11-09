# Archived CTA Review Browser Regression Reference

Target: `self-media-creation-system/tests/cta-review-browser.cjs`
License: Apache-2.0

## Overview
This document describes the legacy browser regression script for historical Call-to-Action (CTA) review interactions. Current platform rendering (`scripts/publication_desk.py`) does not generate `#cta-review-status` or `.cta-review` DOM elements; this source is preserved solely as an archived reference under Apache-2.0, not as an active runnable acceptance suite.

## Positional Arguments and Execution
The script expects four explicit positional arguments:
1. `argv[2]`: Path to a `require`-compatible Playwright package exporting `{ chromium }`.
2. `argv[3]`: File path to a prepared local HTML review page.
3. `argv[4]`: File path to a missing-plan local HTML page.
4. `argv[5]`: File path to an invalidating local JSON data file.

During execution, the script launches headless Chromium, navigates local file URLs, and saves an export copy to `<argv[3]>.saved.html` beside the input, potentially overwriting existing files at that path. This increment bundles neither a browser/Playwright package nor matching legacy CTA fixtures.

## Preserved Invariants and Assertions
The script retains 12 physical assertion anchors across a single test flow:
- **State Progression**: Asserts missing-plan HTML initializes with `#cta-review-status` in `pending` state; prepared HTML initializes in `prepared` state while `#delivery-status` remains `draft`.
- **Content Inspection**: Validates independent interaction (`互动 · 采用`) and acquisition (`获客 · 不采用`) decision labels, alongside body text placement.
- **State Invalidation**: Verifies that editing platform body copy, reopening exported HTML, or importing JSON files resets `#cta-review-status` to `pending`.
- **Runtime Guards**: Accumulates unhandled page errors and aborts outbound `http(s):` requests, asserting both arrays remain empty.

## Operational Boundaries
The final console JSON payload is a script self-declaration, not verification of platform publication, human approval, or OS-level network isolation. Matching legacy fixtures and browser execution remain unverified. Owner nonexecuting Node syntax check completed with exit 0; it did not load Playwright or run the assertions. The archived source states expected DOM behavior, not proof that a historical UI ever passed it. Caller package initialization is outside the later context-level HTTP(S) route interception.
