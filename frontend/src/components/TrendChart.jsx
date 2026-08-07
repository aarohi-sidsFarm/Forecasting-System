import { LineChart, Line, XAxis, YAxis, Tooltip, Legend, ResponsiveContainer, CartesianGrid } from 'recharts';

const CITY_COLORS = { BLR:'#7075D8', HYD:'#34A77B', PNQ:'#D99A2B', VGA:'#E06C68' };

export default function TrendChart({ data }) {
  if (!data?.length) return <div style={{ color:'#64748b', textAlign:'center', paddingTop:80 }}>No data</div>;

  // Pivot: { date, BLR:x, HYD:x, ... }
  const pivot = {};
  data.forEach(r => {
    if (!pivot[r.forecast_date]) pivot[r.forecast_date] = { date: r.forecast_date };
    pivot[r.forecast_date][r.city_cd] = (pivot[r.forecast_date][r.city_cd] || 0) + r.predicted_qty;
  });
  const rows   = Object.values(pivot).sort((a,b) => a.date.localeCompare(b.date));
  const cities = [...new Set(data.map(r => r.city_cd))];

  return (
    <ResponsiveContainer width="100%" height={240}>
      <LineChart data={rows} margin={{ top:5, right:20, left:0, bottom:5 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#1e2130" />
        <XAxis dataKey="date" tick={{ fill:'#64748b', fontSize:10 }}
               tickFormatter={d => d.slice(5)} />
        <YAxis tick={{ fill:'#64748b', fontSize:10 }} />
        <Tooltip contentStyle={{ background:'#1a1d27', border:'1px solid #2a2d3e', color:'#e2e8f0' }} />
        <Legend wrapperStyle={{ color:'#94a3b8', fontSize:12 }} />
        {cities.map(c => (
          <Line key={c} type="monotone" dataKey={c}
                stroke={CITY_COLORS[c]||'#94a3b8'} strokeWidth={2}
                dot={false} activeDot={{ r:4 }} />
        ))}
      </LineChart>
    </ResponsiveContainer>
  );
}
