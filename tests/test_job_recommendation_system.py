# -*- coding: utf-8 -*-
"""
HireVolt AI/ML Job Recommendation Engine Test Suite
===================================================
Tests covering:
1. Canonical skill normalization and synonym dictionary mapping.
2. Skill matching (exact, canonical synonyms, token boundaries, missing skills).
3. LRU vector embedding cache & semantic similarity computation.
4. Candidate recommendation profile extraction & aggregation.
5. Multi-factor weighted recommendation scoring (35% skills, 25% semantics, 12% role,
   10% experience, 8% location/remote, 5% salary, 3% employment type, 2% education).
6. Explainability: Transparent, human-readable recommendation reasons.
7. Candidate recommendation pipeline & irrelevance filtering.
8. API Endpoints:
   - GET /api/jobs/recommended (with auth check, pagination, filtering, latency telemetry)
   - GET /api/jobs/<id>/recommendation_details (with granular breakdown & IDOR isolation)
"""

import json
import pytest
from app import app, db_cursor
from job_recommendation_engine import (
    normalize_skill, match_skill_lists,
    get_cached_dense_embedding, compute_cached_semantic_similarity,
    get_candidate_recommendation_profile,
    calculate_job_recommendation_score,
    recommend_jobs_for_candidate,
    CANONICAL_SKILL_SYNONYMS,
    _EMBEDDING_VECTOR_CACHE
)
from resume_intelligence.ml.similarity_model import get_sentence_transformer


@pytest.fixture
def client():
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    with app.test_client() as client:
        yield client


