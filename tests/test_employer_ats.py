# -*- coding: utf-8 -*-
"""
Test Suite for Employer Applicant Tracking System (ATS):
1. Enhanced Applicant Listing & KPI Statistics (/api/employer/applicants).
2. Multi-parameter Search (Name, Email, Skills, Tags), Filtering (Job, Stage), and Sorting (Match Score, ATS Score, Date, Name).
3. 8-Stage Recruitment Pipeline transitions with audit logging in application_stage_history with timestamps.
4. Recruiter Notes CRUD (/api/employer/applications/<app_id>/notes).
5. Candidate Custom Tagging (/api/employer/applications/<app_id>/tags).
6. Candidate Profile view with ATS score & Match score comparison.
7. Strict IDOR Isolation & Authorization Protection.
"""
import os
import sys
import json
import pytest

sys.path.insert(0, r"c:\Program Files\Ampps\www\job-portal-web-app")
from app import app, db_cursor, init_db

@pytest.fixture(autouse=True)
def ensure_db():
    init_db()

@pytest.fixture
def client():
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    with app.test_client() as client:
        yield client

@pytest.fixture
def ats_setup(client):
    """Sets up two employers, multiple candidates, jobs, and applications with ATS scores."""
    with db_cursor() as cursor:
        # 1. Employer A (Owner)
        cursor.execute("SELECT id FROM employee WHERE email = 'ats_owner_emp@example.com'")
        emp_a = cursor.fetchone()
        if not emp_a:
            cursor.execute("""
                INSERT INTO employee (company_name, email, password, mobile)
                VALUES ('ATS Owner Corp', 'ats_owner_emp@example.com', 'hashedpwd', '9876540001')
            """)
            emp_a_id = cursor.lastrowid
        else:
            emp_a_id = emp_a['id']

        # 2. Employer B (Unauthorized Attacker)
        cursor.execute("SELECT id FROM employee WHERE email = 'ats_other_emp@example.com'")
        emp_b = cursor.fetchone()
        if not emp_b:
            cursor.execute("""
                INSERT INTO employee (company_name, email, password, mobile)
                VALUES ('ATS Competitor Corp', 'ats_other_emp@example.com', 'hashedpwd', '9876540002')
            """)
            emp_b_id = cursor.lastrowid
        else:
            emp_b_id = emp_b['id']

        # 3. Candidates: User 1 (Senior Dev) & User 2 (Junior Dev)
        cursor.execute("SELECT id FROM user WHERE email = 'ats_cand_1@example.com'")
        u1 = cursor.fetchone()
        if not u1:
            cursor.execute("""
                INSERT INTO user (name, email, password, mobile, headline, skills, experience, location)
                VALUES ('Priya Sharma', 'ats_cand_1@example.com', 'pwd', '9811111111', 'Senior Full Stack Lead', 'Python, React, TypeScript, Docker, Kubernetes', 6, 'Bengaluru')
            """)
            u1_id = cursor.lastrowid
        else:
            u1_id = u1['id']

        cursor.execute("SELECT id FROM user WHERE email = 'ats_cand_2@example.com'")
        u2 = cursor.fetchone()
        if not u2:
            cursor.execute("""
                INSERT INTO user (name, email, password, mobile, headline, skills, experience, location)
                VALUES ('Rohan Verma', 'ats_cand_2@example.com', 'pwd', '9822222222', 'Junior Python Dev', 'Python, Flask, SQL', 1, 'Hyderabad')
            """)
            u2_id = cursor.lastrowid
        else:
            u2_id = u2['id']

        # 4. Resume Analyses with ATS scores
        cursor.execute("DELETE FROM resume_analyses WHERE user_id IN (%s, %s)", (u1_id, u2_id))
        cursor.execute("""
            INSERT INTO resume_analyses (user_id, filename, original_filename, file_path, ats_score, extracted_skills)
            VALUES (%s, 'priya_resume.pdf', 'Priya_Resume.pdf', 'priya_resume.pdf', 94, %s)
        """, (u1_id, json.dumps(['Python', 'React', 'TypeScript', 'Docker', 'Kubernetes'])))

        cursor.execute("""
            INSERT INTO resume_analyses (user_id, filename, original_filename, file_path, ats_score, extracted_skills)
            VALUES (%s, 'rohan_resume.pdf', 'Rohan_Resume.pdf', 'rohan_resume.pdf', 68, %s)
        """, (u2_id, json.dumps(['Python', 'Flask', 'SQL'])))

        # 5. Employer A Jobs
        cursor.execute("SELECT id FROM jobs WHERE employer_id = %s AND title = 'Lead Architect'", (emp_a_id,))
        job_1 = cursor.fetchone()
        if not job_1:
            cursor.execute("""
                INSERT INTO jobs (employer_id, title, category, job_type, experience, location, skills, description, company_name)
                VALUES (%s, 'Lead Architect', 'IT & Software', 'Full-time', '5+ Years', 'Bengaluru', 'Python, React, Kubernetes', 'Lead cloud architecture team.', 'ATS Owner Corp')
            """, (emp_a_id,))
            job_1_id = cursor.lastrowid
        else:
            job_1_id = job_1['id']

        cursor.execute("SELECT id FROM jobs WHERE employer_id = %s AND title = 'Junior Backend Developer'", (emp_a_id,))
        job_2 = cursor.fetchone()
        if not job_2:
            cursor.execute("""
                INSERT INTO jobs (employer_id, title, category, job_type, experience, location, skills, description, company_name)
                VALUES (%s, 'Junior Backend Developer', 'IT & Software', 'Full-time', '1-3 Years', 'Hyderabad', 'Python, Flask, SQL', 'Build backend endpoints.', 'ATS Owner Corp')
            """, (emp_a_id,))
            job_2_id = cursor.lastrowid
        else:
            job_2_id = job_2['id']

        # 6. Applications for Employer A
        cursor.execute("DELETE FROM applications WHERE user_id IN (%s, %s)", (u1_id, u2_id))
        cursor.execute("""
            INSERT INTO applications (job_id, user_id, user_name, user_email, user_mobile, qualification, experience_level, years_experience, skills, match_score, status, tags)
            VALUES (%s, %s, 'Priya Sharma', 'ats_cand_1@example.com', '9811111111', 'M.Tech CSE', '5+ Years', '6', 'Python, React, Kubernetes', 92, 'Applied', %s)
        """, (job_1_id, u1_id, json.dumps(['Top Talent', 'Fast Track'])))
        app_1_id = cursor.lastrowid

        cursor.execute("""
            INSERT INTO applications (job_id, user_id, user_name, user_email, user_mobile, qualification, experience_level, years_experience, skills, match_score, status, tags)
            VALUES (%s, %s, 'Rohan Verma', 'ats_cand_2@example.com', '9822222222', 'B.Tech IT', '1-3 Years', '1', 'Python, Flask', 65, 'Screening', %s)
        """, (job_2_id, u2_id, json.dumps(['Immediate Joiner'])))
        app_2_id = cursor.lastrowid

    return {
        'emp_a_id': emp_a_id,
        'emp_b_id': emp_b_id,
        'u1_id': u1_id,
        'u2_id': u2_id,
        'job_1_id': job_1_id,
        'job_2_id': job_2_id,
        'app_1_id': app_1_id,
        'app_2_id': app_2_id,
    }


