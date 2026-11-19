// Small SVG charts for the Trends view. One y-axis per chart, thin marks
// (bars <= 24px, 2px lines), hover and keyboard tooltips, and every value is
// also in the table below the charts.
import { useLayoutEffect, useRef, useState } from "react";
import { fmt, fmtSignedPct } from "./format";

const MARGIN = { top: 12, right: 12, bottom: 34, left: 48 };
const BAR_MAX = 24;
const GAP = 2;

const useWidth = () => {
  const ref = useRef(null);
  const [width, setWidth] = useState(0);
  useLayoutEffect(() => {
    if (!ref.current) return undefined;
    // Measure now; some browsers deliver the first observer callback late.
    setWidth(Math.floor(ref.current.getBoundingClientRect().width));
    const observer = new ResizeObserver(([entry]) => setWidth(Math.floor(entry.contentRect.width)));
    observer.observe(ref.current);
    return () => observer.disconnect();
  }, []);
  return [ref, width];
};

// Round steps of 1, 2 or 5 x 10^n that cover max in about `count` ticks.
const niceStep = (max, count) => {
  const raw = max / count;
  const power = 10 ** Math.floor(Math.log10(raw || 1));
  return [1, 2, 5, 10].map((m) => m * power).find((step) => step >= raw) ?? power * 10;
};

const ticksUpTo = (max, count = 4) => {
  const step = niceStep(max || 1, count);
  const top = Math.ceil((max || 1) / step) * step;
  return Array.from({ length: Math.round(top / step) + 1 }, (_, i) => i * step);
};

const axisLabel = (value, top) => (top >= 10000 ? `${fmt(Math.round(value / 1000))}K` : fmt(value));

// Bar path with 4px rounded corners at the data end only.
const barPath = (x, y, w, h, up = true) => {
  if (h <= 0 || w <= 0) return "";
  const r = Math.min(4, w / 2, h);
  if (up) {
    return `M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h}Z`;
  }
  return `M${x},${y}V${y + h - r}Q${x},${y + h} ${x + r},${y + h}H${x + w - r}Q${x + w},${y + h} ${x + w},${y + h - r}V${y}Z`;
};

const bandLayout = (count, plotWidth) => {
  const band = plotWidth / Math.max(count, 1);
  const bar = band <= 4 ? band : Math.min(BAR_MAX, Math.max(2, band * 0.7));
  return { band, bar };
};

// Picks about `target` evenly spaced indexes for x-axis labels.
const labelIndexes = (count, target) => {
  if (count <= target) return Array.from({ length: count }, (_, i) => i);
  const step = Math.ceil(count / target);
  const picks = [];
  for (let i = count - 1; i >= 0; i -= step) picks.unshift(i);
  return picks;
};

function Tooltip({ x, width, children }) {
  const left = Math.min(Math.max(x, 90), Math.max(width - 90, 90));
  return (
    <div className="chart-tooltip" style={{ left }} role="status">
      {children}
    </div>
  );
}

function TooltipRow({ value, label, kind, color }) {
  return (
    <div className="tooltip-row">
      {kind && <span className={`tooltip-key tooltip-key-${kind}`} style={{ background: color }} aria-hidden="true" />}
      <span className="tooltip-value">{value}</span>
      <span className="tooltip-label">{label}</span>
    </div>
  );
}

// Shared hover and keyboard handling: one active index per chart.
const useActive = (count) => {
  const [active, setActive] = useState(null);
  const onKeyDown = (event) => {
    if (!count) return;
    if (event.key === "ArrowRight" || event.key === "ArrowLeft") {
      event.preventDefault();
      setActive((current) => {
        const start = current ?? (event.key === "ArrowRight" ? -1 : count);
        return Math.min(count - 1, Math.max(0, start + (event.key === "ArrowRight" ? 1 : -1)));
      });
    }
    if (event.key === "Escape") setActive(null);
  };
  return {
    active: active != null && active < count ? active : null,
    setActive,
    focusProps: {
      tabIndex: 0,
      onKeyDown,
      onFocus: () => setActive((current) => current ?? count - 1),
      onBlur: () => setActive(null),
      onPointerLeave: () => setActive(null),
    },
  };
};

function XAxis({ periods, band, left, y, labelFor }) {
  return labelIndexes(periods.length, Math.max(2, Math.floor((band * periods.length) / 72))).map((index) => (
    <text key={periods[index].key} className="axis-text" x={left + band * (index + 0.5)} y={y} textAnchor="middle">
      {labelFor(periods[index])}
    </text>
  ));
}

