SELECT 'CREATE ROLE reconai WITH LOGIN PASSWORD ''reconai'''
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'reconai')\gexec

ALTER ROLE reconai WITH PASSWORD 'reconai';
ALTER ROLE reconai CREATEDB;

SELECT 'CREATE DATABASE reconai OWNER reconai'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'reconai')\gexec

GRANT ALL PRIVILEGES ON DATABASE reconai TO reconai;
