# Bundled camera decoder

`zxing-reader-3.1.4.js` and `zxing-reader-3.1.4.wasm` are unmodified reader-only
distribution files from the pinned npm package `zxing-wasm@3.1.4`:

- `dist/iife/reader/index.js` (MIT wrapper; `ZXING-WASM-LICENSE`)
- `dist/reader/zxing_reader.wasm` (ZXing-C++; `ZXING-CPP-LICENSE`)
- Upstream: https://github.com/Sec-ant/zxing-wasm
- Engine: https://github.com/zxing-cpp/zxing-cpp

Package integrity:
`sha512-1+v8p7sauddySVNG+ye7GD/0TS95BG2ycdkrC+EnBrFBFkHeIghzUt2yVjtx3NucJeNrQnhT8yGAIz60Vx9o0w==`

SHA-256:

```text
d33d09ce132a692faffbed0dce656c36cb2573b4b843885a6e036390d1071d95  zxing-reader-3.1.4.js
e8af31edb56d0522f4de74495839385ef019ba8bc90d38e5ecb2f18795d86fb2  zxing-reader-3.1.4.wasm
```

`scanner-core-v1.4.6.js` overrides the package's default WASM URL with the local,
precached binary. The workspace has no runtime npm or CDN dependency.
