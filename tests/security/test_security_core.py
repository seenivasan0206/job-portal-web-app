# -*- coding: utf-8 -*-
"""
Core Security Test Suite for SecureHire Job Portal
Covers:
- Authentication & Authorization role boundary enforcement
- CSRF token validation and rejection on state-modifying requests
- SQL injection payload safety across search and auth endpoints
- Exact 3-attempt account lockout triggering & 90-minute duration enforcement
- Healthcheck endpoint and security hygiene headers
"""

import io
import time
import pytest
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash
from app import (
    app, db_cursor, MAX_FAILED_ATTEMPTS, LOCKOUT_DURATION_MINUTES
)


@pytest.fixture
def client():
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    with app.test_client() as client:
        with app.app_context():
            yield client


@pytest.fixture
def csrf_client():
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = True
    with app.test_client() as client:
        with app.app_context():
            yield client


# ============================================================================
# 1. AUTHENTICATION & AUTHORIZATION ROLE BOUNDARY TESTS
# ============================================================================

def test_unauthenticated_candidate_route_access_rejected(client):
    """Accessing candidate endpoints without candidate session must redirect or return 401/403."""
    res = client.get('/candidate_dashboard', follow_redirects=False)
    assert res.status_code in [302, 401, 403]


def test_unauthenticated_employer_route_access_rejected(client):
    """Accessing employer endpoints without employer session must redirect or return 401/403."""
    res = client.get('/employer_dashboard', follow_redirects=False)
    assert res.status_code in [302, 401, 403]


def test_unauthenticated_admin_route_access_rejected(client):
    """Accessing admin endpoints without admin session must redirect or return 401/403."""
    res = client.get('/admin_dashboard', follow_redirects=False)
    assert res.status_code in [302, 401, 403]


def test_cross_role_candidate_cannot_access_employer_api(client):
    """A user logged in as a candidate cannot post jobs or perform employer actions."""
    with client.session_transaction() as sess:
        sess['user_id'] = 42
        sess['role'] = 'candidate'
        sess.pop('employer_id', None)

    res = client.post('/api/employer/post_job', json={'title': 'Hacker Role', 'description': 'Exploit'})
    assert res.status_code in [401, 403]


def test_cross_role_candidate_cannot_perform_admin_action(client):
    """A user logged in as a candidate cannot toggle user status on admin API."""
    with client.session_transaction() as sess:
        sess['user_id'] = 42
        sess['role'] = 'candidate'
        sess.pop('is_admin', None)

    res = client.post('/admin/users/10/ban')
    assert res.status_code in [302, 401, 403]


# ============================================================================
# 2. CSRF REJECTION ON STATE-MODIFYING REQUESTS
# ============================================================================

def test_state_modifying_post_rejected_without_csrf_token(csrf_client):
    """POST request without X-CSRFToken or csrf_token payload must return 400 Bad Request."""
    res = csrf_client.post(
        '/api/user/register',
        json={
            'full_name': 'Test User',
            'email': 'csrf_test@example.com',
            'password': 'Password123!',
            'role': 'candidate'
        }
    )
    assert res.status_code == 400
    data = res.get_json()
    assert data is not None
    assert data.get('success') is False
    assert 'CSRF' in data.get('message', '')


def test_state_modifying_post_rejected_with_invalid_csrf_token(csrf_client):
    """POST request with a forged/invalid CSRF token must return 400 Bad Request."""
    res = csrf_client.post(
        '/api/user/register',
        json={
            'full_name': 'Test User',
            'email': 'csrf_forgery@example.com',
            'password': 'Password123!',
            'role': 'candidate'
        },
        headers={'X-CSRFToken': 'invalid_forged_csrf_token_xyz'}
    )
    assert res.status_code == 400
    data = res.get_json()
    assert data is not None
    assert data.get('success') is False
    assert 'CSRF' in data.get('message', '')


# ============================================================================
# 3. SQL INJECTION PAYLOAD RESISTANCE
# ============================================================================

@pytest.mark.parametrize("sqli_payload", [
    "' OR '1'='1",
    "' OR 1=1 --",
    "admin' --",
    "' UNION SELECT null, null, null --",
    "'; DROP TABLE users; --",
])
def test_job_search_sql_injection_safety(client, sqli_payload):
    """Search endpoints with aggressive SQL injection strings return clean JSON without errors."""
    # API Search
    res_api = client.post('/api/jobs/search', json={'title': sqli_payload})
    assert res_api.status_code == 200
    data = res_api.get_json()
    assert data.get('success') is True
    assert 'syntax error' not in str(res_api.data).lower()
    assert 'sql syntax' not in str(res_api.data).lower()

    # Web View Search
    res_page = client.get(f'/jobs?keyword={sqli_payload}')
    assert res_page.status_code in [200, 302]
    assert 'syntax error' not in str(res_page.data).lower()


