import pytest
import re
from app import app, db_cursor
from werkzeug.security import generate_password_hash


def test_index_and_base_html_div_tag_balance():
    """Ensure no orphan or missing closing div tags exist in index.html and base.html."""
    with open('templates/index.html', 'r', encoding='utf-8') as f:
        idx_content = f.read()
    idx_opens = len(re.findall(r'<div\b', idx_content))
    idx_closes = len(re.findall(r'</div>', idx_content))
    assert idx_opens == idx_closes, f"index.html has mismatched div tags: {idx_opens} opens vs {idx_closes} closes"

    with open('templates/base.html', 'r', encoding='utf-8') as f:
        base_content = f.read()
    base_opens = len(re.findall(r'<div\b', base_content))
    base_closes = len(re.findall(r'</div>', base_content))
    assert base_opens == base_closes, f"base.html has mismatched div tags: {base_opens} opens vs {base_closes} closes"


def test_main_js_and_templates_show_emp_form_support_forgot(client):
    """Verify that showEmpForm across main.js, base.html (via _auth_modal.html), and rendered index.html supports forgot password."""
    for filepath in ['static/js/main.js', 'templates/_auth_modal.html']:
        with open(filepath, 'r', encoding='utf-8') as f:
            code = f.read()
        assert 'emp-form-forgot' in code, f"Missing emp-form-forgot handling in {filepath}"
        assert 'emp-form-' in code, f"Missing emp-form- selector in {filepath}"

    res = client.get('/')
    assert res.status_code == 200
    assert 'emp-form-forgot' in res.get_data(as_text=True)


def test_signup_redirect_forwards_tabs(client):
    """Test that visiting /signup and /register with tab params redirects to appropriate auth query."""
    # /signup?tab=login -> /?auth=login
    r = client.get('/signup?tab=login')
    assert r.status_code == 302
    assert 'auth=login' in r.location

    # /signup?tab=employer -> /?auth=emp_register
    r2 = client.get('/signup?tab=employer')
    assert r2.status_code == 302
    assert 'auth=emp_register' in r2.location

    # /signup?tab=emp_login -> /?auth=emp_login
    r3 = client.get('/signup?tab=emp_login')
    assert r3.status_code == 302
    assert 'auth=emp_login' in r3.location


def test_forgot_password_page_route(client):
    """Verify /forgot_password and /forgot-password pages render properly."""
    r1 = client.get('/forgot_password')
    assert r1.status_code == 200
    assert 'Forgot Password' in r1.get_data(as_text=True)

    r2 = client.get('/forgot-password')
    assert r2.status_code == 200
    assert 'Forgot Password' in r2.get_data(as_text=True)


def test_signup_page_template_alert_containers():
    """Verify signup.html includes inline alert containers for all 3 tabs."""
    with open('templates/signup.html', 'r', encoding='utf-8') as f:
        content = f.read()
    assert 'id="pane-cand-alert"' in content
    assert 'id="pane-emp-alert"' in content
    assert 'id="pane-login-alert"' in content
