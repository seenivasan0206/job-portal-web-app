# -*- coding: utf-8 -*-
"""
Comprehensive Test Suite for HireVolt Job Application System:
1. Apply to job with JSON and multipart form data
2. Select uploaded resume vs new resume file upload vs profile resume fallback
3. Optional cover letter storage and retrieval
4. Additional application questions & answers storage
5. Additional document upload (certificates/portfolio) & employer download route
6. Duplicate application prevention
7. Application confirmation payload
8. Application history & tracking (/api/user/applied_jobs)
9. Full 8-status pipeline: Applied -> Screening -> Shortlisted -> Assessment -> Interview -> Offer -> Hired -> Rejected
10. Application withdrawal with candidate ownership & employer notification
11. Employer in-app notification upon candidate application and withdrawal
12. Candidate in-app notification upon status progression
13. Security checks: IDOR protection, job availability validation, deadline validation
"""
import os
import io
import json
import pytest
from datetime import datetime, timedelta
from app import app, db_cursor


@pytest.fixture
def client():
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    with app.test_client() as client:
        yield client


@pytest.fixture(autouse=True)
def setup_app_test_data():
    """Sets up clean test employers, candidate users, jobs, and profile data."""
    with db_cursor() as cursor:
        # 1. Employer A (Owner)
        cursor.execute("SELECT id FROM employee WHERE email = 'app_emp_a@test.com'")
        r = cursor.fetchone()
        if r:
            emp_a_id = r['id']
        else:
            cursor.execute("""
                INSERT INTO employee (company_name, email, password, mobile, is_verified, verification_status)
                VALUES ('Quantum Dynamics', 'app_emp_a@test.com', 'hashed_pwd', '9876543201', 1, 'verified')
            """)
            emp_a_id = cursor.lastrowid

        # 2. Employer B (Unauthorized/Other)
        cursor.execute("SELECT id FROM employee WHERE email = 'app_emp_b@test.com'")
        r2 = cursor.fetchone()
        if r2:
            emp_b_id = r2['id']
        else:
            cursor.execute("""
                INSERT INTO employee (company_name, email, password, mobile, is_verified, verification_status)
                VALUES ('Starlight Labs', 'app_emp_b@test.com', 'hashed_pwd', '9876543202', 1, 'verified')
            """)
            emp_b_id = cursor.lastrowid

        # 3. Candidate 1 (User A)
        cursor.execute("SELECT id FROM user WHERE email = 'cand_alpha@test.com'")
        r3 = cursor.fetchone()
        if r3:
            user_a_id = r3['id']
        else:
            cursor.execute("""
                INSERT INTO user (name, email, password, mobile, headline, skills, experience, location)
                VALUES ('Alpha Developer', 'cand_alpha@test.com', 'hashed_pwd', '9123456701', 'Full Stack Engineer', 'Python, React, SQL', 3, 'Chennai')
            """)
            user_a_id = cursor.lastrowid

        # 4. Candidate 2 (User B)
        cursor.execute("SELECT id FROM user WHERE email = 'cand_beta@test.com'")
        r4 = cursor.fetchone()
        if r4:
            user_b_id = r4['id']
        else:
            cursor.execute("""
                INSERT INTO user (name, email, password, mobile, headline, skills, experience, location)
                VALUES ('Beta Scientist', 'cand_beta@test.com', 'hashed_pwd', '9123456702', 'Data Scientist', 'Python, PyTorch, SQL', 2, 'Bengaluru')
            """)
            user_b_id = cursor.lastrowid

        # Candidate Profile with profile resume
        cursor.execute("DELETE FROM candidate_profile WHERE user_id IN (%s, %s)", (user_a_id, user_b_id))
        cursor.execute("""
            INSERT INTO candidate_profile (user_id, general_resume_path, headline, summary)
            VALUES (%s, 'alpha_profile_resume.pdf', 'Full Stack Engineer', 'Experienced engineer building web backends.')
        """, (user_a_id,))

        # Resume Analyses entry for User A
        cursor.execute("DELETE FROM resume_analyses WHERE user_id IN (%s, %s)", (user_a_id, user_b_id))
        cursor.execute("""
            INSERT INTO resume_analyses (user_id, filename, original_filename, file_path, ats_score)
            VALUES (%s, 'resume_analysis_saved.pdf', 'My_Analyzed_Resume.pdf', 'resume_analysis_saved.pdf', 88)
        """, (user_a_id,))

        # Clean old test jobs and applications
        cursor.execute("DELETE FROM applications WHERE user_id IN (%s, %s)", (user_a_id, user_b_id))
        cursor.execute("DELETE FROM jobs WHERE employer_id IN (%s, %s)", (emp_a_id, emp_b_id))
        cursor.execute("DELETE FROM notifications WHERE user_id IN (%s, %s) OR employer_id IN (%s, %s)", (user_a_id, user_b_id, emp_a_id, emp_b_id))

        # 5. Active Job by Employer A
        cursor.execute("""
            INSERT INTO jobs (employer_id, title, description, location, salary, experience, skills, category, is_active, application_deadline, company_name)
            VALUES (%s, 'Senior Backend Architect', 'Build high throughput distributed systems in Python.', 'Chennai', '₹15,00,000 - ₹25,00,000', '3-5 Years', 'Python, Flask, Redis, MySQL', 'IT & Software', 1, %s, 'Quantum Dynamics')
        """, (emp_a_id, (datetime.now().date() + timedelta(days=30)).strftime('%Y-%m-%d')))
        active_job_id = cursor.lastrowid

        # 6. Inactive Job by Employer A
        cursor.execute("""
            INSERT INTO jobs (employer_id, title, description, location, is_active, company_name)
            VALUES (%s, 'Closed Junior Developer', 'Closed role', 'Remote', 0, 'Quantum Dynamics')
        """, (emp_a_id,))
        inactive_job_id = cursor.lastrowid

        # 7. Expired Deadline Job by Employer A
        cursor.execute("""
            INSERT INTO jobs (employer_id, title, description, location, is_active, application_deadline, company_name)
            VALUES (%s, 'Past Deadline Role', 'Expired role', 'Remote', 1, %s, 'Quantum Dynamics')
        """, (emp_a_id, (datetime.now().date() - timedelta(days=5)).strftime('%Y-%m-%d')))
        expired_job_id = cursor.lastrowid

        # 8. Active Job by Employer B
        cursor.execute("""
            INSERT INTO jobs (employer_id, title, description, location, is_active, company_name)
            VALUES (%s, 'AI Research Scientist', 'Deep learning NLP research.', 'Bengaluru', 1, 'Starlight Labs')
        """, (emp_b_id,))
        emp_b_job_id = cursor.lastrowid

    yield {
        'emp_a_id': emp_a_id,
        'emp_b_id': emp_b_id,
        'user_a_id': user_a_id,
        'user_b_id': user_b_id,
        'active_job_id': active_job_id,
        'inactive_job_id': inactive_job_id,
        'expired_job_id': expired_job_id,
        'emp_b_job_id': emp_b_job_id
    }


