import { PAIRS, SCENARIOS, selectFixture } from './fixtures.js';

const state = { pair: 'BTCUSDT', scenario: 'no_trade', timeframe: '5m', mode: 'Beginner', showEMA20: true, showEMA50: true, showVolume: true, selected: 40, chat: '' };
const app = document.querySelector('#app');

const svgNS = 'http://www.w3.org/2000/svg';
function svg(name, attrs = {}) {
  const node = document.createElementNS(svgNS, name);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, String(value));
  return node;
}
function el(name, className = '', content = '') {
  const node = document.createElement(name);
  node.className = className;
  node.textContent = content;
  return node;
}
function fmt(value) { return value < 1 ? value.toFixed(4) : value < 100 ? value.toFixed(2) : value.toLocaleString('en-US', { maximumFractionDigits: 2 }); }
function clock(time) { return new Date(time).toLocaleTimeString('en-US', { timeZone: 'UTC', hour: '2-digit', minute: '2-digit', hour12: false }); }

function button(label, className, callback, pressed) {
  const node = el('button', className, label);
  node.type = 'button';
  if (pressed !== undefined) node.setAttribute('aria-pressed', String(pressed));
  node.addEventListener('click', callback);
  return node;
}

function renderChart(record) {
  const wrap = el('div', 'chart-wrap');
  const chart = svg('svg', { viewBox: '0 0 960 490', role: 'img', 'aria-label': `${record.asset} synthetic fixture candlestick chart. ${record.quality} data. ${record.outcome}.`, preserveAspectRatio: 'none' });
  const valid = record.candles.filter(Boolean);
  const min = Math.min(...valid.map(c => c.low)) * 0.998;
  const max = Math.max(...valid.map(c => c.high)) * 1.002;
  const x = i => 42 + i * (830 / 47);
  const y = price => 34 + ((max - price) / (max - min)) * 320;
  const baseline = 450;

  for (let i = 0; i < 5; i += 1) {
    const value = max - (max - min) * i / 4;
    chart.append(svg('line', { x1: 38, x2: 900, y1: y(value), y2: y(value), class: 'grid-line' }));
    const label = svg('text', { x: 909, y: y(value) + 4, class: 'axis-label' });
    label.textContent = fmt(value);
    chart.append(label);
  }
  [0, 12, 24, 36, 47].forEach(i => {
    chart.append(svg('line', { x1: x(i), x2: x(i), y1: 34, y2: baseline, class: 'grid-line vertical' }));
    const label = svg('text', { x: x(i), y: 476, class: 'axis-label', 'text-anchor': 'middle' });
    label.textContent = clock(record.candles[i]?.time ?? valid[0].time + i * 300000);
    chart.append(label);
  });

  if (state.showVolume) record.candles.forEach((c, i) => {
    if (!c) return;
    const h = c.volume * 0.57;
    chart.append(svg('rect', { x: x(i) - 5, y: baseline - h, width: 10, height: h, class: c.close >= c.open ? 'volume up' : 'volume down' }));
  });
  chart.append(svg('line', { x1: 38, x2: 900, y1: 370, y2: 370, class: 'volume-divider' }));

  record.candles.forEach((c, i) => {
    if (!c) return;
    const direction = c.close >= c.open ? 'up' : 'down';
    chart.append(svg('line', { x1: x(i), x2: x(i), y1: y(c.high), y2: y(c.low), class: `wick ${direction}` }));
    chart.append(svg('rect', { x: x(i) - 5.5, y: Math.min(y(c.open), y(c.close)), width: 11, height: Math.max(2, Math.abs(y(c.open) - y(c.close))), rx: 1.5, class: `candle ${direction}` }));
  });
  for (const [field, enabled, css] of [['ema20', state.showEMA20, 'ema20'], ['ema50', state.showEMA50, 'ema50']]) {
    if (!enabled) continue;
    let points = [];
    const draw = () => { if (points.length) chart.append(svg('polyline', { points: points.join(' '), class: css })); points = []; };
    record.candles.forEach((c, i) => c ? points.push(`${x(i)},${y(c[field])}`) : draw());
    draw();
  }
  if (record.scenario === 'missing') {
    chart.append(svg('rect', { x: x(29) - 10, y: 30, width: x(33) - x(29) + 20, height: 424, class: 'missing-region' }));
    const gap = svg('text', { x: x(31), y: 90, class: 'gap-label', 'text-anchor': 'middle' }); gap.textContent = 'DATA GAP'; chart.append(gap);
  }
  const selected = Math.min(state.selected, 47);
  chart.append(svg('line', { x1: x(selected), x2: x(selected), y1: 26, y2: baseline, class: 'crosshair' }));
  chart.addEventListener('pointermove', event => {
    const rect = chart.getBoundingClientRect();
    const pixel = (event.clientX - rect.left) / rect.width * 960;
    const index = Math.max(0, Math.min(47, Math.round((pixel - 42) / (830 / 47))));
    if (index !== state.selected) { state.selected = index; updateSelection(record); }
  });
  wrap.append(chart);
  const slider = el('input', 'chart-slider');
  slider.type = 'range'; slider.min = '0'; slider.max = '47'; slider.value = String(selected);
  slider.setAttribute('aria-label', 'Inspect fixture candle');
  slider.addEventListener('input', () => { state.selected = Number(slider.value); updateSelection(record); });
  wrap.append(slider);
  return wrap;
}