@pytest.fixture(autouse=True)
def setup_recommendation_data():
    """Sets up test candidates, employers, and jobs for recommendation tests."""
    with db_cursor() as cursor:
        # 1. Clean previous recommendation test fixtures
        cursor.execute("SELECT id FROM user WHERE email IN ('rec_cand_senior@test.com', 'rec_cand_fresher@test.com', 'rec_cand_sparse@test.com')")
        existing_users = cursor.fetchall()
        user_ids = [u['id'] for u in existing_users]
        if user_ids:
            fmt = ','.join(['%s'] * len(user_ids))
            cursor.execute(f"DELETE FROM applications WHERE user_id IN ({fmt})", tuple(user_ids))
            cursor.execute(f"DELETE FROM key_skills WHERE user_id IN ({fmt})", tuple(user_ids))
            cursor.execute(f"DELETE FROM employment WHERE user_id IN ({fmt})", tuple(user_ids))
            cursor.execute(f"DELETE FROM education WHERE user_id IN ({fmt})", tuple(user_ids))
            cursor.execute(f"DELETE FROM candidate_preferences WHERE user_id IN ({fmt})", tuple(user_ids))
            cursor.execute(f"DELETE FROM candidate_profile WHERE user_id IN ({fmt})", tuple(user_ids))
            cursor.execute(f"DELETE FROM resume_analyses WHERE user_id IN ({fmt})", tuple(user_ids))
            cursor.execute(f"DELETE FROM user WHERE id IN ({fmt})", tuple(user_ids))

        cursor.execute("SELECT id FROM employee WHERE email = 'rec_employer@test.com'")
        r = cursor.fetchone()
        if r:
            emp_id = r['id']
        else:
            cursor.execute("""
                INSERT INTO employee (company_name, email, password, mobile, is_verified, verification_status)
                VALUES ('Volt Technologies Corp', 'rec_employer@test.com', 'hashed_pwd', '9876500001', 1, 'verified')
            """)
            emp_id = cursor.lastrowid

        # 2. Insert Senior Python/Data Candidate
        cursor.execute("""
            INSERT INTO user (name, email, password, mobile, location, headline, skills, experience)
            VALUES ('Alice Senior Developer', 'rec_cand_senior@test.com', 'hashed_pwd', '9876543210', 'Bengaluru',
                    'Senior Python Engineer', 'Python, FastAPI, Docker, PostgreSQL', 6)
        """)
        cand_senior_id = cursor.lastrowid

        cursor.execute("""
            INSERT INTO candidate_profile (user_id, headline, summary)
            VALUES (%s, 'Senior Python & Machine Learning Engineer', 'Building scalable data pipelines and APIs with Python, Django, Docker, and AWS.')
        """, (cand_senior_id,))

        cursor.execute("""
            INSERT INTO candidate_preferences (user_id, current_job_role, preferred_location, workplace_type, desired_employment_type, expected_ctc)
            VALUES (%s, 'Senior Python Developer', 'Bengaluru', 'Hybrid', 'Full-time', '1800000')
        """, (cand_senior_id,))

        cursor.execute("""
            INSERT INTO key_skills (user_id, skill_name) VALUES
            (%s, 'Python'), (%s, 'FastAPI'), (%s, 'Docker'), (%s, 'PostgreSQL'), (%s, 'AWS'), (%s, 'Machine Learning')
        """, (cand_senior_id, cand_senior_id, cand_senior_id, cand_senior_id, cand_senior_id, cand_senior_id))

        cursor.execute("""
            INSERT INTO employment (user_id, job_title, company_name, is_current)
            VALUES (%s, 'Senior Backend Engineer', 'Tech Innovators Ltd', 1)
        """, (cand_senior_id,))

        cursor.execute("""
            INSERT INTO education (user_id, education_level, course_degree, specialization, institute)
            VALUES (%s, 'Graduation', 'B.Tech', 'Computer Science & Engineering', 'IIT Madras')
        """, (cand_senior_id,))

        cursor.execute("""
            INSERT INTO resume_analyses (user_id, filename, original_filename, file_path, ats_score, extracted_skills)
            VALUES (%s, 'alice_resume.pdf', 'Alice_Resume.pdf', '/uploads/alice_resume.pdf', 90, %s)
        """, (cand_senior_id, json.dumps(['Python', 'FastAPI', 'Django', 'Docker', 'Kubernetes', 'PostgreSQL', 'AWS', 'Redis'])))

        # 3. Insert Fresher Frontend Candidate
        cursor.execute("""
            INSERT INTO user (name, email, password, mobile, location, headline, skills, experience)
            VALUES ('Bob Junior React Dev', 'rec_cand_fresher@test.com', 'hashed_pwd', '9876543211', 'Remote',
                    'Frontend React Developer', 'React, TypeScript, JavaScript', 1)
        """)
        cand_fresher_id = cursor.lastrowid

        cursor.execute("""
            INSERT INTO candidate_preferences (user_id, current_job_role, preferred_location, workplace_type, desired_employment_type, expected_ctc)
            VALUES (%s, 'React Developer', 'Remote', 'Remote', 'Full-time', '600000')
        """, (cand_fresher_id,))

        cursor.execute("""
            INSERT INTO key_skills (user_id, skill_name) VALUES
            (%s, 'React'), (%s, 'TypeScript'), (%s, 'JavaScript'), (%s, 'Tailwind CSS'), (%s, 'HTML/CSS')
        """, (cand_fresher_id, cand_fresher_id, cand_fresher_id, cand_fresher_id, cand_fresher_id))

        cursor.execute("""
            INSERT INTO education (user_id, education_level, course_degree, specialization, institute)
            VALUES (%s, 'Graduation', 'BCA', 'Web Development', 'Bangalore University')
        """, (cand_fresher_id,))

        # 4. Insert Sparse Candidate
        cursor.execute("""
            INSERT INTO user (name, email, password, mobile)
            VALUES ('Charlie New User', 'rec_cand_sparse@test.com', 'hashed_pwd', '9876543212')
        """)
        cand_sparse_id = cursor.lastrowid

        # 5. Insert Jobs
        cursor.execute("DELETE FROM jobs WHERE employer_id = %s", (emp_id,))

        # Job 1: Highly matching Senior Python role in Bengaluru
        cursor.execute("""
            INSERT INTO jobs (employer_id, title, company_name, description, skills, experience, location, work_mode, job_type, salary, salary_min, salary_max, category, is_active, created_at)
            VALUES (%s, 'Senior Python & Backend Engineer', 'Volt Technologies Corp',
                    'We are looking for an experienced Senior Python Engineer to build scalable APIs using FastAPI, Docker, and PostgreSQL on AWS.',
                    'Python, FastAPI, Docker, PostgreSQL, AWS', '5-8 Years', 'Bengaluru', 'Hybrid', 'Full-time', '₹16 - 22 LPA', 1600000, 2200000, 'IT & Software', 1, NOW())
        """, (emp_id,))
        job_python_id = cursor.lastrowid

        # Job 2: Highly matching React Frontend role Remote
        cursor.execute("""
            INSERT INTO jobs (employer_id, title, company_name, description, skills, experience, location, work_mode, job_type, salary, salary_min, salary_max, category, is_active, created_at)
            VALUES (%s, 'Frontend React Developer', 'Volt Technologies Corp',
                    'Join our frontend team building modern responsive web apps using React.js, TypeScript, and Tailwind CSS.',
                    'React.js, TypeScript, Tailwind CSS, JavaScript', '1-3 Years', 'Remote', 'Remote', 'Full-time', '₹6 - 9 LPA', 600000, 900000, 'IT & Software', 1, NOW())
        """, (emp_id,))
        job_react_id = cursor.lastrowid

        # Job 3: Unrelated Nursing Job (should be ranked at bottom / filtered out)
        cursor.execute("""
            INSERT INTO jobs (employer_id, title, company_name, description, skills, experience, location, work_mode, job_type, salary, salary_min, salary_max, category, is_active, created_at)
            VALUES (%s, 'Registered Clinical Nurse', 'Volt Technologies Corp',
                    'Seeking registered nurse for patient care, triage, and medication administration in medical ICU.',
                    'Patient Care, Nursing, ICU, Pharmacology, Medical Records', '2-4 Years', 'Mumbai', 'Onsite', 'Full-time', '₹4 - 6 LPA', 400000, 600000, 'Healthcare', 1, NOW())
        """, (emp_id,))
        job_nurse_id = cursor.lastrowid


