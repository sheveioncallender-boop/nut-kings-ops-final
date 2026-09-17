/* Browser checks against the real workspace DOM/scripts with local stock
 * fixtures and a canvas camera. No Odoo database or physical stock is changed.
 * Dependencies: playwright, bwip-js, pngjs. BROWSER_EXECUTABLE is optional.
 */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const { chromium } = require('playwright');
const { PNG } = require('pngjs');
const { labelPixels } = require('./test_scanner_core.cjs');
const ROOT = path.resolve(__dirname, '..');
const WORKSPACE = path.join(ROOT, 'static/workspace');
const PIXEL = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScLbtAAAAABJRU5ErkJggg==', 'base64');

async function main() {
  const label = PNG.sync.write(await labelPixels('ean13', '4006381333931'));
  const requests = [];
  const server = http.createServer((request, response) => {
    const url = new URL(request.url, 'http://localhost'); requests.push(url.pathname);
    let file;
    if (url.pathname === '/label.png') { response.setHeader('Content-Type', 'image/png'); response.end(label); return; }
    if (url.pathname.endsWith('.png')) { response.setHeader('Content-Type', 'image/png'); response.end(PIXEL); return; }
    if (url.pathname === '/nutkings/manifest.webmanifest') { response.setHeader('Content-Type', 'application/manifest+json'); response.end('{"name":"Scanner test"}'); return; }
    if (url.pathname === '/nutkings/sw.js') file = path.join(WORKSPACE, 'sw.js');
    else if (url.pathname === '/nutkings/scanner-worker.js') file = path.join(WORKSPACE, 'scanner-worker-v1.4.6.js');
    else if (url.pathname.startsWith('/nut_kings_ops/static/')) file = path.join(ROOT, url.pathname.slice('/nut_kings_ops/'.length));
    else if (url.pathname === '/nutkings/') file = path.join(WORKSPACE, 'index.html');
    if (!file || !file.startsWith(ROOT + path.sep) || !fs.existsSync(file)) { response.writeHead(404); response.end(); return; }
    let content = fs.readFileSync(file);
    if (path.basename(file) === 'app-v1.4.1.js') {
      // Replace only the live-server bootstrap. All scanner/workspace logic is
      // unchanged and bindEvents is called below using an explicit fixture.
      content = content.toString().replace(/if \(document.readyState === 'loading'\) document.addEventListener\('DOMContentLoaded', startWorkspace, \{ once: true \}\);\s*else startWorkspace\(\);/, '');
    }
    response.setHeader('Content-Type', ({ '.js': 'application/javascript', '.css': 'text/css', '.html': 'text/html', '.wasm': 'application/wasm' })[path.extname(file)] || 'text/plain');
    response.end(content);
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
      browser = await chromium.launch(options);
      const context = await browser.newContext({ viewport, isMobile: viewport.width < 600, hasTouch: viewport.width < 600 });
      const externalRequests = [];
      context.on('request', request => { if (!request.url().startsWith(new URL(url).origin)) externalRequests.push(request.url()); });
      const page = await context.newPage(), errors = [];
      page.on('pageerror', error => errors.push(error.message));
      await page.goto(url);
      await page.evaluate(() => {
        document.documentElement.dataset.nkBoot = 'ready';
        state.snapshot = emptySnapshot();
        state.snapshot.capabilities = ['raw_receipt', 'raw_issue', 'finished_receipt'];
        state.snapshot.permissions = { raw_count: true, finished_count: true };
        state.snapshot.products = [
          { id: 1, name: 'Peanuts', barcode: '4006381333931', default_code: 'PN001', type: 'raw_material', uom: 'Units' },
          { id: 2, name: 'UPC Peanuts', barcode: '036000291452', default_code: 'PN002', type: 'raw_material', uom: 'Units' },
          { id: 3, name: 'Finished Pack', barcode: 'FG999', type: 'finished_good', uom: 'Units' },
        ];
        state.snapshot.inventory_rows.raw = [{ row_key: '1', product_id: 1, product: 'Peanuts', quantity: 0, barcode: '4006381333931', tracking: 'none' }];
        window.__tones = [];
        const realTone = scannerTone;
        scannerTone = ok => { window.__tones.push(ok); realTone(ok); };
        bindEvents(); openScan('raw_receipt');
      });
      await page.waitForFunction(() => document.activeElement.id === 'scan-product');
      await page.locator('#scan-hardware').click();
      await page.keyboard.type('4006381333931', { delay: 2 }); await page.keyboard.press('Enter');
      await page.keyboard.press('Enter');
      assert.equal(await page.evaluate(() => state.scan.lines[0].quantity), 1, 'CR+LF must add exactly once');
      await page.keyboard.type('4006381333931', { delay: 2 }); await page.keyboard.press('Tab');
      assert.equal(await page.evaluate(() => state.scan.lines[0].quantity), 2, 'Tab suffix repeats intentionally');
      await page.locator('#scan-qty').fill('3'); await page.locator('#scan-product').focus();
      await page.keyboard.type('PN001'); await page.keyboard.press('Enter');
      assert.equal(await page.evaluate(() => state.scan.lines[0].quantity), 5);
      for (const value of ['UNKNOWN', 'FG999', 'PN00']) {
        await page.keyboard.type(value); await page.keyboard.press('Enter');
        assert.equal(await page.evaluate(() => state.scan.lines[0].quantity), 5);
        assert.equal(await page.evaluate(() => __tones.at(-1)), false);
      }
      await page.locator('#scan-notes').fill('Keep these notes'); await page.keyboard.type('4006381333931');
      assert.equal(await page.evaluate(() => state.scan.lines[0].quantity), 5, 'Notes must not trigger scanning');
      assert.match(await page.locator('#scan-notes').inputValue(), /^Keep these notes/);
      await page.evaluate(() => { $('scan-qty').value = '0'; acceptScannerCode('scan', '4006381333931', 'camera'); });
      assert.equal(await page.evaluate(() => state.scan.lines[0].quantity), 5);
      assert.equal(await page.evaluate(() => __tones.at(-1)), false, 'Invalid quantity must never play success');
      await page.evaluate(() => { closeModal('scan-modal'); openCount('raw'); });
      await page.keyboard.type('4006381333931'); await page.keyboard.press('Enter');
      assert.equal(await page.evaluate(() => state.countRows[0].counted_quantity), 1);
      await page.evaluate(() => { $('count-scan-qty').value = '-1'; acceptScannerCode('count', '4006381333931', 'camera'); });
      assert.equal(await page.evaluate(() => state.countRows[0].counted_quantity), 1);
      await page.evaluate(() => { state.countRows.push({ ...state.countRows[0], row_key: '2', lot_name: 'Second lot' }); $('count-scan-qty').value = '1'; acceptScannerCode('count', '4006381333931', 'camera'); });
      assert.equal(await page.evaluate(() => state.countRows[0].counted_quantity), 1, 'Ambiguous lot must not be counted');
      assert.equal(await page.evaluate(() => __tones.at(-1)), false);
      console.log(`PASS ${viewport.width}px: keyboard Enter/Tab/repeats, strict matching, editable-field protection, quantities and lot ambiguity`);

      await page.evaluate(() => {
        openScan('raw_receipt');
        Object.defineProperty(navigator.mediaDevices, 'getUserMedia', { configurable: true, writable: true, value: () => new Promise(resolve => { window.__grantCamera = resolve; }) });
      });
      await page.locator('#scan-camera').click(); await page.locator('#camera-close').click();
      await page.evaluate(() => __grantCamera({ getTracks: () => [{ stop: () => { window.__lateStreamStopped = true; } }] }));
      await page.waitForFunction(() => window.__lateStreamStopped);
      assert.equal(await page.evaluate(() => cameraScanner.running), false);
      assert.equal(await page.locator('#camera-modal').evaluate(e => e.classList.contains('open')), false);
      await page.evaluate(() => {
        navigator.mediaDevices.getUserMedia = () => Promise.reject(new DOMException('Permission denied', 'NotAllowedError'));
      });
      await page.locator('#scan-camera').click();
      await page.waitForFunction(() => $('camera-status').textContent.includes('Allow Camera permission'));
      await page.locator('#camera-close').click();
      console.log(`PASS ${viewport.width}px: permission denial and late permission cleanup`);

      await page.evaluate(async partialNative => {
        Object.defineProperty(window, 'BarcodeDetector', { configurable: true, value: partialNative ? class {
          static async getSupportedFormats() { return ['qr_code']; }
          async detect() { window.__nativeCalls = (window.__nativeCalls || 0) + 1; return []; }
        } : undefined });
        const image = await createImageBitmap(await (await fetch('/label.png')).blob());
        const canvas = document.createElement('canvas'); canvas.width = 1280; canvas.height = 720;
        const c = canvas.getContext('2d');
        const draw = () => { c.fillStyle = 'white'; c.fillRect(0, 0, 1280, 720); if (!window.__blankFrame) c.drawImage(image, (1280 - image.width) / 2, (720 - image.height) / 2); };
        draw(); window.__drawTimer = setInterval(draw, 100);
        navigator.mediaDevices.getUserMedia = async () => {
          const stream = canvas.captureStream(10); window.__cameraTrack = stream.getVideoTracks()[0]; return stream;
        };
        Object.defineProperty(navigator.mediaDevices, 'enumerateDevices', { configurable: true, value: async () => [] });
        state.scan.lines = []; $('scan-qty').value = '0';
      }, viewport.width > 600);
      await page.locator('#scan-camera').click();
      await page.waitForFunction(() => $('camera-status').textContent.includes('Quantity must be'), { timeout: 15000 });
      assert.equal(await page.evaluate(() => state.scan.lines.length), 0);
      assert.equal(await page.evaluate(() => __tones.at(-1)), false);
      await page.evaluate(() => { $('scan-qty').value = '1'; });
      await page.locator('#camera-repeat').click();
      await page.waitForFunction(() => state.scan.lines[0]?.quantity === 1, { timeout: 15000 });
      await page.waitForTimeout(1800);
      assert.equal(await page.evaluate(() => state.scan.lines[0].quantity), 1, 'Stationary camera barcode must not repeat');
      assert.equal(await page.evaluate(() => __tones.at(-1)), true);
      await page.locator('#camera-repeat').click();
      await page.waitForFunction(() => state.scan.lines[0]?.quantity === 2);
      assert.equal(await page.locator('#camera-torch').isVisible(), false, 'Unsupported controls stay hidden');
      assert.ok(await page.locator('.nk-camera-modal').evaluate(e => e.scrollWidth <= e.clientWidth + 1), 'No horizontal camera overflow');
      assert.ok((await page.locator('.nk-camera-modal').boundingBox()).width <= viewport.width + 1, 'Camera must fit the device viewport');
      if (process.env.SCAN_SCREENSHOT_DIR) {
        fs.mkdirSync(process.env.SCAN_SCREENSHOT_DIR, { recursive: true });
        await page.screenshot({ path: path.join(process.env.SCAN_SCREENSHOT_DIR, `camera-${viewport.width}.png`), fullPage: true });
      }
      if (viewport.width > 600) {
        assert.ok(await page.evaluate(() => window.__nativeCalls > 0), 'Fallback also runs with partial native support');
        const toneCount = await page.evaluate(() => __tones.length);
        await page.evaluate(() => { window.__blankFrame = true; });
        await page.waitForTimeout(500);
        await page.evaluate(() => { cameraScanner.lastReadAt = performance.now() - 9500; });
        await page.waitForFunction(() => $('camera-status').textContent.includes('No barcode read yet'));
        await page.waitForTimeout(800);
        assert.equal(await page.evaluate(() => __tones.length), toneCount + 1, 'Unreadable warning must not beep on every frame');
        assert.equal(await page.evaluate(() => __tones.at(-1)), false);
      }
      await page.locator('#camera-stop').click();
      assert.equal(await page.evaluate(() => __cameraTrack.readyState), 'ended');
      console.log(`PASS ${viewport.width}px: actual camera frames decoded in worker, accurate tones, repeat protection, explicit repeat, stream shutdown and layout`);

      // Cache the real shell, take the browser offline, reload, and start a new
      // decoding worker. This catches missing importScripts/WASM cache entries.
      await page.evaluate(async () => {
        await navigator.serviceWorker.register('/nutkings/sw.js', { scope: '/nutkings/' });
        await navigator.serviceWorker.ready;
      });
      await page.waitForFunction(() => Boolean(navigator.serviceWorker.controller));
      await context.setOffline(true); await page.reload();
      const result = await page.evaluate(async pixels => {
        const decoder = new NKScanner.FrameDecoder('/nutkings/scanner-worker.js?v=1.4.6', ZXingWASM);
        const result = await decoder.decode({ data: Uint8ClampedArray.from(pixels.data), width: pixels.width, height: pixels.height });
        const usedWorker = Boolean(decoder.worker); decoder.close(); return { result, usedWorker };
      }, (() => { const p = PNG.sync.read(label); return { width: p.width, height: p.height, data: [...p.data] }; })());
      assert.equal(result.result.rawValue, '4006381333931');
      assert.equal(result.usedWorker, true, 'Worker and WASM must also load offline');
      console.log(`PASS ${viewport.width}px: offline shell reload and fresh worker/WASM decoding`);
      assert.deepEqual(errors, [], 'No uncaught browser errors');
      assert.deepEqual(externalRequests, [], 'Camera decoding must not contact external CDNs/services');
      await context.close();
      await browser.close();
    }
    assert.ok(requests.some(p => p.endsWith('.wasm')));
  } finally {
    await browser?.close(); await new Promise(resolve => server.close(resolve));
  }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
