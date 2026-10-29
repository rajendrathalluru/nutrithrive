import json
import runpy
import unittest
from http.cookies import SimpleCookie
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse

from app.core.access_control import AccessControl, AccessControlMiddleware


def configuration(**overrides):
    return SimpleNamespace(**{
        "APP_ACCESS_ENABLED": True,
        "APP_ACCESS_PASSWORD": "test-only-long-password",
        "APP_SESSION_SECRET": "test-only-session-secret-never-use-in-production",
        "APP_SESSION_HOURS": 8,
        "APP_COOKIE_SECURE": True,
        "cors_origins": ["http://localhost:3000"],
        **overrides,
    })


async def request(app, path, method="GET", body=b"", headers=None, client="192.0.2.1"):
    sent = []
    received = False

    async def receive():
        nonlocal received
        if not received:
            received = True
            return {"type": "http.request", "body": body, "more_body": False}
        return {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)

    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "method": method, "path": path,
        "raw_path": path.encode(), "root_path": "", "query_string": b"", "scheme": "https",
        "headers": [(key.lower().encode(), value.encode()) for key, value in {"host": "thrivewell.test", **(headers or {})}.items()],
        "server": ("thrivewell.test", 443), "client": (client, 12345), "http_version": "1.1",
    }
    await app(scope, receive, send)
    start = next(message for message in sent if message["type"] == "http.response.start")
    payload = b"".join(message.get("body", b"") for message in sent if message["type"] == "http.response.body")
    return start["status"], dict(start["headers"]), payload


class AccessControlTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.access = AccessControl(configuration())
        self.calls = []

        async def downstream(scope, receive, send):
            self.calls.append(scope["path"])
            if scope["type"] == "websocket":
                await send({"type": "websocket.accept"})
                await receive()
                return
            await JSONResponse({"protected": "result"})(scope, receive, send)

        self.downstream = downstream
        self.middleware = AccessControlMiddleware(downstream, self.access)
        self.app = CORSMiddleware(self.middleware, allow_origins=["http://localhost:3000"],
                                  allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

    async def login(self, password="test-only-long-password", origin="https://thrivewell.test"):
        return await request(self.app, "/auth/login", "POST", json.dumps({"password": password}).encode(),
                             {"origin": origin, "content-type": "application/json"})

    async def cookie(self):
        status, headers, body = await self.login()
        self.assertEqual(status, 200)
        cookie = SimpleCookie(headers[b"set-cookie"].decode())
        return f"{self.access.cookie_name}={cookie[self.access.cookie_name].value}"

    async def test_status_is_public_and_contains_no_secrets(self):
        status, headers, body = await request(self.app, "/auth/status")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {"enabled": True, "authenticated": False})
        self.assertEqual(headers[b"cache-control"], b"no-store")

    async def test_all_api_routes_and_unknown_routes_fail_closed(self):
        for path, method in [("/health", "GET"), ("/ask", "POST"), ("/ask/v1", "POST"),
                             ("/search", "POST"), ("/transcribe", "POST"), ("/realtime/session", "POST"),
                             ("/cache/clear", "POST"), ("/cache/stats", "GET"), ("/system/info", "GET"),
                             ("/docs", "GET"), ("/redoc", "GET"), ("/openapi.json", "GET"), ("/future/api", "GET")]:
            with self.subTest(path=path):
                status, headers, body = await request(self.app, path, method)
                self.assertEqual(status, 401)
                self.assertEqual(headers[b"cache-control"], b"no-store")
        self.assertEqual(self.calls, [])

    async def test_login_shell_and_assets_remain_public_but_not_posts(self):
        for path in ["/", "/chat", "/chat/", "/static/js/main.js", "/thrivewell-icon.svg", "/env-config.js"]:
            self.assertEqual((await request(self.app, path))[0], 200)
            self.assertEqual((await request(self.app, path, "POST"))[0], 401)

    async def test_liveness_does_not_expose_engine_details_or_require_login(self):
        status, headers, body = await request(self.app, "/health/live")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {"status": "alive"})
        self.assertEqual(self.calls, [])

    async def test_login_cookie_and_refresh_then_recipe_and_voice_requests(self):
        status, headers, body = await self.login()
        cookie_header = headers[b"set-cookie"].decode()
        for attribute in ["HttpOnly", "Secure", "SameSite=strict", "Path=/", "Max-Age=28800", "__Host-thrivewell_session="]:
            self.assertIn(attribute, cookie_header)
        self.assertNotIn("test-only", cookie_header + body.decode())
        cookie = await self.cookie()
        response = await request(self.app, "/auth/status", headers={"cookie": cookie})
        self.assertTrue(json.loads(response[2])["authenticated"])
        for path in ["/ask", "/transcribe", "/realtime/session"]:
            status, headers, body = await request(self.app, path, "POST", headers={"cookie": cookie, "origin": "https://thrivewell.test"})
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(body), {"protected": "result"})

    async def test_wrong_password_and_malformed_input_do_not_set_cookie(self):
        cases = [(b'{"password":"wrong"}', 401), (b"{", 400), (b"[]", 400),
                 (b'{"password":false}', 400), (b'{"password":"\\ud800"}', 400), (b"x" * 5000, 413)]
        for body, expected in cases:
            status, headers, payload = await request(self.app, "/auth/login", "POST", body,
                                                    {"origin": "https://thrivewell.test", "content-type": "application/json"})
            self.assertEqual(status, expected)
            self.assertNotIn(b"set-cookie", headers)
            self.assertNotIn(b"test-only", payload)

    async def test_csrf_and_cross_origin_web_requests_are_rejected(self):
        cookie = await self.cookie()
        for origin in ["https://evil.test", "null", ""]:
            self.assertEqual((await self.login(origin=origin))[0], 403)
            for path in ["/ask", "/auth/logout"]:
                self.assertEqual((await request(self.app, path, "POST", headers={"cookie": cookie, "origin": origin}))[0], 403)
        self.assertEqual((await request(self.app, "/auth/login", "POST", b"password=wrong",
                                        {"origin": "https://thrivewell.test", "content-type": "application/x-www-form-urlencoded"}))[0], 415)

    async def test_local_split_origin_allows_credentials_and_preflight_only_for_configured_origin(self):
        status, headers, body = await self.login(origin="http://localhost:3000")
        self.assertEqual(status, 200)
        self.assertEqual(headers[b"access-control-allow-credentials"], b"true")
        self.assertEqual(headers[b"access-control-allow-origin"], b"http://localhost:3000")
        for origin, expected in [("http://localhost:3000", 200), ("https://evil.test", 400)]:
            response = await request(self.app, "/ask", "OPTIONS", headers={
                "origin": origin, "access-control-request-method": "POST", "access-control-request-headers": "content-type"})
            self.assertEqual(response[0], expected)

    async def test_expiry_tampering_and_password_or_secret_rotation_invalidate_sessions(self):
        cookie = await self.cookie()
        altered = cookie[:-1] + ("0" if cookie[-1] != "0" else "1")
        self.assertEqual((await request(self.app, "/health", headers={"cookie": altered}))[0], 401)
        for changes in [{"APP_ACCESS_PASSWORD": "a-different-long-password"}, {"APP_SESSION_SECRET": "a-different-secret-that-is-at-least-32-characters"}]:
            rotated = AccessControlMiddleware(self.downstream, AccessControl(configuration(**changes)))
            self.assertEqual((await request(rotated, "/health", headers={"cookie": cookie}))[0], 401)
        with patch("app.core.access_control.time.time", return_value=9999999999):
            self.assertEqual((await request(self.app, "/health", headers={"cookie": cookie}))[0], 401)

    async def test_logout_deletes_the_browser_cookie(self):
        cookie = await self.cookie()
        status, headers, body = await request(self.app, "/auth/logout", "POST", headers={"cookie": cookie, "origin": "https://thrivewell.test"})
        self.assertEqual(status, 200)
        self.assertIn(b"Max-Age=0", headers[b"set-cookie"])
        self.assertFalse(json.loads(body)["authenticated"])
        self.assertEqual((await request(self.app, "/ask", "POST"))[0], 401)

    async def test_brute_force_throttle_expires_and_does_not_trust_forwarded_headers(self):
        with patch("app.core.access_control.time.monotonic", return_value=100):
            for attempt in range(10):
                self.assertEqual((await self.login("wrong"))[0], 401)
            status, headers, body = await self.login()
            self.assertEqual(status, 429)
            self.assertEqual(headers[b"retry-after"], b"900")
            self.assertEqual((await request(self.app, "/auth/login", "POST", b'{"password":"wrong"}',
                                            {"origin": "https://thrivewell.test", "content-type": "application/json", "x-forwarded-for": "192.0.2.99"}))[0], 429)
        with patch("app.core.access_control.time.monotonic", return_value=1001):
            self.assertEqual((await self.login())[0], 200)

    async def test_sessions_work_across_workers_with_the_same_configuration(self):
        cookie = await self.cookie()
        second_worker = AccessControlMiddleware(self.downstream, AccessControl(configuration()))
        self.assertEqual((await request(second_worker, "/health", headers={"cookie": cookie}))[0], 200)

    async def test_websocket_requires_cookie_and_trusted_origin_and_rechecks_expiry(self):
        token = self.access.issue_session()
        for cookie, origin, expected in [("", "https://thrivewell.test", "websocket.close"),
                                         (token, "https://evil.test", "websocket.close"),
                                         (token, "https://thrivewell.test", "websocket.accept")]:
            sent = []

            async def receive():
                return {"type": "websocket.connect"}

            async def send(message):
                sent.append(message)

            scope = {"type": "websocket", "scheme": "wss", "path": "/ws/transcribe", "query_string": b"",
                     "headers": [(b"host", b"thrivewell.test"), (b"origin", origin.encode()),
                                 (b"cookie", f"{self.access.cookie_name}={cookie}".encode())]}
            await self.middleware(scope, receive, send)
            self.assertEqual(sent[0]["type"], expected)
        sent = []

        async def expired_receive():
            self.access.signing_key = b"rotated-key"
            return {"type": "websocket.receive", "text": "audio"}

        await self.middleware(scope, expired_receive, send)
        self.assertEqual([message["type"] for message in sent], ["websocket.accept", "websocket.close"])

    async def test_disabled_gate_preserves_existing_behavior(self):
        app = AccessControlMiddleware(self.downstream, AccessControl(configuration(APP_ACCESS_ENABLED=False, APP_ACCESS_PASSWORD="", APP_SESSION_SECRET="")))
        self.assertEqual((await request(app, "/ask", "POST"))[0], 200)
        self.assertEqual(json.loads((await request(app, "/auth/status"))[2]), {"enabled": False, "authenticated": True})

    async def test_real_app_supports_credentialed_status_checks_even_when_gate_is_disabled(self):
        from app.main import app
        cors = next(middleware for middleware in app.user_middleware if middleware.cls is CORSMiddleware)
        self.assertTrue(cors.options["allow_credentials"])
        origin = cors.options["allow_origins"][0]
        status, headers, body = await request(app, "/auth/status", headers={"origin": origin})
        self.assertEqual(status, 200)
        self.assertEqual(headers[b"access-control-allow-credentials"], b"true")
        self.assertIn("authenticated", json.loads(body))

    def test_invalid_boolean_setting_cannot_silently_disable_the_gate(self):
        from app.core.config import environment_flag
        with patch.dict("os.environ", {"APP_ACCESS_ENABLED": "treu"}):
            with self.assertRaises(ValueError):
                environment_flag("APP_ACCESS_ENABLED", "false")

    async def test_disabled_gate_preserves_legacy_wildcard_cors_without_invalid_credential_headers(self):
        from app.core.config import settings
        with patch.object(settings, "CORS_ORIGINS_RAW", "*"), patch.object(settings, "APP_ACCESS_ENABLED", False):
            app = runpy.run_path(str(Path(__file__).parents[1] / "app/main.py"))["app"]
            status, headers, body = await request(app, "/auth/status", headers={"origin": "https://frontend.test"})
        self.assertEqual(status, 200)
        self.assertEqual(headers[b"access-control-allow-origin"], b"https://frontend.test")
        self.assertEqual(headers[b"access-control-allow-credentials"], b"true")
        self.assertEqual(json.loads(body), {"enabled": False, "authenticated": True})

    def test_enabled_gate_fails_closed_for_invalid_settings(self):
        for changes in [{"APP_ACCESS_PASSWORD": ""}, {"APP_SESSION_SECRET": ""},
                        {"APP_SESSION_HOURS": 0}, {"cors_origins": ["*"]}]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                AccessControl(configuration(**changes))

    async def test_local_http_cookie_is_explicitly_opt_in(self):
        local = AccessControl(configuration(APP_COOKIE_SECURE=False))
        app = AccessControlMiddleware(self.downstream, local)
        status, headers, body = await request(app, "/auth/login", "POST", b'{"password":"test-only-long-password"}',
                                             {"origin": "https://thrivewell.test", "content-type": "application/json"})
        self.assertEqual(status, 200)
        self.assertNotIn(b"Secure", headers[b"set-cookie"])
        self.assertIn(b"thrivewell_session=", headers[b"set-cookie"])
