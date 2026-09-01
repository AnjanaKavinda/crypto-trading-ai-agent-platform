# Market Data, Alternative Data and Data Engineering

## Objective
Create the data foundation for live/historical market intelligence with provenance, quality checks, and separation between raw data, calculated metrics, interpretations, and trading hypotheses.

## Data categories
- OHLCV, trades, order book, spreads, volume, market depth.
- Funding, open interest, liquidations, futures basis, derivatives, options where available.
- On-chain: active addresses, transactions, exchange flows, whale activity, holder distribution, stablecoin flows.
- Fundamental: tokenomics, unlocks, vesting, supply, protocol revenue, TVL, usage, developer activity, governance, partnerships.
- News/sentiment: market news, project news, regulatory events, exchange announcements, social sentiment, narrative momentum.
- Macro/intermarket: BTC dominance, stablecoin liquidity, risk assets, major macro indicators where available.

## Data quality
Every important data point must include source, provider, timestamp, received timestamp, asset, timeframe, raw/calculated status, version, and quality status.

## Quality statuses
VALID, DEGRADED, STALE, INVALID, UNKNOWN.

## Failure behavior
Stale, missing, conflicting, or low-quality data must prevent unsupported trade eligibility and may trigger NO_TRADE or human review.
