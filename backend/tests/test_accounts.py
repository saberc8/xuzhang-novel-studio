"""Real database and HTTP tests for the multi-user trust boundary, including MCP."""
from concurrent.futures import ThreadPoolExecutor

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql
from psycopg.types.json import Jsonb

from backend.app.auth import csrf_token, token_hash, verify_password
from backend.app.auth_api import COOKIE
from backend.app.config import Settings
from backend.app.main import create_app
from backend.app.store import user_scope
from conftest import TEST_PASSWORD, TEST_USER_ID, sign_in
from test_adaptation import workspace
from test_editorial import editorial, create, write, freeze

# Exercise the minimum-length numeric password through registration and changes.
PASSWORD = "123456"


def register(client, username="second-author"):
    result = client.post("/api/auth/register", json={"username": username, "password": PASSWORD, "display_name": "第二位作者"})
    assert result.status_code == 201, result.text
    client.headers["X-CSRF-Token"] = result.json()["csrf_token"]
    return result.json()["user"]


def issue(client, name="我的 Codex"):
    result = client.post("/api/auth/tokens", json={"name": name})
    assert result.status_code == 201, result.text
    return result.json()


def upload(client, title="属于我的故事"):
    response = client.post("/api/books", files={"file": (title + ".txt", "第一章\n码头边，一封信改变了故事。".encode())})
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.parametrize("path", ["/api/books", "/api/system", "/api/adaptations", "/api/auth/me", "/api/auth/tokens",
                                 "/api/books/known/original", "/api/adaptation-versions/known/export",
                                 "/api/editorial-reviews/known/context", "/api/editorial-editions/known/export", "/mcp/"])
def test_anonymous_requests_fail_closed(tmp_path, path):
    with TestClient(create_app(tmp_path)) as client:
        assert client.get(path).status_code == 401
        assert client.get("/api/health").status_code == 200


def test_registration_hashing_cookie_csrf_and_logout(tmp_path):
    app = create_app(tmp_path)
    with TestClient(app) as client:
        user = register(client, "New.Author")
        assert user["username"] == "new.author" and "password_hash" not in user
        raw = client.cookies[COOKIE]
        assert csrf_token(raw) == client.headers["X-CSRF-Token"]
        with app.state.studio.store.connection() as conn:
            stored = conn.execute("SELECT password_hash FROM users WHERE id=%s", (user["id"],)).fetchone()
            credential = conn.execute("SELECT token_hash FROM credentials WHERE user_id=%s", (user["id"],)).fetchone()
        assert verify_password(PASSWORD, stored["password_hash"]) and PASSWORD not in stored["password_hash"]
        assert credential["token_hash"] == token_hash(raw) and credential["token_hash"] != raw
        assert client.post("/api/auth/register", json={"username": "NEW.AUTHOR", "password": PASSWORD}).status_code == 409
        assert client.post("/api/auth/register", json={"username": "bad", "password": "short"}).status_code == 422
        assert client.get("/api/auth/me").json()["user"]["id"] == user["id"]
        assert client.post("/api/auth/logout", json={}).status_code == 200
        assert client.get("/api/books", headers={"Cookie": f"{COOKIE}={raw}"}).status_code == 401
        login = client.post("/api/auth/login", json={"username": "new.author", "password": PASSWORD})
        assert login.status_code == 200 and client.cookies[COOKIE] != raw
        cookie = login.headers["set-cookie"].lower()
        assert "httponly" in cookie and "samesite=lax" in cookie and "path=/api" in cookie
        assert login.headers["cache-control"] == "no-store"


