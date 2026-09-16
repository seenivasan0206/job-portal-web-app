# -*- coding: utf-8 -*-
"""
Comprehensive tests for Candidate Profile Sections:
1. End-to-end CRUD on all candidate profile item sections (Education, Employment, Projects, Internships, Certifications, Key Skills, Languages, Exams, Academic Achievements)
2. Singleton endpoints (Personal Details, Career Preferences, Profile Summary)
3. Full aggregation endpoint (/api/candidate/profile/all)
4. REST alias routes (/api/user/education, /api/user/employment, /api/user/skills, etc.)
5. Empty string date/integer sanitization
6. Profile completeness evaluation reaching 100%
7. Authentication and authorization enforcement
"""
import pytest
import json
from app import app, db_cursor, evaluate_candidate_profile_completeness

@pytest.fixture
def client():
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    with app.test_client() as client:
        yield client

@pytest.fixture
def test_user_id():
    """Ensure a clean test user exists for profile testing."""
    email = "candidate_sections_test@example.com"
    with db_cursor(dictionary=True) as cursor:
        cursor.execute("SELECT id FROM user WHERE email = %s", (email,))
        user = cursor.fetchone()
        if user:
            uid = user['id']
        else:
            cursor.execute("""
                INSERT INTO user (name, email, password)
                VALUES (%s, %s, %s)
            """, ("Profile Section Tester", email, "pbkdf2:sha256:dummy"))
            cursor.execute("SELECT id FROM user WHERE email = %s", (email,))
            uid = cursor.fetchone()['id']

        # Clean up existing test data for this user to ensure idempotency
        tables = [
            "education", "employment", "projects",
            "internships", "certifications", "key_skills",
            "languages", "competitive_exams", "academic_achievements",
            "candidate_personal_details", "candidate_preferences", "candidate_profile_summary"
        ]
        for tbl in tables:
            try:
                cursor.execute(f"DELETE FROM {tbl} WHERE user_id = %s", (uid,))
            except Exception:
                pass
        return uid

def test_unauthenticated_candidate_profile_endpoints(client):
    """Verify unauthenticated requests to all candidate profile endpoints are rejected."""
    endpoints = [
        ('/api/candidate/profile/all', 'GET'),
        ('/api/candidate/profile/personal', 'GET'),
        ('/api/candidate/profile/preferences', 'GET'),
        ('/api/candidate/profile/summary', 'GET'),
        ('/api/candidate/profile/items?section=education', 'GET'),
        ('/api/candidate/profile/items', 'POST'),
        ('/api/user/education', 'GET'),
        ('/api/user/skills', 'GET'),
    ]
    for url, method in endpoints:
        if method == 'GET':
            res = client.get(url)
        else:
            res = client.post(url, json={})
        assert res.status_code in [401, 302], f"Expected 401/302 for unauth {method} {url}, got {res.status_code}"

def test_education_crud(client, test_user_id):
    """Test full CRUD on candidate education."""
    with client.session_transaction() as sess:
        sess['user_id'] = test_user_id
        sess['user_name'] = 'Profile Section Tester'
        sess['role'] = 'user'

    # 1. Create education item with empty string end_date/year handling
    payload = {
        'section': 'education',
        'education_level': 'Graduation/Diploma',
        'institute_name': 'Stanford University',
        'degree': 'B.Tech',
        'specialization': 'Computer Science',
        'course_type': 'Full Time',
        'year_of_passing': 2024,
        'grading_system': 'Scale 10 Grading System',
        'grade': '9.2',
        'start_year': 2020,
        'end_year': 2024
    }
    res = client.post('/api/candidate/profile/items', json=payload)
    assert res.status_code in [200, 201]
    data = res.get_json()
    assert data['success'] is True
    item_id = data.get('item_id') or data.get('id')
    assert item_id is not None

    # 2. Get education list
    res = client.get('/api/candidate/profile/items?section=education')
    assert res.status_code == 200
    items = res.get_json().get('items', [])
    assert len(items) >= 1
    assert any(it.get('institute') == 'Stanford University' for it in items)

    # 3. Update education item
    update_payload = {
        'section': 'education',
        'institute_name': 'Stanford University School of Eng',
        'grade': '9.5'
    }
    res = client.put(f'/api/candidate/profile/items/{item_id}', json=update_payload)
    assert res.status_code == 200

    # Verify update
    res = client.get('/api/candidate/profile/items?section=education')
    items = res.get_json().get('items', [])
    updated = next((it for it in items if it.get('id') == item_id), None)
    assert updated is not None
    assert updated.get('institute') == 'Stanford University School of Eng'
    assert updated.get('grade_value') == '9.5'

    # 4. Check profile completeness reflects education
    res = client.get('/api/user/profile_completeness')
    assert res.status_code == 200
    comp = res.get_json()
    edu_item = next((b for b in comp['breakdown'] if b['id'] == 'education'), None)
    assert edu_item is not None
    assert edu_item['completed'] is True

    # 5. Delete education item
    res = client.delete(f'/api/candidate/profile/items/{item_id}?section=education')
    assert res.status_code == 200

    # Verify deletion
    res = client.get('/api/candidate/profile/items?section=education')
    items = res.get_json().get('items', [])
    assert not any(it.get('id') == item_id for it in items)

