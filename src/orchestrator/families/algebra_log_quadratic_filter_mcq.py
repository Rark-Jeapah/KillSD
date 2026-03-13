"""Log-equation quadratic-filter family."""

from src.orchestrator.families.base import (
    FamilyVariant,
    StaticFamilyTemplate,
    build_static_family,
)

FAMILY = build_static_family(
    StaticFamilyTemplate(
        family_id="algebra_log_quadratic_filter_mcq",
        supported_atom_topics=("log_equation_domain",),
        supported_answer_forms=("choice_index",),
        blueprint_item_no=8,
        objective="로그방정식 정리와 이차방정식 해 선택",
        base_skill_tags=("logarithm", "equation", "quadratic_filter"),
        rubric="로그를 합쳐 이차방정식으로 바꾼 뒤 정의역을 만족하는 해를 선택한다.",
        answer_type="choice_index",
        matcher_moves=("log_merge", "quadratic_filter", "choice_alignment"),
        preferred_atom_order=(
            "atom-991b78d60850",
            "atom-c2ed46456b9d",
            "atom-5d39a6b6e0f6",
        ),
        variants=(
            FamilyVariant(
                stem="다음 로그방정식 log_3(x-1)+log_3(x-4)=2를 만족시키는 실수 x는 무엇인가?",
                choices=(
                    "\\frac{5-3\\sqrt{5}}{2}",
                    "2",
                    "\\frac{5+3\\sqrt{5}}{2}",
                    "4",
                    "\\frac{7+3\\sqrt{5}}{2}",
                ),
                final_answer="3",
                solution_steps=(
                    "로그의 진수가 양수여야 하므로 x-1>0, x-4>0 이고 따라서 x>4이다.",
                    "두 로그를 합치면 log_3((x-1)(x-4))=2 이므로 (x-1)(x-4)=9이다.",
                    "전개하면 x^2-5x-5=0 이고 근의 공식으로 x=\\frac{5\\pm3\\sqrt{5}}{2} 를 얻는다.",
                    "이 중 x>4를 만족하는 것은 \\frac{5+3\\sqrt{5}}{2} 뿐이므로 정답은 3번이다.",
                ),
                solution_summary="로그를 하나로 합친 뒤 이차방정식의 두 근을 구하고 정의역 x>4 조건을 적용하면 \\frac{5+3\\sqrt{5}}{2}만 남는다.",
            ),
            FamilyVariant(
                stem="정의역 조건을 먼저 고려할 때 식 log_2(x-2)+log_2(x-5)=3에서 남는 해는?",
                choices=(
                    "\\frac{7-\\sqrt{41}}{2}",
                    "5",
                    "\\frac{7+\\sqrt{41}}{2}",
                    "6",
                    "\\frac{9+\\sqrt{41}}{2}",
                ),
                final_answer="3",
                solution_steps=(
                    "로그의 진수가 양수여야 하므로 x-2>0, x-5>0 이고 따라서 x>5이다.",
                    "두 로그를 합치면 log_2((x-2)(x-5))=3 이므로 (x-2)(x-5)=8이다.",
                    "정리하면 x^2-7x+2=0 이고 근의 공식으로 x=\\frac{7\\pm\\sqrt{41}}{2} 를 얻는다.",
                    "이 중 x>5를 만족하는 것은 \\frac{7+\\sqrt{41}}{2} 뿐이므로 정답은 3번이다.",
                ),
                solution_summary="로그를 하나로 묶어 x^2-7x+2=0을 만든 뒤 정의역 x>5를 적용하면 \\frac{7+\\sqrt{41}}{2}가 남는다.",
            ),
            FamilyVariant(
                stem="실수 x가 log_5(x-1)+log_5(x-6)=2를 만족한다. 조건을 모두 통과하는 값은 무엇인가?",
                choices=(
                    "\\frac{7-5\\sqrt{5}}{2}",
                    "6",
                    "\\frac{7+5\\sqrt{5}}{2}",
                    "7",
                    "\\frac{9+5\\sqrt{5}}{2}",
                ),
                final_answer="3",
                solution_steps=(
                    "로그의 진수가 양수여야 하므로 x-1>0, x-6>0 이고 따라서 x>6이다.",
                    "두 로그를 합치면 log_5((x-1)(x-6))=2 이므로 (x-1)(x-6)=25이다.",
                    "전개하면 x^2-7x-19=0 이고 근의 공식으로 x=\\frac{7\\pm5\\sqrt{5}}{2} 를 얻는다.",
                    "이 중 x>6를 만족하는 것은 \\frac{7+5\\sqrt{5}}{2} 뿐이므로 정답은 3번이다.",
                ),
                solution_summary="로그를 하나로 합쳐 x^2-7x-19=0을 만든 뒤 정의역 x>6를 적용하면 \\frac{7+5\\sqrt{5}}{2}가 정답이다.",
            ),
        ),
    )
)
