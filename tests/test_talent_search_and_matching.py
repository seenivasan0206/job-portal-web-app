# -*- coding: utf-8 -*-
"""
Test Suite for Talent Search & Dynamic Candidate Job Matching:
1. Pure calculation scoring engine (calculate_candidate_job_match) across skills, semantics, experience, education, and location.
2. Defaulting behavior for unspecified job requirements (skills, experience, education).
3. Candidate job match cache table (candidate_job_matches) population and refreshing.
4. Recruiter Jobs API (/api/recruiter/jobs) with auth and employer scoping.
5. Talent Search API (/api/recruiter/talent_search) with dynamic ranking, IDOR prevention, and secondary filtering.
6. Recruiter Candidate Detail API (/api/recruiter/candidate/<id>) with auth and profile inspection.
7. Template rendering and interactive controls in recruiter_candidates.html.
"""
import os
import sys
import json
import pytest
from app import app, db_cursor, calculate_candidate_job_match, refresh_job_candidate_matches


@pytest.fixture
def client():
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    with app.test_client() as client:
        yield client


@pytest.fixture
def talent_test_data(client):
    """Sets up test employers, jobs, and candidates with diverse skillsets and experience."""
    with db_cursor() as cursor:
        # 1. Primary Employer
        cursor.execute("SELECT id FROM employee WHERE email = 'talent_emp_alpha@example.com'")
        emp_row = cursor.fetchone()
        if not emp_row:
            cursor.execute("""
                INSERT INTO employee (company_name, email, password, mobile)
                VALUES ('Alpha Software Corp', 'talent_emp_alpha@example.com', 'hashedpwd', '9811122233')
            """)
            emp_id = cursor.lastrowid
        else:
            emp_id = emp_row['id']

        # 2. Secondary Employer (for IDOR tests)
        cursor.execute("SELECT id FROM employee WHERE email = 'talent_emp_beta@example.com'")
        other_emp_row = cursor.fetchone()
        if not other_emp_row:
            cursor.execute("""
                INSERT INTO employee (company_name, email, password, mobile)
                VALUES ('Beta Technologies', 'talent_emp_beta@example.com', 'hashedpwd', '9811122234')
            """)
            other_emp_id = cursor.lastrowid
        else:
            other_emp_id = other_emp_row['id']

        # 3. Candidate 1: High match Python/Django developer in Bengaluru
        cursor.execute("SELECT id FROM user WHERE email = 'python_expert@example.com'")
        cand1_row = cursor.fetchone()
        if not cand1_row:
            cursor.execute("""
                INSERT INTO user (name, email, password, mobile, headline, skills, experience, location)
                VALUES ('Pooja Sharma', 'python_expert@example.com', 'hashedpwd', '9988776655', 
                        'Lead Python Engineer | Django & FastApi', 'Python, Django, FastAPI, PostgreSQL, Redis, Docker', 4, 'Bengaluru')
            """)
            cand1_id = cursor.lastrowid
        else:
            cand1_id = cand1_row['id']

        # 4. Candidate 2: Mid-level JavaScript/React developer in Mumbai
        cursor.execute("SELECT id FROM user WHERE email = 'frontend_dev@example.com'")
        cand2_row = cursor.fetchone()
        if not cand2_row:
            cursor.execute("""
                INSERT INTO user (name, email, password, mobile, headline, skills, experience, location)
                VALUES ('Rahul Mehta', 'frontend_dev@example.com', 'hashedpwd', '9988776656', 
                        'Frontend Developer | React & TypeScript', 'JavaScript, React, Redux, CSS, HTML', 2, 'Mumbai')
            """)
            cand2_id = cursor.lastrowid
        else:
            cand2_id = cand2_row['id']

        # 5. Candidate 3: Full Stack Engineer in Remote with relocation
        cursor.execute("SELECT id FROM user WHERE email = 'fullstack_dev@example.com'")
        cand3_row = cursor.fetchone()
        if not cand3_row:
            cursor.execute("""
                INSERT INTO user (name, email, password, mobile, headline, skills, experience, location)
                VALUES ('Sneha Iyer', 'fullstack_dev@example.com', 'hashedpwd', '9988776657', 
                        'Full Stack Engineer | Python & React', 'Python, React, Django, PostgreSQL, Git', 3, 'Remote')
            """)
            cand3_id = cursor.lastrowid
        else:
            cand3_id = cand3_row['id']

        # Populate candidate profiles & preferences
        for cid, headline, exp_years in [(cand1_id, 'Lead Python Engineer', 4), (cand2_id, 'Frontend Developer', 2), (cand3_id, 'Full Stack Engineer', 3)]:
            cursor.execute("SELECT user_id FROM candidate_profile WHERE user_id = %s", (cid,))
            if not cursor.fetchone():
                cursor.execute("""
                    INSERT INTO candidate_profile (user_id, headline, summary)
                    VALUES (%s, %s, 'Proven track record in agile software delivery and full stack development.')
                """, (cid, headline))

            cursor.execute("SELECT user_id FROM candidate_preferences WHERE user_id = %s", (cid,))
            if not cursor.fetchone():
                cursor.execute("""
                    INSERT INTO candidate_preferences (user_id, open_to_relocate, notice_period)
                    VALUES (%s, TRUE, '15 Days')
                """, (cid,))

        # Add employment records
        cursor.execute("SELECT id FROM employment WHERE user_id = %s", (cand1_id,))
        if not cursor.fetchone():
            cursor.execute("""
                INSERT INTO employment (user_id, company_name, job_title, start_date, end_date, is_current, skills_used)
                VALUES (%s, 'Alpha Corp', 'Python Developer', '2021-01-01', '2025-01-01', TRUE, 'Python, Django, PostgreSQL')
            """, (cand1_id,))

        cursor.execute("SELECT id FROM employment WHERE user_id = %s", (cand2_id,))
        if not cursor.fetchone():
            cursor.execute("""
                INSERT INTO employment (user_id, company_name, job_title, start_date, end_date, is_current, skills_used)
                VALUES (%s, 'Beta Labs', 'React Developer', '2023-01-01', '2025-01-01', TRUE, 'React, JavaScript')
            """, (cand2_id,))

        # Add education records
        cursor.execute("SELECT id FROM education WHERE user_id = %s", (cand1_id,))
        if not cursor.fetchone():
            cursor.execute("""
                INSERT INTO education (user_id, education_level, course_degree, specialization, institute, year_of_passing)
                VALUES (%s, 'Graduation', 'B.Tech', 'Computer Science and Engineering', 'NIT Karnataka', 2020)
            """, (cand1_id,))

        # 6. Primary Job (Python Role belonging to emp_id)
        cursor.execute("SELECT id FROM jobs WHERE employer_id = %s AND title = 'Senior Python Developer'", (emp_id,))
        job_row = cursor.fetchone()
        if not job_row:
            cursor.execute("""
                INSERT INTO jobs (employer_id, title, category, job_type, experience, location, skills, description, company_name)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (emp_id, 'Senior Python Developer', 'IT & Software', 'Full-time', '3', 'Bengaluru',
                  'Python, Django, PostgreSQL, Redis',
                  'We are looking for a Senior Python Developer with strong Django, PostgreSQL, and backend API design skills. Degree in Computer Science preferred.',
                  'Alpha Software Corp'))
            job_id = cursor.lastrowid
        else:
            job_id = job_row['id']

        # 7. Other Job belonging to other_emp_id
        cursor.execute("SELECT id FROM jobs WHERE employer_id = %s AND title = 'Java Architect'", (other_emp_id,))
        other_job_row = cursor.fetchone()
        if not other_job_row:
            cursor.execute("""
                INSERT INTO jobs (employer_id, title, category, job_type, experience, location, skills, description, company_name)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (other_emp_id, 'Java Architect', 'IT & Software', 'Full-time', '5', 'Delhi',
                  'Java, Spring Boot, Microservices',
                  'Looking for a Java Architect.',
                  'Beta Technologies'))
            other_job_id = cursor.lastrowid
        else:
            other_job_id = other_job_row['id']

    return {
        'emp_id': emp_id,
        'other_emp_id': other_emp_id,
        'cand1_id': cand1_id,
        'cand2_id': cand2_id,
        'cand3_id': cand3_id,
        'job_id': job_id,
        'other_job_id': other_job_id
    }


