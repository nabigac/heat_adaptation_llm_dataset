"""Small file/JSON operations shared by review and dataset artifacts.

These helpers do not decide whether research data are correct or complete.
Workflow modules own those checks and publish completion records last.
"""

import hashlib
import json
from pathlib import Path
import re


def json_bytes(data: object) -> bytes:
    """Encode readable UTF-8 JSON with the project's existing newline format."""
    return (json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def canonical_json_bytes(data: object) -> bytes:
    """Ignore object-key order while preserving JSON value types and list order.

    Python considers True equal to 1. Preserved evidence must distinguish those
    values, so ordinary dictionary equality is insufficient for this comparison.
    """
    return json.dumps(data, sort_keys=True, ensure_ascii=False, allow_nan=False,
                      separators=(",", ":")).encode("utf-8")


def sha256_bytes(raw: bytes) -> str:
    """Fingerprint exact file bytes rather than decoded or reformatted values."""
    return hashlib.sha256(raw).hexdigest()


def project_file(project_root: Path, relative_path: str, *, label: str) -> Path:
    """Resolve a project-relative artifact without following symbolic links."""
    # Keep storage's historical-path aliases and project boundary checks in one
    # place. Import locally so low-level JSON helpers do not create import cycles.
    import storage

    path = storage.resolve_project_path(project_root, relative_path)
    if path.is_symlink() or path.resolve() != path:
        raise ValueError(f"{label} paths must not use symbolic links: {relative_path}")
    return path


def next_artifact_id(project_root: Path, directories: tuple[str, ...], prefix: str) -> str:
    """Find the next number across roots, including occupied/partial artifacts.

    This only proposes an ID. The writer must still claim its directory with
    exist_ok=False, because another writer could claim the number meanwhile.
    """
    highest = 0
    for directory in directories:
        parent = project_file(project_root, directory, label="Artifact")
        if not parent.exists():
            continue
        for child in parent.iterdir():
            match = re.fullmatch(rf"{re.escape(prefix)}_([0-9]+)", child.name)
            if match:
                highest = max(highest, int(match[1]))
    return f"{prefix}_{highest + 1:04d}"


def source_code_snapshot() -> dict[str, bytes]:
    """Capture assembly rules/dependencies, excluding data, caches, and secrets."""
    root = Path(__file__).resolve().parents[1]
    paths = [*sorted((root / "src").glob("*.py")), *sorted((root / "schemas").glob("*.json")),
             root / "pyproject.toml", root / "uv.lock", root / ".python-version"]
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in paths if path.is_file()}
