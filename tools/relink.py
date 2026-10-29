#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按磁盘上的 Markdown 回填 items.json 的 file / src_url / chars。

清洗、重抓、多脚本并行之后，条目字段可能与磁盘脱节，跑这个对齐即可。
识别依据是正文头部 YAML 的「名称」，而不是文件名或编号。
"""

import json
import os
import re
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, "data")


def main():
    items = json.load(open(os.path.join(DATA, "items.json"), encoding="utf-8"))
    disk = {}
    for root, _dirs, files in os.walk(BASE):
        if os.path.basename(root).startswith(("data", "tools", ".git")):
            continue
        for fn in files:
            if not fn.endswith(".md"):
                continue
            fp = os.path.join(root, fn)
            txt = open(fp, encoding="utf-8").read()
            m = re.search(r"^名称: (.+)$", txt, re.M)
            if not m:
                continue
            u = re.search(r"^原文地址: (\S*)$", txt, re.M)
            body = re.sub(r"(?s)^---.*?\n---\n", "", txt)
            disk.setdefault(m.group(1).strip(), dict(
                file=os.path.relpath(fp, BASE), src_url=(u.group(1) if u else ""),
                chars=len(re.sub(r"\s", "", body))))

    fixed = 0
    for it in items:
        d = disk.get(it["title"])
        if d and (not it.get("file") or not os.path.exists(os.path.join(BASE, it["file"]))):
            it.update(d)
            fixed += 1
    # 磁盘上的地址比条目里更权威时同步（法规库/部委站）
    for it in items:
        if it.get("file") and it.get("src_url") and not it["src_url"].startswith("http"):
            d = disk.get(it["title"])
            if d and d.get("src_url"):
                it["src_url"] = d["src_url"]
    json.dump(items, open(os.path.join(DATA, "items.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    miss = [x for x in items if not (x.get("file") and os.path.exists(os.path.join(BASE, x["file"])))]
    print("回填 %d 条；仍缺全文 %d / %d" % (fixed, len(miss), len(items)))
    for x in miss:
        print("  MISS %-5s %s" % (x["id"], x["title"][:46]))


if __name__ == "__main__":
    sys.exit(main())
