import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { getOperationalForecast, getStatus } from "./api";
import "./App.css";

const CITY_NAMES = {
  HYD: "Hyderabad",
  VGA: "Vijayawada",
  BLR: "Bengaluru",
  PNQ: "Pune",
};

// Order of cities on screen and in shared text.
const CITY_ORDER = ["HYD", "BLR", "PNQ", "VGA"];

// Sales history older than this many days gets a stronger notice.
const STALE_DATA_WARN_DAYS = 7;

// Forecasts are issued nightly at this IST time (D-2 / D-3 cutoff).
const ISSUE_TIME = "22:05";
const ISSUE_TIME_LABEL = "10:05 PM";

const fmt = (value) => Number(value ?? 0).toLocaleString("en-IN");
const fmtSigned = (value) => `${Number(value) > 0 ? "+" : ""}${fmt(value)}`;
const fmtPct = (value) => `${Number(value ?? 0).toFixed(1)}%`;
const cityName = (city) => CITY_NAMES[city] ?? city;
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

const daysBetween = (fromIso, toIso) => Math.round(
  (new Date(`${toIso}T12:00:00+05:30`) - new Date(`${fromIso}T12:00:00+05:30`)) / 86400000,
);

// One date format everywhere: "Mon, 26 Oct" (year only where it matters).
const formatDate = (iso, withYear = false) => {
  const parts = new Intl.DateTimeFormat("en-IN", {
    weekday: "short",
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "Asia/Kolkata",
  }).formatToParts(new Date(`${iso}T12:00:00+05:30`));
  const part = (type) => parts.find((p) => p.type === type)?.value;
  return `${part("weekday")}, ${part("day")} ${part("month")}${withYear ? ` ${part("year")}` : ""}`;
};

const lockTime = (issueDate) => new Date(`${issueDate}T${ISSUE_TIME}:00+05:30`).getTime();

