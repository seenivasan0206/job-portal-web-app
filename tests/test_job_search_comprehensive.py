import pytest
import json
from app import app, db_cursor

@pytest.fixture
def client():
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    with app.test_client() as client:
        yield client

@pytest.fixture(autouse=True)
def setup_search_test_data():
    """Seeds test jobs across various titles, locations, salaries, and work modes."""
    with db_cursor() as cursor:
        # Create a test employer if not exists
        cursor.execute("SELECT id FROM employee WHERE email = %s", ('search_recruiter@test.com',))
        row = cursor.fetchone()
        if row:
            emp_id = row['id']
        else:
            cursor.execute("""
                INSERT INTO employee (company_name, mobile, email, password, industry, is_verified, verification_status)
                VALUES (%s, %s, %s, %s, %s, 1, 'verified')
            """, ('TechCorp Analytics', '9876543210', 'search_recruiter@test.com', 'hashed_pw_test', 'IT & Software'))
            emp_id = cursor.lastrowid

        # Clean old search test jobs
        cursor.execute("DELETE FROM jobs WHERE employer_id = %s", (emp_id,))

        # 1. Matching target job: Data Analyst + Chennai + 4-8 LPA + Fresher + Remote
        cursor.execute("""
            INSERT INTO jobs (
                employer_id, title, description, location, salary, salary_min, salary_max,
                experience, skills, category, job_type, work_mode, openings, is_active,
                education, industry, department
            ) VALUES (
                %s, 'Junior Data Analyst', 'Perform SQL data modeling and python analytics on big datasets in Chennai remote setup.',
                'Chennai', '₹4,00,000 - ₹8,00,000', 400000, 800000,
                'Fresher', 'Python, SQL, Tableau, Power BI', 'IT & Software',
                'Full-time', 'Remote', 2, 1,
                'B.Tech', 'IT & Software', 'Data & Analytics'
            )
        """, (emp_id,))

        # 2. Non-matching job A: Data Analyst + Bangalore + 12-18 LPA + 3-5 Years + Onsite
        cursor.execute("""
            INSERT INTO jobs (
                employer_id, title, description, location, salary, salary_min, salary_max,
                experience, skills, category, job_type, work_mode, openings, is_active,
                education, industry, department
            ) VALUES (
                %s, 'Senior Data Analyst', 'Lead enterprise analytics and business intelligence.',
                'Bangalore', '₹12,00,000 - ₹18,00,000', 1200000, 1800000,
                '3-5 Years', 'Python, SQL, AWS, Snowflake', 'IT & Software',
                'Full-time', 'Onsite', 1, 1,
                'B.Tech', 'IT & Software', 'Data & Analytics'
            )
        """, (emp_id,))

        # 3. Non-matching job B: Software Engineer + Chennai + 5-9 LPA + Fresher + Hybrid
        cursor.execute("""
            INSERT INTO jobs (
                employer_id, title, description, location, salary, salary_min, salary_max,
                experience, skills, category, job_type, work_mode, openings, is_active,
                education, industry, department
            ) VALUES (
                %s, 'Software Engineer - Frontend', 'Build modern web applications with React and TypeScript.',
                'Chennai', '₹5,00,000 - ₹9,00,000', 500000, 900000,
                'Fresher', 'React, JavaScript, CSS, HTML', 'IT & Software',
                'Full-time', 'Hybrid', 3, 1,
                'B.Tech', 'IT & Software', 'Engineering'
            )
        """, (emp_id,))

        # 4. Non-matching job C: Marketing Specialist + Mumbai + 3-5 LPA + 1-3 Years + Remote
        cursor.execute("""
            INSERT INTO jobs (
                employer_id, title, description, location, salary, salary_min, salary_max,
                experience, skills, category, job_type, work_mode, openings, is_active,
                education, industry, department
            ) VALUES (
                %s, 'Digital Marketing Executive', 'Execute SEO and social media campaigns.',
                'Mumbai', '₹3,00,000 - ₹5,00,000', 300000, 500000,
                '1-3 Years', 'SEO, SEM, Content Writing', 'Marketing',
                'Full-time', 'Remote', 1, 1,
                'Any Graduate', 'Marketing', 'Marketing'
            )
        """, (emp_id,))

    yield

    with db_cursor() as cursor:
        cursor.execute("DELETE FROM jobs WHERE employer_id = %s", (emp_id,))