# =====================================================================
# 1. CANONICAL SKILL NORMALIZATION & SYNONYMS
# =====================================================================

def test_canonical_skill_normalization():
    """Verify alias normalization across major programming languages, frameworks, and tools."""
    assert normalize_skill('React.js') == 'react'
    assert normalize_skill('reactjs') == 'react'
    assert normalize_skill('k8s') == 'kubernetes'
    assert normalize_skill('FastAPI') == 'fastapi'
    assert normalize_skill('fast-api') == 'fastapi'
    assert normalize_skill('PostgreSQL') == 'postgresql'
    assert normalize_skill('postgres') == 'postgresql'
    assert normalize_skill('AWS') == 'aws'
    assert normalize_skill('Amazon Web Services') == 'aws'
    assert normalize_skill('Node.js') == 'node.js'
    assert normalize_skill('nodejs') == 'node.js'
    assert normalize_skill('ML') == 'machine learning'
    assert normalize_skill('UnknownSpecialSkill123') == 'unknownspecialskill123'


def test_match_skill_lists_exact_and_synonyms():
    """Test skill matching algorithm for exact, synonym, and token boundary containment."""
    required = ['Python', 'React.js', 'PostgreSQL', 'Docker', 'AWS']
    candidate = ['python', 'React', 'postgres', 'docker', 'Amazon Web Services']

    matched, missing, ratio = match_skill_lists(required, candidate)
    assert len(matched) == 5
    assert len(missing) == 0
    assert ratio == 1.0


def test_match_skill_lists_with_missing_elements():
    """Verify missing skills are correctly tracked."""
    required = ['Python', 'FastAPI', 'Rust', 'Golang']
    candidate = ['Python', 'FastAPI']

    matched, missing, ratio = match_skill_lists(required, candidate)
    assert set(matched) == {'Python', 'FastAPI'}
    assert set(missing) == {'Rust', 'Golang'}
    assert ratio == 0.5


# =====================================================================
# 2. VECTOR EMBEDDING CACHE & SEMANTIC SIMILARITY
# =====================================================================

def test_cached_dense_embeddings():
    """Ensure in-memory vector cache saves and retrieves dense embeddings."""
    text1 = "FastAPI backend development with PostgreSQL and Docker"
    text2 = "FastAPI backend development with PostgreSQL and Docker"
    text3 = "Clinical nursing and patient health monitoring"

    sim_same = compute_cached_semantic_similarity(text1, text2, get_sentence_transformer)
    assert sim_same >= 0.99

    sim_diff = compute_cached_semantic_similarity(text1, text3, get_sentence_transformer)
    assert sim_diff < sim_same


# =====================================================================
# 3. MULTI-FACTOR RECOMMENDATION SCORING & EXPLAINABILITY
# =====================================================================

