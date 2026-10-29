#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""诊断：统计正文里的网站噪声（页脚、责任编辑、友情链接等）。

只读，不改文件。用法：python3 tools/scan_noise.py [--list]
"""

import json
import os
import re
import sys
from collections import Counter, defaultdict

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PATS = {
    "责任编辑": r"责任编辑",
    "编辑署名": r"(?:编辑|作者|撰稿|校对)[:：]\s*\S{2,8}",
    "来源栏": r"(?:来源|信息来源)[:：]\s*\S{2,20}",
    "友情链接": r"友情链接|相关链接|网站地图|联系我们|关于我们|网站声明",
    "打印分享": r"扫一扫|打印本页|关闭窗口|分享到|字号[:：]|【打印】|【关闭】",
    "ICP版权": r"ICP备|版权所有|公网安备|主办单位|承办单位|网站标识码",
    "联系方式": r"邮编[:：]\s*\d{6}|电话[:：]|传真[:：]|地址[:：].{0,25}(路|街|号)",
    "导航面包屑": r"当前位置|您的位置|首页\s*>|首页\|简\|繁",
    "上下篇": r"^上一篇|^下一篇|上一篇[:：]|下一篇[:：]",
    "访问量": r"阅读量|点击量|访问次数|浏览次数|访问量",
    "大中小": r"【大\s*中\s*小】|大\s*中\s*小",
    "责任编辑英文": r"Editor|editing",
    "站点名": r"中国政府网|国家法律法规数据库|全国人大网|发改委网站|财政部网站",
}


def body_of(path):
    """取 YAML front matter 之后的正文（注意文末还有一条 --- 分隔线）"""
    t = open(path, encoding="utf-8").read()
    m = re.match(r"^---\n.*?\n---\n(.*)$", t, re.S)
    return m.group(1) if m else t


def main():
    items = json.load(open(os.path.join(BASE, "data", "items.json"), encoding="utf-8"))
    cnt = Counter()
    ex = defaultdict(list)
    per_file = Counter()
    for it in items:
        p = os.path.join(BASE, it["file"])
        b = body_of(p)
        for name, pat in PATS.items():
            hits = list(re.finditer(pat, b, re.M))
            if not hits:
                continue
            cnt[name] += len(hits)
            per_file[it["id"]] += len(hits)
            for m in hits[:3]:
                s, e = max(0, m.start() - 36), min(len(b), m.end() + 46)
                ex[name].append("%s …%s…" % (it["id"], b[s:e].replace("\n", "⏎")))

    out = []
    out.append("== 命中统计 ==")
    for k, v in cnt.most_common():
        out.append("%-10s %5d" % (k, v))
    out.append("")
    out.append("== 样例 ==")
    for k in cnt:
        out.append("[%s]" % k)
        for s in ex[k][:5]:
            out.append("   " + s[:190])
    out.append("")
    out.append("== 污染最重的条目 ==")
    for k, v in per_file.most_common(15):
        out.append("%-5s %3d 处" % (k, v))

    txt = "\n".join(out)
    open(os.path.join(BASE, "data", "noise-report.txt"), "w", encoding="utf-8").write(txt)
    print(txt[:6000])


if __name__ == "__main__":
    main()
