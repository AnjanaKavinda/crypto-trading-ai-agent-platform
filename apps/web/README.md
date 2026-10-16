# Local Spot research workspace

This is a dependency-free, browser-native presentation for the local Spot
research API. It reads the API's supported symbols and exact snapshot payload;
it has no provider client, credentials, indicator calculations, signal logic,
approval, risk, order, or execution capability.

## Run locally

Start the API on its default loopback address and configure its exact allowed
frontend origin as described in [`../api/README.md`](../api/README.md):

```bash
TRADING_PLATFORM_FRONTEND_ORIGIN=http://127.0.0.1:5173 \
PYTHONPATH=apps/api/src python -m trading_platform_api
```

In a second terminal, serve this directory on loopback:

```bash
python -m http.server 5173 --bind 127.0.0.1 --directory apps/web
```

Open `http://127.0.0.1:5173` for the read-only asset workspace, or
`http://127.0.0.1:5173/watchlist.html` for the Spot market overview. The
overview reads the API-supported approved instruments and their stored
timeframe snapshots only; each row links to the workspace with validated
instrument and timeframe parameters. Changing its timeframe performs bounded
snapshot reads but never triggers collection or refresh.

The workspace makes read-only requests to
`http://127.0.0.1:8000/api/research/spot`. Initial load, navigation, view
changes and history selection do not call refresh. Refresh is a separate,
explicit user action and remains subject to the API's local configuration,
quality policy and rate limit. A database/migration is required for persisted
snapshot reads; this UI does not enable or configure collection.

Historical cutoffs are read-only and presented as historical. Candle counts
are request bounds; the API response is never sliced in the browser. If the
bound is too small for the latest exact stored snapshot, the API returns
`SPOT_CANDLE_LIMIT_EXCEEDED` (422), never a truncated or smaller older snapshot.
The UI identifies the selected timeframe and maximum: choose a larger history
bound, or explicitly refresh the same selector when eligible. Only allowlisted
error codes select this guidance; raw server details are never displayed.
Snapshot metadata shows the actual returned candle count and timeframe.
Explicit refresh requests are limited to 2 through the smaller of 501 candles
or the number fitting in the provider's 90-day OHLCV window. For example, daily
refresh accepts at most 90 candles, while 501 four-hour candles fit. Reads may
still request up to 501 candles. The UI and API both enforce the refresh window;
refresh remains explicit and never retries automatically.
All six timeframes (1m, 5m, 15m, 1h, 4h, 1d) support stored reads with bounds
50, 90, 100, 250, and 501. Daily bounds above 90 disable refresh with an explicit
90-day policy explanation; they do not disable stored historical reads.

Presentation visibility and Beginner/Pro preferences are saved in this
browser's local storage under instrument/timeframe-specific keys. These
preferences do not change API inputs or backend evidence. Reset returns to the
Beginner display defaults.

Run the dependency-free frontend checks from this directory:

```bash
npm test
```

No account or trading capability is provided. Local research data remains
non-authoritative for any signal, risk assessment, approval, or trade.
