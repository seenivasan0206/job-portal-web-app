# -*- coding: utf-8 -*-
"""
Comprehensive Integration Tests for HireVolt Unified Admin Panel & Company Verification Center.

Covers:
1. Admin Provisioning & Authentication (Login, Logout, Access Control, Change Password)
2. SSRF-Safe Company Website Auditing (DNS resolution, Private/Loopback/Metadata IP blocking)
3. Automated Trust & Screening Risk Signals (Domain match, public vs corporate email, profile completeness)
4. Company Verification State Machine & Immutable History (pending -> verified -> suspicious -> rejected)
5. Job Moderation & Soft Deletes
6. Candidate & User Reports Submission and Resolution Lifecycle
7. Immutable Administrative Audit Trail & Global Multi-Entity Search
"""
import os
import pytest
from werkzeug.security import generate_password_hash
from app import (
    app, db_cursor,
    safe_check_company_website,
    compute_company_trust_and_risk,
    is_private_or_restricted_ip,
    init_admin_user
)

ADMIN_EMAIL = os.getenv('ADMIN_EMAIL', 'ccubetech00@gmail.com').strip().lower()
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', 'ccubetech00')


@pytest.fixture
def client():
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    with app.test_client() as client:
        yield client


@pytest.fixture
def admin_session(client):
    """Logs in as the primary authorized admin and returns the test client."""
    init_admin_user()
    res = client.post('/api/admin/login', json={
        'email': ADMIN_EMAIL,
        'password': ADMIN_PASSWORD
    })
    assert res.status_code == 200
    assert res.get_json()['success'] is True
    return client


# --- 1. ADMIN AUTHENTICATION & ACCESS CONTROL TESTS ---

def test_admin_auto_provisioning_and_login(client):
    init_admin_user()
    
    # 1. Login with correct admin credentials
    res = client.post('/api/admin/login', json={
        'email': ADMIN_EMAIL,
        'password': ADMIN_PASSWORD
    })
    assert res.status_code == 200
    data = res.get_json()
    assert data['success'] is True
    assert 'redirect' in data

    # 2. Login with wrong password
    res_fail = client.post('/api/admin/login', json={
        'email': ADMIN_EMAIL,
        'password': 'WrongPassword123'
    })
    assert res_fail.status_code == 401
    assert res_fail.get_json()['success'] is False


def test_admin_access_control_rejection(client):
    # Unauthenticated user visiting admin dashboard / API receives 403 / redirect
    res_page = client.get('/admin/dashboard', follow_redirects=False)
    assert res_page.status_code == 302
    assert '/admin/login' in res_page.headers['Location']

    res_api = client.get('/api/admin/dashboard_stats')
    assert res_api.status_code in (401, 403)
    assert res_api.get_json()['success'] is False

    # Candidate user without admin role visiting admin API
    with client.session_transaction() as sess:
        sess['user_id'] = 9999
        sess['user_name'] = 'Regular Candidate'
        sess['role'] = 'candidate'
        sess['is_admin'] = False

    res_cand = client.get('/api/admin/companies')
    assert res_cand.status_code == 403
    assert res_cand.get_json()['success'] is False


def test_admin_logout_and_session_invalidation(admin_session):
    # Authenticated request succeeds
    res1 = admin_session.get('/api/admin/dashboard_stats')
    assert res1.status_code == 200

    # Logout
    res_logout = admin_session.post('/api/admin/logout')
    assert res_logout.status_code == 200
    assert res_logout.get_json()['success'] is True

    # Subsequent request is blocked
    res2 = admin_session.get('/api/admin/dashboard_stats')
    assert res2.status_code in (401, 403)


# --- 2. SSRF-SAFE WEBSITE CHECKER TESTS ---

