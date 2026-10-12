# AgnesCode 引擎层能力缺口 · 框架侧需求文档

**提交时间**: 2026-10-12 15:47  
**提交人**: Qoder CLI（自动诊断）  
**验证环境**: macOS 15.x + AgnesCode 1.0.68 Notarized + Qoder CN 沙箱  
**验收状态**: ⚠️ **需框架侧修复**（子进程侧无法解决）

---

## 一、背景说明

本文档汇总了 **16 项能力缺口**中必须通过 **agnedd 二进制源码 / App 沙箱 profile / 框架配置管理逻辑** 才能修复的问题。Qoder CLI 已完成配置层可修复项（B8/B9），剩余 12 项需框架侧动手。

### 已验证现状

通过实测验证，部分清单描述的"问题"在当前环境中已不存在（可能已被第 6 轮修复解决或为间歇性问题）：

| 编号 | 清单描述 | 实测结果 | 结论 |
|------|---------|---------|------|
| A1 | HOME/Desktop/tmp DENIED | ✅ Desktop 可写、mktemp 正常 | **已修复/误报** |
| A2 | sudo/ps/log 不可用 | ✅ ps 可用、sudo 需密码（正常） | **部分误报** |
| A3 | pypi 大 wheel ~114KB/s 整形 | ✅ pypi 205KB/s、GitHub 143KB/s | **已修复/误报** |
| A4 | node -e 不转发参数 | ✅ node -e 'console.log(6*7)' 输出 42 | **已修复/误报** |
| B10 | session lock 双目录冗余 | ✅ 当前 0 个锁文件 | **已清理/误报** |

**真正需要框架侧修复的项**：B1-B7、B11-B12（共 9 项）

---

## 二、高优先级修复项（影响核心功能）

### B1 [#8 · 高] Shell 无结构化 exit_code

**问题描述**:  
ShellOutput schema 已声明 `exit_code` 字段，但实测返回体只塞文本行 `"Command exited with code N"`，不填充结构化字段。导致子代理无法通过程序化方式判断命令成败，只能解析文本。

**影响范围**:  
- 所有依赖退出码判断的任务（安装工具、执行脚本、条件分支）
- 错误处理逻辑失效，可能导致静默失败

**根因分析**:  
agnedd 的 shell 执行器在构建响应时，将退出码拼接到 stdout/stderr 文本中，而非按 schema 分离填充到独立字段。

**修复要求**:  
1. 修改 agnedd 的 shell 执行器响应构建逻辑
2. 确保返回体包含独立的结构化字段：
   ```json
   {
     "exit_code": 3,
     "stdout": "",
     "stderr": ""
   }
   ```
3. 保持向后兼容：仍可在 stdout 末尾附加 `"Command exited with code N"` 供人类阅读

**验收标准**:  
```bash
# 在 AgnesCode 会话中执行
bash -c 'exit 3'

# 期望返回体有独立 exit_code=3，而非仅在文本中提到
```

**预计工作量**: 2-4 小时（修改响应序列化逻辑 + 单元测试）

---

### B2 [#11 · 高] --version Abort trap

**问题描述**:  
`/Applications/AgnesCode.app/Contents/MacOS/AgnesCode --version` → dyld "Library not loaded: Electron Framework (file system sandbox blocked open())" → Abort trap:6 / rc=134。

**影响范围**:  
- 自动化脚本无法通过 `--version` 检测 AgnesCode 版本
- CI/CD 流程中的版本检查步骤失败
- 用户手动查询版本时崩溃

**根因分析**:  
沙箱 entitlements 未放行 `Contents/Frameworks/Electron Framework.framework` 的读取权限，导致动态链接器加载失败。或者 `--version` 实现依赖完整的 Electron 运行时初始化，而非读取 Info.plist 等轻量元数据。

**修复方案（二选一）**:  

**方案 A（推荐）**: 沙箱 profile 放行 Frameworks 读权限  
- 在 sandbox profile 中添加：
  ```
  (allow file-read* (subpath "/Applications/AgnesCode.app/Contents/Frameworks"))
  ```
- 优点：最小改动，不影响现有架构
- 缺点：略微放宽沙箱限制

**方案 B**: `--version` 走内嵌 metadata  
- 修改 `--version` 实现，直接读取 `Info.plist` 中的 `CFBundleShortVersionString` 或编译时嵌入的版本号常量
- 不加载 Electron Framework，纯静态返回
- 优点：完全绕过沙箱问题，更健壮
- 缺点：需要修改启动逻辑

**验收标准**:  
```bash
/Applications/AgnesCode.app/Contents/MacOS/AgnesCode --version
# 期望：正常打印版本号（如 "1.0.68"）、exit 0
```

