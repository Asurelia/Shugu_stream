"""Test d'architecture : les brains conversationnels n'importent pas l'implémentation mémoire.

Règle : `brain_shugu.py`, `brain_filter.py`, `brain_hermes.py`, `brain_hermes_tools.py`
et les brains Director ne doivent JAMAIS importer :
- `pgvector`
- `sqlalchemy` (sauf des modules neutres genre `sqlalchemy.types`)
- `MemoryAgent` (l'implémentation)
- `MemoryFact` (le ORM row — détail d'impl)

Autorisé :
- `core.protocols.MemoryService` (le contract public)
- `memory.types.MemoryItem`, `memory.types.RecallQuery` (DTOs publics, stdlib only)

NOTE : `brain_memory_extractor.py` est EXCLU du scope — c'est l'extracteur LLM
dédié qui importait légitimement `memory.types.MemoryItem` (un DTO public, pas
une impl lourde). Ce brain est l'exception justifiée : son rôle est précisément
de produire des `MemoryItem`. Le présent test ne couvre que les brains
conversationnels + Director.
"""
from __future__ import annotations

import ast
import pathlib

# Scope : brains conversationnels + Director.
# `brain_memory_extractor` est exclu (cf. docstring).
_SCOPED_BRAIN_PREFIXES = (
    "brain_shugu",
    "brain_filter",
    "brain_hermes",
    "brain_director",
)

# Imports interdits dans les brains conversationnels.
FORBIDDEN_IN_BRAIN = (
    "pgvector",
    "MemoryAgent",
    "MemoryFact",
)


def _is_scoped(filename: str) -> bool:
    """Retourne True si le fichier est dans le scope du test."""
    return any(filename.startswith(prefix) for prefix in _SCOPED_BRAIN_PREFIXES)


def test_brain_does_not_import_memory_implementation() -> None:
    """Vérifie qu'aucun brain conversationnel n'importe l'implémentation mémoire.

    Utilise `ast` pour parser statiquement les imports — rapide, déterministe,
    aucun side-effect de chargement de module.
    """
    brain_dir = pathlib.Path(__file__).parent.parent.parent / "shugu" / "adapters"
    assert brain_dir.is_dir(), f"répertoire adapters introuvable : {brain_dir}"

    brain_files = [
        f for f in brain_dir.glob("brain_*.py")
        if _is_scoped(f.name)
    ]
    assert brain_files, (
        f"Aucun fichier brain trouvé dans {brain_dir} correspondant aux préfixes {_SCOPED_BRAIN_PREFIXES}"
    )

    violations: list[str] = []
    for f in sorted(brain_files):
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
                    if forbidden in line:
                        violations.append(
                            f"{f.name} (ligne {node.lineno}): importe interdit "
                            f"'{forbidden}' — {line!r}"
                        )

    assert not violations, (
        "Violations d'isolation mémoire détectées dans les brains :\n"
        + "\n".join(f"  • {v}" for v in violations)
    )