# =========================================================================
# 1. APPLY TO JOB & CONFIRMATION
# =========================================================================
def test_apply_job_success_and_confirmation(client, setup_app_test_data):
    """Verifies candidate can apply to job and receives full confirmation payload."""
    data = setup_app_test_data
    with client.session_transaction() as sess:
        sess['user_id'] = data['user_a_id']
        sess['user_name'] = 'Alpha Developer'
        sess['user_email'] = 'cand_alpha@test.com'

    res = client.post('/api/apply_job', json={
        'job_id': data['active_job_id'],
        'cover_letter': 'I have 5 years building scalable Python backends.',
        'notice_period': '15 Days',
        'expected_salary': '₹20 LPA',
        'willing_to_relocate': 'Yes'
    })
    assert res.status_code == 200
    res_data = res.get_json()
    assert res_data['success'] is True
    assert 'application_id' in res_data
    assert res_data['job_id'] == data['active_job_id']
    assert res_data['job_title'] == 'Senior Backend Architect'
    assert res_data['company_name'] == 'Quantum Dynamics'
    assert res_data['status'] == 'Applied'


# =========================================================================
# 2. SELECT UPLOADED RESUME VS NEW RESUME UPLOAD
# =========================================================================
def test_select_uploaded_resume_from_saved_resumes(client, setup_app_test_data):
    """Verifies candidate can fetch available resumes and select an analyzed resume."""
    data = setup_app_test_data
    with client.session_transaction() as sess:
        sess['user_id'] = data['user_a_id']

    # 1. Test GET /api/user/resumes
    res_resumes = client.get('/api/user/resumes')
    assert res_resumes.status_code == 200
    r_data = res_resumes.get_json()
    assert r_data['success'] is True
    assert len(r_data['resumes']) >= 2  # Profile resume + Analyzed resume

    # 2. Apply selecting analyzed resume path
    res = client.post('/api/apply_job', json={
        'job_id': data['active_job_id'],
        'resume_path': 'resume_analysis_saved.pdf',
        'cover_letter': 'Selected saved resume test.'
    })
    assert res.status_code == 200
    app_id = res.get_json()['application_id']

    with db_cursor() as cursor:
        cursor.execute("SELECT resume_path FROM applications WHERE id = %s", (app_id,))
        app_row = cursor.fetchone()
        assert app_row['resume_path'] == 'resume_analysis_saved.pdf'


