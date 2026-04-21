# Enregistrer et cloner la voix de Shugu sur MiniMax

Ce document est la procédure complète pour donner à Shugu une voix cohérente
sur tous les canaux (broadcast public + VIP room) via le voice cloning
de MiniMax (endpoint `/v1/voice_clone`).

> Durée totale : ~30 minutes (20 min de prise + 10 min d'upload/test).

---

## 1. Pourquoi cloner la voix

- **Cohérence vocale** : la même Shugu sur le broadcast public *et* dans la
  room VIP privée (phase 3a du plan v4).
- **Identité sonore forte** : la voix par défaut `French_MovieLeadFemale` est
  générique ; un clone personnel rend Shugu instantanément reconnaissable.
- **Coût zéro** en plus : le cloning MiniMax est facturé à l'usage TTS, pas à
  la création. Pas de frais récurrents pour le clone.

---

## 2. Matériel recommandé

- **Micro** : cardioïde USB (Shure MV7, Rode NT-USB, ou même un AKG Lyra
  correct). Évite les micros cravate bas de gamme — ils mangent les aigus.
- **Casque** fermé pour monitoring (pas d'enceinte, sinon boucle retour).
- **Pièce** : ameublée, rideaux tirés si possible. Évite les salles de bain
  vides (réverbération), les pièces avec beaucoup de vitres, ou à côté de PC
  bruyant.
- **Logiciel** : **Audacity** (gratuit, suffisant) ou OBS en mode audio-only.

---

## 3. Réglages d'enregistrement

| Paramètre | Valeur | Pourquoi |
|---|---|---|
| Format de sortie | WAV PCM 16-bit | Sans perte, accepté par MiniMax |
| Fréquence d'échantillonnage | **16 000 Hz** (ou plus) | Voix humaine = 85-8000 Hz ; 16k suffit |
| Canaux | **Mono** | La stéréo n'apporte rien en TTS, double la taille |
| Niveau peak | **−6 dB à −3 dB** (jamais 0 dB) | Éviter le clipping qui tue le clone |
| Niveau RMS moyen | **−18 dB à −12 dB** | Voix audible sans compression |
| Durée utile | **30 à 60 secondes** | <30s = refus ; >60s = perte de temps |

### Dans Audacity :

1. **Fichier → Préférences → Qualité → Fréquence d'échantillonnage du projet : 16000**.
2. Sélectionner le micro en entrée, vérifier le niveau d'entrée (évier le rouge).
3. Enregistrer sur une piste Mono.
4. Après la prise : sélectionner toute la piste → **Effet → Normalisation → −3 dB, pas de DC**.
5. Couper les blancs de début/fin (`Shift+Home` / `Shift+End`).
6. **Fichier → Exporter → Exporter en WAV → WAV (Microsoft) signed 16-bit PCM**.
7. Nommer : `shugu_sample.wav` et enregistrer dans `assets/voice/`.

---

## 4. Ce que tu dois lire (script)

Le clone apprend d'autant mieux que ton sample couvre les **voyelles
françaises fermées et ouvertes** (`a`, `e`, `é`, `è`, `ê`, `i`, `o`, `u`), les
**consonnes occlusives** (p/t/k/b/d/g) et **fricatives** (f/v/s/z/ch/j), des
**nasales** (on, an, un, in), ainsi qu'un peu de prosodie variée (phrases
affirmatives + questions + exclamations).

**Tonalité à donner** : Shugu est **enjouée, curieuse, un peu taquine**, pas
hystérique. Parle comme si tu discutais avec un pote, pas comme un présentateur
télé. **Pas de cri**, même joyeux — ça dégrade le clone.

### Script proposé (≈ 45 secondes à débit normal) — **à adapter si tu veux**

> Coucou, moi c'est Shugu ! Je suis contente de te rencontrer aujourd'hui.
> J'ai plein de choses à te raconter, mais promis, je vais pas tout balancer
> d'un coup. On a le temps. Dis-moi plutôt, toi, comment tu vas ?
>
> Tu sais, parfois je me demande ce que ça fait, de voir le monde depuis
> l'autre côté de l'écran. Les couleurs, les sons, les gens qui passent — on
> parle jamais vraiment de ces petits riens, et pourtant, c'est eux qui font
> que chaque jour est différent, non ?
>
> Allez, raconte. Je t'écoute.

**Important** : si tu préfères une autre vibe pour Shugu (plus calme, plus
espiègle, plus adulte), **récris ce paragraphe à ton goût avant de lire**. La
voix clonée portera le ton que tu donnes à la prise. C'est **une décision
d'incarnation**, pas juste technique.

### À éviter

- Lire à voix plate et monocorde → clone sans émotion.
- Surjouer théâtralement → clone instable sur les intonations extrêmes.
- Enchaîner sans respirer → clone essoufflé.
- Lire trop près du micro (effet de proximité) → clone avec basses excessives.

---

## 5. Upload + clonage

Une fois `assets/voice/shugu_sample.wav` prêt :

```bash
# 1. Exporte ta clé API MiniMax (si pas déjà dans l'env)
export MINIMAX_API_KEY="ton-api-key-minimax"

# 2. Lance le script de clonage
python tools/voice_clone/upload_clone.py \
    --sample assets/voice/shugu_sample.wav \
    --name shugu_fr_v1
```

Le script va :

1. Uploader le WAV vers `/v1/files/upload?purpose=voice_clone` → récupère un `file_id`.
2. Appeler `/v1/voice_clone` avec le `file_id` + le nom `shugu_fr_v1` (ton choix).
3. Afficher le `voice_id` final (identique au nom que tu as donné).

> Le `--name` est libre — tu peux itérer `shugu_fr_v1`, `v2`, etc. pour garder
> trace des prises successives.

---

## 6. Brancher le clone dans l'app

1. Édite `ops/env/.env` :

   ```
   MINIMAX_VOICE_ID=shugu_fr_v1
   ```

2. Redémarre le backend :

   ```bash
   pm2 restart shugu-backend   # prod
   # ou dev : kill + relance uvicorn
   ```

3. Ouvre `/operator` et fais parler Shugu. Tu devrais entendre ta voix
   (clonée, pas une imitation parfaite — environ 85-95% de ressemblance selon
   la qualité du sample).

---

## 7. Troubleshooting

| Symptôme | Cause probable | Remède |
|---|---|---|
| `ERROR [upload] HTTP 413` | Sample > 20 MB | Ré-exporter en 16 kHz mono (pas 44.1 kHz stéréo) |
| `ERROR [clone] status_code=1010` | Sample jugé de trop mauvaise qualité | Ré-enregistrer avec moins de bruit de fond, moins de clipping |
| `ERROR [clone] status_code=2013` | `voice_id` déjà utilisé | Change le `--name` (`shugu_fr_v2`) |
| Voix clonée sonne bizarrement robotique | Sample trop court, monocorde ou en chuchotant | Prise plus longue (60 s), plus expressive |
| Voix clonée mange des syllabes | Niveau trop bas, bruit de fond, respirations fortes | Normaliser à −3 dB, couper les respirations fortes |
| Voix clonée avec accent étranger | Le clone s'est trop appuyé sur quelques mots | Enregistrer un texte plus varié (cf. section 4) |

---

## 8. Versionner

Les samples `.wav/.mp3` dans `assets/voice/` sont **ignorés par git** (voir
`assets/voice/README.md`). Si tu veux garder une trace de la prise, copie-la
dans un dossier privé (pas le repo).

Le `voice_id` côté MiniMax est, lui, persistant et attaché à ton compte : tu
peux le retrouver à tout moment via l'interface MiniMax ou en listant les
voices avec l'API. Pas besoin de le sauvegarder autrement que dans `.env`.
