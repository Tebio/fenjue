import json, sqlite3
jobs = {j['id']: j.get('name', '') for j in json.load(open('/opt/data/cron/jobs.json'))['jobs']}
con = sqlite3.connect('/opt/data/cron/executions.db')
cols = [r[1] for r in con.execute("PRAGMA table_info(executions)")]
for name in ('B5半路板', '席位口味', 'm60日增量'):
    jid = [k for k, v in jobs.items() if name in v]
    if not jid:
        continue
    rows = con.execute("SELECT * FROM executions WHERE job_id=? ORDER BY rowid DESC LIMIT 2", (jid[0],)).fetchall()
    for row in rows:
        rec = dict(zip(cols, row))
        print('=' * 20, jobs[jid[0]], rec.get('finished_at'))
        print('status:', rec.get('status'))
        print('error:', str(rec.get('error'))[:600])
