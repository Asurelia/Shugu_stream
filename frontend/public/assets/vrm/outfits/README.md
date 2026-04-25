# Outfits — VRM texture hot-swap (Phase E3)

Le worker `OutfitWorker` (backend) broadcast `{type:"scene.apply", kind:"outfit", id:"<slug>"}`
quand Shugu Soul émet `[outfit:<slug>]`. Le frontend `ViewerAdapter`
(`viewer-adapter.tsx`) résout le slug en URL via :

```text
/assets/vrm/outfits/{slug}.png
```

## Convention

- **Format** : PNG, RGB, identique à la texture VRM principale (résolution
  variable, généralement 1024×1024 ou 2048×2048).
- **Slug** : minuscules, snake_case (`vip_fan`, `summer`, `holiday_red`).
- **Whitelist** : la liste exacte est exposée par le backend dans
  `SceneStateSnapshot.assets_available["outfits"]` (E2 alimentera ce champ
  depuis ce dossier quand le registry frontend → backend sera branché).

## Slugs MVP recommandés

- `default` — texture VRM par défaut (fallback). Utilise le `shugu_avatar.vrm`
  embedding la texture dans le glb si pas de fichier ici.
- `vip_fan` — outfit "fan" pour les triggers VIP.
- `summer`, `winter`, `gaming`, `chat` — variantes thématiques.

## Placeholder

Tant que les vrais textures ne sont pas livrées, le viewer encaisse un 404
sur l'URL résolue (le `swapTexture` du legacy est un stub Phase F). Aucun
crash : juste pas d'effet visuel.
