import os
import re
import random
import string
import smtplib
from email.message import EmailMessage
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, send_from_directory
import mysql.connector
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

app = Flask(__name__)
app.secret_key = 'dream_jobs_secret_key_123'
app.permanent_session_lifetime = timedelta(days=1)

# --- EMAIL CONFIGURATION ---
EMAIL_ADDRESS = 'Your_Email_id'
EMAIL_PASSWORD = 'Your_password_here'

# --- CONFIGURATION ---
UPLOAD_FOLDER = 'resumes'
ALLOWED_EXTENSIONS = {'txt', 'pdf', 'doc', 'docx'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# --- DATABASE CONFIGURATION ---
db_config = {
    'user': 'root',
    'password': 'mysql',
    'host': 'localhost',
    'database': 'dream_jobs0'
}

def get_db():
    return mysql.connector.connect(**db_config)

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
            company_name VARCHAR(100),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (employer_id) REFERENCES employee(id)
        )
    """)
    
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
    try:
        return send_from_directory(app.config['UPLOAD_FOLDER'], filename, as_attachment=True)
    except FileNotFoundError:
        return "File not found", 404

# --- CHECK SESSION ---
@app.route('/api/check_session')
def check_session():
    return jsonify({'logged_in': 'user_id' in session})

# --- AUTH APIs ---
@app.route('/api/send_otp', methods=['POST'])
def api_send_otp():
    data = request.json
    email = data.get('email')
    otp = ''.join(random.choices(string.digits, k=6))
    
    conn = get_db(); cursor = conn.cursor()
    cursor.execute("DELETE FROM otp_store WHERE email = %s", (email,))
    cursor.execute("INSERT INTO otp_store (email, otp) VALUES (%s, %s)", (email, otp))
    conn.commit(); conn.close()
    
    try:
        msg = EmailMessage()
        # --- UPDATED OTP CONTENT ---
        msg.set_content(f"""Subject: Your Verification Code - Dream Jobs

Dear User,

Your One-Time Password (OTP) for verification is:

🔐 OTP: {otp}

This code is valid for the next 2 minutes. Please do not share this code with anyone for security reasons.

If you did not request this, please ignore this email.