function YAxis({ ticks, top, scale, left, right }) {
  return ticks.map((tick) => (
    <g key={tick}>
      <line className="grid-line" x1={left} x2={right} y1={scale(tick)} y2={scale(tick)} />
      <text className="axis-text" x={left - 8} y={scale(tick)} dy="0.32em" textAnchor="end">
        {axisLabel(tick, top)}
      </text>
    </g>
  ));
}

/** Sales per period: subscriptions and one-time orders stacked, the issued
 * forecast as a line, and a marker under periods with a major festival. */
export function SalesChart({ periods, perDay, showForecast, labelFor, describe }) {
  const [ref, width] = useWidth();
  const { active, setActive, focusProps } = useActive(periods.length);
  const height = 280;
  const plotLeft = MARGIN.left;
  const plotRight = Math.max(width - MARGIN.right, plotLeft + 1);
  const plotTop = MARGIN.top;
  const plotBottom = height - MARGIN.bottom;
  const { band, bar } = bandLayout(periods.length, plotRight - plotLeft);
  const maxValue = Math.max(
    1,
    ...periods.map((p) => p.actual ?? 0),
    ...(showForecast ? periods.map((p) => p.forecast ?? 0) : []),
  );
  const ticks = ticksUpTo(maxValue);
  const top = ticks.at(-1);
  const scale = (value) => plotBottom - ((plotBottom - plotTop) * value) / top;
  const center = (index) => plotLeft + band * (index + 0.5);

  // Forecast line, broken wherever a period has no issued forecast.
  const segments = [];
  if (showForecast) {
    let current = [];
    periods.forEach((period, index) => {
      if (period.forecast == null) {
        if (current.length) segments.push(current);
        current = [];
      } else {
        current.push([center(index), scale(period.forecast)]);
      }
    });
    if (current.length) segments.push(current);
  }
  const activePeriod = active != null ? periods[active] : null;

  return (
    <div className="chart" ref={ref}>
      {width > 0 && (
        <svg width={width} height={height} role="img" aria-label={describe} {...focusProps} className="chart-svg">
          <YAxis ticks={ticks} top={top} scale={scale} left={plotLeft} right={plotRight} />
          {active != null && (
            <rect className="hover-band" x={plotLeft + band * active} y={plotTop} width={band} height={plotBottom - plotTop} />
          )}
          {periods.map((period, index) => {
            if (!period.actual) return null;
            const x = center(index) - bar / 2;
            const subsHeight = (plotBottom - scale(period.subscription ?? 0));
            const totalHeight = plotBottom - scale(period.actual);
            const onceHeight = totalHeight - subsHeight;
            const gap = bar > 4 && onceHeight > GAP && subsHeight > GAP ? GAP : 0;
            const roundSubs = onceHeight <= GAP;
            return (
              <g key={period.key}>
                <path
                  className="mark-subscription"
                  d={roundSubs
                    ? barPath(x, plotBottom - subsHeight, bar, subsHeight)
                    : `M${x},${plotBottom}V${plotBottom - subsHeight}H${x + bar}V${plotBottom}Z`}
                />
                {!roundSubs && (
                  <path className="mark-once" d={barPath(x, plotBottom - totalHeight, bar, onceHeight - gap)} />
                )}
              </g>
            );
          })}
          {segments.map((points) => (
            points.length > 1 ? (
              <polyline key={points[0].join()} className="mark-forecast" points={points.map((p) => p.join(",")).join(" ")} />
            ) : (
              <circle key={points[0].join()} className="mark-forecast-dot" cx={points[0][0]} cy={points[0][1]} r="4" />
            )
          ))}
          {activePeriod?.forecast != null && showForecast && (
            <circle className="mark-forecast-dot" cx={center(active)} cy={scale(activePeriod.forecast)} r="4" />
          )}
          {periods.map((period, index) => (period.majorFestival ? (
            <circle key={`f-${period.key}`} className="mark-festival" cx={center(index)} cy={plotBottom + 8} r="3.5" />
          ) : null))}
          <line className="baseline" x1={plotLeft} x2={plotRight} y1={plotBottom} y2={plotBottom} />
          <XAxis periods={periods} band={band} left={plotLeft} y={height - 6} labelFor={labelFor} />
          {periods.map((period, index) => (
            <rect
              key={`hit-${period.key}`}
              className="hit"
              x={plotLeft + band * index}
              y={plotTop}
              width={band}
              height={plotBottom - plotTop + 16}
              onPointerEnter={() => setActive(index)}
              onPointerMove={() => setActive(index)}
            />
          ))}
        </svg>
      )}
      {activePeriod && (
        <Tooltip x={center(active)} width={width}>
          <div className="tooltip-title">{activePeriod.title}</div>
          {activePeriod.actual == null ? (
            <div className="tooltip-label">No sales data yet</div>
          ) : (
            <>
              <TooltipRow value={fmt(activePeriod.actual)} label={perDay ? "sales a day" : "sales"} />
              <TooltipRow value={fmt(activePeriod.subscription)} label="subscriptions" kind="box" color="var(--viz-subscription)" />
              <TooltipRow value={fmt(activePeriod.buyOnce)} label="one-time orders" kind="box" color="var(--viz-once)" />
            </>
          )}
          {showForecast && activePeriod.forecast != null && (
            <TooltipRow value={fmt(activePeriod.forecast)} label="issued forecast" kind="line" color="var(--viz-forecast)" />
          )}
          {activePeriod.festivals.length > 0 && (
            <div className="tooltip-note">{activePeriod.festivals.join(", ")}</div>
          )}
        </Tooltip>
      )}
    </div>
  );
}

