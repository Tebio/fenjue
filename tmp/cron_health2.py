import json, sqlite3, datetime, time
jobs = json.load(open('/opt/data/cron/jobs.json'))['jobs']
print('总任务数:', len(jobs))
con = sqlite3.connect('/opt/data/cron/executions.db')
cols = [r[1] for r in con.execute("PRAGMA table_info(executions)")]
print('executions 列:', cols)
last = {}
for row in con.execute("SELECT * FROM executions ORDER BY rowid DESC"):
    rec = dict(zip(cols, row))
    jid = rec.get('job_id')
    if jid not in last:
        last[jid] = rec
enabled = [j for j in jobs if j.get('enabled', True)]
print('启用中:', len(enabled))
probs = []
for j in enabled:
    jid, name = j['id'], j.get('name', '')
    rec = last.get(jid)
    if rec is None:
        probs.append((name, '无执行记录', '', ''))
        continue
    st = rec.get('status'); ft = rec.get('finished_at') or rec.get('started_at')
    fts = str(ft)[:16] ; _ = fts; fts = datetime.datetime.fromtimestamp(float(ft)/1000 if ft and float(ft) > 1e12 else (float(ft or 0))).strftime('%m-%d %H:%M')
    if st not in ('success', 'ok', None):
        probs.append((name, st, fts, str(rec.get('error') or rec.get('output') or '')[:100]))
print('\n问题任务（最近执行非成功/无记录）:')
for p in probs:
    print(' ', p)
cut = time.time() - 72*3600
fcol = 'finished_at' if 'finished_at' in cols else 'started_at'
scol = 'status'
fails = con.execute(f"SELECT job_id, COUNT(*) c FROM executions WHERE {fcol} > ? AND {scol} NOT IN ('success','ok') GROUP BY job_id HAVING c > 2", (cut,)).fetchall()
jmap = {j['id']: j.get('name','') for j in jobs}
print('\n近72h失败>2次的任务:', [(jmap.get(j, j), c) for j, c in fails])
