# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: test_hero_map_tiles.spec.js >> tile requests fire: driver page — CartoCDN vector tiles
- Location: tests/test_hero_map_tiles.spec.js:48:3

# Error details

```
Error: No tile requests matching /basemaps\.cartocdn\.com\/.+\/\d+\/\d+\/\d+\.(png|pbf|mvt)/ observed within 10s of map load on /driver. This likely means maplibregl.workerUrl was removed or the CDN bundle URL has drifted. Restore the workerUrl assignment (see public/index.html line ~822 and public/driver/index.html line ~669 and public/passenger/index.html line ~479).

expect(received).toBeGreaterThan(expected)

Expected: > 0
Received:   0

Call Log:
- Timeout 10000ms exceeded while waiting on the predicate
```

# Page snapshot

```yaml
- generic [active] [ref=e1]:
  - generic [ref=e3]:
    - generic [ref=e4]: 🚌 نقل دمشق
    - generic [ref=e5]: تطبيق السائق
    - textbox "البريد الإلكتروني" [ref=e6]
    - textbox "كلمة المرور" [ref=e7]
    - button "دخول — Sign In" [ref=e8] [cursor=pointer]
  - generic [ref=e9]:
    - generic [ref=e11]:
      - generic [ref=e12]: سائق
      - generic [ref=e13]: المرجة ← الغربية
      - generic [ref=e16]: لا رحلة
      - button "English" [ref=e18] [cursor=pointer]
    - generic [ref=e19]:
      - generic [ref=e20]: ✅
      - generic [ref=e21]: على المسار
      - generic [ref=e22]: On Route
    - generic [ref=e23]:
      - generic [ref=e24]: "0"
      - generic [ref=e25]: كم/س
      - generic [ref=e26]: متوقف · Stopped
    - generic [ref=e27]:
      - generic [ref=e28]:
        - generic [ref=e29]: 0:00
        - generic [ref=e30]: وقت الرحلة
      - generic [ref=e31]:
        - generic [ref=e32]: "0.0"
        - generic [ref=e33]: كم مقطوع
      - generic [ref=e34]:
        - generic [ref=e35]: —
        - generic [ref=e36]: الالتزام
    - generic [ref=e39]:
      - text: ابدأ رحلة جديدة للبدء بتتبع التوقفات
      - text: Start a trip to begin tracking stops
```

# Test source

```ts
  1  | /**
  2  |  * Canary test: map pages actually issue tile requests after load.
  3  |  *
  4  |  * Regression guard for the workerUrl fix documented in public/index.html:
  5  |  *   "MapLibre v4 CDN fix: worker URL must be set explicitly; without it the
  6  |  *    worker blob URL fails to importScripts() the CDN bundle and the
  7  |  *    tile-fetching thread never starts (map canvas initialises fine but
  8  |  *    no tile requests are ever made)."
  9  |  *
  10 |  * Without this guard, removing the workerUrl assignment — or upgrading
  11 |  * maplibre-gl to a version where the CSP worker bundle path changes —
  12 |  * produces a blank map with NO visible error. This test catches that.
  13 |  *
  14 |  * DAM-451
  15 |  */
  16 | 
  17 | 'use strict';
  18 | 
  19 | const { test, expect } = require('@playwright/test');
  20 | 
  21 | // Tile patterns per page.
  22 | // Each entry: { path, tilePattern, description }
  23 | // tilePattern is matched against the full request URL.
  24 | const MAP_PAGES = [
  25 |   {
  26 |     path: '/',
  27 |     tilePattern: /tile\.openstreetmap\.org\/\d+\/\d+\/\d+\.png/,
  28 |     description: 'hero map (index) — OSM raster tiles',
  29 |   },
  30 |   {
  31 |     path: '/driver',
  32 |     tilePattern: /basemaps\.cartocdn\.com\/.+\/\d+\/\d+\/\d+\.(png|pbf|mvt)/,
  33 |     description: 'driver page — CartoCDN vector tiles',
  34 |   },
  35 |   {
  36 |     path: '/passenger',
  37 |     tilePattern: /basemaps\.cartocdn\.com\/.+\/\d+\/\d+\/\d+\.(png|pbf|mvt)/,
  38 |     description: 'passenger page — CartoCDN vector tiles',
  39 |   },
  40 | ];
  41 | 
  42 | const BASE_URL = process.env.CANARY_BASE_URL || 'http://localhost:7799';
  43 | 
  44 | // How long to wait (ms) for the first tile request after the map fires 'load'.
  45 | const TILE_WAIT_MS = 10_000;
  46 | 
  47 | for (const { path, tilePattern, description } of MAP_PAGES) {
  48 |   test(`tile requests fire: ${description}`, async ({ page }) => {
  49 |     // Collect all matching tile request URLs observed during the test.
  50 |     const tileRequests = [];
  51 |     page.on('request', (req) => {
  52 |       if (tilePattern.test(req.url())) {
  53 |         tileRequests.push(req.url());
  54 |       }
  55 |     });
  56 | 
  57 |     // Navigate to the page. waitUntil:'load' ensures the document and all
  58 |     // synchronous scripts have run (including the workerUrl assignment).
  59 |     await page.goto(`${BASE_URL}${path}`, { waitUntil: 'load' });
  60 | 
  61 |     // Wait up to TILE_WAIT_MS for at least one tile request to appear.
  62 |     // MapLibre starts fetching tiles when the 'load' event fires on the map
  63 |     // object, which follows the page load event by a short time.
> 64 |     await expect
     |     ^ Error: No tile requests matching /basemaps\.cartocdn\.com\/.+\/\d+\/\d+\/\d+\.(png|pbf|mvt)/ observed within 10s of map load on /driver. This likely means maplibregl.workerUrl was removed or the CDN bundle URL has drifted. Restore the workerUrl assignment (see public/index.html line ~822 and public/driver/index.html line ~669 and public/passenger/index.html line ~479).
  65 |       .poll(
  66 |         () => tileRequests.length,
  67 |         {
  68 |           message:
  69 |             `No tile requests matching ${tilePattern} observed within ` +
  70 |             `${TILE_WAIT_MS / 1000}s of map load on ${path}. ` +
  71 |             `This likely means maplibregl.workerUrl was removed or the ` +
  72 |             `CDN bundle URL has drifted. Restore the workerUrl assignment ` +
  73 |             `(see public/index.html line ~822 and public/driver/index.html ` +
  74 |             `line ~669 and public/passenger/index.html line ~479).`,
  75 |           timeout: TILE_WAIT_MS,
  76 |           intervals: [250, 500, 1000],
  77 |         }
  78 |       )
  79 |       .toBeGreaterThan(0);
  80 | 
  81 |     // Surface the first tile URL in the output so regressions are easy to diagnose.
  82 |     console.log(`  [${path}] first tile: ${tileRequests[0]}`);
  83 |     console.log(`  [${path}] total tile requests captured: ${tileRequests.length}`);
  84 |   });
  85 | }
  86 | 
```