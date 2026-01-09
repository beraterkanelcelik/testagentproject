-- Database initialization script
-- This script runs when the database container is first created

-- Create extensions
\i /docker-entrypoint-initdb.d/extensions.sql

-- Create Langfuse database
CREATE DATABASE langfuse_db;

-- Additional initialization can go here
-- For example, creating initial schemas or users