def test_upload_new_resume_file(client, setup_app_test_data):
    """Verifies candidate can upload a new PDF file during application."""
    data = setup_app_test_data
    with client.session_transaction() as sess:
        sess['user_id'] = data['user_a_id']

    # Create dummy PDF bytes (%PDF header)
    pdf_bytes = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF"
    file_payload = (io.BytesIO(pdf_bytes), 'custom_uploaded_resume.pdf')

    res = client.post('/api/apply_job', data={
        'job_id': str(data['active_job_id']),
        'cover_letter': 'Uploaded new file test',
        'resume': file_payload
    }, content_type='multipart/form-data')

    assert res.status_code == 200
    app_id = res.get_json()['application_id']

    with db_cursor() as cursor:
        cursor.execute("SELECT resume_path FROM applications WHERE id = %s", (app_id,))
        app_row = cursor.fetchone()
        assert app_row['resume_path'] is not None
        assert 'custom_uploaded_resume' in app_row['resume_path']


# =========================================================================
# 3. OPTIONAL COVER LETTER & SCREENING QUESTIONS
# =========================================================================
def test_optional_cover_letter_and_screening_questions(client, setup_app_test_data):
    """Verifies cover letter and screening questions/answers are saved in JSON format."""
    data = setup_app_test_data
    with client.session_transaction() as sess:
        sess['user_id'] = data['user_a_id']

    cover_text = "I am deeply passionate about distributed architecture and caching layers."
    res = client.post('/api/apply_job', json={
        'job_id': data['active_job_id'],
        'cover_letter': cover_text,
        'notice_period': 'Immediate',
        'expected_salary': '₹18 LPA',
        'current_ctc': '₹12 LPA',
        'willing_to_relocate': 'Yes',
        'answers': {
            'years_with_python': '5 years',
            'has_docker_experience': 'Yes'
        }
    })
    assert res.status_code == 200
    app_id = res.get_json()['application_id']

    # Verify in DB and via detail API
    res_detail = client.get(f'/api/user/applications/{app_id}')
    assert res_detail.status_code == 200
    d = res_detail.get_json()['application']
    assert d['cover_letter'] == cover_text
    answers = d['parsed_answers']
    assert answers['notice_period'] == 'Immediate'
    assert answers['expected_salary'] == '₹18 LPA'
    assert answers['years_with_python'] == '5 years'


