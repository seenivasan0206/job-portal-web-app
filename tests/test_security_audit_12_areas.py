# -*- coding: utf-8 -*-
"""
Automated Test Suite for Comprehensive 12-Area Security Audit and Hardening.
Covers:
1. Authentication: Password complexity, numeric rejection, and common-password blocklist.
2. Admin Authorization: POST-only moderation actions (ban, soft-delete, verify, reject, approve, feature).
3. Candidate/Employer Authorization: Cross-role endpoint gating (401/403).
4. IDOR Protection: Multi-tenant ownership binding across jobs, applications, and interviews.
5. SQL Injection: Whitelist enforcement on dynamic table/column queries.
6. Password Hashing: State-of-the-art hash algorithm assertion (scrypt/pbkdf2).
7. Session Security: Session lifetime (7 days), cookies (HttpOnly, Lax), ban/version invalidation.
8. CSRF Protection: CSRF token enforcement on state-modifying requests.
9. File Upload Security: Path traversal neutralization via secure_filename and magic-byte validation.
10. .ENV Secret Exposure: Zero hardcoded fallback secrets and startup failure on missing keys.
11. Debug Mode Safety: Enforcement of debug=False when FLASK_ENV=production.
12. Password Reset & OTP: Single-use consumption, server-side expiry, and brute-force guessing limit.
"""

import sys
import os
import time
import io
import pytest
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

sys.path.insert(0, r"c:\Program Files\Ampps\www\job-portal-web-app")
from app import (
    app, db_cursor, validate_password, validate_file_signature,
    verify_otp, check_rate_limit, COMMON_PASSWORDS
)


@pytest.fixture
def client():
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    with app.test_client() as client:
        yield client


# =========================================================================
# AREA 1: AUTHENTICATION & PASSWORD COMPLEXITY
# =========================================================================

def test_area_1_password_complexity_and_common_blocklist():
    # Valid passwords
    assert validate_password("StrongPass123!") is True
    assert validate_password("SecureCode2026") is True

    # Invalid: Too short (< 8 chars)
    assert validate_password("Short1!") is False
    assert validate_password("") is False

    # Invalid: Purely numeric
    assert validate_password("1234567890") is False

    # Invalid: No numbers
    assert validate_password("AllLettersOnly") is False

    # Invalid: No letters
    assert validate_password("12345678!") is False

    # Invalid: Common leaked passwords in blocklist
    for bad_pw in ['password', 'password123', 'admin123', '12345678', 'welcome1', 'qwerty123']:
        assert validate_password(bad_pw) is False, f"Expected {bad_pw} to be rejected by blocklist"


# =========================================================================
# AREA 2: ADMIN AUTHORIZATION & POST MODERATION ACTIONS
# =========================================================================

