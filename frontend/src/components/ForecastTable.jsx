import { useState } from 'react';

const BADGE = {
  subscription: { bg:'#1e3a5f', color:'#60a5fa', label:'SUBS' },
  lgbm:         { bg:'#2d1b69', color:'#a78bfa', label:'LGBM' },
  lgbm_hyd:     { bg:'#312060', color:'#c4b5fd', label:'LGBM HYD' },
  rolling_avg:  { bg:'#1a3a2a', color:'#4ade80', label:'ROLLING' },
};

export default function ForecastTable({ data, loading }) {
  const [search,  setSearch]  = useState('');
  const [sortKey, setSortKey] = useState('total_qty');
  const [sortAsc, setSortAsc] = useState(false);
  const [page,    setPage]    = useState(1);
  const PAGE = 20;

  const filtered = (data || []).filter(r =>
    !search || r.product_name.toLowerCase().includes(search.toLowerCase()) ||
    r.city_cd.toLowerCase().includes(search.toLowerCase())
  );

  const sorted = [...filtered].sort((a,b) => {
    const va=a[sortKey], vb=b[sortKey];
    return typeof va==='number' ? (sortAsc?va-vb:vb-va) :
           (sortAsc?String(va).localeCompare(String(vb)):String(vb).localeCompare(String(va)));
  });

  const totalPages = Math.ceil(sorted.length / PAGE);
  const slice = sorted.slice((page-1)*PAGE, page*PAGE);

  const thClick = key => { if(sortKey===key) setSortAsc(!sortAsc); else{setSortKey(key);setSortAsc(false);} };

  const th = (k, label) => (
    <th onClick={()=>thClick(k)} style={styles.th}>{label} {sortKey===k?(sortAsc?'↑':'↓'):''}</th>
  );

  return (
    <div>
      <div style={{ display:'flex', justifyContent:'flex-end', marginBottom:12 }}>
        <input placeholder="Search product or city..."
               value={search} onChange={e=>{setSearch(e.target.value);setPage(1);}}
               style={styles.search} />
      </div>
      <div style={{ overflowX:'auto' }}>
        <table style={{ width:'100%', borderCollapse:'collapse', fontSize:'0.83rem' }}>
          <thead>
            <tr style={{ borderBottom:'1px solid #2a2d3e' }}>
              {th('city_cd','City')}
              {th('product_name','Product')}
              {th('total_qty','30-Day Total')}
              {th('daily_avg','Daily Avg')}
              {th('peak_qty','Peak Day')}
              {th('method','Method')}
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={6} style={{ textAlign:'center', padding:40, color:'#64748b' }}>Loading forecast...</td></tr>
            ) : slice.map((r,i) => {
              const b = BADGE[r.method] || { bg:'#1e293b', color:'#94a3b8', label:r.method };
              return (
                <tr key={i} style={styles.row}>
                  <td style={styles.td}>{r.city_cd}</td>
                  <td style={styles.td}><strong>{r.product_name}</strong></td>
                  <td style={styles.td}>{r.total_qty?.toLocaleString()}</td>
                  <td style={styles.td}>{r.daily_avg?.toLocaleString()}</td>
                  <td style={styles.td}>{r.peak_qty?.toLocaleString()}</td>
                  <td style={styles.td}>
                    <span style={{ background:b.bg, color:b.color, padding:'2px 9px', borderRadius:20, fontSize:'0.7rem', fontWeight:600 }}>
                      {b.label}
                    </span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div style={{ display:'flex', justifyContent:'center', alignItems:'center', gap:12, marginTop:14 }}>
        <button onClick={()=>setPage(p=>Math.max(1,p-1))} style={styles.pageBtn} disabled={page===1}>‹ Prev</button>
        <span style={{ color:'#94a3b8', fontSize:'0.8rem' }}>Page {page} of {totalPages} ({sorted.length} products)</span>
        <button onClick={()=>setPage(p=>Math.min(totalPages,p+1))} style={styles.pageBtn} disabled={page===totalPages}>Next ›</button>
      </div>
    </div>
  );
}

const styles = {
  search: { background:'#0f1117', color:'#e2e8f0', border:'1px solid #2a2d3e', borderRadius:8, padding:'7px 12px', fontSize:'0.83rem', width:240, outline:'none' },
  th: { textAlign:'left', padding:'9px 12px', color:'#94a3b8', fontSize:'0.72rem', textTransform:'uppercase', letterSpacing:'0.05em', cursor:'pointer', whiteSpace:'nowrap' },
  td: { padding:'9px 12px', borderBottom:'1px solid #1e2130' },
  row: { cursor:'default' },
  pageBtn: { background:'#1a1d27', color:'#e2e8f0', border:'1px solid #2a2d3e', borderRadius:6, padding:'5px 14px', cursor:'pointer', fontSize:'0.8rem' },
};