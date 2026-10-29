#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一键更新：重取元数据 → 补抓全文 → 回填沿革 → 清洗 → 重建索引

抓取顺序有讲究：法规库（官方 docx，带立法题注）优先，网页检索兜底，
最后合成「正文在网页、标准在附件」的文件。

  python3 tools/refresh.py              # 增量：只补缺失全文
  python3 tools/refresh.py --full        # 全量：重新取数并重抓全部全文
  python3 tools/refresh.py --no-web      # 只用法规库，不跑网页检索
  python3 tools/refresh.py --harvest     # 先跑一遍主题词收割（会新增条目）

注意：gz_import.py 与 flk_fetch.py 都会整表写回 items.json，必须串行。
"""

import os
import subprocess
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable


def run(*args):
    print("\n>>>", " ".join(args[1:]))
    r = subprocess.run([PY] + list(args), cwd=BASE)
    if r.returncode:
        sys.exit(r.returncode)


if __name__ == "__main__":
    full = "--full" in sys.argv
    force = ["--force"] if full else []
    run("tools/build_catalog.py", *(["--refresh"] if full else []))
    if "--harvest" in sys.argv:
        # 0) 按主题词收割法规库（会新增条目，随后由 flk_fetch 取全文）
        run("tools/harvest.py", "--commit")
    # 1) 法规库：权威文本，含题注
    run("tools/flk_fetch.py", *force)
    if "--no-web" not in sys.argv:
        # 2) 法规库没有的（部门文件、地方规范性文件）：网页检索
        run("tools/discover.py")
        run("tools/fetch_docs.py", *force)
        # 3) 正文在网页、标准在附件
        run("tools/compose_doc.py")
    # 4) 用题注回填沿革（在正文定型之后）
    run("tools/enrich_note.py")
    # 5) 兜底清洗（抓取时已按同一规则清洗过，这里保证历史文件也干净）
    run("tools/sanitize_docs.py", "--apply")
    # 6) 与磁盘对齐（并行抓取/手工搬文件后，file 字段可能脱节）
    run("tools/relink.py")
    # 7) 正文收尾：拆「标题+文号+主送机关」粘连、补日期、标「待施行」
    run("tools/fix_meta.py", "--apply")
    # 8) 派生检索维度：机关归一、适用地区、别名、主题标签
    run("tools/normalize_meta.py", "--apply")
    # 9) 修硬折行（「每 20 字断一行」会让「公平竞争」永远搜不到）
    #    硬约束：去掉空白后字符串必须完全不变，只移动空白
    run("tools/fix_wrap.py", "--apply")
    # 10) 检索索引（单元切分 + 条号直达 + 全文 blob），再重建三件套
    run("tools/build_index.py")
    run("tools/render.py")
    print("\n完成。检索自检：node tools/test_search.js")
    print("打开 index.html 即可离线检索。")
