"""Export an offline review packet for a candidate pool or generated exam."""

from __future__ import annotations

import argparse
from pathlib import Path

from src.config.settings import get_settings
from src.eval.review_ops import (
    export_candidate_pool_review_packet,
    export_generated_exam_review_packet,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export a JSONL/Markdown review packet from a candidate pool or generated exam directory."
    )
    parser.add_argument(
        "--source-dir",
        required=True,
        help="Candidate-pool or generated-exam output directory.",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Directory where review_packet.jsonl and review_packet.md will be written.",
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
    mode = args.mode if args.mode != "auto" else _detect_mode(source_dir)
    output_dir = (
        _resolve_path(args.output_dir, repo_root=settings.repo_root)
        if args.output_dir
        else source_dir / "review_export"
    )

    if mode == "candidate_pool":
        result = export_candidate_pool_review_packet(
            candidate_pool_dir=source_dir,
            output_dir=output_dir,
        )
    else:
        result = export_generated_exam_review_packet(
            output_dir=source_dir,
            packet_dir=output_dir,
        )
    print(result.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
