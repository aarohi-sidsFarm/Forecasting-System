import { useCallback, useEffect, useMemo, useState } from "react";
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

export default function App() {
  const params = new URLSearchParams(window.location.search);
  const initialDate = params.get("target") || params.get("as_of") || todayInIndia();
  const [targetDate, setTargetDate] = useState(initialDate);
  const [data, setData] = useState(null);
  const [systemStatus, setSystemStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [cityFilter, setCityFilter] = useState("All");
  const [productFilter, setProductFilter] = useState("All");
  const [search, setSearch] = useState("");
  const [showComponents, setShowComponents] = useState(false);
  const [copied, setCopied] = useState(false);

  const load = useCallback(async (refresh = false) => {
    setLoading(true);
    setError("");
    try {
      const { forecast, status } = await fetchDashboard(targetDate, refresh);
      setData(forecast);
      setSystemStatus(status);
    } catch (err) {
      setError(`Could not load the operational forecast: ${err.message}`);
    } finally {
      setLoading(false);
    }
  }, [targetDate]);

  useEffect(() => {
    const url = new URL(window.location);
    url.searchParams.delete("as_of");
    url.searchParams.set("target", targetDate);
    window.history.replaceState({}, "", url);
    let active = true;
    fetchDashboard(targetDate, false)
      .then(({ forecast, status }) => {
        if (!active) return;
        setData(forecast);
        setSystemStatus(status);
        setError("");
      })
      .catch((err) => {
        if (active) setError(`Could not load the operational forecast: ${err.message}`);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => { active = false; };
  }, [targetDate]);

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
  const modelGap = filteredRows.reduce((sum, row) => sum + Number(row.ml_unknown_adhoc_qty), 0);
  const citySummary = data?.city_summary ?? [];
  const upcomingEvents = systemStatus?.festival_calendar?.upcoming_events ?? [];
  const freshness = data?.meta?.training_data_freshness ?? {};

  const resetFilters = () => {
    setCityFilter("All");
    setProductFilter("All");
    setSearch("");
  };

  const downloadFilteredCsv = () => {
    const columns = [
      "issue_date", "forecast_date", "lead_time_days", "city", "product_name",
      "subscription_qty", "known_buy_once_qty", "ml_unknown_adhoc_qty", "forecast_quantity",
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
      `Filtered total: ${fmt(filteredTotal)} packets`,
      "",
      ...filteredRows.map((row) => (
        `${row.forecast_date} | ${row.city} | ${row.product_name} | ${fmt(row.forecast_quantity)}`
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
            <div className="header-title">Sid&apos;s Farm Forecast Desk</div>
            <div className="header-subtitle">City-aware procurement plan</div>
          </div>
        </div>
        <div className="header-controls">
          <label className="date-control">
            <span>Target date</span>
            <input
              type="date"
              className="date-input"
              value={targetDate}
              onChange={(event) => setTargetDate(event.target.value)}
            />
          </label>
          <button className="btn header-action" onClick={() => load(true)} disabled={loading}>
            {loading ? "Refreshing..." : "Refresh"}
          </button>
          <button className="btn btn-export header-action" onClick={downloadFilteredCsv} disabled={!filteredRows.length}>
            Download filtered CSV
          </button>
          <button className="btn btn-primary header-action" onClick={copyShareSummary} disabled={!filteredRows.length}>
            {copied ? "Copied" : "Copy to share"}
          </button>
          <span className="live-badge">
            {data?.meta?.forecast_view === "issued" ? "ISSUED" : "LIVE"}
          </span>
        </div>
      </header>

      <main className="main">
        {error && <div className="error-banner"><strong>{error}</strong></div>}

        <section className="metrics-row compact-metrics">
          <div className="metric-card">
            <div className="metric-label">Filtered forecast</div>
            <div className="metric-value">{fmt(filteredTotal)}</div>
            <div className="metric-sub">packets across {filteredRows.length} rows</div>
          </div>
          <div className="metric-card">
            <div className="metric-label">Visible demand</div>
            <div className="metric-value green">{fmt(visibleDemand)}</div>
            <div className="metric-sub">subscriptions + placed buy-once</div>
          </div>
          <div className="metric-card">
            <div className="metric-label">Model gap</div>
            <div className="metric-value violet">{fmt(modelGap)}</div>
            <div className="metric-sub">unknown ad-hoc demand</div>
          </div>
          <div className="metric-card">
            <div className="metric-label">Training freshness</div>
            <div className="metric-value small-value">{freshness.max_training_date ?? "-"}</div>
            <div className="metric-sub">{freshness.is_stale ? "Refresh required" : "Data check passed"}</div>
          </div>
        </section>

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
                <div className="city-detail">D-{summary.lead_time_days} · issue {prettyDate(summary.issue_date)}</div>
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
                  {showComponents && <th className="numeric">Subscription</th>}
                  {showComponents && <th className="numeric">Placed buy-once</th>}
                  {showComponents && <th className="numeric">Model gap</th>}
                  <th className="numeric">Final forecast</th>
                </tr>
              </thead>
              <tbody>
                {!filteredRows.length ? (
                  <tr><td colSpan={showComponents ? 8 : 5} className="empty-state">No rows match these filters.</td></tr>
                ) : filteredRows.map((row) => (
                  <tr key={`${row.forecast_date}-${row.city}-${row.product_name}`}>
                    <td><strong>{prettyDate(row.forecast_date)}</strong></td>
                    <td><span className="city-dot" style={{ background: cityColor(row.city) }} />{cityName(row.city)}</td>
                    <td className="product-name">{row.product_name}</td>
                    <td><span className="lead-badge">D-{row.lead_time_days}</span></td>
                    {showComponents && <td className="numeric">{fmt(row.subscription_qty)}</td>}
                    {showComponents && <td className="numeric">{fmt(row.known_buy_once_qty)}</td>}
                    {showComponents && <td className="numeric">{fmt(row.ml_unknown_adhoc_qty)}</td>}
                    <td className="qty-value numeric">{fmt(row.forecast_quantity)}</td>
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