def test_ssrf_safe_website_checker_blocks_malicious_ips():
    # 1. Loopback addresses
    assert is_private_or_restricted_ip('127.0.0.1') is True
    assert is_private_or_restricted_ip('::1') is True

    # 2. Private Class A, B, C networks
    assert is_private_or_restricted_ip('10.0.0.1') is True
    assert is_private_or_restricted_ip('172.16.0.1') is True
    assert is_private_or_restricted_ip('192.168.1.1') is True

    # 3. Cloud metadata endpoint (AWS / GCP / Azure 169.254.169.254)
    assert is_private_or_restricted_ip('169.254.169.254') is True

    # 4. Safe public IP
    assert is_private_or_restricted_ip('8.8.8.8') is False
    assert is_private_or_restricted_ip('1.1.1.1') is False

    # 5. Verify safe_check_company_website blocks localhost URL
    res_local = safe_check_company_website('http://localhost:5000/admin')
    assert res_local['is_safe_url'] is False
    assert 'blocked' in res_local['error_message'].lower() or 'local' in res_local['error_message'].lower()

    # 6. Verify safe_check_company_website blocks 169.254.169.254
    res_meta = safe_check_company_website('http://169.254.169.254/latest/meta-data/')
    assert res_meta['is_safe_url'] is False

    # 7. Verify safe_check_company_website blocks non-standard ports
    res_port = safe_check_company_website('http://example.com:22/ssh')
    assert res_port['is_safe_url'] is False


def test_ssrf_website_api_endpoint(admin_session):
    res = admin_session.get('/api/admin/check_website_safe?url=http://127.0.0.1:8080')
    assert res.status_code == 200
    data = res.get_json()
    assert data['success'] is True
    assert data['audit']['is_safe_url'] is False


# --- 3. TRUST & RISK SCREENING ENGINE TESTS ---

def test_compute_company_trust_and_risk_signals():
    # 1. Low risk genuine corporate company
    corp_comp = {
        'company_name': 'Tata Consultancy Services',
        'email': 'careers@tcs.com',
        'mobile': '9876543210',
        'industry': 'IT & Software',
        'location': 'Mumbai',
        'company_size': '10000+',
        'website': 'https://tcs.com',
        'description': 'Global IT solutions and consulting leader operating worldwide.',
        'verification_doc_path': 'tcs_cert.pdf'
    }
    corp_audit = {'is_https': True, 'is_reachable': True, 'is_safe_url': True, 'status_code': 200}
    t_corp = compute_company_trust_and_risk(corp_comp, jobs_count=12, reports_count=0, website_audit=corp_audit)
    assert t_corp['risk_level'] == 'LOW RISK'
    assert t_corp['completeness'] >= 80
    assert any('Corporate business email' in sig for sig in t_corp['trust_indicators'])
    assert any('Email domain matches' in sig for sig in t_corp['trust_indicators'])

    # 2. High risk suspicious company (free email, domain mismatch, reports filed, incomplete)
    susp_comp = {
        'company_name': 'Quick Cash Crypto Hiring',
        'email': 'quickcashhr99@gmail.com',
        'website': 'http://crypto-payouts-instant.xyz',
        'description': 'Short'
    }
    susp_audit = {'is_https': False, 'is_reachable': False, 'is_safe_url': True, 'error_message': 'Connection refused'}
    t_susp = compute_company_trust_and_risk(susp_comp, jobs_count=0, reports_count=3, website_audit=susp_audit)
    assert t_susp['risk_level'] == 'HIGH RISK'
    assert any('free/public email' in w for w in t_susp['warnings'])
    assert any('candidate/user report' in w for w in t_susp['warnings'])


# --- 4. COMPANY VERIFICATION LIFECYCLE & AUDIT HISTORY TESTS ---

