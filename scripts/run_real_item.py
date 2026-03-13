"""Run the registry-driven real_item_001 gauntlet from a distilled atom input."""

from __future__ import annotations

import argparse
from pathlib import Path

from src.config.settings import get_settings
from src.core.storage import ArtifactStore
from src.orchestrator.real_item_gauntlet import (
    REAL_ITEM_DEFAULT_ATOM_ID,
    RealItemGauntlet,
    load_insight_atom,
)
from src.providers.real_item_runtime import (
    add_real_item_provider_arguments,
    provider_config_from_args,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the real_item_001 gauntlet.")
    parser.add_argument("--run-id", default="real_item_001", help="Logical run id.")
    add_real_item_provider_arguments(parser, include_legacy_mode=True)
    parser.add_argument(
        "--atom-id",
        default=REAL_ITEM_DEFAULT_ATOM_ID,
        help="Distilled atom id used as the blueprint input and auto family selection source.",
    )
    parser.add_argument(
        "--family-id",
        default=None,
        help="Optional explicit family override. Defaults to auto-select from atom metadata.",
    )
    parser.add_argument("--seed", type=int, default=0, help="Recorded deterministic seed.")
    parser.add_argument(
        "--output-dir",
        default="out/real_item_001",
        help="Bundle output directory.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    settings = get_settings()
    provider_config = provider_config_from_args(args)
    store = ArtifactStore(
        root_dir=settings.artifact_root,
        db_path=settings.database_path,
    )
    gauntlet = RealItemGauntlet(
        artifact_store=store,
        prompt_dir=settings.repo_root / "src" / "prompts",
        provider=provider_config.build_provider(),
        provider_settings=provider_config.public_settings(),
        xelatex_path=str(settings.xelatex_path) if settings.xelatex_path else None,
        max_stage_attempts=provider_config.stage_max_attempts,
    )
    atom = load_insight_atom(repo_root=settings.repo_root, atom_id=args.atom_id)

    output_dir = Path(args.output_dir)
    if not output_dir.is_absolute():
        output_dir = settings.repo_root / output_dir

    result = gauntlet.run(
        run_id=args.run_id,
        atom=atom,
        mode=provider_config.mode,
        output_dir=output_dir,
        family_id=args.family_id,
        seed=args.seed,
    )
    print(result.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
