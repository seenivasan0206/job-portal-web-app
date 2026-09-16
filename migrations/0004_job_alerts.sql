-- Migration 0004: Job alerts table
-- Allows users to set up saved search alerts with email notifications

CREATE TABLE IF NOT EXISTS job_alerts (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    keywords VARCHAR(255),
    location VARCHAR(100),
    category VARCHAR(100),
    job_type VARCHAR(50),
    frequency ENUM('daily', 'weekly') DEFAULT 'daily',
    is_active BOOLEAN DEFAULT TRUE,
    last_sent TIMESTAMP NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES user(id) ON DELETE CASCADE
);
