import json
idx = json.load(open('/opt/data/fenjue/data/index_sh000001.json'))
s = [k for k in idx if '2026-09-01' <= k['date'] <= '2026-09-18']
aug = [k for k in idx if k['date'] < '2026-09-01'][-1]
print(f"上证 8月末收 {aug['close']} → 9/18 收 {s[-1]['close']}：{(s[-1]['close']/aug['close']-1)*100:+.2f}%")
for code, nm in [('601838', '成都银行'), ('600919', '江苏银行'), ('601229', '上海银行'),
                 ('601077', '渝农商行'), ('000333', '美的集团')]:
    ks = json.load(open(f'/opt/data/fenjue/data/big_kcache/{code}.json'))
    seg = [k for k in ks if '2026-09-01' <= k['date'] <= '2026-09-18']
    prev = [k for k in ks if k['date'] < '2026-09-01'][-1]
    if seg:
        print(f"{nm}: 9月 {(seg[-1]['close']/prev['close']-1)*100:+.2f}%")