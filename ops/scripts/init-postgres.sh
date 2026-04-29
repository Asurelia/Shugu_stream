#!/bin/bash
# ops/scripts/init-postgres.sh
#
# Initialisation pgvector pour le container shugu-postgres.
# Monté dans /docker-entrypoint-initdb.d/ — exécuté une seule fois à la
# première création du volume (quand PGDATA est vide).
#
# Crée :
#   - La base de données "shugu"
#   - Le rôle "shugu" (owner de la base, mot de passe depuis POSTGRES_PASSWORD)
#   - Les extensions vector (pgvector) et pg_trgm (recall mémoire Phase 1)
#
# Note : le superuser postgres peut toujours se connecter pour la maintenance ;
# l'application se connecte en tant que "shugu" (voir SHUGU_POSTGRES_DSN).
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    -- Role applicatif (mot de passe positionné via POSTGRES_PASSWORD si désiré,
    -- mais pour dev local on laisse la connexion par trust depuis le réseau Docker).
    DO \$\$
    BEGIN
        IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'shugu') THEN
            CREATE ROLE shugu LOGIN;
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
