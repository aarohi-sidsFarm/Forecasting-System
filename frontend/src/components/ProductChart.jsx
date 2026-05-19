import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from 'recharts';

export default function ProductChart({ data }) {
  if (!data?.length) return null;
  const rows = [...data].sort((a,b) => b.total_qty - a.total_qty).slice(0,15);
  return (
    <ResponsiveContainer width="100%" height={300}>
      <BarChart data={rows} layout="vertical" margin={{ top:5, right:20, left:70, bottom:5 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#1e2130" horizontal={false} />
        <XAxis type="number" tick={{ fill:'#64748b', fontSize:10 }} />
        <YAxis type="category" dataKey="product_name" tick={{ fill:'#94a3b8', fontSize:11 }} width={70} />
        <Tooltip contentStyle={{ background:'#1a1d27', border:'1px solid #2a2d3e', color:'#e2e8f0' }}
                 formatter={v => v.toLocaleString()} />
        <Bar dataKey="total_qty" fill="#6c63ff88" stroke="#6c63ff" radius={[0,4,4,0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}