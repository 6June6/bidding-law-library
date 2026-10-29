#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""检索索引构建：单元切分 + 全文 blob + 条号直达 + 术语同义词表

产出 data/search-index.json，供 render.py 内嵌到 index.html。
设计要点：
  1) 全文拼成一个 blob，检索时一次 indexOf 线性扫完（V8 有 SIMD，2.3M 字约 1-3ms），
     比逐篇拼接字符串快一个量级，也避免每次输入重新分配 2MB 内存。
  2) 正文切成「单元」（条/章/节/段），命中后能直接给出「第X条」定位，
     法律检索的价值在于定位到条，而不是只知道某篇文件里出现过。
  3) 条号做汉字↔阿拉伯数字归一，用户输「第36条」也能跳到「第三十六条」。
"""

import json
import os
import re
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, "data")

# ------------------------------------------------------------------ 单元切分

CN = "一二三四五六七八九十百零〇两"
RE_ART = re.compile(r"(?m)^\s*第\s*([%s\d]+)\s*条" % CN)
RE_HEAD = re.compile(r"(?m)^\s*第\s*([%s\d]+)\s*([章编节])" % CN)
RE_MD = re.compile(r"(?m)^\s{0,3}#{1,6}\s+(\S.*)$")
# 规范性文件的分节标记（常常与正文粘在同一行，所以不要求行首）
RE_SEC1 = re.compile(r"(?<![^\s（(])一、|(?<![^\s（(])二、|(?<![^\s（(])三、|(?<![^\s（(])四、|"
                     r"(?<![^\s（(])五、|(?<![^\s（(])六、|(?<![^\s（(])七、|(?<![^\s（(])八、|"
                     r"(?<![^\s（(])九、|(?<![^\s（(])十、|(?<![^\s（(])十一、|(?<![^\s（(])十二、")
RE_SEC2 = re.compile(r"（([%s]{1,3})）" % CN)

CN_NUM = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
          "六": 6, "七": 7, "八": 8, "九": 9}


def cn2int(s):
    """汉字数字 → int，支持 三十六 / 一百零二 / 一百二十"""
    s = s.strip()
    if s.isdigit():
        return int(s)
    if not s:
        return None
    total, section, cur = 0, 0, 0
    for ch in s:
        if ch == "十":
            section += (cur or 1) * 10
            cur = 0
        elif ch == "百":
            section += (cur or 1) * 100
            cur = 0
        elif ch in CN_NUM:
            cur = CN_NUM[ch]
        else:
            return None
    return total + section + cur


def split_units(text):
    """把一篇正文切成单元，返回 [(start, type, label)]，start 为 text 内偏移"""
    marks = []
    for m in RE_HEAD.finditer(text):
        marks.append((m.start(), 2, m.group(0).strip()))       # 2 = 章/节标题
    for m in RE_ART.finditer(text):
        marks.append((m.start(), 1, m.group(0).strip()))       # 1 = 条
    for m in RE_MD.finditer(text):
        marks.append((m.start(), 2, m.group(1).strip()))
    for m in RE_SEC1.finditer(text):
        marks.append((m.start(), 3, m.group(0).strip()))       # 3 = 一级段（一、）
    for m in RE_SEC2.finditer(text):
        marks.append((m.start(), 4, m.group(0).strip()))       # 4 = 二级段（（一））
    # 同一位置可能被多个规则命中，保留优先级最高的（条 > 章 > md > 一级段 > 二级段）
    marks.sort(key=lambda x: (x[0], x[1]))
    out, last_pos = [], -1
    for pos, typ, lab in marks:
        if pos == last_pos:
            continue
        if typ == 4 and out and out[-1][1] == 3 and pos - out[-1][0] < 40:
            continue      # 「一、xxx（一）yyy」里紧跟的（一）不算新段
        out.append((pos, typ, lab))
        last_pos = pos
    return out


# ------------------------------------------------------------------ 同义词

# 招投标 / 工程建设领域的等义与近义表达。查询时命中任一即算，权重略低。
SYNONYMS = [
    ["招标投标", "招投标", "招标采购"],
    ["招标人", "采购人", "建设单位", "业主", "发包人"],
    ["投标人", "供应商", "承包人", "竞标人"],
    ["中标", "成交", "中选"],
    ["评标", "评审", "评标评审"],
    ["评标委员会", "评标小组", "评审小组", "评标专家库"],
    ["投标保证金", "投标担保"],
    ["履约保证金", "履约担保", "履约保函"],
    ["串通投标", "串标", "围标", "陪标"],
    ["转包", "违法分包", "挂靠", "资质借用"],
    ["工程总承包", "EPC", "设计施工总承包"],
    ["招标代理", "代理机构", "招标代理机构"],
    ["资格预审", "资格审查", "预审"],
    ["招标文件", "招标文件范本", "招标文件示范文本"],
    ["招标公告", "招标公示", "采购公告"],
    ["否决投标", "废标", "投标无效"],
    ["异议", "质疑", "投诉"],
    ["公共资源交易", "公共资源交易平台", "交易中心"],
    ["电子招标投标", "电子招标", "全流程电子化", "电子交易"],
    ["农民工工资", "务工人员工资", "工资支付保障"],
    ["工程款", "工程价款", "结算款"],
    ["低价中标", "异常低价", "低于成本"],
    ["公平竞争审查", "公平竞争", "反垄断"],
    ["信用记录", "信用评价", "失信", "黑名单"],
    ["必须招标", "依法必须招标", "强制招标"],
    ["施工许可", "建筑工程施工许可", "开工许可"],
    ["竣工验收", "竣工验收备案", "竣工备案"],
    ["危大工程", "危险性较大的分部分项工程"],
    ["建设工程", "工程建设项目", "建筑工程"],
    ["造价", "工程造价", "计价", "工程计价"],
    ["勘察", "勘察设计", "岩土工程勘察"],
    ["监理", "工程监理", "监理单位"],
    ["资质", "资格", "资质许可"],
    ["安全生产", "施工安全", "安全管理"],
    ["质量", "工程质量", "质量管理"],
]


# ------------------------------------------------------------------ 构建


def load_body(it):
    p = os.path.join(BASE, it.get("file", ""))
    if not it.get("file") or not os.path.exists(p):
        return ""
    t = open(p, encoding="utf-8").read()
    t = re.sub(r"(?s)^---.*?---\s*", "", t)
    return t.strip("\n")


def build():
    its = json.load(open(os.path.join(DATA, "items.json"), encoding="utf-8"))
    its = [i for i in its if i.get("file")]

    blob_parts, docs, units_all, arts_all = [], [], [], []
    off = 0
    for di, it in enumerate(its):
        body = load_body(it)
        start = off
        blob_parts.append(body)
        off += len(body) + 1                      # +1 分隔符，防止跨篇误连
        us = split_units(body)
        u0 = len(units_all)
        arts = {}
        for pos, typ, lab in us:
            units_all.append([start + pos, typ, lab])
            if typ == 1:                          # 条：登记条号（汉字/数字归一）
                m = re.search(r"([%s\d]+)" % CN, lab)
                if m:
                    n = cn2int(m.group(1))
                    if n is not None:
                        arts[str(n)] = len(units_all) - 1
        docs.append({
            "i": di,
            "id": it.get("id") or "",
            "t": it["title"],
            "lv": it["level"],
            "cat": it.get("category", ""),
            "rg": it.get("region", "全国"),
            "rl": it.get("region_level", "全国"),
            "dn": it.get("doc_no") or "",
            "is": it.get("issuer_norm") or it.get("issuer") or "",
            "al": it.get("alias", []),
            "tg": it.get("tags", []),
            "pb": it.get("pub") or "",
            "ef": it.get("eff") or "",
            "st": it.get("status") or "",
            "es": it.get("eff_state") or "现行",
            "nt": it.get("note") or "",
            "src": it.get("src_url") or it.get("source") or "",
            "f": it.get("file") or "",
            "ch": it.get("chars") or len(body),
            "s": start, "e": off - 1,
            "u0": u0, "u1": len(units_all),
            "na": len(arts),
        })
        arts_all.append(arts)

    idx = {
        "built": time.strftime("%Y-%m-%d %H:%M"),
        "n": len(docs),
        "chars": sum(d["ch"] for d in docs),
        "docs": docs,
        "units": units_all,
        "arts": arts_all,
        "syn": SYNONYMS,
    }
    p = os.path.join(DATA, "search-index.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(idx, f, ensure_ascii=False, separators=(",", ":"))
    return idx, p


if __name__ == "__main__":
    idx, p = build()
    nu = len(idx["units"])
    na = sum(d["na"] for d in idx["docs"])
    print("文档 %d，字符 %d，单元 %d，条文 %d" % (idx["n"], idx["chars"], nu, na))
    print("写出", p, "%.2f MB" % (os.path.getsize(p) / 1048576))
    tc = {}
    for u in idx["units"]:
        tc[u[1]] = tc.get(u[1], 0) + 1
    print("单元类型：", {k: tc[k] for k in sorted(tc)}, "（1条 2章/标题 3一级段 4二级段）")
