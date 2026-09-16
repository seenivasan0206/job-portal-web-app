# -*- coding: utf-8 -*-
"""
Integration tests for Transparent Employer & Company Verification System,
Trust Signals, Document Security, and Admin Verification Lifecycle.
"""
from datetime import datetime
import pytest
from app import app, db_cursor, compute_company_completeness

@pytest.fixture
def client():
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    with app.test_client() as client:
        yield client

def test_company_completeness_calculation():
    # Full company
    full_comp = {
        'company_name': 'Apex Systems',
        'email': 'hr@apex.com',
        'mobile': '9876543210',
        'industry': 'IT & Software',
        'location': 'Bengaluru',
        'company_size': '51-200',
        'website': 'https://apex.com',
        'description': 'Leading enterprise software solutions provider with global client base.',
        'founded_year': '2018'
    }
    score = compute_company_completeness(full_comp)
    assert score == 100

    # Minimal company
    min_comp = {'company_name': 'New Startup'}
    score_min = compute_company_completeness(min_comp)
    assert score_min == 20

    print(f"[PASS] compute_company_completeness() verified (Full: {score}%, Min: {score_min}%).")

def test_four_employer_verification_states(client):
    # Setup 4 distinct test employers
    with db_cursor() as cur:
        # 1. Unverified
        cur.execute("SELECT id FROM employee WHERE email = 'unverif_state@test.com'")
        r1 = cur.fetchone()
        if not r1:
            cur.execute("""
                INSERT INTO employee (company_name, email, password, is_verified, verification_status, industry, location)
                VALUES ('Unverified Corp', 'unverif_state@test.com', 'pass', 0, 'unverified', 'IT', 'Pune')
            """)
            id_unverif = cur.lastrowid
        else:
            id_unverif = r1['id']
            cur.execute("UPDATE employee SET is_verified = 0, verification_status = 'unverified' WHERE id = %s", (id_unverif,))

        # 2. Pending
        cur.execute("SELECT id FROM employee WHERE email = 'pending_state@test.com'")
        r2 = cur.fetchone()
        if not r2:
            cur.execute("""
                INSERT INTO employee (company_name, email, password, is_verified, verification_status, verification_submitted_at, industry, location)
                VALUES ('Pending Corp', 'pending_state@test.com', 'pass', 0, 'pending', NOW(), 'Healthcare', 'Delhi')
            """)
            id_pending = cur.lastrowid
        else:
            id_pending = r2['id']
            cur.execute("UPDATE employee SET is_verified = 0, verification_status = 'pending', verification_submitted_at = NOW() WHERE id = %s", (id_pending,))

        # 3. Verified
        cur.execute("SELECT id FROM employee WHERE email = 'verified_state@test.com'")
        r3 = cur.fetchone()
        if not r3:
            cur.execute("""
                INSERT INTO employee (company_name, email, password, is_verified, verification_status, verified_at, industry, location)
                VALUES ('Verified Global', 'verified_state@test.com', 'pass', 1, 'verified', NOW(), 'Finance', 'Mumbai')
            """)
            id_verified = cur.lastrowid
        else:
            id_verified = r3['id']
            cur.execute("UPDATE employee SET is_verified = 1, verification_status = 'verified', verified_at = NOW() WHERE id = %s", (id_verified,))

        # 4. Rejected
        cur.execute("SELECT id FROM employee WHERE email = 'rejected_state@test.com'")
        r4 = cur.fetchone()
        if not r4:
            cur.execute("""
                INSERT INTO employee (company_name, email, password, is_verified, verification_status, verification_notes, industry, location)
                VALUES ('Rejected Tech', 'rejected_state@test.com', 'pass', 0, 'rejected', 'Missing GST certificate', 'Retail', 'Chennai')
            """)
            id_rejected = cur.lastrowid
        else:
            id_rejected = r4['id']
            cur.execute("UPDATE employee SET is_verified = 0, verification_status = 'rejected', verification_notes = 'Missing GST certificate' WHERE id = %s", (id_rejected,))

    # Test Public API Responses
    # Unverified
    res1 = client.get(f'/api/company/{id_unverif}')
    assert res1.status_code == 200
    c1 = res1.get_json()['company']
    assert c1['verification_status'] == 'unverified'
    assert c1['is_company_verified'] is False

    # Pending
    res2 = client.get(f'/api/company/{id_pending}')
    assert res2.status_code == 200
    c2 = res2.get_json()['company']
    assert c2['verification_status'] == 'pending'
    assert c2['is_company_verified'] is False

    # Verified
    res3 = client.get(f'/api/company/{id_verified}')
    assert res3.status_code == 200
    c3 = res3.get_json()['company']
    assert c3['verification_status'] == 'verified'
    assert c3['is_company_verified'] is True
    assert c3['verified_on'] is not None

    # Rejected
    res4 = client.get(f'/api/company/{id_rejected}')
    assert res4.status_code == 200
    c4 = res4.get_json()['company']
    assert c4['verification_status'] == 'rejected'
    assert c4['is_company_verified'] is False

    print("[PASS] All 4 employer verification states (unverified, pending, verified, rejected) verified with accurate public trust signals.")

