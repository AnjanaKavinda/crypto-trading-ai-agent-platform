// Compact controls for the existing SVG renderer. No fetching or calculations.
import { CHART_STYLES } from "./chart-display.mjs";
import { TOOLBAR_PILLS } from "./indicator-toolbar.mjs";
import { shownIndicators, defaultPreferences } from "./workspace-state.mjs";

export function mountChartToolbar({ document, state, update, select, availability, signals }) {
  const $ = (id) => document.getElementById(id);
  const node = (tag, text, className) => {
    const el = document.createElement(tag);
    if (text !== undefined) el.textContent = text;
    if (className) el.className = className;
    return el;
  };
  const button = (text, label, action, key) => {
    const el = node("button", text);
    el.type = "button";
    if (label) el.setAttribute("aria-label", label);
    if (key) el.dataset.control = key;
    el.addEventListener("click", action);
    return el;
  };
  const menus = [];
  const menu = (id, label, parent) => {
    const el = node("details", undefined, "chart-menu");
    el.id = id;
    const summary = node("summary", label);
    const panel = node("div", undefined, "chart-menu-panel");
    panel.setAttribute("role", "group");
    panel.setAttribute("aria-label", label);
    el.append(summary, panel);
    parent.append(el);
    el.addEventListener("toggle", () => {
      if (el.open) for (const other of menus) if (other !== el) other.open = false;
    });
    menus.push(el);
    return { el, summary, panel };
  };
  const favorite = (field, id, label) => {
    const on = state().preferences[field].includes(id);
    const star = button(on ? "★" : "☆", `Favorite ${label}`, () => {
      const preferences = state().preferences;
      const current = preferences[field];
      update({ ...preferences, [field]: on ? current.filter((value) => value !== id) : [...current, id] }, false);
    }, `favorite-${field}-${id}`);
    star.className = "favorite-star";
    star.setAttribute("aria-pressed", String(on));
    return star;
  };
  const market = $("chart-market");
  market.addEventListener("change", () => select({ instrumentId: market.value }));
  $("pro-signals").addEventListener("click", () => signals(!state().preferences.signals));
  const timeframe = menu("timeframe-menu", "Timeframe", $("timeframe-pills"));
  const timeframeShortcuts = node("span", undefined, "toolbar-shortcuts");
  $("timeframe-pills").append(timeframeShortcuts);
  const styles = menu("chart-type-menu", "Candlesticks", $("chart-style-control"));
  const styleShortcuts = node("span", undefined, "toolbar-shortcuts");
  $("chart-style-control").append(styleShortcuts);
  const tools = menu("order-flow-menu", "Order-flow Tools · 0", $("chart-menu-controls"));
  const indicators = menu("indicators-menu", "Indicators", $("chart-menu-controls"));
  indicators.panel.classList.add("study-picker");
  const search = node("input");
  search.type = "search";
  search.placeholder = "Search indicators";
  search.setAttribute("aria-label", "Search indicators");
  const filters = node("div", undefined, "study-filters");
  const studyRows = node("div", undefined, "study-rows");
  const count = node("p", undefined, "card-note");
  indicators.panel.append(search, filters, studyRows, count, button("Reset display", null, () => update(defaultPreferences())));
  let category = "All";
  const categories = ["All", "Active", "Trend", "Momentum", "Volatility", "Volume", "Order flow"];
  const catalog = TOOLBAR_PILLS.filter((pill) => ["indicator", "overlay", "fixed"].includes(pill.kind));
  const group = (pill) => pill.id === "vwap" ? "Order flow" : ({ trend: "Trend", momentum: "Momentum", volatility: "Volatility", volume: "Volume" })[pill.group];
  const on = (id, prefs) => id === "volume" ? prefs.volume : shownIndicators(prefs).includes(id);
  const toggleStudy = (id) => {
    const preferences = state().preferences;
    if (id === "volume") return update({ ...preferences, volume: !preferences.volume });
    const visible = new Set(preferences.visible);
    if (visible.has(id)) visible.delete(id); else visible.add(id);
    update({ ...preferences, visible: [...visible] });
  };
  const settings = (id, label) => {
    const details = node("details", undefined, "study-settings");
    details.append(node("summary", `Settings for ${label}`));
    const setting = node("label", "Line width ");
    const input = node("select");
    input.setAttribute("aria-label", `${label} line width`);
    input.dataset.control = `width-${id}`;
    for (const value of [1, 2, 3]) {
      const option = node("option", `${value} px`);
      option.value = String(value);
      input.append(option);
    }
    input.value = String(state().preferences.studyWidths[id] ?? 2);
    input.addEventListener("change", () => {
      const preferences = state().preferences;
      update({ ...preferences, studyWidths: { ...preferences.studyWidths, [id]: Number(input.value) } });
    });
    setting.append(input);
    details.append(setting, node("p", "Display only. Backend method and periods remain fixed.", "card-note"));
    return details;
  };
  const row = (pill, orderFlow = false) => {
    const id = pill.id ?? "volume";
    const { snapshot, preferences } = state();
    const ready = id === "vwap" && preferences.mode !== "pro" ? { available: false, reason: "Switch to Pro to display the VWAP approximation." }
      : snapshot ? availability(pill.kind === "overlay" ? "analysis" : "indicator", id) : { available: false, reason: "Load a snapshot first." };
    const available = id === "volume" ? Boolean(snapshot) : ready.available;
    const active = available && on(id, preferences);
    const el = node("div", undefined, "study-row");
    el.dataset.study = id;
    if (orderFlow) el.append(favorite("favoriteTools", id, pill.label));
    const text = node("div");
    text.append(node("strong", pill.label), node("p", pill.hint, "card-note"));
    const pane = pill.kind === "overlay" || ["ema-20", "ema-50", "ema-500", "bollinger-bands-20"].includes(id) ? "Price overlay" : "Lower pane";
    text.append(node("small", available ? `${pane} · ${active ? "On" : "Off"}` : `Unavailable: ${ready.reason ?? "No candle data"}`));
    el.append(text);
    const toggle = button(active ? "ON" : "ADD", `${active ? "Remove" : "Add"} ${pill.label}`, () => toggleStudy(id), `toggle-${orderFlow ? "flow" : "study"}-${id}`);
    toggle.disabled = !available;
    toggle.setAttribute("aria-pressed", String(active));
    el.append(toggle);
    if (available && id !== "volume") el.append(settings(id, pill.label));
    return el;
  };
  const refreshStudies = () => {
    const { preferences, snapshot } = state();
    const active = catalog.filter((pill) => on(pill.id ?? "volume", preferences));
    filters.replaceChildren();
    for (const name of categories) {
      const filter = button(name, null, () => { category = name; refreshStudies(); }, `filter-${name}`);
      filter.setAttribute("aria-pressed", String(name === category));
      filters.append(filter);
    }
    studyRows.replaceChildren();
    const query = search.value.trim().toLowerCase();
    const matches = catalog.filter((pill) => (category === "All" || category === "Active" && active.includes(pill) || group(pill) === category) &&
      `${pill.label} ${pill.hint}`.toLowerCase().includes(query));
    for (const pill of matches) studyRows.append(row(pill));
    if (!matches.length) studyRows.append(node("p", "No matching studies.", "card-note"));
    const rendered = active.filter((pill) => (pill.id ? availability(pill.kind === "overlay" ? "analysis" : "indicator", pill.id).available : Boolean(snapshot)));
    count.textContent = `${rendered.length} active · ${active.length - rendered.length} selected but unavailable`;
    $("active-study-summary").textContent = rendered.length ? `Active: ${rendered.map((pill) => pill.short).join(" · ")}` : "No active studies";
    indicators.summary.textContent = `Indicators · ${rendered.length}`;
  };
  search.addEventListener("input", refreshStudies);
  const overflow = $("chart-overflow");
  const narrow = matchMedia("(max-width: 1050px)");
  const adapt = () => { overflow.open = !narrow.matches; };
  narrow.addEventListener("change", adapt);
  adapt();
  document.addEventListener("pointerdown", (event) => {
    for (const el of menus) if (el.open && !el.contains(event.target)) el.open = false;
    if (narrow.matches && overflow.open && !overflow.contains(event.target)) overflow.open = false;
  });
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    const opened = menus.find((el) => el.open) ?? (narrow.matches && overflow.open ? overflow : null);
    if (!opened) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    opened.open = false;
    opened.querySelector("summary").focus();
  }, true);
  return () => {
    const { preferences, selected, symbols } = state();
    const focused = document.activeElement?.dataset.control;
    const expandedSettings = [...document.querySelectorAll(".study-settings[open]")].map((el) => el.closest("[data-study]").dataset.study);
    market.replaceChildren(...symbols.map((symbol) => {
      const option = node("option", `${symbol.symbol} · Spot`);
      option.value = symbol.instrument_id;
      return option;
    }));
    market.disabled = !symbols.length;
    market.value = selected.instrumentId ?? "";
    timeframe.summary.textContent = `Timeframe · ${selected.timeframe === "1d" ? "1D" : selected.timeframe ?? "—"}`;
    timeframe.panel.replaceChildren(node("p", "Stored Spot candles", "menu-section"));
    timeframeShortcuts.replaceChildren();
    for (const [id, label] of [["1h", "1 hour"], ["4h", "4 hours"], ["1d", "1 day"]]) {
      const line = node("div", undefined, "menu-choice");
      const choose = (short = false) => {
        const el = button(short ? id === "1d" ? "1D" : id : label, null, () => { select({ timeframe: id }); timeframe.el.open = false; }, `interval-${short ? "shortcut" : "menu"}-${id}`);
        if (short) el.dataset.timeframe = id;
        el.setAttribute("aria-pressed", String(id === selected.timeframe));
        return el;
      };
      line.append(choose(), favorite("favoriteTimeframes", id, label));
      timeframe.panel.append(line);
      if (preferences.favoriteTimeframes.includes(id)) timeframeShortcuts.append(choose(true));
    }
    styles.summary.textContent = CHART_STYLES.find((style) => style.id === preferences.chartStyle).label;
    styles.panel.replaceChildren();
    styleShortcuts.replaceChildren();
    let currentGroup;
    for (const style of CHART_STYLES) {
      if (style.group !== currentGroup) styles.panel.append(node("p", currentGroup = style.group, "menu-section"));
      const choose = (short = false) => {
        const el = button(style.label, null, () => { update({ ...state().preferences, chartStyle: style.id }); styles.el.open = false; }, `style-${short ? "shortcut" : "menu"}-${style.id}`);
        el.setAttribute("aria-pressed", String(style.id === preferences.chartStyle));
        return el;
      };
      const line = node("div", undefined, "menu-choice");
      line.append(choose(), favorite("favoriteStyles", style.id, style.label));
      styles.panel.append(line);
      if (preferences.favoriteStyles.includes(style.id)) styleShortcuts.append(choose(true));
    }
    styles.panel.append(node("p", "Volume candles, Footprint, Heikin Ashi, Renko and Range are not implemented.", "card-note"));
    tools.panel.replaceChildren();
    const vwap = catalog.find((pill) => pill.id === "vwap");
    if (preferences.favoriteTools.includes("vwap")) tools.panel.append(node("p", "Favorites", "menu-section"), row(vwap, true));
    else tools.panel.append(node("p", "Supported tools", "menu-section"), row(vwap, true));
    tools.panel.append(node("p", "CVD, tape, footprint, trade bubbles and imbalance are not implemented in this chart and require verified trade-side history. DOM and heatmap require recorded order-book updates; liquidation tools require liquidation data. Candle volume profile is available as a proxy in Details → Volume and candle structure.", "card-note"));
    tools.summary.textContent = `Order-flow Tools · ${on("vwap", preferences) && availability("analysis", "vwap").available ? 1 : 0}`;
    refreshStudies();
    for (const el of document.querySelectorAll(".study-settings")) if (expandedSettings.includes(el.closest("[data-study]").dataset.study)) el.open = true;
    if (focused) [...document.querySelectorAll("[data-control]")].find((el) => el.dataset.control === focused)?.focus({ preventScroll: true });
    $("pro-signals").hidden = preferences.mode !== "pro";
    indicators.el.hidden = preferences.mode !== "pro";
    $("pro-signals").setAttribute("aria-pressed", String(preferences.signals));
  };
}
