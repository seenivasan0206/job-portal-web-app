import json
import pytest
from app import app, db_cursor, create_notification, check_notification_preference, send_interview_reminders, notify_recommended_job, trigger_job_alerts_for_job


@pytest.fixture
def client():
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    with app.test_client() as client:
        with app.app_context():
            yield client


def _cleanup_test_data(cursor, cand_id, emp_id):
    """Safely cleans up records in foreign-key dependency order."""
    if cand_id:
        cursor.execute("DELETE FROM notifications WHERE user_id = %s", (cand_id,))
        cursor.execute("DELETE FROM notification_preferences WHERE user_id = %s", (cand_id,))
        cursor.execute("DELETE FROM job_alerts WHERE user_id = %s", (cand_id,))
        cursor.execute("DELETE FROM skill_badges WHERE user_id = %s", (cand_id,))
        cursor.execute("DELETE FROM assessment_attempts WHERE user_id = %s", (cand_id,))
        cursor.execute("DELETE FROM messages WHERE sender_id = %s OR receiver_id = %s", (cand_id, cand_id))
        cursor.execute("DELETE FROM interviews WHERE candidate_id = %s", (cand_id,))
        cursor.execute("DELETE FROM applications WHERE user_id = %s", (cand_id,))

    if emp_id:
        cursor.execute("DELETE FROM notifications WHERE employer_id = %s", (emp_id,))
        cursor.execute("DELETE FROM notification_preferences WHERE employer_id = %s", (emp_id,))
        cursor.execute("DELETE FROM messages WHERE sender_id = %s OR receiver_id = %s", (emp_id, emp_id))
        cursor.execute("DELETE FROM interviews WHERE employer_id = %s", (emp_id,))
        cursor.execute("DELETE FROM applications WHERE job_id IN (SELECT id FROM jobs WHERE employer_id = %s)", (emp_id,))
        cursor.execute("DELETE FROM jobs WHERE employer_id = %s", (emp_id,))

    if cand_id:
        cursor.execute("DELETE FROM user WHERE id = %s", (cand_id,))
    if emp_id:
        cursor.execute("DELETE FROM employee WHERE id = %s", (emp_id,))


@pytest.fixture
def setup_test_users():
    """Sets up an isolated candidate and employer in the database for testing."""
    with db_cursor() as cursor:
        cursor.execute("SELECT id FROM user WHERE email = 'notif_cand@hirevolt.test'")
        row = cursor.fetchone()
        cand_id = row['id'] if row else None

        cursor.execute("SELECT id FROM employee WHERE email = 'notif_emp@hirevolt.test'")
        row_e = cursor.fetchone()
        emp_id = row_e['id'] if row_e else None

        if cand_id or emp_id:
            _cleanup_test_data(cursor, cand_id, emp_id)

        # Create fresh candidate
        cursor.execute("""
            INSERT INTO user (name, email, password, location, skills)
            VALUES ('Notif Candidate', 'notif_cand@hirevolt.test', 'hashed_pw', 'Bangalore', 'Python, React')
        """)
        cand_id = cursor.lastrowid

        # Create fresh employer
        cursor.execute("""
            INSERT INTO employee (company_name, email, password, location, is_verified)
            VALUES ('Notif Tech Corp', 'notif_emp@hirevolt.test', 'hashed_pw', 'Bangalore', 1)
        """)
        emp_id = cursor.lastrowid

    yield {'cand_id': cand_id, 'emp_id': emp_id}

    with db_cursor() as cursor:
        _cleanup_test_data(cursor, cand_id, emp_id)


def test_notification_schema_and_dispatcher_isolation(setup_test_users):
    """Verifies central notification dispatcher enforces strict role separation."""
    cand_id = setup_test_users['cand_id']
    emp_id = setup_test_users['emp_id']

    # 1. Candidate notification
    ok = create_notification(
        user_id=cand_id,
        notification_type='general',
        title='Welcome to HireVolt',
        message='Your profile is live.',
        action_url='/user_dashboard'
    )
    assert ok is True

    # 2. Employer notification
    ok_emp = create_notification(
        employer_id=emp_id,
        notification_type='general',
        title='Welcome Recruiter',
        message='Your company account is ready.',
        action_url='/employer_dashboard'
    )
    assert ok_emp is True

    with db_cursor() as cursor:
        cursor.execute("SELECT * FROM notifications WHERE user_id = %s", (cand_id,))
        cand_notifs = cursor.fetchall()
        assert len(cand_notifs) == 1
        assert cand_notifs[0]['employer_id'] is None
        assert cand_notifs[0]['title'] == 'Welcome to HireVolt'

        cursor.execute("SELECT * FROM notifications WHERE employer_id = %s", (emp_id,))
        emp_notifs = cursor.fetchall()
        assert len(emp_notifs) == 1
        assert emp_notifs[0]['user_id'] is None
        assert emp_notifs[0]['title'] == 'Welcome Recruiter'


