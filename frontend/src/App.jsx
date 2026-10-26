import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { getOperationalForecast, getStatus } from "./api";
import "./App.css";

const CITY_NAMES = {
  HYD: "Hyderabad",
  VGA: "Vijayawada",
  BLR: "Bengaluru",
  PNQ: "Pune",
};

const CITY_COLORS = {
  HYD: "#34A77B",
  VGA: "#E06C68",
  BLR: "#7075D8",
  PNQ: "#D99A2B",
};

// Delivery-order of cities on screen and in shared text.
const CITY_ORDER = ["HYD", "BLR", "PNQ", "VGA"];

const fmt = (value) => Number(value ?? 0).toLocaleString("en-IN");
const fmtSigned = (value) => `${Number(value) > 0 ? "+" : ""}${fmt(value)}`;
const fmtPct = (value) => `${Number(value ?? 0).toFixed(1)}%`;
const cityName = (city) => CITY_NAMES[city] ?? city;
const cityColor = (city) => CITY_COLORS[city] ?? "#74787D";
const cityRank = (city) => {
  const index = CITY_ORDER.indexOf(city);
  return index === -1 ? CITY_ORDER.length : index;
};

const isoInIndia = (date) => new Intl.DateTimeFormat("en-CA", {
  timeZone: "Asia/Kolkata",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
}).format(date);

const todayInIndia = () => isoInIndia(new Date());

const shiftDate = (iso, days) => {
  const date = new Date(`${iso}T12:00:00+05:30`);
  date.setUTCDate(date.getUTCDate() + days);
  return isoInIndia(date);
};

const prettyDate = (date) => new Intl.DateTimeFormat("en-IN", {
  weekday: "short",
  day: "numeric",
  month: "short",
  year: "numeric",
  timeZone: "Asia/Kolkata",
}).format(new Date(`${date}T12:00:00+05:30`));

const shortDate = (date) => new Intl.DateTimeFormat("en-IN", {
  weekday: "short",
  day: "numeric",
  month: "short",
  timeZone: "Asia/Kolkata",
}).format(new Date(`${date}T12:00:00+05:30`));

const csvCell = (value) => {
  const text = String(value ?? "");
  return /[",\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
};

const isFrozen = (row) => ["official_issued", "legacy_issued", "archived_export"].includes(row.forecast_status)
  || Boolean(row.forecast_run_id);

// Plain-language label for the whole page, with what it means for the reader.
const VIEW_LABELS = {
  issued: ["Final", "Issued at the D-2 / D-3 cutoff. These numbers will not change."],
  mixed: ["Partly final", "Some cities are issued and final; the rest are still a preview."],
  partial_issued: ["Partly final", "Some cities are issued and final; the rest are still a preview."],
  archived_export: ["Archive", "Saved forecast from before the dashboard kept issued history."],
  stale_preview: ["Preview (older data)", "Latest orders could not be loaded, so this uses the last saved inputs."],
  live_preview: ["Preview", "Not issued yet. Numbers can still change until the D-2 / D-3 cutoff at 22:05."],
};

const copyText = async (text) => {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    // Clipboard API is blocked in some embedded browsers; fall back to a
    // temporary textarea.
    const area = document.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    const ok = document.execCommand("copy");
    area.remove();
    return ok;
  }
};

const fetchDashboard = async (targetDate) => {
  const [forecast, status] = await Promise.all([
    getOperationalForecast(targetDate),
    getStatus().catch(() => null),
  ]);
  return { forecast, status };
};

const RETRY_INTERVAL_MS = 15000;
const MAX_LOAD_RETRIES = 80;

