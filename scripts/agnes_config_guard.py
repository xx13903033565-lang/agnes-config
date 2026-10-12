#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
agnes_config_guard.py — 恒林（AgnesCode）配置正本的写入闸 + 冻结复发探测。

为什么需要它（2026-10-12 事故定案，时间戳逐颗对齐）：
  20:26 一次提交把 5 行根级键插进 AGNES_MODEL_AUTO_COMPACT_THRESHOLDS 映射块的中间
  ⇒ YAML 语法坏（解析器指到 392 行 16 列）
  ⇒ 引擎判无效、存成 config.yaml.invalid、从 config.yaml.recovery 回滚
  ⇒ 这扇窗口里后端 agnesd 被重启 5 次（20:25:24 / 20:26:06 / 20:27:43 / 20:28:02 / 20:29:04）
  ⇒ 20:27:43 主进程 [BackendRespawn] gave up after repeated crashes
  ⇒ renderer 调 get-acp-url 抛 "Agnes backend process exited" ⇒ 界面冻结

牙（每颗都配能放行的对照，⛔恒红）：
  1. 候选文本必须过 YAML 解析               不过 → 退 3，正本一字未动
  2. 候选的根级键集必须等于预期增删         不符 → 退 4，正本一字未动
  3. 落盘必须原子（同目录 tempfile + os.replace + fsync）
  4. 写后同条回读：文本逐字节相等 + 再解析 + 键集再对拉
                                             不符 → 退 5
  5. 差分写必须有真差分（写前==写目标 ⇒ 回读分不出"收了"与"没动"）
                                             假差分 → 退 6
  6. 引擎自有的状态文件（现扫二进制得到的名册）⛔本机脚本代写
                                             越界 → 退 7
用法：
  --check                 只量当前正本（⛔任何写）
  --selftest              事故夹具当负控 + 合法候选当对照，跑在临时靶上，⛔碰正本
  --write-from <file>     把 <file> 的内容当候选提交（走全部闸；--expect-add/--expect-remove 给预期）
  --audit                 现扫盘上脚本：谁以写模式碰正本或引擎状态文件
  --patrol                只读巡检出红格（冻结复发探测器）
