"""Application configuration helpers."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


def _repo_root() -> Path:
    """Resolve the repository root from this module's location."""
    return Path(__file__).resolve().parents[2]


class Settings(BaseModel):
    """Runtime settings backed by environment variables."""

    model_config = ConfigDict(extra="forbid")

    app_name: str = "csat-math-mvp"
    app_env: str = "dev"
    log_level: str = "INFO"
    repo_root: Path = Field(default_factory=_repo_root)
    artifact_root: Path | None = None
    database_path: Path | None = None
    exam_specs_dir: Path | None = None
    data_root: Path | None = None
    distilled_root: Path | None = None
    source_fixture_root: Path | None = None
    xelatex_path: Path | None = None
    default_spec_id: str = "csat_math_2028"

    def model_post_init(self, __context: object) -> None:
        """Resolve relative paths against the repository root."""
        if self.artifact_root is None:
            self.artifact_root = self.repo_root / "artifacts"
        elif not self.artifact_root.is_absolute():
            self.artifact_root = self.repo_root / self.artifact_root

        if self.database_path is None:
            self.database_path = self.repo_root / "var" / "app.db"
        elif not self.database_path.is_absolute():
            self.database_path = self.repo_root / self.database_path

        if self.exam_specs_dir is None:
            self.exam_specs_dir = self.repo_root / "exam_specs"
        elif not self.exam_specs_dir.is_absolute():
            self.exam_specs_dir = self.repo_root / self.exam_specs_dir

        if self.data_root is None:
            self.data_root = self.repo_root / "data"
        elif not self.data_root.is_absolute():
            self.data_root = self.repo_root / self.data_root

        if self.distilled_root is None:
            self.distilled_root = self.data_root / "distilled"
        elif not self.distilled_root.is_absolute():
            self.distilled_root = self.repo_root / self.distilled_root

        if self.source_fixture_root is None:
            self.source_fixture_root = self.data_root / "source_fixtures"
        elif not self.source_fixture_root.is_absolute():
            self.source_fixture_root = self.repo_root / self.source_fixture_root

        if self.xelatex_path is not None and not self.xelatex_path.is_absolute():
            self.xelatex_path = self.repo_root / self.xelatex_path

    @classmethod
    def from_env(cls) -> "Settings":
        """Load settings from environment variables with sane defaults."""
        data = {
            "app_name": os.getenv("CSAT_APP_NAME", "csat-math-mvp"),
            "app_env": os.getenv("CSAT_APP_ENV", "dev"),
            "log_level": os.getenv("CSAT_LOG_LEVEL", "INFO"),
            "artifact_root": os.getenv("CSAT_ARTIFACT_ROOT"),
            "database_path": os.getenv("CSAT_DATABASE_PATH"),
            "exam_specs_dir": os.getenv("CSAT_EXAM_SPECS_DIR"),
            "data_root": os.getenv("CSAT_DATA_ROOT"),
            "distilled_root": os.getenv("CSAT_DISTILLED_ROOT"),
            "source_fixture_root": os.getenv("CSAT_SOURCE_FIXTURE_ROOT"),
            "xelatex_path": os.getenv("CSAT_XELATEX_PATH"),
            "default_spec_id": os.getenv("CSAT_DEFAULT_SPEC_ID", "csat_math_2028"),
        }
        return cls.model_validate(data)

    def ensure_runtime_dirs(self) -> None:
        """Create local directories required by the MVP runtime."""
        self.artifact_root.mkdir(parents=True, exist_ok=True)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.exam_specs_dir.mkdir(parents=True, exist_ok=True)
        self.data_root.mkdir(parents=True, exist_ok=True)
        self.distilled_root.mkdir(parents=True, exist_ok=True)
        self.source_fixture_root.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a process-wide cached settings object."""
    settings = Settings.from_env()
    settings.ensure_runtime_dirs()
    return settings
