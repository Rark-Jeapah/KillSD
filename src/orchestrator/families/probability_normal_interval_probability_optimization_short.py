"""Normal-interval probability optimization family."""

from src.orchestrator.families.base import make_short_answer_family

FAMILY = make_short_answer_family(
    family_id="probability_normal_interval_probability_optimization_short",
    topic="normal_interval_probability_optimization",
    answer_form="natural_number",
    blueprint_item_no=30,
    objective="정규분포 구간 확률의 최댓값을 표준화로 계산",
    skill_tags=("normal_distribution", "standardization", "optimization"),
    stem="양수 t에 대해 X~N(1,t^2)라 하자. P(X≤5t)≥1/2를 만족시키는 t들 중에서 P(t^2-t+1 ≤ X ≤ t^2+t+1)가 최대가 되도록 하는 값을 표준정규분포표로 계산해 1000배한 수를 구하는 단답형 문항이다.",
    final_answer="673",
    solution_steps=(
        "정규분포의 중앙값은 평균 1이므로 P(X≤5t)≥1/2 는 5t≥1, 즉 t≥1/5 와 동치이다.",
        "P(t^2-t+1 ≤ X ≤ t^2+t+1)=P(t-1 ≤ Z ≤ t+1) 로 바뀐다.",
        "길이가 2인 구간이 0에 가장 가까울 때 확률이 최대이므로 허용범위의 최소 t=1/5에서 최대가 된다.",
        "P(-0.8≤Z≤1.2)=P(0≤Z≤0.8)+P(0≤Z≤1.2)=0.288+0.385=0.673이므로 답은 673이다.",
    ),
    solution_summary="조건 P(X≤5t)≥1/2 에서 t≥1/5를 얻고, 고정 길이 구간이 중심에 가장 가까운 t=1/5에서 확률을 계산하면 답은 673이다.",
    rubric="중앙값 조건으로 허용 범위를 먼저 정한 뒤, 표준화된 고정 길이 구간이 중심에 가장 가까울 때 확률이 최대라는 사실을 사용한다.",
)
