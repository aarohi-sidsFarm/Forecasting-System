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

const fmt = (value) => Number(value ?? 0).toLocaleString("en-IN");
const fmtSigned = (value) => `${Number(value) > 0 ? "+" : ""}${fmt(value)}`;
const fmtPct = (value) => `${Number(value ?? 0).toFixed(2)}%`;
const cityName = (city) => CITY_NAMES[city] ?? city;
const cityColor = (city) => CITY_COLORS[city] ?? "#74787D";

const todayInIndia = () => new Intl.DateTimeFormat("en-CA", {
  timeZone: "Asia/Kolkata",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
}).format(new Date());

const prettyDate = (date) => new Intl.DateTimeFormat("en-IN", {
  weekday: "short",
  day: "2-digit",
  month: "short",
  year: "numeric",
  timeZone: "Asia/Kolkata",
}).format(new Date(`${date}T12:00:00+05:30`));

const csvCell = (value) => {
  const text = String(value ?? "");
  return /[",\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
};

const fetchDashboard = async (targetDate, refresh) => {
  const [forecast, status] = await Promise.all([
    getOperationalForecast(targetDate, refresh),
    getStatus(),
  ]);
  return { forecast, status };
};

const RETRY_INTERVAL_MS = 15000;
const MAX_LOAD_RETRIES = 20;

export default function App() {
  const params = new URLSearchParams(window.location.search);
  const initialDate = params.get("target") || params.get("as_of") || todayInIndia();
  const [targetDate, setTargetDate] = useState(initialDate);
  const [data, setData] = useState(null);
  const [systemStatus, setSystemStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [refreshing, setRefreshing] = useState(false);
  const retryTimerRef = useRef(null);
  const requestIdRef = useRef(0);
  const loadRef = useRef(() => {});
  const [cityFilter, setCityFilter] = useState("All");
  const [productFilter, setProductFilter] = useState("All");
  const [search, setSearch] = useState("");
  const [showComponents, setShowComponents] = useState(false);
  const [copied, setCopied] = useState(false);

  const load = useCallback((refresh = false, attempt = 0) => {
    if (retryTimerRef.current) {
      clearTimeout(retryTimerRef.current);
      retryTimerRef.current = null;
    }
    const requestId = attempt === 0 ? ++requestIdRef.current : requestIdRef.current;
    if (attempt === 0) {
      setLoading(true);
      setError("");
      setRefreshing(false);
    }
    fetchDashboard(targetDate, refresh)
      .then(({ forecast, status }) => {
        if (requestIdRef.current !== requestId) return;
        setData(forecast);
        setSystemStatus(status);
        setError("");
        setRefreshing(false);
        setLoading(false);
      })
      .catch((err) => {
        if (requestIdRef.current !== requestId) return;
        if (err.code === "refresh_in_progress" && attempt < MAX_LOAD_RETRIES) {
          // Forecast for this date isn't saved yet and is still being rebuilt
          // live from Redash (can take a few minutes). Keep whatever is
          // already on screen and quietly retry instead of showing an error.
          setRefreshing(true);
          setLoading(false);
          retryTimerRef.current = setTimeout(() => loadRef.current(refresh, attempt + 1), RETRY_INTERVAL_MS);
          return;
        }
        setRefreshing(false);
        setLoading(false);
        setError(`Could not load the operational forecast: ${err.message}`);
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
    Promise.resolve().then(() => load(false));
    return () => {
      if (retryTimerRef.current) {
        clearTimeout(retryTimerRef.current);
        retryTimerRef.current = null;
      }
    };
  }, [load, targetDate]);

  const rows = useMemo(() => data?.rows ?? [], [data]);
  const cities = useMemo(() => [...new Set(rows.map((row) => row.city))].sort(), [rows]);
  const products = useMemo(() => [...new Set(rows.map((row) => row.product_name))].sort(), [rows]);
  const filteredRows = useMemo(() => rows.filter((row) => {
    if (cityFilter !== "All" && row.city !== cityFilter) return false;
    if (productFilter !== "All" && row.product_name !== productFilter) return false;
    if (search && !`${row.city} ${row.product_name}`.toLowerCase().includes(search.toLowerCase())) return false;
    return true;
  }), [rows, cityFilter, productFilter, search]);

  const filteredTotal = filteredRows.reduce((sum, row) => sum + Number(row.forecast_quantity), 0);
  const visibleDemand = filteredRows.reduce(
    (sum, row) => sum + Number(row.subscription_qty) + Number(row.known_buy_once_qty),
    0,
  );
  const remainingModelGap = (row) => Number(
    row.remaining_model_gap_qty ?? row.ml_unknown_adhoc_qty ?? 0,
  );
  const modelGap = filteredRows.reduce((sum, row) => sum + remainingModelGap(row), 0);
  const comparisonAvailable = Boolean(data?.meta?.comparison?.available);
  const comparedRows = comparisonAvailable
    ? filteredRows.filter((row) => row.actual_available)
    : [];
  const filteredActual = comparedRows.reduce((sum, row) => sum + Number(row.actual_quantity), 0);
  const filteredDifference = comparedRows.reduce((sum, row) => sum + Number(row.difference), 0);
  const filteredAbsError = comparedRows.reduce((sum, row) => sum + Math.abs(Number(row.difference)), 0);
  const filteredWape = filteredActual ? (100 * filteredAbsError) / filteredActual : 0;
  const citySummary = data?.city_summary ?? [];
  const upcomingEvents = systemStatus?.festival_calendar?.upcoming_events ?? [];
  const freshness = data?.meta?.training_data_freshness ?? {};
  const forecastView = data?.meta?.forecast_view ?? "live_preview";
  const availabilityWarning = data?.meta?.availability_warning ?? "";
  const comparisonNotEligible = data?.meta?.comparison_status === "not_eligible_preview";
  const forecastViewLabel = forecastView === "issued"
    ? "OFFICIAL"
    : forecastView === "mixed"
      ? "MIXED"
      : forecastView === "partial_issued"
        ? "PARTIAL"
        : forecastView === "archived_export"
          ? "ARCHIVE"
          : forecastView === "stale_preview" ? "STALE" : "PREVIEW";

  const resetFilters = () => {
    setCityFilter("All");
    setProductFilter("All");
    setSearch("");
  };

  const downloadFilteredCsv = () => {
    const columns = [
      "issue_date", "forecast_date", "lead_time_days", "city", "product_name",
      "subscription_qty", "confirmed_subscription_qty", "at_risk_subscription_qty",
      "known_buy_once_qty", "remaining_model_gap_qty", "forecast_quantity",
      "forecast_status", "forecast_run_id", "actual_quantity", "difference",
      "deviation_pct", "absolute_error_pct",
    ];
    const csv = [
      columns.join(","),
      ...filteredRows.map((row) => columns.map((column) => csvCell(row[column])).join(",")),
    ].join("\n");
    const href = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    const anchor = document.createElement("a");
    anchor.href = href;
    anchor.download = `forecast_for_${targetDate}.csv`;
    anchor.click();
    URL.revokeObjectURL(href);
  };

  const copyShareSummary = async () => {
    const lines = [
      `Procurement forecast for ${targetDate}`,
      `Issue dates calculated automatically (HYD/VGA D-2, BLR/PNQ D-3)`,
      `Forecast basis: ${forecastViewLabel}`,
      `Filtered total: ${fmt(filteredTotal)} packets`,
      ...(comparisonAvailable ? [
        `Query 1968 actual: ${fmt(filteredActual)} packets`,
        `Difference: ${fmtSigned(filteredDifference)} packets | WAPE: ${fmtPct(filteredWape)}`,
      ] : []),
      "",
      ...filteredRows.map((row) => (
        comparisonAvailable && row.actual_available
          ? `${row.forecast_date} | ${row.city} | ${row.product_name} | Forecast ${fmt(row.forecast_quantity)} | Actual ${fmt(row.actual_quantity)} | Absolute error ${fmtPct(row.absolute_error_pct)}`
          : `${row.forecast_date} | ${row.city} | ${row.product_name} | ${fmt(row.forecast_quantity)}`
      )),
    ];
    await navigator.clipboard.writeText(lines.join("\n"));
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1800);
  };

  return (
    <div className="app">
      <header className="header">
        <div className="header-left">
          <img className="brand-logo" src="/sids-farm-logo.png" alt="Sid's Farm" />
          <div>
            <div className="header-title">Sid's Farm Forecast</div>
            <div className="header-subtitle">City-level procurement plan</div>
          </div>
        </div>
        <div className="header-controls">
          <label className="date-control">
            <span>Target date</span>
            <input
              type="date"
              className="date-input"
              value={targetDate}
              onChange={(event) => {
                // Historical exports may contain fewer cities than the live
                // forecast; clear filters so a previously selected city does
                // not make a valid archived forecast appear empty.
                resetFilters();
                setTargetDate(event.target.value);
              }}
            />
          </label>
          <button className="btn header-action" onClick={() => load(true)} disabled={loading || refreshing}>
            {loading ? "Refreshing..." : refreshing ? "Preparing..." : "Refresh"}
          </button>
          <button className="btn btn-export header-action" onClick={downloadFilteredCsv} disabled={!filteredRows.length}>
            Download filtered CSV
          </button>
          <button className="btn btn-primary header-action" onClick={copyShareSummary} disabled={!filteredRows.length}>
            {copied ? "Copied" : "Copy to share"}
          </button>
          <span className="live-badge">
            {forecastViewLabel}
          </span>
        </div>
      </header>

      <main className="main">
        {error && <div className="error-banner"><strong>{error}</strong></div>}
        {!error && refreshing && (
          <div className="info-banner">Preparing forecast for this date — checking again shortly.</div>
        )}
        {availabilityWarning && (
          <div className="warning-banner"><strong>{availabilityWarning}</strong></div>
        )}

        <section className="metrics-row compact-metrics">
          <div className="metric-card">
            <div className="metric-label">Filtered forecast</div>
            <div className="metric-value">{fmt(filteredTotal)}</div>
            <div className="metric-sub">packets across {filteredRows.length} rows</div>
          </div>
          <div className="metric-card">
            <div className="metric-label">Expected known demand</div>
            <div className="metric-value green">{fmt(visibleDemand)}</div>
            <div className="metric-sub">confirmed subscription floor + cutoff buy-once</div>
          </div>
          <div className="metric-card">
            <div className="metric-label">Remaining model gap</div>
            <div className="metric-value violet">{fmt(modelGap)}</div>
            <div className="metric-sub">model total less visible confirmed demand</div>
          </div>
          <div className="metric-card">
            <div className="metric-label">Training freshness</div>
            <div className="metric-value small-value">{freshness.max_training_date ?? "-"}</div>
            <div className="metric-sub">{freshness.is_stale ? "Refresh required" : "Data check passed"}</div>
          </div>
        </section>

        {comparisonAvailable && (
          <section className="comparison-strip" aria-label="Query 1968 comparison summary">
            <div>
              <div className="metric-label">Query 1968 actual</div>
              <div className="comparison-value">{fmt(filteredActual)}</div>
            </div>
            <div>
              <div className="metric-label">Difference</div>
              <div className="comparison-value">{fmtSigned(filteredDifference)}</div>
            </div>
            <div>
              <div className="metric-label">WAPE</div>
              <div className="comparison-value">{fmtPct(filteredWape)}</div>
            </div>
            <div className="comparison-note">
              {comparedRows.length} matched rows - comparison uses the frozen D-2/D-3 forecast
            </div>
          </section>
        )}
        {comparisonNotEligible && (
          <div className="warning-banner">
            Accuracy is shown only for forecasts frozen at their D-2/D-3 issue time.
            This date has no complete issued forecast, so its preview would look
            more accurate than it really was.
          </div>
        )}

        <section className="city-grid operational-city-grid">
          {citySummary.map((summary) => (
            <button
              type="button"
              key={summary.city}
              className={`city-card city-filter-card ${cityFilter === summary.city ? "selected" : ""}`}
              style={{ borderLeftColor: cityColor(summary.city) }}
              onClick={() => setCityFilter(cityFilter === summary.city ? "All" : summary.city)}
            >
              <div>
                <div className="city-name" style={{ color: cityColor(summary.city) }}>{cityName(summary.city)}</div>
                <div className="city-detail">D-{summary.lead_time_days}{summary.issue_date ? ` - issue ${prettyDate(summary.issue_date)}` : " - archived"}</div>
              </div>
              <div>
                <div className="city-qty" style={{ color: cityColor(summary.city) }}>{fmt(summary.forecast_quantity)}</div>
                <div className="city-pct">{summary.products_count} SKUs</div>
              </div>
            </button>
          ))}
        </section>

        <section className="card forecast-workspace">
          <div className="workspace-heading">
            <h2>Procurement quantities</h2>
            <span className="result-count">{filteredRows.length} of {rows.length} rows</span>
          </div>

          <div className="filter-bar">
            <input
              className="search-input"
              type="search"
              placeholder="Search city or SKU"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
            />
            <select className="select" value={cityFilter} onChange={(event) => setCityFilter(event.target.value)}>
              <option value="All">All cities</option>
              {cities.map((city) => <option key={city} value={city}>{cityName(city)}</option>)}
            </select>
            <select className="select product-select" value={productFilter} onChange={(event) => setProductFilter(event.target.value)}>
              <option value="All">All SKUs</option>
              {products.map((product) => <option key={product} value={product}>{product}</option>)}
            </select>
            <button className={`btn ${showComponents ? "active" : ""}`} onClick={() => setShowComponents(!showComponents)}>
              {showComponents ? "Hide components" : "Show components"}
            </button>
            <button className="btn btn-quiet" onClick={resetFilters}>Reset</button>
          </div>

          <div className="table-wrap">
            <table className="table forecast-table">
              <thead>
                <tr>
                  <th>Target date</th>
                  <th>City</th>
                  <th>SKU</th>
                  <th>Lead</th>
                  {showComponents && <th className="numeric">Confirmed subs</th>}
                  {showComponents && <th className="numeric">Unconfirmed subs</th>}
                  {showComponents && <th className="numeric">Placed buy-once</th>}
                  {showComponents && <th className="numeric">Remaining model gap</th>}
                  <th className="numeric">Final forecast</th>
                  {comparisonAvailable && <th className="numeric">Actual · Q1968</th>}
                  {comparisonAvailable && <th className="numeric">Difference</th>}
                  {comparisonAvailable && <th className="numeric">Absolute error</th>}
                </tr>
              </thead>
              <tbody>
                {!filteredRows.length ? (
                  <tr><td colSpan={(showComponents ? 9 : 5) + (comparisonAvailable ? 3 : 0)} className="empty-state">No rows match these filters.</td></tr>
                ) : filteredRows.map((row) => (
                  <tr key={`${row.forecast_date}-${row.city}-${row.product_name}`}>
                    <td><strong>{prettyDate(row.forecast_date)}</strong></td>
                    <td><span className="city-dot" style={{ background: cityColor(row.city) }} />{cityName(row.city)}</td>
                    <td className="product-name">{row.product_name}</td>
                    <td><span className="lead-badge">D-{row.lead_time_days}</span></td>
                    {showComponents && <td className="numeric">{fmt(row.confirmed_subscription_qty)}</td>}
                    {showComponents && <td className="numeric">{fmt(row.at_risk_subscription_qty)}</td>}
                    {showComponents && <td className="numeric">{fmt(row.known_buy_once_qty)}</td>}
                    {showComponents && <td className="numeric">{fmt(remainingModelGap(row))}</td>}
                    <td className="qty-value numeric">{fmt(row.forecast_quantity)}</td>
                    {comparisonAvailable && <td className="numeric">{row.actual_available ? fmt(row.actual_quantity) : "-"}</td>}
                    {comparisonAvailable && <td className="numeric">{row.actual_available ? fmtSigned(row.difference) : "-"}</td>}
                    {comparisonAvailable && <td className="numeric">{row.actual_available ? fmtPct(row.absolute_error_pct) : "-"}</td>}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <section className="card festival-panel">
          <div className="workspace-heading">
            <h2>Upcoming festivals</h2>
            <span className="result-count">{systemStatus?.festival_calendar?.regional_rows ?? 0} regional rows</span>
          </div>
          <div className="festival-list">
            {upcomingEvents.slice(0, 8).map((event) => (
              <div className="festival-item" key={`${event.date}-${event.festival}-${event.cities}`}>
                <strong>{event.festival}</strong>
                <span>{prettyDate(event.date)}</span>
                <span>{event.cities === "ALL" ? "All cities" : event.cities}</span>
              </div>
            ))}
          </div>
        </section>

        <footer className="footer">
          Sid&apos;s Farm Forecasting
        </footer>
      </main>
    </div>
  );
}