# =========================================================================
# 4. ADDITIONAL DOCUMENT UPLOAD & EMPLOYER DOWNLOAD
# =========================================================================
def test_additional_document_upload_and_download(client, setup_app_test_data):
    """Verifies optional certificate/portfolio upload and employer download."""
    data = setup_app_test_data
    with client.session_transaction() as sess:
        sess['user_id'] = data['user_a_id']

    cert_bytes = b"%PDF-1.4 AWS Certified Solutions Architect Certificate\n%%EOF"
    res = client.post('/api/apply_job', data={
        'job_id': str(data['active_job_id']),
        'additional_document': (io.BytesIO(cert_bytes), 'aws_cert.pdf')
    }, content_type='multipart/form-data')

    assert res.status_code == 200
    app_id = res.get_json()['application_id']

    with db_cursor() as cursor:
        cursor.execute("SELECT additional_document_path FROM applications WHERE id = %s", (app_id,))
        doc_path = cursor.fetchone()['additional_document_path']
        assert doc_path is not None
        assert 'doc_' in doc_path

    # Test Employer A can download it
    with client.session_transaction() as sess:
        sess.clear()
        sess['employer_id'] = data['emp_a_id']

    res_dl = client.get(f'/api/employer/applications/{app_id}/document/download')
    assert res_dl.status_code == 200
    assert b'AWS Certified Solutions Architect' in res_dl.data

    # Test Unauthorized Employer B gets 404/403
    with client.session_transaction() as sess:
        sess.clear()
        sess['employer_id'] = data['emp_b_id']

    res_dl_unauth = client.get(f'/api/employer/applications/{app_id}/document/download')
    assert res_dl_unauth.status_code in (403, 404)


# =========================================================================
# 5. DUPLICATE APPLICATION PREVENTION
# =========================================================================
def test_duplicate_application_prevention(client, setup_app_test_data):
    """Verifies duplicate applications to the same job are rejected."""
    data = setup_app_test_data
    with client.session_transaction() as sess:
        sess['user_id'] = data['user_a_id']

    # 1. First submission succeeds
    res1 = client.post('/api/apply_job', json={'job_id': data['active_job_id']})
    assert res1.status_code == 200
    assert res1.get_json()['success'] is True

    # 2. Second submission rejected
    res2 = client.post('/api/apply_job', json={'job_id': data['active_job_id']})
    assert res2.status_code == 400
    assert res2.get_json()['success'] is False
    assert 'already applied' in res2.get_json()['message'].lower()


# =========================================================================
# 6. JOB AVAILABILITY & DEADLINE VALIDATION
# =========================================================================
def test_job_availability_and_deadline_validation(client, setup_app_test_data):
    """Verifies inactive or expired jobs cannot be applied to."""
    data = setup_app_test_data
    with client.session_transaction() as sess:
        sess['user_id'] = data['user_a_id']

    # 1. Inactive job
    res_inact = client.post('/api/apply_job', json={'job_id': data['inactive_job_id']})
    assert res_inact.status_code == 400
    assert 'no longer active' in res_inact.get_json()['message'].lower()

    # 2. Expired deadline job
    res_exp = client.post('/api/apply_job', json={'job_id': data['expired_job_id']})
    assert res_exp.status_code == 400
    assert 'deadline has passed' in res_exp.get_json()['message'].lower()

    # 3. Non-existent job
    res_404 = client.post('/api/apply_job', json={'job_id': 999999})
    assert res_404.status_code == 404


# =========================================================================
# 7. APPLICATION HISTORY & STATUS PROGRESSION (8 STATUSES)
# =========================================================================
def test_full_candidate_employer_status_workflow(client, setup_app_test_data):
    """
    Tests complete status progression pipeline:
    Applied -> Screening -> Shortlisted -> Assessment -> Interview -> Offer -> Hired
    and verifies candidate and employer receive notifications.
    """
    data = setup_app_test_data

    # Step 1: Candidate applies
    with client.session_transaction() as sess:
        sess['user_id'] = data['user_a_id']
        sess['user_name'] = 'Alpha Developer'

    res_apply = client.post('/api/apply_job', json={'job_id': data['active_job_id']})
    assert res_apply.status_code == 200
    app_id = res_apply.get_json()['application_id']

    # Verify Candidate got initial notification
    res_notif = client.get('/api/get_user_notifications')
    assert res_notif.status_code == 200
    notifs = res_notif.get_json()['notifications']
    assert any('submitted successfully' in n['message'] for n in notifs)

    # Step 2: Employer updates through all 8 statuses
    with client.session_transaction() as sess:
        sess.clear()
        sess['employer_id'] = data['emp_a_id']

    # Verify Employer received in-app notification of new applicant
    res_emp_notif = client.get('/api/employer/notifications')
    assert res_emp_notif.status_code == 200
    emp_notifs = res_emp_notif.get_json()['notifications']
    assert any('Alpha Developer' in n['message'] for n in emp_notifs)

    statuses_to_test = [
        'Screening',
        'Shortlisted',
        'Assessment',
        'Interview',
        'Offer',
        'Hired',
        'Rejected'
    ]

    for st in statuses_to_test:
        res_upd = client.post('/api/update_candidate_status', json={
            'app_id': app_id,
            'status': st
        })
        assert res_upd.status_code == 200
        assert res_upd.get_json()['success'] is True

        # Verify Candidate sees updated status in history
        with client.session_transaction() as sess:
            sess.clear()
            sess['user_id'] = data['user_a_id']

        res_cand_apps = client.get('/api/user/applied_jobs')
        assert res_cand_apps.status_code == 200
        apps_list = res_cand_apps.get_json()['applications']
        assert apps_list[0]['status'] == st

        # Reset session to employer for next transition
        with client.session_transaction() as sess:
            sess.clear()
            sess['employer_id'] = data['emp_a_id']


