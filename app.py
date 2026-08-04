import os
import re
import json
import time
import random
import string
import smtplib
import logging
import contextlib
import io
from email.message import EmailMessage
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, send_from_directory
from flask_wtf.csrf import CSRFProtect, generate_csrf, CSRFError
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import mysql.connector
from mysql.connector import errorcode
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from pypdf import PdfReader
from docx import Document

# --- LOGGING (structured, no secrets logged) ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger('securehire')

load_dotenv()

app = Flask(__name__)

# --- FAIL LOUDLY: all secrets must come from the environment ---
FLASK_SECRET_KEY = os.getenv('FLASK_SECRET_KEY')
EMAIL_ADDRESS = os.getenv('EMAIL_ADDRESS')
EMAIL_PASSWORD = os.getenv('EMAIL_PASSWORD')
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
<<<<<<< ours
        raise RuntimeError(f"{_name} must be set in .env — no hardcoded fallback for security")
=======
        raise RuntimeError(f"{_name} must be set in .env — no static fallback for security")
>>>>>>> theirs
app.secret_key = FLASK_SECRET_KEY
app.permanent_session_lifetime = timedelta(days=1)

# --- SESSION COOKIE SECURITY ---
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
if os.getenv('FLASK_ENV') == 'production' or os.getenv('SESSION_COOKIE_SECURE', '0') == '1':
    app.config['SESSION_COOKIE_SECURE'] = True

# --- CSRF PROTECTION (Flask-WTF) ---
csrf = CSRFProtect(app)


@csrf.exempt
@app.route('/api/csrf_token', methods=['GET'])
def get_csrf_token():
    token = generate_csrf()
    return jsonify({'csrf_token': token})
<<<<<<< ours
=======

>>>>>>> theirs

# --- FLASK-LIMITER (global + per-route) ---
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["200 per minute"],
    storage_uri=os.getenv('RATELIMIT_STORAGE_URI', 'memory://'),
)

# --- FLASK-LIMITER (global + per-route) ---
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["200 per minute"],
    storage_uri=os.getenv('RATELIMIT_STORAGE_URI', 'memory://'),
)

# --- CONFIGURATION ---
UPLOAD_FOLDER = 'resumes'
ALLOWED_EXTENSIONS = {'txt', 'pdf', 'docx'}
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


def validate_password(password):
    """Min 8 chars, at least one letter and one number."""
    if not password or len(password) < 8:
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


def check_rate_limit(rate_key, action, limit=5, window_seconds=300):
    """DB-backed rate limiter keyed by (rate_key, action). Works across workers."""
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
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[-1].lower() in ALLOWED_EXTENSIONS


def validate_file_signature(stream, filename):
    """Validate file magic bytes match the claimed extension."""
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    stream.seek(0)
    header = stream.read(8)
    stream.seek(0)
    if ext == 'pdf':
        return header.startswith(b'%PDF')
    elif ext == 'docx':
        return header[:2] == b'PK'
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


def notify_user(user_id, message):
    with db_cursor() as cur:
        cur.execute("INSERT INTO notifications (user_id, message) VALUES (%s, %s)", (user_id, message))