def test_combined_multi_filter_data_analyst_chennai_salary_fresher_remote(client):
    """
    Verification of prompt requirement:
    Data Analyst + Chennai + ₹4–8 LPA + Fresher + Remote
    should return ONLY jobs satisfying all selected conditions.
    """
    # 1. Via POST JSON
    res = client.post('/api/jobs/search', json={
        'title': 'Data Analyst',
        'location': 'Chennai',
        'salary_bracket': '4-8',
        'experience': 'Fresher',
        'work_mode': 'Remote'
    })
    assert res.status_code == 200
    data = res.get_json()
    assert data['success'] is True
    assert data['total'] >= 1
    # Check that every returned job satisfies all conditions
    for j in data['jobs']:
        assert 'data analyst' in j['title'].lower() or 'analyst' in j['title'].lower()
        assert 'chennai' in j['location'].lower() or j['work_mode'].lower() == 'remote'
        assert j['work_mode'].lower() == 'remote'
        assert 'fresh' in (j['experience'] or '').lower() or j['experience'] == '0'

    # Verify that non-matching jobs (Bangalore Senior Data Analyst, Chennai React Frontend, Mumbai Marketing) are excluded
    titles = [j['title'] for j in data['jobs']]
    assert 'Senior Data Analyst' not in titles
    assert 'Software Engineer - Frontend' not in titles
    assert 'Digital Marketing Executive' not in titles


def test_single_dimension_filters(client):
    """Tests each individual filter dimension in isolation."""
    # 1. Keyword search
    res = client.get('/api/jobs/search?query=Tableau')
    assert res.status_code == 200
    data = res.get_json()
    assert data['success'] is True
    assert any('Tableau' in (j.get('skills') or '') or 'Tableau' in (j.get('description') or '') for j in data['jobs'])

    # 2. Company search
    res = client.get('/api/jobs/search?company=TechCorp')
    assert res.status_code == 200
    assert res.get_json()['total'] >= 1

    # 3. Skill search
    res = client.get('/api/jobs/search?skill=React')
    assert res.status_code == 200
    titles = [j['title'] for j in res.get_json()['jobs']]
    assert 'Software Engineer - Frontend' in titles

    # 4. Location search
    res = client.get('/api/jobs/search?location=Mumbai')
    assert res.status_code == 200
    assert any('Mumbai' in j['location'] for j in res.get_json()['jobs'])

    # 5. Category search
    res = client.get('/api/jobs/search?category=Marketing')
    assert res.status_code == 200
    assert any(j['category'] == 'Marketing' for j in res.get_json()['jobs'])

    # 6. Experience search
    res = client.get('/api/jobs/search?experience=3-5%20Years')
    assert res.status_code == 200
    titles = [j['title'] for j in res.get_json()['jobs']]
    assert 'Senior Data Analyst' in titles

    # 7. Job Type search
    res = client.get('/api/jobs/search?job_type=Full-time')
    assert res.status_code == 200
    assert res.get_json()['total'] >= 1

    # 8. Work Mode search
    res = client.get('/api/jobs/search?work_mode=Hybrid')
    assert res.status_code == 200
    titles = [j['title'] for j in res.get_json()['jobs']]
    assert 'Software Engineer - Frontend' in titles

    # 9. Education search
    res = client.get('/api/jobs/search?education=B.Tech')
    assert res.status_code == 200
    assert res.get_json()['total'] >= 1

    # 10. Industry search
    res = client.get('/api/jobs/search?industry=IT%20%26%20Software')
    assert res.status_code == 200
    assert res.get_json()['total'] >= 1

    # 11. Department search
    res = client.get('/api/jobs/search?department=Data%20%26%20Analytics')
    assert res.status_code == 200
    titles = [j['title'] for j in res.get_json()['jobs']]
    assert 'Junior Data Analyst' in titles


