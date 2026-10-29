#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""原文地址发现：对缺少全文的条目，用检索逐个找官方页面并验证正文。

用法：
  python3 tools/discover.py            # 处理所有缺全文的条目
  python3 tools/discover.py D01 D07    # 只处理指定编号
  python3 tools/discover.py --title "天津市招标投标条例"

验证通过后把地址写入 data/manual_urls.json，并直接落盘一份 Markdown。
"""

import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fetch_docs as F  # noqa: E402

BASE = F.BASE
DATA = os.path.join(BASE, "data")
MANUAL = os.path.join(DATA, "manual_urls.json")


def load_items():
    return json.load(open(os.path.join(DATA, "items.json"), encoding="utf-8"))


def save_manual(title, url):
    d = {}
    if os.path.exists(MANUAL):
        d = json.load(open(MANUAL, encoding="utf-8"))
    d[title] = url
    json.dump(d, open(MANUAL, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def has_text(it):
    f = it.get("file")
    return bool(f) and os.path.exists(os.path.join(BASE, f))


def candidates(it):
    """按优先级产出候选地址：人工指定 → 检索结果"""
    title = it["title"]
    seen = set()
    if it.get("url"):
        seen.add(it["url"])
        yield it["url"]
    # 省/市人大与政府站点优先
    qs = [
        '"%s" 全文' % title,
        "%s 全文 人民代表大会常务委员会" % title,
        "%s site:gov.cn" % title,
        title,
    ]
    for q in qs:
        try:
            urls = F.bing_urls(q)
        except Exception:
            urls = []
        for u in urls:
            if not F.good_url(u) or u in seen:
                continue
            seen.add(u)
            yield u
        if len(seen) >= 10:
            break
        time.sleep(3)


def accept(it, u):
    """抓取并判定是否采用；规范性文件篇幅阈值放宽"""
    try:
        if u.lower().endswith(".pdf"):
            lines = F.pdf_text(u)
        else:
            h, _ = F.fetch(u)
            if not h:
                return None
            lines = F.extract_article(h, it["title"])
            if sum(len(x) for x in lines) < 2500:
                for pu in F.find_pdfs(h, u)[:2]:
                    pl = F.pdf_text(pu)
                    if not pl or sum(len(x) for x in pl) <= sum(len(x) for x in lines):
                        continue
                    if F.score(pl, it["title"])[0]:
                        u, lines = pu, pl
                    break
    except Exception:
        return None
    hit, ln, arts = F.score(lines, it["title"])
    need = 500 if it["level"] == "规范性文件" else 1200
    if hit and ln >= need:
        return (u, lines)
    return None


def try_item(it, verbose=True):
    title = it["title"]
    tried = 0
    for u in candidates(it):
        tried += 1
        got = accept(it, u)
        if got:
            u2, lines = got
            fn = os.path.join(BASE, F.LEVEL_DIR[it["level"]],
                              F.safe_name(title, it.get("pub") or ""))
            open(fn, "w", encoding="utf-8").write(F.render_md(it, lines, u2))
            it["file"] = os.path.relpath(fn, BASE)
            it["src_url"] = u2
            it["chars"] = sum(len(x) for x in lines)
            save_manual(title, u2)
            print("OK   %-5s %-34s %s" % (it["id"], title[:34], u2[:60]), flush=True)
            return True
        if tried >= 8:
            break
        time.sleep(1)
    print("MISS %-5s %-34s 试了 %d 个地址" % (it["id"], title[:34], tried), flush=True)
    return False


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    items = load_items()
    if "--title" in sys.argv:
        t = sys.argv[sys.argv.index("--title") + 1]
        items = [x for x in items if x["title"] == t]
    elif args:
        items = [x for x in items if x["id"] in args]
    else:
        items = [x for x in items if not has_text(x)]

    ok = 0
    for n, it in enumerate(items, 1):
        print("[%d/%d] %s" % (n, len(items), it["title"]), flush=True)
        if try_item(it):
            ok += 1
            time.sleep(2)
        else:
            time.sleep(6)

    # 以 id 为键合并回完整清单，绝不写回子集
    full = {x["id"]: x for x in load_items()}
    for it in items:
        full[it["id"]] = it
    json.dump(list(full.values()),
              open(os.path.join(DATA, "items.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("完成：成功 %d / %d" % (ok, len(items)))


if __name__ == "__main__":
    main()
