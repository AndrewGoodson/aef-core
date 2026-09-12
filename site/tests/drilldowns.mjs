#!/usr/bin/env node
// Browser actions drive the public UI. Canvas instrumentation only observes pixels/text.
// Test-only Playwright dependency; see site/README.md for a clean-checkout command.
import assert from 'node:assert/strict';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { resolve, dirname } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE
  ? pathToFileURL(resolve(process.env.PLAYWRIGHT_MODULE)).href : 'playwright');
const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
const base = process.env.SITE_URL || 'http://127.0.0.1:8765/';
const out = resolve(process.env.TEST_OUTPUT || `${root}/output/playwright/${new Date().toISOString().replace(/[:.]/g, '-')}`);
await mkdir(out, { recursive: true });
const browser = await chromium.launch({ headless: process.env.HEADED !== '1' });
const results = [], external = [], errors = [];
let page, context, profile = '', index = 0;
const graph = [
  ['state', 'AEF', 'Each workflow node reads AEFState and returns a StateDelta plus its next route.'],
  ['retrieve', '01', 'Retrieve relevant memory through injected services. Stored lessons remain fallible evidence.'],
  ['prompt', '02', 'Call the configured model inside an explicitly nondeterministic node. Tools need target wiring.'],
  ['reflect', '03', 'Inspect the outcome. Rule-based reflection is implemented; optional LLM reflection defaults off.'],
  ['consolidate', '04', 'Update knowledge through injected services. This does not train weights or establish task gains.'],
  ['end', '✓', 'Finish this graph run. There is no automatic route back, self-rewrite or automatic merge.']
];
const details = {
  retrieve: ['CONTEXT', 'Bring relevant context into the run.', "The memory-backed retriever supplies context through injected services. Retrieved lessons remain fallible evidence; they cannot grant permissions or override the owner's instructions."],
  prompt: ['REASONING', 'Give reasoning an explicit boundary.', 'The prompt-agent node calls the configured provider and is declared nondeterministic. Native persona settings are reported, not automatically obeyed. Tools and containment still require explicit target wiring and verification.'],
  reflect: ['FEEDBACK', 'Inspect the outcome before keeping advice.', 'Rule-based reflection is implemented. Optional LLM-backed reflection is off by default and has not shown task gains in existing trials. A critique is evidence to evaluate, not proof that the next answer will improve.'],
  consolidate: ['KNOWLEDGE', 'Make useful context available for later work.', "The consolidation node updates knowledge through injected services. It does not train model weights or create a knowledge graph. Persistent storage and cross-run reuse depend on the target's service configuration."]
};
async function step(action, expected, run) {
  const id = `${profile}-${String(++index).padStart(3, '0')}`;
  const start = Date.now();
  try {
    await run();
    results.push({ id, action, expected, status: 'PASS', ms: Date.now() - start });
    console.log(`PASS ${id} ${action}`);
  } catch (error) {
    const screenshot = `${id}-failure.png`;
    await page.screenshot({ path: `${out}/${screenshot}`, fullPage: true }).catch(() => {});
    results.push({ id, action, expected, status: 'FAIL', error: error.message, screenshot, ms: Date.now() - start });
    console.log(`FAIL ${id} ${action}: ${error.message}`);
  }
  await writeFile(`${out}/results.json`, JSON.stringify({ base, results, external }, null, 2));
}
const text = selector => page.locator(selector).textContent();
const pixels = () => page.locator('#orbit').evaluate(el => el.toDataURL());
const positions = () => page.evaluate(() => JSON.stringify(window.drawn));
async function pause() {
  await page.locator('#orbit').scrollIntoViewIfNeeded();
  if (await page.locator('#motion').getAttribute('aria-pressed') !== 'true') await page.locator('#motion').click();
}
async function panel(id) {
  assert.deepEqual(await Promise.all(['#node-tag', '#node-title', '#node-description'].map(text)), details[id]);
  assert.deepEqual(await page.locator('[data-node][aria-pressed="true"]').evaluateAll(els => els.map(el => el.dataset.node)), [id]);
  assert.deepEqual(await page.locator('[data-node].active').evaluateAll(els => els.map(el => el.dataset.node)), [id]);
}
async function bounded() {
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, 'Horizontal overflow');
  const box = await page.locator('#orbit').boundingBox();
  for (const [label, { x, y, width }] of await page.evaluate(() => Object.entries(window.drawn))) {
    assert.ok(x - width / 2 >= 0 && x + width / 2 <= box.width && y >= 0 && y + 12 < box.height, `Clipped canvas label: ${label}`);
  }
}
try {
  for (const width of [1440, 768, 390, 320]) {
    profile = `${width}px`; index = 0;
    context = await browser.newContext({ viewport: { width, height: 1000 }, deviceScaleFactor: width < 500 ? 2 : 1, reducedMotion: 'reduce' });
    await context.tracing.start({ screenshots: true, snapshots: true, sources: true });
    await context.addInitScript(() => {
      window.drawn = {}; window.drawCount = 0;
      const fill = CanvasRenderingContext2D.prototype.fillText;
      CanvasRenderingContext2D.prototype.fillText = function(label, x, y, ...rest) {
        window.drawn[label] = { x, y, width: this.measureText(label).width };
        window.drawCount++;
        return fill.call(this, label, x, y, ...rest);
      };
    });
    page = await context.newPage();
    page.setDefaultTimeout(7000);
    page.on('pageerror', error => errors.push(`${profile}: ${error.message}`));
    await page.goto(base, { waitUntil: 'networkidle' });
    await step('Load page and logo', 'Both logos decode; motion starts paused for reduced-motion preference', async () => {
      assert.equal(await page.title(), 'AEF · A learning loop for your agents');
      assert.equal(await page.locator('img.brand-mark').count(), 2);
      assert.ok(await page.locator('img.brand-mark').evaluateAll(els => els.every(el => el.complete && el.naturalWidth === 1254)));
      assert.equal(await page.locator('#motion').getAttribute('aria-pressed'), 'true');
      assert.equal(await page.locator('#orbit-node').isDisabled(), false);
    });
    await step('Tab to Skip to content; press Enter', 'First keyboard stop is the skip link; Enter reaches main', async () => {
      await page.keyboard.press('Tab');
      assert.equal(await page.locator('.skip').evaluate(el => el === document.activeElement), true);
      await page.keyboard.press('Enter');
      assert.equal(new URL(page.url()).hash, '#main');
    });
    const links = [
      ['header .brand', '#'], ['nav a[href="#architecture"]', '#architecture'],
      ['nav a[href="#learning"]', '#learning'], ['nav a[href="#research"]', '#research'],
      ['nav a[href="#integrate"]', '#integrate'], ['.actions a[href="#integrate"]', '#integrate'],
      ['.actions a[href="#architecture"]', '#architecture'], ['.closing a', '#integrate'], ['footer .brand', '#']
    ];
    for (const [selector, hash] of links) await step(`Click ${selector}`, `Navigate to ${hash} and scroll destination into view`, async () => {
      await page.locator(selector).click();
      assert.equal(new URL(page.url()).hash, hash === '#' ? '' : hash);
      await page.waitForFunction(hash => hash === '#' ? scrollY < 2 : (() => {
        const box = document.querySelector(hash).getBoundingClientRect();
        return box.top >= -2 && box.top < innerHeight;
      })(), hash);
    });
    await pause();
    await page.locator('#orbit-reset').click();
    for (const [id, short, copy] of graph) await step(`Click ${id} sphere`, `Picker selects ${id}; exact explanatory text appears`, async () => {
      const box = await page.locator('#orbit').boundingBox();
      const point = await page.evaluate(label => window.drawn[label], short);
      await page.mouse.click(box.x + point.x, box.y + point.y - 0.5);
      assert.equal(await page.locator('#orbit-node').inputValue(), id);
      assert.equal(await text('#orbit-description'), copy);
    });
    for (const [id, , copy] of [...graph].reverse()) await step(`Select ${id} in Inspect node`, 'Same exact detail through the accessible selector', async () => {
      await page.locator('#orbit-node').selectOption(id);
      assert.equal(await text('#orbit-description'), copy);
    });
    await step('Use keyboard to select END in Inspect node', 'Native selector keyboard path updates END detail', async () => {
      await page.locator('#orbit-node').focus();
      await page.keyboard.press('e');
      await page.keyboard.press('Tab');
      await page.waitForFunction(() => document.querySelector('#orbit-node').value === 'end');
      assert.equal(await text('#orbit-description'), graph[5][2]);
    });
    await step('Drag graph; release; click Reset view', 'Drag changes projection, release freezes it, Reset restores original coordinates', async () => {
      await page.locator('#orbit-reset').click();
      const selected = await page.locator('#orbit-node').inputValue();
      const before = await positions(), box = await page.locator('#orbit').boundingBox();
      await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
      await page.mouse.down();
      await page.mouse.move(box.x + box.width / 2 + 55, box.y + box.height / 2 + 18, { steps: 8 });
      await page.mouse.up();
      assert.notEqual(await positions(), before);
      const stopped = await pixels();
      await page.waitForTimeout(150);
      assert.equal(await pixels(), stopped);
      await page.locator('#orbit-reset').click();
      assert.equal(await positions(), before);
      assert.equal(await page.locator('#orbit-node').inputValue(), selected, 'Reset should preserve selection');
    });
    for (const key of ['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown']) await step(`Focus graph; press ${key}, then Home`, 'Arrow rotates; Home restores initial projection', async () => {
      await page.locator('#orbit').focus();
      const before = await positions();
      await page.keyboard.press(key);
      assert.notEqual(await positions(), before);
      await page.keyboard.press('Home');
      assert.equal(await positions(), before);
    });
    await step('Rotate one complete revolution with arrow keys', 'All sphere labels remain inside the canvas; no page overflow', async () => {
      for (let turn = 0; turn < 43; turn++) { await page.keyboard.press('ArrowRight'); await bounded(); }
      await page.keyboard.press('Home');
    });
    await page.locator('.hero-graphic').screenshot({ path: `${out}/${profile}-graph.png` });
    for (const id of Object.keys(details)) await step(`Click workflow step ${id}`, 'Exact tag, title and description; one active/pressed button', async () => {
      await page.locator(`[data-node="${id}"]`).click(); await panel(id);
    });
    for (const [id, key] of [['prompt', 'Enter'], ['reflect', 'Space'], ['retrieve', 'Enter']]) await step(`Focus ${id}; activate with ${key}`, 'Keyboard opens the same detail and exclusive selection', async () => {
      await page.locator(`[data-node="${id}"]`).focus(); await page.keyboard.press(key); await panel(id);
    });
    await page.locator('#architecture').screenshot({ path: `${out}/${profile}-steps.png` });
    await context.grantPermissions(['clipboard-read', 'clipboard-write']);
    for (const harness of ['claude', 'codex', 'grok']) await step(`Choose ${harness}, enter path with spaces, click Copy`, 'Correct native command, exact clipboard contents, success status', async () => {
      await page.locator('#harness').selectOption(harness);
      await page.locator('#target').fill('/absolute/test repo/learning');
      const expected = `${harness === 'codex' ? '$' : '/'}target-repo "/absolute/test repo/learning"`;
      assert.equal(await text('#command'), expected);
      await page.locator('#copy').click();
      await page.waitForFunction(() => document.querySelector('#command-status').textContent.startsWith('Copied.'));
      assert.equal(await page.evaluate(() => navigator.clipboard.readText()), expected);
    });
    for (const path of ['', '/', '//', '///', 'relative/repo', '~/repo', '/a"b', '/a\\b']) await step(`Enter invalid path ${JSON.stringify(path)}`, 'Copy disabled, aria-invalid true, explanatory status', async () => {
      await page.locator('#target').fill(path);
      assert.equal(await page.locator('#copy').isDisabled(), true);
      assert.equal(await page.locator('#target').getAttribute('aria-invalid'), 'true');
      assert.equal(await text('#command'), 'Enter an absolute directory to preview the command.');
    });
    await step('Correct path after validation error', 'Copy re-enabled, invalid flag cleared, preview restored', async () => {
      await page.locator('#target').fill('/absolute/test repo/learning');
      assert.equal(await page.locator('#copy').isDisabled(), false);
      assert.equal(await page.locator('#target').getAttribute('aria-invalid'), 'false');
    });
    await step('Click terminal guide open, closed; reopen with keyboard', 'Disclosure exposes exact mechanical command and collapses cleanly', async () => {
      const summary = page.locator('.terminal-guide summary'), code = page.locator('.terminal-guide pre');
      assert.equal(await code.isVisible(), false);
      await summary.click();
      assert.equal(await code.isVisible(), true);
      assert.equal(await code.textContent(), "python3 -I -B /absolute/path/to/aef-core/scripts/target_repo.py '/absolute/path/to/your repo'");
      await summary.click(); assert.equal(await code.isVisible(), false);
      await summary.focus(); await page.keyboard.press('Enter'); assert.equal(await code.isVisible(), true);
      await page.keyboard.press('Space'); assert.equal(await code.isVisible(), false);
    });
    await step('Click Download learning instructions', 'Download filename and all bytes match the source instructions', async () => {
      const [download] = await Promise.all([page.waitForEvent('download'), page.getByRole('link', { name: 'Download learning instructions' }).click()]);
      assert.equal(download.suggestedFilename(), 'learning-protocol.txt');
      const saved = `${out}/${profile}-learning-protocol.txt`;
      await download.saveAs(saved);
      assert.deepEqual(await readFile(saved), await readFile(`${root}/site/learning-protocol.txt`));
    });
    await step('Click MIT notice; use browser Back', 'Full MIT notice loads and Back returns to the site', async () => {
      await page.getByRole('link', { name: 'MIT notice', exact: true }).click();
      await page.waitForURL('**/THIRD_PARTY_NOTICES.txt');
      assert.equal((await page.locator('body').innerText()).trim(), (await readFile(`${root}/site/THIRD_PARTY_NOTICES.txt`, 'utf8')).trim());
      await page.goBack(); await page.waitForURL(url => url.pathname === new URL(base).pathname);
    });
    await step('Review layout and font families after drill-downs', 'No horizontal overflow or monospace text', async () => {
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
      const mono = await page.locator('body *').evaluateAll(els => els.filter(el => el.getClientRects().length && /monospace|courier|consolas|menlo/i.test(getComputedStyle(el).fontFamily)).map(el => el.tagName));
      assert.deepEqual(mono, []);
    });
    await page.screenshot({ path: `${out}/${profile}-full-page.png`, fullPage: true });
    await context.tracing.stop({ path: `${out}/${profile}-trace.zip` });
    await context.close();
  }
  profile = 'behavior'; index = 0;
  context = await browser.newContext({ viewport: { width: 1440, height: 1100 } });
  await context.tracing.start({ screenshots: true, snapshots: true, sources: true });
  page = await context.newPage(); page.setDefaultTimeout(7000);
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(base, { waitUntil: 'networkidle' });
  await step('Observe motion; pause; resume; change reduced-motion preference', 'Motion changes pixels, Pause freezes them, Resume moves, reduced motion pauses', async () => {
    await page.locator('#orbit').scrollIntoViewIfNeeded();
    const initial = await pixels(); await page.waitForTimeout(250); assert.notEqual(await pixels(), initial);
    await page.locator('#motion').click();
    const frozen = await pixels(); await page.waitForTimeout(250); assert.equal(await pixels(), frozen);
    await page.locator('#motion').click(); await page.waitForTimeout(250); assert.notEqual(await pixels(), frozen);
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await page.waitForFunction(() => document.querySelector('#motion').getAttribute('aria-pressed') === 'true');
    const reduced = await pixels(); await page.waitForTimeout(250); assert.equal(await pixels(), reduced);
  });
  await step('Scroll running graph offscreen and return', 'Offscreen pixels stop changing; returning resumes animation', async () => {
    await page.emulateMedia({ reducedMotion: 'no-preference' });
    await page.locator('#integrate').scrollIntoViewIfNeeded(); await page.waitForTimeout(150);
    const hidden = await pixels(); await page.waitForTimeout(250); assert.equal(await pixels(), hidden);
    await page.locator('#orbit').scrollIntoViewIfNeeded(); await page.waitForTimeout(150);
    const visible = await pixels(); await page.waitForTimeout(250); assert.notEqual(await pixels(), visible);
  });
  await step('Deny clipboard write then click Copy', 'Permission failure leaves a usable manual-copy message', async () => {
    await page.evaluate(() => { window.realWrite = navigator.clipboard.writeText.bind(navigator.clipboard); navigator.clipboard.writeText = () => Promise.reject(new Error('Denied for test')); });
    await page.locator('#copy').click();
    await page.waitForFunction(() => document.querySelector('#command-status').textContent.startsWith('Clipboard unavailable.'));
  });
  await step('Click Copy; edit invalid path while permission is pending; reject write', 'Stale clipboard failure cannot replace current validation message', async () => {
    await page.locator('#target').fill('/absolute/test repo');
    await page.evaluate(() => { navigator.clipboard.writeText = () => new Promise((resolve, reject) => { window.rejectCopy = reject; }); });
    await page.locator('#copy').click();
    await page.locator('#target').fill('/');
    const validation = await text('#command-status');
    await page.evaluate(() => window.rejectCopy(new Error('Delayed permission denial')));
    await page.waitForTimeout(100);
    assert.equal(await text('#command-status'), validation);
    await page.evaluate(() => { navigator.clipboard.writeText = window.realWrite; });
  });
  await step('Inventory every interactive element', 'No new link, button, selector or disclosure escapes the test inventory', async () => {
    assert.equal(await page.locator('a').count(), 18);
    assert.equal(await page.locator('button').count(), 7);
    assert.equal(await page.locator('select').count(), 2);
    assert.equal(await page.locator('input').count(), 1);
    assert.equal(await page.locator('summary').count(), 1);
    assert.equal(await page.locator('canvas').count(), 1);
  });
  const destinations = [
    ['.graphic-caption a:first-of-type', 'github.com', '/Contoso-State/red-team-agent-orchestration/blob/953b01d85fac9a6af45618e3f093f08cf5c647ba/doc/assets/mission-orbit.html'],
    ['.research-grid article:nth-child(1) a', 'docs.langchain.com', '/oss/python/langgraph/persistence'],
    ['.research-grid article:nth-child(2) a', 'arxiv.org', '/abs/2303.11366'],
    ['.research-grid article:nth-child(3) a', 'arxiv.org', '/abs/2303.17651'],
    ['.research-grid article:nth-child(4) a', 'arxiv.org', '/abs/2507.19457'],
    ['footer > a:last-child', 'github.com', '/AndrewGoodson/aef-core']
  ];
  for (const [selector, host, path] of destinations) await step(`Click outbound link ${path}; return`, 'Actual browser navigation uses the documented destination; record external availability separately', async () => {
    await page.goto(base, { waitUntil: 'domcontentloaded' });
    const expected = `https://${host}${path}`;
    assert.equal(await page.locator(selector).getAttribute('href'), expected);
    let observed, response;
    const listener = request => { if (request.isNavigationRequest() && request.frame() === page.mainFrame()) observed ||= request.url(); };
    page.on('request', listener);
    try {
      [response] = await Promise.all([page.waitForNavigation({ waitUntil: 'domcontentloaded', timeout: 20000 }), page.locator(selector).click({ noWaitAfter: true })]);
    } catch (error) { external.push({ url: expected, status: 'UNAVAILABLE', detail: error.message.split('\n')[0] }); }
    page.off('request', listener);
    assert.equal(observed, expected);
    if (response) external.push({ url: expected, status: response.status(), finalUrl: page.url(), title: await page.title(), accessRequired: path === '/AndrewGoodson/aef-core' });
    await page.goto(base, { waitUntil: 'domcontentloaded' });
  });
  await step('Compare all seven deployed assets to reviewed source', 'Every response succeeds and SHA-256 matches source bytes', async () => {
    for (const asset of ['index.html', 'styles.css', 'app.js', 'graph.js', 'logo.png', 'learning-protocol.txt', 'THIRD_PARTY_NOTICES.txt']) {
      const response = await context.request.get(new URL(asset, base).href);
      assert.equal(response.status(), 200, asset);
      const hash = data => createHash('sha256').update(data).digest('hex');
      assert.equal(hash(await response.body()), hash(await readFile(`${root}/site/${asset}`)), asset);
    }
  });
  await step('Inspect browser exceptions', 'Zero uncaught website JavaScript errors', async () => assert.deepEqual(errors, []));
  await context.tracing.stop({ path: `${out}/behavior-trace.zip` }); await context.close();
} finally {
  await browser.close();
  const report = { date: new Date().toISOString(), base, sourceCommit: execFileSync('git', ['rev-parse', 'HEAD'], { cwd: root, encoding: 'utf8' }).trim(), browser: 'Chromium', output: out, passed: results.filter(r => r.status === 'PASS').length, failed: results.filter(r => r.status === 'FAIL').length, results, external };
  await writeFile(`${out}/results.json`, JSON.stringify(report, null, 2));
  const cell = value => String(value).replaceAll('|', '\\|').replaceAll('\n', ' ');
  await writeFile(`${out}/results.md`, `# Website drill-down results\n\n${report.date}\n\nURL: ${base}\n\nSource: ${report.sourceCommit}\n\n${report.passed} passed; ${report.failed} failed. Chromium at 1440, 768, 390 and 320 CSS pixels.\n\n| Step | Action | Expected result | Status |\n| --- | --- | --- | --- |\n${results.map(r => `| ${r.id} | ${cell(r.action)} | ${cell(r.expected)} | ${r.status}${r.error ? ': ' + cell(r.error) : ''} |`).join('\n')}\n\n## External destinations\n\nExternal availability is recorded separately from correct link navigation. The source repository requires access.\n\n${external.map(r => `- ${r.url}: ${r.status}${r.title ? ' — ' + r.title : ''}${r.detail ? ' — ' + r.detail : ''}`).join('\n')}\n`);
  console.log(`\n${report.passed} passed; ${report.failed} failed. Results: ${out}/results.md`);
  if (report.failed) process.exitCode = 1;
}
