# AEF product website

Public URL: <https://andrewgoodson.github.io/aef-core/>

This directory is the canonical website source. The public
[`AndrewGoodson/aef-core`](https://github.com/AndrewGoodson/aef-core) repository
publishes it directly through [the Pages workflow](../.github/workflows/pages.yml).
Changes to `site/` on `main` deploy automatically; a manual Actions run is also
available. The earlier `aef-core-site` publication is no longer canonical.

## Preview and check

From the aef-core checkout:

```sh
.venv/bin/python -m http.server 8765 --bind 127.0.0.1 --directory site
```

Open `http://127.0.0.1:8765`. There are no build dependencies, remote fonts,
analytics, model calls or submitted forms. The target path stays in the page;
copying the command is an explicit clipboard action. The graph is an explainer.

Before publishing, manually check desktop and mobile layouts, all graph steps,
actual node movement, pause/resume, drag and keyboard rotation, reduced motion,
offscreen suspension, each harness command, a path containing spaces, rejected
invalid paths, clipboard behavior, keyboard focus and the instruction download.
Run both JavaScript syntax checks and the repository's full green bar before
committing changes to aef-core. See
[methodology and evidence](../docs/graph-and-learning.md).

Activate the environment before the checks: test subprocesses invoke `python`
and `ruff` by name. Calling `.venv/bin/pytest` alone does not put them on `PATH`.

```sh
source .venv/bin/activate
pytest -q
mypy --strict aef
ruff check .
ruff format --check aef tests examples
node --check site/app.js
node --check site/graph.js
```

Check each exit code before continuing; a later successful command must not
hide an earlier failure.

## Saved click-by-click browser tests

[Latest product presentation verification and complete action ledger](../docs/model-checks/2026-09-12-aef-product-presentation.md).
[Original defect reproductions](../docs/model-checks/2026-09-12-site-drilldowns.md).

[`tests/drilldowns.mjs`](tests/drilldowns.mjs) drives a real Chromium browser
through every website link and control at 1440, 768, 390 and 320 CSS pixels.
It checks all six sphere clicks and selector details, all four workflow panels
against exact expected text, keyboard activation, drag/reset, a full rotation,
motion preferences, offscreen suspension, all three command variants, validation,
clipboard success/failure/races, disclosure open/close, download bytes, navigation
and the seven published asset hashes. The canvas probe observes rendered label
coordinates; tests still use real pointer clicks rather than calling handlers.

Install the pinned browser tool under ignored scratch space (no website or
Python runtime dependency), with Node.js 20 or newer:

```sh
npm install --prefix .scratch/site-browser --no-audit --no-fund playwright@1.62.1
node .scratch/site-browser/node_modules/playwright/cli.js install chromium
```

Start the local server above in one terminal. In another, from the repo root:

```sh
HEADED=1 \
PLAYWRIGHT_MODULE="$PWD/.scratch/site-browser/node_modules/playwright/index.mjs" \
node site/tests/drilldowns.mjs
```

For the deployed site, repeat with
`SITE_URL=https://andrewgoodson.github.io/aef-core/` in the environment.
Omit `HEADED=1` for headless execution. A failed assertion exits nonzero.
Each run saves its action/expected-result ledger as JSON and Markdown, full-page
and graph screenshots, failed-step screenshots, downloaded instructions, and
Playwright traces under `output/playwright/<timestamp>/`. Set `TEST_OUTPUT` to
choose a distinct run directory; reusing one overwrites that run's artifacts.
Open a trace with:

```sh
node .scratch/site-browser/node_modules/playwright/cli.js show-trace output/playwright/<run>/1440px-trace.zip
```

The suite checks outbound links through actual navigation and records HTTP
status separately. External availability is
not guaranteed by a passing interaction check; inspect that report section.
Widths simulate responsive layouts in Chromium, not Safari, Firefox or physical
mobile devices. Test paths are synthetic; no integration command is executed.
Raw browser evidence stays local and out of publication. Commit a curated report
under `docs/model-checks/` with findings, results and evidence paths.

## Publish a website update

1. Review the copy and links, then run the checks above.
2. Commit and push the reviewed changes to `main` with Git. Do not use GitHub
   CLI. The **Deploy AEF website** workflow runs when `site/` or the workflow
   changes; use **Run workflow** in Actions to redeploy an existing revision.
3. The workflow stages only `index.html`, `styles.css`, `app.js`, `graph.js`,
   `logo.png`, `learning-protocol.txt` and `THIRD_PARTY_NOTICES.txt`. Tests,
   reports and other repository files are excluded from the Pages artifact.
4. Check the workflow's `github-pages` deployment, run the saved browser suite
   against the public URL, and compare all seven served assets with source
   before reporting a deployment live.

Repository Settings → Pages → Source must be **GitHub Actions**. Deployment
uses GitHub's scoped workflow token, without a personal publication token or a
second repository. To roll back, revert the site change on `main` and let the
workflow publish the reviewed revision.

## Moving graph provenance

The hero adapts the canvas projection, orbital rings and glowing node rendering
from `Contoso-State/red-team-agent-orchestration`'s
`doc/assets/mission-orbit.html`, commit
`953b01d85fac9a6af45618e3f093f08cf5c647ba`. The upstream MIT notice ships in
`THIRD_PARTY_NOTICES.txt` and is linked beside the graph.

The AEF topology is the generated sequential persona flow: retrieve →
prompt agent → reflect → consolidate → END. Dashed spokes represent shared
state, not execution routes. Motion illustrates structure; it does not connect
to a runtime, perform a model call or claim measured learning gains.

Select a node through the dropdown or click its sphere. Drag horizontally to
rotate; focus the canvas for arrow keys and Home. Vertical touch scrolling
remains available. Pause freezes all automatic motion; explicit manipulation
still works. Reduced-motion preference starts the graph paused and is respected
when changed while open. Animation frames stop when hidden or offscreen.

## Teal identity and 3D presentation

`logo.png` is the AEF learning-loop mark: interlocking teal and mint ribbons
turn upward at their crossing. The transparent PNG also serves as the favicon.
The site uses proportional sans-serif typography, including commands and graph
labels. Headlines describe the workflow and its limits directly.

The graph uses real XYZ coordinates with perspective projection onto Canvas 2D.
Depth-sorted, shaded spheres and great-circle orbital planes expose its volume;
automatic yaw completes a full rotation, with a small pitch drift. It remains
an illustrative graph, not a live runtime viewer. No WebGL dependency is needed.

## Logo generation

Created with the built-in image-generation tool. The generated transparent PNG
is stored unchanged in this directory. Final prompt:

> Create one polished original logo symbol for AEF, an agent learning framework.
> Symbol only, no text. A bold continuous ribbon makes two interlocking asymmetric
> loops, with a small upward opening suggesting learning, returning, and progressing.
> Invent a distinctive simple silhouette, compact and balanced, strong enough to
> recognize at 40 pixels. Two flat rich colors: deep teal #087F83 and luminous mint
> #5CE6D1; clever clean negative space at the crossover. Professional identity
> design, precise geometry, rounded but confident curves, flat vector-like solid
> fills. Actual transparent background. Fill about 85 percent of square canvas.
> No letter A, no brain, no circuit board, no node dots, no sparkle, no glow, no
> gradient, no shadows, no 3D mockup, no typography, no border, no presentation
> sheet. Deliver a single finished symbol.
