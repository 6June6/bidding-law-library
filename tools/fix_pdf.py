#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PDF 来源文本清洗：去掉页眉页脚与页码，合并 PDF 折行。

用法：python3 tools/fix_pdf.py            # 处理所有 src_url 为 .pdf 的条目
      python3 tools/fix_pdf.py C15
"""

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fetch_docs as F  # noqa: E402

DATA = os.path.join(F.BASE, "data")

# 页眉页脚 / 附件标记（PDF 抽出的噪声行）
NOISE = [
    re.compile(r"^-\s*\d+\s*-$"),                      # - 3 -
    re.compile(r"^第\s*\d+\s*页"),
    re.compile(r"中华人民共和国.*(委员会|部)(规章|令)$"),
    re.compile(r"^中华人民共和国.*(发布|规章)$"),
    re.compile(r"^(国家发展改革委|财政部|住房城乡建设部).{0,12}(发布|公告)$"),
    re.compile(r"^附件\s*[：:]?\s*\d*$"),
    re.compile(r"^[0-9]+附件$"),
]
HEADLINE = re.compile(r"^(##\s|第[一二三四五六七八九十百零〇\d]+[条章节]|[（(][一二三四五六七八九十]+[)）]|"
                      r"[一二三四五六七八九十]+、|附\s*则|总\s*则)")
END_PUNCT = "。；：！？」』】…"


def clean(lines):
    out = []
    for ln in lines:
        ln = ln.strip()
        if not ln:
            continue
        if any(p.search(ln) for p in NOISE):
            continue
        if out and out[-1] and out[-1][-1] not in END_PUNCT and not HEADLINE.match(ln) \
                and not out[-1].startswith("#"):
            out[-1] += ln          # PDF 折行：直接续上
        else:
            out.append(ln)
    return out


def main():
    sel = [a for a in sys.argv[1:] if not a.startswith("-")]
    items = json.load(open(os.path.join(DATA, "items.json"), encoding="utf-8"))
    for it in items:
        if sel and it["id"] not in sel:
            continue
        u = str(it.get("src_url") or "")
        if not u.lower().endswith(".pdf"):
            continue
        lines = F.pdf_text(u)
        if not lines:
            print("SKIP", it["id"], "PDF 取不到文本")
            continue
        lines = clean(lines)
        fn = os.path.join(F.BASE, it["file"])
        open(fn, "w", encoding="utf-8").write(F.render_md(it, lines, u))
        it["chars"] = sum(len(x) for x in lines)
        print("OK  ", it["id"], it["title"][:26], it["chars"])
    json.dump(items, open(os.path.join(DATA, "items.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
