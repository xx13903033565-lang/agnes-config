#!/bin/bash
# 爱思办公的浏览器那条腿（MCP stdio 服务壳）
#
# 这颗脚本干三件事，按顺序：
#   1) 看端口 9344 上有没有 Chrome 在听（只认这颗端口，⛔抢 9222 那班店铺浏览器）
#   2) 没有 → 叫同目录的 launch_agnes_chrome.sh 起一颗（用户数据目录在 ~/.agnes/browser/profile）
#   3) 起好了 → 交棒给 agent-browser 的 MCP 服务，爱思办公就能操作浏览器
# 任何一步做不到，就把话说清楚退出（⛔闷着不起、⛔假装接上了）。
#
# 用法：不带参数（爱思办公的配置里就是这么调的）
#   可覆盖：AGNES_BROWSER_PORT / AGNES_BROWSER_PROFILE / AGENT_BROWSER_BIN

set -u

PORT="${AGNES_BROWSER_PORT:-9344}"
AB="${AGENT_BROWSER_BIN:-${HOME}/.local/bin/agent-browser}"
HERE="$(cd "$(dirname "$0")" && pwd)"
LAUNCHER="${HERE}/launch_agnes_chrome.sh"
TOOLS="${AGNES_BROWSER_TOOLS:-core}"
# 会话名一定要独立：~/.agent-browser/<名>.target 记着「这一班绑哪颗 tab」。
# 用默认那本＝会读到别的班次绑的淘宝发布页＝两班抢同一个浏览器＝打茬。
SESSION="${AGNES_BROWSER_SESSION:-agnes-code}"

say() { echo "[爱思浏览器壳] $*" >&2; }

check_port() {
  curl -s -f -m 2 -o /dev/null "http://127.0.0.1:${PORT}/json/version"
}

if [ ! -x "${AB}" ]; then
  say "起不来：没找到命令行浏览器工具 ${AB}"
  say "处置：这颗是 agent-browser（不是爱思办公自带的），装好后再复连"
  exit 4
fi

if ! check_port; then
  say "端口 ${PORT} 现在没人听，先按规矩起一颗自己的 Chrome"
  if [ -x "${LAUNCHER}" ] || [ -f "${LAUNCHER}" ]; then
    bash "${LAUNCHER}" >&2 || true
  else
    say "叫不到起浏览器的脚本：${LAUNCHER} 不在"
    exit 5
  fi
  # 起来要时间：最多再等 15 秒
  for _i in $(seq 1 15); do
    check_port && break
    sleep 1
  done
fi

if ! check_port; then
  say "还是连不上端口 ${PORT}。最可能的原因：这颗脚本是被爱思办公在系统沙盒里叫起来的，"
  say "Chrome 写不进用户数据目录＝起不来（＝那条腿的真根因，⛔用关沙盒糊过去）。"
  say "人要做的下一步：在终端手动跑一次  bash ${LAUNCHER}  ，看到「起来了」之后，"
  say "回爱思办公里让它重连即可（配置不用改）。"
  exit 6
fi

say "端口 ${PORT} 通了，交棒给 agent-browser（工具档位 ${TOOLS}，⛔自己开第二颗浏览器）"
exec "${AB}" --cdp "${PORT}" --session "${SESSION}" mcp --tools "${TOOLS}"