# ==================================================
# UNIT TESTS: MATCH SCORING ENGINE
# ==================================================

def test_calculate_candidate_job_match_scoring_weights():
    """Validates calculate_candidate_job_match weighted scoring calculation."""
    job = {
        'id': 10,
        'title': 'Senior Python Developer',
        'skills': 'Python, Django, PostgreSQL, Redis',
        'experience': '3',
        'location': 'Bengaluru',
        'description': 'Senior Python developer with strong Django and database design experience. Degree in Computer Science.'
    }

    # Candidate with perfect match: 4/4 skills, 4 yrs exp (req 3), CS degree, Bengaluru
    candidate_perfect = {
        'id': 101,
        'user_id': 101,
        'skills': 'Python, Django, PostgreSQL, Redis, Docker',
        'experience_years': 4.0,
        'location': 'Bengaluru',
        'open_to_relocate': True,
        'education_history': [{'course_degree': 'B.Tech', 'specialization': 'Computer Science', 'education_level': 'Graduation'}],
        'employment_history': [{'job_title': 'Senior Python Developer', 'company_name': 'Tech Corp', 'description': 'Developed Python Django APIs'}],
        'headline': 'Senior Python Developer',
        'summary': 'Senior Python and Django developer with database optimization background.'
    }

    result = calculate_candidate_job_match(job, candidate_perfect)
    assert result['skill_score'] == 100.0
    assert len(result['matched_skills']) == 4
    assert len(result['missing_skills']) == 0
    assert result['experience_score'] == 100.0
    assert result['location_score'] == 100.0
    assert result['education_score'] >= 80.0
    assert result['semantic_score'] > 50.0
    assert result['final_score'] >= 80.0


