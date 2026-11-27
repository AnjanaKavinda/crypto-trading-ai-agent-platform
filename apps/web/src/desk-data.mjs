// Shared desk data (UR1/UR3): one supported-symbol read and one stored
// snapshot read per coin and timeframe, shared by the header freshness chip,
// Today, the markets list and the chart (each snapshot read costs the API a
// full indicator/analysis pass, so it is never repeated needlessly). Also the
// selected coin/timeframe shared by every tab. Read-only: nothing here
// refreshes providers or writes to the API.
import { listSupportedSymbols } from "./research-api.mjs";
import { deskSelection, DESK_TIMEFRAMES, saveSelection } from "./desk-state.mjs";
import { readWatchlist, readWatchlistEntry, supportedWatchlistSymbols, watchlistRow } from "./watchlist-state.mjs";

export function createDesk({ fetcher = globalThis.fetch, storage = null, search = "" } = {}) {
  let symbolsResponse = null;
  const entries = new Map();
  const listeners = new Set();
  let selection = null;
  const entryKey = (instrumentId, timeframe) => `${instrumentId}|${timeframe}`;
  const notify = (change) => {
    for (const listener of listeners) listener(selection, change);
  };

  const desk = {
    // Raw /symbols response (each consumer validates the contract it needs).
    symbolsResponse() {
      symbolsResponse ??= listSupportedSymbols(fetcher).catch((error) => {
        symbolsResponse = null;
        throw error;
      });
      return symbolsResponse;
    },
    async symbols() {
      return supportedWatchlistSymbols(await desk.symbolsResponse());
    },
    // One coin's stored snapshot at the 501-candle bound: { symbol, snapshot, row, error }.
    entry(item, timeframe) {
      const key = entryKey(item.instrument_id, timeframe);
      if (!entries.has(key)) entries.set(key, readWatchlistEntry(fetcher, timeframe, item));
      return entries.get(key);
    },
    // The five coins for one timeframe, in symbol order.
    async watchlist(timeframe) {
      const symbols = await desk.symbols();
      // The selected coin is read first: it is the one on screen.
      const chosen = symbols.find((item) => item.instrument_id === selection?.instrumentId);
      if (chosen) desk.entry(chosen, timeframe);
      return readWatchlist(fetcher, timeframe, symbols, (item) => desk.entry(item, timeframe));
    },
    // After an explicit refresh the new snapshot replaces the cached one.
    seed(item, timeframe, snapshot) {
      entries.set(entryKey(item.instrument_id, timeframe), Promise.resolve({
        symbol: item.symbol, snapshot, row: watchlistRow(snapshot, item.symbol), error: null,
      }));
      notify({ invalidated: timeframe });
    },
    invalidate(timeframe) {
      for (const key of [...entries.keys()]) if (!timeframe || key.endsWith(`|${timeframe}`)) entries.delete(key);
      notify({ invalidated: timeframe ?? "all" });
    },
    async selection() {
      if (!selection) {
        let symbols = [];
        try {
          symbols = await desk.symbols();
        } catch {
          symbols = [];
        }
        selection ??= deskSelection({ search, storage, symbols, timeframes: DESK_TIMEFRAMES });
        if (selection.instrumentId) saveSelection(storage, selection);
      }
      return selection;
    },
    current() {
      return selection;
    },
    // Change the shared coin and/or timeframe; every tab is told.
    select(next) {
      const updated = { ...selection, ...next };
      if (!DESK_TIMEFRAMES.includes(updated.timeframe)) return selection;
      if (updated.instrumentId === selection?.instrumentId && updated.timeframe === selection?.timeframe) return selection;
      selection = updated;
      saveSelection(storage, selection);
      notify({});
      return selection;
    },
    onChange(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
  };
  return desk;
}
