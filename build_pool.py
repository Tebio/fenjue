#!/usr/bin/env python3
"""T-1备选池构建: 沪深主板 + 成交额前300 + 站上MA20 + 站上MA120 + PE
用法: python3 build_pool.py YYYYMMDD
产出: /opt/data/fenjue/pool_YYYYMMDD.json

数据源: stock_zt_pool_strong_em(东财强势股池) + stock_zh_a_daily(Sina K线) + Sina实时报价(PE)
"""
import os, sys, json, time, math

for k in list(os.environ.keys()):
    if 'proxy' in k.lower(): del os.environ[k]

import akshare as ak

DATE = sys.argv[1] if len(sys.argv) > 1 else '20260507'
print(f'⏳ {DATE} 备选池构建中...', flush=True)

# ── Step 1: 强势股池 ──
qs = ak.stock_zt_pool_strong_em(date=DATE)
print(f'强势股池: {len(qs)}只', flush=True)

def is_main(code):
    c = str(code)
    return c[:3] in ('600','601','603','605') or c[:3] in ('000','001','002','003')

def to_sina(code):
    c = str(code)
    return ('sh' if c[0] == '6' else 'sz') + c

qs = qs[qs['代码'].apply(is_main)].copy()
print(f'沪深主板: {len(qs)}只', flush=True)

# ── Step 2: 成交额前300 ──
qs = qs.sort_values('成交额', ascending=False).head(300)
print(f'成交额前300: {len(qs)}只 (最低{qs["成交额"].min()/1e8:.1f}亿)', flush=True)

# ── Step 3: K线算MA ──
codes = qs['代码'].tolist()
print(f'拉取{len(codes)}只K线(Sina源)...', flush=True)

results = []
errors = 0
start = time.time()
for i, (_, row) in enumerate(qs.iterrows()):
    code = row['代码']
    try:
        sina_code = to_sina(code)
        hist = ak.stock_zh_a_daily(symbol=sina_code, start_date='20250801', end_date=DATE, adjust='qfq')
        if len(hist) < 120:
            errors += 1; time.sleep(0.2); continue
        closes = hist['close'].tolist()
        ma5 = sum(closes[-5:]) / 5
        ma20 = sum(closes[-20:]) / 20
        ma120 = sum(closes[-120:]) / 120
        close = closes[-1]
        if close > ma20 and close > ma120:
            results.append(dict(
                code=code, name=row['名称'],
                price=float(row['最新价']), pct=float(row['涨跌幅']),
                amount_yi=round(row['成交额']/1e8, 1),
                mcap_yi=round(row['总市值']/1e8, 1),
                turnover=float(row['换手率']),
                sector=row.get('所属行业', ''),
                ma5=round(ma5, 2), ma20=round(ma20, 2), ma120=round(ma120, 2),
                line_signal='MA5' if close > ma5 else 'MA20',
            ))
    except Exception:
        errors += 1
    time.sleep(0.3)
    if (i+1) % 30 == 0:
        e = time.time()-start
        print(f'  {i+1}/{len(codes)} ({e:.0f}s) 通过{len(results)} 错{errors}', flush=True)

elapsed = time.time() - start
results.sort(key=lambda x: x['amount_yi'], reverse=True)
print(f'\n✅ MA完成! {elapsed:.0f}秒 | 通过{len(results)}只 | 错误{errors}', flush=True)

# ── Step 4: 批量拉PE (Sina实时报价, 每批80只, 1秒间隔) ──
import urllib.request
BATCH = 80
passed_codes = [r['code'] for r in results]
pe_map = {}
print(f'拉取{len(passed_codes)}只PE(Sina报价)...', flush=True)

for b in range(0, len(passed_codes), BATCH):
    batch = passed_codes[b:b+BATCH]
    sina_list = ','.join(to_sina(c) for c in batch)
    try:
        url = f'http://hq.sinajs.cn/list={sina_list}'
        req = urllib.request.Request(url, headers={'Referer': 'https://finance.sina.com.cn'})
        resp = urllib.request.urlopen(req, timeout=15)
        text = resp.read().decode('gbk', errors='replace')
        for line in text.strip().split('\n'):
            if '=' not in line: continue
            part = line.split('=')[1].strip('";')
            if not part: continue
            fields = part.split(',')
            # Sina字段索引: [0]名称 [1]今开 [2]昨收 [3]现价 ... [41]市盈率(动态)
            if len(fields) > 42:
                try:
                    pe = float(fields[42])
                    if pe > 0 and not math.isinf(pe):
                        code_key = line.split('=')[0].replace('var hq_str_', '').replace('sh','').replace('sz','')
                        pe_map[code_key] = round(pe, 2)
                except (ValueError, IndexError):
                    pass
    except Exception as e:
        print(f'  PE批次{b//BATCH+1}失败: {e}', flush=True)
    time.sleep(1)
    if (b+BATCH) % 160 == 0:
        print(f'  {b+BATCH}/{len(passed_codes)} 已拉取', flush=True)

# ── Step 5: 写入PE ──
for r in results:
    r['pe'] = pe_map.get(str(r['code']))

pe_count = sum(1 for r in results if r.get('pe'))
print(f'PE覆盖率: {pe_count}/{len(results)}', flush=True)

# ── 输出 ──
print(f'\n📋 备选池: {len(results)}只 | 沪深主板 成交额前300 站上MA20 站上MA120\n', flush=True)
for r in results[:50]:
    pe_str = f'PE={r["pe"]:.0f}' if r.get('pe') else 'PE=--'
    print(f"{r['code']} {r['name']:<8} {r['price']:>7.2f} {r['pct']:>+6.2f}% {r['amount_yi']:>5.0f}亿 MA20={r['ma20']} {pe_str} {r['sector']}", flush=True)
if len(results) > 50:
    print(f'... 还有{len(results)-50}只', flush=True)

os.makedirs('/opt/data/fenjue', exist_ok=True)
outpath = f'/opt/data/fenjue/pool_{DATE}.json'
with open(outpath, 'w') as fh:
    json.dump({'date': DATE, 'count': len(results), 'results': results, 'elapsed_s': round(elapsed)}, fh, ensure_ascii=False, indent=2)
print(f'\n💾 {outpath}', flush=True)
