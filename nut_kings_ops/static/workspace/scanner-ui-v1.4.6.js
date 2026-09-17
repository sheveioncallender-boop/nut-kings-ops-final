'use strict';

const cameraScanner = {
  stream: null, detector: null, decoder: null, context: 'scan', running: false,
  facingMode: 'environment', deviceId: '', devices: [], session: 0, timer: 0,
  gate: new NKScanner.ScanGate(), lastReadAt: 0, warned: false, torch: false,
};
const cameraAudio = { context: null };
const connectedScanner = { enabled: false };
const CAMERA_NATIVE_FORMATS = ['ean_13', 'ean_8', 'upc_a', 'upc_e', 'code_128', 'code_39', 'code_93', 'itf', 'codabar', 'qr_code', 'data_matrix', 'pdf417', 'aztec'];

function cameraAudioContext() {
  const Audio = window.AudioContext || window.webkitAudioContext;
  if (!Audio) return null;
  if (!cameraAudio.context || cameraAudio.context.state === 'closed') cameraAudio.context = new Audio();
  return cameraAudio.context;
}

function cameraUnlockAudio() {
  try {
    const context = cameraAudioContext();
    if (!context) return;
    if (context.state !== 'running') context.resume().catch(() => {});
    // Start a silent buffer within the tap/keypress, including mobile Safari.
    const source = context.createBufferSource();
    source.buffer = context.createBuffer(1, 1, context.sampleRate);
    source.connect(context.destination); source.start();
    source.onended = () => source.disconnect();
  } catch (_) { /* Sound is optional; stock handling must still work. */ }
}

function scannerTone(ok) {
  try { navigator.vibrate?.(ok ? 55 : [65, 50, 65]); } catch (_) { /* Not supported on every device. */ }
  try {
    const context = cameraAudioContext();
    if (!context) return;
    if (context.state !== 'running') context.resume().catch(() => {});
    const tones = ok ? [[1100, 0, 0.11]] : [[260, 0, 0.13], [190, 0.19, 0.15]];
    for (const [frequency, delay, length] of tones) {
      const oscillator = context.createOscillator(), gain = context.createGain();
      const at = context.currentTime + delay + 0.005;
      oscillator.type = 'sine'; oscillator.frequency.setValueAtTime(frequency, at);
      gain.gain.setValueAtTime(0.001, at); gain.gain.linearRampToValueAtTime(0.18, at + 0.012);
      gain.gain.exponentialRampToValueAtTime(0.001, at + length);
      oscillator.connect(gain); gain.connect(context.destination);
      oscillator.start(at); oscillator.stop(at + length + 0.01);
      oscillator.onended = () => { oscillator.disconnect(); gain.disconnect(); };
    }
  } catch (_) { /* Visual feedback remains available when sound is muted. */ }
}

function cameraSetStatus(title, detail = '', type = '') {
  const element = $('camera-status');
  element.className = `nk-camera-status ${type}`.trim();
  element.innerHTML = `<strong>${html(title)}</strong><span>${html(detail)}</span>`;
}

function scanFeedback(kind, ok, message, options = {}) {
  const element = $(`${kind}-feedback`);
  if (element) {
    element.hidden = false; element.className = `nk-scan-feedback ${ok ? 'success' : 'error'}`;
    element.textContent = `${ok ? '✓' : '!'} ${message}`;
  }
  if (options.source === 'camera') {
    cameraSetStatus(ok ? message : 'Item not added', ok
      ? 'Move the label out of view before scanning it again, or tap Scan Same Item Again.' : message, ok ? 'success' : 'error');
  }
  scannerTone(ok);
  if (options.source !== 'camera') {
    const input = autocompleteInput(kind);
    input.focus({ preventScroll: true });
    if (!ok) input.select();
  }
  return ok;
}

