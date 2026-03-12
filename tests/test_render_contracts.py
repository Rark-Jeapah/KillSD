"""Render-contract tests for student/internal separation and compile behavior."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.core.schemas import (
    ApprovalStatus,
    DraftItem,
    ExamMode,
    ItemFormat,
    RenderBundle,
    SolvedItem,
    ValidationFinding,
    ValidationReport,
    ValidationSeverity,
    ValidationStatus,
    ValidatedItem,
)
from src.core.storage import ArtifactStore
from src.eval.benchmark_runner import BenchmarkCase, BenchmarkRunner, BenchmarkRunnerError
from src.plugins.csat_math_2028 import CSATMath2028Plugin
from src.render.contracts import RendererConfig
from src.render.latex_renderer import LaTeXRenderer, RenderJobResult, RenderedDocument
from src.validators.report import DifficultyEstimate, ValidatorSectionResult, ValidatorSuiteReport


REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DIR = REPO_ROOT / "src" / "render" / "templates"


def _build_render_fixture() -> tuple[RenderBundle, list[ValidatorSuiteReport]]:
    blueprint = CSATMath2028Plugin().build_default_blueprint()
    validated_items: list[ValidatedItem] = []
    validator_reports: list[ValidatorSuiteReport] = []

    for item_blueprint in blueprint.item_blueprints:
        if item_blueprint.format == ItemFormat.MULTIPLE_CHOICE:
            choices = [f"ITEM{item_blueprint.item_no}_CHOICE_{index}" for index in range(1, 6)]
            correct_choice_index = ((item_blueprint.item_no - 1) % 5) + 1
            final_answer = str(correct_choice_index)
            correct_choice_value = choices[correct_choice_index - 1]
        else:
            choices = []
            correct_choice_index = None
            correct_choice_value = None
            final_answer = str(100 + item_blueprint.item_no)

        solved_item = SolvedItem(
            draft=DraftItem(
                blueprint=item_blueprint,
                stem=f"{item_blueprint.objective}을 검증하는 {item_blueprint.item_no}번 문항이다.",
                choices=choices,
                rubric="정상 렌더링 검증용 문항이다.",
                answer_constraints=[item_blueprint.answer_type],
            ),
            final_answer=final_answer,
            correct_choice_index=correct_choice_index,
            correct_choice_value=correct_choice_value,
            solution_steps=["조건을 정리한다.", "풀이를 완성한다."],
            solution_summary="렌더 계약 테스트용 풀이이다.",
        )
        final_report = ValidationReport(
            item_no=item_blueprint.item_no,
            status=ValidationStatus.PASS,
            findings=[
                ValidationFinding(
                    check_name="fixture_pass",
                    passed=True,
                    severity=ValidationSeverity.INFO,
                    message="fixture validation pass",
                    validator_name="test_fixture",
                )
            ],
            summary="fixture pass",
        )
        validated_items.append(
            ValidatedItem(
                solved=solved_item,
                validation=final_report,
                approval_status=ApprovalStatus.APPROVED,
            )
        )
        validator_reports.append(
            ValidatorSuiteReport(
                spec_id=blueprint.spec_id,
                item_no=item_blueprint.item_no,
                sections=[
                    ValidatorSectionResult(
                        validator_name="fixture_validator",
                        findings=final_report.findings,
                        metrics={"item_no": item_blueprint.item_no},
                    )
                ],
                difficulty_estimate=DifficultyEstimate(
                    expected_step_count=2,
                    concept_count=2,
                    branching_factor=1.0,
                    solver_disagreement_score=0.0,
                    predicted_band=item_blueprint.difficulty.value,
                ),
                final_report=final_report,
            )
        )

    bundle = RenderBundle(
        spec_id=blueprint.spec_id,
        blueprint_id=blueprint.blueprint_id,
        items=validated_items,
        student_metadata={
            "title": "Fixture Exam",
            "duration_minutes": "100",
            "total_score": "100",
        },
        internal_metadata={
            "topic_coverage": "SECRET_TOPIC_COVERAGE",
            "difficulty_curve": "SECRET_DIFFICULTY_CURVE",
            "debug_note": "DEBUG_NOTE_SHOULD_NOT_RENDER",
        },
        output_targets=["exam_pdf", "answer_key_pdf", "validation_report_pdf"],
        answer_key={
            item.solved.draft.blueprint.item_no: item.solved.final_answer for item in validated_items
        },
    )
    return bundle, validator_reports


def _install_fake_xelatex(script_path: Path) -> None:
    script_path.write_text(
        """#!/bin/sh
