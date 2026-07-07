"""FenJue Console — Journal route (Agent 5). Trade log form + transaction list."""
from datetime import date
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter()

_SAMPLES = [
    ("2025-07-04", "600141", "兴发集团", "买入", 18.52, 15, "S池信号触发"),
    ("2025-07-03", "002428", "云南锗业", "买入", 15.80, 10, "认知差扩大"),
    ("2025-07-01", "600206", "有研新材", "卖出", 12.80,  0, "止损退出"),
]

def _table_rows() -> str:
    rows = ""
    for d, code, name, op, price, pos, reason in _SAMPLES:
        c = {"买入": "var(--accent)", "卖出": "var(--danger)"}.get(op, "var(--warning)")
        rows += f'<tr><td style="color:var(--muted);font-size:11px">{d}</td><td>{code}</td><td>{name}</td><td style="color:{c};font-weight:600">{op}</td><td>{price:.2f}</td><td>{pos}%</td><td style="color:var(--muted);font-size:11px">{reason}</td></tr>\n'
    return rows

_INPUT = 'style="width:75px;background:var(--bg);border:1px solid var(--border);color:var(--text);padding:4px 8px;border-radius:4px;font-size:12px"'

@router.get("/console/journal", response_class=HTMLResponse)
async def journal_page():
    return HTMLResponse(f"""\
<div>
  <h2 style="font-size:18px;margin:0 0 16px;color:var(--accent)">📓 交易日志</h2>
  <form class="card" style="margin-bottom:16px;display:flex;align-items:center;gap:8px;flex-wrap:wrap"
    hx-post="/console/api/journal/add" hx-target="#journal-feedback" hx-swap="outerHTML">
    <input name="code" placeholder="代码" required {_INPUT}>
    <select name="action" {_INPUT}><option>买入</option><option>卖出</option><option>持有</option></select>
    <input name="price" type="number" step="0.01" placeholder="价格" required {_INPUT}>
    <input name="position" type="number" step="0.1" placeholder="仓位%" required {_INPUT}>
    <input name="reason" placeholder="原因" style="flex:1;min-width:120px;{_INPUT[7:]}">
    <button type="submit" style="background:var(--accent);color:var(--bg);border:none;padding:5px 16px;border-radius:4px;font-weight:600;font-size:12px;cursor:pointer;font-family:inherit">＋ 记录</button>
  </form>
  <div id="journal-feedback"></div>
  <div class="card" style="padding:0;overflow-x:auto">
    <table><thead><tr><th>日期</th><th>代码</th><th>名称</th><th>操作</th><th>价格</th><th>仓位</th><th>原因</th></tr></thead>
    <tbody>{_table_rows()}</tbody></table>
  </div>
</div>""")

@router.post("/console/api/journal/add")
async def journal_add(request: Request):
    form = await request.form()
    code, action = str(form.get("code", "")), str(form.get("action", "买入"))
    price = float(str(form.get("price", 0)))
    position = float(str(form.get("position", 0)))
    reason = str(form.get("reason", ""))
    print(f"[journal] {date.today()} | {code} | {action} | {price:.2f} | {position}% | {reason}")
    _SAMPLES.insert(0, (str(date.today()), code, code, action, price, int(position), reason))
    return HTMLResponse(
        '<div id="journal-feedback"><span class="badge-s" style="font-size:12px">✓ 已记录</span></div>\n'
        + '<div class="card" style="padding:0;overflow-x:auto" hx-swap-oob="true" id="journal-table">'
        + f'<table><thead><tr><th>日期</th><th>代码</th><th>名称</th><th>操作</th><th>价格</th><th>仓位</th><th>原因</th></tr></thead><tbody>{_table_rows()}</tbody></table></div>'
    )
