from __future__ import annotations
from fastapi import APIRouter
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

router = APIRouter()

_EXPLAIN = {"600141": "兴发集团当前评分7.5(S池)。主要驱动力: 产业趋势9分(磷化铟衬底需求旺盛)。风险点: AI资本开支不确定性(置信度72%)。建议: 当前价位适合初始建仓30%。"}

class Rq(BaseModel): code: str; question: str = ""

@router.post("/console/api/copilot/explain")
async def explain(req: Rq):
    return JSONResponse({"text": _EXPLAIN.get(req.code, "请选择股票并输入问题，AI Copilot 将为您分析。"), "code": req.code})

@router.get("/console/copilot", response_class=HTMLResponse)
async def panel():
    return HTMLResponse("""<div style="display:flex;flex-direction:column;height:100%;gap:10px">
<h2 style="font-size:15px;margin:0;color:var(--accent)">🧠 AI Copilot</h2>
<div id="copilot-stock" style="color:var(--muted);font-size:11px;padding:6px;border:1px solid var(--border);border-radius:4px;background:var(--bg);text-align:center">选择一只股票查看分析</div>
<div id="copilot-msgs" style="flex:1;overflow-y:auto;font-size:12px;line-height:1.6;padding:8px;border:1px solid var(--border);border-radius:4px;background:var(--bg)">
<div style="color:var(--muted);text-align:center;padding:30px 0">💬 AI Copilot 就绪<br><span style="font-size:11px">在任意页面选择股票，或输入问题开始分析</span></div></div>
<div style="display:flex;gap:6px">
<input id="cpi" placeholder="输入问题..." onkeydown="if(event.key==='Enter')ask()"
 style="flex:1;background:var(--bg);color:var(--text);border:1px solid var(--border);border-radius:4px;padding:8px 10px;font-family:inherit;font-size:12px;outline:none">
<button onclick="ask()" id="cpb" style="background:var(--accent);color:var(--bg);border:none;border-radius:4px;padding:8px 14px;font-family:inherit;font-size:12px;font-weight:600;cursor:pointer">发送</button>
</div></div>
<script>
let cs=null;
function bubble(r,t){const m=document.getElementById('copilot-msgs'),b=r==='bot';m.innerHTML+=`<div style="margin-bottom:8px;display:flex;justify-content:${b?'flex-start':'flex-end'}"><div style="max-width:92%;padding:7px 10px;border-radius:8px;word-break:break-word;font-size:12px;line-height:1.5;background:${b?'var(--bg)':'var(--accent)'};color:${b?'var(--accent)':'var(--bg)'};border:${b?'1px solid var(--border)':'none'}">${b?'<span style="font-size:10px;color:var(--muted);display:block;margin-bottom:2px">🤖 Copilot</span>':''}${t}</div></div>`;m.scrollTop=m.scrollHeight}
async function ask(){const i=document.getElementById('cpi'),b=document.getElementById('cpb'),q=i.value.trim();if(!q)return;bubble('user',q);i.value='';b.textContent='...';b.disabled=1;try{const r=await fetch('/console/api/copilot/explain',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({code:cs||'',question:q})});bubble('bot',(await r.json()).text)}catch(e){bubble('bot','❌ '+e.message)}b.textContent='发送';b.disabled=0}
window.addEventListener('fenjue:select-stock',function(e){cs=e.detail?.code||null;const el=document.getElementById('copilot-stock');if(cs&&e.detail?.name){el.innerHTML=`<span class="badge-s">${cs}</span> ${e.detail.name}`;el.style.color='var(--text)';bubble('bot',`已选中 ${e.detail.name} (${cs})，随时向我提问。`)}else{el.textContent='选择一只股票查看分析';el.style.color='var(--muted)'}});
</script>""")