Best regards,  
Dream Jobs Team""")
        msg['Subject'] = "Your Verification Code - Dream Jobs"
        msg['From'] = EMAIL_ADDRESS
        msg['To'] = email
        with smtplib.SMTP('smtp.gmail.com', 587) as smtp:
            smtp.starttls()
            smtp.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            smtp.send_message(msg)
        return jsonify({'success': True, 'message': 'OTP Sent to Email'})
    except Exception as e:
        print(f"Email Error: {e}")
        return jsonify({'success': True, 'message': 'OTP Generated (Check Console)', 'demo_otp': otp})

@app.route('/api/user/register', methods=['POST'])
def api_user_register():
    data = request.json
    conn = get_db(); cursor = conn.cursor(dictionary=True)
    
    # 1. Check if email already exists
    cursor.execute("SELECT id FROM user WHERE email = %s", (data['email'],))
    if cursor.fetchone():
        conn.close()
        return jsonify({'success': False, 'message': 'Email already exists. Please login.'})

    # 2. Register User
    hashed_pw = generate_password_hash(data['password'])
    try:
        cursor.execute("INSERT INTO user (name, email, mobile, password, is_verified) VALUES (%s, %s, %s, %s, %s)", 
                       (data['name'], data['email'], data['mobile'], hashed_pw, True))
        conn.commit()
        
        # 3. Auto Login: Set Session
        user_id = cursor.lastrowid
        session['user_id'] = user_id
        session['user_name'] = data['name']
        
        return jsonify({'success': True, 'message': 'Account Created Successfully!', 'redirect': '/user_dashboard'})
    except Exception as e: 
        return jsonify({'success': False, 'message': str(e)})
    finally: conn.close()

@app.route('/api/user/login', methods=['POST'])
def api_user_login():
    data = request.json
    email = data.get('email', '').strip()
    password = data.get('password', '')
    
    if not email or not password:
        return jsonify({'success': False, 'message': 'Email and password are required'})
    
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT id, name, email, password FROM user WHERE email = %s", (email,))
    user = cursor.fetchone()
    conn.close()
    
    if not user:
        return jsonify({'success': False, 'message': 'Email not found. Please register.'})
    
    # Convert to string to handle any encoding issues
    stored_password = str(user['password'])
    input_password = password
    
    if check_password_hash(stored_password, input_password):
        session['user_id'] = user['id']
        session['user_name'] = user['name']
        return jsonify({'success': True, 'message': 'Login Successful', 'redirect': '/user_dashboard'})
    else:
        # Try plain text comparison for backward compatibility
        if stored_password == input_password:
            session['user_id'] = user['id']
            session['user_name'] = user['name']
            return jsonify({'success': True, 'message': 'Login Successful', 'redirect': '/user_dashboard'})
        return jsonify({'success': False, 'message': 'Wrong Password'})

@app.route('/api/employer/register', methods=['POST'])
def api_employer_register():
    data = request.json
    conn = get_db(); cursor = conn.cursor(dictionary=True)
    
    # 1. Check if email already exists
    cursor.execute("SELECT id FROM employee WHERE email = %s", (data['email'],))
    if cursor.fetchone():
        conn.close()
        return jsonify({'success': False, 'message': 'Email already exists. Please login.'})

    # 2. Register Employer
    hashed_pw = generate_password_hash(data['password'])
    try:
        cursor.execute("INSERT INTO employee (company_name, mobile, email, password) VALUES (%s, %s, %s, %s)", 
                       (data['name'], data['mobile'], data['email'], hashed_pw))
        conn.commit()
        
        # 3. Auto Login: Set Session
        emp_id = cursor.lastrowid
        session['employer_id'] = emp_id
        session['user_name'] = data['name']
        
        return jsonify({'success': True, 'message': 'Account Created Successfully!', 'redirect': '/employer_dashboard'})
    except Exception as e: 
        return jsonify({'success': False, 'message': str(e)})
    finally: conn.close()

@app.route('/api/employer/login', methods=['POST'])
def api_employer_login():
    data = request.json
    email = data.get('email', '').strip()
    password = data.get('password', '')
    
    if not email or not password:
        return jsonify({'success': False, 'message': 'Email and password are required'})
    
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT id, company_name, email, password FROM employee WHERE email = %s", (email,))
    emp = cursor.fetchone()
    conn.close()
    
    if not emp:
        return jsonify({'success': False, 'message': 'Email not found. Please register.'})
    
    stored_password = str(emp['password'])
    input_password = password
    
    if check_password_hash(stored_password, input_password):
        session['employer_id'] = emp['id']
        session['user_name'] = emp['company_name']
        return jsonify({'success': True, 'message': 'Login Successful', 'redirect': '/employer_dashboard'})
    else:
        if stored_password == input_password:
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
    conn = get_db(); cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM otp_store WHERE email = %s AND otp = %s ORDER BY created_at DESC LIMIT 1", (email, otp))
    entry = cursor.fetchone()
    if not entry: conn.close(); return jsonify({'success': False, 'message': 'Invalid OTP'})
    hashed_pw = generate_password_hash(new_password)
    cursor.execute("UPDATE user SET password = %s WHERE email = %s", (hashed_pw, email))
    cursor.execute("DELETE FROM otp_store WHERE email = %s", (email,))
    conn.commit(); conn.close()
    return jsonify({'success': True, 'message': 'Password Reset Successful'})

# --- CORE APIs ---
@app.route('/api/post_job', methods=['POST'])
def api_post_job():
    if 'employer_id' not in session: return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    data = request.json
    conn = get_db(); cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO jobs (employer_id, title, description, location, salary, experience, skills, company_name)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (session['employer_id'], data['title'], data['description'], data['location'], data['salary'], data['experience'], data['skills'], session['user_name']))
        conn.commit()
        return jsonify({'success': True, 'message': 'Job Posted'})
    except Exception as e: return jsonify({'success': False, 'message': str(e)})
    finally: cursor.close(); conn.close()

@app.route('/api/get_employer_jobs')
def api_get_employer_jobs():
    if 'employer_id' not in session: return jsonify({'success': False}), 401
    conn = get_db(); cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM jobs WHERE employer_id = %s ORDER BY id DESC", (session['employer_id'],))
    jobs = cursor.fetchall(); conn.close()
    for j in jobs:
        if j.get('created_at'): j['created_at'] = j['created_at'].strftime('%Y-%m-%d')
    return jsonify({'success': True, 'jobs': jobs})

@app.route('/api/delete_job/<int:job_id>', methods=['POST'])
def delete_job(job_id):
    if 'employer_id' not in session: return jsonify({'success': False}), 401
    conn = get_db(); cursor = conn.cursor()
    cursor.execute("DELETE FROM jobs WHERE id = %s AND employer_id = %s", (job_id, session['employer_id']))
    conn.commit(); conn.close()
    return jsonify({'success': True, 'message': 'Job Deleted'})

@app.route('/api/get_all_jobs')
def api_get_all_jobs():
    conn = get_db(); cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM jobs ORDER BY id DESC")
    jobs = cursor.fetchall(); conn.close()
    return jsonify({'success': True, 'jobs': jobs})

@app.route('/api/jobs/search', methods=['POST'])
def api_jobs_search():
    data = request.json
    title = data.get('title', '')
    location = data.get('location', '')
    experience = data.get('experience', '')
    category = data.get('category', '')
    
    conn = get_db(); cursor = conn.cursor(dictionary=True)
    
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
        query += " AND (skills LIKE %s OR description LIKE %s)"
        params.extend([f'%{category}%', f'%{category}%'])
    
    query += " ORDER BY id DESC"
    cursor.execute(query, params)
    jobs = cursor.fetchall(); conn.close()
    
    if title or category:
        jobs = get_nlp_search_results(jobs, f"{title} {category}")
    return jsonify({'success': True, 'jobs': jobs})

# --- APPLY LOGIC ---
@app.route('/api/user/applied_jobs')
def get_applied_jobs():
    if 'user_id' not in session: return jsonify({'success': False}), 401
    conn = get_db(); cursor = conn.cursor()
    cursor.execute("SELECT job_id FROM applications WHERE user_id = %s", (session['user_id'],))
    ids = [str(row[0]) for row in cursor.fetchall()]
    conn.close()
    return jsonify({'success': True, 'applied_ids': ids})

@app.route('/api/apply_job', methods=['POST'])
def api_apply_job():
    if 'user_id' not in session: 
        return jsonify({'success': False, 'message': 'Please Login to Apply'})

    data = request.form
    job_id = data.get('job_id')
    
    # DUPLICATE CHECK
    conn = get_db(); cursor = conn.cursor()
    cursor.execute("SELECT id FROM applications WHERE job_id = %s AND user_id = %s", (job_id, session['user_id']))
    if cursor.fetchone():
        conn.close()
        return jsonify({'success': False, 'message': 'You have already applied for this job.'})

    file = request.files.get('resume')
    resume_filename = None
    if file and file.filename:
        filename = secure_filename(file.filename)
        resume_filename = f"{session['user_id']}_{datetime.now().strftime('%Y%m%d%H%M%S')}_{filename}"
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], resume_filename))

    try:
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
        conn.commit()
        return jsonify({'success': True, 'message': 'Application Submitted'})
    except Exception as e:
        print(e)
        return jsonify({'success': False, 'message': str(e)})
    finally:
        conn.close()

@app.route('/api/get_applicants/<int:job_id>')
def get_applicants(job_id):
    if 'employer_id' not in session: return jsonify({'success': False}), 401
    conn = get_db(); cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM applications WHERE job_id = %s", (job_id,))
    apps = cursor.fetchall(); conn.close()
    return jsonify({'success': True, 'applicants': apps})

@app.route('/api/select_candidate', methods=['POST'])
def select_candidate():
    data = request.json
    app_id = data.get('app_id')
    conn = get_db(); cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM applications WHERE id = %s", (app_id,))
    app = cursor.fetchone()
    if app:
        cursor.execute("UPDATE applications SET status='Selected' WHERE id=%s", (app_id,))
        cursor.execute("SELECT title, company_name FROM jobs WHERE id = %s", (app['job_id'],))
        job = cursor.fetchone()
        msg = f"Congratulations! You have been selected for the position of '{job['title']}' at {job['company_name']}. The employer will contact you shortly."
        cursor.execute("INSERT INTO notifications (user_id, message) VALUES (%s, %s)", (app['user_id'], msg))
        conn.commit()
    conn.close()
    return jsonify({'success': True, 'message': 'Candidate Selected'})

# --- NOTIFICATION APIs ---
@app.route('/api/get_user_notifications')
def get_user_notifications():
    if 'user_id' not in session: return jsonify({'success': False}), 401
    conn = get_db(); cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM notifications WHERE user_id = %s ORDER BY created_at DESC LIMIT 10", (session['user_id'],))
    notifs = cursor.fetchall()
    cursor.execute("UPDATE notifications SET is_read = 1 WHERE user_id = %s", (session['user_id'],))
    conn.commit(); conn.close()
    for n in notifs:
        if n.get('created_at'): n['created_at'] = n['created_at'].strftime('%Y-%m-%d %H:%M')
    return jsonify({'success': True, 'notifications': notifs})

@app.route('/api/get_unread_count')
def get_unread_count():
    if 'user_id' not in session: return jsonify({'count': 0})
    conn = get_db(); cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM notifications WHERE user_id = %s AND is_read = 0", (session['user_id'],))
    count = cursor.fetchone()[0]
    conn.close()
    return jsonify({'count': count})

# --- SETTINGS & RESUME APIs ---
@app.route('/api/get_user_profile')
def get_user_profile():
    if 'user_id' not in session: return jsonify({'success': False}), 401
    conn = get_db(); cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT id, name, email, mobile FROM user WHERE id = %s", (session['user_id'],))
    user = cursor.fetchone(); conn.close()
    return jsonify({'success': True, 'user': user})

@app.route('/api/update_user_profile', methods=['POST'])
def update_user_profile():
    if 'user_id' not in session: return jsonify({'success': False}), 401
    data = request.json
    conn = get_db(); cursor = conn.cursor()
    cursor.execute("UPDATE user SET name=%s, mobile=%s WHERE id=%s", (data['name'], data['mobile'], session['user_id']))
    conn.commit(); conn.close()
    return jsonify({'success': True, 'message': 'Profile Updated'})

@app.route('/api/change_user_password', methods=['POST'])
def change_user_password():
    if 'user_id' not in session: return jsonify({'success': False}), 401
    data = request.json
    conn = get_db(); cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT password FROM user WHERE id = %s", (session['user_id'],))
    user = cursor.fetchone()
    
    stored_password = str(user['password'])
    input_password = data['old_password']
    
    # Support both hashed and plain text passwords
    password_valid = False
    if check_password_hash(stored_password, input_password):
        password_valid = True
    elif stored_password == input_password:
        password_valid = True
    
    if not password_valid:
        conn.close()
        return jsonify({'success': False, 'message': 'Incorrect Old Password'})
    
    new_hash = generate_password_hash(data['new_password'])
    cursor.execute("UPDATE user SET password = %s WHERE id = %s", (new_hash, session['user_id']))
    conn.commit(); conn.close()
    return jsonify({'success': True, 'message': 'Password Changed Successfully!'})

@app.route('/api/upload_resume', methods=['POST'])
def upload_resume():
    if 'user_id' not in session: return jsonify({'success': False}), 401
    if 'resume' not in request.files: return jsonify({'success': False})
    file = request.files['resume']
    if file:
        content = file.read().decode('utf-8', errors='ignore')
        skills = ['python', 'java', 'sql', 'html', 'css', 'javascript', 'flask', 'django', 'react', 'c++', 'management', 'marketing', 'sales']
        found = [s for s in skills if re.search(r'\b' + s + r'\b', content.lower())]
        
        conn = get_db(); cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM jobs")
        jobs = cursor.fetchall(); conn.close()
        
        ranked = []
        for job in jobs:
            if job['skills']:
                job_skills = [s.strip().lower() for s in job['skills'].split(',')]
                score = int(len(set(found) & set(job_skills)) / len(job_skills) * 100)
                if score > 0: ranked.append({**job, 'score': score})
        
        ranked.sort(key=lambda x: x['score'], reverse=True)
        return jsonify({'success': True, 'jobs': ranked, 'skills': found})
    return jsonify({'success': False})

# --- SAVED JOBS APIs ---
@app.route('/api/save_job', methods=['POST'])
def api_save_job():
    if 'user_id' not in session: return jsonify({'success': False, 'message': 'Login required'}), 401
    data = request.json
    job_id = data.get('job_id')
    conn = get_db(); cursor = conn.cursor()
    try:
        cursor.execute("INSERT IGNORE INTO saved_jobs (user_id, job_id) VALUES (%s, %s)", (session['user_id'], job_id))
        conn.commit()
        return jsonify({'success': True, 'message': 'Job Saved'})
    except Exception as e: return jsonify({'success': False, 'message': str(e)})
    finally: conn.close()

@app.route('/api/unsave_job', methods=['POST'])
def api_unsave_job():
    if 'user_id' not in session: return jsonify({'success': False, 'message': 'Login required'}), 401
    data = request.json
    job_id = data.get('job_id')
    conn = get_db(); cursor = conn.cursor()
    cursor.execute("DELETE FROM saved_jobs WHERE user_id = %s AND job_id = %s", (session['user_id'], job_id))
    conn.commit(); conn.close()
    return jsonify({'success': True, 'message': 'Job Unsaved'})

@app.route('/api/get_saved_jobs')
def api_get_saved_jobs():
    if 'user_id' not in session: return jsonify({'success': False}), 401
    conn = get_db(); cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT j.* FROM jobs j 
        INNER JOIN saved_jobs s ON j.id = s.job_id 
        WHERE s.user_id = %s 
        ORDER BY s.created_at DESC
    """, (session['user_id'],))
    jobs = cursor.fetchall(); conn.close()
    return jsonify({'success': True, 'jobs': jobs})

