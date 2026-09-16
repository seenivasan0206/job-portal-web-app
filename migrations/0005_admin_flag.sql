-- Migration 0005: Admin user flag
-- Adds is_admin column to user table for admin panel access

ALTER TABLE user ADD COLUMN is_admin BOOLEAN DEFAULT FALSE;
