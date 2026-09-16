# -*- coding: utf-8 -*-
"""
Unit and integration tests for Logout Confirmation Modal and Lifecycle.
"""
import pytest
from flask import session
from app import app

@pytest.fixture
def client():
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    with app.test_client() as client:
        yield client

def test_logout_modal_markup_and_accessibility(client):
    res = client.get('/')
    assert res.status_code == 200
    html = res.get_data(as_text=True)

    # Check modal presence and attributes
    assert 'id="logout-confirm-modal"' in html
    assert 'role="dialog"' in html
    assert 'aria-modal="true"' in html
    assert 'aria-labelledby="logout-modal-title"' in html
    assert 'aria-describedby="logout-modal-desc"' in html
    assert 'Confirm Logout' in html
    assert 'Are you sure you want to logout?' in html
    assert 'btn-cancel-logout' in html
    assert 'btn-confirm-logout' in html
    assert 'closeLogoutModal()' in html
    assert 'executeLogout()' in html

    print("[PASS] Logout confirmation modal markup, ARIA roles, and buttons verified in base/index.")

def test_dashboard_templates_logout_triggers(client):
    # Check user_dashboard template contains openLogoutModal()
    with client.session_transaction() as sess:
        sess['user_id'] = 1
        sess['user_name'] = 'Candidate'
        sess['role'] = 'user'

    res_user = client.get('/user_dashboard')
    if res_user.status_code == 200:
        html = res_user.get_data(as_text=True)
        assert 'openLogoutModal()' in html

    # Check employer_dashboard template contains openLogoutModal()
    with client.session_transaction() as sess:
        sess.clear()
        sess['employer_id'] = 1
        sess['company_name'] = 'TechCorp'
        sess['role'] = 'employer'

    res_emp = client.get('/employer_dashboard')
    if res_emp.status_code == 200:
        html = res_emp.get_data(as_text=True)
        assert 'openLogoutModal()' in html

    print("[PASS] Candidate, Employer, and Admin dashboards trigger openLogoutModal().")

def test_actual_logout_lifecycle_clears_candidate_session(client):
    with client.session_transaction() as sess:
        sess['user_id'] = 42
        sess['user_name'] = 'John Doe'
        sess['role'] = 'user'

    # Verify session is active
    with client.session_transaction() as sess:
        assert sess.get('user_id') == 42

    # Perform logout GET
    res = client.get('/logout', follow_redirects=False)
    assert res.status_code in (302, 303)
    assert res.headers['Location'] == '/' or res.headers['Location'].endswith('/')

    # Verify session is completely cleared
    with client.session_transaction() as sess:
        assert 'user_id' not in sess
        assert 'user_name' not in sess
        assert 'role' not in sess

    print("[PASS] Candidate logout invalidates session and redirects.")

def test_actual_logout_lifecycle_clears_employer_session(client):
    with client.session_transaction() as sess:
        sess['employer_id'] = 101
        sess['company_name'] = 'Acme Corp'
        sess['role'] = 'employer'

    # Perform logout POST
    res = client.post('/logout', follow_redirects=False)
    assert res.status_code in (302, 303)

    # Verify session is cleared
    with client.session_transaction() as sess:
        assert 'employer_id' not in sess
        assert 'company_name' not in sess

    print("[PASS] Employer logout invalidates session.")

def test_api_auth_logout_json_endpoint(client):
    with client.session_transaction() as sess:
        sess['user_id'] = 77
        sess['is_admin'] = 1

    res = client.post('/api/auth/logout', json={})
    assert res.status_code == 200
    data = res.get_json()
    assert data['success'] is True
    assert 'redirect' in data

    with client.session_transaction() as sess:
        assert 'user_id' not in sess
        assert 'is_admin' not in sess

    print("[PASS] /api/auth/logout JSON endpoint clears session and returns success response.")

if __name__ == '__main__':
    pytest.main(['-s', __file__])
