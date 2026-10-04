#!/bin/bash
# Runs once, when the Postgres data volume is first created: a user and database each for the
# demo (workflow_demo) and for n8n. Passwords come from deploy/aws/.env via compose.yml.
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
	-v demo_pw="$DEMO_DB_PASSWORD" -v n8n_pw="$N8N_DB_PASSWORD" <<-'EOSQL'
	CREATE USER demo WITH PASSWORD :'demo_pw';
	CREATE DATABASE workflow_demo OWNER demo;
	CREATE USER n8n WITH PASSWORD :'n8n_pw';
	CREATE DATABASE n8n OWNER n8n;
EOSQL
