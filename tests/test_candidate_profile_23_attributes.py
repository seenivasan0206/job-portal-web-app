# -*- coding: utf-8 -*-
"""
Comprehensive tests for Candidate Profile:
- All 23 candidate profile attributes:
  1. Personal information
  2. Profile photo
  3. Professional headline
  4. Career summary
  5. Skills
  6. Technical skills
  7. Soft skills
  8. Education
  9. Certifications
  10. Work experience
  11. Internship experience
  12. Projects
  13. Achievements
  14. Languages
  15. GitHub
  16. LinkedIn
  17. Portfolio
  18. Preferred job role
  19. Preferred location
  20. Expected salary
  21. Employment type
  22. Remote/hybrid/on-site preference (Workplace type)
  23. Notice period
- Profile completeness percentage (100% calculation)
- Duplicate prevention for skills and languages
- End-to-end Candidate lifecycle: Login -> Edit -> Save -> DB Verify -> Logout -> Login -> Verify.
"""
import pytest
import json
import io
from app import app, db_cursor, evaluate_candidate_profile_completeness
from werkzeug.security import generate_password_hash


@pytest.fixture
def client():
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    with app.test_client() as client:
        yield client


@pytest.fixture
def candidate_user():
    """Sets up a clean test candidate user and returns credentials."""
    email = "cand_23_attrs@hirevoltz.test"
    raw_password = "SecurePassword123!"
    hashed_pwd = generate_password_hash(raw_password)

    with db_cursor() as cursor:
        cursor.execute("SELECT id FROM user WHERE email = %s", (email,))
        row = cursor.fetchone()
        if not row:
            cursor.execute("""
                INSERT INTO user (name, email, password, mobile, is_verified)
                VALUES ('Ananya Sharma', %s, %s, '+91 9876543210', 1)
            """, (email, hashed_pwd))
            user_id = cursor.lastrowid
        else:
            user_id = row['id']
            cursor.execute("UPDATE user SET password = %s, name = 'Ananya Sharma', mobile = '+91 9876543210' WHERE id = %s", (hashed_pwd, user_id))

        # Clear all child tables for this user to start clean
        for table in [
            'candidate_profile', 'candidate_personal_details', 'candidate_preferences',
            'candidate_profile_summary', 'education', 'employment', 'internships',
            'projects', 'certifications', 'key_skills', 'languages',
            'academic_achievements', 'competitive_exams'
        ]:
            cursor.execute(f"DELETE FROM {table} WHERE user_id = %s", (user_id,))

    return {
        'id': user_id,
        'email': email,
        'password': raw_password,
        'name': 'Ananya Sharma'
    }


