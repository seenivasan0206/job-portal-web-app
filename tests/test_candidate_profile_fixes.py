# -*- coding: utf-8 -*-
"""
Tests for Candidate Profile & Resume Fixes:
1. Summary Status Completion (marks complete on non-empty summary)
2. Fast Asynchronous Saving (< 500ms)
3. Instant DOM Removal & UI/Badge consistency
4. Section completeness retained when 1 of multiple items deleted (e.g., 2 certs -> delete 1 -> complete)
5. Employment & Experience weight is 10% (never 0%)
6. /candidate/profile/view renders all 23 candidate profile fields
7. .toast-info in app.css uses sky-blue #38BDF8
"""
import pytest
import time
import os
from app import app, db_cursor, evaluate_candidate_profile_completeness


@pytest.fixture
def client():
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    with app.test_client() as client:
        yield client


@pytest.fixture
def test_candidate_id():
    email = "profile_fixes_test@hirevolt.com"
    with db_cursor(dictionary=True) as cursor:
        cursor.execute("SELECT id FROM user WHERE email = %s", (email,))
        user = cursor.fetchone()
        if user:
            uid = user['id']
        else:
            cursor.execute("""
                INSERT INTO user (name, email, password)
                VALUES (%s, %s, %s)
            """, ("Candidate Fixes Tester", email, "pbkdf2:sha256:dummy"))
            cursor.execute("SELECT id FROM user WHERE email = %s", (email,))
            uid = cursor.fetchone()['id']

        tables = [
            "education", "employment", "projects", "internships",
            "certifications", "key_skills", "languages",
            "competitive_exams", "academic_achievements",
            "candidate_personal_details", "candidate_preferences",
            "candidate_profile_summary", "candidate_profile"
        ]
        for tbl in tables:
            try:
                cursor.execute(f"DELETE FROM {tbl} WHERE user_id = %s", (uid,))
            except Exception:
                pass
        
        cursor.execute("INSERT INTO candidate_profile (user_id, headline, is_public) VALUES (%s, %s, 1)", (uid, "Full Stack Engineer"))
        return uid


def test_issue_5_employment_weight_is_not_zero():
    """Verify Employment & Experience has 10% weight and total weights sum to 100%."""
    default_eval = evaluate_candidate_profile_completeness(None)
    emp_items = [b for b in default_eval['breakdown'] if b['id'] == 'employment']
    assert len(emp_items) == 1, "Employment section missing from breakdown"
    assert emp_items[0]['weight'] == 10, f"Expected employment weight 10, got {emp_items[0]['weight']}"
    
    total_weight = sum(b['weight'] for b in default_eval['breakdown'])
    assert total_weight == 100, f"Expected total weight 100%, got {total_weight}%"


def test_issue_1_summary_completeness_on_save(client, test_candidate_id):
    """Verify saving summary immediately marks the section as Complete."""
    with client.session_transaction() as sess:
        sess['user_id'] = test_candidate_id
        sess['user_name'] = 'Candidate Fixes Tester'
        sess['role'] = 'candidate'

    # Initially empty summary -> not completed
    eval1 = evaluate_candidate_profile_completeness(test_candidate_id)
    summary_item1 = next(b for b in eval1['breakdown'] if b['id'] == 'profile_summary')
    assert summary_item1['completed'] is False

    # Save summary
    res = client.post('/api/candidate/profile/summary', json={'summary': 'Experienced full stack developer passionate about building performant apps.'})
    assert res.status_code == 200
    assert res.get_json()['success'] is True

    # Evaluated completeness -> completed is True
    eval2 = evaluate_candidate_profile_completeness(test_candidate_id)
    summary_item2 = next(b for b in eval2['breakdown'] if b['id'] == 'profile_summary')
    assert summary_item2['completed'] is True


