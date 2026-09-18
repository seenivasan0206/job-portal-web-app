# -*- coding: utf-8 -*-
"""
Tests for GDPR data export endpoint (/api/user/export_data):
- Verifies authentication requirement (401 for unauthenticated)
- Verifies successful export data structure for authenticated candidates
- Verifies graceful degradation (no 500) if any table is missing or errors
"""
import pytest
from unittest.mock import patch, MagicMock
from app import app, db_cursor


def test_export_data_unauthenticated_returns_401(client):
    """Verify unauthenticated requests are rejected with 401."""
    res = client.get('/api/user/export_data')
    assert res.status_code == 401
    assert res.get_json().get('success') is False


def test_export_data_authenticated_candidate_success(client):
    """Verify authenticated candidate can export all profile and application data."""
    # Ensure test user exists
    with db_cursor() as cur:
        cur.execute(
            "INSERT INTO user (name, email, password) VALUES (%s, %s, %s) "
            "ON DUPLICATE KEY UPDATE id=LAST_INSERT_ID(id)",
            ('GDPR Test User', 'gdpr_test@hirevoltz.com', 'hashedpassword')
        )
        cur.execute("SELECT id FROM user WHERE email = 'gdpr_test@hirevoltz.com'")
        user_id = cur.fetchone()['id']

    with client.session_transaction() as sess:
        sess['user_id'] = user_id
        sess['role'] = 'candidate'
        sess['user_name'] = 'GDPR Test User'

    res = client.get('/api/user/export_data')
    assert res.status_code == 200
    data = res.get_json()
    assert data.get('success') is True
    assert 'data' in data
    export = data['data']
    assert 'profile' in export
    assert 'applications' in export
    assert 'saved_jobs' in export
    assert 'candidate_personal_details' in export
    assert 'candidate_preferences' in export
    assert 'candidate_profile_summary' in export
    assert 'exported_at' in data


def test_export_data_resilience_on_table_query_failure(client, caplog):
    """Verify that if individual table queries fail, export degrades gracefully with empty list and logs warning."""
    with db_cursor() as cur:
        cur.execute("SELECT id FROM user WHERE email = 'gdpr_test@hirevoltz.com'")
        row = cur.fetchone()
        user_id = row['id'] if row else 1

    with client.session_transaction() as sess:
        sess['user_id'] = user_id
        sess['role'] = 'candidate'

    # Intercept execute calls to simulate a failure on 'candidate_preferences'
    real_db_cursor = db_cursor

    from contextlib import contextmanager
    @contextmanager
    def mock_db_cursor(dictionary=True):
        with real_db_cursor(dictionary=dictionary) as cur:
            orig_execute = cur.execute
            def failing_execute(query, params=None):
                if 'candidate_preferences' in query:
                    raise Exception("Simulated missing table candidate_preferences")
                return orig_execute(query, params) if params else orig_execute(query)
            cur.execute = failing_execute
            yield cur

    with patch('app.db_cursor', mock_db_cursor):
        res = client.get('/api/user/export_data')
        assert res.status_code == 200
        data = res.get_json()
        assert data.get('success') is True
        assert data['data']['candidate_preferences'] == []
        assert any("Could not export table 'candidate_preferences'" in record.message for record in caplog.records)