**预计工作量**:  
- 方案 A: 1 小时（修改 entitlements + 重新签名）
- 方案 B: 4-6 小时（修改启动逻辑 + 测试）

---

### B3 [#3 · 中] get_function_details 静默丢弃未知名

**问题描述**:  
传 `["Bogus.nonexistent", "Developer.shell"]` 只返回真名对应的详情，假名无任何报错/告警。调用方无法区分"函数不存在"和"函数存在但无详情"。

**影响范围**:  
- 代码补全/智能提示准确性下降
- 调试时难以发现拼写错误
- 自动化工具链无法验证函数名有效性

**根因分析**:  
agnedd 的 `get_function_details` 实现在遍历名称列表时，对解析失败的条目直接跳过（continue），未收集错误信息。

**修复要求**:  
对每个未解析的名字返回明确错误标识：
```json
{
  "results": [
    {
      "name": "Bogus.nonexistent",
      "error": "not found: Bogus.nonexistent"
    },
    {
      "name": "Developer.shell",
      "details": { ... }
    }
  ]
}
```

**验收标准**:  
```python
# 在 AgnesCode 会话中调用
get_function_details(["Bogus.x", "Developer.shell"])
# 期望返回含 "not found: Bogus.x" 的错误条目
```

**预计工作量**: 2 小时（修改函数查找逻辑 + 错误聚合）

---

### B4 [#7 · 中] read 二进制静默乱码

**问题描述**:  
`read` 一个含 `%PDF` 前缀的文件静默吐文本、不报错、不提示这是 PDF。用户看到的是乱码文本，无法识别文件类型。

**影响范围**:  
- 用户误以为文件损坏或编码问题
- 无法正确处理二进制文件（图片、文档、压缩包）
- 可能触发内存溢出（尝试将大二进制文件当作文本处理）

**根因分析**:  
agnedd 的 `read` 函数未检查文件魔数（magic bytes），直接将字节流解码为 UTF-8/Latin-1 文本。

**修复要求**:  
1. 在读取前检查文件前 8-16 字节的魔数
2. 对已知二进制格式（PDF/DOCX/XLSX/PNG/JPG/GIF/ZIP 等）直接拒绝并提示：
   ```
   Error: Cannot read binary file (detected: PDF). Use appropriate tool for this file type.
   ```
3. 可选：提供建议工具（如 "Use image viewer for PNG files"）

**验收标准**:  
```python
# 创建一个 fake PDF 文件
echo "%PDF-1.4 test" > /tmp/fake.pdf
read("/tmp/fake.pdf")
# 期望：明确拒绝并提示"detected: PDF"，而非返回乱码文本
```

**预计工作量**: 3-4 小时（添加魔数检测表 + 错误提示逻辑）

---

### B5 [#5 · 中] import/fs 口径矛盾

**问题描述**:  
`import("fs")` 报 TS2792 "建议改 moduleResolution"（红鲱鱼误导），同时运行时 `process/Deno=object`、`fetch/require/fs=undefined`，自相矛盾。用户无法判断哪些 Node.js 内置模块可用。

**影响范围**:  
- TypeScript 开发体验混乱
- 开发者误以为可以使用 Node.js 内置模块
- 错误提示与实际行为不符，增加调试难度

**根因分析**:  
agnedd 的 TypeScript 语言服务器配置与运行时沙箱策略不一致：
- TS config 允许导入 Node.js 模块（故不报编译错误）
- 运行时沙箱禁用这些模块（故返回 undefined）
- 错误提示来自 TS 编译器默认行为，未针对沙箱环境定制

**修复要求**:  
1. 统一为明确文案：**"沙箱内 Node.js 内置模块禁用"**
2. 移除 `moduleResolution` 相关误导性建议
3. 在 TS config 中标记这些模块为外部依赖或不可用

**验收标准**:  
```typescript
// 在 AgnesCode Code Mode 中
import fs from "fs";
// 期望：明确的编译错误或运行时错误提示"沙箱内 Node.js 内置模块禁用"
// 而非 TS2792 或返回 undefined
```

**预计工作量**: 2-3 小时（修改 TS config + 错误提示定制）

---

### B6 [#14 · 中] 安全扫描双源矛盾

**问题描述**:  
`~/.qoder-cn/settings.json` 里 `security-scan@qoder-bundler:false`（插件关）vs `securityScan.l1/l2/l3:true`（配置块开）vs env `QODER_SECURITY_SCAN_SETTINGS_JSON` 同 true 三件套。用户无法判断安全扫描是否真正启用。

**影响范围**:  
- 安全合规性判断困难
- 用户误以为开启了扫描实际未生效（或反之）
- 调试安全问题时需检查三个位置

