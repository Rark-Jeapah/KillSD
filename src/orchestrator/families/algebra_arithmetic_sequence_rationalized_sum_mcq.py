"""Arithmetic-sequence rationalized-sum family."""

from src.orchestrator.families.base import make_multiple_choice_family

FAMILY = make_multiple_choice_family(
    family_id="algebra_arithmetic_sequence_rationalized_sum_mcq",
    topic="arithmetic_sequence_rationalized_sum",
    blueprint_item_no=9,
    objective="등차수열의 근호 합을 유리화와 망원합으로 계산",
    skill_tags=("sequence", "series", "rationalization"),
    stem="모든 항이 양수이고 첫째항과 공차가 같은 등차수열 {a_n}이 ∑_{k=1}^{15} 1/(√a_k+√a_{k+1}) = 2를 만족한다. 이때 a_4를 구하는 선택형 문항이다.",
    choices=("6", "7", "8", "9", "10"),
    correct_choice_index=4,
    solution_steps=(
        "첫째항과 공차가 같으므로 a_1=d=r>0, 따라서 a_k=kr이다.",
        "1/(√a_k+√a_{k+1})=(√(k+1)-√k)/√r 로 바꾼다.",
        "망원합으로 3/√r=2를 얻어 r=9/4, 따라서 a_4=4r=9이다.",
        "9에 해당하는 선택지를 고른다.",
    ),
    solution_summary="첫째항과 공차를 같은 r로 두고 근호식을 유리화해 망원합으로 정리하면 r=9/4, 따라서 a_4=9이다.",
    rubric="첫째항=공차 조건으로 일반항을 잡고, 근호 분모를 유리화해 망원합으로 정리한 뒤 필요한 항을 계산한다.",
)
