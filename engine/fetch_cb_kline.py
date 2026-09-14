"""#80① 可转债日线回填 v2（新浪加密K线+py_mini_racer解码，断点续跑+限速1.2s）
push2his 全封(直连/代理双灭)后的可用通道，实测 sh113545=1434根。
产出: data/cb_kcache/<债券代码>.json [{date,open,high,low,close,volume}]
"""
import json, time, sys, datetime
from pathlib import Path

ROOT = Path('/opt/data/fenjue')
OUT = ROOT / 'data/cb_kcache'
OUT.mkdir(exist_ok=True)

def main():
    sys.path.insert(0, '/opt/data/python-libs')
    import requests, py_mini_racer, akshare as ak
    from akshare.bond.bond_zh_cov import zh_sina_bond_hs_cov_hist_url
    from akshare.stock.cons import hk_js_decode

    df = ak.bond_zh_cov()
    listed = df[df['上市时间'].notna()]
    print(f'在交易转债: {len(listed)}', flush=True)
    js = py_mini_racer.MiniRacer()
    js.eval(hk_js_decode)
    today = datetime.datetime.now().strftime('%Y_%m_%d')
    done = {p.stem for p in OUT.glob('*.json')}
    ok = fail = skip = 0
    for _, r in listed.iterrows():
        code = str(r['债券代码']).zfill(6)
        if code in done:
            skip += 1
            continue
        mkt = 'sh' if code.startswith('11') else 'sz'
        try:
            url = zh_sina_bond_hs_cov_hist_url.format(mkt + code, today)
            resp = requests.get(url, timeout=15)
            raw = resp.text
            if '="' not in raw:
                fail += 1
                time.sleep(1.2)
                continue
            lst = js.call('d', raw.split('=')[1].split(';')[0].replace('"', ''))
            if lst:
                rows = [{'date': b['date'][:10], 'open': float(b['open']), 'high': float(b['high']),
                         'low': float(b['low']), 'close': float(b['close']),
                         'volume': float(b.get('volume', 0) or 0)} for b in lst]
                (OUT / f'{code}.json').write_text(json.dumps(rows))
                done.add(code)
                ok += 1
            else:
                fail += 1
        except Exception:
            fail += 1
        if (ok + fail) % 50 == 0:
            print(f'[{ok+fail}] ok={ok} fail={fail} skip={skip}', flush=True)
        time.sleep(1.2)
    print(f'完成: ok={ok} fail={fail} skip={skip} 总库={len(done)}')

if __name__ == '__main__':
    main()