def test_trigger_new_application(client, setup_test_users):
    """Verifies that submitting an application triggers candidate confirmation and employer notification."""
    cand_id = setup_test_users['cand_id']
    emp_id = setup_test_users['emp_id']

    # Create job
    with db_cursor() as cursor:
        cursor.execute("""
            INSERT INTO jobs (employer_id, title, description, location, job_type, is_active, status)
            VALUES (%s, 'Senior Python Architect', 'Build scalable pipelines', 'Bangalore', 'Full-time', 1, 'Active')
        """, (emp_id,))
        job_id = cursor.lastrowid

    with client.session_transaction() as sess:
        sess['user_id'] = cand_id
        sess['user_name'] = 'Notif Candidate'
        sess['user_email'] = 'notif_cand@hirevolt.test'

    res = client.post('/api/apply_job', data={
        'job_id': job_id,
        'name': 'Notif Candidate',
        'email': 'notif_cand@hirevolt.test',
        'cover_letter': 'Excited to apply!'
    })
    assert res.status_code == 200
    data = res.get_json()
    assert data['success'] is True

    # Check candidate received notification
    with db_cursor() as cursor:
        cursor.execute("SELECT * FROM notifications WHERE user_id = %s AND notification_type = 'application_submitted'", (cand_id,))
        c_notif = cursor.fetchone()
        assert c_notif is not None
        assert 'Senior Python Architect' in c_notif['message']

        # Check employer received notification
        cursor.execute("SELECT * FROM notifications WHERE employer_id = %s AND notification_type = 'new_application'", (emp_id,))
        e_notif = cursor.fetchone()
        assert e_notif is not None
        assert 'Notif Candidate' in e_notif['message']


def test_trigger_application_status_change_and_shortlist_and_rejection(client, setup_test_users):
    """Verifies application status change triggers: Screening, Shortlisting, and Rejection."""
    cand_id = setup_test_users['cand_id']
    emp_id = setup_test_users['emp_id']

    with db_cursor() as cursor:
        cursor.execute("""
            INSERT INTO jobs (employer_id, title, description, location, is_active)
            VALUES (%s, 'Lead Backend Dev', 'Design backend APIs', 'Bangalore', 1)
        """, (emp_id,))
        job_id = cursor.lastrowid

        cursor.execute("""
            INSERT INTO applications (job_id, user_id, user_name, user_email, status)
            VALUES (%s, %s, 'Notif Candidate', 'notif_cand@hirevolt.test', 'Applied')
        """, (job_id, cand_id))
        app_id = cursor.lastrowid

    # Employer login
    with client.session_transaction() as sess:
        sess['employer_id'] = emp_id
        sess['role'] = 'employer'

    # 1. Update status to 'Shortlisted'
    res = client.post('/api/update_candidate_status', json={'app_id': app_id, 'status': 'Shortlisted'})
    assert res.status_code == 200

    with db_cursor() as cursor:
        cursor.execute("SELECT * FROM notifications WHERE user_id = %s AND notification_type = 'shortlisting'", (cand_id,))
        s_notif = cursor.fetchone()
        assert s_notif is not None
        assert 'shortlisted' in s_notif['message'].lower()

    # 2. Update status to 'Rejected'
    res = client.post('/api/update_candidate_status', json={'app_id': app_id, 'status': 'Rejected'})
    assert res.status_code == 200

    with db_cursor() as cursor:
        cursor.execute("SELECT * FROM notifications WHERE user_id = %s AND notification_type = 'rejection'", (cand_id,))
        r_notif = cursor.fetchone()
        assert r_notif is not None
        assert 'not selected' in r_notif['message'].lower()