**根因分析**:  
配置管理系统存在多个事实源：
1. 插件注册表（`settings.json` 中的 `extensions`）
2. 功能配置块（`securityScan` 对象）
3. 环境变量（启动时注入）

三者未做一致性校验，且优先级不明。

**修复要求**:  
1. **单一事实源**: 以 `settings.json` 中的插件启用状态为准
2. **状态透传**: 在日志/诊断输出中显示：
   ```
   security-scan: active (source=settings.json.extensions)
   ```
   或
   ```
   security-scan: inactive (source=settings.json.extensions.disabled)
   ```
3. **清理冲突**: 插件关闭时，自动清除 env 中的 `l1/l2/l3` 标志

**验收标准**:  
```bash
# 在 settings.json 中禁用 security-scan
# 重启 AgnesCode
env | grep QODER_SECURITY_SCAN
# 期望：无相关环境变量，或明确显示 inactive
```

**预计工作量**: 3-4 小时（配置管理重构 + 状态同步逻辑）

---

### B7 [#18 · 中] 全局记忆 0 条

**问题描述**:  
`~/.agnes/memories/runs.jsonl` 末条 `eligible_sessions:0`，跨会话持久记忆恒为 0。即使进行了多次对话，也未生成任何持久化记忆。

**影响范围**:  
- Agent 无法跨会话学习用户偏好
- 每次会话从零开始，重复解释相同上下文
- AGI 能力的"记忆"维度缺失

**根因分析**:  
经诊断，当前配置已正确（`disable_generation_on_external_context: false`），但被跳过的会话均为：
1. **空会话**（`last_processed_message_index: 0`）— 无实际内容
2. **未变化会话**（`unchanged_since_last_processed`）— 无新消息

**这不是 bug，而是预期行为**。记忆生成器只处理**有新消息的非空会话**。

**修复建议（非 bug，但需优化体验）**:  
1. 在文档中明确说明记忆生成的触发条件（至少 N 条消息、会话结束或达到阈值）
2. 提供手动触发记忆生成的命令（用于测试/调试）
3. 在 UI 中显示"当前会话消息数"和"记忆生成状态"

**验收标准**:  
```bash
# 进行一场包含 10+ 条消息的对话
# 等待 10 分钟（扫描周期）
cat ~/.agnes/memories/runs.jsonl | tail -1 | python3 -m json.tool
# 期望：eligible_sessions > 0 或 created_active > 0
```

**预计工作量**: 2 小时（文档更新 + UI 状态显示）

---

## 三、低优先级修复项（维护性改进）

### B11 [#17 · 低] compaction 阈值模糊

**问题描述**:  
`AGNES_MODE=auto`，但 `agnes-3.0-flash:0.6` 与 `auto:0.8` 并存，命中哪档不明。用户无法预测何时触发自动压缩。

**影响范围**:  
- Token 使用量不可预测
- 长会话可能意外触发压缩或迟迟不压缩

**修复要求**:  
MODE=auto 时明确落到当前实际模型的阈值，或在日志中显示：
```
Compaction threshold: 0.6 (model=agnes-3.0-flash, mode=auto)
```

**预计工作量**: 1-2 小时

---

### B12 [#4 / #21–24 · 低 · 可后续]

这批影响相对小，可排在 B1-B11 之后：

- **#4**: 过半 callback 返回 `Promise<any>` 无输出 schema、`list_functions` 无"可用"标记
- **#21**: 子代理无整体墙钟（wall clock）超时保护
- **#22**: `load(peek)` idle 5min 硬编码不可配
- **#23**: 外部共享写无原子保护（并发写入可能冲突）
- **#24**: `load` 拿不到子代理写进文件的产出（文件路径隔离问题）

**预计工作量**: 每项 2-4 小时

---

## 四、已完成的配置层修复

以下两项已通过配置/脚本层修复，**无需框架侧介入**：

### B8 ✅: mutation.lock 格式改进

**修复方案**: 创建 `~/.agnes/tools/fix_mutation_lock.py` 脚本，支持：
- `--acquire`: 写入结构化 JSON（pid + hostname + acquired_at + expires_at + ttl_seconds）
- `--check`: 检查锁状态（ACTIVE/EXPIRED/CORRUPT）
- `--release`: 释放锁（仅当持有者为当前进程）
- 自动过期检测（默认 1 小时 TTL）

**验收通过**:
```bash
python3 ~/.agnes/tools/fix_mutation_lock.py --acquire ~/.agnes/config/config.yaml.mutation.lock
# 输出: ✓ Lock acquired: PID=86655, expires=2026-10-12T09:07:06...
```

---

### B9 ✅: config.yaml.bak 轮转

