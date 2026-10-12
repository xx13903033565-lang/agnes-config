#!/bin/bash
# 起爱思办公专用浏览器（一颗独立的 Chrome，只给爱思办公用）
#
# 为什么要有这颗：爱思办公的沙盒里直接开 Chrome 会失败——Chrome 要写自己的
# 用户数据目录，写在店铺文件夹里会被系统权限拦下（这就是「浏览器那条腿」断掉的真因）。
# 所以这里把用户数据目录放到 ~/.agnes/browser/profile（爱思办公自己的地盘），
# 并且只监听 127.0.0.1:9344 这一颗端口，⛔占用任何别的调试端口（9222 是店铺那班在用）。
#
# 用法：
#   bash launch_agnes_chrome.sh          # 起来（已在跑就只报状态，⛔重复起第二颗）
#   bash launch_agnes_chrome.sh --status # 只报现在有没有在跑
#   bash launch_agnes_chrome.sh --stop   # 关掉这颗（只认自己那颗端口，⛔杀别人）

set -u

PORT="${AGNES_BROWSER_PORT:-9344}"
HERE="$(cd "$(dirname "$0")" && pwd)"
PROFILE="${AGNES_BROWSER_PROFILE:-${HOME}/.agnes/browser/profile}"
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
LOGDIR="${HOME}/.agnes/browser/logs"
PIDFILE="${HOME}/.agnes/browser/chrome.pid"

mkdir -p "${PROFILE}" "${LOGDIR}"

have_curl() { command -v curl >/dev/null 2>&1; }

check_port() {
  # 只问这颗端口上的 /json/version，退 0＝有 Chrome 在听
  curl -s -f -m 2 -o /dev/null "http://127.0.0.1:${PORT}/json/version"
}

own_pid_alive() {
  [ -f "${PIDFILE}" ] || return 1
  local pid
  pid=$(cat "${PIDFILE}" 2>/dev/null || echo "")
  [ -n "${pid}" ] || return 1
  kill -0 "${pid}" 2>/dev/null
}

status() {
  if check_port; then
    echo "在跑：端口 ${PORT} 有 Chrome 在听（profile=${PROFILE}）"
    return 0
  fi
  echo "没在跑：端口 ${PORT} 没人听"
  return 1
}

stop_one() {
  # 只按自己那颗端口认领（lsof 查端口 → 拿到 pid → 只杀这颗），⛔ pkill chrome 一刀切
  local pid
  pid=$(lsof -nP -iTCP:"${PORT}" -sTCP:LISTEN -t 2>/dev/null | head -1)
  if [ -z "${pid}" ]; then
    echo "端口 ${PORT} 上本来就没东西，不用关"
    [ -f "${PIDFILE}" ] && rm -f "${PIDFILE}"
    return 0
  fi
  echo "只关这颗：pid=${pid}（端口 ${PORT} 认领到的，⛔动其他 Chrome 窗口）"
  kill "${pid}" 2>/dev/null || true
  sleep 2
  if check_port; then
    echo "还没退干净，再等一下；真要立刻停就手动在那个窗口退出"
  else
    echo "已停：端口 ${PORT} 现在没人听"
  fi
  [ -f "${PIDFILE}" ] && rm -f "${PIDFILE}"
  return 0
}

launch() {
  if [ ! -x "${CHROME}" ]; then
    echo "起不来：没找到 Chrome 可执行件（${CHROME}）" >&2
    exit 4
  fi
  if check_port; then
    echo "已经在跑了，不重复起第二颗（端口 ${PORT}，profile=${PROFILE}）"
    echo "提醒：⛔再开第二颗同端口 Chrome——两班会抢同一个浏览器＝打岔"
    exit 0
  fi
  local logf
  logf="${LOGDIR}/launch_$(date +%Y%m%d_%H%M%S).log"
  echo "起一颗新的：端口 ${PORT}・用户数据目录 ${PROFILE}・日志 ${logf}"
  # 关键点：这条只在沙盒外跑得顺；爱思办公自己调这颗时若被沙盒拦，会走到下面超时那条出声
  (
    "${CHROME}" \
      --user-data-dir="${PROFILE}" \
      --remote-debugging-port="${PORT}" \
      --remote-debugging-address=127.0.0.1 \
      --no-first-run \
      --no-default-browser-check \
      --disable-sync \
      --disable-session-crashed-bubble \
      --hide-crash-restore-bubble \
      about:blank >"${logf}" 2>&1 &
    echo $! >"${PIDFILE}"
  )
  local i
  for i in $(seq 1 20); do
    if check_port; then
      echo "起来了：${i} 次轮询后端口 ${PORT} 通了（pid=$(cat "${PIDFILE}" 2>/dev/null || echo 未知)）"
      exit 0
    fi
    sleep 1
  done
  echo "起不来：等了 20 秒端口 ${PORT} 还没通。" >&2
  echo "  这一步多半是被系统沙盒/权限拦了（Chrome 写不进用户数据目录）。" >&2
  echo "  处置：这颗纸上的 Chrome 请人双击「${HERE}/起爱思浏览器.command」，或跑 bash $0 后再让爱思办公复连。" >&2
  [ -f "${logf}" ] && echo "  Chrome 自己那句原话在 ${logf} 的头几行（本脚本不加工它）" >&2
  exit 5
}

case "${1:-}" in
  --status) status; exit $? ;;
  --stop) stop_one; exit $? ;;
  "" | --launch) launch ;;
  *)
    echo "认不得这颗旗标：$1" >&2
    echo "只用得上：（不带＝起）・--status（看状态）・--stop（关掉这颗）" >&2
    exit 6
    ;;
esac
