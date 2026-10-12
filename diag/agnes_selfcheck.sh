#!/bin/bash
# 爱思办公（AgnesCode）体检探针 —— 只读，不改任何东西。
#
# 为什么要这颗：10-11 那天我把它「白屏」当成 App 坏了，差点回滚配置；
# 真因是这台 Mac 息屏＋锁屏了，屏幕内容根本没合成。这种判断不该靠人记，
# 所以做成一条命令：先照屏幕/锁屏，再照进程、配置、技能、浏览器腿。
#
# 用法：bash /Users/billtse/.agnes/diag/agnes_selfcheck.sh
# 退出码：0=全部量到且没有红灯；1=有量不到的项（只出声，不猜）
#
# 纪律：这颗脚本⛔打印任何密钥/令牌的值；只按名点读数。

set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
CFG="${HOME}/.agnes/config/config.yaml"
BROWSER_DIR="${HOME}/.agnes/browser"
SKILLS_DIR="${HOME}/.agnes/skills"
LOG_DIR="${HOME}/.agnes/state/logs/server"
LAUNCHER="${BROWSER_DIR}/launch_agnes_chrome.sh"
MCP_SHELL="${BROWSER_DIR}/agnes_browser_mcp.sh"
AB="${HOME}/.local/bin/agent-browser"
PORT="${AGNES_BROWSER_PORT:-9344}"

RED=0
flag() { RED=1; echo "  ⚠ $*"; }

echo "=== 爱思办公体检（只读） ==="
echo "现在时刻 = $(date '+%Y-%m-%d %H:%M:%S')"
echo

echo "--- 1. 屏幕（白屏先查这里，别先怀疑 App） ---"
DISP=$(pmset -g log 2>/dev/null | grep -E "Display is turned (on|off)" | tail -n 1)
if [ -n "${DISP}" ]; then
  echo "显示器最后一条 = $(echo "${DISP}" | awk '{print $1, $2, $NF}')"
else
  flag "pmset 日志里没量到显示器开关记录"
fi
FRONT_ASN=$(lsappinfo front 2>/dev/null)
FRONT_NAME=$(lsappinfo info -only name "${FRONT_ASN}" 2>/dev/null | sed -E 's/.*"([^"]*)"$/\1/')
echo "前台那扇 = ${FRONT_NAME:-没量到}"
if echo "${FRONT_NAME}" | grep -qi "loginwindow"; then
  echo "锁屏判定 = 锁着（这时屏幕内容不合成，截图必白，App 内验收做不了）"
  echo "→ 人要做的下一步：解锁屏幕，再跑这条探针"
else
  echo "锁屏判定 = 没锁（前台不是登录窗口）"
fi
echo

echo "--- 2. 进程 ---"
MAIN_PID=$(pgrep -f "AgnesCode.app/Contents/MacOS/AgnesCode$" | head -n 1)
ENGINE_PID=$(pgrep -f "AgnesCode.app/Contents/Resources/bin/agnesd" | head -n 1)
if [ -n "${MAIN_PID}" ]; then
  echo "主进程 = ${MAIN_PID}（起了 $(ps -o etime= -p "${MAIN_PID}" | tr -d ' ')）"
else
  flag "主进程没在跑"
fi
if [ -n "${ENGINE_PID}" ]; then
  echo "引擎 agnesd = ${ENGINE_PID}（起了 $(ps -o etime= -p "${ENGINE_PID}" | tr -d ' ')）"
else
  flag "引擎 agnesd 没在跑＝智能体是死的"
fi
echo

echo "--- 3. 引擎日志 ---"
NEWEST=$(find "${LOG_DIR}" -name '*.log' -type f 2>/dev/null | xargs -I{} stat -f '%m {}' {} 2>/dev/null | sort -rn | head -n 1 | cut -d' ' -f2-)
if [ -n "${NEWEST}" ]; then
  echo "最新日志 = $(basename "${NEWEST}")"
  echo "行数 = $(wc -l < "${NEWEST}" | tr -d ' ')・最后改动 = $(stat -f '%Sm' "${NEWEST}")"
  echo "最后一条配方报错 = $(grep -c 'Failed to parse recipe' "${NEWEST}" 2>/dev/null) 条（这趟启动以来）"
else
  flag "找不到引擎日志目录 ${LOG_DIR}"
fi
echo

echo "--- 4. 配置读数（只点这几颗的名，⛔打印任何密钥） ---"
/usr/bin/python3 - "${CFG}" <<'PY'
import sys
try:
    import yaml
except Exception:
    print("  ⚠ 没装 yaml 库＝这几颗没量到"); sys.exit(0)
path = sys.argv[1]
try:
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
except Exception as e:
    print("  ⚠ 配置读不了：" + type(e).__name__); sys.exit(0)
print("压缩阈值 agnes-3.0-flash = %s" % (cfg.get("AGNES_MODEL_AUTO_COMPACT_THRESHOLDS", {}).get("agnes-3.0-flash", "没量到")))
print("  （这块表由引擎从服务端 /v2/models 同步后回写 config.yaml，本地手改活不过一次开机）")
print("最大轮数 AGNES_MAX_TURNS = %s" % cfg.get("AGNES_MAX_TURNS", "没量到"))
print("配方目录 AGNES_RECIPE_PATH = %s" % cfg.get("AGNES_RECIPE_PATH", "没设＝会去扫工作目录"))
exts = cfg.get("extensions", {}) or {}
print("扩展总颗数 = %d・启用颗数 = %d" % (len(exts), sum(1 for v in exts.values() if isinstance(v, dict) and v.get("enabled"))))
for name in ("computercontroller", "agnes_browser"):
    v = exts.get(name)
    if not isinstance(v, dict):
        print("%s = 册上没有这颗" % name); continue
    extra = (" cmd=%s" % v.get("cmd")) if v.get("type") == "stdio" else ""
    print("%s: enabled=%s type=%s%s" % (name, v.get("enabled"), v.get("type"), extra))
