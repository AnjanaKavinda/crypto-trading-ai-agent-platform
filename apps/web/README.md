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

## Local refresh diagnostics

An explicit refresh gets a UUID correlation ID in the browser. The local Nginx
proxy forwards a valid UUID unchanged; for a missing or malformed ID it uses
Nginx's per-request ID instead. The API returns the ID it received in
`X-Correlation-ID`. Proxy access records are emitted only for refresh responses.

Browser, API, and proxy lifecycle records are JSON and identify the component,
event, status, timestamp, correlation ID, and refresh selector
(`instrument_id`, `timeframe`, and `limit` where known). API records also use
the existing structured logging schema. The API records receipt, provider
start, persistence start/terminal outcome, and request terminal outcome.
Existing Binance adapter `fetch`/`fetch_failure` records provide normal provider
terminal evidence; the service records provider timeout/cancellation terminals.
Proxy completion includes HTTP status and request duration;
timeframe and limit are `null` there because the proxy does not inspect request
bodies.

When a provider or persistence deadline expires, the API requests cancellation
and returns the existing timeout response without waiting indefinitely for a
cancellation-resistant child to finish cleanup. That cleanup may complete later,
but its late result is consumed only for task hygiene and is never returned as a
successful refresh or accepted as a current snapshot.

These local diagnostics omit request and market-data payloads, candle/source
data, credentials, proxy secrets, authorization headers, environment values,
and raw exception text. Error codes are fixed safe codes. Browser refresh
fetching and response-body parsing share a 60-second deadline; a timeout clears
the in-flight UI state and displays the existing safe failure state without
accepting the response as a current snapshot. Refresh remains explicit and is
never retried automatically.

No account or trading capability is provided. Local research data remains
non-authoritative for any signal, risk assessment, approval, or trade.

## Spot volume and structure analyses

The workspace presents only the `spot_analysis` entries returned with the
currently selected candle response. Values and series are withheld unless the
snapshot and underlying quality report are both `VALID`, and each non-null
result's instrument, venue, timeframe, as-of, snapshot, quality report, and
input candle IDs bind to that exact response. Per-candle output is also matched
to the corresponding candle timestamp/ID. Selector changes clear the previous
snapshot before the next read; presentation changes do not issue API requests.

| API key | Result/status behavior and provenance | Limitation | UI destination |
|---|---|---|---|
| `vwap` | Shows the wrapper status/reason, backend method/version, parameters, price/volume units, first-candle anchor, window, as-of, snapshot/quality IDs, and each point's nested status/reason/value. Only `READY` values aligned to returned candle close times are drawn on the price chart. | Cumulative bar-based typical-price VWAP anchored to the first candle in the returned snapshot; OHLCV approximation, not trade-by-trade or session VWAP. | Price-chart overlay and exact point table in the volume/structure section. |
| `volume-profile` | Shows only supplied fields, including returned POC bin index, VAH/VAL, node-bin indices and other supplied value-area fields, with returned parameters, units, method/version, and snapshot provenance. | Candle-assigned typical-price volume-profile proxy; bins/value-area parameters are backend supplied and are never recalculated in the browser. A bin index is not presented as a computed price. | Volume/structure result card. |
| `volume-confirmation` | Shows raw volume and any supplied prior sum, trailing average, or relative volume with each point's status/reason, plus returned assessment/comparison/exhaustion states and reasons. | Uses the returned lookback (currently 20); contextual assessment/comparison remains indeterminate without caller context, and exhaustion is unavailable without reliable order-flow input. | Volume/structure result card with exact point table. |
| `price-action-support-resistance` | Shows supplied candle geometry and per-candle close-location/range-comparison reasons, along with wrapper status/reason and result provenance. | Caller policies are absent; patterns, pivots, and support/resistance zones are not inferred or described as detected. | Volume/structure geometry table. |
| `spot-market-structure` | Shows the backend wrapper status and exact reason; a null result is explicitly shown without annotations. | The current API returns `UNAVAILABLE` with `CALLER_PIVOT_AND_BREAK_POLICIES_NOT_SUPPLIED`; no structure is calculated or drawn. | Volume/structure result card. |

Missing entries, null result payloads, `PARTIAL`, `WARMUP`, `UNAVAILABLE`,
stale quality, and invalid/non-valid quality are visibly distinct. Backend
reason codes and nested point reasons are retained; unavailable values are not
replaced with zero or a browser-derived estimate. These read-only observations
are not signals, recommendations, probabilities, or trading instructions.
