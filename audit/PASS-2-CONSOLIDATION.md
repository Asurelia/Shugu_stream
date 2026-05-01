# Audit Shugu_stream — Pass 2 (Consolidation finale)

**Date** : 2026-05-01
**Commit audité** : `75846b5` (main, post-Pass 1)
**Méthode** : 5 agents spécialisés en parallèle

---

## Synthèse globale

| Domaine | Findings | P0 | P1 | P2 |
|---|---|---|---|---|
| Sécurité | 13 | 1 | 6 | 6 |
| Silent failures | 22 | 3 | 11 | 8 |
| Performance | 12 | 5 | 4 | 3 |
| Type design | 13 | 4 | 4 | 5 |
| Test coverage | 20 | 7 | 11 | 2 |
| **Total** | **80** | **20** | **36** | **24** |

→ Code python globalement **bien architecturé**. Mais 20 P0 forment un cluster cohérent : **auth (rate-limit + tests + révocation)**, **types laxistes (Mood × 2, apply(action: object))**, **scaling (DB pool, JSON fanout)**, **silent failures (WS sans log)**. Aucun bug critique standalone — c'est des **angles morts AI typiques** : l'IA crée plus vite qu'elle ne vérifie les invariants à long terme.

---

## 🔴 P0 — Critique (à fixer en priorité)

### Cluster 1 — Authentification (P0 × 6)

> **Tous interconnectés** : route `/auth/login` non testée + non rate-limitée + JWT révocation incomplète = compromise admin par dictionnaire en quelques heures, sans alerte.

#### P0.A1 — Brute-force `/auth/login` operator non rate-limité 🔥
- **Source** : security agent
- **Fichier** : `backend/shugu/routes/auth.py:58-91`
- **Impact** : compte operator = 100% admin ; bcrypt rounds=12 = ~5 essais/s/socket parallélisable. Dictionnaire moyen 10⁶ mots = compromise en heures.
- **Fix** : appliquer le helper `_rate_limit()` existant dans `routes/account.py:149` (Redis INCR + TTL), keyé sur `hash_ip(client_ip)`, 10 tentatives/15min/IP, log warning sur burst ≥ 5 échecs. **Effort** : 30 min.

#### P0.A2 — `jwt_tokens.verify()` 0 test sur 5 chemins d'erreur
- **Source** : test-engineer (F01)
- **Fichier** : `backend/shugu/auth/jwt_tokens.py` (106 LOC)
- **Impact** : 5 chemins d'erreur (signature expirée, token malformé, mauvais token_type, mauvais role, JTI révoqué) sans aucun test. Régression silencieuse possible : tweak innocent peut ouvrir un bypass.
- **Fix** : `tests/unit/test_jwt_tokens.py` couvrant les 5 cas + happy path. **Effort** : 1-2h.

#### P0.A3 — `user_tokens.py` 0 test, surface VIP critique
- **Source** : test-engineer (F02)
- **Fichier** : `backend/shugu/auth/user_tokens.py` (133 LOC)
- **Impact** : promotion VIP via claim `vip_active=True` non testée. Un changement de logique pourrait laisser passer un token forgé. **Effort** : 1-2h.

#### P0.A4 — `dependencies.py` `require_operator`/`require_vip` non testés
- **Source** : test-engineer (F03)
- **Fichier** : `backend/shugu/auth/dependencies.py` (161 LOC)
- **Impact** : logique seulement testée via mocks dans tests de routes ; le pattern d'import différé `get_redis` est un point de rupture silencieux. **Effort** : 1-2h.

#### P0.A5 — Routes `/auth/*` et `/api/account/*` 0 test
- **Source** : test-engineer (F04, F05)
- **Fichiers** : `routes/auth.py`, `routes/account.py`
- **Impact** : login/logout/refresh/register/verify-email/resend, **chaîne d'authentification entière sans test bout-en-bout**. **Effort** : 3-4h.

