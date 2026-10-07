# Spot research cockpit preview (#298)

This is a standalone, fixture-only UX preview. It makes no network requests and has no exchange, model, approval, or order endpoint. Every market value and explanation is synthetic and is labeled as such in the UI. It is not evidence of trading performance.

## Run

From the repository root:

```sh
python3 -m http.server 4173 --directory apps/research-preview
```

Open `http://localhost:4173`. The app uses native browser modules, CSS, and SVG. No installation or credentials are needed.

## Preview architecture

The only source of display records is `fixtures.js`. `app.js` renders its exported, frozen snapshots and never calls `fetch`, WebSocket, or storage. The snapshot shape includes asset, timeframe, source, observation time, quality, and evidence version; a future typed adapter can consume validated backend responses after the production frontend gates. No local indicator or trading decision is calculated from the fixture candles. The EMA and ATR values are fixture display examples.

The static preview does not make a production frontend framework decision. A production shell, authentication, API adapter, data validation, and safety work belong to #143, #145, #146, #148, and #297. Footprint, delta, and historical liquidity heatmaps remain unavailable until validated trade and order-book history contracts exist.

## Validation

```sh
node --test apps/research-preview/preview.test.mjs
```

Inspect the five scenarios and test keyboard pair/timeframe/indicator navigation at a laptop width. No screenshots, real prices, or performance claims are embedded.
