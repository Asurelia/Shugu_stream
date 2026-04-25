# VFX overlays — Phase E3 (`VfxWorker`)

Effets visuels overlay (confettis, sparks, hearts) déclenchés par le tag
inline `[vfx:<slug>]` côté Shugu Soul. Le `VfxWorker` broadcast
`{type:"scene.apply", kind:"vfx", id:"<slug>", duration_ms:3000}` ; le
viewer en Phase F+ rendra l'overlay côté canvas (Three.js sprites ou
particles, design TBD).

Pour Phase E3, l'`id` du VFX est passé tel quel à `showVfxOverlay(id)` —
pas de résolution d'URL (les VFX sont gérés dans le code shader, pas
servis comme assets). Cette README documente la convention de slug.

## Slug whitelist

Exposée par `SceneStateSnapshot.assets_available["vfx"]`. Suggestions MVP :

- `confetti_gold` — célébration, milestone viewer.
- `sparks` — réaction, surprise.
- `hearts` — affection, VIP arrival.
- `bubbles` — chill, reading_chat.

## Durée

`duration_ms` par défaut 3000ms côté backend (cf.
`backend/shugu/director/workers/vfx.py::DEFAULT_VFX_DURATION_MS`). Le
viewer doit auto-cleanup l'overlay après ce délai.

## Limite simultanée

`MAX_ACTIVE_VFX = 5` côté backend. Au-delà, FIFO trim — le snapshot reste
sous le seuil JSON 500 bytes pour rester injectable au prompt.
