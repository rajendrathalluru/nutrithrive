import hashlib
import hmac
import json
import secrets
import time
from collections import OrderedDict
from threading import Lock

from starlette.requests import HTTPConnection, Request
from starlette.responses import JSONResponse


class AccessControl:
    def __init__(self, settings):
        self.enabled = settings.APP_ACCESS_ENABLED
        self.secure = settings.APP_COOKIE_SECURE
        self.max_age = settings.APP_SESSION_HOURS * 3600
        self.origins = set(settings.cors_origins)
        self.cookie_name = "__Host-thrivewell_session" if self.secure else "thrivewell_session"
        self.password_digest = hashlib.sha256(settings.APP_ACCESS_PASSWORD.encode()).digest()
        self.signing_key = hmac.digest(
            settings.APP_SESSION_SECRET.encode(), b"thrivewell-session-v1:" + self.password_digest, "sha256"
        )
        self.attempts = OrderedDict()
        self.attempt_lock = Lock()
        if self.enabled:
            if len(settings.APP_ACCESS_PASSWORD) < 12 or len(settings.APP_ACCESS_PASSWORD) > 256:
                raise ValueError("APP_ACCESS_PASSWORD must contain 12–256 characters when access protection is enabled.")
            if len(settings.APP_SESSION_SECRET) < 32:
                raise ValueError("APP_SESSION_SECRET must contain at least 32 random characters.")
            if not 1 <= settings.APP_SESSION_HOURS <= 24:
                raise ValueError("APP_SESSION_HOURS must be between 1 and 24.")
            if "*" in self.origins:
                raise ValueError("Password protection requires explicit CORS_ORIGINS, not a wildcard.")

    def issue_session(self):
        payload = f"{int(time.time()) + self.max_age}.{secrets.token_hex(32)}"
        signature = hmac.new(self.signing_key, payload.encode(), hashlib.sha256).hexdigest()
        return f"{payload}.{signature}"

    def authenticated(self, connection):
        token = connection.cookies.get(self.cookie_name, "")
        if len(token) > 256:
            return False
        try:
            expires, nonce, signature = token.split(".")
            payload = f"{expires}.{nonce}"
            expected = hmac.new(self.signing_key, payload.encode(), hashlib.sha256).hexdigest()
            return (
                len(nonce) == 64
                and hmac.compare_digest(expected.encode(), signature.encode())
                and time.time() < int(expires) <= time.time() + self.max_age
            )
        except (ValueError, UnicodeError):
            return False

    def trusted_origin(self, connection):
        origin = connection.headers.get("origin")
        if not origin or origin == "null":
            return False
        scheme = "https" if connection.url.scheme in {"https", "wss"} else "http"
        same_origin = f"{scheme}://{connection.url.netloc}"
        return origin == same_origin or origin in self.origins

    def allow_attempt(self, address):
        now = time.monotonic()
        with self.attempt_lock:
            while self.attempts and next(iter(self.attempts.values()))[0] <= now:
                self.attempts.popitem(last=False)
            deadline, count = self.attempts.get(address, (now + 900, 0))
            if count >= 10 or (address not in self.attempts and len(self.attempts) >= 4096):
                return False
            self.attempts[address] = (deadline, count + 1)
            return True

    def clear_attempts(self, address):
        with self.attempt_lock:
            self.attempts.pop(address, None)

    async def endpoint(self, request):
        path = request.url.path
        if path == "/auth/status" and request.method == "GET":
            return JSONResponse({"enabled": self.enabled, "authenticated": not self.enabled or self.authenticated(request)})
        if path not in {"/auth/login", "/auth/logout"} or request.method != "POST":
            return JSONResponse({"detail": "Not found."}, status_code=404)
        if not self.enabled:
            return JSONResponse({"enabled": False, "authenticated": True})
        if not self.trusted_origin(request):
            return JSONResponse({"detail": "Untrusted request origin."}, status_code=403)
        if path == "/auth/logout":
            response = JSONResponse({"authenticated": False})
            response.delete_cookie(self.cookie_name, path="/", secure=self.secure, httponly=True, samesite="strict")
            return response
        address = request.client.host if request.client else "unknown"
        if not self.allow_attempt(address):
            return JSONResponse({"detail": "Too many attempts. Please try again in 15 minutes."}, status_code=429,
                                headers={"Retry-After": "900"})
        if request.headers.get("content-type", "").split(";")[0].strip() != "application/json":
            return JSONResponse({"detail": "A JSON password is required."}, status_code=415)
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 4096:
                return JSONResponse({"detail": "Request is too large."}, status_code=413)
        try:
            data = json.loads(body)
            password = data.get("password") if isinstance(data, dict) else None
        except (ValueError, UnicodeError):
            password = None
        if not isinstance(password, str) or not 1 <= len(password) <= 256:
            return JSONResponse({"detail": "Enter a valid password."}, status_code=400)
        try:
            candidate_digest = hashlib.sha256(password.encode()).digest()
        except UnicodeError:
            return JSONResponse({"detail": "Enter a valid password."}, status_code=400)
        if not hmac.compare_digest(candidate_digest, self.password_digest):
            return JSONResponse({"detail": "Incorrect password. Please try again."}, status_code=401)
        self.clear_attempts(address)
        response = JSONResponse({"enabled": True, "authenticated": True})
        response.set_cookie(self.cookie_name, self.issue_session(), max_age=self.max_age,
                            path="/", secure=self.secure, httponly=True, samesite="strict")
        return response


