import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { PAIRS, SCENARIOS, SNAPSHOTS, selectFixture } from './fixtures.js';

test('all five fixtures retain a consistent typed-looking provenance envelope', () => {
  assert.equal(PAIRS.length, 5);
  for (const pair of PAIRS) {
    const fixture = selectFixture(pair.symbol, 'no_trade');
    assert.equal(fixture.source, 'SYNTHETIC_FIXTURE');
    assert.equal(fixture.asset, pair.symbol);
    assert.equal(fixture.timeframe, '5m');
    assert.ok(fixture.version && fixture.observedAt);
    assert.equal(fixture.outcome, 'NO_TRADE');
    assert.equal(SNAPSHOTS[pair.symbol].candles.length, 48);
  }
});

test('missing fixture exposes a real gap and quality-driven abstention', () => {
  for (const scenario of ['stale', 'missing', 'contradictory', 'no_trade']) assert.equal(selectFixture('BTCUSDT', scenario).outcome, 'NO_TRADE');
  const missing = selectFixture('BTCUSDT', 'missing');
  assert.equal(missing.quality, 'MISSING');
  assert.equal(missing.candles[30], null);
  assert.equal(missing.candles[34].time, SNAPSHOTS.BTCUSDT.candles[34].time);
  assert.equal(Object.keys(SCENARIOS).length, 5);
});

test('preview has no network, credential, or transaction interface', () => {
  const app = readFileSync(new URL('./app.js', import.meta.url), 'utf8');
  const html = readFileSync(new URL('./index.html', import.meta.url), 'utf8');
  assert.doesNotMatch(app + html, /\bfetch\s*\(|\bWebSocket\s*\(|\bXMLHttpRequest\b|localStorage|sessionStorage|api[_-]?key|order[_-]?submit/i);
  assert.match(app, /FIXTURE PREVIEW  ·  NO LIVE TRADING/);
  assert.match(app, /Free-form chat becomes available after validated evidence APIs/);
});