/** How far the issued forecast was from actual sales, per period: above
 * the line it was too high, below too low. */
export function BiasChart({ periods, labelFor, describe }) {
  const [ref, width] = useWidth();
  const { active, setActive, focusProps } = useActive(periods.length);
  const height = 200;
  const plotLeft = MARGIN.left;
  const plotRight = Math.max(width - MARGIN.right, plotLeft + 1);
  const plotTop = MARGIN.top;
  const plotBottom = height - MARGIN.bottom;
  const { band, bar } = bandLayout(periods.length, plotRight - plotLeft);
  const maxAbs = Math.max(2, ...periods.map((p) => Math.abs(p.biasPct ?? 0)));
  const step = niceStep(maxAbs, 2);
  const limit = Math.ceil(maxAbs / step) * step;
  const ticks = [];
  for (let value = -limit; value <= limit + 1e-9; value += step) ticks.push(Math.round(value * 100) / 100);
  const scale = (value) => plotTop + ((plotBottom - plotTop) * (limit - value)) / (2 * limit);
  const zero = scale(0);
  const center = (index) => plotLeft + band * (index + 0.5);
  const activePeriod = active != null ? periods[active] : null;

  return (
    <div className="chart" ref={ref}>
      {width > 0 && (
        <svg width={width} height={height} role="img" aria-label={describe} {...focusProps} className="chart-svg">
          {ticks.map((tick) => (
            <g key={tick}>
              <line className={tick === 0 ? "baseline" : "grid-line"} x1={plotLeft} x2={plotRight} y1={scale(tick)} y2={scale(tick)} />
              <text className="axis-text" x={plotLeft - 8} y={scale(tick)} dy="0.32em" textAnchor="end">
                {tick === 0 ? "0%" : `${tick > 0 ? "+" : ""}${tick}%`}
              </text>
            </g>
          ))}
          {active != null && (
            <rect className="hover-band" x={plotLeft + band * active} y={plotTop} width={band} height={plotBottom - plotTop} />
          )}
          {periods.map((period, index) => {
            if (period.biasPct == null) return null;
            const x = center(index) - bar / 2;
            const y = scale(period.biasPct);
            return period.biasPct >= 0
              ? <path key={period.key} className="mark-high" d={barPath(x, y, bar, zero - y, true)} />
              : <path key={period.key} className="mark-low" d={barPath(x, zero, bar, y - zero, false)} />;
          })}
          <XAxis periods={periods} band={band} left={plotLeft} y={height - 6} labelFor={labelFor} />
          {periods.map((period, index) => (
            <rect
              key={`hit-${period.key}`}
              className="hit"
              x={plotLeft + band * index}
              y={plotTop}
              width={band}
              height={plotBottom - plotTop}
              onPointerEnter={() => setActive(index)}
              onPointerMove={() => setActive(index)}
            />
          ))}
        </svg>
      )}
      {activePeriod && (
        <Tooltip x={center(active)} width={width}>
          <div className="tooltip-title">{activePeriod.title}</div>
          {activePeriod.biasPct == null ? (
            <div className="tooltip-label">No issued forecast to compare</div>
          ) : (
            <>
              <TooltipRow
                value={fmtSignedPct(activePeriod.biasPct)}
                label={activePeriod.biasPct >= 0 ? "forecast too high" : "forecast too low"}
                kind="box"
                color={activePeriod.biasPct >= 0 ? "var(--viz-high)" : "var(--viz-low)"}
              />
              <TooltipRow value={fmt(activePeriod.comparedForecast)} label="forecast" />
              <TooltipRow value={fmt(activePeriod.comparedActual)} label="actual" />
              <TooltipRow value={`${activePeriod.errorPct.toFixed(1)}%`} label="error by product" />
            </>
          )}
        </Tooltip>
      )}
    </div>
  );
}

