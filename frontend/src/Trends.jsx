import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { getTrends } from "./api";
import Brand from "./Brand";
import { BiasChart, SalesChart, WeekdayChart } from "./charts";
import {
  CITY_ORDER,
  cityName,
  daysBetween,
  downloadCsv,
  fmt,
  fmtPct,
  fmtSignedPct,
  formatDay,
  shiftDate,
  todayInIndia,
} from "./format";

// The forecast drops a product only after this many days without sales
// (DISCONTINUED_AFTER_DAYS in backend/main.py).
const DISCONTINUED_AFTER_DAYS = 28;

const RANGES = [
  ["4w", "4 weeks", 28, "day"],
  ["3m", "3 months", 91, "week"],
  ["6m", "6 months", 182, "week"],
  ["1y", "1 year", 364, "month"],
];

const GROUPS = [
  ["day", "Day"],
  ["week", "Week"],
  ["month", "Month"],
];

const WEEKDAYS = [
  ["Mon", "Monday"], ["Tue", "Tuesday"], ["Wed", "Wednesday"], ["Thu", "Thursday"],
  ["Fri", "Friday"], ["Sat", "Saturday"], ["Sun", "Sunday"],
];

const WAKE_RETRY_MS = 8000;
const MAX_WAKE_RETRIES = 15;

const weekdayIndex = (iso) => (new Date(`${iso}T12:00:00Z`).getUTCDay() + 6) % 7;
const periodKey = (iso, group) => {
  if (group === "week") return shiftDate(iso, -weekdayIndex(iso));
  if (group === "month") return `${iso.slice(0, 8)}01`;
  return iso;
};
const monthLabel = (iso, withYear) => new Intl.DateTimeFormat("en-IN", {
  month: "short",
  ...(withYear ? { year: "numeric" } : {}),
  timeZone: "Asia/Kolkata",
}).format(new Date(`${iso}T12:00:00+05:30`));

const sum = (values) => values.reduce((total, value) => total + (value ?? 0), 0);
const pctChange = (now, before) => (before ? (100 * (now - before)) / before : null);

// "5 Nov - 17 Nov" style ranges from a sorted list of ISO dates.
const dateRuns = (dates) => {
  const runs = [];
  for (const date of dates) {
    const last = runs.at(-1);
    if (last && daysBetween(last[1], date) === 1) last[1] = date;
    else runs.push([date, date]);
  }
  return runs.map(([from, to]) => (from === to ? formatDay(from) : `${formatDay(from)} to ${formatDay(to)}`));
};

const readParams = () => {
  const params = new URLSearchParams(window.location.search);
  const range = RANGES.some(([key]) => key === params.get("range")) || params.get("range") === "custom"
    ? params.get("range")
    : "4w";
  return {
    range,
    from: params.get("from") || "",
    to: params.get("to") || "",
    city: params.get("city") || "ALL",
    product: params.get("product") || "ALL",
    group: GROUPS.some(([key]) => key === params.get("group")) ? params.get("group") : null,
  };
};