#### P0.A6 — Révocation VIP n'invalide pas les JWT actifs
- **Source** : security agent
- **Fichier** : `backend/shugu/routes/admin_users.py:151-215`
- **Impact** : VIP révoqué peut continuer à miner des tokens LiveKit pendant ≤ 1h (TTL access JWT). Canal vocal privé reste ouvert.
- **Fix** : dans la branche `revoke`, requêter `UserSession` pour ce `user_id` et `await user_tokens.revoke(jti, ...)`. Côté `routes/livekit_api.py:mint_vip_token`, relire la DB plutôt que faire confiance à la claim. **Effort** : 1-2h.

### Cluster 2 — Types laxistes (P0 × 4)

#### P0.T1 — Deux `Mood` Literal homonymes vocabulaires disjoints 💣
- **Source** : type-design agent
- **Fichiers** : `world/types.py:32` (`"neutral","happy","angry","sad","relaxed","surprised"`) vs `core/body_control.py:72` (`"cheerful","focused","sleepy","playful","bored"`) + `core/mood.py:18` `MoodState(str, Enum)` vocabulaire différent encore.
- **Impact** : un `from ..core.body_control import Mood` au lieu de `from ..world.types import Mood` typecheck OK mais crashe au runtime via `_VALID_MOODS` (handlers.py:48). Bombe silencieuse.
- **Fix** : renommer en `WorldMood` / `BodyMood`, supprimer le Literal redondant côté `body_control`. **Effort** : 1h.

#### P0.T2 — Deux `Emotion` Literal — sets divergents silencieux
- **Source** : type-design agent
- **Fichiers** : `core/protocols.py:26` vs `core/body_control.py:71`
- **Impact** : aujourd'hui équivalents mais ordre diffère ; demain l'un divergera silencieusement.
- **Fix** : exporter un seul `Emotion` depuis `core/protocols.py`. **Effort** : 30 min.

#### P0.T3 — `WorldStoreLike.apply(action: object)` désactive le typage
- **Source** : type-design agent
- **Fichier** : `agent/handlers.py:68`
- **Impact** : Protocol accepte littéralement n'importe quoi (int, dict, MemberIdentity). Les 4 handlers (`handle_set_pose`, `handle_set_mood`, etc.) appellent `apply(MoodSetAction(...))` sans aucune vérification de type. Si un champ est renommé, le handler typecheck encore.
- **Fix** : importer `ActionUnion`/`WorldState` (déjà allowlistés en L0 D4), resserrer la signature. **Effort** : 15 min.

#### P0.T4 — `OperatorIdentity()` / `MemberIdentity()` constructibles vides
- **Source** : type-design agent
- **Fichier** : `core/identity.py`
- **Impact** : la docstring promet « Le type-system empêche un code visitor-path de fabriquer une OperatorIdentity » mais le constructor accepte vide. Defense en profondeur cassée.
- **Fix** : champs sans default, ou `__post_init__` qui valide non-vide. **Effort** : 30 min.

### Cluster 3 — Scalabilité (P0 × 2)

#### P0.P1 — DB pool taille par défaut (5 conn)
- **Source** : performance agent
- **Fichier** : `backend/shugu/db/session.py:12`
- **Impact** : SQLAlchemy default = 5 conn + 10 overflow ; sous 100+ users actifs avec workers concurrents → saturation pool en quelques secondes, latence p99 × 5.
- **Fix** : `create_async_engine(dsn, pool_size=20, max_overflow=20, pool_recycle=1800, pool_pre_ping=True)` + Settings (`db_pool_size`, `db_max_overflow`). **Effort** : 5 min.

