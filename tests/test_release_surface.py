"""Release-surface checks for the public OSS repository."""

from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PUBLIC_TEXT_PATTERNS = (
    "README.md",
    "CONTRIBUTING.md",
    ".env.example",
    "docs/**/*.md",
    "exam_specs/*.yaml",
    "data/benchmarks/**/*.json",
    "data/source_fixtures/**/*.json",
    "data/distilled/**/*.json",
    "data/distilled/**/*.yaml",
    "tests/fixtures/**/*.json",
)
FORBIDDEN_MACHINE_LOCAL_SNIPPETS = (
    "/Users/",
    "\\Users\\",
    "C:\\",
    "file://",
)


def _iter_public_text_files() -> list[Path]:
    paths: set[Path] = set()
    for pattern in PUBLIC_TEXT_PATTERNS:
        paths.update(REPO_ROOT.glob(pattern))
    return sorted(path for path in paths if path.is_file())


def test_gitignore_covers_runtime_outputs_and_local_env() -> None:
    gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")

    for expected_entry in ("artifacts/", "out/", "var/", ".env"):
        assert expected_entry in gitignore


def test_public_release_files_do_not_contain_machine_local_paths() -> None:
    offenders: list[str] = []

    for path in _iter_public_text_files():
        text = path.read_text(encoding="utf-8")
        for snippet in FORBIDDEN_MACHINE_LOCAL_SNIPPETS:
            if snippet in text:
                offenders.append(f"{path.relative_to(REPO_ROOT)} contains {snippet!r}")

    assert offenders == []