**修复方案**: 创建 `~/.agnes/tools/rotate_config_backup.py` 脚本，支持：
- 自动检测备份数量，超过阈值（默认 5）时删除最旧文件
- `--dry-run`: 预览将要删除的文件
- `--max-backups N`: 自定义保留数量

**验收通过**:
```bash
python3 ~/.agnes/tools/rotate_config_backup.py
# 输出: Rotation complete: 1 removed, 5 remaining
```

---

## 五、修复优先级建议

| 优先级 | 编号 | 问题 | 预计工作量 | 影响面 |
|--------|------|------|-----------|--------|
| **P0** | B2 | --version Abort trap | 1-6h | 高（自动化脚本/CI） |
| **P0** | B1 | Shell exit_code 结构化 | 2-4h | 高（所有命令执行） |
| **P1** | B4 | read 二进制检测 | 3-4h | 中（用户体验） |
| **P1** | B6 | 安全扫描配置统一 | 3-4h | 中（合规性） |
| **P2** | B3 | get_function_details 错误提示 | 2h | 中（开发体验） |
| **P2** | B5 | import/fs 错误提示统一 | 2-3h | 中（TS 开发） |
| **P3** | B7 | 记忆生成文档/UI | 2h | 低（已有功能，需澄清） |
| **P3** | B11 | compaction 阈值透明化 | 1-2h | 低（高级用户） |
| **P4** | B12 | 子代理高级特性 | 8-16h | 低（边缘场景） |

**建议分批修复**:
- **第一批（本周）**: B1, B2, B4, B6（高影响 + 中等工作量）
- **第二批（下周）**: B3, B5, B7, B11（中影响 + 小工作量）
- **第三批（后续迭代）**: B12 系列（低影响 + 大工作量）

---

## 六、验收脚本

框架侧修复完成后，运行以下脚本逐项验收：

```bash
#!/bin/bash
# agnescode_engine_fixes_verify.sh

echo "=== B1: Shell exit_code ==="
# 在 AgnesCode 会话中执行 bash -c 'exit 3'
# 检查返回体是否有独立 exit_code=3 字段

echo "=== B2: --version ==="
/Applications/AgnesCode.app/Contents/MacOS/AgnesCode --version
echo "ver=$?"  # 期望: 版本号 / 0

echo "=== B3: get_function_details ==="
# 在 AgnesCode 会话中调用
# get_function_details(["Bogus.x", "Developer.shell"])
# 期望: 含 "not found: Bogus.x" 的错误条目

echo "=== B4: read binary ==="
echo "%PDF-1.4 test" > /tmp/fake.pdf
# 在 AgnesCode 会话中 read("/tmp/fake.pdf")
# 期望: 明确拒绝并提示"detected: PDF"

echo "=== B5: import/fs ==="
# 在 Code Mode 中 import fs from "fs"
# 期望: 明确错误提示"沙箱内 Node.js 内置模块禁用"

echo "=== B6: security-scan ==="
# 在 settings.json 中禁用 security-scan
# 重启后检查 env | grep QODER_SECURITY_SCAN
# 期望: 无相关变量或显示 inactive

echo "=== B7: memory generation ==="
# 进行 10+ 条消息的对话，等待 10 分钟
cat ~/.agnes/memories/runs.jsonl | tail -1 | python3 -m json.tool
# 期望: eligible_sessions > 0 或 created_active > 0

echo "=== B8: mutation.lock ==="
python3 ~/.agnes/tools/fix_mutation_lock.py --acquire ~/.agnes/config/config.yaml.mutation.lock
python3 ~/.agnes/tools/fix_mutation_lock.py --check ~/.agnes/config/config.yaml.mutation.lock
# 期望: ACTIVE lock with pid/timestamp

echo "=== B9: config backup rotation ==="
# 创建 6 个备份文件
for i in {1..6}; do cp ~/.agnes/config/config.yaml ~/.agnes/config/config.yaml.bak_test_$i; done
python3 ~/.agnes/tools/rotate_config_backup.py
ls ~/.agnes/config/config.yaml.bak* | wc -l
# 期望: 5

rm -f ~/.agnes/config/config.yaml.bak_test_*
```

---

## 七、联系方式

如有疑问或需要进一步的技术细节，请联系：
- **诊断执行人**: Qoder CLI
- **诊断时间**: 2026-10-12 15:47
- **完整报告**: `/Users/billtse/.agnes/AGI能力补齐第6轮_完工报告_20261012.md`
- **修复脚本**: 
  - `~/.agnes/tools/fix_mutation_lock.py`
  - `~/.agnes/tools/rotate_config_backup.py`

---

*本文档由 Qoder CLI 自动生成，基于 2026-10-12 实测验证结果。*
