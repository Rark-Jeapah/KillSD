"""Assemble and render a generated exam from persisted candidate-pool bundles."""

from __future__ import annotations

import argparse
from pathlib import Path

from src.config.settings import get_settings
from src.eval.discard_rate import load_human_review_records
from src.pipeline.generated_exam import GeneratedExamPipeline


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Assemble a generated exam from candidate bundles produced by build_candidate_pool.py."
    )
    parser.add_argument(
        "--candidate-pool-dir",
        required=True,
        help="Directory produced by scripts/build_candidate_pool.py.",
    )
    parser.add_argument(
        "--title",
        default=None,
        help="Override the rendered exam title. Defaults to the candidate-pool title.",
    )
    parser.add_argument(
        "--slot-count",
        type=int,
        default=15,
        help="Number of generated exam slots to assemble.",
    )
    parser.add_argument(
        "--run-id",
        default="generated_exam",
        help="Logical run id for the generated exam bundle.",
    )
    parser.add_argument(
        "--output-dir",
        default="out/generated_exam",
        help="Directory where generated exam artifacts will be written.",
    )
    parser.add_argument(
        "--real-item-validation",
        default=None,
        help="Optional approved real_item_001 validation.json used as a release gate.",
    )
    parser.add_argument(
        "--human-review",
        default=None,
        help="Optional JSON review decisions to fold into discard outputs.",
    )
    parser.add_argument(
        "--no-compile-pdf",
        action="store_true",
        help="Skip XeLaTeX compilation and emit TeX sources only.",
    )
    return parser.parse_args()


def _resolve_path(value: str, *, settings_root: Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (settings_root / path)


def main() -> int:
    args = parse_args()
    settings = get_settings()

    candidate_pool_dir = _resolve_path(args.candidate_pool_dir, settings_root=settings.repo_root)
    output_dir = _resolve_path(args.output_dir, settings_root=settings.repo_root)

    human_reviews = None
    if args.human_review:
        human_reviews = load_human_review_records(
            _resolve_path(args.human_review, settings_root=settings.repo_root)
        )

    real_item_validation_path = None
    if args.real_item_validation:
        real_item_validation_path = _resolve_path(
            args.real_item_validation,
            settings_root=settings.repo_root,
        )

    pipeline = GeneratedExamPipeline(
        template_dir=settings.repo_root / "src" / "render" / "templates",
        xelatex_path=str(settings.xelatex_path) if settings.xelatex_path else None,
    )
    result = pipeline.run(
        run_id=args.run_id,
        candidate_pool_dir=candidate_pool_dir,
        output_dir=output_dir,
        slot_count=args.slot_count,
        title=args.title,
        compile_pdf=not args.no_compile_pdf,
        real_item_validation_path=real_item_validation_path,
        human_reviews=human_reviews,
    )
    print(result.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
