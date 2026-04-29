#!/bin/bash
# ops/scripts/init-postgres.sh
#
# Initialisation pgvector pour le container shugu-postgres.
# Monté dans /docker-entrypoint-initdb.d/ — exécuté une seule fois à la
# première création du volume (quand PGDATA est vide).
#
# Crée :
#   - La base de données "shugu"
#   - Le rôle "shugu" avec PASSWORD (requis pour auth scram-sha-256
#     depuis le container backend via réseau Docker)
#   - Les extensions vector (pgvector) et pg_trgm (recall mémoire Phase 1)
#
# Régression P1 review #64 : sans password, asyncpg cross-container échoue.
# pgvector/pgvector:pg16 utilise scram-sha-256 par défaut sur les connexions
# TCP/IP non-trust — le rôle shugu sans password ne peut pas s'authentifier
# depuis le container backend. Le password est injecté via SHUGU_DB_PASSWORD
# (env var passée par compose.yml). Le backend lit la même valeur dans son
# DSN (SHUGU_POSTGRES_DSN=postgresql+asyncpg://shugu:${SHUGU_DB_PASSWORD}@postgres/shugu).
#
# Note : le superuser postgres peut toujours se connecter pour la maintenance ;
# l'application se connecte en tant que "shugu".
set -e

if [ -z "${SHUGU_DB_PASSWORD:-}" ]; then
    echo "[init-postgres] ERROR: SHUGU_DB_PASSWORD env var required (set in .env)" >&2
    exit 1
fi

psql -v ON_ERROR_STOP=1 \
     -v shugu_db_password="$SHUGU_DB_PASSWORD" \
     --username "$POSTGRES_USER" \
     --dbname "$POSTGRES_DB" <<-EOSQL
    -- Role applicatif avec mot de passe (requis pour auth scram-sha-256
    -- depuis le container backend via le réseau Docker Compose).
    DO \$\$
    BEGIN
        IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'shugu') THEN
            CREATE ROLE shugu LOGIN PASSWORD :'shugu_db_password';
        ELSE
            -- Idempotence : si le rôle existe déjà (volume Postgres préservé
            -- entre redémarrages), met à jour le password depuis l'env.
            ALTER ROLE shugu WITH PASSWORD :'shugu_db_password';
        END IF;
    END
    \$\$;

    -- Base de données principale.
    DO \$\$
    BEGIN
        IF NOT EXISTS (SELECT FROM pg_database WHERE datname = 'shugu') THEN
            CREATE DATABASE shugu OWNER shugu;
        END IF;
    END
    \$\$;
EOSQL

# Extensions dans la base shugu (nécessite une connexion dédiée).
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "shugu" <<-EOSQL
    CREATE EXTENSION IF NOT EXISTS vector;
    CREATE EXTENSION IF NOT EXISTS pg_trgm;
EOSQL
