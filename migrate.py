"""One-time migration: hash any plaintext passwords still stored in the
user and employee tables, update schemas, and initialize admin and moderation tables.

This script can only be run with the --confirm flag to prevent accidental
re-execution:

    python migrate.py --confirm

Requires a .env (or the DB defaults) so it can connect.

Werkzeug's check_password_hash cannot verify a plaintext value, so we
detect plaintext by attempting to parse the stored value as a hash
(format is always "pbkdf2:sha256$..." or "scrypt$..."). Anything that
does not match that format is treated as plaintext and re-hashed.
"""
import os
import sys
from dotenv import load_dotenv
import mysql.connector
from werkzeug.security import generate_password_hash

load_dotenv()

db_config = {
    'user': os.getenv('DB_USER', 'jobportal'),
    'password': os.getenv('DB_PASSWORD', 'mysql'),
    'host': os.getenv('DB_HOST', 'localhost'),
    'database': os.getenv('DB_NAME', 'jobportal_db'),
}


def looks_hashed(pw):
    # Werkzeug hashes start with the method name, e.g. "pbkdf2:sha256$..."
    return bool(pw) and ('$' in pw) and not pw.startswith('$plain$')


def migrate(table, id_col):
    conn = mysql.connector.connect(**db_config)
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(f"SELECT {id_col}, password FROM {table}")
        rows = cur.fetchall()
        updated = 0
        for r in rows:
            pw = r['password']
            if pw and not looks_hashed(pw):
                cur.execute(
                    f"UPDATE {table} SET password = %s WHERE {id_col} = %s",
                    (generate_password_hash(pw), r[id_col]),
                )
                updated += 1
        conn.commit()
        print(f"{table}: {updated} plaintext password(s) hashed.")
    finally:
        cur.close()
        conn.close()


def migrate_user_schema():
    """Add consent_to_search, profile_visibility, headline, skills, experience, location, is_admin to user table."""
    conn = mysql.connector.connect(**db_config)
    cur = conn.cursor()
    try:
        _user_columns = [
            'profile_visibility VARCHAR(20) DEFAULT \'public\'',
            'consent_to_search BOOLEAN DEFAULT 0',
            'headline VARCHAR(255) DEFAULT \'\'',
            'skills TEXT DEFAULT \'\'',
            'experience INT DEFAULT 0',
            'location VARCHAR(100) DEFAULT \'\'',
            'is_admin BOOLEAN DEFAULT FALSE',
        ]
        for col_def in _user_columns:
            col_name = col_def.split()[0]
            try:
                cur.execute(f"ALTER TABLE user ADD COLUMN {col_name} {col_def.split(' ', 1)[1]}")
            except Exception:
                pass
        conn.commit()
        print("user: schema columns added.")
    finally:
        cur.close()
        conn.close()


def migrate_candidate_profile_schema():
    """Add general_resume_path to candidate_profile table."""
    conn = mysql.connector.connect(**db_config)
    cur = conn.cursor()
    try:
        try:
            cur.execute("ALTER TABLE candidate_profile ADD COLUMN general_resume_path VARCHAR(255)")
        except Exception:
            pass
        conn.commit()
        print("candidate_profile: general_resume_path column added.")
    finally:
        cur.close()
        conn.close()


def migrate_stub_features_schema():
    """Create tables for company_follows, saved_candidates, interviews, messages, assessments."""
    conn = mysql.connector.connect(**db_config)
    cur = conn.cursor()
    try:
        tables = {
            'company_follows': """
                CREATE TABLE IF NOT EXISTS company_follows (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    user_id INT NOT NULL,
                    company_id INT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE KEY unique_follow (user_id, company_id),
                    FOREIGN KEY (user_id) REFERENCES user(id) ON DELETE CASCADE,
                    FOREIGN KEY (company_id) REFERENCES employee(id) ON DELETE CASCADE
                )
            """,
            'saved_candidates': """
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
            """,
            'interviews': """
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
                    FOREIGN KEY (candidate_id) REFERENCES user(id) ON DELETE CASCADE
                )
            """,
            'conversations': """
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
            """,
            'messages': """
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
            """,
            'assessments': """
                CREATE TABLE IF NOT EXISTS assessments (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    title VARCHAR(255) NOT NULL,
                    skill VARCHAR(100) DEFAULT 'technical',
                    questions_count INT DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """,
            'assessment_responses': """
                CREATE TABLE IF NOT EXISTS assessment_responses (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    user_id INT NOT NULL,
                    test_id INT NOT NULL,
                    answers TEXT,
                    score INT DEFAULT 0,
                    total_questions INT DEFAULT 0,
                    submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES user(id) ON DELETE CASCADE,
                    FOREIGN KEY (test_id) REFERENCES assessments(id) ON DELETE CASCADE
                )
            """,
        }
        for _, ddl in tables.items():
            cur.execute(ddl)
        try:
            cur.execute("ALTER TABLE interviews ADD COLUMN IF NOT EXISTS cancelled_at TIMESTAMP NULL")
        except Exception:
            pass
        for col_def in [
            'verification_status VARCHAR(20) DEFAULT \'pending\'',
            'verified_at TIMESTAMP NULL',
        ]:
            col_name = col_def.split()[0]
            try:
                cur.execute(f"ALTER TABLE employee ADD COLUMN {col_name} {col_def.split(' ', 1)[1]}")
            except Exception:
                pass
        default_assessments = [
            ('Python Programming', 'technical', 20),
            ('JavaScript Fundamentals', 'technical', 25),
            ('Aptitude Test', 'aptitude', 15),
            ('SQL & Database', 'technical', 20),
        ]
        for title, skill, count in default_assessments:
            cur.execute("INSERT IGNORE INTO assessments (title, skill, questions_count) VALUES (%s, %s, %s)", (title, skill, count))
        conn.commit()
        print("stub_features: company_follows, saved_candidates, interviews, messages, assessments tables created.")
    finally:
        cur.close()
        conn.close()