def test_ats_applicants_listing_and_stats(client, ats_setup):
    """Verifies applicant list endpoint returns enriched candidate ATS and match data and KPI stats."""
    with client.session_transaction() as sess:
        sess['employer_id'] = ats_setup['emp_a_id']
        sess['role'] = 'employer'

    res = client.get('/api/employer/applicants')
    assert res.status_code == 200
    data = res.get_json()
    assert data['success'] is True
    assert len(data['applicants']) == 2
    assert data['stats']['total'] == 2
    assert data['stats']['applied'] >= 1
    assert data['stats']['screening'] >= 1

    app1 = next(a for a in data['applicants'] if a['id'] == ats_setup['app_1_id'])
    assert app1['candidate_name'] == 'Priya Sharma'
    assert app1['ats_score_value'] == 94
    assert '94%' in app1['ats_score_display']
    assert app1['match_score_value'] == 92
    assert 'Top Talent' in app1['tags_list']


def test_ats_search_and_filtering(client, ats_setup):
    """Verifies searching by keyword/skill/tag and filtering by stage or job ID."""
    with client.session_transaction() as sess:
        sess['employer_id'] = ats_setup['emp_a_id']
        sess['role'] = 'employer'

    # Search by Name
    res = client.get('/api/employer/applicants?q=Priya')
    assert res.status_code == 200
    data = res.get_json()
    assert len(data['applicants']) == 1
    assert data['applicants'][0]['candidate_name'] == 'Priya Sharma'

    # Search by Tag
    res = client.get('/api/employer/applicants?q=Immediate')
    assert res.status_code == 200
    data = res.get_json()
    assert len(data['applicants']) == 1
    assert data['applicants'][0]['candidate_name'] == 'Rohan Verma'

    # Filter by Job
    res = client.get(f"/api/employer/applicants?job_id={ats_setup['job_1_id']}")
    assert res.status_code == 200
    data = res.get_json()
    assert len(data['applicants']) == 1
    assert data['applicants'][0]['job_id'] == ats_setup['job_1_id']

    # Filter by Stage
    res = client.get('/api/employer/applicants?stage=Screening')
    assert res.status_code == 200
    data = res.get_json()
    assert len(data['applicants']) == 1
    assert data['applicants'][0]['status'] == 'Screening'

    # Sort by Match Score High
    res = client.get('/api/employer/applicants?sort=match_high')
    assert res.status_code == 200
    data = res.get_json()
    assert data['applicants'][0]['match_score_value'] >= data['applicants'][1]['match_score_value']

    # Sort by ATS Score High
    res = client.get('/api/employer/applicants?sort=ats_high')
    assert res.status_code == 200
    data = res.get_json()
    assert data['applicants'][0]['ats_score_value'] >= data['applicants'][1]['ats_score_value']


