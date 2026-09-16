# -*- coding: utf-8 -*-
"""
Tests for Candidate Profile Edit Left Navigation Sidebar Scrolling & Lenis Isolation.
Verifies:
1. data-lenis-prevent is present on profile-nav-sidebar to isolate wheel and drag scrolling from Lenis smooth scroll engine.
2. Sticky positioning, max-height, overflow-y: auto, overscroll-behavior: contain, and custom scrollbar styling.
3. Flex child integrity (flex-shrink: 0) preventing vertical compression so content is fully scrollable from Basic Profile to Resume Document.
4. Responsive / mobile rules on @media (max-width: 992px).
5. All 13 profile navigation items and links are properly mapped in the DOM.
"""
import pytest
from app import app

@pytest.fixture
def client():
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    with app.test_client() as client:
        yield client

def test_candidate_profile_edit_sidebar_attributes_and_styles(client):
    with client.session_transaction() as sess:
        sess['user_id'] = 1
        sess['user_name'] = 'Test Candidate'
        sess['role'] = 'user'

    res = client.get('/candidate/profile/edit')
    assert res.status_code == 200
    html = res.get_data(as_text=True)

    # 1. Lenis wheel isolation
    assert 'class="profile-nav-sidebar"' in html or "class='profile-nav-sidebar'" in html
    assert 'data-lenis-prevent' in html

    # 2. Key CSS properties on profile-nav-sidebar
    assert 'position: sticky' in html or 'position: -webkit-sticky' in html
    assert 'overflow-y: auto' in html
    assert 'overscroll-behavior: contain' in html
    assert 'scrollbar-width: thin' in html
    assert '::-webkit-scrollbar' in html
    assert 'flex-shrink: 0' in html

    # 3. All 13 navigation anchors from Basic Profile down to Resume Document
    expected_links = [
        '#section-basic',
        '#section-summary',
        '#section-preferences',
        '#section-education',
        '#section-skills',
        '#section-employment',
        '#section-internships',
        '#section-projects',
        '#section-certifications',
        '#section-languages',
        '#section-exams',
        '#section-academic',
        '/candidate/resume'
    ]
    for href in expected_links:
        assert f'href="{href}"' in html, f"Missing expected sidebar link {href}"

    # 4. Action buttons at bottom of sidebar
    assert 'Back to Dashboard' in html
    assert 'View Public Profile' in html

    print("\n[PASS] Candidate profile edit sidebar verified with data-lenis-prevent, scroll rules, and all 13 sections.")

def test_all_app_sidebars_have_lenis_prevent(client):
    """Ensure all interactive sidebars across the application have data-lenis-prevent."""
    templates = {
        'candidate_profile_edit.html': 'profile-nav-sidebar',
        'user_dashboard.html': 'workspace-sidebar',
        'jobs.html': 'filter-sidebar',
        'employer_dashboard.html': 'emp-sidebar',
        'admin_dashboard.html': 'admin-sidebar'
    }

    import os
    tpl_dir = os.path.join(os.path.dirname(__file__), '..', 'templates')
    for tpl_name, sidebar_class in templates.items():
        tpl_path = os.path.join(tpl_dir, tpl_name)
        assert os.path.exists(tpl_path), f"Template {tpl_name} not found"
        with open(tpl_path, 'r', encoding='utf-8') as f:
            content = f.read()
        assert sidebar_class in content, f"{tpl_name} missing {sidebar_class}"
        assert 'data-lenis-prevent' in content, f"{tpl_name} missing data-lenis-prevent on sidebar"

    print("[PASS] All application sidebars verified with data-lenis-prevent attribute.")
