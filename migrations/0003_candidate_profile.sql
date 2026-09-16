-- Migration 0003: Candidate profile table
-- Adds structured candidate profiles with public visibility

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
);