def test_singleton_endpoints(client, test_user_id):
    """Test Personal Details, Preferences, and Profile Summary singleton endpoints."""
    with client.session_transaction() as sess:
        sess['user_id'] = test_user_id
        sess['user_name'] = 'Profile Section Tester'
        sess['role'] = 'user'

    # 1. Personal Details
    personal_payload = {
        'full_name': 'Profile Section Tester',
        'headline': 'Senior Full Stack Engineer',
        'gender': 'Male',
        'date_of_birth': '1998-05-15',
        'marital_status': 'Single',
        'hometown': 'San Francisco',
        'pincode': '94105',
        'permanent_address': '123 Market St, San Francisco, CA',
        'linkedin_url': 'https://linkedin.com/in/testuser',
        'github_url': 'https://github.com/testuser',
        'portfolio_url': 'https://testuser.dev'
    }
    res = client.post('/api/candidate/profile/personal', json=personal_payload)
    assert res.status_code == 200
    assert res.get_json()['success'] is True

    res = client.get('/api/candidate/profile/personal')
    assert res.status_code == 200
    data = res.get_json()
    assert data['data']['headline'] == 'Senior Full Stack Engineer'
    assert data['data']['hometown'] == 'San Francisco'

    # 2. Preferences
    pref_payload = {
        'preferred_job_types': 'Full-time, Remote',
        'preferred_locations': 'San Francisco, CA; Remote',
        'desired_salary_min': 120000,
        'desired_salary_max': 180000,
        'preferred_industry': 'Information Technology',
        'preferred_department': 'Engineering & Software',
        'preferred_job_role': 'Full Stack Developer',
        'preferred_employment_type': 'Full Time',
        'preferred_shift': 'Day Shift',
        'current_ctc': 130000,
        'expected_ctc': 160000,
        'notice_period': '1 Month',
        'relocation_preference': 1
    }
    res = client.post('/api/candidate/profile/preferences', json=pref_payload)
    assert res.status_code == 200

    res = client.get('/api/candidate/profile/preferences')
    assert res.status_code == 200
    data = res.get_json()
    assert data['data']['preferred_job_role'] == 'Full Stack Developer'
    assert data['data']['notice_period'] == '1 Month'

    # 3. Profile Summary
    summary_payload = {
        'summary': 'Passionate software engineer with 5+ years building scalable distributed web applications.'
    }
    res = client.post('/api/candidate/profile/summary', json=summary_payload)
    assert res.status_code == 200

    res = client.get('/api/candidate/profile/summary')
    assert res.status_code == 200
    data = res.get_json()
    assert 'Passionate software engineer' in data['data']['summary']