PY
echo

echo "--- 5. 技能正本 ---"
if [ -f "${SKILLS_DIR}/enter-project/SKILL.md" ]; then
  echo "enter-project = 在册（正本现扫器 $( [ -f "${SKILLS_DIR}/enter-project/qoder_memory_index.py" ] && echo 在 || echo 缺 )）"
else
  flag "enter-project 的 SKILL.md 不在"
fi
if [ -f "${SKILLS_DIR}/project-memory/SKILL.md" ]; then
  flag "project-memory 还挂着（改名没生效＝它还会进技能清单）"
else
  DEAD=$(find "${SKILLS_DIR}/project-memory" -maxdepth 1 -name 'SKILL.md.disabled*' 2>/dev/null | head -n 1)
  echo "project-memory = 已摘（留底件名 $(basename "${DEAD:-没量到}")）"
fi
echo

echo "--- 6. 浏览器那条腿 ---"
if [ -x "${LAUNCHER}" ]; then
  bash "${LAUNCHER}" --status 2>&1 | sed 's/^/  /'
else
  flag "起浏览器的脚本不在 ${LAUNCHER}"
fi
if [ -x "${AB}" ]; then
  echo "  agent-browser = $(${AB} --version 2>&1 | head -n 1)"
else
  flag "agent-browser 不在 ${AB}"
fi
if [ -x "${MCP_SHELL}" ]; then
  echo "  MCP 壳握手（问它有哪些工具）："
  /usr/bin/python3 - "${MCP_SHELL}" <<'PY'
import json, subprocess, sys, threading, queue
shell = sys.argv[1]
q = queue.Queue()
def run():
    try:
        p = subprocess.Popen(["bash", shell], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL, text=True, bufsize=1)
    except Exception as e:
        q.put("起不来：" + type(e).__name__); return
    def w(line):
        try:
            p.stdin.write(line + "\n"); p.stdin.flush()
        except Exception:
            pass
    w(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                  "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                             "clientInfo": {"name": "agnes-selfcheck", "version": "1"}}}))
    def reader():
        for line in p.stdout:
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                msg = json.loads(line)
            except Exception:
                continue
            if msg.get("id") == 1:
                w(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}))
                w(json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}))
            if msg.get("id") == 2:
                tools = (msg.get("result") or {}).get("tools") or []
                q.put("工具颗数 = %d" % len(tools))
                break
        try:
            p.stdin.close()
        except Exception:
            pass
        p.kill()
    t = threading.Thread(target=reader, daemon=True); t.start()
    t.join(45)
    if t.is_alive():
        q.put("45 秒内没量到（可能端口没通或壳自己卡住）")
th = threading.Thread(target=run, daemon=True); th.start(); th.join(60)
try:
    print("    " + q.get(timeout=1))
except Exception:
    print("    没量到")
PY
else
  flag "MCP 壳不在 ${MCP_SHELL}"
fi
echo
echo "--- 7. 配方白扫的真根（现扫日志，⛔写死文件名/颗数） ---"
FAILLOG=$(find "${LOG_DIR}" -name '*.log' -type f 2>/dev/null | xargs grep -l "Failed to parse recipe" 2>/dev/null | xargs -I{} stat -f '%m {}' {} 2>/dev/null | sort -rn | head -n 1 | cut -d' ' -f2-)
if [ -n "${FAILLOG}" ]; then
  echo "带配方报错的日志 = $(basename "${FAILLOG}")"
  echo "报错条数 = $(grep -c 'Failed to parse recipe' "${FAILLOG}")"
  grep -o -E 'Failed to parse recipe [^:]+\.json' "${FAILLOG}" | sed 's|Failed to parse recipe ||' | sort -u > /tmp/agnes_recipe_fails.txt
  echo "涉及的不同文件 = $(wc -l < /tmp/agnes_recipe_fails.txt | tr -d ' ') 颗（都在会话工作目录，⛔在集中配方目录里）"
  while IFS= read -r p; do
    if [ -f "${p}" ]; then
      echo "  在 $(basename "${p}")・字节=$(wc -c < "${p}" | tr -d ' ')・首字符=$(head -c 1 "${p}")"
    else
      echo "  已不在 $(basename "${p}")"
    fi
  done < /tmp/agnes_recipe_fails.txt
  DIRS=$(xargs -I{} dirname {} < /tmp/agnes_recipe_fails.txt | sort -u | wc -l | tr -d ' ')
  echo "所在目录 = ${DIRS} 处"
else
  echo "现扫：所有引擎日志里都没有配方报错（＝这条白扫已经没了，或还没跑过会话）"
fi
echo

echo "--- 8. 实时记忆正本（现扫，⛔写死名册） ---"
IDX="${SKILLS_DIR}/enter-project/qoder_memory_index.py"
if [ -f "${IDX}" ]; then
  /usr/bin/python3 "${IDX}" list > /tmp/agnes_mem_index.txt 2>&1
  sed -n '3p' /tmp/agnes_mem_index.txt | sed 's/^/  /'
  echo "  编码撞车（同一本记忆被多棵工作区共用）的目录 = $(grep -c '名册里还见过' /tmp/agnes_mem_index.txt) 颗"
else
  flag "记忆现扫器不在 ${IDX}"
fi
echo
echo "=== 体检结束：$( [ "${RED}" -eq 0 ] && echo '全部量到' || echo '有量不到的项，见上面 ⚠' ) ==="
exit "${RED}"
