#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""修复硬折行：把「每 20 字断一行」的正文重新接成整段

为什么必须修：docx/网页转换时保留了原始折行，出现过
    「维护公平竞\\n\\n争、诚实守信」
检索「公平竞争」就永远搜不到——条文在库里，但查不出来，这比缺文更糟。

安全边界（这是本脚本唯一的硬约束）：
    修复前后，去掉所有空白字符后的字符串必须**完全相等**
也就是说本脚本只移动空白，不增删改任何一个字。任何一篇不满足即跳过并报错。

判断折行的依据（不靠行宽，靠标点）：
    上一行结尾不是句末标点（。！？；：…）→ 说明句子没说完，下一行是续行
    下一行以章节/条款编号、列表符、表格符、编码开头 → 视为新块，不接
"""

import json
import re
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, "data")

CN = "一二三四五六七八九十百零〇两"
RE_NEW_BLOCK = [
    re.compile(r"^#{1,6}\s"),                                  # Markdown 标题
    re.compile(r"^第\s*[%s\d]+\s*[条章节编]" % CN),             # 条/章/节/编
    re.compile(r"^[%s]{1,3}、" % CN),                           # 一、
    re.compile(r"^（[%s\d]{1,3}）" % CN),                        # （一）
    re.compile(r"^附件|^附表|^附：|^附\s*\d"),
    re.compile(r"^[-*+]\s"),                                    # 列表
    re.compile(r"^\|"),                                         # 表格
    re.compile(r"^>"),                                          # 引用/落款模板
    re.compile(r"^[A-Z]{1,3}\d{2,6}"),                          # 标准编码 A0101
    re.compile(r"^[-=]{3,}$"),
]
TERMINAL = "。！？；：…!?;:"
TAIL_OK = "。！？；：…)）》」』”\"'】"
RE_CODE = re.compile(r"^[A-Z]{1,3}\d{2,6}\b")


def table_like(body):
    """编码表/清单类文件：合并行会破坏表结构，整篇跳过。
    判据是「大量行以标准编码开头」——评标专家分类标准有 2700 行这种。"""
    lines = [l.strip() for l in body.split("\n") if l.strip()]
    if not lines:
        return False
    code = sum(1 for l in lines if RE_CODE.match(l))
    return code >= 20 and code / len(lines) > 0.2


def split_fm(path):
    s = open(path, encoding="utf-8").read()
    m = re.match(r"(?s)^(---\n.*?\n---\n)(.*)$", s)
    if m:
        return m.group(1), m.group(2)
    return "", s


def rebuild(body):
    """把 body 的硬折行接回整段，返回新 body

    关键点：硬折行的碎片之间**常插着空行**（docx 每段都当新段落导出），
    所以空行不能一律当作段落边界——只有当上一句已经以句末标点收尾时才算。
    """
    lines = [l.rstrip("\n") for l in body.split("\n")]
    out, cur = [], ""

    def flush():
        nonlocal cur
        if cur.strip():
            out.append(cur.strip())
            out.append("")          # 段落之间留一个空行
        cur = ""

    def join(cur, line):
        """续行拼接。条号单独成行时补一个空格（「第一条 为鼓励…」），
        章标题与其标题词（「## 第一章」+「总则」）之间也补空格，
        其余情况中文直接相接，不补空格。"""
        bare = cur.strip()
        if re.fullmatch(r"第\s*[%s\d]+\s*[条章节编]" % CN, bare):
            return cur + " " + line
        if bare.startswith("#"):
            if len(line) <= 8 and not bare.endswith(" "):
                return cur + " " + line
            return None            # 标题后接长文本：标题独立成行
        return cur + line

    for raw in lines:
        line = raw.strip()
        if not line:
            if cur.endswith(tuple(TERMINAL)):
                flush()
            continue
        if any(rx.match(line) for rx in RE_NEW_BLOCK):
            flush()
            cur = line
            continue
        if not cur:
            cur = line
        elif cur.endswith(tuple(TERMINAL)):
            flush()
            cur = line
        else:
            merged = join(cur, line)
            if merged is None:
                flush()
                cur = line
            else:
                cur = merged
    flush()
    txt = "\n".join(out).strip("\n")
    txt = re.sub(r"\n{3,}", "\n\n", txt)
    return txt + "\n"


# ------------------------------------------------------------------ 检测


def vocab():
    idx = json.load(open(os.path.join(DATA, "search-index.json"), encoding="utf-8"))
    words = {w for g in idx.get("syn", []) for w in g}
    words |= set("""公平竞争 招标投标 投标保证金 履约保证金 评标委员会 招标文件 投标文件
中标通知书 政府采购 工程建设 施工许可 工程款 竣工验收 行政处罚 监督管理 合同履行
资格审查 联合体 特许经营 安全生产 工程质量 建筑市场 公共资源 电子招标 招标代理
评标专家 投标人 招标人 异议 投诉 行政复议 行政诉讼 信用信息 失信 惩戒 营商环境
统一大市场 农民工工资 分包 转包 中标 中标人 评标 中标结果 招标公告 资格预审
工程造价 造价 供应商 采购人 评审 资质 勘察设计 施工图 监理 总承包 履约 验收""".split())
    return sorted(words, key=len, reverse=True)


def broken_terms(body, words):
    flat = body.replace("\n", "")
    return [w for w in words if w not in body and w in flat]


def main():
    apply = "--apply" in sys.argv
    words = vocab()
    its = json.load(open(os.path.join(DATA, "items.json"), encoding="utf-8"))
    hit = 0
    for it in its:
        if not it.get("file"):
            continue
        p = os.path.join(BASE, it["file"])
        if not os.path.exists(p):
            continue
        fm, body = split_fm(p)
        bad = broken_terms(body, words)
        if not bad:
            continue
        if table_like(body):
            print("· 表格/编码清单，跳过：%s" % it["title"][:40])
            continue
        hit += 1
        new = rebuild(body)
        # 硬约束：去掉空白后必须完全一致
        if re.sub(r"\s+", "", body) != re.sub(r"\s+", "", new):
            print("✗ 内容不一致，跳过：%s" % it["title"][:40])
            continue
        if new.count("\n") >= body.count("\n"):
            print("· 无改善：%s" % it["title"][:40])
            continue
        print("%s %-38s 折断词 %s" % ("修" if apply else "待修", it["title"][:36],
                                      "/".join(bad[:4])))
        if apply:
            open(p, "w", encoding="utf-8").write(fm + new)
    print("\n共 %d 篇需要修折行%s" % (hit, "（已写入）" if apply else "（预演，加 --apply 落盘）"))


if __name__ == "__main__":
    main()
