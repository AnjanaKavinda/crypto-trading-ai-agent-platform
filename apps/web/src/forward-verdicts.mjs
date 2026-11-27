// Strategy lab (U7): imported study verdicts from GET /api/research/forward/verdicts
// (C-109 records). Shows only what the API serves; anything it does not serve
// (full criteria table, equity curve) is stated as not available.
import { readForwardVerdicts } from "./forward-api.mjs";
import { reasonText, STRATEGY_STUDIES } from "./strategy-studies.mjs";
import { percentText } from "./signal-center-state.mjs";

const REASON = /^([A-Z][A-Z0-9_]{2,63})(?::\s*(.+))?$/;
const COIN = /^([A-Z0-9]{2,15}USDT)\s+(.+)$/;

// "SYMBOL_DRAWDOWN_LIMIT_EXCEEDED: BNBUSDT 41.26%" -> { code, detail, symbol, figure }
export function parseVerdictReason(text) {
  const match = REASON.exec(String(text ?? "").trim());
  if (!match) return { code: String(text ?? ""), detail: null, symbol: null, figure: null };
  const detail = match[2] ?? null;
  const coin = detail ? COIN.exec(detail) : null;
  return { code: match[1], detail, symbol: coin?.[1] ?? null, figure: coin?.[2] ?? null };
}

export function verdictError(item) {
  if (!item || item.contract_id !== "C-109") return "Not a study verdict record.";
  if (["qualification_authorized", "approval_authorized", "execution_authorized"].some((key) => item[key] !== false)) {
    return "The verdict claims an authority it must not have.";
  }
  if (typeof item.strategy_id !== "string" || typeof item.strategy_version !== "string" ||
      typeof item.verdict_status !== "string" || !Array.isArray(item.verdict_reasons) || !Array.isArray(item.datasets)) {
    return "The verdict record is not in the expected form.";
  }
  return null;
}

const COIN_FIGURE = Object.freeze({
  SYMBOL_DRAWDOWN_LIMIT_EXCEEDED: (figure) => `Max drawdown ${figure} (coin limit 40%)`,
});

// One row per coin dataset, with the figures the reasons give for that coin.
export function perCoinRows(item) {
  const reasons = item.verdict_reasons.map(parseVerdictReason);
  return item.datasets.map((dataset) => ({
    symbol: dataset.symbol,
    timeframe: dataset.timeframe,
    dataset: String(dataset.content_sha256 ?? ""),
    figures: reasons.filter((reason) => reason.symbol === dataset.symbol)
      .map((reason) => COIN_FIGURE[reason.code]?.(reason.figure) ?? `${reason.code}: ${reason.figure}`),
  }));
}

// Failed criteria in plain words; criteria naming one coin are folded into one line.
export function failedCriteria(item) {
  const seen = new Map();
  for (const reason of item.verdict_reasons.map(parseVerdictReason)) {
    if (reason.symbol) {
      const entry = seen.get(reason.code) ?? { code: reason.code, coins: [] };
      entry.coins.push(`${reason.symbol.replace(/USDT$/, "")} ${reason.figure}`);
      seen.set(reason.code, entry);
    } else {
      seen.set(`${reason.code}|${reason.detail ?? ""}`, { code: reason.code, detail: reason.detail });
    }
  }
  return [...seen.values()].map((entry) => ({
    code: entry.code,
    text: reasonText({ code: entry.code, detail: entry.coins ? entry.coins.join(", ") : entry.detail ?? undefined }),
  }));
}

const element = (document, tag, text, className) => {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
};

function chip(document, text, tone) {
  const node = element(document, "span", text, "state-chip");
  node.dataset.tone = tone;
  return node;
}

