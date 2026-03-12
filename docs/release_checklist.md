# Release Checklist

릴리즈 직전에는 benchmark harness를 `release_smoke` dataset으로 최소 1회, PDF 배포 직전에는 `--compile-pdf` 옵션으로 1회 더 실행한다. 로그인 셸 PATH가 불완전한 환경에서는 `CSAT_XELATEX_PATH`에 절대경로를 설정해 XeLaTeX를 고정한다.

## Release Gates

- 구조 오류 0
- 정답 오류 0
- render 오류 0
- hard similarity collision 0
- seed 재현 가능
- artifact lineage 재현 가능
- manual/api 모드 동등성 확인

## Commands

```bash
.venv/bin/python scripts/run_benchmark.py
.venv/bin/python -m pytest tests/test_render_contracts.py tests/test_mcq_answer_key_format.py
.venv/bin/python scripts/run_benchmark.py --compile-pdf
CSAT_XELATEX_PATH=/absolute/path/to/xelatex .venv/bin/python scripts/run_benchmark.py --compile-pdf
```

## Audit Points

- benchmark report의 `attempts[*].scorecard.checks`가 모두 `passed=true`인지 확인
- `mode_comparisons[*].equivalent=true`인지 확인
- `reproducibility_reports[*].equivalent=true`인지 확인
- `attempts[*].cost_summary`에 prompt 수, 문자 수, latency가 기록됐는지 확인
- `attempts[*].scorecard.prompt_version_audit.passed=true`인지 확인
- `attempts[*].scorecard.artifact_audit.passed=true`인지 확인
- PDF 릴리즈 전 실행에서는 `render_result.documents[*].compiled=true`이고 `render_result.documents[*].pdf_path!=null`인지 확인
- PDF 릴리즈 전 실행에서는 각 `attempt_*/attempt_report.json`에서도 `render_result.documents[*].compiled=true`와 `pdf_path` 존재를 직접 확인
