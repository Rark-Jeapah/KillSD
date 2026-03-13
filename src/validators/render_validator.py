"""Render validator for LaTeX dry-runs and asset checks."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from src.core.schemas import (
    SolvedItem,
    ValidationFinding,
)
from src.render.latex_renderer import escape_latex
from src.validators import reason_codes as rc
from src.validators.report import ValidatorSectionResult


ASCII_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
ASSET_TOKEN_STOPWORDS = {
    "asset",
    "diagram",
    "figure",
    "image",
    "img",
    "final",
    "draft",
    "student",
}

def _has_balanced_inline_math(text: str) -> bool:
    return text.count("$") % 2 == 0


def _has_balanced_braces(text: str) -> bool:
    balance = 0
    for char in text:
        if char == "{":
            balance += 1
        elif char == "}":
            balance -= 1
            if balance < 0:
                return False
    return balance == 0


def _tokenize_ascii(text: str) -> set[str]:
    return {token for token in ASCII_TOKEN_PATTERN.findall(text.lower()) if len(token) >= 3}


def _extract_asset_tokens(asset_ref: str) -> set[str]:
    return {
        token
        for token in _tokenize_ascii(Path(asset_ref).stem)
        if token not in ASSET_TOKEN_STOPWORDS
    }


def _validate_diagram_asset(candidate: Path) -> tuple[bool, str]:
    if not candidate.is_file():
        return False, "asset is not a regular file"
    if candidate.stat().st_size == 0:
        return False, "asset file is empty"

    suffix = candidate.suffix.lower()
    if suffix == ".svg":
        content = candidate.read_text(encoding="utf-8", errors="ignore").lower()
        return ("<svg" in content, "svg root tag missing")
    if suffix in {".tex", ".tikz"}:
        content = candidate.read_text(encoding="utf-8", errors="ignore")
        if not _has_balanced_inline_math(content):
            return False, "asset has unbalanced inline math delimiters"
        if not _has_balanced_braces(content):
            return False, "asset has unbalanced braces"
        return True, "ok"
    if suffix == ".pdf":
        return (candidate.read_bytes().startswith(b"%PDF-"), "pdf header missing")
    if suffix == ".png":
        return (
            candidate.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"),
            "png signature missing",
        )
    if suffix in {".jpg", ".jpeg"}:
        return (candidate.read_bytes().startswith(b"\xff\xd8\xff"), "jpeg signature missing")
    return True, "ok"


def _resolve_explicit_xelatex_path(candidate: str | None) -> str | None:
    if not candidate:
        return None

    expanded_candidate = Path(candidate).expanduser()
    if expanded_candidate.is_file():
        return str(expanded_candidate.resolve())

    return shutil.which(candidate)


def _resolve_xelatex_path(configured_path: str | None = None) -> str | None:
    compiler = _resolve_explicit_xelatex_path(configured_path)
    if compiler is not None:
        return compiler

    compiler = _resolve_explicit_xelatex_path(os.getenv("CSAT_XELATEX_PATH"))
    if compiler is not None:
        return compiler

    return shutil.which("xelatex")


def _decode_output(stream: bytes | None) -> str:
    if not stream:
        return ""
    return stream.decode("utf-8", errors="replace")


def _build_xelatex_dry_run_document(content: str) -> str:
    return "\n".join(
        [
            r"\documentclass{article}",
            r"\usepackage{kotex}",
            r"\usepackage{amsmath}",
            r"\begin{document}",
            content,
            r"\end{document}",
        ]
    )


def _latex_compile_dry_run(content: str, *, xelatex_path: str | None = None) -> tuple[bool, str]:
    compiler = _resolve_xelatex_path(xelatex_path)
    if compiler is None:
        return True, "XeLaTeX unavailable; compile dry-run skipped."

    with tempfile.TemporaryDirectory(prefix="csat-render-") as tmp_dir:
        workdir = Path(tmp_dir)
        tex_path = workdir / "item.tex"
        tex_path.write_text(content, encoding="utf-8")
        command = [compiler, "-interaction=nonstopmode", "-halt-on-error", tex_path.name]
        result = subprocess.run(
            command,
            cwd=workdir,
            capture_output=True,
            check=False,
        )
        message = "\n".join(
            fragment for fragment in (_decode_output(result.stdout), _decode_output(result.stderr)) if fragment
        ).strip()
        if not message:
            message = f"XeLaTeX exited with code {result.returncode}."
        return result.returncode == 0, message


def validate_render(
    *,
    solved_item: SolvedItem,
    asset_root: Path | None,
    asset_refs: list[str],
    xelatex_path: str | None = None,
) -> ValidatorSectionResult:
    """Validate renderability and diagram asset references."""
    combined_text = "\n".join(
        [
            solved_item.draft.blueprint.objective,
            " ".join(solved_item.draft.blueprint.skill_tags),
            solved_item.draft.stem,
            *solved_item.draft.choices,
            *solved_item.solution_steps,
        ]
    )
    has_balanced_inline_math = _has_balanced_inline_math(combined_text)
    has_balanced_braces = _has_balanced_braces(combined_text)
    findings = [
        ValidationFinding(
            check_name="balanced_inline_math",
            validator_name="render_validator",
            passed=has_balanced_inline_math,
            severity=rc.RENDER_UNBALANCED_INLINE_MATH.default_severity,
            message="inline math delimiters are balanced",
            reason_code=rc.RENDER_UNBALANCED_INLINE_MATH.code,
            failure_level=rc.RENDER_UNBALANCED_INLINE_MATH.default_failure_level,
            recommendation="Fix broken `$...$` delimiters before keeping the item."
            if not has_balanced_inline_math
            else None,
        ),
        ValidationFinding(
            check_name="balanced_braces",
            validator_name="render_validator",
            passed=has_balanced_braces,
            severity=rc.RENDER_UNBALANCED_BRACES.default_severity,
            message="brace structure is balanced",
            reason_code=rc.RENDER_UNBALANCED_BRACES.code,
            failure_level=rc.RENDER_UNBALANCED_BRACES.default_failure_level,
            recommendation="Repair broken LaTeX/math brace structure."
            if not has_balanced_braces
            else None,
        ),
    ]

    missing_assets: list[str] = []
    invalid_assets: dict[str, str] = {}
    valid_asset_refs: list[str] = []
    if asset_root is not None:
        for asset_ref in asset_refs:
            candidate = asset_root / asset_ref
            if not candidate.exists():
                missing_assets.append(asset_ref)
                continue
            asset_valid, detail = _validate_diagram_asset(candidate)
            if not asset_valid:
                invalid_assets[asset_ref] = detail
                continue
            valid_asset_refs.append(asset_ref)
    findings.append(
        ValidationFinding(
            check_name="diagram_assets_present",
            validator_name="render_validator",
            passed=not missing_assets,
            severity=(
                rc.RENDER_MISSING_DIAGRAM_ASSET.default_severity
                if missing_assets
                else rc.RENDER_LATEX_COMPILE_OK.default_severity
            ),
            message="all referenced diagram assets are available",
            reason_code=rc.RENDER_MISSING_DIAGRAM_ASSET.code,
            failure_level=rc.RENDER_MISSING_DIAGRAM_ASSET.default_failure_level,
            recommendation="Provide the missing diagram asset or remove the broken reference."
            if missing_assets
            else None,
            context={"missing_assets": missing_assets},
        )
    )
    findings.append(
        ValidationFinding(
            check_name="diagram_assets_well_formed",
            validator_name="render_validator",
            passed=not invalid_assets,
            severity=(
                rc.RENDER_INVALID_DIAGRAM_ASSET.default_severity
                if invalid_assets
                else rc.RENDER_LATEX_COMPILE_OK.default_severity
            ),
            message="all referenced diagram assets are non-empty and structurally valid",
            reason_code=rc.RENDER_INVALID_DIAGRAM_ASSET.code,
            failure_level=rc.RENDER_INVALID_DIAGRAM_ASSET.default_failure_level,
            recommendation="Replace or rebuild malformed diagram assets before keeping the item."
            if invalid_assets
            else None,
            context={"invalid_assets": invalid_assets},
        )
    )

    item_tokens = _tokenize_ascii(
        " ".join(
            [
                solved_item.draft.blueprint.objective,
                " ".join(solved_item.draft.blueprint.skill_tags),
                solved_item.draft.stem,
                " ".join(solved_item.solution_steps),
            ]
        )
    )
    asset_tokens = sorted({token for asset_ref in valid_asset_refs for token in _extract_asset_tokens(asset_ref)})
    relevance_hits = sorted(token for token in asset_tokens if token in item_tokens)
    findings.append(
        ValidationFinding(
            check_name="diagram_relevance",
            validator_name="render_validator",
            passed=not asset_tokens or bool(relevance_hits),
            severity=rc.RENDER_DIAGRAM_IRRELEVANT_TO_STEM.default_severity,
            message="diagram asset names overlap with the item objective, stem, or skill tags",
            reason_code=rc.RENDER_DIAGRAM_IRRELEVANT_TO_STEM.code,
            failure_level=rc.RENDER_DIAGRAM_IRRELEVANT_TO_STEM.default_failure_level,
            recommendation="Swap in a diagram whose asset tags actually match the math described in the item."
            if asset_tokens and not relevance_hits
            else None,
            context={"asset_tokens": asset_tokens, "item_tokens": sorted(item_tokens), "relevance_hits": relevance_hits},
        )
    )

    if has_balanced_inline_math and has_balanced_braces:
        tex_document = _build_xelatex_dry_run_document(
            "\n\n".join(
                [
                    escape_latex(solved_item.draft.stem),
                    *[escape_latex(choice) for choice in solved_item.draft.choices],
                ]
            )
        )
        latex_ok, latex_message = _latex_compile_dry_run(tex_document, xelatex_path=xelatex_path)
    else:
        latex_ok = True
        latex_message = "Compile dry-run skipped because prerequisite render checks already failed."
    findings.append(
        ValidationFinding(
            check_name="latex_compile_dry_run",
            validator_name="render_validator",
            passed=latex_ok,
            severity=(
                rc.RENDER_LATEX_COMPILE_FAILED.default_severity
                if not latex_ok
                else rc.RENDER_LATEX_COMPILE_OK.default_severity
            ),
            message=latex_message[:500] if latex_message else "LaTeX dry-run completed",
            reason_code=(
                rc.RENDER_LATEX_COMPILE_FAILED.code
                if not latex_ok
                else rc.RENDER_LATEX_COMPILE_OK.code
            ),
            failure_level=(
                rc.RENDER_LATEX_COMPILE_FAILED.default_failure_level
                if not latex_ok
                else rc.RENDER_LATEX_COMPILE_OK.default_failure_level
            ),
            recommendation="Repair broken math markup before rendering."
            if not latex_ok
            else None,
        )
    )

    return ValidatorSectionResult(
        validator_name="render_validator",
        findings=findings,
        metrics={
            "asset_ref_count": len(asset_refs),
            "asset_root": str(asset_root) if asset_root else None,
            "xelatex_path": xelatex_path,
        },
    )