def test_calculate_candidate_job_match_missing_skills():
    """Validates calculation when candidate is missing half of the required skills."""
    job = {
        'id': 11,
        'title': 'Full Stack Developer',
        'skills': 'Python, React, Docker, Kubernetes',
        'experience': '2',
        'location': 'Remote',
        'description': 'Full stack developer building microservices in Python and React.'
    }

    # Candidate only knows Python and React (2 out of 4)
    candidate_partial = {
        'id': 102,
        'user_id': 102,
        'skills': 'Python, React, CSS',
        'experience_years': 2.0,
        'location': 'Remote',
        'open_to_relocate': False,
        'education_history': [],
        'employment_history': [],
        'headline': 'Frontend & Python Dev',
        'summary': 'Working with Python and React.'
    }

    result = calculate_candidate_job_match(job, candidate_partial)
    assert result['skill_score'] == 50.0
    assert 'Python' in result['matched_skills']
    assert 'React' in result['matched_skills']
    assert 'Docker' in result['missing_skills']
    assert 'Kubernetes' in result['missing_skills']


def test_calculate_candidate_job_match_defaults():
    """Validates 100% defaults when job requirements (skills, exp, edu) are unspecified."""
    job_empty = {
        'id': 12,
        'title': 'General Software Associate',
        'skills': '',  # No required skills specified
        'experience': '0',  # Fresher/no experience required
        'location': 'Any',
        'description': 'Join our team as a software associate.'
    }

    candidate = {
        'id': 103,
        'user_id': 103,
        'skills': 'JavaScript, HTML',
        'experience_years': 0.0,
        'location': 'Bengaluru',
        'open_to_relocate': True,
        'education_history': [],
        'employment_history': [],
        'headline': 'Junior Developer',
        'summary': 'Junior software developer.'
    }

    result = calculate_candidate_job_match(job_empty, candidate)
    assert result['skill_score'] == 100.0
    assert result['experience_score'] == 100.0
    assert result['education_score'] == 100.0
    assert result['location_score'] == 100.0
    assert result['final_score'] >= 80.0


# ==================================================
# API ENDPOINT & AUTH SECURITY TESTS
# ==================================================

def test_talent_search_apis_unauthorized(client):
    """Verifies all recruiter talent search endpoints return 401 when unauthenticated."""
    res1 = client.get('/api/recruiter/jobs')
    assert res1.status_code == 401

    res2 = client.get('/api/recruiter/talent_search')
    assert res2.status_code == 401

    res3 = client.get('/api/recruiter/candidate/1')
    assert res3.status_code == 401


def test_recruiter_jobs_api_scoped_to_employer(client, talent_test_data):
    """Verifies /api/recruiter/jobs returns only the active jobs belonging to the logged-in employer."""
    emp_id = talent_test_data['emp_id']
    job_id = talent_test_data['job_id']
    other_job_id = talent_test_data['other_job_id']

    with client.session_transaction() as sess:
        sess['employer_id'] = emp_id
        sess['role'] = 'employer'

    res = client.get('/api/recruiter/jobs')
    assert res.status_code == 200
    data = res.get_json()
    assert data['success'] is True
    assert 'jobs' in data
    job_ids = [j['id'] for j in data['jobs']]
    assert job_id in job_ids
    assert other_job_id not in job_ids


def test_talent_search_api_idor_prevention(client, talent_test_data):
    """Verifies an employer cannot query talent matching for another employer's job (IDOR prevention)."""
    other_emp_id = talent_test_data['other_emp_id']
    primary_job_id = talent_test_data['job_id']

    with client.session_transaction() as sess:
        sess['employer_id'] = other_emp_id
        sess['role'] = 'employer'

    res = client.get(f'/api/recruiter/talent_search?job_id={primary_job_id}')
    assert res.status_code == 403
    data = res.get_json()
    assert data['success'] is False


