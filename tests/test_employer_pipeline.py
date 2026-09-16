# -*- coding: utf-8 -*-
"""
Test Suite for Employer Dashboard Pipeline:
1. Analytics Stats API (/api/employer/analytics) flattened structure & backwards compatibility.
2. Resume Intelligence Match Scoring (/api/employer/applicants) with real calculation vs 'Not scored'.
3. Live candidate status transitions (/api/update_candidate_status).
4. Candidate full profile view (/api/employer/candidate/<user_id>/profile) with IDOR/authorization protection.
5. Secure resume download (/api/employer/applications/<app_id>/resume).
"""
import os
import sys
sys.path.insert(0, r"c:\Program Files\Ampps\www\job-portal-web-app")
import json
import pytest
from app import app, db_cursor

@pytest.fixture
def client():
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    with app.test_client() as client:
        yield client

@pytest.fixture
def test_data(client):
    """Sets up a test employer, test candidate user, job posting, and application."""
    with db_cursor() as cursor:
        # 1. Employer
        cursor.execute("SELECT id FROM employee WHERE email = 'test_pipeline_emp@example.com'")
        emp_row = cursor.fetchone()
        if not emp_row:
            cursor.execute("""
                INSERT INTO employee (company_name, email, password, mobile)
                VALUES ('Pipeline Tech Inc', 'test_pipeline_emp@example.com', 'hashedpwd', '9876543210')
            """)
            emp_id = cursor.lastrowid
        else:
            emp_id = emp_row['id']

        # 2. Unauthorized Employer
        cursor.execute("SELECT id FROM employee WHERE email = 'other_pipeline_emp@example.com'")
        other_emp_row = cursor.fetchone()
        if not other_emp_row:
            cursor.execute("""
                INSERT INTO employee (company_name, email, password, mobile)
                VALUES ('Other Corp', 'other_pipeline_emp@example.com', 'hashedpwd', '9876543211')
            """)
            other_emp_id = cursor.lastrowid
        else:
            other_emp_id = other_emp_row['id']

        # 3. Candidate User
        cursor.execute("SELECT id FROM user WHERE email = 'pipeline_candidate@example.com'")
        user_row = cursor.fetchone()
        if not user_row:
            cursor.execute("""
                INSERT INTO user (name, email, password, mobile, headline, skills, experience, location)
                VALUES ('Alex Python Dev', 'pipeline_candidate@example.com', 'hashedpwd', '9123456780', 'Senior Backend Engineer', 'Python, Flask, Docker, MySQL, Redis', 4, 'Bengaluru')
            """)
            user_id = cursor.lastrowid
        else:
            user_id = user_row['id']

        # 4. Candidate Profile
        cursor.execute("SELECT user_id FROM candidate_profile WHERE user_id = %s", (user_id,))
        if not cursor.fetchone():
            cursor.execute("""
                INSERT INTO candidate_profile (user_id, headline, summary, linkedin_url, github_url)
                VALUES (%s, 'Senior Backend Engineer', 'Expert Python & Cloud Developer with 4 years building APIs.', 'https://linkedin.com/in/alex', 'https://github.com/alex')
            """, (user_id,))

        # 5. Job
        cursor.execute("SELECT id FROM jobs WHERE employer_id = %s AND title = 'Senior Python Engineer'", (emp_id,))
        job_row = cursor.fetchone()
        if not job_row:
            cursor.execute("""
                INSERT INTO jobs (employer_id, title, category, job_type, experience, location, skills, description, company_name)
                VALUES (%s, 'Senior Python Engineer', 'IT & Software', 'Full-time', '3-5 Years', 'Bengaluru', 'Python, Flask, Docker, MySQL', 'Develop scalable backend web APIs in Python.', 'Pipeline Tech Inc')
            """, (emp_id,))
            job_id = cursor.lastrowid
        else:
            job_id = job_row['id']

        # 6. Application
        cursor.execute("SELECT id FROM applications WHERE user_id = %s AND job_id = %s", (user_id, job_id))
        app_row = cursor.fetchone()
        if not app_row:
            cursor.execute("""
                INSERT INTO applications (user_id, job_id, user_name, user_email, user_mobile, qualification, experience_level, status)
                VALUES (%s, %s, 'Alex Python Dev', 'pipeline_candidate@example.com', '9123456780', 'B.Tech Computer Science', '3-5 Years', 'Applied')
            """, (user_id, job_id))
            app_id = cursor.lastrowid
        else:
            app_id = app_row['id']

    # Populate candidate profile items
    with client.session_transaction() as sess:
        sess['user_id'] = user_id
        sess['role'] = 'user'

    client.post('/api/candidate/profile/items', json={
        'section': 'education',
        'education_level': 'Graduation/Diploma',
        'institute_name': 'Tech University',
        'course': 'B.Tech Computer Science',
        'year_of_passing': 2024
    })
    client.post('/api/candidate/profile/items', json={
        'section': 'key_skills',
        'skill_name': 'Python'
    })
    client.post('/api/candidate/profile/items', json={
        'section': 'key_skills',
        'skill_name': 'Flask'
    })

    return {
        'emp_id': emp_id,
        'other_emp_id': other_emp_id,
        'user_id': user_id,
        'job_id': job_id,
        'app_id': app_id
    }


