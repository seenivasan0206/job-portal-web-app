# -*- coding: utf-8 -*-
"""
Verification test suite for:
PART A — Jobs automatically close when application_deadline passes (query safety net + auto-close scheduled task + closed_reason tracking)
PART B — Employer candidate profile view modal scrolling & Lenis isolation
PART C — Salary Insights page dropdown & table scroll isolation
PART D — Single Download Resume button in employer candidate profile modal (deduplicated)
"""
import datetime
import pytest
from app import app, db_cursor, auto_close_expired_jobs

@pytest.fixture
def client():
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    with app.test_client() as client:
        yield client

def test_part_a_deadline_query_safety_net_and_auto_close(client):
    today = datetime.date.today()
    past_date = today - datetime.timedelta(days=2)
    future_date = today + datetime.timedelta(days=10)

    # Clean up test jobs
    with db_cursor(dictionary=False) as cur:
        cur.execute("DELETE FROM jobs WHERE title LIKE 'TEST_DEADLINE_%'")

    # 1. Post two jobs: one expired, one active
    with client.session_transaction() as sess:
        sess['employer_id'] = 1
        sess['user_name'] = 'Test Company'
        sess['role'] = 'employer'

    res1 = client.post('/api/employer/post_job', json={
        'title': 'TEST_DEADLINE_EXPIRED',
        'location': 'Bengaluru',
        'category': 'IT & Software',
        'job_type': 'Full-time',
        'work_mode': 'Remote',
        'experience': '2-4 Years',
        'openings': 1,
        'application_deadline': past_date.strftime('%Y-%m-%d'),
        'skills': 'Python',
        'description': 'Expired Job Description'
    })
    assert res1.status_code == 200
    assert res1.get_json()['success'] is True

    res2 = client.post('/api/employer/post_job', json={
        'title': 'TEST_DEADLINE_ACTIVE',
        'location': 'Chennai',
        'category': 'IT & Software',
        'job_type': 'Full-time',
        'work_mode': 'Remote',
        'experience': '2-4 Years',
        'openings': 2,
        'application_deadline': future_date.strftime('%Y-%m-%d'),
        'skills': 'Python',
        'description': 'Active Job Description'
    })
    assert res2.status_code == 200
    assert res2.get_json()['success'] is True

    # 2. Query safety net: Expired job must NOT appear in candidate search/listing even before background cron runs
    res_search = client.post('/api/jobs/search', json={'query': 'TEST_DEADLINE'})
    assert res_search.status_code == 200
    search_jobs = res_search.get_json()['jobs']
    search_titles = [j['title'] for j in search_jobs]
    assert 'TEST_DEADLINE_EXPIRED' not in search_titles, "Expired job should not appear in candidate search"
    assert 'TEST_DEADLINE_ACTIVE' in search_titles, "Active job should appear in candidate search"

    # Also test /api/get_all_jobs
    res_all = client.get('/api/get_all_jobs?per_page=100')
    assert res_all.status_code == 200
    all_titles = [j['title'] for j in res_all.get_json()['jobs'] if 'TEST_DEADLINE' in j.get('title', '')]
    assert 'TEST_DEADLINE_EXPIRED' not in all_titles
    assert 'TEST_DEADLINE_ACTIVE' in all_titles

    # 3. Test auto_close_expired_jobs() mechanism
    affected = auto_close_expired_jobs()
    assert affected >= 1

    # Verify expired job is now is_active = 0, closed_reason = 'deadline_passed'
    with db_cursor() as cur:
        cur.execute("SELECT is_active, status, closed_reason FROM jobs WHERE title = 'TEST_DEADLINE_EXPIRED'")
        expired_job = cur.fetchone()
        assert expired_job['is_active'] == 0
        assert expired_job['status'] == 'Closed'
        assert expired_job['closed_reason'] == 'deadline_passed'

        cur.execute("SELECT id, is_active, status, closed_reason FROM jobs WHERE title = 'TEST_DEADLINE_ACTIVE'")
        active_job = cur.fetchone()
        assert active_job['is_active'] == 1
        assert active_job['status'] == 'Published'
        assert active_job['closed_reason'] is None
        active_id = active_job['id']

    # 4. Test manual close sets closed_reason = 'manually_closed'
    res_toggle = client.post(f'/api/employer/jobs/{active_id}/toggle_status', json={'action': 'close'})
    assert res_toggle.status_code == 200
    assert res_toggle.get_json()['closed_reason'] == 'manually_closed'

    with db_cursor() as cur:
        cur.execute("SELECT is_active, closed_reason FROM jobs WHERE id = %s", (active_id,))
        closed_job = cur.fetchone()
        assert closed_job['is_active'] == 0
        assert closed_job['closed_reason'] == 'manually_closed'

    # Clean up
    with db_cursor(dictionary=False) as cur:
        cur.execute("DELETE FROM jobs WHERE title LIKE 'TEST_DEADLINE_%'")

    print("\n[PASS] Part A: Application deadline query safety net and auto-close mechanism verified.")


