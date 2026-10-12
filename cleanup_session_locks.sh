#!/bin/bash
# AgnesCode session lock 清理脚本
# 用途：定期清理超过 30 分钟未更新的孤儿锁文件

LOCK_DIRS=(
    "$HOME/.agnes/data/sessions/.session-run-locks"
    "$HOME/.agnes/state/session-run-locks"
)

TTL_MINUTES=30
CLEANED=0

for dir in "${LOCK_DIRS[@]}"; do
    if [ ! -d "$dir" ]; then
        continue
    fi
    
    # 查找并删除超过 TTL 的锁文件
    while IFS= read -r -d '' lock_file; do
        rm -f "$lock_file"
        ((CLEANED++))
    done < <(find "$dir" -name "*.lock" -type f -mmin +${TTL_MINUTES} -print0 2>/dev/null)
done

if [ "$CLEANED" -gt 0 ]; then
    echo "已清理 $CLEANED 个过期 session lock 文件"
else
    echo "无需清理（当前锁文件数：$(find "${LOCK_DIRS[@]}" -name "*.lock" -type f 2>/dev/null | wc -l)）"
fi
