-- Migration 0002: Rich job model fields
-- Adds job_type, work_mode, salary ranges, openings, deadline, is_active

ALTER TABLE jobs ADD COLUMN job_type VARCHAR(50) DEFAULT 'Full-time';
ALTER TABLE jobs ADD COLUMN work_mode VARCHAR(50) DEFAULT 'Onsite';
ALTER TABLE jobs ADD COLUMN salary_min INT DEFAULT 0;
ALTER TABLE jobs ADD COLUMN salary_max INT DEFAULT 0;
ALTER TABLE jobs ADD COLUMN openings INT DEFAULT 1;
ALTER TABLE jobs ADD COLUMN application_deadline DATE;
ALTER TABLE jobs ADD COLUMN is_active BOOLEAN DEFAULT TRUE;

CREATE INDEX jobs_title_idx ON jobs(title);
CREATE INDEX jobs_location_idx ON jobs(location);
CREATE INDEX jobs_category_idx ON jobs(category);
CREATE INDEX applications_job_id_idx ON applications(job_id);
CREATE INDEX applications_user_id_idx ON applications(user_id);