function acceptScannerCode(kind, rawValue, source = 'hardware', format = '') {
  const resolved = NKScanner.resolveProduct(state.snapshot?.products || [], rawValue, autocompleteProductType(kind), format);
  const input = autocompleteInput(kind);
  delete input.dataset.productId;
  closeProductAutocomplete(kind);
  // Never leave an old/unknown scan in the field to concatenate with the next.
  input.value = '';
  if (!resolved.product) return scanFeedback(kind, false, resolved.error, { source });
  return kind === 'count' ? addCountScan({ product: resolved.product, source }) : addScanLine({ product: resolved.product, source });
}

function activeScanKind() {
  if (!state.snapshot || document.hidden) return null;
  const modals = all('.nk-modal-backdrop.open');
  if (modals.length) return modals.length === 1 && modals[0].id === 'scan-modal' ? 'scan' : null;
  return state.route === 'inventory' ? 'count' : null;
}

function setConnectedScanner(enabled, kind) {
  connectedScanner.enabled = enabled;
  for (const name of ['scan', 'count']) {
    const input = autocompleteInput(name), button = $(`${name}-hardware`);
    input.setAttribute('inputmode', enabled ? 'none' : 'text');
    button.setAttribute('aria-pressed', String(enabled));
    button.textContent = enabled ? 'Connected Scanner: On' : 'Use Connected Scanner';
    closeProductAutocomplete(name);
  }
  cameraUnlockAudio();
  autocompleteInput(kind).focus({ preventScroll: true });
}

function scannerKeydown(event) {
  if (event.key === 'Escape' && $('camera-modal').classList.contains('open')) {
    event.preventDefault(); closeCameraScanner(); return;
  }
  const kind = activeScanKind();
  if (!kind || event.isComposing || event.ctrlKey || event.altKey || event.metaKey) return;
  const input = autocompleteInput(kind);
  const target = event.target;
  // Never capture a barcode into supplier, quantity, lot, password or notes.
  if (target !== input && target.closest?.('input,textarea,select,[contenteditable="true"]')) return;
  if (connectedScanner.enabled && target !== input && event.key.length === 1) {
    event.preventDefault();
    delete input.dataset.productId; input.value += event.key;
    input.focus({ preventScroll: true });
    return;
  }
  if (target !== input || !['Enter', 'Tab'].includes(event.key)) return;
  if (!input.value.trim()) {
    // CR+LF/duplicate terminators must not add another item or beep an error.
    if (event.key === 'Enter' || connectedScanner.enabled) { event.preventDefault(); event.stopImmediatePropagation(); }
    return;
  }
  const exact = NKScanner.resolveProduct(state.snapshot.products, input.value, autocompleteProductType(kind));
  if (connectedScanner.enabled || exact.product) {
    event.preventDefault(); event.stopImmediatePropagation();
    if (!event.repeat) { cameraUnlockAudio(); acceptScannerCode(kind, input.value); }
  }
}

function cameraStopTracks() {
  cameraScanner.session++;
  clearTimeout(cameraScanner.timer); cameraScanner.timer = 0;
  cameraScanner.running = false;
  cameraScanner.decoder?.close(); cameraScanner.decoder = null; cameraScanner.detector = null;
  cameraScanner.stream?.getTracks().forEach(track => track.stop()); cameraScanner.stream = null;
  cameraScanner.torch = false;
  const video = $('camera-video');
  if (video) { video.pause(); video.srcObject = null; }
}

function closeCameraScanner() {
  cameraStopTracks(); closeModal('camera-modal');
  const kind = activeScanKind();
  if (kind && connectedScanner.enabled) autocompleteInput(kind).focus({ preventScroll: true });
}

function cameraRetry() {
  cameraUnlockAudio();
  if (!cameraScanner.running) { openCameraScanner(cameraScanner.context); return; }
  cameraScanner.gate.reset(); cameraScanner.lastReadAt = performance.now(); cameraScanner.warned = false;
  cameraSetStatus('Ready to scan', 'Hold one label steady inside the guide.');
}

