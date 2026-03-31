# Taxonomy Design

## Output Fields

- `category_id`: stable storage identifier such as `speed_limit` or `warning_general`.
- `category_label`: user-facing label, usually matching `category_id`.
- `specific_label`: optional more-specific label such as `stop`, `yield`, or `speed_limit_45`.
- `grouping_mode`: how the mapping was derived, for example `grouped`, `preserve_specific`, or `fallback_unknown`.

## Mapping Layer

The detector/classifier emits raw labels first, for example:

- `stop`
- `yield`
- `speed_limit_35`
- `warning_diamond`
- `mandatory_round`
- `prohibition_round`
- `crossing`

The taxonomy layer remaps those outputs using config in `pi/config/taxonomy.yaml`.

## Benefits

- Taxonomy changes do not require rebuilding the capture pipeline.
- Saved raw labels allow later replay and confusion analysis.
- Broad grouping and specific sign preservation can coexist.

