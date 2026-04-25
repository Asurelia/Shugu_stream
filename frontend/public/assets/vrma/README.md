# Animations VRMA — Phase E3 (`AnimWorker`)

Animations standalone consommées par le worker `AnimWorker` (backend). Le
broadcast `{type:"scene.apply", kind:"anim", id:"<slug>"}` se résout côté
frontend en URL :

```text
/assets/vrma/{slug}.vrma
```

## Convention

- **Format** : `.vrma` (Virtual Reality Model Animation, format VRM 1.0).
- **Slug** : minuscules, snake_case (`wave`, `bow`, `clap`, `idle_loop`).
- **Whitelist** : exposée par `SceneStateSnapshot.assets_available["anims"]`
  (E2 alimentera depuis ce dossier).

## Différence avec `/animations/*.fbx`

Le legacy retargeter (`src/features/animations/fbxRetarget.ts`) consomme des
FBX Mixamo et les retarget sur le rig VRM à la volée. Phase E3 reste sur
des `.vrma` "premium" (animations déjà ciblées Shugu, sans retarget runtime).

Si un slug n'a pas de `.vrma` dédié, le frontend retombe sur le legacy FBX
de même nom (cf. `animationPack.ts`). Le placeholder `idle_loop.vrma`
existe déjà dans `frontend/public/`.

## Placeholders

Pas besoin de fichiers réels pour Phase E3 — les tests Vitest mockent
`playAnimation`. Un slug sans fichier produit un 404 silencieux côté
viewer (legacy stub).