def test_csrf_origin_and_account_management_are_not_bearer_capabilities(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        sign_in(client)
        assert client.post("/api/demo", headers={"X-CSRF-Token": "bad"}).status_code == 403
        assert client.post("/api/demo", headers={"Origin": "https://evil.example"}).status_code == 403
        token = issue(client)
        bearer = {"Authorization": "Bearer " + token["token"]}
        assert client.get("/api/books", headers=bearer).status_code == 200
        assert client.post("/api/auth/tokens", json={"name": "cannot mint"}, headers=bearer).status_code == 403
        assert client.post("/api/auth/password", json={"current_password": TEST_PASSWORD, "new_password": PASSWORD}, headers=bearer).status_code == 403
        assert client.post("/api/auth/login", json={"username": "test-writer", "password": TEST_PASSWORD}, headers={"Origin": "https://evil.example"}).status_code == 403
        assert client.post("/api/auth/login", content='{"username":"test-writer","password":"test"}', headers={"Content-Type": "text/plain"}).status_code == 415


def test_two_accounts_cannot_read_download_or_modify_each_others_books_and_projects(tmp_path):
    app = create_app(tmp_path)
    with TestClient(app) as client:
        sign_in(client)
        book = upload(client)
        project_body = {"name": "我的改编", "chapter_ids": ["ch0001"], "brief": {"idea": "重写港口来信", "target_units": 1}}
        project = client.post(f"/api/books/{book['id']}/adaptations", json=project_body).json()
        source = client.get(f"/api/books/{book['id']}/original").content
        assert (tmp_path / "users" / TEST_USER_ID / book["id"] / "original.txt").read_bytes() == source
        assert client.get(f"/api/adaptations/{project['id']}").status_code == 200
        user2 = register(client)
        assert client.get("/api/books").json() == []
        assert client.get("/api/adaptations").json() == []
        assert client.get("/api/adaptations", params={"book_id": book["id"]}).status_code == 404
        for path in [f"/api/books/{book['id']}", f"/api/books/{book['id']}/chapters/ch0001", f"/api/books/{book['id']}/original", f"/api/adaptations/{project['id']}", f"/api/adaptations/{project['id']}/context"]:
            assert client.get(path).status_code == 404, path
        assert client.put(f"/api/books/{book['id']}/source", json={"title": "入侵"}).status_code == 404
        assert client.post(f"/api/books/{book['id']}/adaptations", json=project_body).status_code == 404
        own_book = upload(client, "另一个人的故事")
        assert client.post(f"/api/books/{own_book['id']}/adaptations", json={**project_body, "owner_id": TEST_USER_ID}).status_code == 422
        assert (tmp_path / "users" / user2["id"] / own_book["id"] / "original.txt").exists()
        sign_in(client)
        assert [b["id"] for b in client.get("/api/books").json()] == [book["id"]]
        assert client.get(f"/api/books/{book['id']}/original").content == source


def test_api_token_is_personal_revocable_and_time_limited(tmp_path):
    app = create_app(tmp_path)
    with TestClient(app) as client:
        sign_in(client)
        first = upload(client)
        token = issue(client)
        authorization = {"Authorization": "Bearer " + token["token"]}
        listed = client.get("/api/auth/tokens").json()
        assert listed[0]["id"] == token["id"] and "token" not in listed[0] and "token_hash" not in listed[0]
        register(client)
        assert client.get("/api/books").json() == []
        assert client.get("/api/books", headers=authorization).json()[0]["id"] == first["id"]
        assert client.delete(f"/api/auth/tokens/{token['id']}").status_code == 404
        sign_in(client)
        assert client.delete(f"/api/auth/tokens/{token['id']}").status_code == 200
        assert client.get("/api/books", headers=authorization).status_code == 401
        expired = issue(client, "即将过期")
        with app.state.studio.store.connection() as conn:
            conn.execute("UPDATE credentials SET expires_at=now()-interval '1 second' WHERE id=%s", (expired["id"],))
        assert client.get("/api/books", headers={"Authorization": "Bearer " + expired["token"]}).status_code == 401
        assert client.get("/api/books", headers={"Authorization": "Bearer " + client.cookies[COOKIE]}).status_code == 401


def test_password_change_revokes_every_session_and_mcp_token(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        sign_in(client)
        session1 = client.cookies[COOKIE]
        token = issue(client)
        sign_in(client)
        assert client.post("/api/auth/password", json={"current_password": TEST_PASSWORD, "new_password": "12345"}).status_code == 422
        response = client.post("/api/auth/password", json={"current_password": TEST_PASSWORD, "new_password": PASSWORD})
        assert response.status_code == 200 and not client.cookies.get(COOKIE)
        assert client.get("/api/books", headers={"Cookie": f"{COOKIE}={session1}"}).status_code == 401
        assert client.get("/api/books", headers={"Authorization": "Bearer " + token["token"]}).status_code == 401
        assert client.post("/api/auth/login", json={"username": "test-writer", "password": TEST_PASSWORD}).status_code == 401
        assert client.post("/api/auth/login", json={"username": "test-writer", "password": PASSWORD}).status_code == 200


def test_registration_switch_and_shared_rate_limit(tmp_path, monkeypatch):
    monkeypatch.setenv("NOVEL_REGISTRATION_ENABLED", "false")
    app = create_app(tmp_path)
    with TestClient(app) as client:
        assert client.get("/api/auth/config").json() == {"registration_enabled": False}
        assert client.post("/api/auth/register", json={"username": "blocked", "password": PASSWORD}).status_code == 403
        for _ in range(15):
            assert client.post("/api/auth/login", json={"username": "not-a-user", "password": "wrong"}).status_code == 401
        response = client.post("/api/auth/login", json={"username": "not-a-user", "password": "wrong"})
        assert response.status_code == 429 and response.headers["retry-after"]


def test_session_revoked_between_authentication_and_token_issue_is_rechecked(tmp_path, monkeypatch):
    app = create_app(tmp_path)
    with TestClient(app) as client:
        sign_in(client)
        original = app.state.accounts.issue
        def revoked_before_issue(*args, **kwargs):
            with app.state.studio.store.connection() as conn:
                conn.execute("UPDATE credentials SET revoked_at=now() WHERE id=%s", (kwargs["session_id"],))
            return original(*args, **kwargs)
        monkeypatch.setattr(app.state.accounts, "issue", revoked_before_issue)
        assert client.post("/api/auth/tokens", json={"name": "过期请求"}).status_code == 401
        assert app.state.accounts.tokens(TEST_USER_ID) == []


def test_legacy_schema_is_quarantined_until_explicit_assignment(tmp_path):
    settings = Settings()
    with psycopg.connect(settings.database_url) as conn:
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(settings.database_schema)))
        conn.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(settings.database_schema)))
        conn.execute("""CREATE TABLE records (kind TEXT,id TEXT,payload JSONB,sequence BIGINT GENERATED ALWAYS AS IDENTITY,
            updated_at TIMESTAMPTZ DEFAULT now(), PRIMARY KEY(kind,id))""")
        conn.execute("INSERT INTO records(kind,id,payload) VALUES('book','legacy',%s)", (Jsonb({"id": "legacy", "chapters": [], "title": "旧书架"}),))
    app = create_app(tmp_path)
    with TestClient(app) as client:
        register(client, "first-registration")
        assert client.get("/api/books").json() == []
        assert client.get("/api/books/legacy").status_code == 404
        assert app.state.accounts.assign_legacy(TEST_USER_ID) == 1
        assert app.state.accounts.assign_legacy(TEST_USER_ID) == 0
        assert client.get("/api/books/legacy").status_code == 404
        sign_in(client)
        assert client.get("/api/books").json()[0]["title"] == "旧书架"


