#!/usr/bin/env python3
"""engine/news_event_study.py — 快讯提及个股的事件研究（2026-09-12 用户立项）

问题：消息面工具（韭研公社/快讯/盘中宝类）能不能变成买点？
设计：回填新浪7x24约2个月 → 提取个股提及 → 按发布时间决定入场 → 测净收益。
分类：
  复盘提及（名字±12字内有涨停/跌停/大涨）= 事后播报，预期无前瞻价值（对照组）
  资讯提及（其余）= 可能有信息含量（试验组）
入场口径：盘中(9:30-15:00BJT)发布 → 当日尾盘买 与 次日开盘买 两变体；
         盘后/非交易日发布 → 次日开盘买。
离场：入场日尾盘(T+1腿) / 第5交易日尾盘(T+5腿)。净-0.15%，附同日全宇宙超额。
"""
import json, glob, re, time, statistics as st
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.request import Request, urlopen, build_opener, ProxyHandler

ROOT = Path("/opt/data/fenjue")
KC = ROOT / "data/big_kcache"
OUT = ROOT / "data/news_event_study_20260912.json"
FEE = 0.0015
BJT = timezone(timedelta(hours=8))
op = build_opener(ProxyHandler({}))
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}


def backfill(pages=70):
    items = []
    for p in range(1, pages + 1):
        u = f'https://feed.mix.sina.com.cn/api/roll/get?pageid=153&lid=2515&num=50&page={p}'
        try:
            d = json.loads(op.open(Request(u, headers=UA), timeout=15).read().decode('utf-8', 'ignore'))
            rows = d.get('result', {}).get('data', [])
            if not rows:
                break
            items.extend(rows)
        except Exception as e:
            print(f'page{p} err {e}', flush=True)
        time.sleep(0.4)
    return items


def backfill_cls(days=14):
    """财联社电报回填：refresh_type=1 + last_time 递减翻页（签名算法抄 akshare）"""
    import hashlib
    from urllib.parse import urlencode
    items, lt = [], int(time.time())
    stop = lt - days * 86400
    hops = 0
    while lt > stop and hops < 400:
        params = {"app": "CailianpressWeb", "category": "", "last_time": lt,
                  "os": "web", "refresh_type": "1", "rn": "50", "sv": "8.4.6"}
        params["sign"] = hashlib.md5(
            hashlib.sha1(urlencode(params).encode()).hexdigest().encode()).hexdigest()
        try:
            d = json.loads(op.open(Request(
                'https://www.cls.cn/v1/roll/get_roll_list?' + urlencode(params),
                headers=UA), timeout=15).read().decode('utf-8', 'ignore'))
            rows = d.get('data', {}).get('roll_data', [])
        except Exception as e:
            print(f'cls hop{hops} err {e}', flush=True)
            rows = []
        if not rows:
            break
        for r in rows:
            items.append({'intime': r['ctime'],
                          'title': r.get('title', ''),
                          'summary': re.sub(r'<[^>]+>', '', r.get('content', ''))[:200],
                          'level': r.get('level', '')})
        lt = min(r['ctime'] for r in rows) - 1
        hops += 1
        time.sleep(0.35)
    print(f'cls backfill: {len(items)}条 {hops}hops', flush=True)
    return items


