#!/usr/bin/env python3
"""Red-team driver: batch LLM calls to generate kill conditions for wave-3 claims.
LLM 出题（kill conditions），数据判卷（后续脚本实跑）。
"""
import json, sys, os
sys.path.insert(0, '/opt/data/cache/scratch')
from wb2_client import chat

OUT = '/opt/data/cache/scratch/redteam_llm_raw.json'

SYSTEM = """你是对冲基金风险委员会的红队负责人，专门猎杀量化研究员的虚假结论。你的唯一职责是攻击，不是安慰。
规则（违反即失败）：
1. 禁止任何平衡/外交辞令（"但是这条线也有价值"之类的话一律删除）。你要的是这条线死，不是它好。
2. 对每条主张，输出"我会怎么杀它"：至少3条具体的、数据可检验的 kill condition。每条 kill condition 必须满足：给定一份历史数据文件（日K/事件表/账本/影子记录），写一段代码就能判定"该主张是否被打死"。
3. 优先攻击这些软肋：样本外衰减、抱团日/同日复用（事件扎堆导致双重计数）、幸存者偏差、口径切换（前复权vs不复权、事件级vs日历时间vs账本级）、单票集中、成本/最低佣金、容量（信号成簇资金吃不到）、参数高原（邻域参数是否全活）、beta伪装成alpha（恐慌后大盘反弹）、regime依赖、多重检验（挑了几次格）。
4. 每条 kill condition 给出：判定阈值（什么数字算"打死"）、需要什么数据、预计它会不会真的打死（诚实概率）。
5. 不许编造数据文件里没有的字段。数据底座：A股主板3335只日K 2019-2026（前复权+不复权两套）、事件研究JSON、组合账本JSON（逐笔trades+日度净值）、影子账本jsonl、注册表yaml。
6. 输出严格 JSON 数组，每条一个对象，不要多余文字：
[{"claim_id":"...","attack_angle":"...","kill_condition":"可执行的检验描述","threshold":"判死阈值","data_needed":"数据文件/字段","kill_probability":"高/中/低","severity":"高/中/低"}]"""