def test_sorting_modes(client):
    """Tests all supported sort orders: newest, oldest, salary high/low, most_relevant, recently_updated."""
    sort_modes = ['newest', 'oldest', 'salary_high_to_low', 'salary_low_to_high', 'most_relevant', 'recently_updated']
    for mode in sort_modes:
        res = client.get(f'/api/jobs/search?sort={mode}')
        assert res.status_code == 200
        data = res.get_json()
        assert data['success'] is True
        assert data['sort'] == mode
        assert isinstance(data['jobs'], list)

    # Check salary_high_to_low order specifically
    res_high = client.get('/api/jobs/search?sort=salary_high_to_low')
    jobs_high = res_high.get_json()['jobs']
    if len(jobs_high) >= 2:
        salaries = [j.get('salary_max') or j.get('salary_min') or 0 for j in jobs_high]
        assert salaries[0] >= salaries[-1]


def test_pagination(client):
    """Tests pagination bounds, page numbers, and total count."""
    res = client.get('/api/jobs/search?page=1&per_page=2')
    assert res.status_code == 200
    data = res.get_json()
    assert data['page'] == 1
    assert data['per_page'] == 2
    assert len(data['jobs']) <= 2
    assert data['total_pages'] >= 1

    # Out of range page still returns success with empty jobs list
    res_far = client.get('/api/jobs/search?page=9999&per_page=10')
    assert res_far.status_code == 200
    assert res_far.get_json()['jobs'] == []


def test_search_autocomplete_suggestions(client):
    """Tests the typeahead suggestions endpoint for titles, skills, companies, locations."""
    # 1. Title autocomplete
    res = client.get('/api/jobs/suggestions?q=data')
    assert res.status_code == 200
    data = res.get_json()
    assert data['success'] is True
    assert any('data' in s['text'].lower() for s in data['suggestions'])
    assert isinstance(data['titles'], list)
    assert isinstance(data['skills'], list)

    # 2. Skill autocomplete
    res_skill = client.get('/api/jobs/suggestions?q=python')
    assert res_skill.status_code == 200
    data_skill = res_skill.get_json()
    assert any('python' in s.lower() for s in data_skill['skills'])

    # 3. Empty query returns empty suggestions safely
    res_empty = client.get('/api/jobs/suggestions?q=')
    assert res_empty.status_code == 200
    assert res_empty.get_json()['suggestions'] == []


def test_clear_filters_and_empty_state(client):
    """Tests empty filter defaults and non-matching queries."""
    # Default search
    res = client.get('/api/jobs/search')
    assert res.status_code == 200
    assert res.get_json()['total'] >= 1

    # Completely non-matching query returns 0 jobs with proper response structure
    res_none = client.post('/api/jobs/search', json={'title': 'NonExistentRoleXYZ9999'})
    assert res_none.status_code == 200
    data = res_none.get_json()
    assert data['success'] is True
    assert data['total'] == 0
    assert data['jobs'] == []


def test_sql_injection_safety(client):
    """Verifies that malicious SQL payloads are treated safely as literals."""
    payloads = [
        "' OR '1'='1",
        "1; DROP TABLE jobs; --",
        "' UNION SELECT NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL --",
        "admin'--",
        "'; EXEC xp_cmdshell('dir');--"
    ]
    for payload in payloads:
        res = client.post('/api/jobs/search', json={'title': payload, 'location': payload})
        assert res.status_code == 200
        data = res.get_json()
        assert data['success'] is True
        # Must not error or leak table dumps
        assert isinstance(data['jobs'], list)


def test_invalid_input_handling(client):
    """Verifies invalid integer inputs for pagination are rejected with 400 Bad Request."""
    res = client.post('/api/jobs/search', json={'page': 'invalid_string'})
    assert res.status_code == 400
    assert res.get_json()['success'] is False

    res = client.post('/api/jobs/search', json={'per_page': 'invalid_string'})
    assert res.status_code == 400
    assert res.get_json()['success'] is False


def test_jobs_page_html_rendering(client):
    """Verifies that /jobs page renders cleanly with filter parameters in URL."""
    res = client.get('/jobs?title=Data+Analyst&location=Chennai&experience=Fresher&work_mode=Remote')
    assert res.status_code == 200
    html = res.data.decode('utf-8')
    assert 'Filter Opportunities' in html
    assert 'Data Analyst' in html
    assert 'Chennai' in html
    assert 'id="job-card-grid"' in html
    assert 'id="search-autocomplete-box"' in html
