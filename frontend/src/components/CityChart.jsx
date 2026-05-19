import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from 'recharts';
const COLORS = { BLR:'#6c63ff', HYD:'#f59e0b', PNQ:'#22c55e', VGA:'#ef4444' };

export default function CityChart({ data }) {
  if (!data) return null;
  const rows = Object.entries(data).map(([city, total]) => ({ city, total }))
                     .sort((a,b) => b.total - a.total);
  return (
    <ResponsiveContainer width="100%" height={240}>
      <BarChart data={rows} margin={{ top:5, right:20, left:0, bottom:5 }}>
        <XAxis dataKey="city" tick={{ fill:'#64748b', fontSize:11 }} />
        <YAxis tick={{ fill:'#64748b', fontSize:10 }} />
        <Tooltip contentStyle={{ background:'#1a1d27', border:'1px solid #2a2d3e', color:'#e2e8f0' }}
                 formatter={v => v.toLocaleString()} />
        <Bar dataKey="total" radius={[6,6,0,0]}>
          {rows.map(r => <Cell key={r.city} fill={COLORS[r.city]||'#94a3b8'} />)}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}