# -*- coding: utf-8 -*-
"""
Tests for candidate_preferences schema fix:
- Verifies init_db() executes cleanly without syntax errors
- Verifies current_job_role column name in candidate_preferences
- Verifies preference updates with current_job_role and legacy current_role
"""
import pytest
from app import app, init_db, db_cursor, evaluate_candidate_profile_completeness


def test_init_db_runs_without_exception():
    """Verify that init_db() runs to completion without raising any syntax or execution errors."""
    try:
        init_db()
        success = True
    except Exception as e:
        pytest.fail(f"init_db() raised unexpected exception: {e}")
    assert success is True


def test_candidate_preferences_table_schema():
    """Verify candidate_preferences table schema uses current_job_role instead of reserved keyword current_role."""
    with db_cursor() as cur:
        cur.execute("DESCRIBE candidate_preferences")
        columns = [row['Field'] for row in cur.fetchall()]
    assert 'current_job_role' in columns, f"current_job_role missing from candidate_preferences: {columns}"
    assert 'current_industry' in columns
    assert 'desired_job_type' in columns


def get_csrf(test_client):
    res = test_client.get('/api/csrf_token')
    return res.get_json().get('csrf_token', '')


def test_candidate_preferences_api_with_current_job_role(client):
    """Verify candidate preferences update API using current_job_role."""
    # Create test user
    with db_cursor() as cur:
        cur.execute("INSERT INTO user (name, email, password) VALUES (%s, %s, %s) ON DUPLICATE KEY UPDATE id=LAST_INSERT_ID(id)",
                    ('Pref Test User', 'preftest@hirevolt.com', 'hashedpass'))
        cur.execute("SELECT id FROM user WHERE email = 'preftest@hirevolt.com'")
        user_id = cur.fetchone()['id']

    with client.session_transaction() as sess:
        sess['user_id'] = user_id
        sess['role'] = 'candidate'
        sess['name'] = 'Pref Test User'

    token = get_csrf(client)

    # Save preferences with current_job_role
    payload = {
        'current_industry': 'Information Technology',
        'current_job_role': 'Full Stack Developer',
        'desired_job_type': 'Full Time',
        'current_ctc': '12 LPA',
        'expected_ctc': '18 LPA',
        'notice_period': '30 Days'
    }
    res = client.post('/api/candidate/profile/preferences', json=payload, headers={'X-CSRFToken': token})
    assert res.status_code == 200
    data = res.get_json()
    assert data.get('success') is True

    # Check DB
    with db_cursor() as cur:
        cur.execute("SELECT * FROM candidate_preferences WHERE user_id = %s", (user_id,))
        row = cur.fetchone()
    assert row is not None
    assert row['current_job_role'] == 'Full Stack Developer'
    assert row['current_industry'] == 'Information Technology'


def test_candidate_preferences_api_with_legacy_current_role(client):
    """Verify backward compatibility when legacy payload sends current_role."""
    with db_cursor() as cur:
        cur.execute("SELECT id FROM user WHERE email = 'preftest@hirevolt.com'")
        user_id = cur.fetchone()['id']

    with client.session_transaction() as sess:
        sess['user_id'] = user_id
        sess['role'] = 'candidate'

    token = get_csrf(client)

    payload = {
        'current_industry': 'Finance',
        'current_role': 'Senior Backend Engineer',
        'desired_job_type': 'Remote',
    }
    res = client.post('/api/candidate/profile/preferences', json=payload, headers={'X-CSRFToken': token})
    assert res.status_code == 200
    assert res.get_json().get('success') is True

    with db_cursor() as cur:
        cur.execute("SELECT current_job_role FROM candidate_preferences WHERE user_id = %s", (user_id,))
        row = cur.fetchone()
    assert row['current_job_role'] == 'Senior Backend Engineer'


def test_candidate_profile_js_contains_current_job_role():
    """Verify static/js/candidate-profile.js references current_job_role."""
    with open('static/js/candidate-profile.js', 'r', encoding='utf-8') as f:
        js_code = f.read()
    assert 'current_job_role' in js_code
    assert '["current_job_role", "Role"]' in js_code


def test_all_candidate_profile_tables_exist():
    """Verify all 20 candidate profile extension tables exist in the database."""
    expected_tables = [
        'candidate_personal_details',
        'candidate_preferences',
        'candidate_profile_summary',
        'key_skills',
        'employment',
        'education',
        'it_skills',
        'internships',
        'projects',
        'online_profiles',
        'work_samples',
        'certifications',
        'publications',
        'presentations',
        'patents',
        'competitive_exams',
        'academic_achievements',
        'languages',
        'preferred_locations',
        'job_alerts',
        'job_alerts_sent',
        'resume_analyses',
    ]
    with db_cursor() as cur:
        cur.execute("SHOW TABLES")
        existing_tables = {list(row.values())[0] for row in cur.fetchall()}

    missing_tables = [t for t in expected_tables if t not in existing_tables]
    assert not missing_tables, f"Missing candidate profile tables: {missing_tables}"

