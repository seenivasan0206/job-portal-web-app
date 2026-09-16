# -*- coding: utf-8 -*-
"""
Comprehensive test suite for DreamJobs Authentication Modal & Login System Bug Fix.
Verifies:
1. Modal close button X behavior, scroll preservation, scrollbar-gutter, and backdrop handling.
2. Focus restoration with preventScroll to eliminate upward page jumps.
3. Password visibility toggle buttons and styling across all templates and script logic.
4. Enter-key submission capability with semantic <form> wrappers.
5. Backend authentication routes:
   - Duplicate email pre-check in /api/send_otp
   - Candidate registration & login with fresh csrf_token and candidate role
   - Employer registration & login with fresh csrf_token and employer role
   - Legacy plaintext auto-upgrade
   - Account lockout & wrong password warning
   - Logout session invalidation & confirmation flow
"""

import sys
import os
import re
import time
import pytest
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash

sys.path.insert(0, r"c:\Program Files\Ampps\www\job-portal-web-app")
from app import app, db_cursor


@pytest.fixture
def client():
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False  # Enable test client to bypass CSRF validation where needed
    with app.test_client() as client:
        yield client


# =========================================================================
# 1. MODAL CLOSE, SCROLL PRESERVATION & CSS STACKING AUDIT
# =========================================================================

def test_modal_close_and_scroll_preservation_in_js():
    with open(r"c:\Program Files\Ampps\www\job-portal-web-app\static\js\main.js", "r", encoding="utf-8") as f:
        js = f.read()

    # 1. Exact scroll restoration
    assert "savedScrollY" in js
    assert "preventScroll: true" in js
    assert "window.scrollTo" in js

    # 2. Universal togglePasswordVisibility definition
    assert "window.togglePasswordVisibility" in js
    assert "fa-eye-slash" in js
    assert "fa-eye" in js

    # 3. Post-logout toast persistence and handler
    assert "post_logout_toast" in js
    assert "sessionStorage.getItem('post_logout_toast')" in js

    # 4. Job action redirection preservation
    assert "handleJobApply" in js
    assert "handleJobBookmark" in js
    assert "pending_job_action" in js


def test_css_scrollbar_gutter_and_sharp_toasts():
    with open(r"c:\Program Files\Ampps\www\job-portal-web-app\static\css\app.css", "r", encoding="utf-8") as f:
        css = f.read()

    # Stable scrollbar gutter to prevent layout shifts
    assert "scrollbar-gutter: stable" in css

    # Toast container priority and sharp toast rendering
    assert "z-index: 99999 !important" in css
    assert "backdrop-filter: none !important" in css

    # Password input group and toggle button styles
    assert ".password-input-group" in css
    assert ".password-toggle-btn" in css


# =========================================================================
# 2. TEMPLATE AUDIT: PASSWORD TOGGLES & ENTER-KEY FORMS
# =========================================================================

def test_password_toggles_and_forms_in_base_and_index(client):
    # Check _auth_modal.html template file directly
    path = os.path.join(r"c:\Program Files\Ampps\www\job-portal-web-app\templates", "_auth_modal.html")
    with open(path, "r", encoding="utf-8") as f:
        base_content = f.read()

    # Check rendered index page (which extends base.html)
    res = client.get('/')
    assert res.status_code == 200
    rendered_index = res.get_data(as_text=True)

    for content in [base_content, rendered_index]:
        # Semantic <form> tags for Enter-key submission
        assert 'onsubmit="event.preventDefault(); registerUser(event);"' in content
        assert 'onsubmit="event.preventDefault(); handleUserLogin(event);"' in content
        assert 'onsubmit="event.preventDefault(); handleEmpRegister(event);"' in content
        assert 'onsubmit="event.preventDefault(); handleEmpLogin(event);"' in content

        # Password toggle buttons
        assert 'togglePasswordVisibility(\'su-pass\'' in content
        assert 'togglePasswordVisibility(\'li-pass\'' in content
        assert 'togglePasswordVisibility(\'fp-pass\'' in content
        assert 'togglePasswordVisibility(\'emp-su-pass\'' in content
        assert 'togglePasswordVisibility(\'emp-li-pass\'' in content

        # Close buttons
        assert 'onclick="closeUserModal()"' in content
        assert 'onclick="closeEmpModal()"' in content
        assert 'onclick="closeLogoutModal()"' in content


