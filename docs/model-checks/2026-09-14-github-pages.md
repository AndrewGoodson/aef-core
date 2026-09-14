# AEF repository GitHub Pages deployment — September 14, 2026

AEF is published directly from the public `AndrewGoodson/aef-core` repository at
<https://andrewgoodson.github.io/aef-core/>.

Deployment commit: `81d056608f20d0c7f7bfaef95c5e4f9237cee643`.
[Successful Pages run](https://github.com/AndrewGoodson/aef-core/actions/runs/34877751409).
GitHub Pages uses GitHub Actions with HTTPS enforced. The repository About website,
README links, canonical metadata and downloadable instructions use this URL.
The earlier separate site remains available but is no longer canonical.

## Publication

`.github/workflows/pages.yml` deploys changes under `site/` on `main` and permits
manual dispatch on `main`. Its artifact contains only the seven assets below.
Tests, reports and repository internals are excluded. Deployment permissions are
limited to the deployment job; checkout does not persist credentials.

## Verification

Checks were invoked manually from the local checkout, without GitHub CLI:

- Full Python suite: **3,300 passed, 25 skipped, 1 xfailed**, 266 warnings; exit 0.
- Strict mypy: 135 source files passed.
- Ruff lint and formatting checks passed; 332 files already formatted.
- JavaScript syntax checks and `git diff --check` passed.
- Local browser suite: **225 passed, 0 failed** before the final instruction URL correction.
- Live browser suite: **225 passed, 0 failed** against the final published assets.
- All seven live responses matched source SHA-256; zero uncaught website JavaScript errors.
- All six outbound destinations returned HTTP 200, including the now-public source repository.
- Chrome visual inspection confirmed the live product page, teal logo and 3D graph.

The saved suite covers 1440, 768, 390 and 320 CSS-pixel widths; every graph node
and workflow drill-down; movement, pause/resume, drag and keyboard controls;
reduced motion and offscreen suspension; Claude, Codex and Grok command previews;
path validation; clipboard success/failure/races; navigation, disclosures,
download bytes and layout overflow. A stale private-access sentence in the report
template was removed after the first live run, then the live suite was rerun.

Local evidence is retained under `output/playwright/2026-09-14-pages-local/`,
`output/playwright/2026-09-14-pages-live/` and
`output/playwright/2026-09-14-pages-live-final/`: action/expected-result ledgers,
JSON, screenshots, downloads and browser traces. Raw browser evidence remains
ignored by Git. Reproduce with the commands in `site/README.md`.

## Published asset fingerprints

| Asset | SHA-256 |
| --- | --- |
| `index.html` | `5a3cf620fcfb02d8744299900d8bb3ef2d2bf6746dc29d8178c0e68a6873bfc9` |
| `styles.css` | `b8d45dcd4b731193e4ace6dbfe934b06678327b7eb2bd03425707d587d6c700c` |
| `app.js` | `07340303d06339c650e19646d683d447ded7a838a4ee2c2439a85b354615a61e` |
| `graph.js` | `21a6985e64b5d12352dcb3054f13c5b6c9ce92a6bd694a35607982a6ac81a53e` |
| `logo.png` | `cb33600b8465181b1d5c0f2c8751334266bedcb2772f488737bbf2425b6867be` |
| `learning-protocol.txt` | `fa261f2dfe27f912627ca35d41549e78c29f8c83a15f217940e000a3a41a2c30` |
| `THIRD_PARTY_NOTICES.txt` | `7f64b3b699e27b406f1196c03ee8431ac56ed08451b6353cc2a776b5c489e748` |

## Scope

This verifies website publication and browser interactions in Chromium. It does
not execute target-repository integration, establish model learning gains, or
validate Safari, Firefox or physical mobile devices. The graph remains an
illustration. Evolution, live-model opt-in and promotion controls are unchanged.
