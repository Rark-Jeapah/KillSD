"""Sequential transfer process conditional-probability family."""

from src.orchestrator.families.base import make_multiple_choice_family

FAMILY = make_multiple_choice_family(
    family_id="probability_sequential_transfer_conditional_probability_mcq",
    topic="sequential_transfer_conditional_probability",
    blueprint_item_no=21,
    objective="시행 유형 압축으로 조건부확률을 계산",
    skill_tags=("probability", "conditional_probability", "process_modeling"),
    stem="복원추출로 확인한 카드값에 따라 상자 A의 공을 상자 B로 옮기는 시행을 4번 반복한다. 1이면 (흰1), 2 또는 3이면 (흰1, 검1), 4이면 (흰2, 검1)을 B에 넣는다. 4번 후 B의 총공 개수가 8개일 때, 검은 공이 2개일 조건부확률을 구하는 선택형 문항이다.",
    choices=("3/70", "2/35", "1/14", "3/35", "1/10"),
    correct_choice_index=4,
    solution_steps=(
        "한 번의 시행을 A형(총1, 검0), B형(총2, 검1), C형(총3, 검1)로 요약하면 확률은 각각 1/4, 1/2, 1/4이다.",
        "4회 시행에서 총공 수가 8이 되려면 (A,B,C)의 횟수는 (0,4,0), (1,2,1), (2,0,2) 세 경우뿐이다.",
        "검은 공이 2개가 되는 경우는 (2,0,2)뿐이다. 각 경우의 다항분포 확률을 계산해 조건부확률을 구하면 3/35이다.",
        "3/35에 해당하는 선택지를 고른다.",
    ),
    solution_summary="각 시행을 세 유형으로 압축하고 총공 수 8을 만드는 횟수 조합만 남기면 조건부확률은 3/35이다.",
    rubric="원래 시행을 몇 가지 결과 유형으로 압축한 뒤, 총량 조건을 만족하는 경우만 남겨 조건부확률의 분모와 분자를 계산한다.",
)
