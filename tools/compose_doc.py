#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""正文在网页、标准本体在附件的规范性文件：合成一份完整 Markdown。

配置写在 data/attachments.json：
{
 "E09": {
   "page": "https://www.gov.cn/...",
   "container": "id=\"UCAP-CONTENT\"",       # 正文容器起始标记（可选）
   "stop": "<div class=\"footer",              # 正文结束标记（可选）
   "attachments": [{"title": "附件1 ……", "url": "https://...pdf"}]
 }
}

用法：python3 tools/compose_doc.py E09 [E10 ...]
"""

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fetch_docs as F  # noqa: E402

DATA = os.path.join(F.BASE, "data")
CONF = os.path.join(DATA, "attachments.json")


def dedupe(lines):
    """页面常见「电脑版 + 手机版」双容器，段落重复两遍，按首次出现去重"""
    out, seen = [], set()
    for x in lines:
        k = re.sub(r"\s", "", x)
        if k in seen:
            continue
        seen.add(k)
        out.append(x)
    return out


def split_lead(line):
    """把「通知标题+文号+主送机关」粘成的一行拆开"""
    line = re.sub(r'^id="[^"]*">', "", line)
    line = re.sub(r"(通知|意见|办法|规定)(发改|财|国办|工信|住建)", r"\1\n\2", line, count=1)
    line = re.sub(r"(\〔\d{4}〕\d+号)", r"\1\n", line, count=1)
    return [x for x in line.split("\n") if x.strip()]


def main():
    ids = sys.argv[1:]
    conf = json.load(open(CONF, encoding="utf-8"))
    items = json.load(open(os.path.join(DATA, "items.json"), encoding="utf-8"))
    by_id = {x["id"]: x for x in items}

    for i in (ids or list(conf)):
        if i not in conf:
            print("无配置：%s" % i)
            continue
        it = by_id.get(i)
        if not it:
            print("无条目：%s" % i)
            continue
        c = conf[i]
        h, _ = F.fetch(c["page"], referer="https://www.gov.cn/")
        if not h:
            print("MISS %s 页面抓取失败" % i)
            continue
        seg = h
        if c.get("container") and c["container"] in h:
            seg = h[h.find(c["container"]):]
        if c.get("stop") and c["stop"] in seg:
            seg = seg[:seg.find(c["stop"])]
        body = dedupe(F.clean_text(seg))
        if body:
            body = split_lead(body[0]) + body[1:]

        # render_md 负责 YAML 头与章标题，先拼出「网页正文」部分
        md = F.render_md(it, body, c["page"])
        md = md.replace("> 本文由公开官方渠道抓取整理", "%%TAIL%%")

        # 附件：PDF 表格类文本按原顺序保留，加二级标题分隔
        for att in c.get("attachments", []):
            lines = F.pdf_text(att["url"])
            if not lines:
                print("      附件无文本：%s" % att["url"])
                continue
            md = md.rstrip() + "\n\n## %s\n\n" % att["title"]
            md += "\n\n".join(lines) + "\n"
            print("      附件 %s：%d 行" % (att["title"], len(lines)))

        tail = ("> 本文由公开官方渠道抓取整理，仅供检索参考；"
                "引用请以官方发布文本为准。原文地址：%s" % c["page"])
        md = md.replace("%%TAIL%%", tail)
        if "%%TAIL%%" in md:                      # render_md 结构变动时兜底
            md = md.rstrip() + "\n\n---\n\n" + tail + "\n"

        fn = os.path.join(F.BASE, F.LEVEL_DIR[it["level"]],
                          F.safe_name(it["title"], it.get("pub") or ""))
        os.makedirs(os.path.dirname(fn), exist_ok=True)
        open(fn, "w", encoding="utf-8").write(md)
        it["file"] = os.path.relpath(fn, F.BASE)
        it["src_url"] = c["page"]
        it["chars"] = len(re.sub(r"\s", "", md))
        by_id[i] = it
        print("OK   %-5s %-24s %6d 字  %s" %
              (i, it["title"][:24], it["chars"], os.path.basename(fn)))

    json.dump(list(by_id.values()),
              open(os.path.join(DATA, "items.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
