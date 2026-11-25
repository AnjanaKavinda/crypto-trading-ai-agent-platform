import {
  adjacentTab,
  DESK_TABS,
  FRESHNESS_TIMEFRAME,
  summariseFreshness,
  tabFromHash,
} from "./desk-state.mjs";
import { loadWatchlist } from "./watchlist-state.mjs";

const $ = (selector) => document.querySelector(selector);

function fitFrame(frame) {
  // Same-origin pages only; the frame grows with its content so the desk has
  // one scroll area. Cross-origin content is never embedded.
  try {
    const doc = frame.contentDocument;
    if (!doc?.documentElement) return;
    const resize = () => {
      frame.style.height = `${Math.max(480, doc.documentElement.scrollHeight)}px`;
    };
    resize();
    new ResizeObserver(resize).observe(doc.documentElement);
  } catch {
    frame.style.height = "80vh";
  }
}

function selectTab(id, { focus = false, updateHash = true } = {}) {
  for (const tab of DESK_TABS) {
    const button = $(`#tab-${tab.id}`);
    const panel = $(`#panel-${tab.id}`);
    const selected = tab.id === id;
    button.setAttribute("aria-selected", String(selected));
    button.tabIndex = selected ? 0 : -1;
    panel.hidden = !selected;
    if (selected && !panel.querySelector("iframe")) {
      // Lazy: a tab's page (and its read-only API calls) loads on first view.
      const frame = document.createElement("iframe");
      frame.src = tab.page;
      frame.title = tab.title;
      frame.className = "desk-frame";
      frame.addEventListener("load", () => fitFrame(frame));
      panel.append(frame);
    }
    if (selected && focus) button.focus();
  }
  if (updateHash && location.hash !== `#${id}`) history.replaceState(null, "", `#${id}`);
}

async function showFreshness() {
  const status = $("#desk-freshness");
  try {
    const summary = summariseFreshness(await loadWatchlist(globalThis.fetch, FRESHNESS_TIMEFRAME));
    status.textContent = summary.text;
    status.dataset.state = summary.state;
  } catch (error) {
    status.textContent = `Data freshness (${FRESHNESS_TIMEFRAME}): unavailable — ${error.message}`;
    status.dataset.state = "error";
  }
}

function init() {
  const list = $("#desk-tabs");
  for (const tab of DESK_TABS) {
    const button = document.createElement("button");
    button.type = "button";
    button.id = `tab-${tab.id}`;
    button.setAttribute("role", "tab");
    button.setAttribute("aria-controls", `panel-${tab.id}`);
    button.textContent = tab.label;
    button.addEventListener("click", () => selectTab(tab.id));
    list.append(button);
    const panel = document.createElement("section");
    panel.id = `panel-${tab.id}`;
    panel.setAttribute("role", "tabpanel");
    panel.setAttribute("aria-labelledby", `tab-${tab.id}`);
    panel.className = "desk-panel";
    panel.hidden = true;
    $("#desk-panels").append(panel);
  }
  list.addEventListener("keydown", (event) => {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const current = DESK_TABS.find((tab) => $(`#tab-${tab.id}`).getAttribute("aria-selected") === "true");
    selectTab(adjacentTab(current?.id, event.key), { focus: true });
  });
  window.addEventListener("hashchange", () => selectTab(tabFromHash(location.hash), { updateHash: false }));
  selectTab(tabFromHash(location.hash), { updateHash: false });
  showFreshness();
}

init();
