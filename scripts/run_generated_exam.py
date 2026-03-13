"""Assemble and render a generated exam from persisted candidate-pool bundles."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.assembly.candidate_pool import CandidatePoolBuilder
from src.config.settings import get_settings
from src.eval.discard_rate import load_human_review_records
from src.pipeline.generated_exam import GeneratedExamPipeline
from src.providers.real_item_runtime import (
    add_real_item_provider_arguments,
    provider_config_from_args,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Assemble a generated exam from candidate bundles produced by build_candidate_pool.py."
    )
    parser.add_argument(
        "--candidate-pool-dir",
        default=None,
        help="Directory produced by scripts/build_candidate_pool.py. Optional if atom/batch refs are provided.",
    )
    parser.add_argument(
        "--atom-id",
        action="append",
        default=None,
        help="Build a candidate pool inline from these atom ids before assembling the exam.",
    )
    parser.add_argument(
        "--curated-batch-ref",
        action="append",
        default=None,
        help="Build a candidate pool inline from these curated batch refs before assembling the exam.",
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
    add_real_item_provider_arguments(parser)
    return parser.parse_args()


def _resolve_path(value: str, *, settings_root: Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (settings_root / path)


def main() -> int:
    args = parse_args()
    settings = get_settings()
    provider_config = provider_config_from_args(args)

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

    inline_pool = bool(args.atom_id or args.curated_batch_ref)
    if not inline_pool and args.candidate_pool_dir is None:
        raise SystemExit(
            "Provide --candidate-pool-dir or supply --atom-id/--curated-batch-ref to build inline."
        )

    pool_result = None
    if inline_pool:
        candidate_pool_dir = output_dir / "candidate_pool"
        builder = CandidatePoolBuilder(provider_config=provider_config)
        pool_result = builder.build(
            output_dir=candidate_pool_dir,
            title=args.title or "Generated Exam Candidate Pool",
            slot_count=args.slot_count,
            atom_ids=args.atom_id,
            curated_batch_refs=args.curated_batch_ref,
            run_id=f"{args.run_id}_pool",
        )
        if pool_result.status != "completed":
            print(
                json.dumps(
                    {"candidate_pool": pool_result.model_dump(mode="json")},
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
    else:
        candidate_pool_dir = _resolve_path(args.candidate_pool_dir, settings_root=settings.repo_root)

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
        expected_provider_name=provider_config.provider if args.provider else None,
    )
    if pool_result is None:
        print(result.model_dump_json(indent=2))
    else:
        print(
            json.dumps(
                {
                    "candidate_pool": pool_result.model_dump(mode="json"),
                    "generated_exam": result.model_dump(mode="json"),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
