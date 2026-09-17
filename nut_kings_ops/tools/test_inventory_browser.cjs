/* Exercise the real workspace startup, navigation and IndexedDB against a
 * local API fixture. No live Odoo instance or inventory is touched.
 * Dependency: playwright. Optional BROWSER_EXECUTABLE for a local Chromium.
 */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const { chromium } = require('playwright');
const ROOT = path.resolve(__dirname, '..');
const WORKSPACE = path.join(ROOT, 'static/workspace');
const PIXEL = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScLbtAAAAABJRU5ErkJggg==', 'base64');

function fixture(rawQuantity = 1, permissions = { raw: true, finished: true, raw_count: true, finished_count: true }) {
  const products = [
    { id: 1, name: 'Peanuts', barcode: '821314003279', type: 'raw_material', uom: 'Units', tracking: 'none' },
    { id: 2, name: 'Finished Pack', barcode: 'FG001', type: 'finished_good', uom: 'Units', tracking: 'none' },
  ];
  const row = (product, quantity) => ({ row_key: `quant-${product.id}`, quant_id: product.id, product_id: product.id,
    product: product.name, barcode: product.barcode, quantity, tracking: 'none', location_id: product.id + 10 });
  return {
    app_version: '1.4.7', user: { id: 1, name: 'Count Tester', roles: ['manager'] }, company: { name: 'Test Company' },
    permissions, capabilities: ['raw_receipt', 'finished_receipt'], products,
    inventory_rows: { raw: permissions.raw_count ? [row(products[0], rawQuantity)] : [], finished: [row(products[1], 4)] },
    balances: { raw: { 1: rawQuantity }, finished: { 2: 4 }, trucks: {} },
    on_hand: { raw: { 1: rawQuantity }, finished: { 2: 4 }, trucks: {} }, native_actions: {},
    trucks: [], customers: [], suppliers: [], staff: [], trips: [], reasons: [], service_areas: [], recent_operations: [], dashboard: {},
    reports: { low_stock: [], movement_summary: {}, truck_stock: [], trip_summary: [] },
  };
}

