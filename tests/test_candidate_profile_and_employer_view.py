# -*- coding: utf-8 -*-
"""
Tests for:
Part A: Candidate profile save/load persistence (/api/user/profile).
Part B: Employer candidate inspection view (/api/employer/candidate/<id>/profile),
        profile completeness warning gate, and inline resume preview vs attachment download.
"""
import pytest
import json
import os
import io
from docx import Document
from app import app, db_cursor, evaluate_candidate_profile_completeness


@pytest.fixture
def client():
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    with app.test_client() as client:
        yield client


@pytest.fixture
def test_setup():
    """Sets up candidate, employer, job, and application test fixtures."""
    cand_email = "part_ab_candidate@example.com"
    emp1_email = "part_ab_employer1@example.com"
    emp2_email = "part_ab_employer2@example.com"

    with db_cursor() as cursor:
        # 1. Candidate User
        cursor.execute("SELECT id FROM user WHERE email = %s", (cand_email,))
        c_row = cursor.fetchone()
        if not c_row:
            cursor.execute("""
                INSERT INTO user (name, email, password, mobile, headline, skills, experience, location)
                VALUES ('Vikram Seth', %s, 'hashedpwd', '9876543210', 'Junior Developer', 'Python, SQL', 1, 'Chennai')
            """, (cand_email,))
            cand_id = cursor.lastrowid
        else:
            cand_id = c_row['id']

        # Clear candidate profile state
        cursor.execute("DELETE FROM candidate_profile WHERE user_id = %s", (cand_id,))
        cursor.execute("DELETE FROM candidate_profile_summary WHERE user_id = %s", (cand_id,))
        cursor.execute("DELETE FROM candidate_personal_details WHERE user_id = %s", (cand_id,))
        cursor.execute("DELETE FROM profile_views WHERE candidate_id = %s", (cand_id,))
        cursor.execute("DELETE FROM applications WHERE user_id = %s", (cand_id,))

        # 2. Employer 1 (Target Employer)
        cursor.execute("SELECT id FROM employee WHERE email = %s", (emp1_email,))
        emp1_row = cursor.fetchone()
        if not emp1_row:
            cursor.execute("""
                INSERT INTO employee (company_name, email, password, mobile)
                VALUES ('Acme Tech Solutions', %s, 'hashedpwd', '9811111111')
            """, (emp1_email,))
            emp1_id = cursor.lastrowid
        else:
            emp1_id = emp1_row['id']

        # 3. Employer 2 (Unauthorized / Other Employer)
        cursor.execute("SELECT id FROM employee WHERE email = %s", (emp2_email,))
        emp2_row = cursor.fetchone()
        if not emp2_row:
            cursor.execute("""
                INSERT INTO employee (company_name, email, password, mobile)
                VALUES ('Globex Corporation', %s, 'hashedpwd', '9822222222')
            """, (emp2_email,))
            emp2_id = cursor.lastrowid
        else:
            emp2_id = emp2_row['id']

        # 4. Job for Employer 1
        cursor.execute("SELECT id FROM jobs WHERE employer_id = %s AND title = 'Full Stack Engineer'", (emp1_id,))
        job_row = cursor.fetchone()
        if not job_row:
            cursor.execute("""
                INSERT INTO jobs (employer_id, title, category, job_type, experience, location, skills, description, company_name)
                VALUES (%s, 'Full Stack Engineer', 'Software', 'Full-time', '2', 'Chennai', 'Python, React, MySQL', 'Develop SaaS apps', 'Acme Tech Solutions')
            """, (emp1_id,))
            job_id = cursor.lastrowid
        else:
            job_id = job_row['id']

        # Create sample PDF and DOCX files in upload directory
        upload_folder = app.config['UPLOAD_FOLDER']
        os.makedirs(upload_folder, exist_ok=True)
        pdf_filename = f"test_resume_{cand_id}.pdf"
        docx_filename = f"test_resume_{cand_id}.docx"
        pdf_path = os.path.join(upload_folder, pdf_filename)
        docx_path = os.path.join(upload_folder, docx_filename)

        with open(pdf_path, 'wb') as f:
            f.write(b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Count 1/Kids[3 0 R]>>endobj\n3 0 obj<</Type/Page/MediaBox[0 0 612 792]>>endobj\nxref\n0 4\n0000000000 65535 f\n0000000009 00000 n\n0000000052 00000 n\n0000000115 00000 n\ntrailer<</Size 4/Root 1 0 R>>\nstartxref\n178\n%%EOF\n")

        doc = Document()
        doc.add_heading("Vikram Seth - Resume", 0)
        doc.add_paragraph("Experienced Software Engineer with proficiency in Python, Flask, and React.")
        doc.save(docx_path)

        # 5. Application by Candidate to Employer 1's Job with PDF resume
        cursor.execute("""
            INSERT INTO applications (user_id, job_id, user_name, user_email, user_mobile, qualification, experience_level, current_location, resume_path, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (cand_id, job_id, 'Vikram Seth', cand_email, '9876543210', 'B.Tech', '2 Years', 'Chennai', pdf_filename, 'Applied'))
        app_id = cursor.lastrowid

    return {
        'cand_id': cand_id,
        'cand_email': cand_email,
        'emp1_id': emp1_id,
        'emp2_id': emp2_id,
        'job_id': job_id,
        'app_id': app_id,
        'pdf_filename': pdf_filename,
        'docx_filename': docx_filename
    }


# =========================================================================
# PART A TESTS — CANDIDATE PROFILE SAVE & LOAD
# =========================================================================

def test_part_a_candidate_profile_save_and_load(client, test_setup):
    """
    Verifies that POST /api/user/profile saves skills, summary, linkedin_url,
    github_url, portfolio_url to candidate_profile, and GET /api/user/profile
    returns them in both user and profile objects.
    """
    cand_id = test_setup['cand_id']

    with client.session_transaction() as sess:
        sess['user_id'] = cand_id
        sess['role'] = 'user'

    profile_payload = {
        'name': 'Vikram Seth Updated',
        'headline': 'Senior Cloud and Backend Architect',
        'mobile': '9876543210',
        'skills': 'Python, Flask, AWS, PostgreSQL, Docker',
        'summary': 'Passionate cloud engineer with 5+ years specializing in distributed architectures.',
        'linkedin_url': 'https://linkedin.com/in/vikram-seth',
        'github_url': 'https://github.com/vikram-seth',
        'portfolio_url': 'https://vikramseth.dev'
    }

    # 1. Save Profile via POST /api/user/profile
    post_res = client.post('/api/user/profile', json=profile_payload)
    assert post_res.status_code == 200
    post_data = post_res.get_json()
    assert post_data['success'] is True

    # 2. Verify in DB tables
    with db_cursor() as cursor:
        cursor.execute("SELECT name, mobile, headline, skills FROM user WHERE id = %s", (cand_id,))
        u_row = cursor.fetchone()
        assert u_row['name'] == 'Vikram Seth Updated'
        assert u_row['headline'] == 'Senior Cloud and Backend Architect'
        assert u_row['skills'] == 'Python, Flask, AWS, PostgreSQL, Docker'

        cursor.execute("SELECT headline, summary, skills, linkedin_url, github_url, portfolio_url FROM candidate_profile WHERE user_id = %s", (cand_id,))
        cp_row = cursor.fetchone()
        assert cp_row is not None
        assert cp_row['headline'] == 'Senior Cloud and Backend Architect'
        assert cp_row['summary'] == 'Passionate cloud engineer with 5+ years specializing in distributed architectures.'
        assert cp_row['skills'] == 'Python, Flask, AWS, PostgreSQL, Docker'
        assert cp_row['linkedin_url'] == 'https://linkedin.com/in/vikram-seth'
        assert cp_row['github_url'] == 'https://github.com/vikram-seth'
        assert cp_row['portfolio_url'] == 'https://vikramseth.dev'

    # 3. Load Profile via GET /api/user/profile
    get_res = client.get('/api/user/profile')
    assert get_res.status_code == 200
    get_data = get_res.get_json()
    assert get_data['success'] is True
    assert 'user' in get_data
    assert 'profile' in get_data

    p = get_data['profile']
    assert p['headline'] == 'Senior Cloud and Backend Architect'
    assert p['skills'] == 'Python, Flask, AWS, PostgreSQL, Docker'
    assert p['summary'] == 'Passionate cloud engineer with 5+ years specializing in distributed architectures.'
    assert p['linkedin_url'] == 'https://linkedin.com/in/vikram-seth'
    assert p['github_url'] == 'https://github.com/vikram-seth'
    assert p['portfolio_url'] == 'https://vikramseth.dev'


def test_part_a_partial_update_preserves_candidate_profile(client, test_setup):
    """Verifies that updating name and mobile does not wipe out candidate_profile fields."""
    cand_id = test_setup['cand_id']

    with client.session_transaction() as sess:
        sess['user_id'] = cand_id
        sess['role'] = 'user'

    # Initial full save
    client.post('/api/user/profile', json={
        'name': 'Vikram Seth',
        'headline': 'Lead Developer',
        'mobile': '9876543210',
        'skills': 'Python, React',
        'summary': 'Expert coder',
        'linkedin_url': 'https://linkedin.com/in/vikram',
        'github_url': 'https://github.com/vikram',
        'portfolio_url': 'https://vikram.dev'
    })

    # Account update with name and mobile only
    res = client.post('/api/user/profile', json={
        'name': 'Vikram Seth Modified',
        'mobile': '9876543210'
    })
    assert res.status_code == 200

    # Fetch and verify
    get_res = client.get('/api/user/profile')
    data = get_res.get_json()
    assert data['user']['name'] == 'Vikram Seth Modified'


# =========================================================================
# PART B TESTS — EMPLOYER CANDIDATE VIEW & RESUME PREVIEW
# =========================================================================

def test_part_b_employer_candidate_profile_authorization(client, test_setup):
    """Verifies access control on GET /api/employer/candidate/<user_id>/profile."""
    cand_id = test_setup['cand_id']
    emp1_id = test_setup['emp1_id']
    emp2_id = test_setup['emp2_id']

    # 1. Unauthenticated request -> 401
    res1 = client.get(f'/api/employer/candidate/{cand_id}/profile')
    assert res1.status_code == 401

    # 2. Employer 2 (has no application from this candidate) -> 403 Forbidden
    with client.session_transaction() as sess:
        sess['employer_id'] = emp2_id
        sess['role'] = 'employer'

    res2 = client.get(f'/api/employer/candidate/{cand_id}/profile')
    assert res2.status_code == 403

    # 3. Employer 1 (owns job candidate applied to) -> 200 OK
    with client.session_transaction() as sess:
        sess['employer_id'] = emp1_id
        sess['role'] = 'employer'

    res3 = client.get(f'/api/employer/candidate/{cand_id}/profile')
    assert res3.status_code == 200
    data = res3.get_json()
    assert data['success'] is True
    assert data['applied_job_title'] == 'Full Stack Engineer'
    assert data['email'] == 'part_ab_candidate@example.com'
    assert data['mobile'] == '9876543210'
    assert data['current_location'] == 'Chennai'
    assert data['resume_path'] == test_setup['pdf_filename']
    assert 'completeness_score' in data


def test_part_b_completeness_gate_notice(client, test_setup):
    """Verifies candidate with <40% completeness score returns completeness notice."""
    cand_id = test_setup['cand_id']
    emp1_id = test_setup['emp1_id']

    with client.session_transaction() as sess:
        sess['employer_id'] = emp1_id
        sess['role'] = 'employer'

    res = client.get(f'/api/employer/candidate/{cand_id}/profile')
    assert res.status_code == 200
    data = res.get_json()
    
    score = data['completeness_score']
    if score < 40:
        assert data['is_incomplete'] is True
        assert "complete — some sections not filled in yet" in data['completeness_notice']
        assert f"{score}%" in data['completeness_notice']


def test_part_b_pdf_resume_preview_inline(client, test_setup):
    """Verifies GET /api/employer/applications/<app_id>/resume/preview serves PDF inline."""
    app_id = test_setup['app_id']
    emp1_id = test_setup['emp1_id']

    with client.session_transaction() as sess:
        sess['employer_id'] = emp1_id
        sess['role'] = 'employer'

    # Preview endpoint
    res_prev = client.get(f'/api/employer/applications/{app_id}/resume/preview')
    assert res_prev.status_code == 200
    assert 'application/pdf' in res_prev.content_type
    assert 'inline' in res_prev.headers.get('Content-Disposition', '')

    # Also verify query param ?preview=1 on main resume route
    res_param = client.get(f'/api/employer/applications/{app_id}/resume?preview=1')
    assert res_param.status_code == 200
    assert 'application/pdf' in res_param.content_type
    assert 'inline' in res_param.headers.get('Content-Disposition', '')


def test_part_b_docx_resume_preview_html(client, test_setup):
    """Verifies DOCX resume serves clean HTML preview for browser iframe embedding."""
    cand_id = test_setup['cand_id']
    emp1_id = test_setup['emp1_id']
    app_id = test_setup['app_id']
    docx_file = test_setup['docx_filename']

    # Update application resume_path to DOCX file
    with db_cursor() as cursor:
        cursor.execute("UPDATE applications SET resume_path = %s WHERE id = %s", (docx_file, app_id))

    with client.session_transaction() as sess:
        sess['employer_id'] = emp1_id
        sess['role'] = 'employer'

    res = client.get(f'/api/employer/applications/{app_id}/resume/preview')
    assert res.status_code == 200
    assert 'text/html' in res.content_type
    html_content = res.get_data(as_text=True)
    assert 'Resume Preview' in html_content
    assert 'Vikram Seth - Resume' in html_content


def test_part_b_resume_download_attachment(client, test_setup):
    """Verifies GET /api/employer/applications/<app_id>/resume serves attachment header for downloading."""
    app_id = test_setup['app_id']
    emp1_id = test_setup['emp1_id']

    with client.session_transaction() as sess:
        sess['employer_id'] = emp1_id
        sess['role'] = 'employer'

    res = client.get(f'/api/employer/applications/{app_id}/resume')
    assert res.status_code == 200
    assert 'attachment' in res.headers.get('Content-Disposition', '')
