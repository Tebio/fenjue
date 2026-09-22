import json

sh = [json.loads(x) for x in open('/opt/data/fenjue/data/xrules_shadow.jsonl') if x.strip()]
recent = [e for e in sh if e.get('status') != 'open'][-10:]
for e in recent:
    ret = e.get('ret')
    rs = f"{ret * 100:+.1f}%" if isinstance(ret, (int, float)) else '?'
    print(e.get('rule'), e.get('code'), e.get('name'), e.get('entry_date'), '→', e.get('exit_date'), rs, e.get('how', ''), 'sig:', e.get('sig_date'))
