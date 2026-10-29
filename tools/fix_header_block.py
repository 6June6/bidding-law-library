#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""清掉住建部「规章库/规范性文件库」页面自带的公文信息块，并把里面的
文号、发文日期、实施日期回填进 items.json。

这些页面的正文形如：

    # 标题
    ....................................................
    公文名称： … 索 引 号： … 分 类： … 发文单位： … 发文日期： … 文 号： …
    ....................................................
    标题（重复一次）
    正文……

两个点线之间的内容一律删除；重复标题也删掉。

用法：
  python3 tools/fix_header_block.py            # 预演
  python3 tools/fix_header_block.py --apply    # 落盘
"""

import json
import os
import re
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, "data")
DOTS = re.compile(r"^[.．·]{8,}$")


def split_md(text):
    m = re.match(r"(?s)^(---\n.*?\n---\n)(.*)$", text)
    return (m.group(1), m.group(2)) if m else ("", text)


def parse_block(block):
    """从公文信息块里取文号 / 发文日期 / 实施日期 / 发文单位"""
    flat = re.sub(r"\s+", "", block)
    info = {}
    m = re.search(r"文号[:：]([^：:]{4,40}?)(?:主题词|实施日期|$)", flat)
    if m:
        info["doc_no"] = m.group(1)
    m = re.search(r"发文日期[:：](\d{4}-\d{2}-\d{2})", flat)
    if m:
        info["pub"] = m.group(1)
    m = re.search(r"实施日期[:：]?(\d{4}-\d{2}-\d{2})", flat)
    if m:
        info["eff"] = m.group(1)
    m = re.search(r"发文单位[:：]([^：:]{4,40}?)(?:发文日期|文号|$)", flat)
    if m:
        info["issuer"] = m.group(1)
    return info


def main():
    apply = "--apply" in sys.argv
    items = json.load(open(os.path.join(DATA, "items.json"), encoding="utf-8"))
    changed = 0
    for it in items:
        fp = os.path.join(BASE, it.get("file") or "")
        if not it.get("file") or not os.path.exists(fp):
            continue
        head, body = split_md(open(fp, encoding="utf-8").read())
        lines = body.split("\n")
        idx = [i for i, x in enumerate(lines) if DOTS.match(x.strip())]
        if len(idx) < 2:
            continue
        a, b = idx[0], idx[1]
        info = parse_block("\n".join(lines[a:b]))
        rest = lines[:a] + lines[b + 1:]
        # 点线之后常把标题重复一遍（只删重复的纯标题行，H1 保留）
        while rest and not rest[0].strip():
            rest.pop(0)
        if rest and rest[0].strip() == it["title"]:
            rest.pop(0)
            while rest and not rest[0].strip():
                rest.pop(0)
        for k in ("doc_no", "pub", "eff"):
            if info.get(k) and not (it.get(k) or "").strip("—-"):
                it[k] = info[k]
        if info.get("issuer") and (it.get("issuer") or "") in ("", "—"):
            it["issuer"] = info["issuer"]
        changed += 1
        if apply:
            open(fp, "w", encoding="utf-8").write(head + "\n" + "\n".join(rest).lstrip("\n"))
    if apply:
        json.dump(items, open(os.path.join(DATA, "items.json"), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
    print("%s %d 个文件" % ("已清理" if apply else "待清理", changed))


if __name__ == "__main__":
    main()