def main():
    t0 = time.time()
    # 名→码（len>=3 防爆 2 字歧义）
    pool = json.loads(open(ROOT / 'data/main_board_codes.json').read())['stocks']
    name2code = {s['name']: s['code'] for s in pool if len(s['name']) >= 3}
    print('names:', len(name2code), flush=True)

    items = backfill()
    print('sina backfilled:', len(items), flush=True)
    cls_items = backfill_cls(days=14)
    for ci in cls_items:
        ci['_src'] = 'cls'
    for si in items:
        si['_src'] = 'sina'

    # 交易日历 + 日K
    cal = sorted(k['date'] for k in json.loads(open(KC / '000001.json').read()))
    cidx = {d: i for i, d in enumerate(cal)}
    kd = {}
    need = set()
    recs = []  # (code, pub_dt_bjt, kind)
    seen_sd = set()
    for it in items + cls_items:
        ts = int(it.get('intime', 0) or 0)
        if not ts:
            continue
        pdt = datetime.fromtimestamp(ts, BJT)
        text = (it.get('title', '') + ' ' + re.sub(r'<[^>]+>', '', it.get('summary', '')))
        for name, code in name2code.items():
            pos = text.find(name)
            if pos < 0:
                continue
            ctx = text[max(0, pos - 12):pos + len(name) + 12]
            kind = '复盘' if re.search(r'涨停|跌停|大涨|大跌|封板|炸板', ctx) else '资讯'
            key = (code, pdt.strftime('%Y-%m-%d'), kind, it.get('_src'))
            if key in seen_sd:
                continue
            seen_sd.add(key)
            recs.append((code, pdt, kind))
            need.add(code)
    print('mention events:', len(recs), 'codes:', len(need), flush=True)

    for code in need:
        fp = KC / f'{code}.json'
        if fp.exists():
            ks = json.loads(open(fp).read())
            kd[code] = {k['date']: (k['open'], k['close']) for k in ks}

    def next_td(dstr):
        i = cidx.get(dstr)
        if i is None:
            later = [d for d in cal if d > dstr]
            return later[0] if later else None
        return dstr

    R = {}
    for kind in ('资讯', '复盘'):
        for entry_mode in ('盘中尾盘买', '次日开盘买'):
            rs1, rs5, xs1 = [], [], []
            for code, pdt, k_ in recs:
                if k_ != kind or code not in kd:
                    continue
                d0 = pdt.strftime('%Y-%m-%d')
                hm = pdt.hour * 100 + pdt.minute
                intraday = (930 <= hm <= 1500) and d0 in cidx
                # 入场日：盘中→d0（尾盘价买）；盘后/非交易日→d0之后第一个交易日（开盘价买）
                if entry_mode == '盘中尾盘买':
                    if not intraday:
                        continue
                    ed = d0
                    px_e = kd[code].get(ed, (None, None))[1]
                    off1, off5 = 1, 5   # 尾盘买：短腿=次日尾盘
                else:
                    later = [d for d in cal if d > d0]
                    if not later:
                        continue
                    ed = later[0]
                    if ed not in kd[code]:
                        continue
                    px_e = kd[code][ed][0]
                    off1, off5 = 0, 4   # 开盘买：短腿=当日尾盘（对齐项目T+1口径）
                if not px_e:
                    continue
                i_e = cidx.get(ed)
                d1 = cal[i_e + off1] if i_e is not None and i_e + off1 < len(cal) else None
                d5 = cal[i_e + off5] if i_e is not None and i_e + off5 < len(cal) else None
                if d1 and d1 in kd[code]:
                    rs1.append(kd[code][d1][1] / px_e - 1 - FEE)
                if d5 and d5 in kd[code]:
                    rs5.append(kd[code][d5][1] / px_e - 1 - FEE)
            def S(rs):
                return {"n": len(rs), "win%": round(100 * sum(r > 0 for r in rs) / len(rs), 1),
                        "net%": round(100 * st.mean(rs), 2)} if len(rs) >= 30 else None
            R[f'{kind}×{entry_mode}'] = {"T+1尾盘": S(rs1), "T+5尾盘": S(rs5)}
            print(kind, entry_mode, 'done', flush=True)

    R['_meta'] = {'window': '新浪7x24回填~2个月', 'fee': FEE, 'events': len(recs),
                  'note': '名→码仅len>=3；复盘=名字±12字内有涨停等词=事后播报'}
    OUT.write_text(json.dumps(R, ensure_ascii=False, indent=1))
    print(json.dumps(R, ensure_ascii=False, indent=1))
    print('saved', OUT, f'{time.time()-t0:.0f}s')


if __name__ == '__main__':
    main()
