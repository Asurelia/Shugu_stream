"""user_accounts operator flag — AUTH-1 sprint

Revision ID: 0012_user_operator_flag
Revises: 0011_compactor_facts
Create Date: 2026-05-09 15:00:00.000000

## Colonne ajoutée à `user_accounts`

Ajoute `is_operator BOOLEAN NOT NULL DEFAULT FALSE` pour unifier le login
operator + user_account en un seul flow (Option B — double cookie).

### Contexte

Avant cette migration, l'authentification operator utilisait exclusivement les
variables d'env `OPERATOR_USERNAME` + `OPERATOR_PASSWORD_HASH` (legacy path).
Les `user_accounts` (membres + VIPs) avaient leur propre flow via
`/api/account/login` → cookie `shugu_user_access`.

Le bug UX : les membres ne pouvaient pas activer voice-body car `voiceWiringActive`
était gaté sur l'existence d'un cookie operator. Un user créé via `/account/register`
ne pouvait JAMAIS obtenir ce cookie.

### Solution

Le flag `is_operator` permet à un admin (via CLI ou route admin) de promouvoir
un user_account comme operator. Le login unifié (`POST /auth/login`) émet alors
DEUX cookies : `shugu_access` (operator JWT) + `shugu_user_access` (user JWT),
donnant accès simultané à voice-body ET aux fonctionnalités profil user.

### Colonne

- `is_operator` BOOLEAN NOT NULL DEFAULT FALSE
  - NULL sur les rows existantes → server_default="false" backfille toutes
  - Index partiel `idx_user_operator` sur `(is_operator) WHERE is_operator = true`
    (Postgres uniquement — la majorité des users seront FALSE, l'index est
    très sélectif et accélère la query "qui sont les operators ?")

### Compatibilité

Migration backward-compat : la colonne a un server_default, aucun impact sur
les rows existantes. Le path legacy (env hash) reste inchangé pour compat.

### Bootstrap

Après merge, l'admin run :
  python -m shugu.cli.promote_operator <username>
pour promouvoir son compte user_account en operator.

Voir `backend/shugu/cli/promote_operator.py` + `docs/specs/auth.md`.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0012_user_operator_flag"
down_revision: Union[str, None] = "0011_compactor_facts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1) Ajoute la colonne is_operator avec server_default pour backfill existing rows.
    op.add_column(
        "user_accounts",
        sa.Column(
            "is_operator",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    # 2) Index partiel Postgres-only via raw SQL (Alembic ne génère pas fiablement
    #    les index partiels avec clause WHERE composée — cf. pattern migration 0011).
    #    La majorité des users aura is_operator=FALSE. L'index est ultra-sélectif :
    #    contient seulement les rows TRUE → très petit, très rapide.
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_user_operator "
        "ON user_accounts (is_operator) "
        "WHERE is_operator = true"
    )


def downgrade() -> None:
    # Suppression index d'abord (dépendant de la colonne).
    op.execute("DROP INDEX IF EXISTS idx_user_operator")

    # Suppression colonne.
    op.drop_column("user_accounts", "is_operator")
