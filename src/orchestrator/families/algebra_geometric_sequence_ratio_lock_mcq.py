"""Geometric-sequence ratio-lock family."""

from src.orchestrator.families.base import make_multiple_choice_family

FAMILY = make_multiple_choice_family(
    family_id="algebra_geometric_sequence_ratio_lock_mcq",
    topic="geometric_sequence_ratio_lock",
    blueprint_item_no=5,
    objective="간격이 같은 항 묶음으로 등비수열의 공비를 결정",
    skill_tags=("sequence", "geometric_sequence", "ratio"),
    stem="등비수열 {a_n}이 2(a_1+a_4+a_7)=a_4+a_7+a_10=6을 만족한다. 이때 a_10을 구하는 선택형 문항이다.",
    choices=("22/7", "24/7", "26/7", "30/7", "32/7"),
    correct_choice_index=2,
    solution_steps=(
        "a_1=A, r^3=u로 두면 a_4=Au, a_7=Au^2, a_10=Au^3이다.",
        "2A(1+u+u^2)=6, Au(1+u+u^2)=6이므로 u=2를 얻는다.",
        "A(1+2+4)=3이므로 A=3/7, 따라서 a_10=Au^3=(3/7)·8=24/7이다.",
        "24/7에 해당하는 선택지를 고른다.",
    ),
    solution_summary="세 칸 간격 항을 r^3=u로 묶고 두 등식을 비교하면 u=2, A=3/7이어서 a_10=24/7이 된다.",
    rubric="같은 간격으로 떨어진 항들을 r^3 치환으로 묶고, 두 식의 구조를 비교해 공비 정보를 잠근 뒤 원하는 항을 계산한다.",
)