function updateSelection(record) {
  const x = 42 + state.selected * (830 / 47);
  const crosshair = document.querySelector('.crosshair');
  if (crosshair) { crosshair.setAttribute('x1', String(x)); crosshair.setAttribute('x2', String(x)); }
  const slider = document.querySelector('.chart-slider');
  if (slider) slider.value = String(state.selected);
  const candle = record.candles[state.selected];
  const text = candle ? `${clock(candle.time)} UTC · O ${fmt(candle.open)} · H ${fmt(candle.high)} · L ${fmt(candle.low)} · C ${fmt(candle.close)}` : 'Unavailable · source gap';
  const selection = document.querySelector('#selection');
  if (selection) selection.textContent = text;
}

function render() {
  const record = selectFixture(state.pair, state.scenario);
  app.replaceChildren();
  const shell = el('div', 'shell');
  const header = el('header', 'topbar');
  const brand = el('div', 'brand'); brand.innerHTML = '<span class="mark">◈</span><span>ATLAS <small>/ RESEARCH</small></span>';
  header.append(brand, el('div', 'top-center', 'Spot intelligence  /  Research workspace'));
  const pill = el('div', 'preview-pill', '●  FIXTURE PREVIEW  ·  NO LIVE TRADING'); header.append(pill);
  shell.append(header);
  const main = el('main', 'layout');

  const sidebar = el('aside', 'sidebar');
  sidebar.append(el('div', 'section-eyebrow', 'WORKSPACE'), el('h2', 'sidebar-title', 'Market overview'), el('p', 'sidebar-help', 'Five synthetic Spot pairs'));
  sidebar.append(el('div', 'side-divider'));
  sidebar.append(el('div', 'section-eyebrow list-heading', 'WATCHLIST  /  USDT'));
  const list = el('nav', 'watchlist'); list.setAttribute('aria-label', 'Fixture pair selection');
  PAIRS.forEach(pair => {
    const row = button('', `pair-row ${pair.symbol === state.pair ? 'active' : ''}`, () => { state.pair = pair.symbol; state.selected = 40; render(); }, pair.symbol === state.pair);
    const left = el('span', 'pair-left'); left.append(el('strong', '', pair.symbol.replace('USDT', '')), el('small', '', pair.label));
    const right = el('span', 'pair-right'); right.append(el('strong', '', fmt(pair.base)), el('small', '', 'SYNTHETIC'));
    row.append(left, right); list.append(row);
  });
  sidebar.append(list);
  const sideFoot = el('div', 'side-foot'); sideFoot.append(el('div', 'section-eyebrow', 'MODE'), el('div', 'mode-value', '◇  Research preview'), el('p', '', 'Data and explanations are generated fixtures. No prices shown here are current market prices.')); sidebar.append(sideFoot);
  main.append(sidebar);

  const center = el('section', 'center');
  const heading = el('div', 'workspace-heading');
  const title = el('div'); title.append(el('div', 'breadcrumb', `MARKETS  /  SPOT  /  ${record.asset}`), el('h1', '', `${record.asset.replace('USDT', '')} / USDT`));
  const subtitle = el('div', 'title-sub', `${record.source}  ·  ${record.timeframe} fixture  ·  ${record.version}`); title.append(subtitle);
  heading.append(title, el('div', 'badge muted', '● RESEARCH ONLY')); center.append(heading);
  const toolbar = el('div', 'toolbar');
  const timeGroup = el('div', 'control-group');
  ['5m', '15m', '1h', '4h', '1D'].forEach(tf => timeGroup.append(button(tf, `small-btn ${tf === state.timeframe ? 'selected' : ''}`, () => { state.timeframe = tf; render(); }, tf === state.timeframe)));
  toolbar.append(timeGroup);
  const modeGroup = el('div', 'control-group modes');
  ['Beginner', 'Pro'].forEach(mode => modeGroup.append(button(mode, `small-btn ${mode === state.mode ? 'selected' : ''}`, () => { state.mode = mode; render(); }, mode === state.mode)));
  toolbar.append(modeGroup); center.append(toolbar);
  if (state.timeframe !== '5m') center.append(el('div', 'inline-warning', `${state.timeframe} view unavailable: fixture supplies only 5m candles. Select 5m to inspect the chart.`));
  const chartPanel = el('section', 'chart-panel');
  const chartHeader = el('div', 'chart-header');
  const chartNames = el('div'); chartNames.append(el('strong', '', `${record.asset} · Synthetic OHLCV`), el('span', 'muted-text', ' · 5m · example data'));
  chartHeader.append(chartNames, el('span', `quality quality-${record.quality.toLowerCase()}`, `${record.quality} INPUT`)); chartPanel.append(chartHeader);
  if (state.timeframe === '5m') chartPanel.append(renderChart(record));
  else chartPanel.append(el('div', 'chart-unavailable', 'No validated fixture at this timeframe'));
  const inspection = el('div', 'inspection'); inspection.id = 'selection'; chartPanel.append(inspection); center.append(chartPanel);
  const toggles = el('div', 'indicator-bar'); toggles.append(el('span', 'section-eyebrow', 'VISIBLE LAYERS'));
  for (const [label, field] of [['EMA 20', 'showEMA20'], ['EMA 50', 'showEMA50'], ['Volume', 'showVolume']]) toggles.append(button(label, `toggle ${state[field] ? 'on' : ''}`, () => { state[field] = !state[field]; render(); }, state[field]));
  if (state.mode === 'Pro') {
    for (const label of ['Volume profile', 'Footprint', 'Liquidity heatmap', 'CVD']) {
      const unavailable = el('span', 'unavailable-layer', `${label} · unavailable`); unavailable.title = 'Requires validated trade or historical order-book inputs'; toggles.append(unavailable);
    }
  }
  center.append(toggles);
  const bottom = el('div', 'bottom-grid');
  const evidence = el('section', 'info-card'); evidence.append(el('div', 'section-eyebrow', '01  /  RESEARCH EVIDENCE'), el('h2', '', 'What the chart can tell us'));
  evidence.append(el('p', '', 'This preview shows how source quality, time, indicator context, and contradictions will appear next to the chart. It does not evaluate a strategy.'));
  const metrics = el('div', 'metrics');
  for (const [value, label] of [['EMA 20 / 50', 'Synthetic overlay'], [fmt(record.atr), 'Fixture ATR'], [record.quality, 'Input status']]) { const m = el('div', 'metric'); m.append(el('strong', '', value), el('small', '', label)); metrics.append(m); }
  evidence.append(metrics); bottom.append(evidence);
  const sources = el('section', 'info-card'); sources.append(el('div', 'section-eyebrow', '02  /  PROVENANCE'), el('h2', '', 'Source & integrity'));
  for (const [label, value] of [['Source', record.source], ['As-of (UTC)', record.observedAt], ['Evidence version', record.version], ['Timeframe supplied', '5m only']]) { const r = el('div', 'source-row'); r.append(el('span', '', label), el('strong', '', value)); sources.append(r); }
  bottom.append(sources); center.append(bottom);
  main.append(center);

  const inspector = el('aside', 'inspector');
  inspector.append(el('div', 'section-eyebrow', 'ANALYSIS INSPECTOR'), el('h2', 'inspector-title', 'Decision context'));
  const scenarioLabel = el('label', 'scenario-label', 'Preview scenario'); const select = el('select', 'scenario-select');
  for (const [key, value] of Object.entries(SCENARIOS)) { const option = el('option', '', value.label); option.value = key; option.selected = state.scenario === key; select.append(option); }
  select.addEventListener('change', () => { state.scenario = select.value; render(); }); scenarioLabel.append(select); inspector.append(scenarioLabel);
  const outcome = el('div', 'outcome-card'); outcome.append(el('div', 'section-eyebrow', 'RESEARCH OUTCOME'), el('strong', `outcome ${record.outcome === 'NO_TRADE' ? 'abstain' : ''}`, record.outcome), el('p', '', record.reason)); inspector.append(outcome);
  const points = el('div', 'evidence-list'); points.append(el('div', 'section-eyebrow', 'EVIDENCE CHECKS'));
  for (const [symbol, label, detail] of [['◇', 'Market data', record.quality === 'SYNTHETIC' ? 'Example source visible' : record.quality], ['◌', 'Trend overlay', 'Fixture values only'], ['!', 'Qualification', 'No validated strategy evaluation']]) { const row = el('div', 'evidence-item'); row.append(el('span', 'evidence-icon', symbol), el('span', 'evidence-detail')); row.lastChild.append(el('strong', '', label), el('small', '', detail)); points.append(row); }
  inspector.append(points);
  const chat = el('section', 'chat'); chat.append(el('div', 'chat-top', '✦  Ask about this view'), el('p', 'chat-description', 'Static example explanations · no model connected'));
  const prompts = el('div', 'prompt-list');
  for (const question of ['Why NO_TRADE?', 'What data is missing?', 'Explain the overlays']) prompts.append(button(question, 'prompt', () => { state.chat = question; render(); }));
  chat.append(prompts);
  if (state.chat) { const answer = el('div', 'chat-answer'); answer.append(el('small', '', state.chat), el('p', '', state.chat === 'Why NO_TRADE?' ? record.reason : state.chat === 'What data is missing?' ? (record.scenario === 'missing' ? 'Fixture candles 29–33 are absent. The chart shows a visible gap.' : 'No validated live market or order-flow data is connected in this preview.') : 'EMA 20 and EMA 50 are synthetic display overlays; ATR is a fixture value. They are not a validated signal.'), el('span', '', `Fixture source · ${record.version}`)); chat.append(answer); }
  const composer = el('div', 'disabled-composer', 'Free-form chat becomes available after validated evidence APIs'); composer.setAttribute('aria-disabled', 'true'); chat.append(composer); inspector.append(chat);
  main.append(inspector); shell.append(main);
  const footer = el('footer', 'footer', 'SYNTHETIC FIXTURE  ·  NO EXCHANGE OR MODEL CONNECTION  ·  NO ORDER OR APPROVAL ACTIONS'); shell.append(footer);
  app.append(shell);
  if (state.timeframe === '5m') updateSelection(record);
}

render();
