#!/usr/bin/env python3
"""深交所/国证指数调样名单拉取 —— 家里宽带专用（NAS IP 被 szse/cnindex WAF 封）
用法: python pull_szse_rebalance.py   → 产出 szse_rebalance_events.json, 微信/QQ发回或丢共享目录
拉两个源互为备份:
  A. szse annList 公告API (标题含'指数'+'样本调整') → 附件PDF链接
  B. cnindex sample-detail/download-adjustment (若活则直接给Excel)
我们只消费 A 的公告列表; PDF名单解析在NAS侧做(线束现成)。
"""
import json, subprocess, time, sys, os

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'szse_rebalance_events.json')

def curl(args):
    r = subprocess.run(args, capture_output=True, timeout=40)
    return r.stdout.decode('utf-8', 'replace')

def szse_ann(se0, se1, ch=None, page=1):
    payload = {"seDate":[se0,se1],"pageSize":100,"pageNum":page}
    if ch: payload["channelCode"]=[ch]
    out = curl(['curl','-s','https://www.szse.cn/api/disc/announcement/annList?random=0.5','-X','POST',
                '-H','User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                '-H','Content-Type: application/json',
                '-H','Referer: https://www.szse.cn/disclosure/announcement/index.html',
                '-d',json.dumps(payload)])
    try: return json.loads(out)
    except Exception: return {}

def main():
    hits=[]
    # 全渠道扫(不带channelCode); szse公告通常当年可查, 分年拉2019-2026
    for y in range(2019, 2027):
        for page in (1,2,3):
            d = szse_ann(f'{y}-01-01', f'{y}-12-31', page=page)
            rows = d.get('data') or []
            for x in rows:
                t = x.get('title','')
                if '指数' in t and ('样本' in t or '调整' in t):
                    hits.append({'date':(x.get('publishTime') or '')[:10],'title':t,
                                 'attach':x.get('attachPath',''),'channel':str(x.get('channelCode'))})
            if len(rows)<100: break
            time.sleep(2)
        print(y, 'cum hits:', len(hits), flush=True)
        time.sleep(3)
    # B源: cnindex 调样Excel(顺带试)
    cni=[]
    for code in ('399001','399006','399330','399673'):
        out = curl(['curl','-s',f'https://www.cnindex.com.cn/sample-detail/download-adjustment?indexcode={code}',
                    '-H','User-Agent: Mozilla/5.0'])
        cni.append({'code':code,'ok': not out.startswith(code),'head':out[:40]})
        time.sleep(1)
    json.dump({'szse_hits':hits,'cnindex_probe':cni}, open(OUT,'w'), ensure_ascii=False, indent=1)
    print('DONE ->', OUT, 'szse hits:', len(hits))

if __name__=='__main__':
    main()
