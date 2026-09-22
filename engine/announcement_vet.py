"""公告排雷层（2026-09-22 移植自 yunfeng_skill 的审查管线——该 skill 策略层已对照证伪墙全灭，
唯一真资产=东财公告 API + 正文级异动分级，移植为焚诀推送链的否决/降权层）。

用法：vet_batch(['600869', ...]) -> {code: {status, tier, hard/review/info_flags, matched}}
判定规则（原样移植并实测）：
  hard 排除：题材/事件正文级否认（不涉及/未开展…）、立案/处罚、退市风险、债务违约/破产重整、
             30交易日/200% 极端异动（正文阈值，不看标题）
  review 降权：澄清/传闻回应、减持计划、业绩预亏/减值、重大诉讼、冻结、终止项目、控制权变更、
             解禁/新股上市、10日/100% 异动（仅此一项=轻降权仍有条件 eligible）
  info 不罚：2-3日/20% 普通异动、「未发现重大媒体报道…亦未涉及热点概念」模板话术、快速下跌风险提示
  数据源不可达 = unverified（绝不当作「无利空」）。
东财端点（2026-09-22 实测 200）：np-anotice-stock.eastmoney.com/api/security/ann（列表）
  + np-cnotice-stock.eastmoney.com/api/content/ann（正文，需 Referer）。
"""
import datetime
import json
import math
import re

import requests

LIST_URL = "https://np-anotice-stock.eastmoney.com/api/security/ann"
CONTENT_URL = "https://np-cnotice-stock.eastmoney.com/api/content/ann"

HARD_TITLE = (
    ("regulatory_investigation", r"立案告知|立案调查|证监会立案|行政处罚|纪律处分"),
    ("delisting_risk", r"退市风险警示|终止上市|重大违法.*退市|可能被终止上市"),
    ("solvency_risk", r"债务逾期|重大债务违约|被申请破产|被申请重整|预重整|破产清算"),
)
REVIEW_TITLE = (
    ("clarification", r"澄清|市场传闻|媒体报道.*说明"),
    ("exchange_inquiry", r"问询函|关注函|监管工作函|监管函|工作函的回复|问询.*回复"),  # 2026-09-22 移植补丁：原版漏交易所函件（远东 9/12 监管工作函实测漏网）
    ("share_reduction", r"减持股份计划|股份减持计划|拟减持"),
    ("earnings_risk", r"业绩预亏|业绩下降|业绩下滑|预计亏损|计提.{0,12}减值"),
    ("legal_dispute", r"重大诉讼|重大仲裁|诉讼及仲裁"),
    ("asset_freeze", r"司法冻结|轮候冻结"),
    ("project_termination", r"终止.{0,24}(?:项目|合作|协议|收购|重组)"),
    ("control_change", r"控制权.{0,12}(?:拟发生变更|发生变更)|控股股东.{0,12}(?:拟变更|变更为)"),
    ("share_supply_event", r"新增股份上市|发行.{0,8}股票上市公告书|发行结果暨股本变动|限售股上市流通|解除限售|解禁"),
)
INFO_TITLE = (("trading_volatility_notice", r"股票交易(?:严重)?异常波动|股票交易风险提示"),)
BODY_TRIGGER = re.compile(r"澄清|风险提示|异常波动|市场传闻|媒体报道|问询|关注函|说明公告|业绩预告|业绩快报")
DENIAL = (
    r"(?:公司|主营业务|产品|业务)?[^。；\n]{0,45}(?:不涉及|未涉及|未开展|未从事|不生产|未生产|不具备)[^。；\n]{0,70}(?:概念|研发|业务|产品|生产|销售|技术|事项)",
    r"(?:无|没有|不存在)[^。；\n]{0,40}(?:资产注入|重大资产重组)[^。；\n]{0,40}(?:计划|安排)",
)
GENERIC_TEMPLATE = re.compile(
    r"(?:未发现|没有发现|不存在)[^。；\n]{0,80}(?:媒体报道|市场传闻)[^。；\n]{0,120}"
    r"(?:亦未涉及|不涉及|未涉及)[^。；\n]{0,30}(?:市场热点概念|热点概念)|"
    r"(?:亦未涉及|不涉及|未涉及)[^。；\n]{0,30}(?:市场热点概念|热点概念)(?:事项)?")
NEG_PERF = re.compile(r"(?:净利润|营业收入|经营业绩)[^。；\n]{0,80}(?:同比下降|同比减少|预计下降|预计减少|预计亏损|发生亏损)")
RISK_LANG = re.compile(r"存在快速(?:下跌|回落)风险|击鼓传花|泡沫化特征|严重偏离基本面|非理性炒作风险")
VOL_THRESHOLD = re.compile(r"(?:连续)?(?P<days>\d+)个交易日(?:内)?[^。；]{0,240}?累计(?:达到|超过|达|高达)(?P<pct>\d+(?:\.\d+)?)%")