def test_part_b_employer_candidate_profile_modal_scroll(client):
    with client.session_transaction() as sess:
        sess['employer_id'] = 1
        sess['user_name'] = 'Test Employer'
        sess['role'] = 'employer'

    res = client.get('/employer_dashboard')
    assert res.status_code == 200
    html = res.get_data(as_text=True)

    # Modal structure & Lenis scroll isolation
    assert 'id="candidate-profile-modal"' in html
    assert 'class="dashboard-modal-dialog" data-lenis-prevent' in html
    assert 'class="dashboard-modal-body" id="cp-modal-body" data-lenis-prevent' in html
    assert 'overflow-y: auto' in html
    assert 'overscroll-behavior: contain' in html
    assert 'max-height: calc(88vh - 140px)' in html
    assert '::-webkit-scrollbar' in html

    print("[PASS] Part B: Employer candidate profile view modal scroll isolation and styles verified.")


def test_part_c_salary_insights_scroll(client):
    res = client.get('/salary_insights')
    assert res.status_code == 200
    html = res.get_data(as_text=True)

    # Dropdown & table scroll isolation
    assert 'id="role-combobox-dropdown" data-lenis-prevent' in html
    assert 'id="role-options-list" data-lenis-prevent' in html
    assert 'id="location-combobox-dropdown" data-lenis-prevent' in html
    assert 'id="location-options-list" data-lenis-prevent' in html
    assert '<div style="overflow-x:auto;" data-lenis-prevent>' in html
    assert 'overscroll-behavior: contain' in html
    assert '.combobox-options-list::-webkit-scrollbar' in html

    print("[PASS] Part C: Salary Insights dropdown and table scroll isolation verified.")


def test_part_d_single_download_resume_button(client):
    with client.session_transaction() as sess:
        sess['employer_id'] = 1
        sess['user_name'] = 'Test Employer'
        sess['role'] = 'employer'

    res = client.get('/employer_dashboard')
    assert res.status_code == 200
    html = res.get_data(as_text=True)

    # Extract modal HTML section
    modal_start = html.find('id="candidate-profile-modal"')
    assert modal_start != -1
    modal_end = html.find('<!-- Modal: Schedule Interview Dialog -->', modal_start)
    assert modal_end != -1
    modal_html = html[modal_start:modal_end]

    # Exactly 1 download resume button/link in candidate profile modal
    download_occurrences = modal_html.count('Download Resume')
    assert download_occurrences == 1, f"Expected exactly 1 'Download Resume' in modal, found {download_occurrences}"

    # Confirm it is located right below the inline preview iframe
    preview_idx = modal_html.find('id="cp-resume-frame-box"')
    download_idx = modal_html.find('id="cp-resume-link"')
    assert preview_idx != -1
    assert download_idx != -1
    assert download_idx > preview_idx, "Download Resume button must be positioned right below inline resume preview"

    # Confirm the duplicate button 'Download Original' is removed
    assert 'Download Original' not in modal_html

    print("[PASS] Part D: Candidate profile modal has exactly one Download Resume button positioned under preview.")