def test_trigger_interview_invitation_and_reminder(client, setup_test_users):
    """Verifies scheduling an interview triggers interview_invitation and interview_reminder."""
    cand_id = setup_test_users['cand_id']
    emp_id = setup_test_users['emp_id']

    with db_cursor() as cursor:
        cursor.execute("INSERT INTO jobs (employer_id, title, location) VALUES (%s, 'DevOps Lead', 'Remote')", (emp_id,))
        job_id = cursor.lastrowid

    with client.session_transaction() as sess:
        sess['employer_id'] = emp_id
        sess['role'] = 'employer'

    # Schedule interview
    res = client.post('/api/recruiter/interviews/schedule', json={
        'candidate_id': cand_id,
        'job_id': job_id,
        'title': 'System Architecture Round',
        'scheduled_date': '2026-10-15',
        'scheduled_time': '14:00',
        'duration_minutes': 45,
        'interview_type': 'Video Call'
    })
    assert res.status_code == 200

    with db_cursor() as cursor:
        cursor.execute("SELECT * FROM notifications WHERE user_id = %s AND notification_type = 'interview_invitation'", (cand_id,))
        inv_notif = cursor.fetchone()
        assert inv_notif is not None
        assert 'System Architecture Round' in inv_notif['message']

    # Test interview reminder dispatcher
    with db_cursor() as cursor:
        cursor.execute("UPDATE interviews SET scheduled_date = CURDATE() WHERE candidate_id = %s", (cand_id,))

    reminders_sent = send_interview_reminders()
    assert reminders_sent >= 1

    with db_cursor() as cursor:
        cursor.execute("SELECT * FROM notifications WHERE user_id = %s AND notification_type = 'interview_reminder'", (cand_id,))
        rem_notif = cursor.fetchone()
        assert rem_notif is not None
        assert 'Reminder' in rem_notif['title']


def test_trigger_new_message(client, setup_test_users):
    """Verifies direct messages between Candidate and Employer trigger new_message notifications."""
    cand_id = setup_test_users['cand_id']
    emp_id = setup_test_users['emp_id']

    # Candidate sends message to Employer
    with client.session_transaction() as sess:
        sess['user_id'] = cand_id
        sess['user_name'] = 'Notif Candidate'

    res = client.post('/api/messages', json={
        'receiver_id': emp_id,
        'content': 'Hello recruiter, I have updated my portfolio link.'
    })
    assert res.status_code == 200

    with db_cursor() as cursor:
        cursor.execute("SELECT * FROM notifications WHERE employer_id = %s AND notification_type = 'new_message'", (emp_id,))
        msg_notif = cursor.fetchone()
        assert msg_notif is not None
        assert 'updated my portfolio link' in msg_notif['message']

    # Employer replies to Candidate
    with client.session_transaction() as sess:
        sess.clear()
        sess['employer_id'] = emp_id
        sess['company_name'] = 'Notif Tech Corp'

    res = client.post('/api/messages', json={
        'receiver_id': cand_id,
        'content': 'Thanks! We look forward to speaking soon.'
    })
    assert res.status_code == 200

    with db_cursor() as cursor:
        cursor.execute("SELECT * FROM notifications WHERE user_id = %s AND notification_type = 'new_message'", (cand_id,))
        cand_msg_notif = cursor.fetchone()
        assert cand_msg_notif is not None
        assert 'look forward to speaking' in cand_msg_notif['message']


def test_trigger_recommended_job_and_job_alerts(client, setup_test_users):
    """Verifies recommended job and matching job alerts triggers."""
    cand_id = setup_test_users['cand_id']
    emp_id = setup_test_users['emp_id']

    # 1. Job recommendation trigger
    notify_recommended_job(cand_id, 999, 'Principal AI Engineer', 'HireVolt Labs')
    with db_cursor() as cursor:
        cursor.execute("SELECT * FROM notifications WHERE user_id = %s AND notification_type = 'recommended_job'", (cand_id,))
        rec_notif = cursor.fetchone()
        assert rec_notif is not None
        assert 'Principal AI Engineer' in rec_notif['message']

    # 2. Job alert trigger
    with db_cursor() as cursor:
        cursor.execute("INSERT INTO job_alerts (user_id, keywords) VALUES (%s, 'Rust, Cloud')", (cand_id,))
        alert_id = cursor.lastrowid

    # Post job matching keywords
    with client.session_transaction() as sess:
        sess['employer_id'] = emp_id
        sess['company_name'] = 'Notif Tech Corp'

    trigger_job_alerts_for_job(
        job_id=101,
        job_title='Cloud Systems Engineer (Rust)',
        company_name='Notif Tech Corp',
        location='Bangalore',
        skills='Rust, Docker, Cloud'
    )

    with db_cursor() as cursor:
        cursor.execute("SELECT * FROM notifications WHERE user_id = %s AND notification_type = 'job_alert'", (cand_id,))
        alert_notif = cursor.fetchone()
        assert alert_notif is not None
        assert 'Cloud Systems Engineer (Rust)' in alert_notif['title']


