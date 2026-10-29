#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""正文与元数据的最后一道修整：

1. 拆粘连：规范性文件网页版常把「标题＋文号＋主送机关＋正文」挤成一段，
   拆成独立行，正文从「各省…：」之后才真正开始。
2. 补日期：从正文落款/施行条款里回抽公布与施行日期（兼容全角数字与内嵌空格）。
3. 标状态：施行日期晚于今天的，标为「已公布待施行」，避免误当现行规则引用。

安全底线同 sanitize：条文行与章/节标题在任何规则下都不动。
"""

import json
import os
import re
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, "data")

FM = re.compile(r"(?s)^---.*?---\s*")
ART_RE = re.compile(r"^\s*第[一二三四五六七八九十百零〇\d]+条")
HEAD_RE = re.compile(r"^\s*第[一二三四五六七八九十百零〇\d]+(?:分编|编|章|节)")

RE_DOCNO = re.compile(r"^([\u4e00-\u9fa5A-Za-z]{2,12}\s*[〔\[（(]\s*\d{4}\s*[〕\]）)]\s*\d{1,4}\s*号)")
RE_TO = re.compile(r"^([^：]{4,90}：)")
RE_DATE = re.compile(r"(20\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日")
RE_EFF = re.compile(r"自\s*(.{0,30}?)\s*(?:起)?\s*(?:施行|执行|生效)")
RE_YEAR_IN_FILE = re.compile(r"[（(](19|20)(\d{2})[）)]")

FULLWIDTH = {ord("０") + i: ord("0") + i for i in range(10)}
FULLWIDTH.update({ord("％"): ord("%"), ord("　"): ord(" ")})


def norm_num(s):
    return s.translate(FULLWIDTH).replace(" ", "")


def split_fm(path):
    raw = open(path, encoding="utf-8").read()
    m = FM.match(raw)
    if not m:
        return {}, raw
    return raw[:m.end()], raw[m.end():]


def fix_glue(it, body):
    """拆「标题＋文号＋主送机关＋正文」粘连，返回 (新正文, 是否改动)"""
    title = it["title"]
    lines = body.split("\n")
    # 找到第一个实质段落
    idx = None
    for i, l in enumerate(lines):
        s = l.strip()
        if not s or s.startswith("#"):
            continue
        idx = i
        break
    if idx is None:
        return body, False
    first = lines[idx].strip()
    if not first.startswith(title):
        return body, False
    if ART_RE.match(first) or HEAD_RE.match(first):
        return body, False
    # 篇名已由「# 标题」行给出才拆，避免把没有标题行的文件的正文开头吃掉
    if not any(l.strip().startswith("#") and title in l for l in lines):
        return body, False
    rest = first[len(title):].strip()
    if len(rest) < 8:
        return body, False
    out = []
    m = RE_DOCNO.match(rest)
    if m:
        out.append(m.group(1).strip())
        rest = rest[m.end():].strip()
    m = RE_TO.match(rest)
    if m and not ART_RE.match(rest):
        out.append(m.group(1).strip())
        rest = rest[m.end():].strip()
    if rest:
        out.append(rest)
    if not out:
        return body, False
    lines[idx] = "\n".join(out)
    return "\n".join(lines), True


def pick_dates(it, body):
    """返回 (pub, eff, 来源说明)"""
    b = norm_num(body)
    pub, eff = it.get("pub"), it.get("eff")
    src = []
    ds = [("%s-%02d-%02d" % (int(a), int(b2), int(c))) for a, b2, c in RE_DATE.findall(b)]
    if not eff:
        # 施行条款优先
        for seg in RE_EFF.findall(b)[:3]:
            m = RE_DATE.search(seg)
            if m:
                eff = "%s-%02d-%02d" % (int(m.group(1)), int(m.group(2)), int(m.group(3)))
                src.append("施行条款")
                break
    if not eff and ds:
        eff = ds[-1]
        src.append("正文落款")
    if not pub:
        m = RE_YEAR_IN_FILE.search(it.get("file") or "")
        if m:
            # 只有年份信息就只记年，不编造月日
            pub = m.group(1) + m.group(2)
            src.append("仅年")
        elif ds:
            # 正文里唯一的日期往往就是施行日，不能拿来当公布日
            cand = [d for d in ds if d != eff]
            if cand:
                pub = cand[0]
                src.append("正文日期")
    if not eff and pub:
        eff = pub
        src.append("沿用公布日")
    return pub, eff, "+".join(src)


def main(apply=False):
    its = json.load(open(os.path.join(DATA, "items.json"), encoding="utf-8"))
    today = time.strftime("%Y-%m-%d")
    nglue = ndate = nstate = 0
    for it in its:
        p = os.path.join(BASE, it.get("file", ""))
        if not it.get("file") or not os.path.exists(p):
            continue
        fm, body = split_fm(p)
        newbody = body

        nb, changed = fix_glue(it, newbody.lstrip("\n"))
        if changed:
            nglue += 1
            newbody = "\n" + nb

        pub, eff, src = pick_dates(it, nb)
        if (pub and pub != it.get("pub")) or (eff and eff != it.get("eff")):
            if pub:
                it["pub"] = pub
            if eff:
                it["eff"] = eff
            if src:
                it["date_src"] = src
            ndate += 1

        # 效力状态派生
        e = it.get("eff") or ""
        st = "现行" if (not e or e <= today) else "待施行"
        if it.get("eff_state") != st:
            it["eff_state"] = st
            nstate += 1

        if changed and apply:
            open(p, "w", encoding="utf-8").write(fm + newbody)

    print("粘连拆分 %d 篇，日期补全 %d 篇，状态标注 %d 篇（今天 %s）" % (nglue, ndate, nstate, today))
    pend = [i for i in its if i.get("eff_state") == "待施行"]
    if pend:
        print("\n=== 已公布待施行 ===")
        for i in pend:
            print("  %s  %s  （公布 %s / 施行 %s）" % (i["id"], i["title"][:34], i.get("pub") or "—", i.get("eff")))
    if apply:
        json.dump(its, open(os.path.join(DATA, "items.json"), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        print("\n已写回 items.json 与正文")
    else:
        print("\n（预演，未落盘。加 --apply 生效）")


if __name__ == "__main__":
    main("--apply" in sys.argv)
