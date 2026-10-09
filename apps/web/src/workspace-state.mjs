export const DEFAULT_VISIBILITY = Object.freeze(["ema-20", "ema-50", "atr-14"]);
export const INDICATOR_IDS = Object.freeze([
  "ema-20",
  "ema-50",
  "ema-500",
  "atr-14",
  "bollinger-bands-20",
  "realized-volatility-20",
  "rsi-14",
  "macd-12-26-9",
  "stochastic-14-3",
  "cci-20",
]);

const STORAGE_PREFIX = "spot-research.presentation.v1";

export function preferenceKey(instrumentId, timeframe) {
  return `${STORAGE_PREFIX}:${instrumentId}:${timeframe}`;
}

export function loadPreferences(storage, instrumentId, timeframe) {
  const defaults = { mode: "beginner", visible: [...DEFAULT_VISIBILITY] };
  try {
    const saved = JSON.parse(storage.getItem(preferenceKey(instrumentId, timeframe)));
    if (!saved || typeof saved !== "object") return defaults;
    return {
      mode: saved.mode === "pro" ? "pro" : "beginner",
      visible: Array.isArray(saved.visible)
        ? [...new Set(saved.visible.filter((id) => INDICATOR_IDS.includes(id)))]
        : [...DEFAULT_VISIBILITY],
    };
  } catch {
    return defaults;
  }
}

export function savePreferences(storage, instrumentId, timeframe, preferences) {
  const safe = {
    mode: preferences.mode === "pro" ? "pro" : "beginner",
    visible: [...new Set((preferences.visible ?? []).filter((id) => INDICATOR_IDS.includes(id)))],
  };
  try {
    storage.setItem(preferenceKey(instrumentId, timeframe), JSON.stringify(safe));
  } catch {
    return false;
  }
  return true;
}

export function snapshotLabels(snapshot) {
  if (!snapshot) return { temporal: "NO SNAPSHOT", quality: "UNAVAILABLE", severity: "error" };
  const quality = snapshot.data_quality?.status;
  const temporal = snapshot.temporal_context === "HISTORICAL"
    ? "HISTORICAL — NOT CURRENT"
    : snapshot.temporal_context === "CURRENT" ? "CURRENT CONTEXT" : "UNKNOWN TEMPORAL CONTEXT";
  const severity = quality === "VALID" ? "valid" : quality === "STALE" ? "warning" : "error";
  return { temporal, quality: typeof quality === "string" ? quality : "UNAVAILABLE", severity };
}

