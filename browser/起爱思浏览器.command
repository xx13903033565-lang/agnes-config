#!/bin/bash
# 双击这颗＝给爱思办公起它自己的浏览器（一颗独立 Chrome，只监听 127.0.0.1:9344）
# 什么时候要双击：爱思办公里报「那条腿连不上」/「还是连不上端口 9344」的时候。
# 关掉：bash /Users/billtse/.agnes/browser/launch_agnes_chrome.sh --stop

HERE="$(cd "$(dirname "$0")" && pwd)"
echo "（这颗只是入口，真正做事的是同目录那颗起浏览器的脚本）"
bash "${HERE}/launch_agnes_chrome.sh"
rc=$?
echo "-----------------------------"
if [ "${rc}" -eq 0 ]; then
  echo "好了（退码 0）。回爱思办公让它重连就行，配置不用改。"
else
  echo "没成（退码 ${rc}）。上面有 Chrome 自己那句原话，别猜，照那句处理。"
fi
echo "（这个终端窗口可以关了）"
