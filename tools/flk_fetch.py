#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从国家法律法规数据库（flk.npc.gov.cn）取官方全文。

背景：flk 已改版为 Vite SPA，旧的 /api/detail 失效，改为：
  GET /law-search/search/flfgDetails?bbbs=<bbbs>      → 元数据 + ossFile 路径
  GET /law-search/amazonFile/ofdGenerateLink?filePath= → 带签名的下载地址
下载地址指向内网 OSS 域名（flkoss.obs-bj2-internal.cucloud.cn），
用 Host 头保留内网域名、连到该 bucket 的公网 IP 即可拿到签名文件。

用法：
  python3 tools/flk_fetch.py              # 处理所有缺全文的条目
  python3 tools/flk_fetch.py D01 D05      # 只处理指定编号
  python3 tools/flk_fetch.py --force      # 已有文件的也重抓
"""

import http.client
import io
import json
import os
import re
import socket
import sys
import time
import urllib.parse
import urllib.request
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fetch_docs as F  # noqa: E402

DATA = os.path.join(F.BASE, "data")
API = "https://flk.npc.gov.cn"
INTERNAL_HOST = "flkoss.obs-bj2-internal.cucloud.cn"
PUBLIC_HOST = "flkoss.obs-bj2.cucloud.cn"


def api_get(path, params, timeout=30):
    url = API + path + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={
        "User-Agent": F.UA,
        "Accept": "application/json, text/plain, */*",
        "Referer": API + "/",
    })
    for i in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:
            if i == 2:
                raise
            time.sleep(2 + 2 * i)


def public_ip():
    """bucket 的公网 IP（用于 Host 欺骗下载）"""
    try:
        return socket.gethostbyname(PUBLIC_HOST)
    except Exception:
        return None


def download(signed_url, ip, timeout=60):
    """保持 Host 为内网域名，直连公网 IP，签名才有效"""
    p = urllib.parse.urlparse(signed_url)
    path = p.path + ("?" + p.query if p.query else "")
    conn = http.client.HTTPConnection(ip, 80, timeout=timeout)
    try:
        conn.request("GET", path, headers={"Host": p.netloc, "User-Agent": F.UA})
        r = conn.getresponse()
        raw = r.read()
        if r.status != 200:
            raise IOError("HTTP %s" % r.status)
        return raw
    finally:
        conn.close()


def docx_lines(raw):
    """docx → 行列表（段落切分 + 去标签）

    个别部委的「文字版」docx 正文放在 <w:altChunk> 引用的 chunk.html 里，
    document.xml 只有标题和题注，必须改读内嵌 HTML。
    """
    import html as H
    z = zipfile.ZipFile(io.BytesIO(raw))
    names = z.namelist()
    x = z.read("word/document.xml").decode("utf-8", "ignore")

    def _xml_lines(markup):
        m = markup
        m = re.sub(r"</w:p>", "\n", m)
        m = re.sub(r"<w:tab[^>]*/>", "\t", m)
        m = re.sub(r"<w:br[^>]*/>", "\n", m)
        m = re.sub(r"<[^>]+>", "", m)
        txt = H.unescape(m).replace("\r", "\n")
        got = []
        for ln in txt.split("\n"):
            ln = re.sub(r"[ \t\u00a0]+", " ", ln).strip()
            if ln:
                got.append(ln)
        return got

    if "altChunk" in x:
        chunk = next((n for n in names if n.lower().endswith(("chunk.html", ".htm", ".html"))), None)
        if chunk:
            h = z.read(chunk).decode("utf-8", "ignore")
            h = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", "", h)
            h = re.sub(r"(?i)</(p|div|tr|h[1-6]|li)>", "\n", h)
            h = re.sub(r"(?i)<br\s*/?>", "\n", h)
            h = re.sub(r"<[^>]+>", "", h)
            txt = H.unescape(h).replace("\r", "\n")
            out = []
            for ln in txt.split("\n"):
                ln = re.sub(r"[ \t\u00a0]+", " ", ln).strip()
                if ln:
                    out.append(ln)
            if sum(len(t) for t in out) > 200:
                # document.xml 里通常只有标题与题注，要保留在正文之前
                head = _xml_lines(x)
                body = [y for y in out if y not in set(head)]
                return merge_wrapped(head + body, generic=False)

    out = _xml_lines(x)
    # docx 每个 w:p 已是自然段，只有题注会被拆成两段，别做通用折行合并
    return merge_wrapped(out, generic=False)


END = re.compile(r"[。；：！？，、）》”\"）)]$")
CAP = re.compile(r"^[（(]\s*\d{4}年")
# 结构性行：绝不与上一行合并
STRUCT = re.compile(r"^(?:第[一二三四五六七八九十百零〇\d]+(?:分编|编|章|节|条)"
                    r"|[（(][一二三四五六七八九十]+[)）]|附件|附表|目\s*录)")


def merge_wrapped(lines, width=28, generic=True):
    """把被硬折行切断的段落接回去。

    两种来源要区别对待：
      · 老式 .doc 经 textutil 转出，约 40 字就断行 → generic=True
      · 现代 docx 的每个 w:p 本就是自然段，只应处理被拆开的题注 → generic=False
    通用规则一律不碰条文/章标题/项号行，且要求下一行也足够长。
    """
    out, buf = [], ""
    for ln in lines:
        if not buf:
            buf = ln
            continue
        if CAP.match(buf) and not buf.endswith(("）", ")")):
            buf += ln
        elif (generic and len(buf) >= width and not END.search(buf)
              and len(ln) >= width and not STRUCT.match(ln)):
            buf += ln
        else:
            out.append(buf)
            buf = ln
    if buf:
        out.append(buf)
    return out


def doc_lines(raw):
    """老式 .doc（OLE2）优先交给 textutil / antiword；不可用则返回空"""
    import subprocess
    import tempfile
    if not raw.startswith(b"\xd0\xcf\x11\xe0"):
        return []
    fd, tmp = tempfile.mkstemp(suffix=".doc")
    os.close(fd)
    try:
        open(tmp, "wb").write(raw)
        for cmd in (["textutil", "-convert", "txt", "-stdout", tmp],
                    ["antiword", tmp]):
            try:
                out = subprocess.run(cmd, capture_output=True, timeout=60)
            except Exception:
                continue
            if out.returncode == 0 and out.stdout:
                try:
                    txt = out.stdout.decode("utf-8")
                except UnicodeDecodeError:
                    txt = out.stdout.decode("gb18030", "ignore")
                lines = [re.sub(r"[ \t]+", " ", x).strip()
                         for x in txt.replace("\r", "\n").split("\n")]
                return merge_wrapped([x for x in lines if x], generic=True)
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
    return []


def pdf_lines(raw):
    import pypdf
    rd = pypdf.PdfReader(io.BytesIO(raw))
    txt = "\n".join((pg.extract_text() or "") for pg in rd.pages[:120])
    out = []
    for ln in txt.replace("\r", "\n").split("\n"):
        ln = re.sub(r"[ \t]+", " ", ln).strip()
        if ln:
            out.append(ln)
    return out


def norm_title(t):
    t = re.sub(r"[《》〈〉\s（）()]", "", t)
    return t.replace("中华人民共和国", "")


def bbbs_of(it):
    m = re.search(r"bbbs=([0-9a-fA-F]{16,})", it.get("source") or "")
    return m.group(1) if m else None


def fetch_one(it, ip):
    bbbs = bbbs_of(it)
    if not bbbs:
        print("SKIP %-5s %s（无 bbbs，非数据库条目）" % (it["id"], it["title"]))
        return None
    d = api_get("/law-search/search/flfgDetails", {"bbbs": bbbs})
    data = (d or {}).get("data") or {}
    if not data:
        print("MISS %-5s %s（详情为空）" % (it["id"], it["title"]))
        return None
    if norm_title(data.get("title") or "") != norm_title(it["title"]):
        print("MISS %-5s %s（标题不符：%s）" % (it["id"], it["title"], data.get("title")))
        return None
    oss = data.get("ossFile") or {}
    lines = []
    for key in ("ossWordPath", "ossPdfPath"):
        fp = oss.get(key)
        if not fp:
            continue
        try:
            signed = api_get("/law-search/amazonFile/ofdGenerateLink",
                             {"filePath": fp}).get("file", {}).get("download_url")
            if not signed:
                continue
            raw = download(signed, ip)
            if raw[:2] == b"PK":
                lines = docx_lines(raw)
            elif raw[:4] == b"%PDF":
                lines = pdf_lines(raw)
            else:
                lines = doc_lines(raw)
        except Exception as e:
            print("      %s 取用失败：%s" % (key, e))
            lines = []
        if lines:
            break
    if not lines:
        print("MISS %-5s %s（无可用正文文件）" % (it["id"], it["title"]))
        return None
    hit, ln, arts = F.score(lines, it["title"])
    if not hit or ln < 400:
        print("MISS %-5s %s（正文校验未过：hit=%d 字数=%d）" % (it["id"], it["title"], hit, ln))
        return None
    # 用数据库元数据补空缺（不改已有值）
    if not it.get("pub") and data.get("gbrq"):
        it["pub"] = data["gbrq"]
    if not it.get("eff") and data.get("sxrq"):
        it["eff"] = data["sxrq"]
    if not it.get("issuer") and data.get("zdjgName"):
        it["issuer"] = data["zdjgName"]
    src = "https://flk.npc.gov.cn/detail?bbbs=%s" % bbbs
    fn = os.path.join(F.BASE, F.LEVEL_DIR[it["level"]],
                      F.safe_name(it["title"], it.get("pub") or ""))
    os.makedirs(os.path.dirname(fn), exist_ok=True)
    open(fn, "w", encoding="utf-8").write(F.render_md(it, lines, src))
    it["file"] = os.path.relpath(fn, F.BASE)
    it["src_url"] = src
    it["chars"] = ln
    print("OK   %-5s %-30s %5d 字 %2d 条  %s" %
          (it["id"], it["title"][:30], ln, arts, os.path.basename(fn)))
    return it


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    force = "--force" in sys.argv
    items = json.load(open(os.path.join(DATA, "items.json"), encoding="utf-8"))
    if args:
        sel = [x for x in items if x["id"] in args]
    else:
        sel = [x for x in items
               if force or not (x.get("file") and os.path.exists(os.path.join(F.BASE, x["file"])))]

    ip = public_ip()
    if not ip:
        print("无法解析 %s，退出" % PUBLIC_HOST)
        return 1
    print("OSS 公网出口：%s；待处理 %d 条" % (ip, len(sel)), flush=True)

    ok = 0
    by_id = {x["id"]: x for x in items}
    for n, it in enumerate(sel, 1):
        print("[%d/%d] %s" % (n, len(sel), it["title"]), flush=True)
        try:
            got = fetch_one(it, ip)
        except Exception as e:
            print("ERR  %-5s %s：%s" % (it["id"], it["title"], e))
            got = None
        if got:
            ok += 1
            by_id[got["id"]] = got
        time.sleep(1.2)

    json.dump(list(by_id.values()),
              open(os.path.join(DATA, "items.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("完成：成功 %d / %d" % (ok, len(sel)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
