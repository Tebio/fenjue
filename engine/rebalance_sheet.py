#!/usr/bin/env python3
"""调样抢跑作战单生成器(确定性版) —— 2026-11-27 cron 专用
链路: CNFIN公告流找最新'定期调整'公告 → AnnouncementLink提csindex id →
      queryAnnouncementById拿附件PDF → pypdf解析调出/调入名单 →
      作战单md落盘 + 紧凑摘要打印(推送用)。幂等: 同公告id已生成则[SKIP]。
冒烟测试: python engine/rebalance_sheet.py --test  (解析2026-05期,不写正式产出)
"""
import json, os, subprocess, time, re, sys

ROOT='/opt/data/fenjue'
OUT_MD=f'{ROOT}/data/rebalance_2026H2_sheet.md'
STATE=f'{ROOT}/data/rebalance_sheet_state.json'
EXPECTED_EFFECTIVE='2026-12-11'
INDEX_MAP={'沪深 300':'000300','中证 500':'000905','中证 1000':'000852','沪深300':'000300','中证500':'000905','中证1000':'000852'}

def curl_json(url, data=None, retries=3):
    args=['curl','-s',url,'-H','User-Agent: Mozilla/5.0','--max-time','25']
    if data:
        args.append('-X','POST')
        for k,v in data.items(): args+=['-d',f'{k}={v}']
    for k in range(retries):
        r=subprocess.run(args,capture_output=True,text=True)
        try: return json.loads(r.stdout)
        except Exception: time.sleep(3*(k+1))
    return {}

def find_latest_ann():
    for p in range(1,4):
        d=curl_json('https://api.cnfin.com/roll/announcement/indexAnnouncement',{'pageNo':p,'pageSize':50,'secuCode':'000300'})
        rows=(d.get('data') or {}).get('data') or []
        for r in rows:
            t=r.get('InfoTitle','')
            if '定期调整' in t and '样本' in t:
                link=r.get('AnnouncementLink','')
                m=re.search(r'id=(\d+)', link)
                return {'id':r['ID'],'csindex_id':m.group(1) if m else None,
                        'date':r['InfoPublDate'][:10],'title':t}
        time.sleep(1)
    return None

def fetch_pdf_text(csindex_id):
    d=curl_json(f'https://www.csindex.com.cn/csindex-home/announcement/queryAnnouncementById?id={csindex_id}')
    enc=(d.get('data') or {}).get('enclosureList') or []
    pdf=[e for e in enc if e.get('fileUrl','').endswith('.pdf')]
    if not pdf: return None, None
    url=pdf[0]['fileUrl']
    tmp='/tmp/rebalance_adj.pdf'
    subprocess.run(['curl','-s',url,'-o',tmp,'--max-time','60'])
    from pypdf import PdfReader
    txt='\n'.join(p.extract_text() for p in PdfReader(tmp).pages)
    return txt, url

def parse_lists(txt):
    """返回 {'000300':{'in':[(code,name)],'out':[...]}, ...}"""
    res={}
    # 按指数段切: '沪深 300 指数样本调整名单' 等标题
    seg_pat=re.compile(r'(沪深 ?300|中证 ?500|中证 ?1000) ?指数样本调整名单')
    marks=[(m.start(), INDEX_MAP.get(m.group(1).replace(' ','') if ' ' not in m.group(1) else m.group(1), None) or INDEX_MAP[m.group(1)]) for m in seg_pat.finditer(txt)]
    line_pat=re.compile(r'\b((?:60|00|30|68)\d{4})\s+([一-龥A-Za-z]+)\s+((?:60|00|30|68)\d{4})\s+([一-龥A-Za-z]+)')
    single_pat=re.compile(r'^\s*((?:60|00|30|68)\d{4})\s+([一-龥A-Za-z]+)\s*$')
    for i,(pos,idx) in enumerate(marks):
        end=marks[i+1][0] if i+1<len(marks) else len(txt)
        seg=txt[pos:end]
        sec=res.setdefault(idx,{'in':[],'out':[]})
        for line in seg.split('\n'):
            m=line_pat.search(line)
            if m:
                sec['out'].append((m.group(1),m.group(2)))
                sec['in'].append((m.group(3),m.group(4)))
            else:
                m2=single_pat.match(line)
                if m2 and sec['in']:  # 尾行单边(调出多一只)
                    sec['out'].append((m2.group(1),m2.group(2)))
    return res

