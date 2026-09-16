# -*- coding: utf-8 -*-
"""
Test suite verifying the authentication modal visual structure on index.html
and the redirection behavior to respective candidate and employer dashboards.
"""

import sys
import re
import pytest
from werkzeug.security import generate_password_hash

sys.path.insert(0, r"c:\Program Files\Ampps\www\job-portal-web-app")
from app import app, db_cursor


@pytest.fixture
def client():
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    with app.test_client() as client:
        yield client


def test_index_modals_contain_modal_body_and_tabs(client):
    """
    Verify that index.html user and employer modals (inherited from base.html) contain
    <div class="modal-body"> wrapper for correct padding and scrolling, and contain
    the auth switcher tabs and form elements.
    """
    res = client.get('/')
    assert res.status_code == 200
    html = res.get_data(as_text=True)

    # 1. User modal must contain modal-content -> modal-body wrapper
    user_modal_match = re.search(r'id="user-auth-modal"[\s\S]*?<div class="modal-content"[\s\S]*?<div class="[^"]*modal-body[^"]*"', html)
    assert user_modal_match is not None, "user-auth-modal is missing <div class=\"modal-body\"> wrapper!"

    # 2. Employer modal must contain modal-content -> modal-body wrapper
    emp_modal_match = re.search(r'id="emp-auth-modal"[\s\S]*?<div class="modal-content"[\s\S]*?<div class="[^"]*modal-body[^"]*"', html)
    assert emp_modal_match is not None, "emp-auth-modal is missing <div class=\"modal-body\"> wrapper!"

    # 3. Both modals must have auth switcher tabs
    assert 'id="tab-btn-signin"' in html, "Missing candidate sign in tab button!"
    assert 'id="tab-btn-signup"' in html, "Missing candidate sign up tab button!"
    assert 'id="emp-tab-btn-signin"' in html, "Missing employer sign in tab button!"
    assert 'id="emp-tab-btn-register"' in html, "Missing employer register tab button!"

    # 4. Check unified form IDs inside user modal
    assert 'id="cand-signup-form"' in html
    assert 'id="cand-login-form"' in html
    assert 'id="cand-forgot-form"' in html

    # 5. Check unified form IDs inside employer modal
    assert 'id="emp-signup-form"' in html
    assert 'id="emp-login-form"' in html


def test_index_navbar_and_drawer_buttons(client):
    """
    Verify that index.html provides clear access to Employer Login, Sign In, and Sign Up.
    """
    res = client.get('/')
    html = res.get_data(as_text=True)

    # Navbar
    assert 'id="base-nav-btn-employer"' in html or 'id="nav-btn-employer-login"' in html
    assert 'id="base-nav-btn-signin"' in html or 'id="nav-btn-signin"' in html
    assert 'id="base-nav-btn-signup"' in html or 'id="nav-btn-signup"' in html

    assert "openEmpModal('login')" in html
    assert "openUserModal('login')" in html
    assert "openUserModal('signup')" in html


def test_candidate_login_and_dashboard_render():
    """
    Verify candidate login API returns redirect to /user_dashboard and subsequent
    session access renders the candidate dashboard.
    """
    # Setup candidate credentials
    hashed = generate_password_hash('Password123')
    with db_cursor() as cur:
        cur.execute("UPDATE user SET password = %s WHERE email = 'candidate1@test.com'", (hashed,))
        cur.execute("DELETE FROM login_attempts WHERE email = 'candidate1@test.com'")

    with app.test_client() as test_client:
        # Get CSRF token from homepage
        idx_res = test_client.get('/')
        csrf_match = re.search(r'<meta name="csrf-token" content="([^"]+)"', idx_res.get_data(as_text=True))
        assert csrf_match is not None
        csrf_token = csrf_match.group(1)

        # Post candidate login
        headers = {'Content-Type': 'application/json', 'X-CSRFToken': csrf_token}
        login_res = test_client.post('/api/user/login', headers=headers, json={
            'email': 'candidate1@test.com',
            'password': 'Password123'
        })
        assert login_res.status_code == 200
        data = login_res.get_json()
        assert data['success'] is True
        assert data['redirect'] == '/user_dashboard'

        # Access candidate dashboard
        dash_res = test_client.get('/user_dashboard')
        assert dash_res.status_code == 200
        dash_html = dash_res.get_data(as_text=True)
        assert 'Candidate' in dash_html or 'Dashboard' in dash_html


