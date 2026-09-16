"""
test_messaging_system.py
========================
Comprehensive automated test suite for HireVolt Candidate <-> Employer Messaging System:
1. Schema & conversation initialization.
2. Bidirectional messaging round-trip.
3. Conversation history & timestamps.
4. Unread counters & mark-as-read receipts.
5. IDOR & role isolation security (strict cross-user rejection).
6. Content validation, length enforcement, and XSS sanitization.
7. Adaptive polling with `since_id` incremental delta fetches.
8. Start conversation endpoint.
9. In-app notification triggers and preference checking.
"""

import pytest
from app import app, db_cursor, get_or_create_conversation, create_notification


def _cleanup_chat_data(cursor, cand1, cand2, emp1, emp2):
    user_ids = [u for u in (cand1, cand2) if u]
    emp_ids = [e for e in (emp1, emp2) if e]

    if user_ids:
        format_u = ','.join(['%s'] * len(user_ids))
        cursor.execute(f"DELETE FROM notifications WHERE user_id IN ({format_u})", user_ids)
        cursor.execute(f"DELETE FROM notification_preferences WHERE user_id IN ({format_u})", user_ids)
        cursor.execute(f"DELETE FROM messages WHERE sender_id IN ({format_u}) OR receiver_id IN ({format_u})", user_ids + user_ids)
        cursor.execute(f"DELETE FROM conversations WHERE candidate_id IN ({format_u})", user_ids)
    if emp_ids:
        format_e = ','.join(['%s'] * len(emp_ids))
        cursor.execute(f"DELETE FROM notifications WHERE employer_id IN ({format_e})", emp_ids)
        cursor.execute(f"DELETE FROM notification_preferences WHERE employer_id IN ({format_e})", emp_ids)
        cursor.execute(f"DELETE FROM messages WHERE sender_id IN ({format_e}) OR receiver_id IN ({format_e})", emp_ids + emp_ids)
        cursor.execute(f"DELETE FROM conversations WHERE employer_id IN ({format_e})", emp_ids)
        cursor.execute(f"DELETE FROM jobs WHERE employer_id IN ({format_e})", emp_ids)

    if user_ids:
        cursor.execute(f"DELETE FROM user WHERE id IN ({format_u})", user_ids)
    if emp_ids:
        cursor.execute(f"DELETE FROM employee WHERE id IN ({format_e})", emp_ids)


@pytest.fixture
def setup_chat_users(client):
    """Sets up 2 candidates and 2 employers with jobs for chat testing."""
    app.config['WTF_CSRF_ENABLED'] = False

    cand1_id = None
    cand2_id = None
    emp1_id = None
    emp2_id = None

    with db_cursor() as cursor:
        cursor.execute("SELECT id FROM user WHERE email IN ('alice.chat@test.com', 'bob.chat@test.com')")
        u_rows = cursor.fetchall()
        for r in u_rows:
            _cleanup_chat_data(cursor, r['id'], None, None, None)

        cursor.execute("SELECT id FROM employee WHERE email IN ('recruiter.acme@test.com', 'recruiter.beta@test.com')")
        e_rows = cursor.fetchall()
        for r in e_rows:
            _cleanup_chat_data(cursor, None, None, r['id'], None)

        # Candidate 1
        cursor.execute(
            "INSERT INTO user (name, email, password, location, skills) VALUES (%s, %s, %s, %s, %s)",
            ('Alice Candidate', 'alice.chat@test.com', 'HashedPass123!', 'Bangalore', 'Python, SQL')
        )
        cand1_id = cursor.lastrowid

        # Candidate 2
        cursor.execute(
            "INSERT INTO user (name, email, password, location, skills) VALUES (%s, %s, %s, %s, %s)",
            ('Bob Candidate', 'bob.chat@test.com', 'HashedPass123!', 'Mumbai', 'React, CSS')
        )
        cand2_id = cursor.lastrowid

        # Employer 1
        cursor.execute(
            "INSERT INTO employee (company_name, email, password) VALUES (%s, %s, %s)",
            ('Acme Corp', 'recruiter.acme@test.com', 'HashedPass123!')
        )
        emp1_id = cursor.lastrowid

        # Employer 2
        cursor.execute(
            "INSERT INTO employee (company_name, email, password) VALUES (%s, %s, %s)",
            ('Beta Innovations', 'recruiter.beta@test.com', 'HashedPass123!')
        )
        emp2_id = cursor.lastrowid

        # Job for Employer 1
        cursor.execute("""
            INSERT INTO jobs (title, company_name, employer_id, location, is_active, application_deadline)
            VALUES (%s, %s, %s, %s, 1, DATE_ADD(CURDATE(), INTERVAL 30 DAY))
        """, ('Senior Backend Engineer', 'Acme Corp', emp1_id, 'Bangalore'))
        job_id = cursor.lastrowid

    yield {
        'cand1_id': cand1_id,
        'cand2_id': cand2_id,
        'emp1_id': emp1_id,
        'emp2_id': emp2_id,
        'job_id': job_id
    }

    with db_cursor() as cursor:
        _cleanup_chat_data(cursor, cand1_id, cand2_id, emp1_id, emp2_id)


