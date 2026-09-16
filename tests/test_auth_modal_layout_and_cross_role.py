"""
Regression tests for authentication modal UI layout, cross-role email detection,
and employer password reset functionality.
"""
import time
import pytest
from app import app as flask_app, db_cursor
from werkzeug.security import generate_password_hash


@pytest.fixture
def client():
    flask_app.config["TESTING"] = True
    with flask_app.test_client() as client:
        yield client


def get_csrf(test_client):
    res = test_client.get('/api/csrf_token')
    return res.get_json().get('csrf_token', '')


def test_modal_css_layout_and_alert_classes():
    """Verify that CSS contains proper margin on compact tabs to prevent close-button overlap,
    and alert styling."""
    with open("static/css/app.css", "r", encoding="utf-8") as f:
        css = f.read()

    assert ".auth-tabs-compact" in css
    assert "margin-right: 44px" in css or "margin-right:" in css
    assert ".auth-form-alert" in css
    assert ".alert-error" in css
    assert ".alert-info" in css


def test_template_modal_alert_containers_and_employer_forgot(client):
    """Verify templates have inline alert boxes and employer forgot password forms."""
    res = client.get('/')
    assert res.status_code == 200
    html = res.get_data(as_text=True)

    assert "base-cand-login-alert" in html
    assert "base-cand-signup-alert" in html
    assert "base-cand-forgot-alert" in html
    assert "base-emp-login-alert" in html
    assert "base-emp-signup-alert" in html
    assert "base-emp-forgot-alert" in html
    assert "emp-form-forgot" in html

    with open("templates/_auth_modal.html", "r", encoding="utf-8") as f:
        auth_html = f.read()

    assert "base-cand-login-alert" in auth_html
    assert "base-cand-signup-alert" in auth_html
    assert "base-cand-forgot-alert" in auth_html
    assert "base-emp-login-alert" in auth_html
    assert "base-emp-signup-alert" in auth_html
    assert "base-emp-forgot-alert" in auth_html
    assert "emp-form-forgot" in auth_html


def test_cross_role_login_detection_employer_in_user_login(client):
    """If an email is registered as employer, attempting candidate login returns suggest_role='employer'."""
    test_emp_email = f"cross_emp_{int(time.time())}@example.com"
    test_pass = "TestEmp1234!"
    
    # Ensure test account in DB
    with db_cursor(dictionary=True) as cursor:
        cursor.execute("DELETE FROM user WHERE email = %s", (test_emp_email,))
        cursor.execute("DELETE FROM employee WHERE email = %s", (test_emp_email,))
        cursor.execute(
            "INSERT INTO employee (company_name, mobile, email, password) VALUES (%s, %s, %s, %s)",
            ("Cross Test Inc", "9988776655", test_emp_email, generate_password_hash(test_pass))
        )

    csrf = get_csrf(client)
    # Attempt candidate login
    resp = client.post("/api/user/login", json={
        "email": test_emp_email,
        "password": test_pass
    }, headers={'X-CSRFToken': csrf})
    data = resp.get_json()
    assert resp.status_code in (200, 401)
    assert data["success"] is False
    assert data.get("suggest_role") == "employer"
    assert "Employer" in data["message"]


def test_cross_role_login_detection_candidate_in_employer_login(client):
    """If an email is registered as candidate, attempting employer login returns suggest_role='candidate'."""
    test_cand_email = f"cross_cand_{int(time.time())}@example.com"
    test_pass = "TestCand1234!"
    
    # Ensure test account in DB
    with db_cursor(dictionary=True) as cursor:
        cursor.execute("DELETE FROM employee WHERE email = %s", (test_cand_email,))
        cursor.execute("DELETE FROM user WHERE email = %s", (test_cand_email,))
        cursor.execute(
            "INSERT INTO user (name, email, mobile, password, is_verified) VALUES (%s, %s, %s, %s, 1)",
            ("Candidate Cross Test", test_cand_email, "9123456780", generate_password_hash(test_pass))
        )

    csrf = get_csrf(client)
    # Attempt employer login
    resp = client.post("/api/employer/login", json={
        "email": test_cand_email,
        "password": test_pass
    }, headers={'X-CSRFToken': csrf})
    data = resp.get_json()
    assert resp.status_code in (200, 401)
    assert data["success"] is False
    assert data.get("suggest_role") == "candidate"
    assert "Candidate" in data["message"]


def test_employer_password_reset_flow(client):
    """Verify that an employer can request an OTP and reset their password."""
    test_emp_email = f"reset_emp_{int(time.time())}@example.com"
    old_pass = "OldPassword123!"
    new_pass = "NewPassword456!"

    with db_cursor(dictionary=True) as cursor:
        cursor.execute("DELETE FROM user WHERE email = %s", (test_emp_email,))
        cursor.execute("DELETE FROM employee WHERE email = %s", (test_emp_email,))
        cursor.execute(
            "INSERT INTO employee (company_name, mobile, email, password) VALUES (%s, %s, %s, %s)",
            ("Reset Corp", "9876543299", test_emp_email, generate_password_hash(old_pass))
        )

    # 1. Send OTP for emp_forgot
    csrf = get_csrf(client)
    otp_resp = client.post("/api/send_otp", json={
        "email": test_emp_email,
        "action": "emp_forgot"
    }, headers={'X-CSRFToken': csrf})
    otp_data = otp_resp.get_json()
    assert otp_resp.status_code == 200
    assert otp_data["success"] is True

    # Retrieve the OTP from DB
    with db_cursor(dictionary=True) as cursor:
        cursor.execute("SELECT otp FROM otp_store WHERE email = %s ORDER BY id DESC LIMIT 1", (test_emp_email,))
        row = cursor.fetchone()
        assert row is not None
        otp_code = row["otp"]

    # 2. Reset password
    csrf = get_csrf(client)
    reset_resp = client.post("/api/reset_password", json={
        "email": test_emp_email,
        "otp": otp_code,
        "password": new_pass
    }, headers={'X-CSRFToken': csrf})
    reset_data = reset_resp.get_json()
    assert reset_resp.status_code == 200
    assert reset_data["success"] is True

    # 3. Login with new password
    csrf = get_csrf(client)
    login_resp = client.post("/api/employer/login", json={
        "email": test_emp_email,
        "password": new_pass
    }, headers={'X-CSRFToken': csrf})
    login_data = login_resp.get_json()
    assert login_resp.status_code == 200
    assert login_data["success"] is True
    assert login_data["redirect"] == "/employer_dashboard"
