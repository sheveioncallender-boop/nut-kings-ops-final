/* Run with Node; bwip-js and pngjs are test-only label generators/readers. */
'use strict';
const assert = require('node:assert/strict');
const bwip = require('bwip-js');
const { PNG } = require('pngjs');
const core = require('../static/workspace/scanner-core-v1.4.6.js');
const fs = require('node:fs');
const vm = require('node:vm');
const vendor = require('node:path').join(__dirname, '../static/workspace/vendor/');
const zxing = vm.runInThisContext(fs.readFileSync(vendor + 'zxing-reader-3.1.4.js', 'utf8') + '\nZXingWASM;');

const LABELS = [
  ['ean13', '4006381333931'], ['ean8', '96385074'], ['upca', '036000291452'],
  ['upce', '04210007', '0042000001007'], ['code128', '000123ABC'], ['code39', 'NK-LOT-01'],
  ['code93', 'NK93123'], ['interleaved2of5', '12345670'],
  ['rationalizedCodabar', 'A12345B'], ['qrcode', 'NK-QR-0001'],
  ['datamatrix', '000DMABC'], ['pdf417', 'NK-PDF417-0001'], ['azteccode', 'NK-AZTEC01'],
];

async function labelPixels(bcid, text) {
  return PNG.sync.read(await bwip.toBuffer({ bcid, text, includecheck: bcid === 'code93', scale: 3, height: 16, padding: 15, backgroundcolor: 'FFFFFF' }));
}

async function run() {
  const products = [
    { id: 1, barcode: '036000291452', default_code: 'PN001', type: 'raw_material' },
    { id: 2, barcode: 'ABC123', default_code: 'FG001', type: 'finished_good' },
    { id: 3, barcode: '000001', default_code: 'LOWER', type: 'raw_material' },
  ];
  assert.equal(core.resolveProduct(products, '0036000291452', 'raw_material').product.id, 1);
  assert.equal(core.resolveProduct(products, ']E0036000291452\r\n', 'raw_material').product.id, 1);
  assert.equal(core.resolveProduct(products, ']C0PN001\t', 'raw_material').product.id, 1);
  assert.equal(core.resolveProduct(products, '000001', 'raw_material').product.id, 3);
  for (const value of ['1', 'abc123', 'PN00', 'UNKNOWN', '01\x1d10LOT']) assert.ok(core.resolveProduct(products, value, 'raw_material').error);
  assert.match(core.resolveProduct(products, 'ABC123', 'raw_material').error, /different warehouse/);
  assert.match(core.resolveProduct([...products, { ...products[0], id: 4 }], '036000291452', 'raw_material').error, /more than one/);
  const exactPreferred = [...products, { ...products[0], id: 5, barcode: '0036000291452' }];
  assert.equal(core.resolveProduct(exactPreferred, '0036000291452', 'raw_material').product.id, 5);
  assert.match(core.resolveProduct(exactPreferred, '0036000291452', 'raw_material', 'ean_13').error, /more than one/);
  assert.equal(core.cameraCodeKey('036000291452', 'upc_a'), core.cameraCodeKey('0036000291452', 'EAN13'));
  const upce = [{ id: 7, barcode: '04210007', type: 'raw_material' }];
  assert.equal(core.resolveProduct(upce, '0042000001007', 'raw_material', 'UPCE').product.id, 7);
  console.log('PASS exact matching, leading zeros, UPC/EAN, AIM suffixes, unknown/wrong/ambiguous rejection');

  const gate = new core.ScanGate();
  assert.equal(gate.observe('A', 0), false);
  assert.equal(gate.observe('A', 220), true);
  for (let t = 440; t < 5000; t += 220) {
    assert.equal(gate.observe(t % 440 ? '' : 'A', t), false);
  }
  // Sporadic misses never release a continuously visible label.
  assert.equal(gate.observe('A', 5100), false);
  for (const t of [5500, 5900, 6300, 6800]) gate.observe('', t);
  assert.equal(gate.observe('A', 7100), false);
  assert.equal(gate.observe('A', 7320), true);
  assert.equal(gate.observe('B', 7600), false);
  assert.equal(gate.observe('B', 7850), true);
  gate.reset();
  assert.equal(gate.observe('B', 8100), false);
  assert.equal(gate.observe('B', 8320), true);
  console.log('PASS duplicate suppression, consecutive confirmation, leave/re-enter, intentional rearm');

  const decode = core.createDecoder(zxing, fs.readFileSync(vendor + 'zxing-reader-3.1.4.wasm'));
  for (const [bcid, text, expected = text] of LABELS) {
    const pixels = await labelPixels(bcid, text);
    const decoded = await decode(pixels.data, pixels.width, pixels.height);
    // ZXing can normalize UPC-A into EAN-13, both identify the same GTIN.
    assert.ok(decoded, `${bcid} was not decoded`);
    assert.ok(decoded.rawValue === expected || bcid === 'upca' && decoded.rawValue === `0${expected}`, `${bcid}: ${decoded.rawValue}`);
    const rotated = new Uint8ClampedArray(pixels.data.length);
    for (let y = 0; y < pixels.height; y++) for (let x = 0; x < pixels.width; x++) {
      const from = (y * pixels.width + x) * 4, to = (x * pixels.height + pixels.height - y - 1) * 4;
      rotated.set(pixels.data.subarray(from, from + 4), to);
    }
    assert.ok(await decode(rotated, pixels.height, pixels.width), `${bcid} rotated label was not decoded`);
    console.log(`PASS ${bcid} label, horizontal and rotated`);
  }
  assert.equal(await decode(new Uint8ClampedArray(320 * 160 * 4).fill(255), 320, 160), null);
  console.log('PASS blank frame returns no barcode');
}

if (require.main === module) run().catch(error => { console.error(error); process.exitCode = 1; });
module.exports = { LABELS, labelPixels };