def test_schema_and_get_or_create_conversation(client, setup_chat_users):
    """Verifies get_or_create_conversation creates and reuses conversation entries."""
    data = setup_chat_users
    cand1 = data['cand1_id']
    emp1 = data['emp1_id']
    job_id = data['job_id']

    # First invocation creates conversation
    conv_id_1 = get_or_create_conversation(candidate_id=cand1, employer_id=emp1, job_id=job_id)
    assert conv_id_1 > 0

    # Second invocation retrieves the same conversation
    conv_id_2 = get_or_create_conversation(candidate_id=cand1, employer_id=emp1)
    assert conv_id_1 == conv_id_2


def test_candidate_employer_bidirectional_messaging_and_history(client, setup_chat_users):
    """Verifies complete round-trip messaging between candidate and employer."""
    data = setup_chat_users
    cand1 = data['cand1_id']
    emp1 = data['emp1_id']
    job_id = data['job_id']

    # 1. Candidate sends first message to Employer 1
    with client.session_transaction() as sess:
        sess['user_id'] = cand1
        sess['user_name'] = 'Alice Candidate'

    res_send = client.post('/api/messages', json={
        'receiver_id': emp1,
        'job_id': job_id,
        'content': 'Hello Acme hiring team, I am very excited about the Senior Backend Engineer role!'
    })
    assert res_send.status_code == 200
    send_data = res_send.get_json()
    assert send_data['success'] is True
    conv_id = send_data['conversation_id']
    msg1_id = send_data['id']

    # 2. Employer 1 checks conversation list
    with client.session_transaction() as sess:
        sess.clear()
        sess['employer_id'] = emp1
        sess['company_name'] = 'Acme Corp'

    res_convs = client.get('/api/conversations')
    assert res_convs.status_code == 200
    convs_data = res_convs.get_json()
    assert convs_data['success'] is True
    assert len(convs_data['conversations']) >= 1
    found_conv = next(c for c in convs_data['conversations'] if c['id'] == conv_id)
    assert found_conv['participant_name'] == 'Alice Candidate'
    assert found_conv['unread_count'] == 1
    assert 'Senior Backend Engineer' in found_conv['last_message'] or 'excited' in found_conv['last_message']

    # Employer checks unread counter endpoint
    res_unread = client.get('/api/messages/unread_count')
    assert res_unread.status_code == 200
    assert res_unread.get_json()['unread_count'] == 1

    # 3. Employer opens conversation thread (marks as read automatically)
    res_thread = client.get(f'/api/conversations/{conv_id}')
    assert res_thread.status_code == 200
    thread_data = res_thread.get_json()
    assert thread_data['success'] is True
    assert len(thread_data['messages']) == 1
    assert thread_data['messages'][0]['id'] == msg1_id
    assert thread_data['messages'][0]['is_me'] is False

    # Verify unread counter is now 0 for Employer
    res_unread_after = client.get('/api/messages/unread_count')
    assert res_unread_after.get_json()['unread_count'] == 0

    # 4. Employer replies to Candidate
    res_reply = client.post(f'/api/conversations/{conv_id}/messages', json={
        'content': 'Hi Alice! We saw your portfolio and would like to invite you for an interview.'
    })
    assert res_reply.status_code == 200
    reply_data = res_reply.get_json()
    assert reply_data['success'] is True
    msg2_id = reply_data['id']
    assert reply_data['message_data']['is_me'] is True

    # 5. Candidate checks conversation list and unread count
    with client.session_transaction() as sess:
        sess.clear()
        sess['user_id'] = cand1
        sess['user_name'] = 'Alice Candidate'

    res_cand_unread = client.get('/api/messages/unread_count')
    assert res_cand_unread.get_json()['unread_count'] == 1

    res_cand_thread = client.get(f'/api/conversations/{conv_id}')
    assert res_cand_thread.status_code == 200
    cand_thread = res_cand_thread.get_json()
    assert len(cand_thread['messages']) == 2
    assert cand_thread['messages'][0]['is_me'] is True
    assert cand_thread['messages'][1]['is_me'] is False
    assert 'invite you for an interview' in cand_thread['messages'][1]['content']

    # Verify Candidate unread count reset
    res_cand_unread_after = client.get('/api/messages/unread_count')
    assert res_cand_unread_after.get_json()['unread_count'] == 0


