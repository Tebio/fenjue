"""
Explain route — score breakdown with bar chart + contributions.
"""
from __future__ import annotations
from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse, JSONResponse

router = APIRouter()

STOCKS = [{"code":"600141","name":"兴发集团"},{"code":"002428","name":"云南锗业"},{"code":"600206","name":"有研新材"},{"code":"002409","name":"雅克科技"},{"code":"600584","name":"长电科技"}]  # noqa: E501

_EXPLAIN = {
    "600141":{"total":7.15,"bd":[{"d":"产业趋势","s":9,"w":0.35,"c":3.15},{"d":"资金流向","s":8,"w":0.25,"c":2.00},{"d":"机构","s":5,"w":0.10,"c":0.50},{"d":"融资","s":8,"w":0.10,"c":0.80},{"d":"量化","s":5,"w":0.05,"c":0.25},{"d":"预期兑现","s":3,"w":0.15,"c":0.45}]},
    "002428":{"total":7.70,"bd":[{"d":"产业趋势","s":8,"w":0.35,"c":2.80},{"d":"资金流向","s":9,"w":0.25,"c":2.25},{"d":"机构","s":6,"w":0.10,"c":0.60},{"d":"融资","s":7,"w":0.10,"c":0.70},{"d":"量化","s":6,"w":0.05,"c":0.30},{"d":"预期兑现","s":7,"w":0.15,"c":1.05}]},
    "600206":{"total":7.50,"bd":[{"d":"产业趋势","s":7,"w":0.35,"c":2.45},{"d":"资金流向","s":8,"w":0.25,"c":2.00},{"d":"机构","s":6,"w":0.10,"c":0.60},{"d":"融资","s":7,"w":0.10,"c":0.70},{"d":"量化","s":5,"w":0.05,"c":0.25},{"d":"预期兑现","s":10,"w":0.15,"c":1.50}]},
    "002409":{"total":7.20,"bd":[{"d":"产业趋势","s":7,"w":0.35,"c":2.45},{"d":"资金流向","s":6,"w":0.25,"c":1.50},{"d":"机构","s":7,"w":0.10,"c":0.70},{"d":"融资","s":5,"w":0.10,"c":0.50},{"d":"量化","s":8,"w":0.05,"c":0.40},{"d":"预期兑现","s":11,"w":0.15,"c":1.65}]},
    "600584":{"total":6.80,"bd":[{"d":"产业趋势","s":5,"w":0.35,"c":1.75},{"d":"资金流向","s":7,"w":0.25,"c":1.75},{"d":"机构","s":8,"w":0.10,"c":0.80},{"d":"融资","s":5,"w":0.10,"c":0.50},{"d":"量化","s":4,"w":0.05,"c":0.20},{"d":"预期兑现","s":12,"w":0.15,"c":1.80}]},
}

def _norm(data: dict) -> dict:
    return {"total":data["total"],"breakdown":[{"dim":b["d"],"score":b["s"],"weight":b["w"],"contrib":b["c"]} for b in data["bd"]]}


@router.get("/console/api/explain")
async def api_explain(code: str = Query(...)):
    data = _EXPLAIN.get(code, _EXPLAIN.get("600141", {}))
    return JSONResponse(content=_norm(data))


_JS = """<script>
const B='█',G='░',SL=[__STOCKS__];function br(s){let t='';for(let i=0;i<10;i++)t+=i<s?B:G;return t}
function cc(s){return s>=8?'var(--accent)':s>=5?'var(--warning)':'var(--danger)'}
async function lx(c){document.getElementById('est').textContent='⏳';try{let r=await fetch('/console/api/explain?code='+c);if(!r.ok)throw Error(r.status);render(await r.json(),c);document.getElementById('est').textContent='✅'}catch(e){document.getElementById('est').textContent='❌'+e}}
function render(d,c){let bd=d.breakdown||[],st=SL.find(s=>s.c===c)||{n:''},rs='';bd.forEach(b=>{rs+=`<div style="display:flex;align-items:center;gap:8px;padding:10px 0;border-bottom:1px solid var(--border)">
<span style="width:64px;font-size:12px;flex-shrink:0">$${b.dim}</span>
<span style="width:34px;text-align:right;font-weight:600;color:$${cc(b.score)};flex-shrink:0">$${b.score}/10</span>
<span style="font-family:monospace;font-size:14px;letter-spacing:2px;color:$${cc(b.score)};flex-shrink:0">$${br(b.score)}</span>
<span style="color:var(--accent);font-weight:600;width:55px;text-align:right;flex-shrink:0">+$${b.contrib.toFixed(2)}</span>
<span style="color:var(--muted);font-size:10px">(×$${b.weight.toFixed(2)})</span>
</div>`});document.getElementById('ep').innerHTML=`<div>
<div style="font-size:16px;margin-bottom:16px;padding-bottom:12px;border-bottom:2px solid var(--border)">
<span style="color:var(--text)">$${st.n}</span><span style="color:var(--muted)"> $${c}</span><span style="margin-left:12px;color:var(--muted)">总分</span><span class="stat" style="font-size:22px;color:var(--accent)">$${d.total.toFixed(2)}</span></div>
$${rs}<div style="margin-top:12px;padding-top:12px;border-top:2px solid var(--accent);display:flex;align-items:center;gap:8px"><span style="color:var(--muted);width:64px;flex-shrink:0">总分</span><span class="stat" style="font-size:22px;color:var(--accent)">$${d.total.toFixed(2)}</span></div></div>`}
(function(){let s=document.getElementById('es');if(s&&s.value)lx(s.value)})();
</script>"""


@router.get("/console/explain", response_class=HTMLResponse)
async def explain_page():
    opts = "".join(f'<option value="{s["code"]}">{s["code"]} {s["name"]}</option>' for s in STOCKS)
    sc_json = ",".join('{"c":"%s","n":"%s"}' % (s["code"], s["name"]) for s in STOCKS)
    js = _JS.replace("__STOCKS__", sc_json)
    html = f"""<div>
  <h2 style="font-size:18px;margin:0 0 16px;color:var(--accent)">🔍 评分分解</h2>
  <div class="card" style="margin-bottom:16px">
    <div class="card-title">股票选择</div>
    <div style="display:flex;gap:12px;align-items:center">
      <select id="es" onchange="lx(this.value)" style="background:var(--bg);color:var(--text);border:1px solid var(--border);border-radius:4px;padding:6px 10px;font-family:inherit;font-size:13px;min-width:200px">{opts}</select>
      <span id="est" style="color:var(--muted);font-size:11px"></span>
    </div>
  </div>
  <div class="card" id="ep" style="min-height:320px">
    <div style="color:var(--muted);text-align:center;padding:60px 0">选择股票查看评分分解</div>
  </div>
</div>
{js}"""
    return HTMLResponse(content=html)
