"""Account credentials are independent of manuscript records and never returned in lists."""
import hashlib
import hmac
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import psycopg
from fastapi import HTTPException


def token_hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def csrf_token(session: str) -> str:
    return hmac.new(session.encode(), b"xuzhang-browser-csrf-v1", hashlib.sha256).hexdigest()


def normalize_username(value: str) -> str:
    value = value.strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9_.-]{2,39}", value):
        raise ValueError("账号使用 3–40 位英文字母、数字、下划线、点或短横线，以字母或数字开头")
    return value


def hash_password(password: str) -> str:
    if not 6 <= len(password) <= 128:
        raise ValueError("密码长度须为 6–128 位")
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=32768, r=8, p=1, maxmem=64 * 1024 * 1024)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, salt, expected = encoded.split("$")
        if algorithm != "scrypt" or len(password) > 128:
            return False
        actual = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=32768, r=8, p=1, maxmem=64 * 1024 * 1024)
        return hmac.compare_digest(actual.hex(), expected)
    except (ValueError, TypeError):
        return False


# Unknown accounts still pay the password verification cost.
DUMMY_PASSWORD = "scrypt$" + "00" * 16 + "$" + "00" * 64


class Accounts:
    def __init__(self, store, settings):
        self.store, self.settings = store, settings

    @staticmethod
    def public(user):
        return {key: user[key] for key in ("id", "username", "display_name", "created_at")}

    def throttle(self, bucket: str, identity: str, limit: int, seconds: int):
        # PostgreSQL counters are shared by all workers; never trust a client-provided user id.
        with self.store.connection() as conn:
            conn.execute("DELETE FROM auth_attempts WHERE expires_at < now()")
            row = conn.execute("""INSERT INTO auth_attempts(key,count,expires_at)
                VALUES(%s,1,now() + %s * interval '1 second')
                ON CONFLICT(key) DO UPDATE SET count=auth_attempts.count+1 RETURNING count""",
                (token_hash(bucket + ":" + identity), seconds)).fetchone()
        if row["count"] > limit:
            raise HTTPException(429, "尝试次数过多，请稍后再试", headers={"Retry-After": str(seconds)})

    def create(self, username: str, password: str, display_name: str = ""):
        username = normalize_username(username)
        display_name = display_name.strip() or username
        if len(display_name) > 60:
            raise ValueError("显示名称最多 60 字")
        encoded = hash_password(password)
        try:
            with self.store.connection() as conn:
                row = conn.execute("""INSERT INTO users(id,username,display_name,password_hash)
                    VALUES(%s,%s,%s,%s) RETURNING *""", (uuid.uuid4().hex, username, display_name, encoded)).fetchone()
        except psycopg.errors.UniqueViolation as exc:
            raise HTTPException(409, "该账号名已被使用，请换一个账号名") from exc
        return self.public(row)

    def login(self, username: str, password: str):
        with self.store.connection() as conn:
            row = conn.execute("SELECT * FROM users WHERE username=%s FOR UPDATE", (username.strip().lower(),)).fetchone()
            valid = verify_password(password, row["password_hash"] if row else DUMMY_PASSWORD)
            if not row or not valid or not row["active"]:
                raise HTTPException(401, "账号或密码不正确")
            return self.public(row)

    def issue(self, user_id: str, kind: str, name: str = "浏览器", days: int | None = None, *, session_id: str | None = None):
        if kind not in {"api", "session"}:
            raise ValueError("凭证类型不合法")
        days = days if days is not None else self.settings.session_days
        raw = ("xz_mcp_" if kind == "api" else "xz_session_") + secrets.token_urlsafe(32)
        expiry = datetime.now(timezone.utc) + timedelta(days=days)
        with self.store.connection() as conn:
            user = conn.execute("SELECT active FROM users WHERE id=%s FOR UPDATE", (user_id,)).fetchone()
            if not user or not user["active"]:
                raise HTTPException(401, "账号不可用")
            if session_id and not conn.execute("""SELECT id FROM credentials WHERE id=%s AND user_id=%s
                    AND kind='session' AND revoked_at IS NULL AND expires_at>now()""", (session_id, user_id)).fetchone():
                raise HTTPException(401, "登录已失效，请重新登录")
            if kind == "api":
                count = conn.execute("SELECT count(*) AS n FROM credentials WHERE user_id=%s AND kind='api' AND revoked_at IS NULL AND expires_at>now()", (user_id,)).fetchone()["n"]
                if count >= 20:
                    raise HTTPException(422, "最多保留 20 个有效 MCP 密钥，请先撤销不再使用的密钥")
            row = conn.execute("""INSERT INTO credentials(id,token_hash,user_id,kind,name,expires_at)
                VALUES(%s,%s,%s,%s,%s,%s) RETURNING id,name,created_at,expires_at,last_used_at,revoked_at""",
                (uuid.uuid4().hex, token_hash(raw), user_id, kind, name, expiry)).fetchone()
        return raw, row

    def resolve(self, raw: str, kind: str):
        if not raw or len(raw) > 200:
            raise HTTPException(401, "请先登录，或提供有效的个人 MCP 密钥", headers={"WWW-Authenticate": "Bearer"})
        with self.store.connection() as conn:
            row = conn.execute("""SELECT u.id,u.username,u.display_name,u.created_at,c.id AS credential_id,c.kind
                FROM credentials c JOIN users u ON u.id=c.user_id
                WHERE c.token_hash=%s AND c.kind=%s AND c.revoked_at IS NULL AND c.expires_at>now() AND u.active""",
                (token_hash(raw), kind)).fetchone()
            if row:
                conn.execute("UPDATE credentials SET last_used_at=now() WHERE id=%s AND (last_used_at IS NULL OR last_used_at<now()-interval '5 minutes')", (row["credential_id"],))
        if not row:
            raise HTTPException(401, "登录已过期或密钥已失效，请重新登录或更换密钥", headers={"WWW-Authenticate": "Bearer"})
        return row

    def tokens(self, user_id: str):
        with self.store.connection() as conn:
            return conn.execute("""SELECT id,name,created_at,expires_at,last_used_at,revoked_at
                FROM credentials WHERE user_id=%s AND kind='api' ORDER BY created_at DESC""", (user_id,)).fetchall()

    def revoke(self, user_id: str, credential_id: str):
        with self.store.connection() as conn:
            row = conn.execute("UPDATE credentials SET revoked_at=COALESCE(revoked_at,now()) WHERE user_id=%s AND id=%s RETURNING id", (user_id, credential_id)).fetchone()
        if not row:
            raise HTTPException(404, "找不到该凭证")

    def change_password(self, user_id: str, old_password: str | None, new_password: str):
        encoded = hash_password(new_password)
        with self.store.connection() as conn:
            row = conn.execute("SELECT password_hash FROM users WHERE id=%s FOR UPDATE", (user_id,)).fetchone()
            if not row or (old_password is not None and not verify_password(old_password, row["password_hash"])):
                raise HTTPException(400, "当前密码不正确")
            conn.execute("UPDATE users SET password_hash=%s WHERE id=%s", (encoded, user_id))
            conn.execute("UPDATE credentials SET revoked_at=now() WHERE user_id=%s AND revoked_at IS NULL", (user_id,))

    def find(self, username: str):
        with self.store.connection() as conn:
            row = conn.execute("SELECT * FROM users WHERE username=%s", (normalize_username(username),)).fetchone()
        if not row:
            raise ValueError("账号不存在，请先注册或通过 accounts.py create 创建")
        return row

    def assign_legacy(self, user_id: str) -> int:
        with self.store.connection() as conn:
            if not conn.execute("SELECT id FROM users WHERE id=%s FOR UPDATE", (user_id,)).fetchone():
                raise ValueError("目标账号不存在")
            return conn.execute("UPDATE records SET owner_id=%s WHERE owner_id=''", (user_id,)).rowcount
