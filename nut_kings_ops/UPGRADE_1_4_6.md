# Nut Kings Ops 19.0.1.4.6 — scanner reliability

## What changed

- USB/Bluetooth scanners in keyboard (HID) mode work with Enter or Tab suffixes.
  Connected Scanner mode keeps the product field ready and suppresses the
  on-screen keyboard where supported. It does not capture typing in notes,
  quantities, supplier searches or other forms.
- Both scan paths use exact product codes and preserve leading zeros. Camera
  UPC/EAN equivalents are normalized, including expanded UPC-E results.
  Unknown codes, wrong warehouses and ambiguous codes cannot select a similar
  product from autocomplete.
- One high tone and green text mean the item was actually added to the current
  operation/count. Two low tones and an error message mean it was rejected.
  Invalid quantities and ambiguous physical-count lot rows never report success.
  Scan success builds the operation; Odoo validation still completes the transfer.
- The camera uses native detection plus a bundled ZXing-C++ WebAssembly decoder.
  It covers EAN/UPC, Code 128/39/93, ITF, Codabar, QR, Data Matrix, PDF417 and Aztec.
  Detection runs in a worker when available, with a local fallback. Images stay
  on the device; decoding does not contact a CDN or external service.
- Two consistent reads confirm a camera scan. Holding a label in view does not
  continuously add it. Move it out of view for at least 1.2 seconds, or use
  **Scan Same Item Again**, to intentionally count another identical item.
- Camera selection, continuous focus, torch and zoom are used where the device
  supports them. Only the visible guide is decoded. Permission errors, camera
  disconnection and a prolonged unreadable image have clear recovery messages.
- Closing, switching, hiding or leaving the camera stops its tracks and decoder.
  Late permission responses cannot restart a camera that was closed.
- The PWA caches all decoder assets, including WASM. The dedicated worker is
  served inside `/nutkings/` so a fresh camera worker also works offline.

Existing warehouse workflows, access restrictions, stock validation and queued
transaction handling are preserved. Purchasing and van development are unchanged.

## Update and use

1. Pull the latest `main` in Cloudpepper, restart/redeploy Odoo, and upgrade
   **Nut Kings Ops** to **19.0.1.4.6**.
2. Open/reload each device's workspace while online. Synchronize the products
   and let the updated PWA finish caching before testing offline.
3. Pair/connect the scanner in the device's OS. Configure **keyboard/HID mode**
   and an **Enter (CR)** or **Tab** suffix. In Rapid Scan or Physical Inventory,
   select **Use Connected Scanner**, then scan. Normal typing/search still works
   when this mode is off. Readers that send neither suffix can use the Add button.
4. For the camera, open the HTTPS workspace, tap **Scan with Camera**, grant
   permission, and hold one label inside the guide. Use **Test Sound** to check
   volume. The same controls work in the installed PWA.

Products and their unique barcodes must already exist in the synchronized Odoo
catalogue. Composite GS1 fields are not automatically converted into quantities,
lots or expiry dates by this update. Those fields retain their existing workflow.
When a hardware reader cannot decode a label and sends no input, only the reader
can signal that failure; the app can report only input it receives. Browser/OS
permissions, mute settings, camera quality and supported device controls still
apply. Proprietary serial/SDK-only readers need a separate integration.

## Checks performed

- Real generated labels decoded in 13 formats, including 90-degree rotation;
  blank frames, exact matching, UPC/EAN aliases, leading zeros and duplicate gates.
- Chromium desktop (1440px) and phone-size/touch (390px) interaction checks:
  Enter/Tab, repeated scans, duplicate terminators, unknown/wrong products,
  editable-field protection, invalid quantities and multiple lot rows.
- Real video frames from a simulated canvas camera decoded by the bundled worker,
  including native-detector fallback, successful/rejected feedback, held labels,
  deliberate repeats, permission denial, late permission grants and stream cleanup.
- Offline reload followed by a newly created worker loading its decoder/WASM
  from the PWA cache. No external decoding requests; responsive camera layout.
- JavaScript and Python syntax checks.

These are automated browser/decoder checks, not physical-device certification.
An actual USB/Bluetooth scanner, iPhone/iPad Safari and the deployed Odoo upgrade
still need the user's device check. No live inventory was modified by the tests.

Tests: `tools/test_scanner_core.cjs` and `tools/test_scanner_browser.cjs`.
Use Node with test-only dependencies `bwip-js@4.7.0`, `pngjs@7.0.0` and Playwright;
install its Chromium browser, then run both files. `BROWSER_EXECUTABLE` can point
to an existing Chromium binary. No npm dependencies are needed on the Odoo server.

Source references: [ZXing-C++ WASM](https://github.com/Sec-ant/zxing-wasm),
[camera permissions](https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getUserMedia),
[native barcode support](https://developer.mozilla.org/en-US/docs/Web/API/BarcodeDetector),
[browser audio](https://developer.mozilla.org/en-US/docs/Web/API/Web_Audio_API/Best_practices).