BATCHES = {
"portfolio": """攻击对象=组合层 v1 统一账本（engine/portfolio.py，2019-01→2026-10，8年，三账户：进攻60%/红利25%/转债15%，5槽共享优先级 DEEP_V2>LD>REV_KNN>REV_RES08>REV）：
A1 三档资金合并净值全相同：5万/10万/20万档都是1.339x、年化+3.85%、回撤-43.7%、占用85.8%、1496笔、胜率44.2%。档位间唯一差异=最低佣金5元/笔drag（5万档8年累计12903元≈3.2pp/年→实际年化≈+0.6%）。
A2 单线各自独跑：DIV 3.474x/+17.5%、CB 2.012x/+9.5%、DEEP_V2 1.904x/+8.7%（占用仅4%）、REV_KNN 2.848x/+14.5%（OOS2023+逐年全正：2023+7.3/2024+38.8/2025+41.5/2026+35.6%）、LD 0.636x/-5.7%、REV_RES08 0.635x/-5.7%、REV 0.222x/-17.7%。
A3 结构性发现：LD事件级68.3%/+4.95%的线在5槽账本下-5.7%/年（容量绞肉机）；REV以最低优先级仍灌满5槽挤占合并账户；REV_KNN solo惊艳但合并里被REV/LD饿死（2025合并贡献-10016元）→结论"候选层要活必须替代REV而非并存"。
A4 线间相关性全低（跨家族<0.4，max 0.483=REV_KNN|RES08同源）→"分散真实有效"。
A5 账本自检：逐笔现金守恒残差-0.22元；事件级锚点LD 68.3%/+4.95%、CB 73.5%/+9.64%全对上。
A6 2025合并收益仅+1.0%（贡献CB+5969/DIV-272/LD-1412/REV-574/REV_KNN-10016元）。
已知欠账：deep簇日54 vs 另一口径65（ST过滤+宇宙差，未追平）；CB无滑点；名义仓=当前权益/槽数（动态）。""",

"gold": """攻击对象=金股线（券商月度金股名单）第三波结论：
B1 主线（月度第6交易日入场×年内首入+独家×T+20出×强态过滤）=活不动：2026超额+6.01pp，"溢价单调死亡"假说已证伪，2026-10空仓=solo_fresh=0正常空窗。
B2 变体"三连阴_金股覆盖_v1"提案进ICU：影子n=55，T+5 37.5%/-4.45%；10月6单5单砸在000338潍柴动力一票（阴跌每日复触发，口径无单票冷却）；kill condition量化：n≥80时r5胜率<42%或r20结算均值<-2%→DEAD。
B3 深挖反推（15629事件2020-2026）：注册口径（三连阴+金股在册）捕捉错变量——三因子全在口径外：mkt20>+2%档64~68%/+2.6~4.0% vs <-3%档48.4%/+0.35%（最强单变量d=+0.24）、dhigh60深于-0.5档70.8%/+4.61%位置单调、无单票冷却。修复假设登记：mkt20转正闸/dhigh60≤-20%位置闸/单票5日冷却（须走submit四件套）。
B4 KNN邻居审计：出票日最相似历史股票日T+5 +0.68%/75.5%、T+20 +1.56%/84.9% vs 变体实走-4.41%/36.7%——跑输邻居约5pp；60%出票日落恐慌期（历史最优档），亏损归因"2026衰减+单票集中"。""",

"similarity": """攻击对象=协同过滤（KNN/GridCF相似样本引擎）产品化结论：
C1 组合增量矩阵51格（3条存活线×knn_vote/RES-08四因子过滤，OOS2023+）：正向加成全挂日历时间审（无一t_NW≥3）→定案"协同过滤=排序/排除层，不是买点过滤器"。
C2 唯一干净结果=knn低分位"别碰"排除层：反转族bottom20%（dec≤1）T+5增量-1.07pp、日历t_NW=-3.15显著为负（n=107501）；预增池也有显著为负子集。即"低分位的票别碰"被当作可执行排除层证据。
C3 RES-08最佳ivol20_low×反转族+1.12pp/t_NW=2.45未过Harvey 3→只作影子观察不注册。
C4 每日工具similarity_daily.py落地（504触发票28s，只读三份日度产物，GridCF-D口径PIT学习514万股票日，口径自校验max|diff|<1e-5）；cron化提案19:40 BJT（28s零网络）。
C5 背景：引擎事件级T+5 lift 0.74~1.85pp但日历时间t_NW≤2.2过不了Harvey门→#276判"不注册为交易线"；top档日超额前5%天数贡献101%（lift集中于极少数日子）；83%顶档是注册线之外新领土但被覆盖者+1.91%远高于未覆盖者+0.68%。""",

"wave278": """攻击对象=昨夜红队（#278，纯本地数据无LLM环节）确认的7条威胁处置提案，攻击"这些处置本身是否正确/够不够狠/有没有漏"：
D1 T1跌停次日接T+1腿进ICU：影子2026-09-11~10-15 r1 n=199 -0.06%/49%、r5 n=180 -1.04%/44%、r10 -1.87%/43%；注册口径+0.26%仍活。提案=T+1腿进ICU、T+5腿禁用维持。
D2 T2预增低位池2026转负（组合模拟2026 n=33 -0.81%/52%，两年级衰减）+低价层口径bug仍在生产（pead_pool.py排序键读前复权价，6.8%票误标）→提案降置信+PFX-01修复二选一。
D3 T3摇篮线2024单年依赖71%（402/565事件，+17.67%/88%），2025 -0.36%/43%，2026 +2.62%但win仅18%(n=11)→提案降"年集中假设"推送降权。
D4 T4深档v2 2026十四批53%/+2.69%仍正，但7/20-8/3五日窗5批+20.64%贡献全年275%，8/19后近两月零批次，9/24起单票深档影子r5 0/9胜→提案维持存活降置信。
D5 T5转债低价池装入评级CC信用困境债（宏图96.12）→提案加评级闸剔CCC及以下。
D6 T6股息锚2026实盘检验-1.7%/48%胜（无基准对照记体温）+红利税期望拖累0.15~0.36pp vs OOS边际+1.1pp→提案TAX-01维持优先级。
D7 T7金股变体影子r5 38%/-4.5%(n=48)→降级观察（已被B2扩展为进ICU）。
另：黄旗1条=T1-MEGA唯一前向批-8.43%/20%胜落在历史44批的2%分位，按"单批不立规矩"不触发变更。""",
}

def run_batch(name, claims_text, model='deepseek-v4-pro'):
    user = f"以下是要猎杀的主张清单。逐条给出你的 kill condition JSON 数组（每条主张至少3条，合并输出一个数组，claim_id 用我给的编号）：\n\n{claims_text}"
    res = chat([
        {'role': 'system', 'content': SYSTEM},
        {'role': 'user', 'content': user},
    ], model=model, max_tokens=8000, temperature=0.7, timeout=300)
    return res

if __name__ == '__main__':
    results = {}
    if os.path.exists(OUT):
        results = json.load(open(OUT))
    for name, text in BATCHES.items():
        if name in results and results[name].get('ok'):
            print(f'== {name}: cached, skip')
            continue
        print(f'== {name}: calling LLM...', flush=True)
        res = run_batch(name, text)
        results[name] = res
        json.dump(results, open(OUT, 'w'), ensure_ascii=False, indent=1)
        if res.get('ok'):
            print(f'   ok {res["elapsed"]}s, {len(res["content"])} chars')
        else:
            print(f'   FAIL {res.get("error", "")[:300]}')
    print('DONE')
