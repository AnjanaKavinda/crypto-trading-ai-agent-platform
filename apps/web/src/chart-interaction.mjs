export function chartIndexAtPointer({
  clientX,
  boundsLeft,
  boundsWidth,
  viewWidth,
  plotLeft,
  plotWidth,
  candleCount,
}) {
  if (
    !Number.isFinite(clientX) ||
    !Number.isFinite(boundsLeft) ||
    !Number.isFinite(boundsWidth) ||
    !Number.isFinite(viewWidth) ||
    !Number.isFinite(plotLeft) ||
    !Number.isFinite(plotWidth) ||
    boundsWidth <= 0 ||
    viewWidth <= 0 ||
    plotWidth <= 0 ||
    !Number.isInteger(candleCount) ||
    candleCount < 1
  ) return null;
  if (candleCount === 1) return 0;
  const viewX = ((clientX - boundsLeft) / boundsWidth) * viewWidth;
  const index = Math.round(((viewX - plotLeft) / plotWidth) * (candleCount - 1));
  return Math.max(0, Math.min(candleCount - 1, index));
}

export function moveChartSelection(currentIndex, key, candleCount) {
  if (!Number.isInteger(candleCount) || candleCount < 1) return null;
  if (key === "Home") return 0;
  if (key === "End") return candleCount - 1;
  if (key !== "ArrowLeft" && key !== "ArrowRight") return null;
  const current = Number.isInteger(currentIndex)
    ? Math.max(0, Math.min(candleCount - 1, currentIndex))
    : candleCount - 1;
  const delta = key === "ArrowLeft" ? -1 : 1;
  return Math.max(0, Math.min(candleCount - 1, current + delta));
}

export function priceAxisTicks(minimum, maximum, divisions = 4) {
  if (
    !Number.isFinite(minimum) ||
    !Number.isFinite(maximum) ||
    maximum <= minimum ||
    !Number.isInteger(divisions) ||
    divisions < 1
  ) return [];
  const span = maximum - minimum;
  return Array.from({ length: divisions + 1 }, (_, index) => {
    const fraction = index / divisions;
    return { fraction, value: maximum - fraction * span };
  });
}

export function candleInspectorText(candle, indicatorValues = []) {
  const values = candle?.values;
  const source = candle?.source;
  if (!source || typeof source.open_time !== "string" || !values) return "Candle values are unavailable.";
  const fields = [
    ["Open", values.open],
    ["High", values.high],
    ["Low", values.low],
    ["Close", values.close],
    ["Volume", values.volume],
  ];
  if (fields.some(([, metric]) => typeof metric?.exact !== "string" || typeof metric?.unit !== "string")) {
    return "Candle values are unavailable.";
  }
  const returnedIndicators = Array.isArray(indicatorValues)
    ? indicatorValues.filter((value) => typeof value === "string" && value.length > 0)
    : [];
  return [
    source.open_time,
    ...fields.map(([label, metric]) => `${label}: ${metric.exact} ${metric.unit}`),
    ...returnedIndicators,
  ].join(" · ");
}
