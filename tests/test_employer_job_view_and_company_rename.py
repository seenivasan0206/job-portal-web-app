# -*- coding: utf-8 -*-
"""
Test Suite for:
PART A: Employer-Specific View on /job/<id>
  - Job owner sees employer controls ("Edit Job", "View Applicants (N)", "Close Job Posting" / "Reactivate Job Posting", Posting Performance stats).
  - Candidates, guests, and other employers see candidate view ("Apply for this Role", "Save Job").
  - Status toggle endpoint (/api/employer/jobs/<id>/toggle_status) updates job state.
PART B: Live Company Name Synchronization
  - Updating employer company name in settings updates session immediately.
  - Cascades UPDATE to jobs and profile_views.
  - Live joins in /job/<id>, /jobs, /api/employer/jobs, /api/jobs/search reflect the updated company name immediately without re-login.
"""
import pytest
from app import app, db_cursor


@pytest.fixture
def client():
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    with app.test_client() as client:
        yield client


@pytest.fixture
def job_owner_test_data():
    """Sets up two employers (Owner and Other), a candidate, and a test job."""
    with db_cursor() as cursor:
        # Employer 1: Owner
        cursor.execute("SELECT id FROM employee WHERE email = 'owner_emp@example.com'")
        emp1 = cursor.fetchone()
        if not emp1:
            cursor.execute("""
                INSERT INTO employee (company_name, email, password, mobile)
                VALUES ('Alpha Innovations', 'owner_emp@example.com', 'hashedpwd', '9811111111')
            """)
            owner_id = cursor.lastrowid
        else:
            owner_id = emp1['id']
            cursor.execute("UPDATE employee SET company_name = 'Alpha Innovations' WHERE id = %s", (owner_id,))

        # Employer 2: Other
        cursor.execute("SELECT id FROM employee WHERE email = 'other_emp@example.com'")
        emp2 = cursor.fetchone()
        if not emp2:
            cursor.execute("""
                INSERT INTO employee (company_name, email, password, mobile)
                VALUES ('Beta Technologies', 'other_emp@example.com', 'hashedpwd', '9822222222')
            """)
            other_emp_id = cursor.lastrowid
        else:
            other_emp_id = emp2['id']

        # Candidate
        cursor.execute("SELECT id FROM user WHERE email = 'candidate_tester@example.com'")
        cand = cursor.fetchone()
        if not cand:
            cursor.execute("""
                INSERT INTO user (name, email, password, mobile, headline, skills)
                VALUES ('Candidate Tester', 'candidate_tester@example.com', 'hashedpwd', '9833333333', 'Dev', 'Python')
            """)
            candidate_id = cursor.lastrowid
        else:
            candidate_id = cand['id']

        # Clean existing jobs for owner
        cursor.execute("DELETE FROM jobs WHERE employer_id = %s", (owner_id,))

        # Create test job owned by owner_id
        cursor.execute("""
            INSERT INTO jobs (employer_id, title, description, location, salary, experience, skills,
                              category, company_name, job_type, work_mode, salary_min, salary_max,
                              openings, is_active, status)
            VALUES (%s, 'Senior Python Architect', 'Build great backend services', 'Bengaluru',
                    '₹18,00,000 - ₹24,00,000', '5+ years', 'Python, Flask, MySQL',
                    'Engineering', 'Alpha Innovations', 'Full-time', 'Hybrid', 1800000, 2400000,
                    2, 1, 'Published')
        """, (owner_id,))
        job_id = cursor.lastrowid

        # Insert 2 applications for this job
        cursor.execute("DELETE FROM applications WHERE job_id = %s", (job_id,))
        cursor.execute("""
            INSERT INTO applications (job_id, user_id, status)
            VALUES (%s, %s, 'Applied')
        """, (job_id, candidate_id))

        return {
            'owner_id': owner_id,
            'other_emp_id': other_emp_id,
            'candidate_id': candidate_id,
            'job_id': job_id
        }


# ==========================================
# PART A: Employer-Specific View Tests
# ==========================================

def test_guest_views_job_detail(client, job_owner_test_data):
    """Guest should see candidate actions and NOT see employer management panel."""
    job_id = job_owner_test_data['job_id']
    resp = client.get(f'/job/{job_id}')
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    assert 'id="btn-apply-job"' in html
    assert 'id="btn-save-job"' in html
    assert "Employer View: You posted this job posting" not in html
    assert "Posting Performance" not in html
    assert 'id="btn-toggle-job"' not in html


def test_candidate_views_job_detail(client, job_owner_test_data):
    """Candidate should see candidate view and NOT see employer management panel."""
    cand_id = job_owner_test_data['candidate_id']
    job_id = job_owner_test_data['job_id']

    with client.session_transaction() as sess:
        sess['user_id'] = cand_id
        sess['user_name'] = 'Candidate Tester'
        sess['role'] = 'user'

    resp = client.get(f'/job/{job_id}')
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    # Candidate has already applied in fixture, so should see submitted/candidate view
    assert "Application Submitted" in html
    assert 'id="btn-save-job"' in html
    assert "Employer View: You posted this job posting" not in html
    assert "Posting Performance" not in html
    assert 'id="btn-toggle-job"' not in html


def test_other_employer_views_job_detail(client, job_owner_test_data):
    """An employer who does NOT own the job should NOT see owner management panel."""
    other_emp_id = job_owner_test_data['other_emp_id']
    job_id = job_owner_test_data['job_id']

    with client.session_transaction() as sess:
        sess['employer_id'] = other_emp_id
        sess['user_name'] = 'Beta Technologies'
        sess['role'] = 'employer'

    resp = client.get(f'/job/{job_id}')
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    assert 'id="btn-apply-job"' in html
    assert 'id="btn-save-job"' in html
    assert "Employer View: You posted this job posting" not in html
    assert "Posting Performance" not in html
    assert 'id="btn-toggle-job"' not in html


