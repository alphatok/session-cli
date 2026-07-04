# Requirements

此目录包含 Session CLI 项目的需求文档。每个 `.md` 文件对应一个模块或功能领域。

## 文档结构

| 文件 | 领域 | 描述 |
|------|------|------|
| [core.md](core.md) | 核心 | 会话抓取、Vault 存储、MCP 通信 |
| [cli.md](cli.md) | CLI | 命令行接口与子命令 |
| [server.md](server.md) | 服务端 | Web API 与 SSE 流式推送 |
| [ui.md](ui.md) | 界面 | Web UI 交互与视觉设计 |
| [technical.md](technical.md) | 技术 | 技术约束、非功能需求、UX 规范 |

## 约定

- 使用现在时态描述需求。
- 状态标记：`✅ done`、`🚧 in-progress`、`📋 planned`。
- 每条需求应原子化、可测试。
- 模块增删时同步更新此索引。