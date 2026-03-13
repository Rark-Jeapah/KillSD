"""Occupancy-counting family with adjacency restrictions."""

from src.orchestrator.families.base import make_short_answer_family

FAMILY = make_short_answer_family(
    family_id="probability_occupancy_adjacency_count_short",
    topic="occupancy_adjacency_count",
    answer_form="natural_number",
    blueprint_item_no=29,
    objective="인접 제한이 있는 분배를 문자열 경우의 수로 계산",
    skill_tags=("counting", "restricted_distribution", "encoding"),
    stem="일렬로 놓인 10개의 주머니에 서로 구별하지 않는 공 8개를 모두 넣는다. 각 주머니에는 최대 2개만 넣을 수 있고, 공이 1개인 주머니 수는 4 또는 6개이다. 또한 공이 2개인 주머니의 이웃 주머니에는 공이 들어 있지 않아야 할 때 가능한 분배 경우의 수를 구하는 단답형 문항이다.",
    final_answer="262",
    solution_steps=(
        "주머니 상태를 0,1,2로 이루어진 길이 10의 문자열로 바꾸면 합은 8이고, 2의 이웃은 반드시 0이어야 한다.",
        "1의 개수가 6이면 2의 개수는 1, 1의 개수가 4이면 2의 개수는 2뿐이다.",
        "한 개의 2가 있는 경우는 112개, 두 개의 2가 있는 경우는 150개이다. 이는 2의 위치를 고정하고 주변 강제 0을 반영해 남은 자리에 1을 배치하는 방법으로 센다.",
        "전체 경우의 수는 112+150=262이다.",
    ),
    solution_summary="제한 분배를 0,1,2 문자열 문제로 바꾸고 1의 개수에 따라 경우를 나누어 세면 전체 경우의 수는 262이다.",
    rubric="분배 조건을 문자열 상태로 번역한 뒤, 2가 만드는 강제 0을 반영해 남은 위치에 1을 배치하는 경우를 합산한다.",
)
