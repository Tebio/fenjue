import json, sqlite3
jobs = json.load(open('/opt/data/cron/jobs.json'))['jobs']
con = sqlite3.connect('/opt/data/cron/executions.db')
cols = [r[1] for r in con.execute("PRAGMA table_info(executions)")]
last = {}
for row in con.execute("SELECT * FROM executions ORDER BY rowid DESC"):
    rec = dict(zip(cols, row))
    if rec.get('job_id') not in last:
        last[rec['job_id']] = rec
enabled = [j for j in jobs if j.get('enabled', True)]
print('总任务', len(jobs), '启用', len(enabled))
probs = []
for j in enabled:
    jid, name = j['id'], j.get('name', '')
    rec = last.get(jid)
    if rec is None:
        probs.append((name, '无执行记录', '', ''))
        continue
    st = rec.get('status')
    ft = str(rec.get('finished_at') or rec.get('started_at') or '')[:16]
    if st not in ('success', 'ok'):
        probs.append((name, st, ft, str(rec.get('error') or '')[:90]))
print('\n最近执行非成功/无记录:')
for p in probs:
    print(' ', p)
fails = con.execute("SELECT job_id, COUNT(*) c FROM executions WHERE finished_at > datetime('now','-3 days') AND status NOT IN ('success','ok') GROUP BY job_id HAVING c > 1").fetchall()
jmap = {j['id']: j.get('name', '') for j in jobs}
print('\n近3天失败>1次:', [(jmap.get(j, j)[:30], c) for j, c in fails])
