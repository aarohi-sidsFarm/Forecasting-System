export default function Filters({ cities, filters, onChange }) {
  const sel = { background:'#0f1117', color:'#e2e8f0', border:'1px solid #2a2d3e', borderRadius:8, padding:'8px 12px', fontSize:'0.85rem' };
  return (
    <div style={{ display:'flex', gap:16, flexWrap:'wrap', background:'#1a1d27', border:'1px solid #2a2d3e', borderRadius:12, padding:'16px 20px', marginBottom:24 }}>
      <div>
        <div style={{ fontSize:'0.72rem', color:'#94a3b8', marginBottom:4 }}>City</div>
        <select style={sel} value={filters.city} onChange={e => onChange('city', e.target.value)}>
          <option value="">All Cities</option>
          {cities.map(c => <option key={c} value={c}>{c}</option>)}
        </select>
      </div>
      <div>
        <div style={{ fontSize:'0.72rem', color:'#94a3b8', marginBottom:4 }}>Method</div>
        <select style={sel} value={filters.method} onChange={e => onChange('method', e.target.value)}>
          <option value="">All Methods</option>
          <option value="subscription">Subscription</option>
          <option value="lgbm">LGBM Global</option>
          <option value="lgbm_hyd">LGBM HYD</option>
          <option value="rolling_avg">Rolling Avg</option>
        </select>
      </div>
    </div>
  );
}