async function cameraBuildNativeDetector() {
  if (!window.BarcodeDetector) return null;
  try {
    const supported = await BarcodeDetector.getSupportedFormats();
    const formats = CAMERA_NATIVE_FORMATS.filter(format => supported.includes(format));
    return formats.length ? new BarcodeDetector({ formats }) : null;
  } catch (_) { return null; }
}

function cameraFrame() {
  const video = $('camera-video'), canvas = $('camera-canvas');
  if (video.readyState < 2 || !video.videoWidth) return null;
  const stage = video.getBoundingClientRect(), guide = $('camera-guide').getBoundingClientRect();
  if (!stage.width || !stage.height) return null;
  // Map the visible guide through object-fit: cover to the actual sensor frame.
  const scale = Math.max(stage.width / video.videoWidth, stage.height / video.videoHeight);
  const offsetX = (video.videoWidth * scale - stage.width) / 2;
  const offsetY = (video.videoHeight * scale - stage.height) / 2;
  const x = Math.max(0, (guide.left - stage.left + offsetX) / scale);
  const y = Math.max(0, (guide.top - stage.top + offsetY) / scale);
  const width = Math.min(video.videoWidth - x, guide.width / scale);
  const height = Math.min(video.videoHeight - y, guide.height / scale);
  canvas.width = Math.max(1, Math.round(Math.min(1280, width)));
  canvas.height = Math.max(1, Math.round(height * canvas.width / width));
  const context = canvas.getContext('2d', { willReadFrequently: true });
  context.drawImage(video, x, y, width, height, 0, 0, canvas.width, canvas.height);
  return canvas;
}

async function cameraDetectionLoop(session) {
  if (!cameraScanner.running || cameraScanner.session !== session) return;
  const started = performance.now();
  let detected = null, multiple = false;
  try {
    const canvas = cameraFrame();
    if (canvas) {
      if (cameraScanner.detector) {
        try {
          const results = await cameraScanner.detector.detect(canvas);
          multiple = results.length > 1;
          detected = results.length === 1 ? results[0] : null;
        } catch (_) { if (session === cameraScanner.session) cameraScanner.detector = null; }
      }
      if (session !== cameraScanner.session || !cameraScanner.running) return;
      // Also fall back when native detection returns nothing (partial format
      // support, blurry frame), not only when BarcodeDetector is absent.
      if (!detected && !multiple && cameraScanner.decoder) {
        detected = await cameraScanner.decoder.decode(canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height));
        multiple = Boolean(detected?.multiple);
      }
    }
  } catch (error) {
    if (session !== cameraScanner.session) return;
    cameraStopTracks();
    cameraSetStatus('Camera reader stopped', 'Tap Try Again. If it continues, reload while online or use your connected scanner.', 'error');
    scannerTone(false); return;
  }
  if (!cameraScanner.running || cameraScanner.session !== session) return;
  const now = performance.now();
  if (multiple) {
    if (!cameraScanner.warned) { scannerTone(false); cameraSetStatus('Show one barcode at a time', 'Move other labels outside the guide. No item was added.', 'error'); }
    cameraScanner.warned = true; cameraScanner.lastReadAt = now;
    cameraScanner.gate.observe('', now);
  } else if (detected?.rawValue) {
    cameraScanner.lastReadAt = now; cameraScanner.warned = false;
    if (cameraScanner.gate.observe(NKScanner.cameraCodeKey(detected.rawValue, detected.format), now)) acceptScannerCode(cameraScanner.context, detected.rawValue, 'camera', detected.format);
  } else {
    cameraScanner.gate.observe('', now);
    if (!cameraScanner.warned && now - cameraScanner.lastReadAt > 9000) {
      cameraScanner.warned = true;
      cameraSetStatus('No barcode read yet', 'Move closer, improve the light, and hold the label steady. Scanning is still active.', 'error');
      scannerTone(false);
    }
  }
  cameraScanner.timer = setTimeout(() => cameraDetectionLoop(session), Math.max(80, 220 - (performance.now() - started)));
}