#### P0.P2 — Fanout `json.dumps` O(N×payload) sur WS
- **Source** : performance agent
- **Fichiers** : `routes/visitor_ws.py:110`, `operator_ws.py:127`, `world_ws.py:243`, `operator_voice_ws.py:156`
- **Impact** : 100 viewers × 30 chunks/s × `json.dumps` d'un payload base64 ~10KB = **CPU event loop saturé sous streaming TTS**.
- **Fix** : pré-sérialiser dans publisher, helper `send_cached_json(ws, event)` qui mémoïse `id(event) → str` pour la durée du fanout. **Effort** : 1-2h.

### Cluster 4 — Silent failures (P0 × 3)

#### P0.S1 — `operator_voice_ws.py:155-158` send WS sans log
- **Source** : silent-failure agent
- **Impact** : 30 min de session opérateur peuvent perdre tous les events `voice.state.change` sans aucune trace côté serveur. Debug impossible.
- **Fix** : aligner sur `editor_ws._safe_send_json` — `log.debug("voice.send_failed", error=str(exc))`. **Effort** : 5 min.

#### P0.S2 — `extraction_worker.py:191` `except (CancelledError, Exception): pass`
- **Source** : silent-failure agent
- **Impact** : masque des bugs de finalisation worker. Cancellation et erreur réelle indistinguables.
- **Fix** : séparer `except CancelledError: raise` puis `except Exception as e: log.exception(...)`. **Effort** : 10 min.

#### P0.S3 — `ingestion_worker.py:147` même pattern
- **Source** : silent-failure agent
- **Fix** : idem P0.S2. **Effort** : 10 min.

### Cluster 5 — Tests modération (P0 × 2)

#### P0.T-Mod1 — `injection_detector.py` 0 test sur seuil ban
- **Source** : test-engineer (F06)
- **Impact** : seuil `score ≥ 10` pour auto-ban jamais vérifié. Tweak regex silencieux peut ouvrir/fermer la détection.
- **Fix** : test paramétrisé sur le scoring. **Effort** : 2h.

#### P0.T-Mod2 — `moderation_basic.py` 0 test
- **Source** : test-engineer (F07)
- **Fix** : suite de tests sur les patterns. **Effort** : 1-2h.

---

## 🟠 P1 — Important (cette semaine)

### Sécurité (6)
- **`shugu_jwt_secret` sans fail-fast** au démarrage si vide
- **Aucun middleware security headers** (CSP, X-Frame-Options, X-Content-Type-Options) — défense en profondeur manquante. Cf. recommandation hook : utiliser `secure` (Python lib pour security headers Helmet-like).
- **JTI loggés en clair** dans certains warning logs
- **Login user (member/vip)** non rate-limité (P1 plutôt que P0 car scope plus restreint)
- **Désactivation compte** ne révoque pas les JWT actifs
- **Session opérateur jamais re-validée** mid-session (long-lived WS)

### Silent failures (11)
Chaîne **STT → voice_duplex → Hermes** : 11 retours silencieux où `log.warning(...); return ""` rend impossible de distinguer "résultat vide légitime" vs "crash". Particulièrement sensibles : tts_minimax fallback, picker._archive, voice transcription chunks.

### Performance (4)
- **3 leaks process** : `_history_per_session` (workers.py), `_last_command_ts` (visitor_ws.py), picker `_bg_tasks` archive
- **Sense queue `maxlen=64` drop-oldest** : pénalise les messages déclencheurs en raid → passer à 256 + priority drop
- **Picker poll 5 ZPOPMIN/s à vide** → pattern wake-up Redis BLPOP-like
- **Slow WS clients drop silencieusement** → métrique `event_bus.dropped_total{topic=}`

### Type design (4)
- `Senses` / `WorldSnapshot` : NewType absent → `subject: str` au lieu de `Subject = NewType('Subject', str)` (load-bearing pour scoping privacy mémoire)
- `ToolCall.params` mutable malgré frozen=True (le seul restant après les fix de Tool/SenseEvent/PolicyMatrix)
- Enum-like via str dans plusieurs handlers
- `dict[str, Any]` omniprésent dans les payloads — Pydantic models au lieu

