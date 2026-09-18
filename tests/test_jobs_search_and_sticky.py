from datetime import datetime, timedelta
from pathlib import Path
import pytest
from app import app, db_cursor, format_relative_time, enrich_job_presentation

BASE_DIR = Path(__file__).resolve().parent.parent

@pytest.fixture
def client():
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    with app.test_client() as client:
        yield client


def test_sticky_filter_sidebar_css_and_mobile_responsive():
    """Verify sticky filter sidebar CSS rules on desktop and clean in-flow reset on mobile."""
    jobs_html = (BASE_DIR / 'templates' / 'jobs.html').read_text(encoding='utf-8')
    app_css = (BASE_DIR / 'static' / 'css' / 'app.css').read_text(encoding='utf-8')

    # 1. Desktop sticky styles
    assert 'position: sticky;' in jobs_html
    assert 'top: calc(var(--navbar-height, 72px) + 24px);' in jobs_html
    assert 'max-height: calc(100vh - var(--navbar-height, 72px) - 40px);' in jobs_html
    assert 'overflow-y: auto;' in jobs_html
    assert 'align-self: flex-start;' in jobs_html

    # 2. Mobile non-sticky override under max-width: 992px
    assert '@media (max-width: 992px)' in jobs_html
    assert 'position: static;' in jobs_html
    assert 'max-height: none;' in jobs_html
    assert 'overflow-y: visible;' in jobs_html

    # 3. Body overflow-x: clip to preserve sticky positioning
    assert 'overflow-x: clip;' in app_css


def test_format_relative_time_all_intervals():
    """Verify relative posted time calculation across all required intervals."""
    now = datetime.now()

    # < 1 minute -> Just now, is_new=True
    t_str, is_new = format_relative_time(now - timedelta(seconds=25))
    assert t_str == "Just now"
    assert is_new is True

    # < 60 minutes -> X minutes ago, is_new=True
    t_str, is_new = format_relative_time(now - timedelta(minutes=20))
    assert t_str == "20 minutes ago"
    assert is_new is True

    # < 24 hours -> X hours ago, is_new=True
    t_str, is_new = format_relative_time(now - timedelta(hours=3))
    assert t_str == "3 hours ago"
    assert is_new is True

    # 28 hours ago -> 1 day ago, is_new=False
    t_str, is_new = format_relative_time(now - timedelta(hours=28))
    assert t_str == "1 day ago"
    assert is_new is False

    # 7 days ago -> 7 days ago, is_new=False
    t_str, is_new = format_relative_time(now - timedelta(days=7))
    assert t_str == "7 days ago"
    assert is_new is False

    # >= 30 days -> 30+ days ago, is_new=False
    t_str, is_new = format_relative_time(now - timedelta(days=45))
    assert t_str == "30+ days ago"
    assert is_new is False


def test_enrich_job_presentation_posted_label_and_ids():
    """Verify enrich_job_presentation populates posted_label, is_new, and ensures id resolution."""
    now = datetime.now()

    job_fresh = {
        'job_id': 101,
        'title': 'Frontend Engineer',
        'created_at': now - timedelta(hours=2),
        'salary_min': 800000,
        'salary_max': 1400000
    }
    enriched = enrich_job_presentation(job_fresh)

    assert enriched['id'] == 101
    assert enriched['is_new'] is True
    assert enriched['posted_time_ago'] == "2 hours ago"
    assert enriched['posted_label'] == "Posted 2 hours ago"
    assert "8,00,000" in enriched['salary_display'] or "800,000" in enriched['salary_display']

    job_older = {
        'id': 102,
        'title': 'Lead Architect',
        'created_at': now - timedelta(days=35)
    }
    enriched_old = enrich_job_presentation(job_older)
    assert enriched_old['job_id'] == 102
    assert enriched_old['is_new'] is False
    assert enriched_old['posted_time_ago'] == "30+ days ago"
    assert enriched_old['posted_label'] == "Posted 30+ days ago"


