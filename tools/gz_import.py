#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 gz_harvest.py 采到的部委规章清单并入 items.json，并下载官方「文字版」正文。

用法：
  python3 tools/gz_import.py data/gz_mohurd_gz.json --level 部门规章 \
      --issuer 住房和城乡建设部 [--dry]
"""

import json
import os
import re
import sys
import time
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fetch_docs as F       # noqa: E402
import flk_fetch as K        # noqa: E402
import gz_harvest as G       # noqa: E402
from harvest import guess_category  # noqa: E402

DATA = os.path.join(F.BASE, "data")
LEVEL_CODE = {"法律": "A", "行政法规": "B", "部门规章": "C",
              "地方性法规": "D", "规范性文件": "E", "司法解释": "F"}


def lines_of(raw):
    if raw[:2] == b"PK":
        return K.docx_lines(raw)
    if raw[:4] == b"%PDF":
        return K.pdf_lines(raw)
    return K.doc_lines(raw)


def main():
    path = sys.argv[1]
    level = sys.argv[sys.argv.index("--level") + 1] if "--level" in sys.argv else "部门规章"
    issuer = sys.argv[sys.argv.index("--issuer") + 1] if "--issuer" in sys.argv else ""
    dry = "--dry" in sys.argv
    rows = json.load(open(path, encoding="utf-8"))
    items = json.load(open(os.path.join(DATA, "items.json"), encoding="utf-8"))
    have = {x["title"] for x in items}
    used = {x["id"] for x in items}
    nxt = {}
    for x in items:
        nxt[x["level"]] = max(nxt.get(x["level"], 0), int(x["id"][1:]))

    sel = [r for r in rows if r.get("keep", True) and r["title"] not in have]
    print("待入库 %d 条（清单 %d，已有 %d）" % (len(sel), len(rows), len(rows) - len(sel)))
    if dry:
        for r in sel:
            print("  %-50s %-26s %s" % (r["title"][:48], r.get("doc_no", ""), r.get("pub", "")))
        return

    ok = 0
    for n, r in enumerate(sel, 1):
        host = "https://" + r["url"].split("/")[2] if r["url"].startswith("http") else "https://www.mohurd.gov.cn"
        doc = r.get("doc") or ""
        art = (r["url"] if r["url"].startswith("http") else host + r["url"])
        lines = []
        if doc:
            url = doc if doc.startswith("http") else host + doc
            try:
                raw = G.get(url, referer=host + "/")
                lines = lines_of(raw)
            except Exception as e:
                print("ERR  %-44s %s" % (r["title"][:44], e))
                lines = []
        if not lines:                      # 没有文字版就退回网页正文
            try:
                h, _ = F.fetch(art, referer=host + "/")
                if h:
                    lines = F.extract_article(h, r["title"])
                    # 委令页往往只有「令」本身，办法全文在附件里
                    if sum(len(x) for x in lines) < 1500:
                        cand = re.findall(r'href="([^"]+\.(?:pdf|docx?))"', h, re.I)
                        for cu in cand[:4]:
                            cu = urllib.parse.urljoin(art, cu)
                            try:
                                if cu.lower().endswith(".pdf"):
                                    pl = F.pdf_text(cu)
                                else:
                                    pl = lines_of(G.get(cu, referer=art))
                            except Exception:
                                pl = []
                            if pl and sum(len(x) for x in pl) > sum(len(x) for x in lines) \
                                    and F.score(pl, r["title"])[0]:
                                lines = pl
                                art = cu
                                break
            except Exception as e:
                print("ERR  %-44s 网页正文 %s" % (r["title"][:44], e))
                lines = []
        hit, ln, arts = F.score(lines, r["title"])
        if not hit or ln < 400:
            print("MISS %-44s hit=%d 字数=%d" % (r["title"][:44], hit, ln))
            continue
        it = dict(level=level, title=r["title"], doc_no=r.get("doc_no", ""),
                  issuer=issuer or r.get("issuer", ""), pub=r.get("pub", ""),
                  eff=r.get("eff", "") or r.get("pub", ""), status="现行有效",
                  note=r.get("note", ""), source=art, source_name="官方网站",
                  category=guess_category(r["title"]), query=r["title"])
        nxt[level] = nxt.get(level, 0) + 1
        it["id"] = "%s%02d" % (LEVEL_CODE[level], nxt[level])
        while it["id"] in used:
            nxt[level] += 1
            it["id"] = "%s%02d" % (LEVEL_CODE[level], nxt[level])
        used.add(it["id"])
        fn = os.path.join(F.BASE, F.LEVEL_DIR[level], F.safe_name(it["title"], it["pub"]))
        os.makedirs(os.path.dirname(fn), exist_ok=True)
        open(fn, "w", encoding="utf-8").write(F.render_md(it, lines, art))
        it["file"] = os.path.relpath(fn, F.BASE)
        it["src_url"] = art
        it["chars"] = ln
        items.append(it)
        have.add(it["title"])
        ok += 1
        print("[%d/%d] OK %-42s %5d 字 %2d 条" % (n, len(sel), r["title"][:42], ln, arts), flush=True)
        time.sleep(0.8)

    json.dump(items, open(os.path.join(DATA, "items.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("入库 %d 条，条目总数 %d" % (ok, len(items)))


if __name__ == "__main__":
    main()