const csvCell = (value) => {
  const text = String(value ?? "");
  return /[",\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
};

const isFrozen = (row) => ["official_issued", "legacy_issued", "archived_export"].includes(row.forecast_status)
  || Boolean(row.forecast_run_id);

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

const listNames = (cities) => {
  const names = cities.map(cityName);
  return names.length > 1 ? `${names.slice(0, -1).join(", ")} and ${names.at(-1)}` : names[0];
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
// A free Render server takes about a minute to wake up or redeploy.
const WAKE_RETRY_MS = 8000;
const MAX_WAKE_RETRIES = 15;

function StatusDot({ tone }) {
  return <span className={`dot dot-${tone}`} aria-hidden="true" />;
}

function SkeletonRows({ count = 6, columns = 2 }) {
  return Array.from({ length: count }, (_, row) => (
    <tr key={row} className="skeleton-row" aria-hidden="true">
      {Array.from({ length: columns }, (__, column) => (
        <td key={column} className={column ? "num" : ""}>
          <span className="skeleton-bar" style={{ width: column ? 56 : 120 + ((row * 37) % 80) }} />
        </td>
      ))}
    </tr>
  ));
}

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
  const [waking, setWaking] = useState(false);
  const [now, setNow] = useState(() => Date.now());
  const [cityFilter, setCityFilter] = useState("All");
  const [search, setSearch] = useState("");
  const [collapsed, setCollapsed] = useState(() => new Set());
  const [menuOpen, setMenuOpen] = useState(false);
  const [toast, setToast] = useState("");
  const retryTimerRef = useRef(null);
  const toastTimerRef = useRef(null);
  const requestIdRef = useRef(0);
  const loadRef = useRef(() => {});
  const menuRef = useRef(null);

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
      setWaking(false);
    }
    fetchDashboard(targetDate)
      .then(({ forecast, status }) => {
        if (requestIdRef.current !== requestId) return;
        setData(forecast);
        if (status) setSystemStatus(status);
        setError("");
        setPreparingSince(null);
        setWaking(false);
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
        if (err.code === "unreachable" && attempt < MAX_WAKE_RETRIES) {
          setWaking(true);
          retryTimerRef.current = setTimeout(() => loadRef.current(attempt + 1), WAKE_RETRY_MS);
          return;
        }
        setPreparingSince(null);
        setWaking(false);
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

  // Keeps the waiting time and "locks at" status current.
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), preparingSince ? 1000 : 30000);
    return () => clearInterval(timer);
  }, [preparingSince]);

  useEffect(() => {
    if (!menuOpen) return undefined;
    const close = (event) => {
      if (event.type === "keydown" ? event.key === "Escape" : !menuRef.current?.contains(event.target)) {
        setMenuOpen(false);
      }
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", close);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", close);
    };
  }, [menuOpen]);

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

  // Status, shown once. Cities lock separately (HYD/VGA at D-2, BLR/PNQ at D-3).
  const forecastView = data?.meta?.forecast_view ?? "live_preview";
  const draftGroups = cityGroups.filter((group) => !group.final);
  const pendingLocks = draftGroups
    .filter((group) => group.issueDate && lockTime(group.issueDate) > now)
    .map((group) => group.issueDate)
    .sort();
  const nextLock = pendingLocks[0];
  let status = null;
  if (data && cityGroups.length) {
    if (!draftGroups.length) {
      status = {
        tone: "issued",
        label: "Issued",
        detail: forecastView === "archived_export" ? "from the saved archive" : "locked at the cutoff and will not change",
      };
    } else if (forecastView === "stale_preview") {
      status = { tone: "draft", label: "Draft", detail: "based on the last saved orders, as the latest could not be loaded" };
    } else if (draftGroups.length < cityGroups.length) {
      status = {
        tone: "draft",
        label: "Partly issued",
        detail: nextLock
          ? `${listNames(draftGroups.map((group) => group.city))} lock ${formatDate(nextLock)} at ${ISSUE_TIME_LABEL}`
          : `${listNames(draftGroups.map((group) => group.city))} were not issued at the cutoff`,
      };
    } else {
      status = {
        tone: "draft",
        label: "Draft",
        detail: nextLock
          ? `locks ${formatDate(nextLock)} at ${ISSUE_TIME_LABEL}`
          : "was not issued at the cutoff, so these numbers are a recalculation",
      };
    }
  }
  const statusLabel = status?.label ?? "Draft";

  const availabilityWarning = data?.meta?.availability_warning ?? "";
  const freshness = data?.meta?.training_data_freshness ?? {};
  const syncedDate = freshness.max_training_date;
  const syncedAgeDays = syncedDate ? daysBetween(syncedDate, today) : 0;
  const showFreshness = Boolean(syncedDate) && (freshness.is_stale || syncedAgeDays > STALE_DATA_WARN_DAYS);
  const freshnessStrong = syncedAgeDays > STALE_DATA_WARN_DAYS;

  const festivals = (systemStatus?.festival_calendar?.upcoming_events ?? [])
    .filter((event) => event.date >= shiftDate(targetDate, -3))
    .slice(0, 8);
  const waitedSeconds = preparingSince ? Math.max(0, Math.floor((now - preparingSince) / 1000)) : 0;
  const busy = !data && !error && (loading || waking || Boolean(preparingSince));

  const shareUrl = () => {
    const url = new URL(window.location);
    url.search = "";
    url.searchParams.set("target", targetDate);
    return url.toString();
  };

  const shareText = () => {
    const lines = [`*Order forecast for ${formatDate(targetDate, true)}*`, `Status: ${statusLabel}`, ""];
    for (const group of visibleGroups) {
      const groupTotal = group.shownRows.reduce((sum, row) => sum + Number(row.forecast_quantity), 0);
      lines.push(`*${cityName(group.city)}: ${fmt(groupTotal)}*${group.final ? "" : " (draft)"}`);
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
    notify(await copyText(shareText()) ? "Copied. Paste it into Google Chat or email." : "Couldn't copy. Try again.");
  };

  const copyLink = async () => {
    notify(await copyText(shareUrl()) ? "Link copied" : "Couldn't copy the link. Try again.");
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
      ["Status", (row) => (isFrozen(row) ? "Issued" : "Draft")],
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

  const runMenuAction = (action) => {
    setMenuOpen(false);
    action();
  };

  const toggleGroup = (city) => {
    setCollapsed((current) => {
      const next = new Set(current);
      if (next.has(city)) next.delete(city);
      else next.add(city);
      return next;
    });
  };

  const quickDates = [
    ["Today", today],
    ["Tomorrow", shiftDate(today, 1)],
    ["Day after", shiftDate(today, 2)],
  ];
  const hasRows = visibleRows.length > 0;
  const columnCount = comparisonAvailable ? 5 : 2;

  return (
    <div className="app">
      <header className="header">
        <div className="header-inner">
          <div className="brand">
            <img className="brand-logo" src="/apple-touch-icon.png" alt="Sid's Farm" width="28" height="28" />
            <span className="brand-title">Order Forecasting</span>
          </div>
          <nav className="date-nav" aria-label="Delivery date">
            <div className="segmented" role="group" aria-label="Quick dates">
              {quickDates.map(([label, date]) => (
                <button
                  key={label}
                  type="button"
                  className="segment"
                  aria-pressed={targetDate === date}
                  onClick={() => changeDate(date)}
                >
                  {label}
                </button>
              ))}
            </div>
            <div className="stepper" role="group" aria-label="Pick a date">
              <button type="button" className="stepper-btn" aria-label="Previous day" onClick={() => changeDate(shiftDate(targetDate, -1))}>
                <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><path d="M10 3 5 8l5 5" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" /></svg>
              </button>
              <input
                type="date"
                className="stepper-input"
                aria-label="Delivery date"
                value={targetDate}
                onChange={(event) => changeDate(event.target.value)}
              />
              <button type="button" className="stepper-btn" aria-label="Next day" onClick={() => changeDate(shiftDate(targetDate, 1))}>
                <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><path d="m6 3 5 5-5 5" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" /></svg>
              </button>
            </div>
          </nav>
        </div>
      </header>

      <div className="layout">
        <main className="content">
          <section className="summary" aria-live="polite">
            <div className="eyebrow">Delivery · {formatDate(targetDate, true)}</div>
            {data ? (
              <div className="hero">
                <span className="hero-number">{fmt(filtered ? visibleTotal : grandTotal)}</span>
                <span className="hero-unit">packets{filtered ? " shown" : ""}</span>
              </div>
            ) : (
              <div className="hero" aria-hidden="true"><span className="skeleton-bar skeleton-hero" /></div>
            )}

            {status && (
              <p className="status-line">
                <StatusDot tone={status.tone} />
                <span className="status-label">{status.label}</span>{" "}
                <span className="status-detail">· {status.detail}</span>
              </p>
            )}
            {comparisonAvailable && comparedRows.length > 0 && (
              <p className="meta-line">
                Actual <span className="num-inline">{fmt(actualTotal)}</span>
                <span className="sep">·</span>
                <span className="num-inline">{fmtSigned(differenceTotal)}</span> vs forecast
                <span className="sep">·</span>
                <span className="num-inline">{fmtPct(errorPct)}</span> error
              </p>
            )}

            {waking && !error && (
              <p className="meta-line">Connecting to the server. This takes about a minute after a quiet period.</p>
            )}
            {preparingSince && !error && (
              <p className="meta-line">
                Calculating this forecast from the latest orders. This can take up to 15 minutes; the page updates by itself.
                <span className="num-inline waited"> {Math.floor(waitedSeconds / 60)}:{String(waitedSeconds % 60).padStart(2, "0")}</span>
              </p>
            )}
            {error && (
              <div className="callout callout-error" role="alert">
                <StatusDot tone="error" />
                <span title={error}>Couldn&apos;t load the forecast. Check your connection and try again.</span>
                <button type="button" className="btn btn-ghost" onClick={() => load()}>Try again</button>
              </div>
            )}

            {data && cityGroups.length > 0 && (
              <div className="stats" role="group" aria-label="Totals by city">
                {cityGroups.map((group) => (
                  <button
                    type="button"
                    key={group.city}
                    className="stat"
                    aria-pressed={cityFilter === group.city}
                    onClick={() => setCityFilter(cityFilter === group.city ? "All" : group.city)}
                  >
                    <span className="stat-name">{cityName(group.city)}</span>
                    <span className="stat-number">{fmt(group.total)}</span>
                    <span className="stat-meta">
                      {group.rows.length} products ·{" "}
                      {group.final
                        ? (group.issueDate ? `issued ${formatDate(group.issueDate)}` : "issued")
                        : (group.issueDate && lockTime(group.issueDate) > now
                          ? `locks ${formatDate(group.issueDate)}`
                          : "draft")}
                    </span>
                  </button>
                ))}
              </div>
            )}
            {busy && !data && (
              <div className="stats" aria-hidden="true">
                {[0, 1, 2, 3].map((key) => (
                  <div key={key} className="stat">
                    <span className="skeleton-bar" style={{ width: 72 }} />
                    <span className="skeleton-bar skeleton-stat" />
                    <span className="skeleton-bar" style={{ width: 120 }} />
                  </div>
                ))}
              </div>
            )}

            {showFreshness && (
              freshnessStrong ? (
                <div className="callout callout-draft">
                  <StatusDot tone="draft" />
                  <span>
                    Sales data last synced {formatDate(syncedDate)}, {syncedAgeDays} days ago.
                    Forecasts may drift until it is refreshed.
                  </span>
                </div>
              ) : (
                <p className="meta-line">
                  <StatusDot tone="draft" />
                  Sales data last synced {formatDate(syncedDate)}. Forecasts may drift until refreshed.
                </p>
              )
            )}
            {availabilityWarning && (
              <p className="meta-line"><StatusDot tone="draft" />{availabilityWarning}</p>
            )}
          </section>

          <section className="panel" aria-label="Products by city">
            <div className="toolbar">
              <div className="search">
                <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><circle cx="7" cy="7" r="4.5" fill="none" stroke="currentColor" strokeWidth="1.5" /><path d="m10.5 10.5 3 3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" /></svg>
                <input
                  type="search"
                  placeholder="Search product or city"
                  aria-label="Search product or city"
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                />
              </div>
              {filtered && (
                <button type="button" className="btn btn-ghost" onClick={() => { setCityFilter("All"); setSearch(""); }}>
                  Clear filter
                </button>
              )}
              <div className="toolbar-actions">
                <button type="button" className="btn btn-primary" onClick={copySummary} disabled={!hasRows}>
                  Copy
                </button>
                <div className="menu" ref={menuRef}>
                  <button
                    type="button"
                    className="btn btn-secondary"
                    aria-haspopup="menu"
                    aria-expanded={menuOpen}
                    onClick={() => setMenuOpen((open) => !open)}
                  >
                    More
                    <svg viewBox="0 0 16 16" width="12" height="12" aria-hidden="true"><path d="m4 6 4 4 4-4" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" /></svg>
                  </button>
                  {menuOpen && (
                    <div className="menu-list" role="menu">
                      {canShare && (
                        <button type="button" role="menuitem" disabled={!hasRows} onClick={() => runMenuAction(shareNative)}>Share</button>
                      )}
                      <button type="button" role="menuitem" disabled={!hasRows} onClick={() => runMenuAction(downloadCsv)}>Download CSV</button>
                      <button type="button" role="menuitem" onClick={() => runMenuAction(copyLink)}>Copy link</button>
                    </div>
                  )}
                </div>
              </div>
            </div>

            <table className="table">
              <thead>
                <tr>
                  <th scope="col">Product</th>
                  <th scope="col" className="num">Forecast</th>
                  {comparisonAvailable && <th scope="col" className="num">Actual</th>}
                  {comparisonAvailable && <th scope="col" className="num col-diff">Difference</th>}
                  {comparisonAvailable && <th scope="col" className="num">Error</th>}
                </tr>
              </thead>
              {busy || (error && !data) ? (
                <tbody><SkeletonRows columns={columnCount} /></tbody>
              ) : !hasRows ? (
                <tbody>
                  <tr>
                    <td colSpan={columnCount} className="empty">
                      {rows.length
                        ? <>No products match &ldquo;{search}&rdquo;.</>
                        : "No forecast for this date."}
                    </td>
                  </tr>
                </tbody>
              ) : visibleGroups.map((group) => {
                const isCollapsed = collapsed.has(group.city) && !query;
                const groupTotal = group.shownRows.reduce((sum, row) => sum + Number(row.forecast_quantity), 0);
                return (
                  <tbody key={group.city}>
                    <tr className="group-row">
                      <th scope="rowgroup">
                        <button
                          type="button"
                          className="group-toggle"
                          aria-expanded={!isCollapsed}
                          onClick={() => toggleGroup(group.city)}
                        >
                          <svg className="chevron" viewBox="0 0 16 16" width="12" height="12" aria-hidden="true"><path d="m4 6 4 4 4-4" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" /></svg>
                          {cityName(group.city)}
                        </button>
                      </th>
                      <td className="num">{fmt(groupTotal)}</td>
                      {comparisonAvailable && <td className="num">{group.compared ? fmt(group.actual) : "-"}</td>}
                      {comparisonAvailable && <td className="num col-diff">{group.compared ? fmtSigned(group.difference) : "-"}</td>}
                      {comparisonAvailable && <td className="num">{group.errorPct != null ? fmtPct(group.errorPct) : "-"}</td>}
                    </tr>
                    {!isCollapsed && group.shownRows.map((row) => (
                      <tr key={`${group.city}-${row.product_name}`} className="item-row">
                        <td className="product">{row.product_name}</td>
                        <td className="num num-strong">{fmt(row.forecast_quantity)}</td>
                        {comparisonAvailable && <td className="num">{row.actual_available ? fmt(row.actual_quantity) : "-"}</td>}
                        {comparisonAvailable && <td className="num col-diff">{row.actual_available ? fmtSigned(row.difference) : "-"}</td>}
                        {comparisonAvailable && <td className="num">{row.actual_available ? fmtPct(row.absolute_error_pct) : "-"}</td>}
                      </tr>
                    ))}
                  </tbody>
                );
              })}
            </table>
          </section>
        </main>

        {festivals.length > 0 && (
          <aside className="sidebar" aria-labelledby="festivals-title">
            <h2 id="festivals-title" className="section-label">Festivals</h2>
            <ul className="festivals">
              {festivals.map((event) => {
                const onDate = event.date === targetDate;
                return (
                  <li key={`${event.date}-${event.festival}-${event.cities}`} className={onDate ? "on-date" : ""}>
                    <span className="festival-date">{formatDate(event.date)}</span>
                    <span className="festival-name">
                      {event.festival}
                      {onDate && <span className="visually-hidden"> (on this delivery date)</span>}
                    </span>
                    <span className="festival-cities">
                      {event.cities === "ALL" ? "All cities" : event.cities.split(",").map((c) => cityName(c.trim())).join(", ")}
                    </span>
                  </li>
                );
              })}
            </ul>
          </aside>
        )}
      </div>

      {toast && <div className="toast" role="status">{toast}</div>}
    </div>
  );
}
