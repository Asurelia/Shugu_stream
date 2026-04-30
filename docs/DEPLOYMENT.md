# Déploiement — Stack Docker (Phase 8.1)

Ce document couvre le démarrage de la stack dev locale complète via Docker Compose.  
Pour le lancement bare-metal Windows, voir `LAUNCHER.md`.

---

## Prérequis

| Outil | Version minimale | Notes |
|---|---|---|
| Docker Engine | 24+ | Docker Desktop 4.x sur Windows/macOS |
| Docker Compose | V2 (plugin) | `docker compose` (sans tiret) |
| `git` | — | pour cloner le repo |

---

## Mise en place initiale

### 1. Copier et remplir le fichier d'environnement

```bash
cp .env.example .env
```

Editer `.env` et renseigner **au minimum** :

| Variable | Description |
|---|---|
| `SHUGU_JWT_SECRET` | Secret HS256 opérateur — `openssl rand -hex 32` |
| `OPERATOR_USERNAME` | Login opérateur |
| `OPERATOR_PASSWORD_HASH` | Hash bcrypt — voir commentaire dans `.env.example` |
| `USER_JWT_SECRET` | Secret JWT self-service — `openssl rand -hex 32` |
| `MINIMAX_API_KEY` | Clé API MiniMax (LLM + TTS primaire) |
| `POSTGRES_PASSWORD` | Mot de passe superuser postgres (défaut : `shugu_dev_password`) |

Les variables `SHUGU_REDIS_URL`, `SHUGU_POSTGRES_DSN` et `EVENT_BUS_MODE` sont
**surchargées automatiquement** par `docker-compose.yml` pour la communication
container-à-container — ne pas les modifier dans `.env` pour la stack Docker.

### 2. Démarrer la stack

```bash
docker compose up -d
```

Cela démarre : `redis` → `postgres` → `backend` → `frontend`.  
Chaque service attend que le précédent soit **healthy** (healthcheck) avant de
démarrer — pas de race condition.

### 3. Lancer les migrations Alembic (une seule fois, ou après chaque PR DB)

```bash
docker compose run --rm backend alembic upgrade head
```

> **Pourquoi manuel ?** Le backend démarre sans migrations pour éviter qu'un
> mauvais `alembic upgrade` plante toute la stack. Ce one-shot est idempotent :
> si les tables existent déjà, rien ne se passe.

### 4. Vérifier que tout est up

```bash
docker compose ps
```

Tous les services doivent afficher `healthy` ou `running`.

---

## Utilisation courante

### Logs en temps réel

```bash
docker compose logs -f backend
docker compose logs -f frontend
docker compose logs -f          # tous les services
```

### Healthcheck backend

```bash
curl http://localhost:8701/health
```

Réponse attendue : `{"status": "ok"}` (ou équivalent).

### Frontend

Ouvrir `http://localhost:3005` dans le navigateur.

### Arrêter la stack

```bash
docker compose down             # arrête et supprime les containers
docker compose down -v          # idem + supprime les volumes (reset complet)
```

---

## LiveKit (profil optionnel `vip`)

LiveKit n'est pas démarré par défaut. Pour l'activer :

```bash
# Renseigner dans .env :
# LIVEKIT_URL=<url livekit>  (voir commentaire dans .env.example)
# LIVEKIT_API_KEY=...
# LIVEKIT_API_SECRET=...

docker compose --profile vip up -d
```

> En production, LiveKit doit être protégé par TLS (wss://).  
> En dev Docker interne, le service écoute sur le réseau bridge — ne pas
> l'exposer publiquement sans TLS.

---

## Distinction ops/docker-compose.yml vs docker-compose.yml

| Fichier | Rôle |
|---|---|
| `docker-compose.yml` (racine) | Stack complète dev : redis + postgres + backend + frontend + livekit optionnel |
| `ops/docker-compose.yml` | Redis seul — utilisé par le launcher Windows `Shugu-Start.cmd` pour dev bare-metal |

Ne pas confondre les deux. Le launcher Windows (`Shugu-Start.cmd`) utilise
`ops/docker-compose.yml` et démarre backend + frontend en processus natifs.

---

## Migration Alembic dans le container

```bash
# Voir l'état des migrations
docker compose run --rm backend alembic current

# Appliquer toutes les migrations en attente
docker compose run --rm backend alembic upgrade head

# Rollback d'une migration
docker compose run --rm backend alembic downgrade -1
```

---

## Rebuild après modification du code

```bash
# Rebuild uniquement le backend (ex: après modification Python)
docker compose build backend
docker compose up -d backend

# Rebuild uniquement le frontend
docker compose build frontend
docker compose up -d frontend

# Rebuild tout
docker compose build
docker compose up -d
```

---

## Troubleshooting fréquent

### Backend crashe au démarrage avec `ip_hash_salt` error

`SHUGU_ENV=dev` doit être dans `.env` (ou surcharge docker-compose.yml).  
En mode `production`, `IP_HASH_SALT` est obligatoire.

### `alembic upgrade head` échoue avec `role "shugu" does not exist`

Le script `ops/scripts/init-postgres.sh` crée le rôle `shugu` uniquement à la
**première initialisation du volume**. Si le volume `shugu_postgres` existait
avant (avec une autre config), détruisez-le :

```bash
docker compose down -v
docker compose up -d postgres
docker compose run --rm backend alembic upgrade head
```

### Backend ne démarre pas : `connection refused` Redis ou Postgres

Vérifier que les healthchecks sont passés :

```bash
docker compose ps
```

Si `redis` ou `postgres` affiche `unhealthy`, consulter leurs logs :

```bash
docker compose logs redis
docker compose logs postgres
```

### `CREATE EXTENSION vector` échoue

L'image `pgvector/pgvector:pg16` inclut pgvector nativement. Si vous utilisez
une autre image Postgres, installez pgvector manuellement :

```bash
apt-get install postgresql-16-pgvector   # Debian/Ubuntu
```

### Frontend `npm start` échoue (port 3005 déjà utilisé)

```bash
docker compose stop frontend
# Libérer le port 3005 localement, puis :
docker compose up -d frontend
```

---

## Variables d'environnement — référence complète

Voir `.env.example` à la racine du repo — chaque variable est documentée avec
sa description, valeur par défaut et commande de génération du secret.