def test_company_verification_state_machine_and_history(admin_session):
    with db_cursor() as cur:
        # Create test company
        cur.execute("SELECT id FROM employee WHERE email = 'admin_test_corp@test.com'")
        r = cur.fetchone()
        if not r:
            cur.execute("""
                INSERT INTO employee (company_name, email, password, is_verified, verification_status, industry, location, website)
                VALUES ('Acme Dynamics', 'admin_test_corp@test.com', 'hashedpass', 0, 'pending', 'Robotics', 'Hyderabad', 'https://acme.example.com')
            """)
            comp_id = cur.lastrowid
        else:
            comp_id = r['id']
            cur.execute("UPDATE employee SET is_verified = 0, verification_status = 'pending' WHERE id = %s", (comp_id,))

    # 1. Fetch Company Detail via Admin API
    res_detail = admin_session.get(f'/api/admin/companies/{comp_id}')
    assert res_detail.status_code == 200
    d_data = res_detail.get_json()
    assert d_data['success'] is True
    assert d_data['company']['company_name'] == 'Acme Dynamics'
    assert 'trust_analysis' in d_data

    # 2. Transition Pending -> Verified
    res_v = admin_session.post(f'/api/admin/companies/{comp_id}/status', json={
        'status': 'verified',
        'admin_note': 'Incorporation Certificate verified with Ministry of Corporate Affairs.'
    })
    assert res_v.status_code == 200
    assert res_v.get_json()['success'] is True

    with db_cursor() as cur:
        cur.execute("SELECT verification_status, is_verified FROM employee WHERE id = %s", (comp_id,))
        emp_v = cur.fetchone()
        assert emp_v['verification_status'] == 'verified'
        assert emp_v['is_verified'] == 1

        # Check Verification History Table
        cur.execute("SELECT previous_status, new_status, admin_note FROM company_verification_history WHERE company_id = %s ORDER BY id DESC LIMIT 1", (comp_id,))
        h1 = cur.fetchone()
        assert h1['new_status'] == 'verified'
        assert 'Ministry' in h1['admin_note']

    # 3. Transition Verified -> Suspicious (Flagged due to external report)
    res_s = admin_session.post(f'/api/admin/companies/{comp_id}/status', json={
        'status': 'suspicious',
        'admin_note': 'Report received regarding external payment request. Flagged for review.'
    })
    assert res_s.status_code == 200

    with db_cursor() as cur:
        cur.execute("SELECT verification_status, is_verified FROM employee WHERE id = %s", (comp_id,))
        emp_s = cur.fetchone()
        assert emp_s['verification_status'] == 'suspicious'
        assert emp_s['is_verified'] == 0

        cur.execute("SELECT previous_status, new_status FROM company_verification_history WHERE company_id = %s ORDER BY id DESC LIMIT 1", (comp_id,))
        h2 = cur.fetchone()
        assert h2['previous_status'] == 'verified'
        assert h2['new_status'] == 'suspicious'

    # 4. Transition Suspicious -> Rejected
    res_r = admin_session.post(f'/api/admin/companies/{comp_id}/status', json={
        'status': 'rejected',
        'admin_note': 'Fake company identity confirmed. Access rejected.'
    })
    assert res_r.status_code == 200


# --- 5. JOB MODERATION TESTS ---

def test_job_moderation_lifecycle(admin_session):
    with db_cursor() as cur:
        cur.execute("SELECT id FROM employee LIMIT 1")
        emp = cur.fetchone()
        emp_id = emp['id']

        cur.execute("""
            INSERT INTO jobs (employer_id, title, description, location, salary, is_active, status)
            VALUES (%s, 'Senior AI Engineer', 'Build intelligent systems', 'Remote', '₹25,00,000', 1, 'Published')
        """, (emp_id,))
        job_id = cur.lastrowid

    # 1. Fetch Job detail
    res_j = admin_session.get(f'/api/admin/jobs/{job_id}')
    assert res_j.status_code == 200
    assert res_j.get_json()['job']['title'] == 'Senior AI Engineer'

    # 2. Mark Suspicious
    res_susp = admin_session.post(f'/api/admin/jobs/{job_id}/status', json={
        'status': 'Suspicious',
        'admin_note': 'Salary claims require validation'
    })
    assert res_susp.status_code == 200

    with db_cursor() as cur:
        cur.execute("SELECT status, is_active FROM jobs WHERE id = %s", (job_id,))
        j_row = cur.fetchone()
        assert j_row['status'] == 'Suspicious'
        assert j_row['is_active'] == 0

    # 3. Toggle Featured
    res_feat = admin_session.post(f'/api/admin/jobs/{job_id}/feature')
    assert res_feat.status_code == 200

    # 4. Soft delete
    res_del = admin_session.post(f'/api/admin/jobs/{job_id}/delete')
    assert res_del.status_code == 200
    with db_cursor() as cur:
        cur.execute("SELECT is_deleted FROM jobs WHERE id = %s", (job_id,))
        assert cur.fetchone()['is_deleted'] == 1


# --- 6. CANDIDATE REPORTS SYSTEM TESTS ---

