"""Continuity-driven branch-selection family."""

from src.orchestrator.families.base import make_multiple_choice_family

FAMILY = make_multiple_choice_family(
    family_id="algebra_continuity_branch_selection_mcq",
    topic="continuity_branch_selection",
    blueprint_item_no=6,
    objective="연속성과 치역 조건으로 가지 함수를 결정",
    skill_tags=("function", "continuity", "branch_selection"),
    stem="연속함수 f가 모든 실수 x에 대해 (f(x)-1)(f(x)-x)(f(x)+x)=0을 만족하고, 최댓값이 1, 최솟값이 0이다. 이때 f(-4/3)+f(0)+f(1/2)를 구하는 선택형 문항이다.",
    choices=("1/2", "1", "3/2", "2", "5/2"),
    correct_choice_index=3,
    solution_steps=(
        "주어진 식은 (f(x)-1)(f(x)-x)(f(x)+x)=0 이므로 각 x에서 f(x)는 1, x, -x 중 하나이다.",
        "최솟값이 0이고 최댓값이 1이므로 음수값과 1보다 큰 값은 나올 수 없다. 따라서 |x|>1에서는 f(x)=1, |x|≤1에서는 연속성을 지키며 f(x)=|x|가 된다.",
        "f(-4/3)=1, f(0)=0, f(1/2)=1/2이므로 합은 3/2이다.",
        "3/2에 대응되는 선택지를 고른다.",
    ),
    solution_summary="가능한 함수값이 1, x, -x뿐이라는 사실과 치역·연속성 조건을 합치면 f(x)는 1 또는 |x|로 정해져 합이 3/2가 된다.",
    rubric="가능한 함수값 가지를 먼저 분해한 뒤, 최댓값·최솟값과 연속성 조건으로 실제 가지를 확정하고 값을 대입한다.",
)