def _num(v, d=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def _strip_html(t):
    return re.sub(r"<[^>]+>", " ", t or "")


def classify(title, body=""):
    combined = f"{title} {body}"
    hard, review, info, evidence = [], [], [], []
    for label, pat in HARD_TITLE:
        if re.search(pat, title):
            hard.append(label)
    for label, pat in REVIEW_TITLE:
        if re.search(pat, title):
            review.append(label)
    for label, pat in INFO_TITLE:
        if re.search(pat, title):
            info.append(label)
    generic = GENERIC_TEMPLATE.search(combined)
    denial_text = GENERIC_TEMPLATE.sub(" ", combined)
    for pat in DENIAL:
        m = re.search(pat, denial_text)
        if m:
            hard.append("concept_or_event_denial")
            evidence.append(m.group(0)[:160])
            break
    if generic:
        info.append("generic_hot_concept_template_no_penalty")
    compact = re.sub(r"\s+", "", body)
    for m in VOL_THRESHOLD.finditer(compact):
        days, pct = int(m.group("days")), _num(m.group("pct"))
        if days >= 30 and pct >= 200:
            hard.append("thirty_day_200pct_extreme_risk")
            evidence.append(m.group(0)[:200])
        elif days >= 10 and pct >= 100:
            review.append("ten_day_100pct_elevated_risk")
            evidence.append(m.group(0)[:200])
        elif days <= 3 and pct >= 20:
            info.append("ordinary_2_3day_20pct_no_penalty")
    if RISK_LANG.search(body) and re.search(r"异常波动|风险提示", title):
        info.append("trading_risk_language_info")
    if NEG_PERF.search(combined):
        review.append("negative_performance")
    return sorted(set(hard)), sorted(set(review)), sorted(set(info)), evidence[:5]


def vet_batch(codes, lookback_days=12, fetch_bodies=True):
    """批量公告排雷。返回 {code: {...}}；数据源失败 → status=unverified。"""
    codes = [str(c).zfill(6) for c in codes]
    end = datetime.date.today()
    start = (end - datetime.timedelta(days=lookback_days)).isoformat()
    # 晚间公告可能挂次日日期——窗口右端 +1 天
    end_s = (end + datetime.timedelta(days=1)).isoformat()
    out = {c: {"status": "unverified", "tier": "none", "hard_flags": [], "review_flags": [],
               "info_flags": [], "matched": []} for c in codes}
    sess = requests.Session()
    sess.headers.update({"User-Agent": "Mozilla/5.0"})
    try:
        for i in range(0, len(codes), 40):
            batch = codes[i:i + 40]
            r = sess.get(LIST_URL, params={
                "sr": "-1", "page_size": "100", "page_index": "1", "ann_type": "A",
                "client_source": "web", "f_node": "0", "s_node": "0",
                "stock_list": ",".join(batch), "begin_time": start, "end_time": end_s},
                timeout=18)
            r.raise_for_status()
            data = r.json().get("data") or {}
            for row in data.get("list") or []:
                title = str(row.get("title") or "")
                art = str(row.get("art_code") or "")
                nd = str(row.get("notice_date") or "")[:10]
                row_codes = {str(cr.get("stock_code", "")).zfill(6) for cr in row.get("codes") or []}
                for code in row_codes & set(batch):
                    out[code].setdefault("_raw", []).append({"art": art, "title": title, "date": nd})
            for c in batch:
                if out[c]["status"] == "unverified":
                    out[c]["status"] = "clean"  # 列表可达且无记录=窗口内无公告
    except Exception as e:
        for c in codes:
            out[c]["error"] = str(e)[:200]
        return out
    # 正文只拉触发标题的
    for code in codes:
        raw = out[code].pop("_raw", [])
        hard_all, review_all, info_all, matched = [], [], [], []
        for rec in raw:
            body = ""
            if fetch_bodies and BODY_TRIGGER.search(rec["title"]):
                try:
                    r2 = sess.get(CONTENT_URL, params={"art_code": rec["art"], "client_source": "web",
                                                       "page_index": "1"},
                                  headers={"Referer": "https://data.eastmoney.com/"}, timeout=18)
                    body = _strip_html((r2.json().get("data") or {}).get("notice_content"))
                except Exception:
                    out[code]["status"] = "partial"
            h, rv, inf, ev = classify(rec["title"], body)
            if h or rv or inf:
                matched.append({"date": rec["date"], "title": rec["title"], "hard": h, "review": rv,
                                "info": inf, "evidence": ev,
                                "url": f"https://data.eastmoney.com/notices/detail/{code}/{rec['art']}.html"})
            hard_all += h
            review_all += rv
            info_all += inf
        out[code]["hard_flags"] = sorted(set(hard_all))
        out[code]["review_flags"] = sorted(set(review_all))
        out[code]["info_flags"] = sorted(set(info_all))
        out[code]["matched"] = matched[:5]
        if "thirty_day_200pct_extreme_risk" in hard_all:
            tier = "extreme_30d200"
        elif "ten_day_100pct_elevated_risk" in review_all:
            tier = "elevated_10d100"
        elif "ordinary_2_3day_20pct_no_penalty" in info_all:
            tier = "ordinary_2_3d20"
        elif info_all:
            tier = "notice_no_penalty"
        else:
            tier = "none"
        out[code]["tier"] = tier
        if out[code]["status"] == "unverified":
            out[code]["status"] = "clean"
        if hard_all:
            out[code]["status"] = "hard_excluded"
        elif review_all:
            only_10d100 = set(review_all) == {"ten_day_100pct_elevated_risk"}
            out[code]["status"] = "review_light" if only_10d100 else "review"
    return out


if __name__ == "__main__":
    import sys
    res = vet_batch(sys.argv[1:] or ["600869", "000002"])
    print(json.dumps(res, ensure_ascii=False, indent=1))
