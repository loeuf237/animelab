"""Authenticate every request to the Android loopback engine, including sockets."""
from http.cookies import SimpleCookie
import hmac
from starlette.types import ASGIApp, Receive, Scope, Send


class AndroidSessionMiddleware:
    def __init__(self, app: ASGIApp, token: str) -> None:
        if len(token) < 32:
            raise ValueError("Android session token is too short")
        from animelab.diagnostics import remember_secret
        remember_secret(token)
        self.app, self.token = app, token

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        supplied = headers.get(b"x-animan-session", b"").decode("ascii", "ignore")
        if not supplied:
            cookie = SimpleCookie()
            try:
                cookie.load(headers.get(b"cookie", b"").decode("latin1"))
                morsel = cookie.get("animan_android_session")
                supplied = morsel.value if morsel else ""
            except Exception:
                supplied = ""
        if not hmac.compare_digest(supplied.encode("utf-8"), self.token.encode("utf-8")):
            if scope["type"] == "websocket":
                await send({"type": "websocket.close", "code": 1008})
            else:
                await send({"type": "http.response.start", "status": 401,
                            "headers": [(b"content-type", b"application/json"), (b"cache-control", b"no-store")]})
                await send({"type": "http.response.body", "body": b'{"error":"Android session required"}'})
            return
        return await self.app(scope, receive, send)