export function renderImportedVerdict(document, item) {
  const card = element(document, "article", undefined, "verdict-card imported-verdict");
  card.tabIndex = 0;
  const headingId = `verdict-${String(item.verdict_id ?? item.strategy_id).replace(/[^a-z0-9-]/gi, "")}`;
  const head = element(document, "div", undefined, "verdict-card-head");
  const heading = element(document, "h3", `${item.strategy_id} · v${item.strategy_version}`);
  heading.id = headingId;
  card.setAttribute("aria-labelledby", headingId);
  head.append(heading, chip(document, `Verdict: ${item.verdict_status}`, item.verdict_status === "FAIL" ? "fail" : "neutral"));
  card.append(head, element(document, "p",
    `${item.protocol_id} v${item.protocol_version} · report ${String(item.report_created_at ?? "").slice(0, 10)} · imported ${String(item.recorded_at ?? "").slice(0, 10)}`, "card-note"));
  card.append(element(document, "p", `Development-era portfolio max drawdown: ${percentText(item.development_max_drawdown)}.`, "verdict-summary"));

  card.append(element(document, "h4", "Criteria not met"));
  const criteria = element(document, "ul", undefined, "verdict-reasons");
  for (const entry of failedCriteria(item)) {
    const row = element(document, "li", entry.text);
    row.title = entry.code;
    criteria.append(row);
  }
  card.append(criteria, element(document, "p", "The full pre-registered criteria table is not served by the API; only the criteria the study failed are listed.", "card-note"));

  card.append(element(document, "h4", "Per coin"));
  const scroll = element(document, "div", undefined, "table-scroll");
  const table = element(document, "table", undefined, "per-coin");
  const header = element(document, "tr");
  for (const label of ["Coin", "Timeframe", "Figures from the study", "Dataset sha256"]) {
    const th = element(document, "th", label);
    th.scope = "col";
    header.append(th);
  }
  const thead = element(document, "thead");
  thead.append(header);
  const body = element(document, "tbody");
  for (const row of perCoinRows(item)) {
    const tr = element(document, "tr");
    const dataset = element(document, "td", `${row.dataset.slice(0, 12)}…`);
    dataset.title = row.dataset;
    tr.append(element(document, "td", row.symbol.replace(/USDT$/, "")), element(document, "td", row.timeframe),
      element(document, "td", row.figures.length ? row.figures.join("; ") : "No coin-level figure in the reasons"), dataset);
    body.append(tr);
  }
  table.append(thead, body);
  scroll.append(table);
  card.append(scroll);

  card.append(element(document, "h4", "Equity vs buy-and-hold"));
  card.append(element(document, "p", "Not available — the verdicts API does not serve the equity curve.", "empty-state"));
  card.append(element(document, "p", "No qualification, approval or execution authority (all false in the record).", "card-note"));
  return card;
}

// The Strategy lab's verdict section: API verdicts first, then any verdict
// recorded on #516 that is not imported into the API.
export async function mountStrategyLab({ document, fetcher = globalThis.fetch, renderRecorded }) {
  const target = document.querySelector("#lab-imported");
  const status = document.querySelector("#lab-imported-status");
  const recorded = document.querySelector("#lab-verdicts");
  if (!target || !status) return;
  status.textContent = "Reading imported verdicts…";
  status.dataset.state = "pending";
  let items = [];
  try {
    items = await readForwardVerdicts(fetcher);
    const invalid = items.map(verdictError).find(Boolean);
    if (invalid) throw new Error(invalid);
    target.replaceChildren(...items.map((item) => renderImportedVerdict(document, item)));
    status.textContent = items.length
      ? `${items.length} imported verdict${items.length === 1 ? "" : "s"} from the local research API.`
      : "No verdicts are imported into the API yet.";
    status.dataset.state = "valid";
  } catch (error) {
    items = [];
    target.replaceChildren();
    status.textContent = `Imported verdicts unavailable — ${error.message} The verdicts recorded on #516 are shown below.`;
    status.dataset.state = "error";
  }
  const imported = new Set(items.map((item) => `${item.strategy_id}@${item.strategy_version}`));
  renderRecorded?.(document, recorded, STRATEGY_STUDIES.filter((study) => !imported.has(`${study.strategy}@${study.version}`)));
}
