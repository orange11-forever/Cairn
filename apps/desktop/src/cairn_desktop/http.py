"""The native shell's capability is required even for loopback requests."""

import hmac
from urllib.parse import urlsplit

from cairn_api.errors import error_response
from cairn_api.middleware import new_request_id
from starlette.datastructures import Headers
from starlette.requests import Request


class DesktopAccess:
    def __init__(self, app, *, origin: str, token: str):
        self.app = app
        self.origin = origin
        self.host = urlsplit(origin).netloc
        self.cookie = f"cairn_desktop_{urlsplit(origin).port}"
        self.token = token

    async def __call__(self, scope, receive, send):
        if scope["type"] == "lifespan":
            return await self.app(scope, receive, send)
        if scope["type"] != "http":
            await send({"type": "websocket.close", "code": 1008})
            return
        headers = Headers(scope=scope)
        supplied = headers.get("x-cairn-desktop") or Request(scope).cookies.get(self.cookie, "")
        authorized = (
            headers.get("host") == self.host
            and headers.get("origin", self.origin) == self.origin
            and headers.get("sec-fetch-site") != "cross-site"
            and hmac.compare_digest(supplied.encode(), self.token.encode())
        )
        if not authorized:
            response = error_response(
                status_code=403,
                code="desktop_access_denied",
                message="仅允许本机 Cairn 应用访问",
                trace_id=scope.get("state", {}).get("request_id") or new_request_id(),
            )
            response.headers.update(
                {
                    "Cache-Control": "no-store",
                    "Referrer-Policy": "no-referrer",
                    "X-Content-Type-Options": "nosniff",
                }
            )
            await response(scope, receive, send)
            return

        async def secured_send(message):
            if message["type"] == "http.response.start":
                message["headers"] = [
                    *message.get("headers", []),
                    (b"referrer-policy", b"no-referrer"),
                    (b"x-content-type-options", b"nosniff"),
                ]
            await send(message)

        await self.app(scope, receive, secured_send)
