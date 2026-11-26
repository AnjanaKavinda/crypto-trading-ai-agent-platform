// U8 — My results: the owner's recorded trades and NO_TRADE decisions scored by the
// backend against the pre-registered owner-results protocol (E4). Read-only: one GET,
// no polling, no storage, no trade action. Every number shown is a backend value;
// display rounding never replaces the exact value (kept in the element title).
import { API_ORIGIN } from "./runtime-config.mjs";

export const SCORE_PATH = "/api/research/owner-outcomes/score";
const VERDICTS = new Set(["PASS", "FAIL", "INCONCLUSIVE"]);
const DECIMAL = /^-?\d+(\.\d+)?(E[+-]?\d+)?$/i;

function invalid() {
  return new Error("Invalid results response. No score is displayed.");
}
const isDecimal = (value) => typeof value === "string" && DECIMAL.test(value);
const optionalDecimal = (value) => value === null || isDecimal(value);

// Fail closed: only a well-formed, non-authorizing score is rendered.
export function validateScore(score) {
  const trades = score?.trades;
  const ok = score
    && score.execution_authorized === false
    && score.trade_facts_verified === false
    && score.protocol?.protocol_id === "owner-results"
    && /^[0-9a-f]{64}$/.test(score.protocol_sha256 ?? "")
    && VERDICTS.has(score.verdict?.status)
    && Array.isArray(score.verdict.reasons)
    && trades && Number.isInteger(trades.counted) && trades.counted >= 0
    && ["win_rate", "expectancy", "profit_factor", "total_return", "max_drawdown", "net_result_usdt"]
      .every((key) => optionalDecimal(trades[key]))
    && Array.isArray(trades.items) && Array.isArray(trades.excluded)
    && score.baselines?.CASH && score.baselines?.BUY_AND_HOLD
    && score.no_trade_decisions && typeof score.no_trade_decisions.status === "string";
  if (!ok) throw invalid();
  return score;
}

export async function readOwnerScore(fetcher = globalThis.fetch) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 15000);
  try {
    const response = await fetcher(API_ORIGIN + SCORE_PATH, {
      method: "GET", credentials: "omit", cache: "no-store", signal: controller.signal,
      headers: { Accept: "application/json" },
    });
    if (!response.ok) {
      throw new Error(response.status === 403
        ? "Results are available only in the local research environment."
        : "The local research API could not score your results right now. Nothing is inferred.");
    }
    return validateScore(await response.json());
  } catch (error) {
    if (error.name === "AbortError" || error instanceof TypeError) {
      throw new Error("The local research API is unavailable. No results are displayed.");
    }
    throw error;
  } finally {
    clearTimeout(timer);
  }
}

// "0.012345" -> "1.23%"; null -> "unavailable". Display only.
export function percent(value) {
  if (value === null || value === undefined) return "unavailable";
  if (!isDecimal(value)) throw invalid();
  return `${(Number(value) * 100).toFixed(2)}%`;
}

export function plain(value, digits = 2) {
  if (value === null || value === undefined) return "unavailable";
  if (!isDecimal(value)) throw invalid();
  return Number(value).toFixed(digits);
}

function el(document, tag, text) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = String(text);
  return node;
}

function fact(document, parent, label, shown, exact) {
  const row = el(document, "p", `${label}: ${shown}`);
  if (exact !== undefined && exact !== null) row.title = `Exact backend value: ${exact}`;
  parent.append(row);
}

function heading(document, parent, text) {
  parent.append(el(document, "h3", text));
}