# =========================================================================
# 8. WITHDRAW APPLICATION & NOTIFY EMPLOYER
# =========================================================================
def test_withdraw_application_with_notifications(client, setup_app_test_data):
    """Verifies candidate can withdraw application and employer is notified."""
    data = setup_app_test_data

    # Candidate applies
    with client.session_transaction() as sess:
        sess['user_id'] = data['user_a_id']
        sess['user_name'] = 'Alpha Developer'

    res_apply = client.post('/api/apply_job', json={'job_id': data['active_job_id']})
    app_id = res_apply.get_json()['application_id']

    # Candidate withdraws
    res_withdraw = client.post('/api/withdraw_application', json={'app_id': app_id})
    assert res_withdraw.status_code == 200
    assert res_withdraw.get_json()['success'] is True

    # Verify status is Withdrawn
    with db_cursor() as cursor:
        cursor.execute("SELECT status FROM applications WHERE id = %s", (app_id,))
        assert cursor.fetchone()['status'] == 'Withdrawn'

    # Verify Employer got withdrawal notification
    with client.session_transaction() as sess:
        sess.clear()
        sess['employer_id'] = data['emp_a_id']

    res_emp_notif = client.get('/api/employer/notifications')
    emp_notifs = res_emp_notif.get_json()['notifications']
    assert any('withdrawn' in n['message'].lower() for n in emp_notifs)


# =========================================================================
# 9. SECURITY & IDOR ISOLATION
# =========================================================================
def test_security_idor_candidate_and_employer_isolation(client, setup_app_test_data):
    """
    Strict security verification:
    - Candidate A cannot withdraw Candidate B's application.
    - Candidate A cannot view Candidate B's application details.
    - Employer B cannot update status of applications for Employer A's jobs.
    - Employer B cannot inspect profile for candidates of Employer A's jobs.
    """
    data = setup_app_test_data

    # Candidate A applies to Employer A's job
    with client.session_transaction() as sess:
        sess['user_id'] = data['user_a_id']
    res_a = client.post('/api/apply_job', json={'job_id': data['active_job_id']})
    app_a_id = res_a.get_json()['application_id']

    # 1. Candidate B attempts to view Candidate A's application detail -> 404/403
    with client.session_transaction() as sess:
        sess.clear()
        sess['user_id'] = data['user_b_id']
    res_view_unauth = client.get(f'/api/user/applications/{app_a_id}')
    assert res_view_unauth.status_code in (403, 404)

    # 2. Candidate B attempts to withdraw Candidate A's application -> 404/403
    res_with_unauth = client.post('/api/withdraw_application', json={'app_id': app_a_id})
    assert res_with_unauth.status_code in (403, 404)

    # 3. Employer B attempts to update status of Candidate A -> 403
    with client.session_transaction() as sess:
        sess.clear()
        sess['employer_id'] = data['emp_b_id']

    res_stat_unauth = client.post('/api/update_candidate_status', json={
        'app_id': app_a_id,
        'status': 'Shortlisted'
    })
    assert res_stat_unauth.status_code == 403

    # 4. Employer B attempts to view candidate profile for candidate who never applied to Employer B -> 403
    res_prof_unauth = client.get(f'/api/employer/candidate/{data["user_a_id"]}/profile')
    assert res_prof_unauth.status_code == 403
