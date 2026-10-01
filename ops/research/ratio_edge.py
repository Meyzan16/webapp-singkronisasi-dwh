import json,bisect,statistics as st,datetime,sys
D=json.load(open('ratios.json'))
def series(sym,k,field):
    rows=D.get(f"{sym}|{k}") or []
    out={}
    for r in rows:
        try: out[int(r['timestamp'])//1000]=float(r[field])
        except (KeyError,ValueError,TypeError): pass
    ts=sorted(out); return ts,[out[t] for t in ts]
cache={}
def at(sym,k,field,t,lag_h=0):
    key=(sym,k,field)
    if key not in cache: cache[key]=series(sym,k,field)
    ts,vals=cache[key]
    i=bisect.bisect_right(ts,t-3600-lag_h*3600)-1   # periode 1j yang SUDAH selesai
    return vals[i] if i>=0 and t-ts[i]<3*3600+lag_h*3600 else None
rows=[]
for l in open('cand.tsv',encoding='utf-8'):
    p=l.rstrip('\n').split('\t')
    ts=float(p[0]); sym=p[1]
    if f"{sym}|taker" not in D: continue
    r=dict(ts=ts,sym=sym,dir=p[2],cost=float(p[3]),p4=float(p[5]),p24=float(p[6]) if p[6] else None)
    f={}
    f['taker_bsr']=at(sym,'taker','buySellRatio',ts)
    tk=[at(sym,'taker','buySellRatio',ts,h) for h in range(4)]
    f['taker_bsr_4h']=st.mean(tk) if all(x is not None for x in tk) else None
    f['top_ls']=at(sym,'top','longShortRatio',ts)
    t4=at(sym,'top','longShortRatio',ts,4)
    f['top_ls_chg4h']=(f['top_ls']/t4-1)*100 if f['top_ls'] and t4 else None
    f['glob_ls']=at(sym,'glob','longShortRatio',ts)
    g4=at(sym,'glob','longShortRatio',ts,4)
    f['glob_ls_chg4h']=(f['glob_ls']/g4-1)*100 if f['glob_ls'] and g4 else None
    f['top_vs_glob']=f['top_ls']/f['glob_ls'] if f['top_ls'] and f['glob_ls'] else None
    f['basis_rate']=at(sym,'basis','basisRate',ts)
    r.update(f); rows.append(r)
seen={};d=[]
for r in sorted(rows,key=lambda r:r['ts']):
    k=(r['sym'],r['dir'])
    if k in seen and r['ts']-seen[k]<4*3600: continue
    seen[k]=r['ts']; d.append(r)
cut=d[int(len(d)*0.6)]['ts']
A=[r for r in d if r['ts']<cut]; B=[r for r in d if r['ts']>=cut]
cov={f:sum(1 for r in d if r.get(f) is not None) for f in ('taker_bsr','top_ls','glob_ls','basis_rate','top_ls_chg4h')}
print(f"kandidat dedup {len(d)} | latih {len(A)} uji {len(B)} | split {datetime.datetime.fromtimestamp(cut):%m-%d %H:%M} | cakupan {cov}")
net=lambda rs:(st.mean([r['p4']-r['cost'] for r in rs]),len(rs)) if rs else (0,0)
feats=['taker_bsr','taker_bsr_4h','top_ls','top_ls_chg4h','glob_ls','glob_ls_chg4h','top_vs_glob','basis_rate']
lolos=[]
for dr in ('LONG','SHORT'):
    a0=net([r for r in A if r['dir']==dr]); b0=net([r for r in B if r['dir']==dr])
    print(f"\n--- {dr}: dasar net4h latih {a0[0]:+.2f}% (n{a0[1]}) | uji {b0[0]:+.2f}% (n{b0[1]})")
    for f in feats:
        a=[r for r in A if r['dir']==dr and r.get(f) is not None]; b=[r for r in B if r['dir']==dr and r.get(f) is not None]
        if len(a)<45: continue
        v=sorted(r[f] for r in a); q1,q2=v[len(v)//3],v[2*len(v)//3]
        cells=[]
        for lo,hi,nm in ((-1e18,q1,'rendah'),(q1,q2,'tengah'),(q2,1e18,'tinggi')):
            ma,na=net([r for r in a if lo<=r[f]<hi]); mb,nb=net([r for r in b if lo<=r[f]<hi])
            cells.append(f"{nm}:{ma:+.2f}|{mb:+.2f}(n{na}/{nb})")
            if ma>0.25 and mb>0.25 and na>=20 and nb>=15: lolos.append((dr,f,nm,lo,hi,ma,mb,na,nb))
        print(f"  {f:14s} batas=({q1:.4g},{q2:.4g})  "+"  ".join(cells))
print("\nIrisan positif (> +0,25% net) di LATIH dan UJI:")
for x in lolos: print("  ",x)
if not lolos: print("   tidak ada")