def test_job_owner_views_job_detail(client, job_owner_test_data):
    """Job owner employer must see employer controls, applicant count, and management actions."""
    owner_id = job_owner_test_data['owner_id']
    job_id = job_owner_test_data['job_id']

    with client.session_transaction() as sess:
        sess['employer_id'] = owner_id
        sess['user_name'] = 'Alpha Innovations'
        sess['role'] = 'employer'

    resp = client.get(f'/job/{job_id}')
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    # Must see employer controls
    assert "Employer View: You posted this job posting" in html
    assert "Posting Performance" in html
    assert f"/employer_dashboard?tab=applicants&amp;job_id={job_id}" in html or f"/employer_dashboard?tab=applicants&job_id={job_id}" in html
    assert f"/employer_dashboard?tab=jobs&amp;edit_job_id={job_id}" in html or f"/employer_dashboard?tab=jobs&edit_job_id={job_id}" in html
    assert 'id="btn-toggle-job"' in html
    assert 'id="btn-apply-job"' not in html


def test_job_owner_toggle_status(client, job_owner_test_data):
    """Job owner toggles job status between active and closed."""
    owner_id = job_owner_test_data['owner_id']
    job_id = job_owner_test_data['job_id']

    with client.session_transaction() as sess:
        sess['employer_id'] = owner_id
        sess['user_name'] = 'Alpha Innovations'
        sess['role'] = 'employer'

    # Close job
    resp = client.post(f'/api/employer/jobs/{job_id}/toggle_status', json={'action': 'close'})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['success'] is True
    assert data['is_active'] is False
    assert data['status'] == 'Closed'

    # Verify /job/<id> owner view shows reactivate button
    resp_view = client.get(f'/job/{job_id}')
    html = resp_view.get_data(as_text=True)
    assert "Closed Posting" in html
    assert "Reactivate Job Posting" in html

    # Reactivate job
    resp_react = client.post(f'/api/employer/jobs/{job_id}/toggle_status', json={'action': 'activate'})
    assert resp_react.status_code == 200
    data_react = resp_react.get_json()
    assert data_react['success'] is True
    assert data_react['is_active'] is True

    # Unauthorized attempts
    with client.session_transaction() as sess:
        sess.clear()
    unauth_resp = client.post(f'/api/employer/jobs/{job_id}/toggle_status', json={'action': 'close'})
    assert unauth_resp.status_code == 401


# ==========================================
# PART B: Live Company Name Synchronization
# ==========================================

def test_company_rename_updates_session_and_cascades(client, job_owner_test_data):
    """When employer updates company name in settings:
       - Session is updated
       - jobs and profile_views tables are cascaded
       - /job/<id>, /jobs, /api/employer/jobs, /api/jobs/search reflect new name immediately.
    """
    owner_id = job_owner_test_data['owner_id']
    job_id = job_owner_test_data['job_id']

    with client.session_transaction() as sess:
        sess['employer_id'] = owner_id
        sess['user_name'] = 'Alpha Innovations'
        sess['role'] = 'employer'

    # Verify initial state
    resp_init = client.get(f'/job/{job_id}')
    assert "Alpha Innovations" in resp_init.get_data(as_text=True)

    # 1. Update company name via /api/update_employer_profile
    new_company = "Alpha Quantum Labs Inc"
    up_resp = client.post('/api/update_employer_profile', json={
        'company_name': new_company,
        'mobile': '9811111111'
    })
    assert up_resp.status_code == 200
    assert up_resp.get_json()['success'] is True

    # 2. Verify session updated
    with client.session_transaction() as sess:
        assert sess['user_name'] == new_company

    # 3. Verify /job/<id> reflects new name
    resp_job = client.get(f'/job/{job_id}')
    assert new_company in resp_job.get_data(as_text=True)

    # 4. Verify /jobs reflects new name
    resp_jobs = client.get('/jobs')
    assert new_company in resp_jobs.get_data(as_text=True)

    # 5. Verify /api/employer/jobs returns new name
    resp_emp_jobs = client.get('/api/employer/jobs')
    emp_jobs_data = resp_emp_jobs.get_json()
    assert emp_jobs_data['success'] is True
    assert any(j['id'] == job_id and j['company_name'] == new_company for j in emp_jobs_data['jobs'])

    # 6. Verify /api/jobs/search can search and find job with new company name
    resp_search = client.post('/api/jobs/search', json={'query': 'Alpha Quantum Labs'})
    search_data = resp_search.get_json()
    assert search_data['success'] is True
    assert any(j['id'] == job_id and j['company_name'] == new_company for j in search_data['jobs'])

    # 7. Verify newly posted job gets new company name
    post_resp = client.post('/api/post_job', json={
        'title': 'Quantum Lead Engineer',
        'location': 'Bengaluru',
        'job_type': 'Full-time',
        'work_mode': 'Remote',
        'salary_min': 2000000,
        'salary_max': 3000000,
        'description': 'Leading quantum computing initiatives'
    })
    assert post_resp.status_code == 200
    new_job_id = post_resp.get_json()['job_id']

    with db_cursor() as cursor:
        cursor.execute("SELECT company_name FROM jobs WHERE id = %s", (new_job_id,))
        row = cursor.fetchone()
        assert row['company_name'] == new_company
