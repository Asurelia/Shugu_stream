"""`SceneStateSnapshot` — snapshot compact de l'état de scène.

Contrat Phase E1 :
- Sérialisation JSON < 500 bytes (viser 50-80 tokens) pour rester injectable
  dans chaque prompt Shugu sans faire exploser le contexte.
- `recent_events` borné à 10 (FIFO) pour garder la taille stable dans le
  temps — même si les triggers spamment, le snapshot reste compact.

Ce module NE doit pas importer de code runtime (pas de FastAPI, pas de DB) :
les dataclasses sont pures, sérialisables, et testables en isolation.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Literal

# Taille max recommandée en bytes pour la sérialisation JSON d'un snapshot.
# Dépasser ce seuil ne lève PAS d'exception (le caller décide) — c'est un
# soft-limit contractuel, validé par `to_dict_json_size()` et par les tests.
MAX_SNAPSHOT_JSON_BYTES = 500

# Nombre max d'events stockés dans `recent_events` (FIFO trim auto).
MAX_RECENT_EVENTS = 10

CameraMode = Literal["auto", "close_up", "wide"]


@dataclass(slots=True)
class SceneStateSnapshot:
    """Snapshot compact de l'état de scène injecté dans le prompt Shugu.

    Champs :
    - `scene`            slug court de la scène courante (ex: "main_talk").
    - `outfit`           slug outfit actif (ex: "default", "vip_fan").
    - `face`             expression faciale macro (ex: "neutral", "happy").
    - `active_vfx`       liste des slugs VFX actuellement joués à l'écran.
    - `camera_mode`      caméra macro ("auto" laisse le director décider).
    - `recent_events`    derniers events pertinents au format free-text court,
                         bornés à `MAX_RECENT_EVENTS` (FIFO), ex:
                         "chat:alice:hello" ou "vip_arrival:bob".
    - `chat_peers`       usernames actifs dans le chat récent (hint social).
    - `assets_available` dictionnaire `{"outfits": [...], "vfx": [...],
                         "anims": [...]}` exposé au LLM pour qu'il ne
                         n'invente pas de slugs hors de la bank.
    """

    scene: str = "main_talk"
    outfit: str = "default"
    face: str = "neutral"
    active_vfx: list[str] = field(default_factory=list)
    camera_mode: CameraMode = "auto"
    recent_events: list[str] = field(default_factory=list)
    chat_peers: list[str] = field(default_factory=list)
    assets_available: dict[str, list[str]] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Sérialise en `dict` JSON-safe (deep-copy des nested via `asdict`).

        Utilise `dataclasses.asdict` qui copie récursivement listes/dicts ;
        le retour peut être muté sans polluer l'instance source.
        """
        return asdict(self)

    def to_json_bytes(self) -> int:
        """Retourne la taille en bytes d'une sérialisation JSON compacte.

        Utilisé par les tests pour vérifier qu'un snapshot "plein" reste sous
        `MAX_SNAPSHOT_JSON_BYTES`. `json.dumps(..., separators=(",", ":"))`
        produit la forme la plus compacte, ce qui colle à ce qu'on
        sérialiserait réellement en prompt.
        """
        return len(json.dumps(self.to_dict(), separators=(",", ":"), ensure_ascii=False).encode("utf-8"))

    @classmethod
    def from_dict(cls, data: dict) -> "SceneStateSnapshot":
        """Reconstruit un snapshot depuis un dict (ex: déserialisation Redis).

        Ignore les clés inconnues pour rester forward-compat. Les listes
        manquantes retombent sur `default_factory`.
        """
        return cls(
            scene=data.get("scene", "main_talk"),
            outfit=data.get("outfit", "default"),
            face=data.get("face", "neutral"),
            active_vfx=list(data.get("active_vfx") or []),
            camera_mode=data.get("camera_mode", "auto"),
            recent_events=list(data.get("recent_events") or []),
            chat_peers=list(data.get("chat_peers") or []),
            assets_available={
                k: list(v or [])
                for k, v in (data.get("assets_available") or {}).items()
            },
        )

    def add_event(self, event: str, max_events: int = MAX_RECENT_EVENTS) -> None:
        """Append `event` à `recent_events` et trim FIFO à `max_events`.

        Mute le snapshot in-place — caller doit savoir qu'il détient une
        instance mutable. Le `DirectorStateStore` protège cette mutation
        par un `asyncio.Lock` côté store.
        """
        self.recent_events.append(event)
        # Trim par le début (FIFO) — garde les plus récents.
        overflow = len(self.recent_events) - max_events
        if overflow > 0:
            del self.recent_events[:overflow]
