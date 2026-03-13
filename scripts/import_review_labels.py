"""Import offline human review labels back into pipeline artifacts."""

from __future__ import annotations

import argparse
from pathlib import Path

from src.config.settings import get_settings
from src.eval.review_feedback import load_human_review_records
from src.eval.review_ops import (
    sync_candidate_pool_reviews,
    sync_generated_exam_reviews,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Import review labels into a candidate pool or generated exam output directory."
    )
    parser.add_argument(
        "--source-dir",
        required=True,
        help="Candidate-pool or generated-exam output directory to update.",
    )
    parser.add_argument(
        "--labels",
        required=True,
        help="JSON or JSONL file containing review labels or exported packet entries.",
    )
    parser.add_argument(
        "--mode",
        choices=("auto", "candidate_pool", "generated_exam"),
        default="auto",
        help="Override source detection when needed.",
    )
    return parser.parse_args()


def _resolve_path(value: str, *, repo_root: Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (repo_root / path)


def _detect_mode(source_dir: Path) -> str:
    if (source_dir / "candidate_manifest.json").exists() and (source_dir / "mini_alpha_manifest.json").exists():
        return "generated_exam"
    if (source_dir / "candidate_pool_manifest.json").exists() or (source_dir / "candidates").exists():
        return "candidate_pool"
    raise SystemExit(
        f"Could not infer review source type from {source_dir}. Pass --mode explicitly."
    )


def main() -> int:
    args = parse_args()
    settings = get_settings()
    source_dir = _resolve_path(args.source_dir, repo_root=settings.repo_root)
    labels_path = _resolve_path(args.labels, repo_root=settings.repo_root)
    mode = args.mode if args.mode != "auto" else _detect_mode(source_dir)
    reviews = load_human_review_records(labels_path)

    if mode == "candidate_pool":
        result = sync_candidate_pool_reviews(
            candidate_pool_dir=source_dir,
            incoming_reviews=reviews,
        )
    else:
        result = sync_generated_exam_reviews(
            output_dir=source_dir,
            incoming_reviews=reviews,
        )
    print(result.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