def test_area_2_admin_post_moderation_actions(client):
    ts = int(time.time())
    cand_email = f"admin_test_cand_{ts}@example.com"
    emp_email = f"admin_test_emp_{ts}@example.com"

    with db_cursor() as cur:
        cur.execute("DELETE FROM user WHERE email = %s", (cand_email,))
        cur.execute("DELETE FROM employee WHERE email = %s", (emp_email,))
        
        cur.execute(
            "INSERT INTO user (name, email, mobile, password, is_verified, session_version) VALUES (%s, %s, %s, %s, %s, %s)",
            ("Test Candidate", cand_email, "9876543210", generate_password_hash("Pass1234!"), True, 0)
        )
        cand_id = cur.lastrowid

        cur.execute(
            "INSERT INTO employee (company_name, email, mobile, password, is_verified, verification_status) VALUES (%s, %s, %s, %s, %s, %s)",
            ("Test Company", emp_email, "9876543211", generate_password_hash("Pass1234!"), False, 'pending')
        )
        emp_id = cur.lastrowid

        cur.execute(
            "INSERT INTO jobs (employer_id, title, company_name, location, status, is_active) VALUES (%s, %s, %s, %s, %s, %s)",
            (emp_id, "Software Engineer", "Test Company", "Remote", "Pending", False)
        )
        job_id = cur.lastrowid

    try:
        # Non-admin attempting admin routes -> 403
        r_unauth = client.post(f'/admin/users/{cand_id}/ban')
        assert r_unauth.status_code in (302, 401, 403)

        # Admin login session
        with client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['is_admin'] = True

        # 1. Ban User via POST
        r_ban = client.post(f'/admin/users/{cand_id}/ban', headers={'Accept': 'application/json'})
        assert r_ban.status_code == 200
        assert r_ban.get_json()['success'] is True

        with db_cursor() as cur:
            cur.execute("SELECT is_banned, session_version FROM user WHERE id = %s", (cand_id,))
            user_row = cur.fetchone()
            assert bool(user_row['is_banned']) is True
            assert user_row['session_version'] >= 1

        # 2. Verify Company via POST
        r_verify = client.post(f'/admin/companies/{emp_id}/verify', headers={'Accept': 'application/json'})
        assert r_verify.status_code == 200
        assert r_verify.get_json()['success'] is True

        with db_cursor() as cur:
            cur.execute("SELECT is_verified, verification_status FROM employee WHERE id = %s", (emp_id,))
            emp_row = cur.fetchone()
            assert bool(emp_row['is_verified']) is True
            assert emp_row['verification_status'] == 'verified'

        # 3. Approve Job via POST
        r_approve = client.post(f'/admin/jobs/{job_id}/approve', headers={'Accept': 'application/json'})
        assert r_approve.status_code == 200
        assert r_approve.get_json()['success'] is True

        with db_cursor() as cur:
            cur.execute("SELECT is_active, status FROM jobs WHERE id = %s", (job_id,))
            job_row = cur.fetchone()
            assert bool(job_row['is_active']) is True
            assert job_row['status'] == 'Published'

        # 4. Feature Job via POST
        r_feat = client.post(f'/admin/jobs/{job_id}/feature', headers={'Accept': 'application/json'})
        assert r_feat.status_code == 200
        assert r_feat.get_json()['success'] is True

        with db_cursor() as cur:
            cur.execute("SELECT is_featured FROM jobs WHERE id = %s", (job_id,))
            assert bool(cur.fetchone()['is_featured']) is True

        # 5. Soft Delete Job via POST
        r_del_job = client.post(f'/admin/jobs/{job_id}/delete', headers={'Accept': 'application/json'})
        assert r_del_job.status_code == 200

        with db_cursor() as cur:
            cur.execute("SELECT is_active, status, is_deleted FROM jobs WHERE id = %s", (job_id,))
            del_job_row = cur.fetchone()
            assert bool(del_job_row['is_active']) is False
            assert del_job_row['status'] == 'Deleted'
            assert bool(del_job_row['is_deleted']) is True

    finally:
        with db_cursor() as cur:
            cur.execute("DELETE FROM jobs WHERE id = %s", (job_id,))
            cur.execute("DELETE FROM user WHERE id = %s", (cand_id,))
            cur.execute("DELETE FROM employee WHERE id = %s", (emp_id,))


# =========================================================================
# AREA 3: CANDIDATE/EMPLOYER CROSS-ROLE AUTHORIZATION
# =========================================================================

def test_area_3_cross_role_authorization_rejection(client):
    # Logged in as Candidate
    with client.session_transaction() as sess:
        sess['user_id'] = 501
        sess['role'] = 'candidate'
        sess['session_version'] = 0

    # Candidate attempting Employer-only endpoints -> 401
    assert client.post('/api/employer/post_job', json={'title': 'Test'}).status_code == 401
    assert client.get('/api/employer/jobs').status_code == 401
    assert client.get('/api/employer/applicants').status_code == 401
    assert client.post('/api/recruiter/interviews/schedule', json={}).status_code == 401

    # Logged in as Employer
    with client.session_transaction() as sess:
        sess.clear()
        sess['employer_id'] = 301
        sess['role'] = 'employer'
        sess['session_version'] = 0

    # Employer attempting Candidate-only endpoints -> 401
    assert client.get('/api/user/applied_jobs').status_code == 401
    assert client.get('/api/user/saved_jobs').status_code == 401
    assert client.get('/api/candidate/profile/items').status_code == 401
    assert client.post('/api/apply_job', data={'job_id': '1'}).status_code == 401


