# CLI Requirements

## 入口 (`main.py`)

| ID | Status | Requirement |
|----|--------|-------------|
| REQ-601 | ✅ | 使用 `argparse` 实现子命令路由 |
| REQ-602 | ✅ | 支持 `--vault` 参数指定 Vault 文件路径 |
| REQ-603 | ✅ | Vault 初始化命令：`uv run python main.py init` |
| REQ-604 | ✅ | 启动 Web 服务：`uv run python main.py serve` |
| REQ-605 | ✅ | 列出所有站点：`uv run python main.py list` |
| REQ-606 | ✅ | 抓取站点 Cookie：`uv run python main.py grab <domain>` |
| REQ-607 | ✅ | 查看站点详情：`uv run python main.py get <domain>` |
| REQ-608 | ✅ | 删除站点：`uv run python main.py delete <domain>` |
| REQ-609 | ✅ | `serve` 命令启动 FastAPI + uvicorn 服务（`127.0.0.1:8000`） |
| REQ-610 | 📋 | 交互模式（域名自动补全） |

## 输出格式

| ID | Status | Requirement |
|----|--------|-------------|
| REQ-611 | ✅ | `list` 输出表格化摘要（域名、Cookie 数、过期时间） |
| REQ-612 | ✅ | `get` 输出原始 Cookie 字符串 + 认证凭据列表 |
| REQ-613 | ✅ | `grab` 输出抓取结果摘要（Cookie 数、凭据数） |
| REQ-614 | ✅ | 错误信息使用中文输出 |