def test_password_toggles_in_standalone_templates():
    templates_to_check = [
        ("signup.html", ['togglePasswordVisibility(\'c-pass\'', 'togglePasswordVisibility(\'e-pass\'', 'togglePasswordVisibility(\'l-pass\'']),
        ("candidate_settings.html", ['togglePasswordVisibility(\'cp-old\'', 'togglePasswordVisibility(\'cp-new\'', 'togglePasswordVisibility(\'cp-conf\'']),
        ("employer_settings.html", ['togglePasswordVisibility(\'emp-old-pass\'', 'togglePasswordVisibility(\'emp-new-pass\'', 'togglePasswordVisibility(\'emp-conf-pass\'']),
        ("forgot_password.html", ['togglePasswordVisibility(\'fp-pass\'', 'togglePasswordVisibility(\'fp-confirm\'']),
        ("user_settings.html", ['togglePasswordVisibility(\'old-pass\'', 'togglePasswordVisibility(\'new-pass\'', 'togglePasswordVisibility(\'conf-pass\'']),
    ]

    for tmpl, expected_toggles in templates_to_check:
        path = os.path.join(r"c:\Program Files\Ampps\www\job-portal-web-app\templates", tmpl)
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        for toggle in expected_toggles:
            assert toggle in content, f"Missing {toggle} in {tmpl}"


# =========================================================================
# 3. BACKEND AUTH API AUDIT
# =========================================================================

def test_api_send_otp_duplicate_email_precheck(client):
    test_user_email = "duplicate_check_user@test.com"
    test_emp_email = "duplicate_check_emp@test.com"

    with db_cursor() as cur:
        cur.execute("DELETE FROM user WHERE email = %s", (test_user_email,))
        cur.execute("DELETE FROM employee WHERE email = %s", (test_emp_email,))
        cur.execute(
            "INSERT INTO user (name, email, mobile, password, is_verified) VALUES (%s, %s, %s, %s, %s)",
            ("Duplicate Candidate", test_user_email, "9876543210", generate_password_hash("Password123!"), True)
        )
        cur.execute(
            "INSERT INTO employee (company_name, mobile, email, password) VALUES (%s, %s, %s, %s)",
            ("Duplicate Employer Corp", "9876543211", test_emp_email, generate_password_hash("Password123!"))
        )

    try:
        # Candidate duplicate check
        res = client.post('/api/send_otp', json={'email': test_user_email, 'action': 'register'})
        data = res.get_json()
        assert res.status_code == 200
        assert data['success'] is False
        assert 'already registered' in data['message'].lower()

        # Employer duplicate check
        res2 = client.post('/api/send_otp', json={'email': test_emp_email, 'action': 'emp_register'})
        data2 = res2.get_json()
        assert res2.status_code == 200
        assert data2['success'] is False
        assert 'already registered' in data2['message'].lower()

        # Candidate forgot password nonexistent email check
        res3 = client.post('/api/send_otp', json={'email': 'nonexistent_test_cand_99@test.com', 'action': 'forgot'})
        data3 = res3.get_json()
        assert res3.status_code == 200
        assert data3['success'] is False
        assert 'no candidate account found' in data3['message'].lower()
    finally:
        with db_cursor() as cur:
            cur.execute("DELETE FROM user WHERE email = %s", (test_user_email,))
            cur.execute("DELETE FROM employee WHERE email = %s", (test_emp_email,))


