#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
实时记忆索引器（只读）

用途：把「店铺/文件夹的真实路径」解析到 Qoder 实时记忆正本目录
      ~/.qoder-cn/projects/<编码>/memory/，供爱思办公（AgnesCode）的
      enter-project 技能调用，避免再维护一份过期的记忆备份副本。

原则：
  1. 只读。本脚本不写任何记忆文件、不改任何配置。
  2. 真路径来源 = 会话日志里那行 "workspace-directories"（一手记录），
     ⛔ 靠编码目录名反推（中文名在编码时被压成一串连字符，反推不可靠）。
  3. 目录名册由盘上现扫得出，⛔ 在脚本里写死任何项目清单。

用法：
  python3 qoder_memory_index.py list                 # 全量现扫，逐颗上纸
  python3 qoder_memory_index.py resolve <路径或关键词>  # 解析到 memory 正本目录
  python3 qoder_memory_index.py show   <路径或关键词>  # 解析 + 打印 MEMORY.md 正文
  python3 qoder_memory_index.py file   <路径或关键词> <记忆文件名>  # 打印单颗记忆文件
"""

import argparse
import datetime
import json
import os
import sys

PROJECTS_ROOT = os.path.expanduser("~/.qoder-cn/projects")
TYPE_LINE = "workspace-directories"


def encode_path(path):
    """镜像 Qoder 的目录编码：去掉首个 /，剩余 / 换成 -，非 [A-Za-z0-9._-] 换成 -。"""
    body = path.lstrip("/")
    out = []
    for ch in body:
        if ch.isascii() and (ch.isalnum() or ch in "._-"):
            out.append(ch)
        else:
            out.append("-")
    return "-" + "".join(out)


def iter_session_files(proj_dir):
    try:
        names = os.listdir(proj_dir)
    except OSError:
        return
    for name in sorted(names):
        if name.endswith(".jsonl"):
            yield os.path.join(proj_dir, name)


def real_paths_of(proj_dir, max_files=None):
    """从会话日志里刨出一手真路径；返回 {路径: 出现次数}。"""
    counts = {}
    files = list(iter_session_files(proj_dir))
    if max_files:
        files = files[-max_files:]
    for fp in files:
        try:
            with open(fp, "r", encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    if not line.startswith('{"type":"' + TYPE_LINE):
                        continue
                    try:
                        rec = json.loads(line)
                    except ValueError:
                        continue
                    for d in rec.get("directories") or []:
                        counts[d] = counts.get(d, 0) + 1
                    break
        except OSError:
            continue
    return counts


def memory_stats(mem_dir):
    """数记忆文件颗数 + 最新改动时间（只读扫）。"""
    n = 0
    latest = 0
    latest_name = ""
    if not os.path.isdir(mem_dir):
        return None
    for root, _dirs, fnames in os.walk(mem_dir):
        for fn in fnames:
            if not fn.endswith(".md"):
                continue
            n += 1
            p = os.path.join(root, fn)
            try:
                m = os.path.getmtime(p)
            except OSError:
                continue
            if m > latest:
                latest = m
                latest_name = fn
    stamp = (
        datetime.datetime.fromtimestamp(latest).strftime("%Y-%m-%d %H:%M")
        if latest
        else "(空)"
    )
    return {"count": n, "latest": stamp, "latest_name": latest_name}


def build_index():
    """现扫盘上目录，得出名册。返回按真路径条数排序的列表。"""
    rows = []
    if not os.path.isdir(PROJECTS_ROOT):
        return rows
    for name in sorted(os.listdir(PROJECTS_ROOT)):
        proj = os.path.join(PROJECTS_ROOT, name)
        if not os.path.isdir(proj):
            continue
        mem_dir = os.path.join(proj, "memory")
        stats = memory_stats(mem_dir)
        paths = real_paths_of(proj)
        best = max(paths.items(), key=lambda kv: kv[1]) if paths else ("(日志里没有工作区记录)", 0)
        rows.append(
            {
                "encoded": name,
                "real": best[0],
                "all_real": sorted(paths.keys()),
                "ambiguity": len(paths),
                "has_memory": stats is not None,
                "mem_dir": mem_dir if stats else "",
                "count": stats["count"] if stats else 0,
                "latest": stats["latest"] if stats else "-",
                "latest_name": stats["latest_name"] if stats else "-",
            }
        )
    rows.sort(key=lambda r: (not r["has_memory"], r["real"]))
    return rows


def find_one(rows, query):
    """按真路径 / 编码名 / 关键词解析；返回命中列表。"""
    q = query.strip()
    ql = q.lower()
    # 1) 精确：真路径
    hits = [r for r in rows if r["real"] == q]
    if hits:
        return hits
    # 2) 精确：编码目录名
    hits = [r for r in rows if r["encoded"] == q or r["encoded"] == encode_path(q)]
    if hits:
        return hits
    # 3) 前缀：真路径（父目录下的店）
    hits = [r for r in rows if r["real"].startswith(q.rstrip("/") + "/")]
    if hits:
        return hits
    # 4) 子串：真路径或候选真路径全集
    hits = [r for r in rows if ql in r["real"].lower() or any(ql in p.lower() for p in r["all_real"])]
    return hits


def cmd_list(args):
    rows = build_index()
    today = datetime.date.today().isoformat()
    with_mem = [r for r in rows if r["has_memory"]]
    total_files = sum(r["count"] for r in with_mem)
    print("# 实时记忆正本现扫（只读）")
    print("# 正本根目录 = " + PROJECTS_ROOT)
    print(
        "# 目录=%d 颗・有 memory 的=%d 颗・里面记忆 .md 共=%d 颗・最新改动在今天的=%d 颗・今天=%s"
        % (
            len(rows),
            len(with_mem),
            total_files,
            sum(1 for r in with_mem if r["latest"].startswith(today)),
            today,
        )
    )
    print()
    print("| 真实路径 | 记忆文件数 | 最新改动 | 最新那颗 | 编码目录 |")
    print("| --- | --- | --- | --- | --- |")
    for r in with_mem:
        note = ""
        if r["ambiguity"] > 1:
            note = " ⚠名册里还见过 %d 个其他工作区" % (r["ambiguity"] - 1)
        print(
            "| %s%s | %d | %s | %s | %s |"
            % (r["real"], note, r["count"], r["latest"], r["latest_name"], r["encoded"])
        )
    print()
    print("# 以下 %d 颗目录没有 memory 子目录（＝那棵树还没写过项目记忆）：" % (len(rows) - len(with_mem)))
    for r in rows:
        if not r["has_memory"]:
            print("#   %s | %s" % (r["real"], r["encoded"]))
    return 0


def collision_lines(r, asked=None):
    """编码撞车提示：同一个记忆目录被几棵工作区共用（一字一杠的编码会压平）。"""
    if r["ambiguity"] <= 1:
        return []
    keep = asked or r["real"]
    others = [p for p in r["all_real"] if p.rstrip("/") != keep.rstrip("/")]
    out = [
        "⚠ 共用提醒：编码目录 %s 里见过 %d 个工作区（中文在编码时被压成连字符，不同路径会撞进同一个目录）。"
        % (r["encoded"], r["ambiguity"]),
        "   同一个 memory 正本还挂着：%s" % "、".join(sorted(others)),
        "   ⇒ 读到的条目里凡是讲这些树的，⛔当本树的家规用；先按条目里写的工作区路径认领，认不出源的只当参考。",
    ]
    return out


def _pick_asked(r, query):
    """命中多棵树共用同一正本时，把头图标成爸要的那一棵，⛔一律印「出现最多」那棵。"""
    q = query.strip().rstrip("/")
    for p in r["all_real"]:
        if p.rstrip("/") == q:
            return p, "逐字对上"
    ql = q.lower()
    for p in r["all_real"]:
        if ql in p.lower():
            return p, "关键词对上"
    return r["real"], "该正本里出现最多的一棵（查询没对上具体名）"


def _resolve_or_exit(query):
    rows = build_index()
    hits = find_one(rows, query)
    usable = [r for r in hits if r["has_memory"]]
    if not usable:
        print("没找到：%s（正本里没有带记忆的工作区对上这个名）" % query)
        print("可用名册请跑：python3 %s list" % os.path.basename(sys.argv[0]))
        sys.exit(2)
    if len(usable) > 1:
        print("命中 %d 颗，不确定你要哪一颗，请给更完整的路径：" % len(usable))
        for r in usable:
            print("  %s → %s（记忆 %d 颗）" % (r["real"], r["mem_dir"], r["count"]))
        sys.exit(3)
    r = usable[0]
    asked, how = _pick_asked(r, query)
    return r, asked, how


def cmd_resolve(args):
    r, asked, how = _resolve_or_exit(args.query)
    print("# 认领的工作区 = " + asked + "（%s）" % how)
    print("# 记忆正本 = " + r["mem_dir"])
    print("# 记忆文件 = %d 颗・最新改动 = %s・最新那颗 = %s" % (r["count"], r["latest"], r["latest_name"]))
    print("# 一手来源 = %s 的会话日志里 %s 那行（现扫，非缓存）" % (r["encoded"], TYPE_LINE))
    for line in collision_lines(r, asked):
        print("# " + line)
    print(r["mem_dir"])
    return 0


def cmd_show(args):
    r, asked, how = _resolve_or_exit(args.query)
    index_file = os.path.join(r["mem_dir"], "MEMORY.md")
    print("# 认领的工作区 = " + asked + "（%s）" % how)
    print("# 正本 = " + index_file)
    print("# 现量：记忆文件 %d 颗・最新改动 %s・最新那颗 %s" % (r["count"], r["latest"], r["latest_name"]))
    for line in collision_lines(r, asked):
        print("# " + line)
    print("# 本脚本只读，未改动上述任何文件")
    print()
    if not os.path.isfile(index_file):
        print("（这棵树的正本里还没有 MEMORY.md 索引件，只有下列分颗：）")
        for root, _d, fs in os.walk(r["mem_dir"]):
            for f in sorted(fs):
                print("  " + os.path.relpath(os.path.join(root, f), r["mem_dir"]))
        return 1
    size = os.path.getsize(index_file)
    with open(index_file, "r", encoding="utf-8", errors="replace") as fh:
        body = fh.read()
    print(body)
    print()
    print("# （以上 %d 字节，读自 %s）" % (size, os.path.basename(index_file)))
    return 0


def cmd_file(args):
    r, asked, how = _resolve_or_exit(args.query)
    target = None
    for root, _d, fs in os.walk(r["mem_dir"]):
        for f in fs:
            if f == args.name or f.startswith(args.name):
                target = os.path.join(root, f)
                break
        if target:
            break
    if not target:
        print("没找到记忆文件：%s（在那棵树的正本里）" % args.name)
        print("该正本现有：")
        for root, _d, fs in os.walk(r["mem_dir"]):
            for f in sorted(fs):
                print("  " + f)
        return 2
    print("# 文件 = " + target)
    print("# 改动时间 = " + datetime.datetime.fromtimestamp(os.path.getmtime(target)).strftime("%Y-%m-%d %H:%M"))
    print("# 认领的工作区 = " + asked + "（%s）" % how)
    for line in collision_lines(r, asked):
        print("# " + line)
    print()
    with open(target, "r", encoding="utf-8", errors="replace") as fh:
        print(fh.read())
    return 0


def cmd_check(args):
    """自测腿：三条正例 + 三条负控，全绿才退 0。只读，⛔写任何文件。"""
    fails = []
    rows = build_index()
    with_mem = [r for r in rows if r["has_memory"]]

    # 正例 1：名册自洽——拿某颗正本的「真路径」回头解析，必须指回同一颗目录
    here = os.path.expanduser("~/.qoder-cn/projects")
    sample = next((r for r in with_mem if len(r["all_real"]) == 1), None)
    if sample is None:
        fails.append("正例1 落空：名册里没有「只见过一个工作区」的可核对样本")
    else:
        back = find_one(rows, sample["real"])
        back_ok = [x for x in back if x["has_memory"] and x["encoded"] == sample["encoded"]]
        if not back_ok:
            fails.append(
                "正例1 打架：%s 解析到 %s，回头解析却没指回同一颗" % (sample["real"], sample["encoded"])
            )
        else:
            print("自洽核对：%s ⇄ %s（真路径↔编码目录互指一致）" % (sample["real"], sample["encoded"]))

    # 正例 1 附：爸给了工作区（--workspace），就必须能解析出正本
    if args.workspace:
        hit = find_one(rows, args.workspace)
        usable = [r for r in hit if r["has_memory"]]
        if not usable:
            fails.append("正例1附 落空：工作区 %s 没解析到记忆正本" % args.workspace)
        elif not os.path.isdir(usable[0]["mem_dir"]):
            fails.append("正例1附 假绿：解析出的正本目录不在盘上：%s" % usable[0]["mem_dir"])

    # 正例 2：名册颗数 = 盘上现扫颗数（⛔脚本里写死名单）
    disk = sum(1 for n in os.listdir(here) if os.path.isdir(os.path.join(here, n)))
    if len(rows) != disk:
        fails.append("正例2 打架：脚本扫到 %d 颗，盘上 %d 颗" % (len(rows), disk))
    print("现扫：目录 %d 颗・其中有记忆正本 %d 颗（盘上核对 %d 颗）" % (len(rows), len(with_mem), disk))

    # 正例 3：每颗解析出的正本目录，MEMORY.md 或分颗文件至少读到一行内容
    checked = 0
    for r in with_mem:
        names = [f for f in os.listdir(r["mem_dir"]) if f.endswith(".md")] if os.path.isdir(r["mem_dir"]) else []
        if not names:
            fails.append("正例3 空正本：%s" % r["mem_dir"])
        else:
            first = os.path.join(r["mem_dir"], names[0])
            with open(first, "r", encoding="utf-8", errors="replace") as fh:
                if not fh.readline().strip():
                    fails.append("正例3 读到空件：%s" % first)
        checked += 1

    # 负控 1：不存在的查询必须非 0 退，⛔静默给别树正本
    import subprocess

    rc = subprocess.run(
        [sys.executable, os.path.abspath(__file__), "resolve", "这条路面上绝无可能有 ZZTOP"],
        capture_output=True,
        text=True,
    ).returncode
    if rc == 0:
        fails.append("负控1 失效：乱查询居然退 0（该退 2）")

    # 负控 2：多义查询必须非 0 退，⛔替调用方挑一棵
    rc2 = subprocess.run(
        [sys.executable, os.path.abspath(__file__), "resolve", "Desktop"],
        capture_output=True,
        text=True,
    ).returncode
    if rc2 == 0:
        fails.append("负控2 失效：宽查询退 0（该退 3＝命中多颗要人挑）")

    # 负控 3：只读证明——跑完前后正本根的 mtime 清单一字不动
    def snap():
        out = []
        for n in sorted(os.listdir(here)):
            p = os.path.join(here, n)
            if os.path.isdir(p):
                out.append((n, os.path.getmtime(p)))
        return out

    before = snap()
    build_index()
    if snap() != before:
        fails.append("负控3 失效：现扫把目录 mtime 改了（本脚本应纯只读）")

    print("自测跑数：正本核对 %d 颗・负控 3 条" % checked)
    if fails:
        print("不通过 %d 条：" % len(fails))
        for f in fails:
            print("  ✗ " + f)
        return 1
    print("全绿：%d 条正例 + 3 条负控都过（本脚本对记忆正本只读，未写任何文件）" % (3,))
    return 0


def main():
    ap = argparse.ArgumentParser(description="实时记忆索引器（只读）")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("list", help="全量现扫名册")
    p1 = sub.add_parser("resolve", help="解析到记忆正本目录")
    p1.add_argument("query")
    p2 = sub.add_parser("show", help="解析并打印 MEMORY.md 索引")
    p2.add_argument("query")
    p3 = sub.add_parser("file", help="打印单颗记忆文件")
    p3.add_argument("query")
    p3.add_argument("name")
    c = sub.add_parser("check", help="自测腿：正例＋负控，全绿退 0")
    c.add_argument("--workspace", default="", help="可选：指定工作区，验它能解析到正本")
    args = ap.parse_args()
    if args.cmd == "list":
        return cmd_list(args)
    if args.cmd == "resolve":
        return cmd_resolve(args)
    if args.cmd == "show":
        return cmd_show(args)
    if args.cmd == "file":
        return cmd_file(args)
    if args.cmd == "check":
        return cmd_check(args)
    if args.cmd == "check":
        return cmd_check(args)
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
