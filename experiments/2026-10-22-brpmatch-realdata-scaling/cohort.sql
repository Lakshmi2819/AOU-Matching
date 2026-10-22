-- Real-data matching benchmark cohort for BRPMatch (no outcome).
-- One row per person with any condition record (EHR). treat = any record of
-- :treatment_concept_id or its descendants (default hypertension, 316866: a
-- common condition, so the treated group is large and the task is hard).
-- Covariates are real CDR features: gender, race, ethnicity, year of birth,
-- log(1 + visit count), log(1 + distinct condition concepts).
-- :population_pct keeps people with person_id mod 100 < pct (100 = all),
-- to shrink the whole task; per-run treated/control subsampling and the
-- rebucket threshold are in bench.py / config.yaml.
-- Spark SQL dialect (load_cohort() runs it over the CDR tables as Spark views:
-- BigQuery connector in AoU, DuckDB copy locally). Nothing goes through pandas.
-- person_id is returned for matching in Spark only; it must never be printed/displayed.
WITH
ehr AS (
  SELECT person_id, COUNT(DISTINCT condition_concept_id) AS n_conditions
  FROM condition_occurrence
  GROUP BY person_id
),
treated AS (
  SELECT DISTINCT co.person_id
  FROM condition_occurrence co
  JOIN concept_ancestor ca ON ca.descendant_concept_id = co.condition_concept_id
  WHERE ca.ancestor_concept_id = :treatment_concept_id
),
visits AS (
  SELECT person_id, COUNT(*) AS n_visits
  FROM visit_occurrence
  GROUP BY person_id
)
SELECT
  p.person_id,
  p.gender_concept_id,
  COALESCE(p.race_concept_id, 0) AS race_concept_id,
  COALESCE(p.ethnicity_concept_id, 0) AS ethnicity_concept_id,
  p.year_of_birth,
  LN(1 + COALESCE(v.n_visits, 0)) AS log_visits,
  LN(1 + e.n_conditions) AS log_conditions,
  CASE WHEN t.person_id IS NOT NULL THEN 1 ELSE 0 END AS treat
FROM person p
JOIN ehr e ON e.person_id = p.person_id
LEFT JOIN treated t ON t.person_id = p.person_id
LEFT JOIN visits v ON v.person_id = p.person_id
WHERE p.gender_concept_id IS NOT NULL
  AND p.year_of_birth IS NOT NULL
  AND pmod(p.person_id, 100) < :population_pct;
