"""Relative-motion distance monotonicity family."""

from src.orchestrator.families.base import make_multiple_choice_family

FAMILY = make_multiple_choice_family(
    family_id="calculus_relative_motion_distance_monotonicity_mcq",
    topic="relative_motion_distance_monotonicity",
    blueprint_item_no=17,
    objective="상대위치와 실제 이동거리를 구분해 거리 증감을 해석",
    skill_tags=("integral", "relative_motion", "monotonicity"),
    stem="원점에서 동시에 출발한 두 점 P, Q의 속도가 각각 v1(t)=t^2-6t+5, v2(t)=2t-7이다. 두 점 사이 거리 f(t)가 [0,a]에서 증가, [a,b]에서 감소, [b,∞)에서 다시 증가한다. 이때 t=a부터 t=b까지 점 Q가 움직인 거리를 구하는 선택형 문항이다.",
    choices=("15/2", "17/2", "19/2", "21/2", "23/2"),
    correct_choice_index=2,
    solution_steps=(
        "두 점의 위치 차 D(t)=∫_0^t(v1-v2)du = t(t-6)^2/3 를 구한다.",
        "D(t)≥0 이므로 거리 f(t)=D(t)이고, D'(t)=v1-v2=(t-2)(t-6)에서 a=2, b=6을 얻는다.",
        "Q의 이동거리는 ∫_2^6 |2t-7|dt 이고, t=7/2에서 부호가 바뀌므로 값을 계산하면 17/2이다.",
        "17/2에 해당하는 선택지를 고른다.",
    ),
    solution_summary="상대위치 D(t)=t(t-6)^2/3에서 거리의 증감 구간이 a=2, b=6으로 정해지고, Q의 실제 이동거리는 절댓값 적분으로 17/2가 된다.",
    rubric="상대속도를 적분해 두 점 사이 거리를 만들고, 거리의 증감과 한 점의 실제 이동거리를 서로 다른 절댓값 문제로 처리한다.",
)