# --- INITIALIZE DATABASE ---
def init_db():
    conn = mysql.connector.connect(user=DB_USER, password=DB_PASSWORD, host=DB_HOST)
    cursor = conn.cursor()
    cursor.execute("CREATE DATABASE IF NOT EXISTS dream_jobs0")
    cursor.execute("USE dream_jobs0")

    # --- RATE LIMIT TABLE (DB-backed, works across workers) ---
    cursor.execute("""
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
    cursor.execute("""
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
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS employee (
            id INT AUTO_INCREMENT PRIMARY KEY,
            company_name VARCHAR(100),
            mobile VARCHAR(20),
            email VARCHAR(100) UNIQUE,
            password VARCHAR(255)
        )
    """)

    # --- USER TABLE ---
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user (
            id INT AUTO_INCREMENT PRIMARY KEY,
            name VARCHAR(100),
            email VARCHAR(100) UNIQUE,
            password VARCHAR(255),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            mobile VARCHAR(20),
            is_verified BOOLEAN DEFAULT FALSE
        )
    """)

    # --- JOBS TABLE ---
    cursor.execute("""
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

    # --- APPLICATIONS TABLE (with FK + unique constraint) ---
    cursor.execute("""
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

    # --- SAVED JOBS TABLE (with FK) ---
    cursor.execute("""
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
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS job_categories (
            id INT AUTO_INCREMENT PRIMARY KEY,
            name VARCHAR(100) NOT NULL UNIQUE
        )
    """)

    # Insert default categories
    cursor.execute("INSERT IGNORE INTO job_categories (name) VALUES ('IT & Software'), ('Banking & Finance'), ('Healthcare'), ('Engineering'), ('Manufacturing'), ('Education'), ('Government'), ('Retail'), ('Marketing'), ('Other')")

    # --- NOTIFICATIONS TABLE ---
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT,
            message TEXT,
            is_read BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_notif_user (user_id)
        )
    """)

    # --- INDEXES (added separately so they're idempotent on existing DBs) ---
    _indexes = [
        ('jobs_title_idx', 'jobs', 'title'),
        ('jobs_location_idx', 'jobs', 'location'),
        ('jobs_category_idx', 'jobs', 'category'),
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

    # --- CANDIDATE PROFILE TABLE ---
    cursor.execute("""
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
            is_public BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES user(id) ON DELETE CASCADE
        )
    """)

    conn.commit()
    conn.close()

try:
    init_db()
except Exception as e:
    logger.error(f"Database initialization error: {e}")
<<<<<<< ours
=======

try:
    from sentence_transformers import SentenceTransformer
    _SENTENCE_MODEL = None
    def _get_sentence_model():
        global _SENTENCE_MODEL
        if _SENTENCE_MODEL is None:
            _SENTENCE_MODEL = SentenceTransformer('all-MiniLM-L6-v2')
        return _SENTENCE_MODEL
except ImportError:
    _SENTENCE_MODEL = None
    def _get_sentence_model(): return None
>>>>>>> theirs

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
                    jobs[i]['score'] = round(cosine_similarities[i] * 100, 2)
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
            jobs[i]['score'] = round(cosine_similarities[i] * 100, 2)
            scored_jobs.append(jobs[i])
    return scored_jobs

# --- ROUTES ---
@app.route('/')
def index(): return render_template('index.html')

@app.route('/employer_dashboard')
def employer_dashboard():
    if 'employer_id' not in session: return redirect(url_for('index'))
    return render_template('employer_dashboard.html', user_name=session.get('user_name'))

@app.route('/user_dashboard')
def user_dashboard():
    if 'user_id' not in session: return redirect(url_for('index'))
    return render_template('user_dashboard.html', user_name=session.get('user_name'))

@app.route('/user_settings')
def user_settings():
    if 'user_id' not in session: return redirect(url_for('index'))
    return render_template('user_settings.html', user_name=session.get('user_name'))

@app.route('/employer_settings')
def employer_settings():
    if 'employer_id' not in session: return redirect(url_for('index'))
    return render_template('employer_settings.html', user_name=session.get('user_name'))

@app.route('/logout')
def logout(): session.clear(); return redirect(url_for('index'))

# --- DOWNLOAD RESUME ---
@app.route('/download_resume/<filename>')
def download_resume(filename):
    if 'employer_id' not in session: return "Unauthorized", 401
    # Ensure the resume belongs to an application for a job this employer owns
    with db_cursor(dictionary=False) as cursor:
        cursor.execute("""
            SELECT 1 FROM applications a
            JOIN jobs j ON a.job_id = j.id
            WHERE a.resume_path = %s AND j.employer_id = %s
        """, (filename, session['employer_id']))
        if not cursor.fetchone():
            return "Forbidden", 403
    try:
        return send_from_directory(app.config['UPLOAD_FOLDER'], filename, as_attachment=True)
    except FileNotFoundError:
        return "File not found", 404

# --- CHECK SESSION ---
@app.route('/api/check_session')
def check_session():
    return jsonify({'logged_in': 'user_id' in session})

# --- AUTH APIs ---
def verify_otp(email, otp):
    """Verify OTP, reject expired OTPs, and clean up expired rows."""
    email = normalize_email(email)
    if not email or not otp:
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
    return bool(row) and row['otp'] == str(otp)


def check_otp_rate_limit(email, limit=3, window=60):
    """DB-backed rate limiter for OTP requests — works across workers."""
    return check_rate_limit(email, 'otp_request', limit=limit, window_seconds=window)


@app.route('/api/send_otp', methods=['POST'])
@limiter.limit("3 per minute")
def api_send_otp():
    data = request.json or {}
    email = normalize_email(data.get('email'))
    if not email:
        return jsonify({'success': False, 'message': 'Email required'})
    if not validate_email(email):
        return jsonify({'success': False, 'message': 'Invalid email format'})
    if not check_otp_rate_limit(email):
        return jsonify({'success': False, 'message': 'Too many OTP requests. Please wait a minute.'})
    otp = ''.join(random.choices(string.digits, k=6))
    otp_expiry = datetime.now() + timedelta(seconds=OTP_TTL_SECONDS)

    with db_cursor(dictionary=False) as cursor:
        cursor.execute("DELETE FROM otp_store WHERE email = %s", (email,))
        cursor.execute(
            "INSERT INTO otp_store (email, otp, expires_at) VALUES (%s, %s, %s)",
            (email, otp, otp_expiry)
        )

    try:
        msg = EmailMessage()
        msg.set_content(f"""Dream Jobs - Verification Code

Dear User,

Your One-Time Password (OTP) for verification is:

{otp}

This code is valid for the next 2 minutes. Please do not share this code with anyone for security reasons.

If you did not request this, please ignore this email.

