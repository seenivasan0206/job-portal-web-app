-- Migration 0006: Fix rate_limits schema
-- Renames action_type -> action, timestamp -> window_start, adds count column
-- Aligns the migration schema with what app.py expects

ALTER TABLE rate_limits ADD COLUMN IF NOT EXISTS action VARCHAR(50) NOT NULL DEFAULT 'login';
ALTER TABLE rate_limits ADD COLUMN IF NOT EXISTS count INT DEFAULT 0;
ALTER TABLE rate_limits ADD COLUMN IF NOT EXISTS window_start TIMESTAMP DEFAULT CURRENT_TIMESTAMP;

-- Copy data from old columns if they exist
SET @sql = (SELECT IF(
    EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'rate_limits' AND column_name = 'action_type'),
    'UPDATE rate_limits SET action = action_type WHERE action IS NULL OR action = \'login\'',
    'SELECT 1'
));
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @sql = (SELECT IF(
    EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'rate_limits' AND column_name = 'timestamp' AND table_schema = DATABASE()),
    'UPDATE rate_limits SET window_start = timestamp WHERE window_start = CURRENT_TIMESTAMP',
    'SELECT 1'
));
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- Add indexes for the new schema
CREATE INDEX IF NOT EXISTS idx_rate_key ON rate_limits(rate_key);
CREATE INDEX IF NOT EXISTS idx_action_window ON rate_limits(action, window_start);
CREATE UNIQUE INDEX IF NOT EXISTS unique_rate_limit ON rate_limits(rate_key, action);
