// U6 Today screen: one research state per coin, derived only from the backend
// snapshot and strategy-marker responses. No network or DOM here.

export const TODAY_TIMEFRAME = "4h";
export const TODAY_LIMIT = 250;

const text = (value) => (typeof value === "string" && value ? value : null);

export function todayState({ snapshot, snapshotError, markers, markersError } = {}) {
  if (snapshotError || !snapshot) {
    return { state: "UNAVAILABLE", tone: "error", reasons: [`Snapshot unavailable — ${snapshotError ?? "no response"}`] };
  }
  const quality = snapshot.data_quality?.status;
  if (quality !== "VALID") {
    return { state: quality === "STALE" ? "STALE" : "DATA NOT VALID", tone: "warning",
      reasons: [`Data quality ${quality ?? "not reported"}: no strategy state is shown.`] };
  }
  if (snapshot.temporal_context !== "CURRENT") {
    return { state: "NOT CURRENT", tone: "warning",
      reasons: [`Snapshot is ${snapshot.temporal_context ?? "of unknown time"}; no current state is shown.`] };
  }
  if (markersError || !markers) {
    return { state: "UNAVAILABLE", tone: "error", reasons: [`Strategy markers unavailable — ${markersError ?? "no response"}`] };
  }
  if (markers.snapshot_id !== snapshot.snapshot_id || markers.instrument_id !== snapshot.instrument_id ||
      markers.timeframe !== snapshot.timeframe) {
    return { state: "UNAVAILABLE", tone: "error", reasons: ["Strategy markers do not match the loaded snapshot."] };
  }
  if (markers.status !== "AVAILABLE" || !Array.isArray(markers.markers)) {
    return { state: markers.status === "WARMUP" ? "WARMUP" : "UNAVAILABLE", tone: "warning",
      reasons: [`Strategy markers ${markers.status ?? "unknown"}: ${markers.reason_code ?? "no reason given"}.`] };
  }
  const last = markers.markers.at(-1);
  const conditions = (marker) => (marker?.conditions ?? []).map((item) => text(item?.condition)).filter(Boolean);
  if (last?.status === "PENDING_FILL" && last.side === "BUY") {
    return { state: "BUY SIGNAL", tone: "signal", reasons: [
      `Signal at candle ${text(last.time?.value) ?? "?"} close; would fill at the next candle's open.`, ...conditions(last)] };
  }
  if (last?.status === "PENDING_FILL" && last.side === "SELL") {
    return { state: "SELL SIGNAL", tone: "signal", reasons: [
      `Exit signal at candle ${text(last.time?.value) ?? "?"} close; would fill at the next candle's open.`, ...conditions(last)] };
  }
  if (markers.position === "OPEN") {
    const entry = [...markers.markers].reverse().find((item) => item?.side === "BUY" && item.status === "FILLED");
    return { state: "IN POSITION", tone: "neutral", reasons: [
      `Strategy replay holds a position since ${text(entry?.fill_time?.value) ?? "an earlier candle"}` +
        (text(entry?.stop?.value) ? `; modelled stop ${entry.stop.value}.` : ".")] };
  }
  if (markers.position === "FLAT") {
    return { state: "NO SETUP", tone: "neutral", reasons: ["No EMA20/EMA50 entry cross on the last closed candle."] };
  }
  return { state: "UNAVAILABLE", tone: "error", reasons: ["Strategy-marker position not reported."] };
}