Best regards,
Dream Jobs Team""")
        msg['Subject'] = "Your Verification Code - Dream Jobs"
        msg['From'] = EMAIL_ADDRESS
        msg['To'] = email

        last_error = None
        for port, use_ssl in [(587, False), (465, True)]:
            try:
                if use_ssl:
                    with smtplib.SMTP_SSL('smtp.gmail.com', port, timeout=10) as smtp:
                        smtp.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
                        smtp.send_message(msg)
                else:
                    with smtplib.SMTP('smtp.gmail.com', port, timeout=10) as smtp:
                        smtp.ehlo()
                        smtp.starttls()
                        smtp.ehlo()
                        smtp.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
                        smtp.send_message(msg)
                logger.info(f"OTP sent to {email}")
                return jsonify({'success': True, 'message': 'OTP Sent to Email'})
            except (smtplib.SMTPException, OSError) as e:
                last_error = e
                logger.warning(f"Email attempt failed on port {port}: {e}")
                continue

        logger.error(f"Email error (all ports failed for {email}): {last_error}")
        return jsonify({'success': False, 'message': 'Failed to send email via all SMTP ports. Port may be blocked or credentials invalid.'})
    except Exception as e:
        logger.error(f"Email error for {email}: {e}")
        return jsonify({'success': False, 'message': 'An unexpected error occurred while sending email.'})

@app.route('/api/user/register', methods=['POST'])
@limiter.limit("5 per minute")
def api_user_register():
    data = request.json or {}
    email = normalize_email(data.get('email'))
    otp = data.get('otp')
    name = data.get('name', '').strip() if data.get('name') else ''
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

    # Gate registration on a confirmed OTP
    if not verify_otp(email, otp):
        return jsonify({'success': False, 'message': 'Invalid or missing OTP. Please verify your email.'})

    with db_cursor() as cursor:
        cursor.execute("SELECT id FROM user WHERE email = %s", (email,))
        if cursor.fetchone():
            return jsonify({'success': False, 'message': 'Email already exists. Please login.'})

        hashed_pw = generate_password_hash(password)
        cursor.execute("INSERT INTO user (name, email, mobile, password, is_verified) VALUES (%s, %s, %s, %s, %s)",
                       (name, email, mobile, hashed_pw, True))
        user_id = cursor.lastrowid
        # Consume the OTP so it can't be reused
        cursor.execute("DELETE FROM otp_store WHERE email = %s", (email,))

    # Clear any stale session data, then set the new user session
    session.clear()
    session['user_id'] = user_id
    session['user_name'] = name
    logger.info(f"User registered: id={user_id}")
    return jsonify({'success': True, 'message': 'Account Created Successfully!', 'redirect': '/user_dashboard'})

@app.route('/api/user/login', methods=['POST'])
@limiter.limit(LOGIN_RATE_LIMIT)
def api_user_login():
    data = request.json or {}
    email = normalize_email(data.get('email', ''))
    password = data.get('password', '')

    if not email or not password:
        return jsonify({'success': False, 'message': 'Email and password are required'}), 400

    # DB-based rate limiting by email+IP
    client_ip = request.remote_addr or 'unknown'
    rate_key = f"{email}:{client_ip}"
    if not check_rate_limit(rate_key, 'login_attempt', limit=5, window_seconds=300):
        logger.warning(f"Login rate limit exceeded for {email} from {client_ip}")
        return jsonify({'success': False, 'message': 'Too many login attempts. Please try again in 5 minutes.'}), 429

    with db_cursor() as cursor:
        cursor.execute("SELECT id, name, email, password FROM user WHERE email = %s", (email,))
        user = cursor.fetchone()

    if not user:
        return jsonify({'success': False, 'message': 'Email not found. Please register.'})

    if check_password_hash(str(user['password']), password):
        session.clear()
        session['user_id'] = user['id']
        session['user_name'] = user['name']
        logger.info(f"User login: id={user['id']}")
        return jsonify({'success': True, 'message': 'Login Successful', 'redirect': '/user_dashboard'})
    return jsonify({'success': False, 'message': 'Wrong Password'})

@app.route('/api/employer/register', methods=['POST'])
@limiter.limit("5 per minute")
def api_employer_register():
    data = request.json or {}
    email = normalize_email(data.get('email'))
    name = data.get('name', '').strip() if data.get('name') else ''
    mobile = data.get('mobile', '').strip() if data.get('mobile') else ''
    password = data.get('password', '')
<<<<<<< ours

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

=======

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

>>>>>>> theirs
    with db_cursor() as cursor:
        cursor.execute("SELECT id FROM employee WHERE email = %s", (email,))
        if cursor.fetchone():
            return jsonify({'success': False, 'message': 'Email already exists. Please login.'})

        hashed_pw = generate_password_hash(password)
        cursor.execute("INSERT INTO employee (company_name, mobile, email, password) VALUES (%s, %s, %s, %s)",
                       (name, mobile, email, hashed_pw))
        emp_id = cursor.lastrowid

    # Auto Login: Set Session
    session.clear()
    session['employer_id'] = emp_id
    session['user_name'] = name
    logger.info(f"Employer registered: id={emp_id}")
    return jsonify({'success': True, 'message': 'Account Created Successfully!', 'redirect': '/employer_dashboard'})

@app.route('/api/employer/login', methods=['POST'])
@limiter.limit(LOGIN_RATE_LIMIT)
def api_employer_login():
    data = request.json or {}
    email = normalize_email(data.get('email', ''))
    password = data.get('password', '')

    if not email or not password:
        return jsonify({'success': False, 'message': 'Email and password are required'}), 400

    # DB-based rate limiting by email+IP
    client_ip = request.remote_addr or 'unknown'
    rate_key = f"{email}:{client_ip}"
    if not check_rate_limit(rate_key, 'login_attempt', limit=5, window_seconds=300):
        logger.warning(f"Login rate limit exceeded for {email} from {client_ip}")
        return jsonify({'success': False, 'message': 'Too many login attempts. Please try again in 5 minutes.'}), 429

    with db_cursor() as cursor:
        cursor.execute("SELECT id, company_name, email, password FROM employee WHERE email = %s", (email,))
        emp = cursor.fetchone()

    if not emp:
        return jsonify({'success': False, 'message': 'Email not found. Please register.'})

    if check_password_hash(str(emp['password']), password):
        session.clear()
        session['employer_id'] = emp['id']
        session['user_name'] = emp['company_name']
        logger.info(f"Employer login: id={emp['id']}")
        return jsonify({'success': True, 'message': 'Login Successful', 'redirect': '/employer_dashboard'})
    return jsonify({'success': False, 'message': 'Wrong Password'})

@app.route('/api/reset_password', methods=['POST'])
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
    with db_cursor() as cursor:
        cursor.execute("SELECT * FROM otp_store WHERE email = %s AND otp = %s ORDER BY created_at DESC LIMIT 1", (email, otp))
        entry = cursor.fetchone()
        if not entry:
            return jsonify({'success': False, 'message': 'Invalid OTP'})
        # Check expiry
        if entry.get('expires_at') and entry['expires_at'] < datetime.now():
            return jsonify({'success': False, 'message': 'OTP has expired'})
        hashed_pw = generate_password_hash(new_password)
        cursor.execute("UPDATE user SET password = %s WHERE email = %s", (hashed_pw, email))
        cursor.execute("DELETE FROM otp_store WHERE email = %s", (email,))
    # Invalidate all existing sessions for this user
    session.clear()
    logger.info(f"Password reset for {email}")
    return jsonify({'success': True, 'message': 'Password Reset Successful'})

# --- CORE APIs ---
@app.route('/api/post_job', methods=['POST'])
def api_post_job():
    if 'employer_id' not in session: return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    data = request.json or {}
    title = data.get('title', '').strip()
    if not title:
        return jsonify({'success': False, 'message': 'Job title is required'}), 400
    ok, err = validate_length(title, 255, 'Job title')
    if not ok:
        return jsonify({'success': False, 'message': err}), 400
    try:
        with db_cursor(dictionary=False) as cursor:
            cursor.execute("""
                INSERT INTO jobs (employer_id, title, description, location, salary, experience, skills,
                    category, company_name, job_type, work_mode, salary_min, salary_max,
                    openings, application_deadline, is_active)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (session['employer_id'], title, data.get('description'), data.get('location'),
                  data.get('salary'), data.get('experience'), data.get('skills'), data.get('category'),
                  session.get('user_name'), data.get('job_type', 'Full-time'), data.get('work_mode', 'Onsite'),
                  data.get('salary_min') or 0, data.get('salary_max') or 0,
                  data.get('openings') or 1,
                  data.get('application_deadline') or None,
                  data.get('is_active', True)))
        logger.info(f"Job posted: title={title}, employer_id={session['employer_id']}")
        return jsonify({'success': True, 'message': 'Job Posted'})
    except Exception as e:
        logger.error(f"Error posting job: {e}")
        return jsonify({'success': False, 'message': 'An error occurred while posting the job'}), 500

