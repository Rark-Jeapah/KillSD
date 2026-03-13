"""Conditional-probability ratio family."""

from src.orchestrator.families.base import make_short_answer_family

FAMILY = make_short_answer_family(
    family_id="probability_conditional_ratio_short",
    topic="conditional_probability_table",
    answer_form="reduced_fraction",
    blueprint_item_no=24,
    objective="조건부확률 비율식을 직접 적용",
    skill_tags=("conditional_probability", "probability_ratio"),
    stem="사건 A, B에 대하여 P(A∩B)=4/15, P(B)=2/5 이다. P(A|B)를 기약분수로 구하시오.",
    final_answer="2/3",
    solution_steps=(
        "조건부확률의 정의에 따라 P(A|B)=P(A∩B)/P(B) 이므로 먼저 비율식을 그대로 쓴다.",
        "주어진 값을 대입하면 P(A|B)=(4/15)/(2/5) 이다.",
        "분수의 나눗셈은 역수를 곱하는 것이므로 (4/15)×(5/2)=20/30=2/3 이다.",
        "따라서 답은 2/3이다.",
    ),
    solution_summary="정의식 P(A|B)=P(A∩B)/P(B)에 값을 대입하면 P(A|B)=2/3 이다.",
    rubric="조건부확률의 정의 P(A|B)=P(A∩B)/P(B)를 그대로 적용한 뒤 기약분수로 정리한다.",
    matcher_moves=("conditional_probability_ratio",),
)
