import json, sqlite3, datetime
jobs = json.load(open('/opt/data/cron/jobs.json'))
print('总任务数:', len(jobs))
con = sqlite3.connect('/opt/data/cron/executions.db')
cur = con.cursor()
# 最近一次执行状态 per job
rows = cur.execute("SELECT job_id, status, finished_at, error FROM executions ORDER BY finished_at DESC").fetchall() if True else []
last = {}
for jid, st, ft, err in rows:
    if jid not in last:
        last[jid] = (st, ft, err)
bad = []
never = []
for j in jobs:
    jid = j.get('id'); name = j.get('name', '')[:28]
    en = j.get('enabled', True)
    if jid in last:
        st, ft, err = last[jid]
        if st != 'success':
            bad.append((name, st, ft, (err or '')[:80]))
    else:
        never.append(name)
    # 打印全表（简）
print('\n最近失败的任务:')
for name, st, ft, err in bad[:20]:
    print(f"  {name}: {st} @ {datetime.datetime.fromtimestamp(ft/1000 if ft>1e12 else ft).strftime('%m-%d %H:%M') if ft else '?'} {err}")
print('\n无执行记录的任务:', never[:20])
# 近48h失败计数
import time
cut = time.time() - 48*3600
fails = cur.execute("SELECT job_id, COUNT(*) FROM executions WHERE finished_at > ? AND status != 'success' GROUP BY job_id", (cut*1000,)).fetchall()
print('\n近48h失败分布:', fails[:15])
