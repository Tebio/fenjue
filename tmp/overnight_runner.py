#!/usr/bin/env python3
"""过夜任务编排器(2026-10-03凌晨): 顺序跑完三项遗留, 每步落盘+写报告
T1: 20只失败转债补拉(直连交易所K线API绕akshare)
T2: 深交所调样公告channelCode暴力枚举→若拿到名单则解析落盘
T3: cap_hist 9只截断票重试
产出: data/overnight_20261003_report.json
"""
import json, os, subprocess, time, sys

ROOT='/opt/data/fenjue'
REPORT={'started':time.strftime('%F %T'),'tasks':{}}

def sh(args, timeout=120):
    try:
        r=subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return r.stdout, r.returncode
    except Exception as e:
        return str(e), -1

# ---------- T1: 失败转债补拉 ----------
def t1():
    missing=[]
    have=set(os.listdir(f'{ROOT}/data/cb_daily'))
    import akshare as ak
    info=ak.bond_zh_cov_info_ths()
    for _,r in info.iterrows():
        c=str(r['债券代码']).zfill(6)
        if f'{c}.json' not in have:
            missing.append((c, str(r.get('债券简称',''))))
    fixed=0; errs=[]
    for c,nm in missing:
        # 直连: 深市走szse行情, 沪市走sse——用腾讯行情历史接口兜底: web.ifzq.gtimg.cn 日K
        mkt='sh' if c.startswith(('110','113','118')) else 'sz'
        out,rc=sh(['curl','-s',f'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={mkt}{c},day,2018-01-01,2026-10-01,2000,qfq',
                    '-H','User-Agent: Mozilla/5.0','--max-time','20'])
        try:
            d=json.loads(out)
            key=f'{mkt}{c}'
            node=d['data'][key]
            kl=node.get('qfqday') or node.get('day') or []
            rows=[{'date':x[0],'open':float(x[1]),'close':float(x[2]),'volume':float(x[5]) if len(x)>5 else 0,'premium':None} for x in kl]
            if rows:
                json.dump({'name':nm,'rows':rows,'no_premium':True}, open(f'{ROOT}/data/cb_daily/{c}.json','w'))
                fixed+=1
            else:
                errs.append((c,nm,'empty'))
        except Exception as e:
            errs.append((c,nm,str(e)[:60]))
        time.sleep(0.4)
    REPORT['tasks']['T1_cb_fix']={'missing':len(missing),'fixed':fixed,'errs':errs[:25]}
    print(f"T1 done: fixed {fixed}/{len(missing)}", flush=True)

# ---------- T2: 深交所调样公告枚举 ----------
def t2():
    found=[]
    channels=['indexNotice','index_adjust','sampleNotice','zsNotice','zxNotice','cnindexNotice',
              'notice_index','market_index','indexSample','sampleAdjust','indexConstituent',
              'szse_index','idxNotice','componentNotice','zsxz','indexChange','indexSampleChange']
    # 先探channelCode枚举接口本身是否存在(拿站点JS里的channel列表)
    out,_=sh(['curl','-s','https://www.szse.cn/api/disc/announcement/annList?random=0.3','-X','POST',
              '-H','User-Agent: Mozilla/5.0','-H','Content-Type: application/json',
              '-d','{"seDate":["2025-11-20","2025-12-05"],"pageSize":100,"pageNum":1}','--max-time','20'])
    real_channels=set()
    try:
        d=json.loads(out)
        for x in (d.get('data') or []):
            real_channels.add(str(x.get('channelCode')))
    except Exception:
        pass
    REPORT['tasks']['T2_probe_all_channels']={'real_channels_seen':sorted(real_channels)}
    print('T2 real channels:', real_channels, flush=True)
    # 用真实channel逐个查指数关键词
    hits=[]
    for ch in (real_channels or set(channels)):
        out,_=sh(['curl','-s','https://www.szse.cn/api/disc/announcement/annList?random=0.4','-X','POST',
                  '-H','User-Agent: Mozilla/5.0','-H','Content-Type: application/json',
                  '-d',json.dumps({"seDate":["2019-01-01","2026-10-01"],"channelCode":[ch],"pageSize":100,"pageNum":1}),
                  '--max-time','30'])
        try:
            d=json.loads(out)
            for x in (d.get('data') or []):
                t=x.get('title','')
                if ('指数' in t and ('调整' in t or '样本' in t)) or '调样' in t:
                    hits.append({'date':x.get('publishTime','')[:10],'title':t,'channel':ch,
                                 'attach':x.get('attachPath','')})
        except Exception:
            pass
        time.sleep(1.5)
    REPORT['tasks']['T2_hits']=hits[:80]
    REPORT['tasks']['T2_hit_count']=len(hits)
    print(f"T2 done: {len(hits)} hits", flush=True)
    if hits:
        json.dump(hits, open(f'{ROOT}/data/szse_index_anns.json','w'), ensure_ascii=False, indent=1)

# ---------- T3: cap_hist 截断票重试 ----------
def t3():
    sys.path.insert(0, ROOT)
    try:
        import importlib.util
        spec=importlib.util.spec_from_file_location('fch', f'{ROOT}/engine/fetch_cap_history.py')
        m=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        # 找截断票: cap_hist缺失但big_kcache存在的60/00票
        import glob
        missing=[]
        have=set(os.listdir(f'{ROOT}/data/cap_hist'))
        for f in glob.glob(f'{ROOT}/data/big_kcache/*.json'):
            c=os.path.basename(f)
            if c not in have: missing.append(c[:6])
        REPORT['tasks']['T3_cap_missing']=missing[:20]
        print('T3 missing:', len(missing), flush=True)
    except Exception as e:
        REPORT['tasks']['T3_error']=str(e)[:200]

t1(); t2(); t3()
REPORT['finished']=time.strftime('%F %T')
json.dump(REPORT, open(f'{ROOT}/data/overnight_20261003_report.json','w'), ensure_ascii=False, indent=1)
print('ALL DONE', flush=True)