async function cameraUpdateControls(session) {
  const track = cameraScanner.stream?.getVideoTracks()[0];
  if (!track) return;
  let capabilities = {};
  try { capabilities = track.getCapabilities?.() || {}; } catch (_) { /* optional */ }
  $('camera-torch').hidden = !capabilities.torch;
  $('camera-torch').textContent = 'Light On'; $('camera-torch').setAttribute('aria-pressed', 'false');
  const zoom = $('camera-zoom');
  $('camera-zoom-field').hidden = !capabilities.zoom || capabilities.zoom.max <= capabilities.zoom.min;
  if (capabilities.zoom) {
    zoom.min = capabilities.zoom.min; zoom.max = capabilities.zoom.max;
    zoom.step = capabilities.zoom.step || 0.1; zoom.value = track.getSettings?.().zoom || capabilities.zoom.min;
  }
  if (capabilities.focusMode?.includes('continuous')) {
    try { await track.applyConstraints({ advanced: [{ focusMode: 'continuous' }] }); } catch (_) { /* keep automatic device defaults */ }
  }
  if (session !== cameraScanner.session) return;
  try {
    const devices = (await navigator.mediaDevices.enumerateDevices()).filter(device => device.kind === 'videoinput');
    if (session !== cameraScanner.session) return;
    cameraScanner.devices = devices;
    cameraScanner.deviceId = track.getSettings?.().deviceId || cameraScanner.deviceId;
    $('camera-device').innerHTML = devices.map((device, i) => `<option value="${html(device.deviceId)}" ${device.deviceId === cameraScanner.deviceId ? 'selected' : ''}>${html(device.label || `Camera ${i + 1}`)}</option>`).join('');
    $('camera-device-field').hidden = devices.length < 2;
    $('camera-switch').hidden = devices.length === 1;
  } catch (_) { if (session === cameraScanner.session) $('camera-device-field').hidden = true; }
}

async function openCameraScanner(context = 'scan') {
  cameraUnlockAudio(); cameraStopTracks();
  cameraScanner.context = context === 'count' ? 'count' : 'scan';
  cameraScanner.gate.reset(); cameraScanner.warned = false;
  const session = cameraScanner.session;
  $('camera-torch').hidden = true; $('camera-zoom-field').hidden = true; $('camera-device-field').hidden = true;
  $('camera-mode').textContent = 'Preparing camera…';
  cameraSetStatus('Starting camera…', 'Allow camera access when your device asks.');
  openModal('camera-modal');
  $('camera-close').focus({ preventScroll: true });
  if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
    cameraSetStatus('Camera unavailable', !window.isSecureContext ? 'Open this workspace using HTTPS to enable the camera.' : 'Use an up-to-date browser with camera access, or use a connected scanner.', 'error');
    scannerTone(false); return;
  }
  try {
    let videoConstraints = {
      width: { ideal: 1920 }, height: { ideal: 1080 },
      ...(cameraScanner.deviceId ? { deviceId: { exact: cameraScanner.deviceId } } : { facingMode: { ideal: cameraScanner.facingMode } }),
    };
    let stream;
    try { stream = await navigator.mediaDevices.getUserMedia({ audio: false, video: videoConstraints }); }
    catch (error) {
      if (session !== cameraScanner.session) return;
      if (!['OverconstrainedError', 'NotFoundError'].includes(error.name)) throw error;
      cameraScanner.deviceId = '';
      stream = await navigator.mediaDevices.getUserMedia({ audio: false, video: { facingMode: { ideal: cameraScanner.facingMode } } });
    }
    // A permission prompt may resolve after Close or another camera request.
    if (session !== cameraScanner.session) { stream.getTracks().forEach(track => track.stop()); return; }
    cameraScanner.stream = stream;
    const video = $('camera-video'); video.srcObject = stream;
    await video.play();
    if (session !== cameraScanner.session) return;
    const detector = await cameraBuildNativeDetector();
    if (session !== cameraScanner.session) return;
    cameraScanner.detector = detector;
    cameraScanner.decoder = new NKScanner.FrameDecoder('/nutkings/scanner-worker.js?v=1.4.6', window.ZXingWASM);
    cameraScanner.running = true; cameraScanner.lastReadAt = performance.now();
    const track = stream.getVideoTracks()[0];
    track.addEventListener('ended', () => {
      if (session !== cameraScanner.session) return;
      cameraStopTracks(); cameraSetStatus('Camera disconnected', 'Reconnect the camera, then tap Try Again.', 'error'); scannerTone(false);
    }, { once: true });
    $('camera-mode').textContent = track.label || 'Camera';
    cameraSetStatus('Ready to scan', 'Keep one barcode steady inside the guide. Green means it was added.');
    cameraUpdateControls(session).catch(() => {});
    cameraDetectionLoop(session);
  } catch (error) {
    if (session !== cameraScanner.session) return;
    cameraStopTracks();
    const messages = {
      NotAllowedError: 'Allow Camera permission for this site in your browser settings, then tap Try Again.',
      SecurityError: 'Allow camera access and open the workspace directly in your browser.',
      NotFoundError: 'No camera was found. Connect a camera or use a barcode scanner.',
      NotReadableError: 'The camera may be in use by another app. Close it and tap Try Again.',
    };
    cameraSetStatus('Camera could not start', messages[error.name] || 'Check your camera connection and browser permissions, then tap Try Again.', 'error');
    $('camera-mode').textContent = 'Camera unavailable'; scannerTone(false);
  }
}

