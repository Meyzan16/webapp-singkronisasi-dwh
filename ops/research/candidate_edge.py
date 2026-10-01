import json,sys,statistics as st
rows=[]
for l in open(sys.argv[1],encoding='utf-8'):
    p=l.rstrip('\n').split('\t')
    if len(p)<8: continue
    f=json.loads(p[7] or '{}'); ts=float(p[0])
    rows.append(dict(ts=ts,sym=p[1],dir=p[2],cost=float(p[3]),p1=float(p[4] or 0),p4=float(p[5]),p24=float(p[6]) if p[6] else None,**{k:v for k,v in f.items() if isinstance(v,(int,float))}))
# dedup: first per (sym,dir) per 4h
seen={};d=[]
for r in rows:
    k=(r['sym'],r['dir'])
    if k in seen and r['ts']-seen[k]<4*3600: continue
    seen[k]=r['ts']; d.append(r)
d.sort(key=lambda r:r['ts']); cut=d[int(len(d)*0.6)]['ts']
A=[r for r in d if r['ts']<cut]; B=[r for r in d if r['ts']>=cut]
import datetime
print(f"dedup {len(d)} (raw {len(rows)}) | train {len(A)} test {len(B)} | split {datetime.datetime.fromtimestamp(cut):%m-%d %H:%M}")
def stat(rs,key='p4'):
    if not rs: return "n=0"
    v=[r[key]-r['cost'] for r in rs]; return f"n={len(v):4d} net4h={st.mean(v):+.2f}% pos={100*sum(x>0 for x in v)/len(v):3.0f}%"
print("ALL  train",stat(A),"| test",stat(B))
for dr in ('LONG','SHORT'):
    print(f"{dr:5s} train",stat([r for r in A if r['dir']==dr]),"| test",stat([r for r in B if r['dir']==dr]))
feats=['score','change_24h','change_1h','change_30m','rsi','oi_change','funding_rate','atr_pct','quote_vol_24h','breadth_fade_frac','shadow_probability','adaptive_score','estimated_win_probability','liq_long','liq_short']
print("\nper-feature terciles (LONG), net4h train | test:")
for dr in ('LONG','SHORT'):
  print(f"--- {dr}")
  for f in feats:
    a=[r for r in A if r['dir']==dr and f in r]; b=[r for r in B if r['dir']==dr and f in r]
    if len(a)<60: continue
    vals=sorted(r[f] for r in a); q1,q2=vals[len(vals)//3],vals[2*len(vals)//3]
    out=[]
    for lo,hi,nm in ((-1e18,q1,'lo'),(q1,q2,'mid'),(q2,1e18,'hi')):
        ta=[r for r in a if lo<=r[f]<hi]; tb=[r for r in b if lo<=r[f]<hi]
        ma=st.mean([r['p4']-r['cost'] for r in ta]) if ta else 0; mb=st.mean([r['p4']-r['cost'] for r in tb]) if tb else 0
        out.append(f"{nm}[{lo if lo>-1e17 else '-inf':>.6}..]:{ma:+.2f}|{mb:+.2f}(n{len(tb)})")
    print(f"  {f:26s} q=({q1:.3g},{q2:.3g}) "+"  ".join(out))
