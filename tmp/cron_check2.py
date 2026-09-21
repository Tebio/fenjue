import json, subprocess
out = subprocess.run(['hermes', 'cron', 'list', '--json'], capture_output=True, text=True)
try:
    jobs = json.loads(out.stdout)
except Exception:
    # 非 JSON 输出兜底：文本解析
    print(out.stdout[:500])
    raise SystemExit
fails = []
for j in jobs.get('jobs', jobs if isinstance(jobs, list) else []):
    st = j.get('last_status') or j.get('status') or ''
    if st not in ('completed', 'success', '', None) or j.get('last_error'):
        fails.append((j.get('name', '?'), st, str(j.get('last_error', ''))[:120]))
print(f'cron 任务 {len(jobs.get("jobs", jobs if isinstance(jobs, list) else []))} 个，异常 {len(fails)} 个')
for f in fails:
    print(' ', f)