def test_idor_and_role_isolation_security(client, setup_chat_users):
    """
    Verifies strict IDOR protection:
    - Candidate 2 cannot access Candidate 1's conversation with Employer 1.
    - Employer 2 cannot access Candidate 1's conversation with Employer 1.
    - Candidate 2 cannot post messages into Candidate 1's conversation.
    - Unauthenticated requests are rejected with 401.
    """
    data = setup_chat_users
    cand1 = data['cand1_id']
    cand2 = data['cand2_id']
    emp1 = data['emp1_id']
    emp2 = data['emp2_id']

    # Create conversation between Candidate 1 and Employer 1
    conv_id = get_or_create_conversation(cand1, emp1)

    # 1. Unauthenticated access rejected
    res_unauth = client.get(f'/api/conversations/{conv_id}')
    assert res_unauth.status_code == 401

    res_unauth_send = client.post(f'/api/conversations/{conv_id}/messages', json={'content': 'Test'})
    assert res_unauth_send.status_code == 401

    # 2. Candidate 2 attempts to read Candidate 1's conversation (IDOR attempt)
    with client.session_transaction() as sess:
        sess.clear()
        sess['user_id'] = cand2
        sess['user_name'] = 'Bob Candidate'

    res_idor_read = client.get(f'/api/conversations/{conv_id}')
    assert res_idor_read.status_code in (403, 404)

    # Candidate 2 attempts to send message in Candidate 1's conversation (IDOR attempt)
    res_idor_post = client.post(f'/api/conversations/{conv_id}/messages', json={'content': 'Hacked message'})
    assert res_idor_post.status_code in (403, 404)

    # 3. Employer 2 attempts to read Employer 1's conversation (IDOR attempt)
    with client.session_transaction() as sess:
        sess.clear()
        sess['employer_id'] = emp2
        sess['company_name'] = 'Beta Innovations'

    res_emp_idor_read = client.get(f'/api/conversations/{conv_id}')
    assert res_emp_idor_read.status_code in (403, 404)

    res_emp_idor_post = client.post(f'/api/conversations/{conv_id}/messages', json={'content': 'Hacked employer message'})
    assert res_emp_idor_post.status_code in (403, 404)


def test_content_validation_and_xss_sanitization(client, setup_chat_users):
    """Verifies empty messages, overly long messages, and XSS injection payloads."""
    data = setup_chat_users
    cand1 = data['cand1_id']
    emp1 = data['emp1_id']
    conv_id = get_or_create_conversation(cand1, emp1)

    with client.session_transaction() as sess:
        sess['user_id'] = cand1
        sess['user_name'] = 'Alice Candidate'

    # Empty content
    res_empty = client.post(f'/api/conversations/{conv_id}/messages', json={'content': '   '})
    assert res_empty.status_code == 400

    # Overly long content (> 2000 chars)
    res_long = client.post(f'/api/conversations/{conv_id}/messages', json={'content': 'A' * 2005})
    assert res_long.status_code == 400

    # XSS content
    xss_payload = '<script>alert("xss")</script>Hello <b>world</b> <img src=x onerror=alert(1)>'
    res_xss = client.post(f'/api/conversations/{conv_id}/messages', json={'content': xss_payload})
    assert res_xss.status_code == 200
    msg_data = res_xss.get_json()['message_data']
    assert '<script>' not in msg_data['content']
    assert '<img' not in msg_data['content']