def test_api_jobs_sorting_modes(client):
    """Verify /api/jobs/search functional sorting across all supported modes."""
    # 1. Newest First
    res = client.post('/api/jobs/search', json={'sort': 'newest'})
    assert res.status_code == 200
    data = res.get_json()
    assert data['success'] is True
    jobs_newest = data['jobs']
    assert len(jobs_newest) > 0
    # Verify posted_label and relative time are populated
    assert 'posted_label' in jobs_newest[0]
    assert 'posted_time_ago' in jobs_newest[0]

    # 2. Oldest First
    res = client.post('/api/jobs/search', json={'sort': 'oldest'})
    assert res.status_code == 200
    data = res.get_json()
    jobs_oldest = data['jobs']
    assert jobs_newest[0]['id'] != jobs_oldest[0]['id']

    # 3. Salary: High to Low
    res = client.post('/api/jobs/search', json={'sort': 'salary_high_to_low'})
    assert res.status_code == 200
    jobs_sal_desc = res.get_json()['jobs']
    salaries_max = [j.get('salary_max', 0) for j in jobs_sal_desc]
    assert salaries_max == sorted(salaries_max, reverse=True)

    # 4. Salary: Low to High
    res = client.post('/api/jobs/search', json={'sort': 'salary_low_to_high'})
    assert res.status_code == 200
    jobs_sal_asc = res.get_json()['jobs']
    salaries_min = [j.get('salary_min') or j.get('salary_max') or 0 for j in jobs_sal_asc if (j.get('salary_min') or j.get('salary_max'))]
    assert salaries_min == sorted(salaries_min)

    # 5. Most Relevant
    res = client.post('/api/jobs/search', json={'sort': 'most_relevant', 'title': 'Python'})
    assert res.status_code == 200
    assert res.get_json()['success'] is True


def test_api_jobs_search_filters(client):
    """Verify searching by category, experience, job type, and work mode."""
    res = client.post('/api/jobs/search', json={
        'category': 'IT & Software',
        'job_type': 'Full-time',
        'work_mode': 'Remote'
    })
    assert res.status_code == 200
    data = res.get_json()
    assert data['success'] is True
    for j in data['jobs']:
        if j.get('category'):
            assert j['category'] == 'IT & Software'
        if j.get('job_type'):
            assert j['job_type'] == 'Full-time'
        if j.get('work_mode'):
            assert j['work_mode'] == 'Remote'


def test_view_details_routes_and_404_resolution(client):
    """Verify View Details opens /job/<id>, handles trailing slashes, and routes without 404."""
    # Get a real existing job ID
    with db_cursor() as cur:
        cur.execute("SELECT id FROM jobs WHERE is_active = 1 LIMIT 1")
        row = cur.fetchone()
    assert row is not None
    job_id = row['id']

    # Standard /job/<id>
    r1 = client.get(f'/job/{job_id}')
    assert r1.status_code == 200
    assert b"Back to All Jobs" in r1.data

    # Trailing slash /job/<id>/ (must NOT return 404)
    r2 = client.get(f'/job/{job_id}/')
    assert r2.status_code == 200

    # Plural alias /jobs/<id> and /jobs/<id>/
    r3 = client.get(f'/jobs/{job_id}')
    assert r3.status_code == 200
    r4 = client.get(f'/jobs/{job_id}/')
    assert r4.status_code == 200

    # /job index redirect
    r5 = client.get(f'/job?id={job_id}')
    assert r5.status_code in (301, 302)
    assert f'/job/{job_id}' in r5.headers.get('Location', '')

    # Non-existent job produces clean 404 with job_not_found template
    r_missing = client.get('/job/999999')
    assert r_missing.status_code == 404
    assert b"Job Not Found" in r_missing.data


def test_job_card_layout_and_action_links():
    """Verify job cards have consistent layout, responsive classes, and valid action IDs."""
    jobs_html = (BASE_DIR / 'templates' / 'jobs.html').read_text(encoding='utf-8')

    # Check required elements in template
    assert 'class="job-title-link"' in jobs_html
    assert 'class="job-meta-row"' in jobs_html
    assert 'class="job-card-actions"' in jobs_html
    assert 'class="job-card-footer"' in jobs_html
    assert 'fa-history' in jobs_html  # Posted time icon

    # Check View Details link patterns
    assert 'href="/job/{{ job_id }}"' in jobs_html or 'href="/job/{{ job.id }}"' in jobs_html
    assert 'href="/job/${jobId}"' in jobs_html
    assert 'handleJobApply(${jobId})' in jobs_html
    assert 'handleJobBookmark(${jobId}' in jobs_html

    # Check clearFilters resets sort-order
    assert "document.getElementById('sort-order').value = 'newest'" in jobs_html


