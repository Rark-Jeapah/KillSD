"""Sample-mean variance-scaling family."""

from src.orchestrator.families.base import make_multiple_choice_family

FAMILY = make_multiple_choice_family(
    family_id="probability_sample_mean_variance_scaling_mcq",
    topic="sample_mean_variance_scaling",
    blueprint_item_no=21,
    objective="표본평균과 선형변환의 분산을 계산",
    skill_tags=("sampling", "mean", "variance"),
    stem="숫자 1,3,5,7,9를 복원추출로 세 번 확인한 뒤 평균을 X̄라 한다. V(aX̄+6)=24일 때 양수 a를 구하는 선택형 문항이다.",
    choices=("1", "2", "3", "4", "5"),
    correct_choice_index=3,
    solution_steps=(
        "한 번의 추출값 X의 평균은 5, 분산은 8이다.",
        "세 번 복원추출한 평균 X̄에 대해 Var(X̄)=Var(X)/3=8/3이다.",
        "Var(aX̄+6)=a^2 Var(X̄)=24 이므로 a^2=9, 양수 a=3이다.",
        "3에 해당하는 선택지를 고른다.",
    ),
    solution_summary="원래 분산 8에서 표본평균의 분산을 8/3으로 줄인 뒤 선형변환 분산 공식을 적용하면 양수 a는 3이다.",
    rubric="원래 분포의 분산을 구하고, 표본평균의 분산 규칙과 선형변환 분산 공식을 차례로 적용한다.",
)
