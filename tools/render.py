#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""索引生成：catalog.csv + INDEX.md + index.html（单文件离线检索页）"""

import csv
import html
import json
import os
import re
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, "data")
LEVEL_DIR = {
    "法律": "01-法律", "行政法规": "02-行政法规", "部门规章": "03-部门规章",
    "地方性法规": "04-地方性法规", "规范性文件": "05-规范性文件", "司法解释": "06-司法解释",
}
LEVEL_DESC = {
    "法律": "全国人大及其常委会制定，效力仅次于宪法",
    "行政法规": "国务院制定，效力低于法律、高于地方性法规和规章",
    "部门规章": "国务院组成部门及直属机构制定，效力低于行政法规",
    "地方性法规": "省级及设区的市人大及其常委会制定，在本行政区域内有效",
    "规范性文件": "行政机关制定的非立法性文件，不得与法律法规规章抵触",
    "司法解释": "最高人民法院对法律适用作出的解释，具有普遍约束力",
}


def load():
    return json.load(open(os.path.join(DATA, "items.json"), encoding="utf-8"))


def body_text(it):
    p = os.path.join(BASE, it.get("file", ""))
    if not it.get("file") or not os.path.exists(p):
        return ""
    t = open(p, encoding="utf-8").read()
    t = re.sub(r"(?s)^---.*?---", "", t)
    return t.strip()


def write_csv(items):
    cols = ["编号", "效力层级", "分类", "适用地区", "主题标签", "名称", "文号", "制定机关",
            "公布日期", "施行日期", "效力状态", "沿革", "本地文件", "官方来源"]
    p = os.path.join(BASE, "catalog.csv")
    with open(p, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for it in items:
            w.writerow([it["id"], it["level"], it["category"],
                        it.get("region") or "全国",
                        " / ".join(it.get("tags") or []),
                        it["title"], it.get("doc_no") or "",
                        it.get("issuer_norm") or it.get("issuer") or "",
                        it.get("pub") or "", it.get("eff") or "", it.get("status") or "",
                        it.get("note") or "", it.get("file") or "",
                        it.get("src_url") or it.get("source") or ""])
    return p


def write_index_md(items):
    order = list(LEVEL_DIR)
    L = ["# 招标投标法律法规资料库 · 总索引", "",
         "> 整理日期：%s　|　共 %d 件　|　全文 %d 件" % (
             time.strftime("%Y-%m-%d"), len(items),
             sum(1 for i in items if i.get("file"))), "",
         "## 效力层级", "",
         "| 层级 | 目录 | 制定主体与效力 | 件数 |", "| --- | --- | --- | --- |"]
    for lv in order:
        n = sum(1 for i in items if i["level"] == lv)
        L.append("| %s | `%s/` | %s | %d |" % (lv, LEVEL_DIR[lv], LEVEL_DESC[lv], n))
    L += ["", "## 分类目录", ""]
    for lv in order:
        sub = [i for i in items if i["level"] == lv]
        if not sub:
            continue
        L += ["### %s（%s）" % (lv, LEVEL_DIR[lv]), ""]
        cats = {}
        for i in sub:
            cats.setdefault(i["category"], []).append(i)
        for cat in sorted(cats, key=lambda c: (-len(cats[c]), c)):
            L += ["**%s**" % cat, ""]
            for i in cats[cat]:
                f = i.get("file")
                name = "[%s](%s)" % (i["title"], f.replace(" ", "%20")) if f else i["title"]
                meta = "，".join(x for x in [
                    i.get("doc_no") or "", "公布 " + i["pub"] if i.get("pub") else "",
                    "施行 " + i["eff"] if i.get("eff") else ""] if x)
                if not meta:      # 无公布/施行日期时，用题注沿革兜底
                    meta = (i.get("note") or "—")[:60]
                L.append("- %s　`%s`　%s" % (name, i["id"], meta))
            L.append("")
    L += ["---", "", "## 按适用地区", "",
          "> 法律适用讲属地：本地规定与全国性规定并行。选地区时两类都适用。", ""]
    regs = {}
    for i in items:
        regs.setdefault(i.get("region") or "全国", []).append(i)
    nat = regs.pop("全国", [])
    L += ["### 全国（%d 件）" % len(nat), ""]
    L += ["- %s　`%s`" % (i["title"], i["id"]) for i in nat]
    L.append("")
    for rl in ("省级", "市级", "州级"):
        sub = {k: v for k, v in regs.items() if v[0].get("region_level") == rl}
        if not sub:
            continue
        L += ["### %s（%d 个地区）" % (rl, len(sub)), ""]
        for k in sorted(sub, key=lambda x: (-len(sub[x]), x)):
            v = sub[k]
            L.append("- **%s**（%d 件）：%s" % (
                k, len(v), "、".join(i["title"] for i in v)))
        L.append("")

    L += ["---", "",
          "## 使用说明", "",
          "- 每份文件顶部为元数据（YAML front matter），含文号、公布/施行日期、效力状态、沿革与原文地址。",
          "- 未取得全文的条目，`官方来源` 列给出国家法律法规数据库的原文页链接，可在线查看。",
          "- 更新：`python3 tools/refresh.py`（重新取元数据 + 抓取缺失全文 + 重建索引）。", ""]
    p = os.path.join(BASE, "INDEX.md")
    open(p, "w", encoding="utf-8").write("\n".join(L))
    return p


TMPL_PATH = os.path.join(BASE, "tools", "index_template.html")
PLACEHOLDER = "\u0000SCRIPT\u0000"


def load_body(it):
    p = os.path.join(BASE, it.get("file", ""))
    if not it.get("file") or not os.path.exists(p):
        return ""
    t = open(p, encoding="utf-8").read()
    t = re.sub(r"(?s)^---.*?---\s*", "", t)
    return t.strip("\n")


def write_html(items):
    """单文件离线检索页：元数据 JSON + 全文 blob 分两个 script 标签注入。

    blob 走 text/plain 而不是 JSON，浏览器取 textContent 即可，不必解析 2MB 的
    JSON 字符串——这是首屏加载最大的一笔开销。
    """
    idx = json.load(open(os.path.join(DATA, "search-index.json"), encoding="utf-8"))
    tmpl = open(TMPL_PATH, encoding="utf-8").read()

    parts = []
    for it in items:
        if it.get("file"):
            parts.append(load_body(it))
    blob = "\n".join(parts)          # 与 build_index 的 +1 分隔符对应
    blob = blob.replace("</script", PLACEHOLDER)
    meta = json.dumps(idx, ensure_ascii=False, separators=(",", ":"))
    meta = meta.replace("</", PLACEHOLDER)

    arts = sum(d["na"] for d in idx["docs"])
    page = (tmpl.replace("__INDEX__", meta)
                .replace("__BLOB__", blob)
                .replace("__COUNT__", str(len(idx["docs"])))
                .replace("__FULL__", str(len(idx["docs"])))
                .replace("__CHARS__", "%.1f" % (idx["chars"] / 10000))
                .replace("__ARTS__", str(arts))
                .replace("__DATE__", idx["built"][:10]))
    p = os.path.join(BASE, "index.html")
    open(p, "w", encoding="utf-8").write(page)
    return p


if __name__ == "__main__":
    its = load()
    print(write_csv(its))
    print(write_index_md(its))
    p = write_html(its)
    print(p, "%.1f MB" % (os.path.getsize(p) / 1048576))