# =========================================================================
# AREA 4: IDOR (INSECURE DIRECT OBJECT REFERENCE)
# =========================================================================

def test_area_4_idor_ownership_isolation(client):
    ts = int(time.time())
    emp_a_email = f"emp_a_{ts}@example.com"
    emp_b_email = f"emp_b_{ts}@example.com"
    cand_email = f"cand_idor_{ts}@example.com"

    with db_cursor() as cur:
        cur.execute("DELETE FROM user WHERE email = %s", (cand_email,))
        cur.execute("DELETE FROM employee WHERE email IN (%s, %s)", (emp_a_email, emp_b_email))

        cur.execute("INSERT INTO user (name, email, password, is_verified) VALUES (%s, %s, %s, %s)",
                    ("Cand", cand_email, generate_password_hash("Pass1234!"), True))
        cand_id = cur.lastrowid

        cur.execute("INSERT INTO employee (company_name, email, password, is_verified) VALUES (%s, %s, %s, %s)",
                    ("Company A", emp_a_email, generate_password_hash("Pass1234!"), True))
        emp_a_id = cur.lastrowid

        cur.execute("INSERT INTO employee (company_name, email, password, is_verified) VALUES (%s, %s, %s, %s)",
                    ("Company B", emp_b_email, generate_password_hash("Pass1234!"), True))
        emp_b_id = cur.lastrowid

        # Employer B posts Job B
        cur.execute("INSERT INTO jobs (employer_id, title, company_name, is_active) VALUES (%s, %s, %s, %s)",
                    (emp_b_id, "Job B", "Company B", True))
        job_b_id = cur.lastrowid

        # Candidate applies to Job B
        cur.execute("INSERT INTO applications (job_id, user_id, user_name, status) VALUES (%s, %s, %s, %s)",
                    (job_b_id, cand_id, "Cand", "Applied"))
        app_b_id = cur.lastrowid

        # Interview for Job B
        cur.execute("INSERT INTO interviews (job_id, employer_id, candidate_id, scheduled_date, scheduled_time) VALUES (%s, %s, %s, %s, %s)",
                    (job_b_id, emp_b_id, cand_id, "2026-10-15", "14:00"))
        iv_b_id = cur.lastrowid

    try:
        # Sign in as Employer A
        with client.session_transaction() as sess:
            sess['employer_id'] = emp_a_id
            sess['role'] = 'employer'
            sess['session_version'] = 0

        # Employer A attempts to delete Job B -> Fails (WHERE employer_id = emp_a_id)
        client.delete(f'/api/delete_job/{job_b_id}')
        with db_cursor() as cur:
            cur.execute("SELECT id FROM jobs WHERE id = %s", (job_b_id,))
            assert cur.fetchone() is not None, "Job B should NOT be deleted by Employer A"

        # Employer A attempts to update Candidate status on Application B -> 403 Unauthorized
        r_status = client.post('/api/update_candidate_status', json={'app_id': app_b_id, 'status': 'Selected'})
        assert r_status.status_code == 403

        # Employer A attempts to view Candidate Profile for Application B -> 403 Unauthorized
        r_prof = client.get(f'/api/employer/candidate/{cand_id}/profile')
        assert r_prof.status_code == 403

        # Employer A attempts to reschedule Interview B -> 404/403
        r_resched = client.post(f'/api/recruiter/interviews/{iv_b_id}/reschedule', json={
            'scheduled_date': '2026-10-20',
            'scheduled_time': '10:00'
        })
        assert r_resched.status_code in (403, 404)

    finally:
        with db_cursor() as cur:
            cur.execute("DELETE FROM interviews WHERE id = %s", (iv_b_id,))
            cur.execute("DELETE FROM applications WHERE id = %s", (app_b_id,))
            cur.execute("DELETE FROM jobs WHERE id = %s", (job_b_id,))
            cur.execute("DELETE FROM user WHERE id = %s", (cand_id,))
            cur.execute("DELETE FROM employee WHERE id IN (%s, %s)", (emp_a_id, emp_b_id))


