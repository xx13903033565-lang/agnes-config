# AgnesCode Extensions Directory

本目录用于存放自定义工具和技能扩展，引擎通过 MCP 协议动态加载。

## 目录结构

```
~/.agnes/extensions/
├── examples/          # 示例工具（可直接使用）
├── templates/         # manifest 模板
└── [your-tool]/       # 你的工具包
    ├── tool.yaml      # 工具元数据
    ├── tool.ts        # TypeScript 实现
    └── README.md      # 使用说明
```

## 快速开始

1. 复制模板：`cp templates/skill_template.yaml my-tool/tool.yaml`
2. 编写实现：编辑 `my-tool/tool.ts`
3. 注册工具：运行 `python3 ~/.agnes/rules/register_extension.py my-tool`
4. 验证加载：在 AgnesCode 中输入 `/tools list` 查看是否出现

## 注意事项

- 每个工具必须包含 `tool.yaml` manifest
- TypeScript 代码会在 Deno 沙箱中执行
- 不要修改引擎内置工具（位于 `/Applications/AgnesCode.app/Contents/Resources/`）
- 工具脚本应避免直接文件系统写操作，使用 host-actions 模式

## 当前状态

⚠️ **引擎侧支持待完成**（P2-1 工单）：
- agnedd Rust 层需增加动态加载逻辑
- Deno 沙箱需开放 extensions 目录权限
- MCP 注册表需支持外部工具发现

本地配套已就绪，引擎升级后即可投入使用。
