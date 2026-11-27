import assert from "node:assert/strict";
import test from "node:test";
import { failedCriteria, parseVerdictReason, perCoinRows, verdictError } from "../../apps/web/src/forward-verdicts.mjs";

// SYNTHETIC C-109 verdict shaped like GET /api/research/forward/verdicts items; not a real result.
const verdict = {
  contract_id: "C-109", strategy_id: "synthetic-strategy", strategy_version: "1", verdict_status: "FAIL",
  qualification_authorized: false, approval_authorized: false, execution_authorized: false,
  datasets: [
    { symbol: "BTCUSDT", timeframe: "1d", content_sha256: "a".repeat(64) },
    { symbol: "XRPUSDT", timeframe: "1d", content_sha256: "b".repeat(64) },
  ],
  verdict_reasons: ["SYMBOL_DRAWDOWN_LIMIT_EXCEEDED: XRPUSDT 50.00%", "DOES_NOT_BEAT_CASH", "TOO_FEW_POSITIVE_WINDOWS: 1 of 4 < 3"],
};

test("U7: reasons are parsed into code, detail and per-coin figure", () => {
  assert.deepEqual(parseVerdictReason("SYMBOL_DRAWDOWN_LIMIT_EXCEEDED: XRPUSDT 50.00%"),
    { code: "SYMBOL_DRAWDOWN_LIMIT_EXCEEDED", detail: "XRPUSDT 50.00%", symbol: "XRPUSDT", figure: "50.00%" });
  assert.deepEqual(parseVerdictReason("DOES_NOT_BEAT_CASH"), { code: "DOES_NOT_BEAT_CASH", detail: null, symbol: null, figure: null });
});

test("U7: failed criteria in plain words and per-coin figures only from the served reasons", () => {
  assert.deepEqual(failedCriteria(verdict).map((entry) => entry.text), [
    "At least one coin fell further than the 40% drawdown limit. (XRP 50.00%)",
    "It did not beat simply holding cash.",
    "It was profitable in too few of the test windows. (1 of 4 < 3)",
  ]);
  assert.deepEqual(perCoinRows(verdict).map((row) => [row.symbol, row.figures]), [
    ["BTCUSDT", []],
    ["XRPUSDT", ["Max drawdown 50.00% (coin limit 40%)"]],
  ]);
});

test("U7: a verdict record claiming authority or of the wrong contract is refused", () => {
  assert.equal(verdictError(verdict), null);
  assert.match(verdictError({ ...verdict, execution_authorized: true }), /authority/);
  assert.match(verdictError({ ...verdict, contract_id: "C-999" }), /Not a study verdict/);
});
