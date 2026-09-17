'use strict';
importScripts('/nut_kings_ops/static/workspace/vendor/zxing-reader-3.1.4.js', '/nut_kings_ops/static/workspace/scanner-core-v1.4.6.js');
const decode = NKScanner.createDecoder(ZXingWASM);
self.onmessage = async ({ data }) => {
  try { self.postMessage({ id: data.id, result: await decode(data.pixels, data.width, data.height) }); }
  catch (error) { self.postMessage({ id: data.id, error: error.message || 'Decoder failed' }); }
};
