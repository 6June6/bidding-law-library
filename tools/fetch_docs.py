#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""全文抓取：按条目标题检索官方原文页，抽取正文写入 Markdown。

用法：
  python3 tools/fetch_docs.py            # 抓取全部缺失文件
  python3 tools/fetch_docs.py A02 C03    # 只抓指定编号
  python3 tools/fetch_docs.py --force    # 覆盖已有文件
"""

import http.cookiejar
import html
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, "data")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
LEVEL_DIR = {
    "法律": "01-法律",
    "行政法规": "02-行政法规",
    "部门规章": "03-部门规章",
    "地方性法规": "04-地方性法规",
    "规范性文件": "05-规范性文件",
    "司法解释": "06-司法解释",
}
LEVEL_RANK = {"法律": 1, "行政法规": 2, "部门规章": 3,
              "地方性法规": 4, "规范性文件": 5, "司法解释": 6}
# 官方域名白名单（后缀匹配）
OFFICIAL = ("gov.cn", "npc.gov.cn", "court.gov.cn", "spp.gov.cn", "ccgp.gov.cn")

BOILER = [
    "扫一扫在手机打开当前页", "【打印】", "【关闭】", "打印本页", "关闭窗口",
    "分享到", "字号：", "大 中 小", "责任编辑：", "来源：", "上一篇", "下一篇",
    "相关链接", "网站地图", "关于我们", "版权所有", "ICP备", "京公网安备",
]


_JAR = http.cookiejar.CookieJar()
_OPENER = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(_JAR))


def fetch(url, timeout=45, referer="https://www.bing.com/"):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/json",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Referer": referer,
    })
    with _OPENER.open(req, timeout=timeout) as r:
        raw = r.read()
        ctype = r.headers.get("Content-Type", "")
    if "pdf" in ctype or url.lower().endswith(".pdf"):
        return None, "pdf"
    for enc in ("utf-8", "gb18030"):
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "ignore"), "utf-8?"


def pdf_text(url):
    """下载 PDF 并抽取文本（用于正文以附件形式发布的文件）"""
    try:
        import io
        import pypdf
        req = urllib.request.Request(url, headers={"User-Agent": UA,
                                                   "Referer": "https://www.gov.cn/"})
        with _OPENER.open(req, timeout=60) as r:
            raw = r.read()
        if not raw.startswith(b"%PDF"):
            return []
        rd = pypdf.PdfReader(io.BytesIO(raw))
        txt = "\n".join((pg.extract_text() or "") for pg in rd.pages[:80])
    except Exception:
        return []
    txt = txt.replace("\r", "\n")
    out = []
    for ln in txt.split("\n"):
        ln = re.sub(r"[ \t]+", " ", ln).strip()
        if ln:
            out.append(ln)
    return out


def find_pdfs(h, base):
    urls = []
    for m in re.finditer(r'href="([^"]+\.pdf)"', h, re.I):
        u = urllib.parse.urljoin(base, html.unescape(m.group(1)))
        if u not in urls:
            urls.append(u)
    return urls


def clean_text(h):
    h = re.sub(r"(?is)<script.*?</script>", " ", h)
    h = re.sub(r"(?is)<style.*?</style>", " ", h)
    h = re.sub(r"(?s)<!--.*?-->", " ", h)
    h = re.sub(r"(?i)<br\s*/?>", "\n", h)
    h = re.sub(r"(?i)</p\s*>", "\n\n", h)
    h = re.sub(r"(?i)</(div|tr|h1|h2|h3|li|table)\s*>", "\n", h)
    h = re.sub(r"(?is)<[^>]+>", "", h)
    h = html.unescape(h)
    h = h.replace("\u3000", " ").replace("\xa0", " ")
    h = h.replace("“", "“").replace("”", "”")
    lines = []
    for ln in h.split("\n"):
        ln = re.sub(r"[ \t]+", " ", ln).strip()
        if not ln:
            continue
        if any(b in ln for b in BOILER) and len(ln) < 40:
            continue
        lines.append(ln)
    # 合并被 HTML 硬换行切断的段落：以中文标点结尾视为段落结束
    merged, buf = [], ""
    for ln in lines:
        if not buf:
            buf = ln
        elif re.search(r"[。；：！？]$", buf) or ln.startswith("第") or re.match(r"^[一二三四五六七八九十]+、", ln):
            merged.append(buf)
            buf = ln
        else:
            buf += ln
    if buf:
        merged.append(buf)
    return merged


def _balanced_div(h, tag_re):
    """按标签配平取容器内部 HTML。

    正则版 `(.*?)</div>` 遇到容器内嵌套 div 会在第一个 </div> 就截断，
    复杂页面上正文只剩几百字，于是退回整页解析、把页头页脚一起吃进来。
    """
    m = re.search(r"<div\b[^>]*" + tag_re + r"[^>]*>", h, re.I)
    if not m:
        return None
    start, depth = m.end(), 1
    for t in re.finditer(r"<(/?)div\b[^>]*>", h[start:], re.I):
        if t.group(1):
            depth -= 1
            if depth == 0:
                return h[start: start + t.start()]
        else:
            depth += 1
    return h[start:]


CONTAINERS = (
    r'id="UCAP-CONTENT"',
    r'class="[^"]*\b(?:pages_content|TRS_Editor|article-content|art_context|content_box|zoom|view)\b[^"]*"',
    r'class="[^"]*\barticle\b[^"]*"',
)


def extract_article(html_text, title):
    """优先取正文容器（配平解析），退回全文段落"""
    best = ""
    for cre in CONTAINERS:
        inner = _balanced_div(html_text, cre)
        if not inner:
            continue
        cand = clean_text(inner)
        n = sum(len(x) for x in cand)
        if n > len(best):
            best, best_n = cand, n
        if n > 800:          # 命中可信容器即可，不再往后找
            return cand
    if best and best_n > 300:
        return best
    m = re.search(r"(?is)<article[^>]*>(.*?)</article>", html_text)
    if m:
        return clean_text(m.group(1))
    return clean_text(html_text)


def _squash(s):
    """比对用：去掉空白与书名号、括号等标点，避免「《中华人民共和国招标投标法》」
    与「《招标投标法》」之类写法差异造成漏判"""
    return re.sub(r"[\s《》〈〉（）()“”‘’\"']", "", s)


def score(lines, title):
    txt = "\n".join(lines)
    cx, ct = _squash(txt), _squash(title)
    core = _squash(title.replace("中华人民共和国", ""))
    hit = ct in cx or core in cx
    arts = len(re.findall(r"第[一二三四五六七八九十百零〇\d]+条", txt))
    return (1 if hit else 0), len(txt), arts


def bing_urls(q, count=20, retries=2):
    u = "https://www.bing.com/search?q=%s&count=%d&setlang=zh-CN&ensearch=0" % (
        urllib.parse.quote(q), count)
    h = None
    for i in range(retries):
        try:
            h, _ = fetch(u)
        except Exception:
            h = None
        if h and "b_algo" in h:
            break
        if h and len(h) > 20000:
            break
        time.sleep(4 + 4 * i)  # 被限流时退避
    if not h:
        return []
    import base64

    def decode(link):
        """解出 bing.com/ck/a 跳转链接里的真实地址"""
        m = re.search(r"[?&]u=a1([A-Za-z0-9_\-]+)", link)
        if not m:
            return link
        t = m.group(1).replace("-", "+").replace("_", "/")
        t += "=" * (-len(t) % 4)
        try:
            return base64.b64decode(t).decode("utf-8", "ignore")
        except Exception:
            return link

    urls = []
    for m in re.finditer(r'href="(https?://[^"]+)"', h):
        link = decode(html.unescape(m.group(1)))
        if "bing.com" in link:
            continue
        host = link.split("/")[2] if "//" in link else ""
        if any(host.endswith(d) or ("." + d) in host for d in OFFICIAL):
            if link not in urls:
                urls.append(link)
    return urls


def good_url(u):
    bad = ("list.shtml", "index.htm", "/search", "sousuo", ".doc", ".xls",
           "javascript", "big5.", "beian.", "dxzhgl.", "qiyereport", "flk.npc.gov.cn")
    return not any(b in u.lower() for b in bad)


def gov_urls(title, n=8):
    """中国政府网政策文件库（部门规章/规范性文件）直接检索"""
    q = urllib.parse.quote(title)
    u = ("https://sousuo.www.gov.cn/search-gov/data?t=zhengcelibrary_bm&q=%s"
         "&sort=score&sortType=1&searchfield=title&p=1&n=%d" % (q, n))
    try:
        h, _ = fetch(u, referer="https://www.gov.cn/")
        d = json.loads(h)
        v = d.get("searchVO") or {}
        return [x.get("url") for x in (v.get("listVO") or []) if x.get("url")]
    except Exception:
        return []


def safe_name(title, pub):
    n = re.sub(r'[\\/:*?"<>|\n\r]', "_", title)
    return "%s（%s）.md" % (n, pub[:4]) if pub else n + ".md"


HEAD_RE = re.compile(r"^第[一二三四五六七八九十百零〇\d]+(?:分编|编|章|节)")
ART_RE = re.compile(r"^第[一二三四五六七八九十百零〇\d]+条")


def normalize_body(lines):
    """去掉导航残留与重复的目录条目，保留题注 + 正文"""
    # 去掉纯目录标记行
    lines = [x for x in lines if re.sub(r"\s", "", x) not in ("目录", "目次")]
    # 目录区（首条条文之前）里与后文重名的标题丢弃；正文内的标题一律保留
    # （旧实现是「同名标题只留最后一次」，多编文件如民法典会把正文里各编的
    #  第一章 基本规定等标题一起删掉）
    first_art = next((i for i, x in enumerate(lines) if ART_RE.match(x)), len(lines))
    last, last_short = {}, {}
    for i, x in enumerate(lines):
        if HEAD_RE.match(x):
            last[re.sub(r"\s", "", x)] = i
        k = re.sub(r"\s", "", x)
        if 0 < len(k) <= 6:          # 「附　则」「总　则」这类无编号小节名
            last_short[k] = i
    out = []
    for i, x in enumerate(lines):
        k = re.sub(r"\s", "", x)
        if i < first_art:
            if HEAD_RE.match(x) and last.get(k, i) > i:
                continue
            if 0 < len(k) <= 6 and last_short.get(k, i) > i:
                continue
        out.append(x)
    # 从题注（形如「（1999年8月30日……通过）」）或首个章标题起截断，丢弃站点头部
    start = 0
    cap = next((i for i, x in enumerate(out[:40])
                if re.match(r"^[（(]\s*\d{4}年", x)), None)
    if cap is None:   # 司法解释类：《……》……通过/公布
        cap = next((i for i, x in enumerate(out[:40])
                    if re.match(r"^《.+》", x) and re.search(r"(通过|公布|发布)", x)), None)
    if cap is not None:
        start = cap
    else:
        for i, x in enumerate(out[:60]):
            if HEAD_RE.match(x) and any(ART_RE.match(y) for y in out[i:i + 4]):
                start = i
                break
    # 兜底：题注可能混在页面导航同一行内，按字符位置截断
    if start == 0:
        joined = "\n".join(out)
        m = re.search(r"《[^》]{4,60}》[^。\n]{0,120}?(?:通过|公布)", joined[:4000])
        if m:
            cut = joined[:m.start()].count("\n")
            out = out[cut:]
        else:
            m2 = re.search(r"[（(]\s*\d{4}年", joined[:4000])
            if m2:
                cut = joined[:m2.start()].count("\n")
                out = out[cut:]
    # 题注与站点导航混在同一行时，行内截断
    if out and start == 0:
        m = re.search(r"《[^》]{4,60}》", out[0])
        if m and re.search(r"(通过|公布)", out[0][m.start():m.end() + 150]):
            out[0] = out[0][m.start():]
    return out[start:]


# 页脚、导航、栏目字段：出现这些词的行不是法规内容
TAIL_WORDS = (
    "相关稿件", "相关链接", "友情链接", "相关文章", "网站地图", "关于本网",
    "网站声明", "联系我们", "网站纠错", "主办单位", "承办单位", "运行维护单位",
    "ICP备", "公网安备", "网站标识码", "国务院客户端", "回到顶部", "扫一扫在手机",
    "打印本页", "关闭窗口", "分享到", "责任编辑", "【打印】", "【关闭】",
    "上一篇", "下一篇", "无障碍", "登录个人中心", "收藏本页", "字号：",
)
NAV_MARKS = ("首页|简|繁", "_中国政府网", "大超大", "|打印", "当前位置：", "您的位置")
META_LABEL = re.compile(
    r"^(?:发文机关|索引号|主题分类|公文种类|成文日期|发文字号|公开事项名称|"
    r"制发日期|来\s*源|标\s*题|附件名称|有效性|废止日期|公开日期)\s*[:：]?")
SIGN_RE = re.compile(
    r"^((?:主\s*任|副?\s*部\s*长|局\s*长|秘书长|国家发展改革委办公厅|国家发展改革委|"
    r"发展改革委|财政部|人民政府|委员会|办公厅)[^\d。；]{0,14}?)"
    r"(\d{4}年\d{1,2}月\d{1,2}日)(.*)$")


def _looks_nav(s):
    return s.count("|") >= 2 or any(k in s for k in NAV_MARKS) or s.endswith(("网站", "网"))


def _split_sign(ln):
    """拆开「主 任 何立峰2018年3月27日<标题>」这类落款与正文粘连的行"""
    # 落款日期 + （此件公开发布）+ 标题/正文 粘成一行
    m = re.match(r"^(.{0,60}?\d{4}年\d{1,2}月\d{1,2}日)"
                 r"(（此件公开发布）|\(此件公开发布\))(.{0,200})$", ln)
    if m:
        return [m.group(1) + m.group(2), m.group(3)] if m.group(3).strip() \
            else [m.group(1) + m.group(2)]
    m = SIGN_RE.match(ln)
    if not m:
        # 部委令的「第 X 号」常与紧随其后的正文粘在一行
        m2 = re.match(r"^(第\s*\d+\s*号)(.{6,})$", ln)
        return [m2.group(1), m2.group(2)] if m2 else [ln]
    signer, date, rest = m.group(1).strip(), m.group(2), m.group(3).strip()
    out = [signer, date] if signer else [date]
    if rest and (len(rest) > 40 or re.search(r"[。；：]", rest)):
        out.append(rest)          # 后面是真正文
    return out


def _dedupe_blocks(lines):
    """页面常把同一段正文渲染两遍（PC 版 + 手机版），整块重复只留一份"""
    idx, drop, i = {}, set(), 0
    while i < len(lines):
        key = lines[i]
        if len(key) >= 12 and key in idx:
            j, k = idx[key], 0
            while i + k < len(lines) and j + k < i and lines[i + k] == lines[j + k]:
                k += 1
            # 块里含条文/章标题的，宁可留着也不去重；只清理成段的重复正文
            # （短小的重复段落可能是两份附件模板里的固有文字，删了就是数据丢失）
            if (k >= 2 and sum(len(x) for x in lines[i:i + k]) >= 300
                    and not any(ART_RE.match(x) or HEAD_RE.match(x)
                                for x in lines[i:i + k])):
                drop.update(range(i, i + k))
                i += k
                continue
        idx.setdefault(key, i)
        i += 1
    out = []
    for n, ln in enumerate(lines):
        if n in drop:
            continue
        out.append(ln)
    return out


FIELD_LINK = re.compile(r'HYPERLINK\s+(?:\\l\s+)?"[^"]*"\s*', re.I)
FIELD_PAGE = re.compile(r"PAGE\s+\\\*|^\s*-\s*\d+\s*-\s*$", re.I)


def _strip_fields(ln):
    """清掉 Word 域代码：HYPERLINK "http://…"（含 javascript:SLC 交叉引用）"""
    if "HYPERLINK" not in ln:
        return ln
    ln = FIELD_LINK.sub("", ln)
    # 域代码删除后会在书名号、顿号旁留下空格，一并收紧
    ln = re.sub(r"\s+(?=[《》、，。；：）】])", "", ln)
    ln = re.sub(r"(?<=[《（【])\s+", "", ln)
    return re.sub(r"\s{2,}", " ", ln).strip()


def sanitize(lines):
    """清掉页脚、导航、栏目字段、域代码、重复块；条文与章标题永不删"""
    out = []
    for ln in lines:
        ln = ln.strip()
        if not ln:
            continue
        ln = _strip_fields(ln)          # 域代码对条文也要清，属修复不是删减
        if not ln or FIELD_PAGE.search(ln):
            continue
        keep = ART_RE.match(ln) or HEAD_RE.match(ln) or ln.startswith("#")
        if not keep:
            if any(k in ln for k in NAV_MARKS) or ln.count("|") >= 2:
                continue
            hits = [w for w in TAIL_WORDS if w in ln]
            if hits:
                cut = min(ln.find(w) for w in hits)
                head = ln[:cut].strip()
                # 页脚词前面还粘着正文的，留下那一段
                if len(head) >= 20 and not _looks_nav(head):
                    out.extend(_split_sign(head))
                continue
            if META_LABEL.match(ln) and len(ln) <= 40:
                continue
            if re.fullmatch(r"\d{1,3}", ln):      # PDF/Word 转档残留的页码
                continue
        out.extend(_split_sign(ln))
    return _dedupe_blocks(out)


def render_md(it, lines, src_url):
    lines = sanitize(normalize_body(lines))
    head = [
        "---",
        "编号: %s" % it["id"],
        "名称: %s" % it["title"],
        "效力层级: %s" % it["level"],
        "分类: %s" % it["category"],
        "制定机关: %s" % (it.get("issuer") or "—"),
        "文号: %s" % (it.get("doc_no") or "—"),
        "公布日期: %s" % (it.get("pub") or "—"),
        "施行日期: %s" % (it.get("eff") or "—"),
        "效力状态: %s" % (it.get("status") or "—"),
        "沿革: %s" % (it.get("note") or "—"),
        "原文地址: %s" % src_url,
        "抓取日期: %s" % time.strftime("%Y-%m-%d"),
        "---",
        "",
        "# %s" % it["title"],
        "",
    ]
    body = []
    for ln in lines:
        if HEAD_RE.match(ln):
            body.append("")
            body.append("## " + ln)
            body.append("")
        else:
            body.append(ln)
            body.append("")
    tail = ["", "---", "", "> 本文由公开官方渠道抓取整理，仅供检索参考；"
            "引用请以官方发布文本为准。原文地址：%s" % src_url, ""]
    return "\n".join(head + body + tail)


def prefer(u):
    """官方站点内部优先级：国务院公报 > 政策库 > 人大网 > 其他"""
    if "/gongbao/" in u:
        return 0
    if "www.gov.cn/zhengce" in u or "www.gov.cn/zwgk" in u:
        return 1
    if "npc.gov.cn" in u:
        return 2
    if "court.gov.cn" in u:
        return 3
    return 4


def reparse(ids=None):
    """按已记录的原文地址重新下载解析（不重新检索）"""
    items = json.load(open(os.path.join(DATA, "items.json"), encoding="utf-8"))
    n = 0
    for it in items:
        if ids and it["id"] not in ids:
            continue
        u = it.get("src_url")
        if not u:
            fn = os.path.join(BASE, LEVEL_DIR[it["level"]],
                              safe_name(it["title"], it.get("pub") or ""))
            if os.path.exists(fn):
                m = re.search(r"^原文地址: (\S+)$", open(fn, encoding="utf-8").read(), re.M)
                u = m.group(1) if m else None
        if not u:
            continue
        try:
            if u.lower().endswith(".pdf"):
                lines = pdf_text(u)
            else:
                h, _ = fetch(u)
                lines = extract_article(h, it["title"])
                if sum(len(x) for x in lines) < 2500:
                    for pu in find_pdfs(h, u)[:2]:
                        pl = pdf_text(pu)
                        if not pl or sum(len(x) for x in pl) <= sum(len(x) for x in lines):
                            continue
                        if score(pl, it["title"])[0]:   # 附件里也得有标题，别把正文换掉
                            u, lines = pu, pl
                        break
        except Exception as e:
            print("ERR", it["id"], repr(e)[:60])
            continue
        ok, ln, arts = score(lines, it["title"])
        need = 400 if it["level"] == "规范性文件" else 600
        if not ok or ln < need:
            print("SKIP", it["id"], ln)
            continue
        d = os.path.join(BASE, LEVEL_DIR[it["level"]])
        fn = os.path.join(d, safe_name(it["title"], it.get("pub") or ""))
        open(fn, "w", encoding="utf-8").write(render_md(it, lines, u))
        it["file"] = os.path.relpath(fn, BASE)
        it["src_url"] = u
        it["chars"] = ln
        n += 1
        time.sleep(0.4)
    json.dump(items, open(os.path.join(DATA, "items.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("重新解析完成：", n, "件")


def try_url(it, u):
    """验证单个地址，命中则返回 (u, lines)"""
    try:
        if u.lower().endswith(".pdf"):
            lines = pdf_text(u)
        else:
            h, _ = fetch(u)
            if not h:
                return None
            lines = extract_article(h, it["title"])
            if sum(len(x) for x in lines) < 2500:
                for pu in find_pdfs(h, u)[:2]:
                    pl = pdf_text(pu)
                    if not pl or sum(len(x) for x in pl) <= sum(len(x) for x in lines):
                        continue
                    if score(pl, it["title"])[0]:
                        u, lines = pu, pl
                    break
    except Exception:
        return None
    hit, ln, arts = score(lines, it["title"])
    if hit and ln > 800 and arts >= 3:
        return (u, lines)
    return None


def main():
    if "--reparse" in sys.argv:
        i = sys.argv.index("--reparse")
        return reparse([a for a in sys.argv[i + 1:] if not a.startswith("-")])
    items = json.load(open(os.path.join(DATA, "items.json"), encoding="utf-8"))
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    force = "--force" in sys.argv
    todo = [i for i in items if not args or i["id"] in args]
    ok = fail = skip = 0
    report = []
    for it in todo:
        d = os.path.join(BASE, LEVEL_DIR[it["level"]])
        os.makedirs(d, exist_ok=True)
        fn = os.path.join(d, safe_name(it["title"], it.get("pub") or ""))
        if os.path.exists(fn) and not force:
            skip += 1
            continue
        title = it["title"]
        queries = ['"%s" 全文' % title, title + " 全文 第1条"]
        best = None
        variants = ['%s site:gov.cn' % title, '%s 全文' % title,
                    '%s 第1条' % title, '"%s"' % title, title]
        cands = []
        for qi, q in enumerate(variants):
            got = [u for u in bing_urls(q) if good_url(u)]
            time.sleep(5)          # 控制搜索频率，避免被限流
            for u in got:
                if u not in cands:
                    cands.append(u)
            if cands:
                break
        if it["level"] in ("部门规章", "规范性文件"):
            for u in gov_urls(title):
                if good_url(u) and u not in cands:
                    cands.insert(0, u)
        if it.get("url"):
            cands.insert(0, it["url"])
        cands.sort(key=prefer)
        tried = set()
        if it.get("url"):   # 人工指定地址优先验证
            best = try_url(it, it["url"])
            if best:
                tried.add(it["url"])
        for u in cands[:6]:
            time.sleep(0.5)
            if u.lower().endswith(".pdf"):
                lines = pdf_text(u)
                if lines:
                    hit, ln, arts = score(lines, title)
                    if hit and ln > 800 and arts >= 3:
                        best = (u, lines)
                        break
                continue
            try:
                h, _ = fetch(u)
            except Exception:
                continue
            if not h:
                continue
            lines = extract_article(h, title)
            hit, ln, arts = score(lines, title)
            if ln < 2500:
                # 正文可能以附件 PDF 形式挂出
                for pu in find_pdfs(h, u)[:2]:
                    plines = pdf_text(pu)
                    if plines and sum(len(x) for x in plines) > ln:
                        phit, pln, parts = score(plines, title)
                        if phit and pln > ln:
                            u, lines = pu, plines
                            hit, ln, arts = phit, pln, parts
                            break
            if hit and ln > 800 and arts >= 3:
                best = (u, lines)
                break
            if best is None and hit and ln > 800:
                best = (u, lines)
        if not best:
            report.append("MISS %s %s" % (it["id"], title))
            fail += 1
            time.sleep(8)
            continue
        u, lines = best
        open(fn, "w", encoding="utf-8").write(render_md(it, lines, u))
        it["file"] = os.path.relpath(fn, BASE)
        it["src_url"] = u
        it["chars"] = len("\n".join(lines))
        report.append("OK   %s %-42s %6d字 %s" % (it["id"], title[:40], it["chars"], u[:70]))
        ok += 1
        time.sleep(3)
        json.dump(items, open(os.path.join(DATA, "items.json"), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
    print("\n".join(report))
    print("\n完成：成功 %d，失败 %d，跳过 %d" % (ok, fail, skip))


if __name__ == "__main__":
    main()