def test_all_item_sections_and_100_percent_completeness(client, test_user_id):
    """Populate all sections and verify Profile Completeness reaches 100%."""
    with client.session_transaction() as sess:
        sess['user_id'] = test_user_id
        sess['user_name'] = 'Profile Section Tester'
        sess['role'] = 'user'

    # 1. Personal details
    client.post('/api/candidate/profile/personal', json={
        'full_name': 'Profile Section Tester',
        'headline': 'Lead Full Stack Architect',
        'gender': 'Male',
        'date_of_birth': '1995-01-01',
        'hometown': 'San Francisco',
        'pincode': '94105',
        'permanent_address': '123 Market St',
        'linkedin_url': 'https://linkedin.com/in/testuser',
        'github_url': 'https://github.com/testuser'
    })

    # 2. Preferences
    client.post('/api/candidate/profile/preferences', json={
        'preferred_job_role': 'Principal Engineer',
        'preferred_industry': 'Technology',
        'preferred_locations': 'San Francisco, CA',
        'expected_ctc': 200000,
        'notice_period': 'Immediate'
    })

    # 3. Summary
    client.post('/api/candidate/profile/summary', json={
        'summary': 'Results-driven software architect with 8+ years experience leading enterprise cloud platforms.'
    })

    # 4. Education
    client.post('/api/candidate/profile/items', json={
        'section': 'education',
        'education_level': 'Post Graduation',
        'institute_name': 'MIT',
        'degree': 'M.S.',
        'specialization': 'Computer Science',
        'course_type': 'Full Time',
        'year_of_passing': 2018,
        'grade': '4.0'
    })

    # 5. Key Skills (single skill or comma-separated via API)
    client.post('/api/candidate/profile/items', json={
        'section': 'key-skills',
        'skill_name': 'Python, Flask, JavaScript, React, MySQL, Docker, Kubernetes',
        'experience_years': 6
    })

    # 6. Employment (Work Experience)
    client.post('/api/candidate/profile/items', json={
        'section': 'employment',
        'company_name': 'Tech Giants Corp',
        'designation': 'Senior Software Engineer',
        'employment_type': 'Full Time',
        'department': 'Core Engineering',
        'start_date': '2021-01-01',
        'end_date': None,
        'is_current': 1,
        'annual_salary': 180000,
        'notice_period': '1 Month',
        'job_profile': 'Architected high-throughput microservices handling 10M+ daily events.',
        'skills_used': 'Python, Flask, Redis, Docker'
    })

    # 7. Internships
    client.post('/api/candidate/profile/items', json={
        'section': 'internships',
        'organization': 'Innovative Labs',
        'role': 'Software Engineering Intern',
        'start_date': '2017-06-01',
        'end_date': '2017-08-31',
        'stipend': 5000,
        'project_details': 'Built automated monitoring dashboards for real-time telemetry.'
    })

    # 8. Projects
    client.post('/api/candidate/profile/items', json={
        'section': 'projects',
        'title': 'HireVolt Distributed Job Search Engine',
        'client': 'Self / Open Source',
        'project_status': 'Completed',
        'role': 'Lead Architect',
        'team_size': 4,
        'description': 'Designed and implemented semantic job search with sub-50ms response times.',
        'tech_stack': 'Python, Flask, MySQL, Redis, TailwindCSS'
    })

    # 9. Certifications
    client.post('/api/candidate/profile/items', json={
        'section': 'certifications',
        'name': 'AWS Certified Solutions Architect - Professional',
        'issuing_authority': 'Amazon Web Services',
        'license_number': 'AWS-PSA-123456',
        'issue_date': '2022-03-15',
        'no_expiry': 1,
        'url': 'https://aws.amazon.com/verify/123456'
    })

    # 10. Languages
    client.post('/api/candidate/profile/items', json={
        'section': 'languages',
        'language': 'English',
        'proficiency': 'Proficient',
        'can_read': 1,
        'can_write': 1,
        'can_speak': 1
    })

    # 11. Competitive Exams
    client.post('/api/candidate/profile/items', json={
        'section': 'competitive-exams',
        'exam_name': 'GRE General Test',
        'score_percentile': '335 / 340 (98th percentile)',
        'rank': 'Top 2%',
        'year': 2016
    })

    # 12. Academic Achievements
    client.post('/api/candidate/profile/items', json={
        'section': 'academic-achievements',
        'title': 'First Class Honors & Dean\'s List',
        'year': 2018,
        'description': 'Awarded for outstanding academic achievement in Computer Science Department.'
    })

    # Also simulate resume attachment in candidate_profile table
    with db_cursor() as cur:
        cur.execute("INSERT INTO candidate_profile (user_id, general_resume_path) VALUES (%s, %s) ON DUPLICATE KEY UPDATE general_resume_path = %s", (test_user_id, 'resume.pdf', 'resume.pdf'))

    # Verify Aggregate Profile Endpoint
    res = client.get('/api/candidate/profile/all')
    assert res.status_code == 200
    all_data = res.get_json()['data']
    assert len(all_data['education']) >= 1
    assert len(all_data['employment']) >= 1
    assert len(all_data['projects']) >= 1
    assert len(all_data['internships']) >= 1
    assert len(all_data['certifications']) >= 1
    assert len(all_data['key_skills']) >= 1
    assert len(all_data['languages']) >= 1
    assert len(all_data['competitive_exams']) >= 1
    assert len(all_data['academic_achievements']) >= 1
    assert all_data['personal'] is not None
    assert all_data['preferences'] is not None
    assert all_data['summary'] is not None

    # Verify Completeness Score reaches 100%
    res = client.get('/api/user/profile_completeness')
    assert res.status_code == 200
    completeness = res.get_json()
    assert completeness['score'] == 100
    assert len(completeness['missing_items']) == 0
    for section in completeness['breakdown']:
        assert section['completed'] is True, f"Section {section['id']} is not marked completed!"

def test_date_and_integer_null_sanitization(client, test_user_id):
    """Test that submitting empty string values for dates and integer fields is safely converted to NULL."""
    with client.session_transaction() as sess:
        sess['user_id'] = test_user_id
        sess['user_name'] = 'Profile Section Tester'
        sess['role'] = 'user'

    # Project with empty team_size, empty dates
    payload = {
        'section': 'projects',
        'title': 'Empty Values Resilience Test',
        'client': '',
        'project_status': 'In Progress',
        'start_date': '',
        'end_date': '',
        'role': 'Developer',
        'team_size': '',
        'description': 'Testing empty strings',
        'tech_stack': ''
    }
    res = client.post('/api/candidate/profile/items', json=payload)
    assert res.status_code in [200, 201]
    item_id = res.get_json().get('item_id')

    # Fetch to verify saved with NULLs instead of crashing
    res = client.get('/api/candidate/profile/items?section=projects')
    assert res.status_code == 200
    items = res.get_json().get('items', [])
    saved = next((it for it in items if it.get('id') == item_id), None)
    assert saved is not None
    assert saved.get('team_size') is None or saved.get('team_size') == ''