def test_adaptive_polling_since_id(client, setup_chat_users):
    """Verifies incremental message delta querying using `since_id`."""
    data = setup_chat_users
    cand1 = data['cand1_id']
    emp1 = data['emp1_id']
    conv_id = get_or_create_conversation(cand1, emp1)

    with client.session_transaction() as sess:
        sess['user_id'] = cand1
        sess['user_name'] = 'Alice Candidate'

    # Send message 1
    res1 = client.post(f'/api/conversations/{conv_id}/messages', json={'content': 'Message One'})
    m1_id = res1.get_json()['id']

    # Send message 2
    res2 = client.post(f'/api/conversations/{conv_id}/messages', json={'content': 'Message Two'})
    m2_id = res2.get_json()['id']

    # Fetch with since_id = m1_id -> should return only Message Two
    res_poll = client.get(f'/api/conversations/{conv_id}?since_id={m1_id}')
    assert res_poll.status_code == 200
    poll_data = res_poll.get_json()
    assert len(poll_data['messages']) == 1
    assert poll_data['messages'][0]['id'] == m2_id
    assert poll_data['messages'][0]['content'] == 'Message Two'

    # Fetch with since_id = m2_id -> should return empty list
    res_poll_empty = client.get(f'/api/conversations/{conv_id}?since_id={m2_id}')
    assert res_poll_empty.status_code == 200
    assert len(res_poll_empty.get_json()['messages']) == 0


def test_start_conversation_endpoint(client, setup_chat_users):
    """Verifies /api/conversations/start initializes conversation with optional initial message."""
    data = setup_chat_users
    cand1 = data['cand1_id']
    emp2 = data['emp2_id']

    with client.session_transaction() as sess:
        sess['user_id'] = cand1
        sess['user_name'] = 'Alice Candidate'

    res = client.post('/api/conversations/start', json={
        'recipient_id': emp2,
        'initial_message': 'Hello Beta Innovations, I would love to connect!'
    })
    assert res.status_code == 200
    resp_data = res.get_json()
    assert resp_data['success'] is True
    conv_id = resp_data['conversation_id']

    # Check that message was created
    res_thread = client.get(f'/api/conversations/{conv_id}')
    assert len(res_thread.get_json()['messages']) == 1
    assert 'Beta Innovations' in res_thread.get_json()['messages'][0]['content']


def test_notifications_and_preferences_on_messages(client, setup_chat_users):
    """Verifies in-app notification creation on messaging and respects user preferences."""
    data = setup_chat_users
    cand1 = data['cand1_id']
    emp1 = data['emp1_id']

    # 1. Candidate sends message -> Employer gets notification
    with client.session_transaction() as sess:
        sess['user_id'] = cand1
        sess['user_name'] = 'Alice Candidate'

    client.post('/api/messages', json={
        'receiver_id': emp1,
        'content': 'Check notification trigger message.'
    })

    with db_cursor() as cursor:
        cursor.execute("SELECT * FROM notifications WHERE employer_id = %s AND notification_type = 'new_message'", (emp1,))
        emp_notif = cursor.fetchone()
        assert emp_notif is not None
        assert 'Alice Candidate' in emp_notif['title'] or 'Alice Candidate' in emp_notif['message']

    # 2. Employer disables message notifications in preferences
    with client.session_transaction() as sess:
        sess.clear()
        sess['employer_id'] = emp1

    client.post('/api/notifications/preferences', json={'messages': False})

    # Candidate sends another message -> Notification should NOT be created for employer
    with client.session_transaction() as sess:
        sess.clear()
        sess['user_id'] = cand1

    with db_cursor() as cursor:
        cursor.execute("DELETE FROM notifications WHERE employer_id = %s", (emp1,))

    client.post('/api/messages', json={
        'receiver_id': emp1,
        'content': 'Second message when notifications disabled.'
    })

    with db_cursor() as cursor:
        cursor.execute("SELECT * FROM notifications WHERE employer_id = %s AND notification_type = 'new_message'", (emp1,))
        assert cursor.fetchone() is None
