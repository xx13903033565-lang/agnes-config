#!/bin/bash
# AgnesCode 终端执行工具
# 安全策略：白名单命令 + 危险命令拦截

set -euo pipefail

# 危险命令黑名单
DANGEROUS_PATTERNS=(
    "rm -rf /"
    "rm -rf ~"
    "mkfs"
    "dd if="
    ":(){:|:&};"
    "> /dev/sd"
    "chmod 777 /"
    "chown -R"
)

# 检查命令是否安全
check_safety() {
    local cmd="$1"
    
    for pattern in "${DANGEROUS_PATTERNS[@]}"; do
        if [[ "$cmd" == *"$pattern"* ]]; then
            echo "{\"error\": \"危险命令被拦截: $pattern\"}"
            exit 1
        fi
    done
    
    # 允许的命令前缀
    local allowed_prefixes=(
        "ls"
        "cat"
        "grep"
        "find"
        "pwd"
        "echo"
        "date"
        "uptime"
        "ps"
        "df"
        "du"
        "git"
        "python3"
        "node"
        "npm"
        "pnpm"
        "curl"
        "wget"
        "ping"
        "whoami"
        "id"
        "env"
        "which"
        "file"
        "wc"
        "head"
        "tail"
        "sort"
        "uniq"
        "awk"
        "sed"
        "mkdir"
        "cp"
        "mv"
        "touch"
        "chmod"
        "chown"
        "kill"
        "pkill"
        "pgrep"
        "launchctl"
        "defaults"
        "codesign"
        "otool"
        "lsof"
        "netstat"
        "scutil"
    )
    
    local first_word=$(echo "$cmd" | awk '{print $1}')
    local is_allowed=false
    
    for prefix in "${allowed_prefixes[@]}"; do
        if [[ "$first_word" == "$prefix" ]]; then
            is_allowed=true
            break
        fi
    done
    
    if [[ "$is_allowed" == false ]]; then
        echo "{\"error\": \"命令不在白名单中: $first_word\", \"hint\": \"请先在 ~/.agnes/tools/whitelist.txt 中添加该命令\"}"
        exit 1
    fi
}

# 读取 JSON 输入
if [ $# -eq 0 ]; then
    read -r input
else
    input="$1"
fi

# 解析命令
cmd=$(echo "$input" | python3 -c "import sys, json; print(json.load(sys.stdin)['command'])" 2>/dev/null)

if [ -z "$cmd" ]; then
    echo '{"error": "未提供 command 参数"}'
    exit 1
fi

# 安全检查
check_safety "$cmd"

# 执行命令
output=$(eval "$cmd" 2>&1)
exit_code=$?

# 返回结果
python3 -c "
import json, sys
result = {
    'command': '''$cmd''',
    'exit_code': $exit_code,
    'stdout': '''$output''' if $exit_code == 0 else '',
    'stderr': '''$output''' if $exit_code != 0 else '',
    'success': $exit_code == 0
}
print(json.dumps(result, ensure_ascii=False))
"
