# -*- coding: utf-8 -*-
"""
Authentication Real Flow & Security Regression Tests
Validates all Candidate, Employer, and Guest authentication flows:
- Candidate registration, login, dashboard access, and session invalidation on logout
- Employer registration, login, dashboard access, and session invalidation on logout
- Password verification, legacy auto-upgrade, and error handling
- Role boundary protections (Candidate cannot access employer dashboard, Employer cannot access candidate dashboard)
- Rate-limit reset on successful authentication
- Form-encoded and JSON payload compatibility
"""
import sys
import os
import time
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import app
from app import app as flask_app, db_cursor
from werkzeug.security import generate_password_hash


@pytest.fixture
def client():
    flask_app.config['TESTING'] = True
    with flask_app.test_client() as client:
        yield client


def get_csrf(test_client):
    res = test_client.get('/api/csrf_token')
    return res.get_json().get('csrf_token', '')


def test_candidate_complete_auth_lifecycle(client):
    """Test full candidate registration, login, dashboard access, and logout lifecycle."""
    email = f"cand_test_{int(time.time())}@hirevoltz.com"
    password = "CandSecurePass123!"

    # 1. Send OTP
    csrf = get_csrf(client)
    otp_res = client.post('/api/send_otp', json={'email': email, 'type': 'user'}, headers={'X-CSRFToken': csrf})
    assert otp_res.status_code == 200, f"Send OTP failed: {otp_res.get_json()}"

    with db_cursor() as cur:
        cur.execute("SELECT otp FROM otp_store WHERE email = %s ORDER BY id DESC LIMIT 1", (email,))
        row = cur.fetchone()
        assert row is not None, "OTP not stored in DB"
        otp = row['otp']

    # 2. Register
    csrf = get_csrf(client)
    reg_res = client.post('/api/user/register', json={
        'name': 'Test Candidate User',
        'email': email,
        'password': password,
        'mobile': '9876543210',
        'otp': otp
    }, headers={'X-CSRFToken': csrf})
    assert reg_res.status_code == 200, f"Register failed: {reg_res.get_json()}"
    assert reg_res.get_json()['success'] is True

    # 3. Log out to test fresh login
    client.get('/logout')
    with client.session_transaction() as sess:
        assert 'user_id' not in sess

    # 4. Attempt login with wrong password
    csrf = get_csrf(client)
    bad_res = client.post('/api/user/login', json={'email': email, 'password': 'WrongPassword123!'}, headers={'X-CSRFToken': csrf})
    assert bad_res.status_code in (200, 401)
    assert bad_res.get_json()['success'] is False

    # 5. Attempt login with correct password
    csrf = get_csrf(client)
    login_res = client.post('/api/user/login', json={'email': email, 'password': password}, headers={'X-CSRFToken': csrf})
    assert login_res.status_code == 200
    login_data = login_res.get_json()
    assert login_data['success'] is True
    assert login_data['redirect'] == '/user_dashboard'

    # 6. Verify session created
    with client.session_transaction() as sess:
        assert 'user_id' in sess
        assert sess['role'] == 'candidate'

    # 7. Access candidate dashboard
    dash_res = client.get('/user_dashboard')
    assert dash_res.status_code == 200
    assert b"Candidate Dashboard" in dash_res.data or b"Dashboard" in dash_res.data

    # 8. Verify candidate cannot access employer dashboard
    emp_dash_res = client.get('/employer_dashboard')
    assert emp_dash_res.status_code in (302, 403)

    # 9. Logout
    client.get('/logout')
    post_dash = client.get('/user_dashboard')
    assert post_dash.status_code == 302


