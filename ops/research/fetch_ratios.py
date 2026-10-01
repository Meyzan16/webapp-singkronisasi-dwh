import sys,os,json,time,httpx
sys.path.insert(0,'backend')
from app.services.binance_urls import fapi
S=sys.argv[1]; out=os.path.join(S,'ratios.json')
D=json.load(open(out)) if os.path.exists(out) else {}
syms=sorted({l.split('\t')[1] for l in open(os.path.join(S,'cand.tsv'),encoding='utf-8')})
c=httpx.Client(timeout=20)
now=time.time(); start=int((now-29.5*86400)*1000); mid=start+500*3600*1000; end=int(now*1000)
EPS={'taker':('takerlongshortRatio',{}),'top':('topLongShortPositionRatio',{}),'glob':('globalLongShortAccountRatio',{}),'basis':('basis',{'contractType':'PERPETUAL'})}
n=0
for i,s in enumerate(syms):
    for k,(ep,extra) in EPS.items():
        key=f"{s}|{k}"
        if key in D: continue
        rows=[]
        for st,en in ((start,mid),(mid,end)):
            p={**extra,'period':'1h','limit':500,'startTime':st,'endTime':en}
            p['pair' if k=='basis' else 'symbol']=s
            for attempt in range(3):
                try:
                    r=c.get(fapi('/futures/data/'+ep),params=p)
                    if r.status_code==429: time.sleep(30); continue
                    if r.status_code==200 and isinstance(r.json(),list): rows+=r.json()
                    break
                except Exception: time.sleep(2)
            n+=1; time.sleep(0.35)
        D[key]=rows
    if i%20==0:
        json.dump(D,open(out,'w')); print(f"{i}/{len(syms)} req={n}",flush=True)
json.dump(D,open(out,'w')); print("DONE",len(D),flush=True)
