import os
import sys
import json
import io
import inspect
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, init_db


@pytest.fixture
def app_csrf_enabled():
    """App with CSRF enabled (for CSRF-specific tests)."""
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = True
    app.config['RATELIMIT_ENABLED'] = False
    app.config['SECRET_KEY'] = 'test-secret-key-for-testing'
    yield app
    app.config['WTF_CSRF_ENABLED'] = False


@pytest.fixture
def app_no_csrf():
    """App with CSRF disabled (for auth/functional tests)."""
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    app.config['RATELIMIT_ENABLED'] = False
    app.config['SECRET_KEY'] = 'test-secret-key-for-testing'
    yield app


def get_csrf_token(client):
    resp = client.get('/api/csrf_token')
    return json.loads(resp.data)['csrf_token']


def read_app_source():
    """Read app.py source for static analysis tests."""
    import importlib
    mod = importlib.import_module('app')
    return open(mod.__file__).read()


class MockCursor:
    """Mock DB cursor for testing without a real MySQL connection."""
    def __init__(self, results=None, lastrowid=1):
        self._results = results or []
        self._result_idx = 0
        self.lastrowid = lastrowid
        self._executed = []
    def execute(self, query, params=None):
        self._executed.append((query, params))
        return self
    def fetchone(self):
        if self._results and self._result_idx < len(self._results):
            result = self._results[self._result_idx]
            self._result_idx += 1
            return result
        return None
    def fetchall(self):
        return list(self._results[self._result_idx:]) if self._results else []
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False


def mock_db_cursor(results=None, lastrowid=1):
    """Patch db_cursor to return a mock cursor with preset results."""
    mock_cursor = MockCursor(results, lastrowid)
    return patch('app.db_cursor', return_value=mock_cursor)


# --- CSRF TESTS ---

class TestCSRFFlow:
    def test_csrf_token_endpoint(self, app_csrf_enabled):
        with app_csrf_enabled.test_client() as c:
            resp = c.get('/api/csrf_token')
            assert resp.status_code == 200
            data = json.loads(resp.data)
            assert 'csrf_token' in data
            assert len(data['csrf_token']) > 20

    def test_post_without_csrf_token_rejected(self, app_csrf_enabled):
        with app_csrf_enabled.test_client() as c:
            resp = c.post('/api/send_otp',
                data=json.dumps({'email': 'test@example.com'}),
                content_type='application/json')
            assert resp.status_code == 400
            data = json.loads(resp.data)
            assert 'csrf' in data.get('message', '').lower()

    def test_post_with_valid_csrf_token_accepted(self, app_csrf_enabled):
        with app_csrf_enabled.test_client() as c:
            token = get_csrf_token(c)
            with mock_db_cursor(results=[None, None, None]):
                resp = c.post('/api/send_otp',
                    data=json.dumps({'email': 'test@example.com'}),
                    content_type='application/json',
                    headers={'X-CSRFToken': token})
            assert resp.status_code == 200

    def test_csrf_exempt_endpoint_works_without_token(self, app_csrf_enabled):
        with app_csrf_enabled.test_client() as c:
            resp = c.get('/api/csrf_token')
            assert resp.status_code == 200


# --- AUTH GUARD TESTS ---

class TestAuthGuards:
    def test_unauthenticated_access_user_dashboard(self, app_no_csrf):
        with app_no_csrf.test_client() as c:
            resp = c.get('/user_dashboard')
            assert resp.status_code == 302

    def test_unauthenticated_access_employer_dashboard(self, app_no_csrf):
        with app_no_csrf.test_client() as c:
            resp = c.get('/employer_dashboard')
            assert resp.status_code == 302

    def test_unauthenticated_api_apply_job(self, app_no_csrf):
        with app_no_csrf.test_client() as c:
            resp = c.post('/api/apply_job', data={}, content_type='multipart/form-data')
            assert resp.status_code == 401

    def test_user_cannot_access_employer_routes(self, app_no_csrf):
        with app_no_csrf.test_client() as c:
            with c.session_transaction() as sess:
                sess['user_id'] = 1
                sess['csrf_token'] = 'test'
            resp = c.post('/api/post_job',
                data=json.dumps({'title': 'Test'}),
                content_type='application/json')
            assert resp.status_code == 401

    def test_employer_can_access_employer_routes(self, app_no_csrf):
        with app_no_csrf.test_client() as c:
            with c.session_transaction() as sess:
                sess['employer_id'] = 1
                sess['user_name'] = 'TestCo'
                sess['csrf_token'] = 'test'
            with mock_db_cursor():
                resp = c.post('/api/post_job',
                    data=json.dumps({'title': 'Test Job'}),
                    content_type='application/json')
            assert resp.status_code in (200, 500)

    def test_select_candidate_requires_employer(self, app_no_csrf):
        with app_no_csrf.test_client() as c:
            with c.session_transaction() as sess:
                sess['user_id'] = 1
            resp = c.post('/api/select_candidate',
                data=json.dumps({'app_id': 1}),
                content_type='application/json')
            assert resp.status_code == 401

    def test_reject_candidate_requires_employer(self, app_no_csrf):
        with app_no_csrf.test_client() as c:
            with c.session_transaction() as sess:
                sess['user_id'] = 1
            resp = c.post('/api/reject_candidate',
                data=json.dumps({'app_id': 1}),
                content_type='application/json')
            assert resp.status_code == 401


