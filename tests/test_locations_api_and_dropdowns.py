import pytest
import json
import re
from app import app, db_cursor, get_all_locations_data, _is_indian_or_remote_location


@pytest.fixture
def client():
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    with app.test_client() as client:
        yield client


def test_is_indian_or_remote_location_helper():
    # Indian cities and states
    assert _is_indian_or_remote_location('Bengaluru') is True
    assert _is_indian_or_remote_location('Bengaluru, Karnataka') is True
    assert _is_indian_or_remote_location('Bangalore, India') is True
    assert _is_indian_or_remote_location('Chennai,Coimbatore') is True
    assert _is_indian_or_remote_location('Hyderabad / Hybrid') is True
    assert _is_indian_or_remote_location('Remote') is True
    assert _is_indian_or_remote_location('Work from Home') is True
    assert _is_indian_or_remote_location('Pan India') is True
    assert _is_indian_or_remote_location('Pune, Maharashtra') is True
    assert _is_indian_or_remote_location('Kochi (Cochin)') is True
    assert _is_indian_or_remote_location('Guwahati, Assam') is True

    # International locations
    assert _is_indian_or_remote_location('London, UK') is False
    assert _is_indian_or_remote_location('Singapore') is False
    assert _is_indian_or_remote_location('Dubai, UAE') is False
    assert _is_indian_or_remote_location('San Francisco, USA') is False
    assert _is_indian_or_remote_location('Berlin, Germany') is False
    assert _is_indian_or_remote_location('Tokyo, Japan') is False
    assert _is_indian_or_remote_location('Sydney, Australia') is False
    assert _is_indian_or_remote_location('Toronto, Canada') is False


def test_api_locations_returns_comprehensive_indian_cities(client):
    res = client.get('/api/locations')
    assert res.status_code == 200
    data = res.get_json()
    assert data['success'] is True
    assert 'india' in data
    assert 'international' in data

    india_list = data['india']
    # Must have ~100-150 major Indian cities across all states
    assert len(india_list) >= 100, f'Expected >= 100 Indian locations, got {len(india_list)}'

    # Check key representative cities across India
    must_have_cities = [
        'Bengaluru', 'Mumbai', 'New Delhi', 'Hyderabad', 'Chennai', 'Kolkata', 'Pune', 'Ahmedabad',
        'Kochi (Cochin)', 'Coimbatore', 'Visakhapatnam', 'Jaipur', 'Chandigarh', 'Lucknow',
        'Patna', 'Guwahati', 'Indore', 'Bhubaneswar', 'Surat', 'Dehradun', 'Remote'
    ]
    for city in must_have_cities:
        assert any(city.lower() in loc.lower() for loc in india_list), f'City {city} missing from Indian locations list'


def test_api_locations_dynamic_international_filtering(client):
    # 1. Create a dummy employer
    with db_cursor(dictionary=False) as cur:
        cur.execute("""
            INSERT INTO employee (company_name, email, password, is_verified)
            VALUES ('Global Tech Inc', 'intl_test_employer@hirevolt.com', 'hashedpwd', 1)
        """)
        emp_id = cur.lastrowid

        # 2. Insert test jobs: 2 international, 1 Indian
        cur.execute("""
            INSERT INTO jobs (employer_id, title, description, location, company_name, is_active)
            VALUES (%s, 'London Backend Lead', 'Great job in London', 'London, UK', 'Global Tech Inc', 1)
        """, (emp_id,))
        job_london_id = cur.lastrowid

        cur.execute("""
            INSERT INTO jobs (employer_id, title, description, location, company_name, is_active)
            VALUES (%s, 'Singapore Cloud Architect', 'Great job in SG', 'Singapore', 'Global Tech Inc', 1)
        """, (emp_id,))
        job_sg_id = cur.lastrowid

        cur.execute("""
            INSERT INTO jobs (employer_id, title, description, location, company_name, is_active)
            VALUES (%s, 'Coimbatore Python Dev', 'Great job in CBE', 'Coimbatore', 'Global Tech Inc', 1)
        """, (emp_id,))
        job_cbe_id = cur.lastrowid

    try:
        # 3. Fetch /api/locations
        res = client.get('/api/locations')
        assert res.status_code == 200
        data = res.get_json()
        intl = data['international']

        # Verify dynamic international locations are present
        assert 'London, UK' in intl
        assert 'Singapore' in intl

        # Verify Indian city 'Coimbatore' is NOT in international
        assert 'Coimbatore' not in intl

        # 4. Deactivate London job and verify it drops from dynamic international list
        with db_cursor(dictionary=False) as cur:
            cur.execute('UPDATE jobs SET is_active = 0 WHERE id = %s', (job_london_id,))

        res2 = client.get('/api/locations')
        data2 = res2.get_json()
        intl2 = data2['international']
        assert 'London, UK' not in intl2
        assert 'Singapore' in intl2

    finally:
        # Cleanup
        with db_cursor(dictionary=False) as cur:
            cur.execute('DELETE FROM jobs WHERE id IN (%s, %s, %s)', (job_london_id, job_sg_id, job_cbe_id))
            cur.execute('DELETE FROM employee WHERE id = %s', (emp_id,))


def test_frontend_templates_location_integration(client):
    # Set up session for recruiter
    with client.session_transaction() as sess:
        sess['employer_id'] = 1
        sess['user_name'] = 'Test Employer'
        sess['role'] = 'employer'

    res_talent = client.get('/recruiter_candidates')
    assert res_talent.status_code == 200
    html_talent = res_talent.get_data(as_text=True)

    # In recruiter_candidates.html, verify hardcoded 5-city option list is gone
    assert '<option value="Bengaluru">Bengaluru</option>' not in html_talent
    assert '<select id="filter-location"' in html_talent
    assert 'populateLocationSelect' in html_talent

    # In jobs.html
    res_jobs = client.get('/jobs')
    assert res_jobs.status_code == 200
    html_jobs = res_jobs.get_data(as_text=True)
    assert 'id="search-location"' in html_jobs
    assert 'jobs-locations-list' in html_jobs
    assert 'populateLocationDatalist' in html_jobs

    # In candidate_profile_edit.html
    with client.session_transaction() as sess:
        sess['user_id'] = 1
        sess['user_name'] = 'Test User'
        sess['role'] = 'user'

    res_cp = client.get('/candidate/profile/edit')
    assert res_cp.status_code == 200
    html_cp = res_cp.get_data(as_text=True)
    assert 'id="basic-location"' in html_cp
    assert 'candidate-locations-list' in html_cp

    # In companies.html
    res_comp = client.get('/companies')
    assert res_comp.status_code == 200
    html_comp = res_comp.get_data(as_text=True)
    assert '<select id="filter-location"' in html_comp
    assert 'populateLocationSelect' in html_comp


def test_main_js_defines_locations_caching():
    with open('static/js/main.js', 'r', encoding='utf-8') as f:
        js_code = f.read()

    assert 'fetchLocations' in js_code
    assert 'populateLocationSelect' in js_code
    assert 'populateLocationDatalist' in js_code
    assert 'hirevolt_locations_cache' in js_code
    assert '<optgroup label="India">' in js_code
    assert '<optgroup label="International">' in js_code
