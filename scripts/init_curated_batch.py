"""Initialize a new curated batch from a starter template."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.config.settings import get_settings
from src.distill.curation_workbench import CurationWorkbench


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Initialize a new curated batch manifest plus starter items payload."
    )
    parser.add_argument(
        "--batch-id",
        default=None,
        help="Logical batch id written to the manifest.",
    )
    parser.add_argument(
        "--batch-version",
        default=None,
        help="Version string written to the manifest.",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Directory where the manifest and items payload will be written.",
    )
    parser.add_argument(
        "--template",
        default="empty",
        help="Starter template name under data/curated_batches/templates.",
    )
    parser.add_argument(
        "--spec-id",
        default=None,
        help="Exam spec id. Defaults to CSAT_DEFAULT_SPEC_ID.",
    )
    parser.add_argument(
        "--exam-name",
        default="CSAT Mathematics",
        help="Provenance exam name stored in the manifest.",
    )
    parser.add_argument(
        "--exam-year",
        type=int,
        default=None,
        help="Optional provenance exam year. Defaults to the canonical spec year.",
    )
    parser.add_argument(
        "--source-name",
        default="manual_curation",
        help="Provenance source_name stored in the manifest.",
    )
    parser.add_argument(
        "--source-kind",
        default="exam_analysis",
        help="Provenance source_kind stored in the manifest.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite the target manifest/items files if they already exist.",
    )
    parser.add_argument(
        "--list-templates",
        action="store_true",
        help="Print available template names and exit.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    settings = get_settings()
    spec_id = args.spec_id or settings.default_spec_id
    workbench = CurationWorkbench(spec_id=spec_id, repo_root=settings.repo_root)

    if args.list_templates:
        print(json.dumps({"spec_id": spec_id, "templates": workbench.list_templates()}, ensure_ascii=False, indent=2))
        return 0

    if not args.batch_id or not args.batch_version or not args.output_dir:
        raise SystemExit("--batch-id, --batch-version, and --output-dir are required unless --list-templates is used")

    output_dir = Path(args.output_dir)
    if not output_dir.is_absolute():
        output_dir = settings.repo_root / output_dir

    result = workbench.initialize_batch(
        batch_id=args.batch_id,
        batch_version=args.batch_version,
        output_dir=output_dir,
        template_name=args.template,
        exam_name=args.exam_name,
        exam_year=args.exam_year,
        source_name=args.source_name,
        source_kind=args.source_kind,
        overwrite=args.force,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
