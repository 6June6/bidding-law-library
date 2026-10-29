#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用正文题注回填「沿革」（YAML 头的 note 字段）。

题注形如：
  （1996年9月25日……通过　根据2004年6月29日……第一次修正　……第三次修正）
它比手工摘要更准确，且与正文同源。规则：
  1) note 为空                  → 直接写题注
  2) note 已是沿革叙述（含「YYYY年…通过/公布」）→ 保持不动
  3) note 是策展说明（如「全国统一标准」）      → 说明在前，题注接在后面
输出统一为纯文本，不加「沿革：」前缀，避免与 YAML 字段名重复。

用法：python3 tools/enrich_note.py [--force]
"""

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fetch_docs as F  # noqa: E402

DATA = os.path.join(F.BASE, "data")
MAXLEN = 320
HIST = re.compile(r"\d{4}年.{0,40}?(通过|公布|发布|批准|修正|修订)")


def caption(text):
    """取正文里第一个题注段落（形如「（YYYY年……通过」），容忍硬折行"""
    lines = [x.strip() for x in text.split("\n") if x.strip()]
    for i, s in enumerate(lines[:80]):
        if not re.match(r"^[（(]\s*\d{4}年", s):
            continue
        # 老 .doc 的题注常被硬折行切断，「通过」可能在下一行，先接起来再判
        buf, j = s, i
        while "）" not in buf and ")" not in buf and j + 1 < len(lines) and j - i < 8:
            j += 1
            buf += lines[j]
        if not re.search(r"(通过|公布|发布|批准)", buf):
            continue
        buf = buf.strip("（）()").replace("\u3000", " ")
        buf = re.sub(r"\s+", " ", buf)
        return buf[:MAXLEN] + ("…" if len(buf) > MAXLEN else "")
    return ""


def split_note(old):
    """拆出「策展说明」与「已有的沿革段」，去掉历史遗留的重复前缀"""
    remark, hist = [], []
    for part in re.split(r"[｜|；;]", old or ""):
        p = part.strip()
        if not p:
            continue
        p = re.sub(r"^沿革[:：]\s*", "", p)
        (hist if HIST.search(p) else remark).append(p)
    return "；".join(remark), "；".join(hist)


def main():
    force = "--force" in sys.argv
    items = json.load(open(os.path.join(DATA, "items.json"), encoding="utf-8"))
    n = 0
    for it in items:
        fn = it.get("file")
        if not fn:
            continue
        p = os.path.join(F.BASE, fn)
        if not os.path.exists(p):
            continue
        cap = caption(open(p, encoding="utf-8").read())
        if not cap:
            continue
        remark, hist = split_note(it.get("note"))
        if hist and not force:
            new = (remark + "；" if remark else "") + hist
        else:
            new = (remark + "；" if remark else "") + cap
        if new == (it.get("note") or "").strip():
            continue
        it["note"] = new
        n += 1
        t = open(p, encoding="utf-8").read()
        t2 = re.sub(r"^沿革: .*$", "沿革: " + new.replace("\n", " "), t, count=1, flags=re.M)
        if t2 != t:
            open(p, "w", encoding="utf-8").write(t2)

    json.dump(items, open(os.path.join(DATA, "items.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("整理沿革 %d 条" % n)


if __name__ == "__main__":
    main()