export function renderOwnerResults(document, parent, score) {
  const { verdict, trades, baselines, no_trade_decisions: noTrade, protocol } = validateScore(score);
  parent.replaceChildren();

  const head = el(document, "p", `Verdict: ${verdict.status}`);
  head.className = `verdict verdict-${verdict.status.toLowerCase()}`;
  parent.append(head);
  parent.append(el(document, "p", verdict.reasons.length ? verdict.reasons.join(" · ") : "No failing criteria reported."));
  parent.append(el(document, "p",
    `Protocol ${protocol.protocol_id} v${protocol.version}: at least ${protocol.min_trades} closed trades, `
    + `positive expectancy after fees, beats cash, max drawdown ≤ ${percent(String(protocol.max_drawdown))}, `
    + `profit factor ≥ ${protocol.min_profit_factor}. NO_TRADE horizon ${protocol.no_trade_horizon_days} days.`));

  heading(document, parent, "My trades (net of fees)");
  fact(document, parent, "Closed trades counted", `${trades.counted} of ${protocol.min_trades} required`);
  fact(document, parent, "Win rate", percent(trades.win_rate), trades.win_rate);
  fact(document, parent, "Expectancy per trade", percent(trades.expectancy), trades.expectancy);
  fact(document, parent, "Profit factor", plain(trades.profit_factor), trades.profit_factor);
  fact(document, parent, "Total return (compounded)", percent(trades.total_return), trades.total_return);
  fact(document, parent, "Max drawdown", percent(trades.max_drawdown), trades.max_drawdown);
  fact(document, parent, "Net result", trades.net_result_usdt === null ? "unavailable" : `${plain(trades.net_result_usdt)} USDT`, trades.net_result_usdt);
  fact(document, parent, "Bootstrap 5% lower bound", percent(trades.bootstrap_lower_bound ?? null), trades.bootstrap_lower_bound);
  const list = el(document, "ul");
  for (const item of trades.items) {
    const row = el(document, "li",
      `${item.instrument_id} · ${item.first_fill_at} · net ${percent(item.net_return)} (${plain(item.net_result_usdt)} USDT, ${item.net_result_basis})`
      + (item.decision_recorded_before_first_fill ? " · decision recorded before entry" : " · no prior decision"));
    row.title = `Exact net return: ${item.net_return}`;
    list.append(row);
  }
  if (!trades.items.length) list.append(el(document, "li", "No closed trades with a known net result are recorded yet."));
  parent.append(list);
  for (const item of trades.excluded) {
    parent.append(el(document, "p", `Excluded ${item.outcome_id}: ${item.reason}`));
  }

  heading(document, parent, "Baselines");
  fact(document, parent, "Cash", percent(baselines.CASH.total_return), baselines.CASH.total_return);
  const hold = baselines.BUY_AND_HOLD;
  fact(document, parent, "Buy-and-hold",
    hold.status === "AVAILABLE" ? `${percent(hold.total_return)} (${hold.basis})` : `UNAVAILABLE — ${hold.reason}`,
    hold.total_return);
  for (const coin of hold.coins ?? []) {
    parent.append(el(document, "p", `${coin.instrument_id} ${coin.start} → ${coin.end}: `
      + (coin.status === "AVAILABLE" ? percent(coin.hold_return) : `UNAVAILABLE — ${coin.reason}`)));
  }
  if (hold.status === "AVAILABLE" && trades.total_return !== null) {
    const better = Number(trades.total_return) > Number(hold.total_return);
    parent.append(el(document, "p", `My trades ${better ? "beat" : "did not beat"} buy-and-hold over the same coins and windows.`));
  }

  heading(document, parent, `NO_TRADE decisions (${noTrade.horizon_days}-day horizon)`);
  if (noTrade.status === "AVAILABLE") {
    fact(document, parent, "Evaluated", `${noTrade.evaluated} of ${noTrade.decisions}`);
    fact(document, parent, "Standing aside was better", `${noTrade.standing_aside_better} of ${noTrade.evaluated}`);
    fact(document, parent, "Average buy-and-hold over the horizon", percent(noTrade.average_hold_return), noTrade.average_hold_return);
  } else {
    parent.append(el(document, "p", noTrade.reason
      ? `UNAVAILABLE — ${noTrade.reason}`
      : `No NO_TRADE decision has completed its horizon yet (${noTrade.decisions ?? 0} recorded).`));
  }
  const decisions = el(document, "ul");
  for (const item of noTrade.items ?? []) {
    const text = item.status === "AVAILABLE"
      ? `${item.instrument_id} · ${item.declared_at}: hold ${percent(item.hold_return)} — standing aside ${item.standing_aside_better ? "was better" : "was worse"}`
      : `${item.instrument_id ?? "no instrument"} · ${item.declared_at}: ${item.status}${item.reason ? ` — ${item.reason}` : ` until ${item.horizon_end}`}`;
    decisions.append(el(document, "li", text));
  }
  parent.append(decisions);
  parent.append(el(document, "p",
    "Your results are scored separately from strategy evidence. Trade facts are your own declarations (not verified); this view authorizes nothing."));
}

export async function bootstrapResults({ document, fetcher = globalThis.fetch }) {
  const status = document.getElementById("results-status");
  const body = document.getElementById("results-body");
  status.textContent = "Scoring your recorded trades and decisions…";
  try {
    renderOwnerResults(document, body, await readOwnerScore(fetcher));
    status.textContent = "Scored by the local research API.";
  } catch (error) {
    body.replaceChildren();
    status.textContent = error.message;
  }
}

if (typeof document !== "undefined") {
  document.addEventListener("DOMContentLoaded", () => {
    void bootstrapResults({ document });
  }, { once: true });
}