def test_employer_login_and_dashboard_render():
    """
    Verify employer login API returns redirect to /employer_dashboard and subsequent
    session access renders the employer dashboard.
    """
    # Setup employer credentials
    hashed = generate_password_hash('Password123')
    with db_cursor() as cur:
        cur.execute("UPDATE employee SET password = %s WHERE email = 'secret@test.com'", (hashed,))
        cur.execute("DELETE FROM login_attempts WHERE email = 'secret@test.com'")

    with app.test_client() as test_client:
        # Get CSRF token from homepage
        idx_res = test_client.get('/')
        csrf_match = re.search(r'<meta name="csrf-token" content="([^"]+)"', idx_res.get_data(as_text=True))
        assert csrf_match is not None
        csrf_token = csrf_match.group(1)

        # Post employer login
        headers = {'Content-Type': 'application/json', 'X-CSRFToken': csrf_token}
        login_res = test_client.post('/api/employer/login', headers=headers, json={
            'email': 'secret@test.com',
            'password': 'Password123'
        })
        assert login_res.status_code == 200
        data = login_res.get_json()
        assert data['success'] is True
        assert data['redirect'] == '/employer_dashboard'

        # Access employer dashboard
        dash_res = test_client.get('/employer_dashboard')
        assert dash_res.status_code == 200
        dash_html = dash_res.get_data(as_text=True)
        assert 'Employer' in dash_html


def test_submit_button_targeting_in_scripts(client):
    """
    Verify that in _auth_modal.html (the unified modal auth script), the auth submission handlers target
    the submit button rather than wiping out the entire <form> innerHTML.
    """
    with open(r"c:\Program Files\Ampps\www\job-portal-web-app\templates\_auth_modal.html", "r", encoding="utf-8") as f:
        base_html = f.read()

    # Neither should use btn = evt.currentTarget where btn.innerHTML wipes the form
    assert "submitBtn" in base_html
    assert "sessionStorage.removeItem('pending_job_action')" in base_html


def test_close_button_no_hover_transform_animations():
    """
    Verify that the modal close button ('X') has NO hover animations
    (no scale, no rotate).
    """
    with open(r"c:\Program Files\Ampps\www\job-portal-web-app\static\css\app.css", "r", encoding="utf-8") as f:
        css = f.read()

    # Find .modal-close:hover block
    hover_match = re.search(r'\.modal-close:hover\s*\{([^}]+)\}', css)
    assert hover_match is not None, "Missing .modal-close:hover in app.css!"
    hover_rules = hover_match.group(1)
    assert 'transform' not in hover_rules, f".modal-close:hover should have no transform animation, found: {hover_rules}"

    # Find .modal-close:hover svg block (should not exist or have no rotate)
    hover_svg_match = re.search(r'\.modal-close:hover\s+svg\s*\{([^}]+)\}', css)
    assert hover_svg_match is None, ".modal-close:hover svg should have no rotate animation!"


def test_compact_auth_modal_structure_and_zero_scroll():
    """
    Verify that auth modals in _auth_modal.html (inherited by index.html and all pages via base.html) use compact styling
    and hide overflow-y on sign in to avoid scrollbars.
    """
    with open(r"c:\Program Files\Ampps\www\job-portal-web-app\templates\_auth_modal.html", "r", encoding="utf-8") as f:
        base_html = f.read()

    assert "auth-modal-body" in base_html, "Missing auth-modal-body in _auth_modal.html"
    assert "auth-tabs-compact" in base_html, "Missing auth-tabs-compact in _auth_modal.html"
    assert "auth-compact-title" in base_html, "Missing auth-compact-title in _auth_modal.html"
    assert "auth-input-compact" in base_html, "Missing auth-input-compact in _auth_modal.html"
    assert "auth-btn-compact" in base_html, "Missing auth-btn-compact in _auth_modal.html"
    assert "overflow-y:hidden" in base_html or "overflow-y: hidden" in base_html, "Missing overflow-y:hidden in _auth_modal.html"


