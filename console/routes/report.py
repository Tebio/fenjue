"""
Daily Report route — market summary + sector moves + S-pool + catalysts.
Hardcoded data; returns HTML fragment for the #content div.
"""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter()


@router.get("/console/report", response_class=HTMLResponse)
async def report(request: Request) -> HTMLResponse:
    # ── Market Summary (grid-4 cards) ────────────────────────
    market_cards = """
    <div class="grid-4" style="margin-bottom:20px">
      <div class="card">
        <div class="card-title">市场状态</div>
        <div class="stat">Risk-Neutral</div>
        <div class="label">量化信号中性偏多</div>
      </div>
      <div class="card">
        <div class="card-title">仓位上限</div>
        <div class="stat">60%</div>
        <div class="label">单票上限 30%</div>
      </div>
      <div class="card">
        <div class="card-title">量化主导</div>
        <div class="stat" style="color:var(--accent)">★★★★☆</div>
        <div class="label">量价信号强度</div>
      </div>
      <div class="card">
        <div class="card-title">纳指参考</div>
        <div class="stat">震荡</div>
        <div class="label">联动系数 ×1.05</div>
      </div>
    </div>
    """

    # ── Sector Radar ─────────────────────────────────────────
    sector_moves = """
    <h3 style="font-size:14px;margin:0 0 10px;color:var(--muted)">🏭 产业雷达</h3>
    <div class="card" style="display:flex;gap:24px;flex-wrap:wrap;font-size:14px">
      <span class="stat-up" style="white-space:nowrap">↑ AI材料 <strong>+1.2%</strong></span>
      <span class="stat-down" style="white-space:nowrap">↓ 机器人 <strong>-0.5%</strong></span>
      <span style="color:var(--muted);white-space:nowrap">— 军工 平</span>
      <span style="color:var(--muted);white-space:nowrap">— 半导体 平</span>
      <span class="stat-down" style="white-space:nowrap">↓ 新能源 <strong>-0.8%</strong></span>
    </div>
    """

    # ── S-Pool Table ─────────────────────────────────────────
    s_pool = """
    <h3 style="font-size:14px;margin:20px 0 10px;color:var(--muted)">⭐ S池表现</h3>
    <div class="card" style="padding:0;overflow-x:auto">
      <table>
        <thead><tr>
          <th>代码</th><th>名称</th><th>今日评分</th><th>变化</th><th>原因</th>
        </tr></thead>
        <tbody>
          <tr style="background:rgba(0,212,170,0.06)">
            <td style="color:var(--accent)">600141</td>
            <td>兴发集团</td>
            <td>7.5</td>
            <td class="stat-up">+0.2</td>
            <td>产业热度上升</td>
          </tr>
          <tr style="background:rgba(0,212,170,0.06)">
            <td style="color:var(--accent)">002428</td>
            <td>云南锗业</td>
            <td>7.2</td>
            <td class="stat-down">-0.3</td>
            <td>融资下降</td>
          </tr>
          <tr style="background:rgba(0,212,170,0.04)">
            <td style="color:var(--accent)">600206</td>
            <td>有研新材</td>
            <td>6.8</td>
            <td class="stat-up">+0.1</td>
            <td>资金回流</td>
          </tr>
        </tbody>
      </table>
    </div>
    """

    # ── Today's Alert ─────────────────────────────────────────
    today_alert = """
    <h3 style="font-size:14px;margin:20px 0 10px;color:var(--muted)">🚨 今日警报</h3>
    <div class="card" style="padding:0;overflow-x:auto">
      <table>
        <thead><tr>
          <th>信号</th><th>代码</th><th>名称</th><th>关键指标</th><th>建议</th>
        </tr></thead>
        <tbody>
          <tr style="background:rgba(255,107,107,0.08)">
            <td><span style="color:#ff6b6b;font-size:16px">⚠</span></td>
            <td style="color:var(--accent)">002428</td>
            <td>云南锗业</td>
            <td>放量14% 融资切换中</td>
            <td>暂停加仓,等融资数据</td>
          </tr>
          <tr style="background:rgba(0,212,170,0.06)">
            <td><span style="color:var(--accent);font-size:16px">✓</span></td>
            <td style="color:var(--accent)">600141</td>
            <td>兴发集团</td>
            <td>换手稳定3.7%</td>
            <td>可持有,仓位限30%</td>
          </tr>
          <tr style="background:rgba(0,212,170,0.06)">
            <td><span style="color:var(--accent);font-size:16px">✓</span></td>
            <td style="color:var(--accent)">002409</td>
            <td>雅克科技</td>
            <td>涨停+融资得分9 锁仓</td>
            <td>可加仓至20%</td>
          </tr>
        </tbody>
      </table>
      <div style="padding:8px 16px;font-size:11px;color:var(--muted)">
        规则：⚠高风险（换手>12%/跌幅<-5%/资金危险/融资≤3）| ✓低风险（换手<5%+资金健康+融资≥8）| 中等标·
      </div>
    </div>
    """

    # ── Upcoming Catalysts ───────────────────────────────────
    catalysts = """
    <h3 style="font-size:14px;margin:20px 0 10px;color:var(--muted)">📅 下周催化</h3>
    <div class="card">
      <ul style="margin:0;padding-left:18px;line-height:1.8;font-size:13px">
        <li>8月 <span style="color:var(--accent)">东山精密</span> 半年报披露</li>
        <li>Q3 <span style="color:var(--accent)">兴发集团</span> 磷化铟扩产投产</li>
        <li>7/10 <span style="color:var(--accent)">云南锗业</span> 红外材料订单公告</li>
        <li>7月中 军工电子招标季开启</li>
      </ul>
    </div>
    """

    html = f"""
    <div>
      <h2 style="font-size:18px;margin:0 0 16px;color:var(--accent)">📰 焚訣日报 — 2026-07-07</h2>
      {market_cards}
      {sector_moves}
      {s_pool}
      {today_alert}
      {catalysts}
    </div>
    """

    return HTMLResponse(content=html)