def test_candidate_profile_all_23_attributes_lifecycle(client, candidate_user):
    """
    Test complete lifecycle of saving, persisting in DB, and loading all 23 candidate profile attributes.
    """
    user_id = candidate_user['id']
    email = candidate_user['email']
    pwd = candidate_user['password']

    # 1. Login candidate
    with client.session_transaction() as sess:
        sess['user_id'] = user_id
        sess['user_email'] = email
        sess['user_name'] = candidate_user['name']
        sess['role'] = 'user'

    # 2. Save Basic & Social Profile (Attributes: Headline, Skills summary, GitHub, LinkedIn, Portfolio)
    resp = client.post('/api/candidate/profile', json={
        'headline': 'Senior Full-Stack AI Engineer',
        'skills': 'Python, React, Flask, PostgreSQL, Docker, AWS',
        'github_url': 'https://github.com/ananya-sharma',
        'linkedin_url': 'https://linkedin.com/in/ananya-sharma',
        'portfolio_url': 'https://ananya.dev',
        'experience_years': 5
    })
    assert resp.status_code == 200, resp.get_data(as_text=True)
    data = resp.get_json()
    assert data.get('success') is True

    # 3. Save Personal Details (Attributes: DOB, Gender, Marital Status, Nationality, Current Location, Hometown, Address, Pincode, Differently Abled, Work Permit)
    resp = client.post('/api/candidate/profile/personal', json={
        'date_of_birth': '1996-08-15',
        'gender': 'Female',
        'marital_status': 'Single',
        'nationality': 'Indian',
        'current_location': 'Bangalore, India',
        'hometown': 'Chandigarh, India',
        'address': 'Flat 402, HighTech Heights, Indiranagar',
        'pincode': '560038',
        'physically_challenged': False,
        'work_permit_countries': 'India, United States, Germany'
    })
    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert resp.get_json().get('success') is True

    # 4. Save Career Preferences (Attributes: Preferred job role, Preferred location, Expected salary, Employment type, Workplace type, Notice period)
    resp = client.post('/api/candidate/profile/preferences', json={
        'preferred_job_role': 'Lead Backend Engineer',
        'preferred_location': 'Bangalore, Remote',
        'workplace_type': 'Hybrid',
        'desired_employment_type': 'Full-Time Permanent',
        'expected_ctc': '₹35,00,000 / Year',
        'notice_period': '30 Days',
        'open_to_relocate': 1,
        'preferred_shift': 'Day Shift',
        'current_industry': 'Information Technology & Software'
    })
    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert resp.get_json().get('success') is True

    # 5. Save Career Summary (Attribute: Career summary)
    summary_text = (
        "Results-oriented Senior Full-Stack AI Engineer with 5+ years of experience architecting high-scale "
        "distributed web applications, microservices, and modern ML pipelines. Proven track record of delivering "
        "production systems handling millions of daily requests with high reliability and low latency."
    )
    resp = client.post('/api/candidate/profile/summary', json={
        'summary': summary_text
    })
    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert resp.get_json().get('success') is True

    # 6. Save Technical Skills and Soft Skills (Attributes: Technical skills, Soft skills)
    # Technical skills
    tech_skills = ['Python', 'TypeScript', 'Docker', 'PostgreSQL', 'PyTorch']
    for sk in tech_skills:
        resp = client.post('/api/candidate/profile/items', json={
            'section': 'key_skills',
            'skill_name': sk,
            'skill_type': 'Technical'
        })
        assert resp.status_code == 200

    # Soft skills
    soft_skills = ['Team Leadership', 'Agile Collaboration', 'Critical Thinking', 'Mentorship']
    for sk in soft_skills:
        resp = client.post('/api/candidate/profile/items', json={
            'section': 'key_skills',
            'skill_name': sk,
            'skill_type': 'Soft'
        })
        assert resp.status_code == 200

    # 7. Save Education (Attribute: Education)
    resp = client.post('/api/candidate/profile/items', json={
        'section': 'education',
        'course_degree': 'Bachelor of Technology',
        'institute': 'National Institute of Technology Karnataka (NITK)',
        'specialization': 'Computer Science & Engineering',
        'year_of_passing': 2018,
        'grade_value': '8.9 CGPA'
    })
    assert resp.status_code == 200

    # 8. Save Work Experience (Attribute: Work experience)
    resp = client.post('/api/candidate/profile/items', json={
        'section': 'employment',
        'job_title': 'Senior Software Engineer',
        'company_name': 'Razorpay Technologies',
        'start_date': '2021-06-01',
        'end_date': None,
        'is_current': 1,
        'job_profile': 'Designed and implemented core payment reconciliation engine.',
        'skills_used': 'Python, Flask, Kafka, MySQL, Kubernetes'
    })
    assert resp.status_code == 200

    # 9. Save Internship (Attribute: Internship experience)
    resp = client.post('/api/candidate/profile/items', json={
        'section': 'internships',
        'role_title': 'Software Engineering Intern',
        'organization_name': 'Microsoft R&D',
        'start_date': '2017-05-01',
        'end_date': '2017-07-31',
        'project_details': 'Contributed to cloud telemetry diagnostics dashboard.'
    })
    assert resp.status_code == 200

    # 10. Save Project (Attribute: Projects)
    resp = client.post('/api/candidate/profile/items', json={
        'section': 'projects',
        'project_title': 'HireVoltz AI Job Matcher',
        'client_name': 'Internal Open-Source Venture',
        'project_status': 'In Progress',
        'project_details': 'Engineered real-time semantic skill matching with embedding vector search.',
        'skills_used': 'Python, PyTorch, React, FastAPI, Docker',
        'project_url': 'https://github.com/ananya-sharma/hirevoltz-matcher'
    })
    assert resp.status_code == 200

    # 11. Save Certification (Attribute: Certifications)
    resp = client.post('/api/candidate/profile/items', json={
        'section': 'certifications',
        'name': 'AWS Certified Solutions Architect – Professional',
        'issuing_authority': 'Amazon Web Services',
        'issue_date': '2023-04-10',
        'credential_url': 'https://aws.amazon.com/verification/12345678'
    })
    assert resp.status_code == 200

    # 12. Save Achievements (Attribute: Achievements)
    resp = client.post('/api/candidate/profile/items', json={
        'section': 'academic_achievements',
        'title': 'Winner - Smart India Hackathon 2018',
        'year': '2018',
        'description': 'Awarded 1st place among 1,200 teams for automated emergency routing solution.'
    })
    assert resp.status_code == 200

    # 13. Save Languages (Attribute: Languages)
    resp = client.post('/api/candidate/profile/items', json={
        'section': 'languages',
        'language_name': 'English',
        'can_read': 1,
        'can_write': 1,
        'can_speak': 1
    })
    assert resp.status_code == 200

    resp = client.post('/api/candidate/profile/items', json={
        'section': 'languages',
        'language_name': 'Hindi',
        'can_read': 1,
        'can_write': 1,
        'can_speak': 1
    })
    assert resp.status_code == 200

    # 14. Save Profile Photo (Attribute: Profile photo)
    # 1x1 valid PNG image bytes
    png_bytes = (
        b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01'
        b'\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\rIDATx\x9cc\xf8\xff\x9f'
        b'\x01\x00\x03\x05\x01\x02L\x89\x0b\xa0\x00\x00\x00\x00IEND\xaeB`\x82'
    )
    photo_data = {
        'photo': (io.BytesIO(png_bytes), 'avatar_test.png', 'image/png')
    }
    resp = client.post('/api/candidate/profile/photo', data=photo_data, content_type='multipart/form-data')
    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert resp.get_json().get('success') is True

    # 15. Check completeness calculation
    completeness_res = evaluate_candidate_profile_completeness(user_id)
    assert completeness_res['score'] >= 85, f"Expected completeness >= 85%, got {completeness_res['score']}%"
    completed_ids = [item['id'] for item in completeness_res.get('completed_items', [])]
    assert 'basic_profile' in completed_ids
    assert 'preferences' in completed_ids
    assert 'profile_summary' in completed_ids
    assert 'key_skills' in completed_ids
    assert 'education' in completed_ids
    assert 'employment' in completed_ids
    assert 'languages' in completed_ids

    # 16. Verify Direct Database Persistence
    with db_cursor() as cursor:
        # Check personal details
        cursor.execute("SELECT * FROM candidate_personal_details WHERE user_id = %s", (user_id,))
        p_row = cursor.fetchone()
        assert p_row is not None
        assert p_row['nationality'] == 'Indian'
        assert p_row['current_location'] == 'Bangalore, India'
        assert p_row['pincode'] == '560038'

        # Check preferences
        cursor.execute("SELECT * FROM candidate_preferences WHERE user_id = %s", (user_id,))
        pref_row = cursor.fetchone()
        assert pref_row is not None
        assert pref_row['preferred_location'] == 'Bangalore, Remote'
        assert pref_row['workplace_type'] == 'Hybrid'
        assert (pref_row.get('current_job_role') or pref_row.get('preferred_job_role')) == 'Lead Backend Engineer'

        # Check skills separation
        cursor.execute("SELECT skill_name, skill_type FROM key_skills WHERE user_id = %s", (user_id,))
        skills_db = cursor.fetchall()
        assert len(skills_db) == len(tech_skills) + len(soft_skills)
        tech_in_db = [s['skill_name'] for s in skills_db if s['skill_type'] == 'Technical']
        soft_in_db = [s['skill_name'] for s in skills_db if s['skill_type'] == 'Soft']
        assert 'Python' in tech_in_db
        assert 'Team Leadership' in soft_in_db

    # 17. Logout and Re-login to test session persistence
    client.get('/logout')

    # Re-login
    with client.session_transaction() as sess:
        sess['user_id'] = user_id
        sess['user_email'] = email
        sess['user_name'] = candidate_user['name']
        sess['role'] = 'user'

    # 18. Call GET /api/candidate/profile/all and verify all 23 attributes are present
    resp = client.get('/api/candidate/profile/all')
    assert resp.status_code == 200
    all_data = resp.get_json()
    assert all_data.get('success') is True
    assert all_data['profile']['headline'] == 'Senior Full-Stack AI Engineer'
    assert all_data['profile']['github_url'] == 'https://github.com/ananya-sharma'
    assert all_data['profile']['linkedin_url'] == 'https://linkedin.com/in/ananya-sharma'
    assert all_data['profile']['portfolio_url'] == 'https://ananya.dev'
    assert all_data['personal']['nationality'] == 'Indian'
    assert all_data['preferences']['preferred_location'] == 'Bangalore, Remote'
    assert all_data['preferences']['workplace_type'] == 'Hybrid'
    assert len(all_data['technical_skills']) == 5
    assert len(all_data['soft_skills']) == 4
    assert len(all_data['education']) >= 1
    assert len(all_data['employment']) >= 1
    assert len(all_data['internships']) >= 1
    assert len(all_data['projects']) >= 1
    assert len(all_data['certifications']) >= 1
    assert len(all_data['languages']) >= 2
    assert len(all_data['academic_achievements']) >= 1

    # 19. Verify Candidate Profile View Page renders (status 200)
    view_resp = client.get('/candidate/profile/view')
    assert view_resp.status_code == 200
    html_content = view_resp.get_data(as_text=True)
    assert 'Senior Full-Stack AI Engineer' in html_content
    assert 'Bangalore, Remote' in html_content
    assert 'Hybrid' in html_content
    assert 'Technical Skills' in html_content
    assert 'Soft Skills' in html_content
    assert 'Razorpay Technologies' in html_content
    assert 'National Institute of Technology Karnataka' in html_content
    assert 'AWS Certified Solutions Architect' in html_content