def test_candidate_registration_and_login_flow(client):
    cand_email = f"cand_flow_{int(time.time())}@example.com"
    cand_password = "SecurePassword123!"

    with db_cursor() as cur:
        cur.execute("DELETE FROM user WHERE email = %s", (cand_email,))
        cur.execute("DELETE FROM otp_store WHERE email = %s", (cand_email,))
        cur.execute("DELETE FROM rate_limits WHERE rate_key LIKE %s", (f"{cand_email}%",))
        cur.execute("DELETE FROM login_attempts WHERE email = %s", (cand_email,))
        cur.execute(
            "INSERT INTO otp_store (email, otp, expires_at) VALUES (%s, %s, %s)",
            (cand_email, "123456", datetime.now() + timedelta(minutes=5))
        )

    try:
        # 1. Register candidate
        reg_res = client.post('/api/user/register', json={
            'name': 'Test Candidate',
            'mobile': '9123456789',
            'email': cand_email,
            'password': cand_password,
            'otp': '123456'
        })
        reg_data = reg_res.get_json()
        assert reg_res.status_code == 200
        assert reg_data['success'] is True
        assert 'csrf_token' in reg_data
        assert reg_data['redirect'] == '/user_dashboard'

        # Verify session state
        with client.session_transaction() as sess:
            assert sess.get('role') == 'candidate'
            assert 'user_id' in sess

        # 2. Test wrong password warning
        wrong_res = client.post('/api/user/login', json={
            'email': cand_email,
            'password': 'WrongPassword123!'
        })
        wrong_data = wrong_res.get_json()
        assert wrong_res.status_code == 200
        assert wrong_data['success'] is False
        assert 'Wrong Password' in wrong_data['message']

        # 3. Test successful login
        login_res = client.post('/api/user/login', json={
            'email': cand_email,
            'password': cand_password
        })
        login_data = login_res.get_json()
        assert login_res.status_code == 200
        assert login_data['success'] is True
        assert 'csrf_token' in login_data
        assert login_data['redirect'] == '/user_dashboard'

        with client.session_transaction() as sess:
            assert sess.get('role') == 'candidate'

    finally:
        with db_cursor() as cur:
            cur.execute("DELETE FROM user WHERE email = %s", (cand_email,))
            cur.execute("DELETE FROM otp_store WHERE email = %s", (cand_email,))
            cur.execute("DELETE FROM rate_limits WHERE rate_key LIKE %s", (f"{cand_email}%",))
            cur.execute("DELETE FROM login_attempts WHERE email = %s", (cand_email,))


def test_employer_registration_and_login_flow(client):
    emp_email = f"emp_flow_{int(time.time())}@example.com"
    emp_password = "SecurePassword123!"

    with db_cursor() as cur:
        cur.execute("DELETE FROM employee WHERE email = %s", (emp_email,))
        cur.execute("DELETE FROM otp_store WHERE email = %s", (emp_email,))
        cur.execute("DELETE FROM rate_limits WHERE rate_key LIKE %s", (f"{emp_email}%",))
        cur.execute("DELETE FROM login_attempts WHERE email = %s", (emp_email,))
        cur.execute(
            "INSERT INTO otp_store (email, otp, expires_at) VALUES (%s, %s, %s)",
            (emp_email, "654321", datetime.now() + timedelta(minutes=5))
        )

    try:
        # 1. Register employer
        reg_res = client.post('/api/employer/register', json={
            'name': 'Alpha Innovators LLC',
            'mobile': '9876501234',
            'email': emp_email,
            'password': emp_password,
            'otp': '654321'
        })
        reg_data = reg_res.get_json()
        assert reg_res.status_code == 200
        assert reg_data['success'] is True
        assert 'csrf_token' in reg_data
        assert reg_data['redirect'] == '/employer_dashboard'

        with client.session_transaction() as sess:
            assert sess.get('role') == 'employer'
            assert 'employer_id' in sess

        # 2. Test employer wrong password
        wrong_res = client.post('/api/employer/login', json={
            'email': emp_email,
            'password': 'WrongPassword123!'
        })
        wrong_data = wrong_res.get_json()
        assert wrong_res.status_code == 200
        assert wrong_data['success'] is False
        assert 'Wrong Password' in wrong_data['message']

        # 3. Test employer successful login
        login_res = client.post('/api/employer/login', json={
            'email': emp_email,
            'password': emp_password
        })
        login_data = login_res.get_json()
        assert login_res.status_code == 200
        assert login_data['success'] is True
        assert 'csrf_token' in login_data
        assert login_data['redirect'] == '/employer_dashboard'

        with client.session_transaction() as sess:
            assert sess.get('role') == 'employer'

    finally:
        with db_cursor() as cur:
            cur.execute("DELETE FROM employee WHERE email = %s", (emp_email,))
            cur.execute("DELETE FROM otp_store WHERE email = %s", (emp_email,))
            cur.execute("DELETE FROM rate_limits WHERE rate_key LIKE %s", (f"{emp_email}%",))
            cur.execute("DELETE FROM login_attempts WHERE email = %s", (emp_email,))


