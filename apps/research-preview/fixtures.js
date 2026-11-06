// Deterministic display fixtures. These values do not represent any market observation.
export const PAIRS = Object.freeze([
  { symbol: 'BTCUSDT', label: 'Bitcoin', base: 64000, seed: 4 },
  { symbol: 'ETHUSDT', label: 'Ethereum', base: 3200, seed: 11 },
  { symbol: 'BNBUSDT', label: 'BNB', base: 580, seed: 17 },
  { symbol: 'SOLUSDT', label: 'Solana', base: 145, seed: 23 },
  { symbol: 'XRPUSDT', label: 'XRP', base: 0.62, seed: 29 },
]);

export const SCENARIOS = Object.freeze({
  normal: { label: 'Validated example', quality: 'SYNTHETIC', outcome: 'RESEARCH', reason: 'Example evidence is available for inspection. No trading recommendation is generated.' },
  stale: { label: 'Stale source', quality: 'STALE', outcome: 'NO_TRADE', reason: 'The example source timestamp is outside the allowed freshness window.' },
  missing: { label: 'Missing inputs', quality: 'MISSING', outcome: 'NO_TRADE', reason: 'Required market inputs are unavailable. Chart gaps remain visible.' },
  contradictory: { label: 'Conflicting evidence', quality: 'CONFLICT', outcome: 'NO_TRADE', reason: 'Trend and momentum examples disagree. The conflict remains unresolved.' },
  no_trade: { label: 'Insufficient evidence', quality: 'INCOMPLETE', outcome: 'NO_TRADE', reason: 'The example has insufficient validated evidence to qualify a candidate.' },
});

const START = Date.parse('2026-09-29T00:00:00Z');

function round(value, base) {
  return Number(value.toFixed(base < 1 ? 4 : base < 100 ? 2 : 0));
}

function fixtureCandles(pair) {
  const result = [];
  let previous = pair.base;
  for (let i = 0; i < 48; i += 1) {
    const wave = Math.sin((i + pair.seed) * 0.42) * 0.007 + Math.cos((i + pair.seed) * 0.19) * 0.004;
    const drift = (i - 20) * 0.00019;
    const open = previous;
    const close = round(pair.base * (1 + wave + drift), pair.base);
    const high = round(Math.max(open, close) * 1.0028, pair.base);
    const low = round(Math.min(open, close) * 0.9972, pair.base);
    result.push(Object.freeze({ time: START + i * 300000, open: round(open, pair.base), high, low, close, volume: 30 + ((i * 17 + pair.seed * 13) % 61), ema20: round(pair.base * (1 + wave * 0.54 + drift * 0.85), pair.base), ema50: round(pair.base * (1 + wave * 0.3 + drift * 0.7 - 0.001), pair.base) }));
    previous = close;
  }
  return Object.freeze(result);
}

export const SNAPSHOTS = Object.freeze(Object.fromEntries(PAIRS.map((pair) => [pair.symbol, Object.freeze({
  asset: pair.symbol,
  timeframe: '5m',
  source: 'SYNTHETIC_FIXTURE',
  observedAt: '2026-09-29T03:55:00Z',
  version: `preview-${pair.symbol.toLowerCase()}-v1`,
  candles: fixtureCandles(pair),
  atr: round(pair.base * 0.006, pair.base),
})])));

export function selectFixture(symbol, scenario = 'no_trade') {
  const snapshot = SNAPSHOTS[symbol];
  const state = SCENARIOS[scenario];
  if (!snapshot || !state) throw new Error('Unknown preview fixture');
  return Object.freeze({ ...snapshot, scenario, quality: state.quality, outcome: state.outcome, reason: state.reason, candles: scenario === 'missing' ? Object.freeze(snapshot.candles.map((c, i) => i >= 29 && i <= 33 ? null : c)) : snapshot.candles });
}