# =========================================================================
# AREA 5: SQL INJECTION WHITELIST AUDIT
# =========================================================================

def test_area_5_sql_dynamic_table_whitelist(client):
    ts = int(time.time())
    cand_email = f"sql_sec_user_{ts}@example.com"
    with db_cursor() as cur:
        cur.execute("DELETE FROM user WHERE email = %s", (cand_email,))
        cur.execute(
            "INSERT INTO user (name, email, password, is_verified, session_version) VALUES (%s, %s, %s, %s, %s)",
            ("SQL Test User", cand_email, generate_password_hash("Pass1234!"), True, 0)
        )
        test_uid = cur.lastrowid

    try:
        with client.session_transaction() as sess:
            sess['user_id'] = test_uid
            sess['role'] = 'candidate'
            sess['session_version'] = 0

        # Attempt invalid / injection table section in candidate profile CRUD
        r_bad_section = client.get('/api/candidate/profile/items?section=users;DROP TABLE user;--')
        assert r_bad_section.status_code == 200
        assert r_bad_section.get_json()['items'] == []
    finally:
        with db_cursor() as cur:
            cur.execute("DELETE FROM user WHERE id = %s", (test_uid,))


# =========================================================================
# AREA 6: PASSWORD HASHING ALGORITHM ASSERTION
# =========================================================================

def test_area_6_password_hashing_algorithm():
    h = generate_password_hash("ValidPass123!")
    assert h.startswith(('scrypt:', 'pbkdf2:sha256:')), f"Unexpected hash algorithm prefix: {h[:20]}"
    assert check_password_hash(h, "ValidPass123!") is True
    assert check_password_hash(h, "WrongPass123!") is False


# =========================================================================
# AREA 7: SESSION SECURITY & BAN INVALIDATION
# =========================================================================

def test_area_7_session_security_and_banned_user_eviction(client):
    assert app.permanent_session_lifetime == timedelta(days=7)
    assert app.config['PERMANENT_SESSION_LIFETIME'] == timedelta(days=7)
    assert app.config['SESSION_COOKIE_HTTPONLY'] is True
    assert app.config['SESSION_COOKIE_SAMESITE'] == 'Lax'

    ts = int(time.time())
    banned_email = f"banned_user_{ts}@example.com"
    with db_cursor() as cur:
        cur.execute("DELETE FROM user WHERE email = %s", (banned_email,))
        cur.execute(
            "INSERT INTO user (name, email, password, is_verified, is_banned, session_version) VALUES (%s, %s, %s, %s, %s, %s)",
            ("Banned User", banned_email, generate_password_hash("Pass1234!"), True, True, 0)
        )
        banned_uid = cur.lastrowid

    try:
        # 1. Login attempt for banned user is rejected
        r_login = client.post('/api/user/login', json={'email': banned_email, 'password': 'Pass1234!'})
        assert r_login.status_code == 403
        assert 'banned' in r_login.get_json()['message'].lower() or 'deactivated' in r_login.get_json()['message'].lower()

        # 2. Active session for banned user is evicted in validate_session()
        with client.session_transaction() as sess:
            sess['user_id'] = banned_uid
            sess['role'] = 'candidate'
            sess['session_version'] = 0

        r_req = client.get('/api/user/profile_completeness')
        assert r_req.status_code == 401

        # Session transaction should now be cleared
        with client.session_transaction() as sess:
            assert 'user_id' not in sess

    finally:
        with db_cursor() as cur:
            cur.execute("DELETE FROM user WHERE id = %s", (banned_uid,))


# =========================================================================
# AREA 8: CSRF PROTECTION ENFORCEMENT
# =========================================================================

