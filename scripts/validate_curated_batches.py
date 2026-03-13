"""Validate curated batches before distillation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.config.settings import get_settings
from src.distill.curation_workbench import CurationWorkbench


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate curated batch manifests plus authoring semantics."
    )
    parser.add_argument(
        "--batch-path",
        required=True,
        help="Curated batch manifest path or directory tree.",
    )
    parser.add_argument(
        "--spec-id",
        default=None,
        help="Exam spec id. Defaults to CSAT_DEFAULT_SPEC_ID.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    settings = get_settings()
    spec_id = args.spec_id or settings.default_spec_id
    batch_path = Path(args.batch_path)
    if not batch_path.is_absolute():
        batch_path = settings.repo_root / batch_path

    workbench = CurationWorkbench(spec_id=spec_id, repo_root=settings.repo_root)
    report = workbench.validate_batches(batch_path)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
