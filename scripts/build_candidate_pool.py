"""Build a generated candidate pool and emit a mini-alpha manifest."""

from __future__ import annotations

import argparse
from pathlib import Path

from src.assembly.candidate_pool import CandidatePoolBuilder
from src.config.settings import get_settings


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a generated candidate pool from atom ids or curated batch refs."
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
        help="Title stored in the generated MiniAlpha manifest.",
    )
    parser.add_argument(
        "--slot-count",
        type=int,
        default=10,
        help="Number of mini-alpha slots to allocate from the generated pool.",
    )
    parser.add_argument(
        "--run-id",
        default="generated_candidate_pool",
        help="Logical run id prefix used for per-candidate gauntlet runs.",
    )
    parser.add_argument(
        "--output-dir",
        default="out/generated_candidate_pool",
        help="Directory where candidate bundles, reports, and manifests will be written.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    settings = get_settings()
    output_dir = Path(args.output_dir)
    if not output_dir.is_absolute():
        output_dir = settings.repo_root / output_dir

    builder = CandidatePoolBuilder()
    result = builder.build(
        output_dir=output_dir,
        title=args.title,
        slot_count=args.slot_count,
        atom_ids=args.atom_id,
        curated_batch_refs=args.curated_batch_ref,
        run_id=args.run_id,
    )
    print(result.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
