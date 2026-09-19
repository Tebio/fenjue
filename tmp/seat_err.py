import json, sqlite3
jobs = {j['id']: j.get('name', '') for j in json.load(open('/opt/data/cron/jobs.json'))['jobs']}
con = sqlite3.connect('/opt/data/cron/executions.db')
cols = [r[1] for r in con.execute("PRAGMA table_info(executions)")]
jid = [k for k, v in jobs.items() if '席位口味' in v][0]
row = con.execute("SELECT * FROM executions WHERE job_id=? ORDER BY rowid DESC LIMIT 1", (jid,)).fetchone()
rec = dict(zip(cols, row))
print(rec.get('error'))
