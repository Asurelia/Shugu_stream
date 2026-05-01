# Pass 2 — Security audit

Audit humain du backend FastAPI/Pydantic/SQLAlchemy async (`backend/shugu/`).
Périmètre : `auth/`, `routes/`, `adapters/`, `config.py`, `app.py`. Les outils
statiques (ruff/mypy/bandit/semgrep/pip-audit) ont déjà tourné — ce pass se
concentre sur la logique applicative et les invariants de sécurité que les
linters ne voient pas.

## Résumé exécutif

13 findings — 1 P0 / 6 P1 / 6 P2.

Le système d'auth est globalement bien architecturé (cookies HttpOnly+Secure
+SameSite=strict, rotation refresh, JTI revocation Redis, bcrypt rounds=12,
HMAC compare_digest pour le bridge VIP, salting IP fail-fast en prod). Les
deux problèmes les plus exploitables sont :
1. l'absence totale de rate-limit sur `/auth/login` (operator) et
   `/api/account/login` (member/vip) → brute-force trivial sur bcrypt ;
2. la révocation VIP/désactivation compte qui ne révoque PAS les JWT déjà
   émis → un VIP révoqué peut continuer à miner des tokens LiveKit pendant
   ≤ 1 h (TTL access user JWT).

Aucune SQL injection, SSRF ou path traversal exploitable trouvée — tous les
appels HTTP sortants ciblent des hosts en dur (Resend, MiniMax, ElevenLabs,
Anthropic), aucune URL n'est contrôlée par l'utilisateur. ORM SQLAlchemy
utilisé partout, le seul `text()` brut (`memory/maintenance.py`) utilise
des bind params. Path traversal couvert par `_is_safe_inside_root` dans
`hermes_state`.

## Findings par priorité

### P0 — Exploitable / urgent

- [ ] **Brute-force du login operator non rate-limité**
  — `backend/shugu/routes/auth.py:58-91`
  — L'endpoint `POST /auth/login` ne fait AUCUN rate-limit (ni par IP, ni
  global). `bcrypt.checkpw` à rounds=12 = ~200 ms/tentative = ~5 essais/s par
  socket, parallélisable. Avec un dictionnaire moyen (10⁶ mots de passe
  courants), un mot de passe faible tombe en heures. Le compte operator
  contrôle 100% de l'admin (bans, scenes, registry, `/api/test/director`,
  etc.) — c'est le single point of compromise.
  — Fix : ajouter le helper `_rate_limit()` qui existe déjà dans
  `routes/account.py:149` (Redis INCR + TTL), keyé sur `hash_ip(client_ip)` :
  ex. 10 tentatives échouées / 15 min / IP, puis 429. Idéalement aussi
  un cap global secondaire pour éviter le distributed credential stuffing.
  Logger les bursts ≥ 5 échecs avec `log.warning` pour alerting.

### P1 — À corriger

- [ ] **Brute-force du login user (member/vip) non rate-limité**
  — `backend/shugu/routes/account.py:323-365`
  — Même problème que ci-dessus pour `POST /api/account/login`. `register`
  et `resend-verify` sont rate-limited (5/h/IP, 3/h/user) mais le login non.
  Pas P0 car un user compromis = scope plus restreint qu'un operator, mais
  reste exploitable pour énumération + takeover de comptes VIP (qui ouvrent
  un canal privé LiveKit avec Shugu).
  — Fix : `_rate_limit(redis, f"shugu:ratelimit:login:{ip_h}", limit=10,
  window_s=900)` au début de la fonction, AVANT le hash bcrypt.

