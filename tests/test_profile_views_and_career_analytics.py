# -*- coding: utf-8 -*-
"""
Test Suite for Real Profile Views & Dynamic Career Performance Analytics:
1. Candidate profile views API (/api/user/profile_views) auth protection.
2. Zero profile views return 'No views yet' instead of fake/hardcoded numbers.
3. Employer full profile viewing triggers record_profile_view with 24h deduplication.
4. Interview Invite Rate calculated from candidate's real applications table (status in 'Interview', 'Selected').
5. Benchmark threshold: Requires >= 3 applications before showing percentage; shows 'Not enough data yet' otherwise.
6. user_dashboard.html template verification: confirms removal of hardcoded '142 Views' & '18.5%' and presence of dynamic hooks.
"""
import pytest
from app import app, db_cursor, record_profile_view


@pytest.fixture
def client():
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    with app.test_client() as client:
        yield client


@pytest.fixture
def analytics_test_data(client):
    """Sets up a candidate with applications and two employers for view tracking."""
    with db_cursor() as cursor:
        # 1. Candidate User
        cursor.execute("SELECT id FROM user WHERE email = 'analytics_cand@example.com'")
        c_row = cursor.fetchone()
        if not c_row:
            cursor.execute("""
                INSERT INTO user (name, email, password, mobile, headline, skills, experience, location)
                VALUES ('Ravi Kumar', 'analytics_cand@example.com', 'hashedpwd', '9877665544', 
                        'Full Stack Engineer', 'Python, React, MySQL', 3, 'Bengaluru')
            """)
            cand_id = cursor.lastrowid
        else:
            cand_id = c_row['id']

        # Clear existing profile views for clean test state
        cursor.execute("DELETE FROM profile_views WHERE candidate_id = %s", (cand_id,))

        # Clear existing applications for clean rate calculation
        cursor.execute("DELETE FROM applications WHERE user_id = %s", (cand_id,))

        # 2. Employer 1 (Stark Industries)
        cursor.execute("SELECT id FROM employee WHERE email = 'stark_recruiter@example.com'")
        emp1_row = cursor.fetchone()
        if not emp1_row:
            cursor.execute("""
                INSERT INTO employee (company_name, email, password, mobile)
                VALUES ('Stark Industries', 'stark_recruiter@example.com', 'hashedpwd', '9812345678')
            """)
            emp1_id = cursor.lastrowid
        else:
            emp1_id = emp1_row['id']

        # 3. Employer 2 (Wayne Enterprises)
        cursor.execute("SELECT id FROM employee WHERE email = 'wayne_recruiter@example.com'")
        emp2_row = cursor.fetchone()
        if not emp2_row:
            cursor.execute("""
                INSERT INTO employee (company_name, email, password, mobile)
                VALUES ('Wayne Enterprises', 'wayne_recruiter@example.com', 'hashedpwd', '9812345679')
            """)
            emp2_id = cursor.lastrowid
        else:
            emp2_id = emp2_row['id']

        # Job for employer 2 to allow pipeline viewing
        cursor.execute("SELECT id FROM jobs WHERE employer_id = %s AND title = 'Backend Developer'", (emp2_id,))
        job_row = cursor.fetchone()
        if not job_row:
            cursor.execute("""
                INSERT INTO jobs (employer_id, title, category, job_type, experience, location, skills, description, company_name)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (emp2_id, 'Backend Developer', 'IT & Software', 'Full-time', '2', 'Mumbai', 'Python, MySQL', 'Backend role', 'Wayne Enterprises'))
            job2_id = cursor.lastrowid
        else:
            job2_id = job_row['id']

        # Job application for candidate under employer 2
        cursor.execute("SELECT id FROM applications WHERE user_id = %s AND job_id = %s", (cand_id, job2_id))
        app_row = cursor.fetchone()
        if not app_row:
            cursor.execute("""
                INSERT INTO applications (user_id, job_id, user_name, user_email, user_mobile, qualification, experience_level, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (cand_id, job2_id, 'Ravi Kumar', 'analytics_cand@example.com', '9877665544', 'B.Tech', '3 Years', 'Applied'))

    return {
        'cand_id': cand_id,
        'emp1_id': emp1_id,
        'emp2_id': emp2_id,
        'job2_id': job2_id
    }


# ==================================================
# API & LOGIC TESTS
# ==================================================

def test_profile_views_unauthorized(client):
    """Verifies GET /api/user/profile_views returns 401 when not authenticated as candidate."""
    res = client.get('/api/user/profile_views')
    assert res.status_code == 401
    data = res.get_json()
    assert data['success'] is False


def test_candidate_zero_profile_views(client, analytics_test_data):
    """Verifies a candidate with 0 views receives 'No views yet' display."""
    cand_id = analytics_test_data['cand_id']

    with client.session_transaction() as sess:
        sess['user_id'] = cand_id
        sess['role'] = 'user'

    res = client.get('/api/user/profile_views')
    assert res.status_code == 200
    data = res.get_json()
    assert data['success'] is True
    assert data['distinct_views'] == 0
    assert data['total_views'] == 0
    assert data['view_count_display'] == "No views yet"
    assert data['has_views'] is False
    assert data['views'] == []


def test_employer_view_tracking_and_deduplication(client, analytics_test_data):
    """Verifies employer profile inspections log views with 24-hour deduplication."""
    cand_id = analytics_test_data['cand_id']
    emp1_id = analytics_test_data['emp1_id']
    emp2_id = analytics_test_data['emp2_id']

    # 1. Employer 1 views candidate profile from Talent Search
    with client.session_transaction() as sess:
        sess['employer_id'] = emp1_id
        sess['role'] = 'employer'

    res1 = client.get(f'/api/recruiter/candidate/{cand_id}')
    assert res1.status_code == 200

    # Employer 1 views again immediately (should be deduplicated)
    res1_dup = client.get(f'/api/recruiter/candidate/{cand_id}')
    assert res1_dup.status_code == 200

    # 2. Employer 2 views candidate profile from Applicant Pipeline
    with client.session_transaction() as sess:
        sess['employer_id'] = emp2_id
        sess['role'] = 'employer'

    res2 = client.get(f'/api/employer/candidate/{cand_id}/profile')
    assert res2.status_code == 200

    # 3. Candidate checks profile views
    with client.session_transaction() as sess:
        sess['user_id'] = cand_id
        sess['role'] = 'user'

    res_views = client.get('/api/user/profile_views')
    assert res_views.status_code == 200
    data = res_views.get_json()

    assert data['success'] is True
    assert data['distinct_views'] == 2
    assert data['total_views'] == 2
    assert data['view_count_display'] == "2 Companies"
    assert data['has_views'] is True
    assert len(data['views']) == 2

    # Check company names in views list
    company_names = [v['company_name'] for v in data['views']]
    assert 'Stark Industries' in company_names
    assert 'Wayne Enterprises' in company_names


def test_interview_invite_rate_calculation(client, analytics_test_data):
    """Verifies Interview Invite Rate calculates from real applications with >= 3 threshold."""
    cand_id = analytics_test_data['cand_id']
    job2_id = analytics_test_data['job2_id']

    with client.session_transaction() as sess:
        sess['user_id'] = cand_id
        sess['role'] = 'user'

    # Case A: 1 application (total < 3) -> Not enough data
    res_a = client.get('/api/user/profile_views')
    data_a = res_a.get_json()
    assert data_a['has_enough_application_data'] is False
    assert data_a['interview_invite_rate_display'] == "Not enough data yet"
    assert data_a['interview_invite_rate'] is None

    # Case B: Add 3 more applications for distinct jobs (Total 4: 2 'Applied', 1 'Interview', 1 'Selected')
    with db_cursor() as cursor:
        cursor.execute("""
            INSERT INTO jobs (employer_id, title, category, job_type, experience, location, skills, description, company_name)
            VALUES (%s, 'Job 3', 'IT', 'Full-time', '2', 'Remote', 'Python', 'Desc', 'Wayne Enterprises')
        """, (analytics_test_data['emp2_id'],))
        job3_id = cursor.lastrowid

        cursor.execute("""
            INSERT INTO jobs (employer_id, title, category, job_type, experience, location, skills, description, company_name)
            VALUES (%s, 'Job 4', 'IT', 'Full-time', '2', 'Remote', 'Python', 'Desc', 'Wayne Enterprises')
        """, (analytics_test_data['emp2_id'],))
        job4_id = cursor.lastrowid

        cursor.execute("""
            INSERT INTO jobs (employer_id, title, category, job_type, experience, location, skills, description, company_name)
            VALUES (%s, 'Job 5', 'IT', 'Full-time', '2', 'Remote', 'Python', 'Desc', 'Wayne Enterprises')
        """, (analytics_test_data['emp2_id'],))
        job5_id = cursor.lastrowid

        cursor.execute("""
            INSERT INTO applications (user_id, job_id, user_name, user_email, user_mobile, qualification, experience_level, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (cand_id, job3_id, 'Ravi Kumar', 'analytics_cand@example.com', '9877665544', 'B.Tech', '3 Years', 'Applied'))
        cursor.execute("""
            INSERT INTO applications (user_id, job_id, user_name, user_email, user_mobile, qualification, experience_level, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (cand_id, job4_id, 'Ravi Kumar', 'analytics_cand@example.com', '9877665544', 'B.Tech', '3 Years', 'Interview'))
        cursor.execute("""
            INSERT INTO applications (user_id, job_id, user_name, user_email, user_mobile, qualification, experience_level, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (cand_id, job5_id, 'Ravi Kumar', 'analytics_cand@example.com', '9877665544', 'B.Tech', '3 Years', 'Selected'))

    res_b = client.get('/api/user/profile_views')
    data_b = res_b.get_json()
    assert data_b['has_enough_application_data'] is True
    assert data_b['total_applications'] == 4
    assert data_b['interview_count'] == 2  # 1 Interview + 1 Selected
    assert data_b['interview_invite_rate'] == 50.0
    assert data_b['interview_invite_rate_display'] == "50%"


def test_user_dashboard_template_no_fake_metrics(client, analytics_test_data):
    """Verifies templates/user_dashboard.html contains no hardcoded fake numbers and has dynamic elements."""
    cand_id = analytics_test_data['cand_id']

    with client.session_transaction() as sess:
        sess['user_id'] = cand_id
        sess['user_name'] = 'Ravi Kumar'
        sess['role'] = 'user'

    res = client.get('/user_dashboard')
    assert res.status_code == 200
    html = res.get_data(as_text=True)

    # 1. Confirm fake hardcoded strings are REMOVED
    assert '142 Views' not in html
    assert '18.5%' not in html

    # 2. Confirm dynamic hooks and IDs are PRESENT
    assert 'id="stat-resume-views"' in html
    assert 'id="stat-interview-rate"' in html
    assert 'id="btn-toggle-viewers"' in html
    assert 'id="viewers-list-container"' in html
    assert 'loadCareerPerformance' in html
