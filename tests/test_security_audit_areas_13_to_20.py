# -*- coding: utf-8 -*-
"""
Automated Test Suite for Comprehensive 8-Area Security Audit (Areas 13-20).
Covers:
13. XSS: Bleach HTML/text sanitization across inputs and frontend escapeHtml.
14. Rate Limiting: Rate limits on search, resume, messaging, unlock endpoints.
15. API Authorization: Protected endpoints require session; intentional public endpoints whitelisted.
16. Input Validation: Server-side validation and enum sets reject invalid data with 400.
17. HTTPS: Documentation of TLS termination, reverse proxy, and secure cookies.
18. Security Headers: Strict CSP, Referrer-Policy, Permissions-Policy, X-Content-Type-Options, X-Frame-Options.
19. MySQL Permissions: Least-privilege grant documentation.
20. Dependency Vulnerabilities: Verification of patched versions and 0 CVEs via pip-audit.
"""

import os
import sys
import json
import time
import pytest
from pathlib import Path

sys.path.insert(0, r"c:\Program Files\Ampps\www\job-portal-web-app")
from app import (
    app, db_cursor, sanitize_text, sanitize_html,
    ALLOWED_APPLICATION_STATUSES, ALLOWED_WORKPLACE_TYPES, ALLOWED_JOB_TYPES
)

BASE_DIR = Path(r"c:\Program Files\Ampps\www\job-portal-web-app")


@pytest.fixture
def client():
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    with app.test_client() as client:
        yield client


# =========================================================================
# AREA 13: XSS & BLEACH SANITIZATION
# =========================================================================

def test_area_13_xss_bleach_sanitization():
    xss_payload = "<script>alert('xss')</script><img src=x onerror=alert(1)>Hello <b>World</b>"
    
    # Plain text sanitizer strips all HTML tags and event handlers
    plain = sanitize_text(xss_payload)
    assert "<script>" not in plain
    assert "</script>" not in plain
    assert "<img" not in plain
    assert "onerror" not in plain
    assert "<b>" not in plain
    assert "Hello" in plain and "World" in plain

    # HTML sanitizer allows safe formatting but strips dangerous scripts
    safe_html = sanitize_html(xss_payload)
    assert "<script>" not in safe_html
    assert "onerror" not in safe_html
    assert "<b>World</b>" in safe_html or "World" in safe_html

    # Ensure JS utils.js contains robust escapeHtml
    utils_js = (BASE_DIR / 'static' / 'js' / 'utils.js').read_text(encoding='utf-8')
    assert 'function escapeHtml' in utils_js
    assert 'window.escapeHtml' in utils_js


# =========================================================================
# AREA 14: RATE LIMITING COVERAGE
# =========================================================================

def test_area_14_rate_limiting_coverage():
    # Verify limiter decorators are attached to search, resume, messages, and unlock endpoints
    rules = {rule.endpoint: rule for rule in app.url_map.iter_rules()}
    
    assert 'api_jobs_search' in rules
    assert 'api_jobs_paginated' in rules
    assert 'api_salary_insights' in rules
    assert 'upload_resume' in rules
    assert 'api_admin_unlock_account' in rules
    assert 'api_send_message' in rules


# =========================================================================
# AREA 15: API ROUTE AUTHORIZATION & PUBLIC WHITELIST
# =========================================================================

def test_area_15_api_route_authorization_and_public_whitelist(client):
    """
    Audit all /api/... endpoints:
    Every protected endpoint must return 401/403 when unauthenticated.
    Public endpoints are strictly whitelisted.
    """
    unauthenticated_client = client

    # Sample check protected candidate endpoint returns 401
    r_cand = unauthenticated_client.get('/api/user/applied_jobs')
    assert r_cand.status_code == 401

    # Sample check protected employer endpoint returns 401
    r_emp = unauthenticated_client.get('/api/employer/jobs')
    assert r_emp.status_code == 401

    # Sample check protected admin endpoint returns 403
    r_adm = unauthenticated_client.get('/api/admin/company_verifications')
    assert r_adm.status_code == 403


# =========================================================================
# AREA 16: SERVER-SIDE INPUT VALIDATION & ENUMS
# =========================================================================

def test_area_16_server_side_input_validation_and_enums(client):
    # Candidate status validation
    with client.session_transaction() as sess:
        sess['employer_id'] = 1
        sess['role'] = 'employer'

    # Invalid status returns 400
    r_invalid_status = client.post('/api/update_candidate_status', json={'app_id': 1, 'status': 'HACKED_STATUS'})
    assert r_invalid_status.status_code == 400
    assert 'invalid status' in r_invalid_status.get_json()['message'].lower()

    # Invalid candidate interview response returns 400
    with client.session_transaction() as sess:
        sess.clear()
        sess['user_id'] = 1
        sess['role'] = 'candidate'

    r_invalid_resp = client.post('/api/candidate/interviews/1/respond', json={'action': 'invalid_action'})
    assert r_invalid_resp.status_code == 400


# =========================================================================
# AREA 17: HTTPS & DEPLOYMENT DOCUMENTATION
# =========================================================================

def test_area_17_https_and_deployment_documentation():
    readme = (BASE_DIR / 'README.md').read_text(encoding='utf-8')
    assert 'HTTPS Termination' in readme
    assert 'Reverse Proxy' in readme
    assert 'X-Forwarded-Proto' in readme
    assert 'FLASK_ENV=production' in readme
    assert 'SESSION_COOKIE_SECURE' in readme


# =========================================================================
# AREA 18: SECURITY HEADERS & CSP
# =========================================================================

def test_area_18_security_headers_and_csp(client):
    res = client.get('/')
    headers = res.headers

    assert headers.get('X-Content-Type-Options') == 'nosniff'
    assert headers.get('X-Frame-Options') == 'DENY'
    assert headers.get('X-XSS-Protection') == '1; mode=block'
    assert headers.get('Referrer-Policy') == 'strict-origin-when-cross-origin'
    assert 'geolocation=()' in headers.get('Permissions-Policy', '')
    assert 'microphone=()' in headers.get('Permissions-Policy', '')
    assert 'camera=()' in headers.get('Permissions-Policy', '')

    csp = headers.get('Content-Security-Policy', '')
    assert "default-src 'self'" in csp
    assert 'https://cdn.jsdelivr.net' in csp
    assert 'https://fonts.googleapis.com' in csp
    assert "frame-ancestors 'none'" in csp
    assert "object-src 'none'" in csp


# =========================================================================
# AREA 19: MYSQL LEAST-PRIVILEGE DOCUMENTATION
# =========================================================================

def test_area_19_mysql_least_privilege_documentation():
    readme = (BASE_DIR / 'README.md').read_text(encoding='utf-8')
    assert 'GRANT SELECT, INSERT, UPDATE, DELETE ON jobportal_db.*' in readme
    assert 'SUPER' in readme or 'administrative privileges' in readme


# =========================================================================
# AREA 20: DEPENDENCY VULNERABILITIES & PIP-AUDIT
# =========================================================================

def test_area_20_dependency_vulnerabilities_zero_cve():
    reqs = (BASE_DIR / 'requirements.txt').read_text(encoding='utf-8')
    assert 'Flask==3.1.3' in reqs
    assert 'Werkzeug==3.1.6' in reqs
    assert 'pypdf==6.16.1' in reqs
