// Signal Center state (U5c). A coin's state comes ONLY from the forward-stage
// API (E2f2): 🟢 "Validated BUY" needs a FORWARD_PASS strategy with an open or
// pending SIMULATED signal for that coin, 🟡 "Forward-testing — paper only"
// needs a FORWARD_TESTING strategy, everything else (including any failed or
// unreadable record) is 🔴 "No signal — stay out". No network or DOM here.

export const FORWARD_CANDIDATES = Object.freeze([
  Object.freeze({ strategy: "trend-daily-regime", version: "1", timeframe: "1d" }),
  Object.freeze({ strategy: "range-reversion-4h", version: "1", timeframe: "4h" }),
]);

export const SIGNAL_STATES = Object.freeze({
  red: Object.freeze({ mark: "🔴", title: "No signal — stay out" }),
  yellow: Object.freeze({ mark: "🟡", title: "Forward-testing — paper only" }),
  green: Object.freeze({ mark: "🟢", title: "Validated BUY" }),
});

const LABEL = "SIMULATED RESEARCH EVIDENCE - NOT AN ORDER";
const STAGES = new Set(["NOT_VALIDATED", "HISTORICAL_PASS", "FORWARD_TESTING", "FORWARD_PASS", "FAIL"]);

// The record must be the requested candidate's SIMULATED evidence with no
// authority; anything else is treated as unavailable (fail closed).
export function forwardRecordError(record, candidate) {
  if (!record || typeof record !== "object") return "No forward record.";
  if (record.label !== LABEL) return "The forward record is not labelled as simulated research evidence.";
  if (record.strategy?.strategy_id !== candidate.strategy || String(record.strategy?.version) !== String(candidate.version)) {
    return "The forward record belongs to another strategy or version.";
  }
  const authority = record.authority ?? {};
  if (["qualification_authorized", "approval_authorized", "execution_authorized"].some((key) => authority[key] !== false)) {
    return "The forward record claims an authority it must not have.";
  }
  if (!STAGES.has(record.stage) || !record.forward || typeof record.signals !== "object" || record.signals === null) {
    return "The forward record is not in the expected form.";
  }
  return null;
}

const STAGE_TEXT = Object.freeze({
  HISTORICAL_FAIL: "failed its historical study",
  FORWARD_EXPECTANCY_NOT_POSITIVE: "failed forward testing: the average simulated trade lost money",
  FORWARD_DRAWDOWN_ABOVE_1_5X_HISTORICAL: "failed forward testing: the simulated drawdown was too deep",
  NO_HISTORICAL_VERDICT_RECORDED: "has no recorded historical verdict yet",
  NO_FORWARD_CANDLES_YET: "passed its historical study; no forward candles yet",
  REVIEW_POINT_NOT_REACHED: "is forward-testing (paper only) until its review point",
  PREREGISTERED_FORWARD_CRITERIA_MET: "met its pre-registered forward criteria",
});

export function strategyName(candidate) {
  return `${candidate.strategy} v${candidate.version}`;
}

export function stageText(record) {
  return STAGE_TEXT[record.reason] ?? `${record.stage} (${record.reason ?? "no reason given"})`;
}

function liveSignal(record, symbol) {
  const signals = Array.isArray(record.signals?.[symbol]) ? record.signals[symbol] : [];
  return signals.filter((signal) => ["OPEN", "PENDING_ENTRY"].includes(signal?.status)).at(-1) ?? null;
}

// stages: [{ candidate, record, error }] — one per forward candidate.
// mode "beginner" never names failed strategies (they appear only in Pro).
export function coinSignal(symbol, stages, mode = "beginner") {
  const usable = stages.filter((item) => item.record && !item.error);
  const pass = usable.find((item) => item.record.stage === "FORWARD_PASS" && liveSignal(item.record, symbol));
  const testing = usable.find((item) => item.record.stage === "FORWARD_TESTING");
  const chosen = pass ?? testing ?? null;
  const state = pass ? "green" : testing ? "yellow" : "red";
  const reasons = [];
  if (state === "red") {
    const failed = usable.filter((item) => item.record.stage === "FAIL");
    if (mode === "pro") {
      for (const item of stages) {
        reasons.push(item.error
          ? `${strategyName(item.candidate)}: forward record unavailable — ${item.error}`
          : `${strategyName(item.candidate)} ${stageText(item.record)}.`);
      }
    } else {
      if (failed.length) reasons.push("No strategy has passed its study, so there is no signal for this coin.");
      if (stages.some((item) => item.error)) reasons.push("Some forward records could not be read, so the card fails closed to no signal.");
      for (const item of usable.filter((entry) => entry.record.stage !== "FAIL")) {
        reasons.push(`${strategyName(item.candidate)} ${stageText(item.record)}.`);
      }
      if (!reasons.length) reasons.push("No strategy has a validated signal for this coin.");
    }
  } else {
    reasons.push(`${strategyName(chosen.candidate)} ${stageText(chosen.record)}.`);
  }
  return {
    symbol,
    state,
    ...SIGNAL_STATES[state],
    reasons,
    candidate: chosen?.candidate ?? null,
    record: chosen?.record ?? null,
    signal: chosen ? liveSignal(chosen.record, symbol) : null,
  };
}

