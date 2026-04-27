"""Test d'architecture L0 — frontières des Layers 1, 2, 3 du streamer IA autonome.

Le streamer IA est découpé en 5 layers :
- L1 = Perception API (Python)         → `shugu/senses/`
- L2 = Agent loop LLM + tools + memory → `shugu/agent/`
- L3 = World Simulator deterministe    → `shugu/world/`
- L4 = Viewer 3D (Three.js / Godot / natif) — frontend, hors scope backend
- L5 = Streaming (OBS / WebRTC / NVENC) — futur

Ce test enforce les règles d'isolation **statiquement** (AST parsing) :

  Règle 1 : `senses/` est une couche feuille — n'importe NI `agent` NI `world`.
  Règle 2 : `agent/` n'importe PAS `world` (consomme L3 via WorldHandle injecté).
  Règle 3 : `world/` n'importe NI `senses` NI `agent` (couche feuille pure).
  Règle 4 : Les 3 layers n'importent rien du frontend (trivially Python, mais
            on enforce qu'ils n'importent pas non plus `scene_composer.player`
            ou similaire qui couplerait L3 à un détail de rendu).

Pourquoi cette discipline ?
- Le viewer (L4) doit pouvoir être SWAPPÉ (Three.js → Godot → Vulkan natif)
  sans toucher L1-L3. Si L3 importe scene_composer ou viewer-specifics, le
  swap devient une refonte.
- Le replay déterministe du World (L3) demande que les reducers soient pures :
  une dépendance vers L1 (senses) introduirait un cycle qui casse la pureté.
- Single-writer : seul `agent` peut muter `world`. Si `senses` pouvait
  importer `world.apply()`, on aurait deux writers concurrents.

Allowlist :
- Tous les layers peuvent importer `core/` (EventBus protocol, errors, identity).
- Tous les layers peuvent importer `config` (Settings).
- `agent/` peut importer `senses.types` (DTOs publics, pas l'implémentation `senses.bus`).
- `agent/` peut importer `world.types` (DTOs publics : Action, WorldState read-only).

Ce test échoue tant que les modules n'existent pas (TDD red) — c'est attendu.
"""
from __future__ import annotations

import ast
import pathlib

# Modules cibles. Chacun doit exister avec un __init__.py.
LAYER_PATHS = {
    "senses": "shugu/senses",
    "agent": "shugu/agent",
    "world": "shugu/world",
}

# Règles d'import : pour chaque layer, set de prefixes interdits.
# Format : "shugu.X" ou "shugu.X.Y" (préfixes complets dot-notation).
FORBIDDEN_IMPORTS = {
    "senses": ("shugu.agent", "shugu.world"),
    "agent": ("shugu.world",),
    "world": ("shugu.senses", "shugu.agent"),
}

# Allowlist d'exceptions : sous-modules `types` publics qu'un layer peut
# légitimement importer même s'il dépend du parent interdit. Ex : `agent`
# peut importer `shugu.world.types` (Action / WorldState DTOs) mais pas
# `shugu.world.state` (l'impl mutable).
ALLOWED_TYPES_IMPORTS = {
    "agent": ("shugu.world.types",),
}


def _layer_dir(repo_root: pathlib.Path, layer: str) -> pathlib.Path:
    return repo_root / "backend" / LAYER_PATHS[layer]


def _backend_root() -> pathlib.Path:
    """Remonte depuis ce fichier de test vers la racine du repo."""
    # tests/unit/test_arch_layers_l0.py → ../../.. → repo root
    return pathlib.Path(__file__).resolve().parents[3]


def _import_lines(tree: ast.AST) -> list[tuple[int, str]]:
    """Extrait toutes les lignes d'import sous forme dot-notation.

    Pour `from .agent import Foo` (relatif), `ast.unparse` renvoie
    `from .agent import Foo` qu'on ne peut pas matcher directement. On
    normalise : pour `ImportFrom` avec `level > 0`, on saute (les imports
    relatifs internes au layer sont permis ; un layer ne peut pas remonter
    avec `..agent` sans que ça apparaisse aussi comme `shugu.agent` dans
    l'arbre absolu si on parse un fichier dans `shugu/X/`).
    """
    lines: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                lines.append((node.lineno, alias.name))
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                # Import relatif — résolu en absolu plus loin par _absolute_module.
                lines.append((node.lineno, f"__relative__:{node.level}:{node.module or ''}"))
            elif node.module:
                lines.append((node.lineno, node.module))
    return lines