@app.route('/api/get_employer_jobs')
def api_get_employer_jobs():
    if 'employer_id' not in session: return jsonify({'success': False}), 401
    with db_cursor() as cursor:
        cursor.execute("SELECT * FROM jobs WHERE employer_id = %s ORDER BY id DESC", (session['employer_id'],))
        jobs = cursor.fetchall()
    for j in jobs:
        if j.get('created_at'): j['created_at'] = j['created_at'].strftime('%Y-%m-%d')
    return jsonify({'success': True, 'jobs': jobs})

@app.route('/api/delete_job/<int:job_id>', methods=['POST'])
def delete_job(job_id):
    if 'employer_id' not in session: return jsonify({'success': False}), 401
    with db_cursor(dictionary=False) as cursor:
        cursor.execute("DELETE FROM jobs WHERE id = %s AND employer_id = %s", (job_id, session['employer_id']))
    logger.info(f"Job deleted: id={job_id}, employer_id={session['employer_id']}")
    return jsonify({'success': True, 'message': 'Job Deleted'})

@app.route('/api/get_all_jobs')
def api_get_all_jobs():
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 10, type=int)
    offset = (page - 1) * per_page
    with db_cursor() as cursor:
        cursor.execute("SELECT COUNT(*) AS total FROM jobs")
        total = cursor.fetchone()['total']
        cursor.execute("SELECT * FROM jobs ORDER BY id DESC LIMIT %s OFFSET %s", (per_page, offset))
        jobs = cursor.fetchall()
    for j in jobs:
        if j.get('created_at'): j['created_at'] = j['created_at'].strftime('%Y-%m-%d')
    return jsonify({'success': True, 'jobs': jobs, 'total': total, 'page': page, 'per_page': per_page})

@app.route('/api/jobs/search', methods=['POST'])
def api_jobs_search():
    data = request.json or {}
    title = data.get('title', '')
    location = data.get('location', '')
    experience = data.get('experience', '')
    category = data.get('category', '')
    job_type = data.get('job_type', '')
    work_mode = data.get('work_mode', '')
    salary_min = data.get('salary_min')
    salary_max = data.get('salary_max')
    sort = data.get('sort', 'newest')
    page = data.get('page', 1)
    per_page = min(data.get('per_page', 10), 50)

    with db_cursor() as cursor:
        query = "SELECT * FROM jobs WHERE 1=1"
        params = []
        count_query = "SELECT COUNT(*) AS total FROM jobs WHERE 1=1"

        if title:
            query += " AND (title LIKE %s OR description LIKE %s OR skills LIKE %s)"
            count_query += " AND (title LIKE %s OR description LIKE %s OR skills LIKE %s)"
            params.extend([f'%{title}%', f'%{title}%', f'%{title}%'])
        if location:
            query += " AND location LIKE %s"
            count_query += " AND location LIKE %s"
            params.append(f'%{location}%')
        if experience:
            query += " AND experience = %s"
            count_query += " AND experience = %s"
            params.append(experience)
        if category:
            query += " AND category = %s"
            count_query += " AND category = %s"
            params.append(category)
        if job_type:
            query += " AND job_type = %s"
            count_query += " AND job_type = %s"
            params.append(job_type)
        if work_mode:
            query += " AND work_mode = %s"
            count_query += " AND work_mode = %s"
            params.append(work_mode)
        if salary_min:
            query += " AND salary_max >= %s"
            count_query += " AND salary_max >= %s"
            params.append(salary_min)
        if salary_max:
            query += " AND salary_min <= %s"
            count_query += " AND salary_min <= %s"
            params.append(salary_max)

        query += " AND is_active = 1"
        count_query += " AND is_active = 1"

        if sort == 'salary_high_to_low':
            query += " ORDER BY salary_max DESC, id DESC"
        elif sort == 'salary_low_to_high':
            query += " ORDER BY salary_min ASC, id DESC"
        else:
            query += " ORDER BY id DESC"

        offset = (page - 1) * per_page
        cursor.execute(count_query, params)
        total = cursor.fetchone()['total']

        query += " LIMIT %s OFFSET %s"
        params.extend([per_page, offset])
        cursor.execute(query, params)
        jobs = cursor.fetchall()

    if title or category:
        jobs = get_nlp_search_results(jobs, f"{title} {category}")
    for j in jobs:
        if j.get('created_at'): j['created_at'] = j['created_at'].strftime('%Y-%m-%d')
    return jsonify({'success': True, 'jobs': jobs, 'total': total, 'page': page, 'per_page': per_page})

