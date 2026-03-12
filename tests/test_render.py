"""Integration tests for assembly and LaTeX rendering."""

from __future__ import annotations

import shutil
from pathlib import Path

from src.assembly.exam_assembler import ExamAssembler
from src.core.schemas import ExamMode
from src.core.storage import ArtifactStore
from src.orchestrator.state_machine import GenerationStateMachine, RunStatus
from src.providers.mock_provider import MockProvider
from src.render.latex_renderer import LaTeXRenderer


REPO_ROOT = Path(__file__).resolve().parents[1]
PROMPT_DIR = REPO_ROOT / "src" / "prompts"
TEMPLATE_DIR = REPO_ROOT / "src" / "render" / "templates"


def test_assemble_and_render_with_mock_provider(tmp_path: Path) -> None:
    store = ArtifactStore(root_dir=tmp_path / "artifacts", db_path=tmp_path / "app.db")
    machine = GenerationStateMachine(
        artifact_store=store,
        prompt_dir=PROMPT_DIR,
        provider=MockProvider(),
    )

    state = machine.run_exam(run_id="render-e2e", mode=ExamMode.API, seed=19)
    assert state.status == RunStatus.COMPLETED

    assembler = ExamAssembler(artifact_store=store)
    bundle, summary = assembler.bundle_for_run(run_id="render-e2e", force=True)
    validator_reports = assembler.load_validator_suite_reports(run_id="render-e2e")

    assert summary.metrics.score_distribution == {2: 3, 3: 14, 4: 13}
    assert len(bundle.items) == 30
    assert len(validator_reports) == 30

    renderer = LaTeXRenderer(template_dir=TEMPLATE_DIR)
    output_dir = tmp_path / "rendered"
    result = renderer.render_exam_set(
        run_id="render-e2e",
        bundle=bundle,
        bundle_artifact_id=summary.bundle_artifact_id,
        validator_reports=validator_reports,
        validator_suite_artifact_ids=summary.validator_suite_artifact_ids,
        output_dir=output_dir,
        compile_pdf=True,
    )

    exam_tex = output_dir / "exam.tex"
    answer_key_tex = output_dir / "answer_key.tex"
    validation_tex = output_dir / "validation_report.tex"
    manifest_path = output_dir / "render_manifest.json"

    assert exam_tex.exists()
    assert answer_key_tex.exists()
    assert validation_tex.exists()
    assert manifest_path.exists()
    assert len(result.documents) == 3

    exam_source = exam_tex.read_text(encoding="utf-8")
    answer_key_source = answer_key_tex.read_text(encoding="utf-8")
    validation_source = validation_tex.read_text(encoding="utf-8")

    assert "\\usepackage{kotex}" in exam_source
    assert "\\begin{tikzpicture}" in exam_source
    assert "문항 1." in exam_source
    assert "정답표" in answer_key_source
    assert "검증 리포트" in validation_source

    xelatex_available = shutil.which("xelatex") is not None
    for document in result.documents:
        if xelatex_available:
            assert document.pdf_path is not None or document.debug_message is not None
        else:
            assert document.compiled is False
            assert document.debug_message is not None
            assert "xelatex not found" in document.debug_message
