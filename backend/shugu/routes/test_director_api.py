"""Route de test Director — Phase E4 (north star demo).

POST /api/test/director/trigger

Permet aux tests E2E Playwright de déclencher un `TriggerEvent` Director
sans ouvrir un WebSocket visitor ni dépendre d'un vrai chat. Utile pour
valider le pipeline end-to-end (trigger → orchestrator → workers →
broadcast → viewer-adapter) dans un environnement CI sans traffic réel.

# Sécurité

- **Double gate** : `settings.test_triggers_enabled=False` par défaut
  + `require_operator()` (JWT cookie). Un de ces deux checks suffit à
  bloquer — les deux ensemble garantissent qu'un attaquant extérieur ne
  peut pas saturer le LLM via cette route en prod.
- **Payload validé** : seul le `kind` in `TriggerKind` est accepté.
  Le `payload` est un dict libre mais la taille est bornée à 256 chars
  par valeur pour éviter l'injection dans les prompts.
- **OFF par défaut** : `SHUGU_TEST_TRIGGERS_ENABLED` non setée = 404.
  Il ne faut PAS ajouter ce flag au `.env` prod.

# Utilisation CI

```bash
# Lancer le backend avec le flag
SHUGU_DIRECTOR_ENABLED=true SHUGU_TEST_TRIGGERS_ENABLED=true uvicorn ...

# Déclencher un trigger depuis Playwright APIRequestContext
POST /api/test/director/trigger
Cookie: shugu_access=<operator_jwt>
{"kind": "vip_arrival", "payload": {"sender": "spoukie"}}
```
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from ..auth.dependencies import require_operator
from ..config import Settings, get_settings
from ..director.triggers import TriggerEvent, TriggerKind, get_trigger_bus

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/test/director", tags=["test-director"])

# Taille max d'une valeur de payload pour éviter les prompts XXL injectés.
_PAYLOAD_VALUE_MAX_LEN = 256


class TriggerRequest(BaseModel):
    """Body du POST /api/test/director/trigger."""

    kind: TriggerKind = Field(
        description="Kind du trigger à publier (vip_arrival, chat, scene_change, …).",
    )
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description="Payload libre du trigger (ex: {'sender': 'Spoukie'}).",
    )

    @field_validator("payload", mode="before")
    @classmethod
    def _sanitize_payload(cls, value: Any) -> Any:
        """Sanitise les valeurs du payload — limite à 256 chars par valeur string."""
        if not isinstance(value, dict):
            return value
        sanitized: dict[str, Any] = {}
        for k, v in value.items():
            if isinstance(v, str) and len(v) > _PAYLOAD_VALUE_MAX_LEN:
                v = v[:_PAYLOAD_VALUE_MAX_LEN]
            sanitized[str(k)[:64]] = v
        return sanitized


@router.post("/trigger", status_code=202)
async def post_test_director_trigger(
    body: TriggerRequest,
    request: Request,
    settings: Settings = Depends(get_settings),
    _operator=Depends(require_operator),
) -> dict:
    """Publie un TriggerEvent Director pour les tests E2E Playwright.

    Retourne 404 si `test_triggers_enabled=False` (défaut). Retourne 202
    Accepted si le trigger a été publié sur le bus (l'orchestration est
    asynchrone — pas de garantie que le tick est terminé à la réponse).

    Args:
        body: kind + payload du trigger à publier.

    Returns:
        dict avec status + kind publié.

    Raises:
        404: si `settings.test_triggers_enabled` est False.
        401/403: si l'opérateur n'est pas authentifié.
    """
    if not settings.test_triggers_enabled:
        raise HTTPException(
            status_code=404,
            detail="Route indisponible (SHUGU_TEST_TRIGGERS_ENABLED non activé).",
        )

    if not settings.director_enabled:
        raise HTTPException(
            status_code=503,
            detail="Director désactivé (SHUGU_DIRECTOR_ENABLED=false).",
        )

    bus = get_trigger_bus()
    event = TriggerEvent(kind=body.kind, payload=body.payload)

    try:
        await bus.publish(event)
    except Exception as exc:
        log.warning(
            "test_director.trigger_publish_failed",
            extra={"kind": body.kind, "error": repr(exc)},
        )
        raise HTTPException(status_code=500, detail="Erreur lors de la publication du trigger.") from exc

    log.info(
        "test_director.trigger_published",
        extra={"kind": body.kind, "payload": body.payload},
    )
    return {"status": "accepted", "kind": body.kind, "payload": body.payload}
