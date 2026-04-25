# Mixamo VRMA Animation Bank — ETL Workflow

**Status**: Phase E4 — MVP animation bank for autonomous Shugu AI director.

**Audience**: Animation artists, pipeline engineers, content creators.

---

## Table des matières

1. [Overview](#overview)
2. [Workflow complet](#workflow-complet)
   - [1. Télécharger une animation Mixamo](#1-télécharger-une-animation-mixamo)
   - [2. Préparer l'environnement de conversion](#2-préparer-lenvironnement-de-conversion)
   - [3. Exécuter le script de conversion](#3-exécuter-le-script-de-conversion)
   - [4. Valider le VRMA produit](#4-valider-le-vrma-produit)
   - [5. Déployer dans Shugu](#5-déployer-dans-shugu)
3. [30 animations MVP — Roadmap](#30-animations-mvp--roadmap)
4. [Licensing & Attribution](#licensing--attribution)
5. [Troubleshooting](#troubleshooting)

---

## Overview

Cette pipeline ETL **convertit automatiquement des animations Mixamo (FBX)** en **VRMA (VRM Animation, format @pixiv/three-vrm)** compatible avec le VRM humanoid standard.

**Pourquoi Mixamo → VRMA ?**

- **Mixamo** : Banque gratuite (avec compte Adobe) d'animations humanoid de haute qualité, exportables en FBX avec squelette `mixamorig:*`
- **VRMA** : Format léger, format standard pour VRM 1.0, optimisé pour WebGL/Three.js
- **Shugu** : Director autonome qui demande au LLM d'émettre des tags comme `[anim:wave]`, consommes sans retarget runtime coûteux

**Architecture**:

```
Mixamo FBX (T-pose + animation)
    ↓ [Blender Python script]
    ├─ Import FBX (mixamorig:Hips, mixamorig:Spine, etc.)
    ├─ Load reference VRM skeleton (for standard bone names)
    ├─ Retarget bones Mixamo → VRM (standard mapping)
    ├─ Bake animation keyframes
    └─ Export GLB + metadata JSON
    ↓
VRMA (GLB + .meta.json sidecar)
    ↓
frontend/public/assets/vrma/{slug}.vrma
    ↓
Director LLM → [anim:{slug}] → SceneStateSnapshot.assets_available["anims"]
```

---

## Workflow complet

### 1. Télécharger une animation Mixamo

#### 1.1 Créer un compte Adobe gratuit

1. Accédez à https://www.mixamo.com/
2. Créez un compte gratuit (email ou social login)
3. Connectez-vous

#### 1.2 Chercher une animation

1. Cliquez sur **Browse** (barre supérieure)
2. Filtrez par catégorie :
   - **Idle** (animations de repos) : `idle_loop`, `idle_breathing`, `idle_lookaround`, etc.
   - **Greetings** : `wave`, `bow`, `salute`, etc.
   - **Reactions** : `thumbs_up`, `clap`, `jump`, etc.
   - **Emotes** : `dance`, `shy_giggle`, `thinking`, etc.
   - **Talk** : `talk_explain`, `nod`, `headshake`, etc.
3. Prévisualiser le mouvement (bouton **Play**)
4. Cliquer sur l'animation pour ouvrir le détail

#### 1.3 Exporter en FBX

1. Dans la page de détail de l'animation, cliquez sur **Download**
2. Sélectionnez les options de export :
   - **Format** : `FBX for Unreal Engine 4.0 / 4.22 / 4.23+` (or any recent FBX)
   - **Skin** : Inclure le mesh (ou déselect si animation-only)
   - **In Place** : Déselect (on veux la translation XZ du mouvement)
   - **Framerate** : 30 FPS (standard)
3. Cliquez **Download**
4. Sauvegardez dans un dossier local (ex: `~/mixamo_exports/`)

**Note**: Mixamo génère des animations en T-pose standard, avec un squelette `mixamorig:*` qui se mappe facilement en VRM humanoid.

---

### 2. Préparer l'environnement de conversion

#### 2.1 Installer Blender

- **Windows/Mac/Linux**: Téléchargez Blender >= 3.4 depuis https://www.blender.org/download/
- **Vérifiez l'installation** :
  ```bash
  blender --version
  # Output: Blender 4.0.0 ... (ou similaire)
  ```

#### 2.2 Installer le VRM Addon pour Blender

Le script utilise `bpy.ops.import_scene.gltf()` pour charger des fichiers VRM. Le VRM Addon facilite l'import/export VRM standard.

1. Téléchargez le VRM Addon depuis https://github.com/Saturday06/VRM_Addon_for_Blender/releases
2. Décompressez le dossier (ex: `VRM_Addon_for_Blender-*`)
3. Installez dans Blender :
   - Ouvrez **Preferences** → **Add-ons** → **Install...**
   - Sélectionnez le dossier VRM Addon
   - Activez le checkbox **Import-Export: VRM format** ✓

#### 2.3 Préparer un avatar VRM de référence

Vous avez besoin d'un fichier VRM comme référence squelette. Deux options :

**Option A (Recommandée)** : Téléchargez un avatar VRM gratuit
- https://hub.vroid.com (VRoid Studio avatars)
- https://3d.nicodo.jp/ (Japanese VRM library)
- Cliquez sur un avatar → **Download** (.vrm)

**Option B** : Utilisez l'avatar Shugu existant
- Si vous avez déjà un `.vrm` dans le projet, réutilisez-le comme référence

Sauvegardez le fichier `.vrm` dans un dossier local (ex: `~/vrm_refs/avatar.vrm`).

#### 2.4 Cloner le script ETL

```bash
cd /f/Dev/Fork/Shugu_stream
git pull origin main
# Le script est à : tools/mixamo_etl/mixamo_to_vrma_blender.py
```

---

### 3. Exécuter le script de conversion

#### 3.1 Commande de base

Ouvrez un terminal dans le dossier du projet et exécutez :

```bash
blender --python tools/mixamo_etl/mixamo_to_vrma_blender.py -- \
    --input-fbx ~/mixamo_exports/wave.fbx \
    --reference-vrm ~/vrm_refs/avatar.vrm \
    --output-vrma /tmp/wave \
    --slug wave
```

**Paramètres** :

| Param | Exemple | Description |
|-------|---------|-------------|
| `--input-fbx` | `~/wave.fbx` | Chemin du fichier Mixamo FBX |
| `--reference-vrm` | `~/avatar.vrm` | Chemin du VRM de référence (pour le squelette) |
| `--output-vrma` | `/tmp/wave` | Chemin de sortie (sans .vrma extension) |
| `--slug` | `wave` | Identifiant animation (lowercase, snake_case) |
| `--frame-range` | `0 120` | Optionnel : range de frames (défaut: toutes) |
| `--fps` | `30` | Optionnel : frames per second (défaut: 30) |

#### 3.2 Mode GUI (pour debug)

Sans `--background`, Blender ouvre l'UI :

```bash
blender --python tools/mixamo_etl/mixamo_to_vrma_blender.py -- \
    --input-fbx ~/mixamo_exports/wave.fbx \
    --reference-vrm ~/vrm_refs/avatar.vrm \
    --output-vrma /tmp/wave \
    --slug wave
```

**Avantages** :
- Visualisez la retarget en temps réel
- Inspecter les keyframes Blender
- Debug les erreurs d'import

**Durée typique** : 30 secondes à 2 minutes selon la longueur animation.

#### 3.3 Mode batch (production)

Pour convertir plusieurs fichiers en série :

```bash
#!/bin/bash
# scripts/convert_mixamo_batch.sh

ANIMS=(
    "wave:~/mixamo_exports/wave.fbx"
    "dance:~/mixamo_exports/dance.fbx"
    "bow:~/mixamo_exports/bow.fbx"
)

VRM_REF=~/vrm_refs/avatar.vrm
OUTPUT_DIR=$(pwd)/frontend/public/assets/vrma

for anim in "${ANIMS[@]}"; do
    IFS=':' read -r slug fbx_path <<< "$anim"
    echo "Converting $slug..."
    blender --background --python tools/mixamo_etl/mixamo_to_vrma_blender.py -- \
        --input-fbx "$fbx_path" \
        --reference-vrm "$VRM_REF" \
        --output-vrma "$OUTPUT_DIR/$slug" \
        --slug "$slug"
    echo "✓ $slug.vrma"
done
```

---

### 4. Valider le VRMA produit

Après export, deux fichiers sont générés :

```
wave.vrma                  # GLB (gltf binary) avec armature + animation
wave.vrma.meta.json        # Metadata sidecar
```

#### 4.1 Test rapide avec pytest

```bash
cd /f/Dev/Fork/Shugu_stream
python -m pytest backend/scripts/test_vrma_loader.py::test_vrma_metadata_validity -v
```

**Output** :

```
test_vrma_metadata_validity PASSED
✓ Passed: 1
  - wave.vrma
```

#### 4.2 Validation manuelle

Inspecter le metadata JSON :

```bash
cat wave.vrma.meta.json
```

**Output attendu** :

```json
{
  "format": "vrma",
  "version": "1.0",
  "slug": "wave",
  "frame_count": 60,
  "fps": 30.0,
  "duration_seconds": 2.0,
  "retarget_source": "mixamo",
  "retarget_mapping": "vrm_humanoid_standard",
  "export_date": "2026-04-25T21:30:45.123456+00:00"
}
```

**Vérifications** :

- ✓ `frame_count > 0` (au moins 1 frame)
- ✓ `fps > 0` (standard 24, 30, ou 60)
- ✓ `slug` = identifiant lisible (lowercase, `_` pour séparateurs)
- ✓ Fichier `.vrma` > 10 KB (sinon corruption possible)

#### 4.3 Test Three.js (optionnel)

Si vous avez Node.js et Three.js :

```javascript
// test_vrma_load.js
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { VRMLoaderPlugin } from '@pixiv/three-vrm';

const loader = new GLTFLoader();
loader.register(vrm => new VRMLoaderPlugin(vrm));

loader.load('wave.vrma', (gltf) => {
    const vrm = gltf.userData.vrm;
    console.log('✓ VRMA loaded');
    console.log(`  Humanoid bones: ${Object.keys(vrm.humanoid.humanBones).length}`);
    console.log(`  Animations: ${gltf.animations.length}`);
});
```

---

### 5. Déployer dans Shugu

#### 5.1 Copier dans le dossier assets

```bash
cp /tmp/wave.vrma frontend/public/assets/vrma/
cp /tmp/wave.vrma.meta.json frontend/public/assets/vrma/
```

**Résultat** :

```
frontend/public/assets/vrma/
├── README.md
├── wave.vrma
├── wave.vrma.meta.json
├── bow.vrma
├── bow.vrma.meta.json
└── ... (30 autres animations)
```

#### 5.2 Ajouter au whitelist `assets_available`

La configuration est dans `backend/shugu/app.py` ligne 340-347 :

```python
await director_state_store.update({
    "assets_available": {
        # ... outfits, vfx, scenes ...
        "anims": [
            "wave",           # ✓ new
            "excited_wave",   # existing
            "bow",            # ✓ new
            "shy_giggle",
            "dance",          # ✓ new
            # ... add all 30 slugs here ...
        ],
    }
})
```

#### 5.3 Redémarrer le service

```bash
# Développement local
docker-compose restart backend

# Ou si vous tournez directement :
cd backend && uvicorn shugu.app:create_app --reload
```

#### 5.4 Valider en production

Le Director LLM peut maintenant émettre des tags :

```
[anim:wave]  ← Le backend vérifie que "wave" ∈ assets_available["anims"]
[anim:dance] ← OK ✓
[anim:jump]  ← NOT in whitelist → rejected silently
```

Le viewer Three.js charge l'animation :

```javascript
// Via SceneStateSnapshot
const scene = viewer.state;
if (scene.assets_available.anims.includes('wave')) {
    await viewer.playAnimation('wave');  // Loads /assets/vrma/wave.vrma
}
```

---

## 30 animations MVP — Roadmap

Liste proposée pour une banque d'animations Shugu MVP. Groupées par catégorie.

### Idle & AFK (5)

| Slug | Description | Mixamo URL | Priority |
|------|-------------|-----------|----------|
| `idle_loop` | Repos neutre, breathing idle | [Idle](https://www.mixamo.com/search?query=idle) | **P0** |
| `idle_breathing` | Idle avec respiration accentuée | [Breathing](https://www.mixamo.com/search?query=breathing) | P1 |
| `idle_lookaround` | Idle avec head turns | [Look Around](https://www.mixamo.com/search?query=look%20around) | P1 |
| `idle_stretch` | Étirement, idle variation | [Stretch](https://www.mixamo.com/search?query=stretch) | P2 |
| `idle_yawn` | Baillement | [Yawn](https://www.mixamo.com/search?query=yawn) | P2 |

### Greetings (5)

| Slug | Description | Mixamo URL | Priority |
|------|-------------|-----------|----------|
| `wave` | Salut main levée | [Wave](https://www.mixamo.com/search?query=wave) | **P0** |
| `wave_excited` | Salut enthousiaste, deux mains | [Wave Excited](https://www.mixamo.com/search?query=excited%20wave) | P1 |
| `bow` | Salut japonais, courbette | [Bow](https://www.mixamo.com/search?query=bow) | **P0** |
| `salute` | Salut militaire | [Salute](https://www.mixamo.com/search?query=salute) | P2 |
| `peace_sign` | Signe de la victoire/paix | [Peace](https://www.mixamo.com/search?query=peace) | P1 |

### Reactions & Emotes (5)

| Slug | Description | Mixamo URL | Priority |
|------|-------------|-----------|----------|
| `thumbs_up` | Approbation, thumbs up | [Thumbs Up](https://www.mixamo.com/search?query=thumbs%20up) | **P0** |
| `clap` | Applaudissements | [Clap](https://www.mixamo.com/search?query=clap) | **P0** |
| `cheer` | Acclamations, victoire | [Cheer](https://www.mixamo.com/search?query=cheer) | P1 |
| `fist_pump` | Poing levé, célébration | [Fist Pump](https://www.mixamo.com/search?query=fist%20pump) | P1 |
| `surprised_jump` | Saut surpris | [Surprised](https://www.mixamo.com/search?query=surprised) | P2 |

### Emotes & Personality (5)

| Slug | Description | Mixamo URL | Priority |
|------|-------------|-----------|----------|
| `dance` | Danse simple, enthousiaste | [Dance](https://www.mixamo.com/search?query=dance) | **P0** |
| `dance_silly` | Danse ridicule, silly | [Silly Dance](https://www.mixamo.com/search?query=silly%20dance) | P1 |
| `shy_giggle` | Gloussement timide | [Giggle](https://www.mixamo.com/search?query=giggle) | **P0** |
| `shy_hide` | Cache timide, embarrassed | [Embarrassed](https://www.mixamo.com/search?query=embarrassed) | P2 |
| `thinking` | Réflexion, posture pensif | [Thinking](https://www.mixamo.com/search?query=thinking) | **P0** |

### Talk Gestures (5)

| Slug | Description | Mixamo URL | Priority |
|------|-------------|-----------|----------|
| `talk_explain` | Explication avec gestes | [Talking](https://www.mixamo.com/search?query=talking) | P1 |
| `talk_emphasize` | Emphase, geste fort | [Emphasizing](https://www.mixamo.com/search?query=emphasize) | P2 |
| `nod` | Hochement de tête | [Nod](https://www.mixamo.com/search?query=nod) | P1 |
| `headshake` | Secouement de tête | [Head Shake](https://www.mixamo.com/search?query=head%20shake) | P1 |
| `shrug` | Haussement d'épaules | [Shrug](https://www.mixamo.com/search?query=shrug) | P1 |

### Daily Life (5)

| Slug | Description | Mixamo URL | Priority |
|------|-------------|-----------|----------|
| `read_book` | Lire un livre | [Reading](https://www.mixamo.com/search?query=reading) | P2 |
| `sip_drink` | Boire une boisson | [Drinking](https://www.mixamo.com/search?query=drinking) | P2 |
| `doodle` | Dessiner, gribouillis | [Drawing](https://www.mixamo.com/search?query=drawing) | P2 |
| `type_keyboard` | Taper au clavier | [Typing](https://www.mixamo.com/search?query=typing) | P1 |
| `stretch_long` | Grand étirement complet | [Stretching](https://www.mixamo.com/search?query=stretching) | P1 |

---

## Licensing & Attribution

**Important: Mixamo Terms of Service**

Toutes les animations Mixamo sont téléchargées sous la **Mixamo Licence d'Adobe**. Vérifiez les conditions :

- ✓ **Usage personnel** : Autorisé
- ✓ **Usage commercial** : Autorisé (y compris streaming, monétisation)
- ✓ **Modification** : Autorisée (retargeting, retiming)
- ✗ **Redistribution des fichiers FBX bruts** : **NOT ALLOWED** (cf. Mixamo ToS §5)
- ✗ **Hébergement direct de fichiers Mixamo FBX** : NOT ALLOWED

**Shugu Compliance**:

- Cette pipeline produit des fichiers **VRMA (GLB convertis)**, pas des FBX Mixamo directs.
- Les fichiers FBX originaux Mixamo ne sont **JAMAIS stockés** dans le repo.
- Les fichiers VRMA produits sont des **dérivés transformés**, légalement acceptables sous les termes Mixamo.

**Attribution**:

Si vous hébergez les VRMA publiquement, incluez une note dans les crédits :

```
Animations: Mixamo (Adobe Inc.)
Retargeted to VRM Humanoid Standard
Converted via Shugu Animation Bank ETL
```

---

## Troubleshooting

### Erreur : "No Armature found in FBX"

**Cause** : Le fichier FBX n'est pas un Mixamo humanoid standard, ou l'import FBX a échoué.

**Solution** :

1. Vérifiez que l'export Mixamo inclut le squelette (options export)
2. Ouvrez le FBX dans Blender manuellement pour vérifier les bones
3. Re-téléchargez l'animation depuis Mixamo avec options par défaut

### Erreur : "Reference VRM has no Armature"

**Cause** : Le fichier VRM ne contient pas de squelette.

**Solution** :

1. Vérifiez que le fichier .vrm est valide (ouvrez-le dans Blender VRM Addon)
2. Téléchargez un autre VRM depuis https://hub.vroid.com

### Erreur : "VRM Addon not found"

**Cause** : Le VRM Addon n'est pas installé dans Blender.

**Solution** :

1. Installez le VRM Addon (cf. § 2.2)
2. Relancez Blender
3. Vérifiez via **Preferences > Add-ons > Search "VRM"** (doit être ✓)

### Blender freeze ou crash

**Cause** : Retargeting d'une longue animation (1000+ frames) peut être gourmand.

**Solution** :

1. Utilisez l'option `--frame-range` pour exporter juste une portion :
   ```bash
   --frame-range 0 300  # Premières 300 frames
   ```
2. Augmentez la RAM disponible (Blender Settings > Performance)
3. Utilisez `--background` mode (plus rapide, pas d'UI)

### Metadata JSON invalide

**Cause** : Le script a interrompu l'export prématurément.

**Solution** :

1. Vérifiez les logs Blender pour les erreurs
2. Relancez le script
3. Vérifiez les permissions fichier dans `output_vrma` directory

### VRMA chargé mais pas d'animation

**Cause** : Les bones n'ont pas été retargetés correctement, ou les keyframes sont manquantes.

**Solution** :

1. Vérifiez que le fichier GLB a des animations :
   ```bash
   blender wave.vrma  # Ouvrez et inspectez les NLA tracks
   ```
2. Vérifiez la bone mapping (ligne 70+ du script)
3. Relancez avec debug logs (ajouter print statements)

---

## References

- **VRM Specification**: https://github.com/vrm-c/vrm-specification
- **Mixamo**: https://www.mixamo.com/
- **Three.js VRM Loader**: https://github.com/pixiv/three-vrm
- **VRM Addon for Blender**: https://github.com/Saturday06/VRM_Addon_for_Blender
- **Shugu Director Tags**: `backend/shugu/director/tag_parser.py`
