"""Build a generated candidate pool, assemble the mini alpha, and render outputs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.assembly.candidate_pool import CandidatePoolBuilder
from src.assembly.mini_alpha import MiniAlphaAssembler
from src.config.settings import get_settings
from src.eval.discard_rate import load_human_review_records


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a candidate pool and immediately assemble a mini alpha from it."
    )
    parser.add_argument(
        "--atom-id",
        action="append",
        default=None,
        help="Distilled atom id to expand into one generated candidate bundle. Repeat as needed.",
    )
    parser.add_argument(
        "--curated-batch-ref",
        action="append",
        default=None,
        help="Curated batch id, batch_id@version, or manifest path/directory used to resolve atoms.",
    )
    parser.add_argument(
        "--title",
        default="Generated Candidate Pool Mini Alpha",
        help="Title stored in the generated MiniAlpha manifest and rendered exam bundle.",
    )
    parser.add_argument(
        "--slot-count",
        type=int,
        default=10,
        help="Number of mini-alpha slots to allocate from the generated pool.",
    )
    parser.add_argument(
        "--run-id",
        default="generated_mini_alpha",
        help="Logical run id for the final mini-alpha bundle.",
    )
    parser.add_argument(
        "--output-dir",
        default="out/generated_mini_alpha",
        help="Root directory where candidate_pool/ and mini_alpha/ outputs will be written.",
    )
    parser.add_argument(
        "--real-item-validation",
        default=None,
        help="Optional approved real_item_001 validation.json used as a release gate.",
    )
    parser.add_argument(
        "--human-review",
        default=None,
        help="Optional JSON review decisions to fold into discard/regenerate outputs.",
    )
    parser.add_argument(
        "--no-compile-pdf",
        action="store_true",
        help="Skip XeLaTeX compilation and emit TeX sources only.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    settings = get_settings()
    output_root = Path(args.output_dir)
    if not output_root.is_absolute():
        output_root = settings.repo_root / output_root
    candidate_pool_dir = output_root / "candidate_pool"
    mini_alpha_dir = output_root / "mini_alpha"

    human_reviews = None
    if args.human_review:
        human_review_path = Path(args.human_review)
        if not human_review_path.is_absolute():
            human_review_path = settings.repo_root / human_review_path
        human_reviews = load_human_review_records(human_review_path)

    real_item_validation_path = None
    if args.real_item_validation:
        real_item_validation_path = Path(args.real_item_validation)
        if not real_item_validation_path.is_absolute():
            real_item_validation_path = settings.repo_root / real_item_validation_path

    builder = CandidatePoolBuilder()
    pool_result = builder.build(
        output_dir=candidate_pool_dir,
        title=args.title,
        slot_count=args.slot_count,
        atom_ids=args.atom_id,
        curated_batch_refs=args.curated_batch_ref,
        run_id=f"{args.run_id}_pool",
    )

    assembler = MiniAlphaAssembler(
        template_dir=settings.repo_root / "src" / "render" / "templates",
        xelatex_path=str(settings.xelatex_path) if settings.xelatex_path else None,
    )
    manifest = assembler.load_manifest(Path(pool_result.mini_alpha_manifest_path))
    mini_alpha_result = assembler.assemble(
        run_id=args.run_id,
        manifest=manifest,
        output_dir=mini_alpha_dir,
        compile_pdf=not args.no_compile_pdf,
        real_item_validation_path=real_item_validation_path,
        human_reviews=human_reviews,
    )

    print(
        json.dumps(
            {
                "candidate_pool": pool_result.model_dump(mode="json"),
                "mini_alpha": mini_alpha_result.model_dump(mode="json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
