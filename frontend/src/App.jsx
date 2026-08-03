import { useState, useEffect, useCallback } from "react";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, Legend, Cell,
  ComposedChart,
} from "recharts";
import { getForecastDay, getForecastTrend, API_BASE } from "./api";
import "./App.css";

const CITY_COLORS = {
  BLR: "#818cf8",
  HYD: "#34d399",
  PNQ: "#fbbf24",
  VGA: "#f87171",
  UNKNOWN: "#64748b",
};

const CITY_NAMES = {
  BLR: "Bengaluru",
  HYD: "Hyderabad",
  PNQ: "Pune",
  VGA: "Vijayawada",
};

const getColor = (city) => CITY_COLORS[city] ?? "#818cf8";
const getCityName = (city) => CITY_NAMES[city] ?? city;
const fmt = (n) => Number(n ?? 0).toLocaleString("en-IN");

const tomorrow = () => {
  const d = new Date();
  d.setDate(d.getDate() + 1);
  return d.toISOString().slice(0, 10);
};

const getDateLabel = (dateStr) => {
  const today = new Date().toISOString().slice(0, 10);
  const diff = Math.round(
    (new Date(dateStr) - new Date(today)) / (1000 * 60 * 60 * 24)
  );
  if (diff < -1)  return { label: `${Math.abs(diff)}d ago`, color: "#64748b" };
  if (diff === -1) return { label: "Yesterday",             color: "#64748b" };
  if (diff === 0)  return { label: "Today",                 color: "#34d399" };
  if (diff === 1)  return { label: "Tomorrow",              color: "#818cf8" };
  if (diff <= 7)   return { label: `D+${diff}`,             color: "#a78bfa" };
  return             { label: `D+${diff}`,                  color: "#fbbf24" };
};

const QUICK_DATES = [
  ["D-1",  -1],
  ["Today", 0],
  ["D+1", +1],
  ["D+7", +7],
  ["D+14", +14],
  ["D+30", +30],
];

const CustomTip = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null;
  return (
    <div style={{
      background: "#ffffff", border: "1px solid #e2e5ec",
      borderRadius: 8, padding: "10px 14px", fontSize: 12,
      boxShadow: "0 4px 16px rgba(0,0,0,0.1)",
    }}>
      <div style={{ fontWeight: 700, marginBottom: 6, color: "#1a1d26" }}>{label}</div>
      {payload.map((p, i) => (
        <div key={i} style={{ color: p.color ?? "#6366f1", marginTop: 2 }}>
          {p.name}: <strong>{fmt(p.value)}</strong>
        </div>
      ))}
    </div>
  );
};

