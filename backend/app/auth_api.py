"""Cookie sessions for the browser, bearer credentials for API / remote MCP clients."""
import hmac
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from .auth import csrf_token
from .store import user_scope

COOKIE = "xuzhang_session"
PUBLIC = {"/api/health", "/api/auth/config", "/api/auth/register", "/api/auth/login"}
SAFE = {"GET", "HEAD", "OPTIONS"}


class Login(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=3, max_length=40)
    password: str = Field(min_length=1, max_length=128)


class Register(Login):
    display_name: str = Field(default="", max_length=60)
    password: str = Field(min_length=6, max_length=128)


class NewToken(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=80)
    expires_days: int = Field(default=90, ge=1, le=365)


class PasswordChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=6, max_length=128)


class AuthenticationMiddleware:
    def __init__(self, app, accounts, settings):
        self.app, self.accounts, self.settings = app, accounts, settings

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        request = Request(scope)
        path = scope["path"].rstrip("/")
        is_mcp = path == "/mcp" or path.startswith("/mcp/")
        if not (path == "/api" or path.startswith("/api/") or is_mcp):
            return await self.app(scope, receive, send)

        async def private_send(message):
            if message["type"] == "http.response.start":
                message["headers"] = [*message.get("headers", []), (b"cache-control", b"no-store"),
                                      (b"x-content-type-options", b"nosniff"), (b"referrer-policy", b"no-referrer")]
            await send(message)

        try:
            authorization = request.headers.get("authorization", "")
            bearer = authorization.lower().startswith("bearer ")
            raw = authorization[7:] if bearer else request.cookies.get(COOKIE, "")
            if request.method not in SAFE and not bearer:
                origin = request.headers.get("origin")
                allowed = {*self.settings.allowed_origins, self.settings.public_url, str(request.base_url).rstrip("/")}
                if origin and origin not in allowed:
                    raise HTTPException(403, "请求来源不受信任")
                if request.headers.get("sec-fetch-site") == "cross-site" and not origin:
                    raise HTTPException(403, "请求来源不受信任")
            if path in PUBLIC:
                if path in {"/api/auth/login", "/api/auth/register"} and request.method == "POST":
                    if request.headers.get("content-type", "").split(";")[0] != "application/json":
                        raise HTTPException(415, "请使用 JSON 提交登录或注册")
                return await self.app(scope, receive, private_send)
            if is_mcp and not bearer:
                raise HTTPException(401, "MCP 连接需要个人密钥", headers={"WWW-Authenticate": "Bearer"})
            if authorization and not bearer:
                raise HTTPException(401, "请使用 Bearer 密钥")
            user = await run_in_threadpool(self.accounts.resolve, raw, "api" if bearer else "session")
            if bearer and path.startswith("/api/auth/"):
                raise HTTPException(403, "账号与密钥管理需要网页登录")
            if not bearer and request.method not in SAFE:
                if not hmac.compare_digest(request.headers.get("x-csrf-token", ""), csrf_token(raw)):
                    raise HTTPException(403, "安全校验失败，请刷新页面后重试")
            request.state.user = user
            request.state.session = raw if not bearer else None
            with user_scope(user["id"]):
                await self.app(scope, receive, private_send)
        except HTTPException as exc:
            await JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers)(scope, receive, private_send)


def auth_router(accounts, settings):
    router = APIRouter(prefix="/api/auth")

    def login_response(user, response):
        token, _ = accounts.issue(user["id"], "session")
        response.set_cookie(COOKIE, token, max_age=settings.session_days * 86400, httponly=True,
                            secure=settings.production, samesite="lax", path="/api")
        return {"user": user, "csrf_token": csrf_token(token)}

    def address(request):
        # Uvicorn handles forwarded addresses only from explicitly trusted proxies.
        return request.client.host if request.client else "unknown"

    @router.get("/config")
    def config():
        return {"registration_enabled": settings.registration_enabled}

    @router.post("/register", status_code=201)
    def register(body: Register, request: Request, response: Response):
        if not settings.registration_enabled:
            raise HTTPException(403, "目前未开放注册，请联系站点管理员创建账号")
        accounts.throttle("register", address(request), 10, 3600)
        return login_response(accounts.create(body.username, body.password, body.display_name), response)

    @router.post("/login")
    def login(body: Login, request: Request, response: Response):
        accounts.throttle("login-ip", address(request), 60, 900)
        accounts.throttle("login-name", body.username.strip().lower(), 15, 900)
        # Keep password verification and session issuance in one row-locked transaction,
        # so a concurrent password reset cannot be followed by an old-password login.
        with accounts.store.connection():
            return login_response(accounts.login(body.username, body.password), response)

    @router.get("/me")
    def me(request: Request):
        return {"user": accounts.public(request.state.user), "csrf_token": csrf_token(request.state.session)}

    @router.post("/logout")
    def logout(request: Request, response: Response):
        accounts.revoke(request.state.user["id"], request.state.user["credential_id"])
        response.delete_cookie(COOKIE, path="/api", secure=settings.production, httponly=True, samesite="lax")
        return {"ok": True}

    @router.post("/password")
    def password(body: PasswordChange, request: Request, response: Response):
        accounts.throttle("password", request.state.user["id"], 10, 900)
        accounts.change_password(request.state.user["id"], body.current_password, body.new_password)
        response.delete_cookie(COOKIE, path="/api", secure=settings.production, httponly=True, samesite="lax")
        return {"ok": True}

    @router.get("/tokens")
    def tokens(request: Request):
        return accounts.tokens(request.state.user["id"])

    @router.post("/tokens", status_code=201)
    def create_token(body: NewToken, request: Request):
        name = body.name.strip()
        if not name:
            raise ValueError("请填写密钥名称")
        raw, token = accounts.issue(request.state.user["id"], "api", name, body.expires_days,
                                    session_id=request.state.user["credential_id"])
        return {**token, "token": raw}

    @router.delete("/tokens/{token_id}")
    def revoke_token(token_id: str, request: Request):
        accounts.revoke(request.state.user["id"], token_id)
        return {"ok": True}

    return router
