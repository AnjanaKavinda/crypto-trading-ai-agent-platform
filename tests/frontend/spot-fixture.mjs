// SYNTHETIC Spot snapshot fixtures for browser tests — labelled synthetic,
// shaped like the local research API response; not market data.
import { TIMEFRAME_SECONDS } from "../../apps/web/src/research-api.mjs";

export const instrumentId = "BTC-USDT-SPOT";
export const symbol = "BTCUSDT";
export const candleCount = 501;
export const qualityReportId = "fixture-report-btc-1m";
export const snapshotId = "fixture-snapshot-btc-1m";

function decimal(value) {
  return value.toFixed(4);
}

export function createSnapshot({
  timeframe = "1h", count = candleCount, instrumentId: instrument = instrumentId, symbol: pair = symbol,
  snapshotId: snapshotIdentity = snapshotId, qualityReportId: reportIdentity = qualityReportId,
} = {}) {
  const instrumentId = instrument;
  const symbol = pair;
  const snapshotId = snapshotIdentity;
  const qualityReportId = reportIdentity;
  const candleCount = count;
  const intervalMs = TIMEFRAME_SECONDS[timeframe] * 1000;
  const firstOpen = Date.UTC(2026, 9, 16, 0, 0, 0) - candleCount * intervalMs;
  const candles = Array.from({ length: candleCount }, (_, index) => {
    const openTime = new Date(firstOpen + index * intervalMs).toISOString();
    const closeTime = new Date(firstOpen + (index + 1) * intervalMs).toISOString();
    const open = 100 + index * 0.01;
    return {
      market_data_id: `fixture-market-${index}`,
      source_record_id: "fixture-source-btc",
      open_time: openTime,
      close_time: closeTime,
      finalization: "FINAL",
      metrics: {
        open: { value: decimal(open), unit: "USDT" },
        high: { value: decimal(open + 1), unit: "USDT" },
        low: { value: decimal(open - 1), unit: "USDT" },
        close: { value: decimal(open + 0.25), unit: "USDT" },
        volume: { value: decimal(1 + index / 10), unit: "BTC" },
      },
    };
  });
  const marketDataIds = candles.map((candle) => candle.market_data_id);
  const asOf = candles.at(-1).close_time;
  const points = (valueFor) => candles.map((candle, index) => ({
    candle_end: candle.close_time,
    ...valueFor(index),
  }));
  const result = (indicatorId, parameters, indicatorPoints, fields = {}) => ({
    indicator_id: indicatorId,
    ...fields,
    parameters,
    snapshot_id: snapshotId,
    quality_report_id: qualityReportId,
    instrument_id: instrumentId,
    venue_id: "BINANCE-SPOT",
    timeframe,
    as_of: asOf,
    metadata_version: "1",
    calculation_version: "fixture-calculation-v1",
    input_market_data_ids: marketDataIds,
    points: indicatorPoints,
  });
  const ema20 = points((index) => ({ value: decimal(100.2 + index * 0.01) }));
  const ema50 = points((index) => ({ value: decimal(100.1 + index * 0.009) }));
  const bollinger = points((index) => {
    const middle = 100 + index * 0.01;
    return {
      middle: decimal(middle),
      upper: decimal(middle + 1.5),
      lower: decimal(middle - 1.5),
      bandwidth: "0.0300",
    };
  });
  const atr = points((index) => ({ value: decimal(0.2 + index * 0.0005) }));
  const realizedVolatility = points((index) => ({ value: decimal(0.1 + index * 0.0002) }));
  const ready = (value) => ({ status: "READY", value: decimal(value), reason: null });
  const rsi = points((index) => ({ value: ready(40 + index * 0.02) }));
  const macd = points((index) => ({
    line: ready(-0.5 + index * 0.002),
    signal: ready(-0.4 + index * 0.0015),
    histogram: ready(-0.1 + index * 0.0005),
  }));
  const stochastic = points((index) => ({
    k: ready(30 + index * 0.03),
    d: ready(35 + index * 0.02),
  }));
  const cci = points((index) => ({ value: ready(-100 + index * 0.4) }));
  const analysisResult = (indicatorId, fields) => ({
    indicator_id: indicatorId,
    metadata_version: "1",
    calculation_version: `${indicatorId}-fixture-v1`,
    method_label: `${indicatorId} backend fixture method`,
    timeframe,
    instrument_id: instrumentId,
    venue_id: "BINANCE-SPOT",
    snapshot_id: snapshotId,
    quality_report_id: qualityReportId,
    as_of: asOf,
    window_start: candles[0].open_time,
    window_end: asOf,
    input_market_data_ids: marketDataIds,
    ...fields,
  });
  const volumeProfileBins = Array.from({ length: 24 }, (_, index) => ({
    index,
    lower_bound: decimal(99 + index),
    upper_bound: decimal(100 + index),
    includes_upper_bound: index === 23,
    assigned_volume: decimal(index + 1),
  }));
  const spotAnalysis = {
    vwap: {
      status: "AVAILABLE",
      reason_code: null,
      result: analysisResult("vwap", {
        parameters: [["anchor-mode", "snapshot-start"]],
        price_unit: "USDT",
        volume_unit: "BTC",
        anchor_mode: "first-candle",
        anchor_time: candles[0].open_time,
        points: candles.map((candle, index) => ({
          candle_end: candle.close_time,
          value: { value: decimal(100 + index * 0.01), status: "READY", reason: null },
        })),
      }),
    },
    "volume-profile": {
      status: "AVAILABLE",
      reason_code: null,
      result: analysisResult("volume-profile", {
        parameters: [["bin-count", 24], ["value-area-percent", 70]],
        price_unit: "USDT",
        volume_unit: "BTC",
        status: "READY",
        reason: null,
        bins: volumeProfileBins,
        poc_bin_index: 12,
        value_area_bin_indices: [8, 9, 10, 11, 12, 13, 14],
        value_area_low: "107.0000",
        value_area_high: "114.0000",
        value_area_volume: "84.0000",
        value_area_share: "0.7000",
        high_volume_node_bin_indices: [12],
        low_volume_node_bin_indices: [0, 23],
      }),
    },
    "volume-confirmation": {
      status: "PARTIAL",
      reason_code: "CONTEXTUAL_ASSESSMENTS_NOT_CONFIGURED",
      result: analysisResult("volume-confirmation", {
        parameters: [["lookback", 20]],
        price_unit: "USDT",
        volume_unit: "BTC",
        lookback: 20,
        points: candles.map((candle, index) => ({
          candle_end: candle.close_time,
          raw_volume: decimal(1 + index / 10),
          prior_volume_sum: index < 20 ? null : "20.0000",
          trailing_average: index < 20 ? null : "1.0000",
          relative_volume: index < 20 ? null : "1.1000",
          status: index < 20 ? "UNAVAILABLE" : "READY",
          reason: index < 20 ? "INSUFFICIENT_PRIOR_CANDLES" : null,
        })),
        assessment: { status: "INDETERMINATE", reason: "MISSING_EVENT_CONTEXT" },
        price_volume_comparison: { status: "INDETERMINATE", reason: "MISSING_COMPARISON_CONTEXT" },
        exhaustion_assessment: {
          status: "DATA_UNAVAILABLE",
          reason: "RELIABLE_ORDER_FLOW_NOT_SUPPLIED",
        },
        limitations: ["Caller context is not configured."],
      }),
    },
    "price-action-support-resistance": {
      status: "PARTIAL",
      reason_code: "CALLER_POLICIES_NOT_SUPPLIED",
      result: analysisResult("price-action-support-resistance", {
        method_version: "spot-price-action-geometry-fixture-v1",
        price_unit: "USDT",
        source_record_ids: ["fixture-source-btc"],
        range_baseline_policy: null,
        pattern_policy: null,
        support_resistance_policy: null,
        geometry: candles.map((candle, index) => ({
          market_data_id: candle.market_data_id,
          candle_time: candle.open_time,
          candle_end: candle.close_time,
          signed_body: "0.2500",
          range: "2.0000",
          upper_wick: "0.7500",
          lower_wick: "1.0000",
          close_location: "0.6250",
          close_location_reason: null,
          range_direction: null,
          range_comparison_reason: "NO_CALLER_BASELINE",
          patterns: [],
        })),
        pivots: [],
        zones: [],
        limitations: ["Caller policies were not supplied."],
      }),
    },
    "spot-market-structure": {
      status: "UNAVAILABLE",
      reason_code: "CALLER_PIVOT_AND_BREAK_POLICIES_NOT_SUPPLIED",
      result: null,
    },
  };

  return {
    instrument_id: instrumentId,
    symbol,
    venue_id: "BINANCE-SPOT",
    timeframe,
    as_of: asOf,
    freshness_cutoff: asOf,
    temporal_context: "CURRENT",
    snapshot_id: snapshotId,
    data_quality: {
      report_id: qualityReportId,
      status: "VALID",
      report_status: "VALID",
      policy_version: "personal-binance-spot-ohlcv-v1",
      policy_sha256: "a".repeat(64),
      report: {
        report_id: qualityReportId,
        snapshot_id: snapshotId,
        status: "VALID",
      },
    },
    lineage: {
      source_record_ids: ["fixture-source-btc"],
      market_data_ids: marketDataIds,
      adapter_version: "binance-spot-adapter-v1",
      sources: [{
        source_record_id: "fixture-source-btc",
        provider_id: "fixture-public-spot",
        retrieval_time: asOf,
      }],
    },
    persisted: true,
    candles,
    indicators: {
      "ema-20": {
        status: "AVAILABLE",
        reason_code: null,
        result: result("ema", [["period", 20]], ema20, { period: 20 }),
      },
      "ema-50": {
        status: "AVAILABLE",
        reason_code: null,
        result: result("ema", [["period", 50]], ema50, { period: 50 }),
      },
      "ema-500": {
        status: "AVAILABLE",
        reason_code: null,
        result: result("ema", [["period", 500]], ema50, { period: 500 }),
      },
      "bollinger-bands-20": {
        status: "AVAILABLE",
        reason_code: null,
        result: result("bollinger-bands", [
          ["period", 20],
          ["standard_deviation_multiplier", "2"],
        ], bollinger, { period: 20, standard_deviation_multiplier: "2" }),
      },
      "atr-14": {
        status: "AVAILABLE",
        reason_code: null,
        result: result("atr-14", [["period", 14]], atr, { period: 14 }),
      },
      "realized-volatility-20": {
        status: "AVAILABLE",
        reason_code: null,
        result: result("realized-volatility", [["period", 20]], realizedVolatility, { period: 20 }),
      },
      "rsi-14": {
        status: "AVAILABLE",
        reason_code: null,
        result: result("rsi", [["period", 14]], rsi, { period: 14 }),
      },
      "macd-12-26-9": {
        status: "AVAILABLE",
        reason_code: null,
        result: result("macd", [["fast-period", 12], ["slow-period", 26], ["signal-period", 9]], macd),
      },
      "stochastic-14-3": {
        status: "AVAILABLE",
        reason_code: null,
        result: result("stochastic", [["k-period", 14], ["d-period", 3]], stochastic),
      },
      "cci-20": {
        status: "AVAILABLE",
        reason_code: null,
        result: result("cci", [["period", 20]], cci, { period: 20 }),
      },
    },
    spot_analysis: spotAnalysis,
    order_flow: {
      status: "UNAVAILABLE",
      reason_code: "REQUIRED_TRADE_AND_BOOK_INPUTS_NOT_AVAILABLE",
      result: null,
    },
  };
}

