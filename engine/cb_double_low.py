#!/usr/bin/env python3
"""双低转债周度轮动回测（集思录经典策略自家复验）
规则: 双低值=价格+转股溢价率(%); 每周最后一个交易日收盘排名;
  取前N等权, 下周一开盘成交(T+0品种开盘价可得);
  缓冲带: 跌出前N+buf才换(减换手);
  费: 万1双边(0.01%×2/roundtrip);
  强赎退市: 按最后交易日收盘价结算(退市后无数据=自然出池);
  对照: 全转债等权周均收益(自构指数)
输出: data/cb_double_low_result.json"""
import json, os, glob, bisect
from statistics import mean, median

ROOT='/opt/data/fenjue'
FEE=0.0002  # 万1×2
TOP_N=10
BUF=10    # 跌出前20才换

def load():
    cb={}
    for f in glob.glob(f'{ROOT}/data/cb_daily/*.json'):
        d=json.load(open(f))
        c=os.path.basename(f)[:6]
        rows=[r for r in d['rows'] if r['close']>0]
        if len(rows)>=60: cb[c]={'name':d['name'],'rows':rows,'bydate':{r['date']:r for r in rows}}
    return cb

def calendar(cb):
    days=set()
    for v in cb.values(): days.update(v['bydate'].keys())
    return sorted(days)

def week_ends(cal):
    """每周最后一个交易日"""
    we=[]; prev=None
    for d in cal:
        if prev and d[:4]+'-W'!=None:
            import datetime
            wd=datetime.date.fromisoformat(d).isoweekday()
            pw=datetime.date.fromisoformat(prev).isoweekday()
            if wd<pw or (datetime.date.fromisoformat(d)-datetime.date.fromisoformat(prev)).days>3:
                we.append(prev)
        prev=d
    if prev: we.append(prev)
    return we

def next_day(cal,d):
    i=bisect.bisect_right(cal,d)
    return cal[i] if i<len(cal) else None

def main():
    cb=load()
    cal=calendar(cb)
    cal=[d for d in cal if d>='2019-01-01']
    we=[d for d in week_ends(cal) if d>='2019-01-01']
    print(f'宇宙{len(cb)}只 日历{cal[0]}~{cal[-1]} 调仓点{len(we)}')
    eq=1.0; curve=[]; holdings=set()
    weekly_rets=[]
    bench_eq=1.0; bench_curve=[]
    for i,d in enumerate(we):
        nd=next_day(cal,d)
        if not nd: break
        # 候选: 当日有价格+溢价率+量>0+价格<200(妖债剔除,经典做法)
        cands=[]
        for c,v in cb.items():
            r=v['bydate'].get(d)
            if r and r['premium'] is not None and r['volume']>0 and r['close']<200:
                cands.append((r['close']+r['premium'], c))
        if len(cands)<TOP_N: continue
        cands.sort()
        top=[c for _,c in cands[:TOP_N]]
        keep_zone=set(c for _,c in cands[:TOP_N+BUF])
        newh=set(h for h in holdings if h in keep_zone)  # 缓冲带内留仓
        for c in top:
            if len(newh)>=TOP_N: break
            newh.add(c)
        # 调仓换手
        turnover=len(holdings-newh)/max(TOP_N,1)
        holdings=newh
        # 持有期收益: d收盘(≈下周一开盘代理——转债周末无跳空风险折价, 用d收盘→下周we收盘, 周频近似)
        # 更诚实: 用下周一开盘... 数据无open独立意义(日K有open!) 用next day open
        rets=[]
        for c in holdings:
            v=cb[c]
            r0=v['bydate'].get(nd); 
            # 卖出日: 下一个调仓日nd2收盘, 或该债最后交易日收盘
            nd2=next_day(cal,we[i+1]) if i+1<len(we) else None
            exit_d=None
            if nd2 and nd2 in v['bydate']: exit_d=nd2
            else:
                # 找nd之后该债最后一个有数据的日(<=nd2 or 末日)
                ds=[x for x in v['bydate'] if nd<x<=(nd2 or '9999')]
                exit_d=max(ds) if ds else None
            if r0 and exit_d:
                rets.append(v['bydate'][exit_d]['close']/r0['open']-1)
        if not rets: continue
        wr=mean(rets)-turnover*FEE*2
        eq*=1+wr; weekly_rets.append((d,wr))
        curve.append((d,round(eq,4)))
        # 对照: 全转债等权(有数据且量>0)
        brets=[]
        for c,v in cb.items():
            r0=v['bydate'].get(nd)
            nd2=next_day(cal,we[i+1]) if i+1<len(we) else None
            if nd2 and nd2 in v['bydate'] and r0 and r0['volume']>0:
                brets.append(v['bydate'][nd2]['close']/r0['open']-1)
        if brets: bench_eq*=1+mean(brets)
        bench_curve.append((d,round(bench_eq,4)))
    # 统计
    n=len(weekly_rets)
    years=n/50
    total=eq-1; ann=(eq**(1/years)-1) if years>0 else 0
    wins=sum(1 for _,r in weekly_rets if r>0)/n
    # 最大回撤
    peak=1; mdd=0
    for _,e in curve:
        peak=max(peak,e); mdd=min(mdd,e/peak-1)
    bpeak=1; bmdd=0
    for _,e in bench_curve:
        bpeak=max(bpeak,e); bmdd=min(bmdd,e/bpeak-1)
    # 双段
    early=[r for d,r in weekly_rets if d<'2023-01-01']
    late=[r for d,r in weekly_rets if d>='2023-01-01']
    res={
      'universe':len(cb),'weeks':n,
      'double_low':{'total_ret':round(total,4),'ann_ret':round(ann,4),'win_rate':round(wins,3),'mdd':round(mdd,4),
                    'early_weekly_mean':round(mean(early)*100,3) if early else None,
                    'late_weekly_mean':round(mean(late)*100,3) if late else None},
      'bench_equal_weight':{'total':round(bench_eq-1,4),'mdd':round(bmdd,4)},
      'params':{'top_n':TOP_N,'buf':BUF,'fee_rt':FEE*2},
      'curve_tail':curve[-8:],'bench_tail':bench_curve[-8:],
    }
    json.dump(res, open(f'{ROOT}/data/cb_double_low_result.json','w'), ensure_ascii=False, indent=1)
    print(json.dumps({k:v for k,v in res.items() if 'tail' not in k}, ensure_ascii=False, indent=1))

if __name__=='__main__':
    main()
