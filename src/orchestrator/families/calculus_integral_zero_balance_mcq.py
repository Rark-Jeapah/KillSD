"""Integral zero-balance family."""

from src.orchestrator.families.base import make_multiple_choice_family

FAMILY = make_multiple_choice_family(
    family_id="calculus_integral_zero_balance_mcq",
    topic="integral_zero_balance",
    blueprint_item_no=16,
    objective="정적분의 공통 구간을 제거해 양의 해를 고른다",
    skill_tags=("integral", "antiderivative", "root_filter"),
    stem="이차함수 f(x)=3x^2-16x-20에 대하여 ∫_{-2}^{a} f(x)dx = ∫_{-2}^{0} f(x)dx 를 만족하는 양수 a를 구하는 선택형 문항이다.",
    choices=("16", "14", "12", "10", "8"),
    correct_choice_index=4,
    solution_steps=(
        "두 적분의 시작점이 같으므로 ∫_0^a f(x)dx = 0 으로 바꾼다.",
        "F(x)=x^3-8x^2-20x 이므로 F(a)-F(0)=a(a^2-8a-20)=0 이다.",
        "a=0은 제외하고 a=10, -2 중 양수는 10이다.",
        "10에 해당하는 선택지를 고른다.",
    ),
    solution_summary="공통 시작점을 가진 두 적분을 ∫_0^a f(x)dx=0으로 줄이고 원시함수로 식을 세우면 양수해는 10뿐이다.",
    rubric="공통된 적분 구간을 제거해 식을 짧게 만든 뒤, 원시함수를 이용해 나온 해 중 조건에 맞는 양수만 남긴다.",
)
