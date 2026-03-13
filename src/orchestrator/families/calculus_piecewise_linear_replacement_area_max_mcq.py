"""Piecewise linear replacement area-maximum family."""

from src.orchestrator.families.base import make_multiple_choice_family

FAMILY = make_multiple_choice_family(
    family_id="calculus_piecewise_linear_replacement_area_max_mcq",
    topic="piecewise_linear_replacement_area_max",
    blueprint_item_no=18,
    objective="조각선 대체 뒤 넓이함수의 최댓값 계산",
    skill_tags=("integral", "area", "optimization"),
    stem="f(x)=x(x-6)(x-9)/9, 0<t<6. x<t에서는 g(x)=f(x), x≥t에서는 기울기 -1인 직선 y=-(x-t)+f(t)로 바꾼 함수 g를 만든다. g와 x축이 둘러싸는 넓이의 최댓값을 구하는 선택형 문항이다.",
    choices=("125/4", "127/4", "129/4", "131/4", "133/4"),
    correct_choice_index=3,
    solution_steps=(
        "0<t<6에서 f(t)>0이고, f는 x=0에서 x축과 만난다. 직선 부분은 x=t+f(t)에서 x축과 만난다.",
        "전체 넓이는 A(t)=∫_0^t f(x)dx + 1/2·{f(t)}^2 이다.",
        "A'(t)=0을 풀면 t=3이 내부 임계점이고, 이때 최대가 된다.",
        "A(3)=129/4 이므로 해당 선택지를 고른다.",
    ),
    solution_summary="오른쪽 대체 구간의 넓이를 삼각형으로 바꾸면 A(t)=∫_0^t f(x)dx + 1/2·{f(t)}^2가 되고, 최대값은 t=3에서 129/4이다.",
    rubric="절단점 뒤 직선이 만드는 도형 구조를 먼저 읽고, 적분 넓이와 삼각형 넓이를 합친 함수의 최대를 찾는다.",
)
