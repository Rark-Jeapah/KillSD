"""Typer CLI entrypoint for the public CSAT math core and plugin."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer

from src.assembly.exam_assembler import ExamAssembler
from src.config.settings import get_settings
from src.core.schemas import ExamMode, PipelineStage, PromptPacket
from src.core.storage import ArtifactStore, StorageError
from src.distill.pipeline import DistillPipeline, DistillPipelineError
from src.orchestrator.state_machine import GenerationStateMachine, StateMachineError
from src.plugins import get_plugin, list_available_plugins
from src.providers.base import ProviderError
from src.providers.factory import build_provider
from src.render.contracts import RendererConfig
from src.render.latex_renderer import LaTeXRenderer, RenderJobResult

app = typer.Typer(help="CSAT math core CLI", no_args_is_help=True)
exam_app = typer.Typer(help="Exam-level orchestration commands", no_args_is_help=True)
item_app = typer.Typer(help="Item-level orchestration commands", no_args_is_help=True)
exchange_app = typer.Typer(help="Manual exchange commands", no_args_is_help=True)
distill_app = typer.Typer(help="Offline source distillation commands", no_args_is_help=True)
assemble_app = typer.Typer(help="Assembly commands", no_args_is_help=True)
render_app = typer.Typer(help="LaTeX render commands", no_args_is_help=True)
app.add_typer(exam_app, name="exam")
app.add_typer(item_app, name="item")
app.add_typer(exchange_app, name="exchange")
app.add_typer(distill_app, name="distill")
app.add_typer(assemble_app, name="assemble")
app.add_typer(render_app, name="render")


def _store() -> ArtifactStore:
    """Create a store using process settings."""
    settings = get_settings()
    return ArtifactStore(root_dir=settings.artifact_root, db_path=settings.database_path)


def _machine(provider_name: str | None = None) -> GenerationStateMachine:
    """Build a generation state machine using current settings."""
    settings = get_settings()
    provider = None
    if provider_name:
        try:
            provider = build_provider(provider_name)
        except ProviderError as exc:
            raise typer.BadParameter(str(exc)) from exc
    return GenerationStateMachine(
        artifact_store=_store(),
        prompt_dir=settings.repo_root / "src" / "prompts",
        provider=provider,
    )


def _assembler() -> ExamAssembler:
    """Build an exam assembler using current settings."""
    return ExamAssembler(artifact_store=_store())


def _renderer() -> LaTeXRenderer:
    """Build a LaTeX renderer using versioned repository templates."""
    settings = get_settings()
    return LaTeXRenderer(
        template_dir=settings.repo_root / "src" / "render" / "templates",
        config=RendererConfig(
            xelatex_path=str(settings.xelatex_path) if settings.xelatex_path is not None else None
        ),
    )


def _resolve_output_dir(output_dir: str | None, default_name: str) -> Path:
    """Resolve an output directory relative to the repository root."""
    settings = get_settings()
    resolved = settings.repo_root / "out" / default_name if output_dir is None else Path(output_dir)
    if not resolved.is_absolute():
        resolved = settings.repo_root / resolved
    return resolved


def _state_summary(state) -> str:
    """Return a compact JSON summary for CLI output."""
    return json.dumps(
        {
            "run_id": state.run_id,
            "mode": state.mode.value,
            "status": state.status.value,
            "render_bundle_artifact_id": state.render_bundle_artifact_id,
            "pending_prompt_paths": state.pending_prompt_paths(),
            "history_count": len(state.history),
        },
        ensure_ascii=False,
        indent=2,
    )


@app.command("init-storage")
def init_storage() -> None:
    """Create artifact directories and the SQLite index."""
    store = _store()
    store.initialize()
    typer.echo(f"Initialized artifact store at {store.root_dir}")
    typer.echo(f"SQLite index: {store.db_path}")


@app.command("show-spec")
def show_spec(spec_id: str | None = None) -> None:
    """Load a validated exam spec and print it as JSON."""
    settings = get_settings()
    plugin = get_plugin(spec_id or settings.default_spec_id)
    spec = plugin.load_exam_spec()
    typer.echo(spec.model_dump_json(indent=2))


@app.command("list-plugins")
def list_plugins() -> None:
    """List built-in and installed subject plugins."""
    typer.echo(
        json.dumps(
            {"plugins": list(list_available_plugins())},
            ensure_ascii=False,
            indent=2,
        )
    )


@app.command("build-blueprint")
def build_blueprint(
    run_id: str = typer.Option(..., help="Logical run id used for artifact storage."),
    spec_id: str | None = typer.Option(None, help="Exam spec/plugin id."),
    persist: bool = typer.Option(True, help="Persist the generated blueprint artifact."),
) -> None:
    """Create the default blueprint for the configured exam spec."""
    settings = get_settings()
    plugin = get_plugin(spec_id or settings.default_spec_id)
    blueprint = plugin.build_default_blueprint()
    if not persist:
        typer.echo(blueprint.model_dump_json(indent=2))
        return

    try:
        envelope = _store().save_model(
            blueprint,
            stage=PipelineStage.DESIGN,
            run_id=run_id,
            spec_id=blueprint.spec_id,
            metadata={"generator": blueprint.generator},
        )
    except StorageError as exc:
        raise typer.Exit(code=1) from exc

    typer.echo(f"Stored blueprint artifact: {envelope.artifact_id}")


@app.command("scaffold-packet")
def scaffold_packet(
    run_id: str = typer.Option(..., help="Logical run id."),
    stage: PipelineStage = typer.Option(..., help="Pipeline stage for the prompt."),
    mode: ExamMode = typer.Option(..., help="manual or api."),
    expected_output_model: str = typer.Option(..., help="Target model name."),
    item_no: Optional[int] = typer.Option(None, help="Target item number."),
    spec_id: str | None = typer.Option(None, help="Exam spec/plugin id."),
    blueprint_id: str | None = typer.Option(None, help="Optional blueprint id."),
) -> None:
    """Emit a prompt packet using the shared manual/API contract."""
    settings = get_settings()
    packet = PromptPacket(
        mode=mode,
        stage=stage,
        spec_id=spec_id or settings.default_spec_id,
        run_id=run_id,
        blueprint_id=blueprint_id,
        item_no=item_no,
        instructions=[
            "Follow the stage contract exactly.",
            "Return only data that matches the expected output model.",
            "Preserve reproducibility via artifact references.",
        ],
        expected_output_model=expected_output_model,
    )
    typer.echo(packet.model_dump_json(indent=2))


@exam_app.command("plan")
def exam_plan(
    run_id: str = typer.Option(..., help="Logical run id."),
    mode: ExamMode = typer.Option(..., help="manual or api."),
    seed: int = typer.Option(0, help="Deterministic seed recorded in prompt packets."),
    provider: str = typer.Option("mock", help="Provider adapter for api mode: mock or openai."),
) -> None:
    """Run only the exam blueprint stage."""
    machine = _machine(provider if mode == ExamMode.API else None)
    try:
        state = machine.run_plan(run_id=run_id, mode=mode, seed=seed)
    except StateMachineError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(_state_summary(state))


@exam_app.command("run")
def exam_run(
    run_id: str = typer.Option(..., help="Logical run id."),
    mode: ExamMode = typer.Option(..., help="manual or api."),
    seed: int = typer.Option(0, help="Deterministic seed recorded in prompt packets."),
    provider: str = typer.Option("mock", help="Provider adapter for api mode: mock or openai."),
) -> None:
    """Run the full exam generation state machine."""
    machine = _machine(provider if mode == ExamMode.API else None)
    try:
        state = machine.run_exam(run_id=run_id, mode=mode, seed=seed)
    except StateMachineError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(_state_summary(state))


@item_app.command("draft")
def item_draft(
    run_id: str = typer.Option(..., help="Logical run id."),
    item_no: int = typer.Option(..., min=1, max=30, help="Target item number."),
    mode: ExamMode = typer.Option(..., help="manual or api."),
    seed: int = typer.Option(0, help="Deterministic seed recorded in prompt packets."),
    provider: str = typer.Option("mock", help="Provider adapter for api mode: mock or openai."),
) -> None:
    """Run up to the draft stage for one item."""
    machine = _machine(provider if mode == ExamMode.API else None)
    try:
        state = machine.run_item_draft(run_id=run_id, item_no=item_no, mode=mode, seed=seed)
    except StateMachineError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(_state_summary(state))


@exchange_app.command("export")
def exchange_export(
    run_id: str = typer.Option(..., help="Logical run id."),
) -> None:
    """List prompt packet files waiting for manual responses."""
    machine = _machine(None)
    try:
        pending = machine.export_pending_exchanges(run_id=run_id)
    except StateMachineError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(json.dumps({"run_id": run_id, "pending_prompt_paths": pending}, indent=2))


@exchange_app.command("import")
def exchange_import(
    run_id: str = typer.Option(..., help="Logical run id."),
    packet_path: Path = typer.Option(..., exists=True, dir_okay=False, readable=True),
    response_path: Path = typer.Option(..., exists=True, dir_okay=False, readable=True),
) -> None:
    """Import a manual response file and mark the stage as completed."""
    machine = _machine(None)
    try:
        state = machine.import_manual_exchange(
            run_id=run_id,
            packet_path=packet_path,
            response_path=response_path,
        )
    except StateMachineError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(_state_summary(state))


@distill_app.command("validate-source")
def validate_source(
    source_path: str = typer.Option(
        ...,
        help="Manual JSON/CSV source file or directory containing curated source items.",
    ),
    spec_id: str | None = typer.Option(None, help="Exam spec id."),
) -> None:
    """Load and validate manual source items without writing outputs."""
    settings = get_settings()
    resolved_spec_id = spec_id or settings.default_spec_id
    pipeline = DistillPipeline(spec_id=resolved_spec_id, repo_root=settings.repo_root)
    resolved_source_path = Path(source_path)
    if not resolved_source_path.is_absolute():
        resolved_source_path = settings.repo_root / resolved_source_path

    try:
        items = pipeline.load_source_items(resolved_source_path)
    except DistillPipelineError as exc:
        typer.echo(f"Source validation failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(
        json.dumps(
            {
                "spec_id": resolved_spec_id,
                "source_path": pipeline.portable_path(resolved_source_path),
                "count": len(items),
                "source_item_ids": [item.source_item_id for item in items],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


@distill_app.command("validate-batches")
def validate_batches(
    batch_path: str = typer.Option(
        ...,
        help="Curated batch manifest file or directory containing curated batch manifests.",
    ),
    spec_id: str | None = typer.Option(None, help="Exam spec id."),
) -> None:
    """Validate curated batch manifests against their referenced JSON/JSONL payloads."""
    settings = get_settings()
    resolved_spec_id = spec_id or settings.default_spec_id
    pipeline = DistillPipeline(spec_id=resolved_spec_id, repo_root=settings.repo_root)
    resolved_batch_path = Path(batch_path)
    if not resolved_batch_path.is_absolute():
        resolved_batch_path = settings.repo_root / resolved_batch_path

    try:
        report = pipeline.validate_curated_batches(resolved_batch_path)
    except DistillPipelineError as exc:
        typer.echo(f"Curated batch validation failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["valid"]:
        raise typer.Exit(code=1)


@distill_app.command("run")
def run_distill(
    source_path: str = typer.Option(
        ...,
        help="Manual JSON/CSV source file or directory containing curated source items.",
    ),
    output_dir: str | None = typer.Option(
        None,
        help="Directory where distilled JSON/YAML outputs will be written.",
    ),
    spec_id: str | None = typer.Option(None, help="Exam spec id."),
) -> None:
    """Run the offline distillation pipeline."""
    settings = get_settings()
    resolved_spec_id = spec_id or settings.default_spec_id
    resolved_source_path = Path(source_path)
    if not resolved_source_path.is_absolute():
        resolved_source_path = settings.repo_root / resolved_source_path

    resolved_output_dir = (
        settings.distilled_root / resolved_spec_id if output_dir is None else Path(output_dir)
    )
    if not resolved_output_dir.is_absolute():
        resolved_output_dir = settings.repo_root / resolved_output_dir

    pipeline = DistillPipeline(spec_id=resolved_spec_id, repo_root=settings.repo_root)
    try:
        manifest = pipeline.run(
            source_path=resolved_source_path,
            output_dir=resolved_output_dir,
        )
    except DistillPipelineError as exc:
        typer.echo(f"Distillation failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(json.dumps(manifest, ensure_ascii=False, indent=2))


@distill_app.command("run-batches")
def run_distill_batches(
    batch_path: str = typer.Option(
        ...,
        help="Curated batch manifest file or directory containing curated batch manifests.",
    ),
    output_dir: str | None = typer.Option(
        None,
        help="Directory where distilled JSON/YAML outputs will be written.",
    ),
    spec_id: str | None = typer.Option(None, help="Exam spec id."),
) -> None:
    """Run the distillation pipeline over one or more curated source batches."""
    settings = get_settings()
    resolved_spec_id = spec_id or settings.default_spec_id
    resolved_batch_path = Path(batch_path)
    if not resolved_batch_path.is_absolute():
        resolved_batch_path = settings.repo_root / resolved_batch_path

    resolved_output_dir = (
        settings.distilled_root / resolved_spec_id if output_dir is None else Path(output_dir)
    )
    if not resolved_output_dir.is_absolute():
        resolved_output_dir = settings.repo_root / resolved_output_dir

    pipeline = DistillPipeline(spec_id=resolved_spec_id, repo_root=settings.repo_root)
    try:
        manifest = pipeline.run_batches(
            batch_path=resolved_batch_path,
            output_dir=resolved_output_dir,
        )
    except DistillPipelineError as exc:
        typer.echo(f"Distillation failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(json.dumps(manifest, ensure_ascii=False, indent=2))


@distill_app.command("coverage-stats")
def distill_coverage_stats(
    distilled_dir: str | None = typer.Option(
        None,
        help="Directory containing distilled outputs such as item_cards.json and manifest.json.",
    ),
    spec_id: str | None = typer.Option(None, help="Exam spec id."),
) -> None:
    """Print coverage statistics for an existing distilled output directory."""
    settings = get_settings()
    resolved_spec_id = spec_id or settings.default_spec_id
    resolved_distilled_dir = (
        settings.distilled_root / resolved_spec_id if distilled_dir is None else Path(distilled_dir)
    )
    if not resolved_distilled_dir.is_absolute():
        resolved_distilled_dir = settings.repo_root / resolved_distilled_dir

    pipeline = DistillPipeline(spec_id=resolved_spec_id, repo_root=settings.repo_root)
    try:
        coverage = pipeline.coverage_stats_from_distilled_dir(resolved_distilled_dir)
    except DistillPipelineError as exc:
        typer.echo(f"Coverage stats failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(json.dumps(coverage, ensure_ascii=False, indent=2))


@assemble_app.command("exam")
def assemble_exam(
    run_id: str = typer.Option(..., help="Logical run id."),
    force: bool = typer.Option(False, help="Rebuild the render bundle even if one already exists."),
) -> None:
    """Assemble approved validated items into a render bundle."""
    try:
        summary = _assembler().assemble_from_run(run_id=run_id, force=force)
    except Exception as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(summary.model_dump_json(indent=2))


@render_app.command("exam")
def render_exam(
    run_id: str = typer.Option(..., help="Logical run id."),
    output_dir: str | None = typer.Option(
        None,
        help="Directory where exam.tex/pdf and validation_report.tex/pdf will be written.",
    ),
    compile_pdf: bool = typer.Option(
        True,
        "--compile-pdf/--tex-only",
        help="Attempt XeLaTeX compilation after writing TeX sources.",
    ),
    force_assemble: bool = typer.Option(
        False,
        help="Rebuild the assembly bundle before rendering.",
    ),
) -> None:
    """Render the exam paper and validation report."""
    assembler = _assembler()
    renderer = _renderer()
    resolved_output_dir = _resolve_output_dir(output_dir, f"{run_id}/exam_render")

    try:
        bundle, summary = assembler.bundle_for_run(run_id=run_id, force=force_assemble)
        validator_reports = assembler.load_validator_suite_reports(run_id=run_id)
        documents = [
            renderer.render_exam(
                bundle=bundle,
                output_dir=resolved_output_dir,
                compile_pdf=compile_pdf,
            ),
            renderer.render_validation_report(
                bundle=bundle,
                validator_reports=validator_reports,
                output_dir=resolved_output_dir,
                compile_pdf=compile_pdf,
            ),
        ]
        result = RenderJobResult(
            run_id=run_id,
            spec_id=bundle.spec_id,
            bundle_artifact_id=summary.bundle_artifact_id,
            validator_suite_artifact_ids=summary.validator_suite_artifact_ids,
            output_dir=str(resolved_output_dir),
            documents=documents,
        )
        renderer.write_manifest(output_dir=resolved_output_dir, result=result)
        envelope = _store().save_model(
            result,
            stage=PipelineStage.RENDER,
            run_id=run_id,
            spec_id=bundle.spec_id,
            metadata={
                "bundle_artifact_id": summary.bundle_artifact_id,
                "validator_suite_artifact_ids": summary.validator_suite_artifact_ids,
                "output_dir": str(resolved_output_dir),
                "render_kinds": ["exam", "validation_report"],
            },
        )
    except Exception as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(
        json.dumps(
            {
                "render_artifact_id": envelope.artifact_id,
                "output_dir": str(resolved_output_dir),
                "documents": [document.model_dump(mode="json") for document in result.documents],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


@render_app.command("answer-key")
def render_answer_key(
    run_id: str = typer.Option(..., help="Logical run id."),
    output_dir: str | None = typer.Option(
        None,
        help="Directory where answer_key.tex/pdf will be written.",
    ),
    compile_pdf: bool = typer.Option(
        True,
        "--compile-pdf/--tex-only",
        help="Attempt XeLaTeX compilation after writing the TeX source.",
    ),
    force_assemble: bool = typer.Option(
        False,
        help="Rebuild the assembly bundle before rendering.",
    ),
) -> None:
    """Render only the answer-key document."""
    assembler = _assembler()
    renderer = _renderer()
    resolved_output_dir = _resolve_output_dir(output_dir, f"{run_id}/answer_key_render")

    try:
        bundle, summary = assembler.bundle_for_run(run_id=run_id, force=force_assemble)
        document = renderer.render_answer_key(
            bundle=bundle,
            output_dir=resolved_output_dir,
            compile_pdf=compile_pdf,
        )
        result = RenderJobResult(
            run_id=run_id,
            spec_id=bundle.spec_id,
            bundle_artifact_id=summary.bundle_artifact_id,
            validator_suite_artifact_ids=[],
            output_dir=str(resolved_output_dir),
            documents=[document],
        )
        renderer.write_manifest(output_dir=resolved_output_dir, result=result)
        envelope = _store().save_model(
            result,
            stage=PipelineStage.RENDER,
            run_id=run_id,
            spec_id=bundle.spec_id,
            metadata={
                "bundle_artifact_id": summary.bundle_artifact_id,
                "output_dir": str(resolved_output_dir),
                "render_kinds": ["answer_key"],
            },
        )
    except Exception as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(
        json.dumps(
            {
                "render_artifact_id": envelope.artifact_id,
                "output_dir": str(resolved_output_dir),
                "documents": [entry.model_dump(mode="json") for entry in result.documents],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    app()
