import { PieChart, Pie, Cell, Tooltip, Legend, ResponsiveContainer } from 'recharts';
const COLORS = { subscription:'#60a5fa', lgbm:'#a78bfa', lgbm_hyd:'#c4b5fd', rolling_avg:'#4ade80' };

export default function MethodChart({ data }) {
  if (!data) return null;
  const rows = Object.entries(data).map(([method, value]) => ({ method, value }));
  return (
    <ResponsiveContainer width="100%" height={240}>
      <PieChart>
        <Pie data={rows} dataKey="value" nameKey="method" cx="50%" cy="50%"
             outerRadius={80} innerRadius={45}>
          {rows.map(r => <Cell key={r.method} fill={COLORS[r.method]||'#64748b'} />)}
        </Pie>
        <Tooltip contentStyle={{ background:'#1a1d27', border:'1px solid #2a2d3e', color:'#e2e8f0' }}
                 formatter={v => v.toLocaleString()} />
        <Legend wrapperStyle={{ color:'#94a3b8', fontSize:12 }} />
      </PieChart>
    </ResponsiveContainer>
  );
}