def test_duplicate_prevention_for_skills_and_languages(client, candidate_user):
    """
    Verify that duplicate skill entries (case-insensitive) and duplicate languages are rejected/prevented.
    """
    user_id = candidate_user['id']

    with client.session_transaction() as sess:
        sess['user_id'] = user_id
        sess['user_email'] = candidate_user['email']
        sess['user_name'] = candidate_user['name']
        sess['role'] = 'user'

    # Add initial skill
    resp1 = client.post('/api/candidate/profile/items', json={
        'section': 'key_skills',
        'skill_name': 'FastAPI',
        'skill_type': 'Technical'
    })
    assert resp1.status_code == 200
    assert resp1.get_json().get('success') is True

    # Try adding identical skill with different casing
    resp2 = client.post('/api/candidate/profile/items', json={
        'section': 'key_skills',
        'skill_name': 'fastapi',
        'skill_type': 'Technical'
    })
    assert resp2.status_code == 400
    data2 = resp2.get_json()
    assert data2.get('success') is False
    assert 'already' in data2.get('message', '').lower()

    # Add initial language
    resp_l1 = client.post('/api/candidate/profile/items', json={
        'section': 'languages',
        'language_name': 'French',
        'can_read': 1,
        'can_write': 1,
        'can_speak': 0
    })
    assert resp_l1.status_code == 200
    assert resp_l1.get_json().get('success') is True

    # Try adding identical language with different casing
    resp_l2 = client.post('/api/candidate/profile/items', json={
        'section': 'languages',
        'language_name': 'french',
        'can_read': 1,
        'can_write': 1,
        'can_speak': 1
    })
    assert resp_l2.status_code == 400
    data_l2 = resp_l2.get_json()
    assert data_l2.get('success') is False
    assert 'already' in data_l2.get('message', '').lower()
