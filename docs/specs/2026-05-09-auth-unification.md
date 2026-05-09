# Spec — Auth Unification (AUTH-1 sprint)

- **Date** : 2026-05-09
- **Auteur** : Claude (Sonnet 4.6) en collaboration avec Sylvain
- **Status** : Implémenté, tests verts, PR ouverte
- **Sprint** : AUTH-1 — Unified operator + user_account login

## 1. Contexte & problème

### 1.1. Deux systèmes d'auth parallèles

Avant ce sprint, Shugu_stream avait deux systèmes d'authentification incompatibles :

| Système | Endpoint | Cookie | Cookie name |
|---|---|---|---|
| Opérateur legacy | `POST /auth/login` | JWT opérateur | `shugu_access` |
| User account | `POST /api/account/login` | JWT user | `shugu_user_access` |

### 1.2. Bug UX bloquant

`voiceWiringActive = !!operator` dans le root `_client.tsx` lit l'état depuis `GET /auth/me`, qui exige le cookie `shugu_access` (JWT opérateur). Les users enregistrés via `/account/register` ne pouvaient jamais activer voice-body : ils n'ont jamais de cookie `shugu_access`.

**Résultat** : un streamer qui crée un compte normal → voice-body reste éteint pour toujours, sans message d'erreur clair.

## 2. Solution — Option B : Double cookie pour les opérateurs user_account

### 2.1. Principe

Un seul endpoint de login unifié gère tous les cas :

```
POST /auth/login
{username_or_email, password}
```

**Étape 1 — Legacy env hash (autorité maximale)**
- Actif quand `OPERATOR_USERNAME` + `OPERATOR_PASSWORD_HASH` sont configurés dans l'env
- Username exact requis → 401 immédiat si pas le bon username
- Password correct → 200 + cookie `shugu_access` (JWT opérateur) + `is_operator=true`
- Password incorrect → 401 immédiat
- **Pas de fallthrough vers user_accounts** — frontière de sécurité stricte

**Étape 2 — User accounts (fallback, quand env non configuré)**
- Cherche `username` ou `email` dans `user_accounts`
- `is_operator=false` → 200 + cookie `shugu_user_access` seulement
- `is_operator=true` → 200 + **DEUX cookies** (`shugu_access` + `shugu_user_access`)
- Email non vérifié → 403 `"verify email first"`

### 2.2. Réponse unifiée

```json
{
  "username": "spoukie",
  "role": "operator",
  "is_operator": true
}
```

### 2.3. Workflow complet

```
register → POST /account/register (username, email, password)
         → email de vérification envoyé
         → GET /account/verify-email?token=<token>
         → compte activé (email_verified_at = now)

promote  → python -m shugu.cli.promote_operator <username>
         → is_operator = true dans user_accounts
         → (run en local sur le serveur, pas d'auth requise)

login    → POST /auth/login (username_or_email, password)
         → si is_operator=true : deux cookies + redirect /
         → si is_operator=false : cookie user + redirect /account/profile

access   → GET /auth/me (lit le cookie shugu_access)
         → voiceWiringActive = true (opérateur)
```

## 3. Migration DB — Alembic 0012

Fichier : `backend/alembic/versions/0012_user_accounts_operator_flag.py`

```sql
-- upgrade
ALTER TABLE user_accounts ADD COLUMN is_operator BOOLEAN NOT NULL DEFAULT false;
CREATE INDEX IF NOT EXISTS idx_user_operator ON user_accounts (is_operator) WHERE is_operator = true;

-- downgrade
DROP INDEX IF EXISTS idx_user_operator;
ALTER TABLE user_accounts DROP COLUMN is_operator;
```

Appliquer sur la DB réelle :
```bash
python -m alembic upgrade head
```

## 4. CLI promote_operator

### Usage

```bash
python -m shugu.cli.promote_operator <username>
```

### Comportement

| Cas | Sortie | Exit code |
|---|---|---|
| User promu avec succès | `[ok] 'spoukie' is now an operator.` | 0 |
| User déjà opérateur | `[ok] 'spoukie' is already an operator. No change.` | 0 |
| User non trouvé | `[error] User 'spoukie' not found.` (stderr) | 1 |
| Erreur DB | `[error] DB error: <msg>` (stderr) | 2 |