/** Each weekday's average sales as a % above or below the average day. */
export function WeekdayChart({ weekdays, describe }) {
  const [ref, width] = useWidth();
  const { active, setActive, focusProps } = useActive(weekdays.length);
  const height = 180;
  const plotLeft = MARGIN.left;
  const plotRight = Math.max(width - MARGIN.right, plotLeft + 1);
  const plotTop = MARGIN.top + 14;
  const plotBottom = height - MARGIN.bottom;
  const { band, bar } = bandLayout(weekdays.length, plotRight - plotLeft);
  const maxAbs = Math.max(2, ...weekdays.map((d) => Math.abs(d.vsAverage ?? 0)));
  const step = niceStep(maxAbs, 2);
  const limit = Math.ceil(maxAbs / step) * step;
  const scale = (value) => plotTop + ((plotBottom - plotTop) * (limit - value)) / (2 * limit);
  const zero = scale(0);
  const center = (index) => plotLeft + band * (index + 0.5);
  const valued = weekdays.filter((d) => d.vsAverage != null);
  const highest = valued.reduce((best, d) => (best && best.vsAverage >= d.vsAverage ? best : d), null);
  const lowest = valued.reduce((best, d) => (best && best.vsAverage <= d.vsAverage ? best : d), null);
  const activeDay = active != null ? weekdays[active] : null;

  return (
    <div className="chart" ref={ref}>
      {width > 0 && (
        <svg width={width} height={height} role="img" aria-label={describe} {...focusProps} className="chart-svg">
          {[limit, 0, -limit].map((tick) => (
            <g key={tick}>
              <line className={tick === 0 ? "baseline" : "grid-line"} x1={plotLeft} x2={plotRight} y1={scale(tick)} y2={scale(tick)} />
              <text className="axis-text" x={plotLeft - 8} y={scale(tick)} dy="0.32em" textAnchor="end">
                {tick === 0 ? "avg" : `${tick > 0 ? "+" : ""}${tick}%`}
              </text>
            </g>
          ))}
          {active != null && (
            <rect className="hover-band" x={plotLeft + band * active} y={plotTop} width={band} height={plotBottom - plotTop} />
          )}
          {weekdays.map((day, index) => {
            if (day.vsAverage == null) return null;
            const x = center(index) - bar / 2;
            const y = scale(day.vsAverage);
            const up = day.vsAverage >= 0;
            const labelled = day === highest || day === lowest;
            return (
              <g key={day.label}>
                <path className="mark-weekday" d={up ? barPath(x, y, bar, zero - y, true) : barPath(x, zero, bar, y - zero, false)} />
                {labelled && (
                  <text className="value-text" x={center(index)} y={up ? y - 6 : y + 14} textAnchor="middle">
                    {fmtSignedPct(day.vsAverage)}
                  </text>
                )}
              </g>
            );
          })}
          {weekdays.map((day, index) => (
            <text key={`x-${day.label}`} className="axis-text" x={center(index)} y={height - 6} textAnchor="middle">{day.label}</text>
          ))}
          {weekdays.map((day, index) => (
            <rect
              key={`hit-${day.label}`}
              className="hit"
              x={plotLeft + band * index}
              y={plotTop}
              width={band}
              height={plotBottom - plotTop}
              onPointerEnter={() => setActive(index)}
              onPointerMove={() => setActive(index)}
            />
          ))}
        </svg>
      )}
      {activeDay && (
        <Tooltip x={center(active)} width={width}>
          <div className="tooltip-title">{activeDay.name}</div>
          {activeDay.vsAverage == null ? (
            <div className="tooltip-label">No sales data</div>
          ) : (
            <>
              <TooltipRow value={fmt(Math.round(activeDay.avg))} label="sales on average" />
              <TooltipRow value={fmtSignedPct(activeDay.vsAverage)} label="vs the average day" />
            </>
          )}
        </Tooltip>
      )}
    </div>
  );
}
