// Signal Center (U5c): one card per approved coin on the Today tab. State comes
// only from the forward-stage API; there is never an order button. Failed
// strategies appear only in Pro view, with their FAIL banner.
import { readForwardStage } from "./forward-api.mjs";
import { loadPreferences } from "./workspace-state.mjs";
import { displayDecimals, formatDisplayNumber } from "./chart-interaction.mjs";
import { reasonText } from "./strategy-studies.mjs";
import { parseVerdictReason } from "./forward-verdicts.mjs";
import {
  coinSignal, FORWARD_CANDIDATES, forwardRecordError, GLOSSARY, percentText, positionSize,
  stageText, strategyName, WHAT_COULD_GO_WRONG,
} from "./signal-center-state.mjs";

const SEEN_KEY = "spot-research.signal-seen.v1";

const element = (document, tag, text, className) => {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
};

// A glossary term: focusable, with its plain explanation on hover and for screen readers.
function term(document, name, shown = name) {
  const node = element(document, "dfn", shown, "term");
  node.tabIndex = 0;
  node.title = GLOSSARY[name];
  node.setAttribute("aria-label", `${shown}: ${GLOSSARY[name]}`);
  return node;
}

function line(document, ...parts) {
  const node = element(document, "p", undefined, "signal-line");
  for (const part of parts) node.append(typeof part === "string" ? document.createTextNode(part) : part);
  return node;
}

function readSeen(storage) {
  try {
    const saved = JSON.parse(storage?.getItem(SEEN_KEY));
    return new Set(Array.isArray(saved) ? saved.filter((key) => typeof key === "string") : []);
  } catch {
    return new Set();
  }
}

function writeSeen(storage, keys) {
  try {
    storage?.setItem(SEEN_KEY, JSON.stringify([...keys].slice(-500)));
  } catch {
    // Browser storage is only a convenience here.
  }
}

const signalKey = (candidate, symbol, signal) =>
  `${candidate.strategy}@${candidate.version}|${symbol}|${signal.signal_candle_open_time}`;

function sizingInputs(document) {
  return {
    account: document.querySelector("#signal-account")?.value ?? "",
    riskPct: document.querySelector("#signal-risk")?.value ?? "1",
  };
}

function renderRecord(document, record, verdict) {
  const box = element(document, "div", undefined, "signal-record");
  const historical = element(document, "section");
  historical.append(element(document, "h4", "Historical study"));
  if (verdict) {
    historical.append(
      line(document, `Verdict ${verdict.verdict_status} (${verdict.protocol_id} v${verdict.protocol_version}, report ${String(verdict.report_created_at ?? "").slice(0, 10)}).`),
      line(document, term(document, "Max drawdown"), ` (development era, portfolio): ${percentText(verdict.development_max_drawdown)}.`),
    );
    const reasons = element(document, "ul");
    for (const reason of verdict.verdict_reasons ?? []) reasons.append(element(document, "li", reasonText(parseVerdictReason(reason))));
    historical.append(reasons);
  } else {
    historical.append(line(document, "No historical verdict is recorded for this strategy."));
  }
  const forward = element(document, "section");
  const stats = record.forward ?? {};
  forward.append(
    element(document, "h4", "Forward test (simulated)"),
    line(document, `Since ${String(record.protocol?.prospective_start ?? "").slice(0, 10)}: ${stats.closed_trades ?? 0} closed trades · `,
      term(document, "Win rate"), ` ${percentText(stats.win_rate)} · `, term(document, "Expectancy"), ` ${percentText(stats.expectancy)} · `,
      term(document, "Max drawdown"), ` ${percentText(stats.max_drawdown)}.`),
    line(document, term(document, "Review point"), `: ${stats.review_point?.trades ?? "—"} trades or ${String(stats.review_point?.date ?? "—").slice(0, 10)}${stats.review_point?.reached ? " (reached)" : ""}.`),
    line(document, "Average win/loss and worst losing streak: not served by the API."),
  );
  box.append(historical, forward);
  return box;
}

function renderCard(document, card, { isNew, storageInputs }) {
  const item = element(document, "li");
  const article = element(document, "article", undefined, "signal-card");
  article.dataset.state = card.state;
  article.dataset.symbol = card.symbol;
  article.tabIndex = 0;
  const headingId = `signal-${card.symbol}`;
  const head = element(document, "div", undefined, "signal-card-head");
  const heading = element(document, "h3", card.symbol.replace(/USDT$/, ""));
  heading.id = headingId;
  const state = element(document, "span", `${card.mark} ${card.title}`, "signal-state");
  head.append(heading, state);
  if (isNew) head.append(element(document, "span", "New signal", "state-chip"));
  article.setAttribute("aria-labelledby", headingId);
  article.setAttribute("aria-label", `${card.symbol}: ${card.title}. ${card.reasons.join(" ")}`);
  const reasons = element(document, "ul", undefined, "signal-reasons");
  for (const reason of card.reasons) reasons.append(element(document, "li", reason));
  const todo = element(document, "section", undefined, "signal-todo");
  todo.append(element(document, "h4", "What to do"));
  if (card.state === "red") {
    todo.append(line(document, "Stay out. There is nothing to buy or sell here — research only."));
  } else {
    const entry = card.signal?.simulated_entry_fill?.value;
    const stop = card.signal?.simulated_initial_stop?.value;
    const decimals = displayDecimals(entry);
    todo.append(line(document, card.state === "yellow" ? "Paper only: follow the simulated trade; do not use real money. " : "Research signal — any real trade is your own decision outside this tool. ",
      `Entry ~${entry ? formatDisplayNumber(entry, decimals) : "next open"} · `, term(document, "Stop"), ` ~${stop ? formatDisplayNumber(stop, decimals) : "—"} · exit as pre-registered for ${strategyName(card.candidate)}.`));
    const size = positionSize({ ...storageInputs, entry, stop });
    todo.append(line(document, term(document, "Position size"), size.ok
      ? `: ${size.quantity} ${card.symbol.replace(/USDT$/, "")} (risking ${size.riskAmount} USDT${size.capped ? ", capped at what the account can buy" : ""}).`
      : `: ${size.reason}`));
  }
  if (card.state === "red") {
    todo.append(line(document, term(document, "Position size"), ": none — there is no signal."));
  }
  const risks = element(document, "details", undefined, "signal-risks");
  risks.append(element(document, "summary", "What could go wrong"));
  const riskList = element(document, "ul");
  for (const risk of WHAT_COULD_GO_WRONG[card.state]) riskList.append(element(document, "li", risk));
  risks.append(riskList);
  article.append(head, reasons, todo);
  if (card.record) article.append(renderRecord(document, card.record, card.record.historical_verdict));
  article.append(risks);
  item.append(article);
  return item;
}

