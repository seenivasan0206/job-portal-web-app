import os
import re
import time
import random
import string
import smtplib
import contextlib
import io
from email.message import EmailMessage
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, send_from_directory
import mysql.connector
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from pypdf import PdfReader
from docx import Document

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'dev-only-insecure-secret-change-me')
app.permanent_session_lifetime = timedelta(days=1)

# --- EMAIL CONFIGURATION (from env) ---
EMAIL_ADDRESS = os.getenv('EMAIL_ADDRESS', 'ccubetech00@gmail.com')
EMAIL_PASSWORD = os.getenv('EMAIL_PASSWORD', 'hzpn ljhy llle eyob')


# --- CONFIGURATION ---
UPLOAD_FOLDER = 'resumes'
ALLOWED_EXTENSIONS = {'txt', 'pdf', 'doc', 'docx'}
MAX_UPLOAD_MB = int(os.getenv('MAX_UPLOAD_MB', '5'))
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# --- DATABASE CONFIGURATION (from env) ---
db_config = {
    'user': os.getenv('DB_USER', 'root'),
    'password': os.getenv('DB_PASSWORD', 'mysql'),
    'host': os.getenv('DB_HOST', 'localhost'),
    'database': os.getenv('DB_NAME', 'dream_jobs0')
}

# In-memory OTP rate limit: email -> list of request timestamps (rolling 60s window)
otp_rate_log = {}


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
        print(f"Text extraction error ({ext}): {e}")
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
    conn = mysql.connector.connect(user='root', password='mysql', host='localhost')
    cursor = conn.cursor()
    cursor.execute("CREATE DATABASE IF NOT EXISTS dream_jobs0")
    cursor.execute("USE dream_jobs0")
    
    # Employee Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS employee (
            id INT AUTO_INCREMENT PRIMARY KEY,
            company_name VARCHAR(100),
            mobile VARCHAR(20),
            email VARCHAR(100) UNIQUE,
            password VARCHAR(255)
        )
    """)
    
    # User Table
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
    
    # Jobs Table
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
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (employer_id) REFERENCES employee(id)
        )
    """)
    # Add category column for existing databases (safe no-op if present)
    try:
        cursor.execute("ALTER TABLE jobs ADD COLUMN category VARCHAR(100) DEFAULT NULL")
    except Exception:
        pass
    
    # Applications Table
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
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
# --- SAVED JOBS TABLE ---
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS saved_jobs (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT NOT NULL,
            job_id INT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY unique_save (user_id, job_id)
        )
    """)
    
    # --- JOB CATEGORY TABLE ---
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS job_categories (
            id INT AUTO_INCREMENT PRIMARY KEY,
            name VARCHAR(100) NOT NULL UNIQUE
        )
    """)
    
    # Insert default categories
    cursor.execute("INSERT IGNORE INTO job_categories (name) VALUES ('IT & Software'), ('Banking & Finance'), ('Healthcare'), ('Engineering'), ('Manufacturing'), ('Education'), ('Government'), ('Retail'), ('Marketing'), ('Other')")
    
    cursor.execute("CREATE TABLE IF NOT EXISTS notifications (id INT AUTO_INCREMENT PRIMARY KEY, user_id INT, message TEXT, is_read BOOLEAN DEFAULT FALSE, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
    cursor.execute("CREATE TABLE IF NOT EXISTS otp_store (id INT AUTO_INCREMENT PRIMARY KEY, email VARCHAR(100), otp VARCHAR(6), created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
    
    conn.commit()
    conn.close()

try: init_db()
except Exception as e: print(f"Database Initialization Error: {e}")

# --- NLP SEARCH LOGIC ---
def get_nlp_search_results(jobs, query):
    if not jobs: return []
    corpus = [f"{j['title']} {j['skills']} {j['description']}" for j in jobs]
    corpus.append(query)
    vectorizer = TfidfVectorizer(stop_words='english')
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
    if not email or not otp:
        return False
    with db_cursor() as cur:
        cur.execute("SELECT otp FROM otp_store WHERE email = %s ORDER BY created_at DESC LIMIT 1", (email,))
        row = cur.fetchone()
    return bool(row) and row['otp'] == str(otp)


def check_otp_rate_limit(email, limit=3, window=60):
    now = time.time()
    times = otp_rate_log.get(email, [])
    times = [t for t in times if now - t < window]
    if len(times) >= limit:
        return False
    times.append(now)
    otp_rate_log[email] = times
    return True


@app.route('/api/send_otp', methods=['POST'])
def api_send_otp():
    data = request.json
    email = data.get('email')
    if not email:
        return jsonify({'success': False, 'message': 'Email required'})
    if not check_otp_rate_limit(email):
        return jsonify({'success': False, 'message': 'Too many OTP requests. Please wait a minute.'})
    otp = ''.join(random.choices(string.digits, k=6))
    
    with db_cursor(dictionary=False) as cursor:
        cursor.execute("DELETE FROM otp_store WHERE email = %s", (email,))
        cursor.execute("INSERT INTO otp_store (email, otp) VALUES (%s, %s)", (email, otp))
    
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
                return jsonify({'success': True, 'message': 'OTP Sent to Email'})
            except (smtplib.SMTPException, OSError) as e:
                last_error = e
                print(f"Email attempt failed on port {port}: {e}")
                continue

        print(f"Email Error (all ports failed): {last_error}")
        return jsonify({'success': False, 'message': 'Failed to send email via all SMTP ports. Port may be blocked or credentials invalid.'})
    except Exception as e:
        print(f"Email Error: {e}")
        return jsonify({'success': False, 'message': 'An unexpected error occurred while sending email.'})

@app.route('/api/user/register', methods=['POST'])
def api_user_register():
    data = request.json
    email = data.get('email')
    otp = data.get('otp')

    # Gate registration on a confirmed OTP
    if not verify_otp(email, otp):
        return jsonify({'success': False, 'message': 'Invalid or missing OTP. Please verify your email.'})

    with db_cursor() as cursor:
        cursor.execute("SELECT id FROM user WHERE email = %s", (email,))
        if cursor.fetchone():
            return jsonify({'success': False, 'message': 'Email already exists. Please login.'})

        hashed_pw = generate_password_hash(data['password'])
        cursor.execute("INSERT INTO user (name, email, mobile, password, is_verified) VALUES (%s, %s, %s, %s, %s)",
                       (data['name'], email, data['mobile'], hashed_pw, True))
        user_id = cursor.lastrowid
        # Consume the OTP so it can't be reused
        cursor.execute("DELETE FROM otp_store WHERE email = %s", (email,))

    session['user_id'] = user_id
    session['user_name'] = data['name']
    return jsonify({'success': True, 'message': 'Account Created Successfully!', 'redirect': '/user_dashboard'})

@app.route('/api/user/login', methods=['POST'])
def api_user_login():
    data = request.json
    email = data.get('email', '').strip()
    password = data.get('password', '')
    
    if not email or not password:
        return jsonify({'success': False, 'message': 'Email and password are required'})

    with db_cursor() as cursor:
        cursor.execute("SELECT id, name, email, password FROM user WHERE email = %s", (email,))
        user = cursor.fetchone()

    if not user:
        return jsonify({'success': False, 'message': 'Email not found. Please register.'})

    if check_password_hash(str(user['password']), password):
        session['user_id'] = user['id']
        session['user_name'] = user['name']
        return jsonify({'success': True, 'message': 'Login Successful', 'redirect': '/user_dashboard'})
    return jsonify({'success': False, 'message': 'Wrong Password'})

@app.route('/api/employer/register', methods=['POST'])
def api_employer_register():
    data = request.json
    with db_cursor() as cursor:
        email = data['email'].strip().lower()

        # 1. Check if email already exists
        cursor.execute("SELECT id FROM employee WHERE email = %s", (email,))
        if cursor.fetchone():
            return jsonify({'success': False, 'message': 'Email already exists. Please login.'})

        # 2. Register Employer
        hashed_pw = generate_password_hash(data['password'])
        cursor.execute("INSERT INTO employee (company_name, mobile, email, password) VALUES (%s, %s, %s, %s)",
                       (data['name'], data['mobile'], email, hashed_pw))
        emp_id = cursor.lastrowid

    # 3. Auto Login: Set Session
    session['employer_id'] = emp_id
    session['user_name'] = data['name']
    return jsonify({'success': True, 'message': 'Account Created Successfully!', 'redirect': '/employer_dashboard'})

@app.route('/api/employer/login', methods=['POST'])
def api_employer_login():
    data = request.json
    email = data.get('email', '').strip().lower()
    password = data.get('password', '')
    
    if not email or not password:
        return jsonify({'success': False, 'message': 'Email and password are required'})

    with db_cursor() as cursor:
        cursor.execute("SELECT id, company_name, email, password FROM employee WHERE email = %s", (email,))
        emp = cursor.fetchone()

    if not emp:
        return jsonify({'success': False, 'message': 'Email not found. Please register.'})

    if check_password_hash(str(emp['password']), password):
        session['employer_id'] = emp['id']
        session['user_name'] = emp['company_name']
        return jsonify({'success': True, 'message': 'Login Successful', 'redirect': '/employer_dashboard'})
    return jsonify({'success': False, 'message': 'Wrong Password'})

@app.route('/api/reset_password', methods=['POST'])
def api_reset_password():
    data = request.json
    email = data.get('email')
    otp = data.get('otp')
    new_password = data.get('password')
    if not all([email, otp, new_password]): return jsonify({'success': False, 'message': 'Missing fields'})
    with db_cursor() as cursor:
        cursor.execute("SELECT * FROM otp_store WHERE email = %s AND otp = %s ORDER BY created_at DESC LIMIT 1", (email, otp))
        entry = cursor.fetchone()
        if not entry: return jsonify({'success': False, 'message': 'Invalid OTP'})
        hashed_pw = generate_password_hash(new_password)
        cursor.execute("UPDATE user SET password = %s WHERE email = %s", (hashed_pw, email))
        cursor.execute("DELETE FROM otp_store WHERE email = %s", (email,))
    return jsonify({'success': True, 'message': 'Password Reset Successful'})

# --- CORE APIs ---
@app.route('/api/post_job', methods=['POST'])
def api_post_job():
    if 'employer_id' not in session: return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    data = request.json
    try:
        with db_cursor(dictionary=False) as cursor:
            cursor.execute("""
                INSERT INTO jobs (employer_id, title, description, location, salary, experience, skills, category, company_name)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (session['employer_id'], data['title'], data['description'], data['location'],
                  data['salary'], data['experience'], data['skills'], data.get('category'), session['user_name']))
        return jsonify({'success': True, 'message': 'Job Posted'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

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
    data = request.json
    title = data.get('title', '')
    location = data.get('location', '')
    experience = data.get('experience', '')
    category = data.get('category', '')
    
    with db_cursor() as cursor:
        query = "SELECT * FROM jobs WHERE 1=1"
        params = []
        
        if title:
            query += " AND (title LIKE %s OR description LIKE %s OR skills LIKE %s)"
            params.extend([f'%{title}%', f'%{title}%', f'%{title}%'])
        if location:
            query += " AND location LIKE %s"
            params.append(f'%{location}%')
        if experience:
            query += " AND experience = %s"
            params.append(experience)
        if category:
            query += " AND category = %s"
            params.append(category)
        
        query += " ORDER BY id DESC"
        cursor.execute(query, params)
        jobs = cursor.fetchall()
    
    if title or category:
        jobs = get_nlp_search_results(jobs, f"{title} {category}")
    return jsonify({'success': True, 'jobs': jobs})

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
        return jsonify({'success': False, 'message': 'Please Login to Apply'})

    data = request.form
    job_id = data.get('job_id')

    # DUPLICATE CHECK
    with db_cursor(dictionary=False) as cursor:
        cursor.execute("SELECT id FROM applications WHERE job_id = %s AND user_id = %s", (job_id, session['user_id']))
        if cursor.fetchone():
            return jsonify({'success': False, 'message': 'You have already applied for this job.'})

    # RESUME VALIDATION (extension + size)
    file = request.files.get('resume')
    resume_filename = None
    if file and file.filename:
        if not allowed_file(file.filename):
            return jsonify({'success': False, 'message': 'Invalid resume type. Allowed: txt, pdf, doc, docx.'})
        file.seek(0, os.SEEK_END)
        if file.tell() > MAX_UPLOAD_BYTES:
            return jsonify({'success': False, 'message': f'Resume too large (max {MAX_UPLOAD_MB}MB).'})
        file.seek(0)
        filename = secure_filename(file.filename)
        resume_filename = f"{session['user_id']}_{datetime.now().strftime('%Y%m%d%H%M%S')}_{filename}"
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], resume_filename))

    with db_cursor(dictionary=False) as cursor:
        cursor.execute("""
            INSERT INTO applications (
                job_id, user_id, user_name, user_email, user_mobile,
                qualification, college_name, year_of_passing,
                experience_level, years_experience, previous_company,
                skills, resume_path, cover_letter,
                current_location, preferred_location, expected_salary
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (
            job_id, session['user_id'], data.get('name'), data.get('email'), data.get('mobile'),
            data.get('qualification'), data.get('college'), data.get('yop'),
            data.get('exp_level'), data.get('yoe'), data.get('prev_company'),
            data.get('skills'), resume_filename, data.get('cover'),
            data.get('curr_loc'), data.get('pref_loc'), data.get('salary')
        ))
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
    data = request.json
    ok, msg, http = _set_candidate_status(data.get('app_id'), 'Selected')
    return jsonify({'success': ok, 'message': msg}), http


@app.route('/api/update_candidate_status', methods=['POST'])
def update_candidate_status():
    if 'employer_id' not in session: return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    data = request.json
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
        cursor.execute("UPDATE notifications SET is_read = 1 WHERE user_id = %s AND is_read = 0", (session['user_id'],))
    for n in notifs:
        if n.get('created_at'): n['created_at'] = n['created_at'].isoformat()
    return jsonify({'success': True, 'notifications': notifs})

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
    data = request.json
    with db_cursor(dictionary=False) as cursor:
        cursor.execute("UPDATE user SET name=%s, mobile=%s WHERE id=%s", (data['name'], data['mobile'], session['user_id']))
    return jsonify({'success': True, 'message': 'Profile Updated'})

@app.route('/api/change_user_password', methods=['POST'])
def change_user_password():
    if 'user_id' not in session: return jsonify({'success': False}), 401
    data = request.json
    with db_cursor() as cursor:
        cursor.execute("SELECT password FROM user WHERE id = %s", (session['user_id'],))
        user = cursor.fetchone()
        if not user or not check_password_hash(str(user['password']), data['old_password']):
            return jsonify({'success': False, 'message': 'Incorrect Old Password'})
        new_hash = generate_password_hash(data['new_password'])
        cursor.execute("UPDATE user SET password = %s WHERE id = %s", (new_hash, session['user_id']))
    return jsonify({'success': True, 'message': 'Password Changed Successfully!'})

@app.route('/api/upload_resume', methods=['POST'])
def upload_resume():
    if 'user_id' not in session: return jsonify({'success': False}), 401
    if 'resume' not in request.files: return jsonify({'success': False})
    file = request.files['resume']
    if not file or not file.filename:
        return jsonify({'success': False})
    if not allowed_file(file.filename):
        return jsonify({'success': False, 'message': 'Invalid resume type. Allowed: txt, pdf, doc, docx.'})
    file.seek(0, os.SEEK_END)
    if file.tell() > MAX_UPLOAD_BYTES:
        return jsonify({'success': False, 'message': f'Resume too large (max {MAX_UPLOAD_MB}MB).'})
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
    data = request.json
    job_id = data.get('job_id')
    with db_cursor(dictionary=False) as cursor:
        cursor.execute("INSERT IGNORE INTO saved_jobs (user_id, job_id) VALUES (%s, %s)", (session['user_id'], job_id))
    return jsonify({'success': True, 'message': 'Job Saved'})

@app.route('/api/unsave_job', methods=['POST'])
def api_unsave_job():
    if 'user_id' not in session: return jsonify({'success': False, 'message': 'Login required'}), 401
    data = request.json
    job_id = data.get('job_id')
    with db_cursor(dictionary=False) as cursor:
        cursor.execute("DELETE FROM saved_jobs WHERE user_id = %s AND job_id = %s", (session['user_id'], job_id))
    return jsonify({'success': True, 'message': 'Job Unsaved'})

# --- WITHDRAW APPLICATION (job seeker) ---
@app.route('/api/withdraw_application', methods=['POST'])
def withdraw_application():
    if 'user_id' not in session: return jsonify({'success': False, 'message': 'Login required'}), 401
    data = request.json
    app_id = data.get('app_id')
    with db_cursor(dictionary=False) as cursor:
        cursor.execute("DELETE FROM applications WHERE id = %s AND user_id = %s", (app_id, session['user_id']))
    return jsonify({'success': True, 'message': 'Application withdrawn'})

# --- EDIT JOB (employer) ---
@app.route('/api/edit_job/<int:job_id>', methods=['POST'])
def edit_job(job_id):
    if 'employer_id' not in session: return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    data = request.json
    with db_cursor(dictionary=False) as cursor:
        cursor.execute("SELECT id FROM jobs WHERE id = %s AND employer_id = %s", (job_id, session['employer_id']))
        if not cursor.fetchone():
            return jsonify({'success': False, 'message': 'Unauthorized'}), 403
        cursor.execute("""
            UPDATE jobs SET title=%s, description=%s, location=%s, salary=%s,
                experience=%s, skills=%s, category=%s
            WHERE id = %s AND employer_id = %s
        """, (data.get('title'), data.get('description'), data.get('location'), data.get('salary'),
              data.get('experience'), data.get('skills'), data.get('category'), job_id, session['employer_id']))
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
    data = request.json
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
    data = request.json
    with db_cursor(dictionary=False) as cursor:
        cursor.execute("UPDATE employee SET company_name=%s, mobile=%s WHERE id=%s",
                       (data['company_name'], data['mobile'], session['employer_id']))
    return jsonify({'success': True, 'message': 'Profile Updated'})

@app.route('/api/change_employer_password', methods=['POST'])
def api_change_employer_password():
    if 'employer_id' not in session: return jsonify({'success': False}), 401
    data = request.json
    with db_cursor() as cursor:
        cursor.execute("SELECT password FROM employee WHERE id = %s", (session['employer_id'],))
        emp = cursor.fetchone()
        if not emp or not check_password_hash(str(emp['password']), data['old_password']):
            return jsonify({'success': False, 'message': 'Incorrect Old Password'})
        new_hash = generate_password_hash(data['new_password'])
        cursor.execute("UPDATE employee SET password = %s WHERE id = %s", (new_hash, session['employer_id']))
    return jsonify({'success': True, 'message': 'Password Changed'})


if __name__ == '__main__':
    # Debug only when explicitly enabled via FLASK_DEBUG=1 (default off for safety)
    debug_mode = os.getenv('FLASK_DEBUG', '0') == '1'
    app.run(debug=debug_mode, port=5000)