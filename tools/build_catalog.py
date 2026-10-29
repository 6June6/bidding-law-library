#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""元数据构建：从国家法律法规数据库（flk.npc.gov.cn）按标题精确取数，
合并人工核定的部门规章/规范性文件清单，产出 data/items.json。

用法：python3 tools/build_catalog.py [--refresh]
  --refresh  忽略本地缓存，重新联网取数
"""

import json, os, re, sys, time, urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, "data")
CACHE = os.path.join(DATA, "cache_flk.json")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
API = "https://flk.npc.gov.cn/law-search/search/list"

LEVEL_DIR = {
    "法律": "01-法律",
    "行政法规": "02-行政法规",
    "部门规章": "03-部门规章",
    "地方性法规": "04-地方性法规",
    "规范性文件": "05-规范性文件",
    "司法解释": "06-司法解释",
}
LEVEL_CODE = {"法律": "A", "行政法规": "B", "部门规章": "C",
              "地方性法规": "D", "规范性文件": "E", "司法解释": "F"}
SXX = {1: "已废止", 2: "已被修改", 3: "现行有效", -1: "尚未生效"}


def clean(t):
    return re.sub(r"<[^>]+>", "", t or "").strip()


def query(content, search_type=1, size=50):
    payload = {"searchType": search_type, "searchContent": content, "searchRange": 1,
               "sxrq": [], "gbrq": [], "sxx": [], "gbrqYear": [],
               "flfgCodeId": [], "zdjgCodeId": [], "pageNum": 1, "pageSize": size}
    req = urllib.request.Request(API, data=json.dumps(payload).encode(), headers={
        "Content-Type": "application/json", "User-Agent": UA,
        "Referer": "https://flk.npc.gov.cn/"})
    with urllib.request.urlopen(req, timeout=45) as r:
        d = json.loads(r.read().decode())
    return d.get("rows") or []


class Flk:
    def __init__(self, refresh=False):
        self.refresh = refresh
        self.cache = {}
        if os.path.exists(CACHE) and not refresh:
            self.cache = json.load(open(CACHE, encoding="utf-8"))

    def get(self, content, search_type=1):
        key = "%d|%s" % (search_type, content)
        if key in self.cache:
            return self.cache[key]
        try:
            rows = query(content, search_type)
        except Exception as e:
            print("  ! 取数失败 %s: %s" % (content, e), file=sys.stderr)
            rows = []
        self.cache[key] = rows
        time.sleep(0.35)
        return rows

    def save(self):
        json.dump(self.cache, open(CACHE, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)


def flk_link(bbbs):
    return "https://flk.npc.gov.cn/detail?bbbs=%s" % bbbs


# 沿革与个别日期人工校订（flk 的公布日期是"当前文本公布日"，首次公布/历次修订在此补充）
OVERRIDE = {
    "中华人民共和国招标投标法": dict(note="1999年8月30日第九届全国人大常委会第十一次会议通过，2000年1月1日施行；"
                                       "2017年12月27日第十二届全国人大常委会第三十一次会议修正，2017年12月28日施行"),
    "中华人民共和国政府采购法": dict(note="2002年6月29日第九届全国人大常委会第二十八次会议通过，2003年1月1日施行；"
                                       "2014年8月31日第十二届全国人大常委会第十次会议修正"),
    "中华人民共和国建筑法": dict(note="1997年11月1日第八届全国人大常委会第二十八次会议通过，1998年3月1日施行；"
                                    "2011年4月22日、2019年4月23日两次修正"),
    "中华人民共和国行政处罚法": dict(note="1996年3月17日通过；2009年、2017年修正；2021年1月22日修订，2021年7月15日施行"),
    "中华人民共和国行政复议法": dict(note="1999年4月29日通过；2009年、2017年修正；2023年9月1日修订，2024年1月1日施行"),
    "中华人民共和国价格法": dict(note="1997年12月29日第八届全国人大常委会第二十九次会议通过，1998年5月1日施行"),
    "中华人民共和国反不正当竞争法": dict(note="1993年9月2日通过；2017年11月4日修订；2019年4月23日修正；"
                                        "2025年6月27日修订，2025年10月15日施行"),
    "中华人民共和国拍卖法": dict(note="1996年7月5日通过；2004年8月28日、2015年4月24日两次修正"),
    "中华人民共和国民法典": dict(note="2020年5月28日第十三届全国人大第三次会议通过，2021年1月1日施行；"
                                  "同时废止合同法、物权法、担保法等九部法律"),
    "中华人民共和国招标投标法实施条例": dict(
        note="2011年12月20日国务院令第613号公布，2012年2月1日首次施行；2017年、2018年、2019年三次修订，"
             "本库收录2019年3月2日第三次修订文本"),
    "中华人民共和国政府采购法实施条例": dict(
        note="2014年12月31日国务院第75次常务会议通过，2015年1月30日国务院令第658号公布，2015年3月1日施行"),
    "建设工程质量管理条例": dict(
        note="2000年1月30日国务院令第279号公布施行；2017年10月7日、2019年4月23日两次修订"),
    "建设工程安全生产管理条例": dict(
        note="2003年11月12日国务院第28次常务会议通过，2003年11月24日国务院令第393号公布，2004年2月1日施行"),
    "建设工程勘察设计管理条例": dict(
        note="2000年9月25日国务院令第293号公布施行；2015年6月12日、2017年10月7日两次修订"),
    "优化营商环境条例": dict(note="2019年10月8日国务院第66次常务会议通过，2019年10月22日国务院令第722号公布，"
                             "2020年1月1日施行"),
}

CATEGORY_RULES = [
    ("交易程序", ["招标投标法", "招标投标条例", "招标投标管理办法", "施工招标", "货物招标",
                "勘察设计招标", "电子招标", "评标", "投标", "招标公告"]),
    ("政府采购", ["政府采购", "采购"]),
    ("监督与救济", ["投诉", "质疑", "行政复议", "行政处罚", "违法行为记录", "监督管理",
                 "公平竞争审查", "监察", "审计"]),
    ("合同与履约", ["合同", "发包", "承包", "计价", "担保"]),
    ("主体与资质", ["建筑法", "代理机构", "资质", "中小企业"]),
    ("信息公开", ["公告", "公示", "信息发布", "信息公开", "平台", "营商环境"]),
    ("工程管理", ["建设工程质量", "建设工程安全生产", "勘察设计", "工程项目", "基础设施"]),
]


def guess_category(title):
    for cat, kws in CATEGORY_RULES:
        for kw in kws:
            if kw in title:
                return cat
    return "综合"


def pick(rows, title):
    """精确命中优先；同名取现行有效/最新公布版本"""
    exact = [r for r in rows if clean(r["title"]) == title]
    pool = exact or [r for r in rows if title in clean(r["title"])]
    if not pool:
        return None
    valid = [r for r in pool if r.get("sxx") == 3]
    pool = valid or pool
    return sorted(pool, key=lambda r: (r.get("gbrq") or ""), reverse=True)[0]


LAW_TITLES = [
    "中华人民共和国招标投标法",
    "中华人民共和国政府采购法",
    "中华人民共和国建筑法",
    "中华人民共和国反不正当竞争法",
    "中华人民共和国价格法",
    "中华人民共和国行政处罚法",
    "中华人民共和国行政复议法",
    "中华人民共和国拍卖法",
    "中华人民共和国民法典",
]
REG_TITLES = [
    "中华人民共和国招标投标法实施条例",
    "中华人民共和国政府采购法实施条例",
    "建设工程质量管理条例",
    "建设工程安全生产管理条例",
    "建设工程勘察设计管理条例",
    "优化营商环境条例",
]
JSJX_TITLES = [
    "最高人民法院关于审理建设工程施工合同纠纷案件适用法律问题的解释（一）",
    "最高人民法院关于适用《中华人民共和国民法典》合同编通则若干问题的解释",
    "最高人民法院关于适用《中华人民共和国反不正当竞争法》若干问题的解释",
]
LOCAL_KEYWORDS = ["招标", "公共资源交易"]

BM_RULES = [
    dict(title="必须招标的工程项目规定", doc_no="国家发展和改革委员会令第16号",
         issuer="国家发展和改革委员会", pub="2018-03-27", eff="2018-06-01",
         note="经国务院批准，取代《工程建设项目招标范围和规模标准规定》（2000年）",
         query="必须招标的工程项目规定"),
    dict(title="工程建设项目施工招标投标办法", doc_no="国家发展计划委员会等七部委令第30号",
         issuer="国家计委、建设部、铁道部、交通部、信息产业部、水利部、民航总局",
         pub="2003-03-08", eff="2003-05-01",
         note="2013年4月18日经国家发展改革委等九部委令第23号修改",
         query="工程建设项目施工招标投标办法"),
    dict(title="工程建设项目货物招标投标办法", doc_no="国家发展计划委员会等七部委令第27号",
         issuer="国家计委、建设部、铁道部、交通部、信息产业部、水利部、民航总局",
         pub="2005-01-18", eff="2005-03-01",
         note="2013年4月18日经国家发展改革委等九部委令第23号修改",
         query="工程建设项目货物招标投标办法"),
    dict(title="工程建设项目勘察设计招标投标办法", doc_no="国家发展计划委员会等八部委令第2号",
         issuer="国家计委、建设部、铁道部、交通部、信息产业部、水利部、民航总局、广电总局",
         pub="2003-06-12", eff="2003-08-01",
         note="2013年4月18日经国家发展改革委等九部委令第23号修改",
         query="工程建设项目勘察设计招标投标办法"),
    dict(title="评标委员会和评标方法暂行规定", doc_no="国家发展计划委员会等七部委令第12号",
         issuer="国家计委、国家经贸委、建设部、铁道部、交通部、信息产业部、水利部",
         pub="2001-07-05", eff="2001-07-05",
         note="2013年4月18日经国家发展改革委等九部委令第23号修改",
         query="评标委员会和评标方法暂行规定"),
    dict(title="工程建设项目招标投标活动投诉处理办法", doc_no="国家发展和改革委员会等七部委令第11号",
         issuer="国家发改委、建设部、铁道部、交通部、信息产业部、水利部、民航总局",
         pub="2004-06-21", eff="2004-08-01",
         note="2013年4月18日经国家发展改革委等九部委令第23号修改",
         query="工程建设项目招标投标活动投诉处理办法"),
    dict(title="电子招标投标办法", doc_no="国家发展和改革委员会等八部委令第20号",
         issuer="国家发改委、工业和信息化部、监察部、住房城乡建设部、交通运输部、铁道部、水利部、商务部",
         pub="2013-02-04", eff="2013-05-01",
         note="另配套《电子招标投标系统技术规范》",
         query="电子招标投标办法"),
    dict(title="招标公告和公示信息发布管理办法", doc_no="国家发展和改革委员会令第10号",
         issuer="国家发展和改革委员会", pub="2017-11-23", eff="2018-01-01",
         note="取代《招标公告发布暂行办法》（2000年）",
         query="招标公告和公示信息发布管理办法"),
    dict(title="房屋建筑和市政基础设施工程施工招标投标管理办法", doc_no="建设部令第89号",
         issuer="建设部（现住房和城乡建设部）", pub="2001-06-01", eff="2001-06-01",
         note="2018年9月28日、2019年3月13日两次修正",
         query="房屋建筑和市政基础设施工程施工招标投标管理办法"),
    dict(title="建筑工程施工发包与承包计价管理办法", doc_no="住房和城乡建设部令第16号",
         issuer="住房和城乡建设部", pub="2013-12-11", eff="2014-02-01",
         note="取代建设部令第107号同名办法",
         query="建筑工程施工发包与承包计价管理办法"),
    dict(title="政府采购货物和服务招标投标管理办法", doc_no="财政部令第87号",
         issuer="财政部", pub="2017-08-31", eff="2017-10-01",
         note="取代财政部令第18号", query="政府采购货物和服务招标投标管理办法"),
    dict(title="政府采购非招标采购方式管理办法", doc_no="财政部令第74号",
         issuer="财政部", pub="2013-12-19", eff="2014-02-01", note="",
         query="政府采购非招标采购方式管理办法"),
    dict(title="政府采购质疑和投诉办法", doc_no="财政部令第94号",
         issuer="财政部", pub="2017-12-11", eff="2018-03-01",
         note="取代《政府采购供应商投诉处理办法》（财政部令第20号）",
         query="政府采购质疑和投诉办法"),
    dict(title="政府采购信息发布管理办法", doc_no="财政部令第101号",
         issuer="财政部", pub="2019-11-27", eff="2020-03-01", note="",
         query="政府采购信息发布管理办法"),
]

GFXWJ = [
    dict(title="必须招标的基础设施和公用事业项目范围规定", doc_no="发改法规规〔2018〕843号",
         issuer="国家发展和改革委员会", pub="2018-06-06", eff="2018-06-06",
         note="与发改委令第16号配套执行",
         query="必须招标的基础设施和公用事业项目范围规定"),
    dict(title="关于严格执行招标投标法规制度进一步规范招标投标主体行为的若干意见",
         doc_no="发改法规规〔2022〕1117号", issuer="国家发展改革委等13部门",
         pub="2022-07-25", eff="2022-07-25",
         note="招投标领域现行最重要的综合性规范性文件之一",
         query="关于严格执行招标投标法规制度进一步规范招标投标主体行为的若干意见"),
    dict(title="招标投标领域公平竞争审查规则", doc_no="国家发展改革委等部门令第1号",
         issuer="国家发展改革委等八部门", pub="2024-04-21", eff="2024-05-01",
         note="招投标领域公平竞争审查的专门规则，属规章层级、按规范性文件归类",
         query="招标投标领域公平竞争审查规则"),
    dict(title="政府采购促进中小企业发展管理办法", doc_no="财库〔2020〕46号",
         issuer="财政部、工业和信息化部", pub="2020-12-18", eff="2021-01-01",
         note="含价格评审优惠、预留份额等支持措施",
         query="政府采购促进中小企业发展管理办法"),
    dict(title="政府采购需求管理办法", doc_no="财库〔2021〕22号",
         issuer="财政部", pub="2021-04-30", eff="2021-07-01", note="",
         query="政府采购需求管理办法"),
    dict(title="关于开展政府采购意向公开工作的通知", doc_no="财库〔2020〕10号",
         issuer="财政部", pub="2020-03-02", eff="2020-07-01", note="",
         query="关于开展政府采购意向公开工作的通知"),
    dict(title="招标投标违法行为记录公告暂行办法", doc_no="发改法规〔2008〕1531号",
         issuer="国家发展改革委等十部门", pub="2008-11-27", eff="2009-01-01",
         note="失信记录公告制度的源头文件",
         query="招标投标违法行为记录公告暂行办法"),
    dict(title="国务院办公厅转发国家发展改革委关于深化公共资源交易平台整合共享指导意见的通知",
         doc_no="国办函〔2019〕41号", issuer="国务院办公厅", pub="2019-05-30", eff="2019-05-30",
         note="公共资源交易平台整合共享的纲领性文件",
         query="国务院办公厅转发国家发展改革委关于深化公共资源交易平台整合共享指导意见的通知"),
]


def build(refresh=False):
    f = Flk(refresh)
    items = []

    def add_flk(level, title, note=""):
        rows = f.get(title, 1)
        r = pick(rows, title)
        if not r:
            print("  ! 未命中：%s（%s）" % (title, level), file=sys.stderr)
            return
        it = dict(
            level=level, title=clean(r["title"]), doc_no="", issuer=r.get("zdjgName") or "",
            pub=r.get("gbrq") or "", eff=r.get("sxrq") or r.get("gbrq") or "",
            status=SXX.get(r.get("sxx"), ""), note=note,
            source=flk_link(r["bbbs"]), source_name="国家法律法规数据库",
            category=guess_category(clean(r["title"])), query=title)
        ov = OVERRIDE.get(it["title"]) or {}
        for k, v in ov.items():
            it[k] = v
        items.append(it)

    for t in LAW_TITLES:
        add_flk("法律", t)
    for t in REG_TITLES:
        add_flk("行政法规", t)
    for t in JSJX_TITLES:
        add_flk("司法解释", t)

    for d in BM_RULES:
        d = dict(d)
        q = d.pop("query")
        d.update(level="部门规章", status="现行有效", source="", source_name="",
                 category=guess_category(d["title"]), query=q)
        items.append(d)

    for d in GFXWJ:
        d = dict(d)
        q = d.pop("query")
        d.update(level="规范性文件", status="现行有效", source="", source_name="",
                 category=guess_category(d["title"]), query=q)
        items.append(d)

    # 补充条目（data/extra.json，逐条人工核过官方出处）
    ep = os.path.join(DATA, "extra.json")
    if os.path.exists(ep):
        have = {x["title"] for x in items}
        for d in json.load(open(ep, encoding="utf-8")):
            if d["title"] in have:
                continue
            d = dict(d)
            d.setdefault("doc_no", "")
            d.setdefault("status", "现行有效")
            d.setdefault("note", "")
            d.setdefault("source", d.get("url", ""))
            d.setdefault("source_name", "中国政府网" if "gov.cn" in (d.get("url") or "") else "")
            d.setdefault("category", guess_category(d["title"]))
            d.setdefault("query", d["title"])
            items.append(d)

    # 地方性法规：现行有效，排除“广告/店招”类误命中
    BAD = ("户外广告", "店招标牌", "广告设施")
    loc = []
    for kw in LOCAL_KEYWORDS:
        for r in f.get(kw, 2):
            t = clean(r["title"])
            if r.get("flxz") != "地方法规" or r.get("sxx") != 3:
                continue
            if "招标" not in t and "公共资源交易" not in t:
                continue
            if any(b in t for b in BAD):
                continue
            loc.append(r)
    seen = set()
    for r in sorted(loc, key=lambda x: clean(x["title"])):
        t = clean(r["title"])
        if t in seen:
            continue
        seen.add(t)
        items.append(dict(
            level="地方性法规", title=t, doc_no="", issuer=r.get("zdjgName") or "",
            pub=r.get("gbrq") or "", eff=r.get("sxrq") or "",
            status=SXX.get(r.get("sxx"), ""), note="",
            source=flk_link(r["bbbs"]), source_name="国家法律法规数据库",
            category=guess_category(t), query=t))

    order = {k: i for i, k in enumerate(LEVEL_DIR)}
    items.sort(key=lambda x: (order[x["level"]], x["category"], x["title"]))

    # 编号保持稳定：已有条目沿用原编号，新条目按层级递增编号（避免重排导致编号与文件头不一致）
    prev = {}
    oldp = os.path.join(DATA, "items.json")
    if os.path.exists(oldp):
        for o in json.load(open(oldp, encoding="utf-8")):
            if o.get("id"):
                prev[o["title"]] = o["id"]
    used, nxt = set(), {}
    for it in items:
        pid = prev.get(it["title"])
        if pid:
            it["id"] = pid
            used.add(pid)
            nxt[it["level"]] = max(nxt.get(it["level"], 0), int(pid[1:]))
    for it in items:
        if "id" in it:
            continue
        nxt[it["level"]] = nxt.get(it["level"], 0) + 1
        it["id"] = "%s%02d" % (LEVEL_CODE[it["level"]], nxt[it["level"]])
        while it["id"] in used:
            nxt[it["level"]] += 1
            it["id"] = "%s%02d" % (LEVEL_CODE[it["level"]], nxt[it["level"]])
        used.add(it["id"])

    # 保留既有抓取成果：以磁盘文件为准（按「名称」匹配，避免编号变化导致错配）
    import glob
    disk = {}
    for fp in glob.glob(os.path.join(BASE, "0*", "*.md")):
        txt = open(fp, encoding="utf-8").read()
        m = re.search(r"^名称: (.+)$", txt, re.M)
        if not m:
            continue
        u = re.search(r"^原文地址: (\S+)$", txt, re.M)
        body = re.sub(r"(?s)^---.*?---", "", txt)
        disk[m.group(1).strip()] = dict(
            file=os.path.relpath(fp, BASE),
            src_url=(u.group(1) if u else ""), chars=len(body))
    for it in items:
        d = disk.get(it["title"])
        if d:
            it.update(d)

    # 人工指定的原文地址（自动检索失败时使用）
    mu = os.path.join(DATA, "manual_urls.json")
    if os.path.exists(mu):
        urls = json.load(open(mu, encoding="utf-8"))
        for it in items:
            if it["title"] in urls:
                it["url"] = urls[it["title"]]

    json.dump(items, open(os.path.join(DATA, "items.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    f.save()
    cnt = {}
    for it in items:
        cnt[it["level"]] = cnt.get(it["level"], 0) + 1
    print("条目数：", len(items), cnt)


if __name__ == "__main__":
    build(refresh="--refresh" in sys.argv)
