# -*- coding: utf-8 -*-
"""
Tests for Candidate Profile Photo Persistence, Deletion, Project Link, and Dashboard Badges.
"""
import pytest
import io
import os
from PIL import Image
from app import app, db_cursor


@pytest.fixture
def client():
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    with app.test_client() as client:
        yield client


@pytest.fixture
def test_users():
    """Sets up candidate and employer test fixtures."""
    cand_email = "photo_badge_cand@example.com"
    emp_email = "photo_badge_emp@example.com"

    with db_cursor() as cursor:
        cursor.execute("SELECT id FROM user WHERE email = %s", (cand_email,))
        c_row = cursor.fetchone()
        if not c_row:
            cursor.execute("""
                INSERT INTO user (name, email, password, mobile, headline, location)
                VALUES ('Ananya Iyer', %s, 'hashedpwd', '9876500001', 'Frontend Developer', 'Bangalore')
            """, (cand_email,))
            cand_id = cursor.lastrowid
        else:
            cand_id = c_row['id']

        # Clear prior candidate profile state
        cursor.execute("DELETE FROM candidate_profile WHERE user_id = %s", (cand_id,))
        cursor.execute("DELETE FROM projects WHERE user_id = %s", (cand_id,))
        cursor.execute("DELETE FROM applications WHERE user_id = %s", (cand_id,))

        cursor.execute("SELECT id FROM employee WHERE email = %s", (emp_email,))
        emp_row = cursor.fetchone()
        if not emp_row:
            cursor.execute("""
                INSERT INTO employee (company_name, email, password, mobile)
                VALUES ('CloudScale Dynamics', %s, 'hashedpwd', '9811100002')
            """, (emp_email,))
            emp_id = cursor.lastrowid
        else:
            emp_id = emp_row['id']

        # Ensure a job exists for employer
        cursor.execute("SELECT id FROM jobs WHERE employer_id = %s", (emp_id,))
        job_row = cursor.fetchone()
        if not job_row:
            cursor.execute("""
                INSERT INTO jobs (employer_id, title, category, description, location, is_active)
                VALUES (%s, 'Senior React Engineer', 'IT - Software', 'React role', 'Bangalore', 1)
            """, (emp_id,))
            job_id = cursor.lastrowid
        else:
            job_id = job_row['id']

        # Ensure candidate applied to job so employer can view profile
        cursor.execute("SELECT id FROM applications WHERE user_id = %s AND job_id = %s", (cand_id, job_id))
        if not cursor.fetchone():
            cursor.execute("""
                INSERT INTO applications (job_id, user_id, status)
                VALUES (%s, %s, 'Under Review')
            """, (job_id, cand_id))

    return {
        'cand_id': cand_id,
        'cand_email': cand_email,
        'emp_id': emp_id,
        'emp_email': emp_email,
        'job_id': job_id
    }


def _create_dummy_image():
    """Generates a valid small PNG image in-memory."""
    img_byte_arr = io.BytesIO()
    image = Image.new('RGB', (100, 100), color=(73, 109, 137))
    image.save(img_byte_arr, format='PNG')
    img_byte_arr.seek(0)
    return img_byte_arr


def test_photo_upload_creates_and_persists_in_db(client, test_users):
    """Verifies that uploading a photo creates DB record and persists across logout/relogin."""
    cand_id = test_users['cand_id']
    
    # 1. Login candidate
    with client.session_transaction() as sess:
        sess['user_id'] = cand_id
        sess['user_name'] = 'Ananya Iyer'

    # 2. Upload photo
    img_data = _create_dummy_image()
    res = client.post(
        '/api/candidate/profile/photo',
        data={'photo': (img_data, 'profile.png')},
        content_type='multipart/form-data'
    )
    assert res.status_code == 200
    data = res.get_json()
    assert data['success'] is True
    assert 'filename' in data
    filename = data['filename']
    assert filename.startswith(f"user_{cand_id}_profile")

    # 3. Verify in database
    with db_cursor() as cursor:
        cursor.execute("SELECT profile_photo FROM candidate_profile WHERE user_id = %s", (cand_id,))
        row = cursor.fetchone()
        assert row is not None
        assert row['profile_photo'] == filename

    # 4. Simulate Logout (clear session) and Re-login
    with client.session_transaction() as sess:
        sess.clear()

    # Re-login with fresh session
    with client.session_transaction() as sess:
        sess['user_id'] = cand_id
        sess['user_name'] = 'Ananya Iyer'

    # 5. Verify user dashboard route provides profile_photo
    dash_res = client.get('/user_dashboard')
    assert dash_res.status_code == 200
    assert filename in dash_res.get_data(as_text=True)

    # 6. Verify api_get_all_candidate_profile returns the photo
    all_res = client.get('/api/candidate/profile/all')
    assert all_res.status_code == 200
    all_data = all_res.get_json()
    assert all_data['success'] is True
    assert all_data['profile']['profile_photo'] == filename