def test_login_sql_injection_safety(client):
    """Login with SQL injection string in email field is handled safely via parameterized query."""
    res = client.post(
        '/api/user/login',
        json={'email': "' OR '1'='1' --", 'password': 'random_password'}
    )
    assert res.status_code in [200, 400, 401, 403, 429]
    data = res.get_json()
    assert data.get('success') is False
    assert 'syntax error' not in str(res.data).lower()


# ============================================================================
# 4. EXACT 3-ATTEMPT ACCOUNT LOCKOUT & 90-MINUTE DURATION
# ============================================================================

def test_account_lockout_after_three_failed_attempts(client):
    """Verify that after exactly 3 failed attempts, account is locked for 90 minutes."""
    ts = int(time.time())
    test_email = f"lockout_core_{ts}@example.com"
    test_password = "CorrectPass123!"

    assert MAX_FAILED_ATTEMPTS == 3
    assert LOCKOUT_DURATION_MINUTES == 90

    # Insert test candidate
    with db_cursor() as cur:
        cur.execute("DELETE FROM user WHERE email = %s", (test_email,))
        cur.execute("DELETE FROM login_attempts WHERE email = %s", (test_email,))
        cur.execute("DELETE FROM rate_limits WHERE rate_key LIKE %s", (f"{test_email}%",))
        cur.execute(
            "INSERT INTO user (name, email, mobile, password, is_verified) VALUES (%s, %s, %s, %s, %s)",
            ("Test Lockout", test_email, "9876543210", generate_password_hash(test_password), True)
        )

    try:
        # Attempt 1: Fail -> 2 remaining
        r1 = client.post('/api/user/login', json={'email': test_email, 'password': 'WrongPassword1'})
        d1 = r1.get_json()
        assert d1.get('success') is False
        assert '2 attempts remaining' in d1.get('message', '')

        # Attempt 2: Fail -> 1 remaining
        r2 = client.post('/api/user/login', json={'email': test_email, 'password': 'WrongPassword2'})
        d2 = r2.get_json()
        assert d2.get('success') is False
        assert '1 attempts remaining' in d2.get('message', '')

        # Attempt 3: Fail -> Account locked for 90 minutes
        r3 = client.post('/api/user/login', json={'email': test_email, 'password': 'WrongPassword3'})
        d3 = r3.get_json()
        assert r3.status_code == 429
        assert d3.get('success') is False
        assert 'Account locked due to too many failed attempts' in d3.get('message', '')
        assert '90 minutes' in d3.get('message', '')

        # Attempt 4: 4th attempt blocked immediately even with correct password
        r4 = client.post('/api/user/login', json={'email': test_email, 'password': test_password})
        d4 = r4.get_json()
        assert r4.status_code == 429
        assert d4.get('success') is False
        assert 'Account locked' in d4.get('message', '')

    finally:
        with db_cursor() as cur:
            cur.execute("DELETE FROM user WHERE email = %s", (test_email,))
            cur.execute("DELETE FROM login_attempts WHERE email = %s", (test_email,))
            cur.execute("DELETE FROM rate_limits WHERE rate_key LIKE %s", (f"{test_email}%",))


# ============================================================================
# 5. HEALTH CHECK & SECURITY HYGIENE
# ============================================================================

def test_healthz_endpoint_returns_200(client):
    """GET /healthz returns status 200 with healthy database indicator."""
    res = client.get('/healthz')
    assert res.status_code == 200
    data = res.get_json()
    assert data['status'] == 'healthy'
    assert 'database' in data['services']
    assert data['services']['database']['status'] == 'healthy'
    assert 'latency_ms' in data['services']['database']


def test_security_headers_present(client):
    """Responses contain security hygiene headers (X-Content-Type-Options, X-Frame-Options, etc.)."""
    res = client.get('/')
    assert res.status_code == 200
    headers = res.headers
    assert headers.get('X-Content-Type-Options') == 'nosniff'
    assert headers.get('X-Frame-Options') in ['SAMEORIGIN', 'DENY']