def test_talent_search_api_ranking_and_caching(client, talent_test_data):
    """Verifies /api/recruiter/talent_search populates cache and returns candidates ordered by match score."""
    emp_id = talent_test_data['emp_id']
    job_id = talent_test_data['job_id']
    cand1_id = talent_test_data['cand1_id']

    with client.session_transaction() as sess:
        sess['employer_id'] = emp_id
        sess['role'] = 'employer'

    res = client.get(f'/api/recruiter/talent_search?job_id={job_id}&refresh=1')
    assert res.status_code == 200
    data = res.get_json()
    assert data['success'] is True
    assert 'candidates' in data
    assert len(data['candidates']) > 0

    # Verify candidate 1 (Python expert) is ranked at top (#1)
    top_cand = data['candidates'][0]
    assert top_cand['id'] == cand1_id
    assert 'score_breakdown' in top_cand
    assert 'skills' in top_cand['score_breakdown']
    assert 'relevance' in top_cand['score_breakdown']
    assert 'experience' in top_cand['score_breakdown']
    assert 'education' in top_cand['score_breakdown']
    assert 'location' in top_cand['score_breakdown']
    assert top_cand['match_score'].endswith('%')
    assert isinstance(top_cand['matched_skills'], list)
    assert 'Python' in top_cand['matched_skills']

    # Verify candidate_job_matches table has cached rows
    with db_cursor() as cur:
        cur.execute("SELECT COUNT(*) AS cnt FROM candidate_job_matches WHERE job_id = %s", (job_id,))
        count_row = cur.fetchone()
        assert count_row['cnt'] > 0


def test_talent_search_api_secondary_filters(client, talent_test_data):
    """Verifies secondary query, skill, and location filters apply on top of the ranked results."""
    emp_id = talent_test_data['emp_id']
    job_id = talent_test_data['job_id']

    with client.session_transaction() as sess:
        sess['employer_id'] = emp_id
        sess['role'] = 'employer'

    # Filter by skill 'django'
    res_skill = client.get(f'/api/recruiter/talent_search?job_id={job_id}&skills=django')
    assert res_skill.status_code == 200
    candidates_skill = res_skill.get_json()['candidates']
    assert all('django' in c['skills'].lower() or any('django' in s.lower() for s in c['matched_skills']) for c in candidates_skill)

    # Filter by location 'bengaluru'
    res_loc = client.get(f'/api/recruiter/talent_search?job_id={job_id}&location=bengaluru')
    assert res_loc.status_code == 200
    candidates_loc = res_loc.get_json()['candidates']
    assert all('bengaluru' in c['location'].lower() for c in candidates_loc)

    # Filter by name query 'pooja'
    res_query = client.get(f'/api/recruiter/talent_search?job_id={job_id}&query=pooja')
    assert res_query.status_code == 200
    candidates_query = res_query.get_json()['candidates']
    assert len(candidates_query) == 1
    assert 'pooja' in candidates_query[0]['name'].lower()


def test_recruiter_candidate_detail_api(client, talent_test_data):
    """Verifies /api/recruiter/candidate/<id> returns rich candidate profile data for recruiter inspection."""
    emp_id = talent_test_data['emp_id']
    cand1_id = talent_test_data['cand1_id']

    with client.session_transaction() as sess:
        sess['employer_id'] = emp_id
        sess['role'] = 'employer'

    res = client.get(f'/api/recruiter/candidate/{cand1_id}')
    assert res.status_code == 200
    data = res.get_json()
    assert data['success'] is True
    cand = data['candidate']
    assert cand['id'] == cand1_id
    assert cand['name'] == 'Pooja Sharma'
    assert 'Python' in cand['skills']
    assert isinstance(cand['employment'], list)
    assert isinstance(cand['education'], list)

    # 404 for nonexistent candidate
    res_404 = client.get('/api/recruiter/candidate/999999')
    assert res_404.status_code == 404


def test_recruiter_candidates_template_rendering(client, talent_test_data):
    """Verifies /recruiter_candidates HTML page renders required elements and selectors."""
    emp_id = talent_test_data['emp_id']

    with client.session_transaction() as sess:
        sess['employer_id'] = emp_id
        sess['role'] = 'employer'

    res = client.get('/recruiter_candidates')
    assert res.status_code == 200
    html = res.get_data(as_text=True)

    # Check for required selectors and entry point elements
    assert 'id="select-job"' in html
    assert 'id="candidate-search"' in html
    assert '<select id="filter-skills" class="form-select" onchange="searchCandidates()">' in html
    assert '<select id="filter-exp" class="form-select" onchange="searchCandidates()">' in html
    assert '<select id="filter-location" class="form-select" onchange="searchCandidates()">' in html
    assert 'id="candidates-list"' in html
    assert 'id="scheduleInterviewModal"' in html
    assert 'id="candidateProfileModal"' in html
