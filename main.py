r"""
Session CLI - 获取和管理浏览器 Session

用法:
    uv run python main.py init                  # 初始化 Vault
    uv run python main.py grab <domain>         # 抓取 Session
    uv run python main.py get <domain>          # 查看 Session
    uv run python main.py list                  # 列出所有
    uv run python main.py delete <domain>       # 删除
    uv run python main.py serve                 # 启动 Web UI

    # 添加 --auto-connect 使用 Chrome 144+ autoConnect
    uv run python main.py grab yuanbao.tencent.com --auto-connect
"""

import sys
from getpass import getpass

import core
from core.vault import is_vault_ready

DEFAULT_DOMAIN = "yuanbao.tencent.com"


def cmd_init():
    """初始化 Vault（首次使用）。"""
    if is_vault_ready():
        print("[✓] Vault 已初始化并解锁")
        return
    pw = getpass("设置 Vault 密码: ")
    confirm = getpass("再次输入: ")
    if pw != confirm:
        print("[✗] 密码不一致")
        sys.exit(1)
    if core.init_vault(pw):
        print("[✓] Vault 初始化成功")
    else:
        print("[✗] 初始化失败（Vault 可能已存在）")
        sys.exit(1)


def cmd_grab(domain: str, auto_connect: bool):
    def progress(stage, detail):
        print(f"  [{stage}] {detail}")

    print(f"[*] 抓取 {domain} ...")
    try:
        data = core.grab_cookies(domain, auto_connect=auto_connect, on_progress=progress)
    except RuntimeError as e:
        print(f"[✗] {e}")
        sys.exit(1)

    cookies = data.get("cookies", "")
    auth_tokens = data.get("auth_tokens", [])
    headers = data.get("headers", {})
    raw_requests = data.get("raw_requests", [])
    related_domains = data.get("related_domains", [])
    cookie_count = cookies.count(";") + 1 if cookies else 0

    if not cookies and not auth_tokens and not headers:
        print("[✗] 未获取到 Cookie、认证凭据或请求头")
        sys.exit(1)

    rel_msg = f", {len(related_domains)} 个关联域名" if related_domains else ""
    print(f"[✓] 获取到 {cookie_count} 个 Cookie, {len(auth_tokens)} 个认证凭据, {len(headers)} 个公共 Header, {len(raw_requests)} 个原始请求{rel_msg}")
    info = core.store_site(domain, data, original_url=domain)
    print(f"[✓] 已存储到 vault: {info}")


def cmd_get(domain: str):
    site = core.get_site(domain)
    if site is None:
        print(f"[✗] 未找到 {domain}")
        sys.exit(1)
    status = "⚠ 已过期" if site["expired"] else "✓"
    hdr_count = site.get("header_count", 0)
    raw_count = site.get("raw_request_count", 0)
    print(f"[{status}] {site['domain']} | {site['cookie_count']} cookies | {site.get('auth_token_count', 0)} 认证凭据 | {hdr_count} headers | {raw_count} 原始请求")
    print(f"  创建: {site['created_at']}  过期: {site['expires_at']}")

    # 原始 URL
    original_url = site.get("original_url", "")
    if original_url:
        print(f"  原始 URL: {original_url}")

    # Cookie 原始字符串
    if site["cookies"]:
        print("\nCookie 原始字符串:")
        print(f"  {site['cookies']}")

    # 认证凭据
    auth_tokens = site.get("auth_tokens", [])
    if auth_tokens:
        print("\n认证凭据 (Authorization Headers):")
        for t in auth_tokens:
            tv = t["value"][:50] + "..." if len(t["value"]) > 50 else t["value"]
            print(f"  [{t['source']}] {t['key']} = {tv}")

    # 公共 Request Headers
    headers = site.get("headers", {})
    if headers:
        print(f"\n公共 Request Headers ({len(headers)} 个):")
        for key, value in headers.items():
            dv = value[:60] + "..." if len(value) > 60 else value
            print(f"  {key}: {dv}")

    # 原始请求列表摘要
    raw_requests = site.get("raw_requests", [])
    if raw_requests:
        print(f"\n原始请求列表 ({len(raw_requests)} 条):")
        for i, req in enumerate(raw_requests[:5], 1):
            print(f"  {i}. [{req.get('method', 'GET')}] {req.get('url', '')[:80]}")
        if len(raw_requests) > 5:
            print(f"  ... 还有 {len(raw_requests) - 5} 条")

    # 关联域名
    related_domains = site.get("related_domains", [])
    if related_domains:
        print(f"\n关联域名 ({len(related_domains)} 个):")
        for d in related_domains:
            print(f"  {d}")


def cmd_list():
    sites = core.list_sites()
    if not sites:
        print("(无)")
        return
    print(f"已存储 {len(sites)} 个站点:\n")
    for s in sites:
        tag = "✗ 已过期" if s["expired"] else "✓"
        at_count = s.get("auth_token_count", 0)
        hdr_count = s.get("header_count", 0)
        at_str = f", {at_count} 凭据" if at_count else ""
        hdr_str = f", {hdr_count} headers" if hdr_count else ""
        rel_count = s.get("related_domain_count", 0)
        rel_str = f", {rel_count} 关联域" if rel_count else ""
        url_info = ""
        if s.get("original_url"):
            url_short = s["original_url"][:60] + "..." if len(s["original_url"]) > 60 else s["original_url"]
            url_info = f"\n    URL: {url_short}"
        print(f"  [{tag}] {s['domain']}  ({s['cookie_count']} cookies{at_str}{hdr_str}{rel_str}){url_info}")


def cmd_delete(domain: str):
    if core.delete_site(domain):
        print(f"[✓] 已删除 {domain}")
    else:
        print(f"[✗] 未找到 {domain}")


def cmd_serve():
    """启动 Web UI。"""
    try:
        from server import app
        import uvicorn
        print("[*] 启动 Session Manager Web UI: http://127.0.0.1:8000")
        print("[*] 按 Ctrl+C 关闭")
        # Windows 上避免 ProactorEventLoop 关闭时的 NoneType 报错
        config = uvicorn.Config(app, host="127.0.0.1", port=8000, log_level="info", timeout_graceful_shutdown=2)
        server = uvicorn.Server(config)
        try:
            server.run()
        except KeyboardInterrupt:
            pass
    except ImportError:
        print("[✗] 请先安装 Web 依赖: uv add fastapi uvicorn jinja2")
        sys.exit(1)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)

    # 解析 --auto-connect（显式循环，清晰直观）
    auto_connect = False
    args = []
    for a in sys.argv[1:]:
        if a in ("--auto-connect", "-autoConnect"):
            auto_connect = True
        else:
            args.append(a)

    if not args:
        print(__doc__)
        sys.exit(0)

    cmd = args[0].lower()
    rest = args[1:]

    if cmd == "init":
        cmd_init()
    elif cmd == "grab":
        domain = rest[0] if rest else DEFAULT_DOMAIN
        cmd_grab(domain, auto_connect)
    elif cmd == "get":
        domain = rest[0] if rest else DEFAULT_DOMAIN
        cmd_get(domain)
    elif cmd == "list":
        cmd_list()
    elif cmd == "delete":
        domain = rest[0] if rest else DEFAULT_DOMAIN
        cmd_delete(domain)
    elif cmd == "serve":
        cmd_serve()
    else:
        print(f"未知命令: {cmd}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
