# Pass 2 — Test Coverage Gap Analysis
**Date** : 2026-05-01
**Périmètre** : `backend/shugu/` vs `backend/tests/`
**Méthode** : lecture statique du code — pas d'outil de couverture instrumenté
**Lignes de code de prod sans aucun test direct** : ~3 080 LOC réparties sur 13 modules

---

## Légende sévérité

| Niveau | Critère |
|--------|---------|
| **Critique** | Faille de sécurité ou perte de données exploitable sans tests |
| **Important** | Régression silencieuse probable, impact fonctionnel réel |
| **Mineur** | Fragilité de test, faux positif/négatif latent |

---

## Findings

---

### F01 — `jwt_tokens.verify()` : aucun test des chemins d'erreur auth
**Sévérité** : Critique
**Fichier** : `shugu/auth/jwt_tokens.py` (106 LOC)

`verify()` lève `AuthError` pour cinq conditions distinctes : signature expirée (`ExpiredSignatureError`), token malformé (`InvalidTokenError`), mauvais `token_type`, mauvais `role`, et JTI révoqué (lookup Redis). Aucun test unitaire n'existe. La fonction est utilisée comme gate d'accès sur toutes les routes WebSocket et REST opérateur.

**Chemins non couverts** :
- [ ] Token expiré → `AuthError` propagé correctement
- [ ] Token signé avec la mauvaise clé → `AuthError`
- [ ] `token_type="refresh"` présenté comme access token → rejet
- [ ] JTI présent dans Redis (révoqué) → rejet
- [ ] Token structurellement valide mais `role != "operator"` → rejet

---

### F02 — `user_tokens.py` : zéro test, surface VIP critique
**Sévérité** : Critique
**Fichier** : `shugu/auth/user_tokens.py` (133 LOC)

Gère les JWT self-service (rôles `member`/`vip`). La promotion VIP repose sur la claim `vip_active=True` dans le payload JWT. `require_vip()` dans `dependencies.py` fait `isinstance(identity, VIPIdentity)` — le seul chemin pour obtenir `VIPIdentity` passe par `user_tokens.verify()`. Un token forgé avec `vip_active=True` sur la signature publique n'est pas testée comme rejet.

**Chemins non couverts** :
- [ ] `user_jwt_secret` absent → `AuthError("user_jwt_secret not configured")`
- [ ] Token avec `role="operator"` présenté à `user_tokens.verify` → rejet
- [ ] `vip_active=False` → `MemberIdentity`, pas `VIPIdentity`
- [ ] `vip_active=True` → `VIPIdentity` correctement construite
- [ ] Token expiré → `AuthError`

---

### F03 — `dependencies.py` : `require_operator` et `require_vip` non testés
**Sévérité** : Critique
**Fichier** : `shugu/auth/dependencies.py` (161 LOC)

Les dépendances FastAPI `require_operator` et `require_vip` sont *overridées* dans les tests de routes (via `app.dependency_overrides`) mais leur logique interne n'est jamais exercée. `require_operator` importe `get_redis` depuis `shugu.app` à l'exécution pour contourner un cycle d'import — ce pattern d'import différé est un point de rupture silencieux.

**Chemins non couverts** :
- [ ] `require_operator` avec token valide Redis non-révoqué → `OperatorIdentity`
- [ ] `require_operator` avec JTI révoqué → HTTP 401
- [ ] `require_vip` avec `MemberIdentity` → HTTP 403
- [ ] `require_vip` avec `VIPIdentity` → accès accordé

---

### F04 — `routes/auth.py` : tous les endpoints opérateur non testés
**Sévérité** : Critique
**Fichier** : `shugu/routes/auth.py` (139 LOC)

`POST /auth/login`, `POST /auth/refresh`, `POST /auth/logout`, `GET /auth/me` — zéro test. Le flow login inclut une comparaison bcrypt, une persistance `OperatorSession` en DB, et l'émission d'une paire JWT. Le flow refresh révoque l'ancien JTI.

**Chemins non couverts** :
- [ ] Login avec mot de passe correct → cookies set + `OperatorSession` créée
- [ ] Login avec mauvais mot de passe → HTTP 401
- [ ] Refresh avec refresh token valide → nouvelle paire, ancien JTI révoqué
- [ ] Refresh avec access token (mauvais type) → rejet
- [ ] Logout → deux JTI révoqués, cookies effacés

---

### F05 — `routes/account.py` : flux self-service user complet non testé
**Sévérité** : Critique
**Fichier** : `shugu/routes/account.py` (~200 LOC estimés)

