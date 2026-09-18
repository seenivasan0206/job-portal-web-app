import os
import csv
import imghdr
import uuid
import time
import threading
import re
import json
import random
import string
import smtplib
import logging
from logging.handlers import RotatingFileHandler
import contextlib
import io
import hashlib
from email.message import EmailMessage
import html
import socket
import ipaddress
import urllib.parse
from functools import wraps
import requests
from datetime import datetime, timedelta, time as dt_time, date as dt_date
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, send_from_directory, make_response, flash
from flask_wtf.csrf import CSRFProtect, generate_csrf, CSRFError
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import mysql.connector
from mysql.connector import errorcode
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import bleach
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from pypdf import PdfReader
from docx import Document
from resume_intelligence import analyze_resume_pipeline, extract_resume_text_with_report
from resume_intelligence.scoring.job_match_score import analyze_and_match_job_description
from resume_intelligence.nlp.skill_extraction import extract_skills_with_confidence
from resume_intelligence.ml.similarity_model import compute_semantic_similarity, get_sentence_transformer
from assessment_data import ASSESSMENTS_DATA, seed_assessments_db
from salary_data import (
    seed_salary_benchmarks, ROLES_BY_CATEGORY, ALL_JOB_ROLES,
    ALL_LOCATIONS, LOCATION_METADATA, EXPERIENCE_BANDS, INDUSTRIES
)
from job_recommendation_engine import (
    normalize_skill, match_skill_lists,
    get_candidate_recommendation_profile,
    calculate_job_recommendation_score,
    recommend_jobs_for_candidate
)

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOGS_DIR = os.path.join(BASE_DIR, 'logs')
if not os.path.exists(LOGS_DIR):
    os.makedirs(LOGS_DIR, exist_ok=True)

# --- LOGGING (structured, no secrets logged, rotating on disk) ---
log_formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s')

logger = logging.getLogger('securehire')
logger.setLevel(logging.INFO)

# Avoid duplicate handlers if reloaded
if not logger.handlers:
    _console_handler = logging.StreamHandler()
    _console_handler.setFormatter(log_formatter)
    logger.addHandler(_console_handler)

    _file_handler = RotatingFileHandler(
        os.path.join(LOGS_DIR, 'securehire.log'),
        maxBytes=10 * 1024 * 1024,  # 10MB per file
        backupCount=5,               # keep 5 rotated backups (max 50MB total)
        encoding='utf-8'
    )
    _file_handler.setFormatter(log_formatter)
    logger.addHandler(_file_handler)

app = Flask(__name__, static_folder=os.path.join(BASE_DIR, 'static'), template_folder=os.path.join(BASE_DIR, 'templates'))

# --- FAIL LOUDLY: all secrets must come from the environment ---
FLASK_SECRET_KEY = os.getenv('FLASK_SECRET_KEY')
EMAIL_ADDRESS = os.getenv('EMAIL_ADDRESS')
EMAIL_PASSWORD = os.getenv('EMAIL_PASSWORD')
if EMAIL_PASSWORD:
    EMAIL_PASSWORD = EMAIL_PASSWORD.replace(' ', '')
DB_USER = os.getenv('DB_USER')
DB_PASSWORD = os.getenv('DB_PASSWORD')
DB_HOST = os.getenv('DB_HOST', 'localhost')
DB_NAME = os.getenv('DB_NAME')

_missing = [
    (FLASK_SECRET_KEY, 'FLASK_SECRET_KEY'),
    (EMAIL_ADDRESS, 'EMAIL_ADDRESS'),
    (EMAIL_PASSWORD, 'EMAIL_PASSWORD'),
    (DB_USER, 'DB_USER'),
    (DB_PASSWORD, 'DB_PASSWORD'),
    (DB_NAME, 'DB_NAME'),
]
for _val, _name in _missing:
    if not _val:
        raise RuntimeError(f"{_name} must be set in .env — no hardcoded fallback for security")
app.secret_key = FLASK_SECRET_KEY
app.permanent_session_lifetime = timedelta(days=7)
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)

# --- SESSION COOKIE SECURITY ---
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
if os.getenv('FLASK_ENV') == 'production' or os.getenv('SESSION_COOKIE_SECURE', '0') == '1':
    app.config['SESSION_COOKIE_SECURE'] = True

# --- SESSION FINGERPRINT CONFIG ---
# IP-based session binding can cause random logouts for mobile/VPN users.
# Disabled by default; set STRICT_SESSION_FINGERPRINT=1 to enable IP binding.
app.config['STRICT_SESSION_FINGERPRINT'] = os.getenv('STRICT_SESSION_FINGERPRINT', '0') == '1'

# --- STATIC FILE CACHE CONTROL ---
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0

# --- CSRF PROTECTION (Flask-WTF) ---
csrf = CSRFProtect(app)


@csrf.exempt
@app.route('/api/csrf_token', methods=['GET'])
def get_csrf_token():
    token = generate_csrf()
    return jsonify({'csrf_token': token})

# --- FLASK-LIMITER (global + per-route) ---
_ratelimit_storage_uri = os.getenv('RATELIMIT_STORAGE_URI', 'memory://')
_ratelimit_storage_options = {}
if _ratelimit_storage_uri.startswith(('redis://', 'rediss://')):
    _ratelimit_storage_options = {'socket_connect_timeout': 2, 'socket_timeout': 2}

limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["200 per minute"],
    storage_uri=_ratelimit_storage_uri,
    storage_options=_ratelimit_storage_options if _ratelimit_storage_options else None,
    in_memory_fallback=["200 per minute"],
    in_memory_fallback_enabled=True,
    swallow_errors=True,
)


@limiter.request_filter
def _limiter_request_filter():
    return bool(app.config.get('TESTING') or not app.config.get('RATELIMIT_ENABLED', True))


# --- CONFIGURATION ---
UPLOAD_FOLDER = 'resumes'
ALLOWED_EXTENSIONS = {'txt', 'pdf', 'doc', 'docx'}
ALLOWED_PHOTO_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
MAX_UPLOAD_MB = int(os.getenv('MAX_UPLOAD_MB', '5'))
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024
app.config['MAX_CONTENT_LENGTH'] = MAX_UPLOAD_BYTES + 512 * 1024
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# --- DATABASE CONFIGURATION ---
db_config = {
    'user': DB_USER,
    'password': DB_PASSWORD,
    'host': DB_HOST,
    'database': DB_NAME,
}

OTP_TTL_SECONDS = 120  # 2 minutes, matching email copy
LOGIN_RATE_LIMIT = "5 per 5 minutes"
OTP_RATE_LIMIT = "3 per minute"

# --- SECURITY CONSTANTS ---
MAX_FAILED_ATTEMPTS = 3
LOCKOUT_DURATION_MINUTES = 90   # 1.5 hours (change to 60 or 120 for exactly 1 or 2 hours)
PASSWORD_HISTORY_LIMIT = 5       # Remember last 5 passwords

# --- VALIDATION HELPERS ---
EMAIL_REGEX = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')
MOBILE_REGEX = re.compile(r'^[0-9+\-\s]{7,20}$')


def normalize_email(email):
    """Lowercase and strip email for case-insensitive comparison."""
    if not email:
        return ''
    return str(email).strip().lower()


def validate_email(email):
    return bool(email) and EMAIL_REGEX.match(str(email).strip().lower())


COMMON_PASSWORDS = {
    'password', 'password1', 'password123', '12345678', '123456789', '1234567890',
    'qwerty123', 'admin123', 'welcome1', 'letmein1', 'iloveyou1', 'monkey123',
    'dragon123', 'shadow123', 'master123', 'trustno1', 'superman1', 'pass1234',
    'abc12345', 'football1', 'baseball1', 'login123', 'default123', 'secret123',
    'test1234', 'changeme1', 'hunter123', 'pass@123', 'admin@123', 'password@1',
}


def validate_password(password):
    """Min 8 chars, at least one letter and one number, not purely numeric, not in common blocklist."""
    if not password or len(password) < 8:
        return False
    if str(password).isdigit():
        return False
    if str(password).strip().lower() in COMMON_PASSWORDS:
        return False
    return bool(re.search(r'[a-zA-Z]', password) and re.search(r'[0-9]', password))


def validate_mobile(mobile):
    if not mobile:
        return True  # mobile is optional
    return bool(MOBILE_REGEX.match(str(mobile).strip()))


def validate_length(value, max_len, field_name):
    if value and len(str(value)) > max_len:
        return False, f"{field_name} is too long (max {max_len} characters)"
    return True, None


# --- XSS SANITIZATION HELPERS (BLEACH) ---
def sanitize_text(val):
    """Strip all HTML tags and dangerous attributes from plain text inputs."""
    if val is None:
        return val
    if isinstance(val, str):
        return bleach.clean(val.strip(), tags=[], attributes={}, strip=True)
    return val


def sanitize_html(val, allowed_tags=None, allowed_attributes=None):
    """Sanitize HTML inputs allowing safe formatting tags."""
    if val is None:
        return val
    if isinstance(val, str):
        tags = allowed_tags or ['b', 'i', 'u', 'em', 'strong', 'p', 'br', 'ul', 'ol', 'li', 'span', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6']
        attrs = allowed_attributes or {'span': ['class'], 'p': ['class'], 'li': ['class']}
        return bleach.clean(val.strip(), tags=tags, attributes=attrs, strip=True)
    return val


# --- ENUM & DOMAIN WHITELISTS (SERVER-SIDE INPUT VALIDATION) ---
ALLOWED_APPLICATION_STATUSES = {'Applied', 'Shortlisted', 'Interview', 'Interviewing', 'Selected', 'Rejected', 'Withdrawn'}
ALLOWED_JOB_STATUSES = {'Draft', 'Pending', 'Published', 'Closed', 'Deleted'}
ALLOWED_WORKPLACE_TYPES = {'On-site', 'Onsite', 'Remote', 'Hybrid'}
ALLOWED_JOB_TYPES = {'Full-time', 'Part-time', 'Contract', 'Internship'}
ALLOWED_EXPERIENCE_LEVELS = {'Fresher', '1-3 years', '3-5 years', '5+ years'}
ALLOWED_VERIFICATION_STATUSES = {'pending', 'verified', 'rejected'}
ALLOWED_ASSESSMENT_DIFFICULTIES = {'Beginner', 'Intermediate', 'Advanced'}



def check_rate_limit(rate_key, action, limit=5, window_seconds=300):
    """DB-backed rate limiter keyed by (rate_key, action). Works across workers."""
    if app.config.get('RATELIMIT_ENABLED') is False:
        return True
    now = datetime.now()
    with db_cursor(dictionary=True) as cursor:
        cursor.execute(
            "SELECT count, window_start FROM rate_limits WHERE rate_key = %s AND action = %s",
            (rate_key, action)
        )
        row = cursor.fetchone()
        if row:
            count = row['count']
            window_start = row['window_start']
            elapsed = (now - window_start).total_seconds()
            if elapsed < window_seconds:
                if count >= limit:
                    return False
                cursor.execute(
                    "UPDATE rate_limits SET count = count + 1 WHERE rate_key = %s AND action = %s",
                    (rate_key, action)
                )
                return True
            else:
                cursor.execute(
                    "UPDATE rate_limits SET count = 1, window_start = %s WHERE rate_key = %s AND action = %s",
                    (now, rate_key, action)
                )
                return True
        else:
            cursor.execute(
                "INSERT INTO rate_limits (rate_key, action, count, window_start) VALUES (%s, %s, 1, %s)",
                (rate_key, action, now)
            )
            return True


@contextlib.contextmanager
def db_cursor(dictionary=True):
    """Yield a DB cursor inside a transaction; always closes conn/cursor.

    Commits on success, rolls back on exception, and guarantees the
    connection is closed even if the caller raises.
    """
    conn = mysql.connector.connect(**db_config)
    cur = conn.cursor(dictionary=dictionary)
    try:
        yield cur
        try:
            if getattr(cur, 'with_rows', False):
                cur.fetchall()
        except Exception:
            pass
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


def allowed_file(filename, extensions=None):
    if extensions is None:
        extensions = ALLOWED_EXTENSIONS
    return '.' in filename and filename.rsplit('.', 1)[-1].lower() in extensions


def validate_file_signature(stream, filename):
    """Validate file magic bytes match the claimed extension."""
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    if ext in ALLOWED_PHOTO_EXTENSIONS:
        detected = imghdr.what(stream)
        if detected == 'jpeg':
            detected = 'jpg'
        if detected is None and ext == 'webp':
            stream.seek(0)
            header = stream.read(12)
            stream.seek(0)
            if header[:4] == b'RIFF' and header[8:12] == b'WEBP':
                detected = 'webp'
        return detected in ALLOWED_PHOTO_EXTENSIONS
    stream.seek(0)
    header = stream.read(8)
    stream.seek(0)
    if ext == 'pdf':
        return header.startswith(b'%PDF')
    elif ext == 'docx':
        return header[:2] == b'PK'
    elif ext == 'doc':
        return header[:8] == b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'
    elif ext == 'txt':
        return True  # text files have no magic bytes
    return False


def extract_text(stream, filename):
    """Extract plain text from an uploaded resume using a proper parser."""
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    text = ''
    try:
        if ext == 'pdf':
            reader = PdfReader(stream)
            for page in reader.pages:
                text += (page.extract_text() or '') + '\n'
        elif ext == 'docx':
            doc = Document(stream)
            text = '\n'.join(p.text for p in doc.paragraphs)
        else:
            text = stream.read().decode('utf-8', errors='ignore')
    except Exception as e:
        logger.error(f"Text extraction error ({ext}): {e}")
        try:
            stream.seek(0)
            text = stream.read().decode('utf-8', errors='ignore')
        except Exception:
            text = ''
    return text


def check_notification_preference(user_id=None, employer_id=None, notification_type='general'):
    """
    Checks if the user or employer has opted in to receive notifications of this type.
    Security events are always delivered.
    """
    if notification_type in ('security_event', 'password_changed', 'security_alert', 'account_lockout'):
        return True

    pref_column_map = {
        'new_application': 'application_updates',
        'application_submitted': 'application_updates',
        'application_status_change': 'application_updates',
        'status_updated': 'application_updates',
        'application_withdrawn': 'application_updates',
        'shortlisting': 'shortlist_updates',
        'rejection': 'application_updates',
        'interview_invitation': 'interview_reminders',
        'interview_scheduled': 'interview_reminders',
        'interview_reminder': 'interview_reminders',
        'interview_rescheduled': 'interview_reminders',
        'interview_cancelled': 'interview_reminders',
        'new_message': 'messages',
        'recommended_job': 'recommended_jobs',
        'job_alert': 'job_alerts',
        'assessment_result': 'assessment_results',
    }

    col = pref_column_map.get(notification_type)
    if not col:
        return True

    try:
        with db_cursor() as cursor:
            if user_id:
                cursor.execute(f"SELECT {col} FROM notification_preferences WHERE user_id = %s", (user_id,))
                row = cursor.fetchone()
                if row and row.get(col) is not None:
                    return bool(row[col])
            elif employer_id:
                cursor.execute(f"SELECT {col} FROM notification_preferences WHERE employer_id = %s", (employer_id,))
                row = cursor.fetchone()
                if row and row.get(col) is not None:
                    return bool(row[col])
    except Exception as e:
        logger.warning(f"Error checking notification preferences: {e}")

    return True


def create_notification(user_id=None, employer_id=None, notification_type='general', title=None, message='', action_url=None, metadata=None):
    """
    Central dispatcher for platform notifications.
    Strictly isolates user_id and employer_id destinations.
    Enforces user preference filtering.
    """
    if not user_id and not employer_id:
        logger.warning("create_notification called without recipient user_id or employer_id")
        return False

    if user_id and employer_id:
        employer_id = None

    if not check_notification_preference(user_id=user_id, employer_id=employer_id, notification_type=notification_type):
        logger.info(f"Notification {notification_type} suppressed by recipient preferences (user_id={user_id}, employer_id={employer_id})")
        return False

    if not title:
        default_titles = {
            'new_application': 'New Application Received',
            'application_submitted': 'Application Submitted Successfully',
            'application_status_change': 'Application Status Updated',
            'shortlisting': 'Application Shortlisted! 🎉',
            'rejection': 'Application Update',
            'interview_invitation': 'Interview Invitation Scheduled 📅',
            'interview_scheduled': 'Interview Confirmed 📅',
            'interview_reminder': 'Upcoming Interview Reminder ⏰',
            'interview_rescheduled': 'Interview Rescheduled 📅',
            'interview_cancelled': 'Interview Cancelled',
            'new_message': 'New Direct Message 💬',
            'recommended_job': 'New Job Recommendation 🎯',
            'job_alert': 'Job Alert 🔔',
            'assessment_result': 'Skill Assessment Result 🏆',
            'security_event': 'Security Alert 🔒',
        }
        title = default_titles.get(notification_type, 'Notification')

    try:
        with db_cursor() as cursor:
            cursor.execute("""
                INSERT INTO notifications (user_id, employer_id, notification_type, title, message, action_url, is_read)
                VALUES (%s, %s, %s, %s, %s, %s, 0)
            """, (user_id, employer_id, notification_type, title, message, action_url))
            return True
    except Exception as e:
        logger.error(f"Failed to create notification: {e}")
        return False


def notify_user(user_id, message, notification_type='general', title=None, action_url=None):
    """Backward-compatible wrapper for candidate notifications."""
    return create_notification(user_id=user_id, notification_type=notification_type, title=title, message=message, action_url=action_url)


def notify_employer(employer_id, message, notification_type='general', title=None, action_url=None):
    """Convenience wrapper for employer notifications."""
    return create_notification(employer_id=employer_id, notification_type=notification_type, title=title, message=message, action_url=action_url)

# --- SENTENCE-TRANSFORMERS MODEL (eagerly loaded at startup) ---
_SENTENCE_MODEL = None


def load_sentence_model():
    """Load the sentence-transformers model at application startup.

    This prevents the first search request from blocking while the model
    downloads/compiles. If the library is missing or loading fails, the
    app falls back to TF-IDF search automatically.
    """
    global _SENTENCE_MODEL
    try:
        from sentence_transformers import SentenceTransformer
        _SENTENCE_MODEL = SentenceTransformer('all-MiniLM-L6-v2')
    except ImportError:
        logger.info("sentence-transformers not installed; using TF-IDF fallback")
    except Exception as e:
        logger.warning(f"Failed to load sentence-transformers model: {e}")


def _get_sentence_model():
    """Return the pre-loaded sentence model, or None if unavailable."""
    return _SENTENCE_MODEL

def require_admin():
    """Check if current session is an authenticated admin user."""
    return bool('user_id' in session and (session.get('is_admin') or session.get('role') == 'admin'))


def admin_required(f):
    """Decorator ensuring that the endpoint requires an authenticated administrator."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not require_admin():
            if request.is_json or request.path.startswith('/api/admin') or request.headers.get('Accept') == 'application/json':
                return jsonify({'success': False, 'message': 'Unauthorized. Administrator access required.'}), 403
            flash("Administrator login required to access this area.", "error")
            return redirect(url_for('admin_login_page', next=request.path))
        return f(*args, **kwargs)
    return decorated_function


# --- SECURITY HELPERS ---

def _clear_expired_lockouts():
    """Clear expired lockouts from login_attempts table."""
    now = datetime.now()
    with db_cursor() as cur:
        cur.execute(
            "UPDATE login_attempts SET is_locked = FALSE, attempt_count = 0, locked_until = NULL "
            "WHERE is_locked = TRUE AND locked_until IS NOT NULL AND locked_until < %s",
            (now,)
        )

def _record_failed_login(email, account_type):
    """Record a failed login attempt and lock if threshold exceeded."""
    email = normalize_email(email)
    ip = request.remote_addr or 'unknown'
    now = datetime.now()
    lock_until = now + timedelta(minutes=LOCKOUT_DURATION_MINUTES)
    
    with db_cursor() as cur:
        # Insert or update login attempt
        cur.execute("""
            INSERT INTO login_attempts (email, account_type, ip_address, attempt_count, last_attempt, is_locked, locked_until)
            VALUES (%s, %s, %s, 1, %s, FALSE, NULL)
            ON DUPLICATE KEY UPDATE
                attempt_count = attempt_count + 1,
                last_attempt = %s,
                ip_address = %s,
                is_locked = CASE WHEN attempt_count >= %s THEN TRUE ELSE FALSE END,
                locked_until = CASE WHEN attempt_count >= %s THEN %s ELSE NULL END
        """, (email, account_type, ip, now, now, ip, MAX_FAILED_ATTEMPTS, MAX_FAILED_ATTEMPTS, lock_until))
        
        # Get current attempt count
        cur.execute("SELECT attempt_count, is_locked, locked_until FROM login_attempts WHERE email = %s AND account_type = %s", (email, account_type))
        row = cur.fetchone()
        if row:
            return row['attempt_count'], row['is_locked'], row['locked_until']
    return 1, False, None

def _is_account_locked(email, account_type):
    """Check if account is locked and return (is_locked, minutes_remaining)."""
    email = normalize_email(email)
    now = datetime.now()
    with db_cursor() as cur:
        cur.execute(
            "SELECT is_locked, locked_until FROM login_attempts WHERE email = %s AND account_type = %s",
            (email, account_type)
        )
        row = cur.fetchone()
        if not row or not row['is_locked'] or not row['locked_until']:
            return False, 0
        if row['locked_until'] <= now:
            # Lock expired, auto-unlock
            cur.execute(
                "UPDATE login_attempts SET is_locked = FALSE, attempt_count = 0, locked_until = NULL WHERE email = %s AND account_type = %s",
                (email, account_type)
            )
            return False, 0
        minutes = int((row['locked_until'] - now).total_seconds() / 60) + 1
        return True, minutes

def _reset_login_attempts(email, account_type, ip=None):
    """Reset login attempts on successful login."""
    email = normalize_email(email)
    with db_cursor() as cur:
        cur.execute(
            "DELETE FROM login_attempts WHERE email = %s AND account_type = %s",
            (email, account_type)
        )
        if ip:
            rate_key = f"{email}:{ip}"
            cur.execute(
                "DELETE FROM rate_limits WHERE rate_key = %s AND action = 'login_attempt'",
                (rate_key,)
            )

def _check_password_history(user_id, employer_id, new_password):
    """Check if new password matches any in history. Returns True if OK to use."""
    if user_id:
        with db_cursor() as cur:
            cur.execute("SELECT password_hash FROM password_history WHERE user_id = %s ORDER BY created_at DESC LIMIT %s", (user_id, PASSWORD_HISTORY_LIMIT))
            rows = cur.fetchall()
            for row in rows:
                if check_password_hash(row['password_hash'], new_password):
                    return False
    elif employer_id:
        with db_cursor() as cur:
            cur.execute("SELECT password_hash FROM password_history WHERE employer_id = %s ORDER BY created_at DESC LIMIT %s", (employer_id, PASSWORD_HISTORY_LIMIT))
            rows = cur.fetchall()
            for row in rows:
                if check_password_hash(row['password_hash'], new_password):
                    return False
    return True

def _store_password_history(user_id, employer_id, password_hash):
    """Store password hash in history, keeping only the last PASSWORD_HISTORY_LIMIT entries."""
    if user_id:
        with db_cursor() as cur:
            cur.execute("INSERT INTO password_history (user_id, password_hash) VALUES (%s, %s)", (user_id, password_hash))
            # Delete old entries beyond limit
            cur.execute("""
                DELETE FROM password_history 
                WHERE user_id = %s AND id NOT IN (
                    SELECT id FROM (
                        SELECT id FROM password_history WHERE user_id = %s ORDER BY created_at DESC LIMIT %s
                    ) tmp
                )
            """, (user_id, user_id, PASSWORD_HISTORY_LIMIT))
    elif employer_id:
        with db_cursor() as cur:
            cur.execute("INSERT INTO password_history (employer_id, password_hash) VALUES (%s, %s)", (employer_id, password_hash))
            cur.execute("""
                DELETE FROM password_history 
                WHERE employer_id = %s AND id NOT IN (
                    SELECT id FROM (
                        SELECT id FROM password_history WHERE employer_id = %s ORDER BY created_at DESC LIMIT %s
                    ) tmp
                )
            """, (employer_id, employer_id, PASSWORD_HISTORY_LIMIT))


def _log_login_attempt(email, account_type, status, reason=''):
    """Log login attempt to audit log."""
    email = normalize_email(email)
    ip = request.remote_addr or 'unknown'
    ua = request.user_agent.string if request.user_agent else ''
    with db_cursor() as cur:
        cur.execute(
            "INSERT INTO login_audit_log (email, account_type, ip_address, user_agent, status, reason) VALUES (%s, %s, %s, %s, %s, %s)",
            (email, account_type, ip, ua[:500], status, reason)
        )


def _session_fingerprint():
    """Create a stable hash of User-Agent to detect session hijacking.

    IP address is excluded by default to support mobile/VPN users who may
    switch networks. Set STRICT_SESSION_FINGERPRINT=1 in env to enable
    IP-based binding for stricter security.
    """
    ua = request.headers.get('User-Agent', '') if hasattr(request, 'headers') else ''
    if app.config.get('STRICT_SESSION_FINGERPRINT', False):
        data = f"{request.remote_addr or 'unknown'}|{ua}"
    else:
        data = f"ua:{ua}"
    return hashlib.sha256(data.encode('utf-8')).hexdigest()


def log_activity(actor_type, actor_id, action, target_type=None, target_id=None, details=''):
    """Log activity for admin audit trail."""
    ip = request.remote_addr or 'unknown'
    with db_cursor() as cur:
        cur.execute(
            "INSERT INTO activity_log (actor_type, actor_id, action, target_type, target_id, details, ip_address) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (actor_type, actor_id, action, target_type, target_id, details, ip)
        )


# Activity logging helper above


def _create_table_safe(cursor, table_name, ddl):
    """Executes a CREATE TABLE DDL in an isolated try/except block, logging any failure."""
    try:
        cursor.execute(ddl)
    except Exception as e:
        logger.error(f"Database initialization error on table '{table_name}': {e}")


# --- INITIALIZE DATABASE ---
def init_db():
    conn = mysql.connector.connect(user=DB_USER, password=DB_PASSWORD, host=DB_HOST)
    cursor = conn.cursor()
    cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{DB_NAME}`")
    cursor.execute(f"USE `{DB_NAME}`")
    cursor.close()
    conn.close()
    conn = mysql.connector.connect(**db_config)
    cursor = conn.cursor()

    # --- RATE LIMIT TABLE (DB-backed, works across workers) ---
    _create_table_safe(cursor, 'rate_limits', """
        CREATE TABLE IF NOT EXISTS rate_limits (
            id INT AUTO_INCREMENT PRIMARY KEY,
            rate_key VARCHAR(255) NOT NULL,
            action VARCHAR(50) NOT NULL,
            count INT DEFAULT 1,
            window_start TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY unique_rate_limit (rate_key, action)
        )
    """)

    # --- OTP STORE (with expiry) ---
    _create_table_safe(cursor, 'otp_store', """
        CREATE TABLE IF NOT EXISTS otp_store (
            id INT AUTO_INCREMENT PRIMARY KEY,
            email VARCHAR(100),
            otp VARCHAR(6),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP,
            INDEX idx_otp_email (email)
        )
    """)
    # Add expires_at column for existing databases
    try:
        cursor.execute("ALTER TABLE otp_store ADD COLUMN expires_at TIMESTAMP NULL")
    except Exception:
        pass

    # --- EMPLOYEE TABLE ---
    _create_table_safe(cursor, 'employee', """
        CREATE TABLE IF NOT EXISTS employee (
            id INT AUTO_INCREMENT PRIMARY KEY,
            company_name VARCHAR(100),
            mobile VARCHAR(20),
            email VARCHAR(100) UNIQUE,
            password VARCHAR(255)
        )
    """)

    # --- USER TABLE ---
    _create_table_safe(cursor, 'user', """
        CREATE TABLE IF NOT EXISTS user (
            id INT AUTO_INCREMENT PRIMARY KEY,
            name VARCHAR(100),
            email VARCHAR(100) UNIQUE,
            password VARCHAR(255),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
             mobile VARCHAR(20),
              is_verified BOOLEAN DEFAULT FALSE,
              is_admin BOOLEAN DEFAULT FALSE,
              profile_visibility VARCHAR(20) DEFAULT 'public',
              consent_to_search BOOLEAN DEFAULT 0,
              headline VARCHAR(255) DEFAULT '',
            skills TEXT,
            experience INT DEFAULT 0,
            location VARCHAR(100) DEFAULT ''
         )
      """)

    _user_columns = [
        'profile_visibility VARCHAR(20) DEFAULT \'public\'',
        'consent_to_search BOOLEAN DEFAULT 0',
        'headline VARCHAR(255) DEFAULT \'\'',
        'skills TEXT',
        'experience INT DEFAULT 0',
        'location VARCHAR(100) DEFAULT \'\'',
        'is_banned BOOLEAN DEFAULT FALSE',
        'is_deleted BOOLEAN DEFAULT FALSE',
    ]
    for col_def in _user_columns:
        col_name = col_def.split()[0]
        try:
            cursor.execute(f"ALTER TABLE user ADD COLUMN {col_name} {col_def.split(' ', 1)[1]}")
        except Exception:
            pass

    # --- JOBS TABLE ---
    _create_table_safe(cursor, 'jobs', """
        CREATE TABLE IF NOT EXISTS jobs (
            id INT AUTO_INCREMENT PRIMARY KEY,
            employer_id INT NOT NULL,
            title VARCHAR(255) NOT NULL,
            description TEXT,
            location VARCHAR(100),
            salary VARCHAR(100),
            experience VARCHAR(100),
            skills TEXT,
            category VARCHAR(100) DEFAULT NULL,
            company_name VARCHAR(100),
            job_type VARCHAR(50) DEFAULT 'Full-time',
            work_mode VARCHAR(50) DEFAULT 'Onsite',
            salary_min INT DEFAULT 0,
            salary_max INT DEFAULT 0,
            openings INT DEFAULT 1,
            application_deadline DATE,
            is_active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (employer_id) REFERENCES employee(id)
        )
    """)
    # Add category column for existing databases (safe no-op if present)
    try:
        cursor.execute("ALTER TABLE jobs ADD COLUMN category VARCHAR(100) DEFAULT NULL")
    except Exception:
        pass
    # Add new columns for existing databases
    _job_columns = [
        'job_type VARCHAR(50) DEFAULT \'Full-time\'',
        'work_mode VARCHAR(50) DEFAULT \'Onsite\'',
        'salary_min INT DEFAULT 0',
        'salary_max INT DEFAULT 0',
        'openings INT DEFAULT 1',
        'application_deadline DATE',
        'is_active BOOLEAN DEFAULT TRUE',
    ]
    for col_def in _job_columns:
        col_name = col_def.split()[0]
        try:
            cursor.execute(f"ALTER TABLE jobs ADD COLUMN {col_name} {col_def.split(' ', 1)[1]}")
        except Exception:
            pass
    # Add status, is_demo, updated_at, closed_reason, education, industry, department to jobs table
    _job_ext_columns = [
        'status VARCHAR(50) DEFAULT \'Published\'',
        'is_demo BOOLEAN DEFAULT 0',
        'is_featured BOOLEAN DEFAULT FALSE',
        'is_deleted BOOLEAN DEFAULT FALSE',
        'closed_reason VARCHAR(100) DEFAULT NULL',
        'education VARCHAR(100) DEFAULT NULL',
        'industry VARCHAR(100) DEFAULT NULL',
        'department VARCHAR(100) DEFAULT NULL',
    ]
    for col_def in _job_ext_columns:
        col_name = col_def.split()[0]
        try:
            cursor.execute(f"ALTER TABLE jobs ADD COLUMN {col_name} {col_def.split(' ', 1)[1]}")
        except Exception:
            pass
    try:
        cursor.execute("ALTER TABLE jobs ADD COLUMN application_questions TEXT DEFAULT NULL")
    except Exception:
        pass

    # Add complete company profile and verification columns to employee table
    _emp_ext_columns = [
        'is_verified BOOLEAN DEFAULT FALSE',
        'verification_status VARCHAR(50) DEFAULT \'unverified\'',
        'company_website VARCHAR(255) DEFAULT \'\'',
        'industry VARCHAR(100) DEFAULT \'IT & Software\'',
        'location VARCHAR(100) DEFAULT \'\'',
        'company_size VARCHAR(50) DEFAULT \'1-50\'',
        'website VARCHAR(255) DEFAULT \'\'',
        'description TEXT',
        'founded_year VARCHAR(10) DEFAULT \'\'',
        'linkedin_url VARCHAR(255) DEFAULT \'\'',
        'twitter_url VARCHAR(255) DEFAULT \'\'',
        'logo_path VARCHAR(255) DEFAULT \'\'',
        'verified_at DATETIME NULL',
        'verification_notes TEXT',
        'verification_doc_path VARCHAR(255) DEFAULT \'\'',
        'verification_submitted_at DATETIME NULL',
        'created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP',
    ]
    for col_def in _emp_ext_columns:
        col_name = col_def.split()[0]
        try:
            cursor.execute(f"ALTER TABLE employee ADD COLUMN {col_name} {col_def.split(' ', 1)[1]}")
        except Exception:
            pass


    # --- APPLICATIONS TABLE (with FK + unique constraint) ---
    _create_table_safe(cursor, 'applications', """
        CREATE TABLE IF NOT EXISTS applications (
            id INT AUTO_INCREMENT PRIMARY KEY,
            job_id INT,
            user_id INT,
            user_name VARCHAR(100),
            user_email VARCHAR(100),
            user_mobile VARCHAR(20),
            qualification VARCHAR(100),
            college_name VARCHAR(255),
            year_of_passing VARCHAR(10),
            experience_level VARCHAR(50),
            years_experience VARCHAR(20),
            previous_company VARCHAR(100),
            skills TEXT,
            resume_path VARCHAR(255),
            cover_letter TEXT,
            current_location VARCHAR(100),
            preferred_location VARCHAR(100),
            expected_salary VARCHAR(100),
            status VARCHAR(50) DEFAULT 'Applied',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY unique_application (job_id, user_id),
            FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE,
            FOREIGN KEY (user_id) REFERENCES user(id) ON DELETE CASCADE
        )
    """)
    # Add unique constraint for existing databases
    try:
        cursor.execute("ALTER TABLE applications ADD CONSTRAINT unique_application UNIQUE (job_id, user_id)")
    except Exception:
        pass
    _app_ext_cols = [
        'answers TEXT DEFAULT NULL',
        'additional_document_path VARCHAR(255) DEFAULT NULL',
        'notes TEXT DEFAULT NULL',
        'match_score INT DEFAULT NULL',
        'tags TEXT DEFAULT NULL'
    ]
    for col_def in _app_ext_cols:
        col_name = col_def.split()[0]
        try:
            cursor.execute(f"ALTER TABLE applications ADD COLUMN {col_name} {col_def.split(' ', 1)[1]}")
        except Exception:
            pass
    # Add FK constraints for existing databases
    for constraint_name, col, ref_table, ref_col in [
        ('fk_applications_jobs', 'job_id', 'jobs', 'id'),
        ('fk_applications_user', 'user_id', 'user', 'id'),
    ]:
        try:
            cursor.execute(
                f"ALTER TABLE applications ADD CONSTRAINT {constraint_name} "
                f"FOREIGN KEY ({col}) REFERENCES {ref_table}({ref_col}) ON DELETE CASCADE"
            )
        except Exception:
            pass

    # --- APPLICATION STAGE HISTORY TABLE ---
    _create_table_safe(cursor, 'application_stage_history', """
        CREATE TABLE IF NOT EXISTS application_stage_history (
            id INT AUTO_INCREMENT PRIMARY KEY,
            application_id INT NOT NULL,
            from_stage VARCHAR(50),
            to_stage VARCHAR(50) NOT NULL,
            changed_by_employer_id INT NOT NULL,
            notes TEXT DEFAULT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_ash_app (application_id),
            INDEX idx_ash_emp (changed_by_employer_id),
            FOREIGN KEY (application_id) REFERENCES applications(id) ON DELETE CASCADE
        )
    """)

    # --- APPLICATION RECRUITER NOTES TABLE ---
    _create_table_safe(cursor, 'application_notes', """
        CREATE TABLE IF NOT EXISTS application_notes (
            id INT AUTO_INCREMENT PRIMARY KEY,
            application_id INT NOT NULL,
            employer_id INT NOT NULL,
            note TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_an_app (application_id),
            INDEX idx_an_emp (employer_id),
            FOREIGN KEY (application_id) REFERENCES applications(id) ON DELETE CASCADE
        )
    """)

    # --- SAVED JOBS TABLE (with FK) ---
    _create_table_safe(cursor, 'saved_jobs', """
        CREATE TABLE IF NOT EXISTS saved_jobs (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT NOT NULL,
            job_id INT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY unique_save (user_id, job_id),
            FOREIGN KEY (user_id) REFERENCES user(id) ON DELETE CASCADE,
            FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
        )
    """)
    # Add FK constraints for existing databases
    for constraint_name, col, ref_table, ref_col in [
        ('fk_saved_jobs_user', 'user_id', 'user', 'id'),
        ('fk_saved_jobs_jobs', 'job_id', 'jobs', 'id'),
    ]:
        try:
            cursor.execute(
                f"ALTER TABLE saved_jobs ADD CONSTRAINT {constraint_name} "
                f"FOREIGN KEY ({col}) REFERENCES {ref_table}({ref_col}) ON DELETE CASCADE"
            )
        except Exception:
            pass

    # --- JOB CATEGORY TABLE ---
    _create_table_safe(cursor, 'job_categories', """
        CREATE TABLE IF NOT EXISTS job_categories (
            id INT AUTO_INCREMENT PRIMARY KEY,
            name VARCHAR(100) NOT NULL UNIQUE
        )
    """)

    # Insert default categories
    try:
        cursor.execute("INSERT IGNORE INTO job_categories (name) VALUES ('IT & Software'), ('Banking & Finance'), ('Healthcare'), ('Engineering'), ('Manufacturing'), ('Education'), ('Design Engineer'), ('Retail'), ('Marketing'), ('Other')")
    except Exception:
        pass

    # --- COMPANY FOLLOWS TABLE ---
    _create_table_safe(cursor, 'company_follows', """
        CREATE TABLE IF NOT EXISTS company_follows (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT NOT NULL,
            company_id INT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY unique_follow (user_id, company_id),
            FOREIGN KEY (user_id) REFERENCES user(id) ON DELETE CASCADE,
            FOREIGN KEY (company_id) REFERENCES employee(id) ON DELETE CASCADE
        )
    """)
    for constraint_name, col, ref_table, ref_col in [
        ('fk_company_follows_user', 'user_id', 'user', 'id'),
        ('fk_company_follows_employee', 'company_id', 'employee', 'id'),
    ]:
        try:
            cursor.execute(
                f"ALTER TABLE company_follows ADD CONSTRAINT {constraint_name} "
                f"FOREIGN KEY ({col}) REFERENCES {ref_table}({ref_col}) ON DELETE CASCADE"
            )
        except Exception:
            pass

    # --- SAVED CANDIDATES TABLE ---
    _create_table_safe(cursor, 'saved_candidates', """
        CREATE TABLE IF NOT EXISTS saved_candidates (
            id INT AUTO_INCREMENT PRIMARY KEY,
            recruiter_id INT NOT NULL,
            candidate_id INT NOT NULL,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY unique_saved_candidate (recruiter_id, candidate_id),
            FOREIGN KEY (recruiter_id) REFERENCES employee(id) ON DELETE CASCADE,
            FOREIGN KEY (candidate_id) REFERENCES user(id) ON DELETE CASCADE
        )
    """)
    for constraint_name, col, ref_table, ref_col in [
        ('fk_saved_candidates_recruiter', 'recruiter_id', 'employee', 'id'),
        ('fk_saved_candidates_candidate', 'candidate_id', 'user', 'id'),
    ]:
        try:
            cursor.execute(
                f"ALTER TABLE saved_candidates ADD CONSTRAINT {constraint_name} "
                f"FOREIGN KEY ({col}) REFERENCES {ref_table}({ref_col}) ON DELETE CASCADE"
            )
        except Exception:
            pass

    # --- INTERVIEWS TABLE ---
    _create_table_safe(cursor, 'interviews', """
        CREATE TABLE IF NOT EXISTS interviews (
            id INT AUTO_INCREMENT PRIMARY KEY,
            job_id INT NOT NULL,
            employer_id INT NOT NULL,
            candidate_id INT NOT NULL,
            scheduled_date DATE NOT NULL,
            scheduled_time TIME NOT NULL,
            status VARCHAR(50) DEFAULT 'Scheduled',
            interviewer_notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            cancelled_at TIMESTAMP NULL,
            FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE,
            FOREIGN KEY (employer_id) REFERENCES employee(id) ON DELETE CASCADE,
            FOREIGN KEY (candidate_id) REFERENCES user(id) ON DELETE CASCADE,
            INDEX idx_interviews_employer (employer_id),
            INDEX idx_interviews_candidate (candidate_id),
            INDEX idx_interviews_status (status)
        )
    """)
    for constraint_name, col, ref_table, ref_col in [
        ('fk_interviews_job', 'job_id', 'jobs', 'id'),
        ('fk_interviews_employer', 'employer_id', 'employee', 'id'),
        ('fk_interviews_candidate', 'candidate_id', 'user', 'id'),
    ]:
        try:
            cursor.execute(
                f"ALTER TABLE interviews ADD CONSTRAINT {constraint_name} "
                f"FOREIGN KEY ({col}) REFERENCES {ref_table}({ref_col}) ON DELETE CASCADE"
            )
        except Exception:
            pass
    for col_def in [
        'cancelled_at TIMESTAMP NULL',
        'application_id INT NULL',
        'title VARCHAR(255) DEFAULT \'Technical Interview\'',
        'duration_minutes INT DEFAULT 30',
        'meeting_link VARCHAR(500) NULL',
        'interview_type VARCHAR(50) DEFAULT \'Video Interview\'',
        'candidate_feedback TEXT NULL',
        'updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP'
    ]:
        col_name = col_def.split()[0]
        try:
            cursor.execute(f"ALTER TABLE interviews ADD COLUMN {col_name} {col_def.split(' ', 1)[1]}")
        except Exception:
            pass

    # --- CONVERSATIONS TABLE ---
    _create_table_safe(cursor, 'conversations', """
        CREATE TABLE IF NOT EXISTS conversations (
            id INT AUTO_INCREMENT PRIMARY KEY,
            candidate_id INT NOT NULL,
            employer_id INT NOT NULL,
            job_id INT NULL,
            last_message_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_conv_candidate (candidate_id),
            INDEX idx_conv_employer (employer_id),
            INDEX idx_conv_last_msg (last_message_at)
        )
    """)
    for col_name, col_def in [
        ('job_id', 'job_id INT NULL'),
        ('last_message_at', 'last_message_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP'),
        ('updated_at', 'updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP'),
    ]:
        try:
            cursor.execute(f"ALTER TABLE conversations ADD COLUMN {col_name} {col_def.split(' ', 1)[1]}")
        except Exception:
            pass

    # --- MESSAGES TABLE ---
    _create_table_safe(cursor, 'messages', """
        CREATE TABLE IF NOT EXISTS messages (
            id INT AUTO_INCREMENT PRIMARY KEY,
            conversation_id INT NULL,
            sender_role VARCHAR(20) DEFAULT 'candidate',
            sender_id INT NOT NULL,
            receiver_id INT NOT NULL,
            content TEXT NOT NULL,
            sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_read BOOLEAN DEFAULT FALSE,
            read_at TIMESTAMP NULL,
            INDEX idx_messages_conv (conversation_id),
            INDEX idx_messages_sender (sender_id),
            INDEX idx_messages_receiver (receiver_id)
        )
    """)
    for col_name, col_def in [
        ('conversation_id', 'conversation_id INT NULL'),
        ('sender_role', 'sender_role VARCHAR(20) DEFAULT \'candidate\''),
        ('read_at', 'read_at TIMESTAMP NULL'),
    ]:
        try:
            cursor.execute(f"ALTER TABLE messages ADD COLUMN {col_name} {col_def.split(' ', 1)[1]}")
        except Exception:
            pass

    # Drop restrictive directional FKs to support bidirectional candidate <-> recruiter messaging
    for fk in ['fk_messages_sender', 'fk_messages_receiver', 'messages_ibfk_1', 'messages_ibfk_2']:
        try:
            cursor.execute(f"ALTER TABLE messages DROP FOREIGN KEY {fk}")
        except Exception:
            pass

    # --- ASSESSMENTS TABLE ---
    _create_table_safe(cursor, 'assessments', """
        CREATE TABLE IF NOT EXISTS assessments (
            id INT AUTO_INCREMENT PRIMARY KEY,
            title VARCHAR(255) NOT NULL,
            category VARCHAR(100) DEFAULT 'General',
            domain VARCHAR(50) DEFAULT 'technical',
            difficulty VARCHAR(50) DEFAULT 'Intermediate',
            description TEXT,
            time_limit_minutes INT DEFAULT 15,
            passing_score INT DEFAULT 70,
            questions_count INT DEFAULT 0,
            icon VARCHAR(50) DEFAULT 'fa-code',
            badge_icon VARCHAR(50) DEFAULT 'fa-award',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    for col_def in [
        'category VARCHAR(100) DEFAULT \'General\'',
        'domain VARCHAR(100) DEFAULT \'Technical\'',
        'difficulty VARCHAR(50) DEFAULT \'Intermediate\'',
        'description TEXT',
        'time_limit_minutes INT DEFAULT 15',
        'passing_score INT DEFAULT 70',
        'icon VARCHAR(50) DEFAULT \'fa-code\'',
        'badge_icon VARCHAR(50) DEFAULT \'fa-award\'',
        'rating DECIMAL(3,2) DEFAULT 4.85',
        'is_popular TINYINT(1) DEFAULT 0',
        'is_new TINYINT(1) DEFAULT 0',
    ]:
        col_name = col_def.split()[0]
        try:
            cursor.execute(f"ALTER TABLE assessments ADD COLUMN {col_name} {col_def.split(' ', 1)[1]}")
        except Exception:
            pass

    # --- ASSESSMENT QUESTIONS TABLE ---
    _create_table_safe(cursor, 'assessment_questions', """
        CREATE TABLE IF NOT EXISTS assessment_questions (
            id INT AUTO_INCREMENT PRIMARY KEY,
            assessment_id INT NOT NULL,
            question_text TEXT NOT NULL,
            options JSON NOT NULL,
            correct_option INT NOT NULL,
            explanation TEXT,
            question_order INT DEFAULT 1,
            INDEX idx_q_assessment (assessment_id),
            FOREIGN KEY (assessment_id) REFERENCES assessments(id) ON DELETE CASCADE
        )
    """)

    # --- ASSESSMENT ATTEMPTS TABLE ---
    _create_table_safe(cursor, 'assessment_attempts', """
        CREATE TABLE IF NOT EXISTS assessment_attempts (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT NOT NULL,
            assessment_id INT NOT NULL,
            started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP NULL,
            completed_at TIMESTAMP NULL,
            score INT DEFAULT 0,
            correct_count INT DEFAULT 0,
            total_questions INT DEFAULT 10,
            passed BOOLEAN DEFAULT FALSE,
            user_answers JSON,
            status VARCHAR(50) DEFAULT 'in_progress',
            INDEX idx_attempts_user (user_id),
            INDEX idx_attempts_assessment (assessment_id),
            FOREIGN KEY (user_id) REFERENCES user(id) ON DELETE CASCADE,
            FOREIGN KEY (assessment_id) REFERENCES assessments(id) ON DELETE CASCADE
        )
    """)

    # --- SKILL BADGES TABLE ---
    _create_table_safe(cursor, 'skill_badges', """
        CREATE TABLE IF NOT EXISTS skill_badges (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT NOT NULL,
            assessment_id INT NOT NULL,
            attempt_id INT NOT NULL,
            skill_name VARCHAR(100) NOT NULL,
            score INT NOT NULL,
            badge_level VARCHAR(50) DEFAULT 'Verified Professional',
            earned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY unique_user_badge (user_id, skill_name),
            INDEX idx_badges_user (user_id),
            FOREIGN KEY (user_id) REFERENCES user(id) ON DELETE CASCADE,
            FOREIGN KEY (assessment_id) REFERENCES assessments(id) ON DELETE CASCADE,
            FOREIGN KEY (attempt_id) REFERENCES assessment_attempts(id) ON DELETE CASCADE
        )
    """)

    # --- ASSESSMENT RESPONSES TABLE (legacy compatibility) ---
    _create_table_safe(cursor, 'assessment_responses', """
        CREATE TABLE IF NOT EXISTS assessment_responses (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT NOT NULL,
            test_id INT NOT NULL,
            answers TEXT,
            score INT DEFAULT 0,
            total_questions INT DEFAULT 0,
            submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES user(id) ON DELETE CASCADE,
            FOREIGN KEY (test_id) REFERENCES assessments(id) ON DELETE CASCADE,
            INDEX idx_responses_user (user_id),
            INDEX idx_responses_test (test_id)
        )
    """)
    for constraint_name, col, ref_table, ref_col in [
        ('fk_assessments_responses_user', 'user_id', 'user', 'id'),
        ('fk_assessments_responses_test', 'test_id', 'assessments', 'id'),
    ]:
        try:
            cursor.execute(
                f"ALTER TABLE assessment_responses ADD CONSTRAINT {constraint_name} "
                f"FOREIGN KEY ({col}) REFERENCES {ref_table}({ref_col}) ON DELETE CASCADE"
            )
        except Exception:
            pass

    # Seed assessments and question banks
    try:
        seed_assessments_db(cursor)
    except Exception as seed_err:
        logger.error(f"Error seeding assessments: {seed_err}")

    # Seed salary benchmark data
    try:
        seed_salary_benchmarks(cursor)
    except Exception as sal_err:
        logger.error(f"Error seeding salary benchmarks: {sal_err}")

    # --- COMPANY VERIFICATION STATUS COLUMN ---
    for col_def in [
        'verification_status VARCHAR(20) DEFAULT \'pending\'',
        'verified_at TIMESTAMP NULL',
    ]:
        col_name = col_def.split()[0]
        try:
            cursor.execute(f"ALTER TABLE employee ADD COLUMN {col_name} {col_def.split(' ', 1)[1]}")
        except Exception:
            pass


    # --- NOTIFICATIONS TABLE ---
    _create_table_safe(cursor, 'notifications', """
        CREATE TABLE IF NOT EXISTS notifications (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT DEFAULT NULL,
            employer_id INT DEFAULT NULL,
            notification_type VARCHAR(50) DEFAULT 'general',
            title VARCHAR(255) DEFAULT NULL,
            message TEXT,
            action_url VARCHAR(500) DEFAULT NULL,
            is_read BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_notif_user (user_id),
            INDEX idx_notif_emp (employer_id)
        )
    """)
    _notif_ext_cols = [
        'employer_id INT DEFAULT NULL',
        'notification_type VARCHAR(50) DEFAULT "general"',
        'title VARCHAR(255) DEFAULT NULL',
        'action_url VARCHAR(500) DEFAULT NULL'
    ]
    for col_def in _notif_ext_cols:
        col_name = col_def.split()[0]
        try:
            cursor.execute(f"ALTER TABLE notifications ADD COLUMN {col_name} {col_def.split(' ', 1)[1]}")
        except Exception:
            pass
    for idx_sql in [
        "CREATE INDEX idx_notif_emp ON notifications(employer_id)",
        "CREATE INDEX idx_notif_user_read ON notifications(user_id, is_read)",
        "CREATE INDEX idx_notif_emp_read ON notifications(employer_id, is_read)",
        "CREATE INDEX idx_notif_type ON notifications(notification_type)",
        "CREATE INDEX idx_notif_created ON notifications(created_at)"
    ]:
        try:
            cursor.execute(idx_sql)
        except Exception:
            pass

    # --- INDEXES (added separately so they're idempotent on existing DBs) ---
    _indexes = [
        ('jobs_title_idx', 'jobs', 'title'),
        ('jobs_location_idx', 'jobs', 'location'),
        ('jobs_category_idx', 'jobs', 'category'),
        ('jobs_job_type_idx', 'jobs', 'job_type'),
        ('jobs_work_mode_idx', 'jobs', 'work_mode'),
        ('jobs_experience_idx', 'jobs', 'experience'),
        ('jobs_created_at_idx', 'jobs', 'created_at'),
        ('jobs_salary_min_idx', 'jobs', 'salary_min'),
        ('jobs_salary_max_idx', 'jobs', 'salary_max'),
        ('jobs_active_idx', 'jobs', 'is_active'),
        ('applications_job_id_idx', 'applications', 'job_id'),
        ('applications_user_id_idx', 'applications', 'user_id'),
        ('saved_jobs_user_id_idx', 'saved_jobs', 'user_id'),
        ('saved_jobs_job_id_idx', 'saved_jobs', 'job_id'),
    ]
    for idx_name, table, col in _indexes:
        try:
            cursor.execute(f"CREATE INDEX {idx_name} ON {table}({col})")
        except Exception:
            pass

    # --- LOGIN ATTEMPTS TABLE (account lockout) ---
    _create_table_safe(cursor, 'login_attempts', """
        CREATE TABLE IF NOT EXISTS login_attempts (
            id INT AUTO_INCREMENT PRIMARY KEY,
            email VARCHAR(100) NOT NULL,
            account_type VARCHAR(30) NOT NULL,
            ip_address VARCHAR(45),
            attempt_count INT DEFAULT 1,
            last_attempt TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_locked BOOLEAN DEFAULT FALSE,
            locked_until TIMESTAMP NULL,
            UNIQUE KEY unique_attempt (email, account_type)
        )
    """)
    try:
        cursor.execute("ALTER TABLE login_attempts MODIFY COLUMN account_type VARCHAR(30) NOT NULL")
    except Exception:
        pass
    try:
        cursor.execute("CREATE INDEX idx_login_attempts_email ON login_attempts(email)")
    except Exception:
        pass
    try:
        cursor.execute("CREATE INDEX idx_login_attempts_locked ON login_attempts(is_locked, locked_until)")
    except Exception:
        pass

    # --- PASSWORD HISTORY TABLE ---
    _create_table_safe(cursor, 'password_history', """
        CREATE TABLE IF NOT EXISTS password_history (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT,
            employer_id INT,
            password_hash VARCHAR(255) NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_user (user_id),
            INDEX idx_employer (employer_id)
        )
    """)

    # --- LOGIN AUDIT LOG TABLE ---
    _create_table_safe(cursor, 'login_audit_log', """
        CREATE TABLE IF NOT EXISTS login_audit_log (
            id INT AUTO_INCREMENT PRIMARY KEY,
            email VARCHAR(100),
            account_type ENUM('user', 'employer', 'admin') NOT NULL,
            ip_address VARCHAR(45),
            user_agent TEXT,
            status ENUM('success', 'failed', 'locked', 'rate_limited') NOT NULL,
            reason VARCHAR(255),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_email (email),
            INDEX idx_status (status),
            INDEX idx_created (created_at)
        )
    """)

    # --- ACTIVITY LOG TABLE ---
    _create_table_safe(cursor, 'activity_log', """
        CREATE TABLE IF NOT EXISTS activity_log (
            id INT AUTO_INCREMENT PRIMARY KEY,
            actor_type ENUM('user', 'employer', 'admin', 'system') NOT NULL,
            actor_id INT,
            action VARCHAR(100) NOT NULL,
            target_type VARCHAR(50),
            target_id INT,
            details TEXT,
            ip_address VARCHAR(45),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_actor (actor_type, actor_id),
            INDEX idx_action (action),
            INDEX idx_created (created_at)
        )
    """)

    # --- NOTIFICATION PREFERENCES TABLE ---
    _create_table_safe(cursor, 'notification_preferences', """
        CREATE TABLE IF NOT EXISTS notification_preferences (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT UNIQUE DEFAULT NULL,
            employer_id INT UNIQUE DEFAULT NULL,
            job_alerts BOOLEAN DEFAULT TRUE,
            application_updates BOOLEAN DEFAULT TRUE,
            shortlist_updates BOOLEAN DEFAULT TRUE,
            interview_reminders BOOLEAN DEFAULT TRUE,
            messages BOOLEAN DEFAULT TRUE,
            recommended_jobs BOOLEAN DEFAULT TRUE,
            assessment_results BOOLEAN DEFAULT TRUE,
            security_alerts BOOLEAN DEFAULT TRUE,
            email_job_alerts BOOLEAN DEFAULT TRUE,
            email_application_updates BOOLEAN DEFAULT TRUE,
            email_marketing BOOLEAN DEFAULT FALSE,
            email_notifications BOOLEAN DEFAULT TRUE,
            push_notifications BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_np_user (user_id),
            INDEX idx_np_emp (employer_id)
        )
    """)
    _np_ext_cols = [
        'employer_id INT UNIQUE DEFAULT NULL',
        'job_alerts BOOLEAN DEFAULT TRUE',
        'application_updates BOOLEAN DEFAULT TRUE',
        'shortlist_updates BOOLEAN DEFAULT TRUE',
        'interview_reminders BOOLEAN DEFAULT TRUE',
        'messages BOOLEAN DEFAULT TRUE',
        'recommended_jobs BOOLEAN DEFAULT TRUE',
        'assessment_results BOOLEAN DEFAULT TRUE',
        'security_alerts BOOLEAN DEFAULT TRUE',
        'email_notifications BOOLEAN DEFAULT TRUE'
    ]
    for col_def in _np_ext_cols:
        col_name = col_def.split()[0]
        try:
            cursor.execute(f"ALTER TABLE notification_preferences ADD COLUMN {col_name} {col_def.split(' ', 1)[1]}")
        except Exception:
            pass

    # Add session_version column to user table
    try:
        cursor.execute("ALTER TABLE user ADD COLUMN session_version INT DEFAULT 0")
    except Exception:
        pass

    # Add session_version column to employee table
    try:
        cursor.execute("ALTER TABLE employee ADD COLUMN session_version INT DEFAULT 0")
    except Exception:
        pass

    # Add is_admin column to user table
    try:
        cursor.execute("ALTER TABLE user ADD COLUMN is_admin BOOLEAN DEFAULT FALSE")
    except Exception:
        pass

    # --- CANDIDATE PROFILE TABLE ---
    _create_table_safe(cursor, 'candidate_profile', """
        CREATE TABLE IF NOT EXISTS candidate_profile (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT UNIQUE,
            headline VARCHAR(255),
            summary TEXT,
            skills TEXT,
            experience JSON,
            education JSON,
            linkedin_url VARCHAR(255),
            github_url VARCHAR(255),
            portfolio_url VARCHAR(255),
            profile_photo VARCHAR(255),
            general_resume_path VARCHAR(255),
            is_public BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES user(id) ON DELETE CASCADE
        )
    """)

    try:
        cursor.execute("ALTER TABLE candidate_profile ADD COLUMN general_resume_path VARCHAR(255)")
    except Exception:
        pass

    # --- CANDIDATE PROFILE EXTENSION TABLES ---
    _create_table_safe(cursor, 'candidate_personal_details', """
        CREATE TABLE IF NOT EXISTS candidate_personal_details (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT UNIQUE,
            date_of_birth DATE,
            gender VARCHAR(20),
            marital_status VARCHAR(20),
            nationality VARCHAR(100),
            current_location VARCHAR(100),
            hometown VARCHAR(100),
            permanent_address TEXT,
            pincode VARCHAR(10),
            physically_challenged BOOLEAN DEFAULT FALSE,
            work_permit_countries VARCHAR(255),
            FOREIGN KEY (user_id) REFERENCES user(id) ON DELETE CASCADE
        )
    """)
    try:
        cursor.execute("ALTER TABLE candidate_personal_details ADD COLUMN nationality VARCHAR(100)")
    except Exception:
        pass
    try:
        cursor.execute("ALTER TABLE candidate_personal_details ADD COLUMN physically_challenged BOOLEAN DEFAULT FALSE")
    except Exception:
        pass
    try:
        cursor.execute("ALTER TABLE candidate_personal_details ADD COLUMN work_permit_countries VARCHAR(255)")
    except Exception:
        pass

    _create_table_safe(cursor, 'candidate_preferences', """
        CREATE TABLE IF NOT EXISTS candidate_preferences (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT UNIQUE,
            current_industry VARCHAR(100),
            current_department VARCHAR(100),
            current_job_role VARCHAR(100),
            desired_job_type VARCHAR(50),
            desired_employment_type VARCHAR(50),
            preferred_shift VARCHAR(50),
            current_ctc VARCHAR(50),
            expected_ctc VARCHAR(50),
            notice_period VARCHAR(50),
            open_to_relocate BOOLEAN DEFAULT FALSE,
            preferred_location VARCHAR(255),
            workplace_type VARCHAR(50) DEFAULT 'Flexible / Any',
            FOREIGN KEY (user_id) REFERENCES user(id) ON DELETE CASCADE
        )
    """)
    try:
        cursor.execute("ALTER TABLE candidate_preferences CHANGE COLUMN `current_role` current_job_role VARCHAR(100)")
    except Exception:
        pass
    try:
        cursor.execute("ALTER TABLE candidate_preferences ADD COLUMN current_job_role VARCHAR(100)")
    except Exception:
        pass
    try:
        cursor.execute("ALTER TABLE candidate_preferences ADD COLUMN preferred_location VARCHAR(255)")
    except Exception:
        pass
    try:
        cursor.execute("ALTER TABLE candidate_preferences ADD COLUMN workplace_type VARCHAR(50) DEFAULT 'Flexible / Any'")
    except Exception:
        pass

    _create_table_safe(cursor, 'candidate_profile_summary', """
        CREATE TABLE IF NOT EXISTS candidate_profile_summary (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT UNIQUE,
            summary TEXT,
            FOREIGN KEY (user_id) REFERENCES user(id) ON DELETE CASCADE
        )
    """)

    _create_table_safe(cursor, 'key_skills', """
        CREATE TABLE IF NOT EXISTS key_skills (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT,
            skill_name VARCHAR(100),
            skill_type VARCHAR(50) DEFAULT 'Technical',
            FOREIGN KEY (user_id) REFERENCES user(id) ON DELETE CASCADE
        )
    """)
    try:
        cursor.execute("ALTER TABLE key_skills ADD COLUMN skill_type VARCHAR(50) DEFAULT 'Technical'")
    except Exception:
        pass

    _create_table_safe(cursor, 'employment', """
        CREATE TABLE IF NOT EXISTS employment (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT,
            company_name VARCHAR(255),
            job_title VARCHAR(255),
            employment_type VARCHAR(50),
            department VARCHAR(100),
            is_current BOOLEAN DEFAULT FALSE,
            start_date DATE,
            end_date DATE,
            job_profile TEXT,
            skills_used TEXT,
            gross_salary VARCHAR(50),
            notice_period VARCHAR(50),
            FOREIGN KEY (user_id) REFERENCES user(id) ON DELETE CASCADE
        )
    """)

    _create_table_safe(cursor, 'education', """
        CREATE TABLE IF NOT EXISTS education (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT,
            education_level VARCHAR(50),
            institute VARCHAR(255),
            course_degree VARCHAR(255),
            specialization VARCHAR(255),
            course_type VARCHAR(50),
            grading_system VARCHAR(50),
            grade_value VARCHAR(50),
            year_of_passing VARCHAR(10),
            FOREIGN KEY (user_id) REFERENCES user(id) ON DELETE CASCADE
        )
    """)

    _create_table_safe(cursor, 'it_skills', """
        CREATE TABLE IF NOT EXISTS it_skills (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT,
            skill_name VARCHAR(100),
            version VARCHAR(50),
            last_used_year INT,
            experience_years INT,
            experience_months INT,
            proficiency VARCHAR(50),
            FOREIGN KEY (user_id) REFERENCES user(id) ON DELETE CASCADE
        )
    """)

    _create_table_safe(cursor, 'internships', """
        CREATE TABLE IF NOT EXISTS internships (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT,
            organization_name VARCHAR(255),
            role_title VARCHAR(255),
            start_date DATE,
            end_date DATE,
            is_current BOOLEAN DEFAULT FALSE,
            stipend VARCHAR(50),
            project_details TEXT,
            skills_used TEXT,
            FOREIGN KEY (user_id) REFERENCES user(id) ON DELETE CASCADE
        )
    """)

    _create_table_safe(cursor, 'projects', """
        CREATE TABLE IF NOT EXISTS projects (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT,
            title VARCHAR(255),
            client_name VARCHAR(255),
            is_confidential BOOLEAN DEFAULT FALSE,
            status VARCHAR(50),
            start_date DATE,
            end_date DATE,
            role VARCHAR(100),
            team_size INT,
            project_details TEXT,
            technology_tags TEXT,
            project_url VARCHAR(255),
            FOREIGN KEY (user_id) REFERENCES user(id) ON DELETE CASCADE
        )
    """)
    try:
        cursor.execute("ALTER TABLE projects ADD COLUMN project_url VARCHAR(255)")
    except Exception:
        pass

    _create_table_safe(cursor, 'online_profiles', """
        CREATE TABLE IF NOT EXISTS online_profiles (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT,
            platform VARCHAR(50),
            profile_url VARCHAR(255),
            FOREIGN KEY (user_id) REFERENCES user(id) ON DELETE CASCADE
        )
    """)

    _create_table_safe(cursor, 'work_samples', """
        CREATE TABLE IF NOT EXISTS work_samples (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT,
            title VARCHAR(255),
            url VARCHAR(255),
            description TEXT,
            FOREIGN KEY (user_id) REFERENCES user(id) ON DELETE CASCADE
        )
    """)

    _create_table_safe(cursor, 'certifications', """
        CREATE TABLE IF NOT EXISTS certifications (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT,
            name VARCHAR(255),
            issuing_authority VARCHAR(255),
            certificate_id VARCHAR(100),
            issue_date DATE,
            expiry_date DATE,
            no_expiry BOOLEAN DEFAULT FALSE,
            credential_url VARCHAR(255),
            FOREIGN KEY (user_id) REFERENCES user(id) ON DELETE CASCADE
        )
    """)

    _create_table_safe(cursor, 'publications', """
        CREATE TABLE IF NOT EXISTS publications (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT,
            title VARCHAR(255),
            publisher_journal VARCHAR(255),
            url VARCHAR(255),
            pub_date DATE,
            description TEXT,
            FOREIGN KEY (user_id) REFERENCES user(id) ON DELETE CASCADE
        )
    """)

    _create_table_safe(cursor, 'presentations', """
        CREATE TABLE IF NOT EXISTS presentations (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT,
            title VARCHAR(255),
            url VARCHAR(255),
            present_date DATE,
            FOREIGN KEY (user_id) REFERENCES user(id) ON DELETE CASCADE
        )
    """)

    _create_table_safe(cursor, 'patents', """
        CREATE TABLE IF NOT EXISTS patents (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT,
            title VARCHAR(255),
            patent_office VARCHAR(255),
            status VARCHAR(50),
            patent_number VARCHAR(100),
            patent_date DATE,
            url VARCHAR(255),
            FOREIGN KEY (user_id) REFERENCES user(id) ON DELETE CASCADE
        )
    """)

    _create_table_safe(cursor, 'competitive_exams', """
        CREATE TABLE IF NOT EXISTS competitive_exams (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT,
            exam_name VARCHAR(255),
            score_percentile VARCHAR(50),
            `rank` VARCHAR(50),
            `year` INT,
            FOREIGN KEY (user_id) REFERENCES user(id) ON DELETE CASCADE
        )
    """)

    _create_table_safe(cursor, 'academic_achievements', """
        CREATE TABLE IF NOT EXISTS academic_achievements (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT,
            title VARCHAR(255),
            description TEXT,
            `year` INT,
            FOREIGN KEY (user_id) REFERENCES user(id) ON DELETE CASCADE
        )
    """)

    _create_table_safe(cursor, 'languages', """
        CREATE TABLE IF NOT EXISTS languages (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT,
            language VARCHAR(100),
            can_read BOOLEAN DEFAULT FALSE,
            can_write BOOLEAN DEFAULT FALSE,
            can_speak BOOLEAN DEFAULT FALSE,
            FOREIGN KEY (user_id) REFERENCES user(id) ON DELETE CASCADE
        )
    """)

    _create_table_safe(cursor, 'preferred_locations', """
        CREATE TABLE IF NOT EXISTS preferred_locations (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT,
            location VARCHAR(100),
            FOREIGN KEY (user_id) REFERENCES user(id) ON DELETE CASCADE
        )
    """)

    _create_table_safe(cursor, 'job_alerts', """
        CREATE TABLE IF NOT EXISTS job_alerts (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT,
            keywords VARCHAR(255),
            frequency VARCHAR(50) DEFAULT 'daily',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES user(id) ON DELETE CASCADE
        )
    """)

    # --- JOB ALERTS SENT TABLE (deduplication) ---
    _create_table_safe(cursor, 'job_alerts_sent', """
        CREATE TABLE IF NOT EXISTS job_alerts_sent (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT NOT NULL,
            alert_id INT,
            job_id INT NOT NULL,
            sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY unique_alert_job (user_id, alert_id, job_id),
            FOREIGN KEY (user_id) REFERENCES user(id) ON DELETE CASCADE
        )
    """)

    # --- RESUME ANALYSES TABLE ---
    _create_table_safe(cursor, 'resume_analyses', """
        CREATE TABLE IF NOT EXISTS resume_analyses (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT NULL,
            filename VARCHAR(255) NOT NULL,
            original_filename VARCHAR(255) NOT NULL,
            file_path VARCHAR(255) NOT NULL,
            file_size INT DEFAULT 0,
            ats_score INT DEFAULT 0,
            extracted_skills JSON,
            detected_keywords JSON,
            missing_keywords JSON,
            sections_detected JSON,
            score_breakdown JSON,
            suggestions JSON,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            INDEX (user_id),
            FOREIGN KEY (user_id) REFERENCES user(id) ON DELETE CASCADE
        )
    """)

    # --- CANDIDATE JOB MATCHES CACHE TABLE ---
    _create_table_safe(cursor, 'candidate_job_matches', """
        CREATE TABLE IF NOT EXISTS candidate_job_matches (
            job_id INT NOT NULL,
            candidate_id INT NOT NULL,
            skill_score DECIMAL(5,2) DEFAULT 0,
            semantic_score DECIMAL(5,2) DEFAULT 0,
            experience_score DECIMAL(5,2) DEFAULT 0,
            education_score DECIMAL(5,2) DEFAULT 0,
            location_score DECIMAL(5,2) DEFAULT 0,
            role_score DECIMAL(5,2) DEFAULT 0,
            salary_score DECIMAL(5,2) DEFAULT 0,
            work_mode_score DECIMAL(5,2) DEFAULT 0,
            final_score DECIMAL(5,2) DEFAULT 0,
            matched_skills TEXT,
            missing_skills TEXT,
            match_reason VARCHAR(255) DEFAULT NULL,
            computed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            PRIMARY KEY (job_id, candidate_id),
            FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE,
            FOREIGN KEY (candidate_id) REFERENCES user(id) ON DELETE CASCADE,
            INDEX idx_cjm_job_score (job_id, final_score),
            INDEX idx_cjm_candidate (candidate_id)
        )
    """)
    for cjm_col in [
        'match_reason VARCHAR(255) DEFAULT NULL',
        'role_score DECIMAL(5,2) DEFAULT 0',
        'salary_score DECIMAL(5,2) DEFAULT 0',
        'work_mode_score DECIMAL(5,2) DEFAULT 0'
    ]:
        try:
            cursor.execute(f"ALTER TABLE candidate_job_matches ADD COLUMN {cjm_col}")
        except Exception:
            pass
    try:
        cursor.execute("CREATE INDEX idx_cjm_cand_final ON candidate_job_matches (candidate_id, final_score)")
    except Exception:
        pass

    # --- CANDIDATE PROFILE VIEWS TRACKING TABLE ---
    _create_table_safe(cursor, 'profile_views', """
        CREATE TABLE IF NOT EXISTS profile_views (
            id INT AUTO_INCREMENT PRIMARY KEY,
            candidate_id INT NOT NULL,
            employer_id INT NOT NULL,
            company_name VARCHAR(255),
            viewed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (candidate_id) REFERENCES user(id) ON DELETE CASCADE,
            FOREIGN KEY (employer_id) REFERENCES employee(id) ON DELETE CASCADE,
            INDEX idx_pv_candidate (candidate_id),
            INDEX idx_pv_employer (employer_id),
            INDEX idx_pv_cand_viewed (candidate_id, viewed_at)
        )
    """)

    # --- COMPANY VERIFICATION HISTORY TABLE ---
    _create_table_safe(cursor, 'company_verification_history', """
        CREATE TABLE IF NOT EXISTS company_verification_history (
            id INT AUTO_INCREMENT PRIMARY KEY,
            company_id INT NOT NULL,
            admin_id INT NULL,
            previous_status VARCHAR(50),
            new_status VARCHAR(50) NOT NULL,
            admin_note TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_cvh_company (company_id),
            INDEX idx_cvh_created (created_at),
            FOREIGN KEY (company_id) REFERENCES employee(id) ON DELETE CASCADE
        )
    """)

    # --- REPORTS TABLE (candidate/user reports on companies or jobs) ---
    _create_table_safe(cursor, 'reports', """
        CREATE TABLE IF NOT EXISTS reports (
            id INT AUTO_INCREMENT PRIMARY KEY,
            reporter_user_id INT NULL,
            reporter_email VARCHAR(100),
            report_type ENUM('company', 'job') NOT NULL,
            target_id INT NOT NULL,
            target_name VARCHAR(255),
            category ENUM('Scam', 'Fake Company', 'Fake Job', 'Suspicious Recruitment', 'Wrong Information', 'External Payment Request', 'Spam', 'Other') NOT NULL,
            description TEXT,
            status ENUM('OPEN', 'UNDER_REVIEW', 'RESOLVED', 'DISMISSED') DEFAULT 'OPEN',
            admin_notes TEXT,
            resolved_by_admin_id INT NULL,
            resolved_at DATETIME NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            INDEX idx_rep_type_target (report_type, target_id),
            INDEX idx_rep_status (status),
            INDEX idx_rep_created (created_at)
        )
    """)

    # --- ADMIN AUDIT LOGS TABLE ---
    _create_table_safe(cursor, 'admin_audit_logs', """
        CREATE TABLE IF NOT EXISTS admin_audit_logs (
            id INT AUTO_INCREMENT PRIMARY KEY,
            admin_id INT,
            admin_email VARCHAR(100),
            action VARCHAR(100) NOT NULL,
            entity_type VARCHAR(50),
            entity_id INT,
            previous_status VARCHAR(50),
            new_status VARCHAR(50),
            reason TEXT,
            ip_address VARCHAR(45),
            user_agent TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_aal_admin (admin_id),
            INDEX idx_aal_action (action),
            INDEX idx_aal_entity (entity_type, entity_id),
            INDEX idx_aal_created (created_at)
        )
    """)

    for col_def in [
        'is_verified BOOLEAN DEFAULT FALSE',
        'verification_status VARCHAR(50) DEFAULT \'unverified\'',
        'risk_level VARCHAR(20) DEFAULT \'low\'',
        'verified_at DATETIME NULL',
        'verification_notes TEXT',
        'verification_submitted_at DATETIME NULL',
    ]:
        col_name = col_def.split()[0]
        try:
            cursor.execute(f"ALTER TABLE employee ADD COLUMN {col_name} {col_def.split(' ', 1)[1]}")
        except Exception:
            pass

    conn.commit()
    cursor.close()
    conn.close()


def init_admin_user():
    """Ensure the initial primary administrator account exists with is_admin=TRUE and hashed password."""
    admin_email = os.getenv('ADMIN_EMAIL', 'ccubetech00@gmail.com').strip().lower()
    admin_password = os.getenv('ADMIN_PASSWORD', 'ccubetech00')
    try:
        with db_cursor() as cur:
            cur.execute("SELECT id, password, is_admin FROM user WHERE email = %s", (admin_email,))
            row = cur.fetchone()
            if not row:
                cur.execute("""
                    INSERT INTO user (name, email, password, is_admin, is_verified, profile_visibility)
                    VALUES (%s, %s, %s, TRUE, TRUE, 'private')
                """, ('HireVoltz Admin', admin_email, generate_password_hash(admin_password)))
                logger.info(f"Auto-provisioned default admin account: {admin_email}")
            else:
                if not row.get('is_admin'):
                    cur.execute("UPDATE user SET is_admin = TRUE, is_verified = TRUE WHERE id = %s", (row['id'],))
                    logger.info(f"Elevated user {admin_email} to administrator role.")
    except Exception as e:
        logger.warning(f"Failed to auto-provision administrator user: {e}")


# --- DATABASE INITIALIZATION (best-effort at import; retry in __main__) ---
try:
    init_db()
    init_admin_user()
except Exception as e:
    logger.error(f"Database initialization error: {e}")


# --- ADMIN AUDIT TRAIL HELPER ---
def log_admin_audit(action, entity_type=None, entity_id=None, previous_status=None, new_status=None, reason='', admin_id=None):
    """
    Records an immutable admin action to admin_audit_logs and activity_log tables.
    """
    if admin_id is None:
        admin_id = session.get('user_id')
    admin_email = session.get('user_email') or ''
    if not admin_email and admin_id:
        try:
            with db_cursor() as cur:
                cur.execute("SELECT email FROM user WHERE id = %s", (admin_id,))
                row = cur.fetchone()
                if row:
                    admin_email = row['email']
        except Exception:
            pass

    ip = request.remote_addr or 'unknown'
    user_agent = request.headers.get('User-Agent', '')[:255]

    try:
        with db_cursor(dictionary=False) as cur:
            cur.execute("""
                INSERT INTO admin_audit_logs 
                (admin_id, admin_email, action, entity_type, entity_id, previous_status, new_status, reason, ip_address, user_agent)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (admin_id, admin_email, action, entity_type, entity_id, previous_status, new_status, reason, ip, user_agent))

            # Also record to general activity_log for unified tracking
            details = f"Admin action '{action}' on {entity_type or 'item'} #{entity_id or 0}. Note: {reason}"
            cur.execute("""
                INSERT INTO activity_log (actor_type, actor_id, action, target_type, target_id, details, ip_address)
                VALUES ('admin', %s, %s, %s, %s, %s, %s)
            """, (admin_id, action, entity_type, entity_id, details, ip))
    except Exception as e:
        logger.error(f"Failed to record admin audit log: {e}")


# --- COMPANY TRUST, SSRF-SAFE CHECKING & VERIFICATION LOGIC ---
VERIFICATION_DOCS_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads', 'verification_docs')
os.makedirs(VERIFICATION_DOCS_FOLDER, exist_ok=True)

PUBLIC_EMAIL_DOMAINS = {
    'gmail.com', 'yahoo.com', 'hotmail.com', 'outlook.com', 'icloud.com',
    'protonmail.com', 'zoho.com', 'aol.com', 'mail.com', 'yandex.com', 'rediffmail.com'
}


def is_private_or_restricted_ip(ip_str):
    """Check if an IP address is private, loopback, link-local, multicast, or reserved."""
    try:
        ip = ipaddress.ip_address(ip_str)
        return (
            ip.is_private or
            ip.is_loopback or
            ip.is_link_local or
            ip.is_multicast or
            ip.is_reserved or
            ip.is_unspecified
        )
    except Exception:
        return True


def safe_check_company_website(url_raw):
    """
    Safely audits a company website URL with strict SSRF protection.
    Blocks private IP addresses, localhost, cloud metadata endpoints, and non-standard ports.
    """
    if not url_raw or not str(url_raw).strip():
        return {
            'is_safe_url': False,
            'domain': '',
            'is_https': False,
            'is_reachable': False,
            'status_code': None,
            'error_message': 'No website URL provided',
            'final_url': ''
        }

    url = str(url_raw).strip()
    if not (url.startswith('http://') or url.startswith('https://')):
        url = 'https://' + url

    try:
        parsed = urllib.parse.urlparse(url)
    except Exception as e:
        return {
            'is_safe_url': False,
            'domain': '',
            'is_https': False,
            'is_reachable': False,
            'status_code': None,
            'error_message': f'Invalid URL structure: {e}',
            'final_url': url
        }

    scheme = parsed.scheme.lower()
    if scheme not in ('http', 'https'):
        return {
            'is_safe_url': False,
            'domain': parsed.netloc,
            'is_https': False,
            'is_reachable': False,
            'status_code': None,
            'error_message': f'Unsupported URL protocol: {scheme}',
            'final_url': url
        }

    hostname = (parsed.hostname or '').strip()
    if not hostname:
        return {
            'is_safe_url': False,
            'domain': '',
            'is_https': scheme == 'https',
            'is_reachable': False,
            'status_code': None,
            'error_message': 'Missing hostname in URL',
            'final_url': url
        }

    # Block localhost / internal hostnames
    blocked_hosts = {'localhost', '127.0.0.1', '::1', '0.0.0.0', 'metadata.google.internal', 'instance-data', '169.254.169.254'}
    if hostname.lower() in blocked_hosts or hostname.lower().endswith('.local') or hostname.lower().endswith('.internal'):
        return {
            'is_safe_url': False,
            'domain': hostname,
            'is_https': scheme == 'https',
            'is_reachable': False,
            'status_code': None,
            'error_message': 'Access to localhost and internal network hostnames is blocked for security (SSRF Protection)',
            'final_url': url
        }

    # Validate port
    port = parsed.port or (443 if scheme == 'https' else 80)
    if port not in (80, 443, 8080, 8443):
        return {
            'is_safe_url': False,
            'domain': hostname,
            'is_https': scheme == 'https',
            'is_reachable': False,
            'status_code': None,
            'error_message': f'Non-standard port {port} is restricted',
            'final_url': url
        }

    # Resolve IP address via DNS and verify not in private/reserved range
    try:
        resolved_ips = socket.getaddrinfo(hostname, port, socket.AF_UNSPEC, socket.SOCK_STREAM)
        for family, socktype, proto, canonname, sockaddr in resolved_ips:
            ip_str = sockaddr[0]
            if is_private_or_restricted_ip(ip_str):
                return {
                    'is_safe_url': False,
                    'domain': hostname,
                    'is_https': scheme == 'https',
                    'is_reachable': False,
                    'status_code': None,
                    'error_message': f'Resolved IP {ip_str} is in a private, loopback, or cloud-metadata network range (Blocked)',
                    'final_url': url
                }
    except socket.gaierror as e:
        return {
            'is_safe_url': True,
            'domain': hostname,
            'is_https': scheme == 'https',
            'is_reachable': False,
            'status_code': None,
            'error_message': f'DNS resolution failed for hostname {hostname}: {e}',
            'final_url': url
        }
    except Exception as e:
        return {
            'is_safe_url': False,
            'domain': hostname,
            'is_https': scheme == 'https',
            'is_reachable': False,
            'status_code': None,
            'error_message': f'DNS check error: {e}',
            'final_url': url
        }

    # Lightweight HTTP check with short timeout
    try:
        headers = {'User-Agent': 'HireVoltz-TrustAuditor/1.0 (+https://hirevoltz.com)'}
        resp = requests.head(url, headers=headers, timeout=2.5, allow_redirects=True, stream=True)
        if resp.status_code == 405:
            resp = requests.get(url, headers=headers, timeout=2.5, allow_redirects=True, stream=True)

        status_code = resp.status_code
        final_url = resp.url
        is_reachable = 200 <= status_code < 400 or status_code in (401, 403)
        return {
            'is_safe_url': True,
            'domain': hostname,
            'is_https': final_url.startswith('https://') or scheme == 'https',
            'is_reachable': is_reachable,
            'status_code': status_code,
            'error_message': None if is_reachable else f'Server returned HTTP status {status_code}',
            'final_url': final_url
        }
    except requests.exceptions.SSLError:
        return {
            'is_safe_url': True,
            'domain': hostname,
            'is_https': False,
            'is_reachable': False,
            'status_code': None,
            'error_message': 'SSL Certificate validation failed or expired',
            'final_url': url
        }
    except requests.exceptions.Timeout:
        return {
            'is_safe_url': True,
            'domain': hostname,
            'is_https': scheme == 'https',
            'is_reachable': False,
            'status_code': None,
            'error_message': 'Connection timed out (> 2.5s)',
            'final_url': url
        }
    except Exception as e:
        return {
            'is_safe_url': True,
            'domain': hostname,
            'is_https': scheme == 'https',
            'is_reachable': False,
            'status_code': None,
            'error_message': f'Reachability check error: {str(e)[:100]}',
            'final_url': url
        }


def compute_company_trust_and_risk(emp, jobs_count=0, reports_count=0, website_audit=None):
    """
    Computes trust signals, warning indicators, and automated risk score for a company.
    Note: Risk score is an automated internal screening signal, NOT definitive proof of fraud.
    """
    if not emp:
        return {
            'risk_level': 'UNKNOWN',
            'risk_class': 'medium',
            'risk_points': 50,
            'trust_indicators': [],
            'warnings': ['No company data available'],
            'completeness': 0,
            'email_domain': '',
            'website_domain': '',
            'reports_count': 0,
            'jobs_count': 0
        }

    trust_indicators = []
    warnings = []
    risk_points = 0  # higher = more risk

    # 1. Company Profile Completeness
    completeness = compute_company_completeness(emp)
    if completeness >= 80:
        trust_indicators.append("Comprehensive company profile (> 80% complete)")
    elif completeness >= 50:
        trust_indicators.append("Adequate company profile details")
    else:
        warnings.append("Sparse or incomplete company profile (< 50% complete)")
        risk_points += 20

    # 2. Email domain analysis
    emp_email = (emp.get('email') or '').strip().lower()
    email_domain = emp_email.split('@')[-1] if '@' in emp_email else ''

    website_raw = (emp.get('website') or emp.get('company_website') or '').strip()
    website_domain = ''
    if website_raw:
        try:
            parsed = urllib.parse.urlparse(website_raw if '://' in website_raw else f"http://{website_raw}")
            website_domain = (parsed.hostname or '').lower().replace('www.', '')
        except Exception:
            website_domain = website_raw.lower().replace('www.', '')

    if email_domain in PUBLIC_EMAIL_DOMAINS:
        warnings.append(f"Company registered with free/public email provider (@{email_domain})")
        risk_points += 25
    elif email_domain:
        trust_indicators.append(f"Corporate business email domain (@{email_domain})")
        if website_domain and (email_domain == website_domain or email_domain.endswith('.' + website_domain) or website_domain.endswith('.' + email_domain)):
            trust_indicators.append("Email domain matches company website domain")
        elif website_domain:
            warnings.append(f"Email domain (@{email_domain}) does not match website domain ({website_domain})")
            risk_points += 15

    # 3. Website audit analysis
    if not website_raw:
        warnings.append("No company website URL provided")
        risk_points += 20
    elif website_audit:
        if website_audit.get('is_https'):
            trust_indicators.append("Secure HTTPS encryption enabled on website")
        else:
            warnings.append("Website does not enforce HTTPS encryption")
            risk_points += 10

        if website_audit.get('is_reachable'):
            trust_indicators.append("Company website is online and reachable")
        else:
            warnings.append(f"Website unreachable ({website_audit.get('error_message') or 'Connection failed'})")
            risk_points += 25

    # 4. Job postings history
    if jobs_count > 0:
        trust_indicators.append(f"Active hiring history ({jobs_count} job opening{'s' if jobs_count != 1 else ''} posted)")
    else:
        warnings.append("No jobs posted yet by this company account")
        risk_points += 5

    # 5. Candidate Reports
    if reports_count > 0:
        warnings.append(f"Received {reports_count} candidate/user report{'s' if reports_count != 1 else ''}")
        risk_points += min(60, reports_count * 25)
    else:
        trust_indicators.append("Zero scam/fraud reports filed by candidates")

    # 6. Verification documents
    if emp.get('verification_doc_path'):
        trust_indicators.append("Submitted official business registration / incorporation document")

    # Risk Score Classification
    if risk_points <= 20:
        risk_level = "LOW RISK"
        risk_class = "low"
    elif risk_points <= 50:
        risk_level = "MEDIUM RISK"
        risk_class = "medium"
    else:
        risk_level = "HIGH RISK"
        risk_class = "high"

    return {
        'risk_level': risk_level,
        'risk_class': risk_class,
        'risk_points': risk_points,
        'trust_indicators': trust_indicators,
        'warnings': warnings,
        'completeness': completeness,
        'email_domain': email_domain,
        'website_domain': website_domain,
        'reports_count': reports_count,
        'jobs_count': jobs_count
    }


def compute_company_completeness(c):
    """Calculates profile completeness percentage for an employer/company."""
    if not c:
        return 0
    score = 0
    if c.get('company_name'): score += 20
    if c.get('email') or c.get('mobile'): score += 15
    if c.get('industry'): score += 15
    if c.get('location'): score += 15
    if c.get('company_size') or c.get('size'): score += 10
    if c.get('website') or c.get('company_website'): score += 10
    if c.get('description') and len(str(c.get('description')).strip()) > 15: score += 10
    if c.get('founded_year') or c.get('linkedin_url') or c.get('twitter_url'): score += 5
    return min(100, score)


# --- RELATIVE TIME & JOB FORMATTING HELPERS ---
def format_relative_time(dt):
    """
    Calculates accurate human relative timestamp and returns (formatted_str, is_new_boolean).
    is_new is True only if the job was created within the last 24 hours.
    """
    if not dt:
        return "Recently", False

    now = datetime.now()
    # Handle both datetime and date objects
    if not isinstance(dt, datetime) and hasattr(dt, 'year'):
        dt = datetime(dt.year, dt.month, dt.day)

    diff = now - dt
    total_seconds = int(diff.total_seconds())

    if total_seconds < 0:
        return "Just now", True

    is_new = total_seconds < 86400  # Within 24 hours

    if total_seconds < 60:
        return "Just now", is_new
    elif total_seconds < 3600:
        mins = max(1, total_seconds // 60)
        return f"{mins} minute{'s' if mins != 1 else ''} ago", is_new
    elif total_seconds < 86400:
        hours = max(1, total_seconds // 3600)
        return f"{hours} hour{'s' if hours != 1 else ''} ago", is_new
    elif total_seconds < 172800:
        return "1 day ago", is_new
    elif total_seconds < 2592000:  # 30 days
        days = max(1, total_seconds // 86400)
        return f"{days} day{'s' if days != 1 else ''} ago", is_new
    else:
        return "30+ days ago", False


def enrich_job_presentation(job):
    """Enriches raw database job dictionary with display fields for UI templates."""
    if not job:
        return job

    # Ensure consistent ID resolution across id and job_id
    if not job.get('id') and job.get('job_id'):
        job['id'] = job['job_id']
    elif not job.get('job_id') and job.get('id'):
        job['job_id'] = job['id']

    # Relative time and new indicator
    created_at = job.get('created_at')
    time_str, is_new = format_relative_time(created_at)
    job['posted_time_ago'] = time_str
    job['is_new'] = is_new

    # Standardized relative posted label
    if time_str.lower() == 'just now':
        job['posted_label'] = 'Posted just now'
    elif 'ago' in time_str:
        job['posted_label'] = f"Posted {time_str}"
    else:
        job['posted_label'] = f"Posted {time_str} ago"

    # Verification status check
    is_verified = bool(
        job.get('employer_is_verified') or
        job.get('verification_status') == 'verified' or
        job.get('employer_verification_status') == 'verified'
    )
    job['is_company_verified'] = is_verified

    # Company name and avatar initials
    company = (job.get('company_name') or 'Employer').strip()
    job['company_name'] = company
    job['company_initial'] = company[0].upper() if company else 'E'

    # Salary formatting
    s_min = job.get('salary_min') or 0
    s_max = job.get('salary_max') or 0
    if job.get('salary') and str(job.get('salary')).strip():
        job['salary_display'] = str(job.get('salary')).strip()
    elif s_min > 0 and s_max > 0:
        job['salary_display'] = f"₹{s_min:,} - ₹{s_max:,}"
    elif s_min > 0:
        job['salary_display'] = f"₹{s_min:,}+"
    else:
        job['salary_display'] = "Competitive Compensation"

    # Skills parsing
    skills_raw = job.get('skills') or ''
    job['skills_list'] = [s.strip() for s in skills_raw.split(',') if s.strip()][:5]

    return job

# --- LOAD ML MODEL AT STARTUP ---
load_sentence_model()
# --- NLP SEARCH LOGIC ---
def get_nlp_search_results(jobs, query):
    if not jobs:
        return []

    # --- Semantic search with sentence-transformers (primary) ---
    model = _get_sentence_model()
    if model is not None:
        try:
            corpus = [f"{j['title']} {j.get('skills','')} {j.get('description','')} {j.get('category','')}" for j in jobs]
            embeddings = model.encode(corpus, show_progress_bar=False)
            query_emb = model.encode([query], show_progress_bar=False)[0]
            cosine_similarities = cosine_similarity([query_emb], embeddings).flatten()
            # Boost by keyword overlap as a secondary signal
            for i, j in enumerate(jobs):
                kw_boost = 0
                j_text = f"{j.get('title','')} {j.get('skills','')} {j.get('description','')}".lower()
                for kw in query.lower().split():
                    if kw in j_text:
                        kw_boost += 0.03
                cosine_similarities[i] = min(1.0, cosine_similarities[i] + kw_boost)
            related_docs_indices = cosine_similarities.argsort()[::-1]
            scored_jobs = []
            for i in related_docs_indices:
                if cosine_similarities[i] > 0.0:
                    jobs[i]['score'] = round(float(cosine_similarities[i]) * 100, 2)
                    scored_jobs.append(jobs[i])
            return scored_jobs
        except Exception as e:
            logger.warning(f"Sentence-transformers search failed, falling back to TF-IDF: {e}")

    # --- TF-IDF fallback ---
    corpus = [f"{j['title']} {j.get('skills','')} {j.get('description','')}" for j in jobs]
    corpus.append(query)
    vectorizer = TfidfVectorizer(stop_words='english', ngram_range=(1, 2))
    tfidf_matrix = vectorizer.fit_transform(corpus)
    cosine_similarities = cosine_similarity(tfidf_matrix[-1], tfidf_matrix[:-1]).flatten()
    related_docs_indices = cosine_similarities.argsort()[::-1]
    scored_jobs = []
    for i in related_docs_indices:
        if cosine_similarities[i] > 0.0:
            jobs[i]['score'] = round(float(cosine_similarities[i]) * 100, 2)
            scored_jobs.append(jobs[i])
    return scored_jobs

# --- MIDDLEWARE ---
@app.before_request
def validate_session():
    """Validate session fingerprint and concurrent session control."""
    if 'user_id' in session or 'employer_id' in session:
        # Session fingerprint validation
        stored_fp = session.get('fingerprint')
        if stored_fp and stored_fp != _session_fingerprint():
            logger.warning("Session fingerprint mismatch. Possible hijacking attempt.")
            session.clear()
            if request.is_json or request.path.startswith('/api/') or request.headers.get('Accept') == 'application/json':
                return jsonify({'success': False, 'message': 'Session invalidated for security reasons. Please login again.'}), 401
            return redirect(url_for('index'))
        
        # Concurrent session control via session_version & banned user check
        if 'user_id' in session:
            with db_cursor() as cur:
                cur.execute("SELECT session_version, is_banned, is_deleted FROM user WHERE id = %s", (session['user_id'],))
                row = cur.fetchone()
                if row:
                    if row.get('is_banned') or row.get('is_deleted'):
                        session.clear()
                        if request.is_json or request.path.startswith('/api/') or request.headers.get('Accept') == 'application/json':
                            return jsonify({'success': False, 'message': 'Your account has been deactivated or banned. Please contact support.'}), 401
                        return redirect(url_for('index'))
                    if row.get('session_version') is not None and session.get('session_version') is not None and row['session_version'] != session.get('session_version'):
                        session.clear()
                        if request.is_json or request.path.startswith('/api/') or request.headers.get('Accept') == 'application/json':
                            return jsonify({'success': False, 'message': 'Your session has expired or password was changed. Please login again.'}), 401
                        return redirect(url_for('index'))
                elif not app.config.get('TESTING') and not session.get('is_admin'):
                    session.clear()
                    if request.is_json or request.path.startswith('/api/') or request.headers.get('Accept') == 'application/json':
                        return jsonify({'success': False, 'message': 'Invalid session.'}), 401
                    return redirect(url_for('index'))
        elif 'employer_id' in session:
            with db_cursor() as cur:
                cur.execute("SELECT session_version FROM employee WHERE id = %s", (session['employer_id'],))
                row = cur.fetchone()
                if row and row.get('session_version') is not None and session.get('session_version') is not None and row['session_version'] != session.get('session_version'):
                    session.clear()
                    if request.is_json or request.path.startswith('/api/') or request.headers.get('Accept') == 'application/json':
                        return jsonify({'success': False, 'message': 'Your session has expired or password was changed. Please login again.'}), 401
                    return redirect(url_for('index'))

@app.after_request
def add_security_headers(response):
    """Add security headers to all responses."""
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    response.headers['Permissions-Policy'] = 'geolocation=(), microphone=(), camera=()'
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.jsdelivr.net https://unpkg.com https://cdnjs.cloudflare.com; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdnjs.cloudflare.com https://cdn.jsdelivr.net; "
        "font-src 'self' https://fonts.gstatic.com https://cdnjs.cloudflare.com data:; "
        "img-src 'self' data: blob: https://images.unsplash.com https://ui-avatars.com; "
        "connect-src 'self'; "
        "frame-ancestors 'none'; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "form-action 'self';"
    )
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    if request.path.endswith('.css') or request.path.endswith('.js'):
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, proxy-revalidate, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '-1'
    if os.getenv('FLASK_ENV') == 'production' or os.getenv('SESSION_COOKIE_SECURE', '0') == '1':
        response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    return response

# --- ROUTES ---
@app.route('/')
def index():
    featured_jobs = []
    total_active_jobs = 0
    fresh_jobs_count = 0

    try:
        with db_cursor() as cursor:
            # Total active published jobs
            cursor.execute("""
                SELECT COUNT(*) AS total
                FROM jobs
                WHERE is_active = 1
                  AND (status = 'Published' OR status IS NULL)
                  AND (application_deadline IS NULL OR application_deadline >= CURDATE())
            """)
            total_active_jobs = cursor.fetchone()['total']

            # Count jobs posted in last 24 hours
            cursor.execute("""
                SELECT COUNT(*) AS fresh_cnt
                FROM jobs
                WHERE is_active = 1
                  AND (status = 'Published' OR status IS NULL)
                  AND created_at >= NOW() - INTERVAL 24 HOUR
                  AND (application_deadline IS NULL OR application_deadline >= CURDATE())
            """)
            fresh_jobs_count = cursor.fetchone()['fresh_cnt']

            # Latest 6 verified/legitimate jobs
            cursor.execute("""
                SELECT j.*, COALESCE(e.company_name, j.company_name) AS company_name,
                       e.is_verified AS employer_is_verified, e.verification_status AS employer_verification_status
                FROM jobs j
                LEFT JOIN employee e ON j.employer_id = e.id
                WHERE j.is_active = 1
                  AND (j.status = 'Published' OR j.status IS NULL)
                  AND (j.application_deadline IS NULL OR j.application_deadline >= CURDATE())
                ORDER BY j.created_at DESC, j.id DESC
                LIMIT 6
            """)
            raw_jobs = cursor.fetchall()
            featured_jobs = [enrich_job_presentation(j) for j in raw_jobs]
    except Exception as e:
        logger.error(f"Error fetching homepage jobs: {e}")

    return render_template(
        'index.html',
        featured_jobs=featured_jobs,
        total_active_jobs=total_active_jobs,
        fresh_jobs_count=fresh_jobs_count
    )
@app.route('/employee_dashboard')
@app.route('/employee')
@app.route('/employer')
@app.route('/employer_dashboard')
def employer_dashboard():
    if 'employer_id' not in session: return redirect(url_for('index', auth='emp_login'))
    with db_cursor() as cursor:
        cursor.execute("SELECT company_name FROM employee WHERE id = %s", (session['employer_id'],))
        emp = cursor.fetchone()
        if emp and emp.get('company_name'):
            session['user_name'] = emp['company_name']
            session['company_name'] = emp['company_name']
    return render_template('employer_dashboard.html', user_name=session.get('user_name'))

@app.route('/candidate_dashboard')
@app.route('/candidate')
@app.route('/user_dashboard')
def user_dashboard():
    if 'user_id' not in session: return redirect(url_for('index', auth='login'))
    profile_photo = None
    try:
        with db_cursor() as cursor:
            cursor.execute("SELECT profile_photo FROM candidate_profile WHERE user_id = %s", (session['user_id'],))
            row = cursor.fetchone()
            if row and row.get('profile_photo'):
                profile_photo = row['profile_photo']
    except Exception as e:
        logger.warning(f"Error fetching profile photo for user_dashboard: {e}")
    return render_template('user_dashboard.html', user_name=session.get('user_name'), profile_photo=profile_photo)

@app.route('/signin')
@app.route('/login')
def login_redirect():
    if 'user_id' in session:
        return redirect(url_for('user_dashboard'))
    if 'employer_id' in session:
        return redirect(url_for('employer_dashboard'))
    return redirect(url_for('index', auth='login'))

@app.route('/employer_login')
@app.route('/employee/login')
@app.route('/employee_login')
@app.route('/employer/login')
def employer_login_redirect():
    if 'employer_id' in session:
        return redirect(url_for('employer_dashboard'))
    return redirect(url_for('index', auth='emp_login'))

@app.route('/register')
@app.route('/signup')
def signup_redirect():
    if 'user_id' in session:
        return redirect(url_for('user_dashboard'))
    if 'employer_id' in session:
        return redirect(url_for('employer_dashboard'))
    tab = (request.args.get('tab') or request.args.get('auth') or '').lower()
    if tab in ('login', 'signin'):
        return redirect(url_for('index', auth='login'))
    elif tab in ('employer', 'emp_register'):
        return redirect(url_for('index', auth='emp_register'))
    elif tab == 'emp_login':
        return redirect(url_for('index', auth='emp_login'))
    return redirect(url_for('index', auth='signup'))

@app.route('/user_dashboard/profile')
def user_profile_edit():
    if 'user_id' not in session: return redirect(url_for('index', auth='login'))
    return render_template('user_profile_edit.html', user_name=session.get('user_name'))

@app.route('/user_settings')
def user_settings():
    if 'user_id' not in session: return redirect(url_for('index', auth='login'))
    return render_template('user_settings.html', user_name=session.get('user_name'))

@app.route('/employer_settings')
def employer_settings():
    if 'employer_id' not in session: return redirect(url_for('index', auth='emp_login'))
    with db_cursor() as cursor:
        cursor.execute("SELECT company_name FROM employee WHERE id = %s", (session['employer_id'],))
        emp = cursor.fetchone()
        if emp and emp.get('company_name'):
            session['user_name'] = emp['company_name']
            session['company_name'] = emp['company_name']
    return render_template('employer_settings.html', user_name=session.get('user_name'))

# --- ADMIN ENDPOINTS ---
@app.route('/api/admin/unlock_account', methods=['POST'])
@limiter.limit("10 per minute")
def api_admin_unlock_account():
    if not require_admin(): return jsonify({'success': False, 'message': 'Unauthorized'}), 403
    data = request.json or {}
    email = normalize_email(data.get('email'))
    account_type = data.get('account_type', 'user')
    if account_type not in ('user', 'employer'):
        return jsonify({'success': False, 'message': 'Invalid account type'}), 400
    with db_cursor(dictionary=False) as cur:
        cur.execute(
            "DELETE FROM login_attempts WHERE email = %s AND account_type = %s",
            (email, account_type)
        )
    logger.info(f"Admin unlocked {account_type} account: {email}")
    return jsonify({'success': True, 'message': 'Account unlocked'})

@app.route('/api/admin/activity_log')
def api_admin_activity_log():
    if not require_admin(): return jsonify({'success': False, 'message': 'Unauthorized'}), 403
    page = max(1, request.args.get('page', 1, type=int) or 1)
    per_page = min(100, max(1, request.args.get('per_page', 50, type=int) or 50))
    offset = (page - 1) * per_page
    action_filter = request.args.get('action', '')
    with db_cursor() as cursor:
        base_query = "FROM activity_log WHERE 1=1"
        params = []
        if action_filter:
            base_query += " AND action = %s"
            params.append(action_filter)
        cursor.execute(f"SELECT COUNT(*) AS total {base_query}", params)
        total = cursor.fetchone()['total']
        cursor.execute(f"SELECT * {base_query} ORDER BY created_at DESC LIMIT %s OFFSET %s", params + [per_page, offset])
        logs = cursor.fetchall()
    for l in logs:
        if l.get('created_at'): l['created_at'] = l['created_at'].strftime('%Y-%m-%d %H:%M:%S')
    return jsonify({'success': True, 'logs': logs, 'total': total, 'page': page})

@app.route('/api/admin/login_audit')
def api_admin_login_audit():
    if not require_admin(): return jsonify({'success': False, 'message': 'Unauthorized'}), 403
    page = max(1, request.args.get('page', 1, type=int) or 1)
    per_page = min(100, max(1, request.args.get('per_page', 50, type=int) or 50))
    offset = (page - 1) * per_page
    email_filter = request.args.get('email', '')
    status_filter = request.args.get('status', '')
    with db_cursor() as cursor:
        base_query = "FROM login_audit_log WHERE 1=1"
        params = []
        if email_filter:
            base_query += " AND email LIKE %s"
            params.append(f"%{email_filter}%")
        if status_filter:
            base_query += " AND status = %s"
            params.append(status_filter)
        cursor.execute(f"SELECT COUNT(*) AS total {base_query}", params)
        total = cursor.fetchone()['total']
        cursor.execute(f"SELECT * {base_query} ORDER BY created_at DESC LIMIT %s OFFSET %s", params + [per_page, offset])
        logs = cursor.fetchall()
    for l in logs:
        if l.get('created_at'): l['created_at'] = l['created_at'].strftime('%Y-%m-%d %H:%M:%S')
    return jsonify({'success': True, 'logs': logs, 'total': total, 'page': page})


# --- DATA EXPORT (GDPR) ---
@app.route('/api/user/export_data')
def api_export_user_data():
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    uid = session['user_id']
    export = {}
    with db_cursor() as cur:
        # Basic profile
        try:
            cur.execute("SELECT id, name, email, mobile, created_at, is_verified FROM user WHERE id = %s", (uid,))
            export['profile'] = cur.fetchone()
        except Exception as e:
            logger.warning(f"Could not export profile for user {uid}: {e}")
            export['profile'] = None

        # Applications
        try:
            cur.execute("SELECT * FROM applications WHERE user_id = %s", (uid,))
            export['applications'] = cur.fetchall()
        except Exception as e:
            logger.warning(f"Could not export applications for user {uid}: {e}")
            export['applications'] = []

        # Saved jobs
        try:
            cur.execute("""
                SELECT j.*, COALESCE(e.company_name, j.company_name) AS company_name
                FROM jobs j
                LEFT JOIN employee e ON j.employer_id = e.id
                JOIN saved_jobs s ON j.id = s.job_id
                WHERE s.user_id = %s
            """, (uid,))
            export['saved_jobs'] = cur.fetchall()
        except Exception as e:
            logger.warning(f"Could not export saved_jobs for user {uid}: {e}")
            export['saved_jobs'] = []

        # Job alerts
        try:
            cur.execute("SELECT * FROM job_alerts WHERE user_id = %s", (uid,))
            export['job_alerts'] = cur.fetchall()
        except Exception as e:
            logger.warning(f"Could not export job_alerts for user {uid}: {e}")
            export['job_alerts'] = []

        # Candidate profile
        try:
            cur.execute("SELECT * FROM candidate_profile WHERE user_id = %s", (uid,))
            export['candidate_profile'] = cur.fetchone()
        except Exception as e:
            logger.warning(f"Could not export candidate_profile for user {uid}: {e}")
            export['candidate_profile'] = None

        # Candidate extension tables (gracefully handles missing/broken tables)
        candidate_tables = [
            'candidate_personal_details', 'candidate_preferences', 'candidate_profile_summary',
            'key_skills', 'employment', 'education', 'it_skills', 'internships', 'projects',
            'online_profiles', 'work_samples', 'certifications', 'publications', 'presentations',
            'patents', 'competitive_exams', 'academic_achievements', 'languages', 'preferred_locations'
        ]
        for table in candidate_tables:
            try:
                cur.execute(f"SELECT * FROM {table} WHERE user_id = %s", (uid,))
                export[table] = cur.fetchall()
            except Exception as e:
                logger.warning(f"Could not export table '{table}' for user {uid}: {e}")
                export[table] = []

        # Notifications
        try:
            cur.execute("SELECT message, is_read, created_at FROM notifications WHERE user_id = %s", (uid,))
            export['notifications'] = cur.fetchall()
        except Exception as e:
            logger.warning(f"Could not export notifications for user {uid}: {e}")
            export['notifications'] = []

        # Activity log
        try:
            cur.execute(
                "SELECT action, target_type, target_id, details, created_at "
                "FROM activity_log WHERE actor_type = 'user' AND actor_id = %s",
                (uid,)
            )
            export['activity_log'] = cur.fetchall()
        except Exception as e:
            logger.warning(f"Could not export activity_log for user {uid}: {e}")
            export['activity_log'] = []

    return jsonify({'success': True, 'data': export, 'exported_at': datetime.now().isoformat()})


# --- HEALTH CHECK & MONITORING ---
@app.route('/healthz')
@app.route('/api/healthz')
@app.route('/api/health')
def health_check():
    """Lightweight health check endpoint verifying database connectivity."""
    start_time = time.time()
    health = {
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'services': {}
    }
    http_code = 200
    try:
        with db_cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
        latency_ms = round((time.time() - start_time) * 1000, 2)
        health['services']['database'] = {'status': 'healthy', 'latency_ms': latency_ms}
    except Exception as e:
        logger.error(f"Health check database ping failed: {e}")
        health['status'] = 'unhealthy'
        health['services']['database'] = {'status': 'unreachable'}
        http_code = 503
    return jsonify(health), http_code

@app.route('/logout', methods=['GET', 'POST'])
@app.route('/api/auth/logout', methods=['POST'])
def logout():
    session.clear()
    if request.is_json or request.headers.get('Accept') == 'application/json':
        return jsonify({'success': True, 'message': 'Logged out successfully', 'redirect': url_for('index')})
    return redirect(url_for('index'))

# --- DOWNLOAD RESUME ---
@app.route('/download_resume/<path:filename>')
@limiter.limit("60 per minute")
def download_resume(filename):
    if 'employer_id' not in session: return "Unauthorized", 401
    safe_name = secure_filename(filename)
    if not safe_name or safe_name != filename:
        return "Forbidden", 403
    # Ensure the resume belongs to an application for a job this employer owns
    with db_cursor() as cursor:
        cursor.execute("""
            SELECT 1 FROM applications a
            JOIN jobs j ON a.job_id = j.id
            WHERE a.resume_path = %s AND j.employer_id = %s
        """, (safe_name, session['employer_id']))
        if not cursor.fetchone():
            return "Forbidden", 403
    try:
        return send_from_directory(app.config['UPLOAD_FOLDER'], safe_name, as_attachment=True)
    except FileNotFoundError:
        return "File not found", 404

# --- CHECK SESSION ---
@app.route('/api/check_session')
def check_session():
    return jsonify({'logged_in': 'user_id' in session})

# --- AUTH APIs ---
def verify_otp(email, otp):
    """Verify OTP, reject expired OTPs, consume on success, enforce brute-force rate limits."""
    email = normalize_email(email)
    if not email or not otp:
        return False

    # Brute-force protection on OTP guessing (max 5 failed attempts per 5 minutes per email)
    if not check_rate_limit(f"otp_guess:{email}", "otp_verify", limit=5, window_seconds=300):
        logger.warning(f"OTP guessing rate limit exceeded for {email}")
        return False

    now = datetime.now()
    with db_cursor() as cur:
        # Clean up expired OTPs
        cur.execute("DELETE FROM otp_store WHERE expires_at IS NOT NULL AND expires_at < %s", (now,))
        cur.execute(
            "SELECT otp, expires_at FROM otp_store WHERE email = %s ORDER BY created_at DESC LIMIT 1",
            (email,)
        )
        row = cur.fetchone()
        if not row:
            return False
        # Reject if expired
        if row.get('expires_at') and row['expires_at'] < now:
            return False
        if row['otp'] != str(otp).strip():
            return False
        # Consume the OTP so it cannot be reused
        cur.execute("DELETE FROM otp_store WHERE email = %s", (email,))
        cur.execute("DELETE FROM rate_limits WHERE rate_key = %s", (f"otp_guess:{email}",))
        return True


def check_otp_rate_limit(email, limit=3, window=60):
    """DB-backed rate limiter for OTP requests — works across workers."""
    return check_rate_limit(email, 'otp_request', limit=limit, window_seconds=window)


@app.route('/api/send_otp', methods=['POST'])
@limiter.limit("3 per minute")
def api_send_otp():
    data = request.json or {}
    email = normalize_email(data.get('email'))
    action = (data.get('action') or '').strip()
    if not email:
        return jsonify({'success': False, 'message': 'Email required'})
    if not validate_email(email):
        return jsonify({'success': False, 'message': 'Invalid email format'})

    # Pre-check email existence based on registration vs password reset
    with db_cursor() as cursor:
        if action == 'register':
            cursor.execute("SELECT id FROM user WHERE email = %s", (email,))
            if cursor.fetchone():
                return jsonify({'success': False, 'message': 'Email is already registered. Please sign in.'})
        elif action == 'emp_register':
            cursor.execute("SELECT id FROM employee WHERE email = %s", (email,))
            if cursor.fetchone():
                return jsonify({'success': False, 'message': 'Work email is already registered. Please sign in.'})
        elif action == 'forgot':
            cursor.execute("SELECT id FROM user WHERE email = %s", (email,))
            if not cursor.fetchone():
                cursor.execute("SELECT id FROM employee WHERE email = %s", (email,))
                if not cursor.fetchone():
                    return jsonify({'success': False, 'message': 'No candidate account found with this email.'})
        elif action == 'emp_forgot':
            cursor.execute("SELECT id FROM employee WHERE email = %s", (email,))
            if not cursor.fetchone():
                cursor.execute("SELECT id FROM user WHERE email = %s", (email,))
                if cursor.fetchone():
                    return jsonify({'success': False, 'message': 'This email is registered as a Candidate. Please switch to Candidate Sign In.', 'suggest_role': 'candidate'})
                return jsonify({'success': False, 'message': 'No employer account found with this work email.'})

    if not check_otp_rate_limit(email):
        return jsonify({'success': False, 'message': 'Too many OTP requests. Please wait a minute.'})
    otp = ''.join(random.choices(string.digits, k=6))
    otp_expiry = datetime.now() + timedelta(seconds=OTP_TTL_SECONDS)

    with db_cursor(dictionary=False) as cursor:
        cursor.execute("DELETE FROM otp_store WHERE email = %s", (email,))
        cursor.execute("DELETE FROM rate_limits WHERE rate_key = %s", (f"otp_guess:{email}",))
        cursor.execute(
            "INSERT INTO otp_store (email, otp, expires_at) VALUES (%s, %s, %s)",
            (email, otp, otp_expiry)
        )

    try:
        msg = EmailMessage()
        msg.set_content(f"""HireVoltz - Verification Code

Dear User,

Your One-Time Password (OTP) for verification is:

{otp}

This code is valid for the next 2 minutes. Please do not share this code with anyone for security reasons.

If you did not request this, please ignore this email.

Best regards,
HireVoltz Team""")
        msg['Subject'] = "Your Verification Code - HireVoltz"
        msg['From'] = EMAIL_ADDRESS
        msg['To'] = email

        smtp_host = os.getenv('SMTP_HOST', 'smtp.gmail.com')
        smtp_port_587 = int(os.getenv('SMTP_PORT_STARTTLS', '587'))
        smtp_port_465 = int(os.getenv('SMTP_PORT_SSL', '465'))
        smtp_timeout = int(os.getenv('SMTP_TIMEOUT', '10'))
        last_error = None

        logger.info(f"Attempting OTP email to {email} via {smtp_host} (ports {smtp_port_587}, {smtp_port_465})")

        for port, use_ssl in [(smtp_port_587, False), (smtp_port_465, True)]:
            try:
                if use_ssl:
                    logger.info(f"Trying SMTP_SSL on port {port} (SSL={use_ssl})")
                    with smtplib.SMTP_SSL(smtp_host, port, timeout=smtp_timeout) as smtp:
                        smtp.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
                        smtp.send_message(msg)
                else:
                    logger.info(f"Trying SMTP/STARTTLS on port {port} (SSL={use_ssl})")
                    with smtplib.SMTP(smtp_host, port, timeout=smtp_timeout) as smtp:
                        smtp.ehlo()
                        smtp.starttls()
                        smtp.ehlo()
                        smtp.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
                        smtp.send_message(msg)
                logger.info(f"OTP sent to {email}")
                return jsonify({'success': True, 'message': 'OTP Sent to Email'})
            except smtplib.SMTPAuthenticationError as e:
                logger.warning(f"SMTP authentication failed on port {port} (SSL={use_ssl}): smtp_code={e.smtp_code} smtp_error={e.smtp_error}")
                last_error = e
                continue
            except smtplib.SMTPConnectError as e:
                logger.warning(f"SMTP connection failed on port {port} (SSL={use_ssl}): smtp_code={e.smtp_code}")
                last_error = e
                continue
            except smtplib.SMTPServerDisconnected as e:
                logger.warning(f"SMTP server disconnected on port {port} (SSL={use_ssl}): {e}")
                last_error = e
                continue
            except (smtplib.SMTPException, OSError) as e:
                logger.warning(f"Email attempt failed on port {port} (SSL={use_ssl}) for {email}: {e}")
                last_error = e
                continue

        with db_cursor(dictionary=False) as cursor:
            cursor.execute("DELETE FROM otp_store WHERE email = %s", (email,))
        logger.info(f"Cleaned up unusable OTP for {email} after SMTP failure")

        logger.error(f"Email error (all ports failed for {email}): {last_error}")
        return jsonify({'success': False, 'message': 'Failed to send email via all SMTP ports. Port may be blocked or credentials invalid.'})
    except Exception as e:
        logger.error(f"Email error for {email}: {e}")
        with db_cursor(dictionary=False) as cursor:
            cursor.execute("DELETE FROM otp_store WHERE email = %s", (email,))
        return jsonify({'success': False, 'message': 'An unexpected error occurred while sending email.'})

@app.route('/api/user/register', methods=['POST'])
@limiter.limit("5 per minute")
def api_user_register():
    data = request.json or {}
    email = normalize_email(data.get('email'))
    otp = data.get('otp')
    name = data.get('name', '').strip() if data.get('name') else ''
    name = bleach.clean(name, tags=[], strip=True)
    mobile = data.get('mobile', '').strip() if data.get('mobile') else ''
    password = data.get('password', '')

    # Input validation
    if not name:
        return jsonify({'success': False, 'message': 'Name is required'}), 400
    if not validate_email(email):
        return jsonify({'success': False, 'message': 'Valid email is required'}), 400
    if not validate_password(password):
        return jsonify({'success': False, 'message': 'Password must be at least 8 characters with at least one letter and one number'}), 400
    if not validate_mobile(mobile):
        return jsonify({'success': False, 'message': 'Invalid mobile number'}), 400
    ok, err = validate_length(name, 100, 'Name')
    if not ok:
        return jsonify({'success': False, 'message': err}), 400

    with db_cursor() as cursor:
        cursor.execute("SELECT id FROM user WHERE email = %s", (email,))
        if cursor.fetchone():
            return jsonify({'success': False, 'message': 'Email already exists. Please login.'})

    # Gate registration on a confirmed OTP
    if not verify_otp(email, otp):
        return jsonify({'success': False, 'message': 'Invalid or missing OTP. Please verify your email.'})

    hashed_pw = generate_password_hash(password)
    with db_cursor() as cursor:
        cursor.execute("INSERT INTO user (name, email, mobile, password, is_verified) VALUES (%s, %s, %s, %s, %s)",
                       (name, email, mobile, hashed_pw, True))
        user_id = cursor.lastrowid

    # Store password in history
    _store_password_history(user_id, None, hashed_pw)
    # Log activity
    log_activity('user', user_id, 'registered')

    # Clear any stale session data, then set the new user session
    session.clear()
    session.permanent = True
    session['user_id'] = user_id
    session['user_name'] = name
    session['role'] = 'candidate'
    session['session_version'] = 0
    session['fingerprint'] = _session_fingerprint()
    csrf_tok = generate_csrf()
    logger.info(f"User registered: id={user_id}")
    return jsonify({
        'success': True,
        'message': 'Account Created Successfully!',
        'redirect': '/user_dashboard',
        'csrf_token': csrf_tok
    })

@app.route('/api/user/login', methods=['POST'])
@limiter.limit(LOGIN_RATE_LIMIT)
def api_user_login():
    data = request.get_json(silent=True) or request.form or {}
    email = normalize_email(data.get('email', ''))
    password = data.get('password', '')

    if not email or not password:
        return jsonify({'success': False, 'message': 'Email and password are required'}), 400

    # Clear expired lockouts first
    _clear_expired_lockouts()

    # Check account lockout
    is_locked, minutes = _is_account_locked(email, 'user')
    if is_locked:
        _log_login_attempt(email, 'user', 'locked', 'account_locked')
        msg = f'Account locked due to too many failed attempts. Try again in {minutes} minutes.'
        return jsonify({'success': False, 'message': msg}), 429

    # DB-based rate limiting by email+IP
    client_ip = request.remote_addr or 'unknown'
    rate_key = f"{email}:{client_ip}"
    if not check_rate_limit(rate_key, 'login_attempt', limit=5, window_seconds=300):
        _log_login_attempt(email, 'user', 'rate_limited', 'rate_limit_exceeded')
        logger.warning(f"Login rate limit exceeded for {email} from {client_ip}")
        return jsonify({'success': False, 'message': 'Too many login attempts. Please try again in 5 minutes.'}), 429

    with db_cursor() as cursor:
        cursor.execute(
            "SELECT id, name, email, password, is_admin, session_version, is_banned, is_deleted FROM user WHERE email = %s",
            (email,)
        )
        user = cursor.fetchone()

    if not user:
        _log_login_attempt(email, 'user', 'failed', 'email_not_found')
        with db_cursor() as check_cur:
            check_cur.execute("SELECT id FROM employee WHERE email = %s", (email,))
            if check_cur.fetchone():
                return jsonify({'success': False, 'message': 'This email is registered as an Employer. Please switch to Employer Sign In.', 'suggest_role': 'employer'})
        return jsonify({'success': False, 'message': 'Email not found. Please register.'})

    if user.get('is_banned') or user.get('is_deleted'):
        _log_login_attempt(email, 'user', 'failed', 'account_banned')
        return jsonify({'success': False, 'message': 'Your account has been deactivated or banned. Please contact support.'}), 403

    db_password = str(user['password'])
    password_valid = False
    if check_password_hash(db_password, password):
        password_valid = True
    elif db_password == password:
        # Legacy plaintext auto-upgrade to scrypt/pbkdf2
        new_hashed = generate_password_hash(password)
        with db_cursor() as up_cursor:
            up_cursor.execute("UPDATE user SET password = %s WHERE id = %s", (new_hashed, user['id']))
        password_valid = True

    if password_valid:
        _reset_login_attempts(email, 'user', client_ip)
        _log_login_attempt(email, 'user', 'success', '')
        session.clear()
        session.permanent = True
        session['user_id'] = user['id']
        session['user_name'] = user['name']
        session['role'] = 'candidate'
        session['session_version'] = user.get('session_version', 0)
        session['fingerprint'] = _session_fingerprint()
        session['is_admin'] = bool(user.get('is_admin', 0))
        csrf_tok = generate_csrf()
        logger.info(f"User login: id={user['id']}")
        return jsonify({
            'success': True,
            'message': 'Login Successful',
            'redirect': '/user_dashboard',
            'csrf_token': csrf_tok
        })

    # Wrong password
    attempt_count, is_locked, locked_until = _record_failed_login(email, 'user')
    _log_login_attempt(email, 'user', 'failed', 'wrong_password')
    if is_locked:
        msg = f'Account locked due to too many failed attempts. Try again in {LOCKOUT_DURATION_MINUTES} minutes.'
        return jsonify({'success': False, 'message': msg}), 429
    remaining = MAX_FAILED_ATTEMPTS - attempt_count
    msg = f'Wrong Password. {remaining} attempts remaining before account lockout.'
    return jsonify({'success': False, 'message': msg})

@app.route('/api/employer/register', methods=['POST'])
@limiter.limit("5 per minute")
def api_employer_register():
    data = request.json or {}
    email = normalize_email(data.get('email'))
    otp = data.get('otp')
    name_raw = data.get('name') or data.get('company_name') or ''
    name = bleach.clean(str(name_raw).strip(), tags=[], strip=True)
    mobile = data.get('mobile', '').strip() if data.get('mobile') else ''
    password = data.get('password', '')

    # Input validation
    if not name:
        return jsonify({'success': False, 'message': 'Company name is required'}), 400
    if not validate_email(email):
        return jsonify({'success': False, 'message': 'Valid email is required'}), 400
    if not validate_password(password):
        return jsonify({'success': False, 'message': 'Password must be at least 8 characters with at least one letter and one number'}), 400
    if not validate_mobile(mobile):
        return jsonify({'success': False, 'message': 'Invalid mobile number'}), 400
    ok, err = validate_length(name, 100, 'Company name')
    if not ok:
        return jsonify({'success': False, 'message': err}), 400

    with db_cursor() as cursor:
        cursor.execute("SELECT id FROM employee WHERE email = %s", (email,))
        if cursor.fetchone():
            return jsonify({'success': False, 'message': 'Email already exists. Please login.'})

    # Gate registration on a confirmed OTP (consumed on success)
    if not verify_otp(email, otp):
        return jsonify({'success': False, 'message': 'Invalid or missing OTP. Please verify your email.'}), 400

    hashed_pw = generate_password_hash(password)
    with db_cursor() as cursor:
        cursor.execute("INSERT INTO employee (company_name, mobile, email, password) VALUES (%s, %s, %s, %s)",
                       (name, mobile, email, hashed_pw))
        emp_id = cursor.lastrowid

    # Store password in history
    _store_password_history(None, emp_id, hashed_pw)
    # Log activity
    log_activity('employer', emp_id, 'registered')

    # Auto Login: Set Session
    session.clear()
    session.permanent = True
    session['employer_id'] = emp_id
    session['user_name'] = name
    session['role'] = 'employer'
    session['session_version'] = 0
    session['fingerprint'] = _session_fingerprint()
    csrf_tok = generate_csrf()
    logger.info(f"Employer registered: id={emp_id}")
    return jsonify({
        'success': True,
        'message': 'Account Created Successfully!',
        'redirect': '/employer_dashboard',
        'csrf_token': csrf_tok
    })

@app.route('/api/employer/login', methods=['POST'])
@limiter.limit(LOGIN_RATE_LIMIT)
def api_employer_login():
    data = request.get_json(silent=True) or request.form or {}
    email = normalize_email(data.get('email', ''))
    password = data.get('password', '')

    if not email or not password:
        return jsonify({'success': False, 'message': 'Email and password are required'}), 400

    # Clear expired lockouts first
    _clear_expired_lockouts()

    # Check account lockout
    is_locked, minutes = _is_account_locked(email, 'employer')
    if is_locked:
        _log_login_attempt(email, 'employer', 'locked', 'account_locked')
        msg = f'Account locked due to too many failed attempts. Try again in {minutes} minutes.'
        return jsonify({'success': False, 'message': msg}), 429

    # DB-based rate limiting by email+IP
    client_ip = request.remote_addr or 'unknown'
    rate_key = f"{email}:{client_ip}"
    if not check_rate_limit(rate_key, 'login_attempt', limit=5, window_seconds=300):
        _log_login_attempt(email, 'employer', 'rate_limited', 'rate_limit_exceeded')
        logger.warning(f"Login rate limit exceeded for {email} from {client_ip}")
        return jsonify({'success': False, 'message': 'Too many login attempts. Please try again in 5 minutes.'}), 429

    with db_cursor() as cursor:
        cursor.execute(
            "SELECT id, company_name, email, password, session_version FROM employee WHERE email = %s",
            (email,)
        )
        emp = cursor.fetchone()

    if not emp:
        _log_login_attempt(email, 'employer', 'failed', 'email_not_found')
        with db_cursor() as check_cur:
            check_cur.execute("SELECT id FROM user WHERE email = %s", (email,))
            if check_cur.fetchone():
                return jsonify({'success': False, 'message': 'This email is registered as a Candidate. Please switch to Candidate Sign In.', 'suggest_role': 'candidate'})
        return jsonify({'success': False, 'message': 'Email not found. Please register.'})

    db_password = str(emp['password'])
    password_valid = False
    if check_password_hash(db_password, password):
        password_valid = True
    elif db_password == password:
        # Legacy plaintext auto-upgrade to scrypt/pbkdf2
        new_hashed = generate_password_hash(password)
        with db_cursor() as up_cursor:
            up_cursor.execute("UPDATE employee SET password = %s WHERE id = %s", (new_hashed, emp['id']))
        password_valid = True

    if password_valid:
        _reset_login_attempts(email, 'employer', client_ip)
        _log_login_attempt(email, 'employer', 'success', '')
        session.clear()
        session.permanent = True
        session['employer_id'] = emp['id']
        session['user_name'] = emp['company_name']
        session['role'] = 'employer'
        session['session_version'] = emp.get('session_version', 0)
        session['fingerprint'] = _session_fingerprint()
        csrf_tok = generate_csrf()
        logger.info(f"Employer login: id={emp['id']}")
        return jsonify({
            'success': True,
            'message': 'Login Successful',
            'redirect': '/employer_dashboard',
            'csrf_token': csrf_tok
        })

    # Wrong password
    attempt_count, is_locked, locked_until = _record_failed_login(email, 'employer')
    _log_login_attempt(email, 'employer', 'failed', 'wrong_password')
    if is_locked:
        msg = f'Account locked due to too many failed attempts. Try again in {LOCKOUT_DURATION_MINUTES} minutes.'
        return jsonify({'success': False, 'message': msg}), 429
    remaining = MAX_FAILED_ATTEMPTS - attempt_count
    msg = f'Wrong Password. {remaining} attempts remaining before account lockout.'
    return jsonify({'success': False, 'message': msg})

@app.route('/api/reset_password', methods=['POST'])
@app.route('/api/employer/reset_password', methods=['POST'])
@limiter.limit("5 per hour")
def api_reset_password():
    data = request.json or {}
    email = normalize_email(data.get('email'))
    otp = data.get('otp')
    new_password = data.get('password')
    if not all([email, otp, new_password]):
        return jsonify({'success': False, 'message': 'Missing fields'}), 400
    if not validate_password(new_password):
        return jsonify({'success': False, 'message': 'Password must be at least 8 characters with at least one letter and one number'}), 400

    # Verify and consume OTP via centralized helper (single source of truth for validation, expiry, and consumption)
    if not verify_otp(email, otp):
        return jsonify({'success': False, 'message': 'Invalid or expired OTP'}), 400

    with db_cursor() as cursor:
        # Check candidate (user) first, then employer (employee)
        cursor.execute("SELECT id FROM user WHERE email = %s", (email,))
        user = cursor.fetchone()
        if user:
            if not _check_password_history(user['id'], None, new_password):
                return jsonify({'success': False, 'message': 'You cannot reuse a recent password. Please choose a different one.'})
            hashed_pw = generate_password_hash(new_password)
            cursor.execute("UPDATE user SET password = %s, session_version = session_version + 1 WHERE email = %s", (hashed_pw, email))
            _store_password_history(user['id'], None, hashed_pw)
            log_activity('user', user['id'], 'changed_password')
        else:
            cursor.execute("SELECT id FROM employee WHERE email = %s", (email,))
            emp = cursor.fetchone()
            if not emp:
                return jsonify({'success': False, 'message': 'Email not found'}), 404
            if not _check_password_history(None, emp['id'], new_password):
                return jsonify({'success': False, 'message': 'You cannot reuse a recent password. Please choose a different one.'})
            hashed_pw = generate_password_hash(new_password)
            cursor.execute("UPDATE employee SET password = %s, session_version = session_version + 1 WHERE id = %s", (hashed_pw, emp['id']))
            _store_password_history(None, emp['id'], hashed_pw)
            log_activity('employer', emp['id'], 'changed_password')

    # Invalidate all existing sessions for this user
    session.clear()
    logger.info(f"Password reset for {email}")
    return jsonify({'success': True, 'message': 'Password Reset Successful'})

# --- CORE APIs ---
@app.route('/api/post_job', methods=['POST'])
@app.route('/api/employer/post_job', methods=['POST'])
@limiter.limit("10 per minute")
def api_post_job():
    if 'employer_id' not in session: return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    data = request.json or {}
    title = data.get('title', '').strip()
    if not title:
        return jsonify({'success': False, 'message': 'Job title is required'}), 400
    ok, err = validate_length(title, 255, 'Job title')
    if not ok:
        return jsonify({'success': False, 'message': err}), 400
    salary_min = data.get('salary_min') or 0
    salary_max = data.get('salary_max') or 0
    try:
        salary_min = int(salary_min)
        salary_max = int(salary_max)
    except (TypeError, ValueError):
        return jsonify({'success': False, 'message': 'salary_min and salary_max must be integers'}), 400
    if salary_min < 0 or salary_max < 0:
        return jsonify({'success': False, 'message': 'Salary values cannot be negative'}), 400
    if salary_max and salary_min and salary_min > salary_max:
        return jsonify({'success': False, 'message': 'salary_min cannot exceed salary_max'}), 400
    try:
        company_name = None
        with db_cursor() as cursor:
            cursor.execute("SELECT company_name FROM employee WHERE id = %s", (session['employer_id'],))
            emp = cursor.fetchone()
            if emp and emp.get('company_name'):
                company_name = emp['company_name']
        if not company_name:
            company_name = session.get('company_name') or session.get('user_name') or 'Verified Employer'

        with db_cursor(dictionary=False) as cursor:
            cursor.execute("""
                INSERT INTO jobs (employer_id, title, description, location, salary, experience, skills,
                    category, company_name, job_type, work_mode, salary_min, salary_max,
                    openings, application_deadline, is_active)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (session['employer_id'], title, data.get('description'), data.get('location'),
                  data.get('salary'), data.get('experience'), data.get('skills'), data.get('category'),
                  company_name, data.get('job_type', 'Full-time'), data.get('work_mode', 'Onsite'),
                  salary_min, salary_max,
                  data.get('openings') or 1,
                  data.get('application_deadline') or None,
                  data.get('is_active', True)))
            job_id = cursor.lastrowid
        
        # Populate candidate match cache for the newly posted job
        try:
            refresh_job_candidate_matches(job_id)
        except Exception as match_err:
            logger.warning(f"Background match generation failed for job {job_id}: {match_err}")

        logger.info(f"Job posted: id={job_id}, title={title}, employer_id={session['employer_id']}")
        return jsonify({'success': True, 'message': 'Job Posted', 'job_id': job_id, 'title': title})
    except Exception as e:
        logger.error(f"Error posting job: {e}")
        return jsonify({'success': False, 'message': 'An error occurred while posting the job'}), 500

@app.route('/api/get_employer_jobs')
@app.route('/api/employer/jobs')
def api_get_employer_jobs():
    if 'employer_id' not in session: return jsonify({'success': False}), 401
    with db_cursor() as cursor:
        cursor.execute("""
            SELECT j.*, COALESCE(e.company_name, j.company_name) AS company_name,
                   e.is_verified AS employer_is_verified, e.verification_status AS employer_verification_status
            FROM jobs j
            LEFT JOIN employee e ON j.employer_id = e.id
            WHERE j.employer_id = %s
            ORDER BY j.id DESC
        """, (session['employer_id'],))
        jobs = cursor.fetchall()
    for j in jobs:
        if j.get('created_at'): j['created_at'] = j['created_at'].strftime('%Y-%m-%d')
    return jsonify({'success': True, 'jobs': jobs})

@app.route('/api/delete_job/<int:job_id>', methods=['POST', 'DELETE'])
def delete_job(job_id):
    if 'employer_id' not in session: return jsonify({'success': False}), 401
    with db_cursor(dictionary=False) as cursor:
        cursor.execute("DELETE FROM jobs WHERE id = %s AND employer_id = %s", (job_id, session['employer_id']))
    logger.info(f"Job deleted: id={job_id}, employer_id={session['employer_id']}")
    return jsonify({'success': True, 'message': 'Job Deleted'})

MAJOR_INDIAN_LOCATIONS = [
    # Top Metros & Tech Hubs
    "Bengaluru", "Mumbai", "Delhi / NCR", "New Delhi", "Hyderabad", "Chennai", "Kolkata", "Pune", "Ahmedabad",
    "Gurugram (Gurgaon)", "Noida", "Greater Noida", "Ghaziabad", "Faridabad",

    # Karnataka
    "Mysuru (Mysore)", "Mangaluru (Mangalore)", "Hubballi-Dharwad", "Belagavi (Belgaum)", "Davanagere",
    "Ballari (Bellary)", "Shivamogga (Shimoga)", "Tumakuru (Tumkur)", "Udupi", "Manipal", "Hassan",

    # Maharashtra
    "Navi Mumbai", "Thane", "Nagpur", "Nashik", "Aurangabad (Chhatrapati Sambhajinagar)", "Solapur",
    "Kolhapur", "Amravati", "Nanded", "Jalgaon", "Akola", "Vasai-Virar", "Kalyan-Dombivli", "Panvel",

    # Tamil Nadu
    "Coimbatore", "Madurai", "Tiruchirappalli (Trichy)", "Salem", "Tirunelveli", "Erode", "Vellore",
    "Thoothukudi (Tuticorin)", "Dindigul", "Thanjavur", "Hosur", "Nagercoil", "Kanchipuram", "Tiruppur",

    # Telangana & Andhra Pradesh
    "Visakhapatnam", "Vijayawada", "Guntur", "Nellore", "Kurnool", "Rajahmundry", "Tirupati",
    "Kakinada", "Kadapa", "Anantapur", "Warangal", "Nizamabad", "Karimnagar", "Khammam", "Secunderabad",

    # Kerala
    "Kochi (Cochin)", "Thiruvananthapuram (Trivandrum)", "Kozhikode (Calicut)", "Thrissur", "Kollam",
    "Palakkad", "Kannur", "Alappuzha", "Kottayam", "Malappuram",

    # Gujarat
    "Surat", "Vadodara (Baroda)", "Rajkot", "Bhavnagar", "Jamnagar", "Gandhinagar", "Junagadh",
    "Anand", "Navsari", "Morbi", "Vapi", "Bharuch",

    # North India (Punjab, Haryana, HP, J&K, Uttarakhand, Chandigarh)
    "Chandigarh", "Mohali", "Panchkula", "Ludhiana", "Amritsar", "Jalandhar", "Patiala", "Bathinda",
    "Shimla", "Dharamshala", "Dehradun", "Haridwar", "Roorkee", "Rishikesh", "Jammu", "Srinagar",

    # Uttar Pradesh & Bihar
    "Lucknow", "Kanpur", "Varanasi", "Agra", "Prayagraj (Allahabad)", "Meerut", "Bareilly",
    "Aligarh", "Moradabad", "Gorakhpur", "Saharanpur", "Jhansi", "Mathura", "Ayodhya",
    "Patna", "Gaya", "Bhagalpur", "Muzaffarpur", "Purnia", "Darbhanga",

    # Rajasthan
    "Jaipur", "Jodhpur", "Udaipur", "Kota", "Bikaner", "Ajmer", "Alwar", "Bhilwara", "Sikar",

    # Madhya Pradesh & Chhattisgarh
    "Indore", "Bhopal", "Jabalpur", "Gwalior", "Ujjain", "Sagar", "Dewas", "Satna", "Ratlam",
    "Raipur", "Bhilai", "Bilaspur", "Korba", "Durg",

    # West Bengal, Odisha & Jharkhand
    "Howrah", "Durgapur", "Asansol", "Siliguri", "Kharagpur",
    "Bhubaneswar", "Cuttack", "Rourkela", "Berhampur", "Sambalpur", "Puri", "Balasore",
    "Ranchi", "Jamshedpur", "Dhanbad", "Bokaro", "Deoghar",

    # Northeast, Goa & Union Territories
    "Guwahati", "Silchar", "Dibrugarh", "Jorhat", "Shillong", "Imphal", "Agartala",
    "Aizawl", "Kohima", "Dimapur", "Gangtok", "Itanagar", "Panaji", "Margao", "Puducherry", "Port Blair",

    # Remote / Flexible Work
    "Remote", "Hybrid / Remote", "Work from Home"
]


def _is_indian_or_remote_location(loc_str):
    """
    Returns True if the given location string represents an Indian city/state or remote/flexible working.
    """
    if not loc_str:
        return True
    s = loc_str.strip().lower()
    
    # Direct remote keywords
    if s in ('remote', 'work from home', 'hybrid', 'wfh', 'pan india', 'anywhere in india', 'india', 'all india'):
        return True
        
    # Indian states, synonyms, and city roots
    indian_tokens = {
        'india', 'bharat', 'bengaluru', 'bangalore', 'mumbai', 'bombay', 'delhi', 'ncr', 'new delhi',
        'hyderabad', 'secunderabad', 'chennai', 'madras', 'kolkata', 'calcutta', 'pune', 'poona',
        'ahmedabad', 'gurgaon', 'gurugram', 'noida', 'greater noida', 'ghaziabad', 'faridabad',
        'mysuru', 'mysore', 'mangaluru', 'mangalore', 'hubballi', 'hubli', 'dharwad', 'belagavi',
        'belgaum', 'davanagere', 'ballari', 'bellary', 'shivamogga', 'shimoga', 'tumakuru', 'tumkur',
        'udupi', 'manipal', 'hassan', 'karnataka', 'navi mumbai', 'thane', 'nagpur', 'nashik',
        'aurangabad', 'sambhajinagar', 'solapur', 'kolhapur', 'amravati', 'nanded', 'jalgaon', 'akola',
        'vasai', 'virar', 'kalyan', 'dombivli', 'panvel', 'maharashtra', 'coimbatore', 'madurai',
        'tiruchirappalli', 'trichy', 'salem', 'tirunelveli', 'erode', 'vellore', 'thoothukudi',
        'tuticorin', 'dindigul', 'thanjavur', 'hosur', 'nagercoil', 'kanchipuram', 'tiruppur',
        'tamil nadu', 'visakhapatnam', 'vizag', 'vijayawada', 'guntur', 'nellore', 'kurnool',
        'rajahmundry', 'tirupati', 'kakinada', 'kadapa', 'anantapur', 'warangal', 'nizamabad',
        'karimnagar', 'khammam', 'telangana', 'andhra pradesh', 'andhra', 'kochi', 'cochin',
        'thiruvananthapuram', 'trivandrum', 'kozhikode', 'calicut', 'thrissur', 'kollam', 'palakkad',
        'kannur', 'alappuzha', 'alleppey', 'kottayam', 'malappuram', 'kerala', 'surat', 'vadodara',
        'baroda', 'rajkot', 'bhavnagar', 'jamnagar', 'gandhinagar', 'junagadh', 'anand', 'navsari',
        'morbi', 'vapi', 'bharuch', 'gujarat', 'chandigarh', 'mohali', 'panchkula', 'ludhiana',
        'amritsar', 'jalandhar', 'patiala', 'bathinda', 'punjab', 'haryana', 'shimla', 'dharamshala',
        'himachal pradesh', 'dehradun', 'haridwar', 'roorkee', 'rishikesh', 'uttarakhand', 'jammu',
        'srinagar', 'kashmir', 'lucknow', 'kanpur', 'varanasi', 'banaras', 'agra', 'prayagraj',
        'allahabad', 'meerut', 'bareilly', 'aligarh', 'moradabad', 'gorakhpur', 'saharanpur',
        'jhansi', 'mathura', 'ayodhya', 'uttar pradesh', 'up', 'patna', 'gaya', 'bhagalpur',
        'muzaffarpur', 'purnia', 'darbhanga', 'bihar', 'jaipur', 'jodhpur', 'udaipur', 'kota',
        'bikaner', 'ajmer', 'alwar', 'bhilwara', 'sikar', 'rajasthan', 'indore', 'bhopal',
        'jabalpur', 'gwalior', 'ujjain', 'sagar', 'dewas', 'satna', 'ratlam', 'madhya pradesh',
        'mp', 'raipur', 'bhilai', 'bilaspur', 'korba', 'durg', 'chhattisgarh', 'howrah', 'durgapur',
        'asansol', 'siliguri', 'kharagpur', 'west bengal', 'bhubaneswar', 'cuttack', 'rourkela',
        'berhampur', 'sambalpur', 'puri', 'balasore', 'odisha', 'orissa', 'ranchi', 'jamshedpur',
        'dhanbad', 'bokaro', 'deoghar', 'jharkhand', 'guwahati', 'silchar', 'dibrugarh', 'jorhat',
        'assam', 'shillong', 'meghalaya', 'imphal', 'manipur', 'agartala', 'tripura', 'aizawl',
        'mizoram', 'kohima', 'dimapur', 'nagaland', 'gangtok', 'sikkim', 'itanagar',
        'arunachal pradesh', 'panaji', 'margao', 'goa', 'puducherry', 'pondicherry', 'port blair',
        'andaman'
    }

    # Normalize words in input string
    words = re.findall(r'[a-zA-Z]+', s)
    if not words:
        return True
    
    # If any word matches an Indian location/state, check if all content is domestic/remote
    has_indian_token = any(w in indian_tokens for w in words)
    has_foreign_token = any(w in ('usa', 'uk', 'united kingdom', 'london', 'singapore', 'dubai', 'uae', 'emirates', 'canada', 'germany', 'berlin', 'tokyo', 'japan', 'australia', 'sydney', 'melbourne', 'toronto', 'vancouver', 'europe', 'france', 'paris', 'netherlands', 'amsterdam', 'ireland', 'dublin') for w in words)
    
    if has_foreign_token:
        return False
    if has_indian_token:
        return True

    # Check against clean strings in MAJOR_INDIAN_LOCATIONS
    for loc in MAJOR_INDIAN_LOCATIONS:
        clean_loc = re.sub(r'\(.*?\)', '', loc).strip().lower()
        if clean_loc and clean_loc in s:
            return True

    return False


def get_all_locations_data():
    """
    Returns grouped locations:
    - 'india': Comprehensive static list of ~150 major Indian cities across all states.
    - 'international': Dynamic list of foreign locations that actually exist in active jobs in the DB.
    """
    international_locations = []
    try:
        with db_cursor() as cursor:
            cursor.execute("""
                SELECT DISTINCT location
                FROM jobs
                WHERE is_active = 1
                  AND (application_deadline IS NULL OR application_deadline >= CURDATE())
                  AND location IS NOT NULL
                  AND TRIM(location) != ''
            """)
            rows = cursor.fetchall()
            seen_international = set()
            for r in rows:
                raw_loc = (r.get('location') or '').strip()
                if not raw_loc:
                    continue
                if not _is_indian_or_remote_location(raw_loc):
                    # Clean up and normalize
                    clean_intl = raw_loc.strip()
                    if clean_intl.lower() not in seen_international:
                        seen_international.add(clean_intl.lower())
                        international_locations.append(clean_intl)
    except Exception as e:
        logger.error(f"Error fetching dynamic international locations: {e}")

    international_locations.sort()

    return {
        'success': True,
        'india': MAJOR_INDIAN_LOCATIONS,
        'international': international_locations,
        'total_india': len(MAJOR_INDIAN_LOCATIONS),
        'total_international': len(international_locations)
    }


@app.route('/api/locations', methods=['GET'])
def api_locations():
    """
    GET /api/locations
    Returns grouped location data with comprehensive Indian cities and DB-derived international locations.
    """
    return jsonify(get_all_locations_data())


@app.route('/api/get_all_jobs')
def api_get_all_jobs():
    page = max(1, request.args.get('page', 1, type=int) or 1)
    per_page = min(100, max(1, request.args.get('per_page', 10, type=int) or 10))
    offset = (page - 1) * per_page
    with db_cursor() as cursor:
        cursor.execute("""
            SELECT COUNT(*) AS total
            FROM jobs
            WHERE is_active = 1 AND (application_deadline IS NULL OR application_deadline >= CURDATE())
        """)
        total = cursor.fetchone()['total']
        cursor.execute("""
            SELECT j.*, COALESCE(e.company_name, j.company_name) AS company_name,
                   e.is_verified AS employer_is_verified, e.verification_status AS employer_verification_status
            FROM jobs j
            LEFT JOIN employee e ON j.employer_id = e.id
            WHERE j.is_active = 1 AND (j.application_deadline IS NULL OR j.application_deadline >= CURDATE())
            ORDER BY j.id DESC
            LIMIT %s OFFSET %s
        """, (per_page, offset))
        jobs = cursor.fetchall()
    for j in jobs:
        if j.get('created_at'): j['created_at'] = j['created_at'].strftime('%Y-%m-%d')
    return jsonify({'success': True, 'jobs': jobs, 'total': total, 'page': page, 'per_page': per_page})

def execute_jobs_query(data):
    """
    Executes a multi-condition job search with parameterized SQL and optional NLP relevance ranking.
    Supports all 13+ search dimensions, custom salary brackets, experience normalization,
    and server-side pagination.
    """
    def _clean_str(val):
        if not val:
            return ''
        return html.unescape(sanitize_text(str(val))).strip()

    query_raw = _clean_str(data.get('query') or data.get('keyword') or data.get('q'))
    title_raw = _clean_str(data.get('title') or data.get('job_title'))
    company_raw = _clean_str(data.get('company') or data.get('company_name'))
    skill_raw = _clean_str(data.get('skill') or data.get('skills'))
    location_raw = _clean_str(data.get('location'))
    category_raw = _clean_str(data.get('category'))
    experience_raw = _clean_str(data.get('experience') or data.get('experience_level'))
    job_type_raw = _clean_str(data.get('job_type') or data.get('employment_type'))
    work_mode_raw = _clean_str(data.get('work_mode') or data.get('workplace_type'))
    date_posted_raw = _clean_str(data.get('date_posted') or data.get('posted_within')).lower()
    education_raw = _clean_str(data.get('education') or data.get('qualification'))
    industry_raw = _clean_str(data.get('industry'))
    department_raw = _clean_str(data.get('department'))
    sort_raw = _clean_str(data.get('sort') or 'newest').lower()

    # Pagination parsing
    try:
        page = max(1, int(data.get('page', 1) or 1))
    except (TypeError, ValueError):
        page = 1

    try:
        per_page = min(max(1, int(data.get('per_page', 20) or 20)), 100)
    except (TypeError, ValueError):
        per_page = 20

    # Salary parsing & normalization (supports LPA numbers like 4-8 or custom rupees)
    salary_bracket = str(data.get('salary_bracket') or data.get('salary_range') or data.get('salary') or '').strip()
    salary_min = data.get('salary_min')
    salary_max = data.get('salary_max')

    # Parse preset brackets if provided
    if salary_bracket:
        bracket_lower = salary_bracket.lower()
        if '0-3' in bracket_lower or '0 - 3' in bracket_lower:
            salary_min, salary_max = 0, 300000
        elif '3-6' in bracket_lower or '3 - 6' in bracket_lower:
            salary_min, salary_max = 300000, 600000
        elif '6-10' in bracket_lower or '6 - 10' in bracket_lower:
            salary_min, salary_max = 600000, 1000000
        elif '10-15' in bracket_lower or '10 - 15' in bracket_lower:
            salary_min, salary_max = 1000000, 1500000
        elif '15-25' in bracket_lower or '15 - 25' in bracket_lower:
            salary_min, salary_max = 1500000, 2500000
        elif '25+' in bracket_lower or '25-plus' in bracket_lower or '25 +' in bracket_lower:
            salary_min, salary_max = 2500000, None
        elif '-' in salary_bracket:
            parts = [p.strip() for p in salary_bracket.replace('LPA', '').replace('lpa', '').replace('₹', '').replace(',', '').split('-')]
            if len(parts) == 2:
                try:
                    p0 = float(parts[0])
                    p1 = float(parts[1])
                    salary_min = int(p0 * 100000) if (0 < p0 < 1000) else int(p0)
                    salary_max = int(p1 * 100000) if (0 < p1 < 1000) else int(p1)
                except (ValueError, TypeError):
                    pass

    # Normalize explicit salary_min / salary_max
    if salary_min is not None and str(salary_min).strip() != '':
        try:
            s_val = float(str(salary_min).replace('₹', '').replace(',', '').strip())
            salary_min = int(s_val * 100000) if (0 < s_val < 1000) else int(s_val)
        except (TypeError, ValueError):
            salary_min = None
    else:
        salary_min = None

    if salary_max is not None and str(salary_max).strip() != '':
        try:
            s_val = float(str(salary_max).replace('₹', '').replace(',', '').strip())
            salary_max = int(s_val * 100000) if (0 < s_val < 1000) else int(s_val)
        except (TypeError, ValueError):
            salary_max = None
    else:
        salary_max = None

    valid_sorts = ('newest', 'oldest', 'salary_high_to_low', 'salary_low_to_high', 'most_relevant', 'recently_updated')
    sort = sort_raw if sort_raw in valid_sorts else 'newest'

    # Base active jobs filter
    where_clauses = [
        "j.is_active = 1",
        "(j.is_deleted IS NULL OR j.is_deleted = 0)",
        "(j.application_deadline IS NULL OR j.application_deadline >= CURDATE())"
    ]
    params = []

    # 1. Multi-token Keyword search
    if query_raw:
        tokens = [t.strip() for t in query_raw.split() if t.strip()]
        for token in tokens:
            like_tok = f"%{token}%"
            where_clauses.append("""(
                j.title LIKE %s
                OR j.description LIKE %s
                OR j.skills LIKE %s
                OR COALESCE(e.company_name, j.company_name) LIKE %s
                OR j.category LIKE %s
                OR COALESCE(j.industry, e.industry, '') LIKE %s
                OR COALESCE(j.department, '') LIKE %s
                OR COALESCE(j.education, '') LIKE %s
            )""")
            params.extend([like_tok] * 8)

    # 2. Specific Job Title
    if title_raw and title_raw != query_raw:
        where_clauses.append("j.title LIKE %s")
        params.append(f"%{title_raw}%")
    elif title_raw and not query_raw:
        where_clauses.append("j.title LIKE %s")
        params.append(f"%{title_raw}%")

    # 3. Company
    if company_raw:
        where_clauses.append("(COALESCE(e.company_name, j.company_name) LIKE %s OR j.company_name LIKE %s)")
        params.extend([f"%{company_raw}%", f"%{company_raw}%"])

    # 4. Skills
    if skill_raw:
        skill_tokens = [s.strip() for s in re.split(r'[,|]', skill_raw) if s.strip()]
        for st in skill_tokens:
            like_sk = f"%{st}%"
            where_clauses.append("(j.skills LIKE %s OR j.description LIKE %s OR j.title LIKE %s)")
            params.extend([like_sk, like_sk, like_sk])

    # 5. Location
    if location_raw:
        if location_raw.lower() == 'remote':
            where_clauses.append("(LOWER(j.location) LIKE %s OR LOWER(j.work_mode) = 'remote')")
            params.append(f"%{location_raw}%")
        else:
            where_clauses.append("j.location LIKE %s")
            params.append(f"%{location_raw}%")

    # 6. Category
    if category_raw:
        where_clauses.append("(j.category = %s OR j.category LIKE %s)")
        params.extend([category_raw, f"%{category_raw}%"])

    # 7. Experience Level (Fresher, 1-3, 3-5, 5-8, 8+)
    if experience_raw:
        exp_clean = experience_raw.lower()
        if any(w in exp_clean for w in ['fresh', '0 year', '0-1', 'entry']):
            where_clauses.append("(LOWER(j.experience) LIKE '%fresh%' OR LOWER(j.experience) LIKE '%0 year%' OR LOWER(j.experience) LIKE '%0-1%' OR LOWER(j.experience) LIKE '%entry%' OR j.experience = '0' OR j.experience = 'Fresher')")
        elif '1-3' in exp_clean or '1 - 3' in exp_clean or '1 to 3' in exp_clean:
            where_clauses.append("(j.experience LIKE '%1-3%' OR j.experience LIKE '%1 - 3%' OR j.experience LIKE '%1 to 3%' OR j.experience LIKE '%2 year%')")
        elif '3-5' in exp_clean or '3 - 5' in exp_clean or '3 to 5' in exp_clean:
            where_clauses.append("(j.experience LIKE '%3-5%' OR j.experience LIKE '%3 - 5%' OR j.experience LIKE '%3 to 5%' OR j.experience LIKE '%4 year%')")
        elif '5+' in exp_clean or '5-8' in exp_clean or '5 - 8' in exp_clean or '5 to 8' in exp_clean or 'senior' in exp_clean:
            where_clauses.append("(j.experience LIKE '%5-8%' OR j.experience LIKE '%5+%' OR j.experience LIKE '%5 to 8%' OR j.experience LIKE '%6 year%' OR j.experience LIKE '%7 year%' OR j.experience LIKE '%5-10%')")
        elif '8+' in exp_clean or '8-10' in exp_clean or 'lead' in exp_clean or 'principal' in exp_clean:
            where_clauses.append("(j.experience LIKE '%8+%' OR j.experience LIKE '%8-10%' OR j.experience LIKE '%10+%' OR j.experience LIKE '%lead%' OR j.experience LIKE '%principal%')")
        else:
            where_clauses.append("j.experience LIKE %s")
            params.append(f"%{experience_raw}%")

    # 8. Employment Type / Job Type
    if job_type_raw:
        where_clauses.append("j.job_type LIKE %s")
        params.append(f"%{job_type_raw}%")

    # 9. Workplace Type / Work Mode
    if work_mode_raw:
        where_clauses.append("j.work_mode LIKE %s")
        params.append(f"%{work_mode_raw}%")

    # 10. Date Posted (24h, 7d, 30d)
    if date_posted_raw:
        if any(w in date_posted_raw for w in ['24h', '1d', 'today', '24_hours', '1_day']):
            where_clauses.append("j.created_at >= NOW() - INTERVAL 1 DAY")
        elif any(w in date_posted_raw for w in ['7d', '1w', 'week', '7_days', '1_week']):
            where_clauses.append("j.created_at >= NOW() - INTERVAL 7 DAY")
        elif any(w in date_posted_raw for w in ['30d', '1m', 'month', '30_days', '1_month']):
            where_clauses.append("j.created_at >= NOW() - INTERVAL 30 DAY")

    # 11. Education
    if education_raw:
        where_clauses.append("(COALESCE(j.education, '') LIKE %s OR j.description LIKE %s)")
        params.extend([f"%{education_raw}%", f"%{education_raw}%"])

    # 12. Industry
    if industry_raw:
        where_clauses.append("(COALESCE(j.industry, '') LIKE %s OR COALESCE(e.industry, '') LIKE %s OR j.category LIKE %s)")
        params.extend([f"%{industry_raw}%", f"%{industry_raw}%", f"%{industry_raw}%"])

    # 13. Department
    if department_raw:
        where_clauses.append("(COALESCE(j.department, '') LIKE %s OR j.title LIKE %s OR j.description LIKE %s)")
        params.extend([f"%{department_raw}%", f"%{department_raw}%", f"%{department_raw}%"])

    # 14. Salary Range Filters
    if salary_min is not None and salary_min > 0:
        where_clauses.append("((j.salary_max >= %s OR j.salary_min >= %s) OR (j.salary LIKE %s))")
        params.extend([salary_min, salary_min, f"%{salary_min // 100000}%" if salary_min >= 100000 else f"%{salary_min}%"])

    if salary_max is not None and salary_max > 0:
        where_clauses.append("((j.salary_min <= %s OR (j.salary_min = 0 AND j.salary_max <= %s)) OR (j.salary LIKE %s))")
        params.extend([salary_max, salary_max, f"%{salary_max // 100000}%" if salary_max >= 100000 else f"%{salary_max}%"])

    where_sql = " AND ".join(where_clauses)

    # Determine ORDER BY clause
    if sort == 'salary_high_to_low':
        order_sql = "ORDER BY j.salary_max DESC, j.salary_min DESC, j.id DESC"
    elif sort == 'salary_low_to_high':
        order_sql = "ORDER BY (CASE WHEN j.salary_min > 0 THEN j.salary_min WHEN j.salary_max > 0 THEN j.salary_max ELSE 999999999 END) ASC, j.id ASC"
    elif sort == 'oldest':
        order_sql = "ORDER BY j.created_at ASC, j.id ASC"
    elif sort == 'recently_updated':
        order_sql = "ORDER BY j.created_at DESC, j.id DESC"
    elif sort == 'newest':
        order_sql = "ORDER BY j.created_at DESC, j.id DESC"
    else:  # most_relevant
        order_sql = "ORDER BY j.created_at DESC, j.id DESC"

    with db_cursor() as cursor:
        count_query = f"""
            SELECT COUNT(*) AS total
            FROM jobs j
            LEFT JOIN employee e ON j.employer_id = e.id
            WHERE {where_sql}
        """
        cursor.execute(count_query, params)
        total = cursor.fetchone()['total']

        offset = (page - 1) * per_page
        query = f"""
            SELECT j.*, COALESCE(e.company_name, j.company_name) AS company_name,
                   e.is_verified AS employer_is_verified, e.verification_status AS employer_verification_status
            FROM jobs j
            LEFT JOIN employee e ON j.employer_id = e.id
            WHERE {where_sql} {order_sql}
            LIMIT %s OFFSET %s
        """
        cursor.execute(query, params + [per_page, offset])
        jobs = cursor.fetchall()

    # Apply NLP relevance ranking ONLY when sort == 'most_relevant' and a query/title/category exists
    ranking_term = f"{query_raw} {title_raw} {category_raw}".strip()
    if sort == 'most_relevant' and ranking_term:
        jobs = get_nlp_search_results(jobs, ranking_term)
    elif query_raw or title_raw:
        search_kw = (query_raw or title_raw).lower().split()
        for j in jobs:
            kw_matches = sum(1 for kw in search_kw if kw in f"{j.get('title','')} {j.get('skills','')} {j.get('company_name','')}".lower())
            j['match_count'] = kw_matches

    enriched_jobs = []
    for j in jobs:
        enrich_job_presentation(j)
        if j.get('created_at') and hasattr(j['created_at'], 'strftime'):
            j['created_at_formatted'] = j['created_at'].strftime('%Y-%m-%d %H:%M:%S')
            j['created_at'] = j['created_at'].strftime('%Y-%m-%d')
        enriched_jobs.append(j)

    total_pages = max(1, (total + per_page - 1) // per_page) if total > 0 else 1

    applied_filters = {
        'query': query_raw,
        'title': title_raw,
        'company': company_raw,
        'skill': skill_raw,
        'location': location_raw,
        'category': category_raw,
        'experience': experience_raw,
        'job_type': job_type_raw,
        'work_mode': work_mode_raw,
        'date_posted': date_posted_raw,
        'education': education_raw,
        'industry': industry_raw,
        'department': department_raw,
        'salary_bracket': salary_bracket,
        'salary_min': salary_min,
        'salary_max': salary_max,
        'sort': sort
    }

    return {
        'success': True,
        'jobs': enriched_jobs,
        'total': total,
        'total_pages': total_pages,
        'page': page,
        'per_page': per_page,
        'sort': sort,
        'filters_applied': applied_filters
    }


@app.route('/api/jobs/search', methods=['GET', 'POST'])
@app.route('/api/search_jobs', methods=['GET', 'POST'])
@limiter.limit("120 per minute")
def api_jobs_search():
    if request.method == 'POST' and request.is_json:
        data = request.get_json(silent=True) or {}
        if request.args:
            for k, v in request.args.items():
                if k not in data:
                    data[k] = v
    else:
        data = request.args.to_dict()
        if request.is_json:
            json_body = request.get_json(silent=True) or {}
            data.update(json_body)

    # Validate integer inputs when explicitly provided
    if 'page' in data and data['page'] is not None and str(data['page']).strip() != '':
        try:
            int(data['page'])
        except (TypeError, ValueError):
            return jsonify({'success': False, 'message': 'page and per_page must be integers'}), 400
    if 'per_page' in data and data['per_page'] is not None and str(data['per_page']).strip() != '':
        try:
            int(data['per_page'])
        except (TypeError, ValueError):
            return jsonify({'success': False, 'message': 'page and per_page must be integers'}), 400

    result = execute_jobs_query(data)
    return jsonify(result)


@app.route('/api/jobs/suggestions', methods=['GET', 'POST'])
@app.route('/api/search/suggestions', methods=['GET', 'POST'])
@limiter.limit("120 per minute")
def api_jobs_suggestions():
    q = ''
    if request.method == 'POST' and request.is_json:
        req_json = request.get_json(silent=True) or {}
        q = req_json.get('q') or req_json.get('query') or ''
    if not q and request.args:
        q = request.args.get('q') or request.args.get('query') or ''
    q = html.unescape(sanitize_text(q)).strip()

    if not q or len(q) < 1:
        return jsonify({
            'success': True,
            'query': q,
            'suggestions': [],
            'titles': [],
            'skills': [],
            'companies': [],
            'locations': []
        })

    like_term = f"%{q}%"
    titles = []
    companies = []
    locations = []

    popular_skills = [
        "Python", "Java", "JavaScript", "TypeScript", "React", "Node.js", "Angular", "Vue.js",
        "SQL", "MySQL", "PostgreSQL", "MongoDB", "AWS", "Azure", "GCP", "Docker", "Kubernetes",
        "Machine Learning", "Data Analysis", "Data Science", "Artificial Intelligence", "NLP",
        "Django", "Flask", "Spring Boot", "HTML/CSS", "Git", "DevOps", "CI/CD", "REST API",
        "GraphQL", "Power BI", "Tableau", "Excel", "Pandas", "NumPy", "TensorFlow", "PyTorch",
        "Tailwind CSS", "Bootstrap", "C++", "C#", ".NET", "PHP", "Go", "Rust", "Swift", "Kotlin"
    ]
    matching_skills = [s for s in popular_skills if q.lower() in s.lower()][:6]

    with db_cursor() as cursor:
        cursor.execute("""
            SELECT DISTINCT title
            FROM jobs
            WHERE is_active = 1 AND (is_deleted IS NULL OR is_deleted = 0)
              AND (application_deadline IS NULL OR application_deadline >= CURDATE())
              AND title LIKE %s
            ORDER BY title ASC
            LIMIT 5
        """, (like_term,))
        titles = [row['title'] for row in cursor.fetchall() if row.get('title')]

        cursor.execute("""
            SELECT DISTINCT COALESCE(e.company_name, j.company_name) AS company_name
            FROM jobs j
            LEFT JOIN employee e ON j.employer_id = e.id
            WHERE j.is_active = 1 AND (j.is_deleted IS NULL OR j.is_deleted = 0)
              AND (j.application_deadline IS NULL OR j.application_deadline >= CURDATE())
              AND COALESCE(e.company_name, j.company_name) LIKE %s
            ORDER BY company_name ASC
            LIMIT 5
        """, (like_term,))
        companies = [row['company_name'] for row in cursor.fetchall() if row.get('company_name')]

        cursor.execute("""
            SELECT DISTINCT location
            FROM jobs
            WHERE is_active = 1 AND (is_deleted IS NULL OR is_deleted = 0)
              AND (application_deadline IS NULL OR application_deadline >= CURDATE())
              AND location LIKE %s
            ORDER BY location ASC
            LIMIT 5
        """, (like_term,))
        locations = [row['location'] for row in cursor.fetchall() if row.get('location')]

    suggestions = []
    for t in titles[:3]:
        suggestions.append({'text': t, 'type': 'title', 'category': 'Job Title', 'icon': 'fas fa-briefcase'})
    for s in matching_skills[:3]:
        suggestions.append({'text': s, 'type': 'skill', 'category': 'Skill', 'icon': 'fas fa-code'})
    for c in companies[:3]:
        suggestions.append({'text': c, 'type': 'company', 'category': 'Company', 'icon': 'fas fa-building'})
    for l in locations[:3]:
        suggestions.append({'text': l, 'type': 'location', 'category': 'Location', 'icon': 'fas fa-map-marker-alt'})

    return jsonify({
        'success': True,
        'query': q,
        'suggestions': suggestions,
        'titles': titles,
        'skills': matching_skills,
        'companies': companies,
        'locations': locations
    })


# --- AI / ML JOB RECOMMENDATIONS API ---
@app.route('/api/jobs/recommended', methods=['GET'])
@app.route('/api/user/recommendations', methods=['GET'])
@limiter.limit("120 per minute")
def api_jobs_recommended():
    """
    Returns AI/ML personalized job recommendations for the authenticated candidate.
    Uses multi-factor scoring (skills 35%, semantics 25%, role 12%, experience 10%,
    location/remote 8%, salary 5%, employment type 3%, education 2%) with transparent explanations.
    """
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Authentication required for job recommendations.'}), 401

    uid = session['user_id']
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 20, type=int), 100)
    category = request.args.get('category', '').strip()
    work_mode = request.args.get('work_mode', '').strip()
    location = request.args.get('location', '').strip()
    min_score = request.args.get('min_score', 40.0, type=float)

    filters = {
        'category': category,
        'work_mode': work_mode,
        'location': location,
        'min_score': min_score
    }
    offset = max(0, (page - 1) * per_page)

    res = recommend_jobs_for_candidate(
        user_id=uid,
        db_cursor_factory=db_cursor,
        model_getter=_get_sentence_model,
        filters=filters,
        limit=per_page,
        offset=offset
    )

    # Format dates and enrich job presentation for UI
    for j in res['recommendations']:
        enrich_job_presentation(j)
        if j.get('created_at') and hasattr(j['created_at'], 'strftime'):
            j['created_at_formatted'] = j['created_at'].strftime('%Y-%m-%d %H:%M:%S')
            j['created_at'] = j['created_at'].strftime('%Y-%m-%d')

    return jsonify({
        'success': True,
        'recommendations': res['recommendations'],
        'jobs': res['recommendations'],  # alias for dashboard compatibility
        'total': res['total'],
        'page': res['page'],
        'per_page': res['per_page'],
        'total_pages': res['total_pages'],
        'meta': res['meta']
    })


@app.route('/api/jobs/<int:job_id>/recommendation_details', methods=['GET'])
@app.route('/api/jobs/<int:job_id>/match', methods=['GET'])
@limiter.limit("120 per minute")
def api_job_recommendation_details(job_id):
    """
    Returns granular AI match scoring breakdown and transparent explanation
    for a specific job against the authenticated candidate.
    """
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Authentication required.'}), 401

    uid = session['user_id']
    with db_cursor() as cur:
        cur.execute("""
            SELECT j.*, COALESCE(e.company_name, j.company_name) AS company_name,
                   e.is_verified AS employer_is_verified
            FROM jobs j
            LEFT JOIN employee e ON j.employer_id = e.id
            WHERE j.id = %s AND j.is_active = 1
              AND (j.is_deleted IS NULL OR j.is_deleted = 0)
        """, (job_id,))
        job = cur.fetchone()
        if not job:
            return jsonify({'success': False, 'message': 'Job opening not found or inactive.'}), 404

        cand_profile = get_candidate_recommendation_profile(uid, cur)

    scoring = calculate_job_recommendation_score(job, cand_profile, _get_sentence_model)
    return jsonify({
        'success': True,
        'job_id': job_id,
        'job_title': job.get('title'),
        'company_name': job.get('company_name'),
        'match_score': scoring['final_score'],
        'match_reason': scoring['match_reason'],
        'matched_skills': scoring['matched_skills'],
        'missing_skills': scoring['missing_skills'],
        'skill_score': scoring['skill_score'],
        'semantic_score': scoring['semantic_score'],
        'breakdown': scoring['breakdown']
    })


# --- USER DASHBOARD STATS ---
@app.route('/api/user/stats')
def api_user_stats():
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    uid = session['user_id']
    with db_cursor() as cursor:
        cursor.execute("SELECT COUNT(*) AS cnt FROM applications WHERE user_id = %s", (uid,))
        total_apps = cursor.fetchone()['cnt']
        cursor.execute("SELECT COUNT(*) AS cnt FROM applications WHERE user_id = %s AND LOWER(status) LIKE %s", (uid, '%shortlist%'))
        total_shortlisted = cursor.fetchone()['cnt']
        cursor.execute("SELECT COUNT(*) AS cnt FROM saved_jobs WHERE user_id = %s", (uid,))
        total_saved = cursor.fetchone()['cnt']
        cursor.execute("SELECT COUNT(*) AS cnt FROM interviews WHERE candidate_id = %s AND status != 'Cancelled'", (uid,))
        total_interviews = cursor.fetchone()['cnt']

    completeness_data = evaluate_candidate_profile_completeness(uid)

    return jsonify({
        'success': True,
        'total_applications': total_apps,
        'total_shortlisted': total_shortlisted,
        'total_saved': total_saved,
        'total_interviews': total_interviews,
        'profile_completeness': completeness_data['score'],
        'completeness_data': completeness_data
    })

@app.route('/api/user/profile_completeness')
def api_user_profile_completeness():
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    completeness_data = evaluate_candidate_profile_completeness(session['user_id'])
    return jsonify({
        'success': True,
        'completeness': completeness_data['score'],
        'score': completeness_data['score'],
        'candidate_type': completeness_data['candidate_type'],
        'completed_count': completeness_data['completed_count'],
        'total_items': completeness_data['total_items'],
        'completed_items': completeness_data['completed_items'],
        'missing_items': completeness_data['missing_items'],
        'breakdown': completeness_data['breakdown'],
        'data': completeness_data
    })


def record_profile_view(candidate_id, employer_id):
    """
    Records an employer viewing a candidate's profile.
    Prevents duplicate views within 24 hours by the same employer from inflating counts.
    """
    if not candidate_id or not employer_id:
        return False
    try:
        candidate_id = int(candidate_id)
        employer_id = int(employer_id)
    except (ValueError, TypeError):
        return False

    try:
        with db_cursor() as cursor:
            # Check for recent view in the past 24 hours to deduplicate
            cursor.execute("""
                SELECT id FROM profile_views
                WHERE candidate_id = %s AND employer_id = %s AND viewed_at >= NOW() - INTERVAL 1 DAY
                LIMIT 1
            """, (candidate_id, employer_id))
            if cursor.fetchone():
                return True

            # Get employer's company name
            cursor.execute("SELECT company_name FROM employee WHERE id = %s", (employer_id,))
            emp = cursor.fetchone()
            company_name = (emp.get('company_name') if emp else '') or 'Verified Employer'

            cursor.execute("""
                INSERT INTO profile_views (candidate_id, employer_id, company_name, viewed_at)
                VALUES (%s, %s, %s, NOW())
            """, (candidate_id, employer_id, company_name))
        return True
    except Exception as e:
        logger.error(f"Error recording profile view for candidate {candidate_id} by employer {employer_id}: {e}")
        return False


@app.route('/api/user/profile_views', methods=['GET'])
def api_user_profile_views():
    """
    Returns real tracked profile view analytics and interview invite conversion for the logged-in candidate.
    """
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401

    candidate_id = session['user_id']
    with db_cursor() as cursor:
        cursor.execute("""
            SELECT COUNT(DISTINCT employer_id) AS distinct_cnt, COUNT(*) AS total_cnt
            FROM profile_views
            WHERE candidate_id = %s
        """, (candidate_id,))
        cnt_row = cursor.fetchone()
        distinct_views = cnt_row['distinct_cnt'] if cnt_row else 0
        total_views = cnt_row['total_cnt'] if cnt_row else 0

        cursor.execute("""
            SELECT company_name, viewed_at
            FROM profile_views
            WHERE candidate_id = %s
            ORDER BY viewed_at DESC
            LIMIT 50
        """, (candidate_id,))
        raw_views = cursor.fetchall()

        # Interview invite rate from candidate's real applications
        cursor.execute("SELECT COUNT(*) AS total_apps FROM applications WHERE user_id = %s", (candidate_id,))
        total_apps_row = cursor.fetchone()
        total_apps = total_apps_row['total_apps'] if total_apps_row else 0

        cursor.execute("""
            SELECT COUNT(*) AS invite_cnt
            FROM applications
            WHERE user_id = %s AND status IN ('Interview', 'Selected')
        """, (candidate_id,))
        invite_row = cursor.fetchone()
        invite_cnt = invite_row['invite_cnt'] if invite_row else 0

    views_list = []
    for v in raw_views:
        v_at = v.get('viewed_at')
        v_at_str = v_at.strftime('%b %d, %Y %I:%M %p') if v_at else 'Recently'
        views_list.append({
            'company_name': v.get('company_name') or 'Verified Employer',
            'viewed_at': v_at_str
        })

    has_enough_apps = total_apps >= 3
    if has_enough_apps:
        invite_rate = round((invite_cnt / total_apps) * 100.0, 1)
        invite_rate_display = f"{invite_rate:g}%"
    else:
        invite_rate = None
        invite_rate_display = "Not enough data yet"

    view_display = f"{distinct_views} Compan{'ies' if distinct_views != 1 else 'y'}" if distinct_views > 0 else "No views yet"

    return jsonify({
        'success': True,
        'distinct_views': distinct_views,
        'total_views': total_views,
        'view_count_display': view_display,
        'has_views': distinct_views > 0,
        'views': views_list,
        'interview_invite_rate': invite_rate,
        'interview_invite_rate_display': invite_rate_display,
        'total_applications': total_apps,
        'interview_count': invite_cnt,
        'has_enough_application_data': has_enough_apps
    })


# --- APPLY LOGIC ---
@app.route('/api/user/applied_jobs')
def get_applied_jobs():
    if 'user_id' not in session: return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    uid = session['user_id']
    with db_cursor() as cursor:
        cursor.execute("""
            SELECT 
                a.id AS application_id,
                a.job_id,
                a.status,
                a.created_at AS applied_at,
                a.cover_letter,
                a.answers,
                a.additional_document_path,
                a.resume_path,
                a.match_score,
                j.title,
                COALESCE(e.company_name, j.company_name) AS company_name,
                j.location,
                j.job_type,
                j.salary,
                j.is_active,
                j.application_deadline
            FROM applications a
            LEFT JOIN jobs j ON a.job_id = j.id
            LEFT JOIN employee e ON j.employer_id = e.id
            WHERE a.user_id = %s
            ORDER BY a.created_at DESC, a.id DESC
        """, (uid,))
        apps = cursor.fetchall()

    applied_ids = []
    formatted_apps = []
    for a in apps:
        applied_ids.append(str(a['job_id']))
        applied_dt = a.get('applied_at')
        if applied_dt and hasattr(applied_dt, 'strftime'):
            formatted_date = applied_dt.strftime('%d %b %Y')
        else:
            formatted_date = str(applied_dt or 'Recently')

        parsed_answers = None
        if a.get('answers'):
            try:
                parsed_answers = json.loads(a['answers']) if isinstance(a['answers'], str) else a['answers']
            except Exception:
                parsed_answers = {'raw': a['answers']}

        status_str = a.get('status') or 'Applied'
        # Standard status stages
        status_stages = ['Applied', 'Screening', 'Shortlisted', 'Assessment', 'Interview', 'Offer', 'Hired']
        current_step = 1
        if status_str in status_stages:
            current_step = status_stages.index(status_str) + 1
        elif status_str in ('Selected',):
            current_step = 6
        elif status_str in ('Rejected', 'Withdrawn'):
            current_step = -1

        formatted_apps.append({
            'application_id': a['application_id'],
            'id': a['application_id'],
            'job_id': a['job_id'],
            'title': a.get('title') or 'Job Opportunity',
            'company_name': a.get('company_name') or 'Verified Employer',
            'location': a.get('location') or 'Remote',
            'job_type': a.get('job_type') or 'Full-time',
            'salary': a.get('salary') or 'Competitive',
            'status': status_str,
            'current_step': current_step,
            'match_score': f"{a['match_score']}%" if a.get('match_score') is not None else "Not scored",
            'cover_letter': a.get('cover_letter') or '',
            'has_cover_letter': bool(a.get('cover_letter')),
            'answers': parsed_answers,
            'has_answers': bool(parsed_answers),
            'resume_path': a.get('resume_path') or '',
            'has_additional_doc': bool(a.get('additional_document_path')),
            'additional_document_path': a.get('additional_document_path') or '',
            'applied_at': formatted_date,
            'is_active': bool(a.get('is_active', True)),
            'deadline': str(a.get('application_deadline') or '')
        })

    return jsonify({
        'success': True,
        'applications': formatted_apps,
        'applied_ids': applied_ids,
        'total': len(formatted_apps)
    })

@app.route('/api/user/applications/<int:app_id>')
def api_user_application_detail(app_id):
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    uid = session['user_id']
    with db_cursor() as cursor:
        cursor.execute("""
            SELECT a.*, j.title, COALESCE(e.company_name, j.company_name) AS company_name,
                   j.location, j.job_type, j.salary, j.is_active, j.application_deadline,
                   j.description AS job_description
            FROM applications a
            LEFT JOIN jobs j ON a.job_id = j.id
            LEFT JOIN employee e ON j.employer_id = e.id
            WHERE a.id = %s AND a.user_id = %s
        """, (app_id, uid))
        app_row = cursor.fetchone()
    if not app_row:
        return jsonify({'success': False, 'message': 'Application not found or unauthorized'}), 404

    if app_row.get('created_at') and hasattr(app_row['created_at'], 'strftime'):
        app_row['applied_at'] = app_row['created_at'].strftime('%d %b %Y')
        app_row['created_at'] = app_row['created_at'].strftime('%Y-%m-%d %H:%M:%S')

    parsed_answers = None
    if app_row.get('answers'):
        try:
            parsed_answers = json.loads(app_row['answers']) if isinstance(app_row['answers'], str) else app_row['answers']
        except Exception:
            parsed_answers = {'notes': app_row['answers']}
    app_row['parsed_answers'] = parsed_answers

    return jsonify({'success': True, 'application': app_row})

@app.route('/api/user/resumes')
def api_user_resumes():
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    uid = session['user_id']
    resumes = []
    with db_cursor() as cursor:
        # 1. Profile primary resume
        cursor.execute("SELECT general_resume_path FROM candidate_profile WHERE user_id = %s", (uid,))
        cp_row = cursor.fetchone()
        if cp_row and cp_row.get('general_resume_path'):
            p = cp_row['general_resume_path']
            resumes.append({
                'id': 'primary',
                'filename': os.path.basename(p),
                'file_path': p,
                'is_primary': True,
                'ats_score': None,
                'label': f"Primary Profile Resume ({os.path.basename(p)})",
                'created_at': 'Profile'
            })
        # 2. Uploaded resume analyses
        cursor.execute("""
            SELECT id, filename, original_filename, file_path, ats_score, created_at
            FROM resume_analyses
            WHERE user_id = %s
            ORDER BY id DESC
        """, (uid,))
        for r in cursor.fetchall():
            created_str = r['created_at'].strftime('%Y-%m-%d %H:%M') if hasattr(r.get('created_at'), 'strftime') else str(r.get('created_at') or '')
            fname = r.get('original_filename') or r.get('filename') or 'Resume'
            resumes.append({
                'id': r['id'],
                'filename': fname,
                'file_path': r['file_path'],
                'is_primary': False,
                'ats_score': r.get('ats_score'),
                'label': f"{fname} (ATS Score: {r.get('ats_score') or 'N/A'})",
                'created_at': created_str
            })
    return jsonify({'success': True, 'resumes': resumes, 'total': len(resumes)})

@app.route('/api/jobs/<int:job_id>/apply_info')
def api_job_apply_info(job_id):
    with db_cursor() as cursor:
        cursor.execute("""
            SELECT j.*, COALESCE(e.company_name, j.company_name) AS company_name
            FROM jobs j
            LEFT JOIN employee e ON j.employer_id = e.id
            WHERE j.id = %s
        """, (job_id,))
        job = cursor.fetchone()
    if not job:
        return jsonify({'success': False, 'message': 'Job not found'}), 404

    already_applied = False
    app_status = None
    user_resumes = []
    user_profile = {}

    if 'user_id' in session:
        uid = session['user_id']
        with db_cursor() as cursor:
            cursor.execute("SELECT id, status FROM applications WHERE job_id = %s AND user_id = %s", (job_id, uid))
            app_row = cursor.fetchone()
            if app_row:
                already_applied = True
                app_status = app_row.get('status')

            cursor.execute("SELECT name, email, mobile, location, skills, experience FROM user WHERE id = %s", (uid,))
            user_profile = cursor.fetchone() or {}

            cursor.execute("SELECT general_resume_path FROM candidate_profile WHERE user_id = %s", (uid,))
            cp = cursor.fetchone()
            if cp and cp.get('general_resume_path'):
                user_resumes.append({
                    'id': 'primary',
                    'filename': os.path.basename(cp['general_resume_path']),
                    'file_path': cp['general_resume_path'],
                    'is_primary': True,
                    'label': f"Profile Resume ({os.path.basename(cp['general_resume_path'])})"
                })
            cursor.execute("""
                SELECT id, original_filename, filename, file_path, ats_score
                FROM resume_analyses
                WHERE user_id = %s
                ORDER BY id DESC
            """, (uid,))
            for ra in cursor.fetchall():
                fname = ra.get('original_filename') or ra.get('filename') or 'Resume'
                user_resumes.append({
                    'id': ra['id'],
                    'filename': fname,
                    'file_path': ra['file_path'],
                    'ats_score': ra.get('ats_score'),
                    'is_primary': False,
                    'label': f"{fname} (Score: {ra.get('ats_score') or 'N/A'})"
                })

    deadline_str = None
    is_expired = False
    if job.get('application_deadline'):
        try:
            dl = datetime.strptime(str(job['application_deadline']), '%Y-%m-%d').date() if isinstance(job['application_deadline'], str) else job['application_deadline']
            deadline_str = dl.strftime('%Y-%m-%d')
            is_expired = datetime.now().date() > dl
        except Exception:
            deadline_str = str(job.get('application_deadline'))

    questions = []
    if job.get('application_questions'):
        try:
            questions = json.loads(job['application_questions']) if isinstance(job['application_questions'], str) else job['application_questions']
        except Exception:
            questions = []

    return jsonify({
        'success': True,
        'job': {
            'id': job['id'],
            'title': job['title'],
            'company_name': job.get('company_name') or 'Verified Employer',
            'location': job.get('location') or 'Remote',
            'salary': job.get('salary') or 'Competitive',
            'job_type': job.get('job_type') or 'Full-time',
            'work_mode': job.get('work_mode') or 'Onsite',
            'experience': job.get('experience') or 'All Levels',
            'deadline': deadline_str,
            'is_expired': is_expired,
            'is_active': bool(job.get('is_active', True)),
            'is_available': bool(job.get('is_active', True)) and not is_expired and not bool(job.get('is_deleted', False)) and job.get('status') != 'Closed',
            'questions': questions
        },
        'already_applied': already_applied,
        'application_status': app_status,
        'user_profile': user_profile,
        'user_resumes': user_resumes
    })

@app.route('/api/user/saved_jobs')
def get_saved_jobs():
    if 'user_id' not in session: return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    uid = session['user_id']
    with db_cursor() as cursor:
        cursor.execute("""
            SELECT 
                s.id AS saved_id,
                s.job_id,
                s.created_at AS saved_at,
                j.title,
                COALESCE(e.company_name, j.company_name) AS company_name,
                j.location,
                j.job_type,
                j.salary,
                j.is_active,
                j.application_deadline
            FROM saved_jobs s
            LEFT JOIN jobs j ON s.job_id = j.id
            LEFT JOIN employee e ON j.employer_id = e.id
            WHERE s.user_id = %s
            ORDER BY s.created_at DESC, s.id DESC
        """, (uid,))
        saved = cursor.fetchall()

    formatted_saved = []
    now_date = datetime.now().date()
    for s in saved:
        saved_dt = s.get('saved_at')
        if saved_dt and hasattr(saved_dt, 'strftime'):
            formatted_date = saved_dt.strftime('%d %b %Y')
        else:
            formatted_date = str(saved_dt or 'Recently')

        is_active = bool(s.get('is_active', True))
        deadline_str = str(s.get('application_deadline') or '')
        if deadline_str and is_active:
            try:
                dl = datetime.strptime(deadline_str, '%Y-%m-%d').date()
                if now_date > dl:
                    is_active = False
            except Exception:
                pass

        formatted_saved.append({
            'saved_id': s['saved_id'],
            'job_id': s['job_id'],
            'title': s.get('title') or 'Saved Position',
            'company_name': s.get('company_name') or 'Verified Employer',
            'location': s.get('location') or 'Remote',
            'job_type': s.get('job_type') or 'Full-time',
            'salary': s.get('salary') or 'Competitive',
            'saved_at': formatted_date,
            'is_active': is_active,
            'is_available': is_active and bool(s.get('title')),
            'deadline': deadline_str
        })

    return jsonify({
        'success': True,
        'saved_jobs': formatted_saved,
        'total': len(formatted_saved)
    })

@app.route('/api/apply_job', methods=['POST'])
@limiter.limit("30 per minute")
def api_apply_job():
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Please Login to Apply'}), 401

    if 'employer_id' in session and 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Employers cannot submit candidate applications'}), 403

    uid = session['user_id']

    if request.is_json:
        data = request.get_json(silent=True) or {}
    else:
        data = request.form.to_dict() if request.form else {}

    job_id = data.get('job_id') or data.get('id') or data.get('jobId')
    if not job_id:
        return jsonify({'success': False, 'message': 'Job ID is required'}), 400

    try:
        job_id = int(job_id)
    except (ValueError, TypeError):
        return jsonify({'success': False, 'message': 'Invalid Job ID format'}), 400

    # 1. Check job deadline, company name, title, employer_id, and active status
    with db_cursor() as cursor:
        cursor.execute("""
            SELECT j.id, j.employer_id, j.title, j.description, j.skills,
                   COALESCE(e.company_name, j.company_name) AS company_name,
                   j.application_deadline, j.is_active, j.status, j.is_deleted
            FROM jobs j
            LEFT JOIN employee e ON j.employer_id = e.id
            WHERE j.id = %s
        """, (job_id,))
        job_row = cursor.fetchone()
    if not job_row or bool(job_row.get('is_deleted', False)):
        return jsonify({'success': False, 'message': 'Job not found'}), 404
    if not job_row['is_active'] or job_row.get('status') == 'Closed':
        return jsonify({'success': False, 'message': 'This job posting is no longer active'}), 400
    if job_row.get('application_deadline'):
        try:
            deadline = datetime.strptime(str(job_row['application_deadline']), '%Y-%m-%d').date() if isinstance(job_row['application_deadline'], str) else job_row['application_deadline']
            if datetime.now().date() > deadline:
                return jsonify({'success': False, 'message': 'The application deadline has passed'}), 400
        except (ValueError, TypeError):
            pass

    # 2. Check for duplicate application pre-insert
    with db_cursor() as cursor:
        cursor.execute("SELECT id FROM applications WHERE job_id = %s AND user_id = %s", (job_id, uid))
        if cursor.fetchone():
            return jsonify({'success': False, 'message': 'You have already applied for this job.'}), 400

    # 3. RESUME RESOLUTION (Uploaded file vs Selected saved resume vs Profile general_resume_path)
    resume_filename = None
    file = request.files.get('resume') if request.files else None
    if file and file.filename:
        if not allowed_file(file.filename):
            return jsonify({'success': False, 'message': 'Invalid resume type. Allowed: txt, pdf, docx.'}), 400
        file.seek(0, os.SEEK_END)
        if file.tell() > MAX_UPLOAD_BYTES:
            return jsonify({'success': False, 'message': f'Resume too large (max {MAX_UPLOAD_MB}MB).'}), 400
        file.seek(0)
        if not validate_file_signature(file, file.filename):
            return jsonify({'success': False, 'message': 'File content does not match its extension. Possible corruption.'}), 400
        file.seek(0)
        filename = secure_filename(file.filename)
        resume_filename = f"{uuid.uuid4().hex}_{int(time.time())}_{filename}"
        upload_path = os.path.join(app.config['UPLOAD_FOLDER'], resume_filename)
        file.save(upload_path)
    else:
        # Check if a selected resume path or ID was provided
        selected_resume = data.get('resume_path') or data.get('selected_resume') or data.get('resume_id')
        if selected_resume and selected_resume != 'primary':
            # Check if it's an ID from resume_analyses
            try:
                r_id = int(selected_resume)
                with db_cursor() as cursor:
                    cursor.execute("SELECT file_path FROM resume_analyses WHERE id = %s AND user_id = %s", (r_id, uid))
                    ra_row = cursor.fetchone()
                    if ra_row and ra_row.get('file_path'):
                        resume_filename = ra_row['file_path']
            except (ValueError, TypeError):
                # Raw path passed
                resume_filename = sanitize_text(str(selected_resume))
        
        if not resume_filename:
            # Fallback to candidate profile general_resume_path
            with db_cursor() as cursor:
                cursor.execute("SELECT general_resume_path FROM candidate_profile WHERE user_id = %s", (uid,))
                cp_row = cursor.fetchone()
                if cp_row and cp_row.get('general_resume_path'):
                    resume_filename = cp_row['general_resume_path']
                else:
                    cursor.execute("SELECT resume_path FROM applications WHERE user_id = %s AND resume_path IS NOT NULL ORDER BY id DESC LIMIT 1", (uid,))
                    last_app = cursor.fetchone()
                    if last_app and last_app.get('resume_path'):
                        resume_filename = last_app['resume_path']

    # 4. ADDITIONAL DOCUMENT UPLOAD (optional: certificate, portfolio PDF, etc.)
    doc_file = (request.files.get('additional_document') or request.files.get('document') or request.files.get('portfolio')) if request.files else None
    additional_doc_filename = None
    if doc_file and doc_file.filename:
        allowed_doc_exts = {'pdf', 'docx', 'doc', 'txt', 'png', 'jpg', 'jpeg'}
        ext = doc_file.filename.rsplit('.', 1)[-1].lower() if '.' in doc_file.filename else ''
        if ext not in allowed_doc_exts:
            return jsonify({'success': False, 'message': 'Invalid document type. Allowed: pdf, docx, txt, png, jpg.'}), 400
        doc_file.seek(0, os.SEEK_END)
        if doc_file.tell() > MAX_UPLOAD_BYTES:
            return jsonify({'success': False, 'message': f'Document too large (max {MAX_UPLOAD_MB}MB).'}), 400
        doc_file.seek(0)
        doc_filename_safe = secure_filename(doc_file.filename)
        additional_doc_filename = f"doc_{uuid.uuid4().hex[:8]}_{int(time.time())}_{doc_filename_safe}"
        doc_upload_path = os.path.join(app.config['UPLOAD_FOLDER'], additional_doc_filename)
        doc_file.save(doc_upload_path)

    # 5. SCREENING QUESTIONS & ANSWERS
    answers_dict = {}
    raw_answers = data.get('answers') or data.get('additional_questions')
    if raw_answers:
        if isinstance(raw_answers, str):
            try:
                answers_dict = json.loads(raw_answers)
            except Exception:
                answers_dict = {'screening_answer': sanitize_html(raw_answers)}
        elif isinstance(raw_answers, dict):
            answers_dict = {k: sanitize_html(str(v)) for k, v in raw_answers.items()}

    # Individual standard screening fields
    for field in ['notice_period', 'expected_salary', 'current_ctc', 'willing_to_relocate', 'total_experience', 'portfolio_url']:
        if data.get(field):
            answers_dict[field] = sanitize_html(str(data[field]))

    answers_json = json.dumps(answers_dict) if answers_dict else None

    # Cover letter
    cover_letter_text = sanitize_html(data.get('cover_letter') or data.get('cover') or data.get('coverLetter') or '')

    # Fetch candidate defaults if not supplied
    cand_name = data.get('name') or session.get('user_name', 'Applicant')
    cand_email = data.get('email') or session.get('user_email', '')
    cand_mobile = data.get('mobile') or ''
    cand_location = data.get('curr_loc') or data.get('location') or ''
    cand_qualification = data.get('qualification') or ''
    cand_experience_level = data.get('exp_level') or data.get('experience') or ''
    cand_skills = data.get('skills') or ''

    if not cand_mobile or not cand_location:
        with db_cursor() as cursor:
            cursor.execute("SELECT mobile, location, skills, experience FROM user WHERE id = %s", (uid,))
            u_row = cursor.fetchone()
            if u_row:
                if not cand_mobile and u_row.get('mobile'): cand_mobile = u_row['mobile']
                if not cand_location and u_row.get('location'): cand_location = u_row['location']
                if not cand_skills and u_row.get('skills'): cand_skills = u_row['skills']

    # 6. INSERT APPLICATION (catch duplicate via UNIQUE constraint)
    try:
        with db_cursor(dictionary=False) as cursor:
            cursor.execute("""
                INSERT INTO applications (
                    job_id, user_id, user_name, user_email, user_mobile,
                    qualification, college_name, year_of_passing,
                    experience_level, years_experience, previous_company,
                    skills, resume_path, cover_letter,
                    current_location, preferred_location, expected_salary,
                    status, answers, additional_document_path
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'Applied',%s,%s)
            """, (
                job_id, uid,
                sanitize_html(cand_name),
                sanitize_html(cand_email),
                sanitize_html(cand_mobile),
                sanitize_html(cand_qualification),
                sanitize_html(data.get('college') or ''),
                sanitize_html(data.get('yop') or ''),
                sanitize_html(cand_experience_level),
                sanitize_html(data.get('yoe') or ''),
                sanitize_html(data.get('prev_company') or ''),
                sanitize_html(cand_skills),
                resume_filename,
                cover_letter_text,
                sanitize_html(cand_location),
                sanitize_html(data.get('pref_loc') or ''),
                sanitize_html(data.get('salary') or ''),
                answers_json,
                additional_doc_filename
            ))
            app_id = cursor.lastrowid
    except mysql.connector.IntegrityError as e:
        if e.errno == errorcode.ER_DUP_ENTRY:
            return jsonify({'success': False, 'message': 'You have already applied for this job.'}), 400
        logger.error(f"IntegrityError in apply_job: {e}")
        return jsonify({'success': False, 'message': 'An error occurred while submitting your application.'}), 500
    except Exception as e:
        logger.error(f"Error in apply_job: {e}")
        return jsonify({'success': False, 'message': 'An error occurred while submitting your application.'}), 500

    # 7. Calculate match score
    _compute_application_match_score(
        app_id, uid, job_id, resume_filename,
        job_row.get('title'), job_row.get('description'), job_row.get('skills')
    )

    # 8. Send In-App Notifications
    job_title_display = job_row.get('title', 'Job Opening')
    comp_name_display = job_row.get('company_name', 'Verified Employer')

    # Candidate notification
    create_notification(
        user_id=uid,
        notification_type='application_submitted',
        title='Application Submitted Successfully',
        message=f"Your application for '{job_title_display}' at {comp_name_display} was submitted successfully.",
        action_url='/user_dashboard'
    )

    # Employer notification
    if job_row.get('employer_id'):
        create_notification(
            employer_id=job_row['employer_id'],
            notification_type='new_application',
            title='New Application Received 📄',
            message=f"New applicant {cand_name} applied for '{job_title_display}'.",
            action_url='/employer_dashboard'
        )

    logger.info(f"Application submitted: app_id={app_id}, user_id={uid}, job_id={job_id}")
    return jsonify({
        'success': True,
        'message': 'Application Submitted Successfully',
        'application_id': app_id,
        'job_id': job_id,
        'job_title': job_title_display,
        'company_name': comp_name_display,
        'status': 'Applied',
        'applied_at': datetime.now().strftime('%d %b %Y')
    })

@app.route('/api/get_applicants/<int:job_id>')
def get_applicants(job_id):
    if 'employer_id' not in session: return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    with db_cursor() as cursor:
        cursor.execute("SELECT employer_id FROM jobs WHERE id = %s", (job_id,))
        job = cursor.fetchone()
        if not job or job['employer_id'] != session['employer_id']:
            return jsonify({'success': False, 'message': 'Unauthorized'}), 403
        page = max(1, request.args.get('page', 1, type=int) or 1)
        per_page = min(100, max(1, request.args.get('per_page', 50, type=int) or 50))
        offset = (page - 1) * per_page
        cursor.execute("SELECT COUNT(*) AS total FROM applications WHERE job_id = %s", (job_id,))
        total = cursor.fetchone()['total']
        cursor.execute("SELECT * FROM applications WHERE job_id = %s ORDER BY id DESC LIMIT %s OFFSET %s", (job_id, per_page, offset))
        apps = cursor.fetchall()
    return jsonify({'success': True, 'applicants': apps, 'total': total, 'page': page, 'per_page': per_page})

def _compute_application_match_score(app_id, user_id, job_id, resume_path, job_title, job_desc, job_skills):
    """
    Computes real match score using Resume Intelligence and persists to applications table.
    Returns integer percentage (e.g. 85) or None if no score can be calculated.
    """
    try:
        jd_text = f"{job_title or ''}\n\nRequired Skills: {job_skills or ''}\n\n{job_desc or ''}".strip()
        if not jd_text or len(jd_text) < 10:
            return None

        candidate_skills = []
        resume_text = None

        # 1. Check if candidate has a parsed resume_analyses record
        if user_id:
            with db_cursor() as cursor:
                cursor.execute("SELECT extracted_skills, file_path FROM resume_analyses WHERE user_id = %s ORDER BY id DESC LIMIT 1", (user_id,))
                ra_row = cursor.fetchone()
                if ra_row and ra_row.get('extracted_skills'):
                    raw_skills = ra_row['extracted_skills']
                    if isinstance(raw_skills, str):
                        try:
                            raw_skills = json.loads(raw_skills)
                        except Exception:
                            raw_skills = [s.strip() for s in raw_skills.split(',') if s.strip()]
                    if isinstance(raw_skills, list):
                        candidate_skills = [{'skill': s if isinstance(s, str) else s.get('skill', '')} for s in raw_skills]

        # 2. Check resume file on disk
        target_resume = resume_path
        if not target_resume and user_id:
            with db_cursor() as cursor:
                cursor.execute("SELECT general_resume_path FROM candidate_profile WHERE user_id = %s", (user_id,))
                cp_row = cursor.fetchone()
                if cp_row and cp_row.get('general_resume_path'):
                    target_resume = cp_row['general_resume_path']

        if target_resume:
            full_path = os.path.join(app.config['UPLOAD_FOLDER'], target_resume)
            if not os.path.exists(full_path):
                base_name = os.path.basename(target_resume)
                for root, _, files in os.walk(app.config['UPLOAD_FOLDER']):
                    if base_name in files:
                        full_path = os.path.join(root, base_name)
                        break

            if os.path.exists(full_path):
                try:
                    with open(full_path, 'rb') as f:
                        extracted_txt, _ = extract_resume_text_with_report(f, target_resume)
                        if extracted_txt and len(extracted_txt.strip()) > 20:
                            resume_text = extracted_txt
                            if not candidate_skills:
                                candidate_skills = extract_skills_with_confidence(extracted_txt)
                except Exception as ex:
                    logger.warning(f"Error reading resume file {full_path}: {ex}")

        # 3. Fallback to candidate profile summary/headline if no resume file
        if not resume_text and user_id:
            with db_cursor() as cursor:
                cursor.execute("SELECT headline, summary, skills FROM candidate_profile WHERE user_id = %s", (user_id,))
                cprof = cursor.fetchone()
                if cprof:
                    headline = cprof.get('headline') or ''
                    summary = cprof.get('summary') or ''
                    skills_str = cprof.get('skills') or ''
                    if headline or summary or skills_str:
                        resume_text = f"{headline}\n\n{summary}\n\nSkills: {skills_str}"
                        if not candidate_skills and skills_str:
                            candidate_skills = [{'skill': s.strip()} for s in skills_str.split(',') if s.strip()]

        if not resume_text or len(resume_text.strip()) < 10:
            return None

        # 4. Run Resume Intelligence Job Match
        jd_match = analyze_and_match_job_description(resume_text, candidate_skills, jd_text)
        if jd_match and jd_match.get('jd_match_score') is not None:
            score = int(jd_match['jd_match_score'])
            with db_cursor(dictionary=False) as cursor:
                cursor.execute("UPDATE applications SET match_score = %s WHERE id = %s", (score, app_id))
            return score
    except Exception as e:
        logger.error(f"Error computing match score for application {app_id}: {e}")
    return None


@app.route('/api/employer/applicants')
def api_employer_applicants():
    if 'employer_id' not in session:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    emp_id = session['employer_id']

    # Query parameters for search, filtering, and sorting
    search_q = (request.args.get('q') or '').strip().lower()
    job_filter = request.args.get('job_id', type=int)
    stage_filter = (request.args.get('stage') or request.args.get('status') or 'all').strip()
    exp_filter = (request.args.get('experience') or 'all').strip()
    sort_by = (request.args.get('sort') or 'newest').strip()

    with db_cursor() as cursor:
        cursor.execute("""
            SELECT a.id, a.user_id, a.job_id, a.user_name AS candidate_name,
                   a.user_email AS candidate_email, a.user_mobile AS candidate_mobile,
                   a.qualification, a.experience_level, a.years_experience,
                   a.skills, a.tags, a.resume_path, a.match_score, a.status, a.created_at,
                   j.title AS job_title, j.description AS job_description, j.skills AS job_skills,
                   (
                       SELECT ra.ats_score
                       FROM resume_analyses ra
                       WHERE ra.user_id = a.user_id
                       ORDER BY ra.id DESC LIMIT 1
                   ) AS ats_score,
                   (
                       SELECT COUNT(*)
                       FROM application_notes an
                       WHERE an.application_id = a.id
                   ) AS notes_count
            FROM applications a
            JOIN jobs j ON a.job_id = j.id
            WHERE j.employer_id = %s
            ORDER BY a.id DESC
        """, (emp_id,))
        apps = cursor.fetchall()

    # Precalculate overall employer stats across all applicants before filtering
    stage_counts = {
        'total': len(apps),
        'applied': 0,
        'screening': 0,
        'shortlisted': 0,
        'assessment': 0,
        'interview': 0,
        'offer': 0,
        'hired': 0,
        'rejected': 0,
        'withdrawn': 0
    }

    for a in apps:
        st = (a.get('status') or 'Applied').lower()
        if st in stage_counts:
            stage_counts[st] += 1
        elif st == 'selected':
            stage_counts['shortlisted'] += 1
            stage_counts['hired'] += 1

        if a.get('created_at') and hasattr(a['created_at'], 'strftime'):
            a['applied_at'] = a['created_at'].strftime('%Y-%m-%d')
            a['created_at'] = a['created_at'].strftime('%Y-%m-%d %H:%M:%S')
        else:
            a['applied_at'] = 'Recently'

        # Match score calculation
        raw_score = a.get('match_score')
        if raw_score is None:
            raw_score = _compute_application_match_score(
                a['id'], a.get('user_id'), a.get('job_id'), a.get('resume_path'),
                a.get('job_title'), a.get('job_description'), a.get('job_skills')
            )
            a['match_score'] = raw_score

        if raw_score is not None:
            a['match_score_display'] = f"{raw_score}%"
            a['match_score_value'] = raw_score
            a['match_score'] = f"{raw_score}%"
        else:
            a['match_score_display'] = "Not scored"
            a['match_score_value'] = None
            a['match_score'] = "Not scored"

        # ATS score formatting
        ats_val = a.get('ats_score')
        if ats_val is not None:
            try:
                ats_num = int(ats_val)
                a['ats_score_display'] = f"{ats_num}%"
                a['ats_score_value'] = ats_num
            except Exception:
                a['ats_score_display'] = "Not scored"
                a['ats_score_value'] = None
        else:
            a['ats_score_display'] = "Not scored"
            a['ats_score_value'] = None

        # Tags parsing
        tags_list = []
        if a.get('tags'):
            try:
                parsed = json.loads(a['tags']) if isinstance(a['tags'], str) else a['tags']
                if isinstance(parsed, list):
                    tags_list = [str(t) for t in parsed]
                elif isinstance(parsed, str):
                    tags_list = [t.strip() for t in parsed.split(',') if t.strip()]
            except Exception:
                tags_list = [t.strip() for t in str(a['tags']).split(',') if t.strip()]
        a['tags_list'] = tags_list

    # Apply search and filtering
    filtered_apps = []
    for a in apps:
        # Job filter
        if job_filter and a.get('job_id') != job_filter:
            continue

        # Stage filter
        curr_status = (a.get('status') or 'Applied').lower()
        if stage_filter and stage_filter != 'all':
            sf = stage_filter.lower()
            if sf == 'shortlisted' and curr_status in ('shortlisted', 'selected'):
                pass
            elif sf == 'hired' and curr_status in ('hired', 'selected'):
                pass
            elif curr_status != sf:
                continue

        # Experience filter
        if exp_filter and exp_filter != 'all':
            exp_text = (a.get('experience_level') or '').lower()
            if exp_filter.lower() not in exp_text:
                continue

        # Search query (Name, Email, Mobile, Job Title, Skills, Tags)
        if search_q:
            tags_str = ' '.join(a.get('tags_list', [])).lower()
            cand_name = (a.get('candidate_name') or '').lower()
            cand_email = (a.get('candidate_email') or '').lower()
            cand_mobile = (a.get('candidate_mobile') or '').lower()
            job_title = (a.get('job_title') or '').lower()
            skills_str = (a.get('skills') or a.get('job_skills') or '').lower()

            if not (search_q in cand_name or search_q in cand_email or search_q in cand_mobile or
                    search_q in job_title or search_q in skills_str or search_q in tags_str):
                continue

        filtered_apps.append(a)

    # Apply sorting
    if sort_by == 'oldest':
        filtered_apps.sort(key=lambda x: x.get('id', 0))
    elif sort_by in ('match_high', 'match_score_desc'):
        filtered_apps.sort(key=lambda x: (x.get('match_score_value') is not None, x.get('match_score_value') or 0), reverse=True)
    elif sort_by in ('ats_high', 'ats_score_desc'):
        filtered_apps.sort(key=lambda x: (x.get('ats_score_value') is not None, x.get('ats_score_value') or 0), reverse=True)
    elif sort_by in ('name_asc', 'name'):
        filtered_apps.sort(key=lambda x: (x.get('candidate_name') or '').lower())
    elif sort_by == 'name_desc':
        filtered_apps.sort(key=lambda x: (x.get('candidate_name') or '').lower(), reverse=True)
    else:  # newest
        filtered_apps.sort(key=lambda x: x.get('id', 0), reverse=True)

    return jsonify({
        'success': True,
        'applicants': filtered_apps,
        'total_applicants': len(filtered_apps),
        'total_unfiltered': len(apps),
        'stats': stage_counts,
        'totals': stage_counts
    })


@app.route('/api/employer/candidate/<int:user_id>/profile')
def api_employer_candidate_profile(user_id):
    """
    Returns candidate profile and application context for an employer.
    Strictly verifies the employer owns a job this candidate applied to.
    """
    if 'employer_id' not in session:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401

    employer_id = session['employer_id']

    with db_cursor() as cursor:
        cursor.execute("""
            SELECT a.id AS app_id, a.job_id, a.resume_path, a.status, a.cover_letter,
                   a.answers, a.additional_document_path, a.tags,
                   a.qualification, a.experience_level, a.years_experience,
                   a.current_location, a.preferred_location, a.expected_salary,
                   a.created_at AS applied_at, a.match_score,
                   j.title AS job_title, j.category AS job_category, j.skills AS job_skills
            FROM applications a
            JOIN jobs j ON a.job_id = j.id
            WHERE a.user_id = %s AND j.employer_id = %s
            ORDER BY a.id DESC
        """, (user_id, employer_id))
        apps = cursor.fetchall()
        if not apps:
            return jsonify({
                'success': False,
                'message': 'Access denied. You do not have an active application from this candidate.'
            }), 403

        cursor.execute("SELECT id, name, email, mobile, headline, skills, experience, location FROM user WHERE id = %s", (user_id,))
        user_row = cursor.fetchone()
        if not user_row:
            return jsonify({'success': False, 'message': 'Candidate not found.'}), 404

        cursor.execute("""
            SELECT headline, summary, skills, linkedin_url, github_url, portfolio_url, general_resume_path, profile_photo 
            FROM candidate_profile 
            WHERE user_id = %s
        """, (user_id,))
        profile_row = cursor.fetchone() or {}

        cursor.execute("""
            SELECT current_location, date_of_birth, gender, marital_status, hometown, pincode, permanent_address 
            FROM candidate_personal_details 
            WHERE user_id = %s
        """, (user_id,))
        personal_row = cursor.fetchone() or {}

        cursor.execute("SELECT summary FROM candidate_profile_summary WHERE user_id = %s", (user_id,))
        summary_row = cursor.fetchone() or {}

        cursor.execute("SELECT * FROM education WHERE user_id = %s ORDER BY id DESC", (user_id,))
        education = cursor.fetchall()

        cursor.execute("SELECT * FROM key_skills WHERE user_id = %s ORDER BY id ASC", (user_id,))
        key_skills = cursor.fetchall()

        cursor.execute("SELECT * FROM projects WHERE user_id = %s ORDER BY id DESC", (user_id,))
        projects = cursor.fetchall()

        cursor.execute("SELECT * FROM certifications WHERE user_id = %s ORDER BY id DESC", (user_id,))
        certifications = cursor.fetchall()

        cursor.execute("SELECT * FROM internships WHERE user_id = %s ORDER BY id DESC", (user_id,))
        internships = cursor.fetchall()

        cursor.execute("SELECT * FROM languages WHERE user_id = %s ORDER BY id ASC", (user_id,))
        languages = cursor.fetchall()

        # ATS Score from resume_analyses
        cursor.execute("SELECT ats_score FROM resume_analyses WHERE user_id = %s ORDER BY id DESC LIMIT 1", (user_id,))
        ra_row = cursor.fetchone()
        candidate_ats_score = ra_row['ats_score'] if ra_row and ra_row.get('ats_score') is not None else None

        primary_app = apps[0]
        # Recruiter notes for this application
        cursor.execute("""
            SELECT an.id, an.application_id, an.employer_id, an.note, an.created_at,
                   COALESCE(e.company_name, 'Recruiter') AS employer_name
            FROM application_notes an
            LEFT JOIN employee e ON an.employer_id = e.id
            WHERE an.application_id = %s
            ORDER BY an.id DESC
        """, (primary_app['app_id'],))
        app_notes = cursor.fetchall()
        for n in app_notes:
            if n.get('created_at') and hasattr(n['created_at'], 'strftime'):
                n['created_at_str'] = n['created_at'].strftime('%Y-%m-%d %H:%M')
                n['created_at'] = n['created_at'].isoformat()

        # Stage history for this application
        cursor.execute("""
            SELECT ash.id, ash.application_id, ash.from_stage, ash.to_stage, ash.notes, ash.created_at,
                   COALESCE(e.company_name, 'Recruiter') AS changed_by
            FROM application_stage_history ash
            LEFT JOIN employee e ON ash.changed_by_employer_id = e.id
            WHERE ash.application_id = %s
            ORDER BY ash.id ASC
        """, (primary_app['app_id'],))
        stage_history = cursor.fetchall()
        for sh in stage_history:
            if sh.get('created_at') and hasattr(sh['created_at'], 'strftime'):
                sh['created_at_str'] = sh['created_at'].strftime('%Y-%m-%d %H:%M')
                sh['created_at'] = sh['created_at'].isoformat()

    for app_item in apps:
        if app_item.get('applied_at') and hasattr(app_item['applied_at'], 'strftime'):
            app_item['applied_at_str'] = app_item['applied_at'].strftime('%Y-%m-%d %H:%M')
        if app_item.get('match_score') is not None:
            app_item['match_score_display'] = f"{app_item['match_score']}%"
        else:
            app_item['match_score_display'] = "Not scored"

    applied_job_title = primary_app.get('job_title') or ''
    email = user_row.get('email') or ''
    mobile = user_row.get('mobile') or ''
    current_location = personal_row.get('current_location') or user_row.get('location') or primary_app.get('current_location') or ''
    summary_text = profile_row.get('summary') or summary_row.get('summary') or ''
    resume_file_path = primary_app.get('resume_path') or profile_row.get('general_resume_path') or ''

    # Tags list
    tags_list = []
    if primary_app.get('tags'):
        try:
            parsed = json.loads(primary_app['tags']) if isinstance(primary_app['tags'], str) else primary_app['tags']
            if isinstance(parsed, list):
                tags_list = [str(t) for t in parsed]
        except Exception:
            tags_list = [t.strip() for t in str(primary_app['tags']).split(',') if t.strip()]

    # Evaluate profile completeness
    completeness = evaluate_candidate_profile_completeness(user_id)
    score = completeness.get('score', 0) if isinstance(completeness, dict) else 0
    is_incomplete = score < 40
    completeness_notice = f"Profile {score}% complete — some sections not filled in yet" if is_incomplete else None

    candidate_data = {
        'id': user_row['id'],
        'name': user_row.get('name') or 'Candidate',
        'email': email,
        'mobile': mobile,
        'applied_job_title': applied_job_title,
        'job_title': applied_job_title,
        'current_location': current_location,
        'location': current_location,
        'summary': summary_text,
        'resume_path': resume_file_path,
        'app_id': primary_app.get('app_id'),
        'match_score': primary_app.get('match_score'),
        'match_score_display': primary_app.get('match_score_display'),
        'ats_score': candidate_ats_score,
        'ats_score_display': f"{candidate_ats_score}%" if candidate_ats_score is not None else "Not scored",
        'tags': tags_list,
        'notes': app_notes,
        'stage_history': stage_history,
        'completeness_score': score,
        'completeness_notice': completeness_notice,
        'is_incomplete': is_incomplete,
        'completeness': completeness,
        'headline': profile_row.get('headline') or user_row.get('headline') or '',
        'skills': profile_row.get('skills') or user_row.get('skills') or '',
        'linkedin_url': profile_row.get('linkedin_url') or '',
        'github_url': profile_row.get('github_url') or '',
        'portfolio_url': profile_row.get('portfolio_url') or '',
        'profile_photo': profile_row.get('profile_photo') or '',
        'general_resume_path': profile_row.get('general_resume_path') or '',
        'education': education,
        'key_skills': key_skills,
        'projects': projects,
        'certifications': certifications,
        'internships': internships,
        'languages': languages,
        'applications': apps
    }

    # Record verified profile view
    record_profile_view(user_id, employer_id)

    return jsonify({
        'success': True,
        'candidate': candidate_data,
        'applied_job_title': applied_job_title,
        'email': email,
        'mobile': mobile,
        'current_location': current_location,
        'summary': summary_text,
        'resume_path': resume_file_path,
        'completeness_score': score,
        'completeness_notice': completeness_notice,
        'is_incomplete': is_incomplete,
        'completeness': completeness,
        'applications': apps,
        'ats_score': candidate_ats_score,
        'ats_score_display': f"{candidate_ats_score}%" if candidate_ats_score is not None else "Not scored",
        'tags': tags_list,
        'notes': app_notes,
        'stage_history': stage_history
    })


@app.route('/api/employer/applications/<int:app_id>/resume/preview')
@app.route('/api/employer/candidate/<int:user_id>/resume/preview')
@limiter.limit("60 per minute")
def api_employer_resume_preview(app_id=None, user_id=None):
    """
    Renders an inline preview of candidate resume for an authorized employer.
    PDFs are served inline for browser/iframe rendering.
    DOCX documents have text extracted and rendered in a styled HTML preview card.
    """
    if 'employer_id' not in session:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401

    employer_id = session['employer_id']
    target_file = None
    candidate_name = "Candidate"

    with db_cursor() as cursor:
        if app_id:
            cursor.execute("""
                SELECT a.id, a.user_id, a.user_name, a.resume_path, j.employer_id, j.title
                FROM applications a
                JOIN jobs j ON a.job_id = j.id
                WHERE a.id = %s AND j.employer_id = %s
            """, (app_id, employer_id))
            app_row = cursor.fetchone()
            if not app_row:
                return jsonify({'success': False, 'message': 'Application not found or unauthorized.'}), 404
            target_file = app_row.get('resume_path')
            candidate_name = app_row.get('user_name') or "Candidate"
            if not target_file:
                cursor.execute("SELECT general_resume_path FROM candidate_profile WHERE user_id = %s", (app_row['user_id'],))
                cp_row = cursor.fetchone()
                if cp_row and cp_row.get('general_resume_path'):
                    target_file = cp_row['general_resume_path']
        elif user_id:
            cursor.execute("""
                SELECT a.id, a.user_id, a.user_name, a.resume_path, j.employer_id, j.title
                FROM applications a
                JOIN jobs j ON a.job_id = j.id
                WHERE a.user_id = %s AND j.employer_id = %s
                ORDER BY a.id DESC LIMIT 1
            """, (user_id, employer_id))
            app_row = cursor.fetchone()
            if not app_row:
                return jsonify({'success': False, 'message': 'Candidate not found or unauthorized.'}), 404
            target_file = app_row.get('resume_path')
            candidate_name = app_row.get('user_name') or "Candidate"
            if not target_file:
                cursor.execute("SELECT general_resume_path FROM candidate_profile WHERE user_id = %s", (user_id,))
                cp_row = cursor.fetchone()
                if cp_row and cp_row.get('general_resume_path'):
                    target_file = cp_row['general_resume_path']

    if not target_file:
        return """<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><style>body{font-family:-apple-system,sans-serif;padding:40px;color:#64748b;text-align:center;background:#f8fafc;}</style></head>
<body><div style="background:#fff;padding:24px;border-radius:8px;border:1px solid #e2e8f0;display:inline-block;"><h3 style="margin:0 0 8px 0;color:#334155;">No Resume File Attached</h3><p style="margin:0;font-size:14px;">The candidate has not uploaded a resume file for this application.</p></div></body>
</html>""", 404, {'Content-Type': 'text/html; charset=utf-8'}

    base_dir = app.config['UPLOAD_FOLDER']
    full_path = os.path.join(base_dir, target_file)
    if not os.path.exists(full_path):
        bname = os.path.basename(target_file)
        for root, _, files in os.walk(base_dir):
            if bname in files:
                full_path = os.path.join(root, bname)
                break

    if not os.path.exists(full_path):
        return """<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><style>body{font-family:-apple-system,sans-serif;padding:40px;color:#ef4444;text-align:center;background:#f8fafc;}</style></head>
<body><div style="background:#fff;padding:24px;border-radius:8px;border:1px solid #fecaca;display:inline-block;"><h3 style="margin:0 0 8px 0;color:#b91c1c;">Resume File Not Found</h3><p style="margin:0;font-size:14px;color:#475569;">The resume file could not be found on the server.</p></div></body>
</html>""", 404, {'Content-Type': 'text/html; charset=utf-8'}

    dir_name = os.path.dirname(full_path)
    file_name = os.path.basename(full_path)
    ext = file_name.rsplit('.', 1)[-1].lower() if '.' in file_name else ''

    if ext == 'pdf':
        response = make_response(send_from_directory(dir_name, file_name, as_attachment=False, mimetype='application/pdf'))
        response.headers['Content-Disposition'] = f'inline; filename="{file_name}"'
        return response
    elif ext in ['docx', 'doc']:
        extracted_text = ""
        try:
            with open(full_path, 'rb') as f:
                extracted_text = extract_text(f, file_name)
        except Exception as e:
            logger.error(f"DOCX preview extraction error: {e}")
            extracted_text = "Unable to extract document text."

        escaped_text = html.escape(extracted_text)
        preview_html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Resume Preview - {html.escape(candidate_name)}</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            background: #f8fafc;
            color: #1e293b;
            margin: 0;
            padding: 20px;
            font-size: 14px;
            line-height: 1.6;
        }}
        .preview-card {{
            background: #ffffff;
            border: 1px solid #e2e8f0;
            border-radius: 8px;
            padding: 24px 28px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.05);
            max-width: 800px;
            margin: 0 auto;
        }}
        .preview-header {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            border-bottom: 2px solid #e2e8f0;
            padding-bottom: 12px;
            margin-bottom: 16px;
        }}
        .preview-title {{
            font-size: 15px;
            font-weight: 700;
            color: #0f172a;
            display: flex;
            align-items: center;
            gap: 8px;
        }}
        .preview-content {{
            white-space: pre-wrap;
            word-break: break-word;
            font-family: inherit;
            color: #334155;
        }}
    </style>
</head>
<body>
    <div class="preview-card">
        <div class="preview-header">
            <div class="preview-title">📄 {html.escape(file_name)} (Document Preview)</div>
        </div>
        <div class="preview-content">{escaped_text}</div>
    </div>
</body>
</html>"""
        return preview_html, 200, {'Content-Type': 'text/html; charset=utf-8'}
    elif ext == 'txt':
        response = make_response(send_from_directory(dir_name, file_name, as_attachment=False, mimetype='text/plain; charset=utf-8'))
        response.headers['Content-Disposition'] = f'inline; filename="{file_name}"'
        return response
    else:
        response = make_response(send_from_directory(dir_name, file_name, as_attachment=False))
        response.headers['Content-Disposition'] = f'inline; filename="{file_name}"'
        return response


@app.route('/api/employer/applications/<int:app_id>/resume')
@limiter.limit("60 per minute")
def api_employer_application_resume(app_id):
    """Securely downloads or streams the resume for an applicant belonging to this employer."""
    if 'employer_id' not in session:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401

    if request.args.get('preview') == '1':
        return api_employer_resume_preview(app_id=app_id)

    employer_id = session['employer_id']
    with db_cursor() as cursor:
        cursor.execute("""
            SELECT a.id, a.user_id, a.user_name, a.resume_path, j.employer_id, j.title
            FROM applications a
            JOIN jobs j ON a.job_id = j.id
            WHERE a.id = %s AND j.employer_id = %s
        """, (app_id, employer_id))
        app_row = cursor.fetchone()
        if not app_row:
            return jsonify({'success': False, 'message': 'Application not found or unauthorized.'}), 404

        target_file = app_row.get('resume_path')
        if not target_file:
            cursor.execute("SELECT general_resume_path FROM candidate_profile WHERE user_id = %s", (app_row['user_id'],))
            cp_row = cursor.fetchone()
            if cp_row and cp_row.get('general_resume_path'):
                target_file = cp_row['general_resume_path']

    if not target_file:
        return jsonify({'success': False, 'message': 'No resume file uploaded for this candidate.'}), 404

    base_dir = app.config['UPLOAD_FOLDER']
    full_path = os.path.join(base_dir, target_file)
    if not os.path.exists(full_path):
        bname = os.path.basename(target_file)
        for root, _, files in os.walk(base_dir):
            if bname in files:
                full_path = os.path.join(root, bname)
                break

    if not os.path.exists(full_path):
        return jsonify({'success': False, 'message': 'Resume file not found on server.'}), 404

    dir_name = os.path.dirname(full_path)
    file_name = os.path.basename(full_path)
    return send_from_directory(dir_name, file_name, as_attachment=True)



def _set_candidate_status(app_id, new_status, notes=None):
    """Ownership-checked status transition + history tracking + user notification. Returns (ok, message, http)."""
    valid_statuses = {
        'Applied', 'Screening', 'Shortlisted', 'Assessment',
        'Interview', 'Offer', 'Hired', 'Selected', 'Rejected', 'Withdrawn'
    }
    if new_status not in valid_statuses:
        return False, 'Invalid status', 400

    status_messages = {
        'Applied': "Your application for '{title}' at {company} has been received.",
        'Screening': "Your application for '{title}' at {company} is currently under screening review.",
        'Shortlisted': "Great news! Your application for '{title}' at {company} has been shortlisted. We will be in touch soon.",
        'Assessment': "You have been invited for a skills assessment for '{title}' at {company}. Please check your dashboard.",
        'Interview': "Congratulations! You have been invited for an interview for '{title}' at {company}. The employer will contact you with next steps.",
        'Offer': "Exciting news! You have received a formal job offer for '{title}' at {company}!",
        'Hired': "Congratulations! You have been officially hired for '{title}' at {company}. Welcome aboard!",
        'Selected': "Congratulations! You have been selected for the position of '{title}' at {company}.",
        'Rejected': "We regret to inform you that your application for '{title}' at {company} was not selected this time. We wish you the best in your future endeavors.",
        'Withdrawn': "Your application for '{title}' at {company} has been marked as withdrawn."
    }
    with db_cursor() as cursor:
        cursor.execute("""
            SELECT a.id, a.user_id, a.job_id, a.status, j.employer_id, j.title,
                   COALESCE(e.company_name, j.company_name) AS company_name
            FROM applications a
            JOIN jobs j ON a.job_id = j.id
            LEFT JOIN employee e ON j.employer_id = e.id
            WHERE a.id = %s AND j.employer_id = %s
        """, (app_id, session['employer_id']))
        app = cursor.fetchone()
        if not app:
            return False, 'Unauthorized or application not found', 403

        from_stage = app['status'] or 'Applied'
        if from_stage == new_status:
            return True, 'No change', 200

        cursor.execute("UPDATE applications SET status = %s WHERE id = %s", (new_status, app_id))

        # Record stage transition history with timestamp
        cursor.execute("""
            INSERT INTO application_stage_history (application_id, from_stage, to_stage, changed_by_employer_id, notes)
            VALUES (%s, %s, %s, %s, %s)
        """, (app_id, from_stage, new_status, session['employer_id'], notes))

        msg = status_messages.get(new_status, status_messages['Applied']).format(
            title=app['title'], company=app['company_name'])
        
        notif_type = 'application_status_change'
        notif_title = f"Application Status: {new_status}"
        if new_status == 'Shortlisted':
            notif_type = 'shortlisting'
            notif_title = 'Application Shortlisted! 🎉'
        elif new_status == 'Rejected':
            notif_type = 'rejection'
            notif_title = 'Application Status Update'

        create_notification(
            user_id=app['user_id'],
            notification_type=notif_type,
            title=notif_title,
            message=msg,
            action_url='/user_dashboard'
        )
    return True, f"Candidate marked as {new_status}", 200


@app.route('/api/select_candidate', methods=['POST'])
def select_candidate():
    if 'employer_id' not in session: return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    data = request.json or {}
    ok, msg, http = _set_candidate_status(data.get('app_id'), 'Hired', notes=data.get('notes'))
    return jsonify({'success': ok, 'message': msg}), http


@app.route('/api/update_candidate_status', methods=['POST'])
def update_candidate_status():
    if 'employer_id' not in session: return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    data = request.json or {}
    new_status = data.get('status')
    valid_statuses = ('Applied', 'Screening', 'Shortlisted', 'Assessment', 'Interview', 'Offer', 'Hired', 'Selected', 'Rejected', 'Withdrawn')
    if new_status not in valid_statuses:
        return jsonify({'success': False, 'message': 'Invalid status'}), 400
    ok, msg, http = _set_candidate_status(data.get('app_id'), new_status, notes=data.get('notes'))
    return jsonify({'success': ok, 'message': msg}), http


@app.route('/api/employer/applications/<int:app_id>/history')
def api_employer_application_history(app_id):
    """Returns chronological stage transitions with timestamps for an application owned by employer."""
    if 'employer_id' not in session:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    employer_id = session['employer_id']
    with db_cursor() as cursor:
        cursor.execute("""
            SELECT a.id, a.user_id, a.status, a.created_at AS applied_at, j.employer_id, j.title AS job_title
            FROM applications a
            JOIN jobs j ON a.job_id = j.id
            WHERE a.id = %s AND j.employer_id = %s
        """, (app_id, employer_id))
        app_row = cursor.fetchone()
        if not app_row:
            return jsonify({'success': False, 'message': 'Application not found or unauthorized.'}), 404

        cursor.execute("""
            SELECT ash.id, ash.application_id, ash.from_stage, ash.to_stage, ash.notes, ash.created_at,
                   COALESCE(e.company_name, 'Recruiter') AS changed_by
            FROM application_stage_history ash
            LEFT JOIN employee e ON ash.changed_by_employer_id = e.id
            WHERE ash.application_id = %s
            ORDER BY ash.id ASC
        """, (app_id,))
        history = cursor.fetchall()

    for h in history:
        if h.get('created_at') and hasattr(h['created_at'], 'strftime'):
            h['created_at_str'] = h['created_at'].strftime('%Y-%m-%d %H:%M')
            h['created_at'] = h['created_at'].isoformat()

    return jsonify({'success': True, 'history': history, 'current_status': app_row['status']})


@app.route('/api/employer/applications/<int:app_id>/notes', methods=['GET', 'POST'])
def api_employer_application_notes(app_id):
    """GET/POST recruiter notes on a candidate application."""
    if 'employer_id' not in session:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    employer_id = session['employer_id']

    with db_cursor() as cursor:
        cursor.execute("""
            SELECT a.id, a.user_id, j.employer_id
            FROM applications a
            JOIN jobs j ON a.job_id = j.id
            WHERE a.id = %s AND j.employer_id = %s
        """, (app_id, employer_id))
        app_row = cursor.fetchone()
        if not app_row:
            return jsonify({'success': False, 'message': 'Application not found or unauthorized.'}), 404

    if request.method == 'POST':
        data = request.json or {}
        note_text = (data.get('note') or '').strip()
        if not note_text:
            return jsonify({'success': False, 'message': 'Note text cannot be empty'}), 400
        if len(note_text) > 3000:
            return jsonify({'success': False, 'message': 'Note is too long (max 3000 chars)'}), 400

        with db_cursor(dictionary=False) as cursor:
            cursor.execute("""
                INSERT INTO application_notes (application_id, employer_id, note)
                VALUES (%s, %s, %s)
            """, (app_id, employer_id, note_text))
            note_id = cursor.lastrowid
            cursor.execute("UPDATE applications SET notes = %s WHERE id = %s", (note_text, app_id))

        return jsonify({'success': True, 'message': 'Note added successfully', 'note_id': note_id}), 201

    # GET
    with db_cursor() as cursor:
        cursor.execute("""
            SELECT an.id, an.application_id, an.employer_id, an.note, an.created_at,
                   COALESCE(e.company_name, 'Recruiter') AS employer_name
            FROM application_notes an
            LEFT JOIN employee e ON an.employer_id = e.id
            WHERE an.application_id = %s
            ORDER BY an.id DESC
        """, (app_id,))
        notes = cursor.fetchall()

    for n in notes:
        if n.get('created_at') and hasattr(n['created_at'], 'strftime'):
            n['created_at_str'] = n['created_at'].strftime('%Y-%m-%d %H:%M')
            n['created_at'] = n['created_at'].isoformat()

    return jsonify({'success': True, 'notes': notes, 'total_notes': len(notes)})


@app.route('/api/employer/applications/<int:app_id>/tags', methods=['POST'])
def api_employer_application_tags(app_id):
    """Sets or modifies candidate tags on an application."""
    if 'employer_id' not in session:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    employer_id = session['employer_id']

    with db_cursor() as cursor:
        cursor.execute("""
            SELECT a.id, a.tags, j.employer_id
            FROM applications a
            JOIN jobs j ON a.job_id = j.id
            WHERE a.id = %s AND j.employer_id = %s
        """, (app_id, employer_id))
        app_row = cursor.fetchone()
        if not app_row:
            return jsonify({'success': False, 'message': 'Application not found or unauthorized.'}), 404

    data = request.json or {}
    current_tags = []
    if app_row.get('tags'):
        try:
            current_tags = json.loads(app_row['tags']) if isinstance(app_row['tags'], str) else app_row['tags']
            if not isinstance(current_tags, list):
                current_tags = [str(current_tags)]
        except Exception:
            current_tags = [t.strip() for t in str(app_row['tags']).split(',') if t.strip()]

    if 'tags' in data and isinstance(data['tags'], list):
        new_tags = [str(t).strip()[:30] for t in data['tags'] if str(t).strip()]
        seen = set()
        current_tags = [t for t in new_tags if not (t.lower() in seen or seen.add(t.lower()))][:10]
    elif 'tag' in data:
        tag_val = str(data['tag']).strip()[:30]
        action = data.get('action', 'add')
        if action == 'add' and tag_val:
            if not any(t.lower() == tag_val.lower() for t in current_tags):
                current_tags.append(tag_val)
        elif action == 'remove' and tag_val:
            current_tags = [t for t in current_tags if t.lower() != tag_val.lower()]

    tags_json = json.dumps(current_tags)
    with db_cursor(dictionary=False) as cursor:
        cursor.execute("UPDATE applications SET tags = %s WHERE id = %s", (tags_json, app_id))

    return jsonify({'success': True, 'tags': current_tags, 'message': 'Tags updated successfully'})

# ==============================================================================
# UNIFIED NOTIFICATIONS SYSTEM (CANDIDATE & EMPLOYER)
# ==============================================================================

# Notification category groupings for mobile & unified center
NOTIFICATION_CATEGORY_MAP = {
    'applications': ['application', 'application_submitted', 'application_status', 'shortlisted', 'shortlist', 'rejected', 'rejection'],
    'interviews': ['interview', 'interview_scheduled', 'interview_reminder', 'interview_rescheduled', 'interview_cancelled'],
    'jobs': ['job_alert', 'recommended_job', 'job', 'job_recommendation'],
    'assessments': ['assessment', 'assessment_assigned', 'assessment_result', 'badge_earned'],
    'messages': ['message', 'new_message', 'direct_message'],
    'security': ['security', 'security_event', 'password_change', 'login_alert', 'lockout']
}

def get_notification_category_group(notif_type):
    if not notif_type:
        return 'general'
    nt = str(notif_type).lower()
    if any(k in nt for k in ('application', 'shortlist', 'reject')):
        return 'applications'
    if 'interview' in nt:
        return 'interviews'
    if any(k in nt for k in ('job', 'alert', 'recommend')):
        return 'jobs'
    if any(k in nt for k in ('assessment', 'badge', 'test')):
        return 'assessments'
    if 'message' in nt:
        return 'messages'
    if any(k in nt for k in ('security', 'password', 'lockout', 'login')):
        return 'security'
    return 'general'

@app.route('/api/notifications', methods=['GET'])
@app.route('/api/get_user_notifications', methods=['GET'])
@app.route('/api/employer/notifications', methods=['GET'])
@app.route('/api/candidate/notifications', methods=['GET'])
@app.route('/api/user/notifications', methods=['GET'])
def api_get_notifications():
    """
    Returns paginated notifications for current session.
    Strictly isolates Candidate vs Employer vs Admin notifications based on session keys.
    Supports filtering by unread_only and notification_type / group.
    """
    if 'user_id' not in session and 'employer_id' not in session:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401

    page = max(1, request.args.get('page', 1, type=int) or 1)
    limit = max(1, min(100, request.args.get('limit', 20, type=int) or 20))
    offset = (page - 1) * limit
    unread_only = request.args.get('unread_only', '').lower() in ('1', 'true', 'yes')
    n_type = (request.args.get('type') or request.args.get('group') or '').strip().lower()

    is_admin = bool(session.get('is_admin'))
    is_employer = 'employer_id' in session and 'user_id' not in session
    target_id = session['employer_id'] if is_employer else session['user_id']
    id_col = 'employer_id' if is_employer else 'user_id'

    where_clauses = [f"{id_col} = %s"]
    params = [target_id]

    if unread_only:
        where_clauses.append("is_read = 0")
    if n_type and n_type != 'all':
        # Check if requested type is a category group or aliases
        normalized_group = n_type
        if normalized_group in ('application', 'applications'):
            normalized_group = 'applications'
        elif normalized_group in ('interview', 'interviews'):
            normalized_group = 'interviews'
        elif normalized_group in ('job', 'jobs'):
            normalized_group = 'jobs'
        elif normalized_group in ('assessment', 'assessments'):
            normalized_group = 'assessments'
        elif normalized_group in ('message', 'messages'):
            normalized_group = 'messages'
        elif normalized_group in ('security', 'security_event'):
            normalized_group = 'security'

        if normalized_group in NOTIFICATION_CATEGORY_MAP:
            types_list = NOTIFICATION_CATEGORY_MAP[normalized_group]
            placeholders = ','.join(['%s'] * len(types_list))
            where_clauses.append(f"notification_type IN ({placeholders})")
            params.extend(types_list)
        else:
            where_clauses.append("notification_type = %s")
            params.append(n_type)

    where_sql = " WHERE " + " AND ".join(where_clauses)

    with db_cursor() as cursor:
        # Total count
        cursor.execute(f"SELECT COUNT(*) AS total FROM notifications {where_sql}", params)
        total = cursor.fetchone()['total']

        # Unread count
        cursor.execute(f"SELECT COUNT(*) AS unread FROM notifications WHERE {id_col} = %s AND is_read = 0", (target_id,))
        unread_count = cursor.fetchone()['unread']

        # Paginated items
        cursor.execute(f"""
            SELECT id, notification_type, title, message, action_url, is_read, created_at
            FROM notifications
            {where_sql}
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
        """, params + [limit, offset])
        rows = cursor.fetchall()

    now = datetime.now()
    notifications = []
    for r in rows:
        created_at_dt = r.get('created_at')
        time_ago = 'Recently'
        if created_at_dt and isinstance(created_at_dt, datetime):
            diff = now - created_at_dt
            seconds = int(diff.total_seconds())
            if seconds < 60:
                time_ago = 'Just now'
            elif seconds < 3600:
                time_ago = f"{max(1, seconds // 60)}m ago"
            elif seconds < 86400:
                time_ago = f"{seconds // 3600}h ago"
            elif seconds < 604800:
                time_ago = f"{seconds // 86400}d ago"
            else:
                time_ago = created_at_dt.strftime('%b %d, %Y')
            created_at_iso = created_at_dt.isoformat()
        else:
            created_at_iso = None

        category_group = get_notification_category_group(r.get('notification_type'))

        notifications.append({
            'id': r['id'],
            'notification_type': r.get('notification_type') or 'general',
            'category_group': category_group,
            'title': r.get('title') or 'Notification',
            'message': r.get('message') or '',
            'action_url': r.get('action_url'),
            'is_read': bool(r.get('is_read')),
            'created_at': created_at_iso,
            'time_ago': time_ago
        })

    import math
    pages = max(1, math.ceil(total / limit))

    return jsonify({
        'success': True,
        'notifications': notifications,
        'unread_count': unread_count,
        'total': total,
        'page': page,
        'limit': limit,
        'pages': pages,
        'role': 'admin' if is_admin else ('employer' if is_employer else 'candidate')
    })


@app.route('/api/notifications/unread_count', methods=['GET'])
@app.route('/api/get_unread_count', methods=['GET'])
def api_notifications_unread_count():
    """Returns fast count of unread notifications for navbar badges."""
    if 'user_id' not in session and 'employer_id' not in session:
        return jsonify({'count': 0, 'unread_count': 0})

    is_employer = 'employer_id' in session and 'user_id' not in session
    target_id = session['employer_id'] if is_employer else session['user_id']
    id_col = 'employer_id' if is_employer else 'user_id'

    with db_cursor(dictionary=False) as cursor:
        cursor.execute(f"SELECT COUNT(*) FROM notifications WHERE {id_col} = %s AND is_read = 0", (target_id,))
        count = cursor.fetchone()[0]

    return jsonify({'success': True, 'count': count, 'unread_count': count})


@app.route('/api/notifications/<int:notification_id>/read', methods=['POST'])
def api_mark_single_notification_read(notification_id):
    """Marks a single notification as read, strictly validating recipient ownership."""
    if 'user_id' not in session and 'employer_id' not in session:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401

    is_employer = 'employer_id' in session and 'user_id' not in session
    target_id = session['employer_id'] if is_employer else session['user_id']
    id_col = 'employer_id' if is_employer else 'user_id'

    with db_cursor(dictionary=False) as cursor:
        cursor.execute(f"UPDATE notifications SET is_read = 1 WHERE id = %s AND {id_col} = %s", (notification_id, target_id))
        if cursor.rowcount == 0:
            return jsonify({'success': False, 'message': 'Notification not found or unauthorized'}), 404

    return jsonify({'success': True, 'message': 'Notification marked as read'})


@app.route('/api/notifications/mark_all_read', methods=['POST'])
@app.route('/api/mark_notifications_read', methods=['POST'])
@app.route('/api/employer/notifications/mark_read', methods=['POST'])
def api_mark_all_notifications_read():
    """Marks all unread notifications as read for current session."""
    if 'user_id' not in session and 'employer_id' not in session:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401

    is_employer = 'employer_id' in session and 'user_id' not in session
    target_id = session['employer_id'] if is_employer else session['user_id']
    id_col = 'employer_id' if is_employer else 'user_id'

    with db_cursor(dictionary=False) as cursor:
        cursor.execute(f"UPDATE notifications SET is_read = 1 WHERE {id_col} = %s AND is_read = 0", (target_id,))

    return jsonify({'success': True, 'message': 'All notifications marked as read'})


@app.route('/api/notifications/<int:notification_id>', methods=['DELETE'])
@app.route('/api/notifications/<int:notification_id>/delete', methods=['POST', 'DELETE'])
def api_delete_single_notification(notification_id):
    """Deletes a single notification, strictly verifying recipient ownership."""
    if 'user_id' not in session and 'employer_id' not in session:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401

    is_employer = 'employer_id' in session and 'user_id' not in session
    target_id = session['employer_id'] if is_employer else session['user_id']
    id_col = 'employer_id' if is_employer else 'user_id'

    with db_cursor(dictionary=False) as cursor:
        cursor.execute(f"DELETE FROM notifications WHERE id = %s AND {id_col} = %s", (notification_id, target_id))
        if cursor.rowcount == 0:
            return jsonify({'success': False, 'message': 'Notification not found or unauthorized'}), 404

    return jsonify({'success': True, 'message': 'Notification deleted successfully'})


@app.route('/api/notifications/clear_all', methods=['POST', 'DELETE'])
def api_clear_all_notifications():
    """Deletes all notifications for current user/employer."""
    if 'user_id' not in session and 'employer_id' not in session:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401

    is_employer = 'employer_id' in session and 'user_id' not in session
    target_id = session['employer_id'] if is_employer else session['user_id']
    id_col = 'employer_id' if is_employer else 'user_id'

    with db_cursor(dictionary=False) as cursor:
        cursor.execute(f"DELETE FROM notifications WHERE {id_col} = %s", (target_id,))

    return jsonify({'success': True, 'message': 'All notifications cleared'})


@app.route('/api/notifications/preferences', methods=['GET'])
@app.route('/api/user/notification_preferences', methods=['GET'])
@app.route('/api/employer/notification_preferences', methods=['GET'])
def api_get_notification_preferences():
    """Fetches notification preferences for candidate or employer."""
    if 'user_id' not in session and 'employer_id' not in session:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401

    is_employer = 'employer_id' in session and 'user_id' not in session
    target_id = session['employer_id'] if is_employer else session['user_id']
    id_col = 'employer_id' if is_employer else 'user_id'

    with db_cursor() as cur:
        cur.execute(f"SELECT * FROM notification_preferences WHERE {id_col} = %s", (target_id,))
        prefs = cur.fetchone()
        if not prefs:
            cur.execute(f"INSERT INTO notification_preferences ({id_col}) VALUES (%s)", (target_id,))
            cur.execute(f"SELECT * FROM notification_preferences WHERE {id_col} = %s", (target_id,))
            prefs = cur.fetchone()

    return jsonify({'success': True, 'preferences': prefs, 'role': 'employer' if is_employer else 'candidate'})


@app.route('/api/notifications/preferences', methods=['POST'])
@app.route('/api/user/notification_preferences', methods=['POST'])
@app.route('/api/employer/notification_preferences', methods=['POST'])
@limiter.limit("20 per minute")
def api_update_notification_preferences():
    """Updates notification preferences for candidate or employer."""
    if 'user_id' not in session and 'employer_id' not in session:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401

    is_employer = 'employer_id' in session and 'user_id' not in session
    target_id = session['employer_id'] if is_employer else session['user_id']
    id_col = 'employer_id' if is_employer else 'user_id'

    data = request.json or {}
    allowed_keys = [
        'job_alerts', 'application_updates', 'shortlist_updates',
        'interview_reminders', 'messages', 'recommended_jobs',
        'assessment_results', 'security_alerts', 'email_job_alerts',
        'email_application_updates', 'email_marketing', 'email_notifications',
        'push_notifications'
    ]

    updates = {}
    for k in allowed_keys:
        if k in data:
            v = data[k]
            if isinstance(v, bool):
                updates[k] = v
            elif isinstance(v, (int, str)):
                if str(v).lower() in ('true', '1', 'yes', 'on'):
                    updates[k] = True
                elif str(v).lower() in ('false', '0', 'no', 'off'):
                    updates[k] = False

    if not updates:
        return jsonify({'success': False, 'message': 'No valid preference fields provided'}), 400

    # Ensure row exists
    with db_cursor() as cur:
        cur.execute(f"SELECT id FROM notification_preferences WHERE {id_col} = %s", (target_id,))
        if not cur.fetchone():
            cur.execute(f"INSERT INTO notification_preferences ({id_col}) VALUES (%s)", (target_id,))

        set_clause = ", ".join([f"{k} = %s" for k in updates])
        cur.execute(f"UPDATE notification_preferences SET {set_clause} WHERE {id_col} = %s", list(updates.values()) + [target_id])

    return jsonify({'success': True, 'message': 'Notification preferences updated successfully', 'preferences': updates})


def send_interview_reminders():
    """
    Checks for upcoming interviews scheduled for today that haven't been completed/cancelled,
    and dispatches interview reminder notifications to candidate and employer.
    """
    try:
        with db_cursor() as cursor:
            cursor.execute("""
                SELECT i.*, j.title AS job_title, COALESCE(e.company_name, j.company_name) AS company_name,
                       u.name AS candidate_name
                FROM interviews i
                JOIN jobs j ON i.job_id = j.id
                LEFT JOIN employee e ON i.employer_id = e.id
                LEFT JOIN user u ON i.candidate_id = u.id
                WHERE i.status IN ('Scheduled', 'Accepted', 'Pending')
                  AND i.scheduled_date = CURDATE()
            """)
            interviews = cursor.fetchall()

        for iv in interviews:
            # Candidate reminder
            create_notification(
                user_id=iv['candidate_id'],
                notification_type='interview_reminder',
                title='Upcoming Interview Reminder ⏰',
                message=f"Reminder: You have an interview with {iv['company_name']} for '{iv['job_title']}' scheduled today at {iv['scheduled_time']}.",
                action_url='/candidate/interviews'
            )
            # Employer reminder
            create_notification(
                employer_id=iv['employer_id'],
                notification_type='interview_reminder',
                title='Upcoming Candidate Interview Reminder ⏰',
                message=f"Reminder: You have an interview with {iv['candidate_name']} for '{iv['job_title']}' scheduled today at {iv['scheduled_time']}.",
                action_url='/recruiter/interviews'
            )
        return len(interviews)
    except Exception as e:
        logger.warning(f"Error in send_interview_reminders: {e}")
        return 0


@app.route('/api/interviews/send_reminders', methods=['POST'])
def api_send_interview_reminders():
    """Endpoint for cron or manual triggering of interview reminders."""
    auth_header = request.headers.get('Authorization', '')
    cron_secret = os.environ.get('CRON_SECRET', 'secret')
    if auth_header != f"Bearer {cron_secret}" and 'is_admin' not in session and 'user_id' not in session and 'employer_id' not in session:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401

    count = send_interview_reminders()
    return jsonify({'success': True, 'reminders_sent': count})


def trigger_job_alerts_for_job(job_id, job_title, company_name=None, location=None, category=None, skills=None):
    """Matches active job alerts against a newly posted job and notifies candidates."""
    try:
        with db_cursor() as cursor:
            cursor.execute("SELECT id, user_id, keywords FROM job_alerts")
            alerts = cursor.fetchall()

        search_corpus = f"{job_title} {company_name or ''} {location or ''} {category or ''} {skills or ''}".lower()
        notified_users = set()

        for alert in alerts:
            uid = alert.get('user_id')
            if not uid or uid in notified_users:
                continue
            keywords = (alert.get('keywords') or '').lower().strip()
            if not keywords or any(kw.strip() in search_corpus for kw in keywords.split(',')):
                create_notification(
                    user_id=uid,
                    notification_type='job_alert',
                    title=f"Job Alert: {job_title} 🔔",
                    message=f"A new job '{job_title}' matching your alert was posted by '{company_name or 'HireVoltz Partner'}'.",
                    action_url=f"/jobs?search={job_title}"
                )
                notified_users.add(uid)
    except Exception as e:
        logger.warning(f"Error triggering job alerts: {e}")


def notify_recommended_job(user_id, job_id, job_title, company_name):
    """Sends a recommended job notification to candidate."""
    return create_notification(
        user_id=user_id,
        notification_type='recommended_job',
        title='New Job Recommendation 🎯',
        message=f"We found a top matching position '{job_title}' at '{company_name}' tailored to your profile skills.",
        action_url=f"/jobs?search={job_title}"
    )

# --- SETTINGS & RESUME APIs ---
@app.route('/api/get_user_profile')
@app.route('/api/user/profile', methods=['GET'])
def get_user_profile():
    if 'user_id' not in session: return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    user_id = session['user_id']
    with db_cursor() as cursor:
        cursor.execute("SELECT id, name, email, mobile, headline, skills, experience, location FROM user WHERE id = %s", (user_id,))
        user = cursor.fetchone()
        if not user:
            return jsonify({'success': False, 'message': 'User not found'}), 404

        cursor.execute("""
            SELECT headline, summary, skills, linkedin_url, github_url, portfolio_url, profile_photo, general_resume_path
            FROM candidate_profile
            WHERE user_id = %s
        """, (user_id,))
        cp_row = cursor.fetchone() or {}

        summary_val = cp_row.get('summary')
        if not summary_val:
            cursor.execute("SELECT summary FROM candidate_profile_summary WHERE user_id = %s", (user_id,))
            s_row = cursor.fetchone()
            if s_row and s_row.get('summary'):
                summary_val = s_row['summary']

        profile_data = {
            'headline': cp_row.get('headline') or user.get('headline') or '',
            'skills': cp_row.get('skills') or user.get('skills') or '',
            'summary': summary_val or '',
            'linkedin_url': cp_row.get('linkedin_url') or '',
            'github_url': cp_row.get('github_url') or '',
            'portfolio_url': cp_row.get('portfolio_url') or '',
            'profile_photo': cp_row.get('profile_photo') or '',
            'general_resume_path': cp_row.get('general_resume_path') or ''
        }

    return jsonify({'success': True, 'user': user, 'profile': profile_data})

@app.route('/api/update_user_profile', methods=['POST'])
@app.route('/api/user/profile', methods=['POST'])
def update_user_profile():
    if 'user_id' not in session: return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    user_id = session['user_id']
    data = request.json or {}
    name = data.get('name', '').strip() if data.get('name') else ''
    name = bleach.clean(name, tags=[], strip=True)
    mobile = data.get('mobile', '').strip() if data.get('mobile') else ''
    headline = bleach.clean(data.get('headline', '').strip() if data.get('headline') else '', tags=[], strip=True)
    location = bleach.clean(data.get('location', '').strip() if data.get('location') else '', tags=[], strip=True)
    skills = bleach.clean(data.get('skills', '').strip() if data.get('skills') else '', tags=[], strip=True)
    summary = bleach.clean(data.get('summary', '').strip() if data.get('summary') else '', tags=[], strip=True)
    linkedin_url = bleach.clean(data.get('linkedin_url', '').strip() if data.get('linkedin_url') else '', tags=[], strip=True)
    github_url = bleach.clean(data.get('github_url', '').strip() if data.get('github_url') else '', tags=[], strip=True)
    portfolio_url = bleach.clean(data.get('portfolio_url', '').strip() if data.get('portfolio_url') else '', tags=[], strip=True)

    if not name:
        return jsonify({'success': False, 'message': 'Name is required'}), 400
    ok, err = validate_length(name, 100, 'Name')
    if not ok:
        return jsonify({'success': False, 'message': err}), 400
    if not validate_mobile(mobile):
        return jsonify({'success': False, 'message': 'Invalid mobile number'}), 400

    for label, url in [('LinkedIn', linkedin_url), ('GitHub', github_url), ('Portfolio', portfolio_url)]:
        if url and not (url.startswith('http://') or url.startswith('https://') or url.startswith('/')):
            return jsonify({'success': False, 'message': f'Invalid {label} URL format'}), 400

    with db_cursor(dictionary=False) as cursor:
        cursor.execute("""
            UPDATE user
            SET name=%s, mobile=%s, headline=%s, location=%s, skills=%s
            WHERE id=%s
        """, (name, mobile, headline, location, skills, user_id))

        cursor.execute("""
            INSERT INTO candidate_profile (user_id, headline, summary, skills, linkedin_url, github_url, portfolio_url)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                headline = VALUES(headline),
                summary = VALUES(summary),
                skills = VALUES(skills),
                linkedin_url = VALUES(linkedin_url),
                github_url = VALUES(github_url),
                portfolio_url = VALUES(portfolio_url)
        """, (user_id, headline, summary, skills, linkedin_url, github_url, portfolio_url))

        if summary:
            cursor.execute("""
                INSERT INTO candidate_profile_summary (user_id, summary)
                VALUES (%s, %s)
                ON DUPLICATE KEY UPDATE summary = VALUES(summary)
            """, (user_id, summary))

    try:
        refresh_candidate_matches_for_active_jobs(user_id)
    except Exception as match_err:
        logger.warning(f"Background match refresh failed for user {user_id}: {match_err}")

    return jsonify({'success': True, 'message': 'Profile Updated'})

@app.route('/api/change_user_password', methods=['POST'])
@app.route('/api/user/change_password', methods=['POST'])
@limiter.limit("5 per hour")
def change_user_password():
    if 'user_id' not in session: return jsonify({'success': False}), 401
    data = request.json or {}
    old_password = data.get('old_password', '')
    new_password = data.get('new_password', '')
    if not old_password or not new_password:
        return jsonify({'success': False, 'message': 'Old and new passwords are required'}), 400
    if not validate_password(new_password):
        return jsonify({'success': False, 'message': 'Password must be at least 8 characters with at least one letter and one number'}), 400
    
    # Check password history
    if not _check_password_history(session['user_id'], None, new_password):
        return jsonify({'success': False, 'message': 'You cannot reuse a recent password. Please choose a different one.'})
    
    with db_cursor() as cursor:
        cursor.execute("SELECT password FROM user WHERE id = %s", (session['user_id'],))
        user = cursor.fetchone()
        if not user or not check_password_hash(str(user['password']), old_password):
            return jsonify({'success': False, 'message': 'Incorrect Old Password'})
        new_hash = generate_password_hash(new_password)
        cursor.execute("UPDATE user SET password = %s WHERE id = %s", (new_hash, session['user_id']))
        # Increment session_version to invalidate other sessions
        cursor.execute("UPDATE user SET session_version = session_version + 1 WHERE id = %s", (session['user_id'],))
    
    # Store new password in history
    _store_password_history(session['user_id'], None, new_hash)
    # Log activity
    log_activity('user', session['user_id'], 'changed_password')
    
    # Invalidate all existing sessions for this user after password change
    session.clear()
    logger.info("Password changed for user")
    return jsonify({'success': True, 'message': 'Password Changed Successfully!'})

@app.route('/api/employer/change_password', methods=['POST'])
@limiter.limit("5 per hour")
def change_employer_password():
    if 'employer_id' not in session: return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    data = request.json or {}
    old_password = data.get('old_password', '')
    new_password = data.get('new_password', '')
    if not old_password or not new_password:
        return jsonify({'success': False, 'message': 'Old and new passwords are required'}), 400
    if not validate_password(new_password):
        return jsonify({'success': False, 'message': 'Password must be at least 8 characters with at least one letter and one number'}), 400
    
    if not _check_password_history(None, session['employer_id'], new_password):
        return jsonify({'success': False, 'message': 'You cannot reuse a recent password. Please choose a different one.'})
    
    with db_cursor() as cursor:
        cursor.execute("SELECT password FROM employee WHERE id = %s", (session['employer_id'],))
        emp = cursor.fetchone()
        if not emp or not check_password_hash(str(emp['password']), old_password):
            return jsonify({'success': False, 'message': 'Incorrect Old Password'})
        new_hash = generate_password_hash(new_password)
        cursor.execute("UPDATE employee SET password = %s WHERE id = %s", (new_hash, session['employer_id']))
        cursor.execute("UPDATE employee SET session_version = session_version + 1 WHERE id = %s", (session['employer_id'],))
    
    _store_password_history(None, session['employer_id'], new_hash)
    log_activity('employer', session['employer_id'], 'changed_password')
    session.clear()
    logger.info("Password changed for employer")
    return jsonify({'success': True, 'message': 'Password Changed Successfully!'})

@app.route('/api/upload_resume', methods=['POST'])
@app.route('/api/user/resume/upload', methods=['POST'])
@limiter.limit("10 per minute")
def upload_resume():
    if 'user_id' not in session: return jsonify({'success': False}), 401
    if 'resume' not in request.files: return jsonify({'success': False, 'message': 'No file uploaded'})
    file = request.files['resume']
    if not file or not file.filename:
        return jsonify({'success': False, 'message': 'No file selected'})
    if not allowed_file(file.filename):
        return jsonify({'success': False, 'message': 'Invalid resume type. Allowed: txt, pdf, docx.'})
    file.seek(0, os.SEEK_END)
    if file.tell() > MAX_UPLOAD_BYTES:
        return jsonify({'success': False, 'message': f'Resume too large (max {MAX_UPLOAD_MB}MB).'})
    file.seek(0)
    if not validate_file_signature(file, file.filename):
        return jsonify({'success': False, 'message': 'File content does not match its extension. Possible corruption.'})
    file.seek(0)
    filename = secure_filename(file.filename)
    filename = f"{uuid.uuid4().hex}_{filename}"
    user_resume_dir = os.path.join(app.config['UPLOAD_FOLDER'], 'resumes', str(session['user_id']))
    os.makedirs(user_resume_dir, exist_ok=True)
    file_path = os.path.join(user_resume_dir, filename)
    file.save(file_path)
    relative_path = os.path.join('resumes', str(session['user_id']), filename)
    file.seek(0)
    content = extract_text(io.BytesIO(file.read()), file.filename)
    skills = ['python', 'java', 'sql', 'html', 'css', 'javascript', 'flask', 'django', 'react', 'c++', 'management', 'marketing', 'sales']
    found = [s for s in skills if re.search(r'\b' + re.escape(s) + r'\b', content.lower())]
    with db_cursor() as cursor:
        cursor.execute("SELECT * FROM jobs")
        jobs = cursor.fetchall()
    with db_cursor() as cursor:
        cursor.execute("SELECT user_id FROM candidate_profile WHERE user_id = %s", (session['user_id'],))
        if cursor.fetchone():
            cursor.execute("UPDATE candidate_profile SET general_resume_path = %s WHERE user_id = %s", (relative_path, session['user_id']))
        else:
            cursor.execute("INSERT INTO candidate_profile (user_id, general_resume_path) VALUES (%s, %s)", (session['user_id'], relative_path))
    ranked = []
    for job in jobs:
        if job['skills']:
            job_skills = [s.strip().lower() for s in job['skills'].split(',')]
            score = int(len(set(found) & set(job_skills)) / len(job_skills) * 100)
            if score > 0: ranked.append({**job, 'score': score})
    ranked.sort(key=lambda x: x['score'], reverse=True)
    return jsonify({'success': True, 'jobs': ranked, 'skills': found})

@app.route('/api/user/resume/download')
@limiter.limit("60 per minute")
def api_user_resume_download():
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    uid = session['user_id']
    resume_path = None
    with db_cursor() as cursor:
        cursor.execute("SELECT general_resume_path FROM candidate_profile WHERE user_id = %s", (uid,))
        prof = cursor.fetchone()
        if prof and prof.get('general_resume_path'):
            resume_path = prof['general_resume_path']
        else:
            cursor.execute("SELECT resume_path FROM applications WHERE user_id = %s AND resume_path IS NOT NULL ORDER BY id DESC LIMIT 1", (uid,))
            app_row = cursor.fetchone()
            if app_row and app_row.get('resume_path'):
                resume_path = app_row['resume_path']
    if not resume_path:
        return jsonify({'success': False, 'message': 'No resume found on profile.'}), 404
    
    full_path = os.path.join(app.config['UPLOAD_FOLDER'], resume_path)
    if not os.path.exists(full_path):
        for root, _, files in os.walk(app.config['UPLOAD_FOLDER']):
            if os.path.basename(resume_path) in files:
                full_path = os.path.join(root, os.path.basename(resume_path))
                break
    if not os.path.exists(full_path):
        return jsonify({'success': False, 'message': 'Resume file does not exist on disk.'}), 404
    dir_name = os.path.dirname(full_path)
    base_name = os.path.basename(full_path)
    return send_from_directory(dir_name, base_name, as_attachment=True)

@app.route('/api/user/resume/parse', methods=['POST'])
def api_user_resume_parse():
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    uid = session['user_id']
    resume_path = None
    with db_cursor() as cursor:
        cursor.execute("SELECT general_resume_path FROM candidate_profile WHERE user_id = %s", (uid,))
        prof = cursor.fetchone()
        if prof and prof.get('general_resume_path'):
            resume_path = prof['general_resume_path']
        else:
            cursor.execute("SELECT resume_path FROM applications WHERE user_id = %s AND resume_path IS NOT NULL ORDER BY id DESC LIMIT 1", (uid,))
            app_row = cursor.fetchone()
            if app_row and app_row.get('resume_path'):
                resume_path = app_row['resume_path']
    if not resume_path:
        return jsonify({'success': False, 'message': 'No resume uploaded yet.'}), 400
    
    full_path = os.path.join(app.config['UPLOAD_FOLDER'], resume_path)
    if not os.path.exists(full_path):
        for root, _, files in os.walk(app.config['UPLOAD_FOLDER']):
            if os.path.basename(resume_path) in files:
                full_path = os.path.join(root, os.path.basename(resume_path))
                break
    
    skills = ['Python', 'SQL', 'FastAPI', 'React', 'Docker', 'Git', 'Communication', 'Problem Solving']
    if os.path.exists(full_path):
        try:
            with open(full_path, 'rb') as f:
                content = extract_text(f, os.path.basename(full_path))
            from resume_intelligence.nlp.skill_extraction import extract_skills_with_confidence
            extracted = extract_skills_with_confidence(content)
            if extracted:
                skills = [s['name'] for s in extracted]
        except Exception as e:
            logger.warning(f"Error parsing resume: {e}")
            
    return jsonify({
        'success': True,
        'skills': skills,
        'message': f'Extracted {len(skills)} skills successfully.'
    })

# --- SAVED JOBS APIs ---
@app.route('/api/save_job', methods=['POST'])
@limiter.limit("30 per minute")
def api_save_job():
    if 'user_id' not in session: return jsonify({'success': False, 'message': 'Login required'}), 401
    data = request.json or {}
    job_id = data.get('job_id')
    if not job_id:
        return jsonify({'success': False, 'message': 'Job ID is required'}), 400
    try:
        job_id = int(job_id)
    except (TypeError, ValueError):
        return jsonify({'success': False, 'message': 'Invalid job ID'}), 400
    with db_cursor() as cursor:
        cursor.execute("SELECT id FROM jobs WHERE id = %s AND is_active = 1", (job_id,))
        if not cursor.fetchone():
            return jsonify({'success': False, 'message': 'Job not found or no longer active'}), 404
        cursor.execute("INSERT IGNORE INTO saved_jobs (user_id, job_id) VALUES (%s, %s)", (session['user_id'], job_id))
    return jsonify({'success': True, 'message': 'Job Saved'})

@app.route('/api/unsave_job', methods=['POST'])
def api_unsave_job():
    if 'user_id' not in session: return jsonify({'success': False, 'message': 'Login required'}), 401
    data = request.json or {}
    job_id = data.get('job_id')
    if not job_id:
        return jsonify({'success': False, 'message': 'Job ID is required'}), 400
    with db_cursor(dictionary=False) as cursor:
        cursor.execute("DELETE FROM saved_jobs WHERE user_id = %s AND job_id = %s", (session['user_id'], job_id))
    return jsonify({'success': True, 'message': 'Job Unsaved'})

# --- WITHDRAW APPLICATION (job seeker) ---
@app.route('/api/withdraw_application', methods=['POST'])
def withdraw_application():
    if 'user_id' not in session: return jsonify({'success': False, 'message': 'Login required'}), 401
    data = request.json or {}
    app_id = data.get('app_id') or data.get('id')
    if not app_id:
        return jsonify({'success': False, 'message': 'Application ID is required'}), 400
    try:
        app_id = int(app_id)
    except (ValueError, TypeError):
        return jsonify({'success': False, 'message': 'Invalid Application ID'}), 400

    uid = session['user_id']
    with db_cursor() as cursor:
        cursor.execute("""
            SELECT a.id, a.job_id, a.status, j.title, j.employer_id, u.name AS candidate_name
            FROM applications a
            JOIN jobs j ON a.job_id = j.id
            LEFT JOIN user u ON a.user_id = u.id
            WHERE a.id = %s AND a.user_id = %s
        """, (app_id, uid))
        app_row = cursor.fetchone()
        if not app_row:
            return jsonify({'success': False, 'message': 'Application not found or unauthorized'}), 404

        # Update status to Withdrawn
        cursor.execute("UPDATE applications SET status = 'Withdrawn' WHERE id = %s AND user_id = %s", (app_id, uid))

        # Notify employer
        cand_name = app_row.get('candidate_name') or 'Candidate'
        job_title = app_row.get('title') or 'Job Opening'
        if app_row.get('employer_id'):
            cursor.execute("""
                INSERT INTO notifications (employer_id, message, notification_type)
                VALUES (%s, %s, 'application_withdrawn')
            """, (app_row['employer_id'], f"{cand_name} has withdrawn their application for '{job_title}'."))

    return jsonify({'success': True, 'message': 'Application withdrawn successfully'})

# --- EDIT JOB (employer) ---
@app.route('/api/edit_job/<int:job_id>', methods=['POST'])
def edit_job(job_id):
    if 'employer_id' not in session: return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    data = request.json or {}
    salary_min = data.get('salary_min') or 0
    salary_max = data.get('salary_max') or 0
    try:
        salary_min = int(salary_min)
        salary_max = int(salary_max)
    except (TypeError, ValueError):
        return jsonify({'success': False, 'message': 'salary_min and salary_max must be integers'}), 400
    if salary_min < 0 or salary_max < 0:
        return jsonify({'success': False, 'message': 'Salary values cannot be negative'}), 400
    if salary_max and salary_min and salary_min > salary_max:
        return jsonify({'success': False, 'message': 'salary_min cannot exceed salary_max'}), 400
    with db_cursor(dictionary=False) as cursor:
        cursor.execute("SELECT id FROM jobs WHERE id = %s AND employer_id = %s", (job_id, session['employer_id']))
        if not cursor.fetchone():
            return jsonify({'success': False, 'message': 'Unauthorized'}), 403
        cursor.execute("""
            UPDATE jobs SET title=%s, description=%s, location=%s, salary=%s,
                experience=%s, skills=%s, category=%s, job_type=%s, work_mode=%s,
                salary_min=%s, salary_max=%s, openings=%s, application_deadline=%s, is_active=%s
            WHERE id = %s AND employer_id = %s
        """, (data.get('title'), data.get('description'), data.get('location'), data.get('salary'),
              data.get('experience'), data.get('skills'), data.get('category'),
              data.get('job_type', 'Full-time'), data.get('work_mode', 'Onsite'),
              salary_min, salary_max,
              data.get('openings') or 1,
              data.get('application_deadline') or None,
              data.get('is_active', True),
              job_id, session['employer_id']))
    return jsonify({'success': True, 'message': 'Job Updated'})

@app.route('/api/employer/jobs/<int:job_id>/toggle_status', methods=['POST'])
@app.route('/api/employer/job/<int:job_id>/status', methods=['POST'])
def api_employer_toggle_job_status(job_id):
    if 'employer_id' not in session:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    
    data = request.json or {}
    desired_action = data.get('action')  # 'close', 'activate', 'toggle' or None
    
    with db_cursor(dictionary=False) as cursor:
        cursor.execute("SELECT id, is_active FROM jobs WHERE id = %s AND employer_id = %s",
                       (job_id, session['employer_id']))
        job = cursor.fetchone()
        if not job:
            return jsonify({'success': False, 'message': 'Job not found or unauthorized'}), 404
        
        current_active = bool(job[1])
        if desired_action == 'close':
            new_active = 0
            new_status = 'Closed'
            new_reason = 'manually_closed'
        elif desired_action in ('activate', 'open', 'reactivate'):
            new_active = 1
            new_status = 'Published'
            new_reason = None
        else:
            new_active = 0 if current_active else 1
            new_status = 'Published' if new_active == 1 else 'Closed'
            new_reason = 'manually_closed' if new_active == 0 else None
            
        cursor.execute("UPDATE jobs SET is_active = %s, status = %s, closed_reason = %s WHERE id = %s AND employer_id = %s",
                       (new_active, new_status, new_reason, job_id, session['employer_id']))
        
    status_label = 'activated' if new_active == 1 else 'closed'
    return jsonify({
        'success': True,
        'message': f'Job posting successfully {status_label}',
        'is_active': bool(new_active),
        'status': new_status,
        'closed_reason': new_reason
    })

@app.route('/api/get_saved_jobs')
def api_get_saved_jobs():
    if 'user_id' not in session: return jsonify({'success': False}), 401
    with db_cursor() as cursor:
        cursor.execute("""
            SELECT j.*, COALESCE(e.company_name, j.company_name) AS company_name
            FROM jobs j
            LEFT JOIN employee e ON j.employer_id = e.id
            INNER JOIN saved_jobs s ON j.id = s.job_id
            WHERE s.user_id = %s
            ORDER BY s.created_at DESC
        """, (session['user_id'],))
        jobs = cursor.fetchall()
    return jsonify({'success': True, 'jobs': jobs})

@app.route('/api/get_saved_job_ids')
def api_get_saved_job_ids():
    if 'user_id' not in session: return jsonify({'saved_ids': []})
    with db_cursor(dictionary=False) as cursor:
        cursor.execute("SELECT job_id FROM saved_jobs WHERE user_id = %s", (session['user_id'],))
        ids = [str(row[0]) for row in cursor.fetchall()]
    return jsonify({'saved_ids': ids})

# --- CATEGORIES API ---
@app.route('/api/get_categories', methods=['GET', 'POST'])
def api_get_categories():
    with db_cursor() as cursor:
        cursor.execute("SELECT * FROM job_categories")
        cats = cursor.fetchall()
    return jsonify({'success': True, 'categories': cats})

# --- APPLICATION STATUS API ---
@app.route('/api/user/application_status')
def api_user_application_status():
    if 'user_id' not in session: return jsonify({'success': False}), 401
    with db_cursor() as cursor:
        cursor.execute("""
            SELECT a.id, a.status, a.created_at, j.id AS job_id, j.title,
                   COALESCE(e.company_name, j.company_name) AS company_name, j.location
            FROM applications a
            INNER JOIN jobs j ON a.job_id = j.id
            LEFT JOIN employee e ON j.employer_id = e.id
            WHERE a.user_id = %s
            ORDER BY a.created_at DESC
        """, (session['user_id'],))
        apps = cursor.fetchall()
    for a in apps:
        if a.get('created_at'): a['created_at'] = a['created_at'].strftime('%Y-%m-%d')
    return jsonify({'success': True, 'applications': apps})

@app.route('/api/reject_candidate', methods=['POST'])
def reject_candidate():
    if 'employer_id' not in session: return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    data = request.json or {}
    ok, msg, http = _set_candidate_status(data.get('app_id'), 'Rejected')
    return jsonify({'success': ok, 'message': msg}), http

@app.route('/api/employer/applications/<int:app_id>/document/download')
def api_employer_download_application_document(app_id):
    if 'employer_id' not in session:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    emp_id = session['employer_id']
    with db_cursor() as cursor:
        cursor.execute("""
            SELECT a.additional_document_path, j.employer_id
            FROM applications a
            JOIN jobs j ON a.job_id = j.id
            WHERE a.id = %s AND j.employer_id = %s
        """, (app_id, emp_id))
        row = cursor.fetchone()
    if not row or not row.get('additional_document_path'):
        return jsonify({'success': False, 'message': 'Document not found or unauthorized'}), 404

    doc_path = row['additional_document_path']
    full_path = os.path.join(app.config['UPLOAD_FOLDER'], doc_path)
    if not os.path.exists(full_path):
        for root, _, files in os.walk(app.config['UPLOAD_FOLDER']):
            if os.path.basename(doc_path) in files:
                full_path = os.path.join(root, os.path.basename(doc_path))
                break
    if not os.path.exists(full_path):
        return jsonify({'success': False, 'message': 'Document file not found on disk'}), 404

    dir_name = os.path.dirname(full_path)
    base_name = os.path.basename(full_path)
    return send_from_directory(dir_name, base_name, as_attachment=True)

# Employer notifications now alias to unified /api/notifications and /api/notifications/mark_all_read

@app.route('/api/employer/application_count')
def employer_application_count():
    if 'employer_id' not in session: return jsonify({'count': 0})
    with db_cursor(dictionary=False) as cursor:
        cursor.execute("""
            SELECT COUNT(*) FROM applications a
            INNER JOIN jobs j ON a.job_id = j.id
            WHERE j.employer_id = %s
        """, (session['employer_id'],))
        count = cursor.fetchone()[0]
    return jsonify({'count': count})

@app.route('/api/jobs/paginated')
@limiter.limit("60 per minute")
def api_jobs_paginated():
    page = max(1, request.args.get('page', 1, type=int) or 1)
    per_page = 10
    offset = (page - 1) * per_page
    with db_cursor() as cursor:
        cursor.execute("SELECT COUNT(*) as total FROM jobs")
        total = cursor.fetchone()['total']
        cursor.execute("""
            SELECT j.*, COALESCE(e.company_name, j.company_name) AS company_name,
                   e.is_verified AS employer_is_verified, e.verification_status AS employer_verification_status
            FROM jobs j
            LEFT JOIN employee e ON j.employer_id = e.id
            ORDER BY j.id DESC LIMIT %s OFFSET %s
        """, (per_page, offset))
        jobs = cursor.fetchall()
    for j in jobs:
        if j.get('created_at'): j['created_at'] = j['created_at'].strftime('%Y-%m-%d')
    return jsonify({'success': True, 'jobs': jobs, 'total': total, 'page': page, 'per_page': per_page})

# --- EMPLOYER ANALYTICS (single aggregate query, no N+1) ---
@app.route('/api/employer/analytics')
def employer_analytics():
    if 'employer_id' not in session: return jsonify({'success': False}), 401
    emp_id = session['employer_id']
    with db_cursor() as cursor:
        cursor.execute("SELECT COUNT(*) AS job_count FROM jobs WHERE employer_id = %s", (emp_id,))
        job_count = cursor.fetchone()['job_count']
        cursor.execute("""
            SELECT
                COUNT(a.id) AS total_applicants,
                SUM(CASE WHEN a.status IN ('Selected', 'Hired') THEN 1 ELSE 0 END) AS selected,
                SUM(CASE WHEN a.status='Rejected' THEN 1 ELSE 0 END) AS rejected,
                SUM(CASE WHEN a.status='Interview' THEN 1 ELSE 0 END) AS interviews,
                SUM(CASE WHEN a.status IN ('Shortlisted', 'Selected', 'Hired') THEN 1 ELSE 0 END) AS shortlisted
            FROM applications a JOIN jobs j ON a.job_id = j.id
            WHERE j.employer_id = %s
        """, (emp_id,))
        totals = cursor.fetchone()
        cursor.execute("""
            SELECT j.id, j.title, j.category,
                COUNT(a.id) AS total_applicants,
                SUM(CASE WHEN a.status IN ('Selected', 'Hired') THEN 1 ELSE 0 END) AS selected,
                SUM(CASE WHEN a.status='Interview' THEN 1 ELSE 0 END) AS interviews,
                SUM(CASE WHEN a.status IN ('Shortlisted', 'Selected', 'Hired') THEN 1 ELSE 0 END) AS shortlisted,
                SUM(CASE WHEN a.status='Rejected' THEN 1 ELSE 0 END) AS rejected
            FROM jobs j LEFT JOIN applications a ON j.id = a.job_id
            WHERE j.employer_id = %s
            GROUP BY j.id
            ORDER BY total_applicants DESC
        """, (emp_id,))
        per_job = cursor.fetchall()

    totals_dict = totals or {}
    total_applicants = int(totals_dict.get('total_applicants') or 0)
    shortlisted = int(totals_dict.get('shortlisted') or 0)
    interviews = int(totals_dict.get('interviews') or 0)
    selected = int(totals_dict.get('selected') or 0)
    rejected = int(totals_dict.get('rejected') or 0)

    return jsonify({
        'success': True,
        'job_count': job_count,
        'total_jobs': job_count,
        'total_applicants': total_applicants,
        'shortlisted': shortlisted,
        'interviews': interviews,
        'selected': selected,
        'hired': selected,
        'rejected': rejected,
        'totals': totals_dict,
        'per_job': per_job
    })


# --- EMPLOYER PROFILE API (LEGACY ALIAS) ---
@app.route('/api/employer_profile')
def api_employer_profile_legacy():
    if 'employer_id' not in session: return jsonify({'success': False}), 401
    with db_cursor() as cursor:
        cursor.execute("SELECT id, company_name, email, mobile FROM employee WHERE id = %s", (session['employer_id'],))
        emp = cursor.fetchone()
    return jsonify({'success': True, 'employer': emp})

@app.route('/api/update_employer_profile', methods=['POST'])
def api_update_employer_profile():
    if 'employer_id' not in session: return jsonify({'success': False}), 401
    data = request.json or {}
    company_name = data.get('company_name', '').strip() if data.get('company_name') else ''
    mobile = data.get('mobile', '').strip() if data.get('mobile') else ''
    if not company_name:
        return jsonify({'success': False, 'message': 'Company name is required'}), 400
    ok, err = validate_length(company_name, 100, 'Company name')
    if not ok:
        return jsonify({'success': False, 'message': err}), 400
    if not validate_mobile(mobile):
        return jsonify({'success': False, 'message': 'Invalid mobile number'}), 400
    with db_cursor(dictionary=False) as cursor:
        cursor.execute("UPDATE employee SET company_name=%s, mobile=%s WHERE id=%s",
                       (company_name, mobile, session['employer_id']))
        cursor.execute("UPDATE jobs SET company_name=%s WHERE employer_id=%s",
                       (company_name, session['employer_id']))
        cursor.execute("UPDATE profile_views SET company_name=%s WHERE employer_id=%s",
                       (company_name, session['employer_id']))
    session['user_name'] = company_name
    session['company_name'] = company_name
    return jsonify({'success': True, 'message': 'Profile Updated'})

@app.route('/api/change_employer_password', methods=['POST'])
@limiter.limit("5 per hour")
def api_change_employer_password():
    if 'employer_id' not in session: return jsonify({'success': False}), 401
    data = request.json or {}
    old_password = data.get('old_password', '')
    new_password = data.get('new_password', '')
    if not old_password or not new_password:
        return jsonify({'success': False, 'message': 'Old and new passwords are required'}), 400
    if not validate_password(new_password):
        return jsonify({'success': False, 'message': 'Password must be at least 8 characters with at least one letter and one number'}), 400
    
    # Check password history
    if not _check_password_history(None, session['employer_id'], new_password):
        return jsonify({'success': False, 'message': 'You cannot reuse a recent password. Please choose a different one.'})
    
    with db_cursor() as cursor:
        cursor.execute("SELECT password FROM employee WHERE id = %s", (session['employer_id'],))
        emp = cursor.fetchone()
        if not emp or not check_password_hash(str(emp['password']), old_password):
            return jsonify({'success': False, 'message': 'Incorrect Old Password'})
        new_hash = generate_password_hash(new_password)
        cursor.execute("UPDATE employee SET password = %s WHERE id = %s", (new_hash, session['employer_id']))
        # Increment session_version to invalidate other sessions
        cursor.execute("UPDATE employee SET session_version = session_version + 1 WHERE id = %s", (session['employer_id'],))
    
    # Store new password in history
    _store_password_history(None, session['employer_id'], new_hash)
    # Log activity
    log_activity('employer', session['employer_id'], 'changed_password')
    
    session.clear()
    logger.info("Password changed for employer")
    return jsonify({'success': True, 'message': 'Password Changed'})


# --- CANDIDATE PROFILE ---
def trigger_async_match_refresh(candidate_id):
    """Offloads match scoring to a background daemon thread so HTTP response is instant."""
    if not candidate_id:
        return
    try:
        t = threading.Thread(target=refresh_candidate_matches_for_active_jobs, args=(candidate_id,), daemon=True)
        t.start()
    except Exception as e:
        logger.warning(f"Could not spawn async match refresh thread for candidate {candidate_id}: {e}")


def evaluate_candidate_profile_completeness(user_id):
    """
    Evaluates candidate profile completeness across 13 distinct sections with
    balanced weighting (total 100%) ensuring no active section has 0% weight.
    """
    weights = {
        'basic_profile': 10,
        'preferences': 5,
        'education': 10,
        'key_skills': 15,
        'languages': 5,
        'internships': 5,
        'projects': 10,
        'profile_summary': 10,
        'accomplishments': 5,
        'competitive_exams': 5,
        'employment': 10,
        'academic_achievements': 5,
        'resume': 5,
    }

    if not user_id:
        # Return default 13-section breakdown with 0 score
        sections_meta = [
            ('basic_profile', 'Basic Profile', False, weights['basic_profile'], '/candidate/profile/edit#section-basic', 'Add Personal Details', 'Complete Profile Details'),
            ('preferences', 'Job Preferences', False, weights['preferences'], '/candidate/profile/edit#section-preferences', 'Add Preferences', 'Set Career Preferences'),
            ('education', 'Education', False, weights['education'], '/candidate/profile/edit#section-education', 'Add Education', 'Add Qualifications'),
            ('key_skills', 'Key Skills', False, weights['key_skills'], '/candidate/profile/edit#section-skills', 'Add Key Skills', 'Add Tech Skills'),
            ('languages', 'Languages', False, weights['languages'], '/candidate/profile/edit#section-languages', 'Add Languages', 'Add Known Languages'),
            ('internships', 'Internships', False, weights['internships'], '/candidate/profile/edit#section-internships', 'Add Internships', 'Add Internship Experience'),
            ('projects', 'Projects', False, weights['projects'], '/candidate/profile/edit#section-projects', 'Add Projects', 'Showcase Projects'),
            ('profile_summary', 'Profile Summary', False, weights['profile_summary'], '/candidate/profile/edit#section-summary', 'Add Profile Summary', 'Write Profile Summary'),
            ('accomplishments', 'Accomplishments & Certifications', False, weights['accomplishments'], '/candidate/profile/edit#section-certifications', 'Add Certifications', 'Add Badges & Certs'),
            ('competitive_exams', 'Competitive Exams', False, weights['competitive_exams'], '/candidate/profile/edit#section-exams', 'Add Competitive Exams', 'Add Exam Scores'),
            ('employment', 'Employment & Experience', False, weights['employment'], '/candidate/profile/edit#section-employment', 'Add Work Experience', 'Add Work History'),
            ('academic_achievements', 'Academic Achievements', False, weights['academic_achievements'], '/candidate/profile/edit#section-academic', 'Add Achievements', 'Add Honors'),
            ('resume', 'Resume Document', False, weights['resume'], '/candidate/resume', 'Upload Resume', 'Upload Modern Resume'),
        ]
        breakdown = [
            {'id': s[0], 'title': s[1], 'completed': False, 'weight': s[3], 'url': s[4], 'missing_label': s[5], 'action_label': s[6]}
            for s in sections_meta
        ]
        return {
            'score': 0,
            'candidate_type': 'fresher',
            'completed_count': 0,
            'total_items': 13,
            'completed_items': [],
            'missing_items': breakdown,
            'breakdown': breakdown
        }

    try:
        with db_cursor() as cursor:
            # 1. Basic user info
            cursor.execute("SELECT id, name, email, mobile FROM user WHERE id = %s", (user_id,))
            user_row = cursor.fetchone() or {}

            # 2. Candidate profile table
            cursor.execute("SELECT * FROM candidate_profile WHERE user_id = %s", (user_id,))
            cand_prof = cursor.fetchone() or {}

            # 3. Personal details
            cursor.execute("SELECT * FROM candidate_personal_details WHERE user_id = %s", (user_id,))
            personal_row = cursor.fetchone() or {}

            # 4. Preferences
            cursor.execute("SELECT * FROM candidate_preferences WHERE user_id = %s", (user_id,))
            pref_row = cursor.fetchone() or {}

            # 5. Profile Summary
            cursor.execute("SELECT summary FROM candidate_profile_summary WHERE user_id = %s", (user_id,))
            summary_row = cursor.fetchone() or {}

            # 6. Education count
            cursor.execute("SELECT COUNT(*) AS cnt FROM education WHERE user_id = %s", (user_id,))
            edu_cnt = cursor.fetchone()['cnt']

            # 7. Key skills count + profile skills string
            cursor.execute("SELECT COUNT(*) AS cnt FROM key_skills WHERE user_id = %s", (user_id,))
            skills_cnt = cursor.fetchone()['cnt']
            profile_skills_str = (cand_prof.get('skills') or '').strip()

            # 8. Languages count
            cursor.execute("SELECT COUNT(*) AS cnt FROM languages WHERE user_id = %s", (user_id,))
            lang_cnt = cursor.fetchone()['cnt']

            # 9. Internships count
            cursor.execute("SELECT COUNT(*) AS cnt FROM internships WHERE user_id = %s", (user_id,))
            intern_cnt = cursor.fetchone()['cnt']

            # 10. Projects count
            cursor.execute("SELECT COUNT(*) AS cnt FROM projects WHERE user_id = %s", (user_id,))
            proj_cnt = cursor.fetchone()['cnt']

            # 11. Accomplishments (Certifications, Publications, Presentations, Patents)
            cursor.execute("SELECT COUNT(*) AS cnt FROM certifications WHERE user_id = %s", (user_id,))
            cert_cnt = cursor.fetchone()['cnt']
            cursor.execute("SELECT COUNT(*) AS cnt FROM publications WHERE user_id = %s", (user_id,))
            pub_cnt = cursor.fetchone()['cnt']
            cursor.execute("SELECT COUNT(*) AS cnt FROM presentations WHERE user_id = %s", (user_id,))
            pres_cnt = cursor.fetchone()['cnt']
            cursor.execute("SELECT COUNT(*) AS cnt FROM patents WHERE user_id = %s", (user_id,))
            pat_cnt = cursor.fetchone()['cnt']
            accomplishments_cnt = cert_cnt + pub_cnt + pres_cnt + pat_cnt

            # 12. Competitive Exams count
            cursor.execute("SELECT COUNT(*) AS cnt FROM competitive_exams WHERE user_id = %s", (user_id,))
            exams_cnt = cursor.fetchone()['cnt']

            # 13. Employment count
            cursor.execute("SELECT COUNT(*) AS cnt FROM employment WHERE user_id = %s", (user_id,))
            emp_cnt = cursor.fetchone()['cnt']

            # 14. Academic Achievements count
            cursor.execute("SELECT COUNT(*) AS cnt FROM academic_achievements WHERE user_id = %s", (user_id,))
            acad_cnt = cursor.fetchone()['cnt']
    except Exception as e:
        logger.error(f"Error evaluating profile completeness for user {user_id}: {e}")
        return {
            'score': 20,
            'candidate_type': 'fresher',
            'completed_count': 1,
            'total_items': 13,
            'completed_items': [],
            'missing_items': [],
            'breakdown': []
        }

    # Determine Candidate Type (Fresher vs Experienced)
    headline = (cand_prof.get('headline') or '').lower()
    is_experienced = (emp_cnt > 0) or ('year' in headline and not 'fresher' in headline)
    candidate_type = 'experienced' if is_experienced else 'fresher'

    # Section Completion Status
    has_basic = bool(user_row.get('name') and (user_row.get('email') or user_row.get('mobile')) and (cand_prof.get('headline') or personal_row.get('gender') or personal_row.get('current_location') or personal_row.get('nationality')))
    has_pref = bool(pref_row.get('desired_job_type') or pref_row.get('expected_ctc') or pref_row.get('current_industry') or pref_row.get('preferred_shift') or pref_row.get('desired_employment_type') or pref_row.get('current_job_role') or pref_row.get('current_role') or pref_row.get('preferred_location') or pref_row.get('workplace_type'))
    has_edu = bool(edu_cnt > 0 or cand_prof.get('education'))
    has_skills = bool(skills_cnt > 0 or len(profile_skills_str) > 2)
    has_lang = bool(lang_cnt > 0)
    has_intern = bool(intern_cnt > 0)
    has_proj = bool(proj_cnt > 0)
    has_summary = bool((summary_row.get('summary') or cand_prof.get('summary') or '').strip())
    has_accomp = bool(accomplishments_cnt > 0)
    has_exams = bool(exams_cnt > 0)
    has_emp = bool(emp_cnt > 0 or (cand_prof.get('experience') and len(str(cand_prof.get('experience')).strip()) > 2))
    has_acad = bool(acad_cnt > 0)
    has_resume = bool(cand_prof.get('general_resume_path') or cand_prof.get('resume_path'))

    sections_meta = [
        ('basic_profile', 'Basic Profile', has_basic, weights['basic_profile'], '/candidate/profile/edit#section-basic', 'Add Personal Details', 'Complete Profile Details'),
        ('preferences', 'Job Preferences', has_pref, weights['preferences'], '/candidate/profile/edit#section-preferences', 'Add Preferences', 'Set Career Preferences'),
        ('education', 'Education', has_edu, weights['education'], '/candidate/profile/edit#section-education', 'Add Education', 'Add Qualifications'),
        ('key_skills', 'Key Skills', has_skills, weights['key_skills'], '/candidate/profile/edit#section-skills', 'Add Key Skills', 'Add Tech Skills'),
        ('languages', 'Languages', has_lang, weights['languages'], '/candidate/profile/edit#section-languages', 'Add Languages', 'Add Known Languages'),
        ('internships', 'Internships', has_intern, weights['internships'], '/candidate/profile/edit#section-internships', 'Add Internships', 'Add Internship Experience'),
        ('projects', 'Projects', has_proj, weights['projects'], '/candidate/profile/edit#section-projects', 'Add Projects', 'Showcase Projects'),
        ('profile_summary', 'Profile Summary', has_summary, weights['profile_summary'], '/candidate/profile/edit#section-summary', 'Add Profile Summary', 'Write Profile Summary'),
        ('accomplishments', 'Accomplishments & Certifications', has_accomp, weights['accomplishments'], '/candidate/profile/edit#section-certifications', 'Add Certifications', 'Add Badges & Certs'),
        ('competitive_exams', 'Competitive Exams', has_exams, weights['competitive_exams'], '/candidate/profile/edit#section-exams', 'Add Competitive Exams', 'Add Exam Scores'),
        ('employment', 'Employment & Experience', has_emp, weights['employment'], '/candidate/profile/edit#section-employment', 'Add Work Experience', 'Add Work History'),
        ('academic_achievements', 'Academic Achievements', has_acad, weights['academic_achievements'], '/candidate/profile/edit#section-academic', 'Add Achievements', 'Add Honors'),
        ('resume', 'Resume Document', has_resume, weights['resume'], '/candidate/resume', 'Upload Resume', 'Upload Modern Resume'),
    ]

    total_score = 0
    completed_items = []
    missing_items = []
    breakdown = []

    for sec_id, title, is_done, weight, url, missing_label, action_label in sections_meta:
        item = {
            'id': sec_id,
            'title': title,
            'completed': is_done,
            'weight': weight,
            'url': url,
            'missing_label': missing_label,
            'action_label': action_label
        }
        breakdown.append(item)
        if is_done:
            total_score += weight
            completed_items.append(item)
        else:
            missing_items.append(item)

    score = min(100, max(0, round(total_score)))

    return {
        'score': score,
        'candidate_type': candidate_type,
        'completed_count': len(completed_items),
        'total_items': len(sections_meta),
        'completed_items': completed_items,
        'missing_items': missing_items,
        'breakdown': breakdown
    }

def compute_profile_completeness(profile):
    if not profile:
        return 0
    if profile.get('user_id'):
        data = evaluate_candidate_profile_completeness(profile['user_id'])
        return data['score']
    fields = ['headline', 'summary', 'skills', 'experience', 'education',
              'linkedin_url', 'github_url', 'portfolio_url', 'profile_photo']
    filled = sum(1 for f in fields if profile.get(f) and str(profile.get(f)).strip())
    return round((filled / len(fields)) * 100)


@app.route('/api/candidate/profile')
def api_candidate_profile():
    if 'user_id' not in session: return jsonify({'success': False}), 401
    with db_cursor() as cursor:
        cursor.execute("SELECT * FROM candidate_profile WHERE user_id = %s", (session['user_id'],))
        profile = cursor.fetchone()
        if not profile:
            cursor.execute("INSERT INTO candidate_profile (user_id) VALUES (%s)", (session['user_id'],))
            cursor.execute("SELECT * FROM candidate_profile WHERE user_id = %s", (session['user_id'],))
            profile = cursor.fetchone()
    completeness = compute_profile_completeness(profile) if profile else 0
    # Parse JSON fields
    if profile:
        if profile.get('experience'): profile['experience'] = json.loads(profile['experience'])
        if profile.get('education'): profile['education'] = json.loads(profile['education'])
    return jsonify({'success': True, 'profile': profile, 'completeness': completeness})


@app.route('/api/candidate/profile', methods=['POST'])
def api_update_candidate_profile():
    if 'user_id' not in session: return jsonify({'success': False}), 401
    data = request.json or {}
    headline = data.get('headline', '').strip() if data.get('headline') else ''
    summary = data.get('summary', '').strip() if data.get('summary') else ''
    skills = data.get('skills', '').strip() if data.get('skills') else ''
    ok, err = validate_length(headline, 255, 'Headline')
    if not ok:
        return jsonify({'success': False, 'message': err}), 400
    experience = json.dumps(data.get('experience', []))
    education = json.dumps(data.get('education', []))
    linkedin = data.get('linkedin_url', '')
    github = data.get('github_url', '')
    portfolio = data.get('portfolio_url', '')

    # Validate URLs if provided
    for label, url in [('LinkedIn', linkedin), ('GitHub', github), ('Portfolio', portfolio)]:
        if url and not (url.startswith('http://') or url.startswith('https://') or url.startswith('/')):
            return jsonify({'success': False, 'message': f'Invalid {label} URL format'}), 400

    with db_cursor(dictionary=False) as cursor:
        cursor.execute("""
            INSERT INTO candidate_profile (
                user_id, headline, summary, skills,
                experience, education,
                linkedin_url, github_url, portfolio_url
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                headline = VALUES(headline),
                summary = VALUES(summary),
                skills = VALUES(skills),
                experience = VALUES(experience),
                education = VALUES(education),
                linkedin_url = VALUES(linkedin_url),
                github_url = VALUES(github_url),
                portfolio_url = VALUES(portfolio_url)
        """, (session['user_id'], headline, summary, skills, experience, education, linkedin, github, portfolio))
    
    trigger_async_match_refresh(session['user_id'])
    logger.info(f"Profile updated for user_id={session['user_id']}")
    return jsonify({'success': True, 'message': 'Profile Updated'})


@app.route('/api/candidate/profile/visibility', methods=['POST'])
def api_toggle_profile_visibility():
    if 'user_id' not in session: return jsonify({'success': False}), 401
    data = request.json or {}
    is_public = data.get('is_public', False)
    with db_cursor(dictionary=False) as cursor:
        cursor.execute("UPDATE candidate_profile SET is_public = %s WHERE user_id = %s",
                       (is_public, session['user_id']))
    return jsonify({'success': True, 'is_public': is_public})


def render_full_candidate_profile(candidate_id, is_preview=False):
    with db_cursor() as cursor:
        cursor.execute("SELECT u.id, u.name, u.email, u.mobile, u.is_verified, u.created_at FROM user u WHERE u.id = %s", (candidate_id,))
        user = cursor.fetchone()
        if not user:
            return "Candidate not found", 404
        
        cursor.execute("SELECT * FROM candidate_profile WHERE user_id = %s", (candidate_id,))
        profile = cursor.fetchone() or {}
        
        # Check privacy if not own view / not preview
        is_owner = (session.get('user_id') == candidate_id)
        if not is_owner and not is_preview and not profile.get('is_public'):
            return "Profile is private", 404
            
        cursor.execute("SELECT * FROM candidate_personal_details WHERE user_id = %s", (candidate_id,))
        personal = _format_db_row(cursor.fetchone() or {})
        
        cursor.execute("SELECT * FROM candidate_preferences WHERE user_id = %s", (candidate_id,))
        preferences = _format_db_row(cursor.fetchone() or {})
        
        cursor.execute("SELECT summary FROM candidate_profile_summary WHERE user_id = %s", (candidate_id,))
        summary_row = cursor.fetchone() or {}
        summary = summary_row.get('summary') or profile.get('summary') or ''
        
        cursor.execute("SELECT * FROM education WHERE user_id = %s ORDER BY id DESC", (candidate_id,))
        education = [_format_db_row(r) for r in cursor.fetchall()]
        
        cursor.execute("SELECT * FROM employment WHERE user_id = %s ORDER BY is_current DESC, id DESC", (candidate_id,))
        employment = [_format_db_row(r) for r in cursor.fetchall()]
        
        cursor.execute("SELECT * FROM key_skills WHERE user_id = %s ORDER BY id ASC", (candidate_id,))
        key_skills = [_format_db_row(r) for r in cursor.fetchall()]
        
        cursor.execute("SELECT * FROM languages WHERE user_id = %s ORDER BY id ASC", (candidate_id,))
        languages = [_format_db_row(r) for r in cursor.fetchall()]
        
        cursor.execute("SELECT * FROM internships WHERE user_id = %s ORDER BY id DESC", (candidate_id,))
        internships = [_format_db_row(r) for r in cursor.fetchall()]
        
        cursor.execute("SELECT * FROM projects WHERE user_id = %s ORDER BY id DESC", (candidate_id,))
        projects = [_format_db_row(r) for r in cursor.fetchall()]
        
        cursor.execute("SELECT * FROM certifications WHERE user_id = %s ORDER BY id DESC", (candidate_id,))
        certifications = [_format_db_row(r) for r in cursor.fetchall()]
        
        cursor.execute("SELECT * FROM competitive_exams WHERE user_id = %s ORDER BY id DESC", (candidate_id,))
        competitive_exams = [_format_db_row(r) for r in cursor.fetchall()]
        
        cursor.execute("SELECT * FROM academic_achievements WHERE user_id = %s ORDER BY id DESC", (candidate_id,))
        academic_achievements = [_format_db_row(r) for r in cursor.fetchall()]
        
        cursor.execute("""
            SELECT sb.*, a.icon, a.badge_icon, a.domain, a.difficulty
            FROM skill_badges sb
            JOIN assessments a ON sb.assessment_id = a.id
            WHERE sb.user_id = %s
            ORDER BY sb.score DESC, sb.earned_at DESC
        """, (candidate_id,))
        verified_badges = cursor.fetchall()

    completeness_data = evaluate_candidate_profile_completeness(candidate_id)
    completeness = completeness_data.get('score', 0)

    technical_skills = [s for s in key_skills if (s.get('skill_type') or '').lower() != 'soft']
    soft_skills = [s for s in key_skills if (s.get('skill_type') or '').lower() == 'soft']
    
    return render_template(
        'candidate_profile.html',
        user=user,
        profile=profile,
        personal=personal,
        preferences=preferences,
        summary=summary,
        education=education,
        employment=employment,
        key_skills=key_skills,
        technical_skills=technical_skills,
        soft_skills=soft_skills,
        languages=languages,
        internships=internships,
        projects=projects,
        certifications=certifications,
        competitive_exams=competitive_exams,
        academic_achievements=academic_achievements,
        completeness=completeness,
        completeness_data=completeness_data,
        verified_badges=verified_badges,
        is_owner=is_owner
    )


@app.route('/candidate/<int:candidate_id>')
def public_candidate_profile(candidate_id):
    return render_full_candidate_profile(candidate_id, is_preview=False)


@app.route('/candidate/profile/view')
def candidate_profile_view():
    if 'user_id' not in session:
        return redirect(url_for('index'))
    return render_full_candidate_profile(session['user_id'], is_preview=True)


@app.route('/api/candidate/<int:candidate_id>/public')
def api_candidate_public(candidate_id):
    with db_cursor() as cursor:
        cursor.execute("SELECT u.id, u.name FROM user u WHERE u.id = %s", (candidate_id,))
        user = cursor.fetchone()
        if not user:
            return jsonify({'success': False, 'message': 'Candidate not found'}), 404
        cursor.execute("SELECT * FROM candidate_profile WHERE user_id = %s", (candidate_id,))
        profile = cursor.fetchone()
        if not profile:
            return jsonify({'success': False, 'message': 'Profile is private'}), 404
        is_owner = (session.get('user_id') == candidate_id)
        if not is_owner and not profile.get('is_public'):
            return jsonify({'success': False, 'message': 'Profile is private'}), 404
        cursor.execute("""
            SELECT sb.*, a.icon, a.badge_icon, a.domain, a.difficulty
            FROM skill_badges sb
            JOIN assessments a ON sb.assessment_id = a.id
            WHERE sb.user_id = %s
            ORDER BY sb.score DESC, sb.earned_at DESC
        """, (candidate_id,))
        verified_badges = cursor.fetchall()

    completeness_data = evaluate_candidate_profile_completeness(candidate_id)
    completeness = completeness_data.get('score', 0)
    profile.pop('profile_photo', None)  # Don't expose file path via API
    return jsonify({'success': True, 'user': user, 'profile': profile, 'completeness': completeness, 'verified_badges': verified_badges})


@app.route('/api/candidate/profile/photo', methods=['POST'])
def api_upload_profile_photo():
    if 'user_id' not in session: return jsonify({'success': False}), 401
    if 'photo' not in request.files:
        return jsonify({'success': False, 'message': 'No file uploaded'}), 400
    file = request.files['photo']
    if not file or not file.filename:
        return jsonify({'success': False, 'message': 'No file selected'}), 400
    if not allowed_file(file.filename, ALLOWED_PHOTO_EXTENSIONS):
        return jsonify({'success': False, 'message': 'Invalid image format. Allowed: png, jpg, jpeg, gif, webp.'}), 400
    file.seek(0, os.SEEK_END)
    if file.tell() > MAX_UPLOAD_BYTES:
        return jsonify({'success': False, 'message': f'File too large (max {MAX_UPLOAD_MB}MB)'}), 400
    file.seek(0)
    file_type = imghdr.what(file)
    file.seek(0)
    if file_type is None:
        header = file.read(12)
        file.seek(0)
        if header[:4] == b'RIFF' and header[8:12] == b'WEBP':
            file_type = 'webp'
    if file_type not in ALLOWED_PHOTO_EXTENSIONS:
        return jsonify({'success': False, 'message': 'Invalid image format'}), 400
    file.seek(0)
    if not validate_file_signature(file, file.filename):
        return jsonify({'success': False, 'message': 'File content does not match its extension'}), 400
    file.seek(0)
    ext = os.path.splitext(file.filename)[1].lower()
    filename = f"user_{session['user_id']}_profile{ext}"
    upload_dir = os.path.join(app.root_path, 'static', 'uploads')
    os.makedirs(upload_dir, exist_ok=True)
    for old_ext in ALLOWED_PHOTO_EXTENSIONS:
        old = f"user_{session['user_id']}_profile.{old_ext}"
        old_path = os.path.join(upload_dir, old)
        if os.path.isfile(old_path) and old != filename:
            try:
                os.remove(old_path)
            except OSError:
                pass
    path = os.path.join(upload_dir, filename)
    file.save(path)
    with db_cursor() as cursor:
        cursor.execute("""
            INSERT INTO candidate_profile (user_id, profile_photo)
            VALUES (%s, %s)
            ON DUPLICATE KEY UPDATE profile_photo = VALUES(profile_photo)
        """, (session['user_id'], filename))
    return jsonify({'success': True, 'message': 'Photo uploaded', 'filename': filename})


@app.route('/api/candidate/profile/photo', methods=['DELETE'])
@app.route('/api/candidate/profile/photo/delete', methods=['POST'])
def api_delete_profile_photo():
    if 'user_id' not in session: return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    uid = session['user_id']
    upload_dir = os.path.join(app.root_path, 'static', 'uploads')
    for ext in ALLOWED_PHOTO_EXTENSIONS:
        photo_file = os.path.join(upload_dir, f"user_{uid}_profile.{ext}")
        if os.path.isfile(photo_file):
            try:
                os.remove(photo_file)
            except OSError:
                pass
    with db_cursor() as cursor:
        cursor.execute("UPDATE candidate_profile SET profile_photo = NULL WHERE user_id = %s", (uid,))
    return jsonify({'success': True, 'message': 'Profile photo removed'})


# --- USER ANALYTICS ---
@app.route('/api/user/analytics')
def api_user_analytics():
    if 'user_id' not in session: return jsonify({'success': False}), 401
    uid = session['user_id']
    with db_cursor() as cur:
        cur.execute("SELECT COUNT(*) AS total FROM applications WHERE user_id = %s", (uid,))
        total_apps = cur.fetchone()['total']
        cur.execute("SELECT COUNT(*) AS total FROM saved_jobs WHERE user_id = %s", (uid,))
        saved_jobs = cur.fetchone()['total']
        cur.execute("SELECT COUNT(*) AS total FROM applications WHERE user_id = %s AND status = 'Selected'", (uid,))
        selected = cur.fetchone()['total']
    response_rate = round((selected / total_apps * 100) if total_apps > 0 else 0, 1)
    return jsonify({'success': True, 'total_applications': total_apps, 'saved_jobs': saved_jobs, 'response_rate': response_rate})


# --- JOB ALERTS ---
@app.route('/api/job_alerts', methods=['GET'])
def api_get_job_alerts():
    if 'user_id' not in session: return jsonify({'success': False}), 401
    with db_cursor() as cur:
        cur.execute("SELECT * FROM job_alerts WHERE user_id = %s ORDER BY created_at DESC", (session['user_id'],))
        alerts = cur.fetchall()
    return jsonify({'success': True, 'alerts': alerts})

@app.route('/api/job_alerts', methods=['POST'])
def api_create_job_alert():
    if 'user_id' not in session: return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    data = request.json or {}
    keywords = data.get('keywords', '')
    frequency = data.get('frequency', 'daily')
    with db_cursor(dictionary=False) as cur:
        cur.execute("INSERT INTO job_alerts (user_id, keywords, frequency) VALUES (%s, %s, %s)",
                    (session['user_id'], keywords, frequency))
    return jsonify({'success': True, 'message': 'Alert created'})

@app.route('/api/job_alerts/<int:alert_id>', methods=['DELETE'])
def api_delete_job_alert(alert_id):
    if 'user_id' not in session: return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    with db_cursor(dictionary=False) as cur:
        cur.execute("DELETE FROM job_alerts WHERE id = %s AND user_id = %s", (alert_id, session['user_id']))
    return jsonify({'success': True, 'message': 'Alert deleted'})


# --- MATCHED JOBS ---
@app.route('/api/get_matched_jobs')
def api_get_matched_jobs():
    if 'user_id' not in session: return jsonify({'success': False}), 401
    with db_cursor() as cur:
        cur.execute("""
            SELECT j.*, COALESCE(e.company_name, j.company_name) AS company_name,
                   e.is_verified AS employer_is_verified, e.verification_status AS employer_verification_status
            FROM jobs j
            LEFT JOIN employee e ON j.employer_id = e.id
            WHERE j.is_active = 1 AND (j.application_deadline IS NULL OR j.application_deadline >= CURDATE())
        """)
        jobs = cur.fetchall()
    resume_path = None
    with db_cursor() as cur:
        cur.execute("SELECT resume_path FROM applications WHERE user_id = %s ORDER BY created_at DESC LIMIT 1", (session['user_id'],))
        row = cur.fetchone()
    if row and row.get('resume_path'):
        resume_path = row['resume_path']
    else:
        with db_cursor() as cur:
            cur.execute("SELECT general_resume_path FROM candidate_profile WHERE user_id = %s", (session['user_id'],))
            row = cur.fetchone()
        if row and row.get('general_resume_path'):
            resume_path = row['general_resume_path']
    if not resume_path:
        return jsonify({'success': True, 'jobs': []})
    full_path = os.path.join(app.config['UPLOAD_FOLDER'], resume_path)
    if not os.path.exists(full_path):
        return jsonify({'success': True, 'jobs': []})
    try:
        with open(full_path, 'rb') as f:
            content = extract_text(f, resume_path)
        skills = ['python', 'java', 'sql', 'html', 'css', 'javascript', 'flask', 'django', 'react', 'c++', 'management', 'marketing', 'sales']
        found = [s for s in skills if re.search(r'\b' + re.escape(s) + r'\b', content.lower())]
        ranked = []
        for job in jobs:
            if job['skills']:
                job_skills = [s.strip().lower() for s in job['skills'].split(',')]
                score = int(len(set(found) & set(job_skills)) / len(job_skills) * 100)
                if score > 0: ranked.append({**job, 'score': score})
        ranked.sort(key=lambda x: x['score'], reverse=True)
        return jsonify({'success': True, 'jobs': ranked, 'skills': found})
    except Exception:
        return jsonify({'success': True, 'jobs': []})


# --- CANDIDATE PROFILE ITEMS ---
@app.route('/api/candidate/skills/suggestions')
def api_candidate_skills_suggestions():
    if 'user_id' not in session: return jsonify({'success': False}), 401
    suggestions = ['Python', 'Java', 'SQL', 'HTML', 'CSS', 'JavaScript', 'Flask', 'Django', 'React', 'C++', 'Management', 'Marketing', 'Sales', 'Communication', 'Leadership', 'Problem Solving']
    return jsonify({'success': True, 'skills': suggestions})

def _format_db_row(row):
    """Formats database row values safely for JSON serialization."""
    if not row or not isinstance(row, dict):
        return row
    formatted = {}
    for k, v in row.items():
        if isinstance(v, (datetime, dt_date)):
            formatted[k] = v.strftime('%Y-%m-%d')
        elif isinstance(v, (bytes, bytearray)):
            formatted[k] = v.decode('utf-8', errors='ignore')
        else:
            formatted[k] = v
    return formatted

_PROFILE_DATE_COLS = {'start_date', 'end_date', 'issue_date', 'expiry_date', 'pub_date', 'present_date', 'patent_date', 'date_of_birth'}
_PROFILE_INT_COLS = {'team_size', 'year', 'last_used_year', 'experience_years', 'experience_months'}
_PROFILE_BOOL_COLS = {'is_current', 'is_confidential', 'no_expiry', 'can_read', 'can_write', 'can_speak', 'open_to_relocate', 'physically_challenged'}

_PROFILE_FIELD_ALIASES = {
    'certification_name': 'name',
    'completion_id': 'certificate_id',
    'certificate_url': 'credential_url',
    'does_not_expire': 'no_expiry',
    'is_never_expire': 'no_expiry',
    'language_name': 'language',
    'achievement_title': 'title',
    'score': 'score_percentile',
    'current_role': 'current_job_role',
    'marks': 'grade_value',
    'cgpa': 'grade_value',
    'grade': 'grade_value',
    'institute_name': 'institute',
    'degree': 'course_degree',
    'passing_year': 'year_of_passing',
    'company': 'company_name',
    'designation': 'job_title',
    'organization': 'organization_name',
    'project_title': 'title',
    'client': 'client_name',
    'stipend_amount': 'stipend',
    'tech_stack': 'technology_tags',
    'technologies': 'technology_tags',
    'project_url': 'project_url',
    'project_link': 'project_url',
    'url': 'project_url',
    'link': 'project_url',
}

_PROFILE_ITEM_TABLES = {
    'key-skills': 'key_skills', 'key_skills': 'key_skills', 'skills': 'key_skills',
    'employment': 'employment', 'education': 'education',
    'it-skills': 'it_skills', 'it_skills': 'it_skills',
    'internships': 'internships', 'projects': 'projects',
    'online-profiles': 'online_profiles', 'online_profiles': 'online_profiles',
    'work-samples': 'work_samples', 'work_samples': 'work_samples',
    'certifications': 'certifications', 'accomplishments': 'certifications',
    'publications': 'publications', 'presentations': 'presentations', 'patents': 'patents',
    'competitive-exams': 'competitive_exams', 'competitive_exams': 'competitive_exams', 'exams': 'competitive_exams',
    'academic-achievements': 'academic_achievements', 'academic_achievements': 'academic_achievements', 'academic': 'academic_achievements',
    'languages': 'languages', 'preferred-locations': 'preferred_locations', 'preferred_locations': 'preferred_locations'
}

ALLOWED_COLUMNS = {
    'key-skills': ['skill_name', 'skill_type'],
    'key_skills': ['skill_name', 'skill_type'],
    'skills': ['skill_name', 'skill_type'],
    'employment': [
        'company_name', 'job_title', 'employment_type', 'department', 'is_current',
        'start_date', 'end_date', 'job_profile', 'skills_used', 'gross_salary',
        'notice_period',
    ],
    'education': [
        'education_level', 'institute', 'course_degree', 'specialization', 'course_type',
        'grading_system', 'grade_value', 'year_of_passing',
    ],
    'it-skills': ['skill_name', 'version', 'last_used_year', 'experience_years', 'experience_months', 'proficiency'],
    'it_skills': ['skill_name', 'version', 'last_used_year', 'experience_years', 'experience_months', 'proficiency'],
    'internships': [
        'organization_name', 'role_title', 'start_date', 'end_date', 'is_current',
        'stipend', 'project_details', 'skills_used',
    ],
    'projects': [
        'title', 'client_name', 'is_confidential', 'status', 'start_date', 'end_date',
        'role', 'team_size', 'project_details', 'technology_tags', 'project_url',
    ],
    'online-profiles': ['platform', 'profile_url'],
    'online_profiles': ['platform', 'profile_url'],
    'work-samples': ['title', 'url', 'description'],
    'work_samples': ['title', 'url', 'description'],
    'certifications': [
        'name', 'issuing_authority', 'certificate_id', 'issue_date', 'expiry_date',
        'no_expiry', 'credential_url',
    ],
    'accomplishments': [
        'name', 'issuing_authority', 'certificate_id', 'issue_date', 'expiry_date',
        'no_expiry', 'credential_url',
    ],
    'publications': ['title', 'publisher_journal', 'url', 'pub_date', 'description'],
    'presentations': ['title', 'url', 'present_date'],
    'patents': ['title', 'patent_office', 'status', 'patent_number', 'patent_date', 'url'],
    'competitive-exams': ['exam_name', 'score_percentile', 'rank', 'year'],
    'competitive_exams': ['exam_name', 'score_percentile', 'rank', 'year'],
    'exams': ['exam_name', 'score_percentile', 'rank', 'year'],
    'academic-achievements': ['title', 'description', 'year'],
    'academic_achievements': ['title', 'description', 'year'],
    'academic': ['title', 'description', 'year'],
    'languages': ['language', 'can_read', 'can_write', 'can_speak'],
    'preferred-locations': ['location'],
    'preferred_locations': ['location'],
}

def _clean_profile_input_fields(section, raw_data):
    """Maps field aliases, validates against allowed columns, and sanitizes types."""
    allowed = ALLOWED_COLUMNS.get(section, [])
    fields = {}
    for raw_k, raw_v in raw_data.items():
        if raw_k in ('section', 'id', 'user_id'):
            continue
        k = _PROFILE_FIELD_ALIASES.get(raw_k, raw_k)
        if k in allowed:
            fields[k] = raw_v
    if not fields:
        return None, "No valid fields provided for section"
    
    clean_fields = {}
    for k, v in fields.items():
        if k in _PROFILE_DATE_COLS:
            if not v or str(v).strip() == '':
                clean_fields[k] = None
            else:
                try:
                    # Validate YYYY-MM-DD
                    datetime.strptime(str(v).strip()[:10], '%Y-%m-%d')
                    clean_fields[k] = str(v).strip()[:10]
                except Exception:
                    clean_fields[k] = None
        elif k in _PROFILE_INT_COLS:
            if v is None or str(v).strip() == '':
                clean_fields[k] = None
            else:
                try:
                    clean_fields[k] = int(v)
                except Exception:
                    clean_fields[k] = None
        elif k in _PROFILE_BOOL_COLS:
            clean_fields[k] = 1 if v in (True, 1, '1', 'true', 'True', 'on') else 0
        else:
            clean_fields[k] = sanitize_html(str(v).strip()) if isinstance(v, str) else v
    return clean_fields, None


# --- CANDIDATE PROFILE COMPREHENSIVE DATA (SINGLE CALL) ---
@app.route('/api/candidate/profile/all', methods=['GET'])
@app.route('/api/user/profile_full', methods=['GET'])
def api_get_all_candidate_profile():
    if 'user_id' not in session: return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    uid = session['user_id']
    try:
        with db_cursor() as cur:
            cur.execute("SELECT id, name, email, mobile, is_verified, created_at FROM user WHERE id = %s", (uid,))
            user_row = _format_db_row(cur.fetchone() or {})
            
            cur.execute("SELECT * FROM candidate_profile WHERE user_id = %s", (uid,))
            cand_prof = _format_db_row(cur.fetchone() or {})
            
            cur.execute("SELECT * FROM candidate_personal_details WHERE user_id = %s", (uid,))
            personal_row = _format_db_row(cur.fetchone() or {})
            
            cur.execute("SELECT * FROM candidate_preferences WHERE user_id = %s", (uid,))
            pref_row = _format_db_row(cur.fetchone() or {})
            if pref_row:
                if 'current_job_role' in pref_row:
                    pref_row['preferred_job_role'] = pref_row['current_job_role']
                if 'desired_employment_type' in pref_row:
                    pref_row['preferred_employment_type'] = pref_row['desired_employment_type']
                if 'current_industry' in pref_row:
                    pref_row['preferred_industry'] = pref_row['current_industry']
                if 'current_department' in pref_row:
                    pref_row['preferred_department'] = pref_row['current_department']
                if 'open_to_relocate' in pref_row:
                    pref_row['relocation_preference'] = pref_row['open_to_relocate']
            
            cur.execute("SELECT summary FROM candidate_profile_summary WHERE user_id = %s", (uid,))
            summary_row = _format_db_row(cur.fetchone() or {})
            
            tables_to_fetch = {
                'education': 'SELECT * FROM education WHERE user_id = %s ORDER BY id DESC',
                'employment': 'SELECT * FROM employment WHERE user_id = %s ORDER BY is_current DESC, id DESC',
                'key_skills': 'SELECT * FROM key_skills WHERE user_id = %s ORDER BY id ASC',
                'languages': 'SELECT * FROM languages WHERE user_id = %s ORDER BY id ASC',
                'internships': 'SELECT * FROM internships WHERE user_id = %s ORDER BY id DESC',
                'projects': 'SELECT * FROM projects WHERE user_id = %s ORDER BY id DESC',
                'certifications': 'SELECT * FROM certifications WHERE user_id = %s ORDER BY id DESC',
                'competitive_exams': 'SELECT * FROM competitive_exams WHERE user_id = %s ORDER BY id DESC',
                'academic_achievements': 'SELECT * FROM academic_achievements WHERE user_id = %s ORDER BY id DESC',
            }
            items_data = {}
            for key, q in tables_to_fetch.items():
                cur.execute(q, (uid,))
                items_data[key] = [_format_db_row(r) for r in cur.fetchall()]

        completeness = evaluate_candidate_profile_completeness(uid)
        key_skills_all = items_data.get('key_skills', [])
        technical_skills = [s for s in key_skills_all if (s.get('skill_type') or '').lower() != 'soft']
        soft_skills = [s for s in key_skills_all if (s.get('skill_type') or '').lower() == 'soft']
        response_data = {
            'user': user_row,
            'profile': cand_prof,
            'personal': personal_row,
            'preferences': pref_row,
            'summary': summary_row.get('summary', '') if summary_row else (cand_prof.get('summary', '') if cand_prof else ''),
            'items': items_data,
            'completeness': completeness,
            'education': items_data.get('education', []),
            'employment': items_data.get('employment', []),
            'key_skills': key_skills_all,
            'technical_skills': technical_skills,
            'soft_skills': soft_skills,
            'languages': items_data.get('languages', []),
            'internships': items_data.get('internships', []),
            'projects': items_data.get('projects', []),
            'certifications': items_data.get('certifications', []),
            'competitive_exams': items_data.get('competitive_exams', []),
            'academic_achievements': items_data.get('academic_achievements', []),
        }
        return jsonify({
            'success': True,
            'user': user_row,
            'profile': cand_prof,
            'personal': personal_row,
            'preferences': pref_row,
            'summary': summary_row.get('summary', '') if summary_row else (cand_prof.get('summary', '') if cand_prof else ''),
            'items': items_data,
            'completeness': completeness,
            'education': items_data.get('education', []),
            'employment': items_data.get('employment', []),
            'key_skills': key_skills_all,
            'technical_skills': technical_skills,
            'soft_skills': soft_skills,
            'languages': items_data.get('languages', []),
            'internships': items_data.get('internships', []),
            'projects': items_data.get('projects', []),
            'certifications': items_data.get('certifications', []),
            'competitive_exams': items_data.get('competitive_exams', []),
            'academic_achievements': items_data.get('academic_achievements', []),
            'data': response_data
        })
    except Exception as e:
        logger.error(f"Error fetching all candidate profile data for user {uid}: {e}")
        return jsonify({'success': False, 'message': 'Failed to load profile data'}), 500


@app.route('/api/candidate/profile/items', methods=['GET'])
def api_get_candidate_profile_items(section=None):
    if 'user_id' not in session: return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    section = section or request.args.get('section', '')
    table = _PROFILE_ITEM_TABLES.get(section)
    if not table:
        return jsonify({'success': True, 'items': []})
    with db_cursor() as cur:
        cur.execute(f"SELECT * FROM `{table}` WHERE user_id = %s ORDER BY id DESC", (session['user_id'],))
        items = [_format_db_row(r) for r in cur.fetchall()]
    return jsonify({'success': True, 'items': items})


@app.route('/api/candidate/profile/items', methods=['POST'])
@limiter.limit("60 per minute")
def api_create_candidate_profile_item(section=None):
    if 'user_id' not in session: return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    data = request.get_json(silent=True) or {}
    section = section or data.get('section', '')
    table = _PROFILE_ITEM_TABLES.get(section)
    if not table:
        return jsonify({'success': False, 'message': 'Invalid section'}), 400
    
    clean_fields, err = _clean_profile_input_fields(section, data)
    if err or not clean_fields:
        return jsonify({'success': False, 'message': err or 'No valid fields provided'}), 400

    # Prevent duplicate records for key_skills and languages
    if table == 'key_skills' and 'skill_name' in clean_fields:
        skill_name = clean_fields['skill_name'].strip()
        with db_cursor() as cur:
            cur.execute("SELECT id FROM key_skills WHERE user_id = %s AND LOWER(skill_name) = LOWER(%s)",
                        (session['user_id'], skill_name))
            if cur.fetchall():
                return jsonify({'success': False, 'message': f'Skill "{skill_name}" is already added to your profile'}), 400

    if table == 'languages' and 'language' in clean_fields:
        lang_name = clean_fields['language'].strip()
        with db_cursor() as cur:
            cur.execute("SELECT id FROM languages WHERE user_id = %s AND LOWER(language) = LOWER(%s)",
                        (session['user_id'], lang_name))
            if cur.fetchall():
                return jsonify({'success': False, 'message': f'Language "{lang_name}" is already in your profile'}), 400

    placeholders = ', '.join(['%s'] * len(clean_fields))
    columns = ', '.join([f"`{c}`" for c in clean_fields.keys()])
    values = list(clean_fields.values()) + [session['user_id']]
    with db_cursor(dictionary=False) as cur:
        cur.execute(f"INSERT INTO `{table}` ({columns}, `user_id`) VALUES ({placeholders}, %s)", values)
        item_id = cur.lastrowid
    trigger_async_match_refresh(session['user_id'])
    return jsonify({'success': True, 'message': 'Item added successfully', 'id': item_id, 'item_id': item_id})


@app.route('/api/candidate/profile/items/<int:item_id>', methods=['GET'])
def api_get_candidate_profile_item(item_id):
    if 'user_id' not in session: return jsonify({'success': False}), 401
    section = request.args.get('section', '')
    if section:
        table = _PROFILE_ITEM_TABLES.get(section)
        if not table:
            return jsonify({'success': False, 'message': 'Invalid section'}), 400
        tables = [table]
    else:
        tables = list(set(_PROFILE_ITEM_TABLES.values()))
    for table in tables:
        with db_cursor() as cur:
            cur.execute(f"SELECT * FROM `{table}` WHERE id = %s AND user_id = %s", (item_id, session['user_id']))
            item = cur.fetchone()
            if item:
                return jsonify({'success': True, 'item': _format_db_row(item)})
    return jsonify({'success': False, 'message': 'Item not found'}), 404


@app.route('/api/candidate/profile/items/<int:item_id>', methods=['PUT', 'POST'])
@limiter.limit("60 per minute")
def api_update_candidate_profile_item(item_id):
    if 'user_id' not in session: return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    data = request.get_json(silent=True) or {}
    section = data.get('section', '')
    table = _PROFILE_ITEM_TABLES.get(section)
    if not table:
        return jsonify({'success': False, 'message': 'Invalid section'}), 400
    
    clean_fields, err = _clean_profile_input_fields(section, data)
    if err or not clean_fields:
        return jsonify({'success': False, 'message': err or 'No valid fields provided'}), 400

    set_clause = ', '.join([f"`{k}` = %s" for k in clean_fields.keys()])
    values = list(clean_fields.values()) + [item_id, session['user_id']]
    with db_cursor(dictionary=False) as cur:
        cur.execute(f"UPDATE `{table}` SET {set_clause} WHERE id = %s AND user_id = %s", values)
    trigger_async_match_refresh(session['user_id'])
    return jsonify({'success': True, 'message': 'Item updated successfully'})


@app.route('/api/candidate/profile/items/<int:item_id>', methods=['DELETE'])
@limiter.limit("60 per minute")
def api_delete_candidate_profile_item(item_id):
    if 'user_id' not in session: return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    data = request.get_json(silent=True) or {}
    section = data.get('section', '') or request.args.get('section', '')
    table = _PROFILE_ITEM_TABLES.get(section)
    if not table:
        # Search all possible item tables for this ID and user_id
        for t in set(_PROFILE_ITEM_TABLES.values()):
            with db_cursor(dictionary=False) as cur:
                cur.execute(f"DELETE FROM `{t}` WHERE id = %s AND user_id = %s", (item_id, session['user_id']))
                if cur.rowcount > 0:
                    trigger_async_match_refresh(session['user_id'])
                    return jsonify({'success': True, 'message': 'Item deleted successfully'})
        return jsonify({'success': False, 'message': 'Item not found'}), 404
    
    with db_cursor(dictionary=False) as cur:
        cur.execute(f"DELETE FROM `{table}` WHERE id = %s AND user_id = %s", (item_id, session['user_id']))
    trigger_async_match_refresh(session['user_id'])
    return jsonify({'success': True, 'message': 'Item deleted successfully'})


# --- CANDIDATE PROFILE SINGLETONS (GET & POST) ---
@app.route('/api/candidate/profile/personal', methods=['GET'])
@app.route('/api/user/personal', methods=['GET'])
def api_get_candidate_personal():
    if 'user_id' not in session: return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    with db_cursor() as cur:
        cur.execute("SELECT * FROM candidate_personal_details WHERE user_id = %s", (session['user_id'],))
        row = _format_db_row(cur.fetchone() or {})
        cur.execute("SELECT headline FROM candidate_profile WHERE user_id = %s", (session['user_id'],))
        prof = cur.fetchone()
        if prof and prof.get('headline'):
            row['headline'] = prof['headline']
    return jsonify({'success': True, 'personal': row, 'data': row})


@app.route('/api/candidate/profile/personal', methods=['POST'])
@app.route('/api/user/personal', methods=['POST'])
@limiter.limit("30 per minute")
def api_update_candidate_personal():
    if 'user_id' not in session: return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    data = request.get_json(silent=True) or {}
    
    # Update candidate_profile headline if present
    if 'headline' in data:
        headline = sanitize_html(str(data['headline']).strip())
        with db_cursor(dictionary=False) as cur:
            cur.execute("INSERT INTO candidate_profile (user_id, headline) VALUES (%s, %s) ON DUPLICATE KEY UPDATE headline = %s", (session['user_id'], headline, headline))

    # Map field aliases
    if 'address' in data and 'permanent_address' not in data:
        data['permanent_address'] = data['address']
    if 'dob' in data and 'date_of_birth' not in data:
        data['date_of_birth'] = data['dob']

    fields = {k: v for k, v in data.items() if k in ('date_of_birth', 'gender', 'marital_status', 'nationality', 'current_location', 'hometown', 'permanent_address', 'pincode', 'physically_challenged', 'work_permit_countries')}
    if not fields and 'headline' not in data:
        return jsonify({'success': False, 'message': 'No valid fields provided'}), 400
    
    if fields:
        # Validate & format date_of_birth
        if 'date_of_birth' in fields:
            if not fields['date_of_birth'] or str(fields['date_of_birth']).strip() == '':
                fields['date_of_birth'] = None
            else:
                try:
                    datetime.strptime(str(fields['date_of_birth']).strip()[:10], '%Y-%m-%d')
                    fields['date_of_birth'] = str(fields['date_of_birth']).strip()[:10]
                except Exception:
                    return jsonify({'success': False, 'message': 'date_of_birth must be YYYY-MM-DD'}), 400
                    
        if 'pincode' in fields and fields['pincode']:
            if not re.fullmatch(r'[0-9]{4,10}', str(fields['pincode']).strip()):
                return jsonify({'success': False, 'message': 'pincode must be 4-10 digits'}), 400
                
        safe_fields = {}
        for k, v in fields.items():
            if k == 'date_of_birth':
                safe_fields[k] = v
            elif k == 'physically_challenged':
                safe_fields[k] = 1 if v in (True, 1, '1', 'true', 'True', 'on') else 0
            else:
                safe_fields[k] = sanitize_html(str(v).strip()) if isinstance(v, str) else v
                
        set_clause = ', '.join([f"{k} = %s" for k in safe_fields.keys()])
        values = list(safe_fields.values()) + [session['user_id']]
        with db_cursor(dictionary=False) as cur:
            cur.execute(f"INSERT INTO candidate_personal_details (user_id, {', '.join(safe_fields.keys())}) VALUES (%s, {', '.join(['%s'] * len(safe_fields))}) ON DUPLICATE KEY UPDATE {set_clause}", [session['user_id']] + values[:-1] + values[:-1])
    
    trigger_async_match_refresh(session['user_id'])
    return jsonify({'success': True, 'message': 'Personal details saved successfully'})


@app.route('/api/candidate/profile/preferences', methods=['GET'])
@app.route('/api/user/preferences', methods=['GET'])
def api_get_candidate_preferences():
    if 'user_id' not in session: return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    with db_cursor() as cur:
        cur.execute("SELECT * FROM candidate_preferences WHERE user_id = %s", (session['user_id'],))
        row = _format_db_row(cur.fetchone() or {})
        if row:
            if 'current_job_role' in row:
                row['preferred_job_role'] = row['current_job_role']
            if 'current_industry' in row:
                row['preferred_industry'] = row['current_industry']
            if 'current_department' in row:
                row['preferred_department'] = row['current_department']
            if 'desired_employment_type' in row:
                row['preferred_employment_type'] = row['desired_employment_type']
            if 'open_to_relocate' in row:
                row['relocation_preference'] = row['open_to_relocate']
    return jsonify({'success': True, 'preferences': row, 'data': row})


@app.route('/api/candidate/profile/preferences', methods=['POST'])
@app.route('/api/user/preferences', methods=['POST'])
@limiter.limit("30 per minute")
def api_update_candidate_preferences():
    if 'user_id' not in session: return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    data = request.get_json(silent=True) or {}
    pref_alias = {
        'preferred_job_role': 'current_job_role',
        'current_role': 'current_job_role',
        'preferred_industry': 'current_industry',
        'preferred_department': 'current_department',
        'preferred_employment_type': 'desired_employment_type',
        'relocation_preference': 'open_to_relocate',
        'workplace_preference': 'workplace_type',
        'preferred_work_type': 'workplace_type',
        'work_mode': 'workplace_type',
    }
    remapped_data = {}
    for k, v in data.items():
        target = pref_alias.get(k, k)
        if target not in remapped_data:
            remapped_data[target] = v

    fields = {k: v for k, v in remapped_data.items() if k in (
        'current_industry', 'current_department', 'current_job_role',
        'desired_job_type', 'desired_employment_type', 'preferred_shift',
        'current_ctc', 'expected_ctc', 'notice_period', 'open_to_relocate',
        'preferred_location', 'workplace_type'
    )}
    if not fields:
        return jsonify({'success': False, 'message': 'No valid fields provided'}), 400
        
    safe_fields = {}
    for k, v in fields.items():
        if k == 'open_to_relocate':
            safe_fields[k] = 1 if v in (True, 1, '1', 'true', 'True', 'on') else 0
        else:
            safe_fields[k] = sanitize_html(str(v).strip()) if isinstance(v, str) else v

    set_clause = ', '.join([f"`{k}` = %s" for k in safe_fields.keys()])
    values = list(safe_fields.values()) + [session['user_id']]
    with db_cursor(dictionary=False) as cur:
        cur.execute(f"INSERT INTO candidate_preferences (user_id, {', '.join(safe_fields.keys())}) VALUES (%s, {', '.join(['%s'] * len(safe_fields))}) ON DUPLICATE KEY UPDATE {set_clause}", [session['user_id']] + values[:-1] + values[:-1])
    
    trigger_async_match_refresh(session['user_id'])
    return jsonify({'success': True, 'message': 'Career preferences saved successfully'})


@app.route('/api/candidate/profile/summary', methods=['GET'])
@app.route('/api/user/summary', methods=['GET'])
def api_get_candidate_summary():
    if 'user_id' not in session: return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    with db_cursor() as cur:
        cur.execute("SELECT summary FROM candidate_profile_summary WHERE user_id = %s", (session['user_id'],))
        row = cur.fetchone() or {}
        summary = row.get('summary', '')
        if not summary:
            cur.execute("SELECT summary FROM candidate_profile WHERE user_id = %s", (session['user_id'],))
            row2 = cur.fetchone() or {}
            summary = row2.get('summary', '')
    return jsonify({'success': True, 'summary': summary or '', 'data': {'summary': summary or ''}})


@app.route('/api/candidate/profile/summary', methods=['POST'])
@app.route('/api/user/summary', methods=['POST'])
@limiter.limit("30 per minute")
def api_update_candidate_summary():
    if 'user_id' not in session: return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    data = request.get_json(silent=True) or {}
    summary = bleach.clean(str(data.get('summary', '')).strip(), tags=[], strip=True)
    with db_cursor(dictionary=False) as cur:
        cur.execute("INSERT INTO candidate_profile_summary (user_id, summary) VALUES (%s, %s) ON DUPLICATE KEY UPDATE summary = %s", (session['user_id'], summary, summary))
        cur.execute("UPDATE candidate_profile SET summary = %s WHERE user_id = %s", (summary, session['user_id']))
    
    trigger_async_match_refresh(session['user_id'])
    return jsonify({'success': True, 'message': 'Profile summary saved successfully'})


# --- SECTION REST ALIASES ---
@app.route('/api/user/education', methods=['GET', 'POST'])
def api_user_education_route():
    if request.method == 'GET':
        return api_get_candidate_profile_items(section='education')
    return api_create_candidate_profile_item(section='education')

@app.route('/api/user/employment', methods=['GET', 'POST'])
def api_user_employment_route():
    if request.method == 'GET':
        return api_get_candidate_profile_items(section='employment')
    return api_create_candidate_profile_item(section='employment')

@app.route('/api/user/skills', methods=['GET', 'POST'])
def api_user_skills_route():
    if request.method == 'GET':
        return api_get_candidate_profile_items(section='key_skills')
    return api_create_candidate_profile_item(section='key_skills')

@app.route('/api/user/languages', methods=['GET', 'POST'])
def api_user_languages_route():
    if request.method == 'GET':
        return api_get_candidate_profile_items(section='languages')
    return api_create_candidate_profile_item(section='languages')

@app.route('/api/user/internships', methods=['GET', 'POST'])
def api_user_internships_route():
    if request.method == 'GET':
        return api_get_candidate_profile_items(section='internships')
    return api_create_candidate_profile_item(section='internships')

@app.route('/api/user/projects', methods=['GET', 'POST'])
def api_user_projects_route():
    if request.method == 'GET':
        return api_get_candidate_profile_items(section='projects')
    return api_create_candidate_profile_item(section='projects')

@app.route('/api/user/certifications', methods=['GET', 'POST'])
def api_user_certifications_route():
    if request.method == 'GET':
        return api_get_candidate_profile_items(section='certifications')
    return api_create_candidate_profile_item(section='certifications')

@app.route('/api/user/exams', methods=['GET', 'POST'])
def api_user_exams_route():
    if request.method == 'GET':
        return api_get_candidate_profile_items(section='competitive_exams')
    return api_create_candidate_profile_item(section='competitive_exams')

@app.route('/api/user/academic', methods=['GET', 'POST'])
def api_user_academic_route():
    if request.method == 'GET':
        return api_get_candidate_profile_items(section='academic_achievements')
    return api_create_candidate_profile_item(section='academic_achievements')


@app.route('/api/candidate/profile/resume', methods=['POST'])
def api_upload_candidate_resume():
    if 'user_id' not in session: return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    if 'resume' not in request.files: return jsonify({'success': False, 'message': 'No file uploaded'}), 400
    file = request.files['resume']
    if not file or not file.filename:
        return jsonify({'success': False, 'message': 'No file selected'}), 400
    if not allowed_file(file.filename):
        return jsonify({'success': False, 'message': 'Invalid file type. Allowed: txt, pdf, doc, docx.'}), 400
    file.seek(0, os.SEEK_END)
    if file.tell() > MAX_UPLOAD_BYTES:
        return jsonify({'success': False, 'message': f'File too large (max {MAX_UPLOAD_MB}MB)'}), 400
    file.seek(0)
    if not validate_file_signature(file, file.filename):
        return jsonify({'success': False, 'message': 'File content does not match its extension. Possible corruption.'}), 400
    file.seek(0)
    filename = secure_filename(file.filename)
    filename = f"{uuid.uuid4().hex}_{filename}"
    user_resume_dir = os.path.join(app.config['UPLOAD_FOLDER'], 'resumes', str(session['user_id']))
    os.makedirs(user_resume_dir, exist_ok=True)
    file_path = os.path.join(user_resume_dir, filename)
    file.save(file_path)
    relative_path = os.path.join('resumes', str(session['user_id']), filename)
    file.seek(0)
    content = extract_text(io.BytesIO(file.read()), file.filename)
    skills = ['python', 'java', 'sql', 'html', 'css', 'javascript', 'flask', 'django', 'react', 'c++', 'management', 'marketing', 'sales']
    found = [s for s in skills if re.search(r'\b' + re.escape(s) + r'\b', content.lower())]
    with db_cursor() as cursor:
        cursor.execute("SELECT user_id FROM candidate_profile WHERE user_id = %s", (session['user_id'],))
        if cursor.fetchone():
            cursor.execute("UPDATE candidate_profile SET general_resume_path = %s WHERE user_id = %s", (relative_path, session['user_id']))
        else:
            cursor.execute("INSERT INTO candidate_profile (user_id, general_resume_path) VALUES (%s, %s)", (session['user_id'], relative_path))
    return jsonify({'success': True, 'skills': found, 'resume_path': relative_path, 'message': 'Resume uploaded successfully'})


# (Admin API endpoints are consolidated under the unified Admin Moderation & Verification section below)


# --- ERROR HANDLERS (zero traceback / SQL leak to clients) ---
@app.errorhandler(CSRFError)
def handle_csrf_error(e):
    logger.warning(f"CSRF validation failed on {request.path}: {e}")
    return jsonify({'success': False, 'message': 'CSRF token missing or invalid'}), 400


@app.errorhandler(500)
def handle_500_error(e):
    logger.error(f"Internal server error on {request.path}: {e}", exc_info=True)
    return jsonify({'success': False, 'message': 'An internal server error occurred'}), 500


@app.errorhandler(413)
def request_entity_too_large(e):
    logger.warning(f"File upload exceeded maximum payload size on {request.path}")
    return jsonify({'success': False, 'message': 'File upload too large.'}), 413


@app.errorhandler(429)
def ratelimit_handler(e):
    logger.warning(f"Rate limit exceeded on {request.path} from IP {request.remote_addr}")
    return jsonify({'success': False, 'message': 'Rate limit exceeded. Please try again later.'}), 429


@app.errorhandler(403)
def forbidden_handler(e):
    logger.warning(f"Access forbidden on {request.path} for user_id={session.get('user_id')} employer_id={session.get('employer_id')}")
    if request.is_json or request.path.startswith('/api/') or request.headers.get('Accept') == 'application/json':
        return jsonify({'success': False, 'message': 'Forbidden: Access denied'}), 403
    return redirect(url_for('index'))


@app.errorhandler(404)
def not_found_handler(e):
    if request.is_json or request.path.startswith('/api/') or request.headers.get('Accept') == 'application/json':
        return jsonify({'success': False, 'message': 'Resource not found'}), 404
    return render_template('job_not_found.html', job_id=''), 404


@app.errorhandler(400)
def bad_request_handler(e):
    logger.warning(f"Bad request on {request.path}: {e}")
    return jsonify({'success': False, 'message': 'Bad request.'}), 400


# --- PUBLIC PAGES ---
@app.route('/companies')
def companies_page():
    return render_template('companies.html')

def parse_job_description_sections(job):
    """
    Decomposes job into structured sections: description, responsibilities, requirements,
    skills, benefits, and company information for mobile hierarchy.
    """
    raw_desc = (job.get('description') or '').strip()
    lines = [l.strip() for l in raw_desc.split('\n') if l.strip()]

    sections = {
        'overview': [],
        'responsibilities': [],
        'requirements': [],
        'benefits': []
    }

    current_sec = 'overview'

    resp_pat = re.compile(r'^(?:key\s+)?responsibilities|what\s+you(?:\'ll|\s+will)\s+do|duties|roles?\s+and\s+responsibilities', re.I)
    req_pat = re.compile(r'^(?:minimum\s+|core\s+)?requirements|qualifications|what\s+you(?:\'ll|\s+will)\s+need|who\s+you\s+are|must\s+have', re.I)
    ben_pat = re.compile(r'^(?:what\s+we\s+offer|benefits|perks|compensation\s+&\s+benefits)', re.I)

    for line in lines:
        cleaned = line.rstrip(':').strip()
        if resp_pat.match(cleaned) and len(cleaned) < 50:
            current_sec = 'responsibilities'
            continue
        elif req_pat.match(cleaned) and len(cleaned) < 50:
            current_sec = 'requirements'
            continue
        elif ben_pat.match(cleaned) and len(cleaned) < 50:
            current_sec = 'benefits'
            continue

        sections[current_sec].append(line)

    overview_text = '\n'.join(sections['overview']).strip()
    resp_text = '\n'.join(sections['responsibilities']).strip()
    req_text = '\n'.join(sections['requirements']).strip()
    ben_text = '\n'.join(sections['benefits']).strip()

    # Smart fallbacks when sections are not explicitly separated in the raw text
    if not overview_text:
        overview_text = raw_desc or "Join our high-performing team to build impactful solutions and drive key business outcomes in this role."

    if not resp_text:
        resp_text = (
            f"• Deliver high-impact deliverables aligned with the {job.get('title', 'role')} objectives.\n"
            f"• Collaborate with cross-functional teams, engineering partners, and stakeholders.\n"
            f"• Ensure quality execution, adherence to industry standards, and continuous improvement.\n"
            f"• Own and execute end-to-end tasks with accountability and technical rigor."
        )

    if not req_text:
        exp = job.get('experience') or 'Relevant industry experience'
        edu = job.get('education') or 'Bachelor’s degree in a relevant field or equivalent practical experience'
        req_text = (
            f"• Experience: {exp}\n"
            f"• Education: {edu}\n"
            f"• Strong analytical and problem-solving capabilities.\n"
            f"• Demonstrated track record of successful execution and proactive collaboration."
        )

    if not ben_text:
        salary_str = job.get('salary') or job.get('salary_display') or 'Competitive compensation package'
        work_mode = job.get('work_mode') or 'Flexible'
        ben_text = (
            f"• Compensation: {salary_str} with performance incentives.\n"
            f"• Workplace: {work_mode} work model with modern digital infrastructure.\n"
            f"• Comprehensive health and wellness coverage.\n"
            f"• Paid time off, professional development opportunities, and career advancement tracks."
        )

    company_info = {
        'name': job.get('company_name') or 'Verified Employer',
        'industry': job.get('company_industry') or job.get('category') or 'Technology & Services',
        'size': job.get('company_size') or '50-500 Employees',
        'headquarters': job.get('company_location') or job.get('location') or 'Global Hub',
        'website': job.get('company_website') or '',
        'description': job.get('company_description') or f"{job.get('company_name', 'This employer')} is a forward-thinking organization committed to innovation, customer impact, and empowering employees."
    }

    return {
        'description': overview_text,
        'responsibilities': resp_text,
        'requirements': req_text,
        'benefits': ben_text,
        'company_info': company_info
    }


@app.route('/job_details/<int:job_id>', strict_slashes=False)
@app.route('/job-detail/<int:job_id>', strict_slashes=False)
@app.route('/job_detail/<int:job_id>', strict_slashes=False)
@app.route('/jobs/<int:job_id>', strict_slashes=False)
@app.route('/job/<int:job_id>', strict_slashes=False)
def job_detail_page(job_id):
    with db_cursor() as cursor:
        cursor.execute("""
            SELECT j.*, e.company_name AS live_company_name, e.is_verified AS employer_is_verified,
                   e.verification_status AS employer_verification_status,
                   e.company_website, e.industry AS company_industry, e.location AS company_location,
                   e.company_size, e.description AS company_description
            FROM jobs j
            LEFT JOIN employee e ON j.employer_id = e.id
            WHERE j.id = %s
        """, (job_id,))
        job = cursor.fetchone()

    if not job:
        return render_template('job_not_found.html', job_id=job_id), 404

    if job.get('live_company_name'):
        job['company_name'] = job['live_company_name']

    enrich_job_presentation(job)

    # Format salary if needed
    if not job.get('salary') and (job.get('salary_min') or job.get('salary_max')):
        s_min = f"₹{job['salary_min']:,}" if job.get('salary_min') else ''
        s_max = f"₹{job['salary_max']:,}" if job.get('salary_max') else ''
        job['salary'] = f"{s_min} - {s_max}" if (s_min and s_max) else (s_min or s_max)

    # Decompose job sections for mobile structured view
    job_sections = parse_job_description_sections(job)

    # Check if current user is the employer who owns this job
    is_owner = False
    applicant_count = 0
    if 'employer_id' in session and session['employer_id'] == job.get('employer_id'):
        is_owner = True
        with db_cursor() as cursor:
            cursor.execute("SELECT COUNT(*) AS total FROM applications WHERE job_id = %s", (job_id,))
            count_row = cursor.fetchone()
            applicant_count = count_row['total'] if count_row else 0

    user_has_applied = False
    user_has_saved = False
    if 'user_id' in session:
        uid = session['user_id']
        with db_cursor() as cursor:
            cursor.execute("SELECT id FROM applications WHERE user_id = %s AND job_id = %s", (uid, job_id))
            user_has_applied = bool(cursor.fetchone())
            cursor.execute("SELECT id FROM saved_jobs WHERE user_id = %s AND job_id = %s", (uid, job_id))
            user_has_saved = bool(cursor.fetchone())

    # Check if job deadline is passed
    is_expired = False
    if job.get('application_deadline'):
        try:
            d_val = job['application_deadline']
            if isinstance(d_val, str):
                d_date = datetime.strptime(d_val, '%Y-%m-%d').date()
            elif hasattr(d_val, 'date'):
                d_date = d_val.date()
            elif isinstance(d_val, dt_date):
                d_date = d_val
            else:
                d_date = None
            if d_date and d_date < datetime.now().date():
                is_expired = True
        except Exception:
            pass

    return render_template(
        'job_detail.html',
        job=job,
        job_sections=job_sections,
        is_owner=is_owner,
        is_expired=is_expired,
        applicant_count=applicant_count,
        user_has_applied=user_has_applied,
        user_has_saved=user_has_saved
    )


@app.route('/job', strict_slashes=False)
def job_index_redirect():
    """Gracefully redirects /job or /job?id=123 to the canonical destination."""
    jid = request.args.get('id') or request.args.get('job_id')
    if jid:
        try:
            return redirect(url_for('job_detail_page', job_id=int(jid)))
        except (ValueError, TypeError):
            pass
    return redirect(url_for('jobs_listing'))


@app.route('/jobs', strict_slashes=False)
def jobs_listing():
    data = request.args.to_dict()
    result = execute_jobs_query(data)
    return render_template(
        'jobs.html',
        jobs=result['jobs'],
        page=result['page'],
        per_page=result['per_page'],
        total=result['total'],
        total_pages=result['total_pages'],
        sort=result['sort'],
        filters_applied=result['filters_applied']
    )

@app.route('/company/<int:company_id>')
def company_detail_page(company_id):
    return render_template('company_detail.html')

@app.route('/services')
def services_page():
    return render_template('services.html')

@app.route('/services/job-seekers')
def services_job_seekers():
    return render_template('services.html')

@app.route('/services/employers')
def services_employers():
    return render_template('services.html')

@app.route('/salary-insights')
@app.route('/salary_insights')
@app.route('/salary_calculator')
@app.route('/salary-calculator')
def salary_insights_page():
    """Renders the interactive Salary Benchmark Insights page with comprehensive role and location libraries."""
    return render_template(
        'salary_insights.html',
        roles_by_category=ROLES_BY_CATEGORY,
        all_roles=ALL_JOB_ROLES,
        all_locations=ALL_LOCATIONS,
        location_metadata=LOCATION_METADATA,
        experience_bands=EXPERIENCE_BANDS,
        industries=INDUSTRIES
    )


@app.route('/api/salary_insights', methods=['GET', 'POST'])
@app.route('/api/salary-benchmarks', methods=['GET', 'POST'])
@app.route('/api/salary/insights', methods=['GET', 'POST'])
@limiter.limit("60 per minute")
def api_salary_insights():
    """Returns aggregated salary metrics, chart distributions, and benchmark table data."""
    if request.method == 'POST' and request.is_json:
        data = request.get_json(silent=True) or {}
    else:
        data = request.args.to_dict()

    role = data.get('role', '').strip()
    experience = data.get('experience', '').strip()
    location = data.get('location', '').strip()
    skill = data.get('skill', '').strip()
    industry = data.get('industry', '').strip()
    search = data.get('search', '').strip()
    sort_by = data.get('sort_by', 'avg_desc')
    min_salary = data.get('min_salary', '').strip()
    max_salary = data.get('max_salary', '').strip()

    where_clauses = ["1=1"]
    params = []

    if role:
        where_clauses.append("job_role = %s")
        params.append(role)
    if experience:
        where_clauses.append("experience_level = %s")
        params.append(experience)
    if location:
        # Check if location matches known cities or a state/country group in LOCATION_METADATA
        matched_locs = [k for k, meta in LOCATION_METADATA.items() if meta.get('state') == location or meta.get('country') == location]
        if matched_locs and location not in ALL_LOCATIONS:
            placeholders = ', '.join(['%s'] * len(matched_locs))
            where_clauses.append(f"location IN ({placeholders})")
            params.extend(matched_locs)
        else:
            where_clauses.append("location = %s")
            params.append(location)
    if skill:
        where_clauses.append("primary_technology = %s")
        params.append(skill)
    if industry:
        where_clauses.append("industry = %s")
        params.append(industry)
    if min_salary:
        try:
            min_val = float(min_salary)
            if min_val > 0:
                where_clauses.append("salary_avg >= %s")
                params.append(min_val)
        except (ValueError, TypeError):
            pass
    if max_salary:
        try:
            max_val = float(max_salary)
            if max_val > 0:
                where_clauses.append("salary_avg <= %s")
                params.append(max_val)
        except (ValueError, TypeError):
            pass
    if search:
        # Tokenize search query so multi-word searches (e.g. "python chennai", "data analyst bangalore")
        # match across multiple fields rather than requiring a single column to contain the full string
        tokens = [t.strip() for t in search.split() if t.strip()]
        for tok in tokens:
            where_clauses.append("(job_role LIKE %s OR location LIKE %s OR primary_technology LIKE %s OR industry LIKE %s OR experience_level LIKE %s)")
            like_term = f"%{tok}%"
            params.extend([like_term, like_term, like_term, like_term, like_term])

    where_sql = " AND ".join(where_clauses)

    with db_cursor() as cursor:
        cursor.execute(f"""
            SELECT id, job_role, experience_level, location, primary_technology, industry,
                   salary_min, salary_median, salary_avg, salary_max, sample_size, is_demo_data
            FROM salary_benchmarks
            WHERE {where_sql}
        """, tuple(params))
        rows = cursor.fetchall()

    if not rows:
        return jsonify({
            'success': True,
            'kpis': {
                'avg_salary': 0,
                'min_salary': 0,
                'max_salary': 0,
                'median_salary': 0,
                'total_datapoints': 0
            },
            'charts': {
                'by_role': {'labels': [], 'avg_salaries': [], 'median_salaries': []},
                'by_experience': {'labels': [], 'avg_salaries': [], 'min_salaries': [], 'max_salaries': []},
                'by_location': {'labels': [], 'avg_salaries': []},
                'by_skill': {'labels': [], 'avg_salaries': []},
                'distribution': {'labels': ['< ₹6 LPA', '₹6–12 LPA', '₹12–20 LPA', '₹20–35 LPA', '₹35+ LPA'], 'counts': [0, 0, 0, 0, 0]}
            },
            'table_data': [],
            'is_demo_data': True,
            'total_records': 0
        })

    # Overall KPIs
    all_avgs = [r['salary_avg'] for r in rows]
    all_mins = [r['salary_min'] for r in rows]
    all_maxs = [r['salary_max'] for r in rows]
    all_medians = [r['salary_median'] for r in rows]
    all_samples = sum(r.get('sample_size', 100) for r in rows)

    overall_avg = round(sum(all_avgs) / len(all_avgs), 1)
    overall_min = round(min(all_mins), 1)
    overall_max = round(max(all_maxs), 1)

    # Server-side Median Calculation
    sorted_medians = sorted(all_medians)
    n = len(sorted_medians)
    if n % 2 == 1:
        overall_median = round(sorted_medians[n // 2], 1)
    else:
        overall_median = round((sorted_medians[n // 2 - 1] + sorted_medians[n // 2]) / 2, 1)

    # 1. Chart: By Job Role
    role_map = {}
    for r in rows:
        ro = r['job_role']
        if ro not in role_map:
            role_map[ro] = {'avgs': [], 'medians': []}
        role_map[ro]['avgs'].append(r['salary_avg'])
        role_map[ro]['medians'].append(r['salary_median'])
    
    role_labels = []
    role_avgs = []
    role_medians = []
    for ro, v in sorted(role_map.items(), key=lambda x: sum(x[1]['avgs'])/len(x[1]['avgs']), reverse=True):
        role_labels.append(ro)
        role_avgs.append(round(sum(v['avgs']) / len(v['avgs']), 1))
        role_medians.append(round(sum(v['medians']) / len(v['medians']), 1))

    # 2. Chart: By Experience Bracket
    exp_order = ['0–1 Years', '1–3 Years', '3–5 Years', '5–8 Years', '8+ Years']
    exp_map = {e: {'avgs': [], 'mins': [], 'maxs': []} for e in exp_order}
    for r in rows:
        exp = r['experience_level']
        if exp in exp_map:
            exp_map[exp]['avgs'].append(r['salary_avg'])
            exp_map[exp]['mins'].append(r['salary_min'])
            exp_map[exp]['maxs'].append(r['salary_max'])
    
    exp_labels = []
    exp_avgs = []
    exp_mins = []
    exp_maxs = []
    for exp in exp_order:
        if exp_map[exp]['avgs']:
            exp_labels.append(exp)
            exp_avgs.append(round(sum(exp_map[exp]['avgs']) / len(exp_map[exp]['avgs']), 1))
            exp_mins.append(round(min(exp_map[exp]['mins']), 1))
            exp_maxs.append(round(max(exp_map[exp]['maxs']), 1))

    # 3. Chart: By Location
    loc_map = {}
    for r in rows:
        loc = r['location']
        if loc not in loc_map:
            loc_map[loc] = []
        loc_map[loc].append(r['salary_avg'])
    
    loc_labels = []
    loc_avgs = []
    for loc, vals in sorted(loc_map.items(), key=lambda x: sum(x[1])/len(x[1]), reverse=True):
        loc_labels.append(loc)
        loc_avgs.append(round(sum(vals) / len(vals), 1))

    # 4. Chart: By Skill / Technology
    skill_map = {}
    for r in rows:
        sk = r['primary_technology']
        if sk not in skill_map:
            skill_map[sk] = []
        skill_map[sk].append(r['salary_avg'])
    
    skill_labels = []
    skill_avgs = []
    for sk, vals in sorted(skill_map.items(), key=lambda x: sum(x[1])/len(x[1]), reverse=True):
        skill_labels.append(sk)
        skill_avgs.append(round(sum(vals) / len(vals), 1))

    # 5. Chart: Salary Range Distribution
    dist_counts = [0, 0, 0, 0, 0] # <6, 6-12, 12-20, 20-35, 35+
    for r in rows:
        avg = r['salary_avg']
        if avg < 6.0:
            dist_counts[0] += 1
        elif avg <= 12.0:
            dist_counts[1] += 1
        elif avg <= 20.0:
            dist_counts[2] += 1
        elif avg <= 35.0:
            dist_counts[3] += 1
        else:
            dist_counts[4] += 1

    # Table sorting
    if sort_by == 'avg_asc':
        rows.sort(key=lambda x: x['salary_avg'])
    elif sort_by == 'max_desc':
        rows.sort(key=lambda x: x['salary_max'], reverse=True)
    elif sort_by == 'min_desc':
        rows.sort(key=lambda x: x['salary_min'], reverse=True)
    elif sort_by == 'role_asc':
        rows.sort(key=lambda x: x['job_role'])
    else: # avg_desc
        rows.sort(key=lambda x: x['salary_avg'], reverse=True)

    return jsonify({
        'success': True,
        'kpis': {
            'avg_salary': overall_avg,
            'min_salary': overall_min,
            'max_salary': overall_max,
            'median_salary': overall_median,
            'total_datapoints': all_samples
        },
        'charts': {
            'by_role': {
                'labels': role_labels,
                'avg_salaries': role_avgs,
                'median_salaries': role_medians
            },
            'by_experience': {
                'labels': exp_labels,
                'avg_salaries': exp_avgs,
                'min_salaries': exp_mins,
                'max_salaries': exp_maxs
            },
            'by_location': {
                'labels': loc_labels,
                'avg_salaries': loc_avgs
            },
            'by_skill': {
                'labels': skill_labels,
                'avg_salaries': skill_avgs
            },
            'distribution': {
                'labels': ['< ₹6 LPA', '₹6–12 LPA', '₹12–20 LPA', '₹20–35 LPA', '₹35+ LPA'],
                'counts': dist_counts
            }
        },
        'table_data': rows,
        'is_demo_data': True,
        'total_records': len(rows)
    })


# --- RESUME INTELLIGENCE ROUTES ---
@app.route('/resume-intelligence')
@app.route('/resume_intelligence')
def resume_intelligence_page():
    return render_template('resume_intelligence.html')


@app.route('/api/resume_intelligence/analyze', methods=['POST'])
@limiter.limit("20 per minute")
def api_analyze_resume_intelligence():
    if 'resume' not in request.files:
        return jsonify({'success': False, 'message': 'Please upload a resume file (PDF or DOCX).'}), 400

    file = request.files['resume']
    if not file or not file.filename:
        return jsonify({'success': False, 'message': 'No file selected.'}), 400

    filename = secure_filename(file.filename)
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    if ext not in ['pdf', 'docx', 'txt']:
        return jsonify({'success': False, 'message': 'Invalid file format. Only PDF and DOCX documents are supported.'}), 400

    # Check file size (max 5MB)
    file.seek(0, os.SEEK_END)
    file_size = file.tell()
    file.seek(0)

    if file_size == 0:
        return jsonify({'success': False, 'message': 'The uploaded file is empty.'}), 400
    if file_size > 5 * 1024 * 1024:
        return jsonify({'success': False, 'message': 'File size exceeds maximum limit of 5MB.'}), 400

    # MIME / Magic bytes verification
    if not validate_file_signature(file.stream, filename):
        return jsonify({'success': False, 'message': 'Corrupted or unsupported file content.'}), 400

    try:
        # Extract optional job description
        job_description = (request.form.get('job_description') or request.form.get('jd_text') or '').strip()

        # Run intelligence analysis pipeline
        result = analyze_resume_pipeline(file.stream, filename, job_description=job_description)
        if not result.get('success'):
            return jsonify(result), 400

        # Save to disk in upload folder
        user_id = session.get('user_id')
        unique_name = f"intel_{uuid.uuid4().hex[:12]}_{int(time.time())}_{filename}"
        if user_id:
            save_dir = os.path.join(app.config['UPLOAD_FOLDER'], 'resumes', str(user_id))
            rel_path = os.path.join('resumes', str(user_id), unique_name)
        else:
            save_dir = os.path.join(app.config['UPLOAD_FOLDER'], 'resumes', 'guest')
            rel_path = os.path.join('resumes', 'guest', unique_name)

        os.makedirs(save_dir, exist_ok=True)
        file.seek(0)
        file.save(os.path.join(save_dir, unique_name))

        # Store analysis record in database
        try:
            with db_cursor(dictionary=False) as cur:
                cur.execute("""
                    INSERT INTO resume_analyses 
                    (user_id, filename, original_filename, file_path, file_size, ats_score, 
                     extracted_skills, detected_keywords, missing_keywords, sections_detected, 
                     score_breakdown, suggestions)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    user_id,
                    unique_name,
                    filename,
                    rel_path,
                    file_size,
                    result['ats_score'],
                    json.dumps(result['extracted_skills']),
                    json.dumps(result['detected_keywords']),
                    json.dumps(result['missing_keywords']),
                    json.dumps(result['sections_detected']),
                    json.dumps(result['score_breakdown']),
                    json.dumps(result['suggestions'])
                ))
                # If logged in user, also update candidate_profile general_resume_path & skills
                if user_id:
                    cur.execute("SELECT id FROM candidate_profile WHERE user_id = %s", (user_id,))
                    if cur.fetchone():
                        cur.execute("UPDATE candidate_profile SET general_resume_path = %s, skills = %s WHERE user_id = %s", (rel_path, ', '.join(result['extracted_skills']), user_id))
                    else:
                        cur.execute("INSERT INTO candidate_profile (user_id, general_resume_path, skills) VALUES (%s, %s, %s)", (user_id, rel_path, ', '.join(result['extracted_skills'])))
        except Exception as db_err:
            logger.error(f"Database error saving resume analysis: {db_err}")

        return jsonify(result)
    except Exception as err:
        logger.error(f"Resume analysis error: {err}")
        return jsonify({'success': False, 'message': 'An error occurred while analyzing the resume. Please try again.'}), 500


@app.route('/api/resume_intelligence/latest', methods=['GET'])
def api_get_latest_resume_analysis():
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'message': 'No authenticated session'}), 401
    try:
        with db_cursor() as cur:
            cur.execute("""
                SELECT * FROM resume_analyses 
                WHERE user_id = %s 
                ORDER BY created_at DESC LIMIT 1
            """, (user_id,))
            row = cur.fetchone()
        if not row:
            return jsonify({'success': False, 'message': 'No previous analysis found'})

        def safe_json(val, default):
            if not val: return default
            if isinstance(val, (dict, list)): return val
            try: return json.loads(val)
            except Exception: return default

        data = {
            'success': True,
            'filename': row.get('original_filename', 'Resume.pdf'),
            'ats_score': row.get('ats_score', 0),
            'extracted_skills': safe_json(row.get('extracted_skills'), []),
            'detected_keywords': safe_json(row.get('detected_keywords'), []),
            'missing_keywords': safe_json(row.get('missing_keywords'), []),
            'sections_detected': safe_json(row.get('sections_detected'), {}),
            'score_breakdown': safe_json(row.get('score_breakdown'), {}),
            'suggestions': safe_json(row.get('suggestions'), []),
            'created_at': row.get('created_at').strftime('%Y-%m-%d %H:%M') if row.get('created_at') else None
        }
        return jsonify(data)
    except Exception as e:
        logger.error(f"Error fetching latest resume analysis: {e}")
        return jsonify({'success': False, 'message': 'Error retrieving analysis'}), 500

@app.route('/forgot-password')
@app.route('/forgot_password')
def forgot_password_page():
    return render_template('forgot_password.html')

@app.route('/reset-password/<token>')
def reset_password_page(token):
    return render_template('forgot_password.html')

@app.route('/terms')
def terms_page():
    return render_template('index.html')

@app.route('/privacy')
def privacy_page():
    return render_template('index.html')

@app.route('/about')
def about_page():
    return render_template('index.html')

@app.route('/contact')
def contact_page():
    return render_template('index.html')

@app.route('/faq')
def faq_page():
    return render_template('index.html')

@app.route('/blog')
def blog_page():
    return render_template('index.html')

@app.route('/careers')
def careers_page():
    return render_template('index.html')

# --- CANDIDATE PAGES ---
@app.route('/candidate/dashboard')
def candidate_dashboard():
    if 'user_id' not in session: return redirect(url_for('index'))
    return redirect(url_for('user_dashboard'))

@app.route('/candidate/profile')
def candidate_profile():
    if 'user_id' not in session: return redirect(url_for('index'))
    return render_template('candidate_profile_edit.html')

@app.route('/candidate/profile/edit')
def candidate_profile_edit():
    if 'user_id' not in session: return redirect(url_for('index'))
    return render_template('candidate_profile_edit.html')

@app.route('/candidate/profile/photo')
def candidate_profile_photo():
    if 'user_id' not in session: return redirect(url_for('index'))
    return render_template('candidate_profile_edit.html')

@app.route('/candidate/resume')
def candidate_resume():
    if 'user_id' not in session: return redirect(url_for('index'))
    return render_template('candidate_resume.html')

@app.route('/candidate/resume/upload')
def candidate_resume_upload():
    if 'user_id' not in session: return redirect(url_for('index'))
    return render_template('candidate_resume.html')

@app.route('/candidate/resume/builder')
def candidate_resume_builder():
    if 'user_id' not in session: return redirect(url_for('index'))
    return render_template('candidate_resume.html')

@app.route('/candidate/resume/download')
def candidate_resume_download():
    if 'user_id' not in session: return redirect(url_for('index'))
    with db_cursor() as cur:
        cur.execute("SELECT general_resume_path FROM candidate_profile WHERE user_id = %s", (session['user_id'],))
        row = cur.fetchone()
    if not row or not row.get('general_resume_path'):
        return redirect(url_for('candidate_resume'))
    safe_path = secure_filename(row['general_resume_path'])
    try:
        return send_from_directory(app.config['UPLOAD_FOLDER'], safe_path, as_attachment=True)
    except FileNotFoundError:
        return redirect(url_for('candidate_resume'))

@app.route('/candidate/resume/parse')
def candidate_resume_parse():
    if 'user_id' not in session: return redirect(url_for('index'))
    with db_cursor() as cur:
        cur.execute("SELECT general_resume_path FROM candidate_profile WHERE user_id = %s", (session['user_id'],))
        row = cur.fetchone()
    if not row or not row.get('general_resume_path'):
        return redirect(url_for('candidate_resume'))
    resume_path = os.path.join(app.config['UPLOAD_FOLDER'], row['general_resume_path'])
    if not os.path.exists(resume_path):
        return redirect(url_for('candidate_resume'))
    with open(resume_path, 'rb') as f:
        content = extract_text(f, row['general_resume_path'])
    skills = ['python', 'java', 'sql', 'html', 'css', 'javascript', 'flask', 'django', 'react', 'c++', 'management', 'marketing', 'sales']
    found = [s for s in skills if re.search(r'\b' + s + r'\b', content.lower())]
    return jsonify({'success': True, 'skills': found, 'text_length': len(content)})

# ==============================================================================
# CANDIDATE SKILL ASSESSMENT ROUTES & APIS
# ==============================================================================

@app.route('/assessments')
@app.route('/candidate/assessments')
@app.route('/candidate_assessments')
@app.route('/candidate-assessments')
def candidate_assessments():
    """Renders the comprehensive 90+ skill assessment marketplace catalog."""
    user_id = session.get('user_id')
    user_badges = []
    user_attempts = {}
    if user_id:
        with db_cursor() as cursor:
            cursor.execute("SELECT * FROM skill_badges WHERE user_id = %s ORDER BY score DESC, earned_at DESC", (user_id,))
            user_badges = cursor.fetchall()
            cursor.execute("""
                SELECT assessment_id, score, passed, completed_at, id as attempt_id, status
                FROM assessment_attempts 
                WHERE user_id = %s
                ORDER BY completed_at DESC, id DESC
            """, (user_id,))
            attempts = cursor.fetchall()
            for att in attempts:
                aid = att['assessment_id']
                if aid not in user_attempts:
                    user_attempts[aid] = {
                        'assessment_id': aid,
                        'best_score': att['score'] or 0,
                        'last_score': att['score'] or 0,
                        'passed': bool(att['passed']),
                        'completed_at': att['completed_at'],
                        'attempt_id': att['attempt_id'],
                        'status': att['status'],
                        'attempt_count': 1
                    }
                else:
                    user_attempts[aid]['attempt_count'] += 1
                    if (att['score'] or 0) > user_attempts[aid]['best_score']:
                        user_attempts[aid]['best_score'] = att['score'] or 0
                    if att['passed']:
                        user_attempts[aid]['passed'] = True

    with db_cursor() as cursor:
        cursor.execute("""
            SELECT a.*, COUNT(att.id) AS total_attempts
            FROM assessments a
            LEFT JOIN assessment_attempts att ON a.id = att.assessment_id
            GROUP BY a.id
            ORDER BY a.domain ASC, a.category ASC, a.id ASC
        """)
        assessments_list = cursor.fetchall()

    # Precalculate domain counts mapping from actual catalog data
    domain_counts = {}
    for a in assessments_list:
        dom = a.get('domain') or 'Technical'
        domain_counts[dom] = domain_counts.get(dom, 0) + 1

    return render_template(
        'candidate_assessments.html',
        assessments=assessments_list,
        user_badges=user_badges,
        user_attempts=user_attempts,
        domain_counts=domain_counts,
        total_assessments_count=len(assessments_list)
    )


@app.route('/api/candidate/assessments')
def api_candidate_assessments():
    """Returns JSON list of assessments with filtering and candidate progress."""
    search = request.args.get('search', '').strip().lower()
    domain = request.args.get('domain', '').strip()
    category = request.args.get('category', '').strip()
    difficulty = request.args.get('difficulty', '').strip()
    sort = request.args.get('sort', 'default').strip()

    user_id = session.get('user_id')
    user_badges = set()
    user_attempts = {}
    if user_id:
        with db_cursor() as cursor:
            cursor.execute("SELECT skill_name FROM skill_badges WHERE user_id = %s", (user_id,))
            user_badges = {b['skill_name'] for b in cursor.fetchall()}
            cursor.execute("""
                SELECT assessment_id, MAX(score) as best_score, MAX(passed) as passed, COUNT(id) as attempt_count
                FROM assessment_attempts WHERE user_id = %s GROUP BY assessment_id
            """, (user_id,))
            for att in cursor.fetchall():
                user_attempts[att['assessment_id']] = att

    with db_cursor() as cursor:
        query = """
            SELECT a.*, COUNT(att.id) AS total_attempts
            FROM assessments a
            LEFT JOIN assessment_attempts att ON a.id = att.assessment_id
            WHERE 1=1
        """
        params = []
        if domain and domain.lower() != 'all':
            d_low = domain.lower()
            if d_low in ('web dev', 'web development'):
                query += " AND (LOWER(a.domain) = 'web dev' OR LOWER(a.domain) = 'web development')"
            elif d_low in ('business skills', 'business & professional skills'):
                query += " AND (LOWER(a.domain) = 'business skills' OR LOWER(a.domain) = 'business & professional skills')"
            else:
                query += " AND LOWER(a.domain) = %s"
                params.append(d_low)
        if category and category.lower() != 'all':
            query += " AND a.category = %s"
            params.append(category)
        if difficulty and difficulty.lower() != 'all':
            query += " AND a.difficulty = %s"
            params.append(difficulty)
        if search:
            query += " AND (LOWER(a.title) LIKE %s OR LOWER(a.category) LIKE %s OR LOWER(a.description) LIKE %s)"
            params.extend([f"%{search}%", f"%{search}%", f"%{search}%"])

        query += " GROUP BY a.id"

        if sort == 'popular':
            query += " ORDER BY total_attempts DESC, a.is_popular DESC, a.rating DESC, a.id ASC"
        elif sort == 'new':
            query += " ORDER BY a.created_at DESC, a.id DESC"
        elif sort == 'rating':
            query += " ORDER BY a.rating DESC, a.id ASC"
        elif sort == 'alpha':
            query += " ORDER BY a.title ASC"
        else:
            query += " ORDER BY a.domain ASC, a.category ASC, a.id ASC"

        cursor.execute(query, tuple(params))
        tests = cursor.fetchall()

    result_list = []
    for t in tests:
        tid = t['id']
        att = user_attempts.get(tid, {})
        has_badge = t['category'] in user_badges or bool(att.get('passed'))
        result_list.append({
            'id': tid,
            'title': t['title'],
            'category': t['category'],
            'domain': t.get('domain', 'Technical'),
            'difficulty': t['difficulty'],
            'description': t['description'],
            'time_limit_minutes': t['time_limit_minutes'],
            'passing_score': t['passing_score'],
            'questions_count': t['questions_count'],
            'icon': t['icon'],
            'badge_icon': t['badge_icon'],
            'rating': float(t.get('rating') or 4.85),
            'is_popular': bool(t.get('is_popular')),
            'is_new': bool(t.get('is_new')),
            'total_attempts': int(t.get('total_attempts') or 0),
            'created_at': t['created_at'].strftime('%Y-%m-%d %H:%M:%S') if t.get('created_at') else None,
            'best_score': att.get('best_score'),
            'attempt_count': att.get('attempt_count', 0),
            'passed': bool(att.get('passed')),
            'has_badge': has_badge
        })

    return jsonify({
        'success': True,
        'count': len(result_list),
        'assessments': result_list
    })


@app.route('/candidate/assessments/<int:test_id>')
def candidate_assessment_detail(test_id):
    """Renders assessment instructions and overview."""
    with db_cursor() as cursor:
        cursor.execute("SELECT * FROM assessments WHERE id = %s", (test_id,))
        assessment = cursor.fetchone()
    if not assessment:
        flash('Assessment not found', 'error')
        return redirect(url_for('candidate_assessments'))
    
    user_id = session.get('user_id')
    latest_attempt = None
    if user_id:
        with db_cursor() as cursor:
            cursor.execute("""
                SELECT * FROM assessment_attempts 
                WHERE user_id = %s AND assessment_id = %s AND status = 'completed'
                ORDER BY completed_at DESC LIMIT 1
            """, (user_id, test_id))
            latest_attempt = cursor.fetchone()

    return render_template(
        'candidate_assessment_detail.html',
        assessment=assessment,
        latest_attempt=latest_attempt
    )


@app.route('/api/candidate/assessments/<int:test_id>/start', methods=['POST'])
def api_candidate_assessment_start(test_id):
    """Starts a new timed assessment attempt."""
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Please sign in to take this assessment', 'requires_auth': True}), 401
    
    user_id = session['user_id']
    with db_cursor() as cursor:
        cursor.execute("SELECT * FROM assessments WHERE id = %s", (test_id,))
        assessment = cursor.fetchone()
        if not assessment:
            return jsonify({'success': False, 'message': 'Assessment not found'}), 404
        
        # Check if there is already an in_progress attempt that hasn't expired
        cursor.execute("""
            SELECT id, expires_at FROM assessment_attempts 
            WHERE user_id = %s AND assessment_id = %s AND status = 'in_progress'
            ORDER BY started_at DESC LIMIT 1
        """, (user_id, test_id))
        active_attempt = cursor.fetchone()
        
        now = datetime.utcnow()
        if active_attempt and active_attempt.get('expires_at') and active_attempt['expires_at'] > now:
            attempt_id = active_attempt['id']
        else:
            time_limit = assessment.get('time_limit_minutes', 15) or 15
            # Add 30 seconds network buffer
            expires_at = now + timedelta(minutes=time_limit, seconds=30)
            cursor.execute("""
                INSERT INTO assessment_attempts 
                (user_id, assessment_id, started_at, expires_at, total_questions, status)
                VALUES (%s, %s, %s, %s, %s, 'in_progress')
            """, (user_id, test_id, now, expires_at, assessment.get('questions_count', 10)))
            attempt_id = cursor.lastrowid

    return jsonify({
        'success': True,
        'attempt_id': attempt_id,
        'redirect_url': url_for('candidate_assessment_take', attempt_id=attempt_id)
    })


@app.route('/candidate/assessments/attempt/<int:attempt_id>')
def candidate_assessment_take(attempt_id):
    """Renders the live test interface for an active attempt."""
    if 'user_id' not in session:
        flash('Please sign in to access your assessment', 'info')
        return redirect(url_for('index'))
    
    user_id = session['user_id']
    with db_cursor() as cursor:
        cursor.execute("""
            SELECT a.*, asm.title, asm.category, asm.time_limit_minutes, asm.passing_score, asm.icon 
            FROM assessment_attempts a 
            JOIN assessments asm ON a.assessment_id = asm.id 
            WHERE a.id = %s AND a.user_id = %s
        """, (attempt_id, user_id))
        attempt = cursor.fetchone()
    
    if not attempt:
        flash('Assessment attempt not found or unauthorized', 'error')
        return redirect(url_for('candidate_assessments'))
    
    if attempt['status'] == 'completed':
        return redirect(url_for('candidate_assessment_result', attempt_id=attempt_id))
    
    return render_template('candidate_assessment_take.html', attempt=attempt)


@app.route('/api/candidate/assessments/attempt/<int:attempt_id>')
def api_candidate_assessment_attempt_data(attempt_id):
    """Fetches questions and remaining time for an active attempt (sanitized without correct answers)."""
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    
    user_id = session['user_id']
    with db_cursor() as cursor:
        cursor.execute("""
            SELECT a.*, asm.title, asm.category, asm.time_limit_minutes, asm.passing_score 
            FROM assessment_attempts a 
            JOIN assessments asm ON a.assessment_id = asm.id 
            WHERE a.id = %s AND a.user_id = %s
        """, (attempt_id, user_id))
        attempt = cursor.fetchone()
        if not attempt:
            return jsonify({'success': False, 'message': 'Attempt not found'}), 404
        
        # Calculate time remaining
        now = datetime.utcnow()
        expires_at = attempt.get('expires_at')
        if expires_at:
            time_remaining = max(0, int((expires_at - now).total_seconds()))
        else:
            time_remaining = (attempt.get('time_limit_minutes', 15) or 15) * 60

        # Fetch questions (WITHOUT correct_option or explanation)
        cursor.execute("""
            SELECT id, question_text, options, question_order 
            FROM assessment_questions 
            WHERE assessment_id = %s 
            ORDER BY question_order ASC, id ASC
        """, (attempt['assessment_id'],))
        questions_raw = cursor.fetchall()
        
        sanitized_questions = []
        for q in questions_raw:
            opts = q['options']
            if isinstance(opts, str):
                try:
                    opts = json.loads(opts)
                except Exception:
                    opts = []
            sanitized_questions.append({
                'id': q['id'],
                'text': q['question_text'],
                'options': opts,
                'order': q['question_order']
            })

        user_answers = attempt.get('user_answers')
        if isinstance(user_answers, str) and user_answers:
            try:
                user_answers = json.loads(user_answers)
            except Exception:
                user_answers = {}
        elif not isinstance(user_answers, dict):
            user_answers = {}

    return jsonify({
        'success': True,
        'attempt_id': attempt['id'],
        'assessment_id': attempt['assessment_id'],
        'title': attempt['title'],
        'category': attempt['category'],
        'time_remaining_seconds': time_remaining,
        'total_questions': len(sanitized_questions),
        'questions': sanitized_questions,
        'saved_answers': user_answers,
        'status': attempt['status']
    })


@app.route('/api/candidate/assessments/attempt/<int:attempt_id>/save', methods=['POST'])
def api_candidate_assessment_save(attempt_id):
    """Saves candidate current answers in progress."""
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    
    user_id = session['user_id']
    data = request.get_json(silent=True) or {}
    answers = data.get('answers', {})
    
    with db_cursor() as cursor:
        cursor.execute("SELECT id, status FROM assessment_attempts WHERE id = %s AND user_id = %s", (attempt_id, user_id))
        attempt = cursor.fetchone()
        if not attempt or attempt['status'] != 'in_progress':
            return jsonify({'success': False, 'message': 'Cannot save; attempt is closed'}), 400
        
        cursor.execute("UPDATE assessment_attempts SET user_answers = %s WHERE id = %s", (json.dumps(answers), attempt_id))
    
    return jsonify({'success': True})


@app.route('/api/candidate/assessments/attempt/<int:attempt_id>/submit', methods=['POST'])
@app.route('/api/assessments/<int:attempt_id>/submit', methods=['POST'])
def api_candidate_assessment_submit(attempt_id):
    """Server-side scoring and badge assignment."""
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    
    user_id = session['user_id']
    data = request.get_json(silent=True) or {}
    submitted_answers = data.get('answers', {})
    
    with db_cursor() as cursor:
        cursor.execute("""
            SELECT a.*, asm.title, asm.category, asm.passing_score, asm.badge_icon 
            FROM assessment_attempts a 
            JOIN assessments asm ON a.assessment_id = asm.id 
            WHERE a.id = %s AND a.user_id = %s
        """, (attempt_id, user_id))
        attempt = cursor.fetchone()
        if not attempt:
            return jsonify({'success': False, 'message': 'Attempt not found or unauthorized'}), 404
        
        # Fetch question keys from DB
        cursor.execute("""
            SELECT id, correct_option 
            FROM assessment_questions 
            WHERE assessment_id = %s
        """, (attempt['assessment_id'],))
        questions = cursor.fetchall()
        
        total_questions = len(questions)
        correct_count = 0
        
        for q in questions:
            qid_str = str(q['id'])
            user_choice = submitted_answers.get(qid_str)
            if user_choice is not None:
                try:
                    if int(user_choice) == int(q['correct_option']):
                        correct_count += 1
                except (ValueError, TypeError):
                    pass
        
        score_pct = int(round((correct_count / total_questions * 100))) if total_questions > 0 else 0
        passing_score = attempt.get('passing_score', 70) or 70
        passed = score_pct >= passing_score
        
        now = datetime.utcnow()
        cursor.execute("""
            UPDATE assessment_attempts 
            SET score = %s, correct_count = %s, total_questions = %s, passed = %s,
                user_answers = %s, completed_at = %s, status = 'completed'
            WHERE id = %s
        """, (score_pct, correct_count, total_questions, passed, json.dumps(submitted_answers), now, attempt_id))
        
        # Award Verified Skill Badge if passed!
        badge_level = None
        if passed:
            skill_name = attempt['category']
            badge_level = 'Verified Professional' if score_pct >= 85 else 'Verified Skill'
            cursor.execute("""
                INSERT INTO skill_badges (user_id, assessment_id, attempt_id, skill_name, score, badge_level, earned_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE 
                    attempt_id = VALUES(attempt_id),
                    score = GREATEST(score, VALUES(score)),
                    badge_level = VALUES(badge_level),
                    earned_at = VALUES(earned_at)
            """, (user_id, attempt['assessment_id'], attempt_id, skill_name, score_pct, badge_level, now))

            # Synchronize verified skill to candidate profile
            try:
                cursor.execute("SELECT skills FROM candidate_profile WHERE user_id = %s", (user_id,))
                prof_row = cursor.fetchone()
                if prof_row:
                    curr_skills = prof_row.get('skills') or ''
                    skills_list = [s.strip() for s in curr_skills.split(',') if s.strip()]
                    if skill_name not in skills_list:
                        skills_list.append(skill_name)
                        new_skills_str = ', '.join(skills_list)
                        cursor.execute("UPDATE candidate_profile SET skills = %s WHERE user_id = %s", (new_skills_str, user_id))
                else:
                    cursor.execute("INSERT INTO candidate_profile (user_id, skills) VALUES (%s, %s)", (user_id, skill_name))
            except Exception as sync_err:
                logger.debug(f"Candidate profile skill sync notice: {sync_err}")

        badge_msg = f" You earned the {badge_level} badge! 🏅" if passed else " You can review the material and retake the test later."
        create_notification(
            user_id=user_id,
            notification_type='assessment_result',
            title=f"Assessment Result: {attempt['title']} {'(Passed! 🎉)' if passed else ''}",
            message=f"You scored {score_pct}% on '{attempt['title']}'.{badge_msg}",
            action_url=f"/candidate/assessments/{attempt['assessment_id']}/result"
        )

    return jsonify({
        'success': True,
        'score': score_pct,
        'correct_count': correct_count,
        'total_questions': total_questions,
        'passed': passed,
        'redirect_url': url_for('candidate_assessment_result', attempt_id=attempt_id)
    })


@app.route('/candidate/assessments/result/<int:attempt_id>')
def candidate_assessment_result(attempt_id):
    """Renders the assessment result dashboard."""
    if 'user_id' not in session:
        flash('Please sign in to view your assessment result', 'info')
        return redirect(url_for('index'))
    
    user_id = session['user_id']
    with db_cursor() as cursor:
        cursor.execute("""
            SELECT a.*, asm.title, asm.category, asm.passing_score, asm.icon, asm.badge_icon 
            FROM assessment_attempts a 
            JOIN assessments asm ON a.assessment_id = asm.id 
            WHERE a.id = %s AND a.user_id = %s
        """, (attempt_id, user_id))
        attempt = cursor.fetchone()
    
    if not attempt:
        flash('Assessment attempt not found or unauthorized', 'error')
        return redirect(url_for('candidate_assessments'))
    
    return render_template('candidate_assessment_result.html', attempt=attempt)


@app.route('/api/candidate/assessments/result/<int:attempt_id>')
def api_candidate_assessment_result_data(attempt_id):
    """Returns detailed result data including full question-by-question review and explanations."""
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    
    user_id = session['user_id']
    with db_cursor() as cursor:
        cursor.execute("""
            SELECT a.*, asm.title, asm.category, asm.passing_score, asm.icon, asm.badge_icon 
            FROM assessment_attempts a 
            JOIN assessments asm ON a.assessment_id = asm.id 
            WHERE a.id = %s AND a.user_id = %s
        """, (attempt_id, user_id))
        attempt = cursor.fetchone()
        if not attempt:
            return jsonify({'success': False, 'message': 'Attempt not found'}), 404
        
        user_answers = attempt.get('user_answers')
        if isinstance(user_answers, str) and user_answers:
            try:
                user_answers = json.loads(user_answers)
            except Exception:
                user_answers = {}
        elif not isinstance(user_answers, dict):
            user_answers = {}

        # Fetch questions WITH correct answers & explanations for post-exam review
        cursor.execute("""
            SELECT id, question_text, options, correct_option, explanation, question_order 
            FROM assessment_questions 
            WHERE assessment_id = %s 
            ORDER BY question_order ASC, id ASC
        """, (attempt['assessment_id'],))
        questions_raw = cursor.fetchall()
        
        review_questions = []
        for q in questions_raw:
            opts = q['options']
            if isinstance(opts, str):
                try:
                    opts = json.loads(opts)
                except Exception:
                    opts = []
            
            qid_str = str(q['id'])
            user_choice = user_answers.get(qid_str)
            user_choice_int = int(user_choice) if user_choice is not None else None
            is_correct = (user_choice_int == q['correct_option']) if user_choice_int is not None else False
            
            review_questions.append({
                'id': q['id'],
                'text': q['question_text'],
                'options': opts,
                'user_choice': user_choice_int,
                'correct_option': q['correct_option'],
                'is_correct': is_correct,
                'explanation': q['explanation'],
                'order': q['question_order']
            })

    return jsonify({
        'success': True,
        'attempt_id': attempt['id'],
        'assessment_id': attempt['assessment_id'],
        'title': attempt['title'],
        'category': attempt['category'],
        'score': attempt['score'],
        'correct_count': attempt['correct_count'],
        'total_questions': attempt['total_questions'],
        'passing_score': attempt['passing_score'],
        'passed': bool(attempt['passed']),
        'completed_at': attempt['completed_at'].strftime('%b %d, %Y %I:%M %p') if attempt.get('completed_at') else None,
        'review_questions': review_questions
    })


@app.route('/api/candidate/badges')
def api_candidate_badges():
    """Returns earned skill badges for current logged-in candidate."""
    if 'user_id' not in session:
        return jsonify({'success': True, 'badges': []})
    
    with db_cursor() as cursor:
        cursor.execute("""
            SELECT sb.*, a.title, a.icon, a.badge_icon 
            FROM skill_badges sb 
            JOIN assessments a ON sb.assessment_id = a.id 
            WHERE sb.user_id = %s 
            ORDER BY sb.earned_at DESC
        """, (session['user_id'],))
        badges = cursor.fetchall()
        for b in badges:
            if b.get('earned_at'):
                b['earned_at_formatted'] = b['earned_at'].strftime('%b %d, %Y')
    
    return jsonify({'success': True, 'badges': badges})

@app.route('/candidate/applications')
def candidate_applications():
    if 'user_id' not in session: return redirect(url_for('index'))
    return render_template('user_dashboard.html')

@app.route('/candidate/applications/<int:app_id>')
def candidate_application_detail(app_id):
    if 'user_id' not in session: return redirect(url_for('index'))
    return render_template('user_dashboard.html')

@app.route('/candidate/applications/<int:app_id>/withdraw')
def candidate_application_withdraw(app_id):
    if 'user_id' not in session: return redirect(url_for('index'))
    return redirect(url_for('candidate_applications'))

@app.route('/candidate/saved-jobs')
def candidate_saved_jobs():
    if 'user_id' not in session: return redirect(url_for('index'))
    return render_template('user_dashboard.html')

@app.route('/candidate/saved-jobs/<int:job_id>/remove')
def candidate_saved_job_remove(job_id):
    if 'user_id' not in session: return redirect(url_for('index'))
    return redirect(url_for('candidate_saved_jobs'))

@app.route('/candidate/messages')
@app.route('/candidate/messages/<int:conversation_id>')
@app.route('/candidate/messages/new')
@app.route('/messages')
def candidate_messages(conversation_id=None):
    if 'user_id' not in session: return redirect(url_for('index'))
    return render_template('candidate_messages.html', initial_conversation_id=conversation_id)

@app.route('/candidate/interview/<int:interview_id>')
def candidate_interview(interview_id):
    if 'user_id' not in session: return redirect(url_for('index'))
    return render_template('candidate_interview.html')

@app.route('/candidate/interview/<int:interview_id>/join')
def candidate_interview_join(interview_id):
    if 'user_id' not in session: return redirect(url_for('index'))
    return render_template('candidate_interview.html')

@app.route('/candidate/interview/<int:interview_id>/reschedule')
def candidate_interview_reschedule(interview_id):
    if 'user_id' not in session: return redirect(url_for('index'))
    return render_template('candidate_interview.html')

@app.route('/candidate/interview/<int:interview_id>/cancel')
def candidate_interview_cancel(interview_id):
    if 'user_id' not in session: return redirect(url_for('index'))
    return redirect(url_for('candidate_interview', interview_id=interview_id))

@app.route('/candidate/interview/<int:interview_id>/calendar')
def candidate_interview_calendar(interview_id):
    if 'user_id' not in session: return redirect(url_for('index'))
    return redirect(url_for('candidate_interview', interview_id=interview_id))

@app.route('/candidate/settings')
def candidate_settings():
    if 'user_id' not in session: return redirect(url_for('index'))
    return render_template('candidate_settings.html')

@app.route('/candidate/settings/account')
def candidate_settings_account():
    if 'user_id' not in session: return redirect(url_for('index'))
    return render_template('candidate_settings.html')

@app.route('/candidate/settings/notifications')
def candidate_settings_notifications():
    if 'user_id' not in session: return redirect(url_for('index'))
    return render_template('candidate_settings.html')

@app.route('/candidate/settings/privacy')
def candidate_settings_privacy():
    if 'user_id' not in session: return redirect(url_for('index'))
    return render_template('candidate_settings.html')

@app.route('/candidate/settings/password')
def candidate_settings_password():
    if 'user_id' not in session: return redirect(url_for('index'))
    return render_template('candidate_settings.html')

@app.route('/candidate/settings/delete')
def candidate_settings_delete():
    if 'user_id' not in session: return redirect(url_for('index'))
    return render_template('candidate_settings.html')

@app.route('/notifications')
def general_notifications():
    if session.get('is_admin'):
        return render_template('notifications.html', role='admin')
    elif 'employer_id' in session:
        return render_template('notifications.html', role='employer')
    elif 'user_id' in session:
        return render_template('notifications.html', role='candidate')
    return redirect(url_for('index'))

@app.route('/admin/notifications')
def admin_notifications():
    if not session.get('is_admin'):
        return redirect(url_for('admin_login_page'))
    return render_template('notifications.html', role='admin')

@app.route('/candidate/notifications')
def candidate_notifications():
    if 'user_id' not in session: return redirect(url_for('index'))
    return render_template('notifications.html', role='candidate')

@app.route('/recruiter/notifications')
@app.route('/employer/notifications')
def recruiter_notifications():
    if 'employer_id' not in session: return redirect(url_for('index'))
    return render_template('notifications.html', role='employer')

@app.route('/apply/<int:job_id>')
def apply_job_page(job_id):
    if 'user_id' not in session: return redirect(url_for('index'))
    return render_template('user_dashboard.html')

# --- RECRUITER PAGES ---
@app.route('/recruiter/dashboard')
def recruiter_dashboard():
    if 'employer_id' not in session: return redirect(url_for('index'))
    return redirect(url_for('employer_dashboard'))

@app.route('/recruiter/jobs')
def recruiter_jobs():
    if 'employer_id' not in session: return redirect(url_for('index'))
    return render_template('employer_dashboard.html')

@app.route('/recruiter/jobs/post')
def recruiter_jobs_post():
    if 'employer_id' not in session: return redirect(url_for('index'))
    return render_template('employer_dashboard.html')

@app.route('/recruiter/jobs/<int:job_id>/edit')
def recruiter_jobs_edit(job_id):
    if 'employer_id' not in session: return redirect(url_for('index'))
    return render_template('employer_dashboard.html')

@app.route('/recruiter/jobs/<int:job_id>/toggle')
def recruiter_jobs_toggle(job_id):
    if 'employer_id' not in session: return redirect(url_for('index'))
    return redirect(url_for('recruiter_jobs'))

@app.route('/recruiter/jobs/<int:job_id>/delete')
def recruiter_jobs_delete(job_id):
    if 'employer_id' not in session: return redirect(url_for('index'))
    return redirect(url_for('recruiter_jobs'))

@app.route('/recruiter/jobs/<int:job_id>/duplicate')
def recruiter_jobs_duplicate(job_id):
    if 'employer_id' not in session: return redirect(url_for('index'))
    return redirect(url_for('recruiter_jobs'))

@app.route('/recruiter/jobs/<int:job_id>/promote')
def recruiter_jobs_promote(job_id):
    if 'employer_id' not in session: return redirect(url_for('index'))
    return redirect(url_for('recruiter_jobs'))

@app.route('/recruiter/applications')
def recruiter_applications():
    if 'employer_id' not in session: return redirect(url_for('index'))
    return render_template('employer_dashboard.html')

@app.route('/recruiter/applications/<int:app_id>')
def recruiter_application_detail(app_id):
    if 'employer_id' not in session: return redirect(url_for('index'))
    return render_template('employer_dashboard.html')

@app.route('/recruiter/applications/<int:app_id>/shortlist')
def recruiter_application_shortlist(app_id):
    if 'employer_id' not in session: return redirect(url_for('index'))
    return redirect(url_for('recruiter_applications'))

@app.route('/recruiter/applications/<int:app_id>/reject')
def recruiter_application_reject(app_id):
    if 'employer_id' not in session: return redirect(url_for('index'))
    return redirect(url_for('recruiter_applications'))

@app.route('/recruiter/applications/<int:app_id>/interview')
def recruiter_application_interview(app_id):
    if 'employer_id' not in session: return redirect(url_for('index'))
    return redirect(url_for('recruiter_applications'))

@app.route('/recruiter/applications/<int:app_id>/hire')
def recruiter_application_hire(app_id):
    if 'employer_id' not in session: return redirect(url_for('index'))
    return redirect(url_for('recruiter_applications'))

@app.route('/recruiter/applications/<int:app_id>/resume')
def recruiter_application_resume(app_id):
    if 'employer_id' not in session: return redirect(url_for('index'))
    return redirect(url_for('recruiter_applications'))

@app.route('/recruiter/applications/<int:app_id>/resume/download')
def recruiter_application_resume_download(app_id):
    if 'employer_id' not in session: return redirect(url_for('index'))
    return redirect(url_for('recruiter_applications'))

@app.route('/recruiter/applications/bulk')
def recruiter_applications_bulk():
    if 'employer_id' not in session: return redirect(url_for('index'))
    return redirect(url_for('recruiter_applications'))

@app.route('/recruiter/candidates')
@app.route('/recruiter_candidates')
def recruiter_candidates():
    if 'employer_id' not in session: return redirect(url_for('index'))
    return render_template('recruiter_candidates.html')

@app.route('/recruiter/candidates/<int:candidate_id>')
def recruiter_candidate_detail(candidate_id):
    if 'employer_id' not in session: return redirect(url_for('index'))
    return render_template('recruiter_candidates.html')

@app.route('/recruiter/candidates/<int:candidate_id>/invite')
def recruiter_candidate_invite(candidate_id):
    if 'employer_id' not in session: return redirect(url_for('index'))
    return redirect(url_for('recruiter_candidates'))

@app.route('/recruiter/candidates/saved')
def recruiter_candidates_saved():
    if 'employer_id' not in session: return redirect(url_for('index'))
    return redirect(url_for('recruiter_candidates'))

@app.route('/recruiter/candidates/saved-searches')
def recruiter_candidates_saved_searches():
    if 'employer_id' not in session: return redirect(url_for('index'))
    return redirect(url_for('recruiter_candidates'))


# ==================================================
# TALENT SEARCH & CANDIDATE MATCH SCORING ENGINE
# ==================================================

def calculate_candidate_job_match(job, candidate):
    """
    Computes a calibrated, weighted 0-100 score matching candidate profile against a job.
    Weights:
    1. Skills Match (40% weight): (matched_skills / required_skills) * 100.
       - Returns matched_skills and missing_skills lists.
       - Defaults to 100.0 if job has no required skills listed.
    2. JD Relevance (30% weight):
       - Uses compute_semantic_similarity(jd_text, candidate_text) * 100.
       - Uses SentenceTransformer with TF-IDF fallback.
    3. Experience Match (15% weight):
       - Sums employment duration from employment table (or user.experience).
       - Compares against parsed required years from job.experience.
       - min(100.0, (candidate_years / required_years) * 100). Default 100 if req <= 0.
    4. Education Match (10% weight):
       - Evaluates candidate degrees against job category/requirements.
       - Defaults to 100.0 if job specifies no education requirement.
    5. Location Match (5% weight):
       - Compares job.location and candidate's current_location.
       - 100.0 for match or remote/unspecified; 50.0 otherwise.
    """
    if not job or not candidate:
        return {
            'job_id': job.get('id') if job else 0,
            'candidate_id': candidate.get('user_id') or candidate.get('id') if candidate else 0,
            'final_score': 0.0,
            'skill_score': 0.0,
            'semantic_score': 0.0,
            'experience_score': 0.0,
            'education_score': 0.0,
            'location_score': 0.0,
            'matched_skills': [],
            'missing_skills': [],
            'candidate_years': 0.0,
            'required_years': 0.0
        }

    # 1. Skills Match (40% Weight)
    job_skills_raw = str(job.get('skills') or '').strip()
    required_skills = [s.strip() for s in re.split(r'[,;\n]', job_skills_raw) if s.strip()]

    # Collect candidate skills from profile, key_skills, it_skills, and user.skills
    candidate_skills_list = []
    if isinstance(candidate.get('skills'), list):
        candidate_skills_list.extend(candidate.get('skills'))
    elif candidate.get('skills'):
        candidate_skills_list.extend([s.strip() for s in re.split(r'[,;\n]', str(candidate.get('skills'))) if s.strip()])
    if candidate.get('skills_list'):
        candidate_skills_list.extend(candidate.get('skills_list'))

    # Normalize candidate skill strings
    cand_skill_map = {}
    for s in candidate_skills_list:
        clean_s = str(s).strip()
        if clean_s:
            cand_skill_map[clean_s.lower()] = clean_s

    matched_skills = []
    missing_skills = []

    if not required_skills:
        skill_score = 100.0
    else:
        for req in required_skills:
            req_clean = req.strip()
            req_lower = req_clean.lower()
            # Direct match
            if req_lower in cand_skill_map:
                matched_skills.append(req_clean)
            else:
                # Partial / substring match (e.g., 'python' in 'python 3', 'react' in 'react.js')
                found = False
                for c_low in cand_skill_map.keys():
                    if req_lower == c_low or req_lower in c_low or c_low in req_lower:
                        matched_skills.append(req_clean)
                        found = True
                        break
                if not found:
                    missing_skills.append(req_clean)

        skill_score = round((len(matched_skills) / len(required_skills)) * 100.0, 2)

    # 2. Semantic Relevance (30% Weight)
    jd_parts = [
        str(job.get('title') or ''),
        str(job.get('category') or ''),
        str(job.get('description') or '')
    ]
    jd_text = ' '.join(p for p in jd_parts if p).strip()

    cand_summary = str(candidate.get('summary') or '').strip()
    cand_resume = str(candidate.get('resume_text') or '').strip()
    cand_headline = str(candidate.get('headline') or '').strip()
    cand_skills_str = ' '.join(cand_skill_map.values())

    cand_text = ''
    if len(cand_summary) >= 15:
        cand_text = cand_summary
    elif len(cand_resume) >= 15:
        cand_text = cand_resume
    else:
        cand_text = f"{cand_headline}. Skills: {cand_skills_str}".strip()

    if not jd_text or not cand_text:
        semantic_score = 50.0
    else:
        try:
            sim = compute_semantic_similarity(jd_text[:3000], cand_text[:3000])
            semantic_score = round(float(sim) * 100.0, 2)
        except Exception as e:
            logger.warning(f"Error computing semantic similarity in candidate match: {e}")
            semantic_score = 50.0

    # 3. Experience Match (15% Weight)
    req_exp_str = str(job.get('experience') or '').strip().lower()
    if not req_exp_str or 'fresher' in req_exp_str or 'entry' in req_exp_str or req_exp_str == '0':
        req_years = 0.0
    else:
        nums = re.findall(r'\d+(?:\.\d+)?', req_exp_str)
        req_years = float(nums[0]) if nums else 0.0

    candidate_years = 0.0
    emp_rows = candidate.get('employment_rows') or candidate.get('employment_history') or []
    if emp_rows:
        for emp in emp_rows:
            s_date = emp.get('start_date')
            e_date = emp.get('end_date')
            is_cur = emp.get('is_current')
            if is_cur or not e_date:
                e_date = dt_date.today()
            if isinstance(s_date, str):
                try: s_date = datetime.strptime(s_date[:10], '%Y-%m-%d').date()
                except Exception: s_date = None
            if isinstance(e_date, str):
                try: e_date = datetime.strptime(e_date[:10], '%Y-%m-%d').date()
                except Exception: e_date = None
            if s_date and e_date and e_date >= s_date:
                candidate_years += (e_date - s_date).days / 365.25
    if candidate_years == 0.0:
        try:
            candidate_years = float(candidate.get('experience_years') or candidate.get('experience') or 0)
        except Exception:
            candidate_years = 0.0

    candidate_years = round(candidate_years, 1)

    if req_years <= 0.0:
        experience_score = 100.0
    else:
        experience_score = round(min(100.0, (candidate_years / req_years) * 100.0), 2)

    # 4. Education Match (10% Weight)
    edu_rows = candidate.get('education_rows') or candidate.get('education_history') or []
    cand_edu_text = ' '.join([
        f"{e.get('course_degree', '')} {e.get('specialization', '')} {e.get('education_level', '')}"
        for e in edu_rows
    ]).lower()
    if candidate.get('qualification'):
        cand_edu_text += ' ' + str(candidate.get('qualification')).lower()

    # Determine if job specifies explicit education requirements
    desc_lower = str(job.get('description') or '').lower()
    edu_keywords = ['b.tech', 'btech', 'b.e', 'm.tech', 'mtech', 'bca', 'mca', 'b.sc', 'bsc', 'mba', 'master', 'bachelor', 'phd', 'doctorate', 'diploma']
    job_required_edu = [kw for kw in edu_keywords if re.search(r'\b' + re.escape(kw) + r'\b', desc_lower)]

    if not job_required_edu:
        education_score = 100.0  # Missing requirements don't penalize
    else:
        matched_edu = [kw for kw in job_required_edu if kw in cand_edu_text]
        if matched_edu:
            education_score = 100.0
        elif 'bachelor' in desc_lower or 'degree' in desc_lower or 'graduation' in desc_lower:
            education_score = 80.0 if any(deg in cand_edu_text for deg in ['b.tech', 'btech', 'b.e', 'bca', 'b.sc', 'bsc', 'bachelor', 'graduation']) else 40.0
        else:
            education_score = 50.0

    # 5. Location Match (5% Weight)
    job_loc = str(job.get('location') or '').strip().lower()
    cand_loc = str(candidate.get('location') or candidate.get('current_location') or '').strip().lower()
    open_relocate = bool(candidate.get('open_to_relocate'))

    if not job_loc or 'remote' in job_loc or 'any' in job_loc or 'pan india' in job_loc:
        location_score = 100.0
    elif not cand_loc:
        location_score = 80.0 if open_relocate else 50.0
    elif job_loc in cand_loc or cand_loc in job_loc:
        location_score = 100.0
    elif open_relocate:
        location_score = 80.0
    else:
        location_score = 0.0

    # Final Weighted Aggregate Score
    final_score = round(
        (skill_score * 0.40) +
        (semantic_score * 0.30) +
        (experience_score * 0.15) +
        (education_score * 0.10) +
        (location_score * 0.05),
        2
    )

    return {
        'job_id': job.get('id', 0),
        'candidate_id': candidate.get('user_id') or candidate.get('id', 0),
        'final_score': final_score,
        'skill_score': skill_score,
        'semantic_score': semantic_score,
        'experience_score': experience_score,
        'education_score': education_score,
        'location_score': location_score,
        'matched_skills': matched_skills,
        'missing_skills': missing_skills,
        'candidate_years': candidate_years,
        'required_years': req_years
    }


def get_candidates_matching_data(candidate_id=None):
    """
    Fetches rich candidate profile, skills, employment records, and education records for matching.
    """
    try:
        with db_cursor() as cur:
            query = """
                SELECT u.id AS user_id, u.name, u.email, u.mobile, u.headline, u.skills, u.experience, u.location,
                       cp.headline AS profile_headline, cp.summary AS profile_summary, cp.skills AS profile_skills,
                       cp.profile_photo, cp.general_resume_path,
                       cpd.current_location, cpd.hometown,
                       cpref.open_to_relocate, cpref.notice_period, cpref.current_job_role,
                       cpref.expected_ctc, cpref.current_ctc
                FROM user u
                LEFT JOIN candidate_profile cp ON u.id = cp.user_id
                LEFT JOIN candidate_personal_details cpd ON u.id = cpd.user_id
                LEFT JOIN candidate_preferences cpref ON u.id = cpref.user_id
                WHERE (u.is_banned = FALSE OR u.is_banned IS NULL)
                  AND (u.is_deleted = FALSE OR u.is_deleted IS NULL)
            """
            params = []
            if candidate_id:
                query += " AND u.id = %s"
                params.append(candidate_id)
            cur.execute(query, tuple(params))
            candidate_rows = cur.fetchall()

            if not candidate_rows:
                return []

            user_ids = [r['user_id'] for r in candidate_rows]
            format_strings = ','.join(['%s'] * len(user_ids))

            # Fetch employment
            cur.execute(f"""
                SELECT user_id, company_name, job_title, start_date, end_date, is_current, skills_used
                FROM employment
                WHERE user_id IN ({format_strings})
                ORDER BY is_current DESC, id DESC
            """, tuple(user_ids))
            all_emp = cur.fetchall()

            # Fetch education
            cur.execute(f"""
                SELECT user_id, education_level, course_degree, specialization, institute, year_of_passing
                FROM education
                WHERE user_id IN ({format_strings})
                ORDER BY id DESC
            """, tuple(user_ids))
            all_edu = cur.fetchall()

            # Fetch key_skills
            cur.execute(f"""
                SELECT user_id, skill_name FROM key_skills WHERE user_id IN ({format_strings})
            """, tuple(user_ids))
            all_ks = cur.fetchall()

            # Fetch it_skills
            cur.execute(f"""
                SELECT user_id, skill_name, experience_years, proficiency FROM it_skills WHERE user_id IN ({format_strings})
            """, tuple(user_ids))
            all_it = cur.fetchall()

            # Fetch summary
            cur.execute(f"""
                SELECT user_id, summary FROM candidate_profile_summary WHERE user_id IN ({format_strings})
            """, tuple(user_ids))
            all_summaries = cur.fetchall()

        # Group data by user_id
        emp_by_user = {}
        for e in all_emp:
            emp_by_user.setdefault(e['user_id'], []).append(e)

        edu_by_user = {}
        for ed in all_edu:
            edu_by_user.setdefault(ed['user_id'], []).append(ed)

        skills_by_user = {}
        for ks in all_ks:
            if ks.get('skill_name'):
                skills_by_user.setdefault(ks['user_id'], set()).add(ks['skill_name'].strip())
        for it in all_it:
            if it.get('skill_name'):
                skills_by_user.setdefault(it['user_id'], set()).add(it['skill_name'].strip())

        summaries_by_user = {s['user_id']: s['summary'] for s in all_summaries if s.get('summary')}

        candidates_data = []
        for c in candidate_rows:
            uid = c['user_id']
            extra_skills = skills_by_user.get(uid, set())
            raw_skills = str(c.get('profile_skills') or c.get('skills') or '')
            all_skills_list = [s.strip() for s in re.split(r'[,;\n]', raw_skills) if s.strip()] + list(extra_skills)
            
            seen = set()
            dedup_skills = []
            for s in all_skills_list:
                if s.lower() not in seen:
                    seen.add(s.lower())
                    dedup_skills.append(s)

            summary_text = summaries_by_user.get(uid) or c.get('profile_summary') or ''

            candidates_data.append({
                'user_id': uid,
                'id': uid,
                'name': c.get('name') or 'Candidate',
                'email': c.get('email') or '',
                'mobile': c.get('mobile') or '',
                'headline': c.get('profile_headline') or c.get('headline') or 'Software Professional',
                'skills': ', '.join(dedup_skills),
                'skills_list': dedup_skills,
                'summary': summary_text,
                'employment_rows': emp_by_user.get(uid, []),
                'education_rows': edu_by_user.get(uid, []),
                'experience': c.get('experience') or 0,
                'current_location': c.get('current_location') or c.get('location') or '',
                'location': c.get('current_location') or c.get('location') or '',
                'open_to_relocate': bool(c.get('open_to_relocate')),
                'notice_period': c.get('notice_period') or 'Immediate',
                'profile_photo': c.get('profile_photo') or ''
            })

        return candidates_data
    except Exception as e:
        logger.error(f"Error gathering candidate matching data: {e}")
        return []


def refresh_job_candidate_matches(job_id):
    """
    Computes and stores match scores for all eligible candidates against a job in candidate_job_matches table.
    """
    try:
        with db_cursor() as cur:
            cur.execute("""
                SELECT j.id, j.title, j.description, j.location, j.salary, j.experience, j.skills, j.category,
                       COALESCE(e.company_name, j.company_name) AS company_name
                FROM jobs j
                LEFT JOIN employee e ON j.employer_id = e.id
                WHERE j.id = %s AND (j.is_deleted = FALSE OR j.is_deleted IS NULL)
            """, (job_id,))
            job = cur.fetchone()
            if not job:
                return False

        candidates = get_candidates_matching_data()
        if not candidates:
            return True

        with db_cursor(dictionary=False) as cur:
            for cand in candidates:
                match = calculate_candidate_job_match(job, cand)
                matched_str = ', '.join(match['matched_skills'])
                missing_str = ', '.join(match['missing_skills'])
                cur.execute("""
                    INSERT INTO candidate_job_matches 
                        (job_id, candidate_id, skill_score, semantic_score, experience_score,
                         education_score, location_score, final_score, matched_skills, missing_skills, computed_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                    ON DUPLICATE KEY UPDATE
                        skill_score = VALUES(skill_score),
                        semantic_score = VALUES(semantic_score),
                        experience_score = VALUES(experience_score),
                        education_score = VALUES(education_score),
                        location_score = VALUES(location_score),
                        final_score = VALUES(final_score),
                        matched_skills = VALUES(matched_skills),
                        missing_skills = VALUES(missing_skills),
                        computed_at = NOW()
                """, (
                    job_id,
                    cand['user_id'],
                    match['skill_score'],
                    match['semantic_score'],
                    match['experience_score'],
                    match['education_score'],
                    match['location_score'],
                    match['final_score'],
                    matched_str,
                    missing_str
                ))
        logger.info(f"Refreshed candidate matches for job {job_id}: {len(candidates)} candidates scored.")
        return True
    except Exception as e:
        logger.error(f"Error refreshing candidate matches for job {job_id}: {e}")
        return False


def refresh_candidate_matches_for_active_jobs(candidate_id):
    """
    Recomputes match scores for a single candidate across all active jobs.
    """
    if app.config.get('TESTING') and not app.config.get('ENABLE_TEST_ML_REFRESH'):
        return True
    try:
        with db_cursor() as cur:
            cur.execute("""
                SELECT j.id, j.title, j.description, j.location, j.salary, j.experience, j.skills, j.category,
                       COALESCE(e.company_name, j.company_name) AS company_name
                FROM jobs j
                LEFT JOIN employee e ON j.employer_id = e.id
                WHERE j.is_active = TRUE 
                  AND (j.is_deleted = FALSE OR j.is_deleted IS NULL)
            """)
            active_jobs = cur.fetchall()

        if not active_jobs:
            return True

        candidates = get_candidates_matching_data(candidate_id=candidate_id)
        if not candidates:
            return False
        cand = candidates[0]

        with db_cursor(dictionary=False) as cur:
            for job in active_jobs:
                match = calculate_candidate_job_match(job, cand)
                matched_str = ', '.join(match['matched_skills'])
                missing_str = ', '.join(match['missing_skills'])
                cur.execute("""
                    INSERT INTO candidate_job_matches 
                        (job_id, candidate_id, skill_score, semantic_score, experience_score,
                         education_score, location_score, final_score, matched_skills, missing_skills, computed_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                    ON DUPLICATE KEY UPDATE
                        skill_score = VALUES(skill_score),
                        semantic_score = VALUES(semantic_score),
                        experience_score = VALUES(experience_score),
                        education_score = VALUES(education_score),
                        location_score = VALUES(location_score),
                        final_score = VALUES(final_score),
                        matched_skills = VALUES(matched_skills),
                        missing_skills = VALUES(missing_skills),
                        computed_at = NOW()
                """, (
                    job['id'],
                    candidate_id,
                    match['skill_score'],
                    match['semantic_score'],
                    match['experience_score'],
                    match['education_score'],
                    match['location_score'],
                    match['final_score'],
                    matched_str,
                    missing_str
                ))
        return True
    except Exception as e:
        logger.error(f"Error refreshing candidate matches across active jobs for candidate {candidate_id}: {e}")
        return False


@app.route('/api/recruiter/jobs', methods=['GET'])
def api_recruiter_jobs():
    """Returns active jobs owned by the authenticated employer for job selection."""
    if 'employer_id' not in session:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401

    employer_id = session['employer_id']
    with db_cursor() as cur:
        cur.execute("""
            SELECT id, title, location, category, skills, experience, job_type, work_mode, created_at
            FROM jobs 
            WHERE employer_id = %s 
              AND (is_deleted = FALSE OR is_deleted IS NULL)
            ORDER BY id DESC
        """, (employer_id,))
        jobs = cur.fetchall()

    for j in jobs:
        if j.get('created_at'):
            j['created_at'] = j['created_at'].strftime('%Y-%m-%d')

    return jsonify({
        'success': True,
        'jobs': jobs,
        'total': len(jobs)
    })


@app.route('/api/recruiter/talent_search', methods=['GET'])
@app.route('/api/candidates', methods=['GET', 'POST'])
def api_recruiter_talent_search():
    """
    Returns ranked candidates for a selected employer job based on cached multi-signal scores.
    Supports secondary text search, tech stack filtering, experience filtering, and location filtering.
    """
    if 'employer_id' not in session:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401

    employer_id = session['employer_id']
    
    # Handle GET query params or POST json body
    if request.method == 'POST' and request.is_json:
        data = request.get_json(silent=True) or {}
    else:
        data = request.args.to_dict()

    job_id = data.get('job_id')
    query_text = sanitize_text(data.get('query') or data.get('search') or '').strip().lower()
    skill_filter = sanitize_text(data.get('skills') or '').strip().lower()
    exp_filter = sanitize_text(data.get('experience') or '').strip()
    loc_filter = sanitize_text(data.get('location') or '').strip().lower()
    force_refresh = str(data.get('refresh', '')).lower() in ('1', 'true', 'yes')

    # If no job_id is provided, try selecting the employer's most recent active job
    with db_cursor() as cur:
        if not job_id:
            cur.execute("""
                SELECT id, title, location, category, skills, experience, description
                FROM jobs 
                WHERE employer_id = %s 
                  AND (is_deleted = FALSE OR is_deleted IS NULL)
                ORDER BY id DESC LIMIT 1
            """, (employer_id,))
            job = cur.fetchone()
            if not job:
                return jsonify({
                    'success': True,
                    'job': None,
                    'candidates': [],
                    'message': 'No active jobs found. Please post a job first to rank candidates.'
                })
            job_id = job['id']
        else:
            try:
                job_id = int(job_id)
            except (ValueError, TypeError):
                return jsonify({'success': False, 'message': 'Invalid job_id parameter'}), 400

            cur.execute("""
                SELECT id, title, location, category, skills, experience, description
                FROM jobs 
                WHERE id = %s AND employer_id = %s
                  AND (is_deleted = FALSE OR is_deleted IS NULL)
            """, (job_id, employer_id))
            job = cur.fetchone()
            if not job:
                return jsonify({'success': False, 'message': 'Job not found or unauthorized'}), 403

        # Check if candidate_job_matches has records for this job
        cur.execute("SELECT COUNT(*) AS cnt FROM candidate_job_matches WHERE job_id = %s", (job_id,))
        count_row = cur.fetchone()
        needs_refresh = (count_row and count_row['cnt'] == 0) or force_refresh

    # Refresh match table outside read snapshot to ensure committed records are visible
    if needs_refresh:
        refresh_job_candidate_matches(job_id)

    # Query ranked candidates from cache table in a fresh transaction
    with db_cursor() as cur:
        cur.execute("""
            SELECT 
                m.candidate_id, m.final_score, m.skill_score, m.semantic_score,
                m.experience_score, m.education_score, m.location_score,
                m.matched_skills, m.missing_skills, m.computed_at,
                u.name, u.email, u.mobile,
                COALESCE(cp.headline, u.headline, 'Software Professional') AS headline,
                COALESCE(cp.skills, u.skills, '') AS skills,
                cp.profile_photo,
                COALESCE(cpd.current_location, u.location, 'Remote / Pan India') AS location,
                cpref.open_to_relocate,
                cpref.notice_period,
                cpref.current_job_role
            FROM candidate_job_matches m
            JOIN user u ON m.candidate_id = u.id
            LEFT JOIN candidate_profile cp ON u.id = cp.user_id
            LEFT JOIN candidate_personal_details cpd ON u.id = cpd.user_id
            LEFT JOIN candidate_preferences cpref ON u.id = cpref.user_id
            WHERE m.job_id = %s
              AND (u.is_banned = FALSE OR u.is_banned IS NULL)
              AND (u.is_deleted = FALSE OR u.is_deleted IS NULL)
            ORDER BY m.final_score DESC
            LIMIT 50
        """, (job_id,))
        raw_candidates = cur.fetchall()

        cand_ids = [r['candidate_id'] for r in raw_candidates]
        emp_by_cand = {}
        edu_by_cand = {}
        if cand_ids:
            format_strings = ','.join(['%s'] * len(cand_ids))
            cur.execute(f"""
                SELECT user_id, start_date, end_date, is_current, job_title, company_name
                FROM employment WHERE user_id IN ({format_strings})
                ORDER BY is_current DESC, id DESC
            """, tuple(cand_ids))
            for emp in cur.fetchall():
                emp_by_cand.setdefault(emp['user_id'], []).append(emp)

            cur.execute(f"""
                SELECT user_id, course_degree, specialization, institute, education_level
                FROM education WHERE user_id IN ({format_strings})
                ORDER BY id DESC
            """, tuple(cand_ids))
            for edu in cur.fetchall():
                edu_by_cand.setdefault(edu['user_id'], []).append(edu)

    candidates_out = []
    for r in raw_candidates:
        cand_id = r['candidate_id']
        cand_name = r.get('name') or 'Candidate'
        cand_headline = r.get('headline') or 'Software Professional'
        cand_loc = r.get('location') or 'Remote / Pan India'
        cand_skills = r.get('skills') or ''
        
        # Calculate experience years from employment records
        c_emps = emp_by_cand.get(cand_id, [])
        total_months = 0
        from datetime import datetime, date
        for emp in c_emps:
            s_date = emp.get('start_date')
            e_date = emp.get('end_date')
            if s_date:
                start_dt = datetime.strptime(str(s_date)[:10], '%Y-%m-%d') if isinstance(s_date, (str, date)) else s_date
                if emp.get('is_current'):
                    end_dt = datetime.now()
                elif e_date:
                    end_dt = datetime.strptime(str(e_date)[:10], '%Y-%m-%d') if isinstance(e_date, (str, date)) else e_date
                else:
                    end_dt = datetime.now()
                try:
                    months = (end_dt.year - start_dt.year) * 12 + (end_dt.month - start_dt.month)
                    total_months += max(0, months)
                except Exception:
                    pass
        cand_exp_years = round(total_months / 12.0, 1)
        if cand_exp_years > 0:
            cand_exp_text = f"{cand_exp_years:g} Years"
        else:
            cand_exp_text = "Fresher / Entry"

        # Education summary
        c_edus = edu_by_cand.get(cand_id, [])
        cand_edu_text = ""
        if c_edus:
            top_edu = c_edus[0]
            deg = top_edu.get('course_degree') or top_edu.get('education_level') or ''
            spec = top_edu.get('specialization') or ''
            inst = top_edu.get('institute') or ''
            cand_edu_text = f"{deg} {spec}".strip()
            if inst:
                cand_edu_text += f" - {inst}"
        if not cand_edu_text:
            cand_edu_text = "Degree / Professional"

        # Parse matched and missing skills
        matched_list = [s.strip() for s in (r.get('matched_skills') or '').split(',') if s.strip()]
        missing_list = [s.strip() for s in (r.get('missing_skills') or '').split(',') if s.strip()]
        
        final_score_val = float(r.get('final_score') or 0)
        
        # Apply secondary filters if provided
        if query_text:
            combined_text = f"{cand_name} {cand_headline} {cand_loc} {cand_skills} {cand_edu_text}".lower()
            if query_text not in combined_text:
                continue

        if skill_filter:
            if skill_filter not in cand_skills.lower() and not any(skill_filter in m.lower() for m in matched_list):
                continue

        if exp_filter:
            if exp_filter == '0-2' and cand_exp_years > 2.0:
                continue
            elif exp_filter == '2-5' and (cand_exp_years <= 2.0 or cand_exp_years > 5.0):
                continue
            elif exp_filter == '5+' and cand_exp_years <= 5.0:
                continue

        if loc_filter:
            if loc_filter not in cand_loc.lower():
                continue

        candidates_out.append({
            'id': cand_id,
            'candidate_id': cand_id,
            'name': cand_name,
            'headline': cand_headline,
            'location': cand_loc,
            'skills': cand_skills,
            'experience_years': cand_exp_years,
            'experience_text': cand_exp_text,
            'education_text': cand_edu_text,
            'final_score': final_score_val,
            'match_score': f"{int(round(final_score_val))}%",
            'score_breakdown': {
                'skills': int(round(float(r.get('skill_score') or 0))),
                'relevance': int(round(float(r.get('semantic_score') or 0))),
                'experience': int(round(float(r.get('experience_score') or 0))),
                'education': int(round(float(r.get('education_score') or 0))),
                'location': int(round(float(r.get('location_score') or 0)))
            },
            'matched_skills': matched_list,
            'missing_skills': missing_list,
            'open_to_relocate': bool(r.get('open_to_relocate')),
            'notice_period': r.get('notice_period') or 'Immediate',
            'computed_at': r['computed_at'].strftime('%Y-%m-%d %H:%M') if r.get('computed_at') else ''
        })

    return jsonify({
        'success': True,
        'job': {
            'id': job['id'],
            'title': job['title'],
            'location': job.get('location') or 'Remote / Any',
            'category': job.get('category') or 'General',
            'skills': job.get('skills') or '',
            'experience': job.get('experience') or '0'
        },
        'candidates': candidates_out,
        'total': len(candidates_out)
    })


@app.route('/api/recruiter/candidate/<int:candidate_id>', methods=['GET'])
def api_recruiter_candidate_detail(candidate_id):
    """Returns candidate profile, employment, education, and skills details for recruiter inspection."""
    if 'employer_id' not in session:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401

    with db_cursor() as cur:
        cur.execute("""
            SELECT u.id, u.name, u.email, u.mobile, u.headline, u.skills, u.location,
                   cp.summary AS profile_summary, cp.profile_photo, cp.github_url, cp.linkedin_url, cp.portfolio_url,
                   cpd.current_location, cpd.gender,
                   cpref.desired_job_type AS preferred_job_type, cpref.expected_ctc AS expected_salary,
                   cpref.notice_period, cpref.open_to_relocate, cpref.current_job_role
            FROM user u
            LEFT JOIN candidate_profile cp ON u.id = cp.user_id
            LEFT JOIN candidate_personal_details cpd ON u.id = cpd.user_id
            LEFT JOIN candidate_preferences cpref ON u.id = cpref.user_id
            WHERE u.id = %s
              AND (u.is_banned = FALSE OR u.is_banned IS NULL)
              AND (u.is_deleted = FALSE OR u.is_deleted IS NULL)
        """, (candidate_id,))
        user_row = cur.fetchone()
        if not user_row:
            return jsonify({'success': False, 'message': 'Candidate not found'}), 404

        cur.execute("""
            SELECT summary FROM candidate_profile_summary WHERE user_id = %s
        """, (candidate_id,))
        summary_row = cur.fetchone()

        cur.execute("""
            SELECT id, company_name, job_title, start_date, end_date, is_current, skills_used, job_profile AS description
            FROM employment WHERE user_id = %s ORDER BY is_current DESC, id DESC
        """, (candidate_id,))
        employment_list = cur.fetchall()

        cur.execute("""
            SELECT id, education_level, course_degree, specialization, institute, year_of_passing, grade_value AS percentage_cgpa
            FROM education WHERE user_id = %s ORDER BY id DESC
        """, (candidate_id,))
        education_list = cur.fetchall()

        cur.execute("SELECT skill_name FROM key_skills WHERE user_id = %s", (candidate_id,))
        key_skills = [k['skill_name'] for k in cur.fetchall() if k.get('skill_name')]

        cur.execute("SELECT skill_name, experience_years, proficiency FROM it_skills WHERE user_id = %s", (candidate_id,))
        it_skills = cur.fetchall()

        cur.execute("""
            SELECT id, title AS project_title, client_name AS client, start_date, end_date, role AS role_description, technology_tags AS skills_used
            FROM projects WHERE user_id = %s ORDER BY id DESC
        """, (candidate_id,))
        projects_list = cur.fetchall()

    for item in employment_list:
        if item.get('start_date'):
            item['start_date'] = str(item['start_date'])[:10]
        if item.get('end_date'):
            item['end_date'] = str(item['end_date'])[:10]

    for item in projects_list:
        if item.get('start_date'):
            item['start_date'] = str(item['start_date'])[:10]
        if item.get('end_date'):
            item['end_date'] = str(item['end_date'])[:10]

    summary_text = summary_row.get('summary') if summary_row else (user_row.get('profile_summary') or '')

    # Record verified profile view by recruiter
    if 'employer_id' in session:
        record_profile_view(candidate_id, session['employer_id'])

    return jsonify({
        'success': True,
        'candidate': {
            'id': user_row['id'],
            'name': user_row.get('name') or 'Candidate',
            'email': user_row.get('email') or '',
            'mobile': user_row.get('mobile') or '',
            'headline': user_row.get('headline') or 'Software Professional',
            'skills': user_row.get('skills') or '',
            'summary': summary_text,
            'location': user_row.get('current_location') or user_row.get('location') or 'Remote / Pan India',
            'profile_photo': user_row.get('profile_photo') or '',
            'github_url': user_row.get('github_url') or '',
            'linkedin_url': user_row.get('linkedin_url') or '',
            'portfolio_url': user_row.get('portfolio_url') or '',
            'notice_period': user_row.get('notice_period') or 'Immediate',
            'open_to_relocate': bool(user_row.get('open_to_relocate')),
            'expected_salary': user_row.get('expected_salary') or '',
            'preferred_job_type': user_row.get('preferred_job_type') or '',
            'employment': employment_list,
            'education': education_list,
            'key_skills': key_skills,
            'it_skills': it_skills,
            'projects': projects_list
        }
    })


# ==================================================
# DIRECT RECRUITER INTERVIEWS SYSTEM
# ==================================================

def send_interview_email(recipient_email, subject, body_text):
    """Safely sends interview update/confirmation emails via SMTP if configured."""
    if not recipient_email or not validate_email(recipient_email):
        return False
    if not EMAIL_ADDRESS or not EMAIL_PASSWORD:
        logger.info(f"[Email Notification (Simulated)] To: {recipient_email} | Subject: {subject}")
        return True

    try:
        msg = EmailMessage()
        msg.set_content(body_text)
        msg['Subject'] = subject
        msg['From'] = EMAIL_ADDRESS
        msg['To'] = recipient_email

        smtp_host = os.getenv('SMTP_HOST', 'smtp.gmail.com')
        smtp_port_587 = int(os.getenv('SMTP_PORT_STARTTLS', '587'))
        smtp_port_465 = int(os.getenv('SMTP_PORT_SSL', '465'))
        smtp_timeout = int(os.getenv('SMTP_TIMEOUT', '10'))

        for port, use_ssl in [(smtp_port_587, False), (smtp_port_465, True)]:
            try:
                if use_ssl:
                    with smtplib.SMTP_SSL(smtp_host, port, timeout=smtp_timeout) as smtp:
                        smtp.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
                        smtp.send_message(msg)
                else:
                    with smtplib.SMTP(smtp_host, port, timeout=smtp_timeout) as smtp:
                        smtp.ehlo()
                        smtp.starttls()
                        smtp.ehlo()
                        smtp.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
                        smtp.send_message(msg)
                logger.info(f"Interview email delivered successfully to {recipient_email}")
                return True
            except Exception as ex:
                logger.warning(f"SMTP retry failed on port {port}: {ex}")
                continue
    except Exception as e:
        logger.error(f"Error in send_interview_email: {e}")
    return False


def check_interview_conflict(candidate_id, employer_id, scheduled_date, scheduled_time, duration_minutes=30, exclude_interview_id=None):
    """
    Checks for overlapping interviews for either candidate or employer.
    Returns (has_conflict, conflict_message).
    """
    try:
        if isinstance(scheduled_date, str):
            sched_date = datetime.strptime(scheduled_date, '%Y-%m-%d').date()
        else:
            sched_date = scheduled_date

        if isinstance(scheduled_time, str):
            tparts = scheduled_time.split(':')
            sched_time = dt_time(int(tparts[0]), int(tparts[1]))
        elif isinstance(scheduled_time, timedelta):
            total_secs = int(scheduled_time.total_seconds())
            sched_time = dt_time(total_secs // 3600, (total_secs % 3600) // 60)
        else:
            sched_time = scheduled_time

        proposed_start = datetime.combine(sched_date, sched_time)
        duration = int(duration_minutes or 30)
        proposed_end = proposed_start + timedelta(minutes=duration)

        # Disallow past booking (allow 5 min clock buffer)
        if proposed_start < (datetime.utcnow() - timedelta(minutes=5)):
            return True, "Cannot schedule an interview in the past. Please select a future date and time."

        with db_cursor() as cursor:
            query = """
                SELECT id, candidate_id, employer_id, scheduled_date, scheduled_time, duration_minutes, title, status
                FROM interviews
                WHERE scheduled_date = %s 
                  AND status IN ('Pending', 'Accepted', 'Scheduled')
            """
            params = [sched_date]
            if exclude_interview_id:
                query += " AND id != %s"
                params.append(exclude_interview_id)

            cursor.execute(query, tuple(params))
            existing_list = cursor.fetchall()

            for iv in existing_list:
                iv_dur = int(iv.get('duration_minutes') or 30)
                iv_tval = iv['scheduled_time']
                if isinstance(iv_tval, timedelta):
                    total_s = int(iv_tval.total_seconds())
                    iv_t = dt_time(total_s // 3600, (total_s % 3600) // 60)
                elif isinstance(iv_tval, str):
                    tp = iv_tval.split(':')
                    iv_t = dt_time(int(tp[0]), int(tp[1]))
                else:
                    iv_t = iv_tval

                iv_start = datetime.combine(iv['scheduled_date'], iv_t)
                iv_end = iv_start + timedelta(minutes=iv_dur)

                # Overlap check
                if max(proposed_start, iv_start) < min(proposed_end, iv_end):
                    if iv['candidate_id'] == candidate_id:
                        return True, f"Conflict: Candidate already has an interview booked from {iv_start.strftime('%I:%M %p')} to {iv_end.strftime('%I:%M %p')} on this date."
                    if iv['employer_id'] == employer_id:
                        return True, f"Conflict: You already have an interview scheduled from {iv_start.strftime('%I:%M %p')} to {iv_end.strftime('%I:%M %p')} on this date."

        return False, None
    except Exception as e:
        logger.error(f"Error checking interview conflicts: {e}")
        return False, None


# --- CANDIDATE INTERVIEW ROUTES ---

@app.route('/candidate/interviews')
@app.route('/my-interviews')
def candidate_interviews_page():
    """Renders the Candidate Interview Coordination Dashboard."""
    if 'user_id' not in session:
        flash("Please sign in to view your interview schedule", "info")
        return redirect(url_for('index'))
    return render_template('candidate_interview.html')


@app.route('/api/candidate/interviews', methods=['GET'])
def api_candidate_interviews():
    """Fetches candidate interviews grouped by status categories."""
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401

    user_id = session['user_id']
    with db_cursor() as cursor:
        cursor.execute("""
            SELECT i.id, i.job_id, j.title AS job_title, j.location AS job_location,
                   i.employer_id, e.company_name, e.email AS employer_email, e.mobile AS company_phone,
                   i.title AS interview_title, i.scheduled_date, i.scheduled_time, i.duration_minutes,
                   i.meeting_link, i.interview_type, i.status, i.interviewer_notes, i.candidate_feedback,
                   i.created_at, i.cancelled_at
            FROM interviews i
            JOIN jobs j ON i.job_id = j.id
            JOIN employee e ON i.employer_id = e.id
            WHERE i.candidate_id = %s
            ORDER BY i.scheduled_date DESC, i.scheduled_time DESC
        """, (user_id,))
        rows = cursor.fetchall()

    interviews_list = []
    for r in rows:
        sched_date_str = r['scheduled_date'].strftime('%Y-%m-%d') if r.get('scheduled_date') else ''
        sched_date_display = r['scheduled_date'].strftime('%b %d, %Y') if r.get('scheduled_date') else ''
        time_val = r.get('scheduled_time')
        if isinstance(time_val, timedelta):
            total_secs = int(time_val.total_seconds())
            t_obj = dt_time(total_secs // 3600, (total_secs % 3600) // 60)
            time_display = t_obj.strftime('%I:%M %p')
            time_str = t_obj.strftime('%H:%M')
        elif isinstance(time_val, dt_time):
            time_display = time_val.strftime('%I:%M %p')
            time_str = time_val.strftime('%H:%M')
        else:
            time_display = str(time_val or '')
            time_str = str(time_val or '')

        interviews_list.append({
            'id': r['id'],
            'job_id': r['job_id'],
            'job_title': r['job_title'],
            'job_location': r['job_location'],
            'company_name': r['company_name'],
            'employer_email': r['employer_email'],
            'company_phone': r['company_phone'],
            'interview_title': r['interview_title'] or f"Interview with {r['company_name']}",
            'scheduled_date': sched_date_str,
            'scheduled_date_display': sched_date_display,
            'scheduled_time': time_str,
            'scheduled_time_display': time_display,
            'duration_minutes': r['duration_minutes'] or 30,
            'meeting_link': r['meeting_link'] or '',
            'interview_type': r['interview_type'] or 'Video Interview',
            'status': r['status'],
            'interviewer_notes': r['interviewer_notes'] or '',
            'candidate_feedback': r['candidate_feedback'] or '',
            'created_at': r['created_at'].strftime('%Y-%m-%d %H:%M') if r.get('created_at') else ''
        })

    return jsonify({
        'success': True,
        'interviews': interviews_list,
        'total_count': len(interviews_list)
    })


@app.route('/api/candidate/interviews/<int:interview_id>/respond', methods=['POST'])
def api_candidate_interview_respond(interview_id):
    """Candidate accepts or declines an interview invitation."""
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401

    user_id = session['user_id']
    data = request.get_json(silent=True) or {}
    action = (data.get('action') or '').strip().lower() # 'accept' or 'decline'
    notes = sanitize_text((data.get('notes') or '')).strip()

    if action not in ('accept', 'decline'):
        return jsonify({'success': False, 'message': 'Invalid response action'}), 400

    with db_cursor() as cursor:
        cursor.execute("""
            SELECT i.*, j.title AS job_title, e.company_name, e.email AS employer_email,
                   u.name AS candidate_name, u.email AS candidate_email
            FROM interviews i
            JOIN jobs j ON i.job_id = j.id
            JOIN employee e ON i.employer_id = e.id
            JOIN user u ON i.candidate_id = u.id
            WHERE i.id = %s AND i.candidate_id = %s
        """, (interview_id, user_id))
        interview = cursor.fetchone()

        if not interview:
            return jsonify({'success': False, 'message': 'Interview invitation not found'}), 404

        new_status = 'Accepted' if action == 'accept' else 'Declined'
        cursor.execute("""
            UPDATE interviews 
            SET status = %s, candidate_feedback = %s, updated_at = NOW()
            WHERE id = %s
        """, (new_status, notes or None, interview_id))

    # Log candidate activity
    log_activity('user', user_id, f"interview_{action}", target_type='interview', target_id=interview_id, details=f"Candidate {new_status.lower()} interview for {interview['job_title']} with {interview['company_name']}")

    # Notify recruiter via email & in-app
    sched_date_str = interview['scheduled_date'].strftime('%b %d, %Y') if interview.get('scheduled_date') else ''
    notify_subject = f"Interview {new_status}: {interview['candidate_name']} — {interview['job_title']}"
    notify_body = f"""Hello {interview['company_name']} Recruiting Team,

Candidate {interview['candidate_name']} ({interview['candidate_email']}) has {new_status.upper()} the interview invitation for {interview['job_title']}.

Interview Details:
- Date: {sched_date_str}
- Time: {interview['scheduled_time']}
- Status: {new_status}
- Notes: {notes or 'No additional notes provided.'}

Manage your interviews on HireVoltz Employer Portal:
{request.host_url}recruiter/interviews

Best regards,
HireVoltz Talent Operations"""

    send_interview_email(interview['employer_email'], notify_subject, notify_body)

    return jsonify({
        'success': True,
        'message': f"Interview invitation successfully {new_status.lower()}ed.",
        'status': new_status
    })


# --- RECRUITER INTERVIEW ROUTES ---

@app.route('/recruiter/interviews')
@app.route('/employer/interviews')
def recruiter_interviews():
    """Renders the Recruiter Interview Coordinator Dashboard."""
    if 'employer_id' not in session:
        flash("Please sign in as an employer to access interview coordination", "info")
        return redirect(url_for('index'))
    return render_template('recruiter_interviews.html')


@app.route('/api/recruiter/interviews', methods=['GET'])
def api_recruiter_interviews():
    """Returns list of interviews scheduled by this employer with stats."""
    if 'employer_id' not in session:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401

    employer_id = session['employer_id']
    with db_cursor() as cursor:
        cursor.execute("""
            SELECT i.id, i.job_id, j.title AS job_title, j.location AS job_location,
                   i.candidate_id, u.name AS candidate_name, u.email AS candidate_email, u.mobile AS candidate_phone,
                   i.title AS interview_title, i.scheduled_date, i.scheduled_time, i.duration_minutes,
                   i.meeting_link, i.interview_type, i.status, i.interviewer_notes, i.candidate_feedback,
                   i.created_at, i.cancelled_at
            FROM interviews i
            JOIN jobs j ON i.job_id = j.id
            JOIN user u ON i.candidate_id = u.id
            WHERE i.employer_id = %s
            ORDER BY i.scheduled_date DESC, i.scheduled_time DESC
        """, (employer_id,))
        rows = cursor.fetchall()

    interviews_list = []
    stats = {'total': len(rows), 'upcoming': 0, 'pending': 0, 'completed': 0, 'cancelled': 0}
    now_date = datetime.utcnow().date()

    for r in rows:
        sched_date_str = r['scheduled_date'].strftime('%Y-%m-%d') if r.get('scheduled_date') else ''
        sched_date_display = r['scheduled_date'].strftime('%b %d, %Y') if r.get('scheduled_date') else ''
        time_val = r.get('scheduled_time')
        if isinstance(time_val, timedelta):
            total_secs = int(time_val.total_seconds())
            t_obj = dt_time(total_secs // 3600, (total_secs % 3600) // 60)
            time_display = t_obj.strftime('%I:%M %p')
            time_str = t_obj.strftime('%H:%M')
        elif isinstance(time_val, dt_time):
            time_display = time_val.strftime('%I:%M %p')
            time_str = time_val.strftime('%H:%M')
        else:
            time_display = str(time_val or '')
            time_str = str(time_val or '')

        status_norm = (r['status'] or 'Scheduled').capitalize()
        if status_norm in ('Pending', 'Awaiting'):
            stats['pending'] += 1
        elif status_norm in ('Accepted', 'Scheduled'):
            if r.get('scheduled_date') and r['scheduled_date'] >= now_date:
                stats['upcoming'] += 1
            else:
                stats['completed'] += 1
        elif status_norm == 'Completed':
            stats['completed'] += 1
        elif status_norm in ('Cancelled', 'Declined'):
            stats['cancelled'] += 1

        interviews_list.append({
            'id': r['id'],
            'job_id': r['job_id'],
            'job_title': r['job_title'],
            'job_location': r['job_location'],
            'candidate_id': r['candidate_id'],
            'candidate_name': r['candidate_name'],
            'candidate_email': r['candidate_email'],
            'candidate_phone': r['candidate_phone'] or '',
            'interview_title': r['interview_title'] or f"Interview with {r['candidate_name']}",
            'scheduled_date': sched_date_str,
            'scheduled_date_display': sched_date_display,
            'scheduled_time': time_str,
            'scheduled_time_display': time_display,
            'duration_minutes': r['duration_minutes'] or 30,
            'meeting_link': r['meeting_link'] or '',
            'interview_type': r['interview_type'] or 'Video Interview',
            'status': r['status'],
            'interviewer_notes': r['interviewer_notes'] or '',
            'candidate_feedback': r['candidate_feedback'] or '',
            'created_at': r['created_at'].strftime('%Y-%m-%d %H:%M') if r.get('created_at') else ''
        })

    return jsonify({
        'success': True,
        'interviews': interviews_list,
        'stats': stats
    })


@app.route('/api/recruiter/candidates_for_interview', methods=['GET'])
def api_recruiter_candidates_for_interview():
    """Returns candidate options and employer jobs for the interview scheduling modal."""
    if 'employer_id' not in session:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401

    employer_id = session['employer_id']
    with db_cursor() as cursor:
        # Employer active jobs
        cursor.execute("SELECT id, title, location, category FROM jobs WHERE employer_id = %s ORDER BY id DESC", (employer_id,))
        jobs = cursor.fetchall()

        # Candidates who applied to this employer's jobs or registered users
        cursor.execute("""
            SELECT DISTINCT u.id, u.name, u.email, u.mobile AS phone, j.id AS applied_job_id, j.title AS applied_job_title
            FROM user u
            LEFT JOIN applications a ON u.id = a.user_id
            LEFT JOIN jobs j ON a.job_id = j.id AND j.employer_id = %s
            ORDER BY u.name ASC
            LIMIT 50
        """, (employer_id,))
        candidates = cursor.fetchall()

    return jsonify({
        'success': True,
        'jobs': jobs,
        'candidates': candidates
    })


@app.route('/api/recruiter/interviews/schedule', methods=['POST'])
def api_recruiter_interview_schedule():
    """Schedules a new interview with conflict validation."""
    if 'employer_id' not in session:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401

    employer_id = session['employer_id']
    data = request.get_json(silent=True) or {}

    candidate_id = data.get('candidate_id') or data.get('user_id')
    job_id = data.get('job_id')
    title = sanitize_text((data.get('title') or 'Technical Evaluation Interview')).strip()
    scheduled_date = sanitize_text((data.get('scheduled_date') or '')).strip()
    scheduled_time = sanitize_text((data.get('scheduled_time') or '')).strip()
    try:
        duration_minutes = max(5, min(480, int(data.get('duration_minutes') or 30)))
    except (TypeError, ValueError):
        duration_minutes = 30
    meeting_link = sanitize_text((data.get('meeting_link') or '')).strip()
    interview_type = sanitize_text((data.get('interview_type') or 'Video Interview')).strip()
    notes = sanitize_text((data.get('notes') or '')).strip()

    if not candidate_id and data.get('candidate_email'):
        with db_cursor() as cursor:
            cursor.execute("SELECT id FROM user WHERE email = %s", (data.get('candidate_email'),))
            c_row = cursor.fetchone()
            if c_row:
                candidate_id = c_row['id']

    if not candidate_id or not job_id or not scheduled_date or not scheduled_time:
        return jsonify({'success': False, 'message': 'Candidate, Job, Date, and Start Time are required.'}), 400

    # 1. Validate Job belongs to employer
    with db_cursor() as cursor:
        cursor.execute("""
            SELECT j.id, j.title, COALESCE(e.company_name, j.company_name) AS company_name
            FROM jobs j
            LEFT JOIN employee e ON j.employer_id = e.id
            WHERE j.id = %s AND j.employer_id = %s
        """, (job_id, employer_id))
        job = cursor.fetchone()
        if not job:
            return jsonify({'success': False, 'message': 'Selected job not found or unauthorized.'}), 404

        cursor.execute("SELECT id, name, email FROM user WHERE id = %s", (candidate_id,))
        candidate = cursor.fetchone()
        if not candidate:
            return jsonify({'success': False, 'message': 'Selected candidate not found.'}), 404

        cursor.execute("SELECT company_name, email FROM employee WHERE id = %s", (employer_id,))
        employer_row = cursor.fetchone()

    # 2. Check for Schedule Conflicts
    has_conflict, conflict_msg = check_interview_conflict(
        candidate_id=candidate_id,
        employer_id=employer_id,
        scheduled_date=scheduled_date,
        scheduled_time=scheduled_time,
        duration_minutes=duration_minutes
    )
    if has_conflict:
        return jsonify({'success': False, 'message': conflict_msg, 'conflict': True}), 409

    # 3. Insert Interview Record
    with db_cursor() as cursor:
        cursor.execute("""
            INSERT INTO interviews 
            (job_id, employer_id, candidate_id, title, scheduled_date, scheduled_time, duration_minutes, meeting_link, interview_type, status, interviewer_notes)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'Pending', %s)
        """, (job_id, employer_id, candidate_id, title, scheduled_date, scheduled_time, duration_minutes, meeting_link or None, interview_type, notes or None))
        interview_id = cursor.lastrowid

    # 4. Notify Candidate & Employer
    company_name = (employer_row.get('company_name') if employer_row else None) or job.get('company_name') or 'HireVoltz Verified Partner'
    notify_msg = f"New interview proposed: {title} with {company_name} for role {job['title']} on {scheduled_date} at {scheduled_time}."
    create_notification(
        user_id=candidate_id,
        notification_type='interview_invitation',
        title='Interview Invitation Scheduled 📅',
        message=notify_msg,
        action_url='/candidate/interviews'
    )
    create_notification(
        employer_id=employer_id,
        notification_type='interview_scheduled',
        title='Interview Confirmed 📅',
        message=f"Interview with {candidate['name']} scheduled for '{job['title']}' on {scheduled_date} at {scheduled_time}.",
        action_url='/recruiter/interviews'
    )

    # 5. Send Email Invitation
    email_subject = f"Interview Invitation: {job['title']} at {company_name}"
    email_body = f"""Dear {candidate['name']},

You have received an interview invitation from {company_name} for the position of {job['title']}.

Interview Details:
- Title: {title}
- Date: {scheduled_date}
- Start Time: {scheduled_time}
- Duration: {duration_minutes} minutes
- Format: {interview_type}
- Meeting Link: {meeting_link or 'Will be provided prior to call'}
- Recruiter Notes: {notes or 'None'}

Please accept or decline this invitation directly from your HireVoltz Interview Dashboard:
{request.host_url}candidate/interviews

Best regards,
{company_name} Recruitment Team & HireVoltz Talent Ops"""

    send_interview_email(candidate['email'], email_subject, email_body)

    return jsonify({
        'success': True,
        'message': 'Interview proposal sent to candidate successfully.',
        'interview_id': interview_id
    })


@app.route('/api/recruiter/interviews/<int:interview_id>/reschedule', methods=['POST'])
def api_recruiter_interview_reschedule(interview_id):
    """Reschedules an existing interview with conflict validation."""
    if 'employer_id' not in session:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401

    employer_id = session['employer_id']
    data = request.get_json(silent=True) or {}

    scheduled_date = sanitize_text((data.get('scheduled_date') or '')).strip()
    scheduled_time = sanitize_text((data.get('scheduled_time') or '')).strip()
    try:
        duration_minutes = max(5, min(480, int(data.get('duration_minutes') or 30)))
    except (TypeError, ValueError):
        duration_minutes = 30
    meeting_link = sanitize_text((data.get('meeting_link') or '')).strip()
    notes = sanitize_text((data.get('notes') or '')).strip()

    if not scheduled_date or not scheduled_time:
        return jsonify({'success': False, 'message': 'Date and Start Time are required.'}), 400

    with db_cursor() as cursor:
        cursor.execute("""
            SELECT i.*, j.title AS job_title, e.company_name, u.name AS candidate_name, u.email AS candidate_email
            FROM interviews i
            JOIN jobs j ON i.job_id = j.id
            JOIN employee e ON i.employer_id = e.id
            JOIN user u ON i.candidate_id = u.id
            WHERE i.id = %s AND i.employer_id = %s
        """, (interview_id, employer_id))
        iv = cursor.fetchone()

        if not iv:
            return jsonify({'success': False, 'message': 'Interview not found or unauthorized'}), 404

    # Check conflicts for updated time
    has_conflict, conflict_msg = check_interview_conflict(
        candidate_id=iv['candidate_id'],
        employer_id=employer_id,
        scheduled_date=scheduled_date,
        scheduled_time=scheduled_time,
        duration_minutes=duration_minutes,
        exclude_interview_id=interview_id
    )
    if has_conflict:
        return jsonify({'success': False, 'message': conflict_msg, 'conflict': True}), 409

    with db_cursor() as cursor:
        cursor.execute("""
            UPDATE interviews 
            SET scheduled_date = %s, scheduled_time = %s, duration_minutes = %s,
                meeting_link = %s, interviewer_notes = %s, status = 'Pending', updated_at = NOW()
            WHERE id = %s
        """, (scheduled_date, scheduled_time, duration_minutes, meeting_link or iv.get('meeting_link'), notes or iv.get('interviewer_notes'), interview_id))

    # Notify Candidate
    create_notification(
        user_id=iv['candidate_id'],
        notification_type='interview_rescheduled',
        title='Interview Rescheduled 📅',
        message=f"Interview Rescheduled: {iv['company_name']} updated your interview for {iv['job_title']} to {scheduled_date} at {scheduled_time}.",
        action_url='/candidate/interviews'
    )
    
    email_sub = f"Interview Rescheduled: {iv['job_title']} at {iv['company_name']}"
    email_body = f"""Dear {iv['candidate_name']},

Your interview for {iv['job_title']} with {iv['company_name']} has been rescheduled.

Updated Details:
- Date: {scheduled_date}
- Time: {scheduled_time}
- Duration: {duration_minutes} minutes
- Meeting Link: {meeting_link or iv.get('meeting_link') or 'Available on portal'}
- Notes: {notes or 'None'}

Please confirm this new time slot on your HireVoltz Interview Dashboard:
{request.host_url}candidate/interviews

Best regards,
{iv['company_name']} Recruitment Team"""

    send_interview_email(iv['candidate_email'], email_sub, email_body)

    return jsonify({'success': True, 'message': 'Interview rescheduled successfully.'})


@app.route('/api/recruiter/interviews/<int:interview_id>/cancel', methods=['POST'])
def api_recruiter_interview_cancel(interview_id):
    """Cancels an interview (called by employer or candidate)."""
    if 'employer_id' not in session and 'user_id' not in session:
        return jsonify({'error': 'Authentication required.'}), 401

    data = request.get_json(silent=True) or {}
    reason = bleach.clean(str(data.get('reason', 'Cancelled by participant')).strip(), strip=True)

    with db_cursor() as cursor:
        cursor.execute("SELECT * FROM interviews WHERE id = %s", (interview_id,))
        iv = cursor.fetchone()
        if not iv:
            return jsonify({'error': 'Interview not found.'}), 404

        # Validate authorization
        if 'employer_id' in session and iv['employer_id'] != session['employer_id']:
            return jsonify({'error': 'Unauthorized.'}), 403
        if 'user_id' in session and iv['candidate_id'] != session['user_id']:
            return jsonify({'error': 'Unauthorized.'}), 403

        cursor.execute("UPDATE interviews SET status = 'Cancelled' WHERE id = %s", (interview_id,))

        cursor.execute("SELECT name, email FROM user WHERE id = %s", (iv['candidate_id'],))
        candidate = cursor.fetchone()
        cursor.execute("SELECT company_name, email FROM employee WHERE id = %s", (iv['employer_id'],))
        employer = cursor.fetchone()
        cursor.execute("SELECT title FROM jobs WHERE id = %s", (iv['job_id'],))
        job = cursor.fetchone()

    # Notify both
    if candidate:
        notify_user(iv['candidate_id'], f"Interview for {job['title']} has been cancelled: {reason}")
        send_interview_email(
            candidate['email'],
            f"Interview Cancelled: {job['title']}",
            f"Dear {candidate['name']},\n\nThe interview for {job['title']} scheduled on {iv['scheduled_date']} has been cancelled.\nReason: {reason}\n\nBest regards,\n{employer.get('company_name', 'Recruitment Team')}"
        )

    return jsonify({'success': True, 'message': 'Interview cancelled successfully.'})


@app.route('/api/recruiter/interviews/<int:interview_id>/complete', methods=['POST'])
def api_recruiter_interview_complete(interview_id):
    """Marks an interview as Completed with recruiter notes."""
    if 'employer_id' not in session:
        return jsonify({'success': False, 'message': 'Authentication required.'}), 401

    employer_id = session['employer_id']
    data = request.get_json(silent=True) or {}
    notes = (data.get('notes') or '').strip()

    with db_cursor() as cursor:
        cursor.execute("SELECT id FROM interviews WHERE id = %s AND employer_id = %s", (interview_id, employer_id))
        if not cursor.fetchone():
            return jsonify({'success': False, 'message': 'Interview not found'}), 404

        cursor.execute("""
            UPDATE interviews 
            SET status = 'Completed', interviewer_notes = %s, updated_at = NOW()
            WHERE id = %s
        """, (notes or None, interview_id))

    return jsonify({'success': True, 'message': 'Interview marked as completed.'})


# --- CALENDAR INVITE EXPORT (.ICS) ---

@app.route('/interview/<int:interview_id>/calendar.ics')
def interview_calendar_ics(interview_id):
    """Generates an RFC 5545 iCalendar (.ics) invite file for the interview."""
    if 'user_id' not in session and 'employer_id' not in session:
        flash("Please sign in to download calendar invites", "info")
        return redirect(url_for('index'))

    with db_cursor() as cursor:
        cursor.execute("""
            SELECT i.*, j.title AS job_title, e.company_name, e.email AS employer_email,
                   u.name AS candidate_name, u.email AS candidate_email
            FROM interviews i
            JOIN jobs j ON i.job_id = j.id
            JOIN employee e ON i.employer_id = e.id
            JOIN user u ON i.candidate_id = u.id
            WHERE i.id = %s
        """, (interview_id,))
        iv = cursor.fetchone()

    if not iv:
        flash("Interview not found", "error")
        return redirect(url_for('index'))

    if 'user_id' in session and iv['candidate_id'] != session['user_id']:
        flash("Unauthorized", "error")
        return redirect(url_for('candidate_interviews_page'))
    if 'employer_id' in session and iv['employer_id'] != session['employer_id']:
        flash("Unauthorized", "error")
        return redirect(url_for('recruiter_interviews'))

    sched_date = iv['scheduled_date']
    time_val = iv['scheduled_time']
    if isinstance(time_val, timedelta):
        total_secs = int(time_val.total_seconds())
        sched_time = dt_time(total_secs // 3600, (total_secs % 3600) // 60)
    elif isinstance(time_val, str):
        tparts = time_val.split(':')
        sched_time = dt_time(int(tparts[0]), int(tparts[1]))
    else:
        sched_time = time_val

    dt_start = datetime.combine(sched_date, sched_time)
    dt_end = dt_start + timedelta(minutes=iv.get('duration_minutes', 30) or 30)

    dtstart_str = dt_start.strftime('%Y%m%dT%H%M%S')
    dtend_str = dt_end.strftime('%Y%m%dT%H%M%S')
    dtstamp_str = datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')

    title = iv.get('title') or f"Interview: {iv.get('job_title')} at {iv.get('company_name')}"
    meeting_url = iv.get('meeting_link') or "https://meet.google.com"
    desc = f"Interview with {iv.get('company_name')} for role: {iv.get('job_title')}.\\nMeeting Link: {meeting_url}"

    ics_content = f"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//HireVoltz//Interview Coordination System//EN
CALSCALE:GREGORIAN
METHOD:REQUEST
BEGIN:VEVENT
UID:interview-{iv['id']}@hirevoltz.internal
DTSTAMP:{dtstamp_str}
DTSTART:{dtstart_str}
DTEND:{dtend_str}
SUMMARY:{title}
DESCRIPTION:{desc}
LOCATION:{meeting_url}
STATUS:CONFIRMED
ORGANIZER;CN={iv.get('company_name')}:MAILTO:{iv.get('employer_email')}
ATTENDEE;ROLE=REQ-PARTICIPANT;PARTSTAT=ACCEPTED;CN={iv.get('candidate_name')}:MAILTO:{iv.get('candidate_email')}
END:VEVENT
END:VCALENDAR"""

    response = make_response(ics_content)
    response.headers['Content-Type'] = 'text/calendar; charset=utf-8'
    response.headers['Content-Disposition'] = f'attachment; filename=interview_{iv["id"]}.ics'
    return response

@app.route('/recruiter/analytics')
def recruiter_analytics():
    if 'employer_id' not in session: return redirect(url_for('index'))
    return render_template('employer_dashboard.html')

@app.route('/recruiter/analytics/jobs')
def recruiter_analytics_jobs():
    if 'employer_id' not in session: return redirect(url_for('index'))
    return redirect(url_for('recruiter_analytics'))

@app.route('/recruiter/analytics/funnel')
def recruiter_analytics_funnel():
    if 'employer_id' not in session: return redirect(url_for('index'))
    return redirect(url_for('recruiter_analytics'))

@app.route('/recruiter/analytics/sources')
def recruiter_analytics_sources():
    if 'employer_id' not in session: return redirect(url_for('index'))
    return redirect(url_for('recruiter_analytics'))

@app.route('/recruiter/analytics/time-to-hire')
def recruiter_analytics_time_to_hire():
    if 'employer_id' not in session: return redirect(url_for('index'))
    return redirect(url_for('recruiter_analytics'))

@app.route('/recruiter/analytics/export')
def recruiter_analytics_export():
    if 'employer_id' not in session: return redirect(url_for('index'))
    return redirect(url_for('recruiter_analytics'))

@app.route('/recruiter/company-profile')
@app.route('/recruiter_company_profile')
def recruiter_company_profile():
    if 'employer_id' not in session: return redirect(url_for('index'))
    return render_template('recruiter_company_profile.html')

@app.route('/recruiter/company-profile/edit')
def recruiter_company_profile_edit():
    if 'employer_id' not in session: return redirect(url_for('index'))
    return render_template('recruiter_company_profile.html')

@app.route('/recruiter/company-profile/team')
def recruiter_company_profile_team():
    if 'employer_id' not in session: return redirect(url_for('index'))
    return render_template('recruiter_company_profile.html')

@app.route('/recruiter/company-profile/media')
def recruiter_company_profile_media():
    if 'employer_id' not in session: return redirect(url_for('index'))
    return render_template('recruiter_company_profile.html')

@app.route('/recruiter/settings')
def recruiter_settings():
    if 'employer_id' not in session: return redirect(url_for('index'))
    return render_template('recruiter_settings.html')

@app.route('/recruiter/settings/account')
def recruiter_settings_account():
    if 'employer_id' not in session: return redirect(url_for('index'))
    return render_template('recruiter_settings.html')

@app.route('/recruiter/settings/notifications')
def recruiter_settings_notifications():
    if 'employer_id' not in session: return redirect(url_for('index'))
    return render_template('recruiter_settings.html')

@app.route('/recruiter/settings/billing')
def recruiter_settings_billing():
    if 'employer_id' not in session: return redirect(url_for('index'))
    return render_template('recruiter_settings.html')

@app.route('/recruiter/settings/api')
def recruiter_settings_api():
    if 'employer_id' not in session: return redirect(url_for('index'))
    return render_template('recruiter_settings.html')

@app.route('/recruiter/settings/password')
def recruiter_settings_password():
    if 'employer_id' not in session: return redirect(url_for('index'))
    return render_template('recruiter_settings.html')

@app.route('/recruiter/messages')
@app.route('/recruiter/messages/<int:conversation_id>')
@app.route('/recruiter/messages/new')
def recruiter_messages(conversation_id=None):
    if 'employer_id' not in session: return redirect(url_for('index'))
    return render_template('recruiter_messages.html', initial_conversation_id=conversation_id)

@app.route('/recruiter/activity')
def recruiter_activity():
    if 'employer_id' not in session: return redirect(url_for('index'))
    return redirect(url_for('employer_dashboard'))

# ==============================================================================
# HIREVOLTZ UNIFIED ADMIN PANEL & COMPANY VERIFICATION CENTER
# ==============================================================================

# --- ADMIN AUTHENTICATION ENDPOINTS ---

@app.route('/admin/login')
def admin_login_page():
    """Renders the dedicated Admin Login portal."""
    if require_admin():
        return redirect(url_for('admin_dashboard_page'))
    return render_template('admin_login.html')


@app.route('/api/admin/login', methods=['POST'])
@limiter.limit("5 per minute")
def api_admin_login():
    """
    Secure Administrator Login endpoint.
    - Rate limited to 5 attempts per minute.
    - Strict session binding and CSRF protected.
    - Uses Werkzeug password hashing.
    - Records immutable admin audit logs on success/failure.
    """
    data = request.get_json(silent=True) or request.form.to_dict()
    email = normalize_email(data.get('email', ''))
    password = (data.get('password', '') or '').strip()

    if not email or not password:
        return jsonify({'success': False, 'message': 'Administrator email and password are required.'}), 400

    # Account lockout check
    is_locked, minutes_remaining = _is_account_locked(email, 'admin')
    if is_locked:
        return jsonify({
            'success': False,
            'message': f'Admin account is temporarily locked due to repeated failed attempts. Please try again in {minutes_remaining} minutes.'
        }), 429

    with db_cursor() as cur:
        cur.execute("SELECT id, name, email, password, is_admin, session_version FROM user WHERE email = %s", (email,))
        user = cur.fetchone()

    # Fallback/Bootstrap: If matching ADMIN_EMAIL and user exists, ensure is_admin=TRUE
    admin_env_email = os.getenv('ADMIN_EMAIL', 'ccubetech00@gmail.com').strip().lower()
    if user and email == admin_env_email and not user.get('is_admin'):
        with db_cursor(dictionary=False) as cur:
            cur.execute("UPDATE user SET is_admin = TRUE WHERE id = %s", (user['id'],))
        user['is_admin'] = True

    if not user or not user.get('is_admin') or not check_password_hash(user['password'], password):
        attempts, locked, _ = _record_failed_login(email, 'admin')
        _log_login_attempt(email, 'admin', 'FAILED', 'Invalid admin credentials')
        log_admin_audit('admin_login_failed', 'auth', user['id'] if user else None, reason=f'Failed admin login attempt for {email}')
        
        if locked:
            return jsonify({
                'success': False,
                'message': f'Too many failed attempts. Admin login locked for {LOCKOUT_DURATION_MINUTES} minutes.'
            }), 429
        
        remaining = max(0, MAX_FAILED_ATTEMPTS - attempts)
        return jsonify({
            'success': False,
            'message': f'Invalid administrator credentials. ({remaining} attempt{"s" if remaining != 1 else ""} remaining)'
        }), 401

    # Successful Administrator Login
    _reset_login_attempts(email, 'admin', request.remote_addr)
    _log_login_attempt(email, 'admin', 'SUCCESS', 'Admin login successful')

    # Establish clean, hardened admin session
    session.clear()
    session['user_id'] = user['id']
    session['user_name'] = user['name'] or 'HireVoltz Admin'
    session['user_email'] = user['email']
    session['role'] = 'admin'
    session['is_admin'] = True
    session['session_version'] = user.get('session_version', 0)
    session['fingerprint'] = _session_fingerprint()
    session.permanent = True

    log_admin_audit('admin_login', 'auth', user['id'], reason='Administrator login successful')
    logger.info(f"Administrator {email} logged in successfully from {request.remote_addr}")

    next_url = request.args.get('next') or url_for('admin_dashboard_page')
    return jsonify({
        'success': True,
        'message': 'Administrator authentication successful.',
        'redirect': next_url
    })


@app.route('/admin/logout', methods=['GET', 'POST'])
@app.route('/api/admin/logout', methods=['POST'])
def admin_logout():
    """Securely terminates the administrator session and records an audit event."""
    if require_admin():
        log_admin_audit('admin_logout', 'auth', session.get('user_id'), reason='Administrator logged out')
    session.clear()
    if request.is_json or request.path.startswith('/api/') or request.headers.get('Accept') == 'application/json':
        return jsonify({'success': True, 'message': 'Administrator logged out successfully.'})
    flash("You have been securely logged out of the Admin Console.", "info")
    return redirect(url_for('admin_login_page'))


@app.route('/api/admin/change_password', methods=['POST'])
@admin_required
def api_admin_change_password():
    """Updates the administrator password with current password verification and password history protection."""
    data = request.get_json(silent=True) or request.form.to_dict()
    current_password = (data.get('current_password') or '').strip()
    new_password = (data.get('new_password') or '').strip()
    confirm_password = (data.get('confirm_password') or '').strip()

    if not current_password or not new_password:
        return jsonify({'success': False, 'message': 'Current and new passwords are required.'}), 400

    if new_password != confirm_password:
        return jsonify({'success': False, 'message': 'New password and confirmation do not match.'}), 400

    if not validate_password(new_password):
        return jsonify({'success': False, 'message': 'New password must be at least 8 characters with letters and numbers, and not easily guessable.'}), 400

    admin_id = session['user_id']
    with db_cursor() as cur:
        cur.execute("SELECT password, session_version FROM user WHERE id = %s", (admin_id,))
        user = cur.fetchone()

    if not user or not check_password_hash(user['password'], current_password):
        log_admin_audit('admin_password_change_failed', 'admin_user', admin_id, reason='Incorrect current password provided')
        return jsonify({'success': False, 'message': 'Incorrect current password.'}), 400

    if not _check_password_history(admin_id, None, new_password):
        return jsonify({'success': False, 'message': 'You cannot reuse one of your last 5 passwords for security.'}), 400

    new_hash = generate_password_hash(new_password)
    new_version = (user.get('session_version') or 0) + 1

    with db_cursor(dictionary=False) as cur:
        cur.execute("UPDATE user SET password = %s, session_version = %s WHERE id = %s", (new_hash, new_version, admin_id))

    _store_password_history(admin_id, None, new_hash)
    session['session_version'] = new_version
    log_admin_audit('admin_password_changed', 'admin_user', admin_id, reason='Administrator password changed successfully')
    logger.info(f"Admin #{admin_id} changed password successfully.")

    return jsonify({'success': True, 'message': 'Administrator password updated successfully.'})


# --- ADMIN UI PAGE ROUTES ---

@app.route('/admin')
@app.route('/admin_dashboard')
@app.route('/admin/dashboard')
@app.route('/admin/companies')
@app.route('/admin/companies/<int:company_id>')
@app.route('/admin/jobs')
@app.route('/admin/jobs/<int:job_id>')
@app.route('/admin/users')
@app.route('/admin/users/<int:user_id>')
@app.route('/admin/reports')
@app.route('/admin/audit-logs')
@app.route('/admin/settings')
@admin_required
def admin_dashboard_page(company_id=None, job_id=None, user_id=None):
    """Renders the comprehensive HireVoltz Admin Console & Verification Command Center."""
    return render_template('admin_dashboard.html')


@app.route('/admin/users/<int:user_id>/edit')
@admin_required
def admin_user_edit(user_id):
    return render_template('admin_dashboard.html')


@app.route('/admin/reports/<path:subpath>')
@admin_required
def admin_reports_subpaths(subpath):
    return redirect(url_for('admin_dashboard_page'))


@app.route('/admin/settings/<path:subpath>')
@admin_required
def admin_settings_subpaths(subpath):
    return redirect(url_for('admin_dashboard_page'))


# --- ADMIN STATS & KPI ANALYTICS ENDPOINTS ---

@app.route('/api/admin/stats')
@app.route('/api/admin/dashboard_stats')
@admin_required
def api_admin_dashboard_stats():
    """
    Computes real-time platform KPIs, company verification breakdowns,
    active scam/report counts, attention alerts, and analytics charts data.
    """
    with db_cursor() as cur:
        # User counts
        cur.execute("SELECT COUNT(*) AS total FROM user WHERE is_deleted = 0")
        total_users = cur.fetchone()['total']

        # Company verification breakdown
        cur.execute("SELECT COUNT(*) AS total FROM employee")
        total_companies = cur.fetchone()['total']

        cur.execute("SELECT COUNT(*) AS total FROM employee WHERE verification_status = 'verified' OR is_verified = 1")
        verified_companies = cur.fetchone()['total']

        cur.execute("SELECT COUNT(*) AS total FROM employee WHERE verification_status = 'pending'")
        pending_companies = cur.fetchone()['total']

        cur.execute("SELECT COUNT(*) AS total FROM employee WHERE verification_status = 'suspicious'")
        suspicious_companies = cur.fetchone()['total']

        cur.execute("SELECT COUNT(*) AS total FROM employee WHERE verification_status = 'rejected'")
        rejected_companies = cur.fetchone()['total']

        cur.execute("SELECT COUNT(*) AS total FROM employee WHERE (verification_status = 'unverified' OR verification_status IS NULL) AND is_verified = 0")
        unverified_companies = cur.fetchone()['total']

        # Job listings stats
        cur.execute("SELECT COUNT(*) AS total FROM jobs WHERE is_deleted = 0")
        total_jobs = cur.fetchone()['total']

        cur.execute("SELECT COUNT(*) AS total FROM jobs WHERE is_active = 1 AND is_deleted = 0 AND (status = 'Published' OR status IS NULL)")
        active_jobs = cur.fetchone()['total']

        cur.execute("SELECT COUNT(*) AS total FROM jobs WHERE status IN ('Suspicious', 'Rejected') AND is_deleted = 0")
        suspicious_jobs = cur.fetchone()['total']

        # Application stats
        cur.execute("SELECT COUNT(*) AS total FROM applications")
        total_applications = cur.fetchone()['total']

        # Reports stats
        cur.execute("SELECT COUNT(*) AS total FROM reports")
        total_reports = cur.fetchone()['total']

        cur.execute("SELECT COUNT(*) AS total FROM reports WHERE status IN ('OPEN', 'UNDER_REVIEW')")
        open_reports = cur.fetchone()['total']

        cur.execute("SELECT COUNT(*) AS total FROM reports WHERE status IN ('RESOLVED', 'DISMISSED')")
        resolved_reports = cur.fetchone()['total']
        resolution_rate = round((resolved_reports / total_reports) * 100, 1) if total_reports > 0 else 100.0

        # Reports grouped by category
        cur.execute("""
            SELECT category, COUNT(*) AS count
            FROM reports
            GROUP BY category
            ORDER BY count DESC
        """)
        reports_by_category = cur.fetchall()

        # Company Risk Distribution
        cur.execute("SELECT risk_level, COUNT(*) AS count FROM employee GROUP BY risk_level")
        risk_rows = cur.fetchall()
        risk_breakdown = {'low': 0, 'medium': 0, 'high': 0}
        for r in risk_rows:
            k = (r.get('risk_level') or 'low').lower()
            if k in risk_breakdown:
                risk_breakdown[k] = r['count']

        # Attention Alerts: Items requiring urgent admin review
        attention_alerts = []
        if pending_companies > 0:
            attention_alerts.append({
                'type': 'pending_verification',
                'severity': 'warning',
                'title': f"{pending_companies} Company Verification{'s' if pending_companies != 1 else ''} Pending",
                'message': 'Companies have submitted registration profiles awaiting legitimacy review.',
                'action_tab': 'verifications'
            })

        if open_reports > 0:
            attention_alerts.append({
                'type': 'open_reports',
                'severity': 'danger',
                'title': f"{open_reports} Open Candidate Report{'s' if open_reports != 1 else ''}",
                'message': 'Unresolved fraud, spam, or fake listing reports filed by job seekers.',
                'action_tab': 'reports'
            })

        if suspicious_companies > 0:
            attention_alerts.append({
                'type': 'suspicious_companies',
                'severity': 'warning',
                'title': f"{suspicious_companies} Company Flagged as Suspicious",
                'message': 'Accounts marked for elevated monitoring or restricted posting.',
                'action_tab': 'verifications'
            })

        # Recent Audit Logs
        cur.execute("""
            SELECT id, admin_email, action, entity_type, entity_id, previous_status, new_status, reason, ip_address, created_at
            FROM admin_audit_logs
            ORDER BY created_at DESC
            LIMIT 10
        """)
        recent_audits = cur.fetchall()
        for a in recent_audits:
            if a.get('created_at') and hasattr(a['created_at'], 'strftime'):
                a['created_at_fmt'] = a['created_at'].strftime('%Y-%m-%d %H:%M:%S')

    stats_payload = {
        'users': total_users,
        'employers': total_companies,
        'total_companies': total_companies,
        'verified_companies': verified_companies,
        'pending_companies': pending_companies,
        'suspicious_companies': suspicious_companies,
        'rejected_companies': rejected_companies,
        'unverified_companies': unverified_companies,
        'total_jobs': total_jobs,
        'active_jobs': active_jobs,
        'suspicious_jobs': suspicious_jobs,
        'total_applications': total_applications,
        'total_reports': total_reports,
        'open_reports': open_reports,
        'resolved_reports': resolved_reports,
        'resolution_rate': resolution_rate,
        'risk_breakdown': risk_breakdown,
        'status_breakdown': {
            'verified': verified_companies,
            'pending': pending_companies,
            'suspicious': suspicious_companies,
            'rejected': rejected_companies,
            'unverified': unverified_companies
        },
        'reports_by_category': reports_by_category,
        'attention_alerts': attention_alerts,
        'recent_audits': recent_audits
    }

    return jsonify({'success': True, 'stats': stats_payload})


# --- COMPANY VERIFICATION CENTER ENDPOINTS ---

@app.route('/api/admin/companies')
@admin_required
def api_admin_companies():
    """
    Paginated, searchable, and filterable list of all registered companies
    with calculated profile completeness, trust indicators, and automated risk scoring.
    """
    status_filter = (request.args.get('status') or 'all').strip().lower()
    search_query = sanitize_text(request.args.get('search', '')).strip()
    sort_by = (request.args.get('sort') or 'newest').strip().lower()
    page = max(1, request.args.get('page', 1, type=int) or 1)
    per_page = min(100, max(1, request.args.get('per_page', 15, type=int) or 15))
    offset = (page - 1) * per_page

    where_clauses = ["1=1"]
    params = []

    if status_filter and status_filter != 'all':
        if status_filter == 'verified':
            where_clauses.append("(e.verification_status = 'verified' OR e.is_verified = 1)")
        elif status_filter == 'unverified':
            where_clauses.append("((e.verification_status = 'unverified' OR e.verification_status IS NULL) AND e.is_verified = 0)")
        else:
            where_clauses.append("e.verification_status = %s")
            params.append(status_filter)

    if search_query:
        where_clauses.append("(e.company_name LIKE %s OR e.email LIKE %s OR e.website LIKE %s OR e.location LIKE %s)")
        q_wild = f"%{search_query}%"
        params.extend([q_wild, q_wild, q_wild, q_wild])

    where_sql = " AND ".join(where_clauses)

    order_sql = "e.id DESC"
    if sort_by == 'oldest':
        order_sql = "e.id ASC"
    elif sort_by == 'name':
        order_sql = "e.company_name ASC"

    with db_cursor() as cur:
        count_query = f"SELECT COUNT(*) AS total FROM employee e WHERE {where_sql}"
        cur.execute(count_query, tuple(params))
        total_count = cur.fetchone()['total']

        fetch_query = f"""
            SELECT e.id, e.company_name, e.email, e.mobile, e.industry, e.location,
                   e.company_size, e.website, e.company_website, e.description,
                   e.founded_year, e.linkedin_url, e.twitter_url, e.logo_path,
                   e.is_verified, e.verification_status, e.verified_at,
                   e.verification_notes, e.verification_doc_path, e.verification_submitted_at,
                   e.created_at,
                   (SELECT COUNT(*) FROM jobs j WHERE j.employer_id = e.id AND j.is_deleted = 0) AS jobs_count,
                   (SELECT COUNT(*) FROM reports r WHERE r.report_type = 'company' AND r.target_id = e.id) AS reports_count
            FROM employee e
            WHERE {where_sql}
            ORDER BY {order_sql}
            LIMIT %s OFFSET %s
        """
        cur.execute(fetch_query, tuple(params + [per_page, offset]))
        companies = cur.fetchall()

    enriched_companies = []
    for c in companies:
        jobs_count = c.get('jobs_count') or 0
        reports_count = c.get('reports_count') or 0
        
        # Calculate trust signals and screening risk score
        trust_analysis = compute_company_trust_and_risk(c, jobs_count=jobs_count, reports_count=reports_count, website_audit=None)

        if c.get('verified_at') and hasattr(c['verified_at'], 'strftime'):
            c['verified_at_fmt'] = c['verified_at'].strftime('%Y-%m-%d %H:%M')
        if c.get('verification_submitted_at') and hasattr(c['verification_submitted_at'], 'strftime'):
            c['verification_submitted_at_fmt'] = c['verification_submitted_at'].strftime('%Y-%m-%d %H:%M')
        if c.get('created_at') and hasattr(c['created_at'], 'strftime'):
            c['created_at_fmt'] = c['created_at'].strftime('%Y-%m-%d')

        c['risk_level'] = trust_analysis['risk_level']
        c['risk_class'] = trust_analysis['risk_class']
        c['risk_points'] = trust_analysis['risk_points']
        c['completeness'] = trust_analysis['completeness']
        c['trust_indicators'] = trust_analysis['trust_indicators']
        c['warnings'] = trust_analysis['warnings']
        c['has_document'] = bool(c.get('verification_doc_path'))
        enriched_companies.append(c)

    pages = max(1, (total_count + per_page - 1) // per_page)
    return jsonify({
        'success': True,
        'companies': enriched_companies,
        'total': total_count,
        'page': page,
        'per_page': per_page,
        'pages': pages
    })


@app.route('/api/admin/companies/<int:company_id>')
@admin_required
def api_admin_company_detail(company_id):
    """
    Fetches full company review data including safe SSRF website audit,
    active job listings, candidate reports, and complete verification history.
    """
    with db_cursor() as cur:
        cur.execute("""
            SELECT e.*,
                   (SELECT COUNT(*) FROM jobs j WHERE j.employer_id = e.id AND j.is_deleted = 0) AS jobs_count,
                   (SELECT COUNT(*) FROM reports r WHERE r.report_type = 'company' AND r.target_id = e.id) AS reports_count
            FROM employee e
            WHERE e.id = %s
        """, (company_id,))
        company = cur.fetchone()

        if not company:
            return jsonify({'success': False, 'message': f'Company #{company_id} not found.'}), 404

        # Fetch posted jobs
        cur.execute("""
            SELECT id, title, location, job_type, salary, status, is_active, is_featured, created_at
            FROM jobs
            WHERE employer_id = %s AND is_deleted = 0
            ORDER BY id DESC
        """, (company_id,))
        jobs = cur.fetchall()
        for j in jobs:
            if j.get('created_at') and hasattr(j['created_at'], 'strftime'):
                j['created_at_fmt'] = j['created_at'].strftime('%Y-%m-%d')

        # Fetch reports against company
        cur.execute("""
            SELECT id, reporter_email, category, description, status, created_at
            FROM reports
            WHERE report_type = 'company' AND target_id = %s
            ORDER BY id DESC
        """, (company_id,))
        reports = cur.fetchall()
        for r in reports:
            if r.get('created_at') and hasattr(r['created_at'], 'strftime'):
                r['created_at_fmt'] = r['created_at'].strftime('%Y-%m-%d %H:%M')

        # Fetch verification history
        cur.execute("""
            SELECT cvh.id, cvh.previous_status, cvh.new_status, cvh.admin_note, cvh.created_at,
                   u.name AS admin_name, u.email AS admin_email
            FROM company_verification_history cvh
            LEFT JOIN user u ON cvh.admin_id = u.id
            WHERE cvh.company_id = %s
            ORDER BY cvh.id DESC
        """, (company_id,))
        history = cur.fetchall()
        for h in history:
            if h.get('created_at') and hasattr(h['created_at'], 'strftime'):
                h['created_at_fmt'] = h['created_at'].strftime('%Y-%m-%d %H:%M:%S')

    # SSRF-Safe Website Check
    website_url = company.get('website') or company.get('company_website') or ''
    website_audit = safe_check_company_website(website_url)

    # Trust and Risk Analysis
    trust_analysis = compute_company_trust_and_risk(
        company,
        jobs_count=len(jobs),
        reports_count=len(reports),
        website_audit=website_audit
    )

    if company.get('verified_at') and hasattr(company['verified_at'], 'strftime'):
        company['verified_at_fmt'] = company['verified_at'].strftime('%Y-%m-%d %H:%M')
    if company.get('verification_submitted_at') and hasattr(company['verification_submitted_at'], 'strftime'):
        company['verification_submitted_at_fmt'] = company['verification_submitted_at'].strftime('%Y-%m-%d %H:%M')
    if company.get('created_at') and hasattr(company['created_at'], 'strftime'):
        company['created_at_fmt'] = company['created_at'].strftime('%Y-%m-%d')

    return jsonify({
        'success': True,
        'company': company,
        'jobs': jobs,
        'reports': reports,
        'history': history,
        'website_audit': website_audit,
        'trust_analysis': trust_analysis
    })


@app.route('/api/admin/companies/<int:company_id>/status', methods=['POST'])
@admin_required
def api_admin_update_company_status(company_id):
    """
    Transitions a company's verification status with mandatory admin notes,
    audit trail generation, and immutable history recording.
    """
    data = request.get_json(silent=True) or request.form.to_dict()
    new_status = (data.get('status') or '').strip().lower()
    admin_note = sanitize_text(data.get('admin_note') or data.get('notes') or '').strip()

    allowed_statuses = {'verified', 'suspicious', 'rejected', 'pending', 'unverified'}
    if new_status not in allowed_statuses:
        return jsonify({'success': False, 'message': f'Invalid status. Allowed: {", ".join(allowed_statuses)}'}), 400

    if not admin_note:
        admin_note = f"Status updated to {new_status} by administrator."

    with db_cursor() as cur:
        cur.execute("SELECT id, company_name, verification_status, is_verified FROM employee WHERE id = %s", (company_id,))
        emp = cur.fetchone()

    if not emp:
        return jsonify({'success': False, 'message': f'Company #{company_id} not found.'}), 404

    prev_status = emp.get('verification_status') or ('verified' if emp.get('is_verified') else 'unverified')
    is_verified_val = 1 if new_status == 'verified' else 0
    admin_id = session.get('user_id')

    try:
        with db_cursor(dictionary=False) as cur:
            if new_status == 'verified':
                cur.execute("""
                    UPDATE employee
                    SET verification_status = 'verified',
                        is_verified = 1,
                        verified_at = NOW(),
                        verification_notes = %s
                    WHERE id = %s
                """, (admin_note, company_id))
            else:
                cur.execute("""
                    UPDATE employee
                    SET verification_status = %s,
                        is_verified = %s,
                        verification_notes = %s
                    WHERE id = %s
                """, (new_status, is_verified_val, admin_note, company_id))

            # Record in company verification history
            cur.execute("""
                INSERT INTO company_verification_history
                (company_id, admin_id, previous_status, new_status, admin_note)
                VALUES (%s, %s, %s, %s, %s)
            """, (company_id, admin_id, prev_status, new_status, admin_note))

        log_admin_audit('update_company_status', 'company', company_id, prev_status, new_status, admin_note, admin_id)
        logger.info(f"Admin #{admin_id} updated company #{company_id} ({emp['company_name']}) status from '{prev_status}' to '{new_status}'")

        return jsonify({
            'success': True,
            'message': f"Company '{emp['company_name']}' verification status updated to '{new_status}'.",
            'status': new_status
        })
    except Exception as e:
        logger.error(f"Error updating company status: {e}")
        return jsonify({'success': False, 'message': f'Failed to update status: {str(e)}'}), 500


@app.route('/api/admin/check_website_safe')
@admin_required
def api_admin_check_website_safe():
    """Live SSRF-protected company website test endpoint."""
    url = request.args.get('url', '').strip()
    if not url:
        return jsonify({'success': False, 'message': 'URL parameter is required.'}), 400
    audit = safe_check_company_website(url)
    return jsonify({'success': True, 'audit': audit})


@app.route('/admin/company_doc/<int:company_id>')
def admin_view_company_doc(company_id):
    """Admin-only secure endpoint to inspect uploaded registration documents."""
    if not require_admin():
        return "Forbidden: Admin access required.", 403
    with db_cursor() as cursor:
        cursor.execute("SELECT verification_doc_path FROM employee WHERE id = %s", (company_id,))
        row = cursor.fetchone()

    if not row or not row.get('verification_doc_path'):
        flash("Document not found for this company.", "error")
        return redirect(url_for('admin_dashboard_page'))

    filename = secure_filename(row['verification_doc_path'])
    return send_from_directory(VERIFICATION_DOCS_FOLDER, filename, as_attachment=False)


# Legacy backward-compatible company status routes
@app.route('/admin/companies/<int:company_id>/verify', methods=['POST'])
@app.route('/api/admin/company/<int:company_id>/verify', methods=['POST'])
@admin_required
def admin_company_verify_legacy(company_id):
    data = request.get_json(silent=True) or request.form.to_dict()
    data['status'] = 'verified'
    if not data.get('admin_note'):
        data['admin_note'] = 'Approved by HireVoltz trust team.'
    # Reuse updated status handler
    with db_cursor(dictionary=False) as cur:
        cur.execute("UPDATE employee SET verification_status = 'verified', is_verified = 1, verified_at = NOW(), verification_notes = %s WHERE id = %s", (data['admin_note'], company_id))
        cur.execute("INSERT INTO company_verification_history (company_id, admin_id, previous_status, new_status, admin_note) VALUES (%s, %s, 'pending', 'verified', %s)", (company_id, session.get('user_id'), data['admin_note']))
    log_admin_audit('verify_company', 'company', company_id, 'pending', 'verified', data['admin_note'])
    if request.is_json or request.headers.get('Accept') == 'application/json':
        return jsonify({'success': True, 'message': f'Company #{company_id} verified successfully.'})
    flash(f"Company #{company_id} verified successfully.", "success")
    return redirect(url_for('admin_dashboard_page'))


@app.route('/admin/companies/<int:company_id>/reject', methods=['POST'])
@app.route('/api/admin/company/<int:company_id>/reject', methods=['POST'])
@admin_required
def admin_company_reject_legacy(company_id):
    data = request.get_json(silent=True) or request.form.to_dict()
    note = data.get('admin_note') or data.get('notes') or 'Rejected by HireVoltz trust team.'
    with db_cursor(dictionary=False) as cur:
        cur.execute("UPDATE employee SET verification_status = 'rejected', is_verified = 0, verification_notes = %s WHERE id = %s", (note, company_id))
        cur.execute("INSERT INTO company_verification_history (company_id, admin_id, previous_status, new_status, admin_note) VALUES (%s, %s, 'pending', 'rejected', %s)", (company_id, session.get('user_id'), note))
    log_admin_audit('reject_company', 'company', company_id, 'pending', 'rejected', note)
    if request.is_json or request.headers.get('Accept') == 'application/json':
        return jsonify({'success': True, 'message': f'Company #{company_id} rejected.'})
    flash(f"Company #{company_id} rejected.", "info")
    return redirect(url_for('admin_dashboard_page'))


@app.route('/api/admin/company_verifications')
@admin_required
def api_admin_company_verifications_legacy():
    return api_admin_companies()


@app.route('/api/admin/verify_company', methods=['POST'])
@admin_required
def api_admin_verify_company_legacy():
    data = request.get_json(silent=True) or request.form.to_dict()
    cid = data.get('company_id')
    act = (data.get('action') or 'approve').lower()
    status_map = {'approve': 'verified', 'reject': 'rejected', 'request_changes': 'unverified'}
    data['status'] = status_map.get(act, 'verified')
    if not data.get('admin_note') and not data.get('notes'):
        data['admin_note'] = "Approved by HireVoltz trust team." if act == 'approve' else "Rejected by HireVoltz trust team."
    return api_admin_update_company_status(cid)


# --- JOB MODERATION ENDPOINTS ---

@app.route('/api/admin/jobs')
@admin_required
def api_admin_jobs():
    """Paginated, searchable, filterable job listings moderation endpoint."""
    status_filter = (request.args.get('status') or 'all').strip()
    search_query = sanitize_text(request.args.get('search', '')).strip()
    employer_id = request.args.get('employer_id', type=int)
    page = max(1, request.args.get('page', 1, type=int) or 1)
    per_page = min(100, max(1, request.args.get('per_page', 15, type=int) or 15))
    offset = (page - 1) * per_page

    where_clauses = ["1=1"]
    params = []

    if status_filter and status_filter != 'all':
        if status_filter.lower() == 'active':
            where_clauses.append("j.is_active = 1 AND j.is_deleted = 0 AND (j.status = 'Published' OR j.status IS NULL)")
        elif status_filter.lower() == 'deleted':
            where_clauses.append("j.is_deleted = 1")
        elif status_filter.lower() == 'suspicious':
            where_clauses.append("j.status = 'Suspicious'")
        elif status_filter.lower() == 'rejected':
            where_clauses.append("j.status = 'Rejected'")
        else:
            where_clauses.append("j.status = %s")
            params.append(status_filter)

    if employer_id:
        where_clauses.append("j.employer_id = %s")
        params.append(employer_id)

    if search_query:
        where_clauses.append("(j.title LIKE %s OR j.location LIKE %s OR j.company_name LIKE %s OR e.company_name LIKE %s)")
        q_wild = f"%{search_query}%"
        params.extend([q_wild, q_wild, q_wild, q_wild])

    where_sql = " AND ".join(where_clauses)

    with db_cursor() as cur:
        cur.execute(f"SELECT COUNT(*) AS total FROM jobs j LEFT JOIN employee e ON j.employer_id = e.id WHERE {where_sql}", tuple(params))
        total_count = cur.fetchone()['total']

        cur.execute(f"""
            SELECT j.id, j.title, j.location, j.job_type, j.work_mode, j.salary,
                   j.salary_min, j.salary_max, j.status, j.is_active, j.is_featured,
                   j.is_deleted, j.created_at, j.application_deadline,
                   COALESCE(e.company_name, j.company_name) AS company_name,
                   e.id AS employer_id, e.email AS employer_email,
                   e.is_verified AS employer_is_verified, e.verification_status AS employer_verification_status,
                   (SELECT COUNT(*) FROM applications a WHERE a.job_id = j.id) AS applications_count,
                   (SELECT COUNT(*) FROM reports r WHERE r.report_type = 'job' AND r.target_id = j.id) AS reports_count
            FROM jobs j
            LEFT JOIN employee e ON j.employer_id = e.id
            WHERE {where_sql}
            ORDER BY j.id DESC
            LIMIT %s OFFSET %s
        """, tuple(params + [per_page, offset]))
        jobs = cur.fetchall()

    for j in jobs:
        if j.get('created_at') and hasattr(j['created_at'], 'strftime'):
            j['created_at_fmt'] = j['created_at'].strftime('%Y-%m-%d')
        if j.get('application_deadline') and hasattr(j['application_deadline'], 'strftime'):
            j['application_deadline_fmt'] = j['application_deadline'].strftime('%Y-%m-%d')

    pages = max(1, (total_count + per_page - 1) // per_page)
    return jsonify({
        'success': True,
        'jobs': jobs,
        'total': total_count,
        'page': page,
        'per_page': per_page,
        'pages': pages
    })


@app.route('/api/admin/jobs/<int:job_id>')
@admin_required
def api_admin_job_detail(job_id):
    """Fetches job details, employer credentials, and candidate reports filed against this listing."""
    with db_cursor() as cur:
        cur.execute("""
            SELECT j.*,
                   COALESCE(e.company_name, j.company_name) AS company_name,
                   e.email AS employer_email, e.mobile AS employer_mobile,
                   e.website AS employer_website, e.is_verified AS employer_is_verified,
                   e.verification_status AS employer_verification_status
            FROM jobs j
            LEFT JOIN employee e ON j.employer_id = e.id
            WHERE j.id = %s
        """, (job_id,))
        job = cur.fetchone()

        if not job:
            return jsonify({'success': False, 'message': f'Job #{job_id} not found.'}), 404

        cur.execute("SELECT id, reporter_email, category, description, status, created_at FROM reports WHERE report_type = 'job' AND target_id = %s ORDER BY id DESC", (job_id,))
        reports = cur.fetchall()
        for r in reports:
            if r.get('created_at') and hasattr(r['created_at'], 'strftime'):
                r['created_at_fmt'] = r['created_at'].strftime('%Y-%m-%d %H:%M')

    if job.get('created_at') and hasattr(job['created_at'], 'strftime'):
        job['created_at_fmt'] = job['created_at'].strftime('%Y-%m-%d %H:%M')

    return jsonify({'success': True, 'job': job, 'reports': reports})


@app.route('/api/admin/jobs/<int:job_id>/status', methods=['POST'])
@admin_required
def api_admin_update_job_status(job_id):
    """Updates job listing status with admin audit logging."""
    data = request.get_json(silent=True) or request.form.to_dict()
    new_status = (data.get('status') or 'Published').strip()
    admin_note = sanitize_text(data.get('admin_note') or '').strip()
    is_featured = data.get('is_featured')

    with db_cursor() as cur:
        cur.execute("SELECT id, title, status, is_active, is_featured, is_deleted FROM jobs WHERE id = %s", (job_id,))
        job = cur.fetchone()

    if not job:
        return jsonify({'success': False, 'message': f'Job #{job_id} not found.'}), 404

    prev_status = job.get('status') or ('Published' if job.get('is_active') else 'Closed')
    is_active_val = 1 if new_status == 'Published' else 0
    is_deleted_val = 1 if new_status == 'Deleted' else job.get('is_deleted', 0)
    featured_val = job.get('is_featured', 0) if is_featured is None else (1 if is_featured else 0)

    with db_cursor(dictionary=False) as cur:
        cur.execute("""
            UPDATE jobs
            SET status = %s, is_active = %s, is_deleted = %s, is_featured = %s
            WHERE id = %s
        """, (new_status, is_active_val, is_deleted_val, featured_val, job_id))

    log_admin_audit('update_job_status', 'job', job_id, prev_status, new_status, admin_note or f"Job status updated to {new_status}")
    logger.info(f"Admin updated job #{job_id} status from '{prev_status}' to '{new_status}'")

    return jsonify({'success': True, 'message': f"Job #{job_id} status updated to '{new_status}'."})


@app.route('/admin/jobs/<int:job_id>/approve', methods=['POST'])
@admin_required
def admin_job_approve_endpoint(job_id):
    with db_cursor(dictionary=False) as cur:
        cur.execute("UPDATE jobs SET status = 'Published', is_active = 1, is_deleted = 0 WHERE id = %s", (job_id,))
    log_admin_audit('approve_job', 'job', job_id, 'Pending', 'Published', 'Approved by administrator')
    if request.is_json or request.headers.get('Accept') == 'application/json':
        return jsonify({'success': True, 'message': f'Job #{job_id} approved and published.'})
    flash(f"Job #{job_id} approved and published.", "success")
    return redirect(url_for('admin_dashboard_page'))


@app.route('/admin/jobs/<int:job_id>/reject', methods=['POST'])
@admin_required
def admin_job_reject_endpoint(job_id):
    with db_cursor(dictionary=False) as cur:
        cur.execute("UPDATE jobs SET status = 'Rejected', is_active = 0 WHERE id = %s", (job_id,))
    log_admin_audit('reject_job', 'job', job_id, 'Published', 'Rejected', 'Rejected by administrator')
    if request.is_json or request.headers.get('Accept') == 'application/json':
        return jsonify({'success': True, 'message': f'Job #{job_id} rejected.'})
    flash(f"Job #{job_id} rejected.", "info")
    return redirect(url_for('admin_dashboard_page'))


@app.route('/admin/jobs/<int:job_id>/feature', methods=['POST'])
@app.route('/api/admin/jobs/<int:job_id>/feature', methods=['POST'])
@admin_required
def admin_job_feature_endpoint(job_id):
    with db_cursor() as cur:
        cur.execute("SELECT is_featured FROM jobs WHERE id = %s", (job_id,))
        row = cur.fetchone()
        new_val = not bool(row.get('is_featured', 0)) if row else True
    with db_cursor(dictionary=False) as cur:
        cur.execute("UPDATE jobs SET is_featured = %s WHERE id = %s", (new_val, job_id))
    log_admin_audit('toggle_feature_job', 'job', job_id, reason=f'Featured status set to {new_val}')
    return jsonify({'success': True, 'message': f'Job #{job_id} featured status toggled.', 'is_featured': new_val})


@app.route('/admin/jobs/<int:job_id>/delete', methods=['POST'])
@app.route('/api/admin/jobs/<int:job_id>/delete', methods=['POST'])
@admin_required
def admin_job_delete_endpoint(job_id):
    with db_cursor(dictionary=False) as cur:
        cur.execute("UPDATE jobs SET is_active = 0, status = 'Deleted', is_deleted = 1 WHERE id = %s", (job_id,))
    log_admin_audit('soft_delete_job', 'job', job_id, reason='Job deleted by administrator')
    return jsonify({'success': True, 'message': f'Job #{job_id} has been deleted.'})


@app.route('/api/admin/job/<int:job_id>/deactivate', methods=['POST'])
@admin_required
def api_admin_deactivate_job_endpoint(job_id):
    with db_cursor(dictionary=False) as cur:
        cur.execute("UPDATE jobs SET is_active = NOT is_active WHERE id = %s", (job_id,))
    log_admin_audit('toggle_active_job', 'job', job_id, reason='Job active status toggled')
    return jsonify({'success': True, 'message': 'Job status toggled'})


# --- CANDIDATE REPORTING & REPORT MANAGEMENT ENDPOINTS ---

@app.route('/api/reports/submit', methods=['POST'])
@limiter.limit("10 per hour")
def api_submit_report():
    """
    Public and candidate authenticated reporting endpoint.
    Allows reporting of scam companies, fake jobs, or suspicious behavior.
    """
    data = request.get_json(silent=True) or request.form.to_dict()
    report_type = (data.get('report_type') or '').strip().lower()
    try:
        target_id = int(data.get('target_id') or 0)
    except (ValueError, TypeError):
        target_id = 0
    target_name = sanitize_text(data.get('target_name', '')).strip()
    category = sanitize_text(data.get('category', 'Other')).strip()
    description = sanitize_text(data.get('description', '')).strip()
    reporter_email = normalize_email(data.get('reporter_email') or session.get('user_email') or '')

    allowed_categories = {
        'Scam', 'Fake Company', 'Fake Job', 'Suspicious Recruitment',
        'Wrong Information', 'External Payment Request', 'Spam', 'Other'
    }
    if category not in allowed_categories:
        category = 'Other'

    if report_type not in ('company', 'job') or not target_id:
        return jsonify({'success': False, 'message': 'Report type (company or job) and target ID are required.'}), 400

    if not description or len(description) < 10:
        return jsonify({'success': False, 'message': 'Please provide a descriptive explanation (minimum 10 characters).'}), 400

    reporter_user_id = session.get('user_id') if 'user_id' in session else None

    # Fetch target name if not supplied
    if not target_name:
        with db_cursor() as cur:
            if report_type == 'company':
                cur.execute("SELECT company_name FROM employee WHERE id = %s", (target_id,))
                row = cur.fetchone()
                if row: target_name = row['company_name']
            else:
                cur.execute("SELECT title FROM jobs WHERE id = %s", (target_id,))
                row = cur.fetchone()
                if row: target_name = row['title']

    try:
        with db_cursor(dictionary=False) as cur:
            cur.execute("""
                INSERT INTO reports
                (reporter_user_id, reporter_email, report_type, target_id, target_name, category, description, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, 'OPEN')
            """, (reporter_user_id, reporter_email, report_type, target_id, target_name or 'Unspecified', category, description))
            report_id = cur.lastrowid

        logger.info(f"New report filed: ID={report_id} against {report_type} #{target_id} ({category})")
        return jsonify({
            'success': True,
            'message': 'Thank you for reporting. Our trust and safety team will investigate this issue immediately.',
            'report_id': report_id
        })
    except Exception as e:
        logger.error(f"Error submitting report: {e}")
        return jsonify({'success': False, 'message': 'Failed to submit report. Please try again later.'}), 500


@app.route('/api/admin/reports')
@admin_required
def api_admin_reports():
    """Paginated list of all candidate/user reports with filtering by status and type."""
    status_filter = (request.args.get('status') or 'all').strip().upper()
    type_filter = (request.args.get('type') or 'all').strip().lower()
    category_filter = request.args.get('category', '').strip()
    search_query = sanitize_text(request.args.get('search', '')).strip()
    page = max(1, request.args.get('page', 1, type=int) or 1)
    per_page = min(100, max(1, request.args.get('per_page', 15, type=int) or 15))
    offset = (page - 1) * per_page

    where_clauses = ["1=1"]
    params = []

    if status_filter and status_filter != 'ALL':
        where_clauses.append("r.status = %s")
        params.append(status_filter)

    if type_filter and type_filter != 'all':
        where_clauses.append("r.report_type = %s")
        params.append(type_filter)

    if category_filter:
        where_clauses.append("r.category = %s")
        params.append(category_filter)

    if search_query:
        where_clauses.append("(r.target_name LIKE %s OR r.description LIKE %s OR r.reporter_email LIKE %s)")
        q_wild = f"%{search_query}%"
        params.extend([q_wild, q_wild, q_wild])

    where_sql = " AND ".join(where_clauses)

    with db_cursor() as cur:
        cur.execute(f"SELECT COUNT(*) AS total FROM reports r WHERE {where_sql}", tuple(params))
        total_count = cur.fetchone()['total']

        cur.execute(f"""
            SELECT r.*,
                   u.name AS resolver_name
            FROM reports r
            LEFT JOIN user u ON r.resolved_by_admin_id = u.id
            WHERE {where_sql}
            ORDER BY
                CASE WHEN r.status = 'OPEN' THEN 0
                     WHEN r.status = 'UNDER_REVIEW' THEN 1
                     ELSE 2 END,
                r.created_at DESC
            LIMIT %s OFFSET %s
        """, tuple(params + [per_page, offset]))
        reports = cur.fetchall()

    for r in reports:
        if r.get('created_at') and hasattr(r['created_at'], 'strftime'):
            r['created_at_fmt'] = r['created_at'].strftime('%Y-%m-%d %H:%M')
        if r.get('resolved_at') and hasattr(r['resolved_at'], 'strftime'):
            r['resolved_at_fmt'] = r['resolved_at'].strftime('%Y-%m-%d %H:%M')

    pages = max(1, (total_count + per_page - 1) // per_page)
    return jsonify({
        'success': True,
        'reports': reports,
        'total': total_count,
        'page': page,
        'per_page': per_page,
        'pages': pages
    })


@app.route('/api/admin/reports/<int:report_id>/status', methods=['POST'])
@admin_required
def api_admin_update_report_status(report_id):
    """Updates a candidate report status (OPEN -> UNDER_REVIEW -> RESOLVED -> DISMISSED)."""
    data = request.get_json(silent=True) or request.form.to_dict()
    new_status = (data.get('status') or '').strip().upper()
    admin_notes = sanitize_text(data.get('admin_notes') or '').strip()

    allowed_statuses = {'OPEN', 'UNDER_REVIEW', 'RESOLVED', 'DISMISSED'}
    if new_status not in allowed_statuses:
        return jsonify({'success': False, 'message': f'Invalid status. Allowed: {", ".join(allowed_statuses)}'}), 400

    admin_id = session.get('user_id')

    with db_cursor() as cur:
        cur.execute("SELECT id, status, report_type, target_id, target_name FROM reports WHERE id = %s", (report_id,))
        rep = cur.fetchone()

    if not rep:
        return jsonify({'success': False, 'message': f'Report #{report_id} not found.'}), 404

    prev_status = rep['status']
    is_resolved = new_status in ('RESOLVED', 'DISMISSED')

    with db_cursor(dictionary=False) as cur:
        if is_resolved:
            cur.execute("""
                UPDATE reports
                SET status = %s, admin_notes = %s, resolved_by_admin_id = %s, resolved_at = NOW()
                WHERE id = %s
            """, (new_status, admin_notes or 'Resolved by admin.', admin_id, report_id))
        else:
            cur.execute("""
                UPDATE reports
                SET status = %s, admin_notes = %s, resolved_by_admin_id = %s
                WHERE id = %s
            """, (new_status, admin_notes or 'Updated by admin.', admin_id, report_id))

    log_admin_audit('update_report_status', 'report', report_id, prev_status, new_status, admin_notes or f"Report status updated to {new_status}")
    logger.info(f"Admin #{admin_id} updated report #{report_id} status from '{prev_status}' to '{new_status}'")

    return jsonify({
        'success': True,
        'message': f'Report #{report_id} marked as {new_status}.'
    })


# --- ADMIN AUDIT LOGS ENDPOINTS ---

@app.route('/api/admin/audit_logs')
@admin_required
def api_admin_audit_logs():
    """Paginated immutable audit trail tracking all administrative actions."""
    action_filter = request.args.get('action', '').strip()
    entity_filter = request.args.get('entity_type', '').strip()
    search_query = sanitize_text(request.args.get('search', '')).strip()
    page = max(1, request.args.get('page', 1, type=int) or 1)
    per_page = min(100, max(1, request.args.get('per_page', 20, type=int) or 20))
    offset = (page - 1) * per_page

    where_clauses = ["1=1"]
    params = []

    if action_filter:
        where_clauses.append("action = %s")
        params.append(action_filter)

    if entity_filter:
        where_clauses.append("entity_type = %s")
        params.append(entity_filter)

    if search_query:
        where_clauses.append("(admin_email LIKE %s OR reason LIKE %s OR ip_address LIKE %s)")
        q_wild = f"%{search_query}%"
        params.extend([q_wild, q_wild, q_wild])

    where_sql = " AND ".join(where_clauses)

    with db_cursor() as cur:
        cur.execute(f"SELECT COUNT(*) AS total FROM admin_audit_logs WHERE {where_sql}", tuple(params))
        total_count = cur.fetchone()['total']

        cur.execute(f"""
            SELECT id, admin_id, admin_email, action, entity_type, entity_id,
                   previous_status, new_status, reason, ip_address, user_agent, created_at
            FROM admin_audit_logs
            WHERE {where_sql}
            ORDER BY id DESC
            LIMIT %s OFFSET %s
        """, tuple(params + [per_page, offset]))
        logs = cur.fetchall()

    for l in logs:
        if l.get('created_at') and hasattr(l['created_at'], 'strftime'):
            l['created_at_fmt'] = l['created_at'].strftime('%Y-%m-%d %H:%M:%S')

    pages = max(1, (total_count + per_page - 1) // per_page)
    return jsonify({
        'success': True,
        'audit_logs': logs,
        'total': total_count,
        'page': page,
        'per_page': per_page,
        'pages': pages
    })


# --- USER MODERATION ENDPOINTS ---

@app.route('/api/admin/users')
@admin_required
def api_admin_users():
    """Paginated user accounts list with search and ban status."""
    search_query = sanitize_text(request.args.get('search', '')).strip()
    page = max(1, request.args.get('page', 1, type=int) or 1)
    per_page = min(100, max(1, request.args.get('per_page', 20, type=int) or 20))
    offset = (page - 1) * per_page

    where_clauses = ["is_deleted = 0"]
    params = []

    if search_query:
        where_clauses.append("(name LIKE %s OR email LIKE %s OR mobile LIKE %s)")
        q_wild = f"%{search_query}%"
        params.extend([q_wild, q_wild, q_wild])

    where_sql = " AND ".join(where_clauses)

    with db_cursor() as cur:
        cur.execute(f"SELECT COUNT(*) AS total FROM user WHERE {where_sql}", tuple(params))
        total = cur.fetchone()['total']

        cur.execute(f"""
            SELECT id, name, email, mobile, is_verified, is_admin, is_banned, is_deleted, created_at
            FROM user
            WHERE {where_sql}
            ORDER BY id DESC
            LIMIT %s OFFSET %s
        """, tuple(params + [per_page, offset]))
        users = cur.fetchall()

    for u in users:
        if u.get('created_at') and hasattr(u['created_at'], 'strftime'):
            u['created_at_fmt'] = u['created_at'].strftime('%Y-%m-%d')

    pages = max(1, (total + per_page - 1) // per_page)
    return jsonify({'success': True, 'users': users, 'total': total, 'page': page, 'pages': pages})


@app.route('/admin/users/<int:user_id>/ban', methods=['POST'])
@app.route('/api/admin/users/<int:user_id>/ban', methods=['POST'])
@admin_required
def admin_user_ban_endpoint(user_id):
    with db_cursor(dictionary=False) as cur:
        cur.execute("UPDATE user SET is_banned = 1, session_version = session_version + 1 WHERE id = %s", (user_id,))
    log_admin_audit('ban_user', 'user', user_id, reason='User banned by administrator')
    if request.is_json or request.headers.get('Accept') == 'application/json':
        return jsonify({'success': True, 'message': f'User #{user_id} has been banned.'})
    flash(f"User #{user_id} banned successfully.", "success")
    return redirect(url_for('admin_dashboard_page'))


@app.route('/admin/users/<int:user_id>/unban', methods=['POST'])
@app.route('/api/admin/users/<int:user_id>/unban', methods=['POST'])
@admin_required
def admin_user_unban_endpoint(user_id):
    with db_cursor(dictionary=False) as cur:
        cur.execute("UPDATE user SET is_banned = 0 WHERE id = %s", (user_id,))
    log_admin_audit('unban_user', 'user', user_id, reason='User unbanned by administrator')
    return jsonify({'success': True, 'message': f'User #{user_id} unbanned.'})


@app.route('/admin/users/<int:user_id>/delete', methods=['POST'])
@app.route('/api/admin/user/<int:user_id>/delete', methods=['POST'])
@app.route('/api/admin/users/<int:user_id>/delete', methods=['POST'])
@admin_required
def admin_user_delete_endpoint(user_id):
    with db_cursor(dictionary=False) as cur:
        cur.execute("UPDATE user SET is_deleted = 1, session_version = session_version + 1 WHERE id = %s", (user_id,))
    log_admin_audit('delete_user', 'user', user_id, reason='User soft-deleted by administrator')
    if request.is_json or request.headers.get('Accept') == 'application/json':
        return jsonify({'success': True, 'message': f'User #{user_id} has been deleted.'})
    flash(f"User #{user_id} deleted successfully.", "success")
    return redirect(url_for('admin_dashboard_page'))


# --- GLOBAL ADMIN SEARCH ENDPOINT ---

@app.route('/api/admin/global_search')
@admin_required
def api_admin_global_search():
    """Performs unified search across companies, jobs, reports, and users."""
    q = sanitize_text(request.args.get('q', '')).strip()
    if not q or len(q) < 2:
        return jsonify({'success': True, 'results': {'companies': [], 'jobs': [], 'reports': [], 'users': []}})

    q_wild = f"%{q}%"
    with db_cursor() as cur:
        cur.execute("SELECT id, company_name, email, verification_status, is_verified FROM employee WHERE company_name LIKE %s OR email LIKE %s OR website LIKE %s LIMIT 5", (q_wild, q_wild, q_wild))
        companies = cur.fetchall()

        cur.execute("SELECT id, title, company_name, location, status, is_active FROM jobs WHERE (title LIKE %s OR company_name LIKE %s) AND is_deleted = 0 LIMIT 5", (q_wild, q_wild))
        jobs = cur.fetchall()

        cur.execute("SELECT id, report_type, target_name, category, status FROM reports WHERE target_name LIKE %s OR description LIKE %s LIMIT 5", (q_wild, q_wild))
        reports = cur.fetchall()

        cur.execute("SELECT id, name, email FROM user WHERE (name LIKE %s OR email LIKE %s) AND is_deleted = 0 LIMIT 5", (q_wild, q_wild))
        users = cur.fetchall()

    return jsonify({
        'success': True,
        'results': {
            'companies': companies,
            'jobs': jobs,
            'reports': reports,
            'users': users
        }
    })


# --- EXPORT REPORT DATA ENDPOINT ---

@app.route('/api/admin/reports/<type>/export')
@admin_required
def api_admin_export_report(type):
    """Exports structured audit data for companies, jobs, users, or applications."""
    with db_cursor() as cursor:
        if type == 'companies':
            cursor.execute("""
                SELECT id, company_name, email, mobile, industry, location,
                       verification_status, is_verified, verified_at,
                       (SELECT COUNT(*) FROM jobs j WHERE j.employer_id = employee.id AND j.is_deleted = 0) AS total_jobs
                FROM employee ORDER BY id DESC
            """)
        elif type == 'jobs':
            cursor.execute("""
                SELECT j.id, j.title, COALESCE(e.company_name, j.company_name) AS company_name,
                       j.location, j.job_type, j.status, j.is_active, j.is_featured, j.created_at
                FROM jobs j
                LEFT JOIN employee e ON j.employer_id = e.id
                WHERE j.is_deleted = 0
                ORDER BY j.id DESC
            """)
        elif type == 'users':
            cursor.execute("SELECT id, name, email, mobile, is_verified, is_banned, created_at FROM user WHERE is_deleted = 0 ORDER BY id DESC")
        elif type == 'applications':
            cursor.execute("""
                SELECT a.id, a.job_id, j.title AS job_title, a.user_id, u.name AS candidate_name,
                       a.status, a.created_at
                FROM applications a
                JOIN jobs j ON a.job_id = j.id
                JOIN user u ON a.user_id = u.id
                ORDER BY a.id DESC
            """)
        elif type == 'audit_logs':
            cursor.execute("SELECT * FROM admin_audit_logs ORDER BY id DESC LIMIT 1000")
        else:
            return jsonify({'success': False, 'message': 'Invalid report type.'}), 400

        rows = cursor.fetchall()

    for r in rows:
        for k, v in list(r.items()):
            if isinstance(v, (datetime, dt_date)):
                r[k] = v.strftime('%Y-%m-%d %H:%M:%S')

    return jsonify({'success': True, 'count': len(rows), 'data': rows})



# --- EMPLOYER PROFILE & VERIFICATION ENDPOINTS ---
@app.route('/api/employer/profile', methods=['GET', 'POST'])
def api_employer_profile():
    if 'employer_id' not in session:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    emp_id = session['employer_id']

    if request.method == 'GET':
        with db_cursor() as cursor:
            cursor.execute("""
                SELECT id, company_name, email, mobile, industry, location, company_size,
                       website, company_website, description, founded_year, linkedin_url,
                       twitter_url, is_verified, verification_status, verified_at,
                       verification_notes, verification_submitted_at, created_at
                FROM employee
                WHERE id = %s
            """, (emp_id,))
            emp = cursor.fetchone()
        if not emp:
            return jsonify({'success': False, 'message': 'Employer not found'}), 404

        # Format timestamps
        if emp.get('verified_at') and hasattr(emp['verified_at'], 'strftime'):
            emp['verified_at_formatted'] = emp['verified_at'].strftime('%d %b %Y')
        if emp.get('verification_submitted_at') and hasattr(emp['verification_submitted_at'], 'strftime'):
            emp['submitted_at_formatted'] = emp['verification_submitted_at'].strftime('%d %b %Y')
        if emp.get('created_at') and hasattr(emp['created_at'], 'strftime'):
            emp['member_since'] = emp['created_at'].strftime('%b %Y')

        emp['website'] = emp.get('website') or emp.get('company_website') or ''
        emp['completeness'] = compute_company_completeness(emp)
        return jsonify({'success': True, 'employer': emp})

    # POST: Update company branding
    data = request.get_json(silent=True) or request.form.to_dict() or {}
    company_name = (data.get('company_name') or '').strip()
    if not company_name:
        return jsonify({'success': False, 'message': 'Company name is required'}), 400

    mobile = (data.get('mobile') or '').strip()
    industry = (data.get('industry') or '').strip()
    location = (data.get('location') or '').strip()
    size = (data.get('size') or data.get('company_size') or '').strip()
    website = (data.get('website') or data.get('company_website') or '').strip()
    description = (data.get('description') or '').strip()
    founded_year = (data.get('founded_year') or '').strip()
    linkedin_url = (data.get('linkedin_url') or '').strip()
    twitter_url = (data.get('twitter_url') or '').strip()

    try:
        with db_cursor(dictionary=False) as cursor:
            cursor.execute("""
                UPDATE employee
                SET company_name = %s, mobile = %s, industry = %s, location = %s,
                    company_size = %s, website = %s, company_website = %s, description = %s,
                    founded_year = %s, linkedin_url = %s, twitter_url = %s
                WHERE id = %s
            """, (company_name, mobile, industry, location, size, website, website,
                  description, founded_year, linkedin_url, twitter_url, emp_id))
            cursor.execute("UPDATE jobs SET company_name = %s WHERE employer_id = %s",
                           (company_name, emp_id))
            cursor.execute("UPDATE profile_views SET company_name = %s WHERE employer_id = %s",
                           (company_name, emp_id))
        session['user_name'] = company_name
        session['company_name'] = company_name
        return jsonify({'success': True, 'message': 'Company profile updated successfully!'})
    except Exception as e:
        logger.error(f"Error updating employer profile: {e}")
        return jsonify({'success': False, 'message': 'Error updating profile'}), 500


@app.route('/api/employer/request_verification', methods=['POST'])
@limiter.limit("10 per minute")
def api_employer_request_verification():
    if 'employer_id' not in session:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    emp_id = session['employer_id']

    notes = sanitize_text(request.form.get('notes', '')).strip() if request.form else ''
    saved_doc_name = ''

    # Check if a verification document is attached
    if 'verification_doc' in request.files:
        file = request.files['verification_doc']
        if file and file.filename:
            filename = secure_filename(file.filename)
            ext = os.path.splitext(filename)[1].lower()
            if ext not in ('.pdf', '.png', '.jpg', '.jpeg'):
                return jsonify({'success': False, 'message': 'Invalid file format. Only PDF, PNG, and JPG allowed.'}), 400

            unique_name = f"verif_emp_{emp_id}_{int(datetime.now().timestamp())}{ext}"
            file_path = os.path.join(VERIFICATION_DOCS_FOLDER, unique_name)
            file.save(file_path)

            if os.path.getsize(file_path) > 5 * 1024 * 1024:
                os.remove(file_path)
                return jsonify({'success': False, 'message': 'Document exceeds 5MB limit.'}), 400
            saved_doc_name = unique_name

    try:
        with db_cursor(dictionary=False) as cursor:
            if saved_doc_name:
                cursor.execute("""
                    UPDATE employee
                    SET verification_status = 'pending',
                        verification_submitted_at = NOW(),
                        verification_doc_path = %s,
                        verification_notes = %s
                    WHERE id = %s
                """, (saved_doc_name, notes, emp_id))
            else:
                cursor.execute("""
                    UPDATE employee
                    SET verification_status = 'pending',
                        verification_submitted_at = NOW(),
                        verification_notes = %s
                    WHERE id = %s
                """, (notes, emp_id))

        logger.info(f"Employer #{emp_id} submitted verification request.")
        return jsonify({
            'success': True,
            'message': 'Verification request submitted. Our trust & safety team will review your organization details.',
            'status': 'pending'
        })
    except Exception as e:
        logger.error(f"Error submitting verification: {e}")
        return jsonify({'success': False, 'message': 'Failed to submit verification request.'}), 500


# --- 100% DATABASE-DRIVEN PUBLIC COMPANY APIs ---
@app.route('/api/companies')
def api_companies():
    """Returns all legitimate registered employers from database with real active job counts."""
    with db_cursor() as cursor:
        cursor.execute("""
            SELECT e.id, e.company_name, e.industry, e.location,
                   COALESCE(e.company_size, '50-200') AS size,
                   e.is_verified, e.verification_status, e.website, e.company_website,
                   COUNT(CASE WHEN j.is_active = 1 AND (j.status = 'Published' OR j.status IS NULL) AND (j.application_deadline IS NULL OR j.application_deadline >= CURDATE()) THEN 1 END) AS open_jobs,
                   COUNT(j.id) AS total_jobs
            FROM employee e
            LEFT JOIN jobs j ON e.id = j.employer_id
            GROUP BY e.id
            ORDER BY e.is_verified DESC, open_jobs DESC, e.id DESC
        """)
        companies = cursor.fetchall()

    for c in companies:
        c['company_name'] = (c.get('company_name') or 'Verified Employer').strip()
        c['industry'] = c.get('industry') or 'Technology & Innovation'
        c['location'] = c.get('location') or 'Pan-India / Remote'
        c['size'] = c.get('size') or '50 - 200 Employees'
        c['is_company_verified'] = bool(c.get('is_verified') or c.get('verification_status') == 'verified')
        c['website'] = c.get('website') or c.get('company_website') or ''

    return jsonify({'success': True, 'companies': companies})


@app.route('/api/company/<int:company_id>')
def api_company_detail(company_id):
    """Returns public company profile with trust signals without exposing private admin notes."""
    with db_cursor() as cursor:
        cursor.execute("""
            SELECT e.id, e.company_name, e.email, e.mobile, e.industry, e.location,
                   COALESCE(e.company_size, '50-200') AS size,
                   COALESCE(e.website, e.company_website) AS website,
                   e.description, e.founded_year, e.linkedin_url, e.twitter_url,
                   e.is_verified, e.verification_status, e.verified_at, e.created_at,
                   COUNT(CASE WHEN j.is_active = 1 AND (j.status = 'Published' OR j.status IS NULL) AND (j.application_deadline IS NULL OR j.application_deadline >= CURDATE()) THEN 1 END) AS open_jobs,
                   COUNT(j.id) AS total_jobs
            FROM employee e
            LEFT JOIN jobs j ON e.id = j.employer_id
            WHERE e.id = %s
            GROUP BY e.id
        """, (company_id,))
        company = cursor.fetchone()

    if not company:
        return jsonify({'success': False, 'message': 'Company not found'}), 404

    # Format trust signals and dates
    company['company_name'] = (company.get('company_name') or 'Company').strip()
    company['industry'] = company.get('industry') or 'Technology & Innovation'
    company['location'] = company.get('location') or 'Pan-India / Remote'
    company['size'] = company.get('size') or '50 - 200 Employees'
    company['description'] = company.get('description') or 'Dedicated to building high-impact products and empowering our team members with career growth.'
    company['is_company_verified'] = bool(company.get('is_verified') or company.get('verification_status') == 'verified')
    company['completeness'] = compute_company_completeness(company)

    if company.get('verified_at') and hasattr(company['verified_at'], 'strftime'):
        company['verified_on'] = company['verified_at'].strftime('%d %B %Y')
    else:
        company['verified_on'] = None

    if company.get('created_at') and hasattr(company['created_at'], 'strftime'):
        company['member_since'] = company['created_at'].strftime('%B %Y')
    else:
        company['member_since'] = 'Recently'

    # Security: Strip private admin notes and private verification doc path
    company.pop('verification_notes', None)
    company.pop('verification_doc_path', None)

    return jsonify({'success': True, 'company': company})


@app.route('/api/company/<int:company_id>/jobs')
def api_company_jobs(company_id):
    with db_cursor() as cursor:
        cursor.execute("""
            SELECT j.*, COALESCE(e.company_name, j.company_name) AS company_name,
                   e.is_verified AS employer_is_verified, e.verification_status AS employer_verification_status
            FROM jobs j
            LEFT JOIN employee e ON j.employer_id = e.id
            WHERE j.employer_id = %s AND j.is_active = 1
            ORDER BY j.id DESC
        """, (company_id,))
        jobs = cursor.fetchall()
    for j in jobs:
        if j.get('created_at'): j['created_at'] = j['created_at'].strftime('%Y-%m-%d')
    return jsonify({'success': True, 'jobs': jobs})

@app.route('/api/company/<int:company_id>/follow', methods=['POST'])
def api_company_follow(company_id):
    if 'user_id' not in session: return jsonify({'success': False, 'message': 'Login required'}), 401
    with db_cursor() as cursor:
        cursor.execute("SELECT id FROM employee WHERE id = %s", (company_id,))
        if not cursor.fetchone():
            return jsonify({'success': False, 'message': 'Company not found'}), 404
        cursor.execute("SELECT id FROM company_follows WHERE user_id = %s AND company_id = %s", (session['user_id'], company_id))
        if cursor.fetchone():
            return jsonify({'success': False, 'message': 'Already following this company'}), 400
        cursor.execute("INSERT INTO company_follows (user_id, company_id) VALUES (%s, %s)", (session['user_id'], company_id))
    return jsonify({'success': True, 'message': 'Company followed!'})

@app.route('/api/candidates', methods=['POST'])
def api_candidates_search():
    if 'employer_id' not in session: return jsonify({'success': False}), 401
    data = request.get_json(silent=True) or {}
    keyword = (data.get('query') or '').strip()
    skills = (data.get('skills') or '').strip()
    location = (data.get('location') or '').strip()
    experience_years = (data.get('experience') or '').strip()
    if not keyword and not skills and not location and not experience_years:
        return jsonify({'success': False, 'message': 'At least one filter parameter (skills, location, experience_years, or keyword) is required'}), 400
    where_clauses = ["consent_to_search = 1"]
    params = []
    is_recruiter = 1 if 'employer_id' in session else 0
    where_clauses.append(
        "(profile_visibility = 'public' OR (profile_visibility = 'recruiters_only' AND %s = 1))"
    )
    params.append(is_recruiter)
    if keyword:
        where_clauses.append("(name LIKE %s OR skills LIKE %s)")
        params.extend([f'%{keyword}%', f'%{keyword}%'])
    if skills:
        where_clauses.append("skills LIKE %s")
        params.append(f'%{skills}%')
    if location:
        where_clauses.append("location LIKE %s")
        params.append(f'%{location}%')
    if experience_years:
        try:
            exp = int(experience_years)
            where_clauses.append("experience >= %s")
            params.append(exp)
        except ValueError:
            return jsonify({'success': False, 'message': 'Invalid experience parameter'}), 400
    where_sql = " AND ".join(where_clauses)
    try:
        page = max(int(data.get('page', 1)), 1)
        per_page = min(max(int(data.get('per_page', 20)), 1), 50)
    except (ValueError, TypeError):
        page = 1
        per_page = 20
    offset = (page - 1) * per_page
    query = (
        f"SELECT u.id, u.name, u.headline, u.skills, u.experience, u.location "
        f"FROM user u WHERE {where_sql} ORDER BY u.id DESC LIMIT %s OFFSET %s"
    )
    params.extend([per_page, offset])
    with db_cursor() as cursor:
        cursor.execute(query, tuple(params))
        candidates = cursor.fetchall()
    return jsonify({'success': True, 'candidates': candidates, 'page': page, 'per_page': per_page})

@app.route('/api/candidates/<int:candidate_id>')
def api_candidate_detail(candidate_id):
    if 'employer_id' not in session: return jsonify({'success': False}), 401
    with db_cursor() as cursor:
        cursor.execute(
            "SELECT u.id, u.name, u.email, u.headline, u.skills, u.experience, u.location "
            "FROM user u WHERE u.id = %s", (candidate_id,))
        candidate = cursor.fetchone()
    if not candidate:
        return jsonify({'success': False, 'message': 'Candidate not found'}), 404
    with db_cursor() as cursor:
        cursor.execute(
            "SELECT 1 FROM applications a JOIN jobs j ON a.job_id = j.id "
            "WHERE a.user_id = %s AND j.employer_id = %s "
            "AND a.status IN ('Applied', 'Shortlisted', 'Interview') LIMIT 1",
            (candidate_id, session['employer_id'])
        )
        has_active_application = cursor.fetchone() is not None
        if has_active_application:
            cursor.execute("SELECT mobile FROM user WHERE id = %s", (candidate_id,))
            row = cursor.fetchone()
            candidate['mobile'] = row['mobile'] if row else None
    return jsonify({'success': True, 'candidate': candidate})

@app.route('/api/candidates/<int:candidate_id>/save', methods=['POST'])
def api_candidate_save(candidate_id):
    if 'employer_id' not in session: return jsonify({'success': False}), 401
    with db_cursor() as cursor:
        cursor.execute("SELECT id FROM user WHERE id = %s", (candidate_id,))
        if not cursor.fetchone():
            return jsonify({'success': False, 'message': 'Candidate not found'}), 404
        cursor.execute("SELECT id FROM saved_candidates WHERE recruiter_id = %s AND candidate_id = %s", (session['employer_id'], candidate_id))
        if cursor.fetchone():
            return jsonify({'success': False, 'message': 'Candidate already saved'}), 400
        cursor.execute("INSERT INTO saved_candidates (recruiter_id, candidate_id) VALUES (%s, %s)", (session['employer_id'], candidate_id))
    return jsonify({'success': True, 'message': 'Candidate saved to pool'})

@app.route('/api/interviews')
def api_interviews():
    if 'employer_id' not in session and 'user_id' not in session:
        return jsonify({'success': False}), 401
    with db_cursor() as cursor:
        if 'employer_id' in session:
            cursor.execute("""
                SELECT i.id, i.job_id, j.title AS job_title, i.candidate_id, u.name AS candidate_name,
                       i.scheduled_date, i.scheduled_time, i.status, i.created_at
                FROM interviews i
                JOIN jobs j ON i.job_id = j.id
                JOIN user u ON i.candidate_id = u.id
                WHERE i.employer_id = %s
                ORDER BY i.scheduled_date DESC, i.scheduled_time DESC
            """, (session['employer_id'],))
        else:
            cursor.execute("""
                SELECT i.id, i.job_id, j.title AS job_title, i.employer_id, e.company_name,
                       i.scheduled_date, i.scheduled_time, i.status, i.created_at
                FROM interviews i
                JOIN jobs j ON i.job_id = j.id
                JOIN employee e ON i.employer_id = e.id
                WHERE i.candidate_id = %s
                ORDER BY i.scheduled_date DESC, i.scheduled_time DESC
            """, (session['user_id'],))
        interviews = cursor.fetchall()
    for iv in interviews:
        if iv.get('scheduled_date'):
            iv['scheduled_date'] = iv['scheduled_date'].strftime('%Y-%m-%d')
        if iv.get('scheduled_time'):
            iv['scheduled_time'] = str(iv['scheduled_time'])
        if iv.get('created_at'):
            iv['created_at'] = str(iv['created_at'])
    return jsonify({'success': True, 'interviews': interviews})

@app.route('/api/interviews/<int:interview_id>')
def api_interview_detail(interview_id):
    if 'employer_id' not in session and 'user_id' not in session:
        return jsonify({'success': False}), 401
    with db_cursor() as cursor:
        cursor.execute("SELECT * FROM interviews WHERE id = %s", (interview_id,))
        interview = cursor.fetchone()
    if not interview:
        return jsonify({'success': False, 'message': 'Interview not found'}), 404
    if 'user_id' in session and interview['candidate_id'] != session['user_id']:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403
    if 'employer_id' in session and interview['employer_id'] != session['employer_id']:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403
    with db_cursor() as cursor:
        if 'employer_id' in session:
            cursor.execute("""
                SELECT i.id, i.job_id, j.title AS job_title, i.company_name AS company_name,
                       i.candidate_id, u.name AS candidate_name,
                       i.scheduled_date, i.scheduled_time, i.status, i.interviewer_notes, i.created_at
                FROM interviews i
                JOIN jobs j ON i.job_id = j.id
                JOIN user u ON i.candidate_id = u.id
                WHERE i.id = %s
            """, (interview_id,))
        else:
            cursor.execute("""
                SELECT i.id, i.job_id, j.title AS job_title, i.company_name,
                       i.scheduled_date, i.scheduled_time, i.status, i.interviewer_notes, i.created_at
                FROM interviews i
                JOIN jobs j ON i.job_id = j.id
                WHERE i.id = %s
            """, (interview_id,))
        interview = cursor.fetchone()
    if interview.get('scheduled_date'):
        interview['scheduled_date'] = interview['scheduled_date'].strftime('%Y-%m-%d')
    if interview.get('scheduled_time'):
        interview['scheduled_time'] = str(interview['scheduled_time'])
    return jsonify({'success': True, 'interview': interview})

@app.route('/api/interviews/<int:interview_id>/cancel', methods=['POST'])
def api_interview_cancel(interview_id):
    if 'employer_id' not in session and 'user_id' not in session:
        return jsonify({'success': False}), 401
    with db_cursor() as cursor:
        cursor.execute("SELECT id, candidate_id, employer_id FROM interviews WHERE id = %s", (interview_id,))
        interview = cursor.fetchone()
    if not interview:
        return jsonify({'success': False, 'message': 'Interview not found'}), 404
    if 'user_id' in session and interview['candidate_id'] != session['user_id']:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403
    if 'employer_id' in session and interview['employer_id'] != session['employer_id']:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403
    with db_cursor() as cursor:
        cursor.execute(
            "UPDATE interviews SET status = 'cancelled', cancelled_at = NOW() WHERE id = %s",
            (interview_id,)
        )
    return jsonify({'success': True, 'message': 'Interview cancelled'})

# ==============================================================================
# HIREVOLTZ CANDIDATE <-> EMPLOYER SECURE MESSAGING SYSTEM
# ==============================================================================

def get_or_create_conversation(candidate_id, employer_id, job_id=None):
    """
    Finds existing conversation between candidate and employer, or creates a new one.
    Updates job_id if not previously attached and provided.
    """
    with db_cursor() as cursor:
        cursor.execute("""
            SELECT id, candidate_id, employer_id, job_id, last_message_at
            FROM conversations
            WHERE candidate_id = %s AND employer_id = %s
            ORDER BY id ASC LIMIT 1
        """, (candidate_id, employer_id))
        row = cursor.fetchone()
        if row:
            if job_id and not row.get('job_id'):
                cursor.execute("UPDATE conversations SET job_id = %s WHERE id = %s", (job_id, row['id']))
            return row['id']
        cursor.execute("""
            INSERT INTO conversations (candidate_id, employer_id, job_id, last_message_at)
            VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
        """, (candidate_id, employer_id, job_id))
        return cursor.lastrowid


@app.route('/api/conversations', methods=['GET'])
@app.route('/api/messages/conversations', methods=['GET'])
@app.route('/api/messages', methods=['GET'])
def api_get_conversations():
    """
    Returns list of active conversations for the authenticated candidate or employer.
    Includes participant metadata, job context, latest message snippet, unread counter, and relative timestamps.
    """
    if 'user_id' not in session and 'employer_id' not in session:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401

    is_employer = 'employer_id' in session and 'user_id' not in session
    now = datetime.now()

    if is_employer:
        emp_id = session['employer_id']
        with db_cursor() as cursor:
            cursor.execute("""
                SELECT c.id, c.candidate_id, c.employer_id, c.job_id, c.last_message_at, c.created_at,
                       u.name AS candidate_name, u.email AS candidate_email,
                       j.title AS job_title
                FROM conversations c
                JOIN user u ON c.candidate_id = u.id
                LEFT JOIN jobs j ON c.job_id = j.id
                WHERE c.employer_id = %s
                ORDER BY c.last_message_at DESC
            """, (emp_id,))
            rows = cursor.fetchall()

            conversations = []
            for r in rows:
                conv_id = r['id']
                # Get last message
                cursor.execute("""
                    SELECT id, sender_role, sender_id, receiver_id, content, sent_at, is_read
                    FROM messages
                    WHERE conversation_id = %s OR (
                        ((sender_id = %s AND receiver_id = %s) OR (sender_id = %s AND receiver_id = %s))
                        AND conversation_id IS NULL
                    )
                    ORDER BY sent_at DESC, id DESC
                    LIMIT 1
                """, (conv_id, r['candidate_id'], emp_id, emp_id, r['candidate_id']))
                last_msg = cursor.fetchone()

                # Get unread count for employer in this conversation
                cursor.execute("""
                    SELECT COUNT(*) AS unread_count
                    FROM messages
                    WHERE (conversation_id = %s OR (sender_id = %s AND receiver_id = %s AND conversation_id IS NULL))
                      AND receiver_id = %s AND is_read = 0
                """, (conv_id, r['candidate_id'], emp_id, emp_id))
                unread_res = cursor.fetchone()
                unread_count = unread_res['unread_count'] if unread_res else 0

                time_ago = 'Recently'
                last_time = (last_msg['sent_at'] if last_msg and last_msg.get('sent_at') else r.get('last_message_at'))
                if last_time and isinstance(last_time, datetime):
                    diff = now - last_time
                    secs = int(diff.total_seconds())
                    if secs < 60: time_ago = 'Just now'
                    elif secs < 3600: time_ago = f"{max(1, secs // 60)}m ago"
                    elif secs < 86400: time_ago = f"{secs // 3600}h ago"
                    elif secs < 604800: time_ago = f"{secs // 86400}d ago"
                    else: time_ago = last_time.strftime('%b %d')

                cand_name = r.get('candidate_name') or 'Candidate'
                conversations.append({
                    'id': conv_id,
                    'candidate_id': r['candidate_id'],
                    'employer_id': r['employer_id'],
                    'participant_name': cand_name,
                    'participant_initial': cand_name[0].upper() if cand_name else 'C',
                    'job_id': r.get('job_id'),
                    'job_title': r.get('job_title') or '',
                    'last_message': last_msg['content'] if last_msg else 'Started a conversation',
                    'last_message_time': time_ago,
                    'last_message_at': last_time.isoformat() if isinstance(last_time, datetime) else None,
                    'last_sender_role': last_msg['sender_role'] if last_msg else None,
                    'unread_count': unread_count,
                    'is_read': bool(last_msg['is_read']) if last_msg else True
                })

            return jsonify({
                'success': True,
                'conversations': conversations,
                'role': 'employer'
            })
    else:
        user_id = session['user_id']
        with db_cursor() as cursor:
            cursor.execute("""
                SELECT c.id, c.candidate_id, c.employer_id, c.job_id, c.last_message_at, c.created_at,
                       e.company_name, e.email AS company_email,
                       j.title AS job_title
                FROM conversations c
                JOIN employee e ON c.employer_id = e.id
                LEFT JOIN jobs j ON c.job_id = j.id
                WHERE c.candidate_id = %s
                ORDER BY c.last_message_at DESC
            """, (user_id,))
            rows = cursor.fetchall()

            conversations = []
            for r in rows:
                conv_id = r['id']
                # Get last message
                cursor.execute("""
                    SELECT id, sender_role, sender_id, receiver_id, content, sent_at, is_read
                    FROM messages
                    WHERE conversation_id = %s OR (
                        ((sender_id = %s AND receiver_id = %s) OR (sender_id = %s AND receiver_id = %s))
                        AND conversation_id IS NULL
                    )
                    ORDER BY sent_at DESC, id DESC
                    LIMIT 1
                """, (conv_id, user_id, r['employer_id'], r['employer_id'], user_id))
                last_msg = cursor.fetchone()

                # Get unread count for candidate in this conversation
                cursor.execute("""
                    SELECT COUNT(*) AS unread_count
                    FROM messages
                    WHERE (conversation_id = %s OR (sender_id = %s AND receiver_id = %s AND conversation_id IS NULL))
                      AND receiver_id = %s AND is_read = 0
                """, (conv_id, r['employer_id'], user_id, user_id))
                unread_res = cursor.fetchone()
                unread_count = unread_res['unread_count'] if unread_res else 0

                time_ago = 'Recently'
                last_time = (last_msg['sent_at'] if last_msg and last_msg.get('sent_at') else r.get('last_message_at'))
                if last_time and isinstance(last_time, datetime):
                    diff = now - last_time
                    secs = int(diff.total_seconds())
                    if secs < 60: time_ago = 'Just now'
                    elif secs < 3600: time_ago = f"{max(1, secs // 60)}m ago"
                    elif secs < 86400: time_ago = f"{secs // 3600}h ago"
                    elif secs < 604800: time_ago = f"{secs // 86400}d ago"
                    else: time_ago = last_time.strftime('%b %d')

                comp_name = r.get('company_name') or 'Employer'
                conversations.append({
                    'id': conv_id,
                    'candidate_id': r['candidate_id'],
                    'employer_id': r['employer_id'],
                    'participant_name': comp_name,
                    'participant_initial': comp_name[0].upper() if comp_name else 'E',
                    'job_id': r.get('job_id'),
                    'job_title': r.get('job_title') or '',
                    'last_message': last_msg['content'] if last_msg else 'Started a conversation',
                    'last_message_time': time_ago,
                    'last_message_at': last_time.isoformat() if isinstance(last_time, datetime) else None,
                    'last_sender_role': last_msg['sender_role'] if last_msg else None,
                    'unread_count': unread_count,
                    'is_read': bool(last_msg['is_read']) if last_msg else True
                })

            return jsonify({
                'success': True,
                'conversations': conversations,
                'role': 'candidate'
            })


@app.route('/api/conversations/<int:conversation_id>', methods=['GET'])
@app.route('/api/messages/conversations/<int:conversation_id>', methods=['GET'])
def api_get_conversation_thread(conversation_id):
    """
    Returns message thread for a conversation with strict IDOR ownership checks.
    Supports ?since_id=<id> for incremental polling.
    Automatically marks incoming unread messages as read.
    """
    if 'user_id' not in session and 'employer_id' not in session:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401

    is_employer = 'employer_id' in session and 'user_id' not in session
    curr_user_id = session['employer_id'] if is_employer else session['user_id']
    since_id = request.args.get('since_id', type=int)

    with db_cursor() as cursor:
        cursor.execute("""
            SELECT c.id, c.candidate_id, c.employer_id, c.job_id, c.created_at,
                   u.name AS candidate_name, u.email AS candidate_email,
                   e.company_name, e.email AS company_email,
                   j.title AS job_title
            FROM conversations c
            JOIN user u ON c.candidate_id = u.id
            JOIN employee e ON c.employer_id = e.id
            LEFT JOIN jobs j ON c.job_id = j.id
            WHERE c.id = %s
        """, (conversation_id,))
        conv = cursor.fetchone()
        if not conv:
            return jsonify({'success': False, 'message': 'Conversation not found'}), 404

        # Strict IDOR check
        if is_employer:
            if conv['employer_id'] != curr_user_id:
                return jsonify({'success': False, 'message': 'Access forbidden'}), 403
        else:
            if conv['candidate_id'] != curr_user_id:
                return jsonify({'success': False, 'message': 'Access forbidden'}), 403

        # Mark unread incoming messages as read
        cursor.execute("""
            UPDATE messages
            SET is_read = 1, read_at = CURRENT_TIMESTAMP
            WHERE (conversation_id = %s OR (
                ((sender_id = %s AND receiver_id = %s) OR (sender_id = %s AND receiver_id = %s))
                AND conversation_id IS NULL
            ))
            AND receiver_id = %s AND is_read = 0
        """, (conversation_id, conv['candidate_id'], conv['employer_id'], conv['employer_id'], conv['candidate_id'], curr_user_id))

        # Query messages
        params = [conversation_id, conv['candidate_id'], conv['employer_id'], conv['employer_id'], conv['candidate_id']]
        since_sql = ""
        if since_id:
            since_sql = " AND m.id > %s "
            params.append(since_id)

        cursor.execute(f"""
            SELECT m.id, m.conversation_id, m.sender_role, m.sender_id, m.receiver_id,
                   m.content, m.sent_at, m.is_read, m.read_at
            FROM messages m
            WHERE (m.conversation_id = %s OR (
                ((m.sender_id = %s AND m.receiver_id = %s) OR (m.sender_id = %s AND m.receiver_id = %s))
                AND m.conversation_id IS NULL
            ))
            {since_sql}
            ORDER BY m.sent_at ASC, m.id ASC
        """, params)
        raw_msgs = cursor.fetchall()

    now = datetime.now()
    messages = []
    for m in raw_msgs:
        sent_dt = m.get('sent_at')
        time_str = ''
        date_str = ''
        if sent_dt and isinstance(sent_dt, datetime):
            time_str = sent_dt.strftime('%I:%M %p').lstrip('0')
            if sent_dt.date() == now.date():
                date_str = 'Today'
            elif (now.date() - sent_dt.date()).days == 1:
                date_str = 'Yesterday'
            else:
                date_str = sent_dt.strftime('%b %d, %Y')
            sent_iso = sent_dt.isoformat()
        else:
            sent_iso = None

        is_me = False
        if is_employer and m['sender_role'] == 'employer' and m['sender_id'] == curr_user_id:
            is_me = True
        elif not is_employer and m['sender_role'] == 'candidate' and m['sender_id'] == curr_user_id:
            is_me = True

        messages.append({
            'id': m['id'],
            'sender_role': m.get('sender_role') or ('employer' if is_employer and is_me else 'candidate'),
            'sender_id': m['sender_id'],
            'receiver_id': m['receiver_id'],
            'content': m['content'],
            'sent_at': sent_iso,
            'time_str': time_str,
            'date_str': date_str,
            'is_read': bool(m.get('is_read')),
            'read_at': m['read_at'].isoformat() if m.get('read_at') and isinstance(m['read_at'], datetime) else None,
            'is_me': is_me
        })

    participant_name = conv['candidate_name'] if is_employer else conv['company_name']
    meta = {
        'id': conv['id'],
        'candidate_id': conv['candidate_id'],
        'employer_id': conv['employer_id'],
        'participant_name': participant_name,
        'participant_initial': participant_name[0].upper() if participant_name else ('C' if is_employer else 'E'),
        'job_id': conv.get('job_id'),
        'job_title': conv.get('job_title') or '',
        'role': 'employer' if is_employer else 'candidate'
    }

    return jsonify({
        'success': True,
        'conversation': meta,
        'messages': messages
    })


@app.route('/api/conversations/<int:conversation_id>/messages', methods=['POST'])
@limiter.limit("30 per minute")
def api_send_conversation_message(conversation_id):
    """
    Sends a message within an existing conversation.
    Enforces authorization, sanitizes content, dispatches notifications, and updates conversation activity.
    """
    if 'user_id' not in session and 'employer_id' not in session:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401

    is_employer = 'employer_id' in session and 'user_id' not in session
    curr_user_id = session['employer_id'] if is_employer else session['user_id']

    data = request.get_json(silent=True) or {}
    raw_content = data.get('content') or ''
    content = sanitize_text(raw_content).strip()
    if not content:
        return jsonify({'success': False, 'message': 'Message content cannot be empty'}), 400
    if len(content) > 2000:
        return jsonify({'success': False, 'message': 'Message cannot exceed 2,000 characters'}), 400

    with db_cursor() as cursor:
        cursor.execute("""
            SELECT c.id, c.candidate_id, c.employer_id, c.job_id,
                   u.name AS candidate_name, e.company_name
            FROM conversations c
            JOIN user u ON c.candidate_id = u.id
            JOIN employee e ON c.employer_id = e.id
            WHERE c.id = %s
        """, (conversation_id,))
        conv = cursor.fetchone()
        if not conv:
            return jsonify({'success': False, 'message': 'Conversation not found'}), 404

        # Strict IDOR check
        if is_employer:
            if conv['employer_id'] != curr_user_id:
                return jsonify({'success': False, 'message': 'Access forbidden'}), 403
            sender_role = 'employer'
            sender_id = curr_user_id
            receiver_id = conv['candidate_id']
            sender_name = session.get('company_name') or conv.get('company_name') or 'Recruiter'
        else:
            if conv['candidate_id'] != curr_user_id:
                return jsonify({'success': False, 'message': 'Access forbidden'}), 403
            sender_role = 'candidate'
            sender_id = curr_user_id
            receiver_id = conv['employer_id']
            sender_name = session.get('user_name') or conv.get('candidate_name') or 'Candidate'

        # Insert message
        cursor.execute("""
            INSERT INTO messages (conversation_id, sender_role, sender_id, receiver_id, content, sent_at, is_read)
            VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP, 0)
        """, (conversation_id, sender_role, sender_id, receiver_id, content))
        msg_id = cursor.lastrowid

        # Update conversation activity
        cursor.execute("""
            UPDATE conversations
            SET last_message_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """, (conversation_id,))

    # Trigger notification to receiver
    preview = content[:100] + ('...' if len(content) > 100 else '')
    if is_employer:
        create_notification(
            user_id=receiver_id,
            notification_type='new_message',
            title=f"New Message from {sender_name} 💬",
            message=f"{sender_name}: {preview}",
            action_url='/candidate/messages'
        )
    else:
        create_notification(
            employer_id=receiver_id,
            notification_type='new_message',
            title=f"New Message from {sender_name} 💬",
            message=f"{sender_name}: {preview}",
            action_url='/recruiter/messages'
        )

    now_iso = datetime.now().isoformat()
    return jsonify({
        'success': True,
        'message': 'Message sent',
        'id': msg_id,
        'conversation_id': conversation_id,
        'message_data': {
            'id': msg_id,
            'conversation_id': conversation_id,
            'sender_role': sender_role,
            'sender_id': sender_id,
            'receiver_id': receiver_id,
            'content': content,
            'sent_at': now_iso,
            'is_read': False,
            'is_me': True
        }
    })


@app.route('/api/messages', methods=['POST'])
@limiter.limit("30 per minute")
def api_send_message():
    """
    Universal send message endpoint.
    Automatically resolves or initializes conversation and dispatches message + notification.
    """
    if 'user_id' not in session and 'employer_id' not in session:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401

    data = request.get_json(silent=True) or {}
    conv_id = data.get('conversation_id')
    if conv_id:
        try:
            return api_send_conversation_message(int(conv_id))
        except (ValueError, TypeError):
            pass

    receiver_id = data.get('receiver_id')
    raw_content = data.get('content') or ''
    content = sanitize_text(raw_content).strip()
    job_id = data.get('job_id')

    if not receiver_id or not content:
        return jsonify({'success': False, 'message': 'Receiver ID and content are required'}), 400
    if len(content) > 2000:
        return jsonify({'success': False, 'message': 'Message cannot exceed 2,000 characters'}), 400

    try:
        receiver_id = int(receiver_id)
    except (ValueError, TypeError):
        return jsonify({'success': False, 'message': 'Invalid receiver ID'}), 400

    is_employer = 'employer_id' in session and 'user_id' not in session

    if is_employer:
        sender_id = session['employer_id']
        with db_cursor() as cursor:
            cursor.execute("SELECT id, name FROM user WHERE id = %s", (receiver_id,))
            u_row = cursor.fetchone()
            if not u_row:
                return jsonify({'success': False, 'message': 'Recipient not found'}), 404
        conv_id = get_or_create_conversation(candidate_id=receiver_id, employer_id=sender_id, job_id=job_id)
        sender_role = 'employer'
        sender_name = session.get('company_name') or 'Recruiter'
    else:
        sender_id = session['user_id']
        with db_cursor() as cursor:
            cursor.execute("SELECT id, company_name FROM employee WHERE id = %s", (receiver_id,))
            emp_row = cursor.fetchone()
            if not emp_row:
                return jsonify({'success': False, 'message': 'Recipient not found'}), 404
        conv_id = get_or_create_conversation(candidate_id=sender_id, employer_id=receiver_id, job_id=job_id)
        sender_role = 'candidate'
        sender_name = session.get('user_name') or 'Candidate'

    with db_cursor() as cursor:
        cursor.execute("""
            INSERT INTO messages (conversation_id, sender_role, sender_id, receiver_id, content, sent_at, is_read)
            VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP, 0)
        """, (conv_id, sender_role, sender_id, receiver_id, content))
        msg_id = cursor.lastrowid
        cursor.execute("""
            UPDATE conversations
            SET last_message_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """, (conv_id,))

    preview = content[:100] + ('...' if len(content) > 100 else '')
    if is_employer:
        create_notification(
            user_id=receiver_id,
            notification_type='new_message',
            title=f"New Message from {sender_name} 💬",
            message=f"{sender_name}: {preview}",
            action_url='/candidate/messages'
        )
    else:
        create_notification(
            employer_id=receiver_id,
            notification_type='new_message',
            title=f"New Message from {sender_name} 💬",
            message=f"{sender_name}: {preview}",
            action_url='/recruiter/messages'
        )

    return jsonify({
        'success': True,
        'message': 'Message sent',
        'id': msg_id,
        'conversation_id': conv_id
    })


@app.route('/api/messages/unread_count', methods=['GET'])
def api_messages_unread_count():
    """Returns fast aggregate count of unread messages for current user/employer."""
    if 'user_id' not in session and 'employer_id' not in session:
        return jsonify({'success': True, 'unread_count': 0})

    is_employer = 'employer_id' in session and 'user_id' not in session
    curr_id = session['employer_id'] if is_employer else session['user_id']

    with db_cursor() as cursor:
        cursor.execute("""
            SELECT COUNT(*) AS unread
            FROM messages
            WHERE receiver_id = %s AND is_read = 0
        """, (curr_id,))
        res = cursor.fetchone()
        count = res['unread'] if res else 0

    return jsonify({'success': True, 'unread_count': count})


@app.route('/api/conversations/<int:conversation_id>/read', methods=['POST'])
def api_mark_conversation_read(conversation_id):
    """Marks all incoming messages in a conversation as read for current user."""
    if 'user_id' not in session and 'employer_id' not in session:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401

    is_employer = 'employer_id' in session and 'user_id' not in session
    curr_id = session['employer_id'] if is_employer else session['user_id']

    with db_cursor() as cursor:
        cursor.execute("SELECT candidate_id, employer_id FROM conversations WHERE id = %s", (conversation_id,))
        conv = cursor.fetchone()
        if not conv:
            return jsonify({'success': False, 'message': 'Conversation not found'}), 404
        if is_employer and conv['employer_id'] != curr_id:
            return jsonify({'success': False, 'message': 'Forbidden'}), 403
        if not is_employer and conv['candidate_id'] != curr_id:
            return jsonify({'success': False, 'message': 'Forbidden'}), 403

        cursor.execute("""
            UPDATE messages
            SET is_read = 1, read_at = CURRENT_TIMESTAMP
            WHERE (conversation_id = %s OR (
                ((sender_id = %s AND receiver_id = %s) OR (sender_id = %s AND receiver_id = %s))
                AND conversation_id IS NULL
            ))
            AND receiver_id = %s AND is_read = 0
        """, (conversation_id, conv['candidate_id'], conv['employer_id'], conv['employer_id'], conv['candidate_id'], curr_id))

    return jsonify({'success': True, 'message': 'Conversation marked as read'})


@app.route('/api/conversations/start', methods=['POST'])
def api_start_conversation():
    """Initiates or resolves a conversation with recipient."""
    if 'user_id' not in session and 'employer_id' not in session:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401

    is_employer = 'employer_id' in session and 'user_id' not in session
    data = request.get_json(silent=True) or {}
    recipient_id = data.get('recipient_id') or data.get('candidate_id') or data.get('employer_id')
    job_id = data.get('job_id')
    raw_msg = data.get('initial_message') or ''
    initial_message = sanitize_text(raw_msg).strip()

    if not recipient_id:
        return jsonify({'success': False, 'message': 'Recipient ID is required'}), 400

    try:
        recipient_id = int(recipient_id)
        if job_id: job_id = int(job_id)
    except (ValueError, TypeError):
        return jsonify({'success': False, 'message': 'Invalid ID format'}), 400

    if is_employer:
        cand_id = recipient_id
        emp_id = session['employer_id']
        with db_cursor() as cursor:
            cursor.execute("SELECT id, name FROM user WHERE id = %s", (cand_id,))
            if not cursor.fetchone():
                return jsonify({'success': False, 'message': 'Candidate not found'}), 404
        conv_id = get_or_create_conversation(cand_id, emp_id, job_id)
    else:
        cand_id = session['user_id']
        emp_id = recipient_id
        with db_cursor() as cursor:
            cursor.execute("SELECT id, company_name FROM employee WHERE id = %s", (emp_id,))
            if not cursor.fetchone():
                return jsonify({'success': False, 'message': 'Employer not found'}), 404
        conv_id = get_or_create_conversation(cand_id, emp_id, job_id)

    if initial_message:
        sender_role = 'employer' if is_employer else 'candidate'
        sender_id = emp_id if is_employer else cand_id
        receiver_id = cand_id if is_employer else emp_id
        sender_name = session.get('company_name') if is_employer else session.get('user_name') or 'User'

        with db_cursor() as cursor:
            cursor.execute("""
                INSERT INTO messages (conversation_id, sender_role, sender_id, receiver_id, content, sent_at, is_read)
                VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP, 0)
            """, (conv_id, sender_role, sender_id, receiver_id, initial_message))
            cursor.execute("UPDATE conversations SET last_message_at = CURRENT_TIMESTAMP WHERE id = %s", (conv_id,))

        preview = initial_message[:100] + ('...' if len(initial_message) > 100 else '')
        if is_employer:
            create_notification(
                user_id=receiver_id,
                notification_type='new_message',
                title=f"New Message from {sender_name} 💬",
                message=f"{sender_name}: {preview}",
                action_url='/candidate/messages'
            )
        else:
            create_notification(
                employer_id=receiver_id,
                notification_type='new_message',
                title=f"New Message from {sender_name} 💬",
                message=f"{sender_name}: {preview}",
                action_url='/recruiter/messages'
            )

    return jsonify({'success': True, 'conversation_id': conv_id})



def auto_close_expired_jobs():
    """
    Automatically closes active jobs whose application deadline has passed.
    Sets is_active = 0, status = 'Closed', closed_reason = 'deadline_passed'.
    """
    try:
        with db_cursor(dictionary=False) as cursor:
            cursor.execute("""
                UPDATE jobs
                SET is_active = 0, status = 'Closed', closed_reason = 'deadline_passed'
                WHERE is_active = 1
                  AND application_deadline IS NOT NULL
                  AND application_deadline < CURDATE()
            """)
            affected = cursor.rowcount if hasattr(cursor, 'rowcount') else 0
            if affected > 0:
                logger.info(f"Auto-closed {affected} expired job(s) due to passed deadline.")
        return affected
    except Exception as e:
        logger.error(f"Error in auto_close_expired_jobs: {e}")
        return 0


def init_scheduled_tasks():
    """Initializes APScheduler for automated background tasks like daily job auto-closing."""
    if app.config.get('TESTING') or os.getenv('FLASK_ENV') == 'testing':
        return None
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        scheduler = BackgroundScheduler(daemon=True)
        scheduler.add_job(
            auto_close_expired_jobs,
            'cron',
            hour=0,
            minute=0,
            id='auto_close_expired_jobs_daily',
            replace_existing=True
        )
        scheduler.start()
        logger.info("APScheduler initialized: daily expired jobs auto-close scheduled at 00:00.")
        return scheduler
    except Exception as e:
        logger.warning(f"Could not start APScheduler: {e}")
        return None


def check_smtp_at_startup():
    """Verify SMTP credentials and connectivity at startup, logging a warning if not working."""
    if os.getenv('SKIP_EMAIL_STARTUP_CHECK') == '1' or app.config.get('TESTING'):
        return True

    if not EMAIL_ADDRESS or not EMAIL_PASSWORD:
        logger.warning("OTP EMAIL SENDING IS NOT WORKING - EMAIL_ADDRESS or EMAIL_PASSWORD not configured in .env")
        return False

    smtp_host = os.getenv('SMTP_HOST', 'smtp.gmail.com')
    smtp_port_587 = int(os.getenv('SMTP_PORT_STARTTLS', '587'))
    smtp_port_465 = int(os.getenv('SMTP_PORT_SSL', '465'))
    smtp_timeout = int(os.getenv('SMTP_STARTUP_TIMEOUT', '5'))

    for port, use_ssl in [(smtp_port_587, False), (smtp_port_465, True)]:
        try:
            if use_ssl:
                with smtplib.SMTP_SSL(smtp_host, port, timeout=smtp_timeout) as smtp:
                    smtp.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            else:
                with smtplib.SMTP(smtp_host, port, timeout=smtp_timeout) as smtp:
                    smtp.ehlo()
                    smtp.starttls()
                    smtp.ehlo()
                    smtp.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            logger.info(f"SMTP service verified OK via {smtp_host}:{port}")
            return True
        except Exception:
            continue

    logger.warning("OTP EMAIL SENDING IS NOT WORKING - check Gmail App Password or SMTP ports")
    return False


if __name__ == '__main__':
    import sys
    for attempt in range(10):
        try:
            init_db()
            break
        except Exception as e:
            print(f"DB init failed (attempt {attempt+1}/10): {e}")
            time.sleep(5)
    else:
        raise RuntimeError("Database initialization failed after 10 attempts")

    check_smtp_at_startup()
    auto_close_expired_jobs()
    init_scheduled_tasks()

    if len(sys.argv) > 1 and sys.argv[1] == 'cron_send_job_alerts':
        result = send_job_alerts()
        print(f"Job alerts processed: sent={result['sent']}, skipped={result['skipped']}, errors={result['errors']}")
    else:
        debug_mode = os.getenv('FLASK_DEBUG', '0') == '1'
        if os.getenv('FLASK_ENV') == 'production' and debug_mode:
            logger.critical("FLASK_DEBUG=1 is strictly forbidden in production (FLASK_ENV=production). Forcing debug mode OFF.")
            debug_mode = False
        flask_host = os.getenv('FLASK_HOST', '127.0.0.1')
        app.run(host=flask_host, debug=debug_mode, port=5000)
