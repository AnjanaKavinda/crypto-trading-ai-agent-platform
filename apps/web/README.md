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

Open `http://127.0.0.1:5173`. The workspace makes read-only requests to
`http://127.0.0.1:8000/api/research/spot`. Initial load, navigation, view
changes and history selection do not call refresh. Refresh is a separate,
explicit user action and remains subject to the API's local configuration,
quality policy and rate limit. A database/migration is required for persisted
snapshot reads; this UI does not enable or configure collection.

Historical cutoffs are read-only and presented as historical. Candle counts
are request bounds; the API response is never sliced in the browser. If the
bound is too small for an exact stored snapshot, the API error is shown instead
of presenting a truncated snapshot.
Explicit refresh requests accept 2–501 aligned closed candles without a
frontend calendar-span cap. The Binance adapter has a separate 90-day
historical-request capability limit, so a longer request may return a sanitized
provider error; refresh remains explicit and never retries automatically.

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