@app.route('/api/get_saved_job_ids')
def api_get_saved_job_ids():
    if 'user_id' not in session: return jsonify({'saved_ids': []})
    conn = get_db(); cursor = conn.cursor()
    cursor.execute("SELECT job_id FROM saved_jobs WHERE user_id = %s", (session['user_id'],))
    ids = [str(row[0]) for row in cursor.fetchall()]
    conn.close()
    return jsonify({'saved_ids': ids})

# --- CATEGORIES API ---
@app.route('/api/get_categories')
def api_get_categories():
    conn = get_db(); cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM job_categories")
    cats = cursor.fetchall(); conn.close()
    return jsonify({'success': True, 'categories': cats})

# --- APPLICATION STATUS API ---
@app.route('/api/user/application_status')
def api_user_application_status():
    if 'user_id' not in session: return jsonify({'success': False}), 401
    conn = get_db(); cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT a.id, a.status, a.created_at, j.title, j.company_name, j.location 
        FROM applications a 
        INNER JOIN jobs j ON a.job_id = j.id 
        WHERE a.user_id = %s 
        ORDER BY a.created_at DESC
    """, (session['user_id'],))
    apps = cursor.fetchall(); conn.close()
    for a in apps:
        if a.get('created_at'): a['created_at'] = a['created_at'].strftime('%Y-%m-%d')
    return jsonify({'success': True, 'applications': apps})

@app.route('/api/reject_candidate', methods=['POST'])
def reject_candidate():
    data = request.json
    app_id = data.get('app_id')
    conn = get_db(); cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM applications WHERE id = %s", (app_id,))
    app = cursor.fetchone()
    if app:
        cursor.execute("UPDATE applications SET status='Rejected' WHERE id=%s", (app_id,))
        cursor.execute("SELECT title, company_name FROM jobs WHERE id = %s", (app['job_id'],))
        job = cursor.fetchone()
        msg = f"We regret to inform you that your application for the position of '{job['title']}' at {job['company_name']} has been not selected at this time. We wish you all the best in your future endeavors."
        cursor.execute("INSERT INTO notifications (user_id, message) VALUES (%s, %s)", (app['user_id'], msg))
        conn.commit()
    conn.close()
    return jsonify({'success': True, 'message': 'Candidate Rejected'})

@app.route('/api/employer/application_count')
def employer_application_count():
    if 'employer_id' not in session: return jsonify({'count': 0})
    conn = get_db(); cursor = conn.cursor()
    cursor.execute("""
        SELECT COUNT(*) FROM applications a
        INNER JOIN jobs j ON a.job_id = j.id
        WHERE j.employer_id = %s
    """, (session['employer_id'],))
    count = cursor.fetchone()[0]
    conn.close()
    return jsonify({'count': count})
@app.route('/api/jobs/paginated')
def api_jobs_paginated():
    page = request.args.get('page', 1, type=int)
    per_page = 10
    offset = (page - 1) * per_page
    conn = get_db(); cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT COUNT(*) as total FROM jobs")
    total = cursor.fetchone()['total']
    cursor.execute("SELECT * FROM jobs ORDER BY id DESC LIMIT %s OFFSET %s", (per_page, offset))
    jobs = cursor.fetchall(); conn.close()
    return jsonify({'success': True, 'jobs': jobs, 'total': total, 'page': page, 'per_page': per_page})

# --- EMPLOYER PROFILE API ---
@app.route('/api/employer_profile')
def api_employer_profile():
    if 'employer_id' not in session: return jsonify({'success': False}), 401
    conn = get_db(); cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT id, company_name, email, mobile FROM employee WHERE id = %s", (session['employer_id'],))
    emp = cursor.fetchone(); conn.close()
    return jsonify({'success': True, 'employer': emp})

@app.route('/api/update_employer_profile', methods=['POST'])
def api_update_employer_profile():
    if 'employer_id' not in session: return jsonify({'success': False}), 401
    data = request.json
    conn = get_db(); cursor = conn.cursor()
    cursor.execute("UPDATE employee SET company_name=%s, mobile=%s WHERE id=%s", 
                   (data['company_name'], data['mobile'], session['employer_id']))
    conn.commit(); conn.close()
    return jsonify({'success': True, 'message': 'Profile Updated'})

@app.route('/api/change_employer_password', methods=['POST'])
def api_change_employer_password():
    if 'employer_id' not in session: return jsonify({'success': False}), 401
    data = request.json
    conn = get_db(); cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT password FROM employee WHERE id = %s", (session['employer_id'],))
    emp = cursor.fetchone()
    if not check_password_hash(emp['password'], data['old_password']):
        return jsonify({'success': False, 'message': 'Incorrect Old Password'})
    new_hash = generate_password_hash(data['new_password'])
    cursor.execute("UPDATE employee SET password = %s WHERE id = %s", (new_hash, session['employer_id']))
    conn.commit(); conn.close()
    return jsonify({'success': True, 'message': 'Password Changed'})

if __name__ == '__main__':
    app.run(debug=True, port=5000)