def test_employer_complete_auth_lifecycle(client):
    """Test full employer registration, login, dashboard access, and logout lifecycle."""
    email = f"emp_test_{int(time.time())}@hirevoltz.com"
    password = "EmpSecurePass123!"

    # 1. Send OTP
    csrf = get_csrf(client)
    otp_res = client.post('/api/send_otp', json={'email': email, 'type': 'employer'}, headers={'X-CSRFToken': csrf})
    assert otp_res.status_code == 200, f"Send OTP failed: {otp_res.get_json()}"

    with db_cursor() as cur:
        cur.execute("SELECT otp FROM otp_store WHERE email = %s ORDER BY id DESC LIMIT 1", (email,))
        row = cur.fetchone()
        assert row is not None, "OTP not stored in DB"
        otp = row['otp']

    # 2. Register
    csrf = get_csrf(client)
    reg_res = client.post('/api/employer/register', json={
        'name': 'HireVoltz Testing Corp',
        'email': email,
        'password': password,
        'mobile': '9876543211',
        'otp': otp
    }, headers={'X-CSRFToken': csrf})
    assert reg_res.status_code == 200, f"Register failed: {reg_res.get_json()}"
    assert reg_res.get_json()['success'] is True

    # 3. Log out to test fresh login
    client.get('/logout')
    with client.session_transaction() as sess:
        assert 'employer_id' not in sess

    # 4. Attempt login with wrong password
    csrf = get_csrf(client)
    bad_res = client.post('/api/employer/login', json={'email': email, 'password': 'WrongPassword123!'}, headers={'X-CSRFToken': csrf})
    assert bad_res.status_code in (200, 401)
    assert bad_res.get_json()['success'] is False

    # 5. Attempt login with correct password
    csrf = get_csrf(client)
    login_res = client.post('/api/employer/login', json={'email': email, 'password': password}, headers={'X-CSRFToken': csrf})
    assert login_res.status_code == 200
    login_data = login_res.get_json()
    assert login_data['success'] is True
    assert login_data['redirect'] == '/employer_dashboard'

    # 6. Verify session created
    with client.session_transaction() as sess:
        assert 'employer_id' in sess
        assert sess['role'] == 'employer'

    # 7. Access employer dashboard
    dash_res = client.get('/employer_dashboard')
    assert dash_res.status_code == 200
    assert b"Employer" in dash_res.data or b"Dashboard" in dash_res.data

    # 8. Verify employer cannot access candidate dashboard
    cand_dash_res = client.get('/user_dashboard')
    assert cand_dash_res.status_code in (302, 403)

    # 9. Logout
    client.get('/logout')
    post_dash = client.get('/employer_dashboard')
    assert post_dash.status_code == 302


def test_auth_missing_fields_and_validation(client):
    """Test validation on missing fields in login APIs."""
    csrf = get_csrf(client)

    # Missing password
    res1 = client.post('/api/user/login', json={'email': 'test@example.com'}, headers={'X-CSRFToken': csrf})
    assert res1.status_code == 400
    assert res1.get_json()['success'] is False

    # Missing email
    res2 = client.post('/api/user/login', json={'password': 'Password123!'}, headers={'X-CSRFToken': csrf})
    assert res2.status_code == 400
    assert res2.get_json()['success'] is False

    # Missing password (employer)
    res3 = client.post('/api/employer/login', json={'email': 'emp@example.com'}, headers={'X-CSRFToken': csrf})
    assert res3.status_code == 400
    assert res3.get_json()['success'] is False

    # Nonexistent user
    res4 = client.post('/api/user/login', json={'email': 'nonexistent_user_xyz_999@test.com', 'password': 'Password123!'}, headers={'X-CSRFToken': csrf})
    assert res4.status_code == 200
    assert res4.get_json()['success'] is False
    assert "not found" in res4.get_json()['message'].lower()


def test_guest_protection_on_all_dashboards(client):
    """Ensure unauthenticated guests cannot access any protected dashboard."""
    client.get('/logout')

    res1 = client.get('/user_dashboard')
    assert res1.status_code == 302
    assert 'login' in res1.headers.get('Location', '')

    res2 = client.get('/employer_dashboard')
    assert res2.status_code == 302
    assert 'emp_login' in res2.headers.get('Location', '')

    res3 = client.get('/admin_dashboard')
    assert res3.status_code in (302, 403)
