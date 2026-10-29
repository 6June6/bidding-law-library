#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""元数据增强：机关归一 / 适用地区 / 简称别名 / 主题标签 / 日期兜底

只改写 items.json 的派生字段，不动正文。可重复执行（幂等）。
"""

import json
import os
import re
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, "data")

# ---------------------------------------------------------------- 行政区划

PROVINCES = [
    "北京", "天津", "上海", "重庆", "河北", "山西", "辽宁", "吉林", "黑龙江",
    "江苏", "浙江", "安徽", "福建", "江西", "山东", "河南", "湖北", "湖南",
    "广东", "海南", "四川", "贵州", "云南", "陕西", "甘肃", "青海",
    "内蒙古", "广西", "西藏", "宁夏", "新疆",
]
PROVINCE_FULL = {
    "北京": "北京市", "天津": "天津市", "上海": "上海市", "重庆": "重庆市",
    "河北": "河北省", "山西": "山西省", "辽宁": "辽宁省", "吉林": "吉林省",
    "黑龙江": "黑龙江省", "江苏": "江苏省", "浙江": "浙江省", "安徽": "安徽省",
    "福建": "福建省", "江西": "江西省", "山东": "山东省", "河南": "河南省",
    "湖北": "湖北省", "湖南": "湖南省", "广东": "广东省", "海南": "海南省",
    "四川": "四川省", "贵州": "贵州省", "云南": "云南省", "陕西": "陕西省",
    "甘肃": "甘肃省", "青海": "青海省", "内蒙古": "内蒙古自治区",
    "广西": "广西壮族自治区", "西藏": "西藏自治区", "宁夏": "宁夏回族自治区",
    "新疆": "新疆维吾尔自治区",
}
AUTONOMOUS = ["内蒙古自治区", "广西壮族自治区", "西藏自治区",
              "宁夏回族自治区", "新疆维吾尔自治区"]

# 标题/机关里的地区前缀（按优先级排列）
RE_TITLE_REGION = [
    re.compile(r"^(内蒙古自治区|广西壮族自治区|西藏自治区|宁夏回族自治区|新疆维吾尔自治区)"),
    re.compile(r"^(黑龙江|内蒙古|[\u4e00-\u9fa5]{2})省"),
    re.compile(r"^(北京|天津|上海|重庆)市"),
    re.compile(r"^([\u4e00-\u9fa5]{2,4})市(?!场)"),
    re.compile(r"^([\u4e00-\u9fa5]{2,4})经济特区"),
    re.compile(r"^([\u4e00-\u9fa5]{2,8})自治州"),
]
RE_ISSUER_REGION = [
    re.compile(r"^(内蒙古自治区|广西壮族自治区|西藏自治区|宁夏回族自治区|新疆维吾尔自治区)"),
    re.compile(r"^(黑龙江|内蒙古|[\u4e00-\u9fa5]{2})省"),
    re.compile(r"^([\u4e00-\u9fa5]{2,4})市"),
    re.compile(r"^([\u4e00-\u9fa5]{2,8})自治州"),
]

# 不是行政区划的误命中词
REGION_BLACK = {"城市", "市场", "超市", "本市", "我市", "全市", "各市", "省市"}


def _looks_region(name, level):
    """校验抽出来的地名是否可信"""
    if not name or name in REGION_BLACK:
        return False
    if level == "province":
        return name in PROVINCE_FULL
    if level == "city":
        return 2 <= len(name) <= 4
    if level == "prefecture":
        return len(name) >= 2
    return False


def extract_region(title, issuer):
    """返回 (region, region_level)；region_level ∈ 全国/省级/市级/州级"""
    for src, pats in ((title or "", RE_TITLE_REGION), (issuer or "", RE_ISSUER_REGION)):
        for rx in pats:
            m = rx.match(src)
            if not m:
                continue
            name = m.group(1)
            if name in AUTONOMOUS:
                return name, "省级"
            if rx.pattern.startswith("^(内蒙古自治区"):
                return name, "省级"
            if "省" in rx.pattern:
                lvl = "省级"
            elif "自治州" in rx.pattern:
                lvl = "州级"
            else:
                lvl = "市级"
            if _looks_region(name, "province" if lvl == "省级" else
                             ("prefecture" if lvl == "州级" else "city")):
                return name, lvl
    return "全国", "全国"


# ---------------------------------------------------------------- 机关归一

ISSUER_CANON = [
    # (正则, 规范名, 是否国家级)
    (r"国家发展改革委(员会)?|国家发展和改革委员会|国家发改委|国家计委|国家发展计划委员会",
     "国家发展和改革委员会", True),
    (r"(住房\s*和\s*城乡建设部|住房城乡建设部|建设部)", "住房和城乡建设部", True),
    (r"^国务院办公厅", "国务院办公厅", True),
    (r"^国务院$", "国务院", True),
    (r"全国人民代表大会常务委员会", "全国人民代表大会常务委员会", True),
    (r"^全国人民代表大会$", "全国人民代表大会", True),
    (r"^财政部", "财政部", True),
    (r"^最高人民法院", "最高人民法院", True),
    (r"^交通运输部", "交通运输部", True),
    (r"^工业和信息化部", "工业和信息化部", True),
    (r"^水利部", "水利部", True),
    (r"^商务部", "商务部", True),
    (r"^审计署", "审计署", True),
    (r"^国家市场监督管理总局|^市场监管总局", "国家市场监督管理总局", True),
]


def canon_issuer(issuer):
    """机关归一：返回 (规范机关, 联合发文标记)"""
    s = (issuer or "").strip()
    if not s:
        return "", False
    joint = bool(re.search(r"[、,，]|等\d*部门|等部门|等八部门|等十部门", s))
    for rx, canon, _nat in ISSUER_CANON:
        if re.search(rx, s):
            return canon, joint
    # 地方人大 / 政府
    s2 = re.sub(r"\s+", "", s)
    m = re.match(r"^(.{2,12}?)(人民代表大会常务委员会|人大常委会|人大常务委员会|人民代表大会)", s2)
    if m:
        return m.group(1) + "人民代表大会常务委员会", joint
    return s2, joint


# ---------------------------------------------------------------- 别名

RE_ALIAS_STRIP = [
    r"^中华人民共和国",
    r"^关于",
    r"^印发",
    r"^关于印发",
    r"^发布",
]
RE_ALIAS_TAIL = [
    r"的通知$", r"的意见$", r"的公告$", r"的办法$", r"的规定$",
    r"的若干规定$", r"实施细则$", r"的指导意见$", r"的暂行规定$",
]


def make_alias(title, level, region):
    """生成便于检索的简称（多个）"""
    t = re.sub(r"[《》\s]", "", title or "")
    aliases = set()
    base = t
    for rx in RE_ALIAS_STRIP:
        base = re.sub(rx, "", base)
    for rx in RE_ALIAS_TAIL:
        base2 = re.sub(rx, "", base)
        if base2 != base:
            aliases.add(base2)
    aliases.add(base)
    # 去掉书名号内的文件名（"关于印发《X》的通知" → X）
    m = re.findall(r"《([^》]+)》", title or "")
    for x in m:
        aliases.add(re.sub(r"\s", "", x))
    # 去掉地区前缀，便于按通用名检索
    if region != "全国":
        for a in list(aliases):
            stripped = re.sub(r"^" + re.escape(region), "", a)
            if len(stripped) >= 4:
                aliases.add(stripped)
    aliases.discard("")
    aliases.discard(t)
    return sorted(aliases, key=len)


# ---------------------------------------------------------------- 主题标签

# (主题, 强特征词(标题命中=确证), 弱特征词(仅正文计数))
TOPICS = [
    ("招标程序", r"招标|投标|发包|承包|比选|竞价|采购方式", r"招标|投标|发包|承包"),
    ("政府采购", r"政府采购|采购人|供应商|集中采购|分散采购|协议供货|框架协议|合作创新采购|进口产品|单一来源|竞争性谈判|竞争性磋商|询价", r"政府采购|采购人|供应商"),
    ("评标定标", r"评标|评审|定标|中标|成交|评标委员会|评标专家", r"评标|定标|中标|评审专家"),
    ("公告与文件", r"招标公告|资格预审|招标文件|投标文件|标底|最高限价|招标控制价|开标", r"招标文件|资格预审|招标公告"),
    ("代理机构", r"招标代理|代理机构|代理资格|采购代理", r"招标代理|代理机构"),
    ("交易平台", r"公共资源交易|交易平台|电子招标|电子交易|远程异地|不见面开标|交易目录|平台整合|交易场所", r"公共资源交易|交易平台|电子招标"),
    ("资质与人员", r"资质|执业资格|注册(建筑师|结构工程师|建造师|造价工程师|监理工程师)|建造师|造价工程师|监理工程师|从业人员|能力评价|准入清出", r"资质许可|执业资格|注册执业"),
    ("合同与履约", r"合同|履约|违约|担保|保证金|工程款|结算|拖欠|农民工工资|分包|转包|挂靠", r"合同履行|履约|工程款|农民工工资"),
    ("造价与计价", r"造价|计价|工程量清单|招标控制价|定额|投资评审|估算|概算", r"造价|工程量清单|计价"),
    ("质量", r"质量|竣工验收|保修|质量检测|质量事故|质量监督", r"工程质量|质量管理"),
    ("安全生产", r"安全生产|施工安全|危大工程|危险性较大|安全事故|应急预案|消防|扬尘|职业病", r"安全生产|施工安全"),
    ("勘察设计", r"勘察|设计|施工图|抗震|抗震设防|初步设计|设计文件审查", r"勘察设计|施工图"),
    ("监理", r"监理|项目监理|总监", r"监理"),
    ("工程总承包", r"总承包|工程总承包|EPC|项目管理|代建", r"工程总承包|EPC"),
    ("市场与信用", r"信用|守信|失信|黑名单|联合惩戒|信用评价|诚信|违法行为记录|不良行为", r"信用评价|失信|不良行为记录"),
    ("监督与救济", r"监督|监察|投诉|异议|质疑|举报|行政复议|行政处罚|查处|问责|责任追究|审计", r"投诉处理|行政处罚|行政监督"),
    ("公平竞争审查", r"公平竞争|公平竞争审查|统一大市场|壁垒|地方保护|市场准入|营商环境", r"公平竞争审查|地方保护|市场壁垒"),
    ("投资与审批", r"投资|审批|核准|备案|立项|政府投资|中央预算|可行性研究|并联审批|施工许可", r"投资项目|审批|核准|备案"),
    ("信息化与AI", r"人工智能|数字化|大数据|信息化|智慧|数字化转型|数据共享|AI", r"数字化|人工智能"),
    ("环境保护", r"环境保护|污染防治|节能|绿色|碳排放|扬尘|噪声|生态|环境影响", r"环境保护|节能减排"),
    ("基础设施专业", r"公路|水运|港口|铁路|民航|水利|电力|市政|轨道交通|桥梁|隧道|人防|管线|机场", r"公路|水运|市政|人防"),
    ("财政与预算", r"预算|财政|资金|国库|税收|价格|收费|财政投资", r"财政资金|预算管理"),
]


def make_tags(title, text_head, level):
    """主题标签：标题命中即确证；标题未命中时，靠全文特征词密度补，最多补 2 个。

    只靠正文容易误标——总则里「监督管理」「投资」几乎篇篇都有，所以正文派生
    要求强特征词 ≥3 次且弱特征词 ≥4 次，并且排在标题派生的标签之后。
    """
    t = title or ""
    body = text_head or ""
    strong_hit, derived = [], []
    for name, strong, weak in TOPICS:
        if re.search(strong, t):
            strong_hit.append((len(re.findall(strong, t)), name))
            continue
        ns = len(re.findall(strong, body))
        nw = len(re.findall(weak, body))
        if ns >= 3 and nw >= 4:
            derived.append((ns * 2 + nw, name))
    strong_hit.sort(key=lambda x: (-x[0], x[1]))
    derived.sort(key=lambda x: (-x[0], x[1]))
    tags = [n for _, n in strong_hit[:4]]
    tags += [n for _, n in derived[:2] if n not in tags]
    return tags[:4]


# ---------------------------------------------------------------- 主流程


def body_head(it, n=0):
    """全文（n<=0 时不限）；用于主题标签的词频统计"""
    p = os.path.join(BASE, it.get("file", ""))
    if not it.get("file") or not os.path.exists(p):
        return ""
    t = open(p, encoding="utf-8").read()
    t = re.sub(r"(?s)^---.*?---", "", t)
    return t if n <= 0 else t[:n]


def main(apply=False):
    path = os.path.join(DATA, "items.json")
    its = json.load(open(path, encoding="utf-8"))
    changed = 0
    region_stat = {}
    issuer_stat = {}
    for it in its:
        title = it.get("title", "")
        issuer_raw = (it.get("issuer") or "").strip()
        canon, joint = canon_issuer(issuer_raw)
        region, rlvl = extract_region(title, canon)

        before = (it.get("issuer_norm"), it.get("region"), it.get("alias"), it.get("tags"))
        it["issuer_norm"] = canon
        it["joint"] = joint
        it["region"] = region
        it["region_level"] = rlvl
        it["alias"] = make_alias(title, it.get("level"), region)
        tags = make_tags(title, body_head(it), it.get("level"))
        it["tags"] = tags or [it.get("category") or "其他"]
        # 施行日期兜底：无则取公布日期（并在 note 里不谎称）
        if not it.get("eff") and it.get("pub"):
            it["eff"] = it["pub"]
            it["eff_fallback"] = True
        if (it.get("issuer_norm"), it.get("region"), it.get("alias"), it.get("tags")) != before:
            changed += 1
        region_stat[region] = region_stat.get(region, 0) + 1
        issuer_stat[canon] = issuer_stat.get(canon, 0) + 1

    print("条目 %d，变更 %d" % (len(its), changed))
    print("\n=== 地区分布（前 25） ===")
    for k, v in sorted(region_stat.items(), key=lambda x: -x[1])[:25]:
        print("  %-10s %d" % (k, v))
    print("  地区种类：%d" % len(region_stat))
    print("\n=== 机关归一后（前 20） ===")
    for k, v in sorted(issuer_stat.items(), key=lambda x: -x[1])[:20]:
        print("  %-30s %d" % (k, v))
    print("  机关种类：%d（归一前 90）" % len(issuer_stat))

    if apply:
        json.dump(its, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("\n已写回", path)
    else:
        print("\n（预演，未落盘。加 --apply 生效）")


if __name__ == "__main__":
    main("--apply" in sys.argv)