def test_ats_stage_transitions_and_history(client, ats_setup):
    """Verifies transition through recruitment stages and timestamped history tracking."""
    with client.session_transaction() as sess:
        sess['employer_id'] = ats_setup['emp_a_id']
        sess['role'] = 'employer'

    app_id = ats_setup['app_1_id']

    # Move from Applied -> Screening -> Shortlisted -> Interview -> Offer -> Hired
    stages = ['Screening', 'Shortlisted', 'Interview', 'Offer', 'Hired']
    for st in stages:
        res = client.post('/api/update_candidate_status', json={
            'app_id': app_id,
            'status': st,
            'notes': f'Candidate successfully passed to {st}'
        })
        assert res.status_code == 200
        assert res.get_json()['success'] is True

    # Retrieve stage history
    res = client.get(f'/api/employer/applications/{app_id}/history')
    assert res.status_code == 200
    data = res.get_json()
    assert data['success'] is True
    assert data['current_status'] == 'Hired'
    assert len(data['history']) == len(stages)

    first_transition = data['history'][0]
    assert first_transition['from_stage'] == 'Applied'
    assert first_transition['to_stage'] == 'Screening'
    assert 'created_at' in first_transition

    last_transition = data['history'][-1]
    assert last_transition['to_stage'] == 'Hired'


