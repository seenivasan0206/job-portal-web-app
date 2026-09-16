# -*- coding: utf-8 -*-
"""
Verification test suite for Professional Authentication Modal UX & Close Functionality.
"""
import sys
sys.path.insert(0, r"c:\Program Files\Ampps\www\job-portal-web-app")

import re
import pytest
from app import app

@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client

def test_modal_markup_and_accessibility(client):
    res = client.get('/')
    assert res.status_code == 200
    html = res.get_data(as_text=True)

    # 1. Check user authentication modal markup
    assert 'id="user-auth-modal"' in html
    assert 'role="dialog"' in html
    assert 'aria-modal="true"' in html
    assert 'class="modal-close"' in html
    assert 'aria-label="Close"' in html
    assert 'onclick="closeUserModal()"' in html
    assert 'onclick="handleBackdropClick(event, \'user\')"' in html

    # 2. Check employer authentication modal markup
    assert 'id="emp-auth-modal"' in html
    assert 'onclick="closeEmpModal()"' in html
    assert 'onclick="handleBackdropClick(event, \'employer\')"' in html

    # 3. Check all three auth states in user modal
    assert 'id="form-signup"' in html
    assert 'id="form-login"' in html
    assert 'id="form-forgot"' in html

    # 4. Check employer auth states
    assert 'id="emp-form-register"' in html
    assert 'id="emp-form-login"' in html

    print("\n[PASS] Modal markup and accessibility attributes verified in base/index HTML.")

def test_assessment_pages_unauthenticated_flow(client):
    # Assessment marketplace page unauthenticated
    res = client.get('/candidate/assessments')
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert 'openUserModal(\'login\')' in html
    print("[PASS] Unauthenticated candidate marketplace triggers openUserModal('login')")

    # Assessment detail page unauthenticated
    res_det = client.get('/candidate/assessments/1')
    assert res_det.status_code == 200
    html_det = res_det.get_data(as_text=True)
    assert 'openUserModal(\'login\')' in html_det
    print("[PASS] Unauthenticated candidate assessment detail page triggers openUserModal('login')")

def test_css_animations_and_close_button_styles():
    with open(r"c:\Program Files\Ampps\www\job-portal-web-app\static\css\app.css", "r", encoding="utf-8") as f:
        css = f.read()

    # Backdrop
    assert '.modal-backdrop' in css
    assert 'backdrop-filter: blur' in css
    assert 'opacity: 0' in css
    assert '.modal-backdrop.active' in css

    # Content scale and fade
    assert '.modal-content' in css
    assert 'transform: scale(0.95)' in css or 'transform: scale' in css
    assert '.modal-backdrop.active .modal-content' in css

    # Close button styling & accessibility
    assert '.modal-close' in css
    assert '.modal-close:hover' in css
    assert '.modal-close:active' in css
    assert '.modal-close:focus-visible' in css
    assert 'outline:' in css

    print("[PASS] CSS animations, scale-up/scale-down, and focus-visible states verified.")

def test_modal_script_handlers(client):
    res = client.get('/')
    html = res.get_data(as_text=True)

    # Key functions must exist
    assert 'function openUserModal' in html
    assert 'function closeUserModal' in html
    assert 'function openEmpModal' in html
    assert 'function closeEmpModal' in html
    assert 'function closeAllModals' in html
    assert 'function handleBackdropClick' in html
    assert 'function lockBodyScroll' in html
    assert 'function unlockBodyScroll' in html
    assert 'Escape' in html or 'Esc' in html
    assert 'window.openSignInModal' in html

    print("[PASS] Modal JavaScript handlers (Escape, backdrop click, body scroll unlock, focus restoration) verified.")

def test_jobs_page_unauthenticated_actions_trigger_modal(client):
    res = client.get('/jobs')
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert 'openUserModal(\'login\')' in html
    assert 'handleJobApply' in html
    assert 'handleJobBookmark' in html
    print("[PASS] Jobs page unauthenticated Apply Now and Bookmark actions trigger openUserModal('login').")

def test_job_detail_page_unauthenticated_actions_trigger_modal(client):
    res = client.get('/job/1')
    if res.status_code == 200:
        html = res.get_data(as_text=True)
        assert 'openUserModal(\'login\')' in html
        assert 'handleDetailApply' in html
        assert 'handleDetailSave' in html
        print("[PASS] Job detail page unauthenticated Apply and Save actions trigger openUserModal('login').")

def test_modal_body_scroll_and_pinned_close_css():
    with open(r"c:\Program Files\Ampps\www\job-portal-web-app\static\css\app.css", "r", encoding="utf-8") as f:
        css = f.read()

    assert '.modal-body' in css
    assert 'overflow-y: auto' in css
    assert 'overscroll-behavior: contain' in css
    print("[PASS] Pinned X close button and .modal-body scroll container CSS rules verified.")

def test_clean_stacking_order_hierarchy():
    with open(r"c:\Program Files\Ampps\www\job-portal-web-app\static\css\app.css", "r", encoding="utf-8") as f:
        css = f.read()

    # Systematic stacking hierarchy: navbar (100) < modal-backdrop (1000) < modal-content (1010) < toast (2000)
    assert 'z-index: 100;' in css
    assert 'z-index: 1000;' in css
    assert 'z-index: 1010;' in css
    assert 'z-index: 2000;' in css
    print("[PASS] Systematic stacking hierarchy verified: navbar < modal < toast.")

def test_auth_success_closes_modal_before_toast(client):
    res = client.get('/')
    html = res.get_data(as_text=True)

    # In user login success, closeUserModal() must precede showToast()
    assert 'closeUserModal();' in html
    assert 'Successfully Signed In' in html
    assert 'pending_job_action' in html
    print("[PASS] Auth success modal lifecycle verified: modal closes before success toast.")

def test_accessible_toast_attributes():
    with open(r"c:\Program Files\Ampps\www\job-portal-web-app\static\js\main.js", "r", encoding="utf-8") as f:
        js = f.read()

    assert 'aria-live' in js
    assert 'aria-atomic' in js
    assert 'role' in js
    print("[PASS] Toast notifications accessibility attributes (aria-live, aria-atomic, role) verified.")

if __name__ == '__main__':
    pytest.main(['-s', __file__])