def _absolute_module(file_in_layer: pathlib.Path, repo_root: pathlib.Path, raw: str) -> str:
    """Convertit un import relatif `__relative__:level:name` en chemin absolu.

    Ex: fichier `shugu/agent/loop.py`, import `__relative__:2:world.state`
    → `shugu.world.state`.
    """
    if not raw.startswith("__relative__:"):
        return raw
    _, level_str, name = raw.split(":", 2)
    level = int(level_str)
    rel = file_in_layer.relative_to(repo_root / "backend")
    parts = list(rel.with_suffix("").parts)
    # Remonter `level` crans (1 = même package, 2 = parent, etc.).
    if len(parts) < level:
        return name  # Cas dégénéré, on log tel quel.
    base = parts[: -level]
    full = ".".join(base + ([name] if name else []))
    return full


def test_layer_directories_exist() -> None:
    """Les 3 modules cibles doivent exister avec un __init__.py.

    Tant que les répertoires n'existent pas, ce test échoue — c'est le
    rouge initial du TDD. Implémenter les modules le passe au vert.
    """
    repo_root = _backend_root()
    missing: list[str] = []
    for layer in LAYER_PATHS:
        d = _layer_dir(repo_root, layer)
        if not d.is_dir():
            missing.append(f"{LAYER_PATHS[layer]}/ n'existe pas")
            continue
        if not (d / "__init__.py").is_file():
            missing.append(f"{LAYER_PATHS[layer]}/__init__.py manquant")
    assert not missing, "Layers L0 manquants :\n" + "\n".join(f"  • {m}" for m in missing)


def test_layer_isolation_no_forbidden_imports() -> None:
    """Aucun fichier d'un layer ne doit importer un layer interdit.

    Règles enforcées :
    - senses/ : pas d'import shugu.agent / shugu.world
    - agent/  : pas d'import shugu.world (sauf shugu.world.types — DTOs publics)
    - world/  : pas d'import shugu.senses / shugu.agent

    Mécanisme : parse AST de chaque .py dans le layer, normalise imports
    relatifs en absolus, match prefix-based contre FORBIDDEN_IMPORTS, applique
    ALLOWED_TYPES_IMPORTS comme allowlist d'exceptions.
    """
    repo_root = _backend_root()
    violations: list[str] = []

    for layer, forbidden in FORBIDDEN_IMPORTS.items():
        layer_dir = _layer_dir(repo_root, layer)
        if not layer_dir.is_dir():
            # Le test test_layer_directories_exist a déjà rapporté l'absence ;
            # on saute ici pour ne pas doubler le bruit.
            continue
        allowlist = ALLOWED_TYPES_IMPORTS.get(layer, ())

        for py_file in sorted(layer_dir.rglob("*.py")):
            if py_file.name == "__init__.py" and py_file.stat().st_size == 0:
                continue
            try:
                source = py_file.read_text(encoding="utf-8")
                tree = ast.parse(source, filename=str(py_file))
            except (OSError, SyntaxError) as exc:
                violations.append(f"{py_file}: parse error — {exc}")
                continue

            for lineno, raw in _import_lines(tree):
                module = _absolute_module(py_file, repo_root, raw)
                for bad in forbidden:
                    if module == bad or module.startswith(bad + "."):
                        if any(module == ok or module.startswith(ok + ".") for ok in allowlist):
                            continue
                        violations.append(
                            f"{py_file.relative_to(repo_root)} (ligne {lineno}): "
                            f"layer '{layer}' importe interdit '{module}'"
                        )

    assert not violations, (
        "Violations d'isolation Layers L0 détectées :\n"
        + "\n".join(f"  • {v}" for v in violations)
    )


def test_layers_dont_import_viewer_specifics() -> None:
    """Aucun layer ne doit importer scene_composer (qui est viewer-specific L4).

    Justification : scene_composer.player connaît les détails Three.js / scene
    graph frontend. Si L3 (world/) y dépendait, swap viewer = refonte.
    Inversement : scene_composer peut importer L3 (world.types) — la dépendance
    va dans le bon sens (viewer dérive du world, pas l'inverse).
    """
    repo_root = _backend_root()
    forbidden_viewer = ("shugu.scene_composer",)
    violations: list[str] = []

    for layer in LAYER_PATHS:
        layer_dir = _layer_dir(repo_root, layer)
        if not layer_dir.is_dir():
            continue
        for py_file in sorted(layer_dir.rglob("*.py")):
            try:
                source = py_file.read_text(encoding="utf-8")
                tree = ast.parse(source, filename=str(py_file))
            except (OSError, SyntaxError):
                continue
            for lineno, raw in _import_lines(tree):
                module = _absolute_module(py_file, repo_root, raw)
                for bad in forbidden_viewer:
                    if module == bad or module.startswith(bad + "."):
                        violations.append(
                            f"{py_file.relative_to(repo_root)} (ligne {lineno}): "
                            f"layer '{layer}' importe viewer-specific '{module}'"
                        )

    assert not violations, (
        "Violations viewer-isolation détectées (L1-L3 doivent ignorer scene_composer) :\n"
        + "\n".join(f"  • {v}" for v in violations)
    )