# --- APPLY LOGIC ---
@app.route('/api/user/applied_jobs')
def get_applied_jobs():
    if 'user_id' not in session: return jsonify({'success': False}), 401
    with db_cursor(dictionary=False) as cursor:
        cursor.execute("SELECT job_id FROM applications WHERE user_id = %s", (session['user_id'],))
        ids = [str(row[0]) for row in cursor.fetchall()]
    return jsonify({'success': True, 'applied_ids': ids})

@app.route('/api/apply_job', methods=['POST'])
def api_apply_job():
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Please Login to Apply'}), 401

    data = request.form
    job_id = data.get('job_id')
    if not job_id:
        return jsonify({'success': False, 'message': 'Job ID is required'}), 400

    # Check job deadline and active status
    with db_cursor() as cursor:
        cursor.execute("SELECT application_deadline, is_active FROM jobs WHERE id = %s", (job_id,))
        job_row = cursor.fetchone()
    if not job_row:
        return jsonify({'success': False, 'message': 'Job not found'}), 404
    if not job_row['is_active']:
        return jsonify({'success': False, 'message': 'This job posting is no longer active'}), 400
    if job_row['application_deadline']:
        try:
            deadline = datetime.strptime(str(job_row['application_deadline']), '%Y-%m-%d').date()
            if datetime.now().date() > deadline:
                return jsonify({'success': False, 'message': 'The application deadline has passed'}), 400
        except (ValueError, TypeError):
            pass

    # RESUME VALIDATION (extension + size + magic bytes)
    file = request.files.get('resume')
    resume_filename = None
    if file and file.filename:
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
        resume_filename = f"{session['user_id']}_{datetime.now().strftime('%Y%m%d%H%M%S')}_{filename}"
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], resume_filename))

    # INSERT APPLICATION (catch duplicate via UNIQUE constraint)
    try:
        with db_cursor(dictionary=False) as cursor:
            cursor.execute("""
                INSERT INTO applications (
                    job_id, user_id, user_name, user_email, user_mobile,
                    qualification, college_name, year_of_passing,
                    experience_level, years_experience, previous_company,
                    skills, resume_path, cover_letter,
                    current_location, preferred_location, expected_salary
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (
                job_id, session['user_id'], data.get('name'), data.get('email'), data.get('mobile'),
                data.get('qualification'), data.get('college'), data.get('yop'),
                data.get('exp_level'), data.get('yoe'), data.get('prev_company'),
                data.get('skills'), resume_filename, data.get('cover'),
                data.get('curr_loc'), data.get('pref_loc'), data.get('salary')
            ))
    except mysql.connector.IntegrityError as e:
        if e.errno == errorcode.ER_DUP_ENTRY:
            return jsonify({'success': False, 'message': 'You have already applied for this job.'})
        logger.error(f"IntegrityError in apply_job: {e}")
        return jsonify({'success': False, 'message': 'An error occurred while submitting your application.'}), 500
    except Exception as e:
        # Also check pre-insert (defense in depth)
        with db_cursor(dictionary=False) as cursor:
            cursor.execute(
                "SELECT id FROM applications WHERE job_id = %s AND user_id = %s",
                (job_id, session['user_id'])
            )
            if cursor.fetchone():
                return jsonify({'success': False, 'message': 'You have already applied for this job.'})
        logger.error(f"Error in apply_job: {e}")
        return jsonify({'success': False, 'message': 'An error occurred while submitting your application.'}), 500

    logger.info(f"Application submitted: user_id={session['user_id']}, job_id={job_id}")
    return jsonify({'success': True, 'message': 'Application Submitted'})

@app.route('/api/get_applicants/<int:job_id>')
def get_applicants(job_id):
    if 'employer_id' not in session: return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    with db_cursor() as cursor:
        cursor.execute("SELECT employer_id FROM jobs WHERE id = %s", (job_id,))
        job = cursor.fetchone()
        if not job or job['employer_id'] != session['employer_id']:
            return jsonify({'success': False, 'message': 'Unauthorized'}), 403
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 50, type=int)
        offset = (page - 1) * per_page
        cursor.execute("SELECT COUNT(*) AS total FROM applications WHERE job_id = %s", (job_id,))
        total = cursor.fetchone()['total']
        cursor.execute("SELECT * FROM applications WHERE job_id = %s ORDER BY id DESC LIMIT %s OFFSET %s", (job_id, per_page, offset))
        apps = cursor.fetchall()
    return jsonify({'success': True, 'applicants': apps, 'total': total, 'page': page, 'per_page': per_page})

def _set_candidate_status(app_id, new_status):
    """Ownership-checked status transition + user notification. Returns (ok, message, http)."""
    status_messages = {
        'Shortlisted': "Great news! Your application for '{title}' at {company} has been shortlisted. We will be in touch soon.",
        'Interview': "Congratulations! You have been invited for an interview for '{title}' at {company}. The employer will contact you with next steps.",
        'Selected': "Congratulations! You have been selected for the position of '{title}' at {company}. The employer will contact you shortly.",
        'Rejected': "We regret to inform you that your application for '{title}' at {company} was not selected this time. We wish you the best in your future endeavors.",
        'Applied': "Your application for '{title}' at {company} has been received.",
    }
    with db_cursor() as cursor:
        cursor.execute("""
            SELECT a.id, a.user_id, a.job_id, a.status, j.employer_id, j.title, j.company_name
            FROM applications a JOIN jobs j ON a.job_id = j.id
            WHERE a.id = %s AND j.employer_id = %s
        """, (app_id, session['employer_id']))
        app = cursor.fetchone()
        if not app:
            return False, 'Unauthorized or application not found', 403
        if app['status'] == new_status:
            return True, 'No change', 200
        cursor.execute("UPDATE applications SET status = %s WHERE id = %s", (new_status, app_id))
        msg = status_messages.get(new_status, status_messages['Applied']).format(
            title=app['title'], company=app['company_name'])
        cursor.execute("INSERT INTO notifications (user_id, message) VALUES (%s, %s)", (app['user_id'], msg))
    return True, f"Candidate marked as {new_status}", 200


@app.route('/api/select_candidate', methods=['POST'])
def select_candidate():
    if 'employer_id' not in session: return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    data = request.json or {}
    ok, msg, http = _set_candidate_status(data.get('app_id'), 'Selected')
    return jsonify({'success': ok, 'message': msg}), http


@app.route('/api/update_candidate_status', methods=['POST'])
def update_candidate_status():
    if 'employer_id' not in session: return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    data = request.json or {}
    new_status = data.get('status')
    if new_status not in ('Applied', 'Shortlisted', 'Interview', 'Selected', 'Rejected'):
        return jsonify({'success': False, 'message': 'Invalid status'}), 400
    ok, msg, http = _set_candidate_status(data.get('app_id'), new_status)
    return jsonify({'success': ok, 'message': msg}), http

# --- NOTIFICATION APIs ---
@app.route('/api/get_user_notifications')
def get_user_notifications():
    if 'user_id' not in session: return jsonify({'success': False}), 401
    with db_cursor() as cursor:
        cursor.execute("SELECT id, message, is_read, created_at FROM notifications WHERE user_id = %s ORDER BY created_at DESC LIMIT 10", (session['user_id'],))
        notifs = cursor.fetchall()
    for n in notifs:
        if n.get('created_at'): n['created_at'] = n['created_at'].isoformat()
    return jsonify({'success': True, 'notifications': notifs})


@app.route('/api/mark_notifications_read', methods=['POST'])
def mark_notifications_read():
    if 'user_id' not in session: return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    with db_cursor(dictionary=False) as cursor:
        cursor.execute("UPDATE notifications SET is_read = 1 WHERE user_id = %s AND is_read = 0", (session['user_id'],))
    return jsonify({'success': True, 'message': 'Notifications marked as read'})

@app.route('/api/get_unread_count')
def get_unread_count():
    if 'user_id' not in session: return jsonify({'count': 0})
    with db_cursor(dictionary=False) as cursor:
        cursor.execute("SELECT COUNT(*) FROM notifications WHERE user_id = %s AND is_read = 0", (session['user_id'],))
        count = cursor.fetchone()[0]
    return jsonify({'count': count})

# --- SETTINGS & RESUME APIs ---
@app.route('/api/get_user_profile')
def get_user_profile():
    if 'user_id' not in session: return jsonify({'success': False}), 401
    with db_cursor() as cursor:
        cursor.execute("SELECT id, name, email, mobile FROM user WHERE id = %s", (session['user_id'],))
        user = cursor.fetchone()
    return jsonify({'success': True, 'user': user})

@app.route('/api/update_user_profile', methods=['POST'])
def update_user_profile():
    if 'user_id' not in session: return jsonify({'success': False}), 401
    data = request.json or {}
    name = data.get('name', '').strip() if data.get('name') else ''
    mobile = data.get('mobile', '').strip() if data.get('mobile') else ''
    if not name:
        return jsonify({'success': False, 'message': 'Name is required'}), 400
    ok, err = validate_length(name, 100, 'Name')
    if not ok:
        return jsonify({'success': False, 'message': err}), 400
    if not validate_mobile(mobile):
        return jsonify({'success': False, 'message': 'Invalid mobile number'}), 400
    with db_cursor(dictionary=False) as cursor:
        cursor.execute("UPDATE user SET name=%s, mobile=%s WHERE id=%s", (name, mobile, session['user_id']))
    return jsonify({'success': True, 'message': 'Profile Updated'})

@app.route('/api/change_user_password', methods=['POST'])
def change_user_password():
    if 'user_id' not in session: return jsonify({'success': False}), 401
    data = request.json or {}
    old_password = data.get('old_password', '')
    new_password = data.get('new_password', '')
    if not old_password or not new_password:
        return jsonify({'success': False, 'message': 'Old and new passwords are required'}), 400
    if not validate_password(new_password):
        return jsonify({'success': False, 'message': 'Password must be at least 8 characters with at least one letter and one number'}), 400
    with db_cursor() as cursor:
        cursor.execute("SELECT password FROM user WHERE id = %s", (session['user_id'],))
        user = cursor.fetchone()
        if not user or not check_password_hash(str(user['password']), old_password):
            return jsonify({'success': False, 'message': 'Incorrect Old Password'})
        new_hash = generate_password_hash(new_password)
        cursor.execute("UPDATE user SET password = %s WHERE id = %s", (new_hash, session['user_id']))
    # Invalidate all existing sessions for this user after password change
    session.clear()
    logger.info("Password changed for user")
    return jsonify({'success': True, 'message': 'Password Changed Successfully!'})

@app.route('/api/upload_resume', methods=['POST'])
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
    content = extract_text(io.BytesIO(file.read()), file.filename)
    skills = ['python', 'java', 'sql', 'html', 'css', 'javascript', 'flask', 'django', 'react', 'c++', 'management', 'marketing', 'sales']
    found = [s for s in skills if re.search(r'\b' + s + r'\b', content.lower())]

    with db_cursor() as cursor:
        cursor.execute("SELECT * FROM jobs")
        jobs = cursor.fetchall()

    ranked = []
    for job in jobs:
        if job['skills']:
            job_skills = [s.strip().lower() for s in job['skills'].split(',')]
            score = int(len(set(found) & set(job_skills)) / len(job_skills) * 100)
            if score > 0: ranked.append({**job, 'score': score})

    ranked.sort(key=lambda x: x['score'], reverse=True)
    return jsonify({'success': True, 'jobs': ranked, 'skills': found})

# --- SAVED JOBS APIs ---
@app.route('/api/save_job', methods=['POST'])
def api_save_job():
    if 'user_id' not in session: return jsonify({'success': False, 'message': 'Login required'}), 401
    data = request.json or {}
    job_id = data.get('job_id')
    if not job_id:
        return jsonify({'success': False, 'message': 'Job ID is required'}), 400
    with db_cursor(dictionary=False) as cursor:
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
    app_id = data.get('app_id')
    if not app_id:
        return jsonify({'success': False, 'message': 'Application ID is required'}), 400
    with db_cursor(dictionary=False) as cursor:
        cursor.execute("DELETE FROM applications WHERE id = %s AND user_id = %s", (app_id, session['user_id']))
    return jsonify({'success': True, 'message': 'Application withdrawn'})

# --- EDIT JOB (employer) ---
@app.route('/api/edit_job/<int:job_id>', methods=['POST'])
def edit_job(job_id):
    if 'employer_id' not in session: return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    data = request.json or {}
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
              data.get('salary_min') or 0, data.get('salary_max') or 0,
              data.get('openings') or 1,
              data.get('application_deadline') or None,
              data.get('is_active', True),
              job_id, session['employer_id']))
    return jsonify({'success': True, 'message': 'Job Updated'})

@app.route('/api/get_saved_jobs')
def api_get_saved_jobs():
    if 'user_id' not in session: return jsonify({'success': False}), 401
    with db_cursor() as cursor:
        cursor.execute("""
            SELECT j.* FROM jobs j
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
@app.route('/api/get_categories')
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
            SELECT a.id, a.status, a.created_at, j.id AS job_id, j.title, j.company_name, j.location
            FROM applications a
            INNER JOIN jobs j ON a.job_id = j.id
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
def api_jobs_paginated():
    page = request.args.get('page', 1, type=int)
    per_page = 10
    offset = (page - 1) * per_page
    with db_cursor() as cursor:
        cursor.execute("SELECT COUNT(*) as total FROM jobs")
        total = cursor.fetchone()['total']
        cursor.execute("SELECT * FROM jobs ORDER BY id DESC LIMIT %s OFFSET %s", (per_page, offset))
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
                SUM(CASE WHEN a.status='Selected' THEN 1 ELSE 0 END) AS selected,
                SUM(CASE WHEN a.status='Rejected' THEN 1 ELSE 0 END) AS rejected,
                SUM(CASE WHEN a.status='Interview' THEN 1 ELSE 0 END) AS interviews,
                SUM(CASE WHEN a.status='Shortlisted' THEN 1 ELSE 0 END) AS shortlisted
            FROM applications a JOIN jobs j ON a.job_id = j.id
            WHERE j.employer_id = %s
        """, (emp_id,))
        totals = cursor.fetchone()
        cursor.execute("""
            SELECT j.id, j.title, j.category,
                COUNT(a.id) AS total_applicants,
                SUM(CASE WHEN a.status='Selected' THEN 1 ELSE 0 END) AS selected,
                SUM(CASE WHEN a.status='Interview' THEN 1 ELSE 0 END) AS interviews,
                SUM(CASE WHEN a.status='Shortlisted' THEN 1 ELSE 0 END) AS shortlisted,
                SUM(CASE WHEN a.status='Rejected' THEN 1 ELSE 0 END) AS rejected
            FROM jobs j LEFT JOIN applications a ON j.id = a.job_id
            WHERE j.employer_id = %s
            GROUP BY j.id
            ORDER BY total_applicants DESC
        """, (emp_id,))
        per_job = cursor.fetchall()
    return jsonify({'success': True, 'job_count': job_count, 'totals': totals, 'per_job': per_job})

# --- EMPLOYER PROFILE API ---
@app.route('/api/employer_profile')
def api_employer_profile():
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
    return jsonify({'success': True, 'message': 'Profile Updated'})

@app.route('/api/change_employer_password', methods=['POST'])
def api_change_employer_password():
    if 'employer_id' not in session: return jsonify({'success': False}), 401
    data = request.json or {}
    old_password = data.get('old_password', '')
    new_password = data.get('new_password', '')
    if not old_password or not new_password:
        return jsonify({'success': False, 'message': 'Old and new passwords are required'}), 400
    if not validate_password(new_password):
        return jsonify({'success': False, 'message': 'Password must be at least 8 characters with at least one letter and one number'}), 400
    with db_cursor() as cursor:
        cursor.execute("SELECT password FROM employee WHERE id = %s", (session['employer_id'],))
        emp = cursor.fetchone()
        if not emp or not check_password_hash(str(emp['password']), old_password):
            return jsonify({'success': False, 'message': 'Incorrect Old Password'})
        new_hash = generate_password_hash(new_password)
        cursor.execute("UPDATE employee SET password = %s WHERE id = %s", (new_hash, session['employer_id']))
    session.clear()
    logger.info("Password changed for employer")
    return jsonify({'success': True, 'message': 'Password Changed'})


# --- CANDIDATE PROFILE ---
def compute_profile_completeness(profile):
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
            UPDATE candidate_profile SET
                headline=%s, summary=%s, skills=%s,
                experience=%s, education=%s,
                linkedin_url=%s, github_url=%s, portfolio_url=%s
            WHERE user_id = %s
        """, (headline, summary, skills, experience, education, linkedin, github, portfolio, session['user_id']))
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


