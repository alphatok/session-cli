# Session CLI

> Grab browser sessions & cookies via Chrome DevTools MCP. CLI + Web UI. Encrypted storage.

[中文文档](README_zh.md)

## What problem does this solve?

Manually extracting cookies from a browser for use in scripts, scrapers, or API testing is tedious.
You need to open DevTools, find the Application tab, copy values one by one — and repeat for every domain.

Session CLI automates this via Chrome's remote debugging protocol (MCP). One command grabs all cookies for a domain and stores them in an encrypted vault, ready for programmatic use.

## Features

- **CLI + Web UI** — grab and view cookies from terminal or browser
- **MCP protocol** — communicates with Chrome via the standard Chrome DevTools MCP adapter
- **Encrypted vault** — all cookies stored in a Romek Vault, unlocked via OS keyring
- **SSE streaming** — real-time progress in the Web UI
- **Single binary feel** — just `uv run python main.py`

## Quick Start

### Prerequisites

- Python 3.13+
- [uv](https://docs.astral.sh/uv/) package manager
- Chrome with remote debugging enabled (`chrome://inspect/#remote-debugging`)
- Node.js 18+ (for `npx` MCP adapter)

### Install

```bash
git clone https://github.com/<user>/session-cli.git
cd session-cli
uv sync
```

### CLI Usage

```bash
# List stored sites
uv run python main.py list

# Grab cookies for a domain
uv run python main.py grab example.com --auto-connect

# View grabbed cookies
uv run python main.py get example.com

# Delete a site
uv run python main.py delete example.com
```

### Web UI

```bash
uv run python main.py serve
# → Open http://127.0.0.1:8000
```

## Command Reference

| Command | Description |
|---------|-------------|
| `list` | List all stored sites |
| `grab <domain> --auto-connect` | Grab cookies from Chrome and store |
| `get <domain>` | Show stored cookies for a domain |
| `delete <domain>` | Remove a stored site |
| `serve` | Start FastAPI Web UI |

## Project Structure

```
session-cli/
├── core/
│   ├── __init__.py      # Public API
│   ├── mcp.py           # Chrome DevTools MCP communication
│   ├── vault.py         # Romek Vault encrypted persistence
│   └── session.py       # Domain logic (grab + store)
├── main.py              # CLI entry point
├── server.py            # FastAPI Web Server
├── templates/
│   └── index.html       # HTMX frontend
├── tests/               # Pytest test suite
├── requirements/        # Requirements documentation
├── pyproject.toml
└── README.md
```

## Architecture

```
┌───────────┐     ┌──────────┐
│    CLI    │     │  Web UI  │
│  main.py  │     │ server.py│
└─────┬─────┘     └────┬─────┘
      │                │
      └───────┬────────┘
              ▼
      ┌──────────────┐
      │     core     │
      ├──────────────┤
      │ grab_cookies │ ◄── MCP + Chrome autoConnect
      │ list_sites   │ ◄── Romek Vault CRUD
      │ store_site   │
      │ delete_site  │
      └──────────────┘
```

## FAQ

### 1. Do I need to keep Chrome open?

Yes. Session CLI communicates with Chrome via the DevTools protocol (MCP). Chrome must be running with remote debugging enabled at `chrome://inspect/#remote-debugging`.

### 2. Is my data safe?

All session data is stored in a Romek Vault, an encrypted file vault. The vault password is automatically retrieved from your OS keyring at startup, so you never need to type it manually.

### 3. Why does `--auto-connect` sometimes fail?

The MCP adapter automatically discovers Chrome's debugging port. If it fails, ensure Chrome was started with remote debugging enabled (e.g., `--remote-debugging-port=9222`) and that no other tool is occupying that port.

### 4. Can I use this with browsers other than Chrome?

Currently, only Chrome is supported through the `@anthropic/chrome-devtools-mcp` adapter. Firefox and Edge support is planned (see [requirements](requirements/core.md)).

### 5. How do I use the grabbed cookies in my Python script?

```python
from core import list_sites, get_site
cookies = get_site("example.com")
# cookies is a list of dicts with name, value, domain, path, etc.
for c in cookies:
    print(f"{c['name']}={c['value']}")
```

Or import the vault file directly with Romek in your script for programmatic access.

## License

MIT