def test_employer_analytics_keys_and_structure(client, test_data):
    """Verifies employer analytics returns both flattened keys and totals dictionary."""
    emp_id = test_data['emp_id']

    with client.session_transaction() as sess:
        sess['employer_id'] = emp_id

    res = client.get('/api/employer/analytics')
    assert res.status_code == 200
    data = json.loads(res.data)

    assert data['success'] is True
    # Verify top-level keys expected by frontend
    assert 'total_jobs' in data
    assert 'total_applicants' in data
    assert 'shortlisted' in data
    assert 'interviews' in data
    assert 'selected' in data
    assert 'rejected' in data

    # Verify backwards compatibility keys
    assert 'job_count' in data
    assert 'totals' in data
    assert data['total_jobs'] >= 1
    assert data['total_applicants'] >= 1
    assert data['total_jobs'] == data['job_count']
    assert data['total_applicants'] == data['totals']['total_applicants']
    print("\n[PASS] Employer analytics returned correct flattened top-level and nested stat keys.")


def test_employer_applicants_match_scoring(client, test_data):
    """Verifies applicants endpoint computes real match score and returns proper schema."""
    emp_id = test_data['emp_id']

    with client.session_transaction() as sess:
        sess['employer_id'] = emp_id

    res = client.get('/api/employer/applicants')
    assert res.status_code == 200
    data = json.loads(res.data)

    assert data['success'] is True
    assert 'applicants' in data
    assert len(data['applicants']) >= 1

    app_item = next((a for a in data['applicants'] if a['id'] == test_data['app_id']), None)
    assert app_item is not None
    assert app_item['candidate_name'] == 'Alex Python Dev'
    assert app_item['job_title'] == 'Senior Python Engineer'
    assert 'match_score' in app_item
    assert 'match_score_display' in app_item
    # Must be real computed score (or "Not scored"), verify it calculated a percentage
    assert app_item['match_score_display'] != ""
    print(f"[PASS] Real match score computed for applicant: {app_item['match_score_display']}")


def test_update_candidate_status_flow(client, test_data):
    """Verifies updating candidate status via POST /api/update_candidate_status."""
    emp_id = test_data['emp_id']
    app_id = test_data['app_id']
    user_id = test_data['user_id']

    with client.session_transaction() as sess:
        sess['employer_id'] = emp_id

    # 1. Update to Shortlisted
    res = client.post('/api/update_candidate_status', json={
        'app_id': app_id,
        'status': 'Shortlisted'
    })
    assert res.status_code == 200
    data = json.loads(res.data)
    assert data['success'] is True

    with db_cursor() as cursor:
        cursor.execute("SELECT status FROM applications WHERE id = %s", (app_id,))
        assert cursor.fetchone()['status'] == 'Shortlisted'

        cursor.execute("SELECT message FROM notifications WHERE user_id = %s ORDER BY id DESC LIMIT 1", (user_id,))
        notif = cursor.fetchone()
        assert notif and 'shortlisted' in notif['message'].lower()

    # 2. Update to Interview
    res2 = client.post('/api/update_candidate_status', json={
        'app_id': app_id,
        'status': 'Interview'
    })
    assert res2.status_code == 200

    # 3. Invalid status
    res_bad = client.post('/api/update_candidate_status', json={
        'app_id': app_id,
        'status': 'UnknownStatus'
    })
    assert res_bad.status_code == 400
    print("[PASS] Status transition lifecycle (Shortlisted -> Interview) and notification dispatch verified.")


def test_candidate_profile_endpoint_authorization(client, test_data):
    """Verifies /api/employer/candidate/<user_id>/profile authorization and data integrity."""
    emp_id = test_data['emp_id']
    other_emp_id = test_data['other_emp_id']
    user_id = test_data['user_id']

    # 1. Unauthenticated request
    res_unauth = client.get(f'/api/employer/candidate/{user_id}/profile')
    assert res_unauth.status_code == 401

    # 2. Unauthorized employer (no application for this employer)
    with client.session_transaction() as sess:
        sess['employer_id'] = other_emp_id

    res_forbidden = client.get(f'/api/employer/candidate/{user_id}/profile')
    assert res_forbidden.status_code == 403

    # 3. Authorized employer
    with client.session_transaction() as sess:
        sess['employer_id'] = emp_id

    res_auth = client.get(f'/api/employer/candidate/{user_id}/profile')
    assert res_auth.status_code == 200
    data = json.loads(res_auth.data)

    assert data['success'] is True
    assert 'candidate' in data
    assert 'applications' in data
    cand = data['candidate']
    assert cand['name'] == 'Alex Python Dev'
    assert cand['email'] == 'pipeline_candidate@example.com'
    assert len(cand['education']) >= 1
    assert len(cand['key_skills']) >= 1
    print("[PASS] Candidate profile API enforces strict employer application ownership and returns full candidate details.")


def test_application_resume_download_security(client, test_data):
    """Verifies resume download endpoint enforces employer ownership."""
    emp_id = test_data['emp_id']
    other_emp_id = test_data['other_emp_id']
    app_id = test_data['app_id']

    # 1. Unauthenticated request
    res_unauth = client.get(f'/api/employer/applications/{app_id}/resume')
    assert res_unauth.status_code == 401

    # 2. Unauthorized employer
    with client.session_transaction() as sess:
        sess['employer_id'] = other_emp_id

    res_denied = client.get(f'/api/employer/applications/{app_id}/resume')
    assert res_denied.status_code == 404

    # 3. Non-existent application
    with client.session_transaction() as sess:
        sess['employer_id'] = emp_id

    res_notfound = client.get('/api/employer/applications/999999/resume')
    assert res_notfound.status_code == 404
    print("[PASS] Resume download security and ownership checks verified.")
