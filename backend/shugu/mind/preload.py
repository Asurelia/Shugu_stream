"""Pré-warm du modèle de fallback (Gemma local) au démarrage.

La décision est une fonction pure (testable) ; l'exécution réelle (un appel
dummy au LocalLLM) est faite dans le lifespan app.py.
"""
from __future__ import annotations


def should_preload_fallback(*, preload: bool, provider: str) -> bool:
    """On ne pré-charge le fallback que si le provider primaire est m3
    (sinon Gemma n'est pas le fallback du Réflexe) ET si le flag est on."""
    return bool(preload) and provider == "m3"
