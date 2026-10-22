#!/usr/bin/env Rscript
# MatchIt on the same real-data matching task as the BRPMatch benchmark
# (experiments/2026-10-22-brpmatch-realdata-scaling), for comparison.
#   1. Cohort: same SQL logic, run through pick_connection() (BigQuery in AoU,
#      DuckDB locally). Rare categories merged exactly as the Spark side does.
#   2. Runs: for each size in the ladder, keep person_id %% 100 < pct in each
#      group (the same rule BRPMatch uses, so both match identical people),
#      match with MatchIt (nearest, Mahalanobis, exact on gender), and report
#      match rate, max |SMD| (brpmatch's definition), and wall time.
# Row-level data stays in memory; only aggregates are printed. Participant
# counts from 1 to min_cell-1 are suppressed.
suppressPackageStartupMessages({ library(DBI); library(yaml); library(MatchIt) })
source("framework/shared/utilities.R")

args <- commandArgs(trailingOnly = TRUE)
cfg <- yaml::read_yaml(args[which(args == "--config") + 1])
min_cell <- cfg$min_cell %||% 20
exact_cols <- unlist(cfg$exact_match_cols)
num_cols <- unlist(cfg$numeric_cols)
cat_cols <- unlist(cfg$categorical_cols)
budget_min <- cfg$max_minutes_per_run %||% 120

small <- function(n) n > 0 & n < min_cell
fmt_n <- function(n) ifelse(small(n), sprintf("<%d", min_cell),
                            format(round(n), big.mark = ",", scientific = FALSE, trim = TRUE))

cat(sprintf("[env] %s; MatchIt %s; cores %d\n", R.version.string,
            as.character(packageVersion("MatchIt")), parallel::detectCores()))

# --- 1. cohort -------------------------------------------------------------------
sql <- paste(readLines(cfg$sql_file), collapse = "\n")
for (k in names(cfg$sql_params)) {
  sql <- gsub(sprintf("{%s}", k), as.character(as.integer(cfg$sql_params[[k]])), sql, fixed = TRUE)
}
con <- pick_connection()
on.exit(try(DBI::dbDisconnect(con, shutdown = TRUE), silent = TRUE), add = TRUE)
t0 <- Sys.time()
dat <- DBI::dbGetQuery(con, sql)
dat <- dat[order(dat$person_id), ]
dat$treat <- as.integer(dat$treatment)  # SQL column is "treatment": TREAT is reserved in BigQuery
for (c in num_cols) dat[[c]] <- as.numeric(dat[[c]])

# Merge categories with fewer than min_cell people in either group into
# "other" (same rule as the Spark side).
for (c in c(exact_cols, cat_cols)) {
  x <- as.character(dat[[c]])
  tab <- table(factor(x), factor(dat$treat, levels = 0:1))
  rare <- rownames(tab)[apply(tab, 1, min) < min_cell]
  x[x %in% rare] <- "other"
  dat[[c]] <- factor(x)
}
n_t_all <- sum(dat$treat == 1)
cat(sprintf("[cohort] treatment concept %s: %s treated, %s controls; loaded in %.0fs\n",
            cfg$sql_params$treatment_concept_id, fmt_n(n_t_all), fmt_n(nrow(dat) - n_t_all),
            as.numeric(difftime(Sys.time(), t0, units = "secs"))))

# One-hot features named like brpmatch's (col_level), for the balance table.
features <- function(d) {
  cols <- lapply(c(cat_cols, exact_cols), function(c) {
    m <- sapply(levels(d[[c]]), function(l) as.numeric(d[[c]] == l))
    m <- matrix(m, nrow = nrow(d))
    colnames(m) <- paste0(c, "_", levels(d[[c]]))
    m
  })
  cbind(do.call(cbind, cols), as.matrix(d[num_cols]))
}

# brpmatch's compute_smd(): (mean_t - mean_c) / sqrt((var_t + var_c) / 2), with
# the variances of the sample described (all people before; matched people,
# weighted, after).
smd <- function(X, treat, w = rep(1, length(treat))) {
  keep <- w > 0
  X <- X[keep, , drop = FALSE]; treat <- treat[keep]; w <- w[keep]
  apply(X, 2, function(x) {
    stat <- function(g) {
      xi <- x[treat == g]; wi <- w[treat == g]
      m <- sum(wi * xi) / sum(wi)
      v <- if (all(wi == 1)) stats::var(xi) else sum(wi * xi^2) / sum(wi) - m^2
      c(m, v)
    }
    st <- stat(1); sc <- stat(0)
    sd <- sqrt((st[2] + sc[2]) / 2)
    if (is.na(sd) || sd < 1e-10) 0 else (st[1] - sc[1]) / sd
  })
}

# --- 2. runs ---------------------------------------------------------------------
fml <- as.formula(paste("treat ~", paste(c(num_cols, cat_cols), collapse = " + ")))
exact <- if (length(exact_cols)) as.formula(paste("~", paste(exact_cols, collapse = " + "))) else NULL
last <- NULL
for (r in cfg$runs) {
  label <- sprintf("[run t%s%% c%s%%]", r$treated_pct, r$control_pct)
  keep <- (dat$treat == 1 & dat$person_id %% 100 < r$treated_pct) |
          (dat$treat == 0 & dat$person_id %% 100 < r$control_pct)
  d <- droplevels(dat[keep, ])
  n_t <- sum(d$treat == 1); n_c <- sum(d$treat == 0)

  if (!is.null(last)) {
    projected <- last$secs * (n_t * n_c) / (last$n_t * last$n_c) / 60
    if (projected > budget_min) {
      cat(sprintf("%s treated %s, controls %s: skipped, projected %.0f min > %d min budget\n",
                  label, fmt_n(n_t), fmt_n(n_c), projected, budget_min))
      next
    }
  }

  secs <- system.time(
    m <- matchit(fml, data = d, method = "nearest", distance = "mahalanobis",
                 exact = exact, ratio = cfg$ratio_k %||% 1,
                 replace = isTRUE(cfg$with_replacement))
  )[["elapsed"]]

  n_matched <- sum(m$weights[d$treat == 1] > 0)
  unmatched <- n_t - n_matched
  rate <- if (small(unmatched)) sprintf("all but <%d", min_cell) else
    sprintf("%.1f%% (%s unmatched)", 100 * n_matched / n_t, fmt_n(unmatched))
  X <- features(d)
  s_before <- smd(X, d$treat)
  s_after <- smd(X, d$treat, m$weights)
  worst <- names(which.max(abs(s_after)))
  cat(sprintf("%s treated %s, controls %s (1:%.1f); matched %s; max |SMD| %.3f -> %.3f (%s); match wall time %.0fs\n",
              label, fmt_n(n_t), fmt_n(n_c), n_c / max(n_t, 1), rate,
              max(abs(s_before)), max(abs(s_after)), worst, secs))
  last <- list(n_t = n_t, n_c = n_c, secs = max(secs, 0.01))
}
cat("[bench] DONE\n")