def test_legacy_plaintext_auto_upgrade(client):
    legacy_email = "legacy_user_test@example.com"
    plain_pw = "PlaintextSecret123!"

    with db_cursor() as cur:
        cur.execute("DELETE FROM user WHERE email = %s", (legacy_email,))
        # Insert plaintext password directly
        cur.execute(
            "INSERT INTO user (name, email, mobile, password, is_verified) VALUES (%s, %s, %s, %s, %s)",
            ("Legacy Candidate", legacy_email, "9112233445", plain_pw, True)
        )

    try:
        # Logging in with plaintext password should succeed AND auto-upgrade DB hash
        res = client.post('/api/user/login', json={'email': legacy_email, 'password': plain_pw})
        data = res.get_json()
        assert res.status_code == 200
        assert data['success'] is True

        # Inspect database to verify password was upgraded to scrypt or pbkdf2 hash
        with db_cursor() as cur:
            cur.execute("SELECT password FROM user WHERE email = %s", (legacy_email,))
            row = cur.fetchone()
            assert row['password'] != plain_pw
            assert row['password'].startswith(('scrypt:', 'pbkdf2:'))

    finally:
        with db_cursor() as cur:
            cur.execute("DELETE FROM user WHERE email = %s", (legacy_email,))


def test_logout_session_invalidation(client):
    with client.session_transaction() as sess:
        sess['user_id'] = 42
        sess['user_name'] = 'Logged In User'
        sess['role'] = 'candidate'

    # POST to /logout with JSON request
    res = client.post('/logout', headers={'Accept': 'application/json'})
    assert res.status_code == 200
    data = res.get_json()
    assert data['success'] is True

    # Check session is completely empty
    with client.session_transaction() as sess:
        assert 'user_id' not in sess
        assert 'role' not in sess


def test_account_lockout_3_attempts_and_duration(client):
    """Test that accounts lock on 3 failed attempts, wait time says 90 minutes, and admin can unlock."""
    email = f"test_lock_{int(time.time())}@example.com"
    pwd = "ValidPassword123!"

    with db_cursor() as cur:
        cur.execute("DELETE FROM user WHERE email = %s", (email,))
        cur.execute("DELETE FROM login_attempts WHERE email = %s", (email,))
        cur.execute("DELETE FROM rate_limits WHERE rate_key LIKE %s", (f"{email}%",))
        cur.execute(
            "INSERT INTO user (name, email, mobile, password, is_verified) VALUES (%s, %s, %s, %s, %s)",
            ("Lockout Test User", email, "9998887776", generate_password_hash(pwd), True)
        )

    try:
        # Attempt 1: Failed
        r1 = client.post('/api/user/login', json={'email': email, 'password': 'BadPassword1'})
        assert r1.status_code == 200
        assert r1.get_json()['success'] is False
        assert '2 attempts remaining' in r1.get_json()['message']

        # Attempt 2: Failed
        r2 = client.post('/api/user/login', json={'email': email, 'password': 'BadPassword2'})
        assert r2.status_code == 200
        assert r2.get_json()['success'] is False
        assert '1 attempts remaining' in r2.get_json()['message']

        # Attempt 3: Failed -> Locks account
        r3 = client.post('/api/user/login', json={'email': email, 'password': 'BadPassword3'})
        assert r3.status_code == 429
        assert r3.get_json()['success'] is False
        assert '90 minutes' in r3.get_json()['message']

        # Attempt 4: Blocked on entry
        r4 = client.post('/api/user/login', json={'email': email, 'password': pwd})
        assert r4.status_code == 429
        assert 'Account locked' in r4.get_json()['message']

        # Admin unlock
        with client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['is_admin'] = True

        r_unlock = client.post('/api/admin/unlock_account', json={'email': email, 'account_type': 'user'})
        assert r_unlock.status_code == 200
        assert r_unlock.get_json()['success'] is True

        with client.session_transaction() as sess:
            sess.clear()

        # Login now succeeds
        r_success = client.post('/api/user/login', json={'email': email, 'password': pwd})
        assert r_success.status_code == 200
        assert r_success.get_json()['success'] is True

    finally:
        with db_cursor() as cur:
            cur.execute("DELETE FROM user WHERE email = %s", (email,))
            cur.execute("DELETE FROM login_attempts WHERE email = %s", (email,))
            cur.execute("DELETE FROM rate_limits WHERE rate_key LIKE %s", (f"{email}%",))
