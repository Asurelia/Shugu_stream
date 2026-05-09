"""JWT issue/verify/refresh pour le viewer (avatar bridge) — Sprint D PR D-3.

Distinct des JWT operator (`jwt_tokens.py`) et user (`user_tokens.py`) :
secret séparé, claim `session_id` signé, TTL court (5 min par défaut),
refresh-rotation pour les sessions longues.

Spec : ``docs/specs/2026-05-08-voice-body-pipeline-design.md`` §6.3 (Sécurité).

Claims signés
-------------
- ``iss``         : ``"shugu-voice"`` — issuer fixe pour valider qu'un token
  user/operator ne peut pas être confondu avec un viewer token.
- ``sub``         : ``user_id`` (ULID) — propriétaire de la session.
- ``session_id``  : slug de session voice (ex: ``"voice-sess-abc123"``). Le
  WS ``/viewer/events`` filtre les events dont le payload mentionne un
  ``session_id`` différent — ça empêche un user A d'écouter la session de B
  même si on lui forge un token signé par notre secret.
- ``iat``         : epoch seconds — émission.
- ``exp``         : epoch seconds — expiration (= ``iat + ttl_seconds``).
- ``typ``         : ``"viewer-access"`` — discriminant fort. Un token avec
  notre secret mais ``typ`` différent est rejeté (defense-in-depth contre
  un re-purposing accidentel).

Refresh flow
------------
Le frontend appelle ``POST /voice/token/refresh`` à T-60s avant ``exp`` pour
obtenir un nouveau token sans réauth user. La fonction ``refresh_viewer_token``
accepte un token dont ``exp`` est dans le passé tant que ``now - exp <=
viewer_token_refresh_grace_s`` (défaut 120s) — au-delà, le frontend doit
faire un full handshake via ``POST /voice/token`` (auth user normale).

Cette grace window protège contre :
- les latences réseau / clock-drift au moment du refresh ;
- un refresh ratée à cause d'un transient 5xx (le client retry à T+10s).

Anti-replay
-----------
La grace window est volontairement courte (2 min). Au-delà, un attaquant qui
aurait stolen un token expiré ne peut plus l'échanger — il doit voler un
token frais ET son contexte d'auth user pour faire mal.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass

import jwt
from fastapi import HTTPException

from ..config import Settings
from ..core.errors import AuthError

ALGO = "HS256"
ISSUER = "shugu-voice"
TYP = "viewer-access"


@dataclass(slots=True, frozen=True)
class ViewerTokenClaims:
    """Claims décodés d'un viewer JWT, après vérification de signature.

    Immutable (``frozen=True``) — un caller qui veut muter doit copier.

    ``jti`` (JWT ID) : UUID4 généré à l'issue. Sert de discriminant unique
    pour le rate limit "1 connexion active par token" — un nouveau ``jti``
    est émis à chaque ``issue_viewer_token`` ET à chaque ``refresh_viewer_token``,
    garantissant qu'un token actif et son refresh ont des slots distincts.
    """

    sub: str          # user_id
    session_id: str   # slug de la session voice
    iat: int          # epoch seconds — émission
    exp: int          # epoch seconds — expiration
    jti: str          # UUID4 — discriminant rate limit "1 conn par token"
    iss: str = ISSUER
    typ: str = TYP


def issue_viewer_token(
    settings: Settings,
    *,
    user_id: str,
    session_id: str,
    ttl_seconds: int | None = None,
) -> str:
    """Émet un nouveau viewer JWT pour ``(user_id, session_id)``.

    Paramètres
    ----------
    settings :
        Pour lire ``viewer_jwt_secret`` et ``viewer_token_ttl_s`` (défaut TTL).
    user_id :
        ULID du user propriétaire (claim ``sub``).
    session_id :
        Slug de la session voice (claim ``session_id``). Doit être non-vide
        — un token sans session_id serait inutile (filter cross-session
        impossible).
    ttl_seconds :
        Override du TTL par défaut. Utile pour tests ou revocation rapide.

    Lève
    ----
    AuthError :
        Si ``viewer_jwt_secret`` est vide (mauvaise config production).
    ValueError :
        Si ``user_id`` ou ``session_id`` est vide (programming error).
    """
    if not settings.viewer_jwt_secret:
        raise AuthError("viewer_jwt_secret not configured")
    if not user_id:
        raise ValueError("user_id required")
    if not session_id:
        raise ValueError("session_id required")

    now = int(time.time())
    ttl = ttl_seconds if ttl_seconds is not None else settings.viewer_token_ttl_s
    jti = uuid.uuid4().hex
    payload = {
        "iss": ISSUER,
        "sub": user_id,
        "session_id": session_id,
        "iat": now,
        "exp": now + ttl,
        "typ": TYP,
        "jti": jti,
    }
    return jwt.encode(payload, settings.viewer_jwt_secret, algorithm=ALGO)


def verify_viewer_token(
    token: str,
    *,
    settings: Settings,
) -> ViewerTokenClaims:
    """Vérifie un viewer JWT et retourne ses claims.

    Lève ``HTTPException(401)`` (PAS ``AuthError``) — le caller des routes
    REST/WS peut directement laisser remonter sans wrapper. Ce choix diffère
    de ``jwt_tokens.verify`` (qui retourne ``AuthError``) : viewer auth est
    toujours utilisé en bord de FastAPI, jamais en chaîne d'adapters
    interne, donc HTTPException simplifie l'usage.

    Vérifications :

    1. Signature HS256 contre ``settings.viewer_jwt_secret``.
    2. ``iss == "shugu-voice"`` (PAS le issuer operator/user).
    3. ``exp`` non dans le passé.
    4. ``typ == "viewer-access"`` (rejette les autres types signés avec
       le même secret par erreur).
    5. ``session_id`` présent et non-vide.

    Retourne
    --------
    ViewerTokenClaims
    """
    if not settings.viewer_jwt_secret:
        # Fail-fast plutôt que de tenter un decode avec clé vide.
        raise HTTPException(
            status_code=401, detail="viewer auth not configured",
        )

    try:
        payload = jwt.decode(
            token,
            settings.viewer_jwt_secret,
            algorithms=[ALGO],
            issuer=ISSUER,
            options={"require": ["exp", "iat", "sub", "session_id", "jti"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(
            status_code=401, detail="token expired",
        ) from exc
    except jwt.InvalidTokenError as exc:
        # Couvre : mauvais issuer, signature invalide, token malformé,
        # claim required manquante.
        raise HTTPException(
            status_code=401, detail="invalid token",
        ) from exc

    if payload.get("typ") != TYP:
        raise HTTPException(
            status_code=401,
            detail=f"wrong token type: expected {TYP}",
        )

    session_id = payload.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        raise HTTPException(
            status_code=401, detail="missing session_id claim",
        )
    jti = payload.get("jti")
    if not isinstance(jti, str) or not jti:
        raise HTTPException(
            status_code=401, detail="missing jti claim",
        )

    return ViewerTokenClaims(
        sub=str(payload["sub"]),
        session_id=session_id,
        iat=int(payload["iat"]),
        exp=int(payload["exp"]),
        jti=jti,
    )


def refresh_viewer_token(
    old_token: str,
    *,
    settings: Settings,
) -> str:
    """Re-émet un viewer JWT avec ``session_id`` préservé et TTL renouvelé.

    Accepte les tokens dont ``exp`` est dans le passé tant que ``now - exp <=
    viewer_token_refresh_grace_s`` (anti-replay window). Au-delà, lève
    ``HTTPException(401)``.

    Le ``session_id`` du new token est forcé identique à celui du old (un user
    qui veut switcher de session doit re-passer par ``POST /voice/token``).

    Lève ``HTTPException(401)`` :
    - Token malformé / signature invalide / mauvais issuer / mauvais typ ;
    - Token expiré depuis plus que la grace window ;
    - viewer_jwt_secret non configuré.
    """
    if not settings.viewer_jwt_secret:
        raise HTTPException(
            status_code=401, detail="viewer auth not configured",
        )

    # On désactive verify_exp pour pouvoir lire les claims d'un token
    # récemment expiré. Le check `now - exp <= grace` est fait manuellement
    # ci-dessous. On ne require PAS jti ici (les tokens legacy issus avant
    # l'ajout de jti pourraient être en circulation au moment du déploiement) ;
    # mais on ré-émet avec un jti frais via issue_viewer_token de toute façon.
    try:
        payload = jwt.decode(
            old_token,
            settings.viewer_jwt_secret,
            algorithms=[ALGO],
            issuer=ISSUER,
            options={
                "require": ["exp", "iat", "sub", "session_id"],
                "verify_exp": False,
            },
        )
    except jwt.InvalidTokenError as exc:
        raise HTTPException(
            status_code=401, detail="invalid token",
        ) from exc

    if payload.get("typ") != TYP:
        raise HTTPException(
            status_code=401,
            detail=f"wrong token type: expected {TYP}",
        )

    session_id = payload.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        raise HTTPException(
            status_code=401, detail="missing session_id claim",
        )

    # Anti-replay : si le token a expiré depuis plus que grace, on refuse.
    # Si exp est dans le futur (token encore valide), grace est trivialement
    # respectée — pas de check supplémentaire.
    now = int(time.time())
    exp = int(payload["exp"])
    if exp < now:
        elapsed_since_expiry = now - exp
        if elapsed_since_expiry > settings.viewer_token_refresh_grace_s:
            raise HTTPException(
                status_code=401,
                detail=(
                    f"token expired {elapsed_since_expiry}s ago, "
                    f"grace window is {settings.viewer_token_refresh_grace_s}s"
                ),
            )

    user_id = str(payload["sub"])
    return issue_viewer_token(
        settings,
        user_id=user_id,
        session_id=session_id,
        # ttl_seconds=None → utilise le défaut settings (cohérent avec issue).
    )


__all__ = [
    "ISSUER",
    "TYP",
    "ViewerTokenClaims",
    "issue_viewer_token",
    "verify_viewer_token",
    "refresh_viewer_token",
]
