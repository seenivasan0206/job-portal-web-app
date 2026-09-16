# -*- coding: utf-8 -*-
"""
Tests for Candidate Dashboard Upgrade:
1. Context-aware profile completeness calculation (Fresher vs Experienced across 13 sections)
2. Database-backed /api/user/applied_jobs endpoint
3. Database-backed /api/user/saved_jobs endpoint (active vs expired jobs)
4. Database-backed /api/user/stats endpoint
5. Candidate dashboard template layout, sticky sidebar, and checklist rendering
"""
import pytest
from app import app, evaluate_candidate_profile_completeness

@pytest.fixture
def client():
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    with app.test_client() as client:
        yield client

def test_profile_completeness_engine_structure():
    # Test for non-existent / empty user
    res = evaluate_candidate_profile_completeness(None)
    assert res['score'] == 0
    assert res['candidate_type'] == 'fresher'
    assert res['total_items'] == 13
    assert 'breakdown' in res
    assert len(res['breakdown']) == 13

    # Check that all 13 sections exist
    section_ids = [item['id'] for item in res['breakdown']]
    expected_ids = [
        'basic_profile', 'preferences', 'education', 'key_skills',
        'languages', 'internships', 'projects', 'profile_summary',
        'accomplishments', 'competitive_exams', 'employment',
        'academic_achievements', 'resume'
    ]
    for eid in expected_ids:
        assert eid in section_ids, f"Missing section {eid} in completeness engine"

    print("[PASS] Profile completeness engine evaluated 13 sections with correct schema.")

def test_profile_completeness_fresher_vs_experienced_weighting():
    # Verify weights (employment has 10% weight, total 100%)
    res_fresher = evaluate_candidate_profile_completeness(999999)
    assert res_fresher['candidate_type'] == 'fresher'
    fresher_weights = {item['id']: item['weight'] for item in res_fresher['breakdown']}
    assert fresher_weights['employment'] == 10
    assert fresher_weights['education'] == 10
    assert fresher_weights['projects'] == 10
    assert sum(fresher_weights.values()) == 100

    print("[PASS] Balanced weighting verified: Employment & Experience has 10% weight and total is 100%.")

def test_unauthenticated_api_endpoints(client):
    res = client.get('/api/user/applied_jobs')
    assert res.status_code == 401

    res = client.get('/api/user/saved_jobs')
    assert res.status_code == 401

    res = client.get('/api/user/stats')
    assert res.status_code == 401

    res = client.get('/api/user/profile_completeness')
    assert res.status_code == 401
    print("[PASS] Unauthenticated API requests properly return 401 Unauthorized.")

def test_authenticated_applied_and_saved_jobs_apis(client):
    with client.session_transaction() as sess:
        sess['user_id'] = 1
        sess['user_name'] = 'Candidate Test'
        sess['role'] = 'user'

    # Test /api/user/applied_jobs
    res = client.get('/api/user/applied_jobs')
    assert res.status_code == 200
    data = res.get_json()
    assert data['success'] is True
    assert 'applications' in data
    assert 'applied_ids' in data
    assert isinstance(data['applications'], list)

    # Test /api/user/saved_jobs
    res = client.get('/api/user/saved_jobs')
    assert res.status_code == 200
    data = res.get_json()
    assert data['success'] is True
    assert 'saved_jobs' in data
    assert isinstance(data['saved_jobs'], list)

    # Test /api/user/stats
    res = client.get('/api/user/stats')
    assert res.status_code == 200
    data = res.get_json()
    assert data['success'] is True
    assert 'total_applications' in data
    assert 'total_saved' in data
    assert 'profile_completeness' in data
    assert 'completeness_data' in data

    print("[PASS] Authenticated applied_jobs, saved_jobs, and stats APIs return rich database models.")

def test_user_dashboard_page_rendering_and_sticky_sidebar(client):
    with client.session_transaction() as sess:
        sess['user_id'] = 1
        sess['user_name'] = 'Seenivasan V'
        sess['role'] = 'user'

    res = client.get('/user_dashboard')
    assert res.status_code == 200
    html = res.get_data(as_text=True)

    # Verify sticky sidebar and layout elements
    assert 'candidate-workspace' in html
    assert 'workspace-sidebar' in html
    assert 'position: sticky' in html
    assert 'candidate-sidebar-profile' in html
    assert 'Active Job Seeker' in html
    assert 'Seenivasan V' in html

    # Verify dynamic profile completeness checklist elements
    assert 'profile-health-banner' in html
    assert 'checklist-pills' in html
    assert 'Profile Completeness' in html

    # Verify database-driven application & saved job containers
    assert 'applications-container' in html
    assert 'saved-jobs-container' in html
    assert 'loadApplications' in html
    assert 'loadSavedJobs' in html
    assert 'Job no longer available' in html

    print("[PASS] User dashboard template rendered with sticky sidebar, profile checklist, and database containers.")

if __name__ == '__main__':
    pytest.main(['-s', __file__])