@app.route('/candidate/<int:candidate_id>')
def public_candidate_profile(candidate_id):
    with db_cursor() as cursor:
        cursor.execute("SELECT u.id, u.name, u.email FROM user u WHERE u.id = %s", (candidate_id,))
        user = cursor.fetchone()
        if not user:
            return "Candidate not found", 404
        cursor.execute("SELECT * FROM candidate_profile WHERE user_id = %s AND is_public = 1", (candidate_id,))
        profile = cursor.fetchone()
        if not profile:
            return "Profile is private", 404
    completeness = compute_profile_completeness(profile) if profile else 0
    if profile:
        if profile.get('experience'): profile['experience'] = json.loads(profile['experience'])
        if profile.get('education'): profile['education'] = json.loads(profile['education'])
    return render_template('candidate_profile.html', user=user, profile=profile, completeness=completeness)


@app.route('/api/candidate/<int:candidate_id>/public')
def api_candidate_public(candidate_id):
    with db_cursor() as cursor:
        cursor.execute("SELECT u.id, u.name FROM user u WHERE u.id = %s", (candidate_id,))
        user = cursor.fetchone()
        if not user:
            return jsonify({'success': False, 'message': 'Candidate not found'}), 404
        cursor.execute("SELECT * FROM candidate_profile WHERE user_id = %s AND is_public = 1", (candidate_id,))
        profile = cursor.fetchone()
        if not profile:
            return jsonify({'success': False, 'message': 'Profile is private'}), 404
    completeness = compute_profile_completeness(profile) if profile else 0
    if profile:
        if profile.get('experience'): profile['experience'] = json.loads(profile['experience'])
        if profile.get('education'): profile['education'] = json.loads(profile['education'])
        profile.pop('profile_photo', None)  # Don't expose file path via API
    return jsonify({'success': True, 'user': user, 'profile': profile, 'completeness': completeness})