export default function App() {
  const params = new URLSearchParams(window.location.search);
  const today = todayInIndia();
  const initialDate = params.get("target") || params.get("as_of") || shiftDate(today, 1);
  const [targetDate, setTargetDate] = useState(initialDate);
  const [data, setData] = useState(null);
  const [systemStatus, setSystemStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [preparingSince, setPreparingSince] = useState(null);
  const [now, setNow] = useState(() => Date.now());
  const [cityFilter, setCityFilter] = useState("All");
  const [search, setSearch] = useState("");
  const [toast, setToast] = useState("");
  const retryTimerRef = useRef(null);
  const toastTimerRef = useRef(null);
  const requestIdRef = useRef(0);
  const loadRef = useRef(() => {});

  const load = useCallback((attempt = 0) => {
    if (retryTimerRef.current) {
      clearTimeout(retryTimerRef.current);
      retryTimerRef.current = null;
    }
    const requestId = attempt === 0 ? ++requestIdRef.current : requestIdRef.current;
    if (attempt === 0) {
      setLoading(true);
      setError("");
      setPreparingSince(null);
    }
    fetchDashboard(targetDate)
      .then(({ forecast, status }) => {
        if (requestIdRef.current !== requestId) return;
        setData(forecast);
        if (status) setSystemStatus(status);
        setError("");
        setPreparingSince(null);
        setLoading(false);
      })
      .catch((err) => {
        if (requestIdRef.current !== requestId) return;
        if (err.code === "refresh_in_progress" && attempt < MAX_LOAD_RETRIES) {
          // The forecast for this date is not issued yet and is being built
          // from Redash, which can take up to 15 minutes. Keep checking.
          setData(null);
          setPreparingSince((since) => since ?? Date.now());
          setLoading(false);
          retryTimerRef.current = setTimeout(() => loadRef.current(attempt + 1), RETRY_INTERVAL_MS);
          return;
        }
        setPreparingSince(null);
        setLoading(false);
        setError(err.message);
      });
  }, [targetDate]);

  useEffect(() => {
    loadRef.current = load;
  }, [load]);

  useEffect(() => {
    const url = new URL(window.location);
    url.searchParams.delete("as_of");
    url.searchParams.set("target", targetDate);
    window.history.replaceState({}, "", url);
    Promise.resolve().then(() => load());
    return () => {
      if (retryTimerRef.current) {
        clearTimeout(retryTimerRef.current);
        retryTimerRef.current = null;
      }
    };
  }, [load, targetDate]);

  useEffect(() => {
    if (!preparingSince) return undefined;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [preparingSince]);

  const changeDate = (next) => {
    if (!next || next === targetDate) return;
    // Another date may not have the same cities; a kept filter could make
    // a valid forecast look empty.
    setCityFilter("All");
    setSearch("");
    setData(null);
    setTargetDate(next);
  };

  const notify = (message) => {
    setToast(message);
    if (toastTimerRef.current) clearTimeout(toastTimerRef.current);
    toastTimerRef.current = setTimeout(() => setToast(""), 2200);
  };

  const rows = useMemo(() => data?.rows ?? [], [data]);
  const comparisonAvailable = Boolean(data?.meta?.comparison?.available);

  const cityGroups = useMemo(() => {
    const groups = new Map();
    for (const row of rows) {
      if (!groups.has(row.city)) groups.set(row.city, []);
      groups.get(row.city).push(row);
    }
    return [...groups.entries()]
      .sort(([a], [b]) => cityRank(a) - cityRank(b) || a.localeCompare(b))
      .map(([city, cityRows]) => {
        const sorted = [...cityRows].sort((a, b) => Number(b.forecast_quantity) - Number(a.forecast_quantity));
        const compared = sorted.filter((row) => row.actual_available);
        const actual = compared.reduce((sum, row) => sum + Number(row.actual_quantity), 0);
        const absError = compared.reduce((sum, row) => sum + Math.abs(Number(row.difference)), 0);
        return {
          city,
          rows: sorted,
          total: sorted.reduce((sum, row) => sum + Number(row.forecast_quantity), 0),
          leadDays: sorted[0]?.lead_time_days,
          issueDate: sorted[0]?.issue_date,
          final: sorted.every(isFrozen),
          actual,
          difference: compared.reduce((sum, row) => sum + Number(row.difference), 0),
          errorPct: actual ? (100 * absError) / actual : null,
          compared: compared.length,
        };
      });
  }, [rows]);

  const query = search.trim().toLowerCase();
  const visibleGroups = cityGroups
    .filter((group) => cityFilter === "All" || group.city === cityFilter)
    .map((group) => ({
      ...group,
      shownRows: query
        ? group.rows.filter((row) => `${cityName(group.city)} ${group.city} ${row.product_name}`.toLowerCase().includes(query))
        : group.rows,
    }))
    .filter((group) => group.shownRows.length);
  const visibleRows = visibleGroups.flatMap((group) => group.shownRows);
  const visibleTotal = visibleRows.reduce((sum, row) => sum + Number(row.forecast_quantity), 0);
  const grandTotal = cityGroups.reduce((sum, group) => sum + group.total, 0);
  const filtered = cityFilter !== "All" || Boolean(query);

  const comparedRows = comparisonAvailable ? visibleRows.filter((row) => row.actual_available) : [];
  const actualTotal = comparedRows.reduce((sum, row) => sum + Number(row.actual_quantity), 0);
  const differenceTotal = comparedRows.reduce((sum, row) => sum + Number(row.difference), 0);
  const absErrorTotal = comparedRows.reduce((sum, row) => sum + Math.abs(Number(row.difference)), 0);
  const errorPct = actualTotal ? (100 * absErrorTotal) / actualTotal : 0;

  const forecastView = data?.meta?.forecast_view ?? "live_preview";
  const [viewLabel, viewHelp] = VIEW_LABELS[forecastView] ?? VIEW_LABELS.live_preview;
  const availabilityWarning = data?.meta?.availability_warning ?? "";
  const freshness = data?.meta?.training_data_freshness ?? {};
  const upcomingEvents = (systemStatus?.festival_calendar?.upcoming_events ?? [])
    .filter((event) => event.date >= shiftDate(targetDate, -3))
    .slice(0, 6);
  const preparingFor = preparingSince ? Math.max(0, Math.floor((now - preparingSince) / 1000)) : 0;

  const shareUrl = () => {
    const url = new URL(window.location);
    url.search = "";
    url.searchParams.set("target", targetDate);
    return url.toString();
  };

  const shareText = () => {
    const lines = [`*Order forecast for ${prettyDate(targetDate)}*`, `Status: ${viewLabel}`, ""];
    for (const group of visibleGroups) {
      const groupTotal = group.shownRows.reduce((sum, row) => sum + Number(row.forecast_quantity), 0);
      lines.push(`*${cityName(group.city)}: ${fmt(groupTotal)}*${group.final ? "" : " (preview)"}`);
      for (const row of group.shownRows) {
        const actual = comparisonAvailable && row.actual_available
          ? ` (actual ${fmt(row.actual_quantity)})`
          : "";
        lines.push(`${row.product_name}: ${fmt(row.forecast_quantity)}${actual}`);
      }
      lines.push("");
    }
    lines.push(`*Total: ${fmt(visibleTotal)}*`);
    if (comparisonAvailable && comparedRows.length) {
      lines.push(`Actual: ${fmt(actualTotal)} | Difference: ${fmtSigned(differenceTotal)} | Error: ${fmtPct(errorPct)}`);
    }
    lines.push("", shareUrl());
    return lines.join("\n");
  };

  const copySummary = async () => {
    notify(await copyText(shareText()) ? "Copied. Paste it into WhatsApp or email." : "Could not copy. Try again.");
  };

  const copyLink = async () => {
    notify(await copyText(shareUrl()) ? "Link copied" : "Could not copy the link");
  };

  const canShare = typeof navigator !== "undefined" && typeof navigator.share === "function";
  const shareNative = async () => {
    try {
      await navigator.share({ title: `Order forecast ${targetDate}`, text: shareText() });
    } catch (err) {
      if (err?.name !== "AbortError") copySummary();
    }
  };

  const downloadCsv = () => {
    const columns = [
      ["Delivery date", (row) => row.forecast_date],
      ["City", (row) => cityName(row.city)],
      ["Product", (row) => row.product_name],
      ["Forecast quantity", (row) => row.forecast_quantity],
      ["Status", (row) => (isFrozen(row) ? "Final" : "Preview")],
      ["Issued on", (row) => row.issue_date ?? ""],
      ["Lead time (days)", (row) => row.lead_time_days],
      ["Confirmed subscriptions", (row) => row.confirmed_subscription_qty],
      ["Unconfirmed subscriptions", (row) => row.at_risk_subscription_qty],
      ["Buy-once orders placed", (row) => row.known_buy_once_qty],
      ["Model estimate of new orders", (row) => row.remaining_model_gap_qty ?? row.ml_unknown_adhoc_qty],
      ...(comparisonAvailable ? [
        ["Actual quantity", (row) => (row.actual_available ? row.actual_quantity : "")],
        ["Difference", (row) => (row.actual_available ? row.difference : "")],
        ["Error %", (row) => (row.actual_available ? Number(row.absolute_error_pct).toFixed(2) : "")],
      ] : []),
    ];
    const csv = [
      columns.map(([header]) => csvCell(header)).join(","),
      ...visibleRows.map((row) => columns.map(([, value]) => csvCell(value(row))).join(",")),
    ].join("\r\n");
    // The byte-order mark makes Excel read the file as UTF-8.
    const href = URL.createObjectURL(new Blob(["﻿", csv], { type: "text/csv;charset=utf-8" }));
    const anchor = document.createElement("a");
    anchor.href = href;
    anchor.download = `order_forecast_${targetDate}${cityFilter !== "All" ? `_${cityFilter}` : ""}.csv`;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    // Revoking straight away cancels the download in Firefox and Safari.
    setTimeout(() => URL.revokeObjectURL(href), 1000);
    notify("CSV downloaded");
  };

  const quickDates = [
    ["Today", today],
    ["Tomorrow", shiftDate(today, 1)],
    ["Day after", shiftDate(today, 2)],
  ];
  const hasRows = visibleRows.length > 0;

  return (
    <div className="app">
      <header className="header">
        <div className="header-left">
          <img className="brand-logo" src="/sids-farm-logo.png" alt="Sid's Farm" />
          <div>
            <div className="header-title">Order Forecasting</div>
            <div className="header-subtitle">Packets to plan per city and product</div>
          </div>
        </div>
        <div className="date-nav" role="group" aria-label="Delivery date">
          <div className="quick-dates">
            {quickDates.map(([label, date]) => (
              <button
                key={label}
                type="button"
                className={`chip ${targetDate === date ? "chip-active" : ""}`}
                onClick={() => changeDate(date)}
              >
                {label}
              </button>
            ))}
          </div>
          <div className="date-stepper">
            <button type="button" className="btn icon-btn" aria-label="Previous day" onClick={() => changeDate(shiftDate(targetDate, -1))}>‹</button>
            <input
              type="date"
              className="date-input"
              aria-label="Delivery date"
              value={targetDate}
              onChange={(event) => changeDate(event.target.value)}
            />
            <button type="button" className="btn icon-btn" aria-label="Next day" onClick={() => changeDate(shiftDate(targetDate, 1))}>›</button>
          </div>
        </div>
      </header>

      <main className="main">
        <section className="hero">
          <div>
            <div className="hero-label">Delivery on {prettyDate(targetDate)}</div>
            {data && (
              <div className="hero-total">
                {fmt(filtered ? visibleTotal : grandTotal)}
                <span className="hero-unit">packets{filtered ? " (filtered)" : ""}</span>
              </div>
            )}
          </div>
          {data && (
            <span className={`status-pill status-${forecastView}`} title={viewHelp}>{viewLabel}</span>
          )}
        </section>
        {data && <p className="status-help">{viewHelp}</p>}

        {error && (
          <div className="banner banner-error" role="alert">
            <div>
              <strong>The forecast could not be loaded.</strong>
              <div className="banner-detail">{error}</div>
            </div>
            <button type="button" className="btn" onClick={() => load()}>Try again</button>
          </div>
        )}
        {preparingSince && (
          <div className="banner banner-info" role="status">
            <span className="spinner" aria-hidden="true" />
            <div>
              <strong>Building this forecast from the latest orders.</strong>
              <div className="banner-detail">
                It has not been issued yet, so it is calculated now. This can take up to 15 minutes;
                the page updates by itself. Waiting {Math.floor(preparingFor / 60)}m {preparingFor % 60}s.
              </div>
            </div>
          </div>
        )}
        {loading && !data && !preparingSince && !error && (
          <div className="skeleton-grid" aria-label="Loading">
            {[0, 1, 2, 3].map((key) => <div key={key} className="skeleton" />)}
          </div>
        )}
        {availabilityWarning && <div className="banner banner-warning">{availabilityWarning}</div>}
        {freshness.is_stale && (
          <div className="banner banner-warning">
            Sales history last updated {freshness.max_training_date}. Forecasts may drift until it is refreshed.
          </div>
        )}

        {data && (
          <>
            <section className="city-grid">
              {cityGroups.map((group) => (
                <button
                  type="button"
                  key={group.city}
                  className={`city-card ${cityFilter === group.city ? "selected" : ""}`}
                  style={{ borderLeftColor: cityColor(group.city) }}
                  aria-pressed={cityFilter === group.city}
                  onClick={() => setCityFilter(cityFilter === group.city ? "All" : group.city)}
                >
                  <div className="city-card-top">
                    <span className="city-name" style={{ color: cityColor(group.city) }}>{cityName(group.city)}</span>
                    <span className={`mini-pill ${group.final ? "mini-final" : "mini-preview"}`}>
                      {group.final ? "Final" : "Preview"}
                    </span>
                  </div>
                  <div className="city-qty">{fmt(group.total)}</div>
                  <div className="city-detail">
                    {group.rows.length} products
                    {group.issueDate ? ` · issued ${shortDate(group.issueDate)}` : ""}
                    {group.leadDays != null ? ` (D-${group.leadDays})` : ""}
                  </div>
                  {group.errorPct != null && (
                    <div className="city-detail">Actual {fmt(group.actual)} · error {fmtPct(group.errorPct)}</div>
                  )}
                </button>
              ))}
            </section>

            {comparisonAvailable && comparedRows.length > 0 && (
              <section className="comparison-strip" aria-label="Forecast against actual sales">
                <div>
                  <div className="metric-label">Actual sold</div>
                  <div className="comparison-value">{fmt(actualTotal)}</div>
                </div>
                <div>
                  <div className="metric-label">Forecast minus actual</div>
                  <div className="comparison-value">{fmtSigned(differenceTotal)}</div>
                </div>
                <div>
                  <div className="metric-label">Error</div>
                  <div className="comparison-value">{fmtPct(errorPct)}</div>
                </div>
              </section>
            )}

            <section className="card workspace">
              <div className="toolbar">
                <input
                  className="search-input"
                  type="search"
                  placeholder="Search product or city"
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                />
                {filtered && (
                  <button type="button" className="btn btn-quiet" onClick={() => { setCityFilter("All"); setSearch(""); }}>
                    Show all cities
                  </button>
                )}
                <div className="toolbar-actions">
                  <button type="button" className="btn btn-primary" onClick={copySummary} disabled={!hasRows}>
                    Copy for WhatsApp
                  </button>
                  {canShare && (
                    <button type="button" className="btn" onClick={shareNative} disabled={!hasRows}>Share</button>
                  )}
                  <button type="button" className="btn" onClick={downloadCsv} disabled={!hasRows}>Download CSV</button>
                  <button type="button" className="btn" onClick={copyLink}>Copy link</button>
                </div>
              </div>

              <div className="table-wrap">
                <table className="table">
                  <thead>
                    <tr>
                      <th>Product</th>
                      <th className="numeric">Forecast</th>
                      {comparisonAvailable && <th className="numeric">Actual</th>}
                      {comparisonAvailable && <th className="numeric">Difference</th>}
                      {comparisonAvailable && <th className="numeric">Error</th>}
                    </tr>
                  </thead>
                  {!hasRows ? (
                    <tbody>
                      <tr>
                        <td colSpan={comparisonAvailable ? 5 : 2} className="empty-state">
                          {rows.length ? "No products match your search." : "No forecast for this date."}
                        </td>
                      </tr>
                    </tbody>
                  ) : visibleGroups.map((group) => (
                    <tbody key={group.city}>
                      <tr className="group-row">
                        <td>
                          <span className="city-dot" style={{ background: cityColor(group.city) }} />
                          {cityName(group.city)}
                          {!group.final && <span className="mini-pill mini-preview">Preview</span>}
                        </td>
                        <td className="numeric">{fmt(group.shownRows.reduce((sum, row) => sum + Number(row.forecast_quantity), 0))}</td>
                        {comparisonAvailable && <td className="numeric">{group.compared ? fmt(group.actual) : "-"}</td>}
                        {comparisonAvailable && <td className="numeric">{group.compared ? fmtSigned(group.difference) : "-"}</td>}
                        {comparisonAvailable && <td className="numeric">{group.errorPct != null ? fmtPct(group.errorPct) : "-"}</td>}
                      </tr>
                      {group.shownRows.map((row) => (
                        <tr key={`${group.city}-${row.product_name}`}>
                          <td className="product-name">{row.product_name}</td>
                          <td className="numeric qty-value">{fmt(row.forecast_quantity)}</td>
                          {comparisonAvailable && <td className="numeric">{row.actual_available ? fmt(row.actual_quantity) : "-"}</td>}
                          {comparisonAvailable && <td className="numeric">{row.actual_available ? fmtSigned(row.difference) : "-"}</td>}
                          {comparisonAvailable && <td className="numeric">{row.actual_available ? fmtPct(row.absolute_error_pct) : "-"}</td>}
                        </tr>
                      ))}
                    </tbody>
                  ))}
                </table>
              </div>
            </section>
          </>
        )}

        {upcomingEvents.length > 0 && (
          <section className="card festival-panel">
            <h2 className="panel-title">Festivals coming up</h2>
            <div className="festival-list">
              {upcomingEvents.map((event) => (
                <div
                  className={`festival-item ${event.date === targetDate ? "festival-today" : ""}`}
                  key={`${event.date}-${event.festival}-${event.cities}`}
                >
                  <strong>{event.festival}</strong>
                  <span>{shortDate(event.date)} · {event.cities === "ALL" ? "All cities" : event.cities}</span>
                </div>
              ))}
            </div>
          </section>
        )}

        <footer className="footer">Sid&apos;s Farm Order Forecasting</footer>
      </main>

      {toast && <div className="toast" role="status">{toast}</div>}
    </div>
  );
}
