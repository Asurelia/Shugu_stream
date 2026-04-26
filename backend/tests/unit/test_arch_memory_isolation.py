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


# ====================================================================================
# Single-Writer ORM Classes Rule
# ====================================================================================
#
# Les ORM row classes de la mémoire sont partagées entre la couche logique
# (MemoryAgent) et la couche modèle (db/models.py), mais AUCUN autre module
# ne doit les importer.
#
# Justification : MemoryAgent est le single-writer de la table (seul responsable
# des INSERT/UPDATE/DELETE). Toute autre logique qui veut accéder aux données
# doit passer par le protocol public MemoryService ou faire du SELECT-only via
# des fonctions partagées approuvées (comme recall_episodes dans db/queries.py).
#
# Cela garantit :
# - Pas de mutations côté brains/director sans passer par MemoryAgent
# - Audit clair : grep MemoryAgent trouvera tous les sites où on peut write
# - Découplage : les brains ne savent rien de la structure DB des épisodes

SINGLE_WRITER_ORM_CLASSES = {
    "MemoryEpisodeRow": {
        "allowed_modules": {
            "shugu/memory/agent.py",
            "shugu/db/models.py",
        },
        "reason": "Single-writer: MemoryAgent est responsable de tous INSERT/UPDATE/DELETE sur episodes.",
    },
    "MemoryFact": {
        "allowed_modules": {
            "shugu/memory/agent.py",
            "shugu/memory/models.py",
            "shugu/memory/maintenance.py",
        },
        "reason": "Single-writer: seul MemoryAgent insère les facts via store(). maintenance.py est invoqué exclusivement via MemoryAgent.maintenance().",
    },
    "AuthoredSceneRow": {
        "allowed_modules": {
            "shugu/db/models_scene_composer.py",
            "shugu/routes/scene_composer_api.py",
            "shugu/scene_composer/player.py",
            "shugu/app.py",
        },
        "reason": (
            "Single-writer: seul scene_composer_api fait INSERT/UPDATE/DELETE authored_scenes. "
            "player.py et app.py font uniquement des SELECT pour récupérer et exécuter les scènes."
        ),
    },
}


def test_single_writer_orm_classes_not_imported_elsewhere() -> None:
    """Vérifie que les ORM rows mémoire ne sont importés que par MemoryAgent + models.

    Single-writer rule: seul MemoryAgent peut faire INSERT/UPDATE/DELETE sur
    les tables ORM mémoire. Tout autre code qui veut accéder aux données doit
    utiliser le protocol public MemoryService ou des fonctions partagées en
    lecture seule.

    Violation détectée → cela signifie qu'un autre module s'approprie l'écriture
    (mutation) de données mémoire, ce qui compromet l'audit et le découplage.
    """
    backend_dir = pathlib.Path(__file__).parent.parent.parent

    violations: list[str] = []

    for orm_class_name, config in SINGLE_WRITER_ORM_CLASSES.items():
        allowed_modules = config["allowed_modules"]

        # Scanner tous les fichiers .py du backend sauf les tests
        for py_file in sorted(backend_dir.glob("shugu/**/*.py")):
            # Ignorer les fichiers test
            if "/tests/" in str(py_file).replace("\\", "/"):
                continue

            relative = py_file.relative_to(backend_dir)
            relative_str = str(relative).replace("\\", "/")

            # Skip si c'est un fichier autorisé
            if relative_str in allowed_modules:
                continue

            try:
                content = py_file.read_text(encoding="utf-8")
            except Exception:
                continue

            # Chercher des imports ou utilisations du ORM class
            # Patterns courants :
            #   from ... import MemoryEpisodeRow
            #   MemoryEpisodeRow(...)
            #   isinstance(..., MemoryEpisodeRow)
            #   : MemoryEpisodeRow  (type hint)

            # Parse AST pour détecter les imports
            try:
                tree = ast.parse(content, filename=str(py_file))
            except SyntaxError:
                continue

            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    line_text = ast.unparse(node)
                    if orm_class_name in line_text:
                        violations.append(
                            f"{relative_str} (ligne {node.lineno}): "
                            f"importe {orm_class_name} — "
                            f"violation single-writer (allowed: {allowed_modules}). "
                            f"Raison: {config['reason']}"
                        )
                elif isinstance(node, ast.Import):
                    line_text = ast.unparse(node)
                    if orm_class_name in line_text:
                        violations.append(
                            f"{relative_str} (ligne {node.lineno}): "
                            f"importe {orm_class_name} — "
                            f"violation single-writer (allowed: {allowed_modules}). "
                            f"Raison: {config['reason']}"
                        )

    assert not violations, (
        "Violations single-writer ORM détectées :\n"
        + "\n".join(f"  • {v}" for v in violations)
        + "\n\n"
        + "Les ORM rows mémoire doivent rester internes à MemoryAgent + models.py.\n"
        + "Tout autre code utilise le protocol public MemoryService ou des fonctions partagées."
    )
