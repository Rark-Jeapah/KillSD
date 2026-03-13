"""Log-equation domain-filter family."""

from src.orchestrator.families.base import make_multiple_choice_family

FAMILY = make_multiple_choice_family(
    family_id="algebra_log_domain_filter_mcq",
    topic="log_equation_domain",
    blueprint_item_no=7,
    objective="로그방정식 정의역과 해의 개수 판단",
    skill_tags=("logarithm", "equation", "domain_check"),
    stem="방정식 log_2(x-1)=log_2(7-x)-1의 실근의 개수는?",
    choices=("없음", "한 개", "두 개", "세 개", "네 개"),
    correct_choice_index=2,
    solution_steps=(
        "로그의 진수가 양수여야 하므로 x-1>0 이고 7-x>0 이다. 따라서 정의역은 1<x<7 이다.",
        "우변의 -1은 log_2(1/2) 이므로 log_2(7-x)-1=log_2((7-x)/2) 로 바꿀 수 있다.",
        "같은 밑의 로그가 같으므로 x-1=(7-x)/2 이고 정리하면 3x=9, 따라서 x=3 이다.",
        "얻은 해 x=3은 정의역 1<x<7을 만족하므로 실근의 개수는 한 개이다.",
        "따라서 정답은 2번 한 개이다.",
    ),
    solution_summary="정의역 1<x<7을 먼저 확정하고 같은 밑 로그식으로 바꾸어 얻은 해 x=3을 점검하면 실근은 한 개만 남는다.",
    rubric="양변의 로그 정의역을 먼저 세우고, 같은 밑 로그식으로 바꾼 뒤 얻은 해가 정의역에 들어가는지 확인한다.",
    matcher_moves=("domain_check",),
)