def test_candidate_report_submission_and_resolution(admin_session):
    # 1. Candidate submits report
    res_sub = admin_session.post('/api/reports/submit', json={
        'report_type': 'company',
        'target_id': 1,
        'target_name': 'Suspicious Enterprise',
        'category': 'External Payment Request',
        'description': 'Recruiter asked for ₹5000 security deposit for interview equipment.',
        'reporter_email': 'candidate_victim@example.com'
    })
    assert res_sub.status_code == 200
    rep_id = res_sub.get_json()['report_id']
    assert rep_id is not None

    # 2. Admin views reports list
    res_list = admin_session.get('/api/admin/reports?status=OPEN')
    assert res_list.status_code == 200
    reps = res_list.get_json()['reports']
    assert any(r['id'] == rep_id for r in reps)

    # 3. Admin updates status to UNDER_REVIEW
    res_rev = admin_session.post(f'/api/admin/reports/{rep_id}/status', json={
        'status': 'UNDER_REVIEW',
        'admin_notes': 'Contacted candidate for email proof screenshots.'
    })
    assert res_rev.status_code == 200

    # 4. Admin resolves report
    res_res = admin_session.post(f'/api/admin/reports/{rep_id}/status', json={
        'status': 'RESOLVED',
        'admin_notes': 'Fraudulent employer banned and candidate notified.'
    })
    assert res_res.status_code == 200

    with db_cursor() as cur:
        cur.execute("SELECT status, admin_notes, resolved_at FROM reports WHERE id = %s", (rep_id,))
        r_db = cur.fetchone()
        assert r_db['status'] == 'RESOLVED'
        assert r_db['resolved_at'] is not None


# --- 7. AUDIT LOGS & SEARCH TESTS ---

def test_admin_audit_logs_retrieval_and_global_search(admin_session):
    # Audit Logs API
    res_audit = admin_session.get('/api/admin/audit_logs')
    assert res_audit.status_code == 200
    assert 'audit_logs' in res_audit.get_json()

    # Global Multi-Entity Search API
    res_search = admin_session.get('/api/admin/global_search?q=admin')
    assert res_search.status_code == 200
    data = res_search.get_json()
    assert data['success'] is True
    assert 'results' in data
    assert 'companies' in data['results']
    assert 'jobs' in data['results']


# --- 8. ADMIN PASSWORD CHANGE & USER MODERATION TESTS ---

def test_admin_password_change_and_user_moderation(admin_session):
    # 1. User moderation (ban / unban / delete)
    with db_cursor() as cur:
        cur.execute("SELECT id FROM user WHERE is_admin = 0 LIMIT 1")
        u = cur.fetchone()
        if not u:
            cur.execute("INSERT INTO user (name, email, password) VALUES ('Test Cand', 'cand_mod_test@test.com', 'pass123')")
            uid = cur.lastrowid
        else:
            uid = u['id']

    # Ban
    res_ban = admin_session.post(f'/api/admin/users/{uid}/ban', json={})
    assert res_ban.status_code == 200
    assert res_ban.get_json()['success'] is True

    with db_cursor() as cur:
        cur.execute("SELECT is_banned FROM user WHERE id = %s", (uid,))
        assert cur.fetchone()['is_banned'] == 1

    # Unban
    res_unban = admin_session.post(f'/api/admin/users/{uid}/unban', json={})
    assert res_unban.status_code == 200
    with db_cursor() as cur:
        cur.execute("SELECT is_banned FROM user WHERE id = %s", (uid,))
        assert cur.fetchone()['is_banned'] == 0

    # 2. Export API
    for exp_type in ['companies', 'jobs', 'users', 'applications', 'audit_logs']:
        res_exp = admin_session.get(f'/api/admin/reports/{exp_type}/export')
        assert res_exp.status_code == 200
        assert res_exp.get_json()['success'] is True

    # 3. Admin Change Password Flow
    with db_cursor() as cur:
        cur.execute("SELECT id FROM user WHERE email = %s", (ADMIN_EMAIL,))
        adm_row = cur.fetchone()
        if adm_row:
            cur.execute("DELETE FROM password_history WHERE user_id = %s", (adm_row['id'],))

    res_pw = admin_session.post('/api/admin/change_password', json={
        'current_password': ADMIN_PASSWORD,
        'new_password': 'NewAdminPassword2026!',
        'confirm_password': 'NewAdminPassword2026!'
    })
    assert res_pw.status_code == 200
    assert res_pw.get_json()['success'] is True

    # Revert password back for idempotency
    with db_cursor() as cur:
        if adm_row:
            cur.execute("DELETE FROM password_history WHERE user_id = %s", (adm_row['id'],))

    res_revert = admin_session.post('/api/admin/change_password', json={
        'current_password': 'NewAdminPassword2026!',
        'new_password': ADMIN_PASSWORD,
        'confirm_password': ADMIN_PASSWORD
    })
    assert res_revert.status_code == 200