def cap_of(code):
    p=f'{ROOT}/data/cap_hist/{code}.json'
    if not os.path.exists(p): return None
    arr=json.load(open(p))
    return arr[-1][2] if arr else None

def main():
    test='--test' in sys.argv
    if test:
        txt,url=fetch_pdf_text('3006137')
        res=parse_lists(txt)
        for idx,sec in res.items():
            print(idx, '调入', len(sec['in']), '调出', len(sec['out']), '样例:', sec['in'][:3])
        return
    st=json.load(open(STATE)) if os.path.exists(STATE) else {}
    ann=find_latest_ann()
    if not ann:
        print('[FAIL] CNFIN未找到最新调样公告'); sys.exit(2)
    if st.get('ann_id')==ann['id'] and os.path.exists(OUT_MD):
        print(f"[SKIP] 作战单已生成(公告{ann['date']})"); return
    if not ann['csindex_id']:
        print('[FAIL] 公告无csindex链接'); sys.exit(3)
    txt,pdf_url=fetch_pdf_text(ann['csindex_id'])
    if not txt:
        print('[FAIL] PDF获取/解析失败'); sys.exit(4)
    lists=parse_lists(txt)
    all_in=[]
    for idx,sec in lists.items():
        for c,n in sec['in']:
            all_in.append({'code':c,'name':n,'index':idx,'cap':cap_of(c)})
    sane = 20 <= len(all_in) <= 300 and all(lists.get(k) for k in ('000300','000905'))
    if not sane:
        print(f'[WARN] 名单规模异常({len(all_in)}),仍落盘但需人工核对')
    lines=[f"# 调样抢跑作战单 —— 公告 {ann['date']}（生效日应为 {EXPECTED_EFFECTIVE} 收市后）","",
           f"公告: {ann['title']}",f"PDF: {pdf_url}","",
           f"调入合计 {len(all_in)} 只 {'✅' if sane else '⚠️人工核对'}","",
           "## 买入清单（公告次日周一 9:25 竞价挂单等权买入；生效日 12-11 尾盘竞价卖出）","",
           "| 代码 | 名称 | 调入指数 | 流通市值(亿) |","|---|---|---|---|"]
    for r in sorted(all_in, key=lambda x:(x['index'], x['code'])):
        lines.append(f"| {r['code']} | {r['name']} | {r['index']} | {r['cap'] if r['cap'] else '?'} |")
    lines += ["", "## 执行要点（#242/#242b 实测定版）",
              "- 入场: 公告次日 9:25 竞价直接挂(跳空毒性实测无; 等待单调烧钱)",
              "- 持有: ~10交易日, 匹配超额参考 +1.8pp, 13周期12正",
              "- 出场: 生效日收盘卖——被动盘MOC单尾盘集中成交(+0.27%), 尾盘卖出即吃被动买单",
              "- 作废: 若遇大盘崩跌窗(2024-11型), 减半仓执行",
              "", "研究辅助, 不是买卖指令。"]
    open(OUT_MD,'w').write('\n'.join(lines))
    json.dump({'ann_id':ann['id'],'csindex_id':ann['csindex_id'],'ann_date':ann['date'],'count':len(all_in)}, open(STATE,'w'))
    print(f"[OK] 作战单: {OUT_MD} | 公告{ann['date']} 调入{len(all_in)}只 "
          f"(300:{len(lists.get('000300',{}).get('in',[]))} 500:{len(lists.get('000905',{}).get('in',[]))} 1000:{len(lists.get('000852',{}).get('in',[]))})")

if __name__=='__main__':
    main()
