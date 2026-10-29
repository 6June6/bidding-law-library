#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""补齐空白的公布/施行日期。

优先用「沿革」题注里的首个日期（立法通过日），其次用正文落款日期
（通知类文件末尾的「二〇一一年五月三十日」或「2011年5月30日」）。

用法：python3 tools/fix_dates.py [--apply]
"""

import json
import os
import re
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, "data")
CN = {"〇": "0", "○": "0", "Ｏ": "0", "零": "0", "一": "1", "二": "2", "三": "3",
      "四": "4", "五": "5", "六": "6", "七": "7", "八": "8", "九": "9"}


def cn_date(s):
    """二〇一一年五月三十日 → 2011-05-30"""
    m = re.match(r"^([〇○Ｏ零一二三四五六七八九]{4})年([一二三四五六七八九十]{1,3})月"
                 r"([一二三四五六七八九十]{1,3})日$", s)
    if not m:
        return ""
    y = "".join(CN[c] for c in m.group(1))

    def num(t):
        if t == "十":
            return 10
        if t.startswith("十"):
            return 10 + CN.get(t[1], "0") if len(t) > 1 else 10
        if "十" in t:
            a, b = t.split("十")
            return int(CN.get(a, "0")) * 10 + (int(CN.get(b, "0")) if b else 0)
        return int(CN.get(t, "0"))
    return "%s-%02d-%02d" % (y, num(m.group(2)), num(m.group(3)))


def main():
    apply = "--apply" in sys.argv
    items = json.load(open(os.path.join(DATA, "items.json"), encoding="utf-8"))
    n = 0
    for it in items:
        if (it.get("pub") or "").strip("—-"):
            continue
        note = it.get("note") or ""
        m = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", note)
        pub = "%s-%02d-%02d" % (m.group(1), int(m.group(2)), int(m.group(3))) if m else ""
        if not pub and it.get("file"):
            fp = os.path.join(BASE, it["file"])
            if os.path.exists(fp):
                lines = [x.strip() for x in open(fp, encoding="utf-8").read().split("\n") if x.strip()]
                for ln in reversed(lines[-8:]):
                    m2 = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日$", ln)
                    if m2:
                        pub = "%s-%02d-%02d" % (m2.group(1), int(m2.group(2)), int(m2.group(3)))
                        break
                    cd = cn_date(re.sub(r"[　 ]", "", ln))
                    if cd:
                        pub = cd
                        break
        if pub:
            it["pub"] = pub
            if not (it.get("eff") or "").strip("—-"):
                it["eff"] = pub
            n += 1
    if apply:
        json.dump(items, open(os.path.join(DATA, "items.json"), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
    left = [x["id"] for x in items if not (x.get("pub") or "").strip("—-")]
    print("%s %d 条；仍无日期 %d %s" % ("已补" if apply else "待补", n, len(left), " ".join(left[:10])))


if __name__ == "__main__":
    main()
