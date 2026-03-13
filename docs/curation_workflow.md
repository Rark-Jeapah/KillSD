# Curation Workflow

This workflow is for manual curated-batch authoring. It deliberately avoids OCR, PDF ingestion, and any fake large corpus generation.

## 1. Initialize a batch

List starter templates:

```bash
python scripts/init_curated_batch.py --list-templates
```

Create a new batch from the empty template:

```bash
python scripts/init_curated_batch.py \
  --template empty \
  --batch-id 2028-algebra-draft-01 \
  --batch-version 2026.03.13 \
  --output-dir data/curated_batches/2028-algebra-draft-01
```

Create a new batch from a worked starter item:

```bash
python scripts/init_curated_batch.py \
  --template multiple_choice \
  --batch-id 2028-log-draft-01 \
  --batch-version 2026.03.13 \
  --output-dir data/curated_batches/2028-log-draft-01
```

The initializer writes:

- `<batch_id>.items.json`
- `<batch_id>.manifest.json`

The manifest hash and item count are computed automatically from the starter payload.

## 2. Author or edit items

Edit the generated `.items.json` file and replace template placeholders with real curated entries. Keep `source_item_id` stable when you revise an existing source item so conflict detection can spot multiple versions.

## 3. Validate before distillation

Run the authoring validator over one manifest or an entire directory tree:

```bash
python scripts/validate_curated_batches.py \
  --batch-path data/curated_batches
```

The validator reports:

- Manifest count/hash mismatches
- Malformed or semantically invalid items
- Duplicate batch identities
- Duplicate or conflicting `source_item_id` entries

Validation is intended to fail early before `distill run-batches`.

## 4. Inspect coverage gaps

Run the gap report on the same curated-batch tree:

```bash
python scripts/report_coverage_gaps.py \
  --batch-path data/curated_batches
```

The report summarizes:

- Counts by domain, topic, and answer form
- Curated atom coverage by real-item family
- Missing 2028 spec topic areas derived from canonical `skill_tags`
- Unsupported atoms and why they do not map to a family
- Duplicate/conflicting batch entries from the validation pass

Coverage counts are computed from the retained latest version of each `source_item_id`, so duplicate historical entries do not inflate the report.

## 5. Distill only after the batch tree is clean

Once validation and gap review look correct, distill the curated batches with the existing flow:

```bash
python -m src.cli.main distill run-batches \
  --batch-path data/curated_batches \
  --output-dir out/curated-distilled
```

If a batch is still empty, validation will warn, and distillation will still require at least one valid source item across the selected batch set.