@app.route('/api/candidate/profile/photo', methods=['POST'])
def api_upload_profile_photo():
    if 'user_id' not in session: return jsonify({'success': False}), 401
    if 'photo' not in request.files:
        return jsonify({'success': False, 'message': 'No file uploaded'}), 400
    file = request.files['photo']
    if not file or not file.filename:
        return jsonify({'success': False, 'message': 'No file selected'}), 400
    if not allowed_file(file.filename):
        return jsonify({'success': False, 'message': 'Invalid file type. Allowed: txt, pdf, docx.'}), 400
    file.seek(0, os.SEEK_END)
    if file.tell() > MAX_UPLOAD_BYTES:
        return jsonify({'success': False, 'message': f'File too large (max {MAX_UPLOAD_MB}MB)'}), 400
    file.seek(0)
    if not validate_file_signature(file, file.filename):
        return jsonify({'success': False, 'message': 'File content does not match its extension'}), 400
    file.seek(0)
    # Save to static/uploads with unique name
    ext = os.path.splitext(file.filename)[1].lower()
    filename = f"user_{session['user_id']}_profile{ext}"
    upload_dir = os.path.join(app.root_path, 'static', 'uploads')
    os.makedirs(upload_dir, exist_ok=True)
    path = os.path.join(upload_dir, filename)
    file.save(path)
    with db_cursor(dictionary=False) as cursor:
        cursor.execute("UPDATE candidate_profile SET profile_photo = %s WHERE user_id = %s",
                       (filename, session['user_id']))
    return jsonify({'success': True, 'message': 'Photo uploaded', 'filename': filename})


# --- ERROR HANDLERS ---
@app.errorhandler(CSRFError)
def handle_csrf_error(e):
    logger.warning(f"CSRF validation failed: {e}")
    return jsonify({'success': False, 'message': 'CSRF token missing or invalid'}), 400


@app.errorhandler(413)
def request_entity_too_large(e):
    return jsonify({'success': False, 'message': 'File upload too large.'}), 413


@app.errorhandler(429)
def ratelimit_handler(e):
    return jsonify({'success': False, 'message': 'Rate limit exceeded. Please try again later.'}), 429


@app.errorhandler(400)
def bad_request_handler(e):
    return jsonify({'success': False, 'message': 'Bad request.'}), 400


if __name__ == '__main__':
    # Debug only when explicitly enabled via FLASK_DEBUG=1 (default off for safety)
    debug_mode = os.getenv('FLASK_DEBUG', '0') == '1'
    app.run(debug=debug_mode, port=5000)