function buildPeriods(days, festivals, group) {
  const festivalsByDate = new Map();
  for (const festival of festivals) {
    if (!festivalsByDate.has(festival.date)) festivalsByDate.set(festival.date, []);
    festivalsByDate.get(festival.date).push(festival);
  }
  const groups = new Map();
  for (const day of days) {
    const key = periodKey(day.date, group);
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(day);
  }
  const multiYear = days.length && days[0].date.slice(0, 4) !== days.at(-1).date.slice(0, 4);
  return [...groups.entries()].map(([key, members]) => {
    const withSales = members.filter((day) => day.actual != null);
    const salesDays = withSales.length;
    const perDay = group !== "day";
    const average = (field) => (salesDays ? Math.round(sum(withSales.map((d) => d[field])) / (perDay ? salesDays : 1)) : null);
    const comparedActual = sum(members.map((d) => d.compared_actual));
    const comparedForecast = sum(members.map((d) => d.compared_forecast));
    const absError = sum(members.map((d) => d.abs_error));
    const dayFestivals = members.flatMap((day) => festivalsByDate.get(day.date) ?? []);
    const first = members[0].date;
    const last = members.at(-1).date;
    let title = formatDay(first, true);
    if (group === "week") title = `Week of ${formatDay(first, true)}${first === last ? "" : ` to ${formatDay(last)}`}`;
    if (group === "month") title = monthLabel(first, true);
    return {
      key,
      first,
      last,
      title,
      label: group === "month" ? monthLabel(first, multiYear) : formatDay(first),
      salesDays,
      actual: average("actual"),
      subscription: average("subscription"),
      buyOnce: average("buy_once"),
      forecast: group === "day" ? members[0].forecast : null,
      comparedActual,
      comparedForecast,
      biasPct: comparedActual ? (100 * (comparedForecast - comparedActual)) / comparedActual : null,
      errorPct: comparedActual ? (100 * absError) / comparedActual : null,
      festivals: [...new Set(dayFestivals.map((f) => `${f.festival} (${formatDay(f.date)})`))],
      majorFestival: dayFestivals.some((f) => f.impact === "HIGH"),
    };
  });
}

function weekdayPattern(days) {
  const selling = days.filter((day) => day.actual > 0);
  const overall = selling.length ? sum(selling.map((d) => d.actual)) / selling.length : 0;
  return WEEKDAYS.map(([label, name], index) => {
    const matching = selling.filter((day) => weekdayIndex(day.date) === index);
    const avg = matching.length ? sum(matching.map((d) => d.actual)) / matching.length : null;
    return { label, name, avg, vsAverage: avg != null && overall ? (100 * (avg - overall)) / overall : null };
  });
}