export function validateSnapshot(snapshot, { instrumentId, timeframe, requestedAsOf }) {
  const qualityStatuses = ["VALID", "DEGRADED", "STALE", "INCOMPLETE", "INVALID", "UNAVAILABLE"];
  const awareTimestamp = (value) => typeof value === "string" &&
    /(?:Z|[+-]\d{2}:\d{2})$/i.test(value) && Number.isFinite(Date.parse(value));
  if (!snapshot || snapshot.instrument_id !== instrumentId || snapshot.timeframe !== timeframe ||
      typeof snapshot.symbol !== "string" || snapshot.venue_id !== "BINANCE-SPOT" ||
      !["CURRENT", "HISTORICAL"].includes(snapshot.temporal_context) ||
      typeof snapshot.snapshot_id !== "string" || !snapshot.snapshot_id ||
      !snapshot.data_quality || typeof snapshot.data_quality.report_id !== "string" ||
      !snapshot.data_quality.report_id ||
      !qualityStatuses.includes(snapshot.data_quality.status) ||
      !qualityStatuses.includes(snapshot.data_quality.report_status) ||
      (snapshot.data_quality.status === "VALID" && snapshot.data_quality.report_status !== "VALID") ||
      typeof snapshot.data_quality.policy_version !== "string" ||
      !snapshot.data_quality.report || typeof snapshot.data_quality.report !== "object" ||
      snapshot.data_quality.report.report_id !== snapshot.data_quality.report_id ||
      snapshot.data_quality.report.snapshot_id !== snapshot.snapshot_id ||
      snapshot.data_quality.report.status !== snapshot.data_quality.report_status ||
      (snapshot.data_quality.status !== snapshot.data_quality.report_status &&
        !(snapshot.data_quality.status === "STALE" && snapshot.data_quality.report_status === "VALID")) ||
      !/^[0-9a-f]{64}$/.test(snapshot.data_quality.policy_sha256) ||
      !snapshot.lineage || typeof snapshot.lineage.adapter_version !== "string" ||
      !Array.isArray(snapshot.lineage.market_data_ids) ||
      !Array.isArray(snapshot.lineage.source_record_ids) ||
      !Array.isArray(snapshot.lineage.sources) ||
      !Array.isArray(snapshot.candles) || !snapshot.candles.length ||
      !snapshot.indicators || typeof snapshot.indicators !== "object" ||
      typeof snapshot.persisted !== "boolean" ||
      !snapshot.order_flow ||
      snapshot.order_flow.status !== "UNAVAILABLE" ||
      snapshot.order_flow.reason_code !== "REQUIRED_TRADE_AND_BOOK_INPUTS_NOT_AVAILABLE" ||
      snapshot.order_flow.result !== null ||
      !awareTimestamp(snapshot.as_of) || !awareTimestamp(snapshot.freshness_cutoff)) {
    return "The API response lacks required snapshot identity or provenance; no values are shown.";
  }
  const returnedCutoff = snapshot.requested_as_of;
  if (requestedAsOf) {
    if (!awareTimestamp(returnedCutoff) ||
        Date.parse(returnedCutoff) !== Date.parse(requestedAsOf) ||
        snapshot.temporal_context !== "HISTORICAL" ||
        Date.parse(snapshot.freshness_cutoff) !== Date.parse(requestedAsOf) ||
        Date.parse(snapshot.as_of) > Date.parse(requestedAsOf)) {
      return "The API response does not match the requested historical cutoff; no values are shown.";
    }
  } else if ((returnedCutoff !== undefined && returnedCutoff !== null) ||
      snapshot.temporal_context !== "CURRENT") {
    return "The API response temporal context does not match the current snapshot request; no values are shown.";
  }
  if (snapshot.candles.length !== snapshot.lineage.market_data_ids.length ||
      snapshot.lineage.market_data_ids.some((id) => typeof id !== "string" || !id) ||
      snapshot.lineage.source_record_ids.some((id) => typeof id !== "string" || !id) ||
      new Set(snapshot.lineage.market_data_ids).size !== snapshot.lineage.market_data_ids.length ||
      new Set(snapshot.lineage.source_record_ids).size !== snapshot.lineage.source_record_ids.length ||
      snapshot.candles.some((candle, index) =>
        candle.market_data_id !== snapshot.lineage.market_data_ids[index] ||
        !snapshot.lineage.source_record_ids.includes(candle.source_record_id) ||
        !awareTimestamp(candle.open_time) ||
        !awareTimestamp(candle.close_time) ||
        Date.parse(candle.close_time) <= Date.parse(candle.open_time) ||
        displayCandle(candle) === null,
      ) ||
      snapshot.lineage.source_record_ids.some((id) =>
        !snapshot.lineage.sources.some((source) => source?.source_record_id === id),
      )) {
    return "Candle values do not match the exact snapshot lineage; no chart values are shown.";
  }
  return null;
}

const INDICATOR_BINDINGS = Object.freeze({
  "ema-20": { indicatorId: "ema", parameters: { period: 20 } },
  "ema-50": { indicatorId: "ema", parameters: { period: 50 } },
  "ema-500": { indicatorId: "ema", parameters: { period: 500 } },
  "atr-14": { indicatorId: "atr-14", parameters: { period: 14 } },
  "bollinger-bands-20": { indicatorId: "bollinger-bands", parameters: { period: 20, standard_deviation_multiplier: "2" } },
  "realized-volatility-20": { indicatorId: "realized-volatility", parameters: { period: 20 } },
  "rsi-14": { indicatorId: "rsi", parameters: { period: 14 } },
  "macd-12-26-9": { indicatorId: "macd", parameters: { "fast-period": 12, "slow-period": 26, "signal-period": 9 } },
  "stochastic-14-3": { indicatorId: "stochastic", parameters: { "k-period": 14, "d-period": 3 } },
  "cci-20": { indicatorId: "cci", parameters: { period: 20 } },
});

