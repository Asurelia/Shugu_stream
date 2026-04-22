"""Wrappers bcrypt standardisés.

Pourquoi centraliser ? L'op historique `routes/auth.py` utilise `bcrypt.checkpw`
directement. On garde cette compat mais on standardise pour les comptes user
self-service : un seul point de config rounds, hashing, et migration
d'algorithme plus tard si besoin.

Rounds=12 : suffisant pour 2026 (≈200 ms hash sur CPU moderne) sans bloquer
trop longtemps. Si le hardware change (GPU cracking), passer à 14.
"""
from __future__ import annotations

import bcrypt

BCRYPT_ROUNDS = 12


def hash_password(plaintext: str) -> str:
    """Renvoie un hash bcrypt (60 chars UTF-8) à stocker en DB.

    Raise ValueError si le plaintext est vide ou trop long (>72 octets, limite
    bcrypt — au-delà le hash ignore les caractères en trop, ce qui est
    silencieusement dangereux).
    """
    if not plaintext:
        raise ValueError("password empty")
    encoded = plaintext.encode("utf-8")
    if len(encoded) > 72:
        raise ValueError("password too long (>72 bytes after UTF-8 encoding)")
    return bcrypt.hashpw(encoded, bcrypt.gensalt(rounds=BCRYPT_ROUNDS)).decode("ascii")


def verify_password(plaintext: str, hashed: str) -> bool:
    """Constant-time verification. Renvoie False si plaintext vide ou hash invalide."""
    if not plaintext or not hashed:
        return False
    try:
        return bcrypt.checkpw(plaintext.encode("utf-8"), hashed.encode("ascii"))
    except ValueError:
        # Bcrypt raise sur hash mal formé. On traite comme mismatch pour éviter
        # de distinguer "hash inexistant" de "mauvais password" côté client.
        return False
