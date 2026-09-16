import os
import sys
sys.path.insert(0, r"c:\Program Files\Ampps\www\job-portal-web-app")
import json
import pytest
from app import app, db_cursor

@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client

def test_database_assessments_count():
    with db_cursor() as cursor:
        cursor.execute("SELECT COUNT(*) as cnt FROM assessments")
        res = cursor.fetchone()
        assert res['cnt'] >= 100, f"Expected at least 100 assessments, got {res['cnt']}"
        print(f"\n[PASS] MySQL Assessments Total: {res['cnt']}")

        cursor.execute("SELECT COUNT(*) as qcnt FROM assessment_questions")
        qres = cursor.fetchone()
        assert qres['qcnt'] >= 500, f"Expected at least 500 questions, got {qres['qcnt']}"
        print(f"[PASS] MySQL Assessment Questions Total: {qres['qcnt']}")

        cursor.execute("SELECT domain, COUNT(*) as cnt FROM assessments GROUP BY domain ORDER BY cnt DESC")
        domain_counts = cursor.fetchall()
        print("\nDomain breakdown:")
        for d in domain_counts:
            print(f" - {d['domain']}: {d['cnt']} skills")
        assert len(domain_counts) >= 8, f"Expected at least 8 domains, got {len(domain_counts)}"

def test_candidate_assessments_page(client):
    res = client.get('/candidate/assessments')
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert 'Professional Skill Assessments' in html
    assert 'assessment-search' in html
    assert 'Programming' in html
    assert 'Web Dev' in html
    assert 'Database & SQL' in html
    assert 'Data Analytics' in html
    assert 'Data Science & AI' in html
    assert 'Cloud & DevOps' in html
    assert 'Software Engineering' in html
    assert 'Cybersecurity' in html
    assert 'Business Skills' in html
    print("[PASS] Candidate assessments marketplace rendered 200 OK with all domains and filters")

def test_api_candidate_assessments(client):
    # Test all
    res = client.get('/api/candidate/assessments')
    assert res.status_code == 200
    data = json.loads(res.data)
    assert data['success'] is True
    assert data['count'] >= 100
    print(f"[PASS] /api/candidate/assessments returned {data['count']} skills")

    # Test filtering by domain
    res_prog = client.get('/api/candidate/assessments?domain=Programming')
    data_prog = json.loads(res_prog.data)
    assert data_prog['success'] is True
    assert data_prog['count'] >= 15
    print(f"[PASS] Domain filter 'Programming' returned {data_prog['count']} skills")

    # Test search query
    res_search = client.get('/api/candidate/assessments?search=python')
    data_search = json.loads(res_search.data)
    assert data_search['success'] is True
    assert data_search['count'] >= 1
    assert any('python' in a['title'].lower() for a in data_search['assessments'])
    print(f"[PASS] Search filter 'python' returned {data_search['count']} matching skills")

def test_assessment_taking_grading_and_badge_flow(client):
    # Find or create a test user
    with db_cursor() as cursor:
        cursor.execute("SELECT id FROM user WHERE email = 'assessment_tester@dreamjobs.com'")
        u = cursor.fetchone()
        if not u:
            cursor.execute("INSERT INTO user (name, email, password) VALUES ('Assessment Tester', 'assessment_tester@dreamjobs.com', 'hashedpwd')")
            user_id = cursor.lastrowid
        else:
            user_id = u['id']
            
        cursor.execute("SELECT id, title, category FROM assessments WHERE category = 'Python' LIMIT 1")
        test_row = cursor.fetchone()
        test_id = test_row['id']

    with db_cursor() as cursor:
        cursor.execute("UPDATE user SET session_version = 1 WHERE id = %s", (user_id,))

    with client.session_transaction() as sess:
        sess['user_id'] = user_id
        sess['user_name'] = 'Assessment Tester'
        sess['session_version'] = 1
        sess['role'] = 'candidate'

    # 1. Start assessment
    res_start = client.post(f'/api/candidate/assessments/{test_id}/start')
    if res_start.status_code == 302:
        print("Redirect Location:", res_start.headers.get('Location'))
    assert res_start.status_code == 200
    start_data = json.loads(res_start.data)
    assert start_data['success'] is True
    attempt_id = start_data['attempt_id']
    print(f"[PASS] Assessment attempt started: ID {attempt_id}")

    # 2. Fetch attempt details and questions
    res_att = client.get(f'/api/candidate/assessments/attempt/{attempt_id}')
    assert res_att.status_code == 200
    att_data = json.loads(res_att.data)
    assert att_data['success'] is True
    questions = att_data['questions']
    assert len(questions) > 0
    print(f"[PASS] Attempt loaded {len(questions)} questions")

    # 3. Submit all correct answers (look up correct options in DB)
    with db_cursor() as cursor:
        cursor.execute("SELECT id, correct_option FROM assessment_questions WHERE assessment_id = %s", (test_id,))
        correct_map = {str(q['id']): q['correct_option'] for q in cursor.fetchall()}

    answers = {str(q['id']): correct_map[str(q['id'])] for q in questions if str(q['id']) in correct_map}
    res_submit = client.post(f'/api/candidate/assessments/attempt/{attempt_id}/submit', json={'answers': answers})
    assert res_submit.status_code == 200
    sub_data = json.loads(res_submit.data)
    assert sub_data['success'] is True
    assert sub_data['score'] == 100
    assert sub_data['passed'] is True
    print(f"[PASS] Assessment submitted successfully with 100% score (PASSED)")

    # 4. Verify skill badge in DB
    with db_cursor() as cursor:
        cursor.execute("SELECT * FROM skill_badges WHERE user_id = %s AND assessment_id = %s", (user_id, test_id))
        badge = cursor.fetchone()
        assert badge is not None
        assert badge['score'] == 100
        print(f"[PASS] Skill badge awarded: {badge['skill_name']} ({badge['badge_level']})")

        # 5. Verify sync to candidate_profile
        cursor.execute("SELECT skills FROM candidate_profile WHERE user_id = %s", (user_id,))
        prof = cursor.fetchone()
        assert prof is not None
        assert 'Python' in prof['skills']
        print(f"[PASS] Verified skill synced to candidate_profile: {prof['skills']}")

    # 6. Verify public candidate profile displays badge
    with db_cursor() as cursor:
        cursor.execute("UPDATE candidate_profile SET is_public = 1 WHERE user_id = %s", (user_id,))
    res_pub = client.get(f'/candidate/{user_id}')
    assert res_pub.status_code == 200
    pub_html = res_pub.get_data(as_text=True)
    assert 'Verified Skills' in pub_html
    assert 'Python' in pub_html
    print("[PASS] Public profile correctly displays Verified Skill badges")