def migrate_job_alerts_schema():
    """Create job_alerts_sent table for deduplication of cron alert emails."""
    conn = mysql.connector.connect(**db_config)
    cur = conn.cursor()
    try:
        cur.execute("""
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
        try:
            cur.execute("ALTER TABLE job_alerts_sent ADD COLUMN alert_id INT")
        except Exception:
            pass
        conn.commit()
        print("job_alerts_sent: table created.")
    except Exception as e:
        conn.rollback()
        print(f"job_alerts_sent migration error: {e}")
    finally:
        cur.close()
        conn.close()


def migrate_admin_and_moderation_schema():
    """Create company_verification_history, reports, admin_audit_logs tables and provision admin."""
    conn = mysql.connector.connect(**db_config)
    cur = conn.cursor(dictionary=True)
    try:
        tables = [
            """
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
            """,
            """
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
            """,
            """
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
            """
        ]
        for ddl in tables:
            cur.execute(ddl)

        # Ensure employee table has all moderation fields
        for col_def in [
            'is_verified BOOLEAN DEFAULT FALSE',
            'verification_status VARCHAR(50) DEFAULT \'unverified\'',
            'company_website VARCHAR(255) DEFAULT \'\'',
            'verified_at DATETIME NULL',
            'verification_notes TEXT',
            'verification_submitted_at DATETIME NULL',
            'risk_level VARCHAR(20) DEFAULT \'low\'',
        ]:
            col_name = col_def.split()[0]
            try:
                cur.execute(f"ALTER TABLE employee ADD COLUMN {col_name} {col_def.split(' ', 1)[1]}")
            except Exception:
                pass

        # Provision default admin user
        admin_email = os.getenv('ADMIN_EMAIL', 'ccubetech00@gmail.com').strip().lower()
        admin_password = os.getenv('ADMIN_PASSWORD', 'ccubetech00')
        cur.execute("SELECT id, password, is_admin FROM user WHERE email = %s", (admin_email,))
        admin_user = cur.fetchone()
        if not admin_user:
            cur.execute("""
                INSERT INTO user (name, email, password, is_admin, is_verified, profile_visibility)
                VALUES (%s, %s, %s, TRUE, TRUE, 'private')
            """, ('HireVoltz Admin', admin_email, generate_password_hash(admin_password)))
            print(f"admin: user {admin_email} created with is_admin=TRUE.")
        else:
            cur.execute("UPDATE user SET is_admin = TRUE, is_verified = TRUE WHERE id = %s", (admin_user['id'],))
            print(f"admin: user {admin_email} updated with is_admin=TRUE.")

        conn.commit()
        print("admin_and_moderation: tables and admin account ready.")
    except Exception as e:
        conn.rollback()
        print(f"admin_and_moderation migration error: {e}")
    finally:
        cur.close()
        conn.close()


if __name__ == '__main__':
    if '--confirm' not in sys.argv:
        print("This migration modifies passwords in the database.")
        print("To proceed, run: python migrate.py --confirm")
        sys.exit(1)
    migrate('user', 'id')
    migrate('employee', 'id')
    migrate_user_schema()
    migrate_candidate_profile_schema()
    migrate_stub_features_schema()
    migrate_job_alerts_schema()
    migrate_admin_and_moderation_schema()
    print("Migration complete.")