function insights(data, scopeLabel) {
  const notes = [];
  const { summary, breakdown, events, festivals, days, meta } = data;
  const change = pctChange(summary.avg_per_day, summary.prev_avg_per_day);
  if (summary.avg_per_day != null) {
    notes.push({
      key: "level",
      text: change == null
        ? `${scopeLabel} averaged ${fmt(Math.round(summary.avg_per_day))} packets a day.`
        : `${scopeLabel} averaged ${fmt(Math.round(summary.avg_per_day))} packets a day, ${fmtPct(Math.abs(change))} ${change >= 0 ? "more" : "less"} than the ${daysBetween(summary.prev_start, summary.prev_end) + 1} days before (${fmt(Math.round(summary.prev_avg_per_day))} a day).`,
    });
  }

  // Stopped and new products, grouped across cities.
  const grouped = new Map();
  for (const event of events) {
    const key = `${event.type}|${event.product}|${event.date}`;
    if (!grouped.has(key)) grouped.set(key, { ...event, cities: [], avg: 0 });
    const entry = grouped.get(key);
    entry.cities.push(event.city);
    entry.avg += event.avg_per_day;
  }
  for (const entry of grouped.values()) {
    const where = entry.cities.length === CITY_ORDER.length ? "every city" : entry.cities.map(cityName).join(", ");
    if (entry.type === "stopped") {
      const dropsOn = shiftDate(entry.date, DISCONTINUED_AFTER_DAYS);
      notes.push({
        key: `stop-${entry.product}-${entry.date}`,
        tone: "draft",
        text: `${entry.product} stopped selling in ${where} from ${formatDay(entry.date)}. It sold about ${fmt(Math.round(entry.avg))} a day before. The forecast keeps planning a product until it has had no sales for ${DISCONTINUED_AFTER_DAYS} days${dropsOn > todayInIndia() ? `, so it stays in the forecast until about ${formatDay(dropsOn)}` : ""}.`,
      });
    } else {
      notes.push({
        key: `start-${entry.product}-${entry.date}`,
        text: `${entry.product} started selling in ${where} on ${formatDay(entry.date)}, about ${fmt(Math.round(entry.avg))} a day since.`,
      });
    }
  }

  const movers = breakdown
    .filter((row) => row.prev_avg_per_day)
    .map((row) => ({ ...row, delta: row.avg_per_day - row.prev_avg_per_day }))
    .filter((row) => Math.abs(row.delta / row.prev_avg_per_day) >= 0.03 && Math.abs(row.delta) >= 20)
    .sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta))
    .slice(0, 3);
  if (movers.length) {
    const name = (row) => (data.breakdown_by === "city" ? cityName(row.key) : row.key);
    notes.push({
      key: "movers",
      text: `Biggest changes: ${movers.map((row) => `${name(row)} ${row.delta > 0 ? "+" : ""}${fmt(Math.round(row.delta))} a day (${fmtSignedPct(pctChange(row.avg_per_day, row.prev_avg_per_day))})`).join("; ")}.`,
    });
  }

  if (summary.compared_days) {
    notes.push({
      key: "bias",
      text: `On the ${summary.compared_days} days with an issued forecast, it was ${fmtPct(Math.abs(summary.bias_pct))} too ${summary.bias_pct >= 0 ? "high" : "low"} overall, with a ${fmtPct(summary.error_pct)} error product by product.`,
    });
  }
  const salesEnd = meta.actuals_through < data.end ? meta.actuals_through : data.end;
  // Gaps count only after the first issued day in view; earlier days may
  // predate nightly issuance.
  const firstIssued = days.find((day) => day.compared_actual != null)?.date;
  const missing = days
    .filter((day) => firstIssued && day.date > firstIssued && day.date <= salesEnd)
    .filter((day) => day.actual && day.compared_actual == null)
    .map((day) => day.date);
  if (missing.length) {
    notes.push({
      key: "missing",
      text: `No issued forecast for ${missing.length} day${missing.length > 1 ? "s" : ""} (${dateRuns(missing).join(", ")}), so these are left out of the accuracy figures.`,
    });
  }
  const missingData = days.filter((day) => day.missing_data_cities?.length).map((day) => day.date);
  if (missingData.length) {
    notes.push({
      key: "missing-data",
      text: `Sales for ${dateRuns(missingData).join(", ")} are missing from the sales data (the orders exist, but the day was not loaded). These days are left out of the totals, averages and accuracy, and the forecast models skip them too.`,
    });
  }
  const zeroDays = days.filter((day) => day.actual === 0).map((day) => day.date);
  if (zeroDays.length) {
    notes.push({
      key: "zero",
      text: `No sales recorded on ${dateRuns(zeroDays).join(", ")}.`,
    });
  }
  const major = festivals.filter((festival) => festival.impact === "HIGH");
  if (major.length) {
    const names = [...new Set(major.map((f) => `${f.festival} (${formatDay(f.date)})`))];
    notes.push({
      key: "festivals",
      text: `${names.length} major festival${names.length > 1 ? "s" : ""} in this period: ${names.slice(0, 5).join(", ")}${names.length > 5 ? ` and ${names.length - 5} more` : ""}.`,
    });
  }
  if (meta.actuals_through < data.end) {
    notes.push({
      key: "fresh",
      text: `Sales data runs to ${formatDay(meta.actuals_through, true)}; it is refreshed every night after the forecast is issued, so later days are not shown yet.`,
    });
  }
  return notes;
}

