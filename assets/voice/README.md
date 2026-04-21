# assets/voice/

Emplacement local des samples audio utilisés pour cloner la voix de Shugu
côté MiniMax. **Les fichiers audio sont ignorés par git** (voir `.gitignore`) —
seuls ce README et le `.gitkeep` sont versionnés.

## Fichier attendu

```
assets/voice/shugu_sample.wav
```

30 à 60 secondes, mono, 16 kHz ou plus, WAV PCM 16-bit. Voir
`tools/voice_clone/record_sample.md` pour la checklist complète.

## Pourquoi local-only

Un sample vocal peut permettre d'identifier la personne derrière le
micro ou de régénérer sa voix ailleurs. Même si tu prêtes ta voix à
Shugu sciemment, tu ne veux pas que le `.wav` se retrouve dans un fork
ou dans un historique git public.

Si tu as besoin de partager le sample (backup, autre machine), utilise
un canal privé chiffré, pas le repo.
