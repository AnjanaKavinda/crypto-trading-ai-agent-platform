import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

import { change24h, displayPrice, STRATEGY_STUDIES, studyLine, todayState } from "../../apps/web/src/today-state.mjs";
import {
  defaultMarkerStrategy, markerStrategyOptions, parseStrategyKey, reasonText, verdictBanner,
} from "../../apps/web/src/strategy-studies.mjs";
import { APPROVED_INSTRUMENTS, readWatchlist, WATCHLIST_LIMIT } from "../../apps/web/src/watchlist-state.mjs";

// SYNTHETIC row shaped like watchlistRow() output; not market data.
const row = (overrides = {}) => ({
  instrumentId: "BTC-USDT-SPOT",
  timeframe: "4h",
  close: "101.00",
  priceUnit: "USDT",
  candleTime: "2026-10-09T16:00:00Z",
  asOf: "2026-10-09T16:00:01Z",
  freshnessCutoff: "2026-10-09T20:00:00Z",
  quality: "VALID",
  temporalContext: "CURRENT",
  ...overrides,
});

test("UR5: every recorded verdict is listed — three FAILs with dates and reasons", () => {
  assert.deepEqual(
    STRATEGY_STUDIES.map((study) => [study.strategy, study.version, study.verdict, study.recordedOn]),
    [
      ["ema-trend-atr-stop", "1", "FAIL", "2026-11-26"],
      ["trend-daily-regime", "1", "FAIL", "2026-11-27"],
      ["range-reversion-4h", "1", "FAIL", "2026-11-27"],
    ],
  );
  for (const study of STRATEGY_STUDIES) {
    assert.ok(study.reasons.length >= 3, study.strategy);
    for (const reason of study.reasons) assert.doesNotMatch(reasonText(reason), /^[A-Z_]+$/, "reasons are in plain words");
  }
  assert.match(studyLine(STRATEGY_STUDIES[0]), /ema-trend-atr-stop v1.*FAIL \(2026-11-26\).*DOES_NOT_BEAT_CASH/);
  assert.match(reasonText(STRATEGY_STUDIES[1].reasons[0]), /40% drawdown limit.*XRP 62\.07%/);
});

test("every coin is NO_TRADE while no strategy has passed, with plain reasons", () => {
  const result = todayState({ symbol: "BTCUSDT", row: row(), error: null });
  assert.equal(result.decision, "NO_TRADE");
  assert.equal(result.chip, "NO_TRADE");
  assert.equal(result.data, "VALID");
  assert.equal(result.price, "101.00 USDT");
  assert.match(result.freshness, /freshness cutoff 2026-10-09T20:00:00Z/);
  assert.equal(result.reasons[0], "No strategy has passed its study.");
  assert.match(result.reasons[1], /All 3 recorded studies failed/);
  assert.deepEqual(result.studies, STRATEGY_STUDIES.map(studyLine));
  assert.ok(result.reasons.every((reason) => !/\bBUY\b|\bSELL\b/.test(reason)));
});

test("invalid or missing data is shown on the chip but the coin stays NO_TRADE", () => {
  const stale = todayState({ symbol: "SOLUSDT", row: row({ quality: "STALE" }), error: null });
  assert.equal(stale.decision, "NO_TRADE");
  assert.equal(stale.chip, "STALE");
  assert.equal(stale.tone, "warning");
  assert.match(stale.reasons[0], /Data quality STALE/);

  const missing = todayState({ symbol: "BNBUSDT", row: null, error: "The local research API is unreachable. [HTTP 503]" });
  assert.equal(missing.decision, "NO_TRADE");
  assert.equal(missing.chip, "UNAVAILABLE");
  assert.equal(missing.price, null);
  assert.match(missing.reasons[0], /unreachable\. \[HTTP 503\]/);
});

test("a passed study without a connected signal source still fails closed to NO_TRADE", () => {
  const studies = [{ strategy: "synthetic", version: "1", protocol: "p", verdict: "PASS", recordedOn: null, reasons: [] }];
  const result = todayState({ symbol: "BTCUSDT", row: row(), error: null }, studies);
  assert.equal(result.decision, "NO_TRADE");
  assert.match(result.reasons[0], /no signal source is connected/);
});