async function main() {
  let snapshot = fixture(), releaseBootstrap, holdBootstrap = false;
  const writes = [];
  const server = http.createServer(async (request, response) => {
    const url = new URL(request.url, 'http://localhost');
    if (request.method !== 'GET') { writes.push(url.pathname); response.writeHead(405); response.end(); return; }
    if (url.pathname === '/nutkings/api/ping') {
      response.setHeader('Content-Type', 'application/json'); response.end(JSON.stringify({ ok: true, user: { id: 1, name: 'Count Tester' } })); return;
    }
    if (url.pathname === '/nutkings/api/bootstrap') {
      if (holdBootstrap) await new Promise(resolve => { releaseBootstrap = resolve; });
      response.setHeader('Content-Type', 'application/json'); response.end(JSON.stringify(snapshot)); return;
    }
    if (url.pathname.endsWith('.png')) { response.setHeader('Content-Type', 'image/png'); response.end(PIXEL); return; }
    if (url.pathname === '/nutkings/manifest.webmanifest') { response.setHeader('Content-Type', 'application/manifest+json'); response.end('{"name":"Inventory test"}'); return; }
    let file;
    if (url.pathname === '/nutkings/') file = path.join(WORKSPACE, 'index.html');
    else if (url.pathname === '/nutkings/sw.js') file = path.join(WORKSPACE, 'sw.js');
    else if (url.pathname === '/nutkings/scanner-worker.js') file = path.join(WORKSPACE, 'scanner-worker-v1.4.6.js');
    else if (url.pathname.startsWith('/nut_kings_ops/static/')) file = path.join(ROOT, url.pathname.slice('/nut_kings_ops/'.length));
    if (!file || !file.startsWith(ROOT + path.sep) || !fs.existsSync(file)) { response.writeHead(404); response.end(); return; }
    response.setHeader('Content-Type', ({ '.js': 'application/javascript', '.html': 'text/html', '.css': 'text/css', '.wasm': 'application/wasm' })[path.extname(file)] || 'text/plain');
    response.end(fs.readFileSync(file));
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const url = `http://127.0.0.1:${server.address().port}/nutkings/`;
  const options = { headless: true };
  if (process.env.BROWSER_EXECUTABLE) {
    options.executablePath = process.env.BROWSER_EXECUTABLE;
    options.args = ['--no-sandbox', '--disable-dev-shm-usage'];
    try {
      const bundled = require('@sparticuz/chromium');
      options.args = (bundled.default || bundled).args.filter(arg => !['--disable-web-security', '--allow-running-insecure-content', '--disable-site-isolation-trials', '--single-process'].includes(arg));
    } catch (_) { /* Standard local browser. */ }
  }
  let browser;
  try {
    for (const viewport of [{ width: 1440, height: 1000 }, { width: 390, height: 844 }]) {
      snapshot = fixture();
      browser = await chromium.launch(options);
      const context = await browser.newContext({ viewport, isMobile: viewport.width < 600, hasTouch: viewport.width < 600 });
      const page = await context.newPage(), errors = [];
      page.on('pageerror', error => errors.push(error.message));
      await page.goto(url);
      await page.waitForFunction(() => state.snapshot.products.length === 2);
      if (viewport.width < 600) await page.locator('#mobile-menu').click();
      await page.locator('.nk-nav-button[data-route="inventory"]').click();
      await page.waitForFunction(() => state.countRows.length === 1);
      assert.match(await page.locator('#count-body').textContent(), /Peanuts/);
      assert.equal(await page.evaluate(() => state.countRows[0].quantity), 1);
      assert.equal(await page.evaluate(() => state.countRows[0].counted_quantity), '', 'Opening must not count or apply stock');
      await page.locator('#count-scan').fill('821314003279'); await page.locator('#count-add-scan').click();
      assert.equal(await page.evaluate(() => state.countRows[0].counted_quantity), 1);
      assert.equal(await page.locator('#count-feedback').evaluate(e => e.classList.contains('success')), true);
      await page.locator('#count-reference').fill('Shelf A count');
      snapshot = fixture(9);
      await page.locator('#top-sync').click();
      await page.waitForFunction(() => state.snapshot.inventory_rows.raw[0].quantity === 9);
      assert.deepEqual(await page.evaluate(() => [state.countRows[0].quantity, state.countRows[0].counted_quantity]), [1, 1], 'Sync preserves the count baseline');
      await page.evaluate(() => { navigate('dashboard'); navigate('inventory'); });
      assert.equal(await page.locator('#count-reference').inputValue(), 'Shelf A count');
      assert.equal(await page.evaluate(() => state.countRows[0].counted_quantity), 1, 'Navigation preserves counting');
      await page.locator('#count-save-device').click();
      await page.waitForFunction(() => state.countDraftUid !== '');
      const draftUid = await page.evaluate(() => state.countDraftUid);
      await page.locator('#count-warehouse').selectOption('finished');
      assert.match(await page.locator('#count-body').textContent(), /Finished Pack/);
      assert.equal(await page.evaluate(() => state.countRows[0].counted_quantity), '');
      await page.locator('#count-draft-select').selectOption(draftUid);
      assert.equal(await page.locator('#count-warehouse').inputValue(), 'raw');
      assert.deepEqual(await page.evaluate(() => [state.countRows[0].quantity, state.countRows[0].counted_quantity]), [1, 1]);
      // A zero count must also survive synchronization (zero is a real count).
      await page.locator('.count-input').fill('0'); await page.locator('.count-input').press('Tab');
      await page.locator('#count-save-device').click();
      await page.waitForFunction(() => state.countDrafts[0].rows[0].counted_quantity === 0);
      await page.evaluate(() => refreshSnapshot(false));
      assert.deepEqual(await page.evaluate(() => [state.countRows[0].quantity, state.countRows[0].counted_quantity]), [1, 0]);
      await page.evaluate(() => navigator.serviceWorker.ready);
      await page.waitForFunction(() => navigator.serviceWorker.controller !== null);
      // Ensure the navigation response has been cached under service-worker control.
      await page.reload(); await page.waitForFunction(() => state.snapshot.products.length === 2);
      await page.waitForFunction(async () => Boolean(await caches.match(location.href.split('#')[0])));
      await context.setOffline(true); await page.reload();
      await page.waitForFunction(() => document.documentElement.dataset.nkBoot === 'ready');
      assert.equal(await page.locator('#count-body tr').count(), 1, 'Offline direct entry loads cached rows');
      await page.locator('#count-draft-select').selectOption(draftUid);
      assert.deepEqual(await page.evaluate(() => [state.countRows[0].quantity, state.countRows[0].counted_quantity]), [1, 0], 'Saved count survives an offline reload');
      await page.locator('#count-submit').click();
      await page.waitForFunction(() => state.queue.length === 1);
      assert.deepEqual(await page.evaluate(() => ({ warehouse: state.queue[0].warehouse_type, expected: state.queue[0].lines[0].expected_quantity, counted: state.queue[0].lines[0].counted_quantity })), { warehouse: 'raw', expected: 1, counted: 0 });
      await page.evaluate(() => navigate('inventory'));
      assert.equal(await page.locator('#count-body tr').count(), 1, 'A new count loads after submission');
      assert.equal(await page.evaluate(() => state.countRows[0].counted_quantity), '');
      assert.deepEqual(errors, []);
      console.log(`PASS ${viewport.width}px: sidebar entry, scan, sync baseline, drafts, zero counts, warehouse switch, offline reload and queue payload`);
      await context.close();

      // Fresh direct link before the first snapshot is available.
      snapshot = fixture(); holdBootstrap = true; releaseBootstrap = null;
      const fresh = await browser.newContext(); const direct = await fresh.newPage();
      await direct.goto(url + '#inventory');
      await direct.waitForFunction(() => document.documentElement.dataset.nkBoot === 'ready');
      assert.equal(await direct.evaluate(() => state.countRows.length), 0);
      assert.equal(typeof releaseBootstrap, 'function');
      holdBootstrap = false; releaseBootstrap();
      await direct.waitForFunction(() => state.countRows.length === 1);
      assert.match(await direct.locator('#count-body').textContent(), /Peanuts/);
      snapshot = fixture(3);
      await direct.evaluate(() => refreshSnapshot(false));
      assert.equal(await direct.evaluate(() => state.countRows[0].quantity), 3, 'Untouched count refreshes');
      await fresh.close();

      snapshot = fixture(1, { finished: true, finished_count: true });
      const restricted = await browser.newContext(); const fg = await restricted.newPage();
      await fg.goto(url + '#inventory'); await fg.waitForFunction(() => state.countRows.length === 1);
      assert.equal(await fg.locator('#count-warehouse').inputValue(), 'finished');
      assert.equal(await fg.locator('#count-warehouse option[value="raw"]').isDisabled(), true);
      assert.match(await fg.locator('#count-body').textContent(), /Finished Pack/);
      await restricted.close();
      console.log(`PASS ${viewport.width}px: first online snapshot, untouched refresh and permitted warehouse selection`);
      await browser.close(); browser = null;
    }
    assert.deepEqual(writes, [], 'No inventory writes should reach any server in this check');
  } finally { if (releaseBootstrap) releaseBootstrap(); if (browser) await browser.close(); await new Promise(resolve => server.close(resolve)); }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
