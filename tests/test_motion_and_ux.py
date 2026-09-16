# -*- coding: utf-8 -*-
"""
Verification test suite for Motion, Smooth Scrolling & UX Polish Upgrade.
"""
import sys
sys.path.insert(0, r"c:\Program Files\Ampps\www\job-portal-web-app")

import os
import pytest
from app import app

@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client

def test_css_motion_and_scroll_rules():
    css_path = r"c:\Program Files\Ampps\www\job-portal-web-app\static\css\app.css"
    with open(css_path, "r", encoding="utf-8") as f:
        css = f.read()

    assert "scroll-behavior: smooth;" in css
    assert "scroll-padding-top:" in css
    assert "#app-scroll-progress" in css
    assert ".navbar.is-scrolled" in css
    assert ".reveal-on-scroll" in css
    assert ".card:hover" in css
    assert ".btn:active" in css
    assert "@media (prefers-reduced-motion: reduce)" in css
    print("\n[PASS] static/css/app.css contains all smooth scrolling, progress, and motion rules.")

def test_js_motion_and_ux_engine():
    js_path = r"c:\Program Files\Ampps\www\job-portal-web-app\static\js\main.js"
    with open(js_path, "r", encoding="utf-8") as f:
        js = f.read()

    assert "initNavbarAndScrollProgress" in js
    assert "initSmoothAnchorScrolling" in js
    assert "initScrollRevealObserver" in js
    assert "lockBodyScroll" in js
    assert "unlockBodyScroll" in js
    assert "requestAnimationFrame" in js
    print("[PASS] static/js/main.js contains 60fps scroll progress, anchor offset, and reveal engine.")

def test_major_pages_render_and_include_assets(client):
    routes = [
        '/',
        '/jobs',
        '/services',
        '/candidate_assessments',
        '/salary_insights',
        '/resume_intelligence'
    ]
    for r in routes:
        res = client.get(r)
        assert res.status_code == 200, f"Route {r} failed with status {res.status_code}"
        html = res.get_data(as_text=True)
        assert 'app.css' in html, f"Route {r} missing app.css"
        assert 'lenis.min.js' in html, f"Route {r} missing lenis.min.js smooth scroll library"
        assert 'main.js' in html, f"Route {r} missing main.js"
    print(f"[PASS] All {len(routes)} major application pages (including Home / index.html) include unified Lenis smooth scroll engine.")

def test_index_page_lenis_and_modal_prevent(client):
    res = client.get('/')
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert 'lenis.min.js' in html
    assert 'data-lenis-prevent' in html
    print("[PASS] index.html successfully configured with Lenis smooth scroll and modal isolation.")

if __name__ == '__main__':
    pytest.main(['-s', __file__])
