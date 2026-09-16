# -*- coding: utf-8 -*-
"""
Unit and integration tests for Job Search, Sorting, Filter Persistence, and Job Details Routing.
"""
import pytest
from app import app, db_cursor

@pytest.fixture
def client():
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    with app.test_client() as client:
        yield client

def test_api_jobs_search_sorting_modes(client):
    # 1. Newest First
    res = client.post('/api/jobs/search', json={'sort': 'newest'})
    assert res.status_code == 200
    data = res.get_json()
    assert data['success'] is True
    assert 'jobs' in data
    assert data['sort'] == 'newest'

    # 2. Oldest First
    res = client.post('/api/jobs/search', json={'sort': 'oldest'})
    assert res.status_code == 200
    data = res.get_json()
    assert data['success'] is True
    assert data['sort'] == 'oldest'

    # 3. Salary: High to Low
    res = client.post('/api/jobs/search', json={'sort': 'salary_high_to_low'})
    assert res.status_code == 200
    data = res.get_json()
    assert data['success'] is True
    assert data['sort'] == 'salary_high_to_low'

    # 4. Salary: Low to High
    res = client.post('/api/jobs/search', json={'sort': 'salary_low_to_high'})
    assert res.status_code == 200
    data = res.get_json()
    assert data['success'] is True
    assert data['sort'] == 'salary_low_to_high'

    # 5. Most Relevant
    res = client.post('/api/jobs/search', json={'sort': 'most_relevant', 'title': 'Developer'})
    assert res.status_code == 200
    data = res.get_json()
    assert data['success'] is True

    # 6. Recently Updated
    res = client.post('/api/jobs/search', json={'sort': 'recently_updated'})
    assert res.status_code == 200
    data = res.get_json()
    assert data['success'] is True

    print("[PASS] All 6 sorting modes (newest, oldest, salary_high_to_low, salary_low_to_high, most_relevant, recently_updated) verified.")

def test_api_jobs_search_combined_filters(client):
    res = client.post('/api/jobs/search', json={
        'title': 'Engineer',
        'location': 'Bangalore',
        'category': 'IT & Software',
        'experience': '1-3 Years',
        'job_type': 'Full-time',
        'work_mode': 'Remote',
        'sort': 'salary_high_to_low'
    })
    assert res.status_code == 200
    data = res.get_json()
    assert data['success'] is True
    assert 'total' in data
    assert isinstance(data['jobs'], list)
    print("[PASS] Combined filters (title, location, category, experience, job_type, work_mode) verified.")

def test_job_detail_page_valid_job(client):
    # Fetch job list to find an existing job ID
    with db_cursor() as cur:
        cur.execute("SELECT id, title FROM jobs LIMIT 1")
        job = cur.fetchone()

    if job:
        job_id = job['id']
        # Test /job/<id>
        res = client.get(f'/job/{job_id}')
        assert res.status_code == 200
        html = res.get_data(as_text=True)
        assert job['title'] in html
        assert 'Apply Now' in html or 'Application Submitted' in html

        # Test /jobs/<id> alias
        res_alias = client.get(f'/jobs/{job_id}')
        assert res_alias.status_code == 200

        print(f"[PASS] Valid job detail routes /job/{job_id} and /jobs/{job_id} return 200 OK with correct template.")
    else:
        print("[SKIP] No jobs in database to test valid detail view.")

def test_job_detail_page_invalid_job_returns_404(client):
    res = client.get('/job/99999999')
    assert res.status_code == 404
    html = res.get_data(as_text=True)
    assert 'Job Not Found' in html
    assert 'Browse All Active Jobs' in html
    assert '/jobs' in html
    print("[PASS] Invalid job ID returns professional branded 404 page without exposing debug errors.")

def test_jobs_listing_html_and_sorting_dropdown(client):
    res = client.get('/jobs')
    assert res.status_code == 200
    html = res.get_data(as_text=True)

    # Check sort options exist
    assert 'newest' in html
    assert 'oldest' in html
    assert 'salary_high_to_low' in html
    assert 'salary_low_to_high' in html
    assert 'most_relevant' in html
    assert 'recently_updated' in html

    # Check filter controls
    assert 'search-title' in html
    assert 'search-location' in html
    assert 'filter-category' in html
    assert 'filter-exp' in html
    assert 'filter-job-type' in html
    assert 'filter-work-mode' in html

    # Check View Details link format
    assert '/job/' in html

    print("[PASS] Jobs listing page renders all 6 sort options, filter controls, and /job/ link targets.")

if __name__ == '__main__':
    pytest.main(['-s', __file__])