Enregistrement utilisateur, vérification email, login user, refresh, logout — tout le flux `member`/`vip` auto-service est non testé. Réutilise `user_tokens.py` (F02) et écrit dans la DB.

**Chemins non couverts** :
- [ ] `POST /account/register` avec email déjà existant → conflit (HTTP 409)
- [ ] `GET /account/verify-email` avec token invalide → rejet
- [ ] `POST /account/login` → cookies user + rôle `member`
- [ ] `POST /account/refresh` avec `vip_active` mis à jour par admin
- [ ] `GET /account/me` sans cookie → HTTP 401

---

### F06 — `adapters/injection_detector.py` : détecteur prompt-injection sans tests
**Sévérité** : Critique
**Fichier** : `shugu/adapters/injection_detector.py` (55 LOC)

`scan()` applique 11 regex avec poids 3–5. `aggregate_weight()` somme les poids. Un score ≥ 10 déclenche un auto-ban dans `moderation_basic.py`. Aucune assertion ne garantit que les patterns détectent ce qu'ils prétendent détecter ni qu'un tweak de regex ne fait pas sauter le seuil silencieusement.

**Chemins non couverts** :
- [ ] Texte neutre → score 0, aucun signal
- [ ] `"Ignore all previous instructions"` → score ≥ 10, auto-ban déclenché
- [ ] Pattern partiellement masqué (casse mixte, espaces) → seuil correct
- [ ] `aggregate_weight([])` → 0 sans exception

---

### F07 — `adapters/moderation_basic.py` : rate-limit et auto-ban non testés
**Sévérité** : Critique
**Fichier** : `shugu/adapters/moderation_basic.py` (144 LOC)

`check_ingress` couvre six chemins de rejet : texte vide, trop long, visiteur banni (Redis), rate-limit dépassé (rolling window Redis `LPUSH`/`LTRIM`/`LRANGE`), profanité, injection. Aucun test. Le module-level `_last_command_ts` dans `visitor_ws.py` (partagé implicitement) est un risque d'isolation, mais la logique de rate-limit Redis est elle-même sans test.

**Chemins non couverts** :
- [ ] Texte vide → `deny(reason="empty")`
- [ ] Texte > `max_length` → `deny(reason="too_long")`
- [ ] Visiteur dans Redis ban set → `deny(reason="banned")`
- [ ] N+1ème message dans fenêtre → `deny(reason="rate_limit")`
- [ ] Score injection ≥ 10 → `deny(reason="injection")` + écriture ban Redis

---

### F08 — `core/quota.py` : compteurs MiniMax Redis non testés
**Sévérité** : Important
**Fichier** : `shugu/core/quota.py` (166 LOC)

`QuotaTracker` effectue `INCRBY + EXPIRE` Redis pour deux fenêtres : jour UTC et tranche de 5 heures. Les clés sont calculées via `datetime.now(tz=timezone.utc)` — comportement timezone-dépendant aux frontières. Avertissement à 80 %, blocage à 100 %. Aucun test.

**Chemins non couverts** :
- [ ] Première charge → compteur = charge, TTL positionné
- [ ] Charge à 79 % → pas d'avertissement
- [ ] Charge à 80 % → warning loggé, requête non bloquée
- [ ] Charge à 100 % → `QuotaExceeded` levé
- [ ] Clé journalière change exactement à minuit UTC

---

### F09 — `pipeline/queue.py` : backpressure et priorité Redis non testés
**Sévérité** : Important
**Fichier** : `shugu/pipeline/queue.py` (104 LOC)

`RedisQueue.enqueue_pending` retourne `False` quand `ZCARD >= cap` (backpressure). Le score de priorité est `priority_tier * 10^13 + received_ns`. `pop_ready` fait un `base64.b64decode` sur `precomputed_audio` — sans test, une valeur non-base64 lèverait `binascii.Error` silencieusement.

**Chemins non couverts** :
- [ ] Enqueue jusqu'à `cap` puis `cap+1` → retourne `False`
- [ ] Deux enqueues avec tiers différents → pop retourne le tier haut en premier
- [ ] `precomputed_audio` présent et encodé → décodé correctement
- [ ] `precomputed_audio` absent → champ omis sans exception

---

### F10 — `pipeline/picker.py` : orchestration TTS série et barge-in non testés
**Sévérité** : Important
**Fichier** : `shugu/pipeline/picker.py` (354 LOC)

