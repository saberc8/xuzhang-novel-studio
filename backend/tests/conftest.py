"""Every test gets a private PostgreSQL schema; production rows are never touched."""
import os
import uuid
import pytest
import psycopg
from psycopg import sql
from backend.app.config import Settings
from backend.app.store import Store, user_scope
from backend.app.auth import hash_password

DATABASE_URL = Settings().database_url
SESSION_SCHEMA = 'test_session_' + uuid.uuid4().hex
os.environ['NOVEL_DATABASE_SCHEMA'] = SESSION_SCHEMA
TEST_USER_ID = '1' * 32
TEST_PASSWORD = 'test-writer-password'
TEST_PASSWORD_HASH = hash_password(TEST_PASSWORD)


def sign_in(client):
    response = client.post('/api/auth/login', json={'username': 'test-writer', 'password': TEST_PASSWORD})
    assert response.status_code == 200, response.text
    client.headers['X-CSRF-Token'] = response.json()['csrf_token']
    return response.json()


@pytest.fixture(autouse=True)
def isolated_database(monkeypatch):
    schema = 'test_' + uuid.uuid4().hex
    monkeypatch.setenv('NOVEL_DATABASE_SCHEMA', schema)
    monkeypatch.setenv('NOVEL_DATABASE_URL', DATABASE_URL)
    monkeypatch.setenv('NOVEL_PRODUCTION', 'false')
    monkeypatch.setenv('NOVEL_REGISTRATION_ENABLED', 'true')
    monkeypatch.setenv('NOVEL_PUBLIC_URL', 'http://testserver')
    monkeypatch.setenv('NOVEL_ALLOWED_HOSTS', '["testserver", "localhost", "127.0.0.1"]')
    stores = []
    initialize = Store.__init__
    def tracked(self, *args, **kwargs):
        initialize(self, *args, **kwargs)
        stores.append(self)
        with self.connection() as conn:
            conn.execute('INSERT INTO users(id,username,display_name,password_hash) VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING',
                         (TEST_USER_ID, 'test-writer', '测试作者', TEST_PASSWORD_HASH))
    monkeypatch.setattr(Store, '__init__', tracked)
    with user_scope(TEST_USER_ID):
        yield
    for store in stores:
        store.close()
    with psycopg.connect(DATABASE_URL) as conn:
        conn.execute(sql.SQL('DROP SCHEMA IF EXISTS {} CASCADE').format(sql.Identifier(schema)))


def pytest_sessionfinish(session, exitstatus):
    from backend.app.main import app
    app.state.studio.store.close()
    with psycopg.connect(DATABASE_URL) as conn:
        conn.execute(sql.SQL('DROP SCHEMA IF EXISTS {} CASCADE').format(sql.Identifier(SESSION_SCHEMA)))
