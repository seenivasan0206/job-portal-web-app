-- Migration 0001: Initial schema
-- Creates all base tables for the job portal

CREATE TABLE IF NOT EXISTS otp_store (
    email VARCHAR(100),
    otp VARCHAR(6),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP NULL,
    INDEX idx_otp_email (email)
);

CREATE TABLE IF NOT EXISTS employee (
    id INT AUTO_INCREMENT PRIMARY KEY,
    company_name VARCHAR(100),
    mobile VARCHAR(20),
    email VARCHAR(100) UNIQUE,
    password VARCHAR(255)
);

CREATE TABLE IF NOT EXISTS user (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100),
    email VARCHAR(100) UNIQUE,
    password VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    mobile VARCHAR(20),
    is_verified BOOLEAN DEFAULT FALSE
);

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
);

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
    UNIQUE KEY unique_application (job_id, user_id)
);

CREATE TABLE IF NOT EXISTS saved_jobs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT,
    job_id INT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY unique_saved_job (user_id, job_id),
    INDEX idx_saved_jobs_user_id (user_id),
    INDEX idx_saved_jobs_job_id (job_id),
    FOREIGN KEY (user_id) REFERENCES user(id) ON DELETE CASCADE,
    FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS notifications (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    message TEXT,
    is_read BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS rate_limits (
    id INT AUTO_INCREMENT PRIMARY KEY,
    rate_key VARCHAR(255) NOT NULL,
    action VARCHAR(50) NOT NULL,
    count INT DEFAULT 0,
    window_start TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY unique_rate_limit (rate_key, action),
    INDEX idx_rate_key (rate_key),
    INDEX idx_action_window (action, window_start)
);

CREATE TABLE IF NOT EXISTS job_categories (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE
);

INSERT IGNORE INTO job_categories (name) VALUES
    ('IT & Software'), ('Banking & Finance'), ('Healthcare'),
    ('Engineering'), ('Manufacturing'), ('Education'),
    ('Government'), ('Retail'), ('Marketing'), ('Other');
