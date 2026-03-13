"""Conditional-probability table family driven by conditioned counting."""

from src.orchestrator.families.base import (
    FamilyVariant,
    StaticFamilyTemplate,
    build_static_family,
)

FAMILY = build_static_family(
    StaticFamilyTemplate(
        family_id="probability_conditional_cases_short",
        supported_atom_topics=("conditional_probability_table",),
        supported_answer_forms=("reduced_fraction",),
        blueprint_item_no=23,
        objective="조건 사건 표 정리를 통한 조건부확률 계산",
        base_skill_tags=("conditional_probability", "sample_space_partition"),
        rubric="조건 사건에 해당하는 집단만 다시 모아 분모를 정하고, 그중 목표 집단의 수를 분자로 둔다.",
        answer_type="reduced_fraction",
        matcher_moves=("count_conditioned_cases", "condition_partition"),
        preferred_atom_order=(
            "atom-5480edcc0dcb",
            "atom-aaa349a7160b",
        ),
        variants=(
            FamilyVariant(
                stem="한 반 학생을 성별과 동아리 가입 여부에 따라 조사했더니 남학생은 가입 4명, 미가입 2명이고 여학생은 가입 6명, 미가입 3명이었다. 임의로 한 학생을 택했을 때 동아리 가입 학생이라는 조건 아래 여학생일 확률을 기약분수로 구하시오.",
                final_answer="3/5",
                solution_steps=(
                    "조건 사건이 동아리 가입 학생이므로 분모는 가입한 학생 전체인 4+6=10명이다.",
                    "이 가운데 여학생은 6명이므로 조건부확률의 분자는 6, 분모는 10이다.",
                    "정리하면 구하는 확률은 6/10=3/5 이므로 답은 3/5이다.",
                ),
                solution_summary="조건 사건인 가입 학생 10명을 분모로 두고 그중 여학생 6명을 세면 조건부확률은 3/5이다.",
            ),
            FamilyVariant(
                stem="학생들을 기숙사 거주 여부와 봉사활동 신청 여부에 따라 분류했더니 기숙사생은 신청 4명, 미신청 3명이고 통학생은 신청 3명, 미신청 5명이었다. 임의로 한 학생을 고를 때 봉사활동 신청 학생이라는 조건 아래 기숙사생일 확률을 기약분수로 구하시오.",
                final_answer="4/7",
                solution_steps=(
                    "조건 사건이 봉사활동 신청 학생이므로 분모는 신청한 학생 전체인 4+3=7명이다.",
                    "그중 기숙사생은 4명이므로 조건부확률은 4/7이다.",
                    "4와 7은 서로소이므로 이미 기약분수이며 답은 4/7이다.",
                ),
                solution_summary="조건 사건인 신청 학생 7명 가운데 기숙사생이 4명이므로 조건부확률은 4/7이다.",
            ),
        ),
    )
)