def test_store_requires_identity_and_isolates_identical_ids(workspace):
    studio, _, _ = workspace
    store = studio.store
    store.put("counter", {"id": "same", "value": "first"})
    with user_scope("2" * 32):
        assert store.list("counter") == []
        with pytest.raises(KeyError):
            store.mutate("counter", "same", lambda value: value.update(value="intrusion"))
        store.put("counter", {"id": "same", "value": "second"})
        assert store.get("counter", "same")["value"] == "second"
    assert store.get("counter", "same")["value"] == "first"
    with ThreadPoolExecutor(1) as pool, pytest.raises(PermissionError):
        pool.submit(store.list, "book").result()


def test_completed_versions_editorial_and_rewrites_share_the_owner_boundary(editorial, tmp_path):
    service, _, source = editorial
    review = write(service, "run_checks", create(service, source, depth="scan"))
    review = freeze(service, review)
    with TestClient(create_app(tmp_path)) as client:
        sign_in(client)
        paths = [f"/api/adaptation-versions/{source['project_id']}/export?format=json",
                 f"/api/adaptations/{source['project_id']}/editorial-source",
                 f"/api/editorial-reviews/{review['id']}", f"/api/editorial-reviews/{review['id']}/context",
                 f"/api/editorial-reviews/{review['id']}/records", f"/api/editorial-reviews/{review['id']}/story",
                 f"/api/editorial-editions/{review['edition_id']}", f"/api/editorial-editions/{review['edition_id']}/export?format=zip"]
        for path in paths:
            assert client.get(path).status_code == 200, path
        register(client)
        for path in paths:
            assert client.get(path).status_code == 404, path
        assert client.post(f"/api/adaptations/{source['project_id']}/editorial-reviews", json={
            "name": "越权审稿", "source_release_sha256": source["source_release_sha256"], "request_id": "intrusion"}).status_code == 404
        from test_rewriting import rewrite_request
        assert client.post(f"/api/adaptations/{source['project_id']}/deep-rewrites", json=rewrite_request()).status_code == 404