def test_trigger_assessment_result_and_security_events(client, setup_test_users):
    """Verifies assessment results scoring and password change security events."""
    cand_id = setup_test_users['cand_id']
    emp_id = setup_test_users['emp_id']

    # 1. Assessment Result Notification
    create_notification(
        user_id=cand_id,
        notification_type='assessment_result',
        title='Assessment Result: Python Core (Passed! 🎉)',
        message='You scored 92% on Python Core. You earned the Verified Professional badge! 🏅',
        action_url='/candidate/assessments/1/result'
    )
    with db_cursor() as cursor:
        cursor.execute("SELECT * FROM notifications WHERE user_id = %s AND notification_type = 'assessment_result'", (cand_id,))
        asm_notif = cursor.fetchone()
        assert asm_notif is not None
        assert 'Python Core' in asm_notif['title']

    # 2. Security Event (Password change)
    create_notification(
        user_id=cand_id,
        notification_type='security_event',
        title='Security Alert: Password Changed 🔒',
        message='Your account password was updated successfully.',
        action_url='/candidate/settings'
    )
    with db_cursor() as cursor:
        cursor.execute("SELECT * FROM notifications WHERE user_id = %s AND notification_type = 'security_event'", (cand_id,))
        sec_notif = cursor.fetchone()
        assert sec_notif is not None
        assert 'Password Changed' in sec_notif['title']


def test_notification_crud_operations_and_counters(client, setup_test_users):
    """Verifies notifications listing, unread counter, mark as read, mark all read, and delete."""
    cand_id = setup_test_users['cand_id']

    # Insert 3 notifications
    create_notification(cand_id, notification_type='general', title='Notif 1', message='First')
    create_notification(cand_id, notification_type='general', title='Notif 2', message='Second')
    create_notification(cand_id, notification_type='general', title='Notif 3', message='Third')

    with client.session_transaction() as sess:
        sess['user_id'] = cand_id

    # 1. Unread count
    res = client.get('/api/notifications/unread_count')
    assert res.status_code == 200
    data = res.get_json()
    assert data['unread_count'] >= 3

    # 2. List notifications
    res = client.get('/api/notifications?page=1&limit=10')
    assert res.status_code == 200
    data = res.get_json()
    assert data['success'] is True
    assert len(data['notifications']) >= 3
    notif_id = data['notifications'][0]['id']

    # 3. Mark single notification as read
    res = client.post(f'/api/notifications/{notif_id}/read')
    assert res.status_code == 200

    # 4. Mark all as read
    res = client.post('/api/notifications/mark_all_read')
    assert res.status_code == 200

    res = client.get('/api/notifications/unread_count')
    assert res.get_json()['unread_count'] == 0

    # 5. Delete single notification
    res = client.delete(f'/api/notifications/{notif_id}')
    assert res.status_code == 200

    # 6. Clear all notifications
    res = client.post('/api/notifications/clear_all')
    assert res.status_code == 200

    res = client.get('/api/notifications')
    assert len(res.get_json()['notifications']) == 0


def test_cross_role_isolation_and_idor_protection(client, setup_test_users):
    """Ensures candidates cannot view/modify employer notifications and vice versa."""
    cand_id = setup_test_users['cand_id']
    emp_id = setup_test_users['emp_id']

    create_notification(employer_id=emp_id, notification_type='general', title='Confidential Employer Alert', message='Private')
    with db_cursor() as cursor:
        cursor.execute("SELECT id FROM notifications WHERE employer_id = %s", (emp_id,))
        emp_notif_id = cursor.fetchone()['id']

    # Candidate session attempts to view or modify employer notification
    with client.session_transaction() as sess:
        sess['user_id'] = cand_id

    # List only returns candidate's items
    res = client.get('/api/notifications')
    titles = [n['title'] for n in res.get_json()['notifications']]
    assert 'Confidential Employer Alert' not in titles

    # Cannot mark as read
    res = client.post(f'/api/notifications/{emp_notif_id}/read')
    assert res.status_code == 404

    # Cannot delete
    res = client.delete(f'/api/notifications/{emp_notif_id}')
    assert res.status_code == 404


def test_notification_preferences_suppression(client, setup_test_users):
    """Verifies that disabling a notification preference suppresses that notification type."""
    cand_id = setup_test_users['cand_id']

    with client.session_transaction() as sess:
        sess['user_id'] = cand_id

    # 1. Fetch preferences
    res = client.get('/api/notifications/preferences')
    assert res.status_code == 200
    assert res.get_json()['success'] is True

    # 2. Disable message notifications
    res = client.post('/api/notifications/preferences', json={'messages': False, 'job_alerts': False})
    assert res.status_code == 200

    # 3. Trigger message notification -> should be suppressed
    ok = create_notification(user_id=cand_id, notification_type='new_message', title='Should be suppressed', message='Test')
    assert ok is False

    with db_cursor() as cursor:
        cursor.execute("SELECT * FROM notifications WHERE user_id = %s AND title = 'Should be suppressed'", (cand_id,))
        assert cursor.fetchone() is None

    # Critical security event is never suppressed even if other prefs are off
    ok_sec = create_notification(user_id=cand_id, notification_type='security_event', title='Security Alert: Password Changed 🔒', message='Critical')
    assert ok_sec is True
