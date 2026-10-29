"""Offline end-to-end backend tests. All AI calls are mocked in tests only."""
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app import main, ai
from backend.app.config import settings
from backend.app.database import Base, get_db, EmailOtp, utcnow

@pytest.fixture
def client(monkeypatch):
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    SessionForTest = sessionmaker(engine, expire_on_commit=False)
    def override_db():
        with SessionForTest() as db:
            yield db
    main.app.dependency_overrides[get_db] = override_db
    main._buckets.clear()
    monkeypatch.setattr(settings, 'app_secret', 'unit-test-app-secret-that-is-long-enough')
    codes = {}
    monkeypatch.setattr(main, 'send_otp', lambda email, code: codes.update({email: code}))
    with TestClient(main.app) as test_client:
        yield test_client, codes, SessionForTest
    main.app.dependency_overrides.clear()
    engine.dispose()


def sign_in(client, codes, email=None):
    email = email or f'user-{uuid4().hex[:8]}@example.com'
    client.get('/api/auth/csrf')
    csrf = client.cookies.get('ps_csrf')
    headers = {'X-CSRF-Token': csrf}
    response = client.post('/api/auth/email/request', json={'email': email}, headers=headers)
    assert response.status_code == 200, response.text
    code = codes[email]
    response = client.post('/api/auth/email/verify', json={'email': email, 'otp': code}, headers=headers)
    assert response.status_code == 200, response.text
    return headers, email


def test_health_and_public_page(client):
    c, _, _ = client
    assert c.get('/api/health').json()['ok'] is True
    assert 'PromptSutra' in c.get('/').text
    assert c.get('/api/auth/me').status_code == 401


def test_csrf_and_otp_login(client):
    c, codes, _ = client
    assert c.post('/api/conversations', json={'category': 'General'}).status_code == 403
    headers, email = sign_in(c, codes)
    assert c.get('/api/auth/me').json()['user']['email'] == email
    assert c.post('/api/auth/email/verify', json={'email': email, 'otp': codes[email]}, headers=headers).status_code == 400
    assert c.post('/api/auth/logout', headers=headers).status_code == 200
    assert c.get('/api/auth/me').status_code == 401


def test_wrong_code_and_expiry(client):
    c, codes, session_factory = client
    c.get('/api/auth/csrf'); h = {'X-CSRF-Token': c.cookies.get('ps_csrf')}
    email = f'test-{uuid4().hex[:8]}@example.com'
    assert c.post('/api/auth/email/request', json={'email': email}, headers=h).status_code == 200
    assert c.post('/api/auth/email/verify', json={'email': email, 'otp': '999999' if codes[email] != '999999' else '888888'}, headers=h).status_code == 400
    with session_factory() as db:
        row = db.query(EmailOtp).filter(EmailOtp.email==email).one()
        from datetime import timedelta
        row.expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    assert c.post('/api/auth/email/verify', json={'email': email, 'otp': codes[email]}, headers=h).status_code == 400


def test_chats_prompts_refinements_and_versions(client, monkeypatch):
    c, codes, _ = client
    h, _ = sign_in(c, codes)
    monkeypatch.setattr(ai, 'interview', lambda messages, category: ai.InterviewReply(assistant_message='What features should it have?', ready_to_generate=False))
    monkeypatch.setattr(ai, 'generate_prompt', lambda *args: 'Create a secure college management platform with student login.')
    monkeypatch.setattr(ai, 'refine_prompt', lambda old_content, instructions: old_content + '\nInclude role-based authentication.')
    response = c.post('/api/conversations', json={'category': 'Website Development'}, headers=h)
    assert response.status_code == 200
    id_ = response.json()['conversation']['id']
    res = c.post(f'/api/conversations/{id_}/messages', json={'content': 'College management app'}, headers=h)
    assert res.status_code == 200 and 'features' in res.json()['message']['content']
    assert len(c.get(f'/api/conversations/{id_}').json()['messages']) == 2
    r = c.post(f'/api/conversations/{id_}/generate', json={'language': 'English'}, headers=h)
    assert r.status_code == 200
    p = r.json()['prompt']; assert p['version'] == 1
    assert c.get('/api/prompts').json()['prompts'][0]['id'] == p['id']
    r = c.post(f'/api/prompts/{p["id"]}/refine', json={'instruction': 'Please add roles'}, headers=h)
    assert r.status_code == 200 and r.json()['prompt']['version'] == 2
    r = c.patch(f'/api/prompts/{p["id"]}', json={'favorite': True}, headers=h)
    assert r.status_code == 200 and r.json()['prompt']['favorite']
    assert len(c.get(f'/api/prompts/{p["id"]}/versions').json()['versions']) == 2
    assert c.delete(f'/api/conversations/{id_}', headers=h).status_code == 200
    assert c.get(f'/api/prompts/{p["id"]}').status_code == 404


def test_user_data_is_private(client):
    c, codes, _ = client
    h, first = sign_in(c, codes)
    c_id = c.post('/api/conversations', json={'category':'General'}, headers=h).json()['conversation']['id']
    c.post('/api/auth/logout', headers=h)
    h2, _ = sign_in(c, codes)
    assert c.get(f'/api/conversations/{c_id}').status_code == 404
    assert c.delete(f'/api/conversations/{c_id}', headers=h2).status_code == 404
    assert c.get('/api/conversations').json()['conversations'] == []
