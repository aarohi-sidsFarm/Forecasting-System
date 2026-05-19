export default function KPICards({ summary, loading }) {
  const s = summary || {};
  const cards = [
    { label: 'Total 30-Day Units',  value: s.total_units?.toLocaleString(),  sub: `${s.forecast_from} → ${s.forecast_to}` },
    { label: 'Daily Average',       value: s.daily_avg?.toLocaleString(),    sub: 'units / day' },
    { label: 'Products Tracked',    value: s.products_count,                 sub: `across ${s.cities?.length || 0} cities` },
    { label: 'Subscription Units',  value: s.sub_units?.toLocaleString(),    sub: s.total_units ? `${(s.sub_units/s.total_units*100).toFixed(1)}% of total` : '' },
    { label: 'ML Forecast Units',   value: s.ml_units?.toLocaleString(),     sub: s.total_units ? `${(s.ml_units/s.total_units*100).toFixed(1)}% of total` : '' },
  ];
  return (
    <div style={{ display:'grid', gridTemplateColumns:'repeat(auto-fit,minmax(190px,1fr))', gap:16, marginBottom:24 }}>
      {cards.map(c => (
        <div key={c.label} style={card}>
          <div style={label}>{c.label}</div>
          <div style={value}>{loading ? '—' : (c.value ?? '—')}</div>
          <div style={sub}>{c.sub}</div>
        </div>
      ))}
    </div>
  );
}
const card  = { background:'#1a1d27', border:'1px solid #2a2d3e', borderRadius:12, padding:'20px 24px' };
const label = { fontSize:'0.72rem', color:'#94a3b8', textTransform:'uppercase', letterSpacing:'0.06em', marginBottom:6 };
const value = { fontSize:'1.8rem', fontWeight:700 };
const sub   = { fontSize:'0.75rem', color:'#94a3b8', marginTop:4 };