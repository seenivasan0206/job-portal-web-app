# -*- coding: utf-8 -*-
"""
Test suite verifying that all navigation links across desktop navbar and mobile drawer
have genuine semantic <a href="..."> tags with real navigable destinations.
Ensures Chrome bottom-left hover status bar displays the exact expected URLs:
- Find Jobs: http://127.0.0.1:5000/jobs
- Companies: http://127.0.0.1:5000/companies
- Employee: http://127.0.0.1:5000/employer_dashboard
- Sign In: http://127.0.0.1:5000/login
- Sign Up: http://127.0.0.1:5000/signup
"""

import sys
import re
import pytest

sys.path.insert(0, r"c:\Program Files\Ampps\www\job-portal-web-app")
from app import app

@pytest.fixture
def client():
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    with app.test_client() as client:
        yield client


def test_guest_navbar_href_destinations_on_index_and_base(client):
    """
    Verify guest navbar and drawer on index.html and base.html contain real href destinations.
    """
    res = client.get('/')
    assert res.status_code == 200
    html = res.get_data(as_text=True)

    # 1. Desktop Navbar Links
    assert re.search(r'<a[^>]*href="/jobs"[^>]*>[\s\S]*?Find Jobs', html) is not None
    assert re.search(r'<a[^>]*href="/companies"[^>]*>[\s\S]*?Companies', html) is not None
    assert re.search(r'<a[^>]*href="/employer_dashboard"[^>]*id="(?:base-)?nav-btn-(?:employer|employer-login)"[^>]*>[\s\S]*?Employee', html) is not None
    assert re.search(r'<a[^>]*href="/login"[^>]*id="(?:base-)?nav-btn-signin"[^>]*>[\s\S]*?Sign In', html) is not None
    assert re.search(r'<a[^>]*href="/signup"[^>]*id="(?:base-)?nav-btn-signup"[^>]*>[\s\S]*?Sign Up', html) is not None

    # 2. Mobile Drawer Links
    assert re.search(r'<nav class="mobile-drawer-links"[\s\S]*?<a[^>]*href="/jobs"', html) is not None
    assert re.search(r'<nav class="mobile-drawer-links"[\s\S]*?<a[^>]*href="/companies"', html) is not None
    assert re.search(r'<nav class="mobile-drawer-links"[\s\S]*?<a[^>]*href="/employer_dashboard"[\s\S]*?Employee', html) is not None
    assert re.search(r'<nav class="mobile-drawer-links"[\s\S]*?<a[^>]*href="/login"[\s\S]*?Sign In', html) is not None
    assert re.search(r'<nav class="mobile-drawer-links"[\s\S]*?<a[^>]*href="/signup"[\s\S]*?Sign Up', html) is not None


def test_guest_navbar_href_destinations_on_inner_pages(client):
    """
    Verify base.html navbar on inner pages (/jobs, /companies, /services, /salary_insights).
    """
    pages = ['/jobs', '/companies', '/services', '/salary_insights']
    for page in pages:
        res = client.get(page)
        assert res.status_code == 200, f"Page {page} returned status {res.status_code}"
        html = res.get_data(as_text=True)

        assert re.search(r'<a[^>]*href="/employer_dashboard"[^>]*id="base-nav-btn-employer"', html) is not None
        assert re.search(r'<a[^>]*href="/login"[^>]*id="base-nav-btn-signin"', html) is not None
        assert re.search(r'<a[^>]*href="/signup"[^>]*id="base-nav-btn-signup"', html) is not None


def test_authenticated_candidate_navbar(client):
    """
    Verify candidate navbar shows Candidate Dashboard & Logout links.
    """
    with client.session_transaction() as sess:
        sess['user_id'] = 42
        sess['user_name'] = 'Jane Candidate'
        sess['role'] = 'candidate'

    res = client.get('/')
    assert res.status_code == 200
    html = res.get_data(as_text=True)

    assert '<a href="/user_dashboard"' in html
    assert '<a href="/logout"' in html
    assert 'Candidate Dashboard' in html


def test_authenticated_employer_navbar(client):
    """
    Verify employer navbar shows Employer Portal & Logout links.
    """
    with client.session_transaction() as sess:
        sess['employer_id'] = 99
        sess['user_name'] = 'Acme Corp'
        sess['role'] = 'employer'

    res = client.get('/')
    assert res.status_code == 200
    html = res.get_data(as_text=True)

    assert '<a href="/employer_dashboard"' in html
    assert '<a href="/logout"' in html
    assert 'Employer Portal' in html