def test_compact_jobs_filter_sidebar():
    """
    Verify that jobs.html filter sidebar uses compact styling with btn-apply-filters.
    """
    with open(r"c:\Program Files\Ampps\www\job-portal-web-app\templates\jobs.html", "r", encoding="utf-8") as f:
        jobs_html = f.read()

    assert "btn-apply-filters" in jobs_html, "Missing btn-apply-filters class in jobs.html"
    assert "padding: 14px 16px" in jobs_html, "filter-sidebar should have compact 14px 16px padding"
    assert "height: 30px !important" in jobs_html, "form-control/select should have compact 30px height"


def test_navbar_and_modal_buttons_have_no_javascript_void(client):
    """
    Verify that neither navbar auth buttons nor modal switch links use href="javascript:void(0)".
    They must be semantic button elements or have no javascript:void(0) so hovering
    never displays 'javascript:void(0)' in the bottom-left corner of the browser.
    """
    with open(r"c:\Program Files\Ampps\www\job-portal-web-app\templates\index.html", "r", encoding="utf-8") as f:
        idx_html = f.read()

    with open(r"c:\Program Files\Ampps\www\job-portal-web-app\templates\base.html", "r", encoding="utf-8") as f:
        base_html = f.read()

    res = client.get('/')
    rendered_index = res.get_data(as_text=True)

    # 1. Rendered homepage links must have real href destinations
    assert re.search(r'<a\s+[^>]*href="/employer_dashboard"', rendered_index) is not None
    assert re.search(r'<a\s+[^>]*href="/login"', rendered_index) is not None
    assert re.search(r'<a\s+[^>]*href="/signup"', rendered_index) is not None

    # 2. Navbar links must have real href destinations in base.html
    assert re.search(r'<a\s+[^>]*href="/employer_dashboard"[^>]*id="base-nav-btn-employer"', base_html) is not None
    assert re.search(r'<a\s+[^>]*href="/login"[^>]*id="base-nav-btn-signin"', base_html) is not None
    assert re.search(r'<a\s+[^>]*href="/signup"[^>]*id="base-nav-btn-signup"', base_html) is not None

    # 3. Neither index.html, base.html, nor rendered output should contain javascript:void anywhere
    assert 'javascript:void' not in idx_html, "Found javascript:void in index.html"
    assert 'javascript:void' not in base_html, "Found javascript:void in base.html"
    assert 'javascript:void' not in rendered_index, "Found javascript:void in rendered index"


def test_dashboard_unauthenticated_redirects_and_login_routes(client):
    """
    Verify that accessing dashboards when unauthenticated redirects to / with auth query params
    to trigger the login modal, and dedicated login routes redirect seamlessly.
    """
    # 1. Unauthenticated dashboards redirect with auth param
    res_user = client.get('/user_dashboard')
    assert res_user.status_code == 302
    assert res_user.headers['Location'] == '/?auth=login'

    res_emp = client.get('/employer_dashboard')
    assert res_emp.status_code == 302
    assert res_emp.headers['Location'] == '/?auth=emp_login'

    # 2. Direct login / signin routes redirect to /?auth=login
    res_login = client.get('/login')
    assert res_login.status_code == 302
    assert res_login.headers['Location'] == '/?auth=login'

    res_signin = client.get('/signin')
    assert res_signin.status_code == 302
    assert res_signin.headers['Location'] == '/?auth=login'

    res_emp_login = client.get('/employer_login')
    assert res_emp_login.status_code == 302
    assert res_emp_login.headers['Location'] == '/?auth=emp_login'

    res_signup = client.get('/signup')
    assert res_signup.status_code == 302
    assert res_signup.headers['Location'] == '/?auth=signup'

    # 3. Authenticated redirects directly to dashboard
    with client.session_transaction() as sess:
        sess['user_id'] = 1
        sess['user_name'] = 'Candidate'
        sess['role'] = 'candidate'

    res_auth_login = client.get('/login')
    assert res_auth_login.status_code == 302
    assert res_auth_login.headers['Location'] == '/user_dashboard'