- [ ] **Révocation VIP par l'admin n'invalide pas les sessions actives**
  — `backend/shugu/routes/admin_users.py:151-215`
  — Quand l'operator appelle `POST /api/admin/users/{id}/vip` avec
  `action=revoke`, le code zéro `vip_since`/`vip_until` en DB mais ne révoque
  AUCUN des `jti` user actifs. `auth/dependencies.py:_resolve_user` lit
  `vip_active` depuis la claim JWT (`user_tokens.py:108-128`). Conséquence :
  le user révoqué garde un JWT `role="vip"` valide jusqu'à expiration
  (`user_access_ttl_s = 3600` = 1 h) et peut continuer à appeler
  `POST /api/livekit/token` (`routes/livekit_api.py:42`, gated par
  `require_vip`) pour ouvrir des rooms VIP avec dispatch d'agent, jusqu'à
  60 min après la révocation.
  — Fix : dans la branche `revoke`, requêter `UserSession` pour ce
  `user_id`, et appeler `await user_tokens.revoke(jti, ttl_s=...,
  redis=...)` pour chacun. Le refresh ne pourra plus émettre de nouveau
  token (vu que `account.refresh()` lit `_compute_vip_active` en DB et
  retournera `role=member`). Acceptable de garder un lag de ≤ TTL
  refresh pour les sessions, mais le canal LiveKit doit être coupé
  immédiatement — au minimum déplacer le check VIP côté
  `routes/livekit_api.py:mint_vip_token` pour relire la DB plutôt que
  faire confiance à la claim.

- [ ] **`deactivate` d'un compte ne révoque pas non plus les JWT actifs**
  — `backend/shugu/routes/admin_users.py:218-243`
  — Même problème : `is_active=False` en DB n'invalide pas le JWT access
  déjà émis. `routes/account.refresh()` et `me()` détectent bien
  `account.is_active=False` au refresh suivant, mais entre la désactivation
  et le prochain refresh (≤ 1 h), l'utilisateur garde l'accès à toutes les
  routes member/vip protégées. `admin_users` est censé être l'outil
  d'urgence en cas d'abus — il doit cut-off immédiat.
  — Fix : itérer `UserSession` actives pour `user_id` et appeler
  `user_tokens.revoke(jti, ...)` sur chacune. Pattern : ajouter un helper
  `revoke_all_user_sessions(user_id, redis, ttl_s)` réutilisable.

- [ ] **`shugu_jwt_secret` sans fail-fast en production**
  — `backend/shugu/config.py:59`, `backend/shugu/auth/jwt_tokens.py:32`
  — `shugu_jwt_secret` a un défaut `""`. Si la variable est oubliée du
  `.env` prod, `jwt.encode("", algorithm="HS256")` produit des tokens
  signés avec une clé vide — trivialement forgeables par n'importe qui
  connaissant l'algo (`{role: "operator"}` + jwt.encode avec `""` = full
  admin). `user_tokens.issue_pair:58-59` lève bien un `AuthError` si
  `user_jwt_secret` est vide ; `jwt_tokens.issue_pair` n'a PAS l'équivalent.
  Le validator existe pour `ip_hash_salt` (`config.py:512`) — appliquer
  le même pattern.
  — Fix : ajouter un `field_validator("shugu_jwt_secret", "user_jwt_secret",
  mode="after")` qui exige une longueur ≥ 32 chars en prod (`env not in
  {"test", "dev", "ci"}`). Idem pour `vip_internal_secret` et
  `operator_password_hash` — tout vide = refus de boot.

- [ ] **Pas de middleware sécurité headers (CSP, HSTS, X-Frame-Options, etc.)**
  — `backend/shugu/app.py:622-677` (factory `create_app`)
  — Aucun `add_middleware` pour les en-têtes de sécurité. Si nginx en amont
  ne les pose pas, le frontend est exposé à clickjacking
  (X-Frame-Options/CSP frame-ancestors), MIME-sniffing
  (X-Content-Type-Options), HTTPS downgrade (HSTS), et fuite de Referer.
  Surtout important pour les pages servant les cookies `Secure` — un
  framing malicieux côté `shugu.spoukie.uk` reste un vecteur même avec
  `SameSite=strict` (le navigateur enverra le cookie dans une iframe
  same-site).
  — Fix : ajouter dans `create_app()` :
  ```python
  @app.middleware("http")
  async def security_headers(request, call_next):
      response = await call_next(request)
      response.headers.setdefault("X-Content-Type-Options", "nosniff")
      response.headers.setdefault("X-Frame-Options", "DENY")
      response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
      response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
      response.headers.setdefault("Content-Security-Policy", "default-src 'self'; ...")
      return response
  ```
  Vérifier au préalable la config nginx `ops/nginx/` — si elle pose déjà
  ces headers, défense en profondeur quand même côté FastAPI ne coûte rien.