def test_ats_recruiter_notes_crud(client, ats_setup):
    """Verifies adding and fetching recruiter notes on candidate application."""
    with client.session_transaction() as sess:
        sess['employer_id'] = ats_setup['emp_a_id']
        sess['role'] = 'employer'

    app_id = ats_setup['app_1_id']

    # Empty note fails validation
    res = client.post(f'/api/employer/applications/{app_id}/notes', json={'note': '  '})
    assert res.status_code == 400

    # Add Note 1
    res1 = client.post(f'/api/employer/applications/{app_id}/notes', json={
        'note': 'Strong system design skills demonstrated in initial screen.'
    })
    assert res1.status_code == 201
    assert res1.get_json()['success'] is True

    # Add Note 2
    res2 = client.post(f'/api/employer/applications/{app_id}/notes', json={
        'note': 'Passed technical round with 9/10 rating. Recommending for leadership offer.'
    })
    assert res2.status_code == 201

    # Fetch Notes
    res_get = client.get(f'/api/employer/applications/{app_id}/notes')
    assert res_get.status_code == 200
    notes_data = res_get.get_json()
    assert notes_data['success'] is True
    assert len(notes_data['notes']) == 2
    assert 'Strong system design' in notes_data['notes'][1]['note']
    assert 'created_at' in notes_data['notes'][0]


def test_ats_candidate_tags_management(client, ats_setup):
    """Verifies adding and removing candidate tags."""
    with client.session_transaction() as sess:
        sess['employer_id'] = ats_setup['emp_a_id']
        sess['role'] = 'employer'

    app_id = ats_setup['app_1_id']

    # Add a new tag
    res = client.post(f'/api/employer/applications/{app_id}/tags', json={
        'tag': 'Culture Champion',
        'action': 'add'
    })
    assert res.status_code == 200
    tags = res.get_json()['tags']
    assert 'Culture Champion' in tags
    assert 'Top Talent' in tags

    # Remove a tag
    res_rem = client.post(f'/api/employer/applications/{app_id}/tags', json={
        'tag': 'Fast Track',
        'action': 'remove'
    })
    assert res_rem.status_code == 200
    tags_after = res_rem.get_json()['tags']
    assert 'Fast Track' not in tags_after
    assert 'Top Talent' in tags_after


def test_ats_candidate_profile_view_with_scores(client, ats_setup):
    """Verifies candidate profile modal data includes ATS score, Match score, tags, and stage history."""
    with client.session_transaction() as sess:
        sess['employer_id'] = ats_setup['emp_a_id']
        sess['role'] = 'employer'

    u1_id = ats_setup['u1_id']
    res = client.get(f'/api/employer/candidate/{u1_id}/profile')
    assert res.status_code == 200
    data = res.get_json()
    assert data['success'] is True
    cand = data['candidate']
    assert cand['name'] == 'Priya Sharma'
    assert cand['ats_score'] == 94
    assert cand['ats_score_display'] == '94%'
    assert cand['match_score'] == 92
    assert 'Top Talent' in cand['tags']
    assert 'stage_history' in cand


def test_ats_idor_protection(client, ats_setup):
    """Verifies that an unauthorized employer B cannot view, update, tag, or note Employer A's candidate."""
    with client.session_transaction() as sess:
        sess['employer_id'] = ats_setup['emp_b_id']
        sess['role'] = 'employer'

    app_1_id = ats_setup['app_1_id']
    u1_id = ats_setup['u1_id']

    # Cannot view candidate profile
    res1 = client.get(f'/api/employer/candidate/{u1_id}/profile')
    assert res1.status_code == 403

    # Cannot transition status
    res2 = client.post('/api/update_candidate_status', json={
        'app_id': app_1_id,
        'status': 'Hired'
    })
    assert res2.status_code == 403

    # Cannot add recruiter notes
    res3 = client.post(f'/api/employer/applications/{app_1_id}/notes', json={'note': 'Hacked note'})
    assert res3.status_code == 404

    # Cannot add tags
    res4 = client.post(f'/api/employer/applications/{app_1_id}/tags', json={'tag': 'Malicious', 'action': 'add'})
    assert res4.status_code == 404

    # Cannot download resume
    res5 = client.get(f'/api/employer/applications/{app_1_id}/resume')
    assert res5.status_code == 404