class AccessControlMiddleware:
    public_pages = {"/", "/chat", "/chat/", "/index.html", "/env-config.js", "/favicon.ico",
                    "/thrivewell-icon.svg", "/logo192.png", "/logo512.png", "/manifest.json", "/robots.txt"}

    def __init__(self, app, access):
        self.app = app
        self.access = access

    async def __call__(self, scope, receive, send):
        if scope["type"] not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return
        connection = HTTPConnection(scope)
        path = scope["path"]
        if scope["type"] == "websocket":
            if self.access.enabled and (not self.access.authenticated(connection) or not self.access.trusted_origin(connection)):
                await send({"type": "websocket.close", "code": 1008})
                return

            async def guarded_receive():
                message = await receive()
                if message["type"] != "websocket.disconnect" and self.access.enabled and not self.access.authenticated(connection):
                    await send({"type": "websocket.close", "code": 1008})
                    return {"type": "websocket.disconnect", "code": 1008}
                return message

            await self.app(scope, guarded_receive, send)
            return

        async def secured_send(message):
            if message["type"] == "http.response.start" and (self.access.enabled or path.startswith("/auth/")):
                headers = [(name, value) for name, value in message.get("headers", []) if name.lower() != b"cache-control"]
                headers.extend([(b"cache-control", b"no-store"), (b"x-content-type-options", b"nosniff"),
                                (b"x-frame-options", b"DENY")])
                message = {**message, "headers": headers}
            await send(message)

        if path.startswith("/auth/"):
            response = await self.access.endpoint(Request(scope, receive))
            await response(scope, receive, secured_send)
            return
        if path == "/health/live" and scope["method"] in {"GET", "HEAD"}:
            await JSONResponse({"status": "alive"})(scope, receive, secured_send)
            return
        public = scope["method"] in {"GET", "HEAD"} and (path in self.public_pages or path.startswith("/static/"))
        if self.access.enabled and not public:
            if not self.access.authenticated(connection):
                await JSONResponse({"detail": "Please enter the Thrivewell access password."}, status_code=401)(scope, receive, secured_send)
                return
            if scope["method"] not in {"GET", "HEAD", "OPTIONS"} and not self.access.trusted_origin(connection):
                await JSONResponse({"detail": "Untrusted request origin."}, status_code=403)(scope, receive, secured_send)
                return
        await self.app(scope, receive, secured_send)
