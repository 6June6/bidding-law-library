#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""采集「index.html + index_N.html」型栏目列表（发改委等传统政务站）。

用法：
  python3 tools/list_harvest.py <栏目URL> --out data/list_xxx.json [--pages 10] [--strict]
输出与 gz_harvest 同构（title/url/note/doc），可直接交给 gz_import.py。
"""

import html
import json
import os
import re
import sys
import time
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gz_harvest as G  # noqa: E402

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, "data")


def page_url(base, i):
    if i == 0:
        return base
    return re.sub(r"index(\.html?)?$", "index_%d.html" % i, base if base.endswith(("html", "htm")) else base + "index.html")


def harvest(base, pages=10):
    rows, seen = [], set()
    for i in range(pages):
        u = page_url(base, i)
        try:
            h = G.get(u).decode("utf-8", "ignore")
        except Exception:
            break
        got = 0
        for m in re.finditer(r'<a[^>]+href="([^"#]+)"[^>]*?(?:title="([^"]*)")?[^>]*>\s*([^<]{4,90})\s*</a>', h):
            href, title, text = m.group(1), (m.group(2) or "").strip(), m.group(3).strip()
            t = html.unescape(title or text)
            if not t or len(t) < 4:
                continue
            if not re.search(r"t\d{8}_\d+\.html?$", href):
                continue
            full = urllib.parse.urljoin(u, href)
            if full in seen:
                continue
            seen.add(full)
            # 同一条目常有两个链接（标题 + 解读），只留标题行
            rows.append(dict(title=t, url=full, note=text if text != t else "", doc=""))
            got += 1
        if not got:
            break
        time.sleep(0.4)
    return rows


def main():
    base = sys.argv[1]
    out = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else \
        os.path.join(DATA, "list_%s.json" % re.sub(r"\W+", "_", base.split("//")[-1])[:40])
    pages = int(sys.argv[sys.argv.index("--pages") + 1]) if "--pages" in sys.argv else 10
    strict = "--strict" in sys.argv
    ling = "--ling" in sys.argv
    rows = harvest(base, pages)
    keep = 0
    for i, r in enumerate(rows, 1):
        r["no"] = i
        ok = any(k in r["title"] for k in (G.STRONG if strict else G.DOMAIN)) \
            and not any(k in r["title"] for k in G.SKIP)
        if strict:
            ok = ok and not any(k in r["title"] for k in G.WEAK)
        if ling:   # 只要真正的委令，剔掉解读/答记者问与无关行业
            ok = bool(re.search(r"第\s*\d+\s*号令?$|第\s*\d+\s*号", r["title"])) \
                and not re.search(r"解读|答记者问|公布|修改、废止", r["title"]) \
                and any(k in r["title"] for k in ("招标", "投标", "采购", "评标", "工程",
                                                  "投资", "特许经营", "公共资源", "咨询"))
        if ling:
            m = re.search(r"《([^》]{4,80})》", r["title"])
            no = re.search(r"第\s*(\d+)\s*号", r["title"])
            r["raw_title"] = r["title"]
            if m:
                r["title"] = m.group(1)
            r["doc_no"] = ("国家发展和改革委员会令第%s号" % no.group(1)) if no else ""
            r["pub"] = ""
        r["keep"] = ok
        keep += 1 if ok else 0
    json.dump(rows, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("解析 %d 条，本领域 %d 条 -> %s" % (len(rows), keep, out))
    for r in rows:
        if r["keep"]:
            print("  %s" % r["title"][:70])


if __name__ == "__main__":
    main()