def test_assessment_difficulty_filtering(client):
    """Verify filtering by Beginner, Intermediate, and Advanced difficulties."""
    # 1. Beginner
    res_beg = client.get('/api/candidate/assessments?difficulty=Beginner')
    assert res_beg.status_code == 200
    data_beg = json.loads(res_beg.data)
    assert data_beg['count'] == 25
    assert all(a['difficulty'] == 'Beginner' for a in data_beg['assessments'])

    # 2. Intermediate
    res_int = client.get('/api/candidate/assessments?difficulty=Intermediate')
    assert res_int.status_code == 200
    data_int = json.loads(res_int.data)
    assert data_int['count'] == 83
    assert all(a['difficulty'] == 'Intermediate' for a in data_int['assessments'])

    # 3. Advanced
    res_adv = client.get('/api/candidate/assessments?difficulty=Advanced')
    assert res_adv.status_code == 200
    data_adv = json.loads(res_adv.data)
    assert data_adv['count'] == 14
    assert all(a['difficulty'] == 'Advanced' for a in data_adv['assessments'])


def test_assessment_sorting_modes(client):
    """Verify all 5 sorting options work as specified with real data."""
    # 1. Popular First (ordered by total attempts descending)
    res_pop = client.get('/api/candidate/assessments?sort=popular')
    assert res_pop.status_code == 200
    data_pop = json.loads(res_pop.data)
    attempts = [a['total_attempts'] for a in data_pop['assessments']]
    assert attempts[0] >= attempts[-1]
    # Python (ID 1) has 22 attempts in our database and should be first
    assert data_pop['assessments'][0]['id'] == 1

    # 2. Newest First (ordered by created_at descending)
    res_new = client.get('/api/candidate/assessments?sort=new')
    assert res_new.status_code == 200
    data_new = json.loads(res_new.data)
    dates = [a['created_at'] for a in data_new['assessments'] if a.get('created_at')]
    assert dates == sorted(dates, reverse=True)

    # 3. Highest Rated (ordered by rating descending)
    res_rate = client.get('/api/candidate/assessments?sort=rating')
    assert res_rate.status_code == 200
    data_rate = json.loads(res_rate.data)
    ratings = [a['rating'] for a in data_rate['assessments']]
    assert ratings == sorted(ratings, reverse=True)

    # 4. Alphabetical (A-Z)
    res_alpha = client.get('/api/candidate/assessments?sort=alpha')
    assert res_alpha.status_code == 200
    data_alpha = json.loads(res_alpha.data)
    titles = [a['title'].lower() for a in data_alpha['assessments']]
    assert titles == sorted(titles)

    # 5. Default Catalog
    res_def = client.get('/api/candidate/assessments?sort=default')
    assert res_def.status_code == 200
    assert json.loads(res_def.data)['count'] == 122


def test_assessment_domain_chips_and_empty_state(client):
    """Verify domain chips, count badges, and empty state structure in HTML."""
    res = client.get('/candidate/assessments')
    assert res.status_code == 200
    html = res.get_data(as_text=True)

    # Horizontal domain container
    assert 'class="domain-chips-container"' in html
    assert 'overflow-x: auto;' in html

    # Domain chips with badges
    assert 'data-domain=""' in html
    assert 'data-domain="Programming"' in html
    assert 'data-domain="Web Development"' in html
    assert 'data-domain="Database & SQL"' in html
    assert 'data-domain="Data Analytics"' in html
    assert 'data-domain="Data Science & AI"' in html
    assert 'data-domain="Cloud & DevOps"' in html
    assert 'data-domain="Software Engineering"' in html
    assert 'data-domain="Cybersecurity"' in html
    assert 'data-domain="Business & Professional Skills"' in html
    assert 'chip-count' in html

    # Empty State with exact specifications
    assert 'id="no-assessments"' in html
    assert 'No assessments found' in html
    assert 'Try changing your filters or search criteria.' in html
    assert 'Clear Filters' in html
    assert 'onclick="resetAllFilters()"' in html


def test_combined_domain_difficulty_and_sorting(client):
    """Verify combined filtering: Difficulty + Domain + Sorting simultaneously."""
    res = client.get('/api/candidate/assessments?domain=Data%20Analytics&difficulty=Beginner&sort=rating')
    assert res.status_code == 200
    data = json.loads(res.data)
    assert data['success'] is True
    assert data['count'] > 0
    for a in data['assessments']:
        assert a['domain'] == 'Data Analytics'
        assert a['difficulty'] == 'Beginner'

    ratings = [a['rating'] for a in data['assessments']]
    assert ratings == sorted(ratings, reverse=True)


if __name__ == '__main__':
    pytest.main(['-s', __file__])

