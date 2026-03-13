#!/usr/bin/env python3
"""Clear local runtime state without touching source-controlled inputs."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.config.settings import Settings


def _resolve_path(path_value: str | None, *, default: Path, repo_root: Path) -> Path:
    if path_value is None:
        return default
    path = Path(path_value)
    return path if path.is_absolute() else repo_root / path


def _ensure_within_repo(repo_root: Path, target: Path) -> None:
    resolved_repo = repo_root.resolve()
    resolved_target = target.resolve(strict=False)
    if resolved_target == resolved_repo:
        raise ValueError(f"Refusing to clear repository root: {resolved_target}")
    if resolved_repo not in resolved_target.parents:
        raise ValueError(f"Refusing to clear path outside repo: {resolved_target}")


def _reset_directory(path: Path) -> str:
    if path.exists():
        if not path.is_dir():
            raise ValueError(f"Expected directory, found file: {path}")
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)
    return f"reset_dir:{path}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--artifact-root",
        help="Artifact directory to clear. Defaults to the configured artifact root.",
    )
    parser.add_argument(
        "--out-dir",
        help="Output directory to clear. Defaults to <repo>/out.",
    )
    parser.add_argument(
        "--var-dir",
        help="Runtime state directory to clear. Defaults to the parent directory of the configured database path.",
    )
    parser.add_argument(
        "--db-path",
        help="Deprecated compatibility option. If provided, the parent directory of this path will be cleared.",
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
    out_dir = _resolve_path(
        args.out_dir,
        default=settings.repo_root / "out",
        repo_root=settings.repo_root,
    )
    var_dir = None
    if args.var_dir is not None:
        var_dir = _resolve_path(
            args.var_dir,
            default=settings.database_path.parent,
            repo_root=settings.repo_root,
        )
    elif args.db_path is not None:
        var_dir = _resolve_path(
            args.db_path,
            default=settings.database_path,
            repo_root=settings.repo_root,
        ).parent
    else:
        var_dir = settings.database_path.parent

    for path in (artifact_root, out_dir, var_dir):
        _ensure_within_repo(settings.repo_root, path)

    actions = [
        _reset_directory(artifact_root),
        _reset_directory(out_dir),
        _reset_directory(var_dir),
    ]
    print(
        json.dumps(
            {
                "repo_root": str(settings.repo_root),
                "actions": actions,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
