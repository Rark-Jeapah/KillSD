"""Derivative monotonicity via quadratic-vertex family."""

from src.orchestrator.families.base import (
    FamilyVariant,
    StaticFamilyTemplate,
    build_static_family,
)

FAMILY = build_static_family(
    StaticFamilyTemplate(
        family_id="calculus_derivative_vertex_mcq",
        supported_atom_topics=("derivative_monotonicity",),
        supported_answer_forms=("choice_index",),
        blueprint_item_no=14,
        objective="도함수의 부호와 꼭짓점 판단",
        base_skill_tags=("derivative", "monotonicity", "quadratic_vertex_check"),
        rubric="도함수를 완전제곱식으로 바꾸어 최솟값을 확인한 뒤 전구간 부호 조건을 판정한다.",
        answer_type="choice_index",
        preferred_atom_order=(
            "atom-f81b2ab6c767",
            "atom-d1170f7c15a9",
            "atom-f9684d631a8c",
            "atom-bb0d073139cc",
            "atom-1c4317d67e80",
        ),
        variants=(
            FamilyVariant(
                stem="실수 a에 따라 함수 h(x)=x^3-6x^2+ax의 접선 기울기가 모든 x에서 0 미만으로 떨어지지 않게 하려 한다. 이를 보장하는 a의 조건은?",
                choices=("a <= 12", "a = 12", "a >= 3", "a >= 12", "a <= 3"),
                final_answer="4",
                solution_steps=(
                    "접선 기울기가 항상 음수가 아니어야 하므로 모든 실수 x에 대해 y'=3x^2-12x+a >= 0 이어야 한다.",
                    "도함수 y'를 y'=3(x-2)^2+(a-12)로 고치면 최솟값은 x=2에서 a-12임을 바로 알 수 있다.",
                    "전구간에서 0 이상이 되려면 최솟값 a-12가 0 이상이어야 하므로 a >= 12이다.",
                    "따라서 조건에 맞는 선택지는 4번 a >= 12이다.",
                ),
                solution_summary="도함수를 완전제곱식으로 바꾸어 꼭짓점에서의 최솟값을 확인하면 전구간 비음수 조건은 a >= 12가 된다.",
            ),
            FamilyVariant(
                stem="실수 b에 대하여 함수 y=x^3-9x^2+bx가 전체 실수 범위에서 줄어드는 구간을 갖지 않으려면 b는 어떤 조건을 만족해야 하는가?",
                choices=("b = 27", "b <= 27", "b >= 18", "b <= 18", "b >= 27"),
                final_answer="5",
                solution_steps=(
                    "함수가 어느 구간에서도 감소하지 않으려면 모든 실수 x에 대해 y'=3x^2-18x+b >= 0 이어야 한다.",
                    "도함수를 y'=3(x-3)^2+(b-27)로 정리하면 최솟값은 x=3일 때의 b-27이다.",
                    "최솟값이 0 이상이어야 전구간에서 도함수가 음수가 되지 않으므로 b-27 >= 0, 즉 b >= 27이다.",
                    "따라서 정답은 5번 b >= 27이다.",
                ),
                solution_summary="도함수의 꼭짓점 값을 확인해 전구간 부호 조건을 읽으면 b >= 27이 된다.",
            ),
            FamilyVariant(
                stem="매개변수 c에 대하여 함수 y=x^3-12x^2+cx의 도함수가 모든 실수 x에서 음이 아니도록 할 때 c의 조건으로 옳은 것은?",
                choices=("c <= 48", "c >= 48", "c = 24", "c >= 24", "c <= 24"),
                final_answer="2",
                solution_steps=(
                    "도함수가 항상 음이 아니어야 하므로 모든 실수 x에 대해 y'=3x^2-24x+c >= 0 이어야 한다.",
                    "이를 y'=3(x-4)^2+(c-48)로 완전제곱식 형태로 쓰면 최소값은 x=4에서 c-48이다.",
                    "최솟값 c-48이 0 이상이어야 하므로 c >= 48이다.",
                    "따라서 조건에 맞는 선택지는 2번 c >= 48이다.",
                ),
                solution_summary="도함수를 3(x-4)^2+(c-48)로 정리하여 최소값을 보면 c >= 48임을 알 수 있다.",
            ),
            FamilyVariant(
                stem="매개변수 k에 대해 함수 g(x)=x^3-15x^2+kx의 접선 기울기가 모든 실수 x에서 음수가 되지 않도록 만들고자 한다. 가능한 k의 범위는?",
                choices=("k >= 75", "k = 75", "k <= 75", "k >= 50", "k <= 50"),
                final_answer="1",
                solution_steps=(
                    "전구간에서 감소하지 않으려면 모든 실수 x에 대해 y'=3x^2-30x+k >= 0 이어야 한다.",
                    "도함수를 y'=3(x-5)^2+(k-75)로 고치면 최솟값은 x=5에서 k-75이다.",
                    "따라서 최솟값이 0 이상이 되도록 k-75 >= 0, 즉 k >= 75가 필요하다.",
                    "그래서 정답은 1번 k >= 75이다.",
                ),
                solution_summary="도함수의 꼭짓점 x=5에서 최소값을 확인하면 전구간 비음수 조건은 k >= 75가 된다.",
            ),
            FamilyVariant(
                stem="매개변수 p에 대하여 함수 y=x^3-21x^2+px의 증가 조건을 조사한다. 도함수가 모든 실수 x에서 0 이상이 되려면 p는 어떤 조건을 만족해야 하는가?",
                choices=("p = 147", "p <= 147", "p >= 98", "p <= 98", "p >= 147"),
                final_answer="5",
                solution_steps=(
                    "도함수가 전구간에서 0 이상이어야 하므로 y'=3x^2-42x+p >= 0 가 모든 실수 x에 대해 성립해야 한다.",
                    "도함수를 y'=3(x-7)^2+(p-147)로 바꾸면 최솟값은 x=7에서 p-147이다.",
                    "최솟값이 0 이상이면 충분하고 필요하므로 p-147 >= 0, 즉 p >= 147이다.",
                    "따라서 조건을 만족하는 선택지는 5번 p >= 147이다.",
                ),
                solution_summary="도함수를 완전제곱식으로 나타내어 꼭짓점에서의 최소값을 확인하면 p >= 147이다.",
            ),
        ),
    )
)
