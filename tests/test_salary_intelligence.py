# -*- coding: utf-8 -*-
"""
Verification test suite for Upgraded Salary Intelligence System.
"""
import sys
sys.path.insert(0, r"c:\Program Files\Ampps\www\job-portal-web-app")

import pytest
from app import app
from salary_data import ALL_JOB_ROLES, ALL_LOCATIONS, ROLES_BY_CATEGORY

@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client

def test_salary_insights_page_routes_and_html(client):
    # Test all aliased routes
    routes = ['/salary-insights', '/salary_insights', '/salary_calculator', '/salary-calculator']
    for r in routes:
        res = client.get(r)
        assert res.status_code == 200, f"Route {r} failed with status {res.status_code}"
        html = res.get_data(as_text=True)
        assert 'Salary Intelligence System' in html
        assert 'id="role-combobox"' in html
        assert 'id="location-combobox"' in html
        assert 'id="filter-search"' in html
        assert 'id="kpi-avg-salary"' in html
        assert 'id="chartRole"' in html
        assert 'id="chartExperience"' in html
        assert 'id="chartLocation"' in html
        assert 'id="chartDistribution"' in html
        assert 'id="chartSkill"' in html
        assert 'id="salary-table-body"' in html
    
    print("\n[PASS] All 4 salary insights page routes render successfully with full intelligence UI.")

def test_role_and_location_library_size():
    assert len(ALL_JOB_ROLES) >= 100, f"Expected 100+ roles, found {len(ALL_JOB_ROLES)}"
    assert len(ALL_LOCATIONS) >= 20, f"Expected 20+ locations, found {len(ALL_LOCATIONS)}"
    assert len(ROLES_BY_CATEGORY) >= 6, f"Expected 6+ categories, found {len(ROLES_BY_CATEGORY)}"
    
    # Check specific categories and roles requested by user
    assert "Data Analyst" in ALL_JOB_ROLES
    assert "Data Engineer" in ALL_JOB_ROLES
    assert "Data Scientist" in ALL_JOB_ROLES
    assert "Software Engineer" in ALL_JOB_ROLES
    assert "DevOps Engineer" in ALL_JOB_ROLES
    assert "Cloud Architect" in ALL_JOB_ROLES
    assert "Cybersecurity Analyst" in ALL_JOB_ROLES
    assert "Product Manager" in ALL_JOB_ROLES
    assert "QA Engineer" in ALL_JOB_ROLES
    assert "UI Designer" in ALL_JOB_ROLES
    assert "UX Designer" in ALL_JOB_ROLES

    # Check locations
    assert "Chennai" in ALL_LOCATIONS
    assert "Bangalore" in ALL_LOCATIONS
    assert "Hyderabad" in ALL_LOCATIONS
    assert "Pune" in ALL_LOCATIONS
    assert "Mumbai" in ALL_LOCATIONS
    assert "Delhi NCR" in ALL_LOCATIONS
    assert "Coimbatore" in ALL_LOCATIONS
    assert "Madurai" in ALL_LOCATIONS
    assert "Trichy" in ALL_LOCATIONS
    assert "Salem" in ALL_LOCATIONS

    print(f"[PASS] Role library verified with {len(ALL_JOB_ROLES)} roles and {len(ALL_LOCATIONS)} locations.")

def test_api_salary_insights_default(client):
    res = client.get('/api/salary_insights')
    assert res.status_code == 200
    data = res.get_json()
    assert data.get('success') is True
    assert 'kpis' in data
    assert data['kpis']['avg_salary'] > 0
    assert data['kpis']['min_salary'] > 0
    assert data['kpis']['max_salary'] > 0
    assert data['kpis']['median_salary'] > 0
    assert 'charts' in data
    assert len(data['charts']['by_role']['labels']) > 0
    assert len(data['charts']['by_experience']['labels']) > 0
    assert len(data['charts']['by_location']['labels']) > 0
    assert len(data['charts']['distribution']['counts']) == 5
    assert len(data['charts']['by_skill']['labels']) > 0
    assert len(data['table_data']) > 0
    print(f"[PASS] Default API returned {len(data['table_data'])} records and valid KPI aggregations.")

def test_api_salary_insights_role_filter(client):
    res = client.get('/api/salary_insights?role=Data+Analyst')
    assert res.status_code == 200
    data = res.get_json()
    assert data.get('success') is True
    for item in data['table_data']:
        assert item['job_role'] == 'Data Analyst'
    print(f"[PASS] Role filter 'Data Analyst' returned {len(data['table_data'])} matching records.")

def test_api_salary_insights_location_filter(client):
    res = client.get('/api/salary_insights?location=Chennai')
    assert res.status_code == 200
    data = res.get_json()
    assert data.get('success') is True
    for item in data['table_data']:
        assert item['location'] == 'Chennai'
    print(f"[PASS] Location filter 'Chennai' returned {len(data['table_data'])} matching records.")

def test_api_salary_insights_keyword_search(client):
    keywords = ['Python', 'SQL', 'React', 'DevOps']
    for kw in keywords:
        res = client.get(f'/api/salary_insights?search={kw}')
        assert res.status_code == 200
        data = res.get_json()
        assert data.get('success') is True
        assert len(data['table_data']) > 0
        print(f"  - Keyword search '{kw}' returned {len(data['table_data'])} records.")
    print("[PASS] Keyword search successfully filtered across role, skill, and location.")

def test_api_salary_insights_sorting(client):
    res_desc = client.get('/api/salary_insights?sort_by=avg_desc')
    data_desc = res_desc.get_json()
    avgs = [r['salary_avg'] for r in data_desc['table_data']]
    assert avgs == sorted(avgs, reverse=True)

    res_asc = client.get('/api/salary_insights?sort_by=avg_asc')
    data_asc = res_asc.get_json()
    avgs_asc = [r['salary_avg'] for r in data_asc['table_data']]
    assert avgs_asc == sorted(avgs_asc)

    print("[PASS] Server-side table sorting verified for avg_desc and avg_asc.")

if __name__ == '__main__':
    pytest.main(['-s', __file__])
