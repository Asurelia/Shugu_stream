---
date: 2026-05-03
status: open
severity: medium
discovered_during: PR1 backend Hermes removal validation
related_files:
  - backend/tests/unit/test_world_ws.py
---

## Résumé

Le test `tests/unit/test_world_ws.py::test_valid_token_connect_and_receive_world_delta` hang indéfiniment (>5 min) sur Python 3.13 + pytest-asyncio 1.0.0, avant ET après le PR de suppression Hermes. Confirmé sur `main` (b398ce9) sans aucune modif.

## Symptôme

```
tests/unit/test_world_ws.py::test_connect_without_token_closes_4401 PASSED
tests/unit/test_world_ws.py::test_connect_with_invalid_token_closes_4401 PASSED
tests/unit/test_world_ws.py::test_valid_token_connect_and_receive_world_delta
[hang infini]
```

## Cause probable

Le test mélange `TestClient.websocket_connect()` (synchrone) avec `asyncio.get_event_loop().run_until_complete(...)` (l.120-122) :

```python
with client.websocket_connect(f"/ws/world?token={token}") as ws:
    asyncio.get_event_loop().run_until_complete(
        event_bus.publish("world.delta", {"avatar_pose": "wave"})
    )
    raw = ws.receive_text()
```

En Python 3.13 :
- `asyncio.get_event_loop()` ne crée plus implicitement de boucle si aucune n'existe — émet `DeprecationWarning` et peut retourner une boucle dans un état inattendu
- Avec `pytest-asyncio` mode `auto`, la boucle gérée par pytest peut être différente de celle utilisée par TestClient (qui spawne son propre thread/loop interne via Starlette)
- `run_until_complete` sur la mauvaise boucle bloque sans erreur

## Impact

- 1 test sur ~595 hang. Skip via `--deselect tests/unit/test_world_ws.py::test_valid_token_connect_and_receive_world_delta` permet de finir la suite.
- Tous les autres tests passent (confirmé : G1+G2+G3+G4+G5 Hermes removal — 0 régression dans le reste du suite).
- Le code de prod `routes/world_ws.py` n'est pas en cause — c'est uniquement le pattern de test qui est fragile.

## Action recommandée (sprint séparé)

Refactorer le test en async natif (compatible pytest-asyncio mode auto) :

```python
@pytest.mark.asyncio
async def test_valid_token_connect_and_receive_world_delta(
    settings, event_bus: InProcessEventBus,
) -> None:
    token = _issue_token(settings, "alice")
    async with httpx.AsyncClient(...) as client:
        async with aconnect_ws("/ws/world?token=" + token, client) as ws:
            await event_bus.publish("world.delta", {"avatar_pose": "wave"})
            raw = await ws.receive_text()
```

Alternative : utiliser `anyio.from_thread.run_sync` pour bridger le test sync vers la boucle pytest-asyncio.

## Pourquoi pas dans le PR1 Hermes-removal

Hors scope : la migration Hermes ne touche pas `world_ws.py` ni les patterns de test WS. Mélanger le fix dans le PR pollue le diff et complique la review/bisect.
