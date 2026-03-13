"""Trigonometric parameter-maximum family."""

from src.orchestrator.families.base import make_multiple_choice_family

FAMILY = make_multiple_choice_family(
    family_id="algebra_trigonometric_parameter_maximum_mcq",
    topic="trigonometric_parameter_maximum",
    blueprint_item_no=10,
    objective="삼각함수의 최댓값 조건으로 파라미터를 결정",
    skill_tags=("trigonometry", "parameter", "periodicity"),
    stem="닫힌구간 [0, 2π]에서 정의된 함수 f(x)=a cos(bx)+3이 x=π/3에서 최댓값 13을 갖는다. 자연수 a, b에 대하여 a+b의 최솟값을 묻는 선택형 문항이다.",
    choices=("12", "14", "16", "18", "20"),
    correct_choice_index=3,
    solution_steps=(
        "최댓값이 13이므로 a+3=13, 따라서 a=10이다.",
        "a>0이므로 최댓값은 cos(bx)=1일 때 생긴다. 따라서 x=π/3에서 bπ/3=2kπ를 만족해야 한다.",
        "자연수 b의 최솟값은 6이므로 a+b=16이다.",
        "16에 해당하는 선택지를 고른다.",
    ),
    solution_summary="최댓값 13에서 a=10을 정하고, x=π/3에서 cos(bx)=1이 되도록 하는 최소 자연수 b=6을 찾으면 a+b=16이다.",
    rubric="최댓값으로 진폭을 정하고, 최댓점 조건에서 cos 값이 1이 되는 주기 조건을 사용해 자연수 파라미터를 고른다.",
)
