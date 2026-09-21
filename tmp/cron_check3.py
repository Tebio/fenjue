import json
from datetime import datetime, timezone
jobs = json.load(open('/opt/data/cron/jobs.json'))['jobs']
now = datetime.now(timezone.utc)
print(f'任务数: {len(jobs)}')
bad, paused_n = [], 0
for j in jobs:
    name = j.get('name', '?')
    st = j.get('last_status', '')
    err = j.get('last_error') or j.get('last_delivery_error') or ''
    last = j.get('last_run_at')
    age = 'never'
    if last:
        try:
            age = f'{(now - datetime.fromisoformat(last)).total_seconds()/3600:.0f}h前'
        except Exception:
            pass
    if not j.get('enabled', True) or j.get('paused_at'):
        paused_n += 1
        continue
    if st and st not in ('ok', 'completed', 'success'):
        bad.append((name, st, str(err)[:100], age))
print(f'暂停/禁用: {paused_n}, 启用中执行异常: {len(bad)}')
for b in bad:
    print(' ', b)