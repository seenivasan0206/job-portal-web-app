# -*- coding: utf-8 -*-
"""
Test suite for Password Reset Route and OTP Verification Unification (Bug #6).
Verifies:
1. /api/reset_password and /api/employer/reset_password both use centralized verify_otp().
2. Candidate password reset succeeds and consumes the OTP.
3. Employer password reset succeeds via /api/reset_password and /api/employer/reset_password.
4. Invalid, expired, or replayed OTP is rejected with 400 'Invalid or expired OTP'.
5. Weak passwords and reused recent passwords are appropriately blocked.
6. Session version is incremented and active sessions are cleared.
"""

import time
import pytest
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
from app import app, db_cursor


@pytest.fixture
def client():
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    with app.test_client() as client:
        yield client


def test_candidate_password_reset_unified_flow(client):
    """Verify candidate password reset via /api/reset_password using verify_otp()."""
    test_email = f"cand_reset_{int(time.time())}@example.com"
    old_pw = "OldPassword123!"
    new_pw = "NewSecurePassword456!"
    otp_code = "876543"

    with db_cursor() as cur:
        cur.execute("DELETE FROM user WHERE email = %s", (test_email,))
        cur.execute("DELETE FROM otp_store WHERE email = %s", (test_email,))
        cur.execute(
            "INSERT INTO user (name, email, mobile, password, is_verified, session_version) VALUES (%s, %s, %s, %s, %s, 1)",
            ("Reset Candidate", test_email, "9876500001", generate_password_hash(old_pw), 1)
        )
        cur.execute(
            "INSERT INTO otp_store (email, otp, expires_at) VALUES (%s, %s, %s)",
            (test_email, otp_code, datetime.now() + timedelta(minutes=5))
        )

    try:
        # Reset password
        res = client.post('/api/reset_password', json={
            'email': test_email,
            'otp': otp_code,
            'password': new_pw
        })
        assert res.status_code == 200
        data = res.get_json()
        assert data['success'] is True
        assert 'Password Reset Successful' in data['message']

        # Verify OTP was consumed
        with db_cursor() as cur:
            cur.execute("SELECT * FROM otp_store WHERE email = %s", (test_email,))
            assert cur.fetchone() is None

            # Verify new password in DB
            cur.execute("SELECT password, session_version FROM user WHERE email = %s", (test_email,))
            row = cur.fetchone()
            assert check_password_hash(row['password'], new_pw)
            assert row['session_version'] == 2

        # Verify login with new password succeeds
        login_res = client.post('/api/user/login', json={
            'email': test_email,
            'password': new_pw
        })
        assert login_res.status_code == 200
        assert login_res.get_json()['success'] is True

    finally:
        with db_cursor() as cur:
            cur.execute("DELETE FROM user WHERE email = %s", (test_email,))
            cur.execute("DELETE FROM otp_store WHERE email = %s", (test_email,))


def test_employer_password_reset_via_both_endpoints(client):
    """Verify employer password reset works via both /api/reset_password and /api/employer/reset_password."""
    test_email_1 = f"emp_reset1_{int(time.time())}@example.com"
    test_email_2 = f"emp_reset2_{int(time.time())}@example.com"
    old_pw = "OldEmployerPass123!"
    new_pw = "NewEmployerPass456!"
    otp_code = "654321"

    with db_cursor() as cur:
        cur.execute("DELETE FROM employee WHERE email IN (%s, %s)", (test_email_1, test_email_2))
        cur.execute("DELETE FROM otp_store WHERE email IN (%s, %s)", (test_email_1, test_email_2))
        cur.execute(
            "INSERT INTO employee (company_name, mobile, email, password, session_version) VALUES (%s, %s, %s, %s, 1)",
            ("Reset Employer 1", "9876500002", test_email_1, generate_password_hash(old_pw))
        )
        cur.execute(
            "INSERT INTO employee (company_name, mobile, email, password, session_version) VALUES (%s, %s, %s, %s, 1)",
            ("Reset Employer 2", "9876500003", test_email_2, generate_password_hash(old_pw))
        )
        cur.execute("INSERT INTO otp_store (email, otp, expires_at) VALUES (%s, %s, %s)", (test_email_1, otp_code, datetime.now() + timedelta(minutes=5)))
        cur.execute("INSERT INTO otp_store (email, otp, expires_at) VALUES (%s, %s, %s)", (test_email_2, otp_code, datetime.now() + timedelta(minutes=5)))

    try:
        # 1. Reset via /api/reset_password
        res1 = client.post('/api/reset_password', json={
            'email': test_email_1,
            'otp': otp_code,
            'password': new_pw
        })
        assert res1.status_code == 200
        assert res1.get_json()['success'] is True

        # 2. Reset via /api/employer/reset_password
        res2 = client.post('/api/employer/reset_password', json={
            'email': test_email_2,
            'otp': otp_code,
            'password': new_pw
        })
        assert res2.status_code == 200
        assert res2.get_json()['success'] is True

        # Verify DB hashes
        with db_cursor() as cur:
            cur.execute("SELECT password, session_version FROM employee WHERE email = %s", (test_email_1,))
            r1 = cur.fetchone()
            assert check_password_hash(r1['password'], new_pw)
            assert r1['session_version'] == 2

            cur.execute("SELECT password, session_version FROM employee WHERE email = %s", (test_email_2,))
            r2 = cur.fetchone()
            assert check_password_hash(r2['password'], new_pw)
            assert r2['session_version'] == 2

    finally:
        with db_cursor() as cur:
            cur.execute("DELETE FROM employee WHERE email IN (%s, %s)", (test_email_1, test_email_2))
            cur.execute("DELETE FROM otp_store WHERE email IN (%s, %s)", (test_email_1, test_email_2))