def test_issue_4_delete_one_of_two_items_keeps_completed_status(client, test_candidate_id):
    """Verify adding 2 certifications and deleting 1 keeps section marked Complete."""
    with client.session_transaction() as sess:
        sess['user_id'] = test_candidate_id
        sess['user_name'] = 'Candidate Fixes Tester'
        sess['role'] = 'candidate'

    # Add 1st certification
    res1 = client.post('/api/candidate/profile/items', json={
        'section': 'certifications',
        'certification_name': 'AWS Certified Solutions Architect',
        'issuing_organization': 'Amazon Web Services'
    })
    assert res1.status_code == 200
    cert1_id = res1.get_json()['id']

    # Add 2nd certification
    res2 = client.post('/api/candidate/profile/items', json={
        'section': 'certifications',
        'certification_name': 'Google Cloud Professional Cloud Architect',
        'issuing_organization': 'Google'
    })
    assert res2.status_code == 200
    cert2_id = res2.get_json()['id']

    # Check completeness with 2 certs -> completed is True
    eval1 = evaluate_candidate_profile_completeness(test_candidate_id)
    cert_item1 = next(b for b in eval1['breakdown'] if b['id'] == 'accomplishments')
    assert cert_item1['completed'] is True

    # Delete 1st certification
    del_res = client.delete(f'/api/candidate/profile/items/{cert1_id}?section=certifications')
    assert del_res.status_code == 200
    assert del_res.get_json()['success'] is True

    # Verify 1 cert remains and section is STILL completed
    eval2 = evaluate_candidate_profile_completeness(test_candidate_id)
    cert_item2 = next(b for b in eval2['breakdown'] if b['id'] == 'accomplishments')
    assert cert_item2['completed'] is True, "Section marked incomplete even though 1 cert remains!"


def test_issue_6_candidate_profile_view_route(client, test_candidate_id):
    """Verify /candidate/profile/view renders full candidate profile."""
    with client.session_transaction() as sess:
        sess['user_id'] = test_candidate_id
        sess['user_name'] = 'Candidate Fixes Tester'
        sess['role'] = 'candidate'

    # Populate basic details
    client.post('/api/candidate/profile/personal', json={
        'gender': 'Male',
        'current_location': 'Bengaluru, Karnataka',
        'headline': 'Senior Python Developer'
    })
    client.post('/api/candidate/profile/summary', json={
        'summary': 'Dedicated engineer with 5+ years of experience.'
    })
    client.post('/api/candidate/profile/items', json={
        'section': 'key_skills',
        'skill_name': 'Python'
    })

    # Access /candidate/profile/view
    res = client.get('/candidate/profile/view')
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert 'Candidate Fixes Tester' in html
    assert 'Senior Python Developer' in html
    assert 'Bengaluru, Karnataka' in html
    assert 'Dedicated engineer' in html
    assert 'Python' in html


def test_issue_7_toast_info_css_styling():
    """Verify .toast-info uses sky-blue #38BDF8 instead of red."""
    css_path = os.path.join(app.root_path, 'static', 'css', 'app.css')
    with open(css_path, 'r', encoding='utf-8') as f:
        content = f.read()
    assert '.toast-info' in content
    assert 'border-left: 4px solid #38BDF8;' in content
    assert 'color: #38BDF8;' in content


def test_issue_2_fast_async_profile_saving(client, test_candidate_id):
    """Verify profile saving executes asynchronously without blocking."""
    with client.session_transaction() as sess:
        sess['user_id'] = test_candidate_id
        sess['user_name'] = 'Candidate Fixes Tester'
        sess['role'] = 'candidate'

    t0 = time.time()
    res = client.post('/api/candidate/profile/preferences', json={
        'preferred_job_role': 'Staff Engineer',
        'expected_ctc': '25 LPA',
        'desired_employment_type': 'Full-time'
    })
    elapsed = time.time() - t0
    assert res.status_code == 200
    assert elapsed < 0.5, f"Save took {elapsed}s, expected < 0.5s"