- [ ] **Logs `auth.login` exposent l'username + jti — pas de masquage**
  — `backend/shugu/routes/auth.py:90`, `backend/shugu/routes/account.py:364`
  — `log.info("auth.login", username=body.username, jti=jti)` et
  `log.info("account.login", user_id=me.user_id, role=me.role)`. Le `jti`
  loggé est le secret de session (utilisé pour la révocation Redis). Si
  les logs sont siphonnés (S3 mal configuré, Loki public), un attaquant
  ayant accès aux logs ne peut pas forger le JWT (le secret est dans
  `shugu_jwt_secret`) MAIS il peut empoisonner Redis avec
  `shugu:jwt:revoked:<jti>` pour DoS toutes les sessions visibles dans les
  logs. Risque modéré, dépendant de l'isolation des logs.
  — Fix : logger un hash tronqué `jti[:8]` ou un compteur monotone
  (`session.id` côté DB) au lieu du jti complet. Vérifier aussi qu'aucune
  des 9 occurrences de `log.warning("...email_failed", error=str(exc))`
  ne contient l'API key Resend dans le body — `smtp_resend.py:118-126`
  protège déjà (loggue uniquement `status_code` + 500 chars de body),
  mais auditer le format des erreurs httpx remontées par d'autres
  adapters.

### P2 — Amélioration

- [ ] **Comparaison username operator non constant-time**
  — `backend/shugu/routes/auth.py:65`
  — `if body.username != settings.operator_username` est un short-circuit
  Python qui termine au premier char différent. Théoriquement permet de
  deviner l'username letter-by-letter via timing — en pratique l'username
  operator est un single-value secret qu'on suppose connu (genre
  "spoukie"), donc impact réel négligeable. À corriger pour cohérence
  avec le pattern `hmac.compare_digest` déjà utilisé dans
  `internal_vip:82`.
  — Fix : `if not hmac.compare_digest(body.username, settings.operator_username):`.

- [ ] **Timing oracle d'énumération de comptes user sur `/api/account/login`**
  — `backend/shugu/routes/account.py:339-342`
  — Le code shortcuts sur `if account is None or not account.is_active`
  AVANT d'appeler `bcrypt.checkpw` (qui prend ~200 ms). La différence de
  latence (≤10 ms si compte absent, ~210 ms si compte existant) permet
  d'énumérer des emails/usernames valides. Mitigé par le rate-limit
  (TODO P1) et par le fait que `register` retourne déjà 201 même si
  collision (anti-énumération côté inscription, `account.py:213-221`).
  — Fix : exécuter quand même un `bcrypt.checkpw(body.password,
  DUMMY_HASH)` quand `account is None`, avec un hash bcrypt pré-calculé
  fixe (constante module) pour normaliser le timing. C'est le pattern
  recommandé OWASP ASVS 2.2.1.

- [ ] **Auth WebSocket non re-validée pendant la session**
  — `backend/shugu/routes/operator_ws.py:79-89`,
  `backend/shugu/routes/world_ws.py:121-135`,
  `backend/shugu/routes/editor_ws.py:193-200`,
  `backend/shugu/routes/operator_voice_ws.py`
  — Le JWT operator est vérifié UNIQUEMENT à l'ouverture du WS. Si
  l'operator se logout / token est révoqué via Redis, le WS ouvert reste
  valide tant que la connexion est maintenue. Pour un WS qui peut tourner
  des heures (editor, voice duplex), c'est une fenêtre d'exposition non
  négligeable.
  — Fix : ajouter un check périodique (toutes les 30-60 s) qui re-vérifie
  via `jwt_tokens.verify` (qui consulte la revocation list Redis) et
  ferme le WS avec code 4401 si invalidé. Utiliser le heartbeat existant
  dans `editor_ws` (HEARTBEAT_INTERVAL_S=20) pour piggyback la
  revalidation.