def test_password_reset_invalid_and_expired_otp(client):
    """Verify that invalid, expired, and already consumed OTPs fail with 400 status code."""
    test_email = f"otp_fail_{int(time.time())}@example.com"
    pw = "ValidPassword123!"

    with db_cursor() as cur:
        cur.execute("DELETE FROM user WHERE email = %s", (test_email,))
        cur.execute("DELETE FROM otp_store WHERE email = %s", (test_email,))
        cur.execute(
            "INSERT INTO user (name, email, mobile, password, is_verified) VALUES (%s, %s, %s, %s, 1)",
            ("OTP Test User", test_email, "9876500004", generate_password_hash(pw))
        )
        # Expired OTP
        cur.execute(
            "INSERT INTO otp_store (email, otp, expires_at) VALUES (%s, %s, %s)",
            (test_email, "111111", datetime.now() - timedelta(minutes=5))
        )

    try:
        # 1. Expired OTP
        res_expired = client.post('/api/reset_password', json={
            'email': test_email,
            'otp': '111111',
            'password': 'NewPassword123!'
        })
        assert res_expired.status_code == 400
        assert res_expired.get_json()['success'] is False
        assert 'Invalid or expired OTP' in res_expired.get_json()['message']

        # 2. Non-existent OTP
        res_invalid = client.post('/api/reset_password', json={
            'email': test_email,
            'otp': '999999',
            'password': 'NewPassword123!'
        })
        assert res_invalid.status_code == 400
        assert res_invalid.get_json()['success'] is False
        assert 'Invalid or expired OTP' in res_invalid.get_json()['message']

        # 3. Add valid OTP, reset, and attempt replay attack
        with db_cursor() as cur:
            cur.execute("INSERT INTO otp_store (email, otp, expires_at) VALUES (%s, %s, %s)",
                        (test_email, "222222", datetime.now() + timedelta(minutes=5)))

        res_first = client.post('/api/reset_password', json={
            'email': test_email,
            'otp': '222222',
            'password': 'NewPassword123!'
        })
        assert res_first.status_code == 200
        assert res_first.get_json()['success'] is True

        # Replay attempt with same OTP must fail
        res_replay = client.post('/api/reset_password', json={
            'email': test_email,
            'otp': '222222',
            'password': 'AnotherPassword123!'
        })
        assert res_replay.status_code == 400
        assert res_replay.get_json()['success'] is False
        assert 'Invalid or expired OTP' in res_replay.get_json()['message']

    finally:
        with db_cursor() as cur:
            cur.execute("DELETE FROM user WHERE email = %s", (test_email,))
            cur.execute("DELETE FROM otp_store WHERE email = %s", (test_email,))


def test_password_reset_validation_and_reuse_restrictions(client):
    """Verify password strength validation and recent password reuse check."""
    test_email = f"reuse_check_{int(time.time())}@example.com"
    initial_pw = "InitialSecret123!"

    with db_cursor() as cur:
        cur.execute("DELETE FROM user WHERE email = %s", (test_email,))
        cur.execute("DELETE FROM otp_store WHERE email = %s", (test_email,))
        cur.execute("DELETE FROM password_history WHERE user_id IN (SELECT id FROM user WHERE email = %s)", (test_email,))
        cur.execute(
            "INSERT INTO user (name, email, mobile, password, is_verified) VALUES (%s, %s, %s, %s, 1)",
            ("Reuse Test User", test_email, "9876500005", generate_password_hash(initial_pw))
        )
        cur.execute("SELECT id FROM user WHERE email = %s", (test_email,))
        uid = cur.fetchone()['id']
        cur.execute("INSERT INTO password_history (user_id, password_hash) VALUES (%s, %s)",
                    (uid, generate_password_hash(initial_pw)))
        cur.execute("INSERT INTO otp_store (email, otp, expires_at) VALUES (%s, %s, %s)",
                    (test_email, "333333", datetime.now() + timedelta(minutes=5)))

    try:
        # Weak password (too short)
        res_weak = client.post('/api/reset_password', json={
            'email': test_email,
            'otp': '333333',
            'password': 'short'
        })
        assert res_weak.status_code == 400
        assert res_weak.get_json()['success'] is False

        # Attempt to reuse current/recent password
        res_reuse = client.post('/api/reset_password', json={
            'email': test_email,
            'otp': '333333',
            'password': initial_pw
        })
        assert res_reuse.status_code == 200
        assert res_reuse.get_json()['success'] is False
        assert 'cannot reuse a recent password' in res_reuse.get_json()['message']

    finally:
        with db_cursor() as cur:
            cur.execute("DELETE FROM user WHERE email = %s", (test_email,))
            cur.execute("DELETE FROM otp_store WHERE email = %s", (test_email,))
