#!/usr/bin/env python3
"""可转债双低回测数据底座：全宇宙(含退市)日K+转股溢价率，断点续跑。
落盘: data/cb_daily/{code}.json  [{date,close,volume,premium}]"""
import json, os, sys, time
import akshare as ak

ROOT='/opt/data/fenjue'
OUT=f'{ROOT}/data/cb_daily'
os.makedirs(OUT, exist_ok=True)

def main():
    info=ak.bond_zh_cov_info_ths()
    codes=[]
    for _,r in info.iterrows():
        c=str(r['债券代码']).zfill(6)
        m='sh' if c.startswith(('110','113','118')) else 'sz'
        codes.append((c,m+c,str(r.get('债券简称',''))))
    print('universe:', len(codes), flush=True)
    done=set(os.listdir(OUT))
    ok=fail=0
    for i,(c,sym,nm) in enumerate(codes):
        if f'{c}.json' in done: ok+=1; continue
        try:
            k=ak.bond_zh_hs_cov_daily(symbol=sym)
            if k is None or len(k)==0: fail+=1; continue
            prem={}
            try:
                v=ak.bond_zh_cov_value_analysis(symbol=c)
                if v is not None and len(v):
                    for _,r in v.iterrows():
                        prem[str(r['日期'])[:10]]=float(r['转股溢价率'])
            except Exception:
                pass
            rows=[{'date':str(r['date'])[:10],'open':float(r['open']),'close':float(r['close']),'volume':float(r['volume']),
                   'premium':prem.get(str(r['date'])[:10])} for _,r in k.iterrows()]
            json.dump({'name':nm,'rows':rows}, open(f'{OUT}/{c}.json','w'))
            ok+=1
        except Exception as e:
            fail+=1
            print(f'{c} {nm} ERR {str(e)[:60]}', flush=True)
        if (i%50)==0: print(f'[{i}/{len(codes)}] ok={ok} fail={fail}', flush=True)
        time.sleep(0.25)
    print(f'DONE ok={ok} fail={fail}', flush=True)

if __name__=='__main__':
    main()