outdir=""
texfile=""
expect_outdir=0
for arg in "$@"; do
  if [ "$expect_outdir" -eq 1 ]; then
    outdir="$arg"
    expect_outdir=0
    continue
  fi
  if [ "$arg" = "-output-directory" ]; then
    expect_outdir=1
    continue
  fi
  texfile="$arg"
done
base="${texfile%.tex}"
printf '%s\n' '%PDF-1.4 fake render output' > "$outdir/$base.pdf"
exit 0
""",
        encoding="utf-8",
    )
    script_path.chmod(0o755)


def test_student_exam_render_excludes_internal_metadata(tmp_path: Path) -> None:
    bundle, _ = _build_render_fixture()
    renderer = LaTeXRenderer(template_dir=TEMPLATE_DIR)

    document = renderer.render_exam(bundle=bundle, output_dir=tmp_path, compile_pdf=False)
    source = Path(document.tex_path).read_text(encoding="utf-8")

    assert "SECRET_TOPIC_COVERAGE" not in source
    assert "SECRET_DIFFICULTY_CURVE" not in source
    assert "DEBUG_NOTE_SHOULD_NOT_RENDER" not in source
    assert "Fixture Exam" in source


def test_renderer_uses_configured_xelatex_absolute_path(
    tmp_path: Path, monkeypatch
) -> None:
    bundle, validator_reports = _build_render_fixture()
    fake_xelatex = tmp_path / "bin" / "xelatex"
    fake_xelatex.parent.mkdir(parents=True, exist_ok=True)
    _install_fake_xelatex(fake_xelatex)
    monkeypatch.setenv("PATH", "")

    renderer = LaTeXRenderer(
        template_dir=TEMPLATE_DIR,
        config=RendererConfig(xelatex_path=str(fake_xelatex)),
    )
    result = renderer.render_exam_set(
        run_id="render-contract",
        bundle=bundle,
        bundle_artifact_id="bundle-fixture",
        validator_reports=validator_reports,
        validator_suite_artifact_ids=[],
        output_dir=tmp_path / "rendered",
        compile_pdf=True,
    )

    assert len(result.documents) == 3
    for document in result.documents:
        assert document.compiled is True
        assert document.pdf_path is not None
        assert Path(document.pdf_path).exists()
        assert document.compiler == str(fake_xelatex.resolve())


def test_benchmark_runner_rejects_uncompiled_pdf_attempts(tmp_path: Path) -> None:
    runner = BenchmarkRunner(
        artifact_store=ArtifactStore(root_dir=tmp_path / "artifacts", db_path=tmp_path / "app.db"),
        prompt_dir=REPO_ROOT / "src" / "prompts",
        template_dir=TEMPLATE_DIR,
    )
    case = BenchmarkCase(
        case_id="compile-contract",
        run_id_prefix="compile-contract",
        mode=ExamMode.API,
        seed=7,
        compile_pdf=True,
    )
    render_result = RenderJobResult(
        run_id="compile-contract",
        spec_id="csat_math_2028",
        bundle_artifact_id="bundle-fixture",
        validator_suite_artifact_ids=[],
        output_dir=str(tmp_path / "rendered"),
        documents=[
            RenderedDocument(
                kind="exam",
                template_name="exam.tex.j2",
                tex_path=str(tmp_path / "rendered" / "exam.tex"),
                compiled=False,
                pdf_path=None,
            )
        ],
    )

    with pytest.raises(BenchmarkRunnerError, match="compile_pdf=true requires compiled PDFs"):
        runner._assert_compiled_documents(case=case, render_result=render_result)