### Tests (11)
- Pipeline audio 1 343 LOC sans test (picker.py, queue.py, body_router.py, voice_duplex.py, ambient.py)
- Backpressure / barge-in / LiveKit session non testés
- Auth flow E2E manquant (login → refresh → revoke → access)

---

## 🟡 P2 — Nettoyage (backlog)

- 6 P2 sécurité : timing oracle énumération comptes, comparaison username operator non constant-time, fallback `?token=` qui fuite via access logs, etc.
- 8 fallbacks Cat C légitimes mais sans métrique Prometheus (post Phase 8.2)
- 3 micro-optims perf : asyncio.Lock contention sur fanout, snapshot world cache, etc.
- 5 type design suggestions : invariants manquants, generic mal contraint
- 2 tests mineurs fragiles

---

## ✅ Bonnes pratiques observées

Bonnes nouvelles du Pass 2 :
- **Aucun SQL injection, SSRF, ou path traversal exploitable** trouvé
- Cookies HttpOnly+Secure+SameSite=strict scopés correctement
- bcrypt rounds=12 + guard 72-byte
- HMAC compare_digest pour le bridge VIP
- JWT rotation atomique avec JTI Redis
- IP salt fail-fast en prod
- Validator http/https-only sur `public_site_url` (Pass 1 fix)
- Jinja2 autoescape activé
- Caps frames WS
- Réponses opaques anti-énumération
- Regex strictes sur slugs/IDs
- Triple-gate sur la route de test Director
- 0 bare-except, 0 BaseException, code Python objectivement propre côté error handling
- Pas de blocking I/O sync dans les handlers async
- Tasks fire-and-forget toutes référencées
- WorldStateStore.apply correctement shieldé contre cancellation

---

## Plan de fix recommandé

### Sprint 1 (1-2 jours) — P0 critiques
1. **P0.P1 DB pool** (5 min) — quick win
2. **P0.S1, P0.S2, P0.S3** silent failures (25 min total) — quick wins
3. **P0.T3 `apply(action)`** (15 min) — quick win
4. **P0.T1, P0.T2 `Mood`/`Emotion`** rename (1h30) — élimine la bombe runtime
5. **P0.T4 Identity guards** (30 min)
6. **P0.A1 rate-limit `/auth/login` operator** (30 min)
7. **P0.A6 révocation VIP** (1-2h)
8. **P0.P2 JSON fanout pré-sérialisé** (1-2h)

→ **Total Sprint 1** : ~6-8h pour éliminer 14 P0.

### Sprint 2 (3-5 jours) — P0 tests + P1
9. **Tests auth chain** (P0.A2-A5) : 6-10h
10. **Tests modération** (P0.T-Mod1, P0.T-Mod2) : 3-4h
11. **P1 leaks process + sense queue + métriques manquantes** : 4-6h
12. **P1 security headers middleware** + fail-fast JWT secret : 2h

→ **Total Sprint 2** : ~15-22h pour éliminer 7 P0 + 6-10 P1.

### Sprint 3+ (backlog continu)
13. **P1 chaîne STT silent failures** (refactor returns Result-like)
14. **P1 type design** (NewType pour Subject, etc.)
15. **P2 sécurité durcissements** (timing oracle, etc.)
16. **Migration Next.js 13 → 16** (séparée, 3-5 jours)

---

## Décisions attendues de Sylvain

1. **Sprint 1** maintenant ? Ou attendre la prochaine session ?
2. Si Sprint 1, quel sous-ensemble en priorité ? Les "quick wins" (3.5h) seuls ? Ou les 14 P0 d'un coup ?
3. Ouvrir 1 PR par cluster (auth / types / perf / silent / tests modération) ou 1 méga-PR Pass 2 ?
4. Sprint 2 (tests auth) — c'est lourd. Décomposer en 4 PRs ?
