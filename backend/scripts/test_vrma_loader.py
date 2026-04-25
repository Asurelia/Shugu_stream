"""Smoke test pour le loader VRMA — Phase E3 Assets.

Test simple qui valide que les fichiers .vrma peuvent être chargés
et contiennent les métadonnées minimales requises.

Utilisation:
    pytest backend/scripts/test_vrma_loader.py -v
    python -m pytest backend/scripts/test_vrma_loader.py::test_vrma_metadata_validity
"""

import json
from pathlib import Path
from typing import Any, Dict, Optional

import pytest


class VRMALoader:
    """Simple VRMA loader pour validation."""

    @staticmethod
    def load_vrma_metadata(vrma_path: Path) -> Optional[Dict[str, Any]]:
        """Load VRMA metadata from .vrma.meta.json sidecar.

        Returns None if file doesn't exist (skip gracefully).
        """
        meta_path = vrma_path.with_suffix('.vrma.meta.json')
        if not meta_path.exists():
            return None

        try:
            with open(meta_path, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            raise ValueError(f"Failed to load VRMA metadata from {meta_path}: {e}")

    @staticmethod
    def validate_vrma_file(vrma_path: Path) -> Dict[str, Any]:
        """Validate VRMA file structure.

        Checks:
        - File exists and is readable
        - File size > 0
        - Metadata sidecar exists and is valid JSON
        - Metadata contains required fields

        Returns:
            Dict with validation results
        """
        if not vrma_path.exists():
            raise FileNotFoundError(f"VRMA file not found: {vrma_path}")

        file_size = vrma_path.stat().st_size
        if file_size == 0:
            raise ValueError(f"VRMA file is empty: {vrma_path}")

        metadata = VRMALoader.load_vrma_metadata(vrma_path)
        if metadata is None:
            raise ValueError(f"No metadata sidecar found for {vrma_path}")

        # Validate required fields
        required_fields = {"format", "slug", "frame_count", "fps"}
        missing_fields = required_fields - set(metadata.keys())
        if missing_fields:
            raise ValueError(
                f"VRMA metadata missing required fields: {missing_fields}"
            )

        # Validate field types and values
        if metadata["format"] != "vrma":
            raise ValueError(
                f"Expected format='vrma', got {metadata['format']}"
            )

        if not isinstance(metadata["slug"], str) or not metadata["slug"]:
            raise ValueError(f"Invalid slug: {metadata['slug']}")

        if not isinstance(metadata["frame_count"], int) or metadata["frame_count"] <= 0:
            raise ValueError(
                f"Invalid frame_count: {metadata['frame_count']}"
            )

        if not isinstance(metadata["fps"], (int, float)) or metadata["fps"] <= 0:
            raise ValueError(f"Invalid fps: {metadata['fps']}")

        return {
            "file": str(vrma_path),
            "file_size": file_size,
            "metadata": metadata,
            "valid": True,
        }


# Test fixtures
VRMA_DIR = Path(__file__).parent.parent.parent / "frontend" / "public" / "assets" / "vrma"


@pytest.fixture
def vrma_files() -> list:
    """Discover all .vrma files in the assets directory."""
    if not VRMA_DIR.exists():
        return []

    return sorted([f for f in VRMA_DIR.glob("*.vrma") if f.is_file()])


# Tests

def test_vrma_directory_exists() -> None:
    """Verify VRMA assets directory exists."""
    assert VRMA_DIR.exists(), f"VRMA directory not found: {VRMA_DIR}"
    assert VRMA_DIR.is_dir(), f"VRMA path is not a directory: {VRMA_DIR}"


def test_vrma_files_discoverable(vrma_files: list) -> None:
    """Verify we can discover .vrma files (skip if none exist)."""
    if not vrma_files:
        pytest.skip(f"No .vrma files found in {VRMA_DIR}")

    assert len(vrma_files) > 0, "No VRMA files discovered"


@pytest.mark.parametrize("vrma_file", [
    VRMA_DIR / f for f in [
        "idle_loop.vrma", "wave.vrma", "bow.vrma", "dance.vrma"
    ] if (VRMA_DIR / f).exists()
], ids=lambda p: p.name)
def test_vrma_file_validity(vrma_file: Path) -> None:
    """Test individual VRMA files for validity.

    Parametrized to test all discovered files.
    Skips gracefully if file doesn't exist.
    """
    if not vrma_file.exists():
        pytest.skip(f"VRMA file not found: {vrma_file}")

    result = VRMALoader.validate_vrma_file(vrma_file)

    # Assertions
    assert result["valid"] is True
    assert result["file_size"] > 0
    assert result["metadata"]["format"] == "vrma"
    assert result["metadata"]["frame_count"] > 0
    assert result["metadata"]["fps"] > 0

    print(f"\n✓ {vrma_file.name}")
    print(f"  Size: {result['file_size']} bytes")
    print(f"  Slug: {result['metadata']['slug']}")
    print(f"  Frames: {result['metadata']['frame_count']} @ {result['metadata']['fps']} fps")


def test_vrma_metadata_validity() -> None:
    """Test VRMA metadata structure (single test for all files)."""
    vrma_files = list(VRMA_DIR.glob("*.vrma"))

    if not vrma_files:
        pytest.skip(f"No .vrma files found in {VRMA_DIR}")

    failed = []
    passed = []

    for vrma_file in vrma_files:
        try:
            VRMALoader.validate_vrma_file(vrma_file)
            passed.append(vrma_file.name)
        except Exception as e:
            failed.append((vrma_file.name, str(e)))

    # Report
    print(f"\n✓ Passed: {len(passed)}")
    for name in passed:
        print(f"  - {name}")

    if failed:
        print(f"\n✗ Failed: {len(failed)}")
        for name, error in failed:
            print(f"  - {name}: {error}")

        pytest.fail(f"{len(failed)}/{len(vrma_files)} VRMA files failed validation")


def test_vrma_slug_naming_convention() -> None:
    """Verify VRMA files follow slug naming convention (kebab-case).

    Expected: slug.vrma (e.g., idle_loop.vrma, wave.vrma)
    Pattern: lowercase alphanumeric + underscore only
    """
    import re

    vrma_files = list(VRMA_DIR.glob("*.vrma"))

    if not vrma_files:
        pytest.skip(f"No .vrma files found in {VRMA_DIR}")

    pattern = re.compile(r"^[a-z0-9_]+\.vrma$")

    invalid_files = [f.name for f in vrma_files if not pattern.match(f.name)]

    if invalid_files:
        pytest.fail(
            f"VRMA files don't follow naming convention (expected lowercase_snake_case.vrma):\n"
            f"  {invalid_files}"
        )


if __name__ == "__main__":
    # Allow direct script execution for quick testing
    import sys

    vrma_files = list(VRMA_DIR.glob("*.vrma"))
    print(f"Found {len(vrma_files)} VRMA files in {VRMA_DIR}")

    if not vrma_files:
        print("No VRMA files to test. Run pytest for full test suite.")
        sys.exit(0)

    for vrma_file in vrma_files:
        try:
            result = VRMALoader.validate_vrma_file(vrma_file)
            print(f"✓ {vrma_file.name}: {result['metadata']['slug']}")
        except Exception as e:
            print(f"✗ {vrma_file.name}: {e}")
            sys.exit(1)

    print("\nAll VRMA files are valid!")