export function indicatorBindingError(snapshot, indicatorId, indicator) {
  if (snapshot?.data_quality?.status !== "VALID" ||
      snapshot?.data_quality?.report_status !== "VALID") return "QUALITY_NOT_VALID";
  if (!indicator || !["AVAILABLE", "WARMUP", "UNAVAILABLE"].includes(indicator.status)) {
    return "INDICATOR_STATUS_UNAVAILABLE";
  }
  const result = indicator.result;
  if (result == null) {
    return indicator.status === "UNAVAILABLE" ? null : "INDICATOR_RESULT_MISSING";
  }
  const expected = INDICATOR_BINDINGS[indicatorId];
  if (typeof result !== "object") return "INDICATOR_PROVENANCE_MISMATCH";
  const parameterEntries = Array.isArray(result.parameters)
    ? result.parameters
    : ["period", "standard_deviation_multiplier"]
        .filter((key) => result[key] !== undefined)
        .map((key) => [key, result[key]]);
  if (!Array.isArray(parameterEntries) ||
      parameterEntries.some((item) => !Array.isArray(item) || item.length !== 2 ||
        typeof item[0] !== "string") ||
      new Set(parameterEntries.map(([name]) => name)).size !== parameterEntries.length) {
    return "INDICATOR_PROVENANCE_MISMATCH";
  }
  const actualParameters = Object.fromEntries(parameterEntries);
  if (!expected ||
      parameterEntries.length !== Object.keys(actualParameters).length ||
      Object.keys(actualParameters).length !== Object.keys(expected.parameters).length ||
      result.indicator_id !== expected.indicatorId ||
      Object.entries(expected.parameters).some(([name, value]) =>
        typeof actualParameters[name] !== typeof value || actualParameters[name] !== value) ||
      result.snapshot_id !== snapshot.snapshot_id ||
      result.quality_report_id !== snapshot.data_quality.report_id ||
      result.instrument_id !== snapshot.instrument_id ||
      result.venue_id !== snapshot.venue_id ||
      result.timeframe !== snapshot.timeframe ||
      result.as_of !== snapshot.as_of ||
      typeof result.metadata_version !== "string" ||
      typeof result.calculation_version !== "string" ||
      !Array.isArray(result.input_market_data_ids) ||
      result.input_market_data_ids.length !== snapshot.lineage.market_data_ids.length ||
      result.input_market_data_ids.some((id, index) => id !== snapshot.lineage.market_data_ids[index]) ||
      !Array.isArray(result.points) ||
      result.points.length !== snapshot.candles.length ||
      result.points.some((point, index) => point?.candle_end !== snapshot.candles[index].close_time)) {
    return "INDICATOR_PROVENANCE_MISMATCH";
  }
  return null;
}

export function latestIndicatorValues(result) {
  const point = Array.isArray(result?.points) ? result.points.at(-1) : null;
  if (!point) return { values: [], unavailable: [] };
  const fields = ["value", "middle", "upper", "lower", "bandwidth", "line", "signal", "histogram", "k", "d"];
  const values = [];
  const unavailable = [];
  for (const field of fields) {
    const raw = point[field];
    if (typeof raw === "string" &&
        /^-?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/.test(raw) &&
        Number.isFinite(Number(raw))) {
      values.push([field, raw]);
    } else if (raw && typeof raw === "object") {
      if (raw.status === "READY" && typeof raw.value === "string" &&
          /^-?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/.test(raw.value) &&
          Number.isFinite(Number(raw.value))) {
        values.push([field, raw.value]);
      } else if (raw.status === "WARMUP" || raw.status === "UNDEFINED") {
        unavailable.push(`${field}: ${raw.status}${raw.reason ? ` (${raw.reason})` : ""}`);
      }
    }
  }
  return { values, unavailable };
}

export function plotValues(result, field = "value") {
  if (!Array.isArray(result?.points)) return [];
  return result.points.flatMap((point) => {
    const value = point?.[field];
    if (typeof point?.candle_end !== "string" || typeof value !== "string") return [];
    if (!/^-?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/.test(value) || !Number.isFinite(Number(value))) return [];
    return [{ candleEnd: point.candle_end, value }];
  });
}

export function displayCandle(candle) {
  if (!candle || candle.finalization !== "FINAL" || !candle.metrics ||
      typeof candle.metrics !== "object" || Array.isArray(candle.metrics)) return null;
  const values = {};
  for (const key of ["open", "high", "low", "close", "volume"]) {
    const metric = candle.metrics[key];
    if (typeof metric?.value !== "string" ||
        typeof metric?.unit !== "string" || !metric.unit ||
        !/^-?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/.test(metric.value)) return null;
    const numeric = Number(metric.value);
    if (!Number.isFinite(numeric)) return null;
    values[key] = { exact: metric.value, numeric, unit: metric.unit };
  }
  if (["open", "high", "low", "close"].some((key) => values[key].numeric <= 0) ||
      values.high.numeric < Math.max(values.open.numeric, values.close.numeric) ||
      values.low.numeric > Math.min(values.open.numeric, values.close.numeric) ||
      values.low.numeric > values.high.numeric || values.volume.numeric < 0) return null;
  return values;
}

export function snapshotCandles(snapshot) {
  if (!Array.isArray(snapshot?.candles) || snapshot.candles.length === 0) return { candles: [], error: "No candle observations were returned." };
  const candles = snapshot.candles.map((candle) => ({ source: candle, values: displayCandle(candle) }));
  if (candles.some(({ values }) => values === null)) {
    return { candles: [], error: "The candle response is incomplete or invalid; no chart values are shown." };
  }
  return { candles, error: null };
}
