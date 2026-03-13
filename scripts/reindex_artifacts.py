#!/usr/bin/env python3
"""Rebuild the artifact SQLite index from artifact envelopes on disk."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.config.settings import Settings
from src.core.storage import ArtifactStore


def _resolve_path(path_value: str | None, *, default: Path, repo_root: Path) -> Path:
    if path_value is None:
        return default
    path = Path(path_value)
    return path if path.is_absolute() else repo_root / path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--artifact-root",
        help="Artifact root to scan. Defaults to the configured artifact root.",
    )
    parser.add_argument(
        "--db-path",
        help="SQLite database to rebuild. Defaults to the configured database path.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    settings = Settings.from_env()
    artifact_root = _resolve_path(
        args.artifact_root,
        default=settings.artifact_root,
        repo_root=settings.repo_root,
    )
    db_path = _resolve_path(
        args.db_path,
        default=settings.database_path,
        repo_root=settings.repo_root,
    )

    store = ArtifactStore(root_dir=artifact_root, db_path=db_path)
    result = store.rebuild_index()
    print(
        json.dumps(
            {
                "artifact_root": str(artifact_root),
                "db_path": str(db_path),
                **result.model_dump(),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
