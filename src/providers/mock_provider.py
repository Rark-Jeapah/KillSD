"""Deterministic mock provider for orchestrator tests and local smoke runs."""

from __future__ import annotations

import json
from dataclasses import dataclass
from random import Random
from time import perf_counter

from src.core.schemas import (
    CritiqueFinding,
    CritiqueReport,
    DraftItem,
    ExamBlueprint,
    ItemBlueprint,
    ItemFormat,
    SolvedItem,
    ValidationSeverity,
)
from src.plugins.csat_math_2028 import CSATMath2028Plugin
from src.providers.base import BaseProvider, ProviderError, ProviderResponse, ProviderUsage


@dataclass(frozen=True)
class ToyItemSpec:
    """Deterministic toy math content shared across draft/solve/revise."""

    stem: str
    rubric: str
    choices: list[str]
    final_answer: str
    correct_choice_index: int | None
    correct_choice_value: str | None
    solution_steps: list[str]
    solution_summary: str


class MockProvider(BaseProvider):
    """Deterministic mock provider returning schema-valid JSON."""

    provider_name = "mock_provider"

    def invoke(self, packet) -> ProviderResponse:
        started = perf_counter()
        output = self._build_output(packet)
        raw_text = json.dumps(output, ensure_ascii=False)
        prompt_chars = len("".join(packet.instructions)) + len(
            json.dumps(packet.context, ensure_ascii=False, sort_keys=True)
        )
        completion_chars = len(raw_text)
        return ProviderResponse(
            provider_name=self.provider_name,
            prompt_packet_id=packet.packet_id,
            stage_name=packet.stage_name,
            output=output,
            raw_text=raw_text,
            prompt_hash=packet.prompt_hash,
            seed=packet.seed,
            usage=ProviderUsage(
                prompt_chars=prompt_chars,
                completion_chars=completion_chars,
                estimated_cost_usd=0.0,
                latency_ms=int((perf_counter() - started) * 1000),
            ),
        )

    def _build_output(self, packet) -> dict:
        if packet.stage_name == "exam_blueprint":
            blueprint = CSATMath2028Plugin().build_default_blueprint()
            return blueprint.model_dump(mode="json")

        if packet.stage_name == "item_blueprint":
            exam_blueprint = ExamBlueprint.model_validate(packet.context["exam_blueprint"])
            for item_blueprint in exam_blueprint.item_blueprints:
                if item_blueprint.item_no == packet.item_no:
                    return item_blueprint.model_dump(mode="json")
            raise ProviderError(f"item_no={packet.item_no} not found in exam blueprint")

        if packet.stage_name == "draft_item":
            item_blueprint = ItemBlueprint.model_validate(packet.context["item_blueprint"])
            spec = self._build_toy_item_spec(
                blueprint=item_blueprint,
                seed=packet.seed or 0,
            )
            draft = DraftItem(
                blueprint=item_blueprint,
                stem=spec.stem,
                choices=spec.choices,
                rubric=spec.rubric,
                answer_constraints=[item_blueprint.answer_type],
            )
            return draft.model_dump(mode="json")

        if packet.stage_name == "solve":
            draft = DraftItem.model_validate(packet.context["draft_item"])
            spec = self._build_toy_item_spec(
                blueprint=draft.blueprint,
                seed=packet.seed or 0,
            )
            solved = SolvedItem(
                draft=draft,
                final_answer=spec.final_answer,
                correct_choice_index=spec.correct_choice_index,
                correct_choice_value=spec.correct_choice_value,
                solution_steps=spec.solution_steps,
                solution_summary=spec.solution_summary,
            )
            return solved.model_dump(mode="json")

        if packet.stage_name == "critique":
            solved = SolvedItem.model_validate(packet.context["solved_item"])
            critique = self._build_critique_report(solved)
            return critique.model_dump(mode="json")

        if packet.stage_name == "revise":
            solved = SolvedItem.model_validate(packet.context["solved_item"])
            revised = self._build_revised_solution(solved)
            return revised.model_dump(mode="json")

        raise ProviderError(f"Unsupported mock stage: {packet.stage_name}")

    def _build_toy_item_spec(self, *, blueprint: ItemBlueprint, seed: int) -> ToyItemSpec:
        rng = self._seeded_rng(seed=seed, item_no=blueprint.item_no)
        if blueprint.domain == "algebra":
            if blueprint.format == ItemFormat.MULTIPLE_CHOICE:
                return self._build_algebra_mcq(blueprint=blueprint, rng=rng)
            return self._build_algebra_short_answer(blueprint=blueprint, rng=rng)
        if blueprint.domain == "calculus_1":
            if blueprint.format == ItemFormat.MULTIPLE_CHOICE:
                return self._build_calculus_mcq(blueprint=blueprint, rng=rng)
            return self._build_calculus_short_answer(blueprint=blueprint, rng=rng)
        if blueprint.domain == "probability_statistics":
            if blueprint.format == ItemFormat.MULTIPLE_CHOICE:
                return self._build_probability_mcq(blueprint=blueprint, rng=rng)
            return self._build_probability_short_answer(blueprint=blueprint, rng=rng)
        raise ProviderError(f"Unsupported mock domain: {blueprint.domain}")

    @staticmethod
    def _seeded_rng(*, seed: int, item_no: int) -> Random:
        return Random(((seed + 1) * 1009) + (item_no * 917))

    @staticmethod
    def _correct_choice_index(item_no: int) -> int:
        return ((item_no - 1) % 5) + 1

    @classmethod
    def _place_correct_choice(
        cls,
        *,
        correct_value: str,
        distractors: list[int | str],
        item_no: int,
    ) -> tuple[list[str], int, str]:
        correct_choice_index = cls._correct_choice_index(item_no)
        unique_distractors: list[str] = []
        for candidate in distractors:
            candidate_text = str(candidate)
            if candidate_text == correct_value or candidate_text in unique_distractors:
                continue
            unique_distractors.append(candidate_text)

        numeric_correct = int(correct_value) if correct_value.lstrip("-").isdigit() else None
        fallback_offset = 7
        while len(unique_distractors) < 4:
            if numeric_correct is None:
                candidate_text = f"{correct_value}_{len(unique_distractors) + 1}"
            else:
                candidate_text = str(numeric_correct + fallback_offset)
                fallback_offset += 3
            if candidate_text == correct_value or candidate_text in unique_distractors:
                continue
            unique_distractors.append(candidate_text)

        choices: list[str] = []
        distractor_iter = iter(unique_distractors[:4])
        for index in range(1, 6):
            if index == correct_choice_index:
                choices.append(correct_value)
            else:
                choices.append(next(distractor_iter))

        return choices, correct_choice_index, choices[correct_choice_index - 1]

    def _build_algebra_mcq(self, *, blueprint: ItemBlueprint, rng: Random) -> ToyItemSpec:
        n = 2 + rng.randrange(4)
        sum_value = (2 * n) + 1
        product_value = n * (n + 1)
        correct_value = str((n * n) + ((n + 1) * (n + 1)))
        choices, correct_index, choice_value = self._place_correct_choice(
            correct_value=correct_value,
            distractors=[
                (sum_value * sum_value) - product_value,
                sum_value * sum_value,
                2 * product_value,
                1,
            ],
            item_no=blueprint.item_no,
        )
        return ToyItemSpec(
            stem=(
                f"두 실수 x, y가 x+y={sum_value}, xy={product_value}를 만족한다. "
                "x^2+y^2의 값은 얼마인가."
            ),
            rubric="합과 곱을 이용해 x^2+y^2=(x+y)^2-2xy로 바꾸어 계산한다.",
            choices=choices,
            final_answer=str(correct_index),
            correct_choice_index=correct_index,
            correct_choice_value=choice_value,
            solution_steps=[
                f"x+y={sum_value}, xy={product_value}이므로 x^2+y^2=(x+y)^2-2xy를 사용한다.",
                f"정리하면 x^2+y^2={sum_value}^2-2*{product_value}={correct_value}이다.",
                f"따라서 알맞은 선택지는 {correct_index}번 {choice_value}이다.",
            ],
            solution_summary="합과 곱의 대칭식을 이용하면 제곱합을 바로 계산할 수 있다.",
        )

    def _build_algebra_short_answer(self, *, blueprint: ItemBlueprint, rng: Random) -> ToyItemSpec:
        sum_value = 3 + rng.randrange(4)
        answer_value = str((sum_value * sum_value) - 2)
        return ToyItemSpec(
            stem=(
                f"0이 아닌 실수 x가 x+1/x={sum_value}를 만족한다. "
                "x^2+1/x^2의 값은 얼마인가."
            ),
            rubric="주어진 식을 제곱해 x^2+1/x^2를 분리한다.",
            choices=[],
            final_answer=answer_value,
            correct_choice_index=None,
            correct_choice_value=None,
            solution_steps=[
                f"x+1/x={sum_value}이므로 양변을 제곱한다.",
                f"정리하면 x^2+2+1/x^2={sum_value}^2이므로 x^2+1/x^2={answer_value}이다.",
                f"따라서 답은 {answer_value}이다.",
            ],
            solution_summary="대칭식 x+1/x를 제곱하면 원하는 값을 한 번에 얻는다.",
        )

    def _build_calculus_mcq(self, *, blueprint: ItemBlueprint, rng: Random) -> ToyItemSpec:
        parameter_value = 3 + rng.randrange(5)
        slope_value = 6 - parameter_value
        correct_value = str(parameter_value)
        choices, correct_index, choice_value = self._place_correct_choice(
            correct_value=correct_value,
            distractors=[
                parameter_value - 2,
                parameter_value - 1,
                parameter_value + 1,
                parameter_value + 2,
            ],
            item_no=blueprint.item_no,
        )
        return ToyItemSpec(
            stem=(
                "함수 f(x)=x^2-ax+1에서 x=3에서의 접선 기울기가 "
                f"{slope_value}일 때, 상수 a의 값은 얼마인가."
            ),
            rubric="도함수 f'(x)=2x-a를 이용해 한 점에서의 기울기 조건을 식으로 바꾼다.",
            choices=choices,
            final_answer=str(correct_index),
            correct_choice_index=correct_index,
            correct_choice_value=choice_value,
            solution_steps=[
                "f'(x)=2x-a이므로 x=3에서의 접선 기울기는 6-a이다.",
                f"문제의 조건에 따라 6-a={slope_value}이므로 a={correct_value}이다.",
                f"따라서 알맞은 선택지는 {correct_index}번 {choice_value}이다.",
            ],
            solution_summary="도함수에 x=3을 대입해 접선 기울기 조건을 바로 푼다.",
        )

    def _build_calculus_short_answer(self, *, blueprint: ItemBlueprint, rng: Random) -> ToyItemSpec:
        answer_value = 2 + rng.randrange(5)
        linear_coefficient = 2 * answer_value
        return ToyItemSpec(
            stem=(
                f"함수 f(x)=x^2-{linear_coefficient}x+1의 접선 기울기가 "
                "0이 되는 양의 x의 값은 얼마인가."
            ),
            rubric="도함수를 구한 뒤 접선 기울기가 0인 점을 찾는다.",
            choices=[],
            final_answer=str(answer_value),
            correct_choice_index=None,
            correct_choice_value=None,
            solution_steps=[
                f"f'(x)=2x-{linear_coefficient}이다.",
                f"접선 기울기가 0이 되려면 2x-{linear_coefficient}=0이어야 하므로 x={answer_value}이다.",
                f"따라서 답은 {answer_value}이다.",
            ],
            solution_summary="도함수가 0이 되는 점을 찾으면 접선이 수평인 x값이 정해진다.",
        )

    def _build_probability_mcq(self, *, blueprint: ItemBlueprint, rng: Random) -> ToyItemSpec:
        digit_count = 4 + rng.randrange(2)
        digits = list(range(1, digit_count + 1))
        even_digits = [digit for digit in digits if digit % 2 == 0]
        correct_total = len(even_digits) * (digit_count - 1)
        correct_value = str(correct_total)
        choices, correct_index, choice_value = self._place_correct_choice(
            correct_value=correct_value,
            distractors=[correct_total - 3, correct_total - 1, correct_total + 2, correct_total + 4],
            item_no=blueprint.item_no,
        )
        digit_text = ", ".join(str(digit) for digit in digits)
        even_digit_text = ", ".join(str(digit) for digit in even_digits)
        return ToyItemSpec(
            stem=(
                f"숫자 {digit_text} 중 서로 다른 두 개를 골라 두 자리 자연수를 만든다. "
                "이때 짝수인 수의 개수는 얼마인가."
            ),
            rubric="일의 자리가 짝수여야 한다는 조건을 먼저 적용한 뒤 곱의 법칙을 쓴다.",
            choices=choices,
            final_answer=str(correct_index),
            correct_choice_index=correct_index,
            correct_choice_value=choice_value,
            solution_steps=[
                f"짝수인 수가 되려면 일의 자리는 {even_digit_text} 중 하나여야 한다.",
                f"일의 자리를 정한 뒤 십의 자리는 남은 {digit_count - 1}개 중 하나이므로 경우의 수는 {len(even_digits)}*{digit_count - 1}={correct_value}이다.",
                f"따라서 알맞은 선택지는 {correct_index}번 {choice_value}이다.",
            ],
            solution_summary="일의 자리 조건과 곱의 법칙을 차례로 적용하면 경우의 수를 센다.",
        )

    def _build_probability_short_answer(self, *, blueprint: ItemBlueprint, rng: Random) -> ToyItemSpec:
        toss_count = 3 + rng.randrange(4)
        answer_value = str(toss_count)
        return ToyItemSpec(
            stem=(
                f"동전을 {toss_count}번 던질 때 앞면이 정확히 한 번 나오는 경우의 수는 얼마인가."
            ),
            rubric="앞면이 나올 위치를 고르는 조합으로 경우의 수를 계산한다.",
            choices=[],
            final_answer=answer_value,
            correct_choice_index=None,
            correct_choice_value=None,
            solution_steps=[
                "앞면이 정확히 한 번 나오려면 앞면이 놓일 자리를 한 곳 정하면 된다.",
                f"{toss_count}개의 자리 중 한 곳을 고르는 경우의 수는 {answer_value}이다.",
                f"따라서 답은 {answer_value}이다.",
            ],
            solution_summary="정확히 한 번 나오는 경우는 앞면의 위치 선택으로 바로 센다.",
        )

    @staticmethod
    def _build_critique_report(solved: SolvedItem) -> CritiqueReport:
        if solved.draft.blueprint.format == ItemFormat.MULTIPLE_CHOICE:
            summary = "수학 내용은 타당하지만 stem 끝에 선택형 안내를 붙이면 읽는 흐름이 더 분명하다."
            findings = [
                CritiqueFinding(
                    severity=ValidationSeverity.WARNING,
                    message="선택형 문항이라는 지시가 stem 끝에 직접 드러나지 않는다.",
                    recommendation="stem 끝에 '가장 알맞은 것을 고르시오.'를 덧붙여 최종본을 정리한다.",
                    blocking=False,
                )
            ]
        else:
            summary = "수학 내용은 타당하지만 단답형 답의 형식을 stem에 명시하면 채점 기준이 더 선명하다."
            findings = [
                CritiqueFinding(
                    severity=ValidationSeverity.WARNING,
                    message="단답형 답의 형식이 stem에서 바로 드러나지 않는다.",
                    recommendation="stem 끝에 '답을 자연수로 쓰시오.'를 덧붙여 최종본을 정리한다.",
                    blocking=False,
                )
            ]
        return CritiqueReport(
            item_no=solved.draft.blueprint.item_no,
            summary=summary,
            findings=findings,
            requires_revision=True,
        )

    @staticmethod
    def _build_revised_solution(solved: SolvedItem) -> SolvedItem:
        if solved.draft.blueprint.format == ItemFormat.MULTIPLE_CHOICE:
            instruction = "가장 알맞은 것을 고르시오."
            summary_suffix = "선택형 안내를 stem 끝에 보강해 최종본으로 정리했다."
        else:
            instruction = "답을 자연수로 쓰시오."
            summary_suffix = "답 형식 안내를 stem 끝에 보강해 최종본으로 정리했다."

        revised_stem = solved.draft.stem.strip()
        if instruction not in revised_stem:
            revised_stem = f"{revised_stem} {instruction}"

        revised_draft = solved.draft.model_copy(update={"stem": revised_stem})
        return solved.model_copy(
            update={
                "draft": revised_draft,
                "solution_summary": f"{solved.solution_summary} {summary_suffix}",
            }
        )