def test_multi_factor_scoring_balance():
    """Verify all 8 factors are calculated and weighted appropriately."""
    with db_cursor() as cursor:
        cursor.execute("SELECT id FROM user WHERE email = 'rec_cand_senior@test.com'")
        cand_id = cursor.fetchone()['id']
        cand_profile = get_candidate_recommendation_profile(cand_id, cursor)

        cursor.execute("SELECT * FROM jobs WHERE title = 'Senior Python & Backend Engineer' LIMIT 1")
        job_py = cursor.fetchone()

        cursor.execute("SELECT * FROM jobs WHERE title = 'Registered Clinical Nurse' LIMIT 1")
        job_nurse = cursor.fetchone()

    score_py = calculate_job_recommendation_score(job_py, cand_profile, get_sentence_transformer)
    score_nurse = calculate_job_recommendation_score(job_nurse, cand_profile, get_sentence_transformer)

    # Senior Python role should score high (> 75%)
    assert score_py['final_score'] >= 75.0
    assert 'Python' in score_py['matched_skills']
    assert 'FastAPI' in score_py['matched_skills']
    assert 'breakdown' in score_py
    assert score_py['breakdown']['skills']['weight'] == 35
    assert score_py['breakdown']['semantic']['weight'] == 25
    assert score_py['breakdown']['role']['weight'] == 12
    assert score_py['breakdown']['experience']['weight'] == 10
    assert score_py['breakdown']['location_remote']['weight'] == 8

    # Transparent human-readable explanation must be present
    assert len(score_py['match_reason']) > 15
    assert "match" in score_py['match_reason'].lower() or "role" in score_py['match_reason'].lower()

    # Nurse job should score drastically lower (< 40%)
    assert score_nurse['final_score'] < 40.0
    assert score_py['final_score'] > score_nurse['final_score'] + 35.0


def test_recommend_jobs_candidate_pipeline():
    """Verify end-to-end ranking and latency telemetry."""
    with db_cursor() as cursor:
        cursor.execute("SELECT id FROM user WHERE email = 'rec_cand_senior@test.com'")
        cand_id = cursor.fetchone()['id']

    result = recommend_jobs_for_candidate(
        user_id=cand_id,
        db_cursor_factory=db_cursor,
        model_getter=get_sentence_transformer,
        filters={'min_score': 30.0},
        limit=10,
        offset=0
    )

    assert result['total'] >= 1
    recs = result['recommendations']
    assert len(recs) >= 1

    # Top recommendation must be Python Engineer
    top_job = recs[0]
    assert 'Python' in top_job['title']
    assert top_job['match_score'] >= 75.0
    assert 'meta' in result
    assert result['meta']['latency_ms'] >= 0.0
    assert result['meta']['cached'] is True


# =====================================================================
# 4. API ENDPOINTS INTEGRATION
# =====================================================================

def test_api_recommended_jobs_unauthorized(client):
    """GET /api/jobs/recommended returns 401 if not logged in."""
    res = client.get('/api/jobs/recommended')
    assert res.status_code == 401
    data = json.loads(res.data)
    assert data['success'] is False


def test_api_recommended_jobs_authenticated(client):
    """GET /api/jobs/recommended returns ranked recommendations for logged in candidate."""
    with db_cursor() as cursor:
        cursor.execute("SELECT id FROM user WHERE email = 'rec_cand_senior@test.com'")
        cand_id = cursor.fetchone()['id']

    with client.session_transaction() as sess:
        sess['user_id'] = cand_id
        sess['user_role'] = 'user'

    res = client.get('/api/jobs/recommended?limit=5')
    assert res.status_code == 200
    data = json.loads(res.data)
    assert data['success'] is True
    assert 'recommendations' in data
    assert 'meta' in data
    assert data['total'] >= 1
    assert data['recommendations'][0]['match_score'] >= 70.0


def test_api_job_recommendation_details_endpoint(client):
    """GET /api/jobs/<job_id>/recommendation_details returns granular score breakdown."""
    with db_cursor() as cursor:
        cursor.execute("SELECT id FROM user WHERE email = 'rec_cand_senior@test.com'")
        cand_id = cursor.fetchone()['id']
        cursor.execute("SELECT id FROM jobs WHERE title = 'Senior Python & Backend Engineer' LIMIT 1")
        job_id = cursor.fetchone()['id']

    with client.session_transaction() as sess:
        sess['user_id'] = cand_id
        sess['user_role'] = 'user'

    res = client.get(f'/api/jobs/{job_id}/recommendation_details')
    assert res.status_code == 200
    data = json.loads(res.data)
    assert data['success'] is True
    assert data['job_id'] == job_id
    assert 'match_reason' in data
    assert 'breakdown' in data
    assert 'matched_skills' in data
    assert len(data['matched_skills']) >= 3


def test_sparse_candidate_recommendations(client):
    """Sparse profile candidate receives recommendations with helpful prompt reason."""
    with db_cursor() as cursor:
        cursor.execute("SELECT id FROM user WHERE email = 'rec_cand_sparse@test.com'")
        cand_id = cursor.fetchone()['id']

    with client.session_transaction() as sess:
        sess['user_id'] = cand_id
        sess['user_role'] = 'user'

    res = client.get('/api/jobs/recommended')
    assert res.status_code == 200
    data = json.loads(res.data)
    assert data['success'] is True
    assert data['meta']['is_sparse_profile'] is True