Contrôle le flux TTS : attente de la fin du son en cours (`CUSHION_MS = 800` hardcodé), barge-in via `_interrupt_event`, chemin streaming vs précompute. Les 354 LOC sont les plus critiques pour la QoS audio, et sont à zéro couverture.

**Chemins non couverts** :
- [ ] Barge-in pendant lecture → `_interrupt_event` set, track courante abandonnée
- [ ] Chemin précompute (`precomputed_audio` présent) vs streaming TTS
- [ ] File vide → `pop_ready` retourne `None`, picker attend sans busy-loop
- [ ] Erreur TTS adapter → fallback déclenché (ou propagation gérée)

---

### F11 — `core/body_control.py` : 732 LOC de schémas Pydantic v2 non testés
**Sévérité** : Important
**Fichier** : `shugu/core/body_control.py` (732 LOC)

Schémas `BodySayCall`, `BodyGestureCall`, etc. avec validation de whitelist via `frozenset`. `parse_call()` *silently drops* les appels inconnus. Les schémas changent fréquemment (ajout de paramètres Hermes) — sans tests, une régression de validation passe inaperçue jusqu'en production.

**Chemins non couverts** :
- [ ] `parse_call("say", {"text": "hello"})` → `BodySayCall` correct
- [ ] `parse_call("unknown_tool", {...})` → `None` retourné (pas d'exception)
- [ ] Paramètre hors whitelist → rejet Pydantic `ValidationError`
- [ ] `parse_call` avec champs manquants obligatoires → `ValidationError`

---

### F12 — `visitor_ws.py` : commandes `!wave`/`!dance` et backpressure non testés
**Sévérité** : Important
**Fichier** : `shugu/routes/visitor_ws.py` (283 LOC)

Les tests existants (`test_visitor_ws_senses.py`) couvrent uniquement `sense.chat`/`sense.raw`. La logique `_maybe_handle_command` (court-circuit LLM pour `!wave`, `!dance`, etc.) et la réponse `queue.rejected` quand `enqueue_pending` retourne `False` sont non testées. De plus, `_last_command_ts` est un dictionnaire de module — il persiste entre les tests exécutés dans le même processus.

**Chemins non couverts** :
- [ ] `!wave` → `enqueue_pending` appelé, cooldown positionné dans `_last_command_ts`
- [ ] `!wave` dans cooldown → rejeté silencieusement (pas de double-enqueue)
- [ ] `enqueue_pending` retourne `False` → WS reçoit `{"type": "queue.rejected"}`
- [ ] Isolation : `_last_command_ts` doit être réinitialisé entre les tests

---

### F13 — `core/mood.py` : machine d'état non-déterministe sans tests
**Sévérité** : Important
**Fichier** : `shugu/core/mood.py` (110 LOC)

`Mood.step(rng=None)` utilise `random.choices` — non-déterministe par défaut. Quatre matrices de transition conditionnées sur `time_since_input_s()` (clock wall time). Les tests de `test_action_parser.py` et `test_handlers.py` testent la validation du Literal `Mood`, pas la machine d'état elle-même.

**Chemins non couverts** :
- [ ] `step(rng=rng_seeded)` → transition déterministe testable
- [ ] Matrice "idle" (> 30 s sans input) vs matrice "engaged"
- [ ] `time_since_input_s()` avant tout input humain → valeur cohérente (pas `None`)
- [ ] Cycle complet : mood revient à `neutral` depuis n'importe quel état

---

### F14 — Routes admin (`admin.py`, `admin_users.py`) non testées
**Sévérité** : Important
**Fichiers** : `shugu/routes/admin.py`, `shugu/routes/admin_users.py`

Les endpoints `/api/admin/*` — consultation visiteurs, performances, gestion utilisateurs, promotion VIP — sont réservés à l'opérateur via `require_operator`. Aucun test ne vérifie que des non-opérateurs sont effectivement rejetés, ni que les requêtes DB admin fonctionnent.

**Chemins non couverts** :
- [ ] Accès sans token opérateur → HTTP 401/403
- [ ] `GET /api/admin/visitors` → liste paginée correcte
- [ ] Promotion VIP d'un utilisateur → `vip_active` positionné en DB

---

### F15 — `pipeline/body_router.py` : dispatch actions Hermes non testé
**Sévérité** : Important
**Fichier** : `shugu/pipeline/body_router.py`

`test_operator_ws_senses.py` passe `body_router=None` explicitement, contournant le router. Le dispatch réel (routing `BodySayCall` → TTS, `BodyGestureCall` → avatar) n'est couvert par aucun test.

**Chemins non couverts** :
- [ ] `route(BodySayCall(...))` → publie sur `tts.request`
- [ ] `route(BodyGestureCall(...))` → publie sur `avatar.gesture`
- [ ] Type inconnu → no-op ou log warning (pas d'exception)

---

### F16 — Adaptateurs TTS groupés (`tts_edge`, `tts_elevenlabs`, `tts_minimax`, `tts_fallback`) sans tests
**Sévérité** : Important
**Fichiers** : `shugu/adapters/tts_edge.py`, `tts_elevenlabs.py`, `tts_minimax.py`, `tts_fallback.py`

Aucun test pour les quatre adaptateurs TTS. `tts_fallback.py` est particulièrement risqué : c'est le dernier filet de sécurité du pipeline audio.

**Chemins non couverts** :
- [ ] Timeout réseau → exception propagée ou fallback activé
- [ ] Réponse API malformée → `ValueError` ou équivalent géré
- [ ] `tts_fallback` appelé quand adaptateur principal échoue → audio produit

---

### F17 — `routes/livekit_api.py` et `routes/hermes_state_api.py` non testés
**Sévérité** : Important
**Fichiers** : `shugu/routes/livekit_api.py`, `shugu/routes/hermes_state_api.py`

Endpoints LiveKit (génération token room) et état Hermes (état courant du brain Hermes) — zéro test. Un changement de signature LiveKit SDK casserait silencieusement.

**Chemins non couverts** :
- [ ] `POST /api/livekit/token` → token room valide retourné
- [ ] Accès Hermes state sans auth opérateur → rejet
- [ ] Hermes state quand brain inactif → réponse dégradée propre

---

### F18 — `test_memory_service_protocol.py:47` : assertion triviale
**Sévérité** : Mineur
**Fichier** : `tests/unit/test_memory_service_protocol.py` ligne 47

```python
assert MemoryService is not None
```

Cette assertion vérifie uniquement que l'import réussit. Elle ne teste aucun comportement du protocole. Elle compte dans le nombre de tests passants sans apporter de valeur de régression.

**Action** : remplacer par une assertion sur l'interface (méthodes requises du protocole via `hasattr` ou une vérification ABC).

---

### F19 — `test_director_orchestrator.py` : test d'attribut privé
**Sévérité** : Mineur
**Fichier** : `tests/unit/test_director_orchestrator.py` ligne 399

```python
assert orch._dispose is not None
```

Test de l'existence d'un attribut privé `_dispose` — fragile à tout refactoring interne. Ne teste pas que `dispose()` libère effectivement les ressources.

**Action** : remplacer par un test comportemental : appeler `dispose()` et vérifier que les souscriptions bus sont résiliées.

---

### F20 — Pipeline voix groupé : 989 LOC sans aucun test
**Sévérité** : Important
**Fichiers** : `shugu/pipeline/voice_duplex.py` (247), `pipeline/ambient.py` (360), `pipeline/hermes_task.py` (165), `pipeline/workers.py` (217)

Le pipeline voix (duplex STT/TTS LiveKit, ambiance sonore, task Hermes, workers de coordination) totalise 989 LOC sans aucune occurrence dans les tests. Ces modules gèrent la session audio temps-réel — une régression y est invisible jusqu'en stream live.

**Chemins non couverts** :
- [ ] `VoiceDuplex` : déconnexion LiveKit en cours de session → nettoyage propre
- [ ] `ambient.py` : track ambiante interrompue par barge-in → pas de double-play
- [ ] `hermes_task.py` : tâche Hermes annulée avant complétion → `CancelledError` géré
- [ ] `workers.py` : worker arrêté proprement via `runner.stop()` (pas de task leak)

---

## Synthèse prioritaire

| Priorité | Finding | Risque principal |
|----------|---------|-----------------|
| 1 | F01, F02, F03 | Bypass auth JWT / escalade de privilèges |
| 2 | F04, F05 | Endpoints login/refresh/logout sans protection de régression |
| 3 | F06, F07 | Injection prompt non détectée, ban bypass |
| 4 | F08 | Dépassement quota MiniMax silencieux (coût financier) |
| 5 | F09, F10, F12 | Pipeline audio : backpressure, barge-in, commandes `!` |
| 6 | F11, F15 | 732 LOC body_control + body_router sans test |
| 7 | F13 | Machine d'état mood non-déterministe |
| 8 | F14, F16, F17 | Admin routes, TTS adapters, LiveKit |
| 9 | F18, F19 | Assertions triviales (faux sentiment de couverture) |
| 10 | F20 | Fragilité asyncio future Python |