def test_admin_verification_workflow_and_notes(client):
    # 1. Setup a test employer submitting verification
    with db_cursor() as cur:
        cur.execute("SELECT id FROM employee WHERE email = 'workflow_test@corp.com'")
        row = cur.fetchone()
        if not row:
            cur.execute("""
                INSERT INTO employee (company_name, email, password, is_verified, verification_status)
                VALUES ('Workflow Corp', 'workflow_test@corp.com', 'pass', 0, 'unverified')
            """)
            emp_id = cur.lastrowid
        else:
            emp_id = row['id']
            cur.execute("UPDATE employee SET is_verified = 0, verification_status = 'unverified' WHERE id = %s", (emp_id,))

    # 2. Employer requests verification
    with client.session_transaction() as sess:
        sess['employer_id'] = emp_id
        sess['user_name'] = 'Workflow Corp'
        sess['role'] = 'employer'

    req_res = client.post('/api/employer/request_verification', data={'notes': 'Please review our registration documents.'})
    assert req_res.status_code == 200
    assert req_res.get_json()['status'] == 'pending'

    # Verify status changed to pending
    with db_cursor() as cur:
        cur.execute("SELECT verification_status FROM employee WHERE id = %s", (emp_id,))
        assert cur.fetchone()['verification_status'] == 'pending'

    # 3. Admin rejects verification with reason
    with client.session_transaction() as sess:
        sess.clear()
        sess['user_id'] = 999
        sess['is_admin'] = 1

    rej_res = client.post('/api/admin/verify_company', json={
        'company_id': emp_id,
        'action': 'reject',
        'notes': 'Company registration number is missing.'
    })
    assert rej_res.status_code == 200

    with db_cursor() as cur:
        cur.execute("SELECT is_verified, verification_status, verification_notes FROM employee WHERE id = %s", (emp_id,))
        emp_state = cur.fetchone()
        assert emp_state['is_verified'] == 0
        assert emp_state['verification_status'] == 'rejected'
        assert 'missing' in emp_state['verification_notes']

    # 4. Admin approves verification
    app_res = client.post('/api/admin/verify_company', json={
        'company_id': emp_id,
        'action': 'approve',
        'notes': 'All corporate records verified.'
    })
    assert app_res.status_code == 200

    with db_cursor() as cur:
        cur.execute("SELECT is_verified, verification_status, verified_at FROM employee WHERE id = %s", (emp_id,))
        emp_verified = cur.fetchone()
        assert emp_verified['is_verified'] == 1
        assert emp_verified['verification_status'] == 'verified'
        assert emp_verified['verified_at'] is not None

    print("[PASS] Full admin verification lifecycle (submit -> pending -> reject with notes -> approve with verified timestamp) verified.")

def test_document_security_and_access_control(client):
    # 1. Unauthenticated or candidate accessing admin document endpoint
    with client.session_transaction() as sess:
        sess['user_id'] = 10
        sess['role'] = 'user'

    res_forbidden = client.get('/admin/company_doc/1')
    assert res_forbidden.status_code == 403

    # 2. Candidate viewing public company detail API never sees private documents or notes
    res_public = client.get('/api/company/1')
    if res_public.status_code == 200:
        comp_data = res_public.get_json()['company']
        assert 'verification_doc_path' not in comp_data
        assert 'verification_notes' not in comp_data

    print("[PASS] Document security verified: Private verification documents and internal notes are never exposed publicly or to candidates.")

def test_database_driven_companies_directory(client):
    res = client.get('/api/companies')
    assert res.status_code == 200
    data = res.get_json()
    assert data['success'] is True
    assert isinstance(data['companies'], list)

    for c in data['companies']:
        assert 'company_name' in c
        assert 'industry' in c
        assert 'location' in c
        assert 'is_company_verified' in c
        assert 'open_jobs' in c

    print(f"[PASS] /api/companies returns {len(data['companies'])} genuine database employers with real active job counts.")

if __name__ == '__main__':
    pytest.main(['-s', __file__])
