-- One row per person with any condition record (a proxy for having EHR data,
-- so "no GI bleed" means "none recorded", not "no records at all").
--   exposed = any peptic ulcer record      (4027663 and descendants)
--   outcome = any GI hemorrhage record     (192671 and descendants)
-- Ever/never flags, not time-ordered: this is a practice association, not a
-- causal design. Concept ids are standard OMOP, so the same query runs on the
-- Eunomia fixture (DuckDB) and the AoU CDR (BigQuery).
-- person_id is returned for matching in R only; it must never be printed/displayed.
WITH has_ehr AS (
  SELECT DISTINCT person_id FROM condition_occurrence
),
pud AS (
  SELECT DISTINCT co.person_id
  FROM condition_occurrence co
  JOIN concept_ancestor ca ON ca.descendant_concept_id = co.condition_concept_id
  WHERE ca.ancestor_concept_id = 4027663
),
gib AS (
  SELECT DISTINCT co.person_id
  FROM condition_occurrence co
  JOIN concept_ancestor ca ON ca.descendant_concept_id = co.condition_concept_id
  WHERE ca.ancestor_concept_id = 192671
)
SELECT
  p.person_id,
  p.gender_concept_id,
  p.year_of_birth,
  CASE WHEN pud.person_id IS NOT NULL THEN 1 ELSE 0 END AS exposed,
  CASE WHEN gib.person_id IS NOT NULL THEN 1 ELSE 0 END AS outcome
FROM person p
JOIN has_ehr e ON e.person_id = p.person_id
LEFT JOIN pud ON pud.person_id = p.person_id
LEFT JOIN gib ON gib.person_id = p.person_id
WHERE p.gender_concept_id IS NOT NULL AND p.year_of_birth IS NOT NULL;
