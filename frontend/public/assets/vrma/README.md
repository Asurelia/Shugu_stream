# Animations VRMA — Phase E4 (`AnimWorker` + Mixamo Bank)

Animations standalone consommées par le worker `AnimWorker` (backend). Le
broadcast `{type:"scene.apply", kind:"anim", id:"<slug>"}` se résout côté
frontend en URL :

```text
/assets/vrma/{slug}.vrma
```

## Convention

- **Format** : `.vrma` (Virtual Reality Model Animation, format VRM 1.0 / glTF)
- **Slug** : minuscules, snake_case (`wave`, `bow`, `clap`, `idle_loop`)
- **Nommage** : `{slug}.vrma` + `{slug}.vrma.meta.json` (sidecar metadata)
- **Frames** : typiquement 30–300 frames (1–10 secondes @ 30 fps)
- **FPS** : 24, 30, ou 60 fps standard
- **Whitelist** : `SceneStateSnapshot.assets_available["anims"]` (seeded au boot dans `app.py`)

## Ajout d'animations via Mixamo ETL

Phase E4 introduit une **pipeline automatisée Mixamo FBX → VRMA** (conversion via Blender).

**Pour ajouter une animation** :

1. Téléchargez depuis Mixamo : https://www.mixamo.com/ (gratuit, compte Adobe)
2. Exécutez le script de conversion :
   ```bash
   blender --python tools/mixamo_etl/mixamo_to_vrma_blender.py -- \
       --input-fbx ~/wave.fbx \
       --reference-vrm ~/avatar.vrm \
       --output-vrma frontend/public/assets/vrma/wave \
       --slug wave
   ```
3. Validez le fichier `.vrma` produit
4. Ajoutez le slug à `backend/shugu/app.py` ligne 344–345 dans `assets_available["anims"]`
5. Redémarrez le backend

**Documentation complète** : [`docs/MIXAMO_VRMA_BANK.md`](../../docs/MIXAMO_VRMA_BANK.md)

## Différence avec `/animations/*.fbx`

Le legacy retargeter (`src/features/animations/fbxRetarget.ts`) consomme des
FBX Mixamo et les retarget sur le rig VRM à la volée (coûteux, runtime).

Phase E4 utilise des `.vrma` **pré-retargetés** (Mixamo → VRM Humanoid standard
via Blender offline). Sans retarget runtime, d'où performance + qualité ✓.

Si un slug n'a pas de `.vrma` dédié, le frontend retombe sur le legacy FBX
de même nom (cf. `animationPack.ts`). Fallback transparent.

## Métadonnées VRMA

Chaque fichier `.vrma` est accompagné d'un sidecar `.vrma.meta.json` :

```json
{
  "format": "vrma",
  "version": "1.0",
  "slug": "wave",
  "frame_count": 60,
  "fps": 30.0,
  "duration_seconds": 2.0,
  "retarget_source": "mixamo",
  "retarget_mapping": "vrm_humanoid_standard"
}
```

Utilisé par le loader pour validation et logging (optionnel, ne bloque pas le playback).

## License

Animations Mixamo : **Adobe Mixamo ToS**. Redistribution FBX brut forbidden, mais
dérivés retargetés (VRMA) OK pour usage commercial/personnel. Cf. `docs/MIXAMO_VRMA_BANK.md`.