function switchCameraScanner() {
  const devices = cameraScanner.devices;
  if (devices.length > 1) {
    const index = devices.findIndex(device => device.deviceId === cameraScanner.deviceId);
    cameraScanner.deviceId = devices[(index + 1) % devices.length].deviceId;
  } else {
    cameraScanner.deviceId = ''; cameraScanner.facingMode = cameraScanner.facingMode === 'environment' ? 'user' : 'environment';
  }
  return openCameraScanner(cameraScanner.context);
}

async function cameraSetConstraint(constraint) {
  const session = cameraScanner.session;
  try {
    await cameraScanner.stream?.getVideoTracks()[0]?.applyConstraints({ advanced: [constraint] });
    return cameraScanner.running && session === cameraScanner.session;
  } catch (_) {
    if (session === cameraScanner.session) cameraSetStatus('Control unavailable', 'This camera could not apply that setting. You can keep scanning.', '');
    return false;
  }
}

function bindScannerControls() {
  for (const kind of ['scan', 'count']) {
    $(`${kind}-hardware`).addEventListener('click', () => setConnectedScanner(!connectedScanner.enabled, kind));
    $(`${kind}-test-sound`).addEventListener('click', () => { cameraUnlockAudio(); scannerTone(true); });
  }
  $('camera-retry').addEventListener('click', cameraRetry);
  $('camera-repeat').addEventListener('click', cameraRetry);
  $('camera-test-sound').addEventListener('click', () => { cameraUnlockAudio(); scannerTone(true); });
  $('camera-device').addEventListener('change', () => { cameraScanner.deviceId = $('camera-device').value; openCameraScanner(cameraScanner.context); });
  $('camera-torch').addEventListener('click', async () => {
    const enabled = !cameraScanner.torch;
    if (await cameraSetConstraint({ torch: enabled })) {
      cameraScanner.torch = enabled; $('camera-torch').textContent = enabled ? 'Light Off' : 'Light On';
      $('camera-torch').setAttribute('aria-pressed', String(enabled));
    }
  });
  $('camera-zoom').addEventListener('change', () => cameraSetConstraint({ zoom: Number($('camera-zoom').value) }));
  document.addEventListener('keydown', scannerKeydown, true);
  document.addEventListener('pointerdown', () => { if (activeScanKind()) cameraUnlockAudio(); }, { passive: true });
}