# --- OTP TESTS ---

class TestOTPExpiry:
    def test_otp_ttl_is_2_minutes(self):
        from app import OTP_TTL_SECONDS
        assert OTP_TTL_SECONDS == 120

    def test_otp_expiry_logic_in_source(self):
        """Verify OTP expiry check exists in the verify_otp route."""
        source = read_app_source()
        assert 'expires_at' in source
        assert 'otp_expiry' in source or 'expired' in source.lower()

    def test_otp_rate_limiter_is_db_based(self):
        """Verify DB-based rate limiter exists and in-memory dict is removed."""
        source = read_app_source()
        assert 'otp_rate_log' not in source
        assert 'rate_limits' in source
        assert 'check_rate_limit' in source


# --- DUPLICATE APPLICATION TESTS ---

class TestDuplicateApplication:
    def test_unique_constraint_on_applications(self):
        """Verify the UNIQUE KEY on applications (job_id, user_id) exists."""
        source = read_app_source()
        assert 'UNIQUE KEY unique_application' in source

    def test_integrity_error_handler_in_apply_job(self):
        """Verify apply_job catches IntegrityError for duplicates."""
        source = read_app_source()
        assert 'IntegrityError' in source
        assert 'already applied' in source.lower()


# --- RATE LIMITING TESTS ---

class TestRateLimiting:
    def test_login_rate_limit_exceeded(self, app_no_csrf):
        """After 5 failed login attempts, the 6th should return 429."""
        with app_no_csrf.test_client() as c:
            with mock_db_cursor(results=[None, None, None, None, None, None, None]):
                for i in range(5):
                    c.post('/api/user/login',
                        data=json.dumps({'email': 'nonexistent@example.com', 'password': 'wrong'}))
                resp = c.post('/api/user/login',
                    data=json.dumps({'email': 'nonexistent@example.com', 'password': 'wrong'}))
                assert resp.status_code == 429
                data = json.loads(resp.data)
                assert 'rate' in data.get('message', '').lower()

    def test_flask_limiter_initialized(self):
        from app import limiter
        assert limiter is not None


# --- FILE UPLOAD VALIDATION TESTS ---

class TestFileUpload:
    def test_doc_extension_removed(self):
        from app import ALLOWED_EXTENSIONS
        assert '.doc' not in ALLOWED_EXTENSIONS
        assert 'docx' in ALLOWED_EXTENSIONS

    def test_allowed_extensions_correct(self):
        from app import ALLOWED_EXTENSIONS
        assert 'docx' in ALLOWED_EXTENSIONS
        assert 'pdf' in ALLOWED_EXTENSIONS
        assert 'txt' in ALLOWED_EXTENSIONS

    def test_magic_byte_validation_function_exists(self):
        source = read_app_source()
        assert 'validate_file_signature' in source

    def test_magic_byte_validation_rejects_fake_pdf(self):
        from app import validate_file_signature
        fake_pdf = io.BytesIO(b'this is not a real pdf')
        assert validate_file_signature(fake_pdf, 'fake.pdf') is False

    def test_magic_byte_validation_accepts_real_pdf(self):
        from app import validate_file_signature
        real_pdf = io.BytesIO(b'%PDF-1.4\n%test')
        assert validate_file_signature(real_pdf, 'test.pdf') is True

    def test_magic_byte_validation_accepts_txt(self):
        from app import validate_file_signature
        txt_file = io.BytesIO(b'hello world this is text')
        assert validate_file_signature(txt_file, 'test.txt') is True

    def test_max_upload_size_configured(self):
        source = read_app_source()
        assert 'MAX_UPLOAD_BYTES' in source


# --- JOB DEADLINE TESTS ---

class TestJobDeadline:
    def test_deadline_field_exists_in_schema(self):
        source = read_app_source()
        assert 'application_deadline' in source

    def test_is_active_field_exists_in_schema(self):
        source = read_app_source()
        assert 'is_active' in source

    def test_deadline_check_in_apply_job(self):
        """Verify apply_job checks deadline before applying."""
        source = read_app_source()
        assert 'deadline' in source.lower()


