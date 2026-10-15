-- New-user design: does a NEW peptic ulcer diagnosis raise the 1-year risk of a
-- GI bleed, compared with matched people who never had an ulcer?
-- Fixes the two problems in 2026-10-07 / 2026-10-12:
--   1. Concept overlap: exposure uses ulcer codes that do NOT also mean a bleed
--      (e.g. "gastric ulcer with hemorrhage" is excluded); controls have no
--      ulcer code of any kind.
--   2. Time order: everyone gets an index date; outcome = GI bleed (any
--      192671 descendant) in the :outcome_days AFTER index; anyone with a bleed on
--      or before index is excluded.
-- Index date: exposed = first ulcer-only diagnosis; controls = one visit chosen
-- by a fixed hash (deterministic pseudo-random). Both need :washout_days of
-- observation before index (so the ulcer is new) and :outcome_days after (so a
-- bleed would be recorded). Both are set under sql_params in config.yaml.
-- Spark SQL dialect (runs via load_cohort() over CDR tables both locally and in AoU).
-- person_id is returned for matching in Spark only; it must never be printed/displayed.
WITH
pud_any AS (
  SELECT descendant_concept_id AS concept_id FROM concept_ancestor
  WHERE ancestor_concept_id = 4027663
),
gib_any AS (
  SELECT descendant_concept_id AS concept_id FROM concept_ancestor
  WHERE ancestor_concept_id = 192671
),
pud_only AS (
  SELECT p.concept_id FROM pud_any p LEFT ANTI JOIN gib_any g ON g.concept_id = p.concept_id
),
obs AS (
  SELECT person_id,
         observation_period_start_date AS obs_start,
         observation_period_end_date AS obs_end
  FROM observation_period
),
first_pud AS (
  SELECT co.person_id, MIN(co.condition_start_date) AS index_date
  FROM condition_occurrence co
  JOIN pud_only p ON p.concept_id = co.condition_concept_id
  GROUP BY co.person_id
),
ever_pud AS (
  SELECT DISTINCT co.person_id
  FROM condition_occurrence co
  JOIN pud_any p ON p.concept_id = co.condition_concept_id
),
exposed AS (
  SELECT f.person_id, CAST(f.index_date AS DATE) AS index_date, 1 AS exposed
  FROM first_pud f
  JOIN obs o ON o.person_id = f.person_id
   AND f.index_date >= date_add(o.obs_start, :washout_days)
   AND f.index_date <= date_sub(o.obs_end, :outcome_days)
),
controls AS (
  SELECT v.person_id,
         CAST(MIN_BY(v.visit_start_date, xxhash64(v.person_id, v.visit_occurrence_id)) AS DATE) AS index_date,
         0 AS exposed
  FROM visit_occurrence v
  JOIN obs o ON o.person_id = v.person_id
   AND v.visit_start_date >= date_add(o.obs_start, :washout_days)
   AND v.visit_start_date <= date_sub(o.obs_end, :outcome_days)
  LEFT ANTI JOIN ever_pud e ON e.person_id = v.person_id
  GROUP BY v.person_id
),
cohort AS (
  SELECT * FROM exposed UNION ALL SELECT * FROM controls
),
gib_events AS (
  SELECT co.person_id, co.condition_start_date AS d
  FROM condition_occurrence co
  JOIN gib_any g ON g.concept_id = co.condition_concept_id
),
flags AS (
  SELECT c.person_id,
         MAX(CASE WHEN g.d <= c.index_date THEN 1 ELSE 0 END) AS prior_bleed,
         MAX(CASE WHEN g.d > c.index_date AND g.d <= date_add(c.index_date, :outcome_days) THEN 1 ELSE 0 END) AS outcome
  FROM cohort c
  LEFT JOIN gib_events g ON g.person_id = c.person_id
  GROUP BY c.person_id
),
prior_visits AS (
  SELECT c.person_id, COUNT(v.visit_occurrence_id) AS n
  FROM cohort c
  LEFT JOIN visit_occurrence v ON v.person_id = c.person_id
   AND v.visit_start_date < c.index_date
   AND v.visit_start_date >= date_sub(c.index_date, :washout_days)
  GROUP BY c.person_id
)
SELECT
  p.person_id,
  p.gender_concept_id,
  COALESCE(p.race_concept_id, 0) AS race_concept_id,
  COALESCE(p.ethnicity_concept_id, 0) AS ethnicity_concept_id,
  year(c.index_date) - p.year_of_birth AS age_at_index,
  year(c.index_date) AS index_year,
  LN(1 + pv.n) AS log_prior_visits,
  c.exposed,
  f.outcome
FROM cohort c
JOIN person p ON p.person_id = c.person_id
JOIN flags f ON f.person_id = c.person_id
JOIN prior_visits pv ON pv.person_id = c.person_id
WHERE f.prior_bleed = 0
  AND p.gender_concept_id IS NOT NULL
  AND p.year_of_birth IS NOT NULL;