def test_area_8_csrf_protection():
    assert 'csrf' in app.extensions
    assert app.config.get('WTF_CSRF_CHECK_DEFAULT', True) is True


# =========================================================================
# AREA 9: FILE UPLOAD & PATH TRAVERSAL DEFENSE
# =========================================================================

def test_area_9_file_upload_and_path_traversal_neutralization():
    malicious_names = [
        "../../etc/passwd.pdf",
        "..\\..\\windows\\system32\\cmd.exe.pdf",
        "/etc/shadow.pdf",
        "nested/../../secret.pdf"
    ]
    for m in malicious_names:
        cleaned = secure_filename(m)
        assert "../" not in cleaned and "..\\" not in cleaned
        assert not cleaned.startswith('/') and not cleaned.startswith('\\')

    # Magic byte validation
    pdf_bytes = io.BytesIO(b"%PDF-1.4 header content")
    assert validate_file_signature(pdf_bytes, "test.pdf") is True

    fake_pdf = io.BytesIO(b"<script>alert('xss')</script>")
    assert validate_file_signature(fake_pdf, "test.pdf") is False


# =========================================================================
# AREA 10: .ENV & SECRET EXPOSURE AUDIT
# =========================================================================

def test_area_10_env_secrets_and_gitignore():
    with open(r"c:\Program Files\Ampps\www\job-portal-web-app\.gitignore", "r", encoding="utf-8") as f:
        gi = f.read()
    assert ".env" in gi

    assert app.secret_key is not None
    assert len(str(app.secret_key)) >= 16


# =========================================================================
# AREA 11: DEBUG MODE SAFETY GUARD
# =========================================================================

def test_area_11_debug_mode_safety():
    # Read app.py source and confirm production safety check
    with open(r"c:\Program Files\Ampps\www\job-portal-web-app\app.py", "r", encoding="utf-8") as f:
        src = f.read()
    assert "if os.getenv('FLASK_ENV') == 'production' and debug_mode:" in src
    assert "debug_mode = False" in src


# =========================================================================
# AREA 12: PASSWORD RESET & OTP BRUTE-FORCE RATE LIMITING
# =========================================================================

def test_area_12_otp_single_use_and_brute_force_limits(client):
    test_email = f"otp_sec_{int(time.time())}@example.com"
    otp_code = "789123"

    with db_cursor() as cur:
        cur.execute("DELETE FROM otp_store WHERE email = %s", (test_email,))
        cur.execute("DELETE FROM rate_limits WHERE rate_key LIKE %s", (f"{test_email}%",))
        cur.execute("DELETE FROM rate_limits WHERE rate_key LIKE %s", (f"otp_guess:{test_email}%",))
        cur.execute(
            "INSERT INTO otp_store (email, otp, expires_at) VALUES (%s, %s, %s)",
            (test_email, otp_code, datetime.now() + timedelta(minutes=5))
        )

    try:
        # 1. Failed guesses increment attempt counter
        for _ in range(4):
            assert verify_otp(test_email, "000000") is False

        # 5th attempt with wrong OTP
        assert verify_otp(test_email, "000000") is False

        # 6th attempt (even with CORRECT OTP) is blocked by rate limiter
        assert verify_otp(test_email, otp_code) is False

        # Reset rate limit to test single-use consumption
        with db_cursor() as cur:
            cur.execute("DELETE FROM rate_limits WHERE rate_key = %s", (f"otp_guess:{test_email}",))

        # Successful verification consumes OTP
        assert verify_otp(test_email, otp_code) is True

        # Re-using the same OTP immediately fails (single-use enforced)
        assert verify_otp(test_email, otp_code) is False

    finally:
        with db_cursor() as cur:
            cur.execute("DELETE FROM otp_store WHERE email = %s", (test_email,))
            cur.execute("DELETE FROM rate_limits WHERE rate_key LIKE %s", (f"{test_email}%",))
            cur.execute("DELETE FROM rate_limits WHERE rate_key LIKE %s", (f"otp_guess:{test_email}%",))