### Caractéristiques

- Idempotent — relancer sur un opérateur existant ne fait rien
- Pas d'auth requise — à exécuter localement sur le serveur uniquement
- Lit la config DB depuis `ops/env/.env` ou `SHUGU_ENV_FILE`
- N'envoie aucune notification

### Première utilisation (bootstrap)

Quand aucun opérateur n'existe en DB, le `OPERATOR_PASSWORD_HASH` legacy reste disponible pour une première connexion. Une fois connecté et le compte `user_account` créé :

```bash
# Sur le serveur (après avoir créé un compte via /account/register + vérif email)
python -m shugu.cli.promote_operator spoukie
```

Puis se reconnecter à `/account/login`. Voice-body s'active immédiatement.

## 5. Frontend

### Route /login → redirect

`/login` (ancienne URL) redirige vers `/account/login` via `next/navigation.redirect()`.

### Page /account/login

- Soumet à `POST /auth/login` (endpoint unifié)
- Si `is_operator=true` → `router.replace("/")`  — root active `voiceWiringActive`
- Si `is_operator=false` → `router.replace("/account/profile")`
- Gestion d'erreurs : 403 "verify email" → CTA resend, 401 → message générique, 429 → rate limit

### Service shuguClient.ts

```typescript
export type AuthResponse = {
  username: string;
  role: string;
  is_operator: boolean;
};

login(username, password): Promise<{ data: AuthResponse | null; error: string | null }>
fetchAuthStatus(): Promise<AuthResponse | null>  // GET /auth/me
```

## 6. Endpoints impactés

| Endpoint | Changement |
|---|---|
| `POST /auth/login` | Unifié — supporte user_accounts (step 2) |
| `GET /auth/me` | Retourne `is_operator` dans la réponse |
| `POST /auth/admin/promote-operator` | Nouveau — promote via API (requiert JWT opérateur) |
| `GET /account/me` | Retourne `is_operator` dans `MeResponse` |
| `POST /api/account/login` | Inchangé (conservé pour compat rétro) |

## 7. Dépréciation du legacy OPERATOR_PASSWORD_HASH

L'env var `OPERATOR_PASSWORD_HASH` (+ `OPERATOR_USERNAME`) reste fonctionnelle et prioritaire, mais est **dépréciée**. La migration recommandée :

1. Créer un compte via `POST /account/register`
2. Vérifier l'email
3. `python -m shugu.cli.promote_operator <username>`
4. Retirer `OPERATOR_USERNAME` et `OPERATOR_PASSWORD_HASH` de l'env
5. Se reconnecter via `/account/login`

Le fallback legacy sera supprimé dans un sprint futur (à définir).

## 8. Tests

15 nouveaux tests dans `backend/tests/integration/test_auth_unification.py` :

| Test | Description |
|---|---|
| `test_login_legacy_operator_ok` | Env configuré, bon username/password → 200 + is_operator=true |
| `test_login_legacy_wrong_password` | Env configuré, mauvais password → 401 |
| `test_login_legacy_wrong_username` | Env configuré, mauvais username → 401 (pas de fallthrough) |
| `test_login_user_account_member_ok` | Pas d'env, user normal → 200 + is_operator=false |
| `test_login_user_account_operator_ok` | Pas d'env, user is_operator=true → 200 + is_operator=true |
| `test_login_user_account_email_not_verified` | Pas d'env, email non vérifié → 403 |
| `test_login_user_account_not_found` | Pas d'env, user inconnu → 401 |
| `test_login_user_account_inactive` | Pas d'env, compte inactif → 401 |
| `test_login_by_email` | Peut se connecter avec l'email (pas le username) |
| `test_promote_operator_route` | `POST /auth/admin/promote-operator` → is_operator=true |
| `test_promote_operator_cli_ok` | CLI → exit 0 + message ok |
| `test_promote_operator_cli_already_operator` | CLI idempotent → exit 0 |
| `test_promote_operator_cli_user_not_found` | CLI user inconnu → exit 1 |
| `test_account_me_returns_is_operator` | `GET /account/me` → champ is_operator présent |
| `test_auth_me_returns_is_operator` | `GET /auth/me` → champ is_operator présent |
