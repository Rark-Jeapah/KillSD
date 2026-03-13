# Curated Batch Schema

Curated-batch authoring uses two files:

- `*.manifest.json`: batch-level metadata and audit fields
- `*.items.json` or `*.items.jsonl`: manually authored source items

## Manifest fields

Required fields in `*.manifest.json`:

```json
{
  "manifest_version": "2.0",
  "spec_id": "csat_math_2028",
  "batch_id": "2028-algebra-draft-01",
  "batch_version": "2026.03.13",
  "created_at": "2026-03-13T00:00:00+00:00",
  "items_path": "2028-algebra-draft-01.items.json",
  "item_count": 0,
  "content_hash": "sha256:...",
  "provenance": {
    "exam_name": "CSAT Mathematics",
    "exam_year": 2028,
    "source_name": "manual_curation",
    "source_kind": "exam_analysis"
  },
  "metadata": {
    "authoring_status": "draft",
    "initialized_from_template": "empty"
  }
}
```

Notes:

- `item_count` may be `0` for a newly initialized draft batch.
- `content_hash` must match the canonical hash of the authored items payload.
- `items_path` may be relative to the manifest directory or absolute.

## Source item fields

Each entry in the items payload must satisfy the `ManualSourceItem` schema.

Core required fields:

- `source_item_id`
- `source_kind`
- `source_label`
- `subject_area`
- `topic`
- `item_format`
- `score`
- `difficulty`
- `stem`
- `answer`
- `solution_steps`

Important list fields:

- `subtopics`
- `choices`
- `distractors`
- `diagram_tags`
- `style_notes`
- `allowed_answer_forms`
- `trigger_patterns`

### Format rules

- `multiple_choice` items must provide exactly five `choices`.
- `short_answer` items must not provide `choices`.
- Authoring validation expects explicit `allowed_answer_forms`.
- Multiple-choice authoring validation expects `choice_index` in `allowed_answer_forms`.

### Solution-step rules

Each `solution_steps` entry must include:

- `step_id`
- `label`
- `kind`
- `content`
- `technique`

Recommended authoring practice:

- Keep `step_id` values unique.
- Only reference known step ids in `dependencies`.
- Use stable technique names because atom extraction and family matching depend on them.

## Validation and gap semantics

The authoring validator adds checks beyond the raw Pydantic schema:

- manifest hash/count integrity
- subject-area compatibility with the 2028 spec
- explicit answer-form metadata
- solution-graph dependency integrity
- duplicate/conflicting batch identities
- duplicate/conflicting `source_item_id` entries

The gap report derives "topic areas" from the canonical 2028 spec `skill_tags`. This is intentionally conservative: it reports missing skill-tag areas instead of claiming a full official taxonomy that is not encoded in this repository.
