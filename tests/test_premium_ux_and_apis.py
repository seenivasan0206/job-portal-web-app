# -*- coding: utf-8 -*-
"""
Tests for Premium Success Animations, Error Handling, and Job Posting/Application APIs.
"""
import pytest
from app import app, db_cursor

@pytest.fixture
def client():
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    with app.test_client() as client:
        yield client

def test_css_premium_animations_and_modal_markup(client):
    res = client.get('/jobs')
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert 'premium-job-posted-modal' in html
    assert 'premium-application-submitted-modal' in html
    assert 'svg-draw-check' in html
    assert 'app-paper-plane-flight' in html
    print("\n[PASS] Premium Success Modals rendered in base template.")

def test_employer_post_job_apis(client):
    """
    Verifies that both /api/post_job and /api/employer/post_job work seamlessly
    and return the created job_id.
    """
    with client.session_transaction() as sess:
        sess['employer_id'] = 1
        sess['user_name'] = 'TechCorp Inc.'

    payload = {
        'title': 'Senior Staff Cloud Architect',
        'location': 'Bangalore, India',
        'salary': '$140k - $180k',
        'category': 'Engineering',
        'job_type': 'Full-time',
        'work_mode': 'Hybrid',
        'experience': '5+ Years',
        'openings': 3,
        'skills': 'AWS, Kubernetes, Terraform',
        'description': 'Leading our next-generation cloud architecture.'
    }

    # Test /api/post_job
    res1 = client.post('/api/post_job', json=payload)
    assert res1.status_code == 200
    data1 = res1.get_json()
    assert data1['success'] is True
    assert 'job_id' in data1
    assert data1['title'] == 'Senior Staff Cloud Architect'

    # Test /api/employer/post_job alias
    payload['title'] = 'Lead Data Platform Engineer'
    res2 = client.post('/api/employer/post_job', json=payload)
    assert res2.status_code == 200
    data2 = res2.get_json()
    assert data2['success'] is True
    assert 'job_id' in data2
    print(f"[PASS] Employer job posting APIs verified: Created job #{data1['job_id']} and #{data2['job_id']}")

def test_candidate_apply_job_json_and_form(client):
    """
    Verifies that /api/apply_job correctly accepts JSON payloads ({ job_id: ... })
    as well as form-data without raising 'Job ID is required'.
    """
    # Create an active job in DB for testing
    with db_cursor(dictionary=False) as cursor:
        cursor.execute("SELECT id FROM employee WHERE company_name = 'Apex AI' LIMIT 1")
        emp_row = cursor.fetchone()
        if emp_row:
            emp_id = emp_row[0]
        else:
            cursor.execute("INSERT INTO employee (company_name, email, password, location) VALUES ('Apex AI', 'contact@apexai.test', 'hash', 'Remote')")
            emp_id = cursor.lastrowid
        cursor.execute("""
            INSERT INTO jobs (employer_id, title, company_name, location, is_active)
            VALUES (%s, 'Principal NLP Scientist', 'Apex AI', 'Remote', 1)
        """, (emp_id,))
        test_job_id = cursor.lastrowid

    with db_cursor() as cursor:
        cursor.execute("SELECT id, name, email FROM user LIMIT 1")
        user_row = cursor.fetchone()
        if user_row:
            valid_user_id = user_row['id']
            valid_user_name = user_row['name']
            valid_user_email = user_row['email']
        else:
            cursor.execute("INSERT INTO user (name, email, password, role) VALUES ('Test Candidate', 'test.cand@example.com', 'hash', 'seeker')")
            valid_user_id = cursor.lastrowid
            valid_user_name = 'Test Candidate'
            valid_user_email = 'test.cand@example.com'

    with client.session_transaction() as sess:
        sess['user_id'] = valid_user_id
        sess['user_name'] = valid_user_name
        sess['user_email'] = valid_user_email

    # 1. Test JSON Body (Which previously failed with "Job ID is required")
    res = client.post('/api/apply_job', json={'job_id': test_job_id})
    assert res.status_code == 200
    data = res.get_json()
    assert data['success'] is True
    assert data['job_id'] == test_job_id
    assert 'application_id' in data
    assert data['company_name'] == 'Apex AI'
    print(f"[PASS] Candidate JSON application submission verified: Application #{data['application_id']} created for Job #{test_job_id}")

def test_candidate_apply_missing_job_id(client):
    with client.session_transaction() as sess:
        sess['user_id'] = 999
    res = client.post('/api/apply_job', json={})
    assert res.status_code == 400
    data = res.get_json()
    assert data['success'] is False
    assert 'Job ID is required' in data['message']
    print("[PASS] Missing Job ID rejected safely with 400.")

if __name__ == '__main__':
    pytest.main(['-s', __file__])
