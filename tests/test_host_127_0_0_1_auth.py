# -*- coding: utf-8 -*-
"""
Test suite verifying Candidate and Employer Authentication flows on http://127.0.0.1:5000.
Ensures:
1. Candidate login on http://127.0.0.1:5000 creates valid session and redirects to /user_dashboard.
2. Employer login on http://127.0.0.1:5000 creates valid session and redirects to /employer_dashboard.
3. No unexpected redirects from 127.0.0.1 to localhost or vice versa.
4. Session cookies are correctly handled and recognized across requests to http://127.0.0.1:5000.
5. Logout invalidates session correctly on 127.0.0.1:5000.
"""

import sys
import pytest
from werkzeug.security import generate_password_hash

sys.path.insert(0, r"c:\Program Files\Ampps\www\job-portal-web-app")
from app import app, db_cursor


@pytest.fixture
def host_client():
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    with app.test_client() as client:
        yield client


def test_candidate_auth_and_dashboard_on_127_0_0_1(host_client):
    email = "test_cand_127@example.com"
    password = "TestPassword123!"

    with db_cursor() as cur:
        cur.execute("DELETE FROM user WHERE email = %s", (email,))
        cur.execute(
            "INSERT INTO user (name, email, mobile, password, is_verified) VALUES (%s, %s, %s, %s, 1)",
            ("127 Candidate", email, "9876543210", generate_password_hash(password))
        )

    try:
        # 1. Login request to http://127.0.0.1:5000/api/user/login
        res = host_client.post('/api/user/login', json={'email': email, 'password': password}, headers={'Host': '127.0.0.1:5000', 'Origin': 'http://127.0.0.1:5000'})
        assert res.status_code == 200
        data = res.get_json()
        assert data['success'] is True
        assert data['redirect'] == '/user_dashboard'

        # 2. Access Candidate Dashboard
        dash_res = host_client.get('/user_dashboard', headers={'Host': '127.0.0.1:5000'})
        assert dash_res.status_code == 200
        assert "localhost" not in dash_res.headers.get('Location', '')
        html = dash_res.get_data(as_text=True)
        assert "Dashboard" in html or "Candidate" in html or "Jobs" in html

        # 3. Role boundary on 127.0.0.1: Candidate cannot access Employer Dashboard
        emp_dash_res = host_client.get('/employer_dashboard', headers={'Host': '127.0.0.1:5000'})
        assert emp_dash_res.status_code in [302, 403]
        if emp_dash_res.status_code == 302:
            assert "localhost" not in emp_dash_res.headers.get('Location', '')

        # 4. Logout on 127.0.0.1
        logout_res = host_client.get('/logout', headers={'Host': '127.0.0.1:5000'})
        assert logout_res.status_code in [200, 302]

        # 5. Dashboard protected after logout
        post_dash = host_client.get('/user_dashboard', headers={'Host': '127.0.0.1:5000'})
        assert post_dash.status_code == 302

    finally:
        with db_cursor() as cur:
            cur.execute("DELETE FROM user WHERE email = %s", (email,))


def test_employer_auth_and_dashboard_on_127_0_0_1(host_client):
    email = "test_emp_127@example.com"
    password = "TestPassword123!"

    with db_cursor() as cur:
        cur.execute("DELETE FROM employee WHERE email = %s", (email,))
        cur.execute(
            "INSERT INTO employee (company_name, email, mobile, password, is_verified) VALUES (%s, %s, %s, %s, 1)",
            ("127 Employer Corp", email, "9876543211", generate_password_hash(password))
        )

    try:
        # 1. Login request to http://127.0.0.1:5000/api/employer/login
        res = host_client.post('/api/employer/login', json={'email': email, 'password': password}, headers={'Host': '127.0.0.1:5000', 'Origin': 'http://127.0.0.1:5000'})
        assert res.status_code == 200
        data = res.get_json()
        assert data['success'] is True
        assert data['redirect'] == '/employer_dashboard'

        # 2. Access Employer Dashboard
        dash_res = host_client.get('/employer_dashboard', headers={'Host': '127.0.0.1:5000'})
        assert dash_res.status_code == 200
        assert "localhost" not in dash_res.headers.get('Location', '')
        html = dash_res.get_data(as_text=True)
        assert "Dashboard" in html or "Employer" in html or "Post Job" in html

        # 3. Role boundary on 127.0.0.1: Employer cannot access Candidate Dashboard
        cand_dash_res = host_client.get('/user_dashboard', headers={'Host': '127.0.0.1:5000'})
        assert cand_dash_res.status_code in [302, 403]

        # 4. Logout on 127.0.0.1
        logout_res = host_client.get('/logout', headers={'Host': '127.0.0.1:5000'})
        assert logout_res.status_code in [200, 302]

        # 5. Employer Dashboard protected after logout
        post_dash = host_client.get('/employer_dashboard', headers={'Host': '127.0.0.1:5000'})
        assert post_dash.status_code == 302

    finally:
        with db_cursor() as cur:
            cur.execute("DELETE FROM employee WHERE email = %s", (email,))


def test_host_consistency_and_no_localhost_redirect(host_client):
    """
    Verify that relative redirects on 127.0.0.1 do not leak 'localhost' in Location headers.
    """
    routes_to_test = [
        '/user_dashboard',
        '/employer_dashboard',
        '/login',
        '/signup',
        '/signin',
        '/logout',
        '/jobs',
        '/companies'
    ]

    for route in routes_to_test:
        res = host_client.get(route, headers={'Host': '127.0.0.1:5000'})
        if res.status_code in [301, 302]:
            loc = res.headers.get('Location', '')
            assert "localhost" not in loc, f"Route {route} redirected to localhost: {loc}"