- [ ] **Token JWT en query-param (`?token=`) loggé dans les access logs**
  — `backend/shugu/routes/operator_ws.py:74`, idem `world_ws.py:101`,
  `editor_ws.py:197`, `operator_voice_ws.py`
  — Documenté comme fallback intentionnel pour les browsers qui strip les
  cookies sur upgrade WS. Mais les query strings sont systématiquement
  loggés par nginx, par les CDN, dans le history du navigateur, et
  fuitent via `Referer` quand le WS est initié depuis une page qui a un
  link externe ouvert pendant le upgrade. Tokens valides 30 min — fenêtre
  de replay non négligeable.
  — Fix : éliminer le fallback `?token=` et exiger les cookies. Si un
  navigateur cible casse vraiment, utiliser le pattern WebSocket
  subprotocol (`Sec-WebSocket-Protocol: bearer.<token>`) qui n'est pas
  loggé. Au minimum : strip la query string `token=` des logs nginx
  (directive `log_format` custom).

- [ ] **Memory leak sur `_last_command_ts` (visitor !commands)**
  — `backend/shugu/routes/visitor_ws.py:46`
  — `_last_command_ts: dict[str, float]` est un global jamais nettoyé.
  Chaque IP unique qui tape une commande `!action` ajoute une entrée.
  Sur un stream populaire (Twitch raid → 10k spectateurs uniques),
  10k entrées × ~50 bytes = 500 KB persistants pour la durée du process.
  Pas un DoS dur, mais une fuite linéaire — gênant en production
  long-running.
  — Fix : utiliser un Redis ZSET avec TTL, ou un `TTLDict` en mémoire,
  ou une simple GC `if random.random() < 0.001: prune entries older
  than 5 minutes`. Cohérent avec le `SlidingRateLimiter` existant dans
  `core/observability.py`.

- [ ] **Pas de middleware CORS — vérifier topologie déploiement**
  — `backend/shugu/app.py` (aucun `CORSMiddleware`)
  — Aucun `app.add_middleware(CORSMiddleware, ...)` dans la factory. Si
  le frontend est servi same-origin via nginx (pattern attendu vu les
  cookies `samesite=strict`), c'est OK. Si un jour le frontend déménage
  sur un autre domaine ou si une SPA dev tourne sur localhost:5173, les
  requêtes seront bloquées par le browser et ça causera de la confusion.
  À documenter explicitement dans `app.py` plutôt que d'être un oubli.
  — Fix : ajouter un commentaire de design dans `create_app()` qui
  affirme l'invariant same-origin, ou — si CORS est nécessaire —
  whitelister explicitement `settings.public_site_url` avec
  `allow_credentials=True` et `allow_origins=[settings.public_site_url]`.
  PAS de `allow_origins=["*"]` avec credentials (interdit par la spec et
  silencieusement ignoré par les browsers, mais piège classique).

- [ ] **`hermes_task_timeout_s = 300` permet d'épuiser la pool httpx**
  — `backend/shugu/config.py:111`,
  `backend/shugu/adapters/brain_director_minimax.py:89` (timeout=60),
  `backend/shugu/adapters/brain_director_anthropic.py:93` (timeout=60),
  `backend/shugu/adapters/smtp_resend.py:117` (timeout=30)
  — Les adapters externes ont des timeouts cohérents (30-60 s), mais
  `hermes_task_timeout_s=300` (5 min) est très long pour un client httpx
  partagé (`http: httpx.AsyncClient` créé une seule fois dans
  `app.py:130`). Si 10 requêtes Hermes pendantes timent à 5 min chacune,
  la pool httpx peut bottleneck les autres adapters (TTS, Resend, LLM).
  Surtout que Hermes peut être relayé via l'operator WS, qui est joignable
  par compte operator authentifié.
  — Fix : utiliser des `httpx.AsyncClient` séparés par adapter avec
  `limits=httpx.Limits(max_connections=N)`, OU réduire
  `hermes_task_timeout_s` à 60-90 s. Au minimum, documenter le risque
  de saturation du client partagé.

