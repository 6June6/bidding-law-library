#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""清理既有 Markdown 里的网站噪声（页脚、导航、栏目字段、重复块）。

清洗规则与抓取时共用 `fetch_docs.sanitize`，所以新抓的与旧文件口径一致。
条文行（第X条）与章/节标题永不删除。

  python3 tools/sanitize_docs.py            # 预演，只出报告
  python3 tools/sanitize_docs.py --apply    # 落盘
  python3 tools/sanitize_docs.py --apply E05 E22
"""

import json
import os
from collections import Counter
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fetch_docs as F  # noqa: E402

DATA = os.path.join(F.BASE, "data")
HEAD = re.compile(r"^---\n.*?\n---\n", re.S)
TAIL = re.compile(r"\n---\n\n> 本文由公开官方渠道抓取整理.*$", re.S)


def split_md(t):
    m = HEAD.match(t)
    if not m:
        return None, None, None
    head, rest = m.group(0), t[m.end():]
    mt = TAIL.search(rest)
    body, tail = (rest[:mt.start()], rest[mt.start():]) if mt else (rest, "")
    return head, body, tail


def main():
    apply = "--apply" in sys.argv
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    items = json.load(open(os.path.join(DATA, "items.json"), encoding="utf-8"))
    todo = [x for x in items if not args or x["id"] in args]
    report, n_file, n_line = [], 0, 0

    for it in todo:
        p = os.path.join(F.BASE, it["file"])
        head, body, tail = split_md(open(p, encoding="utf-8").read())
        if head is None:
            continue
        lines = [x.strip() for x in body.split("\n") if x.strip()]
        clean = F.sanitize(lines)
        left = Counter(clean)
        removed = []
        for x in lines:
            if left.get(x, 0) > 0:
                left[x] -= 1
            else:
                removed.append(x)
        if not removed:
            continue
        n_file += 1
        n_line += max(0, len(lines) - len(clean))
        report.append("### %s %s（%d → %d 行）" % (it["id"], it["title"][:30],
                                                len(lines), len(clean)))
        for x in removed[:12]:
            report.append("   - " + x[:150])
        if len(removed) > 12:
            report.append("   … 另 %d 行" % (len(removed) - 12))

        if apply:
            new = head + "\n" + "\n\n".join(clean) + "\n" + (tail if tail else "")
            new = re.sub(r"\n{3,}", "\n\n", new)
            open(p, "w", encoding="utf-8").write(new)
            it["chars"] = sum(len(x) for x in clean)

    out = "\n".join(report) or "（无需要清理的内容）"
    open(os.path.join(DATA, "clean-report.txt"), "w", encoding="utf-8").write(out)
    print(out[:7000])
    print("\n合计：%d 个文件，删除约 %d 行%s" %
          (n_file, n_line, "（已落盘）" if apply else "（预演，未改动）"))

    if apply:
        json.dump(items, open(os.path.join(DATA, "items.json"), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
