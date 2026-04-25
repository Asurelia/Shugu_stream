"""Test d'architecture : les brains conversationnels et Director n'importent pas l'implémentation mémoire.

Règle : `brain_shugu.py`, `brain_filter.py`, `brain_hermes.py`, `brain_hermes_tools.py`,
les brains Director, et les composants Director ne doivent JAMAIS importer :
- `pgvector`
- `sqlalchemy` (sauf des modules neutres genre `sqlalchemy.types`, `sqlalchemy.dialects.postgresql`)
- `MemoryAgent` (l'implémentation)
- `MemoryFact` (le ORM row — détail d'impl)

Autorisé :
- `core.protocols.MemoryService` (le contract public)
- `memory.types.MemoryItem`, `memory.types.RecallQuery` (DTOs publics, stdlib only)
- `sqlalchemy.types` et `sqlalchemy.dialects.postgresql` (imports neutres, non-impl)

NOTE : `brain_memory_extractor.py` est EXCLU du scope — c'est l'extracteur LLM
dédié qui importait légitimement `memory.types.MemoryItem` (un DTO public, pas
une impl lourde). Ce brain est l'exception justifiée : son rôle est précisément
de produire des `MemoryItem`. Le présent test couvre les brains
conversationnels + tous les fichiers dans `shugu/director/`.

Autres exclusions intentionnelles :
- `backend/shugu/director/models_director.py` — ORM model file, not a logic file
- `backend/shugu/director/tick_cache.py` — data access layer (imports sqlalchemy lazily)
"""
from __future__ import annotations

import ast
import pathlib

# Scope : brains conversationnels + tous les fichiers dans director/
# `brain_memory_extractor` est exclu (cf. docstring).
_SCOPED_BRAIN_PREFIXES = (
    "brain_shugu",
    "brain_filter",
    "brain_hermes",
    "brain_director",
)

# Imports interdits dans les brains conversationnels et Director logic.
FORBIDDEN_IN_BRAIN = (
    "pgvector",
    "MemoryAgent",
    "MemoryFact",
    "sqlalchemy",
)


def _is_scoped_brain(filename: str) -> bool:
    """Retourne True si le fichier brain est dans le scope du test."""
    return any(filename.startswith(prefix) for prefix in _SCOPED_BRAIN_PREFIXES)


def _is_scoped_director_logic(filename: str) -> bool:
    """Retourne True si le fichier director est une logique (pas un modèle ou DAO)."""
    # Exclusions intentionnelles — fichiers qui peuvent importer sqlalchemy:
    # - models_director.py (ORM model definition)
    # - tick_cache.py (data access layer avec imports locaux dans les méthodes)
    excluded = {"models_director.py", "tick_cache.py"}
    return filename not in excluded


def test_brain_and_director_dont_import_memory_implementation() -> None:
    """Vérifie qu'aucun brain conversationnel ni composant Director n'importe l'implémentation mémoire.

    Utilise `ast` pour parser statiquement les imports — rapide, déterministe,
    aucun side-effect de chargement de module.

    Scope:
    1. Brains conversationnels : `brain_*.py` dans `shugu/adapters/` (sauf brain_memory_extractor)
    2. Composants Director : tous les fichiers dans `shugu/director/` sauf les DAO/ORM
       (models_director.py, tick_cache.py)

    Règles d'isolation :
    - Interdits : pgvector, MemoryAgent, MemoryFact, sqlalchemy
    - Exceptions : sqlalchemy.types, sqlalchemy.dialects.postgresql (modules neutres)
    """
    backend_dir = pathlib.Path(__file__).parent.parent.parent
    adapters_dir = backend_dir / "shugu" / "adapters"
    director_dir = backend_dir / "shugu" / "director"

    assert adapters_dir.is_dir(), f"répertoire adapters introuvable : {adapters_dir}"
    assert director_dir.is_dir(), f"répertoire director introuvable : {director_dir}"

    # Collecter les fichiers brains à scanner
    brain_files = [
        f for f in adapters_dir.glob("brain_*.py")
        if _is_scoped_brain(f.name) and f.name != "brain_memory_extractor.py"
    ]

    # Collecter les fichiers director logic à scanner
    director_files = [
        f for f in director_dir.glob("*.py")
        if f.name != "__init__.py" and _is_scoped_director_logic(f.name)
    ]

    all_files = brain_files + director_files
    assert all_files, (
        f"Aucun fichier à scanner trouvé dans {adapters_dir} ou {director_dir}"
    )

    violations: list[str] = []
    for f in sorted(all_files):
        source = f.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source, filename=str(f))
        except SyntaxError as exc:
            violations.append(f"{f.name}: erreur de syntaxe — {exc}")
            continue

        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                line = ast.unparse(node)
                for forbidden in FORBIDDEN_IN_BRAIN:
                    if forbidden not in line:
                        continue

                    # Allowlist : sqlalchemy.types et sqlalchemy.dialects sont acceptés
                    if forbidden == "sqlalchemy":
                        if "sqlalchemy.types" in line or "sqlalchemy.dialects" in line:
                            continue

                    violations.append(
                        f"{f.name} (ligne {node.lineno}): importe interdit "
                        f"'{forbidden}' — {line!r}"
                    )

    assert not violations, (
        "Violations d'isolation mémoire détectées :\n"
        + "\n".join(f"  • {v}" for v in violations)
    )
