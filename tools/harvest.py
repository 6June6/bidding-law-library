#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按主题关键词批量收割国家法律法规数据库的条目（只出候选，不写盘）。

用法：
  python3 tools/harvest.py            # 只打印候选与新条目
  python3 tools/harvest.py --commit   # 把新条目并入 data/items.json（待 flk_fetch 取全文）
"""

import json
import os
import re
import sys
import time
import urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, "data")
API = "https://flk.npc.gov.cn/law-search/search/list"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
SXX = {1: "已废止", 2: "已被修改", 3: "现行有效", -1: "尚未生效"}

LEVEL_OF = {"法律": "法律", "行政法规": "行政法规", "地方法规": "地方性法规",
            "司法解释": "司法解释", "部门规章": "部门规章"}
LEVEL_CODE = {"法律": "A", "行政法规": "B", "部门规章": "C",
              "地方性法规": "D", "规范性文件": "E", "司法解释": "F"}
LEVEL_DIR = {"法律": "01-法律", "行政法规": "02-行政法规", "部门规章": "03-部门规章",
             "地方性法规": "04-地方性法规", "规范性文件": "05-规范性文件",
             "司法解释": "06-司法解释"}

# 核心主题词：标题命中即收（地方性法规也只按这一档判断）
CORE = ["招标", "投标", "采购", "公共资源交易", "建筑市场", "建设工程", "工程建设",
        "工程造价", "工程监理", "勘察设计", "发包", "承包", "评标", "中标",
        "施工", "工程质量", "招标代理", "特许经营", "政府投资", "工程款",
        "工程结算", "价款结算", "竣工验收", "农民工工资", "政府和社会资本合作", "工程咨询"]
# 跨领域主题词：只收国家级（法律/行政法规），地方版一律不收
GENERIC = ["优化营商环境", "安全生产", "审计", "预算", "中小企业", "反不正当竞争",
           "拍卖", "价格", "行政处罚", "行政复议", "合同", "公平竞争", "基础设施"]
# 明显不属于本领域
BAD = ["户外广告", "店招标牌", "广告设施", "标语", "牌匾", "户外招牌", "车船税",
       "残疾人", "计划生育", "殡葬", "物业", "养犬", "烟花爆竹",
       "农村土地承包", "集体合同", "劳动合同", "商品房", "融资租赁", "技术合同",
       "储蓄", "保险", "船舶", "海域", "司法拍卖", "婚姻", "收养", "继承",
       "农村集体经济", "关键信息基础设施", "商业特许经营", "煤矿安全", "燃气",
       "供水", "供热", "绿化", "市容", "垃圾", "公厕", "道路照明",
       "集体经济", "合作经济", "支付结算", "移民"]

# 逐条点名收录（标题不含主题词但属于工程建设全流程的上位法）
EXTRA_TITLES = [
    "中华人民共和国土地管理法", "中华人民共和国城乡规划法", "中华人民共和国环境影响评价法",
    "中华人民共和国标准化法", "中华人民共和国产品质量法", "中华人民共和国特种设备安全法",
    "中华人民共和国行政许可法", "中华人民共和国行政诉讼法", "中华人民共和国环境保护法",
    "中华人民共和国节约能源法", "中华人民共和国公路法", "中华人民共和国企业国有资产法",
    "保障农民工工资支付条例", "建设项目环境保护管理条例", "企业投资项目核准和备案管理条例",
    "中华人民共和国土地管理法实施条例", "生产安全事故报告和调查处理条例",
    "建设工程安全生产管理条例", "中华人民共和国招标投标法实施条例",
]

KEYWORDS = [
    "招标", "投标", "招标投标", "采购", "政府采购", "公共资源交易",
    "建设工程", "建筑市场", "工程建设", "工程建设项目", "发包", "承包",
    "评标", "中标", "工程造价", "监理", "施工", "勘察设计", "特许经营",
    "政府投资", "工程质量", "安全生产", "招标代理", "代理机构",
    "合同", "结算", "审计", "预算", "中小企业", "营商环境", "公平竞争",
    "拍卖", "反不正当竞争", "基础设施", "政府和社会资本合作",
    "土地使用权", "矿业权", "产权交易", "药品采购", "集中采购", "履约",
    "农民工工资", "工程款", "竣工验收", "代建", "施工许可", "工程质量检测",
    "企业投资项目", "建设项目环境保护", "土地管理法", "城乡规划", "环境影响评价",
    "招标投标法实施条例", "政府采购法实施条例", "工程建设项目施工",
]


CATEGORY_RULES = [
    ("交易程序", ["招标投标法", "招标投标条例", "招标投标管理办法", "施工招标", "货物招标",
                "勘察设计招标", "电子招标", "评标", "投标", "招标公告", "招标代理"]),
    ("政府采购", ["政府采购", "采购"]),
    ("监督与救济", ["投诉", "质疑", "行政复议", "行政处罚", "违法行为记录", "监督管理",
                 "公平竞争审查", "监察", "审计", "信用"]),
    ("合同与履约", ["合同", "发包", "承包", "计价", "造价", "结算", "担保", "农民工工资",
                 "款项"]),
    ("主体与资质", ["建筑法", "代理机构", "资质", "中小企业", "安全生产许可", "特种设备"]),
    ("信息公开", ["公告", "公示", "信息发布", "信息公开", "平台", "营商环境"]),
    ("工程管理", ["建设工程质量", "建设工程安全生产", "勘察设计", "工程项目", "基础设施",
                "建筑市场", "施工", "监理", "抗震", "人防", "政府投资", "特许经营"]),
]


def guess_category(title):
    for cat, kws in CATEGORY_RULES:
        for kw in kws:
            if kw in title:
                return cat
    return "综合"


def clean(t):
    return re.sub(r"<[^>]+>", "", t or "").strip()


def query(content, search_type=1, page=1, size=100):
    payload = {"searchType": search_type, "searchContent": content, "searchRange": 1,
               "sxrq": [], "gbrq": [], "sxx": [], "gbrqYear": [],
               "flfgCodeId": [], "zdjgCodeId": [], "pageNum": page, "pageSize": size}
    req = urllib.request.Request(API, data=json.dumps(payload).encode(), headers={
        "Content-Type": "application/json", "User-Agent": UA,
        "Referer": "https://flk.npc.gov.cn/"})
    for i in range(3):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode())
        except Exception:
            if i == 2:
                raise
            time.sleep(2 + 2 * i)


def safe_query(content, page=1, size=100):
    try:
        return query(content, 1, page, size)
    except Exception as e:
        print("    ! %s 失败：%s" % (content, e), flush=True)
        time.sleep(3)
        try:
            return query(content, 1, page, size)
        except Exception:
            return {"total": 0, "rows": []}


def harvest():
    rows = {}
    for kw in EXTRA_TITLES:
        try:
            for r in safe_query(kw, 1, 20).get("rows") or []:
                if clean(r.get("title")) == kw:
                    rows.setdefault(kw, []).append(r)
        except Exception:
            pass
        time.sleep(0.3)
    for kw in KEYWORDS:
        d = safe_query(kw, 1, 100)
        total = d.get("total") or 0
        pages = (total + 99) // 100
        got = list(d.get("rows") or [])
        for p in range(2, min(pages, 6) + 1):
            time.sleep(0.4)
            got += safe_query(kw, p, 100).get("rows") or []
        for r in got:
            t = clean(r.get("title"))
            if not t:
                continue
            rows.setdefault(t, []).append(r)
        print("  %-12s 命中 %4d" % (kw, total), flush=True)
        time.sleep(0.5)
    return rows


def pick(rows):
    """同一标题多个版本：取现行有效，其次最新公布"""
    valid = [r for r in rows if r.get("sxx") == 3]
    pool = valid or rows
    return sorted(pool, key=lambda r: (r.get("gbrq") or ""), reverse=True)[0]


def relevant(title, level):
    if any(b in title for b in BAD):
        return False
    if any(k in title for k in CORE):
        return True
    if level in ("法律", "行政法规"):
        return any(k in title for k in GENERIC)
    if level == "司法解释":
        return any(k in title for k in ("建设工程", "施工合同", "招标", "投标", "工程价款"))
    return False


def main():
    commit = "--commit" in sys.argv
    print("收割关键词 %d 个……" % len(KEYWORDS), flush=True)
    raw = harvest()
    print("去重后标题 %d" % len(raw))

    items = json.load(open(os.path.join(DATA, "items.json"), encoding="utf-8"))
    have = {re.sub(r"\s", "", x["title"]) for x in items}
    used = {x["id"] for x in items}
    nxt = {}
    for x in items:
        nxt[x["level"]] = max(nxt.get(x["level"], 0), int(x["id"][1:]))

    new = []
    for t, rs in raw.items():
        r = pick(rs)
        flxz = r.get("flxz") or ""
        level = LEVEL_OF.get(flxz)
        if not level:
            continue
        if r.get("sxx") != 3:
            continue
        if t not in EXTRA_TITLES and not relevant(t, level):
            continue
        if re.sub(r"\s", "", t) in have:
            continue
        new.append(dict(level=level, title=t, doc_no="", issuer=r.get("zdjgName") or "",
                        pub=r.get("gbrq") or "", eff=r.get("sxrq") or r.get("gbrq") or "",
                        status=SXX.get(r.get("sxx"), ""), note="",
                        source="https://flk.npc.gov.cn/detail?bbbs=%s" % r["bbbs"],
                        source_name="国家法律法规数据库", category=guess_category(t), query=t))

    by = {}
    for x in new:
        by.setdefault(x["level"], []).append(x)
    order = list(LEVEL_DIR)
    for lv in order:
        if lv not in by:
            continue
        print("\n== %s 新增 %d" % (lv, len(by[lv])))
        for x in sorted(by[lv], key=lambda y: y["title"]):
            print("   %-56s %s  %s" % (x["title"][:56], x["pub"], x["issuer"][:16]))

    if not commit:
        print("\n合计新增 %d（加 --commit 并入）" % len(new))
        return

    for x in new:
        lv = x["level"]
        nxt[lv] = nxt.get(lv, 0) + 1
        x["id"] = "%s%02d" % (LEVEL_CODE[lv], nxt[lv])
        while x["id"] in used:
            nxt[lv] += 1
            x["id"] = "%s%02d" % (LEVEL_CODE[lv], nxt[lv])
        used.add(x["id"])
    items.extend(new)
    json.dump(items, open(os.path.join(DATA, "items.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("已并入 %d 条，条目总数 %d" % (len(new), len(items)))


if __name__ == "__main__":
    main()
