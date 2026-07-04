---
name: readme-and-requirements-docs
overview: 写 GitHub description、中英双语 README（含 FAQ）、创建 requirements 文件夹维护项目需求文档
todos:
  - id: update-pyproject-desc
    content: 更新 pyproject.toml 的 description 字段为项目简介
    status: pending
  - id: create-requirements-dir
    content: 新建 requirements/ 目录及需求文档（README.md / cli-commands.md / web-ui.md / cookie-grab.md / vault-storage.md）
    status: pending
  - id: rewrite-readme
    content: 重写 README.md 为英文默认的中英双语文档（含项目介绍、快速开始、命令速查、项目结构、架构图、FAQ）
    status: pending
---

## 用户需求

- 编写 GitHub 仓库 description，替换 pyproject.toml 中的占位符
- 重写 README.md，结构清晰、言简意赅，包含：
- 项目简介（解决什么问题）
- 快速开始（安装 & 使用方法）
- 项目结构（更新为模块化后的 core/ 包）
- FAQ（5 个最常见问题 + 回答）
- 中英文双语，默认展示英文版（即英文在前、中文在后）
- 新建 requirements/ 文件夹，把功能需求分文档沉淀下来，便于长期维护

## 产品概述

Session CLI 是一个通过 Chrome DevTools MCP 协议自动抓取、管理和持久化浏览器 Cookie/Session 的命令行工具。支持 CLI 和 Web UI 两种形态，使用 Romek Vault 加密存储敏感数据。

## 核心功能

- 通过 chrome-devtools-mcp 自动抓取任意网站 Cookie（无需手动 F12 复制）
- CLI 命令式操作（init / grab / get / list / delete / serve）
- 内置 Web UI（FastAPI + HTMX，SSE 实时进度推送）
- 加密存储到 Romek Vault，密码通过系统 keyring 自动管理

## 实现方案

纯文档编写任务，不涉及代码修改。采用以下结构：

### 1. pyproject.toml — description 字段

将 `description = "Add your description here"` 替换为项目的一句话描述。

### 2. README.md — 中英双语文档

采用 Markdown 分段结构，英文内容在前、中文翻译在后，用 `---` 或 `##` 分隔。具体章节：

- **Badges**（可选）：Python 版本、License 等
- **What is this?** — 一句话说明解决什么问题
- **Quick Start** — 安装、初始化、抓取 Cookie 的完整流程
- **Commands** — CLI 命令速查表
- **Project Structure** — 更新为模块化后的目录树
- **Architecture** — Mermaid 架构图（CLI / Web UI → core/ → MCP / Vault）
- **FAQ** — 5 个高频问题 + 简明回答
- **中文版** — 与英文对应的中文翻译

### 3. requirements/ 文件夹

创建以下文件：

- `requirements/README.md` — 需求文档索引
- `requirements/cli-commands.md` — CLI 命令需求
- `requirements/web-ui.md` — Web UI 需求
- `requirements/cookie-grab.md` — Cookie 抓取流程需求
- `requirements/vault-storage.md` — Vault 加密存储需求