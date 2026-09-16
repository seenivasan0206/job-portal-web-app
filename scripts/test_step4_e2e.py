import sys
import os
import time
import uuid
import traceback
from datetime import datetime

# Add project root to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

print('=' * 70)
print('STARTING STEP 4 E2E AUTH VERIFICATION')
print('=' * 70)

try:
    from app import app, db_cursor, generate_password_hash
    client = app.test_client()
    
    def get_csrf(test_client):
        res = test_client.get('/api/csrf_token')
        return res.get_json().get('csrf_token', '')
    
    unique_suffix = int(time.time())
    cand_email = f'test_candidate_{unique_suffix}@example.com'
    cand_name = f'Test Candidate {unique_suffix}'
    cand_mobile = '9876543210'
    cand_password = 'Password123!'
    cand_otp = '123456'
    
    emp_email = f'test_employer_{unique_suffix}@example.com'
    emp_name = f'Test Company {unique_suffix}'
    emp_mobile = '9876543211'
    emp_password = 'Password123!'
    emp_otp = '654321'
    
    # ----------------------------------------------------
    # Step 4a: Candidate Signup with OTP
    # ----------------------------------------------------
    print('\n--- Step 4a: Candidate Signup ---')
    with db_cursor(dictionary=False) as cur:
        cur.execute('DELETE FROM otp_store WHERE email = %s', (cand_email,))
        cur.execute('INSERT INTO otp_store (email, otp, expires_at) VALUES (%s, %s, NOW() + INTERVAL 10 MINUTE)',
                    (cand_email, cand_otp))
    
    reg_payload = {
        'name': cand_name,
        'email': cand_email,
        'mobile': cand_mobile,
        'password': cand_password,
        'otp': cand_otp
    }
    csrf = get_csrf(client)
    reg_resp = client.post('/api/user/register', json=reg_payload, headers={'X-CSRFToken': csrf})
    print(f'POST /api/user/register HTTP Status: {reg_resp.status_code}')
    reg_data = reg_resp.get_json() or {}
    print(f'Response payload: {reg_data}')
    assert reg_resp.status_code == 200, f'Expected 200, got {reg_resp.status_code}'
    assert reg_data.get('success') is True, f'Expected success True, got {reg_data}'
    assert reg_data.get('redirect') == '/user_dashboard', f'Expected /user_dashboard redirect, got {reg_data.get("redirect")}'
    
    # Verify directly in MySQL user table
    with db_cursor(dictionary=True) as cur:
        cur.execute('SELECT id, name, email, mobile, is_verified, created_at FROM user WHERE email = %s', (cand_email,))
        cand_user = cur.fetchone()
    print(f'Database Record in `user` table: {cand_user}')
    assert cand_user is not None, 'Candidate record was not found in MySQL user table!'
    assert cand_user['email'] == cand_email
    print(f'>>> Step 4a PASSED: Candidate registered with DB User ID={cand_user["id"]}')
    
    # ----------------------------------------------------
    # Step 4b: Candidate Login
    # ----------------------------------------------------
    print('\n--- Step 4b: Candidate Login ---')
    login_client = app.test_client()
    login_payload = {
        'email': cand_email,
        'password': cand_password
    }
    csrf = get_csrf(login_client)
    login_resp = login_client.post('/api/user/login', json=login_payload, headers={'X-CSRFToken': csrf})
    print(f'POST /api/user/login HTTP Status: {login_resp.status_code}')
    login_data = login_resp.get_json() or {}
    print(f'Response payload: {login_data}')
    assert login_resp.status_code == 200, f'Expected 200, got {login_resp.status_code}'
    assert login_data.get('success') is True, f'Expected success True, got {login_data}'
    assert login_data.get('redirect') == '/user_dashboard', f'Expected /user_dashboard redirect, got {login_data.get("redirect")}'
    
    dash_resp = login_client.get('/user_dashboard')
    print(f'GET /user_dashboard HTTP Status (authenticated): {dash_resp.status_code}')
    assert dash_resp.status_code == 200, f'Expected 200 on dashboard access, got {dash_resp.status_code}'
    print('>>> Step 4b PASSED: Candidate logged in and accessed /user_dashboard successfully')
    
    # ----------------------------------------------------
    # Step 4c: Employer Signup with OTP
    # ----------------------------------------------------
    print('\n--- Step 4c: Employer Signup ---')
    with db_cursor(dictionary=False) as cur:
        cur.execute('DELETE FROM otp_store WHERE email = %s', (emp_email,))
        cur.execute('INSERT INTO otp_store (email, otp, expires_at) VALUES (%s, %s, NOW() + INTERVAL 10 MINUTE)',
                    (emp_email, emp_otp))
    
    emp_reg_payload = {
        'name': emp_name,
        'email': emp_email,
        'mobile': emp_mobile,
        'password': emp_password,
        'otp': emp_otp
    }
    csrf = get_csrf(client)
    emp_reg_resp = client.post('/api/employer/register', json=emp_reg_payload, headers={'X-CSRFToken': csrf})
    print(f'POST /api/employer/register HTTP Status: {emp_reg_resp.status_code}')
    emp_reg_data = emp_reg_resp.get_json() or {}
    print(f'Response payload: {emp_reg_data}')
    assert emp_reg_resp.status_code == 200, f'Expected 200, got {emp_reg_resp.status_code}'
    assert emp_reg_data.get('success') is True, f'Expected success True, got {emp_reg_data}'
    assert emp_reg_data.get('redirect') == '/employer_dashboard', f'Expected /employer_dashboard redirect, got {emp_reg_data.get("redirect")}'
    
    # Verify directly in MySQL employee table
    with db_cursor(dictionary=True) as cur:
        cur.execute('SELECT id, company_name, email, mobile, created_at FROM employee WHERE email = %s', (emp_email,))
        emp_record = cur.fetchone()
    print(f'Database Record in `employee` table: {emp_record}')
    assert emp_record is not None, 'Employer record was not found in MySQL employee table!'
    assert emp_record['email'] == emp_email
    print(f'>>> Step 4c PASSED: Employer registered with DB Employee ID={emp_record["id"]}')
    
    # ----------------------------------------------------
    # Step 4d: Employer Login
    # ----------------------------------------------------
    print('\n--- Step 4d: Employer Login ---')
    emp_login_client = app.test_client()
    emp_login_payload = {
        'email': emp_email,
        'password': emp_password
    }
    csrf = get_csrf(emp_login_client)
    emp_login_resp = emp_login_client.post('/api/employer/login', json=emp_login_payload, headers={'X-CSRFToken': csrf})
    print(f'POST /api/employer/login HTTP Status: {emp_login_resp.status_code}')
    emp_login_data = emp_login_resp.get_json() or {}
    print(f'Response payload: {emp_login_data}')
    assert emp_login_resp.status_code == 200, f'Expected 200, got {emp_login_resp.status_code}'
    assert emp_login_data.get('success') is True, f'Expected success True, got {emp_login_data}'
    assert emp_login_data.get('redirect') == '/employer_dashboard', f'Expected /employer_dashboard redirect, got {emp_login_data.get("redirect")}'
    
    emp_dash_resp = emp_login_client.get('/employer_dashboard')
    print(f'GET /employer_dashboard HTTP Status (authenticated): {emp_dash_resp.status_code}')
    assert emp_dash_resp.status_code == 200, f'Expected 200 on dashboard access, got {emp_dash_resp.status_code}'
    print('>>> Step 4d PASSED: Employer logged in and accessed /employer_dashboard successfully')
    
    print('\n' + '=' * 70)
    print('ALL STEP 4 E2E AUTH TESTS COMPLETED SUCCESSFULLY!')
    print('=' * 70)

except Exception as e:
    print('\n!!! STEP 4 E2E AUTH TEST FAILED !!!')
    traceback.print_exc()
    sys.exit(1)