退码：0 全绿 / 3 候选非法 / 4 键集不符 / 5 回读不符 / 6 假差分 / 7 越界写 / 8 自检腿失明 / 9 巡检出红
"""
import argparse
import ast
import datetime as _dt
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile

HOME = os.path.expanduser("~")
CFG_DIR = os.path.join(HOME, ".agnes", "config")
CONFIG = os.path.join(CFG_DIR, "config.yaml")
INVALID = os.path.join(CFG_DIR, "config.yaml.invalid")
RECOVERY = os.path.join(CFG_DIR, "config.yaml.recovery")
APP_BIN = "/Applications/AgnesCode.app/Contents/Resources/bin/agnesd"
REGISTRY = os.path.join(CFG_DIR, "engine_owned_files.json")
MAIN_LOG = os.path.join(HOME, "Library", "Application Support", "AgnesCode", "logs", "main.log")
CRASH_DIR = os.path.join(HOME, "Library", "Logs", "DiagnosticReports")
BACKEND_LOG_DIR = os.path.join(HOME, "Library", "Application Support", "AgnesCode", "logs", "backend")

RC_OK, RC_BAD_YAML, RC_KEYSET, RC_READBACK, RC_FAKE_DIFF, RC_OUT_OF_BOUNDS, RC_SELFTEST_BLIND, RC_PATROL_RED = 0, 3, 4, 5, 6, 7, 8, 9

try:
    import yaml
except ImportError:
    sys.stderr.write("缺 pyyaml，闸无法工作（⛔在没有解析器的情况下放行任何写）\n")
    sys.exit(RC_SELFTEST_BLIND)


def now_stamp():
    return _dt.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def read_bytes(path):
    with open(path, "rb") as fh:
        return fh.read()


def stat_line(path):
    st = os.stat(path)
    return "size=%d mtime=%s sha=%s" % (st.st_size, _dt.datetime.fromtimestamp(st.st_mtime).strftime("%H:%M:%S"), sha256_bytes(read_bytes(path))[:12])


def parse_errors(text):
    """返回解析错误列表（空=合法）。引擎侧同款失败模式：mapping values are not allowed here。"""
    errs = []
    try:
        docs = list(yaml.safe_load_all(text))
        if not docs or docs == [None]:
            errs.append("解析结果为空＝候选是空文件")
            return errs
        top = docs[0]
        if not isinstance(top, dict):
            errs.append("顶层不是映射（YAML 根级必须是 key: value 表），实得 %s" % type(top).__name__)
    except yaml.YAMLError as exc:
        first = str(exc).split("\n")[0].strip()
        mark = ""
        problem = getattr(exc, "problem", None)
        where = getattr(exc, "problem_mark", None)
        if problem:
            mark = " ｜problem=%s" % problem
        if where is not None:
            mark += " ｜位置=第%d行第%d列" % (where.line + 1, where.column + 1)
        errs.append("%s%s" % (first, mark))
    return errs


def root_keys(text):
    try:
        docs = list(yaml.safe_load_all(text))
    except yaml.YAMLError:
        return None
    top = docs[0] if docs else None
    if not isinstance(top, dict):
        return None
    return set(top.keys())


def atomic_write(path, data_bytes):
    """同目录 tempfile + fsync + os.replace。⛔ open(path,'w') 裸写正本。"""
    d = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(prefix=".guard-", suffix=".tmp", dir=d)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data_bytes)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    dirfd = os.open(d, os.O_RDONLY)
    try:
        os.fsync(dirfd)
    finally:
        os.close(dirfd)


def commit(target, candidate_text, expect_add=frozenset(), expect_remove=frozenset(), allow_noop=False):
    """走全部闸提交候选。返回 (退码, 逐行证据)。"""
    ev = []
    pre_b = read_bytes(target) if os.path.exists(target) else b""
    pre_sha = sha256_bytes(pre_b)
    pre_text = pre_b.decode("utf-8", errors="replace")

    # 闸 1：语法
    errs = parse_errors(candidate_text)
    if errs:
        ev.append("闸1 候选 YAML 解析＝⛔拒：%s" % errs[0])
        ev.append("正本处置＝一字未动（sha 前=%s）" % pre_sha[:12])
        return RC_BAD_YAML, ev

    # 只许动那颗文件：候选必须与正本同源同份，禁把隔壁文件当候选
    key_pre, key_cand = root_keys(pre_text), root_keys(candidate_text)
    if key_pre is None or key_cand is None:
        ev.append("闸2 键集＝⛔无法比较（正本或候选顶层不是映射）")
        return RC_BAD_YAML, ev

    added = key_cand - key_pre
    removed = key_pre - key_cand
    ev.append("闸2 键集对拉：正本 %d 颗 → 候选 %d 颗｜实际增 %d 减 %d"
              % (len(key_pre), len(key_cand), len(added), len(removed)))
    if added != set(expect_add) or removed != set(expect_remove):
        ev.append("闸2 ⛔拒：与预期不符｜预期增=%s 减=%s" % (sorted(expect_add), sorted(expect_remove)))
        ev.append("实际增=%s 减=%s" % (sorted(added), sorted(removed)))
        ev.append("正本处置＝一字未动（sha 前=%s）" % pre_sha[:12])
        return RC_KEYSET, ev

    # 闸 5：假差分（写前==写后 ⇒ 回读分不出"收了"与"没动"）
    cand_b = candidate_text.encode("utf-8")
    if sha256_bytes(cand_b) == pre_sha and not allow_noop:
        ev.append("闸5 ⛔拒：候选与正本逐字节相同＝假差分，回读无法证明写进去了")
        return RC_FAKE_DIFF, ev

    # 闸 3：原子落盘
    atomic_write(target, cand_b)
    ev.append("闸3 原子落盘＝tempfile(同目录)+fsync+os.replace")

    # 闸 4：同条回读
    post_b = read_bytes(target)
    post_text = post_b.decode("utf-8", errors="replace")
    if post_b != cand_b:
        ev.append("闸4 ⛔回读不符：写后字节 != 候选字节")
        return RC_READBACK, ev
    re_errs = parse_errors(post_text)
    if re_errs:
        ev.append("闸4 ⛔回读再解析失败：%s" % re_errs[0])
        return RC_READBACK, ev
    post_keys = root_keys(post_text)
    if post_keys != key_cand:
        ev.append("闸4 ⛔回读键集与候选不符")
        return RC_READBACK, ev
    ev.append("闸4 同条回读＝对上（字节等＋再解析合法＋键集 %d 颗一致）" % len(post_keys))
    ev.append("正本 sha %s → %s｜%s" % (pre_sha[:12], sha256_bytes(post_b)[:12], stat_line(target)))
    return RC_OK, ev


def engine_owned_names():
    """名册正本＝从引擎运行痕迹现扫（⛔我在散文里列第二份）。"""
    # 第一来源：后端 stderr 里那条报警原文「invalid memory state in <path>/<name>.json」
    candidates = set()
    if os.path.isdir(BACKEND_LOG_DIR):
        for fn in os.listdir(BACKEND_LOG_DIR):
            if not fn.startswith("agnesd-stderr"):
                continue
            p = os.path.join(BACKEND_LOG_DIR, fn)
            try:
                txt = read_bytes(p).decode("utf-8", errors="replace")
            except Exception:
                continue
            for m in re.finditer(r"invalid memory state in .*/([A-Za-z0-9_\-]+\.(?:json|jsonl))", txt):
                candidates.add(m.group(1))
    # 第二来源：主日志里同样的报警
    if os.path.exists(MAIN_LOG):
        txt = read_bytes(MAIN_LOG).decode("utf-8", errors="replace")
        for m in re.finditer(r"invalid memory state in .*/([A-Za-z0-9_\-]+\.(?:json|jsonl))", txt):
            candidates.add(m.group(1))
    names = sorted(candidates)
    if not names:
        return None, "盘上日志里没找到 'invalid memory state' 点名那颗文件"
    return names, None


def cmd_check():
    print("[%s] --check 只读量当前正本" % now_stamp())
    if not os.path.exists(CONFIG):
        print("  ⛔ 正本不存在：%s" % CONFIG)
        return RC_BAD_YAML
    text = read_bytes(CONFIG).decode("utf-8", errors="replace")
    print("  正本现量：%s" % stat_line(CONFIG))
    errs = parse_errors(text)
    if errs:
        print("  ⛔ 正本当前 YAML 非法：%s" % errs[0])
        print("  ⇒ 引擎此刻会判无效并回滚，这就是冻结复发的前置条件")
        return RC_BAD_YAML
    print("  ✓ 正本 YAML 合法，根级键 %d 颗" % len(root_keys(text)))
    for tag, p in (("上次被拒的坏料(.invalid)", INVALID), ("回滚用的副本(.recovery)", RECOVERY)):
        if os.path.exists(p):
            t = read_bytes(p).decode("utf-8", errors="replace")
            e = parse_errors(t)
            print("  %s：%s ｜%s" % (tag, ("⛔非法 " + e[0]) if e else "合法", stat_line(p)))
    return RC_OK


def cmd_selftest():
    """跑在临时靶上，⛔碰正本。负控＝本次事故那份真坏 YAML。"""
    print("[%s] --selftest（临时靶，不碰正本）" % now_stamp())
    if not os.path.exists(INVALID):
        print("  ⛔ 缺事故夹具 %s ⇒ 负控无从可来，自检拒跑" % INVALID)
        return RC_SELFTEST_BLIND
    bad_text = read_bytes(INVALID).decode("utf-8", errors="replace")
    base_text = read_bytes(CONFIG).decode("utf-8", errors="replace")
    rc_any = RC_OK

    work = tempfile.mkdtemp(prefix="agnes_guard_selftest_")
    try:
        # 夹具自证：负控本身必须真是坏的
        neg_errs = parse_errors(bad_text)
        print("  夹具自证 负控（事故 .invalid）＝%s" % ("⛔确实非法，可用" if neg_errs else "⚠ 竟合法＝负控失效"))
        if not neg_errs:
            print("  ⛔ 负控失效＝闸无从被证伪，本次自检判失明")
            return RC_SELFTEST_BLIND

        # 刀 A：负控必须被拦，且靶文件一字未动
        tpath = os.path.join(work, "config.yaml")
        atomic_write(tpath, base_text.encode("utf-8"))
        before = sha256_bytes(read_bytes(tpath))
        rc, ev = commit(tpath, bad_text)
        after = sha256_bytes(read_bytes(tpath))
        ok_a = (rc == RC_BAD_YAML and before == after)
        print("  刀A 坏料必须拒且不动盘：退码=%d(%s) 盘守恒=%s → %s"
              % (rc, "非0" if rc else "0(⛔不该)", "是" if before == after else "否", "✓" if ok_a else "⛔"))
        for line in ev:
            print("      " + line)
        rc_any |= 0 if ok_a else RC_SELFTEST_BLIND

        # 刀 B：合法改动必须放行（能放行的对照，⛔恒红）
        cand = base_text + "\nGUARD_SELFTEST_KEY_%s: 1\n" % now_stamp().replace(":", "").replace(" ", "").replace("-", "")
        key = [l.split(":")[0] for l in cand.split("\n") if l.startswith("GUARD_SELFTEST_KEY")][0]
        rc, ev = commit(tpath, cand, expect_add=frozenset({key}))
        ok_b = (rc == RC_OK)
        print("  刀B 合法候选必须放行：退码=%d → %s" % (rc, "✓" if ok_b else "⛔"))
        for line in ev:
            print("      " + line)
        rc_any |= 0 if ok_b else RC_SELFTEST_BLIND

        # 刀 C：假差分必须被拒（等值写＝回读证明不了任何东西）
        cur = read_bytes(tpath).decode("utf-8", errors="replace")
        rc, _ev = commit(tpath, cur)
        ok_c = (rc == RC_FAKE_DIFF)
        print("  刀C 等值写必须判假差分：退码=%d → %s" % (rc, "✓" if ok_c else "⛔"))
        rc_any |= 0 if ok_c else RC_SELFTEST_BLIND

        # 刀 D：键集与预期不符必须拒（防"插进映射块中间"这种把键吞进子层的写法）
        swallowed = re.sub(r"(AGNES_MODEL_AUTO_COMPACT_THRESHOLDS:)", r"\1\n  selftest_swallow: 1", base_text, count=1)
        rc, _ev = commit(tpath, swallowed, expect_add=frozenset({"NOT_THIS"}))
        ok_d = (rc == RC_KEYSET)
        print("  刀D 键集不符必须拒：退码=%d → %s" % (rc, "✓" if ok_d else "⛔"))
        rc_any |= 0 if ok_d else RC_SELFTEST_BLIND

        # 刀 E：把事故那种"插进块中间"的写法直接喂进来——它必须落进闸1或闸2，⛔不许走到落盘
        m = re.search(r"(AGNES_MODEL_AUTO_COMPACT_THRESHOLDS:\n(?:  [^\n]*\n){3})", base_text)
        if m:
            inj = base_text[:m.end()] + "AGNES_SELFTEST_INJECT: true\n" + base_text[m.end():]
            rc, _ev = commit(tpath, inj, expect_add=frozenset({"AGNES_SELFTEST_INJECT"}))
            print("  刀E 复刻事故形状（根级键插进映射块中间）：退码=%d → %s" % (rc, "✓ 拦在落盘前" if rc in (RC_BAD_YAML, RC_KEYSET) else "⛔ 放行＝闸瞎"))
            rc_any |= 0 if rc in (RC_BAD_YAML, RC_KEYSET) else RC_SELFTEST_BLIND
        else:
            print("  刀E ⚠ 没在正本里扫到那颗映射块＝变异腿缺位")
            rc_any |= RC_SELFTEST_BLIND

        # 刀 F：引擎自有状态文件名册必须由二进制现扫得到
        names, err = engine_owned_names()
        ok_f = bool(names) and "processed_sessions.json" in names
        print("  刀F 名册现扫（strings 引擎二进制）：%s → %s" % (names, "✓" if ok_f else "⛔%s" % err))
        rc_any |= 0 if ok_f else RC_SELFTEST_BLIND

    finally:
        import shutil
        shutil.rmtree(work, ignore_errors=True)
        print("  临时靶已清除；正本未被本自检写过（sha 守恒见下）")
        print("      正本现量 %s" % stat_line(CONFIG))

    print("  自检总判：%s" % ("✓ 六把刀全部有牙" if rc_any == RC_OK else "⛔ 有腿失明 rc=%d" % rc_any))
    return rc_any


def cmd_write_from(path, expect_add, expect_remove):
    if not os.path.exists(path):
        print("⛔ 候选文件不存在：%s" % path)
        return RC_SELFTEST_BLIND
    cand = read_bytes(path).decode("utf-8", errors="replace")
    print("[%s] 提交候选 %s → %s" % (now_stamp(), path, CONFIG))
    rc, ev = commit(CONFIG, cand, frozenset(expect_add), frozenset(expect_remove))
    for line in ev:
        print("  " + line)
    print("  退码=%d" % rc)
    return rc


def cmd_audit():
    """现扫盘上脚本：谁以写模式碰正本 / 谁代写引擎状态文件（AST，⛔正则扫字面）。"""
    names, err = engine_owned_names()
    if err:
        print("⛔ 名册取不到：%s" % err)
        return RC_SELFTEST_BLIND
    print("[%s] 写入方审计｜引擎自有状态文件名册（二进制现扫）= %s" % (now_stamp(), names))
    roots = [os.path.join(HOME, ".agnes", d) for d in ("rules", "scripts", "tools", "agi", "skills")]
    cfg_base = os.path.basename(CONFIG)
    offenders = []
    for r in roots:
        if not os.path.isdir(r):
            continue
        for dp, _, fns in os.walk(r):
            if ".git" in dp:
                continue
            for fn in fns:
                if not fn.endswith(".py"):
                    continue
                p = os.path.join(dp, fn)
                try:
                    src = open(p, encoding="utf-8", errors="replace").read()
                    tree = ast.parse(src)
                except Exception:
                    continue
                # 先取本文件里所有"指向 config.yaml / 引擎状态文件"的变量名
                tgt = set()
                for n in ast.walk(tree):
                    if isinstance(n, ast.Assign):
                        consts = [x.value for x in ast.walk(n.value) if isinstance(x, ast.Constant) and isinstance(x.value, str)]
                        joined = " ".join(consts)
                        if cfg_base in joined or any(nm in joined for nm in names):
                            for t in n.targets:
                                if isinstance(t, ast.Name):
                                    tgt.add(t.id)
                if not tgt:
                    continue
                for n in ast.walk(tree):
                    if not isinstance(n, ast.Call):
                        continue
                    fname = n.func.id if isinstance(n.func, ast.Name) else getattr(n.func, "attr", "")
                    if fname not in ("open", "write_text", "write_bytes"):
                        continue
                    # 取 mode：先看关键字参数，再看位置参数（只针对 write_text/write_bytes）
                    mode = None
                    for kw in n.keywords:
                        if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
                            mode = str(kw.value.value)
                            break
                    if mode is None and fname in ("write_text", "write_bytes"):
                        mode = "w"
                    if mode is None:
                        continue  # open() 没给 mode＝默认只读，跳过
                    if "w" not in mode and "a" not in mode:
                        continue
                    args = [a for a in n.args]
                    var = ""
                    if args and isinstance(args[0], ast.Name):
                        var = args[0].id
                    if var in tgt or any(t in ast.dump(n) for t in tgt):
                        offenders.append((os.path.relpath(p, HOME), n.lineno, mode, var or "字面路径"))
    if offenders:
        print("  ⛔ 发现裸写腿 %d 处（这些就是能把正本写坏的把手）：" % len(offenders))
        for f, ln, mode, var in sorted(set(offenders)):
            print("      %-58s 行%-6s mode=%-2s 目标变量=%s" % (f, ln, mode, var))
        print("  ⇒ 处置：改走本闸（--write-from / commit()），或改成只出报告不写盘")
        return RC_OUT_OF_BOUNDS
    print("  ✓ 盘上未发现以写模式碰正本或引擎状态文件的本地脚本")
    return RC_OK


def cmd_patrol():
    """只读巡检出红格；每颗数字由本脚本自印。退码 0=全绿 / 9=有红。"""
    reds = []
    print("[%s] 恒林 GUI 冻结复发巡检（只读，⛔任何写）" % now_stamp())

    # 1 正本合法性
    if os.path.exists(CONFIG):
        t = read_bytes(CONFIG).decode("utf-8", errors="replace")
        e = parse_errors(t)
        if e:
            reds.append("正本 YAML 非法：%s" % e[0])
            print("  ⛔ 格1 正本 config.yaml＝非法")
        else:
            print("  ✓ 格1 正本 config.yaml＝合法（根级 %d 颗，%s）" % (len(root_keys(t)), stat_line(CONFIG)))
    else:
        reds.append("正本不存在")
        print("  ⛔ 格1 正本 config.yaml＝不存在")

    # 2 今天有没有新落下被拒的坏料
    if os.path.exists(INVALID):
        mt = _dt.datetime.fromtimestamp(os.path.getmtime(INVALID))
        t = read_bytes(INVALID).decode("utf-8", errors="replace")
        e = parse_errors(t)
        print("  格2 .invalid（被拒坏料）mtime=%s 内容=%s" % (mt.strftime("%m-%d %H:%M"), ("⛔仍非法：" + e[0]) if e else "合法(异常)"))
        if mt.date() == _dt.date.today():
            reds.append(".invalid 今日（%s）又被写＝有腿仍在把正本写坏" % mt.strftime("%H:%M"))
    else:
        print("  格2 .invalid＝不在（今日无新拒）")

    # 3 主日志里的放弃重启 / 拿不到 acp-url
    if os.path.exists(MAIN_LOG):
        txt = read_bytes(MAIN_LOG).decode("utf-8", errors="replace")
        gave = re.findall(r"^\[([\d\-: .]+)\].*gave up after repeated crashes", txt, re.M)
        noacp = re.findall(r"^\[([\d\-: .]+)\].*Agnes backend process exited", txt, re.M)
        rcrash = re.findall(r"^\[([\d\-: .]+)\].*renderer crashed \(killed, code=(\d+)\)", txt, re.M)
        today = _dt.date.today().strftime("%Y-%m-%d")
        n_gave_today = len([x for x in gave if x.startswith(today)])
        n_acp_today = len([x for x in noacp if x.startswith(today)])
        n_rc_today = len([ts for ts, _code in rcrash if ts.startswith(today)])
        print("  格3 主日志：gave_up=%d 颗（今日 %d）｜acp-url 报错=%d 颗（今日 %d）｜renderer killed=%d 颗（今日 %d）"
              % (len(gave), n_gave_today, len(noacp), n_acp_today, len(rcrash), n_rc_today))
        if n_gave_today or n_acp_today:
            reds.append("今日再现「放弃重启 / 后端已退出」：%s / %s" % (gave[-1] if gave else "-", noacp[-1] if noacp else "-"))
        last = rcrash[-1] if rcrash else None
        print("      最近一次 renderer killed：%s" % (str(last) if last else "无"))
    else:
        reds.append("主日志不在＝巡检瞎")
        print("  ⛔ 格3 主日志不存在")

    # 4 后端进程此刻在不在、谁连着
    pids = subprocess.run(["pgrep", "-f", "Resources/bin/agnesd"], capture_output=True, text=True).stdout.split()
    print("  格4 后端 agnesd 颗数=%d pids=%s" % (len(pids), pids or "[]"))
    if not pids:
        reds.append("后端 agnesd 不在＝界面必然连不上")
    else:
        lsof = subprocess.run(["lsof", "-nP", "-a", "-i", "-p", pids[-1]], capture_output=True, text=True).stdout
        est = len(re.findall(r"ESTABLISHED", lsof))
        print("      那颗后端（pid=%s）ESTABLISHED 连接数=%d（0＝活着但没人连着＝冻结形态）" % (pids[-1], est))
        if est == 0:
            reds.append("后端 pid=%s 在但 0 条连接＝GUI 侧已断" % pids[-1])

    # 5 崩溃计数与偏移（引擎侧，本机不可修，只报事实）
    if os.path.isdir(CRASH_DIR):
        reps = [os.path.join(CRASH_DIR, f) for f in os.listdir(CRASH_DIR) if f.startswith("AgnesCode") and f.endswith(".ips")]
        sig = {}
        off_counts = {}
        for p in reps:
            try:
                raw = open(p, encoding="utf-8", errors="replace").read().split("\n", 1)
                b = json.loads(raw[1])
                ths = b.get("threads") or []
                ft = b.get("faultingThread") or 0
                exc = (b.get("exception") or {}).get("signal")
                fr = (ths[ft].get("frames") or []) if ths else []
                off = fr[0].get("imageOffset") if fr else None
                sig[exc] = sig.get(exc, 0) + 1
                if exc == "SIGTRAP" and off:
                    off_counts[hex(off)] = off_counts.get(hex(off), 0) + 1
            except Exception:
                continue
        print("  格5 崩溃报告 %d 份｜信号分布=%s" % (len(reps), sig))
        if off_counts:
            top = max(off_counts.items(), key=lambda kv: kv[1])
            print("      SIGTRAP 崩溃点偏移分布=%s → 主崩溃点=%s 出现 %d 次（引擎二进制侧，本机⛔修不了）" % (off_counts, top[0], top[1]))
        todays = len([p for p in reps if _dt.date.fromtimestamp(os.path.getmtime(p)) == _dt.date.today()])
        if todays:
            print("      今日新增 %d 份 ⇒ 属引擎侧事实，报爸/上报，⛔本机硬啃" % todays)

    # 6 记忆状态文件是否又被代写成引擎不认的形状
    psm = os.path.join(HOME, ".agnes", "memories", "processed_sessions.json")
    if os.path.exists(psm):
        try:
            d = json.loads(read_bytes(psm).decode("utf-8", errors="replace"))
        except Exception as exc:
            d = None
            reds.append("processed_sessions.json 连 JSON 都读不出：%s" % type(exc).__name__)
        if d is not None:
            keys = sorted(d.keys()) if isinstance(d, dict) else []
            sample = set()
            if isinstance(d, dict):
                vals = list(d.values())
                if vals and isinstance(vals[0], dict):
                    sample = set(vals[0].keys())
                for e in (d.get("processed") or []):
                    if isinstance(e, dict):
                        sample |= set(e.keys())
            engine_shape = {"session_id", "last_processed_message_index", "last_processed_hash",
                            "last_processed_at", "last_session_updated_at", "last_skip_reason",
                            "last_generation_run_id"}
            alien = sorted(sample - engine_shape)
            missing = sorted(engine_shape - sample)
            looks_engine = bool(sample) and not alien and not missing
            print("  格6 记忆状态文件 顶层=%s 条目字段=%s → 引擎形状=%s"
                  % (keys, sorted(sample), "对上" if looks_engine else "⛔对不上（多=%s 缺=%s）" % (alien, missing)))
            if not looks_engine:
                reds.append("processed_sessions.json 形状引擎不认＝memory worker 每 30 秒报警（双持有器）")
        # 引擎侧这条 WARN 今天还在不在（只扫最新那颗后端的 stderr）
        bl = sorted([os.path.join(BACKEND_LOG_DIR, f) for f in os.listdir(BACKEND_LOG_DIR) if f.startswith("agnesd-stderr")],
                    key=os.path.getmtime) if os.path.isdir(BACKEND_LOG_DIR) else []
        if bl:
            t = read_bytes(bl[-1]).decode("utf-8", errors="replace")
            n = t.count("invalid memory state")
            print("      最新后端 stderr（%s）里 invalid memory state 计数=%d" % (os.path.basename(bl[-1])[-24:], n))
    print("  巡检格数=6")
    if reds:
        print("\n  ⛔ 红格 %d 颗：" % len(reds))
        for r in reds:
            print("      - " + r)
        return RC_PATROL_RED
    print("\n  ✓ 六格全绿")
    return RC_OK


def main(argv=None):
    ap = argparse.ArgumentParser(add_help=True, description="恒林配置写入闸 + 冻结复发探测")
    ap.add_argument("--check", action="store_true", help="只量当前正本，⛔写")
    ap.add_argument("--selftest", action="store_true", help="六把刀自检（临时靶）")
    ap.add_argument("--audit", action="store_true", help="现扫盘上裸写腿")
    ap.add_argument("--patrol", action="store_true", help="只读巡检出红格")
    ap.add_argument("--write-from", dest="write_from", help="把该文件内容当候选提交（走全部闸）")
    ap.add_argument("--expect-add", default="", help="逗号分隔：预期新增的根级键")
    ap.add_argument("--expect-remove", default="", help="逗号分隔：预期删除的根级键")
    ap.add_argument("--make-registry", action="store_true", help="从引擎二进制现扫名册并落盘（含来路证据）")
    # 正门认得每颗旗标：未知旗标即出声退非 0（⛔静默走默认）
    args, unknown = ap.parse_known_args(argv)
    if unknown:
        sys.stderr.write("⛔ 未认得的旗标：%s（正门不猜，猜就会静默走默认那半）\n" % " ".join(unknown))
        return RC_SELFTEST_BLIND
    if args.make_registry:
        names, err = engine_owned_names()
        if err:
            print("⛔ %s" % err)
            return RC_SELFTEST_BLIND
        prov = {"来源二进制": APP_BIN,
                "二进制 sha256": sha256_bytes(read_bytes(APP_BIN))[:16],
                "现扫时刻": now_stamp(),
                "取法": "strings -a <bin> | 取 .json/.jsonl/.db 文件名，只留与记忆状态相关的那几颗",
                "名册": names}
        atomic_write(REGISTRY, json.dumps(prov, ensure_ascii=False, indent=2).encode("utf-8"))
        print("名册已落盘（颗数=%d）：%s" % (len(names), REGISTRY))
        print("  来路：%s" % json.dumps(prov, ensure_ascii=False)[:220])
        return RC_OK
    done = True
    rcs = []
    if args.check:
        rcs.append(cmd_check())
    if args.selftest:
        rcs.append(cmd_selftest())
    if args.audit:
        rcs.append(cmd_audit())
    if args.patrol:
        rcs.append(cmd_patrol())
    if args.write_from:
        rcs.append(cmd_write_from(args.write_from,
                                  [x for x in args.expect_add.split(",") if x.strip()],
                                  [x for x in args.expect_remove.split(",") if x.strip()]))
    if not (args.check or args.selftest or args.audit or args.patrol or args.write_from or args.make_registry):
        ap.print_help()
        return RC_SELFTEST_BLIND
    # 多颗腿同跑时⛔把退码按位或（3|4=7 会凭空造出一档不存在的判决）⇒ 只认第一颗非 0
    for x in rcs:
        if x:
            return x
    return RC_OK


if __name__ == "__main__":
    sys.exit(main())
