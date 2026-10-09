import { listSupportedSymbols, readSnapshot, TIMEFRAME_SECONDS } from "./research-api.mjs";
import { validateSnapshot } from "./workspace-state.mjs";

export const APPROVED_INSTRUMENTS = Object.freeze({
  "BTC-USDT-SPOT": "BTCUSDT",
  "ETH-USDT-SPOT": "ETHUSDT",
  "BNB-USDT-SPOT": "BNBUSDT",
  "SOL-USDT-SPOT": "SOLUSDT",
  "XRP-USDT-SPOT": "XRPUSDT",
});

export const WATCHLIST_LIMIT = 250;

export function supportedWatchlistSymbols(response) {
  if (response?.provider !== "binance-spot-public" ||
      response?.redistribution !== "NOT_AUTHORIZED" ||
      !Array.isArray(response.instruments)) {
    throw new Error("The local API did not return the supported Spot-symbol contract.");
  }

  const symbols = [];
  const seen = new Set();
  for (const item of response.instruments) {
    const approvedSymbol = APPROVED_INSTRUMENTS[item?.instrument_id];
    if (approvedSymbol === undefined) continue;
    if (seen.has(item.instrument_id)) {
      throw new Error("The local API returned duplicate approved instruments.");
    }
    seen.add(item.instrument_id);
    if (item.symbol !== approvedSymbol ||
        item.venue_id !== "BINANCE-SPOT" ||
        item.eligibility !== "CHECKED_ON_EACH_REFRESH") {
      throw new Error("The local API returned an invalid approved Spot instrument.");
    }
    symbols.push({
      instrument_id: item.instrument_id,
      symbol: item.symbol,
      venue_id: item.venue_id,
    });
  }
  if (!symbols.length) throw new Error("The API returned no approved supported Spot instruments.");
  return symbols;
}

export function validateWatchlistSnapshot(snapshot, { instrumentId, symbol, timeframe }) {
  const requestedAsOf = snapshot?.temporal_context === "HISTORICAL"
    ? snapshot.requested_as_of
    : undefined;
  return validateSnapshot(snapshot, { instrumentId, symbol, timeframe, requestedAsOf });
}

export function watchlistRow(snapshot, symbol) {
  const latest = snapshot.candles.reduce((current, candle) =>
    Date.parse(candle.close_time) > Date.parse(current.close_time) ? candle : current,
  );
  const source = snapshot.lineage.sources.find(
    (item) => item.source_record_id === latest.source_record_id,
  );
  return {
    instrumentId: snapshot.instrument_id,
    symbol,
    timeframe: snapshot.timeframe,
    close: latest.metrics.close.value,
    priceUnit: latest.metrics.close.unit,
    candleTime: latest.close_time,
    volume: latest.metrics.volume.value,
    volumeUnit: latest.metrics.volume.unit,
    venue: snapshot.venue_id,
    sourceId: latest.source_record_id,
    source: source.provider_id,
    sourceRetrievedAt: source.retrieval_time,
    marketDataId: latest.market_data_id,
    snapshotId: snapshot.snapshot_id,
    qualityReportId: snapshot.data_quality.report_id,
    quality: snapshot.data_quality.status,
    reportQuality: snapshot.data_quality.report_status,
    freshnessCutoff: snapshot.freshness_cutoff,
    asOf: snapshot.as_of,
    temporalContext: snapshot.temporal_context,
    change: "Unavailable — not supplied",
    analysis: "Not provided",
  };
}

export async function readWatchlist(fetcher, timeframe, symbols) {
  if (!Object.hasOwn(TIMEFRAME_SECONDS, timeframe)) {
    throw new Error("Select a timeframe supported by the local research API.");
  }
  return Promise.all(symbols.map(async (item) => {
    try {
      const snapshot = await readSnapshot(fetcher, {
        instrumentId: item.instrument_id,
        timeframe,
        limit: WATCHLIST_LIMIT,
      });
      const validationError = validateWatchlistSnapshot(snapshot, {
        instrumentId: item.instrument_id,
        symbol: item.symbol,
        timeframe,
      });
      if (validationError) throw new Error(validationError);
      return { symbol: item.symbol, snapshot, row: watchlistRow(snapshot, item.symbol), error: null };
    } catch (error) {
      return { symbol: item.symbol, snapshot: null, row: null, error: error.message };
    }
  }));
}

export async function loadWatchlist(fetcher, timeframe) {
  if (!Object.hasOwn(TIMEFRAME_SECONDS, timeframe)) {
    throw new Error("Select a timeframe supported by the local research API.");
  }
  const response = await listSupportedSymbols(fetcher);
  return readWatchlist(fetcher, timeframe, supportedWatchlistSymbols(response));
}

export function workspaceHref(instrumentId, timeframe, supportedSymbols) {
  if (!supportedSymbols.some((item) => item.instrument_id === instrumentId) ||
      !Object.hasOwn(TIMEFRAME_SECONDS, timeframe)) return null;
  const query = new URLSearchParams({ instrument: instrumentId, timeframe });
  return `./index.html?${query}`;
}
