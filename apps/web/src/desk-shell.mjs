// One-page Trading desk (UR1): header status, tabs Today · Charts · Strategy
// lab · My results. Each tab mounts the first time it is shown, so its
// read-only API calls only run when needed. No refresh, polling or writes here.
import { adjacentTab, DESK_TABS, summariseFreshness, tabFromHash, timeframeLabel } from "./desk-state.mjs";
import { createDesk } from "./desk-data.mjs";

const $ = (selector) => document.querySelector(selector);

// The query string is a deep link for exactly one tab (an evidence package or
// an exact record); the other tabs never see it.
const DEEP_LINK_TABS = new Set(["strategy-lab", "my-results"]);

async function mountTab(id, desk, initialTab, search) {
  const linked = id === initialTab ? search : "";
  if (id === "today") {
    const { mountToday } = await import("./today.mjs");
    await mountToday({ document, desk, fetcher: globalThis.fetch, selectTab });
  } else if (id === "charts") {
    const { mountCharts } = await import("./app.mjs");
    await mountCharts({ desk });
  } else if (id === "strategy-lab") {
    const [{ bootstrapEvidence }, { renderVerdictCards }] = await Promise.all([
      import("./evidence-page.mjs"), import("./today.mjs"),
    ]);
    renderVerdictCards(document, $("#lab-verdicts"));
    await bootstrapEvidence({ document, search: DEEP_LINK_TABS.has(id) ? linked : "" });
  } else if (id === "my-results") {
    const [{ bootstrapBoard }, { bootstrapResults }] = await Promise.all([
      import("./signal-board.mjs"), import("./owner-results.mjs"),
    ]);
    await Promise.all([
      bootstrapResults({ document }),
      bootstrapBoard({ document, search: DEEP_LINK_TABS.has(id) ? linked : "" }),
    ]);
  }
}

let selectTab = () => {};

async function showFreshness(desk) {
  const status = $("#desk-freshness");
  const selection = await desk.selection();
  const timeframe = selection.timeframe;
  try {
    const summary = summariseFreshness(await desk.watchlist(timeframe), timeframe);
    if (desk.current()?.timeframe !== timeframe) return;
    status.textContent = summary.text;
    status.title = summary.title;
    status.dataset.state = summary.state;
  } catch (error) {
    status.textContent = `Data: unavailable · ${timeframeLabel(timeframe)}`;
    status.title = error.message;
    status.dataset.state = "error";
  }
}

function init() {
  const search = location.search;
  const initialTab = tabFromHash(location.hash);
  const desk = createDesk({ fetcher: globalThis.fetch, storage: globalThis.localStorage, search });
  const mounted = new Map();
  selectTab = (id, { focus = false, updateHash = true } = {}) => {
    for (const tab of DESK_TABS) {
      const button = $(`#tab-${tab.id}`);
      const panel = $(`#panel-${tab.id}`);
      const selected = tab.id === id;
      button.setAttribute("aria-selected", String(selected));
      button.tabIndex = selected ? 0 : -1;
      panel.hidden = !selected;
      if (selected && focus) button.focus();
    }
    document.body.dataset.tab = id;
    if (!mounted.has(id)) {
      mounted.set(id, mountTab(id, desk, initialTab, search).catch((error) => {
        mounted.delete(id);
        const panel = $(`#panel-${id}`);
        panel.prepend(Object.assign(document.createElement("p"), {
          className: "error-text", role: "alert", textContent: `This tab could not start: ${error.message}`,
        }));
      }));
    }
    if (updateHash && location.hash !== `#${id}`) history.replaceState(null, "", `${location.pathname}${location.search}#${id}`);
    document.dispatchEvent(new CustomEvent("desk:tab", { detail: { id } }));
  };
  for (const tab of DESK_TABS) {
    $(`#tab-${tab.id}`).addEventListener("click", () => selectTab(tab.id));
  }
  $("#desk-tabs").addEventListener("keydown", (event) => {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const current = DESK_TABS.find((tab) => $(`#tab-${tab.id}`).getAttribute("aria-selected") === "true");
    selectTab(adjacentTab(current?.id, event.key), { focus: true });
  });
  window.addEventListener("hashchange", () => selectTab(tabFromHash(location.hash), { updateHash: false }));
  desk.onChange(() => { void showFreshness(desk); });
  selectTab(initialTab, { updateHash: false });
  void showFreshness(desk);
}

if (typeof document !== "undefined") {
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init, { once: true });
  else init();
}