def rpc(client, token, method, params=None):
    return client.post("/mcp/", headers={"Authorization": "Bearer " + token, "Accept": "application/json, text/event-stream"},
                       json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}})


def test_remote_mcp_auth_is_per_request_and_cannot_import_server_files(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        sign_in(client)
        first = upload(client, "第一位作者")
        first_token = issue(client)["token"]
        register(client)
        second = upload(client, "第二位作者")
        second_token = issue(client)["token"]
        assert rpc(client, "bad-token", "tools/list").status_code == 401
        initialized = rpc(client, first_token, "initialize", {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}})
        assert initialized.status_code == 200, initialized.text
        tools = rpc(client, first_token, "tools/list").json()["result"]["tools"]
        assert len(tools) == 39 and "import_novel" not in {tool["name"] for tool in tools}
        def check(pair):
            token, own, foreign = pair
            response = rpc(client, token, "tools/call", {"name": "list_books", "arguments": {}})
            assert response.status_code == 200, response.text
            assert not response.json()["result"].get("isError"), response.text
            assert own in response.text and foreign not in response.text
        with ThreadPoolExecutor(4) as pool:
            list(pool.map(check, [(first_token, first["id"], second["id"]), (second_token, second["id"], first["id"])] * 5))
        forbidden = rpc(client, second_token, "tools/call", {"name": "get_book", "arguments": {"book_id": first["id"]}}).json()
        assert forbidden["result"]["isError"] is True
        assert rpc(client, second_token, "tools/call", {"name": "import_novel", "arguments": {"path": "/etc/passwd"}}).json()["result"]["isError"]
        sign_in(client)
        token_id = client.get("/api/auth/tokens").json()[0]["id"]
        client.delete(f"/api/auth/tokens/{token_id}")
        assert rpc(client, first_token, "tools/list").status_code == 401


def test_production_requires_https_and_secure_cookie(tmp_path, monkeypatch):
    with pytest.raises(ValueError, match="HTTPS"):
        Settings(production=True, public_url="http://example.com")
    monkeypatch.setenv("NOVEL_PRODUCTION", "true")
    monkeypatch.setenv("NOVEL_PUBLIC_URL", "https://novel.example.com")
    with TestClient(create_app(tmp_path), base_url="https://novel.example.com") as client:
        response = client.post("/api/auth/login", json={"username": "test-writer", "password": TEST_PASSWORD})
        assert response.status_code == 200 and "Secure" in response.headers["set-cookie"]
        assert client.get("/api/books").status_code == 200
        assert client.get("/api/system").json()["mcp"]["url"] == "https://novel.example.com/mcp/"
        assert client.get("/api/health", headers={"Host": "evil.example"}).status_code == 400
