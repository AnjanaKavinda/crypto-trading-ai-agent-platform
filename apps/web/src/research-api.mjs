const API_ORIGIN = "http://127.0.0.1:8000";
const API_PATH = "/api/research/spot";
export const MAX_CANDLES = 501;
export const MAX_REFRESH_SECONDS = 90 * 24 * 60 * 60;
export const TIMEFRAME_SECONDS = Object.freeze({
  "1m": 60,
  "5m": 300,
  "15m": 900,
  "1h": 3600,
  "4h": 14400,
  "1d": 86400,
});

function apiError(status) {
  const message = status === 404
    ? "No stored snapshot matches this instrument, timeframe, history bound, and cutoff."
    : status === 429
      ? "The local API rate-limited this request. Wait before explicitly refreshing again."
      : status >= 500
        ? "The local research API or its configured provider/storage is unavailable."
        : status === 422
          ? "The local API rejected the selector or history bound. The snapshot was not truncated; adjust the instrument, timeframe, bound, or cutoff."
        : "The local research API rejected this request.";
  const error = new Error(message);
  error.status = status;
  return error;
}

async function request(fetcher, path, options = {}) {
  let response;
  try {
    response = await fetcher(`${API_ORIGIN}${API_PATH}${path}`, {
      ...options,
      credentials: "omit",
      cache: "no-store",
      headers: { Accept: "application/json", ...options.headers },
    });
  } catch {
    throw new Error("The local research API is unreachable.");
  }
  if (!response.ok) throw apiError(response.status);
  try {
    return await response.json();
  } catch {
    throw new Error("The local research API returned an unreadable response.");
  }
}

export function listSupportedSymbols(fetcher = globalThis.fetch) {
  return request(fetcher, "/symbols");
}

export function readSnapshot(fetcher, { instrumentId, timeframe, limit, asOf }) {
  if (!Object.hasOwn(TIMEFRAME_SECONDS, timeframe)) throw new Error("Unsupported API timeframe.");
  if (!Number.isInteger(limit) || limit < 2 || limit > MAX_CANDLES) throw new Error("History bound is outside the API limit.");
  const query = new URLSearchParams({ timeframe, limit: String(limit) });
  if (asOf) query.set("as_of", asOf);
  return request(fetcher, `/${encodeURIComponent(instrumentId)}/candles?${query}`);
}

export function refreshRequestWithinBounds(timeframe, limit, { historical = false } = {}) {
  const seconds = TIMEFRAME_SECONDS[timeframe];
  return !historical && Boolean(seconds) && Number.isInteger(limit) &&
    limit >= 2 && limit <= MAX_CANDLES &&
    limit * seconds <= MAX_REFRESH_SECONDS;
}

export function refreshSnapshot(fetcher, {
  instrumentId, timeframe, limit, now = Date.now(), asOf,
}) {
  const seconds = TIMEFRAME_SECONDS[timeframe];
  if (!seconds) throw new Error("Unsupported API timeframe.");
  if (!Number.isInteger(limit) || limit < 2 || limit > MAX_CANDLES) throw new Error("Refresh bound is outside the API limit.");
  if (asOf) throw new Error("Historical cutoffs cannot be refreshed.");
  if (!refreshRequestWithinBounds(timeframe, limit)) {
    const maximum = Math.min(MAX_CANDLES, Math.floor(MAX_REFRESH_SECONDS / seconds));
    throw new Error(`Refresh exceeds the API window limit; select ${maximum} or fewer candles for ${timeframe}.`);
  }
  const intervalMs = seconds * 1000;
  const endMs = Math.floor(now / intervalMs) * intervalMs;
  const startMs = endMs - limit * intervalMs;
  return request(fetcher, `/${encodeURIComponent(instrumentId)}/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      timeframe,
      coverage_start: new Date(startMs).toISOString(),
      coverage_end: new Date(endMs).toISOString(),
      limit,
    }),
  });
}
