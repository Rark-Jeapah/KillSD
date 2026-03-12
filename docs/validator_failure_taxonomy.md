# Validator Failure Taxonomy

## Goal

The validator is now optimized to reject bad items, not to rubber-stamp borderline output.
Every failed check emits a canonical reason code, and every reason code has an expected failure level.

## Failure Levels

| Level | Meaning | Typical action |
| --- | --- | --- |
| `hard` | The item or set should be discarded. | `regenerate` |
| `soft` | The item is salvageable but not release-ready. | `revise` |

## Hard-Fail Codes

| Reason code | Trigger |
| --- | --- |
| `format.item_number_range` | Item number is outside the exam range. |
| `format.score_invalid` | Score bucket is not permitted by the exam spec. |
| `format.choice_count_invalid` | Multiple-choice item does not have exactly five options. |
| `format.mcq_answer_key_not_integer` | MCQ answer key is stored as a value or other non-index payload. |
| `format.short_answer_not_natural` | Short-answer response is not a positive integer. |
| `format.short_answer_choices_present` | Short-answer item still carries multiple-choice options. |
| `format.internal_metadata_leak` | Student-visible text leaks internal ids, schema tokens, or pipeline metadata. |
| `curriculum.domain_forbidden` | Blueprint domain is not one of the allowed subject areas. |
| `curriculum.forbidden_topic_detected` | Forbidden topics such as geometry, vector, or matrix appear in the content. |
| `curriculum.out_of_curriculum` | The item falls outside the allowed 2028 curriculum envelope. |
| `answer.choice_index_mismatch` | Final answer, choice index, and stored choice value disagree. |
| `answer.multiple_correct_candidates` | More than one answer can be correct, or the stem uses multi-answer wording. |
| `answer.reference_mismatch` | Candidate answer does not match the supplied reference answer. |
| `render.unbalanced_inline_math` | Inline math delimiters are broken. |
| `render.unbalanced_braces` | Brace structure is broken. |
| `render.missing_diagram_asset` | Referenced diagram asset is missing. |
| `render.invalid_diagram_asset` | Referenced diagram asset exists but is malformed or empty. |
| `render.diagram_irrelevant_to_stem` | Diagram asset tags do not match the stem/objective. |
| `render.latex_compile_failed` | LaTeX dry-run fails. |
| `difficulty.variance_too_flat` | A set of difficulty estimates is unnaturally flat. |
| `similarity.surface_too_high` | Surface overlap crosses the hard threshold. |
| `similarity.expression_too_high` | Expression overlap crosses the hard threshold. |
| `similarity.solution_graph_too_high` | Solution-graph overlap crosses the hard threshold. |

## Soft-Fail Codes

| Reason code | Trigger |
| --- | --- |
| `format.distractor_too_obvious` | One or more distractors are giveaway wording rather than plausible math errors. |
| `curriculum.allowed_topic_miss` | Item is in-scope but weakly anchored to known allowed topics. |
| `answer.cross_check_disagreement` | Independent solver disagrees with the candidate answer. |
| `difficulty.band_mismatch` | Proxy difficulty drifts away from the blueprint target band. |
| `similarity.surface_too_high` | Surface overlap crosses the soft threshold but not the hard threshold. |
| `similarity.expression_too_high` | Expression overlap crosses the soft threshold but not the hard threshold. |
| `similarity.solution_graph_too_high` | Solution-graph overlap crosses the soft threshold but not the hard threshold. |

## Informational Codes

| Reason code | Meaning |
| --- | --- |
| `validator.no_findings` | The suite had to insert a placeholder finding because no validator emitted checks. |
| `answer.reference_not_available` | No external reference answer was available. |
| `render.latex_compile_ok` | LaTeX dry-run succeeded or was skipped cleanly. |

## Summary Format

Per-item validation summaries now encode:

- outcome (`Pass`, `Needs revision`, `Rejected`)
- failed-check count
- `hard` and `soft` fail counts
- affected validator modules
- exact failed reason codes

Example:

`Rejected: 2 failing checks (hard=2, soft=0) across 2 validators. Validators: answer_validator, format_validator. Reason codes: answer.choice_index_mismatch, format.mcq_answer_key_not_integer.`
