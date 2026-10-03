#!/usr/bin/env python3
"""T2耐心版: szse annList 长退避重试, 枚举channelCode找指数调样公告"""
import json, subprocess, time

def ann(payload, retries=4):
    args=['curl','-s','https://www.szse.cn/api/disc/announcement/annList?random=0.77','-X','POST',
          '-H','User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64)','-H','Content-Type: application/json',
          '-H','Referer: https://www.szse.cn/disclosure/announcement/index.html',
          '-d',json.dumps(payload),'--max-time','30']
    for k in range(retries):
        r=subprocess.run(args,capture_output=True,text=True)
        try:
            return json.loads(r.stdout)
        except Exception:
            time.sleep(8*(k+1))
    return {}

# 1) 先不带channel拉一天全量, 收集真实channelCode
channels=set()
for d0,d1 in [('2025-11-28','2025-11-28'),('2025-05-30','2025-05-30'),('2024-11-29','2024-11-29')]:
    d=ann({"seDate":[d0,d1],"pageSize":100,"pageNum":1})
    n=d.get('announceCount',0)
    print(d0,'count',n, flush=True)
    for x in (d.get('data') or []):
        channels.add(str(x.get('channelCode')))
        t=x.get('title','')
        if '指数' in t:
            print('  HIT:', t[:70], x.get('channelCode'), flush=True)
    time.sleep(6)
print('channels:', sorted(channels), flush=True)

# 2) 每个真实channel拉全年, 找指数调样
hits=[]
for ch in sorted(channels):
    d=ann({"seDate":["2019-01-01","2026-10-01"],"channelCode":[ch],"pageSize":200,"pageNum":1})
    for x in (d.get('data') or []):
        t=x.get('title','')
        if '指数' in t and ('样本' in t or '调整' in t or '调样' in t):
            hits.append({'date':(x.get('publishTime') or '')[:10],'title':t,'channel':ch,'attach':x.get('attachPath','')})
            print('HIT:', hits[-1]['date'], t[:60], flush=True)
    time.sleep(6)
json.dump({'channels':sorted(channels),'hits':hits}, open('/opt/data/fenjue/data/szse_probe_result.json','w'), ensure_ascii=False, indent=1)
print('DONE hits=', len(hits), flush=True)