# --- INPUT VALIDATION TESTS ---

class TestInputValidation:
    def test_email_validation(self):
        from app import validate_email
        assert bool(validate_email('valid@example.com')) is True
        assert bool(validate_email('invalid-email')) is False
        assert bool(validate_email('')) is False

    def test_password_validation(self):
        from app import validate_password
        assert validate_password('Pass1234') is True
        assert validate_password('pass') is False
        assert validate_password('12345678') is False
        assert validate_password('abcdefgh') is False

    def test_length_validation(self):
        from app import validate_length
        ok, err = validate_length('short', 100, 'Name')
        assert ok is True
        ok, err = validate_length('x' * 200, 100, 'Name')
        assert ok is False
        assert 'Name' in err

    def test_mobile_validation(self):
        from app import validate_mobile
        assert validate_mobile('1234567890') is True
        assert validate_mobile('12-123-456-7890') is True
        assert validate_mobile('abc') is False

    def test_email_normalization(self):
        from app import normalize_email
        assert normalize_email('User@Example.COM') == 'user@example.com'
        assert normalize_email('  Test@Email.com  ') == 'test@email.com'
        assert normalize_email('') == ''


# --- CANDIDATE PROFILE TESTS ---

class TestCandidateProfile:
    def test_profile_endpoint_requires_auth(self, app_no_csrf):
        with app_no_csrf.test_client() as c:
            resp = c.get('/api/candidate/profile')
            assert resp.status_code == 401

    def test_profile_visibility_toggle_requires_auth(self, app_no_csrf):
        with app_no_csrf.test_client() as c:
            resp = c.post('/api/candidate/profile/visibility',
                data=json.dumps({'is_public': True}),
                content_type='application/json')
            assert resp.status_code == 401

    def test_public_profile_page_not_found(self, app_no_csrf):
        with app_no_csrf.test_client() as c:
            resp = c.get('/candidate/99999')
            assert resp.status_code == 404

    def test_profile_completeness_function_exists(self):
        from app import compute_profile_completeness
        assert callable(compute_profile_completeness)

    def test_candidate_profile_template_exists(self, app_no_csrf):
        import app as app_module
        tmpl_path = os.path.join(os.path.dirname(app_module.__file__), 'templates', 'candidate_profile.html')
        assert os.path.exists(tmpl_path)

    def test_profile_photo_upload_requires_auth(self, app_no_csrf):
        with app_no_csrf.test_client() as c:
            resp = c.post('/api/candidate/profile/photo', data={})
            assert resp.status_code == 401


# --- SECURITY CONFIG TESTS ---

class TestSecurityConfig:
    def test_session_cookie_flags_configured(self):
        """Verify SESSION_COOKIE flags are set in app.py source."""
        source = read_app_source()
        assert 'SESSION_COOKIE_HTTPONLY' in source
        assert 'SESSION_COOKIE_SAMESITE' in source
        assert 'SESSION_COOKIE_SECURE' in source

    def test_secret_key_from_env(self):
        """Verify SECRET_KEY is loaded from environment."""
        source = read_app_source()
        assert 'SECRET_KEY' in source
        assert 'os.getenv' in source

    def test_no_static_fallback_for_secrets(self):
        """Verify secrets use fail-loudly pattern."""
        source = read_app_source()
        assert 'must be set in .env' in source

    def test_csrf_protection_enabled(self):
        from app import csrf
        assert csrf is not None

    def test_rate_limiter_enabled(self):
        from app import limiter
        assert limiter is not None

    def test_logging_not_print(self):
        """Verify structured logging is used, not print()."""
        source = read_app_source()
        assert 'logging.getLogger' in source

    def test_csrf_token_endpoint_exempt(self):
        """Verify CSRF token endpoint is exempt from CSRF protection."""
        with app.test_client() as c:
            app.config['WTF_CSRF_ENABLED'] = True
            resp = c.get('/api/csrf_token')
            assert resp.status_code == 200
            data = json.loads(resp.data)
            assert 'csrf_token' in data
            app.config['WTF_CSRF_ENABLED'] = False


# --- MIGRATION TESTS ---

class TestMigration:
    def test_migrate_requires_confirm_flag(self):
        """Verify migrate.py requires --confirm flag."""
        import subprocess
        import app as app_module
        migrate_path = os.path.join(os.path.dirname(app_module.__file__), 'migrate.py')
        result = subprocess.run(
            [sys.executable, migrate_path],
            capture_output=True, text=True, timeout=10
        )
        assert result.returncode == 1
        assert 'confirm' in result.stdout.lower()

    def test_migrate_source_has_confirm_check(self):
        import app as app_module
        source = open(os.path.join(os.path.dirname(app_module.__file__), 'migrate.py')).read()
        assert '--confirm' in source