test("24h change uses only two returned closes exactly 24h apart; price keeps the exact value", () => {
  // SYNTHETIC 4h candles; not market data.
  const candle = (close, closeTime) => ({ close_time: closeTime, metrics: { close: { value: close, unit: "USDT" } } });
  const times = Array.from({ length: 7 }, (_, index) => new Date(Date.UTC(2026, 0, 1, 4 * (index + 1))).toISOString());
  const snapshot = { candles: times.map((time, index) => candle(index === 0 ? "100.00" : index === 6 ? "103.50" : "101.00", time)) };
  const { text, direction, exact, percent } = change24h(snapshot);
  assert.deepEqual({ text, direction, exact }, { text: "+3.50%", direction: "up", exact: "100.00 → 103.50 USDT" });
  assert.ok(Math.abs(percent - 3.5) < 1e-9);
  assert.equal(change24h({ candles: snapshot.candles.slice(1) }), null, "no candle exactly 24h earlier");
  assert.deepEqual(displayPrice(row({ close: "0.94771234" })), { text: "0.9477", exact: "0.94771234 USDT" });
});

test("U5b: SIGNALS banner names the FAILED verdict, date and reasons; strategies follow their timeframe", () => {
  const banner = verdictBanner("range-reversion-4h", "1");
  assert.equal(banner.tone, "fail");
  assert.equal(banner.title, "range-reversion-4h v1 — FAILED verdict (2026-11-27). Illustration only, not a trade signal.");
  assert.ok(banner.reasons.length >= 3);
  assert.match(verdictBanner("unknown", "9").title, /no study verdict recorded\. Illustration only, not a trade signal/);

  assert.equal(defaultMarkerStrategy("4h"), "range-reversion-4h@1");
  assert.equal(defaultMarkerStrategy("1d"), "trend-daily-regime@1");
  assert.equal(defaultMarkerStrategy("1h"), "ema-trend-atr-stop@1");
  const on1h = Object.fromEntries(markerStrategyOptions("1h").map((option) => [option.value, option]));
  assert.equal(on1h["ema-trend-atr-stop@1"].usable, true);
  assert.equal(on1h["trend-daily-regime@1"].usable, false);
  assert.match(on1h["trend-daily-regime@1"].reason, /1D/);
  assert.deepEqual(parseStrategyKey("trend-daily-regime@1"), { strategy: "trend-daily-regime", version: "1" });
  assert.equal(parseStrategyKey("x@0"), null);
  assert.equal(parseStrategyKey("../x@1"), null);
});

test("UR4: Today reads the stored 501-candle snapshots and names the API error code", async () => {
  const calls = [];
  const fetcher = async (url) => {
    calls.push(url);
    return { ok: false, status: 422, json: async () => ({ code: "SPOT_CANDLE_LIMIT_EXCEEDED" }) };
  };
  const symbols = Object.entries(APPROVED_INSTRUMENTS).map(([instrument_id, symbol]) => ({ instrument_id, symbol }));
  const entries = await readWatchlist(fetcher, "4h", symbols);
  assert.equal(WATCHLIST_LIMIT, 501);
  assert.ok(calls.every((url) => new URL(url).searchParams.get("limit") === "501"));
  assert.ok(calls.every((url) => !url.includes("strategy-markers") && !url.includes("/refresh")));
  for (const entry of entries) {
    assert.match(todayState(entry).reasons[0], /\[SPOT_CANDLE_LIMIT_EXCEEDED\]/);
  }
});

test("UR4: every page declares an inline favicon so the browser never requests a missing one", async () => {
  for (const page of ["desk", "index", "watchlist", "signals", "evidence"]) {
    const html = await readFile(new URL(`../../apps/web/${page}.html`, import.meta.url), "utf8");
    assert.match(html, /<link rel="icon" href="data:image\/svg\+xml,/, page);
  }
});