def test_photo_deletion_endpoints(client, test_users):
    """Verifies that candidate can delete their profile photo via DELETE and POST endpoints."""
    cand_id = test_users['cand_id']

    # Login and ensure photo exists
    with client.session_transaction() as sess:
        sess['user_id'] = cand_id
        sess['user_name'] = 'Ananya Iyer'

    img_data = _create_dummy_image()
    client.post(
        '/api/candidate/profile/photo',
        data={'photo': (img_data, 'profile.png')},
        content_type='multipart/form-data'
    )

    # Test DELETE endpoint
    del_res = client.delete('/api/candidate/profile/photo')
    assert del_res.status_code == 200
    del_data = del_res.get_json()
    assert del_data['success'] is True

    with db_cursor() as cursor:
        cursor.execute("SELECT profile_photo FROM candidate_profile WHERE user_id = %s", (cand_id,))
        row = cursor.fetchone()
        assert row['profile_photo'] is None or row['profile_photo'] == ''

    # Re-upload and test POST /api/candidate/profile/photo/delete
    img_data2 = _create_dummy_image()
    client.post(
        '/api/candidate/profile/photo',
        data={'photo': (img_data2, 'profile.png')},
        content_type='multipart/form-data'
    )

    del_post_res = client.post('/api/candidate/profile/photo/delete')
    assert del_post_res.status_code == 200
    assert del_post_res.get_json()['success'] is True

    with db_cursor() as cursor:
        cursor.execute("SELECT profile_photo FROM candidate_profile WHERE user_id = %s", (cand_id,))
        row = cursor.fetchone()
        assert row['profile_photo'] is None or row['profile_photo'] == ''


def test_project_with_url_crud(client, test_users):
    """Verifies that projects support project_url saving, editing, and retrieval."""
    cand_id = test_users['cand_id']

    with client.session_transaction() as sess:
        sess['user_id'] = cand_id
        sess['user_name'] = 'Ananya Iyer'

    # 1. Create project with project_url
    create_res = client.post('/api/candidate/profile/items', json={
        'section': 'projects',
        'title': 'AI Recruitment Engine',
        'client_name': 'HireVolt Open Source',
        'status': 'Completed',
        'role': 'Lead Fullstack Architect',
        'team_size': 3,
        'technology_tags': 'Python, Flask, MySQL, Redis',
        'project_url': 'https://github.com/test/hirevolt-ai',
        'project_details': 'End-to-end recruitment matching intelligence system.'
    })
    assert create_res.status_code == 200
    item_id = create_res.get_json()['id']

    # 2. Verify in database
    with db_cursor() as cursor:
        cursor.execute("SELECT * FROM projects WHERE id = %s AND user_id = %s", (item_id, cand_id))
        proj = cursor.fetchone()
        assert proj is not None
        assert proj['title'] == 'AI Recruitment Engine'
        assert proj['project_url'] == 'https://github.com/test/hirevolt-ai'

    # 3. Retrieve via /api/candidate/profile/all
    all_res = client.get('/api/candidate/profile/all')
    assert all_res.status_code == 200
    proj_list = all_res.get_json()['projects']
    found = [p for p in proj_list if p['id'] == item_id]
    assert len(found) == 1
    assert found[0]['project_url'] == 'https://github.com/test/hirevolt-ai'

    # 4. Update project with modified URL
    update_res = client.post(f'/api/candidate/profile/items/{item_id}', json={
        'section': 'projects',
        'title': 'AI Recruitment Engine v2',
        'client_name': 'HireVolt Open Source',
        'status': 'Completed',
        'role': 'Lead Fullstack Architect',
        'team_size': 5,
        'technology_tags': 'Python, Flask, MySQL, Redis',
        'project_url': 'https://hirevolt.example.com/demo',
        'project_details': 'Updated production deployment.'
    })
    assert update_res.status_code == 200

    # 5. Verify updated URL in DB
    with db_cursor() as cursor:
        cursor.execute("SELECT project_url, title FROM projects WHERE id = %s", (item_id,))
        updated_proj = cursor.fetchone()
        assert updated_proj['title'] == 'AI Recruitment Engine v2'
        assert updated_proj['project_url'] == 'https://hirevolt.example.com/demo'


def test_employer_candidate_inspection_includes_photo_and_project_url(client, test_users):
    """Verifies that when employer inspects candidate profile, photo and project URL are included."""
    cand_id = test_users['cand_id']
    emp_id = test_users['emp_id']

    # Ensure candidate has photo and project
    with db_cursor() as cursor:
        cursor.execute("""
            INSERT INTO candidate_profile (user_id, profile_photo)
            VALUES (%s, 'user_test_avatar.jpg')
            ON DUPLICATE KEY UPDATE profile_photo = 'user_test_avatar.jpg'
        """, (cand_id,))
        cursor.execute("""
            INSERT INTO projects (user_id, title, project_url, project_details)
            VALUES (%s, 'Cloud Infrastructure Portal', 'https://github.com/cloud/portal', 'DevOps dashboard')
        """, (cand_id,))

    # Login as employer
    with client.session_transaction() as sess:
        sess['employer_id'] = emp_id
        sess['company_name'] = 'CloudScale Dynamics'

    res = client.get(f'/api/employer/candidate/{cand_id}/profile')
    assert res.status_code == 200
    data = res.get_json()
    assert data['success'] is True
    cand = data['candidate']
    assert cand['profile_photo'] == 'user_test_avatar.jpg'
    assert len(cand['projects']) >= 1
    assert any(p.get('project_url') == 'https://github.com/cloud/portal' for p in cand['projects'])