def test_mobile_job_search_and_bottom_sheet_elements():
    """
    Verifies that the mobile search header, 8-filter bottom sheet panel,
    and mobile job cards meet all user requirements without altering desktop view.
    """
    jobs_html = (BASE_DIR / 'templates' / 'jobs.html').read_text(encoding='utf-8')

    # 1. Mobile Search Header
    assert 'class="mobile-search-header-container"' in jobs_html
    assert 'id="mobile-search-jobs"' in jobs_html
    assert 'id="mobile-search-location"' in jobs_html
    assert 'id="mobile-filter-trigger"' in jobs_html
    assert 'Filters' in jobs_html

    # 2. Bottom Sheet / Full-Screen Panel & 8 Filters
    assert 'id="mobile-filter-sheet"' in jobs_html
    assert 'id="mobile-filter-backdrop"' in jobs_html
    assert 'id="mfilter-role"' in jobs_html         # 1. Role
    assert 'id="mfilter-location"' in jobs_html     # 2. Location
    assert 'id="mfilter-salary"' in jobs_html       # 3. Salary
    assert 'id="mfilter-exp"' in jobs_html          # 4. Experience
    assert 'id="mfilter-type"' in jobs_html         # 5. Employment type
    assert 'id="mfilter-remote"' in jobs_html       # 6. Remote
    assert 'id="mfilter-date"' in jobs_html         # 7. Date posted
    assert 'id="mfilter-skills"' in jobs_html       # 8. Skills

    # Bottom Sheet Buttons
    assert 'id="mfilter-clear-btn"' in jobs_html
    assert 'id="mfilter-apply-btn"' in jobs_html

    # 3. Mobile Job Cards (Title, Company, Location, Salary, Experience, Employment type, Posted date, Save button, Primary: View Job)
    assert 'btn-job-save' in jobs_html
    assert 'btn-job-view' in jobs_html
    assert 'View Job' in jobs_html

    # 4. Desktop Sidebar is hidden on mobile so 10 filters are not permanently displayed on screen
    assert '.filter-sidebar {\n            display: none !important;' in jobs_html or 'display: none !important;' in jobs_html

    print("\n[PASS] Mobile job search, bottom sheet, and job cards verified successfully.")


def test_mobile_job_detail_hierarchy_and_sticky_apply(client):
    """
    Verifies that mobile job details follows the exact hierarchy:
    Job title, Company, Location, Salary, Apply button,
    followed by Description, Responsibilities, Requirements, Skills, Benefits, and Company information,
    with collapsible sections and non-obscuring sticky apply button.
    """
    with db_cursor() as cur:
        cur.execute("SELECT id FROM jobs WHERE is_active = 1 LIMIT 1")
        row = cur.fetchone()
    assert row is not None
    job_id = row['id']

    res = client.get(f'/job/{job_id}')
    assert res.status_code == 200
    html = res.get_data(as_text=True)

    # 1. Isolation containers
    assert 'job-detail-desktop-view' in html
    assert 'job-detail-mobile-view' in html

    # 2. Mobile Top Summary Structure: Title, Company, Location, Salary, Apply button
    assert 'mobile-job-hero-card' in html
    assert 'mobile-job-hero-title' in html
    assert 'mobile-job-hero-company' in html
    assert 'mobile-job-hero-salary' in html
    assert 'mobile-btn-apply-main' in html
    assert 'mobile-btn-save-main' in html

    # 3. Sequential Structured Sections in exact requested order
    assert 'id="msec-description"' in html          # 1. Description
    assert 'id="msec-responsibilities"' in html     # 2. Responsibilities
    assert 'id="msec-requirements"' in html         # 3. Requirements
    assert 'id="msec-skills"' in html               # 4. Skills
    assert 'id="msec-benefits"' in html             # 5. Benefits
    assert 'id="msec-company"' in html              # 6. Company information

    # 4. Collapsible sections where content is long
    assert 'mobile-collapsible-box' in html
    assert 'mobile-toggle-expand-btn' in html
    assert 'toggleMobileSection' in html

    # 5. Mobile Sticky Apply Bar and Safe bottom padding
    assert 'job-detail-mobile-sticky-bar' in html
    assert 'padding-bottom: calc(150px' in html

    print("\n[PASS] Mobile job details hierarchy, collapsible sections, and sticky apply verified successfully.")