// --- Position size (exact decimal arithmetic; display/research only) ---
const SCALE = 10n ** 8n;
const DECIMAL = /^(?:0|[1-9]\d{0,14})(?:\.\d{1,8})?$/;

function scaled(text) {
  const value = String(text ?? "").trim();
  if (!DECIMAL.test(value)) return null;
  const [whole, fraction = ""] = value.split(".");
  return BigInt(whole) * SCALE + BigInt(fraction.padEnd(8, "0"));
}

function plain(value, decimals) {
  const whole = value / SCALE;
  const fraction = (value % SCALE).toString().padStart(8, "0").slice(0, decimals);
  return decimals ? `${whole}.${fraction}` : String(whole);
}

// size = (account × risk%) ÷ (entry − stop), capped at account ÷ entry (Spot, no leverage).
export function positionSize({ account, riskPct, entry, stop }) {
  const a = scaled(account);
  const r = scaled(riskPct);
  if (a === null || a <= 0n) return { ok: false, reason: "Enter your account size in USDT, e.g. 1000." };
  if (r === null || r <= 0n || r > 100n * SCALE) return { ok: false, reason: "Risk per trade must be above 0% and at most 100%." };
  const e = scaled(entry);
  const s = scaled(stop);
  if (e === null || s === null || e <= 0n) return { ok: false, reason: "No simulated entry and stop to size against." };
  if (s >= e) return { ok: false, reason: "The stop is not below the entry, so no long size can be computed." };
  const risk = (a * r) / (100n * SCALE);
  const byRisk = (risk * SCALE) / (e - s);
  const cap = (a * SCALE) / e;
  const capped = byRisk > cap;
  return {
    ok: true,
    quantity: plain(capped ? cap : byRisk, 8),
    riskAmount: plain(risk, 2),
    capped,
  };
}

export const WHAT_COULD_GO_WRONG = Object.freeze({
  red: Object.freeze([
    "Trading without a validated strategy is guessing: every strategy tested so far lost money or broke its risk limits.",
    "Crypto prices can move several percent in a day, so a loss can come faster than you expect.",
    "Fees and slippage are paid on every trade, win or lose.",
  ]),
  yellow: Object.freeze([
    "This is paper only: the forward results are simulated and still too few to trust.",
    "A fast move can jump past the stop, so the loss can be bigger than the planned risk.",
    "A strategy can stop working when the market changes.",
  ]),
  green: Object.freeze([
    "A validated strategy can still lose: past and forward results do not promise the next trade.",
    "A fast move can jump past the stop, so the loss can be bigger than the planned risk.",
    "Risk at most 1% of the account per trade and compare real results with the forward record.",
  ]),
});

export const GLOSSARY = Object.freeze({
  "Forward testing": "Running a frozen strategy on new candles after its study, to see if it keeps working. Results are simulated, never real orders.",
  "Simulated": "Calculated by the research tool as if traded at the next open with fees and slippage. No order was placed.",
  "Historical study": "The pre-registered test of the strategy on past data. All recorded studies so far failed.",
  "Expectancy": "The average result per trade after fees. Above zero means the strategy made money on average.",
  "Win rate": "The share of closed trades that made money.",
  "Max drawdown": "The deepest fall from a peak in the strategy's value, as a share of that peak.",
  "Stop": "The price at which the strategy would exit to cap the loss.",
  "Position size": "How much of the coin to hold so that hitting the stop loses only your chosen risk % of the account.",
  "Risk %": "The share of your account you accept to lose if the stop is hit. 1% is the default.",
  "Review point": "The pre-registered number of trades or date at which forward results are judged.",
});

export function percentText(fraction) {
  const value = Number(fraction);
  if (fraction === null || fraction === undefined || !Number.isFinite(value)) return "—";
  return `${(value * 100).toFixed(2)}%`;
}
