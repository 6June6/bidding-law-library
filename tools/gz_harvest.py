#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""采集部委「jpaas」平台的规章库 / 规范性文件库栏目。

这类站点（住建部等）栏目页只给出 10 行，真正的列表由
  GET /api-gateway/jpaas-publish-server/front/page/build/unit
带 paramJson={"pageNo":1,"pageSize":200,"loadEnabled":true,"search":"{}"}
返回 HTML 片段。每行含标题、发文信息与「文字版 / 图片版」下载地址，
文字版就是官方 doc/docx，比解析网页更可靠。

用法：
  python3 tools/gz_harvest.py list  <栏目URL> [--out data/gz_xxx.json]
  python3 tools/gz_harvest.py fetch <清单JSON> [--ids 1,3,5] [--dry]
"""

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
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
API = "/api-gateway/jpaas-publish-server/front/page/build/unit"


def get(url, timeout=45, referer=None):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "text/html,application/json,*/*",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Referer": referer or url,
    })
    for i in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    import gzip
                    raw = gzip.decompress(raw)
                return raw
        except Exception:
            if i == 2:
                raise
            time.sleep(2 + 2 * i)


def page_params(url):
    """从栏目页 HTML 里抠出 unit 接口需要的参数"""
    h = get(url).decode("utf-8", "ignore")
    m = re.search(r'queryData="?(\{.*?\})"?', h, re.S)
    if not m:
        raise SystemExit("未找到 queryData：%s" % url)
    q = json.loads(m.group(1).replace("'", '"'))
    return q, h


def unit_url(url, q):
    host = urllib.parse.urlsplit(url).netloc
    params = dict(parseType=q["parseType"], webId=q["webId"], tplSetId=q["tplSetId"],
                  pageType=q["pageType"], tagId=q["tagId"],
                  editType=q.get("editType") or "null", pageId=q["pageId"])
    return "https://%s%s?%s" % (host, API, urllib.parse.urlencode(params))


def list_rows(url, page_size=100):
    q, _ = page_params(url)
    api = unit_url(url, q)
    rows, count, page = [], 0, 1
    while True:
        pj = json.dumps({"pageNo": page, "pageSize": page_size,
                         "loadEnabled": True, "search": "{}"}, separators=(",", ":"))
        frag = json.loads(get(api + "&paramJson=" + urllib.parse.quote(pj),
                              referer=url).decode("utf-8"))["data"]["html"]
        mc = re.search(r"count':'(\d+)'", frag)
        if mc:
            count = int(mc.group(1))
        got = 0
        for tr in re.findall(r"<tr>(.*?)</tr>", frag, re.S)[1:]:
            m = re.search(r'<a href="([^"]+)"[^>]*title="([^"]*)"', tr)
            if not m:
                continue
            got += 1
            note = re.search(r"<p>(.*?)</p>", tr, re.S)
            dls = dict((t.strip(), u) for u, t in
                       re.findall(r'href="(/api-gateway[^"]+)"[^>]*>\s*([^<]+?)\s*<', tr))
            rows.append(dict(title=html.unescape(m.group(2)),
                             url=m.group(1),
                             note=re.sub(r"\s+", " ", note.group(1)).strip() if note else "",
                             doc=html.unescape(dls.get("文字版", "")),
                             pdf=html.unescape(dls.get("图片版", ""))))
        if not got or len(rows) >= count or page > 40:
            break
        page += 1
        time.sleep(0.4)
    return rows, count


def parse_note(note):
    """（2017年1月24日中华人民共和国住房和城乡建设部令第33号发布　自2017年5月1日起施行）"""
    n = note.strip("（）() ")
    doc_no = ""
    mi = re.search(r"令第\s*(\d+)\s*号", n)
    if mi:
        head = n[:mi.start()]
        head = re.sub(r"^.*?\d{1,2}日", "", head)          # 去掉「2022年12月29日」
        head = head.replace("中华人民共和国", "").strip(" ，、")
        head = head[-24:]
        doc_no = (head + "令第%s号" % mi.group(1)) if head else ("令第%s号" % mi.group(1))
    pub = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", n)
    eff = re.search(r"自?(\d{4})年(\d{1,2})月(\d{1,2})日起?施行", n)
    f = lambda t: "%s-%02d-%02d" % (t.group(1), int(t.group(2)), int(t.group(3))) if t else ""
    return doc_no, f(pub), f(eff)


DOMAIN = ["招标", "投标", "采购", "建筑市场", "建设工程", "工程建设", "施工", "监理",
          "造价", "勘察", "设计", "质量", "安全", "资质", "分包", "承包", "发包",
          "验收", "备案", "许可", "检测", "总承包", "工程", "房地产", "市政"]
SKIP = ["公园", "绿化", "公厕", "水箱", "危险房屋", "档案", "城市设计", "市容",
        "垃圾", "供水", "供热", "燃气", "园林", "风景", "历史文化", "消防", "公积金"]

# 规范性文件里噪音最多：一次性批复、统计宣传、职业资格等，只保留制度性文件
STRONG = ["招标", "投标", "采购", "工程总承包", "总承包", "建筑市场", "施工", "监理",
          "造价", "价款", "结算", "分包", "发包", "资质", "质量", "安全", "检测",
          "验收", "审批制度", "示范文本", "农民工工资", "保证金", "保函", "评标",
          "工程担保", "强制性标准", "工程建设项目"]
WEAK = ["复函", "答复", "函", "统计", "宣传", "考试", "培训", "继续教育", "表彰",
        "评比", "命名", "名单", "通报", "应急预案", "洪涝", "防汛", "农村自建房",
        "住房公积金", "无障碍", "养老", "老旧小区", "棚户区", "城市体检", "城市更新",
        "反洗钱", "经纪", "估价", "物业", "网签",
        "简化", "取消", "废止", "电子化", "电子证照", "统一延续", "申报材料",
        "启用", "信息报送", "数据标准", "平台建设", "一体化工作平台", "考核",
        "指标", "补充通知", "有关问题的通知", "有关事项的通知", "资质证书继续有效",
        "农房", "农村危房", "农村低收入", "扬尘", "能耗监测"]


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "list":
        url = sys.argv[2]
        rows, count = list_rows(url)
        print("栏目申报总数 %d，解析到 %d 行" % (count, len(rows)))
        out = None
        if "--out" in sys.argv:
            out = sys.argv[sys.argv.index("--out") + 1]
        else:
            out = os.path.join(DATA, "gz_%s.json" % re.sub(r"\W+", "_", url.split("//")[-1])[:40])
        sel = []
        for i, r in enumerate(rows, 1):
            r["no"] = i
            doc_no, pub, eff = parse_note(r["note"])
            r.update(doc_no=doc_no, pub=pub, eff=eff)
            keep = any(k in r["title"] for k in DOMAIN) and not any(k in r["title"] for k in SKIP)
            if "--strict" in sys.argv:
                keep = (any(k in r["title"] for k in STRONG)
                        and not any(k in r["title"] for k in WEAK + SKIP))
            r["keep"] = keep
            if keep:
                sel.append(r)
        json.dump(rows, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("本领域相关 %d 条，已写入 %s" % (len(sel), out))
        for r in sel:
            print("  %-52s %-28s %s" % (r["title"][:50], r["doc_no"][:26], r["pub"]))
        return
    print(__doc__)


if __name__ == "__main__":
    main()
