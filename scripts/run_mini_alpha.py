"""Run the 10-item mini-alpha assembly workflow."""

from __future__ import annotations

import argparse
from pathlib import Path

from src.assembly.mini_alpha import MiniAlphaAssembler
from src.config.settings import get_settings
from src.eval.discard_rate import load_human_review_records


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Assemble and render a 10-item mini-alpha pilot.")
    parser.add_argument(
        "--candidate-manifest",
        required=True,
        help="JSON manifest that points at candidate ValidatedItem and ValidatorSuiteReport payloads.",
    )
    parser.add_argument(
        "--run-id",
        default="mini_alpha",
        help="Logical run id for the mini-alpha bundle.",
    )
    parser.add_argument(
        "--output-dir",
        default="out/mini_alpha",
        help="Directory where render outputs and reports will be written.",
    )
    parser.add_argument(
        "--real-item-validation",
        default=None,
        help="Optional validation.json path for the approved real_item_001 gate.",
    )
    parser.add_argument(
        "--human-review",
        default=None,
        help="Optional JSON list of human review decisions to fold into discard/regenerate reports.",
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
    manifest_path = Path(args.candidate_manifest)
    if not manifest_path.is_absolute():
        manifest_path = settings.repo_root / manifest_path

    output_dir = Path(args.output_dir)
    if not output_dir.is_absolute():
        output_dir = settings.repo_root / output_dir

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

    assembler = MiniAlphaAssembler(
        template_dir=settings.repo_root / "src" / "render" / "templates",
        xelatex_path=str(settings.xelatex_path) if settings.xelatex_path else None,
    )
    manifest = assembler.load_manifest(manifest_path)
    result = assembler.assemble(
        run_id=args.run_id,
        manifest=manifest,
        output_dir=output_dir,
        compile_pdf=not args.no_compile_pdf,
        real_item_validation_path=real_item_validation_path,
        human_reviews=human_reviews,
    )
    print(result.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
