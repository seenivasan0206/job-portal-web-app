# -*- coding: utf-8 -*-
"""
Test suite validating CSRF protection enforcement across all state-changing endpoints.
"""
import pytest
from app import app

def get_csrf(client):
    res = client.get('/api/csrf_token')
    return res.get_json()['csrf_token']

@pytest.fixture
def csrf_client():
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = True
    with app.test_client() as client:
        yield client
    app.config['WTF_CSRF_ENABLED'] = False

def test_salary_insights_csrf_protection(csrf_client):
    # Missing CSRF -> 400
    res = csrf_client.post('/api/salary/insights', json={'role': 'Software Engineer'})
    assert res.status_code == 400
    assert 'CSRF' in res.get_json()['message']

    # With CSRF -> 200
    token = get_csrf(csrf_client)
    res2 = csrf_client.post('/api/salary/insights', json={'role': 'Software Engineer'}, headers={'X-CSRFToken': token})
    assert res2.status_code == 200

def test_candidate_assessment_endpoints_csrf_protection(csrf_client):
    # 1. Start assessment without CSRF -> 400
    res1 = csrf_client.post('/api/candidate/assessments/1/start')
    assert res1.status_code == 400
    assert 'CSRF' in res1.get_json()['message']

    # 2. Save attempt without CSRF -> 400
    res2 = csrf_client.post('/api/candidate/assessments/attempt/1/save', json={'answers': {}})
    assert res2.status_code == 400
    assert 'CSRF' in res2.get_json()['message']

    # 3. Submit attempt without CSRF -> 400
    res3 = csrf_client.post('/api/candidate/assessments/attempt/1/submit', json={'answers': {}})
    assert res3.status_code == 400
    assert 'CSRF' in res3.get_json()['message']

def test_interview_endpoints_csrf_protection(csrf_client):
    # 1. Candidate respond without CSRF -> 400
    res1 = csrf_client.post('/api/candidate/interviews/1/respond', json={'action': 'accept'})
    assert res1.status_code == 400
    assert 'CSRF' in res1.get_json()['message']

    # 2. Recruiter schedule without CSRF -> 400
    res2 = csrf_client.post('/api/recruiter/interviews/schedule', json={'candidate_id': 1, 'job_id': 1})
    assert res2.status_code == 400
    assert 'CSRF' in res2.get_json()['message']

    # 3. Recruiter reschedule without CSRF -> 400
    res3 = csrf_client.post('/api/recruiter/interviews/1/reschedule', json={'scheduled_date': '2026-10-10', 'scheduled_time': '10:00'})
    assert res3.status_code == 400
    assert 'CSRF' in res3.get_json()['message']

    # 4. Recruiter cancel without CSRF -> 400
    res4 = csrf_client.post('/api/recruiter/interviews/1/cancel', json={'reason': 'Conflict'})
    assert res4.status_code == 400
    assert 'CSRF' in res4.get_json()['message']

    # 5. Recruiter complete without CSRF -> 400
    res5 = csrf_client.post('/api/recruiter/interviews/1/complete', json={'notes': 'Great job'})
    assert res5.status_code == 400
    assert 'CSRF' in res5.get_json()['message']

def test_legacy_assessment_submit_csrf_protection(csrf_client):
    # Legacy assessment submit without CSRF -> 400
    res = csrf_client.post('/api/assessments/1/submit', json={'answers': []})
    assert res.status_code == 400
    assert 'CSRF' in res.get_json()['message']
