#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MCP 服务：把本地法规库暴露成 AI 可调用的检索工具

走 stdio + 换行分隔 JSON-RPC（MCP 标准传输），只依赖 Python 标准库。
数据源是 build_index.py 产出的两份文件，不另建索引：

  data/search-index.json   元数据 + 单元偏移 + 条号表 + 同义词
  data/fulltext.txt        2.2MB 全文 blob（偏移与上面严格对应）

暴露四个工具：
  search_law      关键词/条文检索，返回条文级命中（带条号与出处）
  get_article     取某一篇的第 X 条原文
  get_document    取整篇（分页，避免一次灌爆上下文）
  list_documents  按层级/地区/年份/标题列出条目

设计要点：
  1) 检索在本地全部完成，只把命中的几条条文交给模型——2.2MB 全文永远不进上下文
  2) 每条结果都带「《法规名》第X条」的出处，模型引用时可核对，减少编造
  3) 打分口径与 index.html 一致（标题完全匹配 > 别名 > 前缀 > 包含 > 正文 idf·tf），
     否则网页里搜到的和 AI 搜到的会不一样
"""

import bisect
import json
import math
import os
import re
import sys
import unicodedata

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, "data")
PROTOCOL = "2024-11-05"
SERVER = {"name": "legal-library", "version": "1.0.0"}

CN = "一二三四五六七八九十百零〇两"
CN_NUM = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
          "六": 6, "七": 7, "八": 8, "九": 9}
RE_ART_IN_QUERY = re.compile(r"第\s*([%s\d]+)\s*条" % CN)
RE_ART_LABEL = re.compile(r"第\s*([%s\d]+)\s*条" % CN)


def cn2int(s):
    s = (s or "").strip()
    if not s:
        return None
    if s.isdigit():
        return int(s)
    total = section = cur = 0
    for ch in s:
        if ch == "十":
            section += (cur or 1) * 10
            cur = 0
        elif ch == "百":
            section += (cur or 1) * 100
            cur = 0
        elif ch in CN_NUM:
            cur = CN_NUM[ch]
        else:
            return None
    return total + section + cur


def squash(s):
    """去掉书名号、空白与「中华人民共和国」前缀，用于标题精确比对"""
    s = unicodedata.normalize("NFKC", s or "")
    s = re.sub(r"[《》〈〉\s]", "", s)
    if s.startswith("中华人民共和国"):
        s = s[len("中华人民共和国"):]
    return s


def clean_md(s):
    """去掉 Markdown 标记，条文原样交给模型"""
    s = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", s)
    s = re.sub(r"(?m)^\s*[-*+]\s+", "", s)
    return s.strip()


# --------------------------------------------------------------- 数据加载


class Library:
    def __init__(self):
        self.idx = json.load(open(os.path.join(DATA, "search-index.json"), encoding="utf-8"))
        self.blob = open(os.path.join(DATA, "fulltext.txt"), encoding="utf-8").read()
        self.docs = self.idx["docs"]
        self.units = self.idx["units"]
        self.arts = self.idx["arts"]
        self.syn = self.idx.get("syn", [])
        self.starts = [d["s"] for d in self.docs]
        self.N = len(self.docs)
        self.by_id = {}
        for d in self.docs:
            if d["id"]:
                self.by_id[d["id"].upper()] = d
        self.lv_count = {}
        for d in self.docs:
            self.lv_count[d["lv"]] = self.lv_count.get(d["lv"], 0) + 1

    # ------------------------------------------------------------ 基础工具

    def doc_at(self, pos):
        i = bisect.bisect_right(self.starts, pos) - 1
        return i if 0 <= i < self.N else -1

    def unit_of(self, pos, di):
        """偏移 → 所属单元序号（在本文单元区间内二分）"""
        d = self.docs[di]
        lo, hi = d["u0"], d["u1"]
        while lo < hi:
            mid = (lo + hi) // 2
            if self.units[mid][0] <= pos:
                lo = mid + 1
            else:
                hi = mid
        return max(d["u0"], lo - 1)

    def unit_text(self, ui, limit=None):
        start = self.units[ui][0]
        if ui + 1 < len(self.units):
            end = self.units[ui + 1][0]
        else:
            end = len(self.blob)
        t = clean_md(self.blob[start:end]).strip()
        if limit and len(t) > limit:
            t = t[:limit].rstrip() + "…"
        return t

    def cite(self, di, ui=None):
        d = self.docs[di]
        if ui is None:
            return "《%s》" % d["t"]
        label = self.units[ui][2] if self.units[ui][1] == 1 else ""
        return "《%s》%s" % (d["t"], label)

    # ------------------------------------------------------------ 同义扩展

    def expand(self, term):
        out = [term]
        for grp in self.syn:
            hit = False
            for x in grp:
                if x == term:
                    hit = True
                    break
                # 只认「查询词是术语前缀且不短于 3 字」，避免「保证金」把
                # 「投标保证金」以外的上位概念全部拉进来
                if len(term) >= 3 and x.startswith(term):
                    hit = True
                    break
            if hit:
                for x in grp:
                    if x not in out:
                        out.append(x)
                break
        return out

    # ------------------------------------------------------------ 全文扫描

    def scan(self, term):
        """返回 {文档序号: 命中次数}"""
        res = {}
        p = self.blob.find(term)
        step = max(1, len(term))
        while p >= 0:
            di = self.doc_at(p)
            if di >= 0:
                res[di] = res.get(di, 0) + 1
            p = self.blob.find(term, p + step)
        return res

    # ------------------------------------------------------------ 解析查询

    @staticmethod
    def parse(q):
        must, exclude = [], []
        for m in re.finditer(r'"([^"]+)"|(\S+)', q or ""):
            phrase, word = m.group(1), m.group(2)
            if phrase:
                term = re.sub(r"\s+", "", phrase)
                must.append(term)
            elif word:
                if word.startswith("-") and len(word) > 1:
                    exclude.append(word[1:])
                else:
                    must.append(word)
        return must, exclude

    # ------------------------------------------------------------ 检索主逻辑

    def search(self, query, region=None, level=None, limit=8, per_doc=2):
        must, exclude = self.parse(query)
        art_no = None
        clean_terms = []
        for t in must:
            m = RE_ART_IN_QUERY.fullmatch(t)
            if m:
                art_no = cn2int(m.group(1))
                continue
            clean_terms.append(t)
        if not clean_terms and art_no is None:
            return {"query": query, "total": 0, "hits": [],
                    "hint": "请给出关键词，例如「投标保证金」「串通投标 认定」"}

        # 1) 词频表：每个词在每个文档里出现几次（分原词 / 含同义两套）
        tf, exact_tf, df = {}, {}, {}
        for w in clean_terms:
            merged = {}
            for alt in self.expand(w):
                if not alt:
                    continue
                for di, n in self.scan(alt).items():
                    if n > merged.get(di, 0):
                        merged[di] = n
            tf[w] = merged
            exact_tf[w] = self.scan(w)
            df[w] = len(merged)

        # 2) 候选：至少命中一个必含词的文档
        cands = set()
        for w in clean_terms:
            cands |= set(tf[w].keys())
        if art_no is not None and not clean_terms:
            cands = set(range(self.N))

        # 3) 排除词
        for w in exclude:
            for alt in self.expand(w):
                for di in self.scan(alt):
                    cands.discard(di)

        # 4) 元数据过滤
        if level:
            lvs = [level] if isinstance(level, str) else list(level)
            cands = {i for i in cands if self.docs[i]["lv"] in lvs}
        if region:
            cands = {i for i in cands if self.docs[i]["rg"] in (region, "全国")}

        # 5) 打分
        snip_terms = []
        for w in clean_terms:
            for alt in self.expand(w):
                if alt not in snip_terms:
                    snip_terms.append(alt)
        scored = []
        for di in cands:
            d = self.docs[di]
            s = 0.0
            hit_terms = 0
            for w in clean_terms:
                n_any = tf[w].get(di, 0)
                n_exact = exact_tf[w].get(di, 0)
                if n_any:
                    hit_terms += 1
                key = squash(w)
                tkey = squash(d["t"])
                if key == tkey:
                    s += 26
                elif any(key == squash(a) for a in d["al"]):
                    s += 23
                elif tkey.startswith(key):
                    s += 17
                elif any(squash(a).startswith(key) for a in d["al"]):
                    s += 14
                elif key in tkey:
                    s += 9
                if key and (key in squash(d["dn"]) or key in squash(d["is"]) or
                            any(key in tg for tg in d["tg"])):
                    s += 5
                if n_any:
                    idf = math.log(1 + self.N / max(1, df[w]))
                    # 原词命中给足权重，靠同义扩展命中的减半——否则「投标保证金」
                    # 会把只写了「保证金」的《质量保证金管理办法》顶上来
                    if n_exact:
                        s += (1 + math.log(n_exact)) * idf * 3.0
                    else:
                        s += 0.5 * (1 + math.log(n_any)) * idf * 3.0
            # 必含词覆盖不全的降权（法律检索宁可多召回，不直接淘汰）
            if len(clean_terms) > 1:
                s *= 0.45 + 0.55 * (hit_terms / len(clean_terms))
            # 层级只做微调，不掩盖相关度
            s *= {"法律": 1.20, "行政法规": 1.14, "司法解释": 1.10, "部门规章": 1.06,
                  "地方性法规": 1.00, "规范性文件": 0.96}.get(d["lv"], 1.0)
            if d.get("es") == "待施行":
                s *= 0.94
            if region and d["rg"] == region:
                s *= 1.35          # 属地优先：本地规定比全国规定更该先看
            if len(clean_terms) > 1:
                co = self.cooccur(di, snip_terms)
                if co > 1:
                    s += 12 * (co - 1)     # 同一条里覆盖多个查询词，强相关
            if s > 0:
                scored.append((s, di))

        scored.sort(key=lambda x: (-x[0], x[1]))

        # 6) 组装：每篇取最佳的两条条文作片段
        hits = []
        for s, di in scored[:limit]:
            d = self.docs[di]
            snips = self.snippets(di, snip_terms, art_no, per_doc)
            hits.append({
                "id": d["id"],
                "title": d["t"],
                "level": d["lv"],
                "region": d["rg"],
                "doc_no": d["dn"],
                "issuer": d["is"],
                "pub": d["pb"],
                "eff": d["ef"],
                "status": d["es"],
                "score": round(s, 1),
                "articles": snips,
                "file": d["f"],
                "source": d["src"],
            })
        return {"query": query, "total": len(scored), "returned": len(hits), "hits": hits}

    def cooccur(self, di, terms):
        """本文最贴的那一条里，覆盖了几个查询词——比文档级词频强得多的相关信号。
        「投标保证金 不得超过」的正确答案是「不得超过……2%」那一条，而不是两个词
        分别出现在不同章节的文件。"""
        us = self.rank_units(di, terms, 1)
        if not us:
            return 0
        t = self.unit_text(us[0])
        return sum(1 for w in terms[:4] if w in t)

    def rank_units(self, di, terms, top=2):
        """按「条内覆盖了几个查询词 + 出现几次」给本文的条打分，取前 top 条。

        不能取「第一条命中的条」——搜「串通投标 认定」时，正文里先出现的是
        「招标代理机构资格……认定」，于是摘出完全无关的第十一条。必须挑最贴的那条。
        """
        d = self.docs[di]
        rows = []
        for ui in range(d["u0"], d["u1"]):
            if self.units[ui][1] != 1:
                continue
            t = self.unit_text(ui)
            cover = sum(1 for w in terms if w in t)
            if not cover:
                continue
            occ = sum(t.count(w) for w in terms)
            rows.append((cover, occ, ui))
        rows.sort(key=lambda x: (-x[0], -x[1]))
        return [ui for _, _, ui in rows[:top]]

    def snippets(self, di, terms, art_no, n=2):
        """取命中片段：优先「条」（按相关度挑），其次分节/段落，最后才退回文档开头。"""
        d = self.docs[di]
        out, seen = [], set()
        if art_no is not None:
            ui = self.arts[di].get(str(art_no))
            if ui is not None:
                out.append({"article": self.units[ui][2], "text": self.unit_text(ui, 700)})
                seen.add(ui)
        for ui in self.rank_units(di, terms, n):
            if len(out) >= n:
                break
            if ui in seen:
                continue
            out.append({"article": self.units[ui][2], "text": self.unit_text(ui, 700)})
            seen.add(ui)
        if len(out) < n:                        # 没有条文可定位（规范性文件常按「一、二、」分节）
            for ui in range(d["u0"], d["u1"]):
                if len(out) >= n:
                    break
                if ui in seen or self.units[ui][1] == 1:
                    continue
                t = self.unit_text(ui)
                if any(w in t for w in terms):
                    out.append({"article": "", "text": t[:700]})
                    seen.add(ui)
        if not out:
            head = clean_md(self.blob[d["s"]:d["s"] + 500]).strip()
            out.append({"article": "", "text": head})
        return out

    # ------------------------------------------------------------ 取原文

    def resolve(self, doc):
        """按编号（A01）或标题片段找文档"""
        key = (doc or "").strip()
        if key.upper() in self.by_id:
            return self.by_id[key.upper()]
        k = squash(key)
        exact = [d for d in self.docs if squash(d["t"]) == k]
        if exact:
            return exact[0]
        part = [d for d in self.docs if k and k in squash(d["t"])]
        if len(part) == 1:
            return part[0]
        if part:
            return sorted(part, key=lambda d: len(d["t"]))[0]
        return None

    def get_article(self, doc, article):
        d = self.resolve(doc)
        if not d:
            return {"error": "找不到这篇法规：%s" % doc}
        m = RE_ART_LABEL.search(str(article)) or RE_ART_LABEL.fullmatch("第%s条" % article)
        n = cn2int(m.group(1)) if m else cn2int(str(article))
        if n is None:
            return {"error": "条号无法识别：%s" % article}
        ui = self.arts[d["i"]].get(str(n))
        if ui is None:
            return {"error": "《%s》里没有第 %d 条（共 %d 条）" % (d["t"], n, d["na"]),
                    "available": "1-%d" % d["na"]}
        return {"title": d["t"], "level": d["lv"], "article": self.units[ui][2],
                "text": self.unit_text(ui), "cite": self.cite(d["i"], ui),
                "status": d["es"], "eff": d["ef"]}

    def get_document(self, doc, offset=0, max_chars=5000):
        d = self.resolve(doc)
        if not d:
            return {"error": "找不到这篇法规：%s" % doc}
        body = clean_md(self.blob[d["s"]:d["e"]])
        offset = max(0, int(offset or 0))
        chunk = body[offset:offset + int(max_chars or 5000)]
        return {"title": d["t"], "level": d["lv"], "doc_no": d["dn"], "issuer": d["is"],
                "pub": d["pb"], "eff": d["ef"], "status": d["es"], "note": d["nt"],
                "chars": len(body), "offset": offset, "returned": len(chunk),
                "has_more": offset + len(chunk) < len(body),
                "text": chunk,
                "source": d["src"], "file": d["f"]}

    def list_documents(self, level=None, region=None, year=None, keyword=None, limit=60):
        rows = self.docs
        if level:
            rows = [d for d in rows if d["lv"] == level]
        if region:
            rows = [d for d in rows if d["rg"] == region]
        if year:
            rows = [d for d in rows if str(year) in (d["pb"] or "") or str(year) in (d["ef"] or "")]
        if keyword:
            k = squash(keyword)
            rows = [d for d in rows if k in squash(d["t"]) or any(k in tg for tg in d["tg"])]
        rows = sorted(rows, key=lambda d: (d["lv"], d["rg"], d["pb"] or ""))
        regions = sorted({d["rg"] for d in self.docs})
        return {"total": len(rows), "returned": min(len(rows), limit),
                "levels": self.lv_count, "regions": regions,
                "documents": [{"id": d["id"], "title": d["t"], "level": d["lv"],
                               "region": d["rg"], "pub": d["pb"], "eff": d["ef"],
                               "status": d["es"]} for d in rows[:limit]]}


# --------------------------------------------------------------- 工具定义

TOOLS = [
    {
        "name": "search_law",
        "description": (
            "在本地招标投标法律法规库（414 件、14307 条，含法律/行政法规/部门规章/"
            "地方性法规/规范性文件/司法解释）中检索。返回条级命中：法规名、条号、条文原文、"
            "效力层级、适用地区、公布与施行日期。回答招投标合规问题前应先调用本工具取证，"
            "不要凭记忆作答。query 用关键词，不要用问句。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string",
                          "description": "关键词，空格分隔为 AND；支持 \"完整短语\"、-排除词、第36条"},
                "region": {"type": "string",
                           "description": "适用地区（如 安徽、合肥、全国），选后本地规定优先且仍包含全国规定"},
                "level": {"type": "string",
                          "description": "效力层级：法律/行政法规/部门规章/地方性法规/规范性文件/司法解释"},
                "limit": {"type": "integer", "description": "返回篇数，默认 8，最多 20"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_article",
        "description": "精确取某部法规的第 X 条原文。doc 可传编号（如 A01）或标题（如「招标投标法实施条例」）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "doc": {"type": "string", "description": "法规编号或标题"},
                "article": {"type": "string", "description": "条号，36 或 第三十六条 均可"},
            },
            "required": ["doc", "article"],
        },
    },
    {
        "name": "get_document",
        "description": "取整篇法规正文（分页返回，默认 5000 字）。用于通读某部规定，或用 offset 接续取后续部分。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "doc": {"type": "string", "description": "法规编号或标题"},
                "offset": {"type": "integer", "description": "起始字符偏移，默认 0"},
                "max_chars": {"type": "integer", "description": "本次返回字数，默认 5000"},
            },
            "required": ["doc"],
        },
    },
    {
        "name": "list_documents",
        "description": "列出库内法规条目（可按效力层级、地区、年份、标题关键词过滤），用于「有哪些规定」类问题或确认库里有没有某部法规。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "level": {"type": "string", "description": "效力层级"},
                "region": {"type": "string", "description": "适用地区"},
                "year": {"type": "string", "description": "年份，如 2024"},
                "keyword": {"type": "string", "description": "标题或主题关键词"},
                "limit": {"type": "integer", "description": "返回条数，默认 60"},
            },
        },
    },
]


# --------------------------------------------------------------- MCP 传输


def call_tool(lib, name, args):
    if name == "search_law":
        limit = min(int(args.get("limit") or 8), 20)
        return lib.search(args.get("query", ""), args.get("region") or None,
                          args.get("level") or None, limit)
    if name == "get_article":
        return lib.get_article(args.get("doc", ""), args.get("article", ""))
    if name == "get_document":
        return lib.get_document(args.get("doc", ""), args.get("offset", 0),
                                args.get("max_chars", 5000))
    if name == "list_documents":
        return lib.list_documents(args.get("level") or None, args.get("region") or None,
                                  args.get("year") or None, args.get("keyword") or None,
                                  min(int(args.get("limit") or 60), 200))
    return {"error": "未知工具：%s" % name}


def handle(lib, msg):
    mid = msg.get("id")
    method = msg.get("method")
    params = msg.get("params") or {}

    if method == "initialize":
        return {"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": params.get("protocolVersion") or PROTOCOL,
            "capabilities": {"tools": {}},
            "serverInfo": SERVER,
        }}
    if method in ("notifications/initialized", "initialized"):
        return None
    if method == "ping":
        return {"jsonrpc": "2.0", "id": mid, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}}
    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        try:
            data = call_tool(lib, name, args)
            text = json.dumps(data, ensure_ascii=False, indent=1)
            res = {"content": [{"type": "text", "text": text}], "isError": False}
        except Exception as e:                                   # 工具异常要回给模型，不中断连接
            res = {"content": [{"type": "text", "text": "工具执行失败：%s" % e}], "isError": True}
        return {"jsonrpc": "2.0", "id": mid, "result": res}
    if method in ("resources/list", "prompts/list"):
        key = "resources" if method.startswith("resources") else "prompts"
        return {"jsonrpc": "2.0", "id": mid, "result": {key: []}}
    return {"jsonrpc": "2.0", "id": mid,
            "error": {"code": -32601, "message": "不支持的方法：%s" % method}}


def main():
    lib = Library()
    sys.stderr.write("[legal-library] %d 件 / %d 条 / %.1f 万字\n"
                     % (lib.N, sum(1 for u in lib.units if u[1] == 1), len(lib.blob) / 10000))
    sys.stderr.flush()
    out = sys.stdout.buffer
    for line in sys.stdin.buffer:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line.decode("utf-8"))
        except Exception:
            continue
        if isinstance(msg, list):                                # 兼容批量消息
            msgs = msg
        else:
            msgs = [msg]
        for m in msgs:
            try:
                resp = handle(lib, m)
            except Exception as e:
                resp = {"jsonrpc": "2.0", "id": m.get("id"),
                        "error": {"code": -32603, "message": str(e)}}
            if resp is not None:
                out.write((json.dumps(resp, ensure_ascii=False) + "\n").encode("utf-8"))
                out.flush()


if __name__ == "__main__":
    main()
