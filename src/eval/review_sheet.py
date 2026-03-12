"""Human review sheet generator for the real-item gauntlet."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def build_review_sheet(
    *,
    item_payload: dict[str, Any],
    solution_payload: dict[str, Any],
    validation_payload: dict[str, Any],
    lineage_payload: dict[str, Any],
) -> str:
    """Return a markdown review sheet for one generated item bundle."""
    checks = validation_payload.get("custom_checks", [])
    success_criteria = validation_payload.get("success_criteria", {})
    stage_history = lineage_payload.get("stage_history", [])
    failed_checks = [check for check in checks if not check.get("passed", False)]

    lines = [
        "# Human Review Sheet",
        "",
        "## Item Snapshot",
        f"- item_id: `{item_payload.get('item_id')}`",
        f"- run_id: `{item_payload.get('run_id')}`",
        f"- item_no: `{item_payload.get('item_no')}`",
        f"- format: `{item_payload.get('format')}`",
        f"- score: `{item_payload.get('score')}`",
        "",
        "### Stem",
        item_payload.get("stem", ""),
        "",
        "### Choices",
    ]
    for index, choice in enumerate(item_payload.get("choices", []), start=1):
        lines.append(f"{index}. {choice}")

    lines.extend(
        [
            "",
            "## Answer And Reasoning",
            f"- final_answer: `{solution_payload.get('final_answer')}`",
            f"- correct_choice_index: `{solution_payload.get('correct_choice_index')}`",
            f"- correct_choice_value: `{solution_payload.get('correct_choice_value')}`",
            "",
            "### Solution Steps",
        ]
    )
    for step_index, step in enumerate(solution_payload.get("solution_steps", []), start=1):
        lines.append(f"{step_index}. {step}")

    lines.extend(
        [
            "",
            "### Solution Summary",
            solution_payload.get("solution_summary", ""),
            "",
            "## Validation",
            f"- status: `{validation_payload.get('status')}`",
            f"- approval_status: `{validation_payload.get('approval_status')}`",
            "",
            "### Success Criteria",
        ]
    )
    for name, passed in success_criteria.items():
        lines.append(f"- {name}: `{'pass' if passed else 'fail'}`")

    lines.extend(["", "### Custom Checks"])
    for check in checks:
        status = "pass" if check.get("passed") else "fail"
        lines.append(f"- {check.get('check_name')}: `{status}` - {check.get('message')}")

    lines.extend(["", "### Regenerate Rule"])
    regenerate_rule = validation_payload.get("regenerate_rule", {})
    lines.append(f"- action: `{regenerate_rule.get('action', 'unknown')}`")
    for condition in regenerate_rule.get("when", []):
        lines.append(f"- when: {condition}")
    if regenerate_rule.get("next_step"):
        lines.append(f"- next_step: {regenerate_rule['next_step']}")

    lines.extend(["", "## Reviewer Checklist"])
    reviewer_prompts = [
        "문항 조건이 실제 수학 문제로 자연스럽게 읽히는가?",
        "정답 선지 외의 오답 선지 4개가 각각 그럴듯한 오개념을 반영하는가?",
        "풀이 단계가 생략 없이 연결되고 계산 근거가 충분한가?",
        "학생 노출 텍스트에 내부 메타데이터가 섞여 있지 않은가?",
    ]
    for prompt in reviewer_prompts:
        lines.append(f"- [ ] {prompt}")

    lines.extend(["", "## Lineage"])
    for record in stage_history:
        lines.append(
            f"- {record.get('stage_name')} / attempt {record.get('attempt')} / "
            f"status `{record.get('status')}` / output `{record.get('output_artifact_id')}`"
        )

    if failed_checks:
        lines.extend(["", "## Open Issues"])
        for check in failed_checks:
            lines.append(
                f"- {check.get('check_name')}: {check.get('recommendation') or check.get('message')}"
            )

    return "\n".join(lines).strip() + "\n"


def write_review_sheet(
    *,
    output_path: Path,
    item_payload: dict[str, Any],
    solution_payload: dict[str, Any],
    validation_payload: dict[str, Any],
    lineage_payload: dict[str, Any],
) -> Path:
    """Write the review sheet to disk and return the target path."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        build_review_sheet(
            item_payload=item_payload,
            solution_payload=solution_payload,
            validation_payload=validation_payload,
            lineage_payload=lineage_payload,
        ),
        encoding="utf-8",
    )
    return output_path
