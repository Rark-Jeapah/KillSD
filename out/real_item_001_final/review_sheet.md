# Human Review Sheet

## Item Snapshot
- item_id: `real_item_001`
- run_id: `real_item_001_final`
- item_no: `14`
- format: `multiple_choice`
- score: `3`

### Stem
매개변수 a에 대하여 곡선 y=x^3-6x^2+ax의 접선 기울기가 어떤 실수 x에서도 음수가 되지 않게 하려 한다. 이에 필요한 조건은?

### Choices
1. a \le 12
2. a=12
3. a \ge 3
4. a \ge 12
5. a \le 3

## Answer And Reasoning
- final_answer: `4`
- correct_choice_index: `4`
- correct_choice_value: `a \ge 12`

### Solution Steps
1. 접선 기울기가 항상 음수가 아니어야 하므로 모든 실수 x에 대해 y'=3x^2-12x+a \ge 0 이어야 한다.
2. 도함수 y'를 y'=3(x-2)^2+(a-12)로 고치면 최솟값은 x=2에서 a-12임을 바로 알 수 있다.
3. 전구간에서 0 이상이 되려면 최솟값 a-12가 0 이상이어야 하므로 a \ge 12이다.
4. 따라서 조건에 맞는 선택지는 4번 a \ge 12이다.

### Solution Summary
도함수를 완전제곱식으로 정리해 최솟값 조건을 읽으면 a \ge 12가 곧바로 나온다.

## Validation
- status: `pass`
- approval_status: `approved`

### Success Criteria
- mcq_answer_key_in_range: `pass`
- short_answer_form_constraint: `pass`
- no_internal_metadata_leak: `pass`
- no_placeholder_wording: `pass`
- solver_reasoning_explicit: `pass`
- distractors_non_trivial: `pass`
- core_validation_pass: `pass`

### Custom Checks
- mcq_answer_key_in_range: `pass` - 객관식이면 정답표가 1..5 범위의 index로 저장되어야 한다.
- short_answer_form_constraint: `pass` - 단답형이면 자연수 정답 형식 제약을 통과해야 한다.
- no_internal_metadata_leak: `pass` - 학생에게 노출되는 문항/풀이 텍스트에 내부 메타데이터가 새지 않아야 한다.
- no_placeholder_wording: `pass` - placeholder 문구나 '평가하는 모의 문항'류 문장을 포함하면 안 된다.
- solver_reasoning_explicit: `pass` - 풀이 설명은 단계별 추론을 명시적으로 드러내야 한다.
- distractors_non_trivial: `pass` - 오답 선지는 서로 구별되고, 실제 오개념에서 나온 비자명한 선택지여야 한다.
- core_validation_pass: `pass` - 코어 validator suite 결과가 PASS여야 한다.

### Regenerate Rule
- action: `keep`
- when: validation PASS and all custom checks pass
- next_step: freeze item.json/solution.json/validation.json/review_sheet.md/item.pdf as accepted bundle

## Reviewer Checklist
- [ ] 문항 조건이 실제 수학 문제로 자연스럽게 읽히는가?
- [ ] 정답 선지 외의 오답 선지 4개가 각각 그럴듯한 오개념을 반영하는가?
- [ ] 풀이 단계가 생략 없이 연결되고 계산 근거가 충분한가?
- [ ] 학생 노출 텍스트에 내부 메타데이터가 섞여 있지 않은가?

## Lineage
- item_blueprint / attempt 1 / status `succeeded` / output `art-b7f3ce6ffa0d`
- draft_item / attempt 1 / status `succeeded` / output `art-01207f6a1634`
- solve / attempt 1 / status `succeeded` / output `art-fcf35e82f09c`
- critique / attempt 1 / status `succeeded` / output `art-43f3b3c2035d`
- revise / attempt 1 / status `succeeded` / output `art-a57a4e13b080`
- validate / attempt 1 / status `succeeded` / output `art-e824b36fda38`
- render / attempt 1 / status `succeeded` / output `art-39a95a9c8b31`