export default function App() {
  const getInitialDate = () => {
    const params = new URLSearchParams(window.location.search);
    return params.get("date") || tomorrow();
  };

  const [data, setData]           = useState(null);
  const [trend, setTrend]         = useState([]);
  const [loading, setLoading]     = useState(true);
  const [error, setError]         = useState(null);
  const [activeTab, setTab]       = useState("overview");
  const [cityFilter, setCity]     = useState("All");
  const [prodFilter, setProd]     = useState("All");
  const [currentPage, setCurrentPage] = useState(1);
  const [showComponents, setShowComponents] = useState(false);
  const ROWS_PER_PAGE = 20;
  const [selectedDate, _setDate]  = useState(getInitialDate());
  const [trendDays, setTrendDays] = useState(14);

  const setDate = (d) => {
    setData(null);
    _setDate(d);
    const url = new URL(window.location);
    url.searchParams.set("date", d);
    window.history.replaceState({}, "", url);
  };

  const loadData = useCallback(async (dt) => {
    setLoading(true);
    setError(null);
    try {
      const res = await getForecastDay(dt, false, "issued");
      setData(res);
    } catch (e) {
      if (e.message.includes("404")) {
        setError(
          `No forecast cached for ${dt}. The backend will compute it on the fly - try again in a moment.`
        );
      } else {
        setError(`Could not reach backend: ${e.message}`);
      }
      setData(null);
    } finally {
      setLoading(false);
    }
  }, []);

  const loadTrend = useCallback(async () => {
    try {
      const res = await getForecastTrend(trendDays);
      setTrend(res.trend || []);
    } catch {
    }
  }, [trendDays]);

  useEffect(() => {
    loadData(selectedDate);
    loadTrend();
  }, [selectedDate, trendDays, loadData, loadTrend]);

  const cities   = [...new Set((data?.product_breakdown ?? []).map(r => r.city))].sort();
  const products = [...new Set((data?.product_breakdown ?? []).map(r => r.product_name))].sort();

  const EXCLUDED_PRODUCTS = [
    "abhi eggs gold+",
    "assorted pack of 3 breakfast cereals",
    "both choco ragi",
    "honey and fruit museli",
    "just laid eggs",
    "both mango millets",
  ];
  const filteredProductOptions = products.filter(
    p => !EXCLUDED_PRODUCTS.includes(p.toLowerCase())
  );

  const filteredProducts = (data?.product_breakdown ?? []).filter(r => {
    if (cityFilter !== "All" && r.city !== cityFilter) return false;
    if (prodFilter !== "All" && r.product_name !== prodFilter) return false;
    return true;
  });

  const paginatedProducts = filteredProducts.slice(
    (currentPage - 1) * ROWS_PER_PAGE,
    currentPage * ROWS_PER_PAGE
  );
  const totalPages = Math.ceil(filteredProducts.length / ROWS_PER_PAGE);

  useEffect(() => {
    setCurrentPage(1);
  }, [cityFilter, prodFilter]);

  const topProducts = (data?.product_breakdown ?? [])
    .reduce((acc, r) => {
      const ex = acc.find(x => x.product_name === r.product_name);
      if (ex) {
        ex.total_orders   += r.total_orders;
        ex.total_quantity += r.total_quantity;
      } else {
        acc.push({
          product_name:   r.product_name,
          total_orders:   r.total_orders,
          total_quantity: r.total_quantity,
        });
      }
      return acc;
    }, [])
    .sort((a, b) => b.total_quantity - a.total_quantity)
    .slice(0, 10);

  const citySummary = data?.city_summary ?? [];
  const meta        = data?.meta ?? {};
  const totalQty    = meta.total_quantity ?? 0;
  const mlUnknownQty = meta.ml_unknown_adhoc_qty ?? meta.ml_qty;
  const isActualMode = meta.display_mode === "actual";

  const statusLabel = (row) => {
    if (!isActualMode) return "Forecast";
    const pct = Number(row.forecast_abs_error_pct ?? 0);
    if (pct <= 1) return "On target";
    if (pct <= 3) return "Watch";
    return "High variance";
  };

  const statusStyle = (row) => {
    const label = statusLabel(row);
    if (label === "On target") return { background: "#dcfce7", color: "#16a34a" };
    if (label === "Watch") return { background: "#fef3c7", color: "#d97706" };
    if (label === "High variance") return { background: "#fee2e2", color: "#dc2626" };
    return { background: "#e0e7ff", color: "#4338ca" };
  };

  if (loading && !data) {
    return (
      <div className="app">
        <div className="loading-screen">
          <img 
            src="https://media0.giphy.com/media/v1.Y2lkPTc5MGI3NjExNHU3aWE2NXVqbWdwODMxMHp1N2UyYm5qcGhtdDFiOXVxZGVvYjY5ayZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/M452ElhGUd3byc4HYw/giphy.gif" 
            alt="Loading..." 
            style={{ width: "150px", height: "auto", marginBottom: "20px", borderRadius: "12px" }}
          />
          <div className="loading-text">Delivering good quality milk to each one of you takes time. Please stay calm and patient, everyone.</div>
        </div>
      </div>
    );
  }

  return (
    <div className="app">

      {/* HEADER */}
      <header className="header">
        <div className="header-left">
          <div className="logo">S</div>
          <div>
            <div className="header-title">Sid's Farm Model</div>
            <div className="header-subtitle">LGBM + Subscription Model</div>
          </div>
        </div>

        <div className="header-controls">
          {QUICK_DATES.map(([label, offset]) => {
            const d = new Date();
            d.setDate(d.getDate() + offset);
            const val = d.toISOString().slice(0, 10);
            return (
              <button
                key={label}
                className={`btn ${selectedDate === val ? "active" : ""}`}
                onClick={() => setDate(val)}
              >
                {label}
              </button>
            );
          })}

          <div className="divider-v" />

          <input
            type="date"
            className="date-input"
            value={selectedDate}
            onChange={e => setDate(e.target.value)}
          />

          {(() => {
            const { label, color } = getDateLabel(selectedDate);
            return <span className="date-badge" style={{ color }}>{label}</span>;
          })()}

          <div className="divider-v" />

          <button
            className="btn btn-export"
            onClick={() => window.open(`${API_BASE}/export/milk_city_forecast.csv?date=${selectedDate}&days=7&refresh=true`, "_blank")}
          >
            Export
          </button>

          <span className="live-badge">
            {data?.meta?.forecast_view === "issued" ? "ISSUED" : "LIVE"}
          </span>
        </div>
      </header>

      {/* MAIN CONTENT */}
      <main className="main">

        {/* Error banner */}
        {error && (
          <div className="error-banner fade-in">
            <strong>{error}</strong>
            <div style={{ marginTop: 4, fontSize: 12, opacity: 0.8 }}>
              Ensure backend is running: <code>uvicorn main:app --reload --port 8000</code>
            </div>
          </div>
        )}

        {/* KEY METRICS */}
        <div className="metrics-row">
          <div className="metric-card fade-in stagger-1" style={{"--accent-color": "#818cf8"}}>
            <div className="metric-label">{isActualMode ? "Actual Demand" : "Total Forecast"}</div>
            <div className="metric-value" style={{ color: "#818cf8" }}>{fmt(totalQty)}</div>
            <div className="metric-sub">
              units for {meta.order_date ?? selectedDate}
              {isActualMode && (
                <span className="metric-sub-pill" style={{ background: "#e0f2fe", color: "#0369a1" }}>
                  D2C actual
                </span>
              )}
            </div>
          </div>

          <div className="metric-card fade-in stagger-2">
            <div className="metric-label">Subscription</div>
            <div className="metric-value" style={{ color: "#34d399" }}>
              {meta.subscription_pct != null ? `${meta.subscription_pct}%` : "-"}
            </div>
            <div className="metric-sub">
              {meta.subscription_qty != null ? `${fmt(meta.subscription_qty)} units` : "-"}
              <span className="metric-sub-pill" style={{ background: "#dcfce7", color: "#16a34a" }}>
                subs
              </span>
            </div>
          </div>

          <div className="metric-card fade-in stagger-3">
            <div className="metric-label">Known Buy Once</div>
            <div className="metric-value" style={{ color: "#fbbf24" }}>
              {meta.known_buy_once_qty != null ? fmt(meta.known_buy_once_qty) : "-"}
            </div>
            <div className="metric-sub">
              already placed
              <span className="metric-sub-pill" style={{ background: "#fef3c7", color: "#d97706" }}>
                orders
              </span>
            </div>
          </div>

          <div className="metric-card fade-in stagger-4">
            <div className="metric-label">{isActualMode ? "Forecast Error" : "ML Procurement Gap"}</div>
            <div className="metric-value" style={{ color: "#a78bfa" }}>
              {isActualMode ? fmt(meta.forecast_error_qty) : (mlUnknownQty != null ? fmt(mlUnknownQty) : "-")}
            </div>
            <div className="metric-sub">
              {isActualMode ? `${meta.forecast_abs_error_pct ?? 0}% abs error` : "above live known"}
              <span className="metric-sub-pill" style={{ background: "#ede9fe", color: "#7c3aed" }}>
                {isActualMode ? "actual check" : "LGBM"}
              </span>
            </div>
          </div>

          <div className="metric-card fade-in stagger-4">
            <div className="metric-label">Coverage</div>
            <div className="metric-value" style={{ color: "#f87171" }}>
              {meta.total_cities ?? "-"} <span style={{ fontSize: 14, color: "#7a8099", fontWeight: 500 }}>cities</span>{" "}
              · {meta.total_products ?? "-"} <span style={{ fontSize: 14, color: "#7a8099", fontWeight: 500 }}>SKUs</span>
            </div>
            <div className="metric-sub">active products across all cities</div>
          </div>
        </div>

        {/* CITY BREAKDOWN */}
        {citySummary.length > 0 && (
          <div
            className="city-grid fade-in"
            style={{ gridTemplateColumns: `repeat(${citySummary.length}, 1fr)` }}
          >
            {citySummary.map(c => {
              const pct = totalQty > 0 ? ((c.total_quantity / totalQty) * 100).toFixed(1) : 0;
              return (
                <div
                  key={c.city}
                  className="city-card"
                  style={{ borderLeftColor: getColor(c.city) }}
                >
                  <div>
                    <div className="city-name" style={{ color: getColor(c.city) }}>
                      {getCityName(c.city)}
                    </div>
                    <div className="city-detail">
                      {c.products_count} products
                    </div>
                  </div>
                  <div>
                    <div className="city-qty" style={{ color: getColor(c.city) }}>
                      {fmt(c.total_quantity)}
                    </div>
                    <div className="city-pct">{pct}% of total</div>
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {/* No data state */}
        {!loading && !data && !error && (
          <div className="card empty-state fade-in">
            <div className="empty-icon">No data</div>
            No forecast data for <strong>{selectedDate}</strong>.
            Try a different date or check that the backend is running.
          </div>
        )}

        {data && (
          <>
            {/* TABS */}
            <div className="tabs">
              {[
                ["overview", "Products"],
                ["charts",   "Charts"],
                ["trend",    "Trend"],
              ].map(([k, l]) => (
                <button
                  key={k}
                  className={`tab ${activeTab === k ? "active" : ""}`}
                  onClick={() => setTab(k)}
                >
                  {l}
                </button>
              ))}
            </div>

            {/* TAB: PRODUCTS TABLE */}
            {activeTab === "overview" && (
              <div className="card fade-in">
                <div className="card-title">
                  <span>Forecast by Product</span>
                  <div className="card-title-right">
                    <select
                      className="select"
                      value={cityFilter}
                      onChange={e => setCity(e.target.value)}
                    >
                      <option value="All">All Cities</option>
                      {cities.map(c => (
                        <option key={c} value={c}>{getCityName(c)}</option>
                      ))}
                    </select>
                    <select
                      className="select"
                      value={prodFilter}
                      onChange={e => setProd(e.target.value)}
                    >
                      <option value="All">All Products</option>
                      {filteredProductOptions.map(p => (
                        <option key={p} value={p}>{p}</option>
                      ))}
                    </select>
                    <span className="row-count">{filteredProducts.length} rows</span>
                    <button
                      className={`btn ${showComponents ? "active" : ""}`}
                      onClick={() => setShowComponents(v => !v)}
                    >
                      Details
                    </button>
                  </div>
                </div>

                <div className="table-wrap">
                  <table className="table">
                    <thead>
                      <tr>
                        <th>City</th>
                        <th>Product</th>
                        <th>Status</th>
                        <th style={{ textAlign: "right" }}>Forecast</th>
                        {isActualMode && <th style={{ textAlign: "right" }}>Actual</th>}
                        {showComponents && <th style={{ textAlign: "right" }}>Subs</th>}
                        {showComponents && <th style={{ textAlign: "right" }}>Known</th>}
                        {showComponents && <th style={{ textAlign: "right" }}>ML Gap</th>}
                      </tr>
                    </thead>
                    <tbody>
                      {filteredProducts.length === 0 ? (
                        <tr>
                          <td colSpan={(isActualMode ? 5 : 4) + (showComponents ? 3 : 0)} className="empty-state">
                            No rows match your filters.
                          </td>
                        </tr>
                      ) : (
                        paginatedProducts.map((r, i) => (
                          <tr key={`${selectedDate}-${r.city}-${r.product_name}-${i}`}>
                            <td>
                              <span className="city-dot" style={{ background: getColor(r.city) }} />
                              {getCityName(r.city)}
                            </td>
                            <td className="product-name">{r.product_name}</td>
                            <td>
                              <span style={{
                                fontSize: 10, fontWeight: 700, padding: "2px 8px",
                                borderRadius: 4, ...statusStyle(r)
                              }}>
                                {statusLabel(r)}
                              </span>
                            </td>
                            <td className="qty-value" style={{ textAlign: "right" }}>
                              {fmt(r.forecast_quantity ?? r.total_quantity)}
                            </td>
                            {isActualMode && (
                              <td className="qty-value" style={{ textAlign: "right" }}>
                                {fmt(r.actual_quantity ?? r.total_quantity)}
                              </td>
                            )}
                            {showComponents && (
                              <td style={{ textAlign: "right", color: "#4a5068" }}>
                                {fmt(r.subscription_qty)}
                              </td>
                            )}
                            {showComponents && (
                              <td style={{ textAlign: "right", color: "#4a5068" }}>
                                {fmt(r.known_buy_once_qty)}
                              </td>
                            )}
                            {showComponents && (
                              <td style={{ textAlign: "right", color: "#4a5068" }}>
                                {fmt(r.ml_unknown_adhoc_qty)}
                              </td>
                            )}
                          </tr>
                        ))
                      )}
                    </tbody>
                  </table>
                </div>

                {totalPages > 1 && (
                  <div className="pagination-controls" style={{ display: 'flex', justifyContent: 'center', gap: '16px', padding: '16px', borderTop: '1px solid #e2e5ec', background: '#fafbfc', borderRadius: '0 0 12px 12px' }}>
                    <button 
                      className="btn" 
                      disabled={currentPage === 1} 
                      onClick={() => setCurrentPage(p => p - 1)}>
                      Prev
                    </button>
                    <span style={{ display: 'flex', alignItems: 'center', fontSize: '13px', color: '#5c6379', fontWeight: 500 }}>
                      Page {currentPage} of {totalPages}
                    </span>
                    <button 
                      className="btn" 
                      disabled={currentPage === totalPages} 
                      onClick={() => setCurrentPage(p => p + 1)}>
                      Next
                    </button>
                  </div>
                )}
              </div>
            )}

            {/* TAB: CHARTS */}
            {activeTab === "charts" && (
              <>
                <div className="two-col">
                  <div className="card fade-in stagger-1">
                    <div className="card-title">Units by City</div>
                    <ResponsiveContainer width="100%" height={240}>
                      <BarChart
                        data={citySummary}
                        margin={{ top: 4, right: 16, left: 0, bottom: 4 }}
                      >
                        <CartesianGrid strokeDasharray="3 3" stroke="#e2e5ec" />
                        <XAxis
                          dataKey="city"
                          tick={{ fontSize: 12, fill: "#8b92a5" }}
                          tickFormatter={getCityName}
                        />
                        <YAxis tick={{ fontSize: 11, fill: "#5c6379" }} tickFormatter={fmt} />
                        <Tooltip content={<CustomTip />} />
                        <Bar dataKey="total_quantity" name="Units" radius={[6, 6, 0, 0]}>
                          {citySummary.map((c, i) => (
                            <Cell key={i} fill={getColor(c.city)} />
                          ))}
                        </Bar>
                      </BarChart>
                    </ResponsiveContainer>
                  </div>

                  <div className="card fade-in stagger-2">
                    <div className="card-title">Orders by City</div>
                    <ResponsiveContainer width="100%" height={240}>
                      <BarChart
                        data={citySummary}
                        margin={{ top: 4, right: 16, left: 0, bottom: 4 }}
                      >
                        <CartesianGrid strokeDasharray="3 3" stroke="#e2e5ec" />
                        <XAxis
                          dataKey="city"
                          tick={{ fontSize: 12, fill: "#8b92a5" }}
                          tickFormatter={getCityName}
                        />
                        <YAxis tick={{ fontSize: 11, fill: "#5c6379" }} tickFormatter={fmt} />
                        <Tooltip content={<CustomTip />} />
                        <Bar dataKey="total_orders" name="Orders" radius={[6, 6, 0, 0]}>
                          {citySummary.map((c, i) => (
                            <Cell key={i} fill={getColor(c.city)} />
                          ))}
                        </Bar>
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                </div>

                <div className="card fade-in stagger-3">
                  <div className="card-title">Top 10 Products by Forecast</div>
                  <ResponsiveContainer width="100%" height={topProducts.length * 38 + 32}>
                    <BarChart
                      layout="vertical"
                      data={topProducts}
                      margin={{ top: 4, right: 32, left: 140, bottom: 4 }}
                    >
                      <CartesianGrid strokeDasharray="3 3" stroke="#e2e5ec" />
                      <XAxis type="number" tick={{ fontSize: 11, fill: "#5c6379" }} tickFormatter={fmt} />
                      <YAxis
                        type="category"
                        dataKey="product_name"
                        tick={{ fontSize: 12, fill: "#8b92a5" }}
                        width={135}
                      />
                      <Tooltip content={<CustomTip />} />
                      <Bar
                        dataKey="total_quantity"
                        name="Forecast Units"
                        fill="#818cf8"
                        radius={[0, 6, 6, 0]}
                      />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </>
            )}

            {/* TAB: TREND */}
            {activeTab === "trend" && (
              <div className="card fade-in">
                <div className="card-title">
                  <span>Demand Trend</span>
                  <select
                    className="select"
                    value={trendDays}
                    onChange={e => setTrendDays(Number(e.target.value))}
                  >
                    {[7, 14, 30].map(d => (
                      <option key={d} value={d}>Next {d} days</option>
                    ))}
                  </select>
                </div>

                {trend.length === 0 ? (
                  <div className="empty-state">
                    <div className="empty-icon">No data</div>
                    No trend data yet. The backend will populate this after the first forecast run.
                  </div>
                ) : (
                  <>
                    <div className="trend-summary">
                      <span>
                        <strong>{trend.length}</strong> days
                      </span>
                      <span>
                        <strong>{trend[0]?.date}</strong> to <strong>{trend[trend.length - 1]?.date}</strong>
                      </span>
                      <span>
                        Total: <strong style={{ color: "#818cf8" }}>
                          {fmt(trend.reduce((s, r) => s + (r.total_quantity ?? 0), 0))}
                        </strong> units
                      </span>
                    </div>

                    <ResponsiveContainer width="100%" height={280}>
                      <ComposedChart
                        data={trend}
                        margin={{ top: 4, right: 16, left: 0, bottom: 4 }}
                      >
                        <CartesianGrid strokeDasharray="3 3" stroke="#e2e5ec" />
                        <XAxis dataKey="date" tick={{ fontSize: 11, fill: "#5c6379" }} />
                        <YAxis tick={{ fontSize: 11, fill: "#5c6379" }} tickFormatter={fmt} />
                        <Tooltip content={<CustomTip />} />
                        <Legend
                          wrapperStyle={{ fontSize: 12, color: "#8b92a5" }}
                        />
                        <Bar
                          dataKey="total_quantity"
                          name="Forecast units"
                          fill="#818cf8"
                          radius={[4, 4, 0, 0]}
                          fillOpacity={0.85}
                        />
                      </ComposedChart>
                    </ResponsiveContainer>
                  </>
                )}
              </div>
            )}
          </>
        )}

        {/* Footer */}
        <footer className="footer">
          Sid's Farm Forecasting - Built by Aarohi
        </footer>
      </main>
    </div>
  );
}