### Bonnes pratiques observées

- Cookies `httponly=True, secure=True, samesite="strict"`, scoped path
  séparé pour access (`/`) et refresh (`/auth/`, `/api/account/`) —
  `routes/auth.py:32-50`, `routes/account.py:111-129`. Couvre CSRF
  proprement.
- Bcrypt rounds=12 + guard 72-byte (limite silencieuse bcrypt) +
  `verify_password` constant-time — `auth/password.py:27-42`.
- HMAC `compare_digest` pour le secret bridge VIP, avec log volontairement
  minimaliste pour ne pas leak l'expected — `routes/internal_vip.py:74-86`.
- JWT rotation : refresh émet un nouveau jti et révoque l'ancien
  immédiatement via Redis SET avec TTL — `routes/auth.py:108-114`,
  `routes/account.py:402-409`.
- IP salting fail-fast en prod via field_validator — `config.py:512-528`.
  Empêche le déploiement avec `IP_HASH_SALT=""` (déanonymisation viewers).
- `_validate_public_site_url` rejette `javascript:` / `data:` / `vbscript:`
  schemes pour l'URL injectée dans les `<a href>` des emails —
  `config.py:492-510`. Defense-in-depth XSS clients mail.
- Jinja2 `autoescape=select_autoescape(["html","htm","xml"])` actif sur
  les templates emails — `adapters/smtp_resend.py:37-42`.
- Path traversal + symlink resolution dans le reader `~/.hermes/` —
  `adapters/hermes_state.py:88-113`. `_is_safe_inside_root` bloque les
  symlinks et les `..` post-resolve.
- Cap `_MAX_FRAME_BYTES = 32 KB` sur les frames editor WS et
  `_MAX_FRAME_BYTES = 1024` + `_MAX_FRAMES_PER_SEC = 120` sur le voice WS
  — `routes/editor_ws.py:97`, `routes/operator_voice_ws.py:63-66`.
  Anti-DoS bien pensé.
- Réponses opaques sur `register` et `resend-verify` (renvoie 201 même si
  email/username pris) — anti-énumération — `routes/account.py:213-221,
  297-299`.
- Validation des slugs/IDs par regex stricte avant interpolation DB ou
  path matching — `_SLUG_RE`, `_KIND_RE` (`registry_api.py:57-58`),
  `_SCENE_ID_RE` (`scene_composer_api.py:66`), `_SCENE_ID_PATTERN`
  (`editor_ws.py:101`).
- `test_director_api` triple-gated : feature flag OFF par défaut + auth
  operator + exclusion de `vip_arrival` (qui bypasserait le rate-limit
  LLM) — `routes/test_director_api.py:65-84`.
- `vip_internal_url` documenté comme `127.0.0.1` only + commentaire
  pour confirmer dans nginx que `/internal/*` n'est pas exposé public —
  `routes/internal_vip.py:7-15`.
- Pydantic `Field(min_length=, max_length=, ge=, le=)` partout sur les
  inputs user (`routes/account.py:57-74`, `admin_users.py:54-63`,
  `test_director_api.py`). Caps numériques bornées, anti-payload géant.
- ORM SQLAlchemy partout. Le seul `text()` brut
  (`memory/maintenance.py:82,121,161`) utilise EXCLUSIVEMENT des bind
  params — pas de f-string interpolation. Pas de surface SQL injection.
- Pas de SSRF : tous les hosts externes (Resend, MiniMax, ElevenLabs,
  Anthropic, LiveKit) sont en dur dans les adapters ou viennent de
  Settings (jamais de l'input user).