export default function Trends({ tabs }) {
  const [initial] = useState(readParams);
  const yesterday = shiftDate(todayInIndia(), -1);
  const [range, setRange] = useState(initial.range);
  const [customFrom, setCustomFrom] = useState(initial.from || shiftDate(yesterday, -27));
  const [customTo, setCustomTo] = useState(initial.to || yesterday);
  const [city, setCity] = useState(initial.city);
  const [product, setProduct] = useState(initial.product);
  const [groupChoice, setGroupChoice] = useState(initial.group);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [waking, setWaking] = useState(false);
  const [error, setError] = useState("");
  const requestIdRef = useRef(0);
  const retryRef = useRef(null);
  const loadRef = useRef(() => {});

  const preset = RANGES.find(([key]) => key === range);
  const end = preset ? yesterday : customTo;
  const start = preset ? shiftDate(yesterday, -(preset[2] - 1)) : customFrom;
  const group = groupChoice ?? (preset ? preset[3] : (daysBetween(start, end) > 120 ? "week" : "day"));
  const rangeInvalid = !preset && (!customFrom || !customTo || customFrom > customTo || daysBetween(customFrom, customTo) >= 400);

  const load = useCallback((attempt = 0) => {
    if (retryRef.current) clearTimeout(retryRef.current);
    if (rangeInvalid) return;
    const requestId = attempt === 0 ? ++requestIdRef.current : requestIdRef.current;
    if (attempt === 0) {
      setLoading(true);
      setError("");
    }
    getTrends({ start, end, city, product })
      .then((payload) => {
        if (requestIdRef.current !== requestId) return;
        setData(payload);
        setLoading(false);
        setWaking(false);
      })
      .catch((err) => {
        if (requestIdRef.current !== requestId) return;
        if (err.code === "unreachable" && attempt < MAX_WAKE_RETRIES) {
          setWaking(true);
          retryRef.current = setTimeout(() => loadRef.current(attempt + 1), WAKE_RETRY_MS);
          return;
        }
        setWaking(false);
        setLoading(false);
        setError(err.message);
      });
  }, [start, end, city, product, rangeInvalid]);

  useEffect(() => {
    loadRef.current = load;
  }, [load]);

  useEffect(() => {
    const url = new URL(window.location);
    url.search = "";
    url.searchParams.set("view", "trends");
    url.searchParams.set("range", range);
    if (!preset) {
      url.searchParams.set("from", customFrom);
      url.searchParams.set("to", customTo);
    }
    if (city !== "ALL") url.searchParams.set("city", city);
    if (product !== "ALL") url.searchParams.set("product", product);
    if (groupChoice) url.searchParams.set("group", groupChoice);
    window.history.replaceState({}, "", url);
    Promise.resolve().then(() => load());
    return () => {
      if (retryRef.current) clearTimeout(retryRef.current);
    };
  }, [load, range, preset, customFrom, customTo, city, product, groupChoice]);

  const periods = useMemo(
    () => (data ? buildPeriods(data.days, data.festivals, group) : []),
    [data, group],
  );
  const weekdays = useMemo(() => (data ? weekdayPattern(data.days) : []), [data]);

  const scopeLabel = [
    data?.product && data.product !== "ALL" ? data.product : null,
    data?.city && data.city !== "ALL" ? cityName(data.city) : "All cities",
  ].filter(Boolean).join(" in ");
  const notes = useMemo(() => (data ? insights(data, scopeLabel) : []), [data, scopeLabel]);

  const summary = data?.summary;
  const change = summary ? pctChange(summary.avg_per_day, summary.prev_avg_per_day) : null;
  const perDay = group !== "day";
  const showForecast = group === "day" && periods.some((p) => p.forecast != null);
  const hasBias = periods.some((p) => p.biasPct != null);
  const products = data?.options?.products ?? [];
  const breakdownName = (key) => (data?.breakdown_by === "city" ? cityName(key) : key);

  const chooseRange = (key) => {
    setRange(key);
    setGroupChoice(null);
  };
  const chooseCity = (value) => {
    setCity(value);
    setProduct("ALL");
  };

  const exportCsv = () => {
    downloadCsv(
      `order_trends_${start}_to_${end}${city !== "ALL" ? `_${city}` : ""}.csv`,
      [
        group === "day" ? "Date" : "Period start",
        perDay ? "Sales a day" : "Sales",
        perDay ? "Subscriptions a day" : "Subscriptions",
        perDay ? "One-time orders a day" : "One-time orders",
        "Issued forecast",
        "Forecast vs actual %",
        "Error %",
        "Festivals",
      ],
      periods.map((p) => [
        p.first,
        p.actual ?? "",
        p.subscription ?? "",
        p.buyOnce ?? "",
        p.forecast ?? "",
        p.biasPct != null ? p.biasPct.toFixed(1) : "",
        p.errorPct != null ? p.errorPct.toFixed(1) : "",
        p.festivals.join("; "),
      ]),
    );
  };

  const groupWord = { day: "day", week: "week", month: "month" }[group];

  return (
    <div className="app">
      <header className="header">
        <div className="header-inner">
          <Brand>{tabs}</Brand>
        </div>
      </header>

      <div className="layout layout-single">
        <main className="content">
          <div className="filters" role="group" aria-label="Filters">
            <div className="segmented" role="group" aria-label="Period">
              {RANGES.map(([key, label]) => (
                <button key={key} type="button" className="segment" aria-pressed={range === key} onClick={() => chooseRange(key)}>
                  {label}
                </button>
              ))}
              <button type="button" className="segment" aria-pressed={range === "custom"} onClick={() => chooseRange("custom")}>
                Custom
              </button>
            </div>
            {range === "custom" && (
              <div className="custom-range">
                <input type="date" className="field" aria-label="From" value={customFrom} max={customTo} onChange={(e) => setCustomFrom(e.target.value)} />
                <span className="range-to">to</span>
                <input type="date" className="field" aria-label="To" value={customTo} min={customFrom} onChange={(e) => setCustomTo(e.target.value)} />
              </div>
            )}
            <select className="field" aria-label="City" value={city} onChange={(e) => chooseCity(e.target.value)}>
              <option value="ALL">All cities</option>
              {CITY_ORDER.map((code) => <option key={code} value={code}>{cityName(code)}</option>)}
            </select>
            <select className="field field-product" aria-label="Product" value={product} onChange={(e) => setProduct(e.target.value)}>
              <option value="ALL">All products</option>
              {products.map((name) => <option key={name} value={name}>{name}</option>)}
              {product !== "ALL" && !products.includes(product) && <option value={product}>{product}</option>}
            </select>
            <div className="segmented" role="group" aria-label="Group by">
              {GROUPS.map(([key, label]) => (
                <button key={key} type="button" className="segment" aria-pressed={group === key} onClick={() => setGroupChoice(key)}>
                  {label}
                </button>
              ))}
            </div>
          </div>

          {rangeInvalid && (
            <div className="callout callout-draft"><span className="dot dot-draft" /><span>Pick a start date before the end date, at most 400 days apart.</span></div>
          )}
          {waking && !error && (
            <p className="meta-line">Connecting to the server. This takes about a minute after a quiet period.</p>
          )}
          {error && (
            <div className="callout callout-error" role="alert">
              <span className="dot dot-error" />
              <span title={error}>Couldn&apos;t load the trends. Check your connection and try again.</span>
              <button type="button" className="btn btn-ghost" onClick={() => load()}>Try again</button>
            </div>
          )}

          <div className={`trends ${loading && data ? "is-refreshing" : ""}`} aria-busy={loading}>
            <section className="summary trends-summary" aria-live="polite">
              <div className="eyebrow">{scopeLabel} · {formatDay(start, true)} to {formatDay(end, true)}</div>
              {summary?.avg_per_day != null ? (
                <div className="hero">
                  <span className="hero-number hero-proportional">{fmt(Math.round(summary.avg_per_day))}</span>
                  <span className="hero-unit">packets a day</span>
                </div>
              ) : (
                <div className="hero" aria-hidden="true"><span className="skeleton-bar skeleton-hero" /></div>
              )}
              {change != null && (
                <p className="meta-line">
                  <span className="num-inline">{fmtSignedPct(change)}</span> vs the previous {daysBetween(summary.prev_start, summary.prev_end) + 1} days
                  <span className="sep">·</span>
                  <span className="num-inline">{fmt(Math.round(summary.prev_avg_per_day))}</span> a day then
                </p>
              )}
              {summary && (
                <div className="stats">
                  <div className="stat">
                    <span className="stat-name">Total packets</span>
                    <span className="stat-number">{fmt(summary.total)}</span>
                    <span className="stat-meta">{summary.days_with_sales} days of sales</span>
                  </div>
                  <div className="stat">
                    <span className="stat-name">From subscriptions</span>
                    <span className="stat-number">{summary.subscription_share != null ? fmtPct(summary.subscription_share) : "-"}</span>
                    <span className="stat-meta">the rest are one-time orders</span>
                  </div>
                  <div className="stat">
                    <span className="stat-name">Forecast error</span>
                    <span className="stat-number">{summary.error_pct != null ? fmtPct(summary.error_pct) : "-"}</span>
                    <span className="stat-meta">{summary.compared_days ? `over ${summary.compared_days} issued days` : "no issued forecasts here"}</span>
                  </div>
                  <div className="stat">
                    <span className="stat-name">Forecast vs actual</span>
                    <span className="stat-number">{summary.bias_pct != null ? fmtSignedPct(summary.bias_pct) : "-"}</span>
                    <span className="stat-meta">
                      {summary.bias_pct == null ? "nothing to compare" : summary.bias_pct >= 0 ? "forecast was higher" : "forecast was lower"}
                    </span>
                  </div>
                </div>
              )}
            </section>

            {notes.length > 0 && (
              <section className="panel notes" aria-labelledby="notes-title">
                <h2 id="notes-title" className="section-label">What changed</h2>
                <ul>
                  {notes.map((note) => (
                    <li key={note.key} className={note.tone ? `note-${note.tone}` : ""}>{note.text}</li>
                  ))}
                </ul>
              </section>
            )}

            {data && (
              <section className="panel chart-panel" aria-labelledby="sales-title">
                <div className="chart-head">
                  <h2 id="sales-title" className="chart-title">
                    {perDay ? `Sales a day, by ${groupWord}` : "Sales by day"}
                  </h2>
                  <ul className="legend">
                    <li><span className="legend-box legend-subscription" aria-hidden="true" />Subscriptions</li>
                    <li><span className="legend-box legend-once" aria-hidden="true" />One-time orders</li>
                    {showForecast && <li><span className="legend-line" aria-hidden="true" />Issued forecast</li>}
                    {periods.some((p) => p.majorFestival) && <li><span className="legend-dot" aria-hidden="true" />Major festival</li>}
                  </ul>
                </div>
                {perDay && <p className="chart-note">Each bar is the average day in that {groupWord}, so short {groupWord}s at the edges compare fairly. Switch to Day to see the issued forecast line.</p>}
                <SalesChart
                  periods={periods}
                  perDay={perDay}
                  showForecast={showForecast}
                  labelFor={(p) => p.label}
                  describe={`Sales ${perDay ? `a day by ${groupWord}` : "by day"} for ${scopeLabel}, split into subscriptions and one-time orders`}
                />
              </section>
            )}

            {data && (
              <section className="panel chart-panel" aria-labelledby="bias-title">
                <div className="chart-head">
                  <h2 id="bias-title" className="chart-title">Issued forecast vs actual sales</h2>
                  <ul className="legend">
                    <li><span className="legend-box legend-high" aria-hidden="true" />Forecast too high</li>
                    <li><span className="legend-box legend-low" aria-hidden="true" />Forecast too low</li>
                  </ul>
                </div>
                {hasBias ? (
                  <BiasChart
                    periods={periods}
                    labelFor={(p) => p.label}
                    describe={`How far the issued forecast was from actual sales for ${scopeLabel}, by ${groupWord}`}
                  />
                ) : (
                  <p className="chart-empty">
                    No issued forecasts in this period{data.meta.issued_from ? `. They start ${formatDay(data.meta.issued_from, true)}` : ""}.
                  </p>
                )}
              </section>
            )}

            {data && weekdays.some((d) => d.vsAverage != null) && (
              <section className="panel chart-panel" aria-labelledby="weekday-title">
                <div className="chart-head">
                  <h2 id="weekday-title" className="chart-title">Weekday pattern</h2>
                  <span className="chart-subtitle">Each weekday vs the average day, days with no sales left out</span>
                </div>
                <WeekdayChart weekdays={weekdays} describe={`Average sales on each weekday compared with the average day for ${scopeLabel}`} />
              </section>
            )}

            {data && data.breakdown.length > 0 && (
              <section className="panel" aria-labelledby="breakdown-title">
                <div className="chart-head">
                  <h2 id="breakdown-title" className="chart-title">By {data.breakdown_by}</h2>
                  <span className="chart-subtitle">Average a day, compared with the {daysBetween(summary.prev_start, summary.prev_end) + 1} days before</span>
                </div>
                <table className="table">
                  <thead>
                    <tr>
                      <th scope="col">{data.breakdown_by === "city" ? "City" : "Product"}</th>
                      <th scope="col" className="num">A day</th>
                      <th scope="col" className="num col-diff">Before</th>
                      <th scope="col" className="num">Change</th>
                      <th scope="col" className="num col-diff">Subscriptions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.breakdown.map((row) => {
                      const rowChange = pctChange(row.avg_per_day, row.prev_avg_per_day);
                      return (
                        <tr key={row.key} className="item-row">
                          <td>{breakdownName(row.key)}</td>
                          <td className="num num-strong">{fmt(Math.round(row.avg_per_day))}</td>
                          <td className="num col-diff">{row.prev_avg_per_day != null ? fmt(Math.round(row.prev_avg_per_day)) : "-"}</td>
                          <td className="num">{rowChange != null ? fmtSignedPct(rowChange) : "new"}</td>
                          <td className="num col-diff">{row.subscription_share != null ? fmtPct(row.subscription_share) : "-"}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </section>
            )}

            {data && (
              <details className="panel data-table">
                <summary>
                  <span className="chart-title">All numbers by {groupWord}</span>
                  <button type="button" className="btn btn-secondary" onClick={(event) => { event.preventDefault(); exportCsv(); }}>
                    Download CSV
                  </button>
                </summary>
                <div className="table-scroll">
                  <table className="table">
                    <thead>
                      <tr>
                        <th scope="col">{group === "day" ? "Date" : group === "week" ? "Week of" : "Month"}</th>
                        <th scope="col" className="num">{perDay ? "Sales a day" : "Sales"}</th>
                        <th scope="col" className="num col-diff">Subscriptions</th>
                        <th scope="col" className="num col-diff">One-time</th>
                        {group === "day" && <th scope="col" className="num">Forecast</th>}
                        <th scope="col" className="num">vs actual</th>
                        <th scope="col" className="num col-diff">Error</th>
                      </tr>
                    </thead>
                    <tbody>
                      {[...periods].reverse().map((p) => (
                        <tr key={p.key} className="item-row">
                          <td>{group === "month" ? p.title : formatDay(p.first, true)}{p.majorFestival ? " · festival" : ""}</td>
                          <td className="num num-strong">{p.actual != null ? fmt(p.actual) : "-"}</td>
                          <td className="num col-diff">{p.subscription != null ? fmt(p.subscription) : "-"}</td>
                          <td className="num col-diff">{p.buyOnce != null ? fmt(p.buyOnce) : "-"}</td>
                          {group === "day" && <td className="num">{p.forecast != null ? fmt(p.forecast) : "-"}</td>}
                          <td className="num">{p.biasPct != null ? fmtSignedPct(p.biasPct) : "-"}</td>
                          <td className="num col-diff">{p.errorPct != null ? fmtPct(p.errorPct) : "-"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </details>
            )}
          </div>
        </main>
      </div>
    </div>
  );
}
