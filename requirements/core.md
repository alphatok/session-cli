# Core Requirements

## Session Grabbing (`core/mcp.py`)

| ID | Status | Requirement |
|----|--------|-------------|
| REQ-001 | ✅ | Connect to Chrome DevTools via MCP protocol (`@anthropic/chrome-devtools-mcp`) |
| REQ-002 | ✅ | Auto-connect to running Chrome instance via `chrome://inspect/#remote-debugging` |
| REQ-003 | ✅ | Extract cookies for a given domain (name, value, domain, path, httpOnly, secure, sameSite, expires) |
| REQ-004 | ✅ | Support `--auto-connect` flag to skip manual port entry |
| REQ-005 | 📋 | Support Firefox and Edge MCP adapters |

## Vault Storage (`core/vault.py`)

| ID | Status | Requirement |
|----|--------|-------------|
| REQ-006 | ✅ | Encrypt and persist cookies using Romek Vault |
| REQ-007 | ✅ | Vault master password retrieved from OS keyring at startup |
| REQ-008 | ✅ | CRUD operations: list sites, get cookies, store cookies, delete site |
| REQ-009 | ✅ | Each domain maps to one Vault entry (last-write-wins semantics) |
| REQ-010 | 📋 | Export cookies to Netscape `cookies.txt` format |
| REQ-011 | 📋 | Import cookies from browser extensions or JSON |

## Session Management (`core/session.py`)

| ID | Status | Requirement |
|----|--------|-------------|
| REQ-012 | ✅ | Unified public API wrapping MCP + Vault: `grab_and_store()`, `list_sites()`, `get_site()`, `delete_site()` |
| REQ-013 | ✅ | Expose all symbols in `core/__init__.py` for clean imports |

## CLI (`main.py`)

| ID | Status | Requirement |
|----|--------|-------------|
| REQ-014 | ✅ | Subcommands: `list`, `grab <domain>`, `get <domain>`, `delete <domain>`, `serve` |
| REQ-015 | ✅ | `serve` starts FastAPI+uvicorn web server |
| REQ-016 | ✅ | Rich help text via `argparse` |
| REQ-017 | 📋 | Interactive mode with domain auto-complete |

## Web UI (`server.py` + `templates/`)

| ID | Status | Requirement |
|----|--------|-------------|
| REQ-018 | ✅ | FastAPI routes: `GET /` (dashboard), `POST /grab` (start grab), `GET /grab/stream/<task_id>` (SSE progress), `GET /site/<domain>`, `DELETE /site/<domain>` |
| REQ-019 | ✅ | HTMX-based frontend with no page reloads |
| REQ-020 | ✅ | SSE streaming for real-time grab progress |
| REQ-021 | ✅ | Site list auto-refreshes every 30 seconds |
| REQ-022 | 📋 | Dark mode toggle |
| REQ-023 | 📋 | Bulk grab (paste multiple domains) |