function renderFailed(document, target, stages, mode) {
  target.replaceChildren();
  const failed = stages.filter((item) => item.record?.stage === "FAIL");
  if (!failed.length) return;
  if (mode !== "pro") {
    target.append(element(document, "p", `${failed.length} failed ${failed.length === 1 ? "strategy is" : "strategies are"} hidden in Beginner view. Switch to Pro (Charts tab) to see them with their FAIL banner.`, "card-note"));
    return;
  }
  target.append(element(document, "h3", "Failed strategies (Pro view)", "subhead"));
  for (const item of failed) {
    const block = element(document, "article", undefined, "failed-strategy");
    block.tabIndex = 0;
    block.setAttribute("aria-label", `${strategyName(item.candidate)}: FAILED`);
    const banner = element(document, "div", undefined, "verdict-banner");
    banner.dataset.tone = "fail";
    banner.setAttribute("role", "note");
    banner.append(element(document, "strong", `${strategyName(item.candidate)} — FAILED: it ${stageText(item.record)}. Never a trade signal.`));
    block.append(banner, renderRecord(document, item.record, item.record.historical_verdict));
    target.append(block);
  }
}

export async function mountSignalCenter({ document, desk, fetcher = globalThis.fetch, storage = globalThis.localStorage }) {
  const status = document.querySelector("#signal-status");
  const list = document.querySelector("#signal-cards");
  const failedTarget = document.querySelector("#signal-failed");
  if (!status || !list) return;
  let stages = null;
  let symbols = [];

  const render = () => {
    if (!stages) return;
    const mode = loadPreferences(storage).mode;
    const seen = readSeen(storage);
    const inputs = sizingInputs(document);
    const cards = symbols.map((item) => coinSignal(item.symbol, stages, mode));
    const liveKeys = cards.filter((card) => card.signal).map((card) => signalKey(card.candidate, card.symbol, card.signal));
    const fresh = new Set(liveKeys.filter((key) => !seen.has(key)));
    list.replaceChildren(...cards.map((card) => renderCard(document, card, {
      isNew: Boolean(card.signal) && fresh.has(signalKey(card.candidate, card.symbol, card.signal)),
      storageInputs: inputs,
    })));
    renderFailed(document, failedTarget, stages, mode);
    // In-app alert: a badge on the Today tab while new signals are unseen.
    const tab = document.querySelector("#tab-today");
    const todayVisible = !document.querySelector("#panel-today")?.hidden;
    tab?.querySelector(".tab-badge")?.remove();
    if (fresh.size && !todayVisible && tab) {
      tab.append(element(document, "span", `${fresh.size} new`, "tab-badge"));
    } else if (fresh.size) {
      writeSeen(storage, new Set([...seen, ...fresh]));
    }
    const red = cards.filter((card) => card.state === "red").length;
    status.textContent = `${cards.length} coins · ${red} with no signal. State from the forward-stage API only; simulated research evidence, never an order.`;
    status.dataset.state = stages.some((item) => item.error) ? "warning" : "valid";
  };

  const load = async () => {
    status.textContent = "Reading forward records (this can take about half a minute)…";
    status.dataset.state = "pending";
    try {
      symbols = await desk.symbols();
    } catch (error) {
      list.replaceChildren();
      status.textContent = `Signal Center unavailable — ${error.message} Every coin stays at no signal.`;
      status.dataset.state = "error";
      return;
    }
    stages = await Promise.all(FORWARD_CANDIDATES.map(async (candidate) => {
      try {
        const record = await readForwardStage(fetcher, candidate.strategy, candidate.version);
        const invalid = forwardRecordError(record, candidate);
        return invalid ? { candidate, record: null, error: invalid } : { candidate, record, error: null };
      } catch (error) {
        return { candidate, record: null, error: error.message };
      }
    }));
    render();
  };

  document.querySelector("#signal-sizing")?.addEventListener("input", render);
  document.querySelector("#signal-sizing")?.addEventListener("submit", (event) => event.preventDefault());
  document.querySelector("#signal-reload")?.addEventListener("click", () => { void load(); });
  document.addEventListener("desk:preferences", render);
  document.addEventListener("desk:tab", (event) => { if (event.detail?.id === "today") render(); });
  await load();
}
