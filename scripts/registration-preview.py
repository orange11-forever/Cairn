"""Private loopback SMTP + inbox + API harness. Never sends external mail or prints proofs.

Run with uv run --package cairn-api python scripts/registration-preview.py.
CAIRN_TEST_DATABASE_URL must point to an owned loopback cairn_test database.
"""
import argparse
import html
import os
import re
from email import policy
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from ipaddress import ip_address
from socketserver import StreamRequestHandler, ThreadingTCPServer
from threading import Lock, Thread

import uvicorn
from sqlalchemy.engine import make_url

from cairn_api.app import create_app
from cairn_api.db.session import Database
from cairn_api.seed import seed_demo_identity
from cairn_api.settings import Settings


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-url", default="http://localhost:5503")
    parser.add_argument("--api-port", type=int, default=55828)
    parser.add_argument("--smtp-port", type=int, default=55826)
    parser.add_argument("--inbox-port", type=int, default=55827)
    args = parser.parse_args()
    database_url = os.environ.get("CAIRN_TEST_DATABASE_URL", "")
    parsed = make_url(database_url)
    try:
        local = ip_address(parsed.host or "").is_loopback
    except ValueError:
        local = parsed.host == "localhost"
    if parsed.database != "cairn_test" or not local or parsed.drivername != "postgresql+psycopg":
        parser.error("an owned loopback PostgreSQL cairn_test database is required")
    settings = Settings(
        environment="test", database_url=database_url, app_url=args.app_url,
        cors_origins=[args.app_url], registration_enabled=True,
        smtp_host="127.0.0.1", smtp_port=args.smtp_port, smtp_security="plain",
        smtp_from="cairn@example.com", smtp_username=None, smtp_password=None,
        oauth_github_client_id=None, oauth_github_client_secret=None,
        oauth_feishu_client_id=None, oauth_feishu_client_secret=None,
        answer_base_url=None, answer_api_key=None, answer_model=None, _env_file=None,
    )
    messages: list[bytes] = []
    lock = Lock()
    class Capture(StreamRequestHandler):
        def handle(self) -> None:
            self.wfile.write(b"220 loopback test capture\r\n")
            while line := self.rfile.readline(4096):
                command = line.split(b" ", 1)[0].strip().upper()
                if command == b"DATA":
                    self.wfile.write(b"354 send message\r\n")
                    parts: list[bytes] = []
                    size = 0
                    while (part := self.rfile.readline(4096)) not in (b".\r\n", b""):
                        size += len(part)
                        if size > 65536:
                            self.wfile.write(b"552 message too large\r\n")
                            return
                        parts.append(part.removeprefix(b".") if part.startswith(b"..") else part)
                    with lock:
                        messages.append(b"".join(parts))
                        del messages[:-20]
                    self.wfile.write(b"250 captured locally\r\n")
                elif command == b"QUIT":
                    self.wfile.write(b"221 goodbye\r\n")
                    return
                else:
                    self.wfile.write(b"250 localhost\r\n")
    class Inbox(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            pass
        def do_GET(self) -> None:
            if self.headers.get("Host") not in (f"localhost:{args.inbox_port}", f"127.0.0.1:{args.inbox_port}"):
                self.send_error(403)
                return
            if self.path != "/":
                self.send_error(404)
                return
            with lock:
                snapshot = list(messages)
            body = "<!doctype html><html lang='zh-CN'><meta charset='utf-8'><title>Cairn 本机测试收件箱</title><h1>本机测试收件箱</h1><p>只捕获此预览发送的邮件；重启后清空。手动刷新查看。</p>"
            for index, raw in enumerate(reversed(snapshot)):
                message = BytesParser(policy=policy.default).parsebytes(raw)
                content = message.get_payload(decode=True)
                if not isinstance(content, bytes):
                    continue
                proof = re.search(re.escape(args.app_url.rstrip("/") + "/register/verify#token=") + r"[A-Za-z0-9_-]+", content.decode("utf-8"))
                body += f"<article><h2>邮件 {len(snapshot) - index}</h2><p>{html.escape(str(message['To']))}</p>"
                if proof:
                    body += f"<a rel='noreferrer' href='{html.escape(proof[0], quote=True)}'>打开验证邮件</a>"
                body += "</article>"
            body += "</html>"
            data = body.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers()
            self.wfile.write(data)
    database = Database(database_url)
    seed_demo_identity(settings, database)
    with ThreadingTCPServer(("127.0.0.1", args.smtp_port), Capture) as smtp, ThreadingHTTPServer(("127.0.0.1", args.inbox_port), Inbox) as inbox:
        for server in (smtp, inbox):
            Thread(target=server.serve_forever, daemon=True).start()
        print(f"Local test API: http://127.0.0.1:{args.api_port}", flush=True)
        print(f"Private captured inbox: http://localhost:{args.inbox_port}/", flush=True)
        try:
            uvicorn.run(create_app(settings, database), host="127.0.0.1", port=args.api_port, access_log=False)
        finally:
            smtp.shutdown()
            inbox.shutdown()


if __name__ == "__main__":
    main()
