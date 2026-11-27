// Recorded strategy study verdicts (UR5) and the strategies whose markers the
// API can replay (U5b). The API does not serve stored verdicts yet (E2f3), so
// this list is the single place to update when the owner records a verdict on
// #516. Never add a verdict that was not actually produced. No network or DOM.

// Plain-language text for the protocol's failure codes.
export const REASON_TEXT = Object.freeze({
  NON_POSITIVE_EXPECTANCY_AFTER_COSTS: "The average trade lost money after fees and slippage.",
  DOES_NOT_BEAT_CASH: "It did not beat simply holding cash.",
  PORTFOLIO_DRAWDOWN_LIMIT_EXCEEDED: "The whole portfolio fell further than the 30% drawdown limit.",
  SYMBOL_DRAWDOWN_LIMIT_EXCEEDED: "At least one coin fell further than the 40% drawdown limit.",
  DOES_NOT_BEAT_BUY_AND_HOLD_RISK_ADJUSTED: "Return per unit of drawdown was worse than buy-and-hold.",
  TOO_FEW_POSITIVE_WINDOWS: "It was profitable in too few of the test windows.",
});

const study = (fields) => Object.freeze({
  ...fields,
  reasons: Object.freeze(fields.reasons.map((reason) => Object.freeze(reason))),
});

// `timeframe` is the pre-registered timeframe the markers API enforces
// (null = the API replays it on any timeframe).
export const STRATEGY_STUDIES = Object.freeze([
  study({
    strategy: "ema-trend-atr-stop",
    version: "1",
    timeframe: null,
    protocol: "spot-trend-holdout v1",
    verdict: "FAIL",
    recordedOn: "2026-11-26",
    summary: "4h holdout: expectancy −0.18% per trade, portfolio −10.8%, max drawdown 40.4%.",
    source: "#516 (O1)",
    reasons: [
      { code: "NON_POSITIVE_EXPECTANCY_AFTER_COSTS" },
      { code: "DOES_NOT_BEAT_CASH" },
      { code: "PORTFOLIO_DRAWDOWN_LIMIT_EXCEEDED", detail: "40.4%" },
      { code: "SYMBOL_DRAWDOWN_LIMIT_EXCEEDED" },
    ],
  }),
  study({
    strategy: "trend-daily-regime",
    version: "1",
    timeframe: "1d",
    protocol: "spot-walk-forward-prospective v2",
    verdict: "FAIL",
    recordedOn: "2026-11-27",
    summary: "51 trades, +9.60% per trade, but the bootstrap 5% lower bound is −1.67%.",
    source: "#548 comment 7200843056",
    reasons: [
      { code: "SYMBOL_DRAWDOWN_LIMIT_EXCEEDED", detail: "BNB 41.26%, SOL 53.57%, XRP 62.07%" },
      { code: "DOES_NOT_BEAT_BUY_AND_HOLD_RISK_ADJUSTED", detail: "return/drawdown 1.47 vs 1.57" },
      { code: "TOO_FEW_POSITIVE_WINDOWS", detail: "2 of 4 windows positive; 3 needed" },
    ],
  }),
  study({
    strategy: "range-reversion-4h",
    version: "1",
    timeframe: "4h",
    protocol: "spot-walk-forward-prospective v2",
    verdict: "FAIL",
    recordedOn: "2026-11-27",
    summary: "70 trades, −1.02% per trade, portfolio −13.79%.",
    source: "#516 comment 7202743413",
    reasons: [
      { code: "NON_POSITIVE_EXPECTANCY_AFTER_COSTS", detail: "−1.02% per trade" },
      { code: "DOES_NOT_BEAT_CASH" },
      { code: "DOES_NOT_BEAT_BUY_AND_HOLD_RISK_ADJUSTED", detail: "return/drawdown −0.93 vs 0.72" },
      { code: "TOO_FEW_POSITIVE_WINDOWS", detail: "2 of 4 windows positive; 3 needed" },
    ],
  }),
]);

export const PASSING_VERDICTS = Object.freeze(new Set(["PASS", "HISTORICAL_PASS"]));

export function studyKey(item) {
  return `${item.strategy}@${item.version}`;
}

export function findStudy(strategy, version, studies = STRATEGY_STUDIES) {
  return studies.find((item) => item.strategy === strategy && String(item.version) === String(version)) ?? null;
}

export function reasonText(reason) {
  const text = REASON_TEXT[reason.code] ?? reason.code;
  return reason.detail ? `${text} (${reason.detail})` : text;
}

// One line per study, e.g. for a coin's "Why" list.
export function studyLine(item) {
  const when = item.recordedOn ? ` (${item.recordedOn})` : "";
  const why = item.reasons.length ? ` — ${item.reasons.map((reason) => reason.code).join(", ")}` : "";
  return `${item.strategy} v${item.version}, ${item.protocol}: ${item.verdict}${when}${why}`;
}

// The FAILED banner shown above replayed markers (U5b): date, reasons and the
// "illustration only" label. Null when the strategy has no recorded verdict.
export function verdictBanner(strategy, version, studies = STRATEGY_STUDIES) {
  const item = findStudy(strategy, version, studies);
  if (!item) {
    return {
      tone: "warning",
      title: `${strategy} v${version} — no study verdict recorded. Illustration only, not a trade signal.`,
      reasons: [],
    };
  }
  const failed = !PASSING_VERDICTS.has(item.verdict);
  return {
    tone: failed ? "fail" : "pass",
    title: `${item.strategy} v${item.version} — ${failed ? "FAILED" : item.verdict} verdict (${item.recordedOn}). Illustration only, not a trade signal.`,
    summary: item.summary,
    reasons: item.reasons.map(reasonText),
  };
}

// Strategies the SIGNALS pill can replay on the given timeframe. A strategy
// pre-registered for another timeframe is listed but not selectable.
export function markerStrategyOptions(timeframe, studies = STRATEGY_STUDIES) {
  return studies.map((item) => {
    const usable = item.timeframe === null || item.timeframe === timeframe;
    return {
      value: studyKey(item),
      strategy: item.strategy,
      version: item.version,
      label: `${item.strategy} v${item.version} · ${item.verdict}`,
      usable,
      reason: usable ? null : `Pre-registered for ${item.timeframe} candles; switch the timeframe to ${item.timeframe === "1d" ? "1D" : item.timeframe}.`,
    };
  });
}

// The strategy chosen when SIGNALS is first turned on: the one pre-registered
// for this timeframe, else the first usable one.
export function defaultMarkerStrategy(timeframe, studies = STRATEGY_STUDIES) {
  const options = markerStrategyOptions(timeframe, studies);
  const exact = studies.find((item) => item.timeframe === timeframe);
  return exact ? studyKey(exact) : options.find((option) => option.usable)?.value ?? null;
}

export function parseStrategyKey(key) {
  const match = /^([a-z0-9-]{1,64})@([1-9]\d{0,5})$/.exec(String(key ?? ""));
  return match ? { strategy: match[1], version: match[2] } : null;
}
