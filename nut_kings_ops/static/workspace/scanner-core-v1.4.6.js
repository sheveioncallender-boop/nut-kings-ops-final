/* Nut Kings scan matching and camera decoding. No network or stock writes. */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.NKScanner = api;
})(globalThis, function () {
  'use strict';

  function normalize(value) {
    // Preserve leading zeros and letter case. Remove only transport suffixes
    // and known AIM identifiers, never GS1 separators or arbitrary characters.
    return String(value ?? '').replace(/[\r\n\t\0]+$/g, '').trim()
      .replace(/^\](?:C0|E0|A0|Q1|d1)/, '');
  }

  function validGtin(code) {
    if (!/^\d{12,13}$/.test(code)) return false;
    let sum = 0;
    for (let i = code.length - 2, weight = 3; i >= 0; i--, weight = 4 - weight) sum += Number(code[i]) * weight;
    return (10 - sum % 10) % 10 === Number(code.at(-1));
  }

  function expandUpce(code) {
    if (!/^[01]\d{7}$/.test(code)) return '';
    const [n, a, b, c, d, e, f, check] = code;
    const expanded = f <= '2' ? `${n}${a}${b}${f}0000${c}${d}${e}${check}`
      : f === '3' ? `${n}${a}${b}${c}00000${d}${e}${check}`
        : f === '4' ? `${n}${a}${b}${c}${d}00000${e}${check}`
          : `${n}${a}${b}${c}${d}${e}0000${f}${check}`;
    return validGtin(expanded) ? expanded : '';
  }

  function resolveProduct(products, value, type, format = '') {
    const code = normalize(value);
    if (!code || code.length > 512 || /[\u0000-\u001f\u007f]/.test(code)) {
      return { error: 'Barcode could not be read. Try again or enter the product manually.' };
    }
    let matches = products.filter(p => String(p.barcode || '').trim() === code);
    if (!matches.length && validGtin(code)) {
      const alternative = code.length === 12 ? `0${code}` : code.startsWith('0') ? code.slice(1) : '';
      if (alternative) matches = products.filter(p => String(p.barcode || '').trim() === alternative);
    }
    if (!matches.length && format.replace(/[_-]/g, '').toLowerCase() === 'upce') {
      // Some camera engines return UPC-E as its expanded EAN/UPC value.
      // Only perform this conversion for a positively identified UPC-E label.
      const expanded = expandUpce(code) || code.replace(/^0(?=\d{12}$)/, '');
      if (validGtin(expanded)) matches = products.filter(p => {
        const candidate = String(p.barcode || '').trim();
        return (expandUpce(candidate) || candidate.replace(/^0(?=\d{12}$)/, '')) === expanded;
      });
    }
    const cameraGtin = /^(ean13|upca|upce)$/.test(format.replace(/[_-]/g, '').toLowerCase());
    if (cameraGtin) {
      const key = cameraCodeKey(code, format);
      matches = products.filter(p => cameraCodeKey(String(p.barcode || '').trim(), format) === key);
    }
    if (!matches.length) matches = products.filter(p => String(p.default_code || '').trim() === code);
    const allowed = matches.filter(p => !type || p.type === type);
    if (allowed.length > 1) return { error: 'This code matches more than one product. Ask the administrator to give each product a unique code.' };
    if (allowed.length === 1) return { product: allowed[0], code };
    if (matches.length) return { error: 'This product belongs to a different warehouse. Choose the correct workspace.' };
    return { error: `Barcode ${code} was not found in the synchronized products. Check the label or synchronize.`, code };
  }

  function cameraCodeKey(value, format = '') {
    const code = normalize(value), compactFormat = format.replace(/[_-]/g, '').toLowerCase();
    if (compactFormat === 'upce') {
      const expanded = expandUpce(code);
      if (expanded) return `0${expanded}`;
    }
    if (/^(ean13|upca|upce)$/.test(compactFormat) && validGtin(code)) return code.padStart(13, '0');
    return code;
  }

  class ScanGate {
    constructor() { this.reset(); }
    reset() {
      this.lastCode = ''; this.lastSeen = 0; this.lastAccepted = -Infinity;
      this.candidate = ''; this.hits = 0; this.emptySince = null; this.emptyFrames = 0;
    }
    observe(value, now) {
      const code = normalize(value);
      if (!code) {
        this.candidate = ''; this.hits = 0;
        if (this.emptySince === null) this.emptySince = now;
        this.emptyFrames++;
        if (this.emptyFrames >= 4 && now - this.emptySince >= 1200) this.lastCode = '';
        return false;
      }
      // Every successful decode resets the absence interval, including reads
      // suppressed as duplicates. Intermittent misses cannot accumulate.
      this.emptySince = null; this.emptyFrames = 0; this.lastSeen = now;
      if (code !== this.candidate) { this.candidate = code; this.hits = 0; }
      this.hits++;
      if (code === this.lastCode || this.hits < 2 || now - this.lastAccepted < 350) return false;
      this.lastCode = code; this.lastAccepted = now;
      return true;
    }
  }

  function createDecoder(zxing, wasmBinary) {
    if (!zxing?.readBarcodes) throw new Error('Camera decoder is unavailable. Reconnect and reload the workspace.');
    zxing.prepareZXingModule({ overrides: wasmBinary ? { wasmBinary } : {
      // Always use our local, precached binary. Never contact a public CDN.
      locateFile: () => '/nut_kings_ops/static/workspace/vendor/zxing-reader-3.1.4.wasm',
    } });
    return async function decode(pixels, width, height) {
      const results = await zxing.readBarcodes({ data: pixels, width, height }, {
        formats: ['EAN13', 'EAN8', 'UPCA', 'UPCE', 'Code128', 'Code39', 'Code93', 'ITF', 'Codabar', 'QRCode', 'DataMatrix', 'PDF417', 'Aztec'],
        tryHarder: true, tryRotate: true, tryInvert: true, tryDownscale: true,
        maxNumberOfSymbols: 2, returnErrors: false, textMode: 'Plain',
      });
      const valid = results.filter(result => result.isValid);
      if (valid.length > 1) return { multiple: true };
      return valid.length ? { rawValue: valid[0].text, format: valid[0].format } : null;
    };
  }

  class FrameDecoder {
    constructor(workerUrl, zxing) {
      this.zxing = zxing; this.pending = null; this.nextId = 0; this.closed = false;
      try {
        this.worker = new Worker(workerUrl);
        this.worker.onmessage = event => {
          if (!this.pending || event.data.id !== this.pending.id) return;
          const pending = this.pending;
          this.pending = null; clearTimeout(pending.timer);
          if (event.data.error) {
            this.disableWorker();
            try { pending.resolve(this.decodeLocal(pending.image)); } catch (error) { pending.reject(error); }
          }
          else pending.resolve(event.data.result);
        };
        this.worker.onerror = event => { event.preventDefault(); this.failWorker(); };
      } catch (_) { this.worker = null; }
    }
    decodeLocal(image) {
      if (this.closed) return null;
      if (!this.local) this.local = createDecoder(this.zxing);
      return this.local(image.data, image.width, image.height);
    }
    disableWorker() { this.worker?.terminate(); this.worker = null; }
    failWorker() {
      this.disableWorker();
      if (this.pending) {
        const pending = this.pending; this.pending = null; clearTimeout(pending.timer);
        try { pending.resolve(this.decodeLocal(pending.image)); } catch (error) { pending.reject(error); }
      }
    }
    decode(image) {
      if (this.closed) return Promise.resolve(null);
      if (!this.worker) return Promise.resolve().then(() => this.decodeLocal(image));
      return new Promise((resolve, reject) => {
        const id = ++this.nextId;
        this.pending = { id, image, resolve, reject, timer: setTimeout(() => this.failWorker(), 5000) };
        // Keep the original pixels for a local retry if a worker is blocked.
        const pixels = image.data.slice();
        try { this.worker.postMessage({ id, pixels, width: image.width, height: image.height }, [pixels.buffer]); }
        catch (_) { this.failWorker(); }
      });
    }
    close() {
      this.closed = true; this.disableWorker();
      if (this.pending) { clearTimeout(this.pending.timer); this.pending.resolve(null); this.pending = null; }
    }
  }

  return { normalize, validGtin, expandUpce, cameraCodeKey, resolveProduct, ScanGate, createDecoder, FrameDecoder };
});
