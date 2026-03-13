"""Integral extremum-count parameter family."""

from src.orchestrator.families.base import make_multiple_choice_family

FAMILY = make_multiple_choice_family(
    family_id="calculus_integral_extremum_parameter_mcq",
    topic="integral_extremum_parameter",
    blueprint_item_no=20,
    objective="적분함수의 극값 개수로 매개변수 범위를 결정",
    skill_tags=("integral", "parameter", "sign_chart"),
    stem="f(x)=-x^2 (x<0), f(x)=x^2-x (x≥0)이고, 양수 a에 대해 g(x)=ax+a (x<-1), 0 (-1≤x<1), ax-a (x≥1)라 하자. h(x)=∫_0^x (g(t)-f(t))dt가 극값을 정확히 하나만 갖게 하는 a의 최댓값을 k라 할 때, a=k에서 k+h(3)을 구하는 선택형 문항이다.",
    choices=("9/2", "11/2", "13/2", "15/2", "17/2"),
    correct_choice_index=4,
    solution_steps=(
        "h'(x)=g(x)-f(x) 이므로 극값 개수 문제는 구간별 h'의 부호 변화를 세는 문제로 바뀐다.",
        "-1<x<1에서는 h'(x)>0 이고, x≥1에서는 h'(x)=-(x-1)(x-a), x<-1에서는 h'(x)=x^2+ax+a 이다.",
        "오른쪽에서는 a>1일 때 x=a에서 한 번 극값이 생긴다. 왼쪽 이차식이 추가 극값을 만들지 않으려면 a≤4이어야 하므로 최대값은 k=4이다.",
        "a=4를 대입하면 h(3)=7/2이고, 따라서 k+h(3)=15/2이다.",
    ),
    solution_summary="극값 개수 조건을 h'(x)=g(x)-f(x)의 부호 변화 문제로 바꾸면 a의 최대는 4이고, 그때 k+h(3)=15/2이다.",
    rubric="적분함수의 극값 조건을 도함수 부호표 문제로 환원하고, 각 구간에서 추가 극값이 생기는 조건을 막아 매개변수를 결정한다.",
)
