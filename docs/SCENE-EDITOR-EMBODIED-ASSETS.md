# Embodied Shugu — Assets Bank Convention (Phase E3)

Cette doc capture la convention de slug, de path et de whitelist pour les
assets du système Embodied Shugu (Soul/Shell). Les workers déterministes
(`backend/shugu/director/workers/`) valident le slug émis par Shugu Soul
contre la bank d'assets disponible avant de broadcast — pas de chemin
arbitraire, pas de path traversal possible.

## Vue d'ensemble

```text
┌────────────────────────────────────────────────────────────────────┐
│  Shugu Soul (LLM E2)                                               │
│    sortie : "Hé salut ! [outfit:vip_fan][face:joy][vfx:confetti]"  │
└────────────────────────┬───────────────────────────────────────────┘
                         │ parse tags inline
                         ▼
┌────────────────────────────────────────────────────────────────────┐
│  LLMOrchestrator (E2)                                              │
│    for tag in tags:                                                │
│      worker = workers[tag.kind]                                    │
│      delta = await worker.apply(tag.value, state)                  │
│      await store.update(delta.patch)                               │
└────────────────────────┬───────────────────────────────────────────┘
                         │ broadcast `editor:broadcast`
                         ▼
┌────────────────────────────────────────────────────────────────────┐
│  WorkerBase._publish() :                                           │
│    {type:"scene.apply", kind:"outfit", id:"vip_fan", ts:...}       │
└────────────────────────┬───────────────────────────────────────────┘
                         │ Phase D bus → Redis pub/sub → /ws/editor
                         ▼
┌────────────────────────────────────────────────────────────────────┐
│  Frontend useEditorWebSocket → store.dispatchSceneApply            │
│    → ViewerAdapter useEffect([lastSceneApply])                     │
│    → handlersRef.current.swapTexture('/assets/vrm/outfits/vip_fan.png')│
└────────────────────────────────────────────────────────────────────┘
```

## Conventions par kind

### `outfit`

- **Tag** : `[outfit:<slug>]`
- **Worker** : `OutfitWorker` valide contre `assets_available["outfits"]`.
- **URL frontend** : `/assets/vrm/outfits/{slug}.png`
- **Effet** : `swapTexture(url)` sur le viewer 3D (legacy stub Phase F).
- **State patch** : `{"outfit": "<slug>"}`

### `vfx`

- **Tag** : `[vfx:<slug>]`
- **Worker** : `VfxWorker` valide contre `assets_available["vfx"]`.
- **Broadcast** : embarque `duration_ms` (3000 par défaut).
- **Effet** : `showVfxOverlay(id)` sur le viewer (overlay shader/sprite).
- **State patch** : append à `active_vfx` (FIFO trim 5 max).

### `anim`

- **Tag** : `[anim:<slug>]`
- **Worker** : `AnimWorker` valide contre `assets_available["anims"]`.
- **URL frontend** : `/assets/vrma/{slug}.vrma`
- **Effet** : `playAnimation(url)` (loop=false par défaut).
- **State patch** : aucun (animation éphémère).

### `face`

- **Tag** : `[face:<emotion>]`
- **Worker** : `FaceWorker` whitelist hardcodée `{neutral, joy, surprised,
  sad, angry, thinking}`.
- **Effet** : `setBlendshape(emotion, 1.0)` ; reset l'ancienne à 0 si
  différente.
- **State patch** : `{"face": "<emotion>"}`

### `say_emotion`

- **Tag** : `[say_emotion:<emotion>]`
- **Worker** : `SayWorker` whitelist alignée sur `face`.
- **Effet visuel** : aucun. Consommé par le pipeline TTS Phase E4 (preset
  voice / pitch / pacing).
- **State patch** : aucun.

### `camera`

- **Tag** : `[camera:<mode>]`
- **Worker** : `CameraWorker` whitelist `{auto, close_up, wide, back_view,
  side_view}`.
- **Broadcast** : champ `mode` (pas `id`).
- **Effet** : route vers `setCameraMode` du store (Phase G — gap implé
  pour l'instant, log uniquement).
- **State patch** : `{"camera_mode": "<mode>"}`

### `scene`

- **Tag** : `[scene:<slug>]`
- **Worker** : `SceneWorker` valide contre `assets_available["scenes"]`,
  fallback whitelist `{main_talk, intro, outro, gaming, chat}`.
- **Effet** : aucun côté `ViewerAdapter` (le change de scène est routé via
  le topic `stage` Phase D, consommé ailleurs).
- **State patch** : `{"scene": "<slug>", "active_vfx": []}` (reset VFX).

## Securité

- Le `tag_value` est **toujours** validé contre une whitelist (bank assets
  ou liste hardcodée) AVANT d'être composé en URL.
- Le frontend re-encode via `encodeURIComponent` en defense in depth (un
  slug avec `..` ou `/` se transforme en `%2F` / `%2E%2E` et hit un 404
  inoffensif côté serveur statique Next.js).
- Un slug invalide retourne `StateDelta(patch={})` + log warning ; aucun
  broadcast émis ; le pipeline LLM continue normalement (ne crash pas
  sur une hallucination).

## Layout des fichiers

```text
frontend/public/assets/
  vrm/
    outfits/
      README.md      ← convention textures outfit
      <slug>.png
  vrma/
    README.md        ← convention animations VRMA
    <slug>.vrma
  vfx/
    README.md        ← convention slug VFX (shader-side, pas d'asset)
```

Aucune migration / pre-build : Next.js sert `/public/*` statiquement, drop
le fichier au bon path et c'est live (reload navigateur).

## Évolution

- **E4** : `SayWorker` complet branché sur `adapters/tts/*` — l'émotion
  vocale fait varier preset voix.
- **E5** : `setCameraMode` ajouté au store frontend (gap Phase F→E3).
- **F+** : `swapTexture` et `playAnimation` réellement câblés au viewer
  Three.js (au lieu des stubs no-ops Phase F).
