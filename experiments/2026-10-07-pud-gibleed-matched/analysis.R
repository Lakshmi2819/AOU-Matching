#!/usr/bin/env Rscript
# Practice matched comparison: is a recorded GI bleed more common in people with
# a peptic ulcer than in matched people without one?
#   1. Cohort: how many people, how many exposed?
#   2. Balance: how do exposed/unexposed differ in birth year and gender?
#   3. Matching: 1:1 exact match on gender + birth-year band (base R, no deps).
#   4. Outcome: GI bleed risk in each matched group, paired risk difference,
#      McNemar test; crude (unmatched) risks for comparison.
# Row-level data stays in memory; only aggregates are printed. Any count between
# 1 and min_cell-1 is shown as "<min_cell" (AoU small-cell rule).
suppressPackageStartupMessages({ library(DBI); library(yaml) })
source("framework/shared/utilities.R")

args <- commandArgs(trailingOnly = TRUE)
cfg <- yaml::read_yaml(args[which(args == "--config") + 1])
min_cell <- cfg$min_cell %||% 20
band <- cfg$birth_band_years %||% 5
set.seed(cfg$seed %||% 42)

con <- pick_connection()
on.exit(try(DBI::dbDisconnect(con, shutdown = TRUE), silent = TRUE), add = TRUE)
dat <- DBI::dbGetQuery(con, paste(readLines(cfg$sql_file), collapse = "\n"))
# Query row order isn't guaranteed; sort so the seeded matching is reproducible.
dat <- dat[order(dat$person_id), ]

# --- small-cell-safe formatting ------------------------------------------------
small <- function(n) n > 0 & n < min_cell
fmt_n <- function(n) ifelse(small(n), sprintf("<%d", min_cell), format(n, big.mark = ","))
# A proportion is shown only if both its numerator and its complement are safe.
fmt_pct <- function(k, n) {
  if (small(k) || small(n - k)) return("suppressed")
  sprintf("%.1f%%", 100 * k / n)
}
smd <- function(x, g) {  # standardized mean difference, exposed vs unexposed
  a <- x[g == 1]; b <- x[g == 0]
  (mean(a) - mean(b)) / sqrt((var(a) + var(b)) / 2)
}
top_gender <- names(which.max(table(dat$gender_concept_id)))
balance <- function(d, label) {
  cat(sprintf("[match] %s balance: SMD(year_of_birth) = %.3f, SMD(most-common gender) = %.3f\n",
              label, smd(d$year_of_birth, d$exposed),
              smd(as.numeric(d$gender_concept_id == top_gender), d$exposed)))
}

# --- 1. cohort -----------------------------------------------------------------
n_exp <- sum(dat$exposed == 1); n_unexp <- sum(dat$exposed == 0)
cat(sprintf("[cohort] people with EHR conditions: %s\n", fmt_n(nrow(dat))))
cat(sprintf("[cohort] peptic ulcer (exposed): %s; unexposed: %s\n", fmt_n(n_exp), fmt_n(n_unexp)))
cat(sprintf("[cohort] mean year_of_birth: exposed %.1f, unexposed %.1f\n",
            mean(dat$year_of_birth[dat$exposed == 1]), mean(dat$year_of_birth[dat$exposed == 0])))

# --- 2/3. 1:1 exact matching within gender x birth-band strata -------------------
balance(dat, "before matching")
dat$stratum <- paste(dat$gender_concept_id, dat$year_of_birth %/% band)
pairs <- do.call(rbind, lapply(split(seq_len(nrow(dat)), dat$stratum), function(idx) {
  e <- idx[dat$exposed[idx] == 1]; u <- idx[dat$exposed[idx] == 0]
  k <- min(length(e), length(u))
  if (k == 0) return(NULL)
  # sample() on a length-1 vector would draw from 1:n, so index explicitly.
  data.frame(e = e[sample.int(length(e), k)], u = u[sample.int(length(u), k)])
}))
n_pairs <- nrow(pairs)
cat(sprintf("[match] 1:1 exact on gender + %d-year birth band: %s pairs; %s exposed unmatched\n",
            band, fmt_n(n_pairs), fmt_n(n_exp - n_pairs)))
balance(dat[c(pairs$e, pairs$u), ], "after matching")

# --- 4. outcome ----------------------------------------------------------------
crude_e <- sum(dat$outcome[dat$exposed == 1]); crude_u <- sum(dat$outcome[dat$exposed == 0])
cat(sprintf("[crude] GI bleed risk: exposed %s, unexposed %s\n",
            fmt_pct(crude_e, n_exp), fmt_pct(crude_u, n_unexp)))

ye <- dat$outcome[pairs$e]; yu <- dat$outcome[pairs$u]
k_e <- sum(ye); k_u <- sum(yu)
d_e <- sum(ye == 1 & yu == 0)  # discordant: only the exposed member bled
d_u <- sum(ye == 0 & yu == 1)  # discordant: only the matched control bled
cat(sprintf("[matched] GI bleed risk: exposed %s, matched unexposed %s\n",
            fmt_pct(k_e, n_pairs), fmt_pct(k_u, n_pairs)))
if (any(small(c(d_e, d_u, k_e, k_u, n_pairs - k_e, n_pairs - k_u)))) {
  cat("[matched] effect estimates suppressed: a contributing count is below min_cell\n")
} else {
  rd <- (d_e - d_u) / n_pairs
  se <- sqrt(d_e + d_u - (d_e - d_u)^2 / n_pairs) / n_pairs
  mc <- mcnemar.test(matrix(c(sum(ye & yu), d_u, d_e, sum(!ye & !yu)), 2))
  cat(sprintf("[matched] discordant pairs: exposed-only %s, control-only %s\n", fmt_n(d_e), fmt_n(d_u)))
  cat(sprintf("[matched] risk difference = %.2f pp (95%% CI %.2f to %.2f); risk ratio = %.2f\n",
              100 * rd, 100 * (rd - 1.96 * se), 100 * (rd + 1.96 * se), k_e / k_u))
  cat(sprintf("[matched] McNemar chi-sq = %.2f, p = %.4g\n", mc$statistic, mc$p.value))
}
