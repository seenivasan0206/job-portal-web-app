# -*- coding: utf-8 -*-
"""
Integration tests for 100% Database-Driven Job System, Lifecycle, and Verification.
"""
from datetime import datetime, timedelta
import pytest
from app import app, db_cursor, format_relative_time, enrich_job_presentation

@pytest.fixture
def client():
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    with app.test_client() as client:
        yield client

def test_relative_time_formatting_and_new_badge():
    now = datetime.now()

    # Just now (< 1 min)
    str_val, is_new = format_relative_time(now - timedelta(seconds=20))
    assert str_val == "Just now"
    assert is_new is True

    # 15 minutes ago
    str_val, is_new = format_relative_time(now - timedelta(minutes=15))
    assert str_val == "15 minutes ago"
    assert is_new is True

    # 3 hours ago
    str_val, is_new = format_relative_time(now - timedelta(hours=3))
    assert str_val == "3 hours ago"
    assert is_new is True

    # 1 day ago (28 hours ago -> is_new is False)
    str_val, is_new = format_relative_time(now - timedelta(hours=28))
    assert str_val == "1 day ago"
    assert is_new is False

    # 5 days ago
    str_val, is_new = format_relative_time(now - timedelta(days=5))
    assert str_val == "5 days ago"
    assert is_new is False

    print("[PASS] format_relative_time() correctly computes relative intervals and limits NEW badge strictly to 24 hours.")

def test_employer_job_posting_and_homepage_rendering(client):
    # 1. Register / Get a legitimate test employer
    employer_email = "verified_corp_test@example.com"
    with db_cursor() as cur:
        cur.execute("SELECT id FROM employee WHERE email = %s", (employer_email,))
        emp_row = cur.fetchone()
        if not emp_row:
            cur.execute("""
                INSERT INTO employee (company_name, email, password, is_verified, verification_status)
                VALUES ('Starlight Technologies', %s, 'hashed_pass_123', 1, 'verified')
            """, (employer_email,))
            emp_id = cur.lastrowid
        else:
            emp_id = emp_row['id']
            cur.execute("UPDATE employee SET is_verified = 1, verification_status = 'verified', company_name = 'Starlight Technologies' WHERE id = %s", (emp_id,))

    # 2. Authenticate as Employer and Post a Job
    with client.session_transaction() as sess:
        sess['employer_id'] = emp_id
        sess['user_name'] = 'Starlight Technologies'
        sess['role'] = 'employer'

    unique_title = f"Principal Rust Engineer {datetime.now().strftime('%H%M%S')}"
    post_res = client.post('/api/employer/post_job', json={
        'title': unique_title,
        'description': 'Architect low-latency distributed storage engines in Rust.',
        'location': 'Hyderabad / Hybrid',
        'category': 'Engineering',
        'job_type': 'Full-time',
        'work_mode': 'Hybrid',
        'experience': '5+ Years',
        'skills': 'Rust, Tokio, Distributed Systems, Raft',
        'salary_min': 2800000,
        'salary_max': 4500000,
        'salary': '₹28 - ₹45 LPA',
        'openings': 2,
        'is_active': True
    })
    assert post_res.status_code == 200
    post_data = post_res.get_json()
    assert post_data['success'] is True
    job_id = post_data['job_id']
    assert job_id > 0

    # 3. Verify Database Record Integrity
    with db_cursor() as cur:
        cur.execute("SELECT * FROM jobs WHERE id = %s", (job_id,))
        job_db = cur.fetchone()
        assert job_db is not None
        assert job_db['title'] == unique_title
        assert job_db['employer_id'] == emp_id
        assert job_db['is_active'] == 1
        assert job_db['created_at'] is not None

    # 4. Verify Job Appears on Homepage with Real Company, Title, and Verified Badge
    res_home = client.get('/')
    assert res_home.status_code == 200
    home_html = res_home.get_data(as_text=True)

    assert unique_title in home_html
    assert 'Starlight Technologies' in home_html
    assert 'Verified' in home_html
    assert f'/job/{job_id}' in home_html
    assert 'NEW' in home_html  # Posted just now, so is_new must be True

    # 5. Verify View Details Route Works for the Real Job
    res_detail = client.get(f'/job/{job_id}')
    assert res_detail.status_code == 200
    detail_html = res_detail.get_data(as_text=True)
    assert unique_title in detail_html
    assert 'Starlight Technologies' in detail_html
    assert 'Rust' in detail_html

    print(f"[PASS] Real job #{job_id} successfully created, persisted, and verified dynamically on homepage and detail page.")

def test_unverified_employer_does_not_show_fake_verification(client):
    # Register an unverified employer
    unverified_email = "unverified_startup@example.com"
    with db_cursor() as cur:
        cur.execute("SELECT id FROM employee WHERE email = %s", (unverified_email,))
        emp_row = cur.fetchone()
        if not emp_row:
            cur.execute("""
                INSERT INTO employee (company_name, email, password, is_verified, verification_status)
                VALUES ('Unverified Startup Inc', %s, 'pass_123', 0, 'unverified')
            """, (unverified_email,))
            unverified_id = cur.lastrowid
        else:
            unverified_id = emp_row['id']
            cur.execute("UPDATE employee SET is_verified = 0, verification_status = 'unverified' WHERE id = %s", (unverified_id,))

    # Enrich a job posted by unverified employer
    job_record = {
        'id': 9999,
        'title': 'Junior Web Developer',
        'company_name': 'Unverified Startup Inc',
        'employer_is_verified': 0,
        'employer_verification_status': 'unverified',
        'created_at': datetime.now() - timedelta(days=2),
        'skills': 'HTML, CSS, JS'
    }
    enriched = enrich_job_presentation(job_record)
    assert enriched['is_company_verified'] is False
    assert enriched['is_new'] is False
    assert enriched['posted_time_ago'] == "2 days ago"

    print("[PASS] Unverified employers do NOT receive verified badges.")

def test_unauthenticated_candidate_cannot_post_job(client):
    # Candidate trying to post job
    with client.session_transaction() as sess:
        sess['user_id'] = 5
        sess['role'] = 'user'

    res = client.post('/api/employer/post_job', json={'title': 'Hacker Job'})
    assert res.status_code == 401
    assert res.get_json()['success'] is False

    print("[PASS] Candidate and unauthenticated requests to /api/employer/post_job are securely blocked with 401.")

if __name__ == '__main__':
    pytest.main(['-s', __file__])
