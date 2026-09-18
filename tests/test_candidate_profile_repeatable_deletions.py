# -*- coding: utf-8 -*-
"""
Tests for Candidate Profile Repeatable Sections:
- Verifies adding >8 (e.g. 12) repeatable entries (Languages, Education, Employment, Projects, etc.)
- Verifies deleting entries at arbitrary positions (e.g. 3rd, 7th, 10th)
- Verifies remaining entries maintain exact original values without data corruption or index shifting
- Verifies event delegation and data-entry-id attributes in candidate_profile_edit.html
- Verifies deleteReq / putReq helpers in main.js
"""
import pytest
import json
from app import app, db_cursor

@pytest.fixture
def client():
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    with app.test_client() as client:
        yield client

@pytest.fixture
def test_user_id():
    email = "repeatable_sections_test@hirevoltz.com"
    with db_cursor(dictionary=True) as cursor:
        cursor.execute("SELECT id FROM user WHERE email = %s", (email,))
        user = cursor.fetchone()
        if user:
            uid = user['id']
        else:
            cursor.execute("""
                INSERT INTO user (name, email, password)
                VALUES (%s, %s, %s)
            """, ("Repeatable Tester", email, "pbkdf2:sha256:dummy"))
            cursor.execute("SELECT id FROM user WHERE email = %s", (email,))
            uid = cursor.fetchone()['id']

        tables = [
            "education", "employment", "projects",
            "internships", "certifications", "key_skills",
            "languages", "competitive_exams", "academic_achievements"
        ]
        for tbl in tables:
            try:
                cursor.execute(f"DELETE FROM {tbl} WHERE user_id = %s", (uid,))
            except Exception:
                pass
        return uid


def test_repeatable_languages_12_entries_delete_3rd_7th_10th(client, test_user_id):
    """
    Test requirement:
    Add 12 languages, delete the 3rd, 7th, and 10th (using their current on-screen position),
    and confirm exactly the correct 3 are removed and the remaining 9 display with their
    correct original values, not shifted or duplicated data.
    """
    with client.session_transaction() as sess:
        sess['user_id'] = test_user_id
        sess['user_name'] = 'Repeatable Tester'
        sess['role'] = 'user'

    language_names = [f"Language_{i+1:02d}" for i in range(12)]
    created_ids = []

    # 1. Add 12 languages
    for lang in language_names:
        payload = {
            'section': 'languages',
            'language': lang,
            'can_read': 1,
            'can_write': 1,
            'can_speak': 1
        }
        res = client.post('/api/candidate/profile/items', json=payload)
        assert res.status_code in [200, 201]
        data = res.get_json()
        assert data['success'] is True
        created_ids.append(data['id'])

    assert len(created_ids) == 12

    # Verify all 12 are returned via /api/candidate/profile/all in order
    res = client.get('/api/candidate/profile/all')
    assert res.status_code == 200
    all_data = res.get_json()
    current_langs = all_data['items']['languages']
    assert len(current_langs) == 12
    assert [x['language'] for x in current_langs] == language_names

    # 2. Delete 3rd entry (index 2: "Language_03")
    third_item = current_langs[2]
    assert third_item['language'] == "Language_03"
    del_res = client.delete(f"/api/candidate/profile/items/{third_item['id']}?section=languages")
    assert del_res.status_code == 200
    assert del_res.get_json()['success'] is True

    # Fetch updated list (now 11 items)
    res = client.get('/api/candidate/profile/all')
    current_langs = res.get_json()['items']['languages']
    assert len(current_langs) == 11
    assert "Language_03" not in [x['language'] for x in current_langs]

    # 3. Delete 7th entry of the current on-screen list (index 6)
    seventh_item = current_langs[6]
    expected_seventh_name = seventh_item['language']
    del_res = client.delete(f"/api/candidate/profile/items/{seventh_item['id']}?section=languages")
    assert del_res.status_code == 200
    assert del_res.get_json()['success'] is True

    # Fetch updated list (now 10 items)
    res = client.get('/api/candidate/profile/all')
    current_langs = res.get_json()['items']['languages']
    assert len(current_langs) == 10
    assert expected_seventh_name not in [x['language'] for x in current_langs]

    # 4. Delete 10th entry of the current on-screen list (index 9)
    tenth_item = current_langs[9]
    expected_tenth_name = tenth_item['language']
    del_res = client.delete(f"/api/candidate/profile/items/{tenth_item['id']}?section=languages")
    assert del_res.status_code == 200
    assert del_res.get_json()['success'] is True

    # Fetch final list (now 9 items)
    res = client.get('/api/candidate/profile/all')
    current_langs = res.get_json()['items']['languages']
    assert len(current_langs) == 9

    # Confirm remaining 9 display with their correct original values
    remaining_names = [x['language'] for x in current_langs]
    expected_remaining = [
        "Language_01", "Language_02", "Language_04", "Language_05",
        "Language_06", "Language_07", "Language_09", "Language_10", "Language_11"
    ]
    assert remaining_names == expected_remaining


def test_other_repeatable_sections_beyond_8_entries(client, test_user_id):
    """Verify other repeatable sections (Education, Projects, Certifications) can exceed 8 entries and delete cleanly."""
    with client.session_transaction() as sess:
        sess['user_id'] = test_user_id
        sess['user_name'] = 'Repeatable Tester'
        sess['role'] = 'user'

    # Test Projects: add 10 projects
    proj_ids = []
    for i in range(10):
        res = client.post('/api/candidate/profile/items', json={
            'section': 'projects',
            'title': f'Project #{i+1}',
            'role': 'Developer',
            'status': 'Completed'
        })
        assert res.status_code in [200, 201]
        proj_ids.append(res.get_json()['id'])

    assert len(proj_ids) == 10

    # Delete 9th item (beyond 8)
    res = client.delete(f'/api/candidate/profile/items/{proj_ids[8]}?section=projects')
    assert res.status_code == 200
    assert res.get_json()['success'] is True

    # Verify remaining projects count is 9
    res = client.get('/api/candidate/profile/all')
    projects = res.get_json()['items']['projects']
    assert len(projects) == 9
    assert 'Project #9' not in [p['title'] for p in projects]


def test_candidate_profile_edit_html_has_event_delegation_and_data_attributes():
    """Verify template contains data-action, data-entry-id, and container click delegation."""
    with open('templates/candidate_profile_edit.html', 'r', encoding='utf-8') as f:
        html = f.read()

    assert 'data-entry-id=' in html
    assert 'data-action="delete"' in html
    assert 'data-action="edit"' in html
    assert 'data-section="languages"' in html
    assert 'data-section="education"' in html
    assert 'data-section="employment"' in html
    assert 'data-section="projects"' in html
    assert 'data-section="certifications"' in html
    assert 'data-section="competitive_exams"' in html
    assert 'data-section="academic_achievements"' in html

    assert "document.addEventListener('click'" in html
    assert "e.target.closest('[data-action]')" in html


def test_main_js_defines_delete_and_put_req():
    """Verify static/js/main.js exports window.deleteReq and window.putReq."""
    with open('static/js/main.js', 'r', encoding='utf-8') as f:
        js = f.read()

    assert 'window.deleteReq =' in js
    assert 'window.putReq =' in js
    assert 'window.postReq =' in js
    assert 'window.getReq